# Recalith: autonomous memory for one project

Repository starter packet • 2026-10-15 • specification 1.3 • packet edition 1.3-recalith.1

This package specifies Recalith, an autonomous memory system for individual projects. It is a design and implementation handoff, not an implemented or benchmarked product. The display name is **Recalith**. The technical stem is **recalith** across the command, Python import package/distribution, `.recalith/` directory, and `RECALITH_` environment markers. Public distribution-name availability remains unverified; resolve any collision through one documented naming decision before public publication; local pinned-wheel installation does not depend on a registry name.

## Upload and start

Extract `Recalith_Repository_Packet.zip` and place **its contents at the root of the new repository**. The archive already has root-level files; do not add an extra enclosing directory or commit only the ZIP. Include the supplied `.gitignore` when copying. Use `recalith` as the repository name if convenient; no remote repository or public package name has been reserved by this packet.

Open that repository in your coding-agent environment and give the agent this instruction:

> Read `AGENTS.md` and `CODING_AGENT_HANDOFF.md`, then start building Recalith. Follow the dependency order in `docs/IMPLEMENTATION_PLAN.md`, beginning with Tasks 0 and 0b. Implement and verify the work; keep `docs/BUILD_PROGRESS.md` current. Use the full specification and acceptance criteria in this repository. Document unavailable live capabilities honestly and continue unblocked work.

The first delivery milestone is the **Claude autonomous preview**. The complete full-release design is included. Every implementation task starts pending; the packet contains specification and handoff files, not an application or successful host-probe results.

| File | Purpose |
|---|---|
| [CODING_AGENT_HANDOFF.md](CODING_AGENT_HANDOFF.md) | Build objective, first actions, dependency order, gates, and handling of blockers |
| [AGENTS.md](AGENTS.md) | Persistent instructions for agents working in this repository |
| [docs/BUILD_PROGRESS.md](docs/BUILD_PROGRESS.md) | Initial task tracker and continuation record |
| [docs/decisions/0001-recalith-name.md](docs/decisions/0001-recalith-name.md) | Accepted product name, technical namespace, and packet provenance |
| [docs/SYSTEM_SPEC.md](docs/SYSTEM_SPEC.md) | Complete product specification |
| [docs/DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md) | Complete data and interface contracts |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | All 22 reviewed work packages |
| [docs/ACCEPTANCE_TESTS.md](docs/ACCEPTANCE_TESTS.md) | All 73 acceptance cases and profile-specific release gates |
| [docs/SOURCES_AND_REUSE.md](docs/SOURCES_AND_REUSE.md) | Pinned Breadcrumbs reference, optional reuse, and required compatibility evidence |
| [docs/REVIEW_RESPONSE.md](docs/REVIEW_RESPONSE.md) | Integrated round-three dispositions |
| `review/` | Five unchanged historical review documents |
| [MANIFEST.json](MANIFEST.json) | Packet inventory, source provenance, and file digests |

Specification revision `1.3` and packet edition `1.3-recalith.1` identify these documents. Neither is an implemented engine version. This packet applies the chosen name to the reviewed design; it does not reopen its architecture or change its acceptance gates. Historical names in `review/` and upstream Breadcrumbs paths are intentionally preserved.

## Product decision

Start a fresh repository. Build a complete, independent memory installation inside each project. Each installation owns its engine version, configuration, worker, database, jobs, evidence, and all three memory levels. There is no shared memory daemon, global project registry, or automatic transfer between projects. A personal life-management workspace can be a project of its own.

The memory system automatically captures work, maintains task state, creates episodes, derives reusable knowledge, supplies relevant context, and revises its knowledge when evidence changes. It does not require the working agent to remember to maintain memory. Full automatic behavior is available only through host adapters that demonstrably capture and deliver the required events.

## Final design handoff

[REVIEW_RESPONSE.md](docs/REVIEW_RESPONSE.md) records all **21 round-three dispositions**: seven main findings and fourteen smaller fixes. The [round-one review](review/INPUT_REVIEW.md), its [v1.1 response](review/ROUND_1_RESPONSE.md), the [round-two review](review/ROUND_2_REVIEW.md), its [v1.2 response](review/ROUND_2_RESPONSE.md), and the [round-three review](review/ROUND_3_REVIEW.md) are preserved unchanged as historical inputs. Current policy is in the revised documents, not those historical copies.

