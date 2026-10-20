# Recalith Implementation Plan

> **For coding agents:** Begin with [the coding-agent handoff](../CODING_AGENT_HANDOFF.md) and implement this plan task by task using the execution workflow available in your environment. Preserve the task boundaries, test-first cycle, review gates, and contract checks. Checkboxes (`- [ ]`) track work; no particular agent plugin, skill, or delegation setup is required.

**Revision:** 1.3 • 2026-10-15. This is the integrated replacement plan. Task numbers remain stable for review traceability; Task 0b adds the early delivery probe beside Task 0, retaining Task 3b and 12a/12b: **22 work packages** in total. No application code has been implemented by this design revision.

**Goal:** Build an autonomous memory installation inside each project, with independent versions and automatic working, episodic, and durable memory management.

**Architecture:** A local event spool feeds a transactional SQLite store. A bounded controller proposes evidence-linked operations through certified model adapters; deterministic admission and revision checks commit them. Project-specific hooks and optional MCP deliver relevant current memory without requiring the working agent to maintain it.

**Tech Stack:** Python 3.12+, Pydantic v2, packaging for PEP 440 comparisons, standard-library SQLite, optional MCP SDK and embedding adapters, pytest for tests. Lock exact dependency versions at bootstrap. No global daemon, graph database, distributed queue, or web application.

**Spec:** [SYSTEM_SPEC.md](SYSTEM_SPEC.md), with [DATA_CONTRACTS.md](DATA_CONTRACTS.md) and [ACCEPTANCE_TESTS.md](ACCEPTANCE_TESTS.md).

## Global constraints

- Every project contains a complete, independently versioned installation.
- There is no shared memory daemon, global project registry, or automatic transfer between projects.
- Synchronous hooks never wait for a model or write SQLite; their transitive imports are stdlib plus the audited `recalith.fast` package only.
- No model call or network request occurs inside a write transaction.
- No background job edits `CLAUDE.md`, `AGENTS.md`, or the project's source files.
- Python 3.12, 3.13, and 3.14 are the core CI matrix; native Windows, macOS, and Linux are required for platform acceptance.
- Event payload cap: 64 KiB. Segment cap: 256 KiB. Model serialized input cap: 96 KiB. Host wire stdout cap: 256 KiB; decoded body caps follow purpose-specific reservations (4,500/24,000/9,000 bytes).
- Default model invocations: 90 per installation per UTC day; input estimates: 900,000; output estimates: 180,000; concurrent requests: 1; timeout: 120 seconds. Protect 30 invocations/300,000 input/60,000 output for review/correction/revalidation; ordinary jobs cannot borrow that reserve.
- Default context budgets: start 2,000, prompt 1,000, pre-action 400, unchanged memory per session 4,000 estimated tokens. If pre-action is unavailable and eligible caution is substituted, an ordinary prompt has one shared additional 400 allowance (1,400 total); compaction restoration remains capped at 2,000 including cautions.
- The domain layer imports no CLI, MCP, or host adapter module.
- Provider routing and credential use are explicit; missing capability does not authorize a weaker fallback.

- Technical stem: `recalith` command/distribution/import package, `.recalith/` project directory, `RECALITH_` environment prefix. Display name: Recalith.
- All durable declarations, including the guarded typed CLI route, require adversarial review; no declaration-review bypass remains.
- Revalidate every current caution against dependency applicability, not branch-name similarity.

## Review focus

These conditions are easy to omit from an ordinary happy-path build. Their owning tasks below must include the named tests. Recheck all five at **every subproject gate**, rerunning the relevant cross-component tests as new components join; an earlier isolated pass does not satisfy a later integrated gate.

1. Same source event arrives twice across a crash: one support root, one mutation effect (Tasks 3, 5, 10).
2. A source is quoted or repeated through agent memory: its authority and corroboration do not increase (Tasks 8, 9).
3. A correction or forget commits before the final delivery fence: old guidance is excluded; already in-flight emission is explicitly bounded (Tasks 12b, 16).
4. Paths change across Windows, WSL, worktrees, and project relocation: only explicitly registered boundaries are accessible (Tasks 2, 13, 14).
5. A provider or host version changes: certified capability is rechecked; no silent tools, billing change, or fake autonomy claim (Tasks 7, 13, 14).

## Repository and execution strategy

Create a fresh repository. Copy this final handoff into its own docs first. Resolve and record empirical Task 0/0b findings and Task 1 contract changes there; after that repository exists, it is the design authority. Do not wait for another external package-review cycle before starting the probes. An optional Breadcrumbs reference checkout uses the exact commit in SOURCES_AND_REUSE and lives outside the new source tree. Do not copy its `.project-memory`, CI, release workflow, instruction files, or broad CLI module into the new application.

The plan retains four engineering subprojects plus two explicit shippable release cuts: A durable local kernel; B working state and inference boundary; C autonomous knowledge and delivery; D integrations and operational release. Task numbers retain review traceability; the profile-specific dependency sequence below is the execution order. Extract the named operational prerequisites before the preview gate rather than waiting for all full-release features in those work packages.

Tasks 0 and 0b are standalone preconditions before Task 1: certify one inference route and test required delivery paths before building the kernel. Neither needs an engine database. This is a dependency sequence, not a delegation requirement. A failed required host/provider capability produces an immediate explicit blocker and informs the repository docs; deterministic core work can continue without claiming autonomy. Task 7 rechecks provider isolation in production; Task 13 reuses the early delivery harness against the actual engine. Task 3b supplies real sanitized capture fixtures before downstream code depends on synthetic assumptions.

| Stage | Work packages | Reviewable outcome |
|---|---|---|
| Early spikes | 0, 0b | Provider isolation and real start/prompt delivery established, optional-path gaps measured, or concrete blockers documented |
| A: kernel | 1, 2, 3, 3b, 4, 5 | Real capture, durable spool, isolated stores, fenced mutations |
| B: continuity | 6, 7, 8 | Reversible task binding, connected episodes, certified provider, root classes |
| C: knowledge | 9, 10, 11, 12a, 12b | Reviewed learning, revalidation, lightweight packets and accounting |
| Cut 1: Claude autonomous preview | 0–13 including 0b/3b/12a/12b, plus 15 core, 16, 17 health, 18 preview | One real host/provider; autonomous loop, forgetting/recovery, comparative smoke and workload days |
| Cut 2: full release | Remaining slices of 2/4/5/13/15/17/18, plus 14 | Additional host/interfaces, portability, integrity diagnostics, upgrades, full comparison |

### Dependency-safe release sequence

For one implementer, execute `0 → 0b → 1 → 2 → 3 → 3b → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12a → 12b`, then **Task 15 core backup/pin-aware-retention → Task 16 forgetting/restore → Task 17 health → Task 13 real Claude delivery → Task 18 preview gate**. Finish both early probe reports before Task 1 freezes host-facing assumptions; delegation is not required. Prepare the 12 non-held-out smoke fixtures/oracles in Task 1, implement the evaluation harness incrementally from Task 7, and exercise the applicable slices at Tasks 9–13. Evaluation is not postponed until the entire full release exists.

Work-package checklists below describe the eventual full package. A profile annotation explicitly limits what is in preview; deferred checklist items remain pending, never marked complete. Track each feature slice and its acceptance variants in `tests/coverage_manifest.json` with `release_profile`, required capability, owning task, and unavailable reason.

| Work package / feature | Preview commitment | Deferred to full |
|---|---|---|
| 0, 0b, 1, 3, 3b, 6–12b | All core behavior; one configured certified inference route | Additional optional backends |
| 2 installation | One workspace per independent project, clone/move handling, local integration, absent-runtime behavior | Attach, fork, shared integration |
| 4 worker | Persistent worker, active/idle polls 1/5 seconds, budget/lease rules | Session mode, IPC wake and 2-second target |
| 5 mutations | All atomic revisions, evidence/privacy fences, compensating undo | Revision hash chain and integrity scanner |
| 13 Claude | Capture, four delivery probes, required start/prompt gates, operator-command guard/deny rules, private-path probe/report | Broad private-path installation and shared-config mode |
| 14 additional interfaces | Explicit unavailable capabilities and commands | Codex, generic JSON, optional MCP |
| 15 retention/recovery | Consistent backup, ledger, live-evidence pins and 180-day expiry of unpinned event payloads | Capsules, export/import, Breadcrumbs migration |
| 16 privacy | Complete forgetting, surviving-root quarantine, post-forget backup, suppression-aware restore | Nothing required for forgetting is deferred |
| 17 operations | Health, persistent project startup/restart, profile-aware readiness | Side-by-side engine/schema upgrade, including preview-to-full transition |
| 18 evaluation | Applicable correctness/failure tests, comparative 12-scenario smoke, three workload days, all hook latency/usefulness gates | Full 48-scenario three-trial held-out comparison |

