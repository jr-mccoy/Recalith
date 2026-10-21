"""Service-side writer of the hook context manifest read by ``recalith.fast.entry``.

The fast path never resolves an installation itself (no TOML, no SQLite): it
reads ``.recalith/run/hook-context.json``, written here from a context that
``resolve_installation`` already checked for relocation and foreign stores.
The manifest holds identifiers, registered absolute local paths, root
identities, the policy revision, per adapter the host version recorded at
integration time, and (context_schema 2, decision 0006) whether the hook may
start this installation's worker plus the exact route key names that worker
may carry for its selected provider route, and (context_schema 3, decision
0015) per adapter the delivery paths whose injection is installed, and
(context_schema 4, decision 0019) the integration's consent for the brief
session-start notice. Delivery stays off unless a caller passes
``delivery_paths`` explicitly: ``recalith integrate claude``
(``integrations.claude``) passes only the paths a live certification of this
installation and host version certified, with worker autostart and notices on;
controlled test manifests and the certification harness pass trial paths.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Sequence

from recalith.contracts.common import InstallationContext
from recalith.core.paths import private_mkdir, root_identity
from recalith.errors import RecalithError
from recalith.fast import entry

CAPTURE_ADAPTERS = frozenset(entry.ADAPTERS)


def write_hook_context(
    ctx: InstallationContext,
    *,
    adapter_id: str,
    host_version: str | None,
    worker_autostart: bool | None = None,
    worker_route_keys: Sequence[str] | None = None,
    delivery_paths: Sequence[str] | None = None,
    session_notice: bool | None = None,
) -> Path:
    """Create or update the manifest entry for ``adapter_id``; other adapters are kept.

    ``worker_autostart``/``worker_route_keys``/``delivery_paths``/
    ``session_notice`` of None keep the current values (autostart off, no route
    keys, no delivery and no session-start notice for a new manifest);
    ``delivery_paths=[]`` turns delivery off.
    """
    if adapter_id not in CAPTURE_ADAPTERS:
        raise RecalithError("capability_unavailable", f"no capture adapter {adapter_id!r} in this build")
    path = Path(ctx.root) / entry.HOOK_CONTEXT_FILE
    private_mkdir(path.parent)
    adapters: dict = {}
    worker = {"autostart": False, "route_keys": []}
    notices = {"session_start": False}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            if entry.valid_context_manifest(current) and current["installation_id"] == ctx.installation_id:
                adapters = {name: {"host_version": a["host_version"], "delivery_enabled": a["delivery_enabled"], "delivery_paths": list(a.get("delivery_paths") or [])} for name, a in current["adapters"].items()}
                worker = dict(current.get("worker") or worker)
                notices = dict(current.get("notices") or notices)
        except (OSError, ValueError):
            adapters = {}
    previous = adapters.get(adapter_id, {}).get("delivery_paths", [])
    paths = sorted(set(previous if delivery_paths is None else delivery_paths), key=entry.DELIVERY_PATHS.index) if set(previous if delivery_paths is None else delivery_paths) <= set(entry.DELIVERY_PATHS) else None
    if paths is None:
        raise RecalithError("invalid_schema", "unknown delivery path")
    adapters[adapter_id] = {"host_version": host_version, "delivery_enabled": bool(paths), "delivery_paths": paths}
    if worker_autostart is not None:
        worker["autostart"] = bool(worker_autostart)
    if worker_route_keys is not None:
        worker["route_keys"] = list(worker_route_keys)
    if session_notice is not None:
        notices["session_start"] = bool(session_notice)
    manifest = {
        "context_schema": 4,
        "project_id": ctx.project_id,
        "installation_id": ctx.installation_id,
        "workspace_id": ctx.workspace_id,
        "root": str(ctx.root),
        "workspace_root": str(ctx.workspace_root),
        "root_identity": root_identity(ctx.root),
        "workspace_root_identity": root_identity(ctx.workspace_root),
        "policy_revision": ctx.policy_revision,
        "adapters": adapters,
        "worker": worker,
        "notices": notices,
    }
    if not entry.valid_context_manifest(manifest):
        raise RecalithError("invalid_schema", "hook context manifest would be invalid")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    os.replace(tmp, path)
    return path
