"""Task 1 contract tests: strict DTOs, authority boundaries and defaults."""

from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

import factories as f
from recalith.contracts.common import (
    Condition,
    ReadSet,
    Scope,
    canonical_json,
    derived_id,
    digest_of,
    filter_environment,
    new_id,
)
from recalith.contracts.config import (
    BudgetConfig,
    ProjectConfig,
    ProviderConfig,
    RetentionConfig,
    RetentionValue,
    body_cap_for,
    estimate_tokens,
)
from recalith.contracts.context import ContextItem, ContextPacket, DeliveryReceipt, OutcomeLink, SessionScratch
from recalith.contracts.events import CaptureReceipt, EventEnvelope, Segment, TextChunk, ToolAssertion, ToolPayload
from recalith.contracts.health import ALL_CAPABILITIES, DEFERRED_FULL_CAPABILITIES, REQUIRED_CAPABILITIES, HealthReport
from recalith.contracts.jobs import BudgetReservation, FailureRecheck, Job
from recalith.contracts.memory import ClaimRevision, ReviewBatch, RootClass, TaskState
from recalith.contracts.operations import ModelProposalBody, ModelResponse, ProposedOperation, UsageReport, parse_model_body
from recalith.contracts.privacy import ForgetResult, ForgetSelector, OperatorTokenFile, Tombstone
from recalith.contracts.transfers import UpgradeResult
from recalith.errors import RecalithError


def rejects(model, data, match: str | None = None):
    with pytest.raises(ValidationError, match=match):
        model.model_validate(data)


# ---------------------------------------------------------------- required tests


def test_event_rejects_unknown_fields():
    EventEnvelope.model_validate(f.envelope())
    rejects(EventEnvelope, {**f.envelope(), "actor": {"kind": "operator"}}, "Extra inputs")
    rejects(EventEnvelope, {**f.envelope(), "is_operator": True}, "Extra inputs")
    bad_payload = f.tool_payload(authority="explicit_user")
    rejects(EventEnvelope, f.envelope(payload=bad_payload), "Extra inputs")
    # Nested reference objects are strict too.
    env = f.envelope()
    env["origin"] = {**env["origin"], "trusted": True}
    rejects(EventEnvelope, env, "Extra inputs")


def test_provider_cannot_set_actor():
    good = {"operations": [f.operation("propose_claim", f.claim_payload())], "no_op_reason": None}
    ModelProposalBody.model_validate(good)
    # No actor, usage or provider metadata in what a model may return.
    for key, value in (("actor", {"kind": "operator", "id": "x", "channel": "cli"}), ("usage", {}), ("provider", "claude")):
        rejects(ModelProposalBody, {**good, key: value}, "Extra inputs")
    # Payload keys are enumerated per kind: identity, authority and installation stay code-assigned.
    for key, value in (("actor", "operator"), ("authority", "explicit_user"), ("strength", "corroborated"), ("status", "active"), ("installation_id", f.INSTALL), ("project_id", f.PROJECT), ("claim_id", new_id("claim"))):
        rejects(ProposedOperation, f.operation("propose_claim", {**f.claim_payload(), key: value}), "Extra inputs")
    # A status change cannot hand out an active/trusted status.
    rejects(ProposedOperation, f.operation("change_claim_status", {"claim_ref": f.ref(), "status": "active"}))
    # Linking a task is code-owned, never a provider status patch.
    rejects(ProposedOperation, f.operation("update_task", {"task_id": new_id("task"), "expected_revision": 1, "patches": [{"op": "status", "status": "linked"}]}))


def test_scope_unknown_is_not_true():
    item = {"ref": f.ref(), "text": "Use the src layout.", "advice": "context", "basis": "observed", "applicability": "unknown", "freshness": "current", "why": ["lexical_match"]}
    ok = ContextItem.model_validate(item)
    assert ok.applicability == "unknown" and ok.applicability != "true"
    rejects(ContextItem, {**item, "applicability": True})  # JSON booleans are not tri-state strings
    rejects(ContextItem, {**item, "advice": "caution"}, "caution requires")  # unknown never supplies a caution
    rejects(ContextItem, {**item, "applicability": "false"}, "inapplicable")
    ContextItem.model_validate({**item, "advice": "caution", "applicability": "true"})
    rejects(ContextItem, {**item, "advice": "caution", "applicability": "true", "freshness": "needs_revalidation"})
    # Missing environment facts are absent, not defaulted; unregistered keys are not conditions.
    assert Scope.model_validate({}).environment == {}
    with pytest.raises(ValidationError):
        Condition.model_validate({"kind": "environment_equals", "key": "HOME", "value": "/home/x"})


