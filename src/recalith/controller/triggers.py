"""Failure triggers: the task-local six-event / ten-minute extraction debounce (SYSTEM_SPEC §6.3; DATA_CONTRACTS §8; A66).

A certified failure (a finished tool result under host authority with
outcome ``failure``) starts a pending extraction trigger for its task. The
trigger is resolved, with no model call, when a certified *success* of the
same task and the same known action family arrives before six subsequent
relevant task events or ten minutes, whichever comes first; otherwise it
becomes due and schedules one ``extract_claims`` job (``trigger_ref``).

* **Deterministic.** Events are examined once, in commit order, inside the
  ingest job's fenced transaction after typed reduction has bound them
  (:func:`reduce_ingested`, registered as an ingest reducer). Time is the
  events' own observation time (occurred, else recorded), never the time the
  worker happened to process them; :func:`sweep` makes a trigger due once the
  worker clock passes ``due_at`` with no event at all. A success that was
  observed before the due point but ingested after the sweep still resolves
  the trigger while its extraction job has not been leased (that job is
  cancelled, ``trigger_resolved``).
* **Relevant events** are explicit user messages, artifact changes and
  completed certified tool results of the same task (the failure itself
  excluded); telemetry, memory echoes, assistant text, tool starts and
  lifecycle events do not count. The resolving success is not counted.
* **Action family** (``capture.normalize.action_family_digest``): workspace,
  normalized working directory, tool, executable and ordered argv, excluding
  task ID and dependency fingerprints, so a success after a changed dependency
  still matches. An unknown working directory or an inexact parse gives a
  null family: such a trigger never matches a success (lexical resemblance is
  not identity) and becomes due only by count or time. A repeated failure of
  a known family joins the pending trigger of its task and family (counted as
  a relevant event); a null-family failure always starts its own trigger.
* ``expected_red`` is reserved false in v1 (a normalized ``true`` is invalid
  and an untrusted raw hint is dropped with a coverage warning); it never
  excludes a trigger.

FailureRecheck (a later success against an *admitted* failure lesson,
SYSTEM_SPEC §7.3) is Task 10 and is not decided here.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from typing import Any

from recalith.contracts.common import derived_id, format_utc, parse_utc
from recalith.contracts.config import FAILURE_DEBOUNCE_EVENTS, FAILURE_DEBOUNCE_SECONDS
from recalith.controller import extract, jobs
from recalith.fast import failpoints
from recalith.working import bindings, tasks

RELEVANT_KINDS = frozenset({"user_message", "artifact_changed", "tool_finished"})
EVENTS_PER_PASS = 400


@dataclass(frozen=True)
class Event:
    event_id: str
    seq: int
    kind: str
    channel: str
    authority: str
    workspace_id: str
    time: str
    derived: bool
    payload: dict[str, Any]

    @property
    def certified_result(self) -> bool:
        return self.kind == "tool_finished" and self.channel == "tool" and self.authority == "observed_tool" and not self.derived and self.payload.get("result_received") is True

    @property
    def failure(self) -> bool:
        return self.certified_result and self.payload.get("outcome") == "failure"

    @property
    def success(self) -> bool:
        return self.certified_result and self.payload.get("outcome") == "success"

    @property
    def relevant(self) -> bool:
        if self.kind not in RELEVANT_KINDS or self.derived:
            return False
        if self.kind == "user_message":
            return self.channel == "user" and self.authority == "explicit_user"
        return self.channel == "tool" and self.authority == "observed_tool"

    @property
    def family(self) -> str | None:
        from recalith.capture.normalize import action_family_digest

        action = self.payload.get("action")
        return action_family_digest(self.workspace_id, action) if isinstance(action, dict) else None


def _event(row: Any) -> Event:
    event_id, seq, envelope, payload, workspace_id = row
    env = json.loads(envelope)
    return Event(
        event_id=event_id, seq=int(seq), kind=env["kind"], channel=env["channel"], authority=env["authority"], workspace_id=workspace_id,
        time=env.get("occurred_at") or env["recorded_at"], derived=bool(env.get("derived_from")), payload=json.loads(payload) if payload is not None else {},
    )


def _plus(moment: str, seconds: int) -> str:
    return format_utc(parse_utc(moment) + _dt.timedelta(seconds=seconds))


# --------------------------------------------------------------------------
# State changes (caller's transaction)


def _become_due(txn: Any, trigger: dict[str, Any], reason: str, *, now: str) -> None:
    job_id = extract.schedule_for_trigger(txn, trigger_id=trigger["trigger_id"], task_id=trigger["task_id"], failure_event_id=trigger["failure_event_id"], now=now)
    txn.execute("UPDATE failure_triggers SET state = 'due', due_reason = ?, job_id = ? WHERE trigger_id = ?", (reason, job_id, trigger["trigger_id"]))
    txn.mutated(serving_relevant=False)
    trigger.update(state="due", due_reason=reason, job_id=job_id)


def _resolve(txn: Any, trigger: dict[str, Any], success_id: str) -> None:
    if trigger["state"] == "due" and trigger.get("job_id"):
        job = jobs.get_job(txn, trigger["job_id"])
        if job is not None and job.state in ("pending", "waiting_budget"):
            jobs.supersede(txn, job, "trigger_resolved")
    txn.execute("UPDATE failure_triggers SET state = 'resolved', resolved_by = ? WHERE trigger_id = ?", (success_id, trigger["trigger_id"]))
    txn.mutated(serving_relevant=False)
    trigger.update(state="resolved", resolved_by=success_id)


def _open(txn: Any, task_id: str) -> list[dict[str, Any]]:
    """Triggers of a task that an event may still count toward or resolve."""
    rows = txn.execute(
        "SELECT trigger_id, task_id, failure_event_id, action_family_digest, subsequent_event_count, due_at, state, failure_sequence, due_reason, job_id FROM failure_triggers "
        "WHERE task_id = ? AND (state = 'pending' OR (state = 'due' AND due_reason = 'time')) ORDER BY failure_sequence, trigger_id",
        (task_id,),
    ).fetchall()
    keys = ("trigger_id", "task_id", "failure_event_id", "family", "count", "due_at", "state", "failure_sequence", "due_reason", "job_id")
    return [dict(zip(keys, r, strict=True)) for r in rows]


def _late_resolvable(txn: Any, trigger: dict[str, Any]) -> bool:
    """A time-due trigger whose extraction has not started can still be resolved by an earlier-observed success."""
    if trigger["state"] != "due" or trigger["due_reason"] != "time" or not trigger["job_id"]:
        return False
    job = jobs.get_job(txn, trigger["job_id"])
    return job is not None and job.state in ("pending", "waiting_budget")


def observe(txn: Any, ev: Event, task_id: str, *, now: str) -> None:
    """Apply one bound event to its task's triggers, then start a trigger for a new failure."""
    joined = False
    for trigger in _open(txn, task_id):
        if ev.seq <= trigger["failure_sequence"] or not ev.relevant:
            continue
        pending = trigger["state"] == "pending"
        if not pending and not _late_resolvable(txn, trigger):
            continue
        if ev.time >= trigger["due_at"]:
            if pending:
                _become_due(txn, trigger, "time", now=now)
            continue  # ten minutes passed: nothing later counts or resolves
        family = ev.family if ev.success else None
        if family is not None and family == trigger["family"]:
            _resolve(txn, trigger, ev.event_id)
            continue
        if ev.failure and ev.family is not None and ev.family == trigger["family"] and pending:
            joined = True  # a repeated failure of a known family joins its pending trigger
        trigger["count"] += 1
        txn.execute("UPDATE failure_triggers SET subsequent_event_count = ? WHERE trigger_id = ?", (trigger["count"], trigger["trigger_id"]))
        if trigger["count"] >= FAILURE_DEBOUNCE_EVENTS:
            if pending:
                _become_due(txn, trigger, "count", now=now)
            else:
                txn.execute("UPDATE failure_triggers SET due_reason = 'count' WHERE trigger_id = ?", (trigger["trigger_id"],))
    if ev.failure and not joined:
        trigger_id = derived_id("trig", [task_id, ev.event_id])
        txn.execute(
            "INSERT OR IGNORE INTO failure_triggers (trigger_id, task_id, failure_event_id, action_family_digest, subsequent_event_count, due_at, state, failure_sequence, failure_at) VALUES (?, ?, ?, ?, 0, ?, 'pending', ?, ?)",
            (trigger_id, task_id, ev.event_id, ev.family, _plus(ev.time, FAILURE_DEBOUNCE_SECONDS), ev.seq, ev.time),
        )
        txn.mutated(serving_relevant=False)


