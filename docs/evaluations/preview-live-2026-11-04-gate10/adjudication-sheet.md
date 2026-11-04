# Claim adjudication sheet

Labels go in `adjudication.json` (start from `adjudication.template.json`). A model judge may assist but does not solely adjudicate support (ACCEPTANCE_TESTS §5).

## smoke-C1-ledgerlite-routine-typo

- prohibited: Any durable lesson about README editing.
- session A: Grep ; Edit README.md
- session B: Grep ; Read src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash cd <run>/work/C1/c/w && PYTHONPATH=src python -m unittest discover -s tests 2>&1 | tail -15 (exit 0)

## smoke-C2-fieldnotes-tdd-expected-red

- prohibited: The delete test fails.
- prohibited: Do not run the unit tests.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_db278424-4523-4f99-9475-7565ecc2392c` [active, supported]: The project checks are run with `python tools/check.py`.
- session A: Glob ; Bash ls -la (exit 0); Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_store.py; Read tools/check.py; Read README.md; Edit tests/test_store.py; Edit tests/test_store.py; Bash cd <run>/work/C2/c/w && python -m unittest discover -s tests -t . 2>&1 | tail -40 (exit 0); Edit fieldnotes/store.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Bash cd <run>/work/C2/c/w && d=$(mktemp -d) && NOTES_HOME="$d" python tools/check.py 2>&1 | tail -20; echo "exit=${PIPESTATUS[0]}" (exit 0)
- session B: Read README.md; Glob ; Read fieldnotes/__init__.py; Read tools/check.py; Read tests/__init__.py; Write fieldnotes/cli.py; Write tests/test_cli.py; Bash cd <run>/work/C2/c/w && NOTES_HOME="$(mktemp -d)" python tools/check.py (exit 1); Bash cd <run>/work/C2/c/w && ls -la fieldnotes tests tools; cat tests/test_store.py; cat fieldnotes/store.py 2>/dev/null; ls fieldnot (exit 0); Write fieldnotes/cli.py; Write tests/test_cli.py; Bash cd <run>/work/C2/c/w && NOTES_HOME="$(mktemp -d)" python tools/check.py 2>&1 | tail -15 (exit 0)

## smoke-C3-household-utilities-speculation

- prohibited: Any admitted causal explanation for the September increase.
- session A: 
- session B: Read utilities-log.csv; Write utilities-plan.md

## smoke-C4-cross-project-near-match

- prohibited: ledgerlite's test command applies to fieldnotes.
- claim `smoke-C4-cross-project-near-match:claim_38f942e2-c2d3-45b1-8dc0-7cb56bcb3a99` [active, supported]: tools/check.py reads the NOTES_HOME environment variable with os.environ["NOTES_HOME"] and prints its value before running the unit tests.
- claim `smoke-C4-cross-project-near-match:claim_4dfcb38e-ca7c-4b1b-bdbd-fdd0d3294a15` [active, supported]: README.md says the project checks are run with `python tools/check.py`.
- not labeled, candidate `claim_4bd20b28-e0d3-4e25-93f3-8ee973ed64ec` [procedure, weak; review revise: Evidence shows NOTES_HOME set to a mktemp directory; a temporary directory requirement is not shown. / check.py also enforces a 100-character line-length rule, which the procedure does not mention.]: To run the project tests, set NOTES_HOME to a temporary directory and run `python tools/check.py`.
- session A: Glob ; Bash ls -la (exit 0); Bash cat README.md .gitignore; find src tests .claude .recalith -type f | head -50 (exit 0); Bash head -20 tests/test_ledger.py; python --version; python -m pytest --version (exit 1); Bash PYTHONPATH=src python -m unittest discover -s tests -v (exit 0)
- session B: Glob ; Bash ls -la (exit 0); Read README.md; Read tools/check.py; Grep ; Bash echo "NOTES_HOME=${NOTES_HOME-unset}"; ls .claude; cat .gitignore (exit 0); Bash export NOTES_HOME="$(mktemp -d)"; python tools/check.py; echo "exit=$?" (exit 0)

## smoke-L1-ledgerlite-test-command

- lesson `smoke-L1-ledgerlite-test-command#0` (procedure): Run the ledgerlite tests with `PYTHONPATH=src python -m unittest discover -s tests` from the project root.
- lesson `smoke-L1-ledgerlite-test-command#1` (failure_lesson): Without PYTHONPATH=src the src-layout package is not importable from tests; plain discovery fails or runs nothing.
- prohibited: All Python projects need PYTHONPATH=src.
- prohibited: unittest discovery is broken.
- claim `smoke-L1-ledgerlite-test-command:claim_3133a05c-5955-4ed5-bb95-76ff3a5ecd4f` [active, supported]: In the recorded run, running `PYTHONPATH=src python -m unittest discover -s tests -v` from the project root reported both ledgerlite tests as ok.
- claim `smoke-L1-ledgerlite-test-command:claim_f08e22cb-125e-41dd-b007-b8b86bd60f4e` [active, supported]: Running the ledgerlite tests with `python -m unittest discover -s tests` from the project root, without PYTHONPATH=src, fails with `FAILED (errors=1)`.
- not labeled, candidate `claim_e54b7c03-b4c3-48fd-90ba-00c1b0a67426` [fact, weak; review revise: Evidence shows pytest missing from one Python 3.13 install, not that it is this project's environment. / Evidence does not show the so-clause: tests run with unittest because pytest is absent.]: pytest is not installed in the Python 3.13 environment used for this project, so the ledgerlite tests are run with unittest.
- session A: Glob ; Bash ls -la (exit 0); Bash cat README.md .gitignore; find src tests .claude .recalith -type f | head -50 (exit 0); Read tests/test_ledger.py; Read src/ledgerlite/__init__.py; Bash python -m pytest --version; python --version (exit 0); Bash python -m unittest discover -s tests 2>&1 | tail -5; echo ---; PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -10 (exit 0)
- session B: Glob ; Read src/ledgerlite/__init__.py; Read tests/test_ledger.py; Edit src/ledgerlite/__init__.py; Edit tests/test_ledger.py; Bash cd <run>/work/L1/c/w && PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)

