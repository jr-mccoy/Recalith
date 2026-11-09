# Recalith build log, November 2026 (historical)

The per-checkpoint narrative moved out of [BUILD_PROGRESS](../../BUILD_PROGRESS.md) by decision 0047; it is kept verbatim here. Each entry is the state of the work on its date; later entries and decision records supersede earlier ones. References elsewhere to "the X checkpoint in BUILD_PROGRESS" resolve to these files.

### 2026-11-01 — The sixth pilot and the fourth live gate (the owner's run): complete and clean, failed on R4's conflict label; decision 0036 (engine 0.1.0.dev6)

- **The run.** The owner ran `probe-private\run-pilot6-gate4.ps1` (untracked) from an ordinary window. It started at 16:57Z, on repository `0510cf2`, and every step exited as expected. The log is `probe-private\pilot6-gate4-run.log` (untracked; checked for the key: none).
  - **The pilot, steps 1–8, on `C:\Code\rl-pilot6`:**
    - the `0.1.0.dev5` wheel was provisioned at the recorded digest;
    - the provider probe certified the route (17.3 s), and the runtime check passed with both isolation checks;
    - `integrate claude` installed 11 hooks and 450 deny rules;
    - the engine-mode delivery probe found every required path healthy, live on 2.1.310 (518.5 s);
    - `status` reported ready.
  - **The fourth gate**, with 6 slots, into `C:\Code\rl-gate4`: exit **8** after 2,683 s (44.7 min). At 2 slots the third gate took 102 min. The whole run took about 54 minutes.
- **Complete and clean:**
  - All 24 trials ran, with no error, no contaminated arm and no suspension. Every wait was `quiet`, and the host stayed at 2.1.310.
  - **Workload days:** all three ran at once (33, 43 and 28 calls), and none hit any pool. No call ended at its output cap.
  - **Demonstrations:** all five shown.
  - **Cost:** foreground $1.78 over 48 sessions; background 194 model calls and 4,371,430 ledger tokens.
  - **Clean tree:** the report says `tree_clean: false`, because the pilot's probes had just rewritten `docs\host-compatibility.json`. That file is committed with this checkpoint.
- **Outcomes, candidate/baseline:**
  - L4 and R3 failed/succeeded; every other scenario succeeded in both arms.
  - The paired differences are inconclusive, apart from token and time costs. No superiority claim.
- **The gate failed with two reasons:**
  - `quality_targets_unmet:conflict_uncertainty_preservation`: 0/1, R4;
  - `claims_unadjudicated:31`: 23 claims and 8 lessons.
- **The measures that need no labels:** incorrect confident guidance 0; legitimate retries discouraged 0/2; irrelevant caution 0/3; routine human maintenance 0. Conflict preservation 0/1 is not met.
  - **Retrieval points:** 9/12. Unmet:
    - L1 and L4 at session start, both packets empty again;
    - R4 at C's prompt, where the stale storage claim was delivered as `current`.
- **Adjudication.** As for the third gate, no `adjudication.json` was written (ACCEPTANCE_TESTS §5). `adjudication.suggested.json` (every label null) is in the results directory and in the sanitized record.
  - **Suggested totals:** support 22/23, useful recall 7/7, failed-approach recall 2/2. R2 #0 is suggested `evidence_absent`: session A's plain discovery failed with "Start directory is not importable" and A itself added `tests/__init__.py`, so the gold's `ModuleNotFoundError` never occurred (`missed` is defensible). The one claim suggested unsupported is L4's plan, which turned "do step 1 only, then stop" into a rule for every session.
  - **What the labels would leave:** if a reviewer adopts them, every §5.1 target is met except conflict preservation, so labeling alone cannot pass this gate.
- **What `extract_claims@3` changed** (decision 0035), against the third gate:
  - L1 #1's pipe-hidden failure is recalled, as an inferred fact;
  - L2's declared decision is recalled;
  - the curator call records now show every admission outcome. For example, 29 of the 43 `update_task` calls returned no operation.
- **Why the gate failed and what else showed** (decision 0036):
  - **R4, caused by `@3`.** "Remember for this project: notes are stored in notes.json under NOTES_HOME" became a `user_declared` decision without a file. When `store.py` changed, it stayed current. Under `@2` it had been a fact depending on `fieldnotes/store.py`, labeled `needs_revalidation`.
  - **R3:** session A only talked, so it was never curated. The $600 was never recorded, so the $700 correction had nothing to supersede. The candidate's `groceries.csv` then had an unquoted comma, and the oracle raised instead of judging it (decision 0028 item 24).
  - **L1 and L4:** a new session's start carries only open questions until a binding exists, which is the spec as written. L4's session B redid step 1.
  - **L4:** session A's `update_task` set no next action, and session B followed the plan claim's "Step 1 only … in a session".
- **Built after the gate:**
  - `extract_claims@4`: a statement of how the project is becomes a `user_declared` fact with its file dependencies, while a rule, decision or preference stays a decision or preference. `@1`–`@3` are unchanged.
  - A session that only talked settles at its end and is extracted.
  - A fresh session's start carries the workspace's one active task's state and episodes, never its claims. This amends SYSTEM_SPEC §5.1.1, DATA_CONTRACTS §8 and decisions 0013 and 0019.
  - The L3 and R3 oracles' `grocery_csv_parses` check (decision 0028 item 24).
  - Engine `0.1.0.dev6`.
- **Wheel:** `uv build --wheel -o dist` → `recalith-0.1.0.dev6-py3-none-any.whl` (616,573 bytes), SHA-256 `6cbf968dd5609f56ba5f42cf6ba210858a1a20a17b3bba49ad6453a484946243`. `tools/build_release.py --out <scratch>` → `problems: []`, `signing: unsigned`, the same wheel digest. The wheel ships `extract_v4.md`; the wheelhouse is unchanged.
- **The sanitized record** is [`docs/evaluations/preview-live-2026-11-01/`](evaluations/preview-live-2026-11-01/report.md): 34 files, with the results directory as `<run>` and temporary paths as `<temp>`. A scan by count found 0 user names, drive paths, keys, email addresses or model identifiers.
- **Prepared, not run:** `probe-private\run-pilot7-gate5.ps1` (untracked; parses cleanly, ASCII only). It runs a fresh pilot's steps 1–8 on `C:\Code\rl-pilot7` from the `0.1.0.dev6` wheel, then the fifth gate with 6 slots into `C:\Code\rl-gate5`, asking for the key once.
- **Tests** (native Windows, Python 3.13, `--basetemp C:/Code/t`):
  - **New:**
    - `test_a_session_without_tool_calls_settles_at_session_end` (episodes);
    - `test_a_fresh_session_start_carries_the_one_active_task` and `…_tasks_episodes` (retrieval, both the service and hook paths; a second active task removes it; claims are not resumed);
    - `test_r3_judges_an_unparseable_grocery_list_as_a_failed_check` (smoke oracles);
    - the extended `test_prompt_digests_are_pinned_separately`: `@4`'s digest, `@4` is `@3` with the passage replaced, and `@3` keeps its digest.
  - **Runs:**
    - `tests/integration/test_retrieval.py test_episodes.py test_delivery.py tests/unit/test_smoke_scenarios.py` → 107 passed, 1 skipped;
    - `tests/integration/test_claim_admission.py::test_prompt_digests_are_pinned_separately` → passed.
  - `uvx ruff@0.14.0 check --select F,E9,B` on every changed Python file → clean. `tools/generate_schemas.py --check` → exit 0. `tools/release_checklist.py` → no problems, verdict `blocked`.
  - **The whole suite** (`tests`) → 1 failed, 1,346 passed, 61 skipped (40.8 min).
    - **The failure:** `test_abandoned_scratch_is_settled_before_pruning` (retention). It assumed a new session's start delivers nothing, but the start now carries the one active task, so the scratch held an `emitted` entry before the killed hook's reservation. The behavior under test is unchanged: the dead hook's reservation is still settled `uncertain` before the scratch is pruned. The test now checks that attempt by its ID, and `tests/integration/test_retention.py` → 24 passed, 1 skipped.
    - **A rule slip:** that test edit was made while the whole suite was still running. The suite had already run that file, so its other results stand.
    - **The likeliest-touched files, in a separate run:** working memory, the Claude adapter, requests, claim admission, capture recovery, health, runtime provenance, the capture-only and smoke platform tests, evaluation and live evaluation → 351 passed, 7 skipped.
- **Acceptance:** statuses unchanged. A failed gate and an unrun engine change are not passes.

### 2026-11-01 — The seventh pilot and the fifth live gate (the owner's run): complete and clean, every unlabeled measure met; the result turns on one label

- **The run.** The owner ran `probe-private\run-pilot7-gate5.ps1` (untracked) from an ordinary window. It started at 19:43Z, on repository `4e83f8f`, and every step exited as expected. The log is `probe-private\pilot7-gate5-run.log` (untracked; checked for the key: none).
  - **The pilot, steps 1–8, on `C:\Code\rl-pilot7`:**
    - the `0.1.0.dev6` wheel was provisioned at the recorded digest;
    - the provider probe certified the route (17.7 s), and the runtime check passed with both isolation checks;
    - `integrate claude` installed 11 hooks and 450 deny rules;
    - the engine-mode delivery probe found every required path healthy, live on 2.1.310 (503.8 s), so a new session's resumed task left the probe's nonces in one item each, as decision 0036 intended;
    - `status` reported ready.
  - **The fifth gate**, with 6 slots, into `C:\Code\rl-gate5`: exit **8** after 2,880 s (48.0 min). The whole run took about 57 minutes.
- **Complete and clean:**
  - All 24 trials ran, with no error, no contaminated arm and no suspension. Every wait was `quiet`, and the host stayed at 2.1.310.
  - **Workload days:** all three ran at once (32, 39 and 30 calls), and none hit any pool. No call ended at its output cap.
  - **Demonstrations:** all five shown.
  - **Cost:** foreground $1.73 over 48 sessions; background 194 model calls and 4,227,836 ledger tokens.
  - **Clean tree:** `tree_clean: false` again, because the pilot's probes rewrote `docs\host-compatibility.json`. That file is committed with this checkpoint (scanned: no user names, paths, keys or model identifiers).
- **Outcomes, candidate/baseline:**
  - L3 failed/succeeded: the candidate's `groceries.csv` has unquoted commas ("Rice and grains (rice, oats, pasta)"), so it does not parse (decision 0028 item 24). Its memory was right: it flagged the $625 draft against the $600 limit.
  - R3 succeeded/failed. Every other scenario succeeded in both arms.
  - The paired differences are inconclusive, apart from token and time costs. No superiority claim.
- **The gate failed with one reason:** `claims_unadjudicated:26` (18 claims and 8 lessons).
- **Every measure that needs no labels is met:** incorrect confident guidance 0; conflict preservation **1/1** (R4, met for the first time); legitimate retries discouraged 0/2; irrelevant caution 0/3; routine human maintenance 0.
  - **Retrieval points:** 11/12. L1 and L4 at session start are met now. The one unmet is R3 at C's prompt: the $600 claim was delivered as `current` at the very prompt that corrects it, the limit decision 0036 states (the correction is curated after C). The agent used the $700 and said the memory was stale.
- **What `0.1.0.dev6` changed, shown live** (decision 0036):
  - **R4:** the storage statement became a `user_declared` fact depending on `fieldnotes/store.py`. At C's prompt it was labeled `needs_revalidation`, and it is now `disputed`.
  - **Talk-only sessions:** R3's and C3's sessions A settled at their end and were extracted. R3's $600 was recorded, and the $700 correction superseded it. C3's brainstorm left no claim, which is the quiet case's gold.
  - **Resume:** every learning scenario's session B or C started with the task and its settled episode. L4's session B did step 2 and stopped before step 3.
- **Adjudication.** As for the third and fourth gates, no `adjudication.json` was written (ACCEPTANCE_TESTS §5). `adjudication.suggested.json` (every label null) is in the results directory and in the sanitized record.
  - **Suggested totals:** support 18/18, useful recall 6/7, failed-approach recall 1/2.
  - **L1 #1 is suggested `missed`.** Session A piped its failing discovery through `tail`. The extractor stated the failure as inferred facts, as `@3` and `@4` ask, but the reviewer returned `revise` for both (`claim_1da95d44`, which narrates one call's output and exit status, and `claim_2c0f2362`, which says the tests import the package "only when PYTHONPATH=src is set"). Both stayed weak candidates. The objection texts went with the trial stores. In the fourth gate the same failure, phrased as a condition ("Running … without PYTHONPATH=src fails … with ModuleNotFoundError …"), was reviewed supported. The failure did reach session B, inside the settled episode delivered at its start. `recalled` is defensible only if an episode counts as durable memory; SYSTEM_SPEC §3.4 makes long-term records claims.
  - **R2 #0 is suggested `evidence_absent`**, as in the fourth gate: session A fixed the condition itself by writing `tests/__init__.py`, so the lesson was no longer true when A ended. `missed` is defensible.
  - **What the labels decide.** The report code, run on a scratch copy with the suggestions copied into labels, fails only on `quality_targets_unmet:failed_approach_recall` (1/2). With L1 #1 `recalled` instead, the gate is `passed_smoke` with no reasons. The copy was deleted, and nothing in `C:\Code\rl-gate5` was labeled.
- **Also seen:**
  - `update_task` returned no operation in 28 of 45 calls, as in the fourth gate (the logged follow-up).
  - Pre-action packets carry recent observations of successful reads and edits as context: no caution, but most of each packet.
- **The sanitized record** is [`docs/evaluations/preview-live-2026-11-01-gate5/`](evaluations/preview-live-2026-11-01-gate5/report.md): 34 files, with the results directory as `<run>` and temporary paths as `<temp>`. A scan by count found 0 user names, drive paths, keys, email addresses or model identifiers.
- **Built after the gate** (harness only; the wheel is unchanged): each claim in a trial record keeps its head's review verdict and objections, and the adjudication sheet lists the claims a reviewer does not label, with their review, as context for the recall labels (decision 0028 item 25). The fifth gate's own record predates it.
  - **Tests:** new `test_a_trial_record_keeps_each_claims_review_verdict`, and the extended `test_live_quality_comes_from_reviewer_labels`. `tests/unit/test_live_eval.py tests/integration/test_evaluation.py tests/unit/test_smoke_scenarios.py` → 75 passed. `uvx ruff@0.14.0 check --select F,E9,B` on the changed files → clean.
