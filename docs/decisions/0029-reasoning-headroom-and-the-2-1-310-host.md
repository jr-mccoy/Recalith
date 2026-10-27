# Decision 0029: Reasoning headroom, worker temporary files, handler error types, the macOS group kill and Claude Code 2.1.310

Status: accepted (Task 4/7 engine slice and Task 3b capture review, preview; the reasoning headroom approved by the owner on 2026-10-26) · Date: 2026-10-26 · Engine: `0.1.0.dev1` · Observed: the first live gate (2026-10-23 to 2026-10-26), the two pilots' stores (read-only), and Claude Code 2.1.310 on native Windows in request capture (loopback scripted endpoint, placeholder key, private `HOME`; this session's credentials and proxy never used)

## Context

The first live gate failed (BUILD_PROGRESS, 2026-10-26 checkpoint; [its record](../evaluations/preview-live-2026-10-26/report.md)). Three of its findings were in the engine, not the harness:

- **Reasoning filled the output allowance.** The curator model reasons by default, and its reasoning counts against the same `max_tokens` cap as the visible reply (decision 0027 item 9). Of 16 `update_task` calls, 12 stopped at the 1,500-token cap (`output_cap_reached`), and each retry re-sent an input of about 41,000 reported tokens. For the other purposes, reported output was 3 to 4 times the visible reply. In the second pilot's store, an `extract_claims` call reported 4,112 output tokens against a visible estimate of 1,161, which is about 2,950 tokens of reasoning. The `update_task` calls that did finish reasoned about 1,000 to 1,100 tokens.
- **A hook-started worker without a temporary directory fails every typed reduction.** The first pilot's ingest jobs all failed. When the hooks' environment carried no `TEMP`/`TMP`, SQLite on Windows fell back to the Windows directory, which a normal user cannot write. The harness gives its agents a temporary directory now (decision 0028 item 4), but a real host that passed none would hit the same failure. Reproduced on this laptop with every other variable removed: a sort that spills past the page cache and a statement journal both fail with `unable to open database file`, and both succeed once the temporary files are kept in memory.
- **The failure was recorded only as `handler_error`.** The exception type was lost, while the model lane already records `lane_error:<type>`.

The host also updated itself to 2.1.310 during the run (decision 0028 item 12), so the pilot's certification no longer matches the installed host.

CI on the first build of these changes found a fourth engine fault, on macOS only. `test_runtime_check_refuses_a_recorded_route_of_another_backend` failed once with `PermissionError` out of the timeout kill (`controller/launch.py`); the same commit passed on macOS in the branch run. In its hang case the HTTP child's socket timeout equals the launch deadline, so the child can exit just as the launcher kills its process group. Darwin refuses to signal a group whose members have all exited but are not yet reaped (`EPERM`, not `ESRCH`). The kill did not expect that, and the liveness check counted such a group as alive.

## Decisions

1. **Reasoning headroom (SYSTEM_SPEC §6.3 amended).** `REASONING_HEADROOM` is 6,000 tokens, the same for every model purpose.
   - The provider's hard output cap is the purpose's allowance plus the headroom: `update_task` 7,500; `build_episode` and `extract_claims` 14,000; `review_claims` and `revalidate` 9,000. This is `max_tokens`, or the configured output-cap field.
   - The reservation's output estimate is that cap, because it is what the provider may charge. `BudgetReservation.reasoning_headroom` records it.
   - Unchanged:
     - the decoded body cap, 3 × the allowance;
     - the request's `limits.reserved_output_estimate`, which the model sees: still the allowance;
     - the reported total is still charged, reasoning included. A smaller known usage releases the rest; unknown interrupted usage keeps it.
   - The headroom is flat because the measured reasoning did not grow with the allowance. It is about twice the largest reasoning observed. At the measured 150 output tokens a second or so, a full 14,000-token reply takes about 95 seconds, inside the 120-second process timeout.
   - The daily pools are unchanged. The next run's workload days measure them again. Reservations near the end of a pool are larger now, so up to one cap's worth of a pool can be left unusable.
   - A reservation stored before this decision has no headroom field. It reads as 0, so its limit is the allowance alone.
