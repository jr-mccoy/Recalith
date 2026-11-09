# Round-two review response and revision record

Revision 1.2 • 2026-10-15 • Replaces the v1.1 design documents for implementation.

The architecture remains project-local and autonomous. The main product change is a **Claude autonomous preview** with its own honest release gate, before the full portability/multi-host release. The core still converts events into short-term state, medium-term episodes, and long-term knowledge; recalls it automatically; and revises or forgets it when required. Each project contains its own installation, version, worker, store, and policy. A personal external brain is a separate project.

This revision addresses all eight major findings, the eleven rows of the proposed release cut, and nineteen smaller fixes in the supplied [round-two review](../review/ROUND_2_REVIEW.md). The table IDs below are revision-tracking labels, not additional acceptance IDs. All substantive changes are integrated in SYSTEM_SPEC, DATA_CONTRACTS, IMPLEMENTATION_PLAN, and ACCEPTANCE_TESTS. This response is explanatory, not an additional policy source.

## What changed

- **Authority:** remove the typed declaration-review bypass; guard administrative CLI mutations against ordinary agent-channel execution, require a human TTY or explicit token-file workflow for unmarked administrative automation, and add A73.
- **Capacity:** separate bounded host output from decoded response size; use purpose-specific allowances; review candidates in bounded batches with per-candidate verdicts and no extractor rationale.
- **Maintenance:** a certified matching success suspends failure caution in the ingestion transaction, before model review. Resumed single-task sessions can link provisionally without model budget.
- **Delivery:** one 250 ms soft scheduling deadline with explicit degradation order; mandatory reservation/fencing; required start/prompt paths and separately certified optional paths.
- **Release:** preview keeps forgetting, safe expiry, backup/restore, and health. Secondary integrations, transfers, capsules, hash-chain diagnostics, IPC, and upgrade tooling wait for full. The dependency order brings recovery prerequisites forward.

## Major findings

| ID | Review finding | Disposition and integrated change | Verification / owner |
|---|---|---|---|
| N01 | Agent shell can invoke operator CLI | Accepted with a stronger content-policy fix: remove declaration bypass on every route. Guard before actor assignment; known host/curator markers refuse even with TTY/token. Unmarked admin mutations require TTY or a token file; record content-free refusal telemetry. Install certified command deny rules and disclose same-user bypass limits. No unverified Codex marker is assumed. | SYSTEM_SPEC §7.1.2/13.1; DATA_CONTRACTS §2/12; Tasks 12a/13/14; A60/A73 |
| N02 | 6,000-byte default rejects ordinary episode output | Accepted. Defaults: task 1,500; episode/extraction 8,000; review/revalidation 3,000 output estimates. Enforce 256 KiB raw wire and purpose-specific decoded body separately, plus bounded stderr. A valid 15 KB episode fits. Keep the 180,000 daily pool with explicit 48-call maximum-reservation example; 90 is a call ceiling, not guaranteed capacity. | SYSTEM_SPEC §6.3; DATA_CONTRACTS §8; Tasks 4/7; A30/A50 |
| N03 | Per-claim review contradicts budget arithmetic | Accepted with corrected arithmetic and output-aware splitting. Persist batches from one extraction job, at most eight candidates and input/output caps; return one locatable verdict per candidate. Five fitting candidates cost one ordinary extraction plus one protected review, two total. With K review batches and two expansions each, upper bound is 3 + 3K calls before other work/retries. | SYSTEM_SPEC §7.2; DATA_CONTRACTS §5/6.2/7/11; Tasks 4/9; A50/A60 |
| N04 | Existing failure lesson lacks immediate success-driven withdrawal | Accepted with epistemic qualification. Same-family certified later success atomically adds context evidence, marks needs_revalidation, advances epoch and queues review, even with no budget. Success alone is not a logical contradiction of a conditional historical failure. Action family includes workspace/working directory and excludes task ID; task debounce adds task ID separately. Missing dependencies already prevented failure caution in v1.1; v1.2 makes that gate explicit. | SYSTEM_SPEC §6.3/7.3–7.4; DATA_CONTRACTS §5/8; Task 10; A43 |
| N05 | Hook sub-budgets lack deadline arithmetic | Accepted as a soft scheduling deadline: entry +250 ms, all substeps use remaining time, 40 ms nominal safety tail, cold fallback starts only with ≥60 ms. Drop optional overlay, then wake, then dependency refresh; unknown dependencies cannot caution. Capture acknowledgment and delivery safety are never fabricated. Blocked filesystem I/O can exceed the deadline. Unbound start uses workspace scope. | SYSTEM_SPEC §5.1.1–5.1.2; DATA_CONTRACTS §2.3; Tasks 3b/11/12b; A58 |
| N06 | Required delivery paths are undefined | Accepted. Start and prompt are required; pre-action/compact injection are separately probed optional capabilities. Prompt fallback is explicit and does not claim before-every-tool warning. A captured unique compaction can restore via prompt; an unobserved compaction grants no extra allowance. | SYSTEM_SPEC §8.2/9.3/15; DATA_CONTRACTS HealthReport; Tasks 13/14/17; A27/A61 |
| N07 | Exhausted budget fragments resumed work forever | Accepted as a reversible heuristic. Exactly one eligible prior task, no explicit conflicting boundary, and first three compatible path-bearing actions permit a provisional link without a model. Preserve pending pairs, narrative objectives, binding history, and a nonowning linked placeholder. Ambiguous cases remain separate. | SYSTEM_SPEC §3.2; DATA_CONTRACTS §3.1; Task 6; A57 |
| N08 | expected_red and runtime versions lack certified sources | Resolved explicitly. expected_red is reserved false; raw intent hints cannot set it true. Debounce and semantic A13 remain. Runtime versions come from declared project config or certified observed version output tied to executable/workspace, never pmem's own runtime. Conflicting/unbound/stale values stay unknown. | SYSTEM_SPEC §6.3/13; DATA_CONTRACTS §1.1/2.1; Task 3; A13/A52/A54/A66 |

