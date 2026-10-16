# Acceptance Tests and Evaluation Protocol

Revision 1.3 • 2026-10-15 • All numerical values below are proposed release gates, not measured results.

## 1. Evaluation principles

Test capture, memory formation, relevance, maintenance, and agent outcomes separately. A record being written does not demonstrate useful learning; a warning being delivered does not demonstrate a prevented failure. Deterministic fixtures validate mechanics. Live models validate extraction and reasoning. Live working agents validate practical benefit.

Freeze fixtures, gold labels, and scoring before comparing model or policy variants. Do not silently rewrite baselines to pass a change. Label the current baseline, candidate version, prompt digests, adapter versions, models, store schemas, and environment. Preserve failed examples as future regression cases after the held-out evaluation closes.

Use only authorized project data. Private real transcripts stay in local test storage. The public test repository contains synthetic or explicitly approved fixtures. Provider calls made by the evaluation suite require the same configured routing as product use. Test-mode budget increases must be explicit.

## 2. Deterministic acceptance matrix

All 73 cases are required for the full release. Preview requirements and explicit partial variants are in §2.1; unavailable features are not counted as passed. Implementation task ownership is listed in the plan. The fixtures exercise actual service operations and serialized host payloads, not mocks of the policy being tested. A10/A12 and other model-influenced cases have a deterministic mechanics form using recorded accepted/rejected proposals, and a live quality form in §5. Passing the former does not prove that a live model finds correct task boundaries or narrative links. A27/A61 similarly separate harness mechanics from real-host visibility certification.

