"""Session-local scratch for the hook fast path (SYSTEM_SPEC §5.1.2).

``run/sessions/<session_id>.json`` holds bounded, scrubbed data only. Every
read-modify-write happens under a per-session OS lock acquired within at most
20 ms and the caller's remaining soft deadline, and the file is replaced
atomically; there is no unlocked read-modify-write. A lock timeout skips the
optional update and never affects durable capture, which has already finished
when the overlay runs. A platform without a supported lock primitive disables
the scratch capability instead of writing unlocked.

In capture-only builds (Task 3b) the only writer is the post-tool typed
outcome overlay: an outcome references the original event ID and the
normalized action, never a model paraphrase. Delivery entries, token
reservations and fences arrive with Task 12b.
"""

from __future__ import annotations

import json
import os
import time

from recalith.fast import redact
from recalith.fast.wire import LIMITS, canonical_json, validate

SESSIONS_DIR = ("run", "sessions")
LOCK_WAIT_SECONDS = LIMITS["SESSION_LOCK_WAIT_MS"] / 1000
MAX_OUTCOMES = LIMITS["SESSION_SCRATCH_OUTCOMES"]
SCRATCH_CAP = LIMITS["SESSION_SCRATCH_CAP"]
ABANDONED_SECONDS = 24 * 3600
PRUNE_BATCH = 16
_POLL_SECONDS = 0.001

try:  # POSIX
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - Windows
    _fcntl = None
try:  # Windows
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None


def sessions_dir(root) -> str:
    return os.path.join(os.fspath(root), ".recalith", *SESSIONS_DIR)


def scratch_path(root, session_id: str) -> str:
    return os.path.join(sessions_dir(root), f"{session_id}.json")


def locking_supported() -> bool:
    return _fcntl is not None or _msvcrt is not None


class SessionLock:
    """Exclusive per-session lock; ``acquire`` waits at most ``wait`` seconds."""

    def __init__(self, root, session_id: str) -> None:
        self.path = os.path.join(sessions_dir(root), f"{session_id}.lock")
        self.fd: int | None = None

    def acquire(self, wait: float) -> bool:
        directory = os.path.dirname(self.path)
        if not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
            if os.name != "nt":
                os.chmod(directory, 0o700)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
        give_up = time.monotonic() + max(0.0, wait)
        while True:
            try:
                if _fcntl is not None:
                    _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                else:
                    _msvcrt.locking(fd, _msvcrt.LK_NBLCK, 1)
                self.fd = fd
                return True
            except OSError:
                if time.monotonic() >= give_up:
                    os.close(fd)
                    return False
                time.sleep(_POLL_SECONDS)

    def release(self) -> None:
        if self.fd is None:
            return
        try:
            if _fcntl is not None:
                _fcntl.flock(self.fd, _fcntl.LOCK_UN)
            else:
                os.lseek(self.fd, 0, os.SEEK_SET)
                _msvcrt.locking(self.fd, _msvcrt.LK_UNLCK, 1)
        finally:
            os.close(self.fd)
            self.fd = None


def empty_scratch(session_id: str, policy_revision: int) -> dict:
    return {
        "scratch_schema": 1,
        "session_id": session_id,
        "state_revision": 0,
        "store_revision": 0,
        "guidance_epoch": 0,
        "policy_revision": policy_revision,
        "tombstone_epoch": 0,
        "reserved_tokens": 0,
        "emitted_tokens": 0,
        "outcomes": [],
        "entries": [],
    }


def read_scratch(root, session_id: str) -> dict | None:
    """The validated scratch, or None when absent or invalid (never trusted unvalidated)."""
    try:
        with open(scratch_path(root, session_id), "rb") as fh:
            data = json.loads(fh.read(SCRATCH_CAP + 1).decode("utf-8"))
    except (OSError, ValueError):
        return None
    errors, value = validate("SessionScratch", data)
    if errors or value["session_id"] != session_id:
        return None
    return value


def _write_atomic(path: str, data: bytes) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
    finally:
        os.close(fd)
    os.replace(tmp, path)


def outcome_from_envelope(envelope: dict) -> dict:
    """A typed outcome overlay entry: original event ID, action and coverage only."""
    payload = envelope["payload"]
    action = payload["action"]
    changed = list(action.get("paths") or []) if action.get("action_kind") in ("write", "delete") and payload["outcome"] == "success" else []
    outcome = {"event_id": envelope["event_id"], "action": action, "outcome": payload["outcome"], "changed_paths": changed, "coverage": dict(envelope["coverage"])}
    scrubbed, _ = redact.scrub_json(outcome)  # defense in depth: the envelope is already scrubbed
    return scrubbed


def record_outcome(root, session_id: str, outcome: dict, *, policy_revision: int, deadline: float) -> str:
    """Append one typed outcome under the session lock; returns a status code.

    ``updated``, or a content-free degradation: ``deadline_overlay_skipped``,
    ``scratch_lock_timeout``, ``scratch_lock_unsupported``, ``scratch_io_error``.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return "deadline_overlay_skipped"
    if not locking_supported():
        return "scratch_lock_unsupported"
    lock = SessionLock(root, session_id)
    try:
        if not lock.acquire(min(LOCK_WAIT_SECONDS, remaining)):
            return "scratch_lock_timeout"
        scratch = read_scratch(root, session_id) or empty_scratch(session_id, policy_revision)
        outcomes = [o for o in scratch["outcomes"] if o["event_id"] != outcome["event_id"]] + [outcome]
        scratch["outcomes"] = outcomes[-MAX_OUTCOMES:]
        scratch["state_revision"] += 1
        while scratch["outcomes"] and len(canonical_json(scratch)) > SCRATCH_CAP:
            scratch["outcomes"].pop(0)  # eviction never resets counters
        if validate("SessionScratch", scratch)[0]:
            return "scratch_io_error"
        _write_atomic(scratch_path(root, session_id), canonical_json(scratch))
        return "updated"
    except OSError:
        return "scratch_io_error"
    finally:
        lock.release()


def discard(root, session_id: str, *, deadline: float) -> str:
    """Remove a finished session's scratch under its lock (SessionEnd)."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return "deadline_overlay_skipped"
    if not locking_supported():
        return "scratch_lock_unsupported"
    lock = SessionLock(root, session_id)
    try:
        if not lock.acquire(min(LOCK_WAIT_SECONDS, remaining)):
            return "scratch_lock_timeout"
        try:
            os.unlink(scratch_path(root, session_id))
        except FileNotFoundError:
            pass
        return "discarded"
    except OSError:
        return "scratch_io_error"
    finally:
        # The lock file stays: unlinking it could let a waiter lock an orphaned inode.
        lock.release()


def prune_abandoned(root, *, now: float | None = None, limit: int = PRUNE_BATCH) -> int:
    """Delete at most ``limit`` scratch/lock files idle for more than 24 hours."""
    directory = sessions_dir(root)
    now = time.time() if now is None else now
    removed = 0
    try:
        names = os.listdir(directory)
    except OSError:
        return 0
    for name in names:
        if removed >= limit:
            break
        if not name.endswith((".json", ".lock")):
            continue
        path = os.path.join(directory, name)
        try:
            if now - os.stat(path).st_mtime > ABANDONED_SECONDS:
                os.unlink(path)
                removed += 1
        except OSError:
            continue
    return removed