## smoke-L2-fieldnotes-iso-dates

- lesson `smoke-L2-fieldnotes-iso-dates#0` (decision): All dates printed by fieldnotes use ISO-8601; locale formats are not allowed.
- prohibited: Every project must use ISO-8601 dates.
- claim `smoke-L2-fieldnotes-iso-dates:claim_4ae9d90e-11de-4894-b65b-969326873d33` [active, supported]: `tools/check.py` reads the `NOTES_HOME` environment variable with `os.environ["NOTES_HOME"]` and prints its value before running the unit tests.
- claim `smoke-L2-fieldnotes-iso-dates:claim_a45fd9e9-f747-4d21-a0e1-797e46fadc35` [active, supported]: `fieldnotes export` prints one line per note in the form `<created>: <text>`, where `<created>` is the note's stored `created` value.
- claim `smoke-L2-fieldnotes-iso-dates:claim_da35dc73-4f88-40e9-bb84-833d34b69bf5` [active, supported]: Every date fieldnotes prints must be ISO-8601 (YYYY-MM-DD...). Never use locale formats like 'Jan 2' or '02/01/2026'.
- claim `smoke-L2-fieldnotes-iso-dates:claim_da7245ea-f6a5-4531-a81d-f06a4ab11bb1` [active, corroborated]: `fieldnotes list` prints each note's stored `created` value as read from the store, without reformatting it. `add` stores `created` as `moment.isoformat()`, with `moment` defaulting to `datetime.now(timezone.utc)`.
- session A: Grep ; Glob ; Grep ; Read fieldnotes/cli.py; Read fieldnotes/store.py
- session B: Glob ; Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_store.py; Read tools/check.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Write tests/test_cli.py; Bash NOTES_HOME="$(mktemp -d)" python tools/check.py (exit 0)

## smoke-L3-household-grocery-budget

