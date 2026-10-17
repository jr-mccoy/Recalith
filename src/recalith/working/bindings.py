"""Versioned event-to-task bindings and their resolution (SYSTEM_SPEC §3.2; DATA_CONTRACTS §3.1).

An event's capture-time ``task_id`` is only an immutable hint. Its task is the
head of a versioned binding chain (``task_binding_revisions`` →
``task_binding_heads``), one chain per event (``bind_`` + SHA-256 of the
event ID). Reassignment appends a revision; history is never rewritten, so a
later split can reverse a link and an operator undo can restore a binding.

Every change here is an operation applied by ``controller.apply`` inside its
transaction (Task 5): this module holds the admission checks and the
handlers for ``create_task``, ``bind_events``, ``record_boundary`` and
``resolve_task_binding``; it opens no transaction of its own.

**Pairs.** A tool call and its result are joined by ``tool_call_id``
(``tool_calls``), across splits and sessions: a result inherits its call's
binding before any boundary decision, and a range that would separate a call
from a result that has already arrived is rejected. A call whose result has
not arrived may move; the late result then follows the call.

**Resolution** (:func:`check_resolve`, :func:`apply_resolve`): a split moves
an exact contiguous range of one session's events to a new task that code
allocates, together with the typed items whose evidence lies in the range;
the source keeps its objective. A link moves a session's range to an eligible
existing task without copying objective, constraints or narrative; a source
left with no events becomes a ``linked`` placeholder (``redirect_task_id``)
whose pending call associations moved first. A rejection confirms the events
where they are.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Protocol, Sequence

from recalith.contracts.common import InstallationContext, RecordRef, derived_id, new_id
from recalith.contracts.memory import TaskBindingProposal, TaskBoundaryCandidate, TaskState
from recalith.contracts.operations import BindEventsPayload, CreateTaskPayload, RecordBoundaryPayload
from recalith.core import policy
from recalith.fast import failpoints
from recalith.storage import records
from recalith.working import segment, tasks
from recalith.working.tasks import Ev

STALE = "stale_binding"


class Writer(Protocol):
    """What a handler may do inside the application transaction (``controller.apply``)."""

    txn: Any
    ctx: InstallationContext
    now: str
    op_id: str
    source: str  # proposal | service | reduction

    def record(self, ref: RecordRef, before: int | None) -> None: ...
    def created(self, kind: str, record_id: str) -> None: ...
    def binding(self, event_id: str, before: dict[str, Any] | None, after: dict[str, Any]) -> None: ...
    def boundary(self, boundary_id: str, before: str | None, after: str) -> None: ...
    def serving(self) -> None: ...


# --------------------------------------------------------------------------
# Reads


def binding_id_for(event_id: str) -> str:
    return derived_id("bind", [event_id])


def binding_head(q: Any, event_id: str) -> dict[str, Any] | None:
    row = q.execute("SELECT h.binding_id, h.revision, h.task_id, r.binding, r.boundary_id FROM task_binding_heads h JOIN task_binding_revisions r ON r.binding_id = h.binding_id AND r.revision = h.revision WHERE h.event_id = ?", (event_id,)).fetchone()
    return None if row is None else {"binding_id": row[0], "revision": row[1], "task_id": row[2], "binding": row[3], "boundary_id": row[4]}


def task_session_events(q: Any, task_id: str, session_id: str) -> list[tuple[str, int]]:
    return [(r[0], r[1]) for r in q.execute("SELECT event_id, commit_sequence FROM task_binding_heads WHERE task_id = ? AND session_id = ? ORDER BY commit_sequence", (task_id, session_id)).fetchall()]


def task_event_count(q: Any, task_id: str) -> int:
    return q.execute("SELECT COUNT(*) FROM task_binding_heads WHERE task_id = ?", (task_id,)).fetchone()[0]


def partner_id(q: Any, ev: Ev) -> str | None:
    """The other half of a tool call/result pair, when it has been reduced."""
    call = ev.tool_call_id
    if call is None:
        return None
    row = q.execute("SELECT start_event_id, finish_event_id FROM tool_calls WHERE adapter_id = ? AND tool_call_id = ?", (ev.adapter_id, call)).fetchone()
    if row is None:
        return None
    other = row[1] if ev.kind == "tool_started" else row[0]
    return other if other and other != ev.event_id else None


def index_tool_call(txn: Any, ev: Ev) -> None:
    """Record a call or its result under its tool_call_id (first of each kind wins)."""
    call = ev.tool_call_id
    if call is None:
        return
    column = "start_event_id" if ev.kind == "tool_started" else "finish_event_id"
    txn.execute("INSERT OR IGNORE INTO tool_calls (adapter_id, tool_call_id) VALUES (?, ?)", (ev.adapter_id, call))
    txn.execute(f"UPDATE tool_calls SET {column} = ? WHERE adapter_id = ? AND tool_call_id = ? AND {column} IS NULL", (ev.event_id, ev.adapter_id, call))  # noqa: S608 - fixed column


def bound_partner_task(q: Any, ev: Ev) -> str | None:
    other = partner_id(q, ev)
    if other is None:
        return None
    head = binding_head(q, other)
    return None if head is None else tasks.resolve_task(q, head["task_id"])


def load_boundary(q: Any, boundary_id: str) -> TaskBoundaryCandidate | None:
    row = q.execute("SELECT body FROM task_boundaries WHERE boundary_id = ?", (boundary_id,)).fetchone()
    return None if row is None else TaskBoundaryCandidate.model_validate_json(row[0])


# --------------------------------------------------------------------------
# Reducer bookkeeping (derived from events and bindings; never served)


def task_book(q: Any, task_id: str) -> dict[str, Any]:
    row = q.execute("SELECT body FROM working_tasks WHERE task_id = ?", (task_id,)).fetchone()
    book = json.loads(row[0]) if row is not None else {}
    book.setdefault("clusters", [])
    book.setdefault("open_from", None)
    book.setdefault("checkpoint_pending", False)
    book.setdefault("last_episode_id", None)
    return book


def save_task_book(txn: Any, task_id: str, book: dict[str, Any]) -> None:
    txn.execute(
        "INSERT INTO working_tasks (task_id, body) VALUES (?, ?) ON CONFLICT(task_id) DO UPDATE SET body = excluded.body",
        (task_id, json.dumps({**book, "clusters": sorted(set(book.get("clusters") or []))}, sort_keys=True, separators=(",", ":"))),
    )


def save_session(txn: Any, state: segment.SessionState) -> None:
    txn.execute("INSERT INTO working_sessions (session_id, task_id, body) VALUES (?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET task_id = excluded.task_id, body = excluded.body", (state.session_id, state.task_id, state.to_json()))


def recompute_clusters(q: Any, task_id: str, config: Any) -> list[str]:
    found: set[str] = set()
    rows = q.execute("SELECT e.event_id, e.commit_sequence, e.envelope, e.payload FROM task_binding_heads b JOIN events e ON e.event_id = b.event_id WHERE b.task_id = ? AND e.kind = 'tool_started' ORDER BY b.commit_sequence", (task_id,)).fetchall()  # noqa: S608
    for row in rows:
        found |= segment.action_clusters(tasks.ev_from_row(row), config)
    return sorted(found)


# --------------------------------------------------------------------------
# Writes


def write_binding(w: Writer, ev_id: str, *, seq: int, session_id: str, task_id: str, binding: str, boundary_id: str | None) -> None:
    head = binding_head(w.txn, ev_id)
    binding_id = binding_id_for(ev_id)
    revision = 1 if head is None else head["revision"] + 1
    w.txn.execute(
        "INSERT INTO task_binding_revisions (binding_id, revision, event_id, task_id, binding, boundary_id, assigned_by_operation, previous_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (binding_id, revision, ev_id, task_id, binding, boundary_id, w.op_id, None if head is None else head["revision"]),
    )
    w.txn.execute(
        "INSERT INTO task_binding_heads (event_id, binding_id, revision, task_id, commit_sequence, session_id) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(event_id) DO UPDATE SET revision = excluded.revision, task_id = excluded.task_id",
        (ev_id, binding_id, revision, task_id, seq, session_id),
    )
    before = None if head is None else {"revision": head["revision"], "task_id": head["task_id"], "binding": head["binding"], "boundary_id": head["boundary_id"]}
    w.binding(ev_id, before, {"revision": revision, "task_id": task_id, "binding": binding, "boundary_id": boundary_id})


def write_task(w: Writer, data: dict[str, Any], before: int | None) -> RecordRef:
    data = {**data, "revision": 1 if before is None else before + 1, "updated_at": w.now if before is not None else data["updated_at"]}
    state = TaskState.model_validate_json(json.dumps(data))
    ref = records.write_task(w.txn, state, workspace_id=w.ctx.workspace_id)
    if before is None:
        w.created("task", state.task_id)
    w.record(ref, before)
    w.serving()
    return ref


def _set_boundary(w: Writer, candidate: TaskBoundaryCandidate, state: str) -> None:
    before = candidate.state
    updated = candidate.model_copy(update={"state": state})
    w.txn.execute("UPDATE task_boundaries SET state = ?, body = ? WHERE boundary_id = ?", (state, updated.model_dump_json(), candidate.boundary_id))
    w.boundary(candidate.boundary_id, before, state)


# --------------------------------------------------------------------------
# create_task


def check_create_task(q: Any, ctx: InstallationContext, typed: CreateTaskPayload) -> str | None:
    if not typed.task_id.startswith("task_") or records.head(q, "task", typed.task_id) is not None:
        return "task_id_unavailable"
    for session_id in typed.session_ids:
        row = q.execute("SELECT workspace_id FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None or row[0] != ctx.workspace_id:
            return "session_missing"
    return None


def apply_create_task(w: Writer, typed: CreateTaskPayload) -> None:
    state = tasks.new_task(w.ctx, task_id=typed.task_id, title=typed.title, session_ids=typed.session_ids, started_at=typed.started_at)
    write_task(w, state.model_dump(mode="json"), None)


# --------------------------------------------------------------------------
# bind_events


def check_bind_events(q: Any, ctx: InstallationContext, typed: BindEventsPayload) -> str | None:
    head = records.head(q, "task", typed.task_id)
    if head is None:
        return "task_missing"
    if head[1] == "linked":
        return "task_redirected"
    if typed.patches and head[1] not in policy.TASK_UPDATABLE_STATUSES:
        return "task_not_updatable"
    if records.task_workspace(q, typed.task_id) != ctx.workspace_id:
        return "workspace_mismatch"
    if typed.boundary_id is not None and load_boundary(q, typed.boundary_id) is None:
        return "boundary_missing"
    found = {ev.event_id: ev for ev in tasks.load_events(q, typed.event_ids)}
    for event_id in typed.event_ids:
        ev = found.get(event_id)
        if ev is None:
            return "evidence_missing"
        if ev.kind in tasks.UNBOUND_KINDS:
            return "event_not_bindable"
        if binding_head(q, event_id) is not None:
            return "event_already_bound"
        partner_task = bound_partner_task(q, ev)
        if partner_task is not None and partner_task != typed.task_id:
            return "detaches_call_result"  # a result follows its call's binding
    return None


def apply_bind_events(w: Writer, typed: BindEventsPayload) -> None:
    revision, status, data = tasks.head_state(w.txn, typed.task_id)  # type: ignore[misc]
    events = tasks.load_events(w.txn, typed.event_ids)
    for ev in events:
        write_binding(w, ev.event_id, seq=ev.seq, session_id=ev.session_id, task_id=typed.task_id, binding="provisional", boundary_id=typed.boundary_id)
        index_tool_call(w.txn, ev)
    before = json.dumps(data, sort_keys=True)
    data = json.loads(before)
    if typed.patches:
        tasks.patch_fields(data, typed.patches, list_fields=tasks.TASK_LIST_FIELDS, op_id=w.op_id, ids={"pending_actions": "action_id"}, keep_ids=True)
    _derive_activity(data, events)
    if json.dumps(data, sort_keys=True) != before:
        write_task(w, data, revision)
    book = task_book(w.txn, typed.task_id)
    if events and book["open_from"] is None:
        book["open_from"] = events[0].seq
        save_task_book(w.txn, typed.task_id, book)


def _derive_activity(data: dict[str, Any], events: Iterable[Ev]) -> None:
    """Code-owned fields that follow from bound events: sessions, last activity, reactivation."""
    for ev in events:
        if ev.session_id not in data["session_ids"]:
            data["session_ids"] = [*data["session_ids"], ev.session_id]
        if ev.is_activity:
            if ev.time > data["last_activity_at"]:
                data["last_activity_at"] = ev.time
            if data["status"] == "paused":
                data["status"] = "active"  # new activity resumes a paused task; it never completes it


# --------------------------------------------------------------------------
# record_boundary


def check_record_boundary(q: Any, ctx: InstallationContext, typed: RecordBoundaryPayload) -> str | None:
    c = typed.candidate
    if load_boundary(q, c.boundary_id) is not None:
        return "boundary_exists"
    if records.head(q, "task", c.source_task_id) is None:
        return "task_missing"
    if q.execute("SELECT 1 FROM sessions WHERE session_id = ?", (c.session_id,)).fetchone() is None:
        return "session_missing"
    for event_id in [*c.proposed_event_ids, *([c.after_event_id] if c.after_event_id else [])]:
        if q.execute("SELECT 1 FROM events WHERE event_id = ?", (event_id,)).fetchone() is None:
            return "evidence_missing"
    return None


def apply_record_boundary(w: Writer, typed: RecordBoundaryPayload) -> None:
    c = typed.candidate
    w.txn.execute(
        "INSERT INTO task_boundaries (boundary_id, session_id, after_event_id, source_task_id, reason, state, policy_revision, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (c.boundary_id, c.session_id, c.after_event_id, c.source_task_id, c.reason, c.state, c.policy_revision, c.model_dump_json()),
    )
    w.boundary(c.boundary_id, None, c.state)


# --------------------------------------------------------------------------
# resolve_task_binding


def stale_bindings(q: Any, proposal: TaskBindingProposal) -> bool:
    """A named binding moved since the proposal read it: re-evaluate, never overwrite."""
    for event_id, expected in proposal.expected_binding_revisions.items():
        head = binding_head(q, event_id)
        if head is not None and head["revision"] != expected:
            return True
    return False


def check_resolve(q: Any, ctx: InstallationContext, p: TaskBindingProposal) -> str | None:
    candidate = load_boundary(q, p.boundary_id)
    if candidate is None:
        return "boundary_missing"
    if candidate.state in ("confirmed", "rejected"):
        return "boundary_resolved"
    if candidate.state == "linked" and p.decision == "reject":
        return "boundary_linked"  # a link is reversed by an explicit split, never by reviving the placeholder
    if p.decision != "reject" and not p.event_ids:
        return "event_range_required"
    if not p.evidence:
        return "evidence_required"
    if set(p.expected_binding_revisions) != set(p.event_ids) or len(set(p.event_ids)) != len(p.event_ids):
        return "binding_revisions_mismatch"
    heads = {e: binding_head(q, e) for e in p.event_ids}
    if any(h is None for h in heads.values()):
        return "event_unbound"
    if any(h["revision"] != p.expected_binding_revisions[e] for e, h in heads.items()):  # type: ignore[index]
        return STALE
    source = tasks.resolve_task(q, candidate.source_task_id)
    if not p.event_ids:
        return None
    if {h["task_id"] for h in heads.values()} != {source}:  # type: ignore[index]
        return "range_not_in_source"
    events = tasks.load_events(q, p.event_ids)
    sessions = {ev.session_id for ev in events}
    if len(sessions) != 1:
        return "range_spans_sessions"
    order = [e for e, _seq in task_session_events(q, source, next(iter(sessions)))]  # type: ignore[arg-type]
    positions = sorted(order.index(e) for e in p.event_ids)
    if positions != list(range(positions[0], positions[0] + len(positions))):
        return "range_not_contiguous"
    selected = set(p.event_ids)
    for ev in events:
        other = partner_id(q, ev)
        if other is not None and other not in selected:
            return "detaches_call_result"
    if p.decision == "link_session":
        target = p.target_task_id
        head = records.head(q, "task", target) if target else None
        if head is None or records.task_workspace(q, target) != ctx.workspace_id:  # type: ignore[arg-type]
            return "target_missing"
        if head[1] == "linked":
            return "target_redirected"
        if candidate.state == "linked":
            return None if target == source else "link_conflicts"
        if target == source:
            return "target_is_source"
        if head[1] not in policy.TASK_LINKABLE_STATUSES:
            return "target_ineligible"
    return None


def _moves(data: dict[str, Any], moved: set[str]) -> dict[str, list[dict[str, Any]]]:
    """List items whose evidence all lies in the moved events (they move with them)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for name in tasks.TASK_LIST_FIELDS:
        for item in data.get(name) or []:
            refs = {link["ref"]["id"] for link in records._walk_links(item) if link["ref"]["kind"] == "event"}  # noqa: SLF001
            if refs and refs <= moved:
                out.setdefault(name, []).append(item)
    return out


