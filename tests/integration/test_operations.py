"""Task 5: mutation application and optimistic concurrency (A14, A19–A21, A41; review focus 1).

Every test applies real operations in real transactions against a real store
whose events were captured from the sanitized Claude Code 2.1.301 lifecycle
fixture. Proposals are persisted under a real lease before application; the
worker tests drive the real model lane with a fake provider backend (Task 7
owns the real one). Nothing here mocks admission, storage or application.
"""

from __future__ import annotations

import hashlib
import threading
import time

import pytest

import operation_scenarios as osc
import worker_scenarios as ws
from recalith.contracts.common import Actor, RecordRef, derived_id, new_id
from recalith.contracts.config import BudgetConfig
from recalith.contracts.memory import TaskState
from recalith.contracts.operations import ProposedOperation
from recalith.controller import admission, apply, budgets, jobs, worker
from recalith.core import policy
from recalith.errors import RecalithError
from recalith.storage import db, failpoints, records

LATER = "2026-10-16T08:00:05.000000Z"


@pytest.fixture(autouse=True)
def _disarm():
    failpoints.disarm_all()
    yield
    failpoints.disarm_all()


@pytest.fixture
def root(tmp_path):
    return osc.project(tmp_path)


def ops(*items):
    return [ProposedOperation.model_validate(item) for item in items]


def seed_claim(root, proposition=osc.ORIGINAL, *, basis="inferred", role="fail") -> RecordRef:
    """An operator-submitted candidate claim (a real service write)."""
    result = apply.apply_operations(
        osc.operator(root), ops(osc.op("seed", "propose_claim", osc.claim(proposition, basis=basis), evidence=[osc.link(root, role)])),
        read_set=osc.read_set(root), submission_id=new_id("op"), now=ws.START,
    )
    assert [d.outcome for d in result.decisions] == ["candidate_only"]
    return result.changed_refs[0]


def run_job(root, kind, op_list, *, input_refs=None, read_set=None, purpose=None, now=LATER, persist_now=None):
    """Lease a job, persist the proposal under its fence, apply it; returns (job, response, result)."""
    job = osc.leased(root, kind, input_refs=input_refs)
    response = osc.response(op_list, purpose=purpose or kind, no_op_reason=None if op_list else "nothing")
    with db.open_store(osc.context(root)) as store:
        apply.persist_proposal(store, job, response, read_set or osc.read_set(root, list(job.input_refs) if input_refs else []), now=persist_now or now)
        result = apply.apply_proposal(osc.context(root), job, response, store=store, now=now)
    return job, response, result


def exhaust_budget(root) -> None:
    """Spend today's whole budget (both pools) in the real ledger."""
    config = BudgetConfig()
    with db.open_store(osc.context(root)) as store, store.transaction() as txn:
        for purpose in ("review_claims", "extract_claims"):
            for i in range(config.daily_invocations + 1):
                if isinstance(budgets.reserve(txn, job_id=derived_id("job", [purpose, i]), purpose=purpose, input_estimate=100, now=LATER, config=config), budgets.Refusal):
                    break
        assert isinstance(budgets.reserve(txn, job_id=new_id("job"), purpose="review_claims", input_estimate=100, now=LATER, config=config), budgets.Refusal)


def job_row(root, job_id):
    with db.open_store(osc.context(root), readonly=True) as store, store.read() as view:
        return jobs.get_job(view, job_id)


# ---------------------------------------------------------------------------
# Idempotency (review focus 1; DATA_CONTRACTS §8)


def test_duplicate_proposal_has_one_effect(root):
    """The same proposal applied twice, and the same claim proposed by another job, add one effect."""
    lesson = osc.op("lesson", "propose_claim", osc.claim(osc.LESSON, basis="observed"), evidence=[osc.link(root, "fail", quote="FAILURES", mapping="tool.exit_code")])
    job, response, first = run_job(root, "extract_claims", [lesson])
    before = osc.meta(root)
    second = apply.apply_proposal(osc.context(root), job, response, now=LATER)
    assert second == first
    assert second.operation_ids == first.operation_ids and second.store_revision == first.store_revision
    assert osc.meta(root) == before  # nothing written, not even bookkeeping
    assert first.operation_ids == [apply.operation_id(job.job_id, apply.proposal_digest(response), "lesson")]  # deterministic
    # A different job proposing the identical claim from the same evidence root: one claim, one support link.
    _job2, _r2, third = run_job(root, "extract_claims", [lesson])
    assert [(d.outcome, d.reason_code) for d in third.decisions] == [("candidate_only", "duplicate_existing")] and third.operation_ids == []
    claim = osc.claim_by_text(root, osc.LESSON)
    assert claim["revision"] == 1 and len(claim["supports"]) == 1
    # Re-attaching support from the same root is a duplicate mention: no new revision, no confirmation.
    ref = osc.head_ref(root, "claim", claim["claim_id"])
    attach = osc.op("again", "attach_evidence", {"claim_ref": ref.model_dump(mode="json"), "relation": "supports"}, evidence=[osc.link(root, "fail")])
    _j, _r, fourth = run_job(root, "extract_claims", [attach])
    assert [(d.outcome, d.reason_code) for d in fourth.decisions] == [("apply", "duplicate_evidence")] and fourth.operation_ids == []
    assert osc.claim_by_text(root, osc.LESSON)["revision"] == 1
    # A genuinely new root is attached once, as a new revision.
    attach_new = osc.op("new", "attach_evidence", {"claim_ref": ref.model_dump(mode="json"), "relation": "supports"}, evidence=[osc.link(root, "ls_fail")])
    _j, _r, fifth = run_job(root, "extract_claims", [attach_new])
    updated = osc.claim_by_text(root, osc.LESSON)
    assert fifth.operation_ids and updated["revision"] == 2 and len(updated["supports"]) == 2
    assert updated["strength"] == "weak" and updated["status"] == "candidate"  # strength/admission are Task 9


