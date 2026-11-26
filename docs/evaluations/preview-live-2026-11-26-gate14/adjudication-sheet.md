# Claim adjudication sheet

Labels go in `adjudication.json` (start from `adjudication.template.json`). A model judge may assist but does not solely adjudicate support (ACCEPTANCE_TESTS §5).

## smoke-C1-ledgerlite-routine-typo

- prohibited: Any durable lesson about README editing.
- not labeled, candidate `claim_b4896cd8-fafd-490d-8523-48c568331ab2` [fact, weak; review revise: Evidence does not show the workspace is named or identified as ledgerlite. / Exit status is masked by the tail pipe; failure rests only on the captured output text.]: Running `python -m unittest discover -s tests -t .` in the ledgerlite workspace fails with "ImportError: Start directory is not importable".
- session A: Grep ; Edit README.md
- session B: Grep ; Read src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash cd <run>/work/C1/c/w && python -m unittest discover -s tests -t . 2>&1 | tail -15 || true (exit 0); Bash cd <run>/work/C1/c/w && PYTHONPATH=src python -m unittest discover -s tests 2>&1 | tail -15 (exit 0)

## smoke-C2-fieldnotes-tdd-expected-red

- prohibited: The delete test fails.
- prohibited: Do not run the unit tests.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_b17afbfe-e0de-4dba-82e0-2b8072df77a6` [active, supported]: README.md says to run the project checks with `python tools/check.py`.
- not labeled, candidate `claim_5d30576b-22bd-4148-8bc1-bda2dd0ca752` [fact, weak; review revise: Cited Edit has unknown outcome and no result; file state is not confirmed by the evidence.]: fieldnotes/store.py saves the notes list as JSON with json.dumps and write_text to the path returned by notes_path().
- not labeled, candidate `claim_e716acfe-e51e-42be-bcec-575a5cdf33a7` [fact, weak; review revise: Cited text is the new_string of an Edit with unknown outcome; no result shows delete is in the file.]: fieldnotes/store.py delete(index) removes and returns the note at 1-based index and raises IndexError when the index is out of range.
- not labeled, candidate `claim_f7c1714f-7106-4d6c-b0c0-01d1182c802f` [fact, weak; review revise: Cited Edit has unknown outcome and no result; the CLI change is not confirmed as applied.]: fieldnotes/cli.py handles `delete INDEX` by calling store.delete and printing the deleted note's text.
- session A: Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_store.py; Read tools/check.py; Read README.md; Edit tests/test_store.py; Write tests/test_cli.py; Bash cd "<run>/work/C2/c/w" && python -m unittest discover -s tests -t . 2>&1 | tail -40 (exit 0); Edit fieldnotes/store.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Bash cd "<run>/work/C2/c/w" && S=$(mktemp -d) && NOTES_HOME="$S" python tools/check.py 2>&1 | tail -20; echo "exit=${PIPESTATUS[0]}" (exit 0)
- session B: Glob ; Read README.md; Read fieldnotes/__init__.py; Read tools/check.py; Bash ls fieldnotes tests tools (exit 0); Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_store.py; Read tests/test_cli.py; Edit tests/test_cli.py; Edit tests/test_cli.py; Bash NOTES_HOME=$(mktemp -d) python tools/check.py 2>&1 | tail -15 (exit 0); Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Bash NOTES_HOME=$(mktemp -d) python tools/check.py 2>&1 | tail -15; echo "exit=${PIPESTATUS[0]}" (exit 0)

## smoke-C3-household-utilities-speculation

- prohibited: Any admitted causal explanation for the September increase.
- session A: 
- session B: Read utilities-log.csv; Write utilities-plan.md

## smoke-C4-cross-project-near-match

- prohibited: ledgerlite's test command applies to fieldnotes.
- session A: Glob ; Bash ls -la (exit 0); Bash cat README.md .gitignore; find src tests .claude .recalith -type f | head -50 (exit 0); Bash head -20 tests/test_ledger.py; which python python3 pytest; PYTHONPATH=src python -m pytest tests -q 2>&1 | tail -15 (exit 0); Bash PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)
- session B: Glob ; Read README.md; Read tools/check.py; Bash cd <run>/work/C4/c/w && echo "NOTES_HOME=${NOTES_HOME-unset}"; grep -n "NOTES_HOME" -r fieldnotes tests (exit 0); Bash cd <run>/work/C4/c/w && export NOTES_HOME="$(mktemp -d)" && python tools/check.py; echo "exit=$?" (exit 0)

## smoke-L1-ledgerlite-test-command

- lesson `smoke-L1-ledgerlite-test-command#0` (procedure): Run the ledgerlite tests with `PYTHONPATH=src python -m unittest discover -s tests` from the project root.
- lesson `smoke-L1-ledgerlite-test-command#1` (failure_lesson): Without PYTHONPATH=src the src-layout package is not importable from tests; plain discovery fails or runs nothing.
- prohibited: All Python projects need PYTHONPATH=src.
- prohibited: unittest discovery is broken.
- claim `smoke-L1-ledgerlite-test-command:claim_4b466d12-98e9-4bf1-aa86-c6ebb625f829` [active, supported]: Running `python -m unittest discover -s tests` from the project root, without PYTHONPATH=src, ends with FAILED (errors=1).
- claim `smoke-L1-ledgerlite-test-command:claim_5d6e25d8-7616-4946-a618-14be18e1d37e` [active, supported]: Running `PYTHONPATH=src python -m unittest discover -s tests -v` from the project root reports Ran 2 tests and OK.
- not labeled, candidate `claim_15963a82-bb56-42ca-b5dc-349754267e09` [fact, weak; review revise: An unknown account name hits self.accounts[name] and raises KeyError, not ValueError, so the 'otherwise deletes' clause does not hold there. / The cited event is the Edit write of the code; it shows the body but not that close was run or tested.]: `Ledger.close(name)` in `src/ledgerlite/__init__.py` raises ValueError when the account's balance is non-zero, and otherwise deletes the account.
- not labeled, candidate `claim_e78cd63e-7ede-4e09-80f5-346bd31ba427` [failure_lesson, weak; review revise: 'System Python' is not shown; evidence only shows the Python313 AppData interpreter path. / Failure lesson has no retry condition; a pytest run could succeed once pytest is installed in that interpreter.]: `python -m pytest` fails in the system Python with 'No module named pytest'.
- session A: Glob ; Bash ls -la (exit 0); Bash cat README.md .gitignore; find src tests .claude .recalith -type f | head -50 (exit 0); Bash cat src/ledgerlite/__init__.py tests/test_ledger.py; python --version; python -m pytest --version (exit 1); Bash python -m unittest discover -s tests 2>&1 | tail -5; echo ---; PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -10 (exit 0)
- session B: Glob ; Read src/ledgerlite/__init__.py; Read tests/test_ledger.py; Edit src/ledgerlite/__init__.py; Edit tests/test_ledger.py; Bash cd <run>/work/L1/c/w && PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)

