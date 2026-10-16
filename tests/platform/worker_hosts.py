"""Helpers for native worker lifecycle tests: simulated hosts, waits and cleanup.

A *host* here is a real process standing in for Claude Code: it runs the real
hook entry as its own child, exactly as the host would, and is then
terminated the way a host session ends. On POSIX the test starts the host in
its own process group and kills that whole group; on Windows the host puts
itself into a kill-on-close Job Object (optionally permitting breakaway) and
is terminated, which kills every process still in the job.

Every worker a test starts is stopped at teardown through the worker's stop
request, and killed by PID if it does not stop: no test leaves an orphan.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import claude_fixtures as cf
from recalith.controller import worker
from recalith.fast import process_env

HOST_SCRIPT = r"""
import json, os, subprocess, sys, time
spec = json.loads(sys.argv[1])
if os.name == "nt" and spec.get("job") is not None:
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    class Basic(ctypes.Structure):
        _fields_ = [("a", ctypes.c_int64), ("b", ctypes.c_int64), ("LimitFlags", wintypes.DWORD), ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("e", wintypes.DWORD), ("f", ctypes.c_size_t), ("g", wintypes.DWORD), ("h", wintypes.DWORD)]
    class Io(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in "abcdef"]
    class Extended(ctypes.Structure):
        _fields_ = [("Basic", Basic), ("Io", Io), ("p", ctypes.c_size_t), ("q", ctypes.c_size_t), ("r", ctypes.c_size_t), ("s", ctypes.c_size_t)]
    job = k32.CreateJobObjectW(None, None)
    info = Extended()
    info.Basic.LimitFlags = 0x2000 | (0x800 if spec["job"] == "breakaway_ok" else 0)  # KILL_ON_JOB_CLOSE [| BREAKAWAY_OK]
    assert k32.SetInformationJobObject(job, 9, ctypes.addressof(info), ctypes.sizeof(info)), ctypes.get_last_error()
    assert k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()), ctypes.get_last_error()
control = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(3600)"])
hook = subprocess.run(spec["hook"], input=open(spec["stdin"], "rb").read(), capture_output=True, env=spec["env"], timeout=60)
with open(spec["ready"], "w", encoding="utf-8") as fh:
    fh.write(json.dumps({"hook_rc": hook.returncode, "hook_stdout": len(hook.stdout), "control_pid": control.pid, "host_pid": os.getpid()}))
