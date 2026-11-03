# Decision 0038: A malformed operation says what failed

Status: accepted (Task 7 provider boundary, preview) · Date: 2026-11-03 · Engine: `0.1.0.dev8` · Observed: the sixth live gate (`0.1.0.dev7`, Claude Code 2.1.310, 6 slots)

## Context

The sixth live gate ran complete: 24 trials with no error and no contamination, every wait quiet, three workload days within budget. It failed on two counts.
- **The forgetting demonstration** was not shown. It needs L3's live claim naming the $600 limit, and there was none.
- **Useful recall.** The drafted labels give 5/7, whatever the judgment calls. The two lessons missed were the user's declarations in L2 and L3.

Decision 0037 worked: L1's pipe-hidden failure was worded as a condition and reviewed supported, and failed-approach recall is 2/2.

Both declarations were lost to code's strict checks. Neither was lost to the curator's judgment.
- **L3.** The extraction after session A proposed one claim, and admission refused it with `declaration_requires_user_evidence`. Admission returns that code when no cited evidence is the user's own words. The cited records went with the trial store.
- **L2.** The record shows an extraction with no operations and no stated reason, but the contract refuses an empty proposal without a reason. The parser explains it: when every operation a model returns fails strict validation, the stored response holds those operations only under `malformed`, with no operations and no reason. The harness did not read `malformed`. So L2's extraction most likely proposed the decision, and validation refused it.

The same pattern is far larger in `update_task`:
- In the fourth, fifth and sixth gates, 27 of 43, 24 of 45 and 30 of 45 `update_task` calls were stored with no operations and no reason. That is the "returned no operation" count the earlier checkpoints logged as weak narrative.
- In the four kept R4 rerun stores, every such `update_task` proposal holds `malformed` entries: 6 of 8 calls. One extraction there also had a malformed operation beside two valid ones.

A `MalformedOperation` keeps only its index, `local_ref`, dependencies and the generic `malformed_operation`, by design, because the raw text is not retained. So no record says which rule failed. Plausible model replies fail for different reasons, for example:
- a missing `reason`;
- a string appended to a list field;
- evidence attached to a task patch;
- a title over 256 characters.

Fixing it now would be a guess.

## Decisions

1. **`MalformedOperation.detail`** (DATA_CONTRACTS §7.1; at most 240 characters; null in older records). It says what failed without quoting the model:
   - up to three failing fields' paths and validation error types, such as `reason:missing` or `patches.0.?:extra_forbidden`;
   - for a `value_error`, the validator's own message, which is code's text, such as `patches.0:value_error(append adds one item to a list field)`;
   - `kind:<kind>` when a valid operation's kind is not permitted for the purpose.

   A path part that is not a short identifier or index is written `?`, such as a union branch label or a key the model invented, so model text cannot reach the record through a field name. Validation inputs are never included.
2. **The harness reads it.** Each curator call in a trial record lists its malformed operations with `detail` (decision 0028 item 27).
3. **Engine `0.1.0.dev8`.** The wheel changes, so the next live run needs a fresh pilot (decision 0030 item 2).

## Rejected

- **Keep the malformed raw text.** Decision 0007 drops it, so that an invalid reply's text is never retained as if it were a proposal.
- **Guess the fix now.** One prompt change per plausible cause, unmeasured, would trade one guess for another.
- **A repair round now.** Code's refusal codes could go back to the model in one bounded retry, so a mechanically refused proposal could be corrected. That is not an objection the review withholds (decision 0011). It would change the request, budget and retry rules, though, and the next gate's details will show whether it is the right fix. It is recorded here as the likely next step if the details show the refusals are citation or shape mistakes.

## Tests

`test_a_malformed_operation_says_what_failed_without_quoting_the_model` (unit, provider contract) runs four replies through the adapter's parser:
- a missing `reason`;
- an `append` of a string;
- a key the model invented;
- a valid operation of a kind `update_task` may not return.

It checks each detail, and checks that no text the model wrote appears in any of them. `test_a_refused_claim_operation_keeps_what_it_proposed_and_cited` (unit, live evaluation) checks that the harness records the malformed entries. The deny-spelling test is re-pinned to `0.1.0.dev8`. The `ModelResponse` schema is regenerated.

## Limits

- **Diagnosis, not a fix.** `update_task` and extraction replies will fail validation as often as before. Only the next live run's records show why.
- **Three errors at most.** An operation with more failing fields shows its first three.

## Consequences

The owner provisions a ninth pilot from `dist\recalith-0.1.0.dev8-py3-none-any.whl` and runs the seventh gate, in one command (`probe-private\run-pilot9-gate7.ps1`, BUILD_PROGRESS handoff). Its records show what every malformed operation got wrong and what every refused claim operation cited. If the gate fails on recall again, the fix starts from those records.
