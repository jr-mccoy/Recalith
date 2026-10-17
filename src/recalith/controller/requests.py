"""Model request preparation and narrative scheduling (DATA_CONTRACTS §7, §11; SYSTEM_SPEC §6.2–§6.3).

:func:`prepare_model_request` builds the one bounded :class:`ModelRequest` a
model job sends, for every purpose the worker can launch:

* ``update_task`` (task narrative): the current task head (following a linked
  placeholder to its target), its recent bound events, its latest episodes and
  its pending boundary candidates with the binding revisions their events
  have now;
* ``build_episode`` (episode narrative): the episode, its source events and
  its task; or, for a job naming only a task, the task's open range;
* ``extract_claims``: the named events and episodes, the task and its pending
  boundary candidates, and a bounded slice of current claim heads;
* ``review_claims``: the candidates of the job's persisted, immutable
  :class:`ReviewBatch` (created here before launch, reused while unchanged)
  and only their batch evidence, with review rationale fields removed;
* ``revalidate``: the claims and the events their links cite.

Every collection is a selected slice from *this* installation's store (a
reference this store does not hold is refused, never looked up elsewhere),
source text is quoted data inside the request (see :mod:`recalith.prompts`),
and the request carries the ``ReadSet`` of the records it consulted, so a
proposal prepared against an older revision is re-evaluated, never
overwritten (decision 0007). The serialized request never exceeds 96 KiB:
the bulkiest successful-output events first (user requests and failed or
interrupted results last), then older episodes and claims, are dropped until
it fits, and :func:`request_estimate` is the exact local input estimate the lane
reserves before launch. Evidence-expansion rounds add only records this
installation holds.

Consumers owned by later tasks stay as Task 5/6 left them: extraction
proposals apply as weak candidates (semantic admission is Task 9), review
assessments change nothing yet (``review_admission_unavailable``, Task 9),
and revalidation applies only its structural checks (Task 10).

**Narrative scheduling** (decision 0009). Typed reduction schedules narrative
at its checkpoints, in the same transaction that creates the episode: one
``build_episode`` job per new *settled* episode with at least one step (band
3, completed-attempt episode work) and one ``update_task`` job per
checkpointed task (band 4), both from the ordinary pool and coalesced (at most
one pending narrative job per task and per episode). Task narrative waits
for a quiet task: it is due :data:`QUIET_SECONDS` after the checkpoint, and a
task with activity inside that window defers it (``task_active``) without a
call or reservation. A job whose task was linked, completed or abandoned, or
whose episode was archived, is cancelled without a call (``narrative_obsolete``).
"""

from __future__ import annotations

import datetime as _dt
import json
from functools import lru_cache
from typing import Any, Callable, Iterable, Sequence

from recalith.contracts.common import EvidenceLink, InstallationContext, ReadSet, RecordRef, canonical_json, derived_id, digest_of, format_utc, new_id, parse_utc, utc_now
from recalith.contracts.config import MODEL_INPUT_CAP, PURPOSE_OUTPUT_ALLOWANCE, STDERR_CAP, WIRE_STDOUT_CAP, body_cap_for, estimate_tokens
from recalith.contracts.events import EventEnvelope
from recalith.contracts.jobs import Job
from recalith.contracts.memory import ClaimRevision, Episode, ReviewBatch, ReviewEvidence, TaskState
from recalith.contracts.operations import PAYLOAD_MODELS, PURPOSE_KINDS, BoundaryContext, ModelRequest, ModelResponse, RequestEvidencePayload, RequestLimits
from recalith.controller import jobs
from recalith import prompts
from recalith.fast import failpoints
from recalith.storage import records, repository
from recalith.working import bindings, segment, tasks

QUIET_SECONDS = 300
MAX_EVENTS = 64
MAX_EPISODES = 3
MAX_CLAIMS = 16
MAX_BOUNDARIES = 8
EXPANSION_EVENTS = 16
ACTIVE_CLAIM_STATES = ("candidate", "active", "disputed")


