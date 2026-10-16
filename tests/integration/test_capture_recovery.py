"""Task 3: durable capture, source cursors and replay recovery (A05–A09, A34, A49).

Crash tests kill a real child process at a deterministic failpoint, restart
from the durable state, and compare the reopened store with a reference run
of the same seeded scenario (ACCEPTANCE_TESTS §4). Repetitions default to 3
per failpoint; set RECALITH_CRASH_REPS=20 (nightly) or 100 (release candidate).
"""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import capture_scenarios as cs
from recalith.capture import pipeline, sources
from recalith.capture.normalize import RawEvent, normalize_event
from recalith.contracts.common import digest_of
from recalith.contracts.events import EventEnvelope
from recalith.storage import db, failpoints, repository, spool

HERE = Path(__file__).resolve().parent
REPS = int(os.environ.get("RECALITH_CRASH_REPS", "3"))
SECRET = "ghp_" + "Q" * 36
SECRET2 = "sk-ant-api03-" + "z" * 40
AWS = "AKIA" + "ABCDEFGHIJKLMNOP"


@pytest.fixture(autouse=True)
def _disarm():
    failpoints.disarm_all()
    yield
    failpoints.disarm_all()


@pytest.fixture
def project(tmp_path):
    root = cs.init_project(tmp_path, "proj")
    return root, cs.register_transcript(root)


def ctx_of(root):
    return cs.context(root)


def raw_user(key: str, text: str = "hello") -> RawEvent:
    return RawEvent(adapter_id=cs.ADAPTER, adapter_version="1", source_event_key=key, session_id=cs.SESSION, host_session_id=cs.HOST_SESSION, kind="user_message", payload={"text": text})


def envs(ctx, *raws):
    out = []
    for raw in raws:
        out += normalize_event(ctx, raw)[0]
    return out


def count(root, table):
    with db.open_store(ctx_of(root), readonly=True) as store:
        return repository.count_rows(store, table)


def all_bytes_under(path: Path) -> bytes:
    blob = b""
    for p in sorted(path.rglob("*")):
        if p.is_file():
            blob += p.read_bytes()
    return blob


def run_driver(root: Path, seed: int, start: int, failpoint: str | None = None, skip: int = 0, producer: str = "service") -> subprocess.CompletedProcess:
    args = [sys.executable, str(HERE / "capture_scenarios.py"), str(root), str(seed), str(start)]
    if failpoint:
        args += [failpoint, str(skip)]
    args += ["--producer", producer]
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)


# ------------------------------------------------------------ plan-named failpoint tests


def test_publish_before_cursor_replays_once(project):
    """A05: the segment is durable, the process dies before the cursor write."""
    root, source_id = project
    steps = cs.build_scenario(1)
    cs.ensure_appended(root, steps, 0)
    result = run_driver(root, 1, 0, failpoints.CURSOR_WRITE)
    assert result.returncode == failpoints.KILL_STATUS, result.stderr
    dirs = spool.SpoolDirs(root)
    assert len(spool.ready_segments(dirs)) >= 1  # published
    assert spool.read_cursor(dirs, source_id) is None  # cursor never advanced
    # Restart: the host retries from the old cursor; recovery republishes the same lines.
    restart = run_driver(root, 1, 0)
    assert restart.returncode == 0, restart.stderr
    cs.settle(root, source_id)
    state = cs.authoritative_state(root)
    keys = [e[1] for e in state["events"]]
    assert len(keys) == len(set(keys))  # each normalized event exactly once
    assert set(state["job_coverage"].values()) == {1}  # one support/job reference per event
    assert spool.read_cursor(dirs, source_id) is not None and state["cursor"][0][1] > 0
    reference = _reference(root.parent / "ref", 1)
    assert state["events"] == reference["events"] and state["cursor"] == reference["cursor"]


