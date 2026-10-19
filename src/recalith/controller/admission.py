"""Deterministic admission: structure, identity, revisions, evidence and semantic gates.

``evaluate_operation`` (DATA_CONTRACTS §11) decides one proposed operation
against the current store. The structural checks (Task 5, SYSTEM_SPEC §7.1):
the actor may apply the kind; the operation's target names the record its
payload changes; every referenced record exists in *this* installation (a
foreign or invented ID simply does not exist here); a target revision is the
current head (otherwise the proposal is stale and is re-evaluated, never
overwritten); cited evidence exists, is available, keeps its evidence-root
identity (an event link names only the event's own roots; a record link only
roots its stored provenance reaches, ``core.lineage``), and every quoted span
hashes to its digest; scope names registered workspaces and existing tasks;
status transitions are in the policy table.

The semantic gates (Task 9, decision 0011) cannot prove natural-language
entailment; they decide mechanically what a claim may *be*:

* **Mappings.** ``tool.exit_code`` needs a finished certified invocation with
  a numeric exit code; ``tool.reported_result`` a certified ``ToolAssertion``
  named by its exact locator; ``config.exact_value`` has no registered parser
  in this build and is refused. A mapping is validated wherever it appears.
* **Observed.** Only a ``fact`` whose every support link carries a valid
  mapping, and whose proposition is exactly the code rendering of what those
  mappings observed (:func:`render_mapping`). A cause, a lesson or any wider
  wording is not mechanically supported; it can only be proposed as
  ``inferred`` and reviewed. An observed fact is admitted ``apply`` (active,
  strength from lineage) without a model.
* **User declared.** Every user-channel support span must be a direct user
  statement (``core.lineage`` user-declaration roots), complete, and outside
  every nondeclaration region (``core.regions``: fenced code, blockquotes,
  attachments, email and diff blocks, pasted output), checked by span
  intersection. Typed operator declarations get no bypass.
* **Failure lessons** cite a certified failure; code derives the body's
  ``last_supporting_failure_event_id`` and ``action_family_digest``.
* **Scope** never names a workspace the evidence does not come from.

Everything but an observed fact is admitted ``candidate_only`` as a weak
candidate and becomes active only through a supported review
(``controller.review``), when :func:`activation_refusal` finds nothing
against it. :func:`assign_strength` derives ``weak|supported|corroborated``
from lineage alone: retrieval, delivery and model self-confidence never
raise it.

The read set a proposal was produced under is checked by
:func:`check_read_set`: a changed consulted record, policy revision,
tombstone epoch or live fingerprint means the whole proposal is re-evaluated.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from pydantic import ValidationError

from recalith.contracts.common import EvidenceLink, InstallationContext, ReadSet, RecordRef, Scope, digest_of
from recalith.contracts.events import MEMORY_KINDS, EventEnvelope
from recalith.contracts.memory import TaskBindingProposal
from recalith.contracts.operations import (
    AdmissionDecision,
    AttachEvidencePayload,
    BindEventsPayload,
    ChangeClaimStatusPayload,
    CreateEpisodePayload,
    CreateTaskPayload,
    ProposeClaimPayload,
    ProposedOperation,
    RecordBoundaryPayload,
    ReviseClaimPayload,
    ReviseEpisodePayload,
    UpdateTaskPayload,
)
from recalith.core import lineage, policy, regions
from recalith.core.paths import PathPolicy
from recalith.errors import RecalithError
from recalith.storage import records
from recalith.storage.db import Store, open_store
from recalith.working import bindings
from recalith.working import tasks as working_tasks

APPLY = "apply"
CANDIDATE = "candidate_only"
REVIEW_REQUIRED = "review_required"
REJECT = "reject"
REQUEUE = "requeue"


@dataclass
class Resolution:
    """What earlier operations of the same application established.

    ``locals`` maps an applied local ref to the record it created or resolved
    to. ``base`` keeps the pre-application head revision of every existing
    record this application already changed, so a later operation naming that
    revision is not mistaken for a stale one. ``isolated`` evaluates one
    operation alone (``evaluate_operation``): local refs are unresolved yet.
    """

    locals: dict[str, RecordRef] = field(default_factory=dict)
    base: dict[tuple[str, str], int] = field(default_factory=dict)
    isolated: bool = False
    review: Any = None  # ``controller.review.ReviewScope`` while applying a review job's assessments


@dataclass(frozen=True)
class Verdict:
    outcome: str
    reason: str

    @property
    def admitted(self) -> bool:
        return self.outcome in (APPLY, CANDIDATE, REVIEW_REQUIRED)


def _ok(outcome: str = APPLY, reason: str = "admitted") -> Verdict:
    return Verdict(outcome, reason)


def _no(reason: str) -> Verdict:
    return Verdict(REJECT, reason)


def _stale(reason: str = "stale_revision") -> Verdict:
    return Verdict(REQUEUE, reason)


# --------------------------------------------------------------------------
# Read sets


def fingerprint_file(ctx: InstallationContext, rel: str) -> str:
    """SHA-256 of a workspace file's current bytes; a fixed ``absent`` digest when missing."""
    guard = PathPolicy([ctx.workspace_root])
    target = guard.authorize(rel)
    if not target.exists():
        return digest_of({"absent": rel})
    with guard.open_read(target) as fh:
        data = fh.read(policy.MAX_FINGERPRINT_FILE_BYTES + 1)
    if len(data) > policy.MAX_FINGERPRINT_FILE_BYTES:
        raise RecalithError("capability_unavailable", "fingerprinted file exceeds the bounded read")
    return hashlib.sha256(data).hexdigest()


