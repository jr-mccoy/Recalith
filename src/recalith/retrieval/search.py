"""Retrieval: eligible candidates, applicability, advice and deterministic ranking (SYSTEM_SPEC §7.3–§7.4, §8.1–§8.2; DATA_CONTRACTS §9, §11).

Order (SYSTEM_SPEC §8.1): resolve the installation, workspace and task (a
linked placeholder redirects to its target and never serves itself); exclude
retired and out-of-scope records **before any candidate cap** (hot columns in
``retrieval_docs``, then full tri-state applicability; a ``false`` result
never occupies a slot); gather structural matches (exact action family,
paths, tools, subjects), lexical matches (FTS5 or the token index), active
task context and evidence-linked neighbors; evaluate conditions, the
failure-lesson dependency gate and freshness through the Task 10 advice gate
(:func:`recalith.controller.revalidate.guidance`); rank deterministically.

Each candidate is first built as the primitive dict the worker also
pre-serializes into ``context_views`` (:func:`claim_candidate` and friends),
so the stdlib hook compiler sees exactly the same rendered text, conditions,
dependencies and evidence; :func:`decide` is the strict decision the hook's
:func:`recalith.fast.context.decide` twins. Delivery-table rows (§8.2):

* active supported/corroborated, current → ``context``; ``caution`` only for a
  supported failure lesson with ``true`` applicability, a ``true``
  dependency gate, current freshness and an action-specific match;
* active, needs revalidation or unknown freshness → ``context`` with its
  freshness label, never caution;
* candidates → ``context`` labeled tentative (``tentative_context``), only
  for the bound task or an exact action match;
* expired/redacted support (field or live evidence state) → omitted;
* disputed → one ``conflict`` item with both sides; an open intent question
  folds its declarations into one ``conflict`` item;
* superseded, invalidated, archived, quarantined, forgotten → never candidates.

Recent typed observations of the bound task are a separate group: exact
captured results, ``context`` only, never caution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from recalith.capture import provenance
from recalith.contracts.common import InstallationContext, RecordRef
from recalith.contracts.context import ContextItem, ContextQuery
from recalith.contracts.memory import ClaimRevision
from recalith.controller import revalidate
from recalith.core import conditions as cond
from recalith.errors import RecalithError
from recalith.fast import context as fc
from recalith.retrieval import index
from recalith.storage import records
from recalith.storage.db import Store, open_store

CANDIDATE_LIMIT = 64
SEED_LIMIT = 96
NEIGHBOR_LIMIT = 16
TASK_CLAIMS = 128
OBSERVATIONS = 3
EPISODES = 2
QUESTIONS = 8
MAX_REDIRECTS = 8
PROPOSITION_CHARS = 600
PART_CHARS = 240
STRENGTH_BASE = {"corroborated": 4.0, "supported": 3.0, "weak": 1.0}
RECHECK_LABEL = {
    "later_success": "a later run of the same action succeeded",
    "order_unknown": "a run of the same action succeeded in uncertain order",
    "dependency_changed": "a dependency changed",
    "source_conflict": "its source is in conflict",
    "support_lost": "some of its evidence is no longer available",
}


# --------------------------------------------------------------------------
# Rendering helpers


def conditions_text(scope: dict[str, Any], conditions: Sequence[dict[str, Any]], dependencies: Sequence[dict[str, Any]]) -> str | None:
    parts = []
    if scope.get("paths"):
        parts.append("paths " + ", ".join(scope["paths"]))
    for key, value in sorted((scope.get("environment") or {}).items()):
        parts.append(f"{key}={value}")
    if scope.get("task_ids"):
        parts.append("task-scoped")
    for c in conditions:
        neg = "not " if c.get("exclude") else ""
        kind, key, value = c["kind"], c["key"], c["value"]
        if kind == "version_range":
            text = f"{key} == {value}" if c.get("upper") == value else f"{key} in [{value}, {c.get('upper') or '∞'}]"
        elif kind == "environment_equals":
            text = f"{key}={value}"
        else:
            text = f"{kind.replace('_ref', '').replace('_', ' ')} {value}"
        parts.append(neg + text)
    deps = [f"{d['kind']} {d['key']}" for d in dependencies]
    if deps:
        parts.append("depends on " + ", ".join(deps[:6]) + ("…" if len(deps) > 6 else ""))
    return fc.bounded("; ".join(parts), 600) or None


def _supported(value: dict[str, Any] | None) -> str | None:
    return None if not value else fc.bounded(value.get("text", ""), PART_CHARS)


def retry_text(claim: dict[str, Any]) -> str | None:
    """The legitimate retry condition (SYSTEM_SPEC §8.2): reviewed retry conditions, else the dependency rule."""
    failure = claim.get("failure") or {}
    texts = [fc.bounded(r["text"], PART_CHARS) for r in failure.get("retry_conditions") or []]
    if texts:
        return fc.bounded("; ".join(texts), 600)
    files = [d["key"] for d in claim.get("dependencies") or [] if d["kind"] in ("file", "config", "environment")]
    if files:
        return fc.bounded(f"retrying is reasonable once {', '.join(files[:4])} changes; Recalith re-checks this lesson then", 600)
    return "retrying is reasonable once the cause is fixed; a later passing run of the same action lifts this note"


def pending_reasons(q: Any, claim_id: str) -> list[str]:
    return sorted({r["reason"] for r in revalidate.pending(q, claim_id) if r["reason"] in RECHECK_LABEL})


def claim_text(claim: dict[str, Any], *, pending: Sequence[str] = ()) -> str:
    kind = claim["kind"]
    prop = fc.bounded(claim["proposition"], PROPOSITION_CHARS)
    if kind == "failure_lesson":
        failure = claim.get("failure") or {}
        parts = [f"Failure lesson: {prop}"]
        for label, key in (("Observed", "observed_failure"), ("Consequence", "consequence"), ("Alternative", "alternative")):
            text = _supported(failure.get(key))
            if text:
                parts.append(f"{label}: {text}")
        text = " ".join(parts)
    elif kind == "procedure":
        steps = [s["text"] for s in ((claim.get("procedure") or {}).get("steps") or [])][:6]
        text = f"Procedure: {prop}" + (" Steps: " + " ".join(f"{i}. {fc.bounded(s, 120)}" for i, s in enumerate(steps, 1)) if steps else "")
    else:
        text = f"{kind.capitalize()}: {prop}"
    if claim["status"] == "candidate":
        text = "Tentative (unreviewed candidate): " + text
    elif claim["strength"] == "weak":
        text = "Tentative (weak support): " + text
    if claim["freshness"] != "current":
        why = "; ".join(RECHECK_LABEL[r] for r in pending) or "applicability not re-established"
        text += f" [pending revalidation: {why}]"
    return fc.bounded(text, 1800)


def _link_summary(q: Any, link: dict[str, Any]) -> str:
    ref = link["ref"]
    if ref["kind"] != "event":
        return f"{ref['kind']} {ref['id']}"
    row = q.execute("SELECT event_id, commit_sequence, envelope, payload, kind, payload_state FROM events WHERE event_id = ?", (ref["id"],)).fetchone()
    if row is None or row[3] is None or row[5] not in fc.SUFFICIENT_EVIDENCE:
        return "unavailable evidence"
    from recalith.working.tasks import ev_from_row, result_summary

    payload = json.loads(row[3])
    if row[4] == "tool_finished":
        return fc.bounded(result_summary(ev_from_row(row[:4])), 200)
    if isinstance(payload.get("text"), str):
        return '"' + fc.bounded(payload["text"], 160) + '"'
    return row[4]


# --------------------------------------------------------------------------
# Evidence state


def evidence_state(q: Any, claim: dict[str, Any]) -> str:
    """The claim's field, unless its support events are no longer available (expired/forgotten payloads)."""
    declared = claim.get("evidence_availability", "available")
    if declared not in fc.SUFFICIENT_EVIDENCE:
        return declared
    events = [link["ref"]["id"] for link in claim.get("supports") or [] if link["ref"]["kind"] == "event"]
    if not events:
        return declared
    marks = ",".join("?" for _ in events)
    states = {r[0] for r in q.execute(f"SELECT payload_state FROM events WHERE event_id IN ({marks})", tuple(events)).fetchall()}  # noqa: S608
    if states & fc.SUFFICIENT_EVIDENCE:
        return declared
    return "expired"


