"""Decision 0023: the operator probe for direct-API backends (``anthropic_messages``, ``openai_compatible``).

Called by ``tools/probe_provider.py`` when the configured backend is an API
backend; it is not run directly. Unlike the Claude CLI probe it uses the
engine's own adapter (``recalith.providers``): the shipped transport *is* the
certified program, so the probe exercises exactly what the worker will run.

* ``request_capture``: the transport is pointed at a loopback capture endpoint
  (the configured path and query, a placeholder under the selected key name)
  from a clean and a host-marked parent with decoy credentials. The engine
  verifies the exact request (``providers.isolation.api_isolation_check``) and
  the bounds: a hung server killed at the timeout, a flood past the wire cap,
  a body past the purpose cap, a valid 15 KB episode body, malformed JSON.
  No account is used; this never certifies.
* ``live``: the operator's own route from an ordinary terminal, from a clean
  and a host-marked parent: the call authenticates, the provider reports the
  expected model, a schema-valid no-op body comes back within the timeout, a
  deliberately small output cap is enforced, the endpoint is the configured
  origin (verified TLS unless loopback; no redirect), and usage reporting is
  recorded. Only a complete live pass with the operator's attestation
  (``checked_eligible``, or ``not_applicable_local`` for a loopback server)
  certifies.

Values of environment variables never enter the report; the selected key is
read by the transport child by name.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

import probe_common as pc

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

SECTION = "provider_isolation"
CAP_PROBE_TOKENS = 32
DECOYS = {"ANTHROPIC_API_KEY": "recalith-probe-decoy-anthropic", "OPENAI_API_KEY": "recalith-probe-decoy-openai", "ANTHROPIC_AUTH_TOKEN": "recalith-probe-decoy-auth", "GITHUB_TOKEN": "recalith-probe-decoy-github", "AWS_PROFILE": "recalith-probe-decoy"}
SCHEMA_INSTRUCTION = 'Reply with exactly this JSON object and nothing else: {"operations": [], "no_op_reason": "probe"}'
CAP_INSTRUCTION = "Reply with one JSON object whose no_op_reason field is a 600-word essay about rivers. Do not stop early."
CHECK_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def provider_config(cfg: Mapping[str, Any], *, installation_id: str, certification: Mapping[str, Any] | None = None) -> Any:
    """The ``ProviderConfig`` a probe configuration describes (raises ``ValueError`` when it is invalid)."""
    from recalith.contracts.config import ProviderConfig

    auth = cfg["auth_route"]
    kind = auth["kind"]
    data = {
        "provider_id": cfg["provider_id"], "installation_id": installation_id, "backend": cfg["backend"], "executable": None,
        "configured_model": cfg["model"], "expected_resolved_model": cfg.get("expected_resolved_model"),
        "auth_route": "none" if kind in ("none", "not_configured") else "env_api_key", "auth_env_keys": list(auth["env_keys"]),
        "network_env_keys": list(cfg["network_env_keys"]), "nonsecret_env": dict(cfg["nonsecret_env"]), "invocation_args": [],
        "endpoint": cfg["endpoint"], "timeout_seconds": cfg["limits"]["timeout_seconds"], "certification": dict(certification or {"certified": False}),
    }
    return ProviderConfig.model_validate(data)


def parents(*, selected: Iterable[str]) -> dict[str, dict[str, str]]:
    """The clean and the host-marked parent. Decoys stand in for every credential except the route's own (``selected``):
    a decoy under a selected name would replace the operator's key, and a live run would test the decoy, not the route."""
    clean = {k: v for k, v in os.environ.items() if k not in pc.DEFAULT_HOST_MARKERS and not k.startswith("RECALITH_")}
    keep = set(selected)
    decoys = {k: v for k, v in DECOYS.items() if k not in keep}
    marked = {**os.environ, **decoys, "CLAUDECODE": "1", "CLAUDE_CODE_CHILD_SESSION": "1", pc.WORKER_MARKER: "inst_99999999-9999-4999-8999-999999999999"}
    return {"clean": clean, "host_marked": marked}