def current_fingerprint(ctx: InstallationContext, key: str) -> str | None:
    """The current value of a read-set fingerprint key; None when this build cannot verify it."""
    if key.startswith("file:"):
        rel = key[len("file:") :]
        if not rel or rel.startswith("/") or "\\" in rel or "\x00" in rel or ".." in Path(rel).parts:
            return None
        try:
            return fingerprint_file(ctx, rel)
        except RecalithError:
            return None
    return None


def check_read_set(q: Any, ctx: InstallationContext, read_set: ReadSet) -> Verdict | None:
    """None when the read set still holds; otherwise requeue (changed) or reject (unverifiable)."""
    policy_revision, tombstone_epoch = q.execute("SELECT policy_revision, tombstone_epoch FROM installation_meta WHERE singleton = 1").fetchone()
    if read_set.policy_revision != policy_revision:
        return _stale("policy_changed")
    if read_set.tombstone_epoch != tombstone_epoch:
        return _stale("tombstone_epoch_changed")
    if read_set.workspace_id != ctx.workspace_id or q.execute("SELECT 1 FROM workspaces WHERE workspace_id = ? AND attachment_state IN ('primary', 'attached')", (read_set.workspace_id,)).fetchone() is None:
        return _no("workspace_unregistered")
    for ref in read_set.entity_revisions:
        if ref.kind in records.HEAD_TABLES:
            current = records.head(q, ref.kind, ref.id)
            if current is None:
                return _no("read_set_record_missing")
            if current[0] != ref.revision:
                return _stale("read_set_changed")
        elif not _source_exists(q, ref):
            return _stale("read_set_changed")
    if len(read_set.fingerprints) > policy.MAX_FINGERPRINTS:
        return _no("read_set_unverifiable")
    for key, expected in sorted(read_set.fingerprints.items()):
        current = current_fingerprint(ctx, key)
        if current is None:
            return _no("read_set_unverifiable")
        if current != expected:
            return _stale("fingerprint_changed")
    return None


def _source_exists(q: Any, ref: RecordRef) -> bool:
    if ref.kind == "event":
        row = q.execute("SELECT payload_state FROM events WHERE event_id = ?", (ref.id,)).fetchone()
        return row is not None and row[0] == "available" and ref.revision == 1
    return q.execute("SELECT 1 FROM evidence_capsules WHERE capsule_id = ?", (ref.id,)).fetchone() is not None


# --------------------------------------------------------------------------
# Evidence integrity


