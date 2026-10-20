"""The public project-memory service (DATA_CONTRACTS §11–§12; SYSTEM_SPEC §7.1.2, §7.3, §13.1, §14).

Every function takes a resolved :class:`InstallationContext` (no global
lookup) and returns a strict DTO or a JSON-ready mapping. Nothing here prints,
reads a terminal, inspects markers, or imports a host entry point: transports
(``recalith.cli`` now; MCP later) assign the actor after their own guard and
render the result. Business policy lives in the domain modules this layer
calls; the service only composes them.

**Guarded operator writes.** :func:`declare` and :func:`correct` accept only
an operator actor (``channel=cli``, assigned by the CLI guard after it passed;
a CLI channel alone is never operator authority). Each records an exact,
scrubbed operator event (``operator_declaration`` / ``operator_correction``)
on the user channel and applies typed operations through the ordinary
application path (``controller.apply.apply_in_transaction``) in **one**
transaction: event ingestion (root class, revision hooks), admission, the
candidate, the review job (``controller.review.schedule``) and, for a
correction, the immediate invalidation with its guidance-epoch advance. No
model is called and nothing waits for a provider; a declaration or a
correction's replacement stays a weak candidate until its own adversarial
review is admitted (no declaration-review bypass, decision 0011). A
submission's identity is derived from its exact content, so retrying the
same command after a crash returns the original result instead of a second
effect (decision 0014).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TypeVar

from pydantic import ValidationError

from recalith.capture import pipeline
from recalith.capture.normalize import RawEvent, normalize_event
from recalith.contracts.common import Actor, InstallationContext, ReadSet, RecordRef, Scope, canonical_json, derived_id, digest_of, new_id, utc_now
from recalith.contracts.config import ProjectConfig
from recalith.contracts.context import ContextItem, ContextPacket, ContextQuery
from recalith.contracts.events import CaptureReceipt, EventEnvelope
from recalith.contracts.operations import ApplyResult, ProposedOperation, UndoPreview
from recalith.contracts.transfers import ArtifactManifest
from recalith.controller import apply, jobs
from recalith.core import identity
from recalith.errors import RecalithError
from recalith.fast import failpoints, process_env, redact
from recalith.storage import records
from recalith.storage.db import Store, open_store

T = TypeVar("T")

CLI_ADAPTER = "recalith_cli"
OPERATOR_HOST_SESSION = "operator"
GUARD_HOST_SESSION = "guard"
# Read-only inspection carries no authority at all (DATA_CONTRACTS §1.1).
READER = Actor(kind="host_agent", id="cli-reader", channel="cli")
# ``observe`` is an agent assertion on agent transports, never an administrative declaration.
OBSERVER = Actor(kind="host_agent", id="cli-observe", channel="cli")
# The guard's content-free refusal audit is adapter telemetry (memory channel, derived).
AUDITOR = Actor(kind="adapter", id="cli-guard", channel="cli")
DECLARATION_KINDS = ("decision", "preference")
MAX_STATEMENT_CHARS = 4096
PAGE_DEFAULT = 50
PAGE_MAX = 200
SEARCH_HISTORY_SCAN = 2000
SNIPPET_CHARS = 240
BUSY_RETRY_SECONDS = 5.0
WORKER_STOP_SECONDS = 15.0
ADMITTED = frozenset({"apply", "candidate_only"})
LIST_KINDS = {"tasks": "task", "episodes": "episode", "claims": "claim"}
STATUSES = {
    "task": ("active", "paused", "completed", "abandoned", "linked"),
    "episode": ("open", "settled", "archived"),
    "claim": ("candidate", "active", "disputed", "superseded", "invalidated", "archived", "quarantined", "forgotten"),
}


def unavailable(feature: str, owner: str) -> RecalithError:
    """An explicit result for a command whose owning task is not complete in this build."""
    return RecalithError("capability_unavailable", f"{feature} is not available in this build (owned by {owner})")


def resolve(root: Path, *, actor: Actor) -> InstallationContext:
    return identity.resolve_installation(Path(root), actor=actor)


def require_operator(ctx: InstallationContext, action: str) -> None:
    if ctx.actor.kind != "operator" or ctx.actor.channel != "cli":
        raise RecalithError("policy_refused", f"{action} is an operator action of the guarded CLI transport")


def _retrying(fn: Callable[[], T]) -> T:
    """A short write retried while the worker holds the write lock (bounded; nothing applied by a failed BEGIN)."""
    deadline = time.monotonic() + BUSY_RETRY_SECONDS
    while True:
        try:
            return fn()
        except RecalithError as exc:
            if exc.code != "storage_failure" or "busy" not in exc.message or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


# --------------------------------------------------------------------------
# Operator events and guarded submissions


def cli_session(ctx: InstallationContext, host_session: str) -> str:
    return derived_id("sess", [ctx.installation_id, CLI_ADAPTER, host_session])


def _exact_statement(statement: str) -> str:
    """The exact operator text, refused rather than altered when it cannot be recorded as given."""
    if not isinstance(statement, str) or not statement.strip():
        raise RecalithError("invalid_schema", "the statement is empty")
    if len(statement) > MAX_STATEMENT_CHARS:
        raise RecalithError("invalid_schema", f"the statement exceeds {MAX_STATEMENT_CHARS} characters")
    if any(0xD800 <= ord(c) <= 0xDFFF for c in statement) or "\x00" in statement:
        raise RecalithError("invalid_schema", "the statement is not valid text")
    if redact.contains_secret(statement):
        raise RecalithError("invalid_schema", "the statement contains a credential-shaped value; nothing was recorded")
    return statement


def operator_event(ctx: InstallationContext, kind: str, payload: dict[str, Any], *, key: str) -> EventEnvelope:
    """An operator event of the guarded transport: user channel, explicit user authority, its own root.

    The hook path refuses these kinds (``fast.normalize``); only this
    service builds them, after the caller passed the CLI guard.
    """
    require_operator(ctx, "recording an operator event")
    session_id = cli_session(ctx, OPERATOR_HOST_SESSION)
    source_key = f"{kind}:{key}"
    event_id = derived_id("evt", [ctx.installation_id, CLI_ADAPTER, source_key])
    digest = digest_of(payload)
    data = {
        "schema_version": 1,
        "event_id": event_id,
        "project_id": ctx.project_id,
        "installation_id": ctx.installation_id,
        "workspace_id": ctx.workspace_id,
        "adapter_id": CLI_ADAPTER,
        "adapter_version": ctx.engine_version,
        "source_event_key": source_key,
        "session_id": session_id,
        "host_session_id": OPERATOR_HOST_SESSION,
        "task_id": None,
        "source_sequence": None,
        "occurred_at": None,
        "recorded_at": utc_now(),
        "kind": kind,
        "channel": "user",
        "origin": {"adapter_id": CLI_ADAPTER, "source_event_key": source_key, "host_session_id": OPERATOR_HOST_SESSION, "origin_kind": "operator_cli", "source_digest": digest, "locator": None},
        "authority": "explicit_user",
        "derived_from": [],
        "root_event_ids": [event_id],
        "payload": payload,
        "payload_digest": digest,
        "coverage": {"truncated": False, "redacted": False, "missing_context": False, "parser_complete": True},
        "extensions": {},
    }
    try:
        return EventEnvelope.model_validate(data)
    except ValidationError:
        raise RecalithError("invalid_schema", "the operator event is invalid") from None


def _statement_link(event_id: str, statement: str, relation: str) -> dict[str, Any]:
    locator = {"field": "statement", "start": 0, "end": len(statement), "text_digest": hashlib.sha256(statement.encode("utf-8")).hexdigest()}
    return {"ref": {"kind": "event", "id": event_id, "revision": 1}, "relation": relation, "root_event_ids": [event_id], "locator": locator, "mapping": None}


@dataclass
class Submission:
    """A guarded write's result plus what the transport reports alongside it."""

    result: ApplyResult
    event_id: str
    submission_id: str
    review_job_ids: list[str] = field(default_factory=list)
    duplicate: bool = False
    guidance_epoch: int = 0

    def report(self) -> dict[str, Any]:
        return {
            "result": self.result.model_dump(mode="json"), "event_id": self.event_id, "submission_id": self.submission_id,
            "review_job_ids": self.review_job_ids, "duplicate": self.duplicate, "guidance_epoch": self.guidance_epoch,
        }


