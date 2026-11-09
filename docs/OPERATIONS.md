# Operating a Recalith installation (Claude autonomous preview)

Engine `0.1.0.dev14` · release profile `claude_preview` · status: **live smoke gate passed on native Windows (2026-11-04, on `0.1.0.dev10`; to be re-run on the fixed engine, [audit](audits/2026-11-06-memory-system-audit.md))**; not released · platforms: Windows certified, Linux pending, macOS not certified ([decision 0041](decisions/0041-preview-platforms-windows-and-linux.md)) · license: GPL-3.0-only ([decision 0042](decisions/0042-gpl-3-license.md)).

This guide is for the person who owns one project's installation. Every project has its own complete installation under `.recalith/` (engine pin, configuration, worker, store, evidence, jobs, budgets). Nothing is shared between projects, and there is no global registry or daemon. The normative behavior is in [SYSTEM_SPEC](SYSTEM_SPEC.md) and [DATA_CONTRACTS](DATA_CONTRACTS.md); this guide tells you which parts run by themselves, which run in a fallback, and which do not exist in this build.

`recalith status` is the source of truth for your installation. It names the release profile, every required and optional capability with its state and reason, and every deferred full-release feature. It exits 0 only when the installation is `autonomous_ready`, and 8 otherwise.

## 1. Automatic operation (no human action once set up)

When `recalith status` reports `readiness: ready`, all of the following happen without anyone asking:

| What | How | Where it is specified |
|---|---|---|
| Capture | Claude Code hooks installed by `recalith integrate claude` spool every captured event durably before acknowledging it; the hook never waits for a model and never writes SQLite | SYSTEM_SPEC §5, decision 0005 |
| Worker start | The first hook of a session starts the installation's own worker through the registered internal start (never the operator CLI); the worker polls every 1 s when active and 5 s when idle | decision 0006 |
| Working state and episodes | Typed reduction binds events to tasks, keeps pending actions and results, and settles episodes at checkpoints | decision 0008 |
| Long-term knowledge | Extraction proposals, adversarial review and deterministic admission through the certified inference route, within the daily budgets | decisions 0011, 0012 |
| Revision | Changed dependencies, later successes and conflicting evidence queue revalidation; old guidance is withdrawn at the delivery fence | decisions 0012, 0015 |
| Delivery | Session-start and prompt context (required), pre-action cautions and compaction restoration (optional, certified separately), each inside its token budget | SYSTEM_SPEC §8.2 |
| Retention | Unpinned event payloads expire at day 181; live memories pin their evidence; closed task history ages after 90 days and episodes 180 days after their task closed, unless a live memory cites them | SYSTEM_SPEC §11, decisions 0016, 0020 |
| Backups | Verified backups with the tombstone ledger; backups older than 30 days are deleted | decision 0016 |
| Recovery | The worker finishes interrupted backups, restores and forget phases before delivery resumes | decisions 0016, 0017 |

No routine memory operation needs a person: nobody approves a queue of memories, and the working agent is never told to maintain memory.

## 2. Fallback operation (degraded, visible, still safe)

`readiness: degraded` means at least one required capability is not healthy. The installation keeps doing what it safely can and says so in `recalith status` and, once per distinct set of limitations, in a short session-start notice.

