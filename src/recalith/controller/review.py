"""Adversarial review of claim candidates (SYSTEM_SPEC §6.2, §7.1.2, §7.2; DATA_CONTRACTS §5, §6.2, §7.1, §8, §11).

**Scheduling** (:func:`schedule`). Every application that writes a new or
changed candidate (an extraction's ``propose_claim``/``attach_evidence``/
``revise_claim``, or a typed operator declaration) schedules its review in the
same transaction: one persisted extraction job (or one service submission) is
partitioned in stable proposal order into review jobs of at most eight
candidates, at most as many as the 9,000-byte review body holds at 768 bytes
per compact assessment beside the 2,000-byte envelope, and at most the 96 KiB
serialized request. A candidate too large to review on its own is deferred
(``review_outcomes``: ``deferred``), never truncated. Recording an assessment
never schedules another review, so a ``review_capacity`` reject cannot loop.
The review priority is code-assigned from the guarded origin and candidate
kind (``jobs.review_priority_for``); it orders launches, it never admits.

**Batches** (:func:`prepare`). The review request is built from the job's
persisted, immutable :class:`ReviewBatch` (made under the job's lease fence
before any reservation and reused while unchanged): the candidates in batch
order through an allowlisted view that drops review rationale and provider
provenance (a proposal's ``reason`` and an extractor's rationale or
self-confidence are not claim fields and never reach it), and exactly their
batch evidence: event text is never trimmed, and a batch over the input cap
fails rather than shrink. Its read set names no candidate revision, so one
changed candidate cannot requeue the others: each assessment is checked on
its own.

**Assessments** (:func:`check_assessment`). An ``assess_claim`` counts only for
the job's own batch, a candidate in it, exactly once, while the candidate's
current revision still has the snapshot digest, citing only that candidate's
batch evidence IDs. ``supported`` must cite a support link and pass every
activation gate (``admission.activation_refusal``); then the candidate becomes
active with its strength from lineage. ``revise`` records objections only (a
changed proposition is a new proposal); a substantive ``reject`` archives the
candidate (it asserts no falsity); ``reject`` with the sole objection
``review_capacity`` is a capacity failure: the candidate stays a candidate.
Missing, duplicate, foreign and stale verdicts activate nothing while valid
independent assessments in the same response apply; every outcome is
recorded per candidate with its exact reason code.

Without a certified route review jobs wait (``provider_unavailable``) and the
candidates stay weak candidates: candidate-only degradation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from recalith.contracts.common import EvidenceLink, InstallationContext, ReadSet, RecordRef, canonical_json, derived_id, digest_of, new_id
from recalith.contracts.config import ASSESSMENT_OP_MAX_BYTES, MODEL_INPUT_CAP, REVIEW_BATCH_MAX_CANDIDATES, REVIEW_ENVELOPE_BYTES, body_cap_for
from recalith.contracts.jobs import Job
from recalith.contracts.memory import ClaimRevision, Episode, ReviewBatch, ReviewEvidence, TaskState
from recalith.contracts.operations import AdmissionDecision, AssessClaimPayload, ModelRequest, ModelResponse, ProposedOperation
from recalith import prompts
from recalith.controller import admission, jobs, requests
from recalith.errors import RecalithError
from recalith.storage import records

CAPACITY = "review_capacity"
OUTCOMES = {"review_supported": "admitted", "review_revise": "revise", "review_rejected": "rejected", CAPACITY: "capacity"}
REJECTED_OUTCOMES = {"assessment_foreign": "foreign", "assessment_duplicate": "duplicate", "candidate_stale": "stale"}
# Fields of a candidate the reviewer sees; everything else (earlier assessments,
# provider provenance, any future rationale field) is withheld.
CANDIDATE_FIELDS = frozenset(ClaimRevision.model_fields) - {"review_assessment", "model_provenance"}


def output_capacity(body_cap: int | None = None) -> int:
    """Candidates one review body can assess: 768 bytes each beside the 2,000-byte envelope, at most eight."""
    cap = body_cap_for("review_claims") if body_cap is None else body_cap
    return max(0, min(REVIEW_BATCH_MAX_CANDIDATES, (cap - REVIEW_ENVELOPE_BYTES) // ASSESSMENT_OP_MAX_BYTES))


def candidate_view(claim: ClaimRevision) -> ClaimRevision:
    """The allowlisted claim a reviewer sees (rationale-free; proposition, scope, conditions and evidence exact).

    A cited active claim keeps only the supported verdict it cannot exist
    without (no objection text); a candidate shows none.
    """
    data = {k: v for k, v in claim.model_dump(mode="json").items() if k in CANDIDATE_FIELDS}
    kept = requests.claim_for_request(claim).review_assessment
    return ClaimRevision.model_validate({**data, "review_assessment": kept.model_dump(mode="json") if kept is not None else None, "model_provenance": None})


# --------------------------------------------------------------------------
# Batch snapshots and the review request


def snapshot(view: Any, *, review_job_id: str, origin_job_id: str | None, candidates: Sequence[ClaimRevision], version: str, read_set: ReadSet) -> ReviewBatch:
    index: list[ReviewEvidence] = []
    seen: set[str] = set()
    for claim in candidates:
        for link in [*claim.supports, *claim.contradicts]:
            evidence_id = evidence_id_of(link)
            if evidence_id not in seen:
                seen.add(evidence_id)
                index.append(ReviewEvidence(evidence_id=evidence_id, link=link))
    return ReviewBatch(
        batch_id=new_id("batch"),
        origin_job_id=origin_job_id,
        review_job_id=review_job_id,
        candidate_refs=[records.ref_of(c) for c in candidates],
        candidate_digests={c.claim_id: candidate_digest(c) for c in candidates},
        evidence_digest=digest_of([e.model_dump(mode="json") for e in index]),
        prompt_digest=prompts.prompt_digest(version),
        evidence_index=index,
        read_set=read_set,
    )


def evidence_id_of(link: EvidenceLink) -> str:
    return derived_id("evd", link.model_dump(mode="json"))


def candidate_digest(claim: ClaimRevision) -> str:
    return digest_of(claim.model_dump(mode="json"))


def _evidence_records(view: Any, ctx: InstallationContext, batch: ReviewBatch) -> tuple[list[str], list[Episode], list[ClaimRevision], TaskState | None]:
    events: list[str] = []
    episodes: list[Episode] = []
    claims: list[ClaimRevision] = []
    task: TaskState | None = None
    for evidence in batch.evidence_index:
        ref = evidence.link.ref
        if ref.kind == "event":
            if ref.id not in events:
                events.append(ref.id)
        elif ref.kind in ("episode", "claim", "task"):
            record = records.load(view, ref.kind, ref.id, ref.revision)
            if isinstance(record, Episode) and all(e.episode_id != record.episode_id or e.revision != record.revision for e in episodes):
                episodes.append(record)
            elif isinstance(record, ClaimRevision) and all(c.claim_id != record.claim_id for c in claims):
                claims.append(candidate_view(record))
            elif isinstance(record, TaskState) and task is None:
                task = record
    return events, episodes, claims, task


def request_data(view: Any, ctx: InstallationContext, *, job_id: str, version: str, instruction: str, batch: ReviewBatch, candidates: Sequence[ClaimRevision], extra_events: Iterable[str] = (), timeout_seconds: int = 120) -> dict[str, Any]:
    """The review request exactly as serialized (also used to size partitions before a job exists)."""
    policy_revision, tombstone_epoch = requests.view_meta(view)
    event_ids, episodes, cited_claims, task = _evidence_records(view, ctx, batch)
    for event_id in extra_events:
        if event_id not in event_ids:
            event_ids.append(event_id)
    loaded = sorted(requests.load_events(view, ctx, event_ids), key=lambda pair: pair[0])
    claims = [candidate_view(c) for c in candidates] + [c for c in cited_claims if c.claim_id not in {x.claim_id for x in candidates}]
    allowed = [e.link.ref for e in batch.evidence_index] + [RecordRef(kind="event", id=e.event_id, revision=1) for _s, e in loaded]
    read_set = ReadSet(workspace_id=ctx.workspace_id, policy_revision=policy_revision, tombstone_epoch=tombstone_epoch)
    return {
        "request_schema": 1, "job_id": job_id, "purpose": "review_claims", "prompt_version": version, "instruction_text": instruction,
        "events": [e.model_dump(mode="json") for _s, e in loaded], "episodes": [e.model_dump(mode="json") for e in episodes],
        "claims": [c.model_dump(mode="json") for c in claims], "task_state": task.model_dump(mode="json") if task is not None else None,
        "boundaries": [], "allowed_evidence_refs": [r.model_dump(mode="json") for r in dict.fromkeys(allowed)],
        "read_set": read_set.model_dump(mode="json"), "output_schema": requests.output_schema("review_claims"),
        "review_batch": batch.model_dump(mode="json"), "limits": requests.limits_for("review_claims", timeout_seconds).model_dump(mode="json"),
    }


def batch_candidates(view: Any, job: Job) -> list[ClaimRevision]:
    """The job's candidates still at the revision it was scheduled for (a newer revision has its own review)."""
    out = []
    for ref in [r for r in job.input_refs if r.kind == "claim"][:REVIEW_BATCH_MAX_CANDIDATES]:
        head = records.head(view, "claim", ref.id)
        if head is None or head != (ref.revision, "candidate"):
            continue
        claim = records.load(view, "claim", ref.id, ref.revision)
        if claim is not None:
            out.append(claim)
    return out