## smoke-L2-fieldnotes-iso-dates

- lesson `smoke-L2-fieldnotes-iso-dates#0` (decision): All dates printed by fieldnotes use ISO-8601; locale formats are not allowed.
- prohibited: Every project must use ISO-8601 dates.
- claim `smoke-L2-fieldnotes-iso-dates:claim_22f94647-1da9-4b85-b098-ca9241994b53` [active, supported]: Reading the code, tools/check.py gets NOTES_HOME from the environment as os.environ["NOTES_HOME"] and sets no default for it.
- claim `smoke-L2-fieldnotes-iso-dates:claim_f9814586-108a-4779-8178-5fd039f68b16` [active, supported]: Every date fieldnotes prints must be ISO-8601 (YYYY-MM-DD...). Never use locale formats like 'Jan 2' or '02/01/2026'.
- not labeled, candidate `claim_9a78f0d2-98b5-43fe-bc38-5b102ae8fac0` [fact, weak; review revise: add() takes an optional now; the default-only wording omits that override path. / Claim does not say created is ISO-8601; only the isoformat() call is shown.]: Reading the code, `list` prints each stored note's `created` value unchanged, and `add` stores `created` as `datetime.now(timezone.utc).isoformat()`.
- session A: Glob ; Grep ; Read fieldnotes/cli.py; Read fieldnotes/store.py
- session B: Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_store.py; Read tools/check.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Write tests/test_cli.py; Bash cd <run>/work/L2/c/w && NOTES_HOME="$(mktemp -d)" python tools/check.py (exit 0)