| Condition | What still works | What stops | Status reason |
|---|---|---|---|
| No certified inference route (B1 today) | Capture, typed task state, episodes, deterministic retrieval of existing knowledge, forgetting, backup, restore | New long-term knowledge: model jobs wait visibly | `provider_not_configured`, `request_capture_only`, `route_uncertified`, `certification_failed_<check>` |
| A certified API route withdrawn by a reply (decision 0023) | As above | Model calls until the route is recertified (or the worker restarts after an auth fix) | `model_mismatch`, `output_cap_exceeded`, `provider_auth_rejected`, `provider_not_found`, `provider_redirect_refused`, `isolation_tools_exposed`; an adapter changed by an engine update is `adapter_changed` |
| A certified API route's last call failed transiently | Everything; the failed call is charged and retried on the normal backoff | Nothing beyond the backoff | `endpoint_unreachable`, `tls_verification_failed`, `provider_rate_limited`, `provider_server_error`, `provider_overloaded`, `provider_timeout` (degraded) |
| Start/prompt delivery not certified for the installed Claude Code version | Capture and learning | Automatic delivery into sessions (the hook stays silent) | `delivery_not_certified`, `delivery_request_capture_only`, `host_version_changed` |
| Budget pool exhausted for the UTC day | Capture, deterministic work, delivery of existing knowledge | New model calls until the next UTC day; protected review keeps its own reserve | `budget_exhausted:<pool>.<dimension>` |
| Privacy maintenance (forget or restore) in progress | Capture | Delivery and model launches until cleanup finished | `maintenance_in_progress` |
| Pre-action or compaction path unavailable | Prompt delivery substitutes eligible cautions within one shared 400-token allowance | Pre-action injection | reported only; not a readiness loss |
| Out-of-band edits (a pull, another editor) | The hook's bounded live dependency check labels affected knowledge `needs_revalidation` and never cautions on it | Cautions that depend on the changed file | `dependency_changed` |
| Unknown or uncertified host version | Conservative capture with explicit coverage gaps | Delivery and the notice | `uncertified_host_version` |
| The worker stopped on an unexpected error (decision 0044) | Capture: hooks keep spooling, and the next hook starts a new worker | Ingestion and curation until that restart | `worker_crashed` under recovery; a failing poll step that the worker survives shows as `worker_error` with `poll_error:<step>:<type>` in its status |

A fallback is never promoted to "ready", and an unavailable capability never counts as a passed check.

**Known limit (not a health condition): prompt context at scale.** Since decision 0021 the hook reaches prompt-relevant facts beyond the worker's views through a bounded lexical lookup that the worker maintains. Each prompt can add up to 16 extra candidates, found through the 8 rarest of its first 32 terms. The same filters and the final fence apply as for every other candidate. At 10,000 claim heads this delivers the prompt-specific fact on every warm and cold trial measured (§7; the Task 11 follow-up checkpoint in BUILD_PROGRESS has the per-platform figures). Three limits remain:
- **Rebuild lag.** After a large import, a forget, a restore, or a change of environment or policy, the worker rebuilds the lookup in batches of 512 claims (about a quarter of a millisecond per claim). Until it finishes, claims it has not reached are found by `recalith search` and `recalith context` (full lexical search), not by the hook.
- **Common words.** A claim whose only matching words are very common in the store can still fall outside the hook's bounded read.
- **Pre-action cautions.** At corpus scale these still come from the views' 64-claim action-family slice.

## 3. Missing capabilities (not in this build)

Preview reports these 16 full-release features `unavailable` with reason `deferred_full_release`; their commands return `capability_unavailable` (exit 4), never empty success:

`codex_capture`, `codex_delivery`, `generic_json`, `mcp`, `capsules`, `export`, `import`, `breadcrumbs_import`, `workspace_attach`, `project_fork`, `session_worker`, `shared_integration`, `ipc_wake`, `revision_chain`, `private_path_install`, `side_by_side_upgrade`.

