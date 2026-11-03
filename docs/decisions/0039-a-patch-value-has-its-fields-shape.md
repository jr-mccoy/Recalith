# Decision 0039: A patch value has its field's shape, and evidence is never inside a payload

Status: accepted (Task 7 curator prompts, preview) · Date: 2026-11-03 · Engine: `0.1.0.dev9` · Observed: the seventh live gate (`0.1.0.dev8`, Claude Code 2.1.310, 6 slots)

## Context

The seventh gate ran complete: 24 trials with no error and no contamination, every wait quiet, three workload days within budget. L3's declaration was admitted this time, so the forgetting demonstration ran end to end. It failed on that demonstration (decision 0028 item 29), and the drafted labels meet every labeled measure only through two judgment calls.

Decision 0038's `detail` now says why operations failed validation. Across the 12 candidate trials and three workload days:
- **`update_task`.** Of 45 calls, 34 had a malformed operation, and 31 of those had nothing else. Every malformed operation failed the same rule, `append adds one item to a list field`. The model appended bare strings to list fields such as `plan`, `constraints` and `open_questions`, where each item is a supported text: an object with `text`, `evidence` and `basis`. Five more calls failed to apply (`invalid_result`), consistent with a bare string set on `next_action`. Four set `completed` without a completion basis that cites evidence.
- **`build_episode`.** Of 45 calls, four had a malformed operation: a bare string, in one case over 256 characters, where a field takes a supported text. Six more failed to apply.
- **`extract_claims`.** L2's extraction after session A proposed the user's ISO-8601 decision and a second claim. Both carried their evidence inside `payload`, not in the operation's own `evidence` array, so both were refused: L2's lesson was missed for the second gate running. (An operation's own `evidence` field is valid, so that error can only have come from the payload.) In L4, one extraction operation carried a `claim_ref` key where its kind has none.
- **`revalidate`.** Two of four calls were refused. One operation carried a `supersedes` key, which no revalidation kind has. One asked for a file excerpt without its `path`.

The old detail cannot say whether those two keys sat inside the payload or beside it.

The causes are in what the model is told:
- **No shape for patch values.** `update_task@1` and `build_episode@1` never describe a patch value. The request's `output_schema` types a value as an object or a short string, so it cannot say which field takes which.
- **A misleading detail path.** `detail` reported a payload's own failures without the `payload.` prefix, so `evidence:extra_forbidden` read as the operation's own field.

## Decisions

1. **Shaped narrative prompts.** `update_task@2` and `build_episode@2` say what each patch value is. A supported text is `{"text": ..., "evidence": [...], "basis": ...}`, with evidence entries shaped like an operation's and basis `observed`, `user_declared` or `inferred`.
   - In a task, `title` is a plain string of at most 256 characters. `next_action` and `completion_basis` take one supported text. `plan`, `constraints` and `open_questions` change only by `append`, one supported text per patch, never a bare string or a list. Completion sets `completion_basis` in the same operation as the status patch, with evidence citing the work done.
   - In an episode, `objective` and `outcome` take one supported text, and `preconditions` and `unresolved` take one per `append`. Recorded steps cannot be edited, so a failed step's cause goes in the outcome text.
2. **Evidence stays out of payloads.** `extract_claims@6` (`extract_v6.md`) is `@5` plus one sentence: an operation's evidence is its own `evidence` array, and a payload holds only the keys `output_schema` gives its kind. A `propose_claim` payload has no `evidence`, `claim_ref` or `supersedes`, and an existing claim changes only through `attach_evidence` or `revise_claim`. `revalidate@3` (`revalidate_v3.md`) is `@2` plus the same rule for `revise_claim`, which supersedes with `change_claim_status`. It also says a file or dependency `request_evidence` names its path in `payload.path`.
3. **Payload failures are named under `payload`** (DATA_CONTRACTS §7.1). The parser re-roots a payload model's validation errors at the operation's `payload` key, as in `payload.patches.2:value_error(...)` and `payload.evidence:extra_forbidden`.
4. **The pinned versions.** New jobs pin `update_task@2`, `build_episode@2`, `extract_claims@6` and `revalidate@3`. A job that pinned an older version is still served its text, and the review prompt is unchanged.
5. **Engine `0.1.0.dev9`.** The wheel changes, so the next live run needs a fresh pilot (decision 0030 item 2).

## Rejected

- **The provider's schema enforcement.** Decision 0023 already declined `output_config.format`, because it adds a provider-written system prompt and rejects the constraints the engine's schema uses.
- **A per-field discriminated patch schema.** It would let the schema say each field's shape. But the reducer applies typed patches through the same model, so it would change every task and episode write path to fix a gap the instructions can close.
- **Code repairing a reply's shape,** such as wrapping a bare string as a supported text or moving `evidence` out of a payload. That would invent a basis and support the model never gave, and strict validation is the boundary (decision 0007).
- **A repair round now.** Every observed refusal is one of the shape mistakes the new text names. If shape errors persist after this change, decision 0038's bounded retry remains the next step.

## Tests

- `test_task_and_episode_narratives_apply_in_the_shapes_their_prompts_name` (integration, requests) runs the real lifecycle session through the worker, with a backend that answers the real requests in two ways:
  - **In the shapes the @2 prompts name.** The title, next action, a plan item, a constraint, the episode outcome and an unresolved item all apply, with their evidence and basis.
  - **With bare strings.** The task and episode are unchanged, and the malformed detail names `payload.patches.2` and `payload.patches.3`.

  It pins both prompts' digests and checks that `@1` is still served.
- `test_a_malformed_operation_says_what_failed_without_quoting_the_model` now expects `payload.`-rooted paths and adds a `propose_claim` with evidence inside its payload.
- The golden-digest tests pin `extract_claims@6` and `revalidate@3`. They check that each is its predecessor plus exactly the new text, and they keep the older digests.
- The scheduling test expects the new pinned versions. The deny-spelling test is re-pinned to `0.1.0.dev9`.

## Limits

- **Instructions, not enforcement.** A model can still send a bare string. It is refused as before, now with a `payload.` path that names it.
- **Not measured live.** Whether the shapes cure the refusals, and whether better task narratives change delivery, shows only in the next gate.
- **The labeled measures stay thin.** The review returned `revise` for revisions after a dependency change in L1 and R1, which left two once-active lessons as weak candidates at the end. As drafted, both lessons count as recalled, but by judgment calls. This decision does not change the review.

## Consequences

The owner provisions a tenth pilot from `dist\recalith-0.1.0.dev9-py3-none-any.whl` and runs the eighth gate, in one command (`probe-private\run-pilot10-gate8.ps1`, BUILD_PROGRESS handoff). The forgetting demonstration now records what carried the forgotten value, if anything did (decision 0028 item 29).
