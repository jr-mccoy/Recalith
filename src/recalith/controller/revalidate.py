"""Revalidation: FailureRecheck, the dependency index and revalidation outcomes (SYSTEM_SPEC §3.5, §6.3, §7.2–§7.4; DATA_CONTRACTS §5, §8, §11).

**Rechecks.** Every reason a claim needs revalidation is one ``claim_rechecks``
row, keyed by claim, reason and the observation that caused it, so a replayed
or repeated cause records nothing twice: a certified later success of a
failure lesson's action family (FailureRecheck ``later_success``), the same
with ambiguous chronology (``order_unknown``), a changed dependency
(``dependency_changed``, also transitively through claim dependencies), an
unresolved source conflict (``source_conflict``), required evidence that is no
longer available (``support_lost``, Task 15: a forgetting override or a
reactivation over expired support), a due review (``review_due``) or a
consolidation group (``consolidation``). The first five
set ``needs_revalidation`` on live guidance and suppress caution at once
(:func:`mark`): a new claim revision with the counter-observation attached as
``context`` (never support, never ``contradicts``), the guidance epoch
advanced, a content-free audit operation, and a coalesced protected
revalidation job, all in the caller's transaction. A candidate is not
guidance: its rechecks are recorded ``deferred`` and take effect in the
transaction that activates it (:func:`apply_deferred`).

**FailureRecheck** (:func:`failure_recheck`) runs in the ingestion
transaction, before any model call and whatever the budget: a certified
success whose known action family matches a live failure lesson, in a
compatible workspace, *after* the lesson's latest supporting failure in
certified order (:func:`certified_order`), is a ``later_success``; known older
replay is nothing; ambiguous chronology, or a lesson without a supporting
failure reference, is ``order_unknown``. Unknown family or working directory
never matches (a null digest matches nothing), and identical argv in another
package directory is another family. It never asserts the historical failure
false and never invalidates anything.

**Dependency index** (:func:`dependents`, :func:`revalidate_dependents`): the
``dependencies`` rows of current claim revisions, by kind and key. A change
whose new fingerprint equals the recorded one preserves applicability; any
other change, an unknown new value included, marks the claim, then every live
claim depending on it (bounded, cycle-safe). Changes come from certified
writes and deletions (``artifact_writes``) and new environment observations.

**Settling** (:func:`settle`). A revalidation job's proposal applies through
``apply_proposal`` like any other; afterwards each of its claims' pending
rechecks is settled. A recheck clears only when the proposal's read set holds
the still-current claim revision (otherwise the proposal was requeued) and
the recheck's own observation. ``revise_claim``, a status change or a
confirming new failure settle it; a plain *keep* settles everything except a
``later_success`` on a failure lesson, which needs a revision with an explicit
retry condition (reviewed), a retirement, a dispute or a newer supporting
failure, and an unresolved source conflict, which only a new authoritative
observation resolves. When nothing that suppresses caution remains, the
claim is ``current`` again and its next review is due a full period later.

:func:`guidance` is the deterministic advice gate Task 11 consumes: scope,
conditions, the failure-lesson dependency gate over current fingerprints, and
freshness; ``caution`` needs all of them ``true``/``current``.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from recalith.contracts.common import EvidenceLink, InstallationContext, ReadSet, RecordRef, canonical_json, derived_id, digest_of, format_utc, parse_utc, utc_now
from recalith.contracts.context import ContextQuery
from recalith.contracts.events import EventEnvelope
from recalith.contracts.jobs import DependencyChange, FailureRecheck, Job
from recalith.contracts.memory import ClaimRevision
from recalith.core import conditions, lineage, policy
from recalith.errors import RecalithError
from recalith.fast import failpoints
from recalith.storage import records
from recalith.storage.db import Store, Txn, open_store

LIVE = frozenset({"candidate", "active", "disputed"})
GUIDANCE = frozenset({"active", "disputed"})
FRESHNESS_REASONS = frozenset({"later_success", "order_unknown", "dependency_changed", "source_conflict", "support_lost"})
# Reasons a model can settle. A source conflict waits for a new authoritative observation. A ``support_lost`` keep
# never restores strength or availability: strength counts only support that is still available (Task 15).
MODEL_REASONS = frozenset({"later_success", "order_unknown", "dependency_changed", "review_due", "consolidation", "support_lost"})
RECHECK_REF = "@recheck"
SETTLE_REF = "@settle"
RECHECK_KIND = "recheck"
SETTLE_KIND = "revalidation"
REVALIDATION_BATCH = 8
SETTLED = "revalidation_settled"  # a revalidation job with nothing a model can settle, cancelled without a call
TRANSITIVE_LIMIT = 256
DEPENDENCY_DEPTH = 16
WRITE_KINDS = frozenset({"write", "delete"})


# --------------------------------------------------------------------------
# Events and certified order


def stored_event(q: Any, event_id: str) -> EventEnvelope | None:
    row = q.execute("SELECT envelope, payload, payload_state FROM events WHERE event_id = ?", (event_id,)).fetchone()
    if row is None or row[1] is None or row[2] != "available":
        return None
    body = json.loads(row[0])
    body["payload"] = json.loads(row[1])
    return EventEnvelope.model_validate(body)


def certified_result(env: EventEnvelope) -> bool:
    return env.kind == "tool_finished" and env.channel == "tool" and env.authority == "observed_tool" and not env.derived_from and env.payload.get("result_received") is True


def certified_order(first: EventEnvelope, second: EventEnvelope) -> str:
    """Whether ``second`` happened ``after`` or ``before`` ``first`` in certified order, else ``unknown``.

    Certified, in this order: the adapter's source sequence within one host
    session and origin stream; the adapter-reported occurrence time of both;
    the capture time of two live, synchronous host hooks of one certified
    adapter (both under tool authority). Never commit order or the time the
    worker processed them: ingestion order says nothing about chronology, so
    an old replay or a late-delivered segment cannot assert a later success.
    """

    def compare(a: Any, b: Any) -> str:
        if a == b:
            return "unknown"
        return "after" if b > a else "before"

    same_stream = (first.adapter_id, first.host_session_id, first.origin.origin_kind) == (second.adapter_id, second.host_session_id, second.origin.origin_kind)
    if same_stream and first.source_sequence is not None and second.source_sequence is not None:
        return compare(first.source_sequence, second.source_sequence)
    if first.occurred_at is not None and second.occurred_at is not None:
        return compare(first.occurred_at, second.occurred_at)
    live = all(e.origin.origin_kind == "hook" and e.authority == "observed_tool" and e.occurred_at is None for e in (first, second))
    if live and first.adapter_id == second.adapter_id:
        return compare(first.recorded_at, second.recorded_at)
    return "unknown"


def _event_link(event_id: str) -> EvidenceLink:
    return EvidenceLink(ref=RecordRef(kind="event", id=event_id, revision=1), relation="context", root_event_ids=[event_id])


# --------------------------------------------------------------------------
# Recheck rows


RECHECK_COLUMNS = ("recheck_id", "claim_id", "claim_revision", "reason", "event_id", "detail", "state", "outcome", "job_id", "causal_root", "created_at", "settled_at")


def recheck_id(claim_id: str, reason: str, key: str) -> str:
    return derived_id("rchk", [claim_id, reason, key])


def rechecks(q: Any, claim_id: str | None = None, *, states: Sequence[str] = ("pending", "deferred", "cleared")) -> list[dict[str, Any]]:
    marks = ",".join("?" for _ in states)
    sql = f"SELECT {', '.join(RECHECK_COLUMNS)} FROM claim_rechecks WHERE state IN ({marks})"  # noqa: S608 - fixed names
    params: tuple = tuple(states)
    if claim_id is not None:
        sql += " AND claim_id = ?"
        params += (claim_id,)
    rows = q.execute(sql + " ORDER BY created_at, recheck_id", params).fetchall()
    out = []
    for row in rows:
        item = dict(zip(RECHECK_COLUMNS, row, strict=True))
        item["detail"] = json.loads(item["detail"])
        out.append(item)
    return out


def pending(q: Any, claim_id: str) -> list[dict[str, Any]]:
    return rechecks(q, claim_id, states=("pending",))


def _insert(txn: Txn, rid: str, *, claim_id: str, revision: int | None, reason: str, event_id: str | None, detail: Mapping[str, Any], state: str, causal_root: str | None, now: str) -> bool:
    if txn.one("SELECT 1 FROM claim_rechecks WHERE recheck_id = ?", (rid,)) is not None:
        return False
    txn.execute(
        "INSERT INTO claim_rechecks (recheck_id, claim_id, claim_revision, reason, event_id, detail, state, causal_root, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rid, claim_id, revision, reason, event_id, canonical_json(dict(detail)).decode(), state, causal_root, now),
    )
    txn.mutated(serving_relevant=False)
    return True


def _clear(txn: Txn, rid: str, outcome: str, *, now: str) -> None:
    txn.execute("UPDATE claim_rechecks SET state = 'cleared', outcome = ?, settled_at = ? WHERE recheck_id = ?", (outcome[:64], now, rid))
    txn.mutated(serving_relevant=False)


def _note(txn: Txn, rid: str, outcome: str) -> None:
    txn.execute("UPDATE claim_rechecks SET outcome = ? WHERE recheck_id = ?", (outcome[:64], rid))


def _audit(txn: Txn, ctx: InstallationContext, *, scope: str, kind: str, local_ref: str, inputs: Mapping[str, Any], changed: list[dict[str, Any]], causal_root: str | None, now: str) -> str:
    """A content-free operation row for a deterministic revision (the revision audit)."""
    oid = derived_id("op", [scope, local_ref])
    txn.execute(
        "INSERT OR IGNORE INTO operations (operation_id, job_id, proposal_id, atomic_group_id, actor, kind, inputs, changed, reason, causal_root, store_revision, created_at, local_ref, proposal_digest) VALUES (?, NULL, NULL, NULL, ?, ?, ?, ?, NULL, ?, ?, ?, ?, NULL)",
        (oid, canonical_json(ctx.actor).decode(), kind, canonical_json(dict(inputs)).decode(), canonical_json(changed).decode(), causal_root, txn.next_store_revision, now, local_ref),
    )
    return oid


def _merge_link(links: list[dict[str, Any]], link: EvidenceLink) -> bool:
    dumped = link.model_dump(mode="json")
    if any(records.link_identity(EvidenceLink.model_validate(item)) == records.link_identity(link) for item in links):
        return False
    links.append(dumped)
    return True


def _write(txn: Txn, data: dict[str, Any], *, now: str) -> RecordRef:
    data["revision"] += 1
    data["recorded_at"] = now
    claim = ClaimRevision.model_validate_json(json.dumps(data))
    return records.write_claim(txn, claim)


# --------------------------------------------------------------------------
# Marking


def mark(
    txn: Txn,
    ctx: InstallationContext,
    claim_id: str,
    *,
    reason: str,
    key: str,
    event_id: str | None,
    detail: Mapping[str, Any],
    context: EvidenceLink | None,
    now: str,
    causal_root: str | None,
    _depth: int = 0,
    _seen: set[str] | None = None,
) -> list[str]:
    """Record one recheck for a live claim; returns the claims it marked (itself and dependents).

    Live guidance gets a new revision (``needs_revalidation`` for the freshness
    reasons, review due now, the counter-observation as ``context``) and the
    guidance epoch advances; a candidate's recheck waits ``deferred`` for its
    activation. Idempotent per claim, reason and key.
    """
    seen = set() if _seen is None else _seen
    if claim_id in seen or len(seen) >= TRANSITIVE_LIMIT:
        return []
    seen.add(claim_id)
    head = records.head(txn, "claim", claim_id)
    if head is None or head[1] not in LIVE:
        return []
    rid = recheck_id(claim_id, reason, key)
    if txn.one("SELECT 1 FROM claim_rechecks WHERE recheck_id = ?", (rid,)) is not None:
        return []
    stored = {**detail, **({"context": context.model_dump(mode="json")} if context is not None else {})}
    if head[1] == "candidate":
        _insert(txn, rid, claim_id=claim_id, revision=None, reason=reason, event_id=event_id, detail=stored, state="deferred", causal_root=causal_root, now=now)
        return [claim_id]
    data = records.body(txn, "claim", claim_id, head[0])
    assert data is not None
    changed = False
    if reason in FRESHNESS_REASONS and data["freshness"] != "needs_revalidation":
        data["freshness"] = "needs_revalidation"
        changed = True
    if reason in FRESHNESS_REASONS and (data.get("review_due_at") is None or data["review_due_at"] > now):
        data["review_due_at"] = now  # a changed dependency or counter-observation makes review due early
        changed = True
    data.setdefault("context", [])
    if context is not None and _merge_link(data["context"], context):
        changed = True
    revision = head[0]
    if changed:
        ref = _write(txn, data, now=now)
        revision = ref.revision
        _audit(txn, ctx, scope=rid, kind=RECHECK_KIND, local_ref=RECHECK_REF, inputs={"recheck_id": rid, "reason": reason, "detail": dict(detail)},
               changed=[{"ref": ref.model_dump(mode="json"), "before": head[0]}], causal_root=causal_root, now=now)
        txn.mutated(serving_relevant=True)
    _insert(txn, rid, claim_id=claim_id, revision=revision, reason=reason, event_id=event_id, detail=stored, state="pending", causal_root=causal_root, now=now)
    failpoints.hit(failpoints.RECHECK_AFTER_MARK)
    out = [claim_id]
    if reason in FRESHNESS_REASONS and _depth < DEPENDENCY_DEPTH:
        for dependent in claim_dependents(txn, claim_id):
            out += mark(txn, ctx, dependent, reason="dependency_changed", key=f"{key}:via:{claim_id}", event_id=event_id, detail={"via_claim": claim_id, "cause": reason},
                        context=None, now=now, causal_root=causal_root, _depth=_depth + 1, _seen=seen)
    return out


def claim_dependents(q: Any, claim_id: str) -> list[str]:
    """Live claims whose current revision depends on ``claim_id`` (the claim-dependency index)."""
    rows = q.execute(
        "SELECT DISTINCT d.claim_id FROM dependencies d JOIN claim_heads h ON h.claim_id = d.claim_id AND h.revision = d.claim_revision "
        "WHERE d.kind = 'claim' AND d.record_id = ? AND h.status IN ('candidate', 'active', 'disputed') ORDER BY d.claim_id",
        (claim_id,),
    ).fetchall()
    return [r[0] for r in rows if r[0] != claim_id]


def apply_deferred(q: Any, claim_id: str, data: dict[str, Any], *, now: str) -> list[dict[str, Any]]:
    """Fold a candidate's deferred rechecks into the revision that activates it (caller writes it)."""
    rows = rechecks(q, claim_id, states=("deferred",))
    data.setdefault("context", [])
    for row in rows:
        if row["reason"] in FRESHNESS_REASONS:
            data["freshness"] = "needs_revalidation"
            data["review_due_at"] = now
        link = row["detail"].get("context")
        if link is not None:
            _merge_link(data["context"], EvidenceLink.model_validate(link))
    return rows


