"""The lexical lookup projection behind the hook's prompt context (SYSTEM_SPEC §5.1.1; DATA_CONTRACTS §10; decision 0021).

Views hold a query-independent slice; a prompt-specific fact outside it never
reached the stdlib hook (decision 0020 item 15). This projection gives the
hook a bounded, query-dependent input it can read with the standard library
(:mod:`recalith.fast.lookup`): per workspace, one pre-rendered candidate row
for every live claim head (``lookup_candidates``, the primitive form views
carry, or a null body when the claim is not servable there) and one posting
per term of a servable row (``lookup_postings``; the candidate's own
``terms``, so the hook and the indexer share one tokenizer).

:func:`refresh` reconciles it in the worker's projection step whenever its
recorded epochs differ from the store's. In one read snapshot it finds what
is owed: missing rows; rows at another revision, environment digest or
policy revision; rows of heads that are no longer live (deleted); and
*volatile* rows rendered at an older guidance epoch: content that can change
without a new claim revision (a disputed claim's quoted evidence, pending
recheck text, claim-dependency values, a claim not servable when rendered).
Bound tasks are stored scope-only; the hook re-reads bindings live.
It renders at most :data:`BATCH` owed claims in that snapshot, outside the
write lock, then writes them in one short transaction that first re-reads
the epochs: if they moved, the batch is discarded (``lookup_retry``) so a
forget, expiry or correction committed in between is never overwritten by
older content. The epochs are recorded only when nothing remains owed.
Nothing here advances the store revision or the guidance epoch, calls a
model or touches the network. :func:`purge` (forgetting) and :func:`reset`
(restore) remove rows with the records they render.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from recalith.capture import provenance
from recalith.contracts.common import InstallationContext, canonical_json, utc_now
from recalith.fast import failpoints
from recalith.fast import lookup as fl
from recalith.retrieval import index, search
from recalith.storage import records
from recalith.storage.db import Store, Txn

BATCH = 512
DELETE_BATCH = 4096
EPOCHS = ("guidance_epoch", "policy_revision", "tombstone_epoch")


@dataclass
class Plan:
    """One reconciliation batch, rendered from a read snapshot (``meta`` are its epochs)."""

    meta: dict[str, int]
    deletes: list[tuple[str, str]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    remaining: int = 0


def epochs(meta: dict[str, int]) -> tuple[int, int, int]:
    return tuple(meta[k] for k in EPOCHS)  # type: ignore[return-value]


def due(q: Any, meta: dict[str, int]) -> bool:
    """The projection is behind the epochs (never built, or not complete at the current ones)."""
    state = index.state(q)
    return state is None or (state["lookup_guidance"], state["lookup_policy"], state["lookup_tombstone"]) != epochs(meta)


def _quoted(q: Any, claim: Any) -> dict[str, str | None]:
    """Events a disputed candidate's text quotes (``search._link_summary`` of two supports and two contradictions), with their payload states."""
    if claim.status != "disputed":
        return {}
    events = sorted({link.ref.id for link in [*claim.supports[:2], *claim.contradicts[:2]] if link.ref.kind == "event"})
    if not events:
        return {}
    marks = ",".join("?" for _ in events)
    states = dict(q.execute(f"SELECT event_id, payload_state FROM events WHERE event_id IN ({marks})", tuple(events)).fetchall())  # noqa: S608
    return {e: states.get(e) for e in events}


def _cited(cand: dict[str, Any] | None, quoted: dict[str, Any]) -> list[str]:
    """Every ID a row's content derives from besides its claim: what tombstones and forgetting must find."""
    ids = set(quoted)
    if cand is not None:
        ids |= set(cand.get("support_events") or ())
        ids |= {r["id"] for r in cand.get("evidence_refs") or []}
        ids |= {v["record_id"] for v in (cand.get("claim_values") or {}).values() if v.get("record_id")}
        ids.discard(cand["ref"]["id"])
    return sorted(ids)


def plan(q: Any, ctx: InstallationContext, meta: dict[str, int]) -> Plan:
    """What is owed, and at most :data:`BATCH` of it rendered, from the read snapshot ``q`` (no write)."""
    heads = {r[0]: (r[1], r[2], r[3]) for r in q.execute("SELECT claim_id, revision, status, freshness FROM claim_heads WHERE status IN ('candidate', 'active', 'disputed')").fetchall()}
    existing = {(r[0], r[1]): r[2:] for r in q.execute("SELECT workspace_id, claim_id, claim_revision, environment_digest, policy_revision, guidance_epoch, volatile FROM lookup_candidates").fetchall()}
    workspaces = [r[0] for r in q.execute("SELECT workspace_id FROM workspaces ORDER BY workspace_id").fetchall()]
    known = set(workspaces)
    deletes = sorted(key for key in existing if key[0] not in known or key[1] not in heads)
    owed: list[tuple[str, str, dict[str, str], str]] = []
    for workspace_id in workspaces:
        environment = provenance.environment_values_in(q, ctx, workspace_id=workspace_id)
        digest = fl.environment_digest(environment)
        for claim_id in sorted(heads):
            row = existing.get((workspace_id, claim_id))
            if (row is None or row[0] != heads[claim_id][0] or row[1] != digest or row[2] != meta["policy_revision"]
                    or (row[4] and row[3] != meta["guidance_epoch"])):
                owed.append((workspace_id, claim_id, environment, digest))
    out = Plan(meta, deletes=deletes[:DELETE_BATCH], remaining=max(0, len(deletes) - DELETE_BATCH) + max(0, len(owed) - BATCH))
    for workspace_id, claim_id, environment, digest in owed[:BATCH]:
        revision, status, freshness = heads[claim_id]
        claim = records.load(q, "claim", claim_id, revision)
        cand = search.servable_candidate(q, ctx, claim, environment=environment, workspace_id=workspace_id) if claim is not None else None
        if cand is not None:
            cand["task_ids"] = sorted(set(cand["scope"].get("task_ids") or ()))  # bindings change without a revision: the hook re-reads them live
        quoted = _quoted(q, claim) if claim is not None else {}
        volatile = cand is None or status == "disputed" or freshness != "current" or bool(cand.get("claim_values"))
        out.rows.append({
            "workspace_id": workspace_id, "claim_id": claim_id, "revision": revision, "digest": digest, "volatile": int(volatile),
            "cand": cand, "cited": _cited(cand, quoted), "quoted": quoted,
        })
    return out


