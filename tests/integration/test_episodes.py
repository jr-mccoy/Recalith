# SPDX-License-Identifier: GPL-3.0-only
"""Task 6: connected episodes across chunks and compactions (A12, A13 episode side).

Same harness as ``test_working_memory.py``: real 2.1.301 hook payloads through
the real adapter, a real worker, and synthetic variants only where no real
payload exists (named in each docstring). Each ``drain`` is a separate chunk:
the events reach the store in separate ingest transactions and reduction
passes.
"""

from __future__ import annotations

import hashlib

import pytest

import operation_scenarios as osc
import working_scenarios as wks
from working_scenarios import record, variant
from recalith.contracts.common import RecordRef
from recalith.episodes import condense
from recalith.episodes import segment as episode_segment
from recalith.storage import failpoints

PROMPT = "FIXTURE lifecycle: run the scripted tools."


@pytest.fixture(autouse=True)
def _disarm():
    failpoints.disarm_all()
    yield
    failpoints.disarm_all()


def call(tool_use_id: str, *, post: str = "PostToolUse", **kw):
    return [variant(record("lifecycle", "PreToolUse", tool_use_id), **kw), variant(record("lifecycle", post, tool_use_id), **kw)]


def green_rerun_of_test_mid() -> list[dict]:
    """Synthetic variant: the real passing pytest payload with its command set to ``pytest -q test_mid.py``."""
    return [
        variant(record("lifecycle", "PreToolUse", "toolu_probe_0003"), tool_suffix="green"),
        variant(record("lifecycle", "PostToolUse", "toolu_probe_0004"), replace={"toolu_probe_0004": "toolu_probe_0003_green", "pytest -q -s test_pass.py": "pytest -q test_mid.py"}),
    ]


def compaction() -> list[dict]:
    """The real manual-compaction sequence: PreCompact, SessionStart(compact), PostCompact."""
    return [record("lifecycle", "PreCompact"), record("lifecycle", "SessionStart", n=1), record("lifecycle", "PostCompact")]


def task_id(p: wks.Project) -> str:
    return p.task_of(p.event("user_message", text="FIXTURE lifecycle")["id"])


def test_failure_and_fix_cross_chunk_boundary(tmp_path):
    """A failure, a compaction, the change and the later result form one connected episode (A12)."""
    p = wks.Project(tmp_path)
    p.send(record("lifecycle", "SessionStart"))
    p.send(record("lifecycle", "UserPromptSubmit"))
    p.send_all(call("toolu_probe_0003", post="PostToolUseFailure"))
    p.drain()  # chunk 1: the failure
    p.send_all(compaction())
    p.drain()  # chunk 2: the compaction checkpoint must not sever the failure from its fix
    tid = task_id(p)
    assert p.episodes(tid) == []
    with p.view() as v:
        from recalith.working import bindings

        assert bindings.task_book(v, tid)["checkpoint_pending"] is True
    assert p.task(tid)["blockers"]  # restored after compaction: still open
    p.send_all(call("toolu_probe_0010"))
    p.drain()  # chunk 3: the change
    assert p.episodes(tid) == []
    p.send_all(green_rerun_of_test_mid())
    p.drain()  # chunk 4: the later result resolves the pending checkpoint
    [episode] = p.episodes(tid)
    assert episode["state"] == "settled" and episode["head_state"] == "settled"
    labels = [(s["action"]["text"], s["outcome"]) for s in episode["steps"]]
    assert labels == [("Bash `pytest -q test_mid.py`", "failure"), ("Edit new.txt", "success"), ("Bash `pytest -q test_mid.py`", "success")]
    failure, change, fixed = (p.event("tool_finished", call=c) for c in ("toolu_probe_0003", "toolu_probe_0010", "toolu_probe_0003_green"))
    compactions = [e["id"] for e in p.events("compaction")]
    assert {failure["id"], change["id"], fixed["id"], *compactions} <= set(episode["source_event_ids"])
    assert episode["coverage"]["compactions"] == 3 and episode["coverage"]["causal_assessment"] == "unassessed"
    assert all(s["causal_assessment"] is None for s in episode["steps"])  # uncertainty: no causal claim from condensation
    assert "causes not assessed" in episode["outcome"]["text"] and episode["unresolved"] == []
    assert p.task(tid)["blockers"] == []


