"""Shared, standard-library-only helpers for the Task 0/0b standalone probes.

These probes run before the engine exists (IMPLEMENTATION_PLAN Tasks 0 and 0b),
so nothing here needs an engine database; the only engine module used is the
stdlib-only ``recalith.fast.process_env``. Every helper is deliberately small:

* ``build_child_environment`` constructs a *fresh* allowlisted child
  environment (SYSTEM_SPEC §9.1) through the engine's one stdlib helper,
  ``recalith.fast.process_env.spawn_environment`` (no second filter). It never
  copies the inherited map wholesale, always removes registered
  host/nested-session markers and inherited recalith role markers, then sets
  exactly one fresh role marker.
* ``run_bounded`` launches an argument array with ``shell=False`` in its own
  process group, bounds raw stdout/stderr while reading, enforces a wall-clock
  deadline and verifies the whole process tree is gone afterwards.
* ``RecordingEndpoint`` is a loopback-only Anthropic-Messages-compatible
  recording server used by the request-capture diagnostic mode. It lets the
  probe inspect the exact request an installed CLI would send (tool inventory,
  system prompt, messages) without any account or credential.
* ``merge_report_section`` updates one section of ``docs/host-compatibility.json``
  atomically and never overwrites another probe's section.

Values of environment variables are never written to reports; only key names.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import http.server
import json
import os
import platform
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REPORT_SCHEMA = 1

# Exit codes shared by both probes (IMPLEMENTATION_PLAN Task 0/0b interfaces).
EXIT_CERTIFIED = 0
EXIT_USAGE = 2
EXIT_UNAVAILABLE = 4
EXIT_DEGRADED = 8

# Registered host / nested-session markers. Only documented-and-observed markers
# are registered (SYSTEM_SPEC §13.1); a Codex marker is not invented here.
DEFAULT_HOST_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION")
WORKER_MARKER = "RECALITH_WORKER_INSTALLATION"
CURATOR_MARKER = "RECALITH_CURATOR_INSTALLATION"
ROLE_MARKERS = (WORKER_MARKER, CURATOR_MARKER)
ROLE_FOR_PURPOSE = {"worker": WORKER_MARKER, "curator": CURATOR_MARKER}

# Platform keys a CLI child generally needs. Purpose-specific HOME/config keys
# are *not* here: the probe supplies its own fixture values for those.
DEFAULT_PLATFORM_ENV_KEYS = (
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "TERM",
    "SystemRoot",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
)

WIRE_STDOUT_CAP = 256 * 1024
STDERR_CAP = 64 * 1024

_SECRETISH = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|gh[pousr]_[A-Za-z0-9]{16,}|"
    r"(?i:api[_-]?key|token|secret|password)\s*[=:]\s*\S+|"
    # Generic opaque tokens: 40+ chars mixing upper case, lower case and digits
    # (hex digests, identifiers and env-var names do not match).
    r"\b(?=[A-Za-z0-9+/_\-]*[0-9])(?=[A-Za-z0-9+/_\-]*[a-z])(?=[A-Za-z0-9+/_\-]*[A-Z])[A-Za-z0-9+/_\-]{40,}={0,2})",
)


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def platform_facts() -> dict[str, str]:
    system = platform.system().lower()
    os_name = {"windows": "windows", "linux": "linux", "darwin": "macos"}.get(system, "other")
    machine = platform.machine().lower()
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(machine, "other")
    return {
        "os": os_name,
        "arch": arch,
        "platform": platform.platform(),
        "python": platform.python_version(),
    }


# --------------------------------------------------------------------------
# Sanitization


WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def path_forms(path: str) -> list[str]:
    """Every spelling of ``path`` a host payload or probe report can carry.

    A POSIX path appears as is. A Windows drive path also appears with forward
    slashes (``Path.as_posix()``, ``$CLAUDE_PROJECT_DIR`` in Git Bash),
    JSON-escaped once or twice (a command echoed inside a JSON string) and in
    the MSYS form Git Bash prints (``/c/...``); match those case-insensitively.
    """
    if not WINDOWS_PATH.match(path):
        return [path]
    native = path.replace("/", "\\").rstrip("\\")
    msys = "/" + native[0].lower() + native[2:].replace("\\", "/")
    return list(dict.fromkeys([native, native.replace("\\", "/"), native.replace("\\", "\\\\"), native.replace("\\", "\\\\\\\\"), msys]))


def replace_path(value: str, old: str, new: str, *, fold: bool) -> str:
    return re.sub(re.escape(old), lambda _m: new, value, flags=re.IGNORECASE) if fold else value.replace(old, new)


class Sanitizer:
    """Replace local paths (on Windows in every spelling, :func:`path_forms`) with placeholders and scrub secret-shaped text."""

    def __init__(self, replacements: Mapping[str, str] | None = None, secrets: Iterable[str] = ()) -> None:
        pairs = [(form, v, bool(WINDOWS_PATH.match(k))) for k, v in (replacements or {}).items() if k for form in path_forms(k)]
        # Longest first so nested paths map to the most specific placeholder.
        self._pairs = sorted(pairs, key=lambda kv: len(kv[0]), reverse=True)
        self._secrets = [s for s in secrets if s and len(s) >= 4]

    def text(self, value: str, *, limit: int | None = 2048) -> str:
        for secret in self._secrets:
            value = value.replace(secret, "<redacted>")
        for old, new, fold in self._pairs:
            value = replace_path(value, old, new, fold=fold)
        value = _SECRETISH.sub("<redacted>", value)
        if limit is not None and len(value) > limit:
            value = value[:limit] + f"...<{len(value) - limit} chars omitted>"
        return value

    def value(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.text(obj, limit=None)
        if isinstance(obj, list):
            return [self.value(v) for v in obj]
        if isinstance(obj, dict):
            return {self.text(str(k), limit=None): self.value(v) for k, v in obj.items()}
        return obj


# --------------------------------------------------------------------------
# Fresh allowlisted child environment


class EnvironmentPolicyError(ValueError):
    pass


def _process_env():
    """The engine's stdlib role-environment helper (``recalith.fast.process_env``).

    It is standard library only and needs no engine database, so the
    standalone probes reuse it instead of keeping a second environment filter
    (DATA_CONTRACTS §2.3; Task 7 migration).
    """
    src = str(Path(__file__).resolve().parent.parent / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from recalith.fast import process_env

    return process_env


def build_child_environment(
    inherited: Mapping[str, str],
    *,
    purpose: str,
    installation_id: str,
    platform_keys: Sequence[str],
    selected_auth_keys: Sequence[str] = (),
    network_keys: Sequence[str] = (),
    overrides: Mapping[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """``(environment, key-name report)`` for an engine-owned child role, via ``spawn_environment``.

    Only the named keys are taken from ``inherited`` (platform keys, then the
    selected route's auth and network keys); ``overrides`` supplies
    purpose-specific nonsecret values (fixture HOME, telemetry switches) and
    may not name a marker. Registered host markers and inherited recalith role
    markers are removed after selection and the one fresh role marker is set.
    The inherited map is never mutated.
    """
    pe = _process_env()
    manifest = {
        "manifest_schema": 1,
        "purpose": purpose,
        "installation_id": installation_id,
        "platform_keys": list(platform_keys),
        "route_keys": list(dict.fromkeys([*network_keys, *selected_auth_keys])),
        "overrides": dict(overrides or {}),
    }
    try:
        return pe.spawn_environment_report(manifest, inherited, purpose=purpose)
    except pe.ManifestError as exc:
        raise EnvironmentPolicyError(str(exc)) from None


def environment_key_report(
    child: Mapping[str, str],
    inherited: Mapping[str, str],
    *,
    host_markers: Sequence[str],
    purpose: str,
) -> dict[str, Any]:
    """Describe a child environment by key names only."""
    role = ROLE_FOR_PURPOSE[purpose]
    other_roles = [m for m in ROLE_MARKERS if m != role]
    return {
        "child_keys": sorted(child),
        "removed_inherited_keys": sorted(set(inherited) - set(child)),
        "host_markers_present": sorted(k for k in host_markers if k in child),
        "role_marker_present": role in child,
        "other_role_markers_present": sorted(k for k in other_roles if k in child),
    }


def observed_process_environment_keys(pid: int, *, attempts: int = 20, interval_s: float = 0.01) -> list[str] | None:
    """Key names of a live child's initial environment (Linux /proc only).

    While a launcher shim ``exec``s the real CLI, /proc can briefly report an
    empty environment. A launched child always carries at least its role
    marker, so an empty read is re-sampled and, if it persists, reported as
    unobservable (None) rather than as an observed empty environment.
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


# --------------------------------------------------------------------------
# Bounded subprocess execution


class BoundedResult:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.stdout = b""
        self.stderr = b""
        self.stdout_overflow = False
        self.stderr_truncated = False
        self.timed_out = False
        self.killed = False
        self.duration_ms = 0
        self.tree_cleaned: bool | None = None
        self.descendants_outlived_exit = False
        self.observed_env_keys: list[str] | None = None
        self.pid: int | None = None

    def to_report(self) -> dict[str, Any]:
        return {
            "returncode": self.returncode,
            "stdout_bytes": len(self.stdout),
            "stderr_bytes_retained": len(self.stderr),
            "stdout_overflow": self.stdout_overflow,
            "stderr_truncated": self.stderr_truncated,
            "timed_out": self.timed_out,
            "killed": self.killed,
            "duration_ms": self.duration_ms,
            "process_tree_cleaned": self.tree_cleaned,
            "descendants_outlived_exit": self.descendants_outlived_exit,
        }


def _linux_group_states(pgid: int) -> list[str] | None:
    """Process states of the group's members from /proc, or None if unavailable."""
    proc_root = Path("/proc")
    if not (proc_root / "self" / "stat").exists():
        return None
    states = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        # Fields after the parenthesized command: state ppid pgrp ...
        fields = stat[stat.rfind(")") + 2 :].split()
        if len(fields) > 2 and int(fields[2]) == pgid:
            states.append(fields[0])
    return states


def _process_group_alive(pgid: int) -> bool:
    """True while any non-zombie member of the process group exists."""
    states = _linux_group_states(pgid)
    if states is not None:
        return any(state != "Z" for state in states)
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill_tree(proc: subprocess.Popen, pgid: int | None) -> None:
    if os.name == "nt":  # pragma: no cover - exercised on native Windows runners
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)
        return
    if pgid is None:
        proc.kill()
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            proc.poll()  # reap the leader so it does not linger as a zombie
            if not _process_group_alive(pgid):
                return
            time.sleep(0.02)


