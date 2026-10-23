"""Intentional forgetting and suppression-aware restore (SYSTEM_SPEC §11–§12; DATA_CONTRACTS §8, §10–§11; decision 0017).

**Preview** (:func:`preview_forget`, read-only). A :class:`ForgetSelector`
names records (claims, tasks, episodes, events), tasks (the task, the events
bound to it, its linked placeholders and episodes, and its sessions' events
not yet bound), source ranges (one adapter's host session; the adapter's
source sequence, or for an adapter that reports none the 1-based capture
ordinal in that session, spooled events after stored ones) or a saved exact
query result. The dependency closure adds every event derived from or
relaying a forgotten one, every record any revision of which cites forgotten
content (an event, a root, a record, a claim dependency), the delivery
receipts that name a closure record, and the recorded backups whose snapshot
still holds closure content. A derivative whose current revision keeps a
surviving root becomes a **content-free quarantined** head; the selected
records and every derivative without one become **forgotten**. The preview
digest covers the selector, the closure, the head revisions, the affected
backups and exports and the tombstone epoch.

**Apply** (:func:`apply_forget`) runs persisted maintenance phases under an
exclusive privacy-maintenance lock with delivery and model launches paused
(the maintenance marker): (1) in **one transaction**, the closure is
recomputed and must match the preview digest, the payloads are released
(``retention.release_payloads``: forgetting overrides pins), every revision
body of a closure record is purged and a body-less forgotten/quarantined
marker revision becomes its head, envelopes, conflict bodies, root
descriptors, environment values, write paths, operation inputs and reasons,
proposal bodies, binding annotations, deliveries and outcome links, the
projections (views, lexical index, FTS) are purged, unfinished jobs over
closure input are cancelled, the content-free tombstone, its targets and the
new tombstone epoch are written, and the privacy operation is persisted; the
spool and session scratch are cleaned before the commit too, and again
after it; (2) external file cleanup; (3) the latest ledger copy; (4) a fresh
verified backup; (5) deletion of the affected older backups, even when that
backup failed (privacy first: ``backup_unavailable_after_forget``); (6) the
reconstruction jobs (an extraction over each quarantined claim's surviving
roots: ordinary admission and review, never part of the purge); (7) the
marker is removed and delivery resumes. A crash anywhere resumes from the
persisted operation (the worker's poll, the next forget or restore); until
then the marker keeps delivery paused.

**Replay suppression.** Every forgotten event ID (stored or still spooled)
and record ID is a tombstone target; ingestion stores nothing for a target
(``repository.insert_event``: ``suppressed``), so a replay of a known source
or an old spool segment cannot resurrect it. A truly new statement has a new
source identity and is ordinary new evidence. Paraphrases are not detected:
that would need the forgotten content.

**Restore** (:func:`restore`) verifies first (Task 15), then takes the same
lock and marker plus the installation lock (the worker must stop), stages the
snapshot beside the live store, applies inside the staged store every newer
tombstone (from the live store, the latest ledger copy and the backup's own
ledger) with the same purge, carries over the live backup and privacy
records, queues reconstruction, and only then replaces the live store
atomically (journaled; recovery finishes or discards an interrupted restore
before the worker opens the store).

**Limits** (reported, never hidden): explicit external exports, operator
copies of backups and remote provider copies cannot be recalled by local
deletion; logical forgetting is not secure erasure of storage media
(filesystem forensics, the WAL before a checkpoint, third-party backups); the
ledger's identifiers and digests permit membership guesses by anyone who can
read it; adapters' source event keys are kept as opaque origin identifiers.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from recalith import prompts
from recalith.contracts.common import InstallationContext, RecordRef, canonical_json, derived_id, digest_of, utc_now
from recalith.contracts.privacy import ForgetPreview, ForgetRequest, ForgetResult, ForgetSelector, RestoreResult
from recalith.core import lineage
from recalith.errors import RecalithError
from recalith.fast import failpoints, process_env, session, spool
from recalith.privacy import capsules, retention
from recalith.storage import records
from recalith.storage.db import SCHEMA_VERSION, STATE_DB, Store, Txn, open_store

FORGET_KIND = "forget"
RESTORE_KIND = "restore"
PURGED = ("forgotten", "quarantined")
TERMINAL_JOBS = ("completed", "failed", "cancelled")
FORGOTTEN_INPUT = "forgotten_input"
BACKUP_DIR = Path(".recalith") / "backups"
RESTORE_JOURNAL = Path(".recalith") / "run" / "restore.json"
PRIVACY_LOCK = "privacy.lock"
LOCK_WAIT_SECONDS = 10.0
SCRATCH_LOCK_WAIT = 0.5
SCRATCH_LOCK_BUDGET = 2.0
BUSY_RETRY_SECONDS = 5.0
WORKER_STOP_SECONDS = 15.0
CONTENT_FREE_OPERATIONS = frozenset({"payload_release", "support_lost", "retention_expiry", capsules.KIND, FORGET_KIND, RESTORE_KIND, "recheck", "job_retry"})
LIMITS = (
    "external_exports_not_recallable",
    "remote_provider_copies_not_recallable",
    "operator_backup_copies_not_recallable",
    "filesystem_forensics_outside_guarantee",
    "ledger_digest_membership_disclosure",
    "paraphrase_not_detected",
)
_ID = re.compile(r"\b(?:evt|claim|task|ep|cap)_(?:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|[0-9a-f]{64})\b")
_IN = 400
_KIND_OF_PREFIX = {"evt": "event", "claim": "claim", "task": "task", "ep": "episode"}
_SHELL_FIELDS = (
    "schema_version", "event_id", "project_id", "installation_id", "workspace_id", "adapter_id", "adapter_version", "source_event_key", "session_id",
    "host_session_id", "task_id", "source_sequence", "occurred_at", "recorded_at", "kind", "channel", "authority", "root_event_ids", "payload_digest", "coverage",
)


def _chunks(items: Sequence[Any]) -> Iterable[Sequence[Any]]:
    for i in range(0, len(items), _IN):
        yield items[i : i + _IN]


def _marks(items: Sequence[Any]) -> str:
    return ",".join("?" for _ in items)


def _kind_of(record_id: str) -> str | None:
    return _KIND_OF_PREFIX.get(record_id.split("_", 1)[0])


# --------------------------------------------------------------------------
# Exclusive privacy maintenance: the lock and the marker


class _PrivacyLock(session.SessionLock):
    """One privacy-maintenance operation per installation (forget, restore, their recovery)."""

    def __init__(self, root: Path | str) -> None:
        self.path = os.path.join(process_env.run_dir(root), PRIVACY_LOCK)
        self.fd = None


@contextlib.contextmanager
def _exclusive(ctx: InstallationContext, *, wait: float) -> Iterator[None]:
    lock = _PrivacyLock(ctx.root)
    if not lock.acquire(wait):
        raise RecalithError("capability_unavailable", "another privacy maintenance operation (forget or restore) holds this installation; retry when it completes")
    try:
        yield
    finally:
        lock.release()


def write_marker(ctx: InstallationContext, *, kind: str, operation_id: str) -> None:
    """Pause delivery and model launches: the hook and the model lane check this file (decision 0017)."""
    path = Path(session.maintenance_path(ctx.root))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    try:
        os.write(fd, canonical_json({"kind": kind, "operation_id": operation_id, "pid": os.getpid(), "created_at": utc_now()}))
        spool.full_fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    spool.fsync_dir(path.parent)


def clear_marker(ctx: InstallationContext) -> None:
    try:
        os.unlink(session.maintenance_path(ctx.root))
    except FileNotFoundError:
        pass


def maintenance_marker(root: Path | str) -> dict[str, Any] | None:
    try:
        return json.loads(Path(session.maintenance_path(root)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@contextlib.contextmanager
def _write(store: Store) -> Iterator[Txn]:
    deadline = time.monotonic() + BUSY_RETRY_SECONDS
    while True:
        cm = store.transaction()
        try:
            txn = cm.__enter__()
        except RecalithError as exc:
            if exc.code != "storage_failure" or "busy" not in exc.message or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
            continue
        break
    try:
        yield txn
    except BaseException as exc:
        if not cm.__exit__(type(exc), exc, exc.__traceback__):
            raise
    else:
        cm.__exit__(None, None, None)


# --------------------------------------------------------------------------
# The spool (pending capture not yet in the store)


def _spool_envelopes(root: Path | str) -> list[tuple[Path, dict[str, Any]]]:
    out: list[tuple[Path, dict[str, Any]]] = []
    for path in spool.ready_segments(spool.SpoolDirs(root)):
        try:
            data = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        for env in data.get("envelopes") or []:
            if isinstance(env, dict) and isinstance(env.get("event_id"), str):
                out.append((path, env))
    return out


# --------------------------------------------------------------------------
# The dependency closure


@dataclass
class Closure:
    seed_events: set[str] = field(default_factory=set)
    seed_records: set[tuple[str, str]] = field(default_factory=set)
    events: set[str] = field(default_factory=set)  # stored events released as forgotten
    spool_events: set[str] = field(default_factory=set)  # selected events still in the spool
    capsules: set[str] = field(default_factory=set)  # capsules of released events (full profile, decision 0025): purged with them
    forgotten: set[tuple[str, str]] = field(default_factory=set)
    quarantined: dict[tuple[str, str], list[str]] = field(default_factory=dict)  # -> surviving root events
    heads: dict[tuple[str, str], int] = field(default_factory=dict)
    backups: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)

    @property
    def records(self) -> set[tuple[str, str]]:
        return self.forgotten | set(self.quarantined)

    @property
    def record_ids(self) -> set[str]:
        return {rid for _k, rid in self.records}

    @property
    def targets(self) -> list[str]:
        """Tombstone targets: every forgotten event (stored or spooled), its capsule, and forgotten record."""
        return sorted(self.events | self.spool_events | self.capsules | {rid for _k, rid in self.forgotten})

    def digest(self, selector: Any, tombstone_epoch: int) -> str:
        data = {
            "selector": selector, "events": sorted(self.events), "forgotten": sorted([k, i] for k, i in self.forgotten),
            "quarantined": sorted([k, i, roots] for (k, i), roots in self.quarantined.items()), "heads": sorted([k, i, r] for (k, i), r in self.heads.items()),
            "backups": sorted(self.backups), "exports": sorted(self.exports), "tombstone_epoch": tombstone_epoch,
        }
        if self.capsules:
            data["capsules"] = sorted(self.capsules)
        return digest_of(data)


def _events_of_sessions(q: Any, session_ids: Iterable[str]) -> list[tuple[str, int, int | None]]:
    out = []
    for chunk in _chunks(sorted(set(session_ids))):
        out += q.execute(f"SELECT event_id, commit_sequence, source_sequence FROM events WHERE session_id IN ({_marks(chunk)}) ORDER BY commit_sequence", tuple(chunk)).fetchall()  # noqa: S608
    return sorted(out, key=lambda r: r[1])


def _task_family(q: Any, task_id: str) -> set[str]:
    """The task and every linked placeholder that redirects to it (any depth)."""
    family, frontier = {task_id}, [task_id]
    while frontier:
        current = frontier.pop()
        for (child,) in q.execute("SELECT task_id FROM task_heads WHERE redirect_task_id = ?", (current,)).fetchall():
            if child not in family:
                family.add(child)
                frontier.append(child)
    return family


def _seeds(q: Any, ctx: InstallationContext, selector: ForgetSelector) -> tuple[set[str], set[tuple[str, str]], set[str]]:
    """(selected event IDs, selected records, selected IDs only in the spool)."""
    events: set[str] = set()
    found: set[tuple[str, str]] = set()
    pending = _spool_envelopes(ctx.root)
    spooled = {env["event_id"]: env for _p, env in pending}
    refs = list(selector.record_refs) + (list(selector.saved_query.record_refs) if selector.saved_query else [])
    for ref in refs:
        if ref.kind == "event":
            if q.execute("SELECT 1 FROM events WHERE event_id = ?", (ref.id,)).fetchone() is None and ref.id not in spooled:
                raise RecalithError("invalid_schema", "a selected event is not an event of this installation")
            events.add(ref.id)
        elif ref.kind in records.HEAD_TABLES:
            if records.head(q, ref.kind, ref.id) is None:
                raise RecalithError("invalid_schema", "a selected record is not a record of this installation")
            found.add((ref.kind, ref.id))
        else:
            origin = capsules.origin_event(q, ref.id)
            if origin is None:
                profile = q.execute("SELECT release_profile FROM installation_meta WHERE singleton = 1").fetchone()[0]
                if profile != "full":
                    raise RecalithError("invalid_schema", "capsules are full-release records; select their source events")
                raise RecalithError("invalid_schema", "a selected capsule is not a capsule of this installation")
            events.add(origin)  # forgetting a capsule forgets the evidence it keeps: its origin event (decision 0025)
    for task_id in selector.task_ids:
        if records.head(q, "task", task_id) is None:
            raise RecalithError("invalid_schema", "a selected task is not a task of this installation")
        family = _task_family(q, task_id)
        sessions: set[str] = set()
        for member in sorted(family):
            found.add(("task", member))
            for event_id, session_id in q.execute("SELECT event_id, session_id FROM task_binding_heads WHERE task_id = ?", (member,)).fetchall():
                events.add(event_id)
                if session_id:
                    sessions.add(session_id)
            for (episode_id,) in q.execute("SELECT episode_id FROM episode_heads WHERE task_id = ?", (member,)).fetchall():
                found.add(("episode", episode_id))
            for (session_id,) in q.execute("SELECT session_id FROM working_sessions WHERE task_id = ?", (member,)).fetchall():
                sessions.add(session_id)
        # Events of those sessions not bound to any task yet (still unreduced) and those still in the spool.
        for event_id, _seq, _source in _events_of_sessions(q, sessions):
            if q.execute("SELECT 1 FROM task_binding_heads WHERE event_id = ?", (event_id,)).fetchone() is None:
                events.add(event_id)
        events |= {eid for eid, env in spooled.items() if env.get("session_id") in sessions}
    for source in selector.source_ranges:
        sessions = {r[0] for r in q.execute("SELECT session_id FROM sessions WHERE adapter_id = ? AND host_session_id = ?", (source.adapter_id, source.host_session_id)).fetchall()}
        stored = _events_of_sessions(q, sessions)
        ordered: list[tuple[str, int | None]] = [(e, s) for e, _c, s in stored]
        known = {e for e, _s in ordered}
        ordered += [(eid, env.get("source_sequence")) for eid, env in spooled.items()
                    if env.get("adapter_id") == source.adapter_id and env.get("host_session_id") == source.host_session_id and eid not in known]
        for ordinal, (event_id, sequence) in enumerate(ordered, start=1):
            position = sequence if sequence is not None else ordinal
            if source.from_sequence <= position <= source.to_sequence:
                events.add(event_id)
    stored_ids: set[str] = set()
    for chunk in _chunks(sorted(events)):
        stored_ids |= {r[0] for r in q.execute(f"SELECT event_id FROM events WHERE event_id IN ({_marks(chunk)})", tuple(chunk)).fetchall()}  # noqa: S608
    return stored_ids, found, (events - stored_ids) & set(spooled)


def _derived_events(q: Any) -> dict[str, set[str]]:
    """parent event -> events derived from it, rooted in it or relaying it (forwarded subagent results)."""
    children: dict[str, set[str]] = {}
    for event_id, envelope, kind, state in q.execute("SELECT event_id, envelope, kind, payload_state FROM events").fetchall():
        env = json.loads(envelope)
        parents = {r.get("id") for r in env.get("derived_from") or [] if isinstance(r, dict) and r.get("kind") == "event"}
        parents |= {r for r in env.get("root_event_ids") or [] if isinstance(r, str)}
        for parent in parents - {event_id, None}:
            children.setdefault(parent, set()).add(event_id)
        if kind == "tool_finished" and state == "available":
            for relayed in lineage.forwarded_events(q, event_id):
                if relayed != event_id:
                    children.setdefault(relayed, set()).add(event_id)
    return children


def _link_index(q: Any) -> tuple[dict[tuple[str, str], set[tuple[str, str]]], dict[str, set[tuple[str, str]]]]:
    by_target: dict[tuple[str, str], set[tuple[str, str]]] = {}
    by_root: dict[str, set[tuple[str, str]]] = {}
    for owner_kind, owner_id, target_kind, target_id, roots in q.execute("SELECT owner_kind, owner_id, target_kind, target_id, root_event_ids FROM evidence_links").fetchall():
        owner = (owner_kind, owner_id)
        by_target.setdefault((target_kind, target_id), set()).add(owner)
        for root in json.loads(roots or "[]"):
            by_root.setdefault(root, set()).add(owner)
    for claim_id, record_id in q.execute("SELECT claim_id, record_id FROM dependencies WHERE kind = 'claim' AND record_id IS NOT NULL").fetchall():
        kind = _kind_of(record_id) or "claim"
        by_target.setdefault((kind, record_id), set()).add(("claim", claim_id))
    return by_target, by_root


def _surviving(q: Any, kind: str, record_id: str, revision: int, events: set[str], records_: set[tuple[str, str]]) -> list[str] | None:
    """Surviving roots of a derivative's current revision: events not forgotten, or None when nothing survives.

    A claim counts its support links; a task or episode every link. A record
    link to a record outside the closure also survives (its own roots).
    """
    relation = "AND relation = 'supports'" if kind == "claim" else ""
    rows = q.execute(
        f"SELECT target_kind, target_id, root_event_ids FROM evidence_links WHERE owner_kind = ? AND owner_id = ? AND owner_revision = ? {relation}",  # noqa: S608 - fixed text
        (kind, record_id, revision),
    ).fetchall()
    alive: set[str] = set()
    record_alive = False
    for target_kind, target_id, roots in rows:
        candidates = set(json.loads(roots or "[]"))
        if target_kind == "event":
            candidates.add(target_id)
        elif target_kind == "capsule" and (origin := capsules.origin_event(q, target_id)) is not None:
            candidates.add(origin)
        elif (target_kind, target_id) not in records_ and target_kind in records.HEAD_TABLES:
            head = records.head(q, target_kind, target_id)
            record_alive = record_alive or (head is not None and head[1] not in PURGED)
        for event_id in candidates - events:
            row = q.execute("SELECT payload_state FROM events WHERE event_id = ?", (event_id,)).fetchone()
            if row is not None and row[0] in ("available", "capsule_only"):
                alive.add(event_id)
    if alive or record_alive:
        return sorted(alive)
    return None


def _receipts_naming(q: Any, record_ids: set[str]) -> set[str]:
    out = set()
    for event_id, payload in q.execute("SELECT event_id, payload FROM events WHERE kind = 'memory_delivered' AND payload IS NOT NULL").fetchall():
        if set(_ID.findall(payload)) & record_ids:
            out.add(event_id)
    return out


def _affected_backups(q: Any, events: set[str], record_ids: set[str]) -> list[str]:
    """Recorded verified backups whose snapshot still holds content of the closure (unreadable counts as affected)."""
    from recalith.storage import backup

    out = []
    for backup_id, location in q.execute("SELECT backup_id, location FROM backups WHERE state = 'verified' ORDER BY created_at, backup_id").fetchall():
        if location and backup.holds(Path(location) / backup.BACKUP_DB, events, record_ids) is not False:
            out.append(backup_id)
    return out


def compute_closure(q: Any, ctx: InstallationContext, seed_events: set[str], seed_records: set[tuple[str, str]], *, spool_events: set[str] = frozenset()) -> Closure:  # type: ignore[assignment]
    cl = Closure(seed_events=set(seed_events), seed_records=set(seed_records), spool_events=set(spool_events))
    children = _derived_events(q)
    events = set(seed_events)
    frontier = list(events | set(spool_events))
    while frontier:
        parent = frontier.pop()
        for child in children.get(parent, ()):
            if child not in events:
                events.add(child)
                frontier.append(child)
    by_target, by_root = _link_index(q)
    found: set[tuple[str, str]] = set()
    queue: list[tuple[str, str]] = []

    def add(record: tuple[str, str]) -> None:
        if record in found:
            return
        head = records.head(q, *record)
        if head is None or head[1] == "forgotten":
            return  # nothing left to purge
        if head[1] == "quarantined" and record not in seed_records:
            return  # already content-free; its surviving roots were not selected
        found.add(record)
        queue.append(record)

    for record in sorted(seed_records):
        add(record)
    for event_id in sorted(events | set(spool_events)):
        owners = by_target.get(("event", event_id), set()) | by_target.get(("capsule", capsules.capsule_id(event_id)), set()) | by_root.get(event_id, set())
        for owner in sorted(owners):
            add(owner)
    while queue:
        record = queue.pop()
        for owner in sorted(by_target.get(record, ())):
            add(owner)
    record_ids = {rid for _k, rid in found}
    events |= _receipts_naming(q, record_ids)
    cl.events = events
    cl.capsules = set(capsules.existing(q, events))
    for record in sorted(found):
        revision = records.head(q, *record)[0]
        cl.heads[record] = revision
        if record in seed_records:
            cl.forgotten.add(record)
            continue
        surviving = _surviving(q, record[0], record[1], revision, events, found)
        if surviving is None:
            cl.forgotten.add(record)
        else:
            cl.quarantined[record] = surviving
    cl.backups = _affected_backups(q, events | set(spool_events), record_ids)
    cl.exports = [r[0] for r in q.execute("SELECT export_id FROM exports ORDER BY created_at, export_id").fetchall()]
    return cl


def closure_for(q: Any, ctx: InstallationContext, selector: ForgetSelector) -> Closure:
    events, found, spooled = _seeds(q, ctx, selector)
    return compute_closure(q, ctx, events, found, spool_events=spooled)


def _ref(kind: str, record_id: str, revision: int) -> RecordRef:
    return RecordRef(kind=kind, id=record_id, revision=revision)  # type: ignore[arg-type]


def _preview_of(cl: Closure, selector: ForgetSelector, epoch: int) -> ForgetPreview:
    affected = [_ref("event", e, 1) for e in sorted(cl.seed_events | cl.spool_events)]
    affected += [_ref(k, i, cl.heads[(k, i)]) for k, i in sorted(cl.seed_records) if (k, i) in cl.heads]
    derived = [_ref("event", e, 1) for e in sorted(cl.events - cl.seed_events)]
    derived += [_ref(k, i, cl.heads[(k, i)]) for k, i in sorted(cl.records - cl.seed_records)]
    return ForgetPreview(
        affected_refs=affected, derivative_refs=derived, backup_ids=cl.backups, export_ids=cl.exports,
        preview_digest=cl.digest(selector.model_dump(mode="json"), epoch),
        quarantined_refs=[_ref(k, i, cl.heads[(k, i)]) for k, i in sorted(cl.quarantined)], limits=list(LIMITS),
    )


def preview_forget(ctx: InstallationContext, selector: ForgetSelector, *, store: Store | None = None) -> ForgetPreview:
    """DATA_CONTRACTS §11: the dependency-aware preview (read-only; any actor)."""
    own = store is None
    store = store or open_store(ctx, readonly=True)
    try:
        with store.read() as view:
            epoch = view.execute("SELECT tombstone_epoch FROM installation_meta WHERE singleton = 1").fetchone()[0]
            return _preview_of(closure_for(view, ctx, selector), selector, epoch)
    finally:
        if own:
            store.close()


# --------------------------------------------------------------------------
# The purge (inside the caller's transaction; shared by forget and restore)


def _shell(envelope: str) -> str:
    """A forgotten event's content-free envelope: identities, times, channel and coverage only."""
    env = json.loads(envelope)
    out = {k: env[k] for k in _SHELL_FIELDS if k in env}
    origin = env.get("origin") or {}
    out["origin"] = {k: origin[k] for k in ("adapter_id", "source_event_key", "host_session_id", "origin_kind", "source_digest") if k in origin}
    out["derived_from"] = [{"kind": r.get("kind"), "id": r.get("id"), "revision": r.get("revision", 1)} for r in env.get("derived_from") or [] if isinstance(r, dict)]
    out["extensions"] = {}
    out["forgotten"] = True
    return canonical_json(out).decode()


