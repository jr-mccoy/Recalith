#!/usr/bin/env python3
"""Measure the preview worker's typed-state latency, start cost and idle footprint (ACCEPTANCE_TESTS §7).

    python tools/measure_worker_latency.py [--trials 100] [--start-trials 30] [--idle-seconds 600] \
        [--output docs/measurements/worker-typed-state-latency.json]

* ``typed_state``: a real Claude Code 2.1.301 prompt payload is captured by a
  fresh ``python -I -m recalith.fast.entry`` process at a uniformly random
  moment of an *idle* worker's 5-second poll cycle. Latency runs from the
  hook's acknowledgment (process exit, after durable publication) to the
  event being committed with its ``ingest`` job completed, observed from a
  separate read-only connection polling every 10 ms. ``from_hook_spawn`` adds
  the hook's own run time. Preview target: p95 ≤ 5 s (no IPC wake).
* ``hook_with_worker_start`` versus ``hook_worker_running``: hook wall time
  (spawn to exit) when the hook starts the worker and when it finds one
  running. The hook never waits for the worker to come up.
* ``idle``: CPU time and resident memory of an idle worker over the window
  (Linux ``/proc``, macOS ``ps``, Windows ``GetProcessTimes`` and
  ``K32GetProcessMemoryInfo``; anything else reports unavailable). Targets:
  < 1 % of one core over 10 idle minutes, ≤ 150 MiB resident.

The worker is the real process started by the hook's registered start path.
The OS page cache is not dropped. Nothing here involves a model provider.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests" / "platform"), str(ROOT / "tests")]

import claude_fixtures as cf  # noqa: E402
import worker_hosts as wh  # noqa: E402
from recalith.controller import worker  # noqa: E402
from recalith.fast import process_env, spool  # noqa: E402
from recalith.storage import db  # noqa: E402


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def summarize(samples: list[float], unit: str = "s") -> dict:
    scale = 1000 if unit == "ms" else 1
    xs = [s * scale for s in samples]
    return {"n": len(xs), "unit": unit, "p50": round(percentile(xs, 0.5), 3), "p95": round(percentile(xs, 0.95), 3), "p99": round(percentile(xs, 0.99), 3), "max": round(max(xs), 3), "mean": round(statistics.fmean(xs), 3)}


def run_hook(replayer: cf.Replay, data: bytes, event: str, tmp: Path) -> tuple[dict, float]:
    reply = tmp / f"reply-{time.monotonic_ns()}.json"
    proc, wall = cf.run_hook(replayer.root, data, event=event, reply=reply)
    if proc.returncode != 0:
        raise SystemExit(f"hook failed: {proc.stderr[-500:]!r}")
    return json.loads(reply.read_text(encoding="utf-8")), wall


def available(root: Path, event_id: str) -> bool:
    ctx = cf.identity.resolve_installation(root, actor=cf.ADAPTER_ACTOR)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        if view.execute("SELECT 1 FROM events WHERE event_id = ?", (event_id,)).fetchone() is None:
            return False
        return view.execute("SELECT 1 FROM jobs WHERE kind = 'ingest' AND state = 'completed' AND body LIKE ?", (f"%{event_id}%",)).fetchone() is not None


class Observer:
    """Measurement-only timeline, sampled every 10 ms from outside the worker: each status write the worker
    makes (its poll index, start, step offsets and the sleep before it) and, per trial, when the hook's segment
    appeared in and left ``spool/ready``, when its event row appeared and when its ingest job completed. All
    times are wall-clock seconds (``time.time()``), the clock the worker's ``last_poll_wall`` uses."""

    def __init__(self, root: Path, interval: float = 0.01) -> None:
        self.root, self.interval = root, interval
        self.dirs = spool.SpoolDirs(root)
        self.polls: dict[int, dict] = {}
        # In WAL mode only a checkpoint writes the main database file, so a change of its size or mtime marks one.
        self.store_file = Path(root) / ".recalith" / db.STATE_DB
        self.store_sig: tuple | None = None
        self.checkpoints: list[dict] = []
        self.write_failures = 0
        self.trial: dict | None = None
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> "Observer":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop.set()
        self.thread.join(5)

    def begin(self, trial: int) -> dict:
        with self.lock:
            self.trial = {"trial": trial, "segments_before": {p.name for p in spool.ready_segments(self.dirs)}, "segment": None, "event_id": None}
            return self.trial

    def end(self) -> dict:
        with self.lock:
            done, self.trial = self.trial, None
            return done or {}

    def _status(self, now: float) -> None:
        st = worker.read_status(self.root)
        if not st:
            return
        poll, counters = st.get("poll") or {}, st.get("counters") or {}
        index = counters.get("polls")
        if not isinstance(index, int) or index in self.polls:
            return
        if st.get("last_error") == "status_write_failed":
            self.write_failures += 1
        self.polls[index] = {"poll": index, "started_wall": poll.get("last_poll_wall"), "status_seen_wall": round(now, 4), "worked": poll.get("last_poll_worked"),
                             "interval": poll.get("interval_seconds"), "state": st.get("state"), "segments_total": counters.get("segments"),
                             "previous_poll_seconds": poll.get("last_poll_seconds"), "timing": poll.get("timing"), "last_error": st.get("last_error"),
                             "errors": counters.get("errors")}

    def _store_file(self, now: float) -> None:
        st = os.stat(self.store_file)
        sig = (st.st_size, st.st_mtime_ns)
        if self.store_sig is not None and sig != self.store_sig:
            try:
                wal = os.stat(f"{self.store_file}-wal").st_size
            except OSError:
                wal = None
            self.checkpoints.append({"seen_wall": round(now, 4), "mtime_wall": round(st.st_mtime_ns / 1e9, 4), "db_bytes": st.st_size, "wal_bytes": wal})
        self.store_sig = sig

    def _trial(self, now: float) -> None:
        with self.lock:
            t = self.trial
            if t is None:
                return
            names = {p.name for p in spool.ready_segments(self.dirs)} - t["segments_before"]
            if t["segment"] is None and names:
                t["segment"], t["segment_visible_wall"] = sorted(names)[0], round(now, 4)
            elif t["segment"] is not None and "segment_gone_wall" not in t and t["segment"] not in names:
                t["segment_gone_wall"] = round(now, 4)
            event_id = t.get("event_id")
        if event_id is None or "ingest_completed_wall" in t:
            return
        ctx = cf.identity.resolve_installation(self.root, actor=cf.ADAPTER_ACTOR)
        with db.open_store(ctx, readonly=True) as store, store.read() as view:
            if "event_row_wall" not in t and view.execute("SELECT 1 FROM events WHERE event_id = ?", (event_id,)).fetchone() is not None:
                t["event_row_wall"] = round(time.time(), 4)
            if "event_row_wall" in t and view.execute("SELECT 1 FROM jobs WHERE kind = 'ingest' AND state = 'completed' AND body LIKE ?", (f"%{event_id}%",)).fetchone() is not None:
                t["ingest_completed_wall"] = round(time.time(), 4)

    def _run(self) -> None:
        while not self.stop.is_set():
            now = time.time()
            try:
                self._status(now)
                self._store_file(now)
                self._trial(now)
            except (OSError, ValueError, db.sqlite3.Error):
                pass  # a busy file or snapshot is retried on the next sample
            self.stop.wait(self.interval)


