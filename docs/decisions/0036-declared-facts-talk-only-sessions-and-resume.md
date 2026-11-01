# Decision 0036: A declared fact keeps its file, a talk-only session is curated, a new session's start resumes the one active task

Status: accepted (Task 9 prompt slice, Task 6 segmentation, Task 11 retrieval; preview) · Date: 2026-11-01 · Engine: `0.1.0.dev6` · Observed: the fourth live gate (`0.1.0.dev5`, `extract_claims@3`, Claude Code 2.1.310, 6 slots), compared with the third gate's records

## Context

The fourth live gate ran complete and clean in 44.7 minutes at 6 slots: 24 trials with no error and no contamination, every wait quiet, three workload days (33, 43 and 28 calls, none exhausted) and all five demonstrations. It failed for two reasons: conflict preservation was 0/1, and 31 items await a reviewer's labels. Model-drafted labels (`docs/evaluations/preview-live-2026-11-01/adjudication.suggested.json`, every label null) put claim support at 22/23, useful recall at 7/7 and failed-approach recall at 2/2, with R2 #0 suggested `evidence_absent`. If a reviewer adopts them, conflict preservation is the only §5.1 target the gate misses. `extract_claims@3` recovered both lessons that the third gate missed because a pipe hid the failure (L1 #1, as an inferred fact), and L2's declaration.

Three causes showed in the records:

- **R4, the failing measure, was caused by `@3`.** In session A the user said "Remember for this project: notes are stored in notes.json under NOTES_HOME."
  - `@3`'s new passage ("Remember …" → a `user_declared` decision or preference) recorded this as a **decision**.
  - The dependency passage gives a decision no file dependency, so when `fieldnotes/store.py` changed before session C, the claim stayed `current`. C's prompt packet delivered it as current, and the retrieval point "conflict or freshness label" failed.
  - In the third gate (`@2`), the same statement became an inferred **fact** depending on `fieldnotes/store.py`, labeled `needs_revalidation` at C's prompt. That met the point.
  - The working agent noticed the mismatch and followed the code, so the task succeeded. Memory still delivered a stale statement as current.
