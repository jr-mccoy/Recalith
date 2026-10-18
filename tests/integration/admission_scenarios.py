"""Test-only builders for Task 9: claim extraction, deterministic admission and review over real payloads.

Real inputs: every Claude event enters through the real 2.1.301 adapter
mapping, normalization, capture, ingestion and typed reduction
(``working_scenarios.Project``). Real payloads used: the lifecycle session
(prompts, the failing ``pytest -q test_long.py``/``test_mid.py`` with their
certified exit-status and pytest assertions, the passing ``pytest -q -s
test_pass.py``, ``seq``, ``grep``, ``Read``, ``Write``/``Edit``, the failing
``ls``) and the subagent session (the host ``<task-notification>`` prompt).

**Synthetic variants** (named at each use; payload shape, mapping and
normalization stay real): changed prompt texts (pasted email, fenced code,
blockquotes, diffs, tracebacks, terminal transcripts, a terse instruction,
CRLF line ends), reruns of real calls under new tool-use IDs and changed
commands, a second host session, and controlled capture times. A prompt
variant over the 48 KiB part size is partitioned by the real normalizer.

**Model behavior is recorded proposals**: extraction bodies and review
verdicts are written here and go through the real persisted-proposal path
(lease, ``persist_proposal`` under the fence, ``apply_proposal``). They
exercise the admission mechanics, not live extraction or review quality
(ACCEPTANCE_TESTS §5 stays unavailable without a certified route, B1).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Sequence

import working_scenarios as wks  # first: puts tests/, tests/integration and tests/platform on sys.path
import operation_scenarios as osc  # noqa: E402
from recalith.contracts.common import RecordRef, derived_id, new_id, utc_now  # noqa: E402
from recalith.contracts.jobs import Job  # noqa: E402
from recalith.contracts.memory import ReviewBatch  # noqa: E402
from recalith.contracts.operations import ModelRequest, ModelResponse, ProposedOperation  # noqa: E402
from recalith.controller import apply, jobs, review  # noqa: E402
from recalith.storage import db, records  # noqa: E402

# Event times ahead of the real clock: the real worker's time sweep never fires before a test's own events arrive.
BASE = wks.later(hours=48)
KEY = {"subject": "fixture tests", "predicate": "observed"}


def at(minutes: float = 0, seconds: float = 0) -> str:
    return wks.later(minutes=minutes + seconds / 60, base=BASE)


def project(tmp: Path, name: str = "admission") -> wks.Project:
    p = wks.Project(tmp, name)
    p.scenario("lifecycle")
    p.drain()
    return p


def prompt(p: wks.Project, text: str, *, at_: str | None = None, session: str | None = None) -> dict[str, Any]:
    """Send a synthetic prompt variant and return its stored user_message event (the last part)."""
    p.send(wks.variant(wks.record("lifecycle", "UserPromptSubmit"), prompt=text, session=session), at=at_)
    p.drain()
    found = [e for e in p.events("user_message") if (e["payload"].get("text") or "") and text.startswith(e["payload"]["text"][:64])]
    return found[-1]


def send_call(p: wks.Project, tool_use_id: str, suffix: str, *, command: str | None = None, at_: str | None = None, session: str | None = None, outcome_of: str | None = None) -> None:
    """Send a rerun of a real call (synthetic variant: new tool-use ID, optional changed command).

    ``outcome_of`` takes the *result* record from another real call (e.g. the passing pytest result for a
    rerun of a failing command), keeping this call's ID and command.
    """
    pre = [r for r in wks.cf.records("lifecycle") if r["event"] == "PreToolUse" and r["payload"].get("tool_use_id") == tool_use_id]
    source = outcome_of or tool_use_id
    post = [r for r in wks.cf.records("lifecycle") if r["event"] in ("PostToolUse", "PostToolUseFailure") and r["payload"].get("tool_use_id") == source]
    for rec in pre:
        p.send(wks.variant(rec, tool_suffix=suffix, command=command, session=session), at=at_)
    for rec in post:
        rec = wks.variant(rec, replace={source: tool_use_id}) if outcome_of else rec
        if outcome_of:
            rec["payload"]["tool_input"] = json.loads(json.dumps(pre[0]["payload"]["tool_input"]))
        p.send(wks.variant(rec, tool_suffix=suffix, command=command, session=session), at=at_)


def call(p: wks.Project, tool_use_id: str, suffix: str, **kw: Any) -> dict[str, Any]:
    """:func:`send_call`, ingested and reduced; returns its finished event."""
    send_call(p, tool_use_id, suffix, **kw)
    p.drain()
    return p.event("tool_finished", call=f"{tool_use_id}_{suffix}")


# --------------------------------------------------------------------------
# Evidence links


def link(ev: dict[str, Any], *, relation: str = "supports", field: str | None = None, quote: str | None = None, start: int | None = None, end: int | None = None, mapping: str | None = None) -> dict[str, Any]:
    locator = None
    if field is not None:
        text = ev["payload"]
        for part in field.split("."):
            text = text[int(part)] if isinstance(text, list) else text[part]
        assert isinstance(text, str)
        if quote is not None:
            start = text.index(quote)
            end = start + len(quote)
        start = 0 if start is None else start
        end = len(text) if end is None else end
        span = text[start:end]
        locator = {"field": field, "start": start, "end": end, "text_digest": hashlib.sha256(span.encode("utf-8")).hexdigest()}
    return {"ref": {"kind": "event", "id": ev["id"], "revision": 1}, "relation": relation, "root_event_ids": [ev["id"]], "locator": locator, "mapping": mapping}


def claim(proposition: str, *, kind: str = "fact", basis: str = "inferred", subject: str = "fixture tests", **extra: Any) -> dict[str, Any]:
    return osc.claim(proposition, kind=kind, basis=basis, subject=subject, **extra)


def lesson(proposition: str, **failure: Any) -> dict[str, Any]:
    body = {"action_family_digest": None, "last_supporting_failure_event_id": None, "observed_failure": {"text": "The run failed.", "evidence": [], "basis": "inferred"}, "retry_conditions": []}
    body.update(failure)
    return claim(proposition, kind="failure_lesson", failure=body)


# --------------------------------------------------------------------------
# Recorded proposals through the real persisted path


def extract(p: wks.Project, ops: list[dict[str, Any]], *, input_refs: list[RecordRef] | None = None, response: ModelResponse | None = None):
    """A recorded extraction proposal: lease, persist under the fence, apply (returns ApplyResult)."""
    refs = input_refs or [RecordRef(kind="event", id=p.events("user_message")[0]["id"], revision=1)]
    job = osc.leased(p.root, "extract_claims", input_refs=refs, now=utc_now())
    response = response or osc.response(ops, purpose="extract_claims")
    with db.open_store(p.ctx) as store:
        apply.persist_proposal(store, job, response, osc.read_set(p.root), now=utc_now())
        return apply.apply_proposal(p.ctx, job, response, store=store, now=utc_now())


def operator_submit(p: wks.Project, ops: list[dict[str, Any]]):
    return apply.apply_operations(osc.operator(p.root), [ProposedOperation.model_validate(o) for o in ops], read_set=osc.read_set(p.root), submission_id=new_id("op"), now=utc_now())


def created_claim(result) -> str:
    refs = [r for r in result.changed_refs if r.kind == "claim"]
    assert refs, result.decisions
    return refs[0].id


def head(p: wks.Project, claim_id: str) -> dict[str, Any]:
    with p.view() as v:
        revision, status = records.head(v, "claim", claim_id)
        return {**records.body(v, "claim", claim_id, revision), "head_status": status}


def review_jobs(p: wks.Project, claim_id: str | None = None, *, states: Sequence[str] = ("pending", "waiting_budget", "leased", "completed", "cancelled", "failed")) -> list[Job]:
    with p.view() as v:
        rows = v.execute("SELECT body FROM jobs WHERE kind = 'review_claims' ORDER BY rowid").fetchall()
    out = [Job.model_validate_json(r[0]) for r in rows]
    return [j for j in out if j.state in states and (claim_id is None or any(r.id == claim_id for r in j.input_refs))]


def lease(p: wks.Project, job_id: str, *, now: str | None = None, owner: str = "review-test") -> Job:
    """Lease one specific job the way ``jobs.lease_next`` does (test infrastructure only)."""
    now = now or utc_now()
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        job = jobs.get_job(txn, job_id)
        assert job is not None and job.state in ("pending", "waiting_budget"), job
        leased = job.model_copy(update={"state": "leased", "lease_owner": owner, "lease_generation": job.lease_generation + 1, "lease_until": jobs._plus(now, 600)})
        jobs._save(txn, leased)
    return leased


def assess(batch: ReviewBatch, ref: RecordRef | dict[str, Any], verdict: str, *, local_ref: str, objections: Sequence[str] = (), evidence_ids: Sequence[str] = (), batch_id: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    target = ref.model_dump(mode="json") if isinstance(ref, RecordRef) else ref
    payload = {"batch_id": batch_id or batch.batch_id, "candidate_ref": target, "verdict": verdict, "objections": list(objections), "evidence_ids": list(evidence_ids), **(extra or {})}
    return {"local_ref": local_ref, "kind": "assess_claim", "depends_on": [], "target": target, "payload": payload, "evidence": [], "reason": ""}


def support_ids(batch: ReviewBatch, claim_body: dict[str, Any], relation: str = "supports") -> list[str]:
    links = [json.dumps(item, sort_keys=True) for item in claim_body[relation]]
    return [e.evidence_id for e in batch.evidence_index if json.dumps(e.link.model_dump(mode="json"), sort_keys=True) in links]


def run_review(p: wks.Project, job_id: str, decide: Callable[[ModelRequest], list[dict[str, Any]]], *, no_op_reason: str | None = None):
    """Prepare the job's persisted batch through ``review.review_candidates`` and apply the recorded verdicts."""
    job = lease(p, job_id)
    captured: dict[str, Any] = {}

    def launch(request: ModelRequest) -> ModelResponse:
        captured["request"] = request
        return osc.response(decide(request), purpose="review_claims", no_op_reason=no_op_reason)

    with db.open_store(p.ctx) as store:
        with store.read() as view:
            claim_ids = [c.claim_id for c in review.batch_candidates(view, job)]
        response = review.review_candidates(p.ctx, claim_ids, job=job, store=store, launch=launch)
        request = captured["request"]
        apply.persist_proposal(store, job, response, request.read_set, now=utc_now())
        result = apply.apply_proposal(p.ctx, job, response, store=store, now=utc_now())
    return request, result


