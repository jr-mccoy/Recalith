"""Task 17: independent installations across pinned builds and schemas, and the preview-to-full transition (A02, A40).

**Preview (A02/A40 preview variants).** Two independent installations with
independently pinned build/schema fixtures (A: a genuine schema-9 store built
from the migration files 0001–0009 with an ``engine.lock`` pinned to an older
release; B: the current schema and engine), and recovery of A leaves B
untouched (A's interrupted backup and restore, made by real child processes
killed with ``os._exit``, are recovered by A's real worker process while B's
every file stays byte-identical). The CLI's ``upgrade`` forms pass the guard
and answer ``capability_unavailable`` in this build.

**Full (A02/A40 full variants; decision 0026).** The in-place preview-to-full
profile transition (``operations.upgrade.transition``, SYSTEM_SPEC §10.1) on
real preview stores (``retention_scenarios.build``: real Claude 2.1.301
payloads, claims admitted through the real extraction/review path, the typed
declaration through the guarded service, a real forget): exclusive
maintenance with the worker stopped, a verified backup with the current
tombstone ledger, a staged store (profile, policy/guidance fences, the chain's
activation baseline, exact capsules or retained pins under the target
retention policy), capability registration, the activation journal, one
atomic activation and its recovery. The transition is reached through the
operations function: like ``init --release-profile full`` (decision 0024), the
guarded CLI and the service keep answering ``capability_unavailable`` until
the full release (decision 0026). The supplied wheel is a synthetic artifact
named as this engine's wheel (the fixtures run from the source tree); the
transition verifies its name, version and digest. Not built and still
pending: the side-by-side engine switch between two releases.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import health_scenarios as hs  # first: puts tests/, tests/integration and tests/platform on sys.path
import cli_scenarios as cs  # noqa: E402
import consolidation_scenarios as csn  # noqa: E402
import forget_scenarios as fs  # noqa: E402
import operation_scenarios as osc  # noqa: E402
import retention_scenarios as rsn  # noqa: E402
import upgrade_scenarios as us  # noqa: E402
import worker_hosts as wh  # noqa: E402
import worker_scenarios as ws  # noqa: E402
import working_scenarios as wks  # noqa: E402
from recalith import __version__, service  # noqa: E402
from recalith.contracts.common import ReadSet, Scope  # noqa: E402
from recalith.contracts.health import REQUIRED_CAPABILITIES  # noqa: E402
from recalith.controller import jobs, worker  # noqa: E402
from recalith.core import identity  # noqa: E402
from recalith.errors import RecalithError  # noqa: E402
from recalith.fast import failpoints, process_env  # noqa: E402
from recalith.operations import health as operations_health  # noqa: E402
from recalith.operations import upgrade  # noqa: E402
from recalith.privacy import capsules, forget, retention  # noqa: E402
from recalith.storage import backup, db, integrity  # noqa: E402

PENDING = "pending: the side-by-side engine switch between two releases is not built (Task 17 full remainder, decision 0026)"
# What the transition compacts at day 181 and which pins it keeps, with their reasons (decision 0025 §3; test_capsules).
COMPACTED = ("decision", "typed", "quote", "edit", "observed", "sub_result")
DEFERRED = {
    "seq": "unlocated_reference", "write": "unlocated_reference", "read": "unlocated_reference", "pass": "unlocated_reference", "grep": "unlocated_reference",
    "forward": "not_a_root", "echo": "not_a_root", "fail": "owed_work", "long": "owed_work", "missing": "owed_work", "ls": "owed_work", "sleep": "owed_work",
    "b_start": "open_working_context", "b_prompt": "open_working_context", "b_call": "open_working_context", "b_result": "open_working_context",
}


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
    assert rep.capabilities["recovery"].coverage["upgrade"] == {"journal": None, "last": None}  # no transition ran or is journaled




# ---------------------------------------------------------------------------
# A02/A40 full: the preview-to-full profile transition (decision 0026)


@pytest.fixture(autouse=True)
def _disarm():
    failpoints.disarm_all()
    yield
    failpoints.disarm_all()


def transit(root: Path, tmp: Path, now: str | None = None, *, profile: str | None = "full", ctx=None, **kw):
    path, digest = us.wheel(tmp / "wheel")
    return upgrade.transition(ctx or osc.operator(root), path, expected_digest=digest, release_profile=profile, now=now, **kw)


def transition_op(root: Path) -> dict:
    with db.open_store(osc.context(root), readonly=True) as store, store.read() as v:
        rows = v.execute("SELECT inputs, reason FROM operations WHERE kind = ?", (us.TRANSITION_KIND,)).fetchall()
    assert len(rows) == 1, rows
    return json.loads(rows[0][0])


def engine_files(root: Path) -> dict[str, str]:
    """The pinned engine's tracked files and the provisioned runtimes (none in a source-tree fixture)."""
    tree = hs.tree_digest(root)
    runtime = sorted(p.name for p in (root / ".recalith" / "runtime").iterdir()) if (root / ".recalith" / "runtime").is_dir() else []
    return {**{k: v for k, v in tree.items() if k.startswith((".recalith/bin/", ".recalith/engine.lock"))}, "runtime": json.dumps(runtime)}


