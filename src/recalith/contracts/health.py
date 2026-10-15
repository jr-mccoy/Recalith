"""Profile-aware health and readiness (DATA_CONTRACTS §11, SYSTEM_SPEC §15)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import JsonObject, NonNegative, StrictModel, UtcTime
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


class CapabilityState(StrictModel):
    state: Literal["healthy", "degraded", "unavailable"]
    required: bool
    reason_codes: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]] = Field(default_factory=list)
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


class HealthReport(StrictModel):
    release_profile: ReleaseProfile
    capabilities: dict[str, CapabilityState]
    worker_state: Literal["running", "idle", "stopped", "degraded", "budget_paused", "migration_required"]
    coverage_gaps: list[Annotated[str, Field(max_length=256)]] = Field(default_factory=list)
    job_summary: JsonObject = Field(default_factory=dict)
    budget_summary: JsonObject = Field(default_factory=dict)
    retention_summary: RetentionSummary
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
        return self