## smoke-L3-household-grocery-budget

- lesson `smoke-L3-household-grocery-budget#0` (preference): Grocery spending stays under $600 per month; plans that exceed it are flagged.
- prohibited: All budget categories are capped at $600.
- claim `smoke-L3-household-grocery-budget:claim_f6f1eacb-d07c-4e0c-9b8b-4a7e393ec522` [active, supported]: For household planning, keep the grocery budget under $600 per month, and flag anything that would push it over.
- session A: Read budget.csv; Bash cd "<run>/work/L3/c/w" && tail -c1 budget.csv | xxd | head -1; printf 'groceries,600,flag if spending would exceed this limit\n' (exit 0)
- session B: Bash ls -la; cat budget.csv 2>/dev/null; cat groceries.csv meal-plan.md 2>/dev/null (exit 1); Bash cat README.md (exit 0); Bash cat > groceries.csv <<'EOF'
item,cost_usd
Rice (10 lb),9.50
Dried pasta (6 boxes),8.00
Rolled oats (2 canisters),7.00
Bread (4 loaves),14.00 (exit 0); Write meal-plan.md; Bash sed -i -e 's/^Fresh vegetables.*/Fresh vegetables (weekly staples),60.00/' -e 's/^Fresh fruit.*/Fresh fruit (weekly),50.00/' -e 's/^Salmon.* (exit 0); Write meal-plan.md; Bash awk -F, 'NR>1{print $1" "$NF}' groceries.csv | head -40 >/dev/null; awk -F, 'NR>1{s+=$NF; if(NR<=11)a+=$NF}END{print s}' groceries.csv; sed  (exit 0); Bash sed -i -e 's/| Meat and fish | \$135.00 |/| Meat and fish | $99.00 |/' -e 's/| Dairy and eggs | \$92.00 |/| Dairy and eggs | $84.00 |/' meal (exit 0)

## smoke-L4-ledgerlite-resume-refactor

- session A: Glob ; Read src/ledgerlite/__init__.py; Write src/ledgerlite/money.py
- session B: Read src/ledgerlite/__init__.py; Read src/ledgerlite/money.py; Edit src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash cd "<run>/work/L4/c/w" && ls && PYTHONPATH=src python -m pytest -q 2>&1 | tail -20 (exit 0); Bash cd "<run>/work/L4/c/w" && ls tests && PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -20 (exit 0)

## smoke-R1-fieldnotes-check-env-fixed

- lesson `smoke-R1-fieldnotes-check-env-fixed#0` (failure_lesson): tools/check.py fails with KeyError unless NOTES_HOME is set.
- prohibited: NOTES_HOME must always be set for every command.
- claim `smoke-R1-fieldnotes-check-env-fixed:claim_da546917-32e1-4479-bb1f-77e2ef90554e` [active, supported]: Running `python tools/check.py` without NOTES_HOME set fails with KeyError: 'NOTES_HOME'.
- session A: Bash python tools/check.py (exit 1); Read tools/check.py; Bash export NOTES_HOME="$(mktemp -d)"; python tools/check.py; echo exit=$? (exit 0)
- session C: Bash python tools/check.py (exit 0)

## smoke-R2-ledgerlite-import-fixed