2. **SQLite keeps its temporary files in memory.** Every store connection sets `PRAGMA temp_store = MEMORY`: statement journals, sort spills and TEMP tables, including the integrity scanner's row capture. The store runs no `VACUUM`, and the memory involved is small. The hooks' read-only snapshot connections are unchanged; they run on the audited fast path and spill nothing.
3. **A failed deterministic handler names its exception type** as `handler_error:<ExceptionType>` (64 characters at most; no message text), the same form as `lane_error:<type>`.
4. **Engine version `0.1.0.dev1`.** Items 1–3 and 6 change the certified wheel. The bootstrap refuses a different artifact under a version it has already provisioned, and in-place upgrade is not in preview, so the live re-certification needs a fresh pilot provisioned with the new wheel. Item 6 was added and the wheel rebuilt before any installation was provisioned with the first `0.1.0.dev1` build, so the version did not move again.
5. **Capture certification of Claude Code 2.1.310** (Task 3b; decision 0019 procedure).
   - Captured with `tools/capture_claude_fixtures.py` → exit 0. It observed the same 12 events as 2.1.309, removed 23 owned hooks and preserved the unrelated settings.
   - Reviewed against the 2.1.309 capture on the same laptop:
     - the same event sequence and per-scenario counts in all four scenarios;
     - identical field sets and value types in every payload, compared recursively;
     - identical transcript record types, keys and skeleton fields;
     - manifests that differ only in times and session identifiers.
   - Values differ only in identifiers and timings (two digits of a test-run duration, at the same lengths) and in the persisted-output file name.
   - Seen before: one recorder note, the transcript file not yet existing at the first `PreToolUse` of the lifecycle scenario. The same timing varied between 2.1.306 and 2.1.309 in two other scenarios. It is when the host first writes its transcript, not a format change.
   - The adapter maps every record identically to 2.1.309 (the subagent scenario as a multiset), and the transcripts parse to the same record counts.
   - 2.1.310 joins `claude_capture.CERTIFIED_VERSIONS`, and its fixtures are `tests/fixtures/hosts/claude/2.1.310/`.
   - This is not a live certification. The live delivery certification of 2.1.310 is the owner's engine-mode run on the fresh pilot (`tools/probe_delivery.py --engine-project`), as for 2.1.309.
6. **A process group whose members exited unreaped is settled, not raised (macOS).**
   - The tree kill treats `EPERM` from `killpg` as possibly exited members. It reaps the leader and checks liveness as before, then moves to `SIGKILL` and the final check. It never raises out of the launch.
   - When a liveness probe is refused, the members' states come from `/bin/ps` (`-A -o pgid=,stat=`, `LC_ALL=C`). The group is alive while any member is not a zombie. If `ps` cannot be read, the group counts as alive, so a refused group is never reported cleaned.
   - Linux still reads `/proc`, and Windows still uses the Job Object; neither changes.
   - The probe tools' copy (`tools/probe_common.py`) gets the same change.

## Tests

- `test_reservations_hold_the_reasoning_headroom_and_keep_the_body_cap` (contracts; including the stored reservation without a headroom field).
- `test_full_reservation_arithmetic_with_reasoning_headroom`, and the pool tests rewritten for the new reservation sizes. Calls that finish are settled at their usage, as the worker does; the protected-pool, borrowing, input-cap, budget-exhaustion and declaration tests seed them that way.
- `test_certified_api_route_reserves_charges_failures_and_backs_off` now checks that each request's `max_completion_tokens` equals its reservation's output limit.
- `test_exhausted_budget_pools_are_reported`. After eight 14,000-token extractions, the ordinary pool still serves a 7,500-token task update, so health does not call it exhausted until a task update no longer fits. It always tested with the smallest ordinary call; only the arithmetic moved.
- `test_store_connection_policy` (`temp_store`), and `test_store_writes_need_no_temp_directory`. The latter is a subprocess without `TEMP`/`TMP`. Against the tree without item 2 it fails on this laptop with `unable to open database file`; with item 2 it passes.
- `test_a_handler_failure_names_its_exception_type`.
- `test_a_group_whose_members_exited_unreaped_is_settled_not_raised` and `test_ps_group_states_reads_one_group`. The first refuses every signal with `EPERM`, as Darwin does, and checks that the kill reaps and returns, that a live refusing member still counts and that unreadable states are never called dead. The second runs the real `ps` where it exists and parses a fixed listing. Without item 6 both fail on this laptop. The race itself was seen once in macOS CI and is not forced here.
- `test_reviewed_2_1_310_fixtures_map_like_2_1_309`, `test_reviewed_2_1_310_transcripts_parse_like_2_1_309`, `test_reviewed_2_1_310_fixtures_are_sanitized`.
- The deny-spelling test is re-pinned to `0.1.0.dev1`; the launcher digests stay pinned to the texts of `0.1.0.dev0`.

## Limits

- The headroom is sized from one gate run and two pilots. Each live trial and workload day now records per-purpose calls at the cap (decision 0028 item 15), so the next run shows whether 6,000 is enough.
- The daily input pool, not the output pool, ran out first on two of three days. Removing the capped retries should help, but no budget default changes here.
- The budget summary's per-dimension `exhausted` still means nothing left (remaining ≤ 0). The refusal reason and health's `exhausted_pools` report a pool that can no longer fit its smallest call. With the larger reservations those two can differ by up to one cap.

## Consequences

The wheel changes, so the owner provisions a fresh pilot from `dist\recalith-0.1.0.dev1-py3-none-any.whl`, then certifies its route and runs the engine-mode delivery probe on the installed 2.1.310 (BUILD_PROGRESS handoff). The live gate's `--source-project` and `--wheel` then name that pilot and wheel. The first pilot (`C:\Code\rl-pilot`, engine `0.1.0.dev0`, host record 2.1.309) stays as it was, as the record of B1's first certification.