def bound_tasks(q: Any, event_ids: Iterable[str]) -> list[str]:
    ids = sorted(set(event_ids))
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    return sorted({r[0] for r in q.execute(f"SELECT task_id FROM task_binding_heads WHERE event_id IN ({marks})", tuple(ids)).fetchall()})  # noqa: S608


# --------------------------------------------------------------------------
# Candidates (the primitive form views also carry)


def _precomputed(claim: ClaimRevision, environment: dict[str, str]) -> dict[str, Any]:
    """Version results the hook may reuse only while the exact consulted value matches (PEP 440 stays here)."""
    out = {}
    for i, c in enumerate(claim.conditions):
        if c.kind == "version_range" and c.key in environment:
            # The raw comparison, before the exclusion flag the hook applies itself.
            out[str(i)] = {"value_digest": fc.value_digest(c.key, environment[c.key]), "result": cond.version_in_range(environment[c.key], c.value, c.upper)}
    return out


def claim_candidate(q: Any, ctx: InstallationContext, claim: ClaimRevision, *, environment: dict[str, str]) -> dict[str, Any]:
    data = claim.model_dump(mode="json")
    pending = pending_reasons(q, claim.claim_id) if claim.freshness != "current" else []
    support_events = sorted({link.ref.id for link in claim.supports if link.ref.kind == "event"})
    disputed = claim.status == "disputed"
    text = claim_text(data, pending=pending)
    refs = [link.ref.model_dump(mode="json") for link in claim.supports[:4]]
    if disputed:
        pro = "; ".join(_link_summary(q, link) for link in data["supports"][:2]) or "no available support"
        con = "; ".join(_link_summary(q, link) for link in data["contradicts"][:2]) or "contradiction recorded without available evidence"
        text = fc.bounded(f"Disputed: {fc.bounded(claim.proposition, PROPOSITION_CHARS)} For: {pro}. Against: {con}. Unresolved; verify before relying on either side.", 1800)
        refs = [link.ref.model_dump(mode="json") for link in [*claim.supports[:2], *claim.contradicts[:2]]]
    claim_values = {}
    for dep in claim.dependencies:
        if dep.kind == "claim" and dep.record is not None:
            head = records.head(q, "claim", dep.record.id)
            claim_values[f"claim:{dep.key}"] = {"value": revalidate.claim_fingerprint(q, dep.record.id), "record_id": dep.record.id, "head_revision": head[0] if head else None}
    words = index.document("claim", claim.claim_id, claim.revision, claim.status, data).words
    specificity = sum(bool(x) for x in (claim.scope.paths, claim.scope.task_ids, claim.scope.environment)) + len(claim.conditions)
    return {
        "ref": {"kind": "claim", "id": claim.claim_id, "revision": claim.revision}, "group": "conflict" if disputed else "claim",
        "claim_kind": claim.kind, "status": claim.status, "strength": claim.strength, "basis": claim.basis, "freshness": claim.freshness,
        "evidence": evidence_state(q, data), "text": text, "scope": claim.scope.model_dump(mode="json"), "conditions": [c.model_dump(mode="json") for c in claim.conditions],
        "dependencies": [{"kind": d.kind, "key": d.key, "fingerprint": d.fingerprint} for d in claim.dependencies],
        "family": claim.failure.action_family_digest if claim.failure is not None else None,
        "task_ids": sorted(set(claim.scope.task_ids) | set(bound_tasks(q, support_events))), "terms": words[:64], "term_count": len(words),
        "base": round(STRENGTH_BASE[claim.strength] + (1.0 if claim.freshness == "current" else 0.0) + 0.5 * specificity, 6),
        "tentative": claim.status == "candidate" or claim.strength == "weak", "subject": claim.proposition_key.subject.casefold() if claim.proposition_key else None,
        "evidence_refs": refs, "support_events": support_events, "conditions_text": conditions_text(data["scope"], data["conditions"], data["dependencies"]),
        "retry_text": retry_text(data) if claim.kind == "failure_lesson" else None, "precomputed": _precomputed(claim, environment), "claim_values": claim_values,
    }


