# Claim adjudication sheet

Labels go in `adjudication.json` (start from `adjudication.template.json`). A model judge may assist but does not solely adjudicate support (ACCEPTANCE_TESTS §5).

## smoke-C1-ledgerlite-routine-typo

- prohibited: Any durable lesson about README editing.
- session A: Grep ; Edit README.md
- session B: Grep ; Read src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash PYTHONPATH=src python -m unittest discover -s tests 2>&1 | tail -15 (exit 0)

## smoke-C2-fieldnotes-tdd-expected-red

- prohibited: The delete test fails.
- prohibited: Do not run the unit tests.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_1fa5dba9-6726-4c4c-9b1f-e18bb02824f7` [active, supported]: The first unit-test run before the delete implementation reported an error in test_delete_out_of_range_raises_and_keeps_notes.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_aa9ddb89-03ff-4657-8fc5-c9601510c469` [active, supported]: Run the fieldnotes project checks by setting NOTES_HOME to a scratch directory and running python tools/check.py, which should print OK and exit with code 0.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_e2be8380-1b9c-4ad0-bd2a-3fcaafe2417b` [active, supported]: fieldnotes stores its notes in notes.json inside the directory named by the NOTES_HOME environment variable, and store.notes_path() requires NOTES_HOME to be set.
- session A: Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_store.py; Read README.md; Read tools/check.py; Edit tests/test_store.py; Edit tests/test_store.py; Bash python -m unittest discover -s tests -t . 2>&1 | tail -30 (exit 0); Edit fieldnotes/store.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Bash d=$(mktemp -d) && NOTES_HOME="$d" python tools/check.py 2>&1 | tail -20; echo "exit=${PIPESTATUS[0]}" (exit 0)
- session B: Glob ; Bash ls fieldnotes tests tools; cat tools/check.py fieldnotes/*.py tests/*.py (exit 0); Edit fieldnotes/store.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit tests/test_store.py; Bash d=$(mktemp -d); NOTES_HOME="$d" python tools/check.py; echo exit=$? (exit 0)

## smoke-C3-household-utilities-speculation

- prohibited: Any admitted causal explanation for the September increase.
- session A: 
- session B: Read utilities-log.csv; Write utilities-plan.md

## smoke-C4-cross-project-near-match

- prohibited: ledgerlite's test command applies to fieldnotes.
- claim `smoke-C4-cross-project-near-match:claim_668c082f-6d37-4319-8415-2b7dced563ed` [active, supported]: tools/check.py reads NOTES_HOME with os.environ["NOTES_HOME"] and no default, so it fails when NOTES_HOME is unset.
- session A: Glob ; Bash ls -la (exit 0); Bash cat README.md .gitignore; find src tests .claude .recalith -type f | head -50 (exit 0); Bash head -20 tests/test_ledger.py; ls src/ledgerlite; python --version; python -m pytest --version (exit 1); Bash PYTHONPATH=src python -m unittest discover -s tests -v (exit 0)
- session B: Glob ; Bash ls -la (exit 0); Read README.md; Read tools/check.py; Bash echo "NOTES_HOME=${NOTES_HOME-<unset>}"; grep -rn "NOTES_HOME" fieldnotes tests .claude .recalith/*.toml 2>/dev/null | head (exit 0); Bash d=$(mktemp -d) && NOTES_HOME="$d" python tools/check.py; echo "exit=$?" (exit 0)

## smoke-L1-ledgerlite-test-command

- lesson `smoke-L1-ledgerlite-test-command#0` (procedure): Run the ledgerlite tests with `PYTHONPATH=src python -m unittest discover -s tests` from the project root.
- lesson `smoke-L1-ledgerlite-test-command#1` (failure_lesson): Without PYTHONPATH=src the src-layout package is not importable from tests; plain discovery fails or runs nothing.
- prohibited: All Python projects need PYTHONPATH=src.
- prohibited: unittest discovery is broken.
- claim `smoke-L1-ledgerlite-test-command:claim_5202c89d-b5ba-4d29-a4b1-e2771f846513` [active, corroborated]: tests/test_ledger.py defines three unit tests in class LedgerTests: test_transfer_preserves_total, test_rejects_non_positive_amount and test_close_requires_zero_balance.
- claim `smoke-L1-ledgerlite-test-command:claim_98d2e31a-2a8f-407e-adb9-f7a2276fc0bf` [active, supported]: To run the ledgerlite unit tests, run PYTHONPATH=src python -m unittest discover -s tests -v from the project root; that run's output showed both tests ok.
- claim `smoke-L1-ledgerlite-test-command:claim_c96b7896-4ec4-495a-b092-2130ca57d229` [active, supported]: Ledger.close(name) in src/ledgerlite/__init__.py raises ValueError when the account's balance is not zero, and otherwise deletes the account.
- session A: Glob ; Bash pwd; ls -la (exit 0); Read README.md; Read tests/test_ledger.py; Read src/ledgerlite/__init__.py; Read .recalith/project.toml; Bash cd <run>/work/L1/c/w; python -m unittest discover -s tests 2>&1 | tail -8; echo ---; PYTHONPATH=src python -m unittest discover - (exit 0)
- session B: Glob ; Read src/ledgerlite/__init__.py; Read tests/test_ledger.py; Edit src/ledgerlite/__init__.py; Edit tests/test_ledger.py; Bash PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)

