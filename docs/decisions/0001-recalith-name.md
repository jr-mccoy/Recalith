# Decision 0001: Recalith name and repository handoff

Status: accepted by the project owner · Date: 2026-10-15

## Decision

The new product is **Recalith**. It starts in a fresh repository using the complete reviewed specification revision 1.3. Breadcrumbs remains the name of the earlier system and an optional pinned reference/import source.

| Previous design placeholder | Accepted name |
|---|---|
| `Project Memory` display name | `Recalith` |
| `pmem` command / distribution / import | `recalith` |
| `src/pmem/` | `src/recalith/` |
| `.pmem/` | `.recalith/` |
| `PMEM_` environment prefix | `RECALITH_` |
| `PMEM_WORKER_INSTALLATION` | `RECALITH_WORKER_INSTALLATION` |
| `PMEM_CURATOR_INSTALLATION` | `RECALITH_CURATOR_INSTALLATION` |
| `ProjectMemoryError` | `RecalithError` |

This is a naming change before implementation. Do not add aliases, scan for old private directories, or invent a migration from an unimplemented placeholder namespace. Breadcrumbs import remains the separate explicit full-release feature. Ordinary descriptions such as “project memory,” logical record identifiers, and the upstream `.project-memory` path are not renamed indiscriminately.

## What this packet changes

Packet edition `1.3-recalith.1` applies the mapping throughout the complete current specification, contracts, implementation plan, acceptance criteria, and explanatory documents. The five historical review files are preserved byte for byte, including their old product names and superseded recommendations. Upstream URLs, source commit, and licensing references are preserved.

The README now explains repository upload and kickoff. The implementation-plan introduction is portable across coding-agent environments rather than requiring a particular assistant skill. Root agent instructions, the coding-agent handoff, an initial pending build tracker, and a source-repository `.gitignore` are added. MANIFEST records source and packaged file digests.

No product behavior, task dependency, numerical default, acceptance ID, release profile, or review disposition is removed or replaced by these additions. This handoff is not a specification revision 1.4, a product implementation, or an engine release. All 22 work packages, 73 acceptance cases, 67 preview case IDs with their partial variants, and 21 round-three dispositions remain in the full documents.

## Consequences

Use the accepted namespace consistently in code, commands, configuration, generated schemas, installation paths, tests, and operator documentation. The core service error is `RecalithError`; stable error-code strings remain those in DATA_CONTRACTS and IMPLEMENTATION_PLAN.

The repository name is suggested, not provisioned. Public registry/domain/trademark availability is not established by the choice of name. Local pinned-wheel builds can proceed. If future public distribution requires a different package name, record that separate packaging decision before publishing; do not silently create multiple runtime namespaces.

The authoritative design now travels with implementation in this repository. Future empirical findings belong in its docs, tests, compatibility evidence, and decision records. MANIFEST is the immutable inventory of this initial packet, not a requirement to keep every documentation file unchanged during authorized development.
