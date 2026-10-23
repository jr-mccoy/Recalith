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


def read_set(ctx) -> ReadSet:
    return ReadSet(workspace_id=ctx.workspace_id, policy_revision=1, tombstone_epoch=0)


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
    return worker.ModelRuntime(backend=backend, prepare=prepare or (lambda store, job, rounds: request_for(store, job, rounds)))


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
        effects = view.execute("SELECT job_id, COUNT(*) FROM operations WHERE kind = 'apply_proposal' GROUP BY job_id").fetchall()
        usage = view.execute("SELECT job_id, state FROM provider_usage ORDER BY rowid").fetchall()
        proposals = view.execute("SELECT job_id, COUNT(*) FROM proposals GROUP BY job_id").fetchall()
    return {"jobs": rows, "effects": dict(effects), "usage": usage, "proposals": dict(proposals)}


# --------------------------------------------------------------------------
# Crash driver


def pending_work(root: Path) -> str:
    """``R S``: whether typed reduction (R) and the binding decision (S) are still outstanding (read-only peek)."""
    import sqlite3

    path = root / ".recalith" / db.STATE_DB
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        cursor = conn.execute("SELECT commit_sequence FROM working_cursor").fetchone()[0]
        latest = conn.execute("SELECT COALESCE(MAX(commit_sequence), 0) FROM events").fetchone()[0]
        undecided = conn.execute("SELECT COUNT(*) FROM task_boundaries WHERE reason = 'pivot_prefix' AND state = 'pending'").fetchone()[0]
        ready = any((root / ".recalith" / "spool" / "ready").glob("*.json"))
        return f"{int(ready or cursor < latest or latest == 0)} {int(undecided > 0)}"
    except sqlite3.Error:
        return "1 1"
    finally:
        conn.close()