- **R3 and C3: a session that only talked was never curated.** `episodes.segment.decide` kept a range with no tool calls open forever, so it produced no episode, no extraction and no task narrative.
  - R3's session A ("Keep the grocery budget under $600 per month for my planning") ran no tool in either gate, and the only curation in the trial followed session C.
  - The $700 correction was recorded from C alone ("replacing the earlier $600 limit", C's own words). The superseding that the gold expects could not happen.
  - SYSTEM_SPEC §3.5 makes a durable explicit decision a claim, and lists session end among the checkpoints.
- **L1 and L4: a new session's start was empty in both gates.** This conforms to the spec as written.
  - SYSTEM_SPEC §5.1.1 sends a session-start lookup without a binding to `(workspace_id, task_id=null, session_start)`. Decisions 0013 and 0019 carry only open questions there, and a new session is linked to an earlier task only after three path-bearing actions (§3.2), by which time the agent has acted.
  - In L4, session B was asked to "continue the refactor where we left off" and redid step 1. Its prompt packet held the three-step plan through a lexical match, but no task state and no episode.
  - This contradicts §1's continuity across sessions and §3.5's "Knowledge/episodes → working state: new relevant task".
- **The R3 candidate also wrote an unparseable `groceries.csv`.** An item had an unquoted comma, so its cost column read `pasta`. The oracle raised and reported `oracle_error` instead of judging the file.

## Decisions

1. **`extract_claims@4`.** `prompts/extract_v4.md` is `extract_v3.md` with its declaration passage replaced. The new passage separates what the user wants from what the user says the project is:
   - A user's explicit statement is still durable in itself, even when the session's tools only read files or none ran.
   - A stated rule, decision or preference is a `user_declared` decision or preference citing those words.
   - A statement of how the project is, such as where it stores its data or which file, format or command it uses, is a `user_declared` fact citing those words, with the file dependencies that the unchanged dependency passage describes. A later change to that file then labels the claim instead of delivering it as current.
   - A test checks that `@4` is exactly `@3` with that passage replaced. `@1`–`@3` keep their golden digests and are still served to jobs that pinned them.
2. **A session that only talked settles at its end** (amends the segmentation rule; §3.5 already names session end as a checkpoint).
   - `segment.decide` settles a range with no tool calls at session end when it holds a user request. Before the end, a turn without tools is still no attempt boundary.
   - `extract.schedule_for_episode` now schedules any settled episode with source events. `worth_extracting` still cancels the job without a call when no user request, failure or test result is in it.
   - `build_episode` still needs steps, so a zero-step episode gets no narrative call. `update_task` is scheduled as at any checkpoint.
   - The cost is at most two ordinary calls per talk-only session (extraction and task narrative), plus review when a claim is proposed.
3. **A fresh session's start resumes the workspace's one active task** (amends SYSTEM_SPEC §5.1.1, the DATA_CONTRACTS §8 row and decision 0019's session-start sentence).
   - When no binding exists yet and exactly one task in the workspace is `active`, the session-start packet carries that task's working state and its episodes.
   - Both compilers do this: the published workspace view the hook reads, and the service path.
   - Each item has reason `task_continuity` with the text "the project's one active task; not yet linked to this session".
   - Nothing is bound: the three-action continuity rule still decides the link, and delivery stays advisory. With no action at session start, no item can be a caution.
   - With no active task, or two or more, nothing more than open questions is carried. A paused task is left out, because a view has no wall-clock time to apply the 24-hour window with.
   - Durable claims are **not** resumed: they keep their own relevance rules at the prompt and before actions. This also keeps the engine-mode delivery probe exact. Its prompt and pre-action nonces live in claims backed by the setup task's events, and carrying them at session start would let a nonce reach the agent before the path under test. The task and episode texts there are built from nonce-free setup events.
4. **The R3 and L3 oracles judge an unparseable grocery list.** `grocery_csv_parses` is a failed check, not an oracle error, and the task still fails.
5. **Engine `0.1.0.dev6`.** The wheel changes, so the next live run needs a fresh pilot (decision 0030 item 2).

## Rejected

- **Change the L1 and L4 gold to match the spec.** That would hide a gap that L4's redone step shows in the product.
- **Bind a new session to the one active task at its start.** The three-action evidence exists so that a wrong link can't overwrite task state. An advisory packet needs no link.
- **Resume the task's claims too.** That would break the delivery probe's one-item isolation (decision 3), and those claims already reach the session through the relevance rules when they matter.
- **Detect a correction in the prompt hook** (R3's "Correction: … not $600"). Hooks never wait for a model, and a phrase rule would be the declaration heuristic that SYSTEM_SPEC §7.1.2 rules out.
- **Settle a talk-only range at every turn.** That would make each conversational turn an attempt and a model call.

## Tests

- `test_prompt_digests_are_pinned_separately` (integration, admission) checks:
  - `@4` is current, with its golden digest;
  - `@4`'s text is exactly `@3` with the passage replaced;
  - `@3` keeps its digest.
- `test_a_session_without_tool_calls_settles_at_session_end` (integration, episodes). The real tool-less session's records:
  - after Stop, there is no episode;
  - after SessionEnd, there is one settled zero-step episode, whose objective holds the declaration;
  - one `extract_claims` and one `update_task` job are queued, and no `build_episode`.
- `test_a_fresh_session_start_carries_the_one_active_task` (integration, retrieval), on both the service and hook paths:
  - the task and its episodes carry `task_continuity`;
  - its claims are not resumed;
  - a second active task removes it.
- `test_r3_judges_an_unparseable_grocery_list_as_a_failed_check` (unit, smoke oracles).
- Engine-scheduled extraction jobs pin `@4` (`test_requests`), and the deny-spelling test is re-pinned to `0.1.0.dev6`.

## Limits

- **R3's prompt point may now fail where it passed by absence.**
  - Session A's $600 is now recorded, and session C's correction is in C's own prompt, which is extracted only after C. So C's prompt packet will likely deliver the $600 preference as current through the lexical match.
  - If C's task then fails for any reason, `incorrect_confident_guidance` counts it.
  - This is how an advisory store behaves before a correction is curated. After C, extraction can supersede the $600, and the reviewer judges that.
- **Resume can carry an earlier task into an unrelated new session** when that task is the only active one. It is labeled "not yet linked", is context only, and stays within the 2,000-token session-start budget.
- **The task narrative is weak.** In the fourth gate, 29 of 43 `update_task` calls returned no operation. Of the 14 that proposed one, 7 were admitted; the others were refused for invalid results, completion without evidence, a rejected group or a root mismatch. L4's session A left no next action, although the agent's reply named step 2. Resume carries the objective and the episode either way; improving the narrative prompt is separate work.
- **A plan scoped to one session became a rule.** L4's plan claim turned "do step 1 only, then stop" into "Step 1 only is to be done in a session". Session B cited it, and the suggested label is `unsupported`.
- **A prompt is not a guarantee.** Whether the live extractor records a declared fact with its file is model behavior, shown only by a live run with one trial per scenario.

## Consequences

The owner provisions a seventh pilot from `dist\recalith-0.1.0.dev6-py3-none-any.whl`, certifies its route, runs the engine-mode delivery probe, then runs the fifth gate with 6 slots (`probe-private\run-pilot7-gate5.ps1`; BUILD_PROGRESS handoff).
