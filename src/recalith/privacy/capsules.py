"""Exact evidence capsules (full profile; SYSTEM_SPEC §11; DATA_CONTRACTS §6; decision 0025).

**What a capsule is.** When a payload a live claim needs is past the full
profile's unpinned window, the retention sweep may replace it with a capsule
that keeps exactly what the live owners cite: one :class:`CapsuleSpan` per
distinct referenced locator (the exact substring, its original field/start/
end/digest and at most :data:`CONTEXT_CODE_POINTS` of surrounding text from the
same stored field), the typed fields a registered mapping or the failure
derivation reads, and, for a user or operator statement, the code-point
ranges of its nondeclaration regions so the declaration check can be repeated
on a span. The event row keeps its envelope metadata; its payload becomes NULL
and ``payload_state`` ``capsule_only``. Capsule creation is deterministic
storage work: no model, no network, no new root and no fresh support.

**Sufficiency** (:func:`compact`). The pin stays, with a reason, unless the
event is a registered root needed by no unfinished work and no live working
context, has no unresolved source conflict, and every reference to it from a
record revision the live claims' pin closure visits is covered: a locator that
resolves exactly in the payload, a mapping on a certified tool result, or a
null locator on a statement (whose contract cites the whole field). The built
capsule is validated and every reference re-resolved through it before
anything is written.

**Identity and the origin index.** ``capsule_id`` is derived from the event ID,
so the event-to-capsule index needs no column; ``preserved_observation``
names the event for the reverse direction. Covered claim-owned
``evidence_links`` rows are redirected to the capsule (original locator kept);
task/episode links and frozen refs in revision and proposal bodies stay event
refs and resolve through the event's capsule.

**Resolution** (:func:`resolve`) dispatches by ``RecordRef.kind`` and finds a
located reference by its exact original locator. It never slices a capsule at
the old offsets.

**Release** (:func:`drop`). Expiry of a released capsule-only event and
forgetting delete the capsule and turn links redirected to it back into
event refs, in the caller's transaction.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from recalith.contracts.common import RecordRef, Scope, SourceRef, SpanLocator, canonical_json, derived_id, digest_of
from recalith.contracts.memory import CapsuleSpan, EvidenceCapsule
from recalith.core import regions

KIND = "retention_capsule"  # the content-free audit of one compaction transaction
CONTEXT_CODE_POINTS = 160
CAPSULE_SCHEMA = 1
DECLARATION_FIELDS = {"user_message": "text", "operator_declaration": "statement", "operator_correction": "statement"}
TOOL_FIELDS = ("tool_name", "action", "result_received", "outcome", "exit_code")
_ASSERTION = re.compile(r"^assertions\.(\d+)\.value$")
_IN = 400

# Why a pinned payload past its window was not compacted (decision 0025 §3).
REASONS = ("owed_work", "open_working_context", "not_a_root", "source_conflict", "locator_unresolved", "mapping_unpreserved", "unlocated_reference", "verification_failed")


def capsule_id(event_id: str) -> str:
    """The capsule of one event (deterministic: the origin index needs no column)."""
    return derived_id("cap", ["evidence_capsule", event_id])


def _chunks(items: Sequence[Any]) -> Iterable[Sequence[Any]]:
    for i in range(0, len(items), _IN):
        yield items[i : i + _IN]


# --------------------------------------------------------------------------
# Reading


def load(q: Any, cid: str) -> EvidenceCapsule | None:
    row = q.execute("SELECT body FROM evidence_capsules WHERE capsule_id = ?", (cid,)).fetchone()
    if row is None or row[0] is None:
        return None
    return EvidenceCapsule.model_validate_json(row[0])


def for_event(q: Any, event_id: str) -> EvidenceCapsule | None:
    return load(q, capsule_id(event_id))


def origin_event(q: Any, cid: str) -> str | None:
    """The event a capsule preserves (None when the capsule is unknown)."""
    capsule = load(q, cid)
    return None if capsule is None else origin_of(capsule)


def origin_of(capsule: EvidenceCapsule) -> str:
    return capsule.preserved_observation["event_id"]


def existing(q: Any, event_ids: Iterable[str]) -> dict[str, str]:
    """capsule ID -> event ID for the given events that have a capsule."""
    wanted = {capsule_id(e): e for e in event_ids}
    found: dict[str, str] = {}
    keys = sorted(wanted)
    for chunk in _chunks(keys):
        marks = ",".join("?" for _ in chunk)
        for (cid,) in q.execute(f"SELECT capsule_id FROM evidence_capsules WHERE capsule_id IN ({marks})", tuple(chunk)).fetchall():  # noqa: S608
            found[cid] = wanted[cid]
    return found


def stats(q: Any) -> tuple[int, int]:
    """(capsule count, capsule body bytes)."""
    count, size = q.execute("SELECT COUNT(*), COALESCE(SUM(length(CAST(body AS BLOB))), 0) FROM evidence_capsules").fetchone()
    return int(count), int(size)


def find_span(capsule: EvidenceCapsule, locator: SpanLocator) -> CapsuleSpan | None:
    """The span with exactly this original locator (field, start, end and digest), or None."""
    for span in capsule.spans:
        if span.original_locator == locator:
            return span
    return None


def whole_statement(capsule: EvidenceCapsule) -> CapsuleSpan | None:
    """The span keeping a statement's whole field, if the capsule keeps it."""
    statement = capsule.preserved_observation.get("statement")
    if not isinstance(statement, dict):
        return None
    for span in capsule.spans:
        loc = span.original_locator
        if (loc.field, loc.start, loc.end) == (statement["field"], 0, statement["length"]):
            return span
    return None


