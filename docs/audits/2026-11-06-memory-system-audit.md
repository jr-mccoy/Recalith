# Recalith memory-system audit

Date: 2026-11-06 · Engine audited: `0.1.0.dev10` at commit `500fbb5` · Purpose: find the errors and oversights that stand between the current preview and a version fit for public use.

Companion: [the phased fix plan](2026-11-06-fix-plan.md).

## 1. Verdict in brief

The design is coherent and most of it is implemented the way the specification says. The deterministic kernel (installation isolation, the operator guard, transactional application, pin-aware retention, forgetting and suppression-aware restore, the §8.2 advice table, the provider boundary's TLS/redirect/key rules) held up under review and under targeted reproduction. The architecture choices that matter most for a public tool are sound: hooks never write SQLite, no model call sits inside a write transaction, the model proposes and code decides.

It is not yet fit for strangers. The audit found **one critical and eleven high-severity defects**, plus about thirty medium and low ones, in four clusters:

1. **Secrets escape the scrubber.** A password or token passed as a separate shell argument (`--password hunter2`) survives into the durable spool, the store, the context delivered back to the model, and the curator's provider requests, while the event is marked `redacted: true`. Common `.env` names (`SECRET_KEY=`, `DB_PASS=`) are not scrubbed in text at all. A named `HTTP_PROXY` sends a loopback plain-HTTP curator request, key included, to the proxy host.
2. **The worker can spin or starve.** A model job whose evidence-expansion rounds outlast its 180-second lease is relaunched forever, two charged calls per cycle; a job that nearly fits the budget is leased and re-prepared every second and blocks protected revalidation behind it; the retry ladder never advances for non-launch failures; an ordinary Python exception in a poll step kills the worker while its status file still says idle; the retention sweep livelocks once 4,096 old payloads are pinned.
3. **Retrieval drops the right answer at scale.** Applicability is evaluated after fixed candidate caps, so a store with enough same-topic claims scoped to another operating system silently drops the one applicable fact; the hook's pre-action view keeps 64 lessons across all action families, so 65 unrelated lessons remove the caution for the action about to run, and the hook reports healthy delivery.
4. **Nobody can install it from the documentation.** The README quick start is circular (`bootstrap.py` needs the file only `init` writes; `init` is reachable only through a launcher that `init` creates), `bootstrap.py` dies with a traceback on exactly the clone it was built for, there is no `recalith` console command, release artifacts lack `bootstrap.py` and the lock file, the sdist ships the whole repository, and `integrate claude` silently edits a git-tracked settings file when the project is a subdirectory of a repository.

Separately, the evaluation that justifies the preview is weaker than its "passed" label suggests (§5): one trial per arm, gold and oracles written and twice edited by the same coding agent during the gate cycle, a run recorded from a dirty tree, two gold retrieval points that the design cannot satisfy, and a corpus on which the headline benefit (fewer repeated failures) is unmeasurable because the no-memory baseline never fails. What the run does establish is the cost side: the candidate used about 18 % more foreground tokens than the baseline and roughly 220,000 background tokens per scenario.

The fixes are tractable. None requires a redesign; the plan estimates three to four weeks of focused work before a re-run of the live gate and a Linux certification.

## 2. Scope and method

Eight independent reviewers each took one subsystem, read the source against SYSTEM_SPEC and DATA_CONTRACTS, and reproduced findings with small scripts against real installations built with the test factories wherever that was cheap. The lead re-ran the critical reproduction, audited the evaluation harness and the tenth-gate record, and ran the full deterministic suite. Nothing under `src/`, `tests/` or `evals/` was modified. No guarded or credential-bearing command was run, and no environment marker was removed.

| Area | Files | Reviewer's reproduction scripts |
|---|---|---|
| Hook fast path | `src/recalith/fast/**`, `capture/hooks.py`, launchers | 3 |
| Storage, retention, forgetting, backup/restore | `storage/**`, `privacy/**` | 2, plus an end-to-end forget and restore |
| Controller and worker | `controller/**`, `prompts/**` | 2 (fake provider, virtual clock) |
| Providers | `providers/**`, `tools/probe_*`, `check_provider_runtime.py` | 2 (loopback servers) |
| CLI, service, integration, bootstrap, health | `cli/**`, `service.py`, `integrations/**`, `operations/**`, `bootstrap.py` | ~40 CLI invocations against scratch projects |
| Capture, lineage, working state, contracts | `capture/**`, `core/**`, `working/**`, `episodes/**`, `contracts/**` | 5 |
| Retrieval and delivery | `retrieval/**`, view and lookup publication | 5 (real stores up to 10,000 heads) |
| Release readiness | docs, packaging, CI, tracked evidence, quick-start walkthrough | full quick start in a scratch clone |

Each finding is labeled **verified** (reproduced, or traced line by line to a definite conclusion) or **suspected**. Severity: **critical** = secret leak, data loss, security bypass or wrong memory served as fact; **high** = a feature is broken or a spec rule violated in a way users will hit; **medium** = edge case, degraded behavior or misleading report; **low** = hygiene.

Finding IDs are prefixed by area: FP (fast path), CAP (capture/core/working), CTL (controller), PROV (providers), RET (retrieval), STO (storage/privacy), CLI (CLI/integration), REL (release), EVAL (evaluation). The reviewers' full notes, including the exact scripts and outputs, are preserved in the session scratchpad and summarized here.

## 3. Findings by severity

### Critical

| ID | Finding | Status |
|---|---|---|
| FP-1 | CLI secrets passed as separate arguments survive in `action.argv` and reach the spool, store, delivered context and provider | verified, reproduced twice |

### High

| ID | Finding | Status |
|---|---|---|
| CAP-1 | Oversized user messages with escape-heavy text are partitioned by raw bytes but capped on canonical JSON; the parts fail validation and the message is silently lost | verified |
| CAP-2 | Text redaction misses `SECRET_KEY=`, `SECRET_KEY_BASE=`, `*_SIGNING_KEY=`, `ENCRYPTION_KEY=`, `DB_PASS=` although the JSON-key scrubber treats them as sensitive | verified |
| PROV-1 | A named `HTTP_PROXY` makes urllib proxy a loopback plain-HTTP curator request; the proxy host receives the request and the bearer key in cleartext | verified |
| CTL-1 | Model lease (180 s) is never renewed across evidence-expansion rounds; a long job is fenced, re-leased and relaunched indefinitely, charging two calls per cycle, never `failed` | verified |
| CTL-2 | A job that passes the one-token lower bound but not its exact reservation is leased and re-prepared every second and starves every lower band, including protected revalidation | verified |
| RET-1 | Applicability is evaluated after the 96-seed lexical cap and the 64-postings lookup cap; inapplicable claims fill the slots and the applicable fact is omitted with no degraded reason | verified |
| RET-2 | The hook's pre-action view holds 64 action-family claims across all families by strength; 65 unrelated lessons remove the current action's caution while the hook reports a healthy view | verified |
| CLI-1 | `bootstrap.py install` crashes with a raw `FileNotFoundError` on a fresh clone of an initialized project (stages into `runtime/`, which only `init` creates) | verified |
| CLI-2 | The quick start is circular: bootstrap needs `project.toml`, which only `init` writes, which is reachable only through the launcher `init` creates; no `recalith` console script exists; the spec's bootstrap pre-init forms do not exist | verified |
| CLI-3 | `integrate claude` skips the "tracked settings file is refused" rule when the project is a subdirectory of a git repository or when git fails (dubious ownership), and misreports the ignore state | verified |
| REL-1 | Release artifacts omit `bootstrap.py`, `requirements.lock` and any wheelhouse; the wheelhouse recipe exists only in `ci.yml` and is platform- and Python-version-specific | verified |

### Medium

| ID | Finding | Status |
|---|---|---|
| FP-2 | `prune_abandoned` deletes a live session's lock file after 24 h (mtime never refreshed); two hooks can then hold different lock inodes and race on scratch | verified |
| CTL-3 | The 1/5/30-minute backoff ladder advances only after a reservation; any persistent prepare/apply failure retries every 60 s forever and never reaches `failed` | verified |
| CTL-4 | A non-`RecalithError` exception in a poll step (planner, projection, retention, triggers) kills the worker; the status file still says `idle`; hooks relaunch it into a crash loop | verified |
| CTL-5 | A candidate whose review verdict was missing, `revise` or `review_capacity` is never reviewed again; the spec promises bounded retries | suspected (traced) |
| CAP-3 | Further redaction gaps: URL passwords containing `/`, `Cookie:` headers, `mysql -pPASS`, GitLab/SendGrid/Azure SAS/bare AWS secret shapes | verified |
| CAP-4 | The lineage artifact-snapshot rule is pinned to Claude Code 2.1.301; on the four other certified versions identical file reads from different working directories count as separate roots | verified |
| CAP-5 | A session that ends with an unresolved failing test never yields an episode (only the 64-step cap flushes); failed attempts are exactly what memory should keep | verified |
| CAP-6 | The local-filesystem guard misses `vboxsf`, `virtiofs`, `vmhgfs`, `drvfs`, generic `fuse`; it does nothing on macOS or Windows | verified by reading |
| RET-3 | Deterministic context query misses p95 ≤ 150 ms on common-term prompts at 10,000 heads (p50 167 ms, max 217 ms); the recorded figure is a p50 on a favourable corpus | verified |
| RET-4 | A failure lesson with unknown applicability skips the live dependency check and is shown `current` after an outside edit, while a fact with the same dependency is correctly labeled | verified |
| RET-5 | The lexical backend is sticky: a store moved to a SQLite build without FTS5 keeps `fts5`; projection, service search and forget's `optimize` then fail | selection verified, consequence traced |
| RET-6 | `fit()` under-reports `omitted_count` when both the packet cap and the session allowance cut (3 reported, 17 actual) | verified |
| STO-1 | The retention sweep takes its 4,096-row window before filtering pins; once the oldest 4,096 age-eligible payloads are pinned nothing expires again and the full sweep re-runs every poll | verified |
| STO-2 | `backup.holds()` checks only payloads, capsules and revision bodies; a backup that keeps forgotten text in `operations.inputs` or `proposals.body` is not treated as affected by a forget | verified by trace |
| PROV-2 | The Claude CLI envelope is split with `str.splitlines()`, which breaks on U+2028/U+2029/U+0085 that Node leaves raw; the reply is charged and fails as `envelope_invalid` | verified |
| PROV-3 | Every Claude CLI error result (revoked key, rate limit) collapses to `envelope_invalid`; a CLI auth rejection never withdraws the route | code path verified |
| CLI-4 | `integrate claude --remove` exits 5 forever when the pre-install settings file was whitespace-only | verified |
| CLI-5 | A symlinked `.claude/settings.local.json` is replaced by a regular file; `--remove` reports `byte_identical` | verified |
| CLI-6 | The production worker receives the curator key only from Claude Code's own environment; no document tells the user to export it in the shell that launches Claude Code | verified by reading |
| REL-2 | The sdist ships the entire repository (3.2 MB: the 555 KB build log, 369 evaluation files, `review/` with the owner's name) | verified |
| REL-3 | `BUILD_PROGRESS.md`'s current-state table says the live gate never ran and there is no acceptance evidence; the same file records the tenth gate's pass | verified |
| REL-4 | No `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, changelog, issue templates or Dependabot | verified |
| REL-5 | Users are not told what data leaves the machine, how to uninstall, or that a preview store may not survive the next release (no migration exists; `init` refuses to start over) | verified |
| EVAL-1 | The passing gate record cannot be reproduced exactly: the tree was dirty (`tree_clean: false`), and the report pins no digest of the scenarios or oracles, which were edited twice during the gate cycle | verified |
| EVAL-2 | The smoke corpus cannot measure the headline benefit: the no-memory baseline repeats no mistakes (0/0 on every scenario) because every answer is recoverable from the repository; the measurable effect is cost (+18 % foreground tokens, ~220 k background tokens per scenario) | verified from the record |

### Low

| ID | Finding |
|---|---|
| FP-3 | Oversized-output withdrawal leaves `restoration_tokens` inconsistent (unreachable today) |
| FP-4 | Directory-fsync failure after a successful rename is reported `not_captured` (phantom gap, dropped delivery) |
| FP-5 | The session-start notice tells Windows users to run `.recalith/bin/recalith status`, which cmd.exe cannot run |
| FP-6 | `_newest_gap` scans 512 of up to 1,000 gap files in unspecified order |
| FP-7 | The POSIX hook launcher propagates a nonzero exit and traceback when the venv exists but `recalith` cannot import; the `.cmd` launcher hides it |
| FP-8 | A notice whose envelope emission ended `uncertain` is never shown again |
| FP-9 | Every PostToolUse hook reads up to 8 MiB of `ledger.json` before any deadline check |
| CTL-6 | `Worker.tick` closes the model lane's connection from the main thread when a restore journal appears |
| CTL-7 | `limits.timeout_seconds` sent to the model is always 120 regardless of configuration |
| CTL-8 | `request_stop` writes the stop file with the umask mode |
| CAP-7 | `--password` with no value (psql's prompt flag) swallows the next argument |
| CAP-8 | Schema snapshots omit every operation payload model, `ToolPayload` and `ObservationDescriptor` |
| CAP-9 | Region detection misses `<pre>`/`<code>` blocks and `%`/`#` shell prompts |
| CAP-10 | `checkpoints()` pairs planned tasks with episode refs positionally |
| CAP-11 | "Paused within 24 h" uses `updated_at`, which any narrative patch refreshes |
| CAP-12 | An excerpt locator can address the omission marker when `result_text` was bounded to nothing |
| CAP-13 | `recover_source` never advances the cursor when every tail event is rejected |
| RET-7 | Fallback rows are not checked against the payload state of contradiction evidence they quote |
| RET-8 | Conflict items carry imperative text ("ask the user which applies") inside an advisory packet |
| STO-3 | The "read-only" view accepts `PRAGMA x = y` writes |
| STO-4 | `.recalith/run/backups/` is created with the umask (0755) instead of 0700 |
| STO-5 | Restore swap on Windows surfaces a raw `PermissionError` with no recovery hint |
| STO-6 | A backup directory with `.DS_Store`/`Thumbs.db` is unverifiable |
| PROV-4 | `argument_problems` inspects only the first `--tools` occurrence |
| PROV-5 | Probe console output names failing dimensions but not failure codes; no TLS/CA hint |
| PROV-6 | The tracked report records the endpoint path; only the query is checked for credentials |
| PROV-7 | The sanitizer covers only the invoking user's home and the repository root |
| CLI-7 | The user's settings file becomes 0600 after integrate; tracked `.recalith/` files are 0600 in a 0700 directory |
| CLI-8 | `init` on a clone silently ignores `--profile` |
| CLI-9 | `doctor` is documented as guarded for `--full-integrity` but runs unguarded; it writes a checkpoint in a full store |
| CLI-10 | Three registered error codes fall back to exit 5 |
| CLI-11 | `operator-token create --project` leaves the token file behind when registration fails |
| CLI-12 | `bootstrap.py install` deletes an unmarked existing runtime tree even if a worker runs from it |
| REL-6 | One tracked measurement file contains a coding-agent scratch path |
| REL-7 | Packaging metadata lacks urls, authors, classifiers, keywords |
| REL-8 | No copyright holder is named anywhere; the build's foreign-copyright check would reject the owner's own notice |
| REL-9 | CI actions pinned by major tag; no concurrency guard; attestation not scaffolded |
| REL-10 | `recalith status` prints hundreds of JSON lines and seven reason codes with no human summary or next step |
| REL-11 | `MANIFEST.json` says the project is not started; `review/` is shipped and carries the owner's name |
| REL-12 | "216 deny rules" is the POSIX count (450 on Windows); OPERATIONS §4 commands are abbreviated and do not run as written |

## 4. Findings in detail

### 4.1 Secrets and privacy (FP-1, CAP-2, CAP-3, PROV-1, PROV-6, PROV-7, STO-2)

**FP-1 (critical).** `fast/claude_capture.py` `build_action` splits the *raw* Bash command into `action.argv` and only then scrubs each element on its own. The per-string scrubber cannot see a flag/value pair, so `mytool --password hunter2secret --host db` yields `arguments.command: mytool --password [REDACTED:cli_secret] --host db` next to `argv: ["mytool", "--password", "hunter2secret", "--host", "db"]`, with `coverage.redacted: true`. Reproduced end to end with the real `python -I -m recalith.fast.entry` on a fixture PostToolUse payload: exit 0, receipt `accepted`, the secret present in the durable segment. The argv is rendered into the typed-outcome overlay the next hook delivers to the model (`fast/delivery.py` `_outcome_text` joins argv) and travels inside curator prompts. Any `curl -H`, `--token`, `--api-key` or `--password` invocation leaks. Token-shaped secrets (`ghp_…`) are caught per element; context-dependent ones are not. Fix: split the scrubbed command, then re-scrub joined argv; add a fixture test asserting `argv` never contains a substring that `arguments.command` redacted.

**CAP-2 (high).** The text `assignment` pattern in `fast/redact.py` ends only in `password|passwd|pwd|passphrase|secret|token|api_key|…` followed by a word boundary. `SECRET_KEY=`, `SECRET_KEY_BASE=`, `JWT_SIGNING_KEY=`, `ENCRYPTION_KEY=`, `DB_PASS=` do not match, while `scrub_json({"SECRET_KEY": …})` does redact. `cat .env`, `cat settings.py` and `env` output store these values verbatim and send them to the provider. Fix: derive the text name grammar from the same token rules as `sensitive_key`.

**CAP-3 (medium).** URL passwords containing `/` (`postgres://alice:p/ss@host`), `Cookie:`/`Set-Cookie:` headers, `mysql -pHunter2`, and GitLab `glpat-`, SendGrid `SG.`, Azure `sig=`, bare AWS secret keys are not covered.

**PROV-1 (high).** `http_transport.py` decides "plain HTTP is allowed" from the URL hostname and then hands the request to urllib's `ProxyHandler`, which proxies loopback hosts whenever `http_proxy`/`HTTP_PROXY`/`ALL_PROXY` is set and `no_proxy` does not exempt them. Live mode forwards `network_env_keys` without setting `NO_PROXY`, and `nonsecret_env` accepts a proxy URL. Reproduced with two loopback servers: the endpoint saw nothing, the proxy received `POST http://127.0.0.1:PORT/v1/chat/completions` with `Authorization: Bearer <key>`. The repository's own test (`test_api_providers.py:437-447`) asserts the proxied behavior as expected. Fix: build the opener with `ProxyHandler({})` for `http` URLs, forbid proxy names in `nonsecret_env`, flip the test.

**STO-2 (medium).** Forgetting deletes affected older backups, but `backup.holds()` scans only `events.payload`, `evidence_capsules.body` and `*_revisions.body`. The live purge also scrubs `operations.inputs`, `operations.reason`, `proposals.body`, `source_conflicts`, `deliveries.items`, because they hold the same text. A backup taken after payloads expired and bodies aged still carries the forgotten narrative in `operations.inputs` (never aged) and is kept, and no limit reports it. Restore itself re-purges, so the live store is safe; the backup directory on disk is not.

What held: `capture/redact.py` is literally the same module object as `fast/redact.py`, so the two paths cannot drift; scrubbing runs before digesting, bounding, spooling and provider transmission; the key is read by name inside the transport child and appears in no argv, log, record or report; TLS has no bypass; redirects are returned as final responses and the target receives nothing; `provider.json` holds names only at mode 0600; the tracked tree holds no credential, user name or machine path except one scratch path in a measurement file (REL-6).

### 4.2 Hook fast path (FP-2 to FP-9)

**FP-2 (medium).** `SessionLock.acquire` never refreshes the lock file's mtime, and `prune_abandoned` deletes `.lock` files older than 24 h independently of their `.json`. A session alive for a day loses its lock file at the next SessionStart of any session; a hook that already holds the old inode keeps running while the next hook creates and locks a new file. Hooks of one session do run concurrently (parallel tool calls; subagent hooks share the parent `session_id`). The code and decision 0005 both state this cannot happen. Fix: prune a lock only when its scratch is gone or pruned in the same pass, or `os.utime` on acquire.

The remaining fast-path findings are low. FP-7 matters for first impressions: when the venv exists but the package cannot import (interrupted bootstrap), every hook exits 1 with a traceback and Claude Code shows a hook error on every event; the `.cmd` launcher hides the same condition.

What held: imports are stdlib plus `recalith.fast` and are enforced by fresh-process tests over real payloads; durability is temp → fsync → rename → directory fsync with exactly one Windows retry; SQLite reads use `mode=ro`, `query_only`, `busy_timeout=0`, a write-denying authorizer and one `BEGIN` snapshot, never `immutable=1`; the single 250 ms deadline and the shedding order and reason codes match the spec; reservation precedes emission and the receipt precedes the `emitted` mark under one lock; the fence is a fresh snapshot over all three epochs and every served head; stdout is empty or one JSON envelope and the process always exits 0; the worker start builds a fresh allowlisted environment, removes markers, and never routes through the guarded CLI.

### 4.3 Capture, lineage and working state (CAP-1, CAP-4 to CAP-13)

**CAP-1 (high).** `fast/normalize.py` `_partition` cuts long messages into 48 KiB pieces measured as raw UTF-8, but the 64 KiB cap enforced by `EventEnvelope` and the wire validator is the canonical-JSON length, where `"`, `\` and control characters expand. A 100 KiB user message of JSON-like text produced parts of 66,606 and 66,613 bytes, both invalid. On the worker path the whole message is refused; on the hook path the oversized parts are counted as `invalid_schema` and only the small final part is spooled, leaving `text_part index=2 count=3` with no siblings. A pasted JSON blob, Windows-path-heavy log or coloured terminal output is lost silently. Fix: size parts by their canonical JSON length.

**CAP-4 (medium).** `core/lineage.py` grants the `artifact_snapshot` root class (workspace + path + content digest) only when `adapter_version == "2.1.301"`. On 2.1.305 to 2.1.310, a complete `Read` falls to the generic experiment family, so two reads of the same unchanged file from different working directories form two root classes and can corroborate a claim. §7.1 says repeated reads of an unchanged file count once. Fix: tie `AdapterLineage.versions` to `claude_capture.CERTIFIED_VERSIONS` and test that they agree.

**CAP-5 (medium).** `episodes/segment.py` `decide` returns `None` whenever the range has an unresolved failure, even at session end; only the 64-step cap flushes. A session that ends red (common: the user gives up, or re-runs the test with `-v`, which changes the action signature) never produces an episode, so no narrative, no extraction, no declaration review for that attempt. Fix: at session end, emit an `open` episode carrying the failure in `unresolved`.

**CAP-6 (medium).** `identity.require_local_filesystem` refuses a fixed list of network filesystems on Linux and does nothing on macOS or Windows. VirtualBox, VMware, Parallels, WSL1 and generic FUSE mounts pass, and the user later meets `database is locked` or corruption instead of a clear refusal at `init`.

What held: strict contracts everywhere (`extra="forbid"`, `strict=True`, frozen, no `Any`); path authorization proves containment by file identity and refuses traversal, symlink escapes and NUL; transcript tail recovery handles partial lines, append, atomic-save replacement, truncation and symlinks; cursors never move backwards and are written only after publication; dedup and `source_conflicts` behave per contract; the environment allowlist drops unregistered keys without retaining values and never uses Recalith's own interpreter version; roots exclude assistant text, memory telemetry, calls without results, `echo`/`printf` and forwarded subagent output; conditions are tri-state and `unknown` never yields caution; the continuity rule, pivot prefixes, `@code` cluster and completion-evidence rules match §3.2; `config.py` defaults match every number in §6.3, §8.2 and §11.

### 4.4 Controller and worker (CTL-1 to CTL-8)

**CTL-1 (high).** `jobs.lease_seconds` is `timeout + 60` = 180 s, but `ModelLane._call` may run three provider calls of up to 120 s each plus three prepares without renewing (`jobs.renew` exists and has no caller). When the lease expires mid-job, the next fenced write raises; `step()` counts a fenced result and returns; the job stays `leased` with an expired lease and is re-leased at the next poll, generation + 1, from round 0. `jobs.fail` is never called, so the ladder is bypassed. Reproduced with a virtual clock: four lane steps → eight charged invocations, four fenced results, the job still `leased`. A single extraction that legitimately needs two slow expansion rounds can drain the day's ordinary pool. Fix: renew at each round, and treat a fenced result as a failed attempt.

**CTL-2 (high).** `lease_next` checks only `fits_lower_bound` (one input token plus the output cap). A job whose exact estimate does not fit is leased, fully prepared (96 KiB canonical JSON), refused by `reserve`, parked in `waiting_budget` with its `due_at` unchanged, and is the first candidate again one second later. Because candidates are ordered by band, no lower-band job is ever leased: a protected `revalidate` with 300,000 input tokens available never runs. Reproduced: 20 steps, revalidate still `pending`. Decision 0006 item 10 ("a job that cannot fit is never leased") holds only for the invocation dimension. Fix: on refusal, set `due_at` to the next UTC day or a bounded retry; in `lease_next`, skip rather than stop at a `waiting_budget` job whose dimension has not improved.

**CTL-3 (medium).** `attempt` grows only in `count_attempt` after a successful reservation. Every pre-launch failure (`storage_failure` from prepare, a `lane_error`, a `revision_conflict` from a missing persisted proposal, a non-fenced apply error) calls `fail` with `attempt` unchanged, always picking the 60 s rung. Reproduced: eight steps over eight simulated minutes, `state=pending attempt=0 gen=8`. The job never reaches `failed`, so `recalith jobs retry` has nothing to retry and status never shows the failure.

**CTL-4 (medium).** `Worker.tick` catches `RecalithError`, `OSError`, `ValueError`, `sqlite3.Error`. A `KeyError`/`TypeError`/`AttributeError` from the planner, projection refresh, retention, triggers or forget resume propagates out of `run` and `main`; the process dies with exit 1 and the status file keeps `state: idle`. Every hook then relaunches the worker into the same bug: a crash loop driven by the user's own tool calls, invisible in `status`.

**CTL-5 (medium, suspected).** `review.schedule` is called only when an application writes a new candidate revision. Candidates whose verdict was `missing` (the model omitted them), `revise` or `review_capacity` keep `candidate` status and nothing re-queues them. §7.2 says `review_capacity` retries follow the bounded retry policy; here there is no retry.

What held: budget constants, pool split, borrow direction, purpose caps and the 6,000-token headroom match §6.3 exactly; reservation precedes launch and failures stay charged; priority bands are code-assigned from provenance; the proposal is persisted under the fence before application; application, operation rows, `store_revision`, `guidance_epoch` and job completion commit together; revision conflicts requeue one coalesced re-evaluation, never overwrite; admission validates every §7.1 gate and no model-supplied field sets authority, strength, status, installation or priority; review batches are bounded and reasons stripped; the launcher bounds stdout/stderr and kills the process tree; prompts leak nothing and are digest-pinned.

### 4.5 Providers (PROV-2 to PROV-5)

**PROV-2 (medium).** `claude_cli.py` splits the stream-json envelope with `str.splitlines()`, which splits on U+2028, U+2029 and U+0085; Node's `JSON.stringify` leaves them raw (confirmed with the installed node). A reply quoting text with one of them is split into non-JSON fragments, charged, and fails as `envelope_invalid`; the same reply fails the same way on every retry. Fix: split on `\n`.

**PROV-3 (medium).** Any `result` event with `is_error: true` (revoked key, rate limit, overload) raises `ValueError` and becomes `envelope_invalid`. The API route maps 401/403 to `provider_auth_rejected` and withdraws the route; the CLI route keeps retrying a revoked key as a format error, and `recalith status` tells the operator their host version is wrong.

What held: loopback detection refuses `127.0.0.1.nip.io`, `0.0.0.0`, `127.0.0.2`, `127.1`, mapped IPv4; the request shape is exact (model, hard cap, system, messages, optional JSON mode; no tools, stream or store); `output_tokens > cap` withdraws the route; the body cap is 3 × allowance on original bytes and nothing is clipped; thinking blocks are dropped and cannot smuggle text; `Content-Length` shortfall is `provider_response_incomplete`; the route recheck at worker start compares adapter digest, executable digest, host version, key names and invocation; the isolation probe plants sentinels in the same private HOME the CLI uses and validates its detectors with non-isolated control launches.

### 4.6 Retrieval and delivery (RET-1 to RET-8)

**RET-1 (high).** `search.py` filters seeds by status and workspace/task scope, cuts to 96 by preliminary lexical score, and only then evaluates environment scope, path scope and conditions in `decide`. `fast/lookup.py` has the same shape: 64 postings per term by static score (which rewards specificity, so a scoped-but-inapplicable claim outranks an unscoped applicable one), then applicability. Reproduced on a real store: one applicable fact plus 200 copies scoped `os=windows`; a Linux prompt returned an empty packet from both the service and the hook, `omitted_count 0`, no degraded reason. §8.1 step 2 and decision 0013 ("a `false` never occupies a slot") are violated.

**RET-2 (high).** `compile.py` publishes the pre-action view from `SELECT claim_id FROM claim_heads WHERE live AND action_family_digest IS NOT NULL ORDER BY strength, claim_id LIMIT 64`, with no family dimension. The view is query-independent and the hook does not run the lookup for pre-action. Reproduced: one supported lesson for the current action plus 70 corroborated lessons of other families; the service compiler returned `caution`, the hook returned no advice from a healthy `view` with no degraded reason. The pre-action caution is the one safety-relevant delivery, and it disappears at 65 lessons.

**RET-3 (medium).** The deterministic query at 10,000 heads where the query terms are common: `index.docs` issues one SELECT per hit (72 ms for 10,000 hits), `lexical_ids` and `idf` add 45 ms, then 96 Pydantic loads; p50 167 ms, max 217 ms against the p95 ≤ 150 ms gate. The recorded figure (p50 92 to 99 ms) comes from a corpus where 80 % of heads do not match.

**RET-4 (medium).** The live dependency check (`current` recomputation) is skipped for a failure lesson whose action conditions evaluate `unknown`, which is every prompt and session-start query. After an outside edit the lesson is delivered `freshness: current` while a plain fact with the same dependency in the same packet shows `needs_revalidation`. Decision 0020 says the check runs for every live claim with dependencies.

**RET-5 (medium).** Backend detection runs only when `projection_state` is empty. A store created with FTS5 and later opened by a Python build without it keeps `lexical_backend = fts5`; `DELETE FROM lexical_fts` raises on every poll, views and lookup never refresh, `compile_context` raises, and `forget.purge` fails at its `optimize` statement, so forgetting is blocked.

What held: the §8.2 table on both compilers (no candidate, weak, needs-revalidation or unknown-applicability item could be made a caution); FTS MATCH is parameter-bound over an alphanumeric tokenizer and survived every special-character probe; the tokenizer is literally shared code between worker and hook; forgetting removes lookup rows, postings, index rows and views inside the purge transaction; budgets, the one shared 400-token substitution, the 2,000-token restoration keyed by compaction event, and the per-session 4,000 allowance are enforced and validated; receipts are one row per attempt and `uncertain` never downgrades `emitted`; the rendered packet carries no installation id or absolute path and is labeled advisory.

### 4.7 Storage, retention, forgetting, backup (STO-1, STO-3 to STO-6)

**STO-1 (medium).** `retention.sweep` selects the oldest 4,097 age-eligible payloads by commit order, then drops pinned ones. Once the oldest 4,096 age-eligible payloads are all pinned (live claims' chains, an active task's open range), the candidate list is empty, nothing expires, `truncated` stays true, `run` records `swept_at = NULL`, and the full two-closure sweep re-runs on every 1 to 5 s poll with no progress. In preview nothing compacts, so pinned old payloads accumulate for the life of a project. Reproduced with a reduced window.

What held: PRAGMAs per connection (foreign keys, WAL, `synchronous = FULL`, 250 ms busy timeout, `query_only` for read-only opens); no SQL from untrusted strings; schema mismatches refused for writes and restore; `init` never clobbers; forget purge + tombstone + targets + epoch + audit + privacy-operation row commit together; expiry and aging recompute pins inside their transactions; retention windows match §11 with strict day-181 semantics; the pin closure covers every live owner and every piece of owed work the spec names; the purge reaches every table the contract lists; replay suppression is keyed by tombstone target; backups use the online-backup API into a 0700 staging directory, verified exactly as a restore would before one rename publishes them; restore verifies first, applies every newer tombstone in memory, swaps atomically, and recovers from a journal; the integrity chain and capsules are inert in preview. An end-to-end event-only forget and a restore of a pre-forget backup ran clean: no forgotten text in any table, file or the fresh backup.

### 4.8 CLI, integration, bootstrap, health (CLI-1 to CLI-12)

**CLI-1 and CLI-2 (high).** `bootstrap.py install` requires `.recalith/project.toml` (exit 2 otherwise) and stages into `.recalith/runtime/`, which only `init` creates and `.gitignore` excludes. On an empty project it exits 2 with a message naming a "release init entry point" that does not exist in the tree (DATA_CONTRACTS §12 and SYSTEM_SPEC §13.1 promise bootstrap pre-init `init`/`operator-token` forms; `bootstrap.py` has only `install` and `status`). On a clone of an initialized project it dies in `mkdtemp` with a raw `FileNotFoundError`, exit 1. README and OPERATIONS say "bootstrap, then init"; the live harness runs init first from the development venv with `uv run`, which a user with release artifacts cannot do. The wheel installs no `recalith` executable (no `[project.scripts]`); the only launcher is written by `init`. The pre-init refusal texts point to that launcher.

**CLI-3 (high).** `integrations/claude.py` `_git` returns `None` unless `.git` exists at the project root, and `_tracked` treats any nonzero git exit as "not tracked". In a monorepo subdirectory, or when git fails because `_git` overrides `HOME` (so the user's `safe.directory` entries are not read and git reports dubious ownership), a tracked `.claude/settings.local.json` receives 216 deny rules and 11 hook groups and `git status` shows it modified. Reproduced both ways. The ignore state is misreported `unverified`/`not_ignored`.

**CLI-4, CLI-5 (medium).** `remove()` parses the before-copy with `json.loads(bytes or "{}")`; whitespace-only bytes are truthy and raise, so `--remove` exits 5 forever and the integration cannot be uninstalled through the CLI. `atomic_write` renames over a symlinked settings file, destroying a dotfiles layout; `--remove` then reports `byte_identical`.

**CLI-6 (medium).** The hook-context manifest's `worker.route_keys` names the provider key's environment variable; the hook-started worker builds its environment from Claude Code's process environment and forwards exactly those keys to the curator. So the curator works only if the user exported the key in the shell that launched Claude Code. OPERATIONS §4 says to export the key "in that terminal only" for the probes, and nothing tells the user about the session that runs Claude Code; `status` from a terminal without the key reports `selected_auth_missing`.

What held: the guard inspects the original environment first; a marked caller with a real pty and a valid token is refused with exit 6 and a content-free audit; there is no bypass switch or environment override; tokens are 0600 with `O_EXCL|O_NOFOLLOW`, verifiers only in `local.toml`, bad tokens never fall back to the TTY; ~35 command forms matched DATA_CONTRACTS §12's exit codes and no traceback reached stdout; `init` refuses re-init and copied checkouts, completes an interrupted init, handles spaces and non-ASCII; `integrate` preserves unrelated entries and key order and restores byte for byte at a true repository root; `status`/`doctor` write nothing and never report `ready` on a fresh install; `declare`/`correct` go through admission with a scheduled review; `FULL_RELEASE_AVAILABLE` is false and every upgrade form answers 4 except downgrade (6).

### 4.9 Release readiness (REL-1 to REL-12)

**REL-1 (high).** `tools/build_release.py` digests `bootstrap.py`, `requirements.lock` and `uv.lock` but copies none to `--out`; the release workflow uploads only the wheel, sdist, `SHA256SUMS` and manifest. The wheelhouse recipe (`pip download --only-binary :all: --require-hashes`) exists only in `ci.yml`, and its output is specific to the Python minor version and platform that ran it (`pydantic_core-…-cp313-manylinux_2_17_x86_64`). A release download cannot be installed by the documented route.

**REL-2 (medium).** The sdist has no include list: 3.2 MB with 485 docs files (BUILD_PROGRESS 568 KB, 369 evaluation files, measurements), tests, evals, tools, `review/` ("@Jeremy Mccoy"), `.github/`. The license-inventory check covers only the wheel.

**REL-3 (medium).** BUILD_PROGRESS row 18 says the live trial path "has not run, so the gate has no live result" and the acceptance line says "Current acceptance evidence: none", two rows below the record of the tenth gate's pass. The Implementation cell stops at decision 0034. README points newcomers here first.

**REL-5 (medium).** README says curation is billed by the provider but never says that captured prompts, tool output and file excerpts are sent to that provider after scrubbing and retained under its terms. There is no uninstall section. A preview store at schema 12 will be refused by any later engine with a different schema (no migration exists in preview) and `init` refuses to start over while `local.toml` exists; nothing tells early adopters their memory may not survive the next release, and export is a deferred feature.

What held: the tracked tree is free of credentials, user names, emails, hostnames and model identifiers (one scratch path excepted); the wheel contains every prompt, schema, sentinel and migration; `requirements.lock` matches `uv export`; dependency licenses are GPL-compatible and recorded; CI declares `contents: read`, uses no secrets and runs `--locked`; the coverage manifest marks nothing `passed`; the release checklist is internally consistent and honestly `blocked`.

## 5. The evaluation and release process (EVAL-1, EVAL-2, and context)

The tenth live gate passed on 2026-11-04 with the owner's recorded labels: support 21/22, useful recall 7/7, failed-approach recall 2/2, every unlabeled measure met, all five demonstrations shown. The record states its own limits honestly. Reading it against ACCEPTANCE_TESTS raises the following points, which bear on how the preview should be described publicly and on what must happen after the engine changes.

**Reproducibility (EVAL-1).** `versions.tree_clean` is `false` and `commit` is `d8a4bbc`, so the exact code that ran is not pinned. The report records prompt versions and the host version but no digest of the scenario files or the oracle module. `evals/oracles/smoke.py` was edited twice during the gate cycle (decision 0028 items 17 and 30) to accept wordings the candidate produced; the edits are recorded in decisions, so they are not silent, but §1 ("freeze fixtures, gold labels and scoring before comparing") was not followed in the strict sense, and a reader cannot verify which oracle judged the pass.

**Gold quality.** Two of twelve expected retrieval points are unsatisfiable by design and were known to be: L1's session-start point (decision 0013) and R3's `must_not_include "$600 as current"` at the prompt that itself carries the correction, where the design cannot yet know the value changed. The R3 case is not a product bug: the superseding worked (the $600 decision is `superseded`, the $700 decision `active`), and the agent's reply handled the stale context correctly. It is a gold-label defect, and it was written by the same coding agent that wrote the engine.

**What the gate can and cannot show (EVAL-2).** Repeated mistakes were 0/0 in both arms on every scenario; `relative reduction None`. The scenarios leave every answer recoverable from the repository, so a capable agent never fails without memory, and the one metric the project exists to move cannot register on this corpus. What did register: the candidate used more foreground tokens than the baseline on average (+26,783 per scenario, 95 % interval excluding zero) and ~219,000 background tokens per scenario; R3's baseline failed the task once and the candidate did not. A fair public description is: "memory was formed, recalled, revised and forgotten correctly in a scripted smoke run; no benefit over no memory has been measured; the cost is measurable."

**Labels.** Support and recall labels came from two outside-model reviews adopted where they agreed, with the owner deciding the two disagreements. ACCEPTANCE_TESTS §5 allows a model to assist but not to adjudicate alone; with the owner deciding only the disagreements, the agreeing labels were effectively model-adjudicated. The record discloses "fewer than two independent reviewers". This is acceptable for a development smoke gate and should be stated plainly in any public claim.

**Consequence for the fixes.** The owner's rule is to certify a version only when the review supports it. Every fix in Phase 0 and most of Phase 1 and 2 changes engine behavior on the paths the gate exercised (capture, admission, retrieval, scheduling). The gate must be re-run on the fixed engine, by the owner, before the preview is published; the dev10 pass does not transfer.

## 6. Test suite

The full deterministic suite (`uv sync --locked` then `python -m pytest -q -rs -p no:cacheprovider`) was run on Linux, Python 3.13.18, in this container.

Result: **1,399 passed, 18 skipped, 0 failed** in 35 min 37 s (exit 0). The skips are the expected environment ones: the installed Claude Code here is 2.1.318, which is not a capture-certified version, so the eight installed-host smoke tests skip in favour of replayed fixtures; the container runs as root, so three permission-bit tests skip in favour of their injected-EACCES variants; three Windows-only cases (junctions, Job Object breakaway) and one case-insensitive-filesystem case skip; one provisioning test needs a real wheel and wheelhouse.

Two things follow. First, every defect in this report lives in code the suite exercises and passes, which is the point: the suite tests the mechanics the specification names, and these are gaps between the specification's intent and the code (argv scrubbing, proxy handling, partition sizing, lease renewal, applicability-before-caps) that no existing test asserts. Phase 0 to 2 of the plan add a test for each. Second, the installed host being ahead of every certified version (2.1.318 against 2.1.310) is the ordinary state for any user who installs Claude Code today; decision 0019's per-version capture review is a recurring cost the project should plan for (see the fix plan, Phase 5.5).

## 7. What was checked and found sound

Beyond the per-area lists above, the lead checked: no `.recalith/` private file is tracked; `MANIFEST.json`, `review/` and `STARTER_PACKET.md` are historical and labeled so; supersession writes `superseded_by` links (`apply.py:580,619`); the R3 correction scenario superseded the stale decision correctly after the correcting session; `tools/release_checklist.py` and the coverage manifest agree with each other; CI runs schema and wire-validator drift checks on every push.

## 8. Recommendation

Do not publish `0.1.0.dev10`. Fix the critical and high findings (the fix plan's Phases 0 to 3), re-run the live gate on the fixed engine, obtain the Linux certification the checklist already requires, and publish as an explicitly experimental preview whose README states what the evaluation did and did not show. The plan sequences this so the owner's own time is spent only on the live runs and the handful of decisions named there.