def test_apply_requires_the_persisted_proposal(root):
    job = osc.leased(root, "extract_claims")
    response = osc.response([osc.op("lesson", "propose_claim", osc.claim(osc.LESSON), evidence=[osc.link(root, "fail")])])
    with pytest.raises(RecalithError) as refused:
        apply.apply_proposal(osc.context(root), job, response, now=LATER)
    assert refused.value.code == "policy_refused"
    with db.open_store(osc.context(root)) as store:
        apply.persist_proposal(store, job, response, osc.read_set(root), now=LATER)
    other = osc.response([osc.op("other", "propose_claim", osc.claim("Something else."), evidence=[osc.link(root, "fail")])])
    with pytest.raises(RecalithError, match="persisted proposal"):
        apply.apply_proposal(osc.context(root), job, other, now=LATER)
    assert osc.count(root, "SELECT COUNT(*) FROM claim_heads") == 0


# ---------------------------------------------------------------------------
# Atomic groups (SYSTEM_SPEC §10; A14, A19)


def supersession(root, original: RecordRef, *, replacement_link=None):
    return [
        osc.op("replacement", "propose_claim", osc.claim(osc.REPLACEMENT, basis="inferred"), evidence=[replacement_link or osc.link(root, "fail", quote="test_end")]),
        osc.op("retire", "change_claim_status", {"claim_ref": original.model_dump(mode="json"), "status": "superseded", "replacement_local_ref": "replacement"}, depends_on=["replacement"], target=original.model_dump(mode="json")),
    ]


def test_replacement_and_retirement_commit_together(root):
    original = seed_claim(root)
    # An altered quote in the replacement fails the whole group: the old claim is not retired.
    bad = osc.link(root, "fail", quote="test_end", digest=hashlib.sha256(b"test_start").hexdigest())
    _job, _r, rejected = run_job(root, "extract_claims", supersession(root, original, replacement_link=bad), input_refs=[original])
    assert {(d.local_ref, d.reason_code) for d in rejected.decisions} == {("replacement", "quote_mismatch"), ("retire", "group_rejected")}
    assert osc.claim_by_text(root, osc.ORIGINAL)["status"] == "candidate" and osc.count(root, "SELECT COUNT(*) FROM claim_heads") == 1
    # The replacement is written first; the retirement then fails (it cites a never-captured event): the written
    # replacement is rolled back with its group, so no orphan replacement survives either.
    late_failure = supersession(root, original)
    late_failure[1] = {**late_failure[1], "evidence": [osc.missing_event_link()]}
    _job, _r, rolled_back = run_job(root, "extract_claims", late_failure, input_refs=[original])
    assert {(d.local_ref, d.reason_code) for d in rolled_back.decisions} == {("replacement", "group_rejected"), ("retire", "evidence_missing")}
    assert osc.count(root, "SELECT COUNT(*) FROM claim_heads") == 1 and osc.count(root, "SELECT COUNT(*) FROM claim_revisions") == 1
    assert osc.count(root, "SELECT COUNT(*) FROM evidence_links WHERE owner_kind = 'claim'") == 1 and rolled_back.operation_ids == []
    # A failure inside the transaction after the group applied leaves no partial supersession.
    failpoints.arm(failpoints.JOB_BEFORE_COMPLETE_COMMIT, lambda name: (_ for _ in ()).throw(RuntimeError("injected")))
    with pytest.raises(RuntimeError):
        run_job(root, "extract_claims", supersession(root, original), input_refs=[original])
    assert osc.claim_by_text(root, osc.ORIGINAL)["revision"] == 1 and osc.count(root, "SELECT COUNT(*) FROM claim_heads") == 1
    # Applied: replacement creation and supersession share one commit and one atomic group.
    _job, _r, result = run_job(root, "extract_claims", supersession(root, original), input_refs=[original])
    assert [(d.local_ref, d.outcome) for d in result.decisions] == [("replacement", "candidate_only"), ("retire", "apply")]
    old, new = osc.claim_by_text(root, osc.ORIGINAL), osc.claim_by_text(root, osc.REPLACEMENT)
    assert old["status"] == "superseded" and old["superseded_by"] == [{"kind": "claim", "id": new["claim_id"], "revision": 1}]
    assert new["status"] == "candidate" and new["supersedes"] == [{"kind": "claim", "id": original.id, "revision": 1}]
    with db.open_store(osc.context(root), readonly=True) as store, store.read() as view:
        made = {r[0] for r in view.execute("SELECT created_store_revision FROM claim_revisions WHERE (claim_id = ? AND revision = 2) OR claim_id = ?", (original.id, new["claim_id"])).fetchall()}
        groups = {r[0] for r in view.execute("SELECT atomic_group_id FROM operations WHERE operation_id IN (%s)" % ",".join("?" * len(result.operation_ids)), result.operation_ids).fetchall()}  # noqa: S608
        relation = view.execute("SELECT COUNT(*) FROM relations WHERE source_id = ? AND target_id = ? AND relation = 'supersedes'", (new["claim_id"], original.id)).fetchone()[0]
    assert made == {result.store_revision} and len(groups) == 1 and relation == 1


