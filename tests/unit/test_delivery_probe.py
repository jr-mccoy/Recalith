"""Task 0b delivery-probe tests (A61 harness mechanics).

The pure evaluation tests pin the nonce protocol. End-to-end tests drive a fake
host; a fake host never certifies a real delivery path.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import probe_common as pc  # noqa: E402
import probe_delivery as pd  # noqa: E402

FAKE_HOST = REPO / "tests" / "fixtures" / "hosts" / "claude" / "delivery" / "fake_host.py"
posix_only = pytest.mark.skipif(os.name == "nt", reason="fake host wrapper uses a POSIX shebang")


# ---------------------------------------------------------------- helpers


def spec(path: str, kind: str = "positive") -> dict:
    return {"trial_id": f"t-{path}-{kind}", "path": path, "kind": kind, "nonce": secrets.token_hex(16)}


def obs_for(sp: dict, *, reply: str | None = None, emitted: bool | None = None, fired: bool = True, extra_timeline=(), **kw) -> dict:
    nonce = sp["nonce"]
    if reply is None:
        reply = f"CANARY {nonce}" if sp["kind"] == "positive" else "CANARY NONE"
    if emitted is None:
        emitted = sp["kind"] == "positive"
    timeline = [{"kind": "init", "version": "x", "model": "m"}]
    if sp["path"] == "pre_action":
        timeline += [{"kind": "tool_use", "name": "Bash", "input": {"command": pd.FIXED_TOOL_COMMAND}}, {"kind": "tool_result", "text": pd.FIXED_TOOL_OUTPUT}]
    if sp["path"] == "compact":
        timeline += [{"kind": "text", "text": "OK"}, {"kind": "compact_boundary"}]
    timeline += list(extra_timeline) + [{"kind": "text", "text": reply}, {"kind": "result", "subtype": "success", "is_error": False}]
    records = [{"path": sp["path"], "event": "x", "emitted": emitted}] if fired else []
    base = {"launched": True, "timed_out": False, "launch_error": False, "timeline": timeline, "hook_records": records, "prompts": ["prompt"], "workspace_files_with_nonce": [], "other_trial_nonces": [], "transcript_contains_nonce": sp["kind"] == "positive"}
    base.update(kw)
    return base


def path_trials(path: str, make) -> list[dict]:
    out = []
    for kind in ("positive", "negative"):
        for _ in range(pd.CONTROLS_PER_KIND):
            sp = spec(path, kind)
            out.append({"kind": kind, "verdict": pd.evaluate_trial(sp, make(sp))})
    return out


def healthy(path: str) -> dict:
    return pd.evaluate_path(path, path_trials(path, lambda sp: obs_for(sp)))


# ---------------------------------------------------------------- required tests


def test_probe_rejects_stdout_only_success():
    """The hook ran and printed the nonce, but the model never echoed it."""
    sp = spec("prompt")
    verdict = pd.evaluate_trial(sp, obs_for(sp, reply="CANARY NONE", emitted=True))
    assert verdict == {"valid": True, "passed": False, "reasons": ["stdout_only_no_model_echo"]}
    trials = path_trials("prompt", lambda s: obs_for(s, reply="CANARY NONE"))
    state = pd.evaluate_path("prompt", trials)
    assert state["state"] == "degraded" and state["positives_passed"] == 0
    assert pd.exit_code_for({"session_start": healthy("session_start"), "prompt": state}) == pc.EXIT_DEGRADED


@pytest.mark.parametrize(
    "contamination,reason",
    [
        ({"prompts": ["leak {nonce}"]}, "nonce_in_prompt"),
        ({"workspace_files_with_nonce": ["notes.txt"]}, "nonce_in_workspace_file"),
        ({"extra_timeline": [{"kind": "tool_use", "name": "Read", "input": {"file_path": "x"}}]}, "unexpected_tool_use"),
    ],
)
def test_probe_rejects_nonce_contamination(contamination, reason):
    sp = spec("session_start")
    kw = {k: ([v[0].format(nonce=sp["nonce"])] if k == "prompts" else v) for k, v in contamination.items()}
    verdict = pd.evaluate_trial(sp, obs_for(sp, **kw))
    assert verdict["valid"] is False and verdict["passed"] is False and reason in verdict["reasons"]
    state = pd.evaluate_path("session_start", [{"kind": "positive", "verdict": verdict}] + path_trials("session_start", lambda s: obs_for(s))[1:])
    assert state["state"] == "degraded"


def test_probe_rejects_nonce_in_fixture_tool_output():
    sp = spec("pre_action")
    o = obs_for(sp)
    o["timeline"][2] = {"kind": "tool_result", "text": f"recalith-fixed-output {sp['nonce']}"}
    assert "nonce_in_tool_output" in pd.evaluate_trial(sp, o)["reasons"]


def test_missing_prompt_blocks_required_delivery():
    prompt = pd.evaluate_path("prompt", path_trials("prompt", lambda s: obs_for(s, fired=False)))
    assert prompt["state"] == "unavailable" and prompt["required"] is True
    paths = {"session_start": healthy("session_start"), "prompt": prompt, "pre_action": healthy("pre_action"), "compact": healthy("compact")}
    assert pd.exit_code_for(paths) == pc.EXIT_UNAVAILABLE


def test_missing_pre_action_is_optional():
    pre = pd.evaluate_path("pre_action", path_trials("pre_action", lambda s: obs_for(s, fired=False)))
    compact = pd.evaluate_path("compact", path_trials("compact", lambda s: obs_for(s, emitted=s["kind"] == "positive", reply="CANARY NONE")))
    assert pre["state"] == "unavailable" and pre["required"] is False
    assert compact["state"] == "degraded" and compact["required"] is False
    paths = {"session_start": healthy("session_start"), "prompt": healthy("prompt"), "pre_action": pre, "compact": compact}
    assert pd.exit_code_for(paths) == pc.EXIT_CERTIFIED


# ---------------------------------------------------------------- protocol details


def test_all_controls_pass_is_healthy_and_needs_three_of_each():
    assert healthy("prompt")["state"] == "healthy"
    two = path_trials("prompt", lambda s: obs_for(s))[1:]
    assert pd.evaluate_path("prompt", two)["state"] == "degraded"
    assert pd.evaluate_path("prompt", [])["state"] == "not_run"


def test_negative_control_must_not_contain_withheld_nonce():
    sp = spec("prompt", "negative")
    verdict = pd.evaluate_trial(sp, obs_for(sp, reply=f"CANARY {sp['nonce']}"))
    assert verdict["passed"] is False and "fabricated_withheld_nonce" in verdict["reasons"]


def test_negative_control_that_injects_is_invalid():
    sp = spec("prompt", "negative")
    assert "negative_control_injected" in pd.evaluate_trial(sp, obs_for(sp, emitted=True))["reasons"]


def test_eligible_text_respects_injection_point():
    sp = spec("pre_action")
    # The nonce appears only before the tool call: that is not post-injection delivery.
    o = obs_for(sp, reply="CANARY NONE", extra_timeline=())
    o["timeline"].insert(1, {"kind": "text", "text": f"early {sp['nonce']}"})
    assert pd.evaluate_trial(sp, o)["reasons"] == ["stdout_only_no_model_echo"]
    sp = spec("compact")
    o = obs_for(sp, reply="CANARY NONE")
    o["timeline"].insert(1, {"kind": "text", "text": f"pre-compaction {sp['nonce']}"})
    assert pd.evaluate_trial(sp, o)["reasons"] == ["stdout_only_no_model_echo"]


def test_compaction_not_triggered_is_not_a_pass():
    sp = spec("compact")
    o = obs_for(sp)
    o["timeline"] = [e for e in o["timeline"] if e["kind"] != "compact_boundary"]
    assert pd.evaluate_trial(sp, o)["reasons"] == ["compaction_not_triggered"]


def test_parse_session_stream_orders_events():
    lines = [
        {"type": "system", "subtype": "init", "claude_code_version": "1"},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "out"}]}},
        {"type": "system", "subtype": "compact_boundary"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
        {"type": "result", "subtype": "success", "is_error": False},
    ]
    parsed = pd.parse_session_stream(("\n".join(json.dumps(x) for x in lines) + "\nnot json\n").encode())
    assert [e["kind"] for e in parsed["timeline"]] == ["init", "tool_use", "tool_result", "compact_boundary", "text", "result"]
    assert parsed["errors"] == ["stream_line_not_json"]


# ---------------------------------------------------------------- owned configuration


def test_owned_hooks_preserve_unrelated_settings(tmp_path):
    settings = tmp_path / ".claude" / "settings.local.json"
    unrelated = {"permissions": {"deny": ["Read(./x)"]}, "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "keep-me"}]}]}}
    settings.parent.mkdir()
    settings.write_text(json.dumps(unrelated), encoding="utf-8")
    manifest = pd.install_owned_hooks(settings, [("UserPromptSubmit", None, "probe-a"), ("SessionStart", "startup", "probe-b")], timeout_s=5)
    installed = json.loads(settings.read_text(encoding="utf-8"))
    assert installed["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] == "keep-me"
    assert len(installed["hooks"]["UserPromptSubmit"]) == 2 and "SessionStart" in installed["hooks"]
    result = pd.remove_owned_hooks(manifest)
    assert result == {"removed": 2, "missing": 0, "modified": 0, "unrelated_preserved": True}
    assert json.loads(settings.read_text(encoding="utf-8")) == unrelated


def test_modified_owned_entry_is_left_and_reported(tmp_path):
    settings = tmp_path / "settings.local.json"
    manifest = pd.install_owned_hooks(settings, [("UserPromptSubmit", None, "probe-a")], timeout_s=5)
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["timeout"] = 99  # operator edited our entry
    settings.write_text(json.dumps(data), encoding="utf-8")
    result = pd.remove_owned_hooks(manifest)
    assert result["modified"] == 1 and result["removed"] == 0 and result["unrelated_preserved"] is False
    assert "probe-a" in settings.read_text(encoding="utf-8")


def test_new_settings_file_is_removed_when_only_owned(tmp_path):
    settings = tmp_path / "settings.local.json"
    manifest = pd.install_owned_hooks(settings, [("UserPromptSubmit", None, "probe-a")], timeout_s=5)
    assert pd.remove_owned_hooks(manifest)["unrelated_preserved"] is True
    assert not settings.exists()


@posix_only
def test_owned_hooks_removed_when_a_trial_crashes(tmp_path, fake_host, monkeypatch):
    cfg = pd.load_config(write_config(tmp_path, fake_host, modes=["request_capture"]))
    ws = pd.Workspace(tmp_path / "ws")
    ws.create()
    before = ws.settings.read_text(encoding="utf-8")

    def boom(*a, **k):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(pd.Driver, "run_trial", boom)
    with pytest.raises(RuntimeError):
        pd.run_mode(cfg, ws, str(fake_host), "request_capture")
    assert json.loads(ws.settings.read_text(encoding="utf-8")) == json.loads(before)


def test_stub_emits_only_for_planned_path(tmp_path, capsys, monkeypatch):
    import io

    sys.path.insert(0, str(REPO / "tools" / "fixtures"))
    import delivery_stub

    plan = tmp_path / "plan.json"
    log = tmp_path / "log.jsonl"
    nonce = secrets.token_hex(16)
    plan.write_text(json.dumps({"trial_id": "t1", "inject_path": "prompt", "nonce": nonce}), encoding="utf-8")
    for path in ("session_start", "prompt"):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "UserPromptSubmit"})))
        assert delivery_stub.main(["--plan", str(plan), "--log", str(log), "--path", path]) == 0
    out = capsys.readouterr().out
    assert out.count(nonce) == 1 and json.loads(out)["hookSpecificOutput"]["additionalContext"].endswith(nonce)
    assert nonce not in log.read_text(encoding="utf-8")  # the nonce never goes to another channel
    assert [json.loads(x)["emitted"] for x in log.read_text(encoding="utf-8").splitlines()] == [False, True]


# ---------------------------------------------------------------- end to end against the fake host


@pytest.fixture()
def fake_host(tmp_path: Path) -> Path:
    exe = tmp_path / "fake-host"
    exe.write_text(f"#!/bin/sh\nexec {sys.executable} -I {FAKE_HOST} \"$@\"\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return exe


def write_config(tmp_path: Path, exe: Path, scenario: str = "echo", **overrides) -> Path:
    delivery = {
        "host_id": "fake_host",
        "executable": str(exe),
        "model": "fake-model",
        "modes": ["live"],
        "nonsecret_env": {"FAKE_HOST_SCENARIO": scenario},
        "auth_route": {"kind": "env_api_key", "billing": "api", "env_keys": ["FAKE_DELIVERY_ROUTE_KEY"]},
        "limits": {"trial_timeout_seconds": 30, "capture_trial_timeout_seconds": 30},
    }
    delivery.update(overrides)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"config_schema": 1, "delivery": delivery}), encoding="utf-8")
    return path


@pytest.fixture()
def route_key(monkeypatch):
    monkeypatch.setenv("FAKE_DELIVERY_ROUTE_KEY", "fake-delivery-value-0001")


def delivery_section(out: Path) -> dict:
    return json.loads(out.read_text(encoding="utf-8"))["sections"]["delivery"]["fake_host"]


@posix_only
def test_end_to_end_all_paths_healthy_preserves_provider_section(tmp_path, fake_host, route_key):
    out = tmp_path / "report.json"
    pc.merge_report_section(out, "provider_isolation", "claude_cli", {"verdict": "kept"})
    code = pd.probe_delivery(write_config(tmp_path, fake_host), out)
    rep = delivery_section(out)
    assert code == pc.EXIT_CERTIFIED, rep["paths"]
    assert {p: v["state"] for p, v in rep["paths"].items()} == dict.fromkeys(pd.PATHS, "healthy")
    assert json.loads(out.read_text(encoding="utf-8"))["sections"]["provider_isolation"]["claude_cli"] == {"verdict": "kept"}
    assert rep["live"]["owned_hook_cleanup"]["unrelated_preserved"] is True
    assert "fake-delivery-value-0001" not in out.read_text(encoding="utf-8")
    trial = rep["live"]["trials"][0]
    assert trial["transcript_contains_nonce"] is True and trial["eligible_response_contains_nonce"] is True


@posix_only
@pytest.mark.parametrize(
    "scenario,code,states",
    [
        ("ignore_context", pc.EXIT_DEGRADED, {"session_start": "degraded", "prompt": "degraded"}),
        ("no_prompt_hook", pc.EXIT_UNAVAILABLE, {"session_start": "healthy", "prompt": "unavailable"}),
        ("no_pre_action", pc.EXIT_CERTIFIED, {"pre_action": "unavailable", "prompt": "healthy"}),
        ("leak_tool_output", pc.EXIT_CERTIFIED, {"pre_action": "degraded"}),
    ],
)
def test_end_to_end_failure_modes(tmp_path, fake_host, route_key, scenario, code, states):
    out = tmp_path / "report.json"
    assert pd.probe_delivery(write_config(tmp_path, fake_host, scenario), out) == code
    got = {p: v["state"] for p, v in delivery_section(out)["paths"].items()}
    assert {p: got[p] for p in states} == states


@posix_only
def test_live_without_route_is_unavailable(tmp_path, fake_host):
    out = tmp_path / "report.json"
    cfg = write_config(tmp_path, fake_host, auth_route={"kind": "not_configured", "env_keys": []})
    assert pd.probe_delivery(cfg, out) == pc.EXIT_UNAVAILABLE
    rep = delivery_section(out)
    assert rep["live"] == {"status": "not_run", "reason": "no_auth_route_configured"}
    assert all(v["state"] == "not_run" for v in rep["paths"].values())


@posix_only
def test_request_capture_reports_feasibility_without_passing(tmp_path, fake_host):
    out = tmp_path / "report.json"
    cfg = write_config(tmp_path, fake_host, modes=["request_capture"], auth_route={"kind": "not_configured", "env_keys": []})
    assert pd.probe_delivery(cfg, out) == pc.EXIT_UNAVAILABLE
    rep = delivery_section(out)
    assert {p: v["state"] for p, v in rep["request_capture"]["paths"].items()} == dict.fromkeys(pd.PATHS, "request_visible")
    assert all(v["state"] == "not_run" for v in rep["paths"].values())


def test_config_rejects_unknown_and_secret_fields(tmp_path):
    exe = tmp_path / "x"
    with pytest.raises(pd.ConfigError, match="unknown"):
        pd.load_config(write_config(tmp_path, exe, surprise=True))
    with pytest.raises(pd.ConfigError, match="credentials"):
        pd.load_config(write_config(tmp_path, exe, nonsecret_env={"MY_TOKEN": "x"}))
    with pytest.raises(pd.ConfigError, match="model"):
        pd.load_config(write_config(tmp_path, exe, model=None))


def test_example_config_delivery_section_is_valid():
    cfg = pd.load_config(REPO / "tools" / "probe_config.example.json")
    assert cfg["host_id"] == "claude_code" and cfg["auth_route"]["env_keys"] == ["ANTHROPIC_API_KEY"]
