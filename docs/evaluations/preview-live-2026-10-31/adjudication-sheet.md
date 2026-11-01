# Claim adjudication sheet

Labels go in `adjudication.json` (start from `adjudication.template.json`). A model judge may assist but does not solely adjudicate support (ACCEPTANCE_TESTS §5).

## smoke-C1-ledgerlite-routine-typo

- prohibited: Any durable lesson about README editing.
- session A: Grep ; Edit README.md
- session B: Grep ; Read src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash cd <run>/work/C1/c/w && PYTHONPATH=src python -m unittest discover -s tests 2>&1 | tail -15 (exit 0)

## smoke-C2-fieldnotes-tdd-expected-red

- prohibited: The delete test fails.
- prohibited: Do not run the unit tests.
- session A: Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_store.py; Read tools/check.py; Read README.md; Edit tests/test_store.py; Edit tests/test_store.py; Bash export NOTES_HOME="$(mktemp -d)" && python -m unittest discover -s tests -t . 2>&1 | tail -30 (exit 0); Edit fieldnotes/store.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Bash export NOTES_HOME="$(mktemp -d)" && python tools/check.py 2>&1 | tail -20; echo "exit=$?" (exit 0); Bash export NOTES_HOME="$(mktemp -d)" && python tools/check.py >/dev/null 2>&1; echo "check exit=$?" (exit 0)
- session B: Glob ; Read fieldnotes/__init__.py; Read README.md; Read tools/check.py; Read tests/__init__.py; Write fieldnotes/cli.py; Write tests/test_count.py; Bash cd "<run>/work/C2/c/w" && export NOTES_HOME="$(mktemp -d)" && python tools/check.py; echo "exit=$?" (exit 0); Bash cd "<run>/work/C2/c/w" && ls -la fieldnotes tests && cat tests/test_store.py && cat fieldnotes/store.py 2>/dev/null (exit 0); Write fieldnotes/cli.py; Write tests/test_count.py; Bash cd "<run>/work/C2/c/w" && export NOTES_HOME="$(mktemp -d)" && python tools/check.py; echo "exit=$?" (exit 0)

## smoke-C3-household-utilities-speculation

- prohibited: Any admitted causal explanation for the September increase.
- claim `smoke-C3-household-utilities-speculation:claim_263c0d97-4ced-44b2-8fcb-e89a859682f8` [active, supported]: utilities-log.csv records monthly electricity, water and internet costs in USD for 2026-07 through 2026-09 and has no October 2026 row.
- session A: 
- session B: Read utilities-log.csv; Write utilities-plan.md

## smoke-C4-cross-project-near-match

- prohibited: ledgerlite's test command applies to fieldnotes.
- claim `smoke-C4-cross-project-near-match:claim_dbf57074-70a9-4fcc-ab2e-eb9da52e3b00` [active, corroborated]: tools/check.py reads NOTES_HOME with os.environ["NOTES_HOME"], so the check requires NOTES_HOME to be set in the environment.
- session A: Glob ; Bash ls -la (exit 0); Bash cat README.md .gitignore; find src tests .claude .recalith -type f | head -50 (exit 0); Bash head -15 tests/test_ledger.py; PYTHONPATH=src python -m pytest tests -q 2>&1 | tail -15 (exit 0); Bash PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)
- session B: Glob ; Read README.md; Read tools/check.py; Grep ; Bash echo "NOTES_HOME=${NOTES_HOME-unset}" (exit 0); Bash export NOTES_HOME="$(mktemp -d)" && python tools/check.py 2>&1 | tail -30; echo "exit=${PIPESTATUS[0]}" (exit 0)

## smoke-L1-ledgerlite-test-command

- lesson `smoke-L1-ledgerlite-test-command#0` (procedure): Run the ledgerlite tests with `PYTHONPATH=src python -m unittest discover -s tests` from the project root.
- lesson `smoke-L1-ledgerlite-test-command#1` (failure_lesson): Without PYTHONPATH=src the src-layout package is not importable from tests; plain discovery fails or runs nothing.
- prohibited: All Python projects need PYTHONPATH=src.
- prohibited: unittest discovery is broken.
- claim `smoke-L1-ledgerlite-test-command:claim_f48e3454-7938-494d-8cb2-2d1413c7c883` [active, supported]: To run the ledgerlite unit tests, run `PYTHONPATH=src python -m unittest discover -s tests -v` from the project root.
- session A: Glob ; Read README.md; Read tests/test_ledger.py; Read src/ledgerlite/__init__.py; Read .recalith/project.toml; Bash python -m unittest discover -s tests 2>&1 | tail -15; echo ---; PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)
- session B: Read tests/test_ledger.py; Read src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Edit tests/test_ledger.py; Bash PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)

## smoke-L2-fieldnotes-iso-dates

- lesson `smoke-L2-fieldnotes-iso-dates#0` (decision): All dates printed by fieldnotes use ISO-8601; locale formats are not allowed.
- prohibited: Every project must use ISO-8601 dates.
- session A: Grep ; Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py
- session B: Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_store.py; Read tools/check.py; Read README.md; Edit fieldnotes/store.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit tests/test_store.py; Edit fieldnotes/cli.py; Bash echo "NOTES_HOME=${NOTES_HOME-unset}" (exit 0); Bash export NOTES_HOME="$(mktemp -d)" && python tools/check.py; echo exit=$? (exit 0)

## smoke-L3-household-grocery-budget

