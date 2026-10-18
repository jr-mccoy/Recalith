"""Job queue: code-assigned priority, leases with fencing, retry and coalescing.

DATA_CONTRACTS §8 and SYSTEM_SPEC §6.2. Rules implemented here:

* **Priority is assigned by code.** :func:`band_for` maps a job kind (and, for
  reviews, the code-assigned review priority) to the model scheduling order:
  (1) correction/declaration review, (2) ordinary review, (3) completed-attempt
  episode work, (4) extraction and task narrative, (5) due revalidation, (6)
  broad consolidation (a revalidation job the planner enqueues with
  ``priority=BAND_CONSOLIDATION``). Ties
  use oldest due time, then job ID. :func:`review_priority_for` derives the
  review priority from guarded provenance and candidate kind, never from a
  provider-supplied number; it grants scheduling order only, not authorship.
* **Leases are fenced.** :func:`lease_next` takes the next *due* job in one
  write transaction and increments its ``lease_generation``. Every later
  write for that attempt runs through :func:`fenced`, which requires the same
  owner and generation, state ``leased`` and an unexpired lease. A worker
  whose lease expired, or was superseded by a newer lease, can no longer
  persist a proposal or apply a result.
* **A model job is launch-eligible only when due, leaseable and its
  reservation fits.** :func:`lease_next` checks the purpose's smallest
  possible reservation before leasing; a job that cannot fit is set to
  ``waiting_budget`` with its reason visible in ``last_error_code``. The exact
  reservation is made after the request is prepared (``budgets.reserve``).
* **Retry/backoff.** A failed attempt is retried after 1, 5 and 30 minutes;
  after that the job is ``failed`` until a scheduled or explicit retry.
* **Coalescing.** Equivalent jobs share an idempotency key. An enqueue with
  ``coalesce=True`` cancels older, not-yet-leased jobs of the same kind over
  the same records. Recurring maintenance is scheduled for the *current* slot
  only, so a suspend/resume clock jump creates one job, not one per missed
  slot.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
from dataclasses import dataclass
from typing import Any, Collection, Iterable, Iterator, Sequence

from recalith.contracts.common import InstallationContext, RecordRef, canonical_json, digest_of, format_utc, new_id, parse_utc
from recalith.contracts.config import REVIEW_BATCH_MAX_CANDIDATES, BudgetConfig
from recalith.contracts.jobs import MODEL_JOB_KINDS, Job
from recalith.controller import budgets
from recalith.errors import RecalithError
from recalith.storage import failpoints
from recalith.storage.db import Store, Txn, open_store
from recalith.storage.repository import idempotency_key

# Model scheduling bands (SYSTEM_SPEC §6.2); deterministic kinds keep their own order.
BAND_DECLARATION_REVIEW = 1
BAND_REVIEW = 2
BAND_EPISODE = 3
BAND_EXTRACTION = 4
BAND_REVALIDATION = 5
BAND_CONSOLIDATION = 6  # broad consolidation (SYSTEM_SPEC §6.2 item 6): revalidation jobs over candidate groups
DETERMINISTIC_BANDS = {"ingest": 0, "compile_context": 1, "maintenance": 2, "export": 3}
DETERMINISTIC_KINDS = frozenset(DETERMINISTIC_BANDS)
MODEL_KINDS = frozenset(MODEL_JOB_KINDS)
LEASEABLE_STATES = ("pending", "waiting_budget")

DETERMINISTIC_LEASE_SECONDS = 60
MODEL_LEASE_MARGIN_SECONDS = 60
HOUSEKEEPING_INTERVAL_SECONDS = 24 * 3600
COALESCED = "coalesced"
PROVIDER_UNAVAILABLE = "provider_unavailable"


def band_for(kind: str, review_priority: str | None = None) -> int:
    if kind == "review_claims":
        return BAND_DECLARATION_REVIEW if review_priority == "correction_or_declaration" else BAND_REVIEW
    if kind == "build_episode":
        return BAND_EPISODE
    if kind in ("extract_claims", "update_task"):
        return BAND_EXTRACTION
    if kind == "revalidate":
        return BAND_REVALIDATION
    return DETERMINISTIC_BANDS[kind]


def pool_for(kind: str) -> str:
    if kind not in MODEL_KINDS:
        return "none"
    return "protected" if budgets.is_protected(kind) else "ordinary"


# --------------------------------------------------------------------------
# Review priority and batches (code-assigned)


@dataclass(frozen=True)
class ReviewCandidate:
    """The guarded facts that decide review priority; Task 9 supplies them per candidate.

    ``origin`` is assigned by the transport/extractor code: an operator
    correction or declaration (guarded CLI), a typed declaration, or ordinary
    extraction. ``direct_user_evidence`` means the candidate passed the
    declaration checks on eligible direct user evidence. Pasted or quoted text
    never sets it.
    """

    claim_id: str
    origin: str  # operator_correction | operator_declaration | typed_declaration | extracted
    claim_kind: str
    direct_user_evidence: bool = False


PRIORITY_ORIGINS = frozenset({"operator_correction", "operator_declaration", "typed_declaration"})
DECLARATION_KINDS = frozenset({"decision", "preference"})


def candidate_is_priority(candidate: ReviewCandidate) -> bool:
    if candidate.origin in PRIORITY_ORIGINS:
        return True
    return candidate.origin == "extracted" and candidate.claim_kind in DECLARATION_KINDS and candidate.direct_user_evidence


def review_priority_for(candidates: Iterable[ReviewCandidate]) -> str:
    """A batch with any correction/declaration candidate gets the highest review priority."""
    return "correction_or_declaration" if any(candidate_is_priority(c) for c in candidates) else "ordinary"


def plan_review_batches(candidates: Sequence[ReviewCandidate], *, max_candidates: int = REVIEW_BATCH_MAX_CANDIDATES) -> list[list[ReviewCandidate]]:
    """Partition one extraction's candidates, in order, into bounded review batches."""
    return [list(candidates[i : i + max_candidates]) for i in range(0, len(candidates), max_candidates)]


