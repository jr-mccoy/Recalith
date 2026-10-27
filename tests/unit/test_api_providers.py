"""Decision 0023: direct-API inference backends (``anthropic_messages``, ``openai_compatible``).

Every call here is a real child process through the production path
(``providers.base.ProviderBackend`` → ``controller.launch.run_bounded`` →
the stdlib transport ``providers/http_transport.py``) against a loopback fake
provider owned by the test (``tests/fixtures/providers/fake_api_server.py``).
No test makes a real network call or uses a real key: the "key" values are
built by concatenation and the "certified" routes are controlled unit states
for the gate logic, never certification evidence.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from recalith.contracts.common import ReadSet, canonical_json, digest_of, new_id
from recalith.contracts.config import PURPOSE_OUTPUT_ALLOWANCE, ProviderConfig, body_cap_for, provider_output_cap
from recalith.contracts.operations import ModelRequest, RequestLimits
from recalith.errors import RecalithError
from recalith.fast import process_env
from recalith.prompts import CURATOR_SYSTEM_PROMPT
from recalith.providers import api, base, isolation
from recalith.providers.errors import ProviderCallFailed

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "providers"
sys.path.insert(0, str(FIXTURES))
import fake_api_server as fas  # noqa: E402

INSTALLATION = "inst_51515151-5151-4151-8151-515151515151"
KEY = "FAKE_PROVIDER_API_KEY"
VALUE = "fake-" + "provider-" + "value-0001"  # built by concatenation: never a credential-shaped literal
DECOYS = {"OPENAI_API_KEY": "dec" + "oy-openai-0001", "ANTHROPIC_API_KEY": "dec" + "oy-anthropic-0001", "GITHUB_TOKEN": "dec" + "oy-github-0001", "AWS_PROFILE": "decoy-profile"}
PATHS = {"anthropic_messages": "/v1/messages", "openai_compatible": "/v1/chat/completions"}
TOOL_KEYS = {"tools", "tool_choice", "functions", "function_call", "parallel_tool_calls", "store", "stream", "n", "metadata", "previous_response_id"}


def endpoint(backend: str, base_url: str, **overrides) -> dict:
    url = base_url
    if backend == "anthropic_messages":
        data = {"url": url, "dialect": "messages", "auth_header": "x-api-key", "output_cap_field": "max_tokens", "json_mode": "none", "api_version": "2023-06-01"}
    else:
        data = {"url": url, "dialect": "chat_completions", "auth_header": "authorization_bearer", "output_cap_field": "max_completion_tokens", "json_mode": "json_object", "api_version": None}
    data.update(overrides)
    return data


def api_config(backend: str, url: str, *, certified: bool = False, endpoint_overrides: dict | None = None, cert: dict | None = None, **overrides) -> ProviderConfig:
    data = {
        "provider_id": "fake_api", "installation_id": INSTALLATION, "backend": backend, "executable": None, "configured_model": "explicit-model",
        "auth_route": "env_api_key", "auth_env_keys": [KEY], "invocation_args": [], "endpoint": endpoint(backend, url, **(endpoint_overrides or {})),
        "certification": {"certified": False},
    }
    data.update(overrides)
    cfg = ProviderConfig.model_validate(data)
    if certified:
        record = {
            "certified": True, "certified_at": "2026-10-22T00:00:00.000000Z", "report_digest": digest_of(["unit"]), "executable_sha256": api.adapter_digest(),
            "mode": "live", "operator_attestation": "not_applicable_local", "auth_env_keys": list(cfg.auth_env_keys), "invocation_digest": base.invocation_digest(cfg),
            "resolved_model": cfg.expected_resolved_model or cfg.configured_model,
        }
        record.update(cert or {})
        cfg = ProviderConfig.model_validate({**cfg.model_dump(mode="json"), "certification": record})
    return cfg


def env(**extra: str) -> dict[str, str]:
    base_env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP", "TMPDIR", "LANG") if k in os.environ}
    return {**base_env, KEY: VALUE, **extra}


def request(purpose: str = "update_task", *, timeout: int = 60) -> ModelRequest:
    limits = RequestLimits(max_input_bytes=96 * 1024, reserved_output_estimate=PURPOSE_OUTPUT_ALLOWANCE[purpose], max_body_bytes=body_cap_for(purpose), max_wire_stdout_bytes=262144, max_stderr_bytes=65536, timeout_seconds=timeout)
    return ModelRequest(request_schema=1, job_id=new_id("job"), purpose=purpose, prompt_version=f"{purpose}@1", instruction_text="unit", read_set=ReadSet(workspace_id=new_id("ws"), policy_revision=1, tombstone_epoch=0), output_schema={"type": "object"}, limits=limits)


def call(cfg: ProviderConfig, inherited: dict, *, purpose: str = "update_task", timeout: float = 60, output_cap: int | None = None):
    backend = base.ProviderBackend(cfg, inherited=inherited)
    raw = canonical_json(request(purpose).model_dump(mode="json"))
    outcome = backend.launch(raw, timeout_s=timeout, purpose=purpose, output_cap=output_cap)
    result = base.evaluate_outcome(outcome, backend, purpose=purpose, body_cap=body_cap_for(purpose), estimate=len(raw) // 3)
    return backend, raw, outcome, result


BACKENDS = ("anthropic_messages", "openai_compatible")


# ---------------------------------------------------------------------------
# Contract: endpoints, dialects, auth and certification records


@pytest.mark.parametrize("backend", BACKENDS)
def test_endpoint_validation(backend):
    path = PATHS[backend]
    api_config(backend, "https://api.example.test" + path)
    api_config(backend, "http://127.0.0.1:8080" + path)
    api_config(backend, "http://localhost:11434" + path)
    api_config(backend, "http://[::1]:8000" + path)
    bad_urls = [
        "http://api.example.test" + path,  # plain http to a non-loopback host
        "http://10.0.0.5:8000" + path,
        "ftp://api.example.test" + path,
        "https://user:pw@api.example.test" + path,  # user info
        "https://api.example.test" + path + "#frag",
        "https://api.example.test" + path + "?api_key=abc",  # a credential-shaped query
        "https://api.example.test" + path + "?key=abc",
        "api.example.test" + path,
    ]
    for url in bad_urls:
        with pytest.raises(ValidationError):
            api_config(backend, url)


def test_dialect_and_auth_rules():
    url = "https://api.example.test/v1/messages"
    for bad in ({"dialect": "chat_completions"}, {"json_mode": "json_object"}, {"api_version": None}, {"output_cap_field": "max_completion_tokens"}, {"auth_header": "api-key"}):
        with pytest.raises(ValidationError):
            api_config("anthropic_messages", url, endpoint_overrides=bad)
    chat = "https://api.example.test/v1/chat/completions"
    for bad in ({"dialect": "messages"}, {"api_version": "2023-06-01"}):
        with pytest.raises(ValidationError):
            api_config("openai_compatible", chat, endpoint_overrides=bad)
    api_config("openai_compatible", chat, endpoint_overrides={"auth_header": "api-key", "output_cap_field": "max_tokens", "json_mode": "none"})
    # API backends take no executable or argument array; process backends need both.
    for bad in ({"executable": sys.executable}, {"invocation_args": ["-p"]}):
        with pytest.raises(ValidationError):
            api_config("openai_compatible", chat, **bad)
    with pytest.raises(ValidationError):
        ProviderConfig.model_validate({"provider_id": "claude_cli", "installation_id": INSTALLATION, "backend": "claude_cli", "executable": None, "configured_model": "m", "auth_route": "env_api_key", "auth_env_keys": ["ANTHROPIC_API_KEY"], "invocation_args": ["-p"], "certification": {"certified": False}})
    with pytest.raises(ValidationError):
        ProviderConfig.model_validate({"provider_id": "claude_cli", "installation_id": INSTALLATION, "backend": "claude_cli", "executable": "/bin/claude", "configured_model": "m", "auth_route": "env_api_key", "auth_env_keys": ["ANTHROPIC_API_KEY"], "invocation_args": ["-p"], "endpoint": endpoint("openai_compatible", chat), "certification": {"certified": False}})
    # No auth only for a loopback endpoint, and then with no key names and no auth header.
    api_config("openai_compatible", "http://127.0.0.1:11434/v1/chat/completions", auth_route="none", auth_env_keys=[], endpoint_overrides={"auth_header": "none"})
    for kwargs in (
        {"auth_route": "none", "auth_env_keys": [], "endpoint_overrides": {"auth_header": "none"}, "url": chat},
        {"auth_route": "none", "auth_env_keys": [KEY], "endpoint_overrides": {"auth_header": "none"}, "url": "http://127.0.0.1:1/v1/chat/completions"},
        {"auth_route": "env_api_key", "auth_env_keys": [KEY], "endpoint_overrides": {"auth_header": "none"}, "url": "http://127.0.0.1:1/v1/chat/completions"},
        {"auth_route": "env_api_key", "auth_env_keys": [], "url": chat},
    ):
        url = kwargs.pop("url")
        with pytest.raises(ValidationError):
            api_config("openai_compatible", url, **kwargs)


def test_certification_rules_for_api_routes():
    local = "http://127.0.0.1:9/v1/chat/completions"
    remote = "https://api.example.test/v1/chat/completions"
    api_config("openai_compatible", local, certified=True)  # positive control: a local server needs no provider terms
    api_config("openai_compatible", remote, certified=True, cert={"operator_attestation": "checked_eligible"})
    with pytest.raises(ValidationError, match="not_applicable_local"):
        api_config("openai_compatible", remote, certified=True)  # a remote provider's terms must be checked
    with pytest.raises(ValidationError, match="resolved model"):
        api_config("openai_compatible", local, certified=True, cert={"resolved_model": None})
    with pytest.raises(ValidationError, match="request-capture"):
        api_config("openai_compatible", local, certified=True, cert={"mode": "request_capture"})
    for unchecked in ("unchecked", "checked_ineligible"):
        with pytest.raises(ValidationError):
            api_config("openai_compatible", remote, certified=True, cert={"operator_attestation": unchecked})
    # A Claude CLI route can never use the local attestation.
    from recalith.providers import claude_cli

    cli = {"provider_id": "claude_cli", "installation_id": INSTALLATION, "backend": "claude_cli", "executable": "/bin/claude", "configured_model": "m", "auth_route": "env_api_key", "auth_env_keys": ["ANTHROPIC_API_KEY"], "invocation_args": list(claude_cli.ISOLATION_ARGS)}
    cert = {"certified": True, "certified_at": "2026-10-22T00:00:00.000000Z", "host_version": "9.9.9", "report_digest": "a" * 64, "executable_sha256": "b" * 64, "mode": "live", "operator_attestation": "not_applicable_local", "auth_env_keys": ["ANTHROPIC_API_KEY"], "invocation_digest": "c" * 64}
    with pytest.raises(ValidationError):
        ProviderConfig.model_validate({**cli, "certification": cert})


def test_invocation_digest_pins_every_request_property():
    url = "https://api.example.test/v1/chat/completions"
    reference = base.invocation_digest(api_config("openai_compatible", url))
    changes = [
        {"configured_model": "other-model"},
        {"expected_resolved_model": "explicit-model-2026"},
        {"endpoint_overrides": {"url": "https://api.example.test/v2/chat/completions"}},
        {"endpoint_overrides": {"auth_header": "api-key"}},
        {"endpoint_overrides": {"output_cap_field": "max_tokens"}},
        {"endpoint_overrides": {"json_mode": "none"}},
        {"auth_env_keys": ["OTHER_PROVIDER_KEY"]},
        {"network_env_keys": ["HTTPS_PROXY"]},
        {"nonsecret_env": {"FAKE_SWITCH": "1"}},
        {"provider_id": "other_api"},
    ]
    digests = {base.invocation_digest(api_config("openai_compatible", url, **change)) for change in changes}
    assert reference not in digests and len(digests) == len(changes)


# ---------------------------------------------------------------------------
# The exact request per dialect


def header_map(record: dict) -> dict[str, str]:
    return {k.lower(): v for k, v in record["headers"]}


@pytest.mark.parametrize("backend", BACKENDS)
def test_exact_request_shape_per_dialect(backend):
    with fas.FakeProvider("ok") as fake:
        query = "?api-version=2026-01-01" if backend == "openai_compatible" else ""
        cfg = api_config(backend, fake.url(PATHS[backend] + query))
        backend_obj, raw, outcome, result = call(cfg, env(**DECOYS, CLAUDECODE="1"))
        assert result.code is None, (result.code, outcome.stdout[:300])
        (record,) = fake.snapshot()
    headers = header_map(record)
    assert record["method"] == "POST" and record["path"] == PATHS[backend] + query
    assert set(headers) == set(api.expected_header_names(cfg))
    if backend == "anthropic_messages":
        assert headers["x-api-key"] == VALUE and headers["anthropic-version"] == "2023-06-01" and "authorization" not in headers
    else:
        assert headers["authorization"] == f"Bearer {VALUE}" and "x-api-key" not in headers
    assert sum(VALUE in v for v in headers.values()) == 1  # the selected key travels in exactly one header
    wire = record["body"] + json.dumps(record["headers"]).encode()
    assert not [k for k, v in DECOYS.items() if v.encode() in wire]  # no other credential reaches the provider
    cap = provider_output_cap("update_task")  # the allowance plus the reasoning headroom (decision 0029)
    assert record["body"] == api.build_body(cfg, raw, output_cap=cap)  # byte-identical to what the engine built
    body = json.loads(record["body"])
    assert set(body) == api.expected_body_keys(cfg) and not set(body) & TOOL_KEYS
    assert body["model"] == "explicit-model"
    if backend == "anthropic_messages":
        assert body["max_tokens"] == cap and body["system"] == CURATOR_SYSTEM_PROMPT
        assert body["messages"] == [{"role": "user", "content": raw.decode("utf-8")}]
    else:
        assert body["max_completion_tokens"] == cap and body["response_format"] == {"type": "json_object"}
        assert body["messages"] == [{"role": "system", "content": CURATOR_SYSTEM_PROMPT}, {"role": "user", "content": raw.decode("utf-8")}]
    response = result.response
    assert response.operations == [] and response.no_op_reason == "nothing new"
    assert response.provenance.resolved_model == "explicit-model" and response.provenance.provider_id == "fake_api"
    assert response.usage.input_tokens == 45 and response.usage.output_tokens == 7
    assert response.usage.provider_request_id in {"msg_fake", "chatcmpl-fake"}


def test_output_cap_field_and_json_mode_options():
    with fas.FakeProvider("ok") as fake:
        cfg = api_config("openai_compatible", fake.url("/v1/chat/completions"), endpoint_overrides={"output_cap_field": "max_tokens", "json_mode": "none", "auth_header": "api-key"})
        _b, _raw, _o, result = call(cfg, env(), purpose="revalidate")
        (record,) = fake.snapshot()
    body = json.loads(record["body"])
    assert result.code is None and body["max_tokens"] == provider_output_cap("revalidate") == 9000
    assert "max_completion_tokens" not in body and "response_format" not in body
    assert header_map(record)["api-key"] == VALUE and "authorization" not in header_map(record)


def test_local_server_without_auth_sends_no_credential():
    with fas.FakeProvider("ok") as fake:
        cfg = api_config("openai_compatible", fake.url("/v1/chat/completions"), auth_route="none", auth_env_keys=[], endpoint_overrides={"auth_header": "none"})
        _b, _raw, _o, result = call(cfg, env(**DECOYS))
        (record,) = fake.snapshot()
    headers = header_map(record)
    assert result.code is None and "authorization" not in headers and VALUE.encode() not in record["body"]
    assert set(headers) == set(api.expected_header_names(cfg))


# ---------------------------------------------------------------------------
# Response parsing: every outcome class


DISABLING = {"model_mismatch", "isolation_tools_exposed", "provider_auth_rejected", "provider_not_found", "provider_redirect_refused", "output_cap_exceeded"}
CASES = [
    ("malformed", "envelope_invalid"),
    ("truncated", "provider_response_incomplete"),
    ("non_json", "envelope_invalid"),
    ("refusal", "provider_refused"),
    ("cap", "output_cap_reached"),
    ("other_model", "model_mismatch"),
    ("tool_use", "isolation_tools_exposed"),
    ("redirect", "provider_redirect_refused"),
    ("status:400", "provider_request_rejected"),
    ("status:401", "provider_auth_rejected"),
    ("status:403", "provider_auth_rejected"),
    ("status:404", "provider_not_found"),
    ("status:408", "provider_timeout"),
    ("status:413", "provider_request_too_large"),
    ("status:429", "provider_rate_limited"),
    ("status:500", "provider_server_error"),
    ("status:503", "provider_server_error"),
    ("status:529", "provider_overloaded"),
    ("status:418", "provider_failed"),
    ("flood", "wire_stdout_oversized"),
]


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("behavior,code", CASES)
def test_response_outcomes_map_to_failure_classes(backend, behavior, code):
    with fas.FakeProvider(behavior) as fake:
        cfg = api_config(backend, fake.url(PATHS[backend]))
        backend_obj, _raw, outcome, result = call(cfg, env())
    assert result.code == code and result.response is None, (behavior, result.code)
    assert (backend_obj.unavailable_reason == code) == (code in DISABLING), (behavior, backend_obj.unavailable_reason)
    assert VALUE.encode() not in outcome.stdout and VALUE.encode() not in outcome.stderr
    if code in DISABLING:
        with pytest.raises(RecalithError, match="unavailable"):
            backend_obj.launch(b"{}", timeout_s=5, purpose="update_task")  # a withdrawn route launches nothing more
    if behavior in ("refusal", "cap"):
        assert result.reported is not None and result.reported.output_tokens is not None  # provider usage is charged when reported


@pytest.mark.parametrize("backend", BACKENDS)
def test_missing_usage_charges_engine_estimates(backend):
    with fas.FakeProvider("no_usage") as fake:
        _b, raw, _o, result = call(api_config(backend, fake.url(PATHS[backend])), env())
    assert result.code is None and result.response.usage.input_tokens is None and result.response.usage.output_tokens is None
    assert result.local.input_estimate == len(raw) // 3 and result.response.usage.estimated_output_tokens > 0


@pytest.mark.parametrize("backend", BACKENDS)
def test_reported_output_above_the_cap_withdraws_the_route(backend):
    with fas.FakeProvider("cap_ignored") as fake:
        backend_obj, _raw, _o, result = call(api_config(backend, fake.url(PATHS[backend])), env(), output_cap=32)
    assert result.code == "output_cap_exceeded" and backend_obj.unavailable_reason == "output_cap_exceeded"


def test_expected_resolved_model_is_explicit():
    with fas.FakeProvider("other_model") as fake:
        cfg = api_config("openai_compatible", fake.url("/v1/chat/completions"), expected_resolved_model="explicit-model-substitute")
        _b, _raw, _o, result = call(cfg, env())
    assert result.code is None and result.response.provenance.resolved_model == "explicit-model-substitute"


@pytest.mark.parametrize("backend", BACKENDS)
def test_15kb_episode_is_accepted(backend):
    with fas.FakeProvider("episode") as fake:
        _b, _raw, outcome, result = call(api_config(backend, fake.url(PATHS[backend])), env(), purpose="build_episode")
    assert result.code is None and len(result.response.operations) == 1 and len(outcome.stdout) > 15_000


@pytest.mark.parametrize("behavior", ["thinking", "thinking_summary", "redacted_thinking"])
def test_messages_reply_with_thinking_blocks_yields_only_its_text(behavior):
    """Decision 0027: thinking-by-default models (adaptive thinking cannot be disabled by omission) put a ``thinking``
    or ``redacted_thinking`` block before the text. It is reasoning, not a tool or state: ignored, never parsed as
    the body; the text block alone is the body; its tokens count as output and the cap still covers them."""
    with fas.FakeProvider(behavior) as fake:
        backend_obj, _raw, _o, result = call(api_config("anthropic_messages", fake.url("/v1/messages")), env())
    assert result.code is None and result.response is not None, result.code
    assert result.response.operations == [] and backend_obj.unavailable_reason is None
    assert result.reported is not None and result.reported.output_tokens == 61  # thinking billed as output, charged
    assert fas.THINKING_SUMMARY not in json.dumps(result.response.model_dump(mode="json"))


@pytest.mark.parametrize("behavior,code", [("thinking_only", "envelope_invalid"), ("thinking_two_text", "envelope_invalid"), ("thinking_tool", "isolation_tools_exposed")])
def test_messages_reply_still_needs_exactly_one_text_block_and_no_tool(behavior, code):
    with fas.FakeProvider(behavior) as fake:
        backend_obj, _raw, _o, result = call(api_config("anthropic_messages", fake.url("/v1/messages")), env())
    assert result.code == code and result.response is None, (behavior, result.code)
    assert (backend_obj.unavailable_reason == code) == (code in DISABLING)


def test_messages_thinking_under_the_cap_is_still_the_cap_reason():
    with fas.FakeProvider("ok") as fake:
        _b, _raw, _o, result = call(api_config("anthropic_messages", fake.url("/v1/messages")), env(), output_cap=32)
    assert result.code == "output_cap_reached"


# ---------------------------------------------------------------------------
# Bounds: timeout, kill, caps, and the key never leaving the child


def test_hung_server_is_killed_at_the_timeout():
    with fas.FakeProvider("hang") as fake:
        start = time.monotonic()
        backend_obj, _raw, outcome, result = call(api_config("openai_compatible", fake.url("/v1/chat/completions"), timeout_seconds=2), env(), timeout=2)
        elapsed = time.monotonic() - start
    assert result.code == "provider_timeout" and outcome.timed_out and elapsed < 15
    assert outcome.tree_cleaned is not False and backend_obj.available  # a timeout is charged and retried, not a withdrawal


def test_unreachable_endpoint_is_transient_and_reported():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    backend_obj, _raw, outcome, result = call(api_config("openai_compatible", f"http://127.0.0.1:{port}/v1/chat/completions"), env())
    assert result.code == "endpoint_unreachable" and backend_obj.available
    assert backend_obj.last_failure["code"] == "endpoint_unreachable"
    assert outcome.stderr == b"" and VALUE.encode() not in outcome.stdout


def run_transport(spec: dict, environment: dict, timeout: float = 30) -> tuple[dict, bytes, bytes, float]:
    start = time.monotonic()
    proc = subprocess.run([sys.executable, "-I", str(api.TRANSPORT_PATH)], input=json.dumps(spec).encode(), capture_output=True, env=environment, timeout=timeout)
    elapsed = time.monotonic() - start
    head, _, body = proc.stdout.partition(b"\n")
    return json.loads(head), body, proc.stderr, elapsed


def test_transport_refuses_plain_http_to_a_non_loopback_host():
    cfg = api_config("openai_compatible", "https://api.example.test/v1/chat/completions")
    spec = api.transport_spec(cfg, b"{}", output_cap=16, timeout_s=30)
    spec["url"] = "http://10.255.255.1:9/v1/chat/completions"  # bypassing the validator: the child refuses too
    header, _body, stderr, elapsed = run_transport(spec, env())
    assert header["outcome"] == "transport_error" and header["reason"] == "insecure_endpoint_refused" and elapsed < 10 and stderr == b""


def test_no_tls_verification_bypass_exists():
    for path in (api.TRANSPORT_PATH, Path(api.__file__)):
        source = path.read_text(encoding="utf-8")
        for forbidden in ("CERT_NONE", "check_hostname = False", "check_hostname=False", "_create_unverified_context", "verify=False", "getproxies()", "HTTPRedirectHandler", "build_opener("):
            assert forbidden not in source, (path.name, forbidden)
    spec_keys = set(api.transport_spec(api_config("openai_compatible", "https://api.example.test/v1/chat/completions"), b"{}", output_cap=16, timeout_s=5))
    assert not {k for k in spec_keys if "verify" in k or "insecure" in k or "tls" in k}


def test_https_is_verified_against_system_or_managed_trust(tmp_path):
    made = fas.make_tls(tmp_path / "tls")
    if made is None:
        pytest.skip("openssl CLI unavailable to make a throwaway loopback CA")
    context, ca = made
    with fas.FakeProvider("ok", tls=context) as fake:
        url = fake.url("/v1/chat/completions")
        assert url.startswith("https://")
        # Untrusted: the throwaway CA is not in the system store.
        b1, _raw, _o, untrusted = call(api_config("openai_compatible", url), env())
        assert untrusted.code == "tls_verification_failed" and b1.available
        # The managed CA bundle travels only as a named network key.
        trusted_cfg = api_config("openai_compatible", url, network_env_keys=["SSL_CERT_FILE"])
        _b2, _raw, _o, trusted = call(trusted_cfg, env(SSL_CERT_FILE=str(ca)))
        assert trusted.code is None
        # The same bundle in the parent environment but not named by the route never reaches the child.
        _b3, _raw, _o, unnamed = call(api_config("openai_compatible", url), env(SSL_CERT_FILE=str(ca)))
        assert unnamed.code == "tls_verification_failed"


def test_tls_handshake_against_a_plaintext_server_fails():
    with fas.FakeProvider("ok") as fake:
        url = f"https://127.0.0.1:{fake.port}/v1/chat/completions"
        _b, _raw, _o, result = call(api_config("openai_compatible", url), env())
    # The handshake fails (or the plaintext server drops the connection); a plaintext reply is never accepted.
    assert result.response is None and result.code in {"tls_handshake_failed", "tls_verification_failed", "endpoint_unreachable"}, result.code


def test_proxy_settings_reach_the_child_only_when_named():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead = s.getsockname()[1]
    proxy = f"http://127.0.0.1:{dead}"
    with fas.FakeProvider("ok") as fake:
        url = fake.url("/v1/chat/completions")
        _b, _raw, _o, direct = call(api_config("openai_compatible", url), env(HTTP_PROXY=proxy, http_proxy=proxy))
        assert direct.code is None  # an unnamed proxy is never inherited
        _b, _raw, _o, proxied = call(api_config("openai_compatible", url, network_env_keys=["HTTP_PROXY", "http_proxy"]), env(HTTP_PROXY=proxy, http_proxy=proxy))
        assert proxied.code == "endpoint_unreachable"  # the named proxy is used (and is dead here)


def test_selected_keys_are_found_case_insensitively_on_windows(tmp_path):
    """Regression (CI run 113, Windows): a route naming ``http_proxy`` beside ``HTTP_PROXY`` was reported missing
    because Windows names are stored upper-cased, which withdrew the route as ``selected_auth_missing``."""
    cfg = api_config("openai_compatible", "http://127.0.0.1:9/v1/chat/completions", network_env_keys=["HTTP_PROXY", "http_proxy"], auth_env_keys=["fake_provider_api_key"])
    inherited = {"PATH": "C:\\bin", "SYSTEMROOT": "C:\\Windows", "Fake_Provider_Api_Key": VALUE, "http_proxy": "http://127.0.0.1:1"}
    with isolation.PrivateRoot() as root:
        env_nt, report_nt = isolation.curator_environment(cfg, root, inherited, platform="nt")
        _env, report_posix = isolation.curator_environment(cfg, root, inherited, platform="posix")
    assert report_nt["missing_route_keys"] == [] and env_nt["FAKE_PROVIDER_API_KEY"] == VALUE and env_nt["HTTP_PROXY"] == "http://127.0.0.1:1"
    assert report_posix["missing_route_keys"] == ["HTTP_PROXY", "fake_provider_api_key"]  # POSIX names are case-sensitive


def test_curator_environment_holds_only_constructed_keys():
    with fas.FakeProvider("ok") as fake:
        inherited = env(**DECOYS, CLAUDECODE="1", CLAUDE_CODE_CHILD_SESSION="1", RECALITH_WORKER_INSTALLATION="inst_99999999-9999-4999-8999-999999999999")
        backend_obj, _raw, outcome, result = call(api_config("openai_compatible", fake.url("/v1/chat/completions")), inherited)
    assert result.code is None
    report = backend_obj.last_environment_report
    assert set(report["permitted"]) <= set(process_env.platform_keys()) | {KEY, "HOME", "USERPROFILE", "TMPDIR", "TEMP", "TMP", process_env.CURATOR_MARKER}
    assert not set(DECOYS) & set(report["permitted"]) and "CLAUDECODE" not in report["permitted"]
    assert VALUE not in json.dumps(report)
    observed = outcome.observed_env_keys
    if sys.platform.startswith("linux"):
        assert observed is not None
    if observed is not None:
        assert set(observed) - isolation.LAUNCHER_ADDED_KEYS <= set(report["permitted"])
        assert process_env.CURATOR_MARKER in observed and process_env.WORKER_MARKER not in observed and "CLAUDECODE" not in observed


# ---------------------------------------------------------------------------
# Route status, certification and the no-fallback rule


def test_route_status_reasons_for_api_routes(tmp_path):
    url = "http://127.0.0.1:9/v1/chat/completions"
    good = api_config("openai_compatible", url, certified=True)
    status = base.route_status(good, installation_id=INSTALLATION, inherited=env())
    assert status.certified and status.reasons == [] and status.observed_version is None  # the gate's positive control
    report = status.report()
    assert report["backend"] == "openai_compatible" and VALUE not in json.dumps(report)
    cases = {
        "route_uncertified": api_config("openai_compatible", url),
        "request_capture_only": api_config("openai_compatible", url, certification={"certified": False, "mode": "request_capture"}),
        "certification_failed:output_cap_unenforced": api_config("openai_compatible", url, certification={"certified": False, "mode": "live", "failed_checks": ["output_cap_unenforced"]}),
        "foreign_provider_config": api_config("openai_compatible", url, certified=True, installation_id=new_id("inst")),
        "adapter_changed": api_config("openai_compatible", url, certified=True, cert={"executable_sha256": "0" * 64}),
        "auth_route_changed": api_config("openai_compatible", url, certified=True, cert={"auth_env_keys": ["OTHER_PROVIDER_KEY"]}),
        "invocation_changed": ProviderConfig.model_validate({**good.model_dump(mode="json"), "endpoint": endpoint("openai_compatible", "http://127.0.0.1:10/v1/chat/completions")}),
    }
    for reason, cfg in cases.items():
        st = base.route_status(cfg, installation_id=INSTALLATION, inherited=env())
        assert not st.certified and reason in st.reasons, (reason, st.reasons)
        assert not {"executable_missing", "host_version_unobserved", "host_version_changed"} & set(st.reasons)
    missing = base.route_status(good, installation_id=INSTALLATION, inherited={"PATH": os.environ.get("PATH", "")})
    assert missing.reasons == ["selected_auth_missing"]
    assert base.route_status(good, installation_id=INSTALLATION, inherited=env()).report()["recertification_required"] is False
    assert base.route_status(cases["adapter_changed"], installation_id=INSTALLATION, inherited=env()).report()["recertification_required"] is True


def init_project(tmp_path: Path, name: str = "project"):
    from recalith.contracts.common import Actor
    from recalith.contracts.config import ProjectConfig
    from recalith.core import identity

    root = tmp_path / name
    root.mkdir()
    identity.initialize_installation(root, ProjectConfig.defaults_for(new_id("proj")))
    return identity.resolve_installation(root, actor=Actor(kind="controller", id="t", channel="worker"))


def test_copied_route_is_foreign_and_never_launched(tmp_path):
    first = init_project(tmp_path, "first")
    second = init_project(tmp_path, "second")
    cfg = api_config("openai_compatible", "http://127.0.0.1:9/v1/chat/completions", certified=True, installation_id=first.installation_id)
    base.save_provider_config(first.root, cfg)
    (Path(second.root) / ".recalith" / "provider.json").write_bytes(base.provider_path(first.root).read_bytes())
    supervisor = base.ProviderSupervisor(second, inherited=env())
    assert supervisor.backend is None and "foreign_provider_config" in supervisor.report()["reasons"]


def test_no_fallback_from_an_unavailable_api_route(tmp_path):
    """An uncertified API route is unavailable even with a Claude CLI on PATH and other keys present."""
    ctx = init_project(tmp_path)
    cfg = api_config("anthropic_messages", "https://api.example.test/v1/messages", installation_id=ctx.installation_id)
    base.save_provider_config(ctx.root, cfg)
    from recalith.controller import worker

    provider, runtime = worker.configured_provider(ctx, env(**DECOYS))
    assert runtime is None and provider.backend is None
    report = provider.report()
    assert report["backend"] == "anthropic_messages" and report["state"] == "unavailable" and "route_uncertified" in report["reasons"]


def test_request_capture_check_proves_the_exact_request():
    cfg = api_config("openai_compatible", "https://api.example.test/v1/chat/completions?api-version=2026-01-01")
    check = isolation.isolation_check(cfg, inherited=env(**DECOYS, CLAUDECODE="1"))
    assert check["verdict"] == "pass", check["failures"]
    assert check["certifies"] is False and check["mode"] == "request_capture"
    capture = check["request_capture"]
    assert capture["path"] == "/v1/chat/completions?api-version=2026-01-01" and capture["body_identical"] and capture["model_visible_tools"] == []
    assert check["environment"]["curator_marker_names_installation"] and check["environment"]["host_markers_present"] == []
    assert VALUE not in json.dumps(check) and not [v for v in DECOYS.values() if v in json.dumps(check)]


@pytest.mark.parametrize("mutation,failure", [("tools", "request_offers_tools"), ("header", "credential_outside_selected_header"), ("model", "request_model_mismatch")])
def test_request_capture_check_catches_a_changed_request(monkeypatch, mutation, failure):
    cfg = api_config("anthropic_messages", "https://api.example.test/v1/messages")
    real_build, real_spec = api.build_body, api.transport_spec
    if mutation == "tools":
        monkeypatch.setattr(api, "build_body", lambda c, raw, output_cap: real_build(c, raw, output_cap=output_cap)[:-1] + b',"tools":[]}')
    elif mutation == "header":
        monkeypatch.setattr(api, "transport_spec", lambda *a, **k: {**real_spec(*a, **k), "headers": {**real_spec(*a, **k)["headers"], "x-extra": isolation.PLACEHOLDER_KEY}})
    else:
        monkeypatch.setattr(api, "build_body", lambda c, raw, output_cap: real_build(c, raw, output_cap=output_cap).replace(b'"explicit-model"', b'"other-model"'))
    check = isolation.isolation_check(cfg, inherited=env())
    assert check["verdict"] == "fail" and failure in check["failures"], check["failures"]


def test_supervisor_recheck_gates_an_api_route(tmp_path, monkeypatch):
    ctx = init_project(tmp_path)
    cfg = api_config("openai_compatible", "http://127.0.0.1:9/v1/chat/completions", certified=True, installation_id=ctx.installation_id)
    base.save_provider_config(ctx.root, cfg)
    supervisor = base.ProviderSupervisor(ctx, inherited=env(**DECOYS, CLAUDECODE="1"))
    assert supervisor.status.certified and supervisor.backend is not None and not supervisor.available
    supervisor.start()
    assert supervisor.ready.wait(60)
    assert supervisor.available and supervisor.report()["state"] == "certified", supervisor.check
    record = base.read_check(ctx.root)
    assert record["isolation_check"]["verdict"] == "pass" and VALUE not in json.dumps(record)
    # The same route whose effective request changed is withdrawn by the recheck.
    real_build = api.build_body
    monkeypatch.setattr(api, "build_body", lambda c, raw, output_cap: real_build(c, raw, output_cap=output_cap)[:-1] + b',"tool_choice":"auto"}')
    changed = base.ProviderSupervisor(ctx, inherited=env())
    changed.start()
    assert changed.ready.wait(60)
    assert not changed.available and changed.backend.unavailable_reason == "isolation_recheck_failed"


def test_complete_runs_one_certified_call(tmp_path):
    with fas.FakeProvider("ok") as fake:
        cfg = api_config("anthropic_messages", fake.url("/v1/messages"), certified=True)
        response = base.complete(request(), cfg, inherited=env())
        assert response.provenance.resolved_model == "explicit-model"
        uncertified = api_config("anthropic_messages", fake.url("/v1/messages"))
        with pytest.raises(Exception, match="route_uncertified"):
            base.complete(request(), uncertified, inherited=env())
        fake.behavior = "status:429"
        with pytest.raises(ProviderCallFailed) as info:
            base.complete(request(), cfg, inherited=env())
        assert info.value.code == "provider_rate_limited"
