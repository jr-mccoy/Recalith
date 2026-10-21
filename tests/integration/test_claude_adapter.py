"""Task 13 (preview): ``recalith integrate claude``, the installed hooks, delivery gating and health (decision 0019).

Acceptance: A08 (transcript supplement through installed hooks), A27/A61
(only certified paths are enabled; a request-capture record certifies none),
A29 (B1 stays visible), A33 (paths with spaces/Unicode), A47 (unknown host
version: conservative, no delivery, no notice), A53 (local install by default,
ignored location, owned-entry removal with unrelated settings preserved, the
absent-runtime clone), A58 (the installed hook stays nonblocking and bounded),
A65 (private-path probe reported, never installed in preview), A73 (marked
callers refused before any effect). Every CLI call is a real child process
with an explicitly provisioned fixture token; every hook is the real entry
behind the installed launcher command. Synthetic states are named in
``claude_scenarios``.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

import claude_scenarios as ccs  # first: puts tests/ and tests/platform on sys.path
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import cli_scenarios as cs  # noqa: E402
import health_scenarios as hs  # noqa: E402
import claude_fixtures as cf  # noqa: E402
from recalith import service  # noqa: E402
from recalith.capture import pipeline  # noqa: E402
from recalith.contracts.common import Actor  # noqa: E402
from recalith.core import identity  # noqa: E402
from recalith.fast import claude as fast_claude, claude_capture, entry, process_env, session, spool  # noqa: E402
from recalith.integrations import claude as integration, install  # noqa: E402

POSIX = os.name != "nt"
posix = pytest.mark.skipif(not POSIX, reason="the installed hook command is a POSIX shell command; native Windows host execution is uncertified (decision 0019); the installer's effects run natively on every platform")
OPERATOR = Actor(kind="operator", id="terminal", channel="cli")


@pytest.fixture(autouse=True)
def _no_leaked_worker(tmp_path):
    """Hooks here run with autostart off; a worker left running under this test's directory is a leak: stop it and fail."""
    yield
    import probe_engine as pe

    leaked = [d.parent for d in tmp_path.rglob(".recalith") if d.is_dir() and process_env.worker_running(str(d.parent))]
    for root in leaked:
        pe.stop_worker(root)
    assert not leaked, f"a test left a worker running: {leaked}"


@pytest.fixture
def provisioned(tmp_path):
    root = ccs.project(tmp_path, "proj with space é")
    cs.provision_runtime(root)
    return root, ccs.Operator(root, tmp_path)


def ok(result: cs.Result) -> dict:
    assert result.code == 0, (result.code, result.stdout, result.stderr)
    return result.obj["result"]


# --------------------------------------------------------------------------
# Local install (A53)


