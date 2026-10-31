"""Task 4: queue, budgets, leases and the project worker (A21, A30, A31, A45, A50).

Scheduling tests drive real worker polls and model-lane steps against real
stores with a deterministic clock. Provider execution is a fake backend
(Task 7 owns the real one): the in-process :class:`FakeBackend`, or a real
child process through the bounded launcher (``fake_backend.py``). Crash tests
kill a real child process at the worker failpoints and compare the reopened
store with a reference run (ACCEPTANCE_TESTS §4). Repetitions default to 3 per
failpoint (RECALITH_CRASH_REPS=20 nightly).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

import operation_scenarios as osc
import worker_scenarios as ws
from recalith.capture import pipeline
from recalith.contracts.common import RecordRef, digest_of, parse_utc, utc_now
from recalith.contracts.config import MODEL_INPUT_CAP, REASONING_HEADROOM, BudgetConfig, ProjectConfig, body_cap_for, provider_output_cap
from recalith.contracts.jobs import MODEL_JOB_KINDS, BudgetReservation
from recalith.controller import apply, budgets, jobs, worker
from recalith.errors import RecalithError
from recalith.storage import db, failpoints, spool

HERE = Path(__file__).resolve().parent
REPS = int(os.environ.get("RECALITH_CRASH_REPS", "3"))
MODEL = tuple(sorted(MODEL_JOB_KINDS))


@pytest.fixture(autouse=True)
def _disarm():
    failpoints.disarm_all()
    yield
    failpoints.disarm_all()


@pytest.fixture
def root(tmp_path):
    return ws.init_project(tmp_path, "proj")


def config_with(**budget) -> ProjectConfig:
    return ProjectConfig.defaults_for(ws.PROJECT_ID).model_copy(update={"budgets": BudgetConfig(**budget)})


def make_worker(root, backend=None, *, clock=None, config=None, prepare=None, owner=None) -> worker.Worker:
    return worker.Worker(ws.context(root), clock=clock or ws.FakeClock(), config=config, model=ws.runtime(backend, prepare) if backend is not None else None, owner=owner)


def job_row(root, job_id):
    with db.open_store(ws.context(root), readonly=True) as store, store.read() as view:
        return jobs.get_job(view, job_id)


def reservations(root) -> list[BudgetReservation]:
    with db.open_store(ws.context(root), readonly=True) as store, store.read() as view:
        rows = view.execute("SELECT body FROM provider_usage ORDER BY rowid").fetchall()
    return [BudgetReservation.model_validate_json(r[0]) for r in rows]


def seed_reservations(root, purpose: str, count: int, *, input_estimate: int = 100, now: str = ws.START, config: BudgetConfig | None = None) -> list:
    """Reserve ``count`` invocations directly in the ledger (the arithmetic under test)."""
    config = config or BudgetConfig()
    out = []
    with db.open_store(ws.context(root)) as store, store.transaction() as txn:
        for i in range(count):
            out.append(budgets.reserve(txn, job_id=f"job_{digest_of([purpose, i, now])}", purpose=purpose, input_estimate=input_estimate, now=now, config=config))
    return out


def seed_charged(root, purpose: str, count: int, *, input_estimate: int = 100, output_tokens: int = 100, now: str = ws.START, config: BudgetConfig | None = None) -> list:
    """Reserve and settle ``count`` invocations at a known small output, as finished calls are (the headroom is released)."""
    from recalith.contracts.jobs import LocalUsage
    from recalith.contracts.operations import UsageReport

    config = config or BudgetConfig()
    out = []
    with db.open_store(ws.context(root)) as store, store.transaction() as txn:
        for i in range(count):
            res = budgets.reserve(txn, job_id=f"job_{digest_of([purpose, 'charged', i, now])}", purpose=purpose, input_estimate=input_estimate, now=now, config=config)
            if isinstance(res, BudgetReservation):
                usage = UsageReport(input_tokens=input_estimate, output_tokens=output_tokens, estimated_input_tokens=input_estimate, estimated_output_tokens=output_tokens, provider_request_id=None, duration_ms=5)
                res = budgets.charge(txn, res.reservation_id, reported=usage, local=LocalUsage(input_estimate=input_estimate, output_estimate=output_tokens))
            out.append(res)
    return out


def outcome(body: bytes = ws.NO_OP_BODY, **kw) -> worker.LaunchOutcome:
    return worker.LaunchOutcome(stdout=ws.envelope(body, usage=kw.pop("usage", {"input_tokens": 50, "output_tokens": 10}), padding=kw.pop("padding", 0)), **kw)


# ---------------------------------------------------------------------------
# Leases and fencing (A21)


def test_expired_lease_is_fenced(root):
    """An expired lease is superseded; the old owner's result never applies; the newer one applies once."""
    job_id = ws.enqueue_model_job(root, "extract_claims")
    ctx = ws.context(root)
    response, read_set = _response(), ws.read_set(ctx)
    with db.open_store(ctx) as store:
        a = jobs.lease_next(ctx, owner="worker-a", now=ws.START, kinds=MODEL, store=store)
        assert a is not None and a.job_id == job_id and a.lease_generation == 1
        assert jobs.lease_next(ctx, owner="worker-b", now=ws.START, kinds=MODEL, store=store) is None  # still leased
        later = jobs._plus(a.lease_until, 1)
        b = jobs.lease_next(ctx, owner="worker-b", now=later, kinds=MODEL, store=store)
        assert b is not None and b.job_id == job_id and b.lease_generation == 2
        for when in (ws.START, later):  # superseded generation: fenced whatever the old owner's clock says
            with pytest.raises(RecalithError, match="lease fenced"):
                apply.persist_proposal(store, a, response, read_set, now=when)
            with pytest.raises(RecalithError, match="lease fenced"):
                apply.apply_proposal(ctx, a, response, store=store, now=when)
        apply.persist_proposal(store, b, response, read_set, now=later)
        first = apply.apply_proposal(ctx, b, response, store=store, now=later)
        with pytest.raises(RecalithError, match="lease fenced"):  # a completed job takes no second, different result
            apply.apply_proposal(ctx, b, _response("something else"), store=store, now=later)
        assert apply.apply_proposal(ctx, b, response, store=store, now=later) == first  # a duplicate returns the original
        assert apply.apply_proposal(ctx, a, response, store=store, now=later) == first  # whoever asks, once committed
    state = ws.state(root)
    assert state["effects"] == {job_id: 1} and job_row(root, job_id).state == "completed"


def test_same_owner_release_is_fenced_by_generation(root):
    """The generation alone fences: the same owner re-leasing after expiry cannot apply its older attempt."""
    job_id = ws.enqueue_model_job(root, "update_task")
    ctx = ws.context(root)
    with db.open_store(ctx) as store:
        first = jobs.lease_next(ctx, owner="worker-a", now=ws.START, kinds=MODEL, store=store)
        later = jobs._plus(first.lease_until, 1)
        second = jobs.lease_next(ctx, owner="worker-a", now=later, kinds=MODEL, store=store)
        assert (second.lease_owner, second.lease_generation) == (first.lease_owner, first.lease_generation + 1)
        with pytest.raises(RecalithError, match="lease fenced"):
            apply.persist_proposal(store, first, _response(), ws.read_set(ctx), now=later)
        apply.persist_proposal(store, second, _response(), ws.read_set(ctx), now=later)
        with pytest.raises(RecalithError, match="lease fenced"):
            apply.apply_proposal(ctx, first, _response(), store=store, now=later)
        apply.apply_proposal(ctx, second, _response(), store=store, now=later)
    assert ws.state(root)["effects"] == {job_id: 1}


def _response(reason: str = "nothing new"):
    from recalith.contracts.operations import ModelProposalBody, ModelResponse, UsageReport

    usage = UsageReport(input_tokens=1, output_tokens=1, estimated_input_tokens=1, estimated_output_tokens=1, provider_request_id=None, duration_ms=1)
    return ModelResponse.from_body(ModelProposalBody.model_validate({"operations": [], "no_op_reason": reason}), usage, None)


def test_late_model_result_after_takeover_is_discarded(root):
    """A worker's call outlives its lease; a newer lease completes the job; the late result applies nothing."""
    job_id = ws.enqueue_model_job(root, "extract_claims")
    clock = ws.FakeClock()
    newer = make_worker(root, ws.FakeBackend(), clock=clock, owner="newer")

    def takeover(request, purpose):
        clock.advance(jobs.lease_seconds("extract_claims", BudgetConfig()) + 5)
        assert newer.lane.step()  # the expired lease is taken over and completed

    late_backend = ws.FakeBackend(on_launch=takeover)
    old = make_worker(root, late_backend, clock=clock, owner="older")
    assert old.lane.step()
    assert old.counters["fenced_results"] == 1
    state = ws.state(root)
    assert state["effects"] == {job_id: 1} and state["proposals"] == {job_id: 1}
    assert [s for _, s in state["usage"]] == ["charged", "charged"]  # both calls spent budget
    assert job_row(root, job_id).state == "completed"


# ---------------------------------------------------------------------------
# Reservations before launch; budget pools (A31, A50)


def test_budget_reservation_precedes_launch(root):
    """At launch the reservation is already committed; without capacity nothing launches."""
    seen = []
    ctx = ws.context(root)

    def check(request, purpose):
        job_id = json.loads(request)["job_id"]
        with db.open_store(ctx, readonly=True) as other, other.read() as view:  # an independent connection
            seen.append(view.execute("SELECT state FROM provider_usage WHERE job_id = ?", (job_id,)).fetchall())

    config = config_with(daily_invocations=31)  # protected 30 + ordinary 1
    first = ws.enqueue_model_job(root, "extract_claims", key="one")
    second = ws.enqueue_model_job(root, "extract_claims", key="two")
    backend = ws.FakeBackend(on_launch=check)
    w = make_worker(root, backend, config=config)
    assert w.lane.step() and w.lane.step() is False
    assert seen == [[("reserved",)]]
    (launched,) = [j for _, j in backend.calls]
    (other,) = {first, second} - {launched}  # equal band and due time: the tie breaks on job ID
    waiting = job_row(root, other)
    assert waiting.state == "waiting_budget" and waiting.last_error_code == "budget_exhausted:ordinary.invocations"
    assert [r.state for r in reservations(root)] == ["charged"]
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        assert jobs.queue_summary(view, now=ws.START)["waiting_reasons"] == {"waiting_budget:budget_exhausted:ordinary.invocations": 1}


def test_ordinary_cannot_spend_protected_pool(root):
    seed_charged(root, "update_task", 45, input_estimate=32_768)
    seed_charged(root, "update_task", 1, input_estimate=1_500_000 - 45 * 32_768)  # 1,500,000 ordinary input used (decision 0034)
    refused = seed_reservations(root, "update_task", 1, input_estimate=1)[0]
    assert isinstance(refused, budgets.Refusal) and refused.reason == "budget_exhausted:ordinary.input_estimate"
    with db.open_store(ws.context(root), readonly=True) as store, store.read() as view:
        pools = budgets.summary(view, "2026-10-16", BudgetConfig())["pools"]
    assert pools["protected"]["remaining"] == {"invocations": 30, "input_estimate": 300_000, "output_estimate": 60_000}
    # Through the worker: the ordinary job waits; a protected review still launches.
    extraction = ws.enqueue_model_job(root, "extract_claims", key="x")
    review = ws.enqueue_model_job(root, "review_claims", key="r")
    backend = ws.FakeBackend()
    w = make_worker(root, backend)
    while w.lane.step():
        pass
    assert [j for _, j in backend.calls] == [review]
    assert job_row(root, extraction).last_error_code == "budget_exhausted:ordinary.input_estimate"
    used = reservations(root)[-1]
    assert used.purpose == "review_claims" and used.protected.invocations == 1
    assert (used.ordinary.invocations, used.ordinary.input_estimate, used.ordinary.output_estimate) == (0, 0, 0)


def test_review_can_borrow_remaining_ordinary_pool(root):
    reviews = seed_reservations(root, "review_claims", 6)  # 54,000 of 60,000 protected output, each the 9,000 cap
    assert all(r.protected.output_estimate == 9000 and r.ordinary.output_estimate == 0 for r in reviews)
    split = seed_reservations(root, "review_claims", 1)[0]  # protected output exhausted mid-reservation
    assert (split.protected.output_estimate, split.ordinary.output_estimate) == (6000, 3000)
    borrowed = seed_reservations(root, "review_claims", 1, now="2026-10-16T09:00:00.000000Z")[0]
    assert borrowed.protected.invocations == 1 and borrowed.protected.output_estimate == 0 and borrowed.ordinary.output_estimate == 9000
    seed_charged(root, "revalidate", 22)  # protected invocations: 30 used (each settled at 100 output tokens)
    after = seed_reservations(root, "review_claims", 1)[0]
    assert after.protected.invocations == 0 and after.ordinary.invocations == 1  # the invocation itself is borrowed
    # Ordinary capacity is finite too: once it is gone, review waits like anything else.
    seed_reservations(root, "extract_claims", 6)  # 84,000 + 21,000 borrowed + 2,200 settled = 107,200 of 120,000 ordinary output
    seed_reservations(root, "review_claims", 1)  # 116,200
    last = seed_reservations(root, "review_claims", 1)[0]
    assert isinstance(last, budgets.Refusal) and last.reason == "budget_exhausted:protected+ordinary.output_estimate"


