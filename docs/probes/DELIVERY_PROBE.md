# Task 0b delivery probe

`tools/probe_delivery.py` establishes whether a host makes hook-supplied context visible to the model on each delivery path, before the engine exists. It implements the SYSTEM_SPEC §9.3 nonce protocol with a nonce-only stub hook (`tools/fixtures/delivery_stub.py`). A pass shows host-path feasibility for that host/model/configuration; Task 13 must repeat it through the real engine with fences, budgets and delivery accounting.

```bash
python -m pytest tests/unit/test_delivery_probe.py -q
python tools/probe_delivery.py --config probe-private/local-config.json --output docs/host-compatibility.json
```

## Protocol

| Path | Required | Host event (Claude 2.1.x) | Injection point / eligible text |
|---|---|---|---|
| `session_start` | yes | `SessionStart` matcher `startup` | First assistant text of the session |
| `prompt` | yes | `UserPromptSubmit` | First assistant text of the turn |
| `pre_action` | optional | `PreToolUse` matcher `Bash` | First assistant text after the fixture tool call (`echo recalith-fixed-output`, whose output never contains the nonce) |
| `compact` | optional | `SessionStart` matcher `compact` | First assistant text after the compaction boundary (turns: `OK`, `/compact`, canary request) |

Per path: three positive controls (a fresh 128-bit nonce in exactly one context item) and three negative controls (nonce generated and withheld). Every trial is a fresh host session with its own private `HOME`; the nonce never appears in a prompt, repository file, tool output or earlier turn. A positive passes only if the eligible assistant text contains the exact nonce. A negative passes only if no assistant text contains the withheld nonce.

A trial is rejected (counts as neither pass) when the nonce reached the session another way: in a prompt, tool output or workspace file; when another trial's nonce appears; when an unexpected tool is used; when a negative control injected; or when a negative's transcript contains its nonce. A hook that ran and printed the nonce while the model did not echo it is `stdout_only_no_model_echo`, never a pass.

Path states: `healthy` (3/3 positive and 3/3 negative valid passes), `degraded` (the host fires the event but some control failed or was rejected), `unavailable` (the event never fired, or compaction/the fixture tool could not be triggered), `not_run` (no live route). Exit 0 requires `session_start` and `prompt` healthy; 4 when either is unavailable or not run; 8 when a supported required path is degraded. Optional paths never change the exit code; they are reported for prompt-fallback planning.

Where the host saves a transcript, the report also records whether it contains the nonce (second check). The probe never claims direct inspection of the model's internal request in live mode.

## Modes

* `live`: the real host with the selected account route and model. Only live results certify a path.
* `request_capture`: the installed host is pointed at a loopback recording endpoint (placeholder key; a scripted loopback "model" that calls the fixture tool once and otherwise answers `CANARY NONE`). The report records whether each injection reached the outbound request. This shows host-path feasibility without an account and **never** counts as an echo pass.

## Owned configuration

Stub hooks are appended to the disposable workspace's `.claude/settings.local.json`, next to deliberately planted unrelated settings (a permission rule and an unrelated `UserPromptSubmit` hook). Removal deletes only groups exactly equal to the recorded ownership manifest, reports `modified`/`missing` entries instead of deleting them, and runs in a `finally` block so a crashed trial still cleans up. The report records whether unrelated settings were preserved byte for byte (canonical JSON).

## `delivery` configuration section

| Field | Required | Meaning |
|---|---|---|
| `host_id` | yes | Report key, e.g. `claude_code` |
| `executable` | yes | Host CLI path |
| `expected_version` | no | Substring of `--version`; a mismatch prevents live trials |
| `model` | live | Explicit working-agent model ID |
| `modes` | no | Subset of `request_capture`, `live` |
| `session_args` | no | Session argument array; `{model}` required. Default loads only local settings (`--setting-sources local`), strict MCP, stream-json, and allows exactly `Bash(echo recalith-fixed-output)` |
| `multi_turn_args` | no | Added for the compaction trial (default `--input-format stream-json`) |
| `nonsecret_env`, `platform_env_keys`, `network_env_keys`, `home_env`, `request_capture_env`, `host_markers` | no | As in the provider section; inherited host markers are removed so each trial is a top-level session |
| `auth_route` | yes | `kind` (`not_configured`, `env_api_key`, `env_oauth_token`, `env_cloud`), `billing`, `env_keys` (names only), `description` |
| `limits` | no | `trial_timeout_seconds` (180), `capture_trial_timeout_seconds` (90), `hook_timeout_seconds` (10) |

A live run makes 24 short host sessions (four paths × six controls); the pre-action and compaction trials make two or three model calls each.