def full_store_checks(root: Path) -> dict:
    report = integrity.verify(osc.context(root), full=True)
    assert report["state"] == "verified" and report["complete_coverage"] is True, report["findings"]
    assert report["baseline"]["reason"] == "activation" and report["pre_baseline_history"] == "not_chained"
    return report


def test_preview_to_full_preserves_live_evidence_and_ids(tmp_path):
    """A02 full: every ID, every claim and its strength, and live evidence beyond day 181 survive; exact capsules or kept pins.

    The transition runs at day 181 on a preview store holding every live owner
    of A35 and the capsule owners. It writes no claim, task or episode
    revision and no new support (root tables unchanged); pinned payloads past
    the target window become exact capsules where every live reference is kept
    exactly and stay pinned with a reported reason otherwise; unpinned payloads
    are left to the next sweep under the new policy; the chain's activation
    baseline verifies with the earlier history reported ``not_chained``. The
    worker's first full-profile sweep then expires only unpinned payloads.
    """
    b = rsn.build(tmp_path, "upgrade", capsules=True)
    p, ev = b.p, b.events
    now = rsn.day(p, 181)
    ids_before, before = us.ids(p.root), us.semantic(p.root)
    engine_before = engine_files(p.root)
    expired_before = sorted(k for k, s in before["payloads"] if s == "expired")
    assert before["profile"] == "claude_preview" and not before["chain_entries"] and before["capsules"] == []

    result = transit(p.root, tmp_path, now)

    assert (result.state, result.source_profile, result.target_profile, result.error_codes) == ("activated", "claude_preview", "full", [])
    assert (result.source_engine, result.target_engine, result.preserved_installation_id) == (__version__, __version__, p.ctx.installation_id)
    with p.view() as v:
        row = v.execute("SELECT state, location, manifest_digest FROM backups WHERE backup_id = ?", (result.verified_backup_id,)).fetchone()
        first = v.execute("SELECT entry_hash FROM revision_chain WHERE sequence = 1").fetchone()[0]
    assert row[0] == "verified" and backup.verify(Path(row[1]), expected_digest=row[2], ctx=p.ctx).manifest.artifact_id == result.verified_backup_id
    assert result.baseline_digest == first
    # Every identifier is preserved; no record revision, root or alias was written; tombstones as they were.
    assert us.ids(p.root) == ids_before
    after = us.semantic(p.root)
    assert (after["profile"], after["project_toml"], after["policy_revision"], after["transitions"]) == ("full", "full", before["policy_revision"] + 1, 1)
    assert after["claims"] == before["claims"]  # status, strength, freshness, availability and last support: unchanged
    for role in COMPACTED:
        assert rsn.payload_state(p, ev[role]) == ("capsule_only", False), role
    for role in DEFERRED:
        assert rsn.payload_state(p, ev[role]) == ("available", True), role
    assert sorted(k for k, s in after["payloads"] if s == "expired") == expired_before  # the transition expires nothing itself
    assert all(ok for _p, ok in after["evidence"]) and len(after["capsules"]) == len(COMPACTED) and all(sealed for _k, sealed, _s in after["capsules"])
    full_store_checks(p.root)
    with p.view() as v:
        summary = retention.summary(v, p.ctx, now=now, config=retention.retention_config(p.ctx))
        held = retention.pinned_events(v) & {e for e, s in rsn.states(p).items() if s == "available"}
    assert result.retained_pin_count == summary.deferred_compaction_count == len(held) and {ev[r] for r in DEFERRED} <= held
    # The autonomy log: one content-free entry with the profiles, the retention outcome and the deferral reasons.
    op = transition_op(p.root)
    assert (op["source_profile"], op["target_profile"], op["backup_id"]) == ("claude_preview", "full", result.verified_backup_id)
    assert op["retention"]["unpinned_event_payload"] == {"before": {"days": 180, "source": "profile_default"}, "after": {"days": 30, "source": "profile_default"}}
    assert op["compaction"]["compacted_count"] == len(COMPACTED) and op["compaction"]["retained_pin_count"] == result.retained_pin_count
    for reason in set(DEFERRED.values()):  # every pin the fixture keeps on purpose is counted under its reason (others may share it)
        assert op["compaction"]["deferred"].get(reason, 0) >= sum(1 for r in DEFERRED.values() if r == reason), reason
    assert rsn.PROPS["quote"] not in json.dumps(op) and rsn.A55_QUOTE not in json.dumps(op)
    # Nothing else of the installation moved: the engine pin and launchers, no leftovers, the last result recorded.
    assert engine_files(p.root) == engine_before and us.leftovers(p.root) == []
    assert upgrade.last_result(p.root)["state"] == "activated"
    rep = operations_health.health(p.ctx, inherited=cs.base_env(), now=now)
    assert rep.release_profile == "full" and rep.installation.schema_state == "current"
    assert rep.capabilities["capsules"].state == "healthy" and rep.capabilities["revision_chain"].state == "healthy", rep.capabilities["revision_chain"]
    assert rep.capabilities["recovery"].coverage["upgrade"]["journal"] is None and rep.capabilities["recovery"].coverage["upgrade"]["last"]["state"] == "activated"
    # The worker's first full-profile sweep: unpinned payloads expire, live evidence stays, nothing is weakened.
    with db.open_store(p.ctx) as store:
        did = retention.run(store, p.ctx, identity.installation_config(p.root), now=now)
    swept = us.semantic(p.root)
    assert did["sweep"]["expired_count"] > 0 and swept["claims"] == before["claims"] and all(ok for _p, ok in swept["evidence"])
    for role in (*COMPACTED, *DEFERRED):
        assert rsn.payload_state(p, ev[role])[0] in ("capsule_only", "available"), role
    full_store_checks(p.root)


