# Claim adjudication sheet

Labels go in `adjudication.json` (start from `adjudication.template.json`). A model judge may assist but does not solely adjudicate support (ACCEPTANCE_TESTS §5).

## smoke-C1-ledgerlite-routine-typo

- prohibited: Any durable lesson about README editing.
- session A: Grep ; Edit README.md
- session B: Grep ; Read src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash cd <run>/work/C1/c/w && PYTHONPATH=src python -m unittest discover -s tests 2>&1 | tail -15 (exit 0)

## smoke-C2-fieldnotes-tdd-expected-red

- prohibited: The delete test fails.
- prohibited: Do not run the unit tests.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_2e3175b9-f8f7-427d-aab1-ac7466f2ea9e` [active, supported]: After the `delete INDEX` change, running `python tools/check.py` exited with code 0 and its output reported 5 tests OK.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_a72bb89c-ad3e-4b03-8b1b-43df0f49dc3a` [active, supported]: The fieldnotes project's `tools/check.py` reads `NOTES_HOME` from the environment with `os.environ["NOTES_HOME"]`, so the checks need `NOTES_HOME` set to a directory.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_b746922b-d270-4a4f-aebd-a6e074dfe1e9` [active, supported]: The fieldnotes CLI has a `count` command, `python -m fieldnotes.cli count`, that prints the number of stored notes.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_be461e57-0e85-4ba0-8e87-b2e49f00af68` [active, supported]: The fieldnotes project's checks are run with `python tools/check.py`.
- claim `smoke-C2-fieldnotes-tdd-expected-red:claim_df107062-5863-4f7e-a4bd-ad95efe11b8a` [active, supported]: For the `delete INDEX` task, the user asked to use TDD: write a failing unit test first, run it to show it fails, then implement the command and make the checks pass.
- not labeled, candidate `claim_fd5c32d8-9b04-4867-ac13-8a2c53c2e764` [fact, weak; review revise: Edit shows only the 0-based docstring; list print order is not evidenced. / Context event is not in the batch evidence index.]: The fieldnotes `delete INDEX` command takes a 0-based index into the notes in the order `list` prints them.
- session A: Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tools/check.py; Read tests/test_store.py; Read README.md; Edit tests/test_store.py; Edit tests/test_store.py; Bash cd "<run>/work/C2/c/w" && export NOTES_HOME="$(mktemp -d)" && python -m unittest discover -s tests -t . 2>&1 | tail -30 (exit 0); Edit fieldnotes/store.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Bash cd "<run>/work/C2/c/w" && export NOTES_HOME="$(mktemp -d)" && python tools/check.py 2>&1 | tail -15; echo "exit=$?" (exit 0); Bash cd "<run>/work/C2/c/w" && export NOTES_HOME="$(mktemp -d)" && python tools/check.py >/dev/null 2>&1; echo "check exit=$?" (exit 0)
- session B: Bash ls -R . | head -50 && cat fieldnotes/cli.py fieldnotes/store.py tests/test_store.py tools/check.py (exit 0); Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit tests/test_store.py; Bash cd <run>/work/C2/c/w && echo "NOTES_HOME=$NOTES_HOME" (exit 0); Bash cd <run>/work/C2/c/w && NOTES_HOME="$(mktemp -d)" python tools/check.py; echo exit=$? (exit 0)

## smoke-C3-household-utilities-speculation

- prohibited: Any admitted causal explanation for the September increase.
- session A: 
- session B: Read utilities-log.csv; Write utilities-plan.md

## smoke-C4-cross-project-near-match

- prohibited: ledgerlite's test command applies to fieldnotes.
- claim `smoke-C4-cross-project-near-match:claim_99f35600-bb7b-4732-8962-1c3be225c217` [active, corroborated]: The project's checks are run with `python tools/check.py`, which runs the unit tests and a 100-character line-length check on fieldnotes Python files.
- claim `smoke-C4-cross-project-near-match:claim_e6a8544b-fc65-4181-b796-426a1f246a28` [active, supported]: tools/check.py reads NOTES_HOME from the environment with os.environ["NOTES_HOME"], so the script requires NOTES_HOME to be set.
- session A: Glob ; Bash ls -la (exit 0); Bash cat README.md .gitignore; find src tests .claude .recalith -type f | head -50 (exit 0); Bash head -20 tests/test_ledger.py; python --version; python -m pytest -q 2>&1 | tail -15 (exit 0); Bash PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)
- session B: Bash ls -la; cat package.json 2>/dev/null | head -40; ls | grep -iE "pytest|tox|Makefile|Cargo|go.mod|pom|build.gradle|setup.py|pyproject" (exit 0); Bash cat README.md .gitignore; find tests tools fieldnotes .claude .recalith -type f | head -50 (exit 0); Read tools/check.py; Bash echo "NOTES_HOME=${NOTES_HOME:-<unset>}"; export NOTES_HOME="${NOTES_HOME:-$(mktemp -d)}"; python tools/check.py 2>&1 | tail -30; echo "exit (exit 0)

