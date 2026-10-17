"""Bounded episode condensation (SYSTEM_SPEC §3.3; DATA_CONTRACTS §4, §11).

:func:`episode_body` turns a task's ordered range into the body of a
``create_episode`` operation; :func:`build_episode` (the public interface)
returns it as an :class:`Episode` without writing anything. Persistence is a
``create_episode`` operation through ``controller.apply``.

* **Steps.** Each tool call is one step: its action cites the call, its
  result the result event, and its outcome is the certified execution
  outcome (``unknown`` while the call awaits a result). Later user messages
  are steps too, so a correction stays in the episode of the attempt it
  corrects.
* **Successful-result preservation.** A result keeps its type, exit code,
  certified test assertions, error signature and a bounded excerpt quoted
  exactly from the stored result text (with its locator), for successes as
  well as failures; never a one-line ``ok``.
* **Carried context.** The objective, a call whose start lies in an earlier
  range, and the unresolved items of a previous open episode are cited with
  relation ``context``: they connect the episode to earlier chunks without
  becoming new support. Support links name only events inside the episode.
* **Uncertainty.** Deterministic condensation makes no causal claim: every
  ``causal_assessment`` is null; a later model narrative may add an inferred
  one through ``revise_episode``.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from recalith.contracts.common import InstallationContext, new_id
from recalith.contracts.memory import Episode
from recalith.episodes import segment as episode_segment
from recalith.working import tasks
from recalith.working.tasks import Ev

EXCERPT_CHARS = 240
USER_STEP_CHARS = 300
TITLE_MAX = 256


def _as_context(item: dict[str, Any], inside: set[str]) -> dict[str, Any]:
    """Links to events outside the episode become context, never support."""
    links = []
    for link in item.get("evidence") or []:
        if link["ref"]["kind"] != "event" or link["ref"]["id"] not in inside:
            link = {**link, "relation": "context"}
        links.append(link)
    return {**item, "evidence": links}


def _result(ev: Ev) -> dict[str, Any]:
    links = [tasks.result_link(ev)]
    text = tasks.result_summary(ev)
    stored = ev.payload.get("result_text")
    if isinstance(stored, str) and stored:
        head = stored
        for chunk in ev.payload.get("text_chunks") or []:
            if chunk.get("stored_field") == "result_text_head" and isinstance(chunk.get("text"), str):
                head = chunk["text"]
        n = min(len(head), EXCERPT_CHARS)
        excerpt = stored[:n]
        text = f"{text}\n{excerpt}" + ("…" if n < len(stored) else "")
        links.append(tasks.event_link(ev, field="result_text", length=n))
    return tasks.supported(text, links, "observed")


def episode_body(
    task_id: str,
    task_data: dict[str, Any],
    events: Sequence[Ev],
    *,
    start_of: Callable[[Ev], Ev | None],
    state: str,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A ``create_episode`` payload for one ordered range of a task's events."""
    inside = {ev.event_id for ev in events}
    objective = task_data.get("objective")
    objective_id = None
    if objective:
        objective_id = next((link["ref"]["id"] for link in objective.get("evidence") or [] if link["ref"]["kind"] == "event"), None)
        objective = _as_context(objective, inside)
    else:
        objective = tasks.supported("Objective not stated in the captured events.", [], "inferred")
    steps: list[dict[str, Any]] = []
    by_call: dict[str, int] = {}
    tool_steps: list[int] = []
    for ev in events:
        if ev.kind == "tool_started" and ev.tool_call_id:
            by_call[ev.tool_call_id] = len(steps)
            tool_steps.append(len(steps))
            steps.append({"ordinal": len(steps), "action": tasks.supported(tasks.action_label(ev), [tasks.event_link(ev)], "observed"), "result": None, "outcome": "unknown", "causal_assessment": None})
        elif ev.kind == "tool_finished":
            index = by_call.get(ev.tool_call_id or "")
            if index is None:
                start = start_of(ev)
                action_links = [tasks.event_link(start, relation="supports" if start.event_id in inside else "context")] if start is not None else []
                steps.append({"ordinal": len(steps), "action": tasks.supported(tasks.action_label(ev), action_links, "observed"), "result": None, "outcome": "unknown", "causal_assessment": None})
                index = len(steps) - 1
                tool_steps.append(index)
            steps[index]["result"] = _result(ev)
            steps[index]["outcome"] = ev.payload.get("outcome") or "unknown"
        elif ev.is_user_request and ev.event_id != objective_id:
            text = ev.payload["text"]
            n = min(len(text), USER_STEP_CHARS)
            steps.append({"ordinal": len(steps), "action": tasks.supported(f"User: {text[:n]}", [tasks.event_link(ev, field="text", length=n)], "user_declared"), "result": None, "outcome": "unknown", "causal_assessment": None})
    calls = [steps[i] for i in tool_steps]
    counts: dict[str, int] = {}
    for s in calls:
        counts[s["outcome"]] = counts.get(s["outcome"], 0) + 1
    finished = [ev for ev in events if ev.kind == "tool_finished"]
    summary = ", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "no tool calls"
    last = finished[-1] if finished else None
    outcome_text = f"{len(calls)} actions ({summary})" + (f"; last result: {tasks.result_summary(last)}" if last is not None else "") + "; causes not assessed"
    outcome = tasks.supported(outcome_text, [tasks.result_link(last)] if last is not None else [], "observed")
    rs = episode_segment.range_state(events)
    unresolved = [tasks.supported(f"{tasks.action_label(ev)} still fails (exit {ev.payload.get('exit_code')})", [tasks.result_link(ev)], "observed") for ev in rs.unresolved.values()]
    unresolved += [tasks.supported(f"{tasks.action_label(ev)}: awaiting result", [tasks.event_link(ev)], "observed") for ev in rs.pending.values()]
    preconditions = [_as_context(item, inside) for item in (previous or {}).get("unresolved") or []] if previous and previous.get("state") == "open" else []
    times = [ev.time for ev in events]
    title = task_data.get("title") or tasks.DEFAULT_TITLE
    return {
        "task_id": task_id,
        "title": title[:TITLE_MAX],
        "state": state,
        "started_at": min(times),
        "ended_at": max(times) if state == "settled" else None,
        "objective": objective,
        "preconditions": preconditions,
        "steps": steps,
        "outcome": outcome,
        "unresolved": unresolved,
        "source_event_ids": [ev.event_id for ev in events],
        "related_episode_ids": [previous["episode_id"]] if previous else [],
    }