- **Prepared, not adopted: engine `0.1.0.dev7`** on the branch `claude/dev7-masked-failure-wording` (`8a55aff`, pushed; not merged into `main`). Decision 0037: `extract_claims@5` words a failure a pipe hid as the project's condition, not as an account of one call, and claims no more than the runs showed. It was to merge only if the fifth gate failed on failed-approach recall; it merged after the owner's call (next checkpoint).
  - **Wheel:** `recalith-0.1.0.dev7-py3-none-any.whl` (618,918 bytes), SHA-256 `e40487f23490305cb20da7f5fff0c46a80b702620e89b2dd66b35dee426e7f34`. `tools/build_release.py --out <scratch>` → `problems: []`, `signing: unsigned`, the same digest. It ships `extract_v5.md`.
  - **Run script:** `probe-private\run-pilot8-gate6.ps1` (untracked; parses cleanly, ASCII only): a fresh pilot on `C:\Code\rl-pilot8` from that wheel, then the sixth gate into `C:\Code\rl-gate6`.
  - **Tests on the branch:** the digest, requests and adapter tests → 94 passed. The whole suite → 1 failed, 1,347 passed, 61 skipped (35.7 min). The failure was `test_concurrent_hooks_preserve_budget`, below; it is not the branch's.
- **The concurrent-hook race, attributed.** `test_delivery.py::test_concurrent_hooks_preserve_budget` named its reason at last: `store_snapshot_unavailable`. A hook that cannot establish its read-only snapshot at once skips with an empty packet, as SYSTEM_SPEC §5.1.1 specifies, and reserves nothing. Eight racing first readers hit it on this laptop: 7 of 15 reps failed on the `0.1.0.dev6` line and 3 of 10 on the branch, with no other assertion failing. The measurement's fault populations already report these empties (2–12 per 100 with four concurrent hooks). The test now accepts that reason, and every other invariant is unchanged: at least one emission, one lock, no lost reservation, no double emission, the allowance and the accounting. As with the pin-expiry race's busy refusal, the designed outcome is tolerated and the race is still exercised. 20 of 20 reps passed, and `tests/integration/test_delivery.py` → 22 passed, 1 skipped.
- **For the labels:** `C:\Code\rl-gate5\labels-to-review.md` lists the 26 items with their suggestions and reasons. `probe-private\label-gate.py` (untracked) writes a reviewer's `adjudication.json` from the suggestions and the reviewer's changes, and never overwrites one. It was tried only on a scratch copy.
- **Acceptance:** statuses unchanged. The gate is not passed until a reviewer's labels pass it.

### 2026-11-01 — The owner's call on the fifth gate: L1 #1 missed; engine 0.1.0.dev7 merged (decision 0037)

- **The owner's words:** "I agree with whatever you recommend. merge dev7". The recommendation was L1 #1 `missed`, so the fifth gate failed on failed-approach recall (1/2), as the projection showed.
- **No `adjudication.json` was written.** Adopting every suggestion without a review would make the labels the model's own, and ACCEPTANCE_TESTS §5 lets a model assist but never solely adjudicate. The fifth gate's report still reads `claims_unadjudicated:26`; the owner's call is recorded here. Labeling it later changes nothing, since the engine has moved on.
- **Merged:** `claude/dev7-masked-failure-wording` fast-forwarded the main line to `4fe1f5b`. Engine `0.1.0.dev7`: `extract_claims@5` (decision 0037).
- **Wheel:** rebuilt from the merged tree. The digest is unchanged, `e40487f23490305cb20da7f5fff0c46a80b702620e89b2dd66b35dee426e7f34`, the one `probe-private\run-pilot8-gate6.ps1` checks.
- **Tests:** the branch's whole suite and its targeted runs are in the fifth-gate checkpoint. The merge adds only the concurrent-hook test change, already run there 20 times.
- **Next:** the owner's run in handoff item 2.

### 2026-11-02 — The eighth pilot and the sixth live gate (the owner's run): complete, failed on two lost declarations; malformed operations (decision 0038, engine 0.1.0.dev8)

- **The run.** The owner ran `probe-private\run-pilot8-gate6.ps1` (untracked) from an ordinary window. It started at 22:42Z on 2026-11-02, on repository `3a0fc06`, and every step exited as expected. The log is `probe-private\pilot8-gate6-run.log` (untracked; checked for the key: none).
  - **The pilot, steps 1–8, on `C:\Code\rl-pilot8`:**
    - the `0.1.0.dev7` wheel was provisioned at the recorded digest;
    - the provider probe certified the route (18.3 s), and the runtime check passed with both isolation checks;
    - `integrate claude` installed 11 hooks and 450 deny rules;
    - the engine-mode delivery probe found every required path healthy, live on 2.1.310 (348.6 s);
    - `status` reported ready.
  - **The sixth gate**, with 6 slots, into `C:\Code\rl-gate6`: exit **8** after 2,569 s (42.8 min). The whole run took about 52 minutes.
- **Complete, apart from one demonstration:**
  - All 24 trials ran, with no error, no contaminated arm and no suspension. Every wait settled, and the host stayed at 2.1.310.
  - **Workload days:** all three ran at once (33, 40 and 30 calls), and none hit any pool. No call ended at its output cap.
  - **Demonstrations:** four of five. Forgetting and restore was not shown: it needs L3's live claim naming the $600 limit, and there was none.
  - **Cost:** foreground $1.73 over 48 sessions; background 193 model calls and 4,239,913 ledger tokens.
  - **Clean tree:** `tree_clean: false` again, because of `docs\host-compatibility.json`, committed with this checkpoint (scanned: no user names, paths, keys or model identifiers).
- **Outcomes, candidate/baseline:**
  - C2 failed/succeeded: session A implemented `delete INDEX` with a 1-based index, which the prompt allows, and the oracle's `delete 0` failed it (fixed, decision 0028 item 26).
  - Every other scenario succeeded in both arms. No superiority claim.
- **The gate failed with two reasons:**
  - `demonstrations_unmet:forgetting_and_restore`;
  - `claims_unadjudicated:21` (13 claims and 8 lessons).
- **The measures that need no labels are met:** incorrect confident guidance 0; conflict preservation 1/1 (R4); legitimate retries discouraged 0/2; irrelevant caution 0/3; routine human maintenance 0.
  - **Retrieval points:** 9/12. Unmet:
    - L2 and L3 at B's prompt, with no claim to deliver;
    - R3 at C's prompt, decision 0036's stated limit.
- **Decision 0037 worked.** L1's pipe-hidden failure became "Running `… -m unittest discover -s tests -v` from the project root, without PYTHONPATH=src, fails with "ModuleNotFoundError: No module named 'ledgerlite'"", and the review supported it. The trial record now carries each claim's review (decision 0028 item 25). The one candidate the review returned, in C2, shows its two objections.
- **Adjudication.** No `adjudication.json` was written. `adjudication.suggested.json` (every label null) and `labels-to-review.md` are in the results directory, and the suggestions are in the sanitized record.
  - **Suggested totals:** support 13/13, useful recall 5/7, failed-approach recall 2/2.
  - **No judgment call changes the result.** L2 #0 and L3 #0 are missed, so useful recall is at most 5/7, under 0.85. The report code, run on a scratch copy with the suggestions copied into labels, fails on `quality_targets_unmet:useful_recall` and the forgetting demonstration. Labeling this gate is optional.
- **Why the two declarations were lost** (decision 0038). Code's strict checks refused both; the curator did not judge them away.
  - **L3:** the extraction after session A proposed one claim, and admission refused it with `declaration_requires_user_evidence`: none of what it cited was the user's own words. What it cited went with the store (decision 0028 item 27 keeps that from now on).
  - **L2:** the record showed an extraction with no operations and no stated reason, which the contract does not allow. The parser stores a reply whose every operation failed strict validation that way, under `malformed`, which the harness did not read. The decision was most likely proposed and refused by validation.
- **The larger finding: most `update_task` replies fail validation.**
  - 27 of 43, 24 of 45 and 30 of 45 `update_task` calls in the fourth, fifth and sixth gates were stored that way. The "no operation" count logged since the fourth gate is mostly malformed replies, not deliberate no-ops.
  - In the four kept R4 rerun stores (`C:\Code\rl-p4` to `rl-p7`), every such proposal holds `malformed_operation` entries: 6 of 8 `update_task` calls. One extraction also had a malformed operation beside two valid ones.
  - A malformed operation kept no reason, so the cause is unknown. Plausible replies fail for different reasons: a missing `reason`, a string appended to a list field, evidence on a patch, or a title over 256 characters.
- **Also seen:** L1's working agent ran the tests through the installation's own runtime interpreter (`.recalith/runtime/0.1.0.dev7/venv/Scripts/python.exe`), and its claims name that path. It worked, but the project's memory runtime is visible to the agent as a Python.
- **Found while checking the tests: dates in the harness that had expired.** The scripted trial clock started at a fixed 2026-11-02T09:00Z. Once that time passed, scripted workers never reached their ingest jobs, which are stamped with real time. `test_the_curator_calls_record_what_admission_decided` and `test_replay_cannot_see_future_evidence` failed at HEAD, without any change from this session, after passing in the `0.1.0.dev7` suite. The live workload days (fixed at 2026-11-03 to 11-05) and two demonstrations would have stalled the same way in the next live run. Every virtual clock now starts relative to today (decision 0028 item 28).
- **Built after the gate:**
  - **Engine `0.1.0.dev8`** (decision 0038): `MalformedOperation.detail` says what failed, with field paths, error types and a validator's own message, never the model's text. DATA_CONTRACTS §7.1 and the `ModelResponse` schema are updated.
  - **Harness** (decision 0028 items 26–28):
    - C2 accepts either index base;
    - a refused claim operation keeps its proposed kind, basis, wording and citations' kinds;
    - curator calls list malformed operations with their detail;
    - the virtual clocks start ahead of real time.
- **The sanitized record** is [`docs/evaluations/preview-live-2026-11-02/`](evaluations/preview-live-2026-11-02/report.md): 34 files, with the results directory as `<run>` and temporary paths as `<temp>`. A scan by count found 0 user names, drive paths, keys, email addresses or model identifiers.
- **Wheel:** `uv build --wheel -o dist` → `recalith-0.1.0.dev8-py3-none-any.whl` (619,573 bytes), SHA-256 `35b3e87f5aeda1d9ba912878dde00056e33aee7e2ab43ae77fb2ce27e4154faf`. `tools/build_release.py --out <scratch>` → `problems: []`, `signing: unsigned`, the same digest.
- **Prepared, not run:** `probe-private\run-pilot9-gate7.ps1` (untracked; parses cleanly, ASCII only). It runs a fresh pilot's steps 1–8 on `C:\Code\rl-pilot9` from the `0.1.0.dev8` wheel, then the seventh gate with 6 slots into `C:\Code\rl-gate7`.
- **Tests** (native Windows, Python 3.13):
  - **New:**
    - `test_a_malformed_operation_says_what_failed_without_quoting_the_model` (provider contract);
    - `test_a_refused_claim_operation_keeps_what_it_proposed_and_cited` (live evaluation);
    - `test_c2_accepts_a_one_based_delete_and_still_fails_one_that_removes_nothing` (smoke oracles).
  - **Changed:** `test_replay_cannot_see_future_evidence` takes its later session from the trial's start, not a fixed date. The deny-spelling test is re-pinned to `0.1.0.dev8`.
  - **Runs:**
    - `tests/unit/test_live_eval.py tests/integration/test_evaluation.py tests/unit/test_smoke_scenarios.py tests/unit/test_eval_harness.py` → 89 passed. That includes the two evaluation tests that had failed at HEAD on the expired date.
    - **The whole suite** (`tests`, `--basetemp C:/Code/t3`) → 1,351 passed, 61 skipped (41.1 min), with no failure.
  - `uvx ruff@0.14.0 check --select F,E9,B` on the changed files → clean. `tools/generate_schemas.py --check` → exit 0: the `ModelResponse` schema was regenerated, and the generator's CRLF output was normalized to LF. `tools/release_checklist.py` → no problems, verdict `blocked`.
- **Acceptance:** statuses unchanged. A failed gate and an unrun engine change are not passes.

### 2026-11-03 — The ninth pilot and the seventh live gate (the owner's run): complete, failed on the forgetting demonstration; patch shapes (decision 0039, engine 0.1.0.dev9)

- **The run.** The owner ran `probe-private\run-pilot9-gate7.ps1` (untracked) from an ordinary window. It started at 14:16Z on 2026-11-03, on repository `e5b649f`, and every step exited as expected. The log is `probe-private\pilot9-gate7-run.log` (untracked; checked for the key: none).
  - **The pilot, steps 1–8, on `C:\Code\rl-pilot9`:**
    - the `0.1.0.dev8` wheel was provisioned at the recorded digest;
    - the provider probe certified the route (18.0 s), and the runtime check passed;
    - `integrate claude` installed 11 hooks and 450 deny rules;
    - the engine-mode delivery probe found every required path healthy, live on 2.1.310 (348.2 s);
    - `status` reported ready.
  - **The seventh gate**, with 6 slots, into `C:\Code\rl-gate7`: exit **8** after 2,855 s (47.6 min). The whole run took about 54 minutes.