def _resolve_field(data: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(data, dict) and part in data:
            data = data[part]
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return None
    return data


def _quote_ok(source: Any, link: EvidenceLink) -> bool:
    loc = link.locator
    if loc is None:
        return True
    text = _resolve_field(source, loc.field)
    if not isinstance(text, str) or loc.end > len(text):
        return False
    return hashlib.sha256(text[loc.start : loc.end].encode("utf-8")).hexdigest() == loc.text_digest


def check_link(q: Any, link: EvidenceLink) -> str | None:
    """A reason code when cited evidence is missing, unavailable, re-rooted or misquoted."""
    ref = link.ref
    roots_needed = list(link.root_event_ids)
    if ref.kind == "event":
        row = q.execute("SELECT envelope, payload, payload_state FROM events WHERE event_id = ?", (ref.id,)).fetchone()
        if row is None or ref.revision != 1:
            return "evidence_missing"
        if row[2] != "available" or row[1] is None:
            return "evidence_unavailable"
        envelope = json.loads(row[0])
        if envelope.get("authority") == "derived" and envelope.get("kind") in MEMORY_KINDS:
            allowed: set[str] = set()  # delivery telemetry is never a support root
        elif envelope.get("derived_from"):
            allowed = set(envelope.get("root_event_ids") or [])
        else:
            allowed = {ref.id}
        if not set(roots_needed) <= allowed:
            return "root_mismatch"  # a proposal cannot invent or reassign evidence-root identity
        if not _quote_ok(json.loads(row[1]), link):
            return "quote_mismatch"
    elif ref.kind == "capsule":
        return "evidence_missing"  # capsules are a full-release feature; none exist in preview
    else:
        if not records.revision_exists(q, ref.kind, ref.id, ref.revision):
            return "evidence_missing"
        source = records.body(q, ref.kind, ref.id, ref.revision)
        if source is None:
            return "evidence_unavailable"
        if not _quote_ok(source, link):
            return "quote_mismatch"
        if roots_needed and not set(roots_needed) <= lineage.provenance_events(q, link):
            return "root_mismatch"  # a record link may name only roots its own stored provenance reaches
    for root in roots_needed:
        if q.execute("SELECT 1 FROM events WHERE event_id = ?", (root,)).fetchone() is None:
            return "root_missing"
    return None


def _payload_links(payload: dict[str, Any]) -> list[EvidenceLink]:
    return [EvidenceLink.model_validate(item) for item in records._walk_links(payload)]  # noqa: SLF001


def check_scope(q: Any, scope: Scope) -> str | None:
    for ws in scope.workspace_ids:
        if q.execute("SELECT 1 FROM workspaces WHERE workspace_id = ? AND attachment_state IN ('primary', 'attached')", (ws,)).fetchone() is None:
            return "scope_unregistered"
    for task in scope.task_ids:
        if records.head(q, "task", task) is None:
            return "scope_unregistered"
    return None


# --------------------------------------------------------------------------
# Semantic gates (Task 9, decision 0011)


def _stored_event(q: Any, event_id: str) -> tuple[EventEnvelope, dict[str, Any], int] | None:
    """The stored envelope (with its payload) and commit sequence; None when absent or unavailable."""
    row = q.execute("SELECT envelope, payload, payload_state, commit_sequence FROM events WHERE event_id = ?", (event_id,)).fetchone()
    if row is None or row[2] != "available" or row[1] is None:
        return None
    payload = json.loads(row[1])
    body = json.loads(row[0])
    body["payload"] = payload
    return EventEnvelope.model_validate(body), payload, int(row[3])


def _certified_result(env: EventEnvelope, payload: dict[str, Any]) -> bool:
    """A finished tool result under certified host authority (never derived or forwarded)."""
    return (
        env.kind == "tool_finished" and env.channel == "tool" and env.authority == "observed_tool" and not env.derived_from
        and payload.get("result_received") is True
    )


def invocation_label(payload: dict[str, Any]) -> str:
    """The captured invocation as rendered in an observed fact: the exact argv, else the tool name."""
    action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
    argv = action.get("argv")
    if isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv):
        return " ".join(argv)
    return str(payload.get("tool_name") or action.get("tool") or "tool")


_ASSERTION_FIELD = re.compile(r"^assertions\.(\d+)\.value$")


def _assertion_at(payload: dict[str, Any], link: EvidenceLink) -> dict[str, Any] | None:
    """The certified assertion a locator names exactly (the whole ``assertions.N.value`` string)."""
    if link.locator is None:
        return None
    m = _ASSERTION_FIELD.match(link.locator.field)
    assertions = payload.get("assertions") if isinstance(payload.get("assertions"), list) else []
    if m is None or int(m.group(1)) >= len(assertions):
        return None
    item = assertions[int(m.group(1))]
    value = item.get("value") if isinstance(item, dict) else None
    if not isinstance(value, str) or link.locator.start != 0 or link.locator.end != len(value):
        return None
    return item


def render_mapping(mapping: str, payload: dict[str, Any], assertion: dict[str, Any] | None) -> str:
    """The one proposition an observed mapping supports (what the tool reported, nothing broader)."""
    label = invocation_label(payload)
    if mapping == "tool.exit_code":
        return f"`{label}` exited with code {payload['exit_code']}."
    assert assertion is not None
    passed = assertion.get("passed")
    verdict = "" if passed is None else (" (passed)" if passed else " (failed)")
    return f"`{label}` reported {assertion['kind']} {assertion['identity']}: {assertion['value']}{verdict}."


