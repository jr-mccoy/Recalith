"""Capture-only real Claude Code adapter and fast-path boundary (Task 3b).

Every test feeds *actual serialized* host events: the sanitized hook stdin
recorded from the installed Claude Code 2.1.301 (``tests/fixtures/hosts/claude/
2.1.301/``) or, where named, a payload built in exactly that recorded format.
Payloads go through the real entry point in a fresh interpreter, the spool
segment on disk, ``ingest_ready`` and a store reopened from disk.

Acceptance: A07, A08, A09, A53, A58, A68, A70 (capture-only variants; delivery
is advertised unavailable and never emitted).
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

import claude_fixtures as cf
from recalith.capture import pipeline, sources
from recalith.capture.normalize import normalize_event
from recalith.contracts.common import canonical_json as strict_canonical
from recalith.contracts.context import SessionScratch
from recalith.contracts.events import CaptureReceipt, EventEnvelope, Segment
from recalith.core import identity
from recalith.fast import claude_capture, entry, failpoints, session, spool, wire
from recalith.fast.normalize import normalize_raw
from recalith.storage import db
from recalith.storage.repository import event_from_row

FIXTURES = cf.FIXTURES
SECRET_FRAGMENT = "fixture-hunter2-not-real"


@pytest.fixture(autouse=True)
def _disarm():
    failpoints.disarm_all()
    yield
    failpoints.disarm_all()


@pytest.fixture
def replay(tmp_path):
    return cf.Replay(tmp_path)


def reopen(root: Path):
    return identity.resolve_installation(root, actor=cf.ADAPTER_ACTOR)


def stored_events(root: Path) -> list[EventEnvelope]:
    ctx = reopen(root)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        rows = view.execute("SELECT envelope, payload, payload_state FROM events ORDER BY commit_sequence").fetchall()
    return [event_from_row(row) for row in rows]


def query(root: Path, sql: str, params=()):
    with db.open_store(reopen(root), readonly=True) as store, store.read() as view:
        return view.execute(sql, params).fetchall()


def gaps(root: Path) -> list[dict]:
    return spool.read_gaps(spool.SpoolDirs(root))


def by_key_suffix(events, suffix):
    found = [e for e in events if e.source_event_key.endswith(suffix)]
    assert len(found) == 1, (suffix, [e.source_event_key for e in found])
    return found[0]


def ctx_dict(replay) -> dict:
    return entry.load_context(str(replay.root), "claude_code")


def run_in_process(replay, record, *, deadline=None, env=None):
    data = replay.prepare(record)
    ctx = ctx_dict(replay)
    return entry.run(str(replay.root), "claude_code", data, registered_event=record["event"], env=env or {}, deadline=deadline if deadline is not None else time.monotonic() + 0.25), ctx


# ---------------------------------------------------------------------------
# The real lifecycle


def test_capture_only_real_lifecycle(replay, tmp_path):
    """Start, prompts, tools (success/failure/no-match/timeout), compaction, stop, end, subagent, denial, resume, /clear."""
    replies = {name: cf.replay(replay, name, tmp_path) for name in ("lifecycle", "subagent", "denied", "secret_and_resume")}
    for name, scenario_replies in replies.items():
        for record, reply in zip(cf.records(name), scenario_replies, strict=True):
            assert reply["delivery"] == {"state": "unavailable", "reason": "capture_only_build"}  # never a placeholder context
            assert reply["host_output"] is None and reply["delivery_attempt_id"] is None and reply["emitted_receipt"] is None
            if record["event"] in claude_capture.ROLES:
                assert reply["receipt"]["status"] == "accepted", (name, record["event"], reply)
                assert CaptureReceipt.model_validate(reply["receipt"])  # the fast receipt is a valid strict receipt
            else:
                assert reply["receipt"] is None  # unsupported host event: an explicit gap, not a guess
    result = pipeline.ingest_ready(replay.ctx)
    total = sum(1 for name in replies for r in cf.records(name) if r["event"] in claude_capture.ROLES)
    assert (result.accepted, result.duplicate, result.conflict) == (total, 0, 0)
    assert spool.ready_segments(spool.SpoolDirs(replay.root)) == []

    events = stored_events(replay.root)  # a store reopened from disk
    kinds = {}
    for e in events:
        kinds[e.kind] = kinds.get(e.kind, 0) + 1
    assert kinds["session_started"] == 6 and kinds["session_ended"] == 5  # 5 sessions incl. resume/clear, 1 subagent start
    assert kinds["compaction"] == 3  # PreCompact, SessionStart(compact) restoration, PostCompact
    # Prompts carry user authority; the host's background-task notification does not.
    users = [e for e in events if e.kind == "user_message"]
    assert all(e.channel == "user" and e.authority == "explicit_user" for e in users)
    notes = [e for e in events if e.kind == "generic_observation"]
    assert len(notes) == 1 and notes[0].payload["host_origin"] == "task_notification" and notes[0].authority == "untrusted"
    # Queued prompts reuse prompt_id on 2.1.301; both are kept as distinct events.
    lifecycle_prompts = [e.payload["text"] for e in users if "FIXTURE lifecycle" in e.payload["text"] or e.payload["text"] == "Reply OK."]
    assert "FIXTURE lifecycle: run the scripted tools." in lifecycle_prompts and lifecycle_prompts.count("Reply OK.") >= 2

    # Immutable call identity: every finish pairs with its own start through tool_call_id.
    ctx = reopen(replay.root)
    with db.open_store(ctx, readonly=True) as store:
        for e in events:
            if e.kind != "tool_started":
                continue
            pair = sources.call_events(store, e.session_id, e.payload["tool_call_id"])
            if e.payload["tool_call_id"] == denied_call():
                assert [p.kind for p in pair] == ["tool_started"]  # a denied call never gets a result
            else:
                assert [p.kind for p in pair] == ["tool_started", "tool_finished"]
                assert pair[1].payload["action"] == pair[0].payload["action"]
    # Exact-version Bash mapping: exit code only from a failure's host prefix.
    exits = {e.payload["tool_call_id"]: (e.payload["outcome"], e.payload["exit_code"]) for e in events if e.kind == "tool_finished"}
    calls = tool_calls("lifecycle")
    assert exits[calls["ls /nonexistent-recalith-fixture-dir"]] == ("failure", 2)
    assert exits[calls["sleep 5"]] == ("failure", 143)  # host timeout
    assert exits[calls["grep -c nomatch notes.txt"]] == ("success", None)  # host-interpreted exit 1 is not exit 0
    assert exits[calls["echo hello-fixture"]] == ("success", None)

    # Sessions and sources come from the actual session payloads.
    sessions = dict(query(replay.root, "SELECT session_id, state FROM sessions"))
    assert len(sessions) == 4 and set(sessions.values()) == {"ended"}  # --resume keeps the host session ID
    registered = query(replay.root, "SELECT session_id, locator, coverage FROM capture_sources")
    transcripts = {json.loads(r[2])["parser"] for r in registered}
    assert transcripts == {claude_capture.TRANSCRIPT_PARSER}
    expected = {cf.Replay.payload(replay, r)["transcript_path"] for name in replies for r in cf.records(name) if "transcript_path" in r["payload"]}
    main_locators = {r[1] for r in registered if "/subagents/" not in r[1].replace("\\", "/")}
    assert main_locators == {claude_capture.exact_locator(p) for p in expected}
    assert any("/subagents/agent-" in r[1].replace("\\", "/") for r in registered)  # subagent transcripts too

    # Unsupported host events leave explicit, content-free gaps.
    assert {(g["code"], g["reason"]) for g in gaps(replay.root)} == {("unsupported_host_event", "PermissionRequest")}
    # Session scratch is discarded at SessionEnd.
    assert not list(Path(session.sessions_dir(replay.root)).glob("*.json"))


def denied_call() -> str:
    return next(r["payload"]["tool_use_id"] for r in cf.records("denied") if r["event"] == "PreToolUse")


def tool_calls(scenario: str) -> dict[str, str]:
    return {r["payload"]["tool_input"].get("command", r["payload"]["tool_input"].get("file_path")): r["payload"]["tool_use_id"] for r in cf.records(scenario) if r["event"] == "PreToolUse"}


def test_secret_prompt_is_scrubbed_before_any_byte_is_written(replay, tmp_path):
    """A34 on a real payload: no spool, scratch, gap or store byte holds the secret."""
    cf.replay(replay, "secret_and_resume", tmp_path)
    blob = b"".join(p.read_bytes() for p in (replay.root / ".recalith" / "spool").rglob("*") if p.is_file())
    assert SECRET_FRAGMENT.encode() not in blob and b"[REDACTED:" in blob
    pipeline.ingest_ready(replay.ctx)
    prompt = next(e for e in stored_events(replay.root) if e.kind == "user_message" and "FIXTURE secret" in e.payload["text"])
    assert SECRET_FRAGMENT not in prompt.payload["text"] and prompt.coverage.redacted
    store_bytes = b"".join(p.read_bytes() for p in (replay.root / ".recalith" / "state").glob("memory.sqlite*"))
    assert SECRET_FRAGMENT.encode() not in store_bytes


def test_duplicate_and_changed_host_events(replay, tmp_path):
    """A09: replayed hooks deduplicate; changed content under the same identity is a conflict."""
    cf.replay(replay, "lifecycle", tmp_path)
    first = pipeline.ingest_ready(replay.ctx)
    cf.replay(replay, "lifecycle", tmp_path)  # the same host events again (overlapping producer)
    second = pipeline.ingest_ready(replay.ctx)
    assert first.accepted > 0 and (second.accepted, second.duplicate, second.conflict) == (0, first.accepted, 0)
    record = next(r for r in cf.records("lifecycle") if r["event"] == "PostToolUse")
    changed = dict(record, payload=dict(record["payload"], tool_response=dict(record["payload"]["tool_response"], stdout="changed by another producer")))
    reply, _ = run_in_process(replay, changed)
    assert reply["receipt"]["status"] == "accepted"
    third = pipeline.ingest_ready(replay.ctx)
    assert (third.accepted, third.conflict) == (0, 1)
    original = by_key_suffix(stored_events(replay.root), f":tool:{record['payload']['tool_use_id']}:finish")
    assert original.payload["result_text"] == "hello-fixture"  # the original event is unchanged
    assert len(query(replay.root, "SELECT conflict_id FROM source_conflicts WHERE original_event_id = ?", (original.event_id,))) == 1


def test_late_result_joins_its_own_call(replay, tmp_path):
    """A08: results arriving late, interleaved or before the start still pair by tool_use_id."""
    records = [r for r in cf.records("lifecycle") if r["event"] in ("PreToolUse", "PostToolUse", "PostToolUseFailure")]
    starts = [r for r in records if r["event"] == "PreToolUse"]
    finishes = [r for r in records if r["event"] != "PreToolUse"]
    order = [finishes[0]] + starts + finishes[1:][::-1]  # one result before its start, the rest reversed and late
    for record in order:
        proc, _ = cf.run_hook(replay.root, replay.prepare(record), event=record["event"])
        assert proc.returncode == 0 and proc.stdout == b""
    pipeline.ingest_ready(replay.ctx)
    with db.open_store(reopen(replay.root), readonly=True) as store:
        for start in starts:
            session_id = claude_capture.session_id_for(replay.ctx.installation_id, start["payload"]["session_id"])
            pair = sources.call_events(store, session_id, start["payload"]["tool_use_id"])
            assert sorted(p.kind for p in pair) == ["tool_finished", "tool_started"]
            assert len({p.payload["tool_call_id"] for p in pair}) == 1


def test_transcript_supplement_recovers_assistant_text_once(replay, tmp_path):
    """A08 on the real sanitized transcript: partial last line read once, truncation is an explicit gap."""
    cf.replay(replay, "denied", tmp_path)
    pipeline.ingest_ready(replay.ctx)
    (source_id, locator), = [(r[0], r[1]) for r in query(replay.root, "SELECT source_id, locator FROM capture_sources")]
    lines = [replay_text(replay, line) for line in (FIXTURES / "denied.transcript.jsonl").read_text(encoding="utf-8").splitlines()]
    blob = "".join(line + "\n" for line in lines).encode("utf-8")
    cut = blob.rindex(b'"OK fixture reply"')  # inside the last assistant record: a partial line
    Path(locator).write_bytes(blob[:cut])
    parse = claude_capture.transcript_line_parser(replay.ctx.installation_id)
    pipeline.recover_source(replay.ctx, source_id, parse)
    pipeline.ingest_ready(replay.ctx)
    assert [e for e in stored_events(replay.root) if e.kind == "assistant_message"] == []  # nothing invented from the partial line
    Path(locator).write_bytes(blob)
    pipeline.recover_source(replay.ctx, source_id, parse)
    pipeline.recover_source(replay.ctx, source_id, parse)
    pipeline.ingest_ready(replay.ctx)
    assistant = [e for e in stored_events(replay.root) if e.kind == "assistant_message"]
    assert [e.payload["text"] for e in assistant] == ["OK fixture reply"]  # read once, whole
    assert assistant[0].channel == "assistant" and assistant[0].authority == "untrusted" and assistant[0].origin.origin_kind == "transcript"
    Path(locator).write_bytes(blob[: len(blob) // 3])  # truncated by the host
    pipeline.recover_source(replay.ctx, source_id, parse)
    assert ("source_truncated" in {g["code"] for g in gaps(replay.root)}) or ("source_rewritten" in {g["code"] for g in gaps(replay.root)})


def replay_text(replay, line: str) -> str:
    for placeholder, real in replay.placeholders().items():
        line = line.replace(placeholder, json.dumps(real)[1:-1])
    return line


def test_unknown_transcript_records_and_host_fields_are_gaps(replay, tmp_path):
    """A47 (capture slice): unsupported fields and records are visible coverage gaps, never guessed."""
    record = cf.records("lifecycle")[1]  # UserPromptSubmit
    extended = dict(record, payload=dict(record["payload"], future_field={"x": 1}))
    reply, _ = run_in_process(replay, extended)
    assert reply["receipt"]["status"] == "accepted"
    pipeline.ingest_ready(replay.ctx)
    (prompt,) = [e for e in stored_events(replay.root) if e.kind == "user_message"]
    assert prompt.coverage.parser_complete is False
    assert prompt.extensions["claude_code"]["coverage_warnings"]["unsupported_host_field"] == 1
    parse = claude_capture.transcript_line_parser(replay.ctx.installation_id)
    with pytest.raises(claude_capture.UnsupportedRecord):
        parse({"type": "future-record", "uuid": "u"}, None)
    assert parse({"type": "queue-operation"}, None) == []


def test_uncertified_host_version_is_conservative(tmp_path):
    """SYSTEM_SPEC §9.2: an unknown host version is captured without user/tool authority or version-specific parsing."""
    replay = cf.Replay(tmp_path, host_version="9.9.9")
    cf.replay(replay, "lifecycle", tmp_path)
    pipeline.ingest_ready(replay.ctx)
    events = stored_events(replay.root)
    assert {e.authority for e in events} == {"untrusted"}
    assert all(not e.coverage.parser_complete for e in events)
    assert all(e.payload["exit_code"] is None for e in events if e.kind == "tool_finished")
    assert all(e.adapter_version == "9.9.9" for e in events)


def test_curator_session_is_rejected(replay):
    """SYSTEM_SPEC §5.3: a curator-owned session never becomes evidence."""
    record = cf.records("lifecycle")[1]
    env = cf.child_env(RECALITH_CURATOR_INSTALLATION=replay.ctx.installation_id)
    reply_path = replay.root.parent / "curator-reply.json"
    proc, _ = cf.run_hook(replay.root, replay.prepare(record), event=record["event"], reply=reply_path, env=env)
    assert proc.returncode == 0 and proc.stdout == b"" and proc.stderr == b""
    assert json.loads(reply_path.read_text(encoding="utf-8"))["degradations"] == ["curator_session_ignored"]
    assert spool.ready_segments(spool.SpoolDirs(replay.root)) == [] and gaps(replay.root) == []


def test_foreign_workspace_and_copied_checkout_capture_nothing(replay, tmp_path):
    record = cf.records("lifecycle")[1]
    outside = dict(record, payload=dict(record["payload"], cwd=str(tmp_path)))
    reply, _ = run_in_process(replay, outside)
    assert reply["degradations"] == ["foreign_workspace"] and reply["receipt"] is None
    assert [g["reason"] for g in gaps(replay.root)] == ["foreign_workspace"]
    copy = tmp_path / "copy"
    shutil.copytree(replay.root, copy, symlinks=True)
    reply_path = tmp_path / "copy-reply.json"
    proc, _ = cf.run_hook(copy, replay.prepare(record), event=record["event"], reply=reply_path)
    assert proc.returncode == 0 and proc.stdout == b""
    assert json.loads(reply_path.read_text(encoding="utf-8"))["degradations"] == ["installation_relocated"]
    assert spool.ready_segments(spool.SpoolDirs(copy)) == []


# ---------------------------------------------------------------------------
# A07: failure before durable publication; the host continues


@pytest.mark.parametrize("failpoint", [failpoints.SPOOL_TEMP_WRITE, failpoints.SPOOL_FSYNC, failpoints.SPOOL_RENAME])
def test_hook_capture_failure_is_not_acknowledged(replay, failpoint):
    record = next(r for r in cf.records("lifecycle") if r["event"] == "PostToolUseFailure")
    failpoints.arm(failpoint, failpoints.DISK_FULL)
    rc = entry.main(["--project", str(replay.root), "claude_code", "--event", record["event"], "--reply-file", str(replay.root.parent / "r.json")], stdin=io.BytesIO(replay.prepare(record)), env={})
    assert rc == 0  # the host continues
    reply = json.loads((replay.root.parent / "r.json").read_text(encoding="utf-8"))
    assert reply["receipt"]["status"] == "not_captured" and reply["receipt"]["error_code"] == "not_captured"
    assert "capture_not_acknowledged" in reply["degradations"]
    dirs = spool.SpoolDirs(replay.root)
    assert spool.ready_segments(dirs) == [] and list(dirs.tmp.iterdir()) == []
    assert [(g["code"], g["reason"]) for g in gaps(replay.root)] == [("not_captured", "disk_full")]
    assert not list(Path(session.sessions_dir(replay.root)).glob("*.json"))  # no overlay for an unacknowledged event
    assert pipeline.capture_health(replay.ctx)["gaps"] == {"not_captured:disk_full": 1}


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="POSIX directory permissions do not block root; the injected EACCES variant covers this platform")
def test_real_permission_failure_is_nonblocking(replay):
    record = cf.records("lifecycle")[1]
    ready = spool.SpoolDirs(replay.root)
    ready.ensure()
    os.chmod(ready.ready, 0o500)
    try:
        reply_path = replay.root.parent / "perm.json"
        proc, _ = cf.run_hook(replay.root, replay.prepare(record), event=record["event"], reply=reply_path)
        assert proc.returncode == 0 and proc.stdout == b"" and proc.stderr == b""
        assert json.loads(reply_path.read_text(encoding="utf-8"))["receipt"]["status"] == "not_captured"
    finally:
        os.chmod(ready.ready, 0o700)
    assert spool.ready_segments(ready) == []


# ---------------------------------------------------------------------------
# A58: one shared deadline; durable capture first; truthful overrun


def test_deadline_overrun_is_reported_and_optional_work_is_shed(replay):
    record = next(r for r in cf.records("lifecycle") if r["event"] == "PostToolUse")
    reply, ctx = run_in_process(replay, record, deadline=time.monotonic() - 1.0)  # already past the soft deadline
    assert reply["receipt"]["status"] == "accepted"  # durable capture is never abandoned for time
    assert "capture_deadline_overrun" in reply["degradations"] and "deadline_overlay_skipped" in reply["degradations"]
    assert len(spool.ready_segments(spool.SpoolDirs(replay.root))) == 1
    assert session.read_scratch(replay.root, reply_session(reply, replay)) is None  # the optional overlay was shed


def reply_session(reply, replay) -> str:
    seg = json.loads(spool.ready_segments(spool.SpoolDirs(replay.root))[-1].read_text(encoding="utf-8"))
    return seg["envelopes"][0]["session_id"]


OVERLAY_DEGRADATIONS = {"deadline_overlay_skipped", "scratch_lock_timeout", "scratch_lock_unsupported", "scratch_io_error"}


def test_scratch_outcomes_are_scrubbed_bounded_and_locked(replay, tmp_path):
    lifecycle = cf.records("lifecycle")
    for record in lifecycle[: [r["event"] for r in lifecycle].index("Stop")]:
        reply, _ = run_in_process(replay, record, deadline=time.monotonic() + 5)
        assert not set(reply["degradations"]) & OVERLAY_DEGRADATIONS, reply["degradations"]
    session_id = claude_capture.session_id_for(replay.ctx.installation_id, lifecycle[0]["payload"]["session_id"])
    scratch = session.read_scratch(replay.root, session_id)
    assert SessionScratch.model_validate(scratch)  # the strict model accepts the fast writer's file
    finished = [r for r in lifecycle if r["event"] in ("PostToolUse", "PostToolUseFailure")]
    assert len(scratch["outcomes"]) == len(finished) and scratch["state_revision"] == len(finished)
    assert [o["outcome"] for o in scratch["outcomes"]][:2] == ["success", "failure"]
    assert next(o for o in scratch["outcomes"] if o["action"]["tool"] == "Write")["changed_paths"] == ["new.txt"]
    # Bounded: at most 32 outcomes, counters never reset. This checks the bound and scrubbing, not latency: a
    # slow runner may shed the optional overlay at the 250 ms deadline (SYSTEM_SPEC §5.1.1; CI run 25 on Windows
    # shed 2 of 40), so these calls get a generous deadline and every reply must report the overlay updated.
    record = finished[0]
    for i in range(40):
        clone = dict(record, payload=dict(record["payload"], tool_use_id=f"toolu_bound_{i:03d}", tool_input={"command": f"echo password=hunter{i}-secret"}))
        reply, _ = run_in_process(replay, clone, deadline=time.monotonic() + 5)
        assert reply["receipt"]["status"] == "accepted" and not set(reply["degradations"]) & OVERLAY_DEGRADATIONS, reply["degradations"]
    scratch = session.read_scratch(replay.root, session_id)
    assert len(scratch["outcomes"]) == 32 and scratch["state_revision"] == len(finished) + 40
    assert b"hunter" not in Path(session.scratch_path(replay.root, session_id)).read_bytes()  # scrubbed
    # A held lock makes the overlay skip within 20 ms while capture still succeeds.
    lock = session.SessionLock(replay.root, session_id)
    assert lock.acquire(0.0)
    try:
        start = time.monotonic()
        reply, _ = run_in_process(replay, dict(record, payload=dict(record["payload"], tool_use_id="toolu_locked")))
        assert time.monotonic() - start < 0.25
        assert reply["receipt"]["status"] == "accepted" and "scratch_lock_timeout" in reply["degradations"]
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# A53: missing runtime


def _launcher(root: Path) -> list[str]:
    if os.name == "nt":
        return ["cmd", "/c", str(root / ".recalith" / "bin" / "recalith-hook.cmd"), "claude_code"]
    return ["sh", str(root / ".recalith" / "bin" / "recalith-hook"), "claude_code"]


def _tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


def test_missing_runtime_is_nonblocking(replay):
    """A53 preview: an unprovisioned clone's hook is an empty nonblocking success, no download, no repeated hint."""
    record = cf.records("lifecycle")[1]
    data = replay.prepare(record)
    before = _tree(replay.root)
    env = {k: v for k, v in cf.child_env().items() if k not in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")}
    env.update({"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9"})  # any download attempt would fail loudly
    for _ in range(3):
        start = time.perf_counter()
        proc = subprocess.run(_launcher(replay.root), input=data, capture_output=True, env=env, timeout=30, check=False)
        assert proc.returncode == 0 and proc.stdout == b"" and proc.stderr == b""  # no output, no hint, never blocking
        assert time.perf_counter() - start < 5
    assert _tree(replay.root) == before  # nothing written, provisioned or downloaded
    assert spool.ready_segments(spool.SpoolDirs(replay.root)) == []


@pytest.mark.skipif(os.environ.get("RECALITH_SKIP_VENV_TESTS") == "1", reason="venv creation disabled by the environment")
def test_provisioned_runtime_launcher_reaches_the_fast_entry(replay):
    """The same launcher, once the pinned runtime exists, runs the stdlib entry and captures."""
    venv = replay.root / ".recalith" / "runtime" / identity.__version__ / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True, timeout=120)
    site = next(venv.rglob("site-packages"))
    (site / "recalith_src.pth").write_text(cf.SRC + "\n", encoding="utf-8")
    record = cf.records("lifecycle")[1]
    proc = subprocess.run(_launcher(replay.root) + ["--event", record["event"]], input=replay.prepare(record), capture_output=True, env=cf.child_env(), timeout=60, check=False)
    assert proc.returncode == 0 and proc.stdout == b"" and proc.stderr == b""
    assert len(spool.ready_segments(spool.SpoolDirs(replay.root))) == 1


