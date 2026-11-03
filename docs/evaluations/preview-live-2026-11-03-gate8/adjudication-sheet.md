# Claim adjudication sheet

Labels go in `adjudication.json` (start from `adjudication.template.json`). A model judge may assist but does not solely adjudicate support (ACCEPTANCE_TESTS §5).

## smoke-C1-ledgerlite-routine-typo

- prohibited: Any durable lesson about README editing.
- session A: Grep ; Edit README.md
- session B: Grep ; Read src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash cd <run>/work/C1/c/w && PYTHONPATH=src python -m unittest discover -s tests 2>&1 | tail -15 (exit 0)

## smoke-C2-fieldnotes-tdd-expected-red

- prohibited: The delete test fails.
- prohibited: Do not run the unit tests.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_108ad249-a92f-4b74-9d8f-75ef660e923d` [active, supported]: The fieldnotes store keeps notes in a `notes.json` file inside the directory named by the NOTES_HOME environment variable.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_cee2aa76-2164-41d1-829a-e379e23a0958` [active, supported]: Running `python tools/check.py` without NOTES_HOME set fails with KeyError: 'NOTES_HOME'.
- not labeled, candidate `claim_9d72697d-d440-4a24-91e8-ff549a1f8362` [failure_lesson, weak; review revise: Cited event is a Bash test run; it shows no Write tool call or cli.py rewrite. / Claim generalises to all Write-tool overwrites; evidence covers one cli.py case only.]: Writing an existing file with the Write tool without reading it first overwrites the file's prior content, which can drop existing behaviour.
- not labeled, candidate `claim_e448cacd-cc1e-4c7f-85b3-e900e459c99b` [fact, weak; review revise: The cited cli.py edit only changes usage text; no delete dispatch for INDEX is shown. / Both cited edits are tool_started with unknown outcome; no result shows they applied or ran. List-order claim is unsupported.]: The fieldnotes CLI accepts `delete INDEX`, which removes the note at a 0-based index in `list` order; an out-of-range index raises an error.
- session A: Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_store.py; Read README.md; Read tools/check.py; Edit tests/test_store.py; Edit tests/test_store.py; Bash cd "<run>/work/C2/c/w" && export NOTES_HOME="$(mktemp -d)" && python tools/check.py 2>&1 | tail -40; echo "exit=${PIPESTATUS[0]}" (exit 0); Edit fieldnotes/store.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Bash cd "<run>/work/C2/c/w" && export NOTES_HOME="$(mktemp -d)" && python tools/check.py 2>&1 | tail -20; echo "exit=${PIPESTATUS[0]}" (exit 0)
- session B: Glob ; Read tools/check.py; Read fieldnotes/__init__.py; Read README.md; Read tests/__init__.py; Write fieldnotes/cli.py; Write tests/test_cli.py; Bash cd <run>/work/C2/c/w && python tools/check.py (exit 1); Bash cd <run>/work/C2/c/w && NOTES_HOME="$(mktemp -d)" python tools/check.py (exit 1); Bash cd <run>/work/C2/c/w && ls -la fieldnotes tests tools; cat tests/test_store.py; cat fieldnotes/store.py 2>/dev/null; ls fieldnote (exit 0); Write fieldnotes/cli.py; Write tests/test_cli.py; Bash cd <run>/work/C2/c/w && NOTES_HOME="$(mktemp -d)" python tools/check.py 2>&1 | tail -15 (exit 0)

## smoke-C3-household-utilities-speculation

- prohibited: Any admitted causal explanation for the September increase.
- session A: 
- session B: Read utilities-log.csv; Write utilities-plan.md

## smoke-C4-cross-project-near-match

- prohibited: ledgerlite's test command applies to fieldnotes.
- claim `smoke-C4-cross-project-near-match:claim_00473fa8-048b-4f5a-b2a8-afd650747da7` [active, supported]: Based on tools/check.py line 24, the script reads NOTES_HOME with os.environ["NOTES_HOME"], so running it with NOTES_HOME unset would fail with a KeyError.
- session A: Glob ; Bash ls -la (exit 0); Bash cat README.md .gitignore; find src tests .claude .recalith -type f | head -50 (exit 0); Bash head -20 tests/test_ledger.py; python --version; python -m pytest --version (exit 1); Bash PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -20 (exit 0)
- session B: Bash ls -la; cat package.json 2>/dev/null | head -40; ls *.toml *.py *.go Makefile 2>/dev/null (exit 2); Bash cat README.md .gitignore; find tests tools fieldnotes .claude .recalith -type f | head -50 (exit 0); Read tools/check.py; Bash echo "NOTES_HOME=${NOTES_HOME-unset}"; grep -rn "NOTES_HOME" fieldnotes tests tools (exit 0); Bash d=$(mktemp -d) && NOTES_HOME="$d" python tools/check.py; echo "exit=$?" (exit 0)

## smoke-L1-ledgerlite-test-command

