"""Task, episode and claim revisions with their heads and normalized links.

Revisions are immutable once committed (except explicit privacy purging); a
head table points at the current one. Every written revision also writes its
normalized ``evidence_links`` (and, for claims, ``dependencies``), which are
authoritative for pins and rendering. Callers hold the write transaction and
decide whether the change is serving-relevant (:meth:`Txn.mutated`).
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from recalith.contracts.common import EvidenceLink, RecordRef, canonical_json, digest_of
from recalith.contracts.memory import ClaimRevision, Episode, TaskState
from recalith.storage.db import Txn

REVISION_TABLES = {"task": ("task_revisions", "task_id"), "episode": ("episode_revisions", "episode_id"), "claim": ("claim_revisions", "claim_id")}
HEAD_TABLES = {"task": ("task_heads", "task_id"), "episode": ("episode_heads", "episode_id"), "claim": ("claim_heads", "claim_id")}
DTO = {"task": TaskState, "episode": Episode, "claim": ClaimRevision}


def head(q: Any, kind: str, record_id: str) -> tuple[int, str] | None:
    """(revision, status-or-state) of the current head, or None."""
    table, key = HEAD_TABLES[kind]
    column = "state" if kind == "episode" else "status"
    row = q.execute(f"SELECT revision, {column} FROM {table} WHERE {key} = ?", (record_id,)).fetchone()  # noqa: S608 - fixed names
    return None if row is None else (row[0], row[1])


def body(q: Any, kind: str, record_id: str, revision: int) -> dict[str, Any] | None:
    """A stored revision body; None when the revision is absent or its body was purged."""
    table, key = REVISION_TABLES[kind]
    row = q.execute(f"SELECT body FROM {table} WHERE {key} = ? AND revision = ?", (record_id, revision)).fetchone()  # noqa: S608
    if row is None or row[0] is None:
        return None
    return json.loads(row[0])


def revision_exists(q: Any, kind: str, record_id: str, revision: int) -> bool:
    table, key = REVISION_TABLES[kind]
    return q.execute(f"SELECT 1 FROM {table} WHERE {key} = ? AND revision = ?", (record_id, revision)).fetchone() is not None  # noqa: S608


def load(q: Any, kind: str, record_id: str, revision: int):
    data = body(q, kind, record_id, revision)
    return None if data is None else DTO[kind].model_validate_json(json.dumps(data))


def ref_of(record: TaskState | Episode | ClaimRevision) -> RecordRef:
    if isinstance(record, TaskState):
        return RecordRef(kind="task", id=record.task_id, revision=record.revision)
    if isinstance(record, Episode):
        return RecordRef(kind="episode", id=record.episode_id, revision=record.revision)
    return RecordRef(kind="claim", id=record.claim_id, revision=record.revision)


# --------------------------------------------------------------------------
# Claim identity


def content_key(claim: ClaimRevision) -> str | None:
    """Exact-duplicate key: kind, proposition, proposition key, scope and conditions."""
    if claim.proposition_key is None or not claim.proposition:
        return None
    return digest_of(
        {
            "kind": claim.kind,
            "proposition": claim.proposition,
            "proposition_key": claim.proposition_key.model_dump(mode="json"),
            "scope": claim.scope.model_dump(mode="json"),
            "conditions": sorted((c.model_dump(mode="json") for c in claim.conditions), key=lambda c: canonical_json(c)),
        }
    )


def link_identity(link: EvidenceLink) -> tuple:
    """A link's evidence-root identity: its roots when known, else its exact ref and locator."""
    if link.root_event_ids:
        return ("roots", tuple(sorted(link.root_event_ids)))
    return ("ref", link.ref.kind, link.ref.id, link.ref.revision, None if link.locator is None else canonical_json(link.locator))


def support_roots(claim: ClaimRevision) -> set[str]:
    return {root for link in claim.supports for root in link.root_event_ids}


# --------------------------------------------------------------------------
# Normalized links


def _walk_links(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("evidence"), list) and "text" in value and "basis" in value:
            yield from value["evidence"]
        for item in value.values():
            yield from _walk_links(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_links(item)


def _write_links(txn: Txn, owner: RecordRef, links: Iterable[EvidenceLink]) -> None:
    for link in links:
        txn.execute(
            "INSERT INTO evidence_links (owner_kind, owner_id, owner_revision, target_kind, target_id, target_revision, relation, root_event_ids, locator, mapping) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                owner.kind, owner.id, owner.revision, link.ref.kind, link.ref.id, link.ref.revision, link.relation,
                canonical_json(list(link.root_event_ids)).decode(), None if link.locator is None else canonical_json(link.locator).decode(), link.mapping,
            ),
        )


def _clear_links(txn: Txn, owner: RecordRef) -> None:
    txn.execute("DELETE FROM evidence_links WHERE owner_kind = ? AND owner_id = ? AND owner_revision = ?", (owner.kind, owner.id, owner.revision))


def _structured_links(data: dict[str, Any]) -> list[EvidenceLink]:
    return [EvidenceLink.model_validate(item) for item in _walk_links(data)]


# --------------------------------------------------------------------------
# Writers