# ---------------------------------------------------------------- validation details


@pytest.mark.parametrize("stamp", ["2026-10-15T12:00:00Z", "2026-10-15T12:00:00.000000+00:00", "2026-02-30T00:00:00.000000Z", "2026-10-15 12:00:00.000000Z", "2026-10-15T12:00:00.000000z"])
def test_invalid_timestamps_rejected(stamp):
    rejects(EventEnvelope, f.envelope(recorded_at=stamp))


def test_nonfinite_json_rejected():
    env = f.envelope("user_message")
    env["payload"] = {"text": "x", "score": math.nan}
    rejects(EventEnvelope, env, "finite")
    raw = json.dumps(f.envelope("user_message")).replace('"Please run the tests."', "NaN")
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate_json(raw)
    with pytest.raises(ValueError):
        canonical_json({"x": math.inf})


def test_payload_digest_and_size_enforced():
    env = f.envelope()
    rejects(EventEnvelope, {**env, "payload_digest": f.sha("other")}, "payload_digest")
    big = {"text": "x" * (64 * 1024)}
    rejects(EventEnvelope, f.envelope("user_message", payload=big), "64 KiB")


def test_channel_authority_pairs():
    rejects(EventEnvelope, f.envelope("assistant_message", authority="explicit_user"), "explicit_user")
    rejects(EventEnvelope, f.envelope("user_message", authority="observed_tool"), "observed_tool")
    rejects(EventEnvelope, f.envelope("memory_delivered", authority="untrusted"), "memory telemetry")
    env = f.envelope("agent_attempted_operator_command")
    EventEnvelope.model_validate(env)
    rejects(EventEnvelope, {**env, "root_event_ids": [env["event_id"]]}, "no eligible root")
    rejects(EventEnvelope, f.envelope("agent_attempted_operator_command", payload={"command_kind": "declare", "marker_category": "host_agent", "reason_code": "policy_refused", "statement": "x"}))


def test_expected_red_is_reserved_false():
    rejects(EventEnvelope, f.envelope(payload=f.tool_payload(expected_red=True)))
    assert ToolPayload.model_validate(f.tool_payload()).expected_red is False


def test_tool_started_has_no_result():
    EventEnvelope.model_validate(f.envelope("tool_started"))
    rejects(EventEnvelope, f.envelope("tool_started", payload=f.tool_payload()), "tool_started")
    rejects(ToolPayload, f.tool_payload(result_received=False), "without a received result")


def test_original_event_is_its_own_root():
    env = f.envelope()
    EventEnvelope.model_validate({**env, "root_event_ids": [env["event_id"]]})
    rejects(EventEnvelope, {**env, "root_event_ids": [f.event_id("other")]}, "own root")


def test_tool_assertion_and_chunk_shapes():
    rejects(ToolAssertion, {"kind": "exit_status", "identity": "exit", "value": "01"}, "canonical")
    rejects(ToolAssertion, {"kind": "parsed_value", "identity": "v", "value": "x", "passed": True}, "verdict")
    ToolAssertion.model_validate({"kind": "test_result", "identity": "tests/test_a.py::test_x", "value": "failed", "passed": False})
    text = "AssertionError: é"
    TextChunk.model_validate({"stored_field": "result_text_tail", "source_field": "result_text", "original_start": 900, "original_end": 900 + len(text), "text": text, "text_digest": f.sha(text)})
    rejects(TextChunk, {"stored_field": "a", "source_field": "b", "original_start": 0, "original_end": 3, "text": text, "text_digest": f.sha(text)}, "length")


def test_unknown_parse_cannot_invent_action():
    rejects(EventEnvelope, f.envelope(payload=f.tool_payload(action=f.action(parse_status="unknown"))), "unknown parse")
    EventEnvelope.model_validate(f.envelope(payload=f.tool_payload(action=f.action(parse_status="unknown", executable=None, argv=None, action_kind=None))))


