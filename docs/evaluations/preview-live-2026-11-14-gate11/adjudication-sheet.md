# Claim adjudication sheet

Labels go in `adjudication.json` (start from `adjudication.template.json`). A model judge may assist but does not solely adjudicate support (ACCEPTANCE_TESTS §5).

## smoke-C1-ledgerlite-routine-typo

- prohibited: Any durable lesson about README editing.
- claim `smoke-C1-ledgerlite-routine-typo:claim_02d6decf-6a82-4f84-aa29-b03e43ca19f8` [active, supported]: Running `python -m unittest discover -s tests -t .` from <run>/work/C1/c/w fails with "ImportError: Start directory is not importable".
- claim `smoke-C1-ledgerlite-routine-typo:claim_b7f270be-99c6-4da2-9975-0000f2bb4c73` [active, supported]: Running `PYTHONPATH=src python -m unittest discover -s tests` from <run>/work/C1/c/w ran 2 tests and passed (OK).
- session A: Grep ; Edit README.md
- session B: Grep ; Read src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash cd <run>/work/C1/c/w && python -m unittest discover -s tests -t . 2>&1 | tail -15 (exit 0); Bash cd <run>/work/C1/c/w && PYTHONPATH=src python -m unittest discover -s tests 2>&1 | tail -15 (exit 0)

## smoke-C2-fieldnotes-tdd-expected-red

