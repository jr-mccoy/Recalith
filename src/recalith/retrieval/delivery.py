"""Delivery accounting: service receipts, receipt ingestion and outcome links (SYSTEM_SPEC §5.1.2, §8.2–§8.3; DATA_CONTRACTS §9–§11; decision 0015).

Hooks never write SQLite. Every delivery, from the hook's delivery branch
(:mod:`recalith.fast.delivery`) or from :func:`record_delivery`, reaches the
store as a spooled ``memory_delivered`` event (memory channel, derived
authority, no root): telemetry, never support. Ingestion calls
:func:`account` inside the event's own transaction:

* one ``deliveries`` row per attempt: an emitted receipt upgrades an
  uncertain row of the same attempt; an uncertain receipt never downgrades an
  emitted one; a repeated receipt is a duplicate event and changes nothing.
  So an attempt is charged exactly once, and only an emitted receipt is
  evidence of local stdout emission (never of model consumption);
* bookkeeping only: the store revision advances, the guidance epoch does not,
  so packets and views stay valid (A41);
* :func:`link_outcomes` records observed follow-up events of an emitted
  delivery: the finished tool call its pre-action delivery preceded, and an
  assistant message citing an emitted record. Labels come only from observed,
  certified evidence (a test action's certified result); an acknowledgment is
  labeled ``acknowledged`` and is never support, corroboration or task
  success. Links change no claim.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from recalith.capture import pipeline
from recalith.capture.normalize import RawEvent, normalize_event
from recalith.contracts.common import InstallationContext, derived_id, digest_of, new_id, utc_now
from recalith.contracts.context import ContextPacket, DeliveryReceipt, EmittedItem
from recalith.contracts.events import EventEnvelope
from recalith.errors import RecalithError
from recalith.fast import context as fc

SERVICE_HOST = "recalith_service"
ACK_WINDOW = 8
_RECORD_ID = re.compile(r"\b(?:claim|task|ep)_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")


# --------------------------------------------------------------------------
# Service receipts (DATA_CONTRACTS §11 ``record_delivery``)


def item_condition_digest(item: dict[str, Any]) -> str:
    """The service's suppression digest when the caller supplies none: what the item says it was decided under."""
    return digest_of(["service_item", item["advice"], item["applicability"], item["freshness"], item.get("conditions_text"), item["why"][0]])


def record_delivery(
    ctx: InstallationContext,
    packet: ContextPacket,
    session_id: str,
    *,
    emitted: bool = True,
    condition_digests: list[str] | None = None,
    host_id: str = SERVICE_HOST,
    host_session_id: str | None = None,
    task_id: str | None = None,
    attempt_id: str | None = None,
    restoration_key: str | None = None,
    trigger_event_id: str | None = None,
) -> DeliveryReceipt:
    """Serialize a receipt for a packet the caller delivered (or attempted) and spool it; ingestion owns the row.

    Raises ``not_captured`` when the receipt could not be made durable (the
    caller keeps the delivery charged and may retry with the same
    ``attempt_id``: the event key names the attempt, so a retry is a
    duplicate, never a second charge).
    """
    data = packet.model_dump(mode="json")
    if packet.installation_id != ctx.installation_id or packet.project_id != ctx.project_id:
        raise RecalithError("foreign_installation", "the packet belongs to another installation")
    digests = condition_digests if condition_digests is not None else [item_condition_digest(i) for i in data["items"]]
    if len(digests) != len(data["items"]):
        raise RecalithError("invalid_schema", "one condition digest per packet item")
    attempt_id = attempt_id or new_id("att")
    now = utc_now()
    receipt = DeliveryReceipt(
        delivery_id="dlv_" + attempt_id.split("_", 1)[1], attempt_id=attempt_id, host_id=host_id, session_id=session_id, task_id=task_id,
        packet_digest=digest_of(data), items=[EmittedItem(record_id=i["ref"]["id"], revision=i["ref"]["revision"], condition_digest=d) for i, d in zip(data["items"], digests, strict=True)],
        purpose=packet.purpose, fence_store_revision=packet.store_revision, guidance_epoch=packet.guidance_epoch, policy_revision=packet.policy_revision,
        tombstone_epoch=packet.tombstone_epoch, generated_at=packet.generated_at, emitted_at=now if emitted else None, estimated_tokens=packet.estimated_tokens,
        pre_action_substitution_tokens=packet.pre_action_substitution_tokens, state="emitted" if emitted else "uncertain",
        restoration_key=restoration_key, trigger_event_id=trigger_event_id,
    )
    raw = RawEvent(
        adapter_id=host_id, adapter_version="service", source_event_key=f"delivery:{attempt_id}:{receipt.state}", session_id=session_id,
        host_session_id=host_session_id or session_id, kind="memory_delivered", payload=receipt.model_dump(mode="json"), origin_kind="service",
    )
    envelopes, _notes = normalize_event(ctx, raw)
    capture = pipeline.capture(ctx, envelopes)
    if capture.status != "accepted":
        raise RecalithError("not_captured", "the delivery receipt was not made durable")
    return receipt