def promote_deferred(txn: Txn, rows: Sequence[dict[str, Any]], *, revision: int, now: str) -> list[str]:
    """After activation: deferred rechecks become pending on the activated revision; returns their claims."""
    claims = []
    for row in rows:
        txn.execute("UPDATE claim_rechecks SET state = 'pending', claim_revision = ? WHERE recheck_id = ? AND state = 'deferred'", (revision, row["recheck_id"]))
        claims.append(row["claim_id"])
    if rows:
        txn.mutated(serving_relevant=True)
    return sorted(set(claims))


# --------------------------------------------------------------------------
# Revalidation jobs


def enqueue(txn: Txn, claim_ids: Iterable[str], *, now: str, consolidation: bool = False) -> list[str]:
    """Coalesced protected revalidation jobs for these claims (batches of eight); returns created job IDs.

    A pending (not yet leased) revalidation job of the same band naming one of
    the claims is absorbed: its live claims join this request, and it is
    cancelled (``coalesced``) unless it already is exactly one of the new
    batches. Each job names its claims at their current heads and the
    observations of their pending rechecks, so its read set can settle them.
    A consolidation group stays one job of its own.
    """
    from recalith import prompts
    from recalith.controller import jobs
    from recalith.storage.repository import idempotency_key

    def live(c: str) -> bool:
        return (records.head(txn, "claim", c) or (0, ""))[1] in LIVE

    wanted = {c for c in claim_ids if live(c)}
    if not wanted:
        return []
    band = jobs.BAND_CONSOLIDATION if consolidation else jobs.BAND_REVALIDATION
    absorbed: list[Job] = []
    if not consolidation:
        for (body,) in txn.execute("SELECT body FROM jobs WHERE kind = 'revalidate' AND state IN ('pending', 'waiting_budget') AND priority = ? ORDER BY job_id", (band,)).fetchall():
            older = Job.model_validate_json(body)
            names = {r.id for r in older.input_refs if r.kind == "claim"}
            if names & wanted:
                wanted |= {c for c in names if live(c)}
                absorbed.append(older)
    ordered = sorted(wanted)
    batches = []
    for i in range(0, len(ordered), REVALIDATION_BATCH):
        batch = ordered[i : i + REVALIDATION_BATCH]
        refs = [RecordRef(kind="claim", id=c, revision=records.head(txn, "claim", c)[0]) for c in batch]  # type: ignore[index]
        events = sorted({r["event_id"] for c in batch for r in pending(txn, c) if r["event_id"]})
        batches.append((batch, refs + [RecordRef(kind="event", id=e, revision=1) for e in events]))
    keep: dict[int, str] = {}
    for older in absorbed:
        same = next((i for i, (_b, refs) in enumerate(batches) if i not in keep and sorted(r.model_dump_json() for r in refs) == sorted(r.model_dump_json() for r in older.input_refs)), None)
        if same is not None:
            keep[same] = older.job_id
        else:
            jobs.supersede(txn, older, jobs.COALESCED)
    created = []
    prompt = prompts.CURRENT["revalidate"]
    for i, (batch, refs) in enumerate(batches):
        job_id = keep.get(i)
        if job_id is None:
            key = idempotency_key("revalidate", refs, policy_revision=txn.meta.policy_revision, prompt_version=prompt, tombstone_epoch=txn.meta.tombstone_epoch)
            existing = txn.one("SELECT state FROM jobs WHERE idempotency_key = ?", (key,))
            if existing is not None and existing[0] not in ("pending", "waiting_budget", "leased"):
                key = digest_of([key, "again", txn.next_store_revision, now])  # the same request again after an earlier one ended
            job_id, new = jobs.enqueue(txn, kind="revalidate", input_refs=refs, now=now, prompt_version=prompt, priority=band, idempotency=key)
            if new:
                created.append(job_id)
        for c in batch:
            txn.execute("UPDATE claim_rechecks SET job_id = ? WHERE claim_id = ? AND state = 'pending'", (job_id, c))
    return created


