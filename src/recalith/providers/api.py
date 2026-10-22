"""Direct-API dialects: the exact request the engine sends and the strict reading of the reply (decision 0023).

Two dialects ship, each as code in this module, never a user-supplied
executable:

* ``messages`` (backend ``anthropic_messages``): ``POST …/v1/messages`` with
  ``model``, ``max_tokens``, ``system`` and one user message. No native JSON
  mode is used (``output_config.format`` adds a provider-written system prompt
  and rejects the constraints the engine's ``output_schema`` uses); the
  curator system prompt asks for JSON, as on the Claude CLI route.
* ``chat_completions`` (backend ``openai_compatible``): ``POST
  …/chat/completions`` with ``model``, a system and a user message, the hard
  output cap in the configured field and, by default, ``response_format:
  {"type": "json_object"}`` (no model-visible tool).

The body's key set is exactly the dialect's set: no tools, tool choice,
functions, streaming, stored state or extra choices. The transport child
(:data:`TRANSPORT_PATH`) sends it once with the key read from its own
environment by name. :func:`unwrap` reads the transport's header line and the
provider's JSON strictly: a returned model other than the expected one, a
tool call, a reported output count above the cap, an auth rejection, a
missing resource or a redirect raise :class:`IsolationViolation` (the backend
is withdrawn); every other failure raises :class:`ProviderCallFailed` with a
content-free code and any usage the provider reported, which the worker
charges. Usage and the resolved model come from the provider's response,
never from model text; the engine's per-operation parsing stays the authority
over the body.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from recalith import __version__
from recalith.prompts import CURATOR_SYSTEM_PROMPT
from recalith.providers.errors import IsolationViolation, ProviderCallFailed

TRANSPORT_PATH = Path(__file__).resolve().with_name("http_transport.py")
ADAPTER_FILES = (Path(__file__).resolve(), TRANSPORT_PATH)
TRANSPORT_SCHEMA = 1
HEADER_ROOM = 4096  # the transport's header line travels inside the same 256 KiB wire cap
USER_AGENT = f"recalith/{__version__}"
# Headers the transport stack adds itself (Python's http.client and urllib), by name.
GENERIC_HEADERS = ("host", "content-type", "content-length", "accept", "accept-encoding", "user-agent", "connection")
AUTH_HEADER = {"x-api-key": ("x-api-key", "raw"), "authorization_bearer": ("authorization", "bearer"), "api-key": ("api-key", "raw"), "none": None}
TRANSPORT_REASONS = frozenset({"endpoint_unreachable", "tls_verification_failed", "tls_handshake_failed", "provider_timeout", "provider_response_incomplete", "provider_failed"})
ROUTE_REASONS = frozenset({"insecure_endpoint_refused", "selected_auth_missing"})
STATUS_CODES = {400: "provider_request_rejected", 408: "provider_timeout", 413: "provider_request_too_large", 429: "provider_rate_limited", 504: "provider_timeout", 529: "provider_overloaded"}
WITHDRAWING_STATUS = {401: "provider_auth_rejected", 403: "provider_auth_rejected", 404: "provider_not_found"}
TOOL_BLOCKS = frozenset({"tool_use", "server_tool_use", "mcp_tool_use"})


def adapter_digest() -> str:
    """SHA-256 over the shipped adapter sources; a certification pins it (``executable_sha256``)."""
    h = hashlib.sha256()
    for path in ADAPTER_FILES:
        data = path.read_bytes().replace(b"\r\n", b"\n")
        h.update(path.name.encode("utf-8") + b"\0" + str(len(data)).encode("ascii") + b"\0" + data)
    return h.hexdigest()


def argv(python: str | None = None) -> list[str]:
    """The transport child: the worker's own interpreter, isolated mode, by file path (no package import)."""
    return [python or sys.executable, "-I", str(TRANSPORT_PATH)]


def expected_model(config: Any) -> str:
    return config.expected_resolved_model or config.configured_model


# --------------------------------------------------------------------------
# Requests


def expected_body_keys(config: Any) -> set[str]:
    endpoint = config.endpoint
    if endpoint.dialect == "messages":
        return {"model", "max_tokens", "system", "messages"}
    return {"model", "messages", endpoint.output_cap_field} | ({"response_format"} if endpoint.json_mode == "json_object" else set())


