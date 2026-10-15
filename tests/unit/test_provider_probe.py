"""Task 0 harness tests (A28/A30/A67 mechanics) using a fake CLI.

These verify the probe's own decisions. They never certify a real host: a
report produced against ``fake_cli.py`` is test data only.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import probe_common as pc  # noqa: E402
import probe_provider as pp  # noqa: E402

FAKE = REPO / "tests" / "fixtures" / "providers" / "fake_cli.py"
ISOLATED = ["-p", "--bare", "--tools", "", "--strict-mcp-config", "--model", "{model}", "--system-prompt", "{system_prompt}", "--output-format", "stream-json", "--verbose"]

pytestmark = pytest.mark.skipif(os.name == "nt", reason="fake CLI wrapper uses a POSIX shebang; native Windows runs the real-host probe")


@pytest.fixture()
def fake_exe(tmp_path: Path) -> Path:
    exe = tmp_path / "fake-claude"
    exe.write_text(f"#!/bin/sh\nexec {sys.executable} -I {FAKE} \"$@\"\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return exe


def write_config(tmp_path: Path, exe: Path, **overrides) -> Path:
    cfg = {
        "provider_id": "fake_cli",
        "executable": str(exe),
        "model": "fake-model",
        "invocation_args": ISOLATED,
        "modes": ["request_capture"],
        "nonsecret_env": {},
        "limits": {"bounds_timeout_seconds": 2, "timeout_seconds": 30},
        "auth_route": {"kind": "not_configured", "billing": "none", "env_keys": []},
        "operator_attestation": {"background_use": "unchecked"},
    }
    cfg.update(overrides)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"config_schema": 1, "provider": cfg}), encoding="utf-8")
    return path


def section(report_path: Path, provider: str = "fake_cli") -> dict:
    return json.loads(report_path.read_text(encoding="utf-8"))["sections"]["provider_isolation"][provider]


# ---------------------------------------------------------------- environment


def test_child_environment_removes_markers_and_sets_curator_marker():
    parent = {"PATH": "/bin", "CLAUDECODE": "1", "CLAUDE_CODE_CHILD_SESSION": "1", pc.WORKER_MARKER: "old", pc.CURATOR_MARKER: "other", "GITHUB_TOKEN": "x", "HOME": "/real"}
    child = pc.build_child_environment(parent, purpose="curator", installation_id="inst_a", platform_keys=["PATH", "CLAUDECODE"], overrides={"HOME": "/fixture"})
    assert child == {"PATH": "/bin", "HOME": "/fixture", pc.CURATOR_MARKER: "inst_a"}
    assert parent["CLAUDECODE"] == "1" and parent[pc.WORKER_MARKER] == "old"  # caller unchanged


def test_marker_removal_wins_over_allowlist_and_overrides():
    child = pc.build_child_environment({"CLAUDECODE": "1"}, purpose="worker", installation_id="inst_a", platform_keys=["CLAUDECODE"], overrides={"CLAUDE_CODE_CHILD_SESSION": "1", pc.CURATOR_MARKER: "x"})
    assert child == {pc.WORKER_MARKER: "inst_a"}


def test_child_environment_rejects_unknown_purpose():
    with pytest.raises(pc.EnvironmentPolicyError):
        pc.build_child_environment({}, purpose="operator", installation_id="inst_a", platform_keys=[])


# ---------------------------------------------------------------- config


@pytest.mark.parametrize(
    "patch,needle",
    [
        ({"surprise": 1}, "unknown config fields"),
        ({"invocation_args": ["-p"]}, "{model}"),
        ({"nonsecret_env": {"ANTHROPIC_API_KEY": "sk-abc12345678"}}, "credentials"),
        ({"nonsecret_env": {"CLAUDECODE": "1"}}, "marker"),
        ({"auth_route": {"kind": "env_api_key", "env_keys": []}}, "env_keys"),
        ({"operator_attestation": {"background_use": "checked_eligible"}}, "checked_on"),
        ({"modes": ["live", "live"]}, "modes"),
    ],
)
def test_config_validation_rejects(tmp_path, fake_exe, patch, needle):
    path = write_config(tmp_path, fake_exe, **patch)
    with pytest.raises(pp.ConfigError, match=needle):
        pp.load_config(path)


def test_invalid_config_exits_2(tmp_path, fake_exe):
    out = tmp_path / "report.json"
    assert pp.probe_provider(write_config(tmp_path, fake_exe, surprise=1), out) == pc.EXIT_USAGE
    assert not out.exists()


# ---------------------------------------------------------------- envelope


def test_stream_envelope_body_cap_and_shapes():
    def stream(text: str) -> bytes:
        return (json.dumps({"type": "system", "subtype": "init", "tools": []}) + "\n" + json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text}) + "\n").encode()

    ok = pp.parse_claude_stream(stream(json.dumps({"a": "é" * 10})), 100)
    assert ok["body"] == {"a": "é" * 10} and ok["body_bytes"] == len(json.dumps({"a": "é" * 10}).encode())
    big = pp.parse_claude_stream(stream(json.dumps({"a": "x" * 200})), 100)
    assert big["body"] is None and "body_cap_exceeded" in big["errors"]
    assert "body_not_json" in pp.parse_claude_stream(stream("nope"), 100)["errors"]
    assert "body_not_json" in pp.parse_claude_stream(stream('{"a": NaN}'), 100)["errors"]
    assert "envelope_line_not_json" in pp.parse_claude_stream(b"garbage\n", 100)["errors"]
    assert "envelope_result_count" in pp.parse_claude_stream(b"", 100)["errors"]


# ---------------------------------------------------------------- end to end against the fake


def test_isolated_fake_passes_isolation_but_is_not_certified(tmp_path, fake_exe):
    out = tmp_path / "report.json"
    code = pp.probe_provider(write_config(tmp_path, fake_exe), out)
    rep = section(out)
    assert code == pc.EXIT_UNAVAILABLE
    dims = {k: v["verdict"] for k, v in rep["dimensions"].items()}
    assert dims["tool_inventory"] == "pass"
    assert dims["customization_absence"] == "pass", rep["dimensions"]["customization_absence"]
    assert dims["environment_isolation"] == "pass", [r["environment"] for r in rep["request_capture"]["isolated_runs"]]
    assert dims["bounds_and_cancellation"] == "pass", rep["request_capture"]["bounds"]
    assert dims["auth_route"] == "not_run" and dims["operator_attestation"] == "not_run"
    assert rep["certified"] is False and rep["usable_route"] is None
    # Detectors were proven by the non-isolated controls.
    assert rep["request_capture"]["detector_validation"]["unvalidated_detectors"] == []
    for run in rep["request_capture"]["isolated_runs"]:
        env = run["environment"]
        assert env["host_markers_present"] == [] and env["role_marker_present"] is True
        assert env["leaked_unselected_keys"] == []
        assert "CLAUDECODE" not in env["child_keys"] and "GITHUB_TOKEN" not in env["child_keys"]


def test_customizations_loaded_despite_flags_fail(tmp_path, fake_exe):
    out = tmp_path / "report.json"
    cfg = write_config(tmp_path, fake_exe, nonsecret_env={"FAKE_CLI_SCENARIO": "ignores_bare"})
    assert pp.probe_provider(cfg, out) == pc.EXIT_UNAVAILABLE
    rep = section(out)
    cust = rep["dimensions"]["customization_absence"]
    assert cust["verdict"] == "fail"
    assert {"sentinel_hook_ran", "sentinel_mcp_started", "request_contains_sentinel"} <= set(cust["failures"])
    assert rep["dimensions"]["tool_inventory"]["verdict"] == "fail"


def test_leaked_tools_fail(tmp_path, fake_exe):
    out = tmp_path / "report.json"
    pp.probe_provider(write_config(tmp_path, fake_exe, nonsecret_env={"FAKE_CLI_SCENARIO": "leaks_tools"}), out)
    tools = section(out)["dimensions"]["tool_inventory"]
    assert tools["verdict"] == "fail" and {"host_reports_tools", "request_offers_tools"} <= set(tools["failures"])


def test_structured_output_flag_tool_is_not_ignored(tmp_path, fake_exe):
    out = tmp_path / "report.json"
    args = ISOLATED + ["--json-schema", '{"type":"object"}']
    pp.probe_provider(write_config(tmp_path, fake_exe, invocation_args=args), out)
    assert section(out)["dimensions"]["tool_inventory"]["verdict"] == "fail"


def test_descendants_are_killed_after_exit(tmp_path, fake_exe):
    out = tmp_path / "report.json"
    pp.probe_provider(write_config(tmp_path, fake_exe, nonsecret_env={"FAKE_CLI_SCENARIO": "grandchild"}), out)
    rep = section(out)
    for run in rep["request_capture"]["isolated_runs"]:
        assert run["process"]["process_tree_cleaned"] is True
        assert run["process"]["descendants_outlived_exit"] is True
    assert rep["request_capture"]["bounds"]["hang"]["pass"] is True


def test_stderr_is_bounded_not_fatal(tmp_path, fake_exe):
    out = tmp_path / "report.json"
    pp.probe_provider(write_config(tmp_path, fake_exe, nonsecret_env={"FAKE_CLI_SCENARIO": "stderr_flood"}), out)
    run = section(out)["request_capture"]["isolated_runs"][0]
    assert run["process"]["stderr_truncated"] is True
    assert run["process"]["stderr_bytes_retained"] == pc.STDERR_CAP


def test_missing_executable_is_unavailable(tmp_path):
    out = tmp_path / "report.json"
    code = pp.probe_provider(write_config(tmp_path, tmp_path / "does-not-exist"), out)
    assert code == pc.EXIT_UNAVAILABLE
    assert section(out)["blocking_reasons"] == ["executable_missing"]


def test_live_without_route_is_not_run(tmp_path, fake_exe):
    out = tmp_path / "report.json"
    pp.probe_provider(write_config(tmp_path, fake_exe, modes=["live"]), out)
    rep = section(out)
    assert rep["live"] == {"status": "not_run", "reason": "no_auth_route_configured"}
    assert rep["dimensions"]["customization_absence"]["verdict"] == "not_run"


def test_live_route_with_missing_credential_is_not_run(tmp_path, fake_exe, monkeypatch):
    monkeypatch.delenv("FAKE_PROBE_ROUTE_KEY", raising=False)
    out = tmp_path / "report.json"
    route = {"kind": "env_api_key", "billing": "api", "env_keys": ["FAKE_PROBE_ROUTE_KEY"]}
    pp.probe_provider(write_config(tmp_path, fake_exe, modes=["live"], auth_route=route), out)
    assert section(out)["live"]["reason"] == "selected_auth_env_missing"


def test_complete_fake_route_exercises_certified_path(tmp_path, fake_exe, monkeypatch):
    """The success path of the verdict logic; a fake host is never real evidence."""
    monkeypatch.setenv("FAKE_PROBE_ROUTE_KEY", "fake-route-value-0001")
    out = tmp_path / "report.json"
    route = {"kind": "env_api_key", "billing": "api", "env_keys": ["FAKE_PROBE_ROUTE_KEY"], "expected_api_key_source": "none"}
    att = {"background_use": "checked_eligible", "basis": "unit test", "checked_on": "2026-10-15"}
    code = pp.probe_provider(write_config(tmp_path, fake_exe, modes=["request_capture", "live"], auth_route=route, operator_attestation=att), out)
    rep = section(out)
    assert code == pc.EXIT_CERTIFIED, (rep["blocking_dimensions"], rep["dimensions"])
    assert rep["certified"] is True
    text = out.read_text(encoding="utf-8")
    assert "fake-route-value-0001" not in text  # credential values never reach the report
    live_env = rep["live"]["isolated_runs"][0]["environment"]
    assert "FAKE_PROBE_ROUTE_KEY" in live_env["child_keys"]
    assert "ANTHROPIC_AUTH_TOKEN" not in live_env["child_keys"]


def test_live_auth_source_mismatch_fails(tmp_path, fake_exe, monkeypatch):
    monkeypatch.setenv("FAKE_PROBE_ROUTE_KEY", "v")
    out = tmp_path / "report.json"
    route = {"kind": "env_api_key", "billing": "api", "env_keys": ["FAKE_PROBE_ROUTE_KEY"], "expected_api_key_source": "ANTHROPIC_API_KEY"}
    att = {"background_use": "checked_eligible", "checked_on": "2026-10-15"}
    assert pp.probe_provider(write_config(tmp_path, fake_exe, modes=["live"], auth_route=route, operator_attestation=att), out) == pc.EXIT_UNAVAILABLE
    assert section(out)["dimensions"]["auth_route"]["failures"] == ["auth_route_mismatch"]


# ---------------------------------------------------------------- report


def test_report_merge_preserves_other_sections(tmp_path):
    out = tmp_path / "report.json"
    pc.merge_report_section(out, "delivery", "claude_code", {"verdict": "x"})
    pc.merge_report_section(out, "provider_isolation", "claude_cli", {"verdict": "y"})
    pc.merge_report_section(out, "provider_isolation", "other", {"verdict": "z"})
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["sections"]["delivery"]["claude_code"] == {"verdict": "x"}
    assert set(data["sections"]["provider_isolation"]) == {"claude_cli", "other"}


def test_sanitizer_keeps_digests_and_scrubs_secrets():
    s = pc.Sanitizer({"/tmp/fixture": "<fixture>"}, secrets=["hunter2-secret"])
    digest = "a" * 64
    assert s.text(f"{digest} /tmp/fixture/x hunter2-secret sk-ant-api03-abcdefghijkl") == f"{digest} <fixture>/x <redacted> <redacted>"
    ident = "request_capture-session_start-positive-1"
    assert s.text(ident) == ident and s.text("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC") == "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"
    assert s.text("token: abc") == "<redacted>"
    assert s.text("Zm9vYmFyQmF6UXV4MTIzNDU2Nzg5MEFCQ0RFRkdISUpLTE1O") == "<redacted>"


def test_example_config_is_valid_and_secret_free():
    example = REPO / "tools" / "probe_config.example.json"
    cfg = pp.load_config(example)
    assert cfg["auth_route"]["env_keys"] == ["ANTHROPIC_API_KEY"]
    assert "--json-schema" not in cfg["invocation_args"]  # decision 0002: it adds a tool
    assert not pc._SECRETISH.search(json.dumps(cfg["nonsecret_env"]))


def test_env_check_tolerates_only_launcher_shell_keys(tmp_path, fake_exe):
    cfg = pp.load_config(write_config(tmp_path, fake_exe))
    probe = pp.Probe(cfg, pp.Fixture(tmp_path / "fx"), str(fake_exe))
    parent = probe.parent("host_marked")
    child = probe.child_env(parent, "request_capture", "http://127.0.0.1:9")

    def check(observed):
        run = pc.BoundedResult()
        run.observed_env_keys = observed
        return pp.env_check(probe, child, parent, run, "request_capture")

    assert check(sorted(child) + ["PWD", "SHLVL"])["failures"] == []
    assert "observed_env_differs_from_constructed" in check(sorted(child) + ["EXTRA"])["failures"]
    assert "observed_env_differs_from_constructed" in check(sorted(child)[1:])["failures"]
    assert "host_marker_present" in check(sorted(child) + ["CLAUDECODE"])["failures"]


def test_empty_proc_environ_is_resampled_not_observed(monkeypatch):
    reads = iter([b"", b"", b"PATH=/bin\0RECALITH_CURATOR_INSTALLATION=x\0"])
    monkeypatch.setattr(pc.Path, "read_bytes", lambda self: next(reads))
    assert pc.observed_process_environment_keys(1, interval_s=0) == ["PATH", "RECALITH_CURATOR_INSTALLATION"]
    monkeypatch.setattr(pc.Path, "read_bytes", lambda self: b"")
    assert pc.observed_process_environment_keys(1, attempts=3, interval_s=0) is None


def test_detectors_validate_when_fixture_path_is_a_symlink(tmp_path, fake_exe, monkeypatch):
    """macOS temp dirs resolve through /private; per-project sentinels must still be found."""
    real = tmp_path / "real-tmp"
    real.mkdir()
    link = tmp_path / "linked-tmp"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(pp.tempfile, "tempdir", str(link))
    out = tmp_path / "report.json"
    pp.probe_provider(write_config(tmp_path, fake_exe), out)
    rep = section(out)
    assert rep["request_capture"]["detector_validation"]["unvalidated_detectors"] == []
    assert rep["dimensions"]["customization_absence"]["verdict"] == "pass"