def test_successful_results_are_preserved(tmp_path):
    """Success keeps result type, exit code, certified assertions and an exact bounded excerpt, not a bare 'ok'."""
    p = wks.Project(tmp_path)
    p.send(record("lifecycle", "SessionStart"))
    p.send(record("lifecycle", "UserPromptSubmit"))
    p.send_all(call("toolu_probe_0004"))  # the real passing pytest run (long output)
    p.send_all(call("toolu_probe_0001"))  # the real echo
    p.send(record("lifecycle", "SessionEnd"))
    p.drain()
    [episode] = p.episodes(task_id(p))
    passing, echo = episode["steps"]
    assert passing["outcome"] == "success" and "1/1 test assertions passed" in passing["result"]["text"] and "output truncated" in passing["result"]["text"]
    assert echo["result"]["text"].startswith("Bash `echo hello-fixture`: success") and "hello-fixture" in echo["result"]["text"].splitlines()[1]
    finished = p.event("tool_finished", call="toolu_probe_0004")
    quotes = [link for link in passing["result"]["evidence"] if link["locator"]]
    assert quotes, "the excerpt is quoted with its locator"
    for link in quotes:
        text = finished["payload"][link["locator"]["field"]][link["locator"]["start"] : link["locator"]["end"]]
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == link["locator"]["text_digest"]
    assert all(link["relation"] == "supports" and link["root_event_ids"] == [link["ref"]["id"]] for s in episode["steps"] for link in s["result"]["evidence"])


def test_session_end_records_an_unanswered_call(tmp_path):
    """The real denied session: at session end the unanswered call is unresolved, never a success."""
    p = wks.Project(tmp_path)
    p.scenario("denied")
    p.drain()
    [episode] = p.episodes()
    assert [s["outcome"] for s in episode["steps"]] == ["unknown"]
    assert [u["text"] for u in episode["unresolved"]] == ["Bash `touch denied.txt`: awaiting result"]
    assert episode["coverage"]["calls_awaiting_result"] == 1


def test_carried_context_is_not_new_evidence(tmp_path):
    """A later episode links its predecessor and cites earlier chunks only as context."""
    p = wks.Project(tmp_path)
    p.send(record("lifecycle", "SessionStart"))
    p.send(record("lifecycle", "UserPromptSubmit"))
    p.send_all(call("toolu_probe_0001"))
    p.send_all(compaction())
    p.drain()
    tid = task_id(p)
    [first] = p.episodes(tid)
    prompt = p.event("user_message", text="FIXTURE lifecycle")
    assert first["objective"]["evidence"][0]["relation"] == "supports" and prompt["id"] in first["source_event_ids"]
    p.send_all(call("toolu_probe_0007"))
    p.send(record("lifecycle", "SessionEnd"))
    p.drain()
    first, second = p.episodes(tid)
    assert second["related_episode_ids"] == [first["episode_id"]]
    assert prompt["id"] not in second["source_event_ids"]
    assert [link["relation"] for link in second["objective"]["evidence"]] == ["context"]  # carried, not new support
    assert not set(first["source_event_ids"]) & set(second["source_event_ids"])
    supports = {link["ref"]["id"] for s in second["steps"] for part in (s["action"], s["result"]) if part for link in part["evidence"] if link["relation"] == "supports"}
    assert supports <= set(second["source_event_ids"])


def test_build_episode_matches_the_checkpoint(tmp_path):
    """``build_episode`` returns the body the checkpoint persists, without writing."""
    p = wks.Project(tmp_path)
    p.send(record("lifecycle", "SessionStart"))
    p.send(record("lifecycle", "UserPromptSubmit"))
    p.send_all(call("toolu_probe_0001"))
    p.drain()
    tid = task_id(p)
    ids = [e["id"] for e in p.events()]
    built = condense.build_episode(osc.context(p.root), tid, ids)
    assert built.state == "settled" and [s.action.text for s in built.steps] == ["Bash `echo hello-fixture`"]
    assert p.episodes() == []
    p.send(record("lifecycle", "SessionEnd"))
    p.drain()
    [stored] = p.episodes(tid)
    assert [s.model_dump(mode="json") for s in built.steps] == stored["steps"] and built.objective.model_dump(mode="json") == stored["objective"]


