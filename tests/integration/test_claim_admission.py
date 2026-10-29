"""Task 9: claim extraction, deterministic admission, adversarial review and failure debounce.

Acceptance: A14–A17, A60, A66 and the A50 review-batch parts (ACCEPTANCE_TESTS §2).
Every event enters through the real Claude Code 2.1.301 adapter, normalization,
capture, ingestion and typed reduction; model behavior is recorded proposals
through the real persisted-proposal path (``admission_scenarios``). These are
mechanics: live extraction and review quality (ACCEPTANCE_TESTS §5) need a
certified route and remain unavailable (B1).
"""

from __future__ import annotations

import json

import pytest

import admission_scenarios as adm
import operation_scenarios as osc
import working_scenarios as wks
import worker_scenarios as ws
from recalith import prompts
from recalith.contracts.common import EvidenceLink, RecordRef, canonical_json, derived_id, digest_of, new_id, utc_now
from recalith.contracts.config import MODEL_INPUT_CAP, BudgetConfig
from recalith.contracts.memory import ClaimRevision
from recalith.controller import admission, budgets, extract, jobs, requests, review, triggers, worker
from recalith.core import regions
from recalith.errors import RecalithError
from recalith.storage import db, failpoints, records

OP = osc.op


@pytest.fixture(autouse=True)
def _disarm():
    failpoints.disarm_all()
    yield
    failpoints.disarm_all()


@pytest.fixture
def p(tmp_path):
    return adm.project(tmp_path)


def decisions(result) -> list[tuple[str, str]]:
    return [(d.outcome, d.reason_code) for d in result.decisions]


def fail_mid(p):
    return p.event("tool_finished", call="toolu_probe_0003")  # pytest -q test_mid.py: exit 1, certified assertions


def exhaust_budget(p, now: str) -> None:
    config = BudgetConfig()
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        for purpose in ("review_claims", "extract_claims"):
            for i in range(config.daily_invocations + 1):
                if isinstance(budgets.reserve(txn, job_id=derived_id("job", [purpose, i, now]), purpose=purpose, input_estimate=100, now=now, config=config), budgets.Refusal):
                    break


# ---------------------------------------------------------------------------
# Plan-named tests


def test_quote_exists_but_cause_is_unsupported(p):
    """A15: a real event is cited, with an exact quote, for a causal explanation: never observed; inferred waits for review."""
    fail = fail_mid(p)
    quote = adm.link(fail, field="result_text", quote="FAILED test_mid.py::test_mid", mapping=None)
    mapped = adm.link(fail, mapping="tool.exit_code")
    cause = "test_mid fails because the fixture database is down."
    result = adm.extract(p, [
        OP("as_observed", "propose_claim", adm.claim(cause, basis="observed"), evidence=[mapped, quote]),
        OP("as_observed_quote", "propose_claim", adm.claim(cause, basis="observed", subject="quoted"), evidence=[{**quote, "mapping": "tool.exit_code"}]),
        OP("as_lesson", "propose_claim", {**adm.lesson("Never run test_mid without a database."), "basis": "observed"}, evidence=[mapped]),
        OP("as_inferred", "propose_claim", adm.claim(cause, subject="inferred"), evidence=[quote]),
    ])
    assert decisions(result) == [
        ("reject", "observed_requires_mapping"),  # the quote link carries no mapping: a quote is not a typed observation
        ("reject", "mapping_locator_mismatch"),  # an exit-code mapping cannot point at prose
        ("reject", "observed_requires_fact"),  # a lesson is never mechanically observed (A13/A66: not from exit status alone)
        ("candidate_only", "candidate_pending_review"),
    ]
    inferred = adm.head(p, adm.created_claim(result))
    assert inferred["basis"] == "inferred" and inferred["status"] == "candidate" and inferred["strength"] == "weak"
    # The only observed claim the event supports is the code rendering of what the tool reported.
    wrong = adm.extract(p, [OP("wide", "propose_claim", adm.claim("`pytest -q test_mid.py` exited with code 1 because of the database.", basis="observed"), evidence=[mapped])])
    assert decisions(wrong) == [("reject", "observed_proposition_unmapped")]
    exact = adm.extract(p, [OP("exact", "propose_claim", adm.claim("`pytest -q test_mid.py` exited with code 1.", basis="observed"), evidence=[mapped])])
    assert decisions(exact) == [("apply", "observed_mapping")]
    observed = adm.head(p, adm.created_claim(exact))
    assert (observed["status"], observed["strength"], observed["basis"], observed["review_assessment"]) == ("active", "supported", "observed", None)
    assert adm.review_jobs(p, observed["claim_id"]) == []  # a verified mapping needs no model
    # The inferred cause becomes active only through its review, and stays labeled inferred.
    adm.admit(p, inferred["claim_id"])
    after = adm.head(p, inferred["claim_id"])
    assert (after["status"], after["basis"], after["strength"], after["review_assessment"]["verdict"]) == ("active", "inferred", "supported", "supported")


def test_typed_declaration_waits_for_review(p, tmp_path):
    """A60: the operator's typed declaration route gets no bypass, and never admits while its review is budget-paused.

    The guarded ``recalith declare`` transport and its ``operator_declaration``
    event are Task 12a; here the operator service route submits a declaration
    that cites a real captured user statement (synthetic prompt variant).
    """
    said = adm.prompt(p, "Keep the fixture tests on pytest; do not migrate them.", at_=adm.at(1))
    decl = adm.claim("Keep the fixture tests on pytest.", kind="decision", basis="user_declared", subject="test runner")
    result = adm.operator_submit(p, [OP("decl", "propose_claim", decl, evidence=[adm.link(said, field="text", quote="Keep the fixture tests on pytest; do not migrate them.")])])
    assert decisions(result) == [("candidate_only", "candidate_pending_review")]
    claim_id = adm.created_claim(result)
    head = adm.head(p, claim_id)
    assert (head["status"], head["strength"], head["review_class"]) == ("candidate", "weak", "stable")
    (job,) = adm.review_jobs(p, claim_id)
    assert job.review_priority == "correction_or_declaration" and job.priority == jobs.BAND_DECLARATION_REVIEW
    with p.view() as v:
        assert v.execute("SELECT origin, origin_job_id FROM review_requests WHERE review_job_id = ?", (job.job_id,)).fetchone() == ("typed_declaration", None)
    # No route around review: the operator cannot assess, and a revision is another unreviewed candidate.
    ref = osc.head_ref(p.root, "claim", claim_id)
    refused = adm.operator_submit(p, [adm.assess(_fake_batch(ref), ref, "supported", local_ref="self", evidence_ids=["evd_" + "0" * 64])])
    assert decisions(refused) == [("reject", "kind_not_permitted")]
    assert adm.head(p, claim_id)["status"] == "candidate"
    # Budget-paused review: the declaration stays a weak candidate and nothing launches.
    clock = ws.FakeClock(adm.at(5))
    exhaust_budget(p, clock.now())
    backend = ws.FakeBackend(lambda purpose, i: worker.LaunchOutcome(stdout=ws.envelope(backend.body)))
    backend.body = b""

    def answer(request: bytes, purpose: str) -> None:
        data = json.loads(request)
        backend.body = osc.body(adm.supported_all(requests.ModelRequest.model_validate(data))) if purpose == "review_claims" else osc.body([], "nothing")

    backend.on_launch = answer
    w = worker.Worker(p.ctx, clock=clock, model=ws.runtime(backend, requests.runtime_preparer(p.ctx)))
    try:
        assert w.lane.step() is False and backend.calls == []
        waiting = adm.review_jobs(p, claim_id)[0]
        assert waiting.state == "waiting_budget" and waiting.last_error_code.startswith("budget_exhausted:protected+ordinary.")
        assert adm.head(p, claim_id)["status"] == "candidate"
        clock.advance(24 * 3600)  # the next UTC day has a fresh ledger; the review runs, and only then admits
        while w.lane.step():
            pass
    finally:
        w.close()
    assert ("review_claims", job.job_id) in backend.calls
    admitted = adm.head(p, claim_id)
    assert (admitted["status"], admitted["strength"], admitted["review_assessment"]["verdict"]) == ("active", "supported", "supported")


def _fake_batch(ref: RecordRef):
    from recalith.contracts.common import ReadSet
    from recalith.contracts.memory import ReviewBatch

    return ReviewBatch(batch_id=new_id("batch"), origin_job_id=None, review_job_id=new_id("job"), candidate_refs=[ref], candidate_digests={ref.id: "0" * 64}, evidence_digest="0" * 64, prompt_digest="0" * 64, read_set=ReadSet(workspace_id=new_id("ws"), policy_revision=1, tombstone_epoch=0))