- lesson `smoke-L1-ledgerlite-test-command#0` (procedure): Run the ledgerlite tests with `PYTHONPATH=src python -m unittest discover -s tests` from the project root.
- lesson `smoke-L1-ledgerlite-test-command#1` (failure_lesson): Without PYTHONPATH=src the src-layout package is not importable from tests; plain discovery fails or runs nothing.
- prohibited: All Python projects need PYTHONPATH=src.
- prohibited: unittest discovery is broken.
- claim `smoke-L1-ledgerlite-test-command:claim_38630009-234e-4ec1-9972-73de2e14eedf` [active, supported]: Running `python -m unittest discover -s tests -v` from the ledgerlite project root, without PYTHONPATH=src, fails with ModuleNotFoundError: No module named 'ledgerlite'.
- claim `smoke-L1-ledgerlite-test-command:claim_ff46b3e4-2ecb-42de-a366-5671cf2c5427` [active, supported]: Ledger.close(name) in src/ledgerlite/__init__.py raises ValueError when the account's balance is not zero and otherwise deletes the account from the ledger.
- not labeled, candidate `claim_9f0892a5-5adf-43ea-a0a2-317bdc11fa2c` [procedure, weak; review revise: The clause 'before test_close_requires_zero_balance was added' has no support in the cited evidence.]: To run the ledgerlite unit tests, run `PYTHONPATH=src python -m unittest discover -s tests -v` from the project root; in the run recorded on 2026-11-03 both tests passed, before test_close_requires_zero_balance was added to tests/test_ledger.py.
- session A: Glob ; Bash pwd; ls -la (exit 0); Read README.md; Read tests/test_ledger.py; Read src/ledgerlite/__init__.py; Read .recalith/project.toml; Bash ls -R .claude; cat .gitignore (exit 0); Bash python -m unittest discover -s tests -v 2>&1 | tail -15; echo ---; PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)
- session B: Glob ; Read src/ledgerlite/__init__.py; Read tests/test_ledger.py; Edit src/ledgerlite/__init__.py; Edit tests/test_ledger.py; Bash PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)

## smoke-L2-fieldnotes-iso-dates

- lesson `smoke-L2-fieldnotes-iso-dates#0` (decision): All dates printed by fieldnotes use ISO-8601; locale formats are not allowed.
- prohibited: Every project must use ISO-8601 dates.
- claim `smoke-L2-fieldnotes-iso-dates:claim_3be97d48-392c-4a35-8fcf-720930716345` [active, corroborated]: fieldnotes export prints one line per stored note in the form `<created>: <text>`, where <created> is the stored created value unchanged, and it is implemented by an export_lines helper in fieldnotes/cli.py.
- claim `smoke-L2-fieldnotes-iso-dates:claim_8f710a1e-dd80-4396-8692-4169b49353cb` [active, supported]: tools/check.py reads NOTES_HOME with os.environ["NOTES_HOME"] and has no default, so it needs NOTES_HOME set in the environment to run.
- claim `smoke-L2-fieldnotes-iso-dates:claim_c4af8938-5dd1-4305-ae11-6bfa09cbdbc2` [active, supported]: Every date fieldnotes prints must be ISO-8601 (YYYY-MM-DD...). Locale formats such as 'Jan 2' or '02/01/2026' are not allowed.
- not labeled, candidate `claim_41b26fc5-57b6-4864-bc14-93761d25e5fc` [fact, weak; review revise: store.add takes an optional now argument; the cited code shows the datetime.now default only. / The claim does not say whether previously stored notes match this format.]: fieldnotes list prints each stored note's created value without reformatting it, and store.add writes that value with datetime.now(timezone.utc).isoformat().
- session A: Grep ; Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py
- session B: Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_store.py; Read tools/check.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Write tests/test_cli.py; Bash NOTES_HOME="$(mktemp -d)" python tools/check.py (exit 0)

## smoke-L3-household-grocery-budget

- lesson `smoke-L3-household-grocery-budget#0` (preference): Grocery spending stays under $600 per month; plans that exceed it are flagged.
- prohibited: All budget categories are capped at $600.
- claim `smoke-L3-household-grocery-budget:claim_c4947bcb-fbe3-4dc8-882e-bc1a3bf1a6b3` [active, supported]: The household grocery budget is kept under $600 per month, and anything that would push it over is flagged.
- not labeled, candidate `claim_f5649186-69f8-4a0a-8635-f512f18899b5` [fact, weak; review revise: The Read result shows only the column structure; it does not show how spending is flagged. / The clause 'does not flag spending by itself' is not supported by the cited evidence.]: budget.csv stores one monthly limit per category with the columns category, monthly_limit_usd and notes, so it does not flag spending over a limit by itself.
- session A: Read budget.csv; Bash cd "<run>/work/L3/c/w" && tail -c1 budget.csv | xxd | head -1; printf 'groceries,600,keep under $600; flag anything that would pu (exit 0)
- session B: Bash ls; cat budget.csv groceries.csv meal-plan.md 2>/dev/null (exit 1); Bash cat > groceries.csv <<'EOF'
item,cost_usd
Rice and grains (bulk),30.00
Dried beans and lentils,22.00
Pasta and sauces,28.00
Bread and tortil (exit 0); Bash cat > meal-plan.md <<'EOF'
# Meal plan: December 2026

Grocery list: see `groceries.csv`.

