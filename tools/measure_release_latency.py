#!/usr/bin/env python3
"""The preview hook latency and usefulness gate on this platform (ACCEPTANCE_TESTS §7; Task 18; decision 0020).

    python tools/measure_release_latency.py [--warm 500] [--cold 500] [--first-launch 50] [--faults 100] \
        [--corpus 10000] [--output FILE]

Every trial is a **fresh interpreter process** running the hook exactly as the
launcher does (``python -I -m recalith.fast.entry``; fault regimes use
``tools/fixtures/hook_fault.py``, which arms one failpoint in that fresh
process and then runs the same entry), fed a real Claude Code 2.1.301
payload variant through the specified caps, against an installation with
10,000 corpus claim heads, an admitted lesson and a controlled delivery
manifest (no host reads the output: this is local compile and emission, not a
delivery certification).

Healthy populations (the gate, per platform):

* ``warm`` — current views; alternating pre-action (a caution) and prompt
  (context) trials. Target p95 ≤ 300 ms, p99 ≤ 750 ms, healthy eligible
  delivery ≥ 99 %, degradation ≤ 1 %.
* ``cold_missing`` — no packet cache (every view deleted; the worker's
  pre-rendered fallback rows and its prompt lookup rows kept, decision 0021):
  the hook reads at most 32 fallback rows, plus for a prompt at most 16
  lookup rows through bounded postings, and filters them live with the
  stdlib. Target p95 ≤ 300 ms, p99 ≤ 750 ms, delivery ≥ 95 %,
  degradation ≤ 5 %.

Usefulness counts a trial *eligible-delivered* only when the expected lesson
or fact text is in the emitted packet; missing content, an empty fallback, a
downgrade or a skipped delivery is *degraded* and reported, never hidden in
the latency counts. Separately reported populations: ``stale`` (views behind
the guidance epoch), ``first_launch`` (the first hook of a new installation,
the engine's bytecode cache state recorded), and the fault-injection cases
``busy_writer`` (a process holding the store's write lock and committing
repeatedly), ``concurrent_hooks`` (four hooks at once), ``slow_fsync``
(30 ms added to every spool fsync) and ``windows_transient_rename`` (one
sharing violation on the spool rename; Windows only). Fault populations test
safe behavior and are never mixed into the healthy gate.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "tests" / "integration"), str(ROOT / "tests" / "platform"), str(ROOT / "tools")]

import measure_hook_latency as mhl  # noqa: E402

FAULT = ROOT / "tools" / "fixtures" / "hook_fault.py"
TARGETS = {"warm": {"p95_ms": 300, "p99_ms": 750, "delivery_min": 0.99, "degradation_max": 0.01}, "cold_missing": {"p95_ms": 300, "p99_ms": 750, "delivery_min": 0.95, "degradation_max": 0.05}}
LESSON_MARK = "test_mid"
FACT_MARK = "sqlite connection"


def run_trial(root: Path, data: bytes, event: str, reply: Path, *, fault: str | None = None) -> dict:
    import claude_fixtures as cf

    if fault is None:
        argv = [sys.executable, "-I", "-m", "recalith.fast.entry", "--project", str(root), "claude_code", "--event", event, "--reply-file", str(reply)]
    else:
        argv = [sys.executable, "-I", str(FAULT), fault, "--project", str(root), "claude_code", "--event", event, "--reply-file", str(reply)]
    started = time.perf_counter()
    proc = subprocess.run(argv, input=data, capture_output=True, env=cf.child_env(), timeout=60, check=False)
    wall = time.perf_counter() - started
    try:
        body = json.loads(reply.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        body = {"delivery": {"state": "no_reply"}, "degradations": ["no_reply"]}
    finally:
        reply.unlink(missing_ok=True)
    return {"wall": wall, "rc": proc.returncode, "stderr": proc.stderr[-300:].decode("utf-8", "replace"), "reply": body, "stdout": proc.stdout}


def classify(result: dict, expect: str | None) -> tuple[bool, bool]:
    """(eligible content delivered, degraded) for one trial."""
    reply = result["reply"]
    delivery = reply.get("delivery") or {}
    state = delivery.get("state")
    text = result["stdout"].decode("utf-8", "replace")
    delivered = state == "emitted" and (expect is None or expect in text)
    bad = set(delivery.get("degraded") or []) - {"view_stale", "view_missing"}
    degraded = (not delivered) or bool(bad) or state in ("skipped", "fenced_out", "uncertain") or result["rc"] != 0
    return delivered, degraded


def population(results: list[dict], expects: list[str | None], events: list[str] | None = None) -> dict:
    walls = [r["wall"] for r in results]
    inner = [r["reply"].get("elapsed_ms", 0) / 1000 for r in results]
    states: dict[str, int] = {}
    reasons: dict[str, int] = {}
    delivered = degraded = 0
    examples = []
    for r, expect in zip(results, expects, strict=True):
        ok, bad = classify(r, expect)
        delivered += ok
        degraded += bad
        state = (r["reply"].get("delivery") or {}).get("state", "?")
        states[state] = states.get(state, 0) + 1
        for reason in set((r["reply"].get("delivery") or {}).get("degraded") or []) | set(r["reply"].get("degradations") or []):
            reasons[reason] = reasons.get(reason, 0) + 1
        if bad and len(examples) < 5:
            examples.append({"state": state, "degraded": (r["reply"].get("delivery") or {}).get("degraded"), "degradations": r["reply"].get("degradations"), "rc": r["rc"], "stderr": r["stderr"][-120:], "expected": expect, "stdout_head": r["stdout"][:600].decode("utf-8", "replace")})
    n = len(results)
    by_event: dict = {}
    for r, expect, event in zip(results, expects, events or [None] * n, strict=True):
        ok, bad = classify(r, expect)
        slot = by_event.setdefault(event or "?", {"n": 0, "eligible_delivered": 0, "degraded": 0})
        slot["n"] += 1
        slot["eligible_delivered"] += ok
        slot["degraded"] += bad
    # Per-trial series in trial order (ms), so a tail can be told apart from a burst.
    series = {"wall_ms": [round(w * 1000, 1) for w in walls], "entry_ms": [round(x * 1000, 1) for x in inner]}
    return {"n": n, "by_event": by_event, "wall_spawn_to_exit": mhl.summarize(walls), "entry_to_exit": mhl.summarize(inner), "delivery_states": states, "reasons": reasons, "series": series,
            "eligible_delivered": delivered, "eligible_delivered_rate": round(delivered / n, 4) if n else None, "degraded": degraded, "degraded_rate": round(degraded / n, 4) if n else None,
            "degraded_examples": examples}


def windows(series: dict, size: int = 50) -> list:
    """Per consecutive window of ``size`` trials: wall and hook-internal p95 and max (ms), so a tail reads as a burst or a spread from the log alone."""
    walls, inner = series.get("wall_ms") or [], series.get("entry_ms") or []
    out = []
    for start in range(0, len(walls), size):
        w, e = sorted(walls[start:start + size]), sorted(inner[start:start + size])
        pick = lambda xs: xs[min(len(xs) - 1, int(0.95 * len(xs)))] if xs else None  # noqa: E731
        out.append({"from": start, "wall_p95": pick(w), "wall_max": w[-1] if w else None, "entry_p95": pick(e), "entry_max": e[-1] if e else None})
    return out


def verdict(name: str, pop: dict) -> dict:
    t = TARGETS[name]
    wall = pop["wall_spawn_to_exit"]
    checks = {"p95": wall["p95_ms"] <= t["p95_ms"], "p99": wall["p99_ms"] <= t["p99_ms"], "delivery": (pop["eligible_delivered_rate"] or 0) >= t["delivery_min"],
              # A rate of 0.0 is a measured zero, not a missing value (``or`` would read it as 100 %).
              "degradation": pop["degraded_rate"] is not None and pop["degraded_rate"] <= t["degradation_max"]}
    return {"targets": t, "checks": checks, "met": all(checks.values())}


def drop_views(root: Path) -> None:
    """A missing packet cache: every pre-serialized view is gone; the bounded fallback rows the worker also publishes stay."""
    db = root / ".recalith" / "state" / "memory.sqlite"
    conn = sqlite3.connect(db, timeout=5)
    try:
        conn.execute("DELETE FROM context_views WHERE purpose != 'fallback'")
        # The hook never reads projection_state; resetting it makes the next publish rebuild the views.
        conn.execute("UPDATE projection_state SET views_store_revision = -1, views_guidance_epoch = -1")
        conn.commit()
    finally:
        conn.close()


class BusyWriter:
    """Another process holds the store's write lock in short bursts and commits continuously (a worker under load)."""

    def __init__(self, root: Path) -> None:
        code = (
            "import sqlite3, sys, time\n"
            "conn = sqlite3.connect(sys.argv[1], timeout=5, isolation_level=None)\n"
            "while True:\n"
            "    conn.execute('BEGIN IMMEDIATE')\n"
            "    conn.execute(\"UPDATE retention_state SET report = report WHERE singleton = 1\")\n"
            "    time.sleep(0.05)\n"
            "    conn.execute('COMMIT')\n"
            "    time.sleep(0.005)\n"
        )
        self.proc = subprocess.Popen([sys.executable, "-I", "-c", code, str(root / ".recalith" / "state" / "memory.sqlite")])

    def stop(self) -> None:
        self.proc.kill()
        self.proc.wait(timeout=30)