def test_inferred_claim_waits_for_review(p):
    """A14/A15: an extracted inference is a weak candidate until a supported review; revise changes nothing but objections."""
    fail = fail_mid(p)
    result = adm.extract(p, [OP("c", "propose_claim", adm.claim("test_mid asserts a value the fixture never produces."), evidence=[adm.link(fail, field="result_text", quote="FAILED test_mid.py::test_mid")])])
    claim_id = adm.created_claim(result)
    head = adm.head(p, claim_id)
    assert (head["status"], head["strength"], head["review_assessment"]) == ("candidate", "weak", None)
    with pytest.raises(ValueError, match="supported review"):  # the record itself cannot be active without one
        ClaimRevision.model_validate({**{k: v for k, v in head.items() if k != "head_status"}, "status": "active"})
    (job,) = adm.review_jobs(p, claim_id)
    _request, revised = adm.run_review(p, job.job_id, lambda r: [adm.assess(r.review_batch, r.review_batch.candidate_refs[0], "revise", local_ref="a0", objections=["Overbroad: only one run of test_mid was observed."])])
    assert decisions(revised) == [("apply", "review_revise")]
    after = adm.head(p, claim_id)
    assert (after["status"], after["proposition"], after["review_assessment"]["objections"]) == ("candidate", head["proposition"], ["Overbroad: only one run of test_mid was observed."])
    assert adm.review_jobs(p, claim_id, states=("pending",)) == []  # an assessment never schedules another review
    # A resubmitted, changed proposition is a new candidate with its own review, which can admit it.
    again = adm.extract(p, [OP("c2", "propose_claim", adm.claim("One run of test_mid failed its assertion.", subject="narrow"), evidence=[adm.link(fail, field="result_text", quote="FAILED test_mid.py::test_mid")])])
    narrow = adm.created_claim(again)
    adm.admit(p, narrow)
    assert adm.head(p, narrow)["status"] == "active" and adm.head(p, claim_id)["status"] == "candidate"


def test_retrieval_count_never_increases_strength(p):
    """A16/A17: retrieval, delivery telemetry, repetition and model self-confidence never raise strength; a new class may."""
    fail = fail_mid(p)
    base = adm.link(fail, field="result_text", quote="FAILED test_mid.py::test_mid")
    result = adm.extract(p, [OP("c", "propose_claim", adm.claim("test_mid fails its assertion.", subject="test_mid"), evidence=[base], reason="CONFIDENCE 0.999: retrieved 40 times, certainly true")])
    claim_id = adm.created_claim(result)
    adm.admit(p, claim_id)
    start = adm.head(p, claim_id)
    assert (start["status"], start["strength"]) == ("active", "supported")
    # Retrieval: delivery receipts and memory telemetry are not observations.
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        cols = [r[1] for r in txn.execute("PRAGMA table_info(deliveries)").fetchall()]
        assert "delivery_id" in cols
    telemetry = _memory_delivered(p, claim_id)
    ref = osc.head_ref(p.root, "claim", claim_id)
    attach = adm.extract(p, [OP("t", "attach_evidence", {"claim_ref": ref.model_dump(mode="json"), "relation": "supports"}, evidence=[{"ref": {"kind": "event", "id": telemetry, "revision": 1}, "relation": "supports", "root_event_ids": [], "locator": None, "mapping": None}], reason="retrieved again: confidence 1.0")])
    assert decisions(attach) == [("apply", "no_independent_root")]
    # An unchanged rerun stays in its class.
    rerun = adm.call(p, "toolu_probe_0003", "rerun")
    ref = osc.head_ref(p.root, "claim", claim_id)
    again = adm.extract(p, [OP("r", "attach_evidence", {"claim_ref": ref.model_dump(mode="json"), "relation": "supports"}, evidence=[adm.link(rerun, field="result_text", quote="FAILED test_mid.py::test_mid")])])
    assert decisions(again) == [("apply", "duplicate_evidence")]
    same = adm.head(p, claim_id)
    assert (same["revision"], same["strength"], same["last_supported_at"]) == (start["revision"], "supported", start["last_supported_at"])
    # A genuinely new observation class (a changed invocation) may add support: corroborated.
    other = adm.call(p, "toolu_probe_0003", "verbose", command="pytest -q -x test_mid.py", at_=adm.at(3))
    ref = osc.head_ref(p.root, "claim", claim_id)
    new = adm.extract(p, [OP("n", "attach_evidence", {"claim_ref": ref.model_dump(mode="json"), "relation": "supports"}, evidence=[adm.link(other, field="result_text", quote="FAILED test_mid.py::test_mid")])])
    assert decisions(new) == [("apply", "admitted")]
    final = adm.head(p, claim_id)
    assert final["strength"] == "corroborated" and final["last_supported_at"] == adm.at(3)
    # Strength is a function of lineage alone: recomputing ignores retrieval counts and reasons.
    with p.view() as v:
        assert admission.assign_strength(v, final) == "corroborated"
        assert admission.assign_strength(v, {**final, "status": "candidate"}) == "weak"


def _memory_delivered(p, claim_id: str) -> str:
    """A memory_delivered telemetry event through the real normalization (no 2.1.301 hook emits one yet)."""
    from recalith.capture import pipeline
    from recalith.capture.normalize import RawEvent, normalize_event

    raw = RawEvent(adapter_id="claude_code", adapter_version="2.1.301", source_event_key=f"delivery:{new_id('dlv')}", session_id=p.session_of("session_started"), host_session_id=wks.LIFECYCLE_SESSION, kind="memory_delivered", payload={"record_ids": [claim_id], "purpose": "prompt"})
    envelopes, _notes = normalize_event(p.ctx, raw)
    assert pipeline.capture(p.ctx, envelopes).status == "accepted"
    p.drain()
    return envelopes[0].event_id


# ---------------------------------------------------------------------------
# Deterministic mappings (A14, A52)


def test_mapping_validators_are_exact(p):
    fail = fail_mid(p)  # exit 1 with exit_status and pytest test_result assertions
    success = p.event("tool_finished", call="toolu_probe_0004")  # PostToolUse never certifies exit 0 (decision 0005)
    prompt_ev = p.events("user_message")[0]
    assertions = fail["payload"]["assertions"]
    status = next(i for i, a in enumerate(assertions) if a["kind"] == "exit_status")
    session = next(i for i, a in enumerate(assertions) if a["identity"] == "pytest:session")

    def check(ev, **kw):
        with p.view() as v:
            return admission.check_mapping(v, EvidenceLink.model_validate(adm.link(ev, **kw)))

    assert check(fail, mapping="tool.exit_code") == (None, "`pytest -q test_mid.py` exited with code 1.")
    assert check(fail, mapping="tool.exit_code", field=f"assertions.{status}.value") == (None, "`pytest -q test_mid.py` exited with code 1.")
    assert check(fail, mapping="tool.exit_code", field="result_text", quote="FAILED")[0] == "mapping_locator_mismatch"
    assert check(success, mapping="tool.exit_code")[0] == "mapping_requires_exit_code"
    assert check(prompt_ev, mapping="tool.exit_code")[0] == "mapping_requires_tool_result"
    assert check(fail, mapping="tool.reported_result")[0] == "mapping_requires_assertion"
    assert check(fail, mapping="tool.reported_result", field=f"assertions.{status}.value")[0] == "mapping_requires_assertion"  # exit status is tool.exit_code's
    assert check(fail, mapping="tool.reported_result", field=f"assertions.{session}.value", start=0, end=1)[0] == "mapping_requires_assertion"  # the whole value or nothing
    assert check(fail, mapping="tool.reported_result", field=f"assertions.{session}.value") == (None, "`pytest -q test_mid.py` reported test_result pytest:session: 1 failed (failed).")
    assert check(success, mapping="tool.reported_result", field="assertions.0.value") == (None, "`pytest -q -s test_pass.py` reported test_result pytest:session: 1 passed (passed).")
    assert check(fail, mapping="config.exact_value")[0] == "mapping_parser_unregistered"  # no registered config parser yet
    # An invalid mapping fails its group wherever it appears; independent groups apply (A14).
    result = adm.extract(p, [
        OP("bad_inferred", "propose_claim", adm.claim("test_mid failed.", subject="a"), evidence=[adm.link(success, mapping="tool.exit_code")]),
        OP("config", "propose_claim", adm.claim("x", basis="observed", subject="b"), evidence=[adm.link(fail, mapping="config.exact_value")]),
        OP("reported", "propose_claim", adm.claim("`pytest -q test_mid.py` reported test_result pytest:session: 1 failed (failed).", basis="observed", subject="c"), evidence=[adm.link(fail, mapping="tool.reported_result", field=f"assertions.{session}.value")]),
    ])
    assert decisions(result) == [("reject", "mapping_requires_exit_code"), ("reject", "mapping_parser_unregistered"), ("apply", "observed_mapping")]