# --------------------------------------------------------------------------
# Ingestion (inside the receipt event's transaction)


def account(txn: Any, ctx: InstallationContext, env: EventEnvelope, *, now: str) -> str:
    """Account one ingested ``memory_delivered`` receipt; returns ``inserted|upgraded|unchanged|invalid``."""
    try:
        receipt = DeliveryReceipt.model_validate(env.payload)
    except ValidationError:
        return "invalid"  # a malformed receipt stays an event; it charges nothing it cannot prove
    if receipt.session_id != env.session_id or receipt.delivery_id != "dlv_" + receipt.attempt_id.split("_", 1)[1]:
        return "invalid"
    items = json.dumps([i.model_dump(mode="json") for i in receipt.items], sort_keys=True, separators=(",", ":"))
    row = txn.one("SELECT state FROM deliveries WHERE attempt_id = ?", (receipt.attempt_id,))
    if row is None:
        txn.execute(
            "INSERT INTO deliveries (delivery_id, attempt_id, session_id, task_id, purpose, state, packet_digest, fence_store_revision, guidance_epoch, policy_revision, "
            "tombstone_epoch, estimated_tokens, substitution_tokens, generated_at, emitted_at, items, host_id, restoration_key, trigger_event_id, fenced_at, in_flight_change, receipt_event_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (receipt.delivery_id, receipt.attempt_id, receipt.session_id, receipt.task_id, receipt.purpose, receipt.state, receipt.packet_digest, receipt.fence_store_revision,
             receipt.guidance_epoch, receipt.policy_revision, receipt.tombstone_epoch, receipt.estimated_tokens, receipt.pre_action_substitution_tokens, receipt.generated_at,
             receipt.emitted_at, items, receipt.host_id, receipt.restoration_key, receipt.trigger_event_id, receipt.fenced_at,
             None if receipt.in_flight_change is None else int(receipt.in_flight_change), env.event_id),
        )
        outcome = "inserted"
    elif row[0] == "uncertain" and receipt.state == "emitted":
        txn.execute(
            "UPDATE deliveries SET state = 'emitted', emitted_at = ?, fenced_at = ?, in_flight_change = ?, receipt_event_id = ? WHERE attempt_id = ?",
            (receipt.emitted_at, receipt.fenced_at, None if receipt.in_flight_change is None else int(receipt.in_flight_change), env.event_id, receipt.attempt_id),
        )
        outcome = "upgraded"
    else:
        return "unchanged"  # an uncertain receipt never downgrades an emitted attempt; the charge is already counted
    txn.mutated(serving_relevant=False)  # bookkeeping: the guidance epoch does not move
    if receipt.state == "emitted" and receipt.trigger_event_id:
        finish = _finish_of(ctx, env.adapter_id, receipt.trigger_event_id, txn)
        if finish is not None:
            _link_tool(txn, receipt.delivery_id, finish, now=now)
    return outcome


def _start_key_of(source_event_key: str) -> str | None:
    return source_event_key[: -len(":finish")] + ":start" if source_event_key.endswith(":finish") else None


