"""Deterministic failpoints for the failure-injection protocol (ACCEPTANCE_TESTS §4).

Production code calls :func:`hit` at named points around spool temp write,
flush, rename, cursor advance, database begin/commit, job lease, budget
reservation, proposal persistence, job completion, retention expiry,
backup completion, forgetting, restore and host integration. Nothing is armed
unless a test calls :func:`arm` in its own process; there is no environment
variable, flag or configuration that arms a failpoint, so this is not a
switch an agent or operator can flip.

Standard library only.
"""

from __future__ import annotations

import errno as _errno
import os

SPOOL_TEMP_WRITE = "spool.temp_write"
SPOOL_FSYNC = "spool.fsync"
SPOOL_RENAME = "spool.rename"
SPOOL_AFTER_RENAME = "spool.after_rename"
SPOOL_AFTER_PUBLISH = "spool.after_publish"  # durable, acknowledged, cursor not yet written
CURSOR_WRITE = "cursor.write"
CURSOR_AFTER_WRITE = "cursor.after_write"
INGEST_BEGIN = "ingest.begin"
INGEST_BEFORE_COMMIT = "ingest.before_commit"
INGEST_AFTER_COMMIT = "ingest.after_commit"  # committed, segment not yet removed
INGEST_AFTER_UNLINK = "ingest.after_unlink"
# Worker boundaries (Task 4): committed lease, committed reservation (before the
# provider launch), committed proposal (before application), the fenced
# completion transaction before and after commit.
JOB_AFTER_LEASE = "job.after_lease"
JOB_AFTER_RESERVE = "job.after_reserve"
JOB_AFTER_PROPOSAL = "job.after_proposal"
JOB_BEFORE_COMPLETE_COMMIT = "job.before_complete_commit"
JOB_AFTER_COMPLETE = "job.after_complete"
# Mutation application (Task 5): inside the proposal-persistence transaction
# before its commit; inside the application transaction after the first atomic
# group's savepoint is released (later groups and job completion still pending);
# inside a service writer's (or undo's) transaction before its commit.
PROPOSAL_BEFORE_COMMIT = "proposal.before_commit"
APPLY_AFTER_GROUP = "apply.after_group"
SERVICE_BEFORE_COMMIT = "service.before_commit"
# Guarded operator service (Task 12a): inside a declaration/correction
# transaction after its operator event was inserted (application, review
# scheduling and commit pending); after that transaction committed (the result
# not yet reported to the caller); inside ``init`` after the new store was
# renamed into place, before ``local.toml`` (with any operator-token verifier)
# marks the installation complete.
SERVICE_AFTER_EVENT = "service.after_event"
SERVICE_AFTER_COMMIT = "service.after_commit"
INIT_AFTER_STORE = "init.after_store"
# Typed reduction and binding application (Task 6): inside an ingest job's
# fenced transaction after the reducer's first application (bindings and
# typed facts written, later passes, episodes and job completion pending);
# inside a binding resolution after the range is rebound and before the task
# revisions and bookkeeping that complete it.
REDUCE_AFTER_APPLY = "reduce.after_apply"
BINDING_AFTER_REBIND = "binding.after_rebind"

# Provider path (Task 7): after a review batch snapshot is committed (before any
# reservation); after a curator child is spawned and its spawn record written
# (the call is in flight, nothing is charged yet).
REQUEST_AFTER_BATCH = "request.after_batch"
PROVIDER_AFTER_SPAWN = "provider.after_spawn"
# Evidence lineage (Task 8): inside the ingestion transaction after a root-class
# merge has moved members, tokens and aliases to the surviving class, before
# the affected claims' revalidation is enqueued and the segment commits.
ROOTS_AFTER_MERGE = "roots.after_merge"
# Claim admission (Task 9): inside an extraction's application transaction after
# its new candidates' review jobs are enqueued (job completion pending); inside a
# review job's application after the first assessment is applied (later
# assessments, outcome records and completion pending); inside an ingest job's
# fenced transaction after the failure-trigger pass advanced its cursor.
REVIEW_AFTER_SCHEDULE = "review.after_schedule"
REVIEW_AFTER_ASSESSMENT = "review.after_assessment"
TRIGGERS_AFTER_PASS = "triggers.after_pass"
# Revision (Task 10): inside the ingestion transaction after a FailureRecheck or a
# dependency change wrote a claim's needs_revalidation revision (its recheck row,
# the transitive dependents, the revalidation job and the segment commit
# pending); inside a revalidation job's application after its claims' rechecks
# are settled (outcomes, review scheduling and job completion pending); inside
# the planner's transaction after it settled or scheduled work (before commit).
RECHECK_AFTER_MARK = "recheck.after_mark"
REVALIDATE_AFTER_SETTLE = "revalidate.after_settle"
PLANNER_AFTER_SCHEDULE = "planner.after_schedule"

