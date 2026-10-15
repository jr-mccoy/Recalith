# Recalith build progress

Initial handoff: 2026-10-15 · Specification 1.3 · Packet 1.3-recalith.1

## Current state

| Item | Initial value |
|---|---|
| Implementation | Not started; this repository packet contains design and handoff files |
| Engine version | Not assigned |
| First release target | `claude_preview` |
| Live provider certification | Not run; no provider/account route selected by this packet |
| Live host delivery certification | Not run |
| Product tests / benchmarks | Not run |
| Next task | Task 0 provider-isolation harness, followed by Task 0b delivery probe |
| Known execution blocker | None assessed yet; inspect the actual build environment |

Update this file as work happens. “Not started” is the initial state, not a failed test. A packet-integrity check is not product verification. Do not prefill successful probe results or an engine build number.

## Execution order

Follow `0 → 0b → 1 → 2 → 3 → 3b → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12a → 12b`, then **15 core → 16 → 17 health → 13 production integration → 18 preview**. Keep full-only work pending until its implementation and gates pass. IMPLEMENTATION_PLAN owns exact scope and ordering; the table below is a tracking aid.

## Work packages

Use states such as `not started`, `in progress`, `blocked`, `preview slice complete`, and `complete`. A whole package is complete only when all its applicable slices are finished and verified. Attach a checkpoint below or link evidence for every claimed completion.

| Task | Work package | Preview slice / treatment | Full-release work / treatment | State |
|---|---|---|---|---|
| 0 | Certify one inference route with a standalone probe | One explicitly configured, certified inference route | Additional optional providers need their own certification | not started |
| 0b | Probe real host delivery before engine construction | Four path reports; required start/prompt controls | Repeat per additional supported host | not started |
| 1 | Establish the repository and executable contracts | Contracts, lock/CI, all-case manifest, smoke fixtures/oracles | Core behavior retained; no separate deferred slice listed | not started |
| 2 | Independent installation and transactional store | Local installation, one workspace, clone/move, missing runtime | Workspace attachment/fork and shared integration | not started |
| 3 | Durable event capture and source cursors | Durable capture, source registration, cursor/idempotency rules | Core behavior retained; no separate deferred slice listed | not started |
| 3b | Capture-only real Claude adapter and fast-path boundary | Real sanitized Claude capture fixtures and fast boundary | Core behavior retained; no separate deferred slice listed | not started |
| 4 | Queue, budgets, and project worker | Persistent worker, polling, budgets, leases, role environments | Session worker and IPC wake | not started |
| 5 | Mutation application and optimistic concurrency | Atomic revisions, evidence/privacy fences, compensating undo | Revision chain and integrity scanner | not started |
| 6 | Tasks, episodes, and cross-session continuity | Task binding, continuity, episodes | Core behavior retained; no separate deferred slice listed | not started |
| 7 | Provider certification and isolated inference | Production isolation and certification for configured route | Core behavior retained; no separate deferred slice listed | not started |
| 8 | Source lineage and applicability | Lineage, independent roots, applicability | Core behavior retained; no separate deferred slice listed | not started |
| 9 | Claim extraction and deterministic admission | Extraction, adversarial review, deterministic admission | Core behavior retained; no separate deferred slice listed | not started |
| 10 | Consolidation and autonomous revision | Consolidation, revision, revalidation | Core behavior retained; no separate deferred slice listed | not started |
| 11 | Retrieval and context composition | Retrieval and bounded context composition | Core behavior retained; no separate deferred slice listed | not started |
| 12a | Public service and CLI contracts | Public service/CLI and strict operator guards | Core behavior retained; no separate deferred slice listed | not started |
| 12b | Delivery accounting, session overlay, and corrections | Delivery accounting, overlay, correction/privacy fences | Core behavior retained; no separate deferred slice listed | not started |
| 13 | Claude Code integration | Real Claude capture/delivery; command guard; private-path probe | Installed private-path restrictions where supported; shared mode | not started |
| 14 | Codex, generic JSON, and optional MCP integration | Deferred capability reporting; adapters are full-release work | Codex, generic JSON, optional MCP; Codex inference separately gated | not started |
| 15 | Evidence retention and portable transfers | Core backup/ledger, live pins, 180-day unpinned retention | Capsules, transfer/export/import, Breadcrumbs importer | not started |
| 16 | Intentional forgetting and safe restore | Complete forgetting and suppression-aware restore | Core behavior retained; no separate deferred slice listed | not started |
| 17 | Health, local upgrades, and independent operations | Health, startup/recovery, profile-aware readiness | Engine/schema upgrade, preview-to-full transition, chain diagnostics | not started |
| 18 | End-to-end evaluations and release hardening | Applicable tests, comparative smoke, three workload days | Deferred variants and full 48-scenario, three-trial evaluation | not started |

## Acceptance tracking

Task 1 creates `tests/coverage_manifest.json` with the complete A01–A73 inventory, profile, capability, variant, owning task, platform, status, and unavailable reason where applicable. Preview includes 67 IDs: all except A38, A39, A42, A46, A55, and A71. The included partial variants remain exactly those in ACCEPTANCE_TESTS §2.1. A deferred or unavailable variant is never a pass.

Current acceptance evidence: **none**. Current product readiness: **not evaluated**.

## Checkpoints

No implementation checkpoints yet. Add each checkpoint with:

- Date and commit when available; completed task slice and changed files.
- Tests or live probes actually executed, exact command, exit status, and evidence path.
- Relevant acceptance IDs/variants and version/platform details.
- Failures, unavailable checks, and remaining full-only work.
- Next concrete action.

## Blockers and decisions

No blocker has been assessed in a coding environment. For each real blocker, record the task, observed evidence, minimal missing action or access, and what can proceed independently. Keep secrets and raw private data out of this file. Place lasting policy/interface decisions in `docs/decisions/` and update the owning normative document.

## Next-session handoff

Initial action: read the repository handoff and Task 0/0b contracts, inspect the available local host/account configuration without exposing credentials, then implement the standalone provider probe and tests. Continue to the delivery probe and record actual outcomes. Do not create fictitious certification data to unblock Task 1.
