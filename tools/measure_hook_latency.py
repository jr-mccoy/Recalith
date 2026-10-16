#!/usr/bin/env python3
"""Measure capture-only hook latency in fresh interpreter processes (ACCEPTANCE_TESTS §7).

    python tools/measure_hook_latency.py [--warm 500] [--cold 100] [--first-launch 50] \
        [--output docs/measurements/hook-latency-capture-only.json]

Each trial starts a fresh ``python -I -m recalith.fast.entry`` exactly as the
hook launcher does and times it from spawn to exit, so the figure includes
interpreter start-up. Payloads are real Claude Code 2.1.301 hook payloads from
``tests/fixtures/hosts/claude/2.1.301/`` (prompt, pre-tool, small post-tool,
the host's 30,000-character stdout cap, and a host-truncated failure).

Regimes, labeled precisely:

* ``warm``: repeated launches; bytecode and OS page cache warm.
* ``cold_bytecode``: ``-X pycache_prefix`` points at a new empty directory per
  trial, so every imported module (stdlib included) is compiled from source.
  A pessimistic bound; a provisioned runtime ships compiled bytecode.
* ``first_launch``: the first hook in a newly initialized installation (spool
  directories created by that hook); bytecode present.

The OS page cache is not dropped (that needs privileges a container lacks);
the report says so. This is capture-only timing: no delivery path exists in
this build, so nothing here is a delivery latency claim.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests" / "platform")]

import claude_fixtures as cf  # noqa: E402

PAYLOAD_CLASSES = {
    "prompt": ("lifecycle", "UserPromptSubmit", None),
    "pre_tool": ("lifecycle", "PreToolUse", None),
    "post_tool_small": ("lifecycle", "PostToolUse", "echo hello-fixture"),
    "post_tool_30k_stdout": ("lifecycle", "PostToolUse", "seq 1 12000"),
    "post_tool_failure_host_truncated": ("lifecycle", "PostToolUseFailure", "pytest -q test_mid.py"),
}


def pick(scenario: str, event: str, command: str | None) -> dict:
    records = cf.records(scenario)
    if command is None:
        return next(r for r in records if r["event"] == event)
    call = next(r["payload"]["tool_use_id"] for r in records if r["event"] == "PreToolUse" and r["payload"]["tool_input"].get("command") == command)
    return next(r for r in records if r["event"] == event and r["payload"].get("tool_use_id") == call)


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def summarize(samples: list[float]) -> dict:
    ms = [s * 1000 for s in samples]
    return {"n": len(ms), "p50_ms": round(percentile(ms, 0.50), 2), "p95_ms": round(percentile(ms, 0.95), 2), "p99_ms": round(percentile(ms, 0.99), 2), "max_ms": round(max(ms), 2), "mean_ms": round(statistics.fmean(ms), 2)}


def trial(root: Path, data: bytes, event: str, reply: Path, *, pycache: Path | None = None) -> tuple[float, dict]:
    argv = [sys.executable, "-I"]
    if pycache is not None:
        argv += ["-X", f"pycache_prefix={pycache}"]
    argv += ["-m", "recalith.fast.entry", "--project", str(root), "claude_code", "--event", event, "--reply-file", str(reply)]
    start = time.perf_counter()
    proc = subprocess.run(argv, input=data, capture_output=True, env=cf.child_env(), timeout=60, check=False)
    elapsed = time.perf_counter() - start
    if proc.returncode != 0 or proc.stdout or proc.stderr:
        raise RuntimeError(f"hook trial failed: rc={proc.returncode} stderr={proc.stderr[-500:]!r}")
    return elapsed, json.loads(reply.read_text(encoding="utf-8"))


def unique(record: dict, i: int) -> dict:
    payload = dict(record["payload"])
    if "tool_use_id" in payload:
        payload["tool_use_id"] = f"{payload['tool_use_id']}_lat{i:05d}"
    if "prompt" in payload:
        payload["prompt"] = f"{payload['prompt']} #{i}"
    return dict(record, payload=payload)


def facts(tmp: Path) -> dict:
    cpu = None
    try:
        cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines() if line.startswith("model name")), None)
    except OSError:
        pass
    from recalith.core.identity import filesystem_type

    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "python_build": " ".join(platform.python_build()),
        "cpu_model": cpu or platform.processor() or None,
        "logical_cpus": os.cpu_count(),
        "filesystem": filesystem_type(tmp),
        "os_page_cache": "not dropped (no privilege in this environment); warm OS cache throughout",
        "power_mode": "unknown (cloud container)",
        "antivirus_indexer": "none observed (Linux container)" if sys.platform.startswith("linux") else "unknown",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--warm", type=int, default=500, help="warm trials per payload class")
    parser.add_argument("--cold", type=int, default=100, help="no-bytecode-cache trials per payload class")
    parser.add_argument("--first-launch", type=int, default=50, help="first hooks in new installations")
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "measurements" / "hook-latency-capture-only.json")
    args = parser.parse_args(argv)
    tmp = Path(tempfile.mkdtemp(prefix="recalith-latency-"))
    replay = cf.Replay(tmp / "main")
    classes = {}
    for name, spec in PAYLOAD_CLASSES.items():
        record = pick(*spec)
        sizes = len(replay.prepare(record))
        warm: list[float] = []
        cold: list[float] = []
        overruns = {"warm": 0, "cold_bytecode": 0}
        statuses: dict[str, int] = {}
        trial(replay.root, replay.prepare(unique(record, 0)), record["event"], tmp / "r.json")  # warm-up compiles bytecode
        for i in range(args.warm):
            elapsed, reply = trial(replay.root, replay.prepare(unique(record, i + 1)), record["event"], tmp / "r.json")
            warm.append(elapsed)
            overruns["warm"] += "capture_deadline_overrun" in reply.get("degradations", [])
            status = (reply.get("receipt") or {}).get("status", "none")
            statuses[status] = statuses.get(status, 0) + 1
        for i in range(args.cold):
            elapsed, reply = trial(replay.root, replay.prepare(unique(record, 100000 + i)), record["event"], tmp / "r.json", pycache=tmp / f"pyc-{name}-{i}")
            cold.append(elapsed)
            overruns["cold_bytecode"] += "capture_deadline_overrun" in reply.get("degradations", [])
        classes[name] = {"event": record["event"], "stdin_bytes": sizes, "warm": summarize(warm), "cold_bytecode": summarize(cold) if cold else None, "deadline_overruns": overruns, "receipt_status": statuses}
        print(name, classes[name]["warm"], classes[name]["cold_bytecode"], flush=True)
    first: list[float] = []
    record = pick(*PAYLOAD_CLASSES["prompt"])
    for i in range(args.first_launch):
        fresh = cf.Replay(tmp / f"first-{i}")
        elapsed, _ = trial(fresh.root, fresh.prepare(record), record["event"], tmp / "r.json")
        first.append(elapsed)
    report = {
        "measurement": "capture-only hook latency (fresh interpreter per trial, spawn to exit)",
        "tool": "tools/measure_hook_latency.py",
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host_fixture_version": cf.VERSION,
        "scope": "Capture branch only; delivery is unavailable in this build, so no delivery latency is claimed. Soft deadline 250 ms from entry; the ACCEPTANCE_TESTS §7 p95 300 ms / p99 750 ms targets apply to capture plus delivery and are evaluated at Task 18.",
        "environment": facts(tmp),
        "regimes": {
            "warm": "repeated launches, bytecode and OS cache warm",
            "cold_bytecode": "-X pycache_prefix=<new empty dir> per trial: all modules compiled from source (pessimistic)",
            "first_launch": "first hook in a newly initialized installation; bytecode present",
        },
        "payload_classes": classes,
        "first_launch": {"payload_class": "prompt", **summarize(first)},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report["first_launch"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