def needs_model(q: Any, job: Job) -> bool:
    """Whether any claim of a revalidation job has a pending recheck a model can settle."""
    for ref in job.input_refs:
        if ref.kind != "claim":
            continue
        head = records.head(q, "claim", ref.id)
        if head is None or head[1] not in LIVE:
            continue
        if any(r["reason"] in MODEL_REASONS for r in pending(q, ref.id)):
            return True
    return False


def request_events(q: Any, claim_ids: Iterable[str]) -> list[str]:
    """The observations of these claims' pending rechecks: a revalidation request consults them (read set)."""
    return sorted({r["event_id"] for c in claim_ids for r in pending(q, c) if r["event_id"]})


# --------------------------------------------------------------------------
# FailureRecheck (ingestion transaction)


def failure_recheck(txn: Txn, ctx: InstallationContext, env: EventEnvelope, *, now: str) -> list[str]:
    """A certified success against live failure lessons of its known action family; returns marked claims."""
    from recalith.capture.normalize import action_family_digest

    if not certified_result(env) or env.payload.get("outcome") != "success":
        return []
    action = env.payload.get("action")
    family = action_family_digest(env.workspace_id, action) if isinstance(action, dict) else None
    if family is None:
        return []  # unknown working directory or parse: never matched by resemblance
    rows = txn.execute(
        "SELECT claim_id, revision FROM claim_heads WHERE action_family_digest = ? AND kind = 'failure_lesson' AND status IN ('candidate', 'active', 'disputed') ORDER BY claim_id",
        (family,),
    ).fetchall()
    marked: list[str] = []
    for claim_id, revision in rows:
        data = records.body(txn, "claim", claim_id, revision)
        if data is None:
            continue
        workspaces = data["scope"].get("workspace_ids") or []
        if workspaces and env.workspace_id not in workspaces:
            continue
        cited = {link["ref"]["id"] for link in [*data["supports"], *data.get("contradicts", []), *data.get("context", [])]}
        if env.event_id in cited:
            continue
        failure_id = (data.get("failure") or {}).get("last_supporting_failure_event_id")
        failure = stored_event(txn, failure_id) if failure_id else None
        if failure is None:
            reason = "order_unknown"  # no supporting failure to order against: an uncertainty trigger only
        else:
            order = certified_order(failure, env)
            if order == "before":
                continue  # known older replay or a late-delivered earlier success: not a counter-observation
            reason = "later_success" if order == "after" else "order_unknown"
        detail = FailureRecheck(
            claim_ref=RecordRef(kind="claim", id=claim_id, revision=revision), success_event_id=env.event_id,
            supporting_failure_event_id=failure_id if failure is not None else None, reason=reason, action_family_digest=family,  # type: ignore[arg-type]
        ).model_dump(mode="json")
        marked += mark(txn, ctx, claim_id, reason=reason, key=env.event_id, event_id=env.event_id, detail=detail, context=_event_link(env.event_id), now=now, causal_root=env.event_id)
    return marked


