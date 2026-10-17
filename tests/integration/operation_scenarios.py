"""Test-only builders for Task 5: real captured evidence, seeded records and proposals.

Projects are filled from the sanitized real Claude Code 2.1.301 lifecycle
fixture (``tests/platform/claude_fixtures.py``): the real hook entry captures
every record in-process and ``ingest_ready`` commits it, so operations cite
real event IDs, payloads and quoted spans. A task is seeded directly because
task creation belongs to Task 6; this is a controlled fixture state, not a
production path. Model responses are built by parsing a JSON body with the
same partitioned parser the worker uses, so malformed operations reach
application exactly as they would from a provider.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

import worker_scenarios as ws  # first: it puts tests/ and tests/platform on sys.path
import claude_fixtures as cf  # noqa: E402
from recalith.capture import pipeline
from recalith.contracts.common import Actor, ReadSet, RecordRef, derived_id, digest_of, new_id
from recalith.contracts.config import body_cap_for
from recalith.contracts.memory import TaskState
from recalith.contracts.operations import ModelResponse, UsageReport, parse_model_body_partitioned
from recalith.controller import jobs
from recalith.core import identity
from recalith.fast import entry
from recalith.storage import db, records

OPERATOR = Actor(kind="operator", id="operator-test", channel="cli")
SCENARIO = "scenario.json"
USAGE = UsageReport(input_tokens=10, output_tokens=10, estimated_input_tokens=10, estimated_output_tokens=10, provider_request_id=None, duration_ms=1)


# --------------------------------------------------------------------------
# Projects with real captured events


def project(tmp: Path, name: str = "proj") -> Path:
    replay = cf.Replay(tmp / name)
    for record in cf.records("lifecycle"):
        entry.run(str(replay.root), "claude_code", replay.prepare(record), registered_event=record["event"], env={}, deadline=time.monotonic() + 5)
    pipeline.ingest_ready(replay.ctx)
    return replay.root


def context(root: Path, actor: Actor = ws.ACTOR):
    return identity.resolve_installation(root, actor=actor)


def operator(root: Path):
    return context(root, OPERATOR)


def events(root: Path) -> dict[str, dict[str, Any]]:
    """Real events by role: the first prompt, the failing pytest run, a failing ls, a success."""
    with db.open_store(context(root), readonly=True) as store, store.read() as view:
        rows = view.execute("SELECT event_id, kind, payload FROM events ORDER BY commit_sequence").fetchall()
    found: dict[str, dict[str, Any]] = {}
    for event_id, kind, payload in rows:
        data = json.loads(payload)
        role = None
        if kind == "user_message" and "prompt" not in found:
            role = "prompt"
        elif kind == "tool_finished" and data.get("exit_code") == 1 and "fail" not in found:
            role = "fail"
        elif kind == "tool_finished" and data.get("exit_code") == 2:
            role = "ls_fail"
        elif kind == "tool_finished" and data.get("result_text") == "hello-fixture":
            role = "success"
        if role:
            found[role] = {"id": event_id, "payload": data}
    assert set(found) == {"prompt", "fail", "ls_fail", "success"}, sorted(found)
    return found


def link(root: Path, role: str, *, relation: str = "supports", quote: str | None = None, field: str | None = None, mapping: str | None = None, digest: str | None = None) -> dict[str, Any]:
    event = events(root)[role]
    locator = None
    if quote is not None:
        field = field or ("text" if role == "prompt" else "result_text")
        text = event["payload"][field]
        start = text.index(quote)
        locator = {"field": field, "start": start, "end": start + len(quote), "text_digest": digest or hashlib.sha256(quote.encode("utf-8")).hexdigest()}
    return {"ref": {"kind": "event", "id": event["id"], "revision": 1}, "relation": relation, "root_event_ids": [event["id"]], "locator": locator, "mapping": mapping}


def supported(root: Path, text: str, role: str = "fail", **kw: Any) -> dict[str, Any]:
    return {"text": text, "evidence": [link(root, role, **kw)], "basis": "observed" if role != "prompt" else "user_declared"}


def missing_event_link() -> dict[str, Any]:
    ghost = derived_id("evt", ["another-installation", "claude_code", "never-captured"])
    return {"ref": {"kind": "event", "id": ghost, "revision": 1}, "relation": "supports", "root_event_ids": [ghost], "locator": None, "mapping": None}


def seed_task(root: Path, *, title: str = "Fix the failing fixture test") -> str:
    """A provisional task head (Task 6 creates these in production)."""
    ctx = context(root)
    now = ws.START
    task_id = new_id("task")
    state = TaskState(
        task_id=task_id, project_id=ctx.project_id, installation_id=ctx.installation_id, revision=1, status="active", title=title,
        objective=None, updated_at=now, last_activity_at=now,
    )
    with db.open_store(ctx) as store, store.transaction() as txn:
        records.write_task(txn, state, workspace_id=ctx.workspace_id)
        txn.mutated(serving_relevant=True)
    return task_id


# --------------------------------------------------------------------------
# Operations and responses


def op(local_ref: str, kind: str, payload: dict[str, Any], *, depends_on: list[str] | None = None, evidence: list[dict] | None = None, target: dict | None = None, reason: str = "fixture") -> dict[str, Any]:
    return {"local_ref": local_ref, "kind": kind, "depends_on": depends_on or [], "target": target, "payload": payload, "evidence": evidence or [], "reason": reason}


def claim(proposition: str, *, kind: str = "fact", basis: str = "inferred", subject: str = "fixture tests", **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "proposition": proposition, "proposition_key": {"subject": subject, "predicate": "observed"}, "basis": basis, **extra}


def body(ops: list[dict[str, Any]], no_op_reason: str | None = None) -> bytes:
    data: dict[str, Any] = {"operations": ops}
    if no_op_reason is not None:
        data["no_op_reason"] = no_op_reason
    return json.dumps(data).encode("utf-8")


def response(ops: list[dict[str, Any]], *, purpose: str = "extract_claims", no_op_reason: str | None = None) -> ModelResponse:
    parsed, reason, malformed = parse_model_body_partitioned(body(ops, no_op_reason), purpose=purpose, body_cap=body_cap_for(purpose))
    return ModelResponse(response_schema=1, operations=parsed, no_op_reason=reason, usage=USAGE, provenance=None, malformed=malformed)


def read_set(root: Path, refs: list[RecordRef] | None = None, fingerprints: dict[str, str] | None = None) -> ReadSet:
    ctx = context(root)
    return ReadSet(entity_revisions=refs or [], workspace_id=ctx.workspace_id, fingerprints=fingerprints or {}, policy_revision=1, tombstone_epoch=0)


def head_ref(root: Path, kind: str, record_id: str) -> RecordRef:
    with db.open_store(context(root), readonly=True) as store, store.read() as view:
        current = records.head(view, kind, record_id)
    assert current is not None
    return RecordRef(kind=kind, id=record_id, revision=current[0])


def leased(root: Path, kind: str, *, input_refs: list[RecordRef] | None = None, now: str = ws.START, owner: str = "worker-test"):
    """Enqueue and lease one model job (the lease the application is fenced by)."""
    ctx = context(root)
    refs = input_refs or [RecordRef(kind="claim", id=new_id("claim"), revision=1)]
    with db.open_store(ctx) as store:
        with store.transaction() as txn:
            candidates = [jobs.ReviewCandidate(claim_id=refs[0].id, origin="extracted", claim_kind="fact")] if kind == "review_claims" else ()
            job_id, _ = jobs.enqueue(txn, kind=kind, input_refs=refs, now=now, prompt_version="test@1", review_candidates=candidates, idempotency=digest_of(new_id("job")))  # a distinct attempt each call
        job = jobs.lease_next(ctx, owner=owner, now=now, kinds=[kind], store=store)
    assert job is not None and job.job_id == job_id
    return job


def meta(root: Path) -> db.Meta:
    with db.open_store(context(root), readonly=True) as store:
        return store.meta()


def claim_heads(root: Path) -> list[dict[str, Any]]:
    with db.open_store(context(root), readonly=True) as store, store.read() as view:
        rows = view.execute("SELECT claim_id, revision, status FROM claim_heads ORDER BY claim_id").fetchall()
        return [{**records.body(view, "claim", cid, rev), "head_status": status} for cid, rev, status in rows]


def claim_by_text(root: Path, proposition: str) -> dict[str, Any]:
    found = [c for c in claim_heads(root) if c["proposition"] == proposition]
    assert len(found) == 1, (proposition, len(found))
    return found[0]


def count(root: Path, sql: str, params: tuple = ()) -> int:
    with db.open_store(context(root), readonly=True) as store, store.read() as view:
        return view.execute(sql, params).fetchone()[0]


# --------------------------------------------------------------------------
# The kill/restart scenario (driven by worker_scenarios.py)

LESSON = "The scripted pytest run fails with exit code 1."
REPLACEMENT = "The fixture pytest run reports FAILURES for test_end."
ORIGINAL = "The fixture pytest run is flaky."


def crash_project(tmp: Path, name: str) -> Path:
    """A project with real events, a task, an operator-seeded claim and four model jobs.

    The job bodies (stored in ``scenario.json``) exercise: an independent
    claim group, an atomic replacement + supersession group, a group citing a
    never-captured event (rejected), a malformed operation and its dependent
    (rejected), an episode, and a task update; the review job proposes nothing.
    """
    from recalith.controller import apply

    root = project(tmp, name)
    ctx = context(root)
    _drain_ingest(root)  # the kill points must land on the model jobs' application, not on typed ingestion
    task_id = seed_task(root)
    seeded = apply.apply_operations(operator(root), [_op(op("orig", "propose_claim", claim(ORIGINAL, basis="inferred"), evidence=[link(root, "fail")]))], read_set=read_set(root), submission_id=derived_id("op", [name, "seed"]), now=ws.START)
    original = seeded.changed_refs[0]
    task = RecordRef(kind="task", id=task_id, revision=1)
    ev = events(root)
    bodies = {
        "extract_claims": body([
            op("lesson", "propose_claim", claim(LESSON, basis="observed"), evidence=[link(root, "fail", quote="FAILURES", mapping="tool.exit_code")]),
            op("replacement", "propose_claim", claim(REPLACEMENT, basis="inferred"), evidence=[link(root, "fail", quote="test_end")]),
            op("retire", "change_claim_status", {"claim_ref": original.model_dump(mode="json"), "status": "superseded", "replacement_local_ref": "replacement"}, depends_on=["replacement"], target=original.model_dump(mode="json")),
            op("ghost", "propose_claim", claim("A never-captured run passed."), evidence=[missing_event_link()]),
            {"local_ref": "broken", "kind": "propose_claim", "payload": {"kind": "fact"}, "reason": "malformed"},
            op("dependent", "attach_evidence", {"claim_ref": original.model_dump(mode="json"), "relation": "supports"}, depends_on=["broken"], evidence=[link(root, "ls_fail")]),
        ]).decode(),
        "review_claims": body([], "nothing to review").decode(),
        "build_episode": body([
            op("episode", "create_episode", {
                "task_id": task_id, "title": "Run the fixture tools", "started_at": ws.START,
                "objective": supported(root, "Run the scripted tools.", role="prompt", quote="run the scripted tools"),
                "steps": [{"ordinal": 0, "action": supported(root, "Ran pytest on test_long.py."), "outcome": "failure"}],
                "outcome": supported(root, "The pytest run failed."), "source_event_ids": [ev["prompt"]["id"], ev["fail"]["id"]],
            }),
        ]).decode(),
        "update_task": body([
            op("progress", "update_task", {"task_id": task_id, "expected_revision": 1, "patches": [
                {"op": "append", "field": "known_results", "value": supported(root, "pytest exits 1 with FAILURES.", quote="FAILURES")},
                {"op": "set", "field": "next_action", "value": supported(root, "Inspect test_end.", quote="test_end")},
            ]}, target=task.model_dump(mode="json")),
        ]).decode(),
    }
    inputs = {"extract_claims": [original], "review_claims": [original], "build_episode": [task], "update_task": [task]}
    with db.open_store(ctx) as store, store.transaction() as txn:
        for kind, refs in inputs.items():
            candidates = [jobs.ReviewCandidate(claim_id=original.id, origin="extracted", claim_kind="fact")] if kind == "review_claims" else ()
            jobs.enqueue(txn, kind=kind, input_refs=refs, now=ws.START, prompt_version="test@1", review_candidates=candidates)
    (root / SCENARIO).write_text(json.dumps({"bodies": bodies}), encoding="utf-8")
    return root


def _drain_ingest(root: Path) -> None:
    from recalith.controller import worker

    w = worker.Worker(context(root))  # real clock: ingest jobs are due at their real capture time
    try:
        while w.poll_once():
            pass
    finally:
        w.close()
    assert count(root, "SELECT COUNT(*) FROM jobs WHERE kind = 'ingest' AND state != 'completed'") == 0


def _op(data: dict[str, Any]):
    from recalith.contracts.operations import ProposedOperation

    return ProposedOperation.model_validate_json(json.dumps(data))


def scenario_bodies(root: Path) -> dict[str, bytes] | None:
    path = root / SCENARIO
    if not path.exists():
        return None
    return {k: v.encode("utf-8") for k, v in json.loads(path.read_text(encoding="utf-8"))["bodies"].items()}


def scenario_prepare(store, job, rounds):
    """The request names exactly the job's input records in its read set."""
    request = ws.request_for(store, job, rounds)
    rs = ReadSet(entity_revisions=list(job.input_refs), workspace_id=store.ctx.workspace_id, policy_revision=1, tombstone_epoch=0)
    return request.model_copy(update={"read_set": rs})


