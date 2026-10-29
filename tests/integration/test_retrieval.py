"""Task 11: retrieval and bounded context composition (SYSTEM_SPEC §5.1.1, §7.3–§7.4, §8; DATA_CONTRACTS §9–§11; decision 0013).

Inputs are real Claude 2.1.301 payloads through the real adapter, ingestion,
typed reduction and the real extraction/review path with recorded proposals
(``retrieval_scenarios``); query actions are the real stored descriptors of
the captured calls. Synthetic store states (expired or redacted support,
content-free heads, a ranking corpus) are named at each use. Nothing here
measures live recall quality (B1): these are deterministic mechanics.
"""

from __future__ import annotations

import json
import math
import time

import pytest

import retrieval_scenarios as rs  # first: puts tests/, tests/integration and tests/platform on sys.path
import admission_scenarios as adm  # noqa: E402
import consolidation_scenarios as cs  # noqa: E402
import operation_scenarios as osc  # noqa: E402
import working_scenarios as wks  # noqa: E402
from recalith.contracts.common import REASON_CODES, new_id  # noqa: E402
from recalith.contracts.context import ContextPacket  # noqa: E402
from recalith.errors import RecalithError  # noqa: E402
from recalith.fast import cache, entry, wire  # noqa: E402
from recalith.fast import context as fc  # noqa: E402
from recalith.retrieval import compile as rc  # noqa: E402
from recalith.retrieval import index, search  # noqa: E402
from recalith.storage import db, records  # noqa: E402

OP = osc.op
SCOPE = {"workspace_ids": [], "task_ids": [], "branch_refs": [], "paths": [], "environment": {}}


@pytest.fixture
def p(tmp_path):
    return rs.project(tmp_path)


def _task(p) -> str:
    return p.task_of(cs.failure(p)["id"])


def _assert_shape(packet) -> None:
    data = packet.model_dump(mode="json") if isinstance(packet, ContextPacket) else packet
    ContextPacket.model_validate(data)
    assert wire.is_valid("ContextPacket", data)
    for item in data["items"]:
        assert item["why"] and item["why"][0] in REASON_CODES
    if data["items"]:
        assert data["estimated_tokens"] == fc.estimate_tokens(fc.render_packet(data["purpose"], data["items"]))


# --------------------------------------------------------------------------
# Plan-named tests


def test_scope_filter_runs_before_limit(p):
    """Status and scope mismatches are excluded before the candidate cap; they never take a slot (A24, §8.1)."""
    cs.lesson(p)
    task = _task(p)
    kept = cs.fact(p, "The fixture setup reads the database settings first.", subject="fixture setup")
    words = "fixture setup database teardown migration"
    other_task = rs.corpus(p, kept, 300, proposition=words + " other task {i}", scope=dict(SCOPE, task_ids=[new_id("task")]))  # synthetic corpus
    retired = rs.corpus(p, kept, 100, proposition=words + " retired {i}", status="archived")
    foreign = rs.corpus(p, kept, 100, proposition=words + " elsewhere {i}", scope=dict(SCOPE, workspace_ids=[new_id("ws")]))
    excluded = set(other_task) | set(retired) | set(foreign)
    q = rs.query(p, "prompt", text=words, task=task)
    top = search.retrieve(p.ctx, q, limit=3)
    assert kept in [i.ref.id for i in top] and not {i.ref.id for i in top} & excluded
    # On text alone they outrank it: without the task, the other-task claims (unknown applicability) fill the cap.
    untasked = rs.query(p, "prompt", text=words, session=new_id("sess"))
    loose = search.retrieve(p.ctx, untasked, limit=3)
    assert {i.ref.id for i in loose} <= set(other_task) and not {i.ref.id for i in loose} & (set(retired) | set(foreign))
    # The hook's views and fallback rows apply the same filters before their caps.
    rs.publish(p)
    hooked = rs.hook(p, q)
    assert hooked["source"] == "view" and not set(rs.ids(hooked["packet"])) & excluded
    assert not set(rs.ids(rs.service(p, q))) & excluded


def test_current_query_excludes_retired_claims(p):
    """Superseded, invalidated, archived, quarantined and forgotten claims never enter current guidance (§8.2, A24)."""
    fact = cs.fact(p, "The fixture database must start before test_mid.", subject="fixture database")
    retire = {s: rs.seed(p, fact, proposition=f"The fixture database ({s} copy) must start before test_mid.", proposition_key={"subject": f"fixture database {s}", "predicate": "observed"})
              for s in ("superseded", "invalidated", "archived", "quarantined", "forgotten")}
    q = rs.query(p, "session_start", text="fixture database start test_mid", task=_task(p))
    rs.publish(p)
    assert set(retire.values()) <= {i.ref.id for i in search.retrieve(p.ctx, q)}  # all live before (unbudgeted)
    cs.fact(p, "An unrelated later fact makes the views stale.", subject="unrelated")
    before = rs.hook(p, q)
    assert before["source"] == "fallback" and set(retire.values()) <= set(rs.ids(before["packet"]))  # fallback rows serve them while live
    for status, claim_id in retire.items():  # synthetic store states: Tasks 12a/16 produce some of these writes
        if status in ("quarantined", "forgotten"):
            rs.content_free(p, claim_id, status)
        else:
            rs.restate(p, claim_id, status=status)
    svc = rs.service(p, q)
    assert fact in rs.ids(svc) and not set(retire.values()) & set(rs.ids(svc))
    stale = rs.hook(p, q)  # the views predate the retirements: fallback rows are filtered against live heads
    assert stale["source"] == "fallback" and "view_stale" in stale["packet"]["degraded_reasons"] and stale["fence"]["ok"]
    assert fact in rs.ids(stale["packet"]) and not set(retire.values()) & set(rs.ids(stale["packet"]))  # filtered rows, not a rejected packet
    rs.publish(p)
    fresh = rs.hook(p, q)
    assert fresh["source"] == "view" and fact in rs.ids(fresh["packet"]) and not set(retire.values()) & set(rs.ids(fresh["packet"]))
    _assert_shape(svc)
    _assert_shape(fresh["packet"])


def _lesson_with_consequence(p) -> str:
    fail = cs.failure(p)
    body = cs.lesson_body()
    body["failure"]["consequence"] = {"text": "test_mid fails again with the fixture value missing.", "evidence": [adm.link(fail)], "basis": "inferred"}
    body["failure"]["alternative"] = {"text": "Provide the fixture value in dep.txt before rerunning.", "evidence": [adm.link(fail)], "basis": "inferred"}
    claim_id = adm.created_claim(adm.extract(p, [OP("l", "propose_claim", body, evidence=[adm.link(fail)])]))
    adm.admit(p, claim_id)
    return claim_id


