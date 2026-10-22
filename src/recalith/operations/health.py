"""Profile-aware health and readiness of one installation (DATA_CONTRACTS §11, SYSTEM_SPEC §1.2, §15; decision 0018).

``health(ctx)`` composes a :class:`HealthReport` for exactly the resolved
installation it is given: no registry, no daemon, no other project. It is
**read-only**: read-only SQLite snapshots (``mode=ro``, ``query_only``), file
reads and non-creating lock probes; it writes no row and creates no file, and
it launches nothing (no provider or host probe: those are the guarded
``doctor --probe-*`` forms). It is not on the hook path.

Readiness is exactly "every required capability healthy": capture,
inference, admission, recovery, forget, operator guard, and the session-start
and prompt delivery paths. Pre-action and compaction delivery are reported,
never required; every deferred full-release feature is an explicit
``unavailable`` result with its reason, never a pass. ``readiness`` is
``ready``, ``unavailable`` when the store's schema cannot be served by this
engine (migration required, newer, unreadable), else ``degraded``.

Sources, all installation-local:

- the store (schema and epochs, jobs, budgets, conflicts, privacy operations,
  backups, retention pins) when its schema is this engine's;
- ``.recalith/run/hook-context.json`` (the hook manifest: host version,
  installed delivery paths, the registered worker start), judged as the hook
  judges it, root identity included;
- ``.recalith/host.json`` (:class:`HostCertification`), Task 13's record of
  live delivery certification per path, the installed command deny rules and
  the private-path probe; absent until Task 13 runs;
- ``.recalith/provider.json`` through ``providers.base.route_status`` (no
  version observation), or the running worker's own report of its route,
  which reflects its environment and its isolation recheck;
- the worker's lock and status record, the spool, the maintenance marker,
  the restore and backup journals and the latest ledger copy.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tomllib
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from recalith import __version__
from recalith.contracts.common import InstallationContext, parse_utc, utc_now
from recalith.contracts.health import (
    DEFERRED_FULL_CAPABILITIES,
    DELIVERY_CAPABILITY,
    MAX_REPORTED,
    OPTIONAL_CAPABILITIES,
    REQUIRED_CAPABILITIES,
    CapabilityState,
    ConflictEntry,
    HealthReport,
    HostCertification,
    InstallationState,
    PrivacyMaintenance,
    PrivacyOperationState,
)
from recalith.core.identity import Layout, load_project_config
from recalith.errors import RecalithError
from recalith.fast import claude_capture, process_env, session, spool
from recalith.operations import autostart
from recalith.storage import db

HOST_FILE = Path(".recalith") / "host.json"
HOST_FILE_MAX_BYTES = 16 * 1024
INGESTION_DELAY_SECONDS = 600.0
PRIVACY_LOCK = "privacy.lock"  # privacy.forget.PRIVACY_LOCK
RESTORE_JOURNAL = Path(".recalith") / "run" / "restore.json"  # privacy.forget.RESTORE_JOURNAL
BACKUP_JOURNALS = Path(".recalith") / "run" / "backups"  # storage.backup.JOURNAL_DIR
LATEST_LEDGER = Path(".recalith") / "state" / "ledger.json"  # storage.backup.LATEST_LEDGER
MAX_DEGRADED_CODES = 32
DEFERRED_REASONS: dict[str, tuple[str, ...]] = {"revision_chain": ("revision_chain_unavailable_in_preview",)}
GUARD_MARKERS = frozenset((*process_env.HOST_MARKERS, process_env.WORKER_MARKER, process_env.CURATOR_MARKER))


def _code(text: str) -> str:
    """A registered-shape reason code from a route reason such as ``invocation_not_isolated:--x``."""
    out = "".join(c if c.isalnum() or c == "_" else "_" for c in text.lower())[:64].strip("_") or "unknown_reason"
    return out if out[0].isalpha() else f"r_{out}"[:64]


class _Cap:
    """A capability being composed: the worst state wins; reasons accumulate in order."""

    ORDER = {"healthy": 0, "degraded": 1, "unavailable": 2}

    def __init__(self, required: bool) -> None:
        self.state = "healthy"
        self.required = required
        self.reasons: list[str] = []
        self.coverage: dict[str, Any] = {}
        self.certified_version: str | None = None
        self.certified_at: str | None = None

    def flag(self, state: str, *codes: str) -> None:
        if self.ORDER[state] > self.ORDER[self.state]:
            self.state = state
        for code in codes:
            code = _code(code)
            if code not in self.reasons:
                self.reasons.append(code)

    def build(self) -> CapabilityState:
        healthy = self.state == "healthy"
        return CapabilityState(
            state=self.state, required=self.required, reason_codes=list(self.reasons), coverage=self.coverage,
            certified_version=self.certified_version if healthy else None, certified_at=self.certified_at if healthy else None,
        )


# --------------------------------------------------------------------------
# Local records


def load_host_certification(root: Path | str, installation_id: str) -> tuple[str, HostCertification | None]:
    """``(state, record)``: ``absent``, ``invalid`` (malformed, oversized or another installation's) or ``ok``."""
    path = Path(root) / HOST_FILE
    try:
        with open(path, "rb") as fh:
            data = fh.read(HOST_FILE_MAX_BYTES + 1)
    except FileNotFoundError:
        return "absent", None
    except OSError:
        return "invalid", None
    if len(data) > HOST_FILE_MAX_BYTES:
        return "invalid", None
    try:
        record = HostCertification.model_validate_json(data)
    except ValidationError:
        return "invalid", None
    if record.installation_id != installation_id:
        return "invalid", None
    return "ok", record


def pinned_engine(root: Path | str) -> str | None:
    try:
        with open(Layout(Path(root)).engine_lock, "rb") as fh:
            value = tomllib.load(fh).get("engine_version")
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return value if isinstance(value, str) and len(value) <= 128 else None


def _store_meta(ctx: InstallationContext) -> tuple[str, db.Meta | None]:
    """The store's schema state from its metadata alone (``read_meta`` on a read-only connection)."""
    try:
        conn = db.connect(Path(ctx.root) / ".recalith" / db.STATE_DB, readonly=True)
    except RecalithError:
        return "unreadable", None
    try:
        meta = db.read_meta(conn)
    except RecalithError:
        return "unreadable", None
    finally:
        conn.close()
    if meta.installation_id != ctx.installation_id or meta.project_id != ctx.project_id:
        raise RecalithError("foreign_installation", "the store belongs to another installation")
    if meta.schema_version > db.SCHEMA_VERSION:
        return "newer_unsupported", meta
    if meta.schema_version < db.SCHEMA_VERSION:
        return "migration_required", meta
    return "current", meta


SCHEMA_REASON = {"migration_required": "schema_migration_required", "newer_unsupported": "store_schema_newer", "unreadable": "store_unreadable"}


# --------------------------------------------------------------------------
# Store reads (one read snapshot, only for this engine's schema)


def _store_facts(ctx: InstallationContext, *, now: str, deep: bool) -> dict[str, Any]:
    from recalith.controller import budgets, jobs
    from recalith.privacy import retention

    config = load_project_config(Layout(Path(ctx.root)))
    out: dict[str, Any] = {}
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        out["queue"] = jobs.queue_summary(view, now=now)
        out["budget"] = budgets.summary(view, budgets.utc_day(now), config.budgets)
        used, limits = budgets.used_by_pool(view, budgets.utc_day(now)), budgets.pool_limits(config.budgets)
        out["ordinary_blocked"] = isinstance(budgets.plan("update_task", 1, used=used, limits=limits), budgets.Refusal)
        out["review_blocked"] = isinstance(budgets.plan("review_claims", 1, used=used, limits=limits), budgets.Refusal)
        protected = limits["protected"] - used["protected"]
        out["protected_exhausted"] = protected.invocations < 1 or protected.input_estimate < 1 or protected.output_estimate < min(budgets.PURPOSE_OUTPUT_ALLOWANCE[p] for p in budgets.PROTECTED_PURPOSES)
        out["hours_to_exhaustion"] = _hours_to_exhaustion(used, limits, now)
        out["conflict_count"] = view.execute("SELECT COUNT(*) FROM source_conflicts WHERE state = 'unresolved'").fetchone()[0]
        out["conflicts"] = view.execute(
            "SELECT conflict_id, original_event_id, adapter_id, payload_digest, first_seen_at FROM source_conflicts WHERE state = 'unresolved' ORDER BY first_seen_at, conflict_id LIMIT ?", (MAX_REPORTED,)
        ).fetchall()
        out["privacy_ops"] = view.execute(
            "SELECT privacy_operation_id, phase, status FROM privacy_operations WHERE status != 'completed' ORDER BY created_at, privacy_operation_id LIMIT 64"
        ).fetchall()
        out["forget_backups"] = [(op_id, updated, json.loads(remaining or "{}")) for op_id, updated, remaining in view.execute(
            "SELECT privacy_operation_id, updated_at, remaining FROM privacy_operations WHERE status = 'completed' ORDER BY created_at, privacy_operation_id"
        ).fetchall()]
        out["backups"] = view.execute("SELECT COUNT(*), MAX(created_at) FROM backups WHERE state = 'verified'").fetchone()
        out["tombstone_epoch"] = view.execute("SELECT tombstone_epoch FROM installation_meta WHERE singleton = 1").fetchone()[0]
        out["reviews_waiting"] = view.execute("SELECT COUNT(*) FROM jobs WHERE kind IN ('review_claims', 'revalidate') AND state NOT IN ('completed', 'failed', 'cancelled')").fetchone()[0]
        out["retention"] = retention.summary(view, ctx, now=now, config=config.retention)
        out["last_sweep"] = retention.last_report(view)
        out["integrity"] = None
        if deep:
            out["integrity"] = view.execute("PRAGMA quick_check").fetchone()[0]
    return out


def _hours_to_exhaustion(used: Mapping[str, Any], limits: Mapping[str, Any], now: str) -> dict[str, float | None]:
    """Per pool, at today's average rate since UTC midnight, the hours until its first dimension runs out."""
    from recalith.controller import budgets

    moment = parse_utc(now)
    elapsed = (moment - moment.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 3600
    out: dict[str, float | None] = {}
    for pool in budgets.POOLS:
        best: float | None = None
        for dim in budgets.DIMENSIONS:
            spent, left = used[pool].get(dim), (limits[pool] - used[pool]).get(dim)
            if left <= 0:
                best = 0.0
                break
            if spent > 0 and elapsed > 0:
                hours = left / (spent / elapsed)
                best = hours if best is None else min(best, hours)
        out[pool] = None if best is None else round(best, 2)
    return out


# --------------------------------------------------------------------------
# Composition


def health(ctx: InstallationContext, *, inherited: Mapping[str, str] | None = None, now: str | None = None, deep: bool = False) -> HealthReport:
    """DATA_CONTRACTS §11 ``health(ctx) -> HealthReport`` for exactly this installation (read-only).

    ``inherited`` is the environment a route check sees when no worker is
    running (default: this process's); ``deep`` adds the store's
    ``PRAGMA quick_check`` (``doctor``).
    """
    from recalith.providers import base as provider_base

    now = now or utc_now()
    env = os.environ if inherited is None else inherited
    root = Path(ctx.root)
    schema_state, meta = _store_meta(ctx)
    facts: dict[str, Any] = {}
    if schema_state == "current":
        try:
            facts = _store_facts(ctx, now=now, deep=deep)
        except sqlite3.DatabaseError:
            schema_state = "unreadable"  # a malformed page met by health's own reads: reported, never a crash
        except RecalithError as exc:
            if exc.code not in ("storage_failure", "invalid_schema"):
                raise
            schema_state = "unreadable"
    current = schema_state == "current"
    manifest_state, manifest = autostart.read_manifest(root)
    adapter = (manifest or {}).get("adapters", {}).get("claude_code") if manifest_state in ("ok", "relocated") else None
    host_version = adapter.get("host_version") if adapter else None
    host_state, host = load_host_certification(root, ctx.installation_id)
    from recalith.integrations import claude as integration

    installed = integration.installed_state(root)  # None: no `integrate` ran here (a tooling/test manifest)
    broken_hooks = sorted(e for e, st in ((installed or {}).get("hooks") or {}).items() if st != "intact")
    worker = autostart.worker_report(ctx, now=now)
    marker_present = os.path.exists(session.maintenance_path(root))
    gaps: list[str] = []
    caps: dict[str, _Cap] = {name: _Cap(name in REQUIRED_CAPABILITIES) for name in (*REQUIRED_CAPABILITIES, *OPTIONAL_CAPABILITIES, *DEFERRED_FULL_CAPABILITIES)}

    # ---------------------------------------------------------------- capture
    dirs = spool.SpoolDirs(root)
    ready = spool.ready_segments(dirs)
    oldest = min((p.stat().st_mtime for p in ready), default=None)
    oldest_age = None if oldest is None else max(0.0, _wall(now) - oldest)
    capture_gaps: dict[str, int] = {}
    for record in spool.read_gaps(dirs):
        label = f"{record.get('code')}:{record.get('reason')}"
        capture_gaps[label] = capture_gaps.get(label, 0) + int(record.get("event_count") or 1)
    quarantined = sum(1 for _ in dirs.quarantine.iterdir()) if dirs.quarantine.is_dir() else 0
    cap = caps["capture"]
    cap.coverage = {
        "manifest": manifest_state, "host_id": "claude_code", "host_version": host_version, "capture_certified_versions": sorted(claude_capture.CERTIFIED_VERSIONS),
        "transcript_parser": claude_capture.TRANSCRIPT_PARSER, "ready_segments": len(ready), "oldest_ready_age_seconds": oldest_age, "gaps": capture_gaps,
        "quarantined_segments": quarantined, "unresolved_conflicts": facts.get("conflict_count"),
        "integration": None if installed is None else {"state": installed.get("state"), "hooks": installed.get("hooks"), "deny_rules": installed.get("deny_rules")},
        "session_notice": bool(((manifest or {}).get("notices") or {}).get("session_start")),
    }
    if installed is not None and (broken_hooks or installed.get("state") != "installed"):
        cap.flag("degraded", "host_hooks_modified")  # an owned hook entry was edited or removed: some events are not captured
    if manifest_state == "absent":
        cap.flag("unavailable", "host_not_integrated")
    elif manifest_state == "invalid":
        cap.flag("unavailable", "hook_context_invalid")
    elif manifest_state == "relocated":
        cap.flag("unavailable", "hook_context_relocated")
    else:
        if host_version is None:
            cap.flag("degraded", "host_version_unknown")
            gaps.append("host_version_unknown")
        elif host_version not in claude_capture.CERTIFIED_VERSIONS:
            cap.flag("degraded", "host_version_uncertified")  # A47: conservative capture-only mode
            gaps.append(f"host_version_uncertified:{host_version}"[:256])
    if not current:
        cap.flag("degraded", SCHEMA_REASON[schema_state])
    for label, count in sorted(capture_gaps.items()):
        gaps.append(f"capture_gap:{label}:{count}"[:256])
    if quarantined:
        gaps.append("spool_segments_quarantined")
    if facts.get("conflict_count"):
        gaps.append(f"source_conflicts_unresolved:{facts['conflict_count']}")

    # ---------------------------------------------------------------- delivery paths
    delivery_paths = set(adapter.get("delivery_paths") or []) if adapter and adapter.get("delivery_enabled") else set()
    for path, name in DELIVERY_CAPABILITY.items():
        cap = caps[name]
        cap.coverage = {"path": path, "installed": path in delivery_paths, "record": host_state, "record_mode": host.mode if host else None, "record_state": host.delivery[path] if host else None, "host_version": host_version}
        if manifest_state != "ok":
            cap.flag("unavailable", {"absent": "host_not_integrated", "invalid": "hook_context_invalid", "relocated": "hook_context_relocated"}[manifest_state])
        if manifest_state == "ok" and host_version is None:
            cap.flag("unavailable", "host_version_unknown")
        if host_state == "absent":
            cap.flag("unavailable", "delivery_not_certified")
        elif host_state == "invalid":
            cap.flag("unavailable", "host_certification_invalid")
        else:
            assert host is not None
            if host.mode != "live":
                cap.flag("unavailable", "delivery_request_capture_only")
            if host_version is not None and host.host_version != host_version:
                cap.flag("unavailable", "host_version_changed")
            if host.delivery[path] == "failed":
                cap.flag("unavailable", "delivery_path_failed")
            elif host.delivery[path] == "unavailable":
                cap.flag("unavailable", "delivery_path_unavailable")
        if host_version is not None and host_version not in claude_capture.CERTIFIED_VERSIONS:
            cap.flag("unavailable", "host_version_uncertified")  # the hook keeps delivery off for an uncertified version
        if manifest_state == "ok" and path not in delivery_paths:
            cap.flag("unavailable", "delivery_path_not_installed")
        if installed is not None and integration.PATH_EVENTS[path] in broken_hooks:
            cap.flag("unavailable", "host_hooks_modified")
        if not current:
            cap.flag("degraded", SCHEMA_REASON[schema_state])
        if marker_present:
            cap.flag("degraded", "maintenance_in_progress")
        if host is not None:
            cap.certified_version, cap.certified_at = host.host_version, host.certified_at
        if not cap.required and cap.state != "healthy":
            gaps.append(f"optional_delivery_unavailable:{path}")

    # ---------------------------------------------------------------- inference
    cap = caps["inference"]
    route: dict[str, Any]
    if worker["running"] and isinstance(worker.get("provider"), dict) and worker["state"] != "degraded":
        route = dict(worker["provider"], source="worker")
    else:
        try:
            status = provider_base.route_status(provider_base.load_provider_config(root), installation_id=ctx.installation_id, inherited=env, observe=False)
            route = dict(status.report(), source="configuration")
        except RecalithError as exc:
            route = {"state": "unavailable", "reasons": ["provider_config_invalid" if exc.code == "invalid_schema" else exc.code], "source": "configuration"}
    cap.coverage = {k: route.get(k) for k in ("source", "provider_id", "backend", "configured_model", "certified_version", "auth_route", "auth_key_names") if k in route}
    if route.get("state") == "certified":
        cap.certified_version = route.get("certified_version")
        failure = route.get("last_call_failure")
        if isinstance(failure, dict) and isinstance(failure.get("code"), str):
            cap.flag("degraded", failure["code"])  # e.g. endpoint_unreachable, provider_rate_limited (decision 0023)
    elif route.get("state") == "checking":
        cap.flag("degraded", "isolation_recheck_pending")
    else:
        cap.flag("unavailable", *(route.get("reasons") or ["provider_unavailable"]))
    if current and facts["ordinary_blocked"]:
        cap.flag("degraded", "ordinary_budget_exhausted")
    if not current:
        cap.flag("degraded", SCHEMA_REASON[schema_state])
    route_ok = route.get("state") == "certified"

    # ---------------------------------------------------------------- admission
    cap = caps["admission"]
    if not current:
        cap.flag("unavailable", SCHEMA_REASON[schema_state])
    else:
        cap.coverage = {"reviews_waiting": facts["reviews_waiting"]}
        if not route_ok:
            cap.flag("degraded", "review_provider_unavailable")
        if facts["review_blocked"]:
            cap.flag("degraded", "protected_budget_exhausted")

    # ---------------------------------------------------------------- recovery and startup
    cap = caps["recovery"]
    startup = autostart.startup_report(ctx, (manifest_state, manifest))
    pinned = pinned_engine(root)
    journals = sorted(p.name for p in (root / BACKUP_JOURNALS).glob("bkp_*.json")) if (root / BACKUP_JOURNALS).is_dir() else []
    restore_journaled = (root / RESTORE_JOURNAL).exists()
    ledger_epoch = _ledger_epoch(root)
    cap.coverage = {
        "startup": startup, "engine": {"running": __version__, "pinned": pinned},
        "worker": {k: worker[k] for k in ("running", "state", "spawned_by", "method", "independence", "degraded_reasons", "heartbeat_age_seconds", "pid")},
        "restore_journaled": restore_journaled, "backup_journals": len(journals),
        "ledger": {"copy_epoch": ledger_epoch, "store_epoch": facts.get("tombstone_epoch")},
        "backups": {"verified": facts["backups"][0], "latest_verified_at": facts["backups"][1]} if current else None,
        "store_integrity": "not_checked" if not deep or not current else ("ok" if facts["integrity"] == "ok" else "failed"),
    }
    if not current:
        cap.flag("unavailable", SCHEMA_REASON[schema_state])
    if pinned is None:
        cap.flag("degraded", "engine_pin_unreadable")
    elif pinned != __version__:
        cap.flag("degraded", "engine_pin_mismatch")
    if not process_env.locking_supported():
        cap.flag("unavailable", "worker_lock_unsupported")
    if startup["registered_hook_start"] in ("not_registered", "not_integrated", "invalid"):
        cap.flag("degraded", "worker_autostart_not_registered")
    elif startup["registered_hook_start"] == "relocated":
        cap.flag("degraded", "hook_context_relocated")
    if worker["running"]:
        if worker["independence"] not in (None, "detached"):
            cap.flag("degraded", "worker_independence_degraded")
        if "worker_heartbeat_stale" in worker["degraded_reasons"]:
            cap.flag("degraded", "worker_heartbeat_stale")
        if worker["last_error"]:
            cap.flag("degraded", "worker_error")
        if "worker_status_unavailable" in worker["degraded_reasons"]:
            cap.flag("degraded", "worker_status_unavailable")
    if restore_journaled:
        cap.flag("degraded", "restore_recovery_pending")
    if journals:
        cap.flag("degraded", "backup_recovery_pending")
    if current and (ledger_epoch or 0) < facts["tombstone_epoch"]:
        cap.flag("degraded", "ledger_copy_stale")
    if oldest_age is not None and oldest_age > INGESTION_DELAY_SECONDS:
        cap.flag("degraded", "ingestion_delayed")
    if current and deep and facts["integrity"] != "ok":
        cap.flag("unavailable", "store_integrity_check_failed")
    if current and not facts["backups"][0]:
        gaps.append("no_verified_backup")

    # ---------------------------------------------------------------- forget and privacy maintenance
    cap = caps["forget"]
    unfinished = [PrivacyOperationState(operation_id=op, phase=phase, status=status) for op, phase, status in facts.get("privacy_ops", [])]
    scratch_owed = any(o.status == "cleanup_pending" for o in unfinished)
    latest_backup = facts["backups"][1] if current else None
    failed_backup = [op for op, updated, remaining in facts.get("forget_backups", []) if (remaining.get("backup") or {}).get("state") == "unavailable" and (latest_backup is None or latest_backup <= updated)]
    pending_work = bool(unfinished) or restore_journaled or autostart.lock_held(os.path.join(process_env.run_dir(root), PRIVACY_LOCK))
    marker = "absent" if not marker_present else ("active" if pending_work else "stale")
    from recalith.privacy.forget import LIMITS

    pm = PrivacyMaintenance(
        state="pending" if (unfinished or scratch_owed or failed_backup or restore_journaled or marker != "absent") else "idle",
        unfinished_operations=unfinished, scratch_cleanup_pending=scratch_owed, backup_unavailable_after_forget=failed_backup,
        restore_journaled=restore_journaled, maintenance_marker=marker, delivery_paused=marker_present, limits=list(LIMITS),
    )
    cap.coverage = {"limits": list(LIMITS), "tombstone_epoch": facts.get("tombstone_epoch")}
    if not current:
        cap.flag("unavailable", SCHEMA_REASON[schema_state])
    if any(o.status == "running" for o in unfinished) or restore_journaled:
        cap.flag("degraded", "privacy_maintenance_pending")
    if scratch_owed:
        cap.flag("degraded", "scratch_cleanup_pending")
    if failed_backup:
        cap.flag("degraded", "backup_unavailable_after_forget")
    if marker == "stale":
        cap.flag("degraded", "maintenance_marker_stale")

    # ---------------------------------------------------------------- operator guard and host protection
    cap = caps["operator_guard"]
    rules = host.command_rules if host is not None else None
    private = host.private_paths if host is not None else "not_run"
    cap.coverage = {
        "marker_guard": "active", "markers": sorted(GUARD_MARKERS),  # the guard's refusal is exercised by A73 through the real CLI
        "command_deny_rules": "installed" if rules == "installed" and (installed is None or installed.get("deny_rules") == "intact") else "not_installed",
        "owned_deny_rules": None if installed is None else installed.get("deny_rules"),
        "private_paths": {"state": private, "installed_rules": "unavailable_in_preview", "os_level_isolation": False},
        "scope": "same_user_friction",  # markers, terminals, tokens and rules are not an OS security boundary
    }
    if host_state == "invalid":
        cap.flag("degraded", "host_certification_invalid")
    if installed is not None and installed.get("deny_rules") in ("modified", "unknown"):
        cap.flag("degraded", "command_deny_rules_modified")
    elif installed is not None and installed.get("deny_rules") == "not_installed":
        cap.flag("degraded", "command_deny_rules_not_installed")
    elif rules != "installed":
        cap.flag("degraded", "command_deny_rules_uncertified" if installed is not None else "command_deny_rules_not_installed")
    if host is not None and host_version is not None and host.host_version != host_version:
        cap.flag("degraded", "host_version_changed")  # the rules and the probe were observed on another host version
    if private == "not_run":
        cap.flag("degraded", "private_path_probe_not_run")
        gaps.append("private_path_probe_not_run")
    elif private != "probed_supported":
        gaps.append("private_path_protection_limited")

    # ---------------------------------------------------------------- deferred full-release features
    profile = meta.release_profile if meta is not None else load_project_config(Layout(root)).release_profile
    for name in DEFERRED_FULL_CAPABILITIES:
        reasons = ("deferred_full_release", *DEFERRED_REASONS.get(name, ())) if profile == "claude_preview" else ("not_built_in_this_engine",)
        caps[name].flag("unavailable", *reasons)
    gaps.append("revision_chain_unavailable_in_preview")

    # ---------------------------------------------------------------- summaries
    retention_summary = facts.get("retention")
    if retention_summary is None:
        gaps.append("retention_summary_unmeasured")
    elif retention_summary.deferred_compaction_count:
        gaps.append(f"pinned_payloads_past_window:{retention_summary.deferred_compaction_count}")
    budget = dict(facts.get("budget") or {})
    if current:
        budget["exhausted_pools"] = [p for p, blocked in (("ordinary", facts["ordinary_blocked"]), ("protected", facts["protected_exhausted"])) if blocked]
        budget["reviews_blocked"] = facts["review_blocked"]
        budget["hours_to_exhaustion"] = facts["hours_to_exhaustion"]
    if worker["running"]:
        worker_state = worker["state"]
    else:
        worker_state = "stopped"
    if schema_state in ("migration_required", "newer_unsupported"):
        worker_state = "migration_required"
    capabilities = {name: c.build() for name, c in caps.items()}
    ready = all(capabilities[n].state == "healthy" for n in REQUIRED_CAPABILITIES)
    installation = InstallationState(
        project_id=ctx.project_id, installation_id=ctx.installation_id, engine_version=__version__, pinned_engine_version=pinned,
        schema_version=meta.schema_version if meta is not None else None, supported_schema_version=db.SCHEMA_VERSION, schema_state=schema_state,
        store_revision=meta.store_revision if meta is not None else None, tombstone_epoch=meta.tombstone_epoch if meta is not None else None,
    )
    return HealthReport(
        release_profile=profile, capabilities=capabilities, worker_state=worker_state,
        readiness="ready" if ready else ("degraded" if current else "unavailable"), checked_at=now, installation=installation,
        coverage_gaps=list(dict.fromkeys(gaps))[:MAX_REPORTED], job_summary=facts.get("queue") or {}, budget_summary=budget, retention_summary=retention_summary,
        source_conflicts=[ConflictEntry(conflict_id=c, original_event_id=e, adapter_id=a, payload_digest=d, first_seen_at=t) for c, e, a, d, t in facts.get("conflicts", [])],
        source_conflict_count=facts.get("conflict_count") or 0, privacy_maintenance=pm, autonomous_ready=ready,
    )


def _wall(now: str) -> float:
    return parse_utc(now).timestamp()


def _ledger_epoch(root: Path) -> int | None:
    try:
        data = json.loads((root / LATEST_LEDGER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    epoch = data.get("tombstone_epoch") if isinstance(data, dict) else None
    return epoch if isinstance(epoch, int) else None


def degraded_codes(report: HealthReport) -> list[str]:
    """The CLI's ``degraded`` list (exit 8): the reasons of every required capability that is not healthy."""
    codes: list[str] = []
    for name in REQUIRED_CAPABILITIES:
        cap = report.capabilities[name]
        if cap.state != "healthy":
            codes.extend(c for c in cap.reason_codes if c not in codes)
    return codes[:MAX_DEGRADED_CODES] or (["not_autonomous_ready"] if not report.autonomous_ready else [])


__all__ = ["health", "degraded_codes", "load_host_certification", "pinned_engine", "HOST_FILE"]
