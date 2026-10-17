"""The persistent project worker (SYSTEM_SPEC §4, §6.1–6.3; DATA_CONTRACTS §11).

One worker per installation is the only automatic writer for hook-captured
work. An exclusive OS lock (``.recalith/run/worker.lock``) admits one worker
per installation; independent installations each run their own. Nothing here
is global: every call receives its resolved installation.

**Lanes.** The deterministic lane runs in the main loop: it recovers
registered transcript tails with the parser each source names (an unknown
parser is an explicit gap), ingests ready spool segments, runs deterministic
jobs (``ingest``, ``maintenance``) and schedules housekeeping. It uses no
model budget. The model lane runs in its own thread with its own store
connection and at most one request in flight (``concurrent_requests = 1``),
so ingestion and typed state stay responsive while a provider call runs.

**Polling (preview).** After a poll that found work the next poll follows in
1 second (active); otherwise in 5 seconds (idle). There is no IPC endpoint and
no wake hint: session mode, ``fast/wake.py`` and the 2-second wake target
are full-release work and unavailable here. A wall-clock jump larger than the
elapsed monotonic time (suspend/resume) is recorded and handled as one jump:
recurring work is scheduled for the current slot only, overdue jobs run one at
a time inside the daily budget.

**Model jobs.** A job is leased only when due and its smallest reservation
fits; the exact reservation (request estimate + purpose allowance) is made in
a fenced transaction *before* the launch; the raw wire and the decoded body
are bounded separately; the proposal is persisted (fenced) before it is
applied; application and completion are one fenced transaction. A late or
superseded result therefore never applies, and recovery after a crash applies
a persisted proposal without another model call. Each evidence-expansion
round is another reserved, charged invocation. Provider execution is behind
the :class:`Backend` interface; production preview has no backend until
Task 7 certifies one, so model jobs wait visibly with ``provider_unavailable``.

**Process entry.** ``python -I -m recalith.controller.worker --project ROOT``
is the internal entry the hook's registered start path launches with a fresh
environment from ``spawn_environment``. It is not the guarded public
``recalith worker`` CLI and grants no operator actor. It refuses a caller
that still carries a host marker or a curator marker, or whose worker marker
does not name this installation.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from recalith.capture import pipeline
from recalith.contracts.common import Actor, InstallationContext, canonical_json, new_id, utc_now
from recalith.contracts.config import MODEL_INPUT_CAP, ProjectConfig, estimate_tokens
from recalith.contracts.jobs import MODEL_JOB_KINDS, Job, LocalUsage
from recalith.contracts.operations import ModelRequest, ModelResponse, ResponseProvenance, UsageReport
from recalith.controller import apply, budgets, jobs, launch
from recalith.errors import RecalithError
from recalith.fast import claude_capture, failpoints, process_env, session
from recalith.storage import spool
from recalith.storage.db import Store, Txn, open_store
from recalith.working import reducer as working_reducer

WORKER_ACTOR = Actor(kind="controller", id="worker", channel="worker")
STATUS_FILE = "worker.json"
STOP_FILE = "worker.stop"
STATUS_SCHEMA = 1
LOCK_RETRY_SECONDS = 1.0
WAIT_SLICE_SECONDS = 0.25
CLOCK_JUMP_SECONDS = 60.0
DETERMINISTIC_BATCH = 50
SOURCE_BATCH = 32
DETACHED_METHODS = frozenset({"posix_session", "windows_breakaway"})


# --------------------------------------------------------------------------
# Clock and backends


class Clock:
    """Wall time as canonical UTC, plus monotonic time and interruptible waits."""

    def now(self) -> str:
        return utc_now()

    def wall(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()

    def wait(self, seconds: float, event: threading.Event) -> bool:
        return event.wait(max(0.0, seconds))


@dataclass
class LaunchOutcome:
    stdout: bytes
    overflowed: bool = False
    timed_out: bool = False
    returncode: int | None = 0
    duration_ms: int = 0
    stderr: bytes = b""
    tree_bound: str = "contained"


class Backend(Protocol):
    """A certified provider route (Task 7). The worker only sees bounded bytes."""

    provider_id: str
    configured_model: str

    def launch(self, request: bytes, *, timeout_s: float, purpose: str) -> LaunchOutcome: ...

    def unwrap(self, stdout: bytes) -> tuple[bytes, dict[str, Any]]:
        """Validate the registered host envelope; return (decoded body bytes, usage)."""
        ...


class ProcessBackend:
    """Runs a configured argument array under :func:`launch.run_bounded`.

    The child environment is built fresh by ``spawn_environment(purpose=
    "curator")`` from the worker's own environment: only registered platform
    keys plus the route's named keys, host and worker markers removed, and the
    curator marker set. ``unwrap`` is the route's certified envelope parser.
    """

    def __init__(
        self,
        argv: Sequence[str],
        *,
        installation_id: str,
        unwrap: Callable[[bytes], tuple[bytes, dict[str, Any]]],
        cwd: Path,
        inherited: Mapping[str, str] | None = None,
        route_keys: Sequence[str] = (),
        overrides: Mapping[str, str] | None = None,
        provider_id: str = "process",
        configured_model: str = "unconfigured",
    ) -> None:
        self.argv = list(argv)
        self.installation_id = installation_id
        self._unwrap = unwrap
        self.cwd = cwd
        self.inherited = inherited
        self.route_keys = list(route_keys)
        self.overrides = dict(overrides or {})
        self.provider_id = provider_id
        self.configured_model = configured_model
        self.last_environment_report: dict[str, Any] | None = None

    def launch(self, request: bytes, *, timeout_s: float, purpose: str) -> LaunchOutcome:
        manifest = process_env.role_manifest(self.installation_id, purpose="curator", route_keys=self.route_keys, overrides=self.overrides)
        env, report = process_env.spawn_environment_report(manifest, os.environ if self.inherited is None else self.inherited, purpose="curator")
        self.last_environment_report = report
        result = launch.run_bounded(self.argv, env=env, cwd=self.cwd, stdin_data=request, timeout_s=timeout_s)
        return LaunchOutcome(
            stdout=result.stdout,
            overflowed=result.stdout_overflow,
            timed_out=result.timed_out,
            returncode=result.returncode,
            duration_ms=result.duration_ms,
            stderr=result.stderr,
            tree_bound=result.tree_bound,
        )

    def unwrap(self, stdout: bytes) -> tuple[bytes, dict[str, Any]]:
        return self._unwrap(stdout)


@dataclass
class ModelRuntime:
    """Everything the model lane needs; Tasks 6–9 supply the real request preparers.

    Application is not pluggable: every persisted proposal goes through
    ``controller.apply.apply_proposal`` (Task 5).
    """

    backend: Backend
    prepare: Callable[[Store, Job, list[ModelResponse]], ModelRequest]
    adapter_version: str = "1"


# --------------------------------------------------------------------------
# Deterministic handlers


def handle_ingest(txn: Txn, job: Job, worker: "Worker") -> None:
    """Typed follow-on processing of newly ingested events (no model budget).

    Task 4 confirms the events are committed; typed task reduction (Task 6,
    ``working.reducer.reduce_ingested``) is registered by default and runs in
    this fenced transaction; failure triggers (Task 9/10) register as further
    reducers here.
    """
    for ref in job.input_refs:
        if txn.one("SELECT 1 FROM events WHERE event_id = ?", (ref.id,)) is None:
            raise RecalithError("revision_conflict", "an ingest job names an event that is not committed")
    for reducer in worker.ingest_reducers:
        reducer(txn, job, worker)


def handle_housekeeping(txn: Txn, job: Job, worker: "Worker") -> None:
    session.prune_abandoned(worker.ctx.root)
    spool.cleanup_stale_temps(spool.SpoolDirs(worker.ctx.root))


DEFAULT_HANDLERS: dict[str, Callable[[Txn, Job, "Worker"], None]] = {"ingest": handle_ingest, "maintenance": handle_housekeeping}


def _claude_parser(name: str) -> Callable[[InstallationContext], Any]:
    version = name.split("@", 1)[1]
    return lambda ctx: claude_capture.transcript_line_parser(ctx.installation_id, host_version=version)


# Parser registry: the name a source registration carries → its line parser.
PARSERS: dict[str, Callable[[InstallationContext], Any]] = {claude_capture.TRANSCRIPT_PARSER: _claude_parser(claude_capture.TRANSCRIPT_PARSER)}


@dataclass
class SpawnInfo:
    spawned_by: str = "direct"  # hook | direct
    method: str = "none"  # posix_session | windows_breakaway | windows_no_breakaway | none
    in_job: bool | None = None  # Windows: observed by the worker itself (IsProcessInJob)

    def independence(self) -> dict[str, Any]:
        """What the worker can honestly claim about outliving its host.

        A Windows breakaway flag is not evidence: a venv launcher between host
        and hook runs the hook in a nested job, so breakaway can leave the
        worker inside the host's job. Detachment is claimed on Windows only
        when the worker observes itself in no Job Object at all.
        """
        degraded: list[str] = []
        if self.method == "windows_no_breakaway":
            degraded.append("job_breakaway_denied")
        elif self.method == "windows_breakaway" and self.in_job is not False:
            degraded.append("job_membership_unverified")
        if self.method in DETACHED_METHODS and not degraded:
            state = "detached"
        elif degraded:
            state = "degraded"
        else:
            state = "not_detached"
        return {"spawned_by": self.spawned_by, "method": self.method, "state": state, "degraded_reasons": degraded, "in_job": self.in_job}


def windows_in_job() -> bool | None:  # pragma: no cover - native Windows
    """Whether this process is in any Job Object (None when it cannot be observed)."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        result = wintypes.BOOL()
        if not k32.IsProcessInJob(k32.GetCurrentProcess(), None, ctypes.byref(result)):
            return None
        return bool(result.value)
    except (OSError, AttributeError):
        return None


