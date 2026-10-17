"""Initial deterministic admission: schema, identity, revisions and evidence integrity.

``evaluate_operation`` (DATA_CONTRACTS §11) decides one proposed operation
against the current store. This preview slice checks only what is structural
(SYSTEM_SPEC §7.1): the actor may apply the kind; the operation's target names
the record its payload changes; every referenced record exists in *this*
installation (a foreign or invented ID simply does not exist here); a target
revision is the current head (otherwise the proposal is stale and is
re-evaluated, never overwritten); cited evidence exists, is available, keeps
its evidence-root identity, and every quoted span hashes to its digest; scope
names registered workspaces and existing tasks; status transitions are in the
policy table. Semantic evidence rules (mapping validators, independent roots,
declaration review, strength) are Task 9: a proposed claim is therefore
admitted ``candidate_only`` as a weak candidate, and a review assessment
changes nothing yet.

The read set a proposal was produced under is checked by
:func:`check_read_set`: a changed consulted record, policy revision,
tombstone epoch or live fingerprint means the whole proposal is re-evaluated.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from recalith.contracts.common import EvidenceLink, InstallationContext, ReadSet, RecordRef, Scope, digest_of
from recalith.contracts.events import MEMORY_KINDS
from recalith.contracts.memory import TaskBindingProposal
from recalith.contracts.operations import (
    AdmissionDecision,
    AttachEvidencePayload,
    BindEventsPayload,
    ChangeClaimStatusPayload,
    CreateEpisodePayload,
    CreateTaskPayload,
    ProposedOperation,
    RecordBoundaryPayload,
    ReviseClaimPayload,
    ReviseEpisodePayload,
    UpdateTaskPayload,
)
from recalith.core import policy
from recalith.core.paths import PathPolicy
from recalith.errors import RecalithError
from recalith.storage import records
from recalith.storage.db import Store, open_store
from recalith.working import bindings
from recalith.working import tasks as working_tasks

APPLY = "apply"
CANDIDATE = "candidate_only"
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


@dataclass(frozen=True)
class Verdict:
    outcome: str
    reason: str

    @property
    def admitted(self) -> bool:
        return self.outcome in (APPLY, CANDIDATE)


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
        return _ok(CANDIDATE, "review_admission_unavailable")  # assessment admission is Task 9
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
        typed_scope = typed.scope  # type: ignore[attr-defined]
        if (reason := check_scope(q, typed_scope)) is not None:
            return _no(reason)
        if typed.basis == "observed" and not any(link.mapping for link in op.evidence if link.relation == "supports"):  # type: ignore[attr-defined]
            return _no("observed_requires_mapping")  # DATA_CONTRACTS §5; validating the mapping itself is Task 9
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
        return _ok()
    if op.kind == "revise_claim":
        assert isinstance(typed, ReviseClaimPayload)
        if status not in policy.REVISABLE_STATUSES:
            return _no("status_not_revisable")
        if typed.scope is not None and (reason := check_scope(q, typed.scope)) is not None:
            return _no(reason)
        return _ok(CANDIDATE, "revision_pending_review")
    assert isinstance(typed, ChangeClaimStatusPayload)
    if typed.status == status:
        return _no("status_unchanged")
    if not policy.transition_allowed(status, typed.status):
        return _no("status_transition_refused")
    if typed.status in policy.STATUS_NEEDS_EVIDENCE and not op.evidence:
        return _no("evidence_required")
    if typed.status == "superseded":
        replacement = _replacement(q, typed, resolution)
        if isinstance(replacement, Verdict):
            return replacement
        if replacement is not None and replacement.id == subject.id:  # type: ignore[union-attr]
            return _no("replacement_is_target")
    return _ok()


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