def main(argv: list[str]) -> int:
    """``ROOT CALLS_LOG [FAILPOINT SKIP | count HITS_LOG]``: optionally kill at one failpoint hit, or log every hit."""
    root, calls_log = Path(argv[1]), Path(argv[2])
    import forget_scenarios as forgetting

    forget_spec = forgetting.scenario(root)  # Task 16: the guarded forget, worker drains, the restore of an older copy
    if forget_spec is not None:
        if len(argv) > 3 and argv[3] == "count":
            hits_path = Path(argv[4])

            def record_forget_hit(name: str) -> None:
                with open(hits_path, "a", encoding="utf-8") as fh:
                    fh.write(f"{name} {forgetting.outstanding(root)}\n")

            for name in (*failpoints.FORGET, *failpoints.RESTORE):
                failpoints.arm(name, record_forget_hit, times=10**6)
        elif len(argv) > 3:
            failpoints.arm(argv[3], failpoints.kill, skip=int(argv[4]))
        forgetting.run_script(root, forget_spec)
        return 0
    import retention_scenarios as retention

    retention_spec = retention.scenario(root)  # Task 15 core: backups, the day-181 retention step, bounded backup retention (+ capsules in full)
    if retention_spec is not None:
        if len(argv) > 3 and argv[3] == "count":
            hits_path = Path(argv[4])

            def record_retention_hit(name: str) -> None:
                with open(hits_path, "a", encoding="utf-8") as fh:
                    fh.write(f"{name} {retention.outstanding(root)}\n")

            for name in (*failpoints.RETENTION, *failpoints.BACKUP, *failpoints.CAPSULE, *failpoints.CHAIN):  # CAPSULE, CHAIN: full-profile stores only
                failpoints.arm(name, record_retention_hit, times=10**6)
        elif len(argv) > 3:
            failpoints.arm(argv[3], failpoints.kill, skip=int(argv[4]))
        retention.run_script(root, retention_spec)
        return 0
    import delivery_scenarios as delivery

    delivery_spec = delivery.scenario(root)  # Task 12b: hooks deliver (reserve, fence, emit, receipt), then the worker accounts
    if delivery_spec is not None:
        if len(argv) > 3 and argv[3] == "count":
            hits_path = Path(argv[4])

            def record_delivery_hit(name: str) -> None:
                with open(hits_path, "a", encoding="utf-8") as fh:
                    fh.write(f"{name} {delivery.outstanding(root)}\n")

            for name in (*failpoints.DELIVERY, failpoints.INGEST_BEFORE_COMMIT, failpoints.INGEST_AFTER_COMMIT):
                failpoints.arm(name, record_delivery_hit, times=10**6)
        elif len(argv) > 3:
            failpoints.arm(argv[3], failpoints.kill, skip=int(argv[4]))
        delivery.run_script(root, delivery_spec)
        ctx = context(root)
        w = worker.Worker(ctx, model=runtime(FakeBackend(log=calls_log)), owner=f"driver:{new_id('act')[4:12]}")
        lock = process_env.InstallationLock(root)
        assert lock.try_acquire(), "another worker holds the installation"
        try:
            w.startup()
            drain(w)
        finally:
            w.close()
            lock.release()
        return 0
    import cli_scenarios as cli

    cli_spec = cli.scenario(root)  # Task 12a: guarded service writes, retried as a whole after a kill
    if cli_spec is not None:
        if len(argv) > 3 and argv[3] == "count":
            hits_path = Path(argv[4])

            def record_service_hit(name: str) -> None:
                with open(hits_path, "a", encoding="utf-8") as fh:
                    fh.write(f"{name} {cli.outstanding(root)}\n")

            for name in (*failpoints.SERVICE, failpoints.REVIEW_AFTER_SCHEDULE):
                failpoints.arm(name, record_service_hit, times=10**6)
        elif len(argv) > 3:
            failpoints.arm(argv[3], failpoints.kill, skip=int(argv[4]))
        cli.run_script(root, cli_spec)
        return 0
    import provider_scenarios as provider

    spec = provider.scenario(root)
    lineage_spec = (root / "lineage.json").exists()  # Task 8: root-class merges at ingestion
    import admission_scenarios as admission

    admission_spec = admission.scenario(root)  # Task 9: extraction, review admission and failure debounce
    import consolidation_scenarios as revision

    revision_spec = revision.scenario(root)  # Task 10: FailureRecheck, dependency changes, revalidation and its review
    import retrieval_scenarios as retrieval

    retrieval_spec = retrieval.scenario(root)  # Task 11: the projection (index and views) over the Task 10 scenario
    if len(argv) > 3 and argv[3] == "count":
        hits = Path(argv[4])
        if lineage_spec:
            import lineage_scenarios as lineage_s

        def record_hit(name: str) -> None:
            state = retrieval.outstanding(root) if retrieval_spec else provider.outstanding(root) if spec else lineage_s.outstanding(root) if lineage_spec else admission.outstanding(root) if admission_spec else revision.outstanding(root) if revision_spec else pending_work(root)
            with open(hits, "a", encoding="utf-8") as fh:
                fh.write(f"{name} {state}\n")

        names = failpoints.WORKER + failpoints.REDUCTION + failpoints.PROVIDER + failpoints.ADMISSION + failpoints.REVISION + failpoints.CHAIN  # CHAIN: full-profile stores only
        if retrieval_spec:
            names += failpoints.RETRIEVAL
        if lineage_spec or revision_spec:
            names += failpoints.LINEAGE + (failpoints.INGEST_BEGIN, failpoints.INGEST_BEFORE_COMMIT, failpoints.INGEST_AFTER_COMMIT, failpoints.INGEST_AFTER_UNLINK)
        for name in names:
            failpoints.arm(name, record_hit, times=10**6)
    elif len(argv) > 3:
        failpoints.arm(argv[3], failpoints.kill, skip=int(argv[4]))
    ctx = context(root)
    import operation_scenarios as scenarios

    if spec is not None:  # Task 7: the production preparer and a real bounded provider child
        clock = FakeClock(spec["clock"])
        w = worker.Worker(ctx, clock=clock, model=provider.runtime(ctx, spec, clock), owner=f"driver:{new_id('act')[4:12]}")
        lock = process_env.InstallationLock(root)
        assert lock.try_acquire(), "another worker holds the installation"
        try:
            w.startup()  # reaps a curator tree a killed predecessor left behind
            drain(w)
        finally:
            w.close()
            lock.release()
        return 0
    if admission_spec is not None or revision_spec is not None:  # Tasks 9/10: the production preparer; recorded bodies from each request
        from recalith.controller import requests as model_requests

        def answer(request: bytes, purpose: str) -> None:
            if revision_spec is not None:
                backend.body = revision.crash_answer(revision_spec, json.loads(request), purpose)
            else:
                backend.body = admission.crash_answer(admission_spec, json.loads(request), purpose)

        backend = FakeBackend(lambda purpose, i: worker.LaunchOutcome(stdout=envelope(backend.body, usage={"input_tokens": 50, "output_tokens": 10})), on_launch=answer, log=calls_log)
        w = worker.Worker(ctx, model=runtime(backend, model_requests.runtime_preparer(ctx)), owner=f"driver:{new_id('act')[4:12]}")
        lock = process_env.InstallationLock(root)
        assert lock.try_acquire(), "another worker holds the installation"
        try:
            w.startup()
            drain(w)
        finally:
            w.close()
            lock.release()
        return 0
    bodies = scenarios.scenario_bodies(root)
    if bodies is None:
        backend, prepare = FakeBackend(log=calls_log), None
    else:  # real operations over real captured events (Tasks 5 and 6)
        import working_scenarios as working

        def body_for(purpose: str) -> bytes:
            if purpose not in bodies and working.dynamic(root):
                if purpose == "update_task":
                    return working.split_body(root)  # a binding decision computed from the reduced store
                return NO_OP_BODY  # e.g. extraction a due failure trigger scheduled (Task 9)
            return bodies.get(purpose, NO_OP_BODY)  # jobs Task 9 schedules beside a scenario's own (reviews, extractions)

        backend = FakeBackend(lambda purpose, i: worker.LaunchOutcome(stdout=envelope(body_for(purpose), usage={"input_tokens": 50, "output_tokens": 10})), log=calls_log)
        prepare = scenarios.scenario_prepare
    w = worker.Worker(ctx, model=runtime(backend, prepare), owner=f"driver:{new_id('act')[4:12]}")
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
