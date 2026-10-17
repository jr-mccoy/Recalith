"""Shared primitive types and references (DATA_CONTRACTS §1).

Every worker/service DTO derives from :class:`StrictModel`: unknown fields are
rejected, values are not coerced between types, NaN/Infinity are refused, and
instances are immutable. Timestamps are kept as canonical strings
(``YYYY-MM-DDTHH:MM:SS.ffffffZ``) so canonical JSON, digests, and the
standard-library fast path agree byte for byte.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import re
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal, Mapping

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

# --------------------------------------------------------------------------
# Base model


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
        validate_default=True,
        ser_json_inf_nan="null",
    )


# --------------------------------------------------------------------------
# Identifiers, digests and time

ID_PREFIXES = frozenset(
    {
        "proj", "inst", "ws", "sess", "task", "ep", "claim", "job", "op", "dlv",
        "evt", "evt_imp", "conf", "root", "batch", "cap", "bnd", "bind", "att",
        "trig", "act", "tok", "src", "prop", "grp", "upg", "bkp", "exp", "imp",
        "frg", "rev", "seg", "obs", "rsv", "inv", "item",
    }
)
_UUID4 = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_SHA = r"[0-9a-f]{64}"
ID_RE = re.compile(rf"^(?P<prefix>[a-z]+(?:_[a-z]+)?)_(?P<body>{_UUID4}|{_SHA})$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def _check_id(value: str) -> str:
    match = ID_RE.match(value)
    if not match or match.group("prefix") not in ID_PREFIXES:
        raise ValueError("invalid identifier: expected a registered lowercase prefix plus UUIDv4 or SHA-256")
    return value


def _check_digest(value: str) -> str:
    if not DIGEST_RE.match(value):
        raise ValueError("digest must be 64 lowercase hex characters")
    return value


def _check_utc(value: str) -> str:
    if not UTC_RE.match(value):
        raise ValueError("timestamp must be UTC RFC3339 with microseconds, e.g. 2026-10-15T00:00:00.000000Z")
    try:
        _dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise ValueError("timestamp is not a valid calendar time") from exc
    return value


def _exact_type(kind: type):
    """Pydantic's literal validator accepts ``True``/``1.0`` for ``1`` and ``0`` for
    ``False`` even in strict mode; this before-check keeps literals type-exact."""

    def check(value: Any) -> Any:
        if type(value) is not kind:
            raise ValueError(f"expected exactly a JSON {'boolean' if kind is bool else 'integer'}")
        return value

    check.exact_type = kind.__name__  # type: ignore[attr-defined]  # read by tools/generate_hook_wire.py
    return BeforeValidator(check)


ExactInt = _exact_type(int)
ExactBool = _exact_type(bool)
One = Annotated[Literal[1], ExactInt]

Id = Annotated[str, AfterValidator(_check_id)]
Digest = Annotated[str, AfterValidator(_check_digest)]
UtcTime = Annotated[str, AfterValidator(_check_utc)]
Revision = Annotated[int, Field(ge=1)]
NonNegative = Annotated[int, Field(ge=0)]


def utc_now() -> str:
    return format_utc(_dt.datetime.now(_dt.timezone.utc))


def format_utc(moment: _dt.datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("naive datetime")
    return moment.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_utc(value: str) -> _dt.datetime:
    return _dt.datetime.strptime(_check_utc(value), "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=_dt.timezone.utc)


def new_id(prefix: str) -> str:
    """A fresh ``prefix_<uuid4>`` identifier."""
    if prefix not in ID_PREFIXES:
        raise ValueError(f"unregistered id prefix {prefix!r}")
    return f"{prefix}_{uuid.uuid4()}"


def derived_id(prefix: str, value: Any) -> str:
    """Deterministic ``prefix_<sha256(canonical JSON)>`` identifier."""
    if prefix not in ID_PREFIXES:
        raise ValueError(f"unregistered id prefix {prefix!r}")
    return f"{prefix}_{digest_of(value)}"


# --------------------------------------------------------------------------
# JSON values


def _check_json(value: Any, depth: int = 0) -> None:
    if depth > 64:
        raise ValueError("JSON nesting deeper than 64")
    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite (no NaN or Infinity)")
        return
    if isinstance(value, list):
        for item in value:
            _check_json(item, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            _check_json(item, depth + 1)
        return
    raise ValueError(f"not a JSON value: {type(value).__name__}")


def _check_json_object(value: dict[str, Any]) -> dict[str, Any]:
    _check_json(value)
    return value


JsonObject = Annotated[dict[str, Any], AfterValidator(_check_json_object)]


def canonical_json(value: Any) -> bytes:
    """Canonical UTF-8 JSON: sorted keys, no whitespace, finite numbers only."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    _check_json(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest_of(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def bounded_text(max_bytes: int):
    def check(value: str) -> str:
        if utf8_len(value) > max_bytes:
            raise ValueError(f"text exceeds {max_bytes} UTF-8 bytes")
        return value

    check.utf8_max = max_bytes  # type: ignore[attr-defined]  # read by tools/generate_hook_wire.py
    return AfterValidator(check)