## smoke-L1-ledgerlite-test-command

- lesson `smoke-L1-ledgerlite-test-command#0` (procedure): Run the ledgerlite tests with `PYTHONPATH=src python -m unittest discover -s tests` from the project root.
- lesson `smoke-L1-ledgerlite-test-command#1` (failure_lesson): Without PYTHONPATH=src the src-layout package is not importable from tests; plain discovery fails or runs nothing.
- prohibited: All Python projects need PYTHONPATH=src.
- prohibited: unittest discovery is broken.
- claim `smoke-L1-ledgerlite-test-command:claim_408d5fed-213a-48d5-8d28-5839c3177d38` [active, supported]: The ledgerlite Ledger class has a close(name) method in src/ledgerlite/__init__.py. It raises ValueError when the account balance is not zero, and otherwise deletes the account.
- claim `smoke-L1-ledgerlite-test-command:claim_9ace3a78-e24e-416a-9d6d-c642bda9a03a` [active, supported]: Running `PYTHONPATH=src python -m unittest discover -s tests -v` from the ledgerlite project root runs the unit tests and reported Ran 2 tests, OK.
- session A: Glob ; Bash pwd; ls -la (exit 0); Bash cat README.md; cat tests/test_ledger.py; cat src/ledgerlite/__init__.py; cat .recalith/project.toml .recalith/local.toml; ls -R .claude (exit 0); Bash python --version; PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -20 (exit 0)
- session B: Glob ; Read src/ledgerlite/__init__.py; Read tests/test_ledger.py; Edit src/ledgerlite/__init__.py; Edit tests/test_ledger.py; Bash PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)

## smoke-L2-fieldnotes-iso-dates

- lesson `smoke-L2-fieldnotes-iso-dates#0` (decision): All dates printed by fieldnotes use ISO-8601; locale formats are not allowed.
- prohibited: Every project must use ISO-8601 dates.
- claim `smoke-L2-fieldnotes-iso-dates:claim_70ed40d0-0fce-468c-a1d8-bac217ba8633` [active, supported]: tools/check.py reads the NOTES_HOME environment variable with os.environ["NOTES_HOME"], so running the project checks requires NOTES_HOME to be set.
- claim `smoke-L2-fieldnotes-iso-dates:claim_77a29005-4705-4418-8f54-f05558cb13f2` [active, corroborated]: fieldnotes export prints each stored note as `created: text`, with `created` printed unchanged from store.load(), the same value that fieldnotes list prints.
- claim `smoke-L2-fieldnotes-iso-dates:claim_7928f95d-abc7-4a48-b7ae-8b67cc557370` [active, corroborated]: fieldnotes list prints each stored note's 'created' value unchanged; store.add writes that value with datetime.isoformat() in UTC, so list output is ISO-8601 only for notes written through store.add.
- claim `smoke-L2-fieldnotes-iso-dates:claim_8e9ece5b-58a4-4de3-a6e9-3aee338a6a54` [active, supported]: Every date fieldnotes prints must be ISO-8601 (YYYY-MM-DD...). Locale formats such as 'Jan 2' or '02/01/2026' must never be used.
- session A: Grep ; Read fieldnotes/store.py; Glob ; Read fieldnotes/cli.py
- session B: Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_store.py; Read tools/check.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Write tests/test_cli.py; Bash NOTES_HOME=$(mktemp -d) python tools/check.py (exit 0)

## smoke-L3-household-grocery-budget

