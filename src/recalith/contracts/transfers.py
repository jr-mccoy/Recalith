"""Backup/export manifests, imports and upgrades (DATA_CONTRACTS §11)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import Digest, Id, NonNegative, RecordRef, StrictModel, UtcTime


class ExportRecordSelection(StrictModel):
    ref: RecordRef
    allowed_fields: list[Annotated[str, Field(min_length=1, max_length=64)]]


class ExportSelection(StrictModel):
    records: Annotated[list[ExportRecordSelection], Field(min_length=1)]
    include_capsules: bool = False
    visibility: Literal["private", "shareable"] = "private"


class ArtifactManifest(StrictModel):
    artifact_id: Id
    artifact_type: Literal["backup", "export"]
    schemas: dict[Annotated[str, Field(pattern=r"^[a-z_]{1,32}$")], Annotated[int, Field(ge=1)]]
    project_id: Id
    installation_id: Id
    engine_version: Annotated[str, Field(min_length=1, max_length=64)]
    created_at: UtcTime
    file_digests: dict[Annotated[str, Field(min_length=1, max_length=256)], Digest]
    tombstone_epoch: NonNegative

    @model_validator(mode="after")
    def _files(self) -> "ArtifactManifest":
        if not self.file_digests:
            raise ValueError("a manifest lists the digests of its files")
        return self


class ImportResult(StrictModel):
    created: NonNegative
    updated: NonNegative
    duplicate: NonNegative
    disputed: NonNegative
    rejected: NonNegative
    resulting_refs: list[RecordRef] = Field(default_factory=list)


class UpgradeResult(StrictModel):
    operation_id: Id
    source_profile: Literal["claude_preview", "full"]
    target_profile: Literal["claude_preview", "full"]
    source_engine: Annotated[str, Field(min_length=1, max_length=64)]
    target_engine: Annotated[str, Field(min_length=1, max_length=64)]
    state: Literal["not_activated", "activated", "rolled_back", "recovery_required"]
    preserved_installation_id: Id
    verified_backup_id: Id | None
    baseline_digest: Digest | None
    retained_pin_count: NonNegative
    error_codes: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _transition(self) -> "UpgradeResult":
        if self.source_profile == "full" and self.target_profile == "claude_preview":
            raise ValueError("full-to-preview downgrade is not a supported transition")
        if self.state in ("activated", "rolled_back") and self.verified_backup_id is None:
            raise ValueError("no migration or activation proceeds without a verified backup")
        return self
