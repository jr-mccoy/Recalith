#!/usr/bin/env python3
"""Task oracles for the 12 non-held-out smoke scenarios.

    python evals/oracles/smoke.py CHECK --workspace DIR --actions FILE

The oracle judges final artifacts and the normalized action log, independently
of any memory text (ACCEPTANCE_TESTS §6). It copies the workspace before
running anything, so judging never mutates the evaluated state.

``--actions`` is a JSON list of ``{"session", "tool", "command", "exit_code"}``
records produced by the evaluation harness from the host transcript.
Prints one JSON object; exit 0 when the task passed, 1 otherwise, 2 on usage.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

TIMEOUT = 120


class Ctx:
    def __init__(self, workspace: Path, actions: list[dict[str, Any]], session: str) -> None:
        self.ws = workspace
        self.actions = [a for a in actions if a.get("session") == session]
        self.checks: dict[str, bool] = {}
        self.metrics: dict[str, Any] = {}

    def check(self, name: str, ok: bool) -> None:
        self.checks[name] = bool(ok)

    def run(self, argv: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
        full = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), **(env or {})}
        return subprocess.run(argv, cwd=cwd or self.ws, env=full, capture_output=True, text=True, timeout=TIMEOUT)

    def commands(self, needle: str) -> list[dict[str, Any]]:
        return [a for a in self.actions if a.get("command") and needle in a["command"]]


def copy_workspace(src: Path) -> Path:
    dst = Path(tempfile.mkdtemp(prefix="recalith-oracle-")) / "ws"
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", ".recalith"))
    return dst


def ledger_tests_pass(c: Ctx) -> bool:
    return c.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], env={"PYTHONPATH": "src"}).returncode == 0


def fieldnotes_check_pass(c: Ctx) -> bool:
    home = tempfile.mkdtemp(prefix="oracle-notes-")
    return c.run([sys.executable, "tools/check.py"], env={"NOTES_HOME": home}).returncode == 0


def ledger_probe(c: Ctx, code: str) -> subprocess.CompletedProcess:
    return c.run([sys.executable, "-c", code], env={"PYTHONPATH": "src"})


def repeated_failures(c: Ctx, needle: str) -> int:
    count = 0
    for action in c.commands(needle):
        if action.get("exit_code") == 0:
            break
        count += 1
    return count


def read_csv_total(path: Path, column: str) -> tuple[int, float]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    total = 0.0
    for row in rows:
        total += float(str(row[column]).replace("$", "").strip())
    return len(rows), total


# ---------------------------------------------------------------- checks


def l1(c: Ctx) -> None:
    c.check("suite_passes", ledger_tests_pass(c))
    probe = ledger_probe(c, "from ledgerlite import Ledger\nl=Ledger();l.open('a');l.open('b');l.transfer('a','b','1')\ntry:\n l.close('a')\nexcept ValueError:\n print('refused')\nl2=Ledger();l2.open('z');l2.close('z');print('closed', 'z' not in l2.accounts)")
    c.check("close_refuses_nonzero", "refused" in probe.stdout)
    c.check("close_removes_zero_account", "closed True" in probe.stdout)
    c.check("close_tested", "close" in "".join(p.read_text(encoding="utf-8") for p in (c.ws / "tests").glob("test_*.py")))
    c.metrics["repeated_test_command_failures"] = repeated_failures(c, "unittest")


def l2(c: Ctx) -> None:
    c.check("checks_pass", fieldnotes_check_pass(c))
    home = tempfile.mkdtemp(prefix="oracle-notes-")
    seed = "from datetime import datetime, timezone\nfrom fieldnotes import store\nstore.add('alpha', now=datetime(2026,1,2,3,4,5,tzinfo=timezone.utc))\nstore.add('beta', now=datetime(2026,3,4,5,6,7,tzinfo=timezone.utc))"
    c.run([sys.executable, "-c", seed], env={"NOTES_HOME": home})
    out = c.run([sys.executable, "-m", "fieldnotes.cli", "export"], env={"NOTES_HOME": home})
    lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
    c.check("export_exists", out.returncode == 0 and len(lines) == 2)
    c.check("export_dates_iso8601", bool(lines) and all(re.match(r"^\d{4}-\d{2}-\d{2}([T ][0-9:.+\-Z]*)?: (alpha|beta)$", ln) for ln in lines))


def l3(c: Ctx) -> None:
    path = c.ws / "groceries.csv"
    c.check("grocery_list_exists", path.exists())
    if path.exists():
        rows, total = read_csv_total(path, "cost_usd")
        c.metrics["grocery_total_usd"] = total
        c.check("at_least_three_items", rows >= 3)
        c.check("within_600_budget", 0 < total <= 600)
    c.check("meal_plan_updated", "No plan yet" not in (c.ws / "meal-plan.md").read_text(encoding="utf-8"))


def l4(c: Ctx) -> None:
    money = c.ws / "src" / "ledgerlite" / "money.py"
    c.check("step1_present", money.exists())
    init = (c.ws / "src" / "ledgerlite" / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(init)
    transfer = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "transfer"), None)
    c.check("step2_transfer_uses_money_parse", transfer is not None and "parse" in ast.unparse(transfer))
    c.check("step3_not_started", not (c.ws / "tests" / "test_money.py").exists())
    c.check("suite_passes", ledger_tests_pass(c))
    probe = ledger_probe(c, "from decimal import Decimal\nfrom ledgerlite import Ledger\nl=Ledger();l.open('a');l.open('b');l.transfer('a','b',Decimal('2'));print(l.balance('b'))")
    c.check("transfer_accepts_decimal", probe.stdout.strip() == "2")


def r1(c: Ctx) -> None:
    plain = [a for a in c.commands("tools/check.py") if "NOTES_HOME" not in a["command"]]
    c.check("plain_retry_attempted", bool(plain))
    c.check("plain_retry_succeeded", any(a.get("exit_code") == 0 for a in plain))
    c.check("check_passes_without_env", c.run([sys.executable, "tools/check.py"]).returncode == 0)


def r2(c: Ctx) -> None:
    plain = [a for a in c.commands("unittest") if "PYTHONPATH" not in a["command"] and "-s tests" in a["command"]]
    c.check("plain_retry_attempted", bool(plain))
    c.check("plain_retry_succeeded", any(a.get("exit_code") == 0 for a in plain))
    c.check("plain_discovery_passes", c.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."]).returncode == 0)


def r3(c: Ctx) -> None:
    path = c.ws / "groceries.csv"
    c.check("grocery_list_exists", path.exists())
    if path.exists():
        _, total = read_csv_total(path, "cost_usd")
        c.metrics["grocery_total_usd"] = total
        c.check("within_corrected_700_budget", 0 < total <= 700)
    plan = (c.ws / "meal-plan.md").read_text(encoding="utf-8")
    c.check("plan_states_700_limit", "700" in plan)
    stale = [ln for ln in plan.splitlines() if re.search(r"\b600\b", ln) and not re.search(r"previous|old|was|former|correct", ln, re.I)]
    c.check("no_stale_600_limit", not stale)


def r4(c: Ctx) -> None:
    script = c.ws / "tools" / "count_notes.py"
    c.check("script_exists", script.exists())
    home = tempfile.mkdtemp(prefix="oracle-notes-")
    c.run([sys.executable, "-c", "from fieldnotes import store\nstore.add('one')\nstore.add('two')"], env={"NOTES_HOME": home})
    out = c.run([sys.executable, "tools/count_notes.py"], env={"NOTES_HOME": home}) if script.exists() else None
    c.check("counts_current_storage", out is not None and out.returncode == 0 and out.stdout.strip().splitlines()[-1:] == ["2"])


def c1(c: Ctx) -> None:
    init = (c.ws / "src" / "ledgerlite" / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(init)
    total = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "total"), None)
    c.check("total_has_docstring", total is not None and bool(ast.get_docstring(total)))
    c.check("suite_passes", ledger_tests_pass(c))


def c2(c: Ctx) -> None:
    c.check("checks_pass", fieldnotes_check_pass(c))
    home = tempfile.mkdtemp(prefix="oracle-notes-")
    env = {"NOTES_HOME": home}
    for text in ("a", "b", "c"):
        c.run([sys.executable, "-m", "fieldnotes.cli", "add", text], env=env)
    count = c.run([sys.executable, "-m", "fieldnotes.cli", "count"], env=env)
    c.check("count_works", count.returncode == 0 and count.stdout.strip().endswith("3"))
    deleted = c.run([sys.executable, "-m", "fieldnotes.cli", "delete", "0"], env=env)
    after = c.run([sys.executable, "-m", "fieldnotes.cli", "count"], env=env)
    c.check("delete_works", deleted.returncode == 0 and after.stdout.strip().endswith("2"))


def c3(c: Ctx) -> None:
    plan = c.ws / "utilities-plan.md"
    c.check("plan_exists", plan.exists())
    c.check("plan_has_estimate", plan.exists() and bool(re.search(r"\$?\s?\d{2,4}", plan.read_text(encoding="utf-8"))))


def c4(c: Ctx) -> None:
    leaked = c.commands("PYTHONPATH=src")
    c.metrics["cross_project_leak_commands"] = len(leaked)
    c.check("no_foreign_test_command", not leaked)
    runs = c.commands("check.py") + c.commands("unittest")
    c.check("project_tests_run_successfully", any(a.get("exit_code") == 0 for a in runs))
    c.check("checks_pass", fieldnotes_check_pass(c))


CHECKS: dict[str, Callable[[Ctx], None]] = {"l1": l1, "l2": l2, "l3": l3, "l4": l4, "r1": r1, "r2": r2, "r3": r3, "r4": r4, "c1": c1, "c2": c2, "c3": c3, "c4": c4}


def judge(check: str, workspace: Path, actions: list[dict[str, Any]], session: str) -> dict[str, Any]:
    ctx = Ctx(copy_workspace(workspace), actions, session)
    try:
        CHECKS[check](ctx)
    except Exception as exc:  # an oracle crash is a failed task, reported explicitly
        ctx.checks["oracle_error"] = False
        ctx.metrics["oracle_error"] = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        shutil.rmtree(ctx.ws.parent, ignore_errors=True)
    return {"check": check, "session": session, "passed": bool(ctx.checks) and all(ctx.checks.values()), "checks": ctx.checks, "metrics": ctx.metrics}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("check", choices=sorted(CHECKS))
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--actions", type=Path)
    parser.add_argument("--session", default="B")
    ns = parser.parse_args(argv)
    actions = json.loads(ns.actions.read_text(encoding="utf-8")) if ns.actions else []
    result = judge(ns.check, ns.workspace, actions, ns.session)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
