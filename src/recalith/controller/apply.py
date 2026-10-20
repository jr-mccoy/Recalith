"""Transactional application of proposed operations (SYSTEM_SPEC §6.2, §10; DATA_CONTRACTS §8, §11).

**Persist, then apply.** :func:`persist_proposal` stores a model response
with the read set it was produced under, inside the job's lease fence, before
anything is applied; recovery applies the persisted proposal without another
model call. :func:`apply_proposal` runs inside ``controller.jobs.fenced``:
the lease is checked, the persisted proposal is located, the read set is
rechecked, operations are grouped and applied, the operation IDs and an
application record are written, the store revision (and, for
serving-relevant changes only, the guidance epoch) advances, and the job
completes, all in one database transaction. No model or network call runs
inside it.

**Idempotency.** The proposal digest covers the operations, no-op reason and
adapter-recorded malformed entries, not usage or provenance. Operation IDs
are ``op_`` + SHA-256 of ``[job ID, proposal digest, local ref]``; the
application record uses the reserved ref ``@apply`` (not a valid local ref).
An already committed application returns its original :class:`ApplyResult`
before the lease is checked, so a duplicate never increments support or
revisions and a completed job needs no re-lease. Exact-duplicate claims are
reused (content key), and support is attached to an existing claim only when
it adds an independent root class (``core.lineage``, decision 0010), so the
same proposal under a different job, a repetition or an unchanged rerun adds
no second effect and never advances ``last_supported_at``.

**Groups.** Local refs and ``depends_on`` form a graph; each connected
component is one atomic group, applied in dependency order inside its own
savepoint. A malformed (adapter-recorded) or rejected operation fails exactly
its group; independent groups still apply.

**Conflicts.** A changed consulted record, policy revision, tombstone epoch or
live fingerprint, or a stale target revision, applies nothing. For a job the
conflict creates one bounded re-evaluation job (at most
``policy.REEVALUATION_LIMIT`` along a chain) through ``jobs.enqueue``; it
never overwrites. A service writer receives ``revision_conflict``.

**Undo.** :func:`preview_undo` computes a compensating change from the
immutable before/after revisions of one operation and reports every field a
later revision changed as a conflict; :func:`apply_undo` applies exactly a
current preview (matching digest) by appending revisions. It never restores a
database snapshot or erases intervening history. The guarded ``recalith
undo`` transport is Task 12a; these service functions require an operator
actor.

The revision chain is full-release work: ``revision_chain`` stays reserved
and unpopulated here and is never reported verified.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from pydantic import ValidationError

from recalith.contracts.common import EvidenceLink, InstallationContext, ReadSet, RecordRef, canonical_json, derived_id, digest_of, format_utc, new_id, parse_utc, utc_now
from recalith.contracts.jobs import Job
from recalith.contracts.memory import ClaimRevision, Episode, ModelProvenance, PendingAction, ReviewAssessment, TaskState
from recalith.contracts.memory import TaskBindingProposal
from recalith.contracts.operations import (
    AdmissionDecision,
    ApplyResult,
    AssessClaimPayload,
    AttachEvidencePayload,
    BindEventsPayload,
    ChangeClaimStatusPayload,
    CreateTaskPayload,
    RecordBoundaryPayload,
    CreateEpisodePayload,
    MalformedOperation,
    ModelResponse,
    ProposeClaimPayload,
    ProposedOperation,
    ReviseClaimPayload,
    ReviseEpisodePayload,
    UndoChange,
    UndoConflict,
    UndoPreview,
    UpdateTaskPayload,
)
from recalith.controller import admission, jobs, review, revalidate
from recalith.core import lineage, policy
from recalith.errors import RecalithError
from recalith.fast import failpoints
from recalith.storage import records
from recalith.storage.db import Store, Txn, open_store
from recalith.working import bindings
from recalith.working import tasks as working_tasks

APPLY_REF = "@apply"
REQUEUE_REF = "@requeue"
UNDO_REF = "@undo"
APPLICATION_KIND = "apply_proposal"
SERVICE_KIND = "apply_service"
REDUCTION_KIND = "apply_reduction"
REQUEUE_KIND = "requeue"
UNDO_KIND = "undo"
REQUEUED = "reevaluation_requeued"
PROPOSAL_RETENTION_DAYS = 7


# --------------------------------------------------------------------------
# Identity


def proposal_digest(response: ModelResponse) -> str:
    """Digest of what was proposed (operations, no-op reason, malformed entries); not usage."""
    return digest_of(
        {
            "operations": [op.model_dump(mode="json") for op in response.operations],
            "no_op_reason": response.no_op_reason,
            "malformed": [m.model_dump(mode="json") for m in response.malformed],
        }
    )


def operation_id(scope_id: str, digest: str, local_ref: str) -> str:
    """Deterministic: job (or submission) ID + persisted proposal digest + local ref."""
    return derived_id("op", [scope_id, digest, local_ref])


def proposal_id_for(job_id: str, digest: str, read_set: ReadSet) -> str:
    return derived_id("prop", [job_id, digest, digest_of(read_set.model_dump(mode="json"))])


# --------------------------------------------------------------------------
# Proposal persistence


def persist_proposal(store: Store, job: Job, response: ModelResponse, read_set: ReadSet, *, now: str) -> str:
    """Store the response and its read set under the job's lease fence (before application)."""
    digest = proposal_digest(response)
    proposal_id = proposal_id_for(job.job_id, digest, read_set)
    retention = format_utc(parse_utc(now) + _days(PROPOSAL_RETENTION_DAYS))
    with jobs.fenced(store, job, now=now) as txn:
        # A response prepared before a forget committed may restate what was forgotten (citing it or not): its
        # body is never stored and it is re-evaluated against the current store in this transaction (decision 0017).
        late = read_set.tombstone_epoch != txn.meta.tombstone_epoch
        txn.execute(
            "INSERT OR IGNORE INTO proposals (proposal_id, job_id, input_digest, read_set_digest, body, retention_after, proposal_digest, read_set) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (proposal_id, job.job_id, job.input_digest, digest_of(read_set.model_dump(mode="json")), None if late else response.model_dump_json(), retention, digest, canonical_json(read_set).decode()),
        )
        current = jobs.set_proposal(txn, job, proposal_id)
        if late:
            run = _Run(ctx=store.ctx, txn=txn, scope_id=job.job_id, digest=digest, now=now, job=current, proposal_id=proposal_id, causal_root=_depth(txn, job.job_id)[1], read_set=read_set)
            _requeue(run, response, read_set, "tombstone_epoch_changed")
        failpoints.hit(failpoints.PROPOSAL_BEFORE_COMMIT)
    failpoints.hit(failpoints.JOB_AFTER_PROPOSAL)
    return proposal_id