def build_body(config: Any, raw: bytes, *, output_cap: int) -> bytes:
    """The exact request body: the pinned model, the hard output cap, the curator prompt and the request JSON."""
    endpoint = config.endpoint
    text = raw.decode("utf-8")
    if endpoint.dialect == "messages":
        body: dict[str, Any] = {"model": config.configured_model, "max_tokens": output_cap, "system": CURATOR_SYSTEM_PROMPT, "messages": [{"role": "user", "content": text}]}
    else:
        body = {"model": config.configured_model, "messages": [{"role": "system", "content": CURATOR_SYSTEM_PROMPT}, {"role": "user", "content": text}], endpoint.output_cap_field: output_cap}
        if endpoint.json_mode == "json_object":
            body["response_format"] = {"type": "json_object"}
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def nonsecret_headers(config: Any) -> dict[str, str]:
    headers = {"content-type": "application/json", "accept": "application/json", "user-agent": USER_AGENT}
    if config.endpoint.dialect == "messages":
        headers["anthropic-version"] = config.endpoint.api_version
    return headers


def auth_spec(config: Any) -> dict[str, str] | None:
    selected = AUTH_HEADER[config.endpoint.auth_header]
    if selected is None:
        return None
    return {"header": selected[0], "scheme": selected[1], "env_key": config.auth_env_keys[0]}


def expected_header_names(config: Any) -> list[str]:
    names = set(GENERIC_HEADERS) | set(nonsecret_headers(config))
    auth = auth_spec(config)
    if auth is not None:
        names.add(auth["header"])
    return sorted(names)


def transport_spec(config: Any, body: bytes, *, output_cap: int, timeout_s: float, url: str | None = None) -> dict[str, Any]:
    """What the transport child reads on stdin; it names the key, never carries it."""
    return {
        "transport_schema": TRANSPORT_SCHEMA, "method": "POST", "url": url or config.endpoint.url, "headers": nonsecret_headers(config), "auth": auth_spec(config),
        "body": body.decode("utf-8"), "timeout_seconds": float(timeout_s), "max_response_bytes": max(1, int(config.max_wire_stdout_bytes) - HEADER_ROOM),
        "echo": {"output_cap": int(output_cap), "dialect": config.endpoint.dialect},
    }


# --------------------------------------------------------------------------
# Replies


@dataclass(frozen=True)
class Expect:
    """What every reply must show: the dialect spoken and the model the provider must report."""

    dialect: str
    model: str


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite JSON constant {name}")