def check_mapping(q: Any, link: EvidenceLink) -> tuple[str | None, str | None]:
    """(refusal, rendering) for a link that names a deterministic mapping (DATA_CONTRACTS §1.1, §6)."""
    mapping = link.mapping
    if mapping not in MAPPINGS:
        return "mapping_unregistered", None
    if MAPPINGS[mapping] is None:
        return "mapping_parser_unregistered", None  # config.exact_value: no registered config parser in this build
    if link.ref.kind != "event":
        return "mapping_requires_tool_result", None
    stored = _stored_event(q, link.ref.id)
    if stored is None or not _certified_result(stored[0], stored[1]):
        return "mapping_requires_tool_result", None
    payload = stored[1]
    if mapping == "tool.exit_code":
        code = payload.get("exit_code")
        if not isinstance(code, int) or isinstance(code, bool):
            return "mapping_requires_exit_code", None  # e.g. a host that never certifies exit 0 (decision 0005)
        if link.locator is not None:
            item = _assertion_at(payload, link)
            if item is None or item.get("kind") != "exit_status" or item.get("value") != str(code):
                return "mapping_locator_mismatch", None
        return None, render_mapping(mapping, payload, None)
    item = _assertion_at(payload, link)
    if item is None:
        return "mapping_requires_assertion", None
    if item.get("kind") not in ("test_result", "parsed_value") or not isinstance(item.get("identity"), str):
        return "mapping_requires_assertion", None
    return None, render_mapping(mapping, payload, item)


# Registered mapping validators; ``None`` names a mapping without a registered parser.
MAPPINGS: dict[str, Any] = {"tool.exit_code": check_mapping, "tool.reported_result": check_mapping, "config.exact_value": None}


def mapping_refusal(q: Any, links: Sequence[EvidenceLink]) -> str | None:
    for link in links:
        if link.mapping is not None:
            reason, _rendering = check_mapping(q, link)
            if reason is not None:
                return reason
    return None


def observed_refusal(q: Any, *, kind: str, proposition: str, supports: Sequence[EvidenceLink]) -> str | None:
    """An observed claim is exactly the rendering of its mapped observations, and only a fact."""
    if kind != "fact":
        return "observed_requires_fact"  # a lesson, decision or procedure is never mechanically observed
    if not supports or any(link.mapping is None for link in supports):
        return "observed_requires_mapping"
    renderings = set()
    for link in supports:
        reason, rendering = check_mapping(q, link)
        if reason is not None:
            return reason
        renderings.add(rendering)
    if renderings != {proposition}:
        return "observed_proposition_unmapped"  # a quote that exists does not support a wider statement
    return None


DECLARATION_FIELDS = {"user_message": "text", "operator_declaration": "statement", "operator_correction": "statement"}


def user_channel_link(q: Any, link: EvidenceLink) -> bool:
    if link.ref.kind != "event":
        return False
    row = q.execute("SELECT channel FROM events WHERE event_id = ?", (link.ref.id,)).fetchone()
    return row is not None and row[0] == "user"


def declaration_refusal(q: Any, link: EvidenceLink) -> str | None:
    """A direct user statement, complete, whose cited span lies outside every nondeclaration region."""
    if link.ref.kind != "event":
        return "declaration_requires_user_evidence"
    stored = _stored_event(q, link.ref.id)
    if stored is None:
        return "declaration_requires_user_evidence"
    env, payload, _seq = stored
    observation = lineage.classify(env)
    if not observation.eligible or observation.descriptor is None or observation.descriptor.observation_kind != "user_declaration":
        return "declaration_requires_user_evidence"  # host-generated, uncertified, derived or non-user text
    name = DECLARATION_FIELDS.get(env.kind)
    text = payload.get(name) if name else None
    if not isinstance(text, str):
        return "declaration_requires_user_evidence"
    part = payload.get("text_part")
    if env.coverage.truncated or env.coverage.missing_context or (isinstance(part, dict) and part.get("count", 1) != 1):
        return "declaration_coverage_incomplete"  # a fence may open in a part not shown: authorship is uncertain
    if link.locator is None:
        start, end = 0, len(text)
    elif link.locator.field != name:
        return "declaration_field_invalid"
    else:
        start, end = link.locator.start, link.locator.end
    if not text[start:end].strip():
        return "declaration_span_empty"
    if regions.intersects(regions.regions(text), start, end):
        return "declaration_in_nondeclaration_region"
    return None