@pytest.mark.skipif(not ccs.has_git(), reason="git is needed to show the settings file is ignored")
def test_local_install_is_default_and_ignored(provisioned):
    root, op = provisioned
    before = (root / ccs.SETTINGS).read_bytes()
    result = ok(op.integrate())
    assert result["scope"] == "local" and result["settings_path"] == ".claude/settings.local.json"
    data = ccs.settings(root)
    groups = ccs.owned_groups(data)
    assert set(groups) == {event for event, _matcher in fast_claude.HOOK_EVENTS}
    for event, matcher in fast_claude.HOOK_EVENTS:
        (group,) = groups[event]
        assert group.get("matcher") == matcher
        (hook,) = group["hooks"]
        assert hook == {"type": "command", "command": fast_claude.hook_command(event), "timeout": fast_claude.HOOK_TIMEOUT_SECONDS}
        assert hook["command"].startswith('"$CLAUDE_PROJECT_DIR"/.recalith/bin/recalith-hook claude_code --event ')  # the pinned project launcher
    # Unrelated entries are untouched and every owned entry is recorded exactly.
    record = ccs.ownership(root)
    assert ccs.without_owned(data, record["owned"]["deny"]) == json.loads(before)
    assert record["state"] == "installed" and record["scope"] == "local"
    assert [o["event"] for o in record["owned"]["hooks"]] == [e for e, _m in fast_claude.HOOK_EVENTS]
    assert all(o["group"] == groups[o["event"]][0] for o in record["owned"]["hooks"])
    assert set(record["owned"]["deny"]) <= set(data["permissions"]["deny"]) and "Bash(rm -rf:*)" not in record["owned"]["deny"]
    assert data["permissions"]["allow"] == ccs.UNRELATED["permissions"]["allow"]  # existing controls never loosened
    # The location is explicitly ignored (the project .gitignore line is owned and recorded) and never tracked.
    assert "/.claude/settings.local.json" in (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert record["owned"]["gitignore"]["line"] == "/.claude/settings.local.json"
    assert ccs.git(root, "check-ignore", "-q", ".claude/settings.local.json").returncode == 0
    assert result["ignored"] == "verified"
    # The manifest: worker start registered, notices on, no delivery path without a live certification.
    m = ccs.manifest(root)
    assert m["context_schema"] == 4 and m["worker"]["autostart"] is True and m["notices"] == {"session_start": True}
    assert m["adapters"]["claude_code"] == {"host_version": ccs.VERSION, "delivery_enabled": False, "delivery_paths": []}
    assert result["delivery_paths"] == [] and "delivery_not_certified" in result["delivery_reasons"]
    assert result["private_paths"]["state"] == "not_run" and result["private_paths"]["installed_rules"] == "unavailable_in_preview"
    assert result["os_startup_entries"] == {"state": "unavailable", "reason": "deferred_full_release"}
    # Files are private.
    for rel in (ccs.SETTINGS, ccs.OWNERSHIP, ccs.MANIFEST):
        assert not POSIX or (root / rel).stat().st_mode & 0o077 == 0, rel


def test_rerun_is_idempotent_and_installs_no_duplicates(provisioned):
    root, op = provisioned
    ok(op.integrate())
    first = (root / ccs.SETTINGS).read_bytes()
    again = ok(op.integrate())
    assert again["settings"] == "unchanged" and (root / ccs.SETTINGS).read_bytes() == first
    assert all(len(v) == 1 for v in ccs.owned_groups(ccs.settings(root)).values())
    assert (root / ".gitignore").read_text(encoding="utf-8").splitlines().count("/.claude/settings.local.json") == 1


@pytest.mark.parametrize("raw", [None, b'{"theme":"light","permissions":{"deny":["Read(./x/**)"]}}', b"{\n\t\"theme\": \"light\"\n}\n"], ids=["claude-format", "compact", "tabs"])
def test_remove_restores_unrelated_settings_byte_for_byte(tmp_path, raw):
    root = ccs.project(tmp_path, "rm", raw=raw)
    op = ccs.Operator(root, tmp_path)
    gitignore = root / ".gitignore"
    gitignore.write_text("node_modules/\n", encoding="utf-8")
    before, ignore_before = (root / ccs.SETTINGS).read_bytes(), gitignore.read_bytes()
    ok(op.integrate())
    result = ok(op.remove())
    assert result["removed"]["hooks"] == len(fast_claude.HOOK_EVENTS) and result["modified"] == [] and result["unrelated_preserved"] == "byte_identical"
    assert (root / ccs.SETTINGS).read_bytes() == before and gitignore.read_bytes() == ignore_before
    assert ccs.ownership(root) is None and ccs.manifest(root) is None
    assert not list((root / ".recalith" / "run" / "integrations").glob("*")), "the private before-copy is removed with the record"


def test_remove_without_prior_settings_leaves_nothing(tmp_path):
    root = ccs.project(tmp_path, "fresh", unrelated=None)
    op = ccs.Operator(root, tmp_path)
    ok(op.integrate())
    assert (root / ccs.SETTINGS).exists() and (root / ".gitignore").exists()
    ok(op.remove())
    assert not (root / ccs.SETTINGS).exists() and not (root / ".claude").exists() and not (root / ".gitignore").exists()


def test_modified_owned_entries_are_reported_for_reconciliation(provisioned):
    root, op = provisioned
    ok(op.integrate())
    data = ccs.settings(root)
    data["hooks"]["Stop"][-1]["hooks"][0]["timeout"] = 99  # the user edited an owned entry
    data["permissions"]["deny"].append("Bash(curl:*)")  # and added an unrelated rule afterwards
    (root / ccs.SETTINGS).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    removed = op.remove()
    assert removed.code == 8 and removed.obj["degraded"] == ["owned_entries_modified"], removed.stdout
    result = removed.obj["result"]
    assert result["modified"] == [{"kind": "hook", "event": "Stop"}]
    after = ccs.settings(root)
    assert set(ccs.owned_groups(after)) == {"Stop"} and after["hooks"]["Stop"][-1]["hooks"][0]["timeout"] == 99
    assert "Bash(curl:*)" in after["permissions"]["deny"] and after["hooks"]["UserPromptSubmit"] == ccs.UNRELATED["hooks"]["UserPromptSubmit"]
    assert ccs.ownership(root)["state"] == "reconcile"
    blocked = op.integrate()
    assert blocked.code == 3 and blocked.obj["error"] == "revision_conflict", blocked.stdout  # never a second copy beside an edited one
    assert len(ccs.owned_groups(ccs.settings(root))["Stop"]) == 1
    after["hooks"]["Stop"] = [g for g in after["hooks"]["Stop"] if ccs.LAUNCHER_MARK not in json.dumps(g)]
    (root / ccs.SETTINGS).write_text(json.dumps(after, indent=2) + "\n", encoding="utf-8")
    final = ok(op.remove())
    assert final["missing"] == [{"kind": "hook", "event": "Stop"}] and ccs.ownership(root) is None
    assert "Bash(curl:*)" in ccs.settings(root)["permissions"]["deny"]


@pytest.mark.skipif(not ccs.has_git(), reason="needs git to track the settings file")
def test_tracked_settings_are_refused(tmp_path):
    root = ccs.project(tmp_path, "tracked")
    op = ccs.Operator(root, tmp_path)
    assert ccs.git(root, "add", "-f", str(ccs.SETTINGS)).returncode == 0
    before = cs.tree(root)
    refused = op.integrate()
    assert refused.code == 6 and refused.obj["error"] == "policy_refused" and "tracked" in refused.obj["message"]
    assert cs.tree(root) == before


@pytest.mark.parametrize("flag", ["--autostart", "--shared"])
def test_full_only_flags_pass_the_guard_then_answer_unavailable(provisioned, flag):
    root, op = provisioned
    before = cs.tree(root)
    result = op.integrate(flag)
    assert result.code == 4 and result.obj["error"] == "capability_unavailable", result.stdout
    assert cs.tree(root) == before
    marked = op.integrate(flag, env=op.env(CLAUDECODE="1"))
    assert marked.code == 6 and marked.obj["refusal"]["category"] == "host_marker"


@pytest.mark.parametrize("marker", sorted(cs.MARKERS))
@pytest.mark.parametrize("form", [("integrate", "claude"), ("integrate", "claude", "--remove"), ("doctor", "--probe-host", "claude")])
def test_marked_callers_are_refused_before_any_effect(provisioned, marker, form):
    root, op = provisioned
    ok(op.integrate())
    before = cs.tree(root)
    result = op.run(*form, env=op.env(**{marker: cs.marked_env(marker, root)[marker]}))
    assert result.code == 6 and result.obj["refusal"]["category"] == cs.MARKERS[marker]
    assert cs.tree(root) == before


def test_probe_host_is_guarded_and_names_the_operator_harness(provisioned):
    root, op = provisioned
    result = op.run("doctor", "--probe-host", "claude")
    assert result.code == 4 and "tools/probe_delivery.py" in result.obj["message"], result.stdout


def test_unknown_host_is_refused_without_effect(provisioned):
    root, op = provisioned
    before = cs.tree(root)
    result = op.run("integrate", "codex")
    assert result.code == 4 and cs.tree(root) == before


# --------------------------------------------------------------------------
# Delivery gating: only certified paths (A27/A61/A47)


def test_only_live_certified_paths_are_enabled(provisioned):
    root, op = provisioned
    inst = cs.context(root).installation_id
    ccs.live_record(root, inst, mode="request_capture", delivery={"session_start": "unavailable", "prompt": "unavailable"})
    assert ok(op.integrate())["delivery_paths"] == []
    ccs.live_record(root, inst, mode="request_capture", delivery={"pre_action": "certified"})  # even a request-capture record that says certified
    result = ok(op.integrate())
    assert result["delivery_paths"] == [] and "delivery_request_capture_only" in result["delivery_reasons"]
    ccs.live_record(root, inst, delivery={"pre_action": "certified"})  # synthetic live record
    result = ok(op.integrate())
    assert result["delivery_paths"] == ["session_start", "prompt", "pre_action"]
    assert ccs.manifest(root)["adapters"]["claude_code"] == {"host_version": ccs.VERSION, "delivery_enabled": True, "delivery_paths": ["session_start", "prompt", "pre_action"]}
    ccs.live_record(root, inst, version="2.1.301")  # certified for another host version: none enabled
    assert ok(op.integrate())["delivery_paths"] == []
    ccs.live_record(root, "inst_77777777-7777-4777-8777-777777777777")  # another installation's record
    result = ok(op.integrate())
    assert result["delivery_paths"] == [] and "host_certification_invalid" in result["delivery_reasons"]


@posix
def test_unknown_host_version_is_conservative(provisioned, tmp_path):
    root, op = provisioned
    op.set_version("2.1.399")
    ccs.live_record(root, cs.context(root).installation_id, version="2.1.399")  # even a (synthetic) record cannot enable it
    result = ok(op.integrate())
    assert result["host"]["capture"] == "conservative" and result["delivery_paths"] == []
    with_worker_off(root)
    rec = ccs.fixture_records(ccs.VERSION, "lifecycle")[0]
    payload = ccs.Payloads(root, tmp_path).prepare(rec)
    proc = ccs.run_installed(root, rec["event"], payload)
    ccs.never_blocks(proc)
    assert proc.stdout == b""  # no notice, no context on an uncertified version
    pipeline.ingest_ready(cs.context(root))
    events = cs.store_rows(root)["counts"]["events"]
    assert events >= 1  # still captured, conservatively


def test_missing_executable_records_unknown_version(provisioned, tmp_path):
    root, op = provisioned
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    env = cs.base_env(PATH=str(empty) + os.pathsep + "/usr/bin" + os.pathsep + "/bin")
    result = op.integrate(env=env)
    assert result.code == 0, result.stdout
    assert result.obj["result"]["host"] == {"executable": None, "version": None, "capture": "unknown"}
    assert ccs.manifest(root)["adapters"]["claude_code"]["host_version"] is None


# --------------------------------------------------------------------------
# The installed hooks (A08, A53, A58)


@posix
def test_installed_hooks_capture_real_lifecycle_and_transcripts(provisioned, tmp_path):
    root, op = provisioned
    ok(op.integrate())
    with_worker_off(root)
    payloads = ccs.Payloads(root, tmp_path)
    for rec in ccs.fixture_records(ccs.VERSION, "lifecycle") + ccs.fixture_records(ccs.VERSION, "subagent"):
        proc = ccs.run_installed(root, rec["event"], payloads.prepare(rec))
        ccs.never_blocks(proc)
    ctx = cs.context(root)
    pipeline.ingest_ready(ctx)
    from recalith.storage import db

    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        kinds = {r[0] for r in view.execute("SELECT kind FROM events").fetchall()}
        sources = view.execute("SELECT source_kind, locator FROM capture_sources").fetchall()
        subagents = view.execute("SELECT COUNT(*) FROM events WHERE kind = 'session_started' AND payload LIKE '%\"scope\":\"subagent\"%'").fetchone()[0]
    assert {"session_started", "user_message", "tool_started", "tool_finished", "compaction", "session_stopped", "session_ended"} <= kinds
    assert sources and all(kind == "transcript_jsonl" for kind, _ in sources)
    assert any("/subagents/agent-" in loc for _p, loc in sources), "the subagent transcript is registered by its exact path"
    assert subagents >= 1


def with_worker_off(root: Path) -> None:
    """Captures in these tests are judged without a worker (the manifest's consent stays as integrate wrote it in the next run)."""
    from recalith.capture.hooks import write_hook_context

    write_hook_context(cs.context(root), adapter_id="claude_code", host_version=ccs.manifest(root)["adapters"]["claude_code"]["host_version"], worker_autostart=False)


@posix
def test_curator_session_is_ignored(provisioned, tmp_path):
    root, op = provisioned
    ok(op.integrate())
    payloads = ccs.Payloads(root, tmp_path)
    inst = cs.context(root).installation_id
    for rec in ccs.fixture_records(ccs.VERSION, "lifecycle")[:6]:
        proc = ccs.run_installed(root, rec["event"], payloads.prepare(rec), env=ccs.host_env(root, **{process_env.CURATOR_MARKER: inst}))
        assert proc.returncode == 0 and proc.stdout == b"" and proc.stderr == b""
    assert spool.ready_segments(spool.SpoolDirs(root)) == []
    assert not process_env.worker_running(str(root)), "a curator-owned session never starts a worker"
    assert not (root / ".recalith" / "run" / fast_claude.NOTICE_FILE).exists()


FAILURES = ["manifest_corrupt", "store_unreadable", "spool_blocked", "runtime_missing", "payload_malformed", "payload_oversized", "entry_crash"]


@posix
@pytest.mark.parametrize("failure", FAILURES)
def test_hook_failure_never_denies_tool(provisioned, tmp_path, failure):
    root, op = provisioned
    inst = cs.context(root).installation_id
    ccs.live_record(root, inst, delivery={"pre_action": "certified"})  # synthetic: delivery enabled so the delivery branch is exercised
    ok(op.integrate())
    with_worker_off(root)
    rec = next(r for r in ccs.fixture_records(ccs.VERSION, "lifecycle") if r["event"] == "PreToolUse")
    payload = ccs.Payloads(root, tmp_path).prepare(rec)
    env = ccs.host_env(root)
    if failure == "manifest_corrupt":
        (root / ccs.MANIFEST).write_text("{not json", encoding="utf-8")
    elif failure == "store_unreadable":
        (root / ".recalith" / "state" / "memory.sqlite").write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)
    elif failure == "spool_blocked":
        cs.block_spool(root)
    elif failure == "runtime_missing":
        shutil.rmtree(root / ".recalith" / "runtime")
    elif failure == "payload_malformed":
        payload = b'{"hook_event_name": "PreToolUse", '
    elif failure == "payload_oversized":
        payload = b'{"x": "' + b"a" * (entry.MAX_HOOK_INPUT + 10) + b'"}'
    elif failure == "entry_crash":
        env = dict(env, PYTHONPATH="")  # the runtime cannot import the engine: the interpreter fails inside the launcher
        (root / ".recalith" / "runtime").rename(root / ".recalith" / "runtime-moved")
        broken = identity.Layout(root).runtime_python(identity.__version__)
        broken.parent.mkdir(parents=True)
        broken.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        broken.chmod(0o755)
    proc = ccs.run_installed(root, "PreToolUse", payload, env=env)
    if failure == "entry_crash":
        # A broken interpreter exits nonzero but never 2 (the only blocking code), and prints no decision: the host continues the tool.
        assert proc.returncode != 2 and proc.stdout == b""
        return
    ccs.never_blocks(proc)
    assert proc.stderr == b""


