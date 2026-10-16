"""Test-only worker fixtures: fake clock, fake provider backends and the crash driver.

The fake backends stand in for a certified provider route (Task 7); they are
never certification subjects. The in-process :class:`FakeBackend` answers
from a scripted behavior; :func:`process_backend` runs the real bounded
launcher against ``tests/fixtures/providers/fake_backend.py``.

Run as a script, this module is the kill/restart driver (ACCEPTANCE_TESTS
§4): it resolves the installation in a fresh process, optionally arms one
worker failpoint to kill the process, and drains the queue with real worker
polls and model-lane steps.

    python worker_scenarios.py ROOT CALLS_LOG [FAILPOINT SKIP]
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
import threading
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
for extra in (HERE.parents[1] / "src", HERE.parent, HERE.parent / "platform"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import factories as f  # noqa: E402
from recalith.contracts.common import Actor, RecordRef, ReadSet, canonical_json, digest_of, format_utc, new_id, parse_utc  # noqa: E402
from recalith.contracts.config import ProjectConfig  # noqa: E402
from recalith.contracts.memory import ReviewBatch  # noqa: E402
from recalith.contracts.operations import ModelRequest, RequestLimits  # noqa: E402
from recalith.controller import jobs, worker  # noqa: E402
from recalith.core import identity  # noqa: E402
from recalith.fast import process_env  # noqa: E402
from recalith.storage import db, failpoints  # noqa: E402

PROJECT_ID = "proj_55555555-5555-4555-8555-555555555555"
ACTOR = Actor(kind="controller", id="test-worker", channel="worker")
FAKE_BACKEND = HERE.parent / "fixtures" / "providers" / "fake_backend.py"
START = "2026-10-16T08:00:00.000000Z"


# --------------------------------------------------------------------------
# Installations and clock


def init_project(parent: Path, name: str) -> Path:
    root = parent / name
    root.mkdir(parents=True)
    identity.initialize_installation(root, ProjectConfig.defaults_for(PROJECT_ID))
    return root


def context(root: Path):
    return identity.resolve_installation(root, actor=ACTOR)


class FakeClock(worker.Clock):
    """Deterministic wall clock; monotonic time advances with it unless a jump is simulated."""

    def __init__(self, start: str = START) -> None:
        self.moment = parse_utc(start)
        self.mono = 1000.0
        self.lock = threading.Lock()

    def now(self) -> str:
        with self.lock:
            return format_utc(self.moment)

    def wall(self) -> float:
        with self.lock:
            return self.moment.timestamp()

    def monotonic(self) -> float:
        with self.lock:
            return self.mono

    def advance(self, seconds: float, *, jump: bool = False) -> None:
        """Advance wall time; ``jump`` leaves monotonic time behind (suspend/resume)."""
        with self.lock:
            self.moment += _dt.timedelta(seconds=seconds)
            if not jump:
                self.mono += seconds

    def wait(self, seconds: float, event: threading.Event) -> bool:
        self.advance(seconds)
        return event.wait(0.001)


# --------------------------------------------------------------------------
# Jobs, requests and proposals


def enqueue_model_job(root: Path, kind: str, *, now: str = START, key: str | None = None, candidates: list[jobs.ReviewCandidate] | None = None, coalesce: bool = False, revision: int = 1) -> str:
    ctx = context(root)
    refs = [RecordRef(kind="claim", id=f"claim_{digest_of(key or new_id('job'))}", revision=revision)]
    if kind == "review_claims" and candidates is None:
        candidates = [jobs.ReviewCandidate(claim_id=refs[0].id, origin="extracted", claim_kind="fact")]
    with db.open_store(ctx) as store, store.transaction() as txn:
        job_id, _ = jobs.enqueue(txn, kind=kind, input_refs=refs, now=now, prompt_version="test@1", review_candidates=candidates or (), coalesce=coalesce)
    return job_id


def request_for(store, job, rounds, *, pad: int = 0) -> ModelRequest:
    """A minimal valid ModelRequest for the job's purpose, optionally padded to a size."""
    from recalith.contracts.config import PURPOSE_OUTPUT_ALLOWANCE, body_cap_for

    read_set = ReadSet(workspace_id=store.ctx.workspace_id, policy_revision=1, tombstone_epoch=0)
    batch = None
    if job.kind == "review_claims":
        ref = job.input_refs[0]
        batch = ReviewBatch(batch_id=f"batch_{ref.id[6:]}", origin_job_id=None, review_job_id=job.job_id, candidate_refs=[ref], candidate_digests={ref.id: f.sha(ref.id)}, evidence_digest=f.sha("e"), prompt_digest=f.sha("p"), read_set=read_set)
    out = PURPOSE_OUTPUT_ALLOWANCE[job.kind]
    limits = RequestLimits(max_input_bytes=96 * 1024, reserved_output_estimate=out, max_body_bytes=body_cap_for(job.kind), max_wire_stdout_bytes=262144, max_stderr_bytes=65536, timeout_seconds=120)
    text = f"job {job.job_id} round {len(rounds)}" + " " * pad
    return ModelRequest(request_schema=1, job_id=job.job_id, purpose=job.kind, prompt_version="test@1", instruction_text=text, read_set=read_set, output_schema={"type": "object"}, review_batch=batch, limits=limits)