class PrepareFailed(Exception):
    """No request can be prepared for this attempt; the lane fails it with ``code`` (nothing reserved).

    ``final`` failures (an input over the cap, a prompt version this build does
    not ship, an input this installation does not hold) are not retried; the
    others use the normal backoff (``task_active`` defers a busy task's
    narrative without counting an attempt).
    """

    def __init__(self, code: str, message: str = "", *, final: bool = False) -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code[:64]
        self.final = final


class NothingToPrepare(PrepareFailed):
    """The job's inputs no longer warrant a model call; the lane cancels it with ``reason``.

    No reservation is made and no model is called.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason, final=True)
        self.reason = reason[:64]


# --------------------------------------------------------------------------
# Output schemas (permitted kinds only; controller-only kinds never appear)


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in ("title", "description")}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


@lru_cache(maxsize=None)
def _output_schema_json(purpose: str) -> str:
    from recalith.contracts.common import EvidenceLink as _Link

    defs: dict[str, Any] = {}

    def lift(schema: dict[str, Any]) -> dict[str, Any]:
        defs.update(schema.pop("$defs", {}))
        return schema

    link = lift(_Link.model_json_schema())
    ref = lift(RecordRef.model_json_schema())
    defs.setdefault("EvidenceLink", link)
    defs.setdefault("RecordRef", ref)
    local = {"type": "string", "pattern": r"^[a-z0-9][a-z0-9_\-]{0,63}$"}
    variants = []
    for kind in sorted(PURPOSE_KINDS[purpose]):
        payload = lift(PAYLOAD_MODELS[kind].model_json_schema())
        variants.append({
            "type": "object",
            "additionalProperties": False,
            "required": ["local_ref", "kind", "payload", "reason"],
            "properties": {
                "local_ref": local, "kind": {"const": kind}, "depends_on": {"type": "array", "items": local},
                "target": {"anyOf": [{"$ref": "#/$defs/RecordRef"}, {"type": "null"}]}, "payload": payload,
                "evidence": {"type": "array", "items": {"$ref": "#/$defs/EvidenceLink"}}, "reason": {"type": "string", "maxLength": 1024},
            },
        })
    schema = {
        "type": "object", "additionalProperties": False, "required": ["operations"],
        "properties": {"operations": {"type": "array", "maxItems": 256, "items": {"oneOf": variants}}, "no_op_reason": {"anyOf": [{"type": "string", "maxLength": 1024}, {"type": "null"}]}},
        "$defs": defs,
    }
    return json.dumps(_strip(schema), sort_keys=True)


def output_schema(purpose: str) -> dict[str, Any]:
    """The provider schema for ``purpose``: exactly its permitted operation kinds and payload keys."""
    return json.loads(_output_schema_json(purpose))


def request_estimate(request: ModelRequest) -> int:
    """The exact local input estimate reserved before launch: ``ceil(UTF-8 bytes / 3)``."""
    return estimate_tokens(len(canonical_json(request.model_dump(mode="json"))))


# --------------------------------------------------------------------------
# Selection helpers (this store only)


def _events(view: Any, ctx: InstallationContext, event_ids: Iterable[str]) -> list[tuple[int, EventEnvelope]]:
    out = []
    seen = set()
    for event_id in event_ids:
        if event_id in seen:
            continue
        seen.add(event_id)
        row = view.execute("SELECT envelope, payload, payload_state, commit_sequence, workspace_id FROM events WHERE event_id = ?", (event_id,)).fetchone()
        if row is None or row[4] != ctx.workspace_id:
            continue
        envelope = repository.event_from_row(row[:3])
        if envelope is not None:  # an expired or forgotten payload is not resent
            out.append((row[3], envelope))
    return out


def _require(view: Any, ref: RecordRef) -> None:
    if ref.kind in ("task", "episode", "claim"):
        if records.head(view, ref.kind, ref.id) is None:
            raise PrepareFailed("request_input_missing", final=True, message="a job input is not a record of this installation")
    elif ref.kind == "event":
        if view.execute("SELECT 1 FROM events WHERE event_id = ?", (ref.id,)).fetchone() is None:
            raise PrepareFailed("request_input_missing", final=True, message="a job input is not an event of this installation")
    else:
        raise PrepareFailed("request_input_missing", final=True, message="unsupported job input kind")


def _head(view: Any, kind: str, record_id: str):
    current = records.head(view, kind, record_id)
    if current is None:
        return None
    return records.load(view, kind, record_id, current[0])


def _task(view: Any, task_id: str | None) -> TaskState | None:
    resolved = tasks.resolve_task(view, task_id) if task_id else None
    return _head(view, "task", resolved) if resolved else None


def _task_events(view: Any, task_id: str, limit: int) -> list[str]:
    rows = view.execute("SELECT event_id FROM task_binding_heads WHERE task_id = ? ORDER BY commit_sequence DESC LIMIT ?", (task_id, limit)).fetchall()
    return [r[0] for r in rows]


def _task_episodes(view: Any, task_id: str, limit: int) -> list[Episode]:
    rows = view.execute("SELECT episode_id FROM episode_heads WHERE task_id = ? AND state != 'archived' ORDER BY rowid DESC LIMIT ?", (task_id, limit)).fetchall()
    return [e for e in (_head(view, "episode", r[0]) for r in rows) if e is not None]


def _boundaries(view: Any, task_id: str) -> list[BoundaryContext]:
    out = []
    for candidate in segment.pending_candidates(view, task_id)[:MAX_BOUNDARIES]:
        out.append(BoundaryContext(candidate=candidate, binding_revisions=bindings.expected_revisions(view, candidate.proposed_event_ids)))
    return out


def _link_events(links: Iterable[EvidenceLink]) -> list[str]:
    return [link.ref.id for link in links if link.ref.kind == "event"]


def _claim_for_request(claim: ClaimRevision) -> ClaimRevision:
    """Rationale-free: earlier review objections and provider provenance are not resent."""
    return claim.model_copy(update={"review_assessment": None, "model_provenance": None})


def _current_claims(view: Any, limit: int) -> list[ClaimRevision]:
    marks = ",".join("?" for _ in ACTIVE_CLAIM_STATES)
    rows = view.execute(f"SELECT claim_id FROM claim_heads WHERE status IN ({marks}) ORDER BY rowid DESC LIMIT ?", (*ACTIVE_CLAIM_STATES, limit)).fetchall()  # noqa: S608
    return [c for c in (_head(view, "claim", r[0]) for r in rows) if c is not None]


class Selection:
    """What one request consults, in priority order (earlier items are kept when trimming)."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.episodes: list[Episode] = []
        self.claims: list[ClaimRevision] = []
        self.task: TaskState | None = None
        self.boundaries: list[BoundaryContext] = []
        self.batch: ReviewBatch | None = None
        self.extra_refs: list[RecordRef] = []

    def add_events(self, ids: Iterable[str]) -> None:
        for event_id in ids:
            if event_id not in self.events:
                self.events.append(event_id)