Preview cannot omit backup/restore merely because most of Task 15 is deferred. It must preserve live memories beyond day 180: A35's pin-aware retention and explicit missing-support handling ship now. Capsules are a later storage/export optimization, not the mechanism required for long-term memory survival. General planning fixtures may be replayed through a test-only registered source without shipping the generic JSON adapter. Every project still has its own complete installation; preview does not introduce shared runtime state.

### Intended source structure

| Directory | Responsibility |
|---|---|
| `src/recalith/contracts/` | Strict worker/service DTOs and generated schemas/wire validators |
| `src/recalith/fast/` | Stdlib-only capture, cache/fence reads, session scratch, host wire entry points |
| `src/recalith/core/` | Identity, scopes, conditions, lineage, policy |
| `src/recalith/storage/` | SQLite, repositories, migrations, spool, consistent backups |
| `src/recalith/capture/` | Source registration, normalization, scrubbing |
| `src/recalith/working/` | Boundary proposals, versioned bindings, task state and event reduction |
| `src/recalith/episodes/` | Segmentation and bounded episode construction |
| `src/recalith/controller/` | Jobs, budgets, worker, admission, review, application, revalidation |
| `src/recalith/providers/` | Isolated inference backends and capability certification |
| `src/recalith/retrieval/` | Eligibility, indexes, ranking, packets, delivery accounting |
| `src/recalith/privacy/` | Retention, capsules, forgetting, tombstones |
| `src/recalith/integrations/` | Claude, Codex, generic JSON, and MCP adapters |
| `src/recalith/transfers/` | Export/import and Breadcrumbs migration |
| `src/recalith/cli/` | Argument parsing and formatting only |
| `src/recalith/prompts/` | Versioned extraction, review, and revalidation prompts |
| `tests/unit/`, `tests/integration/`, `tests/platform/` | Deterministic suites |
| `tests/fixtures/`, `evals/` | Sanitized fixtures, gold labels, live-agent evaluation |

## Early external-dependency check

### Task 0: Certify one inference route with a standalone probe

**Files:** Create `tools/probe_provider.py`, `tests/fixtures/providers/isolation/`, and `docs/host-compatibility.json` using the fields in SOURCES_AND_REUSE §5. This harness may be replaced by the production adapter after its sanitized fixtures are retained.

**Interfaces:** `probe_provider(config_path: Path, output_path: Path) -> int`; configuration identifies an explicit executable/version/model/auth route and the bounded test invocation. Return 0 only for a complete observed certification, 4 when unavailable. No engine imports or production memory store are required.

- [ ] Define fixtures with harmless sentinel user/project instructions, native memory, a sentinel hook, and a dummy MCP server; declare the expected effective inventory to be empty. A hook that runs and is merely ignored fails this probe.
- [ ] Run `python tools/probe_provider.py --config LOCAL_CONFIG --output docs/host-compatibility.json` against an explicitly configured account route. Before implementation, expect missing harness; after it exists, uncertified routes return 4 with the failed dimension.
- [ ] Implement timeout/output bounds, inherited-config checks, tool inventory inspection, sanitized diagnostics, and negative sentinel tests. Record the operator's checked background-use eligibility and managed-control constraints without treating a CLI flag as permission.
- [ ] Run the same provider probe from clean and deliberately host-marked parent fixtures. Build the fresh allowlisted child environment and assert registered host markers are absent, the current curator marker remains, unrelated credentials are absent, and required selected authentication still works. Include both `CLAUDECODE` and `CLAUDE_CODE_CHILD_SESSION` when supported by the installed version (A28/A67). The fixture never sanitizes a public CLI caller into operator authority.
- [ ] Certify Claude CLI first if available. Treat Codex inference as unavailable unless it separately passes; it remains a planned capture host. Never silently switch authentication, provider, or model to obtain a pass.
- [ ] Commit the harness/fixtures/report as `test: establish effective provider isolation before engine build`.

**Gate:** A report names exactly what was observed, what remains unknown, and the usable route. Unknown effective isolation is a blocker for that provider, not for finishing deterministic kernel work.

### Task 0b: Probe real host delivery before engine construction

**Files:** Create `tools/probe_delivery.py`, `tools/fixtures/delivery_stub.py`, `tests/fixtures/hosts/claude/delivery/`, and `tests/unit/test_delivery_probe.py`; extend Task 0's `docs/host-compatibility.json` without overwriting its provider results.

**Interfaces:** `probe_delivery(config_path: Path, output_path: Path) -> int`. Inputs name exact host/model/configuration, a disposable fixture workspace, and the four intended paths. Return 0 only when required start/prompt controls pass, 4 when a required capability is unavailable, 8 when a supported required path is degraded. Optional-path results are separately recorded. No engine, memory database, or production capture hook is needed.

- [ ] Write `test_probe_rejects_stdout_only_success`, `test_probe_rejects_nonce_contamination`, `test_missing_prompt_blocks_required_delivery`, and `test_missing_pre_action_is_optional`. The stub is a fixture, not a product delivery implementation. Pin the three-positive/three-negative controls and exact response evidence required by A61.
- [ ] Run `python -m pytest tests/unit/test_delivery_probe.py -q`; expect missing probe behavior until implemented.
- [ ] Implement temporary, owned hook configuration and a bounded nonce-only stub for session start, prompt, pre-action and post-compaction. Do not expose the nonce through another prompt, repository file or tool output. Preserve unrelated configuration and remove only owned probe entries on completion/failure. Mark unsupported paths unavailable rather than fabricating successful controls.
- [ ] Run `python tools/probe_delivery.py --config LOCAL_CONFIG --output docs/host-compatibility.json` against the actual configured Claude host. Retain sanitized observed responses, versions, contamination checks and all four path verdicts. The setup may use the disposable workspace directly; no `recalith init` or token registry exists yet.
- [ ] Commit as `test: establish host delivery visibility before core build`.

**Gate:** Required start/prompt feasibility is known before Task 1; optional gaps inform prompt fallback. A passing stub probe establishes host-path feasibility only. Task 13 must pass the same harness using the real engine, source fencing, budgets and delivery accounting. A source-document update or second plan package is not a substitute for this probe.

## Subproject A — durable local kernel

### Task 1: Establish the repository and executable contracts

**Files:** Create `pyproject.toml`, `uv.lock`, `src/recalith/__init__.py`, `src/recalith/contracts/{common,config,events,memory,operations,context,jobs,privacy,transfers,health}.py`, `tests/unit/test_contracts.py`, `tests/conftest.py`, and `.github/workflows/ci.yml`. Establish `evals/scenarios/smoke/`, its gold labels, and `tests/coverage_manifest.json` now; reserve the separate 12 held-out scenarios for the full run.

**Interfaces:** Produce all DTOs defined in DATA_CONTRACTS. Add `RecalithError(code: str, message: str)` for service failures; stable codes include `foreign_installation`, `invalid_schema`, `revision_conflict`, `capability_unavailable`, `storage_failure`, and `policy_refused`, `not_captured`, `capability_degraded`, `event_identity_conflict`, `backup_unavailable_after_forget`, and `installation_relocated` (added in Task 2, decision 0003). Test factories create valid envelopes/contexts; they never implement production decisions.

- [ ] Write `test_event_rejects_unknown_fields`, `test_provider_cannot_set_actor`, and `test_scope_unknown_is_not_true`. Assert validation rejects extra authority fields, provider-supplied installation mutations, invalid timestamps, and nonfinite JSON values.
- [ ] Run `python -m pytest tests/unit/test_contracts.py -q`; expect missing-contract failures before implementation.
- [ ] Implement strict models, generated schema snapshots, UTC/ID/digest validation, and the defaults copied from SYSTEM_SPEC. Add pinned dependency resolution and CI for the stated Python matrix.
- [ ] Rerun the contract suite and compare generated schemas to approved snapshots. Expect all tests to pass and no unversioned schema drift.
- [ ] Commit as `feat: define project memory contracts`.

**Gate:** Every worker/service task imports these contracts. Fast hooks consume generated primitive validators and shared fixtures; no separate hand-maintained competing schema or Pydantic import is allowed.

### Task 2: Independent installation and transactional store

**Release slice:** Preview includes local initialization, clone/move handling, one workspace, and missing-runtime behavior. Attachment, project fork, and shared configuration remain unavailable until full.

