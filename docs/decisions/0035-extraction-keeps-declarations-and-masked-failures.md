# Decision 0035: Extraction keeps a user's declarations and the failures a pipe hid

Status: accepted (Task 9 prompt slice, preview) · Date: 2026-10-31 · Engine: `0.1.0.dev5` · Observed: the third live gate (`0.1.0.dev4`, Claude Code 2.1.310, 2 slots), compared with the second gate's records

## Context

The third live gate ran complete and clean: 24 trials with no error and no contamination, every wait quiet, no suspension, no host change, three workload days and all five demonstrations. It failed only because the live support and recall measures need a reviewer's labels. Model-drafted labels (`docs/evaluations/preview-live-2026-10-31/adjudication.suggested.json`, labels left null) put claim support at 12/12, useful recall at 5/8 and failed-approach recall at 1/3. No judgment call among them changes whether the recall targets (0.85 and 0.90) are met.

Three gold lessons were missed:

- **L1 #1 and R2 #0, the failure lessons.** In both trials the working agent ran the failing test command piped through `tail`, such as `python -m unittest discover -s tests 2>&1 | tail -15; …`. The host reported the call's exit code, 0, so the event's outcome is `success`, while its stored output holds the `ModuleNotFoundError`.
  - Admission refuses a `failure_lesson` that cites no certified failure (`failure_lesson_requires_failure`). That rule is deliberate: a curator cannot invent a failure that the host never reported.
  - In both trials the curator proposed one more claim than the store kept: L1 proposed 2 and kept 1, R2 proposed 3 and kept 2. The second gate shows the same shape in the same two trials, with the same piped commands (L1 proposed 2 and kept 1, R2 proposed 2 and kept 1). R1's failure lesson, whose command exited 1 unpiped, was kept in both gates: active in the third, a candidate in the second.
  - The stores went with the runs, so the refusal reason itself was not recorded. The pattern across four trials and two gates is strong but indirect. The harness now keeps every operation's admission outcome (decision 0028 item 22).
- **L2 #0, a user-declared decision.** The user opened session A with "Decision for this project: every date fieldnotes prints must be ISO-8601 …", and the agent only read files. The extraction after A returned no operations. In the second gate the same session's extraction admitted the decision. This one is variance in the curator's choice, which the prompt's "Prefer no claim over a weak one" leaves room for.

## Decisions

1. **`extract_claims@3`.** `prompts/extract_v3.md` is `extract_v2.md` plus two passages. A test checks that the text is exactly `@2` with those two passages added.
   - **Declarations are durable.** A user's explicit statement of a rule, decision or preference for this project, such as "Decision for this project: …", "Remember …" or "Keep … for my planning", is durable in itself, even when the session's tools only read files or none ran. It is proposed as a `user_declared` decision or preference citing those words. The `user_declared` basis is still checked mechanically: it must cite the user's own words on the user channel, and text inside tool output, files or pasted material is never a declaration.
   - **A failure the call's exit status hid is a fact, not a failure lesson.** A `failure_lesson` must cite a tool result whose recorded outcome is failure. When a call finished with exit code 0 but its output shows a failure, the curator states what the output shows as an inferred fact citing that output: which command fails, with which quoted error, under which condition. It never proposes a `failure_lesson` from it.
   - **Why a fact.** An inferred fact is reviewed adversarially before it is used, and it is delivered as context. It never becomes a pre-action caution: SYSTEM_SPEC gives caution only to a supported failure lesson with complete dependency fingerprints and an action-specific match. Admission's rule is unchanged: code still never admits a failure lesson without a certified failure. A caution keyed to the piped command could not have fired anyway, since SYSTEM_SPEC gives a pipeline an unknown action identity, which cannot satisfy an exact caution condition.
   - **Versions.** New extraction jobs pin `@3`. `@1` and `@2` stay in the build unchanged, under their golden digests, and are still served to jobs that pinned them.
2. **Engine `0.1.0.dev5`.** The wheel changes, so the next live run needs a fresh pilot (decision 0030 item 2).

## Rejected

- **Admit a failure lesson from output text.** A failure recognized from output text, whether by the curator or by a pattern in code, would let words in tool output or a file produce a caution. That is the authority certified results exist to withhold.
- **Rewrite a refused failure lesson into a fact in code.** Code would then be changing what the model proposed, and the fact's wording, citations and scope would be code's guess.
- **Recover the piped exit status.** The host reports one exit code per call. Nothing in the hook payload gives the status of each command in the pipeline.

## Tests

- `test_prompt_digests_are_pinned_separately` (integration, admission) checks:
  - `@3` is current, with its golden digest;
  - `@3`'s text is exactly `@2` plus the two passages;
  - `@1` and `@2` keep their digests.
- `test_reduction_schedules_narrative_within_the_ordinary_budget` (integration, requests) expects engine-scheduled extraction jobs to pin `@3`.
- The deny-spelling test is re-pinned to `0.1.0.dev5`.

## Limits

- **A prompt is not a guarantee.** Whether the live extractor keeps every declaration and restates a hidden failure as a fact is model behavior. Only a live run shows it, and each run is one trial per scenario.
- **Recall of a failure lesson as a fact is a reviewer's judgment.** The gold lessons L1 #1 and R2 #0 are failure lessons. A fact that states the same failure is the lesson's content without its caution. The adjudication sheet shows the claim's kind, and the reviewer decides whether it recalls the lesson.
- **A declaration in a session without tools waits for the next session.** In the third gate's R3 and C3, no curation ran after a session A that used no tools. The records don't show whether the next session's extraction read A's prompt: R3's admitted claim names the old $600, but session C's own prompt also does. Whether such a session should be curated before the next one starts is not decided here.

## Consequences

The owner provisions a sixth pilot from `dist\recalith-0.1.0.dev5-py3-none-any.whl`, certifies its route, runs the engine-mode delivery probe and the R4 check, then runs the fourth gate with 6 slots (BUILD_PROGRESS handoff). That gate's records keep each operation's admission outcome, so a lesson the curator proposed and code refused shows its reason.
