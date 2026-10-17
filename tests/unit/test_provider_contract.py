"""Task 7: the provider contract (SYSTEM_SPEC §9.1, §6.3; DATA_CONTRACTS §7, §8, §11).

Route status, certification records, envelope parsing and output bounds. The
"certified" configurations built here are controlled unit states for the
gate logic (DATA_CONTRACTS §11 guards); they are not certification evidence
and no test here launches a real provider route.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from recalith.contracts.common import digest_of, new_id
from recalith.contracts.config import WIRE_STDOUT_CAP, ProviderConfig, body_cap_for
from recalith.contracts.operations import ModelResponse
from recalith.providers import base, claude_cli, isolation, json_process
from recalith.providers.errors import IsolationViolation

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "providers"
sys.path.insert(0, str(FIXTURES))
import fake_backend  # noqa: E402

INSTALLATION = "inst_31313131-3131-4131-8131-313131313131"
SELECTED = "ANTHROPIC_API_KEY"
KEY_VALUE = "sel" + "ected-route-value"  # built by concatenation: never a credential-shaped literal


def version_exe(tmp_path: Path, version: str, name: str = "fake-claude") -> Path:
    """An executable that answers ``--version`` like the host CLI (and nothing else)."""
    if os.name == "nt":
        exe = tmp_path / f"{name}.cmd"
        exe.write_text(f"@echo {version} (Claude Code)\r\n", encoding="utf-8")
    else:
        exe = tmp_path / name
        exe.write_text(f"#!/bin/sh\necho '{version} (Claude Code)'\n", encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return exe


def config(executable: Path | str = "/nonexistent/claude", *, certified: bool = False, version: str = "9.9.9", **overrides) -> ProviderConfig:
    data = {
        "provider_id": "claude_cli", "installation_id": INSTALLATION, "backend": "claude_cli", "executable": str(executable), "configured_model": "explicit-model",
        "auth_route": "env_api_key", "auth_env_keys": [SELECTED], "expected_api_key_source": SELECTED, "invocation_args": list(claude_cli.ISOLATION_ARGS),
        "nonsecret_env": {"DISABLE_AUTOUPDATER": "1"}, "certification": {"certified": False},
    }
    data.update(overrides)
    cfg = ProviderConfig.model_validate(data)
    if certified:
        cert = {
            "certified": True, "certified_at": "2026-10-17T00:00:00.000000Z", "host_version": version, "report_digest": digest_of(["report"]),
            "executable_sha256": base.executable_digest(str(executable)), "mode": "live", "operator_attestation": "checked_eligible",
            "auth_env_keys": [SELECTED], "expected_api_key_source": SELECTED, "invocation_digest": base.invocation_digest(cfg),
        }
        cfg = ProviderConfig.model_validate({**cfg.model_dump(mode="json"), "certification": cert})
    return cfg


def env(**extra: str) -> dict[str, str]:
    return {"PATH": os.environ.get("PATH", ""), SELECTED: KEY_VALUE, **extra}


# ---------------------------------------------------------------------------
# Certification records


def test_certification_record_requires_a_complete_live_observation():
    cfg = config()
    full = {"certified": True, "certified_at": "2026-10-17T00:00:00.000000Z", "host_version": "9.9.9", "report_digest": "a" * 64, "executable_sha256": "b" * 64, "mode": "live", "operator_attestation": "checked_eligible", "auth_env_keys": [SELECTED], "invocation_digest": "c" * 64}
    ProviderConfig.model_validate({**cfg.model_dump(mode="json"), "certification": full})
    for change, message in (
        ({"mode": "request_capture"}, "request-capture"),
        ({"operator_attestation": "unchecked"}, "eligibility"),
        ({"host_version": None}, "records"),
        ({"auth_env_keys": []}, "auth key names"),
    ):
        with pytest.raises(ValidationError, match=message):
            ProviderConfig.model_validate({**cfg.model_dump(mode="json"), "certification": {**full, **change}})
    for bad in ({"auth_env_keys": ["CLAUDECODE"]}, {"network_env_keys": ["RECALITH_WORKER_INSTALLATION"]}, {"nonsecret_env": {"MY_TOKEN": "x"}}, {"invocation_args": ["-p", "--json-schema", "{}"]}, {"max_wire_stdout_bytes": WIRE_STDOUT_CAP + 1}):
        with pytest.raises(ValidationError):
            ProviderConfig.model_validate({**cfg.model_dump(mode="json"), **bad})


# ---------------------------------------------------------------------------
# A29 / review focus 5: unknown capability is unavailability, never a fallback


def test_unknown_capabilities_disable_backend(tmp_path):
    exe = version_exe(tmp_path, "9.9.9")
    good = config(exe, certified=True)
    assert base.route_status(good, installation_id=INSTALLATION, inherited=env()).certified  # the gate's positive control
    cases = {
        "route_uncertified": config(exe),
        "request_capture_only": config(exe, certification={"certified": False, "mode": "request_capture"}),
        "backend_certification_unavailable": config(exe, backend="json_process", provider_id="local_model"),
        "invocation_not_isolated:missing_flag:--bare": config(exe, invocation_args=[a for a in claude_cli.ISOLATION_ARGS if a != "--bare"]),
        "invocation_not_isolated:unsafe_flag:--mcp-config": config(exe, invocation_args=[*claude_cli.ISOLATION_ARGS, "--mcp-config", "x.json"]),
        "executable_missing": config(tmp_path / "absent"),
        "foreign_provider_config": config(exe, installation_id=new_id("inst")),
    }
    for reason, cfg in cases.items():
        status = base.route_status(cfg, installation_id=INSTALLATION, inherited=env())
        assert not status.certified and reason in status.reasons, (reason, status.reasons)
    # The host version changed under a certified route: recertification, not silent reuse.
    newer = tmp_path / "newer"
    newer.mkdir()
    changed = config(version_exe(newer, "9.9.10"), certified=True, version="9.9.9")
    status = base.route_status(changed, installation_id=INSTALLATION, inherited=env())
    assert status.reasons == ["host_version_changed"] and status.report()["recertification_required"] and status.observed_version == "9.9.10"
    # The executable bytes changed (same reported version).
    exe.write_text(exe.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert "executable_changed" in base.route_status(good, installation_id=INSTALLATION, inherited=env()).reasons
    assert base.route_status(None, installation_id=INSTALLATION, inherited=env()).reasons == ["provider_not_configured"]


def test_unknown_capabilities_leave_the_worker_without_a_backend(tmp_path):
    """A configured but uncertifiable route yields no model runtime; jobs wait visibly and nothing launches."""
    from recalith.contracts.config import ProjectConfig
    from recalith.contracts.common import Actor, RecordRef
    from recalith.controller import jobs, worker
    from recalith.core import identity
    from recalith.storage import db

    root = tmp_path / "project"
    root.mkdir()
    identity.initialize_installation(root, ProjectConfig.defaults_for("proj_31313131-3131-4131-8131-313131313131"))
    ctx = identity.resolve_installation(root, actor=Actor(kind="controller", id="t", channel="worker"))
    log = tmp_path / "launches.log"
    exe = tmp_path / "logging-claude"
    if os.name == "nt":
        exe = tmp_path / "logging-claude.cmd"
        exe.write_text(f"@echo %* >> {log}\r\n@echo 9.9.9 (Claude Code)\r\n", encoding="utf-8")
    else:
        exe.write_text(f"#!/bin/sh\necho \"$*\" >> '{log}'\necho '9.9.9 (Claude Code)'\n", encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    cfg = config(exe, installation_id=ctx.installation_id, invocation_args=[a for a in claude_cli.ISOLATION_ARGS if a != "--strict-mcp-config"])
    base.save_provider_config(root, cfg)
    if os.name != "nt":
        assert stat.S_IMODE(base.provider_path(root).stat().st_mode) == 0o600
    provider, runtime = worker.configured_provider(ctx, env())
    assert runtime is None and provider.backend is None
    report = provider.report()
    assert report["state"] == "unavailable" and "route_uncertified" in report["reasons"] and "invocation_not_isolated:missing_flag:--strict-mcp-config" in report["reasons"]
    with db.open_store(ctx) as store, store.transaction() as txn:
        jobs.enqueue(txn, kind="extract_claims", input_refs=[RecordRef(kind="claim", id=new_id("claim"), revision=1)], now="2026-10-17T00:00:00.000000Z", prompt_version="extract_claims@1")
    w = worker.Worker(ctx, model=runtime, provider=provider)
    try:
        w.poll_once()
        status = w.status()
    finally:
        w.close()
    assert status["model_lane"] == "provider_unavailable" and status["provider"]["state"] == "unavailable"
    assert status["queue"]["waiting_reasons"] == {"pending:provider_unavailable": 1}
    launched = log.read_text(encoding="utf-8").split() if log.exists() else []
    assert set(launched) <= {"--version"}  # only the version probe ever ran; never a model call
    # A malformed route file is reported invalid, never guessed around.
    base.provider_path(root).write_text("{\"provider_schema\": 1, \"provider\": {}}", encoding="utf-8")
    assert base.ProviderSupervisor(ctx, inherited=env()).report()["reasons"] == ["provider_config_invalid"]


# ---------------------------------------------------------------------------
# A29: an auth route change is visible and never routed around


def test_auth_route_change_is_visible(tmp_path):
    exe = version_exe(tmp_path, "9.9.9")
    cfg = config(exe, certified=True)
    assert base.route_status(cfg, installation_id=INSTALLATION, inherited=env()).certified
    # The selected key is gone from the worker's environment: unavailable, and no other key is tried.
    alternates = {"ANTHROPIC_AUTH_TOKEN": "alt", "CLAUDE_CODE_USE_BEDROCK": "1", "AWS_PROFILE": "other", "ANTHROPIC_BASE_URL": "https://elsewhere.invalid"}
    missing = base.route_status(cfg, installation_id=INSTALLATION, inherited={"PATH": os.environ.get("PATH", ""), **alternates})
    assert missing.reasons == ["selected_auth_missing"]
    # The configured route differs from what was certified (another key, another expected source).
    switched = ProviderConfig.model_validate({**cfg.model_dump(mode="json"), "auth_env_keys": ["ANTHROPIC_AUTH_TOKEN"]})
    assert "auth_route_changed" in base.route_status(switched, installation_id=INSTALLATION, inherited=env(ANTHROPIC_AUTH_TOKEN="x")).reasons
    resourced = ProviderConfig.model_validate({**cfg.model_dump(mode="json"), "expected_api_key_source": "apiKeyHelper"})
    assert "auth_route_changed" in base.route_status(resourced, installation_id=INSTALLATION, inherited=env()).reasons
    # A live curator environment carries only the selected route: alternate billing/route keys never pass.
    with isolation.PrivateRoot() as root:
        child, report = isolation.curator_environment(cfg, root, env(**alternates, CLAUDECODE="1"), mode="live")
    assert child[SELECTED] == KEY_VALUE and not set(alternates) & set(child) and "CLAUDECODE" not in child
    assert child["RECALITH_CURATOR_INSTALLATION"] == INSTALLATION and KEY_VALUE not in json.dumps(report)
    # Request capture uses no account: neither the selected auth key nor managed network keys reach the child.
    capture_cfg = ProviderConfig.model_validate({**cfg.model_dump(mode="json"), "auth_env_keys": ["ANTHROPIC_AUTH_TOKEN"], "network_env_keys": ["HTTPS_PROXY"]})
    with isolation.PrivateRoot() as root:
        capture_child, capture_report = isolation.curator_environment(capture_cfg, root, env(ANTHROPIC_AUTH_TOKEN="x", HTTPS_PROXY="http://proxy.invalid:1"), mode="request_capture")
    assert "ANTHROPIC_AUTH_TOKEN" not in capture_child and "HTTPS_PROXY" not in capture_child and capture_report["route_keys"] == []
    # The host reports another auth source at call time: the call is rejected and the backend disabled.
    backend = base.ProviderBackend(cfg, inherited=env())
    stdout = stream(fake_backend.json.dumps({"operations": [], "no_op_reason": "x"}), api_key_source="none")
    result = base.evaluate_outcome(base.LaunchOutcome(stdout=stdout), backend, purpose="update_task", body_cap=body_cap_for("update_task"), estimate=10)
    assert result.code == "auth_route_mismatch" and result.response is None
    assert backend.unavailable_reason == "auth_route_mismatch" and not backend.available
    with pytest.raises(Exception) as err:
        backend.launch(b"{}", timeout_s=5, purpose="update_task")
    assert "unavailable" in str(err.value)
    # The worker's lane leases nothing for a disabled route: no lease, no reservation, the reason stays visible.
    from recalith.contracts.common import Actor, RecordRef
    from recalith.contracts.config import ProjectConfig
    from recalith.controller import jobs, worker
    from recalith.core import identity
    from recalith.storage import db

    root_dir = tmp_path / "project"
    root_dir.mkdir()
    identity.initialize_installation(root_dir, ProjectConfig.defaults_for("proj_31313131-3131-4131-8131-313131313131"))
    ctx = identity.resolve_installation(root_dir, actor=Actor(kind="controller", id="t", channel="worker"))
    with db.open_store(ctx) as store, store.transaction() as txn:
        job_id, _ = jobs.enqueue(txn, kind="update_task", input_refs=[RecordRef(kind="task", id=new_id("task"), revision=1)], now="2000-01-01T00:00:00.000000Z", prompt_version="update_task@1")
    w = worker.Worker(ctx, model=worker.ModelRuntime(backend, lambda store, job, rounds: pytest.fail("a disabled route never prepares a request")))
    try:
        assert w.lane.step() is False
        w.poll_once()
        status = w.status()
    finally:
        w.close()
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        job = jobs.get_job(view, job_id)
        assert view.execute("SELECT COUNT(*) FROM provider_usage").fetchone()[0] == 0
    assert job.lease_generation == 0 and job.state == "pending" and job.last_error_code == "provider_unavailable"
    assert status["model_lane"] == "provider_unavailable"


# ---------------------------------------------------------------------------
# Envelopes and bounds (A30)


def stream(body: str, *, tools=(), mcp=(), plugins=(), version="9.9.9", api_key_source=SELECTED, results=1, pad: int = 0) -> bytes:
    init = {"type": "system", "subtype": "init", "tools": list(tools), "mcp_servers": [{"name": m} for m in mcp], "plugins": [{"name": "builtin-a", "path": "builtin"}, *plugins], "apiKeySource": api_key_source, "claude_code_version": version, "model": "resolved-model-id"}
    lines = [init, {"type": "assistant", "message": {"content": [{"type": "text", "text": body}]}, "padding": "m" * pad}]
    lines += [{"type": "result", "subtype": "success", "is_error": False, "result": body, "usage": {"input_tokens": 40, "cache_read_input_tokens": 2, "output_tokens": 7}}] * results
    return ("\n".join(json.dumps(x) for x in lines) + "\n").encode("utf-8")


class Spy:
    provider_id = "spy"
    configured_model = "explicit-model"

    def __init__(self, adapter=json_process, expect=None):
        self.adapter, self.expect, self.unwrapped = adapter, expect, 0

    def unwrap(self, stdout: bytes):
        self.unwrapped += 1
        return self.adapter.unwrap(stdout, expect=self.expect)


def test_envelope_is_bounded_before_body_validation():
    cap = body_cap_for("update_task")
    spy = Spy()
    # Wire overflow is rejected before the envelope is even parsed.
    flood = base.evaluate_outcome(base.LaunchOutcome(stdout=b"", overflowed=True), spy, purpose="update_task", body_cap=cap, estimate=1)
    big = base.evaluate_outcome(base.LaunchOutcome(stdout=b"z" * (WIRE_STDOUT_CAP + 1)), spy, purpose="update_task", body_cap=cap, estimate=1)
    assert flood.code == big.code == "wire_stdout_oversized" and spy.unwrapped == 0
    # A decoded body one byte over its cap is rejected as oversized, even though it is not JSON either:
    # the byte count comes first and nothing is clipped to make it parse.
    over = "{" + "x" * cap
    result = base.evaluate_outcome(base.LaunchOutcome(stdout=fake_envelope(over)), spy, purpose="update_task", body_cap=cap, estimate=1)
    assert result.code == "response_body_oversized" and result.response is None and result.local is not None
    # A body of exactly the cap is accepted (no off-by-one tightening).
    exact = json.dumps({"operations": [], "no_op_reason": "y" * 1000})
    assert base.evaluate_outcome(base.LaunchOutcome(stdout=fake_envelope(exact)), spy, purpose="update_task", body_cap=len(exact.encode("utf-8")), estimate=1).code is None
    # Multi-byte text counts in original UTF-8 bytes, not characters or escaped envelope bytes.
    accented = json.dumps({"operations": [], "no_op_reason": "é" * 500}, ensure_ascii=False)
    ok = base.evaluate_outcome(base.LaunchOutcome(stdout=fake_envelope(accented, ensure_ascii=True)), spy, purpose="update_task", body_cap=len(accented.encode("utf-8")), estimate=1)
    assert ok.code is None and ok.response is not None
    tight = base.evaluate_outcome(base.LaunchOutcome(stdout=fake_envelope(accented, ensure_ascii=True)), spy, purpose="update_task", body_cap=len(accented.encode("utf-8")) - 1, estimate=1)
    assert tight.code == "response_body_oversized"
    # Malformed envelopes and bodies are distinct rejections.
    for stdout in (b"not json", json.dumps({"type": "other"}).encode(), b"[1]"):
        assert base.evaluate_outcome(base.LaunchOutcome(stdout=stdout), spy, purpose="update_task", body_cap=cap, estimate=1).code == "envelope_invalid"
    claude = Spy(claude_cli, claude_cli.Expectations(host_version="9.9.9"))
    assert base.evaluate_outcome(base.LaunchOutcome(stdout=stream("{}", results=2)), claude, purpose="update_task", body_cap=cap, estimate=1).code == "envelope_invalid"
    assert base.evaluate_outcome(base.LaunchOutcome(stdout=b'{"type": "result"}\nnot-json\n'), claude, purpose="update_task", body_cap=cap, estimate=1).code == "envelope_invalid"
    assert base.evaluate_outcome(base.LaunchOutcome(stdout=fake_envelope("not json {")), spy, purpose="update_task", body_cap=cap, estimate=1).code == "response_invalid"
    # Timeouts and nonzero exits never reach the parser.
    assert base.evaluate_outcome(base.LaunchOutcome(stdout=b"", timed_out=True, returncode=None), spy, purpose="update_task", body_cap=cap, estimate=1).code == "provider_timeout"
    assert base.evaluate_outcome(base.LaunchOutcome(stdout=fake_envelope("{}"), returncode=3), spy, purpose="update_task", body_cap=cap, estimate=1).code == "provider_failed"


def fake_envelope(body: str, *, ensure_ascii: bool = True, pad: int = 0) -> bytes:
    return json.dumps({"type": "result", "result": body, "usage": {"input_tokens": 3, "output_tokens": 2}, "padding": "m" * pad}, ensure_ascii=ensure_ascii).encode("utf-8")


def test_15kb_episode_response_is_accepted():
    """A valid 15 KB episode body passes its 24,000-byte allowance inside a much larger host envelope (A30)."""
    body = next(b for b in (fake_backend.body_episode(n) for n in range(15_000, 20_000, 100)) if len(b.encode("utf-8")) >= 15_000)
    assert 15_000 <= len(body.encode("utf-8")) <= body_cap_for("build_episode")
    for adapter, stdout, expect in (
        (claude_cli, fake_backend.stream_envelope(body, 60_000).encode("utf-8"), claude_cli.Expectations(host_version="9.9.9", api_key_source="ANTHROPIC_API_KEY")),
        (json_process, fake_envelope(body, pad=60_000), None),
    ):
        assert len(stdout) > 2 * len(body.encode("utf-8")) and len(stdout) <= WIRE_STDOUT_CAP
        result = base.evaluate_outcome(base.LaunchOutcome(stdout=stdout, duration_ms=12), Spy(adapter, expect), purpose="build_episode", body_cap=body_cap_for("build_episode"), estimate=100)
        assert result.code is None, result.code
        response = result.response
        assert isinstance(response, ModelResponse) and [op.kind for op in response.operations] == ["create_episode"]
        # Usage and provenance are adapter-owned: from the envelope and the configuration, never from model text.
        assert response.usage.estimated_input_tokens == 100 and response.usage.duration_ms == 12
        assert response.provenance is not None and response.provenance.provider_id == "spy" and response.provenance.configured_model == "explicit-model"
        if adapter is claude_cli:
            assert response.usage.input_tokens == 42 and response.provenance.resolved_model == "fake-resolved-model"
    # The same body over a purpose with a smaller allowance is rejected, not clipped.
    stdout = fake_envelope(body)
    assert base.evaluate_outcome(base.LaunchOutcome(stdout=stdout), Spy(), purpose="update_task", body_cap=body_cap_for("update_task"), estimate=1).code == "response_body_oversized"


def test_model_text_cannot_supply_usage_or_provenance():
    body = json.dumps({"operations": [], "no_op_reason": "x", "usage": {"input_tokens": 0}, "provenance": {"provider_id": "other"}})
    result = base.evaluate_outcome(base.LaunchOutcome(stdout=fake_envelope(body)), Spy(), purpose="update_task", body_cap=body_cap_for("update_task"), estimate=1)
    assert result.code == "response_invalid"
    controller_only = json.dumps({"operations": [{"local_ref": "a", "kind": "create_task", "depends_on": [], "target": None, "payload": {}, "evidence": [], "reason": "x"}]})
    result = base.evaluate_outcome(base.LaunchOutcome(stdout=fake_envelope(controller_only)), Spy(), purpose="update_task", body_cap=body_cap_for("update_task"), estimate=1)
    assert result.code is None and result.response.operations == [] and [m.reason_code for m in result.response.malformed] == ["malformed_operation"]


@pytest.mark.parametrize(
    ("change", "code"),
    [({"tools": ["Bash"]}, "isolation_tools_exposed"), ({"mcp": ["server"]}, "isolation_mcp_present"), ({"plugins": [{"name": "third-party", "path": "/x"}]}, "isolation_plugins_present"), ({"version": "9.9.10"}, "host_version_changed")],
)
def test_per_call_host_diagnostic_rechecks_isolation(change, code):
    """Every call re-reads the host's own init diagnostic; a violation disables the backend (review focus 5)."""
    backend = base.ProviderBackend(config("/bin/true", certified=False), inherited=env())
    backend.expect = claude_cli.Expectations(host_version="9.9.9", api_key_source=SELECTED)
    result = base.evaluate_outcome(base.LaunchOutcome(stdout=stream(json.dumps({"operations": [], "no_op_reason": "x"}), **change)), backend, purpose="update_task", body_cap=body_cap_for("update_task"), estimate=1)
    assert result.code == code and backend.unavailable_reason == code
    with pytest.raises(IsolationViolation):
        claude_cli.check_init(None, claude_cli.Expectations(host_version=None))