def _delete(txn: Txn, workspace_id: str, claim_id: str) -> None:
    txn.execute("DELETE FROM lookup_postings WHERE workspace_id = ? AND claim_id = ?", (workspace_id, claim_id))
    txn.execute("DELETE FROM lookup_candidates WHERE workspace_id = ? AND claim_id = ?", (workspace_id, claim_id))


def _insert(txn: Txn, row: dict[str, Any], meta: dict[str, int]) -> None:
    cand = row["cand"]
    txn.execute(
        "INSERT INTO lookup_candidates (workspace_id, claim_id, claim_revision, environment_digest, volatile, guidance_epoch, policy_revision, tombstone_epoch, cited_ids, quoted_states, body) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["workspace_id"], row["claim_id"], row["revision"], row["digest"], row["volatile"], meta["guidance_epoch"], meta["policy_revision"], meta["tombstone_epoch"],
         canonical_json(row["cited"]).decode(), canonical_json(row["quoted"]).decode(), canonical_json(cand).decode() if cand is not None else None),
    )
    if cand is not None:
        terms = list(dict.fromkeys(cand.get("terms") or ()))
        for term in terms:
            txn.execute("INSERT INTO lookup_postings (workspace_id, term, base, claim_id) VALUES (?, ?, ?, ?)", (row["workspace_id"], term, float(cand.get("base", 0.0)), row["claim_id"]))


def _record(txn: Txn, meta: dict[str, int] | None, now: str) -> None:
    values = epochs(meta) if meta is not None else (-1, -1, -1)
    txn.execute(
        "INSERT INTO projection_state (singleton, lexical_backend, lookup_guidance_epoch, lookup_policy_revision, lookup_tombstone_epoch, updated_at) VALUES (1, ?, ?, ?, ?, ?) "
        "ON CONFLICT(singleton) DO UPDATE SET lookup_guidance_epoch = excluded.lookup_guidance_epoch, lookup_policy_revision = excluded.lookup_policy_revision, "
        "lookup_tombstone_epoch = excluded.lookup_tombstone_epoch, updated_at = excluded.updated_at",
        (index.backend_for(None), *values, now),
    )


def refresh(store: Store, ctx: InstallationContext, *, now: str | None = None) -> dict[str, int]:
    """One bounded reconciliation step: ``{"lookup": rows written or deleted}``, ``{"lookup_retry": 1}`` or ``{}`` (nothing due)."""
    with store.read() as q:
        meta = search.meta_of(q)
        if not due(q, meta):
            return {}
        work = plan(q, ctx, meta)
    with store.transaction() as txn:
        if epochs(search.meta_of(txn)) != epochs(work.meta):
            return {"lookup_retry": 1}  # the store moved since the read: never write older content over it
        for workspace_id, claim_id in work.deletes:
            _delete(txn, workspace_id, claim_id)
        for row in work.rows:
            _delete(txn, row["workspace_id"], row["claim_id"])
            _insert(txn, row, work.meta)
        if work.remaining == 0:
            _record(txn, work.meta, now or utc_now())
        failpoints.hit(failpoints.LOOKUP_BEFORE_COMMIT)
    failpoints.hit(failpoints.LOOKUP_AFTER_PUBLISH)
    done = len(work.deletes) + len(work.rows)
    return {"lookup": done} if done else {}


def purge(txn: Txn, ids: set[str]) -> int:
    """Forgetting, inside the purge transaction: every row of a purged record and every row citing one; the projection is owed again."""
    doomed = [(ws, cid) for ws, cid, cited in txn.execute("SELECT workspace_id, claim_id, cited_ids FROM lookup_candidates").fetchall() if cid in ids or ids.intersection(json.loads(cited))]
    for workspace_id, claim_id in doomed:
        _delete(txn, workspace_id, claim_id)
    if txn.one("SELECT 1 FROM projection_state WHERE singleton = 1") is not None:
        _record(txn, None, utc_now())
    return len(doomed)


def reset(txn: Txn) -> None:
    """Restore: the projection is rebuilt from the restored heads after the swap."""
    txn.execute("DELETE FROM lookup_postings")
    txn.execute("DELETE FROM lookup_candidates")


def rows(store: Store) -> list[dict[str, Any]]:
    """Lookup rows and their postings (tests and health)."""
    with store.read() as view:
        out = [{"workspace_id": r[0], "claim_id": r[1], "claim_revision": r[2], "volatile": r[3], "body": json.loads(r[4]) if r[4] else None}
               for r in view.execute("SELECT workspace_id, claim_id, claim_revision, volatile, body FROM lookup_candidates ORDER BY workspace_id, claim_id").fetchall()]
    return out


__all__ = ["BATCH", "DELETE_BATCH", "Plan", "due", "plan", "refresh", "purge", "reset", "rows"]