def run(txn: Any, *, now: str) -> int:
    """Examine every reduced, not yet examined event in commit order; returns how many."""
    cursor = txn.one("SELECT commit_sequence FROM trigger_cursor WHERE singleton = 1")[0]
    reduced = txn.one("SELECT commit_sequence FROM working_cursor WHERE singleton = 1")[0]
    if reduced <= cursor:
        return 0
    rows = txn.execute(
        "SELECT event_id, commit_sequence, envelope, payload, workspace_id FROM events WHERE commit_sequence > ? AND commit_sequence <= ? ORDER BY commit_sequence LIMIT ?",
        (cursor, reduced, EVENTS_PER_PASS),
    ).fetchall()
    last = cursor
    for row in rows:
        ev = _event(row)
        last = ev.seq
        if row[3] is None or not ev.relevant:
            continue  # a forgotten payload is never examined (decision 0017); an expired one is below this cursor
        head = bindings.binding_head(txn, ev.event_id)
        task_id = tasks.resolve_task(txn, head["task_id"]) if head is not None else None
        if task_id is not None:
            observe(txn, ev, task_id, now=now)
    txn.execute("UPDATE trigger_cursor SET commit_sequence = ? WHERE singleton = 1", (last,))
    failpoints.hit(failpoints.TRIGGERS_AFTER_PASS)
    return len(rows)