- **Complete:**
  - All 24 trials ran, with no error, no contaminated arm and no suspension. Every wait settled, and the host stayed at 2.1.310.
  - **Workload days:** all three ran at once (33, 40 and 29 calls), and none hit any pool. No call ended at its output cap.
  - **Demonstrations:** four of five. Forgetting and restore ran end to end and failed (below).
  - **Cost:** foreground $1.74 over 48 sessions; background 191 model calls and 4,228,235 ledger tokens.
  - **Clean tree:** `tree_clean: false` again, because of `docs\host-compatibility.json`, committed with this checkpoint (scanned: no user names, paths, keys or model identifiers).
- **Outcomes, candidate/baseline:**
  - L3 failed/succeeded. The candidate's `groceries.csv` has item names with unquoted commas, such as `Fresh vegetables (onions, carrots, …),85.00`, so it is not the requested two-column CSV. That is the fourth gate's defect, judged a failed check (decision 0028 item 24). Its plan used the $600 limit.
  - Every other scenario succeeded in both arms. No superiority claim.
- **The gate failed with two reasons:**
  - `demonstrations_unmet:forgetting_and_restore`;
  - `claims_unadjudicated:22` (14 claims and 8 lessons).
- **The measures that need no labels are met:** incorrect confident guidance 0; conflict preservation 1/1 (R4); legitimate retries discouraged 0/2; irrelevant caution 0/3; routine human maintenance 0.
  - **Retrieval points:** 10/12. Unmet:
    - L2 at B's prompt, with no claim to deliver;
    - R3 at C's prompt, decision 0036's stated limit.
- **L3's declaration was admitted**, so the forgetting demonstration ran. The claim `claim_01dcde37` is user_declared, was reviewed supported and was delivered at B's prompt.
  - **What worked:**
    - the backup was verified, with an external copy;
    - the forget completed and purged 17 records, and afterwards no store row held the claim;
    - after the suppression-aware restore, the store still held none of it, and the session after the restore was not delivered it.
  - **What failed:** session D, the fresh live session after the forget, was delivered some text containing "600".
  - **Why the cause is unknown:** the demonstration kept only that one boolean, and the workspaces were removed.
  - **Two possible causes:**
    - Session A wrote the limit into `budget.csv` at the user's request. Forgetting never touches project files, so D may have read it again and had its own observation delivered back.
    - The forgotten claim may have resurfaced.
  - The record cannot tell these apart, so the failure stands.
  - The check now records every item that holds the value. Items resting on anything that existed before the forget fail. Items resting only on the fresh session's own new records are reported as relearned (decision 0028 item 29).
- **Adjudication.** No `adjudication.json` was written. `adjudication.suggested.json` (every label null) and `labels-to-review.md` are in the results directory, and the suggestions are in the sanitized record.
  - **Suggested totals:** support 14/14, useful recall 6/7 (0.857 against 0.85), failed-approach recall 2/2. As drafted, every labeled measure is met.
  - **Judgment calls:**
    - **L1 #0 recalled.** The passing command's claim was reviewed supported and delivered at B. After B added a test, its revision claimed the 3-test count, and review left that revision a weak candidate. Missed gives 5/7.
    - **R1 #0 recalled.** The failure lesson was supported and delivered at C without a caution. C's overlay then made its revision a candidate, which is the expected revision. Missed gives 5/7 and 1/2.
    - **R2 #0 evidence_absent,** as before.
  - **No call changes the result:** the forgetting demonstration fails the gate.
  - L2 #0 is missed: its extraction proposed the decision, with evidence inside the payload (below).
- **What failed validation**, first read from decision 0038's `detail`:
  - **`update_task`.** Of 45 calls, 34 had a malformed operation, and 31 had nothing else. Every malformed operation failed `append adds one item to a list field`: bare strings appended where each item is a supported text. Five more failed to apply, and four set `completed` without evidence.
  - **`build_episode`.** Four of 45 calls had a malformed operation, and six failed to apply: bare strings where a field takes a supported text.
  - **`extract_claims`.** L2's two claims after session A carried `evidence` inside `payload`. An L4 operation carried a `claim_ref` key its kind does not have.
  - **`revalidate`.** Two of four calls were refused: one operation carried a `supersedes` key, and one asked for a file excerpt without a path.
  - Neither narrative prompt described a patch value. The detail also dropped the `payload.` prefix from a payload's own errors.
- **Built after the gate:**
  - **Engine `0.1.0.dev9`** (decision 0039):
    - `update_task@2` and `build_episode@2` give each patch value its field's shape;
    - `extract_claims@6` and `revalidate@3` keep an operation's evidence and fields out of its payload;
    - a payload's failures are named under `payload` (DATA_CONTRACTS §7.1).
  - **Harness** (decision 0028 item 29): the forgetting check splits resurfaced from relearned items and records each, with each fresh session's actions.
- **The sanitized record** is [`docs/evaluations/preview-live-2026-11-03/`](evaluations/preview-live-2026-11-03/report.md): 34 files, with the results directory as `<run>` and temporary paths as `<temp>`. A scan by count found 0 user names, drive paths, keys, email addresses or model identifiers.
- **Wheel:** `uv build --wheel -o dist` → `recalith-0.1.0.dev9-py3-none-any.whl` (624,005 bytes), SHA-256 `37ba76f1fe17ebc0e2f5b503165e5f83ce7f4d4883d80b760e09cb9d4a34c2ca`. `tools/build_release.py --out <scratch>` → `problems: []`, `signing: unsigned`, the same digest.
- **Prepared, not run:** `probe-private\run-pilot10-gate8.ps1` (untracked; parses cleanly, ASCII only). It runs a fresh pilot's steps 1–8 on `C:\Code\rl-pilot10` from the `0.1.0.dev9` wheel, then the eighth gate with 6 slots into `C:\Code\rl-gate8`.
- **Tests** (native Windows, Python 3.13):
  - **New:**
    - `test_task_and_episode_narratives_apply_in_the_shapes_their_prompts_name`, in two variants (requests): the real lifecycle session through the worker, with replies in the @2 shapes, which apply, and with bare strings, which are refused with their `payload.` paths;
    - `test_forgetting_counts_only_content_resting_on_what_existed_before_the_forget` (live evaluation).
  - **Changed:**
    - the malformed-detail test expects `payload.` paths and adds evidence inside a payload;
    - the prompt golden-digest tests pin `extract_claims@6` and `revalidate@3`, each its predecessor plus exactly the new text;
    - the scheduling test expects the new pinned versions;
    - the deny-spelling test is re-pinned to `0.1.0.dev9`.
  - **Runs:**
    - the affected suites (`test_live_eval`, `test_provider_contract`, `test_contracts`, `test_claim_admission`, `test_consolidation`, `test_requests`, `test_episodes`) → 189 passed;
    - `test_evaluation` with `test_claude_adapter` → 85 passed;
    - the scripted forgetting demonstration, run once on the new split → demonstrated, with nothing resurfaced or relearned;
    - **the whole suite** (`tests`, `--basetemp C:/Code/t`) → 1,354 passed, 61 skipped (36.0 min), with no failure.
  - `uvx ruff@0.14.0 check --select F,E9,B` on the changed files → clean. `tools/generate_schemas.py --check` → exit 0. `tools/release_checklist.py` → no problems, verdict `blocked`.
- **Acceptance:** statuses unchanged. A failed gate and an unrun engine change are not passes.

### 2026-11-03 — The tenth pilot and the eighth live gate (the owner's run): all five demonstrations shown, failed on R3's oracle (decision 0028 item 30)

- **The run.** The owner ran `probe-private\run-pilot10-gate8.ps1` (untracked) from an ordinary window. It started at 21:37Z on 2026-11-03, on repository `614944c`, and every step exited as expected. The log is `probe-private\pilot10-gate8-run.log` (untracked; checked for the key: none).
  - **The pilot, steps 1–8, on `C:\Code\rl-pilot10`:**
    - the `0.1.0.dev9` wheel was provisioned at the recorded digest;
    - the provider probe certified the route (18.1 s), and the runtime check passed;
    - `integrate claude` installed the hooks and deny rules;
    - the engine-mode delivery probe found every required path healthy, live on 2.1.310 (399.4 s);
    - `status` reported ready.
  - **The eighth gate**, with 6 slots, into `C:\Code\rl-gate8`: exit **8** after 2,821 s (47.0 min). The whole run took about 54 minutes.
- **Complete:**
  - All 24 trials ran, with no error, no contaminated arm and no suspension. Every wait settled, and the host stayed at 2.1.310.
  - **Workload days:** all three ran at once (34, 39 and 29 calls), and none hit any pool. No call ended at its output cap.
  - **Demonstrations: all five shown.** This is the first time. Forgetting and restore:
    - L3's declaration was admitted;
    - the forget purged 15 records, with a verified backup;
    - neither the session after the forget nor the one after the restore was delivered any item holding "600" (resurfaced 0, relearned 0; decision 0028 item 29).
  - **Cost:** foreground $1.74 over 48 sessions; background 199 model calls and 4,479,687 ledger tokens.
  - **Clean tree:** `tree_clean: false` again, because of `docs\host-compatibility.json`, committed with this checkpoint (scanned: no user names, paths, keys or model identifiers).
- **Decision 0039 worked.**
  - **`update_task`:** of 45 calls, one had a malformed operation, a `close` with an invalid item id, and 48 operations were admitted. In the seventh gate, 34 had a malformed operation.
  - **Episodes:** all 45 `build_episode` revisions were admitted.
  - **Extraction:** no `extract_claims` reply had a malformed operation. L2's ISO-8601 decision was admitted (`claim_c4af8938`).
- **Outcomes, candidate/baseline:**
  - R3 failed/succeeded. The candidate used the corrected $700 and said so ("My project memory still lists a $600 preference. I treated your correction as current and used $700"). Its total was $689 against $700.
  - The oracle failed it anyway, on its plan's line "$700 per month (updated from $600)". `no_stale_600_limit` accepted "up from" and "changed from", but not "updated from". That is a false negative, fixed for the next run (decision 0028 item 30).
  - Every other scenario succeeded in both arms. No superiority claim.
- **The gate failed with two reasons:**
  - `quality_targets_unmet:incorrect_confident_guidance`. That is R3: the $600 preference was delivered at C's prompt (decision 0036's stated limit: the correction is in C's own prompt, curated after C), and the task counted as failed.
  - `claims_unadjudicated:22` (14 claims and 8 lessons).
- **The other measures that need no labels are met:** conflict preservation 1/1 (R4); legitimate retries discouraged 0/2; irrelevant caution 0/3; routine human maintenance 0.
  - **Retrieval points:** 10/12. Unmet:
    - L1 at B's session start, which delivered no item. B's prompt delivered the procedure.
    - R3 at C's prompt, decision 0036's stated limit.
- **Adjudication.** No `adjudication.json` was written. `adjudication.suggested.json` (every label null) and `labels-to-review.md` are in the results directory, and the suggestions are in the sanitized record.
  - **Suggested totals:** support 14/14, useful recall 7/7, failed-approach recall 2/2.
  - **Judgment calls:**
    - **L1 #0 recalled.** The procedure was supported and delivered at B; after B, its revision was left a weak candidate. Missed gives 6/7, still met.
    - **R2 #0 evidence_absent,** as before. Missed gives failed-approach recall 2/3.
  - **Projection.** The report code was run on a scratch copy, with the suggestions copied into labels as a projection, not a review. It fails only on `incorrect_confident_guidance`.
- **The verdict stands: failed.** As with decision 0028 items 23, 24 and 26, an oracle correction applies from the next run, and the gate's record keeps its score. The engine is unchanged, so the next run uses the same `0.1.0.dev9` wheel.
- **Still exposed:** R3's prompt point is structurally unmet, so any failure of R3's candidate task fails the gate through `incorrect_confident_guidance` (decision 0036, Limits).
- **Built after the gate:** the R3 oracle's `… from` exception also takes `updated`, `revised`, `adjusted`, `moved` and `bumped` (decision 0028 item 30).
- **The sanitized record** is [`docs/evaluations/preview-live-2026-11-03-gate8/`](evaluations/preview-live-2026-11-03-gate8/report.md): 34 files, with the results directory as `<run>` and temporary paths as `<temp>`. A scan by count found 0 user names, drive paths, keys, email addresses or model identifiers.
- **Prepared, not run:** `probe-private\run-pilot11-gate9.ps1` (untracked; parses cleanly, ASCII only). It runs a fresh pilot's steps 1–8 on `C:\Code\rl-pilot11` from the same `0.1.0.dev9` wheel (SHA-256 `37ba76f1…`), then the ninth gate with 6 slots into `C:\Code\rl-gate9`.
- **Tests** (native Windows, Python 3.13):
  - **New:** two `R3_PLANS` cases of `test_r3_accepts_the_old_limit_named_as_replaced`: the eighth gate's line, and "revised from $600 to $700".
  - **Runs:**
    - `tests/unit/test_smoke_scenarios.py tests/unit/test_eval_harness.py` → 56 passed;
    - `tests/integration/test_evaluation.py tests/unit/test_live_eval.py` → 36 passed.
  - `src/` is unchanged since the `0.1.0.dev9` suite (1,354 passed, 61 skipped).
- **Acceptance:** statuses unchanged. A failed gate is not a pass.

### 2026-11-04 — The eleventh pilot and the ninth live gate (the owner's run): every unlabeled measure and all five demonstrations met; the result waits on the owner's labels

- **The run.** The owner ran `probe-private\run-pilot11-gate9.ps1` (untracked) from an ordinary window. It started at 13:21Z on 2026-11-04, on repository `b17c75c`, and every step exited as expected. The log is `probe-private\pilot11-gate9-run.log` (untracked; checked for the key: none).
  - **The pilot, steps 1–8, on `C:\Code\rl-pilot11`:**
    - the same `0.1.0.dev9` wheel was provisioned at the recorded digest;
    - the provider probe certified the route (17.5 s), and the runtime check passed;
    - the engine-mode delivery probe found every required path healthy, live on 2.1.310 (339.6 s);
    - `status` reported ready.
  - **The ninth gate**, with 6 slots, into `C:\Code\rl-gate9`: exit **8** after 2,569 s (42.8 min). The whole run took about 49 minutes.
