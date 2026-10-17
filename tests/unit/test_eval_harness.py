"""Task 7: the first increment of the smoke evaluation harness (evals/run.py).

No model is called and no agent session runs here: preflight states which
capabilities a candidate run still lacks, and prepare builds independent
candidate/baseline workspaces whose seed must fail its oracle.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "evals" / "run.py"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RUN), *args], capture_output=True, text=True, encoding="utf-8", timeout=300, check=False)


def test_preflight_names_what_a_candidate_run_lacks():
    result = run("preflight")
    assert result.returncode == 4, result.stderr
    out = json.loads(result.stdout)
    assert out["verdict"] == "unavailable" and out["inference"]["reasons"] == ["provider_not_configured"]
    assert out["delivery"]["state"] == "unavailable"
    assert len(out["scenarios"]) == 12 and {s["candidate"] for s in out["scenarios"].values()} == {"unavailable"}
    assert {s["baseline"] for s in out["scenarios"].values()} == {"ready"}  # the clean baseline needs no route


def test_prepare_builds_independent_arms_and_the_seed_fails(tmp_path):
    result = run("prepare", "smoke-L1-ledgerlite-test-command", "--out", str(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout)
    candidate, baseline = Path(out["candidate"]["workspace"]), Path(out["baseline"]["workspace"])
    assert (candidate / ".recalith" / "project.toml").exists() and out["candidate"]["installation_id"].startswith("inst_")
    assert not (baseline / ".recalith").exists() and out["baseline"]["installation_id"] is None
    assert out["seed_oracle"] == {"exit": 1, "passed": False}
    assert run("prepare", "smoke-unknown", "--out", str(tmp_path / "x")).returncode == 2