def test_unrelated_group_can_survive_rejection(root, tmp_path):
    """A14: nonexistent, foreign, re-rooted or misquoted evidence and malformed operations fail only their groups."""
    other = osc.project(tmp_path, "other")
    foreign = osc.link(other, "fail")  # a real event of another installation: it does not exist here
    altered = osc.link(root, "prompt", quote="run the scripted tools", digest=hashlib.sha256(b"delete the scripted tools").hexdigest())
    rerooted = {**osc.link(root, "fail"), "root_event_ids": [osc.events(root)["prompt"]["id"]]}
    proposal = [
        osc.op("good", "propose_claim", osc.claim(osc.LESSON), evidence=[osc.link(root, "fail", quote="FAILURES")]),
        osc.op("good_followup", "propose_claim", osc.claim("The ls fixture exits 2.", subject="ls"), depends_on=["good"], evidence=[osc.link(root, "ls_fail")]),
        osc.op("missing", "propose_claim", osc.claim("A never-captured run passed.", subject="ghost"), evidence=[osc.missing_event_link()]),
        osc.op("foreign", "propose_claim", osc.claim("Another project's run failed.", subject="foreign"), evidence=[foreign]),
        osc.op("misquoted", "propose_claim", osc.claim("The user asked to delete the tools.", basis="user_declared", kind="decision", subject="quote"), evidence=[altered]),
        osc.op("rerooted", "propose_claim", osc.claim("Re-rooted support.", subject="roots"), evidence=[rerooted]),
        osc.op("unmapped", "propose_claim", osc.claim("Observed without a mapping.", basis="observed", subject="unmapped"), evidence=[osc.link(root, "fail")]),
        {"local_ref": "broken", "kind": "propose_claim", "payload": {"kind": "fact", "proposition": 7}, "reason": "malformed"},
        osc.op("needs_broken", "propose_claim", osc.claim("Depends on a malformed op.", subject="dep"), depends_on=["broken"], evidence=[osc.link(root, "success")]),
        osc.op("independent", "propose_claim", osc.claim("echo prints hello-fixture.", subject="echo"), evidence=[osc.link(root, "success", quote="hello-fixture")]),
    ]
    response = osc.response(proposal)
    assert [(m.local_ref, m.reason_code) for m in response.malformed] == [("broken", "malformed_operation")]
    _job, _r, result = run_job(root, "extract_claims", proposal)
    reasons = {d.local_ref: (d.outcome, d.reason_code) for d in result.decisions}
    assert reasons == {
        "good": ("candidate_only", "candidate_pending_review"),
        "good_followup": ("candidate_only", "candidate_pending_review"),
        "missing": ("reject", "evidence_missing"),
        "foreign": ("reject", "evidence_missing"),
        "misquoted": ("reject", "quote_mismatch"),
        "rerooted": ("reject", "root_mismatch"),
        "unmapped": ("reject", "observed_requires_mapping"),
        "broken": ("reject", "malformed_operation"),
        "needs_broken": ("reject", "group_rejected"),
        "independent": ("candidate_only", "candidate_pending_review"),
    }
    assert sorted(c["proposition"] for c in osc.claim_heads(root)) == sorted([osc.LESSON, "The ls fixture exits 2.", "echo prints hello-fixture."])
    assert len(result.operation_ids) == 3


def test_malformed_operation_from_the_provider_fails_only_its_group(root):
    """Through the real model lane: a malformed operation is recorded by the adapter, not fatal to the body."""
    job_id = ws.enqueue_model_job(root, "extract_claims", key="malformed")
    body = osc.body([
        {"local_ref": "bad", "kind": "propose_claim", "payload": {"kind": "fact"}, "reason": "x"},
        {"local_ref": "shell", "kind": "update_task", "payload": {"command": "rm -rf ."}, "reason": "x"},
        osc.op("ok", "propose_claim", osc.claim(osc.LESSON), evidence=[osc.link(root, "fail")]),
    ])
    w = worker.Worker(osc.context(root), clock=ws.FakeClock(), model=ws.runtime(ws.FakeBackend(lambda p, i: worker.LaunchOutcome(stdout=ws.envelope(body)))))
    assert w.lane.step()
    assert job_row(root, job_id).state == "completed"
    assert [c["proposition"] for c in osc.claim_heads(root)] == [osc.LESSON]


# ---------------------------------------------------------------------------
# Read sets and stale revisions (A20)