# ---------------------------------------------------------------------------
# A68: head/tail and error signature on real serialized events


def _finish(scenario: str, command: str) -> dict:
    call = tool_calls(scenario)[command]
    return next(r for r in cf.records(scenario) if r["event"] in ("PostToolUse", "PostToolUseFailure") and r["payload"]["tool_use_id"] == call)


def _chunk_ok(text: str, chunk: dict) -> bool:
    return text[chunk["original_start"]:chunk["original_end"]] == chunk["text"]


def test_head_tail_keeps_failure_line(replay, tmp_path):
    passing = _finish("lifecycle", "pytest -q -s test_pass.py")  # 24 KB real stdout, summary on the last line
    mid = _finish("lifecycle", "pytest -q test_mid.py")  # real failure, host middle-truncated, tail kept
    long = _finish("lifecycle", "pytest -q test_long.py")  # real failure whose tail the host discarded
    # The same 2.1.301 PostToolUseFailure shape with a 40 KB error that ends in the failing assertion.
    lines = [f"progress line {i:04d} ünïcødé ✓ " + "x" * 30 for i in range(800)]
    failing = "FAILED tests/test_big.py::test_end - AssertionError: boom at the very end"
    error = "Exit code 1\n" + "\n".join(lines + ["=========================== short test summary info ============================", failing, "========================= 1 failed, 3 passed in 0.42s ========================="])
    built = dict(mid, payload=dict(mid["payload"], tool_use_id="toolu_constructed_big", tool_input={"command": "pytest -q tests/test_big.py", "description": "constructed"}, error=error))
    for record in (passing, mid, long, built):
        proc, _ = cf.run_hook(replay.root, replay.prepare(record), event=record["event"])
        assert proc.returncode == 0 and proc.stdout == b""
    pipeline.ingest_ready(replay.ctx)
    events = {e.payload["tool_call_id"]: e for e in stored_events(replay.root) if e.kind == "tool_finished"}

    p = events[passing["payload"]["tool_use_id"]]
    original = passing["payload"]["tool_response"]["stdout"]
    head, tail = p.payload["text_chunks"]
    assert p.coverage.truncated and "result_text_bounded" in p.extensions["claude_code"]["coverage_warnings"]
    assert tail["text"].rstrip().endswith("1 passed in " + original.rsplit("1 passed in ", 1)[1].strip())
    assert _chunk_ok(original, head) and _chunk_ok(original, tail) and head["original_start"] == 0 and tail["original_end"] == len(original)
    assert [a["identity"] for a in p.payload["assertions"]] == ["pytest:session"] and p.payload["assertions"][0]["passed"] is True

    m = events[mid["payload"]["tool_use_id"]]
    assert m.payload["exit_code"] == 1 and m.payload["error_signature"].startswith("FAILED test_mid.py::test_mid - AssertionError")
    assert m.coverage.truncated and m.coverage.missing_context  # the host omitted the middle
    assert {"exit_status", "test_result"} <= {a["kind"] for a in m.payload["assertions"]}

    lost = events[long["payload"]["tool_use_id"]]
    assert lost.payload["error_signature"] is None and lost.coverage.truncated and lost.coverage.missing_context
    assert lost.coverage.parser_complete is False  # an honest gap: the host discarded the tail before any hook saw it

    b = events["toolu_constructed_big"]
    text = error[len("Exit code 1\n"):]
    head, tail = b.payload["text_chunks"]
    assert b.payload["error_signature"] == failing and b.payload["exit_code"] == 1
    assert failing in tail["text"] and _chunk_ok(text, head) and _chunk_ok(text, tail) and tail["original_end"] == len(text)
    assert len(strict_canonical(b.payload)) <= 64 * 1024 and "[recalith:" in b.payload["result_text"]
    b.payload["result_text"].encode("utf-8")  # valid Unicode after every cut


