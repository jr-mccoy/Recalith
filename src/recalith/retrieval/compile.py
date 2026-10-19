"""Context packets, pre-serialized views and the worker's projection step (SYSTEM_SPEC §5.1.1, §8.2–§8.3; DATA_CONTRACTS §9–§11; decision 0013).

:func:`compile_context` (DATA_CONTRACTS §11) gathers in one read snapshot
(:func:`recalith.retrieval.search.gather`), fits the exact budget
(``ceil(UTF-8 bytes / 3)`` of the rendered packet; start 2,000, prompt 1,000,
pre-action 400, restoration 2,000, the one shared 400 substitution allowance)
and validates the packet at a **final read-only fence**: a fresh snapshot
whose guidance, policy and tombstone epochs must still equal the gathered
snapshot's. Every change to servable state advances the guidance epoch in its
own transaction, so a correction, forget, recheck or retirement committed
before the fence excludes the old guidance: the packet is recompiled once,
and a second change returns an empty, degraded packet, never old guidance.
Receipt, queue and lease bookkeeping advance only the store revision and
leave packets and views valid.

:func:`refresh_projection` is the worker's deterministic projection step
(every poll, no model, no budget). It keeps the lexical/structural index at
the store revision (:func:`recalith.retrieval.index.refresh`) and, when the
guidance, policy or tombstone epoch moved, republishes the bounded
``context_views`` the stdlib hook compiler reads: per workspace and for the
workspace's most recently active tasks, one view per purpose holding ranked,
pre-rendered candidates with their scope, conditions, precomputed version
results (with the exact consulted value digest), dependencies, evidence and
action family; and up to 128 ranked fallback rows the hook may filter live
(at most 32 per compile). Views, their epochs and the projection state are
written in one transaction that reads the records it renders, so a view can
never carry content older than the epochs it is labeled with. Projection
writes never advance the store revision or the guidance epoch.
"""

from __future__ import annotations

import json
from typing import Any

from recalith.capture import provenance
from recalith.contracts.common import InstallationContext, canonical_json, utc_now
from recalith.contracts.context import ContextPacket, ContextQuery
from recalith.fast import context as fc
from recalith.fast import failpoints
from recalith.retrieval import index, search
from recalith.storage import records
from recalith.storage.db import Store, open_store

VIEW_SCHEMA = 1
VIEW_PURPOSES = ("session_start", "prompt", "pre_action", "compact_restore")
VIEW_TASKS = 4
VIEW_ITEMS = {"session_start": 48, "prompt": 48, "pre_action": 24, "compact_restore": 48}
ACTION_CLAIMS = 64
TOP_CLAIMS = 32
DISPUTED = 8
FALLBACK_STORED = 128
FENCE_ATTEMPTS = 2


# --------------------------------------------------------------------------
# Service compilation


def _hook_ctx(ctx: InstallationContext) -> dict[str, Any]:
    return {"project_id": ctx.project_id, "installation_id": ctx.installation_id, "policy_revision": ctx.policy_revision}


def compile_context(ctx: InstallationContext, query: ContextQuery, *, store: Store | None = None, substitute_pre_action: bool = False) -> ContextPacket:
    """DATA_CONTRACTS §11: a bounded, explained, fenced packet of current context."""
    own = store is None
    store = store or open_store(ctx, readonly=True)
    try:
        reasons: list[str] = []
        for _attempt in range(FENCE_ATTEMPTS):
            with store.read() as view:
                gathered = search.gather(view, ctx, query)
            assembled = fc.assemble(query.purpose, [e["item"] for e in gathered.entries], max_estimated_tokens=query.max_estimated_tokens, substitute_pre_action=substitute_pre_action)
            assembled["omitted_count"] += gathered.cut
            with store.read() as fresh:  # the final fence: a fresh snapshot, never the gathering one
                now_meta = search.meta_of(fresh)
            if all(now_meta[k] == gathered.meta[k] for k in ("guidance_epoch", "policy_revision", "tombstone_epoch")):
                return ContextPacket.model_validate(fc.packet(_hook_ctx(ctx), query.purpose, gathered.meta, assembled, [*reasons, *gathered.degraded]))
            reasons.append("fence_recompiled")
        return ContextPacket.model_validate(fc.empty_packet(_hook_ctx(ctx), query.purpose, now_meta, ["fence_epoch_changed"]))
    finally:
        if own:
            store.close()


# --------------------------------------------------------------------------
# View publication


def view_id(workspace_id: str, task_id: str | None, purpose: str) -> str:
    return f"view:{workspace_id}:{task_id or '-'}:{purpose}"


def fallback_id(workspace_id: str, rank: int, record_id: str) -> str:
    return f"fallback:{workspace_id}:{rank:04d}:{record_id}"


def _claim_rows(q: Any, sql: str, params: tuple) -> list[str]:
    return [r[0] for r in q.execute(sql, params).fetchall()]


