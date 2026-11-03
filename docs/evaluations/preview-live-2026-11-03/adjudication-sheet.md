# Claim adjudication sheet

Labels go in `adjudication.json` (start from `adjudication.template.json`). A model judge may assist but does not solely adjudicate support (ACCEPTANCE_TESTS §5).

## smoke-C1-ledgerlite-routine-typo

- prohibited: Any durable lesson about README editing.
- session A: Grep ; Edit README.md
- session B: Glob ; Grep ; Read src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash cd <run>/work/C1/c/w && PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -20 (exit 0)

## smoke-C2-fieldnotes-tdd-expected-red

- prohibited: The delete test fails.
- prohibited: Do not run the unit tests.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_0992fcb6-d044-487c-8db9-59e2d92e4084` [active, corroborated]: fieldnotes/store.py implements JSON-file note storage, and store.delete(index) removes and returns the note at 1-based index, raising IndexError when no note exists at that index.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_bc172d3e-81b4-488b-978e-160a143b2093` [active, corroborated]: The project checks are run with `python tools/check.py`, which runs the unit tests and a line-length rule of 100 characters.
- session A: Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tools/check.py; Read tests/test_store.py; Read README.md; Write tests/test_cli.py; Bash cd <run>/work/C2/c/w && export NOTES_HOME="$(mktemp -d)" && python -m unittest tests.test_cli -v 2>&1 | tail -30 (exit 0); Edit fieldnotes/store.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Bash cd <run>/work/C2/c/w && export NOTES_HOME="$(mktemp -d)" && python tools/check.py 2>&1 | tail -20; echo "exit=$?" (exit 0); Bash cd <run>/work/C2/c/w && export NOTES_HOME="$(mktemp -d)" && python tools/check.py >/dev/null 2>&1; echo "check exit=$?" (exit 0)
- session B: Glob ; Bash ls -la; cat README.md (exit 0); Read tests/test_store.py; Read fieldnotes/__init__.py; Read tools/check.py; Bash ls -R fieldnotes tests tools .claude | grep -v pyc; cat .gitignore; echo NOTES_HOME=$NOTES_HOME (exit 0); Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_cli.py; Edit tests/test_cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Bash NOTES_HOME="$(mktemp -d)" python tools/check.py (exit 0)

## smoke-C3-household-utilities-speculation

- prohibited: Any admitted causal explanation for the September increase.
- session A: 
- session B: Read utilities-log.csv; Write utilities-plan.md

## smoke-C4-cross-project-near-match

- prohibited: ledgerlite's test command applies to fieldnotes.
- claim `smoke-C4-cross-project-near-match:claim_1872b102-ffc3-4ab8-9953-bca16b1765ca` [active, supported]: tools/check.py reads the NOTES_HOME environment variable with os.environ["NOTES_HOME"], so the script needs that variable set to run; the check harness writes scratch notes to that directory.
- claim `smoke-C4-cross-project-near-match:claim_f96cdd31-44b5-4f58-9255-9d601d399c72` [active, supported]: The project's checks run with `python tools/check.py`, which runs the unittest suite under tests/ and reports lines over 100 characters in fieldnotes/**/*.py.
- session A: Glob ; Bash ls -la (exit 0); Bash cat README.md .gitignore; find src tests .claude .recalith -type f | head -50 (exit 0); Bash head -20 tests/test_ledger.py; python --version; python -m pytest --version (exit 1); Bash PYTHONPATH=src python -m unittest discover -s tests -v (exit 0)
- session B: Bash ls -la; cat package.json 2>/dev/null | head -40; ls *.toml *.py *.go Makefile pom.xml 2>/dev/null (exit 2); Bash cat README.md .gitignore; find tests tools fieldnotes .claude .recalith -type f | head -50 (exit 0); Read tools/check.py; Bash echo "NOTES_HOME=${NOTES_HOME:-unset}"; D=$(mktemp -d) && NOTES_HOME="$D" python tools/check.py 2>&1 | tail -40; echo "exit=${PIPESTATUS[0]} (exit 0)

