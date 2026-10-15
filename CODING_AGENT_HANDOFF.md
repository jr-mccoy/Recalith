# Recalith coding-agent handoff

Date: 2026-10-15 · Specification: 1.3 · Packet: 1.3-recalith.1

**Start building Recalith in this new repository.** The owner has selected the product name and completed three design-review rounds. The complete specification, contracts, implementation plan, acceptance criteria, and preserved review history accompany this file. Begin implementation; another general redesign or downloadable-plan review is not a prerequisite.

This file belongs at the repository root beside `AGENTS.md` and `docs/`. The standalone download contains the same handoff as the repository packet. The detailed documents govern behavior; this handoff explains how to start and continue.

## 1. What you are building

Recalith autonomously captures a project's work, maintains short-term task state, constructs medium-term episodes, extracts and reviews long-term knowledge, recalls relevant context, and revises or forgets knowledge when evidence or intent changes. Routine memory maintenance should require neither a human curator nor a working agent that remembers to call a memory tool.

Each project contains its own complete installation: pinned engine, configuration, worker, SQLite store, evidence, job queue, and budgets. Projects can use different releases and policies. They never share learned memory or runtime state automatically. A personal life-management workspace is a separate project using the same system.

Use a fresh core. Breadcrumbs is optional reference material and a later one-way import source. Do not clone its application architecture or private state into Recalith. Its exact reference commit and reuse candidates are in SOURCES_AND_REUSE.

The first milestone is **Claude autonomous preview** (`claude_preview`). The full-release design remains in scope after that milestone. Implement the complete automatic capture → task state → episode → reviewed knowledge → recall → changed-condition revision loop, with project isolation, backup, forgetting, suppression-aware restore, and health. The first cut uses one configured, certified inference route and Claude capture/delivery; capture host and inference backend are separate capabilities.

## 2. Read the repository in this order

1. [AGENTS.md](AGENTS.md) and [BUILD_PROGRESS.md](docs/BUILD_PROGRESS.md): working constraints, actual progress, and current blockers.
2. [SYSTEM_SPEC.md](docs/SYSTEM_SPEC.md): product behavior and defaults, particularly the release profiles, installation boundaries, inference isolation, retention, and operator guard.
3. [DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md): exact DTOs, service signatures, persistence rules, wire contracts, and CLI forms.
4. [ACCEPTANCE_TESTS.md](docs/ACCEPTANCE_TESTS.md): all 73 cases, the 67-ID preview subset and partial variants, numerical gates, and live experiments.
5. [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md): all 22 work packages, prescribed files and interfaces, and dependency-safe release sequence.
6. [SOURCES_AND_REUSE.md](docs/SOURCES_AND_REUSE.md): exact compatibility-report requirements, upstream pin, and optional reuse.
7. [REVIEW_RESPONSE.md](docs/REVIEW_RESPONSE.md) and [the naming decision](docs/decisions/0001-recalith-name.md): rationale and the accepted namespace.

Historical documents in `review/` may use old names and superseded behavior. Do not implement them in preference to the current documents. SYSTEM_SPEC owns policy; DATA_CONTRACTS owns fields/interfaces; ACCEPTANCE_TESTS owns measurements; IMPLEMENTATION_PLAN owns execution order. Resolve a real disagreement in those documents and record it in the repo; continue unrelated work. Repository docs and tests now own subsequent changes.

## 3. Fixed names and implementation boundaries

| Item | Name or requirement |
|---|---|
| Product | `Recalith` |
| Repository suggestion / CLI / Python distribution / import | `recalith` |
| Source root | `src/recalith/` |
| Project-owned installation files | `.recalith/` |
| Environment prefix | `RECALITH_` |
| Separate internal role markers | `RECALITH_WORKER_INSTALLATION`, `RECALITH_CURATOR_INSTALLATION` |
| Service error type | `RecalithError` |
| Runtime / validation / database | Python 3.12–3.14 CI matrix; Pydantic v2 worker contracts; standard-library SQLite with WAL |
| Fast hook boundary | Stdlib and audited `recalith.fast` only; no synchronous model call or SQLite write |
| Dependency installation | Exact locks and a pinned per-project engine; no hook-triggered package download |