def test_model_narrative_uses_the_same_write_path(tmp_path):
    """A recorded build_episode proposal revises a deterministic episode through Task 5; archiving stays code-owned."""
    p = wks.Project(tmp_path)
    p.send(record("lifecycle", "SessionStart"))
    p.send(record("lifecycle", "UserPromptSubmit"))
    p.send_all(call("toolu_probe_0003", post="PostToolUseFailure"))
    p.send_all(green_rerun_of_test_mid())
    p.send(record("lifecycle", "SessionEnd"))
    p.drain()
    [episode] = p.episodes(task_id(p))
    fixed = p.event("tool_finished", call="toolu_probe_0003_green")
    ref = RecordRef(kind="episode", id=episode["episode_id"], revision=episode["revision"])
    revise = osc.op("why", "revise_episode", {"episode_id": ref.id, "expected_revision": ref.revision, "patches": [
        {"op": "append", "field": "unresolved", "value": wks.supported(fixed, "Why did test_mid start passing? The cause is unassessed.")},
    ]})
    assert p.propose("build_episode", [revise], input_refs=[ref]).decisions[0].outcome == "apply"
    [episode] = p.episodes(task_id(p))
    assert episode["revision"] == 2 and episode["unresolved"][-1]["basis"] == "inferred"
    archive = osc.response([osc.op("arch", "revise_episode", {"episode_id": ref.id, "expected_revision": 2, "patches": [{"op": "set", "field": "state", "value": "archived"}]})], purpose="build_episode")
    assert [m.reason_code for m in archive.malformed] == ["malformed_operation"]


def test_step_cap_flushes_an_open_episode_and_carries_what_is_unresolved(tmp_path):
    """Past the step cap an unresolved range becomes an *open* episode; the next one carries its failure as context.

    Synthetic variants: 64 echo calls (tool-use IDs changed) after the real failing test.
    """
    p = wks.Project(tmp_path)
    p.send(record("lifecycle", "SessionStart"))
    p.send(record("lifecycle", "UserPromptSubmit"))
    p.send_all(call("toolu_probe_0003", post="PostToolUseFailure"))
    for i in range(episode_segment.MAX_STEPS):
        p.send_all(call("toolu_probe_0001", tool_suffix=f"n{i}"))
    p.drain()
    tid = task_id(p)
    [first] = p.episodes(tid)
    assert first["state"] == "open" and first["ended_at"] is None
    assert [u["text"] for u in first["unresolved"]] == ["Bash `pytest -q test_mid.py` still fails (exit 1)"]
    p.send_all(green_rerun_of_test_mid())
    p.send(record("lifecycle", "SessionEnd"))
    p.drain()
    first, second = p.episodes(tid)
    assert second["state"] == "settled" and second["related_episode_ids"] == [first["episode_id"]]
    assert [c["text"] for c in second["preconditions"]] == ["Bash `pytest -q test_mid.py` still fails (exit 1)"]
    assert {link["relation"] for c in second["preconditions"] for link in c["evidence"]} == {"context"}


def test_a_session_without_tool_calls_settles_at_session_end(tmp_path):
    """A conversation-only session is an episode at its end and is extracted then; before the end it stays open (decision 0036).

    Synthetic variants: the real tool-less session's records under one session ID, with the live gates' R3 declaration as the prompt.
    """
    p = wks.Project(tmp_path)
    sid = wks.session_id(3)
    p.send(variant(record("secret_and_resume", "SessionStart"), session=sid))
    p.send(variant(record("secret_and_resume", "UserPromptSubmit"), session=sid, prompt="Keep the grocery budget under $600 per month for my planning."))
    p.send(variant(record("secret_and_resume", "Stop"), session=sid))
    p.drain()
    assert p.episodes() == []  # a turn without tools is not an attempt boundary
    p.send(variant(record("secret_and_resume", "SessionEnd"), session=sid))
    p.drain()
    [episode] = p.episodes()
    assert episode["state"] == "settled" and episode["steps"] == [] and episode["outcome"]["text"].startswith("0 actions (no tool calls)")
    assert "grocery budget under $600" in episode["objective"]["text"]
    with p.view() as v:
        kinds = sorted(r[0] for r in v.execute("SELECT kind FROM jobs WHERE kind IN ('extract_claims', 'build_episode', 'update_task')").fetchall())
    assert kinds == ["extract_claims", "update_task"]  # no narrative of zero steps; the declaration is extracted