def _purge_events(txn: Txn, ctx: InstallationContext, events: set[str], *, now: str) -> list[RecordRef]:
    ids = sorted(events)
    lost = retention.release_payloads(txn, ctx, ids, now=now) if ids else []
    for chunk in _chunks(ids):
        marks = _marks(chunk)
        for event_id, envelope in txn.execute(f"SELECT event_id, envelope FROM events WHERE event_id IN ({marks})", tuple(chunk)).fetchall():  # noqa: S608
            txn.execute("UPDATE events SET envelope = ?, retention_after = NULL WHERE event_id = ?", (_shell(envelope), event_id))
        txn.execute(f"UPDATE source_conflicts SET scrubbed_payload = NULL, state = 'forgotten' WHERE original_event_id IN ({marks})", tuple(chunk))  # noqa: S608
        txn.execute(
            f"UPDATE root_members SET descriptor = NULL WHERE (source_namespace, source_event_key) IN (SELECT source_namespace, source_event_key FROM root_event_members WHERE event_id IN ({marks}))",  # noqa: S608
            tuple(chunk),
        )
        txn.execute(f"DELETE FROM environment_observations WHERE source_event_id IN ({marks})", tuple(chunk))  # noqa: S608
        txn.execute(f"DELETE FROM artifact_writes WHERE event_id IN ({marks})", tuple(chunk))  # noqa: S608
        # A forgotten call or result no longer pairs: a later result of a forgotten call is new capture, bound on its own.
        txn.execute(f"UPDATE tool_calls SET start_event_id = NULL WHERE start_event_id IN ({marks})", tuple(chunk))  # noqa: S608
        txn.execute(f"UPDATE tool_calls SET finish_event_id = NULL WHERE finish_event_id IN ({marks})", tuple(chunk))  # noqa: S608
        txn.execute(f"UPDATE failure_triggers SET state = 'resolved' WHERE state != 'resolved' AND failure_event_id IN ({marks})", tuple(chunk))  # noqa: S608
        txn.execute(f"UPDATE claim_rechecks SET state = 'cleared', outcome = 'forgotten', settled_at = ? WHERE state != 'cleared' AND event_id IN ({marks})", (now, *chunk))  # noqa: S608
    return lost


