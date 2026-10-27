"""Task 17 preview: profile-aware health and readiness of one installation (A29, A40, A46, A47, A49, A65, A72).

Health is computed by ``operations.health.health(ctx)`` (the service's
``health``) from the resolved installation only: no registry, no daemon, no
write. ``autonomous_ready`` is exactly "every required capability healthy"
(capture, inference, admission, recovery, forget, operator guard, start and
prompt delivery); pre-action/compaction delivery are reported, never
required; every deferred full-release feature is an explicit unavailable
result. The CLI is driven as a real child process; synthetic states (a
controlled provider route, a controlled host certification record, the
manifest a Task 13 installation would write) are named in
``health_scenarios`` and at each use. Nothing here is live certification.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

import health_scenarios as hs  # first: puts tests/, tests/integration and tests/platform on sys.path
import cli_scenarios as cs  # noqa: E402
import forget_scenarios as fs  # noqa: E402
import operation_scenarios as osc  # noqa: E402
import working_scenarios as wks  # noqa: E402
from recalith import service  # noqa: E402
from recalith.contracts.common import Scope, derived_id, utc_now  # noqa: E402
from recalith.contracts.config import BudgetConfig  # noqa: E402
from recalith.contracts.health import DEFERRED_FULL_CAPABILITIES, REQUIRED_CAPABILITIES  # noqa: E402
from recalith.controller import budgets  # noqa: E402
from recalith.errors import RecalithError  # noqa: E402
from recalith.fast import failpoints, process_env, session, spool  # noqa: E402
from recalith.privacy import forget, retention  # noqa: E402
from recalith.storage import backup, db  # noqa: E402

POSIX = os.name != "nt"


@pytest.fixture(autouse=True)
def _disarm():
    failpoints.disarm_all()
    yield
    failpoints.disarm_all()


@pytest.fixture(autouse=True)
def _no_worker_left(tmp_path):
    """No test may leave a worker running: every installation under the test's directory is stopped at teardown.

    These tests never start one on purpose (captures run with autostart off);
    a worker found here is a leak and fails the test after it is stopped.
    """
    yield
    import worker_hosts as wh

    leaked = []
    for marker in tmp_path.rglob(".recalith"):
        root = marker.parent
        if process_env.worker_running(root) or (root / ".recalith" / "run" / process_env.START_STAMP).exists():
            leaked.append(str(root))
            wh.stop_worker(root)
    assert not leaked, f"a worker was started and left running: {leaked}"


def token(root: Path, tmp: Path) -> Path:
    """An explicitly provisioned fixture token, registered with this installation (never committed)."""
    path = tmp / f"operator-{root.name}.token"
    cs.register(root, cs.token(path))
    return path


# ---------------------------------------------------------------------------
# Readiness (plan-named tests)


def test_missing_provider_is_degraded_not_ready(tmp_path):
    """A29/B1: no configured route is degraded, never ready; capture stays live; nothing falls back to a CLI on PATH."""
    p = hs.project(tmp_path)
    hs.integrate(p)
    hs.certify_host(p)
    # A claude CLI on PATH is never a route (synthetic executable that answers --version).
    decoy = hs.version_exe(tmp_path / "decoy-bin", name="claude")
    env = {"PATH": os.pathsep.join([str(decoy.parent), os.environ.get("PATH", "")]), hs.SELECTED: hs.KEY_VALUE}
    rep = hs.report(p, env)
    assert rep.autonomous_ready is False and rep.readiness == "degraded"
    inference = rep.capabilities["inference"]
    assert inference.required and inference.state == "unavailable" and "provider_not_configured" in inference.reason_codes
    assert rep.capabilities["admission"].state != "healthy" and "review_provider_unavailable" in rep.capabilities["admission"].reason_codes
    for name in ("capture", "start_delivery", "prompt_delivery", "operator_guard", "forget", "recovery"):
        assert rep.capabilities[name].state == "healthy", (name, rep.capabilities[name])
    # Capture remains live: a real prompt hook is acknowledged and ingested while model jobs wait.
    # (Autostart off while the hook runs in-process: it would otherwise start a real detached worker.)
    before = rep.job_summary["by_state"]
    hs.integrate(p, autostart=False)
    p.send(wks.variant(wks.record("lifecycle", "UserPromptSubmit"), prompt="health check prompt while no provider is configured"))
    p.drain()
    hs.integrate(p, autostart=True)
    after = hs.report(p, env)
    assert after.capabilities["capture"].state == "healthy" and after.autonomous_ready is False
    assert sum(after.job_summary["by_state"].values()) >= sum(before.values())
    # The B1-shaped route: configured but only request-capture observed: still not a route.
    hs.certify_provider(p, tmp_path / "route", certified=False)
    uncertified = hs.report(p, env)
    assert uncertified.capabilities["inference"].state == "unavailable" and "request_capture_only" in uncertified.capabilities["inference"].reason_codes
    assert uncertified.autonomous_ready is False and uncertified.readiness == "degraded"
    # The same report through the real CLI: exit 8 (capability_degraded) naming the loss, never readiness.
    result = cs.cli(p.root, "--json", "status", env=cs.base_env(**{hs.SELECTED: hs.KEY_VALUE}))
    assert result.code == 8, result.stderr
    obj = result.obj
    assert obj["ok"] is True and obj["status"] == "capability_degraded" and "request_capture_only" in obj["degraded"]
    assert obj["result"]["health"]["autonomous_ready"] is False and obj["result"]["health"]["readiness"] == "degraded"


def test_preview_ready_with_optional_delivery_unavailable(tmp_path):
    """Synthetic certified state: preview is operationally ready with pre-action unavailable and compaction failed."""
    p, env = hs.ready(tmp_path, paths=("session_start", "prompt"), delivery={"pre_action": "unavailable", "compact_restore": "failed"})
    rep = hs.report(p, env)
    assert hs.not_healthy(rep, REQUIRED_CAPABILITIES) == {}
    assert rep.autonomous_ready is True and rep.readiness == "ready" and rep.release_profile == "claude_preview"
    pre, compact = rep.capabilities["pre_action_delivery"], rep.capabilities["compact_delivery"]
    assert not pre.required and pre.state == "unavailable" and pre.reason_codes
    assert not compact.required and compact.state == "unavailable" and "delivery_path_failed" in compact.reason_codes
    assert rep.capabilities["start_delivery"].certified_version == hs.cf.VERSION and rep.capabilities["start_delivery"].certified_at
    # Readiness is scoped and honest: deferred features are still listed as unavailable.
    assert all(rep.capabilities[n].state == "unavailable" for n in DEFERRED_FULL_CAPABILITIES)
    # Through the real CLI (the caller carries the selected key): exit 0, the same verdict.
    result = cs.cli(p.root, "--json", "status", env=cs.base_env(**{hs.SELECTED: hs.KEY_VALUE}))
    assert result.code == 0, result.stdout + result.stderr
    assert result.obj["result"]["health"]["autonomous_ready"] is True and "degraded" not in result.obj
    # The same state with the optional paths installed and certified is still ready (and they report healthy).
    hs.integrate(p, paths=hs.DELIVERY_PATHS)
    hs.certify_host(p, delivery={"pre_action": "certified", "compact_restore": "certified"})
    full_paths = hs.report(p, env)
    assert full_paths.autonomous_ready and full_paths.capabilities["pre_action_delivery"].state == "healthy"


@pytest.mark.parametrize(
    "variant",
    ["not_installed", "path_failed", "request_capture_record", "host_version_changed", "uncertified_host_version", "no_record", "foreign_record", "not_integrated"],
)
def test_missing_required_prompt_is_not_ready(tmp_path, variant):
    """A missing or failed required prompt path is never ready, whatever else is certified (synthetic states)."""
    p, env = hs.ready(tmp_path, paths=hs.DELIVERY_PATHS, delivery={"pre_action": "certified", "compact_restore": "certified"})
    assert hs.report(p, env).autonomous_ready is True  # the control: certified, then one thing changes
    if variant == "not_installed":
        hs.integrate(p, paths=("session_start", "pre_action", "compact_restore"))
        expected = "delivery_path_not_installed"
    elif variant == "path_failed":
        hs.certify_host(p, delivery={"prompt": "failed", "pre_action": "certified", "compact_restore": "certified"})
        expected = "delivery_path_failed"
    elif variant == "request_capture_record":
        hs.certify_host(p, mode="request_capture", delivery={"pre_action": "certified", "compact_restore": "certified"})
        expected = "delivery_request_capture_only"
    elif variant == "host_version_changed":
        hs.integrate(p, paths=hs.DELIVERY_PATHS, host_version="2.1.399")
        expected = "host_version_changed"
    elif variant == "uncertified_host_version":
        hs.integrate(p, paths=hs.DELIVERY_PATHS, host_version="2.1.399")
        hs.certify_host(p, host_version="2.1.399", delivery={"pre_action": "certified", "compact_restore": "certified"})
        expected = "host_version_uncertified"
    elif variant == "no_record":
        (p.root / hs.HOST_FILE).unlink()
        expected = "delivery_not_certified"
    elif variant == "foreign_record":
        hs.certify_host(p, installation_id="inst_77777777-7777-4777-8777-777777777777")
        expected = "host_certification_invalid"
    else:
        (p.root / ".recalith" / "run" / "hook-context.json").unlink()
        expected = "host_not_integrated"
    rep = hs.report(p, env)
    prompt = rep.capabilities["prompt_delivery"]
    assert prompt.required and prompt.state != "healthy" and expected in prompt.reason_codes, prompt
    assert rep.autonomous_ready is False and rep.readiness in ("degraded", "unavailable")
    result = cs.cli(p.root, "--json", "status", env=cs.base_env(**{hs.SELECTED: hs.KEY_VALUE}))
    assert result.code == 8 and expected in result.obj["degraded"], result.stdout


def test_deferred_features_are_explicit_not_passed(tmp_path):
    """A46/A65 preview: every deferred full-release feature is unavailable with its reason; its commands answer 4."""
    p, env = hs.ready(tmp_path)
    rep = hs.report(p, env)
    for name in DEFERRED_FULL_CAPABILITIES:
        cap = rep.capabilities[name]
        assert cap.state == "unavailable" and not cap.required and "deferred_full_release" in cap.reason_codes, name
    assert "revision_chain_unavailable_in_preview" in rep.capabilities["revision_chain"].reason_codes
    for name in ("mcp", "codex_capture", "codex_delivery", "generic_json"):
        assert rep.capabilities[name].state == "unavailable"  # A46: no MCP/Codex availability is ever automatic capture
    assert rep.autonomous_ready is True  # deferred features do not unset preview readiness
    tok = token(p.root, tmp_path)
    before = cs.tree(p.root)
    selection = tmp_path / "selection.json"
    selection.write_text("{}", encoding="utf-8")
    forms = [
        ["export", "--selection", str(selection), "--output", str(tmp_path / "out")],
        ["import", str(tmp_path / "in"), "--expected-digest", "0" * 64],
        ["import", "breadcrumbs", "--source", str(tmp_path / "bc")],
        ["upgrade", "--wheel", str(tmp_path / "x.whl"), "--expected-digest", "0" * 64, "--release-profile", "full"],
        ["workspace", "attach", str(tmp_path)],
        ["project", "fork"],
        ["worker", "run", "--mode", "session"],
    ]
    for form in forms:
        result = cs.cli(p.root, "--json", "--operator-token-file", str(tok), *form)
        assert result.code == 4 and result.obj["error"] == "capability_unavailable", (form, result.stdout)
    full_integrity = cs.cli(p.root, "--json", "doctor", "--full-integrity")
    assert full_integrity.code == 4
    doctor = cs.cli(p.root, "--json", "doctor", env=cs.base_env(**{hs.SELECTED: hs.KEY_VALUE}))
    assert doctor.code == 0, doctor.stdout + doctor.stderr
    checks = doctor.obj["result"]["checks"]
    assert checks["revision_chain"] == "unavailable_in_preview" and checks["store_quick_check"] == "ok"
    assert doctor.obj["result"]["health"]["capabilities"]["revision_chain"]["state"] == "unavailable"
    assert cs.tree(p.root) == before  # nothing was changed by any deferred form


# ---------------------------------------------------------------------------
# What health exposes


def test_fresh_installation_reports_every_gap(tmp_path):
    """A real fresh installation (no integration, no route): not ready, every gap named, deferred features unavailable."""
    root = cs.init_project(tmp_path)
    rep = service.health(osc.context(root), inherited=cs.base_env())
    assert rep.autonomous_ready is False and rep.readiness == "degraded" and rep.worker_state == "stopped"
    caps = rep.capabilities
    assert "host_not_integrated" in caps["capture"].reason_codes and caps["capture"].state == "unavailable"
    assert "provider_not_configured" in caps["inference"].reason_codes
    for name in ("start_delivery", "prompt_delivery", "pre_action_delivery", "compact_delivery"):
        assert caps[name].state == "unavailable" and "host_not_integrated" in caps[name].reason_codes
    guard = caps["operator_guard"]
    assert guard.state == "degraded" and {"command_deny_rules_not_installed", "private_path_probe_not_run"} <= set(guard.reason_codes)
    assert guard.coverage["marker_guard"] == "active" and guard.coverage["private_paths"]["os_level_isolation"] is False
    assert "worker_autostart_not_registered" in caps["recovery"].reason_codes
    assert caps["forget"].state == "healthy" and rep.privacy_maintenance.state == "idle"
    assert set(rep.privacy_maintenance.limits) == set(forget.LIMITS)
    assert rep.installation.schema_state == "current" and rep.installation.schema_version == db.SCHEMA_VERSION
    assert rep.installation.installation_id == osc.context(root).installation_id
    assert "private_path_probe_not_run" in rep.coverage_gaps and "no_verified_backup" in rep.coverage_gaps


def test_unknown_host_version_is_conservative(tmp_path):
    """A47: an unknown host version captures in conservative mode, with explicit gaps and no delivery."""
    p = hs.project(tmp_path, scenario=None)
    hs.integrate(p, host_version="2.1.399", paths=hs.DELIVERY_PATHS)
    hs.certify_host(p, host_version="2.1.399")
    rep = hs.report(p)
    assert rep.capabilities["capture"].state == "degraded" and "host_version_uncertified" in rep.capabilities["capture"].reason_codes
    assert all("host_version_uncertified" in rep.capabilities[n].reason_codes for n in ("start_delivery", "prompt_delivery"))
    assert any(g.startswith("host_version_uncertified") for g in rep.coverage_gaps)
    hs.integrate(p, host_version=None)
    assert "host_version_unknown" in hs.report(p).capabilities["capture"].reason_codes


def test_source_conflicts_and_capture_gaps_are_listed(tmp_path):
    """A49/A07: one health entry per distinct conflicting digest; capture gaps and quarantined segments are listed."""
    p = hs.project(tmp_path, scenario=None)
    hs.integrate(p, autostart=False)  # captures run in-process here: no worker is started
    rec = wks.record("lifecycle", "PostToolUse")
    p.send(rec)
    for text in ("changed by another producer", "changed by a third producer"):
        p.send(_same_key(rec, text))
    p.drain()
    with p.view() as v:
        rows = v.execute("SELECT conflict_id, payload_digest FROM source_conflicts WHERE state = 'unresolved' ORDER BY conflict_id").fetchall()
    assert len(rows) == 2
    rep = hs.report(p)
    assert rep.source_conflict_count == 2 and sorted(e.conflict_id for e in rep.source_conflicts) == [r[0] for r in rows]
    assert {e.payload_digest for e in rep.source_conflicts} == {r[1] for r in rows}
    assert rep.capabilities["capture"].coverage["unresolved_conflicts"] == 2
    # Health entries are content-free: no payload text appears anywhere in the report.
    assert "changed by" not in rep.model_dump_json()
    # A capture gap (a durability failure) and a quarantined segment are listed as coverage gaps.
    cs.block_spool(p.root)
    try:
        with pytest.raises(AssertionError):
            p.send(wks.variant(wks.record("lifecycle", "UserPromptSubmit"), prompt="this one is not captured"))
    finally:
        cs.unblock_spool(p.root)
    quarantine = p.root / ".recalith" / "spool" / "quarantine"
    quarantine.mkdir(exist_ok=True)
    (quarantine / "seg-bad.json").write_text("{}", encoding="utf-8")  # synthetic: an invalid segment set aside
    rep = hs.report(p)
    assert any(g.startswith("capture_gap:") for g in rep.coverage_gaps), rep.coverage_gaps
    assert "spool_segments_quarantined" in rep.coverage_gaps


def _same_key(rec, text):
    """A changed result under the same host source identity (synthetic: another producer re-sent the tool result)."""
    changed = json.loads(json.dumps(rec))
    changed["payload"]["tool_response"]["stdout"] = text
    return changed


def test_exhausted_budget_pools_are_reported(tmp_path):
    """Exhausted pools pause the model lane: inference/admission degraded with the pool named; capture unaffected."""
    p, env = hs.ready(tmp_path)
    now = utc_now()
    config = BudgetConfig()
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        for i in range(config.daily_invocations + 1):
            if isinstance(budgets.reserve(txn, job_id=derived_id("job", ["extract_claims", i, now]), purpose="extract_claims", input_estimate=100, now=now, config=config), budgets.Refusal):
                break
    # Eight 14,000-token extractions leave 8,000: no extraction fits, but a 7,500-token task update still does (decision 0029).
    assert "ordinary" not in hs.report(p, env).budget_summary["exhausted_pools"]
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        for i in range(config.daily_invocations + 1):
            if isinstance(budgets.reserve(txn, job_id=derived_id("job", ["update_task", i, now]), purpose="update_task", input_estimate=100, now=now, config=config), budgets.Refusal):
                break
    rep = hs.report(p, env)
    assert "ordinary" in rep.budget_summary["exhausted_pools"]
    assert rep.capabilities["inference"].state == "degraded" and "ordinary_budget_exhausted" in rep.capabilities["inference"].reason_codes
    assert rep.autonomous_ready is False and rep.capabilities["capture"].state == "healthy"
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        for i in range(config.protected_invocations + 1):
            if isinstance(budgets.reserve(txn, job_id=derived_id("job", ["review_claims", i, now]), purpose="review_claims", input_estimate=100, now=now, config=config), budgets.Refusal):
                break
    rep = hs.report(p, env)
    assert set(rep.budget_summary["exhausted_pools"]) == {"ordinary", "protected"}
    assert "protected_budget_exhausted" in rep.capabilities["admission"].reason_codes


def test_retention_summary_is_measured(tmp_path):
    """Pinned/unpinned bytes, live owners, free disk and deferred compaction are measured from the store."""
    p, env = hs.ready(tmp_path)
    rep = hs.report(p, env)
    summary = rep.retention_summary
    with p.view() as v:
        expected = retention.summary(v, p.ctx, now=rep.checked_at, config=retention.retention_config(p.ctx))
        total = v.execute("SELECT COALESCE(SUM(length(CAST(payload AS BLOB))), 0) FROM events WHERE payload_state = 'available' AND payload IS NOT NULL").fetchone()[0]
    assert summary is not None and summary.pinned_payload_bytes == expected.pinned_payload_bytes and summary.live_owner_count == expected.live_owner_count
    assert summary.pinned_payload_bytes + summary.unpinned_payload_bytes == total > 0
    assert summary.live_owner_count > 0 and summary.free_disk_bytes is not None and summary.free_disk_bytes > 0
    assert summary.deferred_compaction_count == 0  # nothing is past its window in a fresh capture


def test_private_path_report_is_not_isolation(tmp_path):
    """A65 preview: the private-path probe is reported (limited/unsupported never gates); it is never OS-level isolation."""
    p, env = hs.ready(tmp_path, private_paths="probed_unsupported")
    rep = hs.report(p, env)
    guard = rep.capabilities["operator_guard"]
    assert guard.state == "healthy" and rep.autonomous_ready is True
    private = guard.coverage["private_paths"]
    assert private["state"] == "probed_unsupported" and private["os_level_isolation"] is False and private["installed_rules"] == "unavailable_in_preview"
    assert "private_path_protection_limited" in rep.coverage_gaps
    hs.certify_host(p, private_paths="not_run")
    rep = hs.report(p, env)
    assert rep.capabilities["operator_guard"].state == "degraded" and "private_path_probe_not_run" in rep.capabilities["operator_guard"].reason_codes
    hs.certify_host(p, command_rules="unavailable")
    rep = hs.report(p, env)
    assert "command_deny_rules_not_installed" in rep.capabilities["operator_guard"].reason_codes and rep.autonomous_ready is False


def test_health_is_read_only(tmp_path):
    """Health opens nothing for writing and creates no file, also while the worker's lock file is absent."""
    p, env = hs.ready(tmp_path)
    lock = p.root / ".recalith" / "run" / "worker.lock"
    lock.unlink(missing_ok=True)
    before, stamps = hs.tree_digest(p.root), hs.mtimes(p.root)
    hs.report(p, env)
    hs.report(p, env, deep=True)
    result = cs.cli(p.root, "--json", "doctor", env=cs.base_env(**{hs.SELECTED: hs.KEY_VALUE}))
    assert result.code == 0
    assert hs.tree_digest(p.root) == before and hs.mtimes(p.root) == stamps and not lock.exists()


