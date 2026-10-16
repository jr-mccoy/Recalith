# Recalith repository instructions

## Mission and first action

Build Recalith: a complete, autonomous memory installation for one project, with short-term working state, medium-term episodes, and long-term evidence-backed knowledge. Each project owns its engine version, configuration, worker, database, evidence, jobs, and budgets. A personal external-brain workspace is another independent project.

Start by reading [CODING_AGENT_HANDOFF.md](CODING_AGENT_HANDOFF.md), the current [build progress](docs/BUILD_PROGRESS.md), and the normative documents below. Then implement the next unblocked task. This repository begins with a reviewed specification, not an existing application. Do not stop after restating the design or producing another plan.

## Design authority

| Document | Owns |
|---|---|
| [SYSTEM_SPEC.md](docs/SYSTEM_SPEC.md) | Product behavior, policy, defaults, and installation boundaries |
| [DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md) | Record fields, types, interfaces, CLI and wire contracts |
| [ACCEPTANCE_TESTS.md](docs/ACCEPTANCE_TESTS.md) | Required measurements, case IDs, profile variants, and release gates |
| [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Task deliverables, dependencies, and execution order |
| [SOURCES_AND_REUSE.md](docs/SOURCES_AND_REUSE.md) | Required compatibility probes and pinned upstream reference |
| [Naming decision](docs/decisions/0001-recalith-name.md) | Recalith name and namespace |

The review response explains the design. `review/` preserves historical inputs and is not current policy. README, this file, the handoff, and the progress tracker are navigation and execution guidance; they do not override the normative documents. Resolve an actual contradiction in the owning docs before implementing the affected behavior, record the decision, and continue independent work. Routine implementation choices do not need another design-package approval.

## Build sequence and naming

- Display name `Recalith`; command/distribution/import `recalith`; source `src/recalith/`; project directory `.recalith/`; environment prefix `RECALITH_`; service error `RecalithError`.
- Work in this fresh repository. Breadcrumbs is an optional pinned reference outside the tree, as specified in SOURCES_AND_REUSE. Do not import its private memory or make it a runtime dependency.
- Begin with Task 0 provider isolation and Task 0b delivery feasibility. Record real outcomes before Task 1 freezes host assumptions. A missing live environment is an explicit blocker for certification; deterministic work with known contracts may continue.
- Follow the profile-specific sequence in IMPLEMENTATION_PLAN. For preview, Task 15 core backup/retention, Task 16 forgetting/restore, and Task 17 health precede Task 13 production delivery and Task 18 release evaluation.
- Deliver preview first. Keep full-only tasks and variants pending until their own implementation and gates pass. Do not mark a whole work package complete when only its preview slice is done.

## Constraints to preserve

- No global memory daemon, global project registry, shared project store, or automatic cross-project learning. Pass resolved installation context through APIs.
- Hooks use the audited stdlib-only fast path, never wait for a model, and never write SQLite. No model or network call inside a write transaction.
- Models propose strictly validated operations. Deterministic code assigns authority, checks evidence and revisions, and commits. Memory delivery is advisory. No background modification of project source or instruction files.
- Preserve primary evidence and independent root identity. Repetition, summaries, replay, and delivery are not new corroboration. Live references pin their required support; forgetting overrides pins.
- Provider/model/auth routing is explicit. A missing capability is not authorization for a different provider, paid route, account, tool permission, or weaker isolation.
- Public operator guards inspect the original caller. Never remove host markers, synthesize a TTY, add a bypass switch, or reuse the internal worker/curator environment builder to obtain operator authority. Internal role environments and registered hook startup remain separate as specified.
- Do not commit credentials, operator-token values, raw private transcripts, private local configuration, or live memory state. Sanitize retained probe evidence. Preserve license notices for any upstream source actually adapted.

## Verification and continuation

Use the exact acceptance IDs, variants, budgets, and deadlines from the specification. Write meaningful tests at the owning task boundary and run the relevant suite after implementation. Keep schemas and the test coverage manifest aligned with contracts. A mock, a stub, a unit test, or an unavailable live capability cannot establish a live certification pass.

Create `tests/coverage_manifest.json` during Task 1 with all A01–A73 and their profile variants. The preview includes 67 IDs with specified partial variants; it is not 67 completed full-release cases. Record exact commands, exit statuses, versions, and evidence locations. Keep sensitive local invocation settings out of tracked reports.

Update `docs/BUILD_PROGRESS.md` after each meaningful checkpoint. Record completed slices, deferred work, tests actually run, blockers, and the next concrete action. Continue unblocked implementation rather than ending at a proposal. Report empirical failures without weakening a gate merely to obtain a pass.

Use the execution tools available in the environment. This repository does not require a particular assistant plugin or delegation workflow. Repository publication, external messaging, credential/account changes, and deployment follow the user's session authorization.