| ID | Scenario | Exact required behavior |
|---|---|---|
| A01 | Two installations have identical record titles, paths, and opposite build commands | Query A never returns B's record ID, text, evidence, or vector candidate; repeat in reverse |
| A02 | Independent releases/schemas and preview-to-full upgrade | A and B remain isolated during recovery/upgrade. Full transition preserves A project/installation/record/root IDs and live evidence beyond day 181, handles capsules or retained pins without new support, keeps explicit overrides, updates capabilities honestly, and never modifies B |
| A03 | Directory move, independent clone, and explicit worktree attachment | Move requires local rebinding; clone has a new installation ID; only an explicit attachment shares the owner's store |
| A04 | Another installation ID is supplied in event, operation, or import payload | Normal paths reject it; explicit import stores origin metadata but uses destination identity |
| A05 | Crash after segment publication but before cursor write | Recovery ingests exactly one event and advances the cursor without duplicate support |
| A06 | Crash after DB ingestion but before segment deletion | Replay creates no duplicate event/job; segment is eventually removed |
| A07 | Disk full or permissions failure before durable publication | Receipt is `not_captured`, cursor does not advance, host continues, health reports a gap |
| A08 | Transcript truncation, file replacement, partial last line, late result | No invented event; full later line is read once; result joins the correct call; gaps are explicit |
| A09 | Overlapping producer segments and duplicate host event IDs | Same content is deduplicated; changed content is retained separately in `source_conflicts`, with the original event unchanged and dependent caution suspended |
| A10 | Two tasks progress concurrently in the same project | Each objective, next action, and pending result stays with its task |
| A11 | A task is idle, a test passes, or a commit appears | No unsupported completion; idle becomes paused; task closes only with relevant completion evidence |
| A12 | A failing command is fixed across chunk/compaction boundaries | One connected episode contains the original failure, change, later result, and uncertainty |
| A13 | Expected red test, denied tool, interruption, and ordinary search miss | No generic failed-approach lesson is automatically created from the exit status alone |
| A14 | Model cites a nonexistent event or altered quote | The affected operation group is rejected; unrelated valid groups can apply |
| A15 | Real event is cited for an unsupported causal explanation | It cannot enter as `observed`; inferred admission requires review and scoped wording |
| A16 | Agent repeats a memory; three subagents repeat the same source | `last_supported_at` and independent-root count do not advance |
| A17 | A new test confirms a memory after it was retrieved | A genuinely new observation class may add support; an unchanged rerun stays in its existing class; retrieval itself adds none |
| A18 | Same proposition under different branches or dependency versions | Both may remain active in their own scope; no false global contradiction |
| A19 | Guarded correction and separately reviewed decision replacement | Correct invalidates the expected target and creates a replacement candidate in one transaction without a model call; zero budget still suppresses old guidance. The replacement stays candidate until its own required review passes; stale revisions fail atomically |
| A20 | Relevant source file changes while curation is running | Read-set check refuses stale application and queues bounded re-evaluation |
| A21 | Old worker finishes after its lease expires | Fencing prevents its result from applying; newer completion applies once |
| A22 | Controller sees its own generated record on the next sweep | No unbounded extraction/review loop and no new independent support |
| A23 | High-overlap claim has unknown applicability | It may be labeled context but cannot produce condition-specific caution |
| A24 | Retired/quarantined records or a linked task placeholder rank highly | Exclude from current guidance before limits. Linked current head has no pending_actions or next_action and supplies no tentative actionable context; use the nonlinked target binding. Explicit history remains clearly historical |
| A25 | Packet cache predates an invalidation/forget at the final delivery fence | A change committed before the fence excludes old guidance; stdlib fallback or degraded output occurs. A change after the fence is recorded as an in-flight race, not claimed retractable |
| A26 | Warning suppression and missing pre-action fallback | Unchanged delivery is suppressed; changed condition/revision may resurface. Eligible substituted cautions share one ≤400 allowance per ordinary prompt, ≤1,400 total; no bonus without a caution or per-item multiplier. All tokens count against session limits; restoration stays ≤2,000 including cautions |
| A27 | Fresh agent starts and compacts under each configured host | Start and prompt must pass real nonce certification for readiness. Pre-action and compaction injection are probed/reported independently; missing optional paths use specified prompt fallback and do not fail core readiness. Unknown required paths do |
| A28 | Curator inherits host markers or triggers host customizations | Clean and host-marked parent fixtures produce the same certified isolated launch with registered host markers removed and fresh curator marker set. No extra auth route/customizations/tools are inherited. Recursive source capture stays suppressed, public CLI is never sanitized into operator authority, and failed effective isolation makes backend unavailable |
| A29 | Provider auth route changes, CLI missing, account limited, or malformed output | No cross-provider fallback; capture remains live; jobs queue/back off; health names capability loss |
| A30 | Provider hangs, floods output, or returns a normal large episode | Bound process tree, 256 KiB raw stdout and 64 KiB stderr; validate the decoded original JSON body separately. Accept a valid 15 KB episode within its 24,000-byte allowance despite a larger host envelope; reject either cap overflow without clipping and charge failures |
| A31 | Daily invocation or estimated-token budget is exhausted | No additional model invocation starts; ordinary capture and deterministic retrieval still work |
| A32 | External issue text or repo file says to override policy | It remains data; cannot change permissions/provider/config or acquire user authority via paraphrase |
| A33 | Paths contain traversal, symlink/junction swap, case variation, Unicode, or spaces | Authorized equivalent paths work; boundary escapes are refused without reading target content |
| A34 | Secret appears in command arguments, tool output, or model proposal | Stored/transmitted normalized text is scrubbed or operation refused; error logs do not repeat the secret |
| A35 | Age retention of pinned/unpinned evidence and permitted support loss | At day 181 preview expires only eligible unpinned payloads; referenced decision, typed declaration and lesson keep evidence/strength, with no retention-caused guidance loss. Test active/disputed/candidate claim owners, open/paused work, transitive/shared roots, concurrent reference versus expiry, release of last owner and forget overriding pins. Full preserves sufficient capsules or retains pins; absent imported/removed support still downgrades honestly |
| A36 | Operator forgets a task whose text appears in claims, episodes, revisions, and caches | Covered derivative bodies are purged or content-free quarantined in the transaction; reconstruction is later reviewed work. Known source replay cannot resurrect them; all external logical cleanup is tracked before delivery resumes |
| A37 | Restore backup created before a forget request | Current tombstones apply before serving; forgotten text does not reappear; affected backups follow policy |
| A38 | Import same knowledge twice from the same origin | Import is idempotent; repeated imports do not increase corroboration |
| A39 | Import contradictory knowledge from a different project | Explicit import is required; origin retained; destination policy handles dispute; no identity adoption |
| A40 | Corrupt backup or interrupted upgrade/profile transition | Reject corrupt backups and unsupported schema writes without damaging current live state. Full tests failure at backup, chain baseline, capsule/link preparation, capability registration and activation: serve a complete previous preview or completed full state only, preserving newest tombstones. Failed capsule sufficiency retains evidence; downgrade by flag is refused |
| A41 | Worker and CLI write concurrently during projection build | Transactions preserve revisions and guidance epochs; guidance changes invalidate packets, receipt-only revisions do not; served items still belong to a consistent eligible snapshot |
| A42 | Source assertion and generated summary are changed by manual export editing | Import requires original revision/digest; modified text becomes a new assertion, never original evidence |
| A43 | An admitted failure is followed by a certified matching success | Before any model invocation, ingestion atomically records the counter-observation as context, sets needs_revalidation, advances guidance epoch, and queues revalidation. Test zero budget, cross-session same family, no dependencies, known older replay, unknown order, unknown family/working directory, identical argv in different package directories, and different conditions. No automatic assertion that historical failure is false; dependency-free failure never earns caution via empty conditions |
| A44 | An unresolved user-intent conflict persists | One relevant question is surfaced without blocking; no invented resolution or repeated prompt spam |
| A45 | Persistent worker host termination, suspend and backlog | Test the worker actually started from a registered host hook, not only a terminal-started worker. It closes inherited handles, uses the allowlisted environment and certified detachment, survives SessionEnd/host termination where supported, and reports degraded independence otherwise. Resume coalesces jobs with no budget burst; typed ingestion stays responsive while model work is pending |
| A46 | Only MCP is installed and the agent never calls it | Health does not claim automatic capture/delivery or `autonomous_ready` |
| A47 | Unknown host version or unsupported transcript field | Conservative capability state, explicit coverage gaps, no fabricated normal parsing |
| A48 | Normal deletion versus logical forgetting | Archive preserves history; forget removes covered content and carries content-free suppression metadata |
| A49 | Two distinct payloads claim the same source event key | Original event remains immutable; each distinct conflicting digest has one separate conflict row and health entry; replay is idempotent |
| A50 | Reservations, bounded review batches and declaration priority | Preserve ordinary/protected pool rules, separate wire/body limits, fitting five-candidate two-call example, all expansion charges, and the 48-call full-reservation arithmetic. With ordinary and declaration/correction reviews queued, code-assigned high-priority review wins next eligible launch without killing an in-flight call; mixed batch gets its highest applicable priority. Exhaustion still blocks all new calls; unextracted text is not treated as a ready declaration |
| A51 | Stable declaration, file/config/environment dependency, failure lesson, and cyclic claim dependency | Dependency-free declared decision/preference is stable; all listed dependent/failure/unknown cases are volatile; due times match 180/30 days |
| A52 | Certified assertion/runtime sources and executable upgrades | Only registered parsers satisfy observed mappings. Runtime values require declared config or certified observed result tied to workspace/executable; never recalith Python. A version observed before a registered executable fingerprint change, or bound to a different fingerprint, is stale and evaluates unknown until refreshed. Unknown binding and untrusted assertions cannot certify a value; hooks never launch probes |
| A53 | Clone lacks runtime; local/shared integration is installed then removed | Hook returns nonblocking empty success without downloads/repeated hints; local is default; removal preserves unrelated/modified entries |
| A54 | Environment contains secrets, absolute paths, unregistered keys | Values are dropped before spool/provider transmission; only registered normalized scalars remain; missing predicates are unknown |
| A55 | Retained quote begins at offset 900 with Unicode after source expiration | Capsule returns the exact original substring by origin locator/digest; link redirection and expiry are atomic; old offsets are not applied to capsule text |
| A56 | Unchanged test reruns, forwarded subagents, new experiments, or partial dependencies | Count canonical classes, not event IDs; unchanged/forwarded/unknown evidence cannot manufacture corroboration; contradictory reruns remain instability |
| A57 | Task boundaries, resumed sessions, and delayed tool results | Versioned binding preserves immutable events and call/result pairs. At zero model budget exactly one eligible prior task plus three compatible path actions yields a reversible provisional link; two candidates/pivot/reset do not. Linked placeholder is not a second active task. Coding src/tests/docs transitions do not propose a disjoint boundary; five truly disjoint actions may |
| A58 | Deadline, WAL/SHM, live checkpoint and hook fault paths | Only stdlib/audited fast imports; read-only snapshots, no database write transaction, recovery/checkpoint, model/network call or lock wait. Test crashed-worker WAL with present/missing/unreadable SHM **and a live worker mid-checkpoint**; busy snapshot degrades immediately with fresh final fence. Retain shared 250 ms budget, overlay→wake→dependency shedding, mandatory reservation/fence, unbound workspace lookup and truthful capture-overrun behavior |
| A59 | Two hooks race before worker ingests receipts or failures | Session lock preserves reservations/outcomes; suppression sees emitted pairs; the next matching pre-action sees the typed failure; crash uncertainty never counts as confirmed emission |
| A60 | Declarations, reviewer rationale and bounded objections | Every durable declaration route requires review; pasted content gains no authority. Strip proposal reasons/rationales while preserving exact evidence. Missing/duplicate/stale verdicts cannot activate candidates. If actionable revise objections cannot fit, return reject/review_capacity, keep candidate unadmitted, and never truncate a revise, infer falsity, or create an unbounded retry loop |
| A61 | Early stub and production four-path nonce probes | Task 0b before Task 1 tests harness mechanics and real installed-host start/prompt/pre-action/compact feasibility without an engine. Each available path requires 3/3 positive and 3/3 negative controls, exact response evidence, no contamination or stdout-only pass. Required start/prompt failure blocks that host route; optional gaps are explicit. Task 13/14 must repeat with the real engine; a stub pass is not product certification |
| A62 | Feature branch merges unchanged dependencies; same branch later changes them | First lesson remains applicable across branches; changed/missing dependencies suppress caution regardless of branch name; explicit branch constraints still apply |
| A63 | Forget removes one of several support roots while model budget is unavailable | Old derivative body is purged to quarantined placeholder before commit; it stays unserved until a new reviewed revision from surviving roots exists |
| A64 | Fresh post-forget backup succeeds or fails | On success verify it before deleting affected old backups; on failure still delete affected backups, retain purged live state/ledger, and report recovery degradation |
| A65 | Private-path capability and out-of-band mutation detection | Preview probes/reports private-path support and chain unavailability; command protections still pass A73. Full tests installed supported path rules without breaking hooks, incremental chain range/coverage, full-row detection of an unchanged-row edit, and an honest baseline when adding chain to a preview store. Whole-chain same-user rewrite remains outside protection |
| A66 | Failure/success debounce, unknown families and expected-red intent | Same task/action family success before six relevant events or ten minutes resolves despite changed dependencies. Null family only becomes due by count/time and never matches success. Normalized expected_red=true is invalid in v1; untrusted raw hints normalize false with coverage, and semantic A13 still rejects general lessons from exit status alone |
| A67 | Inherited environment, configuration and auth affect curator launch | Test clean and host-marked parent through hook→worker→curator. Actual child environments contain only registered platform/selected-auth/config keys and the correct fresh worker/curator marker. Host/nested-session markers and unrelated credentials are absent; auth route unchanged. Effective hooks/plugins/native memory/managed MCP still fail isolation if present; marker removal alone never proves no tools |
| A68 | Very long tool output has its failing assertion at the end | Both bounded head/tail and certified error signature survive with offsets/coverage; total event cap and Unicode validity remain enforced |
| A69 | Every strength/freshness/evidence/status combination reaches the compiler | Automatic context follows SYSTEM_SPEC §8.2 table; expired/redacted inadequate support is omitted; tentative/conflict labels are preserved |
| A70 | PowerShell/cmd/POSIX parsing ambiguity or a host argument array | Certified arrays are used verbatim after registered normalization; ambiguity yields unknown, never guessed executable/action semantics |
| A71 | Same origin is imported into different fresh installation IDs | Imported stub IDs and origin/root classes remain stable; local ownership stays separate; reimport cannot increment independent support |
| A72 | Machine consumers inspect reasons, unavailable capability, or failed capture | First `why` item is a registered reason code; `observe` returns 7 for `not_captured`, partial capability returns 8; host hooks still return nonblocking success |
| A73 | Administrative guard, pre-init tokens and internal startup | Marked host/worker/curator processes get exit 6 for all guarded forms, including token commands and profile flags, even with TTY+token. No requested admin effect; content-free audit when store available. Unmarked TTY can create a standalone token before init; noninteractive init with that provisioned file succeeds once and never overwrites existing state. Missing/invalid/revoked supplied token is 6, not 2; noninteractive minting refuses. Registered hook startup succeeds without operator CLI. Marked IDE error explains the external-terminal route; pre-init refusal creates no store |

