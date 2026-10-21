# Decision 0019: Claude Code integration (preview)

Status: accepted (Task 13, preview slice) · Date: 2026-10-21 · Host observed: Claude Code CLI 2.1.305 on Linux (request-capture mode); fixtures 2.1.301 and 2.1.305; no live route (B1)

## Context

Task 13's preview slice certifies one Claude host and the two required delivery paths, probes both optional paths, installs the operator command protections and probes and reports private-path support (IMPLEMENTATION_PLAN Task 13 and its Cut 1 note; SYSTEM_SPEC §2.2, §5.1–§5.1.2, §6.1, §9.2–§9.3, §13, §13.1, §14, §15; DATA_CONTRACTS §2.3, §11, §12; ACCEPTANCE_TESTS A08, A27–A29, A33, A47, A53, A58, A61, A65, A73). The documents fix the rules. Installation is local by default into the untracked project settings, the location is explicitly ignored, and unrelated entries are preserved. The exact owned entries are recorded, and removal takes back only unchanged owned entries and reports modified ones. Only certified delivery paths are enabled. Readiness depends only on start and prompt delivery, and pre-action and compaction are reported. The nonce protocol runs three positive and three negative controls per path through the real engine, and it never claims to inspect an inaccessible request. The certified deny rules are installed and their coverage is reported exactly. The private-path probe runs in the real permission mode, installs no broad path rules and never loosens controls. A hook-spawned worker must survive the host's end. The session-start warning appears only when memory is materially limited. Shared settings and installed private-path rules are full-only.

The documents leave open:

- what is preview and what is full when a flag is named in both;
- how the installer owns entries across crashes and edits;
- how the hook command finds the project;
- which spellings the deny rules name, and how they are certified;
- how a nonce reaches a packet item through the real engine;
- who writes `.recalith/host.json`, and what a request-capture run may write;
- how a new host version is admitted;
- what the session-start warning reads and how it avoids repeating.

Where a rule was ambiguous the stricter reading was taken.

## Decisions

1. **Preview/full split.**
   - Preview builds `recalith integrate claude` (local only), `integrate claude --remove`, the administrative command deny rules, the hook-context manifest with the registered worker start and only certified delivery paths, the engine-mode certification harness, the private-path *probe*, the host record writer, the session-start notice and the 2.1.305 capture certification.
   - `--shared` (tracked `.claude/settings.json`) and `--autostart` (per-project OS startup entries) pass the guard and answer 4 (decision 0018). Installed private-path rules are full-only and not written.
   - A settings file already tracked by git is refused (exit 6, `policy_refused`), because hooks committed to a repository would be the shared mode by another name.
   - `recalith doctor --probe-host` and `--probe-provider` stay guarded and answer 4 in preview, naming the operator harnesses (`tools/probe_delivery.py --engine-project`, `tools/probe_provider.py`). The certification needs the release's probe harness, a local config and, for its nonce memories, recorded proposals that the engine does not ship.
   - Hosts other than `claude` answer 4 (Codex, generic JSON and MCP are Task 14, full-only).
2. **Files.**
   - `src/recalith/fast/claude.py` is the stdlib host table, envelope and notice.
   - `src/recalith/integrations/{__init__,install,claude}.py` hold the owned-settings installer and the Claude integration with its host record writer.
   - `tools/probe_engine.py` is the Task 0b harness in engine mode; `tools/probe_delivery.py --engine-project` drives it.
   - The fixtures are `tests/fixtures/hosts/claude/2.1.305/`.
   - The tests are `tests/integration/test_claude_adapter.py` (with the builders in `claude_scenarios.py`) and `tests/platform/test_claude_smoke.py`.
   - The plan's "fast/claude.py" holds what the hook needs for Claude beyond Task 3b's capture mapping (`fast/claude_capture.py`, kept). The plan's "versioned Claude fixtures" are the reviewed 2.1.305 capture.
