"""The smoke evaluation harness (evals/run.py): Task 7's first increment and Task 18's preview harness.

No model is called and no live agent session runs here: preflight states which
capabilities a live candidate run still lacks, prepare builds independent
candidate/baseline workspaces whose seed must fail its oracle, and the Task 18
tests run the scripted mode (scripted agent, recorded curator) and check its
labeling, the guard, the report's statistics, the seeded workload days, the
release checklist and the dependency inventory (decision 0020).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

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


# --------------------------------------------------------------------------
# Task 18: the preview harness (decision 0020)

sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "tools")]


def host_record(tmp_path: Path, *, mode: str = "live", **delivery: str) -> Path:
    """A ``.recalith/host.json`` in the HostCertification contract's own shape, as tools/probe_delivery.py writes it."""
    from recalith.contracts.common import digest_of

    states = {"session_start": "certified", "prompt": "certified", "pre_action": "certified", "compact_restore": "certified"} if mode == "live" else dict.fromkeys(("session_start", "prompt", "pre_action", "compact_restore"), "unavailable")
    states.update(delivery)
    record = {
        "certification_schema": 1, "installation_id": "inst_11111111-1111-4111-8111-111111111111", "host_id": "claude_code", "host_version": "2.1.309",
        "mode": mode, "certified_at": "2026-10-23T00:00:00.000000Z", "report_digest": digest_of(["synthetic host record", mode]),
        "delivery": states, "command_rules": "installed", "private_paths": "probed_limited",
    }
    path = tmp_path / "host.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_preflight_names_a_request_capture_host_record(tmp_path):
    record = host_record(tmp_path, mode="request_capture")
    result = run("preflight", "--host-record", str(record))
    assert result.returncode == 4
    out = json.loads(result.stdout)
    assert out["delivery"] == {"state": "unavailable", "reasons": ["delivery_request_capture_only"]}
    assert any("probe_delivery.py" in step for step in out["operator_action"])  # the exact operator route, no secret values


def test_preflight_accepts_a_live_host_record(tmp_path):
    """The first real live record (Claude Code 2.1.309, native Windows) was refused: the preflight read an invented
    shape (``delivery_paths`` of objects) instead of the HostCertification contract (``delivery`` of states)."""
    out = json.loads(run("preflight", "--host-record", str(host_record(tmp_path))).stdout)
    assert out["delivery"] == {"state": "certified", "reasons": [], "host_version": "2.1.309"}
    assert out["inference"]["state"] == "unavailable"  # no route given: still not ready
    failed = json.loads(run("preflight", "--host-record", str(host_record(tmp_path, prompt="failed"))).stdout)
    assert failed["delivery"]["reasons"] == ["required_path_not_certified:prompt"]
    optional = json.loads(run("preflight", "--host-record", str(host_record(tmp_path, pre_action="failed"))).stdout)
    assert optional["delivery"]["state"] == "certified"  # optional paths never gate


def test_preflight_rejects_a_record_outside_the_contract(tmp_path):
    record = tmp_path / "host.json"
    record.write_text(json.dumps({"mode": "live", "delivery_paths": {"session_start": {"state": "certified"}, "prompt": {"state": "certified"}}}), encoding="utf-8")
    out = json.loads(run("preflight", "--host-record", str(record)).stdout)
    assert out["delivery"]["state"] == "unavailable" and out["delivery"]["reasons"] == ["host_record_invalid:ValidationError"]


def test_live_runs_refuse_until_preflight_passes(tmp_path):
    for command in ("smoke", "workload", "demonstrate"):
        result = run(command, "--mode", "live", "--out", str(tmp_path / command))
        assert result.returncode == 4, (command, result.stdout, result.stderr)
        assert json.loads(result.stdout)["verdict"] == "unavailable"
        assert not (tmp_path / command / "trials").exists()  # nothing ran, nothing was labeled a live result


def test_operator_token_route_never_bypasses_the_guard(tmp_path, monkeypatch):
    """A host-marked harness gets the guard's refusal (exit 6); the harness never mints a token or clears a marker."""
    from evals import trial

    token = tmp_path / "token.json"
    token.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    ws = tmp_path / "ws"
    trial.copy_seed("ledgerlite", ws)
    with pytest.raises(trial.TrialError) as refused:
        trial.init_installation(ws, "ledgerlite", route="operator_token", token_file=token, mode="scripted")
    assert refused.value.code == "operator_guard_refused" and "host_marker_present" in refused.value.detail
    assert not (ws / ".recalith").exists()
    with pytest.raises(trial.TrialError) as missing:
        trial.init_installation(ws, "ledgerlite", route="operator_token", token_file=None, mode="scripted")
    assert missing.value.code == "operator_token_not_provisioned"
    with pytest.raises(trial.TrialError) as fixture_live:
        trial.init_installation(ws, "ledgerlite", route="test_fixture", token_file=None, mode="live")
    assert fixture_live.value.code == "test_fixture_route_refused"