def load_proposal(q: Any, proposal_id: str) -> tuple[ModelResponse, ReadSet, str]:
    row = q.execute("SELECT body, read_set, proposal_digest FROM proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
    if row is None or row[0] is None or row[1] is None:
        raise RecalithError("revision_conflict", "persisted proposal is missing")
    response = ModelResponse.model_validate_json(row[0])
    if proposal_digest(response) != row[2]:
        raise RecalithError("storage_failure", "persisted proposal does not match its digest")
    return response, ReadSet.model_validate_json(row[1]), row[2]


# --------------------------------------------------------------------------
# Application state


@dataclass
class _Change:
    entries: list[dict[str, Any]] = field(default_factory=list)
    refs: list[RecordRef] = field(default_factory=list)
    serving: bool | None = None  # None: decided by the operation kind (policy.SERVING_RELEVANT_KINDS)

    def record(self, ref: RecordRef, before: int | None) -> None:
        self.entries.append({"ref": ref.model_dump(mode="json"), "before": before})
        self.refs.append(ref)

    def relation(self, source: str, target: str, relation: str) -> None:
        self.entries.append({"relation": [source, target, relation], "added": True})

    def binding(self, event_id: str, before: dict[str, Any] | None, after: dict[str, Any]) -> None:
        self.entries.append({"binding": event_id, "before": before, "after": after})

    def boundary(self, boundary_id: str, before: str | None, after: str) -> None:
        self.entries.append({"boundary": boundary_id, "before": before, "after": after})


@dataclass
class _Run:
    ctx: InstallationContext
    txn: Txn
    scope_id: str
    digest: str
    now: str
    job: Job | None
    proposal_id: str | None
    causal_root: str
    resolution: admission.Resolution = field(default_factory=admission.Resolution)
    created: set[tuple[str, str]] = field(default_factory=set)
    serving: bool = False
    source: str = "proposal"  # proposal (model) | service | reduction (typed reducer)
    review_queue: list[review.Queued] = field(default_factory=list)  # candidates this application wrote
    provenance: Any = None  # the response's adapter-appended ResponseProvenance (model proposals only)
    read_set: ReadSet | None = None  # what the proposal consulted (a revalidation settles only what it read)
    revalidate_claims: set[str] = field(default_factory=set)  # claims whose activation now owes a revalidation
    decided: dict[str, str] = field(default_factory=dict)  # claim -> operation kind that changed it (revalidation jobs)
    review_origin: str | None = None  # the guarded operator transport's origin for its candidates (operator_correction)

    @property
    def revalidating(self) -> bool:
        return self.job is not None and self.job.kind == "revalidate"


class _Writer:
    """The handler-facing view of one operation inside the application (``bindings.Writer``)."""

    def __init__(self, run: _Run, op: ProposedOperation, change: _Change) -> None:
        self.txn = run.txn
        self.ctx = run.ctx
        self.now = run.now
        self.op_id = operation_id(run.scope_id, run.digest, op.local_ref)
        self.source = run.source
        self._run = run
        self._change = change

    def record(self, ref: RecordRef, before: int | None) -> None:
        if before is not None:
            _touch(self._run, ref.kind, ref.id, before)
        self._change.record(ref, before)

    def created(self, kind: str, record_id: str) -> None:
        self._run.created.add((kind, record_id))

    def binding(self, event_id: str, before: dict[str, Any] | None, after: dict[str, Any]) -> None:
        self._change.binding(event_id, before, after)

    def boundary(self, boundary_id: str, before: str | None, after: str) -> None:
        self._change.boundary(boundary_id, before, after)

    def serving(self) -> None:
        self._change.serving = True


class _GroupFailed(Exception):
    def __init__(self, local_ref: str, reason: str) -> None:
        super().__init__(reason)
        self.local_ref = local_ref
        self.reason = reason


def _validate(model: type, data: dict[str, Any]):
    return model.model_validate_json(json.dumps(data))


def _head_body(q: Any, kind: str, record_id: str) -> tuple[int, dict[str, Any]]:
    current = records.head(q, kind, record_id)
    if current is None:
        raise RecalithError("revision_conflict", f"{kind} head is missing")
    data = records.body(q, kind, record_id, current[0])
    if data is None:
        raise RecalithError("revision_conflict", f"{kind} body is unavailable")
    return current[0], data


def _touch(run: _Run, kind: str, record_id: str, base: int) -> None:
    run.resolution.base.setdefault((kind, record_id), base)


# --------------------------------------------------------------------------
# Operation handlers: each writes revisions and returns (changes, reason override)


def _new_claim_revision(data: dict[str, Any], *, now: str) -> dict[str, Any]:
    data = dict(data)
    data["revision"] = data["revision"] + 1
    data["recorded_at"] = now
    return data


def _merge_links(existing: list[dict[str, Any]], new: Iterable[EvidenceLink]) -> tuple[list[dict[str, Any]], int]:
    seen = {records.link_identity(EvidenceLink.model_validate(item)) for item in existing}
    out, added = list(existing), 0
    for link in new:
        identity = records.link_identity(link)
        if identity not in seen:
            seen.add(identity)
            out.append(link.model_dump(mode="json"))
            added += 1
    return out, added


def _new_support(run: _Run, data: dict[str, Any], new: Iterable[EvidenceLink]) -> tuple[list[dict[str, Any]], int, str | None]:
    """Support links that add an independent root class (SYSTEM_SPEC §7.2 Confirm, §7.1.1; decision 0010).

    A link is attached only when it raises the claim's count of canonical root
    classes for its proposition. Repetition, an unchanged rerun, a forwarded
    or summarized copy, memory telemetry, assistant text and a repeated user
    declaration add none, so they never refresh support. Returns the merged
    links, how many were added, and the latest observation time of the new
    classes' roots (for ``last_supported_at``).
    """
    key = data.get("proposition_key")
    existing = [EvidenceLink.model_validate(item) for item in data["supports"]]
    seen = {records.link_identity(link) for link in existing}
    count = len(lineage.resolve(run.txn, existing, proposition_key=key).support_classes)
    out, added, roots = list(data["supports"]), 0, set()
    for link in new:
        if records.link_identity(link) in seen:
            continue
        trial = lineage.resolve(run.txn, [*existing, link], proposition_key=key)
        if len(trial.support_classes) <= count:
            continue
        existing.append(link)
        seen.add(records.link_identity(link))
        count = len(trial.support_classes)
        out.append(link.model_dump(mode="json"))
        added += 1
        roots |= lineage.resolve(run.txn, [link], proposition_key=key).support_roots
    return out, added, lineage.observed_at(run.txn, roots) if roots else None


def _no_root_reason(run: _Run, data: dict[str, Any], new: Sequence[EvidenceLink]) -> str:
    """``no_independent_root`` when none of the links resolves to an eligible root at all."""
    resolved = lineage.resolve(run.txn, list(new), proposition_key=data.get("proposition_key"))
    return "duplicate_evidence" if resolved.support_classes else "no_independent_root"


def _supported_at(data: dict[str, Any], when: str | None) -> None:
    if when is not None and (data.get("last_supported_at") is None or when > data["last_supported_at"]):
        data["last_supported_at"] = when


def _cap_strength(data: dict[str, Any]) -> None:
    if data.get("contradicts") and data.get("strength") == "corroborated":
        data["strength"] = "supported"  # corroboration requires no unresolved contradiction


def _strength(run: _Run, data: dict[str, Any]) -> None:
    """Strength follows lineage only (``admission.assign_strength``); a candidate stays weak."""
    data["strength"] = admission.assign_strength(run.txn, data)


def _queue(run: _Run, ref: RecordRef, data: dict[str, Any]) -> None:
    """A candidate revision this application wrote: its review is scheduled when the application commits."""
    if data.get("status") != "candidate":
        return
    if run.source == "proposal" or run.ctx.actor.kind != "operator":
        origin = "extracted"
    elif run.review_origin is not None:
        origin = run.review_origin
    else:
        origin = "typed_declaration" if data.get("basis") == "user_declared" else "operator_declaration"
    run.review_queue.append(review.Queued(ref=ref, claim_kind=data["kind"], basis=data["basis"], origin=origin))


def _provenance(run: _Run) -> ModelProvenance | None:
    """Provider, model and pinned prompt of the job that proposed a claim (adapter-appended, never model text)."""
    from recalith import prompts

    if run.job is None or run.provenance is None or run.job.prompt_version is None:
        return None
    try:
        digest = prompts.prompt_digest(run.job.prompt_version)
    except KeyError:
        return None
    p = run.provenance
    return ModelProvenance(provider_id=p.provider_id, configured_model=p.configured_model, resolved_model=p.resolved_model, adapter_version=p.adapter_version, prompt_id=run.job.prompt_version, prompt_digest=digest, job_id=run.job.job_id)


def _write_claim_revision(run: _Run, old_revision: int, data: dict[str, Any], change: _Change, *, context: Sequence[EvidenceLink] = ()) -> RecordRef:
    claim = _validate(ClaimRevision, data)
    ref = records.write_claim(run.txn, claim, context=context)
    _touch(run, "claim", claim.claim_id, old_revision)
    change.record(ref, old_revision)
    return ref


def _propose_claim(run: _Run, op: ProposedOperation, typed: ProposeClaimPayload, change: _Change) -> str | None:
    ctx = run.ctx
    supports = [link for link in op.evidence if link.relation == "supports"]
    contradicts = [link for link in op.evidence if link.relation == "contradicts"]
    context = [link for link in op.evidence if link.relation == "context"]
    _refused, dependencies = revalidate.resolve_dependencies(run.txn, run.ctx, typed.dependencies, op.evidence)  # admission refused a mismatch
    klass, _why = revalidate.review_class(run.txn, kind=typed.kind, basis=typed.basis, dependencies=dependencies)
    failure = typed.failure
    if failure is not None:
        _reason, derived = admission.derive_failure(run.txn, supports)  # admission already refused an underivable body
        assert derived is not None
        failure = failure.model_copy(update=derived)  # code-derived index fields (decision 0011)
    candidate = ClaimRevision(
        claim_id=new_id("claim"),
        project_id=ctx.project_id,
        installation_id=ctx.installation_id,
        revision=1,
        kind=typed.kind,
        proposition=typed.proposition,
        proposition_key=typed.proposition_key,
        scope=typed.scope,
        conditions=typed.conditions,
        basis=typed.basis,
        strength="weak",  # assigned from lineage below once admitted active
        status="active" if typed.basis == "observed" else "candidate",  # only a verified mapping skips review
        freshness="current",
        supports=supports,
        contradicts=contradicts,
        context=context,
        evidence_availability="available",
        effective_from=typed.effective_from,
        effective_until=typed.effective_until,
        recorded_at=run.now,
        review_due_at=format_utc(policy.review_due(parse_utc(run.now), klass)),
        dependencies=dependencies,
        review_class=klass,
        procedure=typed.procedure,
        failure=failure,
        model_provenance=_provenance(run),
    )
    support = lineage.resolve(run.txn, supports, proposition_key=candidate.proposition_key.model_dump(mode="json") if candidate.proposition_key else None)
    if support.support_classes:
        candidate = candidate.model_copy(update={"last_supported_at": lineage.observed_at(run.txn, support.support_roots)})
    key = records.content_key(candidate)
    existing = records.duplicate_heads(run.txn, key) if key else []
    if existing:
        head = existing[0]
        old = head.model_dump(mode="json")
        supports_out, s_added, when = _new_support(run, old, supports)
        contradicts_out, c_added = _merge_links(old["contradicts"], contradicts)
        run.resolution.locals[op.local_ref] = records.ref_of(head)
        if not s_added and not c_added:
            return "duplicate_existing"  # same proposition, scope, conditions and root classes: one effect
        data = _new_claim_revision(old, now=run.now)
        data["supports"], data["contradicts"] = supports_out, contradicts_out
        data["context"], _ = _merge_links(old.get("context") or [], context)
        _supported_at(data, when)
        _strength(run, data)
        ref = _write_claim_revision(run, head.revision, data, change)
        run.resolution.locals[op.local_ref] = ref
        _queue(run, ref, data)
        return "duplicate_new_evidence"
    if candidate.status == "active":
        candidate = candidate.model_copy(update={"strength": admission.assign_strength(run.txn, candidate.model_dump(mode="json"))})
    ref = records.write_claim(run.txn, candidate)
    run.created.add(("claim", candidate.claim_id))
    run.resolution.locals[op.local_ref] = ref
    change.record(ref, None)
    _queue(run, ref, candidate.model_dump(mode="json"))
    return None if candidate.status == "candidate" else "observed_mapping"


def _attach_evidence(run: _Run, op: ProposedOperation, typed: AttachEvidencePayload, change: _Change) -> str | None:
    revision, data = _head_body(run.txn, "claim", typed.claim_ref.id)
    if typed.relation == "context":
        merged, added = _merge_links(data.get("context") or [], op.evidence)
        if not added:
            return "duplicate_evidence"
        data = _new_claim_revision(data, now=run.now)
        data["context"] = merged  # counter-observations: never support, never contradiction
        _write_claim_revision(run, revision, data, change)
        return None
    if typed.relation == "supports":
        merged, added, when = _new_support(run, data, op.evidence)
        if not added:
            return _no_root_reason(run, data, op.evidence)  # duplicate mentions never refresh support
        data = _new_claim_revision(data, now=run.now)
        data["supports"] = merged
        _supported_at(data, when)
        _refresh_failure(run, data)
    else:
        merged, added = _merge_links(data["contradicts"], op.evidence)
        if not added:
            return "duplicate_evidence"
        data = _new_claim_revision(data, now=run.now)
        data["contradicts"] = merged  # contradicting outcomes stay attached, even from one class
    _strength(run, data)
    ref = _write_claim_revision(run, revision, data, change)
    _queue(run, ref, data)  # changed support of a candidate needs its own review
    return None


def _refresh_failure(run: _Run, data: dict[str, Any]) -> None:
    """A failure lesson's code-derived index fields follow its latest supporting failure (decision 0011)."""
    if data.get("kind") != "failure_lesson" or data.get("failure") is None:
        return
    _reason, derived = admission.derive_failure(run.txn, [EvidenceLink.model_validate(i) for i in data["supports"]])
    if derived is not None:
        data["failure"] = {**data["failure"], **derived}


def _revise_claim(run: _Run, op: ProposedOperation, typed: ReviseClaimPayload, change: _Change) -> str | None:
    revision, data = _head_body(run.txn, "claim", typed.claim_ref.id)
    data = _new_claim_revision(data, now=run.now)
    for name in ("proposition", "proposition_key", "scope", "conditions", "dependencies"):
        value = getattr(typed, name)
        if value is not None:
            if isinstance(value, list):
                data[name] = [v.model_dump(mode="json") for v in value]
            else:
                data[name] = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    if typed.dependencies is not None:
        supports = [EvidenceLink.model_validate(i) for i in data["supports"]]
        _refused, data["dependencies"] = revalidate.resolve_dependencies(run.txn, run.ctx, typed.dependencies, supports)
    if typed.retry_conditions is not None:
        data["failure"] = {**data["failure"], "retry_conditions": [r.model_dump(mode="json") for r in typed.retry_conditions]}
    # Altered content needs a fresh review: the revision is an unreviewed candidate.
    data["status"], data["strength"], data["review_assessment"] = "candidate", "weak", None
    data["review_class"], _why = revalidate.review_class(run.txn, kind=data["kind"], basis=data["basis"], dependencies=data["dependencies"], claim_id=typed.claim_ref.id)
    data["review_due_at"] = format_utc(policy.review_due(parse_utc(run.now), data["review_class"]))
    if run.revalidating:
        data["freshness"] = revalidate.revision_freshness(run.txn, typed.claim_ref.id, run.read_set)  # answers the revalidation it read
        run.decided[typed.claim_ref.id] = op.kind
    supports = [link for link in op.evidence if link.relation == "supports"]
    data["supports"], _ = _merge_links(data["supports"], supports)
    data.setdefault("context", [])
    data["context"], _ = _merge_links(data["context"], [link for link in op.evidence if link.relation == "context"])
    _refresh_failure(run, data)
    ref = _write_claim_revision(run, revision, data, change)
    _queue(run, ref, data)
    return None


def _assess_claim(run: _Run, op: ProposedOperation, typed: AssessClaimPayload, change: _Change) -> str | None:
    """Record one admitted review assessment on its candidate (``controller.review`` decided it may count)."""
    scope = run.resolution.review
    assert scope is not None
    revision, data = _head_body(run.txn, "claim", typed.candidate_ref.id)
    links = [scope.link(e) for e in typed.evidence_ids]
    assessment = ReviewAssessment(
        review_job_id=scope.job.job_id, batch_id=scope.batch.batch_id, candidate_ref=typed.candidate_ref, proposal_digest=run.digest,
        evidence_digest=scope.batch.evidence_digest, prompt_digest=scope.batch.prompt_digest, verdict=typed.verdict, objections=list(typed.objections),
        evidence_refs=[link for link in links if link is not None], reviewed_at=run.now,
    )
    data = _new_claim_revision(data, now=run.now)
    data["review_assessment"] = assessment.model_dump(mode="json")
    capacity = typed.verdict == "reject" and typed.objections == [review.CAPACITY]
    deferred: list[dict[str, Any]] = []
    targets: list[tuple[str, int]] = []
    if typed.verdict == "supported":
        data["status"] = "active"
        deferred = revalidate.apply_deferred(run.txn, typed.candidate_ref.id, data, now=run.now)  # rechecks recorded while it was a candidate
        targets = revalidate.pending_supersessions(run.txn, typed.candidate_ref.id)
    elif typed.verdict == "reject" and not capacity:
        data["status"] = "archived"  # not admitted; archiving asserts no falsity
        revalidate.withdraw_supersessions(run.txn, typed.candidate_ref.id, now=run.now)
    applied = []
    for target_id, target_revision in targets:
        head = records.head(run.txn, "claim", target_id)
        if head is not None and head[0] == target_revision and head[1] in ("active", "disputed", "candidate"):
            data["supersedes"] = [*data["supersedes"], RecordRef(kind="claim", id=target_id, revision=target_revision).model_dump(mode="json")]
            applied.append(target_id)
        else:
            revalidate.decide_supersession(run.txn, typed.candidate_ref.id, target_id, "stale", now=run.now)  # the target moved meanwhile
            run.revalidate_claims.update({target_id, typed.candidate_ref.id})
    _strength(run, data)
    ref = _write_claim_revision(run, revision, data, change)
    for target_id in applied:
        # The explicit replacement and its target's supersession commit together, with the activation.
        t_rev, t_data = _head_body(run.txn, "claim", target_id)
        t_data = _new_claim_revision(t_data, now=run.now)
        t_data["status"] = "superseded"
        t_data["superseded_by"] = [*t_data["superseded_by"], ref.model_dump(mode="json")]
        _cap_strength(t_data)
        _write_claim_revision(run, t_rev, t_data, change)
        if records.add_relation(run.txn, ref.id, target_id, "supersedes"):
            change.relation(ref.id, target_id, "supersedes")
        revalidate.decide_supersession(run.txn, typed.candidate_ref.id, target_id, "applied", now=run.now)
        revalidate.withdraw_target(run.txn, target_id, now=run.now)
    if deferred:
        run.revalidate_claims.update(revalidate.promote_deferred(run.txn, deferred, revision=ref.revision, now=run.now))
    return None


def _change_status(run: _Run, op: ProposedOperation, typed: ChangeClaimStatusPayload, change: _Change) -> str | None:
    revision, data = _head_body(run.txn, "claim", typed.claim_ref.id)
    if typed.status == "superseded" and run.ctx.actor.kind != "operator" and data["status"] in ("active", "disputed"):
        replacement = run.resolution.locals[typed.replacement_local_ref] if typed.replacement_local_ref else typed.replacement_ref
        assert replacement is not None
        head = records.head(run.txn, "claim", replacement.id)
        if head is not None and head[1] == "candidate":
            # Held until the replacement's own review activates it (admission: replacement_pending_review).
            revalidate.record_pending_supersession(run.txn, replacement_id=replacement.id, target=typed.claim_ref, operation_id=operation_id(run.scope_id, run.digest, op.local_ref), now=run.now)
            change.entries.append({"pending_supersession": [replacement.id, typed.claim_ref.id]})
            change.serving = False
            return "replacement_pending_review"
    data = _new_claim_revision(data, now=run.now)
    data["status"] = typed.status
    if run.revalidating:
        run.decided[typed.claim_ref.id] = op.kind
        if typed.status == "disputed":
            data["freshness"] = revalidate.revision_freshness(run.txn, typed.claim_ref.id, run.read_set)
    data.setdefault("context", [])
    data["context"], _ = _merge_links(data["context"], [link for link in op.evidence if link.relation == "context"])
    data["supports"], _ = _merge_links(data["supports"], [link for link in op.evidence if link.relation == "supports"])
    data["contradicts"], _ = _merge_links(data["contradicts"], [link for link in op.evidence if link.relation == "contradicts"])
    _cap_strength(data)
    replacement: RecordRef | None = None
    if typed.status == "superseded":
        replacement = run.resolution.locals[typed.replacement_local_ref] if typed.replacement_local_ref else typed.replacement_ref
        assert replacement is not None
        data["superseded_by"] = [*data["superseded_by"], replacement.model_dump(mode="json")]
    old_ref = _write_claim_revision(run, revision, data, change)
    if typed.status != "disputed":
        revalidate.withdraw_supersessions(run.txn, typed.claim_ref.id, now=run.now)  # a retired replacement replaces nothing
        revalidate.withdraw_target(run.txn, typed.claim_ref.id, now=run.now)
    if replacement is not None:
        r_rev, r_data = _head_body(run.txn, "claim", replacement.id)
        old_pointer = RecordRef(kind="claim", id=old_ref.id, revision=revision).model_dump(mode="json")
        r_data = _new_claim_revision(r_data, now=run.now)
        r_data["supersedes"] = [*r_data["supersedes"], old_pointer]
        _write_claim_revision(run, r_rev, r_data, change)  # tracked here, so undo restores both sides
        if records.add_relation(run.txn, replacement.id, old_ref.id, "supersedes"):
            change.relation(replacement.id, old_ref.id, "supersedes")
    return None


def _patch(data: dict[str, Any], patches: Sequence[Any], *, list_fields: frozenset[str], op_id: str, ids: dict[str, str] | None = None) -> None:
    working_tasks.patch_fields(data, patches, list_fields=list_fields, op_id=op_id, ids=ids)


TASK_LIST_FIELDS = frozenset({"constraints", "plan", "pending_actions", "known_results", "blockers", "open_questions"})
EPISODE_LIST_FIELDS = frozenset({"preconditions", "steps", "unresolved", "related_episode_ids"})


def _update_task(run: _Run, op: ProposedOperation, typed: UpdateTaskPayload, change: _Change) -> str | None:
    revision, data = _head_body(run.txn, "task", typed.task_id)
    workspace = records.task_workspace(run.txn, typed.task_id)
    assert workspace is not None
    data = dict(data)
    _patch(data, typed.patches, list_fields=TASK_LIST_FIELDS, op_id=operation_id(run.scope_id, run.digest, op.local_ref), ids={"pending_actions": "action_id"})
    for item in data.get("pending_actions", []):
        PendingAction.model_validate_json(json.dumps(item))
    data["revision"] = revision + 1
    data["updated_at"] = run.now
    state = _validate(TaskState, data)
    ref = records.write_task(run.txn, state, workspace_id=workspace)
    _touch(run, "task", typed.task_id, revision)
    change.record(ref, revision)
    return None


def episode_coverage(q: Any, typed: CreateEpisodePayload) -> dict[str, Any]:
    """Code-derived coverage of an episode's sources (never model-supplied)."""
    events = working_tasks.load_events(q, typed.source_event_ids)
    started = {ev.tool_call_id for ev in events if ev.kind == "tool_started" and ev.tool_call_id}
    finished = {ev.tool_call_id for ev in events if ev.kind == "tool_finished" and ev.tool_call_id}
    return {
        "source_events": len(events),
        "truncated_events": sum(1 for ev in events if ev.coverage.get("truncated")),
        "redacted_events": sum(1 for ev in events if ev.coverage.get("redacted")),
        "incomplete_events": sum(1 for ev in events if ev.coverage.get("missing_context") or not ev.coverage.get("parser_complete", True)),
        "compactions": sum(1 for ev in events if ev.kind == "compaction"),
        "sessions": len({ev.session_id for ev in events}),
        "calls_awaiting_result": len(started - finished),
        "causal_assessment": "assessed" if any(step.causal_assessment is not None for step in typed.steps) else "unassessed",
    }


def _create_episode(run: _Run, op: ProposedOperation, typed: CreateEpisodePayload, change: _Change) -> str | None:
    episode = Episode(
        episode_id=new_id("ep"),
        project_id=run.ctx.project_id,
        installation_id=run.ctx.installation_id,
        revision=1,
        coverage=episode_coverage(run.txn, typed),
        **typed.model_dump(),
    )
    ref = records.write_episode(run.txn, _validate(Episode, episode.model_dump(mode="json")))
    run.created.add(("episode", episode.episode_id))
    run.resolution.locals[op.local_ref] = ref
    change.record(ref, None)
    return None


def _revise_episode(run: _Run, op: ProposedOperation, typed: ReviseEpisodePayload, change: _Change) -> str | None:
    revision, data = _head_body(run.txn, "episode", typed.episode_id)
    data = dict(data)
    _patch(data, typed.patches, list_fields=EPISODE_LIST_FIELDS, op_id=operation_id(run.scope_id, run.digest, op.local_ref))
    data["revision"] = revision + 1
    ref = records.write_episode(run.txn, _validate(Episode, data))
    _touch(run, "episode", typed.episode_id, revision)
    change.record(ref, revision)
    return None


def _create_task(run: _Run, op: ProposedOperation, typed: CreateTaskPayload, change: _Change) -> str | None:
    bindings.apply_create_task(_Writer(run, op, change), typed)
    return None


def _bind_events(run: _Run, op: ProposedOperation, typed: BindEventsPayload, change: _Change) -> str | None:
    change.serving = False  # serving-relevant only when the task revision changes (set by the writer)
    bindings.apply_bind_events(_Writer(run, op, change), typed)
    return None


def _record_boundary(run: _Run, op: ProposedOperation, typed: RecordBoundaryPayload, change: _Change) -> str | None:
    bindings.apply_record_boundary(_Writer(run, op, change), typed)
    return None


def _resolve_binding(run: _Run, op: ProposedOperation, typed: TaskBindingProposal, change: _Change) -> str | None:
    bindings.apply_resolve(_Writer(run, op, change), typed)
    return None


HANDLERS = {
    "create_task": _create_task,
    "bind_events": _bind_events,
    "record_boundary": _record_boundary,
    "resolve_task_binding": _resolve_binding,
    "propose_claim": _propose_claim,
    "attach_evidence": _attach_evidence,
    "revise_claim": _revise_claim,
    "assess_claim": _assess_claim,
    "change_claim_status": _change_status,
    "update_task": _update_task,
    "create_episode": _create_episode,
    "revise_episode": _revise_episode,
}


# --------------------------------------------------------------------------
# Grouping


@dataclass
class _Plan:
    groups: list[list[ProposedOperation]]
    rejected: dict[str, tuple[str, list[str]]]  # local ref -> (reason, group members) for pre-failed groups
    order: list[str]


def _plan(response: ModelResponse) -> _Plan:
    """Connected components of the dependency graph, each in topological order."""
    ops = list(response.operations)
    order = [op.local_ref for op in ops] + [m.local_ref for m in response.malformed if m.local_ref and m.local_ref not in {op.local_ref for op in ops}]
    counts: dict[str, int] = {}
    for op in ops:
        counts[op.local_ref] = counts.get(op.local_ref, 0) + 1
    for m in response.malformed:
        if m.local_ref:
            counts[m.local_ref] = counts.get(m.local_ref, 0) + 1
    bad: dict[str, str] = {}
    for m in response.malformed:
        if m.local_ref:
            bad[m.local_ref] = m.reason_code
    for ref, n in counts.items():
        if n > 1:
            bad[ref] = "duplicate_local_ref"
    known = set(counts)
    deps: dict[str, list[str]] = {}
    for op in ops:
        if op.local_ref in bad:
            continue
        deps[op.local_ref] = list(op.depends_on)
        unknown = [d for d in op.depends_on if d not in known]
        if unknown:
            bad[op.local_ref] = "unknown_dependency"
    malformed_deps = {m.local_ref: list(m.depends_on) for m in response.malformed if m.local_ref}

    parent: dict[str, str] = {ref: ref for ref in counts}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        if a in parent and b in parent:
            parent[find(a)] = find(b)

    for ref, ds in [*deps.items(), *malformed_deps.items()]:
        for d in ds:
            union(ref, d)
    for op in ops:  # a duplicate ref still joins the group of whatever it named
        for d in op.depends_on:
            union(op.local_ref, d)

    components: dict[str, list[str]] = {}
    for ref in order:
        components.setdefault(find(ref), []).append(ref)
    by_ref = {op.local_ref: op for op in ops if counts[op.local_ref] == 1}
    plan = _Plan(groups=[], rejected={}, order=order)
    for members in components.values():
        failed = next((bad[m] for m in members if m in bad), None)
        if failed is None:
            sorted_ops = _topological([by_ref[m] for m in members])
            if sorted_ops is None:
                failed = "dependency_cycle"
            else:
                plan.groups.append(sorted_ops)
                continue
        culprit = next((m for m in members if m in bad), members[0])
        for m in members:
            plan.rejected[m] = (bad.get(m, failed) if m == culprit or m in bad else "group_rejected", members)
    return plan


def _topological(ops: list[ProposedOperation]) -> list[ProposedOperation] | None:
    index = {op.local_ref: i for i, op in enumerate(ops)}
    remaining = {op.local_ref: set(op.depends_on) & set(index) for op in ops}
    out: list[ProposedOperation] = []
    while remaining:
        ready = sorted((r for r, d in remaining.items() if not d), key=lambda r: index[r])
        if not ready:
            return None
        nxt = ready[0]
        out.append(ops[index[nxt]])
        del remaining[nxt]
        for d in remaining.values():
            d.discard(nxt)
    return out


# --------------------------------------------------------------------------
# The application transaction


def _actor_json(ctx: InstallationContext) -> str:
    return canonical_json(ctx.actor).decode()


def _record_operation(run: _Run, op: ProposedOperation, group_id: str, change: _Change) -> str:
    oid = operation_id(run.scope_id, run.digest, op.local_ref)
    run.txn.execute(
        "INSERT INTO operations (operation_id, job_id, proposal_id, atomic_group_id, actor, kind, inputs, changed, reason, causal_root, store_revision, created_at, local_ref, proposal_digest) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            oid, run.job.job_id if run.job else None, run.proposal_id, group_id, _actor_json(run.ctx), op.kind, canonical_json(op).decode(),
            canonical_json(change.entries).decode(), op.reason, run.causal_root, run.txn.next_store_revision, run.now, op.local_ref, run.digest,
        ),
    )
    return oid


