# Project Memory — Revision 1.1 Review Response

Date: 2026-10-15 • Responds to the supplied design review dated 2026-10-14

## Revision decision

Keep the fresh-repository, independently installed project-memory architecture. The review does not justify replacing that architecture; it does identify missing definitions, early integration risks, and operational behavior that the original plan left too implicit.

Revision 1.1 integrates the changes into **all five design documents and the README**. The implementation plan has **21 work packages**: original Tasks 1–18, plus Task 0 and Task 3b, with Task 12 split into 12a/12b. The acceptance matrix grows from **48 to 72 cases**. The separate live evaluation corpus remains 48 scenarios. No application has been implemented or benchmarked during this revision.

The original review is preserved without edits in [INPUT_REVIEW.md](../review/INPUT_REVIEW.md). This response explains decisions and locations; the system specification, data contracts, acceptance document, and implementation plan remain the implementation authorities.

## Material changes

1. **Real integration evidence arrives early.** A standalone effective-provider probe precedes autonomous inference, and Task 3b captures real Claude events during the kernel stage. The production adapter reuses those fixtures.
2. **Hooks have a separate lightweight implementation boundary.** Only stdlib and audited fast modules load. Hooks write the spool and bounded session scratch, never SQLite; the worker precomputes packets and ingests delivery receipts.
3. **Task binding and evidence independence are concrete contracts.** Versioned provisional assignments preserve immutable source events. Root classes collapse repeated/forwarded observations using captured identities and dependency fingerprints.
4. **Learning capacity and prioritization are explicit.** Defaults rise to 90 calls, 900,000 estimated input tokens, and 180,000 estimated output tokens per UTC day, with a protected review/correction/revalidation reserve. Failure triggers are debounced.
5. **User intent, retention, and forgetting have stricter transitions.** Natural-language declarations receive automatic adversarial review. Exact capsule locators survive event expiry. Forget purges before reconstruction and preserves a new restore point when possible.
6. **Release evidence covers usefulness as well as mechanics.** Budget exhaustion, fragmentation, delivery visibility, false suppression, same-session latency, native-memory confounds, independent scenario authorship, and cost/time planning are now required reporting.

## Where the proposed fixes needed qualification

**Root classes are a conservative accounting rule, not proof of independence.** Unchanged test reruns collapse; differing unknown dependency fields cannot create extra support. A newly executed experiment may be independent even if a subagent performed it. Forwarding a parent's result is not. Matching content hashes for unrelated artifact identities also does not make them one source.

**Formatting heuristics cannot prove a user declaration.** A pasted email can contain “I want”; a genuine preference may be terse or non-English. Revision 1.1 uses deterministic exclusion regions plus automatic original-message review for all durable natural-language declarations. Only an explicit typed operator declaration can bypass ordinary language review, and not when it supersedes a decision or creates caution. Routine maintenance still requires no human approval queue.

**Hook emission and model visibility are different observations.** A nonce echoed in the first eligible response is useful end-to-end certification evidence, with contamination checks and negative controls. It is not access to a hidden model request. A successful stdout write is recorded as emitted; a crash at the emission/receipt boundary can remain uncertain. No exactly-once stdout guarantee is claimed.

**Private-path restrictions and a local hash chain have limited strength.** Official host documentation supports relevant controls, but effective behavior depends on version, permission profile, sandbox, and managed settings. A blanket deny could also break the hook's own runtime access. Install only a tested configuration, report coverage, and preserve existing restrictions. A same-user process capable of rewriting both database and hash chain can defeat local tamper detection.

**Debounce uses action family, not independent-root class.** A successful retry after a code change intentionally has different dependency fingerprints. Requiring the same root class would fail to recognize the ordinary red-to-green sequence. Root accounting and trigger cancellation therefore use different, explicitly defined keys.

**Cost and latency estimates remain hypotheses.** The review's specific Pydantic import timings and typical-day exhaustion claim were not independently measured here. The architecture now makes those risks testable early. The full evaluation count is 1,152–2,160 foreground sessions for the stated four-to-five-baseline/two-to-three-session range; the dollar and elapsed-time examples are explicit assumptions to replace with pilot measurements.

## Inconsistencies: complete disposition

