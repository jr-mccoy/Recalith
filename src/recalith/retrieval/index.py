"""Lexical and structural candidate indexes (SYSTEM_SPEC §8.1; DATA_CONTRACTS §10; decision 0013).

The index is a disposable projection of the live record heads, maintained by
the worker's deterministic projection step (:func:`refresh`) and never by the
transactions that change the records: a crash between a record change and the
next refresh leaves the index behind, never ahead, and the reader sees the
lag (``indexed_store_revision`` < the store revision) and covers it directly
(:func:`lagging`). Writing it never advances the store revision or the
guidance epoch: it is not authoritative state.

One row per indexed live head in ``retrieval_docs`` carries the eligibility
hot columns (status, workspace and task scope) so status and scope mismatches
are excluded *before* any candidate cap, and the record's lexical terms.
``lexical_index`` holds each word term and each structural key (``path:``,
``family:``, ``tool:``, ``subject:``) per record. When the SQLite build
provides FTS5 (detected, never assumed) the virtual table ``lexical_fts``
is the lexical candidate source; otherwise the token index is
(``lexical_backend`` in ``projection_state``). Both use the same tokenizer
(:func:`recalith.fast.context.terms`), so they return the same candidates.
"""

from __future__ import annotations

import functools
import json
import math
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable

from recalith.contracts.common import InstallationContext, canonical_json, utc_now
from recalith.fast import context as fc
from recalith.fast import failpoints
from recalith.storage.db import Store, Txn

CLAIM_STATUSES = ("candidate", "active", "disputed")
TASK_STATUSES = ("active", "paused")
EPISODE_STATES = ("open", "settled")
HEADS = {
    "claim": ("claim_heads", "claim_revisions", "claim_id", "status", CLAIM_STATUSES),
    "task": ("task_heads", "task_revisions", "task_id", "status", TASK_STATUSES),
    "episode": ("episode_heads", "episode_revisions", "episode_id", "state", EPISODE_STATES),
}
STRUCTURAL = ("path:", "family:", "tool:", "subject:")
INDEX_BATCH = 500  # heads reindexed per write transaction (whole store revisions)
LAG_LIMIT = 512  # heads changed since the index that a reader covers directly; more is degraded


@functools.lru_cache(maxsize=1)
def fts5_available() -> bool:
    """Capability detection: can this SQLite build create an FTS5 table?"""
    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE probe USING fts5(body)")
            return True
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def backend_for(prefer_fts: bool | None = None) -> str:
    use = fts5_available() if prefer_fts is None else (prefer_fts and fts5_available())
    return "fts5" if use else "tokens"


# --------------------------------------------------------------------------
# Documents


def _supported_texts(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        if isinstance(value.get("text"), str) and "basis" in value:
            yield value["text"]
        for item in value.values():
            yield from _supported_texts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _supported_texts(item)


@dataclass
class Doc:
    kind: str
    record_id: str
    revision: int
    status: str
    workspace_ids: list[str] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)
    words: list[str] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)


def document(kind: str, record_id: str, revision: int, status: str, body: dict[str, Any], *, workspace_id: str | None = None) -> Doc:
    """The indexed form of one live head: words from its servable text, structural keys from its typed fields."""
    if kind == "claim":
        key = body.get("proposition_key") or {}
        text = " ".join([body["proposition"], key.get("subject", ""), key.get("predicate", ""), body["kind"].replace("_", " "), *_supported_texts([body.get("failure"), body.get("procedure")])])
        scope = body.get("scope") or {}
        paths = list(scope.get("paths") or []) + [c["value"] for c in body.get("conditions") or [] if c["kind"] == "path"] + [d["key"] for d in body.get("dependencies") or [] if d["kind"] == "file"]
        keys = [f"path:{p}" for p in paths] + [f"tool:{c['value']}" for c in body.get("conditions") or [] if c["kind"] == "tool"]
        family = (body.get("failure") or {}).get("action_family_digest")
        if family:
            keys.append(f"family:{family}")
        if key.get("subject"):
            keys.append("subject:" + key["subject"].casefold())
        return Doc(kind, record_id, revision, status, list(scope.get("workspace_ids") or []), list(scope.get("task_ids") or []), fc.terms(text), sorted(set(keys)))
    if kind == "task":
        text = " ".join([body.get("title", ""), *_supported_texts([body.get("objective"), body.get("constraints"), body.get("blockers"), body.get("pending_actions"), body.get("next_action"), body.get("open_questions")])])
        return Doc(kind, record_id, revision, status, [workspace_id] if workspace_id else [], [record_id], fc.terms(text), [])
    text = " ".join([body.get("title", ""), *_supported_texts([body.get("objective"), body.get("outcome"), body.get("unresolved")])])
    return Doc(kind, record_id, revision, status, [workspace_id] if workspace_id else [], [body["task_id"]], fc.terms(text), [])


def _workspace_of(q: Any, kind: str, record_id: str, body: dict[str, Any]) -> str | None:
    task_id = record_id if kind == "task" else body.get("task_id")
    row = q.execute("SELECT workspace_id FROM task_heads WHERE task_id = ?", (task_id,)).fetchone() if task_id else None
    return row[0] if row else None


