"""``capture`` and ``ingest_ready`` (DATA_CONTRACTS §11; SYSTEM_SPEC §5.1).

``capture`` re-checks every envelope (ownership, derived identity, scrubbing,
environment allowlist), packs bounded segments, publishes them durably and
only then acknowledges and advances source cursors. It never opens the store,
so the same sequence is valid on the hook path. Operational failures return a
``not_captured`` receipt; nothing is raised to the host.

``ingest_ready`` commits each segment's events, environment observations,
cursor proposals and follow-on ``ingest`` job in one transaction, then removes
the segment. A crash after commit but before removal replays harmlessly: the
events are duplicates and the job's idempotency key already exists.

``ingest_ready``'s ``limit`` bounds the number of *segments* handled in one
call (a segment is never split across transactions).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Iterable, Mapping, Sequence

from pydantic import ValidationError

from recalith.capture import provenance, redact, sources
from recalith.capture.normalize import Notes, digest_of_text, sanitize_payload
from recalith.contracts.common import InstallationContext, RecordRef, canonical_json, derived_id, digest_of, new_id, utc_now
from recalith.contracts.config import HOOK_SOFT_DEADLINE_MS, SEGMENT_CAP
from recalith.contracts.events import TOOL_KINDS, CaptureReceipt, EventEnvelope, Segment
from recalith.contracts.jobs import IngestResult
from recalith.errors import RecalithError
from recalith.storage import failpoints, repository, spool
from recalith.storage.db import open_store

SEGMENT_MARGIN = 4 * 1024
QUARANTINE_CODES = frozenset({"foreign_installation", "event_identity_conflict", "invalid_schema"})


def _not_captured(reason: str, *, error_code: str = "not_captured", **coverage: Any) -> CaptureReceipt:
    return CaptureReceipt(status="not_captured", segment_id=None, event_ids=[], coverage={"reason": reason, **coverage}, error_code=error_code)


def _identity_clean(env: EventEnvelope) -> bool:
    fields = (env.source_event_key, env.host_session_id, env.adapter_version, env.origin.source_event_key, env.origin.host_session_id, env.origin.locator or "")
    return not any(redact.contains_secret(v) for v in fields)


def _rescrub(env: EventEnvelope, warnings: dict[str, int]) -> EventEnvelope:
    """Defensive re-sanitation; a no-op for envelopes built by ``normalize_event``."""
    notes = Notes()
    data = env.model_dump(mode="json")
    payload = sanitize_payload(env.kind, data["payload"], notes)
    if env.kind in TOOL_KINDS and isinstance(payload.get("text_chunks"), list):
        kept = [c for c in payload["text_chunks"] if isinstance(c, dict) and isinstance(c.get("text"), str) and digest_of_text(c["text"]) == c.get("text_digest")]
        if len(kept) != len(payload["text_chunks"]):
            notes.missing_context = True
            notes.warn("chunk_dropped_after_scrub", len(payload["text_chunks"]) - len(kept))
            payload["text_chunks"] = kept
    extensions = sanitize_payload("extensions", data["extensions"], notes) if data["extensions"] else {}
    for code, n in notes.warnings.items():
        warnings[code] = warnings.get(code, 0) + n
    if payload == data["payload"] and extensions == data["extensions"]:
        return env
    data["payload"], data["payload_digest"], data["extensions"] = payload, digest_of(payload), extensions
    coverage = dict(data["coverage"])
    coverage["redacted"] = coverage["redacted"] or notes.redacted
    coverage["missing_context"] = coverage["missing_context"] or notes.missing_context
    data["coverage"] = coverage
    try:
        return EventEnvelope.model_validate(data)
    except ValidationError:
        raise RecalithError("invalid_schema", "envelope is invalid after scrubbing") from None


def _pack(envelopes: list[dict[str, Any]], proposals: list[dict[str, Any]]) -> list[tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """Group envelopes into ≤256 KiB segments; cursor proposals ride in the last one."""
    budget = SEGMENT_CAP - SEGMENT_MARGIN - len(canonical_json(proposals))
    groups: list[list[dict[str, Any]]] = [[]]
    used = 0
    for env in envelopes:
        size = len(canonical_json(env)) + 1
        if groups[-1] and used + size > budget:
            groups.append([])
            used = 0
        groups[-1].append(env)
        used += size
    return [(group, proposals if index == len(groups) - 1 else []) for index, group in enumerate(groups)]


def capture(
    ctx: InstallationContext,
    events: Sequence[EventEnvelope],
    *,
    cursor_proposals: Iterable[Mapping[str, Any]] = (),
    deadline: float | None = None,
    platform: str = os.name,
) -> CaptureReceipt:
    """Durably spool normalized events; acknowledge only after publication."""
    deadline = time.monotonic() + HOOK_SOFT_DEADLINE_MS / 1000 if deadline is None else deadline
    dirs = spool.SpoolDirs(ctx.root)
    proposals = [{"source_id": p["source_id"], "cursor": dict(p["cursor"])} for p in cursor_proposals]
    warnings: dict[str, int] = {}
    rejected: dict[str, int] = {}
    accepted: list[EventEnvelope] = []
    for env in events:
        if env.installation_id != ctx.installation_id or env.project_id != ctx.project_id or env.workspace_id != ctx.workspace_id:
            return _not_captured("foreign_installation", error_code="foreign_installation")
        if env.event_id != derived_id("evt", [ctx.installation_id, env.adapter_id, env.source_event_key]):
            return _not_captured("event_identity_conflict", error_code="event_identity_conflict")
        if not _identity_clean(env):
            rejected["policy_refused"] = rejected.get("policy_refused", 0) + 1
            continue
        try:
            accepted.append(_rescrub(env, warnings))
        except RecalithError as exc:
            rejected[exc.code] = rejected.get(exc.code, 0) + 1
    if not accepted:
        error = "policy_refused" if rejected.get("policy_refused") else "invalid_schema"
        return _not_captured("no_capturable_events", error_code=error, rejected=rejected)
    groups = _pack([e.model_dump(mode="json") for e in accepted], proposals)
    segment_ids: list[str] = []
    rename_retried = overrun = False
    dir_synced = True
    for envelopes, segment_proposals in groups:
        segment_id = new_id("seg")
        created_at = utc_now()
        try:
            segment = Segment.model_validate(
                {
                    "segment_schema": 1,
                    "segment_id": segment_id,
                    "project_id": ctx.project_id,
                    "installation_id": ctx.installation_id,
                    "envelopes": envelopes,
                    "cursor_proposals": segment_proposals,
                    "created_at": created_at,
                    "content_digest": digest_of(spool.segment_body(envelopes, segment_proposals)),
                }
            )
        except ValidationError:
            return _not_captured("segment_invalid", error_code="invalid_schema")
        outcome = spool.publish(dirs, spool.segment_file_name(created_at, segment_id), canonical_json(segment), deadline=deadline, platform=platform)
        if not outcome.ok:
            spool.record_gap(dirs, code="not_captured", reason=outcome.reason or "io_error", event_count=len(accepted), at=utc_now(), source_ids=[p["source_id"] for p in proposals])
            # Earlier segments of this call may be durable; they replay harmlessly and are not acknowledged.
            return _not_captured(outcome.reason or "io_error", published_unacknowledged=len(segment_ids), rename_retried=outcome.rename_retried)
        segment_ids.append(segment_id)
        rename_retried = rename_retried or outcome.rename_retried
        overrun = overrun or outcome.deadline_overrun
        dir_synced = dir_synced and outcome.dir_synced
    failpoints.hit(failpoints.SPOOL_AFTER_PUBLISH)
    cursors_persisted = all(spool.write_cursor(dirs, p["source_id"], p["cursor"]) for p in proposals)
    coverage: dict[str, Any] = {"segment_ids": segment_ids, "dir_synced": dir_synced, "cursors_persisted": cursors_persisted}
    if rejected:
        coverage["rejected"] = rejected
    if warnings:
        coverage["warnings"] = dict(sorted(warnings.items()))
    if rename_retried:
        coverage["rename_retried"] = True
    if overrun or time.monotonic() > deadline:
        coverage["degraded"] = ["capture_deadline_overrun"]
    return CaptureReceipt(status="accepted", segment_id=segment_ids[-1], event_ids=[e.event_id for e in accepted], coverage=coverage, error_code=None)


def recover_source(ctx: InstallationContext, source_id: str, parse_line: sources.LineParser) -> tuple[CaptureReceipt | None, sources.TailRead]:
    """Read a registered source's unprocessed tail and capture it with its cursor."""
    with open_store(ctx, readonly=True) as store:
        registration = sources.get_source(store, source_id)
        if registration is None:
            raise RecalithError("policy_refused", "only registered sources are recovered")
        cursor = sources.current_cursor(store, ctx, source_id)
    tail = sources.read_tail(ctx, registration, cursor, parse_line)
    dirs = spool.SpoolDirs(ctx.root)
    for code, count in tail.gaps.items():
        spool.record_gap(dirs, code=code, reason="source_coverage", event_count=count, at=utc_now(), source_ids=[source_id])
    if tail.events:
        return capture(ctx, tail.events, cursor_proposals=[{"source_id": source_id, "cursor": tail.cursor}]), tail
    if tail.advanced:
        spool.write_cursor(dirs, source_id, tail.cursor)  # only skipped/blank records: nothing to publish
    return None, tail


