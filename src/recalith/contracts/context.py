"""Context queries, packets, delivery accounting and session scratch (DATA_CONTRACTS §2.3, §9)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import (
    REASON_CODES,
    Applicability,
    Digest,
    EnvironmentValues,
    Id,
    JsonObject,
    NonNegative,
    One,
    OriginEventKey,
    RecordRef,
    Revision,
    Scope,
    SourceRef,
    SpanLocator,
    StrictModel,
    UtcTime,
    canonical_json,
)
from .config import (
    SESSION_SCRATCH_CAP,
    SESSION_SCRATCH_ENTRIES,
    SESSION_SCRATCH_OUTCOMES,
)
from .events import ActionDescriptor, Outcome

Purpose = Literal["session_start", "prompt", "pre_action", "compact_restore", "manual"]
MAX_SUBSTITUTION = 400


class ContextQuery(StrictModel):
    session_id: Id
    task_id: Id | None
    workspace_id: Id
    purpose: Purpose
    text: Annotated[str, Field(max_length=16384)]
    action: ActionDescriptor | None = None
    environment: EnvironmentValues = Field(default_factory=dict)
    max_estimated_tokens: Annotated[int, Field(gt=0)] | None = None


class ContextItem(StrictModel):
    ref: RecordRef
    text: Annotated[str, Field(min_length=1, max_length=8192)]
    advice: Literal["context", "caution", "conflict"]
    basis: Literal["observed", "user_declared", "inferred"]
    scope: Scope = Field(default_factory=Scope)
    applicability: Applicability
    freshness: Literal["current", "needs_revalidation", "unknown"]
    why: Annotated[list[Annotated[str, Field(min_length=1, max_length=512)]], Field(min_length=1, max_length=8)]
    evidence_refs: list[RecordRef] = Field(default_factory=list)
    conditions_text: Annotated[str, Field(max_length=1024)] | None = None
    retry_text: Annotated[str, Field(max_length=1024)] | None = None

    @model_validator(mode="after")
    def _advice_gates(self) -> "ContextItem":
        if self.why[0] not in REASON_CODES:
            raise ValueError("why[0] must be a registered ReasonCode")
        if self.advice == "caution":
            # Unknown applicability or stale freshness never supplies a caution.
            if self.applicability != "true" or self.freshness != "current":
                raise ValueError("caution requires applicability 'true' and current freshness")
        if self.applicability == "false":
            raise ValueError("inapplicable items are excluded, never delivered")
        return self


class ContextPacket(StrictModel):
    packet_schema: One
    project_id: Id
    installation_id: Id
    store_revision: NonNegative
    guidance_epoch: NonNegative
    policy_revision: Revision
    tombstone_epoch: NonNegative
    generated_at: UtcTime
    purpose: Purpose
    items: list[ContextItem]
    omitted_count: NonNegative
    estimated_tokens: NonNegative
    pre_action_substitution_tokens: Annotated[int, Field(ge=0, le=MAX_SUBSTITUTION)]
    degraded_reasons: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _substitution(self) -> "ContextPacket":
        if self.pre_action_substitution_tokens:
            if self.purpose != "prompt":
                raise ValueError("only an ordinary prompt packet takes the pre-action substitution allowance")
            if not any(i.advice == "caution" for i in self.items):
                raise ValueError("no substitution allowance without an eligible caution")
        if self.pre_action_substitution_tokens > self.estimated_tokens:
            raise ValueError("substitution is part of, not added to, the packet estimate")
        return self


class EmittedItem(StrictModel):
    record_id: Id
    revision: Revision
    condition_digest: Digest


class DeliveryReceipt(StrictModel):
    delivery_id: Id
    attempt_id: Id
    host_id: Annotated[str, Field(min_length=1, max_length=64)]
    session_id: Id
    task_id: Id | None
    packet_digest: Digest
    items: list[EmittedItem]
    purpose: Purpose
    fence_store_revision: NonNegative
    guidance_epoch: NonNegative
    policy_revision: Revision
    tombstone_epoch: NonNegative
    generated_at: UtcTime
    emitted_at: UtcTime | None
    estimated_tokens: NonNegative
    pre_action_substitution_tokens: Annotated[int, Field(ge=0, le=MAX_SUBSTITUTION)]
    state: Literal["emitted", "uncertain"]

    @model_validator(mode="after")
    def _emission(self) -> "DeliveryReceipt":
        if (self.state == "emitted") != (self.emitted_at is not None):
            raise ValueError("only emitted receipts carry an emission time")
        return self


class OutcomeLink(StrictModel):
    delivery_id: Id
    observed_event_ids: list[Id]
    label: Literal["unknown", "acknowledged", "challenged", "action_changed", "task_succeeded", "task_failed"]

    @model_validator(mode="after")
    def _observed(self) -> "OutcomeLink":
        if self.label != "unknown" and not self.observed_event_ids:
            raise ValueError("only observed follow-up evidence assigns an outcome label")
        return self


class ResolvedEvidence(StrictModel):
    source_ref: SourceRef | None
    origin_event_key: OriginEventKey
    text: str | None
    typed_observation: JsonObject | None
    original_locator: SpanLocator | None
    availability: Literal["available", "capsule_only", "expired", "redacted"]
    root_class_ids: list[Id]
    integrity: Literal["ok", "mismatch"]


class ScratchEntry(StrictModel):
    attempt_id: Id
    packet_digest: Digest
    items: list[EmittedItem]
    state: Literal["reserved", "emitted", "uncertain"]
    purpose: Purpose
    estimated_tokens: NonNegative
    time: UtcTime


class ScratchOutcome(StrictModel):
    event_id: Id
    action: ActionDescriptor
    outcome: Outcome
    changed_paths: list[Annotated[str, Field(max_length=1024)]] = Field(default_factory=list)
    coverage: JsonObject = Field(default_factory=dict)


class SessionScratch(StrictModel):
    scratch_schema: One
    session_id: Id
    state_revision: NonNegative
    store_revision: NonNegative
    guidance_epoch: NonNegative
    policy_revision: Revision
    tombstone_epoch: NonNegative
    reserved_tokens: NonNegative
    emitted_tokens: NonNegative
    outcomes: Annotated[list[ScratchOutcome], Field(max_length=SESSION_SCRATCH_OUTCOMES)] = Field(default_factory=list)
    entries: Annotated[list[ScratchEntry], Field(max_length=SESSION_SCRATCH_ENTRIES)] = Field(default_factory=list)

    @model_validator(mode="after")
    def _bounded(self) -> "SessionScratch":
        if len(canonical_json(self.model_dump(mode="json"))) > SESSION_SCRATCH_CAP:
            raise ValueError("session scratch exceeds 128 KiB")
        return self