def test_full_reservation_arithmetic_with_reasoning_headroom(root):
    """Three 14,000 extractions, ten 7,500 task updates and seven 9,000 reviews (the last borrowing 3,000 ordinary) fill both output pools.

    Each reservation is the purpose's allowance plus the 6,000 reasoning headroom (decision 0029); the body cap stays 3 × the allowance.
    """
    made = seed_reservations(root, "extract_claims", 3) + seed_reservations(root, "update_task", 10) + seed_reservations(root, "review_claims", 7)
    assert all(isinstance(r, BudgetReservation) for r in made) and len(made) == 20
    assert all(r.estimated_output_limit == provider_output_cap(r.purpose) and r.reasoning_headroom == REASONING_HEADROOM for r in made)
    assert all(r.max_response_body_bytes == body_cap_for(r.purpose) and r.max_wire_stdout_bytes == 262_144 and r.max_stderr_bytes == 65_536 for r in made)
    for purpose, reason in (("extract_claims", "ordinary.output_estimate"), ("update_task", "ordinary.output_estimate"), ("review_claims", "protected+ordinary.output_estimate"), ("revalidate", "protected+ordinary.output_estimate")):
        refusal = seed_reservations(root, purpose, 1)[0]
        assert isinstance(refusal, budgets.Refusal) and refusal.reason == f"budget_exhausted:{reason}", purpose
    with db.open_store(ws.context(root), readonly=True) as store, store.read() as view:
        summary = budgets.summary(view, "2026-10-16", BudgetConfig())
    remaining_calls = summary["pools"]["ordinary"]["remaining"]["invocations"] + summary["pools"]["protected"]["remaining"]["invocations"]
    assert remaining_calls == 70  # 90 is only the call ceiling
    assert summary["pools"]["ordinary"]["exhausted"] == ["output_estimate"] and summary["pools"]["protected"]["exhausted"] == ["output_estimate"]
    assert summary["per_purpose"]["extract_claims"] == {"calls": 3, "input_estimate": 300, "output_estimate": 42_000}
    # A smaller known usage releases capacity; unknown interrupted usage keeps it.
    from recalith.contracts.jobs import LocalUsage
    from recalith.contracts.operations import UsageReport

    with db.open_store(ws.context(root)) as store, store.transaction() as txn:
        budgets.charge(txn, made[0].reservation_id, reported=UsageReport(input_tokens=90, output_tokens=2000, estimated_input_tokens=100, estimated_output_tokens=2100, provider_request_id=None, duration_ms=5), local=LocalUsage(input_estimate=100, output_estimate=2100))
        budgets.charge(txn, made[1].reservation_id, reported=None, local=None)
    assert isinstance(seed_reservations(root, "update_task", 1)[0], BudgetReservation)  # 12,000 released
    assert isinstance(seed_reservations(root, "update_task", 4)[-1], budgets.Refusal)  # the interrupted one released nothing


def test_input_estimate_limits_and_model_input_cap(root):
    """Input pools bound calls too; one request is capped at 96 KiB serialized (32,768 estimates)."""
    assert budgets.MAX_INPUT_ESTIMATE == 32_768
    made = seed_charged(root, "update_task", 46, input_estimate=32_768)  # 45 fit the 1,500,000 ordinary pool (decision 0034)
    assert all(isinstance(r, BudgetReservation) for r in made[:45])
    assert isinstance(made[45], budgets.Refusal) and made[45].reason == "budget_exhausted:ordinary.input_estimate"
    assert seed_reservations(root, "revalidate", 1, input_estimate=32_769)[0].reason == "model_input_oversized"
    # Through the worker: a request of exactly 96 KiB launches; one byte more never reaches the backend.
    fits = ws.enqueue_model_job(root, "review_claims", key="fits")
    backend = ws.FakeBackend()
    w = make_worker(root, backend, prepare=ws.sized_preparer(MODEL_INPUT_CAP))
    assert w.lane.step()
    assert backend.calls == [("review_claims", fits)] and reservations(root)[-1].estimated_input_limit == 32_768
    too_big = ws.enqueue_model_job(root, "review_claims", key="big")
    w2 = make_worker(root, backend, prepare=ws.sized_preparer(MODEL_INPUT_CAP + 1))
    assert w2.lane.step()
    assert len(backend.calls) == 1
    row = job_row(root, too_big)
    assert row.state == "failed" and row.last_error_code == "request_invalid"


def test_failed_attempts_are_charged_and_back_off(root):
    """Retries after 1, 5 and 30 minutes, then failed; every launched attempt is charged."""
    job_id = ws.enqueue_model_job(root, "extract_claims")
    clock = ws.FakeClock()
    w = make_worker(root, ws.FakeBackend(lambda purpose, i: worker.LaunchOutcome(stdout=b"", returncode=1)), clock=clock)
    for expected_delay in (60, 300, 1800):
        assert w.lane.step()
        row = job_row(root, job_id)
        assert row.state == "pending" and row.last_error_code == "provider_failed"
        assert row.due_at == jobs._plus(clock.now(), expected_delay)
        assert w.lane.step() is False  # not due yet
        clock.advance(expected_delay)
    assert w.lane.step()
    row = job_row(root, job_id)
    assert row.state == "failed" and row.attempt == 4
    charged = reservations(root)
    assert len(charged) == 4 and {r.state for r in charged} == {"charged"}
    assert all(budgets.actual_usage(r) == (r.estimated_input_limit, r.estimated_output_limit) for r in charged)  # unknown usage keeps the reservation


def test_evidence_expansion_rounds_are_charged(root):
    """Each expansion is another reserved invocation; at most two rounds per job."""
    expanding = ws.enqueue_model_job(root, "extract_claims", key="expanding")
    w = make_worker(root, ws.FakeBackend(lambda purpose, i: outcome(ws.evidence_request_body() if i < 2 else ws.NO_OP_BODY)))
    assert w.lane.step()
    assert job_row(root, expanding).state == "completed"
    assert [r.job_id for r in reservations(root)] == [expanding] * 3
    endless = ws.enqueue_model_job(root, "extract_claims", key="endless")
    w2 = make_worker(root, ws.FakeBackend(lambda purpose, i: outcome(ws.evidence_request_body())))
    assert w2.lane.step()
    row = job_row(root, endless)
    assert row.state == "failed" and row.last_error_code == "expansion_limit"
    assert [r.job_id for r in reservations(root)].count(endless) == 3 and ws.state(root)["effects"] == {expanding: 1}


# ---------------------------------------------------------------------------
# Priority (A50)


def test_declaration_review_precedes_ordinary_review(root):
    """Code-assigned correction/declaration review wins the next launch, without killing an in-flight call."""
    clock = ws.FakeClock()
    ordinary = ws.enqueue_model_job(root, "review_claims", key="ordinary-1", now="2026-10-16T07:00:00.000000Z")
    extraction = ws.enqueue_model_job(root, "extract_claims", key="extract", now="2026-10-16T06:00:00.000000Z")
    gate = threading.Event()
    backend = ws.FakeBackend(gate=gate)
    w = make_worker(root, backend, clock=clock)
    in_flight = threading.Thread(target=w.lane.step)
    in_flight.start()
    assert backend.in_flight.wait(10)
    assert backend.calls == [("review_claims", ordinary)]  # review precedes the older extraction
    correction = ws.enqueue_model_job(root, "review_claims", key="correction", candidates=[jobs.ReviewCandidate(claim_id="claim_x", origin="operator_correction", claim_kind="fact")])
    later_ordinary = ws.enqueue_model_job(root, "review_claims", key="ordinary-2", now="2026-10-16T05:00:00.000000Z")
    assert job_row(root, correction).review_priority == "correction_or_declaration" and job_row(root, correction).priority < job_row(root, later_ordinary).priority
    gate.set()
    in_flight.join(10)
    assert job_row(root, ordinary).state == "completed"  # the healthy in-flight call finished normally
    while w.lane.step():
        pass
    assert [j for _, j in backend.calls] == [ordinary, correction, later_ordinary, extraction]


def test_review_priority_is_code_assigned_and_batches_keep_their_origin():
    c = jobs.ReviewCandidate
    assert jobs.review_priority_for([c("claim_a", "extracted", "fact")]) == "ordinary"
    assert jobs.review_priority_for([c("claim_a", "extracted", "preference")]) == "ordinary"  # no eligible direct user evidence
    assert jobs.review_priority_for([c("claim_a", "extracted", "fact"), c("claim_b", "extracted", "decision", direct_user_evidence=True)]) == "correction_or_declaration"  # mixed batch
    assert jobs.review_priority_for([c("claim_a", "typed_declaration", "preference")]) == "correction_or_declaration"
    assert jobs.band_for("review_claims", "correction_or_declaration") < jobs.band_for("review_claims", "ordinary") < jobs.band_for("build_episode") < jobs.band_for("extract_claims") == jobs.band_for("update_task") < jobs.band_for("revalidate")
    twenty = [c(f"claim_{i}", "extracted", "fact") for i in range(20)]
    assert [len(b) for b in jobs.plan_review_batches(twenty)] == [8, 8, 4]


def test_declaration_cannot_bypass_exhausted_budget(root):
    """Priority orders launches; it never adds capacity."""
    config = BudgetConfig(daily_invocations=30)  # protected 30 + ordinary 0
    seed_charged(root, "revalidate", 30, config=config)  # every invocation used; settled small, so only invocations run out
    correction = ws.enqueue_model_job(root, "review_claims", key="c", candidates=[jobs.ReviewCandidate(claim_id="claim_c", origin="operator_correction", claim_kind="fact")])
    clock = ws.FakeClock()
    backend = ws.FakeBackend()
    w = make_worker(root, backend, clock=clock, config=config_with(daily_invocations=30))
    assert w.lane.step() is False and backend.calls == []
    row = job_row(root, correction)
    assert row.state == "waiting_budget" and row.last_error_code == "budget_exhausted:protected+ordinary.invocations"
    w.poll_once()
    assert w.status()["state"] == "budget_paused"
    clock.advance(24 * 3600)  # the next UTC day has a fresh ledger
    assert w.lane.step() and backend.calls == [("review_claims", correction)]


def test_five_candidates_use_one_review_call(tmp_path):
    """One extraction proposing five candidates plus one fitting review batch is two calls: one ordinary, one protected.

    Real flow (Task 9): real captured events, the production request preparer,
    the persisted proposal, admission scheduling the review job in the
    extraction's application, the persisted ReviewBatch and assessment
    admission. The backend answers with recorded bodies built from the request
    it receives (mechanics, not live model quality).
    """
    from recalith import prompts
    from recalith.controller import requests

    root = osc.project(tmp_path)
    ctx = osc.context(root)
    fail = osc.events(root)["fail"]
    with db.open_store(ctx) as store, store.transaction() as txn:
        extraction, _ = jobs.enqueue(txn, kind="extract_claims", input_refs=[RecordRef(kind="event", id=fail["id"], revision=1)], now=ws.START, prompt_version=prompts.CURRENT["extract_claims"], due_at=osc.EARLIEST)
    link = osc.link(root, "fail", quote="FAILURES")
    extraction_body = osc.body([osc.op(f"c{i}", "propose_claim", osc.claim(f"Candidate {i}: the fixture pytest run failed.", subject=f"five-{i}"), evidence=[link]) for i in range(5)])
    seen: dict[str, Any] = {}

    def answer(request: bytes, purpose: str) -> None:
        data = json.loads(request)
        if purpose == "extract_claims":
            seen["body"] = extraction_body
            return
        batch = data["review_batch"]
        seen["batch"] = batch
        ops = []
        for i, ref in enumerate(batch["candidate_refs"]):
            claim = next(c for c in data["claims"] if c["claim_id"] == ref["id"])
            evidence = next(e["evidence_id"] for e in batch["evidence_index"] if e["link"] in claim["supports"])
            payload = {"batch_id": batch["batch_id"], "candidate_ref": ref, "verdict": "supported", "objections": [], "evidence_ids": [evidence]}
            ops.append({"local_ref": f"a{i}", "kind": "assess_claim", "depends_on": [], "target": ref, "payload": payload, "evidence": [], "reason": ""})
        seen["body"] = json.dumps({"operations": ops}).encode()

    backend = ws.FakeBackend(lambda purpose, i: outcome(seen["body"]), on_launch=answer)
    w = worker.Worker(ctx, clock=ws.FakeClock(), model=worker.ModelRuntime(backend=backend, prepare=requests.runtime_preparer(ctx, now=lambda: ws.START)))
    try:
        while w.lane.step():
            pass
    finally:
        w.close()
    (review_job,) = [j for _, j in backend.calls if j != extraction]
    assert backend.calls == [("extract_claims", extraction), ("review_claims", review_job)]  # two calls in all
    used = reservations(root)
    assert [(r.purpose, r.ordinary.invocations, r.protected.invocations) for r in used] == [("extract_claims", 1, 0), ("review_claims", 0, 1)]
    assert len(seen["batch"]["candidate_refs"]) == 5  # one fitting batch, persisted before launch
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        assert view.execute("SELECT COUNT(*) FROM review_batches WHERE review_job_id = ?", (review_job,)).fetchone()[0] == 1
        heads = view.execute("SELECT status, strength FROM claim_heads").fetchall()
    assert sorted(heads) == [("active", "supported")] * 5
    assert job_row(root, extraction).state == "completed" and job_row(root, review_job).state == "completed"


# ---------------------------------------------------------------------------
# Output bounds: wire versus body (A30, worker side)