def test_a_task_that_goes_quiet_unresolved_is_an_open_episode_and_is_extracted(tmp_path):
    """Audit 2026-11-06 CAP-5: a range with an unresolved failing test never became an episode unless 64 steps
    followed, so an abandoned attempt (and any declaration in it) was never extracted. A session end still keeps
    the range open, since a resumed session may bring the fix into the same episode; the idle pause now records it
    as an open episode with its extraction scheduled.

    Synthetic variant: the real failing ``test_mid`` call; the pause is run 25 hours after the last activity.
    """
    from recalith.contracts.common import format_utc, parse_utc
    from recalith.core import identity
    from recalith.storage import db
    from recalith.working import reducer
    import datetime as _dt

    p = wks.Project(tmp_path)
    p.send(record("lifecycle", "SessionStart"))
    p.send(record("lifecycle", "UserPromptSubmit"))
    p.send_all(call("toolu_probe_0003", post="PostToolUseFailure"))
    p.send(record("lifecycle", "SessionEnd"))
    p.drain()
    tid = task_id(p)
    assert p.episodes(tid) == []  # a session end keeps it open: a resumed session may still bring the fix
    later = format_utc(parse_utc(p.task(tid)["last_activity_at"]) + _dt.timedelta(hours=25))
    with db.open_store(p.ctx) as store:
        assert reducer.pause_idle_tasks(store, p.ctx, identity.installation_config(p.root), now=later) == [tid]
    [first] = p.episodes(tid)
    assert first["state"] == "open" and [u["text"] for u in first["unresolved"]] == ["Bash `pytest -q test_mid.py` still fails (exit 1)"]
    with p.view() as v:
        extractions = [r[0] for r in v.execute("SELECT body FROM jobs WHERE kind = 'extract_claims'").fetchall()]
    assert any(first["episode_id"] in body for body in extractions)
    assert episode_segment.decide(episode_segment.RangeState(steps=2, tool_steps=2, unresolved={"sig": None}), checkpoint=True, session_end=True) is None


def test_an_excerpt_never_quotes_only_the_omission_marker():
    """Audit 2026-11-06 CAP-12: a result bounded to its tail (no kept head) quotes no excerpt; a kept head is quoted."""
    from recalith.fast import normalize
    from recalith.working import tasks

    def finished(bounded) -> tasks.Ev:
        payload = {"tool_name": "Bash", "outcome": "failure", "exit_code": 1, "result_text": bounded.stored, "text_chunks": bounded.chunks}
        from recalith.contracts.common import new_id

        return tasks.Ev(new_id("evt"), 1, "tool_finished", new_id("sess"), "claude", "tool", "observed", "2026-11-08T00:00:00Z", None, payload, {"truncated": True})

    tail_only = normalize.bound_text("x" * 50_000 + "\nFAILED test_mid", source_field="result_text", head=0)
    assert tail_only.stored.startswith("\n[recalith:")
    item = condense._result(finished(tail_only))  # noqa: SLF001
    assert "[recalith:" not in item["text"] and all(link["locator"] is None or link["locator"]["field"] != "result_text" for link in item["evidence"])
    with_head = normalize.bound_text("collected 3 items\n" + "y" * 50_000, source_field="result_text")
    item = condense._result(finished(with_head))  # noqa: SLF001
    assert "collected 3 items" in item["text"] and any((link["locator"] or {}).get("field") == "result_text" for link in item["evidence"])