def declared_refusal(q: Any, supports: Sequence[EvidenceLink]) -> str | None:
    """User-declared basis: at least one direct declaration; every user-channel span must be one."""
    direct = 0
    for link in supports:
        if user_channel_link(q, link):
            reason = declaration_refusal(q, link)
            if reason is not None:
                return reason
            direct += 1
    return None if direct else "declaration_requires_user_evidence"


def derive_failure(q: Any, supports: Sequence[EvidenceLink]) -> tuple[str | None, dict[str, Any] | None]:
    """The latest cited certified failure and its action family (code-derived index fields)."""
    from recalith.capture.normalize import action_family_digest

    latest: tuple[int, EventEnvelope, dict[str, Any]] | None = None
    for link in supports:
        if link.ref.kind != "event":
            continue
        stored = _stored_event(q, link.ref.id)
        if stored is None:
            continue
        env, payload, seq = stored
        if _certified_result(env, payload) and payload.get("outcome") == "failure" and (latest is None or seq > latest[0]):
            latest = (seq, env, payload)
    if latest is None:
        return "failure_lesson_requires_failure", None
    _seq, env, payload = latest
    action = payload.get("action") if isinstance(payload.get("action"), dict) else None
    family = action_family_digest(env.workspace_id, action) if action is not None else None
    return None, {"last_supporting_failure_event_id": env.event_id, "action_family_digest": family}


def failure_refusal(q: Any, supports: Sequence[EvidenceLink], body: dict[str, Any] | None) -> str | None:
    reason, derived = derive_failure(q, supports)
    if reason is not None:
        return reason
    assert derived is not None and body is not None
    for key, value in derived.items():
        if body.get(key) is not None and body.get(key) != value:
            return "failure_body_mismatch"  # the model may leave them null; code derives them
    return None


def scope_refusal(q: Any, scope: Scope, links: Sequence[EvidenceLink]) -> str | None:
    """A claim never names a workspace its evidence does not come from (narrowest justified scope)."""
    if not scope.workspace_ids:
        return None
    sources: set[str] = set()
    for link in links:
        if link.ref.kind == "event":
            row = q.execute("SELECT workspace_id FROM events WHERE event_id = ?", (link.ref.id,)).fetchone()
            if row is not None:
                sources.add(row[0])
    if sources and not set(scope.workspace_ids) <= sources:
        return "scope_broader_than_evidence"
    return None


def basis_refusal(q: Any, *, kind: str, basis: str, proposition: str, evidence: Sequence[EvidenceLink]) -> str | None:
    """What the proposed basis requires of its support links (at proposal and again at activation)."""
    supports = [link for link in evidence if link.relation == "supports"]
    if basis == "observed":
        return observed_refusal(q, kind=kind, proposition=proposition, supports=supports)
    if basis == "user_declared":
        return declared_refusal(q, supports)
    if not supports:
        return "inferred_requires_support"
    return None


def activation_refusal(q: Any, data: dict[str, Any]) -> str | None:
    """Why this claim revision may not become active guidance now (None: it may)."""
    supports = [EvidenceLink.model_validate(item) for item in data.get("supports") or []]
    for link in [*supports, *(EvidenceLink.model_validate(item) for item in data.get("contradicts") or [])]:
        reason = check_link(q, link)
        if reason is not None:
            return reason
    reason = mapping_refusal(q, supports) or basis_refusal(q, kind=data["kind"], basis=data["basis"], proposition=data["proposition"], evidence=supports)
    if reason is not None:
        return reason
    found = lineage.resolve(q, supports, proposition_key=data.get("proposition_key"))
    if not found.support_classes:
        return "no_primary_support"  # assistant text, telemetry or echoes alone support nothing
    if found.needs_revalidation:
        return "source_conflict_unresolved"
    return None


def assign_strength(q: Any, data: dict[str, Any]) -> str:
    """``weak|supported|corroborated`` from lineage only (SYSTEM_SPEC §7.1).

    A candidate (unreviewed) is weak. Active guidance is supported once its
    support resolves to an eligible class; corroborated needs at least two
    classes for the same scoped proposition, nothing blocking corroboration
    and no unresolved contradiction. One user's declarations collapse into
    one authority class, so they alone never exceed supported. Retrieval and
    delivery counts and model self-confidence are not inputs.
    """
    if data.get("status") not in ("active", "disputed"):
        return "weak"
    supports = [EvidenceLink.model_validate(item) for item in data.get("supports") or []]
    contradicts = [EvidenceLink.model_validate(item) for item in data.get("contradicts") or []]
    found = lineage.resolve(q, [*supports, *contradicts], proposition_key=data.get("proposition_key"))
    if not found.support_classes:
        return "weak"
    if len(found.support_classes) >= 2 and not found.corroboration_blocked and not contradicts:
        return "corroborated"
    return "supported"