def test_altered_quote_or_invented_event_rejects_only_its_group(p):
    """A14 with semantic gates: a misquote or a never-captured event fails its group; a valid independent claim applies."""
    fail = fail_mid(p)
    altered = adm.link(fail, field="result_text", quote="FAILED test_mid.py::test_mid")
    altered["locator"]["text_digest"] = digest_of("not the quoted text")
    result = adm.extract(p, [
        OP("misquote", "propose_claim", adm.claim("a", subject="a"), evidence=[altered]),
        OP("ghost", "propose_claim", adm.claim("b", subject="b"), evidence=[osc.missing_event_link()]),
        OP("dependent", "propose_claim", adm.claim("c", subject="c"), depends_on=["ghost"], evidence=[adm.link(fail)]),
        OP("good", "propose_claim", adm.claim("`pytest -q test_mid.py` exited with code 1.", basis="observed", subject="d"), evidence=[adm.link(fail, mapping="tool.exit_code")]),
    ])
    assert decisions(result) == [("reject", "quote_mismatch"), ("reject", "evidence_missing"), ("reject", "group_rejected"), ("apply", "observed_mapping")]


# ---------------------------------------------------------------------------
# Declarations and nondeclaration regions (A60; SYSTEM_SPEC §7.1.2)

MIXED = (
    "Use uv for installs, not pip.\n\n"
    "Here is what was sent to me:\n"
    "> I want us to switch to poetry.\n\n"
    "```\n# I prefer tabs everywhere\n```\n\n"
    "diff --git a/setup.cfg b/setup.cfg\n@@ -1,2 +1,2 @@\n-tool = pip\n+tool = poetry\n\n"
    "From: Dana\nTo: team\nSubject: deploys\nI decided we deploy on Fridays."
)


def test_fenced_quoted_pasted_and_email_text_is_never_a_declaration(p):
    said = adm.prompt(p, MIXED, at_=adm.at(1))
    text = said["payload"]["text"]
    assert text == MIXED

    def declare(local_ref, quote=None, kind="preference", **kw):
        link = adm.link(said, field="text", quote=quote) if quote else adm.link(said)
        return OP(local_ref, "propose_claim", adm.claim(f"declared {local_ref}", kind=kind, basis="user_declared", subject=local_ref), evidence=[link])

    result = adm.extract(p, [
        declare("own", "Use uv for installs, not pip."),  # terse, not first person: no verb heuristic either way
        declare("blockquote", "I want us to switch to poetry."),
        declare("fenced", "I prefer tabs everywhere"),
        declare("diff", "+tool = poetry"),
        declare("email", "I decided we deploy on Fridays."),
        declare("whole"),  # no locator: the whole message, which contains quoted regions
        declare("straddle", "pip.\n\nHere is what was sent to me:\n> I want"),
    ])
    assert decisions(result) == [("candidate_only", "candidate_pending_review")] + [("reject", "declaration_in_nondeclaration_region")] * 6
    # The quoted preference may still be proposed as inferred, attributed content (never a user decision).
    inferred = adm.extract(p, [OP("attributed", "propose_claim", adm.claim("A colleague proposed switching to poetry.", subject="poetry"), evidence=[adm.link(said, field="text", quote="I want us to switch to poetry.")])])
    assert decisions(inferred) == [("candidate_only", "candidate_pending_review")]
    # Review priority is code-assigned: the user's own preference is a declaration candidate; the attributed text is not.
    (own_job,) = adm.review_jobs(p, adm.created_claim(result))
    (attributed_job,) = adm.review_jobs(p, adm.created_claim(inferred))
    assert own_job.review_priority == "correction_or_declaration" and attributed_job.review_priority == "ordinary"


@pytest.mark.parametrize(
    "message, quoted, own",
    [
        ("Traceback (most recent call last):\n  File \"app.py\", line 3, in <module>\nValueError: I want retries disabled\nPlease add retries to the client.", "I want retries disabled", "Please add retries to the client."),
        ("$ make deploy\nI decided to skip the tests\n\nKeep running the tests before deploys.", "I decided to skip the tests", "Keep running the tests before deploys."),
        ("2026-10-01 12:00:01 INFO I want verbose logs\n2026-10-01 12:00:02 WARN rotated\n\nKeep the logs quiet.", "I want verbose logs", "Keep the logs quiet."),
        ("Settings:\n\n    I prefer two-space indents\n\nUse four spaces.", "I prefer two-space indents", "Use four spaces."),
        ("<document name=\"notes\">\nWe always squash merges.\n</document>\nUse merge commits.", "We always squash merges.", "Use merge commits."),
        ("Use uv.\r\n> I want poetry instead.\r\nKeep the lockfile.", "I want poetry instead.", "Use uv."),
    ],
    ids=["traceback", "terminal", "log", "indented", "attachment", "crlf"],
)
def test_uncertain_authorship_regions(p, message, quoted, own):
    said = adm.prompt(p, message, at_=adm.at(1))
    assert said["payload"]["text"] == message  # stored exactly, whatever the line ends
    result = adm.extract(p, [
        OP("quoted", "propose_claim", adm.claim("quoted", kind="preference", basis="user_declared", subject="q"), evidence=[adm.link(said, field="text", quote=quoted)]),
        OP("own", "propose_claim", adm.claim("own", kind="preference", basis="user_declared", subject="o"), evidence=[adm.link(said, field="text", quote=own)]),
    ])
    assert decisions(result) == [("reject", "declaration_in_nondeclaration_region"), ("candidate_only", "candidate_pending_review")]


def test_non_user_and_incomplete_text_is_never_a_declaration(tmp_path):
    p = wks.Project(tmp_path, "sources")
    p.scenario("lifecycle")
    p.scenario("subagent")
    p.drain()
    notification = next(e for e in p.events("generic_observation") if e["payload"].get("host_origin") == "task_notification")  # host-generated
    tool = p.event("tool_finished", call="toolu_probe_0001")
    long_text = "Use uv for every install. " + "Context line that the user pasted. " * 2200  # over the 64 KiB event cap
    big = adm.prompt(p, long_text, at_=adm.at(1))
    assert big["payload"].get("text_part", {}).get("count", 1) > 1  # the real normalizer partitioned it
    result = adm.extract(p, [
        OP("host", "propose_claim", adm.claim("host", kind="preference", basis="user_declared", subject="h"), evidence=[adm.link(notification, field="text", start=0, end=20)]),
        OP("tool", "propose_claim", adm.claim("tool", kind="preference", basis="user_declared", subject="t"), evidence=[adm.link(tool, field="result_text")]),
        OP("part", "propose_claim", adm.claim("part", kind="preference", basis="user_declared", subject="p"), evidence=[adm.link(big, field="text", quote="Use uv for every install.")]),
    ])
    assert decisions(result) == [("reject", "declaration_requires_user_evidence"), ("reject", "declaration_requires_user_evidence"), ("reject", "declaration_coverage_incomplete")]


def test_unextracted_statement_is_not_a_ready_declaration(p):
    """A50: a natural-language declaration nobody extracted creates no candidate and no review."""
    before = len(adm.review_jobs(p))
    adm.prompt(p, "Always run the linters before committing.", at_=adm.at(1))
    assert len(adm.review_jobs(p)) == before and p.count("SELECT COUNT(*) FROM claim_heads") == 0


def test_declarations_alone_never_exceed_supported(p):
    a = adm.prompt(p, "Prefer uv over pip for installs.", at_=adm.at(1))
    b = adm.prompt(p, "Again: uv, not pip, for installs.", at_=adm.at(2))
    decl = adm.claim("Use uv for installs.", kind="preference", basis="user_declared", subject="installer")
    result = adm.extract(p, [OP("d", "propose_claim", decl, evidence=[adm.link(a, field="text", quote="Prefer uv over pip for installs."), adm.link(b, field="text", quote="Again: uv, not pip, for installs.")])])
    claim_id = adm.created_claim(result)
    adm.admit(p, claim_id)
    head = adm.head(p, claim_id)
    assert (head["status"], head["strength"]) == ("active", "supported")  # one user's statements are one authority class
    with p.view() as v:
        assert len(admission.lineage.resolve(v, [EvidenceLink.model_validate(x) for x in head["supports"]], proposition_key=head["proposition_key"]).support_classes) == 1