def _subject_refs(op: ProposedOperation) -> list[RecordRef]:
    typed = op.typed_payload()
    refs = []
    subject = admission.subject_ref(op, typed)
    if subject is not None:
        refs.append(subject)
    if isinstance(typed, ChangeClaimStatusPayload) and typed.replacement_ref is not None:
        refs.append(typed.replacement_ref)
    return refs


def _stale_targets(q: Any, ops: Iterable[ProposedOperation]) -> bool:
    for op in ops:
        try:
            refs = _subject_refs(op)
            typed = op.typed_payload()
        except ValidationError:
            continue
        if isinstance(typed, TaskBindingProposal) and bindings.stale_bindings(q, typed):
            return True
        for ref in refs:
            if ref.kind not in records.HEAD_TABLES:
                continue
            current = records.head(q, ref.kind, ref.id)
            if current is not None and current[0] != ref.revision:
                return True
    return False


def _run_groups(run: _Run, response: ModelResponse) -> tuple[list[AdmissionDecision], list[str], list[RecordRef]]:
    plan = _plan(response)
    decided: dict[str, AdmissionDecision] = {}
    operation_ids: list[str] = []
    changed: list[RecordRef] = []
    for ref, (reason, _members) in plan.rejected.items():
        decided[ref] = AdmissionDecision(local_ref=ref, outcome="reject", reason_code=reason, resolved_operation_id=None)
    for gi, group in enumerate(plan.groups):
        group_id = derived_id("grp", [run.scope_id, run.digest, group[0].local_ref])
        snapshot = (dict(run.resolution.locals), dict(run.resolution.base), set(run.created), len(run.review_queue), set(run.revalidate_claims), dict(run.decided))
        run.txn.execute("SAVEPOINT apply_group")
        group_decisions: list[AdmissionDecision] = []
        group_ids: list[str] = []
        group_changed: list[RecordRef] = []
        group_serving = False
        try:
            for op in group:
                if run.source == "proposal" and op.kind in policy.REDUCTION_KINDS:
                    raise _GroupFailed(op.local_ref, "kind_not_permitted")  # controller-only kinds never come from a model
                verdict = admission.check_operation(run.txn, run.ctx, op, resolution=run.resolution)
                if not verdict.admitted:
                    raise _GroupFailed(op.local_ref, verdict.reason)
                handler = HANDLERS.get(op.kind)
                oid = None
                reason = verdict.reason
                if handler is not None:
                    change = _Change()
                    try:
                        override = handler(run, op, op.typed_payload(), change)
                    except (ValueError, ValidationError, KeyError, TypeError) as exc:
                        raise _GroupFailed(op.local_ref, "invalid_result") from exc
                    reason = override or reason
                    if change.entries:
                        oid = _record_operation(run, op, group_id, change)
                        group_ids.append(oid)
                        group_changed.extend(change.refs)
                        group_serving = group_serving or (change.serving if change.serving is not None else op.kind in policy.SERVING_RELEVANT_KINDS)
                group_decisions.append(AdmissionDecision(local_ref=op.local_ref, outcome=verdict.outcome, reason_code=reason, resolved_operation_id=oid))  # type: ignore[arg-type]
        except _GroupFailed as failed:
            run.txn.execute("ROLLBACK TO apply_group")
            run.txn.execute("RELEASE apply_group")
            run.resolution.locals, run.resolution.base, run.created, queued, run.revalidate_claims, run.decided = snapshot
            del run.review_queue[queued:]
            for op in group:
                code = failed.reason if op.local_ref == failed.local_ref else "group_rejected"
                decided[op.local_ref] = AdmissionDecision(local_ref=op.local_ref, outcome="reject", reason_code=code, resolved_operation_id=None)
            continue
        run.txn.execute("RELEASE apply_group")
        for d in group_decisions:
            decided[d.local_ref] = d
        operation_ids.extend(group_ids)
        changed.extend(group_changed)
        run.serving = run.serving or group_serving
        if gi == 0:
            failpoints.hit(failpoints.APPLY_AFTER_GROUP)
        if group_ids and any(op.kind == "assess_claim" for op in group) and run.resolution.review is not None:
            failpoints.hit(failpoints.REVIEW_AFTER_ASSESSMENT)
    ordered = [decided[r] for r in plan.order if r in decided] + [d for r, d in decided.items() if r not in plan.order]
    return ordered, operation_ids, changed