Cases A01–A09, A16, A19–A22, A24–A25, A28–A34, A36–A42, A46–A47, and A49–A73 (their deterministic mechanics forms) are blocking correctness gates: zero violations across the defined deterministic corpus and stress repetitions. Passing does not prove absence of failures outside that population.

### 2.1 Release-profile coverage

The `claude_preview` gate includes **67 case IDs**: all A01–A73 except A38, A39, A42, A46, A55, and A71. The six excluded IDs depend on transfer/capsule/MCP components. They remain explicit unavailable capabilities and pending tests. The included cases below have named partial variants; every other included case applies in full to preview. Do not claim 67 complete full-feature cases or mark deferred variants passed.

| Included ID / feature family | Preview-required variant | Full-only variant |
|---|---|---|
| A02 | Independent pinned build/schema fixtures and recovery of A leave B untouched | Live side-by-side upgrade and in-place preview-to-full transition |
| A03 | Directory relocation/rebinding and independent clone | Explicit workspace attachment/project fork |
| A04 | Reject foreign IDs in ordinary events/operations | Explicit import-origin remapping |
| A27, A47, A61 | Claude exact-version coverage; start/prompt required, two optional paths reported | Same certification for Codex |
| A35 | Live-reference pins and unreferenced expiry at day 181; explicit loss/forget handling | Exact capsule compaction/redirects, retaining pins on insufficient preservation |
| A40 | Corrupt backup rejected; unsupported schema writes refused; current live store preserved | Interrupted upgrade/profile-transition rollback with current tombstones |
| A45 | Hook-started persistent worker lifecycle/environment, polling/restart/suspend and budgets | Session worker and IPC-wake variants |
| A53 | No-runtime clone, local install/remove, unrelated configuration preserved | Shared tracked configuration |
| A58 | Preview deadline, polling/no-IPC, WAL/SHM and fallback paths | Additional IPC deadline/host variants |
| A65 | Private-path probe/coverage report; revision chain explicitly unavailable | Installed private paths and incremental/full chain/row verification |