def test_contaminated_arms_are_never_labeled_no_memory(tmp_path):
    from evals import baselines

    ws, home = tmp_path / "ws", tmp_path / "home"
    ws.mkdir()
    baselines.prepare_home(home)
    clean = baselines.manifest("no_memory", mode="live", ws=ws, home=home, native_memory={"state": "disabled"}, installation=None, agent={})
    assert clean["label"] == "no_memory" and clean["contamination"] == []
    for state in ("not_disableable", "detector_unvalidated", "not_observed"):
        assert baselines.manifest("no_memory", mode="live", ws=ws, home=home, native_memory={"state": state}, installation=None, agent={})["label"] == "contaminated"
    (ws / "CLAUDE.md").write_text("Always use PYTHONPATH=src.\n", encoding="utf-8")
    dirty = baselines.manifest("no_memory", mode="scripted", ws=ws, home=home, native_memory={}, installation=None, agent={})
    assert dirty["label"] == "contaminated" and "inherited_instructions" in dirty["contamination"]
    (ws / "CLAUDE.md").unlink()
    wrong = baselines.manifest("no_memory", mode="scripted", ws=ws, home=home, native_memory={}, installation={"installation_id": "x"}, agent={})
    assert wrong["label"] == "contaminated" and "installation_mismatch" in wrong["contamination"]


def test_report_statistics_are_honest():
    from evals import report

    assert report.wilson(0, 0) is None and report.wilson(3, 3)[1] == 1.0
    assert report.proportion(7, 8)["value"] == 0.875
    flat = report.paired_bootstrap([0.0] * 12)
    assert flat["mean"] == 0.0 and flat["ci_95"] == (0.0, 0.0) and flat["inconclusive"]
    assert report.paired_bootstrap([1.0, 0.0, 0.0]) == report.paired_bootstrap([1.0, 0.0, 0.0])  # seeded, reproducible
    assert report.target_met("irrelevant_caution_quiet", 0.0) is True and report.target_met("supported_precision", 0.9) is False and report.target_met("useful_recall", None) is None
    gate = report.gate({"mode": "scripted", "quality_5_1": {"measures": {}}}, {"blockers": ["B1"]})
    assert gate["state"] == "blocked" and gate["superiority_claim"] is False


def test_workload_days_are_the_seeded_templates():
    from evals import workload

    for project, make in workload.GENERATORS.items():
        day = make()
        assert day == workload.load_day(project), f"{project}: regenerate with `python evals/workload.py generate` and review the diff"
        assert day["synthetic"] and day["duration_seconds"] == 8 * 3600 and max(e["at"] for e in day["events"]) < day["duration_seconds"]
        assert [e["at"] for e in day["events"]] == sorted(e["at"] for e in day["events"])


def test_scripted_smoke_run_writes_labeled_trials(tmp_path):
    result = run("smoke", "--out", str(tmp_path), "--scenario", "smoke-L1-ledgerlite-test-command", "--no-native-memory-observation")
    assert result.returncode == 0, result.stderr
    trials = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in (tmp_path / "trials").glob("*.json")}
    assert set(trials) == {"smoke-L1-ledgerlite-test-command.candidate.json", "smoke-L1-ledgerlite-test-command.no_memory.json"}
    cand, base = trials["smoke-L1-ledgerlite-test-command.candidate.json"], trials["smoke-L1-ledgerlite-test-command.no_memory.json"]
    assert cand["mode"] == "scripted" and cand["manifest"]["candidate"]["agent"]["live"] is False
    assert cand["manifest"]["candidate"]["recalith_installation"]["init"]["route"] == "test_fixture"
    assert base["manifest"]["no_memory"]["label"] == "no_memory" and base["manifest"]["no_memory"]["recalith_installation"] is None
    assert cand["outcomes"]["repeated_mistakes"] == 0 and base["outcomes"]["repeated_mistakes"] == 1  # the mistake learned in A
    report = run("report", str(tmp_path))
    assert report.returncode == 8  # the gate is never passed by a scripted run
    built = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert built["counts_toward_gate"] is False and built["gate"]["state"] == "blocked" and built["gate"]["superiority_claim"] is False
    assert {"budget_exhaustion", "task_over_fragmentation", "delivery_visibility", "false_suppression", "same_session_learning_latency", "curation_throughput", "evidence_strength_distribution"} <= set(built["operational_5_2"])


def test_release_checklist_and_dependency_inventory_are_consistent():
    import build_release
    import release_checklist

    problems, summary = release_checklist.check(ROOT / "docs" / "release" / "claude_preview_checklist.json")
    assert problems == [] and summary["verdict"] == "blocked"
    tracked = json.loads((ROOT / "docs" / "release" / "DEPENDENCIES.json").read_text(encoding="utf-8"))
    assert build_release.dependency_inventory() == tracked