def test_changed_read_set_requeues(root):
    """A20: a consulted file changes during curation; nothing applies and one bounded re-evaluation is queued."""
    source = osc.context(root).workspace_root / "src" / "fixture_app.py"
    source.parent.mkdir(parents=True)
    source.write_text("def run():\n    return 1\n", encoding="utf-8")
    consulted = {"file:src/fixture_app.py": hashlib.sha256(source.read_bytes()).hexdigest()}
    lesson = osc.op("lesson", "propose_claim", osc.claim(osc.LESSON), evidence=[osc.link(root, "fail")])
    job = osc.leased(root, "extract_claims")
    response = osc.response([lesson])
    with db.open_store(osc.context(root)) as store:
        apply.persist_proposal(store, job, response, osc.read_set(root, fingerprints=consulted), now=LATER)
    source.write_text("def run():\n    return 2\n", encoding="utf-8")  # the live file changed while the model ran
    before = osc.meta(root)
    result = apply.apply_proposal(osc.context(root), job, response, now=LATER)
    assert [(d.outcome, d.reason_code) for d in result.decisions] == [("requeue", "fingerprint_changed")]
    assert result.operation_ids == [] and result.changed_refs == [] and len(result.requeued_job_ids) == 1
    assert osc.count(root, "SELECT COUNT(*) FROM claim_heads") == 0
    after = osc.meta(root)
    assert after.guidance_epoch == before.guidance_epoch and after.store_revision == before.store_revision + 1  # bookkeeping only
    old, new = job_row(root, job.job_id), job_row(root, result.requeued_job_ids[0])
    assert (old.state, old.last_error_code) == ("cancelled", apply.REQUEUED)
    assert (new.kind, new.state, new.input_refs) == (job.kind, "pending", job.input_refs)
    assert apply.apply_proposal(osc.context(root), job, response, now=LATER) == result  # duplicate: same result, no second job
    assert osc.count(root, "SELECT COUNT(*) FROM jobs WHERE kind = 'extract_claims'") == 2


def test_changed_consulted_record_requeues_but_unrelated_change_does_not(root):
    consulted, unrelated = seed_claim(root), seed_claim(root, "An unrelated fact.", role="success")
    archive = lambda ref: ops(osc.op("archive", "change_claim_status", {"claim_ref": ref.model_dump(mode="json"), "status": "archived"}))  # noqa: E731
    lesson = osc.op("lesson", "propose_claim", osc.claim(osc.LESSON), evidence=[osc.link(root, "fail")])
    # An unrelated record changes: the proposal still applies.
    job = osc.leased(root, "extract_claims", input_refs=[consulted])
    response = osc.response([lesson])
    with db.open_store(osc.context(root)) as store:
        apply.persist_proposal(store, job, response, osc.read_set(root, [consulted]), now=LATER)
    apply.apply_operations(osc.operator(root), archive(unrelated), read_set=osc.read_set(root), submission_id=new_id("op"), now=LATER)
    assert [d.outcome for d in apply.apply_proposal(osc.context(root), job, response, now=LATER).decisions] == ["candidate_only"]
    # The consulted record changes: requeued, re-evaluation names its current revision.
    job2 = osc.leased(root, "extract_claims", input_refs=[consulted])
    response2 = osc.response([osc.op("lesson2", "propose_claim", osc.claim("Another lesson.", subject="other"), evidence=[osc.link(root, "fail")])])
    with db.open_store(osc.context(root)) as store:
        apply.persist_proposal(store, job2, response2, osc.read_set(root, [consulted]), now=LATER)
    apply.apply_operations(osc.operator(root), archive(consulted), read_set=osc.read_set(root), submission_id=new_id("op"), now=LATER)
    result = apply.apply_proposal(osc.context(root), job2, response2, now=LATER)
    assert [d.reason_code for d in result.decisions] == ["read_set_changed"]
    assert job_row(root, result.requeued_job_ids[0]).input_refs == [RecordRef(kind="claim", id=consulted.id, revision=2)]


def test_stale_target_revision_never_overwrites(root):
    """An operation naming an old revision requeues the proposal (job) or fails atomically (service writer)."""
    target = seed_claim(root)
    apply.apply_operations(osc.operator(root), ops(osc.op("archive", "change_claim_status", {"claim_ref": target.model_dump(mode="json"), "status": "archived"})), read_set=osc.read_set(root), submission_id=new_id("op"), now=LATER)
    revise = osc.op("revise", "revise_claim", {"claim_ref": target.model_dump(mode="json"), "proposition": "Overwritten text."}, target=target.model_dump(mode="json"))
    good = osc.op("good", "propose_claim", osc.claim(osc.LESSON), evidence=[osc.link(root, "fail")])
    _job, _r, result = run_job(root, "revalidate", [good, revise], purpose="revalidate")
    assert {d.outcome for d in result.decisions} == {"requeue"} and result.requeued_job_ids
    assert osc.claim_by_text(root, osc.ORIGINAL)["status"] == "archived"  # not overwritten
    assert osc.count(root, "SELECT COUNT(*) FROM claim_heads") == 1  # and nothing else from that proposal applied
    with pytest.raises(RecalithError) as stale:
        apply.apply_operations(osc.operator(root), ops(good, revise), read_set=osc.read_set(root), submission_id=new_id("op"), now=LATER)
    assert stale.value.code == "revision_conflict" and osc.count(root, "SELECT COUNT(*) FROM claim_heads") == 1