def run_bounded(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    stdin_data: bytes,
    timeout_s: float,
    stdout_cap: int = WIRE_STDOUT_CAP,
    stderr_cap: int = STDERR_CAP,
    observe_env: bool = False,
) -> BoundedResult:
    """Run ``argv`` (never through a shell) with bounded output and deadline.

    Stdout beyond ``stdout_cap`` is a hard failure: the tree is killed and the
    output rejected rather than clipped. Stderr is retained up to ``stderr_cap``
    and the remainder drained and discarded.
    """
    result = BoundedResult()
    kwargs: dict[str, Any] = {}
    if os.name == "nt":  # pragma: no cover
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    start = time.monotonic()
    proc = subprocess.Popen(
        list(argv),
        cwd=str(cwd),
        env=dict(env),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        close_fds=True,
        **kwargs,
    )
    result.pid = proc.pid
    pgid = None if os.name == "nt" else os.getpgid(proc.pid)
    if observe_env:
        result.observed_env_keys = observed_process_environment_keys(proc.pid)

    overflow = threading.Event()
    out_buf = bytearray()
    err_buf = bytearray()

    def read_stdout() -> None:
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read1(65536) if hasattr(proc.stdout, "read1") else proc.stdout.read(65536)
            if not chunk:
                return
            if len(out_buf) + len(chunk) > stdout_cap:
                overflow.set()
                return
            out_buf.extend(chunk)

    def read_stderr() -> None:
        assert proc.stderr is not None
        while True:
            chunk = proc.stderr.read(65536)
            if not chunk:
                return
            room = stderr_cap - len(err_buf)
            if room > 0:
                err_buf.extend(chunk[:room])
            if len(chunk) > max(room, 0):
                result.stderr_truncated = True

    t_out = threading.Thread(target=read_stdout, daemon=True)
    t_err = threading.Thread(target=read_stderr, daemon=True)
    t_out.start()
    t_err.start()
    try:
        assert proc.stdin is not None
        proc.stdin.write(stdin_data)
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass

    deadline = start + timeout_s
    while True:
        if overflow.is_set():
            result.stdout_overflow = True
            result.killed = True
            _kill_tree(proc, pgid)
            break
        if proc.poll() is not None:
            break
        if time.monotonic() >= deadline:
            result.timed_out = True
            result.killed = True
            _kill_tree(proc, pgid)
            break
        time.sleep(0.01)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        _kill_tree(proc, pgid)
        proc.wait(timeout=5)
    # Descendants that outlived the leader are still part of this launch; kill
    # them before joining readers, since they may hold the output pipes open.
    if pgid is not None:
        if _process_group_alive(pgid):
            result.descendants_outlived_exit = not result.killed
            _kill_tree(proc, pgid)
            result.tree_cleaned = not _process_group_alive(pgid)
            result.killed = True
        else:
            result.tree_cleaned = True
    t_out.join(timeout=2)
    t_err.join(timeout=2)
    if overflow.is_set():
        result.stdout_overflow = True
    result.returncode = proc.returncode
    result.stdout = b"" if result.stdout_overflow else bytes(out_buf)
    result.stderr = bytes(err_buf)
    result.duration_ms = int((time.monotonic() - start) * 1000)
    return result


