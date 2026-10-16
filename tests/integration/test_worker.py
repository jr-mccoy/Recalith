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

import pytest

import operation_scenarios as osc
import worker_scenarios as ws
from recalith.capture import pipeline
from recalith.contracts.common import RecordRef, digest_of, utc_now
from recalith.contracts.config import MODEL_INPUT_CAP, BudgetConfig, ProjectConfig
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
    seed_reservations(root, "update_task", 18, input_estimate=32_768)
    seed_reservations(root, "update_task", 1, input_estimate=600_000 - 18 * 32_768)  # 600,000 ordinary input used
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
    reviews = seed_reservations(root, "review_claims", 20)  # 60,000 protected output: exhausted
    assert all(r.protected.output_estimate == 3000 and r.ordinary.output_estimate == 0 for r in reviews)
    borrowed = seed_reservations(root, "review_claims", 1, now="2026-10-16T09:00:00.000000Z")[0]
    assert borrowed.protected.invocations == 1 and borrowed.protected.output_estimate == 0 and borrowed.ordinary.output_estimate == 3000
    seed_reservations(root, "revalidate", 9)  # protected invocations: 30 used
    after = seed_reservations(root, "review_claims", 1)[0]
    assert after.protected.invocations == 0 and after.ordinary.invocations == 1  # the invocation itself is borrowed
    # Ordinary capacity is finite too: once it is gone, review waits like anything else.
    seed_reservations(root, "extract_claims", 13)  # 104,000 + 2×3,000 borrowed = 110,000 of 120,000 ordinary output
    seed_reservations(root, "review_claims", 3)
    last = seed_reservations(root, "review_claims", 1)[0]
    assert isinstance(last, budgets.Refusal) and last.reason == "budget_exhausted:protected+ordinary.output_estimate"


def test_48_call_full_reservation_arithmetic(root):
    """Twelve 8,000 + sixteen 1,500 ordinary and twenty 3,000 protected reservations fill both output pools."""
    made = seed_reservations(root, "extract_claims", 12) + seed_reservations(root, "update_task", 16) + seed_reservations(root, "review_claims", 20)
    assert all(isinstance(r, BudgetReservation) for r in made) and len(made) == 48
    assert all(r.max_response_body_bytes == 3 * r.estimated_output_limit and r.max_wire_stdout_bytes == 262_144 and r.max_stderr_bytes == 65_536 for r in made)
    for purpose, reason in (("extract_claims", "ordinary.output_estimate"), ("update_task", "ordinary.output_estimate"), ("review_claims", "protected+ordinary.output_estimate"), ("revalidate", "protected+ordinary.output_estimate")):
        refusal = seed_reservations(root, purpose, 1)[0]
        assert isinstance(refusal, budgets.Refusal) and refusal.reason == f"budget_exhausted:{reason}", purpose
    with db.open_store(ws.context(root), readonly=True) as store, store.read() as view:
        summary = budgets.summary(view, "2026-10-16", BudgetConfig())
    remaining_calls = summary["pools"]["ordinary"]["remaining"]["invocations"] + summary["pools"]["protected"]["remaining"]["invocations"]
    assert remaining_calls == 42  # 90 is only the call ceiling
    assert summary["pools"]["ordinary"]["exhausted"] == ["output_estimate"] and summary["pools"]["protected"]["exhausted"] == ["output_estimate"]
    assert summary["per_purpose"]["extract_claims"] == {"calls": 12, "input_estimate": 1200, "output_estimate": 96_000}
    # A smaller known usage releases capacity; unknown interrupted usage keeps it.
    from recalith.contracts.jobs import LocalUsage
    from recalith.contracts.operations import UsageReport

    with db.open_store(ws.context(root)) as store, store.transaction() as txn:
        budgets.charge(txn, made[0].reservation_id, reported=UsageReport(input_tokens=90, output_tokens=2000, estimated_input_tokens=100, estimated_output_tokens=2100, provider_request_id=None, duration_ms=5), local=LocalUsage(input_estimate=100, output_estimate=2100))
        budgets.charge(txn, made[1].reservation_id, reported=None, local=None)
    assert isinstance(seed_reservations(root, "update_task", 1)[0], BudgetReservation)  # 6,000 released
    assert isinstance(seed_reservations(root, "update_task", 4)[-1], budgets.Refusal)  # the interrupted one released nothing


