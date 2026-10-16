"""Normalize adapter events into strict envelopes (SYSTEM_SPEC §3.3, §5.1, §13).

Order matters: invalid Unicode is replaced, credentials are scrubbed, the
platform environment is reduced to the registered allowlist, and only then are
certified parsers run and text bounded. Nothing unscrubbed is digested,
bounded or written.

* ``result_text`` keeps at most 8 KiB from the head and 8 KiB from the tail on
  code-point boundaries. The stored display string is ``head + marker + tail``;
  the marker is never addressable evidence. ``text_chunks`` hold the head and
  tail as exact spans with their original code-point offsets, so locators and
  future capsules address real text only (decision 0004).
* Assertions, the error-signature line and runtime versions come only from
  :mod:`recalith.capture.parsers`. Host- or model-supplied assertions and the
  reserved ``expected_red`` hint are dropped with a coverage warning.
* Structured fields take priority over diagnostic text: when an event would
  exceed 64 KiB the head/tail allowance shrinks first, then oversized argument
  strings are bounded, and an event that still cannot fit is refused.
* Very large messages are partitioned into linked events with original offsets.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from pydantic import ValidationError

from recalith.capture import parsers, redact
from recalith.contracts.common import InstallationContext, canonical_json, derived_id, digest_of, filter_environment, utc_now, utf8_len
from recalith.contracts.config import EVENT_PAYLOAD_CAP, EXTENSIONS_CAP, KIB, RESULT_TEXT_HEAD, RESULT_TEXT_TAIL, TOOL_ASSERTIONS_MAX
from recalith.contracts.events import MEMORY_KINDS, OPERATOR_KINDS, TOOL_KINDS, ActionDescriptor, EventEnvelope
from recalith.errors import RecalithError

RUNTIME_KEYS = frozenset({"python_version", "node_version"})
PLATFORM_ENVIRONMENT_KINDS = frozenset({"session_started", "generic_observation"})
MESSAGE_KINDS = frozenset({"user_message", "assistant_message", "generic_observation"})
MESSAGE_PART_BYTES = 48 * KIB
ARGUMENT_STRING_HEAD = 2 * KIB
ARGUMENT_STRING_TAIL = 2 * KIB
TOOL_FIELDS = frozenset({"tool_call_id", "tool_name", "arguments", "result_received", "outcome", "exit_code", "result_text", "action", "observation"})
UNTRUSTED_TOOL_FIELDS = ("assertions", "error_signature", "text_chunks")
_SURROGATE = re.compile(r"[\ud800-\udfff]")

# (channel, authority) assigned by adapter code; never by model output.
CERTIFIED_ROUTING: dict[str, tuple[str, str]] = {
    "session_started": ("external", "untrusted"),
    "user_message": ("user", "explicit_user"),
    "assistant_message": ("assistant", "untrusted"),
    "tool_started": ("tool", "observed_tool"),
    "tool_finished": ("tool", "observed_tool"),
    "artifact_changed": ("tool", "observed_tool"),
    "compaction": ("external", "untrusted"),
    "session_stopped": ("external", "untrusted"),
    "session_ended": ("external", "untrusted"),
    "memory_delivered": ("memory", "derived"),
    "agent_attempted_operator_command": ("memory", "derived"),
    "generic_observation": ("external", "untrusted"),
}


def routing(kind: str, *, certified: bool) -> tuple[str, str]:
    channel, authority = CERTIFIED_ROUTING[kind]
    if not certified and authority in ("explicit_user", "observed_tool"):
        authority = "untrusted"  # an uncertified source never carries user/tool authority
    return channel, authority


@dataclass
class Notes:
    """Coverage flags plus content-free warning counts for one source event."""

    truncated: bool = False
    redacted: bool = False
    missing_context: bool = False
    parser_complete: bool = True
    warnings: dict[str, int] = field(default_factory=dict)

    def warn(self, code: str, n: int = 1) -> None:
        self.warnings[code] = self.warnings.get(code, 0) + n

    def coverage(self) -> dict[str, bool]:
        return {"truncated": self.truncated, "redacted": self.redacted, "missing_context": self.missing_context, "parser_complete": self.parser_complete}


@dataclass
class RawEvent:
    """What an adapter observed, before normalization (never persisted as-is)."""

    adapter_id: str
    adapter_version: str
    source_event_key: str
    session_id: str
    host_session_id: str
    kind: str
    payload: dict[str, Any]
    certified: bool = True
    origin_kind: str = "hook"
    locator: str | None = None
    occurred_at: str | None = None
    recorded_at: str | None = None
    source_sequence: int | None = None
    task_id: str | None = None
    extensions: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Text primitives


def clean_unicode(value: Any, notes: Notes) -> Any:
    """Replace lone surrogates so every stored string is valid UTF-8."""
    if isinstance(value, str):
        if _SURROGATE.search(value):
            notes.warn("invalid_unicode_replaced")
            return _SURROGATE.sub("�", value)
        return value
    if isinstance(value, list):
        return [clean_unicode(v, notes) for v in value]
    if isinstance(value, dict):
        return {clean_unicode(k, notes): clean_unicode(v, notes) for k, v in value.items()}
    return value


def omission_marker(omitted: int) -> str:
    return f"\n[recalith: {omitted} code points omitted]\n"


@dataclass(frozen=True)
class BoundedText:
    stored: str
    chunks: list[dict[str, Any]]
    omitted: tuple[int, int] | None


def _chunk(stored_field: str, source_field: str, start: int, text: str) -> dict[str, Any]:
    return {"stored_field": stored_field, "source_field": source_field, "original_start": start, "original_end": start + len(text), "text": text, "text_digest": digest_of_text(text)}


def digest_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bound_text(text: str, *, source_field: str, head: int = RESULT_TEXT_HEAD, tail: int = RESULT_TEXT_TAIL) -> BoundedText:
    """Keep ≤``head`` UTF-8 bytes from the start and ≤``tail`` from the end.

    Cuts fall on code-point boundaries; chunk offsets are code points into
    the original string.
    """
    data = text.encode("utf-8")
    if len(data) <= head + tail:
        return BoundedText(text, [], None)
    head_chars = len(data[:head].decode("utf-8", errors="ignore")) if head else 0
    tail_chars = len(data[len(data) - tail :].decode("utf-8", errors="ignore")) if tail else 0
    head_text = text[:head_chars]
    tail_start = len(text) - tail_chars
    tail_text = text[tail_start:]
    chunks = []
    if head_text:
        chunks.append(_chunk(f"{source_field}_head", source_field, 0, head_text))
    if tail_text:
        chunks.append(_chunk(f"{source_field}_tail", source_field, tail_start, tail_text))
    omitted = (head_chars, tail_start)
    return BoundedText(head_text + omission_marker(tail_start - head_chars) + tail_text, chunks, omitted)


def _bound_long_strings(value: Any, notes: Notes) -> Any:
    if isinstance(value, str):
        if utf8_len(value) > ARGUMENT_STRING_HEAD + ARGUMENT_STRING_TAIL:
            notes.truncated = True
            notes.warn("argument_text_bounded")
            return bound_text(value, source_field="argument", head=ARGUMENT_STRING_HEAD, tail=ARGUMENT_STRING_TAIL).stored
        return value
    if isinstance(value, list):
        return [_bound_long_strings(v, notes) for v in value]
    if isinstance(value, dict):
        return {k: _bound_long_strings(v, notes) for k, v in value.items()}
    return value


# --------------------------------------------------------------------------
# Payload sanitation (shared with capture's defensive re-check)


def platform_environment(raw: Any, notes: Notes) -> dict[str, str]:
    """Registered, normalized, nonsecret adapter platform facts only (A54)."""
    if not isinstance(raw, Mapping):
        notes.warn("environment_dropped:<invalid>")
        return {}
    kept, dropped = filter_environment(raw)
    for key in sorted(RUNTIME_KEYS & kept.keys()):
        # Runtime versions come only from operator config or a certified tool observation.
        del kept[key]
        dropped[key] = dropped.get(key, 0) + 1
    for label, count in dropped.items():
        notes.warn(f"environment_dropped:{label}", count)
    return kept


def sanitize_payload(kind: str, payload: Mapping[str, Any], notes: Notes) -> dict[str, Any]:
    cleaned = clean_unicode(dict(payload), notes)
    scrubbed, report = redact.scrub_json(cleaned)
    if report.total:
        notes.redacted = True
        notes.warn("redacted", report.total)
    if kind in PLATFORM_ENVIRONMENT_KINDS and "environment" in scrubbed:
        scrubbed["environment"] = platform_environment(scrubbed["environment"], notes)
    return scrubbed


# --------------------------------------------------------------------------
# Tool payloads


def action_family_digest(workspace_id: str, action: ActionDescriptor | Mapping[str, Any]) -> str | None:
    """DATA_CONTRACTS §8: workspace + cwd + tool + executable + ordered argv, or null."""
    a = action.model_dump(mode="json") if isinstance(action, ActionDescriptor) else dict(action)
    if a.get("parse_status") != "exact" or a.get("cwd_path") is None or a.get("argv") is None:
        return None
    return digest_of([workspace_id, a["cwd_path"], a["tool"], a.get("executable"), a["argv"]])


def normalize_tool_payload(kind: str, raw: Mapping[str, Any], notes: Notes) -> dict[str, Any] | None:
    """A ToolPayload-shaped dict, or None when even structured fields cannot fit."""
    data = dict(raw)
    hint = data.pop("expected_red", False)
    if hint not in (False, None):
        notes.warn("expected_red_hint_dropped")  # reserved false in v1: no certified true source
    for key in UNTRUSTED_TOOL_FIELDS:
        if data.pop(key, None) not in (None, [], ""):
            notes.warn(f"untrusted_{key}_dropped")
    unknown = sorted(set(data) - TOOL_FIELDS)
    for key in unknown:
        data.pop(key)
    if unknown:
        notes.parser_complete = False
        notes.warn("unknown_tool_field_dropped", len(unknown))
    action = dict(data.get("action") or {})
    result_received = bool(data.get("result_received")) and kind == "tool_finished"
    exit_code = data.get("exit_code") if result_received and isinstance(data.get("exit_code"), int) and not isinstance(data.get("exit_code"), bool) else None
    text = data.get("result_text") if result_received and isinstance(data.get("result_text"), str) else None
    if kind == "tool_finished" and not result_received:
        notes.missing_context = True
    assertions: list[dict[str, Any]] = []
    signature = None
    if exit_code is not None:
        assertions.append(parsers.exit_status_assertion(exit_code))
    spec = parsers.applicable_parser(action) if result_received and text is not None else None
    if spec is not None:
        parsed = spec.parse(text, exit_code)
        if parsed.recognized:
            assertions.extend(parsed.assertions[: TOOL_ASSERTIONS_MAX - len(assertions)])
            signature = parsed.error_signature
        else:
            notes.parser_complete = False
            notes.warn(f"parser_unrecognized:{spec.qualified_id}")
    base = {
        "tool_call_id": data.get("tool_call_id"),
        "tool_name": data.get("tool_name"),
        "arguments": data.get("arguments") if isinstance(data.get("arguments"), dict) else {},
        "result_received": result_received,
        "outcome": data.get("outcome", "unknown") if result_received else "unknown",
        "exit_code": exit_code,
        "assertions": assertions,
        "action": action,
        "observation": data.get("observation"),
        "error_signature": signature,
        "expected_red": False,
    }
    head, tail = RESULT_TEXT_HEAD, RESULT_TEXT_TAIL
    bounded_arguments = False
    while True:
        payload = dict(base)
        if text is None:
            payload["result_text"], payload["text_chunks"] = None, []
            truncated = False
        else:
            bounded = bound_text(text, source_field="result_text", head=head, tail=tail)
            payload["result_text"], payload["text_chunks"] = bounded.stored, bounded.chunks
            truncated = bounded.omitted is not None
        if len(canonical_json(payload)) <= EVENT_PAYLOAD_CAP:
            if truncated:
                notes.truncated = True
                notes.warn("result_text_bounded")
            return payload
        if head or tail:
            head, tail = head // 2, tail // 2
            if head < 256 and tail < 256:
                head = tail = 0
            continue
        if not bounded_arguments:
            bounded_arguments = True
            base["arguments"] = _bound_long_strings(base["arguments"], notes)
            continue
        notes.warn("event_too_large")
        return None


# --------------------------------------------------------------------------
# Events


def _partition(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Split an oversized message ``text`` into parts with original offsets."""
    text = payload["text"]
    rest = {k: v for k, v in payload.items() if k != "text"}
    parts, start, data = [], 0, text
    while data:
        chunk_chars = len(data.encode("utf-8")[:MESSAGE_PART_BYTES].decode("utf-8", errors="ignore"))
        parts.append((start, data[:chunk_chars]))
        start += chunk_chars
        data = data[chunk_chars:]
    return [dict(rest, text=part, text_part={"source_field": "text", "index": i, "count": len(parts), "original_start": s, "original_end": s + len(part)}) for i, (s, part) in enumerate(parts)]