def origin_of(view: Any, review_job_id: str) -> tuple[str | None, str | None]:
    row = view.execute("SELECT origin_job_id, origin FROM review_requests WHERE review_job_id = ?", (review_job_id,)).fetchone()
    return (None, None) if row is None else (row[0], row[1])


def prepare(view: Any, ctx: InstallationContext, job: Job, *, rounds: Sequence[ModelResponse], instruction: str, timeout_seconds: int) -> tuple[ModelRequest, ReviewBatch | None]:
    """(request, batch to persist or None when the persisted snapshot is reused)."""
    candidates = batch_candidates(view, job)
    if not candidates:
        raise requests.NothingToPrepare("review_candidates_stale")
    version = job.prompt_version or prompts.CURRENT["review_claims"]
    read_set = ReadSet(entity_revisions=[records.ref_of(c) for c in candidates], workspace_id=ctx.workspace_id, policy_revision=requests.view_meta(view)[0], tombstone_epoch=requests.view_meta(view)[1])
    fresh = snapshot(view, review_job_id=job.job_id, origin_job_id=origin_of(view, job.job_id)[0], candidates=candidates, version=version, read_set=read_set)
    existing = requests.persisted_batch(view, job.job_id)
    batch, new = (existing, None) if existing is not None and requests.same_batch(existing, fresh) else (fresh, fresh)
    extra = requests.expansion_events(view, ctx, rounds)
    data = request_data(view, ctx, job_id=job.job_id, version=version, instruction=instruction, batch=batch, candidates=candidates, extra_events=extra, timeout_seconds=timeout_seconds)
    if len(canonical_json(data)) > MODEL_INPUT_CAP:
        # Evidence is never trimmed for review: a misleading partial judgment is worse than none.
        raise requests.PrepareFailed("review_input_oversized", "a review batch never drops evidence to fit", final=True)
    return ModelRequest.model_validate(data), new


