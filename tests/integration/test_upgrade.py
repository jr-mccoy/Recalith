"""Task 17: independent installations across pinned builds and schemas (A02 preview, A40 preview).

The preview variant of A02 is exercised here: two independent installations
with **independently pinned build/schema fixtures** (A: a genuine schema-9
store built from the migration files 0001–0009 with an ``engine.lock`` pinned
to an older release; B: the current schema and engine), and **recovery of A
leaves B untouched** (A's interrupted backup and restore, made by real child
processes killed with ``os._exit``, are recovered by A's real worker process
while B's every file stays byte-identical).

Engine/schema upgrade, side-by-side runtimes, the preview-to-full transition
and its rollback are **full-only** (SYSTEM_SPEC §10.1, IMPLEMENTATION_PLAN
Task 17): the preview build answers ``upgrade`` with ``capability_unavailable``
and the plan-named upgrade tests below are explicit *pending* skips, never
passes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import health_scenarios as hs  # first: puts tests/, tests/integration and tests/platform on sys.path
import cli_scenarios as cs  # noqa: E402
import operation_scenarios as osc  # noqa: E402
import worker_hosts as wh  # noqa: E402
from recalith import service  # noqa: E402
from recalith.contracts.common import Scope  # noqa: E402
from recalith.errors import RecalithError  # noqa: E402
from recalith.fast import failpoints, process_env  # noqa: E402
from recalith.privacy import forget  # noqa: E402
from recalith.storage import backup, db  # noqa: E402

FULL_ONLY = "pending: full-only (Task 17 full slice, SYSTEM_SPEC §10.1); the preview build answers upgrade with capability_unavailable"


def pending_full_only(what: str) -> None:
    pytest.skip(f"{FULL_ONLY}: {what}")


@pytest.fixture
def started():
    roots: list[Path] = []
    yield roots
    leftovers = [str(r) for r in roots if not wh.stop_worker(r)]
    assert not leftovers, f"workers did not stop on request and were killed: {leftovers}"


def token(root: Path, tmp: Path) -> Path:
    path = tmp / f"operator-{root.name}.token"
    cs.register(root, cs.token(path))
    return path


def report_shape(rep) -> dict:
    """What must not move in an untouched installation (the check time, ages and free disk excluded)."""
    data = json.loads(rep.model_dump_json())
    data.pop("checked_at")
    data["job_summary"].pop("oldest_due_backlog_seconds", None)
    data["capabilities"]["capture"]["coverage"].pop("oldest_ready_age_seconds", None)
    if data.get("retention_summary"):
        data["retention_summary"].pop("free_disk_bytes")
    return data


# ---------------------------------------------------------------------------
# A02 preview: independent pinned builds and schemas


def test_independent_pinned_builds_report_their_own_schema(tmp_path, monkeypatch):
    """A (schema 9, older pin) and B (current) are reported and refused independently; nothing of B moves."""
    a = hs.schema9_installation(tmp_path, "a", monkeypatch)
    b = hs.project(tmp_path, "b").root
    b_before = hs.tree_digest(b)
    rep_a = service.health(osc.context(a), inherited=cs.base_env())
    rep_b = service.health(osc.context(b), inherited=cs.base_env())
    assert rep_a.installation.installation_id != rep_b.installation.installation_id and rep_a.installation.project_id != rep_b.installation.project_id
    assert (rep_a.installation.schema_version, rep_a.installation.schema_state, rep_a.installation.pinned_engine_version) == (hs.OLD_SCHEMA, "migration_required", hs.OLD_ENGINE)
    assert (rep_b.installation.schema_version, rep_b.installation.schema_state, rep_b.installation.pinned_engine_version) == (db.SCHEMA_VERSION, "current", hs.identity.__version__)
    assert rep_a.worker_state == "migration_required" and rep_b.worker_state == "stopped"
    assert "engine_pin_mismatch" in rep_a.capabilities["recovery"].reason_codes and "engine_pin_mismatch" not in rep_b.capabilities["recovery"].reason_codes
    # A refuses every write and never migrates silently (the worker exits; the store stays schema 9) ...
    a_store = (a / ".recalith" / db.STATE_DB).read_bytes()
    with pytest.raises(RecalithError, match="invalid_schema"):
        service.declare(osc.operator(a), "decision", "Keep A on its own build.", Scope())
    worker = cs.run([__import__("sys").executable, "-I", "-m", "recalith.controller.worker", "--project", str(a)], env=wh.worker_env(a))
    assert worker.code != 0 and hs.store_schema(a) == hs.OLD_SCHEMA and (a / ".recalith" / db.STATE_DB).read_bytes() == a_store
    # ... B never moved and still writes under its own schema.
    assert hs.tree_digest(b) == b_before
    result = service.declare(osc.operator(b), "decision", "Keep B on the current build.", Scope())
    assert result.decisions and hs.store_schema(b) == db.SCHEMA_VERSION


def test_recovering_A_leaves_B_untouched(tmp_path, started):
    """A's interrupted backup and restore (real children killed abruptly) are recovered by A's real worker; B is byte-identical."""
    pa = hs.project(tmp_path, "a")
    pb = hs.project(tmp_path, "b")
    a, b = pa.root, pb.root
    good = backup.create(pa.ctx, tmp_path / "a-good")
    assert hs.killed_at(a, failpoints.BACKUP_AFTER_MANIFEST, "backup", source=tmp_path / "a-interrupted") == failpoints.KILL_STATUS
    assert hs.killed_at(a, failpoints.RESTORE_BEFORE_SWAP, "restore", source=Path(good.location), digest=good.manifest_digest) == failpoints.KILL_STATUS
    rep_a = service.health(osc.context(a), inherited=cs.base_env())
    assert {"restore_recovery_pending", "backup_recovery_pending"} <= set(rep_a.capabilities["recovery"].reason_codes)
    assert rep_a.privacy_maintenance.restore_journaled
    b_tree, b_report = hs.tree_digest(b), report_shape(service.health(osc.context(b), inherited=cs.base_env()))
    # A's own worker (a real process with the fresh worker environment) recovers A at its start.
    started.append(a)
    proc = wh.start_direct(a)
    assert wh.wait_for(lambda: not forget.restore_pending(a) and not list((a / ".recalith" / "run" / "backups").glob("bkp_*.json")) and wh.status(a), 60), proc.stderr
    assert wh.stop_worker(a)
    rep_a = service.health(osc.context(a), inherited=cs.base_env())
    assert not {"restore_recovery_pending", "backup_recovery_pending"} & set(rep_a.capabilities["recovery"].reason_codes)
    assert rep_a.privacy_maintenance.state == "idle" and rep_a.installation.schema_state == "current"
    # B: no file changed, no worker started, the same report.
    assert hs.tree_digest(b) == b_tree and not process_env.worker_running(b)
    assert not (b / ".recalith" / "run" / process_env.START_STAMP).exists()
    assert report_shape(service.health(osc.context(b), inherited=cs.base_env())) == b_report


def test_upgrade_is_unavailable_in_preview(tmp_path):
    """``upgrade`` (and the profile flag) is guarded first, then answers 4 in preview; nothing is staged or changed."""
    root = cs.init_project(tmp_path)
    tok = token(root, tmp_path)
    before = cs.tree(root)
    wheel = tmp_path / "recalith-9.9.9-py3-none-any.whl"
    wheel.write_bytes(b"not a wheel")
    for extra in ([], ["--release-profile", "full"], ["--release-profile", "claude_preview"]):
        result = cs.cli(root, "--json", "--operator-token-file", str(tok), "upgrade", "--wheel", str(wheel), "--expected-digest", "0" * 64, *extra)
        assert result.code == 4 and result.obj["error"] == "capability_unavailable", result.stdout
        refused = cs.cli(root, "--json", "--operator-token-file", str(tok), "upgrade", "--wheel", str(wheel), "--expected-digest", "0" * 64, *extra, env=cs.marked_env("CLAUDECODE"))
        assert refused.code == 6 and refused.obj["error"] == "policy_refused"
    assert cs.tree(root) == before and not (root / ".recalith" / "runtime" / "9.9.9").exists()
    rep = service.health(osc.context(root), inherited=cs.base_env())
    assert rep.capabilities["side_by_side_upgrade"].state == "unavailable" and rep.release_profile == "claude_preview"


# ---------------------------------------------------------------------------
# Plan-named upgrade tests: full-only, explicitly pending (never a pass)


def test_upgrade_A_leaves_B_running():
    pending_full_only("live side-by-side upgrade of A while B's worker keeps running (A02 full variant)")


def test_interrupted_upgrade_restores_previous_engine():
    pending_full_only("activation/rollback journal restoring the previous engine (A40 full variant)")


def test_preview_to_full_preserves_live_evidence_and_ids():
    pending_full_only("preview-to-full transition preserving IDs and day-181 pinned evidence (A02 full variant)")


def test_profile_transition_honors_retention_override():
    pending_full_only("180→30 day profile default with explicit operator overrides kept")


def test_failed_capsule_transition_keeps_pin():
    pending_full_only("capsule sufficiency failure retains the pin (A35/A40 full variants)")


def test_interrupted_profile_transition_restores_complete_state():
    pending_full_only("interrupted profile transition serves only a complete previous or completed state with the newest tombstones")
