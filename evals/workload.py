"""Workload days: three eight-hour activity days, one per project (ACCEPTANCE_TESTS §5.2; decision 0020).

    python evals/workload.py generate        # (re)write evals/workload/days/*.json from the seeded templates
    python evals/run.py workload --out DIR   # replay them (scripted mode: recorded curator)

Each day file is a **recorded event timeline**: sessions with their prompts and
tool calls, each tool call with its recorded command, exit code and output, at
fixed offsets from the day's start (08:00 UTC), plus gold task labels. The
days are synthetic and representative, written from seeded templates by the
repository's coding agent; they are not recorded real sessions.

Replay feeds every event through the real stdlib hook path at its recorded
time (``agent.HookBridge`` with the virtual capture clock) and runs the
installation's real worker on the same virtual clock between events, so
deterministic scheduling (polling, debounce, quiet windows) is accelerated
while every job still goes through the real queue, leases and **default
budgets**. The UTC budget day is never reset inside a day, nothing is
extrapolated from fresh-budget trials, and an increased-budget run would be a
separately labeled variant (none is run here). In ``live`` mode the model lane
is the installation's own certified route (decision 0028: certified for that
installation by ``tools/probe_provider.py --route-out``, gated by the
production isolation recheck), so calls, latency and usage are real; the
scripted mode answers with the recorded curator, labeled.
"""

from __future__ import annotations

import datetime as _dt
import json
import random
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DAYS = ROOT / "evals" / "workload" / "days"
PROJECTS = ("ledgerlite", "fieldnotes", "household")
DAY_START = {"ledgerlite": "2026-11-03T08:00:00.000000Z", "fieldnotes": "2026-11-04T08:00:00.000000Z", "household": "2026-11-05T08:00:00.000000Z"}
DAY_SECONDS = 8 * 3600
POLL_SECONDS = 5

LEDGER_FAIL = "E\n======================================================================\nERROR: test_ledger (unittest.loader._FailedTest.test_ledger)\n----------------------------------------------------------------------\nImportError: Failed to import test module: test_ledger\nTraceback (most recent call last):\n  File \"tests/test_ledger.py\", line 3, in <module>\n    from ledgerlite import Ledger\nModuleNotFoundError: No module named 'ledgerlite'\n\n----------------------------------------------------------------------\nRan 1 test in 0.000s\n\nFAILED (errors=1)"
LEDGER_OK = "..{extra}\n----------------------------------------------------------------------\nRan {n} tests in 0.001s\n\nOK"
NOTES_FAIL = "Traceback (most recent call last):\n  File \"tools/check.py\", line 23, in main\n    notes_home = os.environ[\"NOTES_HOME\"]\nKeyError: 'NOTES_HOME'"
NOTES_OK = "using NOTES_HOME=/tmp/fieldnotes-check\n..{extra}\n----------------------------------------------------------------------\nRan {n} tests in 0.002s\n\nOK"
ASSERT_FAIL = "F\n======================================================================\nFAIL: {test} (tests.{module}.{cls}.{test})\n----------------------------------------------------------------------\nTraceback (most recent call last):\n  File \"tests/{module}.py\", line 14, in {test}\n    self.assertEqual({lhs}, {rhs})\nAssertionError: {lhs} != {rhs}\n\n----------------------------------------------------------------------\nRan {n} tests in 0.001s\n\nFAILED (failures=1)"


# --------------------------------------------------------------------------
# Generation (seeded templates)


