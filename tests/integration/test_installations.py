"""Task 2: independent installations and the transactional store (A01–A04 preview slices, A53 launcher)."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import factories as f
from recalith.contracts.common import Actor, ReadSet, RecordRef, new_id
from recalith.contracts.config import ProjectConfig
from recalith.contracts.events import EventEnvelope
from recalith.core import identity
from recalith.errors import RecalithError
from recalith.storage import db, repository

OPERATOR = Actor(kind="operator", id="tester", channel="cli")
AGENT = Actor(kind="host_agent", id="agent", channel="cli")
ROOT = Path(__file__).resolve().parents[2]


def make_project(parent: Path, name: str, project_id: str | None = None):
    root = parent / name
    root.mkdir()
    ctx = identity.initialize_installation(root, ProjectConfig.defaults_for(project_id or new_id("proj")))
    return identity.resolve_installation(root, actor=OPERATOR)


def event_for(ctx, key: str = "tool_finished-1", **overrides) -> EventEnvelope:
    data = f.envelope(
        source_event_key=key,
        project_id=ctx.project_id,
        installation_id=ctx.installation_id,
        workspace_id=ctx.workspace_id,
        event_id=f.event_id(key, installation=ctx.installation_id),
    )
    data.update(overrides)
    if "payload" in overrides:
        data["payload_digest"] = f.digest_of(overrides["payload"])
    return EventEnvelope.model_validate(data)


def insert(ctx, env):
    with db.open_store(ctx) as store, store.transaction() as txn:
        return repository.insert_event(txn, ctx, env)


# ---------------------------------------------------------------- required tests


def test_two_installations_have_separate_ids_and_databases(tmp_path):
    a = make_project(tmp_path, "project-a")
    b = make_project(tmp_path, "project-b")
    assert a.installation_id != b.installation_id and a.project_id != b.project_id
    assert not os.path.samefile(a.root / ".recalith/state/memory.sqlite", b.root / ".recalith/state/memory.sqlite")
    # Identical source keys, titles and paths with opposite content in each project.
    ev_a = event_for(a, payload=f.tool_payload(arguments={"command": "make build-a"}))
    ev_b = event_for(b, payload=f.tool_payload(arguments={"command": "make build-b"}))
    assert insert(a, ev_a) == ("inserted", ev_a.event_id)
    assert insert(b, ev_b) == ("inserted", ev_b.event_id)
    assert ev_a.event_id != ev_b.event_id  # ids are installation-derived
    for mine, theirs in ((a, ev_b), (b, ev_a)):
        with db.open_store(mine, readonly=True) as store:
            assert repository.get_event(store, theirs.event_id) is None
            assert repository.count_rows(store, "events") == 1


def test_foreign_installation_is_rejected(tmp_path):
    a = make_project(tmp_path, "a")
    b = make_project(tmp_path, "b")
    with pytest.raises(RecalithError, match="foreign_installation"):
        insert(a, event_for(b))
    # Own installation id but a workspace from another installation.
    with pytest.raises(RecalithError, match="foreign_installation"):
        insert(a, event_for(a, workspace_id=b.workspace_id))
    # A context for A pointed at B's root never opens B's store for A.
    with pytest.raises(RecalithError, match="foreign_installation"):
        db.open_store(a.model_copy(update={"root": b.root}))
    # Event id derived for another installation's identity.
    with pytest.raises(RecalithError, match="event_identity_conflict"):
        insert(a, event_for(a, event_id=f.event_id("tool_finished-1", installation=b.installation_id)))
    with db.open_store(a, readonly=True) as store:
        assert repository.count_rows(store, "events") == 0


def test_unknown_schema_cannot_write(tmp_path):
    a = make_project(tmp_path, "a")
    b = make_project(tmp_path, "b")
    path = a.root / ".recalith/state/memory.sqlite"
    raw = sqlite3.connect(path)
    raw.execute("UPDATE installation_meta SET schema_version = ?", (db.SCHEMA_VERSION + 1,))
    raw.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    raw.commit()
    raw.close()
    before = path.read_bytes()
    for readonly in (False, True):
        with pytest.raises(RecalithError, match="invalid_schema"):
            db.open_store(a, readonly=readonly)
    assert path.read_bytes() == before  # no best-effort write into an unknown schema
    # The other installation is unaffected (A02 preview variant).
    assert insert(b, event_for(b))[0] == "inserted"


def test_path_escape_is_refused(tmp_path):
    from recalith.core.paths import PathPolicy

    a = make_project(tmp_path, "a")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    policy = PathPolicy([a.workspace_root])
    for bad in ("../outside.txt", str(outside), "src/../../outside.txt"):
        with pytest.raises(RecalithError, match="policy_refused"):
            policy.authorize(bad)


# ---------------------------------------------------------------- clone, move, copy (A03 preview)


def tracked_clone(src: Path, dst: Path) -> None:
    """What `git clone` brings: only the tracked .recalith files."""
    (dst / ".recalith").mkdir(parents=True)
    for name in ("project.toml", "engine.lock", ".gitignore"):
        shutil.copy2(src / ".recalith" / name, dst / ".recalith" / name)
    shutil.copytree(src / ".recalith" / "bin", dst / ".recalith" / "bin")


def test_clone_keeps_project_id_and_gets_new_installation(tmp_path):
    a = make_project(tmp_path, "origin")
    clone = tmp_path / "clone"
    tracked_clone(a.root, clone)
    with pytest.raises(RecalithError, match="capability_unavailable"):
        identity.resolve_installation(clone, actor=OPERATOR)
    config = identity.load_project_config(identity.Layout(clone))
    c = identity.initialize_installation(clone, config)
    assert c.project_id == a.project_id and c.installation_id != a.installation_id
    with pytest.raises(RecalithError, match="policy_refused"):
        identity.initialize_installation(clone, ProjectConfig.defaults_for(new_id("proj")))


def test_move_requires_operator_rebind(tmp_path):
    a = make_project(tmp_path, "before")
    moved = tmp_path / "after"
    os.rename(a.root, moved)
    with pytest.raises(RecalithError, match="installation_relocated"):
        identity.resolve_installation(moved, actor=OPERATOR)
    with pytest.raises(RecalithError, match="policy_refused"):
        identity.rebind_installation(moved, actor=AGENT)
    ctx = identity.rebind_installation(moved, actor=OPERATOR)
    assert ctx.installation_id == a.installation_id and ctx.root == moved.resolve()
    with db.open_store(ctx, readonly=True) as store:
        meta = store.meta()
        assert meta.store_revision == 1
        assert repository.count_rows(store, "operations") == 1
    assert insert(ctx, event_for(ctx))[0] == "inserted"


def test_copy_never_starts_a_second_writer(tmp_path):
    a = make_project(tmp_path, "original")
    copy = tmp_path / "copy"
    shutil.copytree(a.root, copy)
    with pytest.raises(RecalithError, match="installation_relocated"):
        identity.resolve_installation(copy, actor=OPERATOR)
    with pytest.raises(RecalithError, match="installation_relocated"):
        identity.rebind_installation(copy, actor=OPERATOR)
    with pytest.raises(RecalithError, match="policy_refused"):
        identity.discard_copied_private_state(a.root, actor=OPERATOR)  # never the original
    identity.discard_copied_private_state(copy, actor=OPERATOR)
    fresh = identity.initialize_installation(copy, identity.load_project_config(identity.Layout(copy)))
    assert fresh.installation_id != a.installation_id and fresh.project_id == a.project_id
    assert identity.resolve_installation(a.root, actor=OPERATOR).installation_id == a.installation_id


def test_preview_installation_features_are_unavailable():
    for feature in ("workspace attach", "project fork", "shared integration"):
        err = identity.unavailable_in_preview(feature)
        assert err.code == "capability_unavailable" and err.exit_code == 4


# ---------------------------------------------------------------- init safety


def test_init_never_overwrites_an_existing_store(tmp_path):
    a = make_project(tmp_path, "a")
    path = a.root / ".recalith/state/memory.sqlite"
    insert(a, event_for(a))
    with pytest.raises(RecalithError, match="policy_refused"):
        identity.initialize_installation(a.root, ProjectConfig.defaults_for(a.project_id))
    with db.open_store(a, readonly=True) as store:
        assert repository.count_rows(store, "events") == 1
    assert path.exists()


def test_interrupted_init_completes_with_the_same_identity(tmp_path):
    a = make_project(tmp_path, "a")
    (a.root / ".recalith/local.toml").unlink()  # crash after the store rename
    again = identity.initialize_installation(a.root, ProjectConfig.defaults_for(a.project_id))
    assert again.installation_id == a.installation_id and again.workspace_id == a.workspace_id


def test_network_filesystem_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(identity, "filesystem_type", lambda path: "nfs4")
    root = tmp_path / "remote"
    root.mkdir()
    with pytest.raises(RecalithError, match="storage_failure"):
        identity.initialize_installation(root, ProjectConfig.defaults_for(new_id("proj")))
    assert not (root / ".recalith").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_private_state_has_restrictive_permissions(tmp_path):
    a = make_project(tmp_path, "a")
    base = a.root / ".recalith"
    assert (base / "local.toml").stat().st_mode & 0o777 == 0o600
    assert (base / "state/memory.sqlite").stat().st_mode & 0o777 == 0o600
    for name in identity.PRIVATE_DIRS:
        assert (base / name).stat().st_mode & 0o777 == 0o700
    assert os.access(base / "bin/recalith", os.X_OK)


def test_tracked_files_are_exactly_the_portable_ones(tmp_path):
    git = shutil.which("git")
    if git is None:
        pytest.skip("git unavailable")
    a = make_project(tmp_path, "a")
    subprocess.run([git, "init", "-q", str(a.root)], check=True)
    out = subprocess.run([git, "-C", str(a.root), "status", "--porcelain", "--untracked-files=all"], capture_output=True, text=True, check=True).stdout
    listed = sorted(line[3:] for line in out.splitlines())
    assert listed == [".recalith/.gitignore", ".recalith/bin/recalith", ".recalith/bin/recalith-hook", ".recalith/bin/recalith-hook.cmd", ".recalith/bin/recalith.cmd", ".recalith/engine.lock", ".recalith/project.toml"]


# ---------------------------------------------------------------- store behavior


def test_store_connection_policy(tmp_path):
    a = make_project(tmp_path, "a")
    conn = db.connect(a.root / ".recalith/state/memory.sqlite")
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 250
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()
    expected = {"installation_meta", "workspaces", "sessions", "capture_sources", "source_conflicts", "root_classes", "root_members", "root_aliases", "task_boundaries", "task_binding_revisions", "task_binding_heads", "failure_triggers", "environment_observations", "review_batches", "events", "task_revisions", "task_heads", "episode_revisions", "episode_heads", "claim_revisions", "claim_heads", "evidence_links", "evidence_capsules", "dependencies", "relations", "jobs", "proposals", "operations", "revision_chain", "privacy_operations", "deliveries", "outcome_links", "tombstones", "imports", "exports", "backups", "provider_usage", "context_views", "lexical_index"}
    assert expected <= tables


def test_busy_writer_fails_within_busy_timeout(tmp_path):
    a = make_project(tmp_path, "a")
    blocker = db.connect(a.root / ".recalith/state/memory.sqlite")
    blocker.execute("BEGIN IMMEDIATE")
    try:
        with db.open_store(a) as store:
            start = time.monotonic()
            with pytest.raises(RecalithError, match="storage_failure"):
                with store.transaction():
                    pass
            assert time.monotonic() - start < 2.0  # bounded wait, never a hang
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()


def test_read_set_conflicts_refuse_application(tmp_path):
    a = make_project(tmp_path, "a")
    env = event_for(a)
    insert(a, env)
    good = ReadSet(entity_revisions=[RecordRef(kind="event", id=env.event_id, revision=1)], workspace_id=a.workspace_id, policy_revision=1, tombstone_epoch=0)
    with db.open_store(a) as store:
        with store.transaction(good):
            pass
        for bad in (
            good.model_copy(update={"policy_revision": 2}),
            good.model_copy(update={"tombstone_epoch": 1}),
            good.model_copy(update={"entity_revisions": [RecordRef(kind="claim", id=new_id("claim"), revision=1)]}),
        ):
            with pytest.raises(RecalithError, match="revision_conflict"):
                with store.transaction(bad):
                    pass


def test_duplicates_are_idempotent_and_conflicts_keep_the_original(tmp_path):
    a = make_project(tmp_path, "a")
    env = event_for(a)
    assert insert(a, env) == ("inserted", env.event_id)
    with db.open_store(a, readonly=True) as store:
        rev = store.meta().store_revision
    assert insert(a, env) == ("duplicate", env.event_id)
    changed = event_for(a, payload=f.tool_payload(exit_code=2, assertions=[]), event_id=env.event_id)
    outcome, conflict_id = insert(a, changed)
    assert outcome == "conflict" and conflict_id.startswith("conf_")
    assert insert(a, changed) == ("conflict", conflict_id)  # replay is idempotent
    with db.open_store(a, readonly=True) as store:
        assert repository.get_event(store, env.event_id).payload_digest == env.payload_digest
        assert repository.count_rows(store, "source_conflicts") == 1
        meta = store.meta()
    assert meta.store_revision == rev + 1  # duplicate: no revision; conflict: one
    assert meta.guidance_epoch == 1  # an unresolved conflict changes servable state


def test_concurrent_writers_serialize_revisions(tmp_path):
    a = make_project(tmp_path, "a")
    errors: list[BaseException] = []

    def writer(n: int) -> None:
        for i in range(10):
            for _ in range(50):
                try:
                    insert(a, event_for(a, key=f"w{n}-{i}"))
                    break
                except RecalithError as exc:
                    if exc.code != "storage_failure":
                        errors.append(exc)
                        return
                    time.sleep(0.01)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    with db.open_store(a, readonly=True) as store:
        assert repository.count_rows(store, "events") == 30
        assert store.meta().store_revision == 30


# ---------------------------------------------------------------- launcher and runtime (A53 preview)


def test_missing_runtime_launcher_is_explicit_and_downloads_nothing(tmp_path):
    a = make_project(tmp_path, "a")
    before = sorted(p.relative_to(a.root) for p in a.root.rglob("*"))
    if os.name == "nt":
        cmd = ["cmd", "/c", str(a.root / ".recalith/bin/recalith.cmd"), "status"]
    else:
        cmd = ["sh", str(a.root / ".recalith/bin/recalith"), "status"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env={"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")})
    assert result.returncode == 4
    assert "capability_unavailable" in result.stderr and result.stdout == ""
    after = sorted(p.relative_to(a.root) for p in a.root.rglob("*") if not p.name.startswith("memory.sqlite-"))
    assert [p for p in after if p not in before] == []


def test_bootstrap_refuses_digest_mismatch_and_missing_inputs(tmp_path):
    a = make_project(tmp_path, "a")
    wheel = tmp_path / "recalith-0.1.0.dev0-py3-none-any.whl"
    wheel.write_bytes(b"not really a wheel")
    house = tmp_path / "wheelhouse"
    house.mkdir()

    def run(*extra):
        return subprocess.run([sys.executable, str(ROOT / "bootstrap.py"), "install", "--project", str(a.root), *extra], capture_output=True, text=True, timeout=60)

    assert run("--wheel", str(wheel), "--expected-digest", "0" * 64, "--wheelhouse", str(house)).returncode == 2
    assert run("--wheel", str(tmp_path / "missing" / wheel.name), "--expected-digest", "0" * 64, "--wheelhouse", str(house)).returncode == 4
    assert run("--wheel", str(wheel), "--expected-digest", "not-a-digest", "--wheelhouse", str(house)).returncode == 2
    assert not any((a.root / ".recalith/runtime").iterdir())


@pytest.mark.skipif(not os.environ.get("RECALITH_TEST_WHEELHOUSE"), reason="set RECALITH_TEST_WHEEL and RECALITH_TEST_WHEELHOUSE to exercise real provisioning")
def test_bootstrap_provisions_pinned_runtime_offline(tmp_path):
    import hashlib

    wheel = Path(os.environ["RECALITH_TEST_WHEEL"])
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    a = make_project(tmp_path, "a")
    cmd = [sys.executable, str(ROOT / "bootstrap.py"), "install", "--project", str(a.root), "--wheel", str(wheel), "--expected-digest", digest, "--wheelhouse", os.environ["RECALITH_TEST_WHEELHOUSE"]]
    first = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert first.returncode == 0, first.stderr
    assert json.loads(subprocess.run(cmd, capture_output=True, text=True, timeout=600).stdout)["status"] == "already_provisioned"
    lock = (a.root / ".recalith/engine.lock").read_text(encoding="utf-8")
    assert f'artifact_sha256 = "{digest}"' in lock
    py = identity.Layout(a.root).runtime_python(json.loads(first.stdout)["version"])
    probe = subprocess.run([str(py), "-I", "-c", "import recalith.contracts, sys; print(sys.prefix)"], capture_output=True, text=True)
    assert probe.returncode == 0 and str(a.root) in probe.stdout
