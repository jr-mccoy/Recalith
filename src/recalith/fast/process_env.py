"""Fresh role environments and the registered worker start (SYSTEM_SPEC §6.1, §9.1).

Standard library only: the hook fast path uses this module to start the
project's worker, and the worker uses the same helper for its model children
(DATA_CONTRACTS §2.3). There is no second environment filter.

``spawn_environment(manifest, inherited, *, purpose)`` builds a *new* map from
the exact key names a validated manifest permits. It never copies the
inherited map and strips a few keys: anything not named is absent. Registered
host/nested-session markers and every inherited ``RECALITH_*`` key are removed
afterwards, so an allowlist mistake cannot carry one through, and then the one
fresh role marker for ``purpose`` is set. The caller's map is never mutated,
and nothing here grants an operator actor: public CLI guards inspect the
original caller and never call this sanitizer.

``ensure_worker(ctx, deadline=...)`` is the registered internal start path
that the hook runs after capture. It never routes through the guarded
``recalith worker`` CLI; it can start only ``python -I -m
recalith.controller.worker`` for this installation with the hook's own pinned
interpreter. It probes the installation's OS lock, throttles repeated
attempts, spawns the worker detached (new POSIX session; on Windows a detached
process in a new process group that breaks away from the host's Job Object
where the job permits it) with standard handles on the null device and no
other inherited handles, and returns at once. It never waits for the worker to
start or ingest, and it uses only the remaining soft deadline: the
non-blocking lock probe runs whenever any time remains, and below
:data:`START_MIN_REMAINING` the spawn itself is shed (the next hook retries). ``subprocess`` is imported only when a start is actually due.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

from recalith.fast import redact

WORKER_MARKER = "RECALITH_WORKER_INSTALLATION"
CURATOR_MARKER = "RECALITH_CURATOR_INSTALLATION"
ROLE_MARKERS = {"worker": WORKER_MARKER, "curator": CURATOR_MARKER}
ROLE_PREFIX = "RECALITH_"
# Registered host and nested-session markers (decision 0002; Claude Code 2.1.301).
HOST_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION")

# Platform registry: OS/path/temp/locale names a Python child needs. Home and
# configuration directories are purpose-specific overrides, never inherited.
POSIX_PLATFORM_KEYS = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "TZ", "TMPDIR")
WINDOWS_PLATFORM_KEYS = ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "PATH", "PATHEXT", "TEMP", "TMP", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE")

MANIFEST_KEYS = frozenset({"manifest_schema", "purpose", "installation_id", "platform_keys", "route_keys", "overrides"})
_NAME = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_INSTALLATION_ID = re.compile(r"\Ainst_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
MAX_KEYS = 64
MAX_OVERRIDE_BYTES = 4096

RUN_DIR = (".recalith", "run")
LOCK_FILE = "worker.lock"
START_STAMP = "worker-start.json"
START_THROTTLE_SECONDS = 10.0
START_MIN_REMAINING = 0.030
WORKER_MODULE = "recalith.controller.worker"

# Windows process-creation flags (winbase.h); named here so POSIX needs no import.
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
ERROR_ACCESS_DENIED = 5

try:  # POSIX
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - Windows
    _fcntl = None
try:  # Windows
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None


class ManifestError(ValueError):
    """The environment manifest is not a valid primitive manifest (content-free message)."""


# --------------------------------------------------------------------------
# Manifests and environments


def platform_keys(platform: str = os.name) -> tuple:
    return WINDOWS_PLATFORM_KEYS if platform == "nt" else POSIX_PLATFORM_KEYS


def role_manifest(installation_id: str, *, purpose: str, route_keys=(), overrides=None, platform: str = os.name) -> dict:
    """The default manifest: the platform registry plus explicitly selected route keys."""
    return {
        "manifest_schema": 1,
        "purpose": purpose,
        "installation_id": installation_id,
        "platform_keys": list(platform_keys(platform)),
        "route_keys": list(route_keys),
        "overrides": dict(overrides or {}),
    }


def _forbidden(name: str) -> bool:
    upper = name.upper()
    return upper.startswith(ROLE_PREFIX) or upper in HOST_MARKERS


def validate_manifest(manifest, *, purpose: str) -> None:
    """Raise :class:`ManifestError` unless ``manifest`` is a valid manifest for ``purpose``."""
    if purpose not in ROLE_MARKERS:
        raise ManifestError("purpose must be worker or curator")
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS:
        raise ManifestError("manifest fields are not the registered set")
    if manifest["manifest_schema"] != 1 or type(manifest["manifest_schema"]) is not int:
        raise ManifestError("unsupported manifest schema")
    if manifest["purpose"] != purpose:
        raise ManifestError("manifest purpose does not match the requested role")
    if not isinstance(manifest["installation_id"], str) or not _INSTALLATION_ID.match(manifest["installation_id"]):
        raise ManifestError("manifest installation identity is invalid")
    for field in ("platform_keys", "route_keys"):
        names = manifest[field]
        if not isinstance(names, list) or len(names) > MAX_KEYS or not all(isinstance(n, str) and _NAME.match(n) for n in names):
            raise ManifestError(f"{field} must list at most {MAX_KEYS} environment key names")
    overrides = manifest["overrides"]
    if not isinstance(overrides, dict) or len(overrides) > MAX_KEYS:
        raise ManifestError("overrides must be a bounded name→value map")
    for name, value in overrides.items():
        if not isinstance(name, str) or not _NAME.match(name) or _forbidden(name):
            raise ManifestError("an override may not name a marker or an unregistered key shape")
        if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_OVERRIDE_BYTES or "\x00" in value:
            raise ManifestError("override values are bounded strings")
        if redact.contains_secret(value):
            raise ManifestError("overrides are nonsecret configuration")


def _lookup(inherited, platform: str) -> dict:
    if platform != "nt":
        return {k: v for k, v in inherited.items() if isinstance(k, str) and isinstance(v, str)}
    # Windows environment names are case-insensitive: match on the upper-cased name.
    return {k.upper(): v for k, v in inherited.items() if isinstance(k, str) and isinstance(v, str)}


def spawn_environment_report(manifest: dict, inherited, *, purpose: str, platform: str = os.name) -> tuple:
    """``(environment, report)``; the report holds key *names* only, never values."""
    validate_manifest(manifest, purpose=purpose)
    source = _lookup(inherited, platform)
    norm = (lambda n: n.upper()) if platform == "nt" else (lambda n: n)
    route = {norm(n) for n in manifest["route_keys"]}
    child: dict = {}
    dropped_secret_shaped = []
    for name in list(manifest["platform_keys"]) + list(manifest["route_keys"]):
        key = norm(name)
        if key in child or key not in source:
            continue
        value = source[key]
        if key not in route and redact.contains_secret(value):
            dropped_secret_shaped.append(key)  # a platform value never carries a credential
            continue
        child[key] = value
    for name, value in manifest["overrides"].items():
        child[norm(name)] = value
    removed_markers = sorted(k for k in child if _forbidden(k))
    for key in removed_markers:
        del child[key]  # explicit removal wins over an allowlist mistake
    child[ROLE_MARKERS[purpose]] = manifest["installation_id"]
    report = {
        "purpose": purpose,
        "permitted": sorted(child),
        "removed_allowlisted_markers": removed_markers,
        "dropped_secret_shaped": sorted(dropped_secret_shaped),
        "inherited_not_permitted": sorted(set(source) - {norm(k) for k in child}),
    }
    return child, report


def spawn_environment(manifest: dict, inherited, *, purpose: str) -> dict:
    """A fresh allowlisted environment for an engine-owned ``worker`` or ``curator`` child."""
    return spawn_environment_report(manifest, inherited, purpose=purpose)[0]


# --------------------------------------------------------------------------
# The installation's worker lock (shared by the hook probe and the worker)


def run_dir(root) -> str:
    return os.path.join(os.fspath(root), *RUN_DIR)


def lock_path(root) -> str:
    return os.path.join(run_dir(root), LOCK_FILE)


def locking_supported() -> bool:
    return _fcntl is not None or _msvcrt is not None


class InstallationLock:
    """The exclusive per-installation worker lock (one worker per installation).

    POSIX uses ``flock`` (per open file description, so two holders in one
    process also conflict); Windows locks byte 0 with ``msvcrt.locking``. The
    OS releases it when the holder dies, so a crashed worker never blocks its
    successor. The lock file is never deleted.
    """

    def __init__(self, root) -> None:
        self.path = lock_path(root)
        self.fd = None

    def try_acquire(self) -> bool:
        directory = os.path.dirname(self.path)
        if not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
            if os.name != "nt":
                os.chmod(directory, 0o700)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
        try:
            if _fcntl is not None:
                _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            elif _msvcrt is not None:
                _msvcrt.locking(fd, _msvcrt.LK_NBLCK, 1)
            else:
                raise OSError("no supported lock primitive")
        except OSError:
            os.close(fd)
            return False
        self.fd = fd
        return True

    def release(self) -> None:
        if self.fd is None:
            return
        try:
            if _fcntl is not None:
                _fcntl.flock(self.fd, _fcntl.LOCK_UN)
            elif _msvcrt is not None:
                os.lseek(self.fd, 0, os.SEEK_SET)
                _msvcrt.locking(self.fd, _msvcrt.LK_UNLCK, 1)
        finally:
            os.close(self.fd)
            self.fd = None


def worker_running(root) -> bool:
    """True while some process holds this installation's worker lock."""
    lock = InstallationLock(root)
    if lock.try_acquire():
        lock.release()
        return False
    return True