_REVISION_STATUS = {"claim": "status", "task": "status", "episode": "state"}


def _purge_record(txn: Txn, kind: str, record_id: str, status: str, *, now: str, backend: str | None) -> None:
    from recalith.retrieval import index

    table, key = records.REVISION_TABLES[kind]
    head_table, _ = records.HEAD_TABLES[kind]
    revision, _old = records.head(txn, kind, record_id)
    txn.execute(f"UPDATE {table} SET body = NULL WHERE {key} = ?", (record_id,))  # noqa: S608 - fixed names
    column = _REVISION_STATUS[kind]
    if kind == "claim":
        claim_kind = txn.one("SELECT kind FROM claim_heads WHERE claim_id = ?", (record_id,))[0]
        txn.execute("INSERT INTO claim_revisions (claim_id, revision, kind, status, body, created_store_revision) VALUES (?, ?, ?, ?, NULL, ?)", (record_id, revision + 1, claim_kind, status, txn.next_store_revision))
        txn.execute("UPDATE claim_heads SET revision = ?, status = ?, review_due_at = NULL, action_family_digest = NULL, content_key = NULL WHERE claim_id = ?", (revision + 1, status, record_id))
        txn.execute("DELETE FROM dependencies WHERE claim_id = ?", (record_id,))
        txn.execute("UPDATE pending_supersessions SET state = 'withdrawn', decided_at = ? WHERE state = 'pending' AND (replacement_id = ? OR target_id = ?)", (now, record_id, record_id))
        txn.execute("UPDATE claim_rechecks SET state = 'cleared', outcome = 'forgotten', settled_at = ? WHERE state != 'cleared' AND claim_id = ?", (now, record_id))
        for question_id, claim_ids in txn.execute("SELECT question_id, claim_ids FROM intent_questions").fetchall():
            if record_id in json.loads(claim_ids):
                txn.execute("UPDATE intent_questions SET state = 'resolved', proposition_key = '{}', resolved_at = COALESCE(resolved_at, ?) WHERE question_id = ?", (now, question_id))
    else:
        txn.execute(f"INSERT INTO {table} ({key}, revision, {column}, body, created_store_revision) VALUES (?, ?, ?, NULL, ?)", (record_id, revision + 1, status, txn.next_store_revision))  # noqa: S608
        txn.execute(f"UPDATE {head_table} SET revision = ?, {column} = ? WHERE {key} = ?", (revision + 1, status, record_id))  # noqa: S608
    if kind == "task":
        txn.execute("DELETE FROM working_tasks WHERE task_id = ?", (record_id,))
        txn.execute("DELETE FROM working_sessions WHERE task_id = ?", (record_id,))
        for boundary_id, state, body in txn.execute("SELECT boundary_id, state, body FROM task_boundaries WHERE source_task_id = ?", (record_id,)).fetchall():
            data = json.loads(body)
            if isinstance(data, dict) and data.get("detail"):
                data["detail"] = {}
            txn.execute("UPDATE task_boundaries SET state = ?, body = ? WHERE boundary_id = ?", ("rejected" if state == "pending" else state, canonical_json(data).decode(), boundary_id))
    txn.execute("DELETE FROM evidence_links WHERE owner_kind = ? AND owner_id = ?", (kind, record_id))
    if backend is not None:
        index._remove(txn, kind, record_id, backend)  # noqa: SLF001 - the projection's own row removal