def test_identifiers_and_paths():
    assert new_id("claim").startswith("claim_")
    assert derived_id("evt", ["a"]) == derived_id("evt", ["a"])
    with pytest.raises(ValueError):
        new_id("bogus")
    rejects(EventEnvelope, f.envelope(project_id="proj_NOT-A-UUID"))
    rejects(EventEnvelope, f.envelope(project_id="PROJ_11111111-1111-4111-8111-111111111111"))
    for bad in ("../x", "/abs", "a//b", "C:/x", "a\\b", "./a"):
        rejects(Scope, {"paths": [bad]})
    Scope.model_validate({"paths": ["src/", "docs/readme.md"]})


def test_environment_filter_drops_unregistered_without_echo():
    kept, dropped = filter_environment({"os": "linux", "HOME": "/home/secret", "python_version": "3.12.4", "arch": "sparc"})
    assert kept == {"os": "linux", "python_version": "3.12.4"}
    assert dropped == {"<unregistered>": 1, "arch": 1}
    assert "/home/secret" not in json.dumps(dropped)


def test_segment_rejects_foreign_installation():
    mine = EventEnvelope.model_validate(f.envelope())
    theirs = EventEnvelope.model_validate(f.envelope(installation_id="inst_77777777-7777-4777-8777-777777777777", source_event_key="other"))
    for envs, ok in (([mine], True), ([mine, theirs], False)):
        body = {"envelopes": [e.model_dump(mode="json") for e in envs], "cursor_proposals": []}
        seg = {"segment_schema": 1, "segment_id": new_id("src"), "project_id": f.PROJECT, "installation_id": f.INSTALL, "envelopes": body["envelopes"], "cursor_proposals": [], "created_at": f.TIME, "content_digest": digest_of(body)}
        if ok:
            Segment.model_validate(seg)
        else:
            rejects(Segment, seg, "foreign_installation")


def test_capture_receipt_shapes():
    CaptureReceipt.model_validate({"status": "not_captured", "segment_id": None, "event_ids": [], "coverage": {}, "error_code": "disk_full"})
    rejects(CaptureReceipt, {"status": "not_captured", "segment_id": None, "event_ids": [], "coverage": {}, "error_code": None})
    rejects(CaptureReceipt, {"status": "accepted", "segment_id": None, "event_ids": [], "coverage": {}, "error_code": None})


# ---------------------------------------------------------------- claims and review


def test_claim_policy_shapes():
    ClaimRevision.model_validate(f.claim())
    rejects(ClaimRevision, f.claim(supports=[f.evidence_link(mapping=None)]), "deterministic evidence mapping")
    rejects(ClaimRevision, f.claim(basis="inferred"), "supported review")
    ClaimRevision.model_validate(f.claim(basis="inferred", review_assessment=f.review()))
    rejects(ClaimRevision, f.claim(kind="decision", basis="user_declared", supports=[f.evidence_link(mapping=None)]), "no bypass")
    rejects(ClaimRevision, f.claim(kind="decision", basis="user_declared", supports=[f.evidence_link(mapping=None)], review_assessment=f.review("revise")), "no bypass")
    ClaimRevision.model_validate(f.claim(kind="decision", basis="user_declared", status="candidate", supports=[f.evidence_link(mapping=None)]))
    forgotten = f.claim(status="forgotten", proposition="", proposition_key=None, supports=[], basis="inferred")
    ClaimRevision.model_validate(forgotten)
    rejects(ClaimRevision, {**forgotten, "proposition": "leftover text"}, "no content")
    failure = {"action_family_digest": None, "last_supporting_failure_event_id": None, "observed_failure": f.supported()}
    rejects(ClaimRevision, f.claim(kind="failure_lesson", failure=failure, review_class="stable"), "volatile")
    rejects(ClaimRevision, f.claim(strength="corroborated", contradicts=[f.evidence_link(relation="contradicts")]), "corroboration")