def covers(capsule: EvidenceCapsule, locator: SpanLocator | None, mapping: str | None) -> bool:
    """Whether this capsule keeps everything a reference with this locator and mapping cites."""
    observation = capsule.preserved_observation
    if locator is not None:
        if find_span(capsule, locator) is None:
            return False
        m = _ASSERTION.match(locator.field)
        if m is not None and mapping is not None:
            return isinstance((observation.get("assertions") or {}).get(m.group(1)), dict)
        return mapping is None or isinstance(observation.get("tool"), dict)
    if mapping is not None:
        return isinstance(observation.get("tool"), dict)
    return whole_statement(capsule) is not None


def typed_payload(capsule: EvidenceCapsule) -> dict[str, Any]:
    """The preserved typed fields shaped like a tool payload (assertions by their original index; no text)."""
    observation = capsule.preserved_observation
    out: dict[str, Any] = dict(observation.get("tool") or {})
    kept = observation.get("assertions") or {}
    size = max((int(k) + 1 for k in kept), default=0)
    out["assertions"] = [kept.get(str(i)) for i in range(size)]
    return out


@dataclass(frozen=True)
class Resolution:
    """What one reference resolves to: ``state`` is the evidence state (``uncovered``: the capsule does not keep it)."""

    state: str  # available | capsule_only | uncovered | expired | forgotten | missing
    text: str | None = None
    source: str | None = None  # payload | capsule
    event_id: str | None = None
    capsule: EvidenceCapsule | None = None