**Files:** Create `bootstrap.py`, `src/recalith/core/{identity,paths}.py`, `src/recalith/storage/{db,repository}.py`, `src/recalith/storage/migrations/0001.sql`, `tests/integration/test_installations.py`, `tests/platform/test_paths.py`.

**Interfaces:** Produce `initialize_installation(root: Path, config: ProjectConfig) -> InstallationContext`, `resolve_installation(root: Path, *, actor: Actor) -> InstallationContext`, and `open_store(ctx: InstallationContext, *, readonly: bool = False) -> Store`.

- [ ] Write `test_two_installations_have_separate_ids_and_databases`, `test_foreign_installation_is_rejected`, `test_unknown_schema_cannot_write`, and `test_path_escape_is_refused`. Assert A01–A04 and A33 through actual opened databases and registered roots.
- [ ] Run `python -m pytest tests/integration/test_installations.py tests/platform/test_paths.py -q`; expect missing initialization/storage failures.
- [ ] Implement the directory layout, exact local runtime launcher, first schema, foreign keys, WAL/FULL settings, revision checks, and 250 ms busy timeout. Runtime provisioning may resolve only the explicitly supplied pinned wheel/digest. No hook-time download.
- [ ] Verify reopening, independent schema versions, relocation detection, and restrictive local permissions. Use native Windows junction/case fixtures, a macOS case-insensitive APFS fixture, and a Linux casefold-enabled fixture where the platform suite provisions it. If that filesystem cannot be provisioned, report the exact coverage gap; a case-sensitive ext4 test cannot claim case-insensitive coverage. Verify A33 and equivalent-path identity without lowercasing paths indiscriminately.
- [ ] Commit as `feat: add isolated project installation and store`.

### Task 3: Durable event capture and source cursors

**Files:** Create `storage/spool.py`, `capture/{normalize,redact,sources}.py`, `tests/integration/test_capture_recovery.py`, `tests/unit/test_redaction.py` under their stated source/test roots. Task 3 also added `storage/failpoints.py`, `capture/{parsers,provenance,pipeline}.py` (certified parsers, runtime provenance, `capture`/`ingest_ready`), `tests/unit/test_normalize.py`, `tests/integration/test_runtime_provenance.py` and the test-only scenario/crash driver `tests/integration/capture_scenarios.py` (decision 0004).

**Interfaces:** Consume `EventEnvelope` and `InstallationContext`. Produce `capture(ctx, events: Sequence[EventEnvelope]) -> CaptureReceipt` and `ingest_ready(ctx, *, limit: int = 100) -> IngestResult`.

- [ ] Write failpoint tests `test_publish_before_cursor_replays_once`, `test_commit_before_unlink_replays_once`, `test_disk_full_does_not_acknowledge`, and `test_secret_never_reaches_spool`. Assert A05–A09 and A34, including exact event/support counts.
- [ ] Run `python -m pytest tests/integration/test_capture_recovery.py tests/unit/test_redaction.py -q`; expect failure before the durable sequence exists.
- [ ] Implement atomic segments, scrub-before-write, caps/coverage, durable cursor ordering, the separate `source_conflicts` table, typed assertions, reserved-false expected_red validation, declared/observed runtime provenance tied to executable/workspace, stale observations after registered executable fingerprint changes (unknown at query until refreshed), allowlisted environment capture, head/tail/error-signature preservation, one bounded Windows publication retry, and transactionally created ingestion jobs. Assert A49, A52, A54, and A68 as well as A05–A09. Adapt selected Breadcrumbs path/redaction behavior only after the dependency/license review.
- [ ] Repeat every crash failpoint and inspect the reopened store. All accepted normalized events must remain available exactly once; rejected capture must not advance the cursor.
- [ ] Commit as `feat: capture events durably with replay recovery`.

### Task 3b: Capture-only real Claude adapter and fast-path boundary

**Files:** Create `src/recalith/fast/{__init__,wire,spool,session,claude_capture,entry}.py`, `tools/generate_hook_wire.py`, `tests/platform/test_hook_imports.py`, `tests/platform/test_capture_only_claude.py`, and `tests/fixtures/hosts/claude/<version>/`. Task 3b also moved the stdlib `storage/{spool,failpoints}.py` and `capture/{redact,parsers}.py` into `fast/` (old names alias the same modules) and the normalization core into `fast/normalize.py`, and added the generated `fast/wire_generated.py`, `capture/hooks.py` (hook context manifest), the `.recalith/bin/recalith-hook` launchers, `tools/capture_claude_fixtures.py` with `tools/fixtures/hook_recorder.py`, `tools/measure_hook_latency.py` and `tests/platform/claude_fixtures.py` (decision 0005).

**Interfaces:** Produce the primitive `hook_capture` and `handle_hook` capture branch from DATA_CONTRACTS §2.3. Reuse the same spool format and wire fixtures as Task 3. Full delivery is deferred to Tasks 11–13.

- [ ] Write `test_capture_only_real_lifecycle`, `test_fast_entry_imports_only_stdlib_and_fast`, `test_missing_runtime_is_nonblocking`, `test_head_tail_keeps_failure_line`, and `test_fast_and_strict_validation_agree`. Assert A07–A09, A53, A58, A68, and A70 on actual serialized events.
- [ ] Run `python -m pytest tests/platform/test_hook_imports.py -q`; expect missing entry point, then require a clean fresh-process import inventory, including package initializers and failure paths.
- [ ] Implement capture-only start/prompt/tool/compaction/stop/end normalization, source registration, immutable call identity, scrubbed scratch outcomes, and curator-session rejection. Preserve a coverage gap for unsupported host events. Follow DATA_CONTRACTS §2.3 event-to-branch mapping with delivery disabled, and instrument the shared 250 ms soft deadline from entry. Do not claim that the clock bounds a blocked fsync.
- [ ] Run `python -m pytest tests/platform/test_capture_only_claude.py -q` against the configured installed host; capture sanitized real payloads/transcript boundaries and record warm/cold hook latency. Verify the absent-runtime launcher does not fail every tool call or download anything.
- [ ] Commit as `feat: validate real Claude capture before memory inference`.

**Gate:** The spool accepts real current-version events and satisfies the stdlib import rule. Timing is measured now; no claim of context delivery is made at this capture-only stage.

### Task 4: Queue, budgets, and project worker

**Release slice:** Preview implements persistent 1-second active/5-second idle polling and the 5-second p95 typed-state target. Session mode, `fast/wake.py`, IPC tests, and the 2-second healthy-wake target are full-only.

**Files:** Create `controller/{jobs,budgets,worker}.py`, `fast/wake.py`, `tests/integration/test_worker.py`, `tests/platform/test_worker_lifecycle.py`, and the shared stdlib `fast/process_env.py`. The preview slice also added `controller/launch.py` (bounded model-child launch with process-tree containment), the test helpers `tests/integration/worker_scenarios.py` (fake clock/backends and the kill/restart driver) and `tests/platform/worker_hosts.py` (simulated hosts), `tests/fixtures/providers/fake_backend.py`, `tools/measure_worker_latency.py`, and hook-context `context_schema` 2 (decision 0006). `fast/wake.py` is full-only and not created in preview.

**Interfaces:** Produce `lease_next(ctx, *, owner: str, now: UtcTime) -> Job|None` and `run_worker(ctx, *, mode: str) -> int`. Jobs use the exact state/idempotency contract.

- [ ] Write `test_only_one_worker_per_installation`, `test_expired_lease_is_fenced`, `test_budget_reservation_precedes_launch`, and `test_resume_coalesces_overdue_jobs`. Assert A21, A30, A31, A45, and A50; two independent installations may run workers concurrently.
- [ ] Run `python -m pytest tests/integration/test_worker.py tests/platform/test_worker_lifecycle.py -q`; expect missing lease/budget behavior.
- [ ] Implement preview persistent polling and OS lock; add session mode and the bounded installation-local IPC wake hint only for full. In both profiles implement due-job prioritization, lease generations, UTC-day protected/ordinary reservations, purpose-specific output allowances, separate raw-envelope/body limits, code-assigned correction/declaration review priority ahead of ordinary review and extraction, and stated retry/backoff limits. Add `test_ordinary_cannot_spend_protected_pool` and `test_review_can_borrow_remaining_ordinary_pool`; typed task updates consume zero model calls and stay responsive during model execution. Add `test_declaration_review_precedes_ordinary_review`, `test_declaration_cannot_bypass_exhausted_budget`, and `test_typed_ingestion_runs_while_model_is_pending` (A50). A job is launch-eligible only when due, leaseable and its reservation fits; waiting-budget reasons stay visible. Keep provider execution behind a fake backend here. Add `test_15kb_episode_body_with_host_envelope_fits`, `test_body_and_wire_caps_are_separate`, and `test_five_candidates_use_one_review_call` (the latter completes against Task 9). Exercise the 48-call fully reserved example and input limits; 90 is only the call ceiling.
- [ ] Kill and restart workers at lease/commit boundaries; verify no late result or duplicate worker applies changes. Test Windows process-tree lifecycle natively and add preview `test_idle_poll_state_available_within_five_seconds`; full adds `test_idle_worker_wakes_within_two_seconds` and `test_failed_wake_preserves_spool_and_reports_lag`. The hook must not wait on worker startup or ingestion. Add `test_hook_spawn_clears_host_markers`, `test_worker_sets_its_own_role_marker`, and native `test_hook_started_worker_survives_host_termination`; close inherited handles and certify actual detachment/Job Object behavior, reporting degraded independence if the host prevents it (A45/A67). Do not silently change host-managed controls.
- [ ] Commit as `feat: add bounded project worker and job scheduling`.