def test_commit_before_unlink_replays_once(project):
    """A06: DB commit succeeded, the process died before removing the segment."""
    root, source_id = project
    result = run_driver(root, 2, 0, failpoints.INGEST_AFTER_COMMIT)
    assert result.returncode == failpoints.KILL_STATUS, result.stderr
    dirs = spool.SpoolDirs(root)
    leftover = spool.ready_segments(dirs)
    assert leftover, "the committed segment must still be in ready/"
    before = cs.authoritative_state(root)
    replay = pipeline.ingest_ready(ctx_of(root))
    after = cs.authoritative_state(root)
    assert replay.accepted == 0 and replay.created_job_ids == []
    assert after["events"] == before["events"] and after["job_coverage"] == before["job_coverage"]
    assert after["ready"] == []  # eventually removed
    assert run_driver(root, 2, 0).returncode == 0
    cs.settle(root, source_id)
    reference = _reference(root.parent / "ref", 2)
    final = cs.authoritative_state(root)
    for key in ("events", "conflicts", "job_coverage", "cursor", "observations"):
        assert final[key] == reference[key], key


@pytest.mark.parametrize("failpoint", [failpoints.SPOOL_TEMP_WRITE, failpoints.SPOOL_FSYNC, failpoints.SPOOL_RENAME])
@pytest.mark.parametrize("injected", ["disk_full", "permission_denied"])
def test_disk_full_does_not_acknowledge(project, failpoint, injected):
    """A07: failure before durable publication → not_captured, no cursor advance, gap reported."""
    root, source_id = project
    ctx = ctx_of(root)
    dirs = spool.SpoolDirs(root)
    (root / cs.TRANSCRIPT).write_bytes(cs.line({"type": "user", "uuid": "u1", "text": "hi"}))
    failpoints.arm(failpoint, failpoints.DISK_FULL if injected == "disk_full" else failpoints.PERMISSION_DENIED)
    receipt, _tail = pipeline.recover_source(ctx, source_id, cs.parse_line)
    assert receipt.status == "not_captured" and receipt.error_code == "not_captured" and receipt.event_ids == []
    assert receipt.coverage["reason"] == injected
    assert spool.ready_segments(dirs) == [] and list(dirs.tmp.iterdir()) == []
    assert spool.read_cursor(dirs, source_id) is None
    health = pipeline.capture_health(ctx)
    assert health["gaps"] == {f"not_captured:{injected}": 1}
    # The host continues; the next attempt captures the same line exactly once.
    receipt2, _ = pipeline.recover_source(ctx, source_id, cs.parse_line)
    assert receipt2.status == "accepted"
    assert pipeline.ingest_ready(ctx).accepted == 1


