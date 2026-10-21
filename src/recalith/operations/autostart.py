"""Project startup in the preview profile: the hook-started worker, reported without side effects (decision 0018).

Preview's only automatic startup route is the registered internal hook
start (``fast.process_env.ensure_worker``, decision 0006): the next project
activity starts this installation's pinned worker. A rebooted or idle
installation therefore resumes on its next hook. Per-project OS startup
entries (``recalith integrate --autostart``) are a full-release capability
and are reported unavailable here; nothing in this module registers one.

A copied or moved checkout never starts or adopts a worker: the hook's
manifest names the recorded root identity, and a checkout whose root is not
that directory is refused before capture or start
(``installation_relocated``); ``resolve_installation`` refuses a copy and a
move awaits an operator rebind (decision 0003). This module only *reports*
that state for one resolved installation; it starts nothing, creates no
file, and never probes another project.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from recalith.contracts.common import InstallationContext, parse_utc
from recalith.fast import entry, process_env

STATUS_FILE = "worker.json"  # the worker's own status record (controller.worker.STATUS_FILE)
HEARTBEAT_STALE_SECONDS = 300.0
OS_STARTUP_ENTRIES = {"state": "unavailable", "reason": "deferred_full_release"}
WORKER_STATES = frozenset({"running", "idle", "degraded", "budget_paused"})

try:  # pragma: no cover - platform dependent
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - Windows
    _fcntl = None
try:  # pragma: no cover - platform dependent
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - POSIX
    _msvcrt = None


def lock_held(path: str | Path) -> bool:
    """Whether some process holds the exclusive lock on ``path``; never creates or changes the file.

    An absent lock file means nobody holds it (every holder creates it
    first). The probe takes and releases a non-blocking lock on the existing
    file, which changes neither its bytes nor its timestamps.
    """
    try:
        fd = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))
    except FileNotFoundError:
        return False
    except OSError:
        return True  # it exists but cannot be opened for locking: assume a holder rather than claim none
    try:
        try:
            if _fcntl is not None:
                _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            elif _msvcrt is not None:  # pragma: no cover - native Windows
                _msvcrt.locking(fd, _msvcrt.LK_NBLCK, 1)
            else:  # pragma: no cover - no lock primitive
                return False
        except OSError:
            return True
        if _fcntl is not None:
            _fcntl.flock(fd, _fcntl.LOCK_UN)
        else:  # pragma: no cover - native Windows
            os.lseek(fd, 0, os.SEEK_SET)
            _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)
        return False
    finally:
        os.close(fd)


def worker_running(root: str | Path) -> bool:
    """True while a worker holds this installation's lock (the read-only twin of ``process_env.worker_running``)."""
    return lock_held(process_env.lock_path(root))


def read_manifest(root: str | Path) -> tuple[str, dict[str, Any] | None]:
    """The hook-context manifest and its state: ``absent``, ``invalid``, ``relocated`` or ``ok`` (as the hook judges it)."""
    path = Path(root) / entry.HOOK_CONTEXT_FILE
    try:
        raw = json.loads(path.read_bytes()[: 64 * 1024].decode("utf-8"))
    except FileNotFoundError:
        return "absent", None
    except (OSError, ValueError):
        return "invalid", None
    if not entry.valid_context_manifest(raw) or "claude_code" not in raw["adapters"]:
        return "invalid", None
    try:
        here = os.stat(root)
        recorded = os.stat(raw["workspace_root"])
    except OSError:
        return "relocated", raw
    if f"{here.st_dev}:{here.st_ino}" != raw["root_identity"] or f"{recorded.st_dev}:{recorded.st_ino}" != raw["workspace_root_identity"]:
        return "relocated", raw
    return "ok", raw


def startup_report(ctx: InstallationContext, manifest: tuple[str, dict[str, Any] | None] | None = None) -> dict[str, Any]:
    """How this installation starts its worker: the registered hook start (preview) and the full-only OS entries."""
    state, raw = manifest if manifest is not None else read_manifest(ctx.root)
    if state == "ok" and raw is not None:
        registered = "registered" if (raw.get("worker") or {}).get("autostart") else "not_registered"
    else:
        registered = {"absent": "not_integrated", "invalid": "invalid", "relocated": "relocated"}[state]
    return {
        "registered_hook_start": registered,
        "worker_lock": "supported" if process_env.locking_supported() else "unsupported",
        "os_startup_entries": dict(OS_STARTUP_ENTRIES),
        "copy_adoption": "refused",  # a checkout whose root is not the recorded directory never starts or adopts a worker
        "resumes_on": "next_project_activity" if registered == "registered" else None,
    }


def read_worker_status(ctx: InstallationContext) -> dict[str, Any] | None:
    """The worker's own status record, only when it names this installation (a copied file never counts)."""
    try:
        data = json.loads((Path(process_env.run_dir(ctx.root)) / STATUS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("installation_id") != ctx.installation_id:
        return None
    return data


def worker_report(ctx: InstallationContext, *, now: str) -> dict[str, Any]:
    """The running worker's state as it reports it, or ``stopped``; heartbeat age and spawn independence."""
    running = worker_running(ctx.root)
    status = read_worker_status(ctx) if running else None
    out: dict[str, Any] = {"running": running, "state": "stopped", "spawned_by": None, "method": None, "independence": None, "degraded_reasons": [], "heartbeat_age_seconds": None, "last_error": None, "pid": None}
    if not running:
        return out
    out["state"] = "running"
    if status is None:
        out["state"] = "degraded"
        out["degraded_reasons"] = ["worker_status_unavailable"]
        return out
    spawn = status.get("spawn") or {}
    out.update({"spawned_by": spawn.get("spawned_by"), "method": spawn.get("method"), "independence": spawn.get("state"), "degraded_reasons": list(spawn.get("degraded_reasons") or []), "last_error": status.get("last_error"), "pid": status.get("pid")})
    state = status.get("state")
    out["state"] = state if state in WORKER_STATES else "running"
    try:
        age = (parse_utc(now) - parse_utc(status["heartbeat_at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        age = None
    out["heartbeat_age_seconds"] = None if age is None else max(0.0, age)
    if age is None or age > HEARTBEAT_STALE_SECONDS:
        out["state"] = "degraded"
        out["degraded_reasons"] = [*out["degraded_reasons"], "worker_heartbeat_stale"]
    out["provider"] = status.get("provider")
    return out


__all__ = ["lock_held", "worker_running", "read_manifest", "startup_report", "read_worker_status", "worker_report", "OS_STARTUP_ENTRIES", "HEARTBEAT_STALE_SECONDS"]
