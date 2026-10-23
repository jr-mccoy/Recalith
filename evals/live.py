"""Live evaluation runs: setup, per-installation certification and real-time quiescence (decisions 0020, 0028).

A live run starts from an ordinary operator terminal (no host or role marker)
with the selected keys exported there. Nothing here mints authority or
certifies by assumption: every administrative step is the operator's own tool
as a child process that inherits this environment unchanged, so a host-marked
caller is refused by the same guards as at the terminal.

Each **candidate installation** of a live smoke trial is provisioned by
:func:`provision`:

1. ``python -m recalith init --operator-token-file FILE`` (the operator- or
   CI-provisioned pre-init token; never created here);
2. ``python bootstrap.py install`` with the verified release wheel, so the
   installed hooks run on the project's own pinned runtime;
3. ``tools/probe_provider.py --route-out`` — a complete live certification of
   the curator route *for this installation*; its ``provider.json`` names this
   installation (nothing is copied, ``foreign_provider_config`` still holds);
4. ``.recalith/bin/recalith integrate claude --operator-token-file FILE``;
5. ``tools/probe_delivery.py --bind-from`` — the host record bound from the
   certified project's live engine-mode record (decision 0028), then the
   integration re-run enables exactly the certified paths.

A **workload day** replays a recorded timeline in process (no host), so it
needs steps 1 and 3 only; its worker is the harness's on the day's virtual
clock with the certified route, gated by the production isolation recheck.

Between the sessions of a live trial the hook-started worker (the product's
registered start) does the curation on real time; :func:`wait_quiescent`
watches the store read-only until nothing is due within the horizon.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
QUIET_HORIZON_SECONDS = 20 * 60  # beyond the 600 s failure debounce and the 300 s quiet window
GAP_DEADLINE_SECONDS = 45 * 60
STALL_SECONDS = 5 * 60
POLL_SECONDS = 5.0
CHILD_TIMEOUT = 900
SESSION_TIMEOUT = 900
AGENT_STDOUT_CAP = 32 * 1024 * 1024
AGENT_TOOLS = ("Bash", "Read", "Edit", "Write")
# A real host session always has its temp directory; the hooks and the worker they start inherit it. Without it,
# Windows falls back to its own directory and SQLite cannot open a temporary file (the first live pilot, 2026-10-23).
TEMP_ENV_KEYS = ("TEMP", "TMP", "TMPDIR")
# The certified engine-mode session flags (tools/probe_engine.py Fixture.argv), with the trial's tool permissions.
SESSION_FLAGS = ("-p", "--strict-mcp-config", "--output-format", "stream-json", "--verbose", "--include-hook-events")


class LiveError(RuntimeError):
    def __init__(self, code: str, detail: str = "", steps: list[dict[str, Any]] | None = None) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.steps = steps or []


def _tool(name: str):
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    return __import__(name)


# --------------------------------------------------------------------------
# Setup


@dataclass
class LiveSetup:
    """What a live run needs, named by the operator; key *values* stay in the environment."""

    config: Path
    token_file: Path
    source_project: Path
    evidence: Path
    wheel: Path
    expected_digest: str
    wheelhouse: Path
    run_dir: Path
    backend: str
    executable: str
    model: str
    delivery: dict[str, Any] = field(repr=False, default_factory=dict)

    def label(self) -> dict[str, Any]:
        """Run metadata without paths of this machine or model identifiers (decision 0027)."""
        return {"backend": self.backend, "agent_model": "<agent-model>", "curator_model": "<curator-model>", "wheel": self.wheel.name, "wheel_sha256": self.expected_digest,
                "delivery_record": "bound from the certified project's live engine-mode record (decision 0028)", "route": "certified per installation by tools/probe_provider.py --route-out"}


def load_setup(*, config: Path | None, token_file: Path | None, source_project: Path | None, evidence: Path | None, wheel: Path | None, wheelhouse: Path | None, run_dir: Path) -> LiveSetup:
    """Validate the operator's inputs (names only); raises :class:`LiveError` naming what is missing."""
    missing = [name for name, value in (("--config", config), ("--operator-token-file", token_file), ("--source-project", source_project), ("--wheel", wheel), ("--wheelhouse", wheelhouse)) if value is None]
    if missing:
        raise LiveError("live_inputs_missing", " ".join(missing))
    assert config and token_file and source_project and wheel and wheelhouse
    for name, path in (("--operator-token-file", token_file), ("--wheel", wheel)):
        if not path.is_file():
            raise LiveError("live_inputs_missing", f"{name} is not a file")
    if not wheelhouse.is_dir():
        raise LiveError("live_inputs_missing", "--wheelhouse is not a directory")
    pd = _tool("probe_delivery")
    pp = _tool("probe_provider")
    try:
        delivery = pd.load_config(config)
        provider = pp.load_config(config)
    except (pd.ConfigError, pp.ConfigError) as exc:
        raise LiveError("live_config_invalid", str(exc)) from exc
    if delivery["model"] is None:
        raise LiveError("live_config_invalid", "the delivery section names no working-agent model")
    digest = _sha256(wheel)
    lock = _engine_lock(source_project)
    if lock.get("artifact_sha256") not in (None, digest):
        raise LiveError("wheel_not_certified_build", "the wheel's digest differs from the certified project's engine.lock")
    return LiveSetup(config=config, token_file=token_file, source_project=source_project, evidence=evidence or ROOT / "docs" / "host-compatibility.json", wheel=wheel,
                     expected_digest=digest, wheelhouse=wheelhouse, run_dir=run_dir, backend=provider["backend"], executable=delivery["executable"], model=delivery["model"], delivery=delivery)


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _engine_lock(project: Path) -> dict[str, Any]:
    import tomllib

    try:
        return tomllib.loads((project / ".recalith" / "engine.lock").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# --------------------------------------------------------------------------
# Provisioning one candidate installation


def _child(argv: list[str], *, step: str, steps: list[dict[str, Any]], expect: int = 0, timeout: float = CHILD_TIMEOUT) -> subprocess.CompletedProcess:
    began = time.monotonic()
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=timeout, check=False, env=dict(os.environ))
    except subprocess.TimeoutExpired as exc:
        steps.append({"step": step, "exit": None, "seconds": round(time.monotonic() - began, 1)})
        raise LiveError(f"{step}_timeout", f"{timeout:.0f} s", steps) from exc
    steps.append({"step": step, "exit": proc.returncode, "seconds": round(time.monotonic() - began, 1)})
    if proc.returncode != expect:
        raise LiveError(("operator_guard_refused" if proc.returncode == 6 else f"{step}_failed"), f"exit {proc.returncode}: {_last_line(proc)}", steps)
    return proc


