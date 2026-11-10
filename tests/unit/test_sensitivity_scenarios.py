# SPDX-License-Identifier: GPL-3.0-only
"""The baseline-sensitivity set (decision 0049; audit 2026-11-06 EVAL-2, fix plan item 5.1).

Four scenarios beside the frozen 12, never part of the preview gate. In each, session A corrects a mistake with a fact
the repository does not hold, and the oracle reports ``repeated_named_mistake`` for session B. Each oracle must fail
the untouched seed, pass a correct solution with no repeat, and count the obvious solution as the repeated mistake.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SENSITIVITY = ROOT / "evals" / "scenarios" / "sensitivity"
SMOKE = ROOT / "evals" / "scenarios" / "smoke"
sys.path.insert(0, str(ROOT / "evals" / "oracles"))

import smoke  # noqa: E402

SCENARIOS = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(SENSITIVITY.glob("sens-*.json"))}
KINDS = {"decision_contradicting_the_code", "unwritten_convention", "environmental_fix", "outside_constraint"}


def test_four_scenarios_one_per_kind_beside_the_frozen_twelve():
    assert len(SCENARIOS) == 4
    assert {s["named_mistake"]["kind"] for s in SCENARIOS.values()} == KINDS
    assert {s["project"] for s in SCENARIOS.values()} == {"ledgerlite", "fieldnotes", "household"}
    assert all(s["set"] == "sensitivity" and s["category"] == "learning" and s["held_out"] is False for s in SCENARIOS.values())
    assert not set(SCENARIOS) & {p.stem for p in SMOKE.glob("smoke-*.json")}
    assert len(list(SMOKE.glob("smoke-*.json"))) == 12, "the gate's 12 are frozen (ACCEPTANCE_TESTS §6.1)"


@pytest.mark.parametrize("sid", sorted(SCENARIOS))
def test_scenario_shape(sid):
    s = SCENARIOS[sid]
    assert s["scenario_schema"] == 1 and s["id"] == sid
    assert (ROOT / "evals" / "projects" / s["project"]).is_dir()
    assert s["oracle"]["check"] in smoke.CHECKS and s["oracle"]["session"] == "B"
    assert [x["name"] for x in s["sessions"]] == ["A", "B"]
    assert len(s["sessions"][0]["prompts"]) == 2, "session A: the task, then the user's correction"
    mistake = s["named_mistake"]
    assert mistake["corrected_in"] == "A" and mistake["judged_in"] == "B" and mistake["description"] and mistake["not_in_repository"]
    gold = s["gold"]
    for key in ("exact_observations", "supported_lessons", "acceptable_uncertainty", "prohibited_generalizations", "expected_retrieval_points", "quiet"):
        assert key in gold, key
    assert gold["quiet"] is False and all(lesson["basis"] == "user_declared" for lesson in gold["supported_lessons"])
    for sess in s["sessions"]:
        for target, ref in sess["overlay_files"].items():
            assert ref.startswith("@file:") and (SENSITIVITY / "overlays" / ref[6:]).exists(), ref
            assert not Path(target).is_absolute() and ".." not in Path(target).parts


@pytest.mark.parametrize("sid", sorted(SCENARIOS))
def test_the_recorded_curator_quotes_the_users_own_words(sid):
    sys.path.insert(0, str(ROOT))
    from evals import curator

    prompts = " ".join(p for sess in SCENARIOS[sid]["sessions"] for p in sess["prompts"])
    proposals = curator.SMOKE[sid]
    assert proposals, sid
    for proposal in proposals:
        for match in proposal.evidence:
            assert match.kind == "user_message" and match.contains in prompts and match.quote in prompts, (proposal.key, match.quote)


def materialize(tmp: Path, sid: str) -> Path:
    s = SCENARIOS[sid]
    ws = tmp / "ws"
    shutil.copytree(ROOT / "evals" / "projects" / s["project"], ws, ignore=shutil.ignore_patterns("__pycache__"))
    for sess in s["sessions"]:
        for target, ref in sess["overlay_files"].items():
            (ws / target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SENSITIVITY / "overlays" / ref[6:], ws / target)
    return ws


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, (path, old)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def act(command: str, code: int = 0) -> dict:
    return {"session": "B", "tool": "Bash", "command": command, "exit_code": code}


# Solutions: the correct one, and the obvious one that repeats the mistake session A corrected.

LEDGER = "src/ledgerlite/__init__.py"


def amounts(ws: Path, *, cents: bool) -> list[dict]:
    value = "Decimal(amount) / 100" if cents else "Decimal(amount)"
    edit(ws / LEDGER, "    def balance(", (
        "    def deposit(self, name: str, amount) -> None:\n"
        f"        self.accounts[name] += {value}\n\n"
        "    def withdraw(self, name: str, amount) -> None:\n"
        f"        value = {value}\n"
        "        if self.accounts[name] < value:\n"
        "            raise ValueError(\"would go below zero\")\n"
        "        self.accounts[name] -= value\n\n"
        "    def balance("))
    unit = "250" if cents else "\"2.50\""
    edit(ws / "tests/test_ledger.py", "\n\nif __name__", (
        "\n\n    def test_deposit_and_withdraw(self):\n        ledger = Ledger()\n        ledger.open(\"a\")\n"
        f"        ledger.deposit(\"a\", {unit})\n        ledger.withdraw(\"a\", {unit})\n        self.assertEqual(ledger.balance(\"a\"), 0)\n"
        "\n\nif __name__"))
    return [act("PYTHONPATH=src python -m unittest discover -s tests")]


WEEK = ["Monday: soup", "Tuesday: tacos", "Wednesday: pasta", "Thursday: stir-fry", "Friday: pizza", "Saturday: roast for four (two friends)", "Sunday: salad"]


def meal_plan(ws: Path, *, prices: bool) -> list[dict]:
    text = "# Meal plan\n\n" + "\n".join(f"- {d}" for d in WEEK) + "\n"
    if prices:
        text += "\nEstimated food cost: $155, within the $200 limit.\n"
    else:
        (ws / "groceries.csv").write_text("item,cost_usd\nweek,155\n", encoding="utf-8")
    (ws / "meal-plan.md").write_text(text, encoding="utf-8")
    return []


COUNT = '    if args[0] == "count":\n        print(len(store.load()))\n        return 0\n    if args[0] == "list":'


def one_job(ws: Path, *, pinned: bool) -> list[dict]:
    edit(ws / "fieldnotes/cli.py", '    if args[0] == "list":', COUNT)
    return [act("NOTES_HOME=/tmp/n python tools/check.py" + (" --jobs 1" if pinned else ""))]


def star(ws: Path, *, sidecar: bool) -> list[dict]:
    cli = ws / "fieldnotes/cli.py"
    edit(cli, "import sys\n", "import json\nimport sys\n")
    if sidecar:
        edit(cli, '    if args[0] == "list":', (
            '    if args[0] == "star" and len(args) == 2:\n        created = store.load()[int(args[1])]["created"]\n'
            '        meta_path = store.notes_path().with_name("meta.json")\n'
            '        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}\n'
            '        meta[created] = {"starred": True}\n        meta_path.write_text(json.dumps(meta), encoding="utf-8")\n        return 0\n'
            '    if args[0] == "list":'))
        edit(cli, "        for note in store.load():\n            print(f\"{note['created']}  {note['text']}\")\n", (
            '        meta_path = store.notes_path().with_name("meta.json")\n'
            '        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}\n'
            '        for note in store.load():\n            mark = "* " if note["created"] in meta else ""\n'
            "            print(f\"{mark}{note['created']}  {note['text']}\")\n"))
    else:
        edit(cli, '    if args[0] == "list":', (
            '    if args[0] == "star" and len(args) == 2:\n        notes = store.load()\n        notes[int(args[1])]["starred"] = True\n'
            '        store.notes_path().write_text(json.dumps(notes), encoding="utf-8")\n        return 0\n'
            '    if args[0] == "list":'))
        edit(cli, "        for note in store.load():\n            print(f\"{note['created']}  {note['text']}\")\n", (
            '        for note in store.load():\n            mark = "* " if note.get("starred") else ""\n'
            "            print(f\"{mark}{note['created']}  {note['text']}\")\n"))
    return [act("NOTES_HOME=/tmp/n python tools/check.py")]


SOLUTIONS = {"s1": lambda ws, ok: amounts(ws, cents=ok), "s2": lambda ws, ok: meal_plan(ws, prices=not ok),
             "s3": lambda ws, ok: one_job(ws, pinned=ok), "s4": lambda ws, ok: star(ws, sidecar=ok)}


@pytest.mark.parametrize("sid", sorted(SCENARIOS))
def test_oracle_fails_seed_passes_correct_and_counts_the_obvious_repeat(tmp_path, sid):
    check = SCENARIOS[sid]["oracle"]["check"]
    seed = smoke.judge(check, materialize(tmp_path / "seed", sid), [], "B")
    assert seed["passed"] is False, seed
    ws = materialize(tmp_path / "correct", sid)
    correct = smoke.judge(check, ws, SOLUTIONS[check](ws, True), "B")
    assert correct["passed"] is True and correct["metrics"]["repeated_named_mistake"] == 0, correct
    ws = materialize(tmp_path / "obvious", sid)
    obvious = smoke.judge(check, ws, SOLUTIONS[check](ws, False), "B")
    assert obvious["passed"] is False and obvious["metrics"]["repeated_named_mistake"] == 1, obvious
    assert "oracle_error" not in obvious["checks"], obvious


@pytest.mark.parametrize("command, pinned", [
    ("NOTES_HOME=$(mktemp -d) python tools/check.py --jobs 1", True),
    ("python tools/check.py --jobs=1 2>&1 | tail -5", True),
    ("cd <run>/w && NOTES_HOME=/tmp/x python tools/check.py -j 1", True),
    ("python tools/check.py -j1", True),
    ("python tools/check.py --jobs 12", False),
    ("export NOTES_HOME=$(mktemp -d); python tools/check.py", False),
])
def test_one_job_is_recognized_in_the_spellings_agents_use(command, pinned):
    assert bool(smoke.ONE_JOB.search(command)) is pinned


@pytest.mark.parametrize("line, priced", [
    ("Estimated food cost: $155", True), ("Within the $ 200 limit", True), ("About 40 dollars for Saturday", True), ("total 12.50 USD", True),
    ("- Saturday: roast chicken for 4 people", False), ("Dinner at 7pm", False), ("- Monday: 2 lb lentil soup", False),
])
def test_a_price_is_any_dollar_amount_and_nothing_else(line, priced):
    assert bool(smoke.PRICE.search(line)) is priced


def test_sensitivity_ids_never_match_the_gates_glob():
    assert all(not re.match(r"smoke-", sid) for sid in SCENARIOS)