Also not available in preview: in-place upgrade and the preview-to-full transition, per-project OS startup entries (the hook start is preview's startup route), `integrate claude --shared` and `--autostart`, and the `doctor --probe` forms (the operator harnesses `tools/probe_provider.py` and `tools/probe_delivery.py --engine-project` run the probes instead).

The revision chain is built for the full profile (decision 0024) but a full store cannot be initialized yet: `init --release-profile full` stays refused until the full release. In a full store, `recalith doctor` verifies the chain entries since its private checkpoint and the rows they touched, and `recalith doctor --full-integrity` the whole chain and every current row (O(store), progress on stderr); findings exit 8 with `revision_chain_findings`. It detects out-of-band edits, not a same-user rewrite of the store and chain together.

Exact evidence capsules are also built for the full profile only (decision 0025), with the same caveat. In a full store the worker's retention step replaces a pinned payload past the 30-day window with an exact capsule when every live reference can be kept exactly, and keeps the payload pinned otherwise; health reports `capsules` with `capsule_count`, `capsule_bytes`, `deferred_compaction_count` and the last compaction's deferral reasons, and `recalith show cap_…` prints a capsule. Preview never compacts.

The preview-to-full transition is built too (decision 0026) and is likewise not available yet: `recalith upgrade` answers `capability_unavailable` (exit 4) until the full release, and `upgrade --release-profile claude_preview` on a full store is always refused (exit 6). When it is available it will run in place under exclusive maintenance (the worker is stopped and restarts on the next hook), take a verified backup first, and either activate in one step or leave the preview store exactly as it was. `recalith status` reports an interrupted transition under `recovery` (`upgrade_recovery_pending`, the journal phase) and the last result; the worker's next start finishes or rolls it back. Explicit retention overrides go in `project.toml` as a `[retention]` table of whole days (for example `unpinned_event_payload = 120`); they survive the transition, while profile defaults follow the store's profile.

## 4. One-time setup (operator, from an ordinary terminal)

Administrative commands are refused inside an agent's process tree, even with a terminal and a token (exit 6). Run everything below from an ordinary OS terminal you opened yourself, outside Claude Code (not an IDE terminal that inherits its marker). Each step is complete as written; `RELEASE` is the release directory (the wheel, `bootstrap.py`, `requirements.lock`, `SHA256SUMS`, one `wheelhouse-<platform>-<python tag>/` per platform and Python version; the checkout's `tools/build_release.py` and `tools/build_wheelhouse.py` build it) and `PROJECT` is the project you are installing into. Python 3.13 is shown; use the wheelhouse whose tag matches your interpreter (`cp312`, `cp313`, `cp314`).

### Linux

```bash
RELEASE=/path/to/recalith-release; PROJECT=/path/to/your/project; VERSION=0.1.0.dev14
WHEEL="$RELEASE/recalith-$VERSION-py3-none-any.whl"
DIGEST=$(grep " recalith-$VERSION-py3-none-any.whl$" "$RELEASE/SHA256SUMS" | cut -d' ' -f1)
HOUSE="$RELEASE/wheelhouse-linux-x86_64-cp313"

# 1. Provision the pinned runtime and initialize the project (one command; exit 0).
python3 "$RELEASE/bootstrap.py" init --project "$PROJECT" --profile coding --release-profile claude_preview \
    --wheel "$WHEEL" --expected-digest "$DIGEST" --wheelhouse "$HOUSE"
cd "$PROJECT"
.recalith/bin/recalith status      # exit 8: degraded, with the next command named

# 2. Certify the curator route (live; billed). Pick a backend below, copy its example, fill it in,
#    export the key in THIS shell, then (from a checkout of the repository, with its own tooling):
export ANTHROPIC_API_KEY=...        # the key name your config selects
uv run python tools/probe_provider.py --config probe-private/local-config.json --backend anthropic_messages --route-out "$PROJECT" --output docs/host-compatibility.json
uv run python tools/check_provider_runtime.py --config probe-private/local-config.json --backend anthropic_messages --project "$PROJECT" --output docs/host-compatibility.json

# 3. Integrate Claude Code (hooks, deny rules, the hook manifest) and certify its delivery paths (live).
.recalith/bin/recalith integrate claude
uv run python tools/probe_delivery.py --config probe-private/local-config.json --engine-project "$PROJECT" --output docs/host-compatibility.json

# 4. Ready?
.recalith/bin/recalith status      # exit 0 when every required capability is healthy
```

### Native Windows (PowerShell)