def test_profile_transition_honors_retention_override(tmp_path):
    """Profile defaults move from 180 to 30 days; explicit operator overrides in ``project.toml`` stay as they were.

    A: ``[retention]`` overrides the unpinned window (120 days) and the backup
    window (45 days). B: defaults only. Before the transition an edit of B's
    tracked ``release_profile`` changes nothing (the store's profile governs,
    decision 0026). At day 100 the transition compacts nothing in A (its 120-day
    window) and compacts B's pinned whole statements; afterwards B's sweep
    expires its unpinned payloads and A's keeps them.
    """
    a = rsn.build(tmp_path, "override", open_work=False)
    b = rsn.build(tmp_path, "defaults", open_work=False)
    toml = a.p.root / ".recalith" / "project.toml"
    toml.write_text(toml.read_text(encoding="utf-8") + "\n[retention]\nunpinned_event_payload = 120\nprivate_backups = 45\n", encoding="utf-8")
    original = toml.read_text(encoding="utf-8")
    cfg = identity.installation_config(a.p.root).retention
    assert (cfg.unpinned_event_payload.days, cfg.unpinned_event_payload.source, cfg.private_backups.days, cfg.private_backups.source) == (120, "operator_override", 45, "operator_override")
    # A tracked profile edit activates nothing: the store's profile decides the defaults.
    b_toml = b.p.root / ".recalith" / "project.toml"
    b_original = b_toml.read_bytes()
    b_toml.write_text(b_original.decode("utf-8").replace('release_profile = "claude_preview"', 'release_profile = "full"'), encoding="utf-8")
    edited = identity.installation_config(b.p.root)
    assert (edited.release_profile, edited.retention.unpinned_event_payload.days, edited.worker.idle_poll_seconds) == ("claude_preview", 180, 5)
    assert service.health(b.p.ctx, inherited=cs.base_env()).release_profile == "claude_preview"
    assert retention.retention_config(b.p.ctx).unpinned_event_payload.days == 180
    b_toml.write_bytes(b_original)
    # Only retention values, as positive whole days, are accepted as overrides.
    for bad in ("\n[retention]\nunpinned_days = 3\n", "\n[retention]\nunpinned_event_payload = 0\n", "\n[retention]\nunpinned_event_payload = \"30\"\n"):
        b_toml.write_bytes(b_original + bad.encode("utf-8"))
        with pytest.raises(RecalithError) as exc:
            identity.installation_config(b.p.root)
        assert exc.value.code == "invalid_schema", bad
    b_toml.write_bytes(b_original)

    now_a, now_b = rsn.day(a.p, 100), rsn.day(b.p, 100)
    ra, rb = transit(a.p.root, tmp_path / "a", now_a), transit(b.p.root, tmp_path / "b", now_b)
    assert ra.state == rb.state == "activated"
    after_a, after_b = identity.installation_config(a.p.root), identity.installation_config(b.p.root)
    assert after_a.release_profile == after_b.release_profile == "full"
    assert (after_a.retention.unpinned_event_payload.days, after_a.retention.unpinned_event_payload.source) == (120, "operator_override")
    assert (after_a.retention.private_backups.days, after_a.retention.private_backups.source) == (45, "operator_override")
    assert (after_a.retention.episode_after_closure.days, after_a.retention.episode_after_closure.source) == (180, "profile_default")
    assert (after_b.retention.unpinned_event_payload.days, after_b.retention.unpinned_event_payload.source) == (30, "profile_default")
    assert toml.read_text(encoding="utf-8") == original.replace('release_profile = "claude_preview"', 'release_profile = "full"')  # only the profile line changed
    assert transition_op(a.p.root)["retention"]["unpinned_event_payload"] == {"before": {"days": 120, "source": "operator_override"}, "after": {"days": 120, "source": "operator_override"}}
    assert transition_op(a.p.root)["retention"]["private_backups"] == {"before": {"days": 45, "source": "operator_override"}, "after": {"days": 45, "source": "operator_override"}}
    assert us.semantic(a.p.root)["capsules"] == [] and transition_op(a.p.root)["compaction"]["compacted_count"] == 0
    assert len(us.semantic(b.p.root)["capsules"]) >= 2  # the declaration and the typed statement
    for built, now, expect_expiry in ((a, now_a, False), (b, now_b, True)):
        before = dict(us.semantic(built.p.root)["payloads"])
        with db.open_store(built.p.ctx) as store:
            did = retention.run(store, built.p.ctx, identity.installation_config(built.p.root), now=now)
        expired = [k for k, s in us.semantic(built.p.root)["payloads"] if s == "expired" and before[k] != "expired"]
        assert bool(expired) is expect_expiry, (built.p.root.name, did)