# --------------------------------------------------------------------------
# One operation


def _current(q: Any, ref: RecordRef, resolution: Resolution) -> tuple[Verdict | None, tuple[int, str] | None]:
    """Is ``ref`` the current head (as of this application's base)? Returns (failure, head)."""
    current = records.head(q, ref.kind, ref.id)
    if current is None:
        return _no("target_missing"), None
    expected = resolution.base.get((ref.kind, ref.id), current[0])
    if ref.revision != expected:
        return _stale(), current
    return None, current


def subject_ref(op: ProposedOperation, typed: Any) -> RecordRef | None:
    """The existing record an operation changes (its required ``target`` when set)."""
    if isinstance(typed, (UpdateTaskPayload, BindEventsPayload)):
        return RecordRef(kind="task", id=typed.task_id, revision=typed.expected_revision)
    if isinstance(typed, ReviseEpisodePayload):
        return RecordRef(kind="episode", id=typed.episode_id, revision=typed.expected_revision)
    if isinstance(typed, (AttachEvidencePayload, ReviseClaimPayload, ChangeClaimStatusPayload)):
        return typed.claim_ref
    return None


def check_operation(q: Any, ctx: InstallationContext, op: ProposedOperation, *, resolution: Resolution) -> Verdict:
    if op.kind not in policy.allowed_kinds(ctx.actor):
        return _no("kind_not_permitted")
    if op.kind == "request_evidence":
        return _no("evidence_request_not_applicable")  # expansion rounds are never persisted or applied
    try:
        typed = op.typed_payload()
    except ValidationError:
        return _no("malformed_payload")
    subject = subject_ref(op, typed)
    if op.kind == "assess_claim":
        from recalith.controller import review  # deferred: review builds on these gates

        return review.check_assessment(q, ctx, op, typed, resolution.review)  # type: ignore[arg-type]
    if op.target is not None and op.target != subject:
        return _no("target_mismatch")
    if op.kind == "no_op":
        return _ok(APPLY, "no_op")
    if isinstance(typed, ChangeClaimStatusPayload) and typed.replacement_local_ref is not None and typed.replacement_local_ref not in op.depends_on:
        return _no("undeclared_dependency")

    head = None
    if subject is not None:
        failure, head = _current(q, subject, resolution)
        if failure is not None:
            return failure

    extra_links = list(typed.evidence) if isinstance(typed, TaskBindingProposal) else []
    for link in [*op.evidence, *_payload_links(op.payload), *extra_links]:
        reason = check_link(q, link)
        if reason is not None:
            return _no(reason)

    if op.kind == "update_task":
        assert head is not None
        if head[1] not in policy.TASK_UPDATABLE_STATUSES:
            return _no("task_not_updatable")  # also refuses reactivating or adding actions to a linked placeholder
        if (reason := _completion(q, typed, head)) is not None:  # type: ignore[arg-type]
            return _no(reason)
        return _ok()
    if op.kind == "create_task":
        assert isinstance(typed, CreateTaskPayload)
        return _verdict(bindings.check_create_task(q, ctx, typed))
    if op.kind == "bind_events":
        assert isinstance(typed, BindEventsPayload)
        return _verdict(bindings.check_bind_events(q, ctx, typed))
    if op.kind == "record_boundary":
        assert isinstance(typed, RecordBoundaryPayload)
        return _verdict(bindings.check_record_boundary(q, ctx, typed))
    if op.kind == "resolve_task_binding":
        assert isinstance(typed, TaskBindingProposal)
        if bindings.stale_bindings(q, typed):
            return _stale(bindings.STALE)
        return _verdict(bindings.check_resolve(q, ctx, typed))
    if op.kind == "create_episode":
        assert isinstance(typed, CreateEpisodePayload)
        task = records.head(q, "task", typed.task_id)
        if task is None:
            return _no("task_missing")
        if task[1] == "linked":
            return _no("task_redirected")
        for event_id in typed.source_event_ids:
            if check_link(q, EvidenceLink(ref=RecordRef(kind="event", id=event_id, revision=1), relation="context")) is not None:
                return _no("evidence_missing")
            bound = bindings.binding_head(q, event_id)
            if bound is not None and working_tasks.resolve_task(q, bound["task_id"]) != typed.task_id:
                return _no("event_bound_elsewhere")  # an episode recounts its own task's events
        if (reason := check_scope(q, typed.scope)) is not None:
            return _no(reason)
        if typed.ended_at is not None and typed.ended_at < typed.started_at:
            return _no("malformed_payload")
        return _ok()
    if op.kind == "revise_episode":
        assert head is not None
        if head[1] == "archived":
            return _no("episode_archived")
        return _ok()
    if op.kind == "propose_claim":
        assert isinstance(typed, ProposeClaimPayload)
        reason = (
            check_scope(q, typed.scope)
            or mapping_refusal(q, op.evidence)
            or basis_refusal(q, kind=typed.kind, basis=typed.basis, proposition=typed.proposition, evidence=op.evidence)
            or (failure_refusal(q, [link for link in op.evidence if link.relation == "supports"], typed.failure.model_dump(mode="json")) if typed.failure is not None else None)
            or _procedure_refusal(q, typed)
            or scope_refusal(q, typed.scope, op.evidence)
            or _dependency_refusal(q, ctx, typed.dependencies, op.evidence)
        )
        if reason is not None:
            return _no(reason)
        if typed.basis == "observed":
            return _ok(APPLY, "observed_mapping")  # a valid deterministic mapping: active without a model
        return _ok(CANDIDATE, "candidate_pending_review")
    assert head is not None
    status = head[1]
    if status in policy.CONTENT_FREE_STATUSES:
        return _no("target_unavailable")
    if op.kind == "attach_evidence":
        assert isinstance(typed, AttachEvidencePayload)
        if status not in policy.LIVE_CLAIM_STATUSES:
            return _no("claim_not_live")
        if not op.evidence:
            return _no("evidence_required")
        if any(link.relation != typed.relation for link in op.evidence):
            return _no("relation_mismatch")
        if (reason := mapping_refusal(q, op.evidence)) is not None:
            return _no(reason)
        if typed.relation == "supports":
            body = records.body(q, "claim", typed.claim_ref.id, typed.claim_ref.revision) or {}
            if body.get("basis") == "observed" and (reason := observed_refusal(q, kind=body["kind"], proposition=body["proposition"], supports=op.evidence)) is not None:
                return _no(reason)
            if body.get("basis") == "user_declared":
                for link in op.evidence:
                    if user_channel_link(q, link) and (reason := declaration_refusal(q, link)) is not None:
                        return _no(reason)
        return _ok()
    if op.kind == "revise_claim":
        assert isinstance(typed, ReviseClaimPayload)
        if status not in policy.REVISABLE_STATUSES:
            return _no("status_not_revisable")
        if typed.scope is not None and (reason := check_scope(q, typed.scope)) is not None:
            return _no(reason)
        if (reason := mapping_refusal(q, op.evidence)) is not None:
            return _no(reason)
        body = records.body(q, "claim", typed.claim_ref.id, typed.claim_ref.revision) or {}
        if typed.retry_conditions is not None and body.get("kind") != "failure_lesson":
            return _no("retry_conditions_require_failure_lesson")
        if typed.dependencies is not None and (reason := _dependency_refusal(q, ctx, typed.dependencies, [EvidenceLink.model_validate(i) for i in body.get("supports") or []])) is not None:
            return _no(reason)
        return _ok(CANDIDATE, "revision_pending_review")
    assert isinstance(typed, ChangeClaimStatusPayload)
    if typed.status == status:
        return _no("status_unchanged")
    if not policy.transition_allowed(status, typed.status):
        return _no("status_transition_refused")
    if typed.status in policy.STATUS_NEEDS_EVIDENCE and not op.evidence:
        return _no("evidence_required")
    if typed.status == "invalidated" and not any(link.relation == "contradicts" for link in op.evidence):
        return _no("invalidation_requires_contradiction")  # direct refutation is cited as such; a later success alone is context
    if ctx.actor.kind != "operator" and typed.status in ("invalidated", "archived") and status in ("active", "disputed"):
        body = records.body(q, "claim", subject.id, subject.revision) or {}  # type: ignore[union-attr]
        if body.get("basis") == "user_declared" and body.get("kind") in ("decision", "preference"):
            return _no("declaration_requires_user_intent")  # only the user (or a reviewed replacement declaration) retires a declared intent
    if typed.status == "superseded":
        replacement = _replacement(q, typed, resolution)
        if isinstance(replacement, Verdict):
            return replacement
        if replacement is not None and replacement.id == subject.id:  # type: ignore[union-attr]
            return _no("replacement_is_target")
        if replacement is not None and status in ("active", "disputed") and ctx.actor.kind != "operator":
            current = records.head(q, "claim", replacement.id)
            if current is None or current[1] not in ("active", "candidate"):
                return _no("replacement_requires_review")
            if current[1] == "candidate":
                # Active guidance is replaced only by reviewed (or observed) guidance: an unreviewed replacement holds the
                # supersession until its own review activates it, and both then commit together (decision 0012).
                return Verdict(REVIEW_REQUIRED, "replacement_pending_review")
            target_body = records.body(q, "claim", subject.id, subject.revision) or {}  # type: ignore[union-attr]
            if target_body.get("basis") == "user_declared" and target_body.get("kind") in ("decision", "preference"):
                new_body = records.body(q, "claim", replacement.id, current[0]) or {}
                if new_body.get("basis") != "user_declared" or new_body.get("kind") != target_body.get("kind"):
                    return _no("declaration_requires_user_intent")  # a decision is replaced only by a reviewed user decision
    return _ok()