def task_candidate(q: Any, task_id: str) -> dict[str, Any] | None:
    head = records.head(q, "task", task_id)
    if head is None or head[1] == "linked":
        return None
    body = records.body(q, "task", task_id, head[0])
    if body is None:
        return None
    parts = [f"Current task: {fc.bounded(body['title'], 160)}."]
    if body.get("objective"):
        parts.append("Objective: " + fc.bounded(body["objective"]["text"], 300) + ".")
    blockers = [fc.bounded(b["text"], 160) for b in body.get("blockers") or []][:3]
    if blockers:
        parts.append("Blockers: " + "; ".join(blockers) + ".")
    pending = [fc.bounded(p["description"]["text"], 120) for p in body.get("pending_actions") or [] if p.get("state") in ("proposed", "running", "awaiting_result")][:3]
    if pending:
        parts.append("Pending: " + "; ".join(pending) + ".")
    if body.get("next_action"):
        parts.append("Next: " + fc.bounded(body["next_action"]["text"], 160) + ".")
    if head[1] != "active":
        parts.append(f"(status {head[1]})")
    objective = body.get("objective") or {}
    return {
        "ref": {"kind": "task", "id": task_id, "revision": head[0]}, "group": "task", "status": head[1], "basis": objective.get("basis", "observed"),
        "freshness": "current", "evidence": "available", "text": fc.bounded(" ".join(parts), 1500), "scope": {}, "conditions": [], "dependencies": [],
        "family": None, "task_ids": [task_id], "terms": [], "term_count": 0, "base": 5.0, "tentative": False, "subject": None,
        "evidence_refs": [], "support_events": [], "conditions_text": None, "retry_text": None, "advice_ceiling": "context",
    }