def test_warning_contains_cause_and_retry_condition(p):
    """A caution carries the failure condition, consequence, alternative and a legitimate retry condition (§8.2)."""
    lesson = _lesson_with_consequence(p)
    q = rs.query(p, act=rs.mid_action(p))
    packet = rs.service(p, q)
    item = rs.by_id(packet)[lesson]
    assert item["advice"] == "caution" and item["why"][0] == "exact_action_match"
    assert "Observed: The run failed." in item["text"] and "Consequence: test_mid fails again" in item["text"] and "Alternative: Provide the fixture value" in item["text"]
    assert item["retry_text"] and "dep.txt" in item["retry_text"]  # the dependency rule, before any reviewed retry condition
    rendered = fc.render_item(item)
    assert "  retry: " in rendered and "  conditions: depends on file dep.txt" in rendered and lesson in rendered
    # A fixed failure caps the caution before any model call; a reviewed retry condition then restores it, with that condition.
    ok = cs.success(p, "fixed")
    capped = rs.by_id(rs.service(p, q))[lesson]
    assert capped["advice"] == "context" and capped["freshness"] == "needs_revalidation" and "a later run of the same action succeeded" in capped["text"]
    (job,) = cs.jobs_of(p, claim_id=lesson, states=("pending",))
    retry = {"text": "A rerun passes once the fixture provides the value.", "evidence": [cs.link(ok)], "basis": "inferred"}
    cs.run_revalidation(p, job.job_id, lambda r: [OP("rev", "revise_claim", {"claim_ref": cs.ref(p, lesson), "retry_conditions": [retry]}, target=cs.ref(p, lesson))])
    tentative = rs.by_id(rs.service(p, q))[lesson]
    assert tentative["advice"] == "context" and tentative["why"][0] == "tentative_context" and tentative["text"].startswith("Tentative (unreviewed candidate)")
    adm.admit(p, lesson)
    restored = rs.by_id(rs.service(p, q))[lesson]
    assert restored["advice"] == "caution" and restored["retry_text"] == retry["text"]
    rs.publish(p)
    hooked = rs.by_id(rs.hook(p, q)["packet"])[lesson]
    assert hooked == restored  # the hook serves the same item from its view


def test_packet_budget_is_enforced(p):
    """Exact estimates on the rendered text; start 2,000, prompt 1,000, pre-action 400, restoration 2,000, one shared 400 substitution."""
    lesson = cs.lesson(p)
    fact = cs.fact(p, "The fixture database settings live in dep.txt.", subject="fixture settings")
    rs.corpus(p, fact, 60, proposition="Fixture note {i}: the fixture database keeps its settings and teardown order in dep.txt for test_mid runs.")  # synthetic
    task = _task(p)
    rs.publish(p)
    act = rs.mid_action(p)
    for purpose, cap in fc.BUDGETS.items():
        q = rs.query(p, purpose, text="fixture database settings teardown test_mid", act=act if purpose != "session_start" else None, task=task)
        for packet in (rs.service(p, q), rs.hook(p, q)["packet"]):
            data = packet.model_dump(mode="json") if isinstance(packet, ContextPacket) else packet
            assert data["items"] and data["omitted_count"] > 0 and 0 < data["estimated_tokens"] <= cap, (purpose, data["estimated_tokens"])
            assert data["estimated_tokens"] == math.ceil(len(fc.render_packet(purpose, data["items"]).encode("utf-8")) / 3)
            assert data["pre_action_substitution_tokens"] == 0
    lower = rs.service(p, rs.query(p, "prompt", text="fixture database settings", task=task, max_tokens=400))
    assert 0 < lower.estimated_tokens <= 400 and lower.omitted_count > 0
    tiny = rs.service(p, rs.query(p, "prompt", text="fixture database settings", task=task, max_tokens=20))
    assert tiny.items == [] and tiny.estimated_tokens == 0 and tiny.omitted_count > 0  # nothing fits: nothing is truncated to fit
    # Pre-action unavailable: one shared 400 allowance for the eligible cautions, 1,400 total, the ordinary part within 1,000.
    sub = rs.service(p, rs.query(p, "prompt", text="fixture database settings teardown test_mid", act=act, task=task), substitute_pre_action=True)
    cautions = [i for i in sub.model_dump(mode="json")["items"] if i["advice"] == "caution"]
    ordinary = [i for i in sub.model_dump(mode="json")["items"] if i["advice"] != "caution"]
    assert [c["ref"]["id"] for c in cautions] == [lesson]
    assert 0 < sub.pre_action_substitution_tokens <= 400 and sub.estimated_tokens <= 1400
    assert math.ceil(len(fc.render_packet("prompt", ordinary).encode("utf-8")) / 3) <= 1000 and sub.estimated_tokens > 1000 - 400
    hooked = rs.hook(p, rs.query(p, "prompt", text="fixture database settings teardown test_mid", act=act, task=task), substitute_pre_action=True)["packet"]
    assert 0 < hooked["pre_action_substitution_tokens"] <= 400 and hooked["estimated_tokens"] <= 1400
    # No bonus without an eligible caution, none for another purpose, and a caller maximum stays binding.
    none = rs.service(p, rs.query(p, "prompt", text="fixture database settings teardown", task=task), substitute_pre_action=True)
    assert none.pre_action_substitution_tokens == 0 and none.estimated_tokens <= 1000
    restore = rs.service(p, rs.query(p, "compact_restore", text="fixture database settings teardown test_mid", act=act, task=task), substitute_pre_action=True)
    assert restore.pre_action_substitution_tokens == 0 and restore.estimated_tokens <= 2000
    capped = rs.service(p, rs.query(p, "prompt", text="fixture database settings teardown test_mid", act=act, task=task, max_tokens=500), substitute_pre_action=True)
    assert capped.estimated_tokens <= 500
    for packet in (sub, none, restore, capped, lower):
        _assert_shape(packet)