def outcomes(p: wks.Project, claim_id: str) -> list[tuple[str, str]]:
    with p.view() as v:
        return [(o["outcome"], o["reason_code"]) for o in review.outcomes(v, claim_id)]


def supported_all(request: ModelRequest) -> list[dict[str, Any]]:
    """Recorded verdicts: every candidate supported, citing its first support evidence ID."""
    batch = request.review_batch
    assert batch is not None
    ops = []
    for i, ref in enumerate(batch.candidate_refs):
        body = next(c for c in request.claims if c.claim_id == ref.id).model_dump(mode="json")
        ops.append(assess(batch, ref, "supported", local_ref=f"a{i}", evidence_ids=support_ids(batch, body)[:1]))
    return ops


def admit(p: wks.Project, claim_id: str) -> None:
    """Run the candidate's pending review with a supported verdict (recorded)."""
    (job,) = review_jobs(p, claim_id, states=("pending", "waiting_budget"))
    _request, result = run_review(p, job.job_id, supported_all)
    assert all(d.outcome == "apply" for d in result.decisions), result.decisions


def evidence_events(p: wks.Project, n: int, *, call_id: str = "toolu_probe_0005", prefix: str = "big") -> list[dict[str, Any]]:
    """``n`` reruns of the real ``seq 1 12000`` call (about 17 KB stored each: head and tail of its output)."""
    for i in range(n):
        send_call(p, call_id, f"{prefix}{i}")
    p.drain()
    return [p.event("tool_finished", call=f"{call_id}_{prefix}{i}") for i in range(n)]