def _submit(
    ctx: InstallationContext,
    env: EventEnvelope,
    build: Callable[[Any, bool], tuple[list[ProposedOperation], list[RecordRef]]],
    *,
    review_origin: str | None,
    store: Store | None,
    now: str | None,
) -> Submission:
    submission_id = derived_id("op", ["operator_submission", env.event_id])

    def run(store_: Store) -> Submission:
        when = now or utc_now()
        with store_.transaction() as txn:
            counts, _job = pipeline.ingest_in_transaction(txn, ctx, [env], now=when)
            if counts["conflict"]:
                raise RecalithError("event_identity_conflict", "an operator event with this identity holds other content")
            duplicate = counts["duplicate"] == 1
            failpoints.hit(failpoints.SERVICE_AFTER_EVENT)
            operations, consulted = build(txn, duplicate)
            read_set = ReadSet(entity_revisions=consulted, workspace_id=ctx.workspace_id, policy_revision=txn.meta.policy_revision, tombstone_epoch=txn.meta.tombstone_epoch)
            result = apply.apply_in_transaction(txn, ctx, operations, read_set=read_set, submission_id=submission_id, now=when, kind=apply.SERVICE_KIND, review_origin=review_origin)
            refused = [d for d in result.decisions if d.outcome not in ADMITTED]
            if refused and not duplicate:
                # Nothing of a refused submission is kept, not even its event (one transaction).
                raise RecalithError("policy_refused", f"{refused[0].reason_code}: the submission was not applied")
            reviews = [r[0] for r in txn.execute("SELECT review_job_id FROM review_requests WHERE submission_id = ? ORDER BY partition_index", (submission_id,)).fetchall()]
            failpoints.hit(failpoints.SERVICE_BEFORE_COMMIT)
        failpoints.hit(failpoints.SERVICE_AFTER_COMMIT)
        return Submission(result=result, event_id=env.event_id, submission_id=submission_id, review_job_ids=reviews, duplicate=duplicate, guidance_epoch=store_.meta().guidance_epoch)

    own = store is None
    opened = store or open_store(ctx)
    try:
        return _retrying(lambda: run(opened))
    finally:
        if own:
            opened.close()