# Task 11 (decision 0013): inside the projection step's index transaction after
# the lexical/structural rows and the covered store revision are written
# (commit pending); inside the view publication transaction after the views and
# their epochs are written (commit pending); after that publication committed.
INDEX_AFTER_REFRESH = "index.after_refresh"
VIEWS_BEFORE_COMMIT = "views.before_commit"
VIEWS_AFTER_PUBLISH = "views.after_publish"

# Delivery (Task 12b, decision 0015), all inside the hook while it holds the
# session lock: the reservation is written to scratch (fence, stdout, receipt
# and mark pending); the final fence held (stdout pending); stdout was written
# and flushed (receipt and mark pending); the emitted receipt was spooled (the
# scratch mark pending); the scratch entry is marked emitted (lock release
# pending).
DELIVERY_AFTER_RESERVE = "delivery.after_reserve"
DELIVERY_AFTER_FENCE = "delivery.after_fence"
DELIVERY_AFTER_EMIT = "delivery.after_emit"
DELIVERY_AFTER_RECEIPT = "delivery.after_receipt"
DELIVERY_AFTER_MARK = "delivery.after_mark"

# Retention (Task 15 core, decision 0016): after a sweep selected its age-eligible
# candidates in a read snapshot (the expiry transaction and its in-transaction pin
# recheck pending); inside the expiry transaction after the payloads were dropped
# and the audit written (commit pending); after that commit.
RETENTION_AFTER_SELECT = "retention.after_select"
RETENTION_BEFORE_COMMIT = "retention.before_commit"
RETENTION_AFTER_COMMIT = "retention.after_commit"
# Backup (Task 15 core): the snapshot was copied into the staging directory (ledger,
# manifest and verification pending); the manifest was written (verification and
# publication pending); the verified staging directory was renamed to the output
# (the ``backups`` row and the latest ledger copy pending); the row committed (the
# latest ledger copy and the journal removal pending); an aged backup's files were
# deleted (its row still says ``verified``).
BACKUP_AFTER_SNAPSHOT = "backup.after_snapshot"
BACKUP_AFTER_MANIFEST = "backup.after_manifest"
BACKUP_AFTER_PUBLISH = "backup.after_publish"
BACKUP_AFTER_RECORD = "backup.after_record"
BACKUP_AFTER_PRUNE = "backup.after_prune"
# Forgetting (Task 16, decision 0017): the maintenance marker is written (delivery
# paused; the purge transaction pending); inside the purge transaction after the
# tombstone, the purge and the persisted privacy operation are written (commit
# pending); after that commit (file cleanup, ledger, backup, deletions and
# reconstruction pending); after the external files were cleaned; after the
# latest ledger copy was written; after the post-forget backup (verified or
# failed) was recorded in the operation; after the affected older backups were
# deleted; after the reconstruction jobs were queued (completion pending).
FORGET_AFTER_MARKER = "forget.after_marker"
FORGET_BEFORE_COMMIT = "forget.before_commit"
FORGET_AFTER_COMMIT = "forget.after_commit"
FORGET_AFTER_FILES = "forget.after_files"
FORGET_AFTER_LEDGER = "forget.after_ledger"
FORGET_AFTER_BACKUP = "forget.after_backup"
FORGET_AFTER_DELETE = "forget.after_delete"
FORGET_AFTER_RECONSTRUCT = "forget.after_reconstruct"
# Restore (Task 16): the staged copy of the snapshot exists (suppression pending);
# inside the staged store's transaction after the newer tombstones were applied
# (commit pending); the staged store is complete and the journal says so (the
# swap pending); the staged store replaced the live one (file cleanup, ledger
# and backup policy pending).
RESTORE_AFTER_STAGE = "restore.after_stage"
RESTORE_BEFORE_COMMIT = "restore.before_commit"
RESTORE_BEFORE_SWAP = "restore.before_swap"
RESTORE_AFTER_SWAP = "restore.after_swap"
# Host integration (Task 13, decision 0019): the ``installing`` ownership record
# is written (settings, ignore line, hook manifest and the final record pending);
# the host settings file is written; the owned ignore line is written; the hook
# manifest is written (the final ``installed`` record pending). Removal: the
# settings are restored (manifest, ignore line and record removal pending); the
# hook manifest is removed; the ignore line is removed (the record pending).
INTEGRATE_AFTER_RECORD = "integrate.after_record"
INTEGRATE_AFTER_SETTINGS = "integrate.after_settings"
INTEGRATE_AFTER_IGNORE = "integrate.after_ignore"
INTEGRATE_AFTER_MANIFEST = "integrate.after_manifest"
REMOVE_AFTER_SETTINGS = "integrate.remove_after_settings"
REMOVE_AFTER_MANIFEST = "integrate.remove_after_manifest"
REMOVE_AFTER_IGNORE = "integrate.remove_after_ignore"