# --------------------------------------------------------------------------
# Ingestion


def _session_lifecycle(txn: Any, env: EventEnvelope) -> None:
    if env.kind == "session_ended":
        txn.execute("UPDATE sessions SET state = 'ended', ended_at = ? WHERE session_id = ? AND state != 'ended'", (env.occurred_at or env.recorded_at, env.session_id))


def ingest_ready(ctx: InstallationContext, *, limit: int = 100) -> IngestResult:
    """Commit ready segments to the store, then remove them."""
    dirs = spool.SpoolDirs(ctx.root)
    spool.cleanup_stale_temps(dirs)
    accepted = duplicate = conflict = 0
    created_jobs: list[str] = []
    with open_store(ctx) as store:
        for path in spool.ready_segments(dirs)[:limit]:
            try:
                segment = Segment.model_validate(json.loads(path.read_bytes().decode("utf-8")))
            except FileNotFoundError:
                continue  # removed by a concurrent ingestion
            except (OSError, UnicodeDecodeError, ValueError):
                spool.quarantine_segment(dirs, path, "invalid")
                spool.record_gap(dirs, code="segment_quarantined", reason="invalid", event_count=0, at=utc_now())
                continue
            if segment.installation_id != ctx.installation_id or segment.project_id != ctx.project_id:
                spool.quarantine_segment(dirs, path, "foreign")
                spool.record_gap(dirs, code="segment_quarantined", reason="foreign_installation", event_count=len(segment.envelopes), at=utc_now())
                continue
            counts = {"inserted": 0, "duplicate": 0, "conflict": 0}
            try:
                with store.transaction() as txn:
                    failpoints.hit(failpoints.INGEST_BEGIN)
                    inserted: list[EventEnvelope] = []
                    for env in segment.envelopes:
                        sources.ensure_session(txn, ctx, session_id=env.session_id, adapter_id=env.adapter_id, host_session_id=env.host_session_id, started_at=env.occurred_at)
                        outcome, _ = repository.insert_event(txn, ctx, env)
                        counts[outcome] += 1
                        if outcome == "inserted":
                            inserted.append(env)
                            provenance.observe_event(txn, ctx, env)
                            _session_lifecycle(txn, env)
                    for proposal in segment.cursor_proposals:
                        sources.apply_cursor(txn, proposal.source_id, proposal.cursor)
                    job_id = None
                    if inserted:
                        refs = [RecordRef(kind="event", id=e.event_id, revision=1) for e in inserted]
                        job_id, created = repository.enqueue_job(txn, kind="ingest", input_refs=refs)
                        job_id = job_id if created else None
                    failpoints.hit(failpoints.INGEST_BEFORE_COMMIT)
            except RecalithError as exc:
                if exc.code not in QUARANTINE_CODES:
                    raise  # storage failure: leave the segment for a later attempt
                spool.quarantine_segment(dirs, path, exc.code)
                spool.record_gap(dirs, code="segment_quarantined", reason=exc.code, event_count=len(segment.envelopes), at=utc_now())
                continue
            failpoints.hit(failpoints.INGEST_AFTER_COMMIT)
            spool.remove_segment(dirs, path)
            failpoints.hit(failpoints.INGEST_AFTER_UNLINK)
            accepted += counts["inserted"]
            duplicate += counts["duplicate"]
            conflict += counts["conflict"]
            if job_id:
                created_jobs.append(job_id)
        last_revision = store.meta().store_revision
    return IngestResult(accepted=accepted, duplicate=duplicate, conflict=conflict, last_store_revision=last_revision, created_job_ids=created_jobs)


