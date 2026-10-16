"""Installation-local repository operations.

Every write verifies that the record belongs to the resolved installation
(A04): an event, operation or import payload naming another installation or
project is ``foreign_installation`` on ordinary paths. Queries are scoped to
this installation's database, so another installation's records are never
visible (A01). Explicit import-origin remapping is a full-release feature.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from recalith.contracts.common import Actor, InstallationContext, canonical_json, derived_id, new_id, utc_now
from recalith.contracts.events import EventEnvelope
from recalith.errors import RecalithError
from recalith.storage.db import Store, Txn

InsertOutcome = Literal["inserted", "duplicate", "conflict"]


def assert_owned(ctx: InstallationContext, *, project_id: str, installation_id: str) -> None:
    if installation_id != ctx.installation_id or project_id != ctx.project_id:
        raise RecalithError("foreign_installation", "record names another installation or project")


def registered_workspace(txn: Txn, workspace_id: str) -> bool:
    return txn.one("SELECT 1 FROM workspaces WHERE workspace_id = ? AND attachment_state IN ('primary', 'attached')", (workspace_id,)) is not None


def insert_event(txn: Txn, ctx: InstallationContext, envelope: EventEnvelope) -> tuple[InsertOutcome, str]:
    """Persist one normalized event exactly once.

    Same adapter/source key and digest is a duplicate (no new row, no new
    support). Same key with a different digest keeps the original event
    unchanged and records one ``source_conflicts`` row per distinct digest.
    Returns the outcome and the event or conflict ID.
    """
    assert_owned(ctx, project_id=envelope.project_id, installation_id=envelope.installation_id)
    if not registered_workspace(txn, envelope.workspace_id):
        raise RecalithError("foreign_installation", "event names a workspace not registered in this installation")
    expected_id = derived_id("evt", [ctx.installation_id, envelope.adapter_id, envelope.source_event_key])
    if envelope.event_id != expected_id:
        raise RecalithError("event_identity_conflict", "event id is not derived from this installation's source identity")
    existing = txn.one("SELECT event_id, payload_digest FROM events WHERE adapter_id = ? AND source_event_key = ?", (envelope.adapter_id, envelope.source_event_key))
    if existing is not None:
        if existing[1] == envelope.payload_digest:
            return "duplicate", existing[0]
        conflict_id = derived_id("conf", [ctx.installation_id, envelope.adapter_id, envelope.source_event_key, envelope.payload_digest])
        if txn.one("SELECT 1 FROM source_conflicts WHERE conflict_id = ?", (conflict_id,)) is None:
            txn.execute(
                "INSERT INTO source_conflicts (conflict_id, original_event_id, adapter_id, source_event_key, payload_digest, scrubbed_payload, coverage, first_seen_at, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unresolved')",
                (conflict_id, existing[0], envelope.adapter_id, envelope.source_event_key, envelope.payload_digest, canonical_json(envelope.payload).decode(), canonical_json(envelope.coverage).decode(), utc_now()),
            )
            txn.mutated(serving_relevant=True)  # dependent guidance must stop treating the source as settled
        return "conflict", conflict_id
    seq_row = txn.one("SELECT COALESCE(MAX(commit_sequence), 0) + 1 FROM events")
    body = envelope.model_dump(mode="json")
    payload = body.pop("payload")
    txn.execute(
        "INSERT INTO events (event_id, adapter_id, source_event_key, payload_digest, source_sequence, commit_sequence, kind, channel, authority, session_id, workspace_id, task_hint, occurred_at, recorded_at, envelope, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            envelope.event_id, envelope.adapter_id, envelope.source_event_key, envelope.payload_digest, envelope.source_sequence, seq_row[0],
            envelope.kind, envelope.channel, envelope.authority, envelope.session_id, envelope.workspace_id, envelope.task_id,
            envelope.occurred_at, envelope.recorded_at, canonical_json(body).decode(), canonical_json(payload).decode(),
        ),
    )
    txn.mutated(serving_relevant=False)
    return "inserted", envelope.event_id


def get_event(store: Store, event_id: str) -> EventEnvelope | None:
    with store.read() as view:
        row = view.execute("SELECT envelope, payload, payload_state FROM events WHERE event_id = ?", (event_id,)).fetchone()
    if row is None:
        return None
    if row[2] != "available" or row[1] is None:
        raise RecalithError("capability_unavailable", f"event payload is {row[2]}")
    body = json.loads(row[0])
    body["payload"] = json.loads(row[1])
    return EventEnvelope.model_validate_json(json.dumps(body))


def count_rows(store: Store, table: str) -> int:
    if table not in {"events", "source_conflicts", "workspaces", "operations"}:
        raise ValueError("unsupported table")
    with store.read() as view:
        return view.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608 - allowlisted


def record_operation(txn: Txn, *, actor: Actor, kind: str, inputs: dict[str, Any], changed: list[dict[str, Any]], reason: str | None, job_id: str | None = None, causal_root: str | None = None) -> str:
    operation_id = new_id("op")
    txn.execute(
        "INSERT INTO operations (operation_id, job_id, actor, kind, inputs, changed, reason, causal_root, store_revision, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (operation_id, job_id, canonical_json(actor).decode(), kind, canonical_json(inputs).decode(), canonical_json(changed).decode(), reason, causal_root, txn.next_store_revision, utc_now()),
    )
    return operation_id