def test_review_assessment_operation_bounds():
    cand = f.ref()
    payload = {"batch_id": new_id("batch"), "candidate_ref": cand, "verdict": "reject", "objections": ["review_capacity"], "evidence_ids": []}
    op = {"local_ref": "a1", "kind": "assess_claim", "depends_on": [], "target": cand, "payload": payload, "evidence": [], "reason": ""}
    ProposedOperation.model_validate(op)
    rejects(ProposedOperation, {**op, "reason": "the extractor said so"}, "empty reason")
    rejects(ProposedOperation, {**op, "target": f.ref()}, "target equals")
    rejects(ProposedOperation, {**op, "payload": {**payload, "objections": ["x" * 161]}}, "160")
    rejects(ProposedOperation, {**op, "payload": {**payload, "objections": ["a", "b", "c"]}})
    rejects(ProposedOperation, {**op, "payload": {**payload, "verdict": "supported"}}, "evidence id")
    maxed = {**payload, "objections": ["é" * 80, "é" * 80], "evidence_ids": [new_id("rev"), new_id("rev")]}
    assert len(canonical_json({**op, "payload": maxed})) > 768
    rejects(ProposedOperation, {**op, "payload": maxed}, "768")


def test_review_responses_are_terminal_or_expansion_not_both():
    cand = f.ref()
    assess = {"local_ref": "a1", "kind": "assess_claim", "depends_on": [], "target": cand, "payload": {"batch_id": new_id("batch"), "candidate_ref": cand, "verdict": "reject", "objections": [], "evidence_ids": []}, "evidence": [], "reason": ""}
    expand = f.operation("request_evidence", {"request_kind": "record", "ref": f.ref("event", f.event_id("x"))}, local_ref="e1")
    body = ModelProposalBody.model_validate({"operations": [assess, expand]})
    with pytest.raises(ValueError, match="not both"):
        body.validate_for_purpose("review_claims")
    with pytest.raises(ValueError, match="not permitted"):
        ModelProposalBody.model_validate({"operations": [f.operation("propose_claim", f.claim_payload())]}).validate_for_purpose("review_claims")


def test_operation_graph_is_acyclic_and_closed():
    a = f.operation("no_op", {}, local_ref="a", depends_on=["b"])
    b = f.operation("no_op", {}, local_ref="b", depends_on=["a"])
    rejects(ModelProposalBody, {"operations": [a, b]}, "cycle")
    rejects(ModelProposalBody, {"operations": [f.operation("no_op", {}, local_ref="a", depends_on=["zz"])]}, "unknown local ref")
    rejects(ModelProposalBody, {"operations": [f.operation("no_op", {}), f.operation("no_op", {})]}, "unique")
    rejects(ModelProposalBody, {"operations": []}, "no_op_reason")


def test_model_body_cap_precedes_parsing_and_15kb_episode_fits():
    task = new_id("task")
    episode = {
        "task_id": task,
        "title": "Fix import path",
        "started_at": f.TIME,
        "objective": f.supported("Make the test suite import the package."),
        "steps": [{"ordinal": 0, "action": f.supported("x" * 7000), "outcome": "failure"}, {"ordinal": 1, "action": f.supported("y" * 7000), "outcome": "success"}],
        "outcome": f.supported("Tests pass."),
        "source_event_ids": [f.event_id("tool_finished-1")],
    }
    raw = json.dumps({"operations": [f.operation("create_episode", episode)]}).encode()
    assert 15_000 <= len(raw) <= body_cap_for("build_episode") == 24_000
    parse_model_body(raw, purpose="build_episode", body_cap=body_cap_for("build_episode"))
    with pytest.raises(ValueError, match="never clipped"):
        parse_model_body(raw, purpose="review_claims", body_cap=body_cap_for("review_claims"))


def test_model_response_metadata_is_adapter_assigned():
    body = ModelProposalBody.model_validate({"operations": [], "no_op_reason": "nothing new"})
    usage = UsageReport(input_tokens=None, output_tokens=None, estimated_input_tokens=10, estimated_output_tokens=3, provider_request_id=None, duration_ms=5)
    resp = ModelResponse.from_body(body, usage, None)
    assert resp.response_schema == 1 and resp.usage.estimated_input_tokens == 10


def test_review_batch_identity():
    c1, c2 = f.ref(), f.ref()
    batch = {"batch_id": new_id("batch"), "origin_job_id": new_id("job"), "review_job_id": new_id("job"), "candidate_refs": [c1, c2], "candidate_digests": {c1["id"]: f.sha("1"), c2["id"]: f.sha("2")}, "evidence_digest": f.sha("e"), "prompt_digest": f.sha("p"), "evidence_index": [], "read_set": {"workspace_id": f.WORKSPACE, "policy_revision": 1, "tombstone_epoch": 0}}
    ReviewBatch.model_validate(batch)
    rejects(ReviewBatch, {**batch, "candidate_refs": [c1] * 9}, "at most 8")
    rejects(ReviewBatch, {**batch, "candidate_digests": {c1["id"]: f.sha("1")}}, "cover exactly")