# --------------------------------------------------------------------------
# The dependency index


def file_writes(env: EventEnvelope) -> list[str]:
    """Workspace paths a certified result wrote or deleted (exact parse only)."""
    if env.kind == "artifact_changed" and env.authority == "observed_tool" and not env.derived_from:
        paths = env.payload.get("paths") or ([env.payload["path"]] if isinstance(env.payload.get("path"), str) else [])
        return sorted({p for p in paths if isinstance(p, str)})
    if not certified_result(env):
        return []
    action = env.payload.get("action")
    if not isinstance(action, dict) or action.get("parse_status") != "exact" or action.get("action_kind") not in WRITE_KINDS:
        return []
    return sorted({p for p in action.get("paths") or [] if isinstance(p, str)})


def environment_fingerprint(key: str, value: str) -> str:
    return digest_of(["environment", key, value])


def changes_for_event(txn: Txn, env: EventEnvelope, observations: Sequence[str]) -> list[DependencyChange]:
    """Dependency changes one newly ingested event shows (records ``artifact_writes`` as it goes)."""
    changes = []
    seq = txn.one("SELECT commit_sequence FROM events WHERE event_id = ?", (env.event_id,))
    for path in file_writes(env):
        txn.execute("INSERT OR IGNORE INTO artifact_writes (event_id, path, commit_sequence) VALUES (?, ?, ?)", (env.event_id, path, seq[0] if seq else 0))
        changes.append(DependencyChange(kind="file", key=path, old_fingerprint=None, new_fingerprint=None, supporting_event_id=env.event_id))
    for oid in observations:
        row = txn.one("SELECT key, value, freshness FROM environment_observations WHERE observation_id = ?", (oid,))
        if row is not None and row[2] == "current":
            changes.append(DependencyChange(kind="environment", key=row[0], old_fingerprint=None, new_fingerprint=environment_fingerprint(row[0], row[1]), supporting_event_id=env.event_id))
    return changes