class DayWriter:
    def __init__(self, project: str, seed: int) -> None:
        self.project = project
        self.rng = random.Random(seed)
        self.events: list[dict[str, Any]] = []
        self.tasks: dict[str, str] = {}
        self.t = 0

    def session(self, name: str, at_minutes: float, task: str, prompt: str) -> None:
        self.t = int(at_minutes * 60)
        self.tasks[name] = task
        self._add(name, "start")
        self._add(name, "prompt", text=prompt)

    def _add(self, session: str, kind: str, **fields: Any) -> None:
        self.events.append({"at": self.t, "session": session, "kind": kind, **fields})
        self.t += self.rng.randint(8, 70)

    def bash(self, session: str, command: str, code: int, output: str, env: dict[str, str] | None = None) -> None:
        self._add(session, "bash", command=command, exit_code=code, output=output)

    def read(self, session: str, path: str, content: str = "...") -> None:
        self._add(session, "read", path=path, content=content)

    def edit(self, session: str, path: str, old: str = "pass", new: str = "return None") -> None:
        self._add(session, "edit", path=path, old=old, new=new)

    def write(self, session: str, path: str, content: str) -> None:
        self._add(session, "write", path=path, content=content)

    def compact(self, session: str) -> None:
        self._add(session, "compact")

    def end(self, session: str, reply: str = "Done.") -> None:
        self._add(session, "stop", reply=reply)

    def day(self) -> dict[str, Any]:
        gold_tasks = sorted(set(self.tasks.values()))
        return {"day_schema": 1, "project": self.project, "start": DAY_START[self.project], "duration_seconds": DAY_SECONDS, "synthetic": True,
                "authorship": "synthetic representative day from seeded templates (evals/workload.py), coding agent; not a recorded real session",
                "gold": {"tasks": len(gold_tasks), "task_of_session": self.tasks}, "events": self.events}


def _ledger_ok(rng: random.Random) -> str:
    n = rng.randint(2, 9)
    return LEDGER_OK.format(extra="." * (n - 2), n=n)


def ledgerlite_day() -> dict[str, Any]:
    d = DayWriter("ledgerlite", 11)
    plain, fixed = "python -m unittest discover -s tests", "PYTHONPATH=src python -m unittest discover -s tests"
    d.session("S1", 5, "test-setup", "Run the ledgerlite unit tests and get them running.")
    d.bash("S1", plain, 1, LEDGER_FAIL)
    d.read("S1", "README.md")
    d.bash("S1", fixed, 0, _ledger_ok(d.rng))
    d.end("S1", "Tests run with PYTHONPATH=src.")
    d.session("S2", 40, "close-account", "Add Ledger.close(name) that refuses nonzero balances, with a test.")
    for path in ("src/ledgerlite/__init__.py", "tests/test_ledger.py"):
        d.read("S2", path)
    d.edit("S2", "src/ledgerlite/__init__.py")
    d.edit("S2", "tests/test_ledger.py")
    d.bash("S2", plain, 1, LEDGER_FAIL)  # a repeated mistake across sessions
    d.bash("S2", fixed, 1, ASSERT_FAIL.format(test="test_close", module="test_ledger", cls="LedgerTests", lhs="Decimal('1')", rhs="Decimal('0')", n=3))
    d.edit("S2", "src/ledgerlite/__init__.py")
    d.bash("S2", fixed, 0, _ledger_ok(d.rng))
    d.end("S2")
    d.session("S3", 95, "close-account", "Continue with close: document it and run the suite again.")
    d.read("S3", "src/ledgerlite/__init__.py")
    d.edit("S3", "src/ledgerlite/__init__.py")
    d.bash("S3", fixed, 0, _ledger_ok(d.rng))
    d.end("S3")
    d.session("S4", 140, "money-module", "Add src/ledgerlite/money.py with parse(value) -> Decimal rejecting non-positive values, plus tests.")
    d.write("S4", "src/ledgerlite/money.py", "from decimal import Decimal\n")
    d.write("S4", "tests/test_money.py", "import unittest\n")
    for _ in range(3):
        d.bash("S4", fixed, 1, ASSERT_FAIL.format(test="test_parse_rejects_zero", module="test_money", cls="MoneyTests", lhs="None", rhs="ValueError", n=4))
        d.edit("S4", "src/ledgerlite/money.py")
    d.bash("S4", fixed, 0, _ledger_ok(d.rng))
    d.end("S4")
    d.session("S5", 200, "transfer-refactor", "Refactor Ledger.transfer to use money.parse; keep the suite green. This will be a long session.")
    for i in range(30):
        d.read("S5", ["src/ledgerlite/__init__.py", "src/ledgerlite/money.py", "tests/test_ledger.py"][i % 3])
        if i % 4 == 0:
            d.edit("S5", "src/ledgerlite/__init__.py")
        if i % 6 == 0:
            d.bash("S5", fixed, 0 if i % 12 else 1, _ledger_ok(d.rng) if i % 12 else ASSERT_FAIL.format(test="test_transfer", module="test_ledger", cls="LedgerTests", lhs="Decimal('2')", rhs="Decimal('3')", n=5))
        if i == 18:
            d.compact("S5")
    d.bash("S5", fixed, 0, _ledger_ok(d.rng))
    d.end("S5")
    d.session("S6", 300, "decimal-decision", "Decision: ledger amounts are always Decimal; never use float anywhere in ledgerlite.")
    d.read("S6", "src/ledgerlite/__init__.py")
    d.bash("S6", "grep -rn float src", 1, "")
    d.end("S6", "No float usage found.")
    d.session("S7", 345, "readme", "Update the README with the test command and a usage example.")
    d.read("S7", "README.md")
    d.edit("S7", "README.md", "ledger library", "ledger library. Run tests with PYTHONPATH=src.")
    d.bash("S7", plain, 1, LEDGER_FAIL)
    d.bash("S7", fixed, 0, _ledger_ok(d.rng))
    d.end("S7")
    d.session("S8", 400, "balance-report", "Add Ledger.report() returning sorted (name, balance) pairs, test first.")
    d.write("S8", "tests/test_report.py", "import unittest\n")
    d.bash("S8", fixed, 1, ASSERT_FAIL.format(test="test_report", module="test_report", cls="ReportTests", lhs="[]", rhs="[('a', 0)]", n=6))  # expected red (TDD)
    d.edit("S8", "src/ledgerlite/__init__.py")
    d.bash("S8", fixed, 0, _ledger_ok(d.rng))
    d.end("S8")
    d.session("S9", 450, "balance-report", "Polish report(): handle empty ledgers and rerun the tests.")
    d.edit("S9", "src/ledgerlite/__init__.py")
    d.bash("S9", fixed, 0, _ledger_ok(d.rng))
    d.end("S9")
    return d.day()