def test_15kb_episode_body_with_host_envelope_fits(root):
    body = ws.episode_body(15_000)
    assert 15_000 <= len(body) <= 24_000
    job_id = ws.enqueue_model_job(root, "build_episode")
    w = make_worker(root, ws.FakeBackend(lambda purpose, i: outcome(body, padding=80_000)))
    assert w.lane.step()
    assert job_row(root, job_id).state == "completed"
    (res,) = reservations(root)
    assert res.max_response_body_bytes == 24_000 and res.state == "charged" and res.reported_usage.output_tokens == 10
    # The same through a real child process and the bounded launcher.
    second = ws.enqueue_model_job(root, "build_episode", key="process")
    w2 = worker.Worker(ws.context(root), clock=ws.FakeClock(), model=worker.ModelRuntime(backend=ws.process_backend(root, "episode", "15000", "100000"), prepare=lambda s, j, r: ws.request_for(s, j, r)))
    assert w2.lane.step()
    assert job_row(root, second).state == "completed"


def test_body_and_wire_caps_are_separate(root):
    clock = ws.FakeClock()
    cases = {
        "body_over_cap": (lambda p, i: outcome(ws.episode_body(25_000)), "response_body_oversized"),
        "envelope_over_wire": (lambda p, i: outcome(ws.NO_OP_BODY, padding=270_000), "wire_stdout_oversized"),
        # The enclosing body is strict; a malformed *operation* fails only its group (test_operations).
        "malformed_body": (lambda p, i: outcome(b'{"operations": [], "no_op_reason": "x", "verdict": "approve"}'), "response_invalid"),
        "not_an_envelope": (lambda p, i: worker.LaunchOutcome(stdout=b"plain text"), "envelope_invalid"),
    }
    for name, (script, code) in cases.items():
        job_id = ws.enqueue_model_job(root, "build_episode", key=name)
        w = make_worker(root, ws.FakeBackend(script), clock=clock)
        assert w.lane.step(), name
        row = job_row(root, job_id)
        assert (row.state, row.last_error_code) == ("pending", code), name  # rejected without clipping, retried with backoff
    assert len(reservations(root)) == len(cases) and {r.state for r in reservations(root)} == {"charged"}  # failures are charged
    # The body cap counts the decoded body's original UTF-8 bytes, not its escaped wire form.
    accented = ws.episode_body(23_000, filler="é")
    wire = ws.envelope(accented)  # JSON-escaped: every é travels as six bytes
    assert len(accented) <= 24_000 < len(wire)
    ok = ws.enqueue_model_job(root, "build_episode", key="escaped")
    w = make_worker(root, ws.FakeBackend(lambda p, i: worker.LaunchOutcome(stdout=wire)), clock=clock)
    assert w.lane.step() and job_row(root, ok).state == "completed"


def test_process_backend_bounds_hang_flood_and_tree(root, tmp_path):
    """A real child that hangs, floods stdout, floods stderr or leaves a grandchild is bounded."""
    clock = ws.FakeClock()
    config = config_with(timeout_seconds=2)
    pidfile = tmp_path / "grandchild.pid"
    for mode, args, code in (("hang", (), "provider_timeout"), ("flood", (), "wire_stdout_oversized"), ("grandchild", (str(pidfile),), "provider_timeout"), ("stderr_flood", (), None)):
        job_id = ws.enqueue_model_job(root, "revalidate", key=mode)
        backend = ws.process_backend(root, mode, *args)
        w = worker.Worker(ws.context(root), clock=clock, config=config, model=worker.ModelRuntime(backend=backend, prepare=lambda s, j, r: ws.request_for(s, j, r)))
        started = time.monotonic()
        assert w.lane.step(), mode
        assert time.monotonic() - started < 15, mode
        row = job_row(root, job_id)
        assert row.last_error_code == code, mode
        if code is None:
            assert row.state == "completed"
    grandchild = int(pidfile.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _alive(grandchild):
        time.sleep(0.05)
    assert not _alive(grandchild), "the grandchild outlived the bounded launch"
    timed_out = reservations(root)[0]  # the hung call: unknown usage keeps its whole reservation
    assert budgets.actual_usage(timed_out) == (timed_out.estimated_input_limit, timed_out.estimated_output_limit)


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # a zombie awaiting its reaper is not running
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return True


def test_curator_child_environment_from_worker(root, tmp_path):
    """A67 (worker→curator hop): the model child gets a fresh curator environment from the worker's."""
    ctx = ws.context(root)
    secret = "sk-ant-api03-" + "q" * 40
    worker_env = {**{k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "LANG")}, "RECALITH_WORKER_INSTALLATION": ctx.installation_id, "CLAUDECODE": "1", "CLAUDE_CODE_CHILD_SESSION": "1", "UNRELATED_TOKEN": secret, "RECALITH_TEST_ROUTE_KEY": "x", "FAKE_ROUTE_KEY": "route-value"}
    record = tmp_path / "env.json"
    job_id = ws.enqueue_model_job(root, "update_task")
    backend = ws.process_backend(root, "env", str(record), inherited=worker_env, route_keys=["FAKE_ROUTE_KEY"])
    w = worker.Worker(ctx, clock=ws.FakeClock(), environment=worker_env, model=worker.ModelRuntime(backend=backend, prepare=lambda s, j, r: ws.request_for(s, j, r)))
    assert w.lane.step() and job_row(root, job_id).state == "completed"
    seen = json.loads(record.read_text(encoding="utf-8"))
    assert seen["curator_marker"] == ctx.installation_id and seen["worker_marker"] is None
    for absent in ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "UNRELATED_TOKEN", "RECALITH_TEST_ROUTE_KEY", "RECALITH_WORKER_INSTALLATION"):
        assert absent not in seen["keys"], absent
    assert "FAKE_ROUTE_KEY" in seen["keys"]  # the selected route key, and only it
    report = backend.last_environment_report
    assert secret not in json.dumps(report) and "route-value" not in json.dumps(report)  # names only


# ---------------------------------------------------------------------------
# Deterministic lane: typed ingestion, recovery, exhaustion (A31, A45, A50)


def _capture_lifecycle(replayer, tmp, records=None):
    import claude_fixtures as cf

    for record in records or cf.records("lifecycle")[:6]:
        proc, _ = cf.run_hook(replayer.root, replayer.prepare(record), event=record["event"])
        assert proc.returncode == 0


def _ingested(root) -> tuple[int, int]:
    import claude_fixtures as cf
    from recalith.core import identity

    ctx = identity.resolve_installation(root, actor=cf.ADAPTER_ACTOR)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        events = view.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        done = view.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'ingest' AND state = 'completed'").fetchone()[0]
    return events, done


def test_typed_ingestion_runs_while_model_is_pending(tmp_path):
    """Real captured Claude events are ingested and their typed jobs complete while a model call is in flight."""
    import claude_fixtures as cf

    replayer = cf.Replay(tmp_path / "replay")
    ctx = replayer.ctx
    with db.open_store(ctx) as store, store.transaction() as txn:
        jobs.enqueue(txn, kind="extract_claims", input_refs=[RecordRef(kind="claim", id=f"claim_{digest_of('pending')}", revision=1)], now=ws.START, prompt_version="test@1")
    gate = threading.Event()
    backend = ws.FakeBackend(gate=gate)
    w = worker.Worker(ctx, config=ProjectConfig.defaults_for(cf.PROJECT_ID), model=ws.runtime(backend))
    runner = threading.Thread(target=w.run)
    runner.start()
    try:
        assert backend.in_flight.wait(15), "the model call never started"
        _capture_lifecycle(replayer, tmp_path)
        # Wait for the drained state, not the first completed job: the worker polls concurrently with capture, so an
        # early poll can finish some ingest jobs while the last segments are still being published (CI run 26, macOS).
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and (_ingested(replayer.root)[1] == 0 or spool.ready_segments(spool.SpoolDirs(replayer.root))):
            time.sleep(0.05)
        events, done = _ingested(replayer.root)
        assert events > 0 and done >= 1 and backend.in_flight.is_set(), "typed ingestion waited for the model"
        assert spool.ready_segments(spool.SpoolDirs(replayer.root)) == []
    finally:
        gate.set()
        w.stop_event.set()
        runner.join(20)
    assert not runner.is_alive()
    assert worker.read_status(replayer.root)["state"] == "stopped"


def test_a_handler_failure_names_its_exception_type(tmp_path):
    """The first live pilot's ingest jobs read only ``handler_error``; a failed handler now names the type, as ``lane_error:<type>`` does."""
    import sqlite3

    import claude_fixtures as cf

    replayer = cf.Replay(tmp_path / "replay")
    clock = ws.FakeClock(utc_now())
    w = worker.Worker(replayer.ctx, clock=clock, config=ProjectConfig.defaults_for(cf.PROJECT_ID))

    def unwritable(txn, job, worker_):
        raise sqlite3.OperationalError("unable to open database file")  # what the pilot's reductions raised

    w.handlers["ingest"] = unwritable
    _capture_lifecycle(replayer, tmp_path)
    clock.advance(max(1.0, (parse_utc(utc_now()) - parse_utc(clock.now())).total_seconds() + 1))
    w.poll_once()
    with db.open_store(replayer.ctx, readonly=True) as store, store.read() as view:
        failed = [jobs.get_job(view, r[0]) for r in view.execute("SELECT job_id FROM jobs WHERE kind = 'ingest'")]
    assert failed and {(j.state, j.last_error_code) for j in failed} == {("pending", "handler_error:OperationalError")}


def test_budget_exhaustion_blocks_launch_but_not_capture(tmp_path):
    """A31: no new invocation starts; capture and deterministic ingestion still work."""
    import claude_fixtures as cf

    replayer = cf.Replay(tmp_path / "replay")
    ctx = replayer.ctx
    clock = ws.FakeClock(utc_now())  # ingestion stamps real time; the fake clock starts there
    seed_charged(replayer.root, "update_task", 60, now=clock.now())  # all 60 ordinary invocations
    with db.open_store(ctx) as store, store.transaction() as txn:
        job_id, _ = jobs.enqueue(txn, kind="extract_claims", input_refs=[RecordRef(kind="claim", id=f"claim_{digest_of('x')}", revision=1)], now=clock.now(), prompt_version="test@1")
    backend = ws.FakeBackend()
    w = worker.Worker(ctx, clock=clock, config=ProjectConfig.defaults_for(cf.PROJECT_ID), model=ws.runtime(backend))
    _capture_lifecycle(replayer, tmp_path)
    # Ingest jobs are due at their real capture time; catch the fake clock up past it (a slow Windows runner
    # takes more than a second for the six hook processes; CI run 27).
    clock.advance(max(1.0, (parse_utc(utc_now()) - parse_utc(clock.now())).total_seconds() + 1))
    assert w.poll_once() is True
    assert w.lane.step() is False and backend.calls == []
    events, done = _ingested(replayer.root)
    assert events > 0 and done >= 1
    status = w.status()
    assert status["queue"]["waiting_reasons"] == {"waiting_budget:budget_exhausted:ordinary.invocations": 1}
    assert status["budget"]["pools"]["ordinary"]["exhausted"] == ["invocations"]


def test_provider_unavailable_is_visible_and_ingestion_continues(tmp_path):
    """Preview without a certified backend: model jobs wait visibly; nothing is launched or faked."""
    import claude_fixtures as cf

    replayer = cf.Replay(tmp_path / "replay")
    ctx = replayer.ctx
    with db.open_store(ctx) as store, store.transaction() as txn:
        job_id, _ = jobs.enqueue(txn, kind="build_episode", input_refs=[RecordRef(kind="task", id="task_00000000-0000-4000-8000-000000000000", revision=1)], now=utc_now(), prompt_version="test@1")
    _capture_lifecycle(replayer, tmp_path)
    w = worker.Worker(ctx, clock=ws.FakeClock(utc_now()))
    w.poll_once()
    row = job_row_ctx(ctx, job_id)
    assert row.state == "pending" and row.last_error_code == "provider_unavailable"
    assert w.status()["model_lane"] == "provider_unavailable"
    assert _ingested(replayer.root)[0] > 0


def job_row_ctx(ctx, job_id):
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        return jobs.get_job(view, job_id)


def test_worker_recovers_registered_transcripts_with_their_named_parser(tmp_path):
    """The worker runs recover_source with each source's registered parser; unknown parsers are explicit gaps."""
    import claude_fixtures as cf

    replayer = cf.Replay(tmp_path / "replay")
    cf.replay(replayer, "denied", tmp_path)
    pipeline.ingest_ready(replayer.ctx)
    with db.open_store(replayer.ctx, readonly=True) as store, store.read() as view:
        (source_id, locator, coverage), = view.execute("SELECT source_id, locator, coverage FROM capture_sources").fetchall()
    assert json.loads(coverage)["parser"] == "claude_code_transcript@2.1.301"
    text = (cf.FIXTURES / "denied.transcript.jsonl").read_text(encoding="utf-8")
    for placeholder, real in replayer.placeholders().items():
        text = text.replace(placeholder, json.dumps(real)[1:-1])
    Path(locator).write_bytes(text.encode("utf-8"))
    w = worker.Worker(replayer.ctx, clock=ws.FakeClock())
    w.poll_once()
    w.poll_once()
    with db.open_store(replayer.ctx, readonly=True) as store, store.read() as view:
        assistant = view.execute("SELECT COUNT(*) FROM events WHERE kind = 'assistant_message'").fetchone()[0]
    assert assistant == 1  # read once, whole, through the worker
    # A source naming a parser this build does not have is a gap, not a guess.
    with db.open_store(replayer.ctx) as store, store.transaction() as txn:
        txn.execute("UPDATE capture_sources SET coverage = ? WHERE source_id = ?", (json.dumps({"parser": "claude_code_transcript@9.9.9"}), source_id))
        txn.mutated(serving_relevant=False)
    w2 = worker.Worker(replayer.ctx, clock=ws.FakeClock())
    w2.poll_once()
    w2.poll_once()
    gaps = [(g["code"], g["reason"]) for g in spool.read_gaps(spool.SpoolDirs(replayer.root))]
    assert gaps.count(("source_parser_unavailable", "claude_code_transcript@9.9.9")) == 1