## smoke-L2-fieldnotes-iso-dates

- lesson `smoke-L2-fieldnotes-iso-dates#0` (decision): All dates printed by fieldnotes use ISO-8601; locale formats are not allowed.
- prohibited: Every project must use ISO-8601 dates.
- claim `smoke-L2-fieldnotes-iso-dates:claim_546de00c-e857-461a-8cab-2b876c8a95c1` [active, supported]: Every date fieldnotes prints must be ISO-8601 (YYYY-MM-DD...). Locale formats such as 'Jan 2' or '02/01/2026' must never be used.
- claim `smoke-L2-fieldnotes-iso-dates:claim_a19c4916-4866-44e9-ad94-a0b445b31d5e` [active, supported]: tools/check.py runs the unittest suite in tests/ and reports failure when any line in fieldnotes/**/*.py is longer than 100 characters.
- claim `smoke-L2-fieldnotes-iso-dates:claim_bffa8b5a-de67-44b3-8050-b0b0b856184c` [active, supported]: The fieldnotes list command prints each stored note's created value unchanged, with no date formatting. The add command prints no date.
- claim `smoke-L2-fieldnotes-iso-dates:claim_ec00132e-45e6-4a0e-8c68-f2d3e159f3b0` [active, corroborated]: The fieldnotes export command prints one line per stored note in the form `created: text`, with created printed unchanged. export_lines() in fieldnotes/cli.py builds these lines.
- session A: Grep ; Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py
- session B: Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_store.py; Read tools/check.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Write tests/test_cli.py; Bash cd <run>/work/L2/c/w && NOTES_HOME=$(mktemp -d) python tools/check.py (exit 0)

## smoke-L3-household-grocery-budget

- lesson `smoke-L3-household-grocery-budget#0` (preference): Grocery spending stays under $600 per month; plans that exceed it are flagged.
- prohibited: All budget categories are capped at $600.
- claim `smoke-L3-household-grocery-budget:claim_7988aff3-feb3-4aec-ad60-a6e980b8fd51` [active, supported]: For household planning, the user keeps the grocery budget under $600 per month and wants anything that would push it over flagged.
- session A: Read budget.csv; Edit budget.csv
- session B: Bash ls -la; cat budget.csv groceries.csv meal-plan.md 2>/dev/null (exit 1); Bash cat README.md (exit 0); Bash cat > groceries.csv <<'EOF'
item,cost_usd
Rice and grains (rice, oats, pasta),38.00
Bread and tortillas,22.00
Dried beans and lentils,18.00
 (exit 0)

## smoke-L4-ledgerlite-resume-refactor

