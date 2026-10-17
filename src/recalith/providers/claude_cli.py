"""Claude CLI inference adapter (SYSTEM_SPEC §9.1; decision 0002).

The curator runs the configured executable with the certified argument array
from decision 0002 (``-p --bare --tools "" --strict-mcp-config
--setting-sources "" --disable-slash-commands --no-session-persistence``
plus the explicit ``--model`` and the fixed curator ``--system-prompt``),
never ``--json-schema`` (it adds a model-visible tool). The request JSON goes
over stdin; the reply is the ``stream-json`` envelope.

:func:`unwrap` is the route's certified envelope parser and also re-checks the
host's own init diagnostic on *every* call: an exposed tool, an MCP server, a
non-builtin plugin, a different host version or a different auth source than
the route was certified with is an :class:`IsolationViolation`, which disables
the backend until the route is recertified. Usage and the resolved model come
from the envelope (adapter code), never from the model's text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Sequence

from recalith.providers.errors import IsolationViolation

BACKEND = "claude_cli"
ENVELOPE = "claude_stream_json"
# Decision 0002: the candidate isolated argument array observed on 2.1.301.
ISOLATION_ARGS = (
    "-p", "--bare", "--tools", "", "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands", "--no-session-persistence",
    "--model", "{model}", "--system-prompt", "{system_prompt}", "--output-format", "stream-json", "--verbose",
)
REQUIRED_FLAGS = ("-p", "--bare", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence")
_VERSION = re.compile(r"(\d+\.\d+\.\d+)")


@dataclass(frozen=True)
class Expectations:
    """What the per-call init diagnostic must show (from the route's certification)."""

    host_version: str | None
    api_key_source: str | None = None


def argument_problems(args: Sequence[str]) -> list[str]:
    """Reasons the configured array is not the certified isolation shape (never a guessed flag)."""
    args = list(args)
    problems = [f"missing_flag:{flag}" for flag in REQUIRED_FLAGS if flag not in args]
    for flag, value in (("--tools", ""), ("--setting-sources", "")):
        if flag not in args or args.index(flag) + 1 >= len(args) or args[args.index(flag) + 1] != value:
            problems.append(f"flag_value:{flag}")
    if "--json-schema" in args:
        problems.append("json_schema_tool")
    if "{model}" not in args:
        problems.append("model_not_explicit")
    for flag in ("--output-format", "--verbose"):
        if flag not in args:
            problems.append(f"missing_flag:{flag}")
    if "--output-format" in args and args[args.index("--output-format") + 1 : args.index("--output-format") + 2] != ["stream-json"]:
        problems.append("envelope_not_stream_json")
    for risky in ("--continue", "--resume", "--add-dir", "--mcp-config", "--settings", "--plugin-dir", "--dangerously-skip-permissions", "--allowedTools", "--allowed-tools"):
        if risky in args:
            problems.append(f"unsafe_flag:{risky}")
    return problems


def argv(executable: str, args: Sequence[str], *, model: str, system_prompt: str) -> list[str]:
    return [executable] + [a.replace("{model}", model).replace("{system_prompt}", system_prompt) for a in args]


def parse_version(text: str) -> str | None:
    match = _VERSION.search(text or "")
    return match.group(1) if match else None


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite JSON constant {name}")


def summarize_init(init: dict[str, Any]) -> dict[str, Any]:
    plugins = [p for p in (init.get("plugins") or []) if isinstance(p, dict)]
    return {
        "tools": [str(t) for t in (init.get("tools") or [])],
        "mcp_servers": [str(s.get("name") if isinstance(s, dict) else s) for s in (init.get("mcp_servers") or [])],
        "non_builtin_plugins": [str(p.get("source") or p.get("name")) for p in plugins if p.get("path") != "builtin"],
        "host_version": init.get("claude_code_version") if isinstance(init.get("claude_code_version"), str) else None,
        "api_key_source": init.get("apiKeySource") if isinstance(init.get("apiKeySource"), str) else None,
        "model": init.get("model") if isinstance(init.get("model"), str) else None,
        "skills_count": len(init.get("skills") or []),
        "slash_commands_count": len(init.get("slash_commands") or []),
    }


def parse_envelope(stdout: bytes) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """``(init event, result event)`` of a stream-json envelope; ``ValueError`` when malformed.

    Every line must be a JSON object; exactly one ``result`` event must be
    present. Unknown event types are host-internal and carry nothing the
    engine reads; nothing is inferred from them.
    """
    init = None
    results = []
    for line in stdout.decode("utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line, parse_constant=_reject_constant)
        if not isinstance(event, dict):
            raise ValueError("envelope line is not an object")
        if event.get("type") == "system" and event.get("subtype") == "init" and init is None:
            init = event
        elif event.get("type") == "result":
            results.append(event)
    if len(results) != 1:
        raise ValueError("envelope must carry exactly one result event")
    return init, results[0]


def check_init(init: dict[str, Any] | None, expect: Expectations) -> dict[str, Any]:
    """Raise :class:`IsolationViolation` unless the host diagnostic shows the certified, tool-free launch."""
    if init is None:
        raise IsolationViolation("isolation_init_missing")
    summary = summarize_init(init)
    if summary["tools"]:
        raise IsolationViolation("isolation_tools_exposed")
    if summary["mcp_servers"]:
        raise IsolationViolation("isolation_mcp_present")
    if summary["non_builtin_plugins"]:
        raise IsolationViolation("isolation_plugins_present")
    if expect.host_version is not None and summary["host_version"] != expect.host_version:
        raise IsolationViolation("host_version_changed")
    if expect.api_key_source is not None and summary["api_key_source"] != expect.api_key_source:
        raise IsolationViolation("auth_route_mismatch")
    return summary


def _int(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def unwrap(stdout: bytes, *, expect: Expectations) -> tuple[bytes, dict[str, Any]]:
    """Validate the envelope and the per-call isolation diagnostic; return (body bytes, usage)."""
    init, result = parse_envelope(stdout)
    summary = check_init(init, expect)
    if result.get("subtype") != "success" or result.get("is_error") is not False:
        raise ValueError("result event is not a success")
    body = result.get("result")
    if not isinstance(body, str):
        raise ValueError("result event carries no body string")
    raw = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    parts = [_int(raw.get(k)) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")]
    input_tokens = None if parts[0] is None else sum(p or 0 for p in parts)
    usage = {
        "input_tokens": input_tokens,
        "output_tokens": _int(raw.get("output_tokens")),
        "provider_request_id": None,
        "resolved_model": summary["model"],
    }
    return body.encode("utf-8"), usage


__all__ = ["BACKEND", "ISOLATION_ARGS", "Expectations", "argument_problems", "argv", "parse_version", "parse_envelope", "check_init", "summarize_init", "unwrap"]