def test_poll_cadence_runs_from_poll_start(root):
    """SYSTEM_SPEC §6.1: the idle 5 s (active 1 s) cadence runs from poll start; a slow poll does not stretch it."""
    clock = ws.FakeClock()
    w = make_worker(root, ws.FakeBackend(), clock=clock)
    try:
        w.poll_once()
        real_tick = w.tick

        def slow_tick() -> bool:
            clock.advance(0.8)  # e.g. fsync'd transactions and the status write on a slow runner
            return real_tick()

        w.tick = slow_tick  # type: ignore[method-assign]
        started = clock.monotonic()
        assert not w.poll_once() and w.state == "idle"
        assert w.cadence_wait(started) == pytest.approx(5.0 - 0.8)
        assert w.status()["poll"]["last_poll_seconds"] == pytest.approx(0.8)
        clock.advance(7.0)
        assert w.cadence_wait(started) == 0.0  # an overlong poll never waits a negative time
    finally:
        w.close()


def test_status_reports_the_poll_it_follows(root):
    """The status written after a poll gives that poll's duration, not the one before it (decision 0022).

    The typed-state measurement read a slow ingesting poll from the status one poll late and charged it to
    the next trial, so Windows' late trials looked like missed cycles with fast polls.
    """
    clock = ws.FakeClock()
    w = make_worker(root, ws.FakeBackend(), clock=clock)
    try:
        real_tick = w.tick
        durations = iter([0.8, 0.1])

        def timed_tick() -> bool:
            clock.advance(next(durations))
            return real_tick()

        w.tick = timed_tick  # type: ignore[method-assign]
        w.poll_once()
        assert w.status()["poll"]["last_poll_seconds"] == pytest.approx(0.8)
        w.poll_once()
        assert w.status()["poll"]["last_poll_seconds"] == pytest.approx(0.1)
        assert w.status()["poll"]["timing"]["marks"]["tick_end"] == pytest.approx(0.1)
    finally:
        w.close()


def _store_file(ctx) -> Path:
    return Path(ctx.root) / ".recalith" / db.STATE_DB


def _file_signature(path: Path) -> tuple[int, int, str]:
    import hashlib

    st = os.stat(path)
    return st.st_size, st.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()


def _fill_wal(path: Path, pages: int) -> None:
    """Append about ``pages`` WAL frames that nothing has checkpointed yet (as a busy day of commits would)."""
    import sqlite3

    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("PRAGMA wal_autocheckpoint = 0")
        conn.execute("CREATE TABLE IF NOT EXISTS test_wal_fill (b BLOB)")
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany("INSERT INTO test_wal_fill VALUES (?)", [(os.urandom(3000),) for _ in range(pages)])
        conn.execute("COMMIT")
    finally:
        conn.close()  # the worker's open connection keeps this close from checkpointing


class _SteppedClock(worker.Clock):
    """Real wall time (ingestion stamps jobs with it); monotonic time a test can move forward."""

    def __init__(self) -> None:
        self.offset = 0.0

    def monotonic(self) -> float:
        return time.monotonic() + self.offset


def _prompt(replayer, trial: int) -> None:
    import claude_fixtures as cf
    import worker_hosts as wh

    proc, _ = cf.run_hook(replayer.root, wh.unique_prompt(replayer, trial), event="UserPromptSubmit")
    assert proc.returncode == 0


def test_store_checkpoint_waits_until_typed_state_is_committed(tmp_path):
    """ACCEPTANCE_TESTS §7 typed-state latency (decision 0022).

    SQLite's automatic WAL checkpoint (every 1000 pages) ran inside whichever commit crossed the threshold,
    usually the ingesting poll's own, so about one event in twelve waited for the checkpoint to copy and flush
    the WAL into the main file before reaching typed state: on Windows CI runners up to 1-3 s. The worker's
    connection defers it: the main file is untouched until typed state is committed, and a poll with nothing
    waiting checkpoints once the interval allows.
    """
    import claude_fixtures as cf

    replayer = cf.Replay(tmp_path / "replay")
    ctx = replayer.ctx
    clock = _SteppedClock()
    w = worker.Worker(ctx, config=ProjectConfig.defaults_for(cf.PROJECT_ID), clock=clock)
    try:
        while w.poll_once():
            pass
        main = _store_file(ctx)
        _fill_wal(main, pages=1200)
        before = _file_signature(main)
        _prompt(replayer, 0)
        typed: list[tuple] = []
        failpoints.arm(failpoints.JOB_AFTER_COMPLETE, lambda _name: typed.append(_file_signature(main)), times=10**6)
        assert w.poll_once()  # the ingesting poll
        assert typed, "the ingest job did not complete in the poll that ingested its segment"
        assert typed[0] == before, "the store was checkpointed before typed state was committed"
        assert _ingested(replayer.root)[1] >= 1
        polls = 0
        while w.poll_once():  # the active tail
            polls += 1
            assert polls < 10
        clock.offset += worker.CHECKPOINT_INTERVAL_SECONDS
        assert not w.poll_once()
        assert _file_signature(main) != before, "an idle poll past the interval did not checkpoint the WAL"
    finally:
        w.close()


def test_deferred_checkpoints_keep_sqlites_frequency(tmp_path):
    """Decision 0022: deferring the checkpoint must not multiply it.

    A checkpoint after every burst cost Windows runners about twelve times as many flushes as SQLite's
    1000-page rule, and one that runs for seconds during a storage stall stretches the idle cycle it runs
    in. The worker checkpoints at most once per interval in a poll with nothing waiting, and under
    continuous work only after the poll's work, once twice the interval has passed.
    """
    import claude_fixtures as cf

    replayer = cf.Replay(tmp_path / "replay")
    clock = _SteppedClock()
    w = worker.Worker(replayer.ctx, config=ProjectConfig.defaults_for(cf.PROJECT_ID), clock=clock)
    try:
        while w.poll_once():
            pass
        assert w.counters["checkpoints"] == 1  # the first idle poll folds whatever WAL the worker inherited
        for trial in range(3):  # three bursts inside one interval
            _prompt(replayer, trial)
            while w.poll_once():
                pass
            clock.offset += 5.0
        assert w.counters["checkpoints"] == 1
        clock.offset += worker.CHECKPOINT_INTERVAL_SECONDS
        assert not w.poll_once()
        assert w.counters["checkpoints"] == 2
        assert "checkpoint" in w.status()["poll"]["timing"]["marks"]
        # Continuous work: a worked poll checkpoints after its work only past twice the interval.
        _prompt(replayer, 3)
        clock.offset += worker.CHECKPOINT_INTERVAL_SECONDS
        assert w.poll_once() and w.counters["checkpoints"] == 2
        _prompt(replayer, 4)
        clock.offset += worker.CHECKPOINT_INTERVAL_SECONDS
        assert w.poll_once() and w.counters["checkpoints"] == 3
        marks = w.status()["poll"]["timing"]["marks"]
        assert marks["checkpoint"] >= marks["deterministic"]  # after typed state, never inside it
    finally:
        w.close()


def test_resume_coalesces_overdue_jobs(root):
    """A suspend/resume clock jump yields one housekeeping job and no launch burst."""
    clock = ws.FakeClock()
    backend = ws.FakeBackend()
    w = make_worker(root, backend, clock=clock)
    w.poll_once()
    for revision in range(1, 11):  # ten revalidations of one claim, superseding each other
        ws.enqueue_model_job(root, "revalidate", key="claim-under-review", revision=revision, coalesce=True)
    extractions = [ws.enqueue_model_job(root, "extract_claims", key=f"e{i}") for i in range(5)]
    clock.advance(72 * 3600, jump=True)  # the machine slept for three days
    w.poll_once()
    assert w.counters["clock_jumps"] == 1
    launches = []
    while True:
        before = len(backend.calls)
        if not w.lane.step():
            break
        launches.append(len(backend.calls) - before)
    assert launches and set(launches) == {1}  # one call per scheduling opportunity
    # The ten revalidations coalesced into one; it names no live claim with a recheck a model could settle, so the
    # planner cancels it without a call (Task 10, decision 0012). The five extractions launch one at a time.
    assert len(backend.calls) == 5 and sorted(j for p, j in backend.calls if p == "extract_claims") == sorted(extractions)
    with db.open_store(ws.context(root), readonly=True) as store, store.read() as view:
        states = view.execute("SELECT kind, state, COUNT(*) FROM jobs WHERE kind IN ('revalidate', 'maintenance') GROUP BY kind, state").fetchall()
        codes = sorted(json.loads(b)["last_error_code"] for (b,) in view.execute("SELECT body FROM jobs WHERE kind = 'revalidate'").fetchall())
        days = {r[0] for r in view.execute("SELECT utc_day FROM provider_usage").fetchall()}
    assert sorted(states) == [("maintenance", "completed", 2), ("revalidate", "cancelled", 10)]
    assert codes == ["coalesced"] * 9 + ["revalidation_settled"]
    assert days == {"2026-10-19"}


def test_only_one_worker_per_installation_in_process(tmp_path):
    """The OS lock admits one worker per installation; another installation runs its own."""
    a = ws.init_project(tmp_path, "a")
    b = ws.init_project(tmp_path, "b")
    first = worker.Worker(ws.context(a))
    other = worker.Worker(ws.context(b))
    threads = [threading.Thread(target=x.run) for x in (first, other)]
    for t in threads:
        t.start()
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not all((worker.read_status(r) or {}).get("state") in ("running", "idle") for r in (a, b)):
            time.sleep(0.05)
        assert all((worker.read_status(r) or {}).get("state") in ("running", "idle") for r in (a, b))
        second = worker.Worker(ws.context(a))
        started = time.monotonic()
        assert second.run() == 0 and time.monotonic() - started < 5  # refused promptly, did nothing
        assert worker.read_status(a)["owner"] == first.owner
    finally:
        for x in (first, other):
            x.stop_event.set()
        for t in threads:
            t.join(20)


def test_session_mode_is_unavailable_in_preview(root):
    with pytest.raises(RecalithError) as refused:
        worker.run_worker(ws.context(root), mode="session")
    assert refused.value.code == "capability_unavailable"


# ---------------------------------------------------------------------------
# Kill/restart at lease and commit boundaries (ACCEPTANCE_TESTS §4)


def _driver(root: Path, log: Path, failpoint: str | None = None, skip: int = 0) -> subprocess.CompletedProcess:
    args = [sys.executable, str(HERE / "worker_scenarios.py"), str(root), str(log)]
    if failpoint:
        args += [failpoint, str(skip)]
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)


# Three reviews since Task 9: the scenario's own review job, plus the reviews the seed claim's and the
# extraction's applications scheduled for their candidates (the replacement's at its superseding revision).
REFERENCE_APPLICATIONS = ["build_episode", "extract_claims", "review_claims", "review_claims", "review_claims", "service", "update_task"]