def fieldnotes_day() -> dict[str, Any]:
    d = DayWriter("fieldnotes", 22)
    plain, fixed = "python tools/check.py", "NOTES_HOME=/tmp/notes python tools/check.py"

    def ok() -> str:
        n = d.rng.randint(1, 6)
        return NOTES_OK.format(extra="." * max(0, n - 2), n=n)

    d.session("S1", 10, "checks", "Run the project checks with python tools/check.py and get them passing.")
    d.bash("S1", plain, 1, NOTES_FAIL)
    d.read("S1", "tools/check.py")
    d.bash("S1", fixed, 0, ok())
    d.end("S1", "Checks need NOTES_HOME.")
    d.session("S2", 55, "iso-dates", "Decision for this project: every printed date is ISO-8601. Check how list prints dates.")
    d.read("S2", "fieldnotes/cli.py")
    d.read("S2", "fieldnotes/store.py")
    d.end("S2")
    d.session("S3", 100, "export", "Add an export command printing DATE: TEXT per note, with a unit test.")
    d.read("S3", "fieldnotes/cli.py")
    d.edit("S3", "fieldnotes/cli.py")
    d.write("S3", "tests/test_export.py", "import unittest\n")
    d.bash("S3", plain, 1, NOTES_FAIL)
    d.bash("S3", fixed, 1, ASSERT_FAIL.format(test="test_export", module="test_export", cls="ExportTests", lhs="'Jan 02: a'", rhs="'2026-01-02: a'", n=3))
    d.edit("S3", "fieldnotes/cli.py")
    d.bash("S3", fixed, 0, ok())
    d.end("S3")
    d.session("S4", 160, "delete", "Using TDD add a delete INDEX command: write the failing test first.")
    d.write("S4", "tests/test_delete.py", "import unittest\n")
    d.bash("S4", fixed, 1, ASSERT_FAIL.format(test="test_delete", module="test_delete", cls="DeleteTests", lhs="2", rhs="0", n=4))
    d.edit("S4", "fieldnotes/cli.py")
    d.bash("S4", fixed, 0, ok())
    d.end("S4")
    d.session("S5", 210, "storage-jsonl", "Move storage to notes.jsonl, one JSON object per line, keeping load/add working. Long session.")
    for i in range(36):
        d.read("S5", ["fieldnotes/store.py", "fieldnotes/cli.py", "tests/test_store.py"][i % 3])
        if i % 3 == 1:
            d.edit("S5", "fieldnotes/store.py")
        if i % 5 == 0:
            d.bash("S5", fixed, 0 if i % 10 else 1, ok() if i % 10 else ASSERT_FAIL.format(test="test_roundtrip", module="test_store", cls="StoreTests", lhs="[]", rhs="[{'text': 'a'}]", n=5))
        if i == 20:
            d.compact("S5")
    d.end("S5")
    d.session("S6", 330, "count", "Add a count command and run the checks.")
    d.edit("S6", "fieldnotes/cli.py")
    d.bash("S6", plain, 1, NOTES_FAIL)
    d.bash("S6", fixed, 0, ok())
    d.end("S6")
    d.session("S7", 390, "line-length", "The style check complains about long lines; fix them.")
    d.bash("S7", fixed, 1, "fieldnotes/cli.py:41: line longer than 100 characters\n" + ok())
    d.edit("S7", "fieldnotes/cli.py")
    d.bash("S7", fixed, 0, ok())
    d.end("S7")
    d.session("S8", 445, "count", "Make count print 0 for an empty store and rerun checks.")
    d.edit("S8", "fieldnotes/cli.py")
    d.bash("S8", fixed, 0, ok())
    d.end("S8")
    return d.day()