### Task 5: Mutation application and optimistic concurrency

**Release slice:** Preview implements all transaction/revision/undo rules; reserve but do not populate revision-chain schema. `storage/integrity.py`, chain computation, and full/incremental integrity tests are full-only.

**Files:** Create `controller/{apply,admission}.py`, `core/policy.py`, `storage/integrity.py`, `tests/integration/test_operations.py`, `tests/integration/test_integrity.py`. The preview slice also added `storage/records.py` (revision/head/link writers), `storage/migrations/0002.sql` (schema 2), the test builders `tests/integration/operation_scenarios.py` (real captured events, seeded records, the kill/restart scenario), and `ModelResponse.malformed`/`UndoPreview` contracts (decision 0007). `storage/integrity.py` is full-only and not created in preview; `test_integrity.py` marks its full-only tests unavailable.

**Interfaces:** Produce `evaluate_operation(ctx, operation: ProposedOperation, read_set: ReadSet) -> AdmissionDecision` and `apply_proposal(ctx, job: Job, response: ModelResponse) -> ApplyResult`. Initial admission handles schema/identity/revisions; semantic evidence rules arrive in Task 9.

- [ ] Write `test_duplicate_proposal_has_one_effect`, `test_replacement_and_retirement_commit_together`, `test_changed_read_set_requeues`, and `test_unrelated_group_can_survive_rejection`. Assert A14 and A19–A21 with actual transactions.
- [ ] Run `python -m pytest tests/integration/test_operations.py -q`; expect missing transactional application.
- [ ] Persist proposals before applying, resolve local refs, topologically group dependent operations, assign deterministic operation IDs, check fencing/read sets, and atomically advance store revision plus guidance epoch for serving-relevant changes. Bookkeeping-only mutations must not invalidate guidance caches. Implement compensating undo previews with conflict detection and, in full only, the transactional revision hash chain. Add `test_unlogged_row_mutation_is_detected` and `test_authorized_purge_extends_chain` for full A65; also test incremental verification coverage versus `doctor --full-integrity`, and baseline the preview store when chain support is first activated without inventing a chain for old mutations. Do not claim resistance to a same-user rewrite of the entire store and chain.
- [ ] Reapply identical proposals and simulate concurrent revisions. Assert no duplicate confirmations or partially retired claims. Verify A41's consistent revision behavior.
- [ ] Commit as `feat: apply memory operations transactionally`.

**Subproject A gate:** Real capture, scoped stores, replay-safe jobs, conflict quarantine, import-clean hooks, and atomic mutation work with fake proposals. Report Task 0 certification separately. Recheck Review focus 1–5 against all components built so far; unavailable future delivery tests remain explicitly pending, never silently passed.

## Subproject B — working state and inference boundary

### Task 6: Tasks, episodes, and cross-session continuity

**Files:** Create `working/{segment,reducer,tasks,bindings}.py`, `episodes/{segment,condense}.py`, `tests/integration/test_working_memory.py`, `tests/integration/test_episodes.py`. The task also added `storage/migrations/0003.sql` (schema 3: binding-head columns, `tool_calls`, reducer bookkeeping), the controller-only operation kinds `create_task`/`bind_events`/`record_boundary` and `controller.apply.apply_in_transaction`, the `failpoints.REDUCTION` family, and the test builders `tests/integration/working_scenarios.py` (real 2.1.301 payloads, named synthetic variants, recorded proposals, the reduction kill/restart scenario) (decision 0008).

**Interfaces:** Produce `reduce_task(ctx, task_id: Id, events: Sequence[EventEnvelope]) -> TaskState` and `build_episode(ctx, task_id: Id, event_ids: Sequence[Id]) -> Episode`. Also produce `propose_task_boundaries(ctx, events) -> list[TaskBoundaryCandidate]` and `resolve_task_binding(ctx, proposal) -> ApplyResult` through Task 5. These build proposed state/episode bodies; persistence goes through Task 5. Deterministic reducers set only supported typed facts; model narrative patches use the same write path later.

- [ ] Write `test_parallel_tasks_keep_distinct_next_actions`, `test_idle_does_not_complete_task`, `test_failure_and_fix_cross_chunk_boundary`, and `test_expected_red_test_is_not_a_failed_approach`. Assert A10–A13 and A57. Add `test_provisional_split_preserves_late_result`, `test_rejected_split_keeps_objective`, and `test_new_session_can_link_without_merging_tasks`. Add `test_single_active_task_links_without_model_budget`, `test_ambiguous_tasks_do_not_autolink`, and `test_src_tests_docs_do_not_propose_a_boundary`. Verify linked placeholders do not count as active tasks, a later split preserves both objectives, and no model call occurs under exhaustion. Recorded proposals exercise mechanics; live segmentation quality is measured later.
- [ ] Run `python -m pytest tests/integration/test_working_memory.py tests/integration/test_episodes.py -q`; expect missing task/episode behavior.
- [ ] Implement deterministic boundary proposals, versioned provisional bindings, atomic reviewed and deterministic provisional reassignment, explicit patches, pending-result joins, compaction checkpoints, episode boundaries, and successful-result preservation. Carry context across chunks without treating carried context as new evidence.
- [ ] Verify restoration after restart and compaction. A task must retain its blockers and pending actions until evidence closes them.
- [ ] Commit as `feat: maintain task state and connected episodes`.

### Task 7: Provider certification and isolated inference

**Files:** Create `providers/{base,isolation,claude_cli,json_process}.py`, `controller/requests.py`, `tests/unit/test_provider_contract.py`, `tests/platform/test_provider_isolation.py`; extend the `docs/host-compatibility.json` created by Task 0. The task also added `providers/errors.py`, the package-data sentinel fixtures `providers/sentinels/` (byte-identical to the Task 0 fixtures), the versioned prompts `src/recalith/prompts/`, `tools/check_provider_runtime.py` (`sections.provider_runtime`), `probe_provider.py --route-out`, the `failpoints.PROVIDER` family, `tests/integration/test_requests.py` and the crash builder `tests/integration/provider_scenarios.py`; narrative jobs are scheduled by typed reduction (decision 0009). `codex_cli.py` is not built (no separate probe has passed).

**Interfaces:** Produce `prepare_model_request(ctx, job: Job) -> ModelRequest` and provider `complete(request: ModelRequest, config: ProviderConfig) -> ModelResponse`.

- [ ] Write `test_provider_never_receives_other_project`, `test_unknown_capabilities_disable_backend`, `test_auth_route_change_is_visible`, `test_timeout_terminates_process_tree`, and `test_output_flood_is_bounded`, `test_envelope_is_bounded_before_body_validation`, and `test_15kb_episode_response_is_accepted`. Assert A28–A30, A47, and A67. Add `test_user_level_hooks_and_memory_are_absent` and `test_recursion_marker_is_not_no_hooks_proof`.
- [ ] Run `python -m pytest tests/unit/test_provider_contract.py tests/platform/test_provider_isolation.py -q`; expect missing isolation/capability enforcement.
- [ ] Implement argument-array execution, stdin input, schema validation, the shared explicit environment allowlist with only selected auth/config/OS keys and correct role marker, isolated cwd, recursion markers, no-tools certification, caps, and usage accounting. Integrate Task 0 fixtures and record tested flags, effective user/project/managed configuration, native-memory state, and exact versions. `codex_cli.py` is optional only after a successful separate probe. Leave an uncertifiable backend explicitly unavailable; do not invent a no-tools flag.
- [ ] Run real installed-CLI probes using a harmless fixture. Inspect effective tool exposure, inherited context, authentication route, output schema, cancellation, and child processes. At least one backend must pass before autonomous extraction proceeds. Re-run the inherited-host-marker case from Task 0 through a worker started by the actual hook; certify effective tools/customization isolation as well as key removal.
- [ ] Commit as `feat: add certified inference provider adapters`.