- **Complete:**
  - All 24 trials ran, with no error, no contaminated arm and no suspension, and the host stayed at 2.1.310.
  - **Workload days:** all three ran at once (35, 42 and 30 calls), and none hit any pool. No call ended at its output cap.
  - **Demonstrations: all five shown.** In forgetting and restore, the forget purged 14 records, and no item holding "600" was delivered after the forget or after the restore.
  - **Cost:** foreground $1.69 over 48 sessions; background 200 model calls and 4,336,418 ledger tokens.
  - **Clean tree:** `tree_clean: false` again, because of `docs\host-compatibility.json`, committed with this checkpoint (scanned).
  - **Malformed:** two operations in 190 calls: a `close` with an invalid item id, and one assessment's evidence id.
- **Outcomes, candidate/baseline:** every candidate succeeded. R2's baseline failed its task; its retry also failed. No superiority claim.
- **The gate's one reason is `claims_unadjudicated:32`** (24 claims and 8 lessons).
- **Every measure that needs no labels is met:** incorrect confident guidance 0; conflict preservation 1/1 (R4); legitimate retries discouraged 0/2; irrelevant caution 0/3; routine human maintenance 0.
  - R3's candidate wrote "updated from the earlier $600", which the oracle already accepted.
  - **Retrieval points:** 10/12. Unmet:
    - L1 at B's session start, with no item; B's prompt delivered the procedure.
    - R3 at C's prompt, decision 0036's stated limit.
- **Adjudication: the result is the owner's to decide.** No `adjudication.json` exists. `adjudication.suggested.json` (every label null) and `labels-to-review.md`, with the deciding calls first, are in the results directory; the suggestions are in the sanitized record.
  - **Suggested totals:** support 24/24, useful recall 6/7 (0.857 against 0.85), failed-approach recall 2/2.
  - **Projection.** The report code was run on a scratch copy, with the suggestions copied into labels as a projection, not a review. It concludes `passed_smoke`.
  - **The margins are thin.** Any one of these fails the gate:
    - L1 #1 missed, not evidence_absent. No session ran the failing form, because session A used `PYTHONPATH=src` from reading the layout.
    - R1 #0 missed. As in the seventh gate, the lesson was active and delivered at C, then left a weak candidate after C's overlay.
    - Two claims unsupported. The judgment calls are C2's dated exit-code claim, which omits that NOTES_HOME was set, and R3's still-active $600 claim.
    - Any other lesson missed.
  - **R3 #0 is missed.** The extraction after C proposed the $700 preference and the superseding of the $600 one. The review returned revise, objecting that "kept under $700" adds a ceiling framing, so the $600 claim stayed active.
  - **R2 #0 is recalled this time:** session A observed `ModuleNotFoundError` with `src` off the path (`claim_f9c623ef`).
- **Limits a pass would carry** (ACCEPTANCE_TESTS §5, §6.1):
  - one trial per arm;
  - one reviewer, not two independent ones;
  - scenarios and gold written by the repository's coding agent, not held out;
  - point estimates with wide intervals (useful recall 6/7, Wilson 95 % 0.49–0.97).
  - A `passed_smoke` is the preview's early comparative gate, not a superiority claim and not full-release quality.
- **Seen, not changed:** a revision pending review unseats a supported head. In L1 (seventh and eighth gates) and R1 (seventh and ninth), the review's `revise` on a revision left a once-active lesson a weak candidate.
- **The sanitized record** is [`docs/evaluations/preview-live-2026-11-04/`](evaluations/preview-live-2026-11-04/report.md): 34 files. A scan by count found 0 user names, drive paths, keys, email addresses or model identifiers.
- **Tests:** none changed. `probe-private\label-gate.py` was dry-run on a scratch copy of this gate's files: it wrote 24 claims and 8 lessons, and applied a `--set`. Nothing was written in `C:\Code\rl-gate9`.
- **Acceptance:** statuses unchanged until the owner's labels are recorded and the report is run.

### 2026-11-04 — The ninth gate's labels: failed on supported precision (22/24); support is judged at admission (decision 0028 item 31)

- **How the labels were made.** The owner judged that they could not reliably review 32 labels and asked for an outside model review.
  - **The packet:** `C:\Code\rl-gate9\review-packet.md`, built mechanically from the sanitized record and the fixture sources. It gives every scenario's gold, prompts, overlays, actions, deliveries, replies, oracle checks and claims. It leaves out this repository's suggestions, their reasons and the term-match heuristic, so the outside review was not anchored on them.
  - **The prompt:** `review-prompt.md`.
  - **The answer** is kept as `outside-review.json`, without the model's name.
- **The comparison:**
  - Lessons: all 8 agree.
  - Claims: 19 of 24 agree. The outside review marked five unsupported:
    - Two overstate a detail, and the outside review is right on both; this session's suggestions were too lenient:
      - C2's `claim_a72bb89c` says the checks need NOTES_HOME "set to a directory", but `check.py` only reads and prints it;
      - L2's `claim_7928f95d` says `store.add` writes dates "in UTC", which is only the default, and "only for notes written through store.add".
    - Three were true when admitted and made stale later in the trial: R1's `check.py` fact, R4's storage fact and R3's $600 preference.
- **The owner's rule** (decision 0028 item 31). A claim's support is judged against the evidence when it was admitted. Going stale later is scored elsewhere: conflict preservation, recall, the retrieval points and incorrect confident guidance. R1 and R4 produce such a claim on every run by design. The adjudication template's instructions now state the rule.
- **Recorded by the owner** with `probe-private\label-gate.py`. The reviewer route is "the owner: two model reviews (the coding agent, an outside model), adopted where they agreed; three out-of-date claims by the owner's rule (decision 0028 item 31)", not independent of SYSTEM_SPEC §7.
- **The report:** exit 8, `quality_targets_unmet:supported_precision`.

  | Measure | Result | Target |
  |---|---|---|
  | supported precision | 22/24 (0.917) | ≥ 0.95 — not met |
  | useful recall | 6/7 (0.857) | ≥ 0.85 — met |
  | failed-approach recall | 2/2 | ≥ 0.90 — met |

  Every other measure and all five demonstrations were met. **The ninth gate failed.** The rule decided nothing here, because the two overstated claims fail support either way.
- **What failed:**
  - **Extraction added detail its evidence did not show:** "to a directory", "in UTC", "only for …".
  - **The review admitted that detail.** In R3, it held back the user's $700 correction because the extraction worded it as "kept under $700". That carried over the old claim's framing instead of the user's words ("the grocery budget is now $700 per month, not $600").
  - Both are claims saying more than their evidence. The next engine change targets that.
- **The sanitized record** in [`docs/evaluations/preview-live-2026-11-04/`](evaluations/preview-live-2026-11-04/report.md) now holds the recorded `adjudication.json`, the outside review and the regenerated report: 36 files, scanned clean.
- **Tests:** the adjudication tests pass with the new template instructions (5 selected).

### 2026-11-04 — Engine 0.1.0.dev10: a claim says no more than its evidence, and the review tests every clause (decision 0040)

- **Why.** The ninth gate failed only on supported precision (22/24).
  - Both unsupported claims added a detail their evidence did not show: "to a directory", "in UTC" and "only …".
  - R3's correction was held back because its extraction carried over the replaced claim's "kept under" framing, not the user's words.
- **Built:**
  - `extract_claims@7` (`extract_v7.md`) is `@6` plus two sentences:
    - say no more than the cited evidence shows (no added requirement, type, unit, time zone, default, consequence or limit, and no default presented as what always happens);
    - word a user's declaration or correction from the user's own words.
  - `review_claims@2` (`review_v2.md`) is `@1` plus one sentence. It tests every clause, including qualifiers, types, units, time zones, defaults and "so"/"because" consequences; a clause the evidence does not show is an objection.
  - New jobs pin both; older pins are still served.
- **Kept for the next labels** (untracked):
  - `probe-private\review-packet.py` builds an outside-review packet from a sanitized record without this session's suggestions;
  - `probe-private\review-prompt.md` is the prompt to send with it.
- **Wheel:** `uv build --wheel -o dist` → `recalith-0.1.0.dev10-py3-none-any.whl` (627,683 bytes), SHA-256 `14fa2075be3471994e81513ac7ab3839c91beb2b9f95e3e8e03bbd5d00776d1d`. `tools/build_release.py --out <scratch>` → `problems: []`, `signing: unsigned`, the same digest.
- **Prepared, not run:** `probe-private\run-pilot12-gate10.ps1` (untracked; parses cleanly, ASCII only). It runs a fresh pilot's steps 1–8 on `C:\Code\rl-pilot12` from the `0.1.0.dev10` wheel, then the tenth gate with 6 slots into `C:\Code\rl-gate10`.
- **Tests** (native Windows, Python 3.13):
  - **Changed:**
    - the golden-digest test pins `extract_claims@7` and `review_claims@2`, each its predecessor plus exactly the new text, and keeps the older digests;
    - the scheduling expectations name the new versions;
    - the deny-spelling test is re-pinned to `0.1.0.dev10`.
  - **Runs:**
    - the admission, consolidation, requests, adapter, provider-contract and contract suites → 230 passed;
    - **the whole suite** (`tests`, `--basetemp C:/Code/t`) → 1,356 passed, 61 skipped (35.8 min), with no failure.
  - `uvx ruff@0.14.0 check --select F,E9,B` on the changed files → clean. `tools/generate_schemas.py --check` → exit 0. `tools/release_checklist.py` → no problems, verdict `blocked`.
- **Acceptance:** statuses unchanged. An unrun engine change is not a pass.

### 2026-11-04 — The twelfth pilot and the tenth live gate (the owner's run): every unlabeled measure and all five demonstrations met; the result waits on reviewer labels

- **The run.** The owner ran `probe-private\run-pilot12-gate10.ps1` (untracked) from an ordinary window. It started at 16:26Z on 2026-11-04, on repository `d8a4bbc`, and every step exited as expected. The log is `probe-private\pilot12-gate10-run.log` (untracked; checked for the key: none).
  - **The pilot, steps 1–8, on `C:\Code\rl-pilot12`:**
    - the `0.1.0.dev10` wheel was provisioned at the recorded digest;
    - the provider probe certified the route (17.3 s), and the runtime check passed;
    - the engine-mode delivery probe found every required path healthy, live on 2.1.310 (337.3 s);
    - `status` reported ready.
  - **The tenth gate**, with 6 slots, into `C:\Code\rl-gate10`: exit **8** after 2,902 s (48.4 min). The whole run took about 55 minutes.
- **Complete:**
  - All 24 trials ran, with no error, no contaminated arm and no suspension, and the host stayed at 2.1.310.
  - **Workload days:** all three ran at once (33, 40 and 28 calls), and none hit any pool. No call ended at its output cap.
  - **Demonstrations: all five shown.** In forgetting and restore, the forget purged 14 records, and nothing holding "600" resurfaced or was relearned after the forget or after the restore.
  - **Cost:** foreground $1.75 over 48 sessions; background 191 model calls and 4,289,417 ledger tokens.
  - **Clean tree:** `tree_clean: false` again, because of `docs\host-compatibility.json`, committed with this checkpoint (scanned).
  - **Malformed:** one operation in 191 calls, a workload `update_task` without its `reason`.
- **Outcomes, candidate/baseline:** every candidate succeeded, R3's included. R3's baseline failed its task. No superiority claim.
- **The gate's one reason is `claims_unadjudicated:30`** (22 claims and 8 lessons).
- **Every measure that needs no labels is met:** incorrect confident guidance 0 (of 12); conflict preservation 1/1 (R4); legitimate retries discouraged 0/2; irrelevant caution 0/3; routine human maintenance 0.
  - **Retrieval points:** 10/12, the same two as the ninth gate:
    - L1 at B's session start, with no item; B's prompt delivered both test-command facts.
    - R3 at C's prompt, decision 0036's stated limit: the correction arrives in that prompt.
- **What decision 0040 changed, as observed:**
  - **R3:** the extraction after C worded the correction from the user's words ("The grocery budget is now $700 per month."). The review supported it, and it superseded the $600 decision.
  - **Exactness:** the drafted labels find no overstated claim among the 22. A default is stated as a default: L2 `claim_da7245ea` says "with `moment` defaulting to `datetime.now(timezone.utc)`".
  - **The stricter review** returned `revise` four times and `reject` once in the smoke trials. Each objection names a clause the evidence does not show, such as "a temporary directory requirement is not shown" and "the so-clause". None of those candidates holds a gold lesson.
- **Adjudication: the result waits on reviewer labels.** No `adjudication.json` exists.
  - `adjudication.suggested.json` (every label null) and `labels-to-review.md`, with the deciding calls first, are in the results directory; the suggestions are in the sanitized record.
  - An outside-review packet without them is `C:\Code\rl-gate10\review-packet.md` (untracked), with `review-prompt.md`.
  - **Suggested totals:** support 22/22, useful recall 7/7, failed-approach recall 2/2.
  - **Projection.** The report code was run on a scratch copy, with the suggestions copied into labels as a projection, not a review. It concludes `passed_smoke`.
  - **What would fail it:**
    - R2 #0 missed, not evidence_absent: failed-approach recall 2/3. As in the fourth to eighth gates, session A fixed the condition itself, so `ModuleNotFoundError` was never observed.
    - L1 #1 or R1 #0 missed: failed-approach recall 1/2.
    - Any two lessons missed. L1 #0 is a judgment call: it is held as one recorded run, not as a procedure.
    - Any two claims unsupported. The judgment calls are R2 `claim_a671e336`, whose "with tests/__init__.py present" leaves out that the file puts `src/` on `sys.path`, and L4 `claim_893d18a9`, whose Python 3.13 is read from the interpreter's folder name.
  - **L1 #1 is recalled this time:** session A ran plain discovery without `PYTHONPATH=src` and saw `FAILED (errors=1)` (`claim_f08e22cb`).