The document version is not the engine version. Set the initial engine version when implementing packaging. Public package-name availability and publication are separate from this build; local pinned-wheel installation does not require publishing a package.

## 4. Start with executable probes

### Task 0 — effective provider isolation

Implement `tools/probe_provider.py`, the harmless isolation sentinel fixtures in `tests/fixtures/providers/isolation/`, and the sanitized report `docs/host-compatibility.json` using SOURCES_AND_REUSE §5. It must run independently of an engine database.

Use the account, executable, model, and auth route explicitly configured for this build. Claude CLI is the first certification candidate if available. Confirm the combined effective absence of tools, MCP, hooks, native memory, inherited instructions/customizations, and previous session state; flags alone are not evidence. Exercise clean and host-marked parents, fresh allowlisted child environments, bounded output, timeout/cancellation, and selected authentication. Never switch billing routes or weaken isolation to force success. Codex inference remains unavailable until its own separate certification passes.

Once implemented, the plan's invocation is:

```bash
python tools/probe_provider.py --config LOCAL_CONFIG --output docs/host-compatibility.json
```

`LOCAL_CONFIG` is a placeholder for a locally configured, ignored file, not a file supplied by this packet. Define and document its exact schema alongside the harness; keep credentials and raw private artifacts out of the repository. Exit 0 requires complete observed certification; exit 4 reports unavailable capability.

### Task 0b — actual model-visible delivery

Implement `tools/probe_delivery.py`, `tools/fixtures/delivery_stub.py`, sanitized fixtures under `tests/fixtures/hosts/claude/delivery/`, and `tests/unit/test_delivery_probe.py`. Extend the same compatibility report without overwriting provider results.

Use a disposable, owned fixture workspace and nonce-only stub hooks. Test session start, prompt, pre-action, and post-compaction delivery separately, with three positive and three negative controls for every available path. The nonce must not be exposed through another channel. A successful hook process or stdout line is not proof that the model received context. Preserve unrelated settings and clean up only owned probe entries, including failure paths.

```bash
python -m pytest tests/unit/test_delivery_probe.py -q
python tools/probe_delivery.py --config LOCAL_CONFIG --output docs/host-compatibility.json
```

Start and prompt delivery are required; pre-action and compaction are independently probed optional paths. Follow the plan's exit codes and evidence protocol. This stub establishes feasibility only. Task 13 must repeat certification through the actual engine, delivery accounting, source/privacy fences, and budgets.

### If live execution is unavailable

Implement and test the harness logic that can run locally. Record exactly which host/account/configuration is absent, which checks ran, which checks did not run, and the minimal operator action needed. Use explicit unavailable/blocked results rather than invented versions or successful probe records. Include the exact ready-to-run operator command once the harness and local-config schema exist; do not include secret values.

Finish both probe reports before Task 1 freezes host-facing assumptions. A blocked report is not certification. Continue deterministic contracts, storage, and other unblocked work where interfaces are defined; leave provider/host-dependent behavior and readiness gated. Ask only for a concrete missing choice or access needed for the next blocked operation. Do not stop all engineering work merely because a live account is absent.

## 5. Follow the preview dependency sequence

Use this sequence from IMPLEMENTATION_PLAN:

1. Tasks **0 → 0b → 1 → 2 → 3 → 3b → 4 → 5**: external feasibility, executable contracts, independent installations, durable capture, real sanitized host fixtures, worker/budgets, and fenced mutations.
2. Tasks **6 → 7 → 8 → 9 → 10 → 11 → 12a → 12b**: continuity, production provider boundary, lineage, extraction/admission, autonomous revision, retrieval, public interfaces, and accounted delivery.
3. **Task 15 core → Task 16 → Task 17 health → Task 13 production integration → Task 18 preview**: pin-aware retention and verified backup, forgetting/restore, health, real delivery certification, and the preview release gate.

Task numbers retain review history and are not a simple numeric execution order. Full-only portions of Tasks 2/4/5/13/15/17/18, and Task 14, stay explicitly pending while preview is built. Apply the exact slice definitions in the plan. In particular, preview must include backup, forgetting, restore, live-evidence pins, strict operator guards, and profile-aware health.

