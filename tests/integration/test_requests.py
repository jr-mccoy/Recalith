"""Task 7: request preparation and narrative scheduling (DATA_CONTRACTS §7, §11; decision 0009).

Projects hold real Claude Code 2.1.301 lifecycle payloads, ingested and
reduced by a real worker (``working_scenarios.Project``). Requests are built
by the production preparer (``controller.requests``); model replies are
recorded proposals answered by an in-process fake backend from the request it
actually received. Consumers owned by later tasks (extraction and review
admission, Task 9; revalidation, Task 10) are exercised as mechanics only.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

import pytest

import operation_scenarios as osc
import working_scenarios as wks
import worker_scenarios as ws
from working_scenarios import record, variant
from recalith.contracts.common import RecordRef, canonical_json, derived_id, format_utc, parse_utc, utc_now
from recalith.contracts.config import MODEL_INPUT_CAP
from recalith.contracts.operations import ModelRequest, PURPOSE_KINDS, REDUCTION_KINDS
from recalith.controller import apply, jobs, requests, worker
from recalith.storage import db, failpoints, records

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures" / "providers"))
import fake_backend  # noqa: E402

PROMPT_VERSION = {purpose: f"{purpose}@1" for purpose in PURPOSE_KINDS}


@pytest.fixture(autouse=True)
def _disarm():
    failpoints.disarm_all()
    yield
    failpoints.disarm_all()


def green_reruns() -> list[dict]:
    """Synthetic variants (as in test_episodes): the real passing pytest payload rerunning both failing test files."""
    out = []
    for call, command in (("toolu_probe_0002", "pytest -q test_long.py"), ("toolu_probe_0003", "pytest -q test_mid.py")):
        out += [
            variant(record("lifecycle", "PreToolUse", call), tool_suffix="green"),
            variant(record("lifecycle", "PostToolUse", "toolu_probe_0004"), replace={"toolu_probe_0004": f"{call}_green", "pytest -q -s test_pass.py": command}),
        ]
    return out


def lifecycle(tmp_path: Path, name: str = "work") -> wks.Project:
    """The real lifecycle session, then the green reruns that resolve its pending checkpoint into a settled episode."""
    p = wks.Project(tmp_path, name)
    p.scenario("lifecycle")
    p.drain()
    p.send_all(green_reruns())
    p.drain()
    return p


def model_jobs(p: wks.Project) -> list[dict]:
    with p.view() as v:
        rows = v.execute("SELECT body FROM jobs WHERE kind IN ('update_task', 'build_episode', 'extract_claims', 'review_claims', 'revalidate') ORDER BY rowid").fetchall()
    return [json.loads(r[0]) for r in rows]


def enqueue(p: wks.Project, kind: str, refs: list[RecordRef], *, now: str | None = None) -> str:
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        candidates = [jobs.ReviewCandidate(claim_id=refs[0].id, origin="extracted", claim_kind="fact")] if kind == "review_claims" else ()
        job_id, _ = jobs.enqueue(txn, kind=kind, input_refs=refs, now=now or osc.EARLIEST, due_at=osc.EARLIEST, prompt_version=PROMPT_VERSION[kind], review_candidates=candidates)
    return job_id


def get_job(p: wks.Project, job_id: str):
    with p.view() as v:
        return jobs.get_job(v, job_id)


def later(base: str, seconds: float) -> str:
    return format_utc(parse_utc(base) + _dt.timedelta(seconds=seconds))


def quiet_now(p: wks.Project) -> str:
    """A moment after every task's activity by more than the quiet window."""
    latest = max(t["last_activity_at"] for t in p.tasks())
    return later(latest, requests.QUIET_SECONDS + 60)


def seed_claim(p: wks.Project, proposition: str = "The scripted pytest run fails with exit code 1.") -> RecordRef:
    op = osc.op("c", "propose_claim", osc.claim(proposition), evidence=[osc.link(p.root, "fail", quote="FAILURES")])  # an inferred candidate
    result = apply.apply_operations(osc.operator(p.root), [osc._op(op)], read_set=osc.read_set(p.root), submission_id=derived_id("op", ["seed", proposition]), now=utc_now())
    return next(r for r in result.changed_refs if r.kind == "claim")