- prohibited: The delete test fails.
- prohibited: Do not run the unit tests.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_1b760cfa-87be-4b3b-b3b4-ebd64a2a766f` [active, supported]: The fieldnotes store delete function removes the note at a 1-based index and raises IndexError when the index is out of range.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_2ff693d4-034b-43bf-91bf-8fd65fe6f697` [active, supported]: The project's checks are run with `python tools/check.py`.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_6bbbd218-d413-48f9-ae9e-9994c9d91520` [active, supported]: The fieldnotes store module keeps notes in a JSON file.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_c1c6d93a-e34b-472b-9150-2a3d039e07d2` [active, supported]: The fieldnotes CLI usage text lists `delete INDEX` alongside `add TEXT` and `list`.
- session A: Glob ; Read fieldnotes/store.py; Read fieldnotes/cli.py; Read tests/test_store.py; Read tools/check.py; Read README.md; Edit tests/test_store.py; Edit tests/test_store.py; Bash NOTES_HOME="$(mktemp -d)" python tools/check.py 2>&1 | tail -40 (exit 0); Edit fieldnotes/store.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Bash NOTES_HOME="$(mktemp -d)" python tools/check.py 2>&1 | tail -20; echo "exit=${PIPESTATUS[0]}" (exit 0)
- session B: Glob ; Bash ls -R fieldnotes tests tools; cat fieldnotes/__init__.py tools/check.py; ls (exit 0); Bash cat fieldnotes/cli.py fieldnotes/store.py tests/test_store.py README.md (exit 0); Bash python - <<'EOF'
import re
p='tests/test_store.py'
s=open(p,encoding='utf-8').read()
s=s.replace('''if __name__ == "__main__":''','''class C (exit 0); Bash python - <<'EOF'
p='fieldnotes/cli.py'
s=open(p,encoding='utf-8').read()
s=s.replace('| delete INDEX"','| delete INDEX | count"')
s=s.replac (exit 0)

## smoke-C3-household-utilities-speculation

- prohibited: Any admitted causal explanation for the September increase.
- session A: 
- session B: Read utilities-log.csv; Write utilities-plan.md

## smoke-C4-cross-project-near-match

- prohibited: ledgerlite's test command applies to fieldnotes.
- claim `smoke-C4-cross-project-near-match:claim_39a8a0da-6541-4776-8c57-605911162a4e` [active, supported]: tools/check.py runs the unittest discover suite in the tests directory and reports a failure for lines longer than 100 characters in fieldnotes/**/*.py.
- claim `smoke-C4-cross-project-near-match:claim_471e92e8-6d6c-434f-917e-41b636f1468a` [active, supported]: tools/check.py reads the NOTES_HOME environment variable with os.environ["NOTES_HOME"] and so expects NOTES_HOME to be set.
- claim `smoke-C4-cross-project-near-match:claim_a3020dfc-d0cf-420c-9409-09076041fc1f` [active, supported]: The project's README.md states that the project checks are run with `python tools/check.py`.
- session A: Glob ; Bash ls -la (exit 0); Bash cat README.md .gitignore; find src tests .claude .recalith -type f | head -50 (exit 0); Bash head -20 tests/test_ledger.py; PYTHONPATH=src python -m pytest tests -q 2>&1 | tail -15 (exit 0); Bash PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)
- session B: Glob ; Bash ls -la (exit 0); Read README.md; Read tools/check.py; Bash export NOTES_HOME="${NOTES_HOME:-$(mktemp -d)}"; python tools/check.py 2>&1 | tail -30; echo "exit=${PIPESTATUS[0]}" (exit 0)

## smoke-L1-ledgerlite-test-command

- lesson `smoke-L1-ledgerlite-test-command#0` (procedure): Run the ledgerlite tests with `PYTHONPATH=src python -m unittest discover -s tests` from the project root.
- lesson `smoke-L1-ledgerlite-test-command#1` (failure_lesson): Without PYTHONPATH=src the src-layout package is not importable from tests; plain discovery fails or runs nothing.
- prohibited: All Python projects need PYTHONPATH=src.
- prohibited: unittest discovery is broken.
- claim `smoke-L1-ledgerlite-test-command:claim_0b7998be-b00f-45c3-8829-07b10524e764` [active, corroborated]: Ledger.close(name) on a missing account raises KeyError rather than ValueError, and no test in tests/test_ledger.py covers this case.
- claim `smoke-L1-ledgerlite-test-command:claim_0d75d806-2076-43a5-94c2-1e6182dac269` [active, supported]: Ledger.close(name) in src/ledgerlite/__init__.py raises ValueError when the account's balance is not zero, and otherwise deletes the account from accounts.
- not labeled, candidate `claim_0ecd8d0b-7ab7-4175-b8e7-70d626480306` [fact, weak; review revise: Cited event does not show close() or its two tests were absent when the run occurred. / Command was piped through tail, so exit status is not captured; only output is shown.]: Running `PYTHONPATH=src .recalith/runtime/0.1.0.dev17/venv/Scripts/python.exe -m unittest discover -s tests -v` from the project root ran 2 ledgerlite tests with an OK result, before the close() method and its two tests were added to the ledgerlite source and test files.
- session A: Glob ; Bash pwd; ls -la (exit 0); Read README.md; Read tests/test_ledger.py; Read src/ledgerlite/__init__.py; Read .recalith/project.toml; Bash PYTHONPATH=src .recalith/runtime/0.1.0.dev17/venv/Scripts/python.exe -m unittest discover -s tests -v 2>&1 | tail -20 (exit 0)
- session B: Glob ; Read src/ledgerlite/__init__.py; Read tests/test_ledger.py; Edit src/ledgerlite/__init__.py; Edit tests/test_ledger.py; Bash cd <run>/work/L1/c/w && PYTHONPATH=src .recalith/runtime/0.1.0.dev17/venv/Scripts/python.exe -m unittest discover -s tests -v 2 (exit 0)

## smoke-L2-fieldnotes-iso-dates

- lesson `smoke-L2-fieldnotes-iso-dates#0` (decision): All dates printed by fieldnotes use ISO-8601; locale formats are not allowed.
- prohibited: Every project must use ISO-8601 dates.
- claim `smoke-L2-fieldnotes-iso-dates:claim_8e7985d9-370b-4592-a65b-654e6d97079a` [active, supported]: Every date fieldnotes prints must be ISO-8601 (YYYY-MM-DD...). Never use locale formats like 'Jan 2' or '02/01/2026'.
- claim `smoke-L2-fieldnotes-iso-dates:claim_d2a7c368-2dd7-42ed-aa8e-d7d0a15d5a96` [active, supported]: fieldnotes stores notes in notes.json in the directory named by the NOTES_HOME environment variable.
- not labeled, candidate `claim_68a5fc97-55d7-4044-b5f1-c31e626157d5` [fact, weak; review revise: add uses now or datetime.now(timezone.utc); a passed now overrides the default, so it is not always that call.]: The fieldnotes list command prints each note's stored created value unchanged, and add stores created as datetime.now(timezone.utc).isoformat().
- not labeled, candidate `claim_7c6867b2-327e-4811-b2a7-15c18d30c64e` [fact, weak; review revise: Cited evidence is an Edit start with outcome unknown; no run or result shows export printing as stated. / "One line per note" is unshown: note text containing newlines would print across several lines.]: fieldnotes export prints one line per note in the form `created: text`, using each note's stored created value.
- session A: Grep ; Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py
- session B: Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_store.py; Read tools/check.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Write tests/test_cli.py; Bash echo "NOTES_HOME=${NOTES_HOME-<unset>}" (exit 0); Bash cd <run>/work/L2/c/w && d=$(mktemp -d) && NOTES_HOME="$d" python tools/check.py (exit 0)

## smoke-L3-household-grocery-budget

- lesson `smoke-L3-household-grocery-budget#0` (preference): Grocery spending stays under $600 per month; plans that exceed it are flagged.
- prohibited: All budget categories are capped at $600.
- claim `smoke-L3-household-grocery-budget:claim_b5fcb07e-0d08-4829-801e-818895f6e3b8` [active, supported]: For household planning, the user said to keep the grocery budget under $600 per month and to flag anything that would push it over.
- claim `smoke-L3-household-grocery-budget:claim_b78e036b-34f6-4217-b8ef-ee548e69a7d3` [active, supported]: budget.csv has the header row category,monthly_limit_usd,notes and, before the groceries row was added, had rows for rent, utilities, transport and eating_out.
- claim `smoke-L3-household-grocery-budget:claim_d73ea019-6d87-4ebc-8fcb-e73aaf50098e` [active, supported]: budget.csv contains a groceries row with monthly_limit_usd 600 and the note "flag any spending that would push groceries over this limit".
- session A: Glob ; Read budget.csv; Bash cd "<run>\work\L3\c\w" && tail -c 1 budget.csv | xxd | head -1; printf 'groceries,600,flag any spending that would push groceri (exit 0)
- session B: Bash ls; cat budget.csv groceries.csv meal-plan.md 2>/dev/null (exit 1); Bash cat > groceries.csv <<'EOF'
item,cost_usd
Rice (10 lb),9.00
Dried pasta (6 boxes),8.50
Rolled oats (2 canisters),7.00
Dried beans and lentil (exit 0); Edit meal-plan.md; Bash grep -n "Status" meal-plan.md; wc -l groceries.csv (exit 0)

## smoke-L4-ledgerlite-resume-refactor

- claim `smoke-L4-ledgerlite-resume-refactor:claim_70131c71-170b-4331-a221-c3fc55fffc97` [active, supported]: In src/ledgerlite/__init__.py, Ledger.transfer calls money.parse(amount) in place of the inline Decimal conversion and positive-value check.
- claim `smoke-L4-ledgerlite-resume-refactor:claim_b2cba653-a4ba-4790-806e-f11d0ebbd06d` [active, supported]: src/ledgerlite/money.py defines parse(value), which accepts str or Decimal, raises TypeError for other types, and raises ValueError for unparseable, non-finite, zero or negative values.
- session A: Glob ; Read src/ledgerlite/__init__.py; Write src/ledgerlite/money.py
- session B: Glob ; Bash cd "<run>/work/L4/c/w" && ls -la src/ledgerlite tests && cat src/ledgerlite/__init__.py && echo ---- && cat tests/test_ledger.p (exit 0); Read src/ledgerlite/money.py; Edit src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash cd "<run>/work/L4/c/w" && PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)

## smoke-R1-fieldnotes-check-env-fixed

- lesson `smoke-R1-fieldnotes-check-env-fixed#0` (failure_lesson): tools/check.py fails with KeyError unless NOTES_HOME is set.
- prohibited: NOTES_HOME must always be set for every command.
- claim `smoke-R1-fieldnotes-check-env-fixed:claim_bd906f96-613c-49d9-bf2b-e1f9d1a8da6d` [active, supported]: Running `python tools/check.py` with NOTES_HOME set to a temporary directory finished with 1 unit test run and OK.
- claim `smoke-R1-fieldnotes-check-env-fixed:claim_f8491e20-7d76-4e70-bec6-8746a67ff28c` [active, supported]: Running `python tools/check.py` with NOTES_HOME unset fails with KeyError: 'NOTES_HOME' at tools/check.py line 25.
- session A: Bash python tools/check.py (exit 1); Read tools/check.py; Bash export NOTES_HOME="$(mktemp -d)" && python tools/check.py (exit 0)
- session C: Bash python tools/check.py (exit 0)

## smoke-R2-ledgerlite-import-fixed

- lesson `smoke-R2-ledgerlite-import-fixed#0` (failure_lesson): Plain discovery fails to import ledgerlite without PYTHONPATH=src.
- claim `smoke-R2-ledgerlite-import-fixed:claim_ca220c29-7b78-4874-933d-b1ecc144f0e1` [active, supported]: Running `python -m unittest discover -s tests -t .` from the repo root, after adding tests/__init__.py, runs 2 tests and ends with OK.
- claim `smoke-R2-ledgerlite-import-fixed:claim_e9ba61a7-6345-44c6-b5a6-6310813cb250` [active, supported]: Make the tests pass without changing the test command `python -m unittest discover -s tests -t .` if possible; otherwise tell the user which command works.
- not labeled, candidate `claim_48154793-801a-49d3-8e6e-0be2b45f8e2c` [fact, weak; review revise: Evidence shows the ImportError but not that tests/ lacked __init__.py when the command ran.]: Running `python -m unittest discover -s tests -t .` from the repo root fails with 'ImportError: Start directory is not importable' when tests/ has no __init__.py.
- session A: Bash python -m unittest discover -s tests -t . 2>&1 | tail -30 (exit 0); Bash ls -la . tests (exit 0); Bash cat tests/test_ledger.py README.md; ls -R src (exit 0); Bash cat src/ledgerlite/__init__.py (exit 0); Bash cat > tests/__init__.py <<'EOF'
# SPDX-License-Identifier: GPL-3.0-only
import os
import sys

# Make the src-layout package importable when  (exit 0)
- session C: Bash python -m unittest discover -s tests -t . 2>&1 | tail -30 (exit 0)

## smoke-R3-household-budget-correction

- lesson `smoke-R3-household-budget-correction#0` (preference): Grocery budget is $700 per month.
- claim `smoke-R3-household-budget-correction:claim_b2d770da-497b-4bb8-9546-141e0fc91e9d` [active, supported]: The user corrected the grocery budget to $700 per month, not $600.
- not labeled, superseded `claim_7ca9d8a5-f580-4752-b198-e15e734d0df1` [preference, supported; review supported: ]: The user asked to keep the grocery budget under $600 per month for their planning.
- session A: 
- session C: Bash cat > groceries.csv <<'EOF'
item,cost_usd
Fresh vegetables and salad greens,45
Fresh fruit,40
Potatoes/onions/garlic,18
Chicken,55
Ground be (exit 0); Bash sed -i 's/see below, kept under the \$700 limit/$688, under the $700 limit/' meal-plan.md; grep Draft meal-plan.md (exit 0)

## smoke-R4-fieldnotes-storage-conflict

- lesson `smoke-R4-fieldnotes-storage-conflict#0` (fact): Notes are stored in notes.json under NOTES_HOME.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_46afac86-5cb2-4788-9ce7-41d339717b67` [active, supported]: Notes are stored in notes.jsonl under NOTES_HOME, one JSON object per line.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_ecb59311-2a36-4b27-ad83-16a901fe86a1` [disputed, supported]: Notes are stored in notes.json under NOTES_HOME.
- session A: Glob ; Bash echo "NOTES_HOME=$NOTES_HOME" (exit 0); Read README.md; Read fieldnotes/cli.py; Read fieldnotes/store.py; Bash d=$(mktemp -d) && NOTES_HOME="$d" python -m fieldnotes.cli list; echo "exit=$?"; ls -A "$d" | wc -l (exit 0)
- session C: Glob ; Bash ls -la; ls tools fieldnotes 2>&1 (exit 0); Read fieldnotes/store.py; Read fieldnotes/cli.py; Read tools/check.py; Write tools/count_notes.py; Bash export NOTES_HOME="$(mktemp -d)"; R=<run>/work/R4/c/w
echo "before:"; python "$R/tools/count_notes.py"
(cd "$R" && python -m fi (exit 0)