def _finish_of(ctx: InstallationContext, adapter_id: str, start_event_id: str, txn: Any) -> tuple | None:
    row = txn.one("SELECT source_event_key FROM events WHERE event_id = ?", (start_event_id,))
    if row is None or not row[0].endswith(":start"):
        return None
    finish_id = derived_id("evt", [ctx.installation_id, adapter_id, row[0][: -len(":start")] + ":finish"])
    found = txn.one("SELECT event_id, payload FROM events WHERE event_id = ?", (finish_id,))
    return None if found is None else (found[0], json.loads(found[1]))


def observed_label(payload: dict[str, Any]) -> str:
    """Only a certified result of a test action labels the follow-up; anything else stays ``unknown``."""
    action = payload.get("action") or {}
    if action.get("action_kind") != "test" or not payload.get("result_received"):
        return "unknown"
    verdicts = [a.get("passed") for a in payload.get("assertions") or [] if a.get("kind") == "test_result" and a.get("passed") is not None]
    codes = [a.get("value") for a in payload.get("assertions") or [] if a.get("kind") == "exit_status"]
    if payload.get("outcome") == "failure" and (False in verdicts or any(c not in ("0", None) for c in codes)):
        return "task_failed"
    if payload.get("outcome") == "success" and verdicts and all(verdicts):
        return "task_succeeded"
    return "unknown"


def _link_tool(txn: Any, delivery_id: str, finish: tuple, *, now: str) -> None:
    event_id, payload = finish
    txn.execute(
        "INSERT OR IGNORE INTO outcome_links (delivery_id, label, observed_event_ids, created_at) VALUES (?, ?, ?, ?)",
        (delivery_id, observed_label(payload), json.dumps([event_id]), now),
    )


def link_outcomes(txn: Any, ctx: InstallationContext, env: EventEnvelope, *, now: str) -> int:
    """Observed follow-up events of earlier emitted deliveries (no claim, strength or root changes)."""
    linked = 0
    if env.kind == "tool_finished":
        start_key = _start_key_of(env.source_event_key)
        if start_key is not None:
            start_id = derived_id("evt", [ctx.installation_id, env.adapter_id, start_key])
            for (delivery_id,) in txn.execute("SELECT delivery_id FROM deliveries WHERE trigger_event_id = ? AND state = 'emitted'", (start_id,)).fetchall():
                _link_tool(txn, delivery_id, (env.event_id, env.payload), now=now)
                linked += 1
    elif env.kind == "assistant_message":
        cited = set(_RECORD_ID.findall(str(env.payload.get("text") or "")))
        if cited:
            rows = txn.execute(
                "SELECT delivery_id, items FROM deliveries WHERE session_id = ? AND state = 'emitted' ORDER BY rowid DESC LIMIT ?", (env.session_id, ACK_WINDOW)
            ).fetchall()
            for delivery_id, items in rows:
                if cited & {i.get("record_id") for i in json.loads(items)}:
                    # Agent acknowledgment: telemetry only, never independent support or task success.
                    txn.execute(
                        "INSERT OR IGNORE INTO outcome_links (delivery_id, label, observed_event_ids, created_at) VALUES (?, 'acknowledged', ?, ?)",
                        (delivery_id, json.dumps([env.event_id]), now),
                    )
                    linked += 1
    return linked


# --------------------------------------------------------------------------
# Inspection (tests, health inputs for Task 17)


def session_accounting(view: Any, session_id: str) -> dict[str, Any]:
    """Durable totals for one session: charged, emitted, uncertain and restoration tokens, attempts by state."""
    rows = view.execute("SELECT state, estimated_tokens, restoration_key, in_flight_change FROM deliveries WHERE session_id = ?", (session_id,)).fetchall()
    out = {"attempts": len(rows), "charged": 0, "emitted": 0, "uncertain": 0, "restoration": 0, "ordinary": 0, "in_flight_changes": 0}
    for state, tokens, key, in_flight in rows:
        out["charged"] += tokens
        out[state] += tokens
        out["restoration" if key else "ordinary"] += tokens
        out["in_flight_changes"] += int(bool(in_flight))
    return out


def estimate_matches(packet: dict[str, Any]) -> bool:
    """The packet's estimate is exactly the rendered text's (helper for tests and diagnostics)."""
    return not packet["items"] or packet["estimated_tokens"] == fc.estimate_tokens(fc.render_packet(packet["purpose"], packet["items"]))
