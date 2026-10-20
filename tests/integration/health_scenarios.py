"""Test-only builders for Task 17: profile-aware health, readiness and independent operations.

Real inputs: every Claude event enters through the real 2.1.301 adapter
mapping, normalization, capture, ingestion and typed reduction
(``working_scenarios.Project``); the worker is the real worker; backups,
forgetting and restore are the real Task 15/16 paths; the CLI is a real
``recalith`` child process with an explicitly provisioned fixture token
(``cli_scenarios``).

**Synthetic states** (named at each use, never production evidence):

- :func:`certify_provider` writes a *controlled* ``.recalith/provider.json``
  whose certification record claims a live observation of a fake executable
  that only answers ``--version``; the selected key's value is assembled by
  concatenation. It stands in for the operator's certified route (B1 is
  open), exactly as the Task 7 unit fixtures do.
- :func:`certify_host` writes a *controlled* ``.recalith/host.json``
  (``HostCertification``), standing in for the record Task 13's real
  delivery certification will produce; no nonce protocol ran.
- :func:`integrate` writes the hook-context manifest with worker autostart
  and the delivery paths a Task 13 installation would enable.
- :func:`schema9_installation` builds a store at schema 9 from the real
  migration files 0001–0009 (the build of Task 15 core), with an
  ``engine.lock`` pinned to an older release: an independent pinned
  build/schema fixture, not an upgrade.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Iterable

import working_scenarios as wks  # first: puts tests/, tests/integration and tests/platform on sys.path
import claude_fixtures as cf  # noqa: E402
import operation_scenarios as osc  # noqa: E402
from recalith.capture.hooks import write_hook_context  # noqa: E402
from recalith.contracts.common import digest_of  # noqa: E402
from recalith.contracts.config import ProjectConfig, ProviderConfig  # noqa: E402
from recalith.core import identity  # noqa: E402
from recalith.providers import base, claude_cli  # noqa: E402
from recalith.storage import db  # noqa: E402

SELECTED = "ANTHROPIC_API_KEY"
KEY_VALUE = "health-" + "fixture-route"  # built by concatenation: never a credential-shaped literal
HOST_FILE = Path(".recalith") / "host.json"
DELIVERY_PATHS = ("session_start", "prompt", "pre_action", "compact_restore")
CAPABILITY_OF_PATH = {"session_start": "start_delivery", "prompt": "prompt_delivery", "pre_action": "pre_action_delivery", "compact_restore": "compact_delivery"}


def project(tmp: Path, name: str = "health", *, scenario: str | None = "lifecycle") -> wks.Project:
    """A real installation; with ``scenario`` its real 2.1.301 session is captured and reduced by the real worker."""
    p = wks.Project(tmp, name)
    if scenario:
        p.scenario(scenario)
        p.drain()
    return p


def integrate(p: wks.Project, *, paths: Iterable[str] = ("session_start", "prompt"), autostart: bool = True, host_version: str | None = cf.VERSION) -> None:
    """Synthetic: the hook manifest a Task 13 installation would write (autostart, installed delivery paths)."""
    write_hook_context(p.ctx, adapter_id="claude_code", host_version=host_version, worker_autostart=autostart, delivery_paths=list(paths))


def certify_host(
    p: wks.Project,
    *,
    delivery: dict[str, str] | None = None,
    command_rules: str = "installed",
    private_paths: str = "probed_limited",
    host_version: str = cf.VERSION,
    mode: str = "live",
    installation_id: str | None = None,
) -> Path:
    """Synthetic: a ``HostCertification`` record as Task 13 would produce it (no nonce protocol ran here)."""
    states = {"session_start": "certified", "prompt": "certified", "pre_action": "unavailable", "compact_restore": "unavailable"}
    states.update(delivery or {})
    record = {
        "certification_schema": 1, "installation_id": installation_id or p.ctx.installation_id, "host_id": "claude_code", "host_version": host_version,
        "mode": mode, "certified_at": "2026-10-20T00:00:00.000000Z", "report_digest": digest_of(["synthetic host certification", host_version]),
        "delivery": states, "command_rules": command_rules, "private_paths": private_paths,
    }
    path = p.root / HOST_FILE
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True))
    return path


def version_exe(tmp: Path, version: str = "9.9.9", name: str = "fake-claude") -> Path:
    """An executable that answers ``--version`` like the host CLI (and nothing else)."""
    tmp.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        exe = tmp / f"{name}.cmd"
        exe.write_text(f"@echo {version} (Claude Code)\r\n", encoding="utf-8")
    else:
        exe = tmp / name
        exe.write_text(f"#!/bin/sh\necho '{version} (Claude Code)'\n", encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return exe


def provider_config(p: wks.Project, executable: Path, *, certified: bool) -> ProviderConfig:
    data = {
        "provider_id": "claude_cli", "installation_id": p.ctx.installation_id, "backend": "claude_cli", "executable": str(executable), "configured_model": "explicit-model",
        "auth_route": "env_api_key", "auth_env_keys": [SELECTED], "expected_api_key_source": SELECTED, "invocation_args": list(claude_cli.ISOLATION_ARGS),
        "nonsecret_env": {"DISABLE_AUTOUPDATER": "1"}, "certification": {"certified": False, "mode": "request_capture"},
    }
    cfg = ProviderConfig.model_validate(data)
    if certified:
        cert = {
            "certified": True, "certified_at": "2026-10-20T00:00:00.000000Z", "host_version": "9.9.9", "report_digest": digest_of(["synthetic provider certification"]),
            "executable_sha256": base.executable_digest(str(executable)), "mode": "live", "operator_attestation": "checked_eligible",
            "auth_env_keys": [SELECTED], "expected_api_key_source": SELECTED, "invocation_digest": base.invocation_digest(cfg),
        }
        cfg = ProviderConfig.model_validate({**cfg.model_dump(mode="json"), "certification": cert})
    return cfg


def certify_provider(p: wks.Project, tmp: Path, *, certified: bool = True) -> dict[str, str]:
    """Synthetic: a controlled route record; returns the caller environment that carries the selected key."""
    exe = version_exe(tmp / "provider-bin")
    base.save_provider_config(p.root, provider_config(p, exe, certified=certified))
    return route_env()


def route_env(**extra: str) -> dict[str, str]:
    return {"PATH": os.environ.get("PATH", ""), SELECTED: KEY_VALUE, **extra}


def ready(tmp: Path, name: str = "health", *, paths: Iterable[str] = ("session_start", "prompt"), **host: Any) -> tuple[wks.Project, dict[str, str]]:
    """A real installation in a synthetic, fully certified preview state (see the module docstring)."""
    p = project(tmp, name)
    integrate(p, paths=paths)
    certify_host(p, **host)
    env = certify_provider(p, tmp / f"{name}-route")
    return p, env


def report(p: wks.Project | Path, env: dict[str, str] | None = None, **kw: Any):
    from recalith import service

    root = p.root if isinstance(p, wks.Project) else Path(p)
    return service.health(osc.context(root), inherited=route_env() if env is None else env, **kw)


def not_healthy(rep, names: Iterable[str]) -> dict[str, tuple[str, list[str]]]:
    return {n: (rep.capabilities[n].state, list(rep.capabilities[n].reason_codes)) for n in names if rep.capabilities[n].state != "healthy"}


def _sqlite_bookkeeping(path: Path) -> bool:
    """SQLite's own read bookkeeping: the shared-memory index, and a WAL with no frames (no write was made).

    A read-only snapshot of an idle WAL store may create both (SYSTEM_SPEC
    §5.1.1 permits SHM bookkeeping for read-only connections); a WAL holding
    any frame is a write and is never excluded.
    """
    return path.name.endswith("-shm") or (path.name.endswith("-wal") and path.stat().st_size == 0)


def tree_digest(root: Path) -> dict[str, str]:
    """Every file under the installation's private directory by digest (SQLite's read bookkeeping excepted)."""
    import hashlib

    out: dict[str, str] = {}
    base_dir = root / ".recalith"
    for path in sorted(base_dir.rglob("*")):
        if path.is_file() and not _sqlite_bookkeeping(path):
            out[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def mtimes(root: Path) -> dict[str, int]:
    """File modification times (directories and SQLite's read bookkeeping excepted)."""
    return {p.relative_to(root).as_posix(): p.stat().st_mtime_ns for p in sorted((root / ".recalith").rglob("*")) if p.is_file() and not _sqlite_bookkeeping(p)}


# --------------------------------------------------------------------------
# Independent pinned build/schema fixtures (A02/A40 preview)

OLD_SCHEMA = 9
OLD_ENGINE = "0.0.9"
OLD_PROJECT = "proj_09090909-0909-4909-8909-090909090909"


def schema9_installation(tmp: Path, name: str, monkeypatch, *, project_id: str = OLD_PROJECT) -> Path:
    """A real schema-9 store built from the migration files 0001–0009, its engine pinned to an older release.

    ``db.SCHEMA_VERSION`` is lowered only while the store is created, so the
    store is exactly what the schema-9 build (Task 15 core) created: the same
    SQL files and identity rows. The ``engine.lock`` pin names the older
    release (synthetic pin: no such wheel is provisioned).
    """
    root = tmp / name
    root.mkdir(parents=True)
    with monkeypatch.context() as m:
        m.setattr(db, "SCHEMA_VERSION", OLD_SCHEMA)
        identity.initialize_installation(root, ProjectConfig.defaults_for(project_id))
    pin_engine(root, OLD_ENGINE, store_schema=OLD_SCHEMA)
    return root


def pin_engine(root: Path, version: str, *, store_schema: int) -> None:
    layout = identity.Layout(root)
    contracts = dict(identity.CONTRACT_VERSIONS, store_schema=store_schema)
    text = identity.dump_toml({"lock_schema": 1, "engine_version": version, "provisioning": "source_tree", "requires_python": identity.REQUIRES_PYTHON, "contracts": contracts}, header="Synthetic older pin (test fixture).")
    layout.engine_lock.write_text(text, encoding="utf-8")


def store_schema(root: Path) -> int:
    import sqlite3

    conn = sqlite3.connect((root / ".recalith" / db.STATE_DB).as_uri() + "?mode=ro", uri=True)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


CHILD = r"""
import json, sys
spec = json.loads(sys.argv[1])
sys.path[:0] = spec["paths"]
from pathlib import Path
from recalith import service
from recalith.contracts.common import Actor
from recalith.core import identity
from recalith.fast import failpoints
failpoints.arm(spec["failpoint"], failpoints.kill)
ctx = identity.resolve_installation(Path(spec["root"]), actor=Actor(kind="operator", id="terminal", channel="cli"))
if spec["action"] == "restore":
    service.restore(ctx, Path(spec["source"]), expected_digest=spec["digest"])
elif spec["action"] == "backup":
    service.submit_backup(ctx, Path(spec["source"]))
sys.exit(0)
"""


def killed_at(root: Path, failpoint: str, action: str, *, source: Path, digest: str | None = None) -> int:
    """Run an operator restore/backup in a real child process that dies abruptly at ``failpoint`` (``os._exit``)."""
    import subprocess

    here = Path(__file__).resolve()
    paths = [cf.SRC, str(here.parent), str(here.parents[1]), str(here.parents[1] / "platform")]
    spec = {"paths": paths, "root": str(root), "failpoint": failpoint, "action": action, "source": str(source), "digest": digest}
    proc = subprocess.run([sys.executable, "-I", "-c", CHILD, json.dumps(spec)], capture_output=True, env=cf.child_env(), timeout=300, check=False)
    return proc.returncode