def placeholder_id() -> str:
    return derived_id("evt", [new_id("job")])


# --------------------------------------------------------------------------
# The kill/restart scenario (driven by worker_scenarios.py)

SCENARIO = "admission.json"
DECLARATION = "Keep the fixture tests on pytest."
CRASH_CLAIMS = {
    "obs": "`pytest -q test_mid.py` exited with code 1.",
    "inf1": "test_mid asserts a value the fixture never produces.",
    "inf2": "test_long fails before test_mid runs.",
    "inf3": "The fixture suite has two failing tests.",
    "decl": "The fixture tests stay on pytest.",
    "lesson": "Fix test_mid's fixture before rerunning it.",
}


def crash_project(tmp: Path, name: str) -> Path:
    """Real lifecycle events, a declaration prompt, one extraction job and a spooled trigger segment.

    Reduced in setup: the real lifecycle and a declaration prompt (variant).
    Its five lifecycle failures made debounce triggers due; their extraction
    jobs are cancelled (setup) so the matrix keeps its own jobs. Spooled, not
    ingested: a rerun of the failing ``test_mid`` followed by six relevant
    ``grep`` results (its trigger becomes due by count) and a failing
    ``test_long`` rerun fixed by a passing rerun of the same command (its
    trigger resolves). The extraction job proposes an observed fact (active
    without review), three inferences, a declaration and a failure lesson; its
    application schedules one review batch of five, whose recorded verdicts
    (built from the request) admit two, are duplicated for one, revise one,
    capacity-reject one and leave one missing.
    """
    p = wks.Project(tmp, name)
    p.scenario("lifecycle")
    p.drain()
    said = prompt(p, DECLARATION + " Do not migrate them.")
    osc.cancel_trigger_extractions(p.root)
    fail = p.event("tool_finished", call="toolu_probe_0003")
    quote = link(fail, field="result_text", quote="FAILED test_mid.py::test_mid")
    ops = [
        osc.op("obs", "propose_claim", claim(CRASH_CLAIMS["obs"], basis="observed", subject="obs"), evidence=[link(fail, mapping="tool.exit_code")]),
        osc.op("inf1", "propose_claim", claim(CRASH_CLAIMS["inf1"], subject="inf1"), evidence=[quote]),
        osc.op("inf2", "propose_claim", claim(CRASH_CLAIMS["inf2"], subject="inf2"), evidence=[link(p.event("tool_finished", call="toolu_probe_0002"))]),
        osc.op("inf3", "propose_claim", claim(CRASH_CLAIMS["inf3"], subject="inf3"), evidence=[quote]),
        osc.op("decl", "propose_claim", claim(CRASH_CLAIMS["decl"], kind="decision", basis="user_declared", subject="runner"), evidence=[link(said, field="text", quote=DECLARATION)]),
        osc.op("lesson", "propose_claim", lesson(CRASH_CLAIMS["lesson"]), evidence=[link(fail)]),
    ]
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        job_id, _ = jobs.enqueue(txn, kind="extract_claims", input_refs=[RecordRef(kind="event", id=fail["id"], revision=1)], now=utc_now(), prompt_version="extract_claims@1", due_at=osc.EARLIEST)
    send_call(p, "toolu_probe_0003", "crash_f")
    for i in range(6):
        send_call(p, "toolu_probe_0006", f"crash_n{i}")
    send_call(p, "toolu_probe_0002", "crash_g", )
    send_call(p, "toolu_probe_0002", "crash_ok", command="pytest -q test_long.py", outcome_of="toolu_probe_0004")
    (p.root / SCENARIO).write_text(json.dumps({"extraction_job": job_id, "extraction_body": osc.body(ops).decode("utf-8")}), encoding="utf-8")
    return p.root