def answering_backend(**kw) -> ws.FakeBackend:
    """Answers the real request it received with the fake JSON process's narrative body."""
    def script(purpose, i):
        return worker.LaunchOutcome(stdout=ws.envelope(backend.last_body, usage={"input_tokens": 50, "output_tokens": 10}))

    def capture(request: bytes, purpose: str) -> None:
        backend.requests.append(request)
        backend.last_body = fake_backend.narrative_body(json.loads(request)).encode("utf-8")
        if kw.get("on_launch"):
            kw["on_launch"](request, purpose)

    backend = ws.FakeBackend(script, on_launch=capture)
    backend.requests = []  # type: ignore[attr-defined]
    return backend


# ---------------------------------------------------------------------------
# Scheduling (decision 0009)


def test_reduction_schedules_narrative_within_the_ordinary_budget(tmp_path):
    p = lifecycle(tmp_path)
    found = model_jobs(p)
    episodes = [e for e in p.episodes() if e["head_state"] == "settled" and e["steps"]]
    assert episodes, "the lifecycle session ends in a settled episode with steps"
    build = [j for j in found if j["kind"] == "build_episode"]
    narrative = [j for j in found if j["kind"] == "update_task"]
    assert sorted(j["input_refs"][0]["id"] for j in build) == sorted(e["episode_id"] for e in episodes)
    assert len(narrative) == 1 and narrative[0]["input_refs"][0]["kind"] == "task"
    for job in found:
        assert job["budget_pool"] == "ordinary" and job["prompt_version"] == PROMPT_VERSION[job["kind"]] and job["state"] == "pending"
    assert {j["priority"] for j in build} == {jobs.BAND_EPISODE} and narrative[0]["priority"] == jobs.BAND_EXTRACTION
    # Task narrative waits for a quiet task: due after the quiet window, not at the checkpoint.
    task = p.task(narrative[0]["input_refs"][0]["id"])
    assert parse_utc(narrative[0]["due_at"]) >= parse_utc(task["last_activity_at"]) + _dt.timedelta(seconds=requests.QUIET_SECONDS) - _dt.timedelta(seconds=1)
    # A later checkpoint of the same task coalesces: at most one pending narrative job per task.
    p.send_all([variant(record("lifecycle", "SessionEnd"), session=wks.LIFECYCLE_SESSION)])
    p.send(variant(record("lifecycle", "UserPromptSubmit"), prompt="FIXTURE: one more step."))
    p.send(variant(record("lifecycle", "PreCompact")))
    p.send(variant(record("lifecycle", "PostCompact")))
    p.drain()
    pending = [j for j in model_jobs(p) if j["kind"] == "update_task" and j["state"] == "pending"]
    assert len(pending) <= 1
    # Coalescing, directly: a checkpoint at a newer task revision replaces the older pending narrative job.
    task_id = narrative[0]["input_refs"][0]["id"]
    p.send(variant(record("lifecycle", "UserPromptSubmit"), prompt="FIXTURE: and another step."))
    p.drain()  # no checkpoint: the task advances without new narrative
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        before = {j["job_id"] for j in model_jobs(p) if j["kind"] == "update_task" and j["state"] == "pending"}
        created = requests.schedule_narrative(txn, task_id=task_id, episode_ref=None, now=utc_now())
    assert len(created) == 1 and created[0] not in before
    after = {j["job_id"]: j for j in model_jobs(p) if j["kind"] == "update_task"}
    assert [j for j in after.values() if j["state"] == "pending"] == [after[created[0]]]
    assert all(after[j]["state"] == "cancelled" and after[j]["last_error_code"] == "coalesced" for j in before)
    # Typed reduction still makes no model call: nothing was reserved.
    assert p.count("SELECT COUNT(*) FROM provider_usage") == 0