@posix
def test_missing_runtime_and_absent_runtime_clone(provisioned, tmp_path):
    root, op = provisioned
    ok(op.integrate())
    shutil.rmtree(root / ".recalith" / "runtime")
    rec = ccs.fixture_records(ccs.VERSION, "lifecycle")[0]
    payload = ccs.Payloads(root, tmp_path).prepare(rec)
    before = cs.tree(root)
    proc = ccs.run_installed(root, rec["event"], payload)
    assert proc.returncode == 0 and proc.stdout == b"" and proc.stderr == b"" and cs.tree(root) == before
    if not ccs.has_git():
        return
    ccs.git(root, "add", "-A")
    ccs.git(root, "commit", "-q", "-m", "fixture")
    clone = tmp_path / "clone"
    assert ccs.git(tmp_path, "clone", "-q", str(root), str(clone)).returncode == 0
    assert not (clone / ccs.SETTINGS).exists(), "the local settings never travel with a clone"
    assert (clone / ".recalith" / "bin" / "recalith-hook").exists() and not (clone / ".recalith" / "runtime").exists()
    command = fast_claude.hook_command("SessionStart")
    import subprocess

    ran = subprocess.run(["sh", "-c", command], input=payload, capture_output=True, env=ccs.host_env(clone), cwd=clone, timeout=60, check=False)
    assert ran.returncode == 0 and ran.stdout == b"" and ran.stderr == b""
    assert not (clone / ".recalith" / "state").exists() and not (clone / ".recalith" / "spool").exists()


