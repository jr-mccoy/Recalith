"""Task 18 (preview): the acceptance manifest and the evaluation harness (ACCEPTANCE_TESTS §2.1, §5–§8; decision 0020).

``test_acceptance_manifest_covers_A01_through_A73_by_profile`` checks the
coverage manifest against ACCEPTANCE_TESTS itself (the 73 IDs, the six preview
exclusions and the §2.1 partial variants are parsed from the document) and
that every required preview variant names executable tests that exist.
``test_replay_cannot_see_future_evidence`` runs real scripted trials through
the harness and proves no trial's retrieval store holds evidence from a later
session, and that the harness refuses to run a session over a contaminated
store.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT, ROOT / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

MANIFEST = json.loads((ROOT / "tests" / "coverage_manifest.json").read_text(encoding="utf-8"))
DOC = (ROOT / "docs" / "ACCEPTANCE_TESTS.md").read_text(encoding="utf-8")
STATUSES = {"pending", "in_progress", "passed", "failed", "unavailable"}
PLATFORMS = {"linux", "macos", "windows"}
TASKS = {"0", "0b", "1", "2", "3", "3b", "4", "5", "6", "7", "8", "9", "10", "11", "12a", "12b", "13", "14", "15", "16", "17", "18"}


def _section_2_1() -> tuple[set[str], set[str]]:
    """(excluded IDs, IDs with partial variants) as ACCEPTANCE_TESTS §2.1 states them."""
    body = DOC.split("### 2.1 Release-profile coverage", 1)[1].split("\n## ", 1)[0]
    excluded = set(re.findall(r"A\d\d", re.search(r"all A01–A73 except ([^.]+)\.", body).group(1)))
    partial: set[str] = set()
    for line in body.splitlines():
        if line.startswith("| A"):
            partial |= set(re.findall(r"A\d\d", line.split("|")[1]))
    return excluded, partial


TASK_TOKEN = re.compile(r"\b(0b|3b|12a|12b|1[0-8]|[0-9])\b")


def _plan_ownership() -> dict[str, set[str]]:
    """IMPLEMENTATION_PLAN "Added-case ownership": each ID's owning tasks, per-ID "also" clauses included."""
    plan = (ROOT / "docs" / "IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")
    body = plan.split("## Added-case ownership", 1)[1].split("\n## ", 1)[0]
    out: dict[str, set[str]] = {}
    for line in body.splitlines():
        if not line.startswith("| A"):
            continue
        ids_cell, owner_cell = line.split("|")[1], line.split("|")[2]
        base, _, notes = owner_cell.partition("(")
        for cid in re.findall(r"A\d\d", ids_cell):
            out[cid] = set(TASK_TOKEN.findall(base))
        for cid, extra in re.findall(r"(A\d\d) also ([^;)]+)", notes):
            out[cid] |= set(TASK_TOKEN.findall(extra))
    return out