def _remove(data: dict[str, Any], moved_items: dict[str, list[dict[str, Any]]]) -> None:
    for name, items in moved_items.items():
        ids = {tasks.item_id(name, i) for i in items}
        data[name] = [i for i in data.get(name) or [] if tasks.item_id(name, i) not in ids]


def _add(data: dict[str, Any], moved_items: dict[str, list[dict[str, Any]]]) -> None:
    for name, items in moved_items.items():
        have = {tasks.item_id(name, i) for i in data.get(name) or []}
        data[name] = [*(data.get(name) or []), *[i for i in items if tasks.item_id(name, i) not in have]]


def apply_resolve(w: Writer, p: TaskBindingProposal) -> None:
    q = w.txn
    candidate = load_boundary(q, p.boundary_id)
    assert candidate is not None
    source = tasks.resolve_task(q, candidate.source_task_id)
    assert source is not None
    events = tasks.load_events(q, p.event_ids)
    confirmed = "provisional" if w.source == "reduction" else "confirmed"
    if p.decision == "reject":
        for ev in events:
            write_binding(w, ev.event_id, seq=ev.seq, session_id=ev.session_id, task_id=source, binding="confirmed", boundary_id=p.boundary_id)
        _set_boundary(w, candidate, "rejected")
        return
    if p.decision == "link_session" and candidate.state == "linked":
        for ev in events:  # the model confirms the deterministic link
            write_binding(w, ev.event_id, seq=ev.seq, session_id=ev.session_id, task_id=source, binding="confirmed", boundary_id=p.boundary_id)
        _set_boundary(w, candidate, "confirmed")
        return
    config = segment._config(w.ctx)  # noqa: SLF001
    moved = {ev.event_id for ev in events}
    session_id = events[0].session_id
    session_order = task_session_events(q, source, session_id)
    takes_tail = session_order[-1][0] in moved
    s_rev, _s_status, s_data = tasks.head_state(q, source)  # type: ignore[misc]
    moved_items = _moves(s_data, moved)
    target = new_id("task") if p.decision == "confirm_split" else p.target_task_id
    assert target is not None
    for ev in events:
        write_binding(w, ev.event_id, seq=ev.seq, session_id=ev.session_id, task_id=target, binding=confirmed if p.decision == "link_session" else "confirmed", boundary_id=p.boundary_id)
    failpoints.hit(failpoints.BINDING_AFTER_REBIND)
    # The source loses exactly the moved items; it keeps its objective and narrative.
    _remove(s_data, moved_items)
    if q.execute("SELECT 1 FROM task_binding_heads WHERE task_id = ? AND session_id = ? LIMIT 1", (source, session_id)).fetchone() is None:
        s_data["session_ids"] = [s for s in s_data["session_ids"] if s != session_id]
    if task_event_count(q, source) == 0 and p.decision == "link_session":
        # A linked placeholder: no actionable context of its own; history stays inspectable.
        s_data.update({"status": "linked", "redirect_task_id": target, "next_action": None, "pending_actions": []})
    if not s_data["session_ids"]:
        s_data["session_ids"] = [session_id]  # history: the placeholder still names its own session
    activity = [ev.time for ev in events if ev.is_activity]
    if p.decision == "confirm_split":
        state = tasks.new_task(w.ctx, task_id=target, title=tasks.DEFAULT_TITLE, session_ids=[session_id], started_at=min(ev.time for ev in events))
        draft = tasks.Draft(state.model_dump(mode="json"), signature_of=lambda _e: None)
        for ev in events:
            if ev.is_user_request:
                tasks.fold_event(draft, ev)
                break
        t_data = draft.data
        _add(t_data, moved_items)
        if activity:
            t_data["last_activity_at"] = max(activity)
        write_task(w, s_data, s_rev)
        write_task(w, t_data, None)
    else:
        t_rev, _t_status, t_data = tasks.head_state(q, target)  # type: ignore[misc]
        _add(t_data, moved_items)
        _derive_activity(t_data, events)
        write_task(w, s_data, s_rev)
        write_task(w, t_data, t_rev)
    # Bookkeeping follows the bindings.
    for task_id in {source, target}:
        book = task_book(q, task_id)
        book["clusters"] = recompute_clusters(q, task_id, config)
        if task_id == target:
            low = min(ev.seq for ev in events)
            book["open_from"] = low if book["open_from"] is None else min(book["open_from"], low)
        save_task_book(q, task_id, book)
    state = segment.load_session(q, session_id)
    if state is not None and (takes_tail or p.decision == "link_session"):
        state.task_id = target
        if p.decision == "link_session":
            state.continuity = "linked"
        state.run_clusters, state.run_event_ids, state.run_after = [], [], None
        save_session(q, state)
    _set_boundary(w, candidate, "confirmed" if p.decision == "confirm_split" else ("linked" if w.source == "reduction" else "confirmed"))