def test_failed_capsule_transition_keeps_pin(tmp_path):
    """A capsule that cannot reproduce a cited span is never created: the pin stays, deferral is reported, nothing is weakened.

    Synthetic store state (as in ``test_capsules``): the located Edit quote's
    normalized links carry a locator digest its payload no longer matches. The
    transition still activates; the other exact references are compacted.
    """
    b = rsn.build(tmp_path, "pin", capsules=True)
    p, ev = b.p, b.events
    claim_id = b.claims["located"]
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        rows = txn.execute("SELECT link_id, locator FROM evidence_links WHERE owner_kind = 'claim' AND owner_id = ? AND target_id = ?", (claim_id, ev["edit"])).fetchall()
        assert len(rows) == 2
        for link_id, locator in rows:
            loc = json.loads(locator)
            loc["text_digest"] = "0" * 64
            txn.execute("UPDATE evidence_links SET locator = ? WHERE link_id = ?", (json.dumps(loc, sort_keys=True, separators=(",", ":")), link_id))
        txn.mutated(serving_relevant=False)
    guidance = rsn.guidance(p)
    now = rsn.day(p, 181)
    result = transit(p.root, tmp_path, now)
    assert result.state == "activated"
    assert rsn.payload_state(p, ev["edit"]) == ("available", True) and capsules.capsule_id(ev["edit"]) not in {c for c in _capsule_ids(p)}
    for role in COMPACTED:
        if role != "edit":
            assert rsn.payload_state(p, ev[role]) == ("capsule_only", False), role
    op = transition_op(p.root)
    assert op["compaction"]["deferred"].get("locator_unresolved") == 1 and op["compaction"]["compacted_count"] == len(COMPACTED) - 1
    with p.view() as v:
        held = retention.pinned_events(v) & {e for e, s in rsn.states(p).items() if s == "available"}
    assert ev["edit"] in held and result.retained_pin_count == len(held)
    assert rsn.guidance(p) == guidance  # neither this claim nor any other is weakened
    assert all(ok for _p, ok in us.semantic(p.root)["evidence"])
    full_store_checks(p.root)


def _capsule_ids(p) -> list[str]:
    with p.view() as v:
        return [r[0] for r in v.execute("SELECT capsule_id FROM evidence_capsules").fetchall()]


@pytest.mark.parametrize("failpoint", [
    failpoints.UPGRADE_AFTER_BACKUP, failpoints.UPGRADE_AFTER_REGISTRATION, failpoints.UPGRADE_AFTER_BASELINE,
    failpoints.UPGRADE_AFTER_CAPSULES, failpoints.UPGRADE_AFTER_STAGE, failpoints.UPGRADE_BEFORE_SWAP,
])
def test_failure_before_activation_rolls_back(tmp_path, failpoint):
    """A40 full: a failure at the backup, registration, chain baseline, capsule/link preparation, staging or before the swap.

    The live store is never touched before activation: the result is
    ``rolled_back`` (a verified backup exists), the previous complete preview
    state serves, no staged store, journal or marker is left, and a re-run
    activates.
    """
    p = hs.project(tmp_path, "rollback")
    before, engine_before = us.semantic(p.root), engine_files(p.root)

    def boom(name):
        raise OSError(f"injected at {name}")

    failpoints.arm(failpoint, boom)
    result = transit(p.root, tmp_path, rsn.day(p, 181))  # past the 30-day window: the staged compaction transaction runs
    assert result.state == "rolled_back" and result.verified_backup_id is not None and result.error_codes, result
    assert us.semantic(p.root) == before and engine_files(p.root) == engine_before and us.leftovers(p.root) == []
    assert upgrade.last_result(p.root)["state"] == "rolled_back"
    rep = service.health(p.ctx, inherited=cs.base_env())
    assert rep.release_profile == "claude_preview" and rep.privacy_maintenance.maintenance_marker == "absent"
    again = transit(p.root, tmp_path, rsn.day(p, 181))
    assert again.state == "activated" and us.semantic(p.root)["profile"] == "full"
    full_store_checks(p.root)


def test_backup_failure_is_not_activated(tmp_path):
    """No verified backup, no migration: a failed backup leaves the store untouched (``not_activated``, no backup ID)."""
    p = hs.project(tmp_path, "nobackup")
    before = us.semantic(p.root)

    def boom(name):
        raise OSError(f"injected at {name}")

    failpoints.arm(failpoints.BACKUP_AFTER_MANIFEST, boom)
    result = transit(p.root, tmp_path)
    assert (result.state, result.verified_backup_id, result.baseline_digest) == ("not_activated", None, None) and "backup_failed" in result.error_codes
    assert us.semantic(p.root) == before and us.leftovers(p.root) == []


