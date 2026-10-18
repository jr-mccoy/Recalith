"""Task 6: task state, versioned bindings and cross-session continuity (A10, A11, A13, A57).

Events enter through the real Claude Code 2.1.301 hook mapping and are
ingested and reduced by a real worker (``working_scenarios``). A test that
needs a payload no real fixture holds uses a *synthetic variant* of a real
record and says so in its docstring (another host session, a changed prompt,
path or command, or a controlled capture time). Model decisions are recorded
proposals applied through the worker's real path; they exercise mechanics,
not live segmentation quality (ACCEPTANCE_TESTS §2, §5).
"""

from __future__ import annotations

import json
import threading
import time

import pytest

import operation_scenarios as osc
import worker_scenarios as ws
import working_scenarios as wks
from working_scenarios import record, session_id, variant
from recalith.capture import pipeline
from recalith.contracts.common import RecordRef, derived_id, new_id, utc_now
from recalith.contracts.config import BudgetConfig, ProjectConfig, SegmentationConfig
from recalith.contracts.events import EventEnvelope
from recalith.controller import budgets, jobs, worker
from recalith.errors import RecalithError
from recalith.storage import db, failpoints, spool
from recalith.working import bindings, reducer, segment, tasks

A = wks.LIFECYCLE_SESSION


@pytest.fixture(autouse=True)
def _disarm():
    failpoints.disarm_all()
    yield
    failpoints.disarm_all()


def call(scenario: str, tool_use_id: str, *, post: str = "PostToolUse", **kw):
    return [variant(record(scenario, "PreToolUse", tool_use_id), **kw), variant(record(scenario, post, tool_use_id), **kw)]


def start_and_prompt(p: wks.Project, *, session: str | None = None, prompt: str | None = None, at: str | None = None) -> None:
    p.send(variant(record("lifecycle", "SessionStart"), session=session), at=at)
    p.send(variant(record("lifecycle", "UserPromptSubmit"), session=session, prompt=prompt), at=at)


def root_actions(p: wks.Project, *, session: str | None = None, suffix: str | None = None, pending_last: bool = False) -> None:
    """Read notes.txt, Write new.txt, Edit new.txt: three real @root actions (variants for another session)."""
    for i, call_id in enumerate(("toolu_probe_0007", "toolu_probe_0009", "toolu_probe_0010")):
        pre, post = call("lifecycle", call_id, session=session, tool_suffix=suffix)
        p.send(pre)
        if not (pending_last and i == 2):
            p.send(post)


def task_by_objective(p: wks.Project, text: str) -> dict:
    found = [t for t in p.tasks() if (t["objective"] or {}).get("text") == text]
    assert len(found) == 1, [(t["objective"] or {}).get("text") for t in p.tasks()]
    return found[0]


def counts(p: wks.Project) -> dict:
    with p.view() as v:
        return tasks.task_counts(v, p.ctx.workspace_id)


def next_action(p: wks.Project, task: dict, ev: dict, text: str):
    op = osc.op("next", "update_task", {"task_id": task["task_id"], "expected_revision": task["revision"], "patches": [{"op": "set", "field": "next_action", "value": wks.supported(ev, text)}]})
    return p.propose("update_task", [op], input_refs=[RecordRef(kind="task", id=task["task_id"], revision=task["revision"])])


LIFECYCLE_PROMPT = "FIXTURE lifecycle: run the scripted tools."


# ---------------------------------------------------------------------------
# A10: parallel tasks


def test_parallel_tasks_keep_distinct_next_actions(tmp_path):
    """Two sessions interleave; each objective, next action and pending result stays with its task (A10).

    Synthetic variants: session B is a second host session (session and
    tool-use IDs changed) working in ``web/``; session A's Read targets
    ``src/app.py``. Session A's pytest result arrives late, after B's events.
    """
    p = wks.Project(tmp_path)
    b = session_id(2)
    start_and_prompt(p)
    start_and_prompt(p, session=b, prompt="Build the fixture web page.")
    a_read = call("lifecycle", "toolu_probe_0007", replace={"<workspace>/notes.txt": "<workspace>/src/app.py"})
    b_reads = [
        call("lifecycle", "toolu_probe_0007", session=b, tool_suffix="b", replace={"<workspace>/notes.txt": "<workspace>/web/index.html"}),
        call("lifecycle", "toolu_probe_0010", session=b, tool_suffix="b", replace={"<workspace>/new.txt": "<workspace>/web/page.html"}),
        call("lifecycle", "toolu_probe_0008", post="PostToolUseFailure", session=b, tool_suffix="b", replace={"<workspace>/missing.txt": "<workspace>/web/style.css"}),
    ]
    p.send(a_read[0])
    p.send(b_reads[0][0])
    p.send(a_read[1])
    p.send(b_reads[0][1])
    a_pytest = call("lifecycle", "toolu_probe_0002", post="PostToolUseFailure")
    p.send(a_pytest[0])  # A's call is pending while B works
    for pre, post in b_reads[1:]:
        p.send(pre)
        p.send(post)
    p.drain()
    task_a, task_b = task_by_objective(p, LIFECYCLE_PROMPT), task_by_objective(p, "Build the fixture web page.")
    assert [x["tool_call_id"] for x in task_a["pending_actions"]] == ["toolu_probe_0002"] and task_b["pending_actions"] == []
    assert p.boundaries("single_active_task") == []  # web/ actions are outside A's clusters: no automatic link
    p.send(a_pytest[1])  # the late result follows its call, not the session that was last active
    p.drain()
    task_a, task_b = task_by_objective(p, LIFECYCLE_PROMPT), task_by_objective(p, "Build the fixture web page.")
    assert task_a["pending_actions"] == [] and any("pytest -q test_long.py" in r["text"] for r in task_a["known_results"])
    assert not any("pytest" in r["text"] for r in task_b["known_results"])
    # Recorded narrative patches, one per task, through the worker's real application path.
    fail = p.event("tool_finished", call="toolu_probe_0002")
    edit = p.event("tool_finished", call="toolu_probe_0010_b")
    assert next_action(p, task_a, fail, "Fix test_long and rerun pytest.").decisions[0].outcome == "apply"
    assert next_action(p, task_b, edit, "Style the fixture page.").decisions[0].outcome == "apply"
    # Both sessions keep working; typed reduction never clears a field it did not touch.
    for pre, post in [call("lifecycle", "toolu_probe_0001", session=b, tool_suffix="b2"), call("lifecycle", "toolu_probe_0009", replace={"<workspace>/new.txt": "<workspace>/src/new.py"})]:
        p.send(pre)
        p.send(post)
    p.drain()
    task_a, task_b = task_by_objective(p, LIFECYCLE_PROMPT), task_by_objective(p, "Build the fixture web page.")
    assert task_a["next_action"]["text"] == "Fix test_long and rerun pytest." and task_b["next_action"]["text"] == "Style the fixture page."
    assert {p.task_of(e["id"]) for e in p.events(session=p.sid(b))} == {task_b["task_id"]}
    assert {p.task_of(e["id"]) for e in p.events() if e["session_id"] != p.sid(b)} == {task_a["task_id"]}
    assert counts(p) == {"active": 2, "paused": 0, "completed": 0, "abandoned": 0, "placeholders": 0, "nonredirected": 2}