### Task 8: Source lineage and applicability

**Files:** Create `core/{lineage,conditions}.py`, `tests/unit/test_lineage.py`, `tests/unit/test_conditions.py`. The task also added `storage/migrations/0004.sql` (schema 4: `root_event_members`, `root_tokens`), root registration inside `capture.pipeline.ingest_ready`, class-based support novelty and `last_supported_at` in `controller/apply.py`, the record-link root check in `controller/admission.py`, `ContextQuery.branch_ref`, the `failpoints.LINEAGE` family (`roots.after_merge`), the test builders `tests/integration/lineage_scenarios.py` (real payloads, named variants, a synthetic certified experiment domain, the merge kill/restart scenario) and the matrix `test_lineage_merge_crash_matches_reference` (decision 0010).

**Interfaces:** Consume `EvidenceLink`, `Condition`, `Scope`, and `ActionDescriptor`. Produce `independent_roots(ctx: InstallationContext, evidence: Sequence[EvidenceLink], *, proposition_key: JsonObject) -> set[Id]` returning canonical root-class IDs and `evaluate_conditions(conditions: Sequence[Condition], query: ContextQuery) -> str`, returning exactly `true`, `false`, or `unknown`.

- [ ] Write `test_memory_echo_cannot_confirm`, `test_shared_subagent_source_counts_once`, `test_new_observation_after_retrieval_can_support`, `test_scope_precedes_similarity`, and `test_unknown_condition_cannot_caution`. Assert A16–A18, A23, A32, A56, A62, and A70. Add unchanged-rerun, contradictory-rerun, missing-dependency, distinct-artifact, forwarded-subagent, and genuinely new-experiment cases.
- [ ] Run `python -m pytest tests/unit/test_lineage.py tests/unit/test_conditions.py -q`; expect missing lineage/condition evaluation.
- [ ] Implement provenance traversal with cycle detection, canonical origin descriptors, equivalence classes/aliases, conservative unknown dependencies, branch annotations versus explicit branch predicates, tri-state evaluation, exclusions, and PEP 440 comparisons through the pinned dependency. Treat unparsable version strings as unknown unless exact comparison is specified.
- [ ] Verify both legitimate imperative preferences and hostile quoted instructions. No authority increase may come from agent paraphrase alone.
- [ ] Commit as `feat: enforce evidence lineage and applicability`.

**Subproject B gate:** Separate/provisionally bound tasks, connected episodes, a certified inference backend, and codable root-class/applicability rules work with captured real fixtures. Recheck all five Review focus items, including current host isolation and concurrent task paths.

## Subproject C — autonomous knowledge and delivery

### Task 9: Claim extraction and deterministic admission

**Files:** Create `controller/{extract,review,triggers}.py`, extend `controller/admission.py`, create `prompts/{extract_v1,review_v1}.md`, `tests/integration/test_claim_admission.py`. The task also added `core/regions.py` (nondeclaration regions), `storage/migrations/0005.sql` (schema 5: `review_requests`, `review_outcomes`, debounce columns, `trigger_cursor`), the `failpoints.ADMISSION` family, the prompt files as `recalith.prompts` package data (they are versions `extract_claims@1`/`review_claims@1`), the test builders `tests/integration/admission_scenarios.py` (real payloads, named variants, recorded proposals, the kill/restart scenario) and the matrix `test_claim_admission_crash_matches_reference` (decision 0011).

**Interfaces:** Consume Tasks 5–8. Produce `review_candidates(ctx, claim_ids: Sequence[Id], *, job: Job) -> ModelResponse`; extraction returns the standard `ModelResponse` and never writes records directly.

- [ ] Write `test_quote_exists_but_cause_is_unsupported`, `test_typed_declaration_waits_for_review`, `test_inferred_claim_waits_for_review`, and `test_retrieval_count_never_increases_strength`. Assert A14–A17, A60, and A66. Every durable declaration route requires review, including typed CLI; do not admit a declaration when its review is budget-paused. Add pasted first-person prose, fenced/quoted declarations, and uncertain authorship cases.
- [ ] Run `python -m pytest tests/integration/test_claim_admission.py -q` with recorded proposals; expect missing evidence-policy behavior.
- [ ] Implement bounded input selection, no-op extraction, narrow scope, operation-specific gates, and separate review over original evidence. Persist bounded ReviewBatch snapshots, stable eight-candidate/input/output partitions, and per-candidate verdicts. Pin the adversarial `review_v1.md` separately; strip all proposal `reason` fields from review inputs and retain original evidence. Test five claims in one fitting review call, input/output splits, missing/duplicate verdicts, stale candidate digests, and a candidate too large to review safely (A50/A60). Add exact rejection reason codes and candidate-only degradation when review is unavailable. If useful revision objections cannot fit the fixed fields, require `reject` with `review_capacity`; never truncate a revise or treat capacity failure as factual disproof. Exercise it in A60. Implement deterministic six-event/ten-minute failure debounce, reserved-false expected_red validation, null-family time/count behavior, and same-task/action-family success cancellation across changed dependency fingerprints.
- [ ] Run the extraction/admission slices of the 12-scenario non-held-out smoke subset once configured; complete live-agent recall/revision trials after delivery is integrated. Fix fabricated support and overgeneralization before tuning recall. Record model/prompt versions and retain failed examples privately.
- [ ] Commit as `feat: derive and admit evidence-backed knowledge`.

### Task 10: Consolidation and autonomous revision

**Files:** Create `controller/{planner,revalidate}.py`, `prompts/revalidate_v1.md`, `tests/integration/test_consolidation.py`. The task also added `storage/migrations/0006.sql` (schema 6: `claim_rechecks`, `pending_supersessions`, `intent_questions`, `artifact_writes`, `planner_state`), `ClaimRevision.context` and `ReviseClaimPayload.retry_conditions`, FailureRecheck/dependency/source-conflict hooks in `capture.pipeline.ingest_ready`, the revalidation settle, held supersessions and deferred rechecks in `controller/apply.py`, dependency resolution and the invalidation/declaration gates in `controller/admission.py`, the revalidation request read set in `controller/requests.py`, the consolidation band (`jobs.BAND_CONSOLIDATION`), the planner in the worker's deterministic poll, the `failpoints.REVISION` family, ID prefixes `rchk`/`qst`, the test builders `tests/integration/consolidation_scenarios.py` and the matrix `test_revision_crash_matches_reference` (decision 0012).

**Interfaces:** Produce `revalidate_dependents(ctx, changes: Sequence[DependencyChange]) -> list[Id]`. Planner creates existing Job types; it cannot create arbitrary executables.

- [ ] Write `test_changed_dependency_marks_for_revalidation`, `test_explicit_replacement_is_atomic`, `test_unknown_conflict_remains_visible`, `test_fixed_failure_allows_retry`, and `test_derived_writes_do_not_loop`. Assert A18–A22, A43–A44, A51, and A62. A dependency-preserving merge keeps applicability; a changed dependency suppresses caution immediately pending revalidation. Add `test_success_caps_existing_failure_before_model_call`, `test_cross_session_success_matches_action_family`, and `test_old_or_unknown_order_success_does_not_assert_contradiction`. Include a failure with no declared dependency, empty conditions, and a model budget of zero; it never earns caution from empty dependencies and its freshness still changes deterministically.
- [ ] Run `python -m pytest tests/integration/test_consolidation.py -q`; expect missing revision scheduling.
- [ ] Implement deterministic volatile/stable review classes, transitive claim-dependency handling, dependency indexes, deterministic candidate groups, model-reviewed scope-aware changes, coalescing, bounded evidence expansion, and causal-loop suppression. Ingestion also applies FailureRecheck context evidence, freshness change, guidance epoch, and revalidation enqueue atomically before model work. Conditional historical truth is retained; successful execution is not automatically a logical contradiction. Consolidation prioritizes current conflicts over cosmetic merges.
- [ ] Replay corrected decisions and successful procedures. Assert historical attempts remain true as history while obsolete guidance is withdrawn.
- [ ] Commit as `feat: consolidate and revalidate project knowledge`.

### Task 11: Retrieval and context composition