def probe_request(instruction: str) -> bytes:
    return json.dumps({"request_schema": 1, "purpose": "probe", "instruction_text": instruction, "output_schema": {"type": "object", "required": ["operations"]}}, separators=(",", ":")).encode("utf-8")


def _verdict(failures: list[str]) -> str:
    return "fail" if failures else "pass"


# --------------------------------------------------------------------------
# Request capture: the exact request, the environment and the bounds


def request_capture(config: Any, cfg: Mapping[str, Any]) -> dict[str, Any]:
    from recalith.contracts.config import body_cap_for
    from recalith.providers import base, isolation

    runs = {name: isolation.api_isolation_check(config, inherited=env, timeout_s=cfg["limits"]["timeout_seconds"]) for name, env in parents(selected=config.auth_env_keys).items()}
    bounds: dict[str, Any] = {}
    timeout = cfg["limits"]["bounds_timeout_seconds"]
    for case, purpose, expected in (("hang", "update_task", "provider_timeout"), ("flood", "update_task", "wire_stdout_oversized"), ("oversize", "update_task", "response_body_oversized"), ("large", "build_episode", None), ("malformed", "update_task", "envelope_invalid")):
        backend, outcome, _records, _parsed = isolation.capture_launch(config, inherited=parents(selected=config.auth_env_keys)["clean"], behavior=case, timeout_s=timeout if case == "hang" else cfg["limits"]["timeout_seconds"])
        result = base.evaluate_outcome(outcome, backend, purpose=purpose, body_cap=body_cap_for(purpose), estimate=1)
        ok = result.code == expected and outcome.tree_cleaned is not False
        bounds[case] = {"pass": ok, "code": result.code, "expected": expected, "duration_ms": outcome.duration_ms, "tree_cleaned": outcome.tree_cleaned}
    return {"method": "The shipped transport sent to a loopback capture endpoint with a placeholder under the selected key name; the engine verified the bytes received. No account is used; this cannot certify.", "isolated_runs": runs, "bounds": bounds}


# --------------------------------------------------------------------------
# Live: the operator's own route


def _transport_facts(stdout: bytes) -> dict[str, Any]:
    from recalith.providers import api

    try:
        header, _body = api.read_transport(stdout)
    except (ValueError, UnicodeDecodeError):
        return {}
    return {"status": header.get("status"), "transport_reason": header.get("reason"), "tls": header.get("tls")}


def live_call(config: Any, inherited: Mapping[str, str], *, instruction: str, output_cap: int | None, timeout: float) -> dict[str, Any]:
    from recalith.contracts.config import body_cap_for, estimate_tokens
    from recalith.providers import base, isolation

    backend = base.ProviderBackend(config, inherited=inherited, mode="live")
    raw = probe_request(instruction)
    outcome = backend.launch(raw, timeout_s=timeout, purpose="update_task", output_cap=output_cap)
    result = base.evaluate_outcome(outcome, backend, purpose="update_task", body_cap=body_cap_for("update_task"), estimate=estimate_tokens(len(raw)))
    report = backend.last_environment_report or {}
    constructed = {k: "" for k in report.get("permitted", [])}
    constructed[isolation.process_env.CURATOR_MARKER] = backend.last_curator_marker or ""
    env_failures, env_detail = isolation.environment_failures(outcome.observed_env_keys, constructed, report, installation_id=config.installation_id)
    usage = result.reported
    return {
        "code": result.code,
        "operations": None if result.response is None else len(result.response.operations),
        "resolved_model": None if result.response is None else result.response.provenance.resolved_model,
        "usage": None if usage is None else {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens, "provider_request_id_present": usage.provider_request_id is not None},
        "duration_ms": outcome.duration_ms, "timed_out": outcome.timed_out, "tree_cleaned": outcome.tree_cleaned,
        "environment_failures": env_failures, "environment": env_detail, **_transport_facts(outcome.stdout),
    }