def _all(response: ModelResponse, outcome: str, reason: str) -> list[AdmissionDecision]:
    refs = [op.local_ref for op in response.operations] + [m.local_ref for m in response.malformed if m.local_ref]
    return [AdmissionDecision(local_ref=r, outcome=outcome, reason_code=reason, resolved_operation_id=None) for r in dict.fromkeys(refs)]  # type: ignore[arg-type]


def _write_application(run: _Run, kind: str, result: ApplyResult, *, app_id: str) -> None:
    run.txn.execute(
        "INSERT INTO operations (operation_id, job_id, proposal_id, atomic_group_id, actor, kind, inputs, changed, reason, causal_root, store_revision, created_at, local_ref, proposal_digest) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)",
        (
            app_id, run.job.job_id if run.job else None, run.proposal_id, _actor_json(run.ctx), kind,
            canonical_json({"result": result.model_dump(mode="json")}).decode(), canonical_json([r.model_dump(mode="json") for r in result.changed_refs]).decode(),
            run.causal_root, run.txn.next_store_revision, run.now, APPLY_REF, run.digest,
        ),
    )
    run.txn.mutated(serving_relevant=run.serving)


def stored_result(q: Any, app_id: str) -> ApplyResult | None:
    row = q.execute("SELECT inputs FROM operations WHERE operation_id = ?", (app_id,)).fetchone()
    data = json.loads(row[0]) if row is not None else {}
    if "result" not in data:
        return None  # absent, or purged by forgetting (it then applies nothing new: its job is cancelled)
    return ApplyResult.model_validate(data["result"])


