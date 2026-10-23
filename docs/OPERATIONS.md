# Operating a Recalith installation (Claude autonomous preview)

Engine `0.1.0.dev0` · release profile `claude_preview` · status: **preview gate blocked (B1)**, not released.

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

## 4. One-time setup (operator, from an ordinary terminal)

Administrative commands are refused inside an agent's process tree, even with a terminal and a token (exit 6). Run them from an ordinary OS terminal launched outside Claude Code (not an IDE terminal that inherits its marker), using the project launcher `.recalith/bin/recalith`.

1. Provision the runtime: `python bootstrap.py install` (hash-locked wheelhouse; no hook-triggered download).
2. `recalith init --project . --profile coding --release-profile claude_preview` at the terminal. For automation, first create a standalone token at the terminal with `recalith operator-token create --output FILE`, then `recalith init --operator-token-file FILE` from the automation; a token is never minted noninteractively.
3. Certify the inference route and the host (B1's operator commands in [BUILD_PROGRESS](BUILD_PROGRESS.md#blockers-and-decisions)): `tools/probe_provider.py --backend BACKEND --route-out`, `tools/check_provider_runtime.py --backend BACKEND`, `recalith integrate claude`, `tools/probe_delivery.py --engine-project`.
4. `recalith status` → exit 0.

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

The preview release gate (ACCEPTANCE_TESTS §6.1, §8) is **blocked by B1**. The evaluation harness (`evals/run.py`), the workload days, the latency gate (`tools/measure_release_latency.py`) and the release checklist ([docs/release/claude_preview_checklist.json](release/claude_preview_checklist.json)) exist and have run in recorded/scripted mode only, which is mechanics evidence and never a live pass. See the Task 18 checkpoint in [BUILD_PROGRESS](BUILD_PROGRESS.md).
