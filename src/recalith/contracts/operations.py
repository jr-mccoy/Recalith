"""Provider requests, proposed operations and admission results (DATA_CONTRACTS §7).

The model returns only a :class:`ModelProposalBody`. Usage, provider and model
metadata are appended by adapter code into :class:`ModelResponse`; the model
cannot vouch for them. Every operation kind has an enumerated payload model,
so authority, identity, strength, status and installation fields cannot be
smuggled in by a provider.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import (
    Condition,
    DependencyRef,
    EvidenceLink,
    Id,
    JsonObject,
    NonNegative,
    One,
    PortablePath,
    ReadSet,
    RecordRef,
    Revision,
    Scope,
    StrictModel,
    UtcTime,
    bounded_text,
    canonical_json,
)
from .config import (
    ASSESSMENT_OP_MAX_BYTES,
    MODEL_INPUT_CAP,
    OBJECTION_MAX_BYTES,
    ModelPurpose,
)
from .events import EventEnvelope
from .memory import (
    Basis,
    ClaimKind,
    ClaimRevision,
    Episode,
    EpisodeStep,
    FailureBody,
    ProcedureBody,
    PropositionKey,
    ReviewBatch,
    SupportedText,
    TaskBindingProposal,
    TaskState,
)

OperationKind = Literal[
    "update_task",
    "resolve_task_binding",
    "create_episode",
    "revise_episode",
    "propose_claim",
    "assess_claim",
    "attach_evidence",
    "revise_claim",
    "change_claim_status",
    "request_evidence",
    "no_op",
]
LocalRef = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_\-]{0,63}$")]


# --------------------------------------------------------------------------
# Per-kind payloads

TaskField = Literal["title", "objective", "constraints", "plan", "pending_actions", "known_results", "blockers", "open_questions", "next_action", "completion_basis"]
LIST_TASK_FIELDS = frozenset({"constraints", "plan", "pending_actions", "known_results", "blockers", "open_questions"})


class TaskPatch(StrictModel):
    """Explicit patch; absence from a chunk never clears a field."""

    op: Literal["set", "append", "close", "status"]
    field: TaskField | None = None
    value: JsonObject | Annotated[str, Field(max_length=256)] | None = None
    item_id: Id | None = None
    status: Literal["active", "paused", "completed", "abandoned"] | None = None

    @model_validator(mode="after")
    def _shape(self) -> "TaskPatch":
        if self.op == "status":
            if self.status is None or self.field is not None or self.value is not None:
                raise ValueError("a status patch names only the new status (linking is code-owned)")
        elif self.field is None or self.status is not None:
            raise ValueError("field patches name a field and no status")
        elif self.op == "append" and (self.field not in LIST_TASK_FIELDS or not isinstance(self.value, dict)):
            raise ValueError("append adds one item to a list field")
        elif self.op == "close" and (self.field not in LIST_TASK_FIELDS or self.item_id is None or self.value is not None):
            raise ValueError("close removes one list item by id")
        elif self.op == "set" and self.value is None:
            raise ValueError("set requires a value")
        return self


class UpdateTaskPayload(StrictModel):
    task_id: Id
    expected_revision: Revision
    patches: Annotated[list[TaskPatch], Field(min_length=1, max_length=64)]


class CreateEpisodePayload(StrictModel):
    task_id: Id
    title: Annotated[str, Field(min_length=1, max_length=256)]
    started_at: UtcTime
    ended_at: UtcTime | None = None
    objective: SupportedText
    preconditions: list[SupportedText] = Field(default_factory=list)
    steps: list[EpisodeStep]
    outcome: SupportedText
    unresolved: list[SupportedText] = Field(default_factory=list)
    source_event_ids: Annotated[list[Id], Field(min_length=1)]
    related_episode_ids: list[Id] = Field(default_factory=list)
    scope: Scope = Field(default_factory=Scope)


class EpisodePatch(StrictModel):
    op: Literal["set", "append"]
    field: Literal["title", "objective", "preconditions", "steps", "outcome", "unresolved", "related_episode_ids", "ended_at"]
    value: JsonObject | Annotated[str, Field(max_length=256)]


class ReviseEpisodePayload(StrictModel):
    episode_id: Id
    expected_revision: Revision
    patches: Annotated[list[EpisodePatch], Field(min_length=1, max_length=64)]


class ProposeClaimPayload(StrictModel):
    """Claim body only; ids, strength, status, authority and times are code-assigned."""

    kind: ClaimKind
    proposition: Annotated[str, Field(min_length=1, max_length=4096)]
    proposition_key: PropositionKey
    scope: Scope = Field(default_factory=Scope)
    conditions: list[Condition] = Field(default_factory=list)
    basis: Basis
    dependencies: list[DependencyRef] = Field(default_factory=list)
    effective_from: UtcTime | None = None
    effective_until: UtcTime | None = None
    procedure: ProcedureBody | None = None
    failure: FailureBody | None = None

    @model_validator(mode="after")
    def _bodies(self) -> "ProposeClaimPayload":
        if (self.kind == "procedure") != (self.procedure is not None):
            raise ValueError("procedure body exactly for kind procedure")
        if (self.kind == "failure_lesson") != (self.failure is not None):
            raise ValueError("failure body exactly for kind failure_lesson")
        return self


class AssessClaimPayload(StrictModel):
    batch_id: Id
    candidate_ref: RecordRef
    verdict: Literal["supported", "revise", "reject"]
    objections: Annotated[list[Annotated[str, bounded_text(OBJECTION_MAX_BYTES), Field(min_length=1)]], Field(max_length=2)]
    evidence_ids: Annotated[list[Id], Field(max_length=2)]

    @model_validator(mode="after")
    def _evidence(self) -> "AssessClaimPayload":
        if self.verdict == "supported" and not self.evidence_ids:
            raise ValueError("supported verdicts cite at least one batch evidence id")
        if self.candidate_ref.kind != "claim":
            raise ValueError("assessments target claim candidates")
        return self


class AttachEvidencePayload(StrictModel):
    claim_ref: RecordRef
    relation: Literal["supports", "contradicts", "context"]


class ReviseClaimPayload(StrictModel):
    claim_ref: RecordRef
    proposition: Annotated[str, Field(min_length=1, max_length=4096)] | None = None
    proposition_key: PropositionKey | None = None
    scope: Scope | None = None
    conditions: list[Condition] | None = None
    dependencies: list[DependencyRef] | None = None

    @model_validator(mode="after")
    def _changes(self) -> "ReviseClaimPayload":
        if all(getattr(self, f) is None for f in ("proposition", "proposition_key", "scope", "conditions", "dependencies")):
            raise ValueError("a revision changes at least one field")
        return self


class ChangeClaimStatusPayload(StrictModel):
    claim_ref: RecordRef
    status: Literal["disputed", "superseded", "invalidated", "archived"]
    replacement_local_ref: LocalRef | None = None
    replacement_ref: RecordRef | None = None

    @model_validator(mode="after")
    def _replacement(self) -> "ChangeClaimStatusPayload":
        has = (self.replacement_local_ref is not None) + (self.replacement_ref is not None)
        if self.status == "superseded" and has != 1:
            raise ValueError("supersession names exactly one replacement")
        if self.status != "superseded" and has:
            raise ValueError("only supersession names a replacement")
        return self


class RequestEvidencePayload(StrictModel):
    request_kind: Literal["file_excerpt", "record", "dependency_diff", "event_range"]
    ref: RecordRef | None = None
    path: PortablePath | None = None
    start: NonNegative | None = None
    end: NonNegative | None = None

    @model_validator(mode="after")
    def _target(self) -> "RequestEvidencePayload":
        if self.request_kind in ("record", "event_range") and self.ref is None:
            raise ValueError("record/event_range requests name an allowed ref")
        if self.request_kind in ("file_excerpt", "dependency_diff") and self.path is None:
            raise ValueError("file/dependency requests name an allowed path")
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("range end precedes start")
        return self


class NoOpPayload(StrictModel):
    pass


PAYLOAD_MODELS: dict[str, type[StrictModel]] = {
    "update_task": UpdateTaskPayload,
    "resolve_task_binding": TaskBindingProposal,
    "create_episode": CreateEpisodePayload,
    "revise_episode": ReviseEpisodePayload,
    "propose_claim": ProposeClaimPayload,
    "assess_claim": AssessClaimPayload,
    "attach_evidence": AttachEvidencePayload,
    "revise_claim": ReviseClaimPayload,
    "change_claim_status": ChangeClaimStatusPayload,
    "request_evidence": RequestEvidencePayload,
    "no_op": NoOpPayload,
}

# Which operation kinds each model purpose may return (provider schema).
PURPOSE_KINDS: dict[str, frozenset[str]] = {
    "update_task": frozenset({"update_task", "resolve_task_binding", "request_evidence", "no_op"}),
    "build_episode": frozenset({"create_episode", "revise_episode", "request_evidence", "no_op"}),
    "extract_claims": frozenset({"propose_claim", "attach_evidence", "revise_claim", "change_claim_status", "update_task", "resolve_task_binding", "request_evidence", "no_op"}),
    "review_claims": frozenset({"assess_claim", "request_evidence"}),
    "revalidate": frozenset({"revise_claim", "change_claim_status", "attach_evidence", "request_evidence", "no_op"}),
}


class ProposedOperation(StrictModel):
    local_ref: LocalRef
    kind: OperationKind
    depends_on: list[LocalRef] = Field(default_factory=list)
    target: RecordRef | None = None
    payload: JsonObject
    evidence: list[EvidenceLink] = Field(default_factory=list)
    reason: Annotated[str, Field(max_length=1024)]

    @model_validator(mode="after")
    def _payload(self) -> "ProposedOperation":
        typed = PAYLOAD_MODELS[self.kind].model_validate(self.payload)
        if self.kind == "assess_claim":
            assert isinstance(typed, AssessClaimPayload)
            if self.reason or self.evidence or self.depends_on:
                raise ValueError("assess_claim carries empty reason, evidence and depends_on")
            if self.target != typed.candidate_ref:
                raise ValueError("assess_claim target equals its candidate_ref")
            if len(canonical_json(self.model_dump(mode="json"))) > ASSESSMENT_OP_MAX_BYTES:
                raise ValueError("a serialized assessment operation is at most 768 bytes")
        if self.local_ref in self.depends_on:
            raise ValueError("an operation cannot depend on itself")
        return self

    def typed_payload(self) -> StrictModel:
        return PAYLOAD_MODELS[self.kind].model_validate(self.payload)


class ModelProposalBody(StrictModel):
    """Exactly what a model may return. No usage, actor or provider metadata."""

    operations: Annotated[list[ProposedOperation], Field(max_length=256)]
    no_op_reason: Annotated[str, Field(max_length=1024)] | None = None

    @model_validator(mode="after")
    def _graph(self) -> "ModelProposalBody":
        refs = [op.local_ref for op in self.operations]
        if len(set(refs)) != len(refs):
            raise ValueError("local refs are unique within a proposal")
        known = set(refs)
        deps = {op.local_ref: set(op.depends_on) for op in self.operations}
        for op in self.operations:
            if not set(op.depends_on) <= known:
                raise ValueError("depends_on references an unknown local ref")
        _check_acyclic(deps)
        if not self.operations and not self.no_op_reason:
            raise ValueError("an empty proposal explains itself with no_op_reason")
        return self

    def validate_for_purpose(self, purpose: ModelPurpose) -> None:
        allowed = PURPOSE_KINDS[purpose]
        bad = sorted({op.kind for op in self.operations} - allowed)
        if bad:
            raise ValueError(f"operation kinds {bad} are not permitted for purpose {purpose}")
        if purpose == "review_claims":
            kinds = {op.kind for op in self.operations}
            if len(kinds) > 1:
                raise ValueError("a review response is either terminal assessments or evidence requests, not both")


def _check_acyclic(deps: dict[str, set[str]]) -> None:
    state: dict[str, int] = {}

    def visit(node: str) -> None:
        if state.get(node) == 1:
            raise ValueError("operation dependencies form a cycle")
        if state.get(node) == 2:
            return
        state[node] = 1
        for nxt in deps.get(node, ()):
            visit(nxt)
        state[node] = 2

    for node in deps:
        visit(node)


class UsageReport(StrictModel):
    input_tokens: NonNegative | None
    output_tokens: NonNegative | None
    estimated_input_tokens: NonNegative
    estimated_output_tokens: NonNegative
    provider_request_id: Annotated[str, Field(max_length=256)] | None
    duration_ms: NonNegative


class ResponseProvenance(StrictModel):
    """Appended by adapter code after the call; never parsed from model text."""

    provider_id: Annotated[str, Field(min_length=1, max_length=64)]
    configured_model: Annotated[str, Field(min_length=1, max_length=128)]
    resolved_model: Annotated[str, Field(max_length=128)] | None
    adapter_version: Annotated[str, Field(min_length=1, max_length=64)]


class ModelResponse(StrictModel):
    response_schema: One
    operations: list[ProposedOperation]
    no_op_reason: Annotated[str, Field(max_length=1024)] | None
    usage: UsageReport
    provenance: ResponseProvenance | None = None

    @classmethod
    def from_body(cls, body: ModelProposalBody, usage: UsageReport, provenance: ResponseProvenance | None) -> "ModelResponse":
        return cls(response_schema=1, operations=list(body.operations), no_op_reason=body.no_op_reason, usage=usage, provenance=provenance)


class RequestLimits(StrictModel):
    max_input_bytes: Annotated[int, Field(gt=0, le=MODEL_INPUT_CAP)]
    reserved_output_estimate: Annotated[int, Field(gt=0)]
    max_body_bytes: Annotated[int, Field(gt=0)]
    max_wire_stdout_bytes: Annotated[int, Field(gt=0)]
    max_stderr_bytes: Annotated[int, Field(gt=0)]
    timeout_seconds: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def _body_cap(self) -> "RequestLimits":
        if self.max_body_bytes != 3 * self.reserved_output_estimate:
            raise ValueError("the decoded body cap is 3 × the reserved output estimate")
        return self


class ModelRequest(StrictModel):
    request_schema: One
    job_id: Id
    purpose: ModelPurpose
    prompt_version: Annotated[str, Field(min_length=1, max_length=64)]
    instruction_text: Annotated[str, Field(min_length=1)]
    events: list[EventEnvelope] = Field(default_factory=list)
    episodes: list[Episode] = Field(default_factory=list)
    claims: list[ClaimRevision] = Field(default_factory=list)
    task_state: TaskState | None = None
    allowed_evidence_refs: list[RecordRef] = Field(default_factory=list)
    read_set: ReadSet
    output_schema: JsonObject
    review_batch: ReviewBatch | None = None
    limits: RequestLimits

    @model_validator(mode="after")
    def _bounded(self) -> "ModelRequest":
        if (self.purpose == "review_claims") != (self.review_batch is not None):
            raise ValueError("exactly review requests carry a persisted ReviewBatch")
        if len(canonical_json(self.model_dump(mode="json"))) > self.limits.max_input_bytes:
            raise ValueError("serialized model input exceeds its cap")
        return self


class AdmissionDecision(StrictModel):
    local_ref: LocalRef
    outcome: Literal["apply", "review_required", "candidate_only", "reject", "requeue"]
    reason_code: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    resolved_operation_id: Id | None


class ApplyResult(StrictModel):
    operation_ids: list[Id]
    changed_refs: list[RecordRef]
    decisions: list[AdmissionDecision]
    store_revision: NonNegative
    requeued_job_ids: list[Id] = Field(default_factory=list)


def parse_model_body(raw: bytes, *, purpose: ModelPurpose, body_cap: int) -> ModelProposalBody:
    """Validate a decoded model body: byte cap first, then strict DTO, then purpose."""
    if len(raw) > body_cap:
        raise ValueError("decoded model body exceeds its purpose cap; it is never clipped")
    body = ModelProposalBody.model_validate_json(raw)
    body.validate_for_purpose(purpose)
    return body