- lesson `smoke-L3-household-grocery-budget#0` (preference): Grocery spending stays under $600 per month; plans that exceed it are flagged.
- prohibited: All budget categories are capped at $600.
- claim `smoke-L3-household-grocery-budget:claim_d2018588-9df2-4566-89c5-b1e8ac04e80b` [active, supported]: For household planning, the user decided to keep the grocery budget under $600 per month and to have anything that would push it over flagged.
- session A: Read budget.csv; Bash printf 'groceries,600,keep under $600/month; flag anything that would push it over\n' >> "<run>/work/L3/c/w/budget.csv" && tail - (exit 0)
- session B: Bash ls -la; cat budget.csv; cat groceries.csv meal-plan.md 2>/dev/null (exit 1); Bash cat > groceries.csv <<'EOF'
item,cost_usd
Rice (10 lb),9.50
Dried pasta (4 boxes),5.00
Rolled oats,4.50
Bread (4 loaves),10.00
Tortillas (2  (exit 0); Write meal-plan.md; Bash awk -F, 'NR>1{print $1","$2}' groceries.csv | wc -l (exit 0); Bash sed -i 's/| \$93 |/| $109.50 |/; s/| \$62 |/| $50 |/; s/| \$144 |/| $144.50 |/' meal-plan.md && grep '^| ' meal-plan.md (exit 0)

## smoke-L4-ledgerlite-resume-refactor

- claim `smoke-L4-ledgerlite-resume-refactor:claim_7b7e67b8-4e09-4da2-a0ea-9677dbcc8d25` [active, corroborated]: Ledger.transfer in src/ledgerlite/__init__.py calls money.parse(amount) in place of its own Decimal conversion and positivity check, and imports money from the package.
- claim `smoke-L4-ledgerlite-resume-refactor:claim_b5066e08-c6d6-4662-9f89-4bf06599540f` [active, supported]: src/ledgerlite/money.py defines parse(value) that returns a finite positive Decimal, raises TypeError for types other than str or Decimal, and raises ValueError for invalid, non-finite or non-positive amounts.
- not labeled, candidate `claim_9d135149-72ab-48e7-a153-52478e83afae` [fact, weak; review revise: Workspace named only by cd path rl-gate9/work/L4/c/w; no ledgerlite identifier in evidence. / Bash command parse is ambiguous (command_parse_ambiguous); scope is weak and volatile.]: Running `python -m pytest -q` from the ledgerlite workspace fails with 'No module named pytest' in this environment.
- session A: Glob ; Read src/ledgerlite/__init__.py; Write src/ledgerlite/money.py
- session B: Read src/ledgerlite/__init__.py; Read src/ledgerlite/money.py; Edit src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash cd <run>/work/L4/c/w && python -m pytest -q 2>&1 | tail -20 (exit 0); Bash cd <run>/work/L4/c/w && ls; ls tests 2>&1; PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -20 (exit 0)

## smoke-R1-fieldnotes-check-env-fixed

- lesson `smoke-R1-fieldnotes-check-env-fixed#0` (failure_lesson): tools/check.py fails with KeyError unless NOTES_HOME is set.
- prohibited: NOTES_HOME must always be set for every command.
- claim `smoke-R1-fieldnotes-check-env-fixed:claim_d8533bc1-4231-40d0-aac2-686a90e02bed` [active, supported]: tools/check.py reads the NOTES_HOME environment variable directly and has no fallback when it is unset.
- not labeled, candidate `claim_73906b70-9d24-48a1-bd28-f328d85af463` [failure_lesson, weak; review revise: Event 2e8d4c contradicts link is wrong: it shows success with NOTES_HOME set, not the no-NOTES_HOME case. / Its contradicts entry should be removed or reclassified as context.]: Running `python tools/check.py` from the project, without NOTES_HOME set, fails with KeyError: 'NOTES_HOME'.
- session A: Bash python tools/check.py (exit 1); Read tools/check.py; Bash export NOTES_HOME="$(mktemp -d)"; python tools/check.py (exit 0)
- session C: Bash python tools/check.py (exit 0)

## smoke-R2-ledgerlite-import-fixed

- lesson `smoke-R2-ledgerlite-import-fixed#0` (failure_lesson): Plain discovery fails to import ledgerlite without PYTHONPATH=src.
- claim `smoke-R2-ledgerlite-import-fixed:claim_1ca57a18-1fad-4f3a-9516-127faa1da7a4` [active, supported]: The user prefers the test command `python -m unittest discover -s tests -t .` to stay unchanged if possible, and otherwise wants to be told which command works.
- claim `smoke-R2-ledgerlite-import-fixed:claim_1de7fd3b-6413-4cdc-97f6-60072665ff01` [active, supported]: With a tests/__init__.py that inserts the sibling src directory into sys.path, running `python -m unittest discover -s tests -t .` from the project root reported 'Ran 2 tests' and 'OK'.
- claim `smoke-R2-ledgerlite-import-fixed:claim_6d7cd3ef-e266-452b-8d7f-19f2a61c1ae5` [active, supported]: The project keeps the ledgerlite package under src/ledgerlite and its unittest module under tests/test_ledger.py.
- claim `smoke-R2-ledgerlite-import-fixed:claim_f9c623ef-f2c3-406e-86da-35b283a593ea` [active, supported]: Running `python -m unittest discover -s tests -t .` from the project root, with an empty tests/__init__.py and no path setup for src/, fails with 'ModuleNotFoundError: No module named 'ledgerlite''.
- not labeled, candidate `claim_b11b9732-452e-40f1-a42d-e2f785c08628` [fact, weak; review revise: Cited output does not show that tests/__init__.py was absent when the command ran.]: Running `python -m unittest discover -s tests -t .` from the project root, while tests/ has no __init__.py, fails with 'ImportError: Start directory is not importable'.
- session A: Bash python -m unittest discover -s tests -t . 2>&1 | tail -30 (exit 0); Bash ls -R . | head -50 (exit 0); Bash touch tests/__init__.py; head -15 tests/test_ledger.py; python -m unittest discover -s tests -t . 2>&1 | tail -15 (exit 0); Bash cat > tests/__init__.py <<'EOF'
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "src"))
EOF
pyth (exit 0)
- session C: Bash env | grep -i ^PYTHONPATH; python -m unittest discover -s tests -t . 2>&1 | tail -20 (exit 0)

