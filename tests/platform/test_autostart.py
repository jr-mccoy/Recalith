"""Task 17 preview: project startup is the hook-started worker; a copy or a move never auto-starts (A03, A45).

Preview's startup route is the registered internal hook start (SYSTEM_SPEC
§6.1, decision 0006): the next project activity starts the installation's
pinned worker. Per-project OS startup entries (``integrate --autostart``)
are full-only and reported unavailable (decision 0018). These tests run the
real hook entry (``python -I -m recalith.fast.entry``) on real Claude Code
2.1.301 payloads in a host-marked environment, as the host runs it; every
worker a test starts is stopped at teardown.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest

import claude_fixtures as cf
import worker_hosts as wh
from recalith import service
from recalith.contracts.common import Actor
from recalith.core import identity
from recalith.fast import process_env, spool
from recalith.operations import autostart

READER = Actor(kind="host_agent", id="t", channel="cli")


@pytest.fixture
def started():
    roots: list[Path] = []
    yield roots
    leftovers = [str(r) for r in roots if not wh.stop_worker(r)]
    assert not leftovers, f"workers did not stop on request and were killed: {leftovers}"


def _hook(replayer: cf.Replay, root: Path, tmp: Path, name: str) -> dict:
    reply = tmp / f"{name}-{time.monotonic_ns()}.json"
    proc, _ = cf.run_hook(root, replayer.prepare(wh.start_record()), event="SessionStart", reply=reply, env=wh.marked_env())
    assert proc.returncode == 0 and proc.stdout == b"" and proc.stderr == b"", proc.stderr[-2000:]  # the host's nonblocking success
    return json.loads(reply.read_text(encoding="utf-8"))


def _nothing_started(*roots: Path) -> None:
    for root in roots:
        assert not process_env.worker_running(root), root
        assert not (root / ".recalith" / "run" / process_env.START_STAMP).exists(), root


def _ready_segments(root: Path) -> int:
    return len(spool.ready_segments(spool.SpoolDirs(root)))


def test_copied_installation_does_not_autostart(tmp_path, started):
    """A copy of a live installation (private state included) never starts a worker, neither its own nor the original's."""
    replayer = cf.Replay(tmp_path / "replay")
    wh.enable_autostart(replayer)
    original = replayer.root
    copy = tmp_path / "copy"
    shutil.copytree(original, copy)
    started.extend([original, copy])
    reply = _hook(replayer, copy, tmp_path, "copy")
    assert reply["worker"] is None and reply["receipt"] is None and "installation_relocated" in reply["degradations"]
    _nothing_started(original, copy)
    assert _ready_segments(copy) == 0 and _ready_segments(original) == 0  # nothing captured into either store
    with pytest.raises(Exception) as refused:
        identity.resolve_installation(copy, actor=READER)
    assert getattr(refused.value, "code", None) == "installation_relocated"
    # Positive control: the same payload at the original starts the original's worker (registered start path).
    statuses = wh.start_via_hook(lambda: _hook(replayer, original, tmp_path, "original")["worker"])
    assert statuses[-1] in ("worker_started", "worker_independence_degraded"), statuses
    assert wh.wait_running(original) is not None
    assert not process_env.worker_running(copy) and not (copy / ".recalith" / "run" / process_env.START_STAMP).exists()


def test_moved_installation_does_not_autostart_until_rebound_and_reintegrated(tmp_path, started):
    """A moved checkout needs an operator rebind; even then the stale hook manifest keeps capture off (health says so)."""
    replayer = cf.Replay(tmp_path / "replay")
    wh.enable_autostart(replayer)
    moved = tmp_path / "moved"
    os.rename(replayer.root, moved)
    started.append(moved)
    reply = _hook(replayer, moved, tmp_path, "moved")
    assert reply["worker"] is None and "installation_relocated" in reply["degradations"]
    _nothing_started(moved)
    rebound = service.rebind(moved, Actor(kind="operator", id="terminal", channel="cli"))
    rep = service.health(service.resolve(moved, actor=READER), inherited=cf.child_env())
    assert rep.capabilities["capture"].state == "unavailable" and "hook_context_relocated" in rep.capabilities["capture"].reason_codes
    assert rep.capabilities["recovery"].coverage["startup"]["registered_hook_start"] == "relocated"
    reply = _hook(replayer, moved, tmp_path, "rebound")
    assert reply["worker"] is None and "installation_relocated" in reply["degradations"]
    _nothing_started(moved)
    assert rebound.installation_id == replayer.ctx.installation_id


def test_recreated_checkout_keeps_the_hook_off(tmp_path, started):
    """A checkout recreated at the same path (new directory, private state carried over) resolves, yet its hook stays off.

    Synthetic: the operator moved the tree away and copied it back to the
    same path, so the path still names the recorded workspace while the
    directory is a different filesystem object than the manifest records.
    """
    replayer = cf.Replay(tmp_path / "replay")
    wh.enable_autostart(replayer)
    root = replayer.root
    started.append(root)
    aside = tmp_path / "aside"
    os.rename(root, aside)
    shutil.copytree(aside, root)
    shutil.rmtree(aside)
    ctx = service.resolve(root, actor=READER)  # the path is the recorded root: resolution succeeds
    reply = _hook(replayer, root, tmp_path, "recreated")
    assert reply["worker"] is None and "installation_relocated" in reply["degradations"]
    _nothing_started(root)
    rep = service.health(ctx, inherited=cf.child_env())
    assert rep.capabilities["capture"].state == "unavailable" and "hook_context_relocated" in rep.capabilities["capture"].reason_codes
    assert rep.capabilities["recovery"].coverage["startup"]["registered_hook_start"] == "relocated"
    assert "hook_context_relocated" in rep.capabilities["recovery"].reason_codes and rep.autonomous_ready is False


def test_os_startup_entries_are_full_only(tmp_path):
    """Per-project OS startup entries are reported unavailable (full-only); the hook start is preview's route."""
    replayer = cf.Replay(tmp_path / "replay")
    ctx = replayer.ctx
    report = autostart.startup_report(ctx)
    assert report["os_startup_entries"] == {"state": "unavailable", "reason": "deferred_full_release"}
    assert report["registered_hook_start"] == "not_registered" and report["copy_adoption"] == "refused"
    wh.enable_autostart(replayer)
    assert autostart.startup_report(ctx)["registered_hook_start"] == "registered"


def test_hook_started_worker_is_reported(tmp_path, started):
    """A45 composition: health reports the hook-started worker's own state and independence, then its stop."""
    replayer = cf.Replay(tmp_path / "replay")
    wh.enable_autostart(replayer)
    root = replayer.root
    started.append(root)
    statuses = wh.start_via_hook(lambda: _hook(replayer, root, tmp_path, "start")["worker"])
    assert statuses[-1] in ("worker_started", "worker_independence_degraded"), statuses
    own = wh.wait_running(root)
    assert own is not None
    rep = service.health(service.resolve(root, actor=READER), inherited=cf.child_env())
    assert rep.worker_state in ("running", "idle", "degraded", "budget_paused")
    worker = rep.capabilities["recovery"].coverage["worker"]
    assert worker["running"] is True and worker["spawned_by"] == "hook" and worker["independence"] == own["spawn"]["state"]
    if own["spawn"]["state"] != "detached":
        assert "worker_independence_degraded" in rep.capabilities["recovery"].reason_codes
    assert wh.stop_worker(root)
    rep = service.health(service.resolve(root, actor=READER), inherited=cf.child_env())
    assert rep.worker_state == "stopped" and rep.capabilities["recovery"].coverage["worker"]["running"] is False
