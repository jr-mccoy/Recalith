# Decision 0049: A baseline-sensitivity set beside the gate

Status: accepted (Task 18, preview evaluation) · Date: 2026-11-10 · Engine: `0.1.0.dev16` (no engine change) · Observed: the tenth live gate's paired outcomes; the pre-publication audit's EVAL-2 ([report](../audits/2026-11-06-memory-system-audit.md), item 5.1 of [the fix plan](../audits/2026-11-06-fix-plan.md))

## Context

The tenth live gate passed, but its comparison with the no-memory baseline could not show the benefit the project exists for. Repeated mistakes were 0/0 in both arms on all twelve smoke scenarios. Every answer in the smoke corpus can be recovered from the repository: the live baseline reads `README.md` and the source before acting (in L1 it ran `PYTHONPATH=src …` on its first attempt in both sessions), so it never repeats a mistake. The trial's generic repeated-mistake count also needs a failed command in session B whose text matches a failed command of session A exactly. A live agent writes `cd <run>/… && … | tail -5`, which changes the text and hides the exit code, so the count almost never registers.

Fix-plan item 5.1 asks for at least four scenarios where the baseline predictably fails or repeats a mistake, because the answer is not in the repository. ACCEPTANCE_TESTS §6.1 fixes the preview gate at the frozen 12, so adding scenarios to the gate would change a measurement the specification owns.

## Decisions

1. **A separate set, never part of the gate.** Four scenarios in `evals/scenarios/sensitivity/` (`sens-S1` … `sens-S4`) run beside the 12. The gate's population, its §5.1 measures, its completeness check and its demonstrations are unchanged. A run writes their trials to `sensitivity/`, never to `trials/`. The report has a separate section, "Baseline-sensitivity set", that says it is not part of the gate and makes no superiority claim. ACCEPTANCE_TESTS §6.1 says so in one sentence.
2. **One pattern, four kinds of missing fact.** In session A the agent does the obvious thing, and the user's second prompt corrects it with a fact the repository does not hold. Session B is a fresh session with a similar task.
   - **S1, ledgerlite (a decision that contradicts the code):** new methods take integer cents, although `transfer` takes dollar strings. Session A's deposit is removed.
   - **S2, household (an unwritten convention):** `meal-plan.md` is shared with the user's partner and never shows a price. Session B starts from a reset meal plan.
   - **S3, fieldnotes (an environmental fix):** on this laptop the checks run with `--jobs 1`. An overlay gives `tools/check.py` a `--jobs` option. The default works, and nothing in the repository says not to use it.
   - **S4, fieldnotes (an outside constraint):** `notes.json` is frozen at `text` and `created` because a phone app reads it, so extras go in `meta.json`. Session A's tags change is reverted.
3. **The measure is the named mistake.** Each oracle judges session B's final files, or for S3 its action log, and reports `repeated_named_mistake`: 1 when the mistake corrected in session A appears again, else 0. A trial records it as an outcome next to the generic count, which is kept and still reported. The section reports both arms' totals, the relative reduction and the paired difference. Task success requires no repeat, so the correct solution passes and the obvious one fails. Each oracle fails the untouched seed.
4. **Frozen and pinned like the 12.** The gate record's `versions.inputs` digests the four scenario files and their overlays (`sensitivity_scenarios`, `sensitivity_overlays`). The oracles share `evals/oracles/smoke.py`, which is already digested. `tools/live_gate/sanitize_record.py` copies `sensitivity/` with the rest of a record. The review packet and the labels cover the 12 only: this set is judged by its oracles.
5. **They run in the same pool.** `smoke` and `gate` schedule the four scenarios with the 12 by default, so `--slots` packs 32 trials instead of 24. `--no-sensitivity` skips them, and `--scenario` runs exactly what it names.
6. **Two harness fixes the set needed.** Neither changes the 12, whose 24 scripted trials gave identical outcomes, claims and oracle checks before and after.
   - **Scripted sessions alternate prompt and action.** A scripted session with several prompts now answers each before the next arrives, as a live session does. The policy step is `A` for the first prompt, then `A2`, `A3`. Single-prompt sessions are unchanged.
   - **Each later prompt gets its own `prompt_id`.** Capture keys a prompt on its `prompt_id` and the transcript's byte length, and the scripted transcript stays empty. The reused id therefore made a second prompt an identity conflict with the first, and neither was captured.
7. **Scripted result (mechanics only).** The scripted baseline repeats the named mistake in 4 of 4 scenarios and fails each task. The scripted candidate, which reads only the context the engine delivered, repeats none and passes each. This shows the corpus and the oracles can register the difference. It is not evidence that a live agent benefits; the live gate measures that.

## Found while building it (not changed here)

When the scripted session still sent all its prompts before acting, S1's declaration never reached session B. Session A recorded the user's correction, then a failed `python -m unittest discover -s tests`, then a passing `PYTHONPATH=src …`. Session B continued session A's task, so no episode closed, and the only extraction was the one the failure triggered. That extraction reads only the events after the failure, so it missed the declaration. When session A had no failed command, an episode was built at the session's end and its extraction admitted the declaration.

In engine terms: a user declaration made before a failure that is fixed in the same session, on a task the next session continues, is not extracted until the episode closes, at the 24-hour idle pause or a task change. A live session usually corrects after acting, which avoids this, but a user can state a rule first and the agent can then hit a failure. Reproduce it with `evals/agent.py` `run_scripted` reverted to send every prompt first and `sens-S1` run as the candidate: the store shows no `build_episode` job and no claim. It is recorded for the engine's owner to decide. Nothing in `src/` changed.

## Rejected

- **Add the four to the gate's smoke population.** That changes ACCEPTANCE_TESTS §6.1's frozen 12 and every gate measure computed over them, and it would make the eleventh gate incomparable with the tenth.
- **Make the obvious command fail.** A failure written into the code is recoverable from the code: a capable agent reads `check.py` and avoids it. A failure written outside the repository would be invented machine state that the oracle could not check in both arms.
- **Loosen the generic repeated-mistake count to fuzzy command matching for every scenario.** That changes the measure the 12 report. The named measure is defined per scenario and is reported only for this set.