def scenario(root: Path) -> dict[str, Any] | None:
    path = root / SCENARIO
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def crash_answer(spec: dict[str, Any], request: dict[str, Any], purpose: str) -> bytes:
    """The recorded body for one request of the scenario (built from the request where verdicts need batch IDs)."""
    if purpose == "extract_claims" and request["job_id"] == spec["extraction_job"]:
        return spec["extraction_body"].encode("utf-8")
    if purpose != "review_claims":
        return json.dumps({"operations": [], "no_op_reason": "nothing durable"}).encode("utf-8")
    batch = ReviewBatch.model_validate(request["review_batch"])
    claims = {c["claim_id"]: c for c in request["claims"]}
    ops: list[dict[str, Any]] = []
    for i, ref in enumerate(batch.candidate_refs):
        body = claims[ref.id]
        if i in (0, 1):
            ops.append(assess(batch, ref, "supported", local_ref=f"s{i}", evidence_ids=support_ids(batch, body)[:1]))
        elif i == 2:
            ops += [assess(batch, ref, "supported", local_ref="d1", evidence_ids=support_ids(batch, body)[:1]), assess(batch, ref, "reject", local_ref="d2", objections=["duplicate verdict"])]
        elif i == 3:
            ops.append(assess(batch, ref, "reject", local_ref="cap", objections=[review.CAPACITY]))
        # i == 4: no verdict (missing)
    if len(batch.candidate_refs) > 5:
        raise AssertionError("one fitting batch of five")
    return json.dumps({"operations": ops}).encode("utf-8")