def test_contradiction_blocks_corroboration(p):
    fail = fail_mid(p)
    other = adm.call(p, "toolu_probe_0003", "x", command="pytest -q -x test_mid.py", at_=adm.at(1))
    result = adm.extract(p, [OP("c", "propose_claim", adm.claim("test_mid fails its assertion.", subject="test_mid"), evidence=[adm.link(fail, field="result_text", quote="FAILED test_mid.py::test_mid"), adm.link(other, field="result_text", quote="FAILED test_mid.py::test_mid")])])
    claim_id = adm.created_claim(result)
    adm.admit(p, claim_id)
    assert adm.head(p, claim_id)["strength"] == "corroborated"
    green = adm.call(p, "toolu_probe_0003", "green", outcome_of="toolu_probe_0004", at_=adm.at(2))
    ref = osc.head_ref(p.root, "claim", claim_id)
    adm.extract(p, [OP("k", "attach_evidence", {"claim_ref": ref.model_dump(mode="json"), "relation": "contradicts"}, evidence=[adm.link(green, relation="contradicts")])])
    assert adm.head(p, claim_id)["strength"] == "supported"


# ---------------------------------------------------------------------------
# Failure lessons, scope and extraction


def test_failure_lesson_fields_are_code_derived(p):
    fail = fail_mid(p)
    success = p.event("tool_finished", call="toolu_probe_0004")
    from recalith.capture.normalize import action_family_digest

    family = action_family_digest(p.ctx.workspace_id, fail["payload"]["action"])
    earlier = p.event("tool_finished", call="toolu_probe_0002")  # test_long failed first
    good = adm.extract(p, [OP("l", "propose_claim", adm.lesson("test_mid needs its fixture before it can pass."), evidence=[adm.link(earlier), adm.link(fail)])])
    body = adm.head(p, adm.created_claim(good))  # the latest cited failure by commit order, whatever the link order
    assert body["failure"]["last_supporting_failure_event_id"] == fail["id"] and body["failure"]["action_family_digest"] == family
    with p.view() as v:
        assert v.execute("SELECT action_family_digest FROM claim_heads WHERE claim_id = ?", (body["claim_id"],)).fetchone()[0] == family
    bad = adm.extract(p, [
        OP("wrong", "propose_claim", adm.lesson("x", action_family_digest="0" * 64), evidence=[adm.link(fail)]),
        OP("success_only", "propose_claim", adm.lesson("y"), evidence=[adm.link(success)]),
    ])
    assert decisions(bad) == [("reject", "failure_body_mismatch"), ("reject", "failure_lesson_requires_failure")]


def test_scope_never_names_a_workspace_the_evidence_is_not_from(p):
    """Narrowest justified scope (synthetic: a second registered workspace row; attachment itself is full-release work)."""
    other = new_id("ws")
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        txn.execute("INSERT INTO workspaces (workspace_id, canonical_root, root_identity, attachment_state, registered_at) VALUES (?, ?, ?, 'attached', ?)", (other, "/elsewhere", "id", utc_now()))
    fail = fail_mid(p)
    result = adm.extract(p, [
        OP("wide", "propose_claim", adm.claim("x", subject="a", scope={"workspace_ids": [p.ctx.workspace_id, other]}), evidence=[adm.link(fail)]),
        OP("narrow", "propose_claim", adm.claim("y", subject="b", scope={"workspace_ids": [p.ctx.workspace_id]}), evidence=[adm.link(fail)]),
    ])
    assert decisions(result) == [("reject", "scope_broader_than_evidence"), ("candidate_only", "candidate_pending_review")]


def test_settled_episode_schedules_bounded_extraction(tmp_path):
    """Each settled episode with steps gets one extraction after the quiet window; selection is bounded and rationale-free."""
    p = wks.Project(tmp_path, "settled")
    p.scenario("subagent")  # real: its range settles at session end (the lifecycle range keeps an unresolved failure open)
    p.drain()
    with p.view() as v:
        rows = v.execute("SELECT body FROM jobs WHERE kind = 'extract_claims'").fetchall()
    extraction = [json.loads(r[0]) for r in rows]
    episodes = [e for e in p.episodes() if e["head_state"] == "settled" and e["steps"]]
    assert episodes and {j["input_refs"][0]["id"] for j in extraction if j["trigger_ref"] is None} == {e["episode_id"] for e in episodes}
    job = jobs.Job.model_validate(next(j for j in extraction if j["trigger_ref"] is None))
    request = requests.prepare_model_request(p.ctx, job, now=utc_now())
    assert request.purpose == "extract_claims" and request.prompt_version == prompts.CURRENT["extract_claims"]
    assert len(request.claims) <= extract.MAX_CLAIMS and len(canonical_json(request.model_dump(mode="json"))) <= MODEL_INPUT_CAP
    assert all(c.review_assessment is None and c.model_provenance is None for c in request.claims)


def test_low_information_extraction_is_cancelled_without_a_call(p):
    read = p.event("tool_finished", call="toolu_probe_0007")
    write = p.event("tool_finished", call="toolu_probe_0009")
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        job_id, _ = jobs.enqueue(txn, kind="extract_claims", input_refs=[RecordRef(kind="event", id=read["id"], revision=1), RecordRef(kind="event", id=write["id"], revision=1)], now=utc_now(), prompt_version=prompts.CURRENT["extract_claims"], due_at=osc.EARLIEST)
    with p.view() as v:
        task_id = wks.bindings.binding_head(v, read["id"])["task_id"]
    with db.open_store(p.ctx) as store, store.transaction() as txn:  # no pending boundary may make it worth a call
        txn.execute("UPDATE task_boundaries SET state = 'rejected' WHERE source_task_id = ?", (task_id,))
    backend = ws.FakeBackend()
    w = worker.Worker(p.ctx, clock=ws.FakeClock(utc_now()), model=ws.runtime(backend, requests.runtime_preparer(p.ctx)))
    try:
        while w.lane.step():
            pass
    finally:
        w.close()
    assert ("extract_claims", job_id) not in backend.calls
    with p.view() as v:
        job = jobs.get_job(v, job_id)
        assert (job.state, job.last_error_code) == ("cancelled", "nothing_to_extract")
        assert v.execute("SELECT COUNT(*) FROM provider_usage WHERE job_id = ?", (job_id,)).fetchone()[0] == 0


def test_extraction_folds_pending_boundary_candidates(tmp_path):
    """Pending boundary candidates ride on extraction: presented with binding revisions, decided or left pending (decision 0008)."""
    p = wks.Project(tmp_path, "fold")
    lifecycle = wks.cf.records("lifecycle")
    stop = next(i for i, r in enumerate(lifecycle) if r["event"] == "Stop")
    p.send_all(lifecycle[:stop])
    p.send(wks.variant(wks.record("lifecycle", "UserPromptSubmit"), prompt="new task: tidy the fixture notes"))
    p.send(wks.variant(wks.record("lifecycle", "PreToolUse", "toolu_probe_0003"), tool_suffix="p"))
    p.send(wks.variant(wks.record("lifecycle", "PostToolUseFailure", "toolu_probe_0003"), tool_suffix="p"))
    p.drain()
    (pivot,) = p.boundaries("pivot_prefix")
    failure = p.event("tool_finished", call="toolu_probe_0003_p")
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        job_id, _ = jobs.enqueue(txn, kind="extract_claims", input_refs=[RecordRef(kind="event", id=failure["id"], revision=1)], now=utc_now(), prompt_version=prompts.CURRENT["extract_claims"], due_at=adm.at(10_000))
    with p.view() as v:
        job = jobs.get_job(v, job_id)
    request = requests.prepare_model_request(p.ctx, job, now=utc_now())
    (shown,) = [b for b in request.boundaries if b.candidate.boundary_id == pivot["boundary_id"]]
    assert shown.binding_revisions == p.expected(pivot["proposed_event_ids"])
    # Left pending by a no-op extraction, then decided by a later extraction's binding resolution.
    adm.extract(p, [], response=osc.response([], purpose="extract_claims", no_op_reason="nothing durable"))
    assert p.boundaries("pivot_prefix")[0]["state"] == "pending"
    with p.view() as v:
        from recalith.working import tasks as wt

        source = wt.resolve_task(v, pivot["source_task_id"])
        order = [e for e, _s in wks.bindings.task_session_events(v, source, pivot["session_id"])]
    event_ids = order[order.index(pivot["proposed_event_ids"][0]):]
    split = p.binding_op("split", "confirm_split", pivot["boundary_id"], event_ids)
    result = adm.extract(p, [split])
    assert decisions(result) == [("apply", "admitted")]
    assert p.boundaries("pivot_prefix")[0]["state"] == "confirmed"


