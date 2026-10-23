"""Consistent, verified private backups and the tombstone ledger (SYSTEM_SPEC §11–§12; DATA_CONTRACTS §10–§11; decision 0016).

**A backup** is a directory of exactly three files: ``memory.sqlite`` (a
consistent snapshot through SQLite's online backup interface, copied in one
step under one read transaction and converted to a self-contained rollback
journal file), ``ledger.json`` (the tombstone ledger *of that snapshot*) and
``manifest.json`` (an :class:`ArtifactManifest` with the digest of each file
and the snapshot's tombstone epoch). The SHA-256 of ``manifest.json`` is the
backup's digest: the ``--expected-digest`` a restore names.

**Publication.** A journal under ``.recalith/run/backups/`` names the
staging directory and the output before anything is written; the snapshot,
ledger and manifest are written and fsynced in a hidden staging directory next
to the output, the staging directory is verified exactly as a restore would,
then renamed to the output in one step, recorded in the store's ``backups``
row, the latest ledger copy is refreshed and the journal removed. A crash
leaves either no output (the staging directory is removed by :func:`recover`)
or a complete output that verifies (recovery records it). Nothing half-written
ever verifies: verification checks the file set, every digest, the snapshot's
integrity, schema and identity, and that the ledger equals the snapshot's
tombstones. An output never replaces anything that exists, and inside the
project checkout it must live under ``.recalith/`` (private, untracked).

**The latest ledger copy** (``.recalith/state/ledger.json``) always holds the
store's current tombstones and epoch, written at every backup and by the
worker whenever the epoch moves; it is what lets Task 16's restore of an older
backup suppress what was forgotten after it.

**Forgetting and restore** (Task 16): :func:`holds` tells whether a
snapshot still holds forgotten content (an affected backup),
:func:`delete_recorded` deletes one for forgetting, and a restore reads the
verified snapshot once into memory (:func:`load_verified_snapshot`), applies
the newer tombstones there and writes the suppressed copy with
:func:`write_database`.

**Retention** (:func:`prune`): verified backups older than the private-backup
window are deleted, files first and then the row, and only when the output's
manifest still names that backup; anything else at a recorded location is left
alone. Spool segments and session scratch are not part of a backup: they are
the live installation's transient intake and per-session state.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from recalith.contracts.common import InstallationContext, canonical_json, format_utc, new_id, parse_utc, utc_now
from recalith.contracts.transfers import ArtifactManifest
from recalith.errors import RecalithError
from recalith.fast import failpoints, spool
from recalith.storage.db import SCHEMA_VERSION, STATE_DB, Store, connect, open_store

BACKUP_DB = "memory.sqlite"
LEDGER = "ledger.json"
MANIFEST = "manifest.json"
FILES = (BACKUP_DB, LEDGER)
LEDGER_SCHEMA = 1
MANIFEST_MAX_BYTES = 64 * 1024
LATEST_LEDGER = Path(".recalith") / "state" / "ledger.json"
JOURNAL_DIR = Path(".recalith") / "run" / "backups"
RENAME_RETRIES = 5


class BackupInvalid(RecalithError):
    """A backup that does not verify; ``reason`` is a stable, content-free code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__("invalid_schema", f"backup verification failed: {reason}" + (f" ({detail})" if detail else ""))
        self.reason = reason


@dataclass
class BackupResult:
    manifest: ArtifactManifest
    manifest_digest: str
    location: str
    bytes: int

    def report(self) -> dict[str, Any]:
        return {"manifest": self.manifest.model_dump(mode="json"), "manifest_digest": self.manifest_digest, "location": self.location, "bytes": self.bytes}


@dataclass
class Verified:
    manifest: ArtifactManifest
    manifest_digest: str
    meta: dict[str, Any]
    ledger: dict[str, Any]


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_file(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        spool.full_fsync(fd)
    finally:
        os.close(fd)


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))  # Windows commits only a writable descriptor
    try:
        spool.full_fsync(fd)
    finally:
        os.close(fd)


