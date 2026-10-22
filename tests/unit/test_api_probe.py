"""Decision 0023: the operator probe and runtime check for direct-API backends.

``tools/probe_provider.py`` and ``tools/check_provider_runtime.py`` run the
production adapter against loopback fake providers owned by the test. A
loopback endpoint is exactly the local-server case of decision 0023, so a
"certified" result here exercises the verdict logic for that case; it is
test data, never evidence about any real provider, and no test makes a real
network call.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tests" / "fixtures" / "providers"))

import check_provider_runtime as cpr  # noqa: E402
import fake_api_server as fas  # noqa: E402
import probe_common as pc  # noqa: E402
import probe_provider as pp  # noqa: E402

KEY = "FAKE_PROVIDER_API_KEY"
VALUE = "fake-" + "provider-" + "value-0003"


@pytest.fixture(autouse=True)
def _ordinary_terminal(monkeypatch):
    for marker in pc.DEFAULT_HOST_MARKERS:
        monkeypatch.delenv(marker, raising=False)


def write_config(tmp_path: Path, url: str, *, backend: str = "openai_compatible", **overrides) -> Path:
    if backend == "anthropic_messages":
        endpoint = {"url": url, "dialect": "messages", "auth_header": "x-api-key", "output_cap_field": "max_tokens", "json_mode": "none", "api_version": "2023-06-01"}
    else:
        endpoint = {"url": url, "dialect": "chat_completions", "auth_header": "authorization_bearer", "output_cap_field": "max_completion_tokens", "json_mode": "json_object", "api_version": None}
    cfg = {
        "provider_id": "fake_api",
        "backend": backend,
        "model": "fake-model",
        "endpoint": endpoint,
        "modes": ["request_capture"],
        "limits": {"bounds_timeout_seconds": 2, "timeout_seconds": 30},
        "auth_route": {"kind": "env_api_key", "billing": "api", "env_keys": [KEY]},
        "operator_attestation": {"background_use": "unchecked"},
    }
    cfg.update(overrides)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"config_schema": 1, "provider": cfg}), encoding="utf-8")
    return path


def section(report: Path, name: str = "provider_isolation") -> dict:
    return json.loads(report.read_text(encoding="utf-8"))["sections"][name]["fake_api"]


def project(tmp_path: Path):
    sys.path.insert(0, str(REPO / "src"))
    from recalith.contracts.common import Actor, new_id
    from recalith.contracts.config import ProjectConfig
    from recalith.core import identity

    root = tmp_path / "project"
    root.mkdir()
    identity.initialize_installation(root, ProjectConfig.defaults_for(new_id("proj")))
    return identity.resolve_installation(root, actor=Actor(kind="controller", id="t", channel="worker"))


LOCAL = {"kind": "none", "billing": "none", "env_keys": []}
NOT_APPLICABLE = {"background_use": "not_applicable_local", "basis": "loopback local server", "checked_on": "2026-10-22"}


def local_endpoint(url: str) -> dict:
    return {"url": url, "dialect": "chat_completions", "auth_header": "none", "output_cap_field": "max_completion_tokens", "json_mode": "json_object", "api_version": None}


@pytest.mark.parametrize("backend", ["anthropic_messages", "openai_compatible"])
def test_request_capture_alone_never_certifies(tmp_path, backend):
    path = "/v1/messages" if backend == "anthropic_messages" else "/v1/chat/completions"
    out = tmp_path / "report.json"
    ctx = project(tmp_path)
    code = pp.probe_provider(write_config(tmp_path, "https://api.example.test" + path, backend=backend), out, route_out=Path(ctx.root))
    rep = section(out)
    assert code == pc.EXIT_UNAVAILABLE and rep["certified"] is False and rep["backend"] == backend
    for dim in ("request_shape", "environment_isolation", "bounds_and_cancellation"):
        assert rep["dimensions"][dim]["verdict"] == "pass", (dim, rep["dimensions"][dim])
    for dim in ("auth_route", "model_identity", "schema_output", "output_cap", "endpoint_identity"):
        assert rep["dimensions"][dim]["verdict"] == "not_run", dim
    from recalith.providers import base

    stored = base.load_provider_config(ctx.root)
    assert stored.backend == backend and stored.certification.certified is False and stored.certification.mode == "request_capture"
    status = base.route_status(stored, installation_id=ctx.installation_id, inherited={KEY: VALUE})
    assert "request_capture_only" in status.reasons


def test_live_local_server_certifies_and_writes_the_route(tmp_path, monkeypatch):
    out = tmp_path / "report.json"
    ctx = project(tmp_path)
    with fas.FakeProvider("ok") as fake:
        cfg = write_config(tmp_path, "", modes=["request_capture", "live"], endpoint=local_endpoint(fake.url("/v1/chat/completions")), auth_route=LOCAL, operator_attestation=NOT_APPLICABLE)
        code = pp.probe_provider(cfg, out, route_out=Path(ctx.root), backend="openai_compatible")
        calls = fake.snapshot()
    rep = section(out)
    assert code == pc.EXIT_CERTIFIED, (rep["blocking_dimensions"], rep["dimensions"])
    assert rep["resolved_model"] == "fake-model" and rep["dimensions"]["usage"]["reported"] is True
    assert rep["dimensions"]["output_cap"]["verdict"] == "pass" and rep["dimensions"]["endpoint_identity"]["verdict"] == "pass"
    caps = sorted(json.loads(c["body"]).get("max_completion_tokens") for c in calls)
    assert caps[0] <= 64  # the deliberately small cap call ran against the live endpoint
    from recalith.providers import api, base

    stored = base.load_provider_config(ctx.root)
    cert = stored.certification
    assert cert.certified and cert.mode == "live" and cert.resolved_model == "fake-model" and cert.executable_sha256 == api.adapter_digest()
    assert base.route_status(stored, installation_id=ctx.installation_id, inherited={}).certified


@pytest.mark.parametrize("behavior,failure,dimension", [("cap_ignored", "output_cap_unenforced", "output_cap"), ("other_model", "model_mismatch", "model_identity"), ("status:401", "provider_auth_rejected", "auth_route"), ("non_json", "envelope_invalid", "schema_output")])
def test_live_failures_block_certification(tmp_path, behavior, failure, dimension):
    out = tmp_path / "report.json"
    ctx = project(tmp_path)
    with fas.FakeProvider(behavior) as fake:
        cfg = write_config(tmp_path, "", modes=["live"], endpoint=local_endpoint(fake.url("/v1/chat/completions")), auth_route=LOCAL, operator_attestation=NOT_APPLICABLE)
        code = pp.probe_provider(cfg, out, route_out=Path(ctx.root))
    rep = section(out)
    assert code == pc.EXIT_UNAVAILABLE and not rep["certified"]
    assert rep["dimensions"][dimension]["verdict"] == "fail" and failure in rep["dimensions"][dimension]["failures"], rep["dimensions"][dimension]
    from recalith.providers import base

    stored = base.load_provider_config(ctx.root)
    assert not stored.certification.certified and failure in stored.certification.failed_checks
    assert f"certification_failed:{failure}" in base.route_status(stored, installation_id=ctx.installation_id, inherited={}).reasons


def test_live_remote_needs_the_key_and_the_operators_terms(tmp_path, monkeypatch):
    monkeypatch.delenv(KEY, raising=False)
    out = tmp_path / "report.json"
    att = {"background_use": "checked_eligible", "basis": "unit", "checked_on": "2026-10-22"}
    assert pp.probe_provider(write_config(tmp_path, "https://api.example.test/v1/chat/completions", modes=["live"], operator_attestation=att), out) == pc.EXIT_UNAVAILABLE
    assert section(out)["live"]["reason"] == "selected_auth_env_missing"
    # The local attestation is refused for a remote endpoint at configuration time.
    bad = write_config(tmp_path, "https://api.example.test/v1/chat/completions", modes=["live"], operator_attestation=NOT_APPLICABLE)
    assert pp.probe_provider(bad, out) == pc.EXIT_USAGE


def test_key_values_never_reach_the_report(tmp_path, monkeypatch):
    monkeypatch.setenv(KEY, VALUE)
    out = tmp_path / "report.json"
    with fas.FakeProvider("ok") as fake:
        att = {"background_use": "not_applicable_local", "checked_on": "2026-10-22"}
        cfg = write_config(tmp_path, fake.url("/v1/chat/completions"), modes=["request_capture", "live"], operator_attestation=att)
        code = pp.probe_provider(cfg, out)
        sent = fake.snapshot()
    assert code == pc.EXIT_CERTIFIED, section(out)["dimensions"]
    assert any(dict(c["headers"]).get("Authorization") == f"Bearer {VALUE}" for c in sent)
    assert VALUE not in out.read_text(encoding="utf-8")


def test_config_and_backend_flag_validation(tmp_path):
    out = tmp_path / "report.json"
    url = "https://api.example.test/v1/chat/completions"
    assert pp.probe_provider(write_config(tmp_path, url), out, backend="claude_cli") == pc.EXIT_USAGE  # the flag must name the configured backend
    for bad in ({"executable": "/bin/true"}, {"invocation_args": ["-p"]}, {"endpoint": None}, {"backend": "codex_exec"}):
        assert pp.probe_provider(write_config(tmp_path, url, **bad), out) == pc.EXIT_USAGE, bad
    assert pp.probe_provider(write_config(tmp_path, "http://api.example.test/v1/chat/completions"), out) == pc.EXIT_USAGE  # plain http off loopback


def test_runtime_check_records_the_production_request_capture(tmp_path):
    out = tmp_path / "report.json"
    code = cpr.main(["--config", str(write_config(tmp_path, "https://api.example.test/v1/messages", backend="anthropic_messages")), "--output", str(out), "--backend", "anthropic_messages"])
    rep = section(out, "provider_runtime")
    assert code == pc.EXIT_UNAVAILABLE and rep["certifies"] is False and rep["adapter"] == "recalith.providers.api"
    assert {k: v["verdict"] for k, v in rep["isolation_checks"].items()} == {"clean": "pass", "host_marked": "pass"}, rep["isolation_checks"]
    assert "route_uncertified" in rep["route_status"]["reasons"] and rep["route_status"]["backend"] == "anthropic_messages"


@pytest.mark.parametrize("name,backend", [("probe_config.anthropic_messages.example.json", "anthropic_messages"), ("probe_config.openai_compatible.example.json", "openai_compatible"), ("probe_config.local_server.example.json", "openai_compatible")])
def test_api_example_configs_are_valid_and_secret_free(name, backend):
    path = REPO / "tools" / name
    cfg = pp.load_config(path, backend=backend)
    assert cfg["backend"] == backend and "executable" not in cfg and cfg["endpoint"]["url"]
    text = path.read_text(encoding="utf-8")
    assert not pc._SECRETISH.search(text) and "EXPLICIT" in cfg["model"]  # a placeholder, never a model name
