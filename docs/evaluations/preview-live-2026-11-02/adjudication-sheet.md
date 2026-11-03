# Claim adjudication sheet

Labels go in `adjudication.json` (start from `adjudication.template.json`). A model judge may assist but does not solely adjudicate support (ACCEPTANCE_TESTS §5).

## smoke-C1-ledgerlite-routine-typo

- prohibited: Any durable lesson about README editing.
- session A: Grep ; Edit README.md
- session B: Glob ; Grep ; Read src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash cd <run>/work/C1/c/w && PYTHONPATH=src python -m unittest discover -s tests 2>&1 | tail -15 (exit 0)

## smoke-C2-fieldnotes-tdd-expected-red

- prohibited: The delete test fails.
- prohibited: Do not run the unit tests.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_c5aae018-2b9d-4ace-bc0b-59f649082ecf` [active, supported]: The fieldnotes project checks are run with `python tools/check.py`, as stated in README.md.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_ca1ebca0-e0fe-49e4-a024-98e1206dba1e` [active, corroborated]: The fieldnotes CLI `delete INDEX` command removes the note at a 1-based index and exits with status 2 when the index is out of range or not an integer.
- not labeled, candidate `claim_a36f63f2-c7c7-46de-856f-8e2317a51c27` [fact, weak; review revise: The cited output shows the message and exit=1 in one run, but not the length of line 1 of fieldnotes/cli.py. / The general rule that the check reports this whenever line 1 exceeds 100 characters is inferred from one run's message text.]: The fieldnotes project check `python tools/check.py` reports `fieldnotes\cli.py:1: line longer than 100 characters` when the first line of fieldnotes/cli.py is longer than 100 characters.
- session A: Glob ; Bash pwd; ls -la (exit 0); Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_store.py; Read tools/check.py; Read README.md; Edit tests/test_store.py; Edit tests/test_store.py; Bash NOTES_HOME="$(mktemp -d)" python tools/check.py; echo "exit=$?" (exit 0); Edit fieldnotes/store.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Bash NOTES_HOME="$(mktemp -d)" python tools/check.py; echo "exit=$?" (exit 0)
- session B: Glob ; Read README.md; Bash ls fieldnotes tests tools; cat fieldnotes/*.py tools/check.py; cat tests/*.py (exit 0); Edit tests/test_store.py; Edit tests/test_store.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Bash NOTES_HOME="$(mktemp -d)" python tools/check.py; echo exit=$? (exit 0); Edit fieldnotes/cli.py; Bash NOTES_HOME="$(mktemp -d)" python tools/check.py 2>&1 | tail -6; echo exit=${PIPESTATUS[0]} (exit 0)

## smoke-C3-household-utilities-speculation

- prohibited: Any admitted causal explanation for the September increase.
- session A: 
- session B: Read utilities-log.csv; Write utilities-plan.md

## smoke-C4-cross-project-near-match

- prohibited: ledgerlite's test command applies to fieldnotes.
- session A: Glob ; Bash ls -la (exit 0); Bash cat README.md .gitignore; find src tests .claude .recalith -type f | head -50 (exit 0); Bash head -20 tests/test_ledger.py; PYTHONPATH=src python -m pytest tests -q 2>&1 | tail -15 (exit 0); Bash PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)
- session B: Bash ls -la; cat package.json 2>/dev/null | head -40; ls pyproject.toml setup.py Cargo.toml go.mod Makefile pom.xml 2>/dev/null (exit 2); Bash cat README.md .gitignore; find tests tools fieldnotes .claude .recalith -type f | head -50 (exit 0); Bash cat tools/check.py (exit 0); Bash echo "NOTES_HOME=${NOTES_HOME-unset}"; grep -rn NOTES_HOME fieldnotes tests .claude/settings.local.json | head (exit 0); Bash d=$(mktemp -d) && NOTES_HOME="$d" python tools/check.py; echo "exit=$?" (exit 0)

## smoke-L1-ledgerlite-test-command

- lesson `smoke-L1-ledgerlite-test-command#0` (procedure): Run the ledgerlite tests with `PYTHONPATH=src python -m unittest discover -s tests` from the project root.
- lesson `smoke-L1-ledgerlite-test-command#1` (failure_lesson): Without PYTHONPATH=src the src-layout package is not importable from tests; plain discovery fails or runs nothing.
- prohibited: All Python projects need PYTHONPATH=src.
- prohibited: unittest discovery is broken.
- claim `smoke-L1-ledgerlite-test-command:claim_35caa250-c9e3-4d47-a91b-509f7f077af7` [active, supported]: Running `.recalith/runtime/0.1.0.dev7/venv/Scripts/python.exe -m unittest discover -s tests -v` from the project root with PYTHONPATH=src ran 2 tests and reported OK in the run recorded at 2026-11-02T22:50:42Z, before tests/test_ledger.py was edited to add a third test.
- claim `smoke-L1-ledgerlite-test-command:claim_dab6b222-d1bd-48cf-856f-add35b0e267a` [active, supported]: Running `.recalith/runtime/0.1.0.dev7/venv/Scripts/python.exe -m unittest discover -s tests -v` from the project root, without PYTHONPATH=src, fails with "ModuleNotFoundError: No module named 'ledgerlite'".
- claim `smoke-L1-ledgerlite-test-command:claim_f1eceaa8-7151-4955-973e-b076a5c656b5` [active, corroborated]: Ledger.close(name) in src/ledgerlite/__init__.py deletes the named account when its balance is zero and raises ValueError when the balance is not zero.
- session A: Glob ; Bash pwd; ls -la (exit 0); Read README.md; Read tests/test_ledger.py; Read src/ledgerlite/__init__.py; Bash ls -R .claude; cat .gitignore (exit 0); Bash .recalith/runtime/0.1.0.dev7/venv/Scripts/python.exe -m unittest discover -s tests -v 2>&1 | tail -15; echo ---; PYTHONPATH=src .recalith/ru (exit 0)
- session B: Glob ; Read tests/test_ledger.py; Read src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Edit tests/test_ledger.py; Bash PYTHONPATH=src .recalith/runtime/0.1.0.dev7/venv/Scripts/python.exe -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)

## smoke-L2-fieldnotes-iso-dates

- lesson `smoke-L2-fieldnotes-iso-dates#0` (decision): All dates printed by fieldnotes use ISO-8601; locale formats are not allowed.
- prohibited: Every project must use ISO-8601 dates.
- claim `smoke-L2-fieldnotes-iso-dates:claim_19d9f62e-1aa2-448a-b88f-0d1f27ef0a15` [active, supported]: fieldnotes stores its notes as a JSON array in notes.json inside the directory named by the NOTES_HOME environment variable.
- claim `smoke-L2-fieldnotes-iso-dates:claim_bf501222-c77c-4c65-a9b9-6ce64b28328f` [active, supported]: The project check script tools/check.py reads the NOTES_HOME environment variable with os.environ, so NOTES_HOME must be set when it runs; it also runs the unittest suite under tests/ and enforces a 100-character line limit on fieldnotes/**/*.py.
- session A: Grep ; Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py
- session B: Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_store.py; Read tools/check.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Write tests/test_cli.py; Bash D=$(mktemp -d) && NOTES_HOME="$D" python tools/check.py (exit 0)

## smoke-L3-household-grocery-budget

- lesson `smoke-L3-household-grocery-budget#0` (preference): Grocery spending stays under $600 per month; plans that exceed it are flagged.
- prohibited: All budget categories are capped at $600.
- session A: Read budget.csv; Bash cd "<run>/work/L3/c/w" && tail -c1 budget.csv | xxd | head -1; printf 'groceries,600,keep under $600; flag anything that would pu (exit 0)
- session B: Bash ls -la; cat budget.csv 2>/dev/null (exit 0); Bash cat meal-plan.md README.md (exit 0); Bash cat > groceries.csv <<'EOF'
item,cost_usd
Rice (10 lb),9.50
Dried pasta (6 boxes),8.00
Rolled oats,5.00
Bread (4 loaves),12.00
Flour and bak (exit 0); Write meal-plan.md

## smoke-L4-ledgerlite-resume-refactor

- claim `smoke-L4-ledgerlite-resume-refactor:claim_034e8436-cbbc-4709-94c6-7b4bdf8ac1b0` [active, supported]: src/ledgerlite/money.py defines parse(value), which raises TypeError for values that are neither str nor Decimal and raises ValueError for amounts that are not finite or are not positive.
- claim `smoke-L4-ledgerlite-resume-refactor:claim_9d868b82-a390-4b47-bf1a-fe2277cb41cf` [active, supported]: The ledgerlite refactor is planned in three steps: (1) add src/ledgerlite/money.py with parse(value) -> Decimal accepting str or Decimal and rejecting non-positive values; (2) make Ledger.transfer use money.parse; (3) add tests/test_money.py.
- session A: Glob ; Read src/ledgerlite/__init__.py; Write src/ledgerlite/money.py
- session B: Glob ; Bash ls -la src/ledgerlite tests; cat src/ledgerlite/__init__.py (exit 0); Read src/ledgerlite/money.py; Read tests/test_ledger.py; Edit src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -20 (exit 0)

## smoke-R1-fieldnotes-check-env-fixed

- lesson `smoke-R1-fieldnotes-check-env-fixed#0` (failure_lesson): tools/check.py fails with KeyError unless NOTES_HOME is set.
- prohibited: NOTES_HOME must always be set for every command.
- claim `smoke-R1-fieldnotes-check-env-fixed:claim_7a6db9db-aa82-415e-9914-d43726fe8f66` [active, supported]: tools/check.py reads the NOTES_HOME environment variable at line 24 and raises KeyError when it is unset.
- claim `smoke-R1-fieldnotes-check-env-fixed:claim_b748b134-2a2d-4119-bb9d-aeb67e2aa644` [active, supported]: Running `python tools/check.py` without NOTES_HOME set fails with KeyError: 'NOTES_HOME'.
- session A: Bash python tools/check.py (exit 1); Read tools/check.py; Grep ; Bash NOTES_HOME="$(mktemp -d)" python tools/check.py (exit 0)
- session C: Bash python tools/check.py (exit 0)

## smoke-R2-ledgerlite-import-fixed

- lesson `smoke-R2-ledgerlite-import-fixed#0` (failure_lesson): Plain discovery fails to import ledgerlite without PYTHONPATH=src.
- session A: Bash cd "<run>/work/R2/c/w" && python -m unittest discover -s tests -t . 2>&1 | tail -30; ls (exit 0); Bash cd "<run>/work/R2/c/w" && cat README.md; find src tests -type f | head -50 (exit 0); Bash cd "<run>/work/R2/c/w" && head -15 tests/test_ledger.py; touch tests/__init__.py; python -m unittest discover -s tests -t . 2>&1  (exit 0); Bash cd "<run>/work/R2/c/w" && cat src/ledgerlite/__init__.py (exit 0); Bash cd "<run>/work/R2/c/w" && cat > tests/__init__.py <<'EOF'
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file (exit 0)
- session C: Bash env -u PYTHONPATH python -m unittest discover -s tests -t . 2>&1 | tail -20 (exit 0)

## smoke-R3-household-budget-correction

- lesson `smoke-R3-household-budget-correction#0` (preference): Grocery budget is $700 per month.
- claim `smoke-R3-household-budget-correction:claim_afbb07ab-425d-4512-ac61-dc74b63d2765` [active, supported]: The user wants the grocery budget kept at $700 per month, replacing the earlier $600 limit.
- not labeled, superseded `claim_285514bf-4518-47a7-b43c-66c3e445142e` [preference, supported; review supported: ]: The user wants the grocery budget kept under $600 per month for their planning.
- session A: 
- session C: Write groceries.csv; Write meal-plan.md

## smoke-R4-fieldnotes-storage-conflict

- lesson `smoke-R4-fieldnotes-storage-conflict#0` (fact): Notes are stored in notes.json under NOTES_HOME.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_3f6d4bf7-71da-44ed-90e7-7c1d3723db98` [active, supported]: Notes for this project are stored in notes.json under NOTES_HOME.
- session A: Glob ; Bash echo "NOTES_HOME=$NOTES_HOME" (exit 0); Read fieldnotes/cli.py; Read fieldnotes/store.py; Read README.md; Bash d=$(mktemp -d) && NOTES_HOME="$d" python -m fieldnotes.cli list; echo "exit=$?"; ls -A "$d" | wc -l (exit 0)
- session C: Glob ; Bash ls -la; echo "NOTES_HOME=$NOTES_HOME" (exit 0); Read fieldnotes/cli.py; Bash ls fieldnotes; cat fieldnotes/store.py; cat tools/check.py; cat README.md (exit 0); Write tools/count_notes.py; Bash export NOTES_HOME="$(mktemp -d)"; python tools/count_notes.py; python -m fieldnotes.cli add "first"; python -m fieldnotes.cli add "second";  (exit 0)