def test_worker_startup_and_recovery_checks(tmp_path):
    """Recovery names the registered hook start, the running worker's own state and every pending recovery step."""
    p, env = hs.ready(tmp_path)
    rep = hs.report(p, env)
    startup = rep.capabilities["recovery"].coverage["startup"]
    assert startup["registered_hook_start"] == "registered" and startup["os_startup_entries"]["state"] == "unavailable"
    assert rep.worker_state == "stopped" and rep.capabilities["recovery"].state == "healthy"  # resumes on next project activity
    hs.integrate(p, autostart=False)
    rep = hs.report(p, env)
    assert "worker_autostart_not_registered" in rep.capabilities["recovery"].reason_codes and rep.autonomous_ready is False
    hs.integrate(p, autostart=True)
    # An interrupted backup (a real child killed after its snapshot) is pending recovery until the worker finishes it.
    code = hs.killed_at(p.root, failpoints.BACKUP_AFTER_SNAPSHOT, "backup", source=tmp_path / "interrupted")
    assert code == failpoints.KILL_STATUS
    rep = hs.report(p, env)
    assert "backup_recovery_pending" in rep.capabilities["recovery"].reason_codes and rep.autonomous_ready is False
    p.drain()
    rep = hs.report(p, env)
    assert rep.capabilities["recovery"].state == "healthy" and rep.autonomous_ready is True
    # Delayed ingestion: a real captured segment left un-ingested, its age set 20 minutes back (synthetic age).
    hs.integrate(p, autostart=False)  # the in-process hook must not start a worker here
    p.send(wks.variant(wks.record("lifecycle", "UserPromptSubmit"), prompt="a prompt the worker has not ingested yet"))
    hs.integrate(p, autostart=True)
    segments = spool.ready_segments(spool.SpoolDirs(p.root))
    assert segments
    rep = hs.report(p, env)
    assert "ingestion_delayed" not in rep.capabilities["recovery"].reason_codes  # a fresh backlog is not a delay
    old = time.time() - 1200
    for seg in segments:
        os.utime(seg, (old, old))
    rep = hs.report(p, env)
    assert "ingestion_delayed" in rep.capabilities["recovery"].reason_codes and rep.capabilities["capture"].coverage["oldest_ready_age_seconds"] >= 1200 - 5
    p.drain()
    assert "ingestion_delayed" not in hs.report(p, env).capabilities["recovery"].reason_codes