```powershell
$Release = "C:\Code\recalith-release"; $Project = "C:\Code\project"; $Version = "0.1.0.dev14"
$Wheel = "$Release\recalith-$Version-py3-none-any.whl"
$Digest = (Select-String -Path "$Release\SHA256SUMS" -Pattern " recalith-$Version-py3-none-any.whl$").Line.Split(' ')[0]
$House = "$Release\wheelhouse-win-amd64-cp313"

# 1. Provision and initialize (exit 0).
py -3.13 "$Release\bootstrap.py" init --project $Project --profile coding --release-profile claude_preview `
    --wheel $Wheel --expected-digest $Digest --wheelhouse $House
cd $Project
.recalith\bin\recalith.cmd status    # exit 8

# 2. Certify the route (export the key in THIS window; from the repository checkout, with its interpreter):
$env:ANTHROPIC_API_KEY = "..."
.\.venv\Scripts\python.exe tools\probe_provider.py --config probe-private\local-config.json --backend anthropic_messages --route-out $Project --output docs\host-compatibility.json
.\.venv\Scripts\python.exe tools\check_provider_runtime.py --config probe-private\local-config.json --backend anthropic_messages --project $Project --output docs\host-compatibility.json

# 3. Integrate and certify delivery.
.recalith\bin\recalith.cmd integrate claude
.\.venv\Scripts\python.exe tools\probe_delivery.py --config probe-private\local-config.json --engine-project $Project --output docs\host-compatibility.json

# 4. Ready?
.recalith\bin\recalith.cmd status    # exit 0
```

The probe configuration file is documented in [docs/probes/LOCAL_CONFIG.md](probes/LOCAL_CONFIG.md); `probe-private/` is git-ignored and holds names, paths and switches, never key values. The live gate (§6) is a separate, optional step.

**Where the curator key must live.** The hook-started worker inherits the environment of the process that launches Claude Code and forwards only the route's key names to the curator (`integrate claude` prints them under `worker.route_keys` and says so under `worker.key_location`). Export the key's variable in the shell you start Claude Code from, or in that shell's profile, not only in the terminal that ran the probes. `recalith status` judges the running worker's own route report when a worker runs (`source: worker`) and this terminal's environment otherwise (`source: configuration`), and its human form says which one lacks the key.

**Automation.** A token stands in for the terminal: `python bootstrap.py operator-token create --project PROJECT --output FILE --wheel … --expected-digest … --wheelhouse …` at a terminal (it is never minted noninteractively), then `python bootstrap.py init … --operator-token-file FILE` from the automation. A clone of an initialized project keeps its tracked profiles: `init` refuses a differing `--profile` or `--release-profile` instead of ignoring it.

**Without a release directory.** From a checkout: `uv run python tools/build_release.py --out dist-release` builds the wheel and copies `bootstrap.py` and `requirements.lock` beside it; `uv run --with pip python tools/build_wheelhouse.py --out dist-release` adds the wheelhouse for the current platform and Python (run it on each platform you need); `dist-release/` is then a release directory.

### Choosing the curator backend (decision 0023)

The background curator needs one explicitly configured route. Pick what you have; nothing ever falls back to another provider, model, key or endpoint.

| You have | `backend` | Start from |
|---|---|---|
| The Claude Code CLI with an API key (or `apiKeyHelper`, or cloud credentials) | `claude_cli` | `tools/probe_config.example.json` |
| An Anthropic API key | `anthropic_messages` | `tools/probe_config.anthropic_messages.example.json` |
| An API key for an OpenAI-compatible Chat Completions provider (OpenAI, Azure OpenAI, OpenRouter, Groq, Together, Gemini's OpenAI-compatible endpoint, …) | `openai_compatible` | `tools/probe_config.openai_compatible.example.json` |
| A local OpenAI-compatible server (Ollama, LM Studio, vLLM) | `openai_compatible` with a loopback `http` URL and `auth_route: none` | `tools/probe_config.local_server.example.json` |

Copy the example to `probe-private/local-config.json`, set the explicit model identifier (no model name is built in), the endpoint URL, the key's environment-variable *name*, and the attestation; export the key in that terminal only; then run the probe (live certification) and the runtime check with `--backend`, and `recalith status`. Notes:

- **Anthropic key funded by a Max or Team plan's included API credits.** It is an ordinary API key: use `anthropic_messages` with `x-api-key`. Check that plan's terms for unattended background use before attesting `checked_eligible`. A subscription login (OAuth) is not this route; subscription harnesses are separate future routes (decision 0023 item 11).
- **A hard spending stop.** Recalith reserves its own daily invocation and token budgets before every call, but the provider bills what it serves. If you want the provider to stop rather than overspend, turn off auto-reload or overage billing in the provider's console and set a spend limit there; a call the provider refuses for credit then fails visibly with the status it returns (for example `provider_request_rejected` or `provider_rate_limited`), is charged against the local budget and backs off.
- **OpenAI-compatible providers.** Use the provider's full `…/chat/completions` URL (Azure: the deployment or v1 URL with its `api-version` query and `auth_header: api-key`). If the provider reports a different model identifier than the one you send (an alias or a deployment name), set `expected_resolved_model` to the identifier it reports; otherwise the call fails with `model_mismatch`. If the server rejects `max_completion_tokens` or JSON mode, use `output_cap_field: max_tokens` or `json_mode: none`; the live probe shows which one the server enforces. A provider that cannot enforce a hard output cap cannot be certified.
- **Local server.** Use `http://127.0.0.1:PORT/v1/chat/completions`, `auth_route: none`, `auth_header: none` and the attestation `not_applicable_local`. The live probe still checks the output cap, the JSON body and the reported model; usage the server does not report is charged at Recalith's own estimates.
- **Proxies and corporate CA bundles** reach the curator only when named in `network_env_keys` (`HTTPS_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`, `SSL_CERT_DIR`). TLS verification cannot be turned off.