def test_active_reviewed_claims_stay_valid_in_later_requests(p):
    """Regression: a request consulting active reviewed guidance keeps its supported verdict (objection text withheld)."""
    fail = fail_mid(p)
    claim_id = adm.created_claim(adm.extract(p, [OP("c", "propose_claim", adm.claim("test_mid fails its assertion."), evidence=[adm.link(fail)])]))
    adm.admit(p, claim_id)
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        job_id, _ = jobs.enqueue(txn, kind="extract_claims", input_refs=[RecordRef(kind="event", id=fail["id"], revision=1)], now=utc_now(), prompt_version=prompts.CURRENT["extract_claims"], due_at=adm.at(10_000))
    with p.view() as v:
        job = jobs.get_job(v, job_id)
    request = requests.prepare_model_request(p.ctx, job, now=utc_now())
    (shown,) = [c for c in request.claims if c.claim_id == claim_id]
    assert shown.status == "active" and shown.review_assessment is not None and shown.review_assessment.verdict == "supported" and shown.review_assessment.objections == []


def test_active_guidance_is_superseded_only_by_reviewed_guidance(p):
    """SYSTEM_SPEC §7.2: an extraction cannot retire active guidance with an unreviewed replacement.

    Since Task 10 (decision 0012) the supersession is held until the replacement's own review activates it
    (``test_consolidation.py::test_explicit_replacement_is_atomic``); until then the old guidance stays active.
    """
    fail = fail_mid(p)
    old = adm.created_claim(adm.extract(p, [OP("o", "propose_claim", adm.claim("The old reading.", subject="old"), evidence=[adm.link(fail)])]))
    adm.admit(p, old)
    ref = osc.head_ref(p.root, "claim", old)
    retire = OP("retire", "change_claim_status", {"claim_ref": ref.model_dump(mode="json"), "status": "superseded", "replacement_local_ref": "new"}, depends_on=["new"], target=ref.model_dump(mode="json"), evidence=[adm.link(fail)])
    held = adm.extract(p, [OP("new", "propose_claim", adm.claim("The new reading.", subject="new"), evidence=[adm.link(fail)]), retire])
    assert decisions(held) == [("candidate_only", "candidate_pending_review"), ("review_required", "replacement_pending_review")]
    assert adm.head(p, old)["status"] == "active"
    observed = OP("new", "propose_claim", adm.claim("`pytest -q test_mid.py` exited with code 1.", basis="observed", subject="new"), evidence=[adm.link(fail, mapping="tool.exit_code")])
    allowed = adm.extract(p, [observed, retire])
    assert decisions(allowed) == [("apply", "observed_mapping"), ("apply", "admitted")]
    assert adm.head(p, old)["status"] == "superseded"


def test_a_superseding_replacement_is_reviewed_at_its_latest_revision(p):
    """Regression: the replacement's supersession revision (same application) is the one scheduled for review."""
    fail = fail_mid(p)
    old = adm.created_claim(adm.extract(p, [OP("o", "propose_claim", adm.claim("The old reading.", subject="old"), evidence=[adm.link(fail)])]))
    ref = osc.head_ref(p.root, "claim", old)
    result = adm.extract(p, [
        OP("new", "propose_claim", adm.claim("The new reading.", subject="new"), evidence=[adm.link(fail)]),
        OP("retire", "change_claim_status", {"claim_ref": ref.model_dump(mode="json"), "status": "superseded", "replacement_local_ref": "new"}, depends_on=["new"], target=ref.model_dump(mode="json"), evidence=[adm.link(fail)]),
    ])
    new = next(r.id for r in result.changed_refs if r.kind == "claim" and r.id != old)
    head = adm.head(p, new)
    assert head["revision"] == 2 and head["status"] == "candidate"
    (job,) = adm.review_jobs(p, new)
    assert job.input_refs == [RecordRef(kind="claim", id=new, revision=2)]


# ---------------------------------------------------------------------------
# Review batches (A50, A60)


def test_review_partitions_by_count_output_and_input(p):
    fail = fail_mid(p)
    ops = [OP(f"c{i}", "propose_claim", adm.claim(f"Candidate {i} about test_mid.", subject=f"s{i}"), evidence=[adm.link(fail)]) for i in range(20)]
    result = adm.extract(p, ops)
    ids = [r.id for r in result.changed_refs if r.kind == "claim"]
    batches = [j for j in adm.review_jobs(p) if any(r.id in ids for r in j.input_refs)]
    assert [len(j.input_refs) for j in batches] == [8, 8, 4]  # stable proposal order, at most eight
    assert [r.id for j in batches for r in j.input_refs] == ids
    assert review.output_capacity() == 8 and review.output_capacity(9000) == 8 and review.output_capacity(5000) == 3
    with p.view() as v:
        claims = [records.load(v, "claim", i, 1) for i in ids[:7]]
        out_split, deferred = review.partition(v, p.ctx, claims, per_batch=review.output_capacity(5000))  # a smaller body splits by output
    assert [len(b) for b in out_split] == [3, 3, 1] and deferred == []
    # Input split: each candidate cites one bulky (~33 KB) real result; a batch never exceeds 96 KiB.
    bulky = adm.evidence_events(p, 6)
    result = adm.extract(p, [OP(f"b{i}", "propose_claim", adm.claim(f"seq run {i} printed numbers.", subject=f"seq{i}"), evidence=[adm.link(ev)]) for i, ev in enumerate(bulky[:4])])
    big_ids = [r.id for r in result.changed_refs if r.kind == "claim"]
    big_batches = [j for j in adm.review_jobs(p) if any(r.id in big_ids for r in j.input_refs)]
    assert 1 < len(big_batches) < 4 and [r.id for j in big_batches for r in j.input_refs] == big_ids
    with p.view() as v:
        for j in big_batches:
            claims = [records.load(v, "claim", r.id, r.revision) for r in j.input_refs]
            assert review._request_bytes(v, p.ctx, claims) <= MODEL_INPUT_CAP
        for a, b in zip(big_batches, big_batches[1:], strict=False):
            joined = [records.load(v, "claim", r.id, r.revision) for r in [*a.input_refs, b.input_refs[0]]]
            assert review._request_bytes(v, p.ctx, joined) > MODEL_INPUT_CAP  # split only because input could not hold more
    # A candidate too large to review on its own is deferred, never truncated.
    huge = adm.extract(p, [OP("huge", "propose_claim", adm.claim("All seq runs printed numbers.", subject="seq-all"), evidence=[adm.link(ev) for ev in bulky])])
    huge_id = adm.created_claim(huge)
    assert adm.review_jobs(p, huge_id) == [] and adm.outcomes(p, huge_id) == [("deferred", "review_input_oversized")]
    assert adm.head(p, huge_id)["status"] == "candidate"
    # The persisted batch carries exact evidence; preparation fails rather than drop any (and never truncates).
    job = big_batches[0]
    request = requests.prepare_model_request(p.ctx, adm.lease(p, job.job_id), now=utc_now())
    shown = {e.event_id: e.payload for e in request.events}
    stored = {e["id"]: e["payload"] for e in p.events("tool_finished")}
    for r in job.input_refs:
        for item in adm.head(p, r.id)["supports"]:
            assert shown[item["ref"]["id"]] == stored[item["ref"]["id"]]  # exact, untrimmed evidence