def test_running_worker_is_judged_from_its_own_record(tmp_path):
    """A running worker's state comes from its own record for this installation (synthetic records, a held lock).

    The lock is held in-process (as a running worker holds it); the status
    records are written by the test: an undetached spawn, a stale
    heartbeat, and a record copied from another installation.
    """
    p, env = hs.ready(tmp_path)
    lock = process_env.InstallationLock(p.root)
    assert lock.try_acquire()
    record = p.root / ".recalith" / "run" / "worker.json"

    def write(**fields):
        base = {"status_schema": 1, "installation_id": p.ctx.installation_id, "pid": os.getpid(), "state": "idle", "heartbeat_at": utc_now(), "last_error": None,
                "spawn": {"spawned_by": "hook", "method": "posix_session", "state": "detached", "degraded_reasons": [], "in_job": None}}
        base.update(fields)
        record.write_text(json.dumps(base), encoding="utf-8")

    try:
        write()
        rep = hs.report(p, env)
        assert rep.worker_state == "idle" and rep.capabilities["recovery"].state == "healthy" and rep.autonomous_ready
        write(spawn={"spawned_by": "hook", "method": "windows_no_breakaway", "state": "degraded", "degraded_reasons": ["job_breakaway_denied"], "in_job": True})
        rep = hs.report(p, env)
        assert "worker_independence_degraded" in rep.capabilities["recovery"].reason_codes and rep.autonomous_ready is False
        assert rep.capabilities["recovery"].coverage["worker"]["degraded_reasons"] == ["job_breakaway_denied"]
        write(heartbeat_at="2026-01-01T00:00:00.000000Z")
        rep = hs.report(p, env)
        assert rep.worker_state == "degraded" and "worker_heartbeat_stale" in rep.capabilities["recovery"].reason_codes
        write(installation_id="inst_77777777-7777-4777-8777-777777777777")  # a record copied from another installation never counts
        rep = hs.report(p, env)
        assert rep.capabilities["recovery"].coverage["worker"]["spawned_by"] is None and "worker_status_unavailable" in rep.capabilities["recovery"].reason_codes
        write(last_error="status_write_failed")
        assert "worker_error" in hs.report(p, env).capabilities["recovery"].reason_codes
    finally:
        lock.release()
        record.unlink(missing_ok=True)
    assert hs.report(p, env).worker_state == "stopped"