def test_input_estimate_limits_and_model_input_cap(root):
    """Input pools bound calls too; one request is capped at 96 KiB serialized (32,768 estimates)."""
    assert budgets.MAX_INPUT_ESTIMATE == 32_768
    made = seed_reservations(root, "update_task", 19, input_estimate=32_768)
    assert all(isinstance(r, BudgetReservation) for r in made[:18])
    assert isinstance(made[18], budgets.Refusal) and made[18].reason == "budget_exhausted:ordinary.input_estimate"
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
    seed_reservations(root, "revalidate", 30, config=config)
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


def test_five_candidates_use_one_review_call(root):
    """One extraction plus one fitting review batch is two calls: one ordinary, one protected."""
    candidates = [jobs.ReviewCandidate(claim_id=f"claim_{i}", origin="extracted", claim_kind="fact") for i in range(5)]
    batches = jobs.plan_review_batches(candidates)
    assert len(batches) == 1
    extraction = ws.enqueue_model_job(root, "extract_claims", key="origin")
    review = ws.enqueue_model_job(root, "review_claims", key="batch", candidates=batches[0])
    backend = ws.FakeBackend()
    w = make_worker(root, backend)
    while w.lane.step():
        pass
    assert sorted(j for _, j in backend.calls) == sorted([extraction, review])
    used = reservations(root)
    assert [(r.purpose, r.ordinary.invocations, r.protected.invocations) for r in used] == [("review_claims", 0, 1), ("extract_claims", 1, 0)]
    pytest.xfail("incomplete until Task 9: ReviewBatch persistence, candidate claims and assessment application are not built; only the scheduling/budget mechanics ran")


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
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and _ingested(replayer.root)[1] == 0:
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


def test_budget_exhaustion_blocks_launch_but_not_capture(tmp_path):
    """A31: no new invocation starts; capture and deterministic ingestion still work."""
    import claude_fixtures as cf

    replayer = cf.Replay(tmp_path / "replay")
    ctx = replayer.ctx
    clock = ws.FakeClock(utc_now())  # ingestion stamps real time; the fake clock starts there
    seed_reservations(replayer.root, "update_task", 60, now=clock.now())  # all 60 ordinary invocations
    with db.open_store(ctx) as store, store.transaction() as txn:
        job_id, _ = jobs.enqueue(txn, kind="extract_claims", input_refs=[RecordRef(kind="claim", id=f"claim_{digest_of('x')}", revision=1)], now=clock.now(), prompt_version="test@1")
    backend = ws.FakeBackend()
    w = worker.Worker(ctx, clock=clock, config=ProjectConfig.defaults_for(cf.PROJECT_ID), model=ws.runtime(backend))
    _capture_lifecycle(replayer, tmp_path)
    clock.advance(1)
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
    assert len(backend.calls) == 6 and sorted(j for p, j in backend.calls if p == "extract_claims") == sorted(extractions)
    with db.open_store(ws.context(root), readonly=True) as store, store.read() as view:
        states = view.execute("SELECT kind, state, COUNT(*) FROM jobs WHERE kind IN ('revalidate', 'maintenance') GROUP BY kind, state").fetchall()
        days = {r[0] for r in view.execute("SELECT utc_day FROM provider_usage").fetchall()}
    assert sorted(states) == [("maintenance", "completed", 2), ("revalidate", "cancelled", 9), ("revalidate", "completed", 1)]
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


REFERENCE_APPLICATIONS = ["build_episode", "extract_claims", "review_claims", "service", "update_task"]


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