def household_day() -> dict[str, Any]:
    d = DayWriter("household", 33)
    d.session("S1", 15, "grocery-budget", "For my household planning: keep the grocery budget under $600 per month. Add a groceries row to budget.csv.")
    d.read("S1", "budget.csv", "category,monthly_limit_usd,notes\nrent,1850,fixed\n")
    d.edit("S1", "budget.csv", "eating_out,150,", "eating_out,150,\ngroceries,600,")
    d.end("S1")
    d.session("S2", 70, "meal-plan", "Draft next month's grocery list in groceries.csv and summarize it in meal-plan.md.")
    d.read("S2", "meal-plan.md", "# Meal plan\n\nNo plan yet for next month.\n")
    d.write("S2", "groceries.csv", "item,cost_usd\nproduce,180\npantry,140\nprotein,160\ndairy,60\n")
    d.write("S2", "meal-plan.md", "# Meal plan\n\nGroceries total $540.\n")
    d.bash("S2", "python -c \"import csv;print(sum(float(r['cost_usd']) for r in csv.DictReader(open('groceries.csv'))))\"", 0, "540.0")
    d.end("S2")
    d.session("S3", 130, "utilities", "Electricity went up in September in utilities-log.csv. Brainstorm why; I have not checked anything.")
    d.read("S3", "utilities-log.csv", "month,electricity_usd,water_usd,internet_usd\n2026-09,131,42,60\n")
    d.end("S3", "Possibly cooling; unverified.")
    d.session("S4", 190, "trip", "Compare the two trip ideas in trip-ideas.md by cost and write trip-plan.md.")
    d.read("S4", "trip-ideas.md", "# Trip ideas\n")
    d.bash("S4", "python tools/cost.py trip-ideas.md", 2, "python: can't open file 'tools/cost.py': [Errno 2] No such file or directory")
    d.write("S4", "trip-plan.md", "# Trip plan\n\nCoast weekend: $420.\n")
    d.end("S4")
    d.session("S5", 260, "grocery-budget", "Correction: the grocery budget is now $700 per month, not $600. Update budget.csv.")
    d.read("S5", "budget.csv", "groceries,600,\n")
    d.edit("S5", "budget.csv", "groceries,600,", "groceries,700,")
    d.end("S5")
    d.session("S6", 320, "meal-plan", "Redo the grocery list for a month with a dinner party within the budget.")
    d.read("S6", "groceries.csv", "item,cost_usd\n")
    d.write("S6", "groceries.csv", "item,cost_usd\nproduce,190\npantry,150\nprotein,180\ndinner party,160\n")
    d.write("S6", "meal-plan.md", "# Meal plan\n\nLimit $700; total $680.\n")
    for _ in range(12):
        d.read("S6", "meal-plan.md", "# Meal plan\n")
    d.compact("S6")
    d.end("S6")
    d.session("S7", 400, "utilities", "Write utilities-plan.md with next month's utilities estimate from utilities-log.csv.")
    d.read("S7", "utilities-log.csv", "month,electricity_usd\n")
    d.write("S7", "utilities-plan.md", "# Utilities plan\n\nEstimate $235.\n")
    d.end("S7")
    d.session("S8", 455, "trip", "Remember for planning: trips are booked only on weekends. Update trip-plan.md accordingly.")
    d.edit("S8", "trip-plan.md", "Coast weekend", "Coast weekend (Sat-Sun)")
    d.end("S8")
    return d.day()


