"""Primitive wire layer of the hook fast path (DATA_CONTRACTS §1, §2.3).

Standard library only. It provides the canonical JSON/digest/identifier
primitives shared with the strict contracts, and a validator that interprets
the tables generated from those contracts (``wire_generated``, kept in sync by
``tools/generate_hook_wire.py --check``). Structural checks come from the
tables. The strict models' cross-field validators are mirrored by hand in
:data:`RULES`; the generator refuses to emit a rule name that has no entry
here, and ``test_fast_and_strict_validation_agree`` proves both paths reach
the same verdict on the shared fixtures.

Hook wire shapes are plain dicts (DATA_CONTRACTS §2.3):

* ``HookContextWire``: ``project_id``, ``installation_id``, ``workspace_id``,
  ``root``, ``workspace_root``, ``root_identity``, ``policy_revision``,
  ``adapter_id``, ``host_version``, ``delivery_enabled`` (read from the
  validated local manifest ``.recalith/run/hook-context.json``).
* ``HookRequestWire``: ``event_role``, ``delivery_enabled``, ``events``
  (normalized envelope dicts), ``source_registrations``, ``coverage_gaps``,
  ``query`` (always null in capture-only builds).
* ``HookReplyWire``: ``receipt`` (a ``CaptureReceipt`` dict), ``host_output``,
  ``delivery_attempt_id``, ``emitted_receipt``, ``delivery`` and
  ``degradations``.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import os
import re

from recalith.fast import wire_generated as _g

LIMITS = _g.LIMITS
ID_PREFIXES = frozenset(_g.ID_PREFIXES)
ID_RE = re.compile(_g.ID_PATTERN)
DIGEST_RE = re.compile(_g.DIGEST_PATTERN)
UTC_RE = re.compile(_g.UTC_PATTERN)
PORTABLE_BAD = re.compile(_g.PORTABLE_BAD_PATTERN)
ENVIRONMENT_GRAMMAR = {key: re.compile(pattern) for key, pattern in _g.ENVIRONMENT_GRAMMAR.items()}


class WireError(Exception):
    """A fast-path failure with a stable, content-free ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


# --------------------------------------------------------------------------
# Primitives (byte-identical to recalith.contracts.common)