def _functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names |= {f"{node.name}::{n.name}" for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return names


def test_acceptance_manifest_covers_A01_through_A73_by_profile():
    cases = {c["id"]: c for c in MANIFEST["cases"]}
    documented = set(re.findall(r"^\| (A\d\d) \|", DOC, re.M))
    assert sorted(cases) == sorted(documented) == [f"A{i:02d}" for i in range(1, 74)]
    excluded, partial = _section_2_1()
    assert excluded == {"A38", "A39", "A42", "A46", "A55", "A71"}
    preview = {cid for cid, c in cases.items() if c["in_preview"]}
    assert len(preview) == 67 and set(cases) - preview == excluded
    problems: list[str] = []
    for cid, owners in sorted(_plan_ownership().items()):
        missing = owners - set(cases[cid]["owning_tasks"])
        if missing:
            problems.append(f"{cid}: owning tasks lack {sorted(missing)} named by IMPLEMENTATION_PLAN's added-case ownership")
    cache: dict[Path, set[str]] = {}
    for cid, case in sorted(cases.items()):
        # Every entry records profile, capability, variant, owning task, platform and status.
        if not case.get("capability") or not case.get("owning_tasks") or not set(case["owning_tasks"]) <= TASKS:
            problems.append(f"{cid}: capability/owning task missing")
        names = [v["variant"] for v in case["variants"]]
        expected = ["full"] if cid in excluded else ["preview", "full_only"] if cid in partial else ["complete"]
        if names != expected:
            problems.append(f"{cid}: variants {names} != §2.1 {expected}")
        for v in case["variants"]:
            tag = f"{cid}/{v['variant']}"
            if not v.get("profiles") or not set(v["profiles"]) <= {"claude_preview", "full"} or v.get("status") not in STATUSES or set(v.get("platforms") or []) != PLATFORMS:
                problems.append(f"{tag}: profile/status/platform not recorded")
            full_only = "claude_preview" not in v["profiles"]
            if full_only:
                if v["status"] == "passed":
                    problems.append(f"{tag}: a full-only variant is marked passed")
                if v.get("preview_status") != "unavailable" or not v.get("unavailable_reason"):
                    problems.append(f"{tag}: a full-only variant is not explicitly unavailable in preview")
            if cid in excluded and v["status"] not in ("pending", "unavailable"):
                problems.append(f"{tag}: an excluded case must be pending or unavailable")
            if not full_only:
                if not v.get("tests"):
                    problems.append(f"{tag}: a required preview variant maps to no executable test")
                for test in v.get("tests", []):
                    file, _, name = test.partition("::")
                    path = ROOT / file
                    if not path.exists():
                        problems.append(f"{tag}: {file} does not exist")
                        continue
                    found = cache.setdefault(path, _functions(path))
                    if name and re.sub(r"\[.*\]$", "", name) not in found:
                        problems.append(f"{tag}: {test} is not a test in that file")
            if v.get("requires_live_host") and v["status"] == "passed" and not v.get("live_evidence"):
                problems.append(f"{tag}: a live variant passed without live evidence")
    assert not problems, "\n".join(problems)


# --------------------------------------------------------------------------
# No future evidence (ACCEPTANCE_TESTS §5: "No future-session evidence enters an earlier session's retrieval store")

EVT = re.compile(r"evt_[0-9a-f]{64}")


def _events(ws: Path) -> dict[str, tuple[str, str]]:
    from evals import trial
    from recalith.storage import db

    with db.open_store(trial.context(ws), readonly=True) as store, store.read() as view:
        # Delivery receipts are bookkeeping, never evidence (their capture time is the hook's wall clock).
        rows = view.execute("SELECT e.event_id, e.recorded_at, s.host_session_id FROM events e JOIN sessions s ON s.session_id = e.session_id WHERE e.kind != 'memory_delivered'").fetchall()
    return {eid: (at, host) for eid, at, host in rows}


def test_replay_cannot_see_future_evidence(tmp_path):
    from evals import agent, trial, workload

    # 1. A smoke trial: a learning session, an overlay that changes evidence, then a later session (R1: A, C).
    sid = "smoke-R1-fieldnotes-check-env-fixed"
    record = trial.run_trial(sid, "candidate", tmp_path / "trials")
    assert record.get("error") is None, record
    checks = record["horizon_checks"]
    assert [c["before"] for c in checks] == ["A", "C"] and checks[0]["host_sessions"] == 0 and checks[1]["host_sessions"] == 1
    ws = tmp_path / "trials" / sid / "candidate" / "ws"
    events = _events(ws)
    order = [s["host_session_id"] for s in record["sessions"]]
    assert max(at for at, host in events.values() if host == order[0]) < min(at for at, host in events.values() if host == order[1])
    # Every event a delivered packet cites was captured before that delivery, in that session or an earlier one.
    cited = 0
    for k, session in enumerate(record["sessions"]):
        for delivery in session["deliveries"]:
            for eid in EVT.findall(delivery["context"] or ""):
                at, host = events[eid]
                assert at <= delivery["at"] and host in order[: k + 1], (session["name"], delivery["purpose"], eid)
                cited += 1
    assert cited, "no delivered packet cited evidence: the check would be vacuous"
    # 2. The harness refuses a session over a store that already holds a later session's evidence.
    root = tmp_path / "contaminated"
    trial.copy_seed("fieldnotes", root)
    trial.init_installation(root, "fieldnotes", route="test_fixture", token_file=None, mode="scripted")
    trial.controlled_manifest(root)
    later = agent.Clock("2026-11-02T15:00:00.000000Z")  # a session from later in the day, captured ahead of the trial clock
    (tmp_path / "home").mkdir()
    agent.run_scripted("r1", "A", ["Run the checks."], root, agent.HookBridge(root, tmp_path / "home", later), seed="later")
    with pytest.raises(trial.TrialError) as refused:
        trial.evidence_horizon(root, allowed_host_sessions=set(), not_after=trial.START)
    assert refused.value.code == "future_evidence"
    # 3. A workload day replays every event at its recorded time: before each session the store holds only earlier sessions.
    day = workload.run_day("household", tmp_path / "days")
    assert day.get("error") is None, day
    sessions = set(workload.load_day("household")["gold"]["task_of_session"])
    assert day["horizon"] == {"checks": len(sessions), "violations": 0, "examples": []}