## Proposed release cut

| ID | Review scope row | Disposition | Where reflected |
|---|---|---|---|
| C01 | Core Tasks 0–13 including split tasks | Accepted. Keep capture, state, episodes, reviewed claims, revision, retrieval, and one certified Claude delivery integration. One selected certified inference route; no silent provider change. | SYSTEM_SPEC §1.2; implementation stage/scope tables |
| C02 | Forgetting in Cut 1 | Accepted in full, including surviving-root quarantine, cleanup phases, fresh backup and replay suppression. | Tasks 15 core/16; A36/A37/A48/A63/A64 |
| C03 | Health now; upgrades later | Accepted. Health and persistent startup move ahead of preview release; upgrade/chain diagnostics remain full-only. Readiness is profile-scoped operational capability, not an evaluation score. | Task 17; HealthReport; release gates |
| C04 | Early smoke/workload/performance/failure tests | Accepted. Prepare fixtures in Task 1 and harness slices from Task 7; extraction tests at Task 9, integrated outcome gate after host/recovery work. Preview uses candidate/no-memory comparison, 12 non-held-out scenarios, three workload days, applicable correctness/failure tests and latency/usefulness gates. | Tasks 1/7/9/13/18; ACCEPTANCE_TESTS §6.1 |
| C05 | Defer Codex/generic JSON/MCP | Accepted. Explicit unavailable capabilities in preview, full Task 14 later. Core generic-planning fixtures use a test-only source. | SYSTEM_SPEC §1.2; Task 14; acceptance profile map |
| C06 | Defer capsules/transfers; 180-day events | Qualified. Defer capsules/export/import/Breadcrumbs, but retain consistent backup/ledger and **safe expiry/downgrade**. An elapsed 180 days cannot depend on the next release arriving. Day-181 tests withdraw inadequately supported guidance atomically. | SYSTEM_SPEC §11; Task 15 core before 16; A35/A40 |
| C07 | Defer revision hash chain | Accepted. Reserve schema, report diagnostic unavailable, retain ordinary revision/concurrency/privacy checks. Full activation records an honest baseline instead of inventing historical chain integrity. | SYSTEM_SPEC §10; Tasks 5/17; A65 variants |
| C08 | Defer IPC, poll 1/5 seconds, target 5 seconds | Accepted. Persistent active/idle polling and p95 ≤5-second typed-state target in preview; CPU gate retained. Full adds healthy IPC ≤2-second target. | SYSTEM_SPEC §6.1; Task 4; performance matrix |
| C09 | Private-path restrictions probe only | Accepted for broad file restrictions. Qualified to retain minimum administrative command guards/deny rules now, otherwise N1 remains needlessly exposed. Report probe, installed command coverage, and limits separately. | SYSTEM_SPEC §13.1; Task 13; A65/A73 |
| C10 | Defer attach/fork/session worker/shared config | Accepted. One workspace and persistent local integration per project installation; independent projects remain fully separate. Deferred forms fail explicitly. | SYSTEM_SPEC §1.2; Tasks 2/4/13; health capability registry |
| C11 | Proposed acceptance subset | Corrected. Retain A37 restore and the backup portion of A40. Preview includes 67 of 73 IDs, excluding only A38/A39/A42/A46/A55/A71; feature variants of A02/A03/A04/A27/A35/A40/A45/A47/A53/A58/A61/A65 are enumerated. No deferred variant is counted passed. | ACCEPTANCE_TESTS §2.1; Task 18 profile manifest |