# --------------------------------------------------------------------------
# Paths

_PORTABLE_BAD = re.compile(r"(^/|^[A-Za-z]:|\\|(^|/)\.\.(/|$)|(^|/)\.(/|$)|//|\x00)")


def _check_portable_path(value: str) -> str:
    """Normalized relative POSIX path; a trailing '/' denotes a directory prefix."""
    if value in ("", "."):
        return value
    if _PORTABLE_BAD.search(value):
        raise ValueError("portable paths are normalized relative POSIX paths without '..', '.', or absolute roots")
    return value


PortablePath = Annotated[str, AfterValidator(_check_portable_path)]


# --------------------------------------------------------------------------
# Actors and references


class Actor(StrictModel):
    """Assigned by the guarded transport; never accepted from provider output."""

    kind: Literal["operator", "host_agent", "controller", "adapter"]
    id: Annotated[str, Field(min_length=1, max_length=128)]
    channel: Literal["cli", "hook", "mcp", "worker", "import"]


class RecordRef(StrictModel):
    kind: Literal["event", "task", "episode", "claim", "capsule"]
    id: Id
    revision: Revision


class SourceRef(StrictModel):
    adapter_id: Annotated[str, Field(min_length=1, max_length=128)]
    source_event_key: Annotated[str, Field(min_length=1, max_length=512)]
    host_session_id: Annotated[str, Field(max_length=256)]
    origin_kind: Annotated[str, Field(min_length=1, max_length=64)]
    source_digest: Digest
    locator: Annotated[str, Field(max_length=1024)] | None = None


class OriginEventKey(StrictModel):
    source_namespace: Annotated[str, Field(min_length=1, max_length=256)]
    source_event_key: Annotated[str, Field(min_length=1, max_length=512)]


class SpanLocator(StrictModel):
    """Unicode code-point offsets into an exact stored string field/chunk."""

    field: Annotated[str, Field(min_length=1, max_length=256)]
    start: NonNegative
    end: NonNegative
    text_digest: Digest

    @model_validator(mode="after")
    def _ordered(self) -> "SpanLocator":
        if self.end < self.start:
            raise ValueError("span end precedes start")
        return self


# --------------------------------------------------------------------------
# Environment values (SYSTEM_SPEC §13; DATA_CONTRACTS §1.1)

ENVIRONMENT_GRAMMAR: dict[str, re.Pattern[str]] = {
    "os": re.compile(r"^(windows|linux|macos|other)$"),
    "arch": re.compile(r"^(x86_64|aarch64|other)$"),
    "python_version": re.compile(r"^[0-9A-Za-z.+!\-]{1,64}$"),
    "node_version": re.compile(r"^v?[0-9A-Za-z.+\-]{1,63}$"),
    "ci": re.compile(r"^(true|false|unknown)$"),
}


def _check_environment(values: dict[str, str]) -> dict[str, str]:
    for key, value in values.items():
        grammar = ENVIRONMENT_GRAMMAR.get(key)
        if grammar is None:
            raise ValueError(f"environment key {key!r} is not registered")
        if utf8_len(value) > 64 or not grammar.match(value):
            raise ValueError(f"environment value for {key!r} violates its registered grammar")
    return values


EnvironmentValues = Annotated[dict[str, str], AfterValidator(_check_environment)]


def filter_environment(raw: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, int]]:
    """Drop unregistered keys and disallowed values before durable capture.

    Returns the allowed map and a key/count-only coverage warning; rejected
    values are never echoed back.
    """
    kept: dict[str, str] = {}
    dropped: dict[str, int] = {}
    for key, value in raw.items():
        grammar = ENVIRONMENT_GRAMMAR.get(key)
        if grammar is not None and isinstance(value, str) and utf8_len(value) <= 64 and grammar.match(value):
            kept[key] = value
        else:
            label = key if grammar is not None else "<unregistered>"
            dropped[label] = dropped.get(label, 0) + 1
    return kept, dropped


