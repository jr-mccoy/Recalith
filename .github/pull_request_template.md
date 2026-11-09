## What changes, and why

One change. Name the finding, the decision record or the document section it serves.

## Checks

- [ ] a test at the owning boundary fails without this change
- [ ] `uv run python tools/generate_schemas.py --check` and `tools/generate_hook_wire.py --check` pass
- [ ] `requirements.lock` is unchanged, or regenerated from `uv export --locked --no-dev --no-emit-project`
- [ ] the normative documents (SYSTEM_SPEC, DATA_CONTRACTS, ACCEPTANCE_TESTS) and `tests/coverage_manifest.json` agree with the change; a contradiction has its decision record
- [ ] nothing private: no credentials, transcripts, store files, machine paths, user names or model identifiers
- [ ] no test skipped, disabled or quarantined to obtain a pass

## Tests run

The command and its summary line.