AUTH_CODES = {"provider_auth_rejected", "selected_auth_missing"}
MODEL_CODES = {"model_mismatch"}
ENDPOINT_CODES = {"provider_redirect_refused", "tls_verification_failed", "tls_handshake_failed", "endpoint_unreachable", "provider_not_found", "insecure_endpoint_refused"}
LAUNCH_CODES = {"provider_timeout", "provider_failed", "wire_stdout_oversized", "provider_server_error", "provider_overloaded", "provider_rate_limited", "provider_request_rejected", "provider_request_too_large", "provider_response_incomplete"}


def live(config: Any, cfg: Mapping[str, Any]) -> dict[str, Any]:
    timeout = cfg["limits"]["timeout_seconds"]
    runs = {name: live_call(config, env, instruction=SCHEMA_INSTRUCTION, output_cap=None, timeout=timeout) for name, env in parents(selected=config.auth_env_keys).items()}
    cap = live_call(config, parents(selected=config.auth_env_keys)["clean"], instruction=CAP_INSTRUCTION, output_cap=CAP_PROBE_TOKENS, timeout=timeout)
    return {"status": "run", "schema_runs": runs, "cap_run": cap, "output_cap_tokens": CAP_PROBE_TOKENS}


def cap_failures(cap: Mapping[str, Any]) -> list[str]:
    code = cap["code"]
    out_tokens = (cap.get("usage") or {}).get("output_tokens")
    if code == "output_cap_reached":
        return [] if out_tokens is None or out_tokens <= CAP_PROBE_TOKENS else ["output_cap_unenforced"]
    if code == "output_cap_exceeded":
        return ["output_cap_unenforced"]
    if code is None:
        return ["output_cap_unenforced"] if out_tokens is not None and out_tokens > CAP_PROBE_TOKENS else ["output_cap_unobserved"]
    return [code]


# --------------------------------------------------------------------------
# Dimensions and the verdict


ENV_FAILURES = {"host_marker_present", "curator_marker_missing", "worker_marker_present", "unpermitted_inherited_key_present", "observed_env_differs_from_constructed"}


def dimensions(config: Any, cfg: Mapping[str, Any], capture: dict[str, Any] | None, live_block: dict[str, Any] | None) -> dict[str, Any]:
    from recalith.contracts.config import is_loopback_url

    dims: dict[str, Any] = {}
    if capture:
        runs = capture["isolated_runs"]
        shape = sorted({x for r in runs.values() for x in r["failures"] if x not in ENV_FAILURES})
        envf = sorted({x for r in runs.values() for x in r["failures"] if x in ENV_FAILURES})
        if set(runs["clean"]["environment"]["constructed_keys"]) != set(runs["host_marked"]["environment"]["constructed_keys"]):
            envf.append("clean_vs_marked_key_sets_differ")
        dims["request_shape"] = {"verdict": _verdict(shape), "failures": shape}
        dims["environment_isolation"] = {"verdict": _verdict(envf), "failures": envf, "observed_through": "request_capture"}
        bf = sorted(k for k, v in capture["bounds"].items() if not v["pass"])
        dims["bounds_and_cancellation"] = {"verdict": _verdict(bf), "failures": bf}
    else:
        for key in ("request_shape", "environment_isolation", "bounds_and_cancellation"):
            dims[key] = {"verdict": "not_run", "failures": [], "reason": "request_capture not selected"}
    if live_block and live_block.get("status") == "run":
        calls = list(live_block["schema_runs"].values())
        codes = {c["code"] for c in calls if c["code"] is not None}
        expected = config.expected_resolved_model or config.configured_model
        auth = sorted(codes & AUTH_CODES)
        model = sorted(codes & MODEL_CODES) or (["model_mismatch"] if any(c["code"] is None and c["resolved_model"] != expected for c in calls) else [])
        schema = sorted(codes - AUTH_CODES - MODEL_CODES - ENDPOINT_CODES - LAUNCH_CODES) + (["schema_output_invalid"] if any(c["code"] is None and c["operations"] != 0 for c in calls) else [])
        endpoint = sorted(codes & ENDPOINT_CODES)
        if not is_loopback_url(config.endpoint.url) and any(c["code"] is None and not (c.get("tls") or {}).get("verified") for c in calls):
            endpoint.append("tls_unverified")
        launch = sorted(codes & LAUNCH_CODES) + sorted({x for c in calls for x in c["environment_failures"]})
        dims["auth_route"] = {"verdict": _verdict(auth), "failures": auth}
        dims["model_identity"] = {"verdict": _verdict(model), "failures": model, "expected": expected, "reported": sorted({str(c["resolved_model"]) for c in calls})}
        dims["schema_output"] = {"verdict": _verdict(schema), "failures": schema, "location": "the reply's single text block / choice message content, decoded and validated locally"}
        dims["endpoint_identity"] = {"verdict": _verdict(endpoint), "failures": endpoint, "origin": _origin(config.endpoint.url), "tls": [c.get("tls") for c in calls]}
        dims["live_launch"] = {"verdict": _verdict(launch), "failures": launch}
        cf = cap_failures(live_block["cap_run"])
        dims["output_cap"] = {"verdict": _verdict(cf), "failures": cf, "requested_tokens": CAP_PROBE_TOKENS, "observed": {k: live_block["cap_run"].get(k) for k in ("code", "usage")}}
        reported = all(c["usage"] and c["usage"]["input_tokens"] is not None and c["usage"]["output_tokens"] is not None for c in calls if c["code"] is None)
        dims["usage"] = {"verdict": "informational", "reported": bool(reported and any(c["code"] is None for c in calls)), "note": "unknown usage is charged at the engine's estimates"}
    else:
        reason = (live_block or {}).get("reason", "live mode not selected in config")
        for key in ("auth_route", "model_identity", "schema_output", "endpoint_identity", "live_launch", "output_cap"):
            dims[key] = {"verdict": "not_run", "failures": [], "reason": reason}
        dims["usage"] = {"verdict": "informational", "reported": None}
    att = cfg["operator_attestation"]["background_use"]
    if att == "checked_eligible" or (att == "not_applicable_local" and is_loopback_url(config.endpoint.url)):
        dims["operator_attestation"] = {"verdict": "pass", "failures": []}
    else:
        dims["operator_attestation"] = {"verdict": "fail" if att in ("checked_ineligible", "not_applicable_local") else "not_run", "failures": [f"background_use_{att}"]}
    return dims