## smoke-L1-ledgerlite-test-command

- lesson `smoke-L1-ledgerlite-test-command#0` (procedure): Run the ledgerlite tests with `PYTHONPATH=src python -m unittest discover -s tests` from the project root.
- lesson `smoke-L1-ledgerlite-test-command#1` (failure_lesson): Without PYTHONPATH=src the src-layout package is not importable from tests; plain discovery fails or runs nothing.
- prohibited: All Python projects need PYTHONPATH=src.
- prohibited: unittest discovery is broken.
- claim `smoke-L1-ledgerlite-test-command:claim_561ac9e0-181d-4530-b479-7af5352f3202` [active, supported]: Ledger.close(name) in src/ledgerlite/__init__.py raises ValueError when the account balance is non-zero and otherwise removes the account.
- claim `smoke-L1-ledgerlite-test-command:claim_82e908e0-fd52-447d-9573-20a3d4b8aa75` [active, supported]: Running `python -m unittest discover -s tests -v` from the project root, without PYTHONPATH=src, fails with a ModuleNotFoundError for the ledgerlite package.
- not labeled, candidate `claim_80771391-38f9-4ba3-ab00-405d44502022` [fact, weak; review revise: Only the 2-test run is supported. The 3-test count rests on evt_272f, which is linked as contradicts, not supports. / Cited evidence does not show the before/after order relative to adding test_close_requires_zero_balance.]: Running `PYTHONPATH=src python -m unittest discover -s tests -v` from the project root passes all ledgerlite tests: 2 tests before test_close_requires_zero_balance was added, 3 tests after.
- session A: Glob ; Bash pwd; ls -la (exit 0); Read README.md; Read tests/test_ledger.py; Read src/ledgerlite/__init__.py; Read .recalith/project.toml; Bash python -m unittest discover -s tests -v 2>&1 | tail -15; echo ---; PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)
- session B: Glob ; Read src/ledgerlite/__init__.py; Read tests/test_ledger.py; Edit src/ledgerlite/__init__.py; Edit tests/test_ledger.py; Bash PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)

## smoke-L2-fieldnotes-iso-dates

- lesson `smoke-L2-fieldnotes-iso-dates#0` (decision): All dates printed by fieldnotes use ISO-8601; locale formats are not allowed.
- prohibited: Every project must use ISO-8601 dates.
- claim `smoke-L2-fieldnotes-iso-dates:claim_f93fddd3-892d-4119-807e-8bb745e489f5` [active, supported]: tools/check.py requires the NOTES_HOME environment variable to be set, because it reads os.environ["NOTES_HOME"] directly.
- not labeled, candidate `claim_b0c2872a-8b72-4920-81b7-b5017a043d45` [fact, weak; review revise: Cited Edit shows only the print format; it does not show created is stored as ISO-8601. / The export command was not run, so the printed output is unverified.]: The fieldnotes export command prints one line per stored note in the form `<created>: <text>`, where created is the note's stored ISO-8601 timestamp.
- session A: Grep ; Read fieldnotes/store.py; Glob ; Read fieldnotes/cli.py
- session B: Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_store.py; Read tools/check.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Write tests/test_cli.py; Bash NOTES_HOME="$(mktemp -d)" python tools/check.py (exit 0)

## smoke-L3-household-grocery-budget

