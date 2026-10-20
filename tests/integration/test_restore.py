"""Task 16 (preview): suppression-aware restore (A37; the A40 preview variant's restore path).

Real inputs as in ``test_forgetting`` (real 2.1.301 payloads, recorded
proposals, real backups, the real guarded ``recalith`` child process with an
explicitly provisioned fixture token). The restored backup is an operator's
**external copy** of a backup taken before the forget: the forget deletes the
recorded affected backup but cannot see a copy it never recorded (a reported
limit); restoring that copy is the A37 case. Synthetic store states are named
where used (a lost live store).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import forget_scenarios as fs  # first: puts tests/, tests/integration and tests/platform on sys.path
import cli_scenarios as cli  # noqa: E402
import consolidation_scenarios as cs  # noqa: E402
import delivery_scenarios as ds  # noqa: E402
import operation_scenarios as osc  # noqa: E402
import retention_scenarios as rsn  # noqa: E402
import retrieval_scenarios as rs  # noqa: E402
import working_scenarios as wks  # noqa: E402
from recalith import service  # noqa: E402
from recalith.contracts.privacy import RestoreResult  # noqa: E402
from recalith.errors import RecalithError  # noqa: E402
from recalith.fast import process_env  # noqa: E402
from recalith.privacy import forget  # noqa: E402
from recalith.storage import backup, failpoints  # noqa: E402


@pytest.fixture(autouse=True)
def _disarm():
    failpoints.disarm_all()
    yield
    failpoints.disarm_all()


def _kept_then_forgotten(tmp: Path, **kw) -> tuple[fs.Built, backup.BackupResult, Path]:
    """The marker project, a backup before the forget and an operator's external copy of it; then the forget."""
    b = fs.build(tmp, **kw)
    old = backup.create(b.p.ctx, tmp / "before-forget")
    kept = fs.copy_backup(old.location, tmp / "operator-kept-copy")
    fs.forget(b, fs.task_selector(b))
    assert not Path(old.location).exists() and fs.marker_locations(b.p.root) == []
    return b, old, kept


def test_restore_applies_newer_tombstones(tmp_path):
    """A37: restoring a backup taken before a forget applies the newer tombstones before anything is served.

    Through the real guarded CLI. Forgotten text never reappears in the live
    store, its projections, scratch or spool; the quarantined head stays
    content-free and gets its reconstruction job again; the unrelated lesson
    is back; delivery resumes only after suppression.
    """
    b, old, kept = _kept_then_forgotten(tmp_path)
    p, c = b.p, b.claims
    assert fs.marker_locations(p.root, kept)  # the external copy still holds the text (outside local forgetting)
    epoch = rsn.meta(p).tombstone_epoch
    tok = tmp_path / "operator.token"
    cli.register(p.root, cli.token(tok))
    done = cli.cli(p.root, "--json", "--operator-token-file", str(tok), "restore", str(kept), "--expected-digest", old.manifest_digest)
    assert done.code == 0, done.stdout + done.stderr
    result = RestoreResult.model_validate(done.obj["result"])
    snapshot_revision = rsn.snapshot_rows(kept / "memory.sqlite", "SELECT store_revision FROM installation_meta")[0][0]
    assert result.restored_revision == snapshot_revision and result.preserved_tombstone_epoch == epoch
    assert result.suppressed_record_count >= 5 and result.source_contains_suppressed is True
    assert "external_copy_holds_suppressed_content" in result.limits
    assert fs.marker_locations(p.root) == [] and not fs.maintenance_active(p)
    assert rsn.meta(p).tombstone_epoch == epoch
    assert fs.statuses(p, [("claim", c["decl"]), ("claim", c["derived"]), ("claim", c["multi"]), ("task", b.tasks["forgotten"]), ("episode", b.episode), ("claim", c["lesson"])]) == {
        c["decl"]: "forgotten", c["derived"]: "forgotten", c["multi"]: "quarantined", b.tasks["forgotten"]: "forgotten", b.episode: "forgotten", c["lesson"]: "active"}
    assert [j for j in cs.jobs_of(p, "extract_claims", states=("pending", "waiting_budget")) if {r.id for r in j.input_refs} == {b.events["seq"]}]
    # The worker runs on the restored store: nothing resurrects (transcript re-reads and spool replays are suppressed).
    p.drain()
    rs.publish(p)
    assert fs.marker_locations(p.root) == []
    assert not {c["decl"], c["multi"], c["derived"]} & set(rs.ids(rs.service(p, rs.query(p, "manual", text="fixture port 8123 seq tree"))))
    _reply, out = ds.hook(p, ds.in_session(wks.record("lifecycle", "UserPromptSubmit"), fs.SESSION_F, prompt="Which port does the fixture listen on? port 8123"))
    assert all(fs.MARK.lower() not in ds.context_text(o).lower() for o in out)
    assert c["lesson"] in rs.ids(rs.service(p, cs.query(p)))
    ledger = backup.read_latest_ledger(p.root)
    assert ledger["tombstone_epoch"] == epoch