def changed_heads(q: Any, since: int) -> list[tuple[str, str, int, str]]:
    """(kind, id, revision, status) of every head whose current revision was written after ``since``."""
    return [h[:4] for h in _changed(q, since)]


def _changed(q: Any, since: int) -> list[tuple[str, str, int, str, int]]:
    out = []
    for kind, (heads, revisions, key, column, _ok) in HEADS.items():
        rows = q.execute(
            f"SELECT h.{key}, h.revision, h.{column}, r.created_store_revision FROM {heads} h JOIN {revisions} r ON r.{key} = h.{key} AND r.revision = h.revision "  # noqa: S608 - fixed names
            f"WHERE r.created_store_revision > ? ORDER BY h.{key}",
            (since,),
        ).fetchall()
        out += [(kind, r[0], r[1], r[2], r[3]) for r in rows]
    return sorted(out, key=lambda h: (h[4], h[0], h[1]))


def eligible(kind: str, status: str) -> bool:
    return status in HEADS[kind][4]


def load_doc(q: Any, kind: str, record_id: str, revision: int, status: str) -> Doc | None:
    if not eligible(kind, status):
        return None
    table, key = HEADS[kind][1], HEADS[kind][2]
    row = q.execute(f"SELECT body FROM {table} WHERE {key} = ? AND revision = ?", (record_id, revision)).fetchone()  # noqa: S608
    if row is None or row[0] is None:
        return None
    body = json.loads(row[0])
    if kind == "task" and body.get("redirect_task_id"):
        return None  # a linked placeholder is never a candidate
    return document(kind, record_id, revision, status, body, workspace_id=_workspace_of(q, kind, record_id, body))


# --------------------------------------------------------------------------
# Maintenance (worker projection step)


def state(q: Any) -> dict[str, Any] | None:
    row = q.execute(
        "SELECT lexical_backend, indexed_store_revision, views_store_revision, views_guidance_epoch, views_policy_revision, views_tombstone_epoch, "
        "lookup_guidance_epoch, lookup_policy_revision, lookup_tombstone_epoch FROM projection_state WHERE singleton = 1"
    ).fetchone()
    if row is None:
        return None
    keys = ("backend", "indexed", "views_store", "views_guidance", "views_policy", "views_tombstone", "lookup_guidance", "lookup_policy", "lookup_tombstone")
    return dict(zip(keys, row, strict=True))


def _ensure_fts(txn: Txn) -> None:
    txn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS lexical_fts USING fts5(body, tokenize = 'unicode61 remove_diacritics 0')")


def _remove(txn: Txn, kind: str, record_id: str, backend: str) -> None:
    row = txn.one("SELECT rowid FROM retrieval_docs WHERE record_kind = ? AND record_id = ?", (kind, record_id))
    if row is None:
        return
    if backend == "fts5":
        txn.execute("DELETE FROM lexical_fts WHERE rowid = ?", (row[0],))
    txn.execute("DELETE FROM lexical_index WHERE record_kind = ? AND record_id = ?", (kind, record_id))
    txn.execute("DELETE FROM retrieval_docs WHERE rowid = ?", (row[0],))


def _insert(txn: Txn, doc: Doc, backend: str, store_revision: int) -> None:
    cur = txn.execute(
        "INSERT INTO retrieval_docs (record_kind, record_id, record_revision, status, workspace_ids, task_ids, terms, term_count, store_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (doc.kind, doc.record_id, doc.revision, doc.status, canonical_json(doc.workspace_ids).decode(), canonical_json(doc.task_ids).decode(),
         canonical_json(doc.words).decode(), len(doc.words), store_revision),
    )
    if backend == "fts5" and doc.words:
        txn.execute("INSERT INTO lexical_fts (rowid, body) VALUES (?, ?)", (cur.lastrowid, " ".join(doc.words)))
    for term in [*doc.words, *doc.keys]:
        txn.execute("INSERT INTO lexical_index (term, record_kind, record_id, record_revision, store_revision) VALUES (?, ?, ?, ?, ?)", (term, doc.kind, doc.record_id, doc.revision, store_revision))