- lesson `smoke-L3-household-grocery-budget#0` (preference): Grocery spending stays under $600 per month; plans that exceed it are flagged.
- prohibited: All budget categories are capped at $600.
- claim `smoke-L3-household-grocery-budget:claim_01dcde37-4c06-4146-a9fd-5bc3b9e61ea6` [active, supported]: For the user's household planning, the grocery budget is kept under $600 per month, and anything that would push it over is flagged.
- session A: Glob ; Read budget.csv; Bash cd "<run>/work/L3/c/w" && tail -c1 budget.csv | xxd | head -1; printf 'groceries,600,keep under; flag anything that would push it (exit 0)
- session B: Bash ls -la; head -50 budget.csv groceries.csv meal-plan.md 2>/dev/null (exit 1); Bash cat README.md (exit 0); Bash cat > groceries.csv <<'EOF'
item,cost_usd
Rice (10 lb),9.50
Dried pasta (6 boxes),8.00
Rolled oats (2 canisters),7.00
Bread (4 loaves),14.00 (exit 0); Bash sed -i -e 's/^Salmon or white fish fillets (4 lb),40.00/Salmon or white fish fillets (3 lb),30.00/' -e 's/^Fresh fruit.*/Fresh fruit (apples (exit 0)

## smoke-L4-ledgerlite-resume-refactor

- claim `smoke-L4-ledgerlite-resume-refactor:claim_0c72c3c4-2d72-4969-8b0b-7a193c372c72` [active, supported]: src/ledgerlite/money.py defines parse(value), which returns a finite, positive Decimal for str or Decimal input, raises TypeError for other types, and raises ValueError for unparseable, non-finite or non-positive values.
- claim `smoke-L4-ledgerlite-resume-refactor:claim_a79b353d-fdb4-43cf-a89f-1c7f4c059562` [active, corroborated]: Ledger.transfer in src/ledgerlite/__init__.py calls money.parse(amount) to validate the amount and no longer contains its own Decimal conversion and positivity check.
- not labeled, candidate `claim_6af60d10-45db-4416-9c22-5b4ce7471097` [fact, weak; review revise: Command cds to a fixed path; workspace root not shown by evidence. / Exit code unrecorded; output piped through tail hides status.]: Running `PYTHONPATH=src python -m unittest discover -s tests -v` from the ledgerlite workspace root produced output ending in 'Ran 2 tests in 0.000s' and 'OK' for the tests in tests/test_ledger.py.
- session A: Glob ; Read src/ledgerlite/__init__.py; Grep ; Write src/ledgerlite/money.py
- session B: Grep ; Glob ; Read src/ledgerlite/__init__.py; Bash ls -la <run>/work/L4/c/w/src/ledgerlite <run>/work/L4/c/w/tests (exit 0); Read src/ledgerlite/money.py; Read tests/test_ledger.py; Edit src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash cd <run>/work/L4/c/w && PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -20 (exit 0)

## smoke-R1-fieldnotes-check-env-fixed

- lesson `smoke-R1-fieldnotes-check-env-fixed#0` (failure_lesson): tools/check.py fails with KeyError unless NOTES_HOME is set.
- prohibited: NOTES_HOME must always be set for every command.
- claim `smoke-R1-fieldnotes-check-env-fixed:claim_22429cbd-15cb-4cca-9a98-75c26704a50c` [active, supported]: tools/check.py reads the NOTES_HOME environment variable and uses it as the scratch notes directory.
- not labeled, candidate `claim_7645b49f-e142-4593-958b-3b0c2e740fc8` [failure_lesson, weak; review revise: The claim generalizes one observed failing run to every run without NOTES_HOME. / The same command later passed (evd_84c3); whether NOTES_HOME was unset in that run is not shown.]: Running `python tools/check.py` without NOTES_HOME set fails with KeyError: 'NOTES_HOME'.
- session A: Bash python tools/check.py (exit 1); Read tools/check.py; Grep ; Bash export NOTES_HOME="$(mktemp -d)"; python tools/check.py (exit 0)
- session C: Bash python tools/check.py (exit 0)

## smoke-R2-ledgerlite-import-fixed

