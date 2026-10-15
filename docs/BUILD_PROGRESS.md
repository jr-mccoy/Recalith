# Recalith build progress

Initial handoff: 2026-10-15 · Specification 1.3 · Packet 1.3-recalith.1

## Current state

| Item | Initial value |
|---|---|
| Implementation | Task 0/0b probe harnesses implemented and tested; engine (Task 1+) not started |
| Engine version | Not assigned |
| First release target | `claude_preview` |
| Live provider certification | **Not established.** Request-capture isolation observed on Claude CLI 2.1.301 (all isolation dimensions pass); live route + operator attestation not configured |
| Live host delivery certification | **Not established.** All four paths request-visible on Claude Code 2.1.301; live nonce echo not run (no route) |
| Product tests / benchmarks | Not run (only probe-harness unit tests exist) |
| Next task | Task 1 contracts (deterministic work proceeds while live certification is blocked) |
| Known execution blocker | No explicitly configured build account route/model or background-use attestation (see Blockers) |

Update this file as work happens. “Not started” is the initial state, not a failed test. A packet-integrity check is not product verification. Do not prefill successful probe results or an engine build number.

## Execution order

Follow `0 → 0b → 1 → 2 → 3 → 3b → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12a → 12b`, then **15 core → 16 → 17 health → 13 production integration → 18 preview**. Keep full-only work pending until its implementation and gates pass. IMPLEMENTATION_PLAN owns exact scope and ordering; the table below is a tracking aid.

## Work packages

Use states such as `not started`, `in progress`, `blocked`, `preview slice complete`, and `complete`. A whole package is complete only when all its applicable slices are finished and verified. Attach a checkpoint below or link evidence for every claimed completion.

| Task | Work package | Preview slice / treatment | Full-release work / treatment | State |
|---|---|---|---|---|
| 0 | Certify one inference route with a standalone probe | One explicitly configured, certified inference route | Additional optional providers need their own certification | blocked (harness complete; live certification needs route) |
| 0b | Probe real host delivery before engine construction | Four path reports; required start/prompt controls | Repeat per additional supported host | blocked (harness complete; live echo needs route) |
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

### 2026-10-15 — Task 0 harness and request-capture observations (commit 3320a11)

- Files: `tools/probe_provider.py`, `tools/probe_common.py`, `tools/probe_config.example.json`, `tests/fixtures/providers/isolation/*`, `tests/fixtures/providers/fake_cli.py`, `tests/unit/test_provider_probe.py`, `docs/probes/LOCAL_CONFIG.md`, `docs/decisions/0002-curator-launch-findings.md`, `docs/host-compatibility.json` (`sections.provider_isolation.claude_cli`).
- Environment: Linux x86_64 cloud container, Python 3.13.16, Claude Code CLI 2.1.301 at `/opt/node22/bin/claude`.
- `.venv/bin/python -m pytest tests/unit/test_provider_probe.py -q` → exit 0, 27 passed. End-to-end fake tests repeated 12× after fixing a `/proc` environ race (dash exports `PWD` on exec).
- `python tools/probe_provider.py --config probe-private/local-config.json --output docs/host-compatibility.json` → exit 4 (`unavailable`). Request-capture mode against the real CLI: tool inventory, customization absence (all 14 blocking detectors validated by non-isolated controls; `AGENTS.md` informational), environment isolation (clean and host-marked parents, observed via `/proc`) and bounds (hang, 260 KiB flood, 15 KB body, oversize body, malformed body) pass. Blocking: `auth_route`, `live_launch`, `schema_output` not run (no route), `operator_attestation` unchecked.
- Acceptance: A28/A30/A67 harness mechanics only; no live certification. Findings recorded in decision 0002 (no `--json-schema`; fresh private curator root outside any user project; `--bare` auth limits; built-in components).

### 2026-10-15 — Task 0b harness and request-capture observations

- Files: `tools/probe_delivery.py`, `tools/fixtures/delivery_stub.py`, `tests/fixtures/hosts/claude/delivery/fake_host.py`, `tests/unit/test_delivery_probe.py`, `docs/probes/DELIVERY_PROBE.md`; `docs/host-compatibility.json` gains `sections.delivery.claude_code` (provider section preserved).
- `.venv/bin/python -m pytest tests/unit/test_delivery_probe.py -q` → exit 0, 27 passed (includes `test_probe_rejects_stdout_only_success`, `test_probe_rejects_nonce_contamination`, `test_missing_prompt_blocks_required_delivery`, `test_missing_pre_action_is_optional`). Full unit suite: `.venv/bin/python -m pytest tests/unit -q` → exit 0, 54 passed.
- `python tools/probe_delivery.py --config probe-private/local-config.json --output docs/host-compatibility.json` → exit 4 (`required_path_unavailable`: live not run). Request-capture mode on Claude Code 2.1.301: session start, prompt, pre-action and post-compaction injections each reached the outbound model request in 3/3 positives with 3/3 clean negatives; owned hooks removed with unrelated settings preserved. This is feasibility evidence only, not an echo pass.
- Acceptance: A61 harness mechanics; A27/A61 live certification pending.

Add each later checkpoint with:

- Date and commit when available; completed task slice and changed files.
- Tests or live probes actually executed, exact command, exit status, and evidence path.
- Relevant acceptance IDs/variants and version/platform details.
- Failures, unavailable checks, and remaining full-only work.
- Next concrete action.

## Blockers and decisions

**B1 — Task 0/0b live certification (open).** Evidence: `docs/host-compatibility.json` (`auth_route.kind = not_configured`, live `not_run`). This cloud session has the Claude CLI but no explicitly configured build account route; the session's own host credentials/proxy are not a Recalith route and are not used. Minimal operator action, from an ordinary terminal outside any agent session:

1. Copy `tools/probe_config.example.json` to `probe-private/local-config.json`; set `executable`, the explicit `model` for both sections, the auth route key names (API key route with `--bare`; see decision 0002), and `operator_attestation` (`checked_eligible` with `basis`/`checked_on` only after checking the account's terms for unattended background use).
2. `export ANTHROPIC_API_KEY=...` (or the selected key name) in that terminal.
3. `python tools/probe_provider.py --config probe-private/local-config.json --output docs/host-compatibility.json` (expect exit 0 when certified).
4. `python tools/probe_delivery.py --config probe-private/local-config.json --output docs/host-compatibility.json` (exit 0 requires healthy start/prompt).

Proceeding independently: Task 1 contracts and the deterministic kernel (Tasks 2–6, 8) do not depend on the live route. Autonomous extraction (Task 9 onward with a real provider) and any readiness claim stay blocked until B1 clears.

For each further blocker, record the task, observed evidence, minimal missing action or access, and what can proceed independently. Keep secrets and raw private data out of this file. Place lasting policy/interface decisions in `docs/decisions/` and update the owning normative document.

## Next-session handoff

Next action: Task 1 — create `pyproject.toml`/`uv.lock`, `src/recalith/contracts/` DTOs from DATA_CONTRACTS, schema snapshots, CI for Python 3.12–3.14, `tests/coverage_manifest.json` (A01–A73 with preview variants) and the 12 non-held-out smoke fixtures/oracles. In parallel, when an operator supplies B1's route, rerun both probes and record the live results here.