## smoke-R3-household-budget-correction

- lesson `smoke-R3-household-budget-correction#0` (preference): Grocery budget is $700 per month.
- claim `smoke-R3-household-budget-correction:claim_4ae057b3-f17c-4284-aae0-e00ccb6af047` [active, supported]: The user wants the grocery budget kept under $600 per month for their planning.
- not labeled, candidate `claim_f7edc86e-9dbe-419f-908a-9be29ec52d4d` [preference, weak; review revise: Evidence says the grocery budget is $700 per month; 'kept under $700' adds a ceiling framing the text does not state. / The cited text is a budget correction, not an explicit statement that the user wants spending kept below the limit.]: The user wants the grocery budget kept under $700 per month for their planning.
- session A: 
- session C: Bash cat > groceries.csv <<'EOF'
item,cost_usd
Fresh vegetables and fruit,90.00
Chicken thighs and breasts,38.00
Ground beef,32.00
Salmon fillets (exit 0)

## smoke-R4-fieldnotes-storage-conflict

- lesson `smoke-R4-fieldnotes-storage-conflict#0` (fact): Notes are stored in notes.json under NOTES_HOME.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_77bb7621-0f79-441e-89eb-67149b62d9d5` [disputed, supported]: Notes for this project are stored in notes.json under the directory named by NOTES_HOME.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_991ce53d-16b6-416b-9aed-b102f324e6d6` [active, supported]: Notes for this project are stored in notes.jsonl under the directory named by NOTES_HOME, one JSON object per line.
- not labeled, candidate `claim_d8a430a2-13f0-4c37-ba83-95a8e1683a20` [fact, weak]: Running `python -m fieldnotes.cli list` with NOTES_HOME set to a fresh empty directory exits with code 0 and prints nothing.
- session A: Glob ; Bash echo "NOTES_HOME=$NOTES_HOME"; ls -la (exit 0); Read README.md; Read fieldnotes/cli.py; Read fieldnotes/store.py; Bash ls -la .claude .recalith; cat .recalith/project.toml .gitignore (exit 0); Write CLAUDE.md; Bash d=$(mktemp -d); NOTES_HOME="$d" python -m fieldnotes.cli list; echo "exit=$?"; ls -A "$d" (exit 0)
- session C: Read fieldnotes/cli.py; Read fieldnotes/store.py; Write tools/count_notes.py; Bash cd <run>/work/R4/c/w && export NOTES_HOME="$(mktemp -d)" && python tools/count_notes.py && python -m fieldnotes.cli add "first" & (exit 0)
