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

CAPTURE = (
    SPOOL_TEMP_WRITE, SPOOL_FSYNC, SPOOL_RENAME, SPOOL_AFTER_RENAME, SPOOL_AFTER_PUBLISH,
    CURSOR_WRITE, CURSOR_AFTER_WRITE, INGEST_BEGIN, INGEST_BEFORE_COMMIT, INGEST_AFTER_COMMIT, INGEST_AFTER_UNLINK,
)
WORKER = (JOB_AFTER_LEASE, JOB_AFTER_RESERVE, JOB_AFTER_PROPOSAL, JOB_BEFORE_COMPLETE_COMMIT, JOB_AFTER_COMPLETE)
ALL = CAPTURE + WORKER
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