@posix
def test_rerun_after_rebind_reintegrates_cleanly(tmp_path):
    root = ccs.project(tmp_path, "before-move")
    cs.provision_runtime(root)
    op = ccs.Operator(root, tmp_path)
    ok(op.integrate())
    moved = tmp_path / "after move"
    root.rename(moved)
    op.root = moved
    ctx_root = moved
    assert ccs.ownership(moved)["state"] == "installed"
    # Moved: refused until the operator rebinds, then the stale manifest keeps the hook off until integrate re-runs.
    ok(op.run("workspace", "rebind"))
    rep = service.health(cs.context(ctx_root), inherited=hs.route_env())
    assert "hook_context_relocated" in rep.capabilities["capture"].reason_codes
    rec = ccs.fixture_records(ccs.VERSION, "lifecycle")[0]
    payload = ccs.Payloads(moved, tmp_path).prepare(rec)
    ccs.run_installed(moved, rec["event"], payload)
    assert spool.ready_segments(spool.SpoolDirs(moved)) == []
    again = ok(op.integrate())
    assert again["settings"] == "updated"  # the absolute launcher spelling of the deny rules follows the new root
    assert all(str(root) not in r for r in ccs.settings(moved)["permissions"]["deny"])
    assert any(str(moved) in r for r in ccs.settings(moved)["permissions"]["deny"])
    rep = service.health(cs.context(ctx_root), inherited=hs.route_env())
    assert "hook_context_relocated" not in rep.capabilities["capture"].reason_codes
    with_worker_off(moved)
    proc = ccs.run_installed(moved, rec["event"], payload)
    ccs.never_blocks(proc)
    assert spool.ready_segments(spool.SpoolDirs(moved)), "the re-integrated hook captures in the moved checkout"


# --------------------------------------------------------------------------
# The session-start notice (SYSTEM_SPEC §14)