def test_views_keep_caution_candidates_ahead_of_the_cap(p):
    """A view's bounded claim list keeps action-family lessons first: never record-ID order (CI run 55 regression)."""
    template = cs.lesson(p)
    fact = cs.fact(p, "The fixture database settings live in dep.txt.", subject="fixture settings")
    rs.corpus(p, fact, 60, proposition="Fixture note {i}: the fixture database keeps its settings in dep.txt.")  # synthetic, all bound to the task
    last = rs.seed(p, template, proposition="Rerunning test_mid without the fixture value fails (sorted last).", claim_id="claim_ffffffff-ffff-4fff-bfff-ffffffffffff",
                   proposition_key={"subject": "sorted last", "predicate": "fails_without_fix"})  # synthetic: the largest possible claim ID
    rs.publish(p)
    act = rs.mid_action(p)
    for purpose in ("prompt", "pre_action", "session_start"):
        with db.open_store(p.ctx, readonly=True) as store:
            view = next(v for v in rc.views(store) if v["purpose"] == purpose and v["task_id"] == _task(p))
        assert last in [c["ref"]["id"] for c in view["body"]["candidates"]], purpose
    hooked = rs.hook(p, rs.query(p, "prompt", text="fixture database settings", act=act, task=_task(p)), substitute_pre_action=True)["packet"]
    assert rs.advice(hooked, last) == "caution" and 0 < hooked["pre_action_substitution_tokens"] <= 400


def test_receipt_does_not_invalidate_guidance_cache(p):
    """Receipt, queue and lease bookkeeping advance only the store revision: views stay valid and identical (§5.1.1, A41)."""
    lesson = cs.lesson(p)
    rs.publish(p)
    q = rs.query(p, act=rs.mid_action(p))
    first = rs.hook(p, q)
    assert first["source"] == "view" and rs.advice(first["packet"], lesson) == "caution"
    before = osc.meta(p.root)
    with db.open_store(p.ctx) as store, store.transaction() as txn:  # a delivery receipt row and a queued job: bookkeeping only
        txn.execute(
            "INSERT INTO deliveries (delivery_id, attempt_id, session_id, task_id, purpose, state, packet_digest, fence_store_revision, guidance_epoch, policy_revision, tombstone_epoch, "
            "estimated_tokens, generated_at, emitted_at, items) VALUES (?, ?, ?, NULL, 'pre_action', 'emitted', ?, ?, ?, 1, 0, ?, ?, ?, '[]')",
            (new_id("dlv"), new_id("att"), q.session_id, "0" * 64, before.store_revision, before.guidance_epoch, first["packet"]["estimated_tokens"], first["packet"]["generated_at"], first["packet"]["generated_at"]),
        )
        txn.mutated(serving_relevant=False)  # what Task 12b's receipt ingestion records: bookkeeping, not servable state
    after = osc.meta(p.root)
    assert after.store_revision > before.store_revision and after.guidance_epoch == before.guidance_epoch
    with db.open_store(p.ctx) as store:
        assert rc.projection_due(store)["views"] is False
    again = rs.hook(p, q)
    assert again["source"] == "view" and rs.ids(again["packet"]) == rs.ids(first["packet"]) and again["packet"]["guidance_epoch"] == before.guidance_epoch
    assert again["packet"]["degraded_reasons"] == []


def test_evidence_change_advances_guidance_epoch(p):
    """New support, a counter-observation and expired evidence each advance the guidance epoch and retire the cached view."""
    lesson = cs.lesson(p)
    fact = cs.fact(p, "The fixture test_mid failure reproduces on rerun.", subject="test_mid rerun")
    rs.publish(p)
    q = rs.query(p, "prompt", text="fixture test_mid failure rerun", act=rs.mid_action(p), task=_task(p))
    assert rs.hook(p, q)["source"] == "view"
    # (a) A genuinely new support class for the fact (a changed invocation): strength corroborated, epoch advances.
    e0 = rs.epoch(p)
    other = adm.call(p, cs.MID, "verbose", command="pytest -q -x test_mid.py", at_=adm.at(3))
    adm.extract(p, [OP("n", "attach_evidence", {"claim_ref": osc.head_ref(p.root, "claim", fact).model_dump(mode="json"), "relation": "supports"}, evidence=[adm.link(other, field="result_text", quote="FAILED test_mid.py::test_mid")])])
    assert adm.head(p, fact)["strength"] == "corroborated" and rs.epoch(p) > e0
    assert rs.hook(p, q)["source"] == "fallback"  # never the view built before the change
    rs.publish(p)
    # (b) A counter-observation (FailureRecheck context evidence) advances it in the ingestion transaction; the next packet drops the caution.
    e1 = rs.epoch(p)
    assert rs.advice(rs.service(p, q), lesson) == "caution"
    cs.success(p, "fixed")
    assert rs.epoch(p) > e1 and adm.head(p, lesson)["context"]
    assert rs.advice(rs.service(p, q), lesson) == "context"
    stale = rs.hook(p, q)
    assert stale["source"] == "fallback" and rs.advice(stale["packet"], lesson) != "caution"
    rs.publish(p)
    assert rs.advice(rs.hook(p, q)["packet"], lesson) == "context"
    # (c) Expired support (synthetic: Task 15 owns the write and its epoch advance): omitted from automatic packets.
    e2 = rs.epoch(p)
    for link in adm.head(p, fact)["supports"]:
        rs.set_payload_state(p, link["ref"]["id"], "expired")
    assert rs.epoch(p) > e2 and fact not in rs.ids(rs.service(p, q)) and fact not in rs.ids(rs.hook(p, q)["packet"])


# --------------------------------------------------------------------------
# The Task 10 advice gate in packets


def test_failure_recheck_and_dependency_change_remove_caution(p):
    """A FailureRecheck or a dependency change removes the caution from the next packet, before any model call."""
    a = cs.lesson(p)
    q = rs.query(p, act=rs.mid_action(p))
    assert rs.advice(rs.service(p, q), a) == "caution"
    cs.write(p, "dep")  # a certified Write of the dependency file
    item = rs.by_id(rs.service(p, q))[a]
    assert item["advice"] == "context" and item["freshness"] == "needs_revalidation" and "a dependency changed" in item["text"]
    assert any(w.startswith("dependency_") or w.startswith("freshness_") for w in item["why"][1:])


def test_uncaptured_dependency_change_is_checked_live(p):
    """A dependency changed outside any captured tool (an editor, a checkout): the bounded live check suppresses caution in both compilers."""
    a = cs.lesson(p)
    q = rs.query(p, act=rs.mid_action(p))
    rs.publish(p)
    assert rs.advice(rs.hook(p, q)["packet"], a) == "caution"
    (p.root / cs.DEP).write_bytes(b"edited outside the host\n")
    assert rs.advice(rs.service(p, q), a) == "context"
    hooked = rs.hook(p, q)
    assert hooked["source"] == "view" and rs.advice(hooked["packet"], a) == "context"
    (p.root / cs.DEP).unlink()  # a missing dependency is a changed value too
    assert rs.advice(rs.hook(p, q)["packet"], a) == "context"