- **Seen, not changed:**
  - **R1's failure lesson stayed active and current after C.** C's plain run passed on the changed `tools/check.py`. The last revalidation kept the lesson unchanged, citing its retry condition "under NOTES_HOME set". The demonstration is met, because the retry was not discouraged; by the owner's rule, support is judged at admission.
  - **C2's session B overwrote `fieldnotes/cli.py`** without reading it, because its truncated listing missed the file, and rebuilt it. The oracle passed, and B told the user. This is the host agent's behavior, not the memory's.
  - L4 `claim_893d18a9` carries the machine's interpreter path from the tool output; the sanitized record replaces it.
- **Limits a pass would carry** (ACCEPTANCE_TESTS §5, §6.1):
  - one trial per arm;
  - labels drafted with model help, with the route recorded;
  - scenarios and gold written by the repository's coding agent, not held out;
  - point estimates with wide intervals (useful recall 7/7, Wilson 95 % 0.65–1.0).
  - A `passed_smoke` is the preview's early comparative gate, not a superiority claim and not full-release quality.
- **The sanitized record** is [`docs/evaluations/preview-live-2026-11-04-gate10/`](evaluations/preview-live-2026-11-04-gate10/report.md): 34 files. A scan by count found 0 user names, drive paths, keys, email addresses or model identifiers.
- **Tests:** none changed.
- **Acceptance:** statuses unchanged until reviewer labels are recorded and the report is run.

### 2026-11-04 — The tenth gate's labels: passed, the first live pass of the smoke quality gate