def test_root_class_canonical_origin():
    keys = [{"source_namespace": "inst_a", "source_event_key": "b"}, {"source_namespace": "inst_a", "source_event_key": "a"}]
    RootClass.model_validate({"root_class_id": derived_id("root", keys[1]), "canonical_origin": keys[1], "member_origin_keys": keys, "equivalence_reasons": ["origin_identity"]})
    rejects(RootClass, {"root_class_id": derived_id("root", keys[0]), "canonical_origin": keys[0], "member_origin_keys": keys}, "least")


def test_linked_placeholder_carries_no_actions():
    base = {"task_id": new_id("task"), "project_id": f.PROJECT, "installation_id": f.INSTALL, "revision": 2, "status": "linked", "redirect_task_id": new_id("task"), "title": "provisional", "objective": None, "updated_at": f.TIME, "last_activity_at": f.TIME}
    TaskState.model_validate(base)
    rejects(TaskState, {**base, "redirect_task_id": None}, "redirect")
    rejects(TaskState, {**base, "next_action": f.supported("run tests")}, "no pending")
    rejects(TaskState, {**base, "status": "completed", "redirect_task_id": None}, "completion")


# ---------------------------------------------------------------- jobs, budgets, delivery


def test_budget_reservation_pools_and_caps():
    base = {"reservation_id": new_id("att"), "job_id": new_id("job"), "invocation_id": new_id("att"), "utc_day": "2026-10-15", "purpose": "extract_claims", "ordinary": {"invocations": 1, "input_estimate": 5000, "output_estimate": 8000}, "protected": {"invocations": 0, "input_estimate": 0, "output_estimate": 0}, "estimated_input_limit": 5000, "estimated_output_limit": 8000, "max_response_body_bytes": 24000, "state": "reserved"}
    BudgetReservation.model_validate(base)
    rejects(BudgetReservation, {**base, "ordinary": {"invocations": 0, "input_estimate": 0, "output_estimate": 0}, "protected": {"invocations": 1, "input_estimate": 5000, "output_estimate": 8000}}, "protected reserves")
    rejects(BudgetReservation, {**base, "max_response_body_bytes": 30000}, "3 ×")
    review = {**base, "purpose": "review_claims", "estimated_output_limit": 3000, "max_response_body_bytes": 9000, "ordinary": {"invocations": 0, "input_estimate": 1000, "output_estimate": 1000}, "protected": {"invocations": 1, "input_estimate": 4000, "output_estimate": 2000}}
    BudgetReservation.model_validate(review)  # protected first, then remaining ordinary capacity
    assert estimate_tokens(10) == 4 and body_cap_for("update_task") == 4500


def test_job_pool_and_priority_rules():
    base = {"job_id": new_id("job"), "kind": "review_claims", "state": "pending", "input_digest": f.sha("i"), "policy_revision": 1, "prompt_version": "review_v1", "idempotency_key": f.sha("k"), "priority": 0, "due_at": f.TIME, "attempt": 0, "budget_pool": "protected", "review_priority": "correction_or_declaration"}
    Job.model_validate(base)
    rejects(Job, {**base, "budget_pool": "ordinary"}, "protected")
    rejects(Job, {**base, "review_priority": None}, "review priority")
    rejects(Job, {**base, "kind": "ingest", "prompt_version": None, "review_priority": None}, "no model budget")
    rejects(Job, {**base, "state": "leased"}, "lease")


def test_failure_recheck_chronology():
    base = {"claim_ref": f.ref(), "success_event_id": f.event_id("s"), "supporting_failure_event_id": None, "reason": "later_success", "action_family_digest": f.sha("fam")}
    rejects(FailureRecheck, base, "order_unknown")
    FailureRecheck.model_validate({**base, "reason": "order_unknown"})