def test_dependency_free_lesson_never_cautions(p):
    """Empty dependencies are unknown for the failure gate: recall as context, never a caution (§7.4)."""
    a = cs.lesson(p, deps=())
    q = rs.query(p, act=rs.mid_action(p))
    assert rs.advice(rs.service(p, q), a) == "context"
    rs.publish(p)
    assert rs.advice(rs.hook(p, q)["packet"], a) == "context"


def test_bounded_live_dependency_check(p, tmp_path):
    """At most 16 files and 1 MiB within 50 ms; excess, unreadable or escaping paths are unknown; nothing executes."""
    root = p.root
    for i in range(20):
        (root / f"d{i}.txt").write_text(f"v{i}\n", encoding="utf-8")
    budget = fc.DependencyBudget(None)
    deps = [{"kind": "file", "key": f"d{i}.txt", "fingerprint": None} for i in range(20)]
    values = fc.current_dependencies(deps, workspace_root=str(root), environment={}, budget=budget)
    assert sum(v is not None for v in values.values()) == 16 and budget.exceeded
    from recalith.controller import admission

    assert values["file:d0.txt"] == admission.current_fingerprint(p.ctx, "file:d0.txt")  # the same value the worker recorded
    assert values["file:d0.txt"] == admission.fingerprint_file(p.ctx, "d0.txt")
    big = fc.DependencyBudget(None)
    (root / "big.bin").write_bytes(b"x" * (fc.DEPENDENCY_BYTES + 1))
    assert big.file(str(root), "big.bin") is None
    for bad in ("../outside.txt", "/etc/passwd", "a\\b.txt", "", "C:x"):
        assert fc.DependencyBudget(None).file(str(root), bad) is None
    assert fc.DependencyBudget(None).file(str(root), "missing.txt") == admission.fingerprint_file(p.ctx, "missing.txt")  # the recorded absent value
    late = fc.DependencyBudget(time.monotonic() - 1)
    assert late.file(str(root), "d0.txt") is None and late.skipped


# --------------------------------------------------------------------------
# A69: every strength/freshness/evidence/status row


def _rows(p):
    """The §8.2 table's rows (synthetic store states copied from really admitted claims; see retrieval_scenarios)."""
    lesson = cs.lesson(p)
    fact = cs.fact(p, "Row fact: the fixture value comes from dep.txt.", subject="row fact")
    candidate = cs.lesson(p, "Row candidate: rerunning test_mid without its fixture fails.", subject="row candidate", admit=False)
    green = p.event("tool_finished", call="toolu_probe_0004")  # the real passing pytest result: the other side of a dispute
    contra = [{"ref": {"kind": "event", "id": green["id"], "revision": 1}, "relation": "contradicts", "root_event_ids": [green["id"]], "locator": None, "mapping": None}]
    rows = {
        "active_supported_current": (fact, "context"),
        "active_lesson_current": (lesson, "caution"),
        "active_corroborated_current": (rs.seed(p, fact, proposition="Row corroborated: the fixture value comes from dep.txt.", strength="corroborated"), "context"),
        "active_needs_revalidation": (rs.seed(p, lesson, proposition="Row stale lesson: rerunning test_mid fails until dep.txt changes.", freshness="needs_revalidation"), "context"),
        "active_unknown_freshness": (rs.seed(p, lesson, proposition="Row unknown lesson: rerunning test_mid fails until dep.txt changes.", freshness="unknown"), "context"),
        "active_capsule_only": (rs.seed(p, fact, proposition="Row capsule: the fixture value comes from dep.txt.", evidence_availability="capsule_only"), "context"),
        "candidate_bound_task": (candidate, "context"),
        "active_weak_tentative": (rs.seed(p, fact, proposition="Row weak: the fixture value comes from dep.txt.", strength="weak"), "context"),
        "expired_support": (rs.seed(p, fact, proposition="Row expired: the fixture value comes from dep.txt.", evidence_availability="expired"), None),
        "redacted_support": (rs.seed(p, fact, proposition="Row redacted: the fixture value comes from dep.txt.", evidence_availability="redacted"), None),
        "disputed": (rs.seed(p, fact, proposition="Row disputed: the fixture value comes from dep.txt.", status="disputed", contradicts=contra), "conflict"),
    }
    for status in ("superseded", "invalidated", "archived"):
        rows[status] = (rs.seed(p, fact, proposition=f"Row {status}: the fixture value comes from dep.txt.", status=status), None)
    for status in ("quarantined", "forgotten"):
        cid = rs.seed(p, fact, proposition=f"Row {status}: the fixture value comes from dep.txt.")
        rs.content_free(p, cid, status)
        rows[status] = (cid, None)
    return rows


def test_every_delivery_row_reaches_the_compiler(p):
    """A69: automatic context follows the §8.2 table in both compilers; tentative and conflict labels are preserved."""
    rows = _rows(p)
    q = rs.query(p, "manual", text="row fixture value dep.txt test_mid", act=rs.mid_action(p), task=_task(p))
    svc = rs.service(p, q)
    rs.publish(p)
    hooked = rs.hook(p, q.model_copy(update={"purpose": "session_start"}))  # the hook has no "manual" view; same 2,000 budget
    assert hooked["source"] == "view"
    for packet in (svc, hooked["packet"]):
        found = rs.by_id(packet)
        for name, (claim_id, expected) in rows.items():
            got = found.get(claim_id)
            assert (got and got["advice"]) == expected, (name, got)
        _assert_shape(packet)
    by = rs.by_id(svc)
    assert by[rows["candidate_bound_task"][0]]["why"][0] == "tentative_context" and by[rows["active_weak_tentative"][0]]["why"][0] == "tentative_context"
    assert by[rows["disputed"][0]]["why"][0] == "conflict" and "For:" in by[rows["disputed"][0]]["text"] and "Against:" in by[rows["disputed"][0]]["text"]
    assert "pending revalidation" in by[rows["active_needs_revalidation"][0]]["text"] and by[rows["active_needs_revalidation"][0]]["freshness"] == "needs_revalidation"
    assert by[rows["active_unknown_freshness"][0]]["freshness"] == "unknown"
    # Live expired evidence (payload state, not the field) is omitted too, and from the fallback rows.
    rs.set_payload_state(p, cs.failure(p)["id"], "expired")
    assert rows["active_supported_current"][0] not in rs.ids(rs.service(p, q))
    assert rows["active_supported_current"][0] not in rs.ids(rs.hook(p, q.model_copy(update={"purpose": "session_start"}))["packet"])


