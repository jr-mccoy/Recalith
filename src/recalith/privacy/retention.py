"""Evidence retention with live pins (SYSTEM_SPEC §11; DATA_CONTRACTS §8, §10–§11; decision 0016).

**Pins.** A payload is pinned while a live owner needs it: a current
``candidate``/``active``/``disputed`` claim head, an ``active``/``paused`` task
head that is not a linked placeholder (its revision's evidence and its open
working range with the calls and results that range pairs), and an ``open``
episode head. The pin is the owner's whole evidence chain
(:func:`pins`): every ``evidence_links`` row of the owner's current revision
(supports, contradictions and context), each link's named roots, every record
revision a link cites (an archived intermediary claim or a settled episode still
preserves what a live claim needs), every event's derivation parents and roots,
and the subagent results a forwarding result relays. Unfinished work is owed its
inputs too: events not yet reduced or examined by the failure debounce, the
inputs of unfinished jobs, the observations of pending rechecks and the failure
events of undebounced failure triggers. Pinning is
retention only: it never changes authority, strength, freshness or
``last_supported_at``, and several owners share one payload.

**Expiry** (:func:`sweep`). An available payload strictly older than its
window by capture time (``recorded_at``: 180 days unpinned in preview,
``delivery_metadata`` days for delivery receipts; the installation's
``RetentionConfig`` decides, so an operator override wins over the profile
default) expires: the payload is dropped, ``payload_state`` becomes
``expired``, the envelope's metadata stays, and the bodies of source conflicts
about it go with it. Candidates are selected in a read snapshot, then the pin
closure is recomputed **inside the expiry transaction** and every candidate
rechecked there (``repinned`` when a concurrent reference won). SQLite
serializes writers, so a new reference either commits first and pins the
payload, or fails admission afterwards against the expired source
(``controller.admission.check_link``: ``evidence_unavailable`` anywhere on the
chain). The transaction writes a content-free ``retention_expiry`` audit and
advances the guidance epoch (expiry is serving-relevant: views are republished,
fallback rows and packets already omit unavailable evidence). Releasing the
last owner makes an already-old payload eligible at the next sweep, without
another window. Delivery metadata (receipt rows and their outcome links) and the
bodies of terminal jobs' proposals age out in the same pass as bookkeeping.

**Lost support** (:func:`support_lost`). Retention alone never lowers a claim:
pinned evidence never expires. When support is actually gone (the forgetting
override below, or an undo reactivating a claim over expired support), the
claim is downgraded in the same transaction: strength from the support that is
still available (never raised), ``evidence_availability`` ``expired`` (or
``redacted`` for forgotten evidence) when nothing is left, freshness
``needs_revalidation`` with a ``support_lost`` recheck, a coalesced
revalidation job and the guidance epoch advanced.

**Forgetting override** (:func:`release_payloads`). Task 16's forgetting calls
this inside its own transaction: it drops payloads whatever pins them and
downgrades what lost support. Tombstones, derivative purge, quarantine and
cleanup of files are Task 16.

**Derived revision bodies** (:func:`age_records`, decision 0020). A completed
or abandoned task's revision bodies age once its closure is strictly older
than ``closed_task_history`` (90 days); a settled or archived episode's once
its task's closure is strictly older than ``episode_after_closure`` (180
days). A revision a live owner or unfinished work cites (a record node of the
pin closure) is kept. Aging empties the body, removes that revision's
evidence links and projection rows, keeps the head and its status, writes a
content-free ``retention_record_aging`` audit and advances the guidance epoch,
in its own transaction with the pins recomputed there.

**Exact capsules** (full profile only, decision 0025). After the expiry pass,
a full store's sweep compacts the pinned payloads past the window that a
capsule can keep exactly (:mod:`recalith.privacy.capsules`): capsule, link
redirection and payload removal in one transaction with the pins recomputed
there, and a content-free ``retention_capsule`` audit. A payload that cannot
be kept exactly stays pinned and is reported with its reason. A capsule-only
event expires like a payload once no live owner needs it: its capsule goes and
its redirected links revert. Preview never compacts.

**Storage growth** is reported, never bounded by pins: :func:`summary` gives
the ``RetentionSummary`` (pinned and unpinned payload bytes, live owners, free
disk, and the pinned payloads past their window still held in full: those a
full-profile capsule could not or did not yet compact).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from recalith.contracts.common import EvidenceLink, InstallationContext, RecordRef, canonical_json, derived_id, digest_of, format_utc, parse_utc, utc_now
from recalith.contracts.config import ProjectConfig, RetentionConfig
from recalith.contracts.health import RetentionSummary
from recalith.core import lineage
from recalith.fast import failpoints
from recalith.privacy import capsules
from recalith.storage import records
from recalith.storage.db import STATE_DB, Store, Txn

LIVE_CLAIMS = ("candidate", "active", "disputed")
LIVE_TASKS = ("active", "paused")
TERMINAL_JOBS = ("completed", "failed", "cancelled")
DELIVERY_EVENT_KINDS = ("memory_delivered",)
SWEEP_INTERVAL_SECONDS = 3600
SWEEP_LIMIT = 4096  # candidates one sweep handles; more stay due for the next poll
AUDIT_IDS = 256
STRENGTH_ORDER = {"weak": 0, "supported": 1, "corroborated": 2}
SCRATCH_IDLE_SECONDS = 24 * 3600
EXPIRY_KIND = "retention_expiry"
SUPPORT_LOST_KIND = "support_lost"
RELEASE_KIND = "payload_release"
RECORD_AGING_KIND = "retention_record_aging"
CLOSED_TASKS = ("completed", "abandoned")
AGEABLE_EPISODES = ("settled", "archived")
_IN = 400


def _chunks(items: Sequence[Any]) -> Iterable[Sequence[Any]]:
    for i in range(0, len(items), _IN):
        yield items[i : i + _IN]


def _minus(moment: str, days: int) -> str:
    return format_utc(parse_utc(moment) - _dt.timedelta(days=days))


def retention_config(ctx: InstallationContext) -> RetentionConfig:
    from recalith.core.identity import installation_config

    return installation_config(Path(ctx.root)).retention  # the store's profile decides the defaults (decision 0026)


# --------------------------------------------------------------------------
# Pins


@dataclass
class Pins:
    """What the live owners and the unfinished work need, as of one snapshot."""

    owned: set[str] = field(default_factory=set)  # events in live owners' evidence chains
    owed: set[str] = field(default_factory=set)  # events unfinished work still needs
    owners: int = 0
    records: set[tuple[str, str, int]] = field(default_factory=set)  # record revisions either closure visits (kept from body aging)
    working: set[str] = field(default_factory=set)  # events live tasks (with their open ranges) and open episodes reach
    claim_records: set[tuple[str, str, int]] = field(default_factory=set)  # record revisions the live claims' closures visit
    owed_payloads: set[str] = field(default_factory=set)  # owed events whose full payload unfinished work reads (not through a claim input)

    @property
    def events(self) -> set[str]:
        return self.owned | self.owed


def _owners(q: Any) -> list[tuple[str, str, int]]:
    claims = q.execute(f"SELECT 'claim', claim_id, revision FROM claim_heads WHERE status IN ({','.join('?' for _ in LIVE_CLAIMS)})", LIVE_CLAIMS).fetchall()  # noqa: S608
    tasks = q.execute(f"SELECT 'task', task_id, revision FROM task_heads WHERE status IN ({','.join('?' for _ in LIVE_TASKS)}) AND redirect_task_id IS NULL", LIVE_TASKS).fetchall()  # noqa: S608
    episodes = q.execute("SELECT 'episode', episode_id, revision FROM episode_heads WHERE state = 'open'").fetchall()
    return [tuple(r) for r in (*claims, *tasks, *episodes)]


def _open_range(q: Any, task_id: str) -> list[str]:
    """A live task's open working range (events not yet in an episode) and the calls/results it pairs."""
    from recalith.working import bindings

    start = bindings.task_book(q, task_id)["open_from"]
    if start is None:
        return []
    out = [r[0] for r in q.execute("SELECT event_id FROM task_binding_heads WHERE task_id = ? AND commit_sequence >= ?", (task_id, start)).fetchall()]
    for a, b in q.execute(
        "SELECT t.start_event_id, t.finish_event_id FROM tool_calls t JOIN task_binding_heads h ON h.event_id IN (t.start_event_id, t.finish_event_id) WHERE h.task_id = ? AND h.commit_sequence >= ?",
        (task_id, start),
    ).fetchall():
        out += [e for e in (a, b) if e]
    return out