# ---------------------------------------------------------------------------
# A11: idle, passing tests and commits never complete a task


def test_idle_does_not_complete_task(tmp_path):
    """Idle → paused, a pass or a commit → still not completed; completion needs completion evidence (A11).

    Real lifecycle session; synthetic variants for the 24-hour gap (controlled
    capture time), a ``git commit`` command and the user's completion statement.
    """
    p = wks.Project(tmp_path)
    p.scenario("lifecycle")
    p.drain()
    task = task_by_objective(p, LIFECYCLE_PROMPT)
    assert task["status"] == "active" and len(task["blockers"]) == 2
    p.drain(clock=wks.fake_clock_at(wks.later(hours=25)))
    task = p.task(task["task_id"])
    assert (task["status"], task["completion_basis"]) == ("paused", None)
    assert len(task["blockers"]) == 2  # pausing keeps what is still open
    resume = wks.later(hours=26)
    p.send(record("secret_and_resume", "SessionStart"), at=resume)
    p.send(variant(record("lifecycle", "UserPromptSubmit"), prompt="Let's continue."), at=resume)
    for pre, post in [call("lifecycle", "toolu_probe_0004", tool_suffix="r"), call("lifecycle", "toolu_probe_0001", tool_suffix="c", command="git commit -m fixture")]:
        p.send(pre, at=resume)
        p.send(post, at=resume)
    p.drain(clock=wks.fake_clock_at(wks.later(hours=26, minutes=5)))
    task = p.task(task["task_id"])
    assert task["status"] == "active" and task["completion_basis"] is None  # resumed, never completed by a pass or a commit
    assert len(task["blockers"]) == 2  # an unrelated passing test closes nothing
    idle = p.boundaries("idle_resume")
    assert [b["state"] for b in idle] == ["pending"] and idle[0]["signal"]["idle_minutes"] >= 30  # a candidate, not a split
    assert len(p.tasks()) == 1
    # A model completion without completion evidence is refused.
    bare = osc.op("done", "update_task", {"task_id": task["task_id"], "expected_revision": task["revision"], "patches": [{"op": "status", "status": "completed"}]})
    refused = p.propose("update_task", [bare], input_refs=[RecordRef(kind="task", id=task["task_id"], revision=task["revision"])])
    assert [(d.outcome, d.reason_code) for d in refused.decisions] == [("reject", "completion_requires_evidence")]
    p.send(variant(record("lifecycle", "UserPromptSubmit"), prompt="The fixture lifecycle task is complete."), at=wks.later(hours=26, minutes=10))
    p.drain(clock=wks.fake_clock_at(wks.later(hours=26, minutes=15)))
    task = p.task(task["task_id"])
    statement = p.event("user_message", text="is complete")
    done = osc.op("done", "update_task", {"task_id": task["task_id"], "expected_revision": task["revision"], "patches": [
        {"op": "set", "field": "completion_basis", "value": wks.supported(statement, "The user stated the task is complete.", basis="user_declared")},
        {"op": "status", "status": "completed"},
    ]})
    assert p.propose("update_task", [done], input_refs=[RecordRef(kind="task", id=task["task_id"], revision=task["revision"])]).decisions[0].outcome == "apply"
    task = p.task(task["task_id"])
    assert task["status"] == "completed" and task["completion_basis"]["evidence"][0]["ref"]["id"] == statement["id"]


# ---------------------------------------------------------------------------
# A13: an expected red test, a denied call, an interruption and a search miss