def test_certified_argument_array_is_checked_not_guessed():
    assert claude_cli.argument_problems(claude_cli.ISOLATION_ARGS) == []
    assert "flag_value:--tools" in claude_cli.argument_problems([a if a != "" else "Bash" for a in claude_cli.ISOLATION_ARGS])
    assert "json_schema_tool" in claude_cli.argument_problems([*claude_cli.ISOLATION_ARGS, "--json-schema", "{}"])
    assert "model_not_explicit" in claude_cli.argument_problems([a.replace("{model}", "some-model") for a in claude_cli.ISOLATION_ARGS])
    argv = claude_cli.argv("/x/claude", claude_cli.ISOLATION_ARGS, model="m-1", system_prompt="SYS")
    assert argv[0] == "/x/claude" and argv[argv.index("--model") + 1] == "m-1" and argv[argv.index("--system-prompt") + 1] == "SYS"
    assert isinstance(argv, list) and "{model}" not in argv  # an argument array; never a shell string


def test_sentinel_fixtures_are_the_task0_fixtures():
    """The production isolation check plants exactly the Task 0 sentinel fixtures."""
    for name in ("sentinels.json", "sentinel_hook.py", "sentinel_mcp.py"):
        assert (isolation.SENTINEL_DIR / name).read_bytes() == (FIXTURES / "isolation" / name).read_bytes()


def test_private_root_is_fresh_and_outside_checkouts(tmp_path):
    with isolation.PrivateRoot() as root:
        assert root.base.name.startswith("recalith-curator-") and not isolation.inside_checkout(root.base)
        assert {p.name for p in root.base.iterdir()} == {"home", "work", "tmp"}
        if os.name != "nt":
            assert stat.S_IMODE(root.base.stat().st_mode) == 0o700
        kept = root.base
    assert not kept.exists()
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    with pytest.raises(isolation.PrivateRootError):
        isolation.PrivateRoot(base=str(checkout))
    assert list(checkout.iterdir()) == [checkout / ".git"]  # the refused root was removed
