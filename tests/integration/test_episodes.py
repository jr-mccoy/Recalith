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
