"""Strict normalization: the shared stdlib core plus Pydantic validation.

The normalization rules live in :mod:`recalith.fast.normalize` so the hook fast
path and the worker/service path run one implementation (decision 0005). This
module validates that core's envelope dicts into strict ``EventEnvelope``
models and translates fast-path errors into :class:`RecalithError`. Read the
core module for the ordering, bounding, parser and partitioning rules.
"""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import ValidationError

from recalith.contracts.common import InstallationContext, digest_of
from recalith.contracts.events import ActionDescriptor, EventEnvelope
from recalith.errors import RecalithError
from recalith.fast.normalize import (  # noqa: F401 - re-exported for worker/service callers
    CERTIFIED_ROUTING,
    MESSAGE_KINDS,
    PLATFORM_ENVIRONMENT_KINDS,
    RUNTIME_KEYS,
    TOOL_FIELDS,
    UNTRUSTED_TOOL_FIELDS,
    BoundedText,
    Notes,
    RawEvent,
    bound_text,
    clean_unicode,
    normalize_raw,
    normalize_tool_payload,
    omission_marker,
    platform_environment,
    routing,
    sanitize_payload,
)
from recalith.fast.wire import WireError, digest_of_text  # noqa: F401


def action_family_digest(workspace_id: str, action: ActionDescriptor | Mapping[str, Any]) -> str | None:
    """DATA_CONTRACTS §8: workspace + cwd + tool + executable + ordered argv, or null."""
    a = action.model_dump(mode="json") if isinstance(action, ActionDescriptor) else dict(action)
    if a.get("parse_status") != "exact" or a.get("cwd_path") is None or a.get("argv") is None:
        return None
    return digest_of([workspace_id, a["cwd_path"], a["tool"], a.get("executable"), a["argv"]])


def _validate(data: dict[str, Any]) -> EventEnvelope:
    try:
        return EventEnvelope.model_validate(data)
    except ValidationError as exc:
        locations = sorted({".".join(str(p) for p in err["loc"]) for err in exc.errors()})[:8]
        raise RecalithError("invalid_schema", f"normalized event failed validation at {locations}") from None


def normalize_event(ctx: InstallationContext, raw: RawEvent) -> tuple[list[EventEnvelope], Notes]:
    """One adapter event → one strict envelope (or linked parts) plus coverage notes."""
    ids = {"project_id": ctx.project_id, "installation_id": ctx.installation_id, "workspace_id": ctx.workspace_id}
    try:
        envelopes, notes = normalize_raw(ids, raw)
    except WireError as exc:
        raise RecalithError(exc.code, exc.message) from None
    return [_validate(env) for env in envelopes], notes