def test_five_candidates_one_fitting_batch_and_exact_verdict_rules(p):
    """Five candidates: one batch; missing, duplicate, foreign and stale verdicts never activate; valid ones proceed."""
    fail = fail_mid(p)
    ops = [OP(f"c{i}", "propose_claim", adm.claim(f"test_mid observation {i}.", subject=f"o{i}"), evidence=[adm.link(fail, field="result_text", quote="FAILED test_mid.py::test_mid")], reason=f"SELF-CONFIDENCE 0.9{i}") for i in range(5)]
    result = adm.extract(p, ops)
    ids = [r.id for r in result.changed_refs if r.kind == "claim"]
    (job,) = [j for j in adm.review_jobs(p) if any(r.id in ids for r in j.input_refs)]
    assert [r.id for r in job.input_refs] == ids
    other = adm.extract(p, [OP("x", "propose_claim", adm.claim("A different candidate.", subject="other"), evidence=[adm.link(fail)])])
    (other_job,) = adm.review_jobs(p, adm.created_claim(other))

    def decide(request):
        batch = request.review_batch
        refs = batch.candidate_refs
        bodies = {c.claim_id: c.model_dump(mode="json") for c in request.claims}
        # A concurrent writer changes candidate 3 after the snapshot: its verdict is stale.
        stale = refs[3]
        adm.extract(p, [OP("more", "attach_evidence", {"claim_ref": stale.model_dump(mode="json"), "relation": "supports"}, evidence=[adm.link(p.event("tool_finished", call="toolu_probe_0002"))])])
        return [
            adm.assess(batch, refs[0], "supported", local_ref="v0", evidence_ids=adm.support_ids(batch, bodies[refs[0].id])[:1]),
            adm.assess(batch, refs[1], "supported", local_ref="v1", evidence_ids=adm.support_ids(batch, bodies[refs[1].id])[:1]),
            adm.assess(batch, refs[1], "reject", local_ref="v1b", objections=["second verdict"]),
            # refs[2]: no verdict at all
            adm.assess(batch, refs[3], "supported", local_ref="v3", evidence_ids=adm.support_ids(batch, bodies[refs[3].id])[:1]),
            adm.assess(batch, refs[4], "supported", local_ref="v4", evidence_ids=adm.support_ids(batch, bodies[refs[4].id])[:1], batch_id=new_id("batch")),
            adm.assess(batch, osc.head_ref(p.root, "claim", adm.created_claim(other)), "supported", local_ref="v5", evidence_ids=adm.support_ids(batch, bodies[refs[0].id])[:1]),
        ]

    request, applied = adm.run_review(p, job.job_id, decide)
    assert len(request.review_batch.candidate_refs) == 5  # one fitting batch
    assert decisions(applied) == [
        ("apply", "review_supported"), ("reject", "assessment_duplicate"), ("reject", "assessment_duplicate"),
        ("reject", "candidate_stale"), ("reject", "assessment_foreign"), ("reject", "assessment_foreign"),
    ]
    states = [adm.head(p, i)["status"] for i in ids]
    assert states == ["active", "candidate", "candidate", "candidate", "candidate"]
    assert adm.head(p, adm.created_claim(other))["status"] == "candidate" and adm.review_jobs(p, adm.created_claim(other))[0].state == "pending"
    assert adm.outcomes(p, ids[0]) == [("admitted", "review_supported")]
    assert sorted(adm.outcomes(p, ids[1])) == [("duplicate", "assessment_duplicate"), ("duplicate", "assessment_duplicate")]
    assert adm.outcomes(p, ids[2]) == [("missing", "verdict_missing")]
    assert ("stale", "candidate_stale") in adm.outcomes(p, ids[3])
    assert adm.outcomes(p, ids[4]) == [("foreign", "assessment_foreign")]  # named only by another batch's verdict
    # The changed candidate's new revision got its own review job (from the writer's application).
    assert any(j.state == "pending" and j.input_refs[0].revision == 2 for j in adm.review_jobs(p, ids[3]))
    # The reviewer saw no proposal reason or self-confidence, and the exact evidence text.
    serialized = canonical_json(request.model_dump(mode="json")).decode()
    assert "SELF-CONFIDENCE" not in serialized and '"reason"' not in json.dumps([c.model_dump(mode="json") for c in request.claims])
    assert any(e.event_id == fail["id"] and e.payload["result_text"] == fail["payload"]["result_text"] for e in request.events)
    assert request.read_set.entity_revisions == []  # one changed candidate cannot requeue the others
    assert request.review_batch.prompt_digest == prompts.prompt_digest(prompts.CURRENT["review_claims"])


def test_revise_returns_objections_only(p):
    fail = fail_mid(p)
    claim_id = adm.created_claim(adm.extract(p, [OP("c", "propose_claim", adm.claim("test_mid fails on every platform."), evidence=[adm.link(fail)])]))
    (job,) = adm.review_jobs(p, claim_id)

    def decide(request):
        batch, ref = request.review_batch, request.review_batch.candidate_refs[0]
        return [
            adm.assess(batch, ref, "revise", local_ref="rewrite", objections=["Only Linux was observed."], extra={"proposition": "test_mid fails on Linux."}),
            adm.assess(batch, ref, "revise", local_ref="empty"),
        ]

    _request, result = adm.run_review(p, job.job_id, decide)
    # A rewritten proposition is not even a valid assessment (strict payload); malformed entries are listed last
    # and, with no attributable payload, never count toward a candidate's verdicts.
    assert decisions(result) == [("reject", "revise_requires_objection"), ("reject", "malformed_operation")]
    assert adm.head(p, claim_id)["proposition"] == "test_mid fails on every platform."
    # A fresh review (another job over the same revision, recorded) with a lone objection-free revise is refused.
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        again, _ = jobs.enqueue(txn, kind="review_claims", input_refs=[osc.head_ref(p.root, "claim", claim_id)], now=utc_now(), prompt_version=prompts.CURRENT["review_claims"], review_candidates=[jobs.ReviewCandidate(claim_id, "extracted", "fact")], idempotency=digest_of(new_id("job")))
    _r, refused = adm.run_review(p, again, lambda r: [adm.assess(r.review_batch, r.review_batch.candidate_refs[0], "revise", local_ref="bare")])
    assert decisions(refused) == [("reject", "revise_requires_objection")]
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        third, _ = jobs.enqueue(txn, kind="review_claims", input_refs=[osc.head_ref(p.root, "claim", claim_id)], now=utc_now(), prompt_version=prompts.CURRENT["review_claims"], review_candidates=[jobs.ReviewCandidate(claim_id, "extracted", "fact")], idempotency=digest_of(new_id("job")))
    _r, revised = adm.run_review(p, third, lambda r: [adm.assess(r.review_batch, r.review_batch.candidate_refs[0], "revise", local_ref="ok", objections=["Only Linux was observed."])])
    assert decisions(revised) == [("apply", "review_revise")]
    head = adm.head(p, claim_id)
    assert (head["status"], head["proposition"], head["review_assessment"]["objections"]) == ("candidate", "test_mid fails on every platform.", ["Only Linux was observed."])


def test_review_capacity_is_not_a_refutation_and_cannot_loop(p):
    fail = fail_mid(p)
    result = adm.extract(p, [
        OP("cap", "propose_claim", adm.claim("Capacity-limited candidate."), evidence=[adm.link(fail)]),
        OP("rej", "propose_claim", adm.claim("Rejected candidate.", subject="r"), evidence=[adm.link(fail)]),
        OP("mix", "propose_claim", adm.claim("Mixed capacity code.", subject="m"), evidence=[adm.link(fail)]),
    ])
    cap, rej, mix = [r.id for r in result.changed_refs if r.kind == "claim"]
    (job,) = [j for j in adm.review_jobs(p) if any(r.id == cap for r in j.input_refs)]

    def decide(request):
        batch = request.review_batch
        by_id = {r.id: r for r in batch.candidate_refs}
        return [
            adm.assess(batch, by_id[cap], "reject", local_ref="a", objections=[review.CAPACITY]),
            adm.assess(batch, by_id[rej], "reject", local_ref="b", objections=["The quote does not mention any platform."]),
            adm.assess(batch, by_id[mix], "revise", local_ref="c", objections=[review.CAPACITY]),
        ]

    _request, applied = adm.run_review(p, job.job_id, decide)
    assert decisions(applied) == [("apply", review.CAPACITY), ("apply", "review_rejected"), ("reject", "capacity_requires_sole_reject")]
    capped = adm.head(p, cap)
    assert (capped["status"], capped["strength"], capped["review_assessment"]["verdict"], capped["review_assessment"]["objections"]) == ("candidate", "weak", "reject", [review.CAPACITY])
    assert adm.outcomes(p, cap) == [("capacity", review.CAPACITY)]
    assert adm.head(p, rej)["status"] == "archived"  # not admitted; asserts no falsity
    assert adm.head(p, mix)["status"] == "candidate" and adm.outcomes(p, mix) == [("refused", "capacity_requires_sole_reject")]
    # No loop: recording the capacity failure scheduled no further review.
    assert [j.job_id for j in adm.review_jobs(p, cap)] == [job.job_id]
    # A later (explicit) re-review sees the candidate without its earlier assessment or objections.
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        again, _ = jobs.enqueue(txn, kind="review_claims", input_refs=[osc.head_ref(p.root, "claim", cap)], now=utc_now(), prompt_version=prompts.CURRENT["review_claims"], review_candidates=[jobs.ReviewCandidate(cap, "extracted", "fact")], idempotency=digest_of(new_id("job")))
    request, _result = adm.run_review(p, again, lambda r: [], no_op_reason="no verdict")
    assert [c.review_assessment for c in request.claims if c.claim_id == cap] == [None]
    assert review.CAPACITY not in json.dumps([c.model_dump(mode="json") for c in request.claims])