CAPTURE = (
    SPOOL_TEMP_WRITE, SPOOL_FSYNC, SPOOL_RENAME, SPOOL_AFTER_RENAME, SPOOL_AFTER_PUBLISH,
    CURSOR_WRITE, CURSOR_AFTER_WRITE, INGEST_BEGIN, INGEST_BEFORE_COMMIT, INGEST_AFTER_COMMIT, INGEST_AFTER_UNLINK,
)
WORKER = (JOB_AFTER_LEASE, JOB_AFTER_RESERVE, PROPOSAL_BEFORE_COMMIT, JOB_AFTER_PROPOSAL, APPLY_AFTER_GROUP, JOB_BEFORE_COMPLETE_COMMIT, JOB_AFTER_COMPLETE)
SERVICE = (SERVICE_AFTER_EVENT, SERVICE_BEFORE_COMMIT, SERVICE_AFTER_COMMIT, INIT_AFTER_STORE)
REDUCTION = (REDUCE_AFTER_APPLY, BINDING_AFTER_REBIND)
PROVIDER = (REQUEST_AFTER_BATCH, PROVIDER_AFTER_SPAWN)
LINEAGE = (ROOTS_AFTER_MERGE,)
ADMISSION = (REVIEW_AFTER_SCHEDULE, REVIEW_AFTER_ASSESSMENT, TRIGGERS_AFTER_PASS)
REVISION = (RECHECK_AFTER_MARK, REVALIDATE_AFTER_SETTLE, PLANNER_AFTER_SCHEDULE)
RETRIEVAL = (INDEX_AFTER_REFRESH, VIEWS_BEFORE_COMMIT, VIEWS_AFTER_PUBLISH)
DELIVERY = (DELIVERY_AFTER_RESERVE, DELIVERY_AFTER_FENCE, DELIVERY_AFTER_EMIT, DELIVERY_AFTER_RECEIPT, DELIVERY_AFTER_MARK)
RETENTION = (RETENTION_AFTER_SELECT, RETENTION_BEFORE_COMMIT, RETENTION_AFTER_COMMIT)
BACKUP = (BACKUP_AFTER_SNAPSHOT, BACKUP_AFTER_MANIFEST, BACKUP_AFTER_PUBLISH, BACKUP_AFTER_RECORD, BACKUP_AFTER_PRUNE)
FORGET = (FORGET_AFTER_MARKER, FORGET_BEFORE_COMMIT, FORGET_AFTER_COMMIT, FORGET_AFTER_FILES, FORGET_AFTER_LEDGER, FORGET_AFTER_BACKUP, FORGET_AFTER_DELETE, FORGET_AFTER_RECONSTRUCT)
RESTORE = (RESTORE_AFTER_STAGE, RESTORE_BEFORE_COMMIT, RESTORE_BEFORE_SWAP, RESTORE_AFTER_SWAP)
INTEGRATION = (INTEGRATE_AFTER_RECORD, INTEGRATE_AFTER_SETTINGS, INTEGRATE_AFTER_IGNORE, INTEGRATE_AFTER_MANIFEST, REMOVE_AFTER_SETTINGS, REMOVE_AFTER_MANIFEST, REMOVE_AFTER_IGNORE)
ALL = CAPTURE + WORKER + SERVICE + REDUCTION + PROVIDER + LINEAGE + ADMISSION + REVISION + RETRIEVAL + DELIVERY + RETENTION + BACKUP + FORGET + RESTORE + INTEGRATION
KILL_STATUS = 137

if False:  # annotations only: importing typing costs hook startup time (SYSTEM_SPEC §5.1.1)
    from typing import Callable

    Action = Callable[[str], None]  # called with the failpoint name
_armed: dict[str, tuple[Action, int, int]] = {}


def kill(name: str) -> None:
    """Abrupt process death: no cleanup handlers, buffers or finally blocks run."""
    os._exit(KILL_STATUS)


def raise_errno(code: int, *, winerror: int | None = None) -> Action:
    def action(name: str) -> None:
        exc = OSError(code, os.strerror(code))
        if winerror is not None:
            exc.winerror = winerror  # type: ignore[attr-defined]
        raise exc

    return action


DISK_FULL = raise_errno(_errno.ENOSPC)
PERMISSION_DENIED = raise_errno(_errno.EACCES)


def arm(name: str, action: Action = kill, *, times: int = 1, skip: int = 0) -> None:
    """Run ``action`` on the next ``times`` hits of ``name`` after ``skip`` passing hits."""
    if name not in ALL:
        raise ValueError(f"unknown failpoint {name!r}")
    _armed[name] = (action, times, skip)


def disarm_all() -> None:
    _armed.clear()


def hit(name: str) -> None:
    entry = _armed.get(name)
    if entry is None:
        return
    action, times, skip = entry
    if skip > 0:
        _armed[name] = (action, times, skip - 1)
        return
    if times <= 1:
        del _armed[name]
    else:
        _armed[name] = (action, times - 1, 0)
    action(name)