def _origin(url: str) -> str:
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def route_record(cfg: Mapping[str, Any], section: Mapping[str, Any], *, installation_id: str) -> Any:
    """The installation's ``ProviderConfig``; ``certified`` only after a complete live pass."""
    from recalith.providers import api, base

    model = provider_config(cfg, installation_id=installation_id)
    certified = bool(section.get("certified")) and (section.get("live") or {}).get("status") == "run"
    failed = [] if certified else sorted({x for x in section.get("failed_checks", []) if CHECK_NAME.match(x)})[:32]
    cert = {
        "certified": certified,
        "certified_at": section.get("tested_at") if certified else None,
        "report_digest": pc.sha256_bytes(pc.canonical_json(section)),
        "executable_sha256": api.adapter_digest(),
        "mode": "live" if (section.get("live") or {}).get("status") == "run" else "request_capture",
        "operator_attestation": cfg["operator_attestation"]["background_use"],
        "auth_env_keys": list(cfg["auth_route"]["env_keys"]),
        "invocation_digest": base.invocation_digest(model),
        "resolved_model": section.get("resolved_model") if certified else None,
        "failed_checks": failed,
    }
    return provider_config(cfg, installation_id=installation_id, certification=cert)


def write_route(project_root: Path, cfg: Mapping[str, Any], section: Mapping[str, Any]) -> Path:
    if any(marker in os.environ for marker in cfg["host_markers"]):
        raise PermissionError("writing a project's provider route is an operator action; run it from an ordinary terminal outside any agent session")
    import tomllib

    from recalith.providers.base import save_provider_config

    installation_id = tomllib.loads((project_root / ".recalith" / "local.toml").read_text(encoding="utf-8"))["installation_id"]
    return save_provider_config(project_root, route_record(cfg, section, installation_id=installation_id))