def episode_candidates(q: Any, task_id: str) -> list[dict[str, Any]]:
    rows = q.execute("SELECT episode_id, revision, state FROM episode_heads WHERE task_id = ? AND state IN ('open', 'settled')", (task_id,)).fetchall()
    bodies = [(r, records.body(q, "episode", r[0], r[1])) for r in rows]
    bodies = sorted(((r, b) for r, b in bodies if b is not None), key=lambda x: (x[1].get("ended_at") or x[1]["started_at"], x[0][0]), reverse=True)[:EPISODES]
    out = []
    for (episode_id, revision, state), body in bodies:
        text = f"Episode ({state}): {fc.bounded(body['title'], 160)}. Outcome: {fc.bounded(body['outcome']['text'], 300)}."
        unresolved = [fc.bounded(u["text"], 120) for u in body.get("unresolved") or []][:2]
        if unresolved:
            text += " Unresolved: " + "; ".join(unresolved) + "."
        out.append({
            "ref": {"kind": "episode", "id": episode_id, "revision": revision}, "group": "episode", "status": state, "basis": body["outcome"].get("basis", "observed"),
            "freshness": "current", "evidence": "available", "text": fc.bounded(text, 1200), "scope": {}, "conditions": [], "dependencies": [], "family": None,
            "task_ids": [task_id], "terms": [], "term_count": 0, "base": 2.0, "tentative": False, "subject": None, "evidence_refs": [], "support_events": [],
            "conditions_text": None, "retry_text": None, "advice_ceiling": "context",
        })
    return out


