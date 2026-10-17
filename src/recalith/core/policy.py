"""Operation policy tables (SYSTEM_SPEC §7.2, §10; DATA_CONTRACTS §7.1, §8).

Code, not the model, decides which actor may apply which operation kind,
which claim status transitions exist, which changes are serving-relevant
(advance ``guidance_epoch``) and how far revision conflicts may re-evaluate.
This preview slice holds the structural rules (schema, identity, revisions,
evidence existence and quote integrity). Semantic evidence rules (deterministic
mappings, independent roots, declaration review, strength) are Task 9 and are
deliberately absent: until then a proposed claim is admitted only as a weak
candidate, never as active guidance.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from recalith.contracts.common import Actor

# Kinds that change memory records. ``no_op``, ``request_evidence`` and
# ``assess_claim`` (Task 9 admission) change nothing here.
MUTATING_KINDS = frozenset({
    "update_task", "create_episode", "revise_episode", "propose_claim", "attach_evidence", "revise_claim", "change_claim_status",
    "resolve_task_binding", "create_task", "bind_events", "record_boundary",
})

# Controller-only kinds (decision 0008): typed reduction opens provisional
# tasks, binds events and records boundary candidates. No model purpose may
# return them, and ``apply_proposal`` rejects them; they reach the store only
# through the deterministic reducer or a controller service writer.
REDUCTION_KINDS = frozenset({"create_task", "bind_events", "record_boundary"})

# These kinds change servable task/episode/claim/evidence state or task
# assignment, so they advance the guidance epoch. ``record_boundary`` stores a
# pending candidate (served nowhere), and ``bind_events`` is serving-relevant
# only when it writes a task revision (decided per change by the handler).
# Job completion, proposal persistence, requeue records and application audit
# rows are bookkeeping and do not.
SERVING_RELEVANT_KINDS = MUTATING_KINDS - {"record_boundary", "bind_events"}

# Who may apply what. The worker applies persisted model proposals; the guarded
# operator transport (Task 12a assigns the actor) applies typed service
# operations such as a correction or archive. Hooks, MCP callers and adapters
# never apply memory operations directly.
WORKER_KINDS = frozenset({"update_task", "resolve_task_binding", "create_episode", "revise_episode", "propose_claim", "assess_claim", "attach_evidence", "revise_claim", "change_claim_status", "request_evidence", "no_op"}) | REDUCTION_KINDS
# An operator binding outranks segmentation guesses (SYSTEM_SPEC §3.2); the
# guarded transport is Task 12a.
OPERATOR_KINDS = frozenset({"update_task", "resolve_task_binding", "propose_claim", "attach_evidence", "revise_claim", "change_claim_status", "no_op"})

LIVE_CLAIM_STATUSES = frozenset({"candidate", "active", "disputed"})
CONTENT_FREE_STATUSES = frozenset({"quarantined", "forgotten"})

# Requested status -> statuses it may be requested from. Superseded,
# invalidated, quarantined and forgotten heads are terminal for proposals
# (an operator undo appends a compensating revision instead).
STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "disputed": frozenset({"candidate", "active"}),
    "superseded": frozenset({"candidate", "active", "disputed", "archived"}),
    "invalidated": frozenset({"candidate", "active", "disputed", "archived"}),
    "archived": frozenset({"candidate", "active", "disputed"}),
}
# DATA_CONTRACTS §7.1: a status change carries evidence; dispute and
# invalidation are claims about the evidence, so they must cite it.
STATUS_NEEDS_EVIDENCE = frozenset({"disputed", "invalidated"})

REVISABLE_STATUSES = LIVE_CLAIM_STATUSES
TASK_UPDATABLE_STATUSES = frozenset({"active", "paused"})
# Tasks a session may be linked into or events reassigned to (never a placeholder).
TASK_LINKABLE_STATUSES = TASK_UPDATABLE_STATUSES


# Revision conflicts create bounded re-evaluation jobs (SYSTEM_SPEC §6.2): a
# job may be re-evaluated at most this many times along one chain; then it
# fails visibly with ``reevaluation_limit`` and nothing is overwritten.
REEVALUATION_LIMIT = 3

# Read-set fingerprints a curator may record and this build can recheck now.
# ``file:<portable path>`` is the SHA-256 of the current workspace file bytes
# (``absent`` digest when missing). Other kinds cannot be verified yet, so a
# proposal that consulted one cannot be applied (``read_set_unverifiable``).
FINGERPRINT_KINDS = ("file:",)
MAX_FINGERPRINTS = 64
MAX_FINGERPRINT_FILE_BYTES = 4 * 1024 * 1024

VOLATILE_REVIEW_DAYS = 30
STABLE_REVIEW_DAYS = 180

# Undo retires a record it created instead of deleting history.
UNDO_RETIRE_STATUS = {"claim": "archived", "episode": "archived"}
# Top-level body keys that are bookkeeping or code-derived, never restored or compared by undo.
UNDO_IGNORED_KEYS = frozenset({"revision", "updated_at", "recorded_at", "last_activity_at", "review_due_at"})


def allowed_kinds(actor: Actor) -> frozenset[str]:
    if actor.kind == "controller" and actor.channel == "worker":
        return WORKER_KINDS
    if actor.kind == "operator" and actor.channel == "cli":
        return OPERATOR_KINDS
    return frozenset()


def review_class(*, kind: str, basis: str, dependencies: list[Any]) -> str:
    """SYSTEM_SPEC §6.3: a dependency-free user-declared decision/preference is stable; all else volatile."""
    if kind in ("decision", "preference") and basis == "user_declared" and not dependencies:
        return "stable"
    return "volatile"


def review_due(recorded_at: _dt.datetime, review_class_name: str) -> _dt.datetime:
    return recorded_at + _dt.timedelta(days=STABLE_REVIEW_DAYS if review_class_name == "stable" else VOLATILE_REVIEW_DAYS)


def transition_allowed(current: str, requested: str) -> bool:
    return current in STATUS_TRANSITIONS.get(requested, frozenset())