def refresh(store: Store, ctx: InstallationContext, *, now: str | None = None, prefer_fts: bool | None = None) -> int:
    """Bring the index up to the current store revision; returns the number of heads reindexed.

    One bounded write transaction: the changed heads' rows and the covered
    revision commit together, so the index never claims coverage it lacks.
    At most :data:`INDEX_BATCH` heads (whole store revisions, oldest first) are
    reindexed per call; a larger backlog is covered over several polls while
    readers cover the lag directly. Nothing here
    is authoritative state (no store revision or guidance epoch advance).
    """
    with store.transaction() as txn:
        current = state(txn)
        wanted = backend_for(prefer_fts) if current is None or prefer_fts is not None else current["backend"]
        if current is not None and current["backend"] == wanted and current["indexed"] == txn.meta.store_revision:
            return 0
        rebuild = current is None or current["backend"] != wanted
        if wanted == "fts5":
            _ensure_fts(txn)
        if rebuild:
            if current is not None and current["backend"] == "fts5" and fts5_available():
                txn.execute("DELETE FROM lexical_fts")
            txn.execute("DELETE FROM lexical_index")
            txn.execute("DELETE FROM retrieval_docs")
        since = 0 if rebuild else current["indexed"]  # type: ignore[index]
        heads = _changed(txn, since)
        covered = txn.meta.store_revision
        if len(heads) > INDEX_BATCH:
            # Bounded write transactions: whole store revisions, oldest first; the next poll continues from here.
            covered = heads[INDEX_BATCH - 1][4]
            heads = [h for h in heads if h[4] <= covered]
        for kind, record_id, revision, status, _created in heads:
            _remove(txn, kind, record_id, wanted)
            doc = load_doc(txn, kind, record_id, revision, status)
            if doc is not None:
                _insert(txn, doc, wanted, txn.meta.store_revision)
        txn.execute(
            "INSERT INTO projection_state (singleton, lexical_backend, indexed_store_revision, updated_at) VALUES (1, ?, ?, ?) "
            "ON CONFLICT(singleton) DO UPDATE SET lexical_backend = excluded.lexical_backend, indexed_store_revision = excluded.indexed_store_revision, updated_at = excluded.updated_at",
            (wanted, covered, now or utc_now()),
        )
        failpoints.hit(failpoints.INDEX_AFTER_REFRESH)
        return len(heads)


# --------------------------------------------------------------------------
# Reading (service retrieval)


@dataclass
class Hit:
    kind: str
    record_id: str
    revision: int
    status: str
    workspace_ids: list[str]
    task_ids: list[str]
    words: list[str]
    keys: set[str] = field(default_factory=set)


def lagging(q: Any, indexed: int) -> tuple[list[Doc], bool]:
    """Heads changed since the index covered them, as documents (bounded); True when more lag than that."""
    heads = changed_heads(q, indexed)
    docs = []
    for kind, record_id, revision, status in heads[:LAG_LIMIT]:
        doc = load_doc(q, kind, record_id, revision, status)
        docs.append(doc if doc is not None else Doc(kind, record_id, revision, status))
    return docs, len(heads) > LAG_LIMIT


def _fts_query(words: list[str]) -> str:
    return " OR ".join('"' + w.replace('"', '""') + '"' for w in words)


def lexical_ids(q: Any, words: list[str], backend: str) -> set[tuple[str, str]]:
    """Records matching any query word, from FTS5 or the token index (same tokenizer, same candidates)."""
    if not words:
        return set()
    if backend == "fts5":
        rows = q.execute(
            "SELECT d.record_kind, d.record_id FROM lexical_fts f JOIN retrieval_docs d ON d.rowid = f.rowid WHERE lexical_fts MATCH ?", (_fts_query(words),)
        ).fetchall()
        return {(r[0], r[1]) for r in rows}
    marks = ",".join("?" for _ in words)
    rows = q.execute(f"SELECT DISTINCT record_kind, record_id FROM lexical_index WHERE term IN ({marks})", tuple(words)).fetchall()  # noqa: S608
    return {(r[0], r[1]) for r in rows}


def structural_ids(q: Any, keys: list[str]) -> dict[tuple[str, str], set[str]]:
    if not keys:
        return {}
    marks = ",".join("?" for _ in keys)
    out: dict[tuple[str, str], set[str]] = {}
    for term, kind, rid in q.execute(f"SELECT term, record_kind, record_id FROM lexical_index WHERE term IN ({marks})", tuple(keys)).fetchall():  # noqa: S608
        out.setdefault((kind, rid), set()).add(term)
    return out


def docs(q: Any, ids: Iterable[tuple[str, str]]) -> dict[tuple[str, str], Hit]:
    out = {}
    for kind, rid in sorted(set(ids)):
        row = q.execute("SELECT record_revision, status, workspace_ids, task_ids, terms FROM retrieval_docs WHERE record_kind = ? AND record_id = ?", (kind, rid)).fetchone()
        if row is not None:
            out[(kind, rid)] = Hit(kind, rid, row[0], row[1], json.loads(row[2]), json.loads(row[3]), json.loads(row[4]))
    return out


def idf(q: Any, words: list[str]) -> dict[str, float]:
    """Inverse document frequency ``1 + ln(N / df)`` over indexed documents (deterministic)."""
    if not words:
        return {}
    n = q.execute("SELECT COUNT(*) FROM retrieval_docs").fetchone()[0] or 1
    marks = ",".join("?" for _ in words)
    df = dict(q.execute(f"SELECT term, COUNT(DISTINCT record_kind || ':' || record_id) FROM lexical_index WHERE term IN ({marks}) GROUP BY term", tuple(words)).fetchall())  # noqa: S608
    return {w: round(1.0 + math.log(max(n, 1) / max(df.get(w, 1), 1)), 6) for w in words}