| ID | Review point | Revision 1.1 decision and implementation location |
|---|---|---|
| I01 | Conflicting payloads claim one event ID | Added separate `source_conflicts` identity, uniqueness, health, retention and privacy handling. Original event stays immutable. Contracts §2.1/§10; Task 3; A49. |
| I02 | Thirty calls/day starves extraction/review | Raised all three budget dimensions, protected review capacity, counted expansion calls, and narrowed the 180-second target to a no-queue/no-expansion path. Spec §6.3; Task 4; A50; Acceptance §5.2/§7. |
| I03 | Volatile/stable is undefined | Exact dependency/kind rule; dependency-free declared decisions/preferences are stable, other/unknown/cyclic cases default volatile. Spec §6.3; Task 10; A51. |
| I04 | Undefined `relationship` claim kind | Removed from v1; typed record relations remain, while ownership propositions can be scoped facts. Spec §3.4; Contracts §5/§6. |
| I05 | Undefined tool assertions | Added bounded `ToolAssertion` and certified-parser eligibility, with exact mapping names. Contracts §2.1; Task 3; A52. |
| I06 | Shared hooks fail in an unbootstrapped clone | Missing-runtime hook exits nonblocking without repeated output or downloads. Local settings are default; `--shared` is explicit. Spec §2.2; Tasks 2/3b/13/14; A53. |
| I07 | Missing uninstall command | Added `pmem integrate HOST --remove` and ownership-aware removal that preserves modified/unrelated entries. Contracts §12; Tasks 13/14; A53. |
| I08 | Three different technical stems | Unified on `pmem`, `.pmem/`, and `PMEM_`, retaining Project Memory as display name. README and all source paths updated. Public distribution-name availability is not claimed. |
| I09 | Open environment dictionaries leak secrets/paths | Introduced `EnvironmentValues`, a small registered allowlist with grammars, early drop and coverage reporting. Spec §13; Contracts §1.1; Task 3; A54. |
| I10 | Capsule links lose original span semantics | Added exact original locator/digest mappings and atomic link redirection with event expiry. Frozen source refs remain resolvable. Spec §11; Contracts §6; Task 15; A55. |

## Major design gaps: complete disposition

| ID | Review point | Revision 1.1 decision and implementation location |
|---|---|---|
| G01 | Define independent roots | Added eligible roots, observation descriptors, equivalence classes, aliases, conservative missing-dependency behavior and import stability. Qualifies statistical independence and subagent fan-out. Spec §7.1.1; Contracts §6.1; Task 8; A56. |
| G02 | Task binding has no owner | `working/segment.py` owns candidate boundaries; versioned bindings and reviewed reassignment preserve call/result pairs and original events. Spec §3.2; Contracts §3.1; Task 6; A57. |
| G03 | Pydantic on synchronous hooks | Introduced stdlib fast entry points, generated wire validators, precomputed packets, read-only fences, and a transitive-import test. CLI/MCP operator writes remain allowed outside hooks. Spec §5.1.1; Tasks 3b/11/12b; A58. |
| G04 | Suppression/overlay lag before ingestion | Added bounded per-session scratch, locks, monotonic budget accounting, recent outcomes, epoch invalidation, and uncertain-emission handling. Spec §5.1.2; Contracts §2.3/§9; Task 12b; A59. |
| G05 | Pasted text becomes `user_declared` | Tightened beyond the proposed heuristic: every natural-language declaration receives original-message review, while explicit typed declarations have a limited bypass. Spec §7.1.2; Task 9; A60. |
| G06 | Delivery proof has no method | Added per-path nonce echo, three positives/three negatives, contamination checks, transcript corroboration, and precise observable-evidence terminology. Spec §9.3; Tasks 13/14; A61. |
| G07 | Branch names dominate applicability | Branch refs become provenance/recall annotations; explicit branch conditions remain available. Dependency fingerprints govern failure caution across merges and fixes. Spec §7.4; Tasks 8/10/11; A62. |
| G08 | Forget order and backup loss | Purge/quarantine before model reconstruction; resumable cleanup; verified new backup before affected older deletion when possible. Backup failure does not preserve forgotten content. Spec §11; Task 16; A63/A64. |
| G09 | Working agent can edit/read memory internals | Added tested private-path restrictions, owned install metadata, and a transactional revision chain. Explicitly limited to friction/detection, with hook-access and same-user caveats. Spec §13/§10; Tasks 5/13/14/17; A65. |
| G10 | Failure-trigger storms | Added six-event/ten-minute debounce and certified expected-red exclusion. Success matching uses action family across changed dependencies. Spec §6.3; Contracts §8; Task 9; A66. |
| G11 | User-level curator customization leaks | Effective probe covers user/project/managed settings, memory, tools, hooks, plugins and MCP. A fired-but-ignored hook fails certification. Spec §9.1; Tasks 0/7; A67. |

