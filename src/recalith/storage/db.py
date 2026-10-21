"""SQLite store: connection policy, migrations and fenced transactions.

Authoritative writes use WAL journaling, ``synchronous=FULL``, foreign keys and
a 250 ms busy timeout (SYSTEM_SPEC §10). A newer or unknown schema is never
written; without an explicit compatible reader it does not open at all.
Transport layers receive a :class:`Store`, never a raw connection.

No model or network call may run inside :meth:`Store.transaction`.
"""

from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Iterator, Sequence

from recalith.contracts.common import InstallationContext, ReadSet, RecordRef, utc_now
from recalith.errors import RecalithError

SCHEMA_VERSION = 11  # 0011: the hook's bounded lexical lookup (decision 0021)
MIN_SQLITE = (3, 37, 0)  # STRICT tables
BUSY_TIMEOUT_MS = 250
STATE_DB = Path("state") / "memory.sqlite"
HEAD_TABLES = {"task": ("task_heads", "task_id"), "episode": ("episode_heads", "episode_id"), "claim": ("claim_heads", "claim_id")}


def sqlite_supported() -> bool:
    return tuple(int(x) for x in sqlite3.sqlite_version.split(".")[:3]) >= MIN_SQLITE


def _migrations() -> list[tuple[int, str]]:
    folder = resources.files("recalith.storage") / "migrations"
    found = []
    for entry in folder.iterdir():
        name = entry.name
        if name.endswith(".sql") and name[:4].isdigit():
            found.append((int(name[:4]), entry.read_text(encoding="utf-8")))
    return sorted(found)


def _configure(conn: sqlite3.Connection, *, readonly: bool) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    if readonly:
        conn.execute("PRAGMA query_only = ON")
    else:
        mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            raise RecalithError("storage_failure", "the store requires WAL journaling on a local filesystem")
        conn.execute("PRAGMA synchronous = FULL")


def connect(path: Path, *, readonly: bool = False, create: bool = False) -> sqlite3.Connection:
    if not sqlite_supported():
        raise RecalithError("capability_unavailable", f"SQLite {sqlite3.sqlite_version} lacks STRICT tables (need 3.37+)")
    if not create and not path.exists():
        raise RecalithError("capability_unavailable", "installation store is missing")
    uri = path.as_uri() + ("?mode=ro" if readonly else ("?mode=rwc" if create else "?mode=rw"))
    try:
        conn = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=BUSY_TIMEOUT_MS / 1000, check_same_thread=False)
    except sqlite3.Error as exc:
        raise RecalithError("storage_failure", f"cannot open store: {type(exc).__name__}") from exc
    try:
        _configure(conn, readonly=readonly)
    except sqlite3.Error as exc:
        conn.close()
        raise RecalithError("storage_failure", f"cannot configure store: {type(exc).__name__}") from exc
    except RecalithError:
        conn.close()
        raise
    return conn


def create_database(path: Path, *, project_id: str, installation_id: str, engine_version: str, release_profile: str, workspace: dict[str, Any]) -> None:
    """Create a fresh store with every migration and its identity rows."""
    conn = connect(path, create=True)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for version, sql in _migrations():
            if version > SCHEMA_VERSION:
                break
            for statement in _split_sql(sql):
                conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        now = utc_now()
        conn.execute(
            "INSERT INTO installation_meta (singleton, project_id, installation_id, engine_version, schema_version, release_profile, created_at) VALUES (1, ?, ?, ?, ?, ?, ?)",
            (project_id, installation_id, engine_version, SCHEMA_VERSION, release_profile, now),
        )
        conn.execute(
            "INSERT INTO workspaces (workspace_id, canonical_root, root_identity, attachment_state, registered_at) VALUES (?, ?, ?, 'primary', ?)",
            (workspace["workspace_id"], workspace["canonical_root"], workspace["root_identity"], now),
        )
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _split_sql(sql: str) -> list[str]:
    """Split a migration into statements (no triggers/strings containing ';')."""
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    return [stmt.strip() for stmt in "\n".join(lines).split(";") if stmt.strip()]


@dataclass(frozen=True)
class Meta:
    project_id: str
    installation_id: str
    engine_version: str
    schema_version: int
    release_profile: str
    store_revision: int
    guidance_epoch: int
    policy_revision: int
    tombstone_epoch: int


def read_meta(conn: sqlite3.Connection) -> Meta:
    try:
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        row = conn.execute(
            "SELECT project_id, installation_id, engine_version, schema_version, release_profile, store_revision, guidance_epoch, policy_revision, tombstone_epoch FROM installation_meta WHERE singleton = 1"
        ).fetchone()
    except sqlite3.Error as exc:
        raise RecalithError("invalid_schema", "store has no readable installation metadata") from exc
    if row is None:
        raise RecalithError("invalid_schema", "store has no installation metadata row")
    meta = Meta(*row)
    if user_version != meta.schema_version:
        raise RecalithError("invalid_schema", "schema version markers disagree")
    return meta


