# Contributing

Recalith is an experimental preview. Contributions are welcome under the rules below, which exist so that nothing private, misleading or unverified lands in a public repository.

## License in, license out

Recalith is licensed under **GPL-3.0-only** ([decision 0042](docs/decisions/0042-gpl-3-license.md)). By contributing you agree that your contribution is licensed under the same terms. There is no contributor license agreement and no copyright assignment: you keep your copyright. "Only" is deliberate: the code is not offered under later GPL versions.

Plainly:

- the engine, its tools and tests are GPL-3.0-only;
- the launchers `recalith init` writes into a project (`.recalith/bin/`) are generated files for that project and carry no license condition for the project they serve;
- your project's memory (`.recalith/` private state, backups, exports) is your data; the license covers the engine, not what it stores.

Every module carries `# SPDX-License-Identifier: GPL-3.0-only`. Keep it on new files.

## Setting up

```bash
uv sync --locked          # the exact locked environment CI uses
uv run pytest             # the whole suite (about 45 minutes; the kill/restart families are slow)
uv run pytest tests/unit  # the quick part
```

Before you push: `uv run python tools/generate_schemas.py --check` and `uv run python tools/generate_hook_wire.py --check` must pass (they fail on unversioned contract drift), `requirements.lock` must match `uv export --locked --no-dev --no-emit-project` (CI diffs it), and `uvx ruff@0.14.0 check --select F,E9,B` should be clean on what you touched.

## What a change needs

- **A test at the owning boundary** that fails without the change. A mock, a stub or a unit test cannot establish a live certification; those come from the owner's live runs.
- **The normative documents** ([SYSTEM_SPEC](docs/SYSTEM_SPEC.md), [DATA_CONTRACTS](docs/DATA_CONTRACTS.md), [ACCEPTANCE_TESTS](docs/ACCEPTANCE_TESTS.md)) own behavior. A change that contradicts them resolves the contradiction there first, with a **decision record** under `docs/decisions/` (number, context, decision, rejected alternatives, tests, limits). Routine implementation choices need no record.
- **Schemas and the coverage manifest** stay aligned with the contracts (`tests/coverage_manifest.json` maps acceptance cases to tests, so a renamed test is a manifest change).
- **No weakening a gate** to obtain a pass: never skip, disable or quarantine a test; report an empirical failure as a failure.

## What never enters the repository

- credentials, operator-token values, `.env` files, `probe-private/`, any `.recalith/provider.json`, `host.json` or `local.toml`;
- raw transcripts, live memory state, backups, measurement or probe output that holds machine paths or user names;
- `dist/`, `wheelhouse/`;
- **model identifiers**, in code comments, commits or documents (say "an outside model" or "the curator"); the tracked evidence reports are sanitized for them (`tools/sanitize_report.py`).

Tracked probe and gate evidence goes through `tools/live_gate/sanitize_record.py` first, and every scan count must be zero.

## Commits and pull requests

- Commit messages say what changed and why, in plain terms. They carry no `Co-Authored-By` trailer and no model identifier.
- One change per pull request, with its test and its document updates. Use the pull request template.
- `main` holds the latest work; the owner publishes by pushing it.

## Communication

The owner's time is the scarce resource. Explain results and choices in plain terms, recommend one option, and keep any step the owner must run to the exact command.
