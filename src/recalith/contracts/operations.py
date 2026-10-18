"""Provider requests, proposed operations and admission results (DATA_CONTRACTS §7).

The model returns only a :class:`ModelProposalBody`. Usage, provider and model
metadata are appended by adapter code into :class:`ModelResponse`; the model
cannot vouch for them. Every operation kind has an enumerated payload model,
so authority, identity, strength, status and installation fields cannot be
smuggled in by a provider.
"""

from __future__ import annotations

import json
import re
from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_validator

from .common import (
    Condition,
    DependencyRef,
    Digest,
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
    TaskBoundaryCandidate,
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
    # Controller-only (decision 0008): typed reduction opens tasks, assigns
    # events and records boundary candidates. No model purpose may return them.
    "create_task",
    "bind_events",
    "record_boundary",
]
REDUCTION_KINDS = frozenset({"create_task", "bind_events", "record_boundary"})
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


class CreateTaskPayload(StrictModel):
    """Controller-only: a provisional task for a new session, a reset or a host binding.

    Code allocates ``task_id`` (no model purpose may return this kind). The
    task starts active; its objective is unknown unless typed evidence names it.
    """

    task_id: Id
    title: Annotated[str, Field(min_length=1, max_length=256)]
    reason: Literal["new_session", "host_reset"]
    session_ids: Annotated[list[Id], Field(min_length=1, max_length=64)]
    started_at: UtcTime


class BindEventsPayload(StrictModel):
    """Controller-only: first (provisional) binding of unbound events plus their typed facts.

    Each patch is a typed field patch citing its supporting events; the task's
    code-owned fields (``session_ids``, ``last_activity_at``, reactivation of
    a paused task) follow from the bound events themselves.
    """

    task_id: Id
    expected_revision: Revision
    event_ids: Annotated[list[Id], Field(min_length=1, max_length=256)]
    boundary_id: Id | None = None
    patches: Annotated[list[TaskPatch], Field(max_length=256)] = Field(default_factory=list)

    @model_validator(mode="after")
    def _distinct(self) -> "BindEventsPayload":
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("an event is bound once per operation")
        return self


class RecordBoundaryPayload(StrictModel):
    """Controller-only: persist one deterministic boundary candidate (pending)."""

    candidate: TaskBoundaryCandidate

    @model_validator(mode="after")
    def _pending(self) -> "RecordBoundaryPayload":
        if self.candidate.state != "pending":
            raise ValueError("a recorded candidate starts pending; resolve_task_binding decides it")
        return self


class CreateEpisodePayload(StrictModel):
    task_id: Id
    title: Annotated[str, Field(min_length=1, max_length=256)]
    state: Literal["open", "settled"] = "open"
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
    field: Literal["title", "objective", "preconditions", "steps", "outcome", "unresolved", "related_episode_ids", "ended_at", "state"]
    value: JsonObject | Annotated[str, Field(max_length=256)]

    @model_validator(mode="after")
    def _state(self) -> "EpisodePatch":
        if self.field == "state" and (self.op != "set" or self.value not in ("open", "settled")):
            raise ValueError("an episode patch may set state to open or settled; archiving is code-owned")
        return self


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
    # A failure lesson retained with an explicit retry condition (SYSTEM_SPEC §7.3, decision 0012).
    retry_conditions: Annotated[list[SupportedText], Field(max_length=8)] | None = None

    @model_validator(mode="after")
    def _changes(self) -> "ReviseClaimPayload":
        if all(getattr(self, f) is None for f in ("proposition", "proposition_key", "scope", "conditions", "dependencies", "retry_conditions")):
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
    "create_task": CreateTaskPayload,
    "bind_events": BindEventsPayload,
    "record_boundary": RecordBoundaryPayload,
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


ReasonCode = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class MalformedOperation(StrictModel):
    """Adapter-recorded: one proposed operation that failed strict validation.

    It fails exactly its atomic dependency group (DATA_CONTRACTS §7.1); its
    raw text is not retained. ``local_ref``/``depends_on`` are kept only when
    they were themselves valid, so dependents can be grouped with it.
    """

    index: NonNegative
    local_ref: LocalRef | None
    depends_on: list[LocalRef] = Field(default_factory=list)
    reason_code: ReasonCode


class ModelResponse(StrictModel):
    response_schema: One
    operations: list[ProposedOperation]
    no_op_reason: Annotated[str, Field(max_length=1024)] | None
    usage: UsageReport
    provenance: ResponseProvenance | None = None
    malformed: list[MalformedOperation] = Field(default_factory=list)

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


class BoundaryContext(StrictModel):
    """A pending boundary candidate as narrative input, with the binding revisions its events have now.

    ``binding_revisions`` is what a ``resolve_task_binding`` proposal must
    name as ``expected_binding_revisions``; a moved binding re-evaluates it.
    """

    candidate: TaskBoundaryCandidate
    binding_revisions: dict[Id, Revision] = Field(default_factory=dict)


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
    boundaries: list[BoundaryContext] = Field(default_factory=list)
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
    reason_code: ReasonCode
    resolved_operation_id: Id | None