Create the 12 non-held-out smoke fixtures and oracles during Task 1. Build the evaluation harness incrementally from Task 7 and exercise relevant slices through Tasks 9–13. Do not postpone all outcome testing until the end.

Task 1 creates `pyproject.toml`, the dependency lock, `src/recalith/contracts/`, strict schema snapshots, core CI, and `tests/coverage_manifest.json`. Later source paths, function signatures, tests, and exit codes are already specified in the plan and contracts; use them rather than creating another API from this summary.

## 6. Preserve the failure-sensitive behavior

- Keep working state, episodes, and durable claims functionally distinct. Long-term knowledge needs original evidence, review, deterministic admission, applicability, revision, and revalidation; persistence alone is insufficient.
- Retain independent evidence-root identity across retries, summaries, replay, imports, and delivery. A repeated observation derived from the same root cannot strengthen itself.
- Pin required evidence while live memories or open work refer to it. Preview's 180-day age policy applies to eligible unpinned payloads. Forgetting overrides pins; freshness is a separate question. Full-release capsules may compact support only when preservation is sufficient.
- Make corrections, forgetting, backup/restore, and delivery fences cooperate. Old jobs and old backups must not resurrect forgotten material. Correctness under crash and concurrent mutation belongs to the required test suite.
- Keep model calls outside write transactions and hook latency paths. Enforce queue reservations, concurrency, input/output limits, deadlines, and exact context budgets from the spec.
- Check public operator authority before internal environment construction. Host-marked callers remain refused even with a TTY and token. Real operator setup uses an ordinary terminal outside the host process tree; a pre-init token must be provisioned through the prescribed operator workflow. Do not clear markers or impersonate a human to make live initialization pass.
- Registered internal hook startup invokes its narrow internal operation. It does not call the guarded public worker CLI. Worker and curator roles have distinct fresh environments and markers.
- Unit fixtures may construct controlled states to test guards. They must not add a production bypass or be reported as proof that an actual live operator workflow succeeded.
- Recalith supplies advice and maintains memory; its background worker does not rewrite `AGENTS.md`, `CLAUDE.md`, source code, or execute remembered procedures. Agents developing this repository may update its docs and code as part of the build.

## 7. Evidence required for completion

The initial packet contains **no implemented tasks, certified hosts, benchmark results, or passing product tests**. Create evidence as implementation proceeds.

For each work-package slice, retain the changed files, tests actually run, exact commands and exit statuses, applicable acceptance IDs/variants, sanitized output locations, and remaining limitations in BUILD_PROGRESS. Keep the coverage manifest synchronized. A task with a deferred full slice stays partially complete.

Preview release requires the exact ACCEPTANCE_TESTS gates: 67 specified case IDs with their preview variants; mandatory real capture, provider, delivery, operator guard, recovery, and forgetting checks; the comparative 12-scenario smoke run against a clean no-memory baseline; three default-budget workload days; and the prescribed latency, usefulness, and quality targets. Optional paths must have honest capability reports. Full adds deferred features and the separate 48-scenario, three-trial comparison. Unavailable capabilities never count as passes.

Demonstrate useful fresh-session recall without a manual remember instruction, changed-condition revision with a legitimate retry, forgetting that survives restore, and isolation from a conflicting second project. Do not claim `autonomous_ready` on a mock-only system or merely because unit tests pass.

## 8. How to continue and report

Begin implementing the probes now. Make reviewable changes at the plan's task boundaries, validate the owning contracts and tests, and continue unblocked tasks. Use the available environment's normal development workflow; the packet has no mandatory assistant-plugin dependency.

Update BUILD_PROGRESS after meaningful checkpoints with the next exact action. When a real design contradiction appears, update its owning documents and record the reason under `docs/decisions/`; do not silently weaken a policy or start another broad redesign. When live access is needed, make the harness and operator instructions concrete before asking for it.

At each handoff or unavoidable pause, report: implemented slices; verification actually performed; live results versus unavailable checks; the concrete blocker, if any; and the next executable step. Keep deferred full-release work visible. The goal is working, evaluated project memory, with the approved design preserved in the same repository as its implementation.
