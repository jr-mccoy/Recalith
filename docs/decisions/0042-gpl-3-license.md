# Decision 0042: Recalith is licensed under the GNU General Public License, version 3 only

Status: accepted (the owner's decision) · Date: 2026-11-04 · Engine: `0.1.0.dev10`

## Context

The repository is public on GitHub but declared no license, so by default nobody else could legally use, copy or change the code. The release checklist recorded the project license as an owner decision and a publication blocker (decision 0020 item 10). The owner wants Recalith open source now and published later, and hopes for outside contributors, for example someone who can certify macOS (decision 0041).

The runtime dependencies are all compatible with GPL-3.0 (`docs/release/DEPENDENCIES.json`):
- `pydantic`, `pydantic-core`, `annotated-types` and `typing-inspection` are MIT;
- `packaging` is Apache-2.0 or BSD-2-Clause;
- `typing-extensions` is PSF-2.0.

No upstream source is adapted. The Breadcrumbs reference (MIT) is consulted, not copied.

## Decisions

1. **The license is GPL-3.0-only.** It is the owner's choice of "GPL 3.0", taken literally. Changing to "or any later version" stays the owner's decision; it can widen the grant later, but not narrow it for copies already shared.
2. **The text** is the Free Software Foundation's `gpl-3.0.txt`, unchanged, as `LICENSE` at the repository root. Its SHA-256 is `3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986`, and it matched GitHub's copy word for word.
3. **The package metadata declares it** (PEP 639):
   - `pyproject.toml` has `license = "GPL-3.0-only"` and `license-files = ["LICENSE"]`;
   - the wheel carries `License-Expression: GPL-3.0-only` and the license file;
   - the sdist carries the license file.

   `tools/build_release.py` reads the expression with `tomllib`, and `docs/release/DEPENDENCIES.json` records it. The earlier regular expression would have kept the TOML quotes.
4. **Contributions come under the same license** (inbound equals outbound), as the README says. No contributor agreement is required.

## Consequences

- The checklist's `release_artifacts` no longer names the license.
- What remains before publication:
  - **Signing:** the planned route is GitHub's artifact attestations, keyless and tied to the repository's workflow. It is not yet enabled, because each run writes to a public transparency log.
  - **The package name:** it has not been checked on the package index (decision 0001).
  - **The owner's go-ahead to publish.**
- `0.1.0.dev10`'s wheel as tested by the gates predates the license metadata. The code is unchanged; the next build carries the license.