def observation_candidates(q: Any, task_id: str) -> list[dict[str, Any]]:
    """The bound task's latest certified results: exact captured outcomes, labeled observations (never lessons)."""
    from recalith.working.tasks import ev_from_row, result_summary

    rows = q.execute(
        "SELECT e.event_id, e.commit_sequence, e.envelope, e.payload FROM events e JOIN task_binding_heads b ON b.event_id = e.event_id "
        "WHERE b.task_id = ? AND e.kind = 'tool_finished' AND e.authority = 'observed_tool' AND e.payload_state = 'available' ORDER BY e.commit_sequence DESC LIMIT 16",
        (task_id,),
    ).fetchall()
    evs = [ev_from_row(r) for r in rows]
    evs = sorted(evs, key=lambda e: (e.payload.get("outcome") == "success", -e.seq))[:OBSERVATIONS]
    out = []
    for ev in evs:
        out.append({
            "ref": {"kind": "event", "id": ev.event_id, "revision": 1}, "group": "observation", "status": "observed", "basis": "observed", "freshness": "current",
            "evidence": "available", "text": fc.bounded("Recent observation (not a durable lesson): " + result_summary(ev), 700), "scope": {}, "conditions": [], "dependencies": [],
            "family": None, "task_ids": [task_id], "terms": [], "term_count": 0, "base": 1.0 + (0.5 if ev.payload.get("outcome") != "success" else 0.0) + ev.seq / 1e9,
            "tentative": False, "subject": None, "evidence_refs": [], "support_events": [ev.event_id], "conditions_text": None, "retry_text": None, "advice_ceiling": "context",
        })
    return out


def question_candidates(q: Any, ctx: InstallationContext, *, environment: dict[str, str]) -> list[dict[str, Any]]:
    """Each open intent question as one conflict candidate (its declarations are folded into it)."""
    out = []
    for qid, claim_ids, key in q.execute("SELECT question_id, claim_ids, proposition_key FROM intent_questions WHERE state = 'open' ORDER BY question_id LIMIT ?", (QUESTIONS,)).fetchall():
        members = []
        for claim_id in json.loads(claim_ids):
            head = records.head(q, "claim", claim_id)
            if head is None or head[1] not in fc.LIVE:
                continue
            claim = records.load(q, "claim", claim_id, head[0])
            if claim is not None:
                members.append(claim)
        if len(members) < 2:
            continue
        parsed = json.loads(key)
        subject = parsed.get("subject", "") if isinstance(parsed, dict) else str(parsed[0]) if parsed else ""
        sides = " ".join(f"({i}) {fc.bounded(m.proposition, 240)}" for i, m in enumerate(members, 1))
        words = sorted({w for m in members for w in index.document("claim", m.claim_id, m.revision, m.status, m.model_dump(mode="json")).words})
        first = members[0]
        out.append({
            "ref": {"kind": "claim", "id": first.claim_id, "revision": first.revision}, "group": "conflict", "question_id": qid, "status": "question",
            "basis": "user_declared", "freshness": "current", "evidence": "available",
            "text": fc.bounded(f"Open question: conflicting user decisions about {subject}: {sides}. Recalith has not chosen; ask the user which applies.", 1800),
            "scope": {}, "conditions": [], "dependencies": [], "family": None, "task_ids": [], "terms": words[:64], "term_count": len(words), "base": 2.0,
            "tentative": False, "subject": None, "members": [m.claim_id for m in members], "member_revisions": {m.claim_id: m.revision for m in members},
            "evidence_refs": [{"kind": "claim", "id": m.claim_id, "revision": m.revision} for m in members[1:4]], "support_events": [],
            "conditions_text": None, "retry_text": None, "advice_ceiling": "conflict",
        })
    return out


# --------------------------------------------------------------------------
# The strict decision (the hook's fc.decide is its twin)


