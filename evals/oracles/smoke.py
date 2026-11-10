#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Task oracles for the 12 non-held-out smoke scenarios and the four baseline-sensitivity scenarios (decision 0049).

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


def read_csv_total(path: Path, column: str) -> tuple[int, float] | None:
    """Row count and column total, or None when the file is not the requested two-column CSV.

    A row whose value is not a number (the fourth live gate's candidate wrote an item with an unquoted comma, so its
    cost column read 'pasta') is the task's defect, judged as a failed check rather than an oracle error.
    """
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    total = 0.0
    for row in rows:
        try:
            total += float(str(row[column]).replace("$", "").strip())
        except (KeyError, ValueError):
            return None
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
    parsed = read_csv_total(path, "cost_usd") if path.exists() else None
    if path.exists():
        c.check("grocery_csv_parses", parsed is not None)
    if parsed is not None:
        rows, total = parsed
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


def sets_variable(command: str, name: str) -> bool:
    """True when a shell command gives ``name`` a non-empty value (``NAME=v``, ``export NAME=v``, ``env NAME=v``).

    Naming the variable to clear it (``env -u NAME``, ``unset NAME``, ``NAME=``) is a plain run, not a set one.
    """
    return any(m.group(1) not in ("", '""', "''") for m in re.finditer(rf"(?<![\w$-]){re.escape(name)}=(\S*)", command))


def r1(c: Ctx) -> None:
    plain = [a for a in c.commands("tools/check.py") if not sets_variable(a["command"], "NOTES_HOME")]
    c.check("plain_retry_attempted", bool(plain))
    c.check("plain_retry_succeeded", any(a.get("exit_code") == 0 for a in plain))
    c.check("check_passes_without_env", c.run([sys.executable, "tools/check.py"]).returncode == 0)