STRENGTH_ORDER = "CASE strength WHEN 'corroborated' THEN 0 WHEN 'supported' THEN 1 ELSE 2 END"


def _view_tasks(q: Any, workspace_id: str) -> list[str]:
    return _claim_rows(q, "SELECT task_id FROM task_heads WHERE workspace_id = ? AND status IN ('active', 'paused') ORDER BY last_activity_at DESC, task_id LIMIT ?", (workspace_id, VIEW_TASKS))


def _actionable(cand: dict[str, Any]) -> bool:
    return bool(cand.get("family") or any(c["kind"] in ("action_kind", "tool", "path") for c in cand.get("conditions") or []) or (cand.get("scope") or {}).get("paths")
                or any(d["kind"] == "file" for d in cand.get("dependencies") or []))


class _Cands:
    """Claim candidates built once per publication (one snapshot)."""

    def __init__(self, q: Any, ctx: InstallationContext, environment: dict[str, str]) -> None:
        self.q, self.ctx, self.environment = q, ctx, environment
        self.cache: dict[str, dict[str, Any] | None] = {}

    def get(self, claim_id: str) -> dict[str, Any] | None:
        if claim_id not in self.cache:
            head = records.head(self.q, "claim", claim_id)
            claim = records.load(self.q, "claim", claim_id, head[0]) if head is not None and head[1] in fc.LIVE else None
            cand = search.claim_candidate(self.q, self.ctx, claim, environment=self.environment) if claim is not None else None
            if cand is not None and cand.get("evidence") not in fc.SUFFICIENT_EVIDENCE:
                cand = None  # never pre-serialized: expired/redacted support stays out of automatic context
            self.cache[claim_id] = cand
        return self.cache[claim_id]


def _in_scope(cand: dict[str, Any], workspace_id: str, task_id: str | None) -> bool:
    scope = cand.get("scope") or {}
    if scope.get("workspace_ids") and workspace_id not in scope["workspace_ids"]:
        return False
    if scope.get("task_ids") and task_id is not None and task_id not in scope["task_ids"]:
        return False
    return True