# --------------------------------------------------------------------------
# Per-purpose selection


def _select_update_task(view: Any, job: Job, now: str) -> Selection:
    task_refs = [r for r in job.input_refs if r.kind == "task"]
    if not task_refs:
        raise PrepareFailed("request_input_missing", final=True, message="a task narrative job names its task")
    sel = Selection()
    task = _task(view, task_refs[0].id)
    if task is None or task.status not in ("active", "paused"):
        raise NothingToPrepare("narrative_obsolete")
    if parse_utc(task.last_activity_at) > parse_utc(now) - _dt.timedelta(seconds=QUIET_SECONDS):
        raise PrepareFailed("task_active", "task narrative waits for a quiet task")
    sel.task = task
    sel.boundaries = _boundaries(view, task.task_id)
    for boundary in sel.boundaries:
        sel.add_events(boundary.candidate.proposed_event_ids[:8])
    sel.add_events(_task_events(view, task.task_id, MAX_EVENTS))
    sel.episodes = _task_episodes(view, task.task_id, MAX_EPISODES)
    return sel


def _select_build_episode(view: Any, job: Job, now: str) -> Selection:
    sel = Selection()
    episode_refs = [r for r in job.input_refs if r.kind == "episode"]
    if episode_refs:
        current = records.head(view, "episode", episode_refs[0].id)
        episode = _head(view, "episode", episode_refs[0].id)
        if current is None or current[1] == "archived" or episode is None:
            raise NothingToPrepare("narrative_obsolete")
        sel.episodes = [episode] + [e for e in (_head(view, "episode", rid) for rid in episode.related_episode_ids[:2]) if e is not None]
        sel.add_events(episode.source_event_ids)
        sel.task = _task(view, episode.task_id)
        return sel
    task_refs = [r for r in job.input_refs if r.kind == "task"]
    if not task_refs:
        raise PrepareFailed("request_input_missing", final=True, message="an episode job names its episode or task")
    from recalith.working import reducer  # deferred: the reducer schedules narrative through this module

    sel.task = _task(view, task_refs[0].id)
    if sel.task is None:
        raise NothingToPrepare("narrative_obsolete")
    book = bindings.task_book(view, sel.task.task_id)
    sel.add_events(e.event_id for e in reducer.open_range(view, sel.task.task_id, book["open_from"] or 0))
    return sel