- lesson `smoke-R2-ledgerlite-import-fixed#0` (failure_lesson): Plain discovery fails to import ledgerlite without PYTHONPATH=src.
- claim `smoke-R2-ledgerlite-import-fixed:claim_502a5869-af23-4e02-8432-5df443d7ed45` [active, supported]: After tests/__init__.py is added to insert src into sys.path, running `python -m unittest discover -s tests -t .` from the project root runs 2 tests and reports OK.
- not labeled, candidate `claim_479c58d2-647d-43b3-ba2e-d494b4000b9c` [fact, weak; review revise: The cited event does not record environment, so 'with no PYTHONPATH set' is not supported by it. / The command had no exit code recorded (null); only the printed OK and test count are shown.]: Running `python -m unittest discover -s tests -t .` from the project root, with no PYTHONPATH set, runs 2 tests and reports OK.
- not labeled, candidate `claim_523213cf-f05e-40fb-907d-8b5d1d224d3d` [fact, weak; review revise: Cited text is a user request to run this command, not evidence it is the project's test command. / Scope is the project's tests, but the source only names a desired command.]: The project's tests are run with `python -m unittest discover -s tests -t .`.
- not labeled, candidate `claim_e74b129e-5a20-4851-a0f8-55cab6877965` [fact, weak; review revise: Output shows the ImportError but not that tests/__init__.py was absent. / The ls output lists only top-level entries, not tests/ contents.]: Running `python -m unittest discover -s tests -t .` from the project root, without tests/__init__.py, fails with ImportError: Start directory is not importable.
- session A: Bash python -m unittest discover -s tests -t . 2>&1 | tail -30; ls (exit 0); Bash ls -R tests src; cat README.md (exit 0); Bash cat tests/test_ledger.py; cat src/ledgerlite/__init__.py (exit 0); Bash cat > tests/__init__.py <<'EOF'
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
EOF
python -m (exit 0)
- session C: Bash python -m unittest discover -s tests -t . 2>&1 | tail -30 (exit 0)

## smoke-R3-household-budget-correction

- lesson `smoke-R3-household-budget-correction#0` (preference): Grocery budget is $700 per month.
- claim `smoke-R3-household-budget-correction:claim_2e0741e1-884b-4dfa-aeab-eeae12d07829` [active, supported]: The user's grocery budget for planning is $700 per month, replacing the earlier $600 monthly limit.
- not labeled, superseded `claim_9b60d703-75ec-4491-85d0-48ebd35319c8` [preference, supported; review supported: ]: The user wants the grocery budget kept under $600 per month for their planning.
- session A: 
- session C: Bash cat > groceries.csv <<'EOF'
item,cost_usd
Fresh vegetables (4 weeks),70
Fruit,45
Potatoes and onions,12
Chicken,45
Ground beef,30
Eggs,15
Fi (exit 0)

## smoke-R4-fieldnotes-storage-conflict

- lesson `smoke-R4-fieldnotes-storage-conflict#0` (fact): Notes are stored in notes.json under NOTES_HOME.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_5876a55f-7fbc-4b25-ae13-de6a71a4f445` [active, supported]: Notes for this project are stored in notes.json under the NOTES_HOME directory.
- session A: Glob ; Bash echo "NOTES_HOME=$NOTES_HOME" (exit 0); Read fieldnotes/cli.py; Read fieldnotes/store.py; Read README.md; Bash d=$(mktemp -d) && cd "<run>/work/R4/c/w" && NOTES_HOME="$d" python -I -m fieldnotes.cli list; echo "exit=$?"; ls -A "$d" (exit 0); Bash d=$(mktemp -d) && cd "<run>/work/R4/c/w" && NOTES_HOME="$d" python -m fieldnotes.cli list; echo "exit=$?"; ls -A "$d" (exit 0)
- session C: Glob ; Bash ls -la; echo "NOTES_HOME=$NOTES_HOME" (exit 0); Read fieldnotes/cli.py; Bash ls fieldnotes; cat fieldnotes/store.py fieldnotes/__init__.py tools/check.py README.md (exit 0); Write tools/count_notes.py; Bash export NOTES_HOME=$(mktemp -d); python tools/count_notes.py; python -m fieldnotes.cli add "first note"; python -m fieldnotes.cli add "second (exit 0)