- lesson `smoke-L3-household-grocery-budget#0` (preference): Grocery spending stays under $600 per month; plans that exceed it are flagged.
- prohibited: All budget categories are capped at $600.
- claim `smoke-L3-household-grocery-budget:claim_c7c29fdd-481d-4419-83e4-0fdd643793c8` [active, supported]: For household planning, keep the grocery budget under $600 per month and flag anything that would push it over.
- not labeled, archived `claim_46f813fc-bac3-4e53-a2c5-0bb2bdf44689` [fact, weak; review reject: Event only requests drafting; it does not show the list was drafted. / Summary in meal-plan.md is only requested, not shown as completed.]: The grocery list is drafted in groceries.csv with columns item,cost_usd, and summarized in meal-plan.md.
- session A: Read budget.csv; Bash cd "<run>/work/L3/c/w" && tail -c1 budget.csv | xxd | head -1; printf 'groceries,600,keep under $600; flag anything that would p (exit 0)
- session B: Bash ls -la; cat budget.csv 2>/dev/null (exit 0); Bash cat meal-plan.md README.md (exit 0); Bash cat > groceries.csv <<'EOF'
item,cost_usd
Rice (10 lb),9.50
Dried pasta (6 boxes),8.00
Rolled oats,5.50
Bread (4 loaves),12.00
Tortillas,4.5 (exit 0); Write meal-plan.md

## smoke-L4-ledgerlite-resume-refactor

- claim `smoke-L4-ledgerlite-resume-refactor:claim_5265e684-e3e9-4807-9834-25ac4369697d` [active, supported]: src/ledgerlite/money.py defines parse(value: str | Decimal) -> Decimal. It returns a finite Decimal greater than zero, raises TypeError for values that are not str or Decimal, and raises ValueError for unparseable, non-finite, or non-positive values.
- claim `smoke-L4-ledgerlite-resume-refactor:claim_893d18a9-9d9c-4b14-b1c5-a34aa521d5c7` [active, supported]: Running `ls && PYTHONPATH=src python -m pytest -q 2>&1 | tail -20` from the project root, with the Python 3.13 installed at <home>\AppData\Local\Programs\Python\Python313\python.exe, fails with 'No module named pytest'.
- claim `smoke-L4-ledgerlite-resume-refactor:claim_accb1ca9-fc9a-4355-9604-77b709bb5d52` [active, supported]: Running `PYTHONPATH=src python -m unittest discover -s tests -v` from the project root runs the two tests in the tests directory, and both passed after the transfer change.
- claim `smoke-L4-ledgerlite-resume-refactor:claim_f65b6694-6bb1-43ff-a0a1-efe0c4171167` [active, corroborated]: In src/ledgerlite/__init__.py, Ledger.transfer converts its amount argument with money.parse(amount) before updating the source and target balances, and the module imports money with `from . import money`.
- session A: Glob ; Read src/ledgerlite/__init__.py; Write src/ledgerlite/money.py
- session B: Read src/ledgerlite/__init__.py; Read src/ledgerlite/money.py; Edit src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash ls && PYTHONPATH=src python -m pytest -q 2>&1 | tail -20 (exit 0); Bash ls tests; PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -20 (exit 0)

## smoke-R1-fieldnotes-check-env-fixed

- lesson `smoke-R1-fieldnotes-check-env-fixed#0` (failure_lesson): tools/check.py fails with KeyError unless NOTES_HOME is set.
- prohibited: NOTES_HOME must always be set for every command.
- claim `smoke-R1-fieldnotes-check-env-fixed:claim_33af0d62-bc73-4299-8f31-9b627337933b` [active, supported]: tools/check.py reads the NOTES_HOME environment variable at line 24.
- claim `smoke-R1-fieldnotes-check-env-fixed:claim_87692ab3-93bf-4a48-b99a-d3ca7fd50b43` [active, supported]: Running `python tools/check.py` with NOTES_HOME unset fails with KeyError: 'NOTES_HOME' at tools/check.py:24.
- session A: Bash python tools/check.py (exit 1); Read tools/check.py; Grep ; Bash d=$(mktemp -d) && NOTES_HOME="$d" python tools/check.py (exit 0)
- session C: Bash python tools/check.py (exit 0)

## smoke-R2-ledgerlite-import-fixed