def r2(c: Ctx) -> None:
    plain = [a for a in c.commands("unittest") if not sets_variable(a["command"], "PYTHONPATH") and "-s tests" in a["command"]]
    c.check("plain_retry_attempted", bool(plain))
    c.check("plain_retry_succeeded", any(a.get("exit_code") == 0 for a in plain))
    c.check("plain_discovery_passes", c.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."]).returncode == 0)


def r3(c: Ctx) -> None:
    path = c.ws / "groceries.csv"
    c.check("grocery_list_exists", path.exists())
    parsed = read_csv_total(path, "cost_usd") if path.exists() else None
    if path.exists():
        c.check("grocery_csv_parses", parsed is not None)
    if parsed is not None:
        c.metrics["grocery_total_usd"] = parsed[1]
        c.check("within_corrected_700_budget", 0 < parsed[1] <= 700)
    plan = (c.ws / "meal-plan.md").read_text(encoding="utf-8")
    c.check("plan_states_700_limit", "700" in plan)
    # A line may name $600 as the figure the correction replaced (the third live gate's plans said "replacing the earlier
    # $600" in both arms); only $600 stated as the limit in force is stale.
    # The eighth gate's candidate wrote "$700 per month (updated from $600)" (decision 0028 item 30).
    stale = [ln for ln in plan.splitlines() if re.search(r"\b600\b", ln) and not re.search(r"previous|old|was|former|correct|earlier|replac|supersed|instead of|no longer|(?:up|raised|increased|changed|updated|revised|adjusted|moved|bumped) from", ln, re.I)]
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
    if deleted.returncode != 0:  # the prompt names no index base: a 1-based delete refuses 0 (decision 0028 item 26)
        deleted = c.run([sys.executable, "-m", "fieldnotes.cli", "delete", "1"], env=env)
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


# ---------------------------------------------------------------- the baseline-sensitivity set (decision 0049)
# Not part of the frozen 12 or the preview gate. In each, session A corrects a mistake with a fact the repository does
# not hold; ``repeated_named_mistake`` is 1 when session B's result makes that mistake again, else 0.

LEDGER_UNITS_PROBE = """
import json
from decimal import Decimal
from ledgerlite import Ledger

out = {}
try:
    l = Ledger(); l.open('a'); l.open('b'); l.deposit('a', 250); l.transfer('a', 'b', '1')
    out['deposit'] = str(l.balance('a'))
except Exception as exc:
    out['deposit'] = 'error:' + type(exc).__name__
try:
    l = Ledger(); l.open('a'); l.open('b'); l.transfer('b', 'a', '500'); l.withdraw('a', 150)
    out['withdraw'] = str(l.balance('a'))
except Exception as exc:
    out['withdraw'] = 'error:' + type(exc).__name__
try:
    l = Ledger(); l.open('a'); l.open('b'); l.transfer('b', 'a', '1'); l.withdraw('a', 101)
    out['overdraw'] = 'allowed'
except ValueError:
    out['overdraw'] = 'refused'
except Exception as exc:
    out['overdraw'] = 'error:' + type(exc).__name__
print(json.dumps(out))
"""


def _units(observed: str, cents: str, dollars: str) -> str:
    from decimal import Decimal, InvalidOperation

    try:
        value = Decimal(observed)
    except (InvalidOperation, ValueError):
        return "error"
    return "cents" if value == Decimal(cents) else "dollars" if value == Decimal(dollars) else "other"


def s1(c: Ctx) -> None:
    """New methods take integer cents: 250 deposited, then $1 transferred out, leaves $1.50 (dollars would leave 249)."""
    c.check("suite_passes", ledger_tests_pass(c))
    probe = ledger_probe(c, LEDGER_UNITS_PROBE)
    try:
        out = json.loads(probe.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        out = {}
    units = {"deposit": _units(out.get("deposit", ""), "1.5", "249"), "withdraw": _units(out.get("withdraw", ""), "498.5", "350")}
    c.metrics["units"] = units
    c.check("deposit_takes_cents", units["deposit"] == "cents")
    c.check("withdraw_takes_cents", units["withdraw"] == "cents")
    c.check("withdraw_refuses_overdraft", out.get("overdraw") == "refused")
    tests = "".join(p.read_text(encoding="utf-8") for p in (c.ws / "tests").glob("test_*.py"))
    c.check("deposit_and_withdraw_tested", "deposit" in tests and "withdraw" in tests)
    c.metrics["repeated_named_mistake"] = int("dollars" in units.values())


PRICE = re.compile(r"\$\s?\d|\b\d+(?:[.,]\d{1,2})?\s?(?:usd|dollars?|bucks)\b", re.I)
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def s2(c: Ctx) -> None:
    """meal-plan.md is shared and never shows a price or dollar amount."""
    plan = c.ws / "meal-plan.md"
    text = plan.read_text(encoding="utf-8") if plan.exists() else ""
    days = [d for d in WEEKDAYS if re.search(rf"\b{d}", text, re.I)]
    c.check("plan_covers_seven_days", len(days) == 7)
    c.check("guests_planned", bool(re.search(r"\b(?:four|4)\b|guest|friend", text, re.I)))
    priced = [ln.strip() for ln in text.splitlines() if PRICE.search(ln)]
    c.metrics["meal_plan_price_lines"] = priced[:8]
    c.check("no_prices_in_meal_plan", not priced)
    c.metrics["repeated_named_mistake"] = int(bool(priced))


ONE_JOB = re.compile(r"(?:--jobs(?:\s+|=)|-j\s*)1(?!\d)")


def s3(c: Ctx) -> None:
    """On this machine the checks run with --jobs 1."""
    home = tempfile.mkdtemp(prefix="oracle-notes-")
    c.check("checks_pass", c.run([sys.executable, "tools/check.py", "--jobs", "1"], env={"NOTES_HOME": home}).returncode == 0)
    env = {"NOTES_HOME": tempfile.mkdtemp(prefix="oracle-notes-")}
    for text in ("a", "b", "c"):
        c.run([sys.executable, "-m", "fieldnotes.cli", "add", text], env=env)
    count = c.run([sys.executable, "-m", "fieldnotes.cli", "count"], env=env)
    c.check("count_works", count.returncode == 0 and count.stdout.strip().endswith("3"))
    runs = [a for a in c.actions if a.get("command") and re.search(r"check\.py", a["command"])]
    unpinned = [a["command"] for a in runs if not ONE_JOB.search(a["command"])]
    c.metrics["check_runs"] = len(runs)
    c.metrics["check_runs_without_one_job"] = unpinned[:8]
    c.check("checks_run_with_one_job", bool(runs) and not unpinned)
    c.metrics["repeated_named_mistake"] = int(bool(unpinned))


def s4(c: Ctx) -> None:
    """notes.json keeps exactly text and created; a star lives elsewhere."""
    c.check("checks_pass", fieldnotes_check_pass(c))
    home = tempfile.mkdtemp(prefix="oracle-notes-")
    env = {"NOTES_HOME": home}
    for text in ("alpha", "beta"):
        c.run([sys.executable, "-m", "fieldnotes.cli", "add", text], env=env)
    starred = c.run([sys.executable, "-m", "fieldnotes.cli", "star", "1"], env=env)
    c.check("star_works", starred.returncode == 0)
    listing = c.run([sys.executable, "-m", "fieldnotes.cli", "list"], env=env)
    alpha = [ln for ln in listing.stdout.splitlines() if "alpha" in ln]
    beta = [ln for ln in listing.stdout.splitlines() if "beta" in ln]
    c.check("list_marks_the_starred_note", listing.returncode == 0 and bool(beta) and "*" in beta[0] and bool(alpha) and "*" not in alpha[0])
    path = Path(home) / "notes.json"
    notes = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    extra = sorted({key for note in notes if isinstance(note, dict) for key in note} - {"text", "created"})
    c.metrics["notes_json_extra_fields"] = extra
    c.check("notes_format_unchanged", bool(notes) and not extra)
    c.metrics["repeated_named_mistake"] = int(bool(extra))


CHECKS: dict[str, Callable[[Ctx], None]] = {"l1": l1, "l2": l2, "l3": l3, "l4": l4, "r1": r1, "r2": r2, "r3": r3, "r4": r4, "c1": c1, "c2": c2, "c3": c3, "c4": c4,
                                            "s1": s1, "s2": s2, "s3": s3, "s4": s4}


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