def _identity_is_clean(raw: RawEvent) -> bool:
    fields = (raw.source_event_key, raw.host_session_id, raw.adapter_version, raw.locator or "")
    return not any(redact.contains_secret(value) for value in fields)


def _validate(data: dict[str, Any]) -> EventEnvelope:
    try:
        return EventEnvelope.model_validate(data)
    except ValidationError as exc:
        locations = sorted({".".join(str(p) for p in err["loc"]) for err in exc.errors()})[:8]
        raise RecalithError("invalid_schema", f"normalized event failed validation at {locations}") from None


def normalize_event(ctx: InstallationContext, raw: RawEvent) -> tuple[list[EventEnvelope], Notes]:
    """One adapter event → one envelope (or linked parts) plus coverage notes."""
    if raw.kind in OPERATOR_KINDS:
        raise RecalithError("policy_refused", "operator events come only from the guarded operator transport")
    if raw.kind not in CERTIFIED_ROUTING:
        raise RecalithError("invalid_schema", "unsupported event kind")
    if not _identity_is_clean(raw):
        raise RecalithError("policy_refused", "a source identity field contains a credential-shaped value; the event is not captured")
    notes = Notes()
    payload = sanitize_payload(raw.kind, raw.payload, notes)
    source_digest = digest_of(payload)
    if raw.kind in TOOL_KINDS:
        tool = normalize_tool_payload(raw.kind, payload, notes)
        if tool is None:
            raise RecalithError("invalid_schema", "tool event cannot fit the 64 KiB event cap even after bounding")
        payloads = [tool]
    elif raw.kind in MESSAGE_KINDS and isinstance(payload.get("text"), str) and len(canonical_json(payload)) > EVENT_PAYLOAD_CAP:
        rest = {k: v for k, v in payload.items() if k != "text"}
        if len(canonical_json(rest)) > 8 * KIB:
            raise RecalithError("invalid_schema", "message metadata is too large to partition")
        payloads = _partition(payload)
        notes.warn("message_partitioned", len(payloads))
    else:
        if len(canonical_json(payload)) > EVENT_PAYLOAD_CAP:
            raise RecalithError("invalid_schema", "event payload exceeds 64 KiB and has no partitionable text")
        payloads = [payload]
    channel, authority = routing(raw.kind, certified=raw.certified)
    extensions = sanitize_payload("extensions", raw.extensions, notes) if raw.extensions else {}
    envelopes = []
    for index, body in enumerate(payloads):
        key = raw.source_event_key if index == 0 else f"{raw.source_event_key}#p{index}"
        event_id = derived_id("evt", [ctx.installation_id, raw.adapter_id, key])
        ext = dict(extensions)
        if notes.warnings:
            namespaced = dict(ext.get(raw.adapter_id, {}))
            namespaced["coverage_warnings"] = dict(sorted(notes.warnings.items()))
            ext[raw.adapter_id] = namespaced
            if len(canonical_json(ext)) > EXTENSIONS_CAP:
                ext = {raw.adapter_id: {"coverage_warnings": {"warnings_truncated": 1}}}
        envelopes.append(
            _validate(
                {
                    "schema_version": 1,
                    "event_id": event_id,
                    "project_id": ctx.project_id,
                    "installation_id": ctx.installation_id,
                    "workspace_id": ctx.workspace_id,
                    "adapter_id": raw.adapter_id,
                    "adapter_version": raw.adapter_version,
                    "source_event_key": key,
                    "session_id": raw.session_id,
                    "host_session_id": raw.host_session_id,
                    "task_id": raw.task_id,
                    "source_sequence": raw.source_sequence,
                    "occurred_at": raw.occurred_at,
                    "recorded_at": raw.recorded_at or utc_now(),
                    "kind": raw.kind,
                    "channel": channel,
                    "origin": {"adapter_id": raw.adapter_id, "source_event_key": raw.source_event_key, "host_session_id": raw.host_session_id, "origin_kind": raw.origin_kind, "source_digest": source_digest, "locator": raw.locator},
                    "authority": authority,
                    "derived_from": [],
                    "root_event_ids": [] if raw.kind in MEMORY_KINDS else [event_id],
                    "payload": body,
                    "payload_digest": digest_of(body),
                    "coverage": notes.coverage(),
                    "extensions": ext,
                }
            )
        )
    return envelopes, notes