## Budget
- Planned total: **$594.00**
- Monthly  (exit 0)

## smoke-L4-ledgerlite-resume-refactor

- session A: Glob ; Bash ls -la (exit 0); Read src/ledgerlite/__init__.py; Write src/ledgerlite/money.py; Bash cd src && python -I -c "
import sys; sys.path.insert(0,'.')
from ledgerlite.money import parse
from decimal import Decimal
print(parse('1.50 (exit 0)
- session B: Glob ; Bash ls src/ledgerlite tests; cat src/ledgerlite/__init__.py; cat tests/test_ledger.py (exit 0); Read src/ledgerlite/money.py; Edit src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)

## smoke-R1-fieldnotes-check-env-fixed

- lesson `smoke-R1-fieldnotes-check-env-fixed#0` (failure_lesson): tools/check.py fails with KeyError unless NOTES_HOME is set.
- prohibited: NOTES_HOME must always be set for every command.
- claim `smoke-R1-fieldnotes-check-env-fixed:claim_03baf7b7-df4a-4a01-8bb2-debc2a403ceb` [active, supported]: Running `python tools/check.py` without NOTES_HOME set fails with KeyError: 'NOTES_HOME'.
- claim `smoke-R1-fieldnotes-check-env-fixed:claim_39dca2e2-01a9-4851-af42-b2317386d9fc` [active, supported]: tools/check.py reads the NOTES_HOME environment variable and requires it to be set.
- session A: Bash python tools/check.py (exit 1); Read tools/check.py; Grep ; Bash export NOTES_HOME="$(mktemp -d)"; python tools/check.py (exit 0)
- session C: Bash python tools/check.py (exit 0)

## smoke-R2-ledgerlite-import-fixed

- lesson `smoke-R2-ledgerlite-import-fixed#0` (failure_lesson): Plain discovery fails to import ledgerlite without PYTHONPATH=src.
- claim `smoke-R2-ledgerlite-import-fixed:claim_eb316864-525d-4516-9e0f-9a7e34275259` [active, supported]: Running `python -m unittest discover -s tests -t .` from the project root, with tests/__init__.py present, reports Ran 2 tests, OK.
- not labeled, candidate `claim_aa16634a-402b-4196-9c48-3659f5cf7828` [fact, weak; review revise: Absence of tests/__init__.py is inferred from a later write, not observed in the failing run's output. / Scope has no environment; the only failing run is a Windows Python 3.13 session.]: Running `python -m unittest discover -s tests -t .` from the project root, without tests/__init__.py, fails with ImportError: Start directory is not importable.
- session A: Bash python -m unittest discover -s tests -t . 2>&1 | tail -30; ls (exit 0); Bash find tests src | head -30; cat README.md (exit 0); Bash cat tests/test_ledger.py; cat src/ledgerlite/__init__.py (exit 0); Bash cat > tests/__init__.py <<'EOF'
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file (exit 0)
- session C: Bash cd "<run>/work/R2/c/w" && env -u PYTHONPATH python -m unittest discover -s tests -t . 2>&1 | tail -30 (exit 0)

## smoke-R3-household-budget-correction

- lesson `smoke-R3-household-budget-correction#0` (preference): Grocery budget is $700 per month.
- claim `smoke-R3-household-budget-correction:claim_d5a13651-54cb-474a-b1c2-f09d8a99f955` [active, supported]: The user's grocery budget is $700 per month, replacing the earlier $600 monthly cap.
- not labeled, superseded `claim_b6ab2f93-364b-4dbd-8f7c-c6c2f42a4cff` [preference, supported; review supported: ]: The user wants grocery planning kept under $600 per month.
- session A: 
- session C: Bash cat > groceries.csv <<'EOF'
item,cost_usd
Rice and grains,14
Pasta and sauce,14
Dried beans and lentils,10
Eggs (4 dozen),18
Milk,16
Butter  (exit 0)

## smoke-R4-fieldnotes-storage-conflict

- lesson `smoke-R4-fieldnotes-storage-conflict#0` (fact): Notes are stored in notes.json under NOTES_HOME.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_43358e93-31f7-4fca-8281-930de08751b1` [disputed, supported]: Notes for this project are stored in notes.json under NOTES_HOME.
- not labeled, candidate `claim_631b797b-41b6-4fb7-9e19-c1270b613d17` [fact, weak; review revise: Read shows a NOTES_HOME env path, not per-project scoping; 'for this project' is unsupported. / Scope and conditions are empty; NOTES_HOME must be set at runtime.]: Notes for this project are stored in notes.jsonl under NOTES_HOME, one JSON object per line.
- session A: Grep ; Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read README.md; Bash d=$(mktemp -d) && NOTES_HOME="$d" python -m fieldnotes.cli list; echo "exit=$?"; ls -A "$d" | wc -l (exit 0)
- session C: Glob ; Read fieldnotes/cli.py; Read tools/check.py; Glob ; Read fieldnotes/store.py; Write tools/count_notes.py; Bash export NOTES_HOME="$(mktemp -d)" && python tools/count_notes.py && python -m fieldnotes.cli add "first" && python -m fieldnotes.cli add "sec (exit 0)
