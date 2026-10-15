"""The 12 non-held-out smoke scenarios and their oracles (Task 1; ACCEPTANCE_TESTS §6.1).

Each oracle must fail on the untouched seed (the task was not done) and pass on a
reference solution, so a smoke run cannot pass vacuously.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "evals" / "scenarios" / "smoke"
sys.path.insert(0, str(ROOT / "evals" / "oracles"))

import smoke  # noqa: E402

SCENARIOS = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(SMOKE.glob("smoke-*.json"))}


def test_twelve_scenarios_four_per_category_across_three_projects():
    assert len(SCENARIOS) == 12
    cats = [s["category"] for s in SCENARIOS.values()]
    assert {c: cats.count(c) for c in set(cats)} == {"learning": 4, "revision": 4, "control": 4}
    assert {s["project"] for s in SCENARIOS.values()} == {"ledgerlite", "fieldnotes", "household"}
    assert all(s["held_out"] is False for s in SCENARIOS.values())
    assert not any((ROOT / "evals" / "scenarios" / "held_out").glob("*.json")), "held-out scenarios need independent authorship"


@pytest.mark.parametrize("sid", sorted(SCENARIOS))
def test_scenario_shape(sid):
    s = SCENARIOS[sid]
    assert s["scenario_schema"] == 1 and s["id"] == sid
    assert (ROOT / "evals" / "projects" / s["project"]).is_dir()
    assert s["oracle"]["check"] in smoke.CHECKS
    assert s["oracle"]["session"] in {x["name"] for x in s["sessions"]}
    gold = s["gold"]
    for key in ("exact_observations", "supported_lessons", "acceptable_uncertainty", "prohibited_generalizations", "expected_retrieval_points", "quiet"):
        assert key in gold, key
    assert gold["quiet"] == (s["category"] == "control")
    for sess in s["sessions"]:
        for target, ref in sess["overlay_files"].items():
            assert ref.startswith("@file:") and (SMOKE / "overlays" / ref[6:]).exists(), ref
            assert not Path(target).is_absolute() and ".." not in Path(target).parts


def materialize(tmp: Path, sid: str) -> Path:
    s = SCENARIOS[sid]
    ws = tmp / "ws"
    shutil.copytree(ROOT / "evals" / "projects" / s["project"], ws, ignore=shutil.ignore_patterns("__pycache__"))
    for sess in s["sessions"]:
        for target, ref in sess["overlay_files"].items():
            (ws / target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SMOKE / "overlays" / ref[6:], ws / target)
        if sess["name"] == s["oracle"]["session"]:
            break
    return ws


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, (path, old)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def act(session: str, command: str, code: int = 0) -> dict:
    return {"session": session, "tool": "Bash", "command": command, "exit_code": code}


# Reference solutions: what a correct agent leaves behind.

LEDGER = "src/ledgerlite/__init__.py"


def ref_l1(ws: Path) -> list[dict]:
    edit(ws / LEDGER, "    def balance(", "    def close(self, name: str) -> None:\n        if self.accounts[name] != 0:\n            raise ValueError(f\"account {name} has a nonzero balance\")\n        del self.accounts[name]\n\n    def balance(")
    edit(ws / "tests/test_ledger.py", "\n\nif __name__", "\n\n    def test_close_requires_zero_balance(self):\n        ledger = Ledger()\n        ledger.open(\"a\")\n        ledger.open(\"b\")\n        ledger.transfer(\"a\", \"b\", \"1\")\n        with self.assertRaises(ValueError):\n            ledger.close(\"a\")\n\n\nif __name__")
    return [act("B", "PYTHONPATH=src python -m unittest discover -s tests")]


def ref_l2(ws: Path) -> list[dict]:
    edit(ws / "fieldnotes/cli.py", '    if args[0] == "list":', '    if args[0] == "export":\n        for note in store.load():\n            print(f"{note[\'created\']}: {note[\'text\']}")\n        return 0\n    if args[0] == "list":')
    return [act("B", "NOTES_HOME=/tmp/n python tools/check.py")]


def ref_l3(ws: Path) -> list[dict]:
    (ws / "groceries.csv").write_text("item,cost_usd\nproduce,180\npantry,140\nprotein,160\ndairy,60\n", encoding="utf-8")
    (ws / "meal-plan.md").write_text("# Meal plan\n\nGroceries total $540, under the $600 monthly budget.\n", encoding="utf-8")
    return []


def ref_l4(ws: Path) -> list[dict]:
    (ws / "src/ledgerlite/money.py").write_text("from decimal import Decimal\n\n\ndef parse(value):\n    amount = value if isinstance(value, Decimal) else Decimal(value)\n    if amount <= 0:\n        raise ValueError(\"amount must be positive\")\n    return amount\n", encoding="utf-8")
    edit(ws / LEDGER, "    def transfer(self, source: str, target: str, amount: str) -> None:\n        value = Decimal(amount)\n        if value <= 0:\n            raise ValueError(\"amount must be positive\")\n", "    def transfer(self, source: str, target: str, amount) -> None:\n        from .money import parse\n\n        value = parse(amount)\n")
    return []


def ref_r1(ws: Path) -> list[dict]:
    return [act("C", "python tools/check.py")]


def ref_r2(ws: Path) -> list[dict]:
    return [act("C", "python -m unittest discover -s tests -t .")]


def ref_r3(ws: Path) -> list[dict]:
    (ws / "groceries.csv").write_text("item,cost_usd\nproduce,190\npantry,150\nprotein,180\ndinner party,160\n", encoding="utf-8")
    (ws / "meal-plan.md").write_text("# Meal plan\n\nLimit used: $700 per month (corrected from the previous $600).\nTotal: $680.\n", encoding="utf-8")
    return []


def ref_r4(ws: Path) -> list[dict]:
    (ws / "tools/count_notes.py").write_text("import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parents[1]))\nfrom fieldnotes import store\n\nprint(len(store.load()))\n", encoding="utf-8")
    return []


def ref_c1(ws: Path) -> list[dict]:
    edit(ws / LEDGER, "    def total(self) -> Decimal:\n", "    def total(self) -> Decimal:\n        \"\"\"Sum of all account balances.\"\"\"\n")
    return []


def ref_c2(ws: Path) -> list[dict]:
    edit(ws / "fieldnotes/cli.py", '    if args[0] == "list":', '    if args[0] == "count":\n        print(len(store.load()))\n        return 0\n    if args[0] == "delete" and len(args) == 2:\n        notes = store.load()\n        del notes[int(args[1])]\n        store.notes_path().write_text(__import__("json").dumps(notes), encoding="utf-8")\n        return 0\n    if args[0] == "list":')
    return []


def ref_c3(ws: Path) -> list[dict]:
    (ws / "utilities-plan.md").write_text("# Utilities plan\n\nEstimate for next month: $235 (electricity 115, water 42, internet 60).\n", encoding="utf-8")
    return []


def ref_c4(ws: Path) -> list[dict]:
    return [act("B", "NOTES_HOME=/tmp/n python tools/check.py")]


REFERENCES = {"l1": ref_l1, "l2": ref_l2, "l3": ref_l3, "l4": ref_l4, "r1": ref_r1, "r2": ref_r2, "r3": ref_r3, "r4": ref_r4, "c1": ref_c1, "c2": ref_c2, "c3": ref_c3, "c4": ref_c4}


@pytest.mark.parametrize("sid", sorted(SCENARIOS))
def test_oracle_fails_untouched_seed_and_passes_reference(tmp_path, sid):
    s = SCENARIOS[sid]
    check, session = s["oracle"]["check"], s["oracle"]["session"]
    seed = materialize(tmp_path / "seed", sid)
    untouched = smoke.judge(check, seed, [], session)
    assert untouched["passed"] is False, untouched
    solved = materialize(tmp_path / "solved", sid)
    actions = REFERENCES[check](solved)
    result = smoke.judge(check, solved, actions, session)
    assert result["passed"] is True, result


def test_cross_project_leak_is_detected(tmp_path):
    ws = materialize(tmp_path, "smoke-C4-cross-project-near-match")
    actions = [act("B", "PYTHONPATH=src python -m unittest discover -s tests", 1), act("B", "NOTES_HOME=/tmp/n python tools/check.py")]
    result = smoke.judge("c4", ws, actions, "B")
    assert result["passed"] is False and result["metrics"]["cross_project_leak_commands"] == 1


def test_repeated_mistakes_are_counted(tmp_path):
    ws = materialize(tmp_path, "smoke-L1-ledgerlite-test-command")
    ref_l1(ws)
    actions = [act("B", "python -m unittest", 5), act("B", "python -m unittest discover -s tests", 1), act("B", "PYTHONPATH=src python -m unittest discover -s tests")]
    assert smoke.judge("l1", ws, actions, "B")["metrics"]["repeated_test_command_failures"] == 2