# --------------------------------------------------------------------------
# Scheduling and partitions


@dataclass(frozen=True)
class Queued:
    """A candidate revision an application wrote that needs review."""

    ref: RecordRef
    claim_kind: str
    basis: str
    origin: str  # extracted | typed_declaration | operator_declaration | operator_correction


def _request_bytes(view: Any, ctx: InstallationContext, claims: Sequence[ClaimRevision]) -> int:
    version = prompts.CURRENT["review_claims"]
    placeholder = new_id("job")  # same length as the real review job ID
    batch = snapshot(view, review_job_id=placeholder, origin_job_id=new_id("job"), candidates=claims, version=version, read_set=ReadSet(entity_revisions=[records.ref_of(c) for c in claims], workspace_id=ctx.workspace_id, policy_revision=1, tombstone_epoch=0))
    data = request_data(view, ctx, job_id=placeholder, version=version, instruction=prompts.instruction(version, "review_claims"), batch=batch, candidates=claims)
    return len(canonical_json(data))


def partition(view: Any, ctx: InstallationContext, claims: Sequence[ClaimRevision], *, per_batch: int | None = None, input_cap: int = MODEL_INPUT_CAP) -> tuple[list[list[ClaimRevision]], list[ClaimRevision]]:
    """Stable partitions by candidate count, output body and serialized input; oversized single candidates are deferred."""
    per_batch = output_capacity() if per_batch is None else per_batch
    batches: list[list[ClaimRevision]] = []
    deferred: list[ClaimRevision] = []
    current: list[ClaimRevision] = []
    for claim in claims:
        if current and len(current) < per_batch and _request_bytes(view, ctx, [*current, claim]) <= input_cap:
            current.append(claim)
            continue
        if current:
            batches.append(current)
            current = []
        if _request_bytes(view, ctx, [claim]) > input_cap:
            deferred.append(claim)  # too large to review safely on its own: deferred, never truncated
        else:
            current = [claim]
    if current:
        batches.append(current)
    return batches, deferred