def test_candidates_are_tentative_only_for_the_bound_task_or_exact_action(p):
    """A weak candidate is context only for its bound task or an exact pending-action match; never repeated otherwise."""
    cand = cs.lesson(p, "Tentative: rerunning test_mid without its fixture fails.", admit=False)
    text = "tentative rerunning test_mid fixture"
    bound = rs.service(p, rs.query(p, "prompt", text=text, task=_task(p)))
    assert rs.advice(bound, cand) == "context" and rs.by_id(bound)[cand]["why"][0] == "tentative_context"
    elsewhere = rs.service(p, rs.query(p, "prompt", text=text, session=new_id("sess")))  # no binding: lexical match alone is not enough
    assert cand not in rs.ids(elsewhere)
    exact = rs.service(p, rs.query(p, "pre_action", act=rs.mid_action(p), session=new_id("sess")))
    assert rs.advice(exact, cand) == "context"


def test_intent_question_is_one_conflict_item(p):
    """Conflicting user declarations surface as one bounded conflict item; nothing is chosen for the user (A44)."""
    a = cs.declaration(p, "We use tabs for indentation in this repository.", "Indentation uses tabs.", subject="indentation")
    b = cs.declaration(p, "We use spaces for indentation in this repository.", "Indentation uses spaces.", subject="indentation")
    p.drain()  # the planner opens the question
    q = rs.query(p, "prompt", text="indentation tabs spaces", task=_task(p))
    packet = rs.service(p, q)
    conflicts = [i for i in packet.items if i.advice == "conflict"]
    assert len(conflicts) == 1 and conflicts[0].why[0] == "conflict"
    assert "Indentation uses tabs." in conflicts[0].text and "Indentation uses spaces." in conflicts[0].text and "has not chosen" in conflicts[0].text
    assert not ({a, b} - {conflicts[0].ref.id} - {r.id for r in conflicts[0].evidence_refs})
    assert len([i for i in packet.items if i.ref.id in (a, b)]) == 1  # folded, not repeated as separate context
    start = rs.service(p, rs.query(p, "session_start", task=_task(p)))
    assert [i.advice for i in start.items if i.ref.id in (a, b)] == ["conflict"]
    rs.publish(p)
    hooked = rs.hook(p, rs.query(p, "session_start", task=_task(p)))["packet"]
    assert [i["advice"] for i in hooked["items"] if i["ref"]["id"] in (a, b)] == ["conflict"]


def test_recent_observations_are_separate_context(p):
    """The bound task's latest certified results are context with their exact outcome, never a caution or a lesson."""
    q = rs.query(p, "prompt", text="anything", task=_task(p))
    packet = rs.service(p, q)
    obs = [i for i in packet.items if i.why[0] == "recent_observation"]
    assert obs and all(i.advice == "context" and i.ref.kind == "event" and i.basis == "observed" for i in obs)
    assert any("failure" in i.text and "exit 1" in i.text for i in obs) and all(i.text.startswith("Recent observation (not a durable lesson)") for i in obs)
    rs.publish(p)
    hooked = rs.hook(p, q)["packet"]
    seen = [i for i in hooked["items"] if i["why"][0] == "recent_observation"]
    assert seen and all(i["advice"] == "context" and i["ref"]["kind"] == "event" for i in seen)


# --------------------------------------------------------------------------
# A01, A18, A23, A24, A25


def test_two_installations_never_cross(tmp_path):
    """A01: identical titles and paths with opposite build commands; each query sees only its own installation."""
    a, b = rs.project(tmp_path, "proj-a"), rs.project(tmp_path, "proj-b")
    made = {}
    for proj, flag in ((a, "release"), (b, "debug")):
        made[proj.root] = {cs.fact(proj, f"Build the fixture with the {flag} flags.", subject="fixture build"), cs.lesson(proj)}
        rs.publish(proj)
    for mine, theirs, other in ((a, b, "debug"), (b, a, "release")):
        q = rs.query(mine, "prompt", text="build the fixture flags", act=rs.mid_action(mine), task=_task(mine))
        for packet in (rs.service(mine, q), rs.hook(mine, q)["packet"]):
            data = packet.model_dump(mode="json") if isinstance(packet, ContextPacket) else packet
            assert set(rs.ids(data)) & made[mine.root] and not set(rs.ids(data)) & made[theirs.root]
            assert other not in json.dumps(data) and theirs.ctx.installation_id not in json.dumps(data)
        foreign = rs.query(mine, "prompt", text="build", workspace=theirs.ctx.workspace_id)
        with pytest.raises(RecalithError, match="foreign_installation"):
            rs.service(mine, foreign)
        assert rs.hook(mine, foreign)["packet"]["degraded_reasons"] == ["foreign_installation"]


def test_branch_and_version_scoped_claims_coexist(p):
    """A18: the same proposition key under different branches or versions stays active in its own scope; no false conflict."""
    fact = cs.fact(p, "The fixture server listens on port 8080.", subject="fixture server port")
    cond = lambda kind, key, value, upper=None: {"kind": kind, "key": key, "value": value, "upper": upper, "exclude": False}  # noqa: E731
    main = rs.restate(p, fact, conditions=[cond("branch_ref", "", "main")]) and fact
    feature = rs.seed(p, fact, proposition="The fixture server listens on port 9090.", conditions=[cond("branch_ref", "", "feature/x")])
    old = rs.seed(p, fact, proposition="The fixture server needs the legacy flag.", conditions=[cond("version_range", "python_version", "3.8", "3.11")])
    new = rs.seed(p, fact, proposition="The fixture server needs the async flag.", conditions=[cond("version_range", "python_version", "3.12")])
    text = "fixture server port listens flag"
    on_main = rs.service(p, rs.query(p, "prompt", text=text, branch="main", environment={"python_version": "3.12.4"}, task=_task(p)))
    assert main in rs.ids(on_main) and feature not in rs.ids(on_main) and new in rs.ids(on_main) and old not in rs.ids(on_main)
    on_feature = rs.service(p, rs.query(p, "prompt", text=text, branch="feature/x", environment={"python_version": "3.9.1"}, task=_task(p)))
    assert feature in rs.ids(on_feature) and main not in rs.ids(on_feature) and old in rs.ids(on_feature) and new not in rs.ids(on_feature)
    unknown = rs.service(p, rs.query(p, "prompt", text=text, task=_task(p)))
    assert {main, feature} <= set(rs.ids(unknown)) and all(i.advice == "context" for i in unknown.items if i.ref.kind == "claim")
    assert not [i for i in unknown.items if i.advice == "conflict"]


