"""Claim extraction: bounded input selection, deterministic no-op and scheduling (SYSTEM_SPEC §3.5, §6.2–§6.3, §7; decision 0011).

Extraction is a model job (``extract_claims``, ordinary pool, band 4). It
returns the standard ``ModelResponse``; it never writes records itself:
everything it proposes is persisted and applied through
``controller.apply.apply_proposal`` and admitted by ``controller.admission``,
so a proposed claim is a weak candidate until its review passes (or an
``observed`` fact whose mapping code verifies).

**When.** Two deterministic triggers schedule it, both inside the
transaction that establishes them: a *settled* episode with steps (the
attempt boundary of SYSTEM_SPEC §3.5; due after the quiet window so its
narrative usually lands first), and a *due* failure trigger
(``controller.triggers``: a failure not fixed within six relevant task events
or ten minutes).

**What** (:func:`select`). The job's named events and episodes; for a trigger,
the failure and at most 24 later events of its task; the task state; its
pending boundary candidates with the binding revisions their events have
now, and those candidates' first events. This is where weak boundary
candidates are *folded* (decision 0008): extraction may return
``resolve_task_binding`` for them, or leave them pending, and they never get
model jobs of their own. Existing knowledge is a bounded slice (16): live
claims citing a selected event or sharing a selected failure's action
family first, then the most recent. Earlier review rationale and provider
provenance are withheld.

**No-op** (:func:`worth_extracting`). Low-information selections (reads,
edits, routine successes and lifecycle events only, with no user request,
failure, certified assertion, test/build result or pending boundary) are
cancelled without a call (``nothing_to_extract``), and a model may always
answer with an empty proposal and a ``no_op_reason``.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from recalith.contracts.common import InstallationContext, RecordRef, digest_of, format_utc, parse_utc
from recalith.contracts.events import EventEnvelope
from recalith.contracts.jobs import Job
from recalith.contracts.memory import ClaimRevision
from recalith import prompts
from recalith.controller import jobs, requests
from recalith.privacy import capsules
from recalith.storage import records
from recalith.working import bindings, tasks

MAX_TRIGGER_EVENTS = 24
MAX_CLAIMS = 16
EXTRACT_DUE_SECONDS = requests.QUIET_SECONDS
LIVE = ("candidate", "active", "disputed")


def _trigger(view: Any, trigger_id: str | None) -> tuple[str, str, int] | None:
    if trigger_id is None:
        return None
    row = view.execute("SELECT task_id, failure_event_id, failure_sequence FROM failure_triggers WHERE trigger_id = ?", (trigger_id,)).fetchone()
    return None if row is None else (row[0], row[1], int(row[2]))


def _after_failure(view: Any, task_id: str, sequence: int) -> list[str]:
    rows = view.execute(
        "SELECT event_id FROM task_binding_heads WHERE task_id = ? AND commit_sequence > ? ORDER BY commit_sequence LIMIT ?",
        (task_id, sequence, MAX_TRIGGER_EVENTS),
    ).fetchall()
    return [r[0] for r in rows]


def _relevant_claims(view: Any, event_ids: list[str], families: set[str]) -> list[ClaimRevision]:
    ids: list[str] = []
    for i in range(0, len(event_ids), 400):
        chunk = event_ids[i : i + 400]
        marks = ",".join("?" for _ in chunk)
        rows = view.execute(f"SELECT DISTINCT owner_id FROM evidence_links WHERE owner_kind = 'claim' AND target_kind = 'event' AND target_id IN ({marks})", tuple(chunk)).fetchall()  # noqa: S608
        ids += [r[0] for r in rows]
        rows = view.execute(  # links redirected to these events' capsules (decision 0025)
            f"SELECT DISTINCT owner_id FROM evidence_links WHERE owner_kind = 'claim' AND target_kind = 'capsule' AND target_id IN ({marks})", tuple(capsules.capsule_targets(chunk)),  # noqa: S608
        ).fetchall()
        ids += [r[0] for r in rows]
    for family in sorted(families):
        ids += [r[0] for r in view.execute("SELECT claim_id FROM claim_heads WHERE kind = 'failure_lesson' AND action_family_digest = ?", (family,)).fetchall()]
    marks = ",".join("?" for _ in LIVE)
    ids += [r[0] for r in view.execute(f"SELECT claim_id FROM claim_heads WHERE status IN ({marks}) ORDER BY rowid DESC LIMIT ?", (*LIVE, MAX_CLAIMS)).fetchall()]  # noqa: S608
    out: list[ClaimRevision] = []
    for claim_id in dict.fromkeys(ids):
        head = records.head(view, "claim", claim_id)
        if head is None or head[1] not in LIVE:
            continue
        claim = records.load(view, "claim", claim_id, head[0])
        if claim is not None:
            out.append(requests.claim_for_request(claim))
        if len(out) >= MAX_CLAIMS:
            break
    return out


def _families(loaded: list[tuple[int, EventEnvelope]]) -> set[str]:
    from recalith.capture.normalize import action_family_digest

    out = set()
    for _seq, env in loaded:
        action = env.payload.get("action")
        if env.kind == "tool_finished" and env.payload.get("outcome") == "failure" and isinstance(action, dict):
            family = action_family_digest(env.workspace_id, action)
            if family is not None:
                out.add(family)
    return out


def worth_extracting(loaded: list[tuple[int, EventEnvelope]], *, boundaries: int) -> bool:
    """Anything a durable claim could rest on; otherwise the job is cancelled without a call."""
    if boundaries:
        return True
    for _seq, env in loaded:
        payload = env.payload
        if env.kind == "user_message" and env.channel == "user" and env.authority == "explicit_user":
            return True
        if env.kind in ("operator_declaration", "operator_correction"):
            return True
        if env.kind == "tool_finished":
            action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
            if payload.get("outcome") in ("failure", "interrupted") or payload.get("assertions") or action.get("action_kind") in ("test", "build"):
                return True
    return False


def select(view: Any, ctx: InstallationContext, job: Job) -> requests.Selection:
    """The bounded inputs of one extraction job (this installation's store only)."""
    sel = requests.Selection()
    task_id: str | None = None
    for ref in job.input_refs:
        if ref.kind == "event":
            sel.add_events([ref.id])
        elif ref.kind == "episode":
            current = records.head(view, "episode", ref.id)
            episode = records.load(view, "episode", ref.id, current[0]) if current is not None else None
            if episode is not None and current is not None and current[1] != "archived":
                sel.episodes.append(episode)
                sel.add_events(episode.source_event_ids)
                task_id = task_id or episode.task_id
        elif ref.kind == "task":
            task_id = task_id or ref.id
    trigger = _trigger(view, job.trigger_ref)
    if trigger is not None:
        task_id = trigger[0]
        sel.add_events([trigger[1]])
        sel.add_events(_after_failure(view, tasks.resolve_task(view, trigger[0]) or trigger[0], trigger[2]))
    if task_id is None and sel.events:
        head = bindings.binding_head(view, sel.events[0])
        task_id = head["task_id"] if head else None
    sel.task = requests._task(view, task_id)  # noqa: SLF001
    if sel.task is not None:
        sel.boundaries = requests._boundaries(view, sel.task.task_id)  # noqa: SLF001
        for boundary in sel.boundaries:  # folded: decided here or left pending, never a job of their own
            sel.add_events(boundary.candidate.proposed_event_ids[:8])
    loaded = requests.load_events(view, ctx, sel.events)
    if not worth_extracting(loaded, boundaries=len(sel.boundaries)):
        raise requests.NothingToPrepare("nothing_to_extract")
    sel.claims = _relevant_claims(view, [e.event_id for _s, e in loaded], _families(loaded))
    return sel


# --------------------------------------------------------------------------
# Scheduling (inside the caller's transaction)


def schedule_for_episode(txn: Any, *, episode_ref: RecordRef, now: str) -> str | None:
    """One extraction per new settled episode with steps, after the quiet window."""
    current = records.head(txn, "episode", episode_ref.id)
    body = records.body(txn, "episode", episode_ref.id, episode_ref.revision) if current is not None else None
    if body is None or body.get("state") != "settled" or not body.get("steps"):
        return None
    due = format_utc(parse_utc(now) + _dt.timedelta(seconds=EXTRACT_DUE_SECONDS))
    key = digest_of(["extract", "episode", episode_ref.id])
    job_id, new = jobs.enqueue(txn, kind="extract_claims", input_refs=[RecordRef(kind="episode", id=episode_ref.id, revision=1)], now=now, due_at=due, prompt_version=prompts.CURRENT["extract_claims"], idempotency=key)
    return job_id if new else None


def schedule_for_trigger(txn: Any, *, trigger_id: str, task_id: str, failure_event_id: str, now: str) -> str:
    """The extraction a due failure trigger asks for (its ``trigger_ref`` names the trigger)."""
    key = digest_of(["extract", "trigger", trigger_id])
    job_id, _new = jobs.enqueue(
        txn, kind="extract_claims", input_refs=[RecordRef(kind="event", id=failure_event_id, revision=1)], now=now, prompt_version=prompts.CURRENT["extract_claims"], idempotency=key, trigger_ref=trigger_id,
    )
    return job_id


__all__ = ["select", "worth_extracting", "schedule_for_episode", "schedule_for_trigger", "MAX_TRIGGER_EVENTS"]
