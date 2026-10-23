"""Claude Code host integration on the stdlib fast path (Task 13; decision 0019).

Standard library only, imported by the hook entry and by the installer:

- :data:`HOOK_EVENTS` and :func:`hook_command`: the exact hook registrations
  ``recalith integrate claude`` installs. Each command runs this project's
  pinned launcher through ``"$CLAUDE_PROJECT_DIR"``, which Claude Code
  2.1.301/2.1.305 sets for every hook process to the directory the session
  was started in; the launcher supplies ``--project`` itself. On native
  Windows the command names the ``.cmd`` launcher (decision 0027).
- :func:`host_output`: the nonblocking host envelope. It carries additional
  model context (certified delivery paths only) and/or a ``systemMessage``
  user notice; never a permission decision, a block or a rewritten tool call.
- :func:`session_notice`: the brief session-start health warning of SYSTEM_SPEC
  §14. It is computed from small local files only (the hook manifest as
  loaded, the worker's own status record, the presence of the provider
  record, the maintenance marker, the spool's gap records and ready
  segments): no SQLite, no Pydantic, no health layer, no model, no launch.
  It names only what *materially* limits memory, at most once per distinct
  set of limitations: a private marker (``run/session-notice.json``) records
  the set before anything is printed, and a marker that cannot be written
  suppresses the notice rather than letting it repeat. A host-observed
  ``systemMessage`` reaches the user and not the model (request-capture
  observation on 2.1.305).
"""

from __future__ import annotations

import json
import os
import time

from recalith.fast import spool
from recalith.fast.wire import digest_of

HOST_ID = "claude_code"
LAUNCHER = ".recalith/bin/recalith-hook"
# Native Windows (decision 0027): Claude Code 2.1.309 runs hook commands through Git Bash, where the POSIX launcher
# finds no ``venv/bin/python`` (a Windows venv has ``Scripts\python.exe``) and silently does nothing; Git Bash runs
# the ``.cmd`` launcher through cmd.exe, which reaches the runtime. ``LAUNCHER`` stays the ownership marker of both.
WINDOWS = os.name == "nt"
WINDOWS_LAUNCHER = LAUNCHER + ".cmd"
HOOK_TIMEOUT_SECONDS = 10
# (event, matcher): every event the exact-version capture mapping handles.
# ``PermissionRequest`` is not registered: it has no tool identity or outcome on
# 2.1.301/2.1.305 and would add a hook process to every permission dialog.
HOOK_EVENTS = (
    ("SessionStart", None),
    ("UserPromptSubmit", None),
    ("PreToolUse", "*"),
    ("PostToolUse", "*"),
    ("PostToolUseFailure", "*"),
    ("PreCompact", None),
    ("PostCompact", None),
    ("Stop", None),
    ("SubagentStart", None),
    ("SubagentStop", None),
    ("SessionEnd", None),
)

NOTICE_FILE = "session-notice.json"
NOTICE_MAX_BYTES = 512
NOTICE_MIN_REMAINING = 0.040
WORKER_STATUS_FILE = "worker.json"
WORKER_STATUS_MAX_BYTES = 64 * 1024
HEARTBEAT_FRESH_SECONDS = 300.0
INGESTION_DELAY_SECONDS = 600.0
MAX_SCAN = 512
REQUIRED_DELIVERY = ("session_start", "prompt")
# Code → the short phrase the user reads; order is the order they are listed.
LIMITATIONS = {
    "inference_unavailable": "no certified inference route, so no new long-term knowledge is learned",
    "delivery_not_certified": "automatic memory delivery is not certified for this Claude Code version",
    "delivery_paused": "memory delivery is paused for privacy maintenance",
    "capture_gaps": "some hook events were not captured",
    "ingestion_delayed": "captured events are waiting for the project worker",
}


def hook_command(event: str, *, windows: bool | None = None) -> str:
    """The exact installed command for ``event``: a POSIX shell command, as Claude Code runs hooks (Git Bash on Windows).

    On POSIX it runs the POSIX launcher; on native Windows the ``.cmd`` launcher.
    """
    launcher = WINDOWS_LAUNCHER if (WINDOWS if windows is None else windows) else LAUNCHER
    return f'"$CLAUDE_PROJECT_DIR"/{launcher} {HOST_ID} --event {event}'


def host_output(hook_event: str, context: str | None = None, notice: str | None = None) -> dict:
    """The nonblocking envelope: model context and/or a user notice, nothing else."""
    out: dict = {}
    if notice:
        out["systemMessage"] = notice
    if context is not None:
        out["hookSpecificOutput"] = {"hookEventName": hook_event, "additionalContext": context}
    return out


def encode(output: dict) -> bytes:
    return json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# --------------------------------------------------------------------------
# The session-start notice


def _run(root: str, name: str) -> str:
    return os.path.join(root, ".recalith", "run", name)