def test_expected_red_test_is_not_a_failed_approach(tmp_path):
    """Exit statuses alone create no failed-approach lesson; red→green closes the blocker (A13).

    Real: the failing ``pytest -q test_mid.py``, the Edit, the ``grep``
    no-match and the denied session. Synthetic variants: the TDD prompt, the
    green rerun of test_mid (the real passing pytest payload with its command
    changed) and an interrupted call (``is_interrupt: true``, never observed
    headless).
    """
    p = wks.Project(tmp_path)
    start_and_prompt(p, prompt="Write a failing test for test_mid first, then make it pass.")
    p.send_all(call("lifecycle", "toolu_probe_0003", post="PostToolUseFailure"))  # expected red
    p.drain()
    task = task_by_objective(p, "Write a failing test for test_mid first, then make it pass.")
    assert [b["text"] for b in task["blockers"]] == ["Bash `pytest -q test_mid.py` fails (exit 1)"]
    p.send_all(call("lifecycle", "toolu_probe_0010"))
    p.send(variant(record("lifecycle", "PreToolUse", "toolu_probe_0003"), tool_suffix="green"))
    p.send(variant(record("lifecycle", "PostToolUse", "toolu_probe_0004"), replace={"toolu_probe_0004": "toolu_probe_0003_green", "pytest -q -s test_pass.py": "pytest -q test_mid.py"}))
    p.send_all(call("lifecycle", "toolu_probe_0006"))  # grep no-match arrives as success
    p.send_all(call("lifecycle", "toolu_probe_0012", post="PostToolUseFailure", tool_suffix="i", interrupt=True))
    p.scenario("denied")
    p.drain()
    task = p.task(task["task_id"])
    assert task["blockers"] == []  # the green rerun closed it
    results = [r["text"] for r in task["known_results"]]
    assert any(r.startswith("Bash `pytest -q test_mid.py`: success") for r in results) and not any(r.startswith("Bash `pytest -q test_mid.py`: failure") for r in results)
    assert any(r.startswith("Bash `grep -c nomatch notes.txt`: success") for r in results)
    assert any(r.startswith("Bash `sleep 5`: interrupted") for r in results)
    denied = task_by_objective(p, "FIXTURE denied: run the scripted tool.")
    assert [(x["tool_call_id"], x["state"]) for x in denied["pending_actions"]] == [("toolu_probe_0016", "awaiting_result")]  # never a success
    # No lesson, claim or failure-driven extraction came from exit statuses: the expected red's debounce
    # trigger (A66, Task 9) was resolved by the green rerun of the same task and action family. The only
    # extraction work is the settled attempt's own (an episode checkpoint, semantic A13 review applies).
    assert p.count("SELECT COUNT(*) FROM claim_heads") == 0
    assert p.count("SELECT COUNT(*) FROM jobs WHERE kind IN ('review_claims', 'revalidate')") == 0
    assert p.count("SELECT COUNT(*) FROM jobs WHERE kind = 'extract_claims' AND body NOT LIKE '%\"trigger_ref\":null%'") == 0
    green = p.event("tool_finished", call="toolu_probe_0003_green")["id"]
    assert p.count("SELECT COUNT(*) FROM failure_triggers") == 1
    assert p.count("SELECT COUNT(*) FROM failure_triggers WHERE state = 'resolved' AND resolved_by = ?", (green,)) == 1
    assert all(e["payload"]["expected_red"] is False for e in p.events("tool_finished"))
    p.send(record("lifecycle", "SessionEnd"))
    p.drain()
    [episode] = [e for e in p.episodes(task["task_id"])]
    outcomes = [s["outcome"] for s in episode["steps"] if not s["action"]["text"].startswith("User: ")]
    assert outcomes == ["failure", "success", "success", "success", "interrupted"]
    assert all(s["causal_assessment"] is None for s in episode["steps"]) and episode["coverage"]["causal_assessment"] == "unassessed"


# ---------------------------------------------------------------------------
# A57: boundaries, splits and late results


def pivot_project(tmp_path, *, pending_call: bool = True, then_reply: bool = False) -> tuple[wks.Project, dict]:
    """Real lifecycle start/prompt; synthetic variant: a pivot prompt, then pytest started (and the real reply prompt)."""
    p = wks.Project(tmp_path)
    start_and_prompt(p)
    p.send(variant(record("lifecycle", "UserPromptSubmit"), prompt="new task: write the release notes"))
    if pending_call:
        p.send(record("lifecycle", "PreToolUse", "toolu_probe_0002"))
    if then_reply:
        p.send(record("lifecycle", "UserPromptSubmit", n=1))
    p.drain()
    [pivot] = p.boundaries("pivot_prefix")
    return p, pivot


def test_provisional_split_preserves_late_result(tmp_path):
    """A confirmed split moves an exact range; the call's late result follows it; a detaching split is refused.

    The split range is the pivot and the started call only: the session's later reply stays with the source,
    so the late result must follow its call (by tool_call_id), not the session.
    """
    p, pivot = pivot_project(tmp_path, then_reply=True)
    source = task_by_objective(p, LIFECYCLE_PROMPT)
    assert pivot["state"] == "pending" and pivot["source_task_id"] == source["task_id"]
    pivot_event = p.event("user_message", text="new task:")
    started = p.event("tool_started", call="toolu_probe_0002")
    assert {p.task_of(pivot_event["id"]), p.task_of(started["id"])} == {source["task_id"]}  # provisional until decided
    split = p.binding_op("split", "confirm_split", pivot["boundary_id"], [pivot_event["id"], started["id"]])
    assert p.propose("update_task", [split]).decisions[0].outcome == "apply"
    new = task_by_objective(p, "new task: write the release notes")
    source = p.task(source["task_id"])
    assert source["objective"]["text"] == LIFECYCLE_PROMPT and source["pending_actions"] == []
    assert [x["tool_call_id"] for x in new["pending_actions"]] == ["toolu_probe_0002"]
    assert p.binding(started["id"])["binding"] == "confirmed" and p.binding(started["id"])["revision"] == 2
    reply = p.event("user_message", text="Reply OK.")
    assert p.task_of(reply["id"]) == source["task_id"]  # outside the range: the session continues in the source
    p.send(record("lifecycle", "PostToolUseFailure", "toolu_probe_0002"))  # the late result
    p.drain()
    finished = p.event("tool_finished", call="toolu_probe_0002")
    assert p.task_of(finished["id"]) == new["task_id"]
    new = p.task(new["task_id"])
    assert new["pending_actions"] == [] and [b["text"] for b in new["blockers"]] == ["Bash `pytest -q test_long.py` fails (exit 1)"]
    assert p.task(source["task_id"])["blockers"] == []
    # A split that would leave an arrived result behind its call is rejected and changes nothing.
    p.send(variant(record("lifecycle", "UserPromptSubmit"), prompt="new task: something else"))
    p.send_all(call("lifecycle", "toolu_probe_0001"))
    p.drain()
    second = [b for b in p.boundaries("pivot_prefix") if b["state"] == "pending"][0]
    new = p.task(new["task_id"])
    pivot2 = p.event("user_message", text="something else")
    echo_start = p.event("tool_started", call="toolu_probe_0001")
    detach = p.binding_op("detach", "confirm_split", second["boundary_id"], [pivot2["id"], echo_start["id"]])
    result = p.propose("update_task", [detach])
    assert [(d.outcome, d.reason_code) for d in result.decisions] == [("reject", "detaches_call_result")]
    assert p.task_of(echo_start["id"]) == source["task_id"] and len(p.tasks()) == 2


