#!/usr/bin/env python3
"""Measure the hook with its delivery branch in fresh processes: compile and local emission timing only (ACCEPTANCE_TESTS §7; Task 12b).

    python tools/measure_delivery_latency.py [--trials 500] [--corpus 10000] \
        [--output docs/measurements/hook-delivery-latency.json]

Each trial is a fresh ``python -I -m recalith.fast.entry`` process, exactly as
the hook launcher runs it, fed one real Claude Code 2.1.301 payload (a
variant with its own tool-use ID or prompt text and, except in the
``suppressed`` regime, its own host session so nothing is suppressed). The hook
captures durably, then delivers: compile (views or at most 32 fallback rows),
session lock, reservation, fresh final fence, stdout write and flush, receipt
spool and mark. The wall time is spawn to exit (interpreter start-up
included); the reply file reports the hook's own time from entry and the
delivery state. The installation enables delivery only in its controlled
test manifest. Regimes:

* ``warm_pre_action``: current views, the captured ``pytest -q test_mid.py``
  pre-action: a caution is emitted;
* ``warm_prompt``: current views, a prompt naming the fixture: context emitted;
* ``suppressed_pre_action``: the same session again: the unchanged caution is
  suppressed (compile, lock and accounting, no output);
* ``fallback_pre_action``: stale views (a later admitted fact moved the
  guidance epoch): at most 32 live-filtered fallback rows, then delivery.

This measures local compile and emission time against the shared 250 ms soft
deadline. It is not a delivery certification (no host reads the output; the
nonce protocol is Task 13) and not live recall quality (B1). The OS page cache
is not dropped.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "tests" / "integration"), str(ROOT / "tests" / "platform"), str(ROOT / "tools")]

import measure_hook_latency as mhl  # noqa: E402


def trial(root: Path, data: bytes, event: str, reply: Path) -> tuple[float, dict, bytes]:
    import subprocess

    import claude_fixtures as cf

    argv = [sys.executable, "-I", "-m", "recalith.fast.entry", "--project", str(root), "claude_code", "--event", event, "--reply-file", str(reply)]
    start = time.perf_counter()
    proc = subprocess.run(argv, input=data, capture_output=True, env=cf.child_env(), timeout=60, check=False)
    elapsed = time.perf_counter() - start
    if proc.returncode != 0 or proc.stderr:
        raise RuntimeError(f"hook trial failed: rc={proc.returncode} stderr={proc.stderr[-500:]!r}")
    return elapsed, json.loads(reply.read_text(encoding="utf-8")), proc.stdout


def run_regime(p, make, n: int, tmp: Path) -> dict:
    walls, inner, states, degraded, emitted_bytes = [], [], {}, 0, []
    sample = None
    for i in range(n):
        rec = make(i)
        wall, reply, out = trial(p.root, p.replay.prepare(rec), rec["event"], tmp / "reply.json")
        walls.append(wall)
        inner.append(reply["elapsed_ms"] / 1000)
        state = reply["delivery"]["state"]
        states[state] = states.get(state, 0) + 1
        bad = set(reply["delivery"].get("degraded", [])) - {"view_stale"}
        degraded += bool(bad) or state in ("skipped", "fenced_out", "uncertain")
        if out:
            emitted_bytes.append(len(out))
        sample = {"delivery": {k: v for k, v in reply["delivery"].items() if k != "receipt"}, "degradations": reply["degradations"], "elapsed_ms": reply["elapsed_ms"]}
    return {"wall_spawn_to_exit": mhl.summarize(walls), "entry_to_exit": mhl.summarize(inner), "delivery_states": states, "degraded_trials": degraded,
            "stdout_bytes_max": max(emitted_bytes, default=0), "deadline_ms": 250, "sample_reply": sample}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trials", type=int, default=500)
    parser.add_argument("--corpus", type=int, default=10_000)
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "measurements" / "hook-delivery-latency.json")
    args = parser.parse_args(argv)

    import consolidation_scenarios as cs
    import delivery_scenarios as ds
    import retrieval_scenarios as rs

    with tempfile.TemporaryDirectory(prefix="recalith-delivery-latency-") as tmp:
        tmp_path = Path(tmp)
        p, ids = ds.project(tmp_path)
        fact = cs.fact(p, "The fixture teardown must close the sqlite connection.", subject="teardown sqlite")
        if args.corpus:
            rs.corpus(p, fact, args.corpus, proposition="Corpus {i}: deployment notes for the staging bucket and cache warmup.")
        rs.publish(p)
        ds.enable(p)

        def pre(session, i):
            return ds.call_records(ds.MID, f"lat{i:05d}", session=session)[0]

        def prompt(session, i):
            return ds.wks.variant(ds.record("UserPromptSubmit"), session=session, prompt=f"How should the fixture teardown close sqlite before test_mid? #{i}")

        fixed = ds.fresh_session(900)
        regimes = {
            "warm_pre_action": lambda i: pre(f"00000000-0000-4000-8001-{i:012d}", i),
            "warm_prompt": lambda i: prompt(f"00000000-0000-4000-8002-{i:012d}", i),
            "suppressed_pre_action": lambda i: pre(fixed, i),
        }
        report = {"regimes": {}}
        for name, make in regimes.items():
            report["regimes"][name] = run_regime(p, make, args.trials, tmp_path)
        cs.fact(p, "A later fact moves the guidance epoch.", subject="later")  # the views are now stale
        report["regimes"]["fallback_pre_action"] = run_regime(p, lambda i: pre(f"00000000-0000-4000-8003-{i:012d}", i), args.trials, tmp_path)
        report.update({
            "tool": "tools/measure_delivery_latency.py",
            "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "measurement": "the real hook entry with its delivery branch (capture, compile, session lock, reservation, final fence, stdout, receipt spool, mark) in fresh python -I processes",
            "scope": "Task 12b compile and local emission timing against the shared 250 ms soft deadline; not a delivery certification (Task 13: no host reads the output), not live recall quality (B1)",
            "store": {"real_payloads": "Claude Code 2.1.301 lifecycle session through the real adapter; per-trial variants (new tool-use IDs, host sessions, prompt texts)",
                      "admitted": ["failure lesson on pytest -q test_mid.py (file dependency)", "fact"], "synthetic_corpus_claim_heads": args.corpus,
                      "manifest": "controlled test manifest with every delivery path enabled"},
            "environment": mhl.facts(tmp_path),
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: (v["wall_spawn_to_exit"], v["entry_to_exit"], v["delivery_states"], v["degraded_trials"]) for k, v in report["regimes"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