def _cancel_jobs(txn: Txn, ids: set[str], events: set[str]) -> list[str]:
    from recalith.controller import jobs

    cancelled = []
    marks = _marks(TERMINAL_JOBS)
    triggers = {trigger_id for trigger_id, failure in txn.execute("SELECT trigger_id, failure_event_id FROM failure_triggers").fetchall() if failure in events}
    for (body,) in txn.execute(f"SELECT body FROM jobs WHERE state NOT IN ({marks})", TERMINAL_JOBS).fetchall():  # noqa: S608
        data = json.loads(body)
        refs = {r.get("id") for r in data.get("input_refs") or []}
        if refs & ids or (data.get("trigger_ref") and data["trigger_ref"] in triggers):
            job = jobs.get_job(txn, data["job_id"])
            if job is not None:
                jobs.supersede(txn, job, FORGOTTEN_INPUT)  # cancelled: a late result is fenced, a lease ends
                cancelled.append(job.job_id)
    return cancelled


def _purge_bookkeeping(txn: Txn, ids: set[str], events: set[str]) -> dict[str, int]:
    counts = {"proposals": 0, "operations": 0, "deliveries": 0, "outcome_links": 0}
    job_inputs: dict[str, set[str]] = {}
    for job_id, body in txn.execute("SELECT job_id, body FROM jobs").fetchall():
        job_inputs[job_id] = {r.get("id") for r in json.loads(body).get("input_refs") or []}
    created: set[str] = set()
    for proposal_id, changed in txn.execute("SELECT proposal_id, changed FROM operations WHERE proposal_id IS NOT NULL").fetchall():
        if set(_ID.findall(changed or "")) & ids:
            created.add(proposal_id)
    for proposal_id, job_id, body in txn.execute("SELECT proposal_id, job_id, body FROM proposals WHERE body IS NOT NULL").fetchall():
        if proposal_id in created or job_inputs.get(job_id, set()) & ids or set(_ID.findall(body)) & ids:
            txn.execute("UPDATE proposals SET body = NULL WHERE proposal_id = ?", (proposal_id,))
            counts["proposals"] += 1
    for operation_id, kind, inputs, changed, local_ref in txn.execute("SELECT operation_id, kind, inputs, changed, local_ref FROM operations").fetchall():
        if kind in CONTENT_FREE_OPERATIONS or local_ref == "@apply":
            continue  # identifiers, counts and reason codes only (an application's ApplyResult is content-free)
        if set(_ID.findall((inputs or "") + (changed or ""))) & ids:
            txn.execute("UPDATE operations SET inputs = ?, reason = NULL WHERE operation_id = ?", (canonical_json({"purged": True, "kind": kind}).decode(), operation_id))
            counts["operations"] += 1
    for delivery_id, items, receipt, trigger in txn.execute("SELECT delivery_id, items, receipt_event_id, trigger_event_id FROM deliveries").fetchall():
        if set(_ID.findall(items or "")) & ids or receipt in events or trigger in events:
            counts["outcome_links"] += txn.execute("DELETE FROM outcome_links WHERE delivery_id = ?", (delivery_id,)).rowcount
            counts["deliveries"] += txn.execute("DELETE FROM deliveries WHERE delivery_id = ?", (delivery_id,)).rowcount
    for link_id, observed in txn.execute("SELECT link_id, observed_event_ids FROM outcome_links").fetchall():
        if set(json.loads(observed or "[]")) & events:
            counts["outcome_links"] += txn.execute("DELETE FROM outcome_links WHERE link_id = ?", (link_id,)).rowcount
    return counts


def _purge_projections(txn: Txn) -> None:
    """Views are dropped (republished after maintenance); FTS segments are merged so deleted terms leave the shadow tables."""
    txn.execute("DELETE FROM context_views")
    txn.execute("UPDATE projection_state SET views_store_revision = -1, views_guidance_epoch = -1, views_policy_revision = -1, views_tombstone_epoch = -1")
    if txn.one("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'lexical_fts'") is not None:
        txn.execute("INSERT INTO lexical_fts (lexical_fts) VALUES ('optimize')")


def purge(txn: Txn, ctx: InstallationContext, cl: Closure, *, now: str) -> dict[str, Any]:
    """Purge a closure inside the caller's transaction (no model, no network). Returns content-free counts."""
    from recalith.retrieval import index

    txn.execute("PRAGMA secure_delete = ON")  # deleted cells are overwritten, not left in free pages
    txn.purged()  # an authorized purge: its chain entry carries the purge marker (full profile)
    state = index.state(txn)
    backend = state["backend"] if state is not None else None
    _purge_events(txn, ctx, cl.events, now=now)
    for record in sorted(cl.forgotten):
        _purge_record(txn, *record, "forgotten", now=now, backend=backend)
    for record in sorted(cl.quarantined):
        _purge_record(txn, *record, "quarantined", now=now, backend=backend)
    ids = cl.record_ids | cl.events | cl.spool_events | cl.capsules
    cancelled = _cancel_jobs(txn, ids, cl.events | cl.spool_events)
    counts = _purge_bookkeeping(txn, ids, cl.events | cl.spool_events)
    _purge_projections(txn)
    from recalith.retrieval import lookup

    lookup.purge(txn, set(ids))
    txn.mutated(serving_relevant=True)
    return {"events": len(cl.events), "spool_events": len(cl.spool_events), "forgotten": len(cl.forgotten), "quarantined": len(cl.quarantined), "jobs_cancelled": len(cancelled), **counts}