# --------------------------------------------------------------------------
# Health inputs (Task 17 composes these into HealthReport)


def capture_health(ctx: InstallationContext) -> dict[str, Any]:
    """Content-free capture state: backlog, gaps, quarantine and unresolved conflicts."""
    dirs = spool.SpoolDirs(ctx.root)
    ready = spool.ready_segments(dirs)
    gaps: dict[str, int] = {}
    for record in spool.read_gaps(dirs):
        label = f"{record['code']}:{record['reason']}"
        gaps[label] = gaps.get(label, 0) + int(record.get("event_count") or 1)
    quarantined = sum(1 for _ in dirs.quarantine.iterdir()) if dirs.quarantine.is_dir() else 0
    with open_store(ctx, readonly=True) as store, store.read() as view:
        conflicts = [r[0] for r in view.execute("SELECT conflict_id FROM source_conflicts WHERE state = 'unresolved' ORDER BY first_seen_at, conflict_id").fetchall()]
    oldest = min((p.stat().st_mtime for p in ready), default=None)
    return {
        "ready_segments": len(ready),
        "oldest_ready_age_seconds": None if oldest is None else max(0.0, time.time() - oldest),
        "gaps": gaps,
        "quarantined_segments": quarantined,
        "unresolved_conflicts": conflicts,
    }
