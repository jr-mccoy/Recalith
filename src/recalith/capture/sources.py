"""Capture-source registration, cursors and tail recovery (SYSTEM_SPEC §5.1–5.2).

A source is one exact file registered from an actual session payload; the
engine never scans directories looking for material. Registration records the
canonical path and file identity. Reading opens exactly that path without
following a final symlink and re-checks the opened object.

Cursor rules:

* A source cursor is ``{generation, offset, identity, tail_digest, line}``.
  ``offset`` is the byte offset just past the last *complete* line consumed;
  a partial trailing line is left for a later read, so it is read once, whole.
* The cursor advances only after the segment holding those events is durably
  published (``capture`` writes ``spool/cursors/<source_id>.json``). Ingestion
  records the same proposal as the source's ingested cursor in the store.
  Recovery resumes from the furthest of the two, so a lost cursor write only
  repeats events, which identity deduplicates.
* Truncation, rewriting or replacement of the file starts a new generation
  from offset 0 and reports an explicit gap; nothing is invented to fill it.
  A replacement that still holds the consumed bytes (an atomic-save rewrite)
  continues in the same generation.

Records without a host event identity get the key
``<source_id>:<generation>:<byte offset>:<subindex>`` (DATA_CONTRACTS §2.1).
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from recalith.capture.normalize import RawEvent, normalize_event
from recalith.contracts.common import InstallationContext, canonical_json, derived_id, utc_now
from recalith.contracts.events import EventEnvelope
from recalith.core.paths import canonical
from recalith.errors import RecalithError
from recalith.storage import spool
from recalith.storage.db import Store, Txn

SOURCE_KINDS = frozenset({"transcript_jsonl"})
TAIL_DIGEST_BYTES = 256
MAX_READ_BYTES = 1024 * 1024


@dataclass(frozen=True)
class SourceRegistration:
    source_id: str
    adapter_id: str
    session_id: str | None
    source_kind: str
    path: Path
    identity: str


@dataclass(frozen=True)
class LineContext:
    source_id: str
    generation: int
    offset: int
    line: int

    def fallback_key(self, subindex: int = 0) -> str:
        return f"{self.source_id}:{self.generation}:{self.offset}:{subindex}"


LineParser = Callable[[dict[str, Any], LineContext], list[RawEvent]]


@dataclass
class TailRead:
    events: list[EventEnvelope]
    cursor: dict[str, Any]
    advanced: bool
    gaps: dict[str, int] = field(default_factory=dict)
    partial_tail: bool = False

    def gap(self, code: str, n: int = 1) -> None:
        self.gaps[code] = self.gaps.get(code, 0) + n


def _identity(st: os.stat_result) -> str:
    return f"{st.st_dev}:{st.st_ino}"


def _exact_path(path: Path | str) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raise RecalithError("policy_refused", "source paths are registered as exact absolute paths from session payloads")
    # Canonicalize the parent only: a symlink as the registered file itself is refused.
    return canonical(raw.parent) / raw.name


def source_id_for(ctx: InstallationContext, adapter_id: str, locator: str) -> str:
    return derived_id("src", [ctx.installation_id, adapter_id, locator])


def ensure_session(txn: Txn, ctx: InstallationContext, *, session_id: str, adapter_id: str, host_session_id: str, started_at: str | None = None) -> None:
    txn.execute(
        "INSERT OR IGNORE INTO sessions (session_id, adapter_id, host_session_id, workspace_id, state, started_at) VALUES (?, ?, ?, ?, 'active', ?)",
        (session_id, adapter_id, host_session_id, ctx.workspace_id, started_at),
    )


def register_source(store: Store, ctx: InstallationContext, *, adapter_id: str, path: Path | str, session_id: str, host_session_id: str, source_kind: str = "transcript_jsonl") -> SourceRegistration:
    """Register one exact session source file; idempotent for the same path."""
    if source_kind not in SOURCE_KINDS:
        raise RecalithError("invalid_schema", "unsupported capture source kind")
    exact = _exact_path(path)
    try:
        st = os.lstat(exact)
    except OSError as exc:
        raise RecalithError("policy_refused", "source file does not exist") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise RecalithError("policy_refused", "a capture source must be a regular file, not a link or directory")
    locator = str(exact)
    source_id = source_id_for(ctx, adapter_id, locator)
    identity = _identity(st)
    with store.transaction() as txn:
        ensure_session(txn, ctx, session_id=session_id, adapter_id=adapter_id, host_session_id=host_session_id)
        txn.execute(
            "INSERT OR IGNORE INTO capture_sources (source_id, adapter_id, session_id, source_kind, locator, coverage, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source_id, adapter_id, session_id, source_kind, locator, canonical_json({"registered_identity": identity}).decode(), utc_now()),
        )
        txn.mutated(serving_relevant=False)
    return SourceRegistration(source_id, adapter_id, session_id, source_kind, exact, identity)


def get_source(store: Store, source_id: str) -> SourceRegistration | None:
    with store.read() as view:
        row = view.execute("SELECT source_id, adapter_id, session_id, source_kind, locator, coverage FROM capture_sources WHERE source_id = ?", (source_id,)).fetchone()
    if row is None:
        return None
    return SourceRegistration(row[0], row[1], row[2], row[3], Path(row[4]), json.loads(row[5]).get("registered_identity", ""))


def stored_cursors(store: Store, source_id: str) -> list[dict[str, Any]]:
    with store.read() as view:
        row = view.execute("SELECT durable_cursor, ingested_cursor FROM capture_sources WHERE source_id = ?", (source_id,)).fetchone()
    return [json.loads(v) for v in row] if row else []


def current_cursor(store: Store, ctx: InstallationContext, source_id: str) -> dict[str, Any]:
    """The furthest durable position known from the cursor file or the store."""
    candidates = [c for c in stored_cursors(store, source_id) if c]
    file_cursor = spool.read_cursor(spool.SpoolDirs(ctx.root), source_id)
    if file_cursor:
        candidates.append(file_cursor)
    return max(candidates, key=spool.cursor_order) if candidates else {}


def apply_cursor(txn: Txn, source_id: str, cursor: dict[str, Any]) -> bool:
    """Ingestion: record a published cursor proposal; never moves backwards."""
    row = txn.one("SELECT durable_cursor, ingested_cursor FROM capture_sources WHERE source_id = ?", (source_id,))
    if row is None:
        return False
    durable, ingested = json.loads(row[0]), json.loads(row[1])
    if ingested and spool.cursor_order(ingested) >= spool.cursor_order(cursor):
        return True
    new_durable = cursor if not durable or spool.cursor_order(cursor) > spool.cursor_order(durable) else durable
    txn.execute(
        "UPDATE capture_sources SET durable_cursor = ?, ingested_cursor = ? WHERE source_id = ?",
        (canonical_json(new_durable).decode(), canonical_json(cursor).decode(), source_id),
    )
    txn.mutated(serving_relevant=False)
    return True


# --------------------------------------------------------------------------
# Tail reading


def _open_exact(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RecalithError("policy_refused", "registered source could not be opened safely") from exc
    try:
        opened = os.fstat(fd)
        current = os.lstat(path)
        if not stat.S_ISREG(opened.st_mode) or stat.S_ISLNK(current.st_mode) or _identity(opened) != _identity(current):
            raise RecalithError("policy_refused", "registered source is not the regular file that was opened")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _pread(fd: int, size: int, offset: int) -> bytes:
    if hasattr(os, "pread"):
        return os.pread(fd, size, offset)
    os.lseek(fd, offset, os.SEEK_SET)  # Windows has no pread
    return os.read(fd, size)


def _tail_digest(fd: int, offset: int) -> str:
    start = max(0, offset - TAIL_DIGEST_BYTES)
    return hashlib.sha256(_pread(fd, offset - start, start)).hexdigest()


def read_tail(ctx: InstallationContext, registration: SourceRegistration, cursor: dict[str, Any], parse_line: LineParser, *, max_bytes: int = MAX_READ_BYTES) -> TailRead:
    """Read complete new records after ``cursor``; never advances past a partial line."""
    fd = _open_exact(registration.path)
    try:
        st = os.fstat(fd)
        identity, size = _identity(st), st.st_size
        generation = int(cursor.get("generation", 0))
        offset = int(cursor.get("offset", 0))
        line_no = int(cursor.get("line", 0))
        result = TailRead(events=[], cursor=dict(cursor), advanced=False)
        if cursor:
            prefix_kept = size >= offset and _tail_digest(fd, offset) == cursor.get("tail_digest")
            if cursor.get("identity") not in (None, identity):
                if not prefix_kept:  # an atomic-save rewrite that kept the consumed bytes is no gap
                    result.gap("source_replaced")
                    generation, offset, line_no = generation + 1, 0, 0
            elif size < offset:
                result.gap("source_truncated")
                generation, offset, line_no = generation + 1, 0, 0
            elif not prefix_kept:
                result.gap("source_rewritten")
                generation, offset, line_no = generation + 1, 0, 0
        data = _pread(fd, max_bytes, offset)
        last_newline = data.rfind(b"\n")
        complete = data[: last_newline + 1] if last_newline >= 0 else b""
        consumed = len(complete)
        if not complete and len(data) >= max_bytes:
            # A single record larger than the read window: skip it explicitly.
            skip = offset + len(data)
            while True:
                more = _pread(fd, max_bytes, skip)
                newline = more.find(b"\n")
                if newline >= 0:
                    consumed = skip + newline + 1 - offset
                    result.gap("oversized_record")
                    line_no += 1
                    break
                if len(more) < max_bytes:
                    break
                skip += len(more)
        position = offset
        for raw_line in complete.split(b"\n")[:-1] if complete else []:
            line_start = position
            position += len(raw_line) + 1
            line_no += 1
            text = raw_line.rstrip(b"\r")
            if not text.strip():
                continue
            try:
                record = json.loads(text.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                result.gap("malformed_record")
                continue
            if not isinstance(record, dict):
                result.gap("malformed_record")
                continue
            line_ctx = LineContext(registration.source_id, generation, line_start, line_no)
            for raw_event in parse_line(record, line_ctx):
                try:
                    envelopes, _notes = normalize_event(ctx, raw_event)
                except RecalithError as exc:
                    result.gap(f"event_refused:{exc.code}")
                    continue
                result.events.extend(envelopes)
        new_offset = offset + consumed
        result.partial_tail = offset + len(data) > new_offset and offset + len(data) >= size
        result.cursor = {"generation": generation, "offset": new_offset, "identity": identity, "tail_digest": _tail_digest(fd, new_offset), "line": line_no}
        result.advanced = not cursor or spool.cursor_order(result.cursor) != spool.cursor_order(cursor) or cursor.get("identity") != identity
        return result
    finally:
        os.close(fd)


def call_events(store: Store, session_id: str, tool_call_id: str) -> list[EventEnvelope]:
    """Tool events of one call in commit order: a late result joins its own call."""
    from recalith.storage.repository import event_from_row

    with store.read() as view:
        rows = view.execute(
            "SELECT envelope, payload, payload_state FROM events WHERE session_id = ? AND kind IN ('tool_started', 'tool_finished') ORDER BY commit_sequence",
            (session_id,),
        ).fetchall()
    found = []
    for row in rows:
        env = event_from_row(row)
        if env is not None and env.payload.get("tool_call_id") == tool_call_id:
            found.append(env)
    return found