def dependents(txn: Txn, ctx: InstallationContext, changes: Sequence[DependencyChange], *, now: str) -> list[str]:
    """Mark the live claims whose current revision depends on a changed key (and their dependents)."""
    marked: list[str] = []
    for change in changes:
        rows = txn.execute(
            "SELECT d.claim_id, d.fingerprint FROM dependencies d JOIN claim_heads h ON h.claim_id = d.claim_id AND h.revision = d.claim_revision "
            "WHERE d.kind = ? AND d.key = ? AND h.status IN ('candidate', 'active', 'disputed') ORDER BY d.claim_id",
            (change.kind, change.key),
        ).fetchall()
        for claim_id, recorded in rows:
            if change.new_fingerprint is not None and recorded == change.new_fingerprint:
                continue  # dependency-preserving: applicability is unchanged
            event_link = _event_link(change.supporting_event_id) if txn.one("SELECT 1 FROM events WHERE event_id = ?", (change.supporting_event_id,)) else None
            marked += mark(txn, ctx, claim_id, reason="dependency_changed", key=f"{change.supporting_event_id}:{change.kind}:{change.key}", event_id=change.supporting_event_id,
                           detail=change.model_dump(mode="json"), context=event_link, now=now, causal_root=change.supporting_event_id)
    return marked


def revalidate_dependents(ctx: InstallationContext, changes: Sequence[DependencyChange], *, store: Store | None = None, now: str | None = None) -> list[str]:
    """DATA_CONTRACTS §11: mark dependents of changed dependencies and enqueue their revalidation; returns claim IDs."""
    own = store is None
    store = store or open_store(ctx)
    now = now or utc_now()
    try:
        with store.transaction() as txn:
            for change in changes:
                if txn.one("SELECT 1 FROM events WHERE event_id = ?", (change.supporting_event_id,)) is None:
                    raise RecalithError("invalid_schema", "a dependency change cites an event of this installation")
            marked = dependents(txn, ctx, changes, now=now)
            enqueue(txn, [c for c in marked if model_pending(txn, c)], now=now)
        return sorted(set(marked))
    finally:
        if own:
            store.close()


def model_pending(q: Any, claim_id: str) -> bool:
    return any(r["reason"] in MODEL_REASONS for r in pending(q, claim_id))


# --------------------------------------------------------------------------
# Ingestion entry points


def on_ingested(txn: Txn, ctx: InstallationContext, env: EventEnvelope, *, observations: Sequence[str], now: str) -> list[str]:
    """FailureRecheck and dependency changes for one newly inserted event, in its ingestion transaction."""
    marked = failure_recheck(txn, ctx, env, now=now)
    marked += dependents(txn, ctx, changes_for_event(txn, env, observations), now=now)
    return marked


def on_conflict(txn: Txn, ctx: InstallationContext, original_event_id: str, conflict_id: str, *, now: str) -> list[str]:
    """An unresolved source conflict: guidance citing the original event needs revalidation and gives no caution."""
    marked: list[str] = []
    for ref in lineage.claims_citing(txn, [original_event_id]):
        marked += mark(txn, ctx, ref.id, reason="source_conflict", key=conflict_id, event_id=original_event_id, detail={"conflict_id": conflict_id}, context=None, now=now, causal_root=original_event_id)
    return marked


