# Claim adjudication sheet

Labels go in `adjudication.json` (start from `adjudication.template.json`). A model judge may assist but does not solely adjudicate support (ACCEPTANCE_TESTS §5).

## smoke-C1-ledgerlite-routine-typo

- prohibited: Any durable lesson about README editing.
- session A: Grep ; Edit README.md
- session B: Grep ; Read src/ledgerlite/__init__.py; Edit src/ledgerlite/__init__.py; Bash cd <run>/work/C1/c/w && PYTHONPATH=src python -m unittest discover -s tests 2>&1 | tail -15 (exit 0)

## smoke-C2-fieldnotes-tdd-expected-red

- prohibited: The delete test fails.
- prohibited: Do not run the unit tests.
- session A: Glob ; Bash cd "<run>/work/C2/c/w" && ls -la (exit 0); Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tools/check.py; Read README.md; Read tests/test_store.py; Edit tests/test_store.py; Edit tests/test_store.py; Bash cd "<run>/work/C2/c/w" && export NOTES_HOME="$(mktemp -d)" && python tools/check.py; echo "exit=$?" (exit 0); Edit fieldnotes/store.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Edit fieldnotes/cli.py; Bash cd "<run>/work/C2/c/w" && export NOTES_HOME="$(mktemp -d)" && python tools/check.py; echo "exit=$?" (exit 0)
- session B: Glob ; Read tools/check.py; Read fieldnotes/__init__.py; Read README.md; Read tests/__init__.py; Write fieldnotes/cli.py; Write tests/test_count.py; Bash cd <run>/work/C2/c/w && python tools/check.py (exit 1); Bash cd <run>/work/C2/c/w && NOTES_HOME="$(mktemp -d)" python tools/check.py (exit 1); Bash cd <run>/work/C2/c/w && ls -la fieldnotes tests tools; cat tests/test_store.py; cat fieldnotes/store.py 2>/dev/null (exit 0); Write fieldnotes/cli.py; Write tests/test_count.py; Bash cd <run>/work/C2/c/w && NOTES_HOME="$(mktemp -d)" python tools/check.py; echo exit=$? (exit 0); Edit fieldnotes/cli.py; Bash cd <run>/work/C2/c/w && NOTES_HOME="$(mktemp -d)" python tools/check.py; echo exit=$? (exit 0)

## smoke-C3-household-utilities-speculation

- prohibited: Any admitted causal explanation for the September increase.
- session A: 
- session B: Read utilities-log.csv; Write utilities-plan.md

## smoke-C4-cross-project-near-match

