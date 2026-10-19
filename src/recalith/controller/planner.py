"""The deterministic revision planner (SYSTEM_SPEC §6.2, §6.3, §7.2, §7.3; decision 0012).

The planner runs in the worker's deterministic lane on every poll, uses no
model budget and creates only existing job kinds (``revalidate`` jobs, in the
revalidation or the consolidation band); it never creates an executable, a
command or a new job type. Each sweep is one short transaction, opened only
when a read finds work:

* **Settle** pending revalidation jobs that need no model: every claim is
  retired, or none has a pending recheck a model can settle (a root-class
  merge's revalidation, whose strength was recomputed in its ingestion
  transaction, or a source conflict only a new observation resolves). They
  are cancelled ``revalidation_settled`` without a call.
* **Due reviews.** Active guidance whose ``review_due_at`` passed (30 days
  volatile, 180 stable, earlier when a dependency changed) and that has no
  pending recheck gets a ``review_due`` recheck and a revalidation job. A due
  review is not evidence: freshness is unchanged.
* **Intent questions** (A44). Two or more live user-declared decisions or
  preferences with the same proposition key, different propositions,
  overlapping scope and conditions that are not certainly disjoint, and no
  supersession between them, are one open question (content-free, created
  once per conflict, resolved when fewer than two remain live). Nothing is
  resolved for the user and nothing blocks; the group also gets one
  consolidation job, first in that band.
* **Routine consolidation** runs when 20 settled episodes accumulated since
  the last run, or 24 hours passed with new evidence. Deterministic
  candidate groups (exact proposition key, overlapping applicability) are
  ordered current conflicts first (different propositions), cosmetic
  duplicates last, and at most ``CONSOLIDATION_GROUPS`` get a job per run. A
  group's recheck is keyed by the content of its members (not their
  revision numbers), so the revalidation's own bookkeeping writes never
  re-trigger it: derived writes do not loop.
* **Withdrawn replacements.** A pending supersession whose replacement is no
  longer live is withdrawn.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from typing import Any

from recalith.contracts.common import Condition, InstallationContext, Scope, canonical_json, derived_id, digest_of, format_utc, parse_utc
from recalith.contracts.memory import ClaimRevision
from recalith.controller import jobs, revalidate
from recalith.fast import failpoints
from recalith.storage import records
from recalith.storage.db import Store, Txn

DUE_BATCH = 32
SETTLE_BATCH = 64
CONSOLIDATION_EPISODES = 20
CONSOLIDATION_SECONDS = 24 * 3600
CONSOLIDATION_GROUPS = 4
GROUP_LIMIT = revalidate.REVALIDATION_BATCH
SETTLED = revalidate.SETTLED
DECLARATION_KINDS = ("decision", "preference")


# --------------------------------------------------------------------------
# Deterministic candidate groups


def _paths_overlap(x: list[str], y: list[str]) -> bool:
    return any(p == q or (p.endswith("/") and q.startswith(p)) or (q.endswith("/") and p.startswith(q)) for p in x for q in y)


def _scope_overlaps(a: Scope, b: Scope) -> bool:
    for dim in ("workspace_ids", "task_ids"):
        x, y = getattr(a, dim), getattr(b, dim)
        if x and y and not set(x) & set(y):
            return False
    if a.paths and b.paths and not _paths_overlap(a.paths, b.paths):
        return False
    return all(a.environment[k] == b.environment[k] for k in set(a.environment) & set(b.environment))


def _conditions_disjoint(a: list[Condition], b: list[Condition]) -> bool:
    """True only when the two condition lists certainly cannot hold together (anything uncertain overlaps)."""
    from recalith.core import conditions

    for x in a:
        for y in b:
            if x.exclude or y.exclude or x.kind != y.kind or x.key != y.key:
                continue
            if x.kind in ("environment_equals", "branch_ref", "action_kind", "tool") and x.value != y.value:
                return True
            if x.kind == "version_range":
                # [x.value, x.upper] and [y.value, y.upper] are disjoint when one ends before the other starts.
                if x.upper is not None and conditions.version_in_range(x.upper, y.value, None) == conditions.FALSE:
                    return True
                if y.upper is not None and conditions.version_in_range(y.upper, x.value, None) == conditions.FALSE:
                    return True
    return False


def overlapping(a: ClaimRevision, b: ClaimRevision) -> bool:
    return _scope_overlaps(a.scope, b.scope) and not _conditions_disjoint(a.conditions, b.conditions)


def _related(a: ClaimRevision, b: ClaimRevision) -> bool:
    ids = {r.id for r in [*a.supersedes, *a.superseded_by]} | {r.id for r in [*b.supersedes, *b.superseded_by]}
    return a.claim_id in ids or b.claim_id in ids


@dataclass(frozen=True)
class Group:
    key: tuple[str, str]
    claims: tuple[ClaimRevision, ...]
    conflict: bool  # different propositions over overlapping applicability
    intent: bool  # every member a user declaration of intent

    @property
    def content_digest(self) -> str:
        """Members by content (not revision numbers): bookkeeping revisions never form a new group."""
        return digest_of(sorted([c.claim_id, records.content_key(c), sorted(link["ref"]["id"] for link in c.model_dump(mode="json")["supports"])] for c in self.claims))

    @property
    def rank(self) -> tuple:
        return (0 if self.intent and self.conflict else 1 if self.conflict else 2, self.content_digest)


def _heads(q: Any, statuses: tuple[str, ...], *, extra: str = "", params: tuple = ()) -> list[ClaimRevision]:
    marks = ",".join("?" for _ in statuses)
    rows = q.execute(f"SELECT claim_id, revision FROM claim_heads WHERE status IN ({marks}){extra} ORDER BY claim_id", (*statuses, *params)).fetchall()  # noqa: S608
    out = []
    for claim_id, revision in rows:
        claim = records.load(q, "claim", claim_id, revision)
        if claim is not None and claim.proposition_key is not None:
            out.append(claim)
    return out


def _find(parent: dict[str, str], x: str) -> str:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def candidate_groups(q: Any, claims: list[ClaimRevision] | None = None) -> list[Group]:
    """Exact proposition-key groups of live guidance whose members overlap; conflicts first."""
    claims = _heads(q, ("active", "disputed")) if claims is None else claims
    by_key: dict[tuple[str, str], list[ClaimRevision]] = {}
    for claim in claims:
        assert claim.proposition_key is not None
        by_key.setdefault((claim.proposition_key.subject, claim.proposition_key.predicate), []).append(claim)
    groups = []
    for key, members in sorted(by_key.items()):
        if len(members) < 2:
            continue
        # Connected components of overlapping, unrelated members.
        parent = {c.claim_id: c.claim_id for c in members}
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                if overlapping(a, b) and not _related(a, b):
                    parent[_find(parent, a.claim_id)] = _find(parent, b.claim_id)
        components: dict[str, list[ClaimRevision]] = {}
        for c in members:
            components.setdefault(_find(parent, c.claim_id), []).append(c)
        for component in components.values():
            if len(component) < 2:
                continue
            component = sorted(component, key=lambda c: c.claim_id)[:GROUP_LIMIT]
            conflict = len({c.proposition for c in component}) > 1
            intent = all(c.basis == "user_declared" and c.kind in DECLARATION_KINDS for c in component)
            groups.append(Group(key=key, claims=tuple(component), conflict=conflict, intent=intent))
    return sorted(groups, key=lambda g: g.rank)


# --------------------------------------------------------------------------
# Sweeps (each runs inside the planner's transaction)


def _settle_jobs(txn: Txn) -> int:
    count = 0
    for (body,) in txn.execute("SELECT body FROM jobs WHERE kind = 'revalidate' AND state IN ('pending', 'waiting_budget') ORDER BY due_at, job_id LIMIT ?", (SETTLE_BATCH,)).fetchall():
        job = jobs.Job.model_validate_json(body)
        if not revalidate.needs_model(txn, job):
            jobs.supersede(txn, job, SETTLED)
            count += 1
    return count


def _due_reviews(txn: Txn, ctx: InstallationContext, now: str) -> int:
    rows = txn.execute(
        "SELECT claim_id, review_due_at FROM claim_heads WHERE status IN ('active', 'disputed') AND review_due_at IS NOT NULL AND review_due_at <= ? ORDER BY review_due_at, claim_id LIMIT ?",
        (now, DUE_BATCH),
    ).fetchall()
    marked = []
    for claim_id, due in rows:
        if txn.one("SELECT 1 FROM claim_rechecks WHERE claim_id = ? AND state IN ('pending', 'deferred')", (claim_id,)) is not None:
            continue  # its revalidation is already owed
        marked += revalidate.mark(txn, ctx, claim_id, reason="review_due", key=due, event_id=None, detail={"review_due_at": due}, context=None, now=now, causal_root=None)
    if marked:
        revalidate.enqueue(txn, marked, now=now)
    return len(marked)


def _consolidate(txn: Txn, ctx: InstallationContext, groups: list[Group], now: str, *, limit: int) -> int:
    scheduled = 0
    for group in groups:
        if scheduled >= limit:
            break
        key = group.content_digest
        ids = [c.claim_id for c in group.claims]
        if all(txn.one("SELECT 1 FROM claim_rechecks WHERE recheck_id = ?", (revalidate.recheck_id(c, "consolidation", key),)) is not None for c in ids):
            continue  # this exact group was already consolidated: its own writes never re-trigger it
        marked = []
        for claim_id in ids:
            marked += revalidate.mark(txn, ctx, claim_id, reason="consolidation", key=key, event_id=None, detail={"group": key, "conflict": group.conflict, "intent": group.intent}, context=None, now=now, causal_root=None)
        if marked:
            revalidate.enqueue(txn, ids, now=now, consolidation=True)
            scheduled += 1
    return scheduled


def question_id(claim_ids: list[str]) -> str:
    return derived_id("qst", sorted(claim_ids))


def _question_work(q: Any) -> tuple[list[Group], list[str]]:
    """(conflicts of user intent without a question, open questions that no longer hold)."""
    declared = _heads(q, ("active", "disputed"), extra=" AND basis = 'user_declared' AND kind IN ('decision', 'preference')")
    new = [g for g in candidate_groups(q, declared) if g.conflict and g.intent and q.execute("SELECT 1 FROM intent_questions WHERE question_id = ?", (question_id([c.claim_id for c in g.claims]),)).fetchone() is None]
    stale = []
    for qid, claim_ids in q.execute("SELECT question_id, claim_ids FROM intent_questions WHERE state = 'open' ORDER BY question_id").fetchall():
        if sum(1 for c in json.loads(claim_ids) if (records.head(q, "claim", c) or (0, ""))[1] in ("active", "disputed")) < 2:
            stale.append(qid)
    return new, stale


def _questions(txn: Txn, ctx: InstallationContext, now: str) -> int:
    """Open one question per unresolved conflict of user intent; resolve questions that no longer hold."""
    new, stale = _question_work(txn)
    for group in new:
        ids = sorted(c.claim_id for c in group.claims)
        txn.execute(
            "INSERT INTO intent_questions (question_id, claim_ids, proposition_key, state, created_at) VALUES (?, ?, ?, 'open', ?)",
            (question_id(ids), canonical_json(ids).decode(), canonical_json(list(group.key)).decode(), now),
        )
        _consolidate(txn, ctx, [group], now, limit=1)
    for qid in stale:
        txn.execute("UPDATE intent_questions SET state = 'resolved', resolved_at = ? WHERE question_id = ?", (now, qid))
    if new or stale:
        txn.mutated(serving_relevant=True)  # a question is served in the next relevant context packet
    return len(new)


def _withdraw(txn: Txn, now: str) -> int:
    count = 0
    for replacement_id, target_id in txn.execute("SELECT replacement_id, target_id FROM pending_supersessions WHERE state = 'pending' ORDER BY replacement_id, target_id").fetchall():
        head = records.head(txn, "claim", replacement_id)
        if head is None or head[1] not in revalidate.LIVE:
            revalidate.decide_supersession(txn, replacement_id, target_id, "withdrawn", now=now)
            count += 1
    return count


def _consolidation_due(q: Any, now: str) -> tuple[bool, dict[str, Any]]:
    """20 settled episodes since the last run, or 24 hours with new evidence (the clock starts at installation)."""
    state = q.execute("SELECT consolidated_at, settled_episodes, evidence_mark FROM planner_state WHERE singleton = 1").fetchone()
    since = state[0] or q.execute("SELECT created_at FROM installation_meta WHERE singleton = 1").fetchone()[0]
    episodes = q.execute("SELECT COUNT(*) FROM episode_heads WHERE state = 'settled'").fetchone()[0]
    mark = q.execute("SELECT COALESCE(MAX(commit_sequence), 0) FROM events").fetchone()[0] + q.execute("SELECT COUNT(*) FROM claim_revisions").fetchone()[0]
    info = {"episodes": episodes, "mark": mark}
    if episodes - state[1] >= CONSOLIDATION_EPISODES:
        return True, info
    elapsed = (parse_utc(now) - parse_utc(since)).total_seconds()
    return elapsed >= CONSOLIDATION_SECONDS and mark > state[2], info


def _work(q: Any, now: str) -> dict[str, bool]:
    """A read-only look: is there anything for the planner's transaction to do?"""
    due, _info = _consolidation_due(q, now)
    new, stale = _question_work(q)
    return {
        "settle": q.execute("SELECT 1 FROM jobs WHERE kind = 'revalidate' AND state IN ('pending', 'waiting_budget') LIMIT 1").fetchone() is not None,
        "due": q.execute("SELECT 1 FROM claim_heads WHERE status IN ('active', 'disputed') AND review_due_at IS NOT NULL AND review_due_at <= ? LIMIT 1", (now,)).fetchone() is not None,
        "questions": bool(new or stale),
        "consolidate": due,
        "withdraw": q.execute("SELECT 1 FROM pending_supersessions WHERE state = 'pending' LIMIT 1").fetchone() is not None,
    }