class Txn:
    """An open write transaction. Storage-internal; repositories use it."""

    def __init__(self, conn: sqlite3.Connection, meta: Meta) -> None:
        self._conn = conn
        self.meta = meta
        self._advance_store = False
        self._advance_guidance = False

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def one(self, sql: str, params: Sequence[Any] = ()) -> tuple | None:
        return self._conn.execute(sql, params).fetchone()

    def mutated(self, *, serving_relevant: bool) -> None:
        """Record that this transaction changed authoritative state.

        Serving-relevant changes (servable task/claim/evidence state,
        applicability, policy, privacy) also advance the guidance epoch;
        receipt/queue bookkeeping does not.
        """
        self._advance_store = True
        self._advance_guidance = self._advance_guidance or serving_relevant

    @property
    def next_store_revision(self) -> int:
        return self.meta.store_revision + 1


class Store:
    """Repository interface for one installation's database."""

    def __init__(self, ctx: InstallationContext, conn: sqlite3.Connection, *, readonly: bool) -> None:
        self.ctx = ctx
        self._conn = conn
        self.readonly = readonly

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def meta(self) -> Meta:
        return read_meta(self._conn)

    def checkpoint(self) -> bool:
        """Fold the WAL into the database file and truncate it (best effort; never inside a transaction).

        Forgetting runs it after its purge so the purged pages leave the WAL
        once no reader still needs them; a busy reader leaves it for later.
        """
        if self.readonly or self._conn.in_transaction:
            return False
        try:
            busy, _log, _done = self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        except sqlite3.Error:
            return False
        return busy == 0

    @contextlib.contextmanager
    def read(self) -> Iterator["_ReadView"]:
        """A consistent read snapshot (explicit read transaction)."""
        self._conn.execute("BEGIN")
        try:
            yield _ReadView(self._conn)
        finally:
            self._conn.execute("COMMIT")

    @contextlib.contextmanager
    def transaction(self, expected: ReadSet | None = None) -> Iterator[Txn]:
        """Short write transaction with optional read-set (revision) checks."""
        if self.readonly:
            raise RecalithError("policy_refused", "store opened read-only")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            raise RecalithError("storage_failure", "store is busy; write not admitted within the busy timeout") from exc
        try:
            meta = read_meta(self._conn)
            _guard_identity(self.ctx, meta)
            if expected is not None:
                _check_read_set(self._conn, meta, expected)
            txn = Txn(self._conn, meta)
            yield txn
            if txn._advance_store:
                self._conn.execute(
                    "UPDATE installation_meta SET store_revision = store_revision + 1, guidance_epoch = guidance_epoch + ? WHERE singleton = 1",
                    (1 if txn._advance_guidance else 0,),
                )
            self._conn.execute("COMMIT")
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise


class _ReadView:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        if not sql.lstrip().upper().startswith(("SELECT", "WITH", "PRAGMA")):
            raise RecalithError("policy_refused", "read views are read-only")
        return self._conn.execute(sql, params)


def _guard_identity(ctx: InstallationContext, meta: Meta) -> None:
    if meta.installation_id != ctx.installation_id or meta.project_id != ctx.project_id:
        raise RecalithError("foreign_installation", "store belongs to another installation")
    if meta.schema_version != SCHEMA_VERSION:
        raise RecalithError("invalid_schema", f"store schema {meta.schema_version} is not writable by schema {SCHEMA_VERSION}")


def _check_read_set(conn: sqlite3.Connection, meta: Meta, expected: ReadSet) -> None:
    if expected.policy_revision != meta.policy_revision or expected.tombstone_epoch != meta.tombstone_epoch:
        raise RecalithError("revision_conflict", "policy or tombstone epoch changed since the read")
    for ref in expected.entity_revisions:
        _check_ref(conn, ref)


def _check_ref(conn: sqlite3.Connection, ref: RecordRef) -> None:
    if ref.kind == "event":
        if conn.execute("SELECT 1 FROM events WHERE event_id = ?", (ref.id,)).fetchone() is None:
            raise RecalithError("revision_conflict", "consulted event no longer exists")
        return
    if ref.kind == "capsule":
        if conn.execute("SELECT 1 FROM evidence_capsules WHERE capsule_id = ?", (ref.id,)).fetchone() is None:
            raise RecalithError("revision_conflict", "consulted capsule no longer exists")
        return
    table, key = HEAD_TABLES[ref.kind]
    row = conn.execute(f"SELECT revision FROM {table} WHERE {key} = ?", (ref.id,)).fetchone()  # noqa: S608 - fixed table names
    if row is None or row[0] != ref.revision:
        raise RecalithError("revision_conflict", f"{ref.kind} head moved since the read")


def open_store(ctx: InstallationContext, *, readonly: bool = False) -> Store:
    """Open this installation's store after verifying identity and schema."""
    path = Path(ctx.root) / ".recalith" / STATE_DB
    conn = connect(path, readonly=readonly)
    try:
        meta = read_meta(conn)
        if meta.installation_id != ctx.installation_id or meta.project_id != ctx.project_id:
            raise RecalithError("foreign_installation", "store belongs to another installation")
        if meta.schema_version > SCHEMA_VERSION:
            # No compatible reader exists for a newer schema: fail clearly.
            raise RecalithError("invalid_schema", f"store schema {meta.schema_version} is newer than this engine supports ({SCHEMA_VERSION})")
        if meta.schema_version < SCHEMA_VERSION:
            raise RecalithError("invalid_schema", f"store schema {meta.schema_version} requires an explicit migration")
    except BaseException:
        conn.close()
        raise
    return Store(ctx, conn, readonly=readonly)