# --------------------------------------------------------------------------
# Loopback recording endpoint (request-capture diagnostic mode)


class RecordingEndpoint:
    """Loopback Anthropic-Messages-compatible server that records requests.

    ``responder(body) -> (behavior, payload)`` chooses the reply. Behaviors:
    ``text`` (normal reply; payload is the text), ``tool_use`` (payload is
    ``{"name": ..., "input": {...}}``), ``hang`` (never answer), and ``error``
    (HTTP 500). Credentials in headers are never recorded.
    """

    def __init__(self, responder: Callable[[dict], tuple[str, str]]) -> None:
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._responder = responder
        self._release = threading.Event()
        self._tool_seq = 0
        endpoint = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                return

            def _record(self, body: Any) -> None:
                headers = {
                    k.lower(): ("<redacted>" if k.lower() in {"x-api-key", "authorization", "cookie"} else v)
                    for k, v in self.headers.items()
                }
                with endpoint._lock:
                    endpoint.requests.append({"method": self.command, "path": self.path, "headers": headers, "body": body})

            def do_GET(self) -> None:  # noqa: N802
                self._record(None)
                self.send_response(404)
                self.send_header("content-length", "0")
                self.end_headers()

            def do_HEAD(self) -> None:  # noqa: N802
                self._record(None)
                self.send_response(200)
                self.send_header("content-length", "0")
                self.end_headers()

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body: Any = json.loads(raw)
                except ValueError:
                    body = {"_unparsed_bytes": len(raw)}
                self._record(body)
                if not self.path.startswith("/v1/messages") or "count_tokens" in self.path:
                    self._send_json({"input_tokens": 1})
                    return
                behavior, text = endpoint._responder(body if isinstance(body, dict) else {})
                if behavior == "hang":
                    endpoint._release.wait(timeout=600)
                    return
                if behavior == "error":
                    self._send_json({"type": "error", "error": {"type": "api_error", "message": "probe"}}, status=500)
                    return
                model = body.get("model") if isinstance(body, dict) else None
                if behavior == "tool_use":
                    with endpoint._lock:
                        endpoint._tool_seq += 1
                        tool_id = f"toolu_probe_{endpoint._tool_seq:04d}"
                    block = {"type": "tool_use", "id": tool_id, "name": text["name"], "input": text["input"]}
                    stop = "tool_use"
                else:
                    block = {"type": "text", "text": text}
                    stop = "end_turn"
                if isinstance(body, dict) and body.get("stream"):
                    self._send_stream(model, block, stop)
                else:
                    self._send_json(
                        {
                            "id": "msg_probe",
                            "type": "message",
                            "role": "assistant",
                            "model": model,
                            "content": [block],
                            "stop_reason": stop,
                            "stop_sequence": None,
                            "usage": {"input_tokens": 1, "output_tokens": 1},
                        }
                    )

            def _send_json(self, obj: Any, status: int = 200) -> None:
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_stream(self, model: Any, block: dict, stop: str) -> None:
                if block["type"] == "tool_use":
                    start = {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}
                    delta = {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
                else:
                    start = {"type": "text", "text": ""}
                    delta = {"type": "text_delta", "text": block["text"]}
                events = [
                    ("message_start", {"type": "message_start", "message": {"id": "msg_probe", "type": "message", "role": "assistant", "model": model, "content": [], "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}}),
                    ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": start}),
                    ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": delta}),
                    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 1}}),
                    ("message_stop", {"type": "message_stop"}),
                ]
                payload = b"".join(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode() for name, data in events)
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "RecordingEndpoint":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._release.set()
        self._server.shutdown()
        self._server.server_close()

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.requests)


def message_requests(requests: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [r["body"] for r in requests if str(r.get("path", "")).startswith("/v1/messages") and "count_tokens" not in str(r.get("path")) and isinstance(r.get("body"), dict)]


# --------------------------------------------------------------------------
# Report handling


def load_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"report_schema": REPORT_SCHEMA, "sections": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("report_schema") != REPORT_SCHEMA or not isinstance(data.get("sections"), dict):
        raise ValueError(f"{path} is not a report_schema={REPORT_SCHEMA} compatibility report")
    return data


def merge_report_section(path: Path, section: str, key: str, value: Mapping[str, Any]) -> dict[str, Any]:
    """Replace ``sections[section][key]`` atomically, preserving everything else."""
    report = load_report(path)
    report["sections"].setdefault(section, {})[key] = value
    report["updated_at"] = utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".host-compat-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:  # LF on every OS, as .gitattributes pins
            json.dump(report, fh, indent=2, sort_keys=False, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return report


def die_usage(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return EXIT_USAGE