The plan has **22 work packages**, including the new early delivery probe, and **73 acceptance cases**. It names two shippable cuts: **Claude autonomous preview** first, then the full release. Preview includes 67 case IDs with explicit feature variants, a comparative 12-scenario smoke run against a clean no-memory baseline, and three default-budget workload days. Full adds the remaining features and the separate 48-scenario, three-trial evaluation. A capability reported unavailable is never counted as a passed test.

The central correction is **pin-on-reference retention**: evidence still needed by live memories survives age-based expiry. The other revisions define clean worker/curator environments, pre-init tokens for noninteractive setup, an early four-path delivery probe, strict operator access from an unmarked terminal, declaration-review priority, and an in-place preview-to-full migration. Capsules become a full-release space and transfer mechanism; live memory does not depend on them arriving before day 180. Preview retains forgetting, backup, restore, and complete project isolation.

## Specification reading order

1. [System specification](docs/SYSTEM_SPEC.md): product behavior, architecture, lifecycle rules, deployment, and operational defaults.
2. [Data and interface contracts](docs/DATA_CONTRACTS.md): identifiers, records, persistence, operations, and component interfaces.
3. [Acceptance tests](docs/ACCEPTANCE_TESTS.md): deterministic scenarios, live-agent experiments, and numerical release gates.
4. [Implementation plan](docs/IMPLEMENTATION_PLAN.md): ordered, independently verifiable work packages for a new repository.
5. [Sources and Breadcrumbs reuse](docs/SOURCES_AND_REUSE.md): inspected baseline, selective reuse, integration evidence, and compatibility probes.

The policy, contract, acceptance, implementation-order, and required certification sections of these documents are normative; rationale, examples, illustrative costs, source observations, the review response, and the supplied review are explanatory. SYSTEM_SPEC owns product policy; DATA_CONTRACTS owns field names and signatures; ACCEPTANCE_TESTS owns measurements; IMPLEMENTATION_PLAN owns execution order. If they disagree, stop the affected implementation task and resolve the inconsistency in the documents rather than choosing silently.

## Starting the new repository

Copy all packet contents into the new repository, including this README, `AGENTS.md`, `CODING_AGENT_HANDOFF.md`, `.gitignore`, `docs/`, `review/`, and `MANIFEST.json`. Do not initialize the new codebase by copying Breadcrumbs wholesale. The implementation plan includes an optional, pinned reference checkout and a one-way importer. Preserve upstream notices for code actually adapted.

Begin with **Task 0 (provider isolation) and Task 0b (delivery feasibility), before Task 1**. These are standalone installed-host probes; no memory engine is needed. Copy the revised docs into the new repository and treat their round-three corrections as Task 0/1 preconditions. **Once that repository exists, its version-controlled docs and tests become the design authority. Do not wait for another downloadable design-package review before starting.** This v1.3 snapshot incorporates the requested corrections as the final handoff; subsequent empirical findings should be resolved in the repository.

Build the smallest automatic capture-to-recall loop in stages. Enable autonomous consolidation only after the evidence and lifecycle tests pass. Follow the preview dependency sequence in IMPLEMENTATION_PLAN; Task 15 core backup/pin-aware retention, Task 16 forgetting, and Task 17 health are prerequisites for its release gate even though their numbers are later. Do not substitute a chat UI, an embedding search demo, or manually authored memories for the end-to-end acceptance demonstration.

## What is fixed and what is configurable

Fixed: installation isolation; evidence lineage; three functional memory levels; reversible revisions; advisory delivery; provider isolation; deterministic admission; bounded computation; no silent cross-project reads.

Configurable: selected model providers, task budgets, retention periods, export visibility, persistent versus full-release session worker mode, and optional semantic retrieval. Defaults are specified so implementation does not depend on another requirements interview.

## Explicit limits of this handoff

- The proposal has not been implemented, load-tested, or shown to outperform another memory system.
- Numerical release targets are engineering acceptance criteria, not claimed results.
- Host CLI flags, transcript layouts, account capabilities, and model availability must be verified against exact installed versions.
- Memory improves supplied context; it does not train the underlying model weights or guarantee that an agent follows advice.
- Live multi-machine synchronization, a hosted service, and arbitrary autonomous command execution are outside the first release.

This packet prepares the new repository for implementation. No remote repository has been created or modified, and no product implementation is included.