class _Closure:
    """Breadth-first evidence closure with a visited set (cycle-safe, no depth bound: a pin is never guessed)."""

    def __init__(self, q: Any) -> None:
        self.q = q
        self.events: set[str] = set()
        self.records: set[tuple[str, str, int]] = set()
        self._seen: set[tuple] = set()
        self._queue: list[tuple] = []

    def add_event(self, event_id: str) -> None:
        self._push(("event", event_id))

    def add_record(self, kind: str, record_id: str, revision: int) -> None:
        self._push((kind, record_id, revision))

    def add_ref(self, ref: dict[str, Any]) -> None:
        kind = ref.get("kind")
        if kind == "event":
            self.add_event(ref["id"])
        elif kind == "capsule":
            origin = capsules.origin_event(self.q, ref["id"])
            if origin is not None:
                self.add_event(origin)  # a redirected link still pins its capsule-only event
        elif kind in records.REVISION_TABLES:
            self.add_record(kind, ref["id"], int(ref.get("revision") or 1))

    def _push(self, node: tuple) -> None:
        if node not in self._seen:
            self._seen.add(node)
            self._queue.append(node)

    def run(self) -> set[str]:
        while self._queue:
            node = self._queue.pop()
            if node[0] == "event":
                self._event(node[1])
            else:
                self.records.add(node)
                self._record(*node)
        return self.events

    def _event(self, event_id: str) -> None:
        row = self.q.execute("SELECT envelope, kind, payload_state FROM events WHERE event_id = ?", (event_id,)).fetchone()
        if row is None:
            return
        self.events.add(event_id)
        envelope = json.loads(row[0])
        for parent in envelope.get("derived_from") or []:
            if isinstance(parent, dict):
                self.add_ref(parent)
        for root in envelope.get("root_event_ids") or []:
            if isinstance(root, str):
                self.add_event(root)
        if row[1] == "tool_finished" and row[2] == "available":
            for forwarded in lineage.forwarded_events(self.q, event_id):
                self.add_event(forwarded)

    def _record(self, kind: str, record_id: str, revision: int) -> None:
        for target_kind, target_id, target_revision, roots in self.q.execute(
            "SELECT target_kind, target_id, target_revision, root_event_ids FROM evidence_links WHERE owner_kind = ? AND owner_id = ? AND owner_revision = ?",
            (kind, record_id, revision),
        ).fetchall():
            self.add_ref({"kind": target_kind, "id": target_id, "revision": target_revision})
            for root in json.loads(roots or "[]"):
                self.add_event(root)