def _depth(q: Any, job_id: str) -> tuple[int, str]:
    row = q.execute("SELECT inputs FROM operations WHERE kind = ? AND job_id = ?", (REQUEUE_KIND, job_id)).fetchone()
    if row is None:
        return 0, job_id
    data = json.loads(row[0])
    return int(data["depth"]), data["root_job_id"]


def _requeue(run: _Run, response: ModelResponse, read_set: ReadSet, reason: str) -> ApplyResult:
    job = run.job
    assert job is not None
    depth, root_job = _depth(run.txn, job.job_id)
    current = jobs.get_job(run.txn, job.job_id)
    assert current is not None
    if depth + 1 > policy.REEVALUATION_LIMIT:
        jobs.fail(run.txn, current, "reevaluation_limit", now=run.now, backoff=())
        result = ApplyResult(operation_ids=[], changed_refs=[], decisions=_all(response, "reject", "reevaluation_limit"), store_revision=run.txn.next_store_revision, requeued_job_ids=[])
        _write_application(run, APPLICATION_KIND, result, app_id=operation_id(run.scope_id, run.digest, APPLY_REF))
        return result
    refs = []
    for ref in current.input_refs:
        head = records.head(run.txn, ref.kind, ref.id) if ref.kind in records.HEAD_TABLES else None
        refs.append(RecordRef(kind=ref.kind, id=ref.id, revision=head[0]) if head is not None else ref)
    signature = digest_of(
        {
            "heads": sorted([r.kind, r.id, (records.head(run.txn, r.kind, r.id) or (0,))[0]] for r in read_set.entity_revisions if r.kind in records.HEAD_TABLES),
            "fingerprints": {k: admission.current_fingerprint(run.ctx, k) for k in sorted(read_set.fingerprints)},
            "epochs": [run.txn.meta.policy_revision, run.txn.meta.tombstone_epoch],
        }
    )
    key = digest_of(["reevaluate", current.idempotency_key, signature])
    new_job = _requeue_revalidation(run, current) if current.kind == "revalidate" else None
    if new_job is None:
        new_job, _created = jobs.enqueue(
            run.txn, kind=current.kind, input_refs=refs, now=run.now, prompt_version=current.prompt_version, review_priority=current.review_priority, coalesce=True, idempotency=key,
        )
    run.txn.execute(
        "INSERT OR IGNORE INTO operations (operation_id, job_id, proposal_id, atomic_group_id, actor, kind, inputs, changed, reason, causal_root, store_revision, created_at, local_ref, proposal_digest) VALUES (?, ?, ?, NULL, ?, ?, ?, '[]', NULL, ?, ?, ?, ?, ?)",
        (
            operation_id(new_job, run.digest, REQUEUE_REF), new_job, run.proposal_id, _actor_json(run.ctx), REQUEUE_KIND,
            canonical_json({"from_job_id": job.job_id, "depth": depth + 1, "root_job_id": root_job, "reason": reason}).decode(), root_job, run.txn.next_store_revision, run.now, REQUEUE_REF, run.digest,
        ),
    )
    jobs.supersede(run.txn, current, REQUEUED)
    result = ApplyResult(operation_ids=[], changed_refs=[], decisions=_all(response, "requeue", reason), store_revision=run.txn.next_store_revision, requeued_job_ids=[new_job])
    _write_application(run, APPLICATION_KIND, result, app_id=operation_id(run.scope_id, run.digest, APPLY_REF))
    return result