@pytest.mark.skipif(os.name == "nt" or not hasattr(os, "geteuid"), reason="POSIX RLIMIT_FSIZE is unavailable on Windows")
def test_real_file_size_limit_is_not_acknowledged(project):
    """A07 with a real OS write failure (EFBIG under RLIMIT_FSIZE), not an injected one."""
    root, source_id = project
    (root / cs.TRANSCRIPT).write_bytes(cs.line({"type": "user", "uuid": "u-big", "text": "x" * 20000}))
    code = (
        "import resource, signal, sys, json\n"
        f"sys.path[:0] = [{str(HERE.parents[1] / 'src')!r}, {str(HERE)!r}]\n"
        "import capture_scenarios as cs\n"
        "from recalith.capture import pipeline, sources\n"
        "from recalith.storage import db\n"
        "signal.signal(signal.SIGXFSZ, signal.SIG_IGN)\n"
        f"ctx = cs.context(cs.Path({str(root)!r}))\n"
        "with db.open_store(ctx, readonly=True) as store:\n"
        f"    reg = sources.get_source(store, {source_id!r})\n"
        "tail = sources.read_tail(ctx, reg, {}, cs.parse_line)\n"
        "resource.setrlimit(resource.RLIMIT_FSIZE, (4096, 4096))  # store reads done; spool writes now fail\n"
        f"r = pipeline.capture(ctx, tail.events, cursor_proposals=[{{'source_id': {source_id!r}, 'cursor': tail.cursor}}])\n"
        "print(json.dumps(r.model_dump(mode='json')))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    assert out.returncode == 0, out.stderr
    receipt = json.loads(out.stdout.strip().splitlines()[-1])
    assert receipt["status"] == "not_captured" and receipt["coverage"]["reason"] == "disk_full"
    dirs = spool.SpoolDirs(root)
    assert spool.ready_segments(dirs) == [] and spool.read_cursor(dirs, source_id) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permission bits; Windows ACL failures use the injected variant")
def test_real_permission_failure_is_not_acknowledged(project):
    if os.geteuid() == 0:
        pytest.skip("running as root: directory permission bits do not block root, so only the injected EACCES variant applies")
    root, source_id = project
    ctx = ctx_of(root)
    dirs = spool.SpoolDirs(root)
    dirs.ensure()
    (root / cs.TRANSCRIPT).write_bytes(cs.line({"type": "user", "uuid": "u1", "text": "hi"}))
    os.chmod(dirs.ready, 0o500)
    try:
        receipt, _ = pipeline.recover_source(ctx, source_id, cs.parse_line)
    finally:
        os.chmod(dirs.ready, 0o700)
    assert receipt.status == "not_captured" and receipt.coverage["reason"] == "permission_denied"
    assert spool.read_cursor(dirs, source_id) is None and spool.ready_segments(dirs) == []


def test_secret_never_reaches_spool(project):
    """A34: credentials in arguments, output, environment, extensions and messages."""
    root, source_id = project
    ctx = ctx_of(root)
    tool = RawEvent(
        adapter_id=cs.ADAPTER, adapter_version="1", source_event_key="tool-secret", session_id=cs.SESSION, host_session_id=cs.HOST_SESSION, kind="tool_finished",
        payload={
            "tool_call_id": "c1", "tool_name": "Bash",
            "arguments": {"command": f"curl -H 'Authorization: Bearer {SECRET2}' https://deploy:{SECRET}@example.com --token {SECRET}", "env": {"API_KEY": "plainvalue123"}},
            "result_received": True, "outcome": "failure", "exit_code": 1,
            "result_text": ("noise\n" * 5000) + f"export AWS_ACCESS_KEY_ID={AWS}\npassword=hunter2hunter2\n",
            "action": cs.action(["curl", "-H", f"Authorization: Bearer {SECRET2}"]), "observation": None,
        },
        extensions={cs.ADAPTER: {"note": f"token: {SECRET}"}},
    )
    start = RawEvent(adapter_id=cs.ADAPTER, adapter_version="1", source_event_key="start-secret", session_id=cs.SESSION, host_session_id=cs.HOST_SESSION, kind="session_started",
                     payload={"environment": {"os": "linux", "ci": SECRET, "python_version": "3.12.1", "AWS_SECRET_ACCESS_KEY": "abc", "arch": "/usr/bin/x86_64"}})
    user = raw_user("user-secret", f"my key is {SECRET2} please store it")
    batch = envs(ctx, tool, start, user)
    receipt = pipeline.capture(ctx, batch)
    assert receipt.status == "accepted"
    # Secret in an identity field: refused, and the error message does not repeat it.
    with pytest.raises(Exception) as refused:
        normalize_event(ctx, raw_user(f"key-{SECRET}"))
    assert SECRET not in str(refused.value)
    # A failed publication leaves no temp copy either.
    failpoints.arm(failpoints.SPOOL_RENAME, failpoints.DISK_FULL)
    assert pipeline.capture(ctx, envs(ctx, raw_user("user-secret-2", f"again {SECRET}"))).status == "not_captured"
    spool_bytes = all_bytes_under(root / ".recalith" / "spool")
    for secret in (SECRET, SECRET2, AWS, "hunter2hunter2", "plainvalue123"):
        assert secret.encode() not in spool_bytes, secret
        assert secret not in json.dumps(receipt.model_dump(mode="json"))
    pipeline.ingest_ready(ctx)
    store_bytes = all_bytes_under(root / ".recalith" / "state")
    for secret in (SECRET, SECRET2, AWS, "hunter2hunter2", "plainvalue123"):
        assert secret.encode() not in store_bytes, secret
    with db.open_store(ctx, readonly=True) as store:
        stored = repository.get_event(store, batch[0].event_id)
        with store.read() as view:
            env_obs = view.execute("SELECT key, value FROM environment_observations").fetchall()
    assert stored.coverage.redacted and stored.coverage.truncated
    assert "[REDACTED:" in stored.payload["result_text"]
    assert sorted(env_obs) == [("os", "linux")]  # ci/arch values invalid, runtime/unregistered dropped


# ------------------------------------------------------------ repeated kill/restart matrix


_REFERENCE_CACHE: dict[int, dict] = {}


def _reference(tmp: Path, seed: int) -> dict:
    if seed not in _REFERENCE_CACHE:
        tmp.mkdir(parents=True, exist_ok=True)
        root = cs.init_project(tmp, f"reference-{seed}-{os.getpid()}-{time.time_ns()}")
        source_id = cs.register_transcript(root)
        cs.run_steps(root, seed, 0, source_id)
        cs.settle(root, source_id)
        _REFERENCE_CACHE[seed] = cs.authoritative_state(root)
    return _REFERENCE_CACHE[seed]


CRASH_POINTS = [fp for fp in failpoints.ALL]


@pytest.mark.parametrize("producer", ["service", "fast"])
@pytest.mark.parametrize("failpoint", CRASH_POINTS)
def test_crash_failpoints_match_reference_run(tmp_path, failpoint, producer):
    """ACCEPTANCE_TESTS §4 for both producers; the reference run is service-produced (Task 3b)."""
    crashed = 0
    for rep in range(REPS):
        seed = 100 + rep
        reference = _reference(tmp_path / "refs", seed)
        root = cs.init_project(tmp_path, f"crash-{rep}")
        source_id = cs.register_transcript(root)
        steps = cs.build_scenario(seed)
        start = rep % len(steps)
        for index in range(start):  # earlier steps complete without failures
            cs.run_step(root, steps, index, source_id, producer)
        result = run_driver(root, seed, start, failpoint, skip=rep % 2, producer=producer)
        if result.returncode == failpoints.KILL_STATUS:
            crashed += 1
            crashed_step = int([ln for ln in result.stdout.splitlines() if ln.startswith("step ")][-1].split()[1])
            restart = run_driver(root, seed, crashed_step, producer=producer)
            assert restart.returncode == 0, restart.stderr
        else:
            assert result.returncode == 0, result.stderr
        cs.settle(root, source_id)
        state = cs.authoritative_state(root)
        for key in ("events", "conflicts", "job_coverage", "cursor", "sessions", "observations"):
            assert state[key] == reference[key], (failpoint, rep, key)
        assert state["ready"] == [] and state["temps"] == [] and state["quarantine"] == []
    assert crashed >= max(1, REPS // 2), f"{failpoint} was not reached often enough to test it"


# ------------------------------------------------------------ A08 transcript recovery


def test_partial_line_is_read_once_when_completed(project):
    root, source_id = project
    ctx = ctx_of(root)
    full = cs.line({"type": "user", "uuid": "u-1", "text": "first"}) + cs.line({"type": "user", "uuid": "u-2", "text": "second, complete later"})
    path = root / cs.TRANSCRIPT
    path.write_bytes(full[:-12])
    receipt, tail = pipeline.recover_source(ctx, source_id, cs.parse_line)
    assert len(receipt.event_ids) == 1 and tail.partial_tail
    with open(path, "ab") as fh:
        fh.write(full[-12:])
    receipt2, tail2 = pipeline.recover_source(ctx, source_id, cs.parse_line)
    assert len(receipt2.event_ids) == 1 and not tail2.partial_tail
    assert pipeline.recover_source(ctx, source_id, cs.parse_line)[0] is None  # nothing new: no invented event
    assert pipeline.ingest_ready(ctx).accepted == 2
    assert count(root, "events") == 2


def test_truncation_and_replacement_are_explicit_gaps(project):
    root, source_id = project
    ctx = ctx_of(root)
    path = root / cs.TRANSCRIPT
    path.write_bytes(cs.line({"type": "user", "uuid": "u-1", "text": "a"}) + cs.line({"type": "user", "uuid": "u-2", "text": "b"}))
    pipeline.recover_source(ctx, source_id, cs.parse_line)
    # Truncation: a new generation from offset 0; host identity deduplicates re-read lines.
    path.write_bytes(cs.line({"type": "user", "uuid": "u-1", "text": "a"}))
    receipt, tail = pipeline.recover_source(ctx, source_id, cs.parse_line)
    assert tail.gaps == {"source_truncated": 1} and tail.cursor["generation"] == 1
    # Atomic-save replacement that keeps the consumed bytes: same generation, no gap.
    replacement = root / "replacement.jsonl"
    replacement.write_bytes(path.read_bytes() + cs.line({"type": "user", "uuid": "u-3", "text": "c"}))
    os.replace(replacement, path)
    receipt2, tail2 = pipeline.recover_source(ctx, source_id, cs.parse_line)
    assert tail2.gaps == {} and tail2.cursor["generation"] == 1 and len(receipt2.event_ids) == 1
    # Replacement with different content: new generation and a gap.
    other = root / "other.jsonl"
    other.write_bytes(cs.line({"type": "user", "uuid": "u-9", "text": "entirely different file"}))
    os.replace(other, path)
    _, tail3 = pipeline.recover_source(ctx, source_id, cs.parse_line)
    assert tail3.gaps == {"source_replaced": 1} and tail3.cursor["generation"] == 2
    # A malformed complete line is an explicit gap and is skipped, not invented.
    with open(path, "ab") as fh:
        fh.write(b"{not json\n" + cs.line({"type": "user", "uuid": "u-10", "text": "after"}))
    receipt4, tail4 = pipeline.recover_source(ctx, source_id, cs.parse_line)
    assert tail4.gaps == {"malformed_record": 1} and len(receipt4.event_ids) == 1
    result = pipeline.ingest_ready(ctx)
    assert result.accepted == 5 and result.conflict == 0  # u-1, u-2, u-3, u-9, u-10
    gaps = pipeline.capture_health(ctx)["gaps"]
    assert {"source_truncated:source_coverage", "source_replaced:source_coverage", "malformed_record:source_coverage"} <= set(gaps)


def test_late_result_joins_its_call(project):
    root, source_id = project
    ctx = ctx_of(root)
    path = root / cs.TRANSCRIPT
    path.write_bytes(cs.line({"type": "tool_use", "uuid": "u-a", "call": "call-A", "argv": ["pytest"]}) + cs.line({"type": "tool_use", "uuid": "u-b", "call": "call-B", "argv": ["pytest", "-x"]}))
    pipeline.recover_source(ctx, source_id, cs.parse_line)
    pipeline.ingest_ready(ctx)
    with open(path, "ab") as fh:  # results arrive late and out of order
        fh.write(cs.line({"type": "tool_result", "uuid": "u-rb", "call": "call-B", "argv": ["pytest", "-x"], "exit": 0, "outcome": "success", "output": "=== 2 passed in 0.1s ==="}))
        fh.write(cs.line({"type": "tool_result", "uuid": "u-ra", "call": "call-A", "argv": ["pytest"], "exit": 1, "outcome": "failure", "output": "FAILED t.py::x - E\n=== 1 failed in 0.1s ==="}))
    pipeline.recover_source(ctx, source_id, cs.parse_line)
    pipeline.ingest_ready(ctx)
    with db.open_store(ctx, readonly=True) as store:
        call_a = sources.call_events(store, cs.SESSION, "call-A")
        call_b = sources.call_events(store, cs.SESSION, "call-B")
    assert [e.kind for e in call_a] == ["tool_started", "tool_finished"] and call_a[1].payload["outcome"] == "failure"
    assert [e.kind for e in call_b] == ["tool_started", "tool_finished"] and call_b[1].payload["outcome"] == "success"


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_swapped_symlink_at_registered_path_is_refused(project, tmp_path):
    root, source_id = project
    ctx = ctx_of(root)
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(cs.line({"type": "user", "uuid": "u-out", "text": "outside content"}))
    path = root / cs.TRANSCRIPT
    path.unlink()
    try:
        os.symlink(outside, path)
    except OSError as exc:
        pytest.skip(f"cannot create symlinks here: {exc}")
    with pytest.raises(Exception, match="policy_refused"):
        pipeline.recover_source(ctx, source_id, cs.parse_line)
    with db.open_store(ctx) as store, pytest.raises(Exception, match="policy_refused"):
        sources.register_source(store, ctx, adapter_id=cs.ADAPTER, path=path, session_id=cs.SESSION, host_session_id=cs.HOST_SESSION)


def test_unregistered_source_is_not_recovered(project):
    root, _ = project
    with pytest.raises(Exception, match="policy_refused"):
        pipeline.recover_source(ctx_of(root), "src_" + "0" * 64, cs.parse_line)


# ------------------------------------------------------------ A09 / A49 overlap and conflicts


def test_overlapping_producers_deduplicate_and_conflicts_stay_separate(project):
    root, _ = project
    ctx = ctx_of(root)
    first = envs(ctx, raw_user("k1", "one"), raw_user("k2", "two"))
    overlap = envs(ctx, raw_user("k2", "two"), raw_user("k3", "three"))  # same content for k2
    changed_a = envs(ctx, raw_user("k1", "one, but changed"))
    changed_b = envs(ctx, raw_user("k1", "one, changed differently"))
    for batch in (first, overlap, changed_a, changed_b, changed_a):  # changed_a replayed
        assert pipeline.capture(ctx, batch).status == "accepted"
    with db.open_store(ctx, readonly=True) as store:
        epoch_before = store.meta().guidance_epoch
    result = pipeline.ingest_ready(ctx)
    assert (result.accepted, result.duplicate, result.conflict) == (3, 1, 3)
    with db.open_store(ctx, readonly=True) as store:
        original = repository.get_event(store, first[0].event_id)
        meta = store.meta()
        with store.read() as view:
            rows = view.execute("SELECT original_event_id, payload_digest, state FROM source_conflicts ORDER BY payload_digest").fetchall()
    assert original.payload["text"] == "one"  # immutable original
    assert sorted(r[1] for r in rows) == sorted({changed_a[0].payload_digest, changed_b[0].payload_digest})
    assert all(r[0] == first[0].event_id and r[2] == "unresolved" for r in rows)
    assert meta.guidance_epoch > epoch_before  # dependent guidance must re-check the source
    assert len(pipeline.capture_health(ctx)["unresolved_conflicts"]) == 2
    # Replaying everything is idempotent.
    for batch in (first, changed_a, changed_b):
        pipeline.capture(ctx, batch)
    again = pipeline.ingest_ready(ctx)
    assert again.accepted == 0 and again.created_job_ids == []
    assert count(root, "source_conflicts") == 2 and count(root, "events") == 3


def test_foreign_and_tampered_input_is_rejected(project, tmp_path):
    root, _ = project
    ctx = ctx_of(root)
    other = cs.init_project(tmp_path, "other")
    foreign = envs(cs.context(other), raw_user("k1"))
    receipt = pipeline.capture(ctx, foreign)
    assert receipt.status == "not_captured" and receipt.error_code == "foreign_installation"
    assert spool.ready_segments(spool.SpoolDirs(root)) == []
    # A segment whose content no longer matches its digest is quarantined, never ingested.
    pipeline.capture(ctx, envs(ctx, raw_user("k2", "real")))
    (segment,) = spool.ready_segments(spool.SpoolDirs(root))
    segment.write_bytes(segment.read_bytes().replace(b'"real"', b'"fake"'))
    result = pipeline.ingest_ready(ctx)
    assert result.accepted == 0 and count(root, "events") == 0
    health = pipeline.capture_health(ctx)
    assert health["quarantined_segments"] == 1 and "segment_quarantined:invalid" in health["gaps"]


def test_large_batches_split_into_bounded_segments(project):
    root, _ = project
    ctx = ctx_of(root)
    batch = envs(ctx, *[raw_user(f"big-{i}", "é" * 30000) for i in range(12)])  # ~60 KB each
    receipt = pipeline.capture(ctx, batch, cursor_proposals=[{"source_id": project[1], "cursor": {"generation": 0, "offset": 7}}])
    assert receipt.status == "accepted" and len(receipt.coverage["segment_ids"]) >= 3
    segments = spool.ready_segments(spool.SpoolDirs(root))
    assert all(p.stat().st_size <= 256 * 1024 for p in segments)
    carrying = [json.loads(p.read_bytes())["cursor_proposals"] for p in segments]
    assert sum(1 for c in carrying if c) == 1 and carrying[-1]  # cursor rides in the last segment
    assert pipeline.ingest_ready(ctx).accepted == 12


def test_deadline_overrun_still_acknowledges_durable_capture(project):
    root, _ = project
    ctx = ctx_of(root)
    receipt = pipeline.capture(ctx, envs(ctx, raw_user("late")), deadline=time.monotonic() - 1)
    assert receipt.status == "accepted" and receipt.coverage["degraded"] == ["capture_deadline_overrun"]


def test_capture_rescrubs_envelopes_built_outside_normalize(project):
    root, _ = project
    ctx = ctx_of(root)
    (env,) = envs(ctx, raw_user("plain", "nothing secret"))
    data = env.model_dump(mode="json")
    data["payload"] = {"text": f"leaked {SECRET}"}
    data["payload_digest"] = digest_of(data["payload"])
    receipt = pipeline.capture(ctx, [EventEnvelope.model_validate(data)])
    assert receipt.status == "accepted" and receipt.coverage["warnings"] == {"redacted": 1}
    assert SECRET.encode() not in all_bytes_under(root / ".recalith" / "spool")


# ------------------------------------------------------------ Windows transient rename retry


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _publish(root, clock, deadline):
    return spool.publish(spool.SpoolDirs(root), "x.seg.json", b"{}", deadline=deadline, platform="nt", clock=clock, sleep=clock.sleep)


def test_windows_sharing_violation_retries_once_within_deadline(tmp_path):
    clock = _Clock()
    failpoints.arm(failpoints.SPOOL_RENAME, failpoints.raise_errno(errno.EACCES, winerror=32))
    outcome = _publish(tmp_path, clock, deadline=clock.now + 0.25)
    assert outcome.ok and outcome.rename_retried and clock.slept == [0.020]


def test_windows_second_sharing_violation_is_not_captured(tmp_path):
    clock = _Clock()
    failpoints.arm(failpoints.SPOOL_RENAME, failpoints.raise_errno(errno.EACCES, winerror=32), times=2)
    outcome = _publish(tmp_path, clock, deadline=clock.now + 0.25)
    assert not outcome.ok and outcome.reason == "rename_failed" and clock.slept == [0.020]
    dirs = spool.SpoolDirs(tmp_path)
    assert spool.ready_segments(dirs) == [] and list(dirs.tmp.iterdir()) == []


def test_windows_retry_uses_only_remaining_deadline(tmp_path):
    clock = _Clock()
    failpoints.arm(failpoints.SPOOL_RENAME, failpoints.raise_errno(errno.EACCES, winerror=32))
    outcome = _publish(tmp_path, clock, deadline=clock.now + 0.005)
    assert outcome.ok and clock.slept == [pytest.approx(0.005)]
    clock2 = _Clock()
    failpoints.arm(failpoints.SPOOL_RENAME, failpoints.raise_errno(errno.EACCES, winerror=32))
    expired = _publish(tmp_path / "b", clock2, deadline=clock2.now - 0.001)
    assert not expired.ok and clock2.slept == []  # no budget left: no retry


@pytest.mark.parametrize("winerror", [None, 2])
def test_non_transient_rename_errors_are_not_retried(tmp_path, winerror):
    clock = _Clock()
    failpoints.arm(failpoints.SPOOL_RENAME, failpoints.raise_errno(errno.EIO, winerror=winerror))
    outcome = _publish(tmp_path, clock, deadline=clock.now + 0.25)
    assert not outcome.ok and outcome.reason == "io_error" and clock.slept == []


def test_posix_never_retries_rename(tmp_path):
    clock = _Clock()
    failpoints.arm(failpoints.SPOOL_RENAME, failpoints.raise_errno(errno.EACCES, winerror=32))
    outcome = spool.publish(spool.SpoolDirs(tmp_path), "x.seg.json", b"{}", deadline=clock.now + 1, platform="posix", clock=clock, sleep=clock.sleep)
    assert not outcome.ok and clock.slept == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_spool_leaves_existing_directory_modes_alone(tmp_path):
    """Publication must not re-chmod a directory an operator (or a fault) restricted."""
    dirs = spool.SpoolDirs(tmp_path)
    dirs.ensure()
    os.chmod(dirs.ready, 0o500)
    try:
        dirs.ensure()
        assert dirs.ready.stat().st_mode & 0o777 == 0o500
    finally:
        os.chmod(dirs.ready, 0o700)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_spool_files_are_private(project):
    root, _ = project
    ctx = ctx_of(root)
    pipeline.capture(ctx, envs(ctx, raw_user("p1")), cursor_proposals=[{"source_id": project[1], "cursor": {"generation": 0, "offset": 1}}])
    dirs = spool.SpoolDirs(root)
    for path in [*spool.ready_segments(dirs), *dirs.cursors.iterdir()]:
        assert path.stat().st_mode & 0o077 == 0, path
    for directory in (dirs.base, dirs.ready, dirs.tmp, dirs.cursors):
        assert directory.stat().st_mode & 0o077 == 0, directory
