"""Pre-serialized context views for the stdlib hook compiler (SYSTEM_SPEC §5.1.1, §8.3; decision 0013).

Standard library and ``recalith.fast`` only; nothing here imports Pydantic,
``packaging``, the service layer or the full search/ranking modules. Every
read is a bounded read-only SQLite snapshot: ``mode=ro`` (never
``immutable=1`` on a live WAL store), ``PRAGMA query_only``, ``busy_timeout
= 0`` and an authorizer that denies every write, so the hook can neither
write, wait for a lock nor run recovery or a checkpoint; any failure to
establish the snapshot immediately is ``store_snapshot_unavailable`` and an
empty packet, never an unchecked cache.

:func:`compile_packet` serves the worker's view for the exact workspace, task
and purpose only while its guidance, policy and tombstone epochs equal the
live store's (store-revision-only bookkeeping keeps it valid). Otherwise, with
at least 60 ms left, it reads at most 32 pre-rendered fallback rows and keeps
only those whose record head is unchanged and still servable, whose support
events still hold available evidence and which no newer tombstone names; a
policy change has no fallback. A prompt compile, on either path, adds at
most 16 live-filtered rows of the worker's lexical lookup
(:mod:`recalith.fast.lookup`, decision 0021) when at least 60 ms remain.
Conditions are evaluated live with the stdlib
twin (PEP 440 results reused only for the exact consulted value), failure
lessons get the bounded live dependency check, and the packet must pass the
fresh final fence (:mod:`recalith.fast.fence`). A stale projection is never
served as current.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.parse

from recalith.fast import context as fc
from recalith.fast import lookup
from recalith.fast.wire import is_valid

STATE_DB = os.path.join(".recalith", "state", "memory.sqlite")
MAX_REDIRECTS = 8
_ALLOWED = frozenset({sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_TRANSACTION})
_READ_PRAGMAS = frozenset({"query_only", "busy_timeout", "user_version", "schema_version", "data_version"})


class SnapshotUnavailable(Exception):
    pass


def _authorizer(action, arg1, arg2, dbname, source):
    if action in _ALLOWED:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and arg1 in _READ_PRAGMAS and arg2 is None:
        return sqlite3.SQLITE_OK  # reading a setting; setting one (or a checkpoint) is denied
    return sqlite3.SQLITE_DENY


def readonly_uri(path: str) -> str:
    """``file:`` URI with ``mode=ro`` (never ``immutable=1``), built without ``pathlib.Path.as_uri``.

    On Python 3.14 ``as_uri`` imports ``urllib.request`` and with it ``http``,
    ``socket`` and ``ssl``: not on the hook path.
    """
    absolute = os.path.abspath(path).replace(os.sep, "/")
    if not absolute.startswith("/"):
        absolute = "/" + absolute  # a Windows drive path: file:///C:/...
    return "file:" + urllib.parse.quote(absolute, safe="/:") + "?mode=ro"


def open_snapshot(root: str) -> sqlite3.Connection:
    """A read-only snapshot connection; raises :class:`SnapshotUnavailable` instead of waiting or repairing."""
    path = os.path.join(root, STATE_DB)
    if not os.path.isfile(path):
        raise SnapshotUnavailable("store_missing")
    try:
        conn = sqlite3.connect(readonly_uri(path), uri=True, timeout=0, isolation_level=None, check_same_thread=False)
    except sqlite3.Error:
        raise SnapshotUnavailable("store_snapshot_unavailable") from None
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA busy_timeout = 0")
        conn.set_authorizer(_authorizer)
        conn.execute("BEGIN")
        conn.execute("SELECT 1 FROM installation_meta").fetchone()  # establishes the snapshot now, or fails now
    except sqlite3.Error:
        conn.close()
        raise SnapshotUnavailable("store_snapshot_unavailable") from None
    return conn


def close(conn: sqlite3.Connection) -> None:
    try:
        if conn.in_transaction:
            conn.execute("COMMIT")
    except sqlite3.Error:
        pass
    conn.close()


def read_meta(conn: sqlite3.Connection):
    row = conn.execute("SELECT project_id, installation_id, store_revision, guidance_epoch, policy_revision, tombstone_epoch FROM installation_meta WHERE singleton = 1").fetchone()
    if row is None:
        return None
    return dict(zip(("project_id", "installation_id", "store_revision", "guidance_epoch", "policy_revision", "tombstone_epoch"), row, strict=True))


def bound_task(conn: sqlite3.Connection, query: dict):
    """The query's task, else the session's worker-established task; linked placeholders redirect to their target (A24)."""
    task_id = query.get("task_id")
    if task_id is None:
        row = conn.execute("SELECT task_id FROM working_sessions WHERE session_id = ?", (query["session_id"],)).fetchone()
        task_id = row[0] if row else None
    for _ in range(MAX_REDIRECTS + 1):
        if task_id is None:
            return None
        row = conn.execute("SELECT status, redirect_task_id, workspace_id FROM task_heads WHERE task_id = ?", (task_id,)).fetchone()
        if row is None or row[2] != query["workspace_id"]:
            return None
        if row[0] != "linked" or row[1] is None:
            return task_id
        task_id = row[1]
    return None


def view_id(workspace_id: str, task_id, purpose: str) -> str:
    return f"view:{workspace_id}:{task_id or '-'}:{purpose}"


def _epochs(body: dict) -> tuple:
    return (body["guidance_epoch"], body["policy_revision"], body["tombstone_epoch"])


def _live_candidate(conn: sqlite3.Connection, cand: dict, row_meta: dict, tombstoned: set) -> bool:
    """Retirement, evidence and forgetting filters for a fallback row (SYSTEM_SPEC §8.3)."""
    ref = cand["ref"]
    if ref["id"] in tombstoned or tombstoned & set(cand.get("support_events") or ()):
        return False
    if cand.get("members"):
        row = conn.execute("SELECT state FROM intent_questions WHERE question_id = ?", (cand.get("question_id"),)).fetchone()
        if row is None or row[0] != "open":
            return False
        for claim_id, revision in (cand.get("member_revisions") or {}).items():
            head = conn.execute("SELECT revision, status FROM claim_heads WHERE claim_id = ?", (claim_id,)).fetchone()
            if head is None or head[0] != revision or head[1] not in fc.LIVE or claim_id in tombstoned:
                return False
        return True
    if ref["kind"] != "claim":
        return False  # fallback rows are claims and questions only
    head = conn.execute("SELECT revision, status, freshness FROM claim_heads WHERE claim_id = ?", (ref["id"],)).fetchone()
    if head is None or head[0] != ref["revision"] or head[1] != cand["status"] or head[1] not in fc.LIVE:
        return False
    events = list(cand.get("support_events") or ())
    if events:
        marks = ",".join("?" for _ in events)
        states = {r[0] for r in conn.execute(f"SELECT payload_state FROM events WHERE event_id IN ({marks})", events).fetchall()}  # noqa: S608
        if not states & fc.SUFFICIENT_EVIDENCE:
            return False
    return True


def _tombstoned(conn: sqlite3.Connection, since: int) -> set:
    out = set()
    for (targets,) in conn.execute("SELECT target_ids FROM tombstones WHERE epoch > ?", (since,)).fetchall():
        try:
            out.update(t for t in json.loads(targets) if isinstance(t, str))
        except ValueError:
            continue
    return out


def _claim_values(conn: sqlite3.Connection, cand: dict) -> dict:
    out = {}
    for key, value in (cand.get("claim_values") or {}).items():
        head = conn.execute("SELECT revision FROM claim_heads WHERE claim_id = ?", (value["record_id"],)).fetchone()
        out[key] = value["value"] if head is not None and head[0] == value["head_revision"] else None
    return out


def restored_ids(conn: sqlite3.Connection, session_id: str, extra=()) -> frozenset:
    """Records this session's emitted receipts (durable, plus the caller's not yet ingested) delivered: a restoration's input."""
    out = set(extra)
    for (items,) in conn.execute("SELECT items FROM deliveries WHERE session_id = ? AND state = 'emitted' ORDER BY rowid DESC LIMIT 256", (session_id,)).fetchall():
        try:
            out.update(i.get("record_id") for i in json.loads(items) if isinstance(i, dict))
        except ValueError:
            continue
    return frozenset(out)