def test_reevaluation_is_bounded(root):
    """Each conflict requeues once; after REEVALUATION_LIMIT re-evaluations the chain fails visibly."""
    task = RecordRef(kind="task", id=osc.seed_task(root), revision=1)
    job = osc.leased(root, "update_task", input_refs=[task])
    chain = [job.job_id]
    for depth in range(policy.REEVALUATION_LIMIT + 1):
        current = osc.head_ref(root, "task", task.id)
        patch = osc.op("touch", "update_task", {"task_id": task.id, "expected_revision": current.revision, "patches": [{"op": "set", "field": "title", "value": f"title {depth}"}]})
        response = osc.response([patch], purpose="update_task")
        with db.open_store(osc.context(root)) as store:
            apply.persist_proposal(store, job, response, osc.read_set(root, [current]), now=LATER)
        # A concurrent typed update moves the task before the proposal applies.
        with db.open_store(osc.context(root)) as store, store.transaction() as txn:
            revision, data = apply._head_body(txn, "task", task.id)
            records.write_task(txn, TaskState.model_validate({**data, "revision": revision + 1}), workspace_id=osc.context(root).workspace_id)
            txn.mutated(serving_relevant=True)
        result = apply.apply_proposal(osc.context(root), job, response, now=LATER)
        if depth < policy.REEVALUATION_LIMIT:
            assert [d.reason_code for d in result.decisions] == ["read_set_changed"] and len(result.requeued_job_ids) == 1
            job = osc_lease(root, result.requeued_job_ids[0])
            chain.append(job.job_id)
        else:
            assert [(d.outcome, d.reason_code) for d in result.decisions] == [("reject", "reevaluation_limit")] and not result.requeued_job_ids
            final = job_row(root, job.job_id)
            assert (final.state, final.last_error_code) == ("failed", "reevaluation_limit")
    assert len(chain) == policy.REEVALUATION_LIMIT + 1
    assert osc.head_ref(root, "task", task.id).revision == 1 + policy.REEVALUATION_LIMIT + 1  # only the concurrent updates landed


def osc_lease(root, job_id):
    ctx = osc.context(root)
    with db.open_store(ctx) as store:
        job = jobs.lease_next(ctx, owner="worker-test", now=LATER, kinds=["update_task"], store=store)
    assert job is not None and job.job_id == job_id
    return job


def test_expired_lease_applies_nothing_and_newer_applies_once(root):
    """A21 with real operations: the late result of a superseded lease never applies."""
    lesson = osc.op("lesson", "propose_claim", osc.claim(osc.LESSON), evidence=[osc.link(root, "fail")])
    ctx = osc.context(root)
    job = osc.leased(root, "extract_claims")
    response = osc.response([lesson])
    with db.open_store(ctx) as store:
        apply.persist_proposal(store, job, response, osc.read_set(root), now=ws.START)
        later = jobs._plus(job.lease_until, 1)
        newer = jobs.lease_next(ctx, owner="worker-b", now=later, kinds=["extract_claims"], store=store)
        with pytest.raises(RecalithError, match="lease fenced"):
            apply.apply_proposal(ctx, job, response, store=store, now=later)
        assert osc.count(root, "SELECT COUNT(*) FROM claim_heads") == 0
        result = apply.apply_proposal(ctx, newer, response, store=store, now=later)  # the persisted proposal; no new model call
        assert apply.apply_proposal(ctx, job, response, store=store, now=later) == result
    assert osc.count(root, "SELECT COUNT(*) FROM claim_heads") == 1 and osc.count(root, "SELECT COUNT(*) FROM operations WHERE kind = 'apply_proposal'") == 1


# ---------------------------------------------------------------------------
# Epochs and concurrency (SYSTEM_SPEC §5.1.1; A41)


def test_bookkeeping_does_not_advance_guidance_epoch(root):
    start = osc.meta(root)
    job, _r, noop = run_job(root, "extract_claims", [])
    after_noop = osc.meta(root)
    assert noop.decisions == [] and after_noop.guidance_epoch == start.guidance_epoch and after_noop.store_revision > start.store_revision
    _j, _r, made = run_job(root, "extract_claims", [osc.op("lesson", "propose_claim", osc.claim(osc.LESSON), evidence=[osc.link(root, "fail")])])
    after_claim = osc.meta(root)
    assert after_claim.guidance_epoch == after_noop.guidance_epoch + 1 and made.store_revision == after_claim.store_revision
    # A requeue, a lease and a rejected-only proposal are bookkeeping too.
    _j, _r, rejected = run_job(root, "extract_claims", [osc.op("ghost", "propose_claim", osc.claim("ghost"), evidence=[osc.missing_event_link()])])
    assert [d.outcome for d in rejected.decisions] == ["reject"] and osc.meta(root).guidance_epoch == after_claim.guidance_epoch