Re-run step 3 after any Claude Code upgrade: a new host version needs a fixture capture and review before it is certified (decision 0019), and delivery stays off for an uncertified version.

### Native Windows (decision 0027)

- **Where to run.** Claude Code on native Windows runs hook commands and its Bash tool through Git Bash. Run the operator commands from an ordinary PowerShell or Windows Terminal window that you opened yourself (not one an IDE or Claude Code started), in the same Windows account; check `Get-ChildItem Env: | Where-Object Name -like '*CLAUDE*'` prints nothing. Call the launcher as `.recalith\bin\recalith.cmd` (the session-start notice names it so on Windows). `integrate claude` installs 475 deny rules on Windows (228 on POSIX): 19 administrative forms in every launcher and module spelling.
- **What integrate installs.** On Windows the hook command is `"$CLAUDE_PROJECT_DIR"/.recalith/bin/recalith-hook.cmd claude_code --event E`; the POSIX launcher cannot reach a Windows venv. An installation integrated on Windows before decision 0027 has POSIX hook commands that do nothing: run `integrate claude` again.
- **Path length.** Without Windows long-path support (`LongPathsEnabled` 0) every path stops at 260 characters. Claude Code's transcript path repeats the workspace path, so keep project and output directories short (for example `C:\Code\project`, and `--out C:\Code\rl-gate` for the live gate).
- **Worker independence.** The hook-started worker survives the session and a kill of the host's process tree, but CPython's venv launcher keeps it inside a Job Object, so `recalith status` reports `recovery` degraded (`worker_independence_degraded`) while a worker runs. This is an open limit, not a failed check.

## 5. Operator actions you may take (never routine)

| Need | Command |
|---|---|
| Correct a memory | `recalith correct ID --expected-revision N --statement TEXT` (reviewed replacement; old guidance suppressed at once) |
| Declare a decision or preference | `recalith declare KIND --statement TEXT --scope FILE` (always reviewed) |
| Forget | `recalith forget --selector FILE --preview`, then `--apply --preview-digest D` |
| Back up / restore | `recalith backup --output PATH`; `recalith restore PATH --expected-digest D` (newer tombstones applied before anything is served) |
| Undo an automatic change | `recalith undo OP --preview`, then `--apply --preview-digest D` |
| Inspect | `recalith status`, `doctor`, `why`, `show`, `search`, `tasks`, `episodes`, `claims`, `jobs` (read-only, any caller) |

