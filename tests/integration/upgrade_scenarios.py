"""Test-only builders for Task 17 full: the preview-to-full profile transition (A02, A40 full; decision 0026).

Real inputs: preview stores built by ``retention_scenarios.build`` (real
Claude 2.1.301 payloads through the adapter, ingestion and typed reduction;
claims admitted through the real extraction/review path with recorded
proposals; the typed declaration through the guarded service), a real
forget through the service, and the real transition
(``operations.upgrade.transition``) acting on the live installation. The
supplied wheel is a **synthetic artifact**: a file named as this engine's
wheel whose digest the test computes (the fixtures run from the source tree,
``provisioning = "source_tree"``); the transition verifies its name, version
and digest, never installs it.

**Controlled time.** As in the retention tests: the transition and the
worker run at an explicit moment ahead of every capture (``rsn.day``).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import retention_scenarios as rsn  # first: puts tests/, tests/integration and tests/platform on sys.path
import operation_scenarios as osc  # noqa: E402
from recalith import __version__  # noqa: E402
from recalith.contracts.common import RecordRef, new_id  # noqa: E402
from recalith.contracts.privacy import ForgetRequest, ForgetSelector  # noqa: E402
from recalith.storage import db, records  # noqa: E402

SCENARIO = "upgrade.json"
TRANSITION_KIND = "profile_transition"


def wheel(directory: Path, version: str = __version__, content: bytes = b"synthetic recalith wheel for the transition tests\n") -> tuple[Path, str]:
    """A synthetic artifact named as ``version``'s wheel, and its SHA-256 (the operator's expected digest)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"recalith-{version}-py3-none-any.whl"
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest()


def forget_claim(root: Path, claim_id: str) -> Any:
    """A real forget of one claim through the guarded service (preview, then apply with its digest)."""
    from recalith import service

    ctx = osc.operator(root)
    revision = osc.head_ref(root, "claim", claim_id).revision
    selector = ForgetSelector(record_refs=[RecordRef(kind="claim", id=claim_id, revision=revision)])
    preview = service.preview_forget(ctx, selector)
    return service.apply_forget(ctx, ForgetRequest(selector=selector, preview_digest=preview.preview_digest))


def project_profile(root: Path) -> str | None:
    import tomllib

    raw = tomllib.loads((root / ".recalith" / "project.toml").read_text(encoding="utf-8"))
    return raw.get("release_profile")