def test_assessment_is_bound_to_the_snapshot_digest(p):
    """A verdict counts only for the exact content its batch snapshot recorded, even at the same revision."""
    fail = fail_mid(p)
    claim_id = adm.created_claim(adm.extract(p, [OP("c", "propose_claim", adm.claim("test_mid fails its assertion."), evidence=[adm.link(fail)])]))
    (job,) = adm.review_jobs(p, claim_id)
    leased = adm.lease(p, job.job_id)
    request = requests.prepare_model_request(p.ctx, leased, now=utc_now())
    batch = request.review_batch
    ref = batch.candidate_refs[0]
    op = adm.assess(batch, ref, "supported", local_ref="a", evidence_ids=adm.support_ids(batch, adm.head(p, claim_id))[:1])
    from recalith.contracts.operations import ProposedOperation

    proposed = ProposedOperation.model_validate(op)
    with p.view() as v:
        good = review.check_assessment(v, p.ctx, proposed, proposed.typed_payload(), review.ReviewScope(job=leased, batch=batch, counts={claim_id: 1}))
        tampered = batch.model_copy(update={"candidate_digests": {claim_id: digest_of("other content")}})
        bad = review.check_assessment(v, p.ctx, proposed, proposed.typed_payload(), review.ReviewScope(job=leased, batch=tampered, counts={claim_id: 1}))
    assert (good.outcome, good.reason) == ("apply", "review_supported") and (bad.outcome, bad.reason) == ("reject", "candidate_stale")


def test_supported_verdict_needs_valid_primary_support(p):
    fail = fail_mid(p)
    echo = p.event("tool_finished", call="toolu_probe_0001")  # echo restates its arguments: not an observation
    green = adm.call(p, "toolu_probe_0003", "green", outcome_of="toolu_probe_0004", at_=adm.at(1))
    result = adm.extract(p, [
        OP("e", "propose_claim", adm.claim("hello-fixture is printed.", subject="echo"), evidence=[adm.link(echo)]),
        OP("k", "propose_claim", adm.claim("test_mid is flaky.", subject="k"), evidence=[adm.link(fail), adm.link(green, relation="contradicts")]),
    ])
    echo_id, k_id = [r.id for r in result.changed_refs if r.kind == "claim"]
    (job,) = [j for j in adm.review_jobs(p) if any(r.id == echo_id for r in j.input_refs)]

    def decide(request):
        batch = request.review_batch
        bodies = {c.claim_id: c.model_dump(mode="json") for c in request.claims}
        by_id = {r.id: r for r in batch.candidate_refs}
        return [
            adm.assess(batch, by_id[echo_id], "supported", local_ref="a", evidence_ids=adm.support_ids(batch, bodies[echo_id])),
            adm.assess(batch, by_id[k_id], "supported", local_ref="b", evidence_ids=adm.support_ids(batch, bodies[k_id], "contradicts")),
        ]

    _r, applied = adm.run_review(p, job.job_id, decide)
    assert decisions(applied) == [("reject", "no_primary_support"), ("reject", "supported_requires_support_evidence")]
    assert adm.head(p, echo_id)["status"] == "candidate" and adm.outcomes(p, echo_id) == [("refused", "no_primary_support")]


def test_candidate_only_degradation_without_review(p):
    """No certified route: review jobs wait visibly, candidates stay weak, and review_candidates refuses without side effects."""
    fail = fail_mid(p)
    claim_id = adm.created_claim(adm.extract(p, [OP("c", "propose_claim", adm.claim("test_mid fails its assertion."), evidence=[adm.link(fail)])]))
    w = worker.Worker(p.ctx, clock=ws.FakeClock(utc_now()))  # production preview: no backend (B1)
    try:
        w.poll_once()
    finally:
        w.close()
    (job,) = adm.review_jobs(p, claim_id)
    assert (job.state, job.last_error_code) == ("pending", "provider_unavailable")
    leased = adm.lease(p, job.job_id)
    with pytest.raises(RecalithError, match="provider_not_configured"):
        review.review_candidates(p.ctx, [claim_id], job=leased)
    with pytest.raises(RecalithError, match="claim_ids must be"):
        review.review_candidates(p.ctx, ["claim_" + "0" * 64], job=leased, launch=lambda r: None)
    head = adm.head(p, claim_id)
    assert (head["status"], head["strength"], head["review_assessment"]) == ("candidate", "weak", None)


def test_prompt_digests_are_pinned_separately():
    """The extraction and review prompts are versioned package data, digested separately (decisions 0011, 0031)."""
    assert prompts.CURRENT["extract_claims"] == "extract_claims@2" and prompts.CURRENT["review_claims"] == "review_claims@1"
    extract_digest, review_digest = prompts.prompt_digest("extract_claims@2"), prompts.prompt_digest("review_claims@1")
    assert extract_digest != review_digest
    # Golden digests: editing a shipped prompt text requires a new version string.
    assert prompts.prompt_digest("extract_claims@1") == "72cbd9c3996f467d2aff4aafec9e6b3cf092ca15374dbb523723acabf8e19f21"  # still served to jobs that pinned it
    assert extract_digest == "a6c44082b67f92e487c5140ecead0bcdc552aee8f757a085d2d6c416ed95b285"
    assert review_digest == "7bafbabe9897d1d173f43f3d43aa60d990e56e59411423faf4c7e39aecf5fbb2"
    assert "review_capacity" in prompts.INSTRUCTIONS["review_claims@1"] and "exited with code" in prompts.INSTRUCTIONS["extract_claims@2"]
    v2 = prompts.INSTRUCTIONS["extract_claims@2"]
    assert '{"kind": "file", "key": "<path>", "fingerprint": null, "record": null}' in v2 and "payload.action.paths" in v2  # decision 0031
    assert "dependencies" not in prompts.INSTRUCTIONS["extract_claims@1"]


# ---------------------------------------------------------------------------
# Failure triggers (A66)


def trigger_project(tmp_path, name="triggers") -> wks.Project:
    """A fresh session: start and prompt at controlled times (synthetic times; real payloads)."""
    p = wks.Project(tmp_path, name)
    p.send(wks.record("lifecycle", "SessionStart"), at=adm.at(0))
    p.send(wks.variant(wks.record("lifecycle", "UserPromptSubmit"), prompt="Make test_mid pass."), at=adm.at(0, 1))
    p.drain()
    return p


def trigger_rows(p):
    with p.view() as v:
        return triggers.triggers(v)


def noise(p, n: int, *, start: float, prefix: str = "n") -> None:
    """``n`` relevant task events: grep results (real payload, new IDs) one second apart."""
    for i in range(n):
        adm.send_call(p, "toolu_probe_0006", f"{prefix}{i}", at_=adm.at(start, i))


def test_success_before_six_events_resolves_the_trigger(tmp_path):
    p = trigger_project(tmp_path)
    adm.send_call(p, "toolu_probe_0003", "f1", at_=adm.at(1))
    # Not relevant: tool starts (each noise call has one), a start alone, and lifecycle events.
    p.send(wks.variant(wks.record("lifecycle", "PreToolUse", "toolu_probe_0001"), tool_suffix="started_only"), at=adm.at(1, 30))
    p.send(wks.record("lifecycle", "Stop"), at=adm.at(1, 31))
    p.send(wks.record("lifecycle", "PreCompact"), at=adm.at(1, 32))
    noise(p, 5, start=2)
    adm.send_call(p, "toolu_probe_0003", "g1", outcome_of="toolu_probe_0004", at_=adm.at(3))
    p.drain()
    (row,) = trigger_rows(p)
    assert (row["state"], row["subsequent_event_count"], row["resolved_by"]) == ("resolved", 5, p.event("tool_finished", call="toolu_probe_0003_g1")["id"])
    assert row["job_id"] is None and p.count("SELECT COUNT(*) FROM jobs WHERE kind = 'extract_claims' AND body LIKE '%trigger_ref\":\"trig_%'") == 0


def test_six_relevant_events_make_the_trigger_due(tmp_path):
    p = trigger_project(tmp_path)
    adm.send_call(p, "toolu_probe_0003", "f1", at_=adm.at(1))
    # Not relevant: a tool start alone, memory telemetry and lifecycle events.
    p.send(wks.variant(wks.record("lifecycle", "PreToolUse", "toolu_probe_0001"), tool_suffix="started_only"), at=adm.at(1, 30))
    p.send(wks.record("lifecycle", "Stop"), at=adm.at(1, 31))
    noise(p, 6, start=2)
    adm.send_call(p, "toolu_probe_0003", "g1", outcome_of="toolu_probe_0004", at_=adm.at(4))
    p.drain()
    (row,) = trigger_rows(p)
    assert (row["state"], row["due_reason"], row["subsequent_event_count"]) == ("due", "count", 6)
    with p.view() as v:
        job = jobs.get_job(v, row["job_id"])
    assert job.kind == "extract_claims" and job.trigger_ref == row["trigger_id"] and job.input_refs[0].id == row["failure_event_id"]
    request = requests.prepare_model_request(p.ctx, job, now=utc_now())  # bounded: the failure and what followed it
    shown = {e.event_id for e in request.events}
    assert row["failure_event_id"] in shown and len(shown) <= 1 + extract.MAX_TRIGGER_EVENTS + 8


