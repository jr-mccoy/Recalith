"""Durable capture spool: the durability boundary before ingestion (SYSTEM_SPEC §5.1).

Publication order: write a private temp segment in ``spool/tmp/``, flush and
fsync it, atomically rename it into ``spool/ready/`` and synchronize the
directory where the platform supports it. Only then is capture acknowledged,
and only after that is a source cursor advanced (``spool/cursors/``). A crash
before the rename leaves an unacknowledged temp file that is never ingested;
a crash after it leaves a segment whose replay is harmless because event
identity deduplicates it.

Platform notes (documented limits, not guarantees):

* POSIX: file ``fsync`` plus a directory ``fsync`` after rename and unlink.
  On macOS ``F_FULLFSYNC`` is used when available, because plain ``fsync``
  does not flush the drive cache there.
* Windows: ``os.replace`` (MoveFileEx) is atomic on NTFS, but directories
  cannot be opened for ``fsync``; directory-entry durability relies on NTFS
  metadata journaling. Antivirus/indexer sharing violations get exactly one
  retry after at most 20 ms within the remaining soft deadline.
* Power loss on hardware that ignores flushes can still lose acknowledged
  data; the spool cannot detect that.

Standard library only (the Task 3b hook fast path reuses this module).
"""

from __future__ import annotations

import errno
import json
import os
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from recalith.storage import failpoints

SPOOL_DIR = "spool"
SEGMENT_SUFFIX = ".seg.json"
TRANSIENT_WINERRORS = frozenset({5, 32, 33})  # access denied, sharing violation, lock violation
RENAME_RETRY_MAX_SECONDS = 0.020
STALE_TEMP_SECONDS = 300
MAX_GAP_FILES = 1000

_DISK_FULL = frozenset({errno.ENOSPC, errno.EFBIG} | ({errno.EDQUOT} if hasattr(errno, "EDQUOT") else set()))
_PERMISSION = frozenset({errno.EACCES, errno.EPERM, errno.EROFS})