def _select_extract(view: Any, job: Job, now: str) -> Selection:
    sel = Selection()
    task_id = None
    for ref in job.input_refs:
        if ref.kind == "event":
            sel.add_events([ref.id])
        elif ref.kind == "episode":
            episode = _head(view, "episode", ref.id)
            if episode is not None:
                sel.episodes.append(episode)
                sel.add_events(episode.source_event_ids)
                task_id = task_id or episode.task_id
        elif ref.kind == "task":
            task_id = ref.id
    if task_id is None and sel.events:
        head = bindings.binding_head(view, sel.events[0])
        task_id = head["task_id"] if head else None
    sel.task = _task(view, task_id)
    if sel.task is not None:
        sel.boundaries = _boundaries(view, sel.task.task_id)
    sel.claims = [_claim_for_request(c) for c in _current_claims(view, MAX_CLAIMS)]
    return sel


def _batch_snapshot(view: Any, job: Job, candidates: list[ClaimRevision], read_set: ReadSet) -> ReviewBatch:
    index: list[ReviewEvidence] = []
    seen: set[str] = set()
    for claim in candidates:
        for link in [*claim.supports, *claim.contradicts]:
            evidence_id = derived_id("evd", link.model_dump(mode="json"))
            if evidence_id not in seen:
                seen.add(evidence_id)
                index.append(ReviewEvidence(evidence_id=evidence_id, link=link))
    version = job.prompt_version or prompts.CURRENT["review_claims"]
    return ReviewBatch(
        batch_id=new_id("batch"),
        origin_job_id=None,
        review_job_id=job.job_id,
        candidate_refs=[records.ref_of(c) for c in candidates],
        candidate_digests={c.claim_id: digest_of(c.model_dump(mode="json")) for c in candidates},
        evidence_digest=digest_of([e.model_dump(mode="json") for e in index]),
        prompt_digest=prompts.prompt_digest(version),
        evidence_index=index,
        read_set=read_set,
    )


def persisted_batch(view: Any, review_job_id: str) -> ReviewBatch | None:
    row = view.execute("SELECT body FROM review_batches WHERE review_job_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1", (review_job_id,)).fetchone()
    return None if row is None else ReviewBatch.model_validate_json(row[0])


def _same_batch(a: ReviewBatch, b: ReviewBatch) -> bool:
    keys = ("candidate_refs", "candidate_digests", "evidence_digest", "prompt_digest", "evidence_index")
    return all(getattr(a, k) == getattr(b, k) for k in keys)


