"""Bounded child-process launch for model backends (SYSTEM_SPEC §6.3, §9.1; A30).

The worker never waits on an unbounded child. :func:`run_bounded` runs an
argument array (never a shell) with:

* a wall-clock timeout (default 120 s), after which the whole process tree is
  killed;
* raw stdout bounded *while reading* at 256 KiB: one byte more kills the tree
  and the output is rejected, never clipped;
* stderr retained up to 64 KiB, the remainder drained and discarded;
* the whole tree contained: on POSIX a new session/process group that is
  killed as a group, including descendants that outlive the leader; on
  Windows a Job Object with kill-on-close, assigned while the child is still
  suspended, so no grandchild can escape before assignment. If the Job Object
  cannot be created the result reports ``tree_bound = "degraded"`` instead of
  claiming containment.

The child environment is built by the caller with
``recalith.fast.process_env.spawn_environment`` (purpose ``curator``); this
module never copies the worker's own environment.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

from recalith.contracts.config import STDERR_CAP, WIRE_STDOUT_CAP

CREATE_SUSPENDED = 0x00000004
CREATE_NEW_PROCESS_GROUP = 0x00000200


@dataclass
class BoundedResult:
    returncode: int | None = None
    stdout: bytes = b""
    stderr: bytes = b""
    stdout_overflow: bool = False
    stderr_truncated: bool = False
    timed_out: bool = False
    killed: bool = False
    duration_ms: int = 0
    tree_bound: str = "unknown"  # contained | degraded
    tree_cleaned: bool | None = None
    descendants_outlived_exit: bool = False
    pid: int | None = None
    observed_env_keys: list[str] | None = None  # Linux /proc only; None when unobservable
    notes: list[str] = field(default_factory=list)

    @property
    def interrupted(self) -> bool:
        return self.timed_out or self.stdout_overflow or self.returncode is None


# --------------------------------------------------------------------------
# POSIX process groups


def _linux_group_members(pgid: int) -> list[str] | None:
    proc_root = Path("/proc")
    if not (proc_root / "self" / "stat").exists():
        return None
    states = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fields = stat[stat.rfind(")") + 2 :].split()
        if len(fields) > 2 and int(fields[2]) == pgid:
            states.append(fields[0])
    return states


def observed_environment_keys(pid: int, *, attempts: int = 20, interval_s: float = 0.01) -> list[str] | None:
    """Key names of a live child's initial environment (Linux ``/proc`` only; names, never values).

    While a launcher shim ``exec``s the real program ``/proc`` can briefly read
    empty; a curator child always carries its role marker, so an empty read is
    re-sampled and, if it persists, reported unobservable (None).
    """
    path = Path(f"/proc/{pid}/environ")
    for _ in range(attempts):
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        keys = sorted({item.split(b"=", 1)[0].decode("utf-8", "replace") for item in raw.split(b"\0") if b"=" in item})
        if keys:
            return keys
        time.sleep(interval_s)
    return None


def group_alive(pgid: int) -> bool:
    states = _linux_group_members(pgid)
    if states is not None:
        return any(state != "Z" for state in states)
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill_group(proc: subprocess.Popen, pgid: int) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        give_up = time.monotonic() + 1.0
        while time.monotonic() < give_up:
            proc.poll()
            if not group_alive(pgid):
                return
            time.sleep(0.02)


# --------------------------------------------------------------------------
# Windows Job Objects (ctypes; never imported on the hook path)


class _WindowsJob:  # pragma: no cover - exercised on native Windows runners
    """A kill-on-close Job Object holding exactly one launched process tree."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.ntdll = ctypes.WinDLL("ntdll")
        self.k32.CreateJobObjectW.restype = wintypes.HANDLE
        self.k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.k32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        self.k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]

        class Basic(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
            ]

        class Io(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Io), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        class Accounting(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64), ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD), ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        self.Accounting = Accounting
        self.handle = self.k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.k32.SetInformationJobObject(self.handle, 9, ctypes.addressof(info), ctypes.sizeof(info)):
            self.close()
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")

    def adopt_suspended(self, proc: subprocess.Popen) -> None:
        handle = int(proc._handle)  # type: ignore[attr-defined]
        if not self.k32.AssignProcessToJobObject(self.handle, handle):
            raise OSError(self.ctypes.get_last_error(), "AssignProcessToJobObject failed")
        if self.ntdll.NtResumeProcess(handle) != 0:
            raise OSError(0, "NtResumeProcess failed")

    def active_processes(self) -> int | None:
        acct = self.Accounting()
        if not self.k32.QueryInformationJobObject(self.handle, 1, self.ctypes.addressof(acct), self.ctypes.sizeof(acct), None):
            return None
        return int(acct.ActiveProcesses)

    def terminate(self) -> None:
        if self.handle:
            self.k32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            self.k32.CloseHandle(self.handle)
            self.handle = None