def _read_json(path: str, cap: int):
    try:
        with open(path, "rb") as fh:
            data = fh.read(cap + 1)
    except OSError:
        return None
    if len(data) > cap:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def _utc_seconds(text) -> float | None:
    """Seconds since the epoch of a canonical ``YYYY-MM-DDTHH:MM:SS…Z`` time (no strptime/calendar import on the hook path)."""
    if not isinstance(text, str) or len(text) < 20 or text[4] != "-" or text[10] != "T":
        return None
    try:
        y, m, d = int(text[0:4]), int(text[5:7]), int(text[8:10])
        hh, mm, ss = int(text[11:13]), int(text[14:16]), int(text[17:19])
    except ValueError:
        return None
    y -= m <= 2  # days from the civil date (H. Hinnant's algorithm)
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    days = era * 146097 + yoe * 365 + yoe // 4 - yoe // 100 + doy - 719468
    return float(days * 86400 + hh * 3600 + mm * 60 + ss)


def _inference_unavailable(ctx: dict) -> bool:
    """From the running worker's own fresh report of its route, else only a missing route record counts."""
    status = _read_json(_run(ctx["root"], WORKER_STATUS_FILE), WORKER_STATUS_MAX_BYTES)
    if isinstance(status, dict) and status.get("installation_id") == ctx["installation_id"]:
        beat = _utc_seconds(status.get("heartbeat_at"))
        provider = status.get("provider")
        if beat is not None and time.time() - beat <= HEARTBEAT_FRESH_SECONDS and isinstance(provider, dict):
            return provider.get("state") != "certified"
    return not os.path.exists(os.path.join(ctx["root"], ".recalith", "provider.json"))


def _newest_gap(dirs: spool.SpoolDirs) -> float:
    newest = 0.0
    try:
        with os.scandir(dirs.gaps) as it:
            for n, item in enumerate(it):
                if n >= MAX_SCAN:
                    break
                try:
                    newest = max(newest, item.stat().st_mtime)
                except OSError:
                    continue
    except OSError:
        return 0.0
    return newest


def _oldest_ready(dirs: spool.SpoolDirs) -> float | None:
    oldest = None
    try:
        with os.scandir(dirs.ready) as it:
            for n, item in enumerate(it):
                if n >= MAX_SCAN:
                    break
                try:
                    mtime = item.stat().st_mtime
                except OSError:
                    continue
                oldest = mtime if oldest is None else min(oldest, mtime)
    except OSError:
        return None
    return oldest


def limitations(ctx: dict, previous: dict | None) -> tuple[list[str], float]:
    """The material limitation codes now (in :data:`LIMITATIONS` order) and the newest gap time considered."""
    from recalith.fast import session

    codes: list[str] = []
    if _inference_unavailable(ctx):
        codes.append("inference_unavailable")
    if not set(REQUIRED_DELIVERY) <= set(ctx.get("delivery_paths") or []):
        codes.append("delivery_not_certified")
    if session.maintenance_active(ctx["root"]):
        codes.append("delivery_paused")
    dirs = spool.SpoolDirs(ctx["root"])
    newest = _newest_gap(dirs)
    seen = float((previous or {}).get("newest_gap") or 0.0)
    if newest > seen:
        codes.append("capture_gaps")
    oldest = _oldest_ready(dirs)
    if oldest is not None and time.time() - oldest > INGESTION_DELAY_SECONDS:
        codes.append("ingestion_delayed")
    return codes, max(newest, seen)


def text_for(codes: list[str]) -> str:
    phrases = "; ".join(LIMITATIONS[c] for c in codes)
    text = f"Recalith: memory is limited in this project ({phrases}). For details run .recalith/bin/recalith status from an ordinary terminal."
    raw = text.encode("utf-8")
    return text if len(raw) <= NOTICE_MAX_BYTES else raw[: NOTICE_MAX_BYTES - 3].decode("utf-8", "ignore") + "..."


def _write_marker(path: str, record: dict) -> bool:
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


def session_notice(ctx: dict, request: dict, *, deadline: float) -> str | None:
    """The notice text for this session start, or None (nothing material, already shown, or no time/marker).

    Eligible only for a real session start (``startup``/``resume``/``clear``,
    never compaction) on a certified host version with the integration's
    consent (``notices.session_start`` in the manifest). The marker is
    written *before* the notice is returned, so a printed notice is never
    shown again for the same set of limitations.
    """
    if not ctx.get("session_notice") or not ctx.get("host_certified") or request.get("event_role") != "session_start":
        return None
    events = request.get("events") or []
    if not events or events[0]["kind"] != "session_started":
        return None
    if deadline - time.monotonic() < NOTICE_MIN_REMAINING:
        return None
    path = _run(ctx["root"], NOTICE_FILE)
    previous = _read_json(path, 4096)
    previous = previous if isinstance(previous, dict) else None
    codes, newest = limitations(ctx, previous)
    key = digest_of({"codes": codes, "newest_gap": newest if "capture_gaps" in codes else None})
    if previous is not None and previous.get("key") == key:
        return None
    if not codes:
        if previous is not None and previous.get("codes"):
            _write_marker(path, {"notice_schema": 1, "key": key, "codes": [], "newest_gap": newest})  # resolved: a recurrence warns again
        return None
    if not _write_marker(path, {"notice_schema": 1, "key": key, "codes": codes, "newest_gap": newest}):
        return None  # cannot persist the marker: suppress rather than repeat
    return text_for(codes)