def _field(data: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(data, dict) and part in data:
            data = data[part]
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return None
    return data


def exact_slice(payload: Any, locator: SpanLocator) -> str | None:
    """The located substring of a stored payload when it hashes to the locator digest, else None."""
    text = _field(payload, locator.field)
    if not isinstance(text, str) or locator.start > locator.end or locator.end > len(text):
        return None
    span = text[locator.start : locator.end]
    return span if hashlib.sha256(span.encode("utf-8")).hexdigest() == locator.text_digest else None


def _from_capsule(capsule: EvidenceCapsule, locator: SpanLocator | None) -> Resolution:
    event_id = origin_of(capsule)
    span = whole_statement(capsule) if locator is None else find_span(capsule, locator)
    if locator is not None and span is None:
        return Resolution("uncovered", None, None, event_id, capsule)
    return Resolution("capsule_only", span.text if span is not None else None, "capsule", event_id, capsule)


def resolve(q: Any, ref: RecordRef, locator: SpanLocator | None) -> Resolution:
    """Dispatch by ``ref.kind``: an event's payload or capsule, or a capsule; never a slice at old offsets."""
    if ref.kind == "capsule":
        capsule = load(q, ref.id)
        return Resolution("missing") if capsule is None else _from_capsule(capsule, locator)
    if ref.kind != "event":
        raise ValueError("capsules resolve event and capsule refs only")
    row = q.execute("SELECT kind, payload_state, payload FROM events WHERE event_id = ?", (ref.id,)).fetchone()
    if row is None:
        return Resolution("missing", event_id=ref.id)
    kind, state, payload = row
    if state == "capsule_only":
        capsule = for_event(q, ref.id)
        return Resolution("missing", event_id=ref.id) if capsule is None else _from_capsule(capsule, locator)
    if state != "available" or payload is None:
        return Resolution(state, event_id=ref.id)
    data = json.loads(payload)
    if locator is None:
        name = DECLARATION_FIELDS.get(kind)
        text = data.get(name) if name else None
        return Resolution("available", text if isinstance(text, str) else None, "payload", ref.id)
    text = exact_slice(data, locator)
    return Resolution("available" if text is not None else "uncovered", text, "payload" if text is not None else None, ref.id)


# --------------------------------------------------------------------------
# Compaction


@dataclass
class Outcome:
    """One compaction transaction (content-free)."""

    compacted: list[str] = field(default_factory=list)
    capsule_ids: list[str] = field(default_factory=list)
    deferred: dict[str, int] = field(default_factory=dict)
    deferred_events: dict[str, str] = field(default_factory=dict)
    redirected: list[int] = field(default_factory=list)

    def defer(self, event_id: str, reason: str) -> None:
        self.deferred[reason] = self.deferred.get(reason, 0) + 1
        self.deferred_events[event_id] = reason


@dataclass(frozen=True)
class _Ref:
    link_id: int
    owner: tuple[str, str, int]
    locator: SpanLocator | None
    mapping: str | None


def _certified_result(envelope: dict[str, Any], payload: dict[str, Any]) -> bool:
    return (
        envelope.get("kind") == "tool_finished" and envelope.get("channel") == "tool" and envelope.get("authority") == "observed_tool"
        and not envelope.get("derived_from") and payload.get("result_received") is True
    )


def _refs(q: Any, event_id: str) -> list[_Ref]:
    rows = q.execute(
        "SELECT link_id, owner_kind, owner_id, owner_revision, locator, mapping FROM evidence_links WHERE target_kind = 'event' AND target_id = ? ORDER BY link_id", (event_id,),
    ).fetchall()
    return [_Ref(r[0], (r[1], r[2], r[3]), None if r[4] is None else SpanLocator.model_validate_json(r[4]), r[5]) for r in rows]


def _registered_root(q: Any, event_id: str) -> bool:
    return q.execute("SELECT 1 FROM root_event_members WHERE event_id = ?", (event_id,)).fetchone() is not None


def _conflicted(q: Any, event_id: str) -> bool:
    return q.execute(
        "SELECT 1 FROM source_conflicts c JOIN events e ON e.adapter_id = c.adapter_id AND e.source_event_key = c.source_event_key WHERE e.event_id = ? AND c.state = 'unresolved'",
        (event_id,),
    ).fetchone() is not None


def _span(text: str, locator: SpanLocator, event_id: str) -> CapsuleSpan:
    start, end = locator.start, locator.end
    return CapsuleSpan(
        origin_ref=RecordRef(kind="event", id=event_id, revision=1), original_locator=locator, text=text[start:end],
        context_before=text[max(0, start - CONTEXT_CODE_POINTS) : start], context_after=text[end : end + CONTEXT_CODE_POINTS], text_digest=locator.text_digest,
    )


def build(envelope: dict[str, Any], payload: dict[str, Any], refs: Sequence[_Ref]) -> tuple[EvidenceCapsule | None, str | None]:
    """The capsule covering ``refs`` exactly, or the reason it cannot (decision 0025 §3–§4). Pure: reads nothing else."""
    from recalith.contracts.events import EventEnvelope
    from recalith.core import lineage

    event_id = envelope["event_id"]
    kind = envelope.get("kind")
    spans: dict[tuple, CapsuleSpan] = {}
    assertions: dict[str, Any] = {}
    statement_name = DECLARATION_FIELDS.get(kind)
    statement = payload.get(statement_name) if statement_name else None
    for ref in refs:
        if ref.locator is not None:
            if exact_slice(payload, ref.locator) is None:
                return None, "locator_unresolved"
            holder = _field(payload, ref.locator.field)
            spans[(ref.locator.field, ref.locator.start, ref.locator.end, ref.locator.text_digest)] = _span(holder, ref.locator, event_id)
            m = _ASSERTION.match(ref.locator.field)
            if m is not None:
                item = _field(payload, f"assertions.{m.group(1)}")
                if isinstance(item, dict):
                    assertions[m.group(1)] = item
            if ref.mapping is not None and not _certified_result(envelope, payload):
                return None, "mapping_unpreserved"
        elif ref.mapping is not None:
            if not _certified_result(envelope, payload):
                return None, "mapping_unpreserved"
        elif isinstance(statement, str):
            whole = SpanLocator(field=statement_name, start=0, end=len(statement), text_digest=hashlib.sha256(statement.encode("utf-8")).hexdigest())
            spans[(whole.field, 0, whole.end, whole.text_digest)] = _span(statement, whole, event_id)
        else:
            return None, "unlocated_reference"
    observation: dict[str, Any] = {"schema": CAPSULE_SCHEMA, "event_id": event_id, "event_kind": kind, "channel": envelope.get("channel"), "authority": envelope.get("authority")}
    if kind == "tool_finished":
        observation["tool"] = {k: payload.get(k) for k in TOOL_FIELDS}
        if assertions:
            observation["assertions"] = assertions
    if isinstance(statement, str):
        part = payload.get("text_part")
        observation["statement"] = {
            "field": statement_name, "length": len(statement), "text_part_count": part.get("count", 1) if isinstance(part, dict) else 1,
            "regions": [[r.start, r.end] for r in regions.regions(statement)],
        }
    env = EventEnvelope.model_validate({**envelope, "payload": payload})
    data = {
        "capsule_id": capsule_id(event_id), "source_ref": SourceRef.model_validate(env.origin.model_dump(mode="json")).model_dump(mode="json"),
        "origin_event_key": lineage.origin_key(env).model_dump(mode="json"), "root_event_ids": [event_id], "preserved_observation": observation,
        "spans": [spans[k].model_dump(mode="json") for k in sorted(spans)], "captured_at": env.recorded_at,
        "scope": Scope(workspace_ids=[env.workspace_id]).model_dump(mode="json"), "redacted": env.coverage.redacted,
    }
    data["content_digest"] = digest_of(data)
    try:
        capsule = EvidenceCapsule.model_validate(data)
    except ValueError:
        return None, "verification_failed"
    # Every reference re-resolved through the capsule gives exactly what the payload gives.
    for ref in refs:
        if not covers(capsule, ref.locator, ref.mapping):
            return None, "verification_failed"
        if ref.locator is not None and find_span(capsule, ref.locator).text != exact_slice(payload, ref.locator):
            return None, "verification_failed"
        if ref.locator is None and ref.mapping is not None and any(capsule.preserved_observation["tool"][k] != payload.get(k) for k in TOOL_FIELDS):
            return None, "verification_failed"
    return capsule, None


def compact(txn: Any, candidates: Sequence[str], *, owed: set[str], working: set[str], claim_records: set[tuple[str, str, int]], keep: set[str],
            cutoff: str, cursor: int) -> Outcome:
    """Inside the compaction transaction: create, verify, redirect and remove, or retain the pin with a reason.

    ``owed``, ``working``, ``claim_records`` and ``keep`` (every pinned event)
    come from the pin closure recomputed in this same transaction.
    """
    out = Outcome()
    for event_id in candidates:
        row = txn.execute("SELECT envelope, payload, payload_state, recorded_at, commit_sequence FROM events WHERE event_id = ?", (event_id,)).fetchone()
        if row is None or row[2] != "available" or row[1] is None or row[3] >= cutoff or row[4] > cursor or event_id not in keep:
            continue  # changed since selection (released, forgotten, or no longer pinned: the expiry pass decides it)
        if event_id in owed:
            out.defer(event_id, "owed_work")
            continue
        if event_id in working:
            out.defer(event_id, "open_working_context")
            continue
        if not _registered_root(txn, event_id):
            out.defer(event_id, "not_a_root")
            continue
        if _conflicted(txn, event_id):
            out.defer(event_id, "source_conflict")
            continue
        refs = _refs(txn, event_id)
        needed = [r for r in refs if r.owner in claim_records]
        envelope, payload = json.loads(row[0]), json.loads(row[1])
        capsule, reason = build(envelope, payload, needed)
        if capsule is None:
            out.defer(event_id, reason or "verification_failed")
            continue
        cid = capsule.capsule_id
        body = canonical_json(capsule.model_dump(mode="json")).decode()
        txn.execute(
            "INSERT OR REPLACE INTO evidence_capsules (capsule_id, source_namespace, source_event_key, content_digest, body) VALUES (?, ?, ?, ?, ?)",
            (cid, capsule.origin_event_key.source_namespace, capsule.origin_event_key.source_event_key, capsule.content_digest, body),
        )
        for ref in refs:
            if ref.owner[0] == "claim" and covers(capsule, ref.locator, ref.mapping):
                txn.execute("UPDATE evidence_links SET target_kind = 'capsule', target_id = ?, target_revision = 1 WHERE link_id = ?", (cid, ref.link_id))
                out.redirected.append(ref.link_id)
        txn.execute("UPDATE events SET payload = NULL, payload_state = 'capsule_only' WHERE event_id = ? AND payload_state = 'available'", (event_id,))
        txn.execute("UPDATE source_conflicts SET scrubbed_payload = NULL WHERE scrubbed_payload IS NOT NULL AND original_event_id = ?", (event_id,))
        out.compacted.append(event_id)
        out.capsule_ids.append(cid)
    return out


def drop(txn: Any, event_ids: Iterable[str]) -> list[str]:
    """Delete these events' capsules and turn links redirected to them back into event refs (expiry, forgetting)."""
    found = existing(txn, event_ids)
    for cid, event_id in sorted(found.items()):
        txn.execute("UPDATE evidence_links SET target_kind = 'event', target_id = ?, target_revision = 1 WHERE target_kind = 'capsule' AND target_id = ?", (event_id, cid))
        txn.execute("DELETE FROM evidence_capsules WHERE capsule_id = ?", (cid,))
    return sorted(found)


def capsule_targets(event_ids: Iterable[str]) -> dict[str, str]:
    """capsule ID -> event ID for these events (whether or not a capsule exists): for readers of normalized links."""
    return {capsule_id(e): e for e in event_ids}


__all__ = [
    "KIND", "CONTEXT_CODE_POINTS", "REASONS", "Resolution", "Outcome", "capsule_id", "load", "for_event", "origin_event", "origin_of", "existing", "stats",
    "find_span", "whole_statement", "covers", "typed_payload", "exact_slice", "resolve", "build", "compact", "drop", "capsule_targets",
]