def test_pending_result_joins_its_call_across_sessions(tmp_path):
    """A result reported in another session joins its call by tool_call_id.

    Synthetic variant: the real failing-pytest result delivered under a second host session.
    """
    p = wks.Project(tmp_path)
    start_and_prompt(p)
    p.send(record("lifecycle", "PreToolUse", "toolu_probe_0002"))
    b = session_id(5)
    start_and_prompt(p, session=b, prompt="A different piece of work.")
    p.send(variant(record("lifecycle", "PostToolUseFailure", "toolu_probe_0002"), session=b))
    p.drain()
    owner = task_by_objective(p, LIFECYCLE_PROMPT)
    other = task_by_objective(p, "A different piece of work.")
    assert p.task_of(p.event("tool_finished", call="toolu_probe_0002")["id"]) == owner["task_id"]
    assert owner["pending_actions"] == [] and owner["blockers"] and other["blockers"] == [] and other["known_results"] == []


def test_rejected_split_keeps_objective(tmp_path):
    """A rejected candidate moves nothing: one task, its objective intact, the events confirmed where they are."""
    p, pivot = pivot_project(tmp_path, pending_call=False)
    source = task_by_objective(p, LIFECYCLE_PROMPT)
    pivot_event = p.event("user_message", text="new task:")
    reject = p.binding_op("reject", "reject", pivot["boundary_id"], [pivot_event["id"]])
    assert p.propose("update_task", [reject]).decisions[0].outcome == "apply"
    assert [b["state"] for b in p.boundaries("pivot_prefix")] == ["rejected"]
    assert len(p.tasks()) == 1 and p.task(source["task_id"])["objective"]["text"] == LIFECYCLE_PROMPT
    head = p.binding(pivot_event["id"])
    assert (head["task_id"], head["binding"], head["revision"]) == (source["task_id"], "confirmed", 2)
    again = p.binding_op("again", "confirm_split", pivot["boundary_id"], [pivot_event["id"]])
    assert [(d.outcome, d.reason_code) for d in p.propose("update_task", [again]).decisions] == [("reject", "boundary_resolved")]


def test_later_split_preserves_both_objectives(tmp_path):
    """A confirmed split creates a new task; the source keeps its objective and later events follow the new one."""
    p, pivot = pivot_project(tmp_path)
    source = task_by_objective(p, LIFECYCLE_PROMPT)
    order = p.session_events(source["task_id"], p.session_of())
    pivot_event = p.event("user_message", text="new task:")
    tail = order[order.index(pivot_event["id"]):]
    assert p.propose("update_task", [p.binding_op("split", "confirm_split", pivot["boundary_id"], tail)]).decisions[0].outcome == "apply"
    new = task_by_objective(p, "new task: write the release notes")
    assert p.task(source["task_id"])["objective"]["text"] == LIFECYCLE_PROMPT
    assert new["objective"]["evidence"][0]["ref"]["id"] == pivot_event["id"]
    p.send(record("lifecycle", "PostToolUseFailure", "toolu_probe_0002"))
    p.send_all(call("lifecycle", "toolu_probe_0001"))
    p.drain()
    later_events = [e for e in p.events() if e["seq"] > max(p.events(), key=lambda e: e["seq"])["seq"] - 3]
    assert {p.task_of(e["id"]) for e in later_events} == {new["task_id"]}  # the session continues in the split task
    assert counts(p)["nonredirected"] == 2 and counts(p)["placeholders"] == 0