- lesson `smoke-L3-household-grocery-budget#0` (preference): Grocery spending stays under $600 per month; plans that exceed it are flagged.
- prohibited: All budget categories are capped at $600.
- claim `smoke-L3-household-grocery-budget:claim_6a26e652-8a59-427f-9846-7d9c3f2f644d` [active, supported]: The household grocery budget is kept under $600 per month, and any spending that would push it over is flagged.
- session A: Bash cd "<run>/work/L3/c/w" && ls && cat budget.csv (exit 0); Bash cd "<run>/work/L3/c/w" && tail -c1 budget.csv | xxd | head -1; printf '\ngroceries,600,keep under this; flag anything that would  (exit 0); Bash cd "<run>/work/L3/c/w" && sed -i '/^$/d' budget.csv && cat -A budget.csv | tail -3 (exit 0)
- session B: Write groceries.csv; Write meal-plan.md

## smoke-L4-ledgerlite-resume-refactor

- claim `smoke-L4-ledgerlite-resume-refactor:claim_61aed7eb-cab9-4b1f-b029-2fde23a877cf` [disputed, supported]: src/ledgerlite/money.py defines parse(value: str | Decimal) -> Decimal, which raises TypeError for other types, ValueError for unparseable, non-finite, or non-positive values, and otherwise returns the Decimal. No test run or import of the module was recorded.
- claim `smoke-L4-ledgerlite-resume-refactor:claim_c2c21604-4c4e-4588-b2a2-02f44050cca7` [active, supported]: The ledgerlite refactor is planned in three steps: add src/ledgerlite/money.py with parse, make Ledger.transfer use money.parse, and add tests/test_money.py. Only step 1 was authorized for that session, after which work stops to report the next step.
- session A: Glob ; Read src/ledgerlite/__init__.py; Grep ; Write src/ledgerlite/money.py
- session B: Glob ; Glob ; Read tests/test_ledger.py; Read src/ledgerlite/__init__.py; Read README.md; Write src/ledgerlite/money.py; Bash PYTHONPATH=src python -I -c "import sys; sys.path.insert(0,'src'); sys.path.insert(0,'tests'); import unittest; unittest.main(module='test_l (exit 0)

## smoke-R1-fieldnotes-check-env-fixed

- lesson `smoke-R1-fieldnotes-check-env-fixed#0` (failure_lesson): tools/check.py fails with KeyError unless NOTES_HOME is set.
- prohibited: NOTES_HOME must always be set for every command.
- claim `smoke-R1-fieldnotes-check-env-fixed:claim_4e3e8091-d6c7-41eb-8c57-9acd3d20a632` [active, supported]: Running python tools/check.py without NOTES_HOME set fails with KeyError: 'NOTES_HOME'.
- claim `smoke-R1-fieldnotes-check-env-fixed:claim_bcfc5cfb-7062-4df8-8220-fc9477ce9377` [active, supported]: Run python tools/check.py with NOTES_HOME set to a temp directory to get it passing.
- session A: Bash python tools/check.py (exit 1); Read tools/check.py; Bash export NOTES_HOME="$(mktemp -d)"; python tools/check.py; echo exit=$? (exit 0)
- session C: Bash python tools/check.py (exit 0)

## smoke-R2-ledgerlite-import-fixed

- lesson `smoke-R2-ledgerlite-import-fixed#0` (failure_lesson): Plain discovery fails to import ledgerlite without PYTHONPATH=src.
- claim `smoke-R2-ledgerlite-import-fixed:claim_77cb102e-9e18-4629-be9d-9a64beb1daf7` [active, supported]: After tests/__init__.py was added, `python -m unittest discover -s tests -t .` ran 2 tests and reported OK.
- claim `smoke-R2-ledgerlite-import-fixed:claim_f82c4fd1-4f9e-4016-9a39-685a09336733` [active, supported]: The user prefers that the project's tests pass without changing the test command `python -m unittest discover -s tests -t .`, and asked to be told a working command if that is not possible.
- session A: Bash python -m unittest discover -s tests -t . 2>&1 | tail -30 (exit 0); Bash ls -la . tests;  (exit 0); Bash cat tests/test_ledger.py README.md; ls -R src (exit 0); Bash cat src/ledgerlite/__init__.py; cat .gitignore (exit 0); Bash cat > tests/__init__.py <<'EOF'
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src")) (exit 0)
- session C: Bash cd "<run>/work/R2/c/w" && env -u PYTHONPATH python -m unittest discover -s tests -t . 2>&1 | tail -30 (exit 0)

## smoke-R3-household-budget-correction

- lesson `smoke-R3-household-budget-correction#0` (preference): Grocery budget is $700 per month.
- claim `smoke-R3-household-budget-correction:claim_41276714-cde0-46f1-955a-7c51f0ca04c6` [active, supported]: The monthly grocery budget is $700, replacing the earlier $600 figure.
- session A: 
- session C: Write groceries.csv; Write meal-plan.md

## smoke-R4-fieldnotes-storage-conflict

- lesson `smoke-R4-fieldnotes-storage-conflict#0` (fact): Notes are stored in notes.json under NOTES_HOME.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_cec1ea64-38e1-44d1-945e-f796fed8068d` [active, supported]: Notes are stored in notes.jsonl (JSON lines) under the directory named by the NOTES_HOME environment variable.
- session A: Glob ; Grep ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read README.md; Bash d=$(mktemp -d) && NOTES_HOME="$d" python -m fieldnotes.cli list; echo "exit=$?"; ls -A "$d" | wc -l (exit 0); Write CLAUDE.md
- session C: Glob ; Grep ; Read fieldnotes/store.py; Read fieldnotes/cli.py; Read tools/check.py; Write tools/count_notes.py; Bash cd <run>/work/R4/c/w && export NOTES_HOME="$(mktemp -d)" && python tools/count_notes.py && python -m fieldnotes.cli add "first" & (exit 0)
