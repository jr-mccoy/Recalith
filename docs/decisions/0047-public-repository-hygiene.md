# Decision 0047: Public-repository hygiene

Status: accepted (Tasks 1, 18 and the repository itself) · Date: 2026-11-09 · Engine: `0.1.0.dev15` (no behavior change) · Observed: the pre-publication audit of `0.1.0.dev10` ([report](../audits/2026-11-06-memory-system-audit.md), Phase 4 of [the fix plan](../audits/2026-11-06-fix-plan.md))

## Context

The audit judged the repository as a stranger would read it before installing anything, and found that the artifacts and pages did not yet read as a maintained public project.

- **REL-2 (medium):** the source distribution had no include list: 3.2 MB with 485 documentation files, tests, evaluations, tools, the review packet (carrying the owner's name) and the workflows. The license inventory covered the wheel only.
- **REL-3 (medium):** BUILD_PROGRESS, where README sends newcomers first, said in its tracking rows that the live trial path had not run and that the acceptance evidence was none, two rows below the record of the tenth gate's pass; its Implementation cell stopped at decision 0034; it was 2,700 lines of narrative.
- **REL-4 (medium):** no `SECURITY.md`, `CONTRIBUTING.md`, code of conduct, changelog, issue or pull request templates, no Dependabot.
- **REL-5 (medium):** nothing told a user that scrubbed prompts, tool output and file excerpts are sent to the provider and retained under its terms; there was no uninstall section; nothing said whether a preview store survives the next engine.
- **REL-8, REL-9, REL-11 (low):** no copyright holder or SPDX identifiers anywhere, and the build's foreign-copyright check would have rejected the project's own notice; actions pinned by major tag, no concurrency guard, no attestation scaffold; `MANIFEST.json` said the project was not started, and `review/` shipped with the owner's name in it.
- **PROV-5, PROV-6, PROV-7 (low):** the probes' console output named failing dimensions but not failure codes and gave no TLS hint; the tracked report recorded an endpoint's path and host, with only the query checked for credentials; the sanitizer knew only the invoking user's home and the repository root.
- **EVAL-1 (medium):** the passing gate record could not be reproduced exactly: the tree was dirty and the report pinned no digest of the scenarios or oracles, which were edited twice during the gate cycle.

## Decisions

1. **The source distribution holds what builds and installs the engine:** `src/recalith`, `README.md`, `LICENSE`, `CHANGELOG.md`, `pyproject.toml`, `bootstrap.py`, `requirements.lock`, `uv.lock` (anchored include patterns; a `README.md` elsewhere is not pulled in). Tests are excluded too: a suite without `tools/` and the fixtures' neighbors would not run, and the repository is where tests run. `tools/build_release.py` inventories the sdist (no file under `docs/`, `evals/`, `review/`, `.github/`, `tests/`, `tools/`, `probe-private/`, no `MANIFEST.json`; no foreign copyright header) and fails on a stray.
2. **Every module carries `# SPDX-License-Identifier: GPL-3.0-only`** (after a shebang where there is one; the generated `fast/wire_generated.py` through its generator). The per-file copyright line waits for the owner's holder name; `pyproject.toml`'s `authors` says "Recalith contributors" meanwhile. The foreign-copyright check now flags a notice that does not name Recalith, in either spelling, in the wheel and the sdist. CONTRIBUTING states the GPL points plainly: license in, license out, no CLA; the engine is GPL-3.0-only ("only" deliberate); generated launchers and the user's memory are the user's.
3. **Community files:** `SECURITY.md` (private reporting through GitHub security advisories; scope: the engine, hooks, store, bootstrap and probes; out of scope: a hostile same-user process, as SYSTEM_SPEC §13 says; a fix ships as a version with a decision record and a test), `CONTRIBUTING.md`, a short original `CODE_OF_CONDUCT.md`, `CHANGELOG.md` seeded from decisions 0029 to 0047 and the `dev0` to `dev15` engines, issue templates (bug, feature) and a pull request template that repeat the rules that matter (what never enters the repository; no gate weakened), and `.github/dependabot.yml` for `github-actions` and `uv` (proposals only; the locks stay authoritative).
4. **OPERATIONS gains §7 "What Recalith stores and sends"** (what the hooks capture; what the scrubber replaces and its stated limit; exactly what a curator request carries, its 96 KiB cap, when it is sent and to whom; that a forget does not reach the provider; the retention windows), **§8 "Uninstalling"** (`integrate claude --remove`, `worker stop`, the private state to delete, what the tracked files mean for collaborators; nothing is installed outside the project) and **§9 "Compatibility of preview stores"** with the stated promise: a later `0.1.0` preview engine migrates a schema-12-or-newer store in place or refuses it visibly, never silently drops memory; before `0.1.0` final a non-migratable change is announced, and a preview store may need deleting. README's status block links all three.
5. **BUILD_PROGRESS is the current state:** the current-state table (Implementation refreshed through decision 0047; row 13 and row 18 refreshed; the acceptance line names the tenth gate's pass and that no live run has observed the fixed engines), the execution order, the work packages, a pointer to the checkpoints, the B1 blocker's summary and commands, and a four-item handoff: 78 lines. The per-checkpoint narrative (43 October and 18 November checkpoints), the "status after each task" history and the 2026-11-09 handoff moved verbatim to `docs/history/build-log-2026-10.md` and `build-log-2026-11.md`; a reference elsewhere to "the X checkpoint in BUILD_PROGRESS" resolves there, and new checkpoints are appended to the current month's log.
6. **Workflows:** every action is pinned to a commit with its version in a comment (`actions/checkout` v4.4.0, `actions/upload-artifact` v4.6.2, `actions/download-artifact` v4.3.0, `astral-sh/setup-uv` v6.8.0, `actions/attest-build-provenance` v3.2.0); `ci.yml` and `release.yml` cancel an older run of the same branch, `measure.yml` queues behind it (measurements are compared across runs). The release workflow has an `attest` job behind a `workflow_dispatch` input, off by default, with `id-token: write` and `attestations: write` only on that job; it publishes digests to the public transparency log, which the owner has not yet accepted.
7. **The design packet moved to `docs/history/packet/`** (`MANIFEST.json`, `review/`) with a README that says what it is and that it is not current policy; AGENTS, the handoff and the starter packet point there.
8. **The probes:** the console line carries `failed_checks` (the failure codes behind the blocking dimensions) and, on a `tls_*` failure, a stderr hint naming `SSL_CERT_FILE`/`SSL_CERT_DIR` in `network_env_keys` (verification is never turned off); on `selected_auth_missing`, that the key is not exported in this terminal. The tracked report records an endpoint as its scheme and a 16-hex-digit hash of its host, never the host or the path (the project's private route record keeps the URL); `ApiEndpoint` refuses a credential-shaped path segment as it already refused a credential-shaped query. The report sanitizer replaces any `/home/<user>`, `/Users/<user>` and `C:\Users\<user>` (every spelling), any UNC path and any email address with `<home>`, `<unc>`, `<email>`, after the explicit replacements.
9. **The gate record pins its inputs:** `versions.inputs` holds the SHA-256 of every smoke scenario, overlay, oracle module, workload day, the recorded curator and the scripted agent; `versions.allow_dirty` records the flag. A live `gate` from a repository with uncommitted changes is refused (exit 2) unless `--allow-dirty` is passed, which is then recorded. Smoke, workload and demonstrate runs record `tree_clean` as before.
10. **Engine `0.1.0.dev15`.** The wheel's bytes change (the headers), so the version does; no behavior changed and no adapter changed.

## Rejected

- **Including `tests` in the sdist** (the plan's list). Half a suite (no `tools/`, no `evals/`) that cannot run misleads more than it helps.
- **Adding a copyright line with a guessed holder.** The holder name is the owner's decision (fix plan, owner actions); the SPDX identifier carries the license meanwhile.
- **Cancelling in-progress measurement runs.** A newer push would discard a 10-minute idle-footprint sample that later runs are compared against.
- **Refusing every live run from a dirty tree.** The owner's pilots and smoke runs are exploratory; only the gate record is a claim.

## Tests

- `tests/unit/test_release_tools.py`: the sdist inventory names repository files and foreign notices; the release layout test uses a real (tiny) sdist.
- `tests/unit/test_capture_sanitization.py`: generic homes in every spelling, a UNC path and an email are replaced; digests and ordinary paths are not.
- `tests/unit/test_api_probe.py`: the recorded origin has no host or path; the console summary names the failed checks and prints the TLS hint.
- `tests/unit/test_contracts.py`: a credential-shaped path segment is refused; an ordinary path is accepted.
- `tests/unit/test_eval_harness.py`: `versions()` pins every input's digest; a live gate from a dirty tree is refused and `--allow-dirty` is recorded.
- The release build (`tools/build_release.py`) ran here: `problems: []`, the sdist holding `src/` and the eight root files only.

## Limits

- **The copyright line and the security contact are not done** until the owner names the holder and turns on private vulnerability reporting in the repository settings; `SECURITY.md` says what the route is.
- **The attestation job has not run.** It is a scaffold; the owner enables it with one dispatch input after accepting the public transparency log.
- **Dependabot proposals need the owner's review;** nothing merges by itself and CI runs `--locked`.
- **The history logs are verbatim**, so their internal wording ("this checkpoint", "below") refers to their original place.

## Consequences

Phase 5 is the owner's: a fresh pilot from the release layout by OPERATIONS §4, the live gate on the fixed engine from a clean tree, and the publication decisions (the holder name, the contact route, attestation, the tag form).