def decide(q: Any, ctx: InstallationContext, cand: dict[str, Any], query: ContextQuery, *, family: str | None, query_terms: set[str], budget: fc.DependencyBudget,
           claim: ClaimRevision | None = None, idf: dict[str, float] | None = None) -> dict[str, Any] | None:
    """One candidate under one query through the strict modules (core.conditions, revalidate.guidance)."""
    qd = query.model_dump(mode="json")
    if cand.get("evidence") not in fc.SUFFICIENT_EVIDENCE:
        return None
    if claim is not None:
        app = cond.applicability(claim.scope, claim.conditions, query)
    else:
        app = fc.applicability(cand.get("scope") or {}, [], qd, query.environment)
    if app == cond.FALSE:
        return None
    match = fc.relevance(cand, qd, query_terms=query_terms, family=family, idf=idf)
    if not fc.relevant(cand, match):
        return None
    if claim is not None:
        current: dict[str, str | None] = {}
        lesson_gate = claim.kind == "failure_lesson" and claim.status == "active" and app == cond.TRUE
        if claim.dependencies and claim.freshness == "current" and (lesson_gate or claim.kind != "failure_lesson"):
            values = {k: v["value"] for k, v in (cand.get("claim_values") or {}).items()}
            current = fc.current_dependencies(cand["dependencies"], workspace_root=str(ctx.workspace_root), environment=query.environment, budget=budget, claim_values=values)
        g = revalidate.guidance(q, ctx, claim, query, current=current)
        advice = g.advice
        if advice is None:
            return None
        if advice == "caution" and "exact_action_match" not in match["reasons"] and not fc._action_conditions_true(cand, qd, query.environment):
            advice = "context"
        extra = [r for r in g.reasons if r != "candidate"]
        shown = g.freshness
    else:
        advice, extra, shown = cand.get("advice_ceiling", "context"), [], None
    item = fc.finish_item(cand, advice, app, match, qd, extra, freshness=shown)
    return {"item": item, "score": match["score"], "rank_group": 0 if advice in ("caution", "conflict") else 1, "subject": cand.get("subject")}


# --------------------------------------------------------------------------
# Gathering


@dataclass
class Gathered:
    entries: list[dict[str, Any]]
    meta: dict[str, int]
    query: ContextQuery
    degraded: list[str] = field(default_factory=list)
    considered: int = 0
    cut: int = 0


def meta_of(q: Any) -> dict[str, int]:
    row = q.execute("SELECT store_revision, guidance_epoch, policy_revision, tombstone_epoch FROM installation_meta WHERE singleton = 1").fetchone()
    return {"store_revision": row[0], "guidance_epoch": row[1], "policy_revision": row[2], "tombstone_epoch": row[3]}


