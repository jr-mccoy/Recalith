"""Forgetting, tombstones, operator tokens and restore (DATA_CONTRACTS §8, §11)."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import (
    Digest,
    Id,
    JsonObject,
    NonNegative,
    One,
    RecordRef,
    StrictModel,
    UtcTime,
)

OPERATOR_TOKEN_MAX_BYTES = 4096
OPERATOR_TOKEN_MIN_ENTROPY_BYTES = 32


class SourceRange(StrictModel):
    adapter_id: Annotated[str, Field(min_length=1, max_length=128)]
    host_session_id: Annotated[str, Field(min_length=1, max_length=256)]
    from_sequence: NonNegative
    to_sequence: NonNegative

    @model_validator(mode="after")
    def _ordered(self) -> "SourceRange":
        if self.to_sequence < self.from_sequence:
            raise ValueError("source range end precedes start")
        return self


class SavedQueryResult(StrictModel):
    query_digest: Digest
    record_refs: Annotated[list[RecordRef], Field(min_length=1)]


class ForgetSelector(StrictModel):
    """An enumerated selection; never executable text."""

    record_refs: list[RecordRef] = Field(default_factory=list)
    task_ids: list[Id] = Field(default_factory=list)
    source_ranges: list[SourceRange] = Field(default_factory=list)
    saved_query: SavedQueryResult | None = None

    @model_validator(mode="after")
    def _nonempty(self) -> "ForgetSelector":
        if not (self.record_refs or self.task_ids or self.source_ranges or self.saved_query):
            raise ValueError("a forget selector names at least one target")
        return self


class ForgetPreview(StrictModel):
    affected_refs: list[RecordRef]
    derivative_refs: list[RecordRef]
    backup_ids: list[Id]
    export_ids: list[Id]
    preview_digest: Digest
    # Task 16 (decision 0017): the derivatives that keep surviving roots (content-free quarantine, reconstruction
    # later) and the content-free limit codes of logical forgetting.
    quarantined_refs: list[RecordRef] = Field(default_factory=list)
    limits: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list)


class ForgetRequest(StrictModel):
    selector: ForgetSelector
    preview_digest: Digest
    reason: Annotated[str, Field(max_length=512)] | None = None


class ForgetResult(StrictModel):
    operation_id: Id
    purge_state: Literal["completed", "cleanup_pending"]
    purged_count: NonNegative
    quarantined_count: NonNegative
    tombstone_epoch: Annotated[int, Field(ge=1)]
    backup_state: Literal["verified", "unavailable", "pending"]
    new_backup_id: Id | None
    deleted_backup_ids: list[Id]
    external_copy_ids: list[Id]
    replay_suppression_coverage: JsonObject
    error_codes: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _backup(self) -> "ForgetResult":
        if (self.backup_state == "verified") != (self.new_backup_id is not None):
            raise ValueError("only a verified post-forget backup has an id")
        if self.backup_state == "unavailable" and "backup_unavailable_after_forget" not in self.error_codes:
            raise ValueError("a failed replacement backup reports backup_unavailable_after_forget")
        return self


class Tombstone(StrictModel):
    """Content-free suppression record: identifiers and digests only."""

    target_ids: Annotated[list[Id], Field(min_length=1)]
    source_digests: list[Digest] = Field(default_factory=list)
    created_at: UtcTime
    epoch: Annotated[int, Field(ge=1)]
    deletion_scope: Literal["record", "task", "source_range", "saved_query"]


def _decode_secret(secret: str) -> bytes:
    text = secret.strip()
    if len(text) != len(secret) or not text:
        raise ValueError("token secret must not have surrounding whitespace")
    try:
        if all(c in "0123456789abcdef" for c in text):
            return binascii.unhexlify(text)
        padded = text + "=" * (-len(text) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("token secret is not hex or base64url") from exc


class OperatorTokenFile(StrictModel):
    schema_: One = Field(alias="schema")
    token_id: Id
    secret: Annotated[str, Field(min_length=43, max_length=1024, repr=False)]
    created_at: UtcTime

    model_config = {**StrictModel.model_config, "populate_by_name": False}

    @model_validator(mode="after")
    def _entropy(self) -> "OperatorTokenFile":
        if not self.token_id.startswith("tok_"):
            raise ValueError("operator token ids use the tok_ prefix")
        if len(_decode_secret(self.secret)) < OPERATOR_TOKEN_MIN_ENTROPY_BYTES:
            raise ValueError("operator token secret carries fewer than 256 bits")
        return self

    @classmethod
    def parse_file_bytes(cls, raw: bytes) -> "OperatorTokenFile":
        """Bounded, strict parse; never echoes file contents in errors."""
        if len(raw) > OPERATOR_TOKEN_MAX_BYTES:
            raise ValueError("operator token file exceeds 4 KiB")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("operator token file is not UTF-8 JSON") from exc
        return cls.model_validate(data)


class RestoreResult(StrictModel):
    applied_schema: Annotated[int, Field(ge=1)]
    restored_revision: NonNegative
    preserved_tombstone_epoch: NonNegative
    suppressed_record_count: NonNegative
    # Task 16 (decision 0017): whether the restored snapshot held content a newer tombstone suppressed, the
    # affected recorded backups deleted under the forgetting policy, and the content-free limit codes.
    source_contains_suppressed: bool = False
    deleted_backup_ids: list[Id] = Field(default_factory=list)
    limits: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list)
