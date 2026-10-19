"""Native worker lifecycle: registered hook start, role environments, detachment (A45, A67, A73).

These tests run real processes on the native platform: the real hook entry
(``python -I -m recalith.fast.entry``) on real Claude Code 2.1.301 payloads,
the worker it starts through the registered internal start path, and a
simulated host that is terminated the way a host session ends. Nothing here
fakes a detached pass: survival is checked by continued ingestion after the
host's whole process group (POSIX) or kill-on-close Job Object (Windows) is
gone, and an unavailable variant is skipped with its reason.
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import claude_fixtures as cf
import worker_hosts as wh
from recalith.controller import worker
from recalith.fast import entry, process_env
from recalith.storage import db

INSTALLATION = "inst_12121212-1212-4121-8121-121212121212"
# Names the operating system itself adds to every new process (never inherited through the allowlist).
OS_INJECTED = {"__CF_USER_TEXT_ENCODING"} if sys.platform == "darwin" else set()


@pytest.fixture
def started(request):
    """Roots whose workers must be stopped at teardown, even when the test fails."""
    roots: list[Path] = []
    yield roots
    leftovers = []
    for root in roots:
        if not wh.stop_worker(root):
            leftovers.append(str(root))
    assert not leftovers, f"workers did not stop on request and were killed: {leftovers}"


@pytest.fixture
def replay(tmp_path, started):
    replayer = cf.Replay(tmp_path / "replay")
    wh.enable_autostart(replayer)
    started.append(replayer.root)
    return replayer


def events_and_done(root: Path) -> tuple[int, int, int]:
    ctx = cf.identity.resolve_installation(root, actor=cf.ADAPTER_ACTOR)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        events = view.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        done = view.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'ingest' AND state = 'completed'").fetchone()[0]
        open_jobs = view.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'ingest' AND state != 'completed'").fetchone()[0]
    return events, done, open_jobs


def event_available(root: Path, event_id: str) -> bool:
    ctx = cf.identity.resolve_installation(root, actor=cf.ADAPTER_ACTOR)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        if view.execute("SELECT 1 FROM events WHERE event_id = ?", (event_id,)).fetchone() is None:
            return False
        return view.execute("SELECT 1 FROM jobs WHERE kind = 'ingest' AND state = 'completed' AND body LIKE ?", (f"%{event_id}%",)).fetchone() is not None


def start_with_hooks(replayer, tmp_path, *, env=None) -> list[str]:
    """Hooks (SessionStart, then prompts) until one starts the worker; shedding under deadline pressure is allowed."""
    records = iter([wh.start_record()] + [wh.prompt_record()] * 4)
    statuses = wh.start_via_hook(lambda: hook(replayer, next(records), tmp_path, env=env)[0]["worker"])
    assert statuses[-1] == "worker_started" and set(statuses[:-1]) <= {"deadline_worker_start_skipped"}, statuses
    return statuses


def hook(replayer, record, tmp_path, *, env=None, data=None, name="reply"):
    reply_path = tmp_path / f"{name}-{time.monotonic_ns()}.json"
    proc, wall = cf.run_hook(replayer.root, data if data is not None else replayer.prepare(record), event=record["event"], reply=reply_path, env=env)
    assert proc.returncode == 0 and proc.stdout == b"" and proc.stderr == b"", proc.stderr[-2000:]
    return json.loads(reply_path.read_text(encoding="utf-8")), wall


# ---------------------------------------------------------------------------
# Fresh role environments (A67 hook→worker hop; DATA_CONTRACTS §2.3)


def test_hook_spawn_clears_host_markers():
    secret = "ghp_" + "Z" * 36
    inherited = {
        "PATH": "/usr/bin", "LANG": "C.UTF-8", "HOME": "/home/agent", "CLAUDECODE": "1", "CLAUDE_CODE_CHILD_SESSION": "1",
        "RECALITH_WORKER_INSTALLATION": "inst_99999999-9999-4999-8999-999999999999", "RECALITH_CURATOR_INSTALLATION": "inst_x", "RECALITH_FOO": "bar",
        "GITHUB_TOKEN": secret, "TZ": secret,
    }
    snapshot = dict(inherited)
    # An allowlist mistake that names markers cannot carry them through.
    manifest = process_env.role_manifest(INSTALLATION, purpose="worker", route_keys=["CLAUDECODE"], platform="posix")
    manifest["platform_keys"] += ["CLAUDE_CODE_CHILD_SESSION", "RECALITH_FOO", "RECALITH_WORKER_INSTALLATION"]
    env, report = process_env.spawn_environment_report(manifest, inherited, purpose="worker", platform="posix")
    assert env == {"PATH": "/usr/bin", "LANG": "C.UTF-8", "RECALITH_WORKER_INSTALLATION": INSTALLATION}
    assert inherited == snapshot  # the caller's map is never mutated
    assert report["removed_allowlisted_markers"] == ["CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "RECALITH_FOO", "RECALITH_WORKER_INSTALLATION"]
    assert report["dropped_secret_shaped"] == ["TZ"]  # a platform key never carries a credential
    assert secret not in json.dumps(report)  # names only
    # The curator role gets its own marker; the worker's is gone.
    curator = process_env.spawn_environment(process_env.role_manifest(INSTALLATION, purpose="curator", platform="posix"), {**inherited, "RECALITH_WORKER_INSTALLATION": INSTALLATION}, purpose="curator")
    assert curator.get("RECALITH_CURATOR_INSTALLATION") == INSTALLATION and "RECALITH_WORKER_INSTALLATION" not in curator
    # Windows names are case-insensitive: lower-case markers are removed too, required OS keys kept.
    win = process_env.spawn_environment_report(
        process_env.role_manifest(INSTALLATION, purpose="worker", route_keys=["claudecode"], platform="nt"),
        {"SystemRoot": r"C:\Windows", "Path": r"C:\Windows\System32", "claudecode": "1", "USERPROFILE": r"C:\Users\agent"},
        purpose="worker", platform="nt",
    )[0]
    assert win == {"SYSTEMROOT": r"C:\Windows", "PATH": r"C:\Windows\System32", "RECALITH_WORKER_INSTALLATION": INSTALLATION}
    # Invalid manifests are refused, never repaired.
    for bad in (
        {**manifest, "purpose": "curator"},
        {**manifest, "extra": 1},
        {**manifest, "overrides": {"CLAUDECODE": "0"}},
        {**manifest, "overrides": {"HOME": "token=" + "s3cr3t" + "-value-1234"}},
        {**manifest, "installation_id": "inst_bad"},
        {**manifest, "platform_keys": ["BAD KEY"]},
    ):
        with pytest.raises(process_env.ManifestError):
            process_env.spawn_environment(bad, inherited, purpose="worker")


def test_worker_sets_its_own_role_marker(replay, tmp_path):
    """Hook-started from a host-marked parent that carries another installation's marker."""
    foreign = "inst_99999999-9999-4999-8999-999999999999"
    env = wh.marked_env(RECALITH_WORKER_INSTALLATION=foreign, RECALITH_FOO="bar", HOME=str(tmp_path), UNRELATED_SECRET="sk-ant-api03-" + "w" * 40)
    start_with_hooks(replay, tmp_path, env=env)
    status = wh.wait_running(replay.root)
    assert status, "the hook-started worker never came up"
    names = set(status["environment"]["key_names"]) - OS_INJECTED
    assert status["environment"]["role_marker"] == replay.ctx.installation_id
    assert status["environment"]["host_markers_present"] == [] and not status["environment"]["curator_marker_present"]
    assert set(names) <= set(process_env.platform_keys()) | {process_env.WORKER_MARKER}
    for absent in ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "RECALITH_FOO", "HOME", "UNRELATED_SECRET"):
        assert absent not in names
    if sys.platform.startswith("linux"):  # a second observation, straight from the kernel
        raw = Path(f"/proc/{status['pid']}/environ").read_bytes()
        keys = sorted({item.split(b"=", 1)[0].decode() for item in raw.split(b"\0") if b"=" in item})
        assert keys == sorted(names)
    if OS_INJECTED:
        print("OS-injected environment names observed in the worker:", sorted(set(status["environment"]["key_names"]) & OS_INJECTED))