def _tombstone(txn: Txn, tombstone_id: str, epoch: int, targets: Sequence[str], digests: Sequence[str], scope: str, now: str) -> None:
    txn.execute(
        "INSERT INTO tombstones (tombstone_id, epoch, target_ids, source_digests, deletion_scope, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (tombstone_id, epoch, canonical_json(sorted(targets)).decode(), canonical_json(sorted(digests)).decode(), scope, now),
    )
    for target in targets:
        txn.execute("INSERT OR IGNORE INTO tombstone_targets (target_id, tombstone_id, epoch) VALUES (?, ?, ?)", (target, tombstone_id, epoch))


def _scope(selector: ForgetSelector) -> str:
    present = [name for name, value in (("task", selector.task_ids), ("source_range", selector.source_ranges), ("saved_query", selector.saved_query), ("record", selector.record_refs)) if value]
    return present[0] if len(present) == 1 else "record"


def _source_digests(selector: ForgetSelector) -> list[str]:
    out = [digest_of(["source_range", r.adapter_id, r.host_session_id, r.from_sequence, r.to_sequence]) for r in selector.source_ranges]
    if selector.saved_query is not None:
        out.append(selector.saved_query.query_digest)
    return sorted(set(out))


def _audit(txn: Txn, ctx: InstallationContext, *, kind: str, key: Any, inputs: dict[str, Any], now: str) -> str:
    oid = derived_id("op", [kind, key])
    txn.execute(
        "INSERT OR IGNORE INTO operations (operation_id, job_id, proposal_id, atomic_group_id, actor, kind, inputs, changed, reason, causal_root, store_revision, created_at, local_ref, proposal_digest) "
        "VALUES (?, NULL, NULL, NULL, ?, ?, ?, '[]', NULL, NULL, ?, ?, ?, NULL)",
        (oid, canonical_json(ctx.actor).decode(), kind, canonical_json(inputs).decode(), txn.next_store_revision, now, f"@{kind}"),
    )
    return oid


# --------------------------------------------------------------------------
# External files: spool segments and session scratch


def _clean_spool(root: Path | str, targets: set[str]) -> int:
    """Drop target events from ready segments (rewritten atomically, or removed when nothing else is left)."""
    dirs = spool.SpoolDirs(root)
    removed = 0
    for path in spool.ready_segments(dirs):
        try:
            data = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        envelopes = data.get("envelopes") or []
        kept = [e for e in envelopes if not (isinstance(e, dict) and e.get("event_id") in targets)]
        if len(kept) == len(envelopes):
            continue
        removed += len(envelopes) - len(kept)
        if not kept:
            spool.remove_segment(dirs, path)
            continue
        data["envelopes"] = kept
        data["content_digest"] = digest_of(spool.segment_body(kept, data.get("cursor_proposals") or [], data.get("source_registrations") or []))
        outcome = spool.publish(dirs, path.name, canonical_json(data), deadline=None)
        if not outcome.ok:
            raise RecalithError("storage_failure", "a spool segment holding forgotten events could not be rewritten")
    for directory in (dirs.quarantine, dirs.tmp):
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            try:
                text = path.read_bytes().decode("utf-8", "replace")
            except OSError:
                continue
            if set(_ID.findall(text)) & targets:
                path.unlink(missing_ok=True)
                removed += 1
    return removed


def _clean_scratch(root: Path | str, events: set[str], record_ids: set[str], *, budget: float = SCRATCH_LOCK_BUDGET) -> list[str]:
    """Filter forgotten outcomes, items and restoration keys out of every session scratch; returns the sessions still owed.

    Each file is rewritten under its session lock (the hook's delivery holds
    the same lock from reservation to mark); totals and attempts stay, so
    accounting never resets. An invalid scratch that names a target is removed.
    """
    directory = Path(session.sessions_dir(root))
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    ids = events | record_ids
    pending = []
    give_up = time.monotonic() + budget
    for name in names:
        path = directory / name
        if name.endswith(".tmp"):
            try:
                if set(_ID.findall(path.read_bytes().decode("utf-8", "replace"))) & ids:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        if not name.endswith(".json"):
            continue
        session_id = name[: -len(".json")]
        try:
            raw = path.read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        if not set(_ID.findall(raw)) & ids:
            continue
        lock = session.SessionLock(root, session_id)
        if not lock.acquire(max(0.0, min(SCRATCH_LOCK_WAIT, give_up - time.monotonic()))):
            pending.append(session_id)
            continue
        try:
            scratch = session.read_scratch(root, session_id)
            if scratch is None:
                path.unlink(missing_ok=True)
                continue
            scratch["outcomes"] = [o for o in scratch["outcomes"] if o["event_id"] not in events]
            for entry in scratch["entries"]:
                entry["items"] = [i for i in entry["items"] if i["record_id"] not in record_ids]
                if entry.get("trigger_event_id") in events:
                    entry["trigger_event_id"] = None
                if entry.get("restoration_key") in events:
                    entry["restoration_key"] = None
            scratch["restored"] = [k for k in scratch["restored"] if k not in events]
            if scratch["compaction_key"] in events:
                scratch["compaction_key"] = None
            scratch["state_revision"] += 1
            session.write(root, scratch)
        except (OSError, ValueError):
            pending.append(session_id)
        finally:
            lock.release()
    return pending


def _purged_ids(q: Any) -> tuple[set[str], set[str]]:
    """(every tombstoned event ID, every forgotten or quarantined record ID): what file cleanup must remove."""
    targets = {r[0] for r in q.execute("SELECT target_id FROM tombstone_targets").fetchall()}
    events = {t for t in targets if t.startswith("evt_")}
    record_ids = {t for t in targets if not t.startswith("evt_")}
    for kind, (table, key) in records.HEAD_TABLES.items():
        column = "state" if kind == "episode" else "status"
        record_ids |= {r[0] for r in q.execute(f"SELECT {key} FROM {table} WHERE {column} IN ('forgotten', 'quarantined')").fetchall()}  # noqa: S608
    return events, record_ids


def clean_files(ctx: InstallationContext, store: Store, *, budget: float = SCRATCH_LOCK_BUDGET) -> list[str]:
    """Spool and scratch cleanup for every tombstone (idempotent); returns the sessions whose scratch is still owed."""
    with store.read() as view:
        events, record_ids = _purged_ids(view)
    if not events and not record_ids:
        return []
    _clean_spool(ctx.root, events)
    return _clean_scratch(ctx.root, events, record_ids, budget=budget)


# --------------------------------------------------------------------------
# Applying a forget: the persisted phases


def _op_row(q: Any, op_id: str) -> tuple[str, dict[str, Any], int, str] | None:
    row = q.execute("SELECT phase, remaining, new_epoch, status FROM privacy_operations WHERE privacy_operation_id = ?", (op_id,)).fetchone()
    return None if row is None else (row[0], json.loads(row[1]), row[2], row[3])


def _save_op(store: Store, op_id: str, *, phase: str, remaining: dict[str, Any], status: str, now: str) -> None:
    with _write(store) as txn:
        txn.execute("UPDATE privacy_operations SET phase = ?, remaining = ?, status = ?, updated_at = ? WHERE privacy_operation_id = ?", (phase, canonical_json(remaining).decode(), status, now, op_id))


def _backup_location(ctx: InstallationContext, op_id: str) -> Path:
    return Path(ctx.root) / BACKUP_DIR / f"forget-{op_id[4:20]}"


def _phase_backup(ctx: InstallationContext, store: Store, op_id: str, remaining: dict[str, Any], *, now: str) -> None:
    from recalith.core.paths import private_mkdir
    from recalith.storage import backup

    location = _backup_location(ctx, op_id)
    backup.recover(ctx, store)
    with store.read() as view:
        row = view.execute("SELECT backup_id FROM backups WHERE location = ? AND state = 'verified'", (str(location),)).fetchone()
    if row is not None:
        remaining["backup"] = {"state": "verified", "backup_id": row[0]}
        return
    try:
        private_mkdir(location.parent)
        made = backup.create(ctx, location, store=store, now=now)
    except RecalithError as exc:
        remaining["backup"] = {"state": "unavailable", "backup_id": None, "error": exc.code}
        return
    remaining["backup"] = {"state": "verified", "backup_id": made.manifest.artifact_id}


def _phase_delete(ctx: InstallationContext, store: Store, remaining: dict[str, Any]) -> None:
    from recalith.storage import backup

    deleted = set(remaining.get("deleted_backups") or [])
    new_id = (remaining.get("backup") or {}).get("backup_id")
    for backup_id in remaining.get("affected_backups") or []:
        if backup_id in deleted or backup_id == new_id:
            continue
        backup.delete_recorded(store, backup_id)
        deleted.add(backup_id)
    remaining["deleted_backups"] = sorted(deleted)