def environment() -> dict:
    facts = {"platform": platform.platform(), "system": platform.system(), "machine": platform.machine(), "python": platform.python_version(), "python_build": " ".join(platform.python_build()),
             "logical_cpus": os.cpu_count(), "sqlite": sqlite3.sqlite_version, "os_page_cache": "not dropped (a fresh process is not a cold OS disk cache)",
             "ci": bool(os.environ.get("GITHUB_ACTIONS")), "runner": os.environ.get("RUNNER_OS")}
    try:
        facts["cpu_model"] = next((ln.split(":", 1)[1].strip() for ln in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines() if ln.startswith("model name")), None)
    except OSError:
        facts["cpu_model"] = platform.processor() or None
    return facts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--warm", type=int, default=500)
    parser.add_argument("--cold", type=int, default=500)
    parser.add_argument("--stale", type=int, default=100)
    parser.add_argument("--first-launch", type=int, default=50)
    parser.add_argument("--faults", type=int, default=100)
    parser.add_argument("--corpus", type=int, default=10_000)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    import consolidation_scenarios as cs
    import delivery_scenarios as ds
    import retrieval_scenarios as rs

    report: dict = {"tool": "tools/measure_release_latency.py", "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "environment": environment(),
                    "command": "python tools/measure_release_latency.py " + " ".join(sys.argv[1:] if argv is None else argv), "populations": {}, "gate": {}}
    tmp = Path(tempfile.mkdtemp(prefix="recalith-release-latency-"))
    try:
        p, _ids = ds.project(tmp / "main")
        fact = cs.fact(p, "The fixture teardown must close the sqlite connection.", subject="teardown sqlite")
        if args.corpus:
            rs.corpus(p, fact, args.corpus, proposition="Corpus {i}: deployment notes for the staging bucket and cache warmup.")
        rs.publish(p)
        ds.enable(p)
        reply = tmp / "reply.json"
        counter = iter(range(10**9))

        def pre(session: str | None = None) -> tuple[bytes, str, str]:
            i = next(counter)
            rec = ds.call_records(ds.MID, f"rl{i:06d}", session=session or f"00000000-0000-4000-8101-{i:012d}")[0]
            return p.replay.prepare(rec), rec["event"], LESSON_MARK

        def prompt() -> tuple[bytes, str, str]:
            i = next(counter)
            rec = ds.wks.variant(ds.record("UserPromptSubmit"), session=f"00000000-0000-4000-8102-{i:012d}", prompt=f"How should the fixture teardown close the sqlite connection before test_mid? #{i}")
            return p.replay.prepare(rec), rec["event"], FACT_MARK

        def regime(n: int, make, *, fault: str | None = None) -> dict:
            results, expects, events = [], [], []
            for k in range(n):
                data, event, expect = make(k)
                results.append(run_trial(p.root, data, event, reply, fault=fault))
                expects.append(expect)
                events.append(event)
            return population(results, expects, events)

        def prompt_or_pre(k: int) -> tuple[bytes, str, str]:
            return pre() if k % 2 == 0 else prompt()

        # Healthy gate populations.
        report["populations"]["warm"] = regime(args.warm, prompt_or_pre)
        report["gate"]["warm"] = verdict("warm", report["populations"]["warm"])
        drop_views(p.root)
        report["populations"]["cold_missing"] = regime(args.cold, prompt_or_pre)
        report["gate"]["cold_missing"] = verdict("cold_missing", report["populations"]["cold_missing"])
        rs.publish(p)
        # Stale views: a later fact moves the guidance epoch.
        cs.fact(p, "A later fact moves the guidance epoch.", subject="later")
        report["populations"]["stale"] = regime(args.stale, prompt_or_pre)
        rs.publish(p)
        # Fault injection (separate populations).
        busy = BusyWriter(p.root)
        try:
            time.sleep(0.3)
            report["populations"]["busy_writer"] = regime(args.faults, prompt_or_pre)
        finally:
            busy.stop()
        rounds = max(1, args.faults // 4)
        conc, cexp, cev = [], [], []
        with ThreadPoolExecutor(max_workers=4) as pool:
            for r in range(rounds):
                items = [prompt_or_pre(k) for k in range(4)]
                futures = [pool.submit(run_trial, p.root, d, e, tmp / f"reply-{r}-{k}.json") for k, (d, e, _x) in enumerate(items)]
                conc += [f.result() for f in futures]
                cexp += [x for _d, _e, x in items]
                cev += [e for _d, e, _x in items]
        report["populations"]["concurrent_hooks"] = {**population(conc, cexp, cev), "concurrency": 4, "rounds": rounds}
        report["populations"]["slow_fsync"] = {**regime(args.faults, prompt_or_pre, fault="slow_fsync"), "injected": "30 ms added to every spool fsync"}
        if os.name == "nt":
            report["populations"]["windows_transient_rename"] = {**regime(args.faults, prompt_or_pre, fault="transient_rename"), "injected": "one ERROR_SHARING_VIOLATION on the spool rename (winerror 32)"}
        else:
            report["populations"]["windows_transient_rename"] = {"state": "not_applicable", "reason": "POSIX rename has no transient sharing violation; measured on native Windows runners"}
        # First launches: the first hook of a new installation (bytecode state recorded).
        firsts, fexp, fev, cache = [], [], [], []
        for k in range(args.first_launch):
            q, _ = ds.project(tmp / f"first-{k}")
            rec = ds.call_records(ds.MID, f"first{k:04d}", session=f"00000000-0000-4000-8103-{k:012d}")[0]
            cache.append(any((ROOT / "src" / "recalith" / "fast" / "__pycache__").glob("*.pyc")))
            firsts.append(run_trial(q.root, q.replay.prepare(rec), rec["event"], tmp / "reply-first.json"))
            fexp.append(LESSON_MARK)
            fev.append(rec["event"])
            shutil.rmtree(tmp / f"first-{k}", ignore_errors=True)
        report["populations"]["first_launch"] = {**population(firsts, fexp, fev), "engine_bytecode_cache_present": sum(cache), "note": "first hook of a new installation in a fresh interpreter; the OS cache state is not controlled"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    report["gate"]["met"] = all(v["met"] for v in report["gate"].values() if isinstance(v, dict))
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    summary = {name: {k: pop.get(k) for k in ("n", "eligible_delivered_rate", "degraded_rate", "reasons", "by_event")}
               | {"p95_ms": (pop.get("wall_spawn_to_exit") or {}).get("p95_ms"), "p99_ms": (pop.get("wall_spawn_to_exit") or {}).get("p99_ms"),
                  "entry_p95_ms": (pop.get("entry_to_exit") or {}).get("p95_ms"), "windows": windows(pop.get("series") or {})}
               for name, pop in report["populations"].items() if "n" in pop}
    print(json.dumps({"environment": report["environment"]["platform"], "gate": report["gate"], "summary": summary}, indent=1, sort_keys=True))
    return 0 if report["gate"]["met"] else 1


if __name__ == "__main__":
    sys.exit(main())