# --------------------------------------------------------------------------
# The worker


class Worker:
    def __init__(
        self,
        ctx: InstallationContext,
        *,
        config: ProjectConfig | None = None,
        clock: Clock | None = None,
        model: ModelRuntime | None = None,
        parsers: Mapping[str, Callable[[InstallationContext], Any]] | None = None,
        handlers: Mapping[str, Callable[[Txn, Job, "Worker"], None]] | None = None,
        owner: str | None = None,
        spawn: SpawnInfo | None = None,
        environment: Mapping[str, str] | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.ctx = ctx
        self.config = config or _project_config(ctx)
        if self.config.project_id != ctx.project_id:
            raise RecalithError("foreign_installation", "worker configuration names another project")
        self.clock = clock or Clock()
        self.model = model
        self.parsers = dict(PARSERS if parsers is None else parsers)
        self.handlers = dict(DEFAULT_HANDLERS if handlers is None else handlers)
        self.ingest_reducers: list[Callable[[Txn, Job, Worker], None]] = [working_reducer.reduce_ingested]
        self.owner = owner or f"worker:{os.getpid()}:{new_id('act')[4:12]}"
        self.spawn = spawn or SpawnInfo()
        self.environment = os.environ if environment is None else environment
        self.stop_event = stop_event or threading.Event()
        self.run_dir = Path(process_env.run_dir(ctx.root))
        self.dirs = spool.SpoolDirs(ctx.root)
        self._store: Store | None = None
        self._seen_sources: dict[str, tuple] = {}
        self._reported_gaps: set[tuple[str, str]] = set()
        self.counters: dict[str, int] = {"polls": 0, "active_polls": 0, "segments": 0, "deterministic_jobs": 0, "model_launches": 0, "fenced_results": 0, "clock_jumps": 0, "errors": 0}
        self.lane = ModelLane(self) if model is not None else None
        self.state = "starting"
        self.last_error: str | None = None
        self.started_at = self.clock.now()
        self._last_poll_wall: float | None = None
        self._last_poll_mono: float | None = None
        self._last_poll_at: str | None = None
        self._last_poll_worked = False
        self._interval = float(self.config.worker.active_poll_seconds)
        self.max_clock_jump = 0.0

    # ---------------------------------------------------------------- store

    @property
    def store(self) -> Store:
        if self._store is None:
            self._store = open_store(self.ctx)
        return self._store

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None
        if self.lane is not None:
            self.lane.close()

    # ---------------------------------------------------------------- one poll

    def tick(self) -> bool:
        """One deterministic poll; True when it found work (the next poll is active)."""
        worked = False
        now = self.clock.now()
        try:
            worked |= self._recover_sources()
            ready = len(spool.ready_segments(self.dirs))
            if ready:
                result = pipeline.ingest_ready(self.ctx)
                self.counters["segments"] += ready
                worked = worked or ready > 0 or bool(result.created_job_ids)
            with self.store.transaction() as txn:
                jobs.schedule_housekeeping(txn, now=now)
            worked |= self._run_deterministic()
            worked |= bool(working_reducer.pause_idle_tasks(self.store, self.ctx, self.config, now=now))
            if self.lane is None:
                jobs.mark_provider_unavailable(self.store)
            self.last_error = None
        except RecalithError as exc:
            self.counters["errors"] += 1
            self.last_error = exc.code
        except (OSError, ValueError, sqlite3.Error) as exc:  # a poll never kills the worker; the next poll retries
            self.counters["errors"] += 1
            self.last_error = f"poll_error:{type(exc).__name__}"[:64]
        return worked

    def _gap_once(self, code: str, reason: str, source_id: str) -> None:
        if (code, source_id) in self._reported_gaps:
            return
        self._reported_gaps.add((code, source_id))
        spool.record_gap(self.dirs, code=code, reason=reason, event_count=0, at=self.clock.now(), source_ids=[source_id])

    def _recover_sources(self) -> bool:
        worked = False
        with self.store.read() as view:
            rows = view.execute("SELECT source_id, locator, coverage FROM capture_sources ORDER BY registered_at, source_id").fetchall()
        recovered = 0
        for source_id, locator, coverage in rows:
            if recovered >= SOURCE_BATCH:
                break
            parser_name = (json.loads(coverage or "{}") or {}).get("parser")
            factory = self.parsers.get(parser_name) if parser_name else None
            if factory is None:
                self._gap_once("source_parser_unavailable", str(parser_name or "unregistered")[:64], source_id)
                continue
            try:
                st = os.stat(locator)
            except FileNotFoundError:
                continue  # the host may not have created the transcript yet
            except OSError:
                self._gap_once("source_unreadable", "stat_failed", source_id)
                continue
            signature = (st.st_size, st.st_mtime_ns, st.st_ino)
            if self._seen_sources.get(source_id) == signature:
                continue
            try:
                receipt, _tail = pipeline.recover_source(self.ctx, source_id, factory(self.ctx))
            except RecalithError as exc:
                self._gap_once("source_unreadable", exc.code, source_id)
                continue
            recovered += 1
            if receipt is not None and receipt.status != "accepted":
                continue  # not acknowledged: retry on the next poll from the same cursor
            self._seen_sources[source_id] = signature
            worked = worked or receipt is not None
        return worked

    def _run_deterministic(self) -> bool:
        worked = False
        kinds = tuple(k for k in self.handlers if k not in MODEL_JOB_KINDS)
        for _ in range(DETERMINISTIC_BATCH):
            job = jobs.lease_next(self.ctx, owner=self.owner, now=self.clock.now(), kinds=kinds, store=self.store, config=self.config.budgets)
            if job is None:
                break
            worked = True
            self.run_job(job)
        return worked

    def run_job(self, job: Job) -> None:
        handler = self.handlers[job.kind]
        try:
            with jobs.fenced(self.store, job, now=self.clock.now()) as txn:
                handler(txn, job, self)
                jobs.complete(txn, job)
                failpoints.hit(failpoints.JOB_BEFORE_COMPLETE_COMMIT)
            failpoints.hit(failpoints.JOB_AFTER_COMPLETE)
            self.counters["deterministic_jobs"] += 1
        except RecalithError as exc:
            if exc.code == "revision_conflict" and "lease fenced" in exc.message:
                self.counters["fenced_results"] += 1
                return
            self._fail(job, exc.code)
        except Exception:  # noqa: BLE001 - a handler bug fails its job, not the worker
            self._fail(job, "handler_error")

    def _fail(self, job: Job, code: str) -> None:
        try:
            with jobs.fenced(self.store, job, now=self.clock.now()) as txn:
                jobs.fail(txn, job, code, now=self.clock.now(), backoff=self.config.budgets.retry_backoff_seconds)
        except RecalithError:
            self.counters["fenced_results"] += 1

    # ---------------------------------------------------------------- status

    def status(self) -> dict[str, Any]:
        now = self.clock.now()
        try:
            with self.store.read() as view:
                queue = jobs.queue_summary(view, now=now)
                budget = budgets.summary(view, budgets.utc_day(now), self.config.budgets)
        except RecalithError as exc:
            queue, budget = {"error": exc.code}, {"error": exc.code}
        env = self.environment
        markers = [k for k in process_env.HOST_MARKERS if k in env]
        waiting = queue.get("by_state", {}).get("waiting_budget", 0) if isinstance(queue.get("by_state"), dict) else 0
        state = self.state
        if state in ("running", "idle") and waiting and self.lane is not None:
            state = "budget_paused"
        if state in ("running", "idle") and self.last_error:
            state = "degraded"
        return {
            "status_schema": STATUS_SCHEMA,
            "installation_id": self.ctx.installation_id,
            "pid": os.getpid(),
            "owner": self.owner,
            "state": state,
            "mode": "persistent",
            "started_at": self.started_at,
            "heartbeat_at": now,
            "poll": {
                "active_seconds": self.config.worker.active_poll_seconds,
                "idle_seconds": self.config.worker.idle_poll_seconds,
                "interval_seconds": self._interval,
                "last_poll_at": self._last_poll_at,
                "last_poll_wall": self._last_poll_wall,
                "last_poll_worked": self._last_poll_worked,
                "ipc_wake": "unavailable_in_preview",
            },
            "spawn": self.spawn.independence(),
            "environment": {
                "role_marker": env.get(process_env.WORKER_MARKER),
                "key_names": sorted(env),
                "host_markers_present": markers,
                "curator_marker_present": process_env.CURATOR_MARKER in env,
            },
            "model_lane": "running" if self.lane is not None else "provider_unavailable",
            "counters": dict(self.counters),
            "max_clock_jump_seconds": round(self.max_clock_jump, 3),
            "last_error": self.last_error,
            "queue": queue,
            "budget": budget,
        }

    def write_status(self, extra: Mapping[str, Any] | None = None) -> None:
        data = self.status()
        if extra:
            data.update(extra)
        path = self.run_dir / STATUS_FILE
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(data, sort_keys=True))
            for attempt in range(5):
                try:
                    os.replace(tmp, path)
                    break
                except PermissionError:  # Windows: a reader has the file open for a moment
                    if attempt == 4:
                        raise
                    time.sleep(0.01)
        except OSError:
            self.last_error = "status_write_failed"

    # ---------------------------------------------------------------- loop

    def stop_requested(self) -> bool:
        if self.stop_event.is_set():
            return True
        path = self.run_dir / STOP_FILE
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
            self.stop_event.set()
            return True
        return False

    def _note_clock(self) -> None:
        wall, mono = self.clock.wall(), self.clock.monotonic()
        if self._last_poll_wall is not None and self._last_poll_mono is not None:
            jump = (wall - self._last_poll_wall) - (mono - self._last_poll_mono)
            if abs(jump) > CLOCK_JUMP_SECONDS:
                self.counters["clock_jumps"] += 1
                self.max_clock_jump = max(self.max_clock_jump, abs(jump))
        self._last_poll_wall, self._last_poll_mono = wall, mono

    def poll_once(self) -> bool:
        self._note_clock()
        worked = self.tick()
        self.counters["polls"] += 1
        if worked:
            self.counters["active_polls"] += 1
        busy = self.lane is not None and self.lane.busy
        self._last_poll_worked = worked
        self._last_poll_at = self.clock.now()
        self._interval = float(self.config.worker.active_poll_seconds if (worked or busy) else self.config.worker.idle_poll_seconds)
        self.state = "running" if (worked or busy) else "idle"
        return worked

    def _sleep(self, seconds: float) -> None:
        give_up = self.clock.monotonic() + seconds
        while not self.stop_requested():
            remaining = give_up - self.clock.monotonic()
            if remaining <= 0:
                return
            self.clock.wait(min(WAIT_SLICE_SECONDS, remaining), self.stop_event)

    def startup(self) -> None:
        """Recovery while holding the lock: dead workers' leases end, their calls stay charged."""
        jobs.recover_abandoned_leases(self.store, owner=self.owner, now=self.clock.now())
        with self.store.transaction() as txn:
            budgets.charge_interrupted(txn)

    def run(self) -> int:
        lock = process_env.InstallationLock(self.ctx.root)
        give_up = time.monotonic() + LOCK_RETRY_SECONDS
        while not lock.try_acquire():
            if time.monotonic() >= give_up:
                return 0  # another worker owns this installation; one worker per installation
            time.sleep(0.02)
        try:
            self.startup()
            self.state = "running"
            self.write_status()
            if self.lane is not None:
                self.lane.start()
            while not self.stop_requested():
                self.poll_once()
                self.write_status()
                self._sleep(self._interval)
            self.state = "stopping"
            self.write_status()
            if self.lane is not None:
                self.lane.stop(timeout=self.config.budgets.timeout_seconds + 10)
            self.state = "stopped"
            self.write_status()
            return 0
        finally:
            self.close()
            lock.release()