def test_ten_minutes_make_the_trigger_due(tmp_path):
    p = trigger_project(tmp_path)
    adm.send_call(p, "toolu_probe_0003", "f1", at_=adm.at(1))
    adm.send_call(p, "toolu_probe_0003", "g1", outcome_of="toolu_probe_0004", at_=adm.at(11))  # at failure + 10 minutes exactly
    adm.send_call(p, "toolu_probe_0002", "f2", at_=adm.at(20))
    adm.send_call(p, "toolu_probe_0002", "g2", outcome_of="toolu_probe_0004", at_=adm.at(29, 59))  # 9:59 later
    p.drain()
    first, second = trigger_rows(p)
    assert (first["state"], first["due_reason"]) == ("due", "time")
    assert (second["state"], second["resolved_by"]) == ("resolved", p.event("tool_finished", call="toolu_probe_0002_g2")["id"])
    # No event at all: the worker's sweep makes a pending trigger due once its ten minutes passed.
    adm.send_call(p, "toolu_probe_0011", "f3", at_=adm.at(40))
    p.drain()
    (third,) = [t for t in trigger_rows(p) if t["state"] == "pending"]
    with db.open_store(p.ctx) as store:
        assert triggers.sweep(store, now=adm.at(49, 59)) == []
        assert triggers.sweep(store, now=adm.at(50)) == [third["trigger_id"]]
    assert next(t for t in trigger_rows(p) if t["trigger_id"] == third["trigger_id"])["due_reason"] == "time"


def test_late_success_resolves_a_time_due_trigger_before_its_extraction_runs(tmp_path):
    p = trigger_project(tmp_path)
    adm.send_call(p, "toolu_probe_0003", "f1", at_=adm.at(1))
    p.drain()
    with db.open_store(p.ctx) as store:
        (trigger_id,) = triggers.sweep(store, now=adm.at(12))  # the worker clock passed the due point first
    job_id = trigger_rows(p)[0]["job_id"]
    adm.send_call(p, "toolu_probe_0003", "g1", outcome_of="toolu_probe_0004", at_=adm.at(5))  # observed at minute 5, ingested late
    p.drain()
    (row,) = trigger_rows(p)
    assert row["state"] == "resolved"
    with p.view() as v:
        assert (jobs.get_job(v, job_id).state, jobs.get_job(v, job_id).last_error_code) == ("cancelled", "trigger_resolved")


def test_success_matches_family_across_changed_dependencies_only_in_the_same_task(tmp_path):
    p = trigger_project(tmp_path)
    adm.send_call(p, "toolu_probe_0003", "f1", at_=adm.at(1))
    adm.send_call(p, "toolu_probe_0010", "edit", at_=adm.at(2))  # a dependency changed (Edit result)
    adm.send_call(p, "toolu_probe_0004", "other", at_=adm.at(3))  # another family succeeds: counts, does not resolve
    adm.send_call(p, "toolu_probe_0003", "g1", outcome_of="toolu_probe_0004", at_=adm.at(4))
    p.drain()
    (row,) = trigger_rows(p)
    assert (row["state"], row["subsequent_event_count"]) == ("resolved", 2)
    # A success of the same family in another session's task does not resolve this task's trigger.
    other = wks.session_id(7)
    adm.send_call(p, "toolu_probe_0002", "f2", at_=adm.at(10))
    p.send(wks.variant(wks.record("lifecycle", "SessionStart"), session=other), at=adm.at(10, 5))
    p.send(wks.variant(wks.record("lifecycle", "UserPromptSubmit"), session=other, prompt="Unrelated work."), at=adm.at(10, 6))
    adm.send_call(p, "toolu_probe_0002", "g2", outcome_of="toolu_probe_0004", at_=adm.at(11), session=other)
    p.drain()
    second = [t for t in trigger_rows(p) if t["failure_event_id"] == p.event("tool_finished", call="toolu_probe_0002_f2")["id"]][0]
    assert second["state"] == "pending" and second["resolved_by"] is None


def test_null_family_never_matches_a_success(tmp_path):
    p = trigger_project(tmp_path)
    piped = "pytest -q test_mid.py | tee out.txt"  # a pipeline: no exact argv, so no family
    adm.send_call(p, "toolu_probe_0003", "f1", command=piped, at_=adm.at(1))
    adm.send_call(p, "toolu_probe_0003", "g1", command=piped, outcome_of="toolu_probe_0004", at_=adm.at(2))
    p.drain()
    (row,) = trigger_rows(p)
    assert row["action_family_digest"] is None and (row["state"], row["subsequent_event_count"]) == ("pending", 1)
    noise(p, 5, start=3)
    p.drain()
    assert trigger_rows(p)[0]["state"] == "due" and trigger_rows(p)[0]["due_reason"] == "count"
    # A second null-family failure starts its own trigger (no lexical matching).
    adm.send_call(p, "toolu_probe_0003", "f2", command=piped, at_=adm.at(9))
    p.drain()
    assert len(trigger_rows(p)) == 2


def test_repeated_known_failure_joins_its_pending_trigger(tmp_path):
    p = trigger_project(tmp_path)
    adm.send_call(p, "toolu_probe_0003", "f1", at_=adm.at(1))
    adm.send_call(p, "toolu_probe_0003", "f2", at_=adm.at(2))
    p.drain()
    (row,) = trigger_rows(p)
    assert (row["state"], row["subsequent_event_count"]) == ("pending", 1)


def test_expected_red_hint_is_dropped_and_still_triggers(tmp_path):
    """A66: a raw expected_red=true is untrusted (dropped with a coverage warning); a strict true is invalid; triggers still start."""
    from recalith.capture import pipeline
    from recalith.capture.normalize import RawEvent, normalize_event
    from recalith.contracts.events import EventEnvelope

    p = trigger_project(tmp_path)
    fail = wks.record("lifecycle", "PostToolUseFailure", "toolu_probe_0003")
    adm.send_call(p, "toolu_probe_0003", "f1", at_=adm.at(1))
    p.drain()
    stored = p.event("tool_finished", call="toolu_probe_0003_f1")
    raw = RawEvent(adapter_id="claude_code", adapter_version="2.1.301", source_event_key=f"hint:{new_id('act')}", session_id=p.session_of("session_started"), host_session_id=fail["payload"]["session_id"], kind="tool_finished", recorded_at=adm.at(1, 30),
                   payload={**{k: v for k, v in stored["payload"].items() if k not in ("assertions", "error_signature", "text_chunks")}, "tool_call_id": "hint-call", "expected_red": True})
    envelopes, notes = normalize_event(p.ctx, raw)
    assert envelopes[0].payload["expected_red"] is False and notes.warnings.get("expected_red_hint_dropped")
    with pytest.raises(ValueError):
        EventEnvelope.model_validate({**envelopes[0].model_dump(mode="json"), "payload": {**envelopes[0].payload, "expected_red": True}})
    assert pipeline.capture(p.ctx, envelopes).status == "accepted"
    p.drain()
    assert len(trigger_rows(p)) >= 1 and all(e["payload"]["expected_red"] is False for e in p.events("tool_finished"))


# ---------------------------------------------------------------------------
# Regions (pure; any newline convention; code points)


def test_regions_are_newline_independent_and_use_code_points():
    for nl in ("\n", "\r\n", "\r"):
        text = nl.join(["Zürich ✓ use uv.", "> I want poetry.", "```", "I prefer tabs", "```", "Keep tests."])
        found = regions.regions(text)
        kinds = [r.kind for r in found]
        assert kinds == ["blockquote", "fenced_code"]
        assert text[found[0].start : found[0].end] == "> I want poetry."
        assert text[found[1].start : found[1].end].startswith("```") and text[found[1].start : found[1].end].endswith("```")
        own = text.index("Keep tests.")
        assert regions.intersects(found, own, own + len("Keep tests.")) == []
        assert regions.intersects(found, 0, len("Zürich ✓ use uv.")) == []
    # No first-person heuristic: plain first-person prose is not a region, and an unclosed fence runs to the end.
    assert regions.regions("I want us to use uv. I decided that yesterday.") == []
    assert regions.regions("Do this.\n```\nI want X\nstill code")[0].end == len("Do this.\n```\nI want X\nstill code")