def poll_rows(polls: dict[int, dict], since: float, until: float) -> list[dict]:
    """Polls that started in [since, until], with their step offsets and the sleep before each."""
    return [p for _i, p in sorted(polls.items()) if isinstance(p.get("started_wall"), float) and since <= p["started_wall"] <= until]


def idle_status(root: Path) -> dict | None:
    s = worker.read_status(root)
    return s if s and s["state"] == "idle" and not s["poll"]["last_poll_worked"] else None


def _ps(pid: int) -> tuple[float, float] | None:
    """macOS/BSD: (cpu seconds, rss MiB) from ``ps`` (cumulative CPU time ``[dd-]hh:mm:ss.cc``)."""
    import subprocess

    try:
        out = subprocess.run(["ps", "-o", "time=,rss=", "-p", str(pid)], capture_output=True, text=True, timeout=10, check=False).stdout.split()
        clock, rss = out[0], int(out[1])
    except (OSError, IndexError, ValueError):
        return None
    days, _, rest = clock.rpartition("-")
    parts = [float(x) for x in rest.split(":")]
    seconds = sum(v * 60 ** i for i, v in enumerate(reversed(parts))) + (int(days) * 86400 if days else 0)
    return seconds, rss / 1024


def _windows(pid: int) -> tuple[float, float] | None:  # pragma: no cover - native Windows
    """Windows: (cpu seconds, working set MiB) from ``GetProcessTimes`` and ``K32GetProcessMemoryInfo``."""
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000 | 0x0010, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            return None
        cpu = sum(((t.dwHighDateTime << 32) | t.dwLowDateTime) for t in times[2:]) / 1e7
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        if not kernel32.K32GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        return cpu, counters.WorkingSetSize / (1024 * 1024)
    finally:
        kernel32.CloseHandle(handle)