# --------------------------------------------------------------------------
# The model lane


class ModelLane:
    """One model request at a time, in its own thread and store connection."""

    def __init__(self, worker: Worker) -> None:
        self.worker = worker
        self.runtime: ModelRuntime = worker.model  # type: ignore[assignment]
        self.config = worker.config.budgets
        self.owner = worker.owner + ":model"
        self._store: Store | None = None
        self._thread: threading.Thread | None = None
        self.busy = False

    @property
    def store(self) -> Store:
        if self._store is None:
            self._store = open_store(self.worker.ctx)
        return self._store

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None

    def now(self) -> str:
        return self.worker.clock.now()

    # ---------------------------------------------------------------- thread

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="recalith-model-lane", daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float) -> None:
        if self._thread is not None:
            self._thread.join(timeout)  # a healthy in-flight call is not killed to stop

    def _loop(self) -> None:
        worker = self.worker
        try:
            while not worker.stop_event.is_set():
                try:
                    launched = self.step()
                except Exception as exc:  # noqa: BLE001 - the lane survives; the job was failed in step()
                    worker.counters["errors"] += 1
                    worker.last_error = (exc.code if isinstance(exc, RecalithError) else f"lane_error:{type(exc).__name__}")[:64]
                    launched = False
                interval = worker.config.worker.active_poll_seconds if launched else worker.config.worker.idle_poll_seconds
                worker.clock.wait(interval, worker.stop_event)
        finally:
            self.close()

    # ---------------------------------------------------------------- one opportunity

    def step(self) -> bool:
        """One model scheduling opportunity; True when a job was leased."""
        job = jobs.lease_next(self.worker.ctx, owner=self.owner, now=self.now(), kinds=MODEL_JOB_KINDS, store=self.store, config=self.config)
        if job is None:
            return False
        self.busy = True
        try:
            if job.proposal_ref is not None:
                with self.store.read() as view:  # recovery: the persisted proposal, no new model call
                    response = apply.load_proposal(view, job.proposal_ref)[0]
            else:
                response = self._call(job)
                if response is None:
                    return True
            self._apply(job, response)
        except RecalithError as exc:
            if exc.code == "revision_conflict" and "lease fenced" in exc.message:
                self.worker.counters["fenced_results"] += 1
                return True
            self._fail_quietly(job, exc.code)
            raise
        except Exception as exc:
            self._fail_quietly(job, f"lane_error:{type(exc).__name__}")
            raise
        finally:
            self.busy = False
        return True

    def _fail_quietly(self, job: Job, code: str) -> None:
        try:
            self._fail(job, code[:64])
        except RecalithError:
            pass  # already fenced or the store is unavailable: the lease simply expires

    def _fail(self, job: Job, code: str, *, final: bool = False) -> None:
        with jobs.fenced(self.store, job, now=self.now()) as txn:
            jobs.fail(txn, job, code, now=self.now(), backoff=() if final else self.config.retry_backoff_seconds)

    def _call(self, job: Job) -> ModelResponse | None:
        rounds: list[ModelResponse] = []
        while True:
            try:
                request = self.runtime.prepare(self.store, job, list(rounds))
            except RecalithError as exc:
                self._fail(job, exc.code)
                return None
            except (ValueError, TypeError):
                self._fail(job, "request_invalid", final=True)  # e.g. a ModelRequest over its input cap
                return None
            raw = canonical_json(request.model_dump(mode="json"))
            if len(raw) > MODEL_INPUT_CAP:
                self._fail(job, "model_input_oversized", final=True)
                return None
            estimate = estimate_tokens(len(raw))
            with jobs.fenced(self.store, job, now=self.now()) as txn:
                reservation = budgets.reserve(txn, job_id=job.job_id, purpose=job.kind, input_estimate=estimate, now=self.now(), config=self.config)
                if isinstance(reservation, budgets.Refusal):
                    jobs.wait_budget(txn, job, reservation.reason)
                    return None
                jobs.count_attempt(txn, job)
            failpoints.hit(failpoints.JOB_AFTER_RESERVE)
            self.worker.counters["model_launches"] += 1
            try:
                outcome = self.runtime.backend.launch(raw, timeout_s=self.config.timeout_seconds, purpose=job.kind)
            except Exception:
                with self.store.transaction() as txn:  # launched with unknown usage: the reservation stays charged
                    budgets.charge(txn, reservation.reservation_id, reported=None, local=None)
                raise
            code, response = self._evaluate(outcome, reservation, estimate)
            if code is not None:
                self._fail(job, code)
                return None
            assert response is not None
            if any(op.kind == "request_evidence" for op in response.operations):
                if len(rounds) >= self.config.evidence_expansion_rounds:
                    self._fail(job, "expansion_limit", final=True)
                    return None
                rounds.append(response)  # each expansion round is another reserved invocation
                continue
            self._persist(job, request, response)
            return response

    def _evaluate(self, outcome: LaunchOutcome, reservation, estimate: int) -> tuple[str | None, ModelResponse | None]:
        backend = self.runtime.backend
        reported: UsageReport | None = None
        local: LocalUsage | None = None
        code: str | None = None
        response: ModelResponse | None = None
        if outcome.timed_out:
            code = "provider_timeout"
        elif outcome.overflowed:
            code = "wire_stdout_oversized"
        elif outcome.returncode != 0:
            code = "provider_failed"
        else:
            try:
                budgets.check_wire(outcome.stdout, overflowed=False)
                body, usage = backend.unwrap(outcome.stdout)
            except budgets.OutputRejected as exc:
                code = exc.code
            except (ValueError, TypeError, KeyError):
                code = "envelope_invalid"
            else:
                local = LocalUsage(input_estimate=estimate, output_estimate=estimate_tokens(len(body)))
                reported = UsageReport(
                    input_tokens=_count(usage.get("input_tokens")),
                    output_tokens=_count(usage.get("output_tokens")),
                    estimated_input_tokens=estimate,
                    estimated_output_tokens=local.output_estimate,
                    provider_request_id=usage.get("provider_request_id") if isinstance(usage.get("provider_request_id"), str) else None,
                    duration_ms=max(0, int(outcome.duration_ms)),
                )
                try:
                    operations, no_op_reason, malformed = budgets.decode_body(body, reservation)
                except budgets.OutputRejected as exc:
                    code = exc.code
                else:
                    provenance = ResponseProvenance(provider_id=backend.provider_id[:64], configured_model=backend.configured_model[:128], resolved_model=None, adapter_version=self.runtime.adapter_version)
                    response = ModelResponse(response_schema=1, operations=operations, no_op_reason=no_op_reason, usage=reported, provenance=provenance, malformed=malformed)
        with self.store.transaction() as txn:  # charged whatever happened, fenced or not
            budgets.charge(txn, reservation.reservation_id, reported=reported, local=local, provider_id=backend.provider_id[:64], model=backend.configured_model[:128])
        return code, response

    def _persist(self, job: Job, request: ModelRequest, response: ModelResponse) -> None:
        apply.persist_proposal(self.store, job, response, request.read_set, now=self.now())

    def _apply(self, job: Job, response: ModelResponse) -> None:
        """Apply the persisted proposal and complete the job in one fenced transaction."""
        try:
            apply.apply_proposal(self.worker.ctx, job, response, store=self.store, now=self.now())
        except RecalithError as exc:
            if exc.code == "revision_conflict" and "lease fenced" in exc.message:
                raise
            self._fail(job, exc.code)