## Smaller fixes

| ID | Review point | Integrated resolution |
|---|---|---|
| S01 | Ordinary src/tests/docs activity proposes boundaries | Coding profile unifies those conventional paths and requires five truly disjoint actions; weak proposals wait for a normal extraction job. SYSTEM_SPEC §3.2; Task 6; A57. |
| S02 | Rare corroboration should be expected | State that no complete-dependency experiment domain is certified by the design; one actor's repeated declarations cannot exceed supported. Add strength distributions. SYSTEM_SPEC §7.1.1; acceptance §5.2. |
| S03 | Reviewer still sees proposal reason | Build allowlisted reviewer input stripping all proposal reason/rationale fields; original source evidence remains exact. SYSTEM_SPEC §7.2; contracts §7; Task 9; A60. |
| S04 | Define correct precisely | Immediate expected-revision typed invalidation and replacement candidate in one transaction; no model needed to stop old guidance, replacement needs review. SYSTEM_SPEC §7.3; contracts §11/12; Task 12a; A19. |
| S05 | Read-only WAL after worker crash | Test present/missing/unreadable SHM, no hook recovery/checkpoint, fresh final snapshot and empty/degraded fallback if no safe read. Do not use immutable on a live WAL. SYSTEM_SPEC §5.1.1; A58. |
| S06 | Doctor O(store) scan | Full profile defaults to incremental chain-range/touched-row verification with disclosed coverage; explicit --full-integrity scans all rows. It cannot claim unchanged-row detection from an incremental pass. SYSTEM_SPEC §10; Task 5; A65. |
| S07 | handle_hook capture/delivery branch mapping | Add normalized host-event mapping table and delivery-enabled capability flag; Task 3b is capture-only and never emits a fake delivery pass. Contracts §2.3. |
| S08 | single_active_task reason | Add exact reason enum and provisional-link/redirect semantics. Contracts §3.1; Task 6; A57. |
| S09 | Null failure family behavior | Time/count only, never success-matched by lexical similarity. Contracts §8; Task 9; A66. |
| S10 | independent_roots signature semantics | Signature comment and contract explicitly return canonical class IDs after all alias resolution, not raw events. Contracts §6.1/11. |
| S11 | CLI refusal code and forms | Exit 6 and complete administrative form list, marker precedence, TTY/token-file workflow, healthy audit and audit-failure behavior. Contracts §12; Task 12a; A73. |
| S12 | A58 wording implies all reads forbidden | Read-only snapshots allowed; no database write transaction, recovery/checkpoint or lock wait. SQLite SHM bookkeeping is not confused with authoritative DB mutation. A58 and SYSTEM_SPEC §5.1.1 agree. |
| S13 | Report strength distribution | Add seventh operational measure, admission/release counts and percentages by strength/basis/project, with candidate-only counts separate. ACCEPTANCE_TESTS §5.2. |
| S14 | Cold-cache latency lacks usefulness threshold | Healthy eligible cold delivery ≥95%, degradation ≤5%; warm ≥99%/≤1%. Gold-required content and separate quiet/fault populations prevent gaming by empty packets. ACCEPTANCE_TESTS §7. |
| S15 | Task 7 recreates compatibility report | Task 7 explicitly extends Task 0's report and fixtures. IMPLEMENTATION_PLAN Task 7. |
| S16 | Task 12a needs agent CLI refusal test | Add named test_agent_channel_cannot_declare_or_forget, parameterized over all guarded forms, markers, TTY/token combinations, and audit failures. A73. |
| S17 | Task 13 probes four but gates two | Explicitly probe all paths; start/prompt gate readiness, optional paths report their states and fallback gaps. Task 13; A27/A61. |
| S18 | Named Cut 1 stage and gate after Task 13 | Add scope/stage tables, dependency-safe execution sequence, and real-host preview gate after Task 13 requiring early recovery/health/evaluation slices. IMPLEMENTATION_PLAN. |
| S19 | Combined file authority note | Combined copy begins with the same no-second-policy-source statement; modular documents are authoritative if packaging differs, and cross-document disagreements must be resolved explicitly. README and generated combined header. |