Logical forgetting does not reach explicit exports, operator or third-party copies of backups, remote provider retention, filesystem forensics, or paraphrases; every forget and restore reports these limits.

## 6. Evaluation status

The preview's live smoke gate (ACCEPTANCE_TESTS §6.1) **passed** on its tenth run (2026-11-04, `0.1.0.dev10`). The preview release (§8) is still **blocked**: Linux is not observed live, and release signing and the go-ahead to publish are open ([checklist](release/claude_preview_checklist.json)). For the preview, macOS is not certified ([decision 0041](decisions/0041-preview-platforms-windows-and-linux.md)). B1 has cleared on native Windows: the pilot project holds a live-certified route and host record (Claude Code 2.1.309). The first live gate ran on 2026-10-23 to 2026-10-26 and **failed**: the host updated itself to 2.1.310 partway through, the laptop slept over a weekend, and the curator's reasoning filled `update_task`'s output allowance, so most waits never settled ([the run's record](evaluations/preview-live-2026-10-26/report.md); the checkpoint in [BUILD_PROGRESS](BUILD_PROGRESS.md)). The second (2026-10-28 to 2026-10-29) also **failed** ([record](evaluations/preview-live-2026-10-29/report.md)). The third (2026-10-31, engine `0.1.0.dev4`) ran complete and clean but **failed**: its live support and recall await reviewer labels, and the drafted labels put useful recall at 5/8 and failed-approach recall at 1/3, both under target ([record](evaluations/preview-live-2026-10-31/report.md); decision 0035). The fourth (2026-11-01, `0.1.0.dev5`) **failed** on R4's conflict label ([record](evaluations/preview-live-2026-11-01/report.md); decision 0036). The fifth (2026-11-01, `0.1.0.dev6`) ran complete and clean and met every measure that needs no labels, but **failed** on failed-approach recall by the owner's call on one label ([record](evaluations/preview-live-2026-11-01-gate5/report.md); decision 0037; the fifth-gate checkpoint in [BUILD_PROGRESS](BUILD_PROGRESS.md)). The sixth (2026-11-02, `0.1.0.dev7`) **failed** on useful recall and the forgetting demonstration: two user declarations were lost to code's strict checks ([record](evaluations/preview-live-2026-11-02/report.md); decision 0038). The seventh (2026-11-03, `0.1.0.dev8`) **failed** on the forgetting demonstration: the session after the forget was delivered text holding the forgotten limit, from a source the record did not keep. As drafted, its labels meet every labeled measure ([record](evaluations/preview-live-2026-11-03/report.md); decisions 0039 and 0028 item 29). The eighth (2026-11-03, `0.1.0.dev9`) showed all five demonstrations, and as drafted its labels meet every labeled measure. It **failed** only on incorrect confident guidance, through an R3 oracle false negative ([record](evaluations/preview-live-2026-11-03-gate8/report.md); decision 0028 item 30). The ninth (2026-11-04, `0.1.0.dev9`) met every other measure and showed all five demonstrations, and **failed** on supported precision (22/24) with the owner's recorded labels: two claims overstated a detail ([record](evaluations/preview-live-2026-11-04/report.md); decision 0028 item 31). The tenth (2026-11-04, `0.1.0.dev10`) **passed** with the owner's recorded labels: support 21/22, useful recall 7/7 and failed-approach recall 2/2, with every other measure and all five demonstrations met ([record](evaluations/preview-live-2026-11-04-gate10/report.md)). It is one run, with one trial per arm, thin margins and no superiority claim. Before that, the evaluation harness (`evals/run.py`), the workload days, the latency gate (`tools/measure_release_latency.py`) and the release checklist ([docs/release/claude_preview_checklist.json](release/claude_preview_checklist.json)) have run only in recorded/scripted mode, which is mechanics evidence and never a live pass. See the Task 18 checkpoints in [BUILD_PROGRESS](BUILD_PROGRESS.md).