def check_json(value, depth: int = 0) -> None:
    if depth > 64:
        raise ValueError("JSON nesting deeper than 64")
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite (no NaN or Infinity)")
        return
    if isinstance(value, list):
        for item in value:
            check_json(item, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            check_json(item, depth + 1)
        return
    raise ValueError(f"not a JSON value: {type(value).__name__}")


def canonical_json(value) -> bytes:
    """Canonical UTF-8 JSON: sorted keys, no whitespace, finite numbers only."""
    check_json(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest_of(value) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def digest_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def derived_id(prefix: str, value) -> str:
    if prefix not in ID_PREFIXES:
        raise ValueError(f"unregistered id prefix {prefix!r}")
    return f"{prefix}_{digest_of(value)}"


def new_id(prefix: str) -> str:
    """``prefix_<uuid4>`` without importing :mod:`uuid`."""
    if prefix not in ID_PREFIXES:
        raise ValueError(f"unregistered id prefix {prefix!r}")
    raw = bytearray(os.urandom(16))
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    h = raw.hex()
    return f"{prefix}_{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# --------------------------------------------------------------------------
# Field checks (mirror contracts.common's AfterValidators)


def _is_id(value: str) -> bool:
    match = ID_RE.match(value)
    return bool(match) and match.group("prefix") in ID_PREFIXES


is_id = _is_id


def _is_utc(value: str) -> bool:
    if not UTC_RE.match(value):
        return False
    try:  # same calendar validity as strptime("%Y-%m-%dT%H:%M:%S.%fZ")
        _dt.datetime(int(value[0:4]), int(value[5:7]), int(value[8:10]), int(value[11:13]), int(value[14:16]), int(value[17:19]), int(value[20:26]))
    except ValueError:
        return False
    return True


def is_portable_path(value: str) -> bool:
    return value in ("", ".") or not PORTABLE_BAD.search(value)


def _is_json_object(value) -> bool:
    try:
        check_json(value)
    except ValueError:
        return False
    return True


def environment_ok(key: str, value) -> bool:
    grammar = ENVIRONMENT_GRAMMAR.get(key)
    return grammar is not None and isinstance(value, str) and utf8_len(value) <= 64 and bool(grammar.match(value))


def _is_environment(values: dict) -> bool:
    return all(environment_ok(k, v) for k, v in values.items())


CHECKS = {
    "id": _is_id,
    "digest": lambda v: bool(DIGEST_RE.match(v)),
    "utc": _is_utc,
    "portable_path": is_portable_path,
    "json_object": _is_json_object,
    "environment": _is_environment,
}


# --------------------------------------------------------------------------
# Table interpreter


def _type_ok(kind: str, value) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "null":
        return value is None
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return False


def _same(a, b) -> bool:
    return type(a) is type(b) and a == b if isinstance(a, bool) or isinstance(b, bool) else a == b


def _resolve(ref: str) -> dict:
    return _g.MODELS[ref] if ref in _g.MODELS else _g.DEFS[ref]


class _Run:
    __slots__ = ("errors",)

    def __init__(self) -> None:
        self.errors: list[str] = []

    def fail(self, path: str, message: str) -> None:
        self.errors.append(f"{path or '$'}: {message}")


def _walk(schema: dict, value, path: str, run: _Run):
    """Validate ``value``; return it with Pydantic's defaults filled in."""
    if "$ref" in schema:
        return _walk(_resolve(schema["$ref"]), value, path, run)
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            trial = _Run()
            result = _walk(option, value, path, trial)
            if not trial.errors:
                return result
        run.fail(path, "matches no allowed alternative")
        return value
    kind = schema.get("type")
    if kind is not None and not _type_ok(kind, value):
        run.fail(path, f"expected {kind}")
        return value
    if "const" in schema and not _same(value, schema["const"]):
        run.fail(path, "unexpected constant")
    if "enum" in schema and not any(_same(value, option) for option in schema["enum"]):
        run.fail(path, "value not in the allowed vocabulary")
    before = len(run.errors)
    result = value
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            run.fail(path, "string too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            run.fail(path, "string too long")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            run.fail(path, "string does not match its pattern")
        if "x-utf8-max" in schema:
            try:
                if utf8_len(value) > schema["x-utf8-max"]:
                    run.fail(path, "text exceeds its UTF-8 byte cap")
            except UnicodeEncodeError:
                run.fail(path, "text is not encodable")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            run.fail(path, "number below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            run.fail(path, "number above maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            run.fail(path, "number not above exclusive minimum")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            run.fail(path, "number not below exclusive maximum")
    elif isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            run.fail(path, "too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            run.fail(path, "too many items")
        if "items" in schema:
            result = [_walk(schema["items"], item, f"{path}[{i}]", run) for i, item in enumerate(value)]
    elif isinstance(value, dict):
        result = _walk_object(schema, value, path, run)
    if len(run.errors) == before and "x-check" in schema and not CHECKS[schema["x-check"]](value):
        run.fail(path, f"invalid {schema['x-check']}")
    if len(run.errors) == before and "x-rule" in schema:
        RULES[schema["x-rule"]](result, path, run)
    return result


def _walk_object(schema: dict, value: dict, path: str, run: _Run) -> dict:
    properties = schema.get("properties", {})
    extra = schema.get("additionalProperties", True)
    out = {}
    for key, item in value.items():
        sub = f"{path}.{key}" if path else key
        if "propertyNames" in schema and not re.search(schema["propertyNames"]["pattern"], key):
            run.fail(sub, "key does not match its pattern")
        if key in properties:
            out[key] = _walk(properties[key], item, sub, run)
        elif extra is False:
            run.fail(sub, "unknown field")
        elif isinstance(extra, dict):
            out[key] = _walk(extra, item, sub, run)
        else:
            out[key] = item
    for key in schema.get("required", ()):
        if key not in value:
            run.fail(f"{path}.{key}" if path else key, "missing required field")
    for key, default in schema.get("x-defaults", {}).items():
        if key not in out:
            out[key] = json.loads(json.dumps(default))
    return out


def validate(name: str, value) -> tuple[list[str], object]:
    """Errors (content-free paths and reasons) plus the default-filled value."""
    run = _Run()
    result = _walk(_resolve(name), value, "", run)
    return run.errors, result


def is_valid(name: str, value) -> bool:
    return not validate(name, value)[0]


# --------------------------------------------------------------------------
# Cross-field rules mirrored from the strict model validators

TOOL_KINDS = frozenset({"tool_started", "tool_finished"})
MEMORY_KINDS = frozenset({"memory_delivered", "agent_attempted_operator_command"})


def _rule_action(v: dict, path: str, run: _Run) -> None:
    if v["parse_status"] == "unknown" and (v["argv"] is not None or v["executable"] is not None or v["action_kind"] not in (None, "unknown")):
        run.fail(path, "an unknown parse cannot carry executable, argv or a specific action_kind")


def _rule_assertion(v: dict, path: str, run: _Run) -> None:
    if v["kind"] == "exit_status":
        value = v["value"]
        try:
            canonical = value.lstrip("-").isdigit() and str(int(value)) == value
        except ValueError:
            canonical = False
        if not canonical:
            run.fail(path, "exit_status value must be a canonical decimal integer")
    if v["kind"] != "test_result" and v["passed"] is not None:
        run.fail(path, "only test_result assertions carry a pass/fail verdict")


def _rule_chunk(v: dict, path: str, run: _Run) -> None:
    if v["original_end"] - v["original_start"] != len(v["text"]):
        run.fail(path, "chunk text length must equal its original coordinate span")
        return
    try:
        if digest_of_text(v["text"]) != v["text_digest"]:
            run.fail(path, "text_digest does not match chunk text")
    except UnicodeEncodeError:
        run.fail(path, "chunk text is not encodable")


def _rule_dependency(v: dict, path: str, run: _Run) -> None:
    if v["kind"] == "file" and not is_portable_path(v["key"]):
        run.fail(path, "file dependencies use portable paths")
    if v["kind"] == "environment" and v["key"] not in ENVIRONMENT_GRAMMAR:
        run.fail(path, "environment dependencies use registered keys")
    if (v["kind"] == "claim") != (v["record"] is not None):
        run.fail(path, "claim dependencies (and only they) carry an exact RecordRef")
    if v["record"] is not None and v["record"]["kind"] != "claim":
        run.fail(path, "claim dependency must reference a claim")


def _rule_tool_payload(v: dict, path: str, run: _Run) -> None:
    if not v["result_received"] and (v["outcome"] != "unknown" or v["exit_code"] is not None):
        run.fail(path, "a call without a received result has unknown outcome and no exit code")


def _rule_envelope(v: dict, path: str, run: _Run) -> None:
    def fail(message: str) -> None:
        run.fail(path, message)

    if not v["event_id"].startswith("evt_"):
        return fail("event ids use the evt_ or evt_imp_ prefix")
    try:
        payload_bytes = canonical_json(v["payload"])
    except ValueError:
        return fail("payload is not canonical JSON")
    if len(payload_bytes) > LIMITS["EVENT_PAYLOAD_CAP"]:
        return fail("event payload exceeds 64 KiB")
    if digest_of(v["payload"]) != v["payload_digest"]:
        return fail("payload_digest does not match the canonical payload")
    extensions = v["extensions"]
    if extensions and len(canonical_json(extensions)) > LIMITS["EXTENSIONS_CAP"]:
        return fail("extensions exceed their byte cap")
    if extensions and set(extensions) != {v["adapter_id"]}:
        return fail("extensions must be namespaced by the producing adapter")
    channel, authority, kind = v["channel"], v["authority"], v["kind"]
    if authority == "explicit_user" and channel != "user":
        return fail("explicit_user authority requires the user channel")
    if authority == "observed_tool" and channel != "tool":
        return fail("observed_tool authority requires the tool channel")
    if channel in ("assistant", "memory") and authority not in ("untrusted", "derived"):
        return fail("assistant and memory channels can never carry user or tool authority")
    if kind in TOOL_KINDS:
        if channel != "tool":
            return fail("tool events use the tool channel")
        errors, tool = validate("ToolPayload", v["payload"])
        if errors:
            return fail("tool payload is invalid")
        if kind == "tool_started" and (tool["result_received"] or tool["outcome"] != "unknown"):
            return fail("tool_started has no result; a later linked event supplies it")
    if kind in MEMORY_KINDS and (channel != "memory" or authority != "derived"):
        return fail("memory telemetry is channel memory with derived authority")
    if kind == "agent_attempted_operator_command":
        if not is_valid("AgentAttemptPayload", v["payload"]):
            return fail("refused-command payload is invalid")
        if v["root_event_ids"] or v["derived_from"]:
            return fail("a refused-command diagnostic has no eligible root")
    if kind == "user_message" and channel != "user":
        return fail("user_message uses the user channel")
    if kind == "assistant_message" and channel != "assistant":
        return fail("assistant_message uses the assistant channel")
    if not v["derived_from"] and v["root_event_ids"] not in ([], [v["event_id"]]):
        return fail("an original event is its own root")
    if authority == "derived" and v["root_event_ids"] and kind in MEMORY_KINDS:
        return fail("memory telemetry never supplies support roots")


def _rule_receipt(v: dict, path: str, run: _Run) -> None:
    if v["status"] == "not_captured" and (v["error_code"] is None or v["segment_id"] is not None):
        run.fail(path, "not_captured receipts carry an error code and no segment")
    if v["status"] == "accepted" and v["segment_id"] is None:
        run.fail(path, "accepted receipts name their durable segment")


def segment_body(envelopes: list, cursor_proposals: list, source_registrations: list | None = None) -> dict:
    from recalith.fast.spool import segment_body as body

    return body(envelopes, cursor_proposals, source_registrations)


def _rule_segment(v: dict, path: str, run: _Run) -> None:
    body = segment_body(v["envelopes"], v["cursor_proposals"], v["source_registrations"])
    if len(canonical_json(body)) > LIMITS["SEGMENT_CAP"]:
        return run.fail(path, "segment exceeds 256 KiB")
    if digest_of(body) != v["content_digest"]:
        return run.fail(path, "segment content_digest mismatch")
    for env in v["envelopes"]:
        if env["installation_id"] != v["installation_id"] or env["project_id"] != v["project_id"]:
            return run.fail(path, "foreign_installation: segment contains another installation's event")


def _rule_scratch(v: dict, path: str, run: _Run) -> None:
    if len(canonical_json(v)) > LIMITS["SESSION_SCRATCH_CAP"]:
        run.fail(path, "session scratch exceeds 128 KiB")
    if v["restoration_tokens"] > v["reserved_tokens"] or v["emitted_tokens"] > v["reserved_tokens"]:
        run.fail(path, "restoration and emitted tokens are parts of the reserved total")


def _rule_delivery_receipt(v: dict, path: str, run: _Run) -> None:
    if (v["state"] == "emitted") != (v["emitted_at"] is not None):
        run.fail(path, "only emitted receipts carry an emission time")
    if v["state"] == "uncertain" and v["in_flight_change"] is not None:
        run.fail(path, "only an emitted receipt reports the post-emission check")
    if v["restoration_key"] is not None and v["purpose"] != "compact_restore":
        run.fail(path, "only a restoration packet carries a restoration key")
    if v["pre_action_substitution_tokens"] > v["estimated_tokens"]:
        run.fail(path, "substitution is part of, not added to, the packet estimate")


REASON_CODES = frozenset({
    "task_continuity", "exact_action_match", "dependency_match", "path_match", "lexical_match", "explicit_query",
    "conflict", "revision_change", "compaction_restore", "recent_observation", "tentative_context",
})


def _rule_item(v: dict, path: str, run: _Run) -> None:
    why = v.get("why")
    if isinstance(why, list) and why and why[0] not in REASON_CODES:
        run.fail(path, "why[0] must be a registered ReasonCode")
    if v.get("advice") == "caution" and (v.get("applicability") != "true" or v.get("freshness") != "current"):
        run.fail(path, "caution requires applicability 'true' and current freshness")
    if v.get("applicability") == "false":
        run.fail(path, "inapplicable items are excluded, never delivered")


def _rule_packet(v: dict, path: str, run: _Run) -> None:
    sub, est = v.get("pre_action_substitution_tokens"), v.get("estimated_tokens")
    if not isinstance(sub, int) or not isinstance(est, int) or isinstance(sub, bool):
        return
    if sub:
        if v.get("purpose") != "prompt":
            run.fail(path, "only an ordinary prompt packet takes the pre-action substitution allowance")
        elif not any(isinstance(i, dict) and i.get("advice") == "caution" for i in v.get("items") or []):
            run.fail(path, "no substitution allowance without an eligible caution")
    if sub > est:
        run.fail(path, "substitution is part of, not added to, the packet estimate")


RULES = {
    "ContextItem._advice_gates": _rule_item,
    "ContextPacket._substitution": _rule_packet,
    "ActionDescriptor._unknown_stays_unknown": _rule_action,
    "ToolAssertion._shape": _rule_assertion,
    "TextChunk._exact": _rule_chunk,
    "DependencyRef._resolution": _rule_dependency,
    "ToolPayload._result_consistency": _rule_tool_payload,
    "EventEnvelope._consistency": _rule_envelope,
    "CaptureReceipt._shape": _rule_receipt,
    "Segment._bounded_and_owned": _rule_segment,
    "SessionScratch._bounded": _rule_scratch,
    "DeliveryReceipt._emission": _rule_delivery_receipt,
}