def _replace(source: Path, target: Path) -> None:
    """Atomic rename; Windows may briefly refuse while a scanner holds a handle (bounded retry)."""
    for attempt in range(RENAME_RETRIES):
        try:
            os.rename(source, target)
            return
        except PermissionError:
            if attempt == RENAME_RETRIES - 1:
                raise
            time.sleep(0.02 * (attempt + 1))


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    _write_file(tmp, data)
    for attempt in range(RENAME_RETRIES):
        try:
            os.replace(tmp, path)
            break
        except PermissionError:
            if attempt == RENAME_RETRIES - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.02 * (attempt + 1))
    spool.fsync_dir(path.parent)


def _snapshot(path: Path) -> sqlite3.Connection:
    """A read-only, immutable view of a snapshot file (no journal, no locks, nothing written)."""
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)


# --------------------------------------------------------------------------
# The tombstone ledger


def ledger_of(q: Any) -> dict[str, Any]:
    """The tombstone ledger of one snapshot: identity, epoch and every content-free tombstone row."""
    meta = q.execute("SELECT project_id, installation_id, tombstone_epoch, store_revision FROM installation_meta WHERE singleton = 1").fetchone()
    rows = q.execute("SELECT tombstone_id, epoch, target_ids, source_digests, deletion_scope, created_at FROM tombstones ORDER BY epoch, tombstone_id").fetchall()
    tombstones = [
        {"tombstone_id": t, "epoch": e, "target_ids": json.loads(targets), "source_digests": json.loads(digests), "deletion_scope": scope, "created_at": created}
        for t, e, targets, digests, scope, created in rows
    ]
    return {"ledger_schema": LEDGER_SCHEMA, "project_id": meta[0], "installation_id": meta[1], "tombstone_epoch": meta[2], "store_revision": meta[3], "tombstones": tombstones}


def write_latest_ledger(ctx: InstallationContext, store: Store) -> dict[str, Any]:
    """Refresh ``.recalith/state/ledger.json`` from the store's current tombstones (atomic replace)."""
    with store.read() as view:
        ledger = ledger_of(view)
    _atomic_write(Path(ctx.root) / LATEST_LEDGER, canonical_json(ledger))
    return ledger