def _view_candidates(q: Any, ctx: InstallationContext, cands: _Cands, workspace_id: str, task_id: str | None, purpose: str, *, shared: dict[str, list[str]], questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    members = {m for qc in questions for m in qc["members"]}
    claim_ids = (search.task_claim_ids(q, task_id) if task_id else []) + shared["action"] + shared["disputed"] + ([] if purpose == "pre_action" else shared["top"])
    seen: set[str] = set()
    limit = VIEW_ITEMS[purpose]
    claims = []
    for claim_id in claim_ids:
        if claim_id in seen or claim_id in members:
            continue
        seen.add(claim_id)
        cand = cands.get(claim_id)
        if cand is None or not _in_scope(cand, workspace_id, task_id):
            continue
        if purpose == "pre_action" and not _actionable(cand):
            continue
        claims.append(cand)
    if task_id is not None:
        if purpose != "pre_action":
            task = search.task_candidate(q, task_id)
            out += [task] if task else []
        if purpose in ("session_start", "compact_restore"):
            out += search.episode_candidates(q, task_id)
        out += search.observation_candidates(q, task_id)
    if purpose != "pre_action":
        out += questions
    return (out + claims)[: limit + len(out)]


def publish_views(store: Store, ctx: InstallationContext, *, now: str | None = None) -> int:
    """Republish every view and fallback row from one write snapshot; returns the number of view rows written."""
    now = now or utc_now()
    with store.transaction() as txn:
        meta = search.meta_of(txn)
        workspaces = [r[0] for r in txn.execute("SELECT workspace_id FROM workspaces ORDER BY workspace_id").fetchall()]
        txn.execute("DELETE FROM context_views")
        written = 0
        for workspace_id in workspaces:
            environment = provenance.environment_values_in(txn, ctx, workspace_id=workspace_id)
            cands = _Cands(txn, ctx, environment)
            live = "status IN ('candidate', 'active', 'disputed')"
            shared = {
                "action": _claim_rows(txn, f"SELECT claim_id FROM claim_heads WHERE {live} AND action_family_digest IS NOT NULL ORDER BY {STRENGTH_ORDER}, claim_id LIMIT ?", (ACTION_CLAIMS,)),  # noqa: S608
                "disputed": _claim_rows(txn, "SELECT claim_id FROM claim_heads WHERE status = 'disputed' ORDER BY claim_id LIMIT ?", (DISPUTED,)),
                "top": _claim_rows(txn, f"SELECT claim_id FROM claim_heads WHERE status = 'active' ORDER BY {STRENGTH_ORDER}, claim_id LIMIT ?", (TOP_CLAIMS,)),  # noqa: S608
            }
            questions = search.question_candidates(txn, ctx, environment=environment)
            for task_id in [None, *_view_tasks(txn, workspace_id)]:
                for purpose in VIEW_PURPOSES:
                    body = {
                        "view_schema": VIEW_SCHEMA, "workspace_id": workspace_id, "task_id": task_id, "purpose": purpose, "environment": environment,
                        "store_revision": meta["store_revision"], "guidance_epoch": meta["guidance_epoch"], "policy_revision": meta["policy_revision"], "tombstone_epoch": meta["tombstone_epoch"],
                        "candidates": _view_candidates(txn, ctx, cands, workspace_id, task_id, purpose, shared=shared, questions=questions),
                    }
                    _insert_view(txn, view_id(workspace_id, task_id, purpose), workspace_id, task_id, purpose, meta, body)
                    written += 1
            ranked = []
            for claim_id in shared["action"] + shared["disputed"] + shared["top"] + _claim_rows(txn, f"SELECT claim_id FROM claim_heads WHERE {live} ORDER BY {STRENGTH_ORDER}, claim_id LIMIT ?", (FALLBACK_STORED,)):  # noqa: S608
                cand = cands.get(claim_id)
                if cand is not None and claim_id not in {c["ref"]["id"] for c in ranked} and _in_scope(cand, workspace_id, None):
                    ranked.append(cand)
            for rank, cand in enumerate((questions + ranked)[:FALLBACK_STORED]):
                body = {"view_schema": VIEW_SCHEMA, "workspace_id": workspace_id, "environment": environment, **{k: meta[k] for k in meta}, "candidate": cand}
                _insert_view(txn, fallback_id(workspace_id, rank, cand["ref"]["id"]), workspace_id, None, "fallback", meta, body)
                written += 1
        txn.execute(
            "INSERT INTO projection_state (singleton, lexical_backend, views_store_revision, views_guidance_epoch, views_policy_revision, views_tombstone_epoch, updated_at) VALUES (1, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(singleton) DO UPDATE SET views_store_revision = excluded.views_store_revision, views_guidance_epoch = excluded.views_guidance_epoch, "
            "views_policy_revision = excluded.views_policy_revision, views_tombstone_epoch = excluded.views_tombstone_epoch, updated_at = excluded.updated_at",
            (index.backend_for(None), meta["store_revision"], meta["guidance_epoch"], meta["policy_revision"], meta["tombstone_epoch"], now),
        )
        failpoints.hit(failpoints.VIEWS_BEFORE_COMMIT)
    failpoints.hit(failpoints.VIEWS_AFTER_PUBLISH)
    return written


def _insert_view(txn: Any, vid: str, workspace_id: str, task_id: str | None, purpose: str, meta: dict[str, int], body: dict[str, Any]) -> None:
    cands = body.get("candidates") or ([body["candidate"]] if "candidate" in body else [])
    conditions = {c["ref"]["id"]: c.get("precomputed") or {} for c in cands if c.get("precomputed")}
    inputs = {"environment": {k: fc.value_digest(k, v) for k, v in sorted((body.get("environment") or {}).items())}}
    txn.execute(
        "INSERT INTO context_views (view_id, workspace_id, task_id, purpose, source_store_revision, guidance_epoch, policy_revision, tombstone_epoch, condition_results, input_fingerprints, body) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (vid, workspace_id, task_id, purpose, meta["store_revision"], meta["guidance_epoch"], meta["policy_revision"], meta["tombstone_epoch"],
         canonical_json(conditions).decode(), canonical_json(inputs).decode(), canonical_json(body).decode()),
    )


# --------------------------------------------------------------------------
# The worker's projection step


def projection_due(store: Store) -> dict[str, bool]:
    """A cheap read: is the index behind the store, or are the views behind the epochs?"""
    with store.read() as view:
        meta = search.meta_of(view)
        state = index.state(view)
    if state is None:
        return {"index": True, "views": True}
    return {
        "index": state["indexed"] != meta["store_revision"],
        "views": (state["views_guidance"], state["views_policy"], state["views_tombstone"]) != (meta["guidance_epoch"], meta["policy_revision"], meta["tombstone_epoch"]),
    }


def refresh_projection(store: Store, ctx: InstallationContext, *, now: str | None = None) -> dict[str, int]:
    """Deterministic, model-free: index at the store revision, views at the epochs. Returns what it did (empty: nothing due)."""
    due = projection_due(store)
    did: dict[str, int] = {}
    if due["index"]:
        changed = index.refresh(store, ctx, now=now)
        if changed:
            did["indexed"] = changed
    if due["views"]:
        did["views"] = publish_views(store, ctx, now=now)
    return did


def views(store: Store) -> list[dict[str, Any]]:
    """Published view rows (tests and health)."""
    with store.read() as view:
        rows = view.execute("SELECT view_id, workspace_id, task_id, purpose, guidance_epoch, policy_revision, tombstone_epoch, body FROM context_views ORDER BY view_id").fetchall()
    return [{"view_id": r[0], "workspace_id": r[1], "task_id": r[2], "purpose": r[3], "guidance_epoch": r[4], "policy_revision": r[5], "tombstone_epoch": r[6], "body": json.loads(r[7])} for r in rows]