def test_unknown_applicability_is_context_never_caution(p):
    """A23: a high-overlap lesson whose condition is unknown under the query may be context, never caution."""
    cond = {"kind": "version_range", "key": "python_version", "value": "3.12", "upper": None, "exclude": False}
    a = cs.lesson(p, conditions=[cond])
    act = rs.mid_action(p)
    assert rs.advice(rs.service(p, rs.query(p, act=act)), a) == "context"  # python_version unknown in this store
    assert rs.advice(rs.service(p, rs.query(p, act=act, environment={"python_version": "3.12.4"})), a) == "caution"
    assert a not in rs.ids(rs.service(p, rs.query(p, act=act, environment={"python_version": "3.11.2"})))  # false: excluded
    # The hook never parses PEP 440: without a precomputed result for the exact consulted value it stays unknown.
    rs.publish(p)
    assert rs.advice(rs.hook(p, rs.query(p, act=act, environment={"python_version": "3.12.4"}))["packet"], a) == "context"
    # A declared runtime (operator configuration) lets the worker precompute the result for exactly that value.
    from recalith.capture import provenance

    with db.open_store(p.ctx) as store:
        provenance.record_declared_runtime(store, osc.operator(p.root), key="python_version", value="3.12.4", config_revision=1)
    rs.publish(p)
    assert rs.advice(rs.service(p, rs.query(p, act=act)), a) == "caution"
    assert rs.advice(rs.hook(p, rs.query(p, act=act))["packet"], a) == "caution"  # the view's environment and its precomputed result
    other = rs.hook(p, rs.query(p, act=act, environment={"python_version": "3.11.2"}))["packet"]
    assert rs.advice(other, a) == "context"  # another consulted value: unknown in the hook, never the reused result


def test_linked_placeholder_redirects_and_supplies_nothing_actionable(tmp_path):
    """A24: a linked placeholder serves its nonlinked target; its own head never supplies pending actions or a next action."""
    import test_working_memory as twm

    p = wks.Project(tmp_path)
    twm.start_and_prompt(p)
    twm.root_actions(p)
    p.drain()
    target = twm.task_by_objective(p, twm.LIFECYCLE_PROMPT)
    b = wks.session_id(2)
    twm.start_and_prompt(p, session=b, prompt="Continue with the fixture notes.")
    twm.root_actions(p, session=b, suffix="b", pending_last=True)
    p.drain()
    [link] = p.boundaries("single_active_task")
    placeholder = link["source_task_id"]
    q = rs.query(p, "session_start", task=placeholder, session=p.sid(b))
    for packet in (rs.service(p, q), (rs.publish(p), rs.hook(p, q))[1]["packet"]):
        tasks = [i for i in rs.by_id(packet).values() if i["ref"]["kind"] == "task"]
        assert [t["ref"]["id"] for t in tasks] == [target["task_id"]] and placeholder not in rs.ids(packet)
        assert twm.LIFECYCLE_PROMPT in tasks[0]["text"] and "Continue with the fixture notes." not in tasks[0]["text"]


def test_correction_before_the_fence_excludes_old_guidance(p, monkeypatch):
    """A25: a change committed before the final fence excludes the old guidance (recompile or degraded, never old text)."""
    a = cs.lesson(p)
    q = rs.query(p, act=rs.mid_action(p))
    rs.publish(p)
    real = search.gather
    calls = []

    def racing(view, ctx, query, **kw):  # a correction lands between gathering and the fence
        out = real(view, ctx, query, **kw)
        if not calls:
            calls.append(1)
            rs.restate(p, a, status="invalidated")
        return out

    monkeypatch.setattr(search, "gather", racing)
    packet = rs.service(p, q)
    assert a not in rs.ids(packet) and "fence_recompiled" in packet.degraded_reasons
    other = cs.fact(p, "A claim that keeps changing during compilation.", subject="churn")

    def churning(view, ctx, query, **kw):  # a change lands after every gathering: the second fence fails too
        out = real(view, ctx, query, **kw)
        rs.restate(p, other, status="archived")
        return out

    monkeypatch.setattr(search, "gather", churning)
    churned = rs.service(p, q)
    assert churned.degraded_reasons == ["fence_epoch_changed"] and churned.items == []
    monkeypatch.undo()
    # The hook: a view compiled before the change fails the fresh fence; the stale view is never served.
    b = cs.lesson(p, "Rerunning test_mid without the fixture value fails again.", subject="mid again")
    rs.publish(p)
    ctx = entry.load_context(str(p.root), "claude_code")
    from recalith.fast import fence

    real_fence = fence.check

    def racing_fence(root, packet, *, deadline):
        rs.restate(p, b, status="invalidated")
        return real_fence(root, packet, deadline=deadline)

    monkeypatch.setattr(fence, "check", racing_fence)
    result = cache.compile_packet(ctx, q.model_dump(mode="json"), deadline=time.monotonic() + 2)
    assert result["packet"]["items"] == [] and result["fence"]["reason"] == "fence_epoch_changed" and result["fence"]["fenced_at"]
    monkeypatch.undo()
    # After the fence, a later change cannot retract what was already compiled: recorded as an in-flight race.
    ok = rs.hook(p, q)
    assert ok["fence"]["ok"] and b not in rs.ids(ok["packet"])


# --------------------------------------------------------------------------
# Stale projections, snapshots and the deadline


def test_stale_projection_falls_back_or_degrades(p):
    """A stale view is never served as current: bounded fallback with time left, else degraded and empty."""
    a = cs.lesson(p)
    q = rs.query(p, act=rs.mid_action(p))
    rs.publish(p)
    cs.fact(p, "A later fact changes the guidance epoch.", subject="later")
    fallback = rs.hook(p, q)
    assert fallback["source"] == "fallback" and "view_stale" in fallback["packet"]["degraded_reasons"] and rs.advice(fallback["packet"], a) == "caution"
    short = rs.hook(p, q, seconds=fc.FALLBACK_MIN_REMAINING - 0.01)
    assert short["packet"]["items"] == [] and "deadline_fallback_skipped" in short["packet"]["degraded_reasons"]
    none = rs.hook(p, q, seconds=fc.FENCE_TAIL / 2)
    assert none["packet"]["items"] == [] and none["packet"]["degraded_reasons"] == ["deadline_delivery_skipped"]
    task_view = rs.hook(p, rs.query(p, act=rs.mid_action(p), task=new_id("task")))
    assert task_view["packet"]["items"] == [] or task_view["source"] == "fallback"


