# The design packet (historical)

This directory holds the initial design packet exactly as it was handed over on 2026-10-15 (specification 1.3, packet edition `1.3-recalith.1`; [decision 0001](../../decisions/0001-recalith-name.md)), moved here from the repository root by decision 0047 so that the root reads as the project it became.

- `MANIFEST.json`: the packet's inventory, source provenance and file digests. It says the project is **not started**, which was true of the packet; the implementation's state is [docs/BUILD_PROGRESS.md](../../BUILD_PROGRESS.md).
- `review/`: the five review documents that shaped the specification. They use old names and superseded behavior and are **not current policy**; [docs/REVIEW_RESPONSE.md](../../REVIEW_RESPONSE.md) records the dispositions, and [SYSTEM_SPEC](../../SYSTEM_SPEC.md), [DATA_CONTRACTS](../../DATA_CONTRACTS.md) and [ACCEPTANCE_TESTS](../../ACCEPTANCE_TESTS.md) own the design.

Nothing here is edited. The build logs of the implementation are the sibling files `build-log-2026-10.md` and `build-log-2026-11.md`.