def sized_preparer(target_bytes: int) -> Callable:
    """Pad requests so their canonical serialization is exactly ``target_bytes``."""

    def prepare(store, job, rounds):
        base = request_for(store, job, rounds)
        size = len(canonical_json(base.model_dump(mode="json")))
        return request_for(store, job, rounds, pad=max(0, target_bytes - size))

    return prepare


def applier(txn, job, response) -> None:
    """Record exactly one effect per application (an ``operations`` row)."""
    txn.execute(
        "INSERT INTO operations (operation_id, job_id, actor, kind, inputs, changed, reason, store_revision, created_at) VALUES (?, ?, ?, 'test_apply', ?, '[]', NULL, ?, ?)",
        (new_id("op"), job.job_id, canonical_json(ACTOR).decode(), json.dumps({"ops": len(response.operations)}), txn.next_store_revision, START),
    )
    txn.mutated(serving_relevant=True)


NO_OP_BODY = json.dumps({"operations": [], "no_op_reason": "nothing new"}).encode()


def evidence_request_body() -> bytes:
    op = f.operation("request_evidence", {"request_kind": "record", "ref": f.ref("event", f.event_id("tool_finished-1"))})
    return json.dumps({"operations": [op]}).encode()


def episode_body(size: int = 15_000, *, filler: str = "x") -> bytes:
    """A valid build_episode body of about ``size`` UTF-8 bytes (step texts stay under 8,192 characters)."""
    count = max(2, -(-size // 6000))
    per_step = max(100, (size - 1200) // count - 260)
    unit = len(filler.encode("utf-8"))
    steps = [{"ordinal": i, "action": f.supported(filler * (per_step // unit)), "outcome": "failure" if i % 2 == 0 else "success"} for i in range(count)]
    episode = {
        "task_id": new_id("task"),
        "title": "Fix import path",
        "started_at": f.TIME,
        "objective": f.supported("Make the test suite import the package."),
        "steps": steps,
        "outcome": f.supported("Tests pass."),
        "source_event_ids": [f.event_id("tool_finished-1")],
    }
    return json.dumps({"operations": [f.operation("create_episode", episode)]}, ensure_ascii=False).encode("utf-8")


def envelope(body: bytes, *, usage: dict[str, Any] | None = None, padding: int = 0) -> bytes:
    """A host-style JSON envelope: the body travels JSON-escaped beside usage/session metadata."""
    return json.dumps({"type": "result", "result": body.decode("utf-8"), "usage": usage or {}, "session_id": "fake-session", "padding": "m" * padding}).encode()


def unwrap(stdout: bytes) -> tuple[bytes, dict[str, Any]]:
    data = json.loads(stdout.decode("utf-8"))
    if not isinstance(data, dict) or data.get("type") != "result" or not isinstance(data.get("result"), str):
        raise ValueError("not a result envelope")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return data["result"].encode("utf-8"), usage


class FakeBackend:
    """In-process scripted backend. ``script(purpose, call_index) -> LaunchOutcome``."""

    provider_id = "fake"
    configured_model = "fake-model"

    def __init__(self, script: Callable[[str, int], worker.LaunchOutcome] | None = None, *, on_launch: Callable[[bytes, str], None] | None = None, gate: threading.Event | None = None, log: Path | None = None) -> None:
        self.script = script or (lambda purpose, i: worker.LaunchOutcome(stdout=envelope(NO_OP_BODY, usage={"input_tokens": 50, "output_tokens": 10})))
        self.on_launch = on_launch
        self.gate = gate
        self.calls: list[tuple[str, str]] = []
        self.log = log
        self.in_flight = threading.Event()

    def launch(self, request: bytes, *, timeout_s: float, purpose: str) -> worker.LaunchOutcome:
        job_id = json.loads(request)["job_id"]
        self.calls.append((purpose, job_id))
        if self.log is not None:
            with open(self.log, "a", encoding="utf-8") as fh:
                fh.write(job_id + "\n")
        if self.on_launch is not None:
            self.on_launch(request, purpose)
        self.in_flight.set()
        try:
            if self.gate is not None:
                assert self.gate.wait(30), "test gate never opened"
            return self.script(purpose, len(self.calls) - 1)
        finally:
            self.in_flight.clear()

    def unwrap(self, stdout: bytes):
        return unwrap(stdout)


def runtime(backend, prepare=None) -> worker.ModelRuntime:
    return worker.ModelRuntime(backend=backend, prepare=prepare or (lambda store, job, rounds: request_for(store, job, rounds)), apply=applier)


def process_backend(root: Path, mode: str, *args: str, inherited=None, route_keys=()) -> worker.ProcessBackend:
    ctx = context(root)
    return worker.ProcessBackend([sys.executable, "-I", str(FAKE_BACKEND), mode, *args], installation_id=ctx.installation_id, unwrap=unwrap, cwd=root, inherited=inherited, route_keys=route_keys, provider_id="fake_process", configured_model="fake-model")


def drain(w: worker.Worker, *, polls: int = 50) -> None:
    """Run polls and model steps until nothing remains to do."""
    for _ in range(polls):
        worked = w.poll_once()
        launched = w.lane.step() if w.lane is not None else False
        if not worked and not launched:
            return
    raise AssertionError("queue did not drain")


def state(root: Path) -> dict[str, Any]:
    ctx = context(root)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        rows = view.execute("SELECT job_id, kind, state FROM jobs WHERE kind != 'maintenance' ORDER BY job_id").fetchall()
        effects = view.execute("SELECT job_id, COUNT(*) FROM operations WHERE kind = 'test_apply' GROUP BY job_id").fetchall()
        usage = view.execute("SELECT job_id, state FROM provider_usage ORDER BY rowid").fetchall()
        proposals = view.execute("SELECT job_id, COUNT(*) FROM proposals GROUP BY job_id").fetchall()
    return {"jobs": rows, "effects": dict(effects), "usage": usage, "proposals": dict(proposals)}


# --------------------------------------------------------------------------
# Crash driver


def main(argv: list[str]) -> int:
    root, calls_log = Path(argv[1]), Path(argv[2])
    if len(argv) > 3:
        failpoints.arm(argv[3], failpoints.kill, skip=int(argv[4]))
    ctx = context(root)
    backend = FakeBackend(log=calls_log)
    w = worker.Worker(ctx, model=runtime(backend), owner=f"driver:{new_id('act')[4:12]}")
    lock = process_env.InstallationLock(root)
    assert lock.try_acquire(), "another worker holds the installation"
    try:
        w.startup()
        drain(w)
    finally:
        w.close()
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