def _phase_reconstruct(store: Store, items: Sequence[dict[str, Any]], *, epoch: int, now: str) -> list[str]:
    """One extraction per quarantined claim over its surviving roots (ordinary admission and review later)."""
    from recalith.controller import jobs

    created = []
    if not items:
        return created
    with _write(store) as txn:
        for item in items:
            refs = [_ref("event", e, 1) for e in item["events"]]
            if not refs:
                continue
            key = digest_of(["reconstruct", item["claim_id"], epoch])
            job_id, _new = jobs.enqueue(txn, kind="extract_claims", input_refs=refs, now=now, prompt_version=prompts.CURRENT["extract_claims"], idempotency=key)
            created.append(job_id)
    return created


PHASES = ("purged", "files", "ledger", "backup", "deleted", "reconstructed", "completed")


def _run_phases(ctx: InstallationContext, store: Store, op_id: str, *, now: str) -> ForgetResult:
    from recalith.storage import backup

    with store.read() as view:
        found = _op_row(view, op_id)
    if found is None:
        raise RecalithError("invalid_schema", "no such privacy operation")
    phase, remaining, epoch, status = found
    if status != "completed":
        write_marker(ctx, kind=FORGET_KIND, operation_id=op_id)
    if PHASES.index(phase) < PHASES.index("files"):
        owed = clean_files(ctx, store)
        remaining["scratch_pending"] = owed
        if owed:
            _save_op(store, op_id, phase=phase, remaining=remaining, status="cleanup_pending", now=now)
            return _result(op_id, remaining, epoch, purge_state="cleanup_pending")
        phase = "files"
        _save_op(store, op_id, phase=phase, remaining=remaining, status="running", now=now)
        failpoints.hit(failpoints.FORGET_AFTER_FILES)
    if PHASES.index(phase) < PHASES.index("ledger"):
        backup._refresh_ledger(ctx, store)  # noqa: SLF001 - the latest ledger copy and its epoch mark
        phase = "ledger"
        _save_op(store, op_id, phase=phase, remaining=remaining, status="running", now=now)
        failpoints.hit(failpoints.FORGET_AFTER_LEDGER)
    if PHASES.index(phase) < PHASES.index("backup"):
        _phase_backup(ctx, store, op_id, remaining, now=now)
        phase = "backup"
        _save_op(store, op_id, phase=phase, remaining=remaining, status="running", now=now)
        failpoints.hit(failpoints.FORGET_AFTER_BACKUP)
    if PHASES.index(phase) < PHASES.index("deleted"):
        _phase_delete(ctx, store, remaining)  # also when the replacement backup failed: privacy first
        phase = "deleted"
        _save_op(store, op_id, phase=phase, remaining=remaining, status="running", now=now)
        failpoints.hit(failpoints.FORGET_AFTER_DELETE)
    if PHASES.index(phase) < PHASES.index("reconstructed"):
        remaining["reconstruction_jobs"] = _phase_reconstruct(store, remaining.get("reconstruct") or [], epoch=epoch, now=now)
        phase = "reconstructed"
        _save_op(store, op_id, phase=phase, remaining=remaining, status="running", now=now)
        failpoints.hit(failpoints.FORGET_AFTER_RECONSTRUCT)
    if status != "completed":
        _save_op(store, op_id, phase="completed", remaining=remaining, status="completed", now=now)
    _release_marker(ctx, store)
    store.checkpoint()
    return _result(op_id, remaining, epoch, purge_state="completed")


def _release_marker(ctx: InstallationContext, store: Store) -> None:
    """Delivery resumes only when no privacy operation is unfinished and no restore is journaled."""
    with store.read() as view:
        unfinished = view.execute("SELECT 1 FROM privacy_operations WHERE status != 'completed' LIMIT 1").fetchone()
    if unfinished is None and not (Path(ctx.root) / RESTORE_JOURNAL).exists():
        clear_marker(ctx)


def _result(op_id: str, remaining: dict[str, Any], epoch: int, *, purge_state: str) -> ForgetResult:
    backup_info = remaining.get("backup") or {"state": "pending", "backup_id": None}
    errors = []
    if backup_info["state"] == "unavailable":
        errors.append("backup_unavailable_after_forget")
    if remaining.get("scratch_pending"):
        errors.append("scratch_cleanup_pending")
    counts = remaining.get("counts") or {}
    return ForgetResult(
        operation_id=op_id, purge_state=purge_state, purged_count=int(counts.get("events", 0)) + int(counts.get("spool_events", 0)) + int(counts.get("forgotten", 0)),
        quarantined_count=int(counts.get("quarantined", 0)), tombstone_epoch=epoch, backup_state=backup_info["state"],
        new_backup_id=backup_info.get("backup_id") if backup_info["state"] == "verified" else None, deleted_backup_ids=sorted(remaining.get("deleted_backups") or []),
        external_copy_ids=sorted(remaining.get("external_copy_ids") or []), replay_suppression_coverage=remaining.get("coverage") or {}, error_codes=errors,
    )


def _coverage(cl: Closure) -> dict[str, Any]:
    return {
        "match": "source_identity", "suppressed_event_ids": len(cl.events | cl.spool_events), "suppressed_record_ids": len(cl.forgotten),
        "spooled_events_removed": len(cl.spool_events), "paraphrase_detection": False, "new_independent_statements": "admitted_as_new_evidence",
        "limits": list(LIMITS),
    }


def apply_forget(ctx: InstallationContext, request: ForgetRequest, *, store: Store | None = None, now: str | None = None, lock_wait: float = LOCK_WAIT_SECONDS) -> ForgetResult:
    """DATA_CONTRACTS §11: digest-guarded purge/quarantine and its persisted phases (the caller checked operator authority).

    Idempotent by preview digest: a retry after a crash resumes the persisted
    operation instead of applying anything twice.
    """
    now = now or utc_now()
    op_id = derived_id("frg", [ctx.installation_id, request.preview_digest])
    own = store is None
    store = store or open_store(ctx)
    try:
        with _exclusive(ctx, wait=lock_wait):
            _resume_unfinished(ctx, store, now=now, skip=op_id)
            with store.read() as view:
                existing = _op_row(view, op_id)
            if existing is not None:
                return _run_phases(ctx, store, op_id, now=now)
            had_marker = maintenance_marker(ctx.root) is not None
            write_marker(ctx, kind=FORGET_KIND, operation_id=op_id)
            failpoints.hit(failpoints.FORGET_AFTER_MARKER)
            try:
                with _write(store) as txn:
                    epoch = txn.meta.tombstone_epoch
                    cl = closure_for(txn, ctx, request.selector)
                    if cl.digest(request.selector.model_dump(mode="json"), epoch) != request.preview_digest:
                        raise RecalithError("revision_conflict", "the forget preview is no longer current (the closure, heads, backups or tombstone epoch changed): preview again")
                    if not cl.targets and not cl.quarantined:
                        raise RecalithError("invalid_schema", "the selection holds nothing left to forget")
                    # Pending capture and scratch are cleaned before the commit too (again after it).
                    _clean_spool(ctx.root, set(cl.targets))
                    pending = _clean_scratch(ctx.root, cl.events | cl.spool_events, cl.record_ids)
                    counts = purge(txn, ctx, cl, now=now)
                    new_epoch = epoch + 1
                    _tombstone(txn, op_id, new_epoch, cl.targets, _source_digests(request.selector), _scope(request.selector), now)
                    txn.execute("UPDATE installation_meta SET tombstone_epoch = ? WHERE singleton = 1", (new_epoch,))
                    _audit(txn, ctx, kind=FORGET_KIND, key=op_id, inputs={"tombstone_id": op_id, "epoch": new_epoch, "deletion_scope": _scope(request.selector), "counts": counts, "reason_recorded": False}, now=now)
                    remaining = {
                        "counts": counts, "affected_backups": cl.backups, "deleted_backups": [], "external_copy_ids": cl.exports, "backup": {"state": "pending", "backup_id": None},
                        "reconstruct": [{"claim_id": i, "events": roots} for (k, i), roots in sorted(cl.quarantined.items()) if k == "claim"],
                        "scratch_pending": pending, "coverage": _coverage(cl),
                    }
                    txn.execute(
                        "INSERT INTO privacy_operations (privacy_operation_id, phase, remaining, new_epoch, status, created_at, updated_at) VALUES (?, 'purged', ?, ?, 'running', ?, ?)",
                        (op_id, canonical_json(remaining).decode(), new_epoch, now, now),
                    )
                    failpoints.hit(failpoints.FORGET_BEFORE_COMMIT)
            except BaseException:
                with store.read() as view:
                    committed = _op_row(view, op_id) is not None
                if not committed and not had_marker:
                    clear_marker(ctx)
                raise
            failpoints.hit(failpoints.FORGET_AFTER_COMMIT)
            return _run_phases(ctx, store, op_id, now=now)
    finally:
        if own:
            store.close()


