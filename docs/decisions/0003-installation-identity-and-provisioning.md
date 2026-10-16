# Decision 0003: Installation identity, relocation and runtime provisioning

Status: accepted (Task 2) · Date: 2026-10-16

## Context

SYSTEM_SPEC §2 requires that a fresh clone gets a new installation while keeping the logical project ID, that a moved project rebinds explicitly, and that copied private state never starts a second writer under the original installation identity. The contracts did not name the error a caller sees for a moved or copied checkout, nor the operator commands that resolve it.

## Decisions

1. **Identity files.** Tracked `.recalith/project.toml` carries only `config_schema`, `project_id`, `domain_profile` and `release_profile`. Ignored `.recalith/local.toml` (mode 0600) carries the installation ID, workspace ID, canonical workspace root and the root's device:inode identity. `init` writes `local.toml` last, so its presence marks a complete installation. An init that crashed after the store rename is completed from the store's own metadata when the store's primary workspace is this root. A self-contained `.recalith/.gitignore` tracks exactly `project.toml`, `engine.lock` and `bin/`; the user's root `.gitignore` is not edited.
2. **Location classes.** `resolve_installation` compares the recorded root with the actual root by file identity (`samefile`), never by lowercasing. The checkout is `same`, `copied` (the recorded root still holds a `local.toml` with the same installation ID) or `moved`. Both `copied` and `moved` raise the new stable code **`installation_relocated`** (exit 4). There is no automatic rebinding.
3. **Operator resolution.** `recalith workspace rebind` (operator only) accepts a move: it updates the workspace row and `local.toml` and records a `workspace_rebind` operation. It refuses a copy. `recalith workspace discard-copy` (operator only) deletes a detected copy's private state so `init` can create a fresh installation that keeps the project ID. It refuses to run on an original. Both are administrative, agent-refusable forms (DATA_CONTRACTS §12). Their CLI transport arrives with Task 12a; the service functions exist now.
4. **Local filesystem.** On Linux, `init` and `rebind` read `/proc/self/mountinfo` and refuse a known network filesystem (`storage_failure`). Elsewhere the filesystem type is reported as unknown rather than assumed local.
5. **Store.** Migration 0001 creates every DATA_CONTRACTS §10 table as a SQLite `STRICT` table with typed hot columns, which requires SQLite 3.37 or newer. An older SQLite makes the store `capability_unavailable`. `PRAGMA user_version` and `installation_meta.schema_version` must agree. A newer schema opens neither read-write nor read-only, because no compatible reader exists yet.
6. **Provisioning.** The stdlib `bootstrap.py install` verifies the explicit engine wheel digest. It then installs the wheel plus the hash-locked dependencies in `requirements.lock` (exported from `uv.lock`) from a local wheelhouse with `pip --no-index --require-hashes`, stages them in a temporary directory and activates with one rename. It records the digest in the tracked `engine.lock`. Nothing is downloaded, and hooks never call it. Building the wheelhouse is a release-pipeline step; CI exercises the full path on Linux.
7. **Interim entry point.** Until Task 12a, `python -m recalith` answers every command with `capability_unavailable` (exit 4), so the launcher chain is testable without pretending to succeed.

## Consequences

`InstallationContext` remains the only way to reach a store. Tasks 3–5 add repositories on top of `Store.transaction(expected)`, which enforces identity, schema, policy and tombstone epochs and the expected entity revisions. Workspace attachment, project fork and shared integration remain `capability_unavailable` in preview.