def _requeue_revalidation(run: _Run, current: Job) -> str | None:
    """A stale revalidation joins the claims' current revalidation (coalesced with any newer recheck's job)."""
    claim_ids = [r.id for r in current.input_refs if r.kind == "claim"]
    if current.priority != jobs.BAND_REVALIDATION or not any(revalidate.pending(run.txn, c) for c in claim_ids):
        return None
    revalidate.enqueue(run.txn, claim_ids, now=run.now)
    for claim_id in claim_ids:
        row = run.txn.one("SELECT job_id FROM claim_rechecks WHERE claim_id = ? AND state = 'pending' AND job_id IS NOT NULL ORDER BY created_at DESC LIMIT 1", (claim_id,))
        if row is not None and row[0] != current.job_id:
            return row[0]
    return None


def _apply(run: _Run, response: ModelResponse, read_set: ReadSet | None, *, kind: str) -> ApplyResult:
    verdict = admission.check_read_set(run.txn, run.ctx, read_set) if read_set is not None else None
    if verdict is None and _stale_targets(run.txn, response.operations):
        verdict = admission.Verdict(admission.REQUEUE, "stale_revision")
    if verdict is not None and verdict.outcome == admission.REQUEUE:
        if run.job is None:
            raise RecalithError("revision_conflict", f"{verdict.reason}: nothing was applied")
        return _requeue(run, response, read_set or ReadSet(workspace_id=run.ctx.workspace_id, policy_revision=run.txn.meta.policy_revision, tombstone_epoch=run.txn.meta.tombstone_epoch), verdict.reason)
    if verdict is not None:
        decisions, operation_ids, changed = _all(response, "reject", verdict.reason), [], []
    else:
        if run.job is not None and run.job.kind == "review_claims":
            run.resolution.review = review.scope_for(run.txn, run.job, response)
        decisions, operation_ids, changed = _run_groups(run, response)
        if run.revalidating:
            assert run.job is not None and read_set is not None
            settled = revalidate.settle(run.txn, run.ctx, run.job, read_set, decided=run.decided, now=run.now)
            changed = [*changed, *settled.refs]
            run.serving = run.serving or settled.serving
        if run.revalidate_claims:
            revalidate.enqueue(run.txn, sorted(run.revalidate_claims), now=run.now)
        if run.resolution.review is not None:
            review.record_outcomes(run.txn, run.resolution.review, response, decisions, now=run.now)
        if run.review_queue:
            review.schedule(run.txn, run.ctx, run.review_queue, origin_job_id=run.job.job_id if run.job else None, submission_id=None if run.job else run.scope_id, now=run.now)
            failpoints.hit(failpoints.REVIEW_AFTER_SCHEDULE)
    result = ApplyResult(operation_ids=operation_ids, changed_refs=changed, decisions=decisions, store_revision=run.txn.next_store_revision, requeued_job_ids=[])
    if run.job is not None:
        jobs.complete(run.txn, run.job, proposal_ref=run.proposal_id)
    _write_application(run, kind, result, app_id=operation_id(run.scope_id, run.digest, APPLY_REF))
    return result