@posix
def test_session_start_notice_is_brief_and_not_repeated(provisioned, tmp_path):
    root, op = provisioned
    ok(op.integrate())
    with_worker_off(root)
    payloads = ccs.Payloads(root, tmp_path)
    records = ccs.fixture_records(ccs.VERSION, "lifecycle")
    start = next(r for r in records if r["event"] == "SessionStart" and r["payload"]["source"] == "startup")
    prompt = next(r for r in records if r["event"] == "UserPromptSubmit")
    compact = next(r for r in records if r["event"] == "SessionStart" and r["payload"]["source"] == "compact")
    early = ccs.run_installed(root, "SessionStart", payloads.prepare(compact))
    ccs.never_blocks(early)
    assert early.stdout == b"", "a compaction restart never carries the notice"
    first = ccs.run_installed(root, "SessionStart", payloads.prepare(start))
    ccs.never_blocks(first)
    obj = ccs.response(first)
    assert set(obj) == {"systemMessage"}, obj  # a user notice only: never model context while delivery is uncertified
    text = obj["systemMessage"]
    assert len(text.encode("utf-8")) <= fast_claude.NOTICE_MAX_BYTES and text.startswith("Recalith:")
    assert "inference" in text and "delivery" in text and "recalith status" in text
    for rec in (prompt, compact, start):
        again = ccs.run_installed(root, rec["event"], payloads.prepare(rec))
        ccs.never_blocks(again)
        assert again.stdout == b"", rec["event"]  # never on prompts or compaction; never repeated for the same limits
    session.maintenance_path(str(root))
    Path(session.maintenance_path(str(root))).write_text("{}", encoding="utf-8")  # a new limitation: privacy maintenance (synthetic marker)
    changed = ccs.run_installed(root, "SessionStart", payloads.prepare(start))
    assert "paused" in ccs.response(changed)["systemMessage"]
    Path(session.maintenance_path(str(root))).unlink()


@posix
def test_notice_is_suppressed_when_its_marker_cannot_be_written(provisioned, tmp_path):
    root, op = provisioned
    ok(op.integrate())
    with_worker_off(root)
    notice = root / ".recalith" / "run" / fast_claude.NOTICE_FILE
    notice.mkdir()  # the private marker cannot be written: suppress rather than repeat
    start = next(r for r in ccs.fixture_records(ccs.VERSION, "lifecycle") if r["event"] == "SessionStart")
    proc = ccs.run_installed(root, "SessionStart", ccs.Payloads(root, tmp_path).prepare(start))
    ccs.never_blocks(proc)
    assert proc.stdout == b""


@posix
def test_no_notice_when_nothing_limits_memory(provisioned, tmp_path):
    root, op = provisioned
    inst = cs.context(root).installation_id
    ccs.live_record(root, inst)  # synthetic live record: start and prompt certified
    ok(op.integrate())
    with_worker_off(root)
    hs.certify_provider(_proj(root), tmp_path / "route")  # synthetic certified provider route
    start = next(r for r in ccs.fixture_records(ccs.VERSION, "lifecycle") if r["event"] == "SessionStart")
    proc = ccs.run_installed(root, "SessionStart", ccs.Payloads(root, tmp_path).prepare(start))
    ccs.never_blocks(proc)
    obj = ccs.response(proc)
    assert obj is None or "systemMessage" not in obj, obj


def _proj(root: Path):
    class P:
        pass

    p = P()
    p.root = root
    p.ctx = cs.context(root)
    return p


# --------------------------------------------------------------------------
# Command deny rules and the private-path report (A65, A73)


def test_deny_rules_cover_admin_forms_in_launcher_and_module_spellings(provisioned):
    root, op = provisioned
    result = ok(op.integrate())
    rules = set(ccs.ownership(root)["owned"]["deny"])
    coverage = result["command_deny_rules"]
    spellings = coverage["spellings"]
    assert {".recalith/bin/recalith", "./.recalith/bin/recalith", f"{root.as_posix()}/.recalith/bin/recalith", "python -m recalith", "python3 -m recalith", "python -m recalith.cli.main"} <= set(spellings)  # absolute spellings in the forward-slash form the installer writes on every OS
    for form in integration.ADMIN_FORMS:
        for spelling in spellings:
            assert f"Bash({spelling} {form}:*)" in rules, (spelling, form)
    for read_only in ("status", "search", "show", "context", "claims", "doctor"):
        assert not any(r.startswith(f"Bash(.recalith/bin/recalith {read_only}:") for r in rules), read_only
    assert coverage["complete"] is False  # a prefix pattern never covers every shell wrapper
    assert {"global_options_before_subcommand", "shell_wrapper", "other_interpreter_or_copy", "previews_overcovered"} <= set(coverage["gaps"])
    assert coverage["certified_on_host"] is None  # until the host probe observes them


def test_private_paths_are_probed_never_installed(provisioned):
    root, op = provisioned
    inst = cs.context(root).installation_id
    ccs.live_record(root, inst, private_paths="probed_limited")
    result = ok(op.integrate())
    data = ccs.settings(root)
    assert not any(".recalith" in r for r in data["permissions"]["deny"] if r.startswith(("Read(", "Edit(", "Write(")))
    assert result["private_paths"] == {"state": "probed_limited", "installed_rules": "unavailable_in_preview", "os_level_isolation": False}


# --------------------------------------------------------------------------
# Health: ready only under a complete certified state (labeled synthetic route and host record)


