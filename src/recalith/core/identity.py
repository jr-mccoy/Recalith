"""Independent project installations (SYSTEM_SPEC §2; A01–A04 preview slices).

Each project root owns ``.recalith/``: a tracked portable identity
(``project.toml``), an exact engine lock and launchers, plus ignored private
state (``local.toml``, the store, spool, cache, run, backups, exports).

* A fresh clone carries ``project.toml`` but no private state; ``init`` there
  keeps the logical project ID and creates a new installation ID.
* A moved checkout is detected (recorded canonical root ≠ actual root) and
  needs an explicit operator rebind; a *copy* — the recorded root still holds
  the same installation — is refused so a second writer never starts under the
  original identity.
* There is no global registry: every call receives the explicit root.

Workspace attachment, project fork and shared integration are full-release
features (``capability_unavailable`` in preview).
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Mapping

from recalith import __version__
from recalith.contracts.common import Actor, InstallationContext, new_id, utc_now
from recalith.contracts.config import ProjectConfig
from recalith.core.paths import canonical, private_mkdir, root_identity, same_location
from recalith.errors import RecalithError
from recalith.fast import failpoints
from recalith.storage import db

DIR = ".recalith"
PRIVATE_DIRS = ("runtime", "state", "spool", "cache", "run", "backups", "exports")
REQUIRES_PYTHON = ">=3.12,<3.15"
CONTRACT_VERSIONS = {"event_schema": 1, "segment_schema": 1, "provider_operation_schema": 1, "packet_schema": 1, "store_schema": db.SCHEMA_VERSION, "export_schema": 1}
NETWORK_FILESYSTEMS = frozenset({"nfs", "nfs4", "cifs", "smb3", "smbfs", "fuse.sshfs", "sshfs", "afs", "ceph", "glusterfs", "fuse.rclone", "davfs", "9p", "lustre", "gpfs"})
INITIALIZER = Actor(kind="controller", id="initializer", channel="cli")

GITIGNORE = """# Recalith: track only the portable identity, exact engine lock and launchers.
*
!.gitignore
!project.toml
!engine.lock
!bin/
!bin/**
"""


# --------------------------------------------------------------------------
# Small TOML writer (flat tables of strings/ints/bools only)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    raise TypeError(f"unsupported TOML value {type(value).__name__}")


def dump_toml(data: Mapping[str, Any], header: str = "") -> str:
    lines = [f"# {ln}" for ln in header.splitlines()] if header else []
    tables = {k: v for k, v in data.items() if isinstance(v, Mapping)}
    for key, value in data.items():
        if key not in tables:
            lines.append(f"{key} = {_toml_value(value)}")
    for name, table in tables.items():
        lines += ["", f"[{name}]"] + [f"{k} = {_toml_value(v)}" for k, v in table.items()]
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, text: str, *, private: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if private and os.name != "nt":
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise RecalithError("invalid_schema", f"{path.name} is not valid TOML") from exc


# --------------------------------------------------------------------------
# Layout


class Layout:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.base = root / DIR
        self.project_toml = self.base / "project.toml"
        self.engine_lock = self.base / "engine.lock"
        self.bin = self.base / "bin"
        self.local_toml = self.base / "local.toml"
        self.db = self.base / db.STATE_DB

    def runtime_python(self, version: str) -> Path:
        venv = self.base / "runtime" / version / "venv"
        return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def filesystem_type(path: Path) -> str | None:
    """Filesystem type of ``path`` from /proc/self/mountinfo (Linux), else None."""
    mountinfo = Path("/proc/self/mountinfo")
    if not mountinfo.exists():
        return None
    target = str(canonical(path))
    best, fstype = "", None
    for line in mountinfo.read_text(encoding="utf-8", errors="replace").splitlines():
        left, _, right = line.partition(" - ")
        fields = left.split()
        if len(fields) < 5 or not right:
            continue
        mount_point = fields[4].replace("\\040", " ")
        if (target == mount_point or target.startswith(mount_point.rstrip("/") + "/")) and len(mount_point) >= len(best):
            best, fstype = mount_point, right.split()[0]
    return fstype


def require_local_filesystem(path: Path) -> str | None:
    fstype = filesystem_type(path)
    if fstype is not None and fstype in NETWORK_FILESYSTEMS:
        raise RecalithError("storage_failure", f"the live database must be on a local filesystem (found {fstype})")
    return fstype


# --------------------------------------------------------------------------
# Launchers


def posix_launcher(version: str) -> str:
    return f"""#!/bin/sh
# Recalith project launcher (generated by `recalith init`; tracked).
# Uses only this project's pinned runtime. Never downloads anything.
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(dirname -- "$(dirname -- "$here")")
py="$root/.recalith/runtime/{version}/venv/bin/python"
if [ ! -x "$py" ]; then
  echo "recalith: capability_unavailable: runtime {version} is not provisioned for this project; run the release bootstrap (python bootstrap.py install --project \\"$root\\" --wheel ... --expected-digest ...)." >&2
  exit 4
fi
exec "$py" -I -m recalith --project "$root" "$@"
"""


def windows_launcher(version: str) -> str:
    return f"""@echo off
rem Recalith project launcher (generated by `recalith init`; tracked).
rem Uses only this project's pinned runtime. Never downloads anything.
setlocal
for %%I in ("%~dp0..\\..") do set "ROOT=%%~fI"
set "PY=%ROOT%\\.recalith\\runtime\\{version}\\venv\\Scripts\\python.exe"
if not exist "%PY%" (
  echo recalith: capability_unavailable: runtime {version} is not provisioned for this project; run the release bootstrap. 1>&2
  exit /b 4
)
"%PY%" -I -m recalith --project "%ROOT%" %*
exit /b %ERRORLEVEL%
"""


def posix_hook_launcher(version: str) -> str:
    return f"""#!/bin/sh
# Recalith hook launcher (generated by `recalith init`; tracked).
# Runs the stdlib-only capture entry on this project's pinned runtime. Without
# that runtime it returns the host's empty nonblocking success: no download,
# no output, no hint (SYSTEM_SPEC §2.2, A53).
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(dirname -- "$(dirname -- "$here")")
py="$root/.recalith/runtime/{version}/venv/bin/python"
if [ ! -x "$py" ]; then
  cat >/dev/null 2>&1
  exit 0
fi
exec "$py" -I -m recalith.fast.entry --project "$root" "$@"
"""


def windows_hook_launcher(version: str) -> str:
    return f"""@echo off
rem Recalith hook launcher (generated by `recalith init`; tracked).
rem Runs the stdlib-only capture entry on this project's pinned runtime. Without
rem that runtime it returns the host's empty nonblocking success: no download, no output.
setlocal
for %%I in ("%~dp0..\\..") do set "ROOT=%%~fI"
set "PY=%ROOT%\\.recalith\\runtime\\{version}\\venv\\Scripts\\python.exe"
if not exist "%PY%" exit /b 0
"%PY%" -I -m recalith.fast.entry --project "%ROOT%" %*
exit /b 0
"""


def write_launchers(layout: Layout, version: str) -> None:
    layout.bin.mkdir(parents=True, exist_ok=True)
    for name, text in (("recalith", posix_launcher(version)), ("recalith-hook", posix_hook_launcher(version))):
        _atomic_write(layout.bin / name, text, private=False)
        if os.name != "nt":
            os.chmod(layout.bin / name, 0o755)
    _atomic_write(layout.bin / "recalith.cmd", windows_launcher(version).replace("\n", "\r\n"), private=False)
    _atomic_write(layout.bin / "recalith-hook.cmd", windows_hook_launcher(version).replace("\n", "\r\n"), private=False)


# --------------------------------------------------------------------------
# Initialization and resolution


def load_project_config(layout: Layout) -> ProjectConfig:
    raw = _read_toml(layout.project_toml)
    allowed = {"config_schema", "project_id", "domain_profile", "release_profile"}
    if set(raw) - allowed:
        raise RecalithError("invalid_schema", f"unknown project.toml fields: {sorted(set(raw) - allowed)}")
    if raw.get("config_schema") != 1:
        raise RecalithError("invalid_schema", "unsupported project.toml config_schema")
    try:
        return ProjectConfig.defaults_for(raw["project_id"], release_profile=raw.get("release_profile", "claude_preview"), domain_profile=raw.get("domain_profile", "coding"))
    except (KeyError, ValueError) as exc:
        raise RecalithError("invalid_schema", "project.toml identity is invalid") from exc


def _project_toml(config: ProjectConfig) -> str:
    return dump_toml(
        {"config_schema": 1, "project_id": config.project_id, "domain_profile": config.domain_profile, "release_profile": config.release_profile},
        header="Recalith project configuration (tracked, portable, nonsecret).\nThe logical project ID is shared by clones; each clone has its own private installation.",
    )


def _engine_lock() -> str:
    return dump_toml(
        {"lock_schema": 1, "engine_version": __version__, "provisioning": "source_tree", "requires_python": REQUIRES_PYTHON, "contracts": CONTRACT_VERSIONS},
        header="Exact engine pin for this project (tracked). The release bootstrap records the verified\nwheel digest here when it provisions .recalith/runtime/.",
    )


LOCAL_HEADER = "Private installation identity for this machine (never tracked)."
# Operator-token verifier tables in local.toml (SYSTEM_SPEC §13.1; decision 0014).
VERIFIERS = "operator_verifiers"
REVOKED = "operator_revoked"


def _local_toml(installation_id: str, workspace_id: str, root: Path, *, verifiers: Mapping[str, str] | None = None) -> str:
    data: dict[str, Any] = {
        "local_schema": 1,
        "installation_id": installation_id,
        "workspace_id": workspace_id,
        "workspace_root": str(root),
        "root_identity": root_identity(root),
        "created_at": utc_now(),
    }
    if verifiers:
        data[VERIFIERS] = dict(verifiers)
    return dump_toml(data, header=LOCAL_HEADER)


def _context(layout: Layout, local: Mapping[str, Any], meta: db.Meta, actor: Actor) -> InstallationContext:
    return InstallationContext(
        project_id=meta.project_id,
        installation_id=meta.installation_id,
        root=layout.root,
        workspace_id=local["workspace_id"],
        workspace_root=layout.root,
        engine_version=__version__,
        schema_version=meta.schema_version,
        policy_revision=meta.policy_revision,
        actor=actor,
    )


def initialize_installation(root: Path, config: ProjectConfig, *, operator_verifiers: Mapping[str, str] | None = None) -> InstallationContext:
    """Create a new private installation in ``root``; never overwrites a live store.

    The returned context carries a neutral controller actor; callers resolve
    the installation again with the actor their guarded transport assigned.
    ``operator_verifiers`` (token ID → one-way verifier) are installed in the
    same ``local.toml`` write that completes the installation, including when
    this call completes an interrupted init, so a token-provisioned first init
    never ends with an installation that lacks its verifier.
    """
    if not Path(root).is_dir():
        raise RecalithError("invalid_schema", "project root must be an existing directory")
    root = canonical(root)
    layout = Layout(root)
    if layout.project_toml.exists():
        tracked = load_project_config(layout)
        if tracked.project_id != config.project_id:
            raise RecalithError("policy_refused", "project.toml already names a different project ID")
    if layout.db.exists():
        if layout.local_toml.exists():
            raise RecalithError("policy_refused", "an installation already exists here; init never resets memory")
        _complete_interrupted_init(layout, verifiers=operator_verifiers)
        return resolve_installation(root, actor=INITIALIZER)
    require_local_filesystem(root)
    private_mkdir(layout.base)
    for name in PRIVATE_DIRS:
        private_mkdir(layout.base / name)
    _atomic_write(layout.base / ".gitignore", GITIGNORE, private=False)
    if not layout.project_toml.exists():
        _atomic_write(layout.project_toml, _project_toml(config), private=False)
    if not layout.engine_lock.exists():
        _atomic_write(layout.engine_lock, _engine_lock(), private=False)
    write_launchers(layout, __version__)

    installation_id, workspace_id = new_id("inst"), new_id("ws")
    tmp_db = layout.db.with_name(f".memory-{installation_id}.sqlite.tmp")
    for stale in layout.db.parent.glob(".memory-*.sqlite.tmp*"):
        stale.unlink()
    db.create_database(
        tmp_db,
        project_id=config.project_id,
        installation_id=installation_id,
        engine_version=__version__,
        release_profile=config.release_profile,
        workspace={"workspace_id": workspace_id, "canonical_root": str(root), "root_identity": root_identity(root)},
    )
    for sidecar in ("-wal", "-shm"):
        Path(str(tmp_db) + sidecar).unlink(missing_ok=True)
    if os.name != "nt":
        os.chmod(tmp_db, 0o600)
    os.replace(tmp_db, layout.db)
    failpoints.hit(failpoints.INIT_AFTER_STORE)
    # local.toml is written last: its presence marks a complete installation.
    _atomic_write(layout.local_toml, _local_toml(installation_id, workspace_id, root, verifiers=operator_verifiers), private=True)
    return resolve_installation(root, actor=INITIALIZER)


def _complete_interrupted_init(layout: Layout, *, verifiers: Mapping[str, str] | None = None) -> None:
    """Finish an init that crashed after the store rename but before local.toml."""
    conn = db.connect(layout.db, readonly=True)
    try:
        meta = db.read_meta(conn)
        row = conn.execute("SELECT workspace_id, canonical_root FROM workspaces WHERE attachment_state = 'primary'").fetchone()
    finally:
        conn.close()
    if row is None or not same_location(row[1], layout.root):
        raise RecalithError("policy_refused", "a store without local identity exists here and does not belong to this root")
    _atomic_write(layout.local_toml, _local_toml(meta.installation_id, row[0], layout.root, verifiers=verifiers), private=True)


def _read_local(layout: Layout) -> dict[str, Any]:
    if not layout.local_toml.exists():
        raise RecalithError("capability_unavailable", "this checkout has no Recalith installation; run `recalith init` (a clone keeps the project ID and gets a new installation)")
    local = _read_toml(layout.local_toml)
    for key in ("installation_id", "workspace_id", "workspace_root", "root_identity"):
        if not isinstance(local.get(key), str):
            raise RecalithError("invalid_schema", f"local.toml lacks {key}")
    return local


def _classify_location(layout: Layout, local: Mapping[str, Any]) -> str:
    """'same', 'moved' or 'copied' relative to the recorded workspace root."""
    recorded = Path(local["workspace_root"])
    if same_location(recorded, layout.root):
        return "same"
    other_local = recorded / DIR / "local.toml"
    if other_local.exists():
        try:
            other = _read_toml(other_local)
        except RecalithError:
            other = {}
        if other.get("installation_id") == local["installation_id"]:
            return "copied"
    return "moved"


def resolve_installation(root: Path, *, actor: Actor) -> InstallationContext:
    """Resolve the installation owned by exactly ``root`` (no upward search)."""
    root = canonical(root)
    layout = Layout(root)
    if not layout.project_toml.exists():
        raise RecalithError("capability_unavailable", "no .recalith/project.toml at this root")
    config = load_project_config(layout)
    local = _read_local(layout)
    location = _classify_location(layout, local)
    if location == "copied":
        raise RecalithError("installation_relocated", "this is a copy of another live installation; copied private state never starts a second writer (remove the copied .recalith private state and run init, or restore from a backup)")
    if location == "moved":
        raise RecalithError("installation_relocated", "the project moved; an operator must rebind it (recalith workspace rebind) before use")
    conn = db.connect(layout.db, readonly=True)
    try:
        meta = db.read_meta(conn)
    finally:
        conn.close()
    if meta.installation_id != local["installation_id"] or meta.project_id != config.project_id:
        raise RecalithError("foreign_installation", "the store does not belong to this checkout's installation")
    return _context(layout, local, meta, actor)


def rebind_installation(root: Path, *, actor: Actor) -> InstallationContext:
    """Operator rebind after a move. Copies are refused, never adopted."""
    if actor.kind != "operator":
        raise RecalithError("policy_refused", "rebinding a moved installation is an operator action")
    root = canonical(root)
    layout = Layout(root)
    local = _read_local(layout)
    location = _classify_location(layout, local)
    if location == "copied":
        raise RecalithError("installation_relocated", "refusing to rebind a copy of a live installation")
    if location == "same":
        return resolve_installation(root, actor=actor)
    require_local_filesystem(root)
    conn = db.connect(layout.db)
    try:
        conn.execute("BEGIN IMMEDIATE")
        meta = db.read_meta(conn)
        if meta.installation_id != local["installation_id"]:
            raise RecalithError("foreign_installation", "the store does not belong to this checkout's installation")
        now = utc_now()
        conn.execute(
            "UPDATE workspaces SET canonical_root = ?, root_identity = ?, rebound_at = ? WHERE workspace_id = ?",
            (str(root), root_identity(root), now, local["workspace_id"]),
        )
        conn.execute(
            "INSERT INTO operations (operation_id, actor, kind, inputs, changed, reason, store_revision, created_at) VALUES (?, ?, 'workspace_rebind', ?, '[]', 'operator rebind after move', ?, ?)",
            (new_id("op"), json.dumps(actor.model_dump(mode="json")), json.dumps({"from": local["workspace_root"], "to": str(root)}), meta.store_revision + 1, now),
        )
        conn.execute("UPDATE installation_meta SET store_revision = store_revision + 1 WHERE singleton = 1")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    updated = dict(local, workspace_root=str(root), root_identity=root_identity(root))
    _atomic_write(layout.local_toml, dump_toml(updated, header=LOCAL_HEADER), private=True)
    return resolve_installation(root, actor=actor)


def unavailable_in_preview(feature: str) -> RecalithError:
    """Explicit result for full-release installation features (attach, fork, shared)."""
    return RecalithError("capability_unavailable", f"{feature} is a full-release capability; this installation runs the claude_preview profile")


def discard_copied_private_state(root: Path, *, actor: Actor) -> None:
    """Operator action: drop *copied* private state so `init` can create a fresh installation.

    Refused unless the recorded root still holds the same live installation,
    i.e. this checkout really is a copy; it never deletes an original store.
    """
    if actor.kind != "operator":
        raise RecalithError("policy_refused", "discarding private state is an operator action")
    layout = Layout(canonical(root))
    if _classify_location(layout, _read_local(layout)) != "copied":
        raise RecalithError("policy_refused", "only a detected copy's private state can be discarded")
    layout.local_toml.unlink()
    for name in PRIVATE_DIRS:
        shutil.rmtree(layout.base / name, ignore_errors=True)


# --------------------------------------------------------------------------
# Operator-token verifiers (installation-local; no global registry)


def operator_tokens(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """The installation's ``(verifiers, revoked)`` maps from ``local.toml``."""
    local = _read_local(Layout(canonical(root)))
    verifiers = local.get(VERIFIERS) or {}
    revoked = local.get(REVOKED) or {}
    if not isinstance(verifiers, dict) or not isinstance(revoked, dict):
        raise RecalithError("invalid_schema", "local.toml operator-token tables are malformed")
    return {str(k): str(v) for k, v in verifiers.items()}, {str(k): str(v) for k, v in revoked.items()}


def update_operator_tokens(root: Path, *, register: Mapping[str, str] | None = None, revoke: str | None = None) -> None:
    """Register verifiers and/or record a revocation with one atomic ``local.toml`` replace.

    Revocation is permanent for this installation: a revoked token ID is never
    registered again. The caller has already passed the operator guard.
    """
    layout = Layout(canonical(root))
    local = _read_local(layout)
    verifiers, revoked = operator_tokens(layout.root)
    for token_id, verifier in (register or {}).items():
        if token_id in revoked:
            raise RecalithError("policy_refused", "this operator token was revoked for this installation")
        verifiers[token_id] = verifier
    if revoke is not None:
        revoked[revoke] = utc_now()
        verifiers.pop(revoke, None)
    updated = {k: v for k, v in local.items() if k not in (VERIFIERS, REVOKED)}
    if verifiers:
        updated[VERIFIERS] = verifiers
    if revoked:
        updated[REVOKED] = revoked
    _atomic_write(layout.local_toml, dump_toml(updated, header=LOCAL_HEADER), private=True)