def canonical_bytes(value: Any) -> bytes:
    """Canonical UTF-8 JSON (sorted keys, no whitespace, finite numbers only)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def segment_body(envelopes: list[dict[str, Any]], cursor_proposals: list[dict[str, Any]]) -> dict[str, Any]:
    """The digested part of a segment (DATA_CONTRACTS §2.2)."""
    return {"envelopes": envelopes, "cursor_proposals": cursor_proposals}


def segment_file_name(created_at: str, segment_id: str) -> str:
    """Ready-queue order is creation time, then segment ID."""
    compact = created_at.replace("-", "").replace(":", "").replace(".", "")
    return f"{compact}-{segment_id}{SEGMENT_SUFFIX}"


class SpoolDirs:
    """The spool layout of one installation (``<root>/.recalith/spool``)."""

    def __init__(self, installation_root: Path | str) -> None:
        self.base = Path(installation_root) / ".recalith" / SPOOL_DIR
        self.tmp = self.base / "tmp"
        self.ready = self.base / "ready"
        self.cursors = self.base / "cursors"
        self.gaps = self.base / "gaps"
        self.quarantine = self.base / "quarantine"

    def ensure(self) -> None:
        """Create missing private directories; existing modes are left as found."""
        for path in (self.base, self.tmp, self.ready, self.cursors, self.gaps, self.quarantine):
            if not path.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                if os.name != "nt":
                    os.chmod(path, 0o700)


# --------------------------------------------------------------------------
# Low-level durability primitives


def full_fsync(fd: int) -> None:
    if sys.platform == "darwin":
        import fcntl

        if hasattr(fcntl, "F_FULLFSYNC"):
            try:
                fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
                return
            except OSError:
                pass
    os.fsync(fd)


def fsync_dir(path: Path) -> bool:
    """Synchronize a directory entry; False where the platform cannot."""
    if os.name == "nt":
        return False
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno in (errno.EINVAL, errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)):
                return False
            raise
    finally:
        os.close(fd)
    return True


def classify(exc: BaseException) -> str:
    """Content-free failure reason for receipts, gaps and health."""
    if isinstance(exc, OSError):
        if exc.errno in _DISK_FULL:
            return "disk_full"
        if exc.errno in _PERMISSION:
            return "permission_denied"
        return "io_error"
    return "internal_error"


def is_transient_rename_error(exc: BaseException) -> bool:
    return isinstance(exc, OSError) and getattr(exc, "winerror", None) in TRANSIENT_WINERRORS


def _write_private(path: Path, data: bytes, *, failpoint_write: str | None = None, failpoint_fsync: str | None = None) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        if failpoint_write:
            failpoints.hit(failpoint_write)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        if failpoint_fsync:
            failpoints.hit(failpoint_fsync)
        full_fsync(fd)
    finally:
        os.close(fd)


def _temp_name(name: str) -> str:
    return f".{name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"


# --------------------------------------------------------------------------
# Segment publication


@dataclass(frozen=True)
class PublishOutcome:
    ok: bool
    path: Path | None
    reason: str | None = None
    rename_retried: bool = False
    dir_synced: bool = False
    deadline_overrun: bool = False


def publish(
    dirs: SpoolDirs,
    name: str,
    data: bytes,
    *,
    deadline: float | None,
    platform: str = os.name,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> PublishOutcome:
    """Durably publish one segment into ``ready/``; never raises for I/O failures.

    ``deadline`` is a :func:`time.monotonic` soft deadline. It only bounds the
    single Windows transient-rename retry: once publication has begun, a
    successful durability step is never abandoned because time ran out
    (the outcome then reports ``deadline_overrun``).
    """
    tmp: Path | None = None
    retried = False
    try:
        dirs.ensure()
        tmp = dirs.tmp / _temp_name(name)
        final = dirs.ready / name
        _write_private(tmp, data, failpoint_write=failpoints.SPOOL_TEMP_WRITE, failpoint_fsync=failpoints.SPOOL_FSYNC)
        try:
            failpoints.hit(failpoints.SPOOL_RENAME)
            os.replace(tmp, final)
        except OSError as exc:
            remaining = None if deadline is None else deadline - clock()
            if platform != "nt" or not is_transient_rename_error(exc) or (remaining is not None and remaining <= 0):
                raise
            retried = True
            sleep(RENAME_RETRY_MAX_SECONDS if remaining is None else min(RENAME_RETRY_MAX_SECONDS, remaining))
            failpoints.hit(failpoints.SPOOL_RENAME)
            os.replace(tmp, final)
        tmp = None
        failpoints.hit(failpoints.SPOOL_AFTER_RENAME)
        synced = fsync_dir(dirs.ready)
    except Exception as exc:  # noqa: BLE001 - every failure becomes not_captured
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        reason = "rename_failed" if retried else classify(exc)
        return PublishOutcome(ok=False, path=None, reason=reason, rename_retried=retried)
    overrun = deadline is not None and clock() > deadline
    return PublishOutcome(ok=True, path=final, rename_retried=retried, dir_synced=synced, deadline_overrun=overrun)


def ready_segments(dirs: SpoolDirs) -> list[Path]:
    if not dirs.ready.is_dir():
        return []
    return sorted(p for p in dirs.ready.iterdir() if p.name.endswith(SEGMENT_SUFFIX) and p.is_file())


def remove_segment(dirs: SpoolDirs, path: Path) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    try:
        fsync_dir(dirs.ready)
    except OSError:
        pass  # a resurrected segment only replays harmlessly


def quarantine_segment(dirs: SpoolDirs, path: Path, reason: str) -> Path | None:
    """Move an unreadable/foreign segment aside; it is never ingested."""
    dirs.ensure()
    target = dirs.quarantine / f"{path.name}.{reason}"
    try:
        os.replace(path, target)
    except FileNotFoundError:
        return None
    fsync_dir(dirs.quarantine)
    return target


def cleanup_stale_temps(dirs: SpoolDirs, *, older_than: float = STALE_TEMP_SECONDS, now: float | None = None) -> int:
    """Delete never-acknowledged temp files older than ``older_than`` seconds."""
    removed = 0
    now = time.time() if now is None else now
    for directory in (dirs.tmp, dirs.cursors):
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if not path.name.endswith(".tmp"):
                continue
            try:
                if now - path.stat().st_mtime >= older_than:
                    path.unlink()
                    removed += 1
            except FileNotFoundError:
                continue
    return removed


# --------------------------------------------------------------------------
# Source cursors (advanced only after durable publication)


def cursor_order(cursor: dict[str, Any]) -> tuple[int, int]:
    return (int(cursor.get("generation", 0)), int(cursor.get("offset", 0)))


def read_cursor(dirs: SpoolDirs, source_id: str) -> dict[str, Any] | None:
    path = dirs.cursors / f"{source_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return None
    if not isinstance(data, dict) or data.get("source_id") != source_id or not isinstance(data.get("cursor"), dict):
        return None
    return data["cursor"]


def write_cursor(dirs: SpoolDirs, source_id: str, cursor: dict[str, Any]) -> bool:
    """Atomically advance one source cursor; never moves it backwards."""
    current = read_cursor(dirs, source_id)
    if current is not None and cursor_order(current) >= cursor_order(cursor):
        return True
    dirs.ensure()
    path = dirs.cursors / f"{source_id}.json"
    tmp = dirs.cursors / _temp_name(path.name)
    try:
        _write_private(tmp, canonical_bytes({"source_id": source_id, "cursor": cursor}))
        failpoints.hit(failpoints.CURSOR_WRITE)
        os.replace(tmp, path)
        fsync_dir(dirs.cursors)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False
    failpoints.hit(failpoints.CURSOR_AFTER_WRITE)
    return True


# --------------------------------------------------------------------------
# Content-free capture-gap records for health (A07)


def record_gap(dirs: SpoolDirs, *, code: str, reason: str, event_count: int, at: str, source_ids: Iterable[str] = ()) -> bool:
    """Best effort: a failure to record a gap must not affect the host."""
    try:
        dirs.ensure()
        if sum(1 for _ in dirs.gaps.iterdir()) >= MAX_GAP_FILES:
            return False
        record = {"gap_schema": 1, "code": code, "reason": reason, "event_count": event_count, "at": at, "source_ids": sorted(source_ids)}
        name = f"{at.replace(':', '').replace('-', '').replace('.', '')}-{secrets.token_hex(4)}.json"
        _write_private(dirs.gaps / name, canonical_bytes(record))
        return True
    except Exception:  # noqa: BLE001
        return False


def read_gaps(dirs: SpoolDirs) -> list[dict[str, Any]]:
    if not dirs.gaps.is_dir():
        return []
    records = []
    for path in sorted(dirs.gaps.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if isinstance(data, dict) and data.get("gap_schema") == 1:
            records.append(data)
    return records