def test_internal_worker_entry_refuses_marked_or_foreign_callers(replay, tmp_path):
    ctx = replay.ctx
    base = wh.worker_env(replay.root)
    cases = {
        "host_marker": {**base, "CLAUDECODE": "1"},
        "curator_marker": {**base, "RECALITH_CURATOR_INSTALLATION": ctx.installation_id},
        "foreign_marker": {**base, "RECALITH_WORKER_INSTALLATION": "inst_99999999-9999-4999-8999-999999999999"},
        "no_marker": {k: v for k, v in base.items() if k != process_env.WORKER_MARKER},
    }
    for name, env in cases.items():
        proc = subprocess.run([sys.executable, "-I", "-m", "recalith.controller.worker", "--project", str(replay.root)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
        assert proc.returncode == 6 and "policy_refused" in proc.stderr, (name, proc.stderr)
    assert not process_env.worker_running(replay.root) and worker.read_status(replay.root) is None


# ---------------------------------------------------------------------------
# One worker per installation (OS lock)


def test_only_one_worker_per_installation(tmp_path, started):
    a = cf.Replay(tmp_path / "a")
    b = cf.Replay(tmp_path / "b")
    started.extend([a.root, b.root])
    first, second, other = wh.start_direct(a.root), wh.start_direct(a.root), wh.start_direct(b.root)
    try:
        assert wh.wait_running(a.root) and wh.wait_running(b.root)
        assert wh.wait_for(lambda: any(p.poll() is not None for p in (first, second)), 20), "both workers kept running for one installation"
        time.sleep(1.5)  # longer than the loser's lock retry window
        losers = [p for p in (first, second) if p.poll() is not None]
        assert len(losers) == 1 and losers[0].returncode == 0, "exactly one of two workers for one installation keeps running"
        winner = second if losers[0] is first else first
        assert winner.poll() is None and other.poll() is None  # the independent installation runs concurrently
        status_a, status_b = worker.read_status(a.root), worker.read_status(b.root)
        assert status_a["installation_id"] == a.ctx.installation_id and status_b["installation_id"] == b.ctx.installation_id
        assert status_a["pid"] != status_b["pid"] and wh.pid_alive(status_a["pid"]) and wh.pid_alive(status_b["pid"])
    finally:
        for root in (a.root, b.root):
            wh.stop_worker(root)
        for p in (first, second, other):
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                p.kill()


# ---------------------------------------------------------------------------
# Registered start from the hook (A45, A73)


def test_registered_start_needs_no_operator_cli(replay, tmp_path):
    """A73 permitted-start control: a host-marked hook starts the worker with no `recalith worker` CLI involved."""
    statuses = start_with_hooks(replay, tmp_path, env=wh.marked_env())
    assert wh.wait_running(replay.root)
    stamp = json.loads((Path(process_env.run_dir(replay.root)) / process_env.START_STAMP).read_text(encoding="utf-8"))
    assert stamp["method"] in ("posix_session", "windows_breakaway", "windows_no_breakaway")
    status = worker.read_status(replay.root)
    assert status["spawn"]["spawned_by"] == "hook" and status["spawn"]["method"] == stamp["method"]
    # The next hook finds it running and starts nothing.
    again, _ = hook(replay, wh.prompt_record(), tmp_path, env=wh.marked_env())
    assert again["worker"] == "worker_running"
    print("worker start statuses:", statuses)


def _hosted_start(tmp_path, replay, *, job):
    """Start the worker from a simulated host's hook, retrying if a hook sheds the start."""
    hosts = []
    for attempt in range(5):
        record = wh.start_record() if attempt == 0 else wh.prompt_record()
        reply_path = tmp_path / f"host-reply-{attempt}.json"
        host, ready = wh.run_host(tmp_path, replay.root, replay.prepare(record), env=wh.marked_env(), event=record["event"], job=job, reply=reply_path)
        hosts.append(host)
        assert ready["hook_rc"] == 0 and ready["hook_stdout"] == 0  # the host got its hook back: no inherited pipe kept it waiting
        reply = json.loads(reply_path.read_text(encoding="utf-8"))
        if reply["worker"] != "deadline_worker_start_skipped":
            return host, ready, reply, hosts
    raise AssertionError("every hook shed the worker start")


def test_hook_started_worker_survives_host_termination(replay, tmp_path):
    """The host's process group (POSIX) or kill-on-close job (Windows) dies; the worker keeps ingesting."""
    job = "breakaway_ok" if os.name == "nt" else None
    host, ready, reply, hosts = _hosted_start(tmp_path, replay, job=job)
    try:
        status = wh.wait_running(replay.root)
        assert status, "the hook-started worker never came up"
        independence = status["spawn"]
        if os.name != "nt" and independence["state"] != "detached":
            pytest.skip(f"this platform/session prevented detachment ({independence['method']}: {independence['degraded_reasons']}); reported degraded, survival not claimed")
        if os.name == "nt":
            # The host job permits breakaway, so survival is supported here and is tested; the worker may
            # still claim only degraded independence when it cannot verify that it left every job.
            assert independence["method"] == "windows_breakaway" and (independence["state"] == "detached") == (independence["in_job"] is False)
        assert reply["worker"] == "worker_started"
        for h in hosts:
            wh.terminate_host(h)
        assert wh.wait_for(lambda: not wh.pid_alive(ready["control_pid"]), 10), "the host termination did not reach its own tree; the test would prove nothing"
        before = events_and_done(replay.root)
        heartbeat = status["heartbeat_at"]
        assert wh.wait_for(lambda: (worker.read_status(replay.root) or {}).get("heartbeat_at", "") > heartbeat, 15), "the worker stopped polling with its host"
        assert process_env.worker_running(replay.root)
        # Continued ingestion after the host is gone.
        later = next(r for r in cf.records("lifecycle") if r["event"] == "PreToolUse")
        after_reply, _ = hook(replay, later, tmp_path, env=wh.marked_env())
        assert after_reply["worker"] == "worker_running"
        event_id = after_reply["receipt"]["event_ids"][0]
        assert wh.wait_for(lambda: event_available(replay.root, event_id), 20), "the surviving worker did not ingest new capture"
        assert events_and_done(replay.root)[0] > before[0]
        print("survived host termination:", independence)
    finally:
        for h in hosts:
            wh.kill_host(h)


@pytest.mark.skipif(os.name != "nt", reason="Job Object breakaway is a Windows mechanism; POSIX uses a new session")
def test_job_without_breakaway_reports_degraded_independence(replay, tmp_path):  # pragma: no cover - native Windows
    """A host job without BREAKAWAY_OK: the worker either escapes it or says it is degraded, never a false claim."""
    host, ready, reply, hosts = _hosted_start(tmp_path, replay, job="no_breakaway")
    try:
        status = wh.wait_running(replay.root)
        assert status, "the hook-started worker never came up"
        claimed = status["spawn"]
        if reply["worker"] == "worker_independence_degraded":
            assert claimed["method"] == "windows_no_breakaway" and claimed["state"] == "degraded" and "job_breakaway_denied" in claimed["degraded_reasons"]
        for h in hosts:
            wh.terminate_host(h)
        died = wh.wait_for(lambda: not process_env.worker_running(replay.root), 10)
        print("no-breakaway job:", {"reply": reply["worker"], "claimed": claimed, "died_with_host_job": bool(died)})
        if died:
            assert claimed["state"] == "degraded", f"the worker died with its host's job but had claimed {claimed}"
        else:
            assert claimed["state"] == "detached" and process_env.worker_running(replay.root)
    finally:
        for h in hosts:
            wh.kill_host(h)


def test_hook_worker_start_closes_inherited_handles(replay, tmp_path):
    """A pipe the host leaks into the hook never reaches the worker: the host sees EOF once the hook exits."""
    for attempt in range(5):
        read_fd, write_fd = os.pipe()
        os.set_inheritable(write_fd, True)
        record = wh.start_record() if attempt == 0 else wh.prompt_record()
        reply_path = tmp_path / f"pipe-reply-{attempt}.json"
        kwargs = {"pass_fds": (write_fd,)} if os.name != "nt" else {"close_fds": False}
        proc = subprocess.run(cf.hook_command(replay.root, record["event"], reply_path), input=replay.prepare(record), capture_output=True, env=wh.marked_env(), timeout=60, check=False, **kwargs)
        os.close(write_fd)
        assert proc.returncode == 0
        if json.loads(reply_path.read_text(encoding="utf-8"))["worker"] == "worker_started":
            break
        os.close(read_fd)
    else:
        raise AssertionError("every hook shed the worker start")
    assert wh.wait_running(replay.root), "the hook-started worker never came up"
    eof = threading.Event()

    def reader():
        while os.read(read_fd, 1024):
            pass
        eof.set()

    threading.Thread(target=reader, daemon=True).start()
    assert eof.wait(10), "a worker (or other descendant) still holds the host's inherited pipe"
    os.close(read_fd)
    assert process_env.worker_running(replay.root)


def test_killed_worker_is_restarted_by_the_next_hook(replay, tmp_path):
    start_with_hooks(replay, tmp_path)
    first = wh.wait_running(replay.root)
    assert first
    wh.kill_pid(first["pid"])
    assert wh.wait_for(lambda: not process_env.worker_running(replay.root), 20)  # the OS released the dead worker's lock
    # Within the start throttle a hook does not spawn again ... The throttle is asserted in process with a generous
    # deadline. Under the real 250 ms deadline a loaded runner can spend it all on capture, and the hook then
    # correctly sheds the start before the throttle check (CI run 32, Windows); that branch is reproduced here.
    record = wh.prompt_record()
    shed = entry.run(str(replay.root), "claude_code", replay.prepare(record), registered_event=record["event"], env=cf.child_env(), deadline=time.monotonic())
    assert shed["worker"] == "deadline_worker_start_skipped"
    pending = entry.run(str(replay.root), "claude_code", replay.prepare(record), registered_event=record["event"], env=cf.child_env(), deadline=time.monotonic() + 5)
    assert pending["worker"] == "worker_start_pending"
    assert not process_env.worker_running(replay.root)
    stamp_path = Path(process_env.run_dir(replay.root)) / process_env.START_STAMP
    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    stamp_path.write_text(json.dumps(dict(stamp, at=stamp["at"] - process_env.START_THROTTLE_SECONDS - 1)), encoding="utf-8")
    # ... after it, the next hook starts a fresh worker, which resumes the queue.
    start_with_hooks(replay, tmp_path)
    second = wh.wait_running(replay.root, other_than=first["pid"])
    assert second and second["pid"] != first["pid"]
    assert wh.wait_for(lambda: events_and_done(replay.root)[2] == 0 and events_and_done(replay.root)[0] > 0, 20)


def test_worker_start_is_shed_under_deadline_pressure(tmp_path, started):
    replayer = cf.Replay(tmp_path / "replay")
    wh.enable_autostart(replayer)
    started.append(replayer.root)
    ctx = entry.load_context(str(replayer.root), "claude_code")
    assert process_env.ensure_worker(ctx, deadline=time.monotonic() + 0.01) == "deadline_worker_start_skipped"
    record = wh.start_record()
    reply = entry.run(str(replayer.root), "claude_code", replayer.prepare(record), registered_event=record["event"], env=wh.marked_env(), deadline=time.monotonic() + 0.005)
    assert reply["receipt"]["status"] == "accepted"  # capture is never what gets shed
    assert reply["worker"] == "deadline_worker_start_skipped" and "deadline_worker_start_skipped" in reply["degradations"]
    assert not process_env.worker_running(replayer.root) and not (Path(process_env.run_dir(replayer.root)) / process_env.START_STAMP).exists()
    # Autostart off (no integration consent in the manifest): no start and no degradation.
    cf.write_hook_context(replayer.ctx, adapter_id="claude_code", host_version=cf.VERSION, worker_autostart=False)
    ctx = entry.load_context(str(replayer.root), "claude_code")
    assert process_env.ensure_worker(ctx, deadline=time.monotonic() + 1) == "worker_autostart_disabled"


# ---------------------------------------------------------------------------
# Polling: typed state within the preview target (ACCEPTANCE_TESTS §7)

PHASES = 8


def test_idle_poll_state_available_within_five_seconds(replay, tmp_path):
    """Captured events reach typed state within p95 ≤ 5 s of an idle 5-second-polling worker.

    Arrivals are placed at evenly spaced phases of the idle poll cycle, so the
    sample covers the whole cycle instead of depending on luck. Latency is
    measured from the hook's acknowledgment (process exit) to the event being
    committed with its ingest job completed, observed from a separate
    read-only connection.
    """
    start_with_hooks(replay, tmp_path)
    assert wh.wait_running(replay.root)
    idle = worker.read_status(replay.root)["poll"]["idle_seconds"]
    assert idle == 5 and worker.read_status(replay.root)["poll"]["ipc_wake"] == "unavailable_in_preview"
    latencies, from_spawn, polls, trials = [], [], [], []
    for trial in range(PHASES):
        settled = wh.wait_for(lambda: (lambda s: s if s and s["state"] == "idle" and not s["poll"]["last_poll_worked"] else None)(worker.read_status(replay.root)), 30)
        assert settled, "worker never returned to idle polling"
        phase = (trial + 0.5) / PHASES * idle
        target = settled["poll"]["last_poll_wall"] + phase
        while target < time.time() + 0.2:
            target += idle
        time.sleep(max(0.0, target - time.time()))
        data = wh.unique_prompt(replay, trial)
        record = wh.prompt_record()
        spawned = time.monotonic()
        spawned_wall = time.time()
        trial_reply, wall = hook(replay, record, tmp_path, data=data, name=f"trial-{trial}")
        acked = spawned + wall
        acked_wall = spawned_wall + wall
        event_id = trial_reply["receipt"]["event_ids"][0]
        assert wh.wait_for(lambda event_id=event_id: event_available(replay.root, event_id), 15, interval=0.01), f"trial {trial} never reached typed state"
        done = time.monotonic()
        latencies.append(done - acked)
        from_spawn.append(done - spawned)
        after = worker.read_status(replay.root) or {}
        poll = after.get("poll", {})
        polls.append(poll.get("last_poll_seconds"))  # diagnostics: where the time goes
        # Where the time goes, per trial: the arrival's offset into the idle cycle, the hook's own wall time,
        # when the latest poll (normally the ingesting one) started relative to the acknowledgment, and any poll
        # error or clock jump the worker counted. A long ``poll_after_ack`` with short polls means the poll grid,
        # not the poll, was late.
        trials.append({
            "phase": round(phase, 3), "hook_wall": round(wall, 3), "latency": round(done - acked, 3),
            "poll_after_ack": round(poll["last_poll_wall"] - acked_wall, 3) if isinstance(poll.get("last_poll_wall"), float) else None,
            "since_settled_poll": round(acked_wall - settled["poll"]["last_poll_wall"], 3), "polls": (after.get("counters") or {}).get("polls"),
            "errors": (after.get("counters") or {}).get("errors"), "last_error": after.get("last_error"), "clock_jump": after.get("max_clock_jump_seconds"),
        })
    p95 = statistics.quantiles(latencies, n=20, method="inclusive")[18]
    report = {"phases": PHASES, "p50": statistics.median(latencies), "p95": p95, "max": max(latencies), "p95_from_hook_spawn": statistics.quantiles(from_spawn, n=20, method="inclusive")[18], "poll_seconds": [round(x, 3) if isinstance(x, float) else x for x in polls], "trials": trials}
    print("typed-state latency (s):", json.dumps({k: round(v, 3) if isinstance(v, float) else v for k, v in report.items()}))
    assert p95 <= 5.0, report
    assert max(latencies) <= idle + 1.0, report  # one idle interval plus bounded processing


# ---------------------------------------------------------------------------
# The installed host, end to end (request-capture mode; skipped without the CLI)


def _installed_claude() -> str | None:
    import shutil

    exe = shutil.which("claude")
    if not exe or os.name == "nt":
        return None
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False).stdout
    return exe if cf.VERSION in out else None


@pytest.mark.skipif(_installed_claude() is None, reason=f"Claude Code {cf.VERSION} CLI is not installed here; the simulated-host tests cover this platform")
def test_installed_host_starts_a_worker_that_outlives_the_session(tmp_path, started):
    """A live Claude Code process runs the real hook, which starts the worker; the host exits and its group is killed."""
    sys.path.insert(0, str(cf.ROOT / "tools"))
    import capture_claude_fixtures as cap
    import probe_common as pc
    import probe_delivery as pd

    base = tmp_path / "host"
    base.mkdir()
    ws, home = cap.make_workspace(base)
    cf.identity.initialize_installation(ws, cf.ProjectConfig.defaults_for(cf.PROJECT_ID))
    ctx = cf.identity.resolve_installation(ws, actor=cf.ADAPTER_ACTOR)
    cf.write_hook_context(ctx, adapter_id="claude_code", host_version=cf.VERSION, worker_autostart=True)
    started.append(ws)
    settings = ws / ".claude" / "settings.local.json"
    pd._write_settings(settings, cap.unrelated_settings())
    entries = []
    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop", "SessionEnd"):
        command = " ".join(json.dumps(x) for x in cf.hook_command(ws, event))
        entries.append((event, "*" if "Tool" in event else None, command))
    manifest = pd.install_owned_hooks(settings, entries, timeout_s=10)
    try:
        with pc.RecordingEndpoint(cap.responder_for(ws)) as endpoint:
            result = cap.run_scenario(_installed_claude(), "lifecycle", ws, home, endpoint.url, None)  # the host's process group is killed after it exits
    finally:
        pd.remove_owned_hooks(manifest)
    assert result["returncode"] == 0 and not result["timed_out"]
    status = wh.wait_running(ws, timeout=20)
    assert status, "no worker survived the host session"
    assert status["spawn"] == {"spawned_by": "hook", "method": "posix_session", "state": "detached", "degraded_reasons": [], "in_job": None}
    assert status["environment"]["host_markers_present"] == [] and status["environment"]["role_marker"] == ctx.installation_id
    # The worker, not the test, ingests the live session's capture, including SessionEnd sent as the host exited.
    expected = {"session_started", "user_message", "tool_started", "tool_finished", "session_ended"}

    def ingested():
        with db.open_store(ctx, readonly=True) as store, store.read() as view:
            kinds = {r[0] for r in view.execute("SELECT DISTINCT kind FROM events").fetchall()}
            hosts = {r[0] for r in view.execute("SELECT DISTINCT host_session_id FROM sessions").fetchall()}
        return (kinds, hosts) if expected <= kinds and events_and_done(ws)[2] == 0 else None

    found = wh.wait_for(ingested, 30)
    assert found, "the surviving worker did not ingest the session"
    assert found[1] == {result["session_id"]} and spool_ready(ws) == 0
    assert wh.pid_alive(status["pid"]) and process_env.worker_running(ws)


def spool_ready(root: Path) -> int:
    from recalith.storage import spool

    return len(spool.ready_segments(spool.SpoolDirs(root)))


def test_schema_one_manifest_still_captures_without_autostart(tmp_path):
    """An integration written before context_schema 2 keeps capturing; it simply never starts a worker."""
    replayer = cf.Replay(tmp_path / "replay")
    path = replayer.root / entry.HOOK_CONTEXT_FILE
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.pop("worker")
    manifest["context_schema"] = 1
    for adapter in manifest["adapters"].values():
        adapter.pop("delivery_paths")  # context_schema 3 (decision 0015) added it; schemas 1–2 never had it
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert entry.load_context(str(replayer.root), "claude_code")["worker_autostart"] is False
    reply, _ = hook(replayer, wh.start_record(), tmp_path)
    assert reply["receipt"]["status"] == "accepted" and reply["worker"] == "worker_autostart_disabled"
    assert not process_env.worker_running(replayer.root)
    for bad in ({**manifest, "context_schema": 2}, {**manifest, "context_schema": 2, "worker": {"autostart": True, "route_keys": ["CLAUDECODE"]}}, {**manifest, "context_schema": 2, "worker": {"autostart": 1, "route_keys": []}}):
        assert not entry.valid_context_manifest(bad)