def test_worker_and_service_writer_keep_consistent_revisions(root):
    """A41: worker applications and service writes interleave; revisions stay gapless and epochs exact."""
    ctx = osc.context(root)
    targets = [seed_claim(root, f"Service-owned fact {i}.", role="success") for i in range(6)]
    model_jobs = []
    for i in range(6):
        job = osc.leased(root, "extract_claims", owner=f"worker-{i}")
        response = osc.response([osc.op("lesson", "propose_claim", osc.claim(f"Worker lesson {i}.", subject=f"w{i}"), evidence=[osc.link(root, "fail")])])
        with db.open_store(ctx) as store:
            apply.persist_proposal(store, job, response, osc.read_set(root), now=LATER)
        model_jobs.append((job, response))
    start = osc.meta(root)
    errors: list[BaseException] = []
    snapshots: list[tuple[int, list[tuple[int, int]]]] = []

    def retrying(fn):
        for _ in range(200):
            try:
                return fn()
            except RecalithError as exc:
                if exc.code != "storage_failure":
                    raise
                time.sleep(0.005)
        raise AssertionError("store stayed busy")

    def worker_side():
        try:
            with db.open_store(ctx) as store:
                for job, response in model_jobs:
                    retrying(lambda job=job, response=response: apply.apply_proposal(ctx, job, response, store=store, now=LATER))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def service_side():
        try:
            op_ctx = osc.operator(root)
            for ref in targets:
                retrying(lambda ref=ref: apply.apply_operations(op_ctx, ops(osc.op("archive", "change_claim_status", {"claim_ref": ref.model_dump(mode="json"), "status": "archived"})), read_set=osc.read_set(root), submission_id=derived_id("op", [ref.id]), now=LATER))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def reader_side():
        with db.open_store(ctx, readonly=True) as store:
            for _ in range(40):
                with store.read() as view:
                    revision = view.execute("SELECT store_revision FROM installation_meta").fetchone()[0]
                    heads = view.execute("SELECT r.created_store_revision, h.revision FROM claim_heads h JOIN claim_revisions r ON r.claim_id = h.claim_id AND r.revision = h.revision").fetchall()
                snapshots.append((revision, heads))
                time.sleep(0.001)

    threads = [threading.Thread(target=t) for t in (worker_side, service_side, reader_side)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors, errors
    end = osc.meta(root)
    assert end.store_revision == start.store_revision + 12  # one revision per committed transaction, none lost
    assert end.guidance_epoch == start.guidance_epoch + 12  # each was serving-relevant
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        revisions = [r[0] for r in view.execute("SELECT store_revision FROM operations WHERE kind IN ('apply_proposal', 'apply_service') AND store_revision > ? ORDER BY store_revision", (start.store_revision,)).fetchall()]
    assert revisions == list(range(start.store_revision + 1, end.store_revision + 1))  # gapless, unique, monotonic
    for revision, heads in snapshots:  # every snapshot read a consistent store: no head from a later commit
        assert all(created <= revision for created, _ in heads)
    assert {c["status"] for c in osc.claim_heads(root) if c["proposition"].startswith("Service-owned")} == {"archived"}
    assert sum(c["proposition"].startswith("Worker lesson") for c in osc.claim_heads(root)) == 6


def test_concurrent_writer_on_the_consulted_claim_requeues_the_worker(root):
    """A41/A20 interleaving: the service writer wins the consulted claim; the worker's proposal re-evaluates."""
    target = seed_claim(root)
    dispute = osc.op("dispute", "change_claim_status", {"claim_ref": target.model_dump(mode="json"), "status": "disputed"}, evidence=[osc.link(root, "ls_fail", relation="contradicts")])
    job = osc.leased(root, "revalidate", input_refs=[target])
    response = osc.response([dispute], purpose="revalidate")
    with db.open_store(osc.context(root)) as store:
        apply.persist_proposal(store, job, response, osc.read_set(root, [target]), now=LATER)
    apply.apply_operations(osc.operator(root), ops(osc.op("archive", "change_claim_status", {"claim_ref": target.model_dump(mode="json"), "status": "archived"})), read_set=osc.read_set(root), submission_id=new_id("op"), now=LATER)
    result = apply.apply_proposal(osc.context(root), job, response, now=LATER)
    assert {d.outcome for d in result.decisions} == {"requeue"}
    assert osc.claim_by_text(root, osc.ORIGINAL)["status"] == "archived"


# ---------------------------------------------------------------------------
# Correction mechanics (A19; the guarded transport is Task 12a)


def test_correction_invalidates_and_creates_candidate_in_one_transaction(root, tmp_path):
    """With zero model budget the old guidance stops at once; the replacement stays candidate; stale fails atomically."""
    target = seed_claim(root, "Use the scripted tools from the fixture.", basis="user_declared", role="prompt")
    exhaust_budget(root)
    usage_rows = osc.count(root, "SELECT COUNT(*) FROM provider_usage")
    correction = [
        osc.op("invalidate", "change_claim_status", {"claim_ref": target.model_dump(mode="json"), "status": "invalidated"}, evidence=[osc.link(root, "prompt", relation="contradicts", quote="FIXTURE lifecycle")], target=target.model_dump(mode="json")),
        osc.op("replacement", "propose_claim", osc.claim("Run the scripted tools only on request.", basis="user_declared", kind="decision"), depends_on=["invalidate"], evidence=[osc.link(root, "prompt")]),
    ]
    start = osc.meta(root)
    result = apply.apply_operations(osc.operator(root), ops(*correction), read_set=osc.read_set(root, [target]), submission_id=new_id("op"), now=LATER)
    after = osc.meta(root)
    assert after.store_revision == start.store_revision + 1 and after.guidance_epoch == start.guidance_epoch + 1  # one transaction
    assert osc.claim_by_text(root, "Use the scripted tools from the fixture.")["status"] == "invalidated"
    replacement = osc.claim_by_text(root, "Run the scripted tools only on request.")
    assert replacement["status"] == "candidate" and replacement["review_assessment"] is None  # review is still owed (Task 9/10)
    assert osc.count(root, "SELECT COUNT(*) FROM provider_usage") == usage_rows and osc.count(root, "SELECT COUNT(*) FROM jobs WHERE kind != 'ingest'") == 0  # no model call
    assert len(result.operation_ids) == 2
    # The same correction against the old revision is stale: nothing applies.
    before = osc.meta(root)
    with pytest.raises(RecalithError) as stale:
        apply.apply_operations(osc.operator(root), ops(*correction), read_set=osc.read_set(root, [target]), submission_id=new_id("op"), now=LATER)
    assert stale.value.code == "revision_conflict" and osc.meta(root) == before
    # Agents and hooks cannot apply memory operations at all.
    agent = osc.context(root, Actor(kind="host_agent", id="claude", channel="mcp"))
    with pytest.raises(RecalithError, match="policy_refused"):
        apply.apply_operations(agent, ops(*correction), read_set=osc.read_set(root), submission_id=new_id("op"), now=LATER)


# ---------------------------------------------------------------------------
# Task and episode operations


def test_task_and_episode_operations_use_expected_revisions(root):
    task_id = osc.seed_task(root)
    ev = osc.events(root)
    episode = osc.op("episode", "create_episode", {
        "task_id": task_id, "title": "Run the fixture tools", "started_at": ws.START,
        "objective": osc.supported(root, "Run the scripted tools.", role="prompt", quote="run the scripted tools"),
        "steps": [{"ordinal": 0, "action": osc.supported(root, "Ran pytest."), "outcome": "failure"}],
        "outcome": osc.supported(root, "The run failed."), "source_event_ids": [ev["prompt"]["id"], ev["fail"]["id"]],
    })
    _j, _r, created = run_job(root, "build_episode", [episode])
    ep_ref = created.changed_refs[0]
    revise = osc.op("revise", "revise_episode", {"episode_id": ep_ref.id, "expected_revision": 1, "patches": [{"op": "append", "field": "unresolved", "value": osc.supported(root, "Why does test_end fail?", quote="test_end")}]})
    _j, _r, revised = run_job(root, "build_episode", [revise], input_refs=[ep_ref])
    assert revised.changed_refs == [RecordRef(kind="episode", id=ep_ref.id, revision=2)]
    update = osc.op("update", "update_task", {"task_id": task_id, "expected_revision": 1, "patches": [
        {"op": "append", "field": "pending_actions", "value": {"description": osc.supported(root, "Inspect test_end."), "state": "proposed"}},
        {"op": "set", "field": "next_action", "value": osc.supported(root, "Inspect test_end.", quote="test_end")},
    ]})
    _j, _r, updated = run_job(root, "update_task", [update])
    with db.open_store(osc.context(root), readonly=True) as store, store.read() as view:
        state = records.load(view, "task", task_id, 2)
    assert state.pending_actions[0].action_id.startswith("act_") and state.next_action.text == "Inspect test_end."
    # Closing an action by its code-assigned id; a patch that cannot apply fails its group.
    close = osc.op("close", "update_task", {"task_id": task_id, "expected_revision": 2, "patches": [{"op": "close", "field": "pending_actions", "item_id": state.pending_actions[0].action_id}]})
    bad = osc.op("bad", "update_task", {"task_id": task_id, "expected_revision": 2, "patches": [{"op": "set", "field": "plan", "value": "a list cannot be set"}]})
    _j, _r, mixed = run_job(root, "update_task", [close])
    assert [d.outcome for d in mixed.decisions] == ["apply"]
    _j, _r, failed = run_job(root, "update_task", [{**bad, "payload": {**bad["payload"], "expected_revision": 3}}])
    assert [(d.outcome, d.reason_code) for d in failed.decisions] == [("reject", "invalid_result")] and osc.head_ref(root, "task", task_id).revision == 3
    assert updated.decisions[0].outcome == "apply"


def test_evaluate_operation_alone_writes_nothing(root):
    original = seed_claim(root)
    ctx = osc.context(root)
    before = osc.meta(root)
    good = ProposedOperation.model_validate(osc.op("retire", "change_claim_status", {"claim_ref": original.model_dump(mode="json"), "status": "archived"}))
    stale = ProposedOperation.model_validate(osc.op("stale", "revise_claim", {"claim_ref": {**original.model_dump(mode="json"), "revision": 9}, "proposition": "x"}))
    ghost = ProposedOperation.model_validate(osc.op("ghost", "propose_claim", osc.claim("ghost"), evidence=[osc.missing_event_link()]))
    foreign_scope = ProposedOperation.model_validate(osc.op("scope", "propose_claim", osc.claim("scoped", scope={"workspace_ids": [new_id("ws")]}), evidence=[osc.link(root, "fail")]))
    assert admission.evaluate_operation(ctx, good, osc.read_set(root)).outcome == "apply"
    assert admission.evaluate_operation(ctx, stale, osc.read_set(root)).outcome == "requeue"
    assert admission.evaluate_operation(ctx, ghost, osc.read_set(root)).reason_code == "evidence_missing"
    assert admission.evaluate_operation(ctx, foreign_scope, osc.read_set(root)).reason_code == "scope_unregistered"
    assert admission.evaluate_operation(ctx, good, osc.read_set(root).model_copy(update={"tombstone_epoch": 1})).reason_code == "tombstone_epoch_changed"
    assert admission.evaluate_operation(ctx, good, osc.read_set(root, fingerprints={"branch:main": "0" * 64})).reason_code == "read_set_unverifiable"
    # Review focus 4: a fingerprint can name only a file inside the registered workspace root.
    outside = ctx.workspace_root.parent / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    escape = hashlib.sha256(outside.read_bytes()).hexdigest()
    for key in ("file:../outside.txt", f"file:{outside.as_posix()}"):
        assert admission.evaluate_operation(ctx, good, osc.read_set(root, fingerprints={key: escape})).reason_code == "read_set_unverifiable", key
    assert admission.evaluate_operation(osc.context(root, Actor(kind="adapter", id="hook", channel="hook")), good, osc.read_set(root)).reason_code == "kind_not_permitted"
    assert osc.meta(root) == before


# ---------------------------------------------------------------------------
# Compensating undo (SYSTEM_SPEC §10; the guarded CLI is Task 12a)


def test_undo_preview_and_apply_append_compensation(root):
    original = seed_claim(root)
    _j, _r, result = run_job(root, "extract_claims", supersession(root, original), input_refs=[original])
    retire_op = next(d.resolved_operation_id for d in result.decisions if d.local_ref == "retire")
    preview = apply.preview_undo(osc.context(root), retire_op)
    assert preview.state == "clean" and {c.action for c in preview.compensations} == {"restore_fields", "remove_relation"}
    with pytest.raises(RecalithError, match="policy_refused"):
        apply.apply_undo(osc.context(root), retire_op, preview_digest=preview.preview_digest)  # the worker is not an operator
    with pytest.raises(RecalithError, match="revision_conflict"):
        apply.apply_undo(osc.operator(root), retire_op, preview_digest="0" * 64)
    before = osc.meta(root)
    undone = apply.apply_undo(osc.operator(root), retire_op, preview_digest=preview.preview_digest, now=LATER)
    assert apply.apply_undo(osc.operator(root), retire_op, preview_digest=preview.preview_digest, now=LATER) == undone  # once
    old, new = osc.claim_by_text(root, osc.ORIGINAL), osc.claim_by_text(root, osc.REPLACEMENT)
    assert (old["status"], old["revision"], old["superseded_by"]) == ("candidate", 3, [])  # appended, history kept
    assert (new["revision"], new["supersedes"]) == (3, [])
    assert osc.count(root, "SELECT COUNT(*) FROM relations") == 0 and osc.count(root, "SELECT COUNT(*) FROM claim_revisions WHERE claim_id = ?", (original.id,)) == 3
    assert osc.meta(root).guidance_epoch == before.guidance_epoch + 1
    assert apply.preview_undo(osc.context(root), retire_op).state == "conflicted"  # undoing it again would fight the undo


def test_undo_conflict_is_shown_and_never_restores_a_snapshot(root):
    target = seed_claim(root)
    first = apply.apply_operations(osc.operator(root), ops(osc.op("rev", "revise_claim", {"claim_ref": target.model_dump(mode="json"), "proposition": "Second wording."})), read_set=osc.read_set(root), submission_id=new_id("op"), now=LATER)
    rev2 = RecordRef(kind="claim", id=target.id, revision=2)
    apply.apply_operations(osc.operator(root), ops(osc.op("rev", "revise_claim", {"claim_ref": rev2.model_dump(mode="json"), "proposition": "Third wording."})), read_set=osc.read_set(root), submission_id=new_id("op"), now=LATER)
    preview = apply.preview_undo(osc.context(root), first.operation_ids[0])
    assert preview.state == "conflicted" and preview.compensations == []
    assert [(c.ref.revision, c.undone_revision, c.current_revision, c.fields, c.reason) for c in preview.conflicts] == [(3, 2, 3, ["proposition"], "changed_later")]
    with pytest.raises(RecalithError, match="revision_conflict"):
        apply.apply_undo(osc.operator(root), first.operation_ids[0], preview_digest=preview.preview_digest)
    assert osc.claim_heads(root)[0]["proposition"] == "Third wording."
    # Undo of a creation retires the record instead of deleting history.
    created = seed_claim(root, "A created fact.", role="success")
    with db.open_store(osc.context(root), readonly=True) as store, store.read() as view:
        op_id = view.execute("SELECT operation_id FROM operations WHERE kind = 'propose_claim' AND changed LIKE ?", (f"%{created.id}%",)).fetchone()[0]
    preview = apply.preview_undo(osc.context(root), op_id)
    assert preview.state == "clean" and [c.action for c in preview.compensations] == ["retire"]
    apply.apply_undo(osc.operator(root), op_id, preview_digest=preview.preview_digest, now=LATER)
    assert osc.claim_by_text(root, "A created fact.")["status"] == "archived"
    with pytest.raises(RecalithError, match="policy_refused"):  # bookkeeping records are not undoable
        with db.open_store(osc.context(root), readonly=True) as store, store.read() as view:
            app_id = view.execute("SELECT operation_id FROM operations WHERE kind = 'apply_service' LIMIT 1").fetchone()[0]
        apply.preview_undo(osc.context(root), app_id)