def after_merge(txn: Txn, ctx: InstallationContext, claims: Sequence[RecordRef], *, now: str) -> list[RecordRef]:
    """Merged root classes: recompute the strength of affected guidance now (deterministic, no model)."""
    from recalith.controller import admission

    changed = []
    for ref in claims:
        head = records.head(txn, "claim", ref.id)
        if head is None or head[1] not in GUIDANCE:
            continue
        data = records.body(txn, "claim", ref.id, head[0])
        assert data is not None
        strength = admission.assign_strength(txn, data)
        if strength != data["strength"]:
            data["strength"] = strength
            new = _write(txn, data, now=now)
            _audit(txn, ctx, scope=derived_id("rchk", [ref.id, "root_merge", str(head[0])]), kind=RECHECK_KIND, local_ref=RECHECK_REF, inputs={"reason": "root_merge"},
                   changed=[{"ref": new.model_dump(mode="json"), "before": head[0]}], causal_root=None, now=now)
            txn.mutated(serving_relevant=True)
            changed.append(new)
    return changed


# --------------------------------------------------------------------------
# Settling a revalidation job's result


def covered(row: Mapping[str, Any], read_events: set[str]) -> bool:
    return row["event_id"] is None or row["event_id"] in read_events


def revision_freshness(q: Any, claim_id: str, read_set: ReadSet | None) -> str:
    """The freshness a revalidation's own revision of this claim may claim: current only when it read every cause."""
    rows = [r for r in pending(q, claim_id) if r["reason"] in FRESHNESS_REASONS]
    if not rows:
        return "current"
    events = {r.id for r in read_set.entity_revisions if r.kind == "event"} if read_set is not None else set()
    if any(not covered(r, events) or r["reason"] == "source_conflict" for r in rows):
        return "needs_revalidation"
    return "current"