def outstanding(root: Path) -> str:
    """``1`` while ingestion, reduction, the trigger pass, the extraction or a review is unfinished (read-only peek)."""
    import sqlite3

    path = root / ".recalith" / db.STATE_DB
    spec = scenario(root) or {}
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        reduced = conn.execute("SELECT commit_sequence FROM working_cursor").fetchone()[0]
        examined = conn.execute("SELECT commit_sequence FROM trigger_cursor").fetchone()[0]
        latest = conn.execute("SELECT COALESCE(MAX(commit_sequence), 0) FROM events").fetchone()[0]
        extraction = conn.execute("SELECT state FROM jobs WHERE job_id = ?", (spec.get("extraction_job"),)).fetchone()
        reviews = conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'review_claims' AND state NOT IN ('completed', 'cancelled', 'failed')").fetchone()[0]
        ready = any((root / ".recalith" / "spool" / "ready").glob("*.json"))
        # A candidate is owed a review until a review job names its revision or an outcome (e.g. deferral) records it.
        named = {(r["id"], r["revision"]) for (b,) in conn.execute("SELECT body FROM jobs WHERE kind = 'review_claims'").fetchall() for r in json.loads(b)["input_refs"]}
        named |= set(conn.execute("SELECT claim_id, claim_revision FROM review_outcomes").fetchall())
        owed = any((c, r) not in named for c, r in conn.execute("SELECT claim_id, revision FROM claim_heads WHERE status = 'candidate'").fetchall())
        busy = ready or reduced < latest or examined < reduced or extraction is None or extraction[0] != "completed" or reviews > 0 or owed
        return "1" if busy else "0"
    except sqlite3.Error:
        return "1"
    finally:
        conn.close()


def admission_state(root: Path) -> dict[str, Any]:
    """Claims by proposition, review outcomes, batches, review requests, triggers and the trigger cursor."""
    ctx = osc.context(root)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        props = {}
        claims = []
        for claim_id, revision, status, strength in view.execute("SELECT claim_id, revision, status, strength FROM claim_heads").fetchall():
            body = records.body(view, "claim", claim_id, revision)
            props[claim_id] = body["proposition"]
            assessment = body.get("review_assessment") or {}
            claims.append((body["proposition"], revision, status, strength, body["basis"], assessment.get("verdict"), tuple(assessment.get("objections") or ())))
        outcomes_ = sorted((props.get(c, c), rev, o, r) for c, rev, o, r in view.execute("SELECT claim_id, claim_revision, outcome, reason_code FROM review_outcomes").fetchall())
        batches = sorted(len(json.loads(b)["candidate_refs"]) for (b,) in view.execute("SELECT body FROM review_batches").fetchall())
        persisted = view.execute("SELECT COUNT(DISTINCT review_job_id) FROM review_batches").fetchone()[0]
        requests_ = sorted((o, i, origin is not None) for o, i, origin in view.execute("SELECT origin, partition_index, origin_job_id FROM review_requests").fetchall())
        priorities = sorted(r for (r,) in view.execute("SELECT review_priority FROM jobs WHERE kind = 'review_claims'").fetchall())
        events = {e: k for e, k in view.execute("SELECT event_id, source_event_key FROM events").fetchall()}
        trigs = sorted((events.get(f, f), fam is not None, n, st, why, events.get(by, by) if by else None, job is not None) for f, fam, n, st, why, by, job in view.execute(
            "SELECT failure_event_id, action_family_digest, subsequent_event_count, state, due_reason, resolved_by, job_id FROM failure_triggers"
        ).fetchall())
        cursor = view.execute("SELECT commit_sequence FROM trigger_cursor").fetchone()[0]
    return {"claims": sorted(claims), "outcomes": outcomes_, "batches": (persisted, batches[-1:]), "review_requests": requests_, "priorities": priorities, "triggers": trigs, "trigger_cursor": cursor}
