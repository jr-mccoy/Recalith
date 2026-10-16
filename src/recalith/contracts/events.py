"""Event envelope, durable segments and capture receipts (DATA_CONTRACTS §2).

Adapters assign transport, origin and authority. A strict envelope rejects
unknown fields, inconsistent channel/authority pairs, digest mismatches,
oversized payloads and the reserved ``expected_red=true``.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import Field, model_validator

from recalith.fast.spool import segment_body

from .common import (
    DependencyRef,
    Digest,
    ExactBool,
    Id,
    JsonObject,
    NonNegative,
    One,
    OriginEventKey,
    PortablePath,
    RecordRef,
    Revision,
    SourceRef,
    StrictModel,
    UtcTime,
    _check_environment,
    bounded_text,
    canonical_json,
    digest_of,
)
from .config import (
    ERROR_SIGNATURE_CAP,
    EVENT_PAYLOAD_CAP,
    EXTENSIONS_CAP,
    RESULT_TEXT_HEAD,
    RESULT_TEXT_TAIL,
    SEGMENT_CAP,
    TOOL_ASSERTION_IDENTITY_MAX,
    TOOL_ASSERTION_VALUE_MAX,
    TOOL_ASSERTIONS_MAX,
)

EventKind = Literal[
    "session_started",
    "user_message",
    "assistant_message",
    "tool_started",
    "tool_finished",
    "artifact_changed",
    "compaction",
    "session_stopped",
    "session_ended",
    "memory_delivered",
    "operator_declaration",
    "operator_correction",
    "operator_forget",
    "agent_attempted_operator_command",
    "generic_observation",
]
Channel = Literal["user", "assistant", "tool", "external", "memory"]
Authority = Literal["untrusted", "observed_tool", "explicit_user", "derived"]
Outcome = Literal["success", "failure", "interrupted", "not_run", "unknown"]
OPERATOR_KINDS = frozenset({"operator_declaration", "operator_correction", "operator_forget"})
TOOL_KINDS = frozenset({"tool_started", "tool_finished"})
MEMORY_KINDS = frozenset({"memory_delivered", "agent_attempted_operator_command"})
SmallStr = Annotated[str, Field(min_length=1, max_length=256)]


class Coverage(StrictModel):
    truncated: bool
    redacted: bool
    missing_context: bool
    parser_complete: bool


class ActionDescriptor(StrictModel):
    cwd_path: PortablePath | None = None
    tool: SmallStr
    action_kind: Literal["read", "write", "delete", "test", "build", "publish", "version_control", "other", "unknown"] | None = None
    executable: Annotated[str, Field(max_length=1024)] | None = None
    argv: list[Annotated[str, Field(max_length=8192)]] | None = None
    paths: list[PortablePath] = Field(default_factory=list)
    raw_digest: Digest | None = None
    parse_status: Literal["exact", "conservative", "unknown"]
    shell: Annotated[str, Field(max_length=64)] | None = None

    @model_validator(mode="after")
    def _unknown_stays_unknown(self) -> "ActionDescriptor":
        # Ambiguous parses cannot invent an executable, argv or action kind.
        if self.parse_status == "unknown" and (self.argv is not None or self.executable is not None or self.action_kind not in (None, "unknown")):
            raise ValueError("an unknown parse cannot carry executable, argv or a specific action_kind")
        return self


class ToolAssertion(StrictModel):
    kind: Literal["test_result", "exit_status", "parsed_value"]
    identity: Annotated[str, bounded_text(TOOL_ASSERTION_IDENTITY_MAX), Field(min_length=1)]
    value: Annotated[str, bounded_text(TOOL_ASSERTION_VALUE_MAX)]
    passed: bool | None = None

    @model_validator(mode="after")
    def _shape(self) -> "ToolAssertion":
        if self.kind == "exit_status" and (not self.value.lstrip("-").isdigit() or str(int(self.value)) != self.value):
            raise ValueError("exit_status value must be a canonical decimal integer")
        if self.kind != "test_result" and self.passed is not None:
            raise ValueError("only test_result assertions carry a pass/fail verdict")
        return self


class TextChunk(StrictModel):
    """A stored span with its original code-point coordinates."""

    stored_field: SmallStr
    source_field: SmallStr
    original_start: NonNegative
    original_end: NonNegative
    text: str
    text_digest: Digest

    @model_validator(mode="after")
    def _exact(self) -> "TextChunk":
        if self.original_end - self.original_start != len(self.text):
            raise ValueError("chunk text length must equal its original coordinate span")
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.text_digest:
            raise ValueError("text_digest does not match chunk text")
        return self


class ObservationDescriptor(StrictModel):
    origin_event_key: OriginEventKey
    observation_kind: Literal["user_declaration", "tool_result", "artifact_snapshot"]
    authority_actor_id: Annotated[str, Field(max_length=128)] | None = None
    artifact_key: Annotated[str, Field(max_length=1024)] | None = None
    artifact_digest: Digest | None = None
    action: ActionDescriptor | None = None
    experiment_identity: Annotated[str, Field(max_length=512)] | None = None
    dependencies: list[DependencyRef] = Field(default_factory=list)
    dependency_coverage: Literal["complete", "partial", "unknown"]
    forwarded_origin_keys: list[OriginEventKey] = Field(default_factory=list)


class ToolPayload(StrictModel):
    tool_call_id: Annotated[str, Field(min_length=1, max_length=256)]
    tool_name: SmallStr
    arguments: JsonObject
    result_received: bool
    outcome: Outcome
    exit_code: int | None = None
    result_text: Annotated[str, bounded_text(RESULT_TEXT_HEAD + RESULT_TEXT_TAIL + 256)] | None = None
    assertions: Annotated[list[ToolAssertion], Field(max_length=TOOL_ASSERTIONS_MAX)] = Field(default_factory=list)
    action: ActionDescriptor
    observation: ObservationDescriptor | None = None
    text_chunks: list[TextChunk] = Field(default_factory=list)
    error_signature: Annotated[str, bounded_text(ERROR_SIGNATURE_CAP)] | None = None
    # Reserved false in v1: no host or assistant-intent signal is certified to set it.
    expected_red: Annotated[Literal[False], ExactBool] = False

    @model_validator(mode="after")
    def _result_consistency(self) -> "ToolPayload":
        if not self.result_received and (self.outcome != "unknown" or self.exit_code is not None):
            raise ValueError("a call without a received result has unknown outcome and no exit code")
        return self


class AgentAttemptPayload(StrictModel):
    """Content-free record of a refused administrative command."""

    command_kind: Annotated[str, Field(min_length=1, max_length=64)]
    marker_category: Annotated[str, Field(min_length=1, max_length=64)]
    reason_code: Literal["policy_refused"]


class EventEnvelope(StrictModel):
    schema_version: One
    event_id: Id
    project_id: Id
    installation_id: Id
    workspace_id: Id
    adapter_id: SmallStr
    adapter_version: Annotated[str, Field(min_length=1, max_length=64)]
    source_event_key: Annotated[str, Field(min_length=1, max_length=512)]
    session_id: Id
    host_session_id: Annotated[str, Field(max_length=256)]
    task_id: Id | None
    source_sequence: NonNegative | None
    occurred_at: UtcTime | None
    recorded_at: UtcTime
    kind: EventKind
    channel: Channel
    origin: SourceRef
    authority: Authority
    derived_from: list[RecordRef] = Field(default_factory=list)
    root_event_ids: list[Id] = Field(default_factory=list)
    payload: JsonObject
    payload_digest: Digest
    coverage: Coverage
    extensions: dict[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.\-]{0,63}$")], JsonObject] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistency(self) -> "EventEnvelope":
        if not (self.event_id.startswith("evt_")):
            raise ValueError("event ids use the evt_ or evt_imp_ prefix")
        payload_bytes = canonical_json(self.payload)
        if len(payload_bytes) > EVENT_PAYLOAD_CAP:
            raise ValueError("event payload exceeds 64 KiB")
        if digest_of(self.payload) != self.payload_digest:
            raise ValueError("payload_digest does not match the canonical payload")
        if self.extensions and len(canonical_json(self.extensions)) > EXTENSIONS_CAP:
            raise ValueError("extensions exceed their byte cap")
        if self.extensions and set(self.extensions) != {self.adapter_id}:
            raise ValueError("extensions must be namespaced by the producing adapter")
        # Channel/authority pairs are assigned by certified adapter code.
        if self.authority == "explicit_user" and self.channel != "user":
            raise ValueError("explicit_user authority requires the user channel")
        if self.authority == "observed_tool" and self.channel != "tool":
            raise ValueError("observed_tool authority requires the tool channel")
        if self.channel in ("assistant", "memory") and self.authority not in ("untrusted", "derived"):
            raise ValueError("assistant and memory channels can never carry user or tool authority")
        if self.kind in TOOL_KINDS:
            if self.channel != "tool":
                raise ValueError("tool events use the tool channel")
            tool = ToolPayload.model_validate(self.payload)
            if self.kind == "tool_started" and (tool.result_received or tool.outcome != "unknown"):
                raise ValueError("tool_started has no result; a later linked event supplies it")
        if self.kind in MEMORY_KINDS and (self.channel != "memory" or self.authority != "derived"):
            raise ValueError("memory telemetry is channel memory with derived authority")
        if self.kind == "agent_attempted_operator_command":
            AgentAttemptPayload.model_validate(self.payload)
            if self.root_event_ids or self.derived_from:
                raise ValueError("a refused-command diagnostic has no eligible root")
        if self.kind == "user_message" and self.channel != "user":
            raise ValueError("user_message uses the user channel")
        if self.kind == "assistant_message" and self.channel != "assistant":
            raise ValueError("assistant_message uses the assistant channel")
        if not self.derived_from and self.root_event_ids not in ([], [self.event_id]):
            raise ValueError("an original event is its own root")
        if self.authority == "derived" and self.root_event_ids and self.kind in MEMORY_KINDS:
            raise ValueError("memory telemetry never supplies support roots")
        return self


class CaptureReceipt(StrictModel):
    status: Literal["accepted", "duplicate", "not_captured"]
    segment_id: Id | None
    event_ids: list[Id]
    coverage: JsonObject
    error_code: Annotated[str, Field(max_length=64)] | None

    @model_validator(mode="after")
    def _shape(self) -> "CaptureReceipt":
        if self.status == "not_captured" and (self.error_code is None or self.segment_id is not None):
            raise ValueError("not_captured receipts carry an error code and no segment")
        if self.status == "accepted" and self.segment_id is None:
            raise ValueError("accepted receipts name their durable segment")
        return self


class CursorProposal(StrictModel):
    source_id: Id
    cursor: JsonObject


SOURCE_REGISTRATIONS_MAX = 8


class SourceRegistrationProposal(StrictModel):
    """An exact transcript path observed in an actual session payload (decision 0005).

    Hooks cannot write SQLite, so the fast path proposes the registration in
    the segment and ingestion records it in ``capture_sources`` in the same
    transaction as the session's events. ``locator`` is a local absolute path;
    it never enters an event payload.
    """

    source_id: Id
    adapter_id: SmallStr
    session_id: Id
    host_session_id: Annotated[str, Field(min_length=1, max_length=256)]
    source_kind: Literal["transcript_jsonl"]
    locator: Annotated[str, Field(min_length=1, max_length=1024)]
    parser: Annotated[str, Field(min_length=1, max_length=64)]


class Segment(StrictModel):
    segment_schema: One
    segment_id: Id
    project_id: Id
    installation_id: Id
    envelopes: Annotated[list[EventEnvelope], Field(min_length=1)]
    cursor_proposals: list[CursorProposal] = Field(default_factory=list)
    source_registrations: Annotated[list[SourceRegistrationProposal], Field(max_length=SOURCE_REGISTRATIONS_MAX)] = Field(default_factory=list)
    created_at: UtcTime
    content_digest: Digest

    @model_validator(mode="after")
    def _bounded_and_owned(self) -> "Segment":
        body = segment_body(
            [e.model_dump(mode="json") for e in self.envelopes],
            [c.model_dump(mode="json") for c in self.cursor_proposals],
            [r.model_dump(mode="json") for r in self.source_registrations],
        )
        if len(canonical_json(body)) > SEGMENT_CAP:
            raise ValueError("segment exceeds 256 KiB")
        if digest_of(body) != self.content_digest:
            raise ValueError("segment content_digest mismatch")
        for env in self.envelopes:
            if env.installation_id != self.installation_id or env.project_id != self.project_id:
                raise ValueError("foreign_installation: segment contains another installation's event")
        return self


class SourceConflict(StrictModel):
    conflict_id: Id
    original_event_id: Id
    adapter_id: SmallStr
    source_event_key: Annotated[str, Field(min_length=1, max_length=512)]
    payload_digest: Digest
    scrubbed_payload: JsonObject
    coverage: JsonObject
    first_seen_at: UtcTime
    state: Literal["unresolved", "resolved", "forgotten"]

    @model_validator(mode="after")
    def _prefix(self) -> "SourceConflict":
        if not self.conflict_id.startswith("conf_"):
            raise ValueError("conflict ids use the conf_ prefix")
        return self


class EnvironmentObservation(StrictModel):
    key: Literal["os", "arch", "python_version", "node_version", "ci"]
    value: Annotated[str, Field(max_length=64)]
    workspace_id: Id
    executable_id: Annotated[str, Field(max_length=256)] | None
    source_kind: Literal["operator_config", "certified_tool", "adapter_platform"]
    source_ref: RecordRef | None
    config_revision: Revision | None
    observed_at: UtcTime
    fingerprint: Digest
    executable_fingerprint: Digest | None
    freshness: Literal["current", "stale", "unknown"]

    @model_validator(mode="after")
    def _source_rules(self) -> "EnvironmentObservation":
        _check_environment({self.key: self.value})
        runtime = self.key in ("python_version", "node_version")
        if self.source_kind == "adapter_platform" and runtime:
            raise ValueError("adapter platform facts never supply runtime versions")
        if self.source_kind == "operator_config" and self.config_revision is None:
            raise ValueError("operator_config observations name their config revision")
        if self.source_kind == "certified_tool":
            if self.source_ref is None or self.source_ref.kind != "event":
                raise ValueError("certified_tool observations reference the observed version-command event")
            if self.executable_id is None or self.executable_fingerprint is None:
                if self.freshness != "unknown":
                    raise ValueError("a tool observation without executable binding is unknown")
        return self