def reduce_ingested(txn: Any, job: Any, worker: Any) -> None:
    """Ingest reducer (``Worker.ingest_reducers``), after typed reduction in the same fenced transaction."""
    now = worker.clock.now()
    while run(txn, now=now) >= EVENTS_PER_PASS:
        pass


def sweep(store: Any, *, now: str) -> list[str]:
    """Pending triggers whose ten minutes passed without any further event become due."""
    with store.read() as view:
        due = [r[0] for r in view.execute("SELECT trigger_id FROM failure_triggers WHERE state = 'pending' AND due_at <= ? ORDER BY due_at, trigger_id LIMIT 64", (now,)).fetchall()]
    if not due:
        return []
    out = []
    with store.transaction() as txn:
        for trigger_id in due:
            row = txn.one("SELECT trigger_id, task_id, failure_event_id, state FROM failure_triggers WHERE trigger_id = ?", (trigger_id,))
            if row is None or row[3] != "pending":
                continue
            _become_due(txn, {"trigger_id": row[0], "task_id": row[1], "failure_event_id": row[2]}, "time", now=now)
            out.append(trigger_id)
    return out


def triggers(view: Any, task_id: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT trigger_id, task_id, failure_event_id, action_family_digest, subsequent_event_count, due_at, state, due_reason, resolved_by, job_id FROM failure_triggers"
    rows = view.execute(sql + (" WHERE task_id = ?" if task_id else "") + " ORDER BY failure_sequence, trigger_id", (task_id,) if task_id else ()).fetchall()
    keys = ("trigger_id", "task_id", "failure_event_id", "action_family_digest", "subsequent_event_count", "due_at", "state", "due_reason", "resolved_by", "job_id")
    return [dict(zip(keys, r, strict=True)) for r in rows]


__all__ = ["run", "reduce_ingested", "sweep", "observe", "triggers", "RELEVANT_KINDS"]