GENERATORS = {"ledgerlite": ledgerlite_day, "fieldnotes": fieldnotes_day, "household": household_day}


def generate() -> list[Path]:
    DAYS.mkdir(parents=True, exist_ok=True)
    out = []
    for project, make in GENERATORS.items():
        path = DAYS / f"{project}.json"
        path.write_text(json.dumps(make(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        out.append(path)
    return out


def load_day(project: str) -> dict[str, Any]:
    return json.loads((DAYS / f"{project}.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Replay


def _plus(moment: str, seconds: float) -> str:
    from recalith.contracts.common import format_utc, parse_utc

    return format_utc(parse_utc(moment) + _dt.timedelta(seconds=seconds))


def _seconds(a: str, b: str) -> float:
    from recalith.contracts.common import parse_utc

    return (parse_utc(b) - parse_utc(a)).total_seconds()


class ReplaySession:
    """One recorded session's payloads through ``agent.Session`` (recorded tool results, no execution)."""

    def __init__(self, name: str, ws: Path, host: Any, seed: str) -> None:
        from evals import agent

        self.s = agent.Session(name, ws, host, seed=seed)

    def event(self, ev: dict[str, Any]) -> None:
        s = self.s
        kind = ev["kind"]
        if kind == "start":
            s.start()
        elif kind == "prompt":
            s.prompt(ev["text"])
        elif kind == "bash":
            code, output = ev["exit_code"], ev["output"]
            response = {"interrupted": False, "isImage": False, "noOutputExpected": False, "stderr": "", "stdout": output[:30_000]}
            if ev["command"].startswith("grep") and code == 1:
                code, response["returnCodeInterpretation"] = 0, "No matches found"  # grep exit 1 arrives as success (decision 0005)
            s._tool("Bash", {"command": ev["command"], "description": "recorded command"}, lambda: (code, output, response), command=ev["command"])  # noqa: SLF001
        elif kind == "read":
            path = str(s.ws / ev["path"])
            content = ev.get("content", "")
            s._tool("Read", {"file_path": path}, lambda: (0, "", {"file": {"content": content, "filePath": path, "numLines": content.count("\n") + 1, "startLine": 1, "totalLines": content.count("\n") + 1}, "type": "text"}), path=ev["path"])  # noqa: SLF001
        elif kind == "edit":
            path = str(s.ws / ev["path"])
            s._tool("Edit", {"file_path": path, "new_string": ev["new"], "old_string": ev["old"], "replace_all": False}, lambda: (0, "", {"filePath": path, "newString": ev["new"], "oldString": ev["old"], "originalFile": ev["old"], "replaceAll": False, "structuredPatch": [], "userModified": False}), path=ev["path"])  # noqa: SLF001
        elif kind == "write":
            path = str(s.ws / ev["path"])
            s._tool("Write", {"content": ev["content"], "file_path": path}, lambda: (0, "", {"content": ev["content"], "filePath": path, "originalFile": None, "structuredPatch": [], "type": "create", "userModified": False}), path=ev["path"])  # noqa: SLF001
        elif kind == "compact":
            base = s._common("PreCompact")  # noqa: SLF001
            s.host.send("PreCompact", {**base, "custom_instructions": None, "prompt_id": s.prompt_id, "trigger": "auto"})
            got = s.host.send("SessionStart", {**s._common("SessionStart"), "source": "compact", "prompt_id": s.prompt_id}, purpose="compact_restore")  # noqa: SLF001
            if got is not None:
                s.delivered.append(got)
            s.host.send("PostCompact", {**s._common("PostCompact"), "compact_summary": "Summary of the session so far.", "prompt_id": s.prompt_id, "trigger": "auto"})  # noqa: SLF001
        elif kind == "stop":
            s.say(ev.get("reply", "Done."))
            s.stop()


def _job(view: Any, job_id: str) -> dict[str, Any] | None:
    row = view.execute("SELECT body FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return None if row is None else json.loads(row[0])


def run_day(project: str, work: Path, *, mode: str = "scripted", live_setup: Any = None) -> dict[str, Any]:
    """Replay one day. ``live``: the installation is initialized with the operator token, its own route is certified live
    (``live.provision`` without a host), and the harness worker's model lane is that route behind the production supervisor
    (its isolation recheck passed), so every call and its usage are real while scheduling stays on the day's virtual clock."""
    from evals import agent, baselines, curator, live, trial
    from recalith.storage import db

    if mode not in ("scripted", "live"):
        return {"kind": "workload_day", "project": project, "mode": mode, "error": "unknown_mode"}
    if mode == "live" and live_setup is None:
        return {"kind": "workload_day", "project": project, "mode": mode, "error": "live_setup_missing"}
    day = load_day(project)
    base = work / project
    if base.exists():
        shutil.rmtree(base)
    ws, home = base / "ws", base / "home"
    home.mkdir(parents=True)
    trial.copy_seed(project, ws)
    baselines.prepare_home(home)
    provisioning = None
    if mode == "live":
        try:
            provisioning = live.provision(ws, project, live_setup, label=f"workload.{project}", host=False)
        except live.LiveError as exc:
            return {"kind": "workload_day", "project": project, "mode": mode, "error": exc.code, "detail": exc.detail, "provisioning_steps": exc.steps}
    else:
        trial.init_installation(ws, project, route="test_fixture", token_file=None, mode="scripted")
    trial.controlled_manifest(ws)
    ctx = trial.context(ws)
    clock = agent.Clock(day["start"])
    calls: list[dict[str, Any]] = []
    plan = curator.RulePlan()
    started_real = time.monotonic()

    def on_call(record: dict[str, Any]) -> None:
        now = clock.now()
        with db.open_store(ctx, readonly=True) as store, store.read() as view:
            job = _job(view, record["job_id"]) or {}
            waiting_declarations = view.execute("SELECT body FROM jobs WHERE kind = 'review_claims' AND state IN ('pending', 'waiting_budget')").fetchall()
        due = job.get("due_at") or now
        record.update(at=now, wait_seconds=max(0.0, _seconds(due, now)), review_priority=job.get("review_priority"), pool=job.get("budget_pool"))
        inversion = False
        if job.get("kind") == "review_claims" and job.get("review_priority") == "ordinary":
            for (body,) in waiting_declarations:
                other = json.loads(body)
                if other.get("review_priority") == "correction_or_declaration" and other.get("due_at", now) <= now:
                    inversion = True
        record["priority_inversion"] = inversion
        calls.append(record)

    supervisor = None
    if mode == "live":
        try:
            backend, supervisor = live.certified_backend(ctx, on_call=on_call)
        except live.LiveError as exc:
            return {"kind": "workload_day", "project": project, "mode": mode, "error": exc.code, "detail": exc.detail, "provisioning": provisioning}
    else:
        backend = curator.RecordedCurator(plan, on_call=on_call)
    drainer = trial.Drainer(ws, clock, backend, provider=supervisor)
    host = agent.HookBridge(ws, home, clock)
    sessions: dict[str, ReplaySession] = {}
    exhausted_at: str | None = None
    pools: set[str] = set()
    horizon: dict[str, Any] = {"checks": 0, "violations": 0, "examples": []}
    record: dict[str, Any] = {"horizon": horizon, "kind": "workload_day", "project": project, "mode": mode, "start": day["start"], "authorship": day["authorship"], "events": len(day["events"]), "budgets": "default (ProjectConfig defaults; UTC day never reset)"}
    if mode == "live":
        record["live"] = {**live_setup.label(), "provisioning": provisioning, "curator": "the installation's certified route (production supervisor, isolation recheck passed); scheduling on the day's virtual clock (ACCEPTANCE_TESTS §5.2)",
                          "host": "recorded timeline replayed in process through the real stdlib hook path (no host session)"}
    try:
        for ev in day["events"]:
            target = _plus(day["start"], ev["at"])
            exhausted_at, pools = _run_until(drainer, clock, target, ctx, exhausted_at, pools)
            if ev["session"] not in sessions:
                import uuid

                clock.set_to(max(target, clock.now()))
                try:
                    trial.evidence_horizon(ws, allowed_host_sessions={rs.s.session_id for rs in sessions.values()}, not_after=clock.now())
                except trial.TrialError as exc:
                    horizon["violations"] += 1
                    horizon["examples"].append(exc.detail)
                horizon["checks"] += 1
                sessions[ev["session"]] = ReplaySession(ev["session"], ws, host, seed=f"workload:{project}")
                plan.sessions[ev["session"]] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"recalith-eval:workload:{project}:{ev['session']}"))
            clock.set_to(max(target, clock.now()))
            sessions[ev["session"]].event(ev)
        exhausted_at, pools = _run_until(drainer, clock, _plus(day["start"], DAY_SECONDS), ctx, exhausted_at, pools)
        record.update(_measures(ctx, day, calls, sessions, exhausted_at, pools, clock))
        if mode == "live":
            record["curation"]["processing"] = {"real_seconds": _dist([c.get("real_seconds", 0.0) for c in calls]), "note": "real provider call durations; queue wait is on the virtual clock"}
            record["curation"]["proposals"] = trial.curator_calls(ws)
        record["harness_real_seconds"] = round(time.monotonic() - started_real, 2)
    except Exception as exc:  # noqa: BLE001 - an unsuccessful day is reported, never dropped
        record["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    finally:
        drainer.close()
    return record


def _run_until(drainer: Any, clock: Any, target: str, ctx: Any, exhausted_at: str | None, pools: set[str]) -> tuple[str | None, set[str]]:
    from recalith.storage import db

    w = drainer.w
    checked = 0
    while clock.now() < target:
        worked = w.poll_once()
        launched = w.lane.step() if w.lane is not None else False
        if worked or launched:
            clock.advance(1)
        else:
            remaining = max(0.0, _seconds(clock.now(), target))
            clock.advance(min(POLL_SECONDS, remaining) or POLL_SECONDS)
        checked += 1
        if checked % 60 == 0:
            with db.open_store(ctx, readonly=True) as store, store.read() as view:
                rows = view.execute("SELECT body FROM jobs WHERE state = 'waiting_budget'").fetchall()
            for (body,) in rows:
                code = json.loads(body).get("last_error_code") or ""
                if code.startswith("budget_exhausted"):
                    pools.add(code.split(":", 1)[-1])
                    exhausted_at = exhausted_at or clock.now()
    return exhausted_at, pools


def _measures(ctx: Any, day: dict[str, Any], calls: list[dict[str, Any]], sessions: dict[str, ReplaySession], exhausted_at: str | None, pools: set[str], clock: Any) -> dict[str, Any]:
    from recalith.storage import db
    from recalith.working import tasks as wtasks

    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        counts = wtasks.task_counts(view, ctx.workspace_id)
        created = view.execute("SELECT COUNT(*) FROM task_heads").fetchone()[0]
        bindings = dict(view.execute("SELECT r.binding, COUNT(*) FROM task_binding_heads h JOIN task_binding_revisions r ON r.binding_id = h.binding_id AND r.revision = h.revision GROUP BY r.binding").fetchall())
        boundaries = dict(view.execute("SELECT state, COUNT(*) FROM task_boundaries GROUP BY state").fetchall())
        episodes = dict(view.execute("SELECT state, COUNT(*) FROM episode_heads GROUP BY state").fetchall())
        claims = view.execute("SELECT h.status, r.body FROM claim_heads h JOIN claim_revisions r ON r.claim_id = h.claim_id AND r.revision = h.revision").fetchall()
        first = view.execute("SELECT r.claim_id, r.body FROM claim_revisions r WHERE r.status = 'active' AND r.revision = (SELECT MIN(r2.revision) FROM claim_revisions r2 WHERE r2.claim_id = r.claim_id AND r2.status = 'active')").fetchall()
        backlog = view.execute("SELECT body FROM jobs WHERE state IN ('pending', 'waiting_budget', 'leased') AND kind IN ('update_task', 'build_episode', 'extract_claims', 'review_claims', 'revalidate')").fetchall()
        usage = view.execute("SELECT purpose, body FROM provider_usage WHERE state = 'charged'").fetchall()
        reversals = view.execute("SELECT COUNT(*) FROM operations WHERE kind = 'undo'").fetchone()[0]
    now = clock.now()
    backlog_jobs = [json.loads(b) for (b,) in backlog]
    tokens_by_purpose: dict[str, int] = {}
    for purpose, body in usage:
        data = json.loads(body)
        local = data.get("local_estimated_usage") or {}
        used = int(local.get("input_estimate") or data.get("estimated_input_limit") or 0) + int(local.get("output_estimate") or data.get("estimated_output_limit") or 0)
        tokens_by_purpose[purpose] = tokens_by_purpose.get(purpose, 0) + used
    calls_by_purpose: dict[str, int] = {}
    for c in calls:
        calls_by_purpose[c["purpose"]] = calls_by_purpose.get(c["purpose"], 0) + 1
    admitted = [json.loads(b) for s, b in claims if s in ("active", "disputed") and b]
    settled = int(episodes.get("settled", 0)) + int(episodes.get("archived", 0))

    def strength(rows: list[dict[str, Any]]) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in rows:
            key = f"{c.get('strength')}:{c.get('basis')}"
            out[key] = out.get(key, 0) + 1
        return out

    learning = []
    for name, rs in sessions.items():
        pre = [d for d in rs.s.delivered if d.purpose == "pre_action"]
        for i, action in enumerate(rs.s.actions):
            if action.tool == "Bash" and action.exit_code:
                nxt = pre[i + 1] if i + 1 < len(pre) else None
                if nxt is not None:
                    learning.append({"session": name, "interval_s": _seconds(action_time(rs, i), nxt.at), "delivered": bool(nxt.context), "mentions_failure": bool(nxt.context and (action.command or "")[:24] in nxt.context), "state": nxt.state, "degraded": [x for x in nxt.degradations if x != "view_stale"]})
    hours = None if exhausted_at is None else round(_seconds(day["start"], exhausted_at) / 3600, 3)
    waits: dict[str, list[float]] = {"correction_declaration_review": [], "ordinary_review": [], "ordinary": []}
    for c in calls:
        if c["purpose"] == "review_claims":
            waits["correction_declaration_review" if c.get("review_priority") == "correction_or_declaration" else "ordinary_review"].append(c.get("wait_seconds", 0.0))
        else:
            waits["ordinary"].append(c.get("wait_seconds", 0.0))
    return {
        "budget": {"exhausted_at": exhausted_at, "exhausted_at_hours": hours, "pools_hit": sorted(pools), "wait_seconds": waits, "priority_inversions": sum(1 for c in calls if c.get("priority_inversion")),
                   "backlog": {"jobs": len(backlog_jobs), "kinds": sorted({j["kind"] for j in backlog_jobs}), "oldest_age_seconds": max((_seconds(j["due_at"], now) for j in backlog_jobs), default=0.0)}},
        "tasks": {"created": created, "gold": day["gold"]["tasks"], "provisional": bindings.get("provisional", 0), "confirmed": bindings.get("confirmed", 0), "placeholders": counts["placeholders"], "nonredirected": counts["nonredirected"],
                  "link_reversals": reversals, "boundaries": boundaries, "boundary_precision": None, "boundary_recall": None, "boundary_note": "boundary gold is not labeled in the synthetic days"},
        "episodes": episodes,
        "curation": {"calls": len(calls), "calls_by_purpose": calls_by_purpose, "estimated_tokens_by_purpose": tokens_by_purpose, "settled_episodes": settled, "admitted_claims": len(admitted),
                     "calls_per_settled_episode": None if not settled else round(len(calls) / settled, 3), "calls_per_admitted_claim": None if not admitted else round(len(calls) / len(admitted), 3),
                     "queue_wait_seconds": _dist([c.get("wait_seconds", 0.0) for c in calls]), "processing": "recorded backend: immediate (no provider latency)"},
        "strength": {"first_admission": strength([json.loads(b) for _c, b in first if b]), "day_end": strength(admitted)},
        "same_session_learning": {"observations": learning, "count": len(learning), "pre_action_vs_prompt": "pre-action path measured; prompt fallback not exercised (pre-action enabled)"},
        "deliveries": {name: [d.purpose + ":" + d.state for d in rs.s.delivered] for name, rs in sessions.items()},
    }


def action_time(rs: ReplaySession, index: int) -> str:
    pre = [d for d in rs.s.delivered if d.purpose == "pre_action"]
    return pre[index].at if index < len(pre) else rs.s.host.clock.now()


def _dist(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    s = sorted(values)
    return {"n": len(s), "p50": round(s[len(s) // 2], 3), "p95": round(s[min(len(s) - 1, int(0.95 * len(s)))], 3), "max": round(s[-1], 3)}


if __name__ == "__main__":
    if sys.argv[1:] == ["generate"]:
        for p in generate():
            print(p.relative_to(ROOT))
    else:
        print(__doc__)
        sys.exit(2)