A61 includes the early Task 0b feasibility report and later production recertification. A37 restore **is retained**: forgetting must remain effective after backup recovery. A73 and profile-aware health are mandatory before preview readiness. Deferred administrative commands still pass the A73 early-refusal branch; unmarked calls return `capability_unavailable`. Each manifest entry records profile, capability, variant, owning task, platform and status. The complete 73-ID inventory remains covered in the manifest even while full-only variants are pending.

## 3. Fixture families

Create sanitized fixtures under `tests/fixtures/`:

- `hosts/claude/<version>/` and `hosts/codex/<version>/`: start, prompt, tool, late completion, compaction, subagent, normal end, interrupted end, and malformed payloads.
- `events/`: causal chains, parallel tasks, identical source IDs, non-ASCII text, large outputs, expected test failures, rejected calls, and explicit corrections.
- `providers/`: accepted proposals, fabricated references, false entailment, dependency groups, evidence requests, timeout/usage/error responses.
- `stores/`: populated installations with conflicts, old schemas, tombstones, imported lineages, stale projections, and expired supporting events.
- `injection/`: hostile instructions in files/issues/results, agent paraphrases, user quotations, and benign imperative preferences.
- `forgetting/`: source-range replay, derived summaries, backups, exports, and new independent statements after deletion.