def _resume_unfinished(ctx: InstallationContext, store: Store, *, now: str, skip: str | None = None) -> list[ForgetResult]:
    with store.read() as view:
        rows = [r[0] for r in view.execute("SELECT privacy_operation_id FROM privacy_operations WHERE status != 'completed' ORDER BY created_at, privacy_operation_id").fetchall()]
    return [_run_phases(ctx, store, op_id, now=now) for op_id in rows if op_id != skip]


def resume(store: Store, ctx: InstallationContext, *, now: str) -> dict[str, Any]:
    """The worker's privacy step (every poll): finish persisted forget phases, drop a stale marker. Never blocks."""
    lock = _PrivacyLock(ctx.root)
    if not lock.acquire(0):
        return {}  # an operator command is running maintenance now
    try:
        did: dict[str, Any] = {}
        finished = _resume_unfinished(ctx, store, now=now)
        if finished:
            did["privacy_operations"] = [r.purge_state for r in finished]
        had = os.path.exists(session.maintenance_path(ctx.root))
        _release_marker(ctx, store)  # the lock is free, so whoever wrote a marker is gone or finished
        if had and not os.path.exists(session.maintenance_path(ctx.root)):
            did["maintenance_released"] = True
        return did
    finally:
        lock.release()


def pending_operations(q: Any) -> int:
    return q.execute("SELECT COUNT(*) FROM privacy_operations WHERE status != 'completed'").fetchone()[0]


# --------------------------------------------------------------------------
# Restore