def pins(q: Any) -> Pins:
    """The pin closure of every live owner and of unfinished work, read in ``q``'s snapshot or transaction."""
    out = Pins()
    owners = _owners(q)
    out.owners = len(owners)
    claimed = _Closure(q)
    working = _Closure(q)  # open working context (decision 0025: never compacted)
    for kind, record_id, revision in owners:
        (claimed if kind == "claim" else working).add_record(kind, record_id, revision)
        if kind == "task":
            for event_id in _open_range(q, record_id):
                working.add_event(event_id)
    out.working = working.run()
    out.owned = claimed.run() | out.working
    out.claim_records = set(claimed.records)
    owed = _Closure(q)
    # A job whose input is a claim reads what that claim cites, which an exact capsule keeps and its request carries
    # (decision 0025): owed for expiry, but not a payload compaction must keep whole.
    claim_inputs = _Closure(q)
    cursor = owed_cursor(q)
    for (event_id,) in q.execute("SELECT event_id FROM events WHERE commit_sequence > ?", (cursor,)).fetchall():
        owed.add_event(event_id)
    for (body,) in q.execute(f"SELECT body FROM jobs WHERE state NOT IN ({','.join('?' for _ in TERMINAL_JOBS)})", TERMINAL_JOBS).fetchall():  # noqa: S608
        for ref in json.loads(body).get("input_refs") or []:
            (claim_inputs if ref.get("kind") == "claim" else owed).add_ref(ref)
    for (event_id,) in q.execute(
        f"SELECT r.event_id FROM claim_rechecks r JOIN claim_heads h ON h.claim_id = r.claim_id WHERE r.state IN ('pending', 'deferred') AND r.event_id IS NOT NULL AND h.status IN ({','.join('?' for _ in LIVE_CLAIMS)})",  # noqa: S608
        LIVE_CLAIMS,
    ).fetchall():
        owed.add_event(event_id)
    for (event_id,) in q.execute("SELECT failure_event_id FROM failure_triggers WHERE state IN ('pending', 'due')").fetchall():
        owed.add_event(event_id)  # an undebounced failure is read when its extraction comes due
    out.owed_payloads = owed.run()
    out.owed = out.owed_payloads | claim_inputs.run()
    out.claim_records |= claim_inputs.records
    out.records = claimed.records | working.records | owed.records | claim_inputs.records
    return out


def pinned_events(q: Any) -> set[str]:
    """Every event a live owner or unfinished work needs (what no age sweep may expire)."""
    return pins(q).events


def owed_cursor(q: Any) -> int:
    """Events after this commit sequence are not yet reduced or examined by the failure debounce."""
    reduced = q.execute("SELECT commit_sequence FROM working_cursor WHERE singleton = 1").fetchone()
    examined = q.execute("SELECT commit_sequence FROM trigger_cursor WHERE singleton = 1").fetchone()
    return min(reduced[0] if reduced else 0, examined[0] if examined else 0)


# --------------------------------------------------------------------------
# Reports


@dataclass
class Report:
    """One sweep's outcome (content-free; the IDs are installation-local identifiers)."""

    now: str
    cutoff: str
    delivery_cutoff: str
    expired: list[str] = field(default_factory=list)
    repinned: list[str] = field(default_factory=list)
    pinned_count: int = 0
    owed_count: int = 0
    downgraded: list[str] = field(default_factory=list)
    deliveries_removed: int = 0
    outcome_links_removed: int = 0
    proposals_trimmed: int = 0
    conflicts_trimmed: int = 0
    truncated: bool = False
    records_aged: dict[str, int] = field(default_factory=lambda: {"task": 0, "episode": 0})
    compacted: list[str] = field(default_factory=list)  # events now capsule-only (full profile)
    compaction_deferred: dict[str, int] = field(default_factory=dict)  # reason -> pinned payloads kept in full
    compaction_reasons: dict[str, str] = field(default_factory=dict)  # event -> why its pin was kept (not in the recorded report)
    links_redirected: int = 0
    summary: RetentionSummary | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "now": self.now, "cutoff": self.cutoff, "delivery_cutoff": self.delivery_cutoff, "expired_count": len(self.expired), "repinned_count": len(self.repinned),
            "pinned_count": self.pinned_count, "owed_count": self.owed_count, "downgraded_count": len(self.downgraded), "deliveries_removed": self.deliveries_removed,
            "outcome_links_removed": self.outcome_links_removed, "proposals_trimmed": self.proposals_trimmed, "conflicts_trimmed": self.conflicts_trimmed,
            "truncated": self.truncated, "records_aged": dict(self.records_aged), "compacted_count": len(self.compacted),
            "compaction_deferred": dict(sorted(self.compaction_deferred.items())), "links_redirected": self.links_redirected,
            "summary": self.summary.model_dump(mode="json") if self.summary is not None else None,
        }


def summary(q: Any, ctx: InstallationContext, *, now: str, config: RetentionConfig, pinned: Pins | None = None) -> RetentionSummary:
    """Measured payload storage: pinned versus unpinned bytes, live owners, free disk, pinned payloads past their window."""
    found = pinned or pins(q)
    keep = found.events
    cutoff = _minus(now, config.unpinned_event_payload.days)
    pinned_bytes = unpinned_bytes = past = 0
    for event_id, size, recorded_at in q.execute("SELECT event_id, length(CAST(payload AS BLOB)), recorded_at FROM events WHERE payload_state = 'available' AND payload IS NOT NULL").fetchall():
        if event_id in keep:
            pinned_bytes += size or 0
            past += recorded_at < cutoff
        else:
            unpinned_bytes += size or 0
    try:
        free: int | None = shutil.disk_usage(Path(ctx.root) / ".recalith" / STATE_DB.parent).free
    except OSError:
        free = None  # unavailable, never unlimited
    return RetentionSummary(pinned_payload_bytes=pinned_bytes, unpinned_payload_bytes=unpinned_bytes, live_owner_count=found.owners, free_disk_bytes=free, deferred_compaction_count=past)