3. **The hook command is project-relative.** Each owned hook group runs `"$CLAUDE_PROJECT_DIR"/.recalith/bin/recalith-hook claude_code --event EVENT` with a 10 s timeout.
   - Claude Code 2.1.305 sets `CLAUDE_PROJECT_DIR` (the session's start directory) and `CLAUDECODE=1` for every hook process (observed). The launcher supplies `--project` itself.
   - A moved checkout keeps the same settings, and its hook refuses on the manifest's root identity until `integrate` re-runs.
   - A clone carries no settings, because the file is untracked.
   - The registered events are SessionStart, UserPromptSubmit, PreToolUse/PostToolUse/PostToolUseFailure (`*`), PreCompact, PostCompact, Stop, SubagentStart, SubagentStop and SessionEnd. `PermissionRequest` is not registered: it has no tool identity or outcome and would add a process to every permission dialog.
   - Windows host execution of this POSIX command is uncertified, because no native Windows host is available. The installer's file effects run natively on every platform in CI.
4. **Ownership** (`integrations/install.py`). The record `.recalith/run/integrations/claude_code.json` is private and ignored. It holds the exact owned hook groups, the owned deny rules, the deny rules that already existed (never owned), the owned ignore line and the settings digests.
   - **Before the first install,** the exact original settings bytes are kept beside the record (private).
   - **Order:** the `installing` record (the intended entries and the ignore plan), the settings, the ignore line, the hook manifest, then the `installed` record. Re-running install or remove after a crash at any step converges, because an intended entry found unchanged is treated as owned and both the previous and the intended sets count.
   - **Removal** takes back unchanged owned entries only. When the rest is semantically the original file, the original bytes are written back (byte for byte). Otherwise the result is written in Claude's own two-space form, keeping later user edits.
   - **Modified owned entries** are left, reported (`modified`, exit 8 `owned_entries_modified`) and the record moves to `reconcile`. A re-install answers 3 while an edited owned entry is still there, so there is never a second copy beside an edited one.
   - **Never loosened:** existing permission rules are not loosened (install only appends) and nothing outside `.claude/settings.local.json`, the project `.gitignore` line and `.recalith/` is written.
   - **Ignored location:** the location is made ignored by an owned `/.claude/settings.local.json` line in the project `.gitignore`, verified with `git check-ignore` when git is available (`ignored: verified|unverified|not_ignored`).
5. **Rebind.** After `workspace rebind` the manifest is stale and health reports `hook_context_relocated` (decision 0018). `integrate claude` re-runs cleanly: the hook groups are unchanged, the absolute-path deny spellings follow the new root (`settings: updated`) and the manifest gets the new identities.
6. **Command deny rules** (`integrations.claude.deny_rules`).
   - **Rules:** `Bash(SPELLING FORM:*)` for 18 administrative forms × 12 spellings, 216 rules in all.
   - **Forms:** init, declare, correct, undo, forget, integrate, backup, restore, export, import, upgrade, workspace, project, worker, `jobs retry`, operator-token, `doctor --probe-host`, `doctor --probe-provider`.
   - **Spellings:** the launcher as `.recalith/bin/recalith`, `./.recalith/bin/recalith` and by its absolute path; `recalith`; `python`/`python3` `-m recalith` with and without `-I`; `-m recalith.cli.main`; and the pinned runtime interpreter, relative and absolute. Windows adds the `.cmd` spellings.
   - **Coverage is reported with `complete: false` and four gaps:**
     - global options before the form (`--json`, `--project`, `--operator-token-file`);
     - shell wrappers (`sh -c`, `bash SCRIPT`, `eval`, `xargs`, scripts);
     - other interpreters, copies, links and quoted absolute paths;
     - previews over-covered: `undo`/`forget` previews are denied with their apply forms.
   - **Backstop:** the CLI marker guard refuses every administrative form from a host-marked process with or without a rule.
   - **Observed on 2.1.305** (request-capture, Bash allowed for the whole session so only the rules could stop a command): all 29 covered commands were denied by the host — every spelling with `declare`, and every form through the launcher. Commands prefixed with `cd . &&`, `true;` or `env A=1` were also denied, because the host splits compound commands and strips assignments. The three gap spellings executed, and the guard refused each one on the actual tool subprocess (exit 6, content-free audit captured). No administrative effect and no store change followed. Tool subprocesses carry both `CLAUDECODE` and `CLAUDE_CODE_CHILD_SESSION`.
7. **Private paths (A65).** The probe runs in the target project's configured permission mode (`permissions.defaultMode`, local over shared, default `default`), with Bash, Read, Grep, Write and Edit allowed, in two disposable fixtures: one without and one with probe-only rules `Read/Edit/Write(./.recalith/**)`. Nothing is installed in the target.
   - **Without rules:** every attempt reached `.recalith/` (Read, Grep, Write, `cat`, `head`, `cp`, `sh -c 'cat …'`, `python3 -c open(…)`).
   - **With rules:** the file tools and the host-recognized read commands (`cat`, `head`, `cp`) were blocked, but `sh -c 'cat …'` and `python3 -c open(…)` still read the file. Hooks kept capturing.
   - The verdict is **`probed_limited`** with `os_level_isolation: false` and `installed_rules: unavailable_in_preview`, reported, never gating (decision 0018).
8. **Delivery certification through the real engine** (`tools/probe_engine.py`).
   - **Each trial:** every trial is a fresh disposable fixture installation (real `init`, the hooks and rules installed by the real `integrate`, one shared provisioned runtime linked in), with a private `HOME`, `--setting-sources local` and `--include-hook-events`. A controlled trial manifest enables only the trial's path.
   - **The nonce memory:**
     - pre-action: a failure lesson on the fixture tool's exact action (`ls /nonexistent-recalith-fixture-dir`, whose fixed output never contains a nonce);
     - prompt: a fact matched lexically by the canary prompt;
     - session start and compaction restoration: an open intent question of two conflicting declarations, one holding the nonce. A fresh session's start, and a restoration with nothing delivered before it, carry only open questions until a task binding exists (decision 0013).
   - **Seeding:** the nonce memory is admitted through the real extraction and review path with recorded proposals over real captured fixture events (labeled synthetic). The nonce lives in exactly one packet item and nowhere the agent can read. Negatives build the same shape with the nonce withheld.
   - **Judging:** live trials are judged by `probe_delivery.evaluate_trial` (first eligible assistant text, contamination, no stdout-only pass). Request-capture trials record whether the nonce reached the loopback request after the injection point, plus the engine's own accounting: an emitted delivery row from the ingested receipt, within the packet cap.
   - **Observed on 2.1.305, request capture:** all four paths are `request_visible` (3/3 positives emitted and in the request, 3/3 clean negatives). This is never an echo pass. Live is `not_run` (`no_auth_route_configured`, B1).
9. **The host record** (`integrations.claude.write_host_record`). Only the certification harness writes `.recalith/host.json`, for the target installation and its integrated host version.
   - **Modes:** `mode: live` only when every path was observed live. Then `healthy` → `certified`, `degraded` → `failed`, `unavailable` → `unavailable`. Any request-capture or incomplete run is `mode: request_capture` with every delivery path `unavailable`, which health treats as uncertified (`delivery_request_capture_only`).
   - **Command rules:** `command_rules: installed` only when the host probe saw every covered spelling denied *and* the target's owned rules are present. These, and `private_paths`, are host-enforcement observations made with scripted tool calls against the real host. They do not depend on model visibility, so a request-capture record carries them, and health's operator guard can be healthy under B1.
   - **Enabled paths:** the harness then re-runs `integrate`, which enables exactly the paths a live record certifies for this installation and exact host version, and none from a request-capture record.
   - **Integration checks in health:** health also checks the integration itself (read-only). An owned hook group edited or removed makes capture degraded and the dependent delivery paths unavailable (`host_hooks_modified`). An edited owned deny rule degrades the guard (`command_deny_rules_modified`). Rules installed but not observed are `command_deny_rules_uncertified`. A record observed on another host version is `host_version_changed`.
10. **Worker survival (A45, §6.1).** A worker started by the registered hook start in a real host session (`--spawned-by hook`, a new POSIX session, independence `detached`) stayed alive and ingested a later observation after each of three endings, observed on Linux: the host's normal end with SessionEnd, `SIGKILL` of the host's whole process group, and a terminal hangup (the pty master closed, then `SIGHUP`). macOS and Windows host termination are not observed here (no host). The decision 0006 platform tests still cover them with simulated hosts.
11. **The 2.1.305 review.** The fixtures were captured with `tools/capture_claude_fixtures.py` in request-capture mode (loopback scripted endpoint, placeholder key; this session's credentials and proxy never used).
   - **Compared field by field with 2.1.301:** the same hook events per scenario in the same order, the same payload field sets per event, and the same value formats (Bash prefixes, truncation sizes, `persistedOutputSize`). The only value differences are pytest timings and identifiers.
   - **Transcripts:** they add only records of already known metadata types (`attachment`, `atis-latch`, `last-prompt`, `api-request-shape`).
   - **Mapping:** the real adapter maps both versions identically (`test_reviewed_2_1_305_fixtures_map_like_2_1_301`).
   - **Result:** 2.1.305 joins `claude_capture.CERTIFIED_VERSIONS`. 2.1.301 stays. The transcript parser keeps its `@2.1.301` name because its format is unchanged. Any other version stays conservative: capture only, no delivery, no notice.
   - **Pin:** the plan-named Task 3b tests still pin 2.1.301. Fixtures are never re-pinned to an uncaptured or unreviewed version.
12. **The session-start notice (§14)** is `fast.claude.session_notice`.
   - **Inputs:** stdlib only, from small local files: the manifest as loaded, the worker's own fresh status record, the presence of the provider record, the maintenance marker, and bounded listings of the spool's gap records and ready segments. There is no SQLite, Pydantic, health layer, model or launch.
   - **Codes:** `inference_unavailable` (the running worker's fresh report, else a missing route record), `delivery_not_certified` (start or prompt not enabled), `delivery_paused` (privacy maintenance), `capture_gaps` (gap records newer than the last notice) and `ingestion_delayed` (a ready segment older than 10 minutes).
   - **When:** only on a real session start (`startup`/`resume`/`clear`, never compaction or a prompt), on a certified host version, with the manifest's consent (context_schema 4 `notices.session_start`, set by `integrate`), and with at least 40 ms of the hook deadline left.
   - **Form:** one sentence of at most 512 bytes in `systemMessage`, merged into the delivery envelope when one is emitted. 2.1.305 shows it to the user and keeps it out of the model request (observed).
   - **Once:** the private marker `run/session-notice.json` records the set of codes before anything is printed. The same set is never shown again; a resolved set clears the marker, so a recurrence warns again. If the marker cannot be written, the notice is suppressed.
13. **Hook failure never denies a tool.** The installed hook exits 0 with empty stdout or only context and a notice for every operational failure: corrupt manifest, unreadable store, blocked spool, missing runtime, malformed or oversized payload. A broken interpreter exits nonzero but never 2, which is the host's only blocking code. On the real host a Bash tool ran in each of the four failure fixtures, with hook exit codes 0.
14. **Kill/restart family** (`failpoints.INTEGRATION`). The family covers `integrate.after_record`, `after_settings`, `after_ignore` and `after_manifest`, and on removal `integrate.remove_after_settings`, `remove_after_manifest` and `remove_after_ignore`. Each rep varies the settings form (host format, compact, tabs, absent) and the presence of a `.gitignore`. A killed install restarted by the same command yields exactly one copy of every owned entry. A killed removal, or a crash followed directly by removal, restores the pre-install bytes of the settings and the `.gitignore` and leaves no record or manifest.
15. **Latency.** Measured through the installed command (`tools/measure_delivery_latency.py --installed-launcher`: `sh -c` as the host runs it, the launcher, the provisioned runtime and the fast entry with delivery, 500 trials per regime, 10,000-claim corpus). Warm pre-action and prompt delivery measured p95 94–99 ms and p99 107–109 ms. Stale views with fallback rows measured p95 97 ms and p99 108 ms. Every eligible trial emitted and none degraded, on the 4-vCPU Linux container (`docs/measurements/hook-delivery-latency-installed.json`). The ACCEPTANCE_TESTS §7 gates (p95 ≤ 300 ms, p99 ≤ 750 ms) hold here; native macOS and Windows were not measured, because no host is available there.

## Consequences

**Wired now:**

- the guarded `integrate claude` and `--remove` through the service;
- the context_schema 4 manifest, the notice, 2.1.305 capture certification, and health's integration checks;
- the engine-mode harness with its host record;
- the deny-rule, private-path, marker, hook-failure and worker-survival probes on the real host.

**Remaining:**

- **B1:** live delivery certification (model echo) on all four paths, and therefore a `live` host record and enabled delivery paths in a real project. The operator commands are in BUILD_PROGRESS (B1).
- **Not observed:** native Windows and macOS host execution and their host-termination behavior.
- **Full release:** `--shared`, `--autostart`, installed private-path rules and Codex.
- **Task 18:** the preview gate.

No certification follows from request-capture evidence.