def build_episode(ctx: InstallationContext, task_id: str, event_ids: Sequence[str], *, store: Any = None) -> Episode:
    """The episode these events would form (DATA_CONTRACTS §11); nothing is written."""
    from recalith.storage import records
    from recalith.storage.db import open_store
    from recalith.working import bindings

    own = store is None
    store = store or open_store(ctx, readonly=True)
    try:
        with store.read() as view:
            current = tasks.head_state(view, task_id)
            if current is None:
                raise ValueError("no such task")
            events = tasks.load_events(view, event_ids)
            if not events:
                raise ValueError("an episode needs at least one source event")

            def start_of(ev: Ev) -> Ev | None:
                other = bindings.partner_id(view, ev)
                found = tasks.load_events(view, [other]) if other else []
                return found[0] if found else None

            book = bindings.task_book(view, task_id)
            previous = None
            if book["last_episode_id"]:
                head = records.head(view, "episode", book["last_episode_id"])
                previous = records.body(view, "episode", book["last_episode_id"], head[0]) if head else None
            finished = {ev.tool_call_id for ev in events if ev.kind == "tool_finished" and ev.tool_call_id}
            state = "settled" if episode_segment.decide(episode_segment.range_state(events, finished_calls=finished), checkpoint=True, session_end=True) == "settled" else "open"
            body = episode_body(task_id, current[2], events, start_of=start_of, state=state, previous=previous)
    finally:
        if own:
            store.close()
    return Episode.model_validate({**body, "episode_id": new_id("ep"), "project_id": ctx.project_id, "installation_id": ctx.installation_id, "revision": 1, "coverage": {}})