**Files:** Create `retrieval/{index,search,compile}.py`, `fast/{cache,context,fence}.py`, `tests/integration/test_retrieval.py`. The task also added `storage/migrations/0007.sql` (schema 7: `projection_state`, `retrieval_docs`, revision-store indexes), the worker's projection step (`retrieval.compile.refresh_projection`, every poll), `capture.provenance.environment_values_in` (resolution inside a snapshot), generated wire validators for `ContextQuery`/`ContextPacket`, the `failpoints.RETRIEVAL` family, the test builders `tests/integration/retrieval_scenarios.py`, the matrix `test_projection_crash_matches_reference`, the stdlib audit `test_hook_context_compiler_is_stdlib_and_read_only` and `tools/measure_compile_latency.py` (decision 0013).

**Interfaces:** Produce `retrieve(ctx, query: ContextQuery) -> list[ContextItem]` and `compile_context(ctx, query: ContextQuery) -> ContextPacket`.

- [ ] Write `test_scope_filter_runs_before_limit`, `test_current_query_excludes_retired_claims`, `test_warning_contains_cause_and_retry_condition`, and `test_packet_budget_is_enforced`. Assert A01, A18, A23–A25, and A69. Exercise every strength/freshness/evidence row and reason-code shape; expired support cannot enter automatic context. Add `test_receipt_does_not_invalidate_guidance_cache` and `test_evidence_change_advances_guidance_epoch`.
- [ ] Run `python -m pytest tests/integration/test_retrieval.py -q`; expect missing retrieval/packet assembly.
- [ ] Implement structural and lexical candidates, FTS5 capability detection with token-index fallback, eligible neighbor expansion, deterministic ranking, tri-state applicability, and exact specified byte-to-token estimation. Pre-serialize bounded candidate/fallback views for the standard-library hook compiler; include recent typed observations separately from claims. Implement final read-only store/guidance/policy/tombstone fencing and bounded live dependency checks. Full service queries may use strict DTOs; hook functions may not import them.
- [ ] Run relevance controls and 10,000-claim corpus checks. Exclude status/scope mismatches before candidate caps. Verify stale projections fall back or return degraded without old guidance.
- [ ] Commit as `feat: retrieve and compile bounded current context`.

### Task 12a: Public service and CLI contracts

**Files:** Create `src/recalith/service.py`, `src/recalith/cli/{main,inspect,mutate,operator_guard}.py`, `src/recalith/__main__.py`, and `tests/integration/test_cli.py`. The task also added `src/recalith/cli/__init__.py`, `capture.pipeline.ingest_in_transaction` (the ingestion helper the guarded writes reuse), `apply_in_transaction(..., review_origin=)`, `jobs.retry`, operator-token verifier tables in `local.toml` (`core.identity.operator_tokens`/`update_operator_tokens`, `initialize_installation(..., operator_verifiers=)`), the failpoints `service.after_event`, `service.after_commit` and `init.after_store`, the builders `tests/integration/cli_scenarios.py`, the kill/restart matrix `test_service_write_crash_matches_reference` and the layering audits in `tests/platform/test_hook_imports.py` (decision 0014; no schema change).

**Interfaces:** Produce `declare(ctx: InstallationContext, kind: str, statement: str, scope: Scope) -> ApplyResult` under the operator-only policy and expose implemented domain operations through the exact CLI forms in DATA_CONTRACTS, including `declare`, `correct`, `integrate --remove`, operator token-file forms, and exit codes 6/7/8. Service results never print and never import a host entry point.

- [ ] Write `test_json_stdout_is_one_object`, `test_observe_not_captured_returns_7`, `test_degraded_capability_returns_8`, and `test_operator_declaration_is_not_agent_authority`. Assert A32, A60, A72, and A73 through real public service/CLI calls. Add `test_agent_channel_cannot_declare_or_forget`, parameterized over every guarded form, TTY present/absent, token present/absent, installed launcher/module spellings, and host/curator markers. Verify a healthy refusal audit contains no statement/token/argv content. Add `test_preinit_token_bootstraps_without_tty`, `test_noninteractive_cannot_mint_token`, `test_missing_or_revoked_token_returns_6`, `test_marked_ide_tty_plus_token_still_refused`, and `test_registered_hook_starts_worker_without_operator_cli`. Pre-init refuses without creating a store; its token command bypasses installation lookup, not the caller guard. Use an explicitly provisioned fixture token for evaluation/CI initialization. Add an unmarked noninteractive refusal and positive human TTY/token workflow. Disk-full audit failure must still refuse.
- [ ] Run `python -m pytest tests/integration/test_cli.py -q`; expect missing transport behavior before implementation.
- [ ] Implement stable CLI parsing/formatting, bounded inspection, guard-before-actor-assignment, pre-init standalone token creation/verification and strict IDE-terminal refusal guidance, no-bypass declaration dispatch, atomic immediate correction invalidation plus queued replacement review, source-preserving error responses, and service/MCP-ready results. Do not implement business policy in the CLI.
- [ ] Compare service and direct domain results; verify unavailable later-stage commands return an explicit capability result until their owning task is complete.
- [ ] Commit as `feat: expose project memory service and CLI contracts`.

### Task 12b: Delivery accounting, session overlay, and corrections

**Files:** Create `src/recalith/retrieval/delivery.py`, extend `fast/{session,context,fence,entry}.py`, add `fast/delivery.py`, and create `tests/integration/test_delivery.py`, `tests/platform/test_session_scratch.py`. The task also added `storage/migrations/0008.sql` (schema 8: receipt columns on `deliveries`, one outcome link per delivery/label/observation), receipt/scratch contract fields with generated `DeliveryReceipt` wire validators, `context_schema` 3 manifests with per-adapter `delivery_paths` (`capture.hooks.write_hook_context(..., delivery_paths=)`), receipt accounting and outcome links in `capture.pipeline.ingest_in_transaction`, `service.record_delivery`, the `failpoints.DELIVERY` family, the builders `tests/integration/delivery_scenarios.py`, the kill/restart matrix `test_delivery_crash_matches_reference` and the delivery import audits in `tests/platform/test_hook_imports.py` (decision 0015).

**Interfaces:** Produce service `record_delivery(ctx, packet: ContextPacket, session_id: Id) -> DeliveryReceipt` by receipt spooling, plus the primitive `hook_compile_context`/`hook_record_delivery` and delivery branch of `handle_hook`. Worker ingestion owns database accounting.

- [ ] Write `test_counts_only_emitted_revisions`, `test_concurrent_hooks_preserve_budget`, `test_failure_overlay_precedes_ingestion`, `test_emission_crash_is_uncertain`, `test_compaction_restores_once`, and `test_correction_before_fence_removes_guidance`. Assert A24–A27, A41, A59, and A72.
- [ ] Run `python -m pytest tests/integration/test_delivery.py tests/platform/test_session_scratch.py -q`; expect missing scratch/fence/accounting behavior.
- [ ] Implement bounded session locks and atomic files, conservative pre-emission reservations, emitted/uncertain receipts, condition-aware suppression, compaction counters, correction/undo routing, and outcome links. Keep scratch TTL/eviction from resetting budget totals. Hooks never write SQLite. Enforce the shared soft deadline, mandatory reservation/fence versus optional outcome-overlay distinction, degradation reason codes, and no-task workspace lookup. Add slow-filesystem/zero-budget/WAL-SHM cases from A58, including a live worker mid-checkpoint. Add A24/A26/A59 coverage for the single 400-token prompt substitution allowance, 1,400 total cap, complete session charging, no per-caution multiplier, and no 400 bonus beyond a restoration's 2,000 cap.
- [ ] Inject races before/after the final fence and stdout flush. Changes committed before the fence suppress old text; already in-flight output after the fence is recorded as such, not falsely claimed retractable. Agent acknowledgment is not independent support or task success.
- [ ] Commit as `feat: account for delivery and same-session memory safely`.

**Subproject C gate:** With a certified inference backend and captured host fixtures, the system learns a supported lesson, recalls it in a fresh task, revises it after changed evidence, and keeps a second installation isolated. No working-agent memory-maintenance instruction is allowed in this demonstration. Recheck Review focus 1–5 across the full fast/service/worker path.

## Subproject D — host integration, operations, and release

### Task 13: Claude Code integration

**Release slice:** Preview certifies one Claude host and the two mandatory delivery paths, probes both optional paths, installs operator command protections, and probes/reports general private-path support. Shared configuration and general private-path installation are full-only.

**Files:** Extend Task 3b capture fixtures and create `fast/claude.py`, `integrations/claude.py`, `integrations/install.py`, versioned Claude fixtures, `tests/integration/test_claude_adapter.py`, `tests/platform/test_claude_smoke.py`.

**Interfaces:** Consume primitive `handle_hook` in synchronous hooks and the typed service interfaces in installer/diagnostics only. Adapter maps documented payloads to these operations and nonblocking host context. Installer pins the local launcher and preserves unrelated user hook configuration.