def _select_review(view: Any, job: Job, now: str, ctx: InstallationContext) -> tuple[Selection, ReviewBatch | None]:
    refs = [r for r in job.input_refs if r.kind == "claim"]
    if not refs:
        raise PrepareFailed("request_input_missing", final=True, message="a review job names its candidate claims")
    candidates = [c for c in (_head(view, "claim", r.id) for r in refs[:8]) if c is not None]
    if not candidates:
        raise NothingToPrepare("review_candidates_gone")
    sel = Selection()
    sel.claims = [_claim_for_request(c) for c in candidates]
    read_set = ReadSet(entity_revisions=[records.ref_of(c) for c in candidates], workspace_id=ctx.workspace_id, policy_revision=view_meta(view)[0], tombstone_epoch=view_meta(view)[1])
    fresh = _batch_snapshot(view, job, candidates, read_set)
    existing = persisted_batch(view, job.job_id)
    if existing is not None and _same_batch(existing, fresh):
        sel.batch = existing
        new = None
    else:
        sel.batch = new = fresh
    for evidence in sel.batch.evidence_index:
        if evidence.link.ref.kind == "event":
            sel.add_events([evidence.link.ref.id])
    return sel, new


def _select_revalidate(view: Any, job: Job, now: str) -> Selection:
    refs = [r for r in job.input_refs if r.kind == "claim"]
    if not refs:
        raise PrepareFailed("request_input_missing", final=True, message="a revalidation job names its claims")
    sel = Selection()
    claims = [c for c in (_head(view, "claim", r.id) for r in refs[:MAX_CLAIMS]) if c is not None]
    if not claims:
        raise NothingToPrepare("revalidation_targets_gone")
    sel.claims = [_claim_for_request(c) for c in claims]
    for claim in claims:
        sel.add_events(_link_events([*claim.supports, *claim.contradicts]))
    for ref in job.input_refs:
        if ref.kind == "event":
            sel.add_events([ref.id])
    return sel


def view_meta(view: Any) -> tuple[int, int]:
    row = view.execute("SELECT policy_revision, tombstone_epoch FROM installation_meta").fetchone()
    return int(row[0]), int(row[1])


# --------------------------------------------------------------------------
# Evidence-expansion rounds


def _expand(view: Any, ctx: InstallationContext, sel: Selection, rounds: Sequence[ModelResponse]) -> None:
    """Resolve ``request_evidence`` operations against records this installation holds (nothing else)."""
    for response in rounds:
        for op in response.operations:
            if op.kind != "request_evidence":
                continue
            typed = op.typed_payload()
            assert isinstance(typed, RequestEvidencePayload)
            ref = typed.ref
            if ref is None:
                continue  # file excerpts and dependency diffs have no registered resolver in this build
            if ref.kind == "event" and typed.request_kind in ("record", "event_range"):
                row = view.execute("SELECT commit_sequence, session_id FROM events WHERE event_id = ? AND workspace_id = ?", (ref.id, ctx.workspace_id)).fetchone()
                if row is None:
                    continue
                if typed.request_kind == "record":
                    sel.add_events([ref.id])
                else:
                    more = view.execute("SELECT event_id FROM events WHERE session_id = ? AND commit_sequence >= ? ORDER BY commit_sequence LIMIT ?", (row[1], row[0], EXPANSION_EVENTS)).fetchall()
                    sel.add_events(r[0] for r in more)
            elif ref.kind == "episode" and typed.request_kind == "record":
                episode = _head(view, "episode", ref.id)
                if episode is not None and all(e.episode_id != episode.episode_id for e in sel.episodes):
                    sel.episodes.append(episode)
            elif ref.kind == "claim" and typed.request_kind == "record":
                claim = _head(view, "claim", ref.id)
                if claim is not None and all(c.claim_id != claim.claim_id for c in sel.claims):
                    sel.claims.append(_claim_for_request(claim))


# --------------------------------------------------------------------------
# Assembly under the input cap