@pytest.mark.parametrize("failpoint", list(failpoints.WORKER))
def test_worker_crash_at_job_boundaries_matches_reference(tmp_path, failpoint):
    """Killed at a lease/reservation/proposal/application/commit boundary and restarted: one effect per job.

    The project holds real captured Claude 2.1.301 events; the jobs propose real
    operations (an independent claim, an atomic replacement + supersession, a
    group citing a never-captured event, a malformed operation and its
    dependent, an episode and a task update). The reopened store must equal a
    reference run: the same jobs, applications, operation rows, decisions,
    claim/task/episode heads and revision counts, relations, links, and the
    same guidance epoch.
    """
    reference_root = osc.crash_project(tmp_path, "reference")
    assert _driver(reference_root, tmp_path / "reference.calls").returncode == 0
    reference = osc.normalized(reference_root)
    assert reference["applications"] == REFERENCE_APPLICATIONS
    assert [k for k, _ref, _kind in reference["operations"]].count("extract_claims") == 3
    crashed = 0
    for rep in range(REPS):
        root = osc.crash_project(tmp_path, f"crash-{rep}")
        log = tmp_path / f"crash-{rep}.calls"
        result = _driver(root, log, failpoint, skip=rep % 3)
        if result.returncode == failpoints.KILL_STATUS:
            crashed += 1
            restart = _driver(root, log)
            assert restart.returncode == 0, restart.stderr
        else:
            assert result.returncode == 0, result.stderr
        assert osc.normalized(root) == reference, (failpoint, rep)
        state = ws.state(root)
        calls = log.read_text(encoding="utf-8").split() if log.exists() else []
        launches_per_job = {j: calls.count(j) for j in set(calls)}
        if failpoint in (failpoints.JOB_AFTER_PROPOSAL, failpoints.APPLY_AFTER_GROUP, failpoints.JOB_BEFORE_COMPLETE_COMMIT, failpoints.JOB_AFTER_COMPLETE):
            assert set(launches_per_job.values()) <= {1}, "a persisted proposal was re-requested from the model"
        assert {s for _, s in state["usage"]} == {"charged"}  # no reservation is left dangling
        assert len(state["usage"]) == len(calls) + (1 if failpoint == failpoints.JOB_AFTER_RESERVE and result.returncode == failpoints.KILL_STATUS else 0)
    assert crashed >= max(1, REPS // 2), f"{failpoint} was not reached often enough to test it"


@pytest.mark.parametrize("failpoint", list(failpoints.CHECKPOINT))
def test_worker_crash_at_deferred_checkpoint_matches_reference(tmp_path, failpoint):
    """Killed just before or after the deferred WAL checkpoint (decision 0022) and restarted: the same store.

    The scenario's last poll has nothing waiting, so it runs the checkpoint the
    burst owes. A kill there leaves committed work in the WAL (before) or in
    the main file (after); either way the reopened store equals the reference,
    passes SQLite's integrity check, and the restarted worker folds the WAL it
    inherited at its own first idle poll.
    """
    reference_root = osc.crash_project(tmp_path, "reference")
    assert _driver(reference_root, tmp_path / "reference.calls").returncode == 0
    reference = osc.normalized(reference_root)
    for rep in range(REPS):
        root = osc.crash_project(tmp_path, f"crash-{rep}")
        log = tmp_path / f"crash-{rep}.calls"
        result = _driver(root, log, failpoint, skip=0)
        assert result.returncode == failpoints.KILL_STATUS, (failpoint, result.stderr[-2000:])
        restart = _driver(root, log)
        assert restart.returncode == 0, restart.stderr
        assert osc.normalized(root) == reference, (failpoint, rep)
        ctx = ws.context(root)
        with db.open_store(ctx, readonly=True) as store, store.read() as view:
            assert view.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        calls = log.read_text(encoding="utf-8").split() if log.exists() else []
        assert set(calls.count(j) for j in set(calls)) <= {1}, "a model job was relaunched although its result had been committed"


def test_backend_bug_fails_its_job_not_the_lane(root):
    """An unexpected backend exception fails that job (charged, backed off); later jobs still run."""
    broken = ws.enqueue_model_job(root, "update_task", key="broken")

    def script(purpose, i):
        if i == 0:
            raise RuntimeError("backend bug")
        return outcome()

    w = make_worker(root, ws.FakeBackend(script))
    with pytest.raises(RuntimeError):
        w.lane.step()
    row = job_row(root, broken)
    assert (row.state, row.last_error_code) == ("pending", "lane_error:RuntimeError")
    assert [r.state for r in reservations(root)] == ["charged"]  # unknown usage: charged in full, never left dangling
    healthy = ws.enqueue_model_job(root, "update_task", key="healthy")
    assert w.lane.step() and job_row(root, healthy).state == "completed"


# ---------------------------------------------------------------------------
# Typed reduction and binding application under kill/restart (Task 6)

REDUCTION_MATRIX = list(failpoints.WORKER) + list(failpoints.REDUCTION)


def _count_hits(root: Path, log: Path, hits: Path) -> subprocess.CompletedProcess:
    args = [sys.executable, str(HERE / "worker_scenarios.py"), str(root), str(log), "count", str(hits)]
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)


@pytest.mark.parametrize("failpoint", REDUCTION_MATRIX)
def test_typed_reduction_crash_matches_reference(tmp_path, failpoint):
    """Killed inside typed reduction, the deterministic link or a binding split, then restarted: one effect.

    The project holds real 2.1.301 lifecycle payloads (with a pivot and one
    more call as variants) and a second, variant session that reduction links
    deterministically; nothing is ingested yet, so the first kills land on
    ingest jobs running typed reduction. One ``update_task`` model job then
    splits the lifecycle session at its pivot. The reference run logs every
    failpoint hit with whether reduction or the split was still outstanding;
    each repetition kills at one of those hits only, and the killed store is
    checked to differ from the reference, so every kill lands on the work
    under test (an ingest job with nothing left to reduce is never the target). The reopened store must equal the reference: tasks, bindings and
    their revisions, boundaries, episodes, operation rows, decisions, the
    reduction cursor and the guidance epoch.
    """
    import working_scenarios as wks

    reference_root = wks.crash_project(tmp_path, "reference")
    hits_log = tmp_path / "reference.hits"
    counted = _count_hits(reference_root, tmp_path / "reference.calls", hits_log)
    assert counted.returncode == 0, counted.stderr
    reference = osc.normalized(reference_root)
    assert sorted(reference["boundaries"]) == [("new_session", "pending"), ("new_session", "pending"), ("pivot_prefix", "confirmed"), ("single_active_task", "linked")]
    # Since Task 9 the lifecycle's unfixed failures also make debounce triggers due; their extractions answer no-op.
    assert reference["applications"].count("update_task") == 1 and set(reference["applications"]) == {"update_task", "extract_claims"}
    assert reference["decisions"] == [("update_task", "split", "apply", "admitted")]
    assert len(reference["tasks"]) == 3 and sorted(status for _rev, status, _body in reference["tasks"]) == ["active", "active", "linked"]
    hits = [line.split() for line in hits_log.read_text(encoding="utf-8").splitlines()]
    mine = [(r, s_) for name, r, s_ in hits if name == failpoint]
    reducing = [i for i, (r, _s) in enumerate(mine) if r == "1"]
    deciding = [i for i, (r, s_) in enumerate(mine) if r == "0" and s_ == "1"]
    # Kill while typed reduction is outstanding (the job that reduces) and while only the split is (the model job).
    ordinals = sorted({*reducing[:1], *deciding[-1:]})
    assert ordinals, f"{failpoint} is never reached while reduction or the binding decision is outstanding"
    for rep in range(REPS):
        root = wks.crash_project(tmp_path, f"crash-{rep}")
        log = tmp_path / f"crash-{rep}.calls"
        result = _driver(root, log, failpoint, skip=ordinals[rep % len(ordinals)])
        assert result.returncode == failpoints.KILL_STATUS, (failpoint, rep, result.stderr)
        assert osc.normalized(root) != reference, "the kill must land before the work under test is complete"
        restart = _driver(root, log)
        assert restart.returncode == 0, restart.stderr
        assert osc.normalized(root) == reference, (failpoint, rep)
        calls = log.read_text(encoding="utf-8").split() if log.exists() else []
        per_job = {j: calls.count(j) for j in set(calls)}
        if failpoint in (failpoints.JOB_AFTER_PROPOSAL, failpoints.JOB_BEFORE_COMPLETE_COMMIT, failpoints.JOB_AFTER_COMPLETE):
            assert max(per_job.values(), default=0) <= 1, "a persisted proposal was re-requested from the model"
        assert max(per_job.values(), default=0) <= 2  # at most the killed launch and one relaunch per model job


# ---------------------------------------------------------------------------
# Root-class merges at ingestion under kill/restart (Task 8)

# Since Task 10 the merge's revalidation needs no model: the planner settles it (``planner.after_schedule``), so the
# model-launch points (reservation, proposal persistence) are never reached while it is outstanding.
MODEL_LAUNCH = (failpoints.JOB_AFTER_RESERVE, failpoints.PROPOSAL_BEFORE_COMMIT, failpoints.JOB_AFTER_PROPOSAL)
LINEAGE_MATRIX = [
    failpoints.INGEST_BEGIN, failpoints.ROOTS_AFTER_MERGE, failpoints.INGEST_BEFORE_COMMIT, failpoints.INGEST_AFTER_COMMIT, failpoints.INGEST_AFTER_UNLINK,
    failpoints.PLANNER_AFTER_SCHEDULE, *(f for f in failpoints.WORKER if f not in MODEL_LAUNCH),
]