def _dependency_refusal(q: Any, ctx: InstallationContext, dependencies: Sequence[Any], evidence: Sequence[EvidenceLink]) -> str | None:
    from recalith.controller import revalidate  # deferred: the dependency index builds on these gates

    return revalidate.resolve_dependencies(q, ctx, dependencies, evidence)[0]


def _procedure_refusal(q: Any, typed: ProposeClaimPayload) -> str | None:
    if typed.procedure is None:
        return None
    for episode_id in typed.procedure.successful_episode_ids:
        if records.head(q, "episode", episode_id) is None:
            return "episode_missing"
    return None


def _verdict(reason: str | None) -> Verdict:
    return _ok() if reason is None else _no(reason)


def _completion(q: Any, typed: UpdateTaskPayload, head: tuple[int, str]) -> str | None:
    """Completion only with completion evidence (SYSTEM_SPEC §3.2); idle or a passing test never suffices."""
    if not any(p.op == "status" and p.status == "completed" for p in typed.patches):
        return None
    basis = next((p.value for p in reversed(typed.patches) if p.op == "set" and p.field == "completion_basis"), None)
    if basis is None:
        body = records.body(q, "task", typed.task_id, head[0]) or {}
        basis = body.get("completion_basis")
    if not working_tasks.completion_supported({"completion_basis": basis}):
        return "completion_requires_evidence"
    return None