def _limits(purpose: str, timeout_seconds: int) -> RequestLimits:
    return RequestLimits(max_input_bytes=MODEL_INPUT_CAP, reserved_output_estimate=PURPOSE_OUTPUT_ALLOWANCE[purpose], max_body_bytes=body_cap_for(purpose), max_wire_stdout_bytes=WIRE_STDOUT_CAP, max_stderr_bytes=STDERR_CAP, timeout_seconds=timeout_seconds)


def _assemble(view: Any, ctx: InstallationContext, job: Job, sel: Selection, *, instruction: str, timeout_seconds: int) -> ModelRequest:
    policy_revision, tombstone_epoch = view_meta(view)
    loaded = _events(view, ctx, sel.events)
    order = {event_id: i for i, event_id in enumerate(sel.events)}
    loaded.sort(key=lambda pair: order[pair[1].event_id])  # priority order for trimming
    events = list(loaded)
    episodes, claims = list(sel.episodes), list(sel.claims)
    schema = output_schema(job.kind)
    limits = _limits(job.kind, timeout_seconds)
    while True:
        consulted = ([records.ref_of(sel.task)] if sel.task is not None else []) + [records.ref_of(e) for e in episodes] + [records.ref_of(c) for c in claims]
        read_set = ReadSet(entity_revisions=consulted, workspace_id=ctx.workspace_id, policy_revision=policy_revision, tombstone_epoch=tombstone_epoch)
        if sel.batch is not None:
            read_set = read_set.model_copy(update={"entity_revisions": list(dict.fromkeys([*consulted, *sel.batch.read_set.entity_revisions]))})
        shown = sorted(events, key=lambda pair: pair[0])
        allowed = consulted + [RecordRef(kind="event", id=e.event_id, revision=1) for _seq, e in shown]
        data = {
            "request_schema": 1, "job_id": job.job_id, "purpose": job.kind, "prompt_version": job.prompt_version, "instruction_text": instruction,
            "events": [e.model_dump(mode="json") for _seq, e in shown], "episodes": [e.model_dump(mode="json") for e in episodes],
            "claims": [c.model_dump(mode="json") for c in claims], "task_state": sel.task.model_dump(mode="json") if sel.task is not None else None,
            "boundaries": [b.model_dump(mode="json") for b in sel.boundaries], "allowed_evidence_refs": [r.model_dump(mode="json") for r in allowed],
            "read_set": read_set.model_dump(mode="json"), "output_schema": schema, "review_batch": sel.batch.model_dump(mode="json") if sel.batch is not None else None,
            "limits": limits.model_dump(mode="json"),
        }
        if len(canonical_json(data)) <= MODEL_INPUT_CAP:
            return ModelRequest.model_validate(data)
        if len(events) > 1:
            # Bulky successful output goes first; user requests and failed or interrupted results last.
            sizes = [len(canonical_json(e.model_dump(mode="json"))) for _seq, e in events]
            events.pop(max(range(len(events)), key=lambda i: (not _keep(events[i][1]), sizes[i], i)))
        elif len(episodes) > 1:
            episodes.pop()
        elif len(claims) > (len(sel.batch.candidate_refs) if sel.batch is not None else 1):
            claims.pop()
        elif events:
            events.pop()
        else:
            raise PrepareFailed("model_input_oversized", "the smallest selection for this job exceeds the 96 KiB input cap", final=True)


def _keep(event: EventEnvelope) -> bool:
    """Events a request drops last: explicit user requests and results that did not succeed."""
    if event.kind == "user_message":
        return True
    return event.kind == "tool_finished" and event.payload.get("outcome") not in ("success", None)