# --------------------------------------------------------------------------
# The sweep


def _eligible(q: Any, *, cutoff: str, delivery_cutoff: str, cursor: int, limit: int) -> list[str]:
    marks = ",".join("?" for _ in DELIVERY_EVENT_KINDS)
    rows = q.execute(
        f"SELECT event_id FROM events WHERE ((payload_state = 'available' AND payload IS NOT NULL) OR payload_state = 'capsule_only') AND commit_sequence <= ? "  # noqa: S608
        f"AND ((kind IN ({marks}) AND recorded_at < ?) OR (kind NOT IN ({marks}) AND recorded_at < ?)) ORDER BY commit_sequence LIMIT ?",
        (cursor, *DELIVERY_EVENT_KINDS, delivery_cutoff, *DELIVERY_EVENT_KINDS, cutoff, limit),
    ).fetchall()
    return [r[0] for r in rows]


def sweep(store: Store, ctx: InstallationContext, *, now: str | None = None, config: RetentionConfig | None = None, limit: int = SWEEP_LIMIT) -> Report:
    """One bounded retention pass: expire eligible unpinned payloads, age out delivery metadata and proposal bodies."""
    now = now or utc_now()
    config = config or retention_config(ctx)
    report = Report(now=now, cutoff=_minus(now, config.unpinned_event_payload.days), delivery_cutoff=_minus(now, config.delivery_metadata.days))
    # Candidates in a read snapshot (cheap); the pins decided here are only a prefilter.
    with store.read() as view:
        cursor = owed_cursor(view)
        found = _eligible(view, cutoff=report.cutoff, delivery_cutoff=report.delivery_cutoff, cursor=cursor, limit=limit + 1)
        report.truncated = len(found) > limit
        found = found[:limit]
        pinned = pins(view)
        prefilter = pinned.events
        # Aging takes the write lock only when something can age; the transaction recomputes pins and candidates.
        ageing = bool(aging_candidates(view, now, config, pinned.records))
        full = view.execute("SELECT release_profile FROM installation_meta WHERE singleton = 1").fetchone()[0] == "full"
        compactable = _compactable(view, cutoff=report.cutoff, cursor=cursor, pinned=prefilter, limit=limit + 1) if full else []
        report.truncated = report.truncated or len(compactable) > limit
        compactable = compactable[:limit]
    candidates = [e for e in found if e not in prefilter]
    failpoints.hit(failpoints.RETENTION_AFTER_SELECT)
    if candidates:
        with store.transaction() as txn:
            _expire(txn, ctx, candidates, report)
            failpoints.hit(failpoints.RETENTION_BEFORE_COMMIT)
        failpoints.hit(failpoints.RETENTION_AFTER_COMMIT)
    if compactable:
        failpoints.hit(failpoints.CAPSULE_AFTER_PLAN)
        with store.transaction() as txn:
            _compact(txn, ctx, compactable, report)
            failpoints.hit(failpoints.CAPSULE_BEFORE_COMMIT)
        failpoints.hit(failpoints.CAPSULE_AFTER_COMMIT)
    if ageing:
        with store.transaction() as txn:
            age_records(txn, ctx, report, config)
    failpoints.hit(failpoints.RETENTION_AFTER_RECORD_AGING)
    with store.transaction() as txn:
        _bookkeeping(txn, report)
        report.downgraded = [r.id for r in reconcile(txn, ctx, None, now=now)]
    with store.read() as view:
        current = pins(view)
        report.pinned_count, report.owed_count = len(current.owned), len(current.owed - current.owned)
        report.summary = summary(view, ctx, now=now, config=config, pinned=current)
    return report


def _expire(txn: Txn, ctx: InstallationContext, candidates: Sequence[str], report: Report) -> None:
    """Inside the expiry transaction: the pin closure is recomputed and every candidate rechecked here."""
    current = pins(txn)
    cursor = owed_cursor(txn)
    keep = current.events
    expired: list[str] = []
    for chunk in _chunks(list(candidates)):
        marks = ",".join("?" for _ in chunk)
        rows = txn.execute(f"SELECT event_id, kind, recorded_at, commit_sequence, payload_state FROM events WHERE event_id IN ({marks})", tuple(chunk)).fetchall()  # noqa: S608
        for event_id, kind, recorded_at, seq, state in rows:
            limit = report.delivery_cutoff if kind in DELIVERY_EVENT_KINDS else report.cutoff
            if state not in ("available", "capsule_only") or recorded_at >= limit or seq > cursor:
                continue
            if event_id in keep:
                report.repinned.append(event_id)  # a reference committed since selection: it pins the payload first
                continue
            expired.append(event_id)
    if not expired:
        return
    for chunk in _chunks(expired):
        marks = ",".join("?" for _ in chunk)
        txn.execute(f"UPDATE events SET payload = NULL, payload_state = 'expired' WHERE payload_state IN ('available', 'capsule_only') AND event_id IN ({marks})", tuple(chunk))  # noqa: S608
        cur = txn.execute(f"UPDATE source_conflicts SET scrubbed_payload = NULL WHERE scrubbed_payload IS NOT NULL AND original_event_id IN ({marks})", tuple(chunk))  # noqa: S608
        report.conflicts_trimmed += cur.rowcount
    capsules.drop(txn, expired)  # a released capsule-only event: its capsule goes, its redirected links revert
    report.expired = sorted(expired)
    _audit(txn, ctx, kind=EXPIRY_KIND, key=[report.now, report.expired], inputs={
        "expired_count": len(expired), "cutoff": report.cutoff, "delivery_cutoff": report.delivery_cutoff, "repinned_count": len(report.repinned),
        "pinned_count": len(current.owned), "owed_count": len(current.owed - current.owned), **_ids(report.expired),
    }, reason="age retention of unpinned payloads", now=report.now)
    txn.mutated(serving_relevant=True)  # evidence expiry is serving-relevant (DATA_CONTRACTS §11)
    txn.purged()  # an authorized retention purge (full profile: a purge chain entry, decision 0024)