def test_new_session_can_link_without_merging_tasks(tmp_path):
    """single_active_task links a new session to the one eligible task without copying its objective.

    Real lifecycle session A; synthetic variant: session B (another host
    session and tool-use IDs) whose first three path actions are A's @root
    files, its last call still pending. Then session C links the same way
    (the placeholder is no candidate), and a recorded split reverses B's link
    into a new task rather than reviving the placeholder.
    """
    p = wks.Project(tmp_path)
    start_and_prompt(p)
    root_actions(p)
    p.send_all(call("lifecycle", "toolu_probe_0008", post="PostToolUseFailure"))
    p.drain()
    target = task_by_objective(p, LIFECYCLE_PROMPT)
    b = session_id(2)
    start_and_prompt(p, session=b, prompt="Continue with the fixture notes.")
    root_actions(p, session=b, suffix="b", pending_last=True)
    p.drain()
    [link] = p.boundaries("single_active_task")
    placeholder = p.task(link["source_task_id"])
    target = p.task(target["task_id"])
    assert (link["state"], placeholder["status"], placeholder["redirect_task_id"]) == ("linked", "linked", target["task_id"])
    assert placeholder["pending_actions"] == [] and placeholder["next_action"] is None
    assert placeholder["objective"]["text"] == "Continue with the fixture notes."  # history of the placeholder, not copied
    assert target["objective"]["text"] == LIFECYCLE_PROMPT and set(target["session_ids"]) == {p.session_of(n=0), p.session_of(n=1)}
    assert "toolu_probe_0010_b" in [x["tool_call_id"] for x in target["pending_actions"]]  # the pending call moved with its session
    b_events = p.events(session=p.sid(b))
    assert {p.task_of(e["id"]) for e in b_events} == {target["task_id"]} and {p.binding(e["id"])["binding"] for e in b_events} == {"provisional"}
    assert counts(p) == {"active": 1, "paused": 0, "completed": 0, "abandoned": 0, "placeholders": 1, "nonredirected": 1}
    p.send(variant(record("lifecycle", "PostToolUse", "toolu_probe_0010"), session=b, tool_suffix="b"))
    p.drain()
    assert "toolu_probe_0010_b" not in [x["tool_call_id"] for x in p.task(target["task_id"])["pending_actions"]]
    # Session C: the linked placeholder is not a second active task, so exactly one candidate remains.
    c = session_id(3)
    start_and_prompt(p, session=c, prompt="One more pass over the notes.")
    root_actions(p, session=c, suffix="c")
    p.drain()
    assert [x["state"] for x in p.boundaries("single_active_task")] == ["linked", "linked"]
    assert counts(p)["placeholders"] == 2 and counts(p)["nonredirected"] == 1
    # The link is reversible: an explicit split of B's range creates a new task; the placeholder stays a placeholder.
    b_range = p.session_events(target["task_id"], p.sid(b))
    assert p.propose("update_task", [p.binding_op("unlink", "confirm_split", link["boundary_id"], b_range)]).decisions[0].outcome == "apply"
    split = [t for t in p.tasks() if t["status"] == "active" and t["task_id"] != target["task_id"]]
    assert len(split) == 1 and {p.task_of(e) for e in b_range} == {split[0]["task_id"]}
    assert p.task(placeholder["task_id"])["status"] == "linked" and p.task(target["task_id"])["objective"]["text"] == LIFECYCLE_PROMPT


def test_single_active_task_links_without_model_budget(tmp_path):
    """The deterministic link needs no model and no budget: today's pools are exhausted and nothing launches."""
    p = wks.Project(tmp_path)
    start_and_prompt(p)
    root_actions(p)
    p.drain()
    config = BudgetConfig()
    now = utc_now()
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        for purpose in ("review_claims", "extract_claims"):
            for i in range(config.daily_invocations + 1):
                if isinstance(budgets.reserve(txn, job_id=derived_id("job", [purpose, i]), purpose=purpose, input_estimate=100, now=now, config=config), budgets.Refusal):
                    break
        jobs.enqueue(txn, kind="update_task", input_refs=[], now=now, prompt_version="test@1")
    reserved = p.count("SELECT COUNT(*) FROM provider_usage")
    b = session_id(2)
    start_and_prompt(p, session=b, prompt="Continue with the fixture notes.")
    root_actions(p, session=b, suffix="b")
    backend = ws.FakeBackend()
    w = worker.Worker(osc.context(p.root), model=ws.runtime(backend))
    try:
        ws.drain(w)
    finally:
        w.close()
    assert [x["state"] for x in p.boundaries("single_active_task")] == ["linked"]
    assert backend.calls == [] and p.count("SELECT COUNT(*) FROM provider_usage") == reserved  # no model call, no reservation
    assert p.count("SELECT COUNT(*) FROM jobs WHERE kind = 'update_task' AND state = 'waiting_budget'") == 1


def test_ambiguous_tasks_do_not_autolink(tmp_path):
    """Two eligible tasks, a pivot or a host reset keep a new session's state separate (A57).

    Real lifecycle session; synthetic variants: a second session working in
    ``web/`` (so two tasks are active), then a third with A's @root actions.
    """
    p = wks.Project(tmp_path)
    start_and_prompt(p)
    root_actions(p)
    b = session_id(2)
    start_and_prompt(p, session=b, prompt="Build the fixture web page.")
    for call_id, path in (("toolu_probe_0007", "notes.txt"), ("toolu_probe_0009", "new.txt"), ("toolu_probe_0010", "new.txt")):
        p.send_all(call("lifecycle", call_id, session=b, tool_suffix="b", replace={f"<workspace>/{path}": f"<workspace>/web/{path}"}))
    c = session_id(3)
    start_and_prompt(p, session=c, prompt="Look at the notes again.")
    root_actions(p, session=c, suffix="c")
    p.drain()
    assert p.boundaries("single_active_task") == []
    assert counts(p)["active"] == 3 and counts(p)["placeholders"] == 0


@pytest.mark.parametrize("variant_kind", ["pivot", "host_reset"])
def test_pivot_or_reset_blocks_the_continuity_link(tmp_path, variant_kind):
    """With exactly one eligible task, an explicit pivot or a host clear still prevents the automatic link.

    ``host_reset`` replays the real ``/clear`` session start (source ``clear``); its three @root actions and the
    pivot session are synthetic variants.
    """
    p = wks.Project(tmp_path)
    start_and_prompt(p)
    root_actions(p)
    p.drain()
    if variant_kind == "pivot":
        s = session_id(4)
        start_and_prompt(p, session=s, prompt="new task: tidy the notes")
    else:
        clear = record("secret_and_resume", "SessionStart", n=1)
        assert clear["payload"]["source"] == "clear"
        s = clear["payload"]["session_id"]
        p.send(clear)
        p.send(variant(record("secret_and_resume", "UserPromptSubmit", n=1)))
    root_actions(p, session=s, suffix="x")
    p.drain()
    assert p.boundaries("single_active_task") == []
    assert counts(p)["active"] == 2
    if variant_kind == "host_reset":
        assert [b["reason"] for b in p.boundaries() if b["session_id"] != p.session_of(n=0)] == ["host_reset"]


# ---------------------------------------------------------------------------
# Path clusters


CODE_PATHS = ["src/a.py", "tests/test_a.py", "docs/a.md", "test/b.py", "src/b.py", "tests/c.py", "docs/d.md", "src/pkg/c.py"]