# ---------------------------------------------------------------------------
# Preparation for every purpose


def test_prepared_requests_cover_every_model_purpose(tmp_path):
    p = lifecycle(tmp_path)
    ctx = p.ctx
    task_id = p.tasks()[0]["task_id"]
    episode = next(e for e in p.episodes() if e["steps"])
    claim = seed_claim(p)
    now = quiet_now(p)
    cases = {
        "update_task": [RecordRef(kind="task", id=task_id, revision=1)],
        "build_episode": [RecordRef(kind="episode", id=episode["episode_id"], revision=episode["revision"])],
        "extract_claims": [RecordRef(kind="episode", id=episode["episode_id"], revision=episode["revision"])],
        "review_claims": [claim],
        "revalidate": [claim],
    }
    other_installation = wks.Project(tmp_path, "other")
    # A revalidation prepares a request only for a pending recheck a model can settle (decision 0012); this one
    # names a later passing result as its observation, which the request must show and its read set name.
    observed = p.events("tool_finished")[-1]["id"]
    with db.open_store(ctx) as store, store.transaction() as txn:
        txn.execute(
            "INSERT INTO claim_rechecks (recheck_id, claim_id, claim_revision, reason, event_id, detail, state, created_at) VALUES (?, ?, ?, 'review_due', ?, '{}', 'pending', ?)",
            (derived_id("rchk", [claim.id]), claim.id, claim.revision, observed, now),
        )
        txn.mutated(serving_relevant=False)
    for purpose, refs in cases.items():
        job = get_job(p, enqueue(p, purpose, refs))
        request = requests.prepare_model_request(ctx, job, now=now)
        raw = canonical_json(request.model_dump(mode="json"))
        assert len(raw) <= MODEL_INPUT_CAP and requests.request_estimate(request) == -(-len(raw) // 3)
        assert request.purpose == purpose and request.prompt_version == PROMPT_VERSION[purpose] and request.job_id == job.job_id
        assert request.read_set.workspace_id == ctx.workspace_id
        # Source text is data inside the request; the instruction is the pinned prompt.
        assert request.instruction_text == requests.prompts.INSTRUCTIONS[PROMPT_VERSION[purpose]]
        kinds = {v["properties"]["kind"]["const"] for v in request.output_schema["properties"]["operations"]["items"]["oneOf"]}
        assert kinds == set(PURPOSE_KINDS[purpose]) and not kinds & REDUCTION_KINDS
        assert other_installation.ctx.installation_id not in raw.decode("utf-8")
        allowed = {(r.kind, r.id) for r in request.allowed_evidence_refs}
        assert {("event", e.event_id) for e in request.events} <= allowed
        if purpose == "update_task":
            assert request.task_state is not None and request.task_state.task_id == task_id
            assert RecordRef(kind="task", id=task_id, revision=request.task_state.revision) in request.read_set.entity_revisions
            assert request.boundaries and all(b.candidate.state == "pending" for b in request.boundaries)
            assert all(b.binding_revisions == p.expected(b.candidate.proposed_event_ids) for b in request.boundaries)
            assert request.episodes and request.events
        if purpose == "build_episode":
            assert request.episodes[0].episode_id == episode["episode_id"]
            shown = {e.event_id for e in request.events}
            assert shown <= set(episode["source_event_ids"])
            # The real session exceeds 96 KiB: bulky successful output is dropped; requests and failures are kept.
            with p.view() as v:
                size = {e: len(v.execute("SELECT payload FROM events WHERE event_id = ?", (e,)).fetchone()[0]) for e in episode["source_event_ids"]}
            kept_last = {e["id"] for e in p.events("user_message")} | {e["id"] for e in p.events("tool_finished") if e["payload"].get("outcome") != "success"}
            dropped = set(size) - shown
            assert dropped and not dropped & kept_last and kept_last & set(size) <= shown
            bulky = {e for e in size if size[e] > 30_000}
            assert bulky and bulky <= dropped  # the 30k-character outputs go first
            failures = {e["id"] for e in p.events("tool_finished") if e["payload"].get("outcome") == "failure"} & set(episode["source_event_ids"])
            assert failures <= shown
        if purpose == "extract_claims":
            assert request.claims and request.task_state is not None
        if purpose == "review_claims":
            assert request.review_batch is not None and [r.id for r in request.review_batch.candidate_refs] == [claim.id]
            assert request.claims[0].review_assessment is None and request.claims[0].model_provenance is None
            assert {e.event_id for e in request.events} == {ev.link.ref.id for ev in request.review_batch.evidence_index}
        if purpose == "revalidate":
            assert request.claims[0].claim_id == claim.id and request.events
            assert observed in {e.event_id for e in request.events} and RecordRef(kind="event", id=observed, revision=1) in request.read_set.entity_revisions
        assert ModelRequest.model_validate_json(raw) == request


def test_output_schemas_offer_only_the_purpose_kinds():
    for purpose, allowed in PURPOSE_KINDS.items():
        schema = requests.output_schema(purpose)
        kinds = {v["properties"]["kind"]["const"] for v in schema["properties"]["operations"]["items"]["oneOf"]}
        assert kinds == set(allowed)
        text = json.dumps(schema)
        for controller_only in REDUCTION_KINDS:
            assert f'"{controller_only}"' not in text
        assert len(canonical_json(schema)) < 40 * 1024  # leaves room for source data under the 96 KiB cap


def test_request_is_bounded_by_dropping_low_priority_slices(tmp_path, monkeypatch):
    p = lifecycle(tmp_path)
    task_id = p.tasks()[0]["task_id"]
    job = get_job(p, enqueue(p, "update_task", [RecordRef(kind="task", id=task_id, revision=1)]))
    now = quiet_now(p)
    full = requests.prepare_model_request(p.ctx, job, now=now)
    full_size = len(canonical_json(full.model_dump(mode="json")))
    cap = full_size - 4000
    monkeypatch.setattr(requests, "MODEL_INPUT_CAP", cap)
    trimmed = requests.prepare_model_request(p.ctx, job, now=now)
    assert len(canonical_json(trimmed.model_dump(mode="json"))) <= cap
    assert trimmed.task_state == full.task_state and len(trimmed.events) < len(full.events)
    # The consulted head stays in the read set; dropped events are no longer allowed evidence.
    assert {(r.kind, r.id) for r in trimmed.allowed_evidence_refs if r.kind == "event"} == {("event", e.event_id) for e in trimmed.events}
    monkeypatch.setattr(requests, "MODEL_INPUT_CAP", 2000)
    with pytest.raises(requests.PrepareFailed) as err:
        requests.prepare_model_request(p.ctx, job, now=now)
    assert err.value.code == "model_input_oversized"


def test_foreign_or_missing_inputs_are_refused(tmp_path):
    a, b = lifecycle(tmp_path, "a"), lifecycle(tmp_path, "b")
    b_task = b.tasks()[0]["task_id"]
    job = get_job(a, enqueue(a, "update_task", [RecordRef(kind="task", id=b_task, revision=1)]))
    with pytest.raises(requests.PrepareFailed) as err:
        requests.prepare_model_request(a.ctx, job, now=quiet_now(a))
    assert err.value.code == "request_input_missing"
    b_event = b.events("user_message")[0]["id"]
    job = get_job(a, enqueue(a, "extract_claims", [RecordRef(kind="event", id=b_event, revision=1)]))
    with pytest.raises(requests.PrepareFailed) as err:
        requests.prepare_model_request(a.ctx, job, now=quiet_now(a))
    assert err.value.code == "request_input_missing"
    job = get_job(a, enqueue(a, "update_task", [RecordRef(kind="task", id=a.tasks()[0]["task_id"], revision=1)]))
    with pytest.raises(requests.PrepareFailed) as err:
        requests.prepare_model_request(a.ctx, job.model_copy(update={"prompt_version": "update_task@99"}), now=quiet_now(a))
    assert err.value.code == "prompt_version_unavailable"


def test_narrative_waits_for_a_quiet_task_and_obsolete_jobs_cancel_without_a_call(tmp_path):
    p = lifecycle(tmp_path)
    task = p.tasks()[0]
    job = get_job(p, enqueue(p, "update_task", [RecordRef(kind="task", id=task["task_id"], revision=1)]))
    with pytest.raises(requests.PrepareFailed) as err:
        requests.prepare_model_request(p.ctx, job, now=later(task["last_activity_at"], 10))
    assert err.value.code == "task_active"
    # In the lane a busy task defers the job visibly, with no reservation and no call.
    clock = ws.FakeClock(later(task["last_activity_at"], 10))
    backend = answering_backend()
    w = worker.Worker(osc.context(p.root), clock=clock, model=worker.ModelRuntime(backend, requests.runtime_preparer(p.ctx, now=clock.now)))
    try:
        for _ in range(10):
            if not w.lane.step():
                break
    finally:
        w.close()
    deferred = get_job(p, job.job_id)
    assert deferred.state == "pending" and deferred.last_error_code == "task_active" and deferred.attempt == 0
    assert parse_utc(deferred.due_at) > parse_utc(clock.now()) - _dt.timedelta(seconds=120)  # retried after the backoff
    assert p.count("SELECT COUNT(*) FROM provider_usage WHERE job_id = ?", (job.job_id,)) == 0
    assert [purpose for purpose, _ in backend.calls if purpose == "update_task"] == []
    # An episode whose head was archived no longer warrants narrative: cancelled, not called.
    episode = next(e for e in p.episodes() if e["steps"])
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        txn.execute("UPDATE episode_heads SET state = 'archived' WHERE episode_id = ?", (episode["episode_id"],))
    job_id = enqueue(p, "build_episode", [RecordRef(kind="episode", id=episode["episode_id"], revision=episode["revision"])])
    with pytest.raises(requests.NothingToPrepare):
        requests.prepare_model_request(p.ctx, get_job(p, job_id), now=quiet_now(p))
    usage_before = p.count("SELECT COUNT(*) FROM provider_usage")
    w = worker.Worker(osc.context(p.root), clock=ws.FakeClock(quiet_now(p)), model=worker.ModelRuntime(backend, requests.runtime_preparer(p.ctx, now=lambda: quiet_now(p))))
    try:
        while w.lane.step():
            pass
    finally:
        w.close()
    assert get_job(p, job_id).state == "cancelled" and get_job(p, job_id).last_error_code == "narrative_obsolete"
    assert ("build_episode", job_id) not in backend.calls
    assert p.count("SELECT COUNT(*) FROM provider_usage WHERE job_id = ?", (job_id,)) == 0 and p.count("SELECT COUNT(*) FROM provider_usage") >= usage_before


def test_stale_narrative_patch_is_reevaluated_not_overwritten(tmp_path):
    """Typed reduction advances the task while its narrative call is in flight (strict optimistic concurrency)."""
    p = lifecycle(tmp_path)
    task_id = p.tasks()[0]["task_id"]
    now = quiet_now(p)
    sent = []

    def advance(request: bytes, purpose: str) -> None:
        if purpose == "update_task" and not sent:
            sent.append(True)  # a new prompt arrives and is reduced while the provider runs
            p.send(variant(record("lifecycle", "UserPromptSubmit"), prompt="FIXTURE: keep the fixture output."), at=later(now, -(requests.QUIET_SECONDS + 30)))
            p.drain()

    backend = answering_backend(on_launch=advance)
    clock = ws.FakeClock(now)
    w = worker.Worker(osc.context(p.root), clock=clock, model=worker.ModelRuntime(backend, requests.runtime_preparer(p.ctx, now=clock.now)))
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        for (body,) in txn.execute("SELECT body FROM jobs WHERE kind = 'update_task'").fetchall():
            job = jobs.Job.model_validate_json(body)
            jobs._save(txn, job.model_copy(update={"due_at": osc.EARLIEST}))
    try:
        for _ in range(20):
            if not w.lane.step():
                break
    finally:
        w.close()
    narratives = [j for j in model_jobs(p) if j["kind"] == "update_task"]
    first = narratives[0]
    assert first["state"] == "cancelled" and first["last_error_code"] == "reevaluation_requeued"
    second = [j for j in narratives if j is not first]
    assert second and second[-1]["state"] == "completed"
    stale = json.loads(backend.requests[[c[0] for c in backend.calls].index("update_task")])["task_state"]["revision"]
    task = p.task(task_id)
    assert task["revision"] > stale + 1  # reduction's revision first, then the re-evaluated narrative on top of it
    assert task["next_action"]["text"] == "Continue from the last checkpoint."
    with p.view() as v:
        older = records.body(v, "task", task_id, stale + 1)
    assert older["next_action"] is None  # the stale patch never overwrote the reduction's revision


def test_consulted_task_change_requeues_episode_narrative(tmp_path):
    """An episode narrative consults its task; a task revision during the call re-evaluates it (decision 0007)."""
    p = lifecycle(tmp_path)
    now = quiet_now(p)
    sent = []

    def advance(request: bytes, purpose: str) -> None:
        if purpose == "build_episode" and not sent:
            sent.append(json.loads(request))
            p.send(variant(record("lifecycle", "UserPromptSubmit"), prompt="FIXTURE: one more note."), at=later(now, -(requests.QUIET_SECONDS + 30)))
            p.drain()

    backend = answering_backend(on_launch=advance)
    clock = ws.FakeClock(now)
    w = worker.Worker(osc.context(p.root), clock=clock, model=worker.ModelRuntime(backend, requests.runtime_preparer(p.ctx, now=clock.now)))
    try:
        assert w.lane.step()  # the episode narrative (band 3) goes first
    finally:
        w.close()
    request = sent[0]
    task_ref = {"kind": "task", "id": request["task_state"]["task_id"], "revision": request["task_state"]["revision"]}
    assert task_ref in request["read_set"]["entity_revisions"]
    [job] = [j for j in model_jobs(p) if j["kind"] == "build_episode" and j["state"] != "pending"]
    assert job["state"] == "cancelled" and job["last_error_code"] == "reevaluation_requeued"
    assert all(not e["title"].startswith("Narrative: ") for e in p.episodes())  # nothing of the stale proposal applied


def test_review_batch_is_persisted_before_launch_and_reused_while_unchanged(tmp_path):
    p = lifecycle(tmp_path)
    claim = seed_claim(p)
    job = get_job(p, enqueue(p, "review_claims", [claim]))
    first = requests.prepare_model_request(p.ctx, job, now=utc_now())
    assert p.count("SELECT COUNT(*) FROM review_batches WHERE review_job_id = ?", (job.job_id,)) == 1
    again = requests.prepare_model_request(p.ctx, job, now=utc_now())
    assert again.review_batch == first.review_batch  # a retry of an unchanged snapshot reuses its batch
    assert p.count("SELECT COUNT(*) FROM review_batches WHERE review_job_id = ?", (job.job_id,)) == 1
    ids = {e.evidence_id for e in first.review_batch.evidence_index}
    assert ids and all(i.startswith("evd_") for i in ids)
    # A changed candidate needs a fresh snapshot (and the read set rechecks it before applying).
    op = osc.op("more", "attach_evidence", {"claim_ref": claim.model_dump(mode="json"), "relation": "supports"}, target=claim.model_dump(mode="json"), evidence=[osc.link(p.root, "ls_fail")])
    apply.apply_operations(osc.operator(p.root), [osc._op(op)], read_set=osc.read_set(p.root), submission_id=derived_id("op", ["more"]), now=utc_now())
    fresh = requests.prepare_model_request(p.ctx, job.model_copy(update={"input_refs": [osc.head_ref(p.root, "claim", claim.id)]}), now=utc_now())
    assert fresh.review_batch.batch_id != first.review_batch.batch_id and len(fresh.review_batch.evidence_index) == len(ids) + 1
    assert p.count("SELECT COUNT(*) FROM review_batches WHERE review_job_id = ?", (job.job_id,)) == 2
    # Through the lane: the job's candidate revision was superseded by the attachment, whose application
    # scheduled the new revision's own review (Task 9), so this job is cancelled without a call; the new
    # review's capacity rejections apply and change nothing but the recorded assessment.
    backend = answering_backend()
    w = worker.Worker(osc.context(p.root), clock=ws.FakeClock(utc_now()), model=worker.ModelRuntime(backend, requests.runtime_preparer(p.ctx)))
    try:
        while w.lane.step():
            pass
    finally:
        w.close()
    stale = get_job(p, job.job_id)
    assert stale.state == "cancelled" and stale.last_error_code == "review_candidates_stale"
    after = osc.claim_by_text(p.root, "The scripted pytest run fails with exit code 1.")
    assert after["head_status"] == "candidate" and after["review_assessment"]["objections"] == ["review_capacity"]


def test_expansion_rounds_resolve_only_this_installations_records(tmp_path):
    a, b = lifecycle(tmp_path, "a"), lifecycle(tmp_path, "b")
    episode = next(e for e in a.episodes() if e["steps"])
    job = get_job(a, enqueue(a, "extract_claims", [RecordRef(kind="event", id=a.events("user_message")[0]["id"], revision=1)]))
    base = requests.prepare_model_request(a.ctx, job, now=utc_now())
    local_event = a.events("tool_finished")[-1]["id"]
    foreign_event = b.events("tool_finished")[-1]["id"]
    ops = [
        osc.op("e1", "request_evidence", {"request_kind": "record", "ref": {"kind": "event", "id": local_event, "revision": 1}}),
        osc.op("e2", "request_evidence", {"request_kind": "record", "ref": {"kind": "event", "id": foreign_event, "revision": 1}}),
        osc.op("e3", "request_evidence", {"request_kind": "record", "ref": {"kind": "episode", "id": episode["episode_id"], "revision": 1}}),
        osc.op("e4", "request_evidence", {"request_kind": "file_excerpt", "path": "README.md"}),
    ]
    round_ = osc.response(ops, purpose="extract_claims")
    expanded = requests.prepare_model_request(a.ctx, job, rounds=[round_], now=utc_now())
    ids = {e.event_id for e in expanded.events}
    assert local_event in ids and foreign_event not in ids and local_event not in {e.event_id for e in base.events}
    assert episode["episode_id"] in {e.episode_id for e in expanded.episodes}


def test_reservation_uses_the_exact_request_estimate(tmp_path):
    p = lifecycle(tmp_path)
    backend = answering_backend()
    clock = ws.FakeClock(quiet_now(p))
    w = worker.Worker(osc.context(p.root), clock=clock, model=worker.ModelRuntime(backend, requests.runtime_preparer(p.ctx, now=clock.now)))
    try:
        while w.lane.step():
            pass
    finally:
        w.close()
    with p.view() as v:
        rows = [json.loads(r[0]) for r in v.execute("SELECT body FROM provider_usage ORDER BY rowid").fetchall()]
    assert len(rows) == len(backend.requests) >= 2
    for row, raw in zip(rows, backend.requests, strict=True):
        assert row["estimated_input_limit"] == -(-len(raw) // 3) and row["state"] == "charged"
        assert row["ordinary"]["invocations"] == 1 and row["protected"]["invocations"] == 0
    assert {j["state"] for j in model_jobs(p)} == {"completed"}
    titles = [e["title"] for e in p.episodes() if e["head_state"] == "settled" and e["steps"]]
    assert titles and all(t.startswith("Narrative: ") for t in titles)