def _last_line(proc: subprocess.CompletedProcess) -> str:
    text = (proc.stdout or "").strip().splitlines()[-1:] or (proc.stderr or "").strip().splitlines()[-1:] or [""]
    return text[0][:240]


def trial_dirs(out_dir: Path, sid: str, arm: str) -> tuple[Path, str, str]:
    """``(base, workspace name, home name)``; short on Windows, where the provisioned runtime adds about 133 characters
    under the workspace and ``MAX_PATH`` is 260 without ``LongPathsEnabled`` (decision 0027)."""
    if os.name != "nt":
        return out_dir / sid / arm, "ws", "home"
    return out_dir / sid.split("-")[1] / {"candidate": "c", "no_memory": "b"}.get(arm, arm), "w", "h"


def launcher(ws: Path) -> Path:
    return ws / ".recalith" / "bin" / ("recalith.cmd" if os.name == "nt" else "recalith")


def provision(ws: Path, project: str, setup: LiveSetup, *, label: str, host: bool = True) -> dict[str, Any]:
    """Initialize, provision and certify one candidate installation (see the module docstring); returns the step log."""
    from evals import trial

    steps: list[dict[str, Any]] = []
    certification = setup.run_dir / "certification"
    certification.mkdir(parents=True, exist_ok=True)
    began = time.monotonic()
    try:
        trial.init_installation(ws, project, route="operator_token", token_file=setup.token_file, mode="live")
    except trial.TrialError as exc:
        steps.append({"step": "init", "exit": None if exc.code == "init_failed" else 6})
        raise LiveError(exc.code, exc.detail, steps) from exc
    steps.append({"step": "init", "exit": 0, "seconds": round(time.monotonic() - began, 1)})
    if host:
        _child([sys.executable, str(ROOT / "bootstrap.py"), "install", "--project", str(ws), "--wheel", str(setup.wheel), "--expected-digest", setup.expected_digest, "--wheelhouse", str(setup.wheelhouse)], step="bootstrap", steps=steps)
    _child([sys.executable, str(TOOLS / "probe_provider.py"), "--config", str(setup.config), "--backend", setup.backend, "--output", str(certification / f"{label}.route.json"), "--route-out", str(ws)], step="route", steps=steps)
    if host:
        _child([str(launcher(ws)), "integrate", "claude", "--operator-token-file", str(setup.token_file), "--json"], step="integrate", steps=steps)
        _child([sys.executable, str(TOOLS / "probe_delivery.py"), "--config", str(setup.config), "--engine-project", str(ws), "--bind-from", str(setup.source_project), "--evidence", str(setup.evidence),
                "--output", str(certification / f"{label}.binding.json")], step="bind_host_record", steps=steps)
    return {"route": "operator_token", "steps": steps, "host": host}


