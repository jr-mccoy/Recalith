"""Test-only builders for Task 10: consolidation, revalidation and FailureRecheck over real payloads.

Real inputs: every Claude event enters through the real 2.1.301 adapter
mapping, normalization, capture, ingestion and typed reduction
(``working_scenarios.Project``). Real payloads used: the lifecycle session's
failing ``pytest -q test_mid.py`` (``toolu_probe_0003``, certified exit code
1 and pytest assertions), the passing ``pytest -q -s test_pass.py`` result
(``toolu_probe_0004``), the ``Write`` of ``new.txt`` (``toolu_probe_0009``),
the ``echo`` call and the prompts.

**Synthetic variants** (named at each use; payload shape, mapping and
normalization stay real): a rerun of the failing command whose result is the
real passing result (a fixed failure), under a new tool-use ID and a
controlled capture time; the same in a second host session or another
package directory (``cwd`` under the workspace); the same command through a
pipeline (an inexact parse: unknown family); a ``Write`` of another workspace
path (a dependency file); a ``git merge`` command over the real ``echo``
result; prompt texts for user declarations; and capture times equal to,
before or after the failure's.

**Model behavior is recorded proposals** through the real persisted-proposal
path (lease, ``persist_proposal`` under the fence, ``apply_proposal``):
extraction bodies, review verdicts and revalidation decisions exercise the
mechanics, not live revalidation quality (ACCEPTANCE_TESTS §5 stays
unavailable without a certified route, B1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Sequence

import admission_scenarios as adm  # first: puts tests/, tests/integration and tests/platform on sys.path
import operation_scenarios as osc  # noqa: E402
import working_scenarios as wks  # noqa: E402
from recalith.capture import pipeline  # noqa: E402
from recalith.contracts.common import RecordRef, utc_now  # noqa: E402
from recalith.contracts.context import ContextQuery  # noqa: E402
from recalith.contracts.jobs import Job  # noqa: E402
from recalith.contracts.memory import ClaimRevision  # noqa: E402
from recalith.contracts.operations import ModelRequest  # noqa: E402
from recalith.controller import apply, requests, revalidate  # noqa: E402
from recalith.storage import db, records  # noqa: E402

MID = "toolu_probe_0003"  # failing `pytest -q test_mid.py`
PASS = "toolu_probe_0004"  # the real passing pytest result
WRITE = "toolu_probe_0009"  # Write new.txt
ECHO = "toolu_probe_0001"  # echo hello-fixture
DEP = "dep.txt"
LESSON = "Rerunning test_mid without fixing its fixture fails again."


def project(tmp: Path, name: str = "revision", *, dep: bytes | None = b"fixture v1\n") -> wks.Project:
    """The real lifecycle session, reduced; trigger extractions cancelled; an optional dependency file."""
    p = adm.project(tmp, name)
    osc.cancel_trigger_extractions(p.root)
    if dep is not None:
        (p.root / DEP).write_bytes(dep)
    return p


def failure(p: wks.Project) -> dict[str, Any]:
    return p.event("tool_finished", call=MID)


def recorded_at(p: wks.Project, event_id: str) -> str:
    with p.view() as v:
        return v.execute("SELECT recorded_at FROM events WHERE event_id = ?", (event_id,)).fetchone()[0]


# --------------------------------------------------------------------------
# Claims


def lesson_body(proposition: str = LESSON, *, deps: Sequence[str] = (DEP,), conditions: Sequence[dict[str, Any]] = (), subject: str = "test_mid", scope: dict[str, Any] | None = None) -> dict[str, Any]:
    body = adm.lesson(proposition)
    body["proposition_key"] = {"subject": subject, "predicate": "fails_without_fix"}
    body["dependencies"] = [{"kind": "file", "key": k, "fingerprint": None, "record": None} for k in deps]
    body["conditions"] = list(conditions)
    if scope is not None:
        body["scope"] = scope
    return body


def lesson(p: wks.Project, proposition: str = LESSON, *, evidence: dict[str, Any] | None = None, admit: bool = True, **kw: Any) -> str:
    """An extracted failure lesson citing a certified failure, admitted through a supported review."""
    ev = evidence or failure(p)
    claim_id = adm.created_claim(adm.extract(p, [osc.op("l", "propose_claim", lesson_body(proposition, **kw), evidence=[adm.link(ev)])]))
    if admit:
        adm.admit(p, claim_id)
    return claim_id


def fact(p: wks.Project, proposition: str, *, subject: str, predicate: str = "observed", evidence: dict[str, Any] | None = None, admit: bool = True, **extra: Any) -> str:
    body = adm.claim(proposition, subject=subject, **extra)
    body["proposition_key"]["predicate"] = predicate
    claim_id = adm.created_claim(adm.extract(p, [osc.op("f", "propose_claim", body, evidence=[adm.link(evidence or failure(p))])]))
    if admit:
        adm.admit(p, claim_id)
    return claim_id


def declaration(p: wks.Project, text: str, proposition: str, *, subject: str, kind: str = "decision", admit: bool = True) -> str:
    said = adm.prompt(p, text)
    body = adm.claim(proposition, kind=kind, basis="user_declared", subject=subject)
    body["proposition_key"]["predicate"] = "chosen"
    claim_id = adm.created_claim(adm.extract(p, [osc.op("d", "propose_claim", body, evidence=[adm.link(said, field="text")])]))
    if admit:
        adm.admit(p, claim_id)
    return claim_id


def head(p: wks.Project, claim_id: str) -> dict[str, Any]:
    return adm.head(p, claim_id)


def claim(p: wks.Project, claim_id: str) -> ClaimRevision:
    with p.view() as v:
        revision, _status = records.head(v, "claim", claim_id)
        return records.load(v, "claim", claim_id, revision)


# --------------------------------------------------------------------------
# Events (synthetic variants of real records)


def send(p: wks.Project, tool_use_id: str, suffix: str, *, outcome_of: str | None = None, command: str | None = None, at: str | None = None, session: str | None = None, cwd: str | None = None, replace: dict[str, str] | None = None) -> None:
    """A rerun of a real call: new tool-use ID; optional real result of another call, command, session, cwd, time."""
    lifecycle = wks.cf.records("lifecycle")
    pre = [r for r in lifecycle if r["event"] == "PreToolUse" and r["payload"].get("tool_use_id") == tool_use_id]
    source = outcome_of or tool_use_id
    post = [r for r in lifecycle if r["event"] in ("PostToolUse", "PostToolUseFailure") and r["payload"].get("tool_use_id") == source]
    swap = dict(replace or {})
    if cwd is not None:
        swap['"cwd": "<workspace>"'] = f'"cwd": "<workspace>/{cwd}"'
    for rec in pre:
        p.send(wks.variant(rec, tool_suffix=suffix, command=command, session=session, replace=swap), at=at)
    for rec in post:
        if outcome_of:
            rec = wks.variant(rec, replace={source: tool_use_id})
            rec["payload"]["tool_input"] = json.loads(json.dumps(pre[0]["payload"]["tool_input"]))
        p.send(wks.variant(rec, tool_suffix=suffix, command=command, session=session, replace=swap), at=at)


def success(p: wks.Project, suffix: str, *, drain: bool = False, **kw: Any) -> dict[str, Any]:
    """The failing command rerun with the real passing result (a fixed failure); ingested, optionally drained."""
    send(p, MID, suffix, outcome_of=PASS, **kw)
    ingest(p, drain=drain)
    return p.event("tool_finished", call=f"{MID}_{suffix}")


def write(p: wks.Project, suffix: str, path: str = DEP, *, content: bytes | None = b"fixture v2\n", drain: bool = False) -> dict[str, Any]:
    """A certified Write of a workspace path (the real Write payload, another path), and the file itself changed."""
    if content is not None:
        (p.root / path).write_bytes(content)
    send(p, WRITE, suffix, replace={"new.txt": path})
    ingest(p, drain=drain)
    return p.event("tool_finished", call=f"{WRITE}_{suffix}")


def ingest(p: wks.Project, *, drain: bool = False) -> None:
    """Ingestion only (no worker job, no model, no budget), or a full drain."""
    if drain:
        p.drain()
    else:
        pipeline.ingest_ready(p.ctx)


# --------------------------------------------------------------------------
# Guidance, rechecks and jobs


def query(p: wks.Project, *, environment: dict[str, str] | None = None, branch: str | None = None) -> ContextQuery:
    return ContextQuery(session_id=p.session_of(), task_id=None, workspace_id=p.ctx.workspace_id, purpose="pre_action", text="pytest -q test_mid.py", environment=environment or {}, branch_ref=branch)


def advice(p: wks.Project, claim_id: str, **kw: Any) -> revalidate.Guidance:
    c = claim(p, claim_id)
    with p.view() as v:
        return revalidate.guidance(v, p.ctx, c, query(p, **kw))


def rechecks(p: wks.Project, claim_id: str | None = None, states: Sequence[str] = ("pending", "deferred", "cleared")) -> list[dict[str, Any]]:
    with p.view() as v:
        return revalidate.rechecks(v, claim_id, states=states)


def jobs_of(p: wks.Project, kind: str = "revalidate", claim_id: str | None = None, *, states: Sequence[str] = ("pending", "waiting_budget", "leased", "completed", "cancelled", "failed")) -> list[Job]:
    with p.view() as v:
        rows = v.execute("SELECT body FROM jobs WHERE kind = ? ORDER BY rowid", (kind,)).fetchall()
    out = [Job.model_validate_json(r[0]) for r in rows]
    return [j for j in out if j.state in states and (claim_id is None or any(r.id == claim_id for r in j.input_refs))]


def epoch(p: wks.Project) -> int:
    return osc.meta(p.root).guidance_epoch


def run_revalidation(p: wks.Project, job_id: str, decide: Callable[[ModelRequest], list[dict[str, Any]]], *, no_op_reason: str | None = None):
    """Prepare the job through the production preparer and apply the recorded decision (returns request, result)."""
    job = adm.lease(p, job_id)
    request = requests.prepare_model_request(p.ctx, job, now=utc_now())
    ops = decide(request)
    response = osc.response(ops, purpose="revalidate", no_op_reason=no_op_reason if no_op_reason or ops else "keep")
    with db.open_store(p.ctx) as store:
        apply.persist_proposal(store, job, response, request.read_set, now=utc_now())
        result = apply.apply_proposal(p.ctx, job, response, store=store, now=utc_now())
    return request, result


def keep(_request: ModelRequest) -> list[dict[str, Any]]:
    return []


def ref(p: wks.Project, claim_id: str) -> dict[str, Any]:
    return osc.head_ref(p.root, "claim", claim_id).model_dump(mode="json")


def status_op(p: wks.Project, local_ref: str, claim_id: str, status: str, *, evidence: Sequence[dict[str, Any]] = (), replacement: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"claim_ref": ref(p, claim_id), "status": status}
    if replacement is not None:
        payload["replacement_ref"] = ref(p, replacement)
    return osc.op(local_ref, "change_claim_status", payload, evidence=list(evidence), target=ref(p, claim_id))


def link(ev: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return adm.link(ev, **kw)


def event_ref(event_id: str) -> RecordRef:
    return RecordRef(kind="event", id=event_id, revision=1)


# --------------------------------------------------------------------------
# The kill/restart scenario (driven by worker_scenarios.py)

SCENARIO = "revision.json"
CRASH = {
    "mid": "Rerunning test_mid without fixing its fixture fails again.",
    "long": "Rerunning test_long without shortening its output fails again.",
    "suite": "The fixture suite's guidance follows the test_mid lesson.",
}
RETRY = "A rerun of test_mid passes once its fixture provides the value."


def crash_project(tmp: Path, name: str) -> Path:
    """Reduced: the lifecycle, an admitted lesson with a file dependency, a dependent fact, a lesson under review.

    Spooled, not ingested: a passing rerun of ``test_mid`` (FailureRecheck,
    ``later_success``), a ``Write`` of the dependency file (dependency change,
    transitively to the dependent fact) and a passing rerun of ``test_long``
    (a deferred recheck of the lesson still under review). The recorded
    answers: the review of the ``test_long`` lesson supports it (activation
    promotes its deferred recheck and queues its revalidation); the
    revalidation revises the ``test_mid`` lesson with a retry condition (a
    reviewed candidate revision, then supported again), keeps the dependent
    fact and retires the ``test_long`` lesson; extractions answer no-op.
    """
    p = project(tmp, name)
    mid = lesson(p, CRASH["mid"])
    fact(p, CRASH["suite"], subject="suite", dependencies=[{"kind": "claim", "key": "lesson", "fingerprint": None, "record": ref(p, mid)}])
    lesson(p, CRASH["long"], evidence=p.event("tool_finished", call="toolu_probe_0002"), subject="test_long", deps=(), admit=False)
    osc.cancel_trigger_extractions(p.root)
    send(p, MID, "crash_ok", outcome_of=PASS)
    (p.root / DEP).write_bytes(b"fixture v2\n")
    send(p, WRITE, "crash_w", replace={"new.txt": DEP})
    send(p, "toolu_probe_0002", "crash_ok", outcome_of=PASS)
    (p.root / SCENARIO).write_text(json.dumps({"revision": True}), encoding="utf-8")
    return p.root


def scenario(root: Path) -> dict[str, Any] | None:
    path = root / SCENARIO
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def crash_answer(spec: dict[str, Any], request: dict[str, Any], purpose: str) -> bytes:
    """The recorded body for one request of the scenario (built from the request)."""
    if purpose == "review_claims":
        return osc.body(adm.supported_all(ModelRequest.model_validate(request)))
    if purpose != "revalidate":
        return osc.body([], "nothing durable")
    ops: list[dict[str, Any]] = []
    for c in request["claims"]:
        target = {"kind": "claim", "id": c["claim_id"], "revision": c["revision"]}
        if c["proposition"] == CRASH["mid"] and c["status"] == "active":
            success_id = next(link["ref"]["id"] for link in c["context"] if link["ref"]["kind"] == "event")
            retry = {"text": RETRY, "evidence": [{"ref": {"kind": "event", "id": success_id, "revision": 1}, "relation": "supports", "root_event_ids": [success_id], "locator": None, "mapping": None}], "basis": "inferred"}
            ops.append(osc.op("mid", "revise_claim", {"claim_ref": target, "retry_conditions": [retry]}, target=target))
        elif c["proposition"] == CRASH["long"] and c["status"] == "active":
            ops.append(osc.op("long", "change_claim_status", {"claim_ref": target, "status": "archived"}, target=target))
    return osc.body(ops, None if ops else "keep")


def outstanding(root: Path) -> str:
    """``1`` while ingestion, reduction, a recheck (owed or recorded), a revalidation or a review is unfinished (read-only)."""
    import sqlite3

    from recalith.capture.normalize import action_family_digest

    path = root / ".recalith" / db.STATE_DB
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        ready = any((root / ".recalith" / "spool" / "ready").glob("*.json"))
        reduced = conn.execute("SELECT commit_sequence FROM working_cursor").fetchone()[0]
        latest = conn.execute("SELECT COALESCE(MAX(commit_sequence), 0) FROM events").fetchone()[0]
        busy = conn.execute("SELECT COUNT(*) FROM jobs WHERE kind IN ('revalidate', 'review_claims') AND state NOT IN ('completed', 'cancelled', 'failed')").fetchone()[0]
        # Owed, even when nothing records it yet: a later certified success of a live lesson's family, or a write of
        # its dependency file, with no recheck naming that event.
        live = conn.execute("SELECT claim_id, revision, action_family_digest FROM claim_heads WHERE kind = 'failure_lesson' AND status IN ('candidate', 'active', 'disputed')").fetchall()
        named = {(c, e) for c, e in conn.execute("SELECT claim_id, event_id FROM claim_rechecks").fetchall()}
        owed = False
        for event_id, ws_id, payload in conn.execute("SELECT event_id, workspace_id, payload FROM events WHERE kind = 'tool_finished' AND source_event_key LIKE '%crash_%'").fetchall():
            data = json.loads(payload)
            action = data.get("action") or {}
            family = action_family_digest(ws_id, action)
            writes = DEP in (action.get("paths") or []) and action.get("action_kind") == "write"
            for claim_id, revision, fam in live:
                body = json.loads(conn.execute("SELECT body FROM claim_revisions WHERE claim_id = ? AND revision = ?", (claim_id, revision)).fetchone()[0])
                if (family is not None and family == fam and data.get("outcome") == "success") or (writes and any(d["key"] == DEP for d in body["dependencies"])):
                    owed = owed or (claim_id, event_id) not in named
        recorded = conn.execute(
            "SELECT COUNT(*) FROM claim_rechecks r JOIN claim_heads h ON h.claim_id = r.claim_id WHERE (r.state = 'pending' AND r.reason != 'source_conflict' AND h.status IN ('candidate', 'active', 'disputed')) "
            "OR (r.state = 'deferred' AND h.status = 'candidate')"
        ).fetchone()[0]
        named_reviews = {r["id"] for (b,) in conn.execute("SELECT body FROM jobs WHERE kind = 'review_claims'").fetchall() for r in json.loads(b)["input_refs"]}
        named_reviews |= {c for (c,) in conn.execute("SELECT claim_id FROM review_outcomes").fetchall()}
        unreviewed = any(c not in named_reviews for (c,) in conn.execute("SELECT claim_id FROM claim_heads WHERE status = 'candidate'").fetchall())
        return "1" if ready or reduced < latest or busy or owed or recorded or unreviewed else "0"
    except sqlite3.Error:
        return "1"
    finally:
        conn.close()


def revision_state(root: Path) -> dict[str, Any]:
    """Claims by proposition (status, freshness, strength, retry conditions, context), rechecks, supersessions, questions."""
    ctx = osc.context(root)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        props: dict[str, str] = {}
        claims = []
        for claim_id, revision, status in view.execute("SELECT claim_id, revision, status FROM claim_heads").fetchall():
            body = records.body(view, "claim", claim_id, revision)
            props[claim_id] = body["proposition"]
            retry = tuple(r["text"] for r in (body.get("failure") or {}).get("retry_conditions") or [])
            claims.append((body["proposition"], status, body["freshness"], body["strength"], retry, len(body.get("context") or []), len(body["dependencies"])))
        events = {e: k for e, k in view.execute("SELECT event_id, source_event_key FROM events").fetchall()}
        checks = sorted((props.get(c, c), reason, events.get(e, e) if e else None, state, outcome) for c, reason, e, state, outcome in view.execute("SELECT claim_id, reason, event_id, state, outcome FROM claim_rechecks").fetchall())
        audits = view.execute("SELECT COUNT(*) FROM operations WHERE kind IN ('recheck', 'revalidation')").fetchone()[0]
        writes = sorted(events.get(e, e) for (e,) in view.execute("SELECT event_id FROM artifact_writes").fetchall())
        epoch = view.execute("SELECT guidance_epoch FROM installation_meta").fetchone()[0]
    return {"claims": sorted(claims), "rechecks": checks, "audits": audits, "writes": writes, "epoch": epoch}
