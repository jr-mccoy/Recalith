"""Working state, episodes, durable claims and lineage (DATA_CONTRACTS §3–§6)."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import (
    Condition,
    DependencyRef,
    Digest,
    EvidenceLink,
    Id,
    JsonObject,
    NonNegative,
    OriginEventKey,
    ReadSet,
    RecordRef,
    Revision,
    Scope,
    SourceRef,
    SpanLocator,
    StrictModel,
    UtcTime,
    bounded_text,
)
from .config import OBJECTION_MAX_BYTES, REVIEW_BATCH_MAX_CANDIDATES

Basis = Literal["observed", "user_declared", "inferred"]
Text = Annotated[str, Field(min_length=1, max_length=8192)]


class SupportedText(StrictModel):
    text: Text
    evidence: list[EvidenceLink] = Field(default_factory=list)
    basis: Basis


class PendingAction(StrictModel):
    action_id: Id
    description: SupportedText
    tool_call_id: Annotated[str, Field(max_length=256)] | None = None
    state: Literal["proposed", "running", "awaiting_result", "finished", "cancelled"]


TaskStatus = Literal["active", "paused", "completed", "abandoned", "linked"]


class TaskState(StrictModel):
    task_id: Id
    project_id: Id
    installation_id: Id
    revision: Revision
    status: TaskStatus
    redirect_task_id: Id | None = None
    title: Annotated[str, Field(min_length=1, max_length=256)]
    objective: SupportedText | None
    constraints: list[SupportedText] = Field(default_factory=list)
    plan: list[SupportedText] = Field(default_factory=list)
    pending_actions: list[PendingAction] = Field(default_factory=list)
    known_results: list[SupportedText] = Field(default_factory=list)
    blockers: list[SupportedText] = Field(default_factory=list)
    open_questions: list[SupportedText] = Field(default_factory=list)
    next_action: SupportedText | None = None
    session_ids: list[Id] = Field(default_factory=list)
    child_task_ids: list[Id] = Field(default_factory=list)
    scope: Scope = Field(default_factory=Scope)
    updated_at: UtcTime
    last_activity_at: UtcTime
    completion_basis: SupportedText | None = None

    @model_validator(mode="after")
    def _linked_placeholder(self) -> "TaskState":
        if self.status == "linked":
            if self.redirect_task_id is None:
                raise ValueError("a linked placeholder requires redirect_task_id")
            if self.redirect_task_id == self.task_id:
                raise ValueError("a linked placeholder cannot redirect to itself")
            if self.pending_actions or self.next_action is not None:
                raise ValueError("a linked placeholder carries no pending actions or next action")
        elif self.redirect_task_id is not None:
            raise ValueError("only linked placeholders redirect")
        if self.status == "completed" and self.completion_basis is None:
            raise ValueError("completion requires evidence of the stated objective")
        return self


class TaskBoundaryCandidate(StrictModel):
    boundary_id: Id
    session_id: Id
    after_event_id: Id | None
    proposed_event_ids: list[Id]
    reason: Literal["host_reset", "pivot_prefix", "disjoint_paths", "idle_resume", "new_session", "single_active_task"]
    source_task_id: Id
    state: Literal["pending", "confirmed", "rejected", "linked"]
    signal: JsonObject = Field(default_factory=dict)
    policy_revision: Revision


class TaskBindingRevision(StrictModel):
    binding_id: Id
    event_id: Id
    revision: Revision
    task_id: Id
    binding: Literal["provisional", "confirmed"]
    boundary_id: Id | None
    assigned_by_operation: Id
    previous_revision: Revision | None

    @model_validator(mode="after")
    def _chain(self) -> "TaskBindingRevision":
        if (self.revision == 1) != (self.previous_revision is None) or (self.previous_revision is not None and self.previous_revision != self.revision - 1):
            raise ValueError("binding revisions form a contiguous chain")
        return self


class TaskBindingProposal(StrictModel):
    boundary_id: Id
    decision: Literal["confirm_split", "reject", "link_session"]
    event_ids: list[Id]
    target_task_id: Id | None
    expected_binding_revisions: dict[Id, Revision]
    evidence: list[EvidenceLink] = Field(default_factory=list)

    @model_validator(mode="after")
    def _target(self) -> "TaskBindingProposal":
        if self.decision == "link_session" and self.target_task_id is None:
            raise ValueError("linking requires an existing target task")
        if self.decision == "confirm_split" and self.target_task_id is not None:
            raise ValueError("code allocates the new task id for a split")
        return self


Outcome = Literal["success", "failure", "interrupted", "not_run", "unknown"]


class EpisodeStep(StrictModel):
    ordinal: NonNegative
    action: SupportedText
    result: SupportedText | None = None
    outcome: Outcome
    causal_assessment: SupportedText | None = None


class Episode(StrictModel):
    episode_id: Id
    project_id: Id
    installation_id: Id
    revision: Revision
    task_id: Id
    title: Annotated[str, Field(min_length=1, max_length=256)]
    started_at: UtcTime
    ended_at: UtcTime | None
    state: Literal["open", "settled", "archived"]
    objective: SupportedText
    preconditions: list[SupportedText] = Field(default_factory=list)
    steps: list[EpisodeStep]
    outcome: SupportedText
    unresolved: list[SupportedText] = Field(default_factory=list)
    source_event_ids: Annotated[list[Id], Field(min_length=1)]
    related_episode_ids: list[Id] = Field(default_factory=list)
    scope: Scope = Field(default_factory=Scope)
    coverage: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def _ordered(self) -> "Episode":
        if [s.ordinal for s in self.steps] != sorted({s.ordinal for s in self.steps}):
            raise ValueError("episode steps are strictly ordered by ordinal")
        return self


class ReviewAssessment(StrictModel):
    review_job_id: Id
    batch_id: Id
    candidate_ref: RecordRef
    proposal_digest: Digest
    evidence_digest: Digest
    prompt_digest: Digest
    verdict: Literal["supported", "revise", "reject"]
    objections: Annotated[list[Annotated[str, bounded_text(OBJECTION_MAX_BYTES), Field(min_length=1)]], Field(max_length=2)]
    evidence_refs: list[EvidenceLink] = Field(default_factory=list)
    reviewed_at: UtcTime

    @model_validator(mode="after")
    def _evidence_rules(self) -> "ReviewAssessment":
        if self.verdict == "supported" and not self.evidence_refs:
            raise ValueError("a supported verdict requires at least one valid evidence reference")
        return self


class ProcedureBody(StrictModel):
    preconditions: list[SupportedText] = Field(default_factory=list)
    steps: Annotated[list[SupportedText], Field(min_length=1)]
    expected_outcomes: list[SupportedText] = Field(default_factory=list)
    stop_conditions: list[SupportedText] = Field(default_factory=list)
    successful_episode_ids: list[Id] = Field(default_factory=list)


class FailureBody(StrictModel):
    action_family_digest: Digest | None
    last_supporting_failure_event_id: Id | None
    observed_failure: SupportedText
    consequence: SupportedText | None = None
    alternative: SupportedText | None = None
    retry_conditions: list[SupportedText] = Field(default_factory=list)


class ImportOrigin(StrictModel):
    source_project_id: Id | None
    source_installation_id: Id | None
    source_record_id: Annotated[str, Field(min_length=1, max_length=256)]
    source_revision: Annotated[str, Field(min_length=1, max_length=64)]
    export_digest: Digest


class ModelProvenance(StrictModel):
    provider_id: Annotated[str, Field(min_length=1, max_length=64)]
    configured_model: Annotated[str, Field(min_length=1, max_length=128)]
    resolved_model: Annotated[str, Field(max_length=128)] | None
    adapter_version: Annotated[str, Field(min_length=1, max_length=64)]
    prompt_id: Annotated[str, Field(min_length=1, max_length=64)]
    prompt_digest: Digest
    job_id: Id


ClaimKind = Literal["fact", "decision", "preference", "failure_lesson", "procedure"]
ClaimStatus = Literal["candidate", "active", "disputed", "superseded", "invalidated", "archived", "quarantined", "forgotten"]
CONTENT_FREE_STATUSES = frozenset({"quarantined", "forgotten"})


class PropositionKey(StrictModel):
    subject: Annotated[str, Field(min_length=1, max_length=256)]
    predicate: Annotated[str, Field(min_length=1, max_length=256)]


class ClaimRevision(StrictModel):
    claim_id: Id
    project_id: Id
    installation_id: Id
    revision: Revision
    kind: ClaimKind
    proposition: Annotated[str, Field(max_length=4096)]
    proposition_key: PropositionKey | None
    scope: Scope = Field(default_factory=Scope)
    conditions: list[Condition] = Field(default_factory=list)
    basis: Basis
    strength: Literal["weak", "supported", "corroborated"]
    status: ClaimStatus
    freshness: Literal["current", "needs_revalidation", "unknown"]
    supports: list[EvidenceLink] = Field(default_factory=list)
    contradicts: list[EvidenceLink] = Field(default_factory=list)
    # Counter-observations (FailureRecheck, decision 0012): context only, never support or contradiction.
    context: list[EvidenceLink] = Field(default_factory=list)
    evidence_availability: Literal["available", "capsule_only", "expired", "redacted"]
    effective_from: UtcTime | None = None
    effective_until: UtcTime | None = None
    recorded_at: UtcTime
    last_supported_at: UtcTime | None = None
    review_due_at: UtcTime | None = None
    dependencies: list[DependencyRef] = Field(default_factory=list)
    review_class: Literal["volatile", "stable"]
    review_assessment: ReviewAssessment | None = None
    supersedes: list[RecordRef] = Field(default_factory=list)
    superseded_by: list[RecordRef] = Field(default_factory=list)
    procedure: ProcedureBody | None = None
    failure: FailureBody | None = None
    origin: ImportOrigin | None = None
    model_provenance: ModelProvenance | None = None

    @model_validator(mode="after")
    def _policy_shape(self) -> "ClaimRevision":
        if self.status in CONTENT_FREE_STATUSES:
            # Forgotten/quarantined heads are content-free markers.
            if self.proposition or self.procedure or self.failure or self.supports or self.contradicts or self.context or self.proposition_key is not None:
                raise ValueError("quarantined/forgotten claim heads carry no content")
        elif not self.proposition:
            raise ValueError("a servable claim needs a proposition")
        if (self.kind == "procedure") != (self.procedure is not None):
            raise ValueError("procedure body exactly for kind procedure")
        if self.kind == "failure_lesson" and self.status not in CONTENT_FREE_STATUSES and self.failure is None:
            raise ValueError("a failure lesson carries its FailureBody")
        if self.kind != "failure_lesson" and self.failure is not None:
            raise ValueError("only failure lessons carry a FailureBody")
        if self.kind == "failure_lesson" and self.review_class != "volatile":
            raise ValueError("failure lessons are always volatile")
        if self.basis == "observed" and self.status not in CONTENT_FREE_STATUSES and not any(link.mapping for link in self.supports):
            raise ValueError("observed basis requires a registered deterministic evidence mapping")
        if any(link.relation != "context" for link in self.context):
            raise ValueError("counter-observations are context links")
        if self.strength == "corroborated" and self.contradicts:
            raise ValueError("corroboration is blocked by an unresolved contradiction")
        if self.status == "active" and self.basis == "inferred" and (self.review_assessment is None or self.review_assessment.verdict != "supported"):
            raise ValueError("an active inferred claim requires its supported review")
        if self.status == "active" and self.basis == "user_declared" and self.kind in ("decision", "preference") and (self.review_assessment is None or self.review_assessment.verdict != "supported"):
            raise ValueError("an active declaration requires its supported review (no bypass)")
        return self


class CapsuleSpan(StrictModel):
    origin_ref: RecordRef
    original_locator: SpanLocator
    text: str
    context_before: Annotated[str, Field(max_length=2048)]
    context_after: Annotated[str, Field(max_length=2048)]
    text_digest: Digest

    @model_validator(mode="after")
    def _exact(self) -> "CapsuleSpan":
        digest = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if digest != self.text_digest or digest != self.original_locator.text_digest:
            raise ValueError("capsule text must hash to both its digest and the original locator digest")
        if self.original_locator.end - self.original_locator.start != len(self.text):
            raise ValueError("capsule text length must equal the original locator span")
        return self


class EvidenceCapsule(StrictModel):
    capsule_id: Id
    source_ref: SourceRef
    origin_event_key: OriginEventKey
    root_event_ids: list[Id]
    preserved_observation: JsonObject
    spans: list[CapsuleSpan]
    captured_at: UtcTime
    scope: Scope = Field(default_factory=Scope)
    redacted: bool
    content_digest: Digest


EquivalenceReason = Literal["origin_identity", "provenance", "artifact_snapshot", "experiment_signature", "same_authority", "unknown_dependencies"]


class RootClass(StrictModel):
    root_class_id: Id
    canonical_origin: OriginEventKey
    member_origin_keys: Annotated[list[OriginEventKey], Field(min_length=1)]
    equivalence_reasons: list[EquivalenceReason] = Field(default_factory=list)

    @model_validator(mode="after")
    def _canonical(self) -> "RootClass":
        if not self.root_class_id.startswith("root_"):
            raise ValueError("root class ids use the root_ prefix")
        if self.canonical_origin not in self.member_origin_keys:
            raise ValueError("the canonical origin is a member of its class")
        least = min(self.member_origin_keys, key=lambda k: (k.source_namespace, k.source_event_key))
        if least != self.canonical_origin:
            raise ValueError("the canonical origin is the lexicographically least member")
        return self


class ReviewEvidence(StrictModel):
    evidence_id: Id
    link: EvidenceLink


class ReviewBatch(StrictModel):
    batch_id: Id
    origin_job_id: Id | None
    review_job_id: Id
    candidate_refs: Annotated[list[RecordRef], Field(min_length=1, max_length=REVIEW_BATCH_MAX_CANDIDATES)]
    candidate_digests: dict[Id, Digest]
    evidence_digest: Digest
    prompt_digest: Digest
    evidence_index: list[ReviewEvidence] = Field(default_factory=list)
    read_set: ReadSet

    @model_validator(mode="after")
    def _consistent(self) -> "ReviewBatch":
        if not self.batch_id.startswith("batch_"):
            raise ValueError("review batch ids use the batch_ prefix")
        ids = [r.id for r in self.candidate_refs]
        if len(set(ids)) != len(ids) or set(ids) != set(self.candidate_digests):
            raise ValueError("candidate digests must cover exactly the distinct candidates")
        if any(r.kind != "claim" for r in self.candidate_refs):
            raise ValueError("review candidates are claim revisions")
        evidence_ids = [e.evidence_id for e in self.evidence_index]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("batch evidence ids are unique")
        return self