Maintain a coverage manifest mapping every acceptance ID to test functions, platforms, fixture versions, and implementation task. CI fails if a required case loses its mapping or is skipped on a required platform without an explicit unsupported-feature result.

## 4. Failure-injection protocol

Instrument deterministic failpoints around spool temp write, flush, rename, cursor advance, database begin/commit, proposal persistence, lease renewal, operation application, projection publication, backup completion, and migration switching.

At each failpoint kill the process, restart, and compare the resulting authoritative state with a reference run. Normalize timestamps and generated IDs only when those differences are irrelevant. Assert identical evidence-root counts, current claims, task states, and operation effects. At least 20 interleavings per transaction/failpoint family in nightly CI; 100 for release candidates. Also inject disk/permission failures and invalid JSON.

Use native Windows, macOS, and Linux runners for process locking and lifecycle behavior. WSL is an additional environment, not a substitute for native Windows. Do not weaken guarantees to make mocked lock tests pass.

## 5. Live extraction and lifecycle corpus

Freeze 48 multi-session scenarios across three independent projects: two coding projects and one generic planning workspace. At least 12 scenarios must be held out from prompt tuning and excluded from the development smoke subset. Source those 12 from sanitized authorized real Breadcrumbs sessions, or from an independent scenario author who has not read SYSTEM_SPEC §7. Record which route, authorship, sanitization, and any designer involvement were used; if unavailable, label the held-out independence limitation rather than asserting independence. Distribute across:

- 24 learning/continuity scenarios: failures with alternatives, successful procedures, direct decisions, task restoration, and long-running threads.
- 12 revision scenarios: changed conditions, legitimate retries, conflicting evidence, and explicit corrections.
- 12 quiet/control scenarios: routine work, unsupported inference, irrelevant memories, expected test failures, and cross-project near-matches.