# --------------------------------------------------------------------------
# The bounded run


def run_bounded(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path | str,
    stdin_data: bytes,
    timeout_s: float,
    stdout_cap: int = WIRE_STDOUT_CAP,
    stderr_cap: int = STDERR_CAP,
    observe_env: bool = False,
    on_spawn: "Callable[[int, int | None], None] | None" = None,
) -> BoundedResult:
    result = BoundedResult()
    kwargs: dict = {}
    job = None
    if os.name == "nt":  # pragma: no cover - native Windows
        try:
            job = _WindowsJob()
            kwargs["creationflags"] = CREATE_NEW_PROCESS_GROUP | CREATE_SUSPENDED
        except OSError:
            kwargs["creationflags"] = CREATE_NEW_PROCESS_GROUP
            result.notes.append("job_object_unavailable")
    else:
        kwargs["start_new_session"] = True
    start = time.monotonic()
    proc = subprocess.Popen(list(argv), cwd=str(cwd), env=dict(env), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, close_fds=True, **kwargs)
    result.pid = proc.pid
    pgid = None
    if os.name == "nt":  # pragma: no cover
        if job is not None:
            try:
                job.adopt_suspended(proc)
                result.tree_bound = "contained"
            except OSError:
                result.notes.append("job_assignment_failed")
                job.close()
                job = None
                proc.kill()
                proc.wait(timeout=5)
                raise
        else:
            result.tree_bound = "degraded"
    else:
        pgid = os.getpgid(proc.pid)
        result.tree_bound = "contained"

    overflow = threading.Event()
    out_buf = bytearray()
    err_buf = bytearray()

    def read_stdout() -> None:
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read1(65536)
            if not chunk:
                return
            if len(out_buf) + len(chunk) > stdout_cap:
                overflow.set()
                return
            out_buf.extend(chunk)

    def read_stderr() -> None:
        assert proc.stderr is not None
        while True:
            chunk = proc.stderr.read1(65536)
            if not chunk:
                return
            room = stderr_cap - len(err_buf)
            if room > 0:
                err_buf.extend(chunk[:room])
            if len(chunk) > max(room, 0):
                result.stderr_truncated = True

    def write_stdin() -> None:
        assert proc.stdin is not None
        try:
            proc.stdin.write(stdin_data)
            proc.stdin.close()
        except OSError:
            pass

    threads = [threading.Thread(target=t, daemon=True) for t in (read_stdout, read_stderr, write_stdin)]
    if on_spawn is not None:
        try:
            on_spawn(proc.pid, pgid)
        except BaseException:
            if job is not None:
                job.terminate()
            elif pgid is not None:
                _kill_group(proc, pgid)
            raise
    if observe_env and os.name != "nt":
        result.observed_env_keys = observed_environment_keys(proc.pid)
    for t in threads:
        t.start()

    def kill_tree() -> None:
        result.killed = True
        if job is not None:
            job.terminate()
        elif pgid is not None:
            _kill_group(proc, pgid)
        else:  # pragma: no cover - Windows without a Job Object
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)

    deadline = start + timeout_s
    while True:
        if overflow.is_set():
            result.stdout_overflow = True
            kill_tree()
            break
        if proc.poll() is not None:
            break
        if time.monotonic() >= deadline:
            result.timed_out = True
            kill_tree()
            break
        time.sleep(0.01)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        kill_tree()
        proc.wait(timeout=5)
    # Descendants that outlived the leader still belong to this launch.
    if pgid is not None:
        if group_alive(pgid):
            result.descendants_outlived_exit = not result.killed
            _kill_group(proc, pgid)
            result.killed = True
        result.tree_cleaned = not group_alive(pgid)
    elif job is not None:  # pragma: no cover
        active = job.active_processes()
        if active:
            result.descendants_outlived_exit = not result.killed
            job.terminate()
            result.killed = True
            time.sleep(0.05)
            active = job.active_processes()
        result.tree_cleaned = active == 0 if active is not None else None
        job.close()
    for t in threads:
        t.join(timeout=2)
    result.stdout_overflow = result.stdout_overflow or overflow.is_set()
    result.returncode = None if (result.timed_out or result.stdout_overflow) else proc.returncode
    result.stdout = b"" if result.stdout_overflow else bytes(out_buf)
    result.stderr = bytes(err_buf)
    result.duration_ms = int((time.monotonic() - start) * 1000)
    return result