# ---------------------------------------------------------------------------
# A70: argument arrays only when unambiguous


@pytest.mark.parametrize(
    ("command", "argv"),
    [
        ("pytest -q tests/test_x.py", ["pytest", "-q", "tests/test_x.py"]),
        ('python -m pytest "tests/a b.py"', ["python", "-m", "pytest", "tests/a b.py"]),
        ("printf '%s\\n' ok | tr a-z A-Z", None),
        ("FOO=1 pytest", None),
        ("pytest > out.txt", None),
        ("cd sub && pytest", None),
        ("pytest $ARGS", None),
        ("pytest tests/*.py", None),
        ('python -c "import sys; sys.exit(1)"', None),
        ("echo 'unterminated", None),
        ("dir C:\\Users", None),
        ("", None),
    ],
)
def test_command_parse_is_exact_or_unknown(command, argv):
    assert claude_capture.parse_posix_command(command) == argv


def test_ambiguous_and_unregistered_tools_never_guess(replay, tmp_path):
    record = next(r for r in cf.records("lifecycle") if r["event"] == "PreToolUse")
    pipeline_cmd = dict(record, payload=dict(record["payload"], tool_use_id="toolu_pipe", tool_input={"command": "pytest -q | tee log"}))
    powershell = dict(record, payload=dict(record["payload"], tool_use_id="toolu_ps", tool_name="PowerShell", tool_input={"command": "Get-ChildItem; pytest"}))
    for rec in (pipeline_cmd, powershell):
        run_in_process(replay, rec)
    pipeline.ingest_ready(replay.ctx)
    actions = {e.payload["tool_call_id"]: e.payload["action"] for e in stored_events(replay.root)}
    assert actions["toolu_pipe"]["parse_status"] == "unknown" and actions["toolu_pipe"]["argv"] is None and actions["toolu_pipe"]["executable"] is None
    assert actions["toolu_pipe"]["raw_digest"] is not None
    assert actions["toolu_ps"]["parse_status"] == "conservative" and actions["toolu_ps"]["argv"] is None