def schedule(txn: Any, ctx: InstallationContext, queued: Sequence[Queued], *, origin_job_id: str | None, submission_id: str | None, now: str) -> list[str]:
    """Review jobs for an application's new candidates, in its transaction; returns created job IDs."""
    latest: dict[str, Queued] = {}
    for item in queued:
        latest[item.ref.id] = item
    claims: list[tuple[Queued, ClaimRevision]] = []
    for item in latest.values():
        # The head as this application leaves it: a later operation of the same application (a supersession
        # naming this candidate as replacement, say) may have written a newer candidate revision.
        head = records.head(txn, "claim", item.ref.id)
        if head is None or head[1] != "candidate":
            continue
        claim = records.load(txn, "claim", item.ref.id, head[0])
        if claim is not None:
            claims.append((item, claim))
    if not claims:
        return []
    batches, deferred = partition(txn, ctx, [c for _q, c in claims])
    for claim in deferred:
        record_outcome(txn, claim_id=claim.claim_id, revision=claim.revision, batch_id=None, review_job_id=None, outcome="deferred", reason="review_input_oversized", now=now, key="deferred")
    by_id = {c.claim_id: q for q, c in claims}
    created: list[str] = []
    for index, batch in enumerate(batches):
        refs = [records.ref_of(c) for c in batch]
        candidates = [jobs.ReviewCandidate(claim_id=c.claim_id, origin=by_id[c.claim_id].origin, claim_kind=c.kind, direct_user_evidence=c.basis == "user_declared") for c in batch]
        origin = next((q.origin for q in (by_id[c.claim_id] for c in batch) if q.origin != "extracted"), "extracted")
        key = digest_of(["review", origin_job_id, submission_id, index, [r.model_dump(mode="json") for r in refs]])
        job_id, new = jobs.enqueue(txn, kind="review_claims", input_refs=refs, now=now, prompt_version=prompts.CURRENT["review_claims"], review_candidates=candidates, idempotency=key)
        if new:
            txn.execute(
                "INSERT INTO review_requests (review_job_id, origin_job_id, submission_id, origin, partition_index, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (job_id, origin_job_id, submission_id, origin, index, now),
            )
            created.append(job_id)
    return created