# --------------------------------------------------------------------------
# Exact capsules (full profile, decision 0025)


def _compactable(q: Any, *, cutoff: str, cursor: int, pinned: set[str], limit: int) -> list[str]:
    """Pinned available payloads past the window (a prefilter in a read snapshot; the transaction rechecks all)."""
    rows = q.execute(
        "SELECT event_id FROM events WHERE payload_state = 'available' AND payload IS NOT NULL AND commit_sequence <= ? AND recorded_at < ? ORDER BY commit_sequence",
        (cursor, cutoff),
    ).fetchall()
    return [r[0] for r in rows if r[0] in pinned][:limit]


def _compact(txn: Txn, ctx: InstallationContext, candidates: Sequence[str], report: Report) -> None:
    """Inside the compaction transaction: pins recomputed here, then each candidate becomes an exact capsule or keeps its pin."""
    current = pins(txn)
    out = capsules.compact(
        txn, candidates, owed=current.owed_payloads, working=current.working, claim_records=current.claim_records, keep=current.events,
        cutoff=report.cutoff, cursor=owed_cursor(txn),
    )
    report.compacted = sorted(out.compacted)
    report.links_redirected = len(out.redirected)
    for reason, n in out.deferred.items():
        report.compaction_deferred[reason] = report.compaction_deferred.get(reason, 0) + n
    report.compaction_reasons.update(out.deferred_events)
    if not out.compacted:
        return
    _audit(txn, ctx, kind=capsules.KIND, key=[report.now, report.compacted], inputs={
        "capsule_count": len(out.compacted), "links_redirected": len(out.redirected), "deferred": dict(sorted(out.deferred.items())), "cutoff": report.cutoff,
        **_ids(report.compacted), "capsule_ids": sorted(out.capsule_ids)[:AUDIT_IDS], "redirected_link_ids": sorted(out.redirected)[:AUDIT_IDS],
    }, reason="exact capsules replace pinned payloads past the window", now=report.now)
    txn.mutated(serving_relevant=True)  # rendering changes (capsule-only evidence, quoted spans)
    txn.purged()  # payload removal is an authorized retention purge (decision 0024)


# --------------------------------------------------------------------------
# Derived revision bodies


def closed_at(q: Any, task_id: str) -> str | None:
    """When the task's current closed streak began: the closing revision's time (its body, else its operation); None when unknown."""
    closing = None
    for _revision, status, body, store_revision in q.execute("SELECT revision, status, body, created_store_revision FROM task_revisions WHERE task_id = ? ORDER BY revision DESC", (task_id,)).fetchall():
        if status not in CLOSED_TASKS:
            break
        closing = (body, store_revision)
    if closing is None:
        return None
    body, store_revision = closing
    if body is not None:
        moment = json.loads(body).get("updated_at")
        if moment:
            return moment
    row = q.execute("SELECT MIN(created_at) FROM operations WHERE store_revision = ?", (store_revision,)).fetchone()
    return row[0] if row else None


def _age_record(txn: Txn, kind: str, record_id: str, keep: set[tuple[str, str, int]], backend: str | None) -> int:
    from recalith.retrieval import index

    table, key = records.REVISION_TABLES[kind]
    head_revision = records.head(txn, kind, record_id)[0]
    aged = 0
    head_aged = False
    for (revision,) in txn.execute(f"SELECT revision FROM {table} WHERE {key} = ? AND body IS NOT NULL ORDER BY revision", (record_id,)).fetchall():  # noqa: S608 - fixed names
        if (kind, record_id, revision) in keep:
            continue
        txn.execute(f"UPDATE {table} SET body = NULL WHERE {key} = ? AND revision = ?", (record_id, revision))  # noqa: S608
        txn.execute("DELETE FROM evidence_links WHERE owner_kind = ? AND owner_id = ? AND owner_revision = ?", (kind, record_id, revision))
        aged += 1
        head_aged = head_aged or revision == head_revision
    if head_aged and backend is not None:
        index._remove(txn, kind, record_id, backend)  # noqa: SLF001 - the projection's own row removal
    return aged