def test_src_tests_docs_do_not_propose_a_boundary(tmp_path):
    """Coding-profile src/tests/test/docs movement is one @code cluster; five truly disjoint actions propose (A57).

    Synthetic variants: real Read payloads with the file path changed.
    """
    p = wks.Project(tmp_path)
    start_and_prompt(p)
    p.send_all(call("lifecycle", "toolu_probe_0007", tool_suffix="first", replace={"<workspace>/notes.txt": "<workspace>/src/main.py"}))
    for i, path in enumerate(CODE_PATHS):
        p.send_all(call("lifecycle", "toolu_probe_0007", tool_suffix=f"c{i}", replace={"<workspace>/notes.txt": f"<workspace>/{path}"}))
    for i in range(5):
        p.send_all(call("lifecycle", "toolu_probe_0007", tool_suffix=f"w{i}", replace={"<workspace>/notes.txt": f"<workspace>/web/page{i}.html"}))
    pipeline.ingest_ready(p.ctx)
    with p.view() as v:
        envelopes = [EventEnvelope.model_validate({**json.loads(r[0]), "payload": json.loads(r[1])}) for r in v.execute("SELECT envelope, payload FROM events ORDER BY commit_sequence").fetchall()]
    proposed = segment.propose_task_boundaries(p.ctx, envelopes)
    assert [c.reason for c in proposed] == ["new_session", "disjoint_paths"]
    disjoint = proposed[1]
    assert disjoint.signal["clusters"] == ["web"] and disjoint.signal["observed_clusters"] == ["@code"] and len(disjoint.proposed_event_ids) == 5
    p.drain()
    recorded = p.boundaries()
    assert [b["reason"] for b in recorded] == ["new_session", "disjoint_paths"]
    assert recorded[1]["proposed_event_ids"] == disjoint.proposed_event_ids and recorded[1]["state"] == "pending"
    assert len(p.tasks()) == 1  # a candidate, not a split


def test_path_cluster_rules():
    coding = {"domain_profile": "coding", "mappings": {}}
    assert {segment.path_cluster(x, **coding) for x in ("src/a.py", "tests/x.py", "test/y.py", "docs/z.md")} == {"@code"}
    assert segment.path_cluster("README.md", **coding) == "@root" and segment.path_cluster("web/a.html", **coding) == "web"
    assert segment.path_cluster(".recalith/state/x", **coding) is None and segment.path_cluster("src/__pycache__/a.pyc", **coding) is None
    assert segment.path_cluster("../outside", **coding) is None and segment.path_cluster("/abs/path", **coding) is None
    assert segment.path_cluster("src/a.py", domain_profile="general", mappings={}) == "src"
    assert segment.path_cluster("lib/core/x.py", domain_profile="coding", mappings={"lib": "@code", "lib/core": "@core"}) == "@core"
    assert segment.pivot_prefix("  NEW TASK: x", ["new task:"]) == "new task:"
    for quoted in ("> new task: x", '"new task: x"', "```\nnew task: x\n```", "please start a new task: x"):
        assert segment.pivot_prefix(quoted, ["new task:"]) is None


def test_operator_cluster_mapping_extends_the_code_cluster(tmp_path):
    """An operator mapping (``segmentation.cluster_mappings``) joins ``lib/`` to @code: no candidate."""
    p = wks.Project(tmp_path)
    start_and_prompt(p)
    for i, path in enumerate(["src/a.py", "lib/b.py", "lib/c.py", "lib/d.py", "lib/e.py", "lib/f.py"]):
        p.send_all(call("lifecycle", "toolu_probe_0007", tool_suffix=f"m{i}", replace={"<workspace>/notes.txt": f"<workspace>/{path}"}))
    pipeline.ingest_ready(p.ctx)
    with p.view() as v:
        envelopes = [EventEnvelope.model_validate({**json.loads(r[0]), "payload": json.loads(r[1])}) for r in v.execute("SELECT envelope, payload FROM events ORDER BY commit_sequence").fetchall()]
    base = ProjectConfig.defaults_for(osc.cf.PROJECT_ID)
    mapped = base.model_copy(update={"segmentation": SegmentationConfig(cluster_mappings={"lib": "@code"})})
    assert [c.reason for c in segment.propose_task_boundaries(p.ctx, envelopes, config=base)] == ["new_session", "disjoint_paths"]
    assert [c.reason for c in segment.propose_task_boundaries(p.ctx, envelopes, config=mapped)] == ["new_session"]


# ---------------------------------------------------------------------------
# Restoration, interfaces and responsiveness


def test_restart_and_compaction_keep_blockers_and_pending_actions(tmp_path):
    """Across a manual compaction and a worker restart a task keeps its blockers and pending calls until evidence closes them.

    Real lifecycle session (with its real PreCompact/compact/PostCompact); synthetic variants: a call left
    pending before the compaction and the green rerun of test_mid after the restart.
    """
    p = wks.Project(tmp_path)
    lifecycle = osc.cf.records("lifecycle")
    stop = next(i for i, r in enumerate(lifecycle) if r["event"] == "Stop")
    p.send_all(lifecycle[:stop])
    p.send(variant(record("lifecycle", "PreToolUse", "toolu_probe_0001"), tool_suffix="pending"))
    p.send_all(lifecycle[stop:])
    p.drain()
    task = task_by_objective(p, LIFECYCLE_PROMPT)
    assert p.count("SELECT COUNT(*) FROM events WHERE kind = 'compaction'") == 3
    before = (sorted(b["text"] for b in task["blockers"]), [x["tool_call_id"] for x in task["pending_actions"]])
    assert before == (["Bash `pytest -q test_long.py` fails (exit 1)", "Bash `pytest -q test_mid.py` fails (exit 1)"], ["toolu_probe_0001_pending"])
    assert p.episodes(task["task_id"]) == []  # the checkpoints wait: an episode never severs these failures from their fix
    # Restart: a new worker over the same store continues from the persisted state.
    p.send(record("secret_and_resume", "SessionStart"))
    p.send(variant(record("lifecycle", "PreToolUse", "toolu_probe_0003"), tool_suffix="green"))
    p.send(variant(record("lifecycle", "PostToolUse", "toolu_probe_0004"), replace={"toolu_probe_0004": "toolu_probe_0003_green", "pytest -q -s test_pass.py": "pytest -q test_mid.py"}))
    p.drain()
    task = p.task(task["task_id"])
    assert [b["text"] for b in task["blockers"]] == ["Bash `pytest -q test_long.py` fails (exit 1)"]
    assert [x["tool_call_id"] for x in task["pending_actions"]] == ["toolu_probe_0001_pending"]
    p.send(variant(record("lifecycle", "PostToolUse", "toolu_probe_0001"), tool_suffix="pending"))
    p.drain()
    assert p.task(task["task_id"])["pending_actions"] == []