def test_failure_after_activation_is_completed_by_recovery(tmp_path):
    """After the swap the store is the complete full store; recovery completes the rest (record, checkpoint, marker)."""
    p = hs.project(tmp_path, "forward")

    def boom(name):
        raise OSError(f"injected at {name}")

    failpoints.arm(failpoints.UPGRADE_AFTER_SWAP, boom)
    result = transit(p.root, tmp_path)
    assert result.state == "recovery_required" and result.verified_backup_id is not None
    assert us.store_profile(p.root) == "full" and us.project_profile(p.root) == "claude_preview"
    full_store_checks(p.root)  # a complete full store serves, never a half-migrated one
    rep = service.health(p.ctx, inherited=cs.base_env())
    assert rep.release_profile == "full" and "upgrade_recovery_pending" in rep.capabilities["recovery"].reason_codes
    assert rep.privacy_maintenance.maintenance_marker == "active" and rep.capabilities["recovery"].coverage["upgrade"]["journal"] == "activated"
    done = upgrade.recover(osc.operator(p.root))
    assert done["upgrade"] == "activated" and us.project_profile(p.root) == "full" and us.leftovers(p.root) == []
    assert upgrade.last_result(p.root)["state"] == "activated"
    rep = service.health(p.ctx, inherited=cs.base_env())
    assert "upgrade_recovery_pending" not in rep.capabilities["recovery"].reason_codes and rep.privacy_maintenance.maintenance_marker == "absent"


INTERRUPTIONS = [  # (failpoint, the state serving after the kill, the state after recovery)
    (failpoints.UPGRADE_AFTER_BACKUP, "claude_preview", "rolled_back"), (failpoints.UPGRADE_AFTER_BASELINE, "claude_preview", "rolled_back"),
    (failpoints.UPGRADE_AFTER_STAGE, "claude_preview", "rolled_back"), (failpoints.UPGRADE_BEFORE_SWAP, "claude_preview", "activated"),
    (failpoints.UPGRADE_AFTER_SWAP, "full", "activated"), (failpoints.UPGRADE_AFTER_RECORD, "full", "activated"),
]


@pytest.mark.parametrize(("failpoint", "serving", "recovered"), INTERRUPTIONS)
def test_interrupted_profile_transition_restores_complete_state(tmp_path, started, failpoint, serving, recovered):
    """A40 full: a real operator child killed (``os._exit``) around activation; the installation's real worker recovers it.

    Before the journal's ``activating`` record (the commit point) the complete
    previous preview state serves and recovery rolls the transition back (the
    operator re-runs it); from that record on recovery activates the staged
    store, which the swap fence admits only if the live store is unchanged.
    Only a complete preview or a complete full store ever serves, and the
    newest tombstones (a forget made before the transition) stay applied.
    """
    b = us.forget_project(tmp_path, "interrupted")
    root = b.p.root
    before = us.semantic(root)
    path, digest = us.wheel(tmp_path / "wheel")
    assert us.killed_transition(root, failpoint, path, digest) == failpoints.KILL_STATUS
    killed = us.semantic(root)
    assert killed["profile"] == serving and killed["tombstones"] == before["tombstones"] >= 1
    if serving == "claude_preview":
        assert killed == before  # the live store was never touched
    else:
        full_store_checks(root)
        assert killed["claims"] == before["claims"]
    rep = service.health(b.p.ctx, inherited=cs.base_env())
    assert rep.capabilities["recovery"].coverage["upgrade"]["journal"] is not None and "upgrade_recovery_pending" in rep.capabilities["recovery"].reason_codes
    assert rep.privacy_maintenance.maintenance_marker == "active" and rep.privacy_maintenance.delivery_paused
    # The installation's own worker (a real process, the fresh worker environment) recovers at its start.
    started.append(root)
    proc = wh.start_direct(root)
    assert wh.wait_for(lambda: not upgrade.pending(root) and wh.status(root), 60), proc.stderr
    assert wh.stop_worker(root)
    assert us.leftovers(root) == [] and upgrade.last_result(root)["state"] == recovered
    if recovered == "rolled_back":
        assert us.semantic(root) == before and transit(root, tmp_path).state == "activated"
    after = us.semantic(root)
    assert (after["profile"], after["project_toml"], after["transitions"], after["tombstones"]) == ("full", "full", 1, before["tombstones"])
    assert after["claims"] == before["claims"] and fs.marker_locations(root) == []
    full_store_checks(root)