- [ ] Write `test_claude_capture_delivery_and_compact`, `test_curator_session_is_ignored`, and `test_hook_failure_never_denies_tool`. Assert A08, A27–A29, A33, A47, A53, A58, A61, and A65. Include missing runtime, local install, owned-entry removal, operator marker/command-denial coverage, and private-path capability probes. Full additionally tests shared install and actual private-path enforcement.
- [ ] Run `python -m pytest tests/integration/test_claude_adapter.py -q`; expect missing adapter mappings.
- [ ] Implement exact-version lifecycle capture, registered transcript supplement, subagent IDs, compaction restoration, and project-specific worker startup. Install locally by default; in full, opt into tracked settings only with `--shared`, and provide `integrate claude --remove` that removes only unchanged owned entries. Install certified administrative command deny patterns and exercise actual tool-subprocess markers (A73), preserving unrelated rules. Probe private-path rules without loosening controls or disabling hook access; preview reports the probe only and full installs the supported restrictions.
- [ ] Reuse Task 0b's harness with the real engine: probe all four delivery paths and run three positive/three negative controls for each supported path. Gate readiness only on session start and prompt; independently report pre-action/compact support, prompt fallback and timing gaps. Retain observable transcript/response evidence. Do not claim inspection of an inaccessible internal request. Verify survival/recovery around SessionEnd and forced host/terminal termination on each supported platform, specifically for a worker spawned by the registered hook path. A detached flag alone does not pass this test.
- [ ] Commit as `feat: integrate automatic Claude Code memory`.

**Cut 1 release gate — Claude autonomous preview:** After Task 13 plus the already completed Task 15 core, Task 16, Task 17 health, and Task 18 preview slices, run the Subproject C demonstration on a real certified Claude host and selected inference backend. Run the 12-scenario candidate/no-memory comparative smoke, three default-budget workload days, profile-applicable deterministic/failure tests, and all hook latency/usefulness gates. Demonstrate a fresh-session lesson, changed evidence, a legitimate retry, forgetting/restore, and an unaffected second independent project. Readiness must name `claude_preview` and every unavailable feature. No full 48-scenario superiority claim is permitted. This gate is a shippable preview, not merely Task 13's unit-test pass.

### Task 14: Codex, generic JSON, and optional MCP integration

**Release slice:** Full-only. Preview returns explicit unavailable capability states for Codex, generic JSON, and MCP.

**Files:** Create `fast/codex.py`, `integrations/{codex,generic,mcp}.py`, versioned Codex fixtures, `tests/integration/test_codex_adapter.py`, `tests/integration/test_generic_mcp.py`, `tests/platform/test_codex_smoke.py`.

**Interfaces:** Same service operations as Task 13. MCP exposes only the five named tools in DATA_CONTRACTS; generic JSON uses EventEnvelope/ContextPacket without new domain types.

- [ ] Write `test_codex_late_tool_result_pairs_once`, `test_codex_context_is_visible`, `test_mcp_availability_is_not_autonomy`, and `test_generic_adapter_cannot_claim_operator_authority`. Assert A08, A27, A32, A46–A47, A53, A58, A61, and A65. Keep Codex capture/delivery certification independent of Codex inference availability.
- [ ] Run `python -m pytest tests/integration/test_codex_adapter.py tests/integration/test_generic_mcp.py -q`; expect missing adapters.
- [ ] Implement documented lifecycle/tool paths, transcript parser version checks, installed-capability registry, and project-scoped registration. Treat unsupported hosted-tool coverage honestly.
- [ ] Run real Codex smoke tests and path-specific positive/negative canaries with async command completion and compaction. Inspect the effective permission profile; beta/legacy configuration differences must not be assumed compatible. Confirm captured IDs are not confused between parent/subagent sessions and that no memory permission decisions are emitted.
- [ ] Commit as `feat: integrate Codex and portable memory interfaces`.

### Task 15: Evidence retention and portable transfers

**Release slice:** Run the preview core slice before Task 16: consistent backups/ledger, default 180-day unpinned event retention, live-reference pins, and explicit missing-support downgrade handling. Capsule preservation and every transfer/importer feature are full-only.

**Files:** Create `privacy/retention.py`, `storage/backup.py`, `transfers/{export,importer,breadcrumbs}.py`, `tests/integration/test_transfers.py`, `tests/integration/test_retention.py`. The preview core (decision 0016) also adds `privacy/__init__.py`, `storage/migrations/0009.sql` (schema 9), the test builders `tests/integration/retention_scenarios.py` and the kill/restart matrix `test_retention_backup_crash_matches_reference` (`failpoints.RETENTION`, `failpoints.BACKUP`); `transfers/*` and `test_transfers.py` belong to the full slice and are not created yet.

**Interfaces:** Preview produces `backup` and pin-aware retention/ledger operations. Full adds `export_memory`, `import_memory`, `import_breadcrumbs`, and capsules using DATA_CONTRACTS signatures.

- [ ] **Preview core first:** Add `test_referenced_roots_do_not_expire`, `test_unreferenced_payloads_expire_at_180_days`, `test_backup_is_consistent`, and `test_backup_contains_current_ledger`. Implement snapshot verification, bounded backup retention, transitive live-owner reachability, atomic pin recheck versus expiry/admission, and honest guidance changes when support is actually lost. Add `test_pin_expiry_race_never_admits_missing_support`, `test_last_owner_release_allows_expiry`, and `test_forget_overrides_pin`. Retention alone cannot lower supported decisions/lessons; freshness policy remains separate. These are prerequisites for Task 16; A35 live-pin/unreferenced-expiry and A40 corrupt-backup variants block preview. Do not mark capsule/transfer tests passed. Pinned payloads may legitimately outlive the age threshold; report storage growth rather than pretending pins guarantee a fixed disk bound.

- [ ] **Full transfer/capsule slice:** Write `test_expiry_preserves_required_capsule`, `test_import_twice_does_not_confirm_twice`, `test_foreign_origin_is_not_local_authority`, and `test_breadcrumbs_source_is_unchanged`. Assert A35, A38–A39, A42, A55, and A71. Test capsule locators with nonzero original offsets, Unicode, and the same origin imported into two new installation IDs.
- [ ] Run the preview retention/backup subset now; full later runs `python -m pytest tests/integration/test_transfers.py tests/integration/test_retention.py -q` for missing capsules/transfers.
- [ ] For full, extend preview retention/backup with transactional capsule/link remapping with original coordinates, canonical imported origin keys/root aliases, retained pins when capsule sufficiency fails, honest missing-support downgrades, consistent backup snapshots, manifest digests, explicit export selections, and one-way migration. Never copy raw source transcripts into a shareable export.
- [ ] Verify export round-trip retains meaning, IDs/origin lineage, supersession, conditions, and uncertainty. Compare source Breadcrumbs bytes before and after import.
- [ ] Commit as `feat: retain evidence and transfer portable knowledge`.

### Task 16: Intentional forgetting and safe restore

**Release slice:** Entire task is in preview and depends on Task 15 core backup/pin-aware retention, not its capsule/transfer slice.

**Files:** Create `privacy/forget.py`, extend `storage/backup.py`, create `tests/integration/test_forgetting.py`, `tests/integration/test_restore.py`.

**Interfaces:** Produce `preview_forget`, `apply_forget`, and `restore` with signatures from DATA_CONTRACTS.

- [ ] Write `test_forget_purges_all_derivatives`, `test_old_job_cannot_resurrect_forgotten_source`, `test_restore_applies_newer_tombstones`, and `test_new_independent_statement_is_allowed`. Assert A25, A36–A37, A48, A63, and A64. A surviving-root derivative must become content-free quarantine before any re-extraction; backup failure cannot undo forgetting.
- [ ] Run `python -m pytest tests/integration/test_forgetting.py tests/integration/test_restore.py -q`; expect missing deletion/suppression paths.
- [ ] Implement the persisted maintenance phases: dependency-aware preview; digest-guarded purge/quarantine and new epoch; external spool/scratch/cache cleanup; ledger update; fresh verified post-forget backup; deletion of affected older backups even if the replacement backup fails; suppression-before-restore-serving; and post-commit reconstruction jobs. Keep delivery paused until required logical cleanup finishes. Report external-export and digest-membership limits. Purge proposal/revision bodies as well as current heads.
- [ ] Search all logical tables, indexes, caches, and retained snapshots for fixture-specific forgotten text. Test late proposals and old source replay. Document that filesystem forensics and remote provider retention are outside logical forgetting guarantees.
- [ ] Commit as `feat: implement forgetting and suppression-aware restore`.