- lesson `smoke-R2-ledgerlite-import-fixed#0` (failure_lesson): Plain discovery fails to import ledgerlite without PYTHONPATH=src.
- claim `smoke-R2-ledgerlite-import-fixed:claim_9dd474d2-7292-4219-b8de-cf46cb30c283` [active, supported]: The user prefers that the test command not be changed if possible.
- claim `smoke-R2-ledgerlite-import-fixed:claim_a671e336-1827-4857-87ff-c8a0fc8232cb` [active, supported]: Running `python -m unittest discover -s tests -t .` with tests/__init__.py present ends with 'Ran 2 tests' and 'OK'.
- claim `smoke-R2-ledgerlite-import-fixed:claim_ee8d34ea-2a40-4206-8992-86497e198377` [active, supported]: Running `python -m unittest discover -s tests -t .` without tests/__init__.py fails with 'Start directory is not importable'.
- not labeled, candidate `claim_3c14d374-bfa2-4e94-b1a5-79afd647f472` [fact, weak; review revise: The user message asks for one run; it does not show the user routinely runs tests with this command.]: The user runs this project's tests with `python -m unittest discover -s tests -t .`.
- not labeled, candidate `claim_9e8b69cc-6b5e-4470-a223-98bf2d413be3` [fact, weak; review revise: Write shows only the sys.path insert; no evidence shows ledgerlite is in src or imported by tests.]: tests/__init__.py inserts the src/ directory into sys.path so that the ledgerlite package can be imported by the tests.
- session A: Bash python -m unittest discover -s tests -t . 2>&1 | tail -40 (exit 0); Bash ls -R . | grep -v pyc | head -50 (exit 0); Bash cat tests/test_ledger.py | head -20; cat README.md; cat src/ledgerlite/__init__.py | head -30 (exit 0); Write tests/__init__.py; Bash python -m unittest discover -s tests -t . 2>&1 | tail -20 (exit 0)
- session C: Bash env -u PYTHONPATH python -m unittest discover -s tests -t . 2>&1 | tail -20 (exit 0)

## smoke-R3-household-budget-correction

- lesson `smoke-R3-household-budget-correction#0` (preference): Grocery budget is $700 per month.
- claim `smoke-R3-household-budget-correction:claim_49a2d9db-cf40-4596-8445-4a4dd55db256` [active, supported]: The grocery budget is now $700 per month.
- not labeled, superseded `claim_18ed29b6-02d8-4d5b-a48b-cfd54a5403a2` [decision, supported; review supported: ]: Keep the grocery budget under $600 per month for my planning.
- session A: 
- session C: Bash cat > groceries.csv <<'EOF'
item,cost_usd
Fresh produce,110
Meat and poultry,110
Fish and seafood,30
Dairy and eggs,55
Bread and bakery,25
R (exit 0)

## smoke-R4-fieldnotes-storage-conflict

- lesson `smoke-R4-fieldnotes-storage-conflict#0` (fact): Notes are stored in notes.json under NOTES_HOME.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_92dff127-624f-4906-9d9a-09718c064f12` [disputed, supported]: Notes are stored in notes.json under NOTES_HOME.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_a8a6fa8f-df5d-4970-aef4-e04167dee830` [active, supported]: Notes are stored in notes.jsonl under NOTES_HOME.
- session A: Glob ; Bash echo "NOTES_HOME=$NOTES_HOME" (exit 0); Read fieldnotes/cli.py; Read fieldnotes/store.py; Read README.md; Bash d=$(mktemp -d) && NOTES_HOME="$d" python -I -m fieldnotes.cli list; echo "exit=$?"; ls "$d" | wc -l (exit 0); Bash d=$(mktemp -d) && NOTES_HOME="$d" PYTHONPATH=. python -m fieldnotes.cli list; echo "exit=$?" (exit 0)
- session C: Glob ; Read fieldnotes/cli.py; Read tools/check.py; Glob ; Read fieldnotes/store.py; Write tools/count_notes.py; Bash cd <run>/work/R4/c/w && export NOTES_HOME=$(mktemp -d) && python tools/count_notes.py && python -m fieldnotes.cli add "first" && (exit 0)