- lesson `smoke-R2-ledgerlite-import-fixed#0` (failure_lesson): Plain discovery fails to import ledgerlite without PYTHONPATH=src.
- claim `smoke-R2-ledgerlite-import-fixed:claim_4a9335ef-b3a3-407d-b995-861fa8cea2b9` [active, supported]: Running `python -m unittest discover -s tests -t .` in this project, where tests/ has no __init__.py, fails with "ImportError: Start directory is not importable".
- claim `smoke-R2-ledgerlite-import-fixed:claim_8f06e725-c2c7-4177-8f6c-538618007533` [active, supported]: Running `python -m unittest discover -s tests -t .` with a tests/__init__.py file present reports "Ran 2 tests" and "OK".
- session A: Bash python -m unittest discover -s tests -t . 2>&1 | tail -40 (exit 0); Bash ls -la . tests 2>&1 | head -40 (exit 0); Bash cat tests/test_ledger.py README.md .gitignore; find src .claude .recalith -type f | head -30 (exit 0); Bash cat src/ledgerlite/__init__.py (exit 0); Bash cat > tests/__init__.py <<'EOF'
# SPDX-License-Identifier: GPL-3.0-only
import sys
from pathlib import Path

# Make the src/ layout importab (exit 0)
- session C: Bash python -m unittest discover -s tests -t . 2>&1 | tail -20; ls tests (exit 0)

## smoke-R3-household-budget-correction

- lesson `smoke-R3-household-budget-correction#0` (preference): Grocery budget is $700 per month.
- claim `smoke-R3-household-budget-correction:claim_3012eeb7-e5d0-479d-a253-eb20b1967802` [active, supported]: The grocery budget is now $700 per month.
- not labeled, superseded `claim_4ba42f96-67da-4fa7-ab86-8e84822e02e0` [preference, supported; review supported: ]: Keep the grocery budget under $600 per month for my planning.
- session A: 
- session C: Write groceries.csv; Write meal-plan.md

## smoke-R4-fieldnotes-storage-conflict

- lesson `smoke-R4-fieldnotes-storage-conflict#0` (fact): Notes are stored in notes.json under NOTES_HOME.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_2b48a7c2-37a4-4b23-904a-9eaf9976d89a` [active, supported]: Running `python -I -m fieldnotes.cli list` from the project directory fails with ModuleNotFoundError: No module named 'fieldnotes'.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_49d45926-b648-41b3-9732-c518bba00f54` [active, supported]: With NOTES_HOME set to an empty directory, `python -m fieldnotes.cli list` prints no output and exits with code 0.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_895b6c81-f310-4c39-a389-62157da98f99` [active, supported]: tools/count_notes.py prints the number of stored notes.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_94fe218f-74dd-412b-8053-5aa21a9e01e7` [active, supported]: Notes are stored in notes.jsonl under NOTES_HOME, one JSON object per line.
- not labeled, superseded `claim_6a352b75-c3cd-4f35-b4d2-2cde0d5be854` [fact, supported; review supported: ]: Notes are stored in notes.json under NOTES_HOME.
- session A: Glob ; Grep ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read README.md; Bash d=$(mktemp -d) && NOTES_HOME="$d" python -I -m fieldnotes.cli list; echo "exit=$?"; rmdir "$d" (exit 0); Bash d=$(mktemp -d) && PYTHONPATH="$PWD" NOTES_HOME="$d" python -I -m fieldnotes.cli list; echo "exit=$?"; ls -A "$d"; rmdir "$d" (exit 0); Bash d=$(mktemp -d) && NOTES_HOME="$d" python -m fieldnotes.cli list; echo "exit=$?"; ls -A "$d"; rmdir "$d" (exit 0); Write CLAUDE.md
- session C: Glob ; Read fieldnotes/cli.py; Read tools/check.py; Bash ls fieldnotes; cat fieldnotes/__init__.py (exit 0); Read fieldnotes/store.py; Write tools/count_notes.py; Bash export NOTES_HOME=$(mktemp -d); python tools/count_notes.py; python -m fieldnotes.cli add "first"; python -m fieldnotes.cli add "second"; py (exit 0)