def run(store: Store, ctx: InstallationContext, *, now: str) -> dict[str, int]:
    """One planner sweep; returns what it did (empty when there was nothing to do)."""
    with store.read() as view:
        work = _work(view, now)
        if work["settle"]:
            work["settle"] = any(not revalidate.needs_model(view, jobs.Job.model_validate_json(b)) for (b,) in view.execute("SELECT body FROM jobs WHERE kind = 'revalidate' AND state IN ('pending', 'waiting_budget') LIMIT ?", (SETTLE_BATCH,)).fetchall())
        if work["due"]:
            work["due"] = view.execute(
                "SELECT 1 FROM claim_heads h WHERE h.status IN ('active', 'disputed') AND h.review_due_at IS NOT NULL AND h.review_due_at <= ? "
                "AND NOT EXISTS (SELECT 1 FROM claim_rechecks r WHERE r.claim_id = h.claim_id AND r.state IN ('pending', 'deferred')) LIMIT 1",
                (now,),
            ).fetchone() is not None
        if work["withdraw"]:
            work["withdraw"] = any((records.head(view, "claim", r) or (0, ""))[1] not in revalidate.LIVE for (r,) in view.execute("SELECT replacement_id FROM pending_supersessions WHERE state = 'pending'").fetchall())
    if not any(work.values()):
        return {}
    done: dict[str, int] = {}
    with store.transaction() as txn:
        if work["settle"]:
            done["settled"] = _settle_jobs(txn)
        if work["due"]:
            done["due_reviews"] = _due_reviews(txn, ctx, now)
        if work["questions"]:
            done["questions"] = _questions(txn, ctx, now)
        if work["consolidate"]:
            due, info = _consolidation_due(txn, now)
            if due:
                done["consolidation"] = _consolidate(txn, ctx, candidate_groups(txn), now, limit=CONSOLIDATION_GROUPS)
                txn.execute("UPDATE planner_state SET consolidated_at = ?, settled_episodes = ?, evidence_mark = ? WHERE singleton = 1", (now, info["episodes"], info["mark"]))
                txn.mutated(serving_relevant=False)
        if work["withdraw"]:
            done["withdrawn"] = _withdraw(txn, now)
        failpoints.hit(failpoints.PLANNER_AFTER_SCHEDULE)
    return {k: v for k, v in done.items() if v}


def questions(view: Any, state: str | None = None) -> list[dict[str, Any]]:
    rows = view.execute("SELECT question_id, claim_ids, proposition_key, state FROM intent_questions" + (" WHERE state = ?" if state else "") + " ORDER BY created_at, question_id", (state,) if state else ()).fetchall()
    return [{"question_id": r[0], "claim_ids": json.loads(r[1]), "proposition_key": json.loads(r[2]), "state": r[3]} for r in rows]


def plus(moment: str, seconds: float) -> str:
    return format_utc(parse_utc(moment) + _dt.timedelta(seconds=seconds))


__all__ = ["run", "candidate_groups", "questions", "Group", "overlapping", "question_id", "SETTLED"]