## Evaluation recommendations: complete disposition

| ID | Review point | Revision 1.1 decision and location |
|---|---|---|
| E01 | Budget exhaustion measure | Scenario-day exhaustion fraction, censored counts, hours-to-exhaustion, pool/backlog details, plus three default-budget eight-hour workload days. Acceptance §5.2. |
| E02 | Task over-fragmentation | Tasks per gold task, provisional/confirmed counts, boundary precision/recall, and continuity failure on severed result pairs. Acceptance §5.2. |
| E03 | Delivery visibility rate | Per-path/version positive/negative control counts, unsupported/contaminated cases, and live certification requirement. Acceptance §5.2 and A61. |
| E04 | False suppression | Missed resurfacing opportunities after revision/condition/compaction changes, with denominator and examples. Acceptance §5.2 and A26. |
| E05 | Same-session learning latency | Capture-to-next-eligible-packet time, opportunity interval, processing delay, misses and degraded overlays reported separately. Acceptance §5.2 and A59. |
| E06 | Native-memory confounds | Disable native automatic memory in all four clean baselines and curator; retain each baseline's intended supplied memory. Otherwise use a separately named host-native baseline or exclude the comparison. Acceptance §6. |
| E07 | Independent scenario authorship | At least 12 held-out scenarios from authorized sanitized real sessions or an author unfamiliar with admission rules, with provenance disclosed; smoke subset excluded. Acceptance §5. |
| E08 | Adversarial review-pass diversity | Versioned `review_v1.md` asks for strongest unsupported/misattributed/overbroad objections with original-source locators; it is not counted as evidence independence. Spec §7.2; Task 9. |
| E09 | Full-run cost and time | Correct session arithmetic, illustrative cost/time table and sensitivity range, measured pilot replacement, explicit run cap, and daily smoke/full-release split. Acceptance §6.1; Task 18. |

## Sequencing recommendations: complete disposition

| ID | Review point | Revision 1.1 decision |
|---|---|---|
| P01 | Early capture-only Claude adapter | Added Task 3b inside Subproject A; real sanitized fixtures feed later integration. |
| P02 | Early import-set gate | Task 3b verifies fresh-process transitive imports on normal and error paths; later fast-path tasks rerun it. |
| P03 | Probe a provider before engine dependency accumulates | Added standalone Task 0; it can run alongside kernel work, or first for a single implementer. Task 7 integrates/rechecks the result. |
| P04 | Split oversized Task 12 | Task 12a owns service/CLI; Task 12b owns session delivery accounting, overlay, and corrections. |
| P05 | Add segmentation and trigger ownership | Task 6 owns reversible binding; Task 9 owns debounce; exact contracts are shared with storage/scheduler. |
| P06 | Recheck Review focus across gates | All five focus items are explicitly rechecked at A, B, C and D gates; future capabilities are marked pending until integrated. |

## Smaller document fixes: complete disposition