def _reconfirmed(q: Any, data: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    """A newer certified supporting failure after the success: the lesson is reconfirmed."""
    failure_id = (data.get("failure") or {}).get("last_supporting_failure_event_id")
    success = stored_event(q, row["event_id"]) if row["event_id"] else None
    failure = stored_event(q, failure_id) if failure_id else None
    return failure is not None and success is not None and certified_order(success, failure) == "after"


@dataclass
class Settled:
    refs: list[RecordRef] = field(default_factory=list)
    serving: bool = False
    outcomes: dict[str, list[str]] = field(default_factory=dict)


def settle(txn: Txn, ctx: InstallationContext, job: Job, read_set: ReadSet, *, decided: Mapping[str, str], now: str) -> Settled:
    """Settle the pending rechecks of a revalidation job's claims after its proposal applied.

    ``decided`` maps a claim this proposal changed to the operation kind that
    changed it. Runs inside the application transaction.
    """
    from recalith.controller import admission

    out = Settled()
    read = {r.id: r.revision for r in read_set.entity_revisions if r.kind == "claim"}
    read_events = {r.id for r in read_set.entity_revisions if r.kind == "event"}
    for ref in job.input_refs:
        if ref.kind != "claim" or ref.id in out.outcomes:
            continue
        rows = pending(txn, ref.id)
        head = records.head(txn, "claim", ref.id)
        codes: list[str] = []
        out.outcomes[ref.id] = codes
        if head is None or head[1] not in LIVE:
            for row in rows:
                _clear(txn, row["recheck_id"], "retired", now=now)
                codes.append("retired")
            continue
        if not rows or ref.id not in read:
            continue
        data = records.body(txn, "claim", ref.id, head[0])
        assert data is not None
        kind = decided.get(ref.id)
        remaining = []
        for row in rows:
            if not covered(row, read_events):
                _note(txn, row["recheck_id"], "counter_observation_unread")
                remaining.append(row)
                codes.append("counter_observation_unread")
                continue
            if row["reason"] == "source_conflict":
                supports = [EvidenceLink.model_validate(i) for i in data["supports"]]
                if lineage.resolve(txn, supports, proposition_key=data.get("proposition_key")).needs_revalidation:
                    _note(txn, row["recheck_id"], "source_conflict_unresolved")
                    remaining.append(row)
                    codes.append("source_conflict_unresolved")
                    continue
                outcome = "conflict_resolved"
            elif kind == "revise_claim":
                outcome = "revised"
            elif kind == "change_claim_status":
                outcome = head[1]
            elif row["reason"] == "later_success" and data["kind"] == "failure_lesson":
                if not _reconfirmed(txn, data, row):
                    _note(txn, row["recheck_id"], "retain_requires_retry_condition")
                    remaining.append(row)
                    codes.append("retain_requires_retry_condition")
                    continue
                outcome = "reconfirmed"
            else:
                outcome = "kept"
            _clear(txn, row["recheck_id"], outcome, now=now)
            codes.append(outcome)
        cleared = len(rows) - len(remaining)
        if not cleared:
            continue
        changed = False
        if not any(r["reason"] in FRESHNESS_REASONS for r in remaining) and data["freshness"] == "needs_revalidation":
            data["freshness"] = "current"
            changed = True
        if not remaining:
            due = format_utc(policy.review_due(parse_utc(now), data["review_class"]))
            if data.get("review_due_at") != due:
                data["review_due_at"] = due
                changed = True
        strength = admission.assign_strength(txn, data)
        if strength != data["strength"]:
            data["strength"] = strength
            changed = True
        if changed:
            new = _write(txn, data, now=now)
            _audit(txn, ctx, scope=f"{job.job_id}:{ref.id}", kind=SETTLE_KIND, local_ref=SETTLE_REF, inputs={"job_id": job.job_id, "claim_id": ref.id, "outcomes": codes},
                   changed=[{"ref": new.model_dump(mode="json"), "before": head[0]}], causal_root=job.job_id, now=now)
            out.refs.append(new)
            out.serving = True
    failpoints.hit(failpoints.REVALIDATE_AFTER_SETTLE)
    return out


# --------------------------------------------------------------------------
# Pending supersessions (explicit replacement of active guidance)


def record_pending_supersession(txn: Txn, *, replacement_id: str, target: RecordRef, operation_id: str, now: str) -> None:
    txn.execute(
        "INSERT INTO pending_supersessions (replacement_id, target_id, target_revision, operation_id, state, created_at) VALUES (?, ?, ?, ?, 'pending', ?) "
        "ON CONFLICT(replacement_id, target_id) DO UPDATE SET target_revision = excluded.target_revision, operation_id = excluded.operation_id, state = 'pending', decided_at = NULL",
        (replacement_id, target.id, target.revision, operation_id, now),
    )
    txn.mutated(serving_relevant=False)


def pending_supersessions(q: Any, replacement_id: str) -> list[tuple[str, int]]:
    return [(r[0], r[1]) for r in q.execute("SELECT target_id, target_revision FROM pending_supersessions WHERE replacement_id = ? AND state = 'pending' ORDER BY target_id", (replacement_id,)).fetchall()]


def decide_supersession(txn: Txn, replacement_id: str, target_id: str, state: str, *, now: str) -> None:
    txn.execute("UPDATE pending_supersessions SET state = ?, decided_at = ? WHERE replacement_id = ? AND target_id = ?", (state, now, replacement_id, target_id))
    txn.mutated(serving_relevant=False)


def withdraw_supersessions(txn: Txn, replacement_id: str, *, now: str) -> None:
    for target_id, _rev in pending_supersessions(txn, replacement_id):
        decide_supersession(txn, replacement_id, target_id, "withdrawn", now=now)


def withdraw_target(txn: Txn, target_id: str, *, now: str) -> None:
    """A retired target: other replacements waiting to supersede it can no longer apply (stale)."""
    for (replacement_id,) in txn.execute("SELECT replacement_id FROM pending_supersessions WHERE target_id = ? AND state = 'pending' ORDER BY replacement_id", (target_id,)).fetchall():
        decide_supersession(txn, replacement_id, target_id, "stale", now=now)


# --------------------------------------------------------------------------
# Dependencies at admission and the review class


def claim_fingerprint(q: Any, claim_id: str) -> str | None:
    """A claim dependency's value: its content and whether it is still guidance (bookkeeping revisions keep it)."""
    head = records.head(q, "claim", claim_id)
    if head is None:
        return None
    data = records.body(q, "claim", claim_id, head[0])
    if data is None:
        return digest_of(["claim", claim_id, head[1]])
    claim = ClaimRevision.model_validate_json(json.dumps(data))
    return digest_of(["claim", claim_id, records.content_key(claim), "guidance" if head[1] in GUIDANCE else head[1]])


def _environment_now(q: Any, workspace_id: str, key: str) -> str | None:
    rows = q.execute("SELECT DISTINCT value FROM environment_observations WHERE workspace_id = ? AND key = ? AND freshness = 'current'", (workspace_id, key)).fetchall()
    return environment_fingerprint(key, rows[0][0]) if len(rows) == 1 else None


def _latest_evidence_sequence(q: Any, evidence: Sequence[EvidenceLink]) -> int:
    seqs = [q.execute("SELECT commit_sequence FROM events WHERE event_id = ?", (link.ref.id,)).fetchone() for link in evidence if link.ref.kind == "event"]
    return max((s[0] for s in seqs if s is not None), default=0)


def resolve_dependencies(q: Any, ctx: InstallationContext, dependencies: Sequence[Any], evidence: Sequence[EvidenceLink]) -> tuple[str | None, list[dict[str, Any]]]:
    """(refusal, resolved dependency dicts): every fingerprint follows its registered resolution rule.

    ``file``: the current workspace bytes, but unknown (null) when a certified
    write to the path was observed after the claim's latest event evidence;
    ``environment``: the one current observed value; ``config``: unknown (no
    registered parser); ``claim``: the dependency's content fingerprint. A
    proposed fingerprint must equal the resolved one; a null one is filled.
    """
    from recalith.controller import admission

    out = []
    since = _latest_evidence_sequence(q, evidence)
    for dep in dependencies:
        d = dep.model_dump(mode="json") if hasattr(dep, "model_dump") else dict(dep)
        if d["kind"] == "file":
            current = admission.current_fingerprint(ctx, "file:" + d["key"])
            if q.execute("SELECT 1 FROM artifact_writes WHERE path = ? AND commit_sequence > ?", (d["key"], since)).fetchone() is not None:
                current = None  # changed after the evidence: the observed state is unknown
        elif d["kind"] == "environment":
            current = _environment_now(q, ctx.workspace_id, d["key"])
        elif d["kind"] == "config":
            current = None
        else:
            record = d.get("record") or {}
            if not records.revision_exists(q, "claim", record.get("id", ""), record.get("revision", 0)):
                return "dependency_claim_missing", []
            current = claim_fingerprint(q, record["id"])
        if d.get("fingerprint") is not None and d["fingerprint"] != current:
            return "dependency_fingerprint_mismatch", []
        out.append({**d, "fingerprint": current})
    return None, out


def review_class(q: Any, *, kind: str, basis: str, dependencies: Sequence[Any], claim_id: str | None = None) -> tuple[str, list[str]]:
    """SYSTEM_SPEC §6.3 deterministically, with the reasons (A51).

    Volatile: any file/config/environment dependency, any volatile, missing or
    cyclic transitive claim dependency, a failure lesson, and every case not
    listed as stable. Stable: a user-declared decision or preference with no
    dependencies at all.
    """
    deps = [d.model_dump(mode="json") if hasattr(d, "model_dump") else dict(d) for d in dependencies]
    reasons: list[str] = []
    if kind == "failure_lesson":
        reasons.append("failure_lesson")
    if any(d["kind"] in ("file", "config", "environment") for d in deps):
        reasons.append("external_dependency")
    seen: set[str] = {claim_id} if claim_id else set()
    stack = [((d.get("record") or {}).get("id"), 1) for d in deps if d["kind"] == "claim"]
    while stack:
        claim_id, depth = stack.pop()
        if claim_id is None or depth > DEPENDENCY_DEPTH:
            reasons.append("claim_dependency_unknown")
            continue
        if claim_id in seen:
            reasons.append("claim_dependency_cycle")
            continue
        seen.add(claim_id)
        head = records.head(q, "claim", claim_id)
        data = records.body(q, "claim", claim_id, head[0]) if head is not None else None
        if data is None:
            reasons.append("claim_dependency_unknown")
            continue
        if data.get("review_class") != "stable":
            reasons.append("volatile_claim_dependency")
        stack += [((d.get("record") or {}).get("id"), depth + 1) for d in data.get("dependencies") or [] if d["kind"] == "claim"]
    if not reasons and policy.review_class(kind=kind, basis=basis, dependencies=deps) == "stable":
        return "stable", ["declared_without_dependencies"]
    return "volatile", sorted(set(reasons)) or ["default_volatile"]


# --------------------------------------------------------------------------
# The advice gate (Task 11 consumes it)


@dataclass(frozen=True)
class Guidance:
    advice: str | None  # caution | context | conflict | None (excluded)
    applicability: str
    dependency: str | None
    freshness: str
    reasons: tuple[str, ...]


def current_dependencies(q: Any, ctx: InstallationContext, dependencies: Sequence[Any], query: ContextQuery) -> dict[str, str | None]:
    """Current values for the dependency gate: live file bytes, the query's environment, claim content; config unknown."""
    from recalith.controller import admission

    out: dict[str, str | None] = {}
    for dep in dependencies:
        key = f"{dep.kind}:{dep.key}"
        if dep.kind == "file":
            out[key] = admission.current_fingerprint(ctx, "file:" + dep.key)
        elif dep.kind == "environment":
            value = query.environment.get(dep.key)
            out[key] = environment_fingerprint(dep.key, value) if value is not None else None
        elif dep.kind == "claim" and dep.record is not None:
            out[key] = claim_fingerprint(q, dep.record.id)
        else:
            out[key] = None
    return out


def guidance(q: Any, ctx: InstallationContext, claim: ClaimRevision, query: ContextQuery, *, current: Mapping[str, str | None] | None = None) -> Guidance:
    """The deterministic advice for one claim head under a query (SYSTEM_SPEC §7.3, §7.4, §8.2)."""
    reasons: list[str] = []
    applicable = conditions.applicability(claim.scope, claim.conditions, query)
    dependency = None
    if claim.status not in LIVE:
        return Guidance(None, applicable, None, claim.freshness, ("retired",))
    if claim.kind == "failure_lesson":
        # The caution gate only (SYSTEM_SPEC §7.4): a changed, missing or unknown dependency suppresses caution;
        # contextual recall with a freshness warning stays possible (§7.3).
        values = current if current is not None else current_dependencies(q, ctx, claim.dependencies, query)
        dependency = conditions.dependency_applicability(claim.dependencies, values)
        if dependency != conditions.TRUE:
            reasons.append(f"dependency_{dependency}")
    elif claim.dependencies and current:
        # Any other claim kind: a changed dependency observed live is never shown as current (decision 0020).
        dependency = conditions.dependency_applicability(claim.dependencies, current)
        if dependency == conditions.FALSE:
            reasons.append("dependency_false")
    freshness = "needs_revalidation" if claim.freshness == "current" and dependency == conditions.FALSE else claim.freshness
    if freshness != "current":
        reasons.append(f"freshness_{freshness}")
    if claim.status == "disputed":
        return Guidance("conflict" if applicable != conditions.FALSE else None, applicable, dependency, freshness, tuple(reasons + ["disputed"]))
    if claim.status == "candidate":
        return Guidance("context" if applicable != conditions.FALSE else None, applicable, dependency, freshness, tuple(reasons + ["candidate"]))
    caution_candidate = claim.kind == "failure_lesson" and claim.strength in ("supported", "corroborated") and dependency == conditions.TRUE
    advice = conditions.advice_for(applicable, freshness, caution_candidate=caution_candidate)
    return Guidance(advice, applicable, dependency, freshness, tuple(reasons))


def plus_days(moment: str, days: int) -> str:
    return format_utc(parse_utc(moment) + _dt.timedelta(days=days))


__all__ = [
    "revalidate_dependents", "failure_recheck", "certified_order", "mark", "enqueue", "settle", "dependents", "on_ingested", "on_conflict", "after_merge",
    "guidance", "review_class", "resolve_dependencies", "rechecks", "pending", "needs_model", "Guidance", "Settled",
]
