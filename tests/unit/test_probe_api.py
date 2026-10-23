"""The live provider probe's parent environments (tools/probe_api.py).

The host-marked parent plants decoy credentials to prove that only the selected
key reaches the curator. A decoy under the selected key's own name replaced the
operator's key there: the first live run of an Anthropic Messages route
(``ANTHROPIC_API_KEY``) authenticated from the clean parent and was rejected
from the host-marked one (``provider_auth_rejected``), so the route stayed
uncertified. Request capture never showed it: there every selected key is
replaced by the placeholder anyway.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tests" / "fixtures" / "providers"))

import fake_api_server as fas  # noqa: E402
import probe_api  # noqa: E402

OPERATOR_VALUE = "operator-" + "probe-" + "value-0001"  # built by concatenation: never a credential-shaped literal
INSTALLATION = "inst_11111111-1111-4111-8111-111111111111"


def probe_config(url: str) -> dict:
    return {
        "provider_id": "anthropic_api", "backend": "anthropic_messages", "model": "explicit-model", "expected_resolved_model": None,
        "endpoint": {"url": url, "dialect": "messages", "auth_header": "x-api-key", "output_cap_field": "max_tokens", "json_mode": "none", "api_version": "2023-06-01"},
        "auth_route": {"kind": "env_api_key", "billing": "api", "env_keys": ["ANTHROPIC_API_KEY"]},
        "network_env_keys": [], "nonsecret_env": {}, "limits": {"timeout_seconds": 30},
    }


def test_host_marked_parent_keeps_the_selected_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", OPERATOR_VALUE)
    parents = probe_api.parents(selected=["ANTHROPIC_API_KEY"])
    marked = parents["host_marked"]
    assert marked["ANTHROPIC_API_KEY"] == OPERATOR_VALUE and parents["clean"]["ANTHROPIC_API_KEY"] == OPERATOR_VALUE
    for name, value in probe_api.DECOYS.items():
        if name != "ANTHROPIC_API_KEY":
            assert marked[name] == value, name  # every other credential is still a decoy
    assert marked["CLAUDECODE"] == "1" and "CLAUDECODE" not in parents["clean"]


def test_an_unset_selected_key_stays_unset(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    marked = probe_api.parents(selected=["OPENAI_API_KEY"])["host_marked"]
    assert "OPENAI_API_KEY" not in marked  # a decoy never stands in for the selected key, set or not
    assert marked["ANTHROPIC_API_KEY"] == probe_api.DECOYS["ANTHROPIC_API_KEY"]


def test_live_run_sends_the_operator_key_from_both_parents(monkeypatch):
    """The failing live run against the loopback fake provider: both schema runs and the cap run carry the operator's key."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", OPERATOR_VALUE)
    with fas.FakeProvider("ok") as fake:
        cfg = probe_config(fake.url("/v1/messages"))
        out = probe_api.live(probe_api.provider_config(cfg, installation_id=INSTALLATION), cfg)
        sent = [dict((k.lower(), v) for k, v in r["headers"]).get("x-api-key") for r in fake.requests]
    assert out["schema_runs"]["clean"]["code"] is None and out["schema_runs"]["host_marked"]["code"] is None, out["schema_runs"]
    assert len(sent) == 3 and set(sent) == {OPERATOR_VALUE}, sent
    assert out["cap_run"]["code"] == "output_cap_reached"