def declaration_key(kind: str, statement: str) -> dict[str, str]:
    """The code-derived proposition key of a typed declaration (decision 0014): its exact text, digested."""
    return {"subject": "declaration " + hashlib.sha256(statement.encode("utf-8")).hexdigest()[:24], "predicate": kind}


def submit_declaration(ctx: InstallationContext, kind: str, statement: str, scope: Scope, *, store: Store | None = None, now: str | None = None) -> Submission:
    """``declare`` with the identifiers the transport reports (see :func:`declare`)."""
    require_operator(ctx, "declare")
    if kind not in DECLARATION_KINDS:
        raise RecalithError("invalid_schema", "a typed declaration is a decision or a preference")
    statement = _exact_statement(statement)
    scope_json = scope.model_dump(mode="json")
    env = operator_event(ctx, "operator_declaration", {"statement": statement, "declaration_kind": kind, "scope": scope_json}, key=digest_of([kind, statement, scope_json]))

    def build(_txn: Any, _duplicate: bool) -> tuple[list[ProposedOperation], list[RecordRef]]:
        payload = {"kind": kind, "proposition": statement, "proposition_key": declaration_key(kind, statement), "scope": scope_json, "conditions": [], "basis": "user_declared", "dependencies": []}
        op = ProposedOperation.model_validate({"local_ref": "declaration", "kind": "propose_claim", "payload": payload, "evidence": [_statement_link(env.event_id, statement, "supports")], "reason": "operator typed declaration"})
        return [op], []

    return _submit(ctx, env, build, review_origin=None, store=store, now=now)


def declare(ctx: InstallationContext, kind: str, statement: str, scope: Scope, *, store: Store | None = None, now: str | None = None) -> ApplyResult:
    """Record an operator's exact decision/preference as a weak candidate with its review queued (DATA_CONTRACTS §11).

    Operator actor only; kind ``decision|preference``. The declaration is
    never admitted here: the candidate becomes active guidance only through
    its own supported adversarial review (same Task 9 path as an extracted
    declaration, at the highest review priority). An exhausted budget pauses
    that review; it is never bypassed.
    """
    return submit_declaration(ctx, kind, statement, scope, store=store, now=now).result


