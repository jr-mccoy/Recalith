#!/usr/bin/env python3
"""Measure hook-side context compilation latency in fresh interpreter processes (ACCEPTANCE_TESTS §7; Task 11).

    python tools/measure_compile_latency.py [--trials 500] [--corpus 10000] \
        [--output docs/measurements/hook-compile-latency.json]

Each trial is a fresh ``python -I`` process that does what the hook's delivery
branch will do before emitting anything (Task 12b adds the session
reservation, stdout and receipts): start the shared soft deadline at entry
+250 ms, read the validated hook-context manifest, and run
:func:`recalith.fast.context.hook_compile_context` (read-only snapshots, the
view or at most 32 fallback rows, live condition and dependency checks, the
budgeted assembly and the fresh final fence). The wall time is spawn to exit,
so it includes interpreter start-up; the child also reports its own time from
entry to the fenced packet against the 250 ms deadline.

The store is a real project: the Claude Code 2.1.301 lifecycle session
through the real adapter, ingestion and reduction, an admitted failure lesson
on the captured ``pytest -q test_mid.py`` failure with a file dependency (the
real path with a recorded review), plus a synthetic corpus of ``--corpus``
claim heads copied from an admitted fact (labeled synthetic). Regimes:

* ``warm_pre_action`` / ``warm_prompt``: current views; the real action (a
  caution with its live dependency check) or a prompt text.
* ``fallback_pre_action``: the views are stale (a later admitted fact moved
  the guidance epoch): at most 32 fallback rows filtered against live heads.

This is not a delivery certification: nothing is emitted and no host is
involved (Task 13). The OS page cache is not dropped.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "tests" / "integration"), str(ROOT / "tests" / "platform"), str(ROOT / "tools")]

import measure_hook_latency as mhl  # noqa: E402

CHILD = r"""
import json, sys, time
start = time.monotonic()
deadline = start + 0.250
from recalith.fast import entry
from recalith.fast import cache
case = json.loads(sys.stdin.read())
ctx = entry.load_context(case["root"], "claude_code")
result = cache.compile_packet(ctx, case["query"], deadline=deadline)
packet = result["packet"]
print(json.dumps({"compile_ms": round((time.monotonic() - start) * 1000, 3), "source": result["source"], "items": len(packet["items"]),
                  "advice": sorted({i["advice"] for i in packet["items"]}), "degraded": packet["degraded_reasons"], "tokens": packet["estimated_tokens"],
                  "fence_ms": (result.get("fence") or {}).get("fence_ms"), "remaining_ms": round((deadline - time.monotonic()) * 1000, 3)}))
"""


def trial(case: dict) -> tuple[float, dict]:
    start = time.perf_counter()
    proc = subprocess.run([sys.executable, "-I", "-c", CHILD], input=json.dumps(case), capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    elapsed = time.perf_counter() - start
    if proc.returncode != 0:
        raise RuntimeError(f"compile trial failed: {proc.stderr[-800:]}")
    return elapsed, json.loads(proc.stdout.strip().splitlines()[-1])


def run_regime(case: dict, n: int) -> dict:
    walls, inner, degraded, sources = [], [], 0, {}
    sample = None
    for _ in range(n):
        wall, reply = trial(case)
        walls.append(wall)
        inner.append(reply["compile_ms"] / 1000)
        sources[reply["source"]] = sources.get(reply["source"], 0) + 1
        degraded += bool(set(reply["degraded"]) - {"view_stale"})
        sample = reply
    return {"wall_spawn_to_exit": mhl.summarize(walls), "entry_to_fenced_packet": mhl.summarize(inner), "sources": sources,
            "degraded_trials": degraded, "deadline_ms": 250, "sample_reply": sample}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trials", type=int, default=500)
    parser.add_argument("--corpus", type=int, default=10_000)
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "measurements" / "hook-compile-latency.json")
    args = parser.parse_args(argv)

    import consolidation_scenarios as cs
    import retrieval_scenarios as rs

    with tempfile.TemporaryDirectory(prefix="recalith-compile-latency-") as tmp:
        tmp_path = Path(tmp)
        p = rs.project(tmp_path)
        cs.lesson(p)
        fact = cs.fact(p, "The fixture teardown must close the sqlite connection.", subject="teardown sqlite")
        if args.corpus:
            rs.corpus(p, fact, args.corpus, proposition="Corpus {i}: deployment notes for the staging bucket and cache warmup.")
        rs.publish(p)
        act = rs.mid_action(p)
        cases = {
            "warm_pre_action": {"root": str(p.root), "query": rs.query(p, act=act).model_dump(mode="json")},
            "warm_prompt": {"root": str(p.root), "query": rs.query(p, "prompt", text="how should the fixture teardown close sqlite?").model_dump(mode="json")},
        }
        report = {"regimes": {}}
        for name, case in cases.items():
            report["regimes"][name] = run_regime(case, args.trials)
        cs.fact(p, "A later fact moves the guidance epoch.", subject="later")  # the views are now stale
        report["regimes"]["fallback_pre_action"] = run_regime(cases["warm_pre_action"], args.trials)
        report.update({
            "tool": "tools/measure_compile_latency.py",
            "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "measurement": "hook-side context compilation (views or bounded fallback, live checks, budget, fresh fence) in fresh python -I processes; nothing emitted",
            "scope": "Task 11 compile latency against the shared 250 ms hook deadline; not a delivery certification (Tasks 12b/13), not live recall quality (B1)",
            "store": {"real_payloads": "Claude Code 2.1.301 lifecycle session through the real adapter", "admitted": ["failure lesson on pytest -q test_mid.py (file dependency)", "fact"],
                      "synthetic_corpus_claim_heads": args.corpus},
            "environment": mhl.facts(tmp_path),
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: (v["wall_spawn_to_exit"], v["entry_to_fenced_packet"], v["sources"], v["degraded_trials"]) for k, v in report["regimes"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