def stop_worker(ws: Path, setup: LiveSetup) -> dict[str, Any]:
    """Stop the installation's hook-started worker through the guarded CLI with the operator token."""
    if not launcher(ws).exists():
        return {"state": "no_launcher"}
    try:
        proc = subprocess.run([str(launcher(ws)), "worker", "stop", "--operator-token-file", str(setup.token_file), "--json"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL, timeout=120, check=False, env=dict(os.environ))
    except subprocess.TimeoutExpired:
        return {"state": "stop_timeout"}
    try:
        state = (json.loads(proc.stdout or "{}").get("result") or {}).get("state")
    except ValueError:
        state = None
    return {"state": state or f"exit_{proc.returncode}", "exit": proc.returncode}


# --------------------------------------------------------------------------
# The certified route as a harness worker's backend (workload days)


class CallRecorder:
    """The certified backend unchanged, with each launch timed and recorded (purpose, request size, job, real seconds)."""

    def __init__(self, backend: Any, *, on_call: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._backend = backend
        self.on_call = on_call
        self.calls: list[dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    def launch(self, request: bytes, *, timeout_s: float, purpose: str):
        began = time.monotonic()
        outcome = self._backend.launch(request, timeout_s=timeout_s, purpose=purpose)
        try:
            job_id = json.loads(request.decode("utf-8")).get("job_id")
        except (ValueError, UnicodeDecodeError, AttributeError):
            job_id = None
        record = {"purpose": purpose, "request_bytes": len(request), "job_id": job_id, "operations": [], "real_seconds": round(time.monotonic() - began, 3),
                  "returncode": outcome.returncode, "timed_out": outcome.timed_out}
        self.calls.append(record)
        if self.on_call is not None:
            self.on_call(record)
        return outcome


def certified_backend(ctx: Any, *, on_call: Callable[[dict[str, Any]], None] | None = None, timeout: float = 300.0) -> tuple[CallRecorder, Any]:
    """The installation's own route through the production supervisor: certified now, and its isolation recheck passed."""
    from recalith.providers import base

    supervisor = base.ProviderSupervisor(ctx, inherited=os.environ)
    if supervisor.backend is None:
        raise LiveError("route_uncertified", ",".join(supervisor.status.reasons))
    supervisor.start()
    supervisor.ready.wait(timeout)
    if not supervisor.available:
        raise LiveError("isolation_recheck_failed", ",".join(supervisor.report()["reasons"])[:300])
    return CallRecorder(supervisor.backend, on_call=on_call), supervisor


# --------------------------------------------------------------------------
# The working agent's environment


def python_dir() -> str:
    """A plain interpreter's directory for the agent's ``python`` (the base interpreter: no engine entry points)."""
    base = getattr(sys, "_base_executable", None) or sys.executable
    return str(Path(base).resolve().parent)


def agent_env(setup: LiveSetup, home: Path, *, route_keys: list[str]) -> dict[str, str]:
    """The live agent's environment: the certified session keys, a private HOME, native memory disabled, no markers."""
    from evals import baselines

    pc = _tool("probe_common")
    cfg = setup.delivery
    keys = [*cfg["platform_env_keys"], *TEMP_ENV_KEYS, *cfg["network_env_keys"], *cfg["auth_route"]["env_keys"], *route_keys]
    env = {k: os.environ[k] for k in dict.fromkeys(keys) if k in os.environ}
    env.update({k: v.replace("{home}", str(home)) for k, v in cfg["home_env"].items()})
    env.update(cfg["nonsecret_env"])
    env.update(baselines.DISABLE_ENV)
    env["PATH"] = os.pathsep.join([python_dir(), env.get("PATH", os.defpath)])
    for marker in (*cfg["host_markers"], *pc.ROLE_MARKERS):
        env.pop(marker, None)
    return env


def route_keys(ws: Path) -> list[str]:
    """The installation's route key names (its hook-started worker carries them to the curator)."""
    from recalith.providers import base

    config = base.load_provider_config(ws)
    return [] if config is None else list(dict.fromkeys([*config.auth_env_keys, *config.network_env_keys]))


# --------------------------------------------------------------------------
# Real-time quiescence between sessions


def _utc(moment: float) -> str:
    import datetime as _dt

    from recalith.contracts.common import format_utc

    return format_utc(_dt.datetime.fromtimestamp(moment, _dt.timezone.utc))


def queue_state(ws: Path, *, now: float, horizon: float = QUIET_HORIZON_SECONDS) -> dict[str, Any]:
    """Read-only: what the worker still owes before the next session (``quiet`` when nothing is due within ``horizon``)."""
    from recalith.contracts.common import parse_utc
    from recalith.fast import spool
    from recalith.storage import db

    from evals import trial

    ready = len(spool.ready_segments(spool.SpoolDirs(ws)))
    limit = _utc(now + horizon)
    with db.open_store(trial.context(ws), readonly=True) as store, store.read() as view:
        leased = view.execute("SELECT COUNT(*) FROM jobs WHERE state = 'leased'").fetchone()[0]
        due = view.execute("SELECT kind, due_at, body FROM jobs WHERE state IN ('pending', 'waiting_budget') AND due_at <= ? ORDER BY due_at", (limit,)).fetchall()
        triggers = view.execute("SELECT MIN(due_at), COUNT(*) FROM failure_triggers WHERE state = 'pending' AND due_at <= ?", (limit,)).fetchone()
        progress = view.execute("SELECT (SELECT COUNT(*) FROM operations), (SELECT COUNT(*) FROM events), (SELECT COUNT(*) FROM jobs WHERE state IN ('completed', 'failed', 'cancelled'))").fetchone()
    stuck = sorted({(json.loads(b).get("last_error_code") or "") for _k, _d, b in due if json.loads(b).get("last_error_code")})
    times = [d for _k, d, _b in due] + ([triggers[0]] if triggers[1] else [])
    next_due = min(times) if times else None
    quiet = not ready and not leased and next_due is None
    return {"quiet": quiet, "spool_ready": ready, "leased": leased, "due_jobs": len(due), "due_kinds": sorted({k for k, _d, _b in due}), "pending_triggers": int(triggers[1] or 0),
            "next_due_in_s": None if next_due is None else round(parse_utc(next_due).timestamp() - now, 1), "waiting_reasons": stuck, "progress": list(progress)}


def wait_quiescent(ws: Path, *, horizon: float = QUIET_HORIZON_SECONDS, deadline: float = GAP_DEADLINE_SECONDS, stall: float = STALL_SECONDS,
                   clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep, worker_running: Callable[[Path], bool] | None = None) -> dict[str, Any]:
    """Wait on real time until the installation owes nothing due within ``horizon`` (or ``deadline`` / a stall ends the wait).

    Returns ``{"state": "quiet"|"deadline"|"stalled", "waited_s", "last": queue_state, "polls", "worker_seen"}``.
    ``stalled``: due work and no store progress for ``stall`` seconds (for example no worker or a route that went
    unavailable); the trial records it and continues, so the next session sees what the engine really had.
    """
    from recalith.fast import process_env

    running = worker_running or (lambda root: process_env.worker_running(str(root)))
    started = clock()
    last_progress, last_change = None, started
    polls = 0
    seen = False
    while True:
        now = clock()
        state = queue_state(ws, now=now, horizon=horizon)
        polls += 1
        seen = seen or running(ws)
        if state["quiet"]:
            return {"state": "quiet", "waited_s": round(now - started, 1), "last": state, "polls": polls, "worker_seen": seen}
        if state["progress"] != last_progress:
            last_progress, last_change = state["progress"], now
        if now - started >= deadline:
            return {"state": "deadline", "waited_s": round(now - started, 1), "last": state, "polls": polls, "worker_seen": seen}
        if now - last_change >= stall and not state["leased"]:
            return {"state": "stalled", "waited_s": round(now - started, 1), "last": state, "polls": polls, "worker_seen": seen}
        due_in = state["next_due_in_s"]
        sleep(POLL_SECONDS if due_in is None or due_in <= 0 else min(max(due_in, 1.0), 60.0))


def has_launcher_runtime(ws: Path) -> bool:
    lock = _engine_lock(ws)
    version = lock.get("engine_version")
    venv = ws / ".recalith" / "runtime" / str(version) / "venv"
    return bool(version) and (venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")).exists()


def remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