# --------------------------------------------------------------------------
# Assessment admission


@dataclass
class ReviewScope:
    """What an assessment is checked against while a review job's proposal applies."""

    job: Job
    batch: ReviewBatch
    counts: dict[str, int] = field(default_factory=dict)  # candidate claim id -> assessments naming it

    def link(self, evidence_id: str) -> EvidenceLink | None:
        return next((e.link for e in self.batch.evidence_index if e.evidence_id == evidence_id), None)

    def own_evidence(self, claim: ClaimRevision) -> set[str]:
        return {evidence_id_of(link) for link in [*claim.supports, *claim.contradicts]}


def scope_for(view: Any, job: Job, response: ModelResponse) -> ReviewScope | None:
    """The persisted batch of a review job (None when no batch was persisted for it)."""
    batch = requests.persisted_batch(view, job.job_id)
    if batch is None:
        return None
    counts: dict[str, int] = {}
    for op in response.operations:
        if op.kind == "assess_claim":
            ref = op.payload.get("candidate_ref") if isinstance(op.payload, dict) else None
            claim_id = ref.get("id") if isinstance(ref, dict) else None
            if isinstance(claim_id, str):
                counts[claim_id] = counts.get(claim_id, 0) + 1
    return ReviewScope(job=job, batch=batch, counts=counts)


def check_assessment(q: Any, ctx: InstallationContext, op: ProposedOperation, typed: AssessClaimPayload, scope: ReviewScope | None) -> admission.Verdict:
    if scope is None:
        return admission.Verdict(admission.REJECT, "assessment_outside_review")
    batch = scope.batch
    ref = typed.candidate_ref
    if typed.batch_id != batch.batch_id or ref not in batch.candidate_refs:
        return admission.Verdict(admission.REJECT, "assessment_foreign")
    if scope.counts.get(ref.id, 0) > 1:
        return admission.Verdict(admission.REJECT, "assessment_duplicate")  # a candidate has exactly one verdict or none counts
    head = records.head(q, "claim", ref.id)
    claim = records.load(q, "claim", ref.id, ref.revision) if head is not None else None
    if head != (ref.revision, "candidate") or claim is None or candidate_digest(claim) != batch.candidate_digests.get(ref.id):
        return admission.Verdict(admission.REJECT, "candidate_stale")
    own = scope.own_evidence(claim)
    if any(e not in own for e in typed.evidence_ids):
        return admission.Verdict(admission.REJECT, "evidence_id_unknown")  # only this candidate's batch evidence
    capacity = typed.verdict == "reject" and typed.objections == [CAPACITY]
    if CAPACITY in typed.objections and not capacity:
        return admission.Verdict(admission.REJECT, "capacity_requires_sole_reject")
    if typed.verdict == "revise" and not typed.objections:
        return admission.Verdict(admission.REJECT, "revise_requires_objection")
    if typed.verdict == "supported":
        cited = [scope.link(e) for e in typed.evidence_ids]
        if not any(link is not None and link.relation == "supports" for link in cited):
            return admission.Verdict(admission.REJECT, "supported_requires_support_evidence")
        for link in cited:
            assert link is not None
            if (reason := admission.check_link(q, link)) is not None:
                return admission.Verdict(admission.REJECT, reason)
        if (reason := admission.activation_refusal(q, claim.model_dump(mode="json"))) is not None:
            return admission.Verdict(admission.REJECT, reason)
        return admission.Verdict(admission.APPLY, "review_supported")
    if capacity:
        return admission.Verdict(admission.APPLY, CAPACITY)  # a capacity failure, not a refutation
    return admission.Verdict(admission.APPLY, "review_rejected" if typed.verdict == "reject" else "review_revise")


# --------------------------------------------------------------------------
# Outcomes