def test_store_snapshot_unavailable_degrades(p, tmp_path):
    """No store, or one the hook cannot open read-only at once: empty and degraded, never a repair or a wait."""
    q = rs.query(p, act=rs.mid_action(p))
    ctx = dict(entry.load_context(str(p.root), "claude_code"))
    missing = dict(ctx, root=str(tmp_path / "nowhere"))
    result = cache.compile_packet(missing, q.model_dump(mode="json"), deadline=time.monotonic() + 1)
    assert result["packet"]["items"] == [] and result["packet"]["degraded_reasons"] == ["store_snapshot_unavailable"]
    # A live writer holding a write transaction: WAL readers neither wait nor fail.
    rs.publish(p)
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        txn.execute("UPDATE projection_state SET updated_at = updated_at")
        start = time.monotonic()
        held = cache.compile_packet(ctx, q.model_dump(mode="json"), deadline=time.monotonic() + 1)
        assert time.monotonic() - start < 0.5 and held["source"] == "view"


def test_hook_reads_are_read_only(p):
    """The hook connection is mode=ro, query_only, busy_timeout 0, and an authorizer denies every write."""
    conn = cache.open_snapshot(str(p.root))
    try:
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1 and conn.execute("PRAGMA busy_timeout").fetchone()[0] == 0
        for sql in ("INSERT INTO planner_state (singleton) VALUES (2)", "DELETE FROM context_views", "CREATE TABLE x (a)", "PRAGMA wal_checkpoint"):
            with pytest.raises(cache.sqlite3.DatabaseError):
                conn.execute(sql)
    finally:
        cache.close(conn)


# --------------------------------------------------------------------------
# Index, ranking and agreement


def test_fts5_and_token_index_agree(p):
    """FTS5 capability detection with a deterministic token-index fallback: the same candidates and packets."""
    cs.lesson(p)
    fact = cs.fact(p, "The fixture database keeps teardown order in dep.txt.", subject="teardown")
    rs.corpus(p, fact, 40, proposition="Note {i}: résumé of the fixture database naïve teardown ordering.")
    q = rs.query(p, "prompt", text="fixture database résumé teardown", task=_task(p))
    packets = {}
    for prefer in (True, False):
        if prefer and not index.fts5_available():
            continue
        with db.open_store(p.ctx) as store:
            index.refresh(store, p.ctx, prefer_fts=prefer)
            with store.read() as v:
                assert index.state(v)["backend"] == ("fts5" if prefer else "tokens")
                words = fc.terms(q.text)
                packets[prefer] = (sorted(index.lexical_ids(v, words, "fts5" if prefer else "tokens")), rs.ids(rs.service(p, q)))
    if len(packets) == 2:
        assert packets[True] == packets[False]
    assert len(packets[False][0]) >= 41


def test_index_lag_is_covered_directly(p):
    """Records changed after the index refresh are covered from the live heads (no stale index entry is trusted)."""
    rs.publish(p)
    new = cs.fact(p, "Freshly admitted: the fixture cache lives in tmp.", subject="cache")
    old = cs.fact(p, "Soon archived: the fixture cache lives in var.", subject="cache old")
    rs.publish(p)
    rs.restate(p, old, status="archived")
    late = cs.fact(p, "Admitted after the refresh: the fixture cache moved.", subject="cache moved")
    q = rs.query(p, "prompt", text="fixture cache lives moved", session=new_id("sess"))  # no task: lexical candidates only
    with p.view() as v:
        assert index.state(v)["indexed"] < osc.meta(p.root).store_revision  # the index really lags
    got = rs.ids(rs.service(p, q))
    assert new in got and late in got and old not in got


def test_relevance_controls(p):
    """Quiet prompts stay quiet; the relevant claim ranks first; an out-of-scope distractor never appears."""
    target = cs.fact(p, "The fixture teardown must close the sqlite connection.", subject="teardown sqlite")
    rs.corpus(p, target, 30, proposition="Unrelated note {i}: deployment uses the staging bucket.")
    distractor = rs.seed(p, target, proposition="The fixture teardown must close the sqlite connection in the other workspace.", scope=dict(SCOPE, workspace_ids=[new_id("ws")]))
    quiet = rs.service(p, rs.query(p, "prompt", text="thanks, that is all for now", session=new_id("sess")))
    assert quiet.items == []
    relevant = rs.service(p, rs.query(p, "prompt", text="how should teardown close sqlite?", session=new_id("sess")))
    assert rs.ids(relevant)[0] == target and distractor not in rs.ids(relevant)
    assert not any("staging bucket" in i.text for i in relevant.items)


def test_ten_thousand_claim_corpus(p):
    """10,000 claim heads: scope and status filters before caps, deterministic ranking, bounded query time."""
    target = cs.fact(p, "The fixture teardown must close the sqlite connection.", subject="teardown sqlite")
    other = new_id("task")
    rs.corpus(p, target, 6000, proposition="Corpus {i}: deployment notes for the staging bucket and cache warmup.")
    rs.corpus(p, target, 2000, proposition="Corpus out of scope {i}: fixture teardown sqlite connection close.", scope=dict(SCOPE, task_ids=[other]))
    rs.corpus(p, target, 2000, proposition="Corpus retired {i}: fixture teardown sqlite connection close.", status="archived")
    with p.view() as v:
        assert v.execute("SELECT COUNT(*) FROM claim_heads").fetchone()[0] >= 10_000
    started = time.perf_counter()
    rs.publish(p)
    publish_seconds = time.perf_counter() - started
    q = rs.query(p, "prompt", text="teardown sqlite connection close", task=_task(p))
    first = rs.service(p, q)
    assert rs.ids(first)[0] == target and len(rs.ids(first)) == len(set(rs.ids(first)))
    assert all("Corpus out of scope" not in i.text and "Corpus retired" not in i.text for i in first.items)
    timings = rs.fixed_seconds(rs.service, p, q, repeat=5)
    assert rs.ids(rs.service(p, q)) == rs.ids(first)  # deterministic
    hook_times = rs.fixed_seconds(rs.hook, p, q, repeat=5)
    hooked = rs.hook(p, q)
    assert hooked["source"] == "view" and not any("Corpus out of scope" in i["text"] or "Corpus retired" in i["text"] for i in hooked["packet"]["items"])
    print(f"10k corpus: publish {publish_seconds:.2f}s; service p50 {sorted(timings)[2] * 1000:.0f} ms; hook compile (in process) p50 {sorted(hook_times)[2] * 1000:.0f} ms")
    assert max(timings) < 5.0 and max(hook_times) < 2.0  # generous CI bounds; measured values are recorded in docs/measurements