# ---------------------------------------------------------------------------
# Fast and strict validation agree


def _envelope_fixtures():
    base = cf.ROOT / "tests" / "fixtures" / "contracts" / "envelopes"
    for path in sorted(base.glob("*/*.json")):
        yield path.parent.name, path.name, json.loads(path.read_text(encoding="utf-8"))["envelope"]


def _mutations(envelope: dict):
    """Single-field mutations of a valid envelope: removal, wrong type, extra field, nested damage."""
    for key in envelope:
        yield f"drop:{key}", {k: v for k, v in envelope.items() if k != key}
        for bad in (None, True, 7, "x", [], {}):
            if type(bad) is not type(envelope[key]) or bad != envelope[key]:
                yield f"set:{key}={bad!r}", dict(envelope, **{key: bad})
    for channel in ("user", "assistant", "tool", "external", "memory"):
        for authority in ("untrusted", "observed_tool", "explicit_user", "derived"):
            yield f"route:{channel}/{authority}", dict(envelope, channel=channel, authority=authority)
    for kind in ("session_started", "user_message", "assistant_message", "tool_started", "tool_finished", "compaction", "memory_delivered", "agent_attempted_operator_command", "operator_forget", "generic_observation"):
        yield f"kind:{kind}", dict(envelope, kind=kind)
        yield f"kind+root:{kind}", dict(envelope, kind=kind, root_event_ids=[envelope["event_id"]])
    yield "extra", dict(envelope, unexpected=1)
    yield "origin.extra", dict(envelope, origin=dict(envelope["origin"], extra=1))
    yield "coverage.int", dict(envelope, coverage=dict(envelope["coverage"], truncated=0))
    yield "extensions.foreign", dict(envelope, extensions={"other": {}})
    yield "extensions.badkey", dict(envelope, extensions={"Bad Key": {}})
    yield "root.other", dict(envelope, root_event_ids=["evt_" + "0" * 64])
    yield "time.calendar", dict(envelope, recorded_at="2026-02-30T00:00:00.000000Z")
    yield "id.prefix", dict(envelope, session_id="nope_" + "0" * 64)
    if isinstance(envelope.get("payload"), dict) and "action" in envelope["payload"]:
        p = envelope["payload"]
        yield "action.unknown-with-argv", _with_payload(envelope, dict(p, action=dict(p["action"], parse_status="unknown")))
        yield "assertion.non-canonical", _with_payload(envelope, dict(p, assertions=[{"kind": "exit_status", "identity": "e", "value": "01", "passed": None}]))
        yield "assertion.verdict", _with_payload(envelope, dict(p, assertions=[{"kind": "exit_status", "identity": "e", "value": "1", "passed": True}]))
        yield "chunk.span", _with_payload(envelope, dict(p, text_chunks=[{"stored_field": "f", "source_field": "f", "original_start": 0, "original_end": 3, "text": "ab", "text_digest": "0" * 64}]))
        yield "path.escape", _with_payload(envelope, dict(p, action=dict(p["action"], paths=["../x"])))
        yield "argv.long", _with_payload(envelope, dict(p, action=dict(p["action"], argv=["x" * 8193])))