def _ledgers(ctx: InstallationContext, verified: Any) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Every tombstone known anywhere (the backup's ledger, the live store's, the latest copy) and the live meta."""
    from recalith.storage import backup

    merged: dict[str, dict[str, Any]] = {t["tombstone_id"]: t for t in verified.ledger["tombstones"]}
    live: dict[str, Any] | None = None
    path = Path(ctx.root) / ".recalith" / STATE_DB
    if path.exists():
        try:
            with open_store(ctx, readonly=True) as store, store.read() as view:
                ledger = backup.ledger_of(view)
                meta = view.execute("SELECT store_revision, guidance_epoch, tombstone_epoch FROM installation_meta WHERE singleton = 1").fetchone()
                backups = view.execute("SELECT backup_id, manifest, tombstone_epoch, state, created_at, location, manifest_digest, bytes FROM backups").fetchall()
                privacy = view.execute("SELECT privacy_operation_id, phase, remaining, new_epoch, status, created_at, updated_at FROM privacy_operations").fetchall()
                audits = view.execute(
                    "SELECT operation_id, job_id, proposal_id, atomic_group_id, actor, kind, inputs, changed, reason, causal_root, store_revision, created_at, local_ref, proposal_digest FROM operations WHERE kind IN (?, ?)",
                    (FORGET_KIND, RESTORE_KIND),
                ).fetchall()
            live = {"store_revision": meta[0], "guidance_epoch": meta[1], "tombstone_epoch": meta[2], "backups": backups, "privacy": privacy, "audits": audits}
            for t in ledger["tombstones"]:
                merged.setdefault(t["tombstone_id"], t)
        except RecalithError:
            live = None  # an unreadable live store: the latest ledger copy still suppresses
    latest = backup.read_latest_ledger(ctx.root)
    if latest is not None and latest.get("project_id") == ctx.project_id and latest.get("installation_id") == ctx.installation_id:
        for t in latest.get("tombstones") or []:
            merged.setdefault(t["tombstone_id"], t)
        if live is None:
            live = {"store_revision": latest.get("store_revision", 0), "guidance_epoch": 0, "tombstone_epoch": latest.get("tombstone_epoch", 0), "backups": None, "privacy": None}
        else:
            live["tombstone_epoch"] = max(live["tombstone_epoch"], latest.get("tombstone_epoch", 0))
    return sorted(merged.values(), key=lambda t: (t["epoch"], t["tombstone_id"])), live


def _write_journal(ctx: InstallationContext, data: dict[str, Any]) -> None:
    path = Path(ctx.root) / RESTORE_JOURNAL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    try:
        os.write(fd, canonical_json(data))
        spool.full_fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    spool.fsync_dir(path.parent)


def _read_journal(root: Path | str) -> dict[str, Any] | None:
    try:
        return json.loads((Path(root) / RESTORE_JOURNAL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def restore_pending(root: Path | str) -> bool:
    return (Path(root) / RESTORE_JOURNAL).exists()


def _sidecars(path: Path) -> list[Path]:
    return [path.with_name(path.name + s) for s in ("-wal", "-shm", "-journal")]


def _unlink_db(path: Path) -> None:
    for p in (path, path.with_name(path.name + ".partial"), *_sidecars(path)):
        p.unlink(missing_ok=True)


def _quiesce_live(live: Path) -> None:
    """Fold the live WAL into its file and make sure no sidecar could be applied to the replacement."""
    if live.exists():
        try:
            conn = sqlite3.connect(live.resolve().as_uri() + "?mode=rw", uri=True, timeout=1)
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                conn.close()
        except sqlite3.Error as exc:
            raise RecalithError("storage_failure", f"the live store could not be quiesced for the restore: {type(exc).__name__}") from exc
    wal = live.with_name(live.name + "-wal")
    if wal.exists() and wal.stat().st_size > 0:
        raise RecalithError("storage_failure", "the live store is still in use (its WAL is not empty); stop every reader and retry the restore")
    for sidecar in _sidecars(live):
        sidecar.unlink(missing_ok=True)


def _replace_file(source: Path, target: Path) -> None:
    for attempt in range(5):
        try:
            os.replace(source, target)
            break
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))
    spool.fsync_dir(target.parent)


def _finish_restore(ctx: InstallationContext, journal: dict[str, Any]) -> dict[str, Any]:
    """After the swap (idempotent): file cleanup, the latest ledger, the forgetting policy for recorded backups."""
    from recalith.storage import backup

    with open_store(ctx) as store:
        clean_files(ctx, store)
        backup._refresh_ledger(ctx, store)  # noqa: SLF001
        with store.read() as view:
            events, record_ids = _purged_ids(view)
            epoch = view.execute("SELECT tombstone_epoch FROM installation_meta WHERE singleton = 1").fetchone()[0]
            stale = [bid for bid in _affected_backups(view, events, record_ids)
                     if view.execute("SELECT tombstone_epoch FROM backups WHERE backup_id = ?", (bid,)).fetchone()[0] < epoch]
        remaining = {"affected_backups": stale, "deleted_backups": []}
        _phase_delete(ctx, store, remaining)
        store.checkpoint()
    (Path(ctx.root) / RESTORE_JOURNAL).unlink(missing_ok=True)
    with open_store(ctx, readonly=True) as store:
        _release_marker(ctx, store)
    return {"deleted_backups": remaining["deleted_backups"]}


def _swap(ctx: InstallationContext, journal: dict[str, Any]) -> None:
    live = Path(ctx.root) / ".recalith" / STATE_DB
    staged = Path(journal["staged"])
    if staged.exists():
        _quiesce_live(live)
        _replace_file(staged, live)
    journal["phase"] = "swapped"
    _write_journal(ctx, journal)


def recover_restore(ctx: InstallationContext) -> dict[str, Any]:
    """Finish or discard an interrupted restore (before anything opens the live store). Needs no worker running."""
    journal = _read_journal(ctx.root)
    if journal is None:
        return {}
    lock = _PrivacyLock(ctx.root)
    if not lock.acquire(0):
        return {}
    try:
        journal = _read_journal(ctx.root)
        if journal is None:
            return {}
        if journal.get("phase") == "staging":
            _unlink_db(Path(journal["staged"]))  # an incomplete staged store never serves
            (Path(ctx.root) / RESTORE_JOURNAL).unlink(missing_ok=True)
            live = Path(ctx.root) / ".recalith" / STATE_DB
            if live.exists():
                with open_store(ctx, readonly=True) as store:
                    _release_marker(ctx, store)
            return {"restore": "discarded"}
        if journal.get("phase") == "staged":
            _swap(ctx, journal)
        done = _finish_restore(ctx, journal)
        return {"restore": "completed", **done}
    finally:
        lock.release()


def _stop_worker(ctx: InstallationContext, wait: float) -> process_env.InstallationLock:
    from recalith.controller import worker as worker_module

    root = str(ctx.root)
    asked = process_env.worker_running(root)
    if asked:
        worker_module.request_stop(root)
    lock = process_env.InstallationLock(root)
    give_up = time.monotonic() + wait
    while not lock.try_acquire():
        if time.monotonic() >= give_up:
            if asked:
                (Path(process_env.run_dir(root)) / worker_module.STOP_FILE).unlink(missing_ok=True)  # no stop request outlives the refusal
            raise RecalithError("capability_unavailable", "restore needs exclusive maintenance: the worker did not stop; stop it and retry")
        time.sleep(0.1)
    return lock


def restore(ctx: InstallationContext, source: Path, *, expected_digest: str, now: str | None = None, stop_wait: float = WORKER_STOP_SECONDS) -> RestoreResult:
    """DATA_CONTRACTS §11: verify, then restore under exclusive maintenance with every newer tombstone applied first."""
    from recalith.storage import backup

    now = now or utc_now()
    verified = backup.verify(Path(source), expected_digest=expected_digest, ctx=ctx)
    if verified.manifest.installation_id != ctx.installation_id:
        raise backup.BackupInvalid("backup_foreign_installation")
    restore_id = derived_id("frg", ["restore", ctx.installation_id, verified.manifest_digest, now])
    with _exclusive(ctx, wait=LOCK_WAIT_SECONDS):
        installation = _stop_worker(ctx, stop_wait)
        try:
            recover_restore_locked = _read_journal(ctx.root)
            if recover_restore_locked is not None:
                raise RecalithError("capability_unavailable", "an interrupted restore is still journaled; the worker's next start finishes it")
            live_path = Path(ctx.root) / ".recalith" / STATE_DB
            if live_path.exists():
                with open_store(ctx) as live_store:
                    _resume_unfinished(ctx, live_store, now=now)  # a forget in progress finishes first
            tombstones, live = _ledgers(ctx, verified)
            write_marker(ctx, kind=RESTORE_KIND, operation_id=restore_id)
            staged = live_path.with_name(f"restore-{restore_id[4:20]}.sqlite")
            journal = {"restore_id": restore_id, "staged": str(staged), "phase": "staging", "manifest_digest": verified.manifest_digest, "created_at": now}
            _write_journal(ctx, journal)
            try:
                result = _stage(ctx, verified, Path(source), staged, tombstones, live, restore_id=restore_id, now=now)
            except BaseException:
                _unlink_db(staged)
                (Path(ctx.root) / RESTORE_JOURNAL).unlink(missing_ok=True)
                if live_path.exists():
                    with open_store(ctx, readonly=True) as live_store:
                        _release_marker(ctx, live_store)
                else:
                    clear_marker(ctx)
                raise
            journal["phase"] = "staged"
            _write_journal(ctx, journal)
            failpoints.hit(failpoints.RESTORE_BEFORE_SWAP)
            _swap(ctx, journal)
            failpoints.hit(failpoints.RESTORE_AFTER_SWAP)
            done = _finish_restore(ctx, journal)
        finally:
            installation.release()
    recorded = {str(Path(r[5]).resolve()) for r in (live or {}).get("backups") or [] if r[5]}
    limits = [*LIMITS]
    if result["suppressed"] and str(Path(source).resolve()) not in recorded:
        limits.insert(0, "external_copy_holds_suppressed_content")
    return RestoreResult(
        applied_schema=SCHEMA_VERSION, restored_revision=result["restored_revision"], preserved_tombstone_epoch=result["epoch"],
        suppressed_record_count=result["suppressed"], source_contains_suppressed=result["suppressed"] > 0, deleted_backup_ids=done["deleted_backups"], limits=limits,
    )


def _stage(ctx: InstallationContext, verified: Any, source: Path, staged: Path, tombstones: list[dict[str, Any]], live: dict[str, Any] | None, *, restore_id: str, now: str) -> dict[str, Any]:
    """Suppress the verified snapshot in memory (every newer tombstone, one transaction), then write it beside the live store.

    Nothing a tombstone covers is ever written to disk: the snapshot's bytes
    are hashed and deserialized into memory, purged there, and only the
    suppressed copy reaches the staged file.
    """
    from recalith.storage import backup

    conn = backup.load_verified_snapshot(source, verified)
    store = Store(ctx, conn, readonly=False)
    try:
        with _write(store) as txn:
            snapshot = {r[0] for r in txn.execute("SELECT tombstone_id FROM tombstones").fetchall()}
            snapshot_revision = txn.meta.store_revision
            # The restored store continues past the live store's revisions and epochs: no fence or cache can match old state.
            epoch = max([txn.meta.tombstone_epoch, *(t["epoch"] for t in tombstones), (live or {}).get("tombstone_epoch", 0)])
            store_revision = max(txn.meta.store_revision, (live or {}).get("store_revision", 0))
            guidance = max(txn.meta.guidance_epoch, (live or {}).get("guidance_epoch", 0))
            txn.execute("UPDATE installation_meta SET tombstone_epoch = ?, store_revision = ?, guidance_epoch = ? WHERE singleton = 1", (epoch, store_revision, guidance))
            txn.meta = dataclasses.replace(txn.meta, store_revision=store_revision, guidance_epoch=guidance, tombstone_epoch=epoch)
            missing = [t for t in tombstones if t["tombstone_id"] not in snapshot]
            for t in missing:
                _tombstone(txn, t["tombstone_id"], t["epoch"], t["target_ids"], t.get("source_digests") or [], t["deletion_scope"], t["created_at"])
            targets = {target for t in missing for target in t["target_ids"]}
            seed_events = {r for r in targets if r.startswith("evt_")}
            stored = set()
            for chunk in _chunks(sorted(seed_events)):
                stored |= {r[0] for r in txn.execute(f"SELECT event_id FROM events WHERE event_id IN ({_marks(chunk)})", tuple(chunk)).fetchall()}  # noqa: S608
            seed_records = {(_kind_of(r), r) for r in targets if not r.startswith("evt_") and _kind_of(r) is not None and records.head(txn, _kind_of(r), r) is not None}
            cl = compute_closure(txn, ctx, stored, seed_records)  # type: ignore[arg-type]
            counts = purge(txn, ctx, cl, now=now) if (cl.events or cl.records) else {}
            if live is not None and live.get("backups") is not None:
                txn.execute("DELETE FROM backups")
                for row in live["backups"]:
                    txn.execute("INSERT INTO backups (backup_id, manifest, tombstone_epoch, state, created_at, location, manifest_digest, bytes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)
            if live is not None and live.get("privacy") is not None:
                for row in live["privacy"]:
                    txn.execute("INSERT OR REPLACE INTO privacy_operations (privacy_operation_id, phase, remaining, new_epoch, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", row)
            for row in (live or {}).get("audits") or []:  # the content-free forget/restore audits stay with the store
                txn.execute(
                    "INSERT OR IGNORE INTO operations (operation_id, job_id, proposal_id, atomic_group_id, actor, kind, inputs, changed, reason, causal_root, store_revision, created_at, local_ref, proposal_digest) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row,
                )
            txn.execute("UPDATE privacy_operations SET status = 'completed', phase = 'completed' WHERE status != 'completed'")  # re-applied here
            _reset_projections(txn)
            txn.execute("UPDATE retention_state SET ledger_epoch = -1 WHERE singleton = 1")
            reconstruct = [{"claim_id": i, "events": roots} for (k, i), roots in sorted(cl.quarantined.items()) if k == "claim"]
            _audit(txn, ctx, kind=RESTORE_KIND, key=restore_id, inputs={
                "backup_id": verified.manifest.artifact_id, "manifest_digest": verified.manifest_digest, "restored_revision": snapshot_revision,
                "tombstones_applied": len(missing), "counts": counts, "tombstone_epoch": epoch,
            }, now=now)
            from recalith.controller import jobs

            for item in reconstruct:
                refs = [_ref("event", e, 1) for e in item["events"]]
                if refs:
                    jobs.enqueue(txn, kind="extract_claims", input_refs=refs, now=now, prompt_version=prompts.CURRENT["extract_claims"], idempotency=digest_of(["reconstruct", item["claim_id"], epoch]))
            txn.mutated(serving_relevant=True)
            failpoints.hit(failpoints.RESTORE_BEFORE_COMMIT)
        partial = staged.with_name(staged.name + ".partial")
        _unlink_db(partial)
        backup.write_database(conn, partial)
        _replace_file(partial, staged)
    finally:
        store.close()
    failpoints.hit(failpoints.RESTORE_AFTER_STAGE)
    return {"restored_revision": snapshot_revision, "epoch": epoch, "suppressed": len(cl.events) + len(cl.records)}


def _reset_projections(txn: Txn) -> None:
    """The restored projections are rebuilt from the authoritative heads after the swap."""
    from recalith.retrieval import lookup

    txn.execute("DELETE FROM context_views")
    lookup.reset(txn)
    txn.execute("DELETE FROM lexical_index")
    txn.execute("DELETE FROM retrieval_docs")
    if txn.one("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'lexical_fts'") is not None:
        txn.execute("DELETE FROM lexical_fts")
        txn.execute("INSERT INTO lexical_fts (lexical_fts) VALUES ('optimize')")
    txn.execute("DELETE FROM projection_state")


__all__ = [
    "preview_forget", "apply_forget", "restore", "resume", "recover_restore", "restore_pending", "clean_files", "purge", "compute_closure", "closure_for",
    "write_marker", "clear_marker", "maintenance_marker", "pending_operations", "Closure", "LIMITS", "RESTORE_JOURNAL",
]
