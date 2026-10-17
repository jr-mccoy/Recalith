"""Typed task reduction: the deterministic ingest reducer (SYSTEM_SPEC §3.2, §3.5, §6.2).

Registered on the worker as an ingest reducer (decision 0006), it runs in the
deterministic lane inside the ingest job's fenced transaction, so typed
state, bindings, boundary candidates, episodes, the reduction cursor and job
completion commit together, or not at all. It uses no model and no model
budget, and stays responsive while the model lane has a call in flight.

One pass reduces every committed event not yet reduced (in commit order) up
to and including the job's own events, so jobs that run out of order still
reduce in order. For each event it:

1. resolves the event's task: a tool result follows its call's binding (by
   ``tool_call_id``, across splits and sessions); otherwise the session's
   current task; a new session gets a provisional task (``new_session``, or
   ``host_reset`` after a host clear);
2. folds the event's typed facts into that task (``working.tasks``);
3. records deterministic boundary candidates (``working.segment``); they are
   proposals and change no binding;
4. applies the budget-independent ``single_active_task`` link when a new
   session's first three path-bearing actions all fall inside the clusters of
   the one eligible task;
5. at checkpoints (compaction, session end, idle pause) turns the task's open
   range into an episode (``episodes``), unless that would sever a failure
   from its later result.

Every persistent change is an operation applied by
``controller.apply.apply_in_transaction`` (Task 5) as one atomic group per
application; a rejected reduction fails the job (it is retried), it is never
partially applied.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Sequence

from recalith.contracts.common import Actor, InstallationContext, ReadSet, derived_id, format_utc, new_id, parse_utc
from recalith.contracts.config import ProjectConfig
from recalith.contracts.memory import TaskState
from recalith.contracts.operations import ApplyResult, ProposedOperation
from recalith.controller import apply
from recalith.episodes import condense
from recalith.episodes import segment as episode_segment
from recalith.errors import RecalithError
from recalith.fast import failpoints
from recalith.storage import records
from recalith.working import bindings, segment, tasks
from recalith.working.tasks import Ev

# Typed reduction is the worker's own deterministic code: it applies as the
# controller, whatever transport resolved the context it was given.
REDUCER_ACTOR = Actor(kind="controller", id="typed-reducer", channel="worker")
EXTRA_EVENTS = 200  # beyond the job's own events, at most this many others per pass
EVENTS_PER_OP = 128
PATCHES_PER_OP = 256
ADMITTED = frozenset({"apply", "candidate_only"})


def _op(index: int, kind: str, payload: dict[str, Any], *, reason: str) -> dict[str, Any]:
    ref = f"r{index}"
    return {"local_ref": ref, "kind": kind, "depends_on": [f"r{index - 1}"] if index else [], "target": None, "payload": payload, "evidence": [], "reason": reason}


class Reduction:
    """One reduction pass inside a caller's write transaction."""

    def __init__(self, txn: Any, ctx: InstallationContext, config: ProjectConfig, *, scope_id: str, now: str) -> None:
        self.txn = txn
        self.ctx = ctx.model_copy(update={"actor": REDUCER_ACTOR})
        self.config = config
        self.scope_id = scope_id
        self.now = now
        self.applications = 0
        self.flagged: dict[str, set[str]] = {}  # task_id -> {"checkpoint", "session_end"}
        self.touched: set[str] = set()
        self._reset()

    # ---------------------------------------------------------------- buffers

    def _reset(self) -> None:
        self.sessions: dict[str, segment.SessionState] = {}
        self.books: dict[str, dict[str, Any]] = {}
        self.drafts: dict[str, tasks.Draft] = {}
        self.frozen: set[str] = set()
        self.base: dict[str, int] = {}
        self.bind: dict[str, list[Ev]] = {}
        self.created: list[dict[str, Any]] = []
        self.boundaries: list[dict[str, Any]] = []
        self.pass_tasks: dict[str, str] = {}
        self.pass_calls: dict[tuple[str, str, str], Ev] = {}
        self.events: dict[str, Ev] = {}

    def session(self, session_id: str) -> segment.SessionState | None:
        if session_id not in self.sessions:
            state = segment.load_session(self.txn, session_id)
            if state is None:
                return None
            self.sessions[session_id] = state
        return self.sessions[session_id]

    def book(self, task_id: str) -> dict[str, Any]:
        if task_id not in self.books:
            self.books[task_id] = bindings.task_book(self.txn, task_id)
        return self.books[task_id]

    def clusters(self, task_id: str) -> set[str]:
        book = self.book(task_id)
        if not isinstance(book["clusters"], set):
            book["clusters"] = set(book["clusters"])
        return book["clusters"]

    def signature_of(self, event_id: str) -> str | None:
        ev = self.events.get(event_id)
        if ev is None:
            found = tasks.load_events(self.txn, [event_id])
            ev = found[0] if found else None
            if ev is not None:
                self.events[event_id] = ev
        return tasks.action_signature(ev) if ev is not None and ev.kind == "tool_finished" else None

    def draft(self, task_id: str) -> tasks.Draft | None:
        if task_id not in self.drafts:
            current = tasks.head_state(self.txn, task_id)
            assert current is not None, "a bound task exists"
            revision, status, data = current
            self.base[task_id] = revision
            self.drafts[task_id] = tasks.Draft(data, signature_of=self.signature_of)
            if status not in ("active", "paused"):
                self.frozen.add(task_id)
        return None if task_id in self.frozen else self.drafts[task_id]

    # ---------------------------------------------------------------- the pass

    def run(self, through: int) -> None:
        cursor = self.txn.one("SELECT commit_sequence FROM working_cursor WHERE singleton = 1")[0]
        latest = self.txn.one("SELECT COALESCE(MAX(commit_sequence), 0) FROM events")[0]
        target = max(through, min(latest, cursor + EXTRA_EVENTS))
        if target <= cursor:
            return
        rows = self.txn.execute(f"SELECT {tasks.EVENT_COLUMNS} FROM events WHERE commit_sequence > ? AND commit_sequence <= ? ORDER BY commit_sequence", (cursor, target)).fetchall()  # noqa: S608
        for row in rows:
            ev = tasks.ev_from_row(row)
            self.events[ev.event_id] = ev
            self.event(ev)
        self.flush()
        self.checkpoints()
        self.txn.execute("UPDATE working_cursor SET commit_sequence = ? WHERE singleton = 1", (target,))

    def resolve(self, task_id: str | None) -> str | None:
        if task_id is None:
            return None
        if any(c["task_id"] == task_id for c in self.created):
            return task_id
        return tasks.resolve_task(self.txn, task_id)

    def partner_task(self, ev: Ev) -> str | None:
        call = ev.tool_call_id
        if call is None:
            return None
        other_kind = "tool_finished" if ev.kind == "tool_started" else "tool_started"
        other = self.pass_calls.get((ev.adapter_id, call, other_kind))
        if other is not None:
            return self.pass_tasks.get(other.event_id)
        return bindings.bound_partner_task(self.txn, ev)

    def new_session(self, ev: Ev) -> segment.SessionState:
        hint = self.resolve(ev.task_hint) if ev.task_hint else None
        if hint is not None and records.task_workspace(self.txn, hint) == self.ctx.workspace_id:
            state = segment.SessionState(session_id=ev.session_id, task_id=hint, origin="host_binding", continuity="none")
            self.sessions[ev.session_id] = state
            return state  # a host binding outranks segmentation guesses
        reason = "host_reset" if ev.kind == "session_started" and ev.payload.get("source") == "clear" else "new_session"
        task_id = new_id("task")
        self.created.append({"task_id": task_id, "title": tasks.DEFAULT_TITLE, "reason": reason, "session_ids": [ev.session_id], "started_at": ev.time})
        state = tasks.new_task(self.ctx, task_id=task_id, title=tasks.DEFAULT_TITLE, session_ids=[ev.session_id], started_at=ev.time)
        self.base[task_id] = 1
        self.drafts[task_id] = tasks.Draft(state.model_dump(mode="json"), signature_of=self.signature_of)
        self.books[task_id] = {"clusters": set(), "open_from": None, "checkpoint_pending": False, "last_episode_id": None}
        policy_revision = self.txn.meta.policy_revision
        candidate = segment.session_candidate(reason, session_id=ev.session_id, first_event_id=ev.event_id, task_id=task_id, policy_revision=policy_revision)
        self.boundaries.append(candidate.model_dump(mode="json"))
        state_ = segment.SessionState(session_id=ev.session_id, task_id=task_id, provisional_task_id=task_id, origin=reason, continuity="pending" if reason == "new_session" else "blocked")
        self.sessions[ev.session_id] = state_
        return state_

    def event(self, ev: Ev) -> None:
        if ev.kind in tasks.UNBOUND_KINDS:
            return
        state = self.session(ev.session_id) or self.new_session(ev)
        current = self.resolve(state.task_id) or state.task_id
        state.task_id = current
        task_id = self.partner_task(ev) or current
        self.touched.add(task_id)
        draft = self.draft(task_id)
        if draft is not None:
            tasks.fold_event(draft, ev)
        self.bind.setdefault(task_id, []).append(ev)
        self.pass_tasks[ev.event_id] = task_id
        if ev.tool_call_id:
            self.pass_calls.setdefault((ev.adapter_id, ev.tool_call_id, ev.kind), ev)
        if ev.kind == "compaction" or ev.kind == "session_ended":
            self.flagged.setdefault(task_id, set()).add("checkpoint")
            if ev.kind == "session_ended":
                self.flagged[task_id].add("session_end")
        if task_id != current:
            return  # a late result of another task: its session's signals belong to the current task
        policy_revision = self.txn.meta.policy_revision
        for signal in segment.observe(state, ev, self.clusters(task_id), self.config):
            candidate = segment.candidate(signal, session_id=ev.session_id, source_task_id=task_id, policy_revision=policy_revision)
            if bindings.load_boundary(self.txn, candidate.boundary_id) is None and all(b["boundary_id"] != candidate.boundary_id for b in self.boundaries):
                self.boundaries.append(candidate.model_dump(mode="json"))
        if state.provisional_task_id == task_id and segment.continuity_step(state, ev, self.config):
            self.continuity(state)

    # ---------------------------------------------------------------- continuity

    def continuity(self, state: segment.SessionState) -> None:
        """SYSTEM_SPEC §3.2 ``single_active_task``: exactly one eligible task, all three actions inside its clusters."""
        self.flush()  # other sessions' provisional tasks of this pass must be visible as candidates
        state = self.session(state.session_id)  # type: ignore[assignment]
        provisional = state.provisional_task_id
        assert provisional is not None
        found = tasks.continuity_candidates(self.txn, self.ctx.workspace_id, exclude=[provisional], now=self.event_time(state), pause_hours=self.config.segmentation.continuity_pause_hours)
        if len(found) != 1 or not segment.continuity_fits(state, bindings.task_book(self.txn, found[0])["clusters"]):
            state.continuity = "declined"
            return
        target = found[0]
        event_ids = [e for e, _seq in bindings.task_session_events(self.txn, provisional, state.session_id)]
        selected = set(event_ids)
        for ev in tasks.load_events(self.txn, event_ids):
            other = bindings.partner_id(self.txn, ev)
            if other is not None and other not in selected:
                state.continuity = "declined"  # a call/result pair spans sessions: keep separate provisional state
                return
        policy_revision = self.txn.meta.policy_revision
        detail = {"candidates": 1, "path_actions": len(state.path_event_ids), "action_clusters": state.path_clusters, "target_clusters": bindings.task_book(self.txn, target)["clusters"], "pause_hours": self.config.segmentation.continuity_pause_hours}
        candidate = segment.candidate(segment.Signal("single_active_task", None, tuple(state.path_event_ids), detail), session_id=state.session_id, source_task_id=provisional, policy_revision=policy_revision)
        evidence = [tasks.event_link(self.events[e] if e in self.events else tasks.load_events(self.txn, [e])[0], relation="context") for e in state.path_event_ids]
        proposal = {"boundary_id": candidate.boundary_id, "decision": "link_session", "event_ids": event_ids, "target_task_id": target, "expected_binding_revisions": bindings.expected_revisions(self.txn, event_ids), "evidence": evidence}
        state.continuity = "linked"
        state.task_id = target
        self._apply([("record_boundary", {"candidate": candidate.model_dump(mode="json")}), ("resolve_task_binding", proposal)], reason="single_active_task")
        self.flagged.setdefault(target, set())
        self.touched.add(target)

    def event_time(self, state: segment.SessionState) -> str:
        return state.last_activity_at or self.now

    # ---------------------------------------------------------------- application

    def flush(self) -> None:
        ops: list[tuple[str, dict[str, Any]]] = []
        for created in self.created:
            ops.append(("create_task", created))
        for task_id, events in self.bind.items():
            draft = self.drafts.get(task_id)
            patches = draft.patches if draft is not None and task_id not in self.frozen else []
            # Bounded operations, in order: every one binds at least one event; patches keep their order.
            n = max(-(-len(events) // EVENTS_PER_OP), -(-len(patches) // PATCHES_PER_OP), 1)
            per_events, per_patches = -(-len(events) // n), -(-len(patches) // n) if patches else 0
            for i in range(n):
                chunk = events[i * per_events : (i + 1) * per_events]
                if not chunk:
                    break
                part = patches[i * per_patches : (i + 1) * per_patches] if per_patches else []
                if i == n - 1 or not events[(i + 1) * per_events :]:
                    part = patches[i * per_patches :] if per_patches else []
                ops.append(("bind_events", {"task_id": task_id, "expected_revision": self.base[task_id], "event_ids": [e.event_id for e in chunk], "boundary_id": None, "patches": part}))
        for boundary in self.boundaries:
            ops.append(("record_boundary", {"candidate": boundary}))
        self._apply(ops, reason="typed reduction")

    def _apply(self, ops: Sequence[tuple[str, dict[str, Any]]], *, reason: str) -> ApplyResult | None:
        self._save_bookkeeping()
        self._reset()
        if not ops:
            return None
        operations = [ProposedOperation.model_validate(_op(i, kind, payload, reason=reason)) for i, (kind, payload) in enumerate(ops)]
        meta = self.txn.meta
        read_set = ReadSet(workspace_id=self.ctx.workspace_id, policy_revision=meta.policy_revision, tombstone_epoch=meta.tombstone_epoch)
        submission = derived_id("op", ["reduction", self.scope_id, self.applications])
        self.applications += 1
        result = apply.apply_in_transaction(self.txn, self.ctx, operations, read_set=read_set, submission_id=submission, now=self.now)
        refused = [d for d in result.decisions if d.outcome not in ADMITTED]
        if refused:
            raise RecalithError("invalid_result", f"typed reduction was refused: {refused[0].local_ref} {refused[0].reason_code}")
        if self.applications == 1:
            failpoints.hit(failpoints.REDUCE_AFTER_APPLY)
        return result

    def _save_bookkeeping(self) -> None:
        for state in self.sessions.values():
            bindings.save_session(self.txn, state)
        for task_id, book in self.books.items():
            bindings.save_task_book(self.txn, task_id, {**book, "clusters": sorted(book["clusters"])})

    # ---------------------------------------------------------------- episodes

    def checkpoints(self) -> None:
        """Turn open ranges into episodes at checkpoints, never severing a failure from its result."""
        ops: list[tuple[str, dict[str, Any]]] = []
        planned: list[str] = []
        for task_id in sorted(self.touched | set(self.flagged)):
            if records.head(self.txn, "task", task_id) is None:
                continue
            book = bindings.task_book(self.txn, task_id)
            flags = self.flagged.get(task_id, set())
            checkpoint = book["checkpoint_pending"] or "checkpoint" in flags
            body = self.episode_for(task_id, book, checkpoint=checkpoint, session_end="session_end" in flags)
            if body is None:
                if checkpoint and not book["checkpoint_pending"]:
                    book["checkpoint_pending"] = True
                    bindings.save_task_book(self.txn, task_id, book)
                continue
            ops.append(("create_episode", body))
            planned.append(task_id)
        if not ops:
            return
        result = self._apply_episodes(ops)
        for task_id, ref in zip(planned, [r for r in result.changed_refs if r.kind == "episode"], strict=False):
            book = bindings.task_book(self.txn, task_id)
            book.update({"open_from": None, "checkpoint_pending": False, "last_episode_id": ref.id})
            bindings.save_task_book(self.txn, task_id, book)

    def _apply_episodes(self, ops: Sequence[tuple[str, dict[str, Any]]]) -> ApplyResult:
        result = self._apply(ops, reason="episode checkpoint")
        assert result is not None
        return result

    def episode_for(self, task_id: str, book: dict[str, Any], *, checkpoint: bool, session_end: bool) -> dict[str, Any] | None:
        if book["open_from"] is None:
            return None
        events = open_range(self.txn, task_id, book["open_from"])
        if not events:
            return None
        finished = finished_calls(self.txn, events)
        decision = episode_segment.decide(episode_segment.range_state(events, finished_calls=finished), checkpoint=checkpoint, session_end=session_end)
        if decision is None:
            return None
        current = tasks.head_state(self.txn, task_id)
        assert current is not None
        previous = None
        if book["last_episode_id"]:
            head = records.head(self.txn, "episode", book["last_episode_id"])
            previous = records.body(self.txn, "episode", book["last_episode_id"], head[0]) if head else None

        def start_of(ev: Ev) -> Ev | None:
            other = bindings.partner_id(self.txn, ev)
            found = tasks.load_events(self.txn, [other]) if other else []
            return found[0] if found else None

        return condense.episode_body(task_id, current[2], events, start_of=start_of, state=decision, previous=previous)


def open_range(q: Any, task_id: str, open_from: int) -> list[Ev]:
    """A task's bound events from ``open_from`` that none of its episodes recounts yet."""
    rows = q.execute(
        "SELECT e.event_id, e.commit_sequence, e.envelope, e.payload FROM task_binding_heads b JOIN events e ON e.event_id = b.event_id "  # noqa: S608
        "WHERE b.task_id = ? AND b.commit_sequence >= ? AND NOT EXISTS (SELECT 1 FROM evidence_links l JOIN episode_heads h ON h.episode_id = l.owner_id AND h.revision = l.owner_revision "
        "WHERE l.owner_kind = 'episode' AND l.target_kind = 'event' AND l.target_id = b.event_id AND h.task_id = b.task_id) ORDER BY b.commit_sequence",
        (task_id, open_from),
    ).fetchall()
    return [tasks.ev_from_row(r) for r in rows]


def finished_calls(q: Any, events: Sequence[Ev]) -> set[str]:
    out = set()
    for ev in events:
        if ev.kind == "tool_started" and ev.tool_call_id:
            row = q.execute("SELECT finish_event_id FROM tool_calls WHERE adapter_id = ? AND tool_call_id = ?", (ev.adapter_id, ev.tool_call_id)).fetchone()
            if row is not None and row[0]:
                out.add(ev.tool_call_id)
    return out


# --------------------------------------------------------------------------
# Worker entry points


def reduce_ingested(txn: Any, job: Any, worker: Any) -> None:
    """Ingest reducer (``Worker.ingest_reducers``): reduce through the job's own events."""
    refs = [r.id for r in job.input_refs if r.kind == "event"]
    if not refs:
        return
    marks = ",".join("?" for _ in refs)
    through = txn.one(f"SELECT COALESCE(MAX(commit_sequence), 0) FROM events WHERE event_id IN ({marks})", refs)[0]  # noqa: S608
    Reduction(txn, worker.ctx, worker.config, scope_id=job.job_id, now=worker.clock.now()).run(through)


def pause_idle_tasks(store: Any, ctx: InstallationContext, config: ProjectConfig, *, now: str) -> list[str]:
    """Active tasks idle for ``worker.paused_task_hours`` become paused (never completed); their ranges checkpoint."""
    cutoff = format_utc(parse_utc(now) - _dt.timedelta(hours=config.worker.paused_task_hours))
    with store.read() as view:
        due = view.execute("SELECT task_id, revision FROM task_heads WHERE workspace_id = ? AND status = 'active' AND last_activity_at < ? ORDER BY task_id LIMIT 64", (ctx.workspace_id, cutoff)).fetchall()
    if not due:
        return []
    paused: list[str] = []
    ctx = ctx.model_copy(update={"actor": REDUCER_ACTOR})
    with store.transaction() as txn:
        meta = txn.meta
        read_set = ReadSet(workspace_id=ctx.workspace_id, policy_revision=meta.policy_revision, tombstone_epoch=meta.tombstone_epoch)
        for task_id, revision in due:
            current = records.head(txn, "task", task_id)
            if current is None or current != (revision, "active"):
                continue
            op = ProposedOperation.model_validate(_op(0, "update_task", {"task_id": task_id, "expected_revision": revision, "patches": [{"op": "status", "status": "paused"}]}, reason="idle pause"))
            result = apply.apply_in_transaction(txn, ctx, [op], read_set=read_set, submission_id=derived_id("op", ["pause", task_id, revision]), now=now)
            if all(d.outcome in ADMITTED for d in result.decisions):
                paused.append(task_id)
        reduction = Reduction(txn, ctx, config, scope_id=derived_id("op", ["pause", now]), now=now)
        for task_id in paused:
            reduction.flagged[task_id] = {"checkpoint"}
        reduction.checkpoints()
    return paused


def reduce_task(ctx: InstallationContext, task_id: str, events: Sequence[Any], *, store: Any = None) -> TaskState:
    """The task state these events support (DATA_CONTRACTS §11); nothing is written.

    Folds the events' typed facts into the current head with exactly the
    rules typed reduction applies; the returned revision is the head's next
    revision when anything changed. Persistence is ``bind_events`` /
    ``update_task`` through ``controller.apply``.
    """
    from recalith.storage.db import open_store

    own = store is None
    store = store or open_store(ctx, readonly=True)
    try:
        with store.read() as view:
            current = tasks.head_state(view, task_id)
            if current is None:
                raise RecalithError("invalid_schema", "no such task")
            revision, _status, data = current
            evs = [e if isinstance(e, Ev) else tasks.ev_from_envelope(e) for e in events]

            def signature_of(event_id: str) -> str | None:
                found = tasks.load_events(view, [event_id])
                return tasks.action_signature(found[0]) if found and found[0].kind == "tool_finished" else None

            draft = tasks.Draft(data, signature_of=signature_of)
            for ev in evs:
                tasks.fold_event(draft, ev)
            bindings._derive_activity(draft.data, evs)  # noqa: SLF001
    finally:
        if own:
            store.close()
    changed = draft.data != data
    return TaskState.model_validate({**draft.data, "revision": revision + 1 if changed else revision})