- claim `smoke-L4-ledgerlite-resume-refactor:claim_5898ab15-03a8-4099-8c24-2387356d50da` [active, supported]: Running pytest with PYTHONPATH=src printed 'No module named pytest' in the workspace's Python 3.13 environment, so pytest was not available there; running PYTHONPATH=src python -m unittest discover -s tests reported 2 tests passing.
- claim `smoke-L4-ledgerlite-resume-refactor:claim_ce23a114-3e78-47e7-8c22-ef119ab2a69e` [active, supported]: src/ledgerlite/money.py defines parse(value: str | Decimal) -> Decimal, which raises TypeError for values that are neither str nor Decimal, raises ValueError for strings that are not valid decimals, and raises ValueError for non-finite or non-positive amounts.
- session A: Glob ; Read src/ledgerlite/__init__.py; Write src/ledgerlite/money.py
- session B: Glob ; Bash ls src/ledgerlite tests; cat src/ledgerlite/__init__.py (exit 0); Read src/ledgerlite/money.py; Edit src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash PYTHONPATH=src python -I -m pytest -q 2>&1 | tail -20 || true; PYTHONPATH=src python -m pytest -q tests 2>&1 | tail -20 (exit 0); Bash head -20 tests/test_ledger.py; PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -20 (exit 0)

## smoke-R1-fieldnotes-check-env-fixed

- lesson `smoke-R1-fieldnotes-check-env-fixed#0` (failure_lesson): tools/check.py fails with KeyError unless NOTES_HOME is set.
- prohibited: NOTES_HOME must always be set for every command.
- claim `smoke-R1-fieldnotes-check-env-fixed:claim_2eb42a9d-84da-482b-9a9f-64e563f4a4b8` [active, supported]: Running python tools/check.py with NOTES_HOME unset fails with KeyError: 'NOTES_HOME'.
- claim `smoke-R1-fieldnotes-check-env-fixed:claim_95be37dd-d46b-4871-915d-6976c9f2837e` [active, supported]: tools/check.py reads the NOTES_HOME environment variable and fails with KeyError when it is unset.
- session A: Bash python tools/check.py (exit 1); Read tools/check.py; Grep ; Bash export NOTES_HOME="$(mktemp -d)"; python tools/check.py (exit 0)
- session C: Bash python tools/check.py (exit 0)

## smoke-R2-ledgerlite-import-fixed

- lesson `smoke-R2-ledgerlite-import-fixed#0` (failure_lesson): Plain discovery fails to import ledgerlite without PYTHONPATH=src.
- session A: Bash python -m unittest discover -s tests -t . 2>&1 | tail -30; ls (exit 0); Bash ls -R tests src | head -30; cat README.md (exit 0); Bash cat tests/test_ledger.py; cat src/ledgerlite/__init__.py (exit 0); Bash touch tests/__init__.py; python -m unittest discover -s tests -t . 2>&1 | tail -15 (exit 0); Bash cat > tests/__init__.py <<'EOF'
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src")) (exit 0)
- session C: Bash env | grep -i '^PYTHONPATH' ; python -m unittest discover -s tests -t . 2>&1 | tail -20 (exit 0)

## smoke-R3-household-budget-correction

- lesson `smoke-R3-household-budget-correction#0` (preference): Grocery budget is $700 per month.
- claim `smoke-R3-household-budget-correction:claim_1cfa033d-1623-4c5c-ad97-cfb56d6f30a5` [active, supported]: The user's grocery budget is $700 per month for their planning.
- session A: 
- session C: Bash cd <run>/work/R3/c/w && cat > groceries.csv <<'EOF'
item,cost_usd
Chicken breasts and thighs,40.00
Ground beef,28.00
Pork shoulde (exit 0)

## smoke-R4-fieldnotes-storage-conflict

- lesson `smoke-R4-fieldnotes-storage-conflict#0` (fact): Notes are stored in notes.json under NOTES_HOME.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_1444e1ff-a8c5-43b5-85ef-8881f3adc4cb` [disputed, supported]: Notes are stored in notes.json under NOTES_HOME.
- session A: Grep ; Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read README.md; Bash d=$(mktemp -d) && NOTES_HOME="$d" python -m fieldnotes.cli list; echo "exit=$?"; ls -A "$d" | wc -l (exit 0)
- session C: Glob ; Bash ls -la (exit 0); Bash ls fieldnotes; cat fieldnotes/*.py tools/check.py README.md (exit 0); Write tools/count_notes.py; Bash export NOTES_HOME=$(mktemp -d); echo "before: $(python tools/count_notes.py)"; python -m fieldnotes.cli add "first"; python -m fieldnotes.cl (exit 0)