def test_interrupted_upgrade_restores_previous_engine(tmp_path, started):
    """The interrupted operation leaves the previous engine and its complete state: pin, launchers, runtimes, ``project.toml``, store.

    This slice switches no engine (target engine = pinned engine, decision
    0026), so what is checked is that an interruption after the staged store
    is complete changes none of the engine's files and the worker's recovery
    discards the staged store; the side-by-side switch between two releases
    remains pending.
    """
    p = hs.project(tmp_path, "engine")
    root = p.root
    engine_before, toml_before, before = engine_files(root), (root / ".recalith" / "project.toml").read_bytes(), us.semantic(root)
    path, digest = us.wheel(tmp_path / "wheel")
    assert us.killed_transition(root, failpoints.UPGRADE_AFTER_STAGE, path, digest) == failpoints.KILL_STATUS
    assert [x for x in us.leftovers(root) if x.endswith(".sqlite")], "the staged store is complete when the kill lands"
    assert engine_files(root) == engine_before and (root / ".recalith" / "project.toml").read_bytes() == toml_before
    started.append(root)
    proc = wh.start_direct(root)
    assert wh.wait_for(lambda: not upgrade.pending(root) and wh.status(root), 60), proc.stderr
    assert wh.stop_worker(root)
    assert us.leftovers(root) == [] and us.semantic(root) == before and engine_files(root) == engine_before
    rep = service.health(p.ctx, inherited=cs.base_env())
    assert rep.installation.pinned_engine_version == __version__ and "engine_pin_mismatch" not in rep.capabilities["recovery"].reason_codes


def test_transition_applies_previous_forget_and_resurrects_nothing(tmp_path):
    """A previous forget's tombstones are carried over; neither the store, the staged copy nor the new backup holds forgotten content.

    The forgotten source's replays (the same real records again) stay
    suppressed in the full store.
    """
    b = us.forget_project(tmp_path, "forgotten")
    p = b.p
    before = us.ids(p.root)
    assert fs.marker_locations(p.root) == []
    result = transit(p.root, tmp_path, rsn.day(p, 181))
    assert result.state == "activated"
    after = us.ids(p.root)
    assert (after["tombstones"], after["tombstone_targets"]) == (before["tombstones"], before["tombstone_targets"])
    assert fs.marker_locations(p.root) == []  # the live store, files and every recorded backup, the upgrade's included
    with p.view() as v:
        counts = (v.execute("SELECT COUNT(*) FROM events").fetchone()[0], v.execute("SELECT COUNT(*) FROM source_conflicts").fetchone()[0])
    p.send(wks.variant(wks.record("lifecycle", "UserPromptSubmit"), prompt=fs.SAID, session=fs.SESSION_F))
    csn.send(p, "toolu_probe_0001", "fm", command=f"echo {fs.MARK}", session=fs.SESSION_F)
    p.drain()
    with p.view() as v:
        assert (v.execute("SELECT COUNT(*) FROM events").fetchone()[0], v.execute("SELECT COUNT(*) FROM source_conflicts").fetchone()[0]) == counts
    assert fs.marker_locations(p.root) == []
    full_store_checks(p.root)


def test_pending_jobs_are_fenced_then_resume(tmp_path):
    """Pending and leased work is carried over; a pre-transition read set is fenced; the restarted worker resumes the jobs."""
    root = ws.init_project(tmp_path, "jobs")
    queued = ws.enqueue_model_job(root, "extract_claims", key="queued")
    leased_id = ws.enqueue_model_job(root, "extract_claims", key="leased")
    ctx = ws.context(root)
    with db.open_store(ctx) as store:
        leased = jobs.lease_next(ctx, owner="worker:dead", now=ws.START, kinds={"extract_claims"}, store=store)
    assert leased is not None
    old = ReadSet(workspace_id=ctx.workspace_id, policy_revision=1, tombstone_epoch=0)
    with db.open_store(ctx, readonly=True) as store, store.read() as v:
        jobs_before = sorted(v.execute("SELECT job_id, kind, state FROM jobs WHERE kind != 'maintenance'").fetchall())
    assert transit(root, tmp_path, ws.START).state == "activated"
    with db.open_store(ctx, readonly=True) as store, store.read() as v:
        assert sorted(v.execute("SELECT job_id, kind, state FROM jobs WHERE kind != 'maintenance'").fetchall()) == jobs_before
    with db.open_store(ctx) as store, pytest.raises(RecalithError, match="policy or tombstone"):
        with store.transaction(expected=old):
            pass  # a proposal prepared before the transition is fenced by the policy revision

    def prepare(store, job, rounds):
        meta = store.meta()
        request = ws.request_for(store, job, rounds)
        return request.model_copy(update={"read_set": ReadSet(workspace_id=ctx.workspace_id, policy_revision=meta.policy_revision, tombstone_epoch=meta.tombstone_epoch)})

    backend = ws.FakeBackend()
    w = worker.Worker(ws.context(root), clock=ws.FakeClock(ws.START), model=ws.runtime(backend, prepare), owner="worker:after")
    lock = process_env.InstallationLock(root)
    assert lock.try_acquire()
    try:
        assert w.recover_maintenance() == {}
        w.startup()
        ws.drain(w)
    finally:
        w.close()
        lock.release()
    assert sorted(job for _purpose, job in backend.calls) == sorted([queued, leased_id])
    with db.open_store(ctx, readonly=True) as store, store.read() as v:
        assert {r[0] for r in v.execute("SELECT state FROM jobs WHERE job_id IN (?, ?)", (queued, leased_id)).fetchall()} == {"completed"}
    full_store_checks(root)