def test_corrupt_store_fails_the_integrity_check(tmp_path):
    """``doctor`` runs ``PRAGMA quick_check``: a malformed index page makes recovery unavailable; nothing crashes.

    Synthetic corruption: the page-type byte of an index root page of a table
    health never reads (the lexical projection) is overwritten after a
    checkpoint, as a damaged disk block would.
    """
    p, env = hs.ready(tmp_path)
    store_file = p.root / ".recalith" / db.STATE_DB
    conn = sqlite3.connect(store_file)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        name, page = conn.execute("SELECT name, rootpage FROM sqlite_master WHERE type = 'index' AND tbl_name = 'lexical_index' AND rootpage > 0 ORDER BY name").fetchone()
    finally:
        conn.close()
    assert hs.report(p, env, deep=True).capabilities["recovery"].coverage["store_integrity"] == "ok"
    with open(store_file, "r+b") as fh:
        fh.seek((page - 1) * page_size)
        fh.write(b"\xff")
    rep = hs.report(p, env, deep=True)
    recovery = rep.capabilities["recovery"]
    assert recovery.state == "unavailable" and "store_integrity_check_failed" in recovery.reason_codes and recovery.coverage["store_integrity"] == "failed"
    assert rep.autonomous_ready is False
    doctor = cs.cli(p.root, "--json", "doctor", env=cs.base_env(**{hs.SELECTED: hs.KEY_VALUE}))
    assert doctor.code == 8 and doctor.obj["result"]["checks"]["store_quick_check"] == "failed" and "store_integrity_check_failed" in doctor.obj["degraded"], name
    # A malformed page that health's own reads meet (the events table's root): reported unreadable, never a crash.
    conn = sqlite3.connect(store_file)
    try:
        events_root = conn.execute("SELECT rootpage FROM sqlite_master WHERE type = 'table' AND name = 'events'").fetchone()[0]
    finally:
        conn.close()
    with open(store_file, "r+b") as fh:
        fh.seek((events_root - 1) * page_size)
        fh.write(b"\xff")
    rep = hs.report(p, env)
    assert rep.installation.schema_state == "unreadable" and rep.readiness == "unavailable" and rep.retention_summary is None
    assert "store_unreadable" in rep.capabilities["recovery"].reason_codes
    status = cs.cli(p.root, "--json", "status", env=cs.base_env(**{hs.SELECTED: hs.KEY_VALUE}))
    assert status.code == 8 and "store_unreadable" in status.obj["degraded"], status.stdout + status.stderr


