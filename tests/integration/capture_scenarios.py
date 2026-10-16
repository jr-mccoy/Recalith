"""Test-only capture source, seeded scenarios and the kill/restart crash driver.

The JSONL format here is a *test-only registered source* (IMPLEMENTATION_PLAN
§Dependency-safe release sequence); it is not a shipped host adapter. Real
Claude transcript parsing is Task 3b.

Run as a script, this module is the crash driver: it resolves the installation
in a fresh process, arms one failpoint to kill the process, and executes
scenario steps from ``start``. ACCEPTANCE_TESTS §4: the parent restarts it,
then compares the reopened store with a reference run.

    python capture_scenarios.py ROOT SEED START [FAILPOINT SKIP]
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
for extra in (HERE.parents[1] / "src", HERE.parent):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from recalith.capture import pipeline, sources  # noqa: E402
from recalith.capture.normalize import RawEvent, normalize_event  # noqa: E402
from recalith.contracts.common import Actor  # noqa: E402
from recalith.contracts.config import ProjectConfig  # noqa: E402
from recalith.core import identity  # noqa: E402
from recalith.storage import db, failpoints, spool  # noqa: E402

ADAPTER = "test_jsonl"
ADAPTER_ACTOR = Actor(kind="adapter", id="test-adapter", channel="hook")
SESSION = "sess_77777777-7777-4777-8777-777777777777"
HOST_SESSION = "host-session-scenario"
TRANSCRIPT = "transcript.jsonl"
PROJECT_ID = "proj_88888888-8888-4888-8888-888888888888"


def action(argv: list[str], **overrides: Any) -> dict[str, Any]:
    data = {"cwd_path": ".", "tool": "Bash", "action_kind": "test", "executable": argv[0], "argv": argv, "paths": [], "raw_digest": None, "parse_status": "exact", "shell": "bash"}
    data.update(overrides)
    return data


def raw_from_record(record: dict[str, Any], key: str) -> RawEvent | None:
    kind = record.get("type")
    common = dict(adapter_id=ADAPTER, adapter_version="1", source_event_key=key, session_id=SESSION, host_session_id=HOST_SESSION, origin_kind="transcript", occurred_at=record.get("at"))
    if kind == "user":
        return RawEvent(kind="user_message", payload={"text": record["text"]}, **common)
    if kind == "assistant":
        return RawEvent(kind="assistant_message", payload={"text": record["text"]}, **common)
    if kind == "start":
        return RawEvent(kind="session_started", payload={"source": "startup", "environment": record.get("environment", {})}, **common)
    if kind in ("tool_use", "tool_result"):
        finished = kind == "tool_result"
        payload = {
            "tool_call_id": record["call"],
            "tool_name": "Bash",
            "arguments": {"command": " ".join(record["argv"])},
            "result_received": finished,
            "outcome": record.get("outcome", "unknown") if finished else "unknown",
            "exit_code": record.get("exit") if finished else None,
            "result_text": record.get("output") if finished else None,
            "action": action(record["argv"]),
            "observation": None,
        }
        return RawEvent(kind="tool_finished" if finished else "tool_started", payload=payload, **common)
    return None


def parse_line(record: dict[str, Any], ctx: sources.LineContext) -> list[RawEvent]:
    raw = raw_from_record(record, record.get("uuid") or ctx.fallback_key())
    return [raw] if raw else []


def line(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")


# --------------------------------------------------------------------------
# Installations


def init_project(parent: Path, name: str) -> Path:
    root = parent / name
    root.mkdir()
    identity.initialize_installation(root, ProjectConfig.defaults_for(PROJECT_ID))
    return root


def context(root: Path):
    return identity.resolve_installation(root, actor=ADAPTER_ACTOR)


def register_transcript(root: Path) -> str:
    path = root / TRANSCRIPT
    path.touch()
    ctx = context(root)
    with db.open_store(ctx) as store:
        return sources.register_source(store, ctx, adapter_id=ADAPTER, path=path, session_id=SESSION, host_session_id=HOST_SESSION).source_id


# --------------------------------------------------------------------------
# Seeded scenarios: several steps of appended transcript bytes plus hook captures


@dataclass
class Step:
    append: bytes
    hook_records: list[dict[str, Any]] = field(default_factory=list)


def build_scenario(seed: int) -> list[Step]:
    rng = random.Random(seed)
    records: list[dict[str, Any]] = [{"type": "start", "uuid": "u-start", "at": "2026-10-16T09:00:00.000000Z", "environment": {"os": "linux", "arch": "x86_64", "SECRET_TOKEN": "x"}}]
    for i in range(rng.randint(4, 9)):
        call = f"call-{i}"
        argv = ["python", "-m", "unittest"] if rng.random() < 0.5 else ["pytest", "-q", f"tests/test_{i}.py"]
        failed = rng.random() < 0.5
        if argv[0] == "python":
            output = f"Ran {rng.randint(1, 9)} tests in 0.01s\n" + ("FAILED (failures=1)" if failed else "OK")
        else:
            output = ("FAILED tests/x.py::t - AssertionError\n" if failed else "") + f"==== {'1 failed' if failed else '3 passed'} in 0.05s ===="
        records.append({"type": "user", "uuid": f"u-user-{i}", "text": f"step {i}: run the tests ✓ ünïcode"})
        records.append({"type": "tool_use", "uuid": f"u-use-{i}", "call": call, "argv": argv})
        records.append({"type": "tool_result", "uuid": f"u-res-{i}", "call": call, "argv": argv, "exit": 1 if failed else 0, "outcome": "failure" if failed else "success", "output": output})
    blob = b"".join(line(r) for r in records)
    # Split into three appends at arbitrary byte positions: partial lines are common.
    cuts = sorted(rng.sample(range(1, len(blob)), 2))
    chunks = [blob[: cuts[0]], blob[cuts[0] : cuts[1]], blob[cuts[1] :]]
    steps = [Step(append=chunk) for chunk in chunks]
    # A second producer (the hook) captures some of the same records: same key
    # and content deduplicates; one seeded record carries changed content.
    hooked = rng.sample(records[1:], k=min(3, len(records) - 1))
    for index, record in enumerate(hooked):
        changed = dict(record)
        if index == 0 and seed % 2 == 0 and record["type"] == "user":
            changed["text"] = record["text"] + " (edited by another producer)"
        steps[rng.randrange(len(steps))].hook_records.append(changed)
    return steps


def ensure_appended(root: Path, steps: list[Step], upto: int) -> None:
    """Idempotently make the transcript equal to the first ``upto + 1`` appends."""
    path = root / TRANSCRIPT
    expected = b"".join(s.append for s in steps[: upto + 1])
    current = path.read_bytes()
    assert expected.startswith(current), "transcript diverged from the scenario"
    with open(path, "ab") as fh:
        fh.write(expected[len(current) :])


def run_step(root: Path, steps: list[Step], index: int, source_id: str) -> None:
    ensure_appended(root, steps, index)
    ctx = context(root)
    if steps[index].hook_records:
        envelopes = []
        for record in steps[index].hook_records:
            envelopes += normalize_event(ctx, raw_from_record(record, record["uuid"]))[0]
        pipeline.capture(ctx, envelopes)
    pipeline.recover_source(ctx, source_id, parse_line)
    pipeline.ingest_ready(ctx)


def run_steps(root: Path, seed: int, start: int, source_id: str) -> None:
    steps = build_scenario(seed)
    for index in range(start, len(steps)):
        run_step(root, steps, index, source_id)


def settle(root: Path, source_id: str) -> None:
    """After all steps: one more recovery/ingest pass and stale-temp cleanup."""
    ctx = context(root)
    pipeline.recover_source(ctx, source_id, parse_line)
    pipeline.ingest_ready(ctx)
    spool.cleanup_stale_temps(spool.SpoolDirs(root), older_than=0)


def authoritative_state(root: Path) -> dict[str, Any]:
    """Comparable state; installation-derived IDs are mapped back to source keys."""
    ctx = context(root)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        key_of = dict(view.execute("SELECT event_id, source_event_key FROM events").fetchall())
        events = sorted(view.execute("SELECT adapter_id, source_event_key, payload_digest, kind FROM events").fetchall())
        conflicts = sorted((key_of[o], d, st) for o, d, st in view.execute("SELECT original_event_id, payload_digest, state FROM source_conflicts").fetchall())
        jobs = view.execute("SELECT body FROM jobs WHERE kind = 'ingest'").fetchall()
        cursor = view.execute("SELECT ingested_cursor FROM capture_sources").fetchall()
        sessions = sorted(view.execute("SELECT session_id, state FROM sessions").fetchall())
        observations = sorted((k, v, sk, key_of.get(e)) for k, v, sk, e in view.execute("SELECT key, value, source_kind, source_event_id FROM environment_observations").fetchall())
    coverage: dict[str, int] = {}
    for (body,) in jobs:
        for ref in json.loads(body)["input_refs"]:
            name = key_of[ref["id"]]
            coverage[name] = coverage.get(name, 0) + 1
    dirs = spool.SpoolDirs(root)
    return {
        "events": events,
        "conflicts": conflicts,
        "job_coverage": coverage,
        "cursor": [spool.cursor_order(json.loads(c[0])) for c in cursor],
        "sessions": sessions,
        "observations": observations,
        "ready": [p.name for p in spool.ready_segments(dirs)],
        "temps": sorted(p.name for p in dirs.tmp.iterdir()) if dirs.tmp.is_dir() else [],
        "quarantine": sorted(p.name for p in dirs.quarantine.iterdir()) if dirs.quarantine.is_dir() else [],
    }


def main(argv: list[str]) -> int:
    root, seed, start = Path(argv[1]), int(argv[2]), int(argv[3])
    if len(argv) > 4:
        failpoints.arm(argv[4], failpoints.kill, skip=int(argv[5]))
    ctx = context(root)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        source_id = view.execute("SELECT source_id FROM capture_sources").fetchone()[0]
    steps = build_scenario(seed)
    for index in range(start, len(steps)):
        print(f"step {index}", flush=True)  # the parent restarts from the crashed step
        run_step(root, steps, index, source_id)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
