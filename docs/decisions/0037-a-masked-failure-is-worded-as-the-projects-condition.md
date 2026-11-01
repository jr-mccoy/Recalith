# Decision 0037: A failure a pipe hid is worded as the project's condition

Status: accepted (Task 9 prompt slice, preview) · Date: 2026-11-01 · Engine: `0.1.0.dev7` · Observed: the fifth live gate (`0.1.0.dev6`, Claude Code 2.1.310, 6 slots). Prepared on the branch `claude/dev7-masked-failure-wording` and merged when the owner accepted the recommendation that L1 #1 was missed, so the fifth gate failed on failed-approach recall.

## Context

The fifth live gate ran complete and clean. It met every measure that needs no labels and awaits a reviewer's labels. The model-drafted labels (`docs/evaluations/preview-live-2026-11-01-gate5/adjudication.suggested.json`, every label null) give support 18/18, useful recall 6/7 and failed-approach recall 1/2. The one missed lesson is L1 #1, "Without PYTHONPATH=src the src-layout package is not importable from tests".

- **What happened.** Session A ran `python -m unittest discover -s tests 2>&1 | tail -8; echo ---; PYTHONPATH=src …` in one call. The host reported exit 0, so the failure is not certified, and the extractor stated it as inferred facts, as decision 0035 asks. The review returned `revise` for both, and they stayed weak candidates:
  - `claim_1da95d44`: "In a Bash call that ran python -m unittest discover -s tests 2>&1 | tail -8 before the PYTHONPATH=src run, the output ended with ModuleNotFoundError … and FAILED (errors=1); the call's recorded exit status was 0 because of the pipe."
  - `claim_2c0f2362`: "… the unit tests import it only when PYTHONPATH=src is set."
- **What the fourth gate admitted.** The same failure in the same scenario, worded as a condition, was reviewed supported: "Running `python -m unittest discover -s tests -v` from the project root, without PYTHONPATH=src, fails on import with ModuleNotFoundError: No module named 'ledgerlite' in the captured output."
- **The difference is the wording.** The fifth gate's facts describe one call: its pipe, its recorded exit status and the reason the status hid the failure. Or they claim more than the runs showed, with "only when". The review prompt asks for the strongest reasons a candidate is unsupported or overbroad. A fact about a single call, or an exclusive claim from one failing and one passing form, gives it those reasons. The objections themselves went with the trial stores, so this reading is indirect. From the next gate, the trial record keeps them (decision 0028 item 25).
- **Why it matters to the gate.** Failed-approach recall needs at least 0.90, and a run has two or three instructive failures. One failure lesson left as a candidate fails the gate.

## Decisions

1. **`extract_claims@5`.** `prompts/extract_v5.md` is `extract_v4.md` with the masked-failure sentence's wording guidance replaced. A test checks that the text is exactly `@4` with that one replacement.
   - **Kept:** a failure the call's exit status hid is stated as an inferred fact citing the output, never as a `failure_lesson`. Admission's rule is unchanged (decision 0035).
   - **New:** word that fact as the project's condition that a later session can act on, such as "Running `<command>` from <where>, without <setting>, fails with <quoted error>.", not as an account of one call, its recorded exit status or the pipe.
   - **New:** claim no more than the runs showed. One failing form and one passing form do not show that the passing form is the only one that works.
   - **Versions.** New extraction jobs pin `@5`. `@1`–`@4` stay in the build unchanged, under their golden digests, and are still served to jobs that pinned them.
2. **Engine `0.1.0.dev7`.** The wheel changes, so the next live run needs a fresh pilot (decision 0030 item 2).

## Rejected

- **Count an episode as recall.** The failure reached session B inside the settled episode delivered at its start, and B used `PYTHONPATH=src` directly. SYSTEM_SPEC §3.4 makes long-term records claims, and whether a lesson is recalled is the reviewer's label. It is not a reason to change the measure.
- **Send the review's objections back to the extractor.** A resubmission path would make `revise` productive, but decision 0011 withholds a candidate's earlier assessment from later requests, so that the extractor does not learn the reviewer's wording. Changing that is a design change of its own.
- **Loosen the review prompt.** The review's objections to a narrated or exclusive fact are the review doing its job.
- **Rewrite the narrated fact in code.** Code would be changing what the model proposed (decision 0035).

## Tests

- `test_prompt_digests_are_pinned_separately` (integration, admission) checks:
  - `@5` is current, with its golden digest;
  - `@5`'s text is exactly `@4` with the one replacement;
  - `@1`–`@4` keep their digests.
- `test_reduction_schedules_narrative_within_the_ordinary_budget` (integration, requests) expects engine-scheduled extraction jobs to pin `@5`.
- The deny-spelling test is re-pinned to `0.1.0.dev7`.

## Limits

- **A prompt is not a guarantee.** Whether the live extractor words a hidden failure as a condition, and whether the review then supports it, is model behavior. Only a live run shows it, one trial per scenario.
- **The reason is inferred.** The fifth gate's objections were not retained. The next gate's record keeps them (decision 0028 item 25).
- **R2 #0 is unchanged.** In the fourth and fifth gates, R2's session A fixed the import itself by writing `tests/__init__.py`. Its lesson was then no longer true, and the drafted labels call it `evidence_absent`.

## Consequences

The owner provisions an eighth pilot from `dist\recalith-0.1.0.dev7-py3-none-any.whl`, certifies its route, runs the engine-mode delivery probe and runs the sixth gate with 6 slots, in one command (`probe-private\run-pilot8-gate6.ps1`, BUILD_PROGRESS handoff). That gate's records keep each claim's review verdict and objections (decision 0028 item 25). It passes only with a reviewer's labels.