def test_health_is_ready_only_under_a_complete_certified_state(provisioned, tmp_path):
    root, op = provisioned
    p = _proj(root)
    inst = cs.context(root).installation_id
    env = hs.certify_provider(p, tmp_path / "route")  # synthetic certified provider route
    ok(op.integrate())
    rep = hs.report(root, env)
    assert rep.readiness == "degraded" and {"delivery_not_certified", "command_deny_rules_uncertified"} <= {c for n in ("start_delivery", "operator_guard") for c in rep.capabilities[n].reason_codes}
    ccs.live_record(root, inst, mode="request_capture", delivery={"session_start": "unavailable", "prompt": "unavailable"})  # what B1 permits
    ok(op.integrate())
    rep = hs.report(root, env)
    assert rep.readiness == "degraded" and "delivery_request_capture_only" in rep.capabilities["prompt_delivery"].reason_codes
    assert rep.capabilities["operator_guard"].state == "healthy"  # enforcement observed on the real host by the request-capture probe
    ccs.live_record(root, inst)  # synthetic live record
    ok(op.integrate())
    rep = hs.report(root, env)
    assert rep.readiness == "ready" and rep.autonomous_ready, hs.not_healthy(rep, rep.capabilities)
    # Each missing piece withdraws readiness with its reason.
    data = ccs.settings(root)
    saved = json.dumps(data, indent=2) + "\n"
    data["permissions"]["deny"] = [r for r in data["permissions"]["deny"] if "declare" not in r]
    (root / ccs.SETTINGS).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    rep = hs.report(root, env)
    assert not rep.autonomous_ready and "command_deny_rules_modified" in rep.capabilities["operator_guard"].reason_codes
    data = json.loads(saved)
    data["hooks"]["UserPromptSubmit"] = [g for g in data["hooks"]["UserPromptSubmit"] if ccs.LAUNCHER_MARK not in json.dumps(g)]
    (root / ccs.SETTINGS).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    rep = hs.report(root, env)
    assert not rep.autonomous_ready and "host_hooks_modified" in rep.capabilities["prompt_delivery"].reason_codes
    assert rep.capabilities["capture"].state == "degraded" and "host_hooks_modified" in rep.capabilities["capture"].reason_codes  # those events are not captured either
    (root / ccs.SETTINGS).write_text(saved, encoding="utf-8")
    assert hs.report(root, env).autonomous_ready
    op.set_version("2.1.399")  # the host was upgraded and integrate re-ran
    ok(op.integrate())
    rep = hs.report(root, env)
    assert not rep.autonomous_ready and "host_version_changed" in rep.capabilities["operator_guard"].reason_codes
    assert "host_version_uncertified" in rep.capabilities["start_delivery"].reason_codes
    op.set_version(ccs.VERSION)
    ok(op.integrate())
    (root / ".recalith" / "provider.json").unlink()  # B1: no route
    rep = hs.report(root, hs.route_env())
    assert rep.readiness == "degraded" and rep.capabilities["inference"].state == "unavailable" and "provider_not_configured" in rep.capabilities["inference"].reason_codes


def test_status_reports_b1_without_a_host_certification(provisioned):
    root, op = provisioned
    ok(op.integrate())
    status = op.run("status", token=False)
    assert status.code == 8, status.stdout
    degraded = set(status.obj["degraded"])
    assert {"provider_not_configured", "delivery_not_certified"} <= degraded


# --------------------------------------------------------------------------
# The host record writer (decision 0019): only a complete live observation certifies


def _report(mode: str, states: dict[str, str], *, version: str = ccs.VERSION, rules: str = "denied_all_covered", private: str = "probed_limited") -> dict:
    return {"mode": mode, "host_version": version, "paths": {p: {"state": s} for p, s in states.items()}, "command_rules": {"state": rules}, "private_paths": {"state": private}, "report_digest": "0" * 64}


ALL_HEALTHY = {"session_start": "healthy", "prompt": "healthy", "pre_action": "healthy", "compact": "healthy"}


def test_host_record_is_live_only_from_a_complete_live_observation(provisioned):
    root, op = provisioned
    ok(op.integrate())
    ctx = cs.context(root)
    rec = integration.write_host_record(ctx, _report("request_capture", {p: "request_visible" for p in ALL_HEALTHY}))
    assert rec.mode == "request_capture" and set(rec.delivery.values()) == {"unavailable"} and rec.command_rules == "installed"
    rec = integration.write_host_record(ctx, _report("live", dict(ALL_HEALTHY, pre_action="degraded", compact="unavailable")))
    assert rec.mode == "live" and rec.delivery == {"session_start": "certified", "prompt": "certified", "pre_action": "failed", "compact_restore": "unavailable"}
    rec = integration.write_host_record(ctx, _report("live", dict(ALL_HEALTHY, prompt="not_run")))
    assert rec.mode == "request_capture", "a live run with a required path not run is not a complete live observation"
    rec = integration.write_host_record(ctx, _report("live", ALL_HEALTHY, rules="executed_covered_spelling"))
    assert rec.command_rules == "unavailable"
    from recalith.errors import RecalithError

    with pytest.raises(RecalithError):
        integration.write_host_record(ctx, _report("live", ALL_HEALTHY, version="2.1.301"))  # not the integrated host version
    assert json.loads((root / ccs.HOST_FILE).read_text(encoding="utf-8"))["mode"] == "live"
    assert not POSIX or (root / ccs.HOST_FILE).stat().st_mode & 0o077 == 0


# --------------------------------------------------------------------------
# The installer's file effects on every platform (no host command is run)


def test_installer_effects_on_every_platform(tmp_path):
    root = ccs.project(tmp_path, "every-os", git_repo=False)
    ctx = identity.resolve_installation(root, actor=OPERATOR)
    before = (root / ccs.SETTINGS).read_bytes()
    result = integration.integrate(ctx, executable=str(ccs.fake_claude(tmp_path / "bin")))
    assert result["settings"] == "installed" and result["ignored"] in ("verified", "unverified")
    removed = integration.remove(ctx)
    assert removed["modified"] == [] and (root / ccs.SETTINGS).read_bytes() == before
    assert install.OWNERSHIP_SCHEMA == 1


# --------------------------------------------------------------------------
# Kill/restart matrix: the persisted integration steps (failpoints.INTEGRATION), judged from effects only

from recalith.fast import failpoints  # noqa: E402