| ID | Review point | Revision 1.1 decision and location |
|---|---|---|
| S01 | Bounded result text loses the failing tail | Default 8 KiB head + 8 KiB tail, exact chunk offsets, optional certified 1 KiB error signature, total event cap preserved. Spec §3.3; Contracts §2.1; A68. |
| S02 | Context eligibility is underspecified | Added strength/status × freshness × evidence display table; expired insufficient evidence is omitted from automatic packets. Spec §8.2; A69. |
| S03 | Windows shell parsing | Host argv first; shell-certified parsing otherwise; ambiguity yields unknown instead of invented action identity. Spec §7.4; Contracts §9; A70. |
| S04 | Account suitability for background use | Probe records checked route/deployment eligibility and dated policy basis/attestation; flags are not contractual authorization. Spec §9.1; Sources §5. |
| S05 | Antivirus/indexer blocks spool rename | One recognized transient retry after at most 20 ms within the hook deadline, then `not_captured` and no cursor advance. Spec §5.1; Task 3. |
| S06 | Tombstone digest membership oracle | Explicitly documented private-ledger residual disclosure and extended to revision-chain content digests. Spec §11/§10. |
| S07 | Free-form evidence mapping names | Closed enum: `tool.exit_code`, `tool.reported_result`, `config.exact_value`, with registered type/source contracts. Contracts §1.1/§6. |
| S08 | Imported stub identity depends on destination | `OriginEventKey`-derived IDs exclude destination installation/export digest; missing upstream identities need a persistent import namespace. Contracts §1/§5; A71. |
| S09 | Match reasons are prose-only | Nonempty `why`; first element is a closed reason code, followed by readable explanation. Contracts §9; A72. |
| S10 | No `not_captured` exit code | Added ordinary CLI exit 7, with host nonblocking translation; partial capability uses exit 8. Contracts §12; A72. |
| S11 | A10/A12 deterministic tests imply model quality | Explicitly separated recorded-proposal mechanics from live segmentation/continuity evaluation. Acceptance §2/§5. |
| S12 | Hook target lacks hardware/cache conditions | Disclosed reference class, fresh interpreter per invocation, warm/cold packet-cache cohorts and first-launch subset; degraded results reported separately. Acceptance §7. |
| S13 | Missing stable error codes | Added `not_captured` and `capability_degraded`, plus conflict/forget-backup codes needed by this revision. Task 1 and Contracts §12. |
| S14 | Case-insensitive filesystem coverage | Added native APFS case-insensitive and Linux casefold fixtures alongside Windows junction/case tests; missing coverage must be explicit. Task 2 and A33. |
| S15 | Codex provider incorrectly looks mandatory | Removed the mandatory provider file; Codex capture/delivery stays in v1, inference remains separately probe-gated. Task 7 and Sources §4. |

## Additional consistency fixes made during revision

- **Delivery linearization:** A correction committed before the final read-only fence removes old guidance. A later concurrent correction cannot retract already-started output. The implementation and acceptance wording now agree on this boundary.
- **Emission crash accounting:** Pending attempts reserve tokens before output; only successful flush becomes an emitted receipt. An uncertain attempt cannot falsely count as model visibility or reset the budget.
- **Schema ownership:** The fast wire validator is generated from the authoritative schema and checked against the same fixtures, so removing Pydantic from hooks does not create a second handwritten contract.
- **Cache validity versus bookkeeping:** Added a guidance epoch so recording a delivery or budget update does not invalidate every subsequent packet. Serving-relevant changes still advance that epoch atomically and invalidate stale guidance.
- **Source conflict consequences:** Conflicting payloads remain separate, and dependent caution is suspended while source identity is unresolved.
- **Capsule reference ownership:** Normalized links supply current DTO references, while old frozen refs resolve through the capsule origin index. Retention does not rewrite historical claim prose.
- **Budget dimensions:** Raising only the call ceiling would leave the original token limits as a hidden bottleneck. Invocation, input, output, protected reserve, and per-call output reservation now agree.
- **Backup-failure behavior:** Forget completion separates purge state from recovery availability. Privacy cleanup is never rolled back solely because making a new backup failed.
- **Idle-worker timing:** Specified a bounded local IPC wake hint plus durable-spool polling fallback; a 30-second idle poll alone cannot satisfy the two-second healthy-worker target. PEP 440 evaluation also stays in the worker so fast hooks do not reintroduce packaging imports.
- **Scenario accounting:** The 72 deterministic acceptance cases and 48 live scenarios are explicitly different populations; adding test cases did not silently enlarge the expensive live comparison.

## Decisions retained from the original design

Retrieval/delivery never strengthens evidence. No model/network call runs inside a write transaction, and proposals persist before application. Every project retains its own installation and worker. Durable knowledge stays in the store; instruction-file export is explicit. Unknown applicability never causes caution. Release claims remain bounded by the tested population. The new repository starts fresh, with selective reuse and a one-way Breadcrumbs importer.

“Passing does not prove absence of failures outside that population” and “do not lower a gate to manufacture success” remain release principles.

## What the next review should establish

Check that the revised interfaces can be implemented without choosing a new policy: root-class equivalence, provisional task reassignment, fast-hook/session accounting, declaration review, dependency-based caution, and forgetting phases should each have one documented behavior and an owning test. Numerical capacity, latency, quality and cost remain proposed measurements until the implementation and pilot exist. No claim in this package should be read as a completed host certification or measured product result.