def store_profile(root: Path) -> str | None:
    try:
        conn = sqlite3.connect((root / ".recalith" / db.STATE_DB).as_uri() + "?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        return conn.execute("SELECT release_profile FROM installation_meta").fetchone()[0]
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def ids(root: Path) -> dict[str, Any]:
    """Every identifier the transition must preserve (A02 full)."""
    ctx = osc.context(root)
    with db.open_store(ctx, readonly=True) as store, store.read() as v:
        meta = v.execute("SELECT project_id, installation_id FROM installation_meta").fetchone()
        return {
            "project": meta[0], "installation": meta[1],
            "workspaces": sorted(r[0] for r in v.execute("SELECT workspace_id FROM workspaces")),
            "sources": sorted(r[0] for r in v.execute("SELECT source_id FROM capture_sources")),
            "sessions": sorted(r[0] for r in v.execute("SELECT session_id FROM sessions")),
            "events": sorted(r[0] for r in v.execute("SELECT event_id FROM events")),
            "claims": sorted(v.execute("SELECT claim_id, revision, status FROM claim_heads").fetchall()),
            "claim_revisions": sorted(v.execute("SELECT claim_id, revision FROM claim_revisions").fetchall()),
            "tasks": sorted(v.execute("SELECT task_id, revision, status FROM task_heads").fetchall()),
            "episodes": sorted(v.execute("SELECT episode_id, revision, state FROM episode_heads").fetchall()),
            "roots": sorted(v.execute("SELECT root_class_id FROM root_classes").fetchall()),
            "root_members": sorted(v.execute("SELECT * FROM root_event_members").fetchall()),
            "aliases": sorted(v.execute("SELECT * FROM root_aliases").fetchall()),
            "tombstones": sorted(v.execute("SELECT tombstone_id, epoch FROM tombstones").fetchall()),
            "tombstone_targets": sorted(r[0] for r in v.execute("SELECT target_id FROM tombstone_targets")),
        }


def claims(view: Any, *, portable: bool = False) -> list[tuple]:
    """Claim heads with their status and guidance fields; ``portable`` drops the build-time support moment (compared across projects)."""
    out = []
    for claim_id, revision, status in view.execute("SELECT claim_id, revision, status FROM claim_heads").fetchall():
        body = records.body(view, "claim", claim_id, revision)
        if body is None:
            out.append(("" if portable else claim_id, revision, status, None, None, None, None))  # a forgotten head: content-free
            continue
        out.append((body["proposition"], revision, status, body["strength"], body["freshness"], body["evidence_availability"], None if portable else body.get("last_supported_at")))
    return sorted(out, key=json.dumps)


def semantic(root: Path, *, portable: bool = False) -> dict[str, Any]:
    """The installation's serving state in installation-independent terms (no backup rows, revisions or timestamps of bookkeeping)."""
    ctx = osc.context(root)
    with db.open_store(ctx, readonly=True) as store, store.read() as v:
        profile, policy, tombstone_epoch = v.execute("SELECT release_profile, policy_revision, tombstone_epoch FROM installation_meta").fetchone()
        out = {
            "profile": profile, "policy_revision": policy, "tombstone_epoch": tombstone_epoch,
            "payloads": sorted(v.execute("SELECT source_event_key, payload_state FROM events").fetchall()),
            "claims": claims(v, portable=portable),
            "tombstones": v.execute("SELECT COUNT(*) FROM tombstones").fetchone()[0],
            "targets": v.execute("SELECT COUNT(*) FROM tombstone_targets").fetchone()[0],
            "jobs": sorted(v.execute("SELECT kind, state FROM jobs WHERE kind != 'maintenance'").fetchall()),
            "transitions": v.execute("SELECT COUNT(*) FROM operations WHERE kind = ?", (TRANSITION_KIND,)).fetchone()[0],
            "chain_entries": v.execute("SELECT COUNT(*) FROM revision_chain").fetchone()[0] > 0,
            **rsn.capsule_view(v),
        }
    out["project_toml"] = project_profile(root)
    return out


def leftovers(root: Path) -> list[str]:
    """Staged stores, partial files, the journal and the maintenance marker left in the installation."""
    base = root / ".recalith"
    found = [p.relative_to(root).as_posix() for p in (base / "state").glob("upgrade-*")]
    for name in ("run/upgrade.json", "run/maintenance.json"):
        if (base / name).exists():
            found.append(f".recalith/{name}")
    return sorted(found)


def forget_project(tmp: Path, name: str) -> Any:
    """``forget_scenarios.build`` (the marker session and everything derived from it) with its task forgotten for real."""
    import forget_scenarios as fs

    b = fs.build(tmp, name, deliver=False)
    _preview, result = fs.forget(b, fs.task_selector(b))
    assert result.purge_state == "completed" and result.tombstone_epoch >= 1
    return b


CHILD = r"""
import json, sys
spec = json.loads(sys.argv[1])
sys.path[:0] = spec["paths"]
from pathlib import Path
from recalith.contracts.common import Actor
from recalith.core import identity
from recalith.fast import failpoints
from recalith.operations import upgrade
failpoints.arm(spec["failpoint"], failpoints.kill)
ctx = identity.resolve_installation(Path(spec["root"]), actor=Actor(kind="operator", id="terminal", channel="cli"))
upgrade.transition(ctx, Path(spec["wheel"]), expected_digest=spec["digest"], release_profile="full", now=spec["now"])
sys.exit(0)
"""


def killed_transition(root: Path, failpoint: str, wheel_path: Path, digest: str, *, now: str | None = None) -> int:
    """Run the operator's transition in a real child process that dies abruptly at ``failpoint`` (``os._exit``)."""
    import subprocess
    import sys

    import claude_fixtures as cf

    here = Path(__file__).resolve()
    paths = [cf.SRC, str(here.parent), str(here.parents[1]), str(here.parents[1] / "platform")]
    spec = {"paths": paths, "root": str(root), "failpoint": failpoint, "wheel": str(wheel_path), "digest": digest, "now": now}
    proc = subprocess.run([sys.executable, "-I", "-c", CHILD, json.dumps(spec)], capture_output=True, env=cf.child_env(), timeout=300, check=False)
    return proc.returncode


# --------------------------------------------------------------------------
# The kill/restart scenario (tests/integration/test_worker.py)
#
# A preview store with every live owner of A35 and the capsule owners
# (``rsn.build(capsules=True)``), a previous forget of the candidate claim
# (a real forget: tombstone, purge, post-forget backup) and the synthetic wheel.
# The script: the worker's recovery (an interrupted transition finishes or is
# rolled back), the operator's transition at day 181 when the store is not yet
# full (re-running the command that did not complete), then a worker drain at
# day 181 under the full profile (pending jobs resume; the 30-day sweep).


def crash_project(tmp: Path, name: str) -> Path:
    b = rsn.build(tmp, name, open_work=False, capsules=True)
    p = b.p
    forget_claim(p.root, b.claims["candidate"])
    path, digest = wheel(tmp / f"{name}-wheel")
    spec = {"clock": rsn.day(p, 181), "wheel": str(path), "digest": digest, "preview": None, "expect": None}
    (p.root / SCENARIO).write_text(json.dumps(spec), encoding="utf-8")
    spec["preview"] = semantic(p.root)  # the complete previous preview state a kill may leave
    (p.root / SCENARIO).write_text(json.dumps(spec), encoding="utf-8")
    return p.root


def scenario(root: Path) -> dict[str, Any] | None:
    path = root / SCENARIO
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def expect(root: Path, reference: dict[str, Any]) -> None:
    spec = scenario(root)
    assert spec is not None
    spec["expect"] = {"payloads": reference["payloads"]}
    (root / SCENARIO).write_text(json.dumps(spec), encoding="utf-8")


def run_script(root: Path, spec: dict[str, Any]) -> None:
    from recalith.controller import worker
    from recalith.fast import process_env
    from recalith.operations import upgrade

    import worker_scenarios as ws

    ctx = osc.operator(root)
    upgrade.recover(ctx)  # what the worker's start runs first (as below); here before the operator's command
    if store_profile(root) != "full":
        result = upgrade.transition(ctx, Path(spec["wheel"]), expected_digest=spec["digest"], release_profile="full", now=spec["clock"])
        assert result.state == "activated", result
    w = worker.Worker(osc.context(root), clock=ws.FakeClock(spec["clock"]), owner=f"driver:{new_id('act')[4:12]}")
    lock = process_env.InstallationLock(root)
    assert lock.try_acquire(), "another worker holds the installation"
    try:
        w.recover_maintenance()
        w.startup()
        ws.drain(w)
    finally:
        w.close()
        lock.release()


def outstanding(root: Path) -> str:
    """``1`` while transition or post-transition work is owed, judged from effects (read-only).

    Owed: the live store or the tracked ``project.toml`` not yet ``full``; the
    maintenance marker present (delivery paused) or a staged store left; a
    payload the reference run expired or compacted still available.
    """
    spec = scenario(root) or {}
    if store_profile(root) != "full" or project_profile(root) != "full" or leftovers(root):
        return "1"
    want = dict(map(tuple, (spec.get("expect") or {}).get("payloads") or []))
    try:
        conn = sqlite3.connect((root / ".recalith" / db.STATE_DB).as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            now = dict(conn.execute("SELECT source_event_key, payload_state FROM events").fetchall())
        finally:
            conn.close()
    except sqlite3.Error:
        return "1"
    return "1" if any(state != "available" and now.get(key) == "available" for key, state in want.items()) else "0"


def kill_invariants(root: Path, spec: dict[str, Any]) -> list[str]:
    """After a kill, only the complete previous preview state or a complete full state may serve, newest tombstones applied."""
    from recalith.storage import integrity

    problems = []
    now = json.loads(json.dumps(semantic(root)))  # the recorded preview state went through JSON
    preview = spec["preview"]
    if now["profile"] == "claude_preview":
        if {k: v for k, v in now.items() if k != "project_toml"} != {k: v for k, v in preview.items() if k != "project_toml"}:
            problems.append("preview_state_changed")
        if now["project_toml"] != "claude_preview":
            problems.append("project_toml_ahead_of_store")
    elif now["profile"] == "full":
        report = integrity.verify(osc.context(root), full=True, persist=False)
        if report["state"] != "verified" or report["pre_baseline_history"] != "not_chained":
            problems.append("chain_not_verified")
        if now["transitions"] != 1:
            problems.append("transition_not_recorded_once")
        kept = {k for k, s in preview["payloads"] if s in ("available", "capsule_only")}
        states = dict(now["payloads"])
        if any(states.get(k) not in ("available", "capsule_only", "expired") for k in kept):
            problems.append("payload_lost")
        if [c for c in now["claims"]] != [c for c in preview["claims"]]:
            problems.append("claims_changed")
        if not all(ok for _p, ok in now["evidence"]):
            problems.append("live_evidence_unresolvable")
    else:
        problems.append("store_unreadable")
    if now["tombstones"] < preview["tombstones"] or now["targets"] < preview["targets"]:
        problems.append("tombstones_lost")
    return problems


__all__ = ["wheel", "semantic", "ids", "crash_project", "run_script", "outstanding", "kill_invariants"]