def test_capabilities_are_reregistered_honestly(tmp_path):
    """Full makes features eligible, never active: Codex/MCP stay unavailable; delivery keeps exactly its certification.

    A synthetic, fully certified preview installation (``health_scenarios.ready``)
    stays ready; its uncertified optional paths stay unavailable; the route is
    probed again (version observed). A request-capture-only installation's
    start/prompt delivery stays unavailable.
    """
    p, env = hs.ready(tmp_path, "caps")
    before = hs.report(p, env)
    assert before.autonomous_ready
    result = transit(p.root, tmp_path / "w1", inherited=env)
    assert result.state == "activated"
    after = hs.report(p, env)
    assert after.release_profile == "full" and after.autonomous_ready and after.readiness == "ready"
    for name in REQUIRED_CAPABILITIES:
        assert after.capabilities[name].state == before.capabilities[name].state == "healthy", name
    for name in ("pre_action_delivery", "compact_delivery"):
        assert after.capabilities[name].state == "unavailable", name
    for name in ("codex_capture", "codex_delivery", "generic_json", "mcp", "export", "import", "ipc_wake", "session_worker", "side_by_side_upgrade"):
        assert after.capabilities[name].state == "unavailable" and "not_built_in_this_engine" in after.capabilities[name].reason_codes, name
    assert after.capabilities["capsules"].state == "healthy" and after.capabilities["revision_chain"].state == "healthy"
    registry = transition_op(p.root)["capabilities"]
    assert registry["provider"]["state"] == "certified" and registry["provider"]["observed_version"] == "9.9.9"
    assert registry["delivery"] == {"session_start": "certified", "prompt": "certified", "pre_action": "unavailable", "compact_restore": "unavailable"}
    assert set(registry["eligible"]) == {"revision_chain", "capsules"} and {"codex_capture", "mcp"} <= set(registry["not_activated"])
    # Request capture only: untested delivery is never reported healthy.
    q = hs.project(tmp_path, "capture-only")
    hs.integrate(q)
    hs.certify_host(q, mode="request_capture", delivery={"session_start": "unavailable", "prompt": "unavailable"})
    assert transit(q.root, tmp_path / "w2").state == "activated"
    rep = hs.report(q)
    for name in ("start_delivery", "prompt_delivery", "pre_action_delivery", "compact_delivery"):
        assert rep.capabilities[name].state == "unavailable", name
    assert not rep.autonomous_ready and transition_op(q.root)["capabilities"]["delivery"]["prompt"] == "unavailable"


def test_downgrade_by_flag_is_refused(tmp_path):
    """Full → preview is never a flag change: ``policy_refused`` (exit 6) before any effect; same-profile is unavailable."""
    root = cs.init_project(tmp_path)
    tok = token(root, tmp_path)
    assert transit(root, tmp_path / "w").state == "activated"
    before = us.semantic(root)
    with pytest.raises(RecalithError) as refused:
        transit(root, tmp_path / "w", profile="claude_preview")
    assert refused.value.code == "policy_refused"
    with pytest.raises(RecalithError) as same:
        transit(root, tmp_path / "w", profile=None)
    assert same.value.code == "capability_unavailable"
    path, digest = us.wheel(tmp_path / "w")
    with pytest.raises(RecalithError) as by_service:
        service.upgrade(osc.operator(root), path, expected_digest=digest, release_profile="claude_preview")
    assert by_service.value.code == "policy_refused"
    result = cs.cli(root, "--json", "--operator-token-file", str(tok), "upgrade", "--wheel", str(path), "--expected-digest", digest, "--release-profile", "claude_preview")
    assert result.code == 6 and result.obj["error"] == "policy_refused" and "refusal" not in result.obj, result.stdout
    marked = cs.cli(root, "--json", "--operator-token-file", str(tok), "upgrade", "--wheel", str(path), "--expected-digest", digest, "--release-profile", "full", env=cs.marked_env("CLAUDECODE"))
    assert marked.code == 6 and marked.obj["refusal"]["category"], marked.stdout  # the operator guard refuses a host-marked caller first
    assert us.semantic(root) == before and us.leftovers(root) == []