def _project_config(ctx: InstallationContext) -> ProjectConfig:
    from recalith.core.identity import Layout, load_project_config

    return load_project_config(Layout(Path(ctx.root)))


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


# --------------------------------------------------------------------------
# Public entry points


def run_worker(ctx: InstallationContext, *, mode: str, **options: Any) -> int:
    """Run the installation's worker until stopped (DATA_CONTRACTS §11).

    ``mode`` is ``persistent``. ``session`` mode is a full-release capability
    and is refused as unavailable in this build. Returns 0 on a clean stop or
    when another worker already owns the installation.
    """
    if mode == "session":
        raise RecalithError("capability_unavailable", "session worker mode is a full-release capability; this build runs persistent workers only")
    if mode != "persistent":
        raise RecalithError("invalid_schema", "worker mode is persistent or session")
    return Worker(ctx, **options).run()


def request_stop(root: Path | str) -> None:
    """Ask the installation's running worker to stop at its next wait slice."""
    path = Path(process_env.run_dir(root)) / STOP_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"requested_at": utc_now()}), encoding="utf-8")


def read_status(root: Path | str) -> dict[str, Any] | None:
    try:
        return json.loads((Path(process_env.run_dir(root)) / STATUS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _parse(argv: Sequence[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    i = 0
    while i < len(argv):
        if argv[i] in ("--project", "--spawned-by", "--spawn-method") and i + 1 < len(argv):
            out[argv[i][2:]] = argv[i + 1]
            i += 2
        else:
            raise RecalithError("invalid_schema", "unknown worker argument")
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """Internal entry for the registered start path; refuses marked or foreign callers."""
    from recalith.core.identity import resolve_installation

    try:
        args = _parse(list(sys.argv[1:] if argv is None else argv))
        if "project" not in args:
            raise RecalithError("invalid_schema", "--project is required")
        env = os.environ
        if any(marker in env for marker in process_env.HOST_MARKERS) or process_env.CURATOR_MARKER in env:
            raise RecalithError("policy_refused", "the internal worker entry runs only in the fresh environment of the registered start path")
        ctx = resolve_installation(Path(args["project"]), actor=WORKER_ACTOR)
        if env.get(process_env.WORKER_MARKER) != ctx.installation_id:
            raise RecalithError("policy_refused", "the worker role marker does not name this installation")
        spawn = SpawnInfo(spawned_by=args.get("spawned-by", "direct"), method=args.get("spawn-method", "none"), in_job=windows_in_job())
        stop = threading.Event()
        if os.name != "nt":
            import signal

            signal.signal(signal.SIGTERM, lambda *_: stop.set())
        return run_worker(ctx, mode="persistent", spawn=spawn, stop_event=stop)
    except RecalithError as exc:
        print(f"recalith-worker: {exc.code}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
