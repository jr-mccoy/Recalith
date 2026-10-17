# Local probe configuration (`LOCAL_CONFIG`)

The Task 0 and Task 0b probes read one operator-owned JSON file:

```bash
python tools/probe_provider.py --config probe-private/local-config.json --output docs/host-compatibility.json
python tools/probe_delivery.py --config probe-private/local-config.json --output docs/host-compatibility.json
```

`probe-private/` is git-ignored. Start from [`tools/probe_config.example.json`](../../tools/probe_config.example.json). The file holds **names, paths, and nonsecret switches only**. Credential values are read from the invoking terminal's environment by the key names you select, kept in process memory, forwarded only to the probed child, and never written to the report. Unknown fields are rejected.

Run probes from an ordinary terminal for the account you intend Recalith to use. Running from inside an agent session is allowed (the parent is then a real host-marked parent), but never point a probe at another session's credentials or proxy to obtain a pass.

## Top level

| Field | Type | Meaning |
|---|---|---|
| `config_schema` | `1` | Required |
| `$comment` | string | Ignored |
| `provider` | object | Task 0 settings (below) |
| `delivery` | object | Task 0b settings (below) |

## `provider` (Task 0, `tools/probe_provider.py`)

| Field | Required | Meaning |
|---|---|---|
| `provider_id` | yes | Lowercase identifier for the report section, e.g. `claude_cli` |
| `executable` | yes | Absolute path (or PATH name) of the CLI. Its SHA-256 and `--version` are recorded |
| `expected_version` | no | Substring the observed `--version` must contain |
| `model` | live | The explicitly selected model ID. Never guessed; required for `live` with a configured route |
| `modes` | no | Subset of `request_capture`, `live` (default both) |
| `invocation_args` | yes | The candidate isolated argument array. `{model}` is required; `{system_prompt}` is replaced by the fixed probe system prompt. Input always arrives on stdin |
| `envelope` | no | Output envelope parser; only `claude_stream_json` (default) |
| `nonsecret_env` | no | Nonsecret switches for the child (keys containing KEY/TOKEN/SECRET/PASSWORD and markers are rejected) |
| `platform_env_keys` | no | Inherited OS keys the child may receive (default `PATH`, locale, `TERM`, Windows system keys) |
| `network_env_keys` | no | Managed proxy/TLS key names forwarded in `live` mode only (e.g. `HTTPS_PROXY`, `NODE_EXTRA_CA_CERTS`) |
| `home_env` | no | Purpose-specific home keys mapped to the disposable private root (default `HOME`, `USERPROFILE` → `{home}`) |
| `request_capture_env` | no | Keys that point the CLI at the loopback recorder (default `ANTHROPIC_BASE_URL={endpoint}`, placeholder `ANTHROPIC_API_KEY`, `NO_PROXY`) |
| `alternate_auth_env_keys` | no | Keys that would select a different account/billing route; planted as decoys and required absent from the child unless selected |
| `control_args`, `control_resume_args` | no | Deliberately non-isolated launches used only to prove detectors fire (request-capture mode, no account) |
| `host_markers` | no | Registered host/nested-session markers (default `CLAUDECODE`, `CLAUDE_CODE_CHILD_SESSION`) |
| `probe_installation_id` | no | Value for the fresh `RECALITH_CURATOR_INSTALLATION` marker (a valid `inst_` UUIDv4; default `inst_00000000-0000-4000-8000-000000000000`). The child environment is built by the engine's stdlib `spawn_environment`, so overrides cannot name a marker |
| `limits` | no | `timeout_seconds` (120), `bounds_timeout_seconds` (10), `wire_stdout_bytes` (262144), `stderr_bytes` (65536), `body_bytes` (24000) |
| `auth_route` | yes | See below |
| `operator_attestation` | yes | See below |

`auth_route`:

| Field | Meaning |
|---|---|
| `kind` | `not_configured`, `env_api_key`, or `env_cloud` |
| `billing` | `none`, `api`, `subscription`, or `cloud` (classification only) |
| `env_keys` | Names of the environment keys that carry the selected credential/route. Values are taken from the invoking environment |
| `expected_api_key_source` | Value the host's init diagnostic must report (Claude: `apiKeySource`), or null |
| `description` | Free text, no secrets |

With Claude CLI 2.1.x, `--bare` reads Anthropic auth strictly from `ANTHROPIC_API_KEY` or an `apiKeyHelper` passed through `--settings`; OAuth/keychain subscription credentials are not read. A subscription route therefore needs a different candidate argument array and its own certification. The probe never switches routes to get a pass.

`operator_attestation`: `background_use` is `checked_eligible`, `checked_ineligible`, or `unchecked`; `basis` names the dated source you checked (no secrets); `checked_on` is `YYYY-MM-DD` (required unless unchecked); `managed_policy` records organization/managed-setting constraints. This is the operator's record, not a legal determination. Certification requires `checked_eligible`.

### What each mode does

* `request_capture` launches the installed CLI against a loopback recording endpoint with a placeholder key. It observes the exact outbound request (tools, system prompt, messages), validates every sentinel detector with non-isolated control launches, and exercises hang, stdout flood, a valid 15 KB body, an oversized body and malformed output. It uses no account and cannot certify authentication.
* `live` runs the isolated launch through the selected route from a clean and a host-marked parent and checks the host init diagnostic, sentinel markers, the actual child environment (Linux `/proc`), the reported auth source and a model-visible negative canary (two short model calls).

Exit codes: 0 complete certification; 4 unavailable/uncertified (report lists blocking dimensions); 2 invalid configuration.

### Recording the route for a project (Task 7)

```bash
python tools/probe_provider.py --config probe-private/local-config.json --output docs/host-compatibility.json --route-out /path/to/project
```

`--route-out` writes the project's private `.recalith/provider.json` (`ProviderConfig`, key **names** only) from this run. It is `certified` only after a complete live pass with `operator_attestation.background_use = checked_eligible`; any other run records the route explicitly uncertified, which the worker reports unavailable and never launches. Writing the route is an operator action: it is refused (exit 6) when the invoking process carries a registered host marker. The worker rechecks the recorded executable digest, host version, auth key names, expected auth source and invocation on every start, plus a request-capture isolation check from its own environment; any change makes the route unavailable until the probe is run again (decision 0009).

`python tools/check_provider_runtime.py --config probe-private/local-config.json --output docs/host-compatibility.json` records the production adapter's own request-capture checks (clean and host-marked parents) and route status in `sections.provider_runtime`; it never certifies (exit 4 unless the route is certified and both checks pass).

## `delivery` (Task 0b, `tools/probe_delivery.py`)

Documented with the delivery probe in [Task 0b](DELIVERY_PROBE.md).