def _replacement(target: dict[str, Any], statement: str, event_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The replacement candidate for a corrected claim, following the target's type and evidence policy.

    A decision/preference is replaced by a user-declared claim of the same
    kind; anything else is replaced by an *inferred* claim of the same kind
    (never relabeled observed): a failure lesson or procedure keeps the
    target's body and its cited support, plus the operator's statement.
    """
    kind = target["kind"]
    link = _statement_link(event_id, statement, "supports")
    key = target.get("proposition_key") or {"subject": "correction " + hashlib.sha256(statement.encode("utf-8")).hexdigest()[:24], "predicate": kind}
    payload: dict[str, Any] = {
        "kind": kind, "proposition": statement, "proposition_key": key, "scope": target.get("scope") or {}, "conditions": target.get("conditions") or [],
        "basis": "user_declared" if kind in DECLARATION_KINDS else "inferred", "dependencies": [],
    }
    evidence = [link]
    if kind in ("failure_lesson", "procedure"):
        evidence = [*[item for item in target.get("supports") or [] if item.get("ref", {}).get("kind") == "event"], link]
        payload["dependencies"] = [dict(d, fingerprint=None) for d in target.get("dependencies") or [] if d.get("kind") != "claim"]
    if kind == "failure_lesson" and target.get("failure"):
        failure = dict(target["failure"])
        failure.update({"action_family_digest": None, "last_supporting_failure_event_id": None, "retry_conditions": []})
        payload["failure"] = failure
    if kind == "procedure" and target.get("procedure"):
        payload["procedure"] = target["procedure"]
    return payload, evidence


def submit_correction(ctx: InstallationContext, claim_id: str, *, expected_revision: int, statement: str, store: Store | None = None, now: str | None = None) -> Submission:
    """``correct`` with the identifiers the transport reports (see :func:`correct`)."""
    require_operator(ctx, "correct")
    statement = _exact_statement(statement)
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 1:
        raise RecalithError("invalid_schema", "--expected-revision is a positive integer")
    target_ref = {"kind": "claim", "id": claim_id, "revision": expected_revision}
    env = operator_event(ctx, "operator_correction", {"statement": statement, "target": target_ref}, key=digest_of([claim_id, expected_revision, statement]))

    def build(txn: Any, duplicate: bool) -> tuple[list[ProposedOperation], list[RecordRef]]:
        head = records.head(txn, "claim", claim_id)
        if head is None:
            raise RecalithError("invalid_schema", "no such claim in this installation")
        if head[0] != expected_revision and not duplicate:  # a retried submission returns its recorded result instead
            raise RecalithError("revision_conflict", f"the claim is at revision {head[0]}, not the expected {expected_revision}: nothing was applied")
        target = records.body(txn, "claim", claim_id, expected_revision)
        if target is None:
            raise RecalithError("invalid_schema", "no such claim revision in this installation")
        if target.get("status") in ("quarantined", "forgotten"):
            raise RecalithError("policy_refused", "a quarantined or forgotten claim has no content to correct")
        ref = RecordRef.model_validate(target_ref)
        invalidate = ProposedOperation.model_validate({
            "local_ref": "invalidate", "kind": "change_claim_status", "target": target_ref,
            "payload": {"claim_ref": target_ref, "status": "invalidated"},
            "evidence": [_statement_link(env.event_id, statement, "contradicts")], "reason": "operator correction",
        })
        payload, evidence = _replacement(target, statement, env.event_id)
        replace = ProposedOperation.model_validate({"local_ref": "replacement", "kind": "propose_claim", "depends_on": ["invalidate"], "payload": payload, "evidence": evidence, "reason": "operator correction replacement"})
        return [invalidate, replace], [ref]

    return _submit(ctx, env, build, review_origin="operator_correction", store=store, now=now)


def correct(ctx: InstallationContext, claim_id: str, *, expected_revision: int, statement: str, store: Store | None = None, now: str | None = None) -> ApplyResult:
    """Invalidate the expected current target and queue a linked replacement's review, atomically (SYSTEM_SPEC §7.3).

    One transaction: the operator correction event, the target's
    invalidation (cited ``contradicts``; the guidance epoch advances, so the
    next packet excludes it) and a replacement candidate whose review is queued
    as an operator correction. A stale ``expected_revision`` applies nothing
    (``revision_conflict``). No model is called; the old guidance stops even
    with a zero budget, and the replacement is not admitted until its review.
    """
    return submit_correction(ctx, claim_id, expected_revision=expected_revision, statement=statement, store=store, now=now).result


# --------------------------------------------------------------------------
# Other guarded writes (operator actor; the CLI guard already passed)


def initialize(root: Path, *, domain_profile: str, release_profile: str, operator_verifiers: Mapping[str, str] | None = None) -> InstallationContext:
    """First init of a checkout; never resets an existing store (``policy_refused``)."""
    if release_profile == "full":
        raise unavailable("the full release profile", "the full release (Cut 2)")
    if release_profile != "claude_preview" or domain_profile not in ("coding", "general"):
        raise RecalithError("invalid_schema", "init takes --profile coding|general and --release-profile claude_preview|full")
    layout = identity.Layout(Path(root))
    if layout.project_toml.exists():
        project_id = identity.load_project_config(layout).project_id
    else:
        project_id = new_id("proj")
    config = ProjectConfig.defaults_for(project_id, release_profile=release_profile, domain_profile=domain_profile)
    return identity.initialize_installation(Path(root), config, operator_verifiers=operator_verifiers)


def undo_preview(ctx: InstallationContext, operation_id: str) -> UndoPreview:
    return apply.preview_undo(ctx, operation_id)


def undo_apply(ctx: InstallationContext, operation_id: str, *, preview_digest: str) -> ApplyResult:
    require_operator(ctx, "undo --apply")
    return _retrying(lambda: apply.apply_undo(ctx, operation_id, preview_digest=preview_digest))


def retry_job(ctx: InstallationContext, job_id: str) -> dict[str, Any]:
    require_operator(ctx, "jobs retry")

    def run() -> dict[str, Any]:
        with open_store(ctx) as store, store.transaction() as txn:
            now = utc_now()
            job = jobs.retry(txn, job_id, now=now)
            txn.execute(
                "INSERT INTO operations (operation_id, job_id, actor, kind, inputs, changed, reason, store_revision, created_at) VALUES (?, ?, ?, 'job_retry', '{}', '[]', 'operator retry', ?, ?)",
                (new_id("op"), job_id, canonical_json(ctx.actor).decode(), txn.next_store_revision, now),
            )
            failpoints.hit(failpoints.SERVICE_BEFORE_COMMIT)
        failpoints.hit(failpoints.SERVICE_AFTER_COMMIT)
        return {"job_id": job.job_id, "kind": job.kind, "state": job.state, "due_at": job.due_at}

    return _retrying(run)


def rebind(root: Path, actor: Actor) -> InstallationContext:
    if actor.kind != "operator":
        raise RecalithError("policy_refused", "rebind is an operator action")
    return identity.rebind_installation(Path(root), actor=actor)


def discard_copy(root: Path, actor: Actor) -> None:
    identity.discard_copied_private_state(Path(root), actor=actor)


def register_token(root: Path, token_id: str, verifier: str) -> None:
    identity.update_operator_tokens(Path(root), register={token_id: verifier})


def revoke_token(root: Path, token_id: str) -> None:
    identity.update_operator_tokens(Path(root), revoke=token_id)


# --------------------------------------------------------------------------
# Backup and the verification a restore runs first (Task 15 core, decision 0016)


def submit_backup(ctx: InstallationContext, destination: Path, *, now: str | None = None):
    """``recalith backup --output PATH``: a consistent, verified backup with the tombstone ledger (operator)."""
    from recalith.storage import backup as storage_backup

    require_operator(ctx, "backup")
    return storage_backup.create(ctx, Path(destination), now=now)


def backup(ctx: InstallationContext, destination: Path) -> ArtifactManifest:
    """DATA_CONTRACTS §11: the verified backup's manifest (see :func:`submit_backup`)."""
    return submit_backup(ctx, destination).manifest


def restore(ctx: InstallationContext, source: Path, *, expected_digest: str):
    """``recalith restore``: verify first (digest, files, snapshot, schema, ledger) without touching the live store.

    A backup that does not verify is rejected (``invalid_schema``, exit 2)
    with its reason code. Applying a verified backup under maintenance with
    the newer suppression ledger is Task 16 and stays unavailable here.
    """
    from recalith.storage import backup as storage_backup

    require_operator(ctx, "restore")
    if not isinstance(expected_digest, str) or len(expected_digest) != 64 or any(c not in "0123456789abcdef" for c in expected_digest):
        raise RecalithError("invalid_schema", "--expected-digest is the 64-character SHA-256 of the backup's manifest")
    verified = storage_backup.verify(Path(source), expected_digest=expected_digest, ctx=ctx)
    raise RecalithError(
        "capability_unavailable",
        f"the backup verified (schema {verified.manifest.schemas['database']}, tombstone epoch {verified.manifest.tombstone_epoch}, store revision {verified.meta['store_revision']}); "
        "applying a restore is not available in this build (owned by Task 16: suppression-aware restore)",
    )


# --------------------------------------------------------------------------
# Worker control (the guarded public transport; the hook never uses it)


def worker_start(ctx: InstallationContext, *, inherited: Mapping[str, str], executable: str | None = None) -> dict[str, Any]:
    """Start this installation's persistent worker detached (operator; markers already refused).

    The worker's own environment is built afterwards by the one stdlib
    builder (``spawn_environment``), exactly as for any worker child. This is
    child-environment construction after the guard, never a way to obtain
    operator authority.
    """
    require_operator(ctx, "worker start")
    root = str(ctx.root)
    if process_env.worker_running(root):
        return {"state": "worker_running"}
    manifest = process_env.role_manifest(ctx.installation_id, purpose="worker")
    env = process_env.spawn_environment(manifest, inherited, purpose="worker")
    exe = executable or sys.executable
    argv = [exe, "-I", "-m", process_env.WORKER_MODULE, "--project", root, "--spawned-by", "cli", "--spawn-method", "posix_session" if os.name != "nt" else "windows_breakaway"]
    pid, method, degraded = process_env.start_detached(argv, env, cwd=process_env.run_dir(root))
    stamp = Path(process_env.run_dir(root)) / process_env.START_STAMP
    stamp.write_text(json.dumps({"at": time.time(), "pid": pid, "method": method, "degraded": degraded, "spawned_by": "cli"}), encoding="utf-8")
    return {"state": "worker_independence_degraded" if degraded else "worker_started", "pid": pid, "method": method, "degraded": degraded}


def worker_stop(ctx: InstallationContext, *, wait_seconds: float = WORKER_STOP_SECONDS) -> dict[str, Any]:
    require_operator(ctx, "worker stop")
    from recalith.controller import worker as worker_module

    root = str(ctx.root)
    if not process_env.worker_running(root):
        return {"state": "not_running"}
    worker_module.request_stop(root)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if not process_env.worker_running(root):
            return {"state": "stopped"}
        time.sleep(0.1)
    return {"state": "stop_requested"}


def worker_command(ctx: InstallationContext, *, inherited: Mapping[str, str], executable: str | None = None) -> tuple[list[str], dict[str, str]]:
    """The foreground ``worker run --mode persistent`` child: the internal entry with a fresh worker environment."""
    require_operator(ctx, "worker run")
    manifest = process_env.role_manifest(ctx.installation_id, purpose="worker")
    env = process_env.spawn_environment(manifest, inherited, purpose="worker")
    argv = [executable or sys.executable, "-I", "-m", process_env.WORKER_MODULE, "--project", str(ctx.root), "--spawned-by", "cli", "--spawn-method", "foreground"]
    return argv, env


# --------------------------------------------------------------------------
# Agent assertion and the guard's audit (spool only; never SQLite)


def observe(ctx: InstallationContext, observations: Sequence[Mapping[str, Any]]) -> CaptureReceipt:
    """``recalith observe --stdin``: an agent assertion, captured as an untrusted external observation.

    It never carries user or tool authority and is never a declaration root.
    The receipt is ``not_captured`` when durability was not acknowledged.
    """
    if not observations or len(observations) > 64:
        raise RecalithError("invalid_schema", "observe takes 1 to 64 observations")
    envelopes: list[EventEnvelope] = []
    for item in observations:
        if not isinstance(item, Mapping) or set(item) - {"source_event_key", "text", "host_session_id", "occurred_at"}:
            raise RecalithError("invalid_schema", "an observation has source_event_key, text and optional host_session_id/occurred_at")
        key, text = item.get("source_event_key"), item.get("text")
        host = item.get("host_session_id") or "observe"
        if not isinstance(key, str) or not key or not isinstance(text, str) or not text or not isinstance(host, str):
            raise RecalithError("invalid_schema", "an observation needs a source_event_key and text")
        raw = RawEvent(adapter_id=CLI_ADAPTER, adapter_version=ctx.engine_version, source_event_key=f"observe:{key}", session_id=cli_session(ctx, f"observe:{host}"), host_session_id=f"observe:{host}"[:256],
                       kind="generic_observation", payload={"text": text}, certified=False, origin_kind="agent_assertion", occurred_at=item.get("occurred_at"))
        envelopes.extend(normalize_event(ctx, raw)[0])
    return pipeline.capture(ctx, envelopes, deadline=time.monotonic() + 5.0)


def audit_refusal(ctx: InstallationContext, *, command_kind: str, marker_category: str) -> CaptureReceipt:
    """Spool one content-free ``agent_attempted_operator_command`` (command kind, caller category, reason)."""
    raw = RawEvent(adapter_id=CLI_ADAPTER, adapter_version=ctx.engine_version, source_event_key=f"refused:{new_id('att')}", session_id=cli_session(ctx, GUARD_HOST_SESSION), host_session_id=GUARD_HOST_SESSION,
                   kind="agent_attempted_operator_command", payload={"command_kind": command_kind[:64], "marker_category": marker_category[:64], "reason_code": "policy_refused"}, origin_kind="operator_guard")
    envelopes, _notes = normalize_event(ctx, raw)
    return pipeline.capture(ctx, envelopes, deadline=time.monotonic() + 2.0)


# --------------------------------------------------------------------------
# Read-only inspection (bounded; no authority needed)


def _page(limit: int | None) -> int:
    if limit is None:
        return PAGE_DEFAULT
    if not isinstance(limit, int) or limit < 1 or limit > PAGE_MAX:
        raise RecalithError("invalid_schema", f"--limit is 1..{PAGE_MAX}")
    return limit


def _snippet(text: Any) -> str | None:
    if not isinstance(text, str):
        return None
    return text if len(text) <= SNIPPET_CHARS else text[: SNIPPET_CHARS - 1] + "…"


def _summary(kind: str, record_id: str, revision: int, status: str, body: dict[str, Any] | None) -> dict[str, Any]:
    body = body or {}
    out: dict[str, Any] = {"kind": kind, "id": record_id, "revision": revision, "status": status}
    if kind == "claim":
        out.update({"claim_kind": body.get("kind"), "basis": body.get("basis"), "strength": body.get("strength"), "freshness": body.get("freshness"), "text": _snippet(body.get("proposition"))})
    elif kind == "task":
        out.update({"title": _snippet(body.get("title"))})
    else:
        out.update({"title": _snippet(body.get("title")), "task_id": body.get("task_id")})
    return out


def list_records(ctx: InstallationContext, group: str, *, status: str | None = None, limit: int | None = None, after: str | None = None) -> dict[str, Any]:
    """``recalith tasks|episodes|claims [--status S]``: one bounded page of heads, cursor-paginated by ID."""
    kind = LIST_KINDS.get(group)
    if kind is None:
        raise RecalithError("invalid_schema", "list tasks, episodes or claims")
    if status is not None and status not in STATUSES[kind]:
        raise RecalithError("invalid_schema", f"{group} status is one of {', '.join(STATUSES[kind])}")
    size = _page(limit)
    table, key = records.HEAD_TABLES[kind]
    column = "state" if kind == "episode" else "status"
    sql = f"SELECT {key}, revision, {column} FROM {table} WHERE (? IS NULL OR {column} = ?) AND (? IS NULL OR {key} > ?) ORDER BY {key} LIMIT ?"  # noqa: S608 - fixed names
    with open_store(ctx, readonly=True) as store, store.read() as view:
        rows = view.execute(sql, (status, status, after, after, size + 1)).fetchall()
        items = [_summary(kind, rid, rev, st, records.body(view, kind, rid, rev)) for rid, rev, st in rows[:size]]
    return {"items": items, "next": items[-1]["id"] if len(rows) > size else None}


def show(ctx: InstallationContext, record_id: str, *, revision: int | None = None) -> dict[str, Any]:
    """``recalith show ID [--revision N]``: one record (current head unless a revision is named)."""
    prefix = record_id.split("_", 1)[0]
    with open_store(ctx, readonly=True) as store, store.read() as view:
        if prefix in ("claim", "task", "ep"):
            kind = {"claim": "claim", "task": "task", "ep": "episode"}[prefix]
            head = records.head(view, kind, record_id)
            if head is None:
                raise RecalithError("invalid_schema", "no such record in this installation")
            rev = head[0] if revision is None else revision
            body = records.body(view, kind, record_id, rev)
            if body is None:
                raise RecalithError("invalid_schema", "no such revision")
            return {"kind": kind, "id": record_id, "revision": rev, "head_revision": head[0], "head_status": head[1], "body": body}
        if prefix == "evt":
            row = view.execute("SELECT envelope, payload FROM events WHERE event_id = ?", (record_id,)).fetchone()
            if row is None:
                raise RecalithError("invalid_schema", "no such event in this installation")
            envelope = json.loads(row[0])
            envelope["payload"] = json.loads(row[1]) if row[1] is not None else None
            return {"kind": "event", "id": record_id, "revision": 1, "body": envelope}
        if prefix == "op":
            row = view.execute("SELECT operation_id, job_id, kind, actor, inputs, changed, reason, causal_root, store_revision, created_at FROM operations WHERE operation_id = ?", (record_id,)).fetchone()
            if row is None:
                raise RecalithError("invalid_schema", "no such operation in this installation")
            keys = ("operation_id", "job_id", "kind", "actor", "inputs", "changed", "reason", "causal_root", "store_revision", "created_at")
            body = dict(zip(keys, row, strict=True))
            for name in ("actor", "inputs", "changed"):
                body[name] = json.loads(body[name])
            return {"kind": "operation", "id": record_id, "revision": 1, "body": body}
        if prefix == "job":
            job = jobs.get_job(view, record_id)
            if job is None:
                raise RecalithError("invalid_schema", "no such job in this installation")
            return {"kind": "job", "id": record_id, "revision": 1, "body": job.model_dump(mode="json")}
    raise RecalithError("invalid_schema", "show takes a claim, task, episode, event, operation or job ID")


def list_jobs(ctx: InstallationContext, *, limit: int | None = None) -> dict[str, Any]:
    size = _page(limit)
    with open_store(ctx, readonly=True) as store, store.read() as view:
        rows = view.execute("SELECT body FROM jobs ORDER BY due_at DESC, job_id LIMIT ?", (size,)).fetchall()
        summary = jobs.queue_summary(view, now=utc_now())
    items = []
    for (body,) in rows:
        job = json.loads(body)
        items.append({k: job.get(k) for k in ("job_id", "kind", "state", "priority", "due_at", "attempt", "budget_pool", "review_priority", "last_error_code")})
    return {"items": items, "summary": summary}


def manual_query(ctx: InstallationContext, text: str, *, purpose: str = "manual", session_id: str | None = None, task_id: str | None = None, **extra: Any) -> ContextQuery:
    try:
        return ContextQuery.model_validate({"session_id": session_id or cli_session(ctx, "inspect"), "task_id": task_id, "workspace_id": ctx.workspace_id, "purpose": purpose, "text": text, **extra})
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})[:8]
        raise RecalithError("invalid_schema", f"invalid context query fields: {fields}") from None