def test_packet_substitution_and_receipts():
    caution = {"ref": f.ref(), "text": "Do not run X before Y.", "advice": "caution", "basis": "observed", "applicability": "true", "freshness": "current", "why": ["exact_action_match"]}
    packet = {"packet_schema": 1, "project_id": f.PROJECT, "installation_id": f.INSTALL, "store_revision": 3, "guidance_epoch": 2, "policy_revision": 1, "tombstone_epoch": 0, "generated_at": f.TIME, "purpose": "prompt", "items": [caution], "omitted_count": 0, "estimated_tokens": 450, "pre_action_substitution_tokens": 400}
    ContextPacket.model_validate(packet)
    rejects(ContextPacket, {**packet, "pre_action_substitution_tokens": 401})
    rejects(ContextPacket, {**packet, "purpose": "compact_restore"}, "only an ordinary prompt")
    rejects(ContextPacket, {**packet, "items": [{**caution, "advice": "context"}]}, "without an eligible caution")
    rejects(ContextItem, {**caution, "why": ["because I said so"]}, "ReasonCode")
    receipt = {"delivery_id": new_id("dlv"), "attempt_id": new_id("att"), "host_id": "claude_code", "session_id": f.SESSION, "task_id": None, "packet_digest": f.sha("p"), "items": [], "purpose": "prompt", "fence_store_revision": 3, "guidance_epoch": 2, "policy_revision": 1, "tombstone_epoch": 0, "generated_at": f.TIME, "emitted_at": None, "estimated_tokens": 0, "pre_action_substitution_tokens": 0, "state": "uncertain"}
    DeliveryReceipt.model_validate(receipt)
    rejects(DeliveryReceipt, {**receipt, "state": "emitted"}, "emission time")
    rejects(OutcomeLink, {"delivery_id": new_id("dlv"), "observed_event_ids": [], "label": "task_succeeded"}, "observed")


def test_session_scratch_bounds():
    base = {"scratch_schema": 1, "session_id": f.SESSION, "state_revision": 0, "store_revision": 0, "guidance_epoch": 0, "policy_revision": 1, "tombstone_epoch": 0, "reserved_tokens": 0, "emitted_tokens": 0}
    SessionScratch.model_validate(base)
    outcome = {"event_id": f.event_id("o"), "action": f.action(), "outcome": "failure"}
    rejects(SessionScratch, {**base, "outcomes": [outcome] * 33})


# ---------------------------------------------------------------- privacy, health, config


def test_forgetting_shapes():
    rejects(ForgetSelector, {}, "at least one")
    ForgetSelector.model_validate({"task_ids": [new_id("task")]})
    base = {"operation_id": new_id("op"), "purge_state": "completed", "purged_count": 3, "quarantined_count": 1, "tombstone_epoch": 2, "backup_state": "unavailable", "new_backup_id": None, "deleted_backup_ids": [new_id("bkp")], "external_copy_ids": [], "replay_suppression_coverage": {}, "error_codes": ["backup_unavailable_after_forget"]}
    ForgetResult.model_validate(base)
    rejects(ForgetResult, {**base, "error_codes": []}, "backup_unavailable_after_forget")
    rejects(Tombstone, {"target_ids": [new_id("claim")], "created_at": f.TIME, "epoch": 1, "deletion_scope": "record", "text": "the forgotten prose"}, "Extra inputs")


def test_operator_token_file_shape():
    good = {"schema": 1, "token_id": new_id("tok"), "secret": "a" * 64, "created_at": f.TIME}
    OperatorTokenFile.parse_file_bytes(json.dumps(good).encode())
    for bad in ({**good, "secret": "a" * 62}, {**good, "extra": 1}, {**good, "token_id": new_id("job")}, {**good, "secret": "!" * 64}):
        with pytest.raises(ValueError):
            OperatorTokenFile.parse_file_bytes(json.dumps(bad).encode())
    with pytest.raises(ValueError, match="4 KiB"):
        OperatorTokenFile.parse_file_bytes(b" " * 5000)
    with pytest.raises(ValueError) as info:
        OperatorTokenFile.parse_file_bytes(b"secret-material-not-json")
    assert "secret-material" not in str(info.value)


def capability(state="healthy", required=False, reasons=()):
    return {"state": state, "required": required, "reason_codes": list(reasons)}