def resolve_task(q: Any, task_id: str | None, workspace_id: str, *, session_id: str | None = None) -> tuple[str | None, list[str]]:
    """The query's task, else the session's worker-established task; linked placeholders redirect to their target (A24).

    A task of another workspace is not used. Without any binding the query is
    workspace-only (SYSTEM_SPEC §5.1.1).
    """
    if task_id is None and session_id is not None:
        row = q.execute("SELECT task_id FROM working_sessions WHERE session_id = ?", (session_id,)).fetchone()
        task_id = row[0] if row else None
    hops = 0
    while task_id is not None:
        row = q.execute("SELECT status, redirect_task_id, workspace_id FROM task_heads WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None, ["task_unknown"]
        if row[2] != workspace_id:
            return None, ["task_outside_workspace"]
        if row[0] != "linked" or row[1] is None:
            return task_id, []
        hops += 1
        if hops > MAX_REDIRECTS:
            return None, ["task_redirect_loop"]
        task_id = row[1]
    return None, []


def structural_keys(query: ContextQuery, family: str | None) -> list[str]:
    keys = []
    action = query.action
    if action is not None:
        if action.parse_status == "exact":
            for path in action.paths:
                keys.append(f"path:{path}")
                parts = path.split("/")
                keys += [f"path:{'/'.join(parts[:i])}/" for i in range(1, len(parts))]
        keys.append(f"tool:{action.tool}")
    if family:
        keys.append(f"family:{family}")
    return sorted(set(keys))


def _prefilter(hit_ws: list[str], hit_tasks: list[str], query: ContextQuery) -> bool:
    """Workspace and task scope from the hot columns: exact dimensions, checked before any cap."""
    if hit_ws and query.workspace_id not in hit_ws:
        return False
    if hit_tasks and query.task_id is not None and query.task_id not in hit_tasks:
        return False
    return True


def task_claim_ids(q: Any, task_id: str) -> list[str]:
    rows = q.execute(
        "SELECT DISTINCT el.owner_id FROM evidence_links el JOIN task_binding_heads b ON b.event_id = el.target_id "
        "JOIN claim_heads h ON h.claim_id = el.owner_id AND h.revision = el.owner_revision "
        "WHERE el.owner_kind = 'claim' AND el.relation = 'supports' AND el.target_kind = 'event' AND b.task_id = ? AND h.status IN ('candidate', 'active', 'disputed') "
        "ORDER BY el.owner_id LIMIT ?",
        (task_id, TASK_CLAIMS),
    ).fetchall()
    scoped = q.execute("SELECT record_id FROM retrieval_docs WHERE record_kind = 'claim' AND task_ids LIKE ? ORDER BY record_id LIMIT ?", (f'%"{task_id}"%', TASK_CLAIMS)).fetchall()
    return sorted({r[0] for r in rows} | {r[0] for r in scoped})


def neighbors(q: Any, claim_ids: Sequence[str]) -> dict[str, str]:
    """Claim-dependency neighbors of the seeds (both directions), bounded: neighbor → seed."""
    out: dict[str, str] = {}
    for seed in claim_ids:
        for dependent in revalidate.claim_dependents(q, seed):
            out.setdefault(dependent, seed)
        head = records.head(q, "claim", seed)
        if head is not None:
            for (rid,) in q.execute("SELECT record_id FROM dependencies WHERE claim_id = ? AND claim_revision = ? AND kind = 'claim' AND record_id IS NOT NULL ORDER BY record_id", (seed, head[0])).fetchall():
                out.setdefault(rid, seed)
        if len(out) >= NEIGHBOR_LIMIT:
            break
    return {k: v for k, v in sorted(out.items())[:NEIGHBOR_LIMIT] if k not in claim_ids}


def gather(q: Any, ctx: InstallationContext, query: ContextQuery, *, limit: int = CANDIDATE_LIMIT) -> Gathered:
    """Everything retrieval decides inside one read snapshot ``q`` (the query environment too, merged under the caller's values)."""
    meta = meta_of(q)
    if q.execute("SELECT 1 FROM workspaces WHERE workspace_id = ?", (query.workspace_id,)).fetchone() is None:
        raise RecalithError("foreign_installation", "the query names a workspace this installation does not own")
    # The caller's values (a hook's adapter platform facts) override the resolved ones key by key (decision 0015).
    environment = {**provenance.environment_values_in(q, ctx, workspace_id=query.workspace_id), **query.environment}
    degraded: list[str] = []
    task_id, notes = resolve_task(q, query.task_id, query.workspace_id, session_id=query.session_id)
    degraded += notes
    eq = query.model_copy(update={"task_id": task_id, "environment": environment})
    qd = eq.model_dump(mode="json")
    family = fc.action_family(eq.workspace_id, qd.get("action"))
    words = fc.terms(eq.text)
    query_terms = set(words)
    state = index.state(q)
    backend = state["backend"] if state else "tokens"
    indexed = state["indexed"] if state else 0
    lag_docs, overflow = index.lagging(q, indexed) if indexed != meta["store_revision"] or state is None else ([], False)
    if overflow:
        degraded.append("lexical_index_stale")
    lagged = {(d.kind, d.record_id): d for d in lag_docs}

    keys = structural_keys(eq, family)
    hits: dict[tuple[str, str], index.Hit] = {}
    if state is not None:
        ids = set(index.lexical_ids(q, words, backend)) | set(index.structural_ids(q, keys))
        hits = index.docs(q, ids)
    for key, doc in lagged.items():
        hits.pop(key, None)
        if index.eligible(doc.kind, doc.status) and (set(doc.words) & query_terms or set(doc.keys) & set(keys)):
            hits[key] = index.Hit(doc.kind, doc.record_id, doc.revision, doc.status, doc.workspace_ids, doc.task_ids, doc.words, set(doc.keys))

    # Seeds: status and scope first (hot columns), then a cheap preliminary order; the cap counts eligible items only.
    idf = index.idf(q, words)
    seeds = []
    for (kind, rid), hit in hits.items():
        if kind != "claim" or not index.eligible(kind, hit.status) or not _prefilter(hit.workspace_ids, hit.task_ids, eq):
            continue
        prelim = sum(idf.get(w, 1.0) for w in hit.words if w in query_terms)
        seeds.append((-prelim, rid))
    seeds.sort()
    claim_ids = [rid for _p, rid in seeds[:SEED_LIMIT]]
    if task_id is not None:
        claim_ids += [c for c in task_claim_ids(q, task_id) if c not in claim_ids]
    if family is not None:
        claim_ids += [r[0] for r in q.execute("SELECT claim_id FROM claim_heads WHERE action_family_digest = ? AND status IN ('candidate', 'active', 'disputed') ORDER BY claim_id", (family,)).fetchall() if r[0] not in claim_ids]
    linked = neighbors(q, claim_ids[:limit])
    claim_ids += [c for c in linked if c not in claim_ids]

    questions = question_candidates(q, ctx, environment=eq.environment)

    budget = fc.DependencyBudget(None)
    entries: list[dict[str, Any]] = []
    considered = 0
    member_of = {m: qc for qc in questions for m in qc["members"]}
    claim_ids += [m for m in member_of if m not in claim_ids]
    for claim_id in claim_ids:
        head = records.head(q, "claim", claim_id)
        if head is None or head[1] not in fc.LIVE:
            continue
        claim = records.load(q, "claim", claim_id, head[0])
        if claim is None:
            continue
        considered += 1
        cand = claim_candidate(q, ctx, claim, environment=eq.environment)
        if claim_id in linked:
            cand["linked"] = linked[claim_id]
        if claim_id in member_of:
            entry = decide(q, ctx, cand, eq, family=family, query_terms=query_terms, budget=budget, claim=claim, idf=idf)
            if entry is not None:
                member_of[claim_id]["member_reasons"] = {k: f"a conflicting declaration matches ({v})" for k, v in fc.relevance(cand, eq.model_dump(mode="json"), query_terms=query_terms, family=family).get("reasons", {}).items()}
            continue
        entry = decide(q, ctx, cand, eq, family=family, query_terms=query_terms, budget=budget, claim=claim, idf=idf)
        if entry is not None:
            entries.append(entry)
    for qc in questions:
        entry = decide(q, ctx, qc, eq, family=family, query_terms=query_terms, budget=budget, idf=idf)
        if entry is not None:
            entries.append(entry)
    if task_id is not None:
        for cand in [c for c in [task_candidate(q, task_id)] if c] + episode_candidates(q, task_id) + observation_candidates(q, task_id):
            entry = decide(q, ctx, cand, eq, family=family, query_terms=query_terms, budget=budget, idf=idf)
            if entry is not None:
                entries.append(entry)
    if budget.skipped:
        degraded.append("deadline_dependency_unknown")
    if budget.exceeded:
        degraded.append("dependency_check_bounded")
    ranked = fc.order(entries)
    # The cap counts eligible claims only; the bound task, its episodes and its recent observations are their own bounded groups.
    claims = [e for e in ranked if e["item"]["ref"]["kind"] == "claim"]
    kept = {id(e) for e in claims[:limit]}
    out = [e for e in ranked if e["item"]["ref"]["kind"] != "claim" or id(e) in kept]
    return Gathered(out, meta, eq, degraded, considered, max(0, len(claims) - limit))


def retrieve(ctx: InstallationContext, query: ContextQuery, *, store: Store | None = None, limit: int = CANDIDATE_LIMIT) -> list[ContextItem]:
    """DATA_CONTRACTS §11: ranked, eligible, explained items (unbudgeted; :func:`compile_context` budgets and fences)."""
    own = store is None
    store = store or open_store(ctx, readonly=True)
    try:
        with store.read() as view:
            gathered = gather(view, ctx, query, limit=limit)
        return [ContextItem.model_validate(e["item"]) for e in gathered.entries]
    finally:
        if own:
            store.close()


def ref_of(item: ContextItem) -> RecordRef:
    return item.ref