def aging_candidates(q: Any, now: str, config: RetentionConfig, keep: set[tuple[str, str, int]]) -> list[tuple[str, str]]:
    """Closed tasks and settled/archived episodes past their cutoff that still hold an unpinned revision body."""
    from recalith.working import tasks

    task_cut = _minus(now, config.closed_task_history.days)
    episode_cut = _minus(now, config.episode_after_closure.days)
    out: list[tuple[str, str]] = []
    closure: dict[str, str | None] = {}
    for task_id, _revision in q.execute(f"SELECT task_id, revision FROM task_heads WHERE status IN ({','.join('?' for _ in CLOSED_TASKS)})", CLOSED_TASKS).fetchall():  # noqa: S608
        closure[task_id] = when = closed_at(q, task_id)
        if when is not None and when < task_cut and _unpinned_body(q, "task", task_id, keep):
            out.append(("task", task_id))
    for episode_id, task_id in q.execute(f"SELECT episode_id, task_id FROM episode_heads WHERE state IN ({','.join('?' for _ in AGEABLE_EPISODES)})", AGEABLE_EPISODES).fetchall():  # noqa: S608
        owner = tasks.resolve_task(q, task_id) or task_id
        if owner not in closure:
            continue  # the task is not closed (or redirects to an open one): its episodes stay
        when = closure[owner]
        if when is not None and when < episode_cut and _unpinned_body(q, "episode", episode_id, keep):
            out.append(("episode", episode_id))
    return out


def _unpinned_body(q: Any, kind: str, record_id: str, keep: set[tuple[str, str, int]]) -> bool:
    table, key = records.REVISION_TABLES[kind]
    return any((kind, record_id, revision) not in keep for (revision,) in q.execute(f"SELECT revision FROM {table} WHERE {key} = ? AND body IS NOT NULL", (record_id,)).fetchall())  # noqa: S608 - fixed names


def age_records(txn: Txn, ctx: InstallationContext, report: Report, config: RetentionConfig) -> None:
    """Inside one transaction: age closed tasks' history and their episodes' bodies, never a pinned revision."""
    from recalith.retrieval import index

    task_cut = _minus(report.now, config.closed_task_history.days)
    episode_cut = _minus(report.now, config.episode_after_closure.days)
    keep = pins(txn).records
    state = index.state(txn)
    backend = state["backend"] if state is not None else None
    aged: dict[str, list[str]] = {"task": [], "episode": []}
    for kind, record_id in aging_candidates(txn, report.now, config, keep):
        n = _age_record(txn, kind, record_id, keep, backend)
        if n:
            aged[kind].append(record_id)
            report.records_aged[kind] += n
    if not aged["task"] and not aged["episode"]:
        return
    txn.execute("DELETE FROM context_views")
    txn.execute("UPDATE projection_state SET views_store_revision = -1, views_guidance_epoch = -1, views_policy_revision = -1, views_tombstone_epoch = -1")
    if txn.one("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'lexical_fts'") is not None:
        txn.execute("INSERT INTO lexical_fts (lexical_fts) VALUES ('optimize')")
    _audit(txn, ctx, kind=RECORD_AGING_KIND, key=[report.now, aged["task"], aged["episode"]], inputs={
        "task_ids": aged["task"][:AUDIT_IDS], "episode_ids": aged["episode"][:AUDIT_IDS], "task_cutoff": task_cut, "episode_cutoff": episode_cut,
        "revisions": dict(report.records_aged), "pinned_records": len(keep),
    }, reason="age retention of derived revision bodies", now=report.now)
    txn.mutated(serving_relevant=True)
    txn.purged()


def _ids(event_ids: Sequence[str]) -> dict[str, Any]:
    if len(event_ids) <= AUDIT_IDS:
        return {"event_ids": list(event_ids)}
    return {"event_ids_digest": digest_of(list(event_ids))}


def _audit(txn: Txn, ctx: InstallationContext, *, kind: str, key: Any, inputs: dict[str, Any], reason: str, now: str, changed: list[dict[str, Any]] | None = None) -> str:
    oid = derived_id("op", [kind, key])
    txn.execute(
        "INSERT OR IGNORE INTO operations (operation_id, job_id, proposal_id, atomic_group_id, actor, kind, inputs, changed, reason, causal_root, store_revision, created_at, local_ref, proposal_digest) "
        "VALUES (?, NULL, NULL, NULL, ?, ?, ?, ?, ?, NULL, ?, ?, ?, NULL)",
        (oid, canonical_json(ctx.actor).decode(), kind, canonical_json(inputs).decode(), canonical_json(changed or []).decode(), reason, txn.next_store_revision, now, f"@{kind}"),
    )
    return oid


def _bookkeeping(txn: Txn, report: Report) -> None:
    """Delivery metadata and terminal jobs' proposal bodies age out; bodies of conflicts about gone payloads go too."""
    rows = [r[0] for r in txn.execute("SELECT delivery_id FROM deliveries WHERE generated_at < ?", (report.delivery_cutoff,)).fetchall()]
    for chunk in _chunks(rows):
        marks = ",".join("?" for _ in chunk)
        report.outcome_links_removed += txn.execute(f"DELETE FROM outcome_links WHERE delivery_id IN ({marks})", tuple(chunk)).rowcount  # noqa: S608
        report.deliveries_removed += txn.execute(f"DELETE FROM deliveries WHERE delivery_id IN ({marks})", tuple(chunk)).rowcount  # noqa: S608
    terminal = ",".join("?" for _ in TERMINAL_JOBS)
    report.proposals_trimmed = txn.execute(
        f"UPDATE proposals SET body = NULL WHERE body IS NOT NULL AND retention_after IS NOT NULL AND retention_after < ? AND job_id IN (SELECT job_id FROM jobs WHERE state IN ({terminal}))",  # noqa: S608
        (report.now, *TERMINAL_JOBS),
    ).rowcount
    report.conflicts_trimmed += txn.execute(
        "UPDATE source_conflicts SET scrubbed_payload = NULL WHERE scrubbed_payload IS NOT NULL AND original_event_id IN (SELECT event_id FROM events WHERE payload_state IN ('expired', 'forgotten'))"
    ).rowcount
    if report.deliveries_removed or report.proposals_trimmed or report.conflicts_trimmed:
        txn.mutated(serving_relevant=False)  # bookkeeping: receipts and proposals are not guidance
        txn.purged()


