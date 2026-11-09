# Changelog

Engine versions of the `claude_preview` profile, newest first. Every entry names the decision record that carries the full reasoning, tests and limits (`docs/decisions/`). No version below is released; see `docs/release/claude_preview_checklist.json` for what the release waits on.

## 0.1.0.dev15 (2026-11-09) — public-repository hygiene

Decision 0047. No engine behavior changed. Every module carries an SPDX license identifier; the source distribution holds only what builds and installs the engine; the repository gains `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, this changelog, issue and pull request templates and Dependabot; OPERATIONS states what is stored and sent, how to uninstall and what a preview store can expect to survive; workflow actions are pinned to commits with concurrency groups, and release attestation is scaffolded behind an opt-in; the design packet moved to `docs/history/packet/`; the probes name their failed checks, hint at the CA bundle on a TLS failure, record only an endpoint's scheme and a hash of its host, and scrub home directories, UNC paths and emails from reports; a live gate record pins the digests of its scenarios, oracles and overlays and refuses a dirty tree unless told otherwise.

## 0.1.0.dev14 (2026-11-09) — an install path a stranger can follow

Decision 0046 (audit Phase 3). The bootstrap has the pre-init `init` and `operator-token create` forms and provisions an empty directory or a fresh clone; a release is a directory with the wheel, `bootstrap.py`, `requirements.lock` and one hash-locked wheelhouse per platform and Python; the wheel installs a `recalith` console script. `integrate claude` judges tracking by the repository's top level, refuses an unknown state and a symlinked settings file, and keeps the settings file's mode. `status` and `doctor` without `--json` print one screen with each code's meaning and the next command. `doctor --full-integrity` is guarded. The curator key's location is stated.

## 0.1.0.dev13 (2026-11-08) — retrieval holds at corpus scale

Decision 0045 (audit Phase 2). Statically inapplicable claims are skipped before the candidate caps on both compilers; the hook's pre-action compile reads its own action family; the live dependency check runs for every live claim with dependencies; the query is ranked in SQL (p95 about 100–118 ms at 10,000 heads sharing the query words); a store that loses FTS5 falls back to the token index; omitted counts, quoted-evidence checks and conflict wording corrected; the local-filesystem guard covers VM and WSL shared folders and the macOS and Windows remote cases.

## 0.1.0.dev12 (2026-11-08) — the worker never spins, starves work or dies silently

Decision 0044 (audit Phase 1). Model leases cover every expansion round; a near-fit budget wait has a due time; every lease is an attempt on the backoff ladder; a poll step's error is contained and a fatal one leaves `crashed`; unjudged review candidates are retried, bounded; the retention sweep pages past pins; `backup.holds()` checks the bookkeeping the purge scrubs; an unresolved range becomes an open episode at the idle pause; lineage covers every certified host version; the session lock is held by one hook; the CLI envelope keeps U+2028 and names its error results.

## 0.1.0.dev11 (2026-11-08) — secrets in split arguments, loopback never proxied, parts sized as stored

Decision 0043 (audit Phase 0). `--password VALUE` and `NAME=value` across argument boundaries are scrubbed; more text patterns; a loopback curator request never goes through a named proxy; a partitioned message's parts are sized by their canonical JSON so none is lost; tracked probe evidence is checked for residue.

## 0.1.0.dev10 (2026-11-04) — a claim says no more than its evidence

Decision 0040. The extractor's wording rule and the reviewer's check that a claim's detail is in its cited evidence; the R3 oracle fix of decision 0028 item 30. The live smoke quality gate passed on this engine (its tenth run) with the owner's recorded labels.

## 0.1.0.dev9 (2026-11-03) — a patch value has its field's shape

Decision 0039. `update_task` patch values are validated to the field they patch, so bare strings where a supported text belongs are refused with the reason named; the refused replies of the sixth and seventh gates no longer occur.

## 0.1.0.dev8 (2026-11-03) — a malformed operation says what failed

Decision 0038. Each refused operation records which field failed which rule; the gate harness keeps what each refused claim cited.

## 0.1.0.dev7 (2026-11-02) — a masked failure is worded as the project's condition

Decision 0037. A failure hidden by a pipe or a wrapper is admitted as a condition of the project, not as the wrapper's success.

## 0.1.0.dev6 (2026-11-01) — declared facts talk only sessions and resume

Decision 0036. A user's statement about the project is a fact, not a decision, unless it decides something; sessions that only talk are curated; the one active task resumes across sessions.

## 0.1.0.dev5 (2026-10-31) — extraction keeps declarations and masked failures

Decision 0035. `extract_claims@3`: a declared decision is extracted even when nothing was built on it, and a failure masked by a pipe's exit status is still a lesson.

## 0.1.0.dev4 (2026-10-29) — the ordinary input budget fits the invocation cap

Decisions 0032 to 0034. An attached contradiction is a revalidation trigger; a file dependency records the bytes its read observed; the ordinary input pool is 1,500,000 tokens so the invocation cap, not the input pool, bounds a day.

## 0.1.0.dev3 (2026-10-29) — extraction asks for the files a claim describes

Decision 0031. The extractor requests the reads a claim depends on before it is admitted.

## 0.1.0.dev2 (2026-10-29) — read evidence records its file dependency

Decision 0030. A certified read of a file the claim describes becomes the claim's file dependency.

## 0.1.0.dev1 (2026-10-26) — reasoning headroom and the 2.1.310 host

Decision 0029. The curator's output allowance leaves room for reasoning; Claude Code 2.1.310 is capture-certified.

## 0.1.0.dev0 (2026-10-15 to 2026-10-23) — the preview engine

Decisions 0001 to 0028: the installation model, capture, the worker, admission, consolidation, retrieval, delivery, retention, forgetting, health, the Claude Code integration, native Windows, the live evaluation installations. The first live pilots and gates ran on this engine.