def health(profile="claude_preview", **states):
    caps = {}
    for name in ALL_CAPABILITIES:
        if name in REQUIRED_CAPABILITIES:
            caps[name] = capability(required=True)
        elif name in DEFERRED_FULL_CAPABILITIES:
            caps[name] = capability("unavailable", reasons=["deferred_full_release"])
        else:
            caps[name] = capability("unavailable", reasons=["not_certified"])
    caps.update(states)
    return {"release_profile": profile, "capabilities": caps, "worker_state": "idle", "retention_summary": {"pinned_payload_bytes": 0, "unpinned_payload_bytes": 0, "live_owner_count": 0, "free_disk_bytes": None, "deferred_compaction_count": 0}}


def test_health_readiness_is_required_capabilities_only():
    HealthReport.model_validate({**health(), "autonomous_ready": True})  # optional paths unavailable are fine
    rejects(HealthReport, {**health(), "autonomous_ready": False}, "exactly")
    degraded = health(prompt_delivery=capability("degraded", True, ["canary_failed"]))
    HealthReport.model_validate({**degraded, "autonomous_ready": False})
    rejects(HealthReport, {**degraded, "autonomous_ready": True})
    rejects(HealthReport, {**health(mcp=capability()), "autonomous_ready": True}, "deferred")
    partial = health()
    del partial["capabilities"]["mcp"]
    rejects(HealthReport, {**partial, "autonomous_ready": True}, "every registered capability")


def test_project_config_defaults_follow_profile():
    preview = f.config()
    assert preview.retention.unpinned_event_payload.days == 180 and preview.worker.idle_poll_seconds == 5
    full = f.config(release_profile="full")
    assert full.retention.unpinned_event_payload.days == 30 and full.worker.idle_poll_seconds == 30
    assert preview.budgets.daily_invocations == 90 and preview.budgets.protected_invocations == 30
    assert preview.context.prompt == 1000 and preview.context.pre_action_substitution == 400
    override = RetentionConfig(unpinned_event_payload=RetentionValue(days=365, source="operator_override"))
    ProjectConfig(project_id=f.PROJECT, retention=override)
    with pytest.raises(ValidationError, match="profile default"):
        ProjectConfig(project_id=f.PROJECT, release_profile="full", retention=RetentionConfig())
    with pytest.raises(ValidationError, match="protected reserve"):
        BudgetConfig(protected_invocations=91)
    with pytest.raises(ValidationError, match="session worker"):
        ProjectConfig(project_id=f.PROJECT, worker={"mode": "session"})


def test_provider_config_rejects_schema_tool_flag():
    base = {"provider_id": "claude_cli", "backend": "claude_cli", "executable": "/usr/bin/claude", "configured_model": "m", "installation_id": f.INSTALL, "auth_route": "env_api_key", "auth_env_keys": ["ANTHROPIC_API_KEY"], "invocation_args": ["-p", "--bare"], "certification": {"certified": False}}
    ProviderConfig.model_validate(base)
    rejects(ProviderConfig, {**base, "invocation_args": ["-p", "--json-schema", "{}"]}, "decision 0002")


def test_upgrade_result_rules():
    base = {"operation_id": new_id("op"), "source_profile": "claude_preview", "target_profile": "full", "source_engine": "0.1", "target_engine": "0.2", "state": "not_activated", "preserved_installation_id": f.INSTALL, "verified_backup_id": None, "baseline_digest": None, "retained_pin_count": 0}
    UpgradeResult.model_validate(base)
    rejects(UpgradeResult, {**base, "state": "activated"}, "verified backup")
    rejects(UpgradeResult, {**base, "source_profile": "full", "target_profile": "claude_preview"}, "downgrade")


def test_read_set_and_canonical_json_are_stable():
    rs = ReadSet(workspace_id=f.WORKSPACE, policy_revision=1, tombstone_epoch=0, fingerprints={"b": f.sha("2"), "a": f.sha("1")})
    assert canonical_json(rs) == canonical_json(rs.model_dump(mode="json"))
    assert canonical_json({"b": 1, "a": "é"}) == '{"a":"é","b":1}'.encode()


def test_recalith_error_codes():
    err = RecalithError("policy_refused", "agent channel")
    assert err.code == "policy_refused" and err.exit_code == 6
    assert RecalithError("not_captured", "x").exit_code == 7
    assert RecalithError("capability_degraded", "x").exit_code == 8
    with pytest.raises(ValueError):
        RecalithError("made_up", "x")