def test_hook_and_service_decisions_agree(p):
    """The stdlib twins (conditions, advice gate, relevance) agree with core.conditions and revalidate.guidance on every candidate."""
    _rows(p)
    cond = {"kind": "version_range", "key": "python_version", "value": "3.12", "upper": "3.13", "exclude": True}
    cs.lesson(p, "Version lesson: rerunning test_mid fails on new runtimes.", subject="versioned", conditions=[cond])
    task = _task(p)
    act = rs.mid_action(p)
    queries = [
        rs.query(p, purpose, text=text, act=a, task=t, environment=env, branch=br)
        for purpose in ("pre_action", "prompt", "session_start", "compact_restore", "manual")
        for text in ("", "row fixture value dep.txt test_mid")
        for a in (act, None)
        for t in (task, None)
        for env in ({}, {"python_version": "3.12.4", "os": "linux"})
        for br in (None, "main")
    ]
    with db.open_store(p.ctx, readonly=True) as store, store.read() as v:
        heads = [r[0] for r in v.execute("SELECT claim_id FROM claim_heads WHERE status IN ('candidate', 'active', 'disputed')").fetchall()]
        compared = 0
        for q in queries:
            eq = q.model_copy(update={"environment": q.environment})
            qd = eq.model_dump(mode="json")
            family = fc.action_family(eq.workspace_id, qd["action"])
            terms = set(fc.terms(eq.text))
            for claim_id in heads:
                claim = records.load(v, "claim", claim_id, records.head(v, "claim", claim_id)[0])
                cand = search.claim_candidate(v, p.ctx, claim, environment=eq.environment)
                strict = search.decide(v, p.ctx, cand, eq, family=family, query_terms=terms, budget=fc.DependencyBudget(None), claim=claim)
                twin = fc.decide(cand, qd, eq.environment, family=family, query_terms=terms, workspace_root=str(p.ctx.workspace_root), budget=fc.DependencyBudget(None),
                                 claim_values={k: x["value"] for k, x in (cand.get("claim_values") or {}).items()})
                assert (strict and strict["item"]) == (twin and twin["item"]), (claim.proposition, qd)
                compared += 1
    assert compared > 1000


def test_worker_publishes_projection_and_is_idempotent(p):
    """The worker's poll keeps the index at the store revision and the views at the epochs; a second poll does nothing."""
    cs.lesson(p)
    p.drain()
    with db.open_store(p.ctx) as store:
        assert rc.projection_due(store) == {"index": False, "views": False, "lookup": False}
        assert rc.refresh_projection(store, p.ctx) == {}
    assert rs.view_count(p) > 0
    before = osc.meta(p.root)
    p.drain()
    after = osc.meta(p.root)
    assert after.guidance_epoch == before.guidance_epoch  # publishing never advances the guidance epoch


def test_older_development_store_is_refused(tmp_path):
    """Schema 7 refuses a schema-6 development store; it is never migrated silently (decisions 0007–0013)."""
    p = rs.project(tmp_path)
    path = p.root / ".recalith" / db.STATE_DB
    raw = db.sqlite3.connect(path)
    raw.execute("UPDATE installation_meta SET schema_version = 6")
    raw.execute("PRAGMA user_version = 6")
    raw.commit()
    raw.close()
    with pytest.raises(RecalithError) as refused:
        db.open_store(p.ctx)
    assert refused.value.code == "invalid_schema" and "explicit migration" in str(refused.value)


def test_uncaptured_dependency_change_labels_every_claim_kind(p):
    """A claim of any kind whose registered file dependency changed outside any captured tool is never shown as current.

    The bounded live dependency check (§7.4) runs for every live claim with
    registered dependencies, not only failure lessons: a changed value labels
    the item ``needs_revalidation`` (§8.2 table row 2) with ``dependency_false``
    in both compilers; restoring the bytes makes it current again. Found by the
    Task 18 smoke run (R4: a stored storage fact stayed "current" after the
    code it describes changed).
    """
    body = adm.claim("The fixture dependency file holds version one.", subject="dependency file version")
    body["dependencies"] = [{"kind": "file", "key": cs.DEP, "fingerprint": None, "record": None}]
    claim_id = adm.created_claim(adm.extract(p, [osc.op("f", "propose_claim", body, evidence=[adm.link(cs.failure(p))])]))
    adm.admit(p, claim_id)
    q = rs.query(p, "prompt", text="Which version does the fixture dependency file hold?")
    rs.publish(p)

    def items():
        return [rs.by_id(rs.service(p, q))[claim_id], rs.by_id(rs.hook(p, q)["packet"])[claim_id]]

    assert [i["freshness"] for i in items()] == ["current", "current"]
    (p.root / cs.DEP).write_bytes(b"fixture v2, edited outside the host\n")
    for item in items():
        assert item["advice"] == "context" and item["freshness"] == "needs_revalidation" and "dependency_false" in item["why"], item
    (p.root / cs.DEP).write_bytes(b"fixture v1\n")
    assert [i["freshness"] for i in items()] == ["current", "current"]


def test_a_fact_read_from_its_scoped_file_is_labeled_when_the_file_changes(p):
    """The live R4 rerun (2026-10-29) end to end: no declared dependency, yet the changed file labels the fact.

    The extractor cited its Read of ``fieldnotes/store.py``, scoped the fact
    to that file and declared no dependency, so the next session's prompt got
    the stale fact as ``current``. Code now records the dependency (decision
    0030) and the bounded live check labels the item in both compilers.
    """
    (p.root / cs.NOTES).write_bytes(b"fixture notes\n")
    body = adm.claim("The notes file holds the fixture notes.", subject="notes file contents", scope=cs.scope(cs.NOTES), dependencies=[])
    claim_id = adm.created_claim(adm.extract(p, [osc.op("f", "propose_claim", body, evidence=[adm.link(cs.read(p))])]))
    adm.admit(p, claim_id)
    q = rs.query(p, "prompt", text="What does the notes file hold?")
    rs.publish(p)

    def items():
        return [rs.by_id(rs.service(p, q))[claim_id], rs.by_id(rs.hook(p, q)["packet"])[claim_id]]

    assert [i["freshness"] for i in items()] == ["current", "current"]
    (p.root / cs.NOTES).write_bytes(b"other notes, rewritten outside the host\n")
    for item in items():
        assert item["advice"] == "context" and item["freshness"] == "needs_revalidation" and "dependency_false" in item["why"], item
