"""Jobs, budgets and deterministic triggers (DATA_CONTRACTS §8)."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import Digest, Id, NonNegative, RecordRef, Revision, StrictModel, UtcTime
from .config import PROTECTED_PURPOSES, PURPOSE_OUTPUT_ALLOWANCE, REASONING_HEADROOM, STDERR_CAP, WIRE_STDOUT_CAP, ModelPurpose, body_cap_for
from .operations import UsageReport

JobKind = Literal["ingest", "update_task", "build_episode", "extract_claims", "review_claims", "revalidate", "compile_context", "maintenance", "export"]
MODEL_JOB_KINDS = frozenset(PURPOSE_OUTPUT_ALLOWANCE)
JobState = Literal["pending", "leased", "waiting_review", "waiting_budget", "completed", "failed", "cancelled"]


class Job(StrictModel):
    job_id: Id
    kind: JobKind
    state: JobState
    input_refs: list[RecordRef] = Field(default_factory=list)
    input_digest: Digest
    policy_revision: Revision
    prompt_version: Annotated[str, Field(max_length=64)] | None
    idempotency_key: Digest
    priority: int
    due_at: UtcTime
    attempt: NonNegative
    lease_owner: Annotated[str, Field(max_length=128)] | None = None
    lease_generation: NonNegative = 0
    lease_until: UtcTime | None = None
    proposal_ref: Id | None = None
    last_error_code: Annotated[str, Field(max_length=64)] | None = None
    budget_pool: Literal["ordinary", "protected", "none"]
    review_priority: Literal["correction_or_declaration", "ordinary"] | None = None
    trigger_ref: Id | None = None

    @model_validator(mode="after")
    def _rules(self) -> "Job":
        if self.state == "leased" and (self.lease_owner is None or self.lease_until is None):
            raise ValueError("a leased job names its owner and lease expiry")
        if self.kind not in MODEL_JOB_KINDS and self.budget_pool != "none":
            raise ValueError("deterministic jobs use no model budget")
        if self.kind in MODEL_JOB_KINDS:
            expected = "protected" if self.kind in PROTECTED_PURPOSES else "ordinary"
            if self.budget_pool != expected:
                raise ValueError(f"{self.kind} draws from the {expected} pool first")
            if self.prompt_version is None:
                raise ValueError("model jobs pin a prompt version")
        if (self.kind == "review_claims") != (self.review_priority is not None):
            raise ValueError("exactly review jobs carry a code-assigned review priority")
        return self


class FailureTrigger(StrictModel):
    trigger_id: Id
    task_id: Id
    failure_event_id: Id
    action_family_digest: Digest | None
    subsequent_event_count: NonNegative
    due_at: UtcTime
    state: Literal["pending", "resolved", "due"]


class FailureRecheck(StrictModel):
    claim_ref: RecordRef
    success_event_id: Id
    supporting_failure_event_id: Id | None
    reason: Literal["later_success", "order_unknown"]
    action_family_digest: Digest

    @model_validator(mode="after")
    def _chronology(self) -> "FailureRecheck":
        if self.supporting_failure_event_id is None and self.reason != "order_unknown":
            raise ValueError("without the supporting failure only an order_unknown trigger is possible")
        return self


class PoolAllocation(StrictModel):
    invocations: Annotated[int, Field(ge=0, le=1)]
    input_estimate: NonNegative
    output_estimate: NonNegative


class LocalUsage(StrictModel):
    input_estimate: NonNegative
    output_estimate: NonNegative


UTC_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class BudgetReservation(StrictModel):
    reservation_id: Id
    job_id: Id
    invocation_id: Id
    utc_day: Annotated[str, Field(pattern=UTC_DAY.pattern)]
    purpose: ModelPurpose
    ordinary: PoolAllocation
    protected: PoolAllocation
    estimated_input_limit: Annotated[int, Field(gt=0)]
    estimated_output_limit: Annotated[int, Field(gt=0)]
    reasoning_headroom: NonNegative = 0  # 0 on a reservation made before decision 0029
    max_wire_stdout_bytes: Literal[262144] = WIRE_STDOUT_CAP  # type: ignore[assignment]
    max_response_body_bytes: Annotated[int, Field(gt=0)]
    max_stderr_bytes: Literal[65536] = STDERR_CAP  # type: ignore[assignment]
    reported_usage: UsageReport | None = None
    local_estimated_usage: LocalUsage | None = None
    state: Literal["reserved", "charged", "released"]

    @model_validator(mode="after")
    def _arithmetic(self) -> "BudgetReservation":
        if self.ordinary.invocations + self.protected.invocations != 1:
            raise ValueError("a reservation covers exactly one invocation")
        if self.ordinary.input_estimate + self.protected.input_estimate != self.estimated_input_limit:
            raise ValueError("pool input allocations sum to the input limit")
        if self.ordinary.output_estimate + self.protected.output_estimate != self.estimated_output_limit:
            raise ValueError("pool output allocations sum to the output limit")
        if self.purpose not in PROTECTED_PURPOSES and (self.protected.invocations or self.protected.input_estimate or self.protected.output_estimate):
            raise ValueError("ordinary jobs cannot consume protected reserves")
        if self.reasoning_headroom not in (0, REASONING_HEADROOM):
            raise ValueError("reasoning headroom is the fixed headroom, or 0 before decision 0029")
        if self.estimated_output_limit != PURPOSE_OUTPUT_ALLOWANCE[self.purpose] + self.reasoning_headroom:
            raise ValueError("output limit is the purpose's allowance plus the reasoning headroom")
        if self.max_response_body_bytes != body_cap_for(self.purpose):
            raise ValueError("max_response_body_bytes is 3 × the purpose's output allowance")
        return self


class IngestResult(StrictModel):
    accepted: NonNegative
    duplicate: NonNegative
    conflict: NonNegative
    last_store_revision: NonNegative
    created_job_ids: list[Id] = Field(default_factory=list)


class DependencyChange(StrictModel):
    kind: Literal["file", "config", "environment", "claim"]
    key: Annotated[str, Field(min_length=1, max_length=512)]
    old_fingerprint: Digest | None
    new_fingerprint: Digest | None
    supporting_event_id: Id