def context(ctx: InstallationContext, query: ContextQuery) -> ContextPacket:
    """``recalith context``: the same fenced, budgeted packet as ``retrieval.compile.compile_context``."""
    from recalith.retrieval import compile as retrieval_compile

    if query.workspace_id != ctx.workspace_id:
        raise RecalithError("foreign_installation", "the query names another workspace")
    return retrieval_compile.compile_context(ctx, query)


def record_delivery(ctx: InstallationContext, packet: ContextPacket, session_id: str, **kw: Any):
    """DATA_CONTRACTS §11: spool a ``DeliveryReceipt`` for a packet this caller delivered; worker ingestion owns the row.

    The hook path never calls this: it uses the stdlib
    ``recalith.fast.delivery.hook_record_delivery`` (DATA_CONTRACTS §2.3).
    """
    from recalith.retrieval import delivery

    return delivery.record_delivery(ctx, packet, session_id, **kw)


def search(ctx: InstallationContext, text: str, *, history: bool = False, limit: int | None = None) -> dict[str, Any]:
    """``recalith search QUERY [--history]``: current eligible items via ``retrieve``; ``--history`` adds retired claims."""
    from recalith.retrieval import search as retrieval_search

    size = _page(limit)
    if not text.strip():
        raise RecalithError("invalid_schema", "search needs query text")
    items: list[ContextItem] = retrieval_search.retrieve(ctx, manual_query(ctx, text), limit=min(size, retrieval_search.CANDIDATE_LIMIT))
    out: dict[str, Any] = {"items": [i.model_dump(mode="json") for i in items[:size]], "history": []}
    if history:
        words = [w for w in text.lower().split() if w][:16]
        with open_store(ctx, readonly=True) as store, store.read() as view:
            rows = view.execute(
                "SELECT h.claim_id, h.revision, h.status FROM claim_heads h WHERE h.status IN ('superseded', 'invalidated', 'archived') ORDER BY h.claim_id LIMIT ?", (SEARCH_HISTORY_SCAN,)
            ).fetchall()
            for claim_id, rev, status in rows:
                body = records.body(view, "claim", claim_id, rev) or {}
                proposition = (body.get("proposition") or "").lower()
                if words and all(w in proposition for w in words):
                    out["history"].append(_summary("claim", claim_id, rev, status, body))
                    if len(out["history"]) >= size:
                        break
    return out


