# Sources, Integration Evidence, and Breadcrumbs Reuse

Baseline inspected 2026-10-14; review integration and host documentation checked 2026-10-15. Revision 1.3. Product architecture and defaults in this package are recommendations. External sources support specific mechanisms or integration facts; they do not establish that this proposed system has been built or will outperform another product.

## 1. Baseline inspected

Repository: [jr-mccoy/breadcrumbs](https://github.com/jr-mccoy/breadcrumbs)

Pinned reference commit: [`4606001ad02f6a22cf7bfc1e775cc6d0edad2333`](https://github.com/jr-mccoy/breadcrumbs/commit/4606001ad02f6a22cf7bfc1e775cc6d0edad2333)

Read the README, architecture and continuity contract, v2 proposal supplied by the user, and selected service, promotion, lifecycle, transcript, and search-index implementation. Also read the continuity benchmark report and current state/version files. This was a targeted architectural inspection, not a full audit or an executed test run.

Findings relevant to the new design:

- [Architecture](https://github.com/jr-mccoy/breadcrumbs/blob/4606001ad02f6a22cf7bfc1e775cc6d0edad2333/docs/architecture.md) and [promotion](https://github.com/jr-mccoy/breadcrumbs/blob/4606001ad02f6a22cf7bfc1e775cc6d0edad2333/breadcrumbs/promote.py) define the long-term tier as instruction-file rules. The new design explicitly separates durable retention from instruction authority.
- [Service](https://github.com/jr-mccoy/breadcrumbs/blob/4606001ad02f6a22cf7bfc1e775cc6d0edad2333/breadcrumbs/service.py) supplies useful transport boundaries but still calls domain functions in `cli.py`. The new core has one-way dependencies.
- [Transcript mining](https://github.com/jr-mccoy/breadcrumbs/blob/4606001ad02f6a22cf7bfc1e775cc6d0edad2333/breadcrumbs/transcript.py) distinguishes success, failure, interruption, not-run, and unknown outcomes. Preserve that distinction in adapters and tests.
- [Continuity results](https://github.com/jr-mccoy/breadcrumbs/blob/4606001ad02f6a22cf7bfc1e775cc6d0edad2333/docs/benchmarks/continuity-results.md) explicitly measure delivery without running an agent. Retain those scenarios, then add actual task outcomes.
- The checked-in [current state](https://github.com/jr-mccoy/breadcrumbs/blob/4606001ad02f6a22cf7bfc1e775cc6d0edad2333/.project-memory/current.md) describes a pending 0.6.0 release while the [version source](https://github.com/jr-mccoy/breadcrumbs/blob/4606001ad02f6a22cf7bfc1e775cc6d0edad2333/breadcrumbs/__init__.py) is 0.6.2. This is a concrete motivation for task-state maintenance, not proof of a particular runtime bug.

## 2. Start fresh; reuse selectively

Do not fork the whole implementation as the new runtime. The change in storage authority, memory lifecycle, runtime ownership, and API boundaries makes a fresh core easier to reason about. A pinned reference checkout is useful during implementation, and a one-way importer preserves existing knowledge.

Optional reference setup, performed only in the future implementation environment:

```bash
git clone https://github.com/jr-mccoy/breadcrumbs.git ../breadcrumbs-reference
git -C ../breadcrumbs-reference checkout --detach 4606001ad02f6a22cf7bfc1e775cc6d0edad2333
```

Keep that checkout outside the new repository. It is a reference source, not a runtime dependency or installed memory engine. Do not copy its private state or credentials. If a different commit is chosen later, record the reason and update the source inventory.

| Candidate | Proposed treatment | Inspection required before copying |
|---|---|---|
| `safetext.py` and its tests | Adapt data rendering and control-character handling | New wire formats, Unicode behavior, text limits |
| `path_policy.py` and platform tests | Port boundary protections where compatible | Runtime/venv executable exceptions, registered workspaces, Windows junctions |
| `secretscan.py` patterns and tests | Reuse selected patterns within a new scrubber | False positives, redaction semantics, imported dependencies, no hidden raw copy |
| Transcript outcome and pairing logic | Adapt into versioned host adapters | Host version, late results, source identity, task/agent binding |
| Mutation/recovery tests | Reuse failure scenarios | SQLite transactions replace file-store mutation mechanics |
| Relevance/critical/task replay cases | Adapt expected behavior | New advice levels, context format, true agent outcome oracles |
| Original Markdown schema | Read-only import compatibility | IDs, lifecycle statuses, evidence, expired records, promoted rules |
| CLI, instruction promotion, global current state | Replace with the new contracts | Do not retain architectural coupling for compatibility |

These are reuse candidates, not a claim that every listed file was audited. Prefer porting small independently understood units and their tests. If dependencies drag in the old core, port the behavior rather than the module.

The pinned repository carries the [MIT license](https://github.com/jr-mccoy/breadcrumbs/blob/4606001ad02f6a22cf7bfc1e775cc6d0edad2333/LICENSE), copyright 2026 Breadcrumbs contributors. Preserve its notice and license text with copied/substantially adapted source. Maintain `THIRD_PARTY_NOTICES.md` listing files, upstream commit, and modifications. This design package contains no copied implementation modules.

## 3. Research and architectural precedents

### MemGPT

[MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560), revised 2024-02-12, describes tiered memory and virtual context management. The applicable idea is separating stored information from the subset currently active in model context. This design adds an external controller so the working agent is not solely responsible for memory upkeep.

### Letta background memory

[Sleep-time Compute](https://www.letta.com/blog/sleep-time-compute/) describes moving memory work to background reasoning. The [current memory documentation](https://docs.letta.com/configuration/memory) describes background conversation review and consolidation, including an optional second agent review. Borrow asynchronous processing and original-evidence review as mechanisms. Do not infer guaranteed correctness from another model's agreement, or copy reported benchmark improvements into this product's expected results.

### Temporal knowledge

[Zep: A Temporal Knowledge Graph Architecture for Agent Memory](https://arxiv.org/abs/2501.13956) describes temporal relationships and evolving knowledge. The applicable idea is preserving historical truth while updating present applicability. This design initially implements typed relations in SQLite; a separate graph database is unnecessary for the specified operations.

## 4. Current integration facts and their limits

### Claude Code

The [CLI reference](https://code.claude.com/docs/en/cli-reference) documents JSON-schema output, built-in tool restriction with `--tools`, and separate MCP tool restrictions. `--tools ""` alone does not remove MCP tools. It also documents customization-isolation options and disabling session persistence. The same reference describes `--bare` and `--setting-sources`; bare mode by itself still has tools. An installed-version probe must establish the combined effective behavior, including user-level settings, native memory, hooks, plugins, and MCP; documented separate flags do not certify a complete isolated launch.

The [hooks reference](https://code.claude.com/docs/en/hooks) documents lifecycle hooks, context output, and background command hooks. Test terminal termination, SessionEnd, cancellation, and compaction behavior on the actual host. An async flag is not a substitute for a durable queue and recovery.

The [environment reference](https://code.claude.com/docs/en/env-vars) documents `CLAUDECODE` in tool, hook, MCP, and IDE-terminal descendants and `CLAUDE_CODE_CHILD_SESSION` for specified child-session processes. These can affect nested launches. The design uses a fresh allowlisted environment for its worker and curator; the public operator guard still evaluates the original caller. Registered markers are friction, not human authentication. The [permissions reference](https://code.claude.com/docs/en/permissions) documents command patterns and their spelling/wrapper limitations. Probe installed launcher and module forms; a rule matching one command spelling is not universal prevention.

The [settings documentation](https://code.claude.com/docs/en/settings) distinguishes local and shared project settings; local integration is the default in this design. The [sandbox documentation](https://code.claude.com/docs/en/sandboxing) documents path restrictions whose effective scope depends on the configured sandbox and settings. Probe file and shell tools and ensure the exact hook launcher still operates; do not equate one tool deny rule with protection from every same-user process.

### Codex

The [non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode) documents `codex exec`, saved authentication reuse, and `--output-schema` for structured final output. `--json` supplies an event stream and is not by itself the schema contract for the final proposal.

The [hooks documentation](https://learn.chatgpt.com/docs/hooks) documents lifecycle and tool hooks plus model-visible context, while warning that transcript format is not a stable interface. Tool coverage and asynchronous completion require adapter fixtures. This review did not establish a universally applicable no-tools/no-customizations Codex inference invocation. A read-only sandbox is not equivalent to removing tools. Codex capture/delivery can be supported independently of whether its CLI qualifies as an inference backend. The design therefore treats Codex as a capture/delivery host, with inference gated on a separate successful future probe; the mandatory Task 7 file list no longer assumes `codex_cli.py`.

The [permissions documentation](https://learn.chatgpt.com/docs/permissions) describes beta filesystem profiles with read/write/deny rules and configuration/runtime constraints. This supports testing a private-path restriction, not assuming identical behavior across native Windows, WSL, Linux, legacy sandbox configuration, or managed policy. The installer must inspect the effective profile and preserve existing restrictions.

### Process lifecycle

Python 3.12's [subprocess documentation](https://docs.python.org/3.12/library/subprocess.html) provides `start_new_session`, descriptor handling, explicit child environments, and Windows creation flags. The [Windows Job Objects documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) describes inherited job membership, job-wide termination, and conditional breakaway. The design inference is that detaching the console alone does not prove survival when the host terminates its process tree or job. Test an actual hook-started worker on each supported platform; report degraded independence when the configured launch cannot survive. Do not bypass managed process policy.

### SQLite

The official [WAL documentation](https://sqlite.org/wal.html) explains the write-ahead logging model and local-host/shared-memory constraints. Use local storage, short transactions, and explicit backup/restore procedures. Do not assume copying one open database file captures all current state. The filesystem and OS still determine durability details, which must be exercised by platform tests. Its read-only WAL section describes existing readable sidecars, permitted sidecar creation, or an immutable database as possible read paths. Our live-store design forbids the immutable shortcut and hook recovery/checkpoint work. The crashed-worker WAL/SHM cases and a live worker mid-checkpoint are required platform tests, not assumed behavior. A busy read-only snapshot degrades without lock waiting or hook recovery work.

## 5. Required compatibility probe report

Tasks **0 and 0b** establish standalone provider-isolation and delivery-feasibility probes before Task 1. They extend one checked-in, sanitized `docs/host-compatibility.json`; neither requires a memory engine. Task 0b uses disposable nonce-only stub hooks. Later Task 7 and the host adapter tasks reuse the harness and re-certify the actual engine integration. A stub pass establishes feasibility, not product readiness. The report records:

1. OS, host CLI version, engine build, exact invocation arguments, and tested date.
2. Auth route classification, without credentials; whether another environment variable could change billing; checked account/deployment eligibility for unattended use, dated source or operator attestation, and managed-policy constraints. This record is not a legal determination.
3. Effective tool inventory and whether managed configuration adds capabilities.
4. Effective project/user instructions, previous session state, plugins, skills, native memory, and hooks; sentinel results and diagnostic method establishing their absence in the curator. “Hook fired but capture ignored it” is not sufficient.
5. Schema-output location and failure shape.
6. Timeout/cancellation, separately bounded raw host envelope and decoded response body, a valid 15 KB episode fixture, stderr cap, and subprocess-tree cleanup.
7. Capture-event coverage, source identities, and transcript parser fixture version.
8. Required start/prompt versus optional pre-action/compact states and observed delivery evidence from the path-specific random-nonce protocol in SYSTEM_SPEC §9.3: three positives/three negatives, model/host versions, transcript locations, contamination checks, and any diagnostic context trace. Task 0b establishes these facts early; required-path failure blocks that host route, optional gaps remain explicit, and Task 13/14 repeat the probes with the production engine. Do not claim direct inspection of an inaccessible internal model request.
9. Worker recovery after normal exit, forced termination, and reboot/next activity. Test a worker launched by a real host hook, including descriptor closure, environment isolation, SessionEnd, host process-tree/job termination, and platform detachment constraints; a terminal-launched worker alone is insufficient.
10. Supported, degraded, or unavailable verdict for each separate capability, including effective private-path read/write protection and any hook-access exception.
11. Warm/cold packet-cache latency on disclosed reference hardware, fast-path import inventory, and platform filesystem coverage.
12. Exact native-memory settings used in outcome baselines; unavailable clean baselines are identified rather than renamed.
13. Host/worker/curator marker inheritance from clean and marked parents; actual child environment key names and selected auth route; effective isolation under nested-session markers; distinct fresh worker and curator role markers; administrative-command refusal and audit behavior; command-deny spellings/gaps; and pre-init/noninteractive and strict external-terminal TTY/token workflows. Never record credential or token values. Do not presume a Codex marker until verified for that adapter. Public CLI calls are never sanitized into operator authority.
14. Release profile, deferred capabilities, polling/IPC mode, pin-aware retention, and profile-specific acceptance variants. Preview's private-path probe is distinct from full's installed protection. Full certification includes an in-place preview-to-full transition, capsule sufficiency or retained pins, explicit retention overrides, current privacy tombstones, capability changes, and rollback/recovery evidence.

Do not record unsupported capabilities as passed in a release claim. Mark them unavailable and state whether they block the selected profile or are deferred/optional. Operational readiness requires healthy capture, inference, admission, start/prompt delivery, operator-command guard, and recovery/forgetting for the configured host. Full-profile quality remains a separate evaluation gate.

## 6. Design choices not dependent on external product claims

Project-local installation, three functional memory levels, evidence-root accounting, bounded operations, idempotent recovery, logical forgetting, and the proposed release metrics are choices in this specification. Their usefulness must be evaluated against real tasks. They are not facts borrowed from a vendor's marketing or an unverified performance benchmark.

## 7. Review-driven decisions and limits

The [round-one review](../review/INPUT_REVIEW.md) and [response](../review/ROUND_1_RESPONSE.md), [round-two review](../review/ROUND_2_REVIEW.md) and [response](../review/ROUND_2_RESPONSE.md), and [round-three review](../review/ROUND_3_REVIEW.md) are historical inputs. Current round-three dispositions are in [REVIEW_RESPONSE.md](REVIEW_RESPONSE.md). The supplied reviews' startup, workload, evaluation cost, and time estimates have not been independently measured in this environment; they identify risks to test. Round three's seven main issues and fourteen smaller fixes are integrated into the normative documents rather than left as an implementation addendum.

The revisions add explicit definitions and failure handling; they do not imply that any host/backend has been certified here. Pinning is not a fixed storage bound or a freshness reset; strict markers/TTY/tokens are not a security boundary against the same OS user; Windows detachment flags are not proof of job independence. The original no-global-daemon boundary, evidence lineage, autonomous routine maintenance, and fresh-repository strategy remain intact. This task changes design artifacts only. Once implementation begins, the new repository's docs, probes, tests, and measured results own further design changes; another package review is not a prerequisite.
