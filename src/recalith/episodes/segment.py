"""Episode boundaries: when a task's open range becomes an episode (SYSTEM_SPEC §3.3, §3.5).

A task's *open range* is its bound events not yet in one of its episodes.
Checkpoints are compaction, session end, an idle pause and an explicit
boundary resolution. At a checkpoint the range becomes a **settled**
episode, unless that would sever an attempt from its later result or fix:

* an unresolved failure (a test/build whose latest outcome in the range is a
  failure) keeps the range open, and the checkpoint stays pending until the
  same test/build passes, so failure, change and later result land in one
  episode across chunk and compaction boundaries;
* a pending call (started, no result yet) keeps it open too, except at
  session end, where an unanswered call (a denied tool, for example) is
  recorded as unresolved instead of holding the episode forever.

A range that reaches :data:`MAX_STEPS` steps becomes an episode regardless,
``open`` when something is still unresolved; the next episode names it in
``related_episode_ids`` and carries its unresolved items as context, never
as new evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from recalith.working import tasks
from recalith.working.tasks import Ev

MAX_STEPS = 64


@dataclass
class RangeState:
    steps: int = 0
    tool_steps: int = 0
    unresolved: dict[str, Ev] = field(default_factory=dict)  # action signature -> latest failing result
    pending: dict[str, Ev] = field(default_factory=dict)  # tool_call_id -> start without a result


def range_state(events: Sequence[Ev], *, finished_calls: set[str] = frozenset()) -> RangeState:  # type: ignore[assignment]
    """Steps, unresolved test/build failures and unanswered calls of an ordered range.

    ``finished_calls`` names calls whose result exists outside the range (a
    late result already reduced elsewhere), so they are not pending.
    """
    state = RangeState()
    for ev in events:
        if ev.kind == "tool_started" and ev.tool_call_id:
            state.pending[ev.tool_call_id] = ev
            state.steps += 1
            state.tool_steps += 1
        elif ev.kind == "tool_finished":
            if ev.tool_call_id in state.pending:
                del state.pending[ev.tool_call_id]
            else:
                state.steps += 1
                state.tool_steps += 1
            if tasks.action_kind(ev) in tasks.TEST_BUILD_KINDS:
                signature = tasks.action_signature(ev)
                if ev.payload.get("outcome") == "failure":
                    state.unresolved[signature] = ev
                elif ev.payload.get("outcome") == "success":
                    state.unresolved.pop(signature, None)
        elif ev.is_user_request:
            state.steps += 1
    for call in list(state.pending):
        if call in finished_calls:
            del state.pending[call]
    return state


def decide(state: RangeState, *, checkpoint: bool, session_end: bool) -> str | None:
    """``settled``, ``open`` (flushed at the step cap while unresolved) or None (keep the range open)."""
    if state.tool_steps == 0:
        return None
    resolved = not state.unresolved and (session_end or not state.pending)
    if state.tool_steps >= MAX_STEPS:
        return "settled" if resolved else "open"
    if checkpoint and resolved:
        return "settled"
    return None