Gold labels specify which observations are exact, which lessons are supported, acceptable uncertainty, intended scope, prohibited generalizations, and expected retrieval points. Two independent human reviews of disputed gold labels are preferred; if only one reviewer is available, report that limitation. A model judge may assist but does not solely adjudicate fabricated support or source fidelity.

For each candidate model/prompt pair, run three fresh trials per scenario. Report all trials and variance, including failure and abstention rates. No future-session evidence enters an earlier session's retrieval store.

### 5.1 Initial quality gates

| Measure | Target |
|---|---:|
| Supported durable-memory precision | ≥ 95% of admitted claims |
| Useful durable-memory recall | ≥ 85% of labeled reusable memories |
| Failed-approach recall | ≥ 90% of labeled instructive failures |
| Incorrect confident guidance with material consequences | 0 in release corpus |
| Required conflict/uncertainty preservation | ≥ 95% |
| Legitimate retry incorrectly discouraged | ≤ 5% of retry scenarios |
| Irrelevant caution on quiet/control scenarios | ≤ 5% |
| Routine operations requiring human memory maintenance | 0 |

Precision must not be optimized by producing almost nothing; recall and quiet-case performance are simultaneous gates. Abstention is appropriate for unresolvable uncertainty but counts as missed recall when the evidence was sufficient. Review threshold changes require a new versioned evaluation run.

### 5.2 Operational measures reported on every release run

| Measure | Exact reporting |
|---|---|
| Budget exhaustion | Include correction/declaration versus ordinary-review waiting time and priority inversions; fraction of evaluated scenario-days hitting any call/input/output pool; median hours from first activity to exhaustion among exhausted days, plus nonexhausted/censored count; backlog age and affected job kinds |
| Task over-fragmentation | Created tasks divided by gold-labeled tasks, distribution per project, provisional versus confirmed counts, allocated linked placeholders versus current nonredirected heads, deterministic-link reversals, and boundary precision/recall; a split severing an attempt/result is a continuity failure |
| Delivery visibility | Positive/negative canary pass counts per injection path, host/model/config version; unsupported and contaminated runs reported separately |
| False suppression | Relevant resurfacing opportunities missed after revision, condition, or compaction change; numerator/denominator and examples from revision scenarios |
| Same-session learning latency | Time from durable captured failure to presence in the next eligible same-session packet; separate pre-action versus prompt fallback, and separately report trigger-to-next-action interval, hook processing delay, misses, and degraded overlays |
| Curation throughput | Calls/tokens per settled episode and admitted claim; extraction/review/expansion/revalidation split; queue wait and processing time separately |
| Evidence-strength distribution | Counts and percentages weak/supported/corroborated at first admission and at release; candidate-only counts separately; split by observed/user-declared/inferred and project. Near-zero corroboration is plausible under conservative root classes, not automatically a defect |

These measures expose usefulness/capacity failures that correctness gates alone miss. They are reported even if no numerical gate is yet set; A26/A59/A61 still gate their defined correctness/certification cases. Do not omit a zero-output day from the denominator.

In addition to individual scenarios, replay at least three representative eight-hour activity days, one per project, under default budgets and the recorded event timing (a virtual clock may accelerate deterministic scheduling). Live provider execution and its queue/call costs remain real. Do not reset the UTC budget between scenarios in this workload test or extrapolate an all-day result from isolated trials with fresh budgets. Increased-budget experiments are separate labeled variants.

## 6. Live-agent outcome evaluation

Use the same 48 scenarios, three fresh trials each, with a fixed working-agent model/configuration across these baselines:

1. No additional memory, with normal repository/tools available.
2. A simple task-summary/notes baseline with a fixed context budget.
3. Current Breadcrumbs with its documented memory instructions, where applicable.
4. The new system with no agent memory-maintenance instructions.

An existing memory-native system may be added as a fifth baseline if practical; record its configuration rather than asserting equivalence from published scores. A general-workspace scenario may not apply to Breadcrumbs; report it separately instead of assigning an artificial failure.

Disable host-native automatic memory in all four baselines and the curator, while preserving each baseline's intentional supplied notes/instructions. Record the effective native-memory setting, inherited instructions, and any retrieval services in each trial manifest. If native memory cannot be disabled, treat that host-native configuration as a separately named fifth baseline or exclude the host from the clean no-memory comparison; never label a contaminated run “no memory.” A missing clean baseline leaves the corresponding outcome claim/gate unestablished. No automatic native memory is quietly added to Breadcrumbs or Recalith.