def test_reduce_task_and_bindings_interfaces(tmp_path):
    """``reduce_task`` returns the state typed reduction persists; ``resolve_task_binding`` goes through Task 5."""
    p = wks.Project(tmp_path)
    start_and_prompt(p)
    p.send_all(call("lifecycle", "toolu_probe_0003", post="PostToolUseFailure"))
    p.drain()
    task = task_by_objective(p, LIFECYCLE_PROMPT)
    with p.view() as v:
        evs = tasks.load_events(v, [e["id"] for e in p.events()])
    seeded = osc.seed_task(p.root, title="Interface check")
    state = reducer.reduce_task(osc.context(p.root), seeded, evs)
    assert state.revision == 2 and state.objective.text == LIFECYCLE_PROMPT
    assert [b.text for b in state.blockers] == [b["text"] for b in task["blockers"]] and state.pending_actions == []
    assert p.task(seeded)["revision"] == 1  # nothing was written
    # The public binding entry is a persisted operation with revision checks.
    p.send(variant(record("lifecycle", "UserPromptSubmit"), prompt="new task: another"))
    p.drain()
    [pivot] = p.boundaries("pivot_prefix")
    event = p.event("user_message", text="new task:")
    from recalith.contracts.memory import TaskBindingProposal

    link = {"ref": {"kind": "event", "id": event["id"], "revision": 1}, "relation": "supports", "root_event_ids": [event["id"]], "locator": None, "mapping": None}
    stale = TaskBindingProposal(boundary_id=pivot["boundary_id"], decision="reject", event_ids=[event["id"]], target_task_id=None, expected_binding_revisions={event["id"]: 7}, evidence=[link])
    with pytest.raises(RecalithError, match="revision_conflict"):
        bindings.resolve_task_binding(osc.context(p.root), stale)
    good = stale.model_copy(update={"expected_binding_revisions": {event["id"]: 1}})
    result = bindings.resolve_task_binding(osc.context(p.root), good)
    assert result.decisions[0].outcome == "apply" and p.count("SELECT COUNT(*) FROM operations WHERE kind = 'resolve_task_binding'") == 1
    assert bindings.resolve_task_binding(osc.context(p.root), good) == result  # idempotent


def test_linked_head_refuses_model_patches(tmp_path):
    """A model cannot reactivate a linked placeholder or put actions on it; controller kinds never come from a model."""
    p = wks.Project(tmp_path)
    start_and_prompt(p)
    root_actions(p)
    p.drain()
    b = session_id(2)
    start_and_prompt(p, session=b, prompt="Continue.")
    root_actions(p, session=b, suffix="b")
    p.drain()
    [link] = p.boundaries("single_active_task")
    placeholder = p.task(link["source_task_id"])
    ev = p.event("tool_finished", call="toolu_probe_0007_b")
    revive = osc.op("revive", "update_task", {"task_id": placeholder["task_id"], "expected_revision": placeholder["revision"], "patches": [{"op": "status", "status": "active"}]})
    act = osc.op("act", "update_task", {"task_id": placeholder["task_id"], "expected_revision": placeholder["revision"], "patches": [{"op": "set", "field": "next_action", "value": wks.supported(ev, "Do more.")}]})
    result = p.propose("update_task", [revive, act])
    assert {(d.outcome, d.reason_code) for d in result.decisions} == {("reject", "task_not_updatable")}
    forged = osc.response([osc.op("forge", "create_task", {"task_id": new_id("task"), "title": "x", "reason": "new_session", "session_ids": [p.session_of()], "started_at": utc_now()})], purpose="update_task")
    assert [m.reason_code for m in forged.malformed] == ["kind_not_permitted"]  # no model purpose may return it


def test_typed_reduction_runs_while_model_call_is_in_flight(tmp_path):
    """Tasks, bindings and candidates appear while a provider call is still running (zero model calls)."""
    p = wks.Project(tmp_path)
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        jobs.enqueue(txn, kind="update_task", input_refs=[], now=ws.START, prompt_version="test@1")
    gate = threading.Event()
    backend = ws.FakeBackend(gate=gate)
    w = worker.Worker(osc.context(p.root), model=ws.runtime(backend))
    runner = threading.Thread(target=w.run)
    runner.start()
    try:
        assert backend.in_flight.wait(15), "the model call never started"
        p.scenario("lifecycle")
        # Wait (bounded) for the drained state being asserted: no ready segment and every event bound.
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            bindable = len([e for e in p.events() if e["kind"] not in tasks.UNBOUND_KINDS])
            if not spool.ready_segments(spool.SpoolDirs(p.root)) and bindable and p.count("SELECT COUNT(*) FROM task_binding_heads") == bindable:
                break
            time.sleep(0.05)
        assert backend.in_flight.is_set(), "the test must observe reduction during the call"
        assert p.count("SELECT COUNT(*) FROM task_binding_heads") == bindable and len(p.tasks()) == 1
        assert task_by_objective(p, LIFECYCLE_PROMPT)["blockers"]
        assert len(backend.calls) == 1  # only the gated job: typed reduction made none
    finally:
        gate.set()
        w.stop_event.set()
        runner.join(20)
    assert not runner.is_alive()