def apply_proposal(ctx: InstallationContext, job: Job, response: ModelResponse, *, store: Store | None = None, now: str | None = None) -> ApplyResult:
    """Apply a persisted proposal for a leased job (DATA_CONTRACTS §11), once.

    Runs inside ``jobs.fenced``: a superseded or expired lease, a changed read
    set or a stale revision applies nothing. A duplicate of an already
    committed application returns the original result before the lease check.
    """
    digest = proposal_digest(response)
    app_id = operation_id(job.job_id, digest, APPLY_REF)
    own = store is None
    store = store or open_store(ctx)
    now = now or utc_now()
    try:
        with store.read() as view:
            done = stored_result(view, app_id)
        if done is not None:
            return done
        try:
            with jobs.fenced(store, job, now=now) as txn:
                done = stored_result(txn, app_id)
                if done is not None:
                    return done
                current = jobs.get_job(txn, job.job_id)
                assert current is not None
                if current.proposal_ref is None:
                    raise RecalithError("policy_refused", "a proposal is persisted before it is applied")
                persisted, read_set, persisted_digest = load_proposal(txn, current.proposal_ref)
                if persisted_digest != digest:
                    raise RecalithError("policy_refused", "the response is not the job's persisted proposal")
                depth_root = _depth(txn, job.job_id)[1]
                run = _Run(ctx=ctx, txn=txn, scope_id=job.job_id, digest=digest, now=now, job=current, proposal_id=current.proposal_ref, causal_root=depth_root, provenance=persisted.provenance, read_set=read_set)
                result = _apply(run, persisted, read_set, kind=APPLICATION_KIND)
                failpoints.hit(failpoints.JOB_BEFORE_COMPLETE_COMMIT)
        except RecalithError as exc:
            if exc.code == "revision_conflict" and "lease fenced" in exc.message:
                with store.read() as view:
                    done = stored_result(view, app_id)
                if done is not None:
                    return done
            raise
        failpoints.hit(failpoints.JOB_AFTER_COMPLETE)
        return result
    finally:
        if own:
            store.close()


def apply_operations(
    ctx: InstallationContext,
    operations: Sequence[ProposedOperation],
    *,
    read_set: ReadSet,
    submission_id: str,
    store: Store | None = None,
    now: str | None = None,
) -> ApplyResult:
    """A service writer's typed operations, applied with the same rules as a proposal.

    The actor is the resolved context's (assigned by the guarded transport,
    Task 12a). ``submission_id`` makes a retry idempotent. A revision conflict
    raises ``revision_conflict`` and applies nothing; there is no job to requeue.
    """
    own = store is None
    store = store or open_store(ctx)
    now = now or utc_now()
    try:
        with store.transaction() as txn:
            result = apply_in_transaction(txn, ctx, operations, read_set=read_set, submission_id=submission_id, now=now, kind=SERVICE_KIND)
            failpoints.hit(failpoints.SERVICE_BEFORE_COMMIT)
        return result
    finally:
        if own:
            store.close()


def apply_in_transaction(
    txn: Txn,
    ctx: InstallationContext,
    operations: Sequence[ProposedOperation],
    *,
    read_set: ReadSet,
    submission_id: str,
    now: str,
    kind: str = REDUCTION_KIND,
    review_origin: str | None = None,
) -> ApplyResult:
    """Apply typed operations inside a write transaction the caller already holds.

    This is the same application as :func:`apply_operations` (admission,
    revision checks, atomic groups, deterministic operation IDs, the
    ``@apply`` record, the epochs), used by the deterministic reducer inside
    its fenced ingest job so typed reduction and job completion commit
    together. ``kind`` is ``apply_reduction`` for the reducer. The guarded
    operator transport (Task 12a) applies a correction with ``kind``
    ``apply_service`` and ``review_origin="operator_correction"`` so its
    replacement's review is recorded as a correction (same review path).
    """
    if not policy.allowed_kinds(ctx.actor):
        raise RecalithError("policy_refused", "this actor cannot apply memory operations")
    response = ModelResponse(response_schema=1, operations=list(operations), no_op_reason=None if operations else "empty submission", usage=_NO_USAGE, provenance=None)
    digest = proposal_digest(response)
    done = stored_result(txn, operation_id(submission_id, digest, APPLY_REF))
    if done is not None:
        return done
    source = "reduction" if kind == REDUCTION_KIND else "service"
    if review_origin is not None and review_origin not in ("operator_declaration", "operator_correction", "typed_declaration"):
        raise ValueError("unknown review origin")
    run = _Run(ctx=ctx, txn=txn, scope_id=submission_id, digest=digest, now=now, job=None, proposal_id=None, causal_root=submission_id, source=source, read_set=read_set, review_origin=review_origin)
    return _apply(run, response, read_set, kind=kind)


def _usage():
    from recalith.contracts.operations import UsageReport

    return UsageReport(input_tokens=0, output_tokens=0, estimated_input_tokens=0, estimated_output_tokens=0, provider_request_id=None, duration_ms=0)


_NO_USAGE = _usage()


# --------------------------------------------------------------------------
# Compensating undo


def _status_of(kind: str, data: dict[str, Any]) -> str:
    return data["state"] if kind == "episode" else data["status"]


def _compute_undo(q: Any, operation_id_: str) -> tuple[list[UndoChange], list[UndoConflict], list[tuple[RecordRef, dict[str, Any]]]]:
    compensations, conflicts, planned, _bindings = _compute_undo_all(q, operation_id_)
    return compensations, conflicts, planned


def _compute_undo_all(q: Any, operation_id_: str) -> tuple[list[UndoChange], list[UndoConflict], list[tuple[RecordRef, dict[str, Any]]], list[tuple[str, dict[str, Any], str | None, str | None]]]:
    row = q.execute("SELECT kind, changed FROM operations WHERE operation_id = ?", (operation_id_,)).fetchone()
    if row is None:
        raise RecalithError("invalid_schema", "no such operation")
    kind, changed = row
    if kind not in policy.MUTATING_KINDS and kind != UNDO_KIND:
        raise RecalithError("policy_refused", "only memory operations can be undone")
    compensations: list[UndoChange] = []
    conflicts: list[UndoConflict] = []
    planned: list[tuple[RecordRef, dict[str, Any]]] = []
    planned_bindings: list[tuple[str, dict[str, Any], str | None, str | None]] = []
    entries = json.loads(changed)
    boundaries = {e["boundary"]: e for e in entries if "boundary" in e}
    for entry in entries:
        if "boundary" in entry:
            continue  # restored with the bindings it decided (below)
        if "pending_supersession" in entry:
            continue  # a held supersession changed no record (it is withdrawn when its replacement retires)
        if "binding" in entry:
            event_id, before, after = entry["binding"], entry["before"], entry["after"]
            head = bindings.binding_head(q, event_id)
            ref = RecordRef(kind="event", id=event_id, revision=1)
            current = 0 if head is None else head["revision"]
            if before is None:
                conflicts.append(UndoConflict(ref=ref, undone_revision=after["revision"], current_revision=current, fields=["task_id"], reason="initial_binding"))
            elif current != after["revision"]:
                conflicts.append(UndoConflict(ref=ref, undone_revision=after["revision"], current_revision=current, fields=["task_id"], reason="changed_later"))
            else:
                compensations.append(UndoChange(action="restore_fields", ref=ref, fields=["task_id"], relation=None))
                decided = boundaries.get(after.get("boundary_id") or "")
                restore_state = decided["before"] if decided is not None else None
                planned_bindings.append((event_id, before, after.get("boundary_id") if decided is not None else None, restore_state))
            continue
        if "relation" in entry:
            source, target, relation = entry["relation"]
            present = q.execute("SELECT 1 FROM relations WHERE source_id = ? AND target_id = ? AND relation = ?", (source, target, relation)).fetchone() is not None
            if entry.get("added") and present:
                compensations.append(UndoChange(action="remove_relation", ref=None, fields=[], relation=[source, target, relation]))
            continue
        after = RecordRef.model_validate(entry["ref"])
        before = entry["before"]
        current = records.head(q, after.kind, after.id)
        if current is None:
            conflicts.append(UndoConflict(ref=after, undone_revision=after.revision, current_revision=0, fields=[], reason="record_missing"))
            continue
        head_ref = RecordRef(kind=after.kind, id=after.id, revision=current[0])
        after_body = records.body(q, after.kind, after.id, after.revision)
        before_body = records.body(q, after.kind, after.id, before) if before is not None else None
        current_body = records.body(q, after.kind, after.id, current[0])
        if after_body is None or current_body is None or (before is not None and before_body is None):
            conflicts.append(UndoConflict(ref=head_ref, undone_revision=after.revision, current_revision=current[0], fields=[], reason="body_unavailable"))
            continue
        if current[1] in policy.CONTENT_FREE_STATUSES:
            conflicts.append(UndoConflict(ref=head_ref, undone_revision=after.revision, current_revision=current[0], fields=[], reason="content_free"))
            continue
        if before is None:
            retire = policy.UNDO_RETIRE_STATUS.get(after.kind)
            if retire is None:
                conflicts.append(UndoConflict(ref=head_ref, undone_revision=after.revision, current_revision=current[0], fields=[], reason="not_undoable"))
            elif _status_of(after.kind, current_body) != _status_of(after.kind, after_body) or current[1] == retire:
                conflicts.append(UndoConflict(ref=head_ref, undone_revision=after.revision, current_revision=current[0], fields=["state" if after.kind == "episode" else "status"], reason="changed_later"))
            else:
                restored = dict(current_body)
                restored["state" if after.kind == "episode" else "status"] = retire
                compensations.append(UndoChange(action="retire", ref=head_ref, fields=["state" if after.kind == "episode" else "status"], relation=None))
                planned.append((head_ref, restored))
            continue
        assert before_body is not None
        keys = sorted(k for k in set(before_body) | set(after_body) if k not in policy.UNDO_IGNORED_KEYS and before_body.get(k) != after_body.get(k))
        restorable = [k for k in keys if current_body.get(k) == after_body.get(k)]
        later = [k for k in keys if k not in restorable]
        if restorable:
            restored = dict(current_body)
            for k in restorable:
                if k in before_body:
                    restored[k] = before_body[k]
                else:
                    restored.pop(k, None)
            try:
                _validate(records.DTO[after.kind], {**restored, "revision": current[0] + 1})
            except (ValidationError, ValueError):
                conflicts.append(UndoConflict(ref=head_ref, undone_revision=after.revision, current_revision=current[0], fields=restorable, reason="invalid_restore"))
            else:
                compensations.append(UndoChange(action="restore_fields", ref=head_ref, fields=restorable, relation=None))
                planned.append((head_ref, restored))
        if later:
            conflicts.append(UndoConflict(ref=head_ref, undone_revision=after.revision, current_revision=current[0], fields=later, reason="changed_later"))
    return compensations, conflicts, planned, planned_bindings