def write_task(txn: Txn, state: TaskState, *, workspace_id: str) -> RecordRef:
    data = state.model_dump(mode="json")
    txn.execute(
        "INSERT INTO task_revisions (task_id, revision, status, body, created_store_revision) VALUES (?, ?, ?, ?, ?)",
        (state.task_id, state.revision, state.status, canonical_json(data).decode(), txn.next_store_revision),
    )
    txn.execute(
        "INSERT INTO task_heads (task_id, revision, status, workspace_id, redirect_task_id, last_activity_at) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(task_id) DO UPDATE SET revision = excluded.revision, status = excluded.status, redirect_task_id = excluded.redirect_task_id, last_activity_at = excluded.last_activity_at",
        (state.task_id, state.revision, state.status, workspace_id, state.redirect_task_id, state.last_activity_at),
    )
    ref = ref_of(state)
    _write_links(txn, ref, _structured_links(data))
    return ref


def task_workspace(q: Any, task_id: str) -> str | None:
    row = q.execute("SELECT workspace_id FROM task_heads WHERE task_id = ?", (task_id,)).fetchone()
    return None if row is None else row[0]


def write_episode(txn: Txn, episode: Episode) -> RecordRef:
    data = episode.model_dump(mode="json")
    txn.execute(
        "INSERT INTO episode_revisions (episode_id, revision, state, body, created_store_revision) VALUES (?, ?, ?, ?, ?)",
        (episode.episode_id, episode.revision, episode.state, canonical_json(data).decode(), txn.next_store_revision),
    )
    txn.execute(
        "INSERT INTO episode_heads (episode_id, revision, state, task_id) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(episode_id) DO UPDATE SET revision = excluded.revision, state = excluded.state, task_id = excluded.task_id",
        (episode.episode_id, episode.revision, episode.state, episode.task_id),
    )
    ref = ref_of(episode)
    sources = [EvidenceLink(ref=RecordRef(kind="event", id=e, revision=1), relation="context") for e in episode.source_event_ids]
    _write_links(txn, ref, [*_structured_links(data), *sources])
    return ref


def _claim_links(claim: ClaimRevision, context: Iterable[EvidenceLink]) -> list[EvidenceLink]:
    return [*claim.supports, *claim.contradicts, *context, *_structured_links({"procedure": claim.procedure.model_dump(mode="json") if claim.procedure else None, "failure": claim.failure.model_dump(mode="json") if claim.failure else None})]


def write_claim(txn: Txn, claim: ClaimRevision, *, context: Iterable[EvidenceLink] = ()) -> RecordRef:
    data = claim.model_dump(mode="json")
    txn.execute(
        "INSERT INTO claim_revisions (claim_id, revision, kind, status, body, created_store_revision) VALUES (?, ?, ?, ?, ?, ?)",
        (claim.claim_id, claim.revision, claim.kind, claim.status, canonical_json(data).decode(), txn.next_store_revision),
    )
    _claim_head(txn, claim)
    ref = ref_of(claim)
    _write_links(txn, ref, _claim_links(claim, context))
    _write_dependencies(txn, claim)
    return ref


def _claim_head(txn: Txn, claim: ClaimRevision) -> None:
    family = claim.failure.action_family_digest if claim.failure is not None else None
    txn.execute(
        "INSERT INTO claim_heads (claim_id, revision, kind, status, freshness, strength, basis, review_due_at, action_family_digest, content_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(claim_id) DO UPDATE SET revision = excluded.revision, kind = excluded.kind, status = excluded.status, freshness = excluded.freshness, strength = excluded.strength, "
        "basis = excluded.basis, review_due_at = excluded.review_due_at, action_family_digest = excluded.action_family_digest, content_key = excluded.content_key",
        (claim.claim_id, claim.revision, claim.kind, claim.status, claim.freshness, claim.strength, claim.basis, claim.review_due_at, family, content_key(claim)),
    )


def _write_dependencies(txn: Txn, claim: ClaimRevision) -> None:
    for dep in claim.dependencies:
        txn.execute(
            "INSERT INTO dependencies (claim_id, claim_revision, kind, key, fingerprint, record_id, record_revision) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (claim.claim_id, claim.revision, dep.kind, dep.key, dep.fingerprint, dep.record.id if dep.record else None, dep.record.revision if dep.record else None),
        )


def write(txn: Txn, kind: str, record: Any, *, workspace_id: str | None = None) -> RecordRef:
    if kind == "task":
        assert workspace_id is not None
        return write_task(txn, record, workspace_id=workspace_id)
    if kind == "episode":
        return write_episode(txn, record)
    return write_claim(txn, record)


def duplicate_heads(q: Any, key: str) -> list[ClaimRevision]:
    """Current, servable claim heads with this exact content key."""
    rows = q.execute("SELECT claim_id, revision FROM claim_heads WHERE content_key = ? AND status IN ('candidate', 'active', 'disputed') ORDER BY claim_id", (key,)).fetchall()
    return [c for c in (load(q, "claim", r[0], r[1]) for r in rows) if c is not None]


# --------------------------------------------------------------------------
# Relations


def add_relation(txn: Txn, source_id: str, target_id: str, relation: str) -> bool:
    if txn.one("SELECT 1 FROM relations WHERE source_id = ? AND target_id = ? AND relation = ?", (source_id, target_id, relation)) is not None:
        return False
    txn.execute("INSERT INTO relations (source_id, target_id, relation, created_revision) VALUES (?, ?, ?, ?)", (source_id, target_id, relation, txn.next_store_revision))
    return True


def remove_relation(txn: Txn, source_id: str, target_id: str, relation: str) -> bool:
    cur = txn.execute("DELETE FROM relations WHERE source_id = ? AND target_id = ? AND relation = ?", (source_id, target_id, relation))
    return cur.rowcount > 0