REPS = int(os.environ.get("RECALITH_CRASH_REPS", "3"))
INSTALL_POINTS = (failpoints.INTEGRATE_AFTER_RECORD, failpoints.INTEGRATE_AFTER_SETTINGS, failpoints.INTEGRATE_AFTER_IGNORE, failpoints.INTEGRATE_AFTER_MANIFEST)
REMOVE_POINTS = (failpoints.REMOVE_AFTER_SETTINGS, failpoints.REMOVE_AFTER_MANIFEST, failpoints.REMOVE_AFTER_IGNORE)
CRASH_CHILD = r"""
import json, sys
spec = json.loads(sys.argv[1])
sys.path[:0] = spec["paths"]
from pathlib import Path
from recalith.contracts.common import Actor
from recalith.core import identity
from recalith.fast import failpoints
from recalith.integrations import claude as integration
if spec["failpoint"]:
    failpoints.arm(spec["failpoint"], failpoints.kill)
ctx = identity.resolve_installation(Path(spec["root"]), actor=Actor(kind="operator", id="terminal", channel="cli"))
if spec["action"] == "integrate":
    integration.integrate(ctx, executable=spec["exe"])
else:
    integration.remove(ctx)
sys.exit(0)
"""


def _child(root: Path, exe: Path, action: str, failpoint: str | None) -> int:
    import subprocess
    import sys

    here = Path(__file__).resolve()
    spec = {"paths": [cf.SRC, str(here.parent), str(here.parents[1]), str(here.parents[1] / "platform")], "root": str(root), "exe": str(exe), "action": action, "failpoint": failpoint}
    return subprocess.run([sys.executable, "-I", "-c", CRASH_CHILD, json.dumps(spec)], capture_output=True, env=cf.child_env(), timeout=120, check=False).returncode


def _variant(rep: int) -> tuple[bytes | None, bytes | None]:
    """Interleavings: settings in the host's format, compact or tab-indented, or absent; a .gitignore present or absent."""
    data = json.loads(json.dumps(ccs.UNRELATED))
    data["permissions"]["deny"] = data["permissions"]["deny"][rep % 2:] + data["permissions"]["deny"][: rep % 2]
    if rep % 3 == 1:
        data["hooks"]["PreToolUse"] = [{"matcher": "Bash", "hooks": [{"type": "command", "command": f"echo user-{rep}"}]}]
    forms = [(json.dumps(data, indent=2) + "\n").encode(), json.dumps(data, separators=(",", ":")).encode(), json.dumps(data, indent="\t").encode(), None]
    ignore = None if rep % 2 else f"node_modules/\n# rep {rep}\n".encode()
    return forms[rep % 4], ignore


def _expect_installed_once(root: Path, original: dict | None) -> None:
    data = ccs.settings(root)
    groups = ccs.owned_groups(data)
    assert {e: len(g) for e, g in groups.items()} == {e: 1 for e, _m in fast_claude.HOOK_EVENTS}
    record = ccs.ownership(root)
    assert record["state"] == "installed" and len(data["permissions"]["deny"]) == len(set(data["permissions"]["deny"]))
    assert ccs.without_owned(data, record["owned"]["deny"]) == (original or {})
    assert (root / ".gitignore").read_text(encoding="utf-8").splitlines().count(integration.IGNORE_LINE) == 1
    m = ccs.manifest(root)
    assert m["context_schema"] == 4 and m["worker"]["autostart"] and m["adapters"]["claude_code"]["host_version"] == ccs.VERSION


def _expect_pristine(root: Path, settings_bytes: bytes | None, ignore_bytes: bytes | None) -> None:
    assert ccs.digest(root / ccs.SETTINGS) == (None if settings_bytes is None else hashlib.sha256(settings_bytes).hexdigest())
    assert ccs.digest(root / ".gitignore") == (None if ignore_bytes is None else hashlib.sha256(ignore_bytes).hexdigest())
    assert ccs.ownership(root) is None and ccs.manifest(root) is None
    assert not (root / ".recalith" / "run" / "integrations").exists() or not list((root / ".recalith" / "run" / "integrations").iterdir())


import hashlib  # noqa: E402


@pytest.mark.parametrize("failpoint", INSTALL_POINTS + REMOVE_POINTS)
def test_integration_crash_matrix(tmp_path, failpoint):
    """Kill the installer/remover at each persisted step, restart, and compare effects with the uninterrupted outcome."""
    exe = ccs.fake_claude(tmp_path / "bin")
    for rep in range(REPS):
        raw, ignore = _variant(rep)
        root = ccs.project(tmp_path / f"r{rep}", "crash", unrelated=None, raw=raw, git_repo=False)
        if ignore is not None:
            (root / ".gitignore").write_bytes(ignore)
        original = None if raw is None else json.loads(raw)
        if failpoint in INSTALL_POINTS:
            assert _child(root, exe, "integrate", failpoint) == failpoints.KILL_STATUS
            if rep % 2 == 0:
                assert _child(root, exe, "integrate", None) == 0  # restart: the same command again
                _expect_installed_once(root, original)
            assert _child(root, exe, "remove", None) == 0  # removal after a crash leaves the pre-install bytes
        else:
            assert _child(root, exe, "integrate", None) == 0
            assert _child(root, exe, "remove", failpoint) == failpoints.KILL_STATUS
            if rep % 2 == 0:
                assert _child(root, exe, "integrate", None) == 0  # re-install over a half-removed integration
                _expect_installed_once(root, original)
            assert _child(root, exe, "remove", None) == 0
        _expect_pristine(root, raw, ignore)


# --------------------------------------------------------------------------
# The 2.1.305 fixture review (decision 0019): the same mapping as 2.1.301


def _mapped(tmp: Path, version: str, scenario: str) -> list[tuple]:
    from recalith.fast.normalize import normalize_raw

    root = ccs.project(tmp / version, f"map-{scenario}", git_repo=False, unrelated=None)
    from recalith.capture.hooks import write_hook_context

    write_hook_context(cs.context(root), adapter_id="claude_code", host_version=version)
    ctx = entry.load_context(str(root), "claude_code")
    payloads = ccs.Payloads(root, tmp / version)
    out = []
    for rec in ccs.fixture_records(version, scenario):
        request = claude_capture.map_hook(ctx, json.loads(payloads.prepare(rec)), registered_event=rec["event"])
        assert not request["coverage_gaps"] or rec["event"] == "PermissionRequest", (version, rec["event"], request["coverage_gaps"])
        for raw in request["raw_events"]:
            assert "unsupported_host_field" not in (raw.adapter_coverage or {}).get("warnings", {}), (version, rec["event"])
            assert "uncertified_host_version" not in (raw.adapter_coverage or {}).get("warnings", {}), version
            (env,), _notes = normalize_raw({"project_id": ctx["project_id"], "installation_id": ctx["installation_id"], "workspace_id": ctx["workspace_id"]}, raw)
            body = env["payload"]
            out.append((rec["event"], env["kind"], sorted(body), body.get("outcome"), body.get("exit_code"), (body.get("action") or {}).get("parse_status"), bool(env["coverage"].get("truncated"))))
    return out