def test_restore_uses_the_latest_ledger_copy_when_the_store_is_lost(tmp_path):
    """The live store is gone (synthetic store state: a lost database file); the guarded CLI restores and the latest ledger copy still suppresses."""
    b, old, kept = _kept_then_forgotten(tmp_path, deliver=False)
    p = b.p
    epoch = rsn.meta(p).tombstone_epoch
    tok = tmp_path / "operator.token"
    cli.register(p.root, cli.token(tok))
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(fs.db_path(p)) + suffix)
        if path.exists():
            path.unlink()
    done = cli.cli(p.root, "--json", "--operator-token-file", str(tok), "restore", str(kept), "--expected-digest", old.manifest_digest)
    assert done.code == 0, done.stdout + done.stderr
    result = RestoreResult.model_validate(done.obj["result"])
    assert result.preserved_tombstone_epoch == epoch and result.suppressed_record_count >= 5
    assert fs.marker_locations(p.root) == []
    assert fs.statuses(p, [("claim", b.claims["decl"]), ("claim", b.claims["multi"])]) == {b.claims["decl"]: "forgotten", b.claims["multi"]: "quarantined"}


def test_restore_of_a_post_forget_backup_needs_no_reapplication(tmp_path):
    """A backup that already carries the tombstones restores with nothing to suppress; the text stays gone."""
    b = fs.build(tmp_path, deliver=False)
    p = b.p
    _preview, forgotten = fs.forget(b, fs.task_selector(b))
    with p.view() as v:
        location, digest = v.execute("SELECT location, manifest_digest FROM backups WHERE backup_id = ?", (forgotten.new_backup_id,)).fetchone()
    result = service.restore(fs.operator(b), Path(location), expected_digest=digest)
    assert result.suppressed_record_count == 0 and result.source_contains_suppressed is False
    assert fs.marker_locations(p.root, Path(location)) == []


def test_restore_requires_exclusive_maintenance(tmp_path):
    """A worker that holds the installation and does not stop keeps the live store untouched; nothing is half-restored."""
    b, old, kept = _kept_then_forgotten(tmp_path, deliver=False)
    p = b.p
    lock = process_env.InstallationLock(p.root)  # synthetic: a worker that holds the installation and ignores the stop request
    assert lock.try_acquire()
    try:
        before = cli.store_rows(p.root)
        with pytest.raises(RecalithError) as refused:
            service.restore(fs.operator(b), kept, expected_digest=old.manifest_digest, stop_wait=0.5)
        assert refused.value.code == "capability_unavailable"
        assert cli.store_rows(p.root) == before and not fs.maintenance_active(p)
        assert not list((p.root / ".recalith" / "state").glob("restore-*"))
    finally:
        lock.release()
    with pytest.raises(RecalithError):
        service.restore(osc.context(p.root), kept, expected_digest=old.manifest_digest)  # not an operator


def test_suppression_happens_before_the_restored_store_is_served(tmp_path):
    """At the swap, the staged store already holds the tombstones and no forgotten text; hooks skip delivery meanwhile."""
    b, old, kept = _kept_then_forgotten(tmp_path)
    p = b.p
    seen: dict[str, object] = {}

    def at_swap(_name: str) -> None:
        staged = list((p.root / ".recalith" / "state").glob("restore-*.sqlite"))
        seen["staged"] = len(staged)
        seen["hits"] = fs._db_hits(staged[0], fs.MARK) if staged else None
        reply, out = ds.hook(p, ds.in_session(wks.record("lifecycle", "UserPromptSubmit"), wks.session_id(45), prompt="Which port does the fixture listen on? port 8123"))
        seen["delivery"] = (reply["delivery"].get("reason"), out)

    failpoints.arm(failpoints.RESTORE_BEFORE_SWAP, at_swap)
    service.restore(fs.operator(b), kept, expected_digest=old.manifest_digest)
    assert seen == {"staged": 1, "hits": [], "delivery": ("maintenance_in_progress", [])}


def test_interrupted_restore_is_recovered_before_the_worker_serves(tmp_path):
    """A restore that stops after staging leaves the old live store serving nothing new; the worker's start finishes it."""
    b, old, kept = _kept_then_forgotten(tmp_path, deliver=False)
    p = b.p

    def stop(_name: str) -> None:
        raise RuntimeError("interrupted after the swap")

    failpoints.arm(failpoints.RESTORE_AFTER_SWAP, stop)
    with pytest.raises(RuntimeError):
        service.restore(fs.operator(b), kept, expected_digest=old.manifest_digest)
    assert fs.maintenance_active(p)
    assert not [loc for loc in fs.marker_locations(p.root) if "memory.sqlite" in loc]
    p.drain()
    assert not fs.maintenance_active(p) and fs.marker_locations(p.root) == []
    assert not list((p.root / ".recalith" / "state").glob("restore-*")) and not (p.root / forget.RESTORE_JOURNAL).exists()


def test_restore_rejects_a_backup_of_another_installation(tmp_path):
    """A verified backup of another installation is refused before anything changes (exit 2 class)."""
    b = fs.build(tmp_path, deliver=False)
    other = fs.build(tmp_path, "other", deliver=False)
    made = backup.create(other.p.ctx, tmp_path / "other-backup")
    before = cli.store_rows(b.p.root)
    with pytest.raises(RecalithError) as refused:
        service.restore(fs.operator(b), Path(made.location), expected_digest=made.manifest_digest)
    assert refused.value.code == "invalid_schema" and ("backup_foreign_project" in refused.value.message or "backup_foreign_installation" in refused.value.message)
    assert cli.store_rows(b.p.root) == before
    assert os.path.exists(made.location) and json.loads((Path(made.location) / "manifest.json").read_text(encoding="utf-8"))["artifact_type"] == "backup"