def _int(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def read_transport(stdout: bytes) -> tuple[dict[str, Any], bytes]:
    head, sep, body = stdout.partition(b"\n")
    if not sep:
        raise ValueError("the transport wrote no header line")
    header = json.loads(head.decode("utf-8"), parse_constant=_reject_constant)
    if not isinstance(header, dict) or header.get("transport_schema") != TRANSPORT_SCHEMA or header.get("outcome") not in ("response", "transport_error"):
        raise ValueError("not a transport header")
    return header, body


def _usage(dialect: str, data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    if dialect == "messages":
        parts = [_int(raw.get(k)) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")]
        input_tokens = None if parts[0] is None else sum(p or 0 for p in parts)
        output_tokens = _int(raw.get("output_tokens"))
    else:
        input_tokens = _int(raw.get("prompt_tokens"))  # cached tokens are a subset
        output_tokens = _int(raw.get("completion_tokens"))  # reasoning tokens are a subset
    request_id = data.get("id")
    model = data.get("model")
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "provider_request_id": request_id if isinstance(request_id, str) and 0 < len(request_id) <= 256 else None,
        "resolved_model": model[:128] if isinstance(model, str) and model else None,
    }


def _check_model_and_cap(data: dict[str, Any], usage: dict[str, Any], expect: Expect, cap: Any) -> None:
    if data.get("model") != expect.model:
        raise IsolationViolation("model_mismatch")  # never a silent substitution
    if usage["output_tokens"] is not None and type(cap) is int and usage["output_tokens"] > cap:
        raise IsolationViolation("output_cap_exceeded")  # the certified hard cap no longer holds


def _messages(data: dict[str, Any], expect: Expect, cap: Any) -> tuple[bytes, dict[str, Any]]:
    if data.get("type") != "message" or data.get("role") != "assistant" or not isinstance(data.get("content"), list):
        raise ValueError("not a messages reply")
    blocks = data["content"]
    if any(isinstance(b, dict) and b.get("type") in TOOL_BLOCKS for b in blocks) or data.get("stop_reason") in ("tool_use", "pause_turn"):
        raise IsolationViolation("isolation_tools_exposed")
    usage = _usage("messages", data)
    _check_model_and_cap(data, usage, expect, cap)
    stop = data.get("stop_reason")
    if stop in ("max_tokens", "model_context_window_exceeded"):
        raise ProviderCallFailed("output_cap_reached", usage=usage)
    if stop == "refusal":
        raise ProviderCallFailed("provider_refused", usage=usage)
    if stop != "end_turn":
        raise ValueError("unexpected stop reason")
    if len(blocks) != 1 or not isinstance(blocks[0], dict) or blocks[0].get("type") != "text" or not isinstance(blocks[0].get("text"), str):
        raise ValueError("a messages reply carries exactly one text block")
    return blocks[0]["text"].encode("utf-8"), usage


def _chat(data: dict[str, Any], expect: Expect, cap: Any) -> tuple[bytes, dict[str, Any]]:
    choices = data.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict) or not isinstance(choices[0].get("message"), dict):
        raise ValueError("a chat reply carries exactly one choice with a message")
    choice, message = choices[0], choices[0]["message"]
    finish = choice.get("finish_reason")
    if message.get("tool_calls") or message.get("function_call") or finish in ("tool_calls", "function_call"):
        raise IsolationViolation("isolation_tools_exposed")
    usage = _usage("chat_completions", data)
    _check_model_and_cap(data, usage, expect, cap)
    if (isinstance(message.get("refusal"), str) and message["refusal"]) or finish == "content_filter":
        raise ProviderCallFailed("provider_refused", usage=usage)
    if finish == "length":
        raise ProviderCallFailed("output_cap_reached", usage=usage)
    if finish != "stop" or message.get("role") not in (None, "assistant") or not isinstance(message.get("content"), str):
        raise ValueError("unexpected chat reply")
    return message["content"].encode("utf-8"), usage


def unwrap(stdout: bytes, *, expect: Expect) -> tuple[bytes, dict[str, Any]]:
    """The certified reading of one transport result: ``(body bytes, usage)``, or a raised failure."""
    header, body = read_transport(stdout)
    if header["outcome"] == "transport_error":
        reason = header.get("reason")
        if reason in ROUTE_REASONS:
            raise IsolationViolation(reason)
        raise ProviderCallFailed(reason if reason in TRANSPORT_REASONS else "provider_failed")
    if header.get("overflow") is not False:
        raise ProviderCallFailed("wire_stdout_oversized")
    echo = header.get("echo") if isinstance(header.get("echo"), dict) else {}
    if echo.get("dialect") != expect.dialect:
        raise ValueError("the transport echoed another dialect")
    status = header.get("status")
    if type(status) is not int:
        raise ValueError("no HTTP status")
    if 300 <= status < 400:
        raise IsolationViolation("provider_redirect_refused")
    if status in WITHDRAWING_STATUS:
        raise IsolationViolation(WITHDRAWING_STATUS[status])
    if status != 200:
        raise ProviderCallFailed(STATUS_CODES.get(status) or ("provider_server_error" if 500 <= status < 600 else "provider_failed"))
    data = json.loads(body.decode("utf-8"), parse_constant=_reject_constant)
    if not isinstance(data, dict):
        raise ValueError("the reply is not a JSON object")
    request_id = header.get("headers", {}).get("request-id") or header.get("headers", {}).get("x-request-id")
    reader = _messages if expect.dialect == "messages" else _chat
    try:
        text, usage = reader(data, expect, echo.get("output_cap"))
    except ProviderCallFailed as exc:
        if exc.usage is not None and exc.usage.get("provider_request_id") is None and isinstance(request_id, str):
            exc.usage["provider_request_id"] = request_id[:256]
        raise
    if usage["provider_request_id"] is None and isinstance(request_id, str):
        usage["provider_request_id"] = request_id[:256]
    return text, usage


__all__ = [
    "TRANSPORT_PATH", "adapter_digest", "argv", "expected_model", "expected_body_keys", "build_body", "nonsecret_headers", "auth_spec",
    "expected_header_names", "transport_spec", "Expect", "read_transport", "unwrap",
]