- **How the labels were made,** as for the ninth gate. The packet `C:\Code\rl-gate10\review-packet.md` leaves out this repository's suggestions. It went to an outside model with `review-prompt.md`, and the answer is kept as `outside-review.json`, without the model's name.
- **The comparison:** 28 of 30 items agree, including two of the four drafted judgment calls (L1 #0 recalled; R2 `claim_a671e336` supported).
- **The owner decided the two differences:**
  - **R2 #0: `evidence_absent`** (the outside review: missed).
    - Session A's plain discovery stopped on "Start directory is not importable", which unittest raises before it imports any test module.
    - A then wrote a `tests/__init__.py` that puts `src/` on `sys.path`, and the command passed. `ModuleNotFoundError` was never observed; A's reply states the import cause from reading the layout.
    - This matches the ninth gate's L1 #1, which the owner recorded `evidence_absent` with both reviews agreeing: a failure the agent explained from reading but never ran.
    - Had it been admitted, the lesson would have been false by the end of A, because A's own fix made plain discovery pass.
  - **L4 `claim_893d18a9`: `unsupported`** (this session's draft: supported). The retained record shows B saying pytest isn't installed. The interpreter path, the version and the error text came from tool output that was not kept. This is the outside review's stricter call, and it does not change the result.
- **Recorded by the owner** with `probe-private\label-gate.py`. The reviewer route is "the owner: two model reviews (the coding agent, an outside model), adopted where they agreed; R2 #0 and claim_893d18a9 decided by the owner", not independent of SYSTEM_SPEC §7. The same commands on a scratch copy first gave the same result.
- **The report:** exit 0, `passed_smoke`, no reasons.

  | Measure | Result | Target |
  |---|---|---|
  | supported precision | 21/22 (0.955; Wilson 95 % 0.78–0.99) | ≥ 0.95 — met |
  | useful recall | 7/7 (Wilson 95 % 0.65–1.0) | ≥ 0.85 — met |
  | failed-approach recall | 2/2 (Wilson 95 % 0.34–1.0) | ≥ 0.90 — met |

  Every other measure is met (incorrect confident guidance 0, conflict preservation 1/1, legitimate retries discouraged 0/2, irrelevant caution 0/3, routine human maintenance 0), and all five demonstrations were shown. **The tenth gate passed**, the first of ten live runs to pass.
- **What the pass shows:** the preview's smoke gate (ACCEPTANCE_TESTS §6.1) on its frozen 12 scenarios, one fresh trial per arm, on native Windows with Claude Code 2.1.310 and engine `0.1.0.dev10`.
- **What it does not show** (ACCEPTANCE_TESTS §5, §6.1):
  - **No superiority.** The paired differences are inconclusive: task success +0.08, 95 % interval 0 to 0.25 (R3's baseline failed its task).
  - **Thin margins.** One more unsupported claim fails support, and the intervals are wide.
  - **The labels** are model reviews adopted by the owner, not two independent human reviews, and are not independent of SYSTEM_SPEC §7. The scenarios and gold were written by the coding agent and are not held out.
  - **R2's failure lesson was not tested.** In six of the last seven runs (the fourth to the eighth, and the tenth), session A fixed the import before the failure appeared. Failed-approach recall rests on L1 #1 and R1 #0.
  - **Not repeated.** One run passed, after nine failures.
- **The checklist:** `smoke_quality_gates` is `passed`. The verdict stays `blocked`:
  - the live case variants and the inference and delivery certification also need Linux and macOS observed live;
  - `release_artifacts` needs signing material, a declared license and the owner's go-ahead.
  - `FULL_RELEASE_AVAILABLE` is unchanged, and enabling the full profile stays the owner's decision (decision 0026).
- **The sanitized record** in [`docs/evaluations/preview-live-2026-11-04-gate10/`](evaluations/preview-live-2026-11-04-gate10/report.md) now holds the recorded `adjudication.json`, the outside review and the regenerated report: 36 files. A scan by count found 0 user names, drive paths, keys, email addresses or model identifiers.
- **Tests:** none changed. `tools/release_checklist.py` → no problems, verdict `blocked`.
- **Acceptance:** `smoke_quality_gates` passed on the tenth live gate. The coverage manifest's statuses are unchanged, because its live variants also name Linux and macOS.

### 2026-11-04 — Live-gate helpers tracked; working from a web session; the owner cannot run macOS live

- **The owner's platforms.** The owner cannot run a live check on macOS, and may be able to run one on Linux. IMPLEMENTATION_PLAN requires native Windows, macOS and Linux for platform acceptance, so the checklist's live items cannot pass as written.
  - The open choice is the owner's: either the preview is certified only on the platforms observed live, with macOS stated as not certified (a recorded decision), or the live checks run elsewhere, for example on hosted CI machines with the owner's key as a repository secret. That route is untested: whether the operator guards allow it without a workaround has not been checked.
  - For the checklist's platform items, a Linux live check is most likely the pilot's route and delivery steps (about 6 minutes on Windows), not a whole gate.
- **Helpers moved into the repository**, so a session without this laptop has them: `tools/live_gate/sanitize_record.py`, `build_review_packet.py`, `label_gate.py` and `review_prompt.md`.
  - They were untracked (`probe-private/`) or session scratch. The tracked copies read the user name from the environment instead of naming it.
  - Each reproduces the tenth gate's outputs exactly: the sanitized record, byte for byte; the review packet; and the labels.
- **Still local to the owner's laptop, by rule:** `probe-private/` (the probe configuration, the run scripts with their machine paths, and the run logs), the results directories `C:\Code\rl-gate*` and pilots `C:\Code\rl-pilot*`, `dist/` and `wheelhouse/`.
  - A web session can do deterministic work, documentation and analysis of committed records.
  - Live runs, probes and label recording stay on the laptop, run by the owner.
- **AGENTS.md** now lists the owner's standing working rules, so every session follows them.
- **Tests:** `uvx ruff@0.14.0 check --select F,E9,B tools/live_gate/` → clean.

### 2026-11-04 — Open source under GPL-3.0-only; the preview certifies Windows and Linux (decisions 0041, 0042)

- **The owner's decisions:**
  - **Platforms:** "Windows and linux is fine for now". The owner has no Mac.
  - **License:** open source now, published later, under GPL 3.0, chosen from Apache-2.0, MIT and GPL-3.0, which were explained in plain terms.
- **Decision 0041.** The Claude preview's platform acceptance is native Windows and Linux.
  - macOS is not certified for the preview; its deterministic suites still run in CI.
  - A platform is certified by its live route and delivery checks. The smoke gate passed once, on Windows, and is not repeated per platform.
  - The full release still requires all three platforms.
  - IMPLEMENTATION_PLAN's platform line points to the decision.
- **Decision 0042.** The license is GPL-3.0-only.
  - `LICENSE` is the Free Software Foundation's text, unchanged (SHA-256 `3972dc97…6986`), and it matched GitHub's copy word for word.
  - `pyproject.toml` declares `license = "GPL-3.0-only"` and `license-files` (PEP 639). `docs/release/DEPENDENCIES.json` records it.
  - `tools/build_release.py` now reads the expression with `tomllib`. Its regular expression would have kept the TOML quotes.
  - All runtime dependencies are GPL-3.0-compatible (MIT, Apache-2.0 or BSD-2-Clause, PSF-2.0).
- **README rewritten** for an open repository: what Recalith is, its honest status, how to try it, a call for macOS and Linux live certification, a map of the documents, and the license. The starter packet's README is kept as `docs/STARTER_PACKET.md`, with its links adjusted.
- **CI, observed while checking the README's claims:**
  - On `d8a4bbc`, macOS Python 3.13 failed one test, `tests/unit/test_api_providers.py::test_hung_server_is_killed_at_the_timeout`.
    - The result was the correct `provider_timeout`, in 2.1 s, but the child's own 2 s socket timeout fired before the parent's 2 s kill, so `outcome.timed_out` was false.
    - That is a race in what the test asserts, not a wrong result.
    - Fixing it is deterministic work for a later session; the test stays as it is until then.
  - On `fa80354`, the macOS job was cancelled after 15 minutes with no failure reported.
  - Linux and Windows were clean, and `4074c0f` passed on every runner.
- **Runs:**
  - `tools/build_release.py --out <scratch>` → exit 0, no problems. The wheel holds `dist-info/licenses/LICENSE` and `License-Expression: GPL-3.0-only` (metadata 2.4), and the sdist holds `LICENSE`.
  - `uv lock --check` → current.
  - `tools/release_checklist.py` → no problems, verdict `blocked`.
  - The release-checklist and inventory test passed.
- **Still open before publication:**
  - a Linux live run;
  - signing (planned: GitHub artifact attestations, keyless, not enabled because each run writes to a public transparency log);
  - the package name on the index (decision 0001);
  - the owner's go-ahead.

### 2026-11-06 — Pre-publication audit of the memory system (web session, read-only)

A full review of `0.1.0.dev10` before public use, by eight parallel reviewers (one per subsystem) with reproductions against real installations, plus a lead review of the evaluation harness and the tenth-gate record and a run of the deterministic suite. Nothing under `src/`, `tests/` or `evals/` was changed; no guarded or credential-bearing command was run.

- **Report:** [docs/audits/2026-11-06-memory-system-audit.md](audits/2026-11-06-memory-system-audit.md). **Plan:** [docs/audits/2026-11-06-fix-plan.md](audits/2026-11-06-fix-plan.md).
- **Verdict:** not fit for strangers yet. One critical and eleven high findings, about thirty medium and low, in four clusters: secrets escaping the scrubber (a `--password VALUE` argument survives in `action.argv` into the spool, store, delivered overlay and provider requests; `SECRET_KEY=`/`DB_PASS=` unscrubbed in text; a named `HTTP_PROXY` sends a loopback plain-HTTP curator request with its key to the proxy host); the worker spinning or starving (lease never renewed across expansion rounds; near-fit jobs re-prepared every second and blocking protected revalidation; backoff ladder stuck at 60 s for non-launch failures; non-`RecalithError` exceptions kill the worker with `idle` in the status file; retention sweep livelock behind 4,096 pinned payloads); retrieval dropping the applicable fact at scale (applicability evaluated after the 96-seed and 64-posting caps; the pre-action view's 64 lessons span all families); and an install path nobody can follow from the docs (circular quick start, `bootstrap.py` traceback on a clone, no console script, release artifacts missing `bootstrap.py`/lock/wheelhouse, sdist shipping the whole repository, `integrate` editing a tracked settings file in a monorepo subdirectory).
- **Held up:** installation isolation, the operator guard, fenced transactions, pins and expiry, the forget purge and suppression-aware restore (run end to end), the §8.2 advice table on both compilers, TLS/redirect/key handling, strict contracts, path authorization, the stdlib-only hook imports and durability order, every budget and retention constant against the spec, and the tracked tree's freedom from secrets and personal paths (one scratch path in a measurement file excepted).
- **Evaluation:** the tenth gate's record is honest but weaker than "passed" suggests: a dirty tree, no digest of the scenarios or oracles (edited twice during the gate cycle), two gold retrieval points unsatisfiable by design, and a corpus on which the no-memory baseline never fails, so the headline benefit is unmeasurable; the measured effect is cost (+18 % foreground tokens, ~220 k background tokens per scenario). Every Phase 0–3 fix changes gated behavior, so the gate must be re-run on the fixed engine.
- **Deterministic suite:** `uv sync --locked` then `python -m pytest -q -rs -p no:cacheprovider` on Linux, Python 3.13.18: **1,399 passed, 18 skipped, 0 failed** in 35 min 37 s, exit 0 (skips: installed Claude Code 2.1.318 is not capture-certified, so the installed-host smoke tests replay fixtures; root permissions; Windows-only cases; the real-wheelhouse provisioning test). Every audited defect sits in code the suite passes: they are gaps between the spec's intent and the code that no test asserts yet; the plan adds one per finding.
- **Next action:** Phase 0 of the plan (engine `0.1.0.dev11`): scrub the split argv, close the text-redaction gaps, stop proxying loopback HTTP, size message parts by canonical JSON, remove the scratch path from the measurement file. Then Phases 1–4, then the owner's eleventh gate and Linux run (Phase 5).

### 2026-11-08 — Audit Phase 0: secrets across split arguments, loopback never proxied, parts sized as stored (`0.1.0.dev11`, decision 0043)

Phase 0 of the [fix plan](audits/2026-11-06-fix-plan.md), all five items, in a web session. Nothing guarded or credential-bearing was run.

- **FP-1 (critical):** `redact.scrub_argv` scrubs an argument array across neighbouring elements (the element after a secret flag, the password of `-u user:pass`, MySQL's `-pVALUE`), and `scrub_json` applies it to every `argv` it meets, so the hook, the worker and the pre-action query share it. The audit's reproduction (`mytool --password hunter2secret --host db` through the real `-I` hook entry) now stores `["mytool", "--password", "[REDACTED:cli_secret]", "--host", "db"]` and the secret is in no byte of the segment. The plan's "split the scrubbed command" was not used: it would have made every secret-bearing command `unknown` (decision 0043, Decision 1).
- **CAP-2, CAP-3, CAP-7:** `sensitive_name` judges text assignments and JSON keys alike (`SECRET_KEY`, `SECRET_KEY_BASE`, `*_SIGNING_KEY`, `ENCRYPTION_KEY`, `DB_PASS`, `PGPASSWORD`); new rules for URL passwords with `/`, cookie headers, signed-URL signatures, `glpat-`, `SG.`, Twilio `SK`, bare AWS secret keys, `mysql -p`, `curl -u`; `psql --password mydb` keeps its database name.
- **PROV-1:** the transport never proxies a loopback host; a proxy variable is refused in `nonsecret_env`. The unit test that asserted the old behavior now asserts the opposite, with a live proxy that must see nothing.
- **Found while fixing (pre-existing in `0.1.0.dev10`):** the text assignment rule backtracked quadratically; 16 KiB of `a.key-` took 8.2 s to scrub inside a 250 ms hook. The name is now matched once (possessive, bounded) and every adversarial input scrubs in under 11 ms; `test_scrubbing_stays_linear_on_adversarial_tool_output` guards it.
- **CAP-1:** message parts are sized by their canonical JSON; four escape-heavy pastes now partition into parts both validators accept.
- **REL-6:** the scratch path is gone from the measurement file; both measurement tools record the output's file name on any platform; a new test scans all tracked evidence for scratch paths and user homes.
- **Engine `0.1.0.dev11`.** The transport is in the API adapter digest, so a `0.1.0.dev10` route reports `adapter_changed` until recertified. The release checklist's `smoke_quality_gates` is now `blocked`: it passed on `0.1.0.dev10`, and this engine changes capture, partitioning and the transport.
- **Specs:** SYSTEM_SPEC §9.1 and §13, DATA_CONTRACTS §11 note the two rules.
- **Tests added** (each new end-to-end test fails on `0.1.0.dev10`): `test_split_command_secrets_never_reach_spool_scratch_store_or_overlay`, 50 redaction cases, `test_a_loopback_endpoint_never_leaves_the_machine_through_a_proxy` and two proxy rules, `test_escape_heavy_messages_partition_into_valid_parts_on_both_paths` (four shapes), `test_tracked_evidence_is_sanitized.py`.
- **Checks:** `tools/generate_schemas.py --check` 0, `tools/generate_hook_wire.py --check` 0, `requirements.lock` matches `uv export`, `tools/release_checklist.py` `problems: []` (verdict `blocked`). Full suite (`python -m pytest -q -rs -p no:cacheprovider`, Linux, Python 3.13.18): 1,470 passed, 18 skipped, 1 failed in 38 min 47 s. The failure was the coverage manifest still mapping A67 to the replaced proxy test; the manifest now names the three replacement tests, and `tests/integration/test_evaluation.py` plus `tests/unit/test_coverage_manifest.py` pass (9 passed). The 18 skips are the environment's, as on 2026-11-06 (installed Claude Code 2.1.318 is not capture-certified; root permissions; Windows-only cases; the real-wheelhouse provisioning test).
- **Not done here:** the existing installations' already-captured split-argument secrets are not rewritten (a forget by source range removes them); the owner's re-certification of a fresh `0.1.0.dev11` pilot waits for Phase 5.
- **Next action:** Phase 1 (engine `0.1.0.dev12`).

### 2026-11-08 — Audit Phase 1: the worker never spins, starves work or dies silently (`0.1.0.dev12`, decision 0044)

Phase 1 of the [fix plan](audits/2026-11-06-fix-plan.md), all twelve items, in a web session. Nothing guarded or credential-bearing was run.

- **Leases and the ladder (CTL-1, CTL-2, CTL-3):** a model lease covers every round and is renewed before each; a lease that runs out under its own worker fails onto the ladder; a budget wait is due again in ten minutes or at the next UTC day, so later bands (protected revalidation included) run; every lease is an attempt, given back when it was not one (budget wait, provider unavailable, a busy task's deferral, now `PrepareDeferred`).
- **Crashes (CTL-4):** each poll step after privacy recovery runs on its own and records `poll_error:<step>:<type>`; a fatal error leaves `state: crashed`, which health reports as `worker_crashed` (OPERATIONS §2 has the row).
- **Review retries (CTL-5):** a missing or `review_capacity` verdict is reviewed again alone, at most three times per claim, then `review_retry_limit`; DATA_CONTRACTS §5 and the review module say so.
- **Retention and forgetting (STO-1, STO-2):** the sweep pages past pins with a resume point in its report; `backup.holds()` checks the bookkeeping the purge scrubs.
- **Episodes (CAP-5):** the plan's "close at session end" was rejected after it broke the cross-session working-memory test (a resumed session's fix belongs in the same episode); an unresolved range becomes an `open` episode at the 24-hour idle pause instead, and open episodes are extracted.
- **Lineage (CAP-4):** the snapshot rule covers all five capture-certified versions; a test keeps the lists equal.
- **Session lock (FP-2):** acquire re-checks that the path names the locked file and refreshes it; the prune takes a whole idle session only while holding its lock.
- **CLI envelope (PROV-2, PROV-3):** split on `\n` only; error results name their code, an auth rejection withdrawing the route.
- **Small (1.12):** read views refuse pragma writes; stop file 0600 and journal directories 0700; a restore waits for an in-flight call; requests name the configured timeout; strict episode pairing; continuity by pause start; a refused source tail moves its cursor.
- **Engine `0.1.0.dev12`.** The CLI adapter changed (`adapter_changed` for an earlier Claude CLI route until recertified). The checklist's smoke gate stays blocked.
- **Tests added:** eight worker-lane tests, two review-retry tests, two retention-sweep tests, one forgetting test, one episode test, one lineage test, three session-lock tests, nine CLI-envelope cases, eighteen small-fix cases (`test_audit_small_fixes.py`). The existing capacity test now expects its one bounded retry.
- **Checks:** schema and wire drift checks 0, `requirements.lock` matches, `tools/release_checklist.py` `problems: []`. Full suite (`python -m pytest -q -rs -p no:cacheprovider`, Linux, Python 3.13.18): 1,484 passed, 18 skipped, 30 failed in 34 min 39 s. All 30 were the kill/restart families `test_claim_admission_crash_matches_reference`, `test_provider_path_crash_matches_reference` and `test_api_provider_path_crash_matches_reference`: their scripted reviewers answer `review_capacity` or leave a candidate unjudged, which the bounded retry now reviews again. The claim-admission reviewer now judges by claim (so a retry gets the same answer and reaches the limit) and states a no-op reason when it judges nothing; the expectations name the retries (seven review jobs, `deferred`/`review_retry_limit`; four for the provider scenarios). The three families then passed in full (30 passed, 9 min 8 s); no `src/` file changed after the suite started.
- **Not covered by a test:** the refused-tail cursor (no current adapter can produce that tail) and a restore waiting on a live model call (decision 0044, Limits).
- **Next action:** Phase 2 (engine `0.1.0.dev13`).

### 2026-11-08 — Audit Phase 2: retrieval holds at corpus scale (`0.1.0.dev13`, decision 0045)

Phase 2 of the [fix plan](audits/2026-11-06-fix-plan.md), all eight items, in a web session. Nothing guarded or credential-bearing was run. No schema change.

- **Applicability before the caps (RET-1):** the service search ranks lexical candidates in SQL (scope-filtered), walks up to 768 of them and skips statically inapplicable claims until 96 seeds remain (`candidate_scan_bounded` past the bound); an inapplicable lookup row has a null body and no postings. The plan's hot scope columns were not needed.
- **The current action's caution (RET-2):** the hook's pre-action compile reads its own action family's lookup rows directly (indexed `claim_heads.action_family_digest`, at most 16, 60 ms floor). The plan's per-family view slices were not needed.
- **Dependency check (RET-4):** every live claim with dependencies and current freshness, in both compilers; the caution gate is unchanged.
- **Query time (RET-3):** grouped SQL ranking and chunked document reads; p50 64–73 ms, p95 100–118 ms at 10,000 heads all sharing the query words (two runs of the test on the 4-vCPU container); the test asserts p95 under 1 s and at most 832 documents loaded.
- **Lost FTS5 (RET-5):** refresh rebuilds on `tokens` and empties the FTS shadow tables without the module; forget, retention and restore use one helper.
- **Counts, quotes, wording (RET-6/7/8):** `fit()` keeps the cap's omissions; fallback rows carry `cited_ids` and `quoted_states`, checked by the hook; conflict texts state the conflict.
- **Filesystems (CAP-6):** VM, WSL and unknown-FUSE shared folders refused on Linux (all mountinfo escapes decoded); macOS by statfs `MNT_LOCAL`; Windows UNC roots and remote drives.
- **Small (CAP-8/9/12):** 63 schema snapshots (every operation payload, `ToolPayload`, `ObservationDescriptor`, `AgentAttemptPayload`); HTML code/quote blocks and guarded `%`/`#`/`user@host` prompts are regions; a result bounded to its tail quotes no excerpt.
- **Engine `0.1.0.dev13`.** No adapter changed. The checklist's smoke gate stays blocked.
- **Tests added:** seven retrieval tests (each failing on `0.1.0.dev12`), one delivery test, fourteen filesystem cases (replacing the single patched-type test), one schema-coverage test, twelve region cases, one excerpt test.
- **Checks:** schema (63 snapshots) and wire drift checks 0, `requirements.lock` unchanged, `tools/release_checklist.py` `problems: []`, `ruff --select F,E9,B` clean on the touched source (one pre-existing unused variable in `test_installations.py` left as is). Full suite (`python -m pytest -q -rs -p no:cacheprovider`, Linux, Python 3.13.18): 1,548 passed, 18 skipped, 0 failed in 42 min 42 s, exit 0; the skips are environment-only (root permission bits, no provisioning wheel, no capture-certified Claude CLI installed (2.1.319 found), Windows-only mechanisms, a case-sensitive filesystem). No `src/` or `tests/` file changed while it ran.
- **Next action:** Phase 3 (engine `0.1.0.dev14`).

### 2026-11-09 — Audit Phase 3: an install path a stranger can follow (`0.1.0.dev14`, decision 0046)

Phase 3 of the [fix plan](audits/2026-11-06-fix-plan.md), all nine items, in a web session. Nothing guarded or credential-bearing was run against a live route; the walkthrough below used a pseudo-terminal as the operator's terminal and no provider.

- **Bootstrap (CLI-1, CLI-2, CLI-12):** `bootstrap.py install` provisions an empty directory or a fresh clone (the private layout exists before staging; `OSError` is exit 5; a missing wheel, wheelhouse or lock is named); `bootstrap.py init` and `operator-token create` provision and then run that form on the provisioned interpreter with the caller's terminal; an unmarked runtime tree is refused, never deleted. The wheel installs the `recalith` console script; metadata has authors, urls, classifiers, keywords. The launchers and the CLI's pre-init refusal name the bootstrap form.
- **Release layout (REL-1):** `tools/build_wheelhouse.py` (one hash-checked wheelhouse per platform and Python, named for both, never mixed, with `WHEELHOUSE.json`); `build_release.py` copies `bootstrap.py` and `requirements.lock` and verifies every wheelhouse in `--out`; `release.yml` builds wheelhouses on Linux and Windows for 3.12 to 3.14, assembles them, and installs from the layout alone to `status` exit 8 before uploading; `ci.yml`'s offline provisioning uses the tool.
- **integrate claude (CLI-3, CLI-4, CLI-5, CLI-7):** tracking judged by `git rev-parse --show-toplevel` with the user's own config plus `-c safe.directory`; an unknown state is refused (`settings_tracking_unknown`); a symlinked settings file is refused on install and removal; the settings file keeps its mode, new and tracked files are ordinary files; a whitespace-only before-copy parses.
- **status (REL-10, CLI-6):** without `--json`, one screen with every degraded code's meaning and action (`operations/reasons.py`, checked complete against health's codes) and the next command; `integrate` and OPERATIONS §4 say the curator key lives in the shell that launches Claude Code; health already judges a running worker's own route report, and the text says whose environment lacks the key.
- **Small (3.8):** Windows notice spelling; the POSIX hook launcher drops stderr and exits 0; `init` on a clone refuses a differing profile; `doctor --full-integrity` guarded and in the deny rules (228 POSIX / 475 Windows); exit codes for every registered error; a failed token registration unlinks the file; decision 0019's count note.
- **Docs (3.9):** README "Trying it" and OPERATIONS §4 are one copy-pasteable sequence per platform from the release directory, linking `docs/probes/LOCAL_CONFIG.md`; DATA_CONTRACTS §12 has the bootstrap forms, the guarded doctor form, the new exit codes, the integrate refusals and the human status.
- **Walkthrough (Linux, this container, release layout built here: `tools/build_release.py --out rel14` after `tools/build_wheelhouse.py --out rel14`; `RELEASE=rel14`, an empty project directory, `env -i PATH HOME`, a pseudo-terminal from `pty.spawn` standing in for the operator's terminal, no Claude Code, no provider):**
  1. `python3 $RELEASE/bootstrap.py init --project . --profile coding --release-profile claude_preview --wheel $RELEASE/recalith-0.1.0.dev14-py3-none-any.whl --expected-digest $(grep ' recalith-0.1.0.dev14-py3-none-any.whl$' $RELEASE/SHA256SUMS | cut -d' ' -f1) --wheelhouse $RELEASE/wheelhouse-linux-x86_64-cp313` → `bootstrap: runtime 0.1.0.dev14 provisioned`, then the init result; **exit 0**.
  2. `.recalith/bin/recalith status` → 33 lines: `readiness degraded (not autonomous_ready)`, seven codes with meanings, `Next: certify a route from an ordinary terminal: tools/probe_provider.py …`; **exit 8**. `--json status` `degraded`: `host_not_integrated, provider_not_configured, review_provider_unavailable, worker_autostart_not_registered, command_deny_rules_not_installed, private_path_probe_not_run, delivery_not_certified` (the expected pre-certification set).
  3. `python3 $RELEASE/bootstrap.py operator-token create --project . --output op.token --wheel … --expected-digest … --wheelhouse …` → `registered: true`; **exit 0**. `bootstrap.py status --project .` → provisioned; **exit 0**.
  4. A second `bootstrap.py init … --operator-token-file op.token` → `already_provisioned`, then `policy_refused: an installation already exists here; init never resets memory`; **exit 6**.
  The same layout, installed noninteractively with a token, is the gated test `test_bootstrap_init_form_initializes_an_empty_directory` (run here with `RECALITH_TEST_WHEEL`/`RECALITH_TEST_WHEELHOUSE` pointing at `rel14`: 7 bootstrap tests passed). The Windows sequence is written from decision 0027's pilots and not walked here.
- **Engine `0.1.0.dev14`.** No adapter changed. The checklist's smoke gate stays blocked.
- **Tests added:** six bootstrap tests (two gated on a real wheelhouse), five release-tool tests, nine integrate tests, four CLI tests, one health test; the launcher digests re-pinned; the guarded-form matrix gains `doctor --full-integrity`.
- **Checks:** schema and wire drift 0, `requirements.lock` matches, `tools/release_checklist.py` `problems: []`, `ruff --select F,E9,B` clean on `src/`, `bootstrap.py` and `tools/`. Full suite (`python -m pytest -q -rs -p no:cacheprovider`, Linux, Python 3.13.18, with `RECALITH_TEST_WHEEL`/`RECALITH_TEST_WHEELHOUSE` set so the two gated bootstrap tests ran): 1,573 passed, 17 skipped, 3 failed in 41 min 18 s. The three were consequences of the newly guarded `doctor --full-integrity` form: `tools/probe_engine.py`'s sample-argument map lacked the 19th form (two deny-command tests), and `test_doctor_and_health_report_the_chain` called the form without a token. The map gained the form and the test passes a token; the two files then passed in full (23 passed, 1 skipped). The skips are environment-only (root permission bits, no capture-certified Claude CLI installed, Windows-only mechanisms, a case-sensitive filesystem). No `src/` file changed after the suite started; the two fixes touched `tools/` and `tests/`.
- **Next action:** Phase 4 (public-repository hygiene; no engine change except SPDX headers once the owner names the holder).


## The next-session handoff as it stood on 2026-11-09 (historical)


Task 18's preview slice, the Task 11 follow-up (decision 0021), the Windows typed-state slice (decision 0022), the direct-API inference backends (decision 0023) and, in Cut 2, Task 5's full slice (decision 0024: the revision chain and integrity scanner) Task 15's capsule slice (decision 0025: exact evidence capsules) and Task 17's preview-to-full transition (decision 0026), all full profile only, are built; see their checkpoints. The transition is reached only through `operations.upgrade.transition` (the tests); the CLI and `init --release-profile full` answer 4 until the owner enables the full profile.

- The preview gate's first live run failed (2026-10-26 checkpoint). The harness gaps it exposed are closed (decision 0028 items 12–16), and so are its engine causes (decision 0029, engine `0.1.0.dev1`).
- The second live run failed too (2026-10-29 checkpoint): mostly a lid closure overnight and Wi-Fi drops on waking, but also R4's agent-written `CLAUDE.md`, R4's missing freshness label and an oracle false negative (fixed, decision 0028 item 17). Claude Code 2.1.310 delivery is live-certified.
- The third live run (2026-10-31 checkpoint) was complete and clean, but the drafted labels put useful recall at 5/8 and failed-approach recall at 1/3. Two failure lessons were refused because a pipe hid the exit status, and one declared decision was not extracted. `extract_claims@3` (decision 0035, engine `0.1.0.dev5`) addresses both.
- The fourth live run (2026-11-01 checkpoint) was complete and clean, in 45 minutes at 6 slots, and its drafted labels meet every recall and support target. It failed on R4's conflict label, which `@3` caused: a user's statement about storage was kept as a decision without its file. Decision 0036 (engine `0.1.0.dev6`) fixes that. It also curates a session that only talked, and resumes the one active task at a new session's start.
- The fifth live run (2026-11-01 fifth-gate checkpoint), on `0.1.0.dev6`, was complete and clean in 48 minutes. It met every measure that needs no labels, conflict preservation included, and showed all three changes of decision 0036 live. One judgment call (L1 #1) decided it. The owner accepted the recommendation that L1 #1 was missed, so the fifth gate failed on failed-approach recall, and engine `0.1.0.dev7` (decision 0037) was merged. The next run is in item 2.
- The sixth live run (2026-11-02 checkpoint), on `0.1.0.dev7`, showed decision 0037 working, but two user declarations were lost to code's strict checks, so it failed on useful recall and the forgetting demonstration. Most `update_task` replies fail validation too. Engine `0.1.0.dev8` (decision 0038) records what each malformed operation got wrong, and the harness keeps what each refused claim cited (decision 0028 item 27). The next run is in item 2.
- The seventh live run (2026-11-03 checkpoint), on `0.1.0.dev8`, admitted L3's declaration and ran the forgetting demonstration end to end. The demonstration failed: the session after the forget was delivered text holding the forgotten value, and the record could not say from where. As drafted, its labels meet every labeled measure. Engine `0.1.0.dev9` (decision 0039) gives each patch value its field's shape and keeps evidence out of payloads. The forgetting check now separates forgotten content from a fresh session's own relearning (decision 0028 item 29). The next run is in item 2.
- The eighth live run (2026-11-03 eighth-gate checkpoint), on `0.1.0.dev9`, showed all five demonstrations, and decision 0039 cured the refused replies. As drafted, its labels meet every labeled measure. It failed only on `incorrect_confident_guidance`, through an R3 oracle false negative, fixed for the next run (decision 0028 item 30). The engine is unchanged. The next run is in item 2.
- The ninth live run (2026-11-04 checkpoints), on `0.1.0.dev9`, met every measure that needs no labels, both recall measures and all five demonstrations. With the owner's recorded labels it failed on supported precision (22/24): two claims overstated a detail. Support is judged at admission (decision 0028 item 31). Engine `0.1.0.dev10` (decision 0040) makes a claim say no more than its evidence, and has the review test every clause.
- The tenth live run (2026-11-04 checkpoints), on `0.1.0.dev10`, **passed** with the owner's recorded labels: support 21/22, useful recall 7/7 and failed-approach recall 2/2, with every other measure and all five demonstrations met. It is the first live pass of the smoke quality gate (checklist `smoke_quality_gates`). The preview release still waits on Linux and macOS live runs and on release signing and license.
- Every healthy §7 target is met on every native platform on b3f1f1f: hook latency and usefulness, typed-state p95 ≤ 5 s and the idle footprint. The checklist item `hook_latency_usefulness_per_platform` is `passed`.

**Native Windows (decision 0027).** The owner's laptop is a native Windows host: integrate installs the `.cmd` hook command there, Claude Code 2.1.309 and 2.1.310 are capture-certified, the harnesses run natively, the §7 gate is met through the installed command, and the pilot `C:\Code\rl-pilot` is set up for the operator (see the native Windows checkpoint). The live gate's trial path is built (decision 0028).

Next actions, in order:

1. **Done (2026-10-23):** the owner certified the curator route and all four delivery paths live on native Windows (B1 live checkpoint). A later Claude Code version needs a capture review (decision 0019) and the delivery probe again. Earlier instruction, kept for reference: **The operator's live certification on native Windows.** Run the PowerShell commands of the native Windows checkpoint (steps 1–7; Anthropic Messages, already configured), then record the live results here: `docs/host-compatibility.json` (check it holds no secret, user name or machine path), the read-only `recalith status`, the coverage manifest for any live variant that actually ran.
   - A later Claude Code version needs a fixture capture and review before it is certified (decision 0019), then `integrate claude` again.
2. **The live gate: passed on the tenth run** (the 2026-11-04 tenth-gate checkpoints; decision 0040; earlier, decisions 0030–0039 and decision 0028 items 12–31). Done on `0.1.0.dev1`: the pilot `C:\Code\rl-pilot2`, its live route, live delivery on Claude Code 2.1.310, the one-scenario pilot, the second gate (failed), and the R4 rerun with kept workspaces (reproduced). Done on `0.1.0.dev2`: the pilot `C:\Code\rl-pilot3`, its live route and live delivery on 2.1.310, and the second R4 rerun (`C:\Code\rl-p5`; the label still missing, with a different claim shape; decision 0031). Done on `0.1.0.dev3`: the pilot `C:\Code\rl-pilot4`, its live route and live delivery on 2.1.310, and the third R4 rerun (`C:\Code\rl-p6`; the file declared, but changed by the harness before curation; decision 0028 item 18). Done on `0.1.0.dev4` (2026-10-31): the pilot `C:\Code\rl-pilot5`, its live route and live delivery on 2.1.310, the fourth R4 rerun (`C:\Code\rl-p7`; the retrieval point met, both arms clean) and the third gate (`C:\Code\rl-gate3`; complete and clean, recall under target). Done on `0.1.0.dev5` (2026-11-01): the pilot `C:\Code\rl-pilot6`, its live route and live delivery on 2.1.310, and the fourth gate (`C:\Code\rl-gate4`; complete and clean, failed on R4's conflict label). Done on `0.1.0.dev6` (2026-11-01): the pilot `C:\Code\rl-pilot7`, its live route and live delivery on 2.1.310, and the fifth gate (`C:\Code\rl-gate5`; complete and clean, every unlabeled measure met; failed on failed-approach recall by the owner's call on L1 #1). Done on `0.1.0.dev7` (2026-11-02): the pilot `C:\Code\rl-pilot8`, its live route and live delivery on 2.1.310, and the sixth gate (`C:\Code\rl-gate6`; failed on useful recall and the forgetting demonstration). Done on `0.1.0.dev8` (2026-11-03): the pilot `C:\Code\rl-pilot9`, its live route and live delivery on 2.1.310, and the seventh gate (`C:\Code\rl-gate7`; failed on the forgetting demonstration; as drafted, its labels meet every labeled measure). Done on `0.1.0.dev9` (2026-11-03): the pilot `C:\Code\rl-pilot10`, its live route and live delivery on 2.1.310, and the eighth gate (`C:\Code\rl-gate8`; all five demonstrations; failed on incorrect confident guidance through R3's oracle; as drafted, every labeled measure met). Done on `0.1.0.dev9` (2026-11-04): the pilot `C:\Code\rl-pilot11`, its live route and live delivery on 2.1.310, and the ninth gate (`C:\Code\rl-gate9`; failed on supported precision, 22/24, with the owner's recorded labels; everything else met). Done on `0.1.0.dev10` (2026-11-04): the pilot `C:\Code\rl-pilot12`, its live route and live delivery on 2.1.310, and the tenth gate (`C:\Code\rl-gate10`; **passed** with the owner's recorded labels: support 21/22, useful recall 7/7, failed-approach recall 2/2). What remains is the owner's, in order:
   - **Done: the tenth gate passed** with the owner's recorded labels (the labels checkpoint). For a later gate, after an engine or host change: `powershell -ExecutionPolicy Bypass -File probe-private\run-pilot12-gate10.ps1` (untracked; `-Slots N` to change the default 6).
     - It runs a fresh pilot's steps 1–8 on `C:\Code\rl-pilot12` from the `0.1.0.dev10` wheel, then the tenth gate into `C:\Code\rl-gate10`.
     - It asks for the key once and runs unattended for about an hour (the ninth run took 49 minutes).
     - It logs every exit code to `probe-private\pilot12-gate10-run.log` and stops at the first unexpected one.
     - The gate step exits 8 even when everything ran, because its labels come afterwards.
   - **Then the labels.** This session drafts suggestions with each item's evidence (`adjudication.suggested.json`, every label null, and a readable `labels-to-review.md`). The sixth gate's sheet also shows each candidate's review objections (decision 0028 item 25). Only a reviewer's labels count (ACCEPTANCE_TESTS §5), so the gate can pass only after the owner records them:
     1. sanitize the results into the repository with `tools\live_gate\sanitize_record.py <results> docs\evaluations\<record>` (every scan count must be 0), and build the packet with `tools\live_gate\build_review_packet.py docs\evaluations\<record> . <results>\review-packet.md "<title>"` (it leaves out the suggestions);
     2. send the packet with `tools\live_gate\review_prompt.md` to an outside model, and paste its JSON reply here; this session compares it with the suggestions, and the owner decides where they differ (`labels-to-review.md` has the deciding calls first);
     3. record them with `.venv\Scripts\python.exe tools\live_gate\label_gate.py <results> --reviewer "<the route, as it happened>" --independent no`, adding `--set KEY=LABEL` for each change (it writes `adjudication.json` and never overwrites one);
     4. run `.venv\Scripts\python.exe evals\run.py report <results>`. Exit 0 is `passed_smoke`; exit 8 lists what failed. Then sanitize again, so the record holds the labels and the report.
   - **Label an earlier gate** (optional; it changes no result): the third to eighth gates' sheets and suggestions are written (`C:\Code\rl-gate3` to `C:\Code\rl-gate8`; the ninth is labeled). For the second, run `evals\run.py adjudicate C:\Code\rl-gate2` first. Then label the template, save it as `adjudication.json`, and run `evals\run.py report` on that directory.
   - **Decided (delegated by the owner, 2026-10-29):**
     - R4's agent-written instruction files: denied in both arms (decision 0028 item 19);
     - fresh-session reuse with a capable agent: required to happen, with its difference reported (item 20);
     - the input pool: 1,500,000 ordinary (decision 0034);
     - an attached contradiction: a revalidation trigger (decision 0032);
     - a change before curation: the dependency records the bytes the read saw (decision 0033).
   - **Before any run:** keep Claude Code's background updates off (`DISABLE_AUTOUPDATER`, OPERATIONS §6; check `claude --version` prints 2.1.310). Keep the laptop plugged in with the lid open, on a stable network (wired if possible). Keep-awake stops idle sleep, not a lid closure.
   - Keep the lid open and the power connected throughout; a suspension fails the gate. To stop early, press Ctrl+C in the run's window rather than sleeping the laptop.
   - For a later fresh pilot and gate, copy `probe-private\run-pilot12-gate10.ps1` and edit its paths, wheel and digest. The commands it runs are below.

   The commands (native PowerShell, an ordinary window, from the repository root; type `$LASTEXITCODE` after each):
   ```powershell
   Get-ChildItem Env: | Where-Object Name -like '*CLAUDE*'   # must print nothing
   claude --version                                         # must print 2.1.310
   $env:PILOT = 'C:\Code\rl-pilot7'; $py = '.\.venv\Scripts\python.exe'
   New-Item -ItemType Directory $env:PILOT | Out-Null; git -C $env:PILOT init -q                                    # 1. an empty repository
   & $py -m recalith init --project $env:PILOT --profile coding --release-profile claude_preview                     # 2. expect 0
   py -3.13 bootstrap.py install --project $env:PILOT --wheel dist\recalith-0.1.0.dev6-py3-none-any.whl --expected-digest 6cbf968dd5609f56ba5f42cf6ba210858a1a20a17b3bba49ad6453a484946243 --wheelhouse wheelhouse   # 3. expect 0
   $k = Read-Host -AsSecureString 'Anthropic API key'
   $env:ANTHROPIC_API_KEY = [System.Net.NetworkCredential]::new('', $k).Password; Remove-Variable k
   [bool]$env:ANTHROPIC_API_KEY                             # must print True (it never prints the key)
   & $py tools\probe_provider.py --config probe-private\local-config.json --backend anthropic_messages --output docs\host-compatibility.json --route-out $env:PILOT   # 4. expect 0
   & $py tools\check_provider_runtime.py --config probe-private\local-config.json --backend anthropic_messages --project $env:PILOT --output docs\host-compatibility.json   # 5. expect 0
   & "$env:PILOT\.recalith\bin\recalith.cmd" integrate claude                                                        # 6. expect 0
   & $py tools\probe_delivery.py --config probe-private\local-config.json --engine-project $env:PILOT --output docs\host-compatibility.json   # 7. expect 0 (live, on 2.1.310)
   & "$env:PILOT\.recalith\bin\recalith.cmd" status                                                                  # 8. 0, or 8 while a worker runs
   $live = @('--config', 'probe-private\local-config.json', '--operator-token-file', 'C:\Code\rl-secure\eval-token.json', '--source-project', $env:PILOT, '--wheel', 'dist\recalith-0.1.0.dev6-py3-none-any.whl', '--wheelhouse', 'wheelhouse')
   & $py evals\run.py gate --mode live @live --out C:\Code\rl-gate5 --slots 6                                       # 9. 8 until labeled; 4 missing input
   Remove-Item Env:ANTHROPIC_API_KEY
   ```
   - **Note:** the probes (steps 4, 5 and 7 of a fresh pilot) write `docs\host-compatibility.json`, and a run without the key replaces the committed live delivery record with a not-run entry. Leave it uncommitted; this session reviews it for secrets, user names and machine paths before it is committed. Results directories hold machine paths and private trial content, so keep them out of git until they are sanitized. The kept R4 workspaces (`C:\Code\rl-p4`, `C:\Code\rl-p5`, `C:\Code\rl-p6`) also hold each trial installation's `provider.json`, `host.json` and `local.toml`; once read they can be deleted.
   - **Owner review:** decision 0028 item 2 binds each trial installation's host record from the pilot's live engine-mode run, instead of re-running 24 live sessions per installation.
3. **Owner decision: worker independence on native Windows** (decision 0027 item 8): start the worker outside the venv redirector's job, or accept `recovery` degraded while it runs.
4. **Watch two Windows tests.**
   - `test_concurrent_hooks_preserve_budget` failed once on a slow Windows runner (CI run 107) with a reason the assertion did not name. It now names it; attribute it on the next occurrence.
   - A Windows typed-state p95 over 5 s on a later run is read from `poll.timing` and the observer's stall records first (decision 0022).
5. **Owner decisions before publication:** the project license and the signing material (the release artifacts are unsigned).
6. **Owner question: enable the full profile for real installations?** Recommendation: not yet. Keep `FULL_RELEASE_AVAILABLE = False` in `operations/upgrade.py` (it gates both `init --release-profile full` and `recalith upgrade`) until the rest of the full release exists; without IPC wake the full profile's 30-second idle poll would miss the typed-state target. Flipping it is one line plus the CLI tests' expectations.
7. **Cut 2 continues** with the slice the owner selects next. Built: Task 5's full slice, Task 15's capsule slice and Task 17's transition. Natural candidates: the side-by-side engine switch (Task 17's remainder) or IPC wake and session mode (Task 4 full), which the full profile's defaults assume.
8. **Watch the Linux warm hook gate.** Measure run 30 missed it on Linux from one runner stall (decision 0026 checkpoint); read the next runs' degradation reasons and sample series before attributing anything to code.

**Moving to local work (Windows laptop).** The laptop runs Claude Code natively (not WSL2); decision 0027 covers that case, and the WSL2 notes below still apply to a WSL2 setup.

- **Where to run the suite and the crash families.** Prefer WSL2 (Ubuntu) with the clone in the Linux filesystem (for example `~/src/Recalith`), never under `/mnt/c`: the Windows drive is a 9p (drvfs) mount, which `identity.require_local_filesystem` refuses for a live store (`storage_failure`), and SQLite's WAL locking and fsync are not reliable there. In WSL2 the commands are the Linux ones in the checkpoints: `uv sync --locked --python 3.13`, then `.venv/bin/python -m pytest -q -rs -p no:cacheprovider`; the crash families with `RECALITH_CRASH_REPS=20` and `-k <family>`, each run with its own `TMPDIR` and, for 3.12/3.14, its own `UV_PROJECT_ENVIRONMENT`, all set inside the command that runs in the background. Native Windows is what CI's `windows` job runs (about 88 skips, about twice as long); run it locally only to reproduce a Windows-only result, from PowerShell in a clone on an NTFS drive (`uv run --locked --python 3.13 python -m pytest -q -rs -p no:cacheprovider`). The Windows-only mechanisms (Job Object breakaway, the console-handle guard test, the Windows typed-state measurement of decision 0022) are exercised only natively.
- **Where the B1 operator commands run.** In an ordinary terminal of the same OS environment as the Claude Code host the working agent uses: a WSL2 shell if Claude Code runs inside WSL2, a native PowerShell or Windows Terminal if it runs natively; never in a terminal an agent or IDE session started. Check that the environment carries no host marker (`env | grep -i claude` in WSL2, `Get-ChildItem Env: | Where-Object Name -like '*CLAUDE*'` in PowerShell) before steps 3–8. The project root must be on that environment's local filesystem. Export the key in that terminal only.
- **What stays out of the repository.** `probe-private/` (the local probe config), every real `.recalith/` private file (`provider.json`, `host.json`, `local.toml`, `state/`, `spool/`, `run/`, `backups/`, `exports/`, `runtime/`), operator token files, API keys and `.env` files, raw transcripts (for example under `~/.claude/projects/`), and measurement or probe outputs that hold machine paths or user names until sanitized. Write measurement and probe output to a scratch directory first; commit only sanitized evidence. The root `.gitignore` already excludes `probe-private/`, `.env*`, `/.claude/settings.local.json` and the private `.recalith/` paths; check `git status` before every commit anyway.

Full-only work stays pending:

- Task 13: `--shared`, `--autostart`, installed private-path rules;
- Task 14: Codex, generic JSON and MCP;
- Task 15: transfers (export, import, the Breadcrumbs importer; capsules are built);
- Task 17: the side-by-side engine switch between two releases, same-profile upgrades, schema migration of older stores, OS startup entries (the preview-to-full transition is built, decision 0026);
- Task 18: the 48-scenario three-trial comparison, the held-out corpus and its independent authorship, the Breadcrumbs and notes baselines.

### 2026-11-09 — Audit Phase 4: public-repository hygiene (`0.1.0.dev15`, decision 0047)

Phase 4 of the [fix plan](../audits/2026-11-06-fix-plan.md), all eight items, in a web session. No engine behavior changed; the wheel's bytes changed (SPDX headers), so the version did.

- **sdist (REL-2):** an anchored include list (`src/recalith` and eight root files; no docs, evals, tests, tools, workflows or packet); `build_release.py` inventories the sdist and fails on a stray or a foreign notice. Built here: `problems: []`, the sdist holding `src/` and the root files only.
- **Headers (REL-8):** `# SPDX-License-Identifier: GPL-3.0-only` on all 238 modules plus the generated wire tables; the foreign-copyright check flags a notice that does not name Recalith; the holder line waits for the owner.
- **Community (REL-4):** SECURITY, CONTRIBUTING, CODE_OF_CONDUCT, CHANGELOG (dev0 to dev15 with their decisions), issue and PR templates, Dependabot (github-actions, uv).
- **OPERATIONS (REL-5):** §7 what is stored and sent, §8 uninstalling, §9 the compatibility promise for preview stores; README links them.
- **BUILD_PROGRESS (REL-3):** 78 lines: the current state (Implementation through decision 0047, rows 13 and 18 refreshed, the acceptance line names the tenth gate's pass and what no live run has observed), the work packages, the B1 blocker and a four-item handoff; the 61 checkpoints, the per-task B1 history and the old handoff moved verbatim to `docs/history/build-log-2026-10.md` and this file.
- **Workflows (REL-9):** every action pinned to a commit with its version; concurrency groups (cancel on ci and release, queue on measure); the attestation job scaffolded behind a dispatch input, off.
- **The packet (REL-11):** `MANIFEST.json` and `review/` under `docs/history/packet/` with a README; AGENTS, the handoff and the starter packet repointed.
- **Probes (PROV-5/6/7):** the console line carries `failed_checks` and a TLS hint names `SSL_CERT_FILE`/`SSL_CERT_DIR`; the tracked endpoint is scheme plus a host hash, no path; `ApiEndpoint` refuses a credential-shaped path segment; the sanitizer replaces any home, UNC path and email.
- **Gate record (EVAL-1):** `versions.inputs` digests the 12 scenarios, 4 overlays, the oracle module, 3 workload days, the recorded curator and the scripted agent; a live gate from a dirty tree is refused unless `--allow-dirty`, recorded.
- **Tests added:** sdist inventory (two), sanitizer patterns, probe origin and console, endpoint path, gate inputs and refusal.
- **Checks:** schema and wire drift 0, `requirements.lock` unchanged, `tools/release_checklist.py` `problems: []`, `ruff --select F,E9,B` clean. Full suite (`python -m pytest -q -rs -p no:cacheprovider`, Linux, Python 3.13.18, with `RECALITH_TEST_WHEEL`/`RECALITH_TEST_WHEELHOUSE` set): 1,581 passed, 17 skipped, 0 failed in 38 min 40 s, exit 0; the skips are environment-only. No `src/`, `tests/` or `evals/` file changed while it ran.
- **Next action:** Phase 5, the owner's (OPERATIONS §4 as a stranger, the live gate from a clean tree, the publication decisions).

### 2026-11-09 — The Windows launcher parses (`0.1.0.dev16`, decision 0048)

Found by reading CI after pulling: `ci` and `release-artifacts` had been red on `main` since `412cb9e` (`0.1.0.dev14`); the Phase 3 and Phase 4 checkpoints recorded the suite on Linux only.

- **Windows `core` job, 84 failures, two causes.** 83: decision 0046's bootstrap hint put `( … )` inside the `.cmd` launcher's `if not exist "%PY%" ( … )` block; cmd.exe ended the block at the hint's `)`, so every `recalith.cmd` invocation exited 255 with `. was unexpected at this time.` (82 guarded-form cases of `test_cli.py`, the missing-runtime case of `test_installations.py`). 1: the notice test expected the POSIX spelling `recalith status`; the Windows notice names `recalith.cmd status`, as decision 0046 intended, and was complete (pytest had shortened the string in its message).
- **`release-artifacts`:** the offline walk used the `cp313` wheelhouse with the runner's `python3`, now 3.14; the bootstrap refused correctly and named the mismatch.
- **Fix:** the `.cmd` launcher uses `goto` and has no block; the release walk, README and OPERATIONS §4 (Linux) derive the wheelhouse tag from `python3`. Tests: the refusal under paths holding `(x86)`, `R&D (copy)` and `a)b`; no Windows launcher line opens or closes a block; the launcher digest re-pinned; the notice test expects its platform's spelling.
- **Checks (native Windows 11, Python 3.13.15):** `python -m pytest -q -p no:cacheprovider tests/integration/test_installations.py tests/integration/test_claude_adapter.py tests/integration/test_cli.py` → 272 passed, 25 skipped, exit 0 (the same files had 84 failures on the Windows CI runner before). `tools/generate_schemas.py --check` exit 0; `tools/release_checklist.py` `problems: []`, verdict `blocked`; `ruff --select F,E9,B` clean. `tests/unit/test_eval_harness.py::test_scripted_smoke_run_writes_labeled_trials` fails on this laptop with and without the change: the pytest temp directory under `AppData\Local\Temp` plus the trial's `.claude\projects\…` name passes the 260-character path limit (`WinError 3`); the Windows CI runner's shorter paths pass it. The full suite runs in CI on this push.
- **Next action:** CI green on Windows; then the Dependabot bumps as one commit (decision 0048's checkpoint below), then Phase 5.
