"""Task 13 smoke test on the real installed Claude Code host (request-capture mode; decision 0019).

The installed CLI runs real sessions in disposable, owned fixture
installations under the test's temporary directory, with a private ``HOME``,
``--setting-sources local`` and a loopback scripted endpoint with a
placeholder key (never this session's credentials or proxy). Every hook is
the real Recalith entry behind the launcher that ``recalith integrate claude``
installed; the store, compiler, fences, budgets, receipts and worker are the
real engine. The harness is the Task 0b harness in engine mode
(``tools/probe_engine.py``).

What this can certify: host *enforcement* and host *behavior* (which hooks
fire, what reaches the outbound model request, which commands the host
denies, which processes survive). What it cannot: model-visible delivery,
which needs a live model echoing the nonce (B1). Every result here is
labeled ``request_capture`` and never writes a ``live`` host record.

**Synthetic states** (labeled in the harness): the nonce memories are claims
admitted through the real extraction/review path with recorded proposals; a
trial enables its path in a controlled hook manifest (``integrate`` enables
only live-certified paths); the scripted endpoint chooses the tool calls.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

import claude_fixtures as cf

sys.path.insert(0, str(cf.ROOT / "tools"))
import probe_engine as pe  # noqa: E402

from recalith.fast import claude_capture  # noqa: E402

PATHS = ("session_start", "prompt", "pre_action", "compact")


def _installed() -> tuple[str | None, str | None]:
    exe = shutil.which("claude")
    if not exe or os.name == "nt":
        return None, None
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False).stdout
    version = out.split()[0] if out.split() else None
    return (exe, version) if version in claude_capture.CERTIFIED_VERSIONS else (None, version)


EXE, VERSION = _installed()
pytestmark = pytest.mark.skipif(EXE is None, reason=f"no installed Claude Code CLI at a capture-certified version {sorted(claude_capture.CERTIFIED_VERSIONS)} (found {VERSION}); replayed real fixtures cover this platform")


@pytest.fixture(scope="module")
def certification(tmp_path_factory):
    """One complete request-capture certification run against an integrated target project."""
    base = tmp_path_factory.mktemp("claude-smoke")
    target = pe.fixture_target(base / "target project é", EXE)
    report = pe.certify(EXE, base=base / "harness", modes=("request_capture",), target_root=target, cfg=None)
    yield report, target
    pe.stop_workers(base)


def test_claude_capture_delivery_and_compact(certification):
    report, _target = certification
    life = report["request_capture"]["lifecycle"]
    assert life["host_version"] == VERSION and life["returncode"] == 0
    assert {"session_started", "user_message", "tool_started", "tool_finished", "compaction", "session_stopped", "session_ended"} <= set(life["event_kinds"])
    assert life["subagent_sessions"] >= 1 and life["subagent_transcripts_registered"] >= 1
    assert life["transcript_sources"] >= 1 and life["assistant_messages_recovered"] >= 1  # the registered transcript supplement
    assert life["worker"]["spawned_by"] == "hook" and life["worker"]["ingested_all"] is True
    deliveries = life["deliveries"]
    assert deliveries["session_start"] >= 1 and deliveries["prompt"] >= 1 and deliveries["pre_action"] >= 1
    assert deliveries["compact_restore"] == 1, "one restoration per compaction"
    assert life["unrelated_settings_preserved"] == "byte_identical"


def test_engine_delivery_reaches_the_request_on_every_path(certification):
    report, _target = certification
    paths = report["request_capture"]["paths"]
    for path in PATHS:
        state = paths[path]
        assert state["positives_hook_emitted"] == 3 and state["negatives_clean"] == 3, (path, state)
        assert state["state"] == "request_visible", (path, state)
        assert state["engine"]["receipts_ingested"] == 3 and state["engine"]["within_packet_cap"] is True, (path, state)
    for trial in report["request_capture"]["trials"]:
        assert "eligible_response_excerpt" not in trial, "request-capture never retains or claims a model echo"
        assert trial["nonce_sha256"] and "nonce" not in trial


def test_command_deny_rules_and_markers_on_actual_tool_subprocesses(certification):
    report, _target = certification
    rules = report["request_capture"]["command_rules"]
    assert rules["state"] == "denied_all_covered", rules
    covered = [c for c in rules["commands"] if c["covered"]]
    assert covered and all(c["outcome"] == "host_denied" for c in covered), covered
    gaps = [c for c in rules["commands"] if not c["covered"]]
    assert gaps and all(c["outcome"] in ("guard_refused", "host_denied") for c in gaps), gaps  # never an admin effect
    assert any(c["outcome"] == "guard_refused" and c["audit"] == "captured" for c in gaps), "A73: the guard refuses on an actual tool subprocess"
    assert set(rules["tool_subprocess_markers"]) == {"CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION"}  # observed on 2.1.305: both reach the agent's tools
    assert rules["admin_effects"] == "none" and rules["store_unchanged"] is True


def test_private_path_probe_in_the_configured_permission_mode(certification):
    report, target = certification
    private = report["request_capture"]["private_paths"]
    assert private["permission_mode"] == "default" and private["state"] in ("probed_supported", "probed_limited", "probed_unsupported")
    assert private["hooks_operated_under_rules"] is True
    assert private["installed_in_target"] is False and private["os_level_isolation"] is False
    attempts = private["with_probe_rules"]
    assert {"Read", "Bash cat"} <= {a["spelling"] for a in attempts}
    settings = json.loads((target / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert not any(".recalith" in r for r in settings["permissions"]["deny"] if r.startswith(("Read(", "Edit(", "Write(")))


def test_hook_spawned_worker_survives_session_end_and_host_termination(certification):
    report, _target = certification
    survival = report["request_capture"]["worker_survival"]
    for case in ("session_end", "host_killed", "terminal_hangup"):
        result = survival[case]
        assert result["spawned_by"] == "hook" and result["method"] == "posix_session" and result["independence"] == "detached", (case, result)
        assert result["alive_after"] is True and result["ingested_after"] is True, (case, result)
    recovery = survival["worker_killed_then_next_session"]
    assert recovery == {"worker_killed": True, "restarted_by": "hook", "backlog_ingested": True}, recovery


def test_hook_failure_never_denies_tool_on_the_real_host(certification):
    report, _target = certification
    failures = report["request_capture"]["hook_failures"]
    assert failures and all(f["tool_ran"] and f["hook_exit_codes"] and all(c != 2 for c in f["hook_exit_codes"]) for f in failures.values()), failures


def test_session_start_notice_reaches_the_user_not_the_model(certification):
    report, _target = certification
    notice = report["request_capture"]["notice"]
    assert notice["in_host_stream"] is True and notice["in_model_request"] is False and notice["repeated"] is False


def test_certification_writes_only_a_request_capture_record(certification):
    report, target = certification
    record = json.loads((target / ".recalith" / "host.json").read_text(encoding="utf-8"))
    assert record["mode"] == "request_capture" and set(record["delivery"].values()) == {"unavailable"}
    assert record["host_version"] == VERSION and record["command_rules"] == "installed"
    assert report["host_record"]["mode"] == "request_capture" and report["live"]["status"] == "not_run"
    from recalith import service
    from recalith.contracts.common import Actor
    from recalith.core import identity

    rep = service.health(identity.resolve_installation(target, actor=Actor(kind="host_agent", id="t", channel="cli")), inherited={"PATH": os.environ.get("PATH", "")})
    assert rep.readiness == "degraded" and not rep.autonomous_ready
    assert "delivery_request_capture_only" in rep.capabilities["start_delivery"].reason_codes
    assert rep.capabilities["inference"].state == "unavailable"