def status(ctx: InstallationContext, *, inherited: Mapping[str, str]) -> dict[str, Any]:
    """``recalith status``: content-free state. Health composition and readiness are Task 17: never claimed here."""
    from recalith.controller import worker as worker_module
    from recalith.providers import base as provider_base

    from recalith.privacy import retention

    with open_store(ctx, readonly=True) as store:
        meta = store.meta()
        with store.read() as view:
            queue = jobs.queue_summary(view, now=utc_now())
            kept = retention.last_report(view)
    route = provider_base.route_status(provider_base.load_provider_config(ctx.root), installation_id=ctx.installation_id, inherited=inherited, observe=False)
    worker_state = worker_module.read_status(ctx.root) or {}
    running = process_env.worker_running(str(ctx.root))
    return {
        "project_id": ctx.project_id, "installation_id": ctx.installation_id, "release_profile": meta.release_profile, "engine_version": ctx.engine_version, "schema_version": meta.schema_version,
        "store_revision": meta.store_revision, "guidance_epoch": meta.guidance_epoch, "policy_revision": meta.policy_revision, "tombstone_epoch": meta.tombstone_epoch,
        "worker": {"running": running, "state": worker_state.get("state") if running else "stopped", "spawn": worker_state.get("spawn") if running else None, "model_lane": worker_state.get("model_lane") if running else None},
        "jobs": queue,
        "capture": pipeline.capture_health(ctx),
        "inference": {"state": route.state, "reasons": route.reasons},
        "retention": kept,
        "health": {"state": "unavailable", "reason_codes": ["health_composition_unavailable"], "owner": "task_17"},
        "autonomous_ready": False,
        "readiness": "not_evaluated",
    }


def doctor(ctx: InstallationContext, *, inherited: Mapping[str, str]) -> dict[str, Any]:
    """``recalith doctor`` without probes: read-only store checks plus :func:`status`; never claims readiness."""
    report = status(ctx, inherited=inherited)
    with open_store(ctx, readonly=True) as store, store.read() as view:
        quick = view.execute("PRAGMA quick_check").fetchone()[0]
    report["checks"] = {"store_quick_check": "ok" if quick == "ok" else "failed", "revision_chain": "unavailable_in_preview", "private_path_rules": "not_probed"}
    return report