@pytest.mark.parametrize("scenario", ["lifecycle", "subagent", "denied", "secret_and_resume"])
def test_reviewed_2_1_305_fixtures_map_like_2_1_301(tmp_path, scenario):
    assert "2.1.305" in claude_capture.CERTIFIED_VERSIONS and "2.1.301" in claude_capture.CERTIFIED_VERSIONS
    assert _mapped(tmp_path, "2.1.305", scenario) == _mapped(tmp_path, "2.1.301", scenario)


def test_reviewed_2_1_305_transcripts_parse_without_gaps():
    parse = claude_capture.transcript_line_parser("inst_11111111-1111-4111-8111-111111111111", host_version="2.1.305")
    base = cf.ROOT / "tests" / "fixtures" / "hosts" / "claude" / "2.1.305"
    texts = 0
    for path in base.glob("*.transcript.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            texts += len(parse(json.loads(line), line))
    assert texts >= 3


@pytest.mark.parametrize("scenario", ["lifecycle", "subagent", "denied", "secret_and_resume"])
def test_reviewed_2_1_306_fixtures_map_like_2_1_305(tmp_path, scenario):
    """The 2.1.306 review (decision 0020): the same mapping as 2.1.305.

    The background subagent's events interleave differently between captures
    (timing, not format), so that scenario compares the mapped records as a
    multiset; the others compare in order.
    """
    assert "2.1.306" in claude_capture.CERTIFIED_VERSIONS
    new, old = _mapped(tmp_path, "2.1.306", scenario), _mapped(tmp_path, "2.1.305", scenario)
    assert (sorted(new) == sorted(old)) if scenario == "subagent" else (new == old)


def test_reviewed_2_1_306_transcripts_parse_without_gaps():
    parse = claude_capture.transcript_line_parser("inst_11111111-1111-4111-8111-111111111111", host_version="2.1.306")
    base = cf.ROOT / "tests" / "fixtures" / "hosts" / "claude" / "2.1.306"
    texts = 0
    for path in base.glob("*.transcript.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            texts += len(parse(json.loads(line), line))
    assert texts >= 3


# --------------------------------------------------------------------------
# Capture, delivery and compaction restoration through the installed hooks (deterministic; the real host is the smoke test)


@posix
def test_claude_capture_delivery_and_compact(tmp_path):
    """Real 2.1.301 lifecycle payloads through the installed commands, every path enabled by a (synthetic) live record (A27/A58).

    The installation holds a failure lesson admitted through recorded proposals (``delivery_scenarios``); ``integrate``
    enables exactly the certified paths; the session start, prompts, the failing call's pre-action caution, the
    compaction cycle and the restoration run through ``sh -c`` and the project launcher. Receipts are ingested.
    """
    import delivery_scenarios as ds

    p, ids = ds.project(tmp_path, paths=())
    cs.provision_runtime(p.root)
    op = ccs.Operator(p.root, tmp_path, version="2.1.301")
    ccs.live_record(p.root, p.ctx.installation_id, version="2.1.301", delivery={"pre_action": "certified", "compact_restore": "certified"})
    assert ok(op.integrate())["delivery_paths"] == list(ccs.DELIVERY_PATHS)
    with_worker_off(p.root)
    host = ds.fresh_session(80)
    pre, post = ds.call_records(ds.MID, "life", session=host)
    records = [ds.in_session(ds.record("SessionStart"), host), ds.wks.variant(ds.record("UserPromptSubmit"), session=host, prompt="Fix test_mid's fixture."), pre, post,
               ds.in_session(ds.record("PreCompact"), host), ds.in_session(ds.record("SessionStart", n=1), host), ds.in_session(ds.record("PostCompact"), host),
               ds.wks.variant(ds.record("UserPromptSubmit"), session=host, prompt="Continue with test_mid."), ds.in_session(ds.record("SessionEnd"), host)]
    outputs = {}
    for rec in records:
        proc = ccs.run_installed(p.root, rec["event"], p.replay.prepare(rec))
        ccs.never_blocks(proc)
        obj = ccs.response(proc)
        outputs.setdefault(rec["event"], []).append(obj)
    pre_context = (outputs["PreToolUse"][0] or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
    assert ids["lesson"] in pre_context and "[caution]" in pre_context
    restored = [o for o in outputs["SessionStart"][1:] if o and "hookSpecificOutput" in o]
    assert len(restored) == 1 and ids["lesson"] in restored[0]["hookSpecificOutput"]["additionalContext"]
    ds.ingest(p)
    rows = ds.deliveries(p, ds.session_of(p, host))
    purposes = [r["purpose"] for r in rows if r["state"] == "emitted"]
    assert purposes.count("compact_restore") == 1 and "pre_action" in purposes
    assert all(r["estimated_tokens"] <= {"session_start": 2000, "prompt": 1000, "pre_action": 400, "compact_restore": 2000}[r["purpose"]] for r in rows)
    with ds.wks.Project.view(p) as v:
        kinds = {k for (k,) in v.execute("SELECT DISTINCT kind FROM events").fetchall()}
    assert {"session_started", "user_message", "tool_started", "tool_finished", "compaction", "session_ended", "memory_delivered"} <= kinds