# --------------------------------------------------------------------------
# Scope, conditions and evidence


class Scope(StrictModel):
    """Empty eligibility lists mean unrestricted within this installation.

    ``branch_refs`` are recall/origin annotations only, never eligibility.
    """

    workspace_ids: list[Id] = Field(default_factory=list)
    task_ids: list[Id] = Field(default_factory=list)
    branch_refs: list[Annotated[str, Field(min_length=1, max_length=256)]] = Field(default_factory=list)
    paths: list[PortablePath] = Field(default_factory=list)
    environment: EnvironmentValues = Field(default_factory=dict)


ConditionKind = Literal["action_kind", "tool", "path", "environment_equals", "version_range", "branch_ref"]
ACTION_KINDS = ("read", "write", "delete", "test", "build", "publish", "version_control", "other", "unknown")


class Condition(StrictModel):
    """Constrained, non-executable applicability predicate (SYSTEM_SPEC §7.4)."""

    kind: ConditionKind
    key: Annotated[str, Field(max_length=256)]
    value: Annotated[str, Field(max_length=512)]
    upper: Annotated[str, Field(max_length=128)] | None = None
    exclude: bool = False

    @model_validator(mode="after")
    def _shape(self) -> "Condition":
        if self.kind == "path":
            _check_portable_path(self.value)
        if self.kind == "environment_equals":
            _check_environment({self.key: self.value})
        if self.kind == "action_kind" and self.value not in ACTION_KINDS:
            raise ValueError("action_kind condition must use the registered vocabulary")
        if self.kind == "version_range":
            if self.key not in ("python_version", "node_version"):
                raise ValueError("version_range applies only to registered runtime version keys")
        elif self.upper is not None:
            raise ValueError("only version_range conditions take an upper bound")
        return self


MappingName = Literal["tool.exit_code", "tool.reported_result", "config.exact_value"]


class EvidenceLink(StrictModel):
    ref: RecordRef
    relation: Literal["supports", "contradicts", "context"]
    root_event_ids: list[Id] = Field(default_factory=list)
    locator: SpanLocator | None = None
    mapping: MappingName | None = None


Applicability = Literal["true", "false", "unknown"]

ReasonCode = Literal[
    "task_continuity",
    "exact_action_match",
    "dependency_match",
    "path_match",
    "lexical_match",
    "explicit_query",
    "conflict",
    "revision_change",
    "compaction_restore",
    "recent_observation",
    "tentative_context",
]
REASON_CODES: tuple[str, ...] = ReasonCode.__args__  # type: ignore[attr-defined]


class InstallationContext(StrictModel):
    """Resolved installation passed through every runtime API (no global lookup)."""

    project_id: Id
    installation_id: Id
    root: Path
    workspace_id: Id
    workspace_root: Path
    engine_version: Annotated[str, Field(min_length=1, max_length=64)]
    schema_version: Revision
    policy_revision: Revision
    actor: Actor


class DependencyRef(StrictModel):
    """A registered dependency; a null fingerprint never matches a current value."""

    kind: Literal["file", "config", "environment", "claim"]
    key: Annotated[str, Field(min_length=1, max_length=512)]
    fingerprint: Digest | None = None
    record: RecordRef | None = None

    @model_validator(mode="after")
    def _resolution(self) -> "DependencyRef":
        if self.kind == "file":
            _check_portable_path(self.key)
        if self.kind == "environment" and self.key not in ENVIRONMENT_GRAMMAR:
            raise ValueError("environment dependencies use registered EnvironmentValues keys")
        if (self.kind == "claim") != (self.record is not None):
            raise ValueError("claim dependencies (and only they) carry an exact RecordRef")
        if self.record is not None and self.record.kind != "claim":
            raise ValueError("claim dependency must reference a claim")
        return self


class ReadSet(StrictModel):
    """What a proposal consulted; rechecked before application (DATA_CONTRACTS §7.1)."""

    entity_revisions: list[RecordRef] = Field(default_factory=list)
    workspace_id: Id
    fingerprints: dict[Annotated[str, Field(min_length=1, max_length=512)], Digest] = Field(default_factory=dict)
    policy_revision: Revision
    tombstone_epoch: NonNegative