def test_transition_requires_the_operator_and_a_verified_artifact(tmp_path, monkeypatch):
    """Refusals before any effect: a non-operator actor, a bad digest or name, another engine version, a foreign pinned artifact, an older schema."""
    root = cs.init_project(tmp_path)
    before = hs.tree_digest(root)
    path, digest = us.wheel(tmp_path / "w")
    cases = [
        (dict(ctx=osc.context(root)), "policy_refused"),
        (dict(expected_digest="f" * 64), "invalid_schema"),
        (dict(expected_digest="not-a-digest"), "invalid_schema"),
    ]
    for kw, code in cases:
        ctx = kw.pop("ctx", osc.operator(root))
        with pytest.raises(RecalithError) as exc:
            upgrade.transition(ctx, path, expected_digest=kw.get("expected_digest", digest), release_profile="full")
        assert exc.value.code == code, (kw, exc.value)
    renamed = tmp_path / "w" / "engine.whl"
    renamed.write_bytes(path.read_bytes())
    other, other_digest = us.wheel(tmp_path / "w9", version="9.9.9")
    for wheel, d, code in ((renamed, digest, "invalid_schema"), (other, other_digest, "capability_unavailable")):
        with pytest.raises(RecalithError) as exc:
            upgrade.transition(osc.operator(root), wheel, expected_digest=d, release_profile="full")
        assert exc.value.code == code, wheel.name
    # A wheel-provisioned pin names its artifact: the supplied wheel must be exactly that artifact.
    lock = root / ".recalith" / "engine.lock"
    lock_bytes = lock.read_bytes()
    lock.write_text(lock_bytes.decode("utf-8").replace('provisioning = "source_tree"', f'provisioning = "wheel"\nartifact_sha256 = "{"a" * 64}"'), encoding="utf-8")
    with pytest.raises(RecalithError) as exc:
        upgrade.transition(osc.operator(root), path, expected_digest=digest, release_profile="full")
    assert exc.value.code == "capability_unavailable"
    lock.write_bytes(lock_bytes)
    assert hs.tree_digest(root) == before
    # The service and the CLI keep answering unavailable until the full release (decision 0026).
    assert upgrade.FULL_RELEASE_AVAILABLE is False
    with pytest.raises(RecalithError) as exc:
        service.upgrade(osc.operator(root), path, expected_digest=digest, release_profile="full")
    assert exc.value.code == "capability_unavailable"
    with pytest.raises(RecalithError) as exc:
        service.upgrade(osc.context(root), path, expected_digest=digest, release_profile="full")
    assert exc.value.code == "policy_refused"
    # A schema-9 store needs the general schema upgrade (not built): refused, byte-identical.
    old = hs.schema9_installation(tmp_path, "old", monkeypatch)
    old_tree = hs.tree_digest(old)
    with pytest.raises(RecalithError) as exc:
        upgrade.transition(identity.resolve_installation(old, actor=osc.OPERATOR), path, expected_digest=digest, release_profile="full")
    assert exc.value.code == "capability_unavailable" and "schema" in exc.value.message
    assert hs.tree_digest(old) == old_tree
    assert hs.tree_digest(root) == before


def files_outside_live_state(root: Path) -> dict[str, str]:
    """Digests of B's files except what its running worker owns (``run/``: its lock, status and scratch; ``state/``: the live store).

    Those directories are skipped before any file is opened: on Windows the
    running worker holds a byte-range lock on ``run/worker.lock``, so even
    reading it fails. B's store is compared through ``semantic`` instead.
    """
    import hashlib

    base = root / ".recalith"
    skip = (base / "run", base / "state")
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(base.rglob("*")) if p.is_file() and not any(d in p.parents for d in skip)}


def test_upgrade_A_leaves_B_running(tmp_path, started):
    """A02 full: A's transition stops A's own worker and changes nothing of B, whose real worker keeps running."""
    a, b = hs.project(tmp_path, "a"), hs.project(tmp_path, "b")
    for p in (a, b):
        started.append(p.root)
        wh.start_direct(p.root)
        assert wh.wait_running(p.root, 60)
    b_pid = wh.status(b.root)["pid"]
    b_before, b_store = files_outside_live_state(b.root), us.semantic(b.root)
    result = transit(a.root, tmp_path, stop_wait=30)
    assert result.state == "activated" and not process_env.worker_running(str(a.root))
    assert us.semantic(a.root)["profile"] == "full"
    assert process_env.worker_running(str(b.root)) and wh.wait_running(b.root, 10)["pid"] == b_pid
    assert files_outside_live_state(b.root) == b_before
    assert us.semantic(b.root) == b_store and us.store_profile(b.root) == "claude_preview"


def test_upgrade_is_refused_while_a_restore_is_journaled_and_restore_while_an_upgrade_is(tmp_path):
    """One maintenance at a time: an interrupted restore must finish before a transition, and the reverse."""
    p = hs.project(tmp_path, "exclusive")
    good = backup.create(p.ctx, tmp_path / "good")
    assert hs.killed_at(p.root, failpoints.RESTORE_BEFORE_SWAP, "restore", source=Path(good.location), digest=good.manifest_digest) == failpoints.KILL_STATUS
    with pytest.raises(RecalithError) as exc:
        transit(p.root, tmp_path)
    assert exc.value.code == "capability_unavailable"
    forget.recover_restore(p.ctx)
    path, digest = us.wheel(tmp_path / "wheel")
    assert us.killed_transition(p.root, failpoints.UPGRADE_AFTER_STAGE, path, digest) == failpoints.KILL_STATUS
    with pytest.raises(RecalithError) as exc:
        service.restore(osc.operator(p.root), Path(good.location), expected_digest=good.manifest_digest)
    assert exc.value.code == "capability_unavailable" and "upgrade" in exc.value.message
