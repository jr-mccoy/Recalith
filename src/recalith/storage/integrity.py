"""Revision hash chain and integrity scanner: full profile only (SYSTEM_SPEC §10, DATA_CONTRACTS §11; decision 0024).

**Recording.** In a ``release_profile: full`` store every write transaction
that changes a chained row appends exactly one ``revision_chain`` entry inside
that transaction, just before its commit. The capture is per connection:
:func:`arm` installs TEMP triggers (AFTER INSERT/UPDATE/DELETE on every chained
table) that note each touched row's table, rowid and primary key in a TEMP
table; :func:`seal` digests the touched rows as they stand at commit and
appends the entry. TEMP objects never reach the database file or a backup, a
rollback (or a savepoint rollback) discards what it captured, and a writer
cannot forget to register a row. No model or network call happens here.

**Entries** hold digests only (no prose): ``row_digests`` is canonical JSON
``{entry_schema, kind, store_revision, metadata_hash, operation_ids, rows}``
(a baseline adds ``reason`` and ``tables``) with ``rows`` a sorted list of
``[table, key_digest, rowid, row_digest | null]``. ``entry_hash`` is the
SHA-256 of canonical ``[sequence, previous_hash, operation_id, row_digests,
purge_marker, tombstone_epoch]``; the first entry links to :data:`GENESIS`.
Authorized retention/forget purges append ``kind: purge`` entries
(``purge_marker = 1``); history is never rewritten.

**Chained tables** are every ordinary table of the store except
``revision_chain`` itself; the FTS5 virtual table and its shadow tables (a
derived ranking index) are not ordinary tables. Preview stores never arm,
never seal and report every integrity form ``unavailable_in_preview``.

**Verification** (:func:`verify`): the default check re-links the entries
after the persisted verified head (the private checkpoint file
``.recalith/state/integrity.json``, never the store) and compares the rows
those entries touched with the store; it cannot see an out-of-band edit to a
row nothing touched since. ``full=True`` re-links the whole chain from its
baseline and compares every current row of every chained table (O(store)).
A same-user process that rewrites rows, chain and checkpoint together is not
detected: this is detection, not an independently trusted log.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence

from recalith.contracts.common import InstallationContext, utc_now
from recalith.errors import RecalithError
from recalith.fast import failpoints

ENTRY_SCHEMA = 1
CHECKPOINT_SCHEMA = 1
GENESIS = "0" * 64
CHECKPOINT = Path("state") / "integrity.json"
TOUCHED = "recalith_chain_touched"
EXCLUDED = frozenset({"revision_chain"})
BASELINE_REASONS = ("init", "activation")
KINDS = ("baseline", "mutation", "purge")
MAX_FINDINGS = 256
CHUNK = 500
UNAVAILABLE = "unavailable_in_preview"


# --------------------------------------------------------------------------
# Canonical digests


def _canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canon(value)).hexdigest()


def _typed(value: Any) -> list[Any]:
    if value is None:
        return ["n"]
    if isinstance(value, int):
        return ["i", value]
    if isinstance(value, float):
        return ["r", value.hex()]
    if isinstance(value, str):
        return ["t", value]
    return ["b", bytes(value).hex()]


def row_digest(table: str, names: Sequence[str], values: Sequence[Any]) -> str:
    """SHA-256 of canonical ``[table, [[column, typed value], ...]]`` in declared column order."""
    return _sha([table, [[n, _typed(v)] for n, v in zip(names, values, strict=True)]])


def key_digest(table: str, key_json: str) -> str:
    """SHA-256 of canonical ``["key", table, primary key values]`` (as SQLite's ``json_array`` renders them; the rowid for keyless tables)."""
    return _sha(["key", table, json.loads(key_json)])


def entry_hash(sequence: int, previous_hash: str, operation_id: str | None, row_digests: str, purge_marker: int, tombstone_epoch: int) -> str:
    return _sha([sequence, previous_hash, operation_id, row_digests, purge_marker, tombstone_epoch])


# --------------------------------------------------------------------------
# Schema


def chained_tables(q: Any) -> list[str]:
    rows = q.execute("PRAGMA main.table_list").fetchall()
    return sorted(name for _schema, name, kind, *_rest in rows if kind == "table" and not name.startswith("sqlite_") and name not in EXCLUDED)


def _key_columns(q: Any, table: str) -> list[str]:
    cols = q.execute(f'PRAGMA main.table_info("{table}")').fetchall()
    return [c[1] for c in sorted(cols, key=lambda c: c[5]) if c[5]]


def _key_sql(columns: Sequence[str], prefix: str = "") -> str:
    return "json_array(" + (", ".join(f'{prefix}"{c}"' for c in columns) if columns else f"{prefix}rowid") + ")"


def _profile(q: Any) -> str:
    return q.execute("SELECT release_profile FROM installation_meta WHERE singleton = 1").fetchone()[0]


def _unavailable() -> RecalithError:
    return RecalithError("capability_unavailable", f"the revision chain is {UNAVAILABLE}: it is a full-release capability (release_profile: full)")


# --------------------------------------------------------------------------
# Recording (inside the writer's transaction)


def arm(conn: Any) -> None:
    """Install this connection's TEMP row capture once (idempotent; also re-armed after a rolled-back first use)."""
    if conn.execute("SELECT 1 FROM temp.sqlite_master WHERE type = 'table' AND name = ?", (TOUCHED,)).fetchone() is not None:
        return
    conn.execute("PRAGMA recursive_triggers = ON")  # REPLACE's implicit deletions fire the delete capture
    conn.execute(f"CREATE TEMP TABLE {TOUCHED} (seq INTEGER PRIMARY KEY, tbl TEXT NOT NULL, rid INTEGER NOT NULL, pk TEXT NOT NULL)")
    for table in chained_tables(conn):
        columns = _key_columns(conn, table)
        for event, refs in (("INSERT", ("NEW",)), ("UPDATE", ("OLD", "NEW")), ("DELETE", ("OLD",))):
            body = " ".join(f"INSERT INTO {TOUCHED} (tbl, rid, pk) VALUES ('{table}', {r}.rowid, {_key_sql(columns, r + '.')});" for r in refs)
            conn.execute(f'CREATE TEMP TRIGGER "{TOUCHED}_{table}_{event[0].lower()}" AFTER {event} ON main."{table}" BEGIN {body} END')


def _current(q: Any, table: str, rowids: Sequence[int]) -> dict[int, tuple[str, str]]:
    """rowid -> (key JSON, row digest) for the given rows of ``table`` that exist."""
    key = _key_sql(_key_columns(q, table))
    out: dict[int, tuple[str, str]] = {}
    for start in range(0, len(rowids), CHUNK):
        chunk = list(rowids[start:start + CHUNK])
        cur = q.execute(f'SELECT rowid, {key}, * FROM main."{table}" WHERE rowid IN ({", ".join("?" for _ in chunk)})', chunk)  # noqa: S608 - schema names
        names = [d[0] for d in cur.description][2:]
        for rid, pk, *values in cur.fetchall():
            out[rid] = (pk, row_digest(table, names, values))
    return out


def _scan(q: Any, table: str) -> Iterator[tuple[int, str, str]]:
    """(rowid, key digest, row digest) for every current row of ``table``."""
    cur = q.execute(f'SELECT rowid, {_key_sql(_key_columns(q, table))}, * FROM main."{table}"')  # noqa: S608 - schema names
    names = [d[0] for d in cur.description][2:]
    for rid, pk, *values in cur:
        yield rid, key_digest(table, pk), row_digest(table, names, values)


def _meta_state(q: Any) -> tuple[int, int, str]:
    rows = _current(q, "installation_meta", [1])
    store_revision, epoch = q.execute("SELECT store_revision, tombstone_epoch FROM installation_meta WHERE singleton = 1").fetchone()
    return store_revision, epoch, rows[1][1]


def _append(q: Any, *, kind: str, rows: list[list[Any]], operation_ids: list[str], extra: dict[str, Any] | None = None) -> int:
    store_revision, epoch, metadata_hash = _meta_state(q)
    head = q.execute("SELECT sequence, entry_hash FROM revision_chain ORDER BY sequence DESC LIMIT 1").fetchone()
    sequence, previous = (1, GENESIS) if head is None else (head[0] + 1, head[1])
    rows.sort(key=lambda item: (item[0], item[1]))
    entry = {"entry_schema": ENTRY_SCHEMA, "kind": kind, "store_revision": store_revision, "metadata_hash": metadata_hash, "operation_ids": operation_ids, "rows": rows, **(extra or {})}
    text = _canon(entry).decode("utf-8")
    operation_id = operation_ids[0] if operation_ids else None
    purge = 1 if kind == "purge" else 0
    q.execute(
        "INSERT INTO revision_chain (sequence, previous_hash, operation_id, row_digests, purge_marker, tombstone_epoch, entry_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sequence, previous, operation_id, text, purge, epoch, entry_hash(sequence, previous, operation_id, text, purge, epoch)),
    )
    return sequence


def seal(conn: Any, *, purge: bool = False) -> int | None:
    """Append the transaction's entry (called just before COMMIT); None when it changed no chained row."""
    touched = conn.execute(f"SELECT tbl, pk, rid FROM {TOUCHED} ORDER BY seq").fetchall()
    if not touched:
        return None
    failpoints.hit(failpoints.CHAIN_BEFORE_SEAL)
    latest: dict[tuple[str, str], int] = {}
    for table, pk, rid in touched:
        latest[(table, pk)] = rid  # first-seen order, last rowid
    by_table: dict[str, list[tuple[str, int]]] = {}
    for (table, pk), rid in latest.items():
        by_table.setdefault(table, []).append((pk, rid))
    digests: dict[tuple[str, str], str | None] = {}
    for table, items in by_table.items():
        found = _current(conn, table, sorted({rid for _pk, rid in items}))
        for pk, rid in items:
            hit = found.get(rid)
            digests[(table, pk)] = hit[1] if hit is not None and hit[0] == pk else None
    rows = [[table, key_digest(table, pk), rid, digests[(table, pk)]] for (table, pk), rid in latest.items()]
    operation_ids = [json.loads(pk)[0] for (table, pk) in latest if table == "operations" and digests[(table, pk)] is not None]
    sequence = _append(conn, kind="purge" if purge else "mutation", rows=rows, operation_ids=operation_ids)
    conn.execute(f"DELETE FROM {TOUCHED}")
    failpoints.hit(failpoints.CHAIN_AFTER_SEAL)
    return sequence


def establish_baseline(q: Any, *, reason: str) -> int:
    """Append the baseline entry over every current row (a new full store, or chain activation on a preview store).

    Runs inside the caller's write transaction, after the profile is
    ``full``. It never invents entries for earlier mutations: verification
    reports a preview store's history before its baseline as ``not_chained``.
    """
    if reason not in BASELINE_REASONS:
        raise RecalithError("invalid_schema", f"a baseline reason is one of {BASELINE_REASONS}")
    if _profile(q) != "full":
        raise _unavailable()
    if q.execute("SELECT 1 FROM revision_chain LIMIT 1").fetchone() is not None:
        raise RecalithError("policy_refused", "the revision chain already has its baseline")
    tables = chained_tables(q)
    rows = [[table, key, rid, digest] for table in tables for rid, key, digest in _scan(q, table)]
    sequence = _append(q, kind="baseline", rows=rows, operation_ids=[], extra={"reason": reason, "tables": tables})
    if q.execute("SELECT 1 FROM temp.sqlite_master WHERE type = 'table' AND name = ?", (TOUCHED,)).fetchone() is not None:
        q.execute(f"DELETE FROM {TOUCHED}")  # the baseline covers whatever this transaction wrote before it
    return sequence


# --------------------------------------------------------------------------
# The verifier's checkpoint (private file; never the store)


def _checkpoint_path(root: Path | str) -> Path:
    return Path(root) / ".recalith" / CHECKPOINT


def read_checkpoint(root: Path | str, installation_id: str) -> dict[str, Any] | None:
    try:
        data = json.loads(_checkpoint_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None if not _checkpoint_path(root).exists() else {"malformed": True}
    if not isinstance(data, dict) or data.get("checkpoint_schema") != CHECKPOINT_SCHEMA or data.get("installation_id") != installation_id:
        return {"malformed": True}
    return data


def _write_checkpoint(root: Path | str, data: dict[str, Any]) -> None:
    path = _checkpoint_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)  # created 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(data, sort_keys=True, indent=1))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _trust(q: Any, cp: dict[str, Any] | None) -> tuple[str, dict[str, Any] | None]:
    if cp is None:
        return "missing", None
    if cp.get("malformed") or not isinstance(cp.get("sequence"), int) or not isinstance(cp.get("entry_hash"), str):
        return "untrusted", None
    row = q.execute("SELECT entry_hash FROM revision_chain WHERE sequence = ?", (cp["sequence"],)).fetchone()
    if row is None or row[0] != cp["entry_hash"]:
        return "untrusted", None
    return "trusted", cp


# --------------------------------------------------------------------------
# Verification


class _Findings:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.count = 0

    def add(self, code: str, *, sequence: int | None = None, table: str | None = None, key: str | None = None) -> None:
        self.count += 1
        if len(self.items) < MAX_FINDINGS:
            item: dict[str, Any] = {"code": code}
            if sequence is not None:
                item["sequence"] = sequence
            if table is not None:
                item["table"] = table
            if key is not None:
                item["key_digest"] = key
            self.items.append(item)


def _parse(row: tuple, findings: _Findings) -> dict[str, Any] | None:
    sequence, _previous, operation_id, text, purge, _epoch, _hash = row
    try:
        entry = json.loads(text)
        ok = (
            isinstance(entry, dict) and entry.get("entry_schema") == ENTRY_SCHEMA and entry.get("kind") in KINDS
            and isinstance(entry.get("store_revision"), int) and isinstance(entry.get("operation_ids"), list) and isinstance(entry.get("rows"), list)
            and all(isinstance(r, list) and len(r) == 4 and isinstance(r[0], str) and isinstance(r[1], str) and isinstance(r[2], int) and (r[3] is None or isinstance(r[3], str)) for r in entry["rows"])
            and purge == (1 if entry["kind"] == "purge" else 0)
            and operation_id == (entry["operation_ids"][0] if entry["operation_ids"] else None)
        )
    except (ValueError, TypeError):
        ok = False
    if not ok:
        findings.add("entry_malformed", sequence=sequence)
        return None
    return entry


def _link(rows: Sequence[tuple], *, first_sequence: int, previous: str, findings: _Findings) -> list[tuple[int, dict[str, Any]]]:
    """Re-link ``rows`` (ordered by sequence) from ``previous``; returns the parsed entries."""
    expected = first_sequence
    last_revision: int | None = None
    parsed: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        sequence, prev, operation_id, text, purge, epoch, stored = row
        if sequence != expected:
            findings.add("sequence_gap", sequence=sequence)
        if prev != previous:
            findings.add("chain_link_broken", sequence=sequence)
        if entry_hash(sequence, prev, operation_id, text, purge, epoch) != stored:
            findings.add("entry_hash_mismatch", sequence=sequence)
        entry = _parse(row, findings)
        if entry is not None:
            if last_revision is not None and entry["store_revision"] < last_revision:
                findings.add("store_revision_regressed", sequence=sequence)
            last_revision = entry["store_revision"]
            parsed.append((sequence, entry))
        expected, previous = sequence + 1, stored
    return parsed


def _baseline(rows: Sequence[tuple]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not rows:
        return None, None
    try:
        entry = json.loads(rows[0][3])
    except ValueError:
        return None, None
    if not isinstance(entry, dict) or entry.get("kind") != "baseline":
        return None, None
    return {"sequence": rows[0][0], "store_revision": entry.get("store_revision"), "reason": entry.get("reason")}, entry


def _latest(parsed: Iterable[tuple[int, dict[str, Any]]]) -> dict[str, tuple[str, int, str | None]]:
    out: dict[str, tuple[str, int, str | None]] = {}
    for _sequence, entry in parsed:
        for table, key, rid, digest in entry["rows"]:
            out[key] = (table, rid, digest)
    return out


def _check_touched(q: Any, latest: dict[str, tuple[str, int, str | None]], tables: set[str], findings: _Findings) -> None:
    by_table: dict[str, list[tuple[str, int, str | None]]] = {}
    for key, (table, rid, digest) in latest.items():
        by_table.setdefault(table, []).append((key, rid, digest))
    for table, items in sorted(by_table.items()):
        if table not in tables:
            for key, _rid, digest in items:
                if digest is not None:
                    findings.add("unlogged_deletion", table=table, key=key)
            continue
        found = _current(q, table, sorted({rid for _k, rid, _d in items}))
        for key, rid, digest in items:
            hit = found.get(rid)
            present = hit is not None and key_digest(table, hit[0]) == key
            if digest is None:
                if present:
                    findings.add("unlogged_row", table=table, key=key)
            elif not present:
                findings.add("unlogged_deletion", table=table, key=key)
            elif hit[1] != digest:
                findings.add("row_digest_mismatch", table=table, key=key)


def _check_all(q: Any, latest: dict[str, tuple[str, int, str | None]], tables: list[str], findings: _Findings, progress: Callable[[dict[str, Any]], None] | None) -> int:
    scanned = 0
    seen: set[str] = set()
    for index, table in enumerate(tables):
        for _rid, key, digest in _scan(q, table):
            scanned += 1
            seen.add(key)
            recorded = latest.get(key)
            if recorded is None or recorded[2] is None or recorded[0] != table:
                findings.add("unlogged_row", table=table, key=key)
            elif recorded[2] != digest:
                findings.add("row_digest_mismatch", table=table, key=key)
        if progress is not None:
            progress({"table": table, "tables_done": index + 1, "tables": len(tables), "rows_scanned": scanned})
    for key, (table, _rid, digest) in latest.items():
        if digest is not None and key not in seen:
            findings.add("unlogged_deletion", table=table, key=key)
    return scanned


def _verify(q: Any, cp: dict[str, Any] | None, *, full: bool, progress: Callable[[dict[str, Any]], None] | None) -> dict[str, Any]:
    started = time.monotonic()
    findings = _Findings()
    rows = q.execute("SELECT sequence, previous_hash, operation_id, row_digests, purge_marker, tombstone_epoch, entry_hash FROM revision_chain ORDER BY sequence").fetchall()
    trust, trusted = _trust(q, cp)
    baseline, _entry = _baseline(rows)
    if baseline is None:
        findings.add("missing_baseline", sequence=rows[0][0] if rows else None)
    if full or trusted is None:
        start_after, previous = 0, GENESIS
    else:
        start_after, previous = trusted["sequence"], trusted["entry_hash"]
    in_range = [r for r in rows if r[0] > start_after]
    parsed = _link(in_range, first_sequence=start_after + 1, previous=previous, findings=findings)
    tables = chained_tables(q)
    latest = _latest(parsed)
    if full:
        rows_checked = _check_all(q, latest, tables, findings, progress)
    else:
        _check_touched(q, latest, set(tables), findings)
        rows_checked = len(latest)
    store_revision = q.execute("SELECT store_revision FROM installation_meta WHERE singleton = 1").fetchone()[0]
    if parsed and in_range and parsed[-1][0] == in_range[-1][0] and parsed[-1][1]["store_revision"] != store_revision:
        findings.add("head_store_revision_mismatch", sequence=in_range[-1][0])
    clean = findings.count == 0
    complete = clean and (full or (trust == "trusted" and bool(trusted and trusted.get("complete"))))
    head = rows[-1] if rows else None
    head_revision = None
    if head is not None:
        try:
            head_revision = json.loads(head[3]).get("store_revision")
        except (ValueError, AttributeError):
            head_revision = None
    return {
        "state": "verified" if clean else "findings",
        "mode": "full" if full else "incremental",
        "head": None if head is None else {"sequence": head[0], "entry_hash": head[6], "store_revision": head_revision},
        "baseline": baseline,
        "pre_baseline_history": None if baseline is None else ("not_chained" if baseline["reason"] == "activation" else "none"),
        "checkpoint": {"state": trust, "sequence": trusted["sequence"] if trusted else None, "complete": bool(trusted and trusted.get("complete"))},
        "checked_range": {"from_sequence": in_range[0][0], "to_sequence": in_range[-1][0]} if in_range else None,
        "entries_checked": len(in_range),
        "rows_checked": rows_checked,
        "purge_entries": sum(1 for r in in_range if r[4] == 1),
        "coverage": "every_current_row" if full else "rows_touched_in_range",
        "complete_coverage": complete,
        "full_integrity_required": not complete,
        "findings": findings.items,
        "finding_count": findings.count,
        "cost": {"entries": len(in_range), "rows_scanned": rows_checked if full else 0, "tables": len(tables) if full else len({t for t, _r, _d in latest.values()}), "seconds": round(time.monotonic() - started, 3)},
    }


def verify(ctx: InstallationContext, *, full: bool = False, persist: bool = True, progress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Check the chain and the rows it covers in one read snapshot (read-only store; content-free report).

    A clean check advances the private checkpoint to the head; ``complete``
    only when it descends from a clean full check. A check with findings never
    advances it and records its codes as the last result.
    """
    from recalith.storage import db

    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        if _profile(view) != "full":
            raise _unavailable()
        cp = read_checkpoint(ctx.root, ctx.installation_id)
        report = _verify(view, cp, full=full, progress=progress)
    report["checked_at"] = utc_now()
    if persist:
        last = {"state": report["state"], "mode": report["mode"], "finding_count": report["finding_count"], "codes": sorted({f["code"] for f in report["findings"]}), "checked_at": report["checked_at"]}
        head = report["head"]
        if report["state"] == "verified" and head is not None:
            data = {
                "checkpoint_schema": CHECKPOINT_SCHEMA, "installation_id": ctx.installation_id, "sequence": head["sequence"], "entry_hash": head["entry_hash"],
                "store_revision": head["store_revision"], "complete": report["complete_coverage"], "mode": report["mode"], "verified_at": report["checked_at"], "last_result": last,
            }
        else:
            data = dict(cp) if cp is not None and not cp.get("malformed") else {"checkpoint_schema": CHECKPOINT_SCHEMA, "installation_id": ctx.installation_id}
            data["last_result"] = last
        _write_checkpoint(ctx.root, data)
    return report


def content_digest(q: Any) -> str:
    """One digest over every row of every chained table (either profile): equal exactly when no such row changed.

    The transition compares the live store with its staged snapshot before
    activating (decision 0026); read inside one snapshot by the caller.
    """
    h = hashlib.sha256()
    for table in chained_tables(q):
        for _rid, key, digest in sorted(_scan(q, table), key=lambda item: item[1]):
            h.update(f"{table}\0{key}\0{digest}\n".encode("utf-8"))
    return h.hexdigest()


def verify_view(q: Any) -> dict[str, Any]:
    """A full check of a store that is not yet the live one (the transition's staged store): nothing is persisted."""
    if _profile(q) != "full":
        raise _unavailable()
    report = _verify(q, None, full=True, progress=None)
    report["checked_at"] = utc_now()
    return report


def record_checked_head(root: Path | str, installation_id: str, report: dict[str, Any], *, live_head: tuple[int, str] | None) -> bool:
    """Persist a clean full check of the staged store as the live store's checkpoint, only if the live chain has that exact head.

    The transition verifies its staged store over every row before activating
    it; after the swap the live store is that file, so the check covers it. A
    head that differs (a later write, a restore) records nothing: the next
    ``doctor`` starts from no checkpoint.
    """
    head = report.get("head")
    if report.get("state") != "verified" or not report.get("complete_coverage") or head is None or live_head != (head["sequence"], head["entry_hash"]):
        return False
    last = {"state": "verified", "mode": "full", "finding_count": 0, "codes": [], "checked_at": report["checked_at"]}
    _write_checkpoint(root, {
        "checkpoint_schema": CHECKPOINT_SCHEMA, "installation_id": installation_id, "sequence": head["sequence"], "entry_hash": head["entry_hash"],
        "store_revision": head["store_revision"], "complete": True, "mode": "full", "verified_at": report["checked_at"], "last_result": last,
    })
    return True


def chain_state(ctx: InstallationContext, q: Any | None = None) -> dict[str, Any]:
    """What health reports without verifying (read-only, O(1) chain reads): head, baseline, checkpoint, last result."""
    from recalith.storage import db

    def read(view: Any) -> dict[str, Any]:
        if _profile(view) != "full":
            return {"state": UNAVAILABLE}
        head = view.execute("SELECT sequence, entry_hash FROM revision_chain ORDER BY sequence DESC LIMIT 1").fetchone()
        first = view.execute("SELECT sequence, previous_hash, operation_id, row_digests, purge_marker, tombstone_epoch, entry_hash FROM revision_chain ORDER BY sequence LIMIT 1").fetchall()
        baseline, _entry = _baseline(first)
        cp = read_checkpoint(ctx.root, ctx.installation_id)
        trust, trusted = _trust(view, cp)
        last = (cp or {}).get("last_result") if cp is not None and not cp.get("malformed") else None
        return {
            "state": "chained" if baseline is not None else "missing_baseline",
            "head_sequence": head[0] if head else 0,
            "baseline": baseline,
            "checkpoint": {"state": trust, "sequence": trusted["sequence"] if trusted else None, "complete": bool(trusted and trusted.get("complete")), "verified_at": trusted.get("verified_at") if trusted else None},
            "entries_since_checkpoint": (head[0] if head else 0) - (trusted["sequence"] if trusted else 0),
            "last_result": last,
        }

    if q is not None:
        return read(q)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        return read(view)


__all__ = [
    "arm", "seal", "establish_baseline", "verify", "verify_view", "record_checked_head", "content_digest", "chain_state", "read_checkpoint", "chained_tables", "row_digest", "key_digest", "entry_hash",
    "GENESIS", "CHECKPOINT", "ENTRY_SCHEMA",
]
