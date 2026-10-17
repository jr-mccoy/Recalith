"""Deterministic failpoints for the failure-injection protocol (ACCEPTANCE_TESTS §4).

Production code calls :func:`hit` at named points around spool temp write,
flush, rename, cursor advance, database begin/commit, job lease, budget
reservation, proposal persistence and job completion. Nothing is armed
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

CAPTURE = (
    SPOOL_TEMP_WRITE, SPOOL_FSYNC, SPOOL_RENAME, SPOOL_AFTER_RENAME, SPOOL_AFTER_PUBLISH,
    CURSOR_WRITE, CURSOR_AFTER_WRITE, INGEST_BEGIN, INGEST_BEFORE_COMMIT, INGEST_AFTER_COMMIT, INGEST_AFTER_UNLINK,
)
WORKER = (JOB_AFTER_LEASE, JOB_AFTER_RESERVE, PROPOSAL_BEFORE_COMMIT, JOB_AFTER_PROPOSAL, APPLY_AFTER_GROUP, JOB_BEFORE_COMPLETE_COMMIT, JOB_AFTER_COMPLETE)
SERVICE = (SERVICE_BEFORE_COMMIT,)
REDUCTION = (REDUCE_AFTER_APPLY, BINDING_AFTER_REBIND)
PROVIDER = (REQUEST_AFTER_BATCH, PROVIDER_AFTER_SPAWN)
LINEAGE = (ROOTS_AFTER_MERGE,)
ALL = CAPTURE + WORKER + SERVICE + REDUCTION + PROVIDER + LINEAGE
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