def _with_payload(envelope: dict, payload: dict) -> dict:
    return dict(envelope, payload=payload, payload_digest=wire.digest_of(payload), origin=dict(envelope["origin"], source_digest=wire.digest_of(payload)))


def _strict_ok(model, value) -> bool:
    try:
        model.model_validate(value)
    except Exception:  # noqa: BLE001 - any rejection is a rejection
        return False
    return True


def test_fast_and_strict_validation_agree(replay, tmp_path):
    # 1. The shared wire fixtures and a mutation corpus around every valid fixture.
    checked = 0
    for group, name, envelope in _envelope_fixtures():
        fast = wire.is_valid("EventEnvelope", envelope)
        assert fast == _strict_ok(EventEnvelope, envelope) == (group == "valid"), name
        if group == "valid":
            for label, mutated in _mutations(envelope):
                assert wire.is_valid("EventEnvelope", mutated) == _strict_ok(EventEnvelope, mutated), (name, label)
                checked += 1
    assert checked >= 800
    # 2. Every real 2.1.301 payload normalizes to byte-identical envelopes on both paths.
    wire_ctx = ctx_dict(replay)
    ids = {k: wire_ctx[k] for k in ("project_id", "installation_id", "workspace_id")}
    compared = 0
    for scenario in ("lifecycle", "subagent", "denied", "secret_and_resume"):
        for record in cf.records(scenario):
            if record["event"] not in claude_capture.ROLES:
                continue
            payload = json.loads(replay.prepare(record))
            request = claude_capture.map_hook(wire_ctx, payload, registered_event=record["event"], recorded_at="2026-10-16T00:00:00.000000Z")
            for raw in request["raw_events"]:
                fast_envs, fast_notes = normalize_raw(ids, raw)
                strict_envs, strict_notes = normalize_event(replay.ctx, raw)
                assert [wire.canonical_json(e) for e in fast_envs] == [strict_canonical(e) for e in strict_envs], record["event"]
                assert fast_notes.warnings == strict_notes.warnings and fast_notes.coverage() == strict_notes.coverage()
                assert all(wire.is_valid("EventEnvelope", e) for e in fast_envs)
                compared += 1
    assert compared >= 60
    # 3. Segments and receipts the fast path wrote are valid strict objects, and damaged ones fail on both.
    cf.replay(replay, "lifecycle", tmp_path)
    for path in spool.ready_segments(spool.SpoolDirs(replay.root)):
        segment = json.loads(path.read_text(encoding="utf-8"))
        assert wire.is_valid("Segment", segment) and _strict_ok(Segment, segment)
        for label, bad in (("digest", dict(segment, content_digest="0" * 64)), ("foreign", dict(segment, installation_id="inst_" + "1" * 64)), ("empty", dict(segment, envelopes=[])), ("extra", dict(segment, extra=True))):
            assert wire.is_valid("Segment", bad) is False and _strict_ok(Segment, bad) is False, label
    # 4. The transcript supplement normalizes identically on both paths.
    parse = claude_capture.transcript_line_parser(replay.ctx.installation_id)
    for line in (FIXTURES / "lifecycle.transcript.jsonl").read_text(encoding="utf-8").splitlines():
        for raw in parse(json.loads(line), None):
            raw.recorded_at = "2026-10-16T00:00:00.000000Z"
            assert [wire.canonical_json(e) for e in normalize_raw(ids, raw)[0]] == [strict_canonical(e) for e in normalize_event(replay.ctx, raw)[0]]