# --------------------------------------------------------------------------
# Persistence helpers


def _job(body: str) -> Job:
    return Job.model_validate_json(body)


def _save(txn: Txn, job: Job) -> None:
    job = Job.model_validate(job.model_dump())
    txn.execute(
        "UPDATE jobs SET state = ?, priority = ?, due_at = ?, attempt = ?, lease_owner = ?, lease_generation = ?, lease_until = ?, budget_pool = ?, review_priority = ?, body = ? WHERE job_id = ?",
        (job.state, job.priority, job.due_at, job.attempt, job.lease_owner, job.lease_generation, job.lease_until, job.budget_pool, job.review_priority, canonical_json(job).decode(), job.job_id),
    )
    txn.mutated(serving_relevant=False)  # queue bookkeeping never advances guidance


def get_job(view: Any, job_id: str) -> Job | None:
    row = view.execute("SELECT body FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return None if row is None else _job(row[0])


def _plus(now: str, seconds: float) -> str:
    return format_utc(parse_utc(now) + _dt.timedelta(seconds=seconds))


def _input_ids(refs: Iterable[RecordRef]) -> list[str]:
    return sorted({f"{r.kind}:{r.id}" for r in refs})


def enqueue(
    txn: Txn,
    *,
    kind: str,
    input_refs: Sequence[RecordRef],
    now: str,
    prompt_version: str | None = None,
    review_candidates: Sequence[ReviewCandidate] = (),
    due_at: str | None = None,
    coalesce: bool = False,
    idempotency: str | None = None,
    review_priority: str | None = None,
    trigger_ref: str | None = None,
    priority: int | None = None,
) -> tuple[str, bool]:
    """Create a job once per idempotency key; priority and pool are computed here.

    ``review_priority`` lets a re-evaluation inherit the code-assigned priority
    of the review job it replaces; a new review job derives it from its candidates.
    """
    if priority is not None and (kind != "revalidate" or priority not in (BAND_REVALIDATION, BAND_CONSOLIDATION)):
        raise RecalithError("invalid_schema", "only revalidation chooses between the revalidation and consolidation bands")
    if kind == "review_claims" and not review_candidates and review_priority is None:
        raise RecalithError("invalid_schema", "a review job names its candidates so code can assign its priority")
    if kind == "review_claims":
        review_priority = review_priority_for(review_candidates) if review_candidates else review_priority
    else:
        review_priority = None
    meta = txn.meta
    key = idempotency or idempotency_key(kind, input_refs, policy_revision=meta.policy_revision, prompt_version=prompt_version, tombstone_epoch=meta.tombstone_epoch)
    existing = txn.one("SELECT job_id FROM jobs WHERE idempotency_key = ?", (key,))
    if existing is not None:
        return existing[0], False
    job = Job(
        job_id=new_id("job"),
        kind=kind,
        state="pending",
        input_refs=list(input_refs),
        input_digest=digest_of([r.model_dump(mode="json") for r in input_refs]),
        policy_revision=meta.policy_revision,
        prompt_version=prompt_version,
        idempotency_key=key,
        priority=band_for(kind, review_priority) if priority is None else priority,
        due_at=due_at or now,
        attempt=0,
        budget_pool=pool_for(kind),
        review_priority=review_priority,
        trigger_ref=trigger_ref,
    )
    if coalesce and input_refs:
        ids = _input_ids(input_refs)
        for (body,) in txn.execute("SELECT body FROM jobs WHERE kind = ? AND state IN ('pending', 'waiting_budget')", (kind,)).fetchall():
            older = _job(body)
            if _input_ids(older.input_refs) == ids:
                _save(txn, older.model_copy(update={"state": "cancelled", "last_error_code": COALESCED}))
    txn.execute(
        "INSERT INTO jobs (job_id, kind, state, idempotency_key, priority, due_at, attempt, lease_generation, budget_pool, review_priority, body) VALUES (?, ?, 'pending', ?, ?, ?, 0, 0, ?, ?, ?)",
        (job.job_id, job.kind, key, job.priority, job.due_at, job.budget_pool, job.review_priority, canonical_json(job).decode()),
    )
    txn.mutated(serving_relevant=False)
    return job.job_id, True


def schedule_housekeeping(txn: Txn, *, now: str, interval_seconds: int = HOUSEKEEPING_INTERVAL_SECONDS) -> str | None:
    """Recurring maintenance for the current slot only: a clock jump yields one job."""
    if txn.one("SELECT 1 FROM jobs WHERE kind = 'maintenance' AND state IN ('pending', 'leased', 'waiting_budget')") is not None:
        return None
    moment = parse_utc(now)
    slot = int(moment.timestamp()) // interval_seconds
    slot_start = format_utc(_dt.datetime.fromtimestamp(slot * interval_seconds, tz=_dt.timezone.utc))
    key = digest_of(["maintenance", "housekeeping", slot, txn.meta.policy_revision, txn.meta.tombstone_epoch])
    job_id, created = enqueue(txn, kind="maintenance", input_refs=[], now=now, due_at=slot_start, idempotency=key)
    return job_id if created else None


# --------------------------------------------------------------------------
# Leasing


def lease_seconds(kind: str, config: BudgetConfig) -> int:
    return config.timeout_seconds + MODEL_LEASE_MARGIN_SECONDS if kind in MODEL_KINDS else DETERMINISTIC_LEASE_SECONDS


def _candidates(txn: Txn, now: str, kinds: Collection[str]) -> list[Job]:
    marks = ",".join("?" for _ in kinds)
    rows = txn.execute(
        f"SELECT body FROM jobs WHERE kind IN ({marks}) AND due_at <= ? AND (state IN ('pending', 'waiting_budget') OR (state = 'leased' AND lease_until <= ?)) ORDER BY priority, due_at, job_id LIMIT 200",  # noqa: S608 - placeholders only
        (*kinds, now, now),
    ).fetchall()
    return [_job(r[0]) for r in rows]


def lease_next(
    ctx: InstallationContext,
    *,
    owner: str,
    now: str,
    kinds: Collection[str] | None = None,
    store: Store | None = None,
    config: BudgetConfig | None = None,
) -> Job | None:
    """Lease the next due, eligible job (DATA_CONTRACTS §11).

    ``kinds`` selects a lane (deterministic or model); by default every kind.
    Model jobs are skipped, and marked ``waiting_budget`` with a visible
    reason, when even their smallest reservation cannot fit today. The
    returned job carries the new ``lease_generation`` (its fencing token).
    """
    config = config or BudgetConfig()
    kinds = tuple(sorted(set(kinds) if kinds is not None else DETERMINISTIC_KINDS | MODEL_KINDS))
    own = store is None
    store = store or open_store(ctx)
    try:
        with store.transaction() as txn:
            used = limits = None
            for job in _candidates(txn, now, kinds):
                if job.kind in MODEL_KINDS:
                    if used is None:
                        used, limits = budgets.used_by_pool(txn, budgets.utc_day(now)), budgets.pool_limits(config)
                    refusal = budgets.fits_lower_bound(job.kind, used=used, limits=limits)
                    if refusal is not None:
                        if job.state != "waiting_budget" or job.last_error_code != refusal.reason:
                            _save(txn, job.model_copy(update={"state": "waiting_budget", "last_error_code": refusal.reason, "lease_owner": None, "lease_until": None}))
                        continue
                leased = job.model_copy(
                    update={
                        "state": "leased",
                        "lease_owner": owner,
                        "lease_generation": job.lease_generation + 1,
                        "lease_until": _plus(now, lease_seconds(job.kind, config)),
                        "attempt": job.attempt if job.kind in MODEL_KINDS else job.attempt + 1,
                        "last_error_code": None if job.last_error_code in (PROVIDER_UNAVAILABLE,) or (job.last_error_code or "").startswith("budget_exhausted") else job.last_error_code,
                    }
                )
                _save(txn, leased)
                break
            else:
                return None
        failpoints.hit(failpoints.JOB_AFTER_LEASE)
        return leased
    finally:
        if own:
            store.close()


@contextlib.contextmanager
def fenced(store: Store, job: Job, *, now: str) -> Iterator[Txn]:
    """A write transaction that applies only while ``job``'s lease is still current.

    Raises ``revision_conflict`` (and writes nothing) when the job was leased
    again (newer generation), released, completed, or the lease expired.
    """
    with store.transaction() as txn:
        current = get_job(txn, job.job_id)
        if (
            current is None
            or current.state != "leased"
            or current.lease_generation != job.lease_generation
            or current.lease_owner != job.lease_owner
            or current.lease_until is None
            or current.lease_until <= now
        ):
            raise RecalithError("revision_conflict", "lease fenced: a newer or expired lease cannot apply this result")
        yield txn


def _current(txn: Txn, job: Job) -> Job:
    current = get_job(txn, job.job_id)
    assert current is not None
    return current


def complete(txn: Txn, job: Job, *, proposal_ref: str | None = None) -> Job:
    current = _current(txn, job)
    done = current.model_copy(update={"state": "completed", "lease_owner": None, "lease_until": None, "last_error_code": None, "proposal_ref": proposal_ref or current.proposal_ref})
    _save(txn, done)
    return done


def set_proposal(txn: Txn, job: Job, proposal_ref: str) -> Job:
    current = _current(txn, job).model_copy(update={"proposal_ref": proposal_ref})
    _save(txn, current)
    return current


def supersede(txn: Txn, job: Job, code: str) -> Job:
    """A conflict replaced this attempt with a re-evaluation job; it never applies."""
    current = _current(txn, job)
    done = current.model_copy(update={"state": "cancelled", "lease_owner": None, "lease_until": None, "last_error_code": code[:64]})
    _save(txn, done)
    return done


def count_attempt(txn: Txn, job: Job) -> Job:
    """A model launch is an attempt (charged even when it fails)."""
    current = _current(txn, job)
    current = current.model_copy(update={"attempt": current.attempt + 1})
    _save(txn, current)
    return current


def fail(txn: Txn, job: Job, code: str, *, now: str, backoff: Sequence[int]) -> Job:
    """Retry after 1, 5, 30 minutes (by attempt); then ``failed`` until an explicit retry."""
    current = _current(txn, job)
    attempt = max(current.attempt, 1)
    if attempt <= len(backoff):
        update = {"state": "pending", "due_at": _plus(now, backoff[attempt - 1])}
    else:
        update = {"state": "failed"}
    failed = current.model_copy(update={**update, "lease_owner": None, "lease_until": None, "last_error_code": code[:64]})
    _save(txn, failed)
    return failed


def wait_budget(txn: Txn, job: Job, reason: str) -> Job:
    current = _current(txn, job)
    waiting = current.model_copy(update={"state": "waiting_budget", "lease_owner": None, "lease_until": None, "last_error_code": reason[:64]})
    _save(txn, waiting)
    return waiting


def release(txn: Txn, job: Job, *, reason: str | None = None) -> Job:
    current = _current(txn, job)
    released = current.model_copy(update={"state": "pending", "lease_owner": None, "lease_until": None, "last_error_code": reason or current.last_error_code})
    _save(txn, released)
    return released


def renew(store: Store, job: Job, *, now: str, config: BudgetConfig) -> Job:
    with fenced(store, job, now=now) as txn:
        renewed = _current(txn, job).model_copy(update={"lease_until": _plus(now, lease_seconds(job.kind, config))})
        _save(txn, renewed)
    return renewed


def recover_abandoned_leases(store: Store, *, owner: str, now: str) -> int:
    """At worker start, holding the installation lock: leases of dead workers end now.

    The OS lock guarantees no other worker of this installation is alive, so
    their leases can return to ``pending`` immediately. Generations are kept;
    the next lease increments them, so a result from the old attempt stays
    fenced. Persisted proposals are kept and applied without a new model call.
    """
    count = 0
    with store.transaction() as txn:
        for (body,) in txn.execute("SELECT body FROM jobs WHERE state = 'leased' AND (lease_owner IS NULL OR lease_owner != ?)", (owner,)).fetchall():
            release(txn, _job(body), reason="lease_abandoned")
            count += 1
    return count


def mark_provider_unavailable(store: Store, *, limit: int = 200) -> int:
    """Pending model jobs show why they are not launching (no certified backend configured)."""
    marks = ",".join("?" for _ in MODEL_KINDS)
    count = 0
    with store.transaction() as txn:
        rows = txn.execute(f"SELECT body FROM jobs WHERE state = 'pending' AND kind IN ({marks}) LIMIT ?", (*sorted(MODEL_KINDS), limit)).fetchall()  # noqa: S608
        for (body,) in rows:
            job = _job(body)
            if job.last_error_code != PROVIDER_UNAVAILABLE:
                _save(txn, job.model_copy(update={"last_error_code": PROVIDER_UNAVAILABLE}))
                count += 1
    return count


# --------------------------------------------------------------------------
# Visible queue state


def queue_summary(view: Any, *, now: str) -> dict[str, Any]:
    """Counts by state/kind, oldest due backlog, and every visible waiting reason."""
    by_state: dict[str, int] = {}
    by_kind: dict[str, dict[str, int]] = {}
    for state, kind, n in view.execute("SELECT state, kind, COUNT(*) FROM jobs GROUP BY state, kind").fetchall():
        by_state[state] = by_state.get(state, 0) + n
        by_kind.setdefault(kind, {})[state] = n
    reasons: dict[str, int] = {}
    oldest_due: str | None = None
    for due_at, body in view.execute("SELECT due_at, body FROM jobs WHERE state IN ('pending', 'waiting_budget', 'leased', 'failed') ORDER BY due_at LIMIT 1000").fetchall():
        job = json.loads(body)
        if job["state"] != "failed" and due_at <= now and (oldest_due is None or due_at < oldest_due):
            oldest_due = due_at
        if job.get("last_error_code"):
            label = f"{job['state']}:{job['last_error_code']}"
            reasons[label] = reasons.get(label, 0) + 1
    backlog_age = None if oldest_due is None else (parse_utc(now) - parse_utc(oldest_due)).total_seconds()
    return {"by_state": by_state, "by_kind": by_kind, "waiting_reasons": reasons, "oldest_due_backlog_seconds": backlog_age}