The optional fifth baseline can be either host-native memory or an external memory-native system; if both are evaluated, report six baselines and recompute costs. Baseline eligibility and tool access must be matched before scoring.

Each trial includes session A that learns, fresh session B that applies, and session C where evidence changes when the scenario requires it. The task oracle observes final artifacts/outcomes independently of memory text. Measure task success, repeated mistakes, unnecessary detours, legitimate retry success, total foreground tokens, background tokens, elapsed time, and operator interventions.

Release targets: at least 25% relative reduction in repeated failures versus no memory on relevant scenarios; overall task success no more than 5 percentage points below the best applicable baseline; no increase beyond 5 percentage points in legitimate-retry failure. Report counts, paired scenario-level differences, and uncertainty intervals from resampling whole scenarios, keeping each scenario's trials together. Small denominators and inconclusive intervals must be reported; point estimates alone do not justify a superiority claim.

The development smoke subset has 12 scenarios: four learning, four revision, four control. Use it while iterating. Run the complete held-out comparison for the full release gate, not for preview or after every reversible edit.

### 6.1 Preview evaluation gate

The preview uses the frozen **12 non-held-out scenarios**, four learning/four revision/four control, one fresh trial per scenario for candidate and clean no-memory baseline. **Breadcrumbs and the notes baseline are not run for preview**; those comparisons belong to the full-release evaluation, so their absence is intentional rather than missing data. The applicable §5.1 quality targets still gate that smoke population; report denominators and uncertainty rather than implying generalization. Demonstrate at least one fresh-session reuse, one changed-condition revision with successful legitimate retry, forgetting plus suppression-aware restore, and isolation from a conflicting second project. Routine human memory-maintenance interventions remain zero. Execute three default-budget eight-hour workload days, all seven operational measures, native-platform hook latency/usefulness, and the profile-required deterministic/failure tests.

Report paired task outcomes, mistakes, retries, and foreground/background costs against no memory even when the difference is inconclusive. The full §6 comparative outcome thresholds and independent held-out claims remain a **Cut 2 gate**; do not call a smoke pass proof of superiority. A failed required correctness or smoke-quality target blocks the named autonomous preview or must be published only as an explicitly experimental build with the unmet target stated. `autonomous_ready` reports runtime capability, not that this release-quality experiment has passed. Full release still requires the complete 48-scenario, three-trial, applicable-baseline comparison; none of those gates is removed.

### 6.2 Evaluation workload, cost, and elapsed-time planning

These are arithmetic planning examples, **not measured product costs or current provider prices**. The exact formula is `scenarios × trials × applicable baselines × sessions per scenario`; scenario-specific ineligibility must be visible, not charged as a failure. For 48 × 3 × 4–5 × 2–3, the range is **1,152–2,160 foreground agent sessions**, not a single fixed count. Background curation/review calls are additional.

For a concrete middle estimate, assume 2.5 sessions/scenario, an illustrative $0.30 foreground cost/session, background cost 25% of foreground, four minutes/session, and 25% orchestration/retry overhead. These inputs are replaceable assumptions. Subscription usage may have quota rather than incremental dollar cost; report quota and tokens separately rather than describing it as free.

| Run | Foreground sessions | Illustrative total cost | Serial foreground time | Illustrative elapsed time including 25% overhead |
|---|---:|---:|---:|---:|
| Daily smoke, candidate only: 12 scenarios × 1 trial × 1 baseline | 30 | $11.25 | 2 hours | About 38 minutes at 4 independent trial slots |
| Comparative smoke: same subset × candidate + no memory | 60 | $22.50 | 4 hours | About 75 minutes at 4 slots |
| Full release, 4 baselines | 1,440 | $540 | 96 hours | 15–30 hours at 8–4 slots |
| Full release, 5 baselines | 1,800 | $675 | 120 hours | About 19–38 hours at 8–4 slots |

Parallel slots initialize separate evaluation installations noninteractively using an explicitly operator/CI-provisioned pre-init token file. Token creation itself does not run from the unmarked noninteractive harness, and no agent marker is bypassed. Parallel slots use those separate evaluation installations; they do not violate the one-model-request-per-installation limit. Rate limits, long background queues, and unavailable host automation can increase elapsed time substantially. A sensitivity range of $0.10–$0.75/session and 5%–40% background cost produces approximately **$121–$2,268** over the 1,152–2,160 session range, before any separately priced infrastructure. This is an assumed envelope, not a quote.