# ---------------------------------------------------------------------------
# Crash protocol on the fast-path producer with real payloads


@pytest.mark.parametrize("failpoint", [failpoints.SPOOL_TEMP_WRITE, failpoints.SPOOL_FSYNC, failpoints.SPOOL_RENAME, failpoints.SPOOL_AFTER_RENAME, failpoints.SPOOL_AFTER_PUBLISH])
def test_real_payload_kill_matches_reference(tmp_path, failpoint):
    """Kill the real entry at each spool failpoint; the reopened store equals a reference run minus unacknowledged loss."""
    records = [r for r in cf.records("lifecycle") if r["event"] in claude_capture.ROLES]
    victim = len(records) // 2
    work = tmp_path / "run"  # both runs use the same paths: host error text embeds the workspace path

    def run(kill: bool):
        if work.exists():
            shutil.rmtree(work)
        work.mkdir()
        replayer = cf.Replay(work)
        victim_key = None
        for index, record in enumerate(records):
            if kill and index == victim:
                argv = [sys.executable, "-I", "-c", "import sys\nfrom recalith.fast import entry, failpoints\nfailpoints.arm(sys.argv[1], failpoints.kill)\nsys.exit(entry.main(sys.argv[2:]))", failpoint, "--project", str(replayer.root), "claude_code", "--event", record["event"]]
                proc = subprocess.run(argv, input=replayer.prepare(record), capture_output=True, env=cf.child_env(), timeout=60, check=False)
                assert proc.returncode == failpoints.KILL_STATUS, proc.stderr[-2000:]
            else:
                cf.run_hook(replayer.root, replayer.prepare(record), event=record["event"])
        pipeline.ingest_ready(replayer.ctx)
        spool.cleanup_stale_temps(spool.SpoolDirs(replayer.root), older_than=0)
        dirs = spool.SpoolDirs(replayer.root)
        assert spool.ready_segments(dirs) == [] and list(dirs.tmp.iterdir()) == [] and list(dirs.quarantine.iterdir()) == []
        return [(e.source_event_key, e.payload_digest) for e in stored_events(replayer.root)], victim_key

    reference, _ = run(kill=False)
    crashed, _ = run(kill=True)
    published = failpoint in (failpoints.SPOOL_AFTER_RENAME, failpoints.SPOOL_AFTER_PUBLISH)
    expected = sorted(reference) if published else sorted(k for i, k in enumerate(reference) if i != victim)
    assert sorted(crashed) == expected  # killed before publication: lost unacknowledged (hosts do not retry hooks); after: exactly once