# --------------------------------------------------------------------------
# Detached start


def worker_argv(executable: str, root: str, *, method: str) -> list:
    return [executable, "-I", "-m", WORKER_MODULE, "--project", root, "--spawned-by", "hook", "--spawn-method", method]


def _read_stamp(path: str):
    try:
        with open(path, "rb") as fh:
            data = json.loads(fh.read(4096).decode("utf-8"))
        return float(data["at"]) if isinstance(data, dict) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_stamp(path: str, record: dict) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    try:
        os.write(fd, json.dumps(record, sort_keys=True).encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, path)


def start_detached(argv: list, env: dict, *, cwd: str, platform: str = os.name) -> tuple:
    """Start ``argv`` independent of the caller; returns ``(pid, method, degraded_reasons)``.

    POSIX: a new session (``setsid``), so terminating the host's process group
    or session does not reach it. Windows: a detached process in a new process
    group, breaking away from the caller's Job Object. When the job forbids
    breakaway the start is retried without it and reported degraded: the
    worker then lives only as long as that job. Standard handles are the null
    device and no other handle is inherited.
    """
    import subprocess  # deferred: only paid when a start is actually due

    common = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True, "env": env, "cwd": cwd, "shell": False}
    if platform != "nt":
        proc = subprocess.Popen(argv, start_new_session=True, **common)
        return proc.pid, "posix_session", []
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        proc = subprocess.Popen(_with_method(argv, "windows_breakaway"), creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, **common)
        return proc.pid, "windows_breakaway", []
    except OSError as exc:
        if getattr(exc, "winerror", None) != ERROR_ACCESS_DENIED:
            raise
    proc = subprocess.Popen(_with_method(argv, "windows_no_breakaway"), creationflags=flags, **common)
    return proc.pid, "windows_no_breakaway", ["job_breakaway_denied"]


