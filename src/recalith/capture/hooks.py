"""Service-side writer of the hook context manifest read by ``recalith.fast.entry``.

The fast path never resolves an installation itself (no TOML, no SQLite): it
reads ``.recalith/run/hook-context.json``, written here from a context that
``resolve_installation`` already checked for relocation and foreign stores.
The manifest holds identifiers, registered absolute local paths, root
identities, the policy revision and, per adapter, the host version recorded at
integration time. Delivery stays disabled in capture-only builds. Task 13's
``integrate`` command calls :func:`write_hook_context`; until then tests and
the fixture tooling call it directly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from recalith.contracts.common import InstallationContext
from recalith.core.paths import private_mkdir, root_identity
from recalith.errors import RecalithError
from recalith.fast import entry

CAPTURE_ADAPTERS = frozenset(entry.ADAPTERS)


def write_hook_context(ctx: InstallationContext, *, adapter_id: str, host_version: str | None) -> Path:
    """Create or update the manifest entry for ``adapter_id``; other adapters are kept."""
    if adapter_id not in CAPTURE_ADAPTERS:
        raise RecalithError("capability_unavailable", f"no capture adapter {adapter_id!r} in this build")
    path = Path(ctx.root) / entry.HOOK_CONTEXT_FILE
    private_mkdir(path.parent)
    adapters = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            if entry.valid_context_manifest(current) and current["installation_id"] == ctx.installation_id:
                adapters = current["adapters"]
        except (OSError, ValueError):
            adapters = {}
    adapters[adapter_id] = {"host_version": host_version, "delivery_enabled": False}
    manifest = {
        "context_schema": 1,
        "project_id": ctx.project_id,
        "installation_id": ctx.installation_id,
        "workspace_id": ctx.workspace_id,
        "root": str(ctx.root),
        "workspace_root": str(ctx.workspace_root),
        "root_identity": root_identity(ctx.root),
        "workspace_root_identity": root_identity(ctx.workspace_root),
        "policy_revision": ctx.policy_revision,
        "adapters": adapters,
    }
    if not entry.valid_context_manifest(manifest):
        raise RecalithError("invalid_schema", "hook context manifest would be invalid")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    os.replace(tmp, path)
    return path