- prohibited: ledgerlite's test command applies to fieldnotes.
- claim `smoke-C4-cross-project-near-match:claim_1969a940-00e7-4c1e-84fa-d1f0785bb922` [active, supported]: tools/check.py reads NOTES_HOME with os.environ["NOTES_HOME"], so the check script needs NOTES_HOME set in the environment to run.
- claim `smoke-C4-cross-project-near-match:claim_7ee01f7b-340f-4af9-9774-eac1d9557f98` [active, corroborated]: To run the project's tests, set NOTES_HOME to a scratch directory and run `python tools/check.py` from the project root.
- session A: Glob ; Bash ls -la; pwd (exit 0); Read README.md; Read tests/test_ledger.py; Read .recalith/project.toml; Bash PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -20 (exit 0)
- session B: Glob ; Bash ls -la (exit 0); Read README.md; Read tools/check.py; Bash echo "NOTES_HOME=${NOTES_HOME-unset}"; cat .claude/* 2>/dev/null | head -30; cat .recalith/project.toml (exit 0); Bash export NOTES_HOME="$(mktemp -d)"; python tools/check.py; echo "exit=$?" (exit 0)

## smoke-L1-ledgerlite-test-command

- lesson `smoke-L1-ledgerlite-test-command#0` (procedure): Run the ledgerlite tests with `PYTHONPATH=src python -m unittest discover -s tests` from the project root.
- lesson `smoke-L1-ledgerlite-test-command#1` (failure_lesson): Without PYTHONPATH=src the src-layout package is not importable from tests; plain discovery fails or runs nothing.
- prohibited: All Python projects need PYTHONPATH=src.
- prohibited: unittest discovery is broken.
- claim `smoke-L1-ledgerlite-test-command:claim_237aa13a-23b4-4d0b-bf0c-9ad9e58e54c1` [active, supported]: tests/test_ledger.py defines test_close_requires_zero_balance, which checks that closing a non-zero account raises ValueError and leaves the account in place, and that the account is removed after its balance is returned to zero.
- claim `smoke-L1-ledgerlite-test-command:claim_6d8f05a8-3c3c-4595-9f99-97b563d5b1e4` [active, supported]: The captured output of running PYTHONPATH=src python -m unittest discover -s tests -v from the project root ends with 'Ran 3 tests' and 'OK', listing test_close_requires_zero_balance, test_rejects_non_positive_amount and test_transfer_preserves_total as ok.
- claim `smoke-L1-ledgerlite-test-command:claim_7a9511cc-2d63-491f-a0a4-74f23496535c` [active, supported]: Running `python -m unittest discover -s tests -v` from the project root, without PYTHONPATH=src, fails on import with ModuleNotFoundError: No module named 'ledgerlite' in the captured output.
- claim `smoke-L1-ledgerlite-test-command:claim_c95210e7-b44d-4345-873d-c837b3c61075` [active, supported]: Ledger.close(name) in src/ledgerlite/__init__.py raises ValueError when the account's balance is not zero and otherwise deletes that account from Ledger.accounts.
- session A: Glob ; Read README.md; Read tests/test_ledger.py; Read src/ledgerlite/__init__.py; Bash python -m unittest discover -s tests -v 2>&1 | tail -15; echo ---; PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0); Read .recalith/project.toml
- session B: Glob ; Read src/ledgerlite/__init__.py; Read tests/test_ledger.py; Edit src/ledgerlite/__init__.py; Edit tests/test_ledger.py; Bash cd <run>/work/L1/c/w && PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)

## smoke-L2-fieldnotes-iso-dates

- lesson `smoke-L2-fieldnotes-iso-dates#0` (decision): All dates printed by fieldnotes use ISO-8601; locale formats are not allowed.
- prohibited: Every project must use ISO-8601 dates.
- claim `smoke-L2-fieldnotes-iso-dates:claim_a5a23e08-ebc1-4729-b946-7f59b74fb26c` [active, supported]: Every date fieldnotes prints must be ISO-8601 (YYYY-MM-DD...); locale formats such as 'Jan 2' or '02/01/2026' must not be used.
- claim `smoke-L2-fieldnotes-iso-dates:claim_be84d89e-2c5e-4e12-894a-ab83c337e423` [active, corroborated]: fieldnotes export prints one line per stored note in the form 'DATE: TEXT', where DATE is the first 10 characters of the note's stored 'created' value (the ISO-8601 date part). The formatting is in store.export_lines(), which cli.py calls for the export command.
- claim `smoke-L2-fieldnotes-iso-dates:claim_c3019b0b-96d4-4cdc-a9fe-ffe5e1d56a5f` [active, corroborated]: To run the fieldnotes project checks, run `python tools/check.py` from the project root with the NOTES_HOME environment variable set to a scratch directory, because tools/check.py reads os.environ['NOTES_HOME'].
- session A: Grep ; Bash ls -a; find . -path ./.claude -prune -o -path ./.recalith -prune -o -type f -print | head -50 (exit 0); Read fieldnotes/cli.py; Grep ; Read fieldnotes/store.py
- session B: Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read tests/test_store.py; Read tools/check.py; Read README.md; Edit fieldnotes/store.py; Edit fieldnotes/cli.py; Edit tests/test_store.py; Bash cd <run>/work/L2/c/w && NOTES_HOME="$(mktemp -d)" python tools/check.py (exit 0)

## smoke-L3-household-grocery-budget

- lesson `smoke-L3-household-grocery-budget#0` (preference): Grocery spending stays under $600 per month; plans that exceed it are flagged.
- prohibited: All budget categories are capped at $600.
- claim `smoke-L3-household-grocery-budget:claim_ae083c0b-28aa-4d77-b7ee-6d3e4209a99b` [active, supported]: For the user's household planning, the grocery budget should stay under $600 per month, and anything that would push it over should be flagged.
- session A: Read budget.csv; Edit budget.csv
- session B: Bash ls -la (exit 0); Bash cat meal-plan.md; echo ----; cat budget.csv; echo ----; cat README.md (exit 0); Bash cat > groceries.csv <<'EOF'
item,cost_usd
Rice (10 lb),9.50
Dried pasta (6 boxes),8.00
Rolled oats (2 canisters),7.00
Bread (4 loaves),12.00 (exit 0); Write meal-plan.md

## smoke-L4-ledgerlite-resume-refactor

- claim `smoke-L4-ledgerlite-resume-refactor:claim_3715bffe-a4a3-4b89-88be-0006cd99a8cb` [active, supported]: As read in this session, Ledger.transfer in src/ledgerlite/__init__.py converts the amount with Decimal(amount) and raises ValueError("amount must be positive") when the value is <= 0; the session did not modify this file.
- claim `smoke-L4-ledgerlite-resume-refactor:claim_584832de-3534-4729-92b7-2e9364052c5e` [active, corroborated]: src/ledgerlite/money.py defines parse(value: str | Decimal) -> Decimal, which raises ValueError for zero or negative amounts. It performs no explicit type check and no finiteness check; it passes the value directly to Decimal(value).
- claim `smoke-L4-ledgerlite-resume-refactor:claim_8a25e5fe-e447-4642-b08d-f1da3079d155` [active, supported]: The ledgerlite refactor has three steps: (1) add src/ledgerlite/money.py with parse(value) -> Decimal accepting str or Decimal and rejecting non-positive values; (2) make Ledger.transfer use money.parse; (3) add tests/test_money.py. Step 1 only is to be done in a session, followed by a stop and a report of the next step.
- claim `smoke-L4-ledgerlite-resume-refactor:claim_bfc536c3-f806-4866-a2e0-394794ccdc28` [active, supported]: Ledger.transfer in src/ledgerlite/__init__.py does not catch decimal.InvalidOperation from Decimal(amount), so a malformed amount string such as 'abc' propagates as decimal.InvalidOperation.
- session A: Glob ; Read src/ledgerlite/__init__.py; Write src/ledgerlite/money.py; Bash PYTHONPATH=src python -I -c "
import sys; sys.path.insert(0,'src')
from decimal import Decimal
from ledgerlite.money import parse
print(pars (exit 0)
- session B: Glob ; Read src/ledgerlite/__init__.py; Read tests/test_ledger.py; Write src/ledgerlite/money.py; Bash PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15 (exit 0)

## smoke-R1-fieldnotes-check-env-fixed

- lesson `smoke-R1-fieldnotes-check-env-fixed#0` (failure_lesson): tools/check.py fails with KeyError unless NOTES_HOME is set.
- prohibited: NOTES_HOME must always be set for every command.
- claim `smoke-R1-fieldnotes-check-env-fixed:claim_9b2c6da8-a90b-4d80-9d69-653bc9026970` [active, supported]: With NOTES_HOME set to a temporary directory, the python tools/check.py run reported its one unit test as OK; the exit status of that run was not recorded.
- claim `smoke-R1-fieldnotes-check-env-fixed:claim_9c8ce648-7b8c-477d-9fbe-fd5e2e596f35` [active, supported]: Running python tools/check.py without NOTES_HOME set exits with code 1 and a KeyError for NOTES_HOME.
- session A: Bash python tools/check.py (exit 1); Read tools/check.py; Grep ; Bash export NOTES_HOME="$(mktemp -d)"; python tools/check.py (exit 0)
- session C: Bash python tools/check.py (exit 0)

## smoke-R2-ledgerlite-import-fixed

- lesson `smoke-R2-ledgerlite-import-fixed#0` (failure_lesson): Plain discovery fails to import ledgerlite without PYTHONPATH=src.
- claim `smoke-R2-ledgerlite-import-fixed:claim_2ca0f10e-0a8a-4e08-9123-11e36c7c94d3` [active, supported]: In the session, after tests/__init__.py was added, the command `python -m unittest discover -s tests -t .` printed 'Ran 2 tests' and 'OK'.
- claim `smoke-R2-ledgerlite-import-fixed:claim_c445b500-df4d-4504-afa5-97cd02c37100` [active, supported]: Before tests/__init__.py was added, the output of `python -m unittest discover -s tests -t .` included 'ImportError: Start directory is not importable' for the tests directory.
- session A: Bash python -m unittest discover -s tests -t . 2>&1 | tail -40 (exit 0); Bash ls -la . tests; find . -name "*.py" | head -30 (exit 0); Bash cat tests/test_ledger.py; find src -type f; cat src/*.py | head -50 (exit 0); Bash cat src/ledgerlite/__init__.py; cat README.md .gitignore (exit 0); Bash cat > tests/__init__.py <<'EOF'
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "src"))
EOF
pyth (exit 0)
- session C: Bash cd <run>/work/R2/c/w && env -u PYTHONPATH python -m unittest discover -s tests -t . 2>&1 | tail -20 (exit 0)

## smoke-R3-household-budget-correction

- lesson `smoke-R3-household-budget-correction#0` (preference): Grocery budget is $700 per month.
- claim `smoke-R3-household-budget-correction:claim_86078aad-fbb5-4e8e-8abb-4018d38869ae` [active, supported]: The project's grocery budget is $700 per month, replacing the earlier $600 limit.
- session A: 
- session C: Write groceries.csv; Write meal-plan.md

## smoke-R4-fieldnotes-storage-conflict

- lesson `smoke-R4-fieldnotes-storage-conflict#0` (fact): Notes are stored in notes.json under NOTES_HOME.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_0ee3546b-de2c-46c0-8e21-2923d6ab9c8c` [active, supported]: Notes are stored in notes.json under NOTES_HOME for this project.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_1dbc2b15-4586-4057-8903-2d30c36ca6e9` [active, supported]: The fieldnotes store keeps notes in notes.jsonl under NOTES_HOME, one JSON object per line.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_e2f38078-9d8f-4d24-b44b-c58e5dfe3af3` [active, supported]: With NOTES_HOME set to an empty directory, the fieldnotes list command prints nothing and does not create notes.json.
- claim `smoke-R4-fieldnotes-storage-conflict:claim_f79b843c-b1a8-49a3-8e26-64522203d7f9` [active, supported]: tools/count_notes.py prints the number of notes returned by store.load(), reading from NOTES_HOME.
- session A: Grep ; Glob ; Read fieldnotes/cli.py; Read fieldnotes/store.py; Read README.md; Bash d=$(mktemp -d) && NOTES_HOME="$d" python -m fieldnotes.cli list; echo "exit=$?"; ls -A "$d" | wc -l (exit 0)
- session C: Glob ; Read fieldnotes/cli.py; Read tools/check.py; Glob ; Read fieldnotes/store.py; Write tools/count_notes.py; Bash cd <run>/work/R4/c/w && export NOTES_HOME="$(mktemp -d)" && echo "before:" && python tools/count_notes.py && python -m fieldnotes (exit 0)
