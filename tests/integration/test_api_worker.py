"""Decision 0023: the worker's model lane through a direct-API backend (A21, A29, A47, A50, A67).

The project is the Task 7 provider scenario (real typed reduction schedules
narrative jobs; a seeded candidate schedules a review). Its model jobs run
through the production preparer, budget reservation, the stdlib HTTP
transport child and the production response parser against a loopback fake
Chat Completions provider owned by the test. The "certified" route files are
controlled unit states for the gate (never certification evidence), and no
call leaves the machine.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import operation_scenarios as osc
import provider_scenarios as ps
import worker_scenarios as ws
from recalith.contracts.common import digest_of, new_id
from recalith.contracts.config import ProviderConfig, provider_output_cap
from recalith.controller import worker
from recalith.fast import process_env
from recalith.operations import health as operations_health
from recalith.providers import api, base
from recalith.storage import db

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures" / "providers"))
import fake_api_server as fas  # noqa: E402

KEY = "FAKE_PROVIDER_API_KEY"
VALUE = "fake-" + "provider-" + "value-0002"  # built by concatenation: never a credential-shaped literal


def platform_env(**extra: str) -> dict[str, str]:
    keep = ("PATH", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP", "TMPDIR", "LANG")
    return {**{k: os.environ[k] for k in keep if k in os.environ}, **extra}


def drive(root: Path, runtime_for) -> worker.Worker:
    spec = ps.scenario(root)
    clock = ws.FakeClock(spec["clock"])
    ctx = osc.context(root)
    w = worker.Worker(ctx, clock=clock, model=runtime_for(ctx, spec, clock), owner=f"test:{new_id('act')[4:12]}")
    lock = process_env.InstallationLock(root)
    assert lock.try_acquire()
    try:
        w.startup()
        ws.drain(w)
    finally:
        w.close()
        lock.release()
    return w


def usage_rows(root: Path) -> list[dict]:
    with db.open_store(osc.context(root), readonly=True) as store, store.read() as view:
        return [dict(json.loads(body), _provider=p, _model=m) for p, m, body in view.execute("SELECT provider_id, model, body FROM provider_usage ORDER BY rowid").fetchall()]


def certified_route(ctx, url: str) -> ProviderConfig:
    data = {
        "provider_id": "fake_api", "installation_id": ctx.installation_id, "backend": "openai_compatible", "executable": None, "configured_model": "fake-model",
        "auth_route": "env_api_key", "auth_env_keys": [KEY], "invocation_args": [], "certification": {"certified": False},
        "endpoint": {"url": url, "dialect": "chat_completions", "auth_header": "authorization_bearer", "output_cap_field": "max_completion_tokens", "json_mode": "json_object", "api_version": None},
    }
    cfg = ProviderConfig.model_validate(data)
    cert = {
        "certified": True, "certified_at": "2026-10-22T00:00:00.000000Z", "report_digest": digest_of(["unit"]), "executable_sha256": api.adapter_digest(), "mode": "live",
        "operator_attestation": "not_applicable_local", "auth_env_keys": [KEY], "invocation_digest": base.invocation_digest(cfg), "resolved_model": "fake-model",
    }
    return ProviderConfig.model_validate({**data, "certification": cert})


def test_api_lane_applies_what_the_process_lane_applies(tmp_path):
    """Admission is backend-agnostic: the API lane ends in exactly the reference state of the JSON-process lane."""
    reference = ps.crash_project(tmp_path, "reference")
    drive(reference, ps.runtime)
    with fas.FakeProvider("narrative") as fake:
        root = ps.crash_project(tmp_path, "api", api_url=fake.url("/v1/chat/completions"))
        drive(root, ps.runtime)
        calls = fake.snapshot()
    assert osc.normalized(root) == osc.normalized(reference)
    assert ps.extra_state(root) == ps.extra_state(reference)
    assert calls and all(json.loads(c["body"])["model"] == "fake-model" for c in calls)
    rows = usage_rows(root)
    assert len(rows) == len(calls) and {r["state"] for r in rows} == {"charged"}
    assert {r["_provider"] for r in rows} == {"fake_api"} and {r["_model"] for r in rows} == {"fake-model"}
    # Provider-reported usage is recorded beside the engine's own estimate (prompt 45 / completion 7 from the fake).
    assert all(r["reported_usage"]["input_tokens"] == 45 and r["reported_usage"]["output_tokens"] == 7 for r in rows)
    assert all(r["local_estimated_usage"]["input_estimate"] > 0 for r in rows)


def test_certified_api_route_reserves_charges_failures_and_backs_off(tmp_path):
    """Through ``configured_provider``: the recheck gates the lane; a rate-limited attempt is charged and backed off;
    the retry succeeds and charges reported usage; the key never appears in any record."""
    with fas.FakeProvider("status:429") as fake:
        root = ps.crash_project(tmp_path, "certified")
        ctx = osc.context(root)
        base.save_provider_config(root, certified_route(ctx, fake.url("/v1/chat/completions")))
        inherited = platform_env(**{KEY: VALUE}, CLAUDECODE="1", OPENAI_API_KEY="dec" + "oy-openai")
        provider, runtime = worker.configured_provider(ctx, inherited)
        assert runtime is not None and provider.status.certified
        provider.start()
        assert provider.ready.wait(60) and provider.available, provider.check
        spec = ps.scenario(root)
        clock = ws.FakeClock(spec["clock"])
        from recalith.controller import requests

        runtime = worker.ModelRuntime(backend=provider.backend, prepare=requests.runtime_preparer(ctx, now=clock.now))
        w = worker.Worker(ctx, clock=clock, model=runtime, provider=provider, owner="test:certified")
        lock = process_env.InstallationLock(root)
        assert lock.try_acquire()
        try:
            w.startup()
            for _ in range(5):
                w.poll_once()
                w.lane.step()
            failed = usage_rows(root)
            assert failed and {r["state"] for r in failed} == {"charged"}
            assert all(r["reported_usage"] is None for r in failed)  # no provider usage on a 429: the reservation stays charged
            report = provider.report()
            assert report["state"] == "certified" and report["last_call_failure"]["code"] == "provider_rate_limited"
            fake.behavior = "narrative"
            clock.advance(4000)  # past every backoff step
            ws.drain(w)
            status = w.status()
        finally:
            w.close()
            lock.release()
        sent = fake.snapshot()
    rows = usage_rows(root)
    assert len(rows) == len(sent) > len(failed)
    # Decision 0029: the hard cap sent is what was reserved, the allowance plus the reasoning headroom.
    assert [json.loads(c["body"])["max_completion_tokens"] for c in sent] == [r["estimated_output_limit"] for r in rows]
    assert all(r["estimated_output_limit"] == provider_output_cap(r["purpose"]) and r["reasoning_headroom"] == 6000 for r in rows)
    assert any(r["reported_usage"] and r["reported_usage"]["output_tokens"] == 7 for r in rows)
    assert all(dict(c["headers"]).get("Authorization") == f"Bearer {VALUE}" for c in sent)
    assert provider.report()["last_call_failure"] is None
    for path in [*Path(root, ".recalith").rglob("*.json"), Path(root, ".recalith", db.STATE_DB)]:
        assert VALUE.encode() not in path.read_bytes(), path
    assert VALUE not in json.dumps(status)


def test_status_names_api_route_reasons_without_keys(tmp_path):
    with fas.FakeProvider("other_model") as fake:
        root = ps.crash_project(tmp_path, "status")
        ctx = osc.context(root)
        route = certified_route(ctx, fake.url("/v1/chat/completions"))
        uncertified = ProviderConfig.model_validate({**route.model_dump(mode="json"), "certification": {"certified": False, "mode": "live", "failed_checks": ["output_cap_unenforced"]}})
        base.save_provider_config(root, uncertified)
        report = operations_health.health(ctx, inherited=platform_env(**{KEY: VALUE}))
        inference = report.capabilities["inference"]
        assert inference.state == "unavailable"
        assert {"route_uncertified", "certification_failed_output_cap_unenforced"} <= set(inference.reason_codes), inference.reason_codes
        assert inference.coverage["backend"] == "openai_compatible" and VALUE not in report.model_dump_json()
        # A certified route whose provider reports another model is withdrawn at the call and says why.
        base.save_provider_config(root, route)
        provider, runtime = worker.configured_provider(ctx, platform_env(**{KEY: VALUE}))
        provider.start()
        assert provider.ready.wait(60) and provider.available
        from recalith.controller import requests

        spec = ps.scenario(root)
        clock = ws.FakeClock(spec["clock"])
        w = worker.Worker(ctx, clock=clock, model=worker.ModelRuntime(backend=provider.backend, prepare=requests.runtime_preparer(ctx, now=clock.now)), provider=provider, owner="test:status")
        lock = process_env.InstallationLock(root)
        assert lock.try_acquire()
        try:
            w.startup()
            w.poll_once()
            w.lane.step()
            status = w.status()
        finally:
            w.close()
            lock.release()
    assert not provider.available and "model_mismatch" in provider.report()["reasons"]
    assert status["model_lane"] == "provider_unavailable" and "model_mismatch" in status["provider"]["reasons"]
    assert VALUE not in json.dumps(status)


def test_health_degrades_on_the_last_call_failure_of_a_certified_api_route(tmp_path):
    """``recalith status`` names a transient route failure (an unreachable endpoint) as degraded inference, by code only."""
    import socket

    import health_scenarios as hs

    p = hs.project(tmp_path, "unreachable")
    p.send_all(ps.green_reruns())
    p.drain()
    hs.integrate(p, autostart=False)
    hs.certify_host(p)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed = s.getsockname()[1]
    ctx = p.ctx
    base.save_provider_config(p.root, certified_route(ctx, f"http://127.0.0.1:{closed}/v1/chat/completions"))
    inherited = platform_env(**{KEY: VALUE})
    provider, runtime = worker.configured_provider(ctx, inherited)
    provider.start()
    assert provider.ready.wait(60) and provider.available
    w = worker.Worker(ctx, model=runtime, provider=provider, owner="test:unreachable")
    lock = process_env.InstallationLock(p.root)
    assert lock.try_acquire()
    try:
        for _ in range(3):
            w.poll_once()
            if w.lane.step():
                break
        assert provider.backend.last_failure["code"] == "endpoint_unreachable" and provider.available
        w.write_status()
        rep = hs.report(p, inherited)
    finally:
        w.close()
        lock.release()
    inference = rep.capabilities["inference"]
    assert inference.state == "degraded" and "endpoint_unreachable" in inference.reason_codes, inference
    assert inference.coverage["source"] == "worker" and inference.coverage["backend"] == "openai_compatible"
    assert rep.autonomous_ready is False and VALUE not in rep.model_dump_json()


def test_hook_started_worker_carries_the_routes_network_keys(tmp_path):
    """The registered hook start forwards the route's auth and network (proxy/TLS) key names, never values."""
    from recalith.integrations import claude

    root = ps.crash_project(tmp_path, "keys")
    ctx = osc.context(root)
    route = certified_route(ctx, "http://127.0.0.1:9/v1/chat/completions")
    endpoint = {**route.endpoint.model_dump(mode="json"), "url": "https://api.example.test/v1/chat/completions"}
    data = {**route.model_dump(mode="json"), "endpoint": endpoint, "network_env_keys": ["HTTPS_PROXY", "SSL_CERT_FILE"], "certification": {"certified": False}}
    base.save_provider_config(root, ProviderConfig.model_validate(data))
    assert claude._route_keys(root) == [KEY, "HTTPS_PROXY", "SSL_CERT_FILE"]