## Where the proposed fix needed qualification

**CLI friction is not authentication.** Same-user code can change its environment or access local files. Removing the declaration-review exception fixes a content-policy inconsistency even when a guard is bypassed. Marker refusals, TTY/token-file intent checks, and command rules then reduce ordinary confused-agent actions. A73 does not promise protection against arbitrary hostile same-user programs. The official marker/command references and their limits are recorded in SOURCES_AND_REUSE.

**Two calls does not mean two protected calls.** A five-claim fitting extraction consumes one ordinary extraction and one priority review. Bigger batches split for output capacity as well as the input ceiling. Otherwise batch review could reproduce N2's oversized-output failure. Every expansion/retry remains charged.

**Success narrows confidence, not history.** The original dependency-free failure gate already forbade action caution without complete fingerprints; that remains. The missing behavior was immediate freshness/revalidation after matching success. A success with the database running does not disprove a past failure when it was down, so the new event is a context counter-observation until reviewed.

**Deadlines cannot complete filesystem I/O by decree.** The new clock constrains optional scheduling and makes degradation testable. Durability acknowledgments still depend on actual publication. Mandatory delivery accounting/fences cannot be treated as a skippable overlay write. Likewise, an unsafe/unavailable WAL snapshot means no memory delivery, not a stale unchecked packet.

**A smaller release still needs recovery and expiry.** Capsule deferral is acceptable; leaving old support indefinitely active when its payload disappears is not. Backup and tombstone-aware restore must ship with forgetting, so A37 and the required Task 15 subset stay in preview. The package defines these exceptions explicitly instead of inheriting the proposed exclusion list mechanically.

**Uncertified intent remains intent.** No v1 host field certifies expected-red semantics. A path pattern or phrase may help interpret a test but does not turn an observed failure into an observed intended failure. Runtime version provenance is explicit, and any unknown binding remains unknown.

## Package status and next implementation action

This is a design-only revision, not an implementation or a benchmark result. Numerical targets remain proposed gates. The package retains 21 work packages, has 73 acceptance IDs, defines 67 preview case IDs with explicit variants, and keeps the full 48-scenario evaluation. Both supplied reviews and the prior response are preserved unchanged as history.

Start a fresh repository with these documents, then follow Task 0 and Task 1 and the stated preview dependency sequence. No wholesale Breadcrumbs clone is recommended; its pinned reference and selective reuse/import plan remain. No product repository or external application was modified by this revision.