# --------------------------------------------------------------------------
# Public service entry


def resolve_task_binding(ctx: InstallationContext, proposal: TaskBindingProposal, *, store: Any = None, now: str | None = None, submission_id: str | None = None) -> Any:
    """Apply one binding decision through the Task 5 path (DATA_CONTRACTS §11).

    The decision becomes a persisted ``resolve_task_binding`` operation applied
    by ``controller.apply.apply_operations`` with the same admission,
    revision and binding-revision checks as a model proposal; a moved binding
    raises ``revision_conflict`` and applies nothing.
    """
    from recalith.contracts.common import ReadSet, digest_of
    from recalith.contracts.operations import ProposedOperation
    from recalith.controller import apply

    op = ProposedOperation(local_ref="binding", kind="resolve_task_binding", payload=proposal.model_dump(mode="json"), reason="binding decision")
    with (store.read() if store is not None else _read(ctx)) as view:
        meta = view.execute("SELECT policy_revision, tombstone_epoch FROM installation_meta WHERE singleton = 1").fetchone()
    read_set = ReadSet(workspace_id=ctx.workspace_id, policy_revision=meta[0], tombstone_epoch=meta[1])
    return apply.apply_operations(ctx, [op], read_set=read_set, submission_id=submission_id or derived_id("op", ["binding", digest_of(proposal.model_dump(mode="json"))]), store=store, now=now)


class _read:
    def __init__(self, ctx: InstallationContext) -> None:
        from recalith.storage.db import open_store

        self.store = open_store(ctx, readonly=True)
        self._cm = self.store.read()

    def __enter__(self) -> Any:
        return self._cm.__enter__()

    def __exit__(self, *exc: Any) -> None:
        self._cm.__exit__(*exc)
        self.store.close()


def session_ranges(q: Any, task_id: str) -> dict[str, list[str]]:
    """Each session's events bound to a task, in commit order (explicit ranges for proposals)."""
    out: dict[str, list[str]] = {}
    for event_id, session_id in q.execute("SELECT event_id, session_id FROM task_binding_heads WHERE task_id = ? ORDER BY commit_sequence", (task_id,)).fetchall():
        out.setdefault(session_id, []).append(event_id)
    return out


def expected_revisions(q: Any, event_ids: Sequence[str]) -> dict[str, int]:
    return {e: binding_head(q, e)["revision"] for e in event_ids}  # type: ignore[index]