def read_latest_ledger(root: Path | str) -> dict[str, Any] | None:
    try:
        data = json.loads((Path(root) / LATEST_LEDGER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("ledger_schema") == LEDGER_SCHEMA else None


# --------------------------------------------------------------------------
# Verification (what a restore runs first)


def verify(path: Path | str, *, expected_digest: str | None = None, ctx: InstallationContext | None = None) -> Verified:
    """Verify a backup directory without changing anything; raises :class:`BackupInvalid` with a reason code."""
    root = Path(path)
    if not root.is_dir():
        raise BackupInvalid("backup_missing")
    try:
        names = {p.name for p in root.iterdir()}
    except OSError:
        raise BackupInvalid("backup_unreadable") from None
    expected = {MANIFEST, *FILES}
    if expected - names:
        raise BackupInvalid("backup_missing_file")
    if names - expected:
        raise BackupInvalid("backup_unexpected_file")
    try:
        raw = (root / MANIFEST).read_bytes()
    except OSError:
        raise BackupInvalid("backup_unreadable") from None
    if len(raw) > MANIFEST_MAX_BYTES:
        raise BackupInvalid("backup_manifest_invalid")
    digest = hashlib.sha256(raw).hexdigest()
    if expected_digest is not None and digest != expected_digest:
        raise BackupInvalid("backup_digest_mismatch")
    try:
        manifest = ArtifactManifest.model_validate_json(raw)
    except ValidationError:
        raise BackupInvalid("backup_manifest_invalid") from None
    if manifest.artifact_type != "backup" or set(manifest.file_digests) != set(FILES) or not manifest.artifact_id.startswith("bkp_"):
        raise BackupInvalid("backup_manifest_invalid")
    for name in FILES:
        try:
            if _sha(root / name) != manifest.file_digests[name]:
                raise BackupInvalid("backup_file_digest_mismatch", name)
        except OSError:
            raise BackupInvalid("backup_unreadable", name) from None
    if manifest.schemas.get("database") != SCHEMA_VERSION or manifest.schemas.get("ledger") != LEDGER_SCHEMA:
        raise BackupInvalid("backup_schema_unsupported")
    if ctx is not None and manifest.project_id != ctx.project_id:
        raise BackupInvalid("backup_foreign_project")
    try:
        conn = _snapshot(root / BACKUP_DB)
    except sqlite3.Error:
        raise BackupInvalid("backup_snapshot_unreadable") from None
    try:
        if [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()] != ["ok"] or conn.execute("PRAGMA foreign_key_check").fetchall():
            raise BackupInvalid("backup_integrity_failed")
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        row = conn.execute("SELECT project_id, installation_id, engine_version, schema_version, release_profile, store_revision, guidance_epoch, policy_revision, tombstone_epoch FROM installation_meta WHERE singleton = 1").fetchone()
        if row is None:
            raise BackupInvalid("backup_integrity_failed", "no installation metadata")
        meta = dict(zip(("project_id", "installation_id", "engine_version", "schema_version", "release_profile", "store_revision", "guidance_epoch", "policy_revision", "tombstone_epoch"), row, strict=True))
        if user_version != SCHEMA_VERSION or meta["schema_version"] != SCHEMA_VERSION:
            raise BackupInvalid("backup_schema_unsupported")
        if (meta["project_id"], meta["installation_id"], meta["tombstone_epoch"]) != (manifest.project_id, manifest.installation_id, manifest.tombstone_epoch):
            raise BackupInvalid("backup_manifest_mismatch")
        snapshot_ledger = ledger_of(conn)
    except sqlite3.Error:
        raise BackupInvalid("backup_snapshot_unreadable") from None
    finally:
        conn.close()
    try:
        ledger = json.loads((root / LEDGER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise BackupInvalid("backup_ledger_mismatch") from None
    if ledger != snapshot_ledger:
        raise BackupInvalid("backup_ledger_mismatch")
    return Verified(manifest=manifest, manifest_digest=digest, meta=meta, ledger=ledger)


# --------------------------------------------------------------------------
# Creating a backup


def _output(ctx: InstallationContext, destination: Path | str) -> Path:
    target = Path(destination)
    if not target.name or target.name in (".", ".."):
        raise RecalithError("invalid_schema", "--output names a new directory")
    try:
        parent = target.parent.resolve(strict=True)
    except (OSError, RuntimeError):
        raise RecalithError("invalid_schema", "the directory that should hold --output does not exist") from None
    if not parent.is_dir():
        raise RecalithError("invalid_schema", "the directory that should hold --output does not exist")
    out = parent / target.name
    if os.path.lexists(out):
        raise RecalithError("invalid_schema", "the --output path already exists; a backup never replaces anything")
    project = Path(ctx.root).resolve()
    private = project / ".recalith"
    if (out == project or project in out.parents) and private not in out.parents:
        raise RecalithError("invalid_schema", "a backup inside the project checkout must be under .recalith/ (private, never tracked)")
    return out


def create(ctx: InstallationContext, destination: Path | str, *, store: Store | None = None, now: str | None = None) -> BackupResult:
    """Write, verify and publish a consistent backup at a new ``destination``; record it (see the module docstring)."""
    now = now or utc_now()
    own = store is None
    store = store or open_store(ctx)  # refuses a store of another schema before anything is written
    try:
        meta = store.meta()
        if meta.schema_version != SCHEMA_VERSION:
            raise RecalithError("invalid_schema", f"store schema {meta.schema_version} is not this engine's schema {SCHEMA_VERSION}")
        out = _output(ctx, destination)
        recover(ctx, store)
        backup_id = new_id("bkp")
        staging = out.parent / f".{out.name}.{backup_id[4:12]}.partial"
        journal = Path(ctx.root) / JOURNAL_DIR / f"{backup_id}.json"
        try:
            _atomic_write(journal, canonical_json({"backup_id": backup_id, "staging": str(staging), "destination": str(out), "created_at": now}))
            staging.mkdir(mode=0o700)
            _copy_snapshot(Path(ctx.root) / ".recalith" / STATE_DB, staging / BACKUP_DB)
            failpoints.hit(failpoints.BACKUP_AFTER_SNAPSHOT)
            conn = _snapshot(staging / BACKUP_DB)
            try:
                ledger = ledger_of(conn)
                snap = conn.execute("SELECT project_id, installation_id, engine_version, schema_version, tombstone_epoch FROM installation_meta WHERE singleton = 1").fetchone()
            finally:
                conn.close()
            _write_file(staging / LEDGER, canonical_json(ledger))
            manifest = ArtifactManifest(
                artifact_id=backup_id, artifact_type="backup", schemas={"database": snap[3], "event": 1, "ledger": LEDGER_SCHEMA, "manifest": 1},
                project_id=snap[0], installation_id=snap[1], engine_version=snap[2], created_at=now,
                file_digests={name: _sha(staging / name) for name in FILES}, tombstone_epoch=snap[4],
            )
            raw = canonical_json(manifest.model_dump(mode="json"))
            _write_file(staging / MANIFEST, raw)
            spool.fsync_dir(staging)
            failpoints.hit(failpoints.BACKUP_AFTER_MANIFEST)
            verified = verify(staging, expected_digest=hashlib.sha256(raw).hexdigest(), ctx=ctx)
            size = sum((staging / name).stat().st_size for name in (*FILES, MANIFEST))
            _replace(staging, out)
            spool.fsync_dir(out.parent)
            failpoints.hit(failpoints.BACKUP_AFTER_PUBLISH)
            _record(store, verified.manifest, verified.manifest_digest, out, size)
            failpoints.hit(failpoints.BACKUP_AFTER_RECORD)
            _refresh_ledger(ctx, store)
            journal.unlink(missing_ok=True)
        except BackupInvalid as exc:
            raise RecalithError("storage_failure", f"the new backup did not verify ({exc.reason}); nothing was published") from exc
        except (OSError, sqlite3.Error) as exc:
            raise RecalithError("storage_failure", f"backup failed: {type(exc).__name__}; nothing incomplete is published") from exc
        return BackupResult(manifest=verified.manifest, manifest_digest=verified.manifest_digest, location=str(out), bytes=size)
    finally:
        if own:
            store.close()


def _copy_snapshot(source: Path, target: Path) -> None:
    os.close(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600))  # private before SQLite opens it
    src = connect(source, readonly=True)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)  # one step: every page under one read transaction (a consistent store revision)
            mode = dst.execute("PRAGMA journal_mode = DELETE").fetchone()[0]
            if str(mode).lower() != "delete":
                raise sqlite3.OperationalError("the snapshot could not leave WAL mode")
        finally:
            dst.close()
    finally:
        src.close()
    for leftover in (target.with_name(target.name + "-wal"), target.with_name(target.name + "-shm"), target.with_name(target.name + "-journal")):
        leftover.unlink(missing_ok=True)
    _fsync_file(target)


def _record(store: Store, manifest: ArtifactManifest, digest: str, location: Path, size: int) -> bool:
    with store.transaction() as txn:
        if txn.one("SELECT 1 FROM backups WHERE backup_id = ?", (manifest.artifact_id,)) is not None:
            return False
        txn.execute(
            "INSERT INTO backups (backup_id, manifest, tombstone_epoch, state, created_at, location, manifest_digest, bytes) VALUES (?, ?, ?, 'verified', ?, ?, ?, ?)",
            (manifest.artifact_id, canonical_json(manifest.model_dump(mode="json")).decode(), manifest.tombstone_epoch, manifest.created_at, str(location), digest, size),
        )
        txn.mutated(serving_relevant=False)  # bookkeeping
    return True


def _refresh_ledger(ctx: InstallationContext, store: Store) -> None:
    ledger = write_latest_ledger(ctx, store)
    with store.transaction() as txn:
        txn.execute("UPDATE retention_state SET ledger_epoch = ? WHERE singleton = 1", (ledger["tombstone_epoch"],))


def _owned(location: Path, backup_id: str) -> bool:
    """Whether ``location`` still holds that backup (its manifest names it); unreadable means no."""
    try:
        data = json.loads((location / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("artifact_id") == backup_id


def recover(ctx: InstallationContext, store: Store) -> list[str]:
    """Finish or clean up interrupted backups from their journals; returns the backup IDs handled."""
    directory = Path(ctx.root) / JOURNAL_DIR
    try:
        journals = sorted(directory.glob("bkp_*.json"))
    except OSError:
        return []
    handled = []
    for journal in journals:
        try:
            data = json.loads(journal.read_text(encoding="utf-8"))
            backup_id, staging, out = data["backup_id"], Path(data["staging"]), Path(data["destination"])
        except (OSError, ValueError, KeyError, TypeError):
            journal.unlink(missing_ok=True)
            continue
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if out.is_dir() and _owned(out, backup_id):
            try:
                verified = verify(out, ctx=ctx)
            except BackupInvalid:
                shutil.rmtree(out, ignore_errors=True)  # ours, yet it does not verify: never left looking like a backup
            else:
                size = sum((out / name).stat().st_size for name in (*FILES, MANIFEST))
                _record(store, verified.manifest, verified.manifest_digest, out, size)
                _refresh_ledger(ctx, store)
        journal.unlink(missing_ok=True)
        handled.append(backup_id)
    return handled


def prune(store: Store, ctx: InstallationContext, *, now: str, days: int) -> list[str]:
    """Delete verified backups older than ``days`` (files, then the row); returns the deleted backup IDs."""
    cutoff = format_utc(parse_utc(now) - _dt.timedelta(days=days))
    with store.read() as view:
        rows = view.execute("SELECT backup_id, location FROM backups WHERE state = 'verified' AND created_at < ? ORDER BY created_at, backup_id", (cutoff,)).fetchall()
    deleted = []
    for backup_id, location in rows:
        path = Path(location) if location else None
        if path is not None and os.path.lexists(path):
            if not path.is_dir() or not _owned(path, backup_id):
                continue  # something else lives there now: never deleted on the row's word alone
            try:
                shutil.rmtree(path)
            except OSError:
                continue  # retried at the next sweep; the row still says verified
            failpoints.hit(failpoints.BACKUP_AFTER_PRUNE)
        with store.transaction() as txn:
            txn.execute("UPDATE backups SET state = 'deleted' WHERE backup_id = ? AND state = 'verified'", (backup_id,))
            txn.mutated(serving_relevant=False)
        deleted.append(backup_id)
    return deleted


# --------------------------------------------------------------------------
# Forgetting and restore (Task 16, decision 0017)


def holds(path: Path | str, event_ids: set[str], record_ids: set[str]) -> bool | None:
    """Whether a backup snapshot still holds a payload, capsule or body of these IDs; None when it cannot be read."""
    from recalith.privacy import capsules
    tables = {"claim": ("claim_revisions", "claim_id"), "task": ("task_revisions", "task_id"), "ep": ("episode_revisions", "episode_id")}
    try:
        conn = _snapshot(Path(path))
    except (sqlite3.Error, OSError, ValueError):
        return None
    try:
        events = sorted(event_ids)
        for i in range(0, len(events), 400):
            chunk = events[i : i + 400]
            if conn.execute(f"SELECT 1 FROM events WHERE payload IS NOT NULL AND event_id IN ({','.join('?' for _ in chunk)}) LIMIT 1", tuple(chunk)).fetchone():  # noqa: S608
                return True
            kept = [capsules.capsule_id(e) for e in chunk]  # a capsule of the event holds its content too (decision 0025)
            if conn.execute(f"SELECT 1 FROM evidence_capsules WHERE body IS NOT NULL AND capsule_id IN ({','.join('?' for _ in kept)}) LIMIT 1", tuple(kept)).fetchone():  # noqa: S608
                return True
        for prefix, (table, key) in tables.items():
            ids = sorted(r for r in record_ids if r.split("_", 1)[0] == prefix)
            for i in range(0, len(ids), 400):
                chunk = ids[i : i + 400]
                if conn.execute(f"SELECT 1 FROM {table} WHERE body IS NOT NULL AND {key} IN ({','.join('?' for _ in chunk)}) LIMIT 1", tuple(chunk)).fetchone():  # noqa: S608
                    return True
        return False
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def delete_recorded(store: Store, backup_id: str) -> bool:
    """Delete one recorded backup for forgetting: its files when the location still holds it, then the row (``deleted``)."""
    with store.read() as view:
        row = view.execute("SELECT location FROM backups WHERE backup_id = ?", (backup_id,)).fetchone()
    if row is None:
        return False
    location = Path(row[0]) if row[0] else None
    if location is not None and os.path.lexists(location) and location.is_dir() and _owned(location, backup_id):
        shutil.rmtree(location)  # files first, then the row: a crash between them repeats the deletion
    with store.transaction() as txn:
        txn.execute("UPDATE backups SET state = 'deleted' WHERE backup_id = ? AND state = 'verified'", (backup_id,))
        txn.mutated(serving_relevant=False)
    return True


def load_verified_snapshot(path: Path | str, verified: Verified) -> sqlite3.Connection:
    """The verified snapshot as an in-memory database: its bytes are read once and must hash to the manifest's digest.

    A restore suppresses newer tombstones in this copy, so nothing that a
    tombstone covers is ever written to disk on the restore path.
    """
    data = (Path(path) / BACKUP_DB).read_bytes()
    if hashlib.sha256(data).hexdigest() != verified.manifest.file_digests[BACKUP_DB]:
        raise BackupInvalid("backup_file_digest_mismatch", BACKUP_DB)
    conn = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    try:
        conn.deserialize(data)
        conn.execute("PRAGMA foreign_keys = ON")
    except sqlite3.Error:
        conn.close()
        raise BackupInvalid("backup_snapshot_unreadable") from None
    return conn


def write_database(conn: sqlite3.Connection, target: Path) -> None:
    """Write a database (e.g. a suppressed in-memory restore copy) to a new private, self-contained file, fsynced."""
    os.close(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600))
    dst = sqlite3.connect(target)
    try:
        conn.backup(dst)
        mode = dst.execute("PRAGMA journal_mode = DELETE").fetchone()[0]
        if str(mode).lower() != "delete":
            raise sqlite3.OperationalError("the copy could not use a rollback journal")
    finally:
        dst.close()
    for leftover in (target.with_name(target.name + "-wal"), target.with_name(target.name + "-shm"), target.with_name(target.name + "-journal")):
        leftover.unlink(missing_ok=True)
    _fsync_file(target)
    spool.fsync_dir(target.parent)


def recorded(store: Store) -> list[dict[str, Any]]:
    with store.read() as view:
        rows = view.execute("SELECT backup_id, state, created_at, location, manifest_digest, bytes, tombstone_epoch FROM backups ORDER BY created_at, backup_id").fetchall()
    keys = ("backup_id", "state", "created_at", "location", "manifest_digest", "bytes", "tombstone_epoch")
    return [dict(zip(keys, r, strict=True)) for r in rows]


__all__ = ["create", "verify", "recover", "prune", "ledger_of", "write_latest_ledger", "read_latest_ledger", "holds", "delete_recorded", "load_verified_snapshot", "write_database", "BackupInvalid", "BackupResult", "Verified", "utc_now"]