# ---------------------------------------------------------------------------
# Pending privacy maintenance (Task 16 state composed into health)


def test_pending_privacy_maintenance_is_reported(tmp_path):
    """Unfinished operations, scratch owed, a failed post-forget backup, a journaled restore and the marker: each named."""
    b = fs.build(tmp_path, deliver=True)
    p = b.p
    hs.integrate(p)
    hs.certify_host(p)
    env = hs.certify_provider(p, tmp_path / "route")
    assert hs.report(p, env).autonomous_ready is True

    # (1) Scratch owed: a hook holds the forgotten session's scratch lock through the whole forget (synthetic interleaving).
    assert Path(session.scratch_path(p.root, b.session)).exists()
    lock = session.SessionLock(p.root, b.session)
    assert lock.acquire(1.0)
    try:
        fs.forget(b, fs.task_selector(b))
        rep = hs.report(p, env)
        pm = rep.privacy_maintenance
        assert pm.state == "pending" and pm.scratch_cleanup_pending and pm.maintenance_marker == "active" and pm.delivery_paused
        assert [o.status for o in pm.unfinished_operations] == ["cleanup_pending"]
        assert "scratch_cleanup_pending" in rep.capabilities["forget"].reason_codes
        assert rep.capabilities["prompt_delivery"].state == "degraded" and "maintenance_in_progress" in rep.capabilities["prompt_delivery"].reason_codes
        assert rep.autonomous_ready is False
    finally:
        lock.release()
    p.drain()
    assert hs.report(p, env).privacy_maintenance.state == "idle"

    # (2) A forget stopped after its purge commit: delivery paused, the operation unfinished until the worker resumes it.
    def stop(_name: str) -> None:
        raise RuntimeError("interrupted after the purge commit")

    failpoints.arm(failpoints.FORGET_AFTER_COMMIT, stop)
    with pytest.raises(RuntimeError):
        fs.forget(b, _claim_selector(b, "lesson"))
    rep = hs.report(p, env)
    pm = rep.privacy_maintenance
    assert pm.state == "pending" and pm.maintenance_marker == "active" and pm.delivery_paused and not pm.scratch_cleanup_pending
    assert [o.status for o in pm.unfinished_operations] == ["running"] and pm.unfinished_operations[0].phase == "purged"
    assert "privacy_maintenance_pending" in rep.capabilities["forget"].reason_codes and rep.autonomous_ready is False
    # The purge committed a new tombstone epoch; the latest ledger copy (its later phase) is still behind it.
    assert "ledger_copy_stale" in rep.capabilities["recovery"].reason_codes
    assert rep.capabilities["recovery"].coverage["ledger"]["copy_epoch"] < rep.capabilities["recovery"].coverage["ledger"]["store_epoch"]
    p.drain()
    rep = hs.report(p, env)
    assert rep.privacy_maintenance.state == "idle" and "ledger_copy_stale" not in rep.capabilities["recovery"].reason_codes

    # (3) The post-forget backup fails (an injected OSError at its snapshot): reported until a later verified backup exists.
    def boom(_name: str) -> None:
        raise OSError("injected: no space left for the post-forget backup")

    failpoints.arm(failpoints.BACKUP_AFTER_SNAPSHOT, boom)
    from recalith.contracts.privacy import ForgetSelector

    _preview, result = fs.forget(b, ForgetSelector(task_ids=[b.tasks["lifecycle"]]))
    assert "backup_unavailable_after_forget" in result.error_codes
    rep = hs.report(p, env)
    assert rep.privacy_maintenance.backup_unavailable_after_forget == [result.operation_id]
    assert "backup_unavailable_after_forget" in rep.capabilities["forget"].reason_codes and rep.autonomous_ready is False
    later = backup.create(p.ctx, tmp_path / "after")
    rep = hs.report(p, env)
    assert rep.privacy_maintenance.backup_unavailable_after_forget == [] and rep.capabilities["forget"].state == "healthy"

    # (4) A restore killed after staging (a real child, os._exit): journaled, marker held, recovered as the worker's start does.
    code = hs.killed_at(p.root, failpoints.RESTORE_AFTER_STAGE, "restore", source=Path(later.location), digest=later.manifest_digest)
    assert code == failpoints.KILL_STATUS
    rep = hs.report(p, env)
    assert rep.privacy_maintenance.restore_journaled and rep.privacy_maintenance.delivery_paused
    assert "restore_recovery_pending" in rep.capabilities["recovery"].reason_codes and rep.autonomous_ready is False
    forget.recover_restore(osc.context(p.root))
    p.drain()
    rep = hs.report(p, env)
    assert rep.privacy_maintenance.state == "idle" and rep.autonomous_ready is True, (rep.privacy_maintenance, hs.not_healthy(rep, REQUIRED_CAPABILITIES))
    assert set(rep.privacy_maintenance.limits) == set(forget.LIMITS)