def normalized(root: Path) -> dict[str, Any]:
    """Authoritative state with irrelevant generated IDs and times removed (ACCEPTANCE_TESTS §4)."""
    ctx = context(root)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        kinds = dict(view.execute("SELECT job_id, kind FROM jobs").fetchall())
        jobs_ = sorted((k, s) for k, s in view.execute("SELECT kind, state FROM jobs WHERE kind NOT IN ('maintenance', 'ingest')").fetchall())
        apps = sorted(kinds.get(j, "service") for (j,) in view.execute("SELECT job_id FROM operations WHERE kind IN ('apply_proposal', 'apply_service')").fetchall())
        ops = sorted((kinds.get(j, "service"), ref, kind) for j, ref, kind in view.execute("SELECT job_id, local_ref, kind FROM operations WHERE kind NOT IN ('apply_proposal', 'apply_service')").fetchall())
        decisions = sorted(
            (kinds.get(j, "service"), d["local_ref"], d["outcome"], d["reason_code"])
            for j, inputs in view.execute("SELECT job_id, inputs FROM operations WHERE kind IN ('apply_proposal', 'apply_service')").fetchall()
            for d in json.loads(inputs)["result"]["decisions"]
        )
        claims = sorted((json.loads(b)["proposition"], rev, status) for _cid, rev, status, b in view.execute("SELECT h.claim_id, h.revision, h.status, r.body FROM claim_heads h JOIN claim_revisions r ON r.claim_id = h.claim_id AND r.revision = h.revision").fetchall())
        tasks = sorted((rev, status, json.dumps({k: v for k, v in json.loads(b).items() if k not in ("updated_at",)}, sort_keys=True).replace(ctx.installation_id, "INST")) for rev, status, b in view.execute("SELECT h.revision, h.status, r.body FROM task_heads h JOIN task_revisions r ON r.task_id = h.task_id AND r.revision = h.revision").fetchall())
        episodes = sorted((json.loads(b)["title"], rev, state) for rev, state, b in view.execute("SELECT h.revision, h.state, r.body FROM episode_heads h JOIN episode_revisions r ON r.episode_id = h.episode_id AND r.revision = h.revision").fetchall())
        counts = {t: view.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("claim_revisions", "task_revisions", "episode_revisions", "relations", "evidence_links", "events", "revision_chain")}  # noqa: S608
        meta = store.meta()
    task_ids = {json.loads(t[2])["task_id"] for t in tasks}
    tasks = [(rev, status, _strip(body_, task_ids)) for rev, status, body_ in tasks]
    return {"jobs": jobs_, "applications": apps, "operations": ops, "decisions": decisions, "claims": claims, "tasks": tasks, "episodes": episodes, "counts": counts, "guidance_epoch": meta.guidance_epoch}


def _strip(text: str, ids: set[str]) -> str:
    data = json.loads(text)
    for item in data.get("pending_actions", []):
        item["action_id"] = "ACT"
    out = json.dumps(data, sort_keys=True)
    for i in ids:
        out = out.replace(i, "TASK")
    return re.sub(r"evt_[0-9a-f]{64}", "EVT", out)  # event IDs derive from the installation