def proc_cpu_seconds(pid: int) -> float | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()
        return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
    except (OSError, IndexError, ValueError):
        pass
    other = _windows(pid) if os.name == "nt" else _ps(pid)
    return None if other is None else other[0]


def proc_rss_mib(pid: int) -> float | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except (OSError, ValueError):
        pass
    other = _windows(pid) if os.name == "nt" else _ps(pid)
    return None if other is None else other[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--start-trials", type=int, default=30)
    parser.add_argument("--idle-seconds", type=int, default=600)
    parser.add_argument("--seed", type=int, default=4)
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "measurements" / "worker-typed-state-latency.json")
    args = parser.parse_args(argv)
    rng = random.Random(args.seed)
    tmp = Path(tempfile.mkdtemp(prefix="recalith-worker-latency-"))
    replayer = cf.Replay(tmp / "replay")
    wh.enable_autostart(replayer)
    start_record = wh.start_record()
    report: dict = {
        "measurement": "preview worker typed-state latency (idle 5 s polling, no IPC), hook start cost, idle footprint",
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host_fixture_version": cf.VERSION,
        "environment": {"platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version(), "logical_cpus": os.cpu_count(), "os_page_cache": "not dropped"},
        "command": "python tools/measure_worker_latency.py " + " ".join(sys.argv[1:] if argv is None else argv),
    }
    try:
        # Hook cost when it starts the worker versus when one is running.
        # A hook short on time sheds the worker step (deadline_worker_start_skipped) and the next hook
        # retries it (SYSTEM_SPEC §5.1.1); those outcomes are counted, never asserted away.
        with_start, running = [], []
        start_states: dict[str, int] = {}
        running_states: dict[str, int] = {}
        for i in range(args.start_trials):
            wh.stop_worker(replayer.root)
            (Path(process_env.run_dir(replayer.root)) / process_env.START_STAMP).unlink(missing_ok=True)
            for _attempt in range(3):
                reply, wall = run_hook(replayer, replayer.prepare(start_record), start_record["event"], tmp)
                start_states[reply["worker"]] = start_states.get(reply["worker"], 0) + 1
                if reply["worker"] == "worker_started":
                    with_start.append(wall)
                    break
            else:
                raise SystemExit(f"three hooks never started the worker: {reply}")
            assert wh.wait_running(replayer.root), "worker never came up"
            reply, wall = run_hook(replayer, wh.unique_prompt(replayer, 10_000 + i), "UserPromptSubmit", tmp)
            running_states[reply["worker"]] = running_states.get(reply["worker"], 0) + 1
            running.append(wall)
        report["hook_with_worker_start"] = {**summarize(with_start, "ms"), "worker_states": start_states}
        report["hook_worker_running"] = {**summarize(running, "ms"), "worker_states": running_states}
        status = wh.wait_running(replayer.root)
        report["spawn"] = status["spawn"]
        # Typed-state latency at random idle phases. The observer timestamps every worker poll and, per trial,
        # segment visibility, the event row and the ingest job's completion, so each trial can be attributed.
        latencies, from_spawn, series = [], [], []
        with Observer(replayer.root) as observer:
            previous_done = 0.0
            for trial in range(args.trials):
                settled = wh.wait_for(lambda: idle_status(replayer.root), 60)
                assert settled, "worker never returned to idle"
                phase = rng.uniform(0, settled["poll"]["idle_seconds"])
                target = settled["poll"]["last_poll_wall"] + phase
                while target < time.time() + 0.15:
                    target += settled["poll"]["idle_seconds"]
                time.sleep(max(0.0, target - time.time()))
                record = observer.begin(trial)
                data = wh.unique_prompt(replayer, trial)
                spawned_wall = time.time()
                reply, wall = run_hook(replayer, data, "UserPromptSubmit", tmp)
                acked_wall = spawned_wall + wall
                with observer.lock:
                    record["event_id"] = reply["receipt"]["event_ids"][0]
                if not wh.wait_for(lambda record=record: "ingest_completed_wall" in record, 30, interval=0.01):
                    raise SystemExit(f"trial {trial} never reached typed state")
                record = observer.end()
                done_wall = record["ingest_completed_wall"]
                latencies.append(done_wall - acked_wall)
                from_spawn.append(done_wall - spawned_wall)
                series.append({"trial": trial, "phase_s": round(phase, 3), "from_hook_ack_s": round(done_wall - acked_wall, 3), "hook_wall_s": round(wall, 3),
                               "settled_poll": (settled.get("counters") or {}).get("polls"), "settled_poll_wall": settled["poll"]["last_poll_wall"],
                               "settled_after_previous_trial": settled["poll"]["last_poll_wall"] > previous_done, "arrival_target_wall": round(target, 4),
                               "hook_spawn_wall": round(spawned_wall, 4), "hook_ack_wall": round(acked_wall, 4),
                               **{k: record.get(k) for k in ("segment_visible_wall", "segment_gone_wall", "event_row_wall", "ingest_completed_wall")}})
                previous_done = done_wall
            time.sleep(6.5)  # the polls after the last trial, so its ingesting poll's successor is on record
        for row in series:
            row["polls"] = poll_rows(observer.polls, row["settled_poll_wall"] - 0.01, row["ingest_completed_wall"] + 0.01)
            row["store_file_writes"] = [c for c in observer.checkpoints if row["hook_spawn_wall"] - 0.01 <= c["mtime_wall"] <= row["ingest_completed_wall"] + 0.01]
        report["typed_state"] = {"from_hook_ack": summarize(latencies), "from_hook_spawn": summarize(from_spawn), "target_p95_seconds": 5.0, "met": percentile(latencies, 0.95) <= 5.0, "idle_poll_seconds": 5, "arrivals": "uniform random phase of the idle cycle", "series": series,
                                 "observer": {"interval_seconds": observer.interval, "polls_observed": len(observer.polls), "status_write_failures_seen": observer.write_failures, "store_file_writes": observer.checkpoints,
                                              "poll_indices": [min(observer.polls, default=None), max(observer.polls, default=None)]},
                                 "poll_timeline": [observer.polls[i] for i in sorted(observer.polls)]}
        # Idle footprint.
        settled = wh.wait_for(lambda: idle_status(replayer.root), 60)
        pid = settled["pid"]
        cpu0, t0 = proc_cpu_seconds(pid), time.monotonic()
        time.sleep(args.idle_seconds)
        cpu1, t1 = proc_cpu_seconds(pid), time.monotonic()
        if cpu0 is None or cpu1 is None:
            report["idle"] = {"state": "unavailable", "reason": "no process accounting (procfs, ps or the Windows process API) on this platform"}
        else:
            share = (cpu1 - cpu0) / (t1 - t0) * 100
            rss = proc_rss_mib(pid)
            report["idle"] = {"accounting": "procfs" if Path(f"/proc/{pid}/stat").exists() else ("windows_process_api" if os.name == "nt" else "ps"), "window_seconds": round(t1 - t0, 1), "cpu_percent_of_one_core": round(share, 4), "cpu_target_percent": 1.0, "cpu_met": share < 1.0, "rss_mib": None if rss is None else round(rss, 1), "rss_target_mib": 150, "rss_met": rss is not None and rss <= 150}
    finally:
        wh.stop_worker(replayer.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("hook_with_worker_start", "hook_worker_running", "typed_state", "idle")}, indent=2))
    return 0 if report["typed_state"]["met"] else 1


if __name__ == "__main__":
    sys.exit(main())