Before a full run, execute a small non-held-out pilot, measure actual foreground/background usage and duration, record the dated chosen model prices or account quota, and replace these illustrative assumptions with a run estimate and spending/time cap. Ordinary development uses deterministic tests and the smoke subset; the frozen full comparison is a release activity. Certification canaries and workload-day experiments are itemized separately.

## 7. Performance and freshness

Reference corpus: 100,000 normalized events, 10,000 claim heads, 5,000 episodes, 20 concurrent session identities, and 5 active tasks. Reference hardware class: a contemporary laptop/desktop with at least 4 physical CPU cores/8 logical threads, 16 GiB RAM, and a local SSD. Record exact CPU, power mode, OS/build, Python build, SSD/filesystem, antivirus/indexer state, and provider latency. Test native Windows, macOS, and Linux; WSL is additional. The original review's specific Pydantic startup numbers are not adopted as measured facts. Avoiding it on the hook path is an architectural constraint that still requires measurement.

| Measurement | Initial target |
|---|---:|
| Capture + immediate delivery hook, including fresh process startup, warm packet cache | p95 ≤ 300 ms; p99 ≤ 750 ms; healthy eligible delivery ≥99%, degradation ≤1% |
| Same hook with cold/missing packet cache and bounded fallback | p95 ≤ 300 ms; p99 ≤ 750 ms; healthy eligible delivery ≥95%, degradation ≤5% |
| Deterministic context query | p95 ≤ 150 ms |
| Typed event to working-state availability, healthy idle worker | Preview p95 ≤5 seconds with 5-second idle polling; full p95 ≤2 seconds with healthy IPC |
| Meaningful boundary to admitted knowledge, healthy backend/no queue/no expansion, extraction + review fast path | p95 ≤ 180 seconds; includes both calls and application |
| Expanded, queued, budget-paused, or revalidation work | Report p50/p95/max queue and end-to-end latency; no 180-second promise |
| Contradiction explicitly accepted by operator to old-guidance suppression | Same successful transaction |
| Idle resident worker CPU | Average < 1% of one core over 10 idle minutes |
| Idle resident worker resident memory | ≤ 150 MiB, excluding model subprocesses |

For usefulness/degradation denominators, use healthy fixtures whose gold labels require an eligible packet and whose dependencies are accessible; count missing required content, empty fallback, inappropriate downgrade, or deadline-skipped delivery as degraded. Correctly quiet fixtures are measured separately and cannot inflate the numerator. Report optional-path absence by capability; it is not disguised as a delivered packet. Fault-injection runs have separate populations/distributions and test safe behavior rather than promising the healthy latency rate during blocked storage. They cannot be mixed into the healthy population to hide misses. A low latency obtained by dropping most cold-cache output fails the usefulness gate.

Run 500 warm-packet and 500 cold/missing-packet hook trials per native platform, each in a fresh interpreter process, with representative payloads through the specified caps. Also report at least 50 first launches after runtime provisioning/reboot separately, identifying OS filesystem-cache state where observable; a fresh process is not automatically a cold OS disk cache. Include stale cache, busy writer, concurrent hooks, slow fsync, and Windows transient-rename cases. Report distributions; do not hide degraded responses inside successful latency counts. Capture/admission lag under budget exhaustion is reported separately, with pending work visible to the user.

## 8. Release checklist (apply the selected profile explicitly)

- Required deterministic case variants pass on supported platforms; preview includes the 67 IDs/partial variants in §2.1, full includes all 73 and every supported variant.
- At least one inference backend passes effective isolation. Preview certifies Claude; full certifies both host adapters. Both require start/prompt delivery, and report optional pre-action/compact paths separately. Codex inference stays optional.
- The selected profile meets its frozen smoke/full quality gates or is labeled experimental with unmet targets; preview does not imply the held-out comparison was run.
- Backup, restore, forget, pin-aware retention, operator-command guards, and cross-installation tests pass in both profiles; migration/upgrade (including preview-to-full transition) and transfers are full-only.
- Dependency and license inventory matches the actual shipped code.
- Both profiles keep independent pinned installations isolated; full additionally upgrades A while B continues operating on its own release.
- Documentation distinguishes automatic operation, fallback operation, and missing capabilities.
- Evaluation report includes unsuccessful runs, all operational measures, native-memory settings, scenario authorship, pilot-based cost/time estimates and actual costs, limitations, and no unsupported superiority claims.
- All five implementation Review focus items are rechecked at each subproject gate.
- Fast-path imports, private-path restriction coverage, default-budget workload days, and fresh post-forget recovery are explicitly reported.