def prepare_model_request(ctx: InstallationContext, job: Job, *, store: Any = None, rounds: Sequence[ModelResponse] = (), now: str | None = None, timeout_seconds: int = 120) -> ModelRequest:
    """The bounded request for ``job`` from this installation's store (DATA_CONTRACTS §11).

    Raises :class:`PrepareFailed` (the lane fails the attempt with its code;
    nothing was reserved) and :class:`NothingToPrepare` (the lane cancels the
    job without a call).
    """
    from recalith.storage.db import open_store

    if job.kind not in PURPOSE_KINDS:
        raise PrepareFailed("invalid_job_kind", "only model jobs have requests", final=True)
    now = now or utc_now()
    try:
        instruction = prompts.instruction(job.prompt_version or "", job.kind)
    except KeyError:
        raise PrepareFailed("prompt_version_unavailable", "this build does not ship the job's pinned prompt version", final=True) from None
    own = store is None
    store = store or open_store(ctx)
    try:
        new_batch = None
        with store.read() as view:
            for ref in job.input_refs:
                _require(view, ref)
            if job.kind == "update_task":
                sel = _select_update_task(view, job, now)
            elif job.kind == "build_episode":
                sel = _select_build_episode(view, job, now)
            elif job.kind == "extract_claims":
                sel = _select_extract(view, job, now)
            elif job.kind == "review_claims":
                sel, new_batch = _select_review(view, job, now, ctx)
            else:
                sel = _select_revalidate(view, job, now)
            _expand(view, ctx, sel, rounds)
            request = _assemble(view, ctx, job, sel, instruction=instruction, timeout_seconds=timeout_seconds)
        if new_batch is not None:
            persist_batch(store, job, new_batch, now=now)  # the immutable snapshot exists before any launch
        return request
    finally:
        if own:
            store.close()


def persist_batch(store: Any, job: Job, batch: ReviewBatch, *, now: str) -> None:
    """Persist a review batch snapshot under the job's lease fence (plain transaction when unleased)."""
    context = jobs.fenced(store, job, now=now) if job.state == "leased" else store.transaction()
    with context as txn:
        txn.execute("INSERT INTO review_batches (batch_id, origin_job_id, review_job_id, body, created_at) VALUES (?, ?, ?, ?, ?)", (batch.batch_id, batch.origin_job_id, batch.review_job_id, batch.model_dump_json(), now))
        txn.mutated(serving_relevant=False)
    failpoints.hit(failpoints.REQUEST_AFTER_BATCH)


def runtime_preparer(ctx: InstallationContext, *, now: Callable[[], str] | None = None, timeout_seconds: int = 120) -> Callable[[Any, Job, list[ModelResponse]], ModelRequest]:
    """The worker's ``ModelRuntime.prepare``: :func:`prepare_model_request` on the lane's own store."""

    def prepare(store: Any, job: Job, rounds: list[ModelResponse]) -> ModelRequest:
        return prepare_model_request(ctx, job, store=store, rounds=rounds, now=(now or utc_now)(), timeout_seconds=timeout_seconds)

    return prepare


# --------------------------------------------------------------------------
# Narrative scheduling (decision 0009)


def schedule_narrative(txn: Any, *, task_id: str, episode_ref: RecordRef | None, now: str) -> list[str]:
    """Enqueue checkpoint narrative in the caller's (reduction) transaction; returns new job IDs."""
    created: list[str] = []
    if episode_ref is not None:
        current = records.head(txn, "episode", episode_ref.id)
        body = records.body(txn, "episode", episode_ref.id, episode_ref.revision) if current else None
        if body is not None and body.get("state") == "settled" and body.get("steps"):
            job_id, new = jobs.enqueue(txn, kind="build_episode", input_refs=[episode_ref], now=now, prompt_version=prompts.CURRENT["build_episode"], coalesce=True)
            if new:
                created.append(job_id)
    head = records.head(txn, "task", task_id)
    if head is not None and head[1] in ("active", "paused"):
        due = format_utc(parse_utc(now) + _dt.timedelta(seconds=QUIET_SECONDS))
        job_id, new = jobs.enqueue(txn, kind="update_task", input_refs=[tasks.task_ref(task_id, head[0])], now=now, due_at=due, prompt_version=prompts.CURRENT["update_task"], coalesce=True)
        if new:
            created.append(job_id)
    return created


__all__ = ["prepare_model_request", "runtime_preparer", "request_estimate", "output_schema", "schedule_narrative", "persist_batch", "persisted_batch", "PrepareFailed", "NothingToPrepare", "QUIET_SECONDS"]