def _claim_selector(b, role):
    from recalith.contracts.common import RecordRef
    from recalith.contracts.privacy import ForgetSelector

    return ForgetSelector(record_refs=[RecordRef(kind="claim", id=b.claims[role], revision=osc.head_ref(b.p.root, "claim", b.claims[role]).revision)])


def test_stale_maintenance_marker_is_reported(tmp_path):
    """A marker left by a dead operator command with nothing pending is stale: reported, dropped by the worker's next poll."""
    p, env = hs.ready(tmp_path)
    forget.write_marker(osc.context(p.root), kind="forget", operation_id="frg_" + "0" * 64)  # synthetic: a dead writer's marker
    rep = hs.report(p, env)
    assert rep.privacy_maintenance.maintenance_marker == "stale" and "maintenance_marker_stale" in rep.capabilities["forget"].reason_codes
    p.drain()
    assert hs.report(p, env).privacy_maintenance.maintenance_marker == "absent"


# ---------------------------------------------------------------------------
# A40 preview: unsupported schemas are refused, the live store preserved


def test_unsupported_schema_store_is_refused_and_preserved(tmp_path, monkeypatch):
    """A genuine schema-9 store: health says migration required; guarded writes and the worker refuse; nothing changes."""
    root = hs.schema9_installation(tmp_path, "old", monkeypatch)
    assert hs.store_schema(root) == hs.OLD_SCHEMA
    ctx = osc.context(root)
    store_file = root / ".recalith" / db.STATE_DB
    before = store_file.read_bytes()
    rep = service.health(ctx, inherited=cs.base_env())
    assert rep.worker_state == "migration_required" and rep.readiness == "unavailable" and rep.autonomous_ready is False
    assert rep.installation.schema_state == "migration_required" and rep.installation.schema_version == hs.OLD_SCHEMA
    assert rep.installation.pinned_engine_version == hs.OLD_ENGINE and rep.retention_summary is None
    assert "engine_pin_mismatch" in rep.capabilities["recovery"].reason_codes
    for name in ("recovery", "forget", "admission"):
        assert "schema_migration_required" in rep.capabilities[name].reason_codes, name
    status = cs.cli(root, "--json", "status")
    assert status.code == 8 and "schema_migration_required" in status.obj["degraded"]
    tok = token(root, tmp_path)
    scope = tmp_path / "scope.json"
    scope.write_text("{}", encoding="utf-8")
    for form in (["backup", "--output", str(tmp_path / "b")], ["declare", "decision", "--statement", "Use pytest.", "--scope", str(scope)]):
        result = cs.cli(root, "--json", "--operator-token-file", str(tok), *form)
        assert result.code == 2 and result.obj["error"] == "invalid_schema", (form, result.stdout)
    with pytest.raises(RecalithError, match="invalid_schema"):
        service.declare(osc.operator(root), "decision", "Use pytest.", Scope())
    worker = cs.run([__import__("sys").executable, "-I", "-m", "recalith.controller.worker", "--project", str(root)], env=_worker_env(root))
    assert worker.code != 0
    assert store_file.read_bytes() == before and not (tmp_path / "b").exists()