### Task 17: Health, local upgrades, and independent operations

**Release slice:** Preview health/startup/recovery diagnostics run before the Task 13 release gate. Engine/schema upgrade, preview-to-full transition and chain diagnostics are full-only.

**Files:** Create `operations/{health,upgrade,autostart}.py`, extend CLI, create `tests/integration/test_upgrade.py`, `tests/platform/test_autostart.py`, `tests/integration/test_health.py`.

**Interfaces:** Produce profile-aware `health(ctx) -> HealthReport`. Upgrade/restore use exclusive maintenance mode; installer writes only the selected project's runtime/owned integration entries.

- [ ] Write `test_upgrade_A_leaves_B_running`, `test_interrupted_upgrade_restores_previous_engine`, `test_missing_provider_is_degraded_not_ready`, and `test_copied_installation_does_not_autostart`. Full also adds `test_preview_to_full_preserves_live_evidence_and_ids`, `test_profile_transition_honors_retention_override`, `test_failed_capsule_transition_keeps_pin`, and `test_interrupted_profile_transition_restores_complete_state`. Assert A02–A03, A29, A40, A45–A47.
- [ ] Run `python -m pytest tests/integration/test_upgrade.py tests/integration/test_health.py tests/platform/test_autostart.py -q`; expect missing upgrade/health behavior.
- [ ] Preview implements health/startup, unsupported-feature results, required start/prompt/operator-guard/recovery checks, and optional delivery reporting. Full adds side-by-side runtime installs, artifact verification, backup-before-migration, compatibility checks, tested activation/rollback, per-project OS startup entries, and bounded health diagnostics. The incoming full-release installer supplies the guarded transition when the preview binary cannot; no re-init or profile-file edit is allowed. Follow SYSTEM_SPEC §10.1: maintenance/fencing, verified backup, staged schema and chain baseline, capsule-or-pin retention, capability registration/probes, policy/guidance fences, recoverable activation, and autonomy-log entry. Preserve explicit retention/provider overrides and the newest tombstones through rollback. No automatic upgrade from a hook.
- [ ] Exercise two independently pinned releases and process restarts on native platforms. Health must accurately expose each capture/inference/delivery/recovery capability, source conflicts, private-path restriction coverage, exhausted budget pools, hash-chain diagnostics or explicit unavailability, pinned/unpinned bytes and live owners/free disk/deferred compaction, and pending privacy cleanup. Add `test_preview_ready_with_optional_delivery_unavailable`, `test_missing_required_prompt_is_not_ready`, and `test_deferred_features_are_explicit_not_passed`. A report of limited host protection is not a claim of OS-level isolation.
- [ ] Commit as `feat: operate and upgrade independent installations`.

### Task 18: End-to-end evaluations and release hardening

**Release slice:** Begin fixture/harness work during Tasks 1/7–13. Preview runs its explicitly scoped gate below; full evaluation and deferred acceptance variants remain pending until Cut 2.

**Files:** Extend the early `evals/` and `tests/coverage_manifest.json` fixtures; create `evals/{run,oracles,baselines,report}.py`, performance harnesses, release workflow, and operator documentation.

**Interfaces:** Consume only public service/host interfaces. Evaluation reports include all measures, populations, versions, and failures from ACCEPTANCE_TESTS.

- [ ] Write `test_acceptance_manifest_covers_A01_through_A73_by_profile` and `test_replay_cannot_see_future_evidence`. Assert every required ID/variant maps to executable tests and every live trial uses only prior evidence. The complete case inventory remains 73; preview exclusions/partial variants are exactly ACCEPTANCE_TESTS §2.1.
- [ ] Run preview's deterministic/failure/latency gates, comparative 12-scenario smoke, and three default-budget workload days as soon as its dependency sequence completes. Record §5.1 quality against the smoke population and paired outcome differences without a superiority claim. Preview intentionally does not run the Breadcrumbs baseline. Initialize independent evaluation stores noninteractively with the operator/CI-provisioned pre-init token; never mint it from an agent-marked process or simulate a TTY to defeat the guard. Fix correctness failures before shipping preview; preserve the held-out corpus for full.
- [ ] For full, extend the established harness with the 48-scenario, three-trial comparison; task outcome oracles; scenario-level paired reporting; hook latency/idle-resource measurement; and failure-injection repetitions. Enforce scenario authorship/held-out separation, native-memory controls, and all seven operational measures in ACCEPTANCE_TESTS. Use its explicit cost/session arithmetic and reference-hardware warm/cold timing protocol; replace illustrative estimates with the measured pilot before the full release run.
- [ ] Run the full-profile gates once its candidate is frozen. If a target is unmet, record it and fix the concrete cause or label the release experimental. Do not lower a gate or rewrite gold to manufacture success.
- [ ] Commit as `test: validate autonomous memory lifecycle and isolation`, then build signed/digested release artifacts using the new repository's own release process.

**Subproject D and release gate:** Recheck all five Review focus items. Full automatic capture → working state → episode → durable knowledge → recall → revision works on both certified hosts, with independent project installations and all blocking correctness tests passing.

## Added-case ownership

The original A01–A48 remain owned by their task references above. New cases map as follows; Task 18 checks completeness but does not replace the owning implementation test.

| IDs | Owning tasks |
|---|---|
| A49, A52, A54, A68 | 3 and 3b |
| A50 | 4, 7, 9 |
| A51 | 10 |
| A53 | 2, 3b, 13, 14 |
| A55, A71 | 15 |
| A56, A62, A70 | 8 (A62 also 10/11; A70 also 3b) |
| A57 | 6 |
| A58 | 3b, 11, 12b, 13, 14 |
| A59 | 12b |
| A60, A66 | 9 |
| A61 | 0b establishes the harness; 13/14 recertify real adapters; report mechanics in 18 |
| A63, A64 | 16 |
| A65 | 5, 13, 14, 17 |
| A67 | 0, 4 and 7; actual hook-spawn lifecycle in 13 |
| A69 | 11 |
| A72 | 12a and 12b |
| A73 | 12a; host protections/certification in 13 and 14 |

## Representative executable assertions

These snippets pin critical assertions for the implementation tests. The named fixtures construct real isolated contexts, registered sources, and persisted proposals; they must not mock the admission, storage, retrieval, or forgetting decisions under test. Expand each owning task's test module with the remaining acceptance cases named above.

```python
def test_foreign_installation_is_rejected(ctx_a, event_from_b):
    with pytest.raises(RecalithError, match="foreign_installation"):
        capture(ctx_a, [event_from_b])


def test_duplicate_proposal_has_one_effect(ctx, leased_job, valid_response):
    first = apply_proposal(ctx, leased_job, valid_response)
    second = apply_proposal(ctx, leased_job, valid_response)
    assert second.operation_ids == first.operation_ids
    assert second.store_revision == first.store_revision


def test_unknown_condition_cannot_caution(unknown_condition, query):
    assert evaluate_conditions([unknown_condition], query) == "unknown"


def test_no_current_guidance_after_forget(ctx, forget_request, query, forgotten_id):
    apply_forget(ctx, forget_request)
    packet = compile_context(ctx, query)
    assert forgotten_id not in {item.ref.id for item in packet.items}


def test_mcp_only_is_not_autonomous(ctx_with_mcp_only):
    assert health(ctx_with_mcp_only).autonomous_ready is False
```

Do not make idempotency depend on re-leasing a completed job: an already committed operation returns its original result before the current-lease check. New application still requires a valid lease generation.

## Optional post-release work

Add semantic retrieval only after observing lexical/structural recall misses in held-out tasks. Implement a provider-neutral embedding index keyed to record revision and tombstone epoch, with eligibility filtering before and after candidate generation. Run the same outcome and quiet-case gates. Do not add embeddings merely to make the architecture appear more agentic.

A graphical inspector, additional sources, and scheduled external-data observations can follow. None should change installation ownership or authorize cross-project reads. Live multi-machine sync needs a separate conflict and identity specification.

## Implementation handoff

Build in the new repository using these documents as the initial contract. The seven round-three decisions and fourteen small fixes are integrated here as startup/implementation preconditions; all subsequent empirical corrections belong in the repository's docs and tests. The handoff package stops being the ongoing design authority once that repo exists. Finish each profile slice's tests and review before committing its dependent slice; use the explicit preview execution order, not numerical task order alone. Keep source references and actual reused-code notices with the repository. A task is complete when its public behavior and failure cases pass, not when its files exist.

Do not start a wholesale Breadcrumbs clone unless a later, evidence-backed implementation review finds a concrete advantage and updates this plan. The default remains a fresh core with selective reuse and an importer.