def _replacement(q: Any, typed: ChangeClaimStatusPayload, resolution: Resolution) -> RecordRef | Verdict | None:
    if typed.replacement_local_ref is not None:
        if resolution.isolated:
            return None
        ref = resolution.locals.get(typed.replacement_local_ref)
        if ref is None or ref.kind != "claim":
            return _no("replacement_unresolved")
        return ref
    assert typed.replacement_ref is not None
    if typed.replacement_ref.kind != "claim":
        return _no("replacement_unresolved")
    failure, head = _current(q, typed.replacement_ref, resolution)
    if failure is not None:
        return failure
    assert head is not None
    if head[1] not in policy.LIVE_CLAIM_STATUSES:
        return _no("replacement_not_live")
    return typed.replacement_ref


def decision(op: ProposedOperation, verdict: Verdict, operation_id: str | None) -> AdmissionDecision:
    return AdmissionDecision(local_ref=op.local_ref, outcome=verdict.outcome, reason_code=verdict.reason, resolved_operation_id=operation_id)  # type: ignore[arg-type]


def evaluate_operation(ctx: InstallationContext, operation: ProposedOperation, read_set: ReadSet, *, store: Store | None = None) -> AdmissionDecision:
    """Evaluate one operation alone against a consistent read snapshot (no write).

    Local refs it depends on are unresolved here; :func:`apply_proposal`
    re-evaluates every operation inside its write transaction, in dependency
    order, before anything is applied.
    """
    own = store is None
    store = store or open_store(ctx, readonly=True)
    try:
        with store.read() as view:
            verdict = check_read_set(view, ctx, read_set) or check_operation(view, ctx, operation, resolution=Resolution(isolated=True))
    finally:
        if own:
            store.close()
    return decision(operation, verdict, None)