def _with_method(argv: list, method: str) -> list:
    out = list(argv)
    if "--spawn-method" in out:
        out[out.index("--spawn-method") + 1] = method
    return out


def ensure_worker(ctx: dict, *, deadline: float, inherited=None, executable: str | None = None, platform: str = os.name, now=time.time) -> str:
    """Start this installation's worker if none is running; never waits for it.

    Returns a content-free status: ``worker_autostart_disabled``,
    ``worker_running``, ``worker_start_pending`` (a recent start is still
    coming up), ``worker_started``, or the degradations
    ``worker_independence_degraded``, ``deadline_worker_start_skipped``,
    ``worker_start_unavailable`` and ``worker_start_failed``.
    """
    if not ctx.get("worker_autostart"):
        return "worker_autostart_disabled"
    if deadline - time.monotonic() <= 0:
        return "deadline_worker_start_skipped"
    executable = sys.executable if executable is None else executable
    if not executable or not locking_supported():
        return "worker_start_unavailable"
    root = ctx["root"]
    try:
        if worker_running(root):  # a non-blocking lock probe: microseconds, so it runs whenever time remains
            return "worker_running"
        stamp = os.path.join(run_dir(root), START_STAMP)
        last = _read_stamp(stamp)
        current = now()
        if last is not None and 0 <= current - last < START_THROTTLE_SECONDS:
            return "worker_start_pending"
        if deadline - time.monotonic() < START_MIN_REMAINING:
            return "deadline_worker_start_skipped"
        manifest = role_manifest(ctx["installation_id"], purpose="worker", route_keys=ctx.get("worker_route_keys") or (), platform=platform)
        env = spawn_environment_report(manifest, os.environ if inherited is None else inherited, purpose="worker", platform=platform)[0]
        _write_stamp(stamp, {"at": current, "method": None})
        pid, method, degraded = start_detached(worker_argv(executable, root, method="posix_session" if platform != "nt" else "windows_breakaway"), env, cwd=run_dir(root), platform=platform)
        _write_stamp(stamp, {"at": current, "pid": pid, "method": method, "degraded": degraded})
    except (OSError, ValueError):
        return "worker_start_failed"
    return "worker_independence_degraded" if degraded else "worker_started"