# --------------------------------------------------------------------------
# Lost support (honest downgrade) and the forgetting override


def _lost_label(txn: Txn, links: Sequence[EvidenceLink]) -> str:
    events: set[str] = set()
    for link in links:
        found, _lost = lineage.support_events(txn, link)
        events |= found
    for chunk in _chunks(sorted(events)):
        marks = ",".join("?" for _ in chunk)
        if txn.one(f"SELECT 1 FROM events WHERE payload_state = 'forgotten' AND event_id IN ({marks})", tuple(chunk)) is not None:  # noqa: S608
            return "redacted"
    return "expired"


def support_lost(txn: Txn, ctx: InstallationContext, claim_ids: Iterable[str], *, now: str, cause: str = "support_lost") -> list[RecordRef]:
    """Downgrade live claims whose required evidence is no longer available, in the caller's transaction.

    Returns the claims marked (downgraded guidance and deferred candidates).
    Nothing changes for a claim whose whole chain is available.
    """
    from recalith.controller import admission, revalidate

    marked: list[str] = []
    for claim_id in sorted(set(claim_ids)):
        head = records.head(txn, "claim", claim_id)
        if head is None or head[1] not in LIVE_CLAIMS:
            continue
        data = records.body(txn, "claim", claim_id, head[0])
        if data is None:
            continue
        links = [EvidenceLink.model_validate(item) for item in data.get("supports") or []]
        gone = [link for link in links if not lineage.chain_available(txn, link)]
        if not gone:
            continue
        lost_events: set[str] = set()
        for link in gone:
            lost_events |= lineage.support_events(txn, link)[0]
        key = digest_of(sorted(lost_events))
        if head[1] != "candidate":
            left = [link for link in links if link not in gone]
            new = dict(data)
            new["evidence_availability"] = "available" if left else _lost_label(txn, gone)
            capped = admission.assign_strength(txn, {**data, "supports": [link.model_dump(mode="json") for link in left]})
            new["strength"] = min(data["strength"], capped, key=STRENGTH_ORDER.__getitem__)
            new["freshness"] = "needs_revalidation"
            if new.get("review_due_at") is None or new["review_due_at"] > now:
                new["review_due_at"] = now
            if any(new[k] != data[k] for k in ("evidence_availability", "strength", "freshness", "review_due_at")):
                ref = revalidate._write(txn, new, now=now)  # noqa: SLF001 - the revision writer rechecks use
                _audit(txn, ctx, kind=SUPPORT_LOST_KIND, key=[claim_id, head[0], key], inputs={"claim_id": claim_id, "cause": cause, "lost_links": len(gone), "left_links": len(left)},
                       reason="required evidence is no longer available", now=now, changed=[{"ref": ref.model_dump(mode="json"), "before": head[0]}])
                txn.mutated(serving_relevant=True)
        marked += revalidate.mark(txn, ctx, claim_id, reason="support_lost", key=key, event_id=None, detail={"cause": cause, "lost_event_count": len(lost_events)}, context=None, now=now, causal_root=None)
    if marked:
        revalidate.enqueue(txn, [c for c in marked if revalidate.model_pending(txn, c)], now=now)
    out = []
    for claim_id in sorted(set(marked)):
        head = records.head(txn, "claim", claim_id)
        if head is not None:
            out.append(RecordRef(kind="claim", id=claim_id, revision=head[0]))
    return out


def reconcile(txn: Txn, ctx: InstallationContext, claim_ids: Iterable[str] | None, *, now: str) -> list[RecordRef]:
    """Guidance still labeled available over support that is gone (e.g. reactivated by an undo) is downgraded.

    ``claim_ids`` None checks every live claim whose head still says available.
    """
    if claim_ids is None:
        rows = txn.execute("SELECT h.claim_id, r.body FROM claim_heads h JOIN claim_revisions r ON r.claim_id = h.claim_id AND r.revision = h.revision WHERE h.status IN ('active', 'disputed')").fetchall()
        claim_ids = [cid for cid, body in rows if body is not None and json.loads(body).get("evidence_availability") == "available"]
    return support_lost(txn, ctx, claim_ids, now=now, cause="reconciled")


def release_payloads(txn: Txn, ctx: InstallationContext, event_ids: Iterable[str], *, now: str, state: str = "forgotten") -> list[RecordRef]:
    """Forgetting overrides pins: drop these payloads whatever needs them; lost support is downgraded here.

    Task 16's ``apply_forget`` calls this inside its purge transaction (the
    tombstones, derivative purge and quarantine are its own). Returns the claims
    that lost support.
    """
    if state not in ("forgotten", "expired"):
        raise ValueError("payloads are released as forgotten or expired")
    ids = sorted(set(event_ids))
    if not ids:
        return []
    # Who needs them, before they are gone (the closure walks forwarding through available payloads).
    affected: list[str] = []
    for claim_id, revision in txn.execute(f"SELECT claim_id, revision FROM claim_heads WHERE status IN ({','.join('?' for _ in LIVE_CLAIMS)})", LIVE_CLAIMS).fetchall():  # noqa: S608
        closure = _Closure(txn)
        closure.add_record("claim", claim_id, revision)
        if closure.run() & set(ids):
            affected.append(claim_id)
    released = 0
    for chunk in _chunks(ids):
        marks = ",".join("?" for _ in chunk)
        released += txn.execute(f"UPDATE events SET payload = NULL, payload_state = ? WHERE payload_state != ? AND event_id IN ({marks})", (state, state, *chunk)).rowcount  # noqa: S608
        txn.execute(f"UPDATE source_conflicts SET scrubbed_payload = NULL WHERE original_event_id IN ({marks})", tuple(chunk))  # noqa: S608
    capsules.drop(txn, ids)  # forgetting reaches capsules: deleted, their links back to the (released) event
    _audit(txn, ctx, kind=RELEASE_KIND, key=[now, ids, state], inputs={"released_count": released, "state": state, **_ids(ids)}, reason="forgetting overrides pins", now=now)
    txn.mutated(serving_relevant=True)
    txn.purged()
    return support_lost(txn, ctx, affected, now=now, cause=state)