class ApplyResult(StrictModel):
    operation_ids: list[Id]
    changed_refs: list[RecordRef]
    decisions: list[AdmissionDecision]
    store_revision: NonNegative
    requeued_job_ids: list[Id] = Field(default_factory=list)


class UndoChange(StrictModel):
    """One compensating change an undo would append (decision 0007)."""

    action: Literal["restore_fields", "retire", "remove_relation"]
    ref: RecordRef | None
    fields: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(default_factory=list)
    relation: Annotated[list[Annotated[str, Field(min_length=1, max_length=128)]], Field(min_length=3, max_length=3)] | None = None

    @model_validator(mode="after")
    def _shape(self) -> "UndoChange":
        if (self.action == "remove_relation") != (self.relation is not None and self.ref is None):
            raise ValueError("relation removals name a relation; record changes name a ref")
        return self


class UndoConflict(StrictModel):
    """A later revision changed what the undone operation changed; undo leaves it alone."""

    ref: RecordRef
    undone_revision: Revision
    current_revision: NonNegative
    fields: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(default_factory=list)
    reason: ReasonCode


class UndoPreview(StrictModel):
    """``recalith undo OPERATION_ID --preview``: the compensation and its conflicts.

    ``--apply`` requires this exact ``preview_digest``; any intervening change
    alters the digest, so nothing is applied that was not previewed.
    """

    operation_id: Id
    state: Literal["clean", "partial", "conflicted", "nothing_to_undo"]
    compensations: list[UndoChange]
    conflicts: list[UndoConflict]
    preview_digest: Digest


def parse_model_body(raw: bytes, *, purpose: ModelPurpose, body_cap: int) -> ModelProposalBody:
    """Validate a decoded model body: byte cap first, then strict DTO, then purpose."""
    if len(raw) > body_cap:
        raise ValueError("decoded model body exceeds its purpose cap; it is never clipped")
    body = ModelProposalBody.model_validate_json(raw)
    body.validate_for_purpose(purpose)
    return body



_LOCAL_REF = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")


def _reject_constant(name: str) -> None:
    raise ValueError(f"non-finite JSON number {name}")


def parse_model_body_partitioned(raw: bytes, *, purpose: ModelPurpose, body_cap: int) -> tuple[list[ProposedOperation], str | None, list[MalformedOperation]]:
    """Validate a decoded body per operation (DATA_CONTRACTS §7.1).

    The byte cap and the enclosing object are strict: oversize, invalid JSON,
    unknown top-level keys or a mixed review response reject the whole body.
    Each operation is then validated strictly on its own; one that fails (or
    whose kind the purpose does not permit) is recorded as a
    :class:`MalformedOperation` and fails only its dependency group.
    """
    if len(raw) > body_cap:
        raise ValueError("decoded model body exceeds its purpose cap; it is never clipped")
    data = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    if not isinstance(data, dict) or not set(data) <= {"operations", "no_op_reason"} or "operations" not in data:
        raise ValueError("a model body is an object with operations and an optional no_op_reason")
    items, reason = data["operations"], data.get("no_op_reason")
    if not isinstance(items, list) or len(items) > 256:
        raise ValueError("operations is a list of at most 256 entries")
    if reason is not None and (not isinstance(reason, str) or len(reason) > 1024):
        raise ValueError("no_op_reason is a bounded string")
    if not items and not reason:
        raise ValueError("an empty proposal explains itself with no_op_reason")
    valid: list[ProposedOperation] = []
    malformed: list[MalformedOperation] = []
    allowed = PURPOSE_KINDS[purpose]

    def _ref(item: object) -> str | None:
        value = item.get("local_ref") if isinstance(item, dict) else None
        return value if isinstance(value, str) and _LOCAL_REF.match(value) else None

    def _deps(item: object) -> list[str]:
        value = item.get("depends_on") if isinstance(item, dict) else None
        return [d for d in value if isinstance(d, str) and _LOCAL_REF.match(d)] if isinstance(value, list) else []

    for index, item in enumerate(items):
        try:
            op = ProposedOperation.model_validate_json(json.dumps(item))
        except (ValidationError, ValueError):
            malformed.append(MalformedOperation(index=index, local_ref=_ref(item), depends_on=_deps(item), reason_code="malformed_operation"))
            continue
        if op.kind not in allowed:
            malformed.append(MalformedOperation(index=index, local_ref=op.local_ref, depends_on=list(op.depends_on), reason_code="kind_not_permitted"))
            continue
        valid.append(op)
    if purpose == "review_claims" and len({op.kind for op in valid}) > 1:
        raise ValueError("a review response is either terminal assessments or evidence requests, not both")
    return valid, reason, malformed
