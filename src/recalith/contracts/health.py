"""Profile-aware health and readiness (DATA_CONTRACTS §11, SYSTEM_SPEC §15; decision 0018)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import Digest, Id, JsonObject, NonNegative, StrictModel, UtcTime
from .config import ReleaseProfile

REQUIRED_CAPABILITIES = (
    "capture",
    "inference",
    "admission",
    "recovery",
    "forget",
    "operator_guard",
    "start_delivery",
    "prompt_delivery",
)
OPTIONAL_CAPABILITIES = ("pre_action_delivery", "compact_delivery")
# Full-release features that a preview must report explicitly (SYSTEM_SPEC §1.2).
DEFERRED_FULL_CAPABILITIES = (
    "codex_capture",
    "codex_delivery",
    "generic_json",
    "mcp",
    "capsules",
    "export",
    "import",
    "breadcrumbs_import",
    "workspace_attach",
    "project_fork",
    "session_worker",
    "shared_integration",
    "ipc_wake",
    "revision_chain",
    "private_path_install",
    "side_by_side_upgrade",
)
ALL_CAPABILITIES = REQUIRED_CAPABILITIES + OPTIONAL_CAPABILITIES + DEFERRED_FULL_CAPABILITIES
# The hook manifest's delivery purposes and the capability each one reports (decision 0015, 0018).
DELIVERY_PATHS = ("session_start", "prompt", "pre_action", "compact_restore")
DELIVERY_CAPABILITY = {"session_start": "start_delivery", "prompt": "prompt_delivery", "pre_action": "pre_action_delivery", "compact_restore": "compact_delivery"}
PRIVACY_PHASES = ("purged", "files", "ledger", "backup", "deleted", "reconstructed", "completed")
MAX_REPORTED = 256

ReasonCode = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
DeliveryPath = Literal["session_start", "prompt", "pre_action", "compact_restore"]


class CapabilityState(StrictModel):
    state: Literal["healthy", "degraded", "unavailable"]
    required: bool
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    certified_version: Annotated[str, Field(max_length=128)] | None = None
    certified_at: UtcTime | None = None
    coverage: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def _explained(self) -> "CapabilityState":
        if self.state != "healthy" and not self.reason_codes:
            raise ValueError("a degraded or unavailable capability states its reason")
        return self


class RetentionSummary(StrictModel):
    pinned_payload_bytes: NonNegative
    unpinned_payload_bytes: NonNegative
    live_owner_count: NonNegative
    free_disk_bytes: NonNegative | None
    deferred_compaction_count: NonNegative


class HostCertification(StrictModel):
    """The installation's host delivery/protection record (``.recalith/host.json``, private; decision 0018).

    Task 13's certification produces it (the nonce protocol per delivery
    path, the installed command deny rules, the private-path probe); health
    only reads it. ``mode`` ``live`` is the only certification: a
    request-capture observation never makes a path healthy. The record binds
    one installation and one exact host version; any other installation or
    version makes it inapplicable.
    """

    certification_schema: Literal[1]
    installation_id: Id
    host_id: Literal["claude_code"]
    host_version: Annotated[str, Field(min_length=1, max_length=128)]
    mode: Literal["live", "request_capture"]
    certified_at: UtcTime
    report_digest: Digest
    delivery: dict[DeliveryPath, Literal["certified", "failed", "unavailable"]]
    command_rules: Literal["installed", "unavailable"]
    private_paths: Literal["probed_supported", "probed_limited", "probed_unsupported", "not_run"]

    @model_validator(mode="after")
    def _every_path(self) -> "HostCertification":
        if set(self.delivery) != set(DELIVERY_PATHS):
            raise ValueError("a host record reports every delivery path")
        return self


class InstallationState(StrictModel):
    """Which installation was checked, its pinned engine and its store schema (A02/A40)."""

    project_id: Id
    installation_id: Id
    engine_version: Annotated[str, Field(max_length=128)]
    pinned_engine_version: Annotated[str, Field(max_length=128)] | None
    schema_version: NonNegative | None
    supported_schema_version: NonNegative
    schema_state: Literal["current", "migration_required", "newer_unsupported", "unreadable"]
    store_revision: NonNegative | None = None
    tombstone_epoch: NonNegative | None = None

    @model_validator(mode="after")
    def _schema(self) -> "InstallationState":
        if self.schema_state == "current" and self.schema_version != self.supported_schema_version:
            raise ValueError("schema_state 'current' means exactly the supported schema")
        if self.schema_state in ("migration_required", "newer_unsupported") and self.schema_version == self.supported_schema_version:
            raise ValueError("a migration or newer schema state names another schema than the supported one")
        return self


class ConflictEntry(StrictModel):
    """One unresolved source conflict (one per distinct conflicting digest, A49); identifiers only."""

    conflict_id: Id
    original_event_id: Id
    adapter_id: Annotated[str, Field(max_length=64)]
    payload_digest: Digest
    first_seen_at: UtcTime


class PrivacyOperationState(StrictModel):
    operation_id: Id
    phase: Literal["purged", "files", "ledger", "backup", "deleted", "reconstructed", "completed"]
    status: Literal["running", "cleanup_pending"]


class PrivacyMaintenance(StrictModel):
    """Pending privacy maintenance from forgetting and restore (decision 0017) and the reported limits."""

    state: Literal["idle", "pending"]
    unfinished_operations: list[PrivacyOperationState] = Field(default_factory=list, max_length=64)
    scratch_cleanup_pending: bool = False
    backup_unavailable_after_forget: list[Id] = Field(default_factory=list, max_length=64)
    restore_journaled: bool = False
    maintenance_marker: Literal["absent", "active", "stale"] = "absent"
    delivery_paused: bool = False
    limits: list[ReasonCode] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> "PrivacyMaintenance":
        pending = bool(self.unfinished_operations or self.scratch_cleanup_pending or self.backup_unavailable_after_forget or self.restore_journaled or self.maintenance_marker != "absent")
        if (self.state == "pending") != pending:
            raise ValueError("privacy maintenance is pending exactly when something is owed")
        if self.delivery_paused != (self.maintenance_marker != "absent"):
            raise ValueError("delivery is paused exactly while the maintenance marker exists")
        return self


class HealthReport(StrictModel):
    release_profile: ReleaseProfile
    capabilities: dict[str, CapabilityState]
    worker_state: Literal["running", "idle", "stopped", "degraded", "budget_paused", "migration_required"]
    readiness: Literal["ready", "degraded", "unavailable"]
    checked_at: UtcTime
    installation: InstallationState
    coverage_gaps: list[Annotated[str, Field(max_length=256)]] = Field(default_factory=list, max_length=MAX_REPORTED)
    job_summary: JsonObject = Field(default_factory=dict)
    budget_summary: JsonObject = Field(default_factory=dict)
    retention_summary: RetentionSummary | None
    source_conflicts: list[ConflictEntry] = Field(default_factory=list, max_length=MAX_REPORTED)
    source_conflict_count: NonNegative = 0
    privacy_maintenance: PrivacyMaintenance
    autonomous_ready: bool

    @model_validator(mode="after")
    def _readiness(self) -> "HealthReport":
        missing = sorted(set(ALL_CAPABILITIES) - set(self.capabilities))
        if missing:
            raise ValueError(f"health must report every registered capability; missing {missing}")
        for name in REQUIRED_CAPABILITIES:
            if not self.capabilities[name].required:
                raise ValueError(f"{name} is a required capability")
        for name in OPTIONAL_CAPABILITIES + DEFERRED_FULL_CAPABILITIES:
            if self.capabilities[name].required:
                raise ValueError(f"{name} does not gate readiness")
        if self.release_profile == "claude_preview":
            for name in DEFERRED_FULL_CAPABILITIES:
                if self.capabilities[name].state != "unavailable":
                    raise ValueError(f"{name} is a deferred full-release capability in preview")
        ready = all(self.capabilities[n].state == "healthy" for n in REQUIRED_CAPABILITIES)
        if self.autonomous_ready != ready:
            raise ValueError("autonomous_ready is exactly 'every required capability healthy'")
        current = self.installation.schema_state == "current"
        expected = "ready" if ready else ("degraded" if current else "unavailable")
        if self.readiness != expected:
            raise ValueError("readiness is 'ready' when autonomous_ready, 'unavailable' when the store cannot be served, else 'degraded'")
        if ready and not current:
            raise ValueError("a store this engine cannot serve is never ready")
        if self.retention_summary is None and current:
            raise ValueError("a servable store's retention is measured, never omitted")
        if len(self.source_conflicts) > self.source_conflict_count:
            raise ValueError("source_conflict_count counts every listed conflict")
        return self