# --------------------------------------------------------------------------
# Session scratch


def prune_scratch(store: Store, ctx: InstallationContext, *, wall: float | None = None, config: RetentionConfig | None = None) -> dict[str, int]:
    """Abandoned session scratch (idle 24 h): owed receipts are settled through the spool first, then the file goes.

    A scratch whose receipts cannot be settled (no hook context, a spool
    failure) is kept until the delivery-metadata window has passed, then
    dropped and counted. Ages are file times against wall time.
    """
    from recalith.fast import delivery, entry, session

    wall = time.time() if wall is None else wall
    config = config or retention_config(ctx)
    directory = Path(session.sessions_dir(ctx.root))
    out = {"settled": 0, "pruned": 0, "unsettled_dropped": 0, "kept": 0}
    try:
        names = sorted(n for n in os.listdir(directory) if n.endswith(".json"))
    except OSError:
        return out
    for name in names:
        path = directory / name
        try:
            idle = wall - path.stat().st_mtime
        except OSError:
            continue
        if idle <= SCRATCH_IDLE_SECONDS:
            continue
        session_id = name[: -len(".json")]
        scratch = session.read_scratch(ctx.root, session_id)
        if scratch is not None and session.owes_receipts(scratch):
            with store.read() as view:
                row = view.execute("SELECT adapter_id, host_session_id FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            status = "unsettled"
            if row is not None:
                try:
                    hook_ctx = entry.load_context(str(ctx.root), row[0])
                    status = delivery.settle(hook_ctx, session_id, row[1], deadline=time.monotonic() + 5.0)
                except Exception:  # noqa: BLE001 - not integrated or unreadable: the receipts stay owed
                    status = "unsettled"
            if status == "settled":
                out["settled"] += 1
            elif idle > config.delivery_metadata.days * 86400:
                out["unsettled_dropped"] += 1
            else:
                out["kept"] += 1
                continue
        try:
            path.unlink()
            out["pruned"] += 1
        except OSError:
            continue
    return out


# --------------------------------------------------------------------------
# The worker's retention step


def _due(swept_at: str | None, now: str) -> bool:
    if swept_at is None:
        return True
    seconds = (parse_utc(now) - parse_utc(swept_at)).total_seconds()
    return seconds >= SWEEP_INTERVAL_SECONDS or seconds < 0


def run(store: Store, ctx: InstallationContext, config: ProjectConfig, *, now: str) -> dict[str, Any]:
    """The worker's deterministic retention step (no model, no budget). Returns what it changed (empty: nothing).

    Every poll: finish an interrupted backup and refresh the latest ledger copy
    when the tombstone epoch moved. At most hourly (or at once while a sweep
    was truncated): the sweep, bounded backup retention and abandoned scratch.
    The sweep time is recorded last, so a crash anywhere before it repeats the
    (idempotent) steps.
    """
    from recalith.storage import backup

    did: dict[str, Any] = {}
    recovered = backup.recover(ctx, store)
    if recovered:
        did["backups_recovered"] = len(recovered)
    with store.read() as view:
        swept_at, ledger_epoch = view.execute("SELECT swept_at, ledger_epoch FROM retention_state WHERE singleton = 1").fetchone()
        epoch = view.execute("SELECT tombstone_epoch FROM installation_meta WHERE singleton = 1").fetchone()[0]
    if ledger_epoch != epoch or backup.read_latest_ledger(ctx.root) is None:
        written = backup.write_latest_ledger(ctx, store)
        with store.transaction() as txn:
            txn.execute("UPDATE retention_state SET ledger_epoch = ? WHERE singleton = 1", (written["tombstone_epoch"],))
        did["ledger_epoch"] = written["tombstone_epoch"]
    if not _due(swept_at, now):
        return did
    report = sweep(store, ctx, now=now, config=config.retention)
    deleted = backup.prune(store, ctx, now=now, days=config.retention.private_backups.days)
    scratch = prune_scratch(store, ctx, config=config.retention)
    data = {**report.as_dict(), "backups_deleted": len(deleted), "scratch": scratch}
    with store.transaction() as txn:
        txn.execute("UPDATE retention_state SET swept_at = ?, report = ? WHERE singleton = 1", (None if report.truncated else now, canonical_json(data).decode()))
    if report.expired or report.compacted or report.downgraded or deleted or report.deliveries_removed or report.proposals_trimmed or scratch["pruned"] or report.truncated:
        did["sweep"] = data
    return did


def last_report(q: Any) -> dict[str, Any]:
    row = q.execute("SELECT swept_at, report FROM retention_state WHERE singleton = 1").fetchone()
    return {"swept_at": row[0], "last_sweep": json.loads(row[1] or "{}")} if row else {"swept_at": None, "last_sweep": {}}