time.sleep(3600)
"""


def wait_for(predicate: Callable[[], Any], timeout: float, interval: float = 0.05) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


def status(root: Path) -> dict[str, Any] | None:
    return worker.read_status(root)


def wait_running(root: Path, timeout: float = 45, *, other_than: int | None = None) -> dict[str, Any] | None:
    def ready():
        s = status(root)
        return s if s and s.get("state") in ("running", "idle", "budget_paused") and s.get("pid") != other_than and process_env.worker_running(root) else None

    return wait_for(ready, timeout)


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return True


def kill_pid(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _started_pid(root: Path) -> int | None:
    try:
        stamp = json.loads((Path(process_env.run_dir(root)) / process_env.START_STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return stamp.get("pid") if isinstance(stamp.get("pid"), int) else None


def stop_worker(root: Path, timeout: float = 20) -> bool:
    """Stop the installation's worker; True if it stopped on request, False if it had to be killed.

    A worker the hook started that has not taken the lock yet is waited for,
    so a failing test cannot leave one coming up behind its back.
    """
    pid = _started_pid(root)
    if not process_env.worker_running(root) and pid is not None and pid_alive(pid):
        wait_for(lambda: process_env.worker_running(root) or not pid_alive(pid), 15)
    if not process_env.worker_running(root):
        if pid is not None and pid_alive(pid):
            kill_pid(pid)
            return False
        return True
    worker.request_stop(root)
    if wait_for(lambda: not process_env.worker_running(root), timeout):
        return True
    s = status(root)
    if s and s.get("pid"):
        kill_pid(int(s["pid"]))
    wait_for(lambda: not process_env.worker_running(root), 10)
    return False


def worker_env(root: Path, **extra: str) -> dict[str, str]:
    """A fresh worker environment for a directly started worker (as the start path builds it)."""
    ctx = cf.identity.resolve_installation(root, actor=cf.ADAPTER_ACTOR)
    manifest = process_env.role_manifest(ctx.installation_id, purpose="worker")
    env = process_env.spawn_environment(manifest, os.environ, purpose="worker")
    env.update(extra)
    return env


def start_direct(root: Path, env: dict[str, str] | None = None) -> subprocess.Popen:
    kwargs: dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x00000200}
    return subprocess.Popen([sys.executable, "-I", "-m", "recalith.controller.worker", "--project", str(root)], env=env if env is not None else worker_env(root), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **kwargs)


def enable_autostart(replayer: cf.Replay) -> None:
    cf.write_hook_context(replayer.ctx, adapter_id="claude_code", host_version=cf.VERSION, worker_autostart=True)


def marked_env(**extra: str) -> dict[str, str]:
    """The environment a Claude Code hook inherits: host markers included."""
    return cf.child_env(CLAUDECODE="1", CLAUDE_CODE_CHILD_SESSION="1", **extra)


def start_record(scenario: str = "lifecycle") -> dict[str, Any]:
    return next(r for r in cf.records(scenario) if r["event"] == "SessionStart")


def prompt_record(scenario: str = "lifecycle") -> dict[str, Any]:
    return next(r for r in cf.records(scenario) if r["event"] == "UserPromptSubmit")


def unique_prompt(replayer: cf.Replay, trial: int) -> bytes:
    """A real 2.1.301 prompt payload whose host identity (transcript position) is unique per trial."""
    record = prompt_record()
    data = replayer.prepare(record)
    payload = json.loads(data)
    payload["prompt"] = f"latency trial {trial}"
    path = Path(payload["transcript_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as fh:
        fh.truncate((record["transcript_bytes"] or 0) + 4096 * (trial + 1))
    return json.dumps(payload).encode("utf-8")


def run_host(tmp: Path, root: Path, data: bytes, *, env: dict[str, str], event: str, job: str | None = None, reply: Path | None = None) -> tuple[subprocess.Popen, dict[str, Any]]:
    """Start a simulated host that runs the real hook; returns (host process, ready record)."""
    stdin = tmp / f"host-stdin-{time.monotonic_ns()}.json"
    stdin.write_bytes(data)
    ready = tmp / f"host-ready-{time.monotonic_ns()}.json"
    spec = {"hook": cf.hook_command(root, event, reply), "stdin": str(stdin), "env": env, "ready": str(ready), "job": job}
    kwargs: dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {}
    host = subprocess.Popen([sys.executable, "-I", "-c", HOST_SCRIPT, json.dumps(spec)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **kwargs)
    record = wait_for(lambda: _ready(ready), 60)
    if not record:
        host.kill()
        raise AssertionError(f"host never ran its hook: {host.stderr.read().decode('utf-8', 'replace')[-2000:] if host.stderr else ''}")
    return host, record


def _ready(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text) if text else None
    except (OSError, ValueError):
        return None


def kill_host(host: subprocess.Popen) -> None:
    """Teardown: make sure a simulated host never outlives its test."""
    if host.poll() is None:
        try:
            terminate_host(host)
        except (OSError, subprocess.TimeoutExpired):
            host.kill()


def start_via_hook(run, attempts: int = 5) -> list[str]:
    """Run hooks until one starts the worker; returns every hook's worker status.

    Under deadline pressure a hook legitimately sheds the start
    (``deadline_worker_start_skipped``) and the next hook retries; anything
    else is a failure the caller sees.
    """
    seen = []
    for _ in range(attempts):
        status = run()
        seen.append(status)
        if status != "deadline_worker_start_skipped":
            break
    return seen


def terminate_host(host: subprocess.Popen) -> None:
    """End the host the way a session ends: its whole process group (POSIX) or job (Windows)."""
    if os.name == "nt":
        host.kill()  # TerminateProcess; the job's last handle closes and kill-on-close applies
    else:
        os.killpg(host.pid, signal.SIGKILL)
    host.wait(timeout=10)