# ---------------------------------------------------------------------------
# The installed host, end to end (request-capture mode; skipped without the CLI)


def _installed_claude() -> str | None:
    exe = shutil.which("claude")
    if not exe:
        return None
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False).stdout
    return exe if cf.VERSION in out else None


@pytest.mark.skipif(_installed_claude() is None, reason=f"Claude Code {cf.VERSION} CLI is not installed here; replayed real fixtures cover this platform")
def test_installed_host_session_captures_through_real_hooks(tmp_path):
    """Owned capture-only hooks run the real entry inside a live Claude Code process (loopback scripted model)."""
    sys.path.insert(0, str(cf.ROOT / "tools"))
    import capture_claude_fixtures as cap
    import probe_common as pc
    import probe_delivery as pd

    base = tmp_path / "host"
    base.mkdir()
    ws, home = cap.make_workspace(base)
    identity.initialize_installation(ws, cf.ProjectConfig.defaults_for(cf.PROJECT_ID))
    ctx = identity.resolve_installation(ws, actor=cf.ADAPTER_ACTOR)
    cf.write_hook_context(ctx, adapter_id="claude_code", host_version=cf.VERSION)
    settings = ws / ".claude" / "settings.local.json"
    pd._write_settings(settings, cap.unrelated_settings())
    before = settings.read_text(encoding="utf-8")
    entries = []
    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "PreCompact", "PostCompact", "Stop", "SubagentStop", "SessionEnd", "PermissionRequest"):
        command = " ".join(json.dumps(x) for x in cf.hook_command(ws, event))
        entries.append((event, "*" if "Tool" in event or event == "PermissionRequest" else None, command))
    manifest = pd.install_owned_hooks(settings, entries, timeout_s=10)
    try:
        with pc.RecordingEndpoint(cap.responder_for(ws)) as endpoint:
            result = cap.run_scenario(_installed_claude(), "lifecycle", ws, home, endpoint.url, None)
    finally:
        cleanup = pd.remove_owned_hooks(manifest)
    assert cleanup["unrelated_preserved"] and settings.read_text(encoding="utf-8") == before
    assert result["returncode"] == 0 and not result["timed_out"]
    ingest = pipeline.ingest_ready(ctx)
    events = stored_events(ws)
    kinds = {e.kind for e in events}
    assert {"session_started", "user_message", "tool_started", "tool_finished", "compaction", "session_stopped", "session_ended"} <= kinds
    assert ingest.accepted == len(events) and ingest.conflict == 0
    assert {e.host_session_id for e in events} == {result["session_id"]}


def test_hook_capture_refuses_unscrubbed_envelopes_from_other_callers(replay):
    """Only envelopes normalized in the same call skip the re-scan; anything else is re-checked."""
    ctx = ctx_dict(replay)
    record = cf.records("lifecycle")[1]
    request = claude_capture.map_hook(ctx, json.loads(replay.prepare(record)), registered_event=record["event"])
    (envelope,) = normalize_raw(ctx, request["raw_events"][0])[0]
    leaked = dict(envelope["payload"], text="token=" + "s3cr3t" + "-value-123456")
    envelope = dict(envelope, payload=leaked, payload_digest=wire.digest_of(leaked))
    receipt = entry.hook_capture(ctx, [envelope])
    assert receipt["status"] == "not_captured" and receipt["coverage"]["rejected"] == {"invalid_schema": 1}
    assert spool.ready_segments(spool.SpoolDirs(replay.root)) == []