def _preview(q: Any, operation_id_: str) -> tuple[UndoPreview, list[tuple[RecordRef, dict[str, Any]]]]:
    preview, planned, _bindings = _preview_all(q, operation_id_)
    return preview, planned


def _preview_all(q: Any, operation_id_: str):
    compensations, conflicts, planned, planned_bindings = _compute_undo_all(q, operation_id_)
    if not compensations and not conflicts:
        state = "nothing_to_undo"
    elif not conflicts:
        state = "clean"
    elif compensations:
        state = "partial"
    else:
        state = "conflicted"
    digest = digest_of({"operation_id": operation_id_, "compensations": [c.model_dump(mode="json") for c in compensations], "conflicts": [c.model_dump(mode="json") for c in conflicts]})
    return UndoPreview(operation_id=operation_id_, state=state, compensations=compensations, conflicts=conflicts, preview_digest=digest), planned, planned_bindings  # type: ignore[arg-type]


def preview_undo(ctx: InstallationContext, operation_id_: str, *, store: Store | None = None) -> UndoPreview:
    """Read-only: the compensating change for one operation and every conflicting later revision."""
    own = store is None
    store = store or open_store(ctx, readonly=True)
    try:
        with store.read() as view:
            return _preview(view, operation_id_)[0]
    finally:
        if own:
            store.close()


def apply_undo(ctx: InstallationContext, operation_id_: str, *, preview_digest: str, store: Store | None = None, now: str | None = None) -> ApplyResult:
    """Append exactly the compensation a current preview showed (operator only)."""
    if ctx.actor.kind != "operator":
        raise RecalithError("policy_refused", "undo is an operator action")
    undo_id = derived_id("op", [UNDO_REF, operation_id_, preview_digest])
    own = store is None
    store = store or open_store(ctx)
    now = now or utc_now()
    try:
        with store.transaction() as txn:
            row = txn.one("SELECT inputs FROM operations WHERE operation_id = ?", (undo_id,))
            if row is not None:
                return ApplyResult.model_validate(json.loads(row[0])["result"])
            preview, planned, planned_bindings = _preview_all(txn, operation_id_)
            if preview.preview_digest != preview_digest:
                raise RecalithError("revision_conflict", "the undo preview is no longer current; preview again")
            if not preview.compensations:
                raise RecalithError("revision_conflict", "nothing can be compensated: every change was superseded by later revisions")
            change = _Change()
            for ref, restored in planned:
                data = {**restored, "revision": ref.revision + 1}
                if ref.kind == "claim":
                    data["recorded_at"] = now
                elif ref.kind == "task":
                    data["updated_at"] = now
                record = _validate(records.DTO[ref.kind], data)
                workspace = records.task_workspace(txn, ref.id) if ref.kind == "task" else None
                new_ref = records.write(txn, ref.kind, record, workspace_id=workspace)
                change.record(new_ref, ref.revision)
            writer = _UndoWriter(txn, ctx, now, undo_id, change)
            restored_boundaries: dict[str, str] = {}
            for event_id, before, boundary_id, boundary_state in planned_bindings:
                row = txn.one("SELECT commit_sequence, session_id FROM events WHERE event_id = ?", (event_id,))
                bindings.write_binding(writer, event_id, seq=row[0], session_id=row[1], task_id=before["task_id"], binding=before["binding"], boundary_id=before.get("boundary_id"))
                if boundary_id is not None and boundary_state is not None:
                    restored_boundaries[boundary_id] = boundary_state
            for boundary_id, state_ in sorted(restored_boundaries.items()):
                candidate = bindings.load_boundary(txn, boundary_id)
                if candidate is not None and candidate.state != state_:
                    txn.execute("UPDATE task_boundaries SET state = ?, body = ? WHERE boundary_id = ?", (state_, candidate.model_copy(update={"state": state_}).model_dump_json(), boundary_id))
                    change.boundary(boundary_id, candidate.state, state_)
            for comp in preview.compensations:
                if comp.action == "remove_relation" and comp.relation is not None:
                    source, target, relation = comp.relation
                    if records.remove_relation(txn, source, target, relation):
                        change.entries.append({"relation": [source, target, relation], "added": False})
            # An undo never revives guidance over evidence that is gone: a reactivated claim whose support expired
            # meanwhile is downgraded in this transaction (Task 15, decision 0016).
            from recalith.privacy import retention

            retention.reconcile(txn, ctx, [ref.id for ref, _restored in planned if ref.kind == "claim"], now=now)
            result = ApplyResult(operation_ids=[undo_id], changed_refs=change.refs, decisions=[], store_revision=txn.next_store_revision, requeued_job_ids=[])
            txn.execute(
                "INSERT INTO operations (operation_id, job_id, proposal_id, atomic_group_id, actor, kind, inputs, changed, reason, causal_root, store_revision, created_at, local_ref, proposal_digest) VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    undo_id, derived_id("grp", [UNDO_REF, undo_id]), canonical_json(ctx.actor).decode(), UNDO_KIND,
                    canonical_json({"undone_operation_id": operation_id_, "preview_digest": preview_digest, "result": result.model_dump(mode="json")}).decode(),
                    canonical_json(change.entries).decode(), "operator undo", operation_id_, txn.next_store_revision, now, UNDO_REF,
                ),
            )
            txn.mutated(serving_relevant=True)
            failpoints.hit(failpoints.SERVICE_BEFORE_COMMIT)
        return result
    finally:
        if own:
            store.close()


class _UndoWriter:
    """Binding writes of an operator undo (``bindings.Writer``), recorded on the undo operation."""

    def __init__(self, txn: Txn, ctx: InstallationContext, now: str, op_id: str, change: _Change) -> None:
        self.txn, self.ctx, self.now, self.op_id, self.source, self._change = txn, ctx, now, op_id, "service", change

    def record(self, ref: RecordRef, before: int | None) -> None:
        self._change.record(ref, before)

    def created(self, kind: str, record_id: str) -> None:
        pass

    def binding(self, event_id: str, before: dict[str, Any] | None, after: dict[str, Any]) -> None:
        self._change.binding(event_id, before, after)

    def boundary(self, boundary_id: str, before: str | None, after: str) -> None:
        self._change.boundary(boundary_id, before, after)

    def serving(self) -> None:
        pass


def _days(n: int):
    import datetime as _dt

    return _dt.timedelta(days=n)


__all__ = [
    "apply_proposal", "apply_operations", "persist_proposal", "load_proposal", "proposal_digest", "operation_id",
    "preview_undo", "apply_undo", "stored_result", "MalformedOperation",
]
