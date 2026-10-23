"""The preview-to-full profile transition of one installation (SYSTEM_SPEC §10.1; DATA_CONTRACTS §11/§12; decision 0026).

:func:`transition` moves a ``claude_preview`` installation to ``full`` in
place, run by the engine the installation already pins, which must be the
release of the supplied, digest-verified wheel. It never re-runs ``init`` and
never creates an installation ID. The steps:

1. **Refusals before any effect**: an actor other than the operator; a
   full-to-preview request (``policy_refused``: a downgrade is never a flag
   change); a same-profile request (the side-by-side engine switch is not
   built); a store at another schema (``migration_required`` stores need the
   general schema upgrade, not built); a wheel whose name, digest, version or
   pinned artifact does not match this engine.
2. **Exclusive maintenance**: the privacy-maintenance lock (no forget or
   restore runs alongside), the worker stopped (its installation lock held),
   an interrupted forget finished first, the maintenance marker written
   (delivery and model launches paused), the journal ``.recalith/run/upgrade.json``.
3. **A verified backup** with the current tombstone ledger
   (``.recalith/backups/upgrade-…``); without it nothing is staged
   (``not_activated``).
4. **Capability registration**: the target build's capability set (the full
   features this engine builds become eligible; Codex, generic JSON and MCP are
   not activated; the rest are unavailable as not built), the configured
   provider route probed again (version observation included), and the
   delivery paths exactly as their certification stands (never healthy
   because of the transition).
5. **Staging** in memory from a consistent snapshot of the live store: the
   pinned payloads past the *target* unpinned window become exact capsules
   where every live reference is kept exactly, else keep their pins with the
   reasons (decision 0025); then one activation transaction: profile ``full``,
   policy revision and guidance epoch advanced (old read sets and serving
   fences no longer match), the content-free ``profile_transition`` autonomy
   log entry, and the revision chain's activation baseline over the staged
   current rows. Every live claim's evidence must stay available and the
   staged chain must verify over every row; the staged file is written beside
   the live store.
6. **Activation**: the journal says ``activating``; the live store must still
   hold exactly the snapshot's rows (a write since then rolls back); the
   staged file replaces the live store atomically. Recovery then completes
   the tracked ``release_profile`` record, the verifier checkpoint of the
   staged check, the latest ledger copy and the marker.

A crash or failure before the swap leaves the previous complete preview store
serving and is rolled back (staged files removed, marker released). After the
swap the store is the complete full store and recovery completes the rest;
no half-migrated store ever serves. The worker's start runs :func:`recover`
before it opens the store. Forgetting stays possible after a crash (privacy
first): a forget on the preview store before the swap makes the swap's
fence roll the transition back, one after the swap applies to the full store.

``FULL_RELEASE_AVAILABLE`` is false in this build: the guarded CLI and the
service answer ``capability_unavailable`` (like ``init --release-profile full``,
decision 0024) while this function is exercised by the test suite.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tomllib
from pathlib import Path
from typing import Any, Mapping

from recalith import __version__
from recalith.contracts.common import InstallationContext, canonical_json, new_id, utc_now
from recalith.contracts.config import ProjectConfig
from recalith.contracts.transfers import UpgradeResult
from recalith.core import identity, lineage
from recalith.errors import RecalithError
from recalith.fast import failpoints, process_env, spool
from recalith.storage import db, integrity

FULL_RELEASE_AVAILABLE = False  # the full release is not complete in this build (decisions 0024, 0026)
KIND = "profile_transition"
JOURNAL = Path(".recalith") / "run" / "upgrade.json"
LAST_RESULT = Path(".recalith") / "state" / "upgrade.json"
STAGED_PREFIX = "upgrade-"
WHEEL_RE = re.compile(r"^recalith-(?P<version>[0-9][0-9A-Za-z.+!]*)-py3-none-any\.whl$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
PROFILES = ("claude_preview", "full")
NOT_ACTIVATED = ("codex_capture", "codex_delivery", "generic_json", "mcp")  # eligible for explicit configuration only
PHASES = ("fenced", "backed_up", "registered", "staging", "staged", "activating", "activated")
BEFORE_ACTIVATION = PHASES[:5]
FAILED_AT = {"fenced": "backup_failed", "backed_up": "registration_failed", "registered": "staging_failed", "staging": "staging_failed", "staged": "activation_failed", "activating": "activation_failed"}


class _Abort(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# --------------------------------------------------------------------------
# Files


def _write_private(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    try:
        os.write(fd, canonical_json(dict(data)))
        spool.full_fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    spool.fsync_dir(path.parent)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def pending(root: Path | str) -> bool:
    """An interrupted transition is journaled (the worker's start recovers it)."""
    return (Path(root) / JOURNAL).exists()


def journal_phase(root: Path | str) -> str | None:
    journal = _read_json(Path(root) / JOURNAL)
    return journal.get("phase") if journal else ("unreadable" if pending(root) else None)


def last_result(root: Path | str) -> dict[str, Any] | None:
    """The last transition's ``UpgradeResult`` (private ``.recalith/state/upgrade.json``), or None."""
    return _read_json(Path(root) / LAST_RESULT)


def _save(root: Path, journal: dict[str, Any], phase: str) -> None:
    journal["phase"] = phase
    _write_private(root / JOURNAL, journal)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _live(root: Path) -> Path:
    return root / ".recalith" / db.STATE_DB


def _staged_files(root: Path) -> list[Path]:
    return sorted((root / ".recalith" / db.STATE_DB.parent).glob(f"{STAGED_PREFIX}*"))


# --------------------------------------------------------------------------
# Refusals before any effect


def verify_wheel(root: Path, wheel: Path, expected_digest: str) -> dict[str, Any]:
    """The supplied artifact must be this engine's own wheel, digest-verified, and the installation's pinned engine."""
    if not isinstance(expected_digest, str) or not DIGEST_RE.match(expected_digest):
        raise RecalithError("invalid_schema", "--expected-digest must be a lowercase SHA-256 hex digest")
    match = WHEEL_RE.match(wheel.name)
    if not match:
        raise RecalithError("invalid_schema", "--wheel does not name a recalith pure-Python wheel (recalith-VERSION-py3-none-any.whl)")
    if not wheel.is_file():
        raise RecalithError("capability_unavailable", "the wheel file is missing")
    actual = _sha(wheel)
    if actual != expected_digest:
        raise RecalithError("invalid_schema", "the wheel's digest does not match --expected-digest; nothing was changed")
    version = match.group("version")
    if version != __version__:
        raise RecalithError("capability_unavailable", f"the wheel is release {version} and this engine is {__version__}: switching engines side by side is not built (decision 0026); "
                            "run the transition with the engine of the supplied wheel")
    try:
        lock = tomllib.loads((root / ".recalith" / "engine.lock").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        raise RecalithError("capability_unavailable", "the installation's engine.lock is unreadable") from None
    if lock.get("engine_version") != __version__:
        raise RecalithError("capability_unavailable", f"the installation pins engine {lock.get('engine_version')!r}, not {__version__}: switching engines side by side is not built (decision 0026)")
    if lock.get("provisioning") == "wheel":
        provisioned = _read_json(root / ".recalith" / "runtime" / __version__ / "provisioned.json")
        if lock.get("artifact_sha256") != actual or (provisioned is not None and provisioned.get("artifact_sha256") != actual):
            raise RecalithError("capability_unavailable", "the pinned runtime is another artifact than the supplied wheel; provision the wheel with the release bootstrap first")
    return {"version": version, "artifact_sha256": actual, "provisioning": lock.get("provisioning")}


def _meta(ctx: InstallationContext) -> db.Meta:
    conn = db.connect(_live(Path(ctx.root)), readonly=True)
    try:
        meta = db.read_meta(conn)
    finally:
        conn.close()
    if meta.installation_id != ctx.installation_id or meta.project_id != ctx.project_id:
        raise RecalithError("foreign_installation", "the store belongs to another installation")
    return meta


def check_request(ctx: InstallationContext, release_profile: str | None) -> tuple[db.Meta, str, str]:
    """``(meta, source, target)`` or the refusal: downgrade ``policy_refused``; same profile or another schema unavailable."""
    if release_profile is not None and release_profile not in PROFILES:
        raise RecalithError("invalid_schema", "--release-profile is claude_preview or full")
    meta = _meta(ctx)
    source = meta.release_profile
    target = release_profile or source
    if source == "full" and target == "claude_preview":
        raise RecalithError("policy_refused", "full-to-preview is not a supported flag change (no lossy reverse migration); explicit restore remains governed by schema compatibility and the privacy ledger")
    if meta.schema_version != db.SCHEMA_VERSION:
        raise RecalithError("capability_unavailable", f"the store is at schema {meta.schema_version}, not {db.SCHEMA_VERSION}: migrating another schema is the general engine/schema upgrade, which is not built (decision 0026); nothing was changed")
    if source == target:
        raise RecalithError("capability_unavailable", f"the installation already runs the {source} profile: a same-profile engine upgrade (side by side) is not built (decision 0026)")
    return meta, source, target


# --------------------------------------------------------------------------
# The transition


def transition(ctx: InstallationContext, wheel: Path, *, expected_digest: str, release_profile: str | None, now: str | None = None,
               inherited: Mapping[str, str] | None = None, stop_wait: float | None = None) -> UpgradeResult:
    """Transition this installation from ``claude_preview`` to ``full`` (see the module docstring). Operator only."""
    from recalith.privacy import forget

    if ctx.actor.kind != "operator":
        raise RecalithError("policy_refused", "the profile transition is an operator action")
    now = now or utc_now()
    root = Path(ctx.root)
    meta, source, target = check_request(ctx, release_profile)
    artifact = verify_wheel(root, Path(wheel), expected_digest)
    op_id = new_id("op")
    with forget._exclusive(ctx, wait=forget.LOCK_WAIT_SECONDS):  # noqa: SLF001 - the one privacy-maintenance lock
        installation = forget._stop_worker(ctx, forget.WORKER_STOP_SECONDS if stop_wait is None else stop_wait, purpose="the profile transition")  # noqa: SLF001
        try:
            if forget.restore_pending(root):
                raise RecalithError("capability_unavailable", "an interrupted restore is still journaled; the worker's next start finishes it")
            if pending(root):
                _recover_locked(ctx)
                meta, source, target = check_request(ctx, release_profile)
            with db.open_store(ctx) as live:
                forget._resume_unfinished(ctx, live, now=now)  # noqa: SLF001 - a forget in progress finishes first
            config = identity.installation_config(root)
            journal: dict[str, Any] = {
                "journal_schema": 1, "operation_id": op_id, "installation_id": ctx.installation_id, "project_id": ctx.project_id,
                "source_profile": source, "target_profile": target, "source_engine": __version__, "target_engine": __version__,
                "artifact_sha256": artifact["artifact_sha256"], "now": now, "created_at": utc_now(), "backup": None, "error_codes": [],
                "staged": str(root / ".recalith" / db.STATE_DB.parent / f"{STAGED_PREFIX}{op_id[3:19]}.sqlite"),
            }
            forget.write_marker(ctx, kind="upgrade", operation_id=op_id)
            _save(root, journal, "fenced")
            return _run(ctx, journal, config, inherited=inherited)
        finally:
            installation.release()


def _run(ctx: InstallationContext, journal: dict[str, Any], config: ProjectConfig, *, inherited: Mapping[str, str] | None) -> UpgradeResult:
    from recalith.storage import backup

    root = Path(ctx.root)
    location = root / ".recalith" / "backups" / f"upgrade-{journal['operation_id'][3:19]}"
    try:
        with db.open_store(ctx) as live:
            made = backup.create(ctx, location, store=live, now=journal["now"])
    except (RecalithError, OSError, sqlite3.Error) as exc:
        return _rollback(ctx, journal, ["backup_failed", *([exc.code] if isinstance(exc, RecalithError) else [])])
    journal["backup"] = {"backup_id": made.manifest.artifact_id, "location": made.location, "manifest_digest": made.manifest_digest}
    _save(root, journal, "backed_up")
    try:
        failpoints.hit(failpoints.UPGRADE_AFTER_BACKUP)
        journal["capabilities"] = register_capabilities(ctx, inherited=inherited)
        _save(root, journal, "registered")
        failpoints.hit(failpoints.UPGRADE_AFTER_REGISTRATION)
        _save(root, journal, "staging")
        journal.update(_stage(ctx, journal, config))
        _save(root, journal, "staged")
        failpoints.hit(failpoints.UPGRADE_AFTER_STAGE)
        _save(root, journal, "activating")
        failpoints.hit(failpoints.UPGRADE_BEFORE_SWAP)
        _swap(ctx, journal)
    except _Abort as abort:
        return _rollback(ctx, journal, [FAILED_AT.get(journal["phase"], "activation_failed"), abort.code])
    except Exception as exc:  # noqa: BLE001 - every failure before the swap rolls back; the live store was never touched
        if not (journal["phase"] == "activating" and not Path(journal["staged"]).exists() and _activated_here(ctx, journal)):
            return _rollback(ctx, journal, [FAILED_AT.get(journal["phase"], "activation_failed"), *([exc.code] if isinstance(exc, RecalithError) else [])])
        # The rename happened (a later step of the swap failed): the full store serves; complete it below.
    _save(root, journal, "activated")
    try:
        failpoints.hit(failpoints.UPGRADE_AFTER_SWAP)
        return _finish(ctx, journal)
    except Exception as exc:  # noqa: BLE001 - the full store serves; recovery completes the rest
        journal["error_codes"] = ["completion_pending", *([exc.code] if isinstance(exc, RecalithError) else [])]
        _save(root, journal, "activated")
        result = _result(journal, "recovery_required")
        _write_private(root / LAST_RESULT, result.model_dump(mode="json"))
        return result


def register_capabilities(ctx: InstallationContext, *, inherited: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The target build's capability registry: eligible, not activated and unavailable features, the provider probed, delivery as certified.

    Read-only apart from the provider's version observation (a process launch,
    never a model call; outside every transaction). Delivery paths are
    ``certified`` exactly when the installation's health reports them healthy
    from its live certification record; the transition certifies nothing.
    """
    from recalith.contracts.health import DEFERRED_FULL_CAPABILITIES, DELIVERY_CAPABILITY, REQUIRED_CAPABILITIES
    from recalith.operations import health as operations_health
    from recalith.providers import base as provider_base

    env = os.environ if inherited is None else inherited
    root = Path(ctx.root)
    try:
        status = provider_base.route_status(provider_base.load_provider_config(root), installation_id=ctx.installation_id, inherited=env, observe=True)
        provider = {"state": status.state, "reasons": list(status.reasons)[:16], "observed_version": status.observed_version}
    except RecalithError as exc:
        provider = {"state": "unavailable", "reasons": [exc.code], "observed_version": None}
    report = operations_health.health(ctx, inherited=env)
    built = sorted(operations_health.BUILT_FULL_CAPABILITIES)

    def healthy(name: str) -> bool:  # the transition's own maintenance marker is not a property of the capability
        cap = report.capabilities[name]
        return cap.state == "healthy" or set(cap.reason_codes) <= {"maintenance_in_progress"}

    return {
        "registry_schema": 1, "profile": "full", "eligible": built, "not_activated": sorted(NOT_ACTIVATED),
        "unavailable": {name: "not_built_in_this_engine" for name in DEFERRED_FULL_CAPABILITIES if name not in built},
        "provider": provider,
        "delivery": {path: ("certified" if healthy(name) else "unavailable") for path, name in DELIVERY_CAPABILITY.items()},
        "required_ready": all(healthy(name) for name in REQUIRED_CAPABILITIES),
    }


def _evidence(view: Any) -> dict[tuple[str, int], list[bool]]:
    """Every live claim head's support links: is each one's lineage chain available."""
    from recalith.contracts.common import EvidenceLink
    from recalith.storage import records

    out = {}
    for claim_id, revision in view.execute("SELECT claim_id, revision FROM claim_heads WHERE status IN ('candidate', 'active', 'disputed')").fetchall():
        body = records.body(view, "claim", claim_id, revision)
        out[(claim_id, revision)] = [lineage.chain_available(view, EvidenceLink.model_validate(i)) for i in (body or {}).get("supports") or []]
    return out


def _retention_outcome(before: ProjectConfig, after: ProjectConfig) -> dict[str, Any]:
    return {name: {"before": getattr(before.retention, name).model_dump(mode="json"), "after": getattr(after.retention, name).model_dump(mode="json")}
            for name in type(before.retention).model_fields}


def _stage(ctx: InstallationContext, journal: dict[str, Any], config: ProjectConfig) -> dict[str, Any]:
    """Build the full store in memory from a consistent snapshot of the live one and write it beside the live store."""
    from recalith.privacy import forget, retention
    from recalith.storage import backup

    root = Path(ctx.root)
    target = identity.load_project_config(identity.Layout(root), release_profile=journal["target_profile"])
    now = journal["now"]
    source = db.connect(_live(root), readonly=True)
    mem = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    try:
        source.backup(mem)
    finally:
        source.close()
    mem.execute("PRAGMA foreign_keys = ON")
    store = db.Store(ctx, mem, readonly=False)
    try:
        with store.read() as view:
            fingerprint = integrity.content_digest(view)
            before = _evidence(view)
            cursor = retention.owed_cursor(view)
            pinned = retention.pins(view).events
        # Exact capsules or retained pins under the target window (decision 0025), in the staged store only.
        report = retention.Report(now=now, cutoff=retention._minus(now, target.retention.unpinned_event_payload.days),  # noqa: SLF001
                                  delivery_cutoff=retention._minus(now, target.retention.delivery_metadata.days))  # noqa: SLF001
        with store.read() as view:
            candidates = retention._compactable(view, cutoff=report.cutoff, cursor=cursor, pinned=pinned, limit=10**9)  # noqa: SLF001
        if candidates:
            with store.transaction() as txn:
                retention._compact(txn, ctx, candidates, report)  # noqa: SLF001
                failpoints.hit(failpoints.UPGRADE_AFTER_CAPSULES)
        with store.read() as view:
            retained = retention.summary(view, ctx, now=now, config=target.retention).deferred_compaction_count
        compaction = {"compacted_count": len(report.compacted), "links_redirected": report.links_redirected, "deferred": dict(sorted(report.compaction_deferred.items())),
                      "retained_pin_count": retained, "cutoff": report.cutoff}
        # The activation transaction: profile, fences, the autonomy log and the chain's activation baseline (last).
        with store.transaction() as txn:
            revision = txn.meta.store_revision + 1
            txn.execute("UPDATE installation_meta SET release_profile = ?, policy_revision = policy_revision + 1, guidance_epoch = guidance_epoch + 1, store_revision = ? WHERE singleton = 1",
                        (journal["target_profile"], revision))
            policy, guidance = txn.execute("SELECT policy_revision, guidance_epoch FROM installation_meta WHERE singleton = 1").fetchone()
            inputs = {
                "source_profile": journal["source_profile"], "target_profile": journal["target_profile"], "source_engine": journal["source_engine"],
                "target_engine": journal["target_engine"], "artifact_sha256": journal["artifact_sha256"], "backup_id": journal["backup"]["backup_id"],
                "policy_revision": policy, "guidance_epoch": guidance, "retention": _retention_outcome(config, target), "compaction": compaction,
                "capabilities": journal["capabilities"], "pre_baseline_history": "not_chained",
            }
            txn.execute(
                "INSERT INTO operations (operation_id, job_id, proposal_id, atomic_group_id, actor, kind, inputs, changed, reason, causal_root, store_revision, created_at, local_ref, proposal_digest) "
                "VALUES (?, NULL, NULL, NULL, ?, ?, ?, '[]', ?, NULL, ?, ?, ?, NULL)",
                (journal["operation_id"], canonical_json(ctx.actor).decode(), KIND, canonical_json(inputs).decode(),
                 f"profile transition {journal['source_profile']} to {journal['target_profile']}", revision, now, f"@{KIND}"),
            )
            sequence = integrity.establish_baseline(txn, reason="activation")
            failpoints.hit(failpoints.UPGRADE_AFTER_BASELINE)
        with store.read() as view:
            baseline = view.execute("SELECT entry_hash FROM revision_chain WHERE sequence = ?", (sequence,)).fetchone()[0]
            after = _evidence(view)
            if any(was and not after.get(key, [False] * len(links))[i] for key, links in before.items() for i, was in enumerate(links)):
                raise _Abort("evidence_check_failed")  # a capsule or redirect lost a live claim's support: never activate
            check = integrity.verify_view(view)
        if check["state"] != "verified" or not check["complete_coverage"] or check["pre_baseline_history"] != "not_chained":
            raise _Abort("baseline_verification_failed")
        staged = Path(journal["staged"])
        partial = staged.with_name(staged.name + ".partial")
        forget._unlink_db(partial)  # noqa: SLF001
        backup.write_database(mem, partial)
        forget._replace_file(partial, staged)  # noqa: SLF001
    finally:
        store.close()
    return {
        "live_fingerprint": fingerprint, "staged_digest": _sha(staged), "baseline_digest": baseline, "retained_pin_count": retained, "compaction": compaction,
        "check": {k: check[k] for k in ("state", "complete_coverage", "head", "checked_at")},
    }


def _swap(ctx: InstallationContext, journal: dict[str, Any]) -> None:
    """Activation: the staged store replaces the live one, only if the live store still holds exactly the snapshot's rows."""
    from recalith.privacy import forget

    root = Path(ctx.root)
    live, staged = _live(root), Path(journal["staged"])
    if staged.exists():
        conn = db.connect(live, readonly=True)
        try:
            conn.execute("BEGIN")
            fingerprint = integrity.content_digest(conn)
            conn.execute("COMMIT")
        finally:
            conn.close()
        if fingerprint != journal["live_fingerprint"]:
            raise _Abort("store_changed_during_upgrade")  # a write (an operator command, a forget) since the snapshot: stage again
        if _sha(staged) != journal["staged_digest"]:
            raise _Abort("staged_store_damaged")
        forget._quiesce_live(live)  # noqa: SLF001
        forget._replace_file(staged, live)  # noqa: SLF001
        return
    if not _activated_here(ctx, journal):
        raise _Abort("activation_state_unknown")


def _activated_here(ctx: InstallationContext, journal: dict[str, Any]) -> bool:
    try:
        with db.open_store(ctx, readonly=True) as store, store.read() as view:
            profile = view.execute("SELECT release_profile FROM installation_meta WHERE singleton = 1").fetchone()[0]
            row = view.execute("SELECT 1 FROM operations WHERE operation_id = ? AND kind = ?", (journal["operation_id"], KIND)).fetchone()
    except RecalithError:
        return False
    return profile == journal["target_profile"] and row is not None


def _finish(ctx: InstallationContext, journal: dict[str, Any]) -> UpgradeResult:
    """After the swap (idempotent): the tracked profile record, the verifier checkpoint, the ledger copy, the marker."""
    from recalith.privacy import forget
    from recalith.storage import backup

    root = Path(ctx.root)
    with db.open_store(ctx) as store:
        with store.read() as view:
            head = view.execute("SELECT sequence, entry_hash FROM revision_chain ORDER BY sequence DESC LIMIT 1").fetchone()
        integrity.record_checked_head(root, ctx.installation_id, journal["check"], live_head=(head[0], head[1]) if head else None)
        identity.record_profile(identity.Layout(root), journal["target_profile"])
        failpoints.hit(failpoints.UPGRADE_AFTER_RECORD)
        backup._refresh_ledger(ctx, store)  # noqa: SLF001
        store.checkpoint()
    (root / JOURNAL).unlink(missing_ok=True)
    spool.fsync_dir((root / JOURNAL).parent)
    with db.open_store(ctx, readonly=True) as store:
        forget._release_marker(ctx, store)  # noqa: SLF001
    result = _result(journal, "activated")
    _write_private(root / LAST_RESULT, result.model_dump(mode="json"))
    return result


def _rollback(ctx: InstallationContext, journal: dict[str, Any], codes: list[str]) -> UpgradeResult:
    """Before activation (idempotent): the staged files go, the journal goes, the marker is released; the preview store serves."""
    from recalith.privacy import forget

    root = Path(ctx.root)
    for path in _staged_files(root):
        forget._unlink_db(path)  # noqa: SLF001
    (root / JOURNAL).unlink(missing_ok=True)
    spool.fsync_dir((root / JOURNAL).parent)
    if _live(root).exists():
        with db.open_store(ctx, readonly=True) as store:
            forget._release_marker(ctx, store)  # noqa: SLF001
    journal["error_codes"] = list(dict.fromkeys(codes))
    result = _result(journal, "rolled_back" if journal.get("backup") else "not_activated")
    _write_private(root / LAST_RESULT, result.model_dump(mode="json"))
    return result


def _result(journal: dict[str, Any], state: str) -> UpgradeResult:
    active = state in ("activated", "recovery_required")
    return UpgradeResult(
        operation_id=journal["operation_id"], source_profile=journal["source_profile"], target_profile=journal["target_profile"],
        source_engine=journal["source_engine"], target_engine=journal["target_engine"], state=state, preserved_installation_id=journal["installation_id"],
        verified_backup_id=(journal.get("backup") or {}).get("backup_id"), baseline_digest=journal.get("baseline_digest") if active else None,
        retained_pin_count=journal.get("retained_pin_count", 0) if active else 0, error_codes=[c[:64] for c in journal.get("error_codes") or []],
    )


# --------------------------------------------------------------------------
# Recovery


def recover(ctx: InstallationContext, *, held: bool = False) -> dict[str, Any]:
    """Finish or roll back an interrupted transition before anything opens the store; ``{}`` when nothing is journaled.

    ``held``: the caller (the worker) already holds the installation lock;
    otherwise it is taken here, and a running worker (which recovers at its own
    start) or a running transition makes this return ``{}``.
    """
    from recalith.privacy import forget

    root = Path(ctx.root)
    if not pending(root):
        return {}
    lock = forget._PrivacyLock(root)  # noqa: SLF001
    if not lock.acquire(0):
        return {}
    installation = None
    try:
        if not held:
            installation = process_env.InstallationLock(str(root))
            if not installation.try_acquire():
                installation = None
                return {}
        return _recover_locked(ctx)
    finally:
        if installation is not None:
            installation.release()
        lock.release()


def _recover_locked(ctx: InstallationContext) -> dict[str, Any]:
    root = Path(ctx.root)
    journal = _read_json(root / JOURNAL)
    if journal is None:
        if pending(root):
            (root / JOURNAL).unlink(missing_ok=True)  # never completed its first write: nothing was staged or activated
            for path in _staged_files(root):
                path.unlink(missing_ok=True)
        return {}
    phase = journal.get("phase")
    if phase in BEFORE_ACTIVATION:
        result = _rollback(ctx, journal, ["interrupted_before_activation"])
        return {"upgrade": result.state, "result": result.model_dump(mode="json")}
    if phase == "activating":
        try:
            _swap(ctx, journal)
        except _Abort as abort:
            if abort.code == "activation_state_unknown":
                journal["error_codes"] = [abort.code]
                _save(root, journal, "activating")
                result = _result(journal, "recovery_required")
                _write_private(root / LAST_RESULT, result.model_dump(mode="json"))
                return {"upgrade": result.state, "result": result.model_dump(mode="json")}
            result = _rollback(ctx, journal, ["interrupted_before_activation", abort.code])
            return {"upgrade": result.state, "result": result.model_dump(mode="json")}
        _save(root, journal, "activated")
    if not _activated_here(ctx, journal):
        journal["error_codes"] = ["activation_state_unknown"]
        result = _result(journal, "recovery_required")
        _write_private(root / LAST_RESULT, result.model_dump(mode="json"))
        return {"upgrade": result.state, "result": result.model_dump(mode="json")}
    journal["error_codes"] = []
    result = _finish(ctx, journal)
    return {"upgrade": result.state, "result": result.model_dump(mode="json")}


__all__ = ["transition", "recover", "pending", "journal_phase", "last_result", "verify_wheel", "check_request", "register_capabilities", "FULL_RELEASE_AVAILABLE", "KIND", "JOURNAL", "LAST_RESULT"]