def _worker_env(root: Path) -> dict[str, str]:
    import worker_hosts as wh

    return wh.worker_env(root)


def test_schema9_backup_is_refused_and_live_store_preserved(tmp_path, monkeypatch):
    """A genuine schema-9 backup of the installation is rejected by the guarded restore (exit 2); the live store is unchanged."""
    root = hs.schema9_installation(tmp_path, "proj", monkeypatch)
    with monkeypatch.context() as m:
        m.setattr(db, "SCHEMA_VERSION", hs.OLD_SCHEMA)
        m.setattr(backup, "SCHEMA_VERSION", hs.OLD_SCHEMA)  # the schema-9 build wrote its backups with its own schema
        old = backup.create(osc.context(root), tmp_path / "schema9-backup")
    # Synthetic: the same installation's live store recreated at the current schema (as an upgrade would leave it).
    ctx = osc.context(root)
    live = root / ".recalith" / db.STATE_DB
    for suffix in ("", "-wal", "-shm"):
        Path(str(live) + suffix).unlink(missing_ok=True)
    workspace = {"workspace_id": ctx.workspace_id, "canonical_root": str(root), "root_identity": _root_identity(root)}
    db.create_database(live, project_id=ctx.project_id, installation_id=ctx.installation_id, engine_version=ctx.engine_version, release_profile="claude_preview", workspace=workspace)
    hs.pin_engine(root, hs.identity.__version__, store_schema=db.SCHEMA_VERSION)
    assert hs.store_schema(root) == db.SCHEMA_VERSION
    before = live.read_bytes()
    tok = token(root, tmp_path)
    result = cs.cli(root, "--json", "--operator-token-file", str(tok), "restore", old.location, "--expected-digest", old.manifest_digest)
    assert result.code == 2 and result.obj["error"] == "invalid_schema" and "backup_schema_unsupported" in result.obj["message"], result.stdout
    assert live.read_bytes() == before and not forget.restore_pending(root)
    rep = service.health(osc.context(root), inherited=cs.base_env())
    assert rep.installation.schema_state == "current" and rep.privacy_maintenance.state == "idle"


def _root_identity(root: Path) -> str:
    from recalith.core.paths import root_identity

    return root_identity(root)