def run(cfg: dict[str, Any], output_path: Path, *, route_out: Path | None = None) -> int:
    from recalith import __version__
    from recalith.providers import api

    placeholder = cfg["probe_installation_id"]
    config = provider_config(cfg, installation_id=placeholder)
    auth = cfg["auth_route"]
    sanitizer = pc.Sanitizer({str(Path.home()): "<home>", str(REPO_ROOT): "<repo>"}, secrets=[os.environ.get(k, "") for k in auth["env_keys"]])
    report: dict[str, Any] = {
        "probe": "tools/probe_provider.py", "probe_schema": 1, "tested_at": pc.utc_now(), "platform": pc.platform_facts(), "provider_id": cfg["provider_id"],
        "backend": cfg["backend"], "engine_build": __version__, "configured_model": cfg["model"], "expected_resolved_model": cfg.get("expected_resolved_model"),
        "endpoint": {"origin": _origin(config.endpoint.url), "path": config.endpoint.url[len(_origin(config.endpoint.url)):], **{k: v for k, v in config.endpoint.model_dump(mode="json").items() if k != "url"}},
        "auth_route": {"kind": auth["kind"], "billing": auth["billing"], "selected_env_key_names": auth["env_keys"], "description": auth["description"], "note": "Names only. No other credential is forwarded to the transport."},
        "operator_attestation": cfg["operator_attestation"],
        "adapter": {"transport": "src/recalith/providers/http_transport.py (python -I, by path)", "dialects": "src/recalith/providers/api.py", "adapter_sha256": api.adapter_digest()},
        "limits": cfg["limits"],
    }
    capture = request_capture(config, cfg) if "request_capture" in cfg["modes"] else None
    live_block: dict[str, Any] | None = None
    if "live" in cfg["modes"]:
        missing = [k for k in auth["env_keys"] if not os.environ.get(k)]
        if auth["kind"] == "not_configured":
            live_block = {"status": "not_run", "reason": "no_auth_route_configured"}
        elif missing:
            live_block = {"status": "not_run", "reason": "selected_auth_env_missing", "missing_key_names": missing}
        elif cfg["operator_attestation"]["background_use"] == "checked_ineligible":
            live_block = {"status": "not_run", "reason": "operator_attested_ineligible_for_background_use"}
        else:
            live_block = live(config, cfg)
    report["request_capture"] = capture
    report["live"] = live_block
    dims = dimensions(config, cfg, capture, live_block)
    report["dimensions"] = dims
    blocking = sorted(k for k, v in dims.items() if v["verdict"] not in ("pass", "informational"))
    certified = not blocking
    report["certified"] = certified
    report["verdict"] = "certified" if certified else ("unavailable" if any(dims[k]["verdict"] == "not_run" for k in blocking) else "uncertified")
    report["blocking_dimensions"] = blocking
    report["failed_checks"] = sorted({x for k in blocking for x in dims[k].get("failures", []) if CHECK_NAME.match(x)})
    calls = (live_block or {}).get("schema_runs") or {}
    resolved = {c["resolved_model"] for c in calls.values() if c.get("resolved_model")}
    report["resolved_model"] = resolved.pop() if len(resolved) == 1 else None
    report["usable_route"] = cfg["provider_id"] if certified else None
    report["limitations"] = [
        "Request capture observes the exact client-side request on loopback; provider-side behavior is observed only in live mode.",
        "An aggregator may route the same model across hosts server-side; only the reported model is checkable.",
        "Environment key names are observed through /proc on Linux; other platforms report the constructed map only.",
    ]
    section = sanitizer.value(report)
    pc.merge_report_section(output_path, SECTION, cfg["provider_id"], section)
    print(json.dumps({"verdict": report["verdict"], "blocking_dimensions": blocking}))
    if route_out is not None:
        try:
            path = write_route(route_out, cfg, section)
        except PermissionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 6
        except (OSError, KeyError, ValueError) as exc:
            return pc.die_usage(f"cannot write the route record: {exc}")
        print(json.dumps({"route_record": str(path), "certified": certified}))
    return pc.EXIT_CERTIFIED if certified else pc.EXIT_UNAVAILABLE


__all__ = ["provider_config", "run", "route_record", "write_route", "dimensions", "cap_failures"]