def _decide_all(conn, ctx: dict, cands: list, query: dict, environment: dict, *, deadline: float, live: bool, restore_ids=frozenset()) -> tuple:
    family = fc.action_family(query["workspace_id"], query.get("action"))
    query_terms = set(fc.terms(query.get("text") or ""))
    budget = fc.DependencyBudget(deadline)
    entries = []
    for cand in cands:
        values = _claim_values(conn, cand) if live or cand.get("lookup") else {k: v["value"] for k, v in (cand.get("claim_values") or {}).items()}
        entry = fc.decide(cand, query, environment, family=family, query_terms=query_terms, workspace_root=ctx["workspace_root"], budget=budget, claim_values=values, restore_ids=restore_ids)
        if entry is not None:
            entries.append(entry)
    reasons = (["deadline_dependency_unknown"] if budget.skipped else []) + (["dependency_check_bounded"] if budget.exceeded else [])
    return fc.order(entries), reasons


def compile_packet(ctx: dict, query: dict, *, deadline: float, substitute_pre_action: bool = False, restore_ids=frozenset()) -> dict:
    """``{"packet", "source", "fence", "keys", ...}``: the hook-side compile under the shared deadline (no emission)."""
    from recalith.fast import fence

    purpose = query["purpose"]
    reasons: list = []
    if deadline - time.monotonic() < fc.FENCE_TAIL:
        return {"packet": fc.empty_packet(ctx, purpose, None, ["deadline_delivery_skipped"]), "source": None, "fence": None}
    if query.get("workspace_id") != ctx.get("workspace_id"):
        return {"packet": fc.empty_packet(ctx, purpose, None, ["foreign_installation"]), "source": None, "fence": None}
    try:
        conn = open_snapshot(ctx["root"])
    except SnapshotUnavailable:
        return {"packet": fc.empty_packet(ctx, purpose, None, ["store_snapshot_unavailable"]), "source": None, "fence": None}
    source = None
    found: list = []
    try:
        meta = read_meta(conn)
        if meta is None or (meta["project_id"], meta["installation_id"]) != (ctx["project_id"], ctx["installation_id"]):
            return {"packet": fc.empty_packet(ctx, purpose, None, ["store_snapshot_unavailable"]), "source": None, "fence": None}
        live_epochs = (meta["guidance_epoch"], meta["policy_revision"], meta["tombstone_epoch"])
        q = dict(query, task_id=bound_task(conn, query))
        row = conn.execute("SELECT body FROM context_views WHERE view_id = ?", (view_id(query["workspace_id"], q["task_id"], purpose),)).fetchone()
        view = json.loads(row[0]) if row else None
        if view is not None and _epochs(view) == live_epochs:
            source, cands, packet_meta = "view", view["candidates"], {k: view[k] for k in ("store_revision", "guidance_epoch", "policy_revision", "tombstone_epoch")}
            base_environment = view.get("environment") or {}
            environment = {**base_environment, **(query.get("environment") or {})}
        else:
            reasons.append("view_stale" if view is not None else "view_missing")
            if deadline - time.monotonic() < fc.FALLBACK_MIN_REMAINING:
                reasons.append("deadline_fallback_skipped")
                return {"packet": fc.empty_packet(ctx, purpose, meta, reasons), "source": None, "fence": None}
            rows = conn.execute("SELECT body FROM context_views WHERE workspace_id = ? AND purpose = 'fallback' ORDER BY view_id LIMIT ?", (query["workspace_id"], fc.FALLBACK_ROWS)).fetchall()
            bodies = [json.loads(r[0]) for r in rows]
            if any(b["policy_revision"] != meta["policy_revision"] for b in bodies):
                reasons.append("fallback_policy_changed")
                bodies = []
            tombstoned = _tombstoned(conn, min((b["tombstone_epoch"] for b in bodies), default=meta["tombstone_epoch"]))
            cands = [b["candidate"] for b in bodies if _live_candidate(conn, b["candidate"], b, tombstoned)]
            base_environment = (bodies[0].get("environment") if bodies else None) or {}
            environment = {**base_environment, **(query.get("environment") or {})}
            source, packet_meta = "fallback", {k: meta[k] for k in ("store_revision", "guidance_epoch", "policy_revision", "tombstone_epoch")}
        if purpose in lookup.PURPOSES and fc.terms(q.get("text") or ""):
            if deadline - time.monotonic() < lookup.MIN_REMAINING:
                reasons.append("deadline_lookup_skipped")
            else:
                extra, why = lookup.candidates(conn, q["workspace_id"], q.get("text") or "", meta, environment, base_environment=base_environment,
                                               exclude=frozenset(c["ref"]["id"] for c in cands))
                reasons += why
                cands = [*cands, *extra]
                found = [c["ref"]["id"] for c in extra]
        restore = restored_ids(conn, query["session_id"], restore_ids) if purpose == "compact_restore" else frozenset()
        entries, dep_reasons = _decide_all(conn, ctx, cands, q, environment, deadline=deadline, live=source == "fallback", restore_ids=restore)
        reasons += dep_reasons
    except sqlite3.Error:
        return {"packet": fc.empty_packet(ctx, purpose, None, ["store_snapshot_unavailable"]), "source": None, "fence": None}
    finally:
        close(conn)
    assembled = fc.assemble(purpose, [e["item"] for e in entries], max_estimated_tokens=query.get("max_estimated_tokens"), substitute_pre_action=substitute_pre_action)
    packet = fc.packet(ctx, purpose, packet_meta, assembled, reasons)
    keyed = {id(e["item"]): e["key"] for e in entries}
    keys = [keyed[id(item)] for item in assembled["items"]]
    if not is_valid("ContextPacket", packet):
        return {"packet": fc.empty_packet(ctx, purpose, packet_meta, reasons + ["packet_invalid"]), "source": source, "fence": None, "keys": [], "environment": environment, "task_id": q["task_id"], "lookup": found}
    if deadline - time.monotonic() < fc.FENCE_TAIL / 2:
        return {"packet": fc.empty_packet(ctx, purpose, packet_meta, reasons + ["deadline_delivery_skipped"]), "source": source, "fence": None, "keys": [], "environment": environment, "task_id": q["task_id"], "lookup": found}
    result = fence.check(ctx["root"], packet, deadline=deadline)
    if not result["ok"]:
        return {"packet": fc.empty_packet(ctx, purpose, packet_meta, reasons + [result["reason"]]), "source": source, "fence": result, "keys": [], "environment": environment, "task_id": q["task_id"], "lookup": found}
    # ``keys`` (aligned with the packet items) are the suppression identities the delivery branch accounts.
    return {"packet": packet, "source": source, "fence": result, "keys": keys, "environment": environment, "task_id": q["task_id"], "lookup": found}