### Running the live gate (decision 0028)

Run it from an ordinary terminal that you opened yourself, with the selected key exported there. The `--source-project` is the project whose route and host record are certified (its `provider.json` and `host.json`). The run provisions each candidate installation with your own tools: init with the pre-init token, the release bootstrap with the certified project's wheel, a live route certification of its own, and `integrate claude`. Each installation's host record is then bound from the certified project's live record. The results directory holds every report the run writes; keep it short on Windows.

```powershell
& .venv\Scripts\python.exe evals\run.py gate --mode live `
    --config probe-private\local-config.json --operator-token-file C:\path\to\eval-token.json `
    --source-project C:\Code\rl-pilot12 --wheel dist\recalith-0.1.0.dev10-py3-none-any.whl --wheelhouse wheelhouse `
    --out C:\Code\rl-gate --slots 6
```

`--slots` is how many smoke trials, and then workload days, run at once, each in its own installation. The time is mostly waiting for curation, not CPU. The third gate took 102 minutes at 2 slots: 80 for the smoke, 16 for the three days run one after another, and 6 for the demonstrations. The fourth took 45 minutes at 6 slots, with the days run together, the fifth 48, the sixth 43, the seventh 48, the eighth 47, the ninth 43 and the tenth 48; a fresh pilot before it adds about 9 minutes, mostly the delivery probe. More slots raise the tokens per minute the key must serve. If the report's curator call outcomes show rate-limit errors or a wait stalls, use fewer slots.

Exit 0 means the gate passed (`passed_smoke`). Exit 8 means it ran and failed: the report lists every reason, including anything that did not run. Exit 4 means a required input or certification was missing and nothing ran.

Before you start it:

- **Keep the host at the certified version for the whole run.** The trial sessions already run with `DISABLE_AUTOUPDATER=1` (the delivery section's `nonsecret_env`), but your own interactive Claude Code sessions update the shared installation. Turn their background updates off too, from before the certification until the gate ends:
  - **Off:** add `"env": { "DISABLE_AUTOUPDATER": "1" }` to `%USERPROFILE%\.claude\settings.json`, next to the other top-level keys. Running sessions pick up the saved change. `claude doctor` then reports auto-updates as disabled. Manual `claude update` still works, so don't run it either.
  - **On again:** delete the `DISABLE_AUTOUPDATER` entry, and the `env` block if it is then empty. The next session start updates as usual. A new version then needs its own capture review and live certification before another gate (§4 step 3).
  - The harness checks `claude --version` against the certified version before every session. On a change it schedules no further trial and writes the report of what ran (exit 8).
- **Keep the machine awake and on power.** The run asks Windows not to idle-sleep while it lasts (macOS: `caffeinate -i`), but a lid close or an explicit sleep still suspends it. A session or wait that ran across a suspension is recorded as `suspended`, and the gate fails on it.

After it finishes, the live §5.1 support and recall need a reviewer's labels, because a live curator's claims are free text that no frozen term list can judge (ACCEPTANCE_TESTS §5):

```powershell
& .venv\Scripts\python.exe evals\run.py adjudicate C:\Code\rl-gate
# label every entry of C:\Code\rl-gate\adjudication.template.json, add yourself under "reviewers", save it as adjudication.json
& .venv\Scripts\python.exe evals\run.py report C:\Code\rl-gate
```

Until every admitted claim and gold lesson is labeled, the report gives those three measures as unestablished and the gate fails with `claims_unadjudicated`. A coding agent may draft suggestions with the evidence for each item (as `adjudication.suggested.json`, every label left null), but only a reviewer's labels count.