def record_outcome(txn: Any, *, claim_id: str, revision: int, batch_id: str | None, review_job_id: str | None, outcome: str, reason: str, now: str, key: str) -> None:
    outcome_id = digest_of([batch_id, claim_id, revision, outcome, key])
    txn.execute(
        "INSERT OR IGNORE INTO review_outcomes (outcome_id, claim_id, claim_revision, batch_id, review_job_id, outcome, reason_code, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (outcome_id, claim_id, revision, batch_id, review_job_id, outcome, reason[:64], now),
    )


def record_outcomes(txn: Any, scope: ReviewScope, response: ModelResponse, decisions: Sequence[AdmissionDecision], *, now: str) -> None:
    """One exact outcome per assessment, and ``missing`` for every batch candidate no assessment named."""
    by_ref = {d.local_ref: d for d in decisions}
    named: set[tuple[str, int]] = set()
    batch = scope.batch
    for op in response.operations:
        if op.kind != "assess_claim":
            continue
        typed = op.typed_payload()
        assert isinstance(typed, AssessClaimPayload)
        ref = typed.candidate_ref
        named.add((ref.id, ref.revision))
        decision = by_ref.get(op.local_ref)
        if decision is None:
            continue
        if decision.outcome == "apply":
            outcome = OUTCOMES.get(decision.reason_code, "refused")
        else:
            outcome = REJECTED_OUTCOMES.get(decision.reason_code, "refused")
        record_outcome(txn, claim_id=ref.id, revision=ref.revision, batch_id=batch.batch_id, review_job_id=scope.job.job_id, outcome=outcome, reason=decision.reason_code, now=now, key=op.local_ref)
    for ref in batch.candidate_refs:
        if (ref.id, ref.revision) not in named:
            record_outcome(txn, claim_id=ref.id, revision=ref.revision, batch_id=batch.batch_id, review_job_id=scope.job.job_id, outcome="missing", reason="verdict_missing", now=now, key="missing")


def outcomes(view: Any, claim_id: str) -> list[dict[str, Any]]:
    rows = view.execute("SELECT claim_revision, batch_id, review_job_id, outcome, reason_code FROM review_outcomes WHERE claim_id = ? ORDER BY recorded_at, rowid", (claim_id,)).fetchall()
    return [{"revision": r[0], "batch_id": r[1], "review_job_id": r[2], "outcome": r[3], "reason_code": r[4]} for r in rows]


# --------------------------------------------------------------------------
# The service interface


def review_candidates(
    ctx: InstallationContext,
    claim_ids: Sequence[str],
    *,
    job: Job,
    store: Any = None,
    launch: Callable[[ModelRequest], ModelResponse] | None = None,
    now: str | None = None,
) -> ModelResponse:
    """Review the one persisted batch assigned to ``job`` (DATA_CONTRACTS §8, §11); returns the provider's response.

    The batch is snapshotted (or reused) under the job's lease fence before
    anything launches, and ``claim_ids`` must be exactly its candidates in
    order. ``launch`` defaults to the installation's certified route
    (``providers.base.complete``); without one this raises
    ``capability_unavailable`` and nothing changes: the candidates stay weak
    candidates. Budget reservation belongs to the worker's model lane, which
    prepares review jobs through this same path; the response is applied with
    ``controller.apply`` after it is persisted.
    """
    request = requests.prepare_model_request(ctx, job, store=store, now=now)
    batch = request.review_batch
    assert batch is not None
    if [r.id for r in batch.candidate_refs] != list(claim_ids):
        raise RecalithError("invalid_schema", "claim_ids must be the job's persisted review batch, in order")
    if launch is None:
        from recalith.providers.base import complete, load_provider_config

        config = load_provider_config(ctx.root)
        if config is None:
            raise RecalithError("capability_unavailable", "provider route unavailable: provider_not_configured")
        return complete(request, config)
    return launch(request)


__all__ = [
    "schedule", "partition", "prepare", "snapshot", "candidate_view", "check_assessment", "scope_for", "record_outcomes", "review_candidates",
    "output_capacity", "Queued", "ReviewScope", "CAPACITY",
]