def test_operator_undo_reverses_a_link(tmp_path):
    """A binding operation is undoable: the preview restores the bindings and both tasks' fields; history stays."""
    from recalith.controller import apply

    p = wks.Project(tmp_path)
    start_and_prompt(p)
    root_actions(p)
    p.drain()
    b = session_id(2)
    start_and_prompt(p, session=b, prompt="Continue with the fixture notes.")
    root_actions(p, session=b, suffix="b", pending_last=True)  # the link is the last change: nothing conflicts
    p.drain()
    [link] = p.boundaries("single_active_task")
    with p.view() as v:
        op_id = v.execute("SELECT operation_id FROM operations WHERE kind = 'resolve_task_binding'").fetchone()[0]
    operator = osc.operator(p.root)
    preview = apply.preview_undo(operator, op_id)
    assert preview.state == "clean" and {c.action for c in preview.compensations} == {"restore_fields"}
    undone = apply.apply_undo(operator, op_id, preview_digest=preview.preview_digest)
    placeholder = p.task(link["source_task_id"])
    assert placeholder["status"] == "active" and placeholder["redirect_task_id"] is None
    assert [x["tool_call_id"] for x in placeholder["pending_actions"]] == ["toolu_probe_0010_b"]
    assert task_by_objective(p, LIFECYCLE_PROMPT)["pending_actions"] == []  # the transferred call went back
    b_events = p.events(session=p.sid(b))
    assert {p.task_of(e["id"]) for e in b_events} == {placeholder["task_id"]}
    assert {p.binding(e["id"])["revision"] for e in b_events} == {3}  # bound, linked, restored: history kept
    assert [x["state"] for x in p.boundaries("single_active_task")] == ["pending"]
    assert apply.apply_undo(operator, op_id, preview_digest=preview.preview_digest) == undone  # idempotent: one compensation
    assert apply.preview_undo(operator, op_id).compensations == []  # the bindings moved again: nothing left to restore
    # After later typed changes to the target, a preview reports them instead of overwriting.
    p2 = wks.Project(tmp_path, "later")
    start_and_prompt(p2)
    root_actions(p2)
    p2.drain()
    start_and_prompt(p2, session=b, prompt="Continue.")
    root_actions(p2, session=b, suffix="b")
    p2.drain()
    with p2.view() as v:
        op2 = v.execute("SELECT operation_id FROM operations WHERE kind = 'resolve_task_binding'").fetchone()[0]
    partial = apply.preview_undo(osc.operator(p2.root), op2)
    assert partial.state == "partial" and {f for c in partial.conflicts for f in c.fields} >= {"pending_actions"}


def test_a_large_pass_stays_within_operation_bounds(tmp_path):
    """One pass over 150 calls (300 events, several hundred typed patches) applies as bounded operations.

    Synthetic variants: the real echo call with its tool-use ID changed.
    """
    p = wks.Project(tmp_path)
    start_and_prompt(p)
    for i in range(150):
        p.send_all(call("lifecycle", "toolu_probe_0001", tool_suffix=f"big{i}"))
    p.drain()
    task = task_by_objective(p, LIFECYCLE_PROMPT)
    assert task["pending_actions"] == [] and len(task["known_results"]) == 1  # one action signature, latest result kept
    assert p.count("SELECT COUNT(*) FROM task_binding_heads") == len(p.events())
    assert p.count("SELECT MAX(commit_sequence) FROM events") == p.count("SELECT commit_sequence FROM working_cursor")


def test_bookkeeping_bindings_do_not_advance_guidance(tmp_path):
    """Binding a lifecycle event with no typed fact is bookkeeping: store revision moves, guidance epoch does not."""
    p = wks.Project(tmp_path)
    start_and_prompt(p)
    p.drain()
    before = osc.meta(p.root)
    p.send(record("lifecycle", "Stop"))
    p.drain()
    after = osc.meta(p.root)
    assert after.store_revision > before.store_revision and after.guidance_epoch == before.guidance_epoch
    p.send_all(call("lifecycle", "toolu_probe_0001"))
    p.drain()
    assert osc.meta(p.root).guidance_epoch > after.guidance_epoch  # a typed result is serving-relevant


def test_link_is_declined_when_a_pair_spans_sessions(tmp_path):
    """A new session whose call's result was reported in another session is not linked (the pair cannot be split).

    Synthetic variants: session B is a second host session; B's Write result is reported under session A,
    so exactly one candidate exists and only the pair rule can decline the link.
    """
    p = wks.Project(tmp_path)
    start_and_prompt(p)
    root_actions(p)
    p.drain()
    b = session_id(6)
    start_and_prompt(p, session=b, prompt="Continue with the fixture notes.")
    p.send_all(call("lifecycle", "toolu_probe_0007", session=b, tool_suffix="b"))
    p.send(variant(record("lifecycle", "PreToolUse", "toolu_probe_0009"), session=b, tool_suffix="b"))
    p.send(variant(record("lifecycle", "PostToolUse", "toolu_probe_0009"), tool_suffix="b"))  # B's result, reported under session A
    p.send_all(call("lifecycle", "toolu_probe_0010", session=b, tool_suffix="b"))  # B's third path action
    p.drain()
    assert p.boundaries("single_active_task") == []
    finished = p.event("tool_finished", call="toolu_probe_0009_b")
    assert p.task_of(finished["id"]) == p.task_of(p.event("tool_started", call="toolu_probe_0009_b")["id"])
    assert p.count("SELECT COUNT(*) FROM jobs WHERE kind = 'ingest' AND state != 'completed'") == 0
    assert counts(p)["active"] == 2 and counts(p)["placeholders"] == 0