@pytest.mark.parametrize("failpoint", LINEAGE_MATRIX)
def test_lineage_merge_crash_matches_reference(tmp_path, failpoint):
    """Killed while a segment that merges two counted root classes is ingested, or while its revalidation is settled.

    Live claims cite two separate classes; the spooled segment's bridging
    event merges them (aliases, moved members and tokens, guidance epoch),
    recomputes their strength and enqueues one revalidation job for the two
    affected claims in the same ingestion transaction; the planner then
    settles that job without a model call (Task 10). The reference run
    logs every failpoint hit with whether the merge or the revalidation was
    still outstanding; each repetition kills at one of those hits only, the
    killed store must differ from the reference, and the restarted store must
    equal it: root classes, members, aliases, token counts, registered events,
    the revalidation job and its inputs, jobs, claims and the guidance epoch.
    """
    import lineage_scenarios as lsc

    reference_root = lsc.crash_project(tmp_path, "reference")
    hits_log = tmp_path / "reference.hits"
    counted = _count_hits(reference_root, tmp_path / "reference.calls", hits_log)
    assert counted.returncode == 0, counted.stderr
    reference = (osc.normalized(reference_root), lsc.lineage_state(reference_root))
    state = reference[1]
    assert state["aliases"] == [("m-x", "m-b"), ("m-y", "m-b")] and state["revalidate"] == [sorted(["Both suites pass.", "Suite a passes."])]
    # Task 10 (decision 0012): the merge recomputes strength in its ingestion transaction; its revalidation needs no
    # model and is settled by the planner (cancelled, ``revalidation_settled``) without a call.
    assert ("revalidate", "cancelled") in reference[0]["jobs"] and all(e[0] != "m-say" for e in state["events"])
    hits = [line.split() for line in hits_log.read_text(encoding="utf-8").splitlines()]
    mine = [i for i, (name, outstanding) in enumerate(h for h in hits if h[0] == failpoint) if outstanding == "1"]
    assert mine, f"{failpoint} is never reached while the merge or its revalidation is outstanding"
    ordinals = sorted({mine[0], mine[len(mine) // 2], mine[-1]})
    for rep in range(REPS):
        root = lsc.crash_project(tmp_path, f"crash-{rep}")
        log = tmp_path / f"crash-{rep}.calls"
        result = _driver(root, log, failpoint, skip=ordinals[rep % len(ordinals)])
        assert result.returncode == failpoints.KILL_STATUS, (failpoint, rep, result.stderr)
        assert (osc.normalized(root), lsc.lineage_state(root)) != reference, "the kill must land before the work under test is complete"
        restart = _driver(root, log)
        assert restart.returncode == 0, restart.stderr
        assert (osc.normalized(root), lsc.lineage_state(root)) == reference, (failpoint, rep)
        calls = log.read_text(encoding="utf-8").split() if log.exists() else []
        assert max((calls.count(j) for j in set(calls)), default=0) <= 2  # at most the killed launch and one relaunch per model job


# ---------------------------------------------------------------------------
# Claim admission, review application and failure debounce under kill/restart (Task 9)

ADMISSION_MATRIX = [*failpoints.ADMISSION, failpoints.REQUEST_AFTER_BATCH, failpoints.REDUCE_AFTER_APPLY, *failpoints.WORKER]


@pytest.mark.parametrize("failpoint", ADMISSION_MATRIX)
def test_claim_admission_crash_matches_reference(tmp_path, failpoint):
    """Killed while a failure trigger is examined, an extraction is admitted and its review scheduled, or a review applies.

    The spooled segment's failure becomes due by count and its rerun pair
    resolves (trigger pass in the ingest transaction); the extraction's
    application admits an observed fact, writes five candidates and schedules
    their one review batch atomically; the review job persists its batch, then
    its verdicts admit two candidates, refuse a duplicated pair, record a
    revise-free capacity reject and leave one missing, with per-candidate
    outcomes. The reference run logs each failpoint hit with whether any of
    that work was outstanding; each repetition kills at one of those hits
    (first, middle, last), the killed store must differ from the reference, and
    the restarted store must equal it: jobs, applications, operations,
    decisions, claim heads with strength, basis and verdicts, review outcomes,
    batches, review requests and priorities, triggers and the trigger cursor.
    """
    import admission_scenarios as asc

    reference_root = asc.crash_project(tmp_path, "reference")
    hits_log = tmp_path / "reference.hits"
    counted = _count_hits(reference_root, tmp_path / "reference.calls", hits_log)
    assert counted.returncode == 0, counted.stderr
    reference = (osc.normalized(reference_root), asc.admission_state(reference_root))
    state = reference[1]
    by_text = {c[0]: c for c in state["claims"]}
    claims = asc.CRASH_CLAIMS
    assert by_text[claims["obs"]][2:5] == ("active", "supported", "observed")
    assert by_text[claims["inf1"]][2:4] == ("active", "supported") and by_text[claims["inf2"]][2:4] == ("active", "supported")
    assert by_text[claims["decl"]][2:] == ("candidate", "weak", "user_declared", "reject", ("review_capacity",))
    assert {o[2] for o in state["outcomes"]} == {"admitted", "duplicate", "capacity", "missing"} and state["batches"] == (1, [5])
    assert state["priorities"] == ["correction_or_declaration"] and state["review_requests"] == [("extracted", 0, True)]
    assert sorted((t[3], t[4]) for t in state["triggers"] if "crash" in t[0]) == [("due", "count"), ("resolved", None)]
    hits = [line.split() for line in hits_log.read_text(encoding="utf-8").splitlines()]
    mine = [i for i, (name, outstanding) in enumerate(h for h in hits if h[0] == failpoint) if outstanding == "1"]
    assert mine, f"{failpoint} is never reached while admission, review or the trigger pass is outstanding"
    ordinals = sorted({mine[0], mine[len(mine) // 2], mine[-1]})
    for rep in range(REPS):
        root = asc.crash_project(tmp_path, f"crash-{rep}")
        log = tmp_path / f"crash-{rep}.calls"
        result = _driver(root, log, failpoint, skip=ordinals[rep % len(ordinals)])
        assert result.returncode == failpoints.KILL_STATUS, (failpoint, rep, result.stderr)
        assert (osc.normalized(root), asc.admission_state(root)) != reference, "the kill must land before the work under test is complete"
        restart = _driver(root, log)
        assert restart.returncode == 0, restart.stderr
        assert osc.normalized(root) == reference[0], (failpoint, rep)
        assert asc.admission_state(root) == reference[1], (failpoint, rep)
        calls = log.read_text(encoding="utf-8").split() if log.exists() else []
        per_job = {j: calls.count(j) for j in set(calls)}
        if failpoint in (failpoints.JOB_AFTER_PROPOSAL, failpoints.APPLY_AFTER_GROUP, failpoints.REVIEW_AFTER_SCHEDULE, failpoints.REVIEW_AFTER_ASSESSMENT, failpoints.JOB_BEFORE_COMPLETE_COMMIT, failpoints.JOB_AFTER_COMPLETE):
            assert max(per_job.values(), default=0) <= 1, "a persisted proposal was re-requested from the model"
        assert max(per_job.values(), default=0) <= 2  # at most the killed launch and one relaunch per model job
        assert {s for _, s in ws.state(root)["usage"]} == {"charged"}


# ---------------------------------------------------------------------------
# The real request-preparation and provider path under kill/restart (Task 7)

PROVIDER_MATRIX = list(failpoints.WORKER) + list(failpoints.PROVIDER)


def _alive_pids(pidlog: Path) -> list[int]:
    import worker_hosts as wh

    pids = [int(x) for x in pidlog.read_text(encoding="utf-8").split()] if pidlog.exists() else []
    return [pid for pid in pids if wh.pid_alive(pid)]


@pytest.mark.parametrize("failpoint", PROVIDER_MATRIX)
def test_provider_path_crash_matches_reference(tmp_path, failpoint):
    """Killed while preparing, launching or applying a real provider call, then restarted: one effect per job.

    Narrative jobs scheduled by real typed reduction and a review job run
    through the production preparer, a persisted review batch, the budget
    reservation and a real bounded child (the fake JSON process, which keeps a
    sleeping grandchild) through ``ProviderBackend``. The reference run logs
    every failpoint hit with whether a model job was still unfinished; each
    repetition kills at one of those hits only (the killed store differs from
    the reference). The reopened store must equal the reference (jobs,
    applications, operation rows, decisions, task/episode/claim heads, review
    batches, episode titles, task narrative), and no curator process may
    survive: the restarted worker reaps a tree its killed predecessor left.
    """
    import provider_scenarios as ps

    reference_root = ps.crash_project(tmp_path, "reference")
    hits_log = tmp_path / "reference.hits"
    counted = _count_hits(reference_root, tmp_path / "reference.calls", hits_log)
    assert counted.returncode == 0, counted.stderr
    reference = osc.normalized(reference_root)
    reference_extra = ps.extra_state(reference_root)
    # Since Task 9 the episode checkpoint and the lifecycle's unfixed failures also schedule extractions (no-op answers).
    assert {"build_episode", "review_claims", "service", "update_task"} <= set(reference["applications"]) <= {"build_episode", "review_claims", "service", "update_task", "extract_claims"}
    assert reference_extra["review_batches"] == (1, 1) and any(t.startswith("Narrative: ") for t in reference_extra["episode_titles"])
    assert "Continue from the last checkpoint." in reference_extra["next_actions"]
    assert wh_wait(lambda: not _alive_pids(tmp_path / "reference.pids"))
    hits = [line.split() for line in hits_log.read_text(encoding="utf-8").splitlines()]
    mine = [i for i, (name, outstanding) in enumerate(h for h in hits if h[0] == failpoint) if outstanding == "1"]
    assert mine, f"{failpoint} is never reached while a model job is unfinished"
    ordinals = sorted({mine[0], mine[len(mine) // 2], mine[-1]})
    for rep in range(REPS):
        root = ps.crash_project(tmp_path, f"crash-{rep}")
        pidlog = tmp_path / f"crash-{rep}.pids"
        log = tmp_path / f"crash-{rep}.calls"
        result = _driver(root, log, failpoint, skip=ordinals[rep % len(ordinals)])
        assert result.returncode == failpoints.KILL_STATUS, (failpoint, rep, result.stderr)
        assert (osc.normalized(root), ps.extra_state(root)) != (reference, reference_extra), "the kill must land before the work under test is complete"
        restart = _driver(root, log)
        assert restart.returncode == 0, restart.stderr
        assert osc.normalized(root) == reference, (failpoint, rep)
        assert ps.extra_state(root) == reference_extra, (failpoint, rep)
        assert wh_wait(lambda pidlog=pidlog: not _alive_pids(pidlog)), f"a curator process outlived the crashed worker at {failpoint}"
        assert not list((root / ".recalith" / "run" / "curators").glob("*.json"))
        state = ws.state(root)
        assert {s for _, s in state["usage"]} == {"charged"}  # the killed call stays charged; nothing dangles


@pytest.mark.parametrize("failpoint", PROVIDER_MATRIX)
def test_api_provider_path_crash_matches_reference(tmp_path, failpoint):
    """Decision 0023: the same kill/restart matrix through the direct-API backend.

    The worker launches the production stdlib HTTP transport (``python -I
    http_transport.py``) against a loopback fake Chat Completions provider
    owned by this test, which answers each real request after a short delay,
    so a kill at ``provider.after_spawn`` leaves a live transport child
    between its spawn record and its result. The restarted store must equal
    the reference and no transport child may outlive the crashed worker.
    """
    import provider_scenarios as ps

    sys.path.insert(0, str(HERE.parent / "fixtures" / "providers"))
    import fake_api_server as fas

    with fas.FakeProvider("narrative", delay=0.3) as fake:
        url = fake.url("/v1/chat/completions")
        reference_root = ps.crash_project(tmp_path, "reference", api_url=url)
        hits_log = tmp_path / "reference.hits"
        counted = _count_hits(reference_root, tmp_path / "reference.calls", hits_log)
        assert counted.returncode == 0, counted.stderr
        reference = osc.normalized(reference_root)
        reference_extra = ps.extra_state(reference_root)
        assert {"build_episode", "review_claims", "service", "update_task"} <= set(reference["applications"])
        assert reference_extra["review_batches"] == (1, 1) and any(t.startswith("Narrative: ") for t in reference_extra["episode_titles"])
        assert "Continue from the last checkpoint." in reference_extra["next_actions"]
        assert fake.snapshot(), "the reference run never reached the provider"
        assert wh_wait(lambda: not _alive_pids(tmp_path / "reference.pids"))
        hits = [line.split() for line in hits_log.read_text(encoding="utf-8").splitlines()]
        mine = [i for i, (name, outstanding) in enumerate(h for h in hits if h[0] == failpoint) if outstanding == "1"]
        assert mine, f"{failpoint} is never reached while a model job is unfinished"
        ordinals = sorted({mine[0], mine[len(mine) // 2], mine[-1]})
        for rep in range(REPS):
            root = ps.crash_project(tmp_path, f"crash-{rep}", api_url=url)
            pidlog = tmp_path / f"crash-{rep}.pids"
            log = tmp_path / f"crash-{rep}.calls"
            result = _driver(root, log, failpoint, skip=ordinals[rep % len(ordinals)])
            assert result.returncode == failpoints.KILL_STATUS, (failpoint, rep, result.stderr)
            assert (osc.normalized(root), ps.extra_state(root)) != (reference, reference_extra), "the kill must land before the work under test is complete"
            if failpoint == failpoints.PROVIDER_AFTER_SPAWN:
                # The transport child exits on its own once its parent's pipe closes, so survival alone cannot show
                # reapability: the spawn record must already exist when the worker dies after the spawn.
                assert list((root / ".recalith" / "run" / "curators").glob("*.json")), "the transport child was spawned without a spawn record"
            restart = _driver(root, log)
            assert restart.returncode == 0, restart.stderr
            assert osc.normalized(root) == reference, (failpoint, rep)
            assert ps.extra_state(root) == reference_extra, (failpoint, rep)
            assert wh_wait(lambda pidlog=pidlog: not _alive_pids(pidlog)), f"a transport child outlived the crashed worker at {failpoint}"
            assert not list((root / ".recalith" / "run" / "curators").glob("*.json"))
            state = ws.state(root)
            assert {s for _, s in state["usage"]} == {"charged"}


def wh_wait(predicate, timeout: float = 15) -> bool:
    import worker_hosts as wh

    return bool(wh.wait_for(predicate, timeout))


# ---------------------------------------------------------------------------
# FailureRecheck, dependency changes and revalidation under kill/restart (Task 10)

# ``planner.after_schedule`` is exercised by the lineage matrix (it settles the merge's revalidation there).
REVISION_MATRIX = [
    failpoints.RECHECK_AFTER_MARK, failpoints.REVALIDATE_AFTER_SETTLE, failpoints.INGEST_BEFORE_COMMIT, failpoints.INGEST_AFTER_COMMIT, failpoints.REVIEW_AFTER_ASSESSMENT, failpoints.REVIEW_AFTER_SCHEDULE, *failpoints.WORKER,
]


@pytest.mark.parametrize("failpoint", REVISION_MATRIX)
def test_revision_crash_matches_reference(tmp_path, failpoint):
    """Killed while ingestion records a FailureRecheck or a dependency change, or while the revalidation and its review apply.

    The spooled segment's passing ``test_mid`` rerun and dependency ``Write``
    mark the admitted lesson (and, transitively, the fact depending on it)
    ``needs_revalidation`` with its counter-observation as context, in the
    ingestion transaction; the passing ``test_long`` rerun defers a recheck of
    the lesson still under review, which its supported review promotes in the
    activation's transaction. The revalidation revises the ``test_mid``
    lesson with a retry condition (reviewed again), keeps the fact and
    retires the ``test_long`` lesson; the planner settles nothing else. The
    reference run logs each failpoint hit with whether any of that work was
    outstanding, owed work without a record included; each repetition kills
    at one of those hits (first, middle, last), the killed store must differ
    from the reference, and the restarted store must equal it: jobs,
    applications, operations, claims (status, freshness, strength, retry
    conditions, context), rechecks and their outcomes, revision audits,
    artifact writes and the guidance epoch.
    """
    import consolidation_scenarios as csc

    reference_root = csc.crash_project(tmp_path, "reference")
    hits_log = tmp_path / "reference.hits"
    counted = _count_hits(reference_root, tmp_path / "reference.calls", hits_log)
    assert counted.returncode == 0, counted.stderr
    reference = (osc.normalized(reference_root), csc.revision_state(reference_root))
    state = reference[1]
    by_text = {c[0]: c for c in state["claims"]}
    assert by_text[csc.CRASH["mid"]][1:5] == ("active", "current", "supported", (csc.RETRY,))
    assert by_text[csc.CRASH["suite"]][1:3] == ("active", "current") and by_text[csc.CRASH["long"]][1] == "archived"
    outcomes = {(c[0], c[1], c[3], c[4]) for c in state["rechecks"]}
    assert (csc.CRASH["mid"], "later_success", "cleared", "revised") in outcomes and (csc.CRASH["mid"], "dependency_changed", "cleared", "revised") in outcomes
    assert (csc.CRASH["suite"], "dependency_changed", "cleared", "kept") in outcomes and (csc.CRASH["long"], "later_success", "cleared", "retired") in outcomes
    hits = [line.split() for line in hits_log.read_text(encoding="utf-8").splitlines()]
    mine = [i for i, (name, outstanding) in enumerate(h for h in hits if h[0] == failpoint) if outstanding == "1"]
    assert mine, f"{failpoint} is never reached while revision work is outstanding"
    ordinals = sorted({mine[0], mine[len(mine) // 2], mine[-1]})
    for rep in range(REPS):
        root = csc.crash_project(tmp_path, f"crash-{rep}")
        log = tmp_path / f"crash-{rep}.calls"
        result = _driver(root, log, failpoint, skip=ordinals[rep % len(ordinals)])
        assert result.returncode == failpoints.KILL_STATUS, (failpoint, rep, result.stderr)
        assert (osc.normalized(root), csc.revision_state(root)) != reference, "the kill must land before the work under test is complete"
        restart = _driver(root, log)
        assert restart.returncode == 0, restart.stderr
        assert osc.normalized(root) == reference[0], (failpoint, rep)
        assert csc.revision_state(root) == reference[1], (failpoint, rep)
        calls = log.read_text(encoding="utf-8").split() if log.exists() else []
        assert max((calls.count(j) for j in set(calls)), default=0) <= 2  # at most the killed launch and one relaunch per model job
        assert {s for _, s in ws.state(root)["usage"]} == {"charged"}


PROJECTION_MATRIX = [*failpoints.RETRIEVAL, failpoints.INGEST_AFTER_COMMIT, failpoints.JOB_BEFORE_COMPLETE_COMMIT, failpoints.JOB_AFTER_COMPLETE]


@pytest.mark.parametrize("failpoint", PROJECTION_MATRIX)
def test_projection_crash_matches_reference(tmp_path, failpoint):
    """Killed while the projection step reindexes or publishes views (or while the work that moves the epochs commits).

    The Task 10 revision scenario, built without any projection: nothing is
    indexed or published when the driver starts, and every application the
    driver runs (FailureRecheck and dependency marking at ingestion, review
    activation, revalidation) advances the guidance epoch again. The reference
    run logs each failpoint hit with whether the index lagged the store
    revision, the views lagged the epochs, or Task 10 work was unfinished;
    each repetition kills at one of those hits (first, middle, last), the
    killed store must differ from the reference, and the restarted store must
    equal it: the Task 10 state, the projection (index terms and documents,
    views and fallback rows with IDs normalized; both current) and the packets
    the service and the hook compile from it for the real ``test_mid`` action.
    """
    import consolidation_scenarios as csc
    import retrieval_scenarios as rsc

    def snapshot(root):
        return (osc.normalized(root), csc.revision_state(root), rsc.projection_state(root), rsc.packets(root))

    reference_root = rsc.crash_project(tmp_path, "reference")
    hits_log = tmp_path / "reference.hits"
    counted = _count_hits(reference_root, tmp_path / "reference.calls", hits_log)
    assert counted.returncode == 0, counted.stderr
    reference = snapshot(reference_root)
    projection = reference[2]
    assert projection["current"] and projection["views"] and projection["terms"] and projection["lookup"] and projection["postings"]
    service_items, source, hook_items = reference[3]
    assert source == "view" and service_items and hook_items  # the final views serve the final state
    hits = [line.split() for line in hits_log.read_text(encoding="utf-8").splitlines()]
    mine = [i for i, (name, outstanding) in enumerate(h for h in hits if h[0] == failpoint) if outstanding == "1"]
    assert mine, f"{failpoint} is never reached while projection work is outstanding"
    ordinals = sorted({mine[0], mine[len(mine) // 2], mine[-1]})
    for rep in range(REPS):
        root = rsc.crash_project(tmp_path, f"crash-{rep}")
        log = tmp_path / f"crash-{rep}.calls"
        result = _driver(root, log, failpoint, skip=ordinals[rep % len(ordinals)])
        assert result.returncode == failpoints.KILL_STATUS, (failpoint, rep, result.stderr)
        assert snapshot(root) != reference, "the kill must land before the work under test is complete"
        restart = _driver(root, log)
        assert restart.returncode == 0, restart.stderr
        got = snapshot(root)
        assert got[0] == reference[0] and got[1] == reference[1], (failpoint, rep)
        assert got[2] == reference[2], (failpoint, rep)
        assert got[3] == reference[3], (failpoint, rep)


SERVICE_MATRIX = [*failpoints.SERVICE, failpoints.REVIEW_AFTER_SCHEDULE]


@pytest.mark.parametrize("failpoint", SERVICE_MATRIX)
def test_service_write_crash_matches_reference(tmp_path, failpoint):
    """Killed inside a guarded operator write (Task 12a), then the operator re-runs the same commands: one effect each.

    The session is a token-provisioned first init of a fresh checkout, a typed
    declaration, a correction of an admitted declaration (real 2.1.301
    lifecycle payloads; the target admitted through a recorded review) and a
    retry of a failed job. The reference run logs every failpoint hit with
    whether some command's effect was still owed (judged from the effects
    themselves: the verifier that verifies the token, the claim citing the
    declaration event and its review, the invalidated target and its
    correction review, the job no longer failed); each repetition kills at one
    of those hits (first, middle, last), the killed state must differ from the
    reference, and after the re-run it must equal it.
    """
    import cli_scenarios as cs

    reference_root = cs.crash_project(tmp_path, "reference")
    hits_log = tmp_path / "reference.hits"
    counted = _count_hits(reference_root, tmp_path / "reference.calls", hits_log)
    assert counted.returncode == 0, counted.stderr
    reference = cs.service_state(reference_root)
    assert reference["init"]["verifies"] and ("operator_correction", 0) in reference["reviews"] and ("typed_declaration", 0) in reference["reviews"]
    hits = [line.split() for line in hits_log.read_text(encoding="utf-8").splitlines()]
    mine = [i for i, (name, owed) in enumerate(h for h in hits if h[0] == failpoint) if owed == "1"]
    assert mine, f"{failpoint} is never reached while an operator command is owed"
    ordinals = sorted({mine[0], mine[len(mine) // 2], mine[-1]})
    for rep in range(REPS):
        root = cs.crash_project(tmp_path, f"crash-{rep}")
        log = tmp_path / f"crash-{rep}.calls"
        result = _driver(root, log, failpoint, skip=ordinals[rep % len(ordinals)])
        assert result.returncode == failpoints.KILL_STATUS, (failpoint, rep, result.stderr)
        assert _comparable(cs.service_state(root)) != _comparable(reference), "the kill must land before the work under test is complete"
        restart = _driver(root, log)
        assert restart.returncode == 0, restart.stderr
        assert _comparable(cs.service_state(root)) == _comparable(reference), (failpoint, rep)


def _comparable(state: dict) -> dict:
    """Event IDs derive from the installation ID: compare kinds and counts, everything else exactly."""
    return {**state, "events": sorted(kind for _event, kind in state["events"])}


DELIVERY_MATRIX = [*failpoints.DELIVERY, failpoints.INGEST_BEFORE_COMMIT, failpoints.INGEST_AFTER_COMMIT]
UNCERTAIN_AFTER_KILL = {failpoints.DELIVERY_AFTER_RESERVE, failpoints.DELIVERY_AFTER_FENCE, failpoints.DELIVERY_AFTER_EMIT}


@pytest.mark.parametrize("failpoint", DELIVERY_MATRIX)
def test_delivery_crash_matches_reference(tmp_path, failpoint):
    """Killed inside a hook's delivery (Task 12b) or the receipt ingestion, then the host goes on and the worker drains.

    The session is a variant host session over real 2.1.301 records with
    delivery enabled in a controlled manifest: start, a prompt, a failing
    ``pytest -q test_mid.py`` (caution, then the overlay failure), its rerun,
    a compaction and its restoration, another prompt. The reference run logs
    every failpoint hit with whether delivery accounting was owed, judged from
    the effects (an unresolved reservation, an attempt with neither a spooled
    receipt nor an accounting row, a receipt not yet accounted), never from a
    scratch flag alone; each repetition kills at one of those hits (first,
    middle, last). The killed state must differ from the reference; after the
    host's remaining hooks and a worker drain the memory state must equal it
    and every accounting invariant must hold: no reservation left, every
    attempt accounted once with its charge, scratch and accounted totals
    equal, no emitted row without stdout, no stdout without a charge, no
    receipt left unaccounted. A hook killed before its receipt was spooled
    leaves an uncertain, still-charged attempt.
    """
    import delivery_scenarios as dsc

    reference_root = dsc.crash_project(tmp_path, "reference")
    hits_log = tmp_path / "reference.hits"
    counted = _count_hits(reference_root, tmp_path / "reference.calls", hits_log)
    assert counted.returncode == 0, counted.stderr
    reference = dsc.delivery_state(reference_root)
    assert reference["hooks_run"] == len(dsc.scenario(reference_root)["script"])
    assert all(v == 0 for v in reference["invariants"].values()), reference["invariants"]
    assert dsc.killed_attempt_states(reference_root).count("emitted") >= 3 and "uncertain" not in dsc.killed_attempt_states(reference_root)
    hits = [line.split() for line in hits_log.read_text(encoding="utf-8").splitlines()]
    mine = [i for i, (name, owed) in enumerate(h for h in hits if h[0] == failpoint) if owed == "1"]
    assert mine, f"{failpoint} is never reached while delivery accounting is owed"
    ordinals = sorted({mine[0], mine[len(mine) // 2], mine[-1]})
    for rep in range(REPS):
        root = dsc.crash_project(tmp_path, f"crash-{rep}")
        log = tmp_path / f"crash-{rep}.calls"
        result = _driver(root, log, failpoint, skip=ordinals[rep % len(ordinals)])
        assert result.returncode == failpoints.KILL_STATUS, (failpoint, rep, result.stderr)
        killed = dsc.delivery_state(root)
        assert killed != reference, "the kill must land before the work under test is complete"
        restart = _driver(root, log)
        assert restart.returncode == 0, restart.stderr
        got = dsc.delivery_state(root)
        assert got["memory"] == reference["memory"], (failpoint, rep)
        assert got["invariants"] == reference["invariants"], (failpoint, rep, got["invariants"])
        states = dsc.killed_attempt_states(root)
        if failpoint in UNCERTAIN_AFTER_KILL:
            assert states.count("uncertain") == 1, (failpoint, rep, states)  # charged, never counted as emitted
        else:
            assert "uncertain" not in states, (failpoint, rep, states)  # the spooled emitted receipt wins


RETENTION_MATRIX = [*failpoints.RETENTION, *failpoints.BACKUP]


@pytest.mark.parametrize("failpoint", RETENTION_MATRIX)
def test_retention_backup_crash_matches_reference(tmp_path, failpoint):
    """Killed inside a backup, the retention sweep or backup retention (Task 15 core), then the operator re-runs what did not complete.

    Real owners over real 2.1.301 payloads (``retention_scenarios.build``) and
    a synthetic tombstone (the ledger has content). The script: a backup taken
    40 days before day 181, the worker at day 181 (a clock ahead of every
    capture; no provider, B1) whose retention step expires the unpinned
    payloads, deletes the aged backup and refreshes the ledger copy, and a
    backup at day 181. A plain reference run gives the expected outcome; a
    counting run of a fresh build logs each failpoint hit with whether work was
    owed, judged from the effects (a payload the reference expired still
    present, the aged backup still on disk or not marked deleted, the new
    backup missing, unrecorded or not verifying by the test's own hashing, a
    staging directory left, the ledger copy behind the store) and never from
    ``retention_state``; each repetition kills at one of those hits (first,
    middle, last). A kill never leaves an output that does not verify, a
    pinned payload gone or a claim changed; after the re-run the state equals
    the reference.
    """
    import retention_scenarios as rsc

    reference_root = rsc.crash_project(tmp_path, "reference")
    plain = _driver(reference_root, tmp_path / "reference.calls")
    assert plain.returncode == 0, plain.stderr
    reference = rsc.retention_state(reference_root)
    expired_keys = [k for k, state, _null in reference["payloads"] if state == "expired"]
    assert expired_keys and reference["audits"] == 2  # one expiry and one record-aging audit (decision 0020)
    assert reference["derived"]["stale_projection_rows"] == reference["derived"]["orphan_links"] == 0 and reference["derived"]["task_bodies"] < rsc.retention_state(rsc.crash_project(tmp_path, "unaged"))["derived"]["task_bodies"]
    assert reference["backups"] == [("new", "verified", 1), ("old", "deleted", 1)] and reference["files"] == {"old": False, "new": True, "partials": 0}
    assert reference["ledger"] == (1, 1) and reference["new_backup"][:2] == (1, 1)
    assert sorted(reference["new_backup"][2]) == sorted((k, s) for k, s, _null in reference["payloads"])  # the new snapshot holds the expiry
    count_root = rsc.crash_project(tmp_path, "count")
    rsc.expect(count_root, expired_keys, reference["derived"])
    hits_log = tmp_path / "count.hits"
    counted = _count_hits(count_root, tmp_path / "count.calls", hits_log)
    assert counted.returncode == 0, counted.stderr
    assert rsc.retention_state(count_root) == reference  # the scenario is deterministic
    hits = [line.split() for line in hits_log.read_text(encoding="utf-8").splitlines()]
    mine = [i for i, (name, owed) in enumerate(h for h in hits if h[0] == failpoint) if owed == "1"]
    assert mine, f"{failpoint} is never reached while retention or backup work is owed"
    ordinals = sorted({mine[0], mine[len(mine) // 2], mine[-1]})
    for rep in range(REPS):
        root = rsc.crash_project(tmp_path, f"crash-{rep}")
        rsc.expect(root, expired_keys, reference["derived"])
        log = tmp_path / f"crash-{rep}.calls"
        result = _driver(root, log, failpoint, skip=ordinals[rep % len(ordinals)])
        assert result.returncode == failpoints.KILL_STATUS, (failpoint, rep, result.stderr)
        assert rsc.retention_state(root) != reference, "the kill must land before the work under test is complete"
        assert rsc.kill_invariants(root, reference) == [], (failpoint, rep)
        restart = _driver(root, log)
        assert restart.returncode == 0, restart.stderr
        assert rsc.retention_state(root) == reference, (failpoint, rep)


FORGET_MATRIX = [*failpoints.FORGET, *failpoints.RESTORE]


@pytest.mark.parametrize("failpoint", FORGET_MATRIX)
def test_forget_restore_crash_matches_reference(tmp_path, failpoint):
    """Killed inside a forget's phases or a restore (Task 16), then the operator re-runs what did not complete.

    Real payloads and recorded proposals (``forget_scenarios.build`` with
    delivery), a recorded backup before the forget, an operator's external copy
    of it and a prompt of the forgotten session still in the spool. The script:
    recovery of an interrupted restore (as the worker's start does), the guarded
    forget of the task by its preview digest (a re-run resumes its persisted
    operation), a worker drain, the restore of the external copy unless the store
    already holds its audit, a drain. A plain reference run gives the outcome; a
    counting run of a fresh build logs each hit with whether work was owed,
    judged from the effects (no tombstone, the marker text anywhere under
    ``.recalith``, the older backup on disk or not marked deleted, no
    post-forget backup verifying by the test's own hashing, the ledger copy
    behind the store, the maintenance marker, a restore journal or staged file,
    no restore audit, no reconstruction job), never from ``privacy_operations``;
    each repetition kills at one of those hits (first, middle, last). After any
    kill no forgotten text remains in the live store, the spool or the scratch
    once the purge committed, and every post-forget backup verifies; after the
    re-run the state equals the reference.
    """
    import forget_scenarios as fsc

    reference_root = fsc.crash_project(tmp_path, "reference")
    plain = _driver(reference_root, tmp_path / "reference.calls")
    assert plain.returncode == 0, plain.stderr
    reference = fsc.forget_state(reference_root)
    assert reference["files"]["marker"] == [] and reference["files"]["maintenance"] is False and reference["files"]["journal"] is False
    assert reference["audits"] == {"forget": 1, "restore": 1} and reference["privacy"] == ["completed"] and reference["reconstruct"] == 1
    assert ("old", "deleted") in reference["backups"] and ("forget", "verified") in reference["backups"] and reference["files"]["forget_backups"] == [True]
    assert reference["heads"]["decl"][0] == "forgotten" and reference["heads"]["multi"][0] == "quarantined" and reference["heads"]["lesson"][0] == "active"
    assert reference["ledger"] == (1, 1) and reference["tombstone_epoch"] == 1
    count_root = fsc.crash_project(tmp_path, "count")
    hits_log = tmp_path / "count.hits"
    counted = _count_hits(count_root, tmp_path / "count.calls", hits_log)
    assert counted.returncode == 0, counted.stderr
    assert fsc.forget_state(count_root) == reference  # the scenario is deterministic
    hits = [line.split() for line in hits_log.read_text(encoding="utf-8").splitlines()]
    mine = [i for i, (name, owed) in enumerate(h for h in hits if h[0] == failpoint) if owed == "1"]
    assert mine, f"{failpoint} is never reached while forget or restore work is owed"
    ordinals = sorted({mine[0], mine[len(mine) // 2], mine[-1]})
    for rep in range(REPS):
        root = fsc.crash_project(tmp_path, f"crash-{rep}")
        log = tmp_path / f"crash-{rep}.calls"
        result = _driver(root, log, failpoint, skip=ordinals[rep % len(ordinals)])
        assert result.returncode == failpoints.KILL_STATUS, (failpoint, rep, result.stderr)
        assert fsc.forget_state(root) != reference, "the kill must land before the work under test is complete"
        assert fsc.kill_invariants(root) == [], (failpoint, rep)
        restart = _driver(root, log)
        assert restart.returncode == 0, restart.stderr
        assert fsc.forget_state(root) == reference, (failpoint, rep)


CHAIN_MATRIX = [*failpoints.CHAIN, *failpoints.WORKER]


@pytest.mark.parametrize("failpoint", CHAIN_MATRIX)
def test_full_profile_chain_crash_matches_reference(tmp_path, monkeypatch, failpoint):
    """Full profile (decision 0024): killed while sealing a chain entry or at a worker boundary, then restarted.

    The Task 5 kill/restart scenario (real captured events, real operations,
    worker-written claim/task/episode revisions) in a ``release_profile: full``
    store. ``chain.before_seal`` falls after a transaction's rows are written
    and before its chain entry; ``chain.after_seal`` after the entry, before
    the commit. Chain kills are spread evenly over every chained transaction a
    counting run of the same driver hits; worker kills use the worker family's
    hits. After the restart the store equals the full-profile reference, and
    the chain is contiguous, ends at the store's revision and verifies over
    every current row.
    """
    import claude_fixtures as cf
    from recalith.storage import integrity

    monkeypatch.setattr(cf, "RELEASE_PROFILE", "full")
    reference_root = osc.crash_project(tmp_path, "reference")
    assert _driver(reference_root, tmp_path / "reference.calls").returncode == 0
    reference = osc.normalized(reference_root)
    assert reference["applications"] == REFERENCE_APPLICATIONS
    assert reference["counts"].pop("revision_chain") > 0
    assert integrity.verify(ws.context(reference_root), full=True)["state"] == "verified"
    ordinals = [0, 1, 2]
    if failpoint in failpoints.CHAIN:
        count_root = osc.crash_project(tmp_path, "count")
        hits_log = tmp_path / "count.hits"
        counted = _count_hits(count_root, tmp_path / "count.calls", hits_log)
        assert counted.returncode == 0, counted.stderr
        n = sum(1 for line in hits_log.read_text(encoding="utf-8").splitlines() if line.split()[0] == failpoint)
        assert n >= 3, f"{failpoint} is reached {n} times"
        spread = max(3, min(REPS, n))
        ordinals = sorted({round(k * (n - 1) / (spread - 1)) for k in range(spread)})
    crashed = 0
    for rep in range(REPS):
        root = osc.crash_project(tmp_path, f"crash-{rep}")
        log = tmp_path / f"crash-{rep}.calls"
        result = _driver(root, log, failpoint, skip=ordinals[rep % len(ordinals)])
        if result.returncode == failpoints.KILL_STATUS:
            crashed += 1
            restart = _driver(root, log)
            assert restart.returncode == 0, restart.stderr
        else:
            assert result.returncode == 0, result.stderr
        state = osc.normalized(root)
        assert state["counts"].pop("revision_chain") > 0
        assert state == reference, (failpoint, rep)
        report = integrity.verify(ws.context(root), full=True)
        assert report["state"] == "verified" and report["complete_coverage"] is True, (failpoint, rep, report["findings"])
        with db.open_store(ws.context(root), readonly=True) as store, store.read() as view:
            sequences = [r[0] for r in view.execute("SELECT sequence FROM revision_chain ORDER BY sequence").fetchall()]
            last = json.loads(view.execute("SELECT row_digests FROM revision_chain ORDER BY sequence DESC LIMIT 1").fetchone()[0])
            revision = store.meta().store_revision
        assert sequences == list(range(1, len(sequences) + 1)) and last["store_revision"] == revision
    assert crashed >= max(1, REPS // 2), f"{failpoint} was not reached often enough to test it"


CAPSULE_MATRIX = [*failpoints.CAPSULE, *failpoints.RETENTION, *failpoints.CHAIN]


@pytest.mark.parametrize("failpoint", CAPSULE_MATRIX)
def test_full_profile_capsule_crash_matches_reference(tmp_path, monkeypatch, failpoint):
    """Full profile (decision 0025): killed around a capsule compaction, the retention sweep or a chain seal, then re-run.

    The Task 15 kill/restart scenario in a ``release_profile: full`` store with
    the capsule owners (``retention_scenarios.capsule_owners``: the A55 quote,
    a located Edit quote, a typed exit-code mapping, the whole declaration and
    the typed statement). The day-181 retention step expires the unpinned
    payloads and compacts the pinned ones a capsule keeps exactly. Counting and
    kill selection follow the retention family (owed judged from effects,
    including a payload the reference compacted still available). After a kill
    no pinned payload is gone, no claim changed, every live claim's evidence
    still resolves and the chain verifies; after the re-run the store equals
    the full-profile reference and the chain verifies over every current row.
    """
    import claude_fixtures as cf
    import retention_scenarios as rsc
    from recalith.storage import integrity

    monkeypatch.setattr(cf, "RELEASE_PROFILE", "full")
    reference_root = rsc.crash_project(tmp_path, "reference", capsules=True)
    plain = _driver(reference_root, tmp_path / "reference.calls")
    assert plain.returncode == 0, plain.stderr
    reference = rsc.retention_state(reference_root)
    expired_keys = [k for k, state, _null in reference["payloads"] if state == "expired"]
    capsule_keys = [k for k, state, _null in reference["payloads"] if state == "capsule_only"]
    assert expired_keys and len(capsule_keys) == len(reference["capsules"]) >= 5 and all(sealed for _k, sealed, _s in reference["capsules"])
    assert reference["redirected_links"] >= 4 and reference["capsule_audits"] == 1 and all(ok for _p, ok in reference["evidence"])
    assert reference["backups"] == [("new", "verified", 1), ("old", "deleted", 1)] and reference["files"] == {"old": False, "new": True, "partials": 0}
    assert sorted(reference["new_backup"][2]) == sorted((k, s) for k, s, _null in reference["payloads"])  # the new snapshot holds the capsules' states
    assert integrity.verify(ws.context(reference_root), full=True)["state"] == "verified"
    count_root = rsc.crash_project(tmp_path, "count", capsules=True)
    rsc.expect(count_root, expired_keys, reference["derived"], capsule_keys)
    hits_log = tmp_path / "count.hits"
    counted = _count_hits(count_root, tmp_path / "count.calls", hits_log)
    assert counted.returncode == 0, counted.stderr
    assert rsc.retention_state(count_root) == reference  # the scenario is deterministic
    hits = [line.split() for line in hits_log.read_text(encoding="utf-8").splitlines()]
    mine = [i for i, (name, owed) in enumerate(h for h in hits if h[0] == failpoint) if owed == "1"]
    assert mine, f"{failpoint} is never reached while retention, capsule or backup work is owed"
    ordinals = sorted({mine[0], mine[len(mine) // 2], mine[-1]})
    for rep in range(REPS):
        root = rsc.crash_project(tmp_path, f"crash-{rep}", capsules=True)
        rsc.expect(root, expired_keys, reference["derived"], capsule_keys)
        log = tmp_path / f"crash-{rep}.calls"
        result = _driver(root, log, failpoint, skip=ordinals[rep % len(ordinals)])
        assert result.returncode == failpoints.KILL_STATUS, (failpoint, rep, result.stderr)
        assert rsc.retention_state(root) != reference, "the kill must land before the work under test is complete"
        assert rsc.kill_invariants(root, reference) == [], (failpoint, rep)
        killed = integrity.verify(ws.context(root), full=True)
        assert killed["state"] == "verified", (failpoint, rep, killed["findings"])  # rows and their entry commit together or not at all
        restart = _driver(root, log)
        assert restart.returncode == 0, restart.stderr
        assert rsc.retention_state(root) == reference, (failpoint, rep)
        report = integrity.verify(ws.context(root), full=True)
        assert report["state"] == "verified" and report["complete_coverage"] is True, (failpoint, rep, report["findings"])


UPGRADE_MATRIX = [*failpoints.UPGRADE, failpoints.BACKUP_AFTER_SNAPSHOT, failpoints.BACKUP_AFTER_MANIFEST, failpoints.BACKUP_AFTER_PUBLISH, failpoints.BACKUP_AFTER_RECORD, *failpoints.CHAIN]


@pytest.mark.parametrize("failpoint", UPGRADE_MATRIX)
def test_profile_transition_crash_matches_reference(tmp_path, failpoint):
    """Task 17 full (decision 0026): killed around the preview-to-full transition or the first full-profile drain, then restarted.

    The scenario (``upgrade_scenarios.crash_project``): a preview store with
    every A35 live owner and the capsule owners, a real forget made before the
    transition, the operator's transition at day 181 (its verified backup,
    capability registration, staged activation transaction with the chain's
    activation baseline, exact capsules or retained pins, staged file, journal,
    swap and record), then the worker's drain at day 181 under the full
    profile. A restart is the worker's recovery, the operator's command again
    when the store is not yet full, and the drain. Kills land only where
    transition or post-transition work is owed, judged from effects (store and
    ``project.toml`` profile, the maintenance marker, staged files, payloads the
    reference expired or compacted). After a kill only the complete previous
    preview state or a complete, verifying full store serves, with the forget's
    tombstones; after the restart the store equals the reference and the chain
    verifies over every current row.
    """
    import upgrade_scenarios as usc
    from recalith.storage import integrity

    reference_root = usc.crash_project(tmp_path, "reference")
    plain = _driver(reference_root, tmp_path / "reference.calls")
    assert plain.returncode == 0, plain.stderr
    reference = usc.semantic(reference_root, portable=True)
    assert (reference["profile"], reference["project_toml"], reference["transitions"]) == ("full", "full", 1)
    assert len(reference["capsules"]) >= 5 and all(ok for _p, ok in reference["evidence"]) and reference["tombstones"] >= 1
    assert usc.leftovers(reference_root) == [] and any(s == "expired" for _k, s in reference["payloads"])
    assert integrity.verify(ws.context(reference_root), full=True)["state"] == "verified"
    count_root = usc.crash_project(tmp_path, "count")
    usc.expect(count_root, reference)
    hits_log = tmp_path / "count.hits"
    counted = _count_hits(count_root, tmp_path / "count.calls", hits_log)
    assert counted.returncode == 0, counted.stderr
    assert usc.semantic(count_root, portable=True) == reference  # the scenario is deterministic
    hits = [line.split() for line in hits_log.read_text(encoding="utf-8").splitlines()]
    mine = [i for i, (name, owed) in enumerate(h for h in hits if h[0] == failpoint) if owed == "1"]
    assert mine, f"{failpoint} is never reached while transition work is owed"
    ordinals = sorted({mine[0], mine[len(mine) // 2], mine[-1]})
    for rep in range(REPS):
        root = usc.crash_project(tmp_path, f"crash-{rep}")
        usc.expect(root, reference)
        log = tmp_path / f"crash-{rep}.calls"
        result = _driver(root, log, failpoint, skip=ordinals[rep % len(ordinals)])
        assert result.returncode == failpoints.KILL_STATUS, (failpoint, rep, result.stderr)
        assert usc.semantic(root, portable=True) != reference or usc.leftovers(root), "the kill must land before the work under test is complete"
        assert usc.kill_invariants(root, usc.scenario(root)) == [], (failpoint, rep)
        restart = _driver(root, log)
        assert restart.returncode == 0, restart.stderr
        assert usc.semantic(root, portable=True) == reference, (failpoint, rep)
        assert usc.leftovers(root) == []
        report = integrity.verify(ws.context(root), full=True)
        assert report["state"] == "verified" and report["complete_coverage"] is True, (failpoint, rep, report["findings"])
