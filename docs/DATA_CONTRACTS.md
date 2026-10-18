# Data and Interface Contracts

Revision 1.3 • 2026-10-15 • Normative companion to [SYSTEM_SPEC](SYSTEM_SPEC.md)

## 1. Conventions and types

Worker/service objects use strict Pydantic models and generated JSON Schema. Synchronous hooks use only primitive JSON wire objects plus generated standard-library validation under `recalith.fast`; they never import these Pydantic modules. A shared fixture suite proves identical accepted/rejected wire shapes. The worker performs full validation again before ingestion. Reject unknown fields in core envelopes and provider operations. Extension data is permitted only inside an adapter-namespaced `extensions` object, with a byte cap. JSON is UTF-8; object keys are strings; no NaN or infinity; timestamps are UTC RFC3339 with microseconds. Literal-valued fields are type-exact: a boolean is never an integer literal and an integer is never a boolean literal (decision 0005). Empty and unknown values are distinct. Arrays retain order unless explicitly defined as sets.

`Id` is a prefixed lowercase identifier. New project, installation, workspace, session, task, episode, claim, job, operation, and delivery IDs use UUIDv4 after a type prefix. Locally captured event IDs are `evt_` + SHA-256 of canonical `[installation_id, adapter_id, source_event_key]`. Imported source stubs are `evt_imp_` + SHA-256 of canonical `OriginEventKey`, excluding the destination installation and export digest. `OriginEventKey = {source_namespace: str, source_event_key: str}`; the namespace is the original project/installation/adapter identity, or an explicitly assigned persistent import-source namespace when that identity is unavailable. Reimports preserve this key across new destination installations. Imported IDs remain metadata-only lineage references, never new local observations. IDs are never reused. Ordering uses event source sequence and database commit sequence, never UUID order or wall-clock time alone.

`Revision` is an integer starting at 1. `Digest` is a full lowercase SHA-256 hex digest. `JsonObject` means a validated JSON object. `UtcTime` is a timestamp as above. API collections use cursor pagination with a default of 50 and maximum of 200. No API returns the complete store by default.

### 1.1 Context and references

| Type | Required fields |
|---|---|
| `InstallationContext` | `project_id: Id`, `installation_id: Id`, `root: Path`, `workspace_id: Id`, `workspace_root: Path`, `engine_version: str`, `schema_version: int`, `policy_revision: int`, `actor: Actor` |
| `Actor` | `kind: operator\|host_agent\|controller\|adapter`, `id: str`, `channel: cli\|hook\|mcp\|worker\|import` |
| `RecordRef` | `kind: event\|task\|episode\|claim\|capsule`, `id: Id`, `revision: int` (events/capsules use 1 unless replaced by an explicit redaction revision) |
| `SourceRef` | `adapter_id: str`, `source_event_key: str`, `host_session_id: str`, `origin_kind: str`, `source_digest: Digest`, optional `locator: str` |
| `Scope` | `workspace_ids: list[Id]`, `task_ids: list[Id]`, `branch_refs: list[str]`, `paths: list[str]`, `environment: EnvironmentValues`; empty eligibility lists mean unrestricted within this installation; `branch_refs` are recall/origin annotations only |
| `Condition` | `kind: action_kind\|tool\|path\|environment_equals\|version_range\|branch_ref`, `key: str`, `value: str`, optional `upper: str`, `exclude: bool` |
| `EvidenceLink` | `ref: RecordRef`, `relation: supports\|contradicts\|context`, `root_event_ids: list[Id]`, `locator: SpanLocator\|null`, `mapping: tool.exit_code\|tool.reported_result\|config.exact_value\|null` |
| `SpanLocator` | `field: str`, `start: int`, `end: int`, `text_digest: Digest`; offsets are Unicode code points into the specified stored string |

Paths in portable objects are normalized relative POSIX paths. Absolute workspace/transcript paths occur only in local source registrations and local configuration. `Scope` eligibility dimensions combine with AND; values within a dimension combine with OR. `branch_refs` are excluded from eligibility; an explicit `Condition(kind="branch_ref")` is required for a genuine branch restriction. Conditions combine with AND, including explicit exclusions. Missing environmental values return unknown. Path conditions use exact paths or directory prefixes ending in `/`; v1 does not accept model-authored glob/regex expressions (a path condition containing `* ? [ ] { }` is refused at validation; a name equal only after case folding or Unicode normalization evaluates unknown). Version ranges initially support PEP 440 through a pinned `packaging` dependency: `value` is the inclusive lower bound and `upper` the inclusive upper bound (absent: unbounded above); `upper == value` specifies exact comparison. Versions outside that grammar require that exact-string comparison or remain unknown. No improvised lexicographic version ordering (decision 0010).

`EnvironmentValues` is a string map validated against the installed adapter registry. Built-ins: `os` in `windows|linux|macos|other`, `arch` in `x86_64|aarch64|other`, bounded runtime-version strings for `python_version`/`node_version`, and `ci` in `true|false|unknown`. Values are at most 64 UTF-8 bytes; registered extensions need an explicit value grammar and sensitivity classification. Unknown keys and disallowed values are dropped before durable capture, with a key/count-only coverage warning. Provider-proposed unregistered conditions are rejected. Never populate this map from arbitrary `os.environ` values.

`EnvironmentObservation = {key: str, value: str, workspace_id: Id, executable_id: str|null, source_kind: operator_config|certified_tool|adapter_platform, source_ref: RecordRef|null, config_revision: int|null, observed_at: UtcTime, fingerprint: Digest, executable_fingerprint: Digest|null, freshness: current|stale|unknown}`. Runtime versions require `operator_config` with a config revision or `certified_tool` with an observed version-command event and registered executable identity. `adapter_platform` may populate only normalized `os`/`arch` and a registered nonsecret `ci` source, never recalith's Python as project Python. A query resolves the applicable declared/observed executable; incompatible sources without a resolved binding, changed executable identity, or stale/unknown metadata return unknown. The executable registry records its current fingerprint and the observed time/revision of the latest fingerprint change. An observed runtime version becomes `stale` if its bound executable fingerprint no longer matches or its observation predates that registered change; a certified-tool observation with missing executable binding/fingerprint is `unknown`. An explicit operator-config value is current only while its applicable config revision remains current; it does not fabricate a tool observation or require a tool-result fingerprint. Both stale and unknown values evaluate as unknown in a current query. Freshness changes advance guidance epoch for affected conditions; a new certified observation or explicit applicable config revision is needed to restore a current value. Evidence remains labeled declared versus observed. The hook consumes the persisted allowlisted value/fingerprint and never probes a runtime.

`MappingName` is the closed three-name enum in `EvidenceLink`. `tool.exit_code` requires a finished certified invocation with a numeric exit code; `tool.reported_result` requires a certified `ToolAssertion`; `config.exact_value` requires the registered config parser, key, exact typed value, and fingerprint. Unknown names do not become valid merely because a provider proposes them. Exact field contracts (decision 0011): both tool mappings cite a `tool_finished` event under `observed_tool` authority with `result_received` true; `tool.exit_code` needs an integer `exit_code` and a null locator or one on exactly the `exit_status` assertion's value; `tool.reported_result` needs a locator covering the whole `assertions.<n>.value` string of a `test_result` or `parsed_value` assertion; `config.exact_value` has no registered parser yet and is refused. A mapping is validated wherever it appears. An `observed` claim is a `fact` whose every support link carries a valid mapping and whose proposition equals the code rendering of the mapped observation exactly: `` `<argv joined by spaces, or the tool name>` exited with code <n>. `` or `` `<label>` reported <kind> <identity>: <value> (passed|failed). `` (no parenthesis for a null verdict); anything wider is `inferred`.

Actor identity is set by the guarded registered transport, not accepted from provider output or a CLI argument. `channel=cli` alone never establishes `kind=operator`; apply SYSTEM_SPEC §13.1 before assigning it. A hook or MCP caller cannot label itself operator. Ordinary JSON events from generic adapters are untrusted observations unless the adapter registration grants a specific structured authority.

## 2. Event envelope and durable segment

### 2.1 `EventEnvelope`

Required fields:

- `schema_version: 1`
- `event_id: Id`
- `project_id: Id`, `installation_id: Id`, `workspace_id: Id`
- `adapter_id: str`, `adapter_version: str`, `source_event_key: str`
- `session_id: Id`, `host_session_id: str`, `task_id: Id|null`
- `source_sequence: int|null`, `occurred_at: UtcTime|null`, `recorded_at: UtcTime`
- `kind: session_started|user_message|assistant_message|tool_started|tool_finished|artifact_changed|compaction|session_stopped|session_ended|memory_delivered|operator_declaration|operator_correction|operator_forget|agent_attempted_operator_command|generic_observation`
- `channel: user|assistant|tool|external|memory`
- `origin: SourceRef`, `authority: untrusted|observed_tool|explicit_user|derived`
- `derived_from: list[RecordRef]`, `root_event_ids: list[Id]`
- `payload: JsonObject`, `payload_digest: Digest`
- `coverage: {truncated: bool, redacted: bool, missing_context: bool, parser_complete: bool}`

Authority is adapter-assigned within its certification. `explicit_user` means the event came from the user channel; whether a particular sentence is a declaration or a quote still requires interpretation before claim admission. It does not authorize arbitrary payload instructions.

Tool payload: `tool_call_id`, `tool_name`, `arguments`, `result_received`, `outcome`, optional `exit_code`, optional bounded `result_text`, optional `assertions: list[ToolAssertion]`, `action: ActionDescriptor`, `observation: ObservationDescriptor|null`, `text_chunks: list[TextChunk]`, `error_signature: str|null`, and `expected_red: bool` (reserved false in v1; no certified true source). Outcome is `success|failure|interrupted|not_run|unknown`. A strict normalized envelope rejects `expected_red=true`; an adapter encountering an untrusted raw suggestion drops it, records a coverage warning, and normalizes false. Assistant intent, a user pivot phrase, and a configured path name are contextual intent, not a certified tool verdict. They may inform semantic A13 review. These are execution outcomes, not classifications of the usefulness of the approach. `tool_started` has `unknown`; a linked later event supplies the result.

`ToolAssertion = {kind: test_result|exit_status|parsed_value, identity: str, value: str, passed: bool|null}`. Identity is at most 256 bytes and value at most 4 KiB; at most 32 assertions fit within the event cap. `passed` is required for a parsed test verdict and null when the parser cannot establish one. `exit_status.value` is the canonical decimal integer; other values follow the adapter's registered parser contract. An assertion is populated only by a parser certified for that output/version. Model-generated prose or arbitrary JSON printed by an untrusted command does not automatically certify an assertion.

`TextChunk = {stored_field: str, source_field: str, original_start: int, original_end: int, text: str, text_digest: Digest}`. Offsets are Unicode code points into the original normalized string before bounding. The default head/tail limits and error-signature limit are in SYSTEM_SPEC §3.3. A `SpanLocator` points at an exact stored string field/chunk, never at the artificial omission marker. Each stored span keeps its original coordinate mapping for future capsules. When `result_text` exceeds its head/tail limits, the stored `result_text` is the display string `head + omission marker + tail` (the marker fits the contract's 256-byte allowance), and `text_chunks` carry the head (`result_text_head`) and tail (`result_text_tail`) as the addressable spans; the omitted original range is the gap between them (decision 0004). Host- or model-supplied `assertions`, `error_signature` and `text_chunks` are dropped and recomputed from certified parsers during normalization.

The adapter constructs the stable source-event key from host event identity where possible; otherwise from registered source-file identity, complete record byte offset, and event subindex. Same key plus same normalized digest is duplicate input. Same key plus a different digest is an `event_identity_conflict`. Keep the first event unchanged and persist `SourceConflict = {conflict_id: Id, original_event_id: Id, adapter_id: str, source_event_key: str, payload_digest: Digest, scrubbed_payload: JsonObject, coverage: JsonObject, first_seen_at: UtcTime, state: unresolved|resolved|forgotten}`. `conflict_id` hashes installation + adapter + key + conflicting normalized digest, under a `conf_` prefix. The uniqueness key is `(adapter_id, source_event_key, payload_digest)` inside the installation. Conflicts are visible in health; dependent guidance becomes needs-revalidation with no caution, and conflicting payloads are ineligible as support until explicitly resolved through a new authoritative observation; never assign two payloads to the original event ID. Conflict bodies follow the same caps, retention, and forgetting rules as events.

`agent_attempted_operator_command` uses channel `memory`, authority `derived`, no eligible root, and payload `{command_kind: str, marker_category: str, reason_code: "policy_refused"}`. It records a refused attempt, not the requested statement or an executed administrative effect. It cannot create `user_declared` evidence. When audit capture fails, refusal still returns exit 6 with audit status rather than retrying the forbidden operation.

### 2.2 `CaptureReceipt` and segments

`CaptureReceipt = {status: accepted|duplicate|not_captured, segment_id: Id|null, event_ids: list[Id], coverage: JsonObject, error_code: str|null}`.

A segment contains `segment_schema: 1`, installation identity, a list of envelopes, source cursor proposals, creation time, and a digest of canonical serialized content. Each event's stored payload is at most 64 KiB; each segment at most 256 KiB. Large messages are partitioned with original offsets and coverage markers. A partitioned message keeps the source key for part 0 and uses `<key>#p<i>` for later parts, each with `text_part = {source_field, index, count, original_start, original_end}`. Segment IDs use the `seg_` prefix. Cursor proposals ride only in the last segment of a capture call. A segment may also carry up to 8 `source_registrations` (`SourceRegistrationProposal = {source_id, adapter_id, session_id, host_session_id, source_kind: transcript_jsonl, locator, parser}`): an exact transcript path observed in an actual session payload by a hook that cannot write SQLite. They ride in the last segment, enter the content digest only when present, and ingestion records them in `capture_sources` in the event transaction after re-deriving the locator and source ID (decision 0005). Model calls select from this journal separately; a capture segment is not necessarily a model episode.

`accepted` means the scrubbed segment is durable. It does not mean curation finished. Segments are private files with restrictive OS permissions where supported. They contain no unsanitized backup payload.

A capture call that spans several segments names its last segment in `segment_id` and every segment in `coverage.segment_ids`. `capture` does not consult the store, so duplicates are resolved at ingestion and `capture` itself answers `accepted` or `not_captured`; `duplicate` is reserved for a transport that already knows the event is durable. The durable source cursor is advanced only after every segment of the call is published (`spool/cursors/<source_id>.json`); ingestion records the same proposal in `capture_sources` in the event transaction, and recovery resumes from the furthest of the two. Spool layout, platform durability limits, and gap records are in decision 0004.

### 2.3 Hook wire types and interfaces

`HookContextWire` holds primitive project/installation/workspace/session IDs, registered absolute local paths, policy revision, and host adapter identity. It is read from a validated local manifest, not accepted from the model: `.recalith/run/hook-context.json` with `{context_schema: 2, project_id, installation_id, workspace_id, root, workspace_root, root_identity, workspace_root_identity, policy_revision, adapters: {<adapter_id>: {host_version, delivery_enabled}}, worker: {autostart, route_keys}}`, written by the service from a resolved installation context; the hook refuses a manifest whose root identities no longer match (`installation_relocated`). `worker.autostart` is the integration's consent for the hook to start this installation's worker through the registered start path; `worker.route_keys` names the selected provider route's environment keys the worker may carry (never a marker). A `context_schema: 1` manifest (no `worker`) still captures, with autostart off (decision 0006). `HookRequestWire` contains `event_role`, `delivery_enabled`, the primitive normalized `events`, `source_registrations`, content-free `coverage_gaps` and an optional primitive context `query`. `HookReplyWire` holds the capture `receipt`, `host_output` (host context envelope), `delivery_attempt_id`, `emitted_receipt` if any, `delivery` state, `degradations` and the content-free `worker` start status (`worker_started|worker_running|worker_start_pending|worker_autostart_disabled` or a degradation code). These are plain-data wire contracts, not a competing domain model; their primitive validators are generated from the strict models by `tools/generate_hook_wire.py` (decision 0005).

`SessionScratch` contains schema/version identity, session ID, state revision, store revision and guidance/policy/tombstone fence, cumulative reserved/emitted token totals, recent outcomes, and delivery entries. An entry has `attempt_id`, `packet_digest`, exact `(record_id, revision, condition_digest)` items, `state: reserved|emitted|uncertain`, purpose, estimated tokens, and time. Outcomes reference original event IDs and `ActionDescriptor`, never a model paraphrase. Bounds: 128 KiB, 256 entries, 32 outcomes, 20 ms lock acquisition. A worker-owned safe checkpoint can prune entries after durable receipt accounting; counters never reset on pruning.

```python
hook_capture(ctx: HookContextWire, events: Sequence[dict]) -> dict
hook_compile_context(ctx: HookContextWire, query: dict) -> dict
hook_record_delivery(ctx: HookContextWire, attempt: dict, *, emitted: bool) -> dict
handle_hook(ctx: HookContextWire, request: HookRequestWire) -> HookReplyWire
spawn_environment(manifest: dict, inherited: Mapping[str, str], *, purpose: str) -> dict[str, str]
ensure_worker(ctx: HookContextWire, *, deadline: float) -> str
```

`spawn_environment` lives in `fast/process_env.py`; purpose is exactly `worker|curator`. Its primitive validated manifest `{manifest_schema: 1, purpose, installation_id, platform_keys, route_keys, overrides}` contains installation identity, exact permitted platform/backend environment-key names (a per-OS platform registry plus the selected route's named auth/config keys), configured nonsecret overrides and auth-reference policy, never arbitrary model-proposed keys; a credential-shaped platform value is dropped and Windows names match case-insensitively. `ensure_worker` is the registered internal worker start the hook runs after capture: lock probe, 10-second start throttle, fresh worker environment, detached start of `python -I -m recalith.controller.worker` for this installation only, never the guarded CLI, never waiting, and shed with `deadline_worker_start_skipped` below 30 ms of remaining deadline (decision 0006). It builds a fresh map from the selected permitted sources, removes registered host/nested-session markers and inherited recalith role markers, then assigns only the correct worker/curator installation marker. Explicit forbidden marker removal wins over an allowlist mistake. It never mutates the parent map or grants an operator actor. Provider code uses the same stdlib helper; it does not maintain a second filter. Credentials are resolved only for the selected route, kept in process memory, and excluded from manifests/logs/proposals. Environment diagnostics record key names only.

These live under `src/recalith/fast/`, import only stdlib and that audited package, perform no SQLite database write transactions, and return validated primitive wire shapes matching the named domain types. `handle_hook` owns session locking, final revision fencing, budget reservation, stdout emission, and receipt spooling. It must not call the heavier public service functions with the same conceptual purpose. One monotonic deadline is entry +250 ms; optional substeps use the remaining time and SYSTEM_SPEC §5.1.1's degradation order. Session reservation and the fresh final fence are required for any emission, distinct from a skippable typed-outcome overlay update.

Host event names are mapped by the exact-version adapter fixture to the normalized roles below; a similar name is not certification. `HookRequestWire` carries a registered `event_role` and `delivery_enabled` derived from the installed capability manifest, never from model input.

| Normalized role | Capture branch | Delivery branch when installed/certified |
|---|---|---|
| Session start | `session_started`; register source/session | `session_start`, workspace-only until a binding exists |
| User prompt submission | `user_message` | `prompt`, with compaction-restoration purpose if a captured restoration is pending |
| Before tool/action | `tool_started` | Optional `pre_action` |
| After tool/action, including failure | `tool_finished`; optional typed-outcome overlay | None |
| Compaction notification | `compaction` with stable identity | Optional `compact_restore` only on a certified post-compaction injection event; pre-compaction capture alone does not inject |
| Stop, end, assistant/transcript supplement | Corresponding lifecycle/message events | None |

Task 3b enables only the capture column and advertises delivery unavailable; it does not return a placeholder context marked delivered. The exact Claude Code 2.1.301 mapping, identity keys and host-output limits are recorded in decision 0005 and `docs/host-compatibility.json` (`sections.capture.claude_code`). Task 12b adds the delivery branch, and Task 13 certifies its paths. Unknown/unsupported host roles retain a coverage gap rather than guessing a mapping.

## 3. Working state

`TaskState` fields:

| Field | Type / meaning |
|---|---|
| `task_id`, `project_id`, `installation_id` | IDs |
| `revision` | Current task revision |
| `status` | active, paused, completed, abandoned, linked (nonowning provisional placeholder only) |
| `redirect_task_id` | `Id\|null`; required for linked placeholder; same installation/workspace; never a cycle |
| `title` | Short task name |
| `objective` | `SupportedText` |
| `constraints` | `list[SupportedText]` |
| `plan` | `list[SupportedText]` |
| `pending_actions` | `list[PendingAction]` |
| `known_results` | `list[SupportedText]` |
| `blockers`, `open_questions` | `list[SupportedText]` |
| `next_action` | `SupportedText\|null` |
| `session_ids`, `child_task_ids` | Lists of IDs |
| `scope` | `Scope` |
| `updated_at`, `last_activity_at` | UTC times |
| `completion_basis` | `SupportedText\|null` |

`SupportedText = {text: str, evidence: list[EvidenceLink], basis: observed|user_declared|inferred}`.

`PendingAction = {action_id: Id, description: SupportedText, tool_call_id: str|null, state: proposed|running|awaiting_result|finished|cancelled}`.

A `linked` placeholder has `next_action=null` and `pending_actions=[]` in its current head. Reducers do not derive actions, blockers or tentative actionable context from it; follow the versioned binding to the nonlinked target instead. Historical pre-link revisions remain inspectable as history only. Link creation transfers pending call associations before clearing the placeholder's current actionable fields. Reject model patches that try to reactivate or put actions on a linked head; an explicit later split creates a new task under the existing rules.

No field is cleared just because it was absent from a new chunk. Task operations are explicit patches: set a field, append an item, close an item by ID, or change status. A pending action's ID is its code-assigned `action_id`; every other list item (a `SupportedText`) is identified by `item_` + SHA-256 of its normalized content (decision 0008). Full replacement requires an expected revision and a complete state. Field changes preserve supporting references in history. A status patch to `completed` requires a `completion_basis` citing at least one record (`completion_requires_evidence`); inactivity pauses a task and never completes it.

### 3.1 Versioned task bindings

`TaskBoundaryCandidate = {boundary_id: Id, session_id: Id, after_event_id: Id|null, proposed_event_ids: list[Id], reason: host_reset|pivot_prefix|disjoint_paths|idle_resume|new_session|single_active_task, source_task_id: Id, state: pending|confirmed|rejected|linked}`. Record the exact signal and policy version. Path clustering uses the first normalized component (`@root` for root files), excluding `.recalith/` and ignored generated paths. The coding profile groups `src`, `test`, `tests`, and `docs` as `@code`; explicit configured mappings may extend it. Five consecutive path-bearing actions must share a nonempty disjoint cluster to propose a split. `single_active_task` follows SYSTEM_SPEC §3.2's exactly-one candidate, 24-hour pause limit, no conflicting explicit boundary, and first-three-path-actions rule. Code records a reversible provisional link using version-checked binding operations; no model or model budget is required.

`TaskBindingRevision = {binding_id: Id, event_id: Id, revision: int, task_id: Id, binding: provisional|confirmed, boundary_id: Id|null, assigned_by_operation: Id, previous_revision: int|null}`. Event `task_id` is only the immutable capture-time hint; reducers resolve the current binding head. A tool completion inherits its start event's binding before any new boundary decision. Queries expose provisional status and do not silently present it as a confirmed task split.

`TaskBindingProposal = {boundary_id: Id, decision: confirm_split|reject|link_session, event_ids: list[Id], target_task_id: Id|null, expected_binding_revisions: dict[Id,int], evidence: list[EvidenceLink]}`. For a split, code allocates the new task ID and moves the exact range atomically with the task-state revisions; the model cannot rewrite source events. Linking requires an existing eligible same-project task. Pending call/result pairs remain together. An unknown/ambiguous decision keeps provisional bindings and preserves separate existing objectives. After the deterministic link, the abandoned provisional head has `status=linked` and `redirect_task_id=target`; it is not a second active objective or candidate for another automatic link. Reassign the provisional session range and its pending call/result pairs atomically; do not copy narrative fields over the target. Preserve history so an explicit later split can reverse the assignment. Metrics count allocated placeholders separately from nonredirected task heads.

Persistence (decision 0008): typed reduction opens provisional tasks with the controller-only `create_task`, writes first (provisional) bindings and their typed facts with `bind_events`, and records candidates with `record_boundary`; none of the three is in any model purpose's permitted kinds. One binding chain per event (`binding_id` = `bind_` + SHA-256 of the event ID). A result joins its call by `tool_call_id` (`tool_calls`), across splits and sessions. A proposal's `event_ids` must be bound to the boundary's source task (following redirects), lie in one session and form a contiguous slice of that session's events in the task; a range that would separate a call from a result that has already arrived is rejected (`detaches_call_result`), while a still-pending call may move and its result follows it. `confirm_split` moves the range and the items whose evidence lies wholly inside it; the source keeps its objective. `reject` confirms the events where they are. `link_session` on a `linked` candidate with its current target confirms the deterministic link; a link is reversed only by an explicit split, never by reviving the placeholder.

## 4. Episode

`Episode` fields: `episode_id`, installation identity, `revision`, `task_id`, `title`, `started_at`, `ended_at|null`, `state: open|settled|archived`, `objective: SupportedText`, `preconditions: list[SupportedText]`, `steps: list[EpisodeStep]`, `outcome: SupportedText`, `unresolved: list[SupportedText]`, `source_event_ids: list[Id]`, `related_episode_ids: list[Id]`, `scope`, and `coverage`.

`EpisodeStep = {ordinal: int, action: SupportedText, result: SupportedText|null, outcome: success|failure|interrupted|not_run|unknown, causal_assessment: SupportedText|null}`.

Episodes retain successful, unsuccessful, and uncertain outcomes. `create_episode` takes `state: open|settled` (default `open`); `coverage` is computed by code from the source events, never supplied; `revise_episode` may set `state` to `open` or `settled` only. Deterministic checkpoint episodes cite events outside their own `source_event_ids` (the objective, a call started in an earlier range, a predecessor's unresolved items) with relation `context` only (decision 0008). A procedure extracted from several episodes references each episode and its underlying independent roots. An episode derived only from another episode cannot masquerade as a new experience.

## 5. Claim and procedure

`ClaimRevision` fields:

| Field | Type / policy |
|---|---|
| `claim_id`, `project_id`, `installation_id` | IDs |
| `revision` | Integer |
| `kind` | fact, decision, preference, failure_lesson, procedure |
| `proposition` | Human-readable claim |
| `proposition_key` | Structured `{subject: str, predicate: str}` used to propose comparisons; not proof of equivalence |
| `scope` | `Scope` |
| `conditions` | `list[Condition]` |
| `basis` | observed, user_declared, inferred |
| `strength` | weak, supported, corroborated |
| `status` | candidate, active, disputed, superseded, invalidated, archived, quarantined, forgotten |
| `freshness` | current, needs_revalidation, unknown |
| `supports`, `contradicts` | `list[EvidenceLink]` |
| `context` | `list[EvidenceLink]`, relation `context` only: counter-observations such as a FailureRecheck's later success; carried on later revisions; never support, never contradiction (decision 0012) |
| `evidence_availability` | available, capsule_only, expired, redacted |
| `effective_from`, `effective_until` | UTC or null; never guessed |
| `recorded_at`, `last_supported_at`, `review_due_at` | UTC or null as appropriate |
| `dependencies` | `list[DependencyRef]` |
| `review_class` | volatile or stable; computed by code under SYSTEM_SPEC §6.3 (`controller.revalidate.review_class`, transitive over claim dependencies, decision 0012) |
| `review_assessment` | `ReviewAssessment\|null`; required by the operation policy |
| `supersedes`, `superseded_by` | `list[RecordRef]` |
| `procedure` | `ProcedureBody\|null` |
| `failure` | `FailureBody\|null` |
| `origin` | `ImportOrigin\|null` |
| `model_provenance` | `ModelProvenance\|null` |

`DependencyRef = {kind: file|config|environment|claim, key: str, fingerprint: Digest|null, record: RecordRef|null}`.

`ReviewAssessment = {review_job_id: Id, batch_id: Id, candidate_ref: RecordRef, proposal_digest: Digest, evidence_digest: Digest, prompt_digest: Digest, verdict: supported|revise|reject, objections: list[str], evidence_refs: list[EvidenceLink], reviewed_at: UtcTime}`. Provider provenance and time are assigned by code. A capacity-limited assessment returns `reject` with objection `review_capacity` instead of truncating a `revise`. That code leaves the claim unadmitted/candidate and records a capacity failure, not a factual refutation or an automatic status retirement; normal bounded retries apply. `supported` means that this bounded review found the scoped proposal supportable; it is not a new observation or proof of truth. Altering the reviewed proposition, evidence, scope, or relevant conditions requires a fresh review. Verdict effects (decision 0011): an admitted `supported` makes the candidate `active` with strength from its root classes; `revise` records objections only (candidate and proposition unchanged); a substantive `reject` archives the candidate (not admitted, no falsity asserted); `reject` with the sole objection `review_capacity` leaves a weak candidate. Every outcome, and every refused, duplicate, foreign, stale, missing or deferred verdict, is recorded per candidate revision in `review_outcomes` with its exact reason code; recording an assessment never schedules another review.

Every dependency key has a registered resolution rule. `file` keys are normalized workspace-relative paths; `config` keys identify a registered parser and property; `environment` keys use `EnvironmentValues`; `claim` uses an exact `RecordRef`. A null fingerprint never matches an arbitrary current value. Branch annotations are not a substitute for these dependencies. Fingerprints are resolved by code at admission (decision 0012): `file` — SHA-256 of the current workspace bytes, null when a certified write to the path was observed after the claim's latest event evidence; `environment` — `SHA-256(["environment", key, value])` of the one current observed value; `config` — null (no registered parser); `claim` — the dependency's content fingerprint (content key and whether it is still guidance). A proposed non-null fingerprint must equal the resolved one (`dependency_fingerprint_mismatch`).

`ProcedureBody = {preconditions: list[SupportedText], steps: list[SupportedText], expected_outcomes: list[SupportedText], stop_conditions: list[SupportedText], successful_episode_ids: list[Id]}`.

`FailureBody = {action_family_digest: Digest|null, last_supporting_failure_event_id: Id|null, observed_failure: SupportedText, consequence: SupportedText|null, alternative: SupportedText|null, retry_conditions: list[SupportedText]}`. The two index fields are re-derived whenever the support links change (a newer confirming failure moves them).

`ImportOrigin = {source_project_id: Id|null, source_installation_id: Id|null, source_record_id: str, source_revision: str, export_digest: Digest}`. Import materializes local metadata-only source-event stubs for imported observation roots, keyed by `OriginEventKey` and the deterministic `evt_imp_` ID, and remaps evidence references to local records or capsules. These stubs have import provenance and do not become new independently observed events. Reimporting the same origin reuses the same local lineage mapping.

`ModelProvenance = {provider_id: str, configured_model: str, resolved_model: str|null, adapter_version: str, prompt_id: str, prompt_digest: Digest, job_id: Id}`.

Claim revisions are immutable except explicit privacy purging. `status` in an old revision remains historical; the `claim_heads` table points to the current revision. Superseding creates a new claim ID when the proposition is replaced; clarification/narrowing of the same proposition creates a new revision. A `confirms` evidence attachment also creates a revision. Record titles may change without changing IDs. A forgotten claim retains only a content-free tombstone/head marker; `show` returns that marker instead of reconstructing a required proposition body.

## 6. Evidence capsules and relations

Live retention owners are current claim heads with status `active|disputed|candidate`, nonlinked task heads with status `active|paused`, and episode heads with state `open`. Traverse their authoritative evidence links to primary source payloads and all required locator/intermediary context; deduplicate shared roots. Stored archived/superseded intermediate records do not break a live owner's provenance path. An old historical revision alone is not a live owner. Pin eligibility is derived from these heads/links; any cache of it is rebuildable and cannot authorize expiry on its own.

Age-based removal rechecks owner reachability and source availability in the same transaction that expires the payload. Admission/reference mutation uses the same serialization/revision checks, so concurrent pin-versus-expiry cannot leave supported guidance backed by absent data. Preview's 180-day clock applies only to unpinned payloads. Full uses a 30-day default for unpinned payloads and may replace pinned support with a verified sufficient exact capsule atomically. Failed capsule conversion retains the pin. Release of the final owner permits expiry on the next sweep if already old; forgetting overrides pins. Explicit loss/missing imported support still triggers availability/strength recomputation and guidance fencing.

`EvidenceCapsule = {capsule_id: Id, source_ref: SourceRef, origin_event_key: OriginEventKey, root_event_ids: list[Id], preserved_observation: JsonObject, spans: list[CapsuleSpan], captured_at: UtcTime, scope: Scope, redacted: bool, content_digest: Digest}`.

`CapsuleSpan = {origin_ref: RecordRef, original_locator: SpanLocator, text: str, context_before: str, context_after: str, text_digest: Digest}`. Exact text must hash to both `text_digest` and the original locator digest. Context is scrubbed and bounded and does not create a new observation. Preserve source-region/declaration attribution and any necessary surrounding context; if authorship or meaning cannot be supported after expiry, downgrade availability rather than retaining a falsely certified declaration. A typed capsule preserves the registered assertion/parser fields instead of inventing prose.

The evidence resolver dispatches by `RecordRef.kind`. For a capsule, it finds the matching origin locator and returns that exact substring; it does not slice the capsule at the old event offsets. Capsule creation, reference redirection in `evidence_links`, and event payload expiration commit together. Normalized evidence links are authoritative for current DTO rendering; frozen proposal/revision source refs remain resolvable through the capsule origin index. Do not rewrite immutable historical claim prose merely to update a storage locator. The redirect is a recorded retention operation preserving original ref/locator metadata. If a full-profile compaction cannot preserve adequate text, retain the original pinned payload. If the text is already unavailable, missing support becomes `expired`, never an unresolved pointer presented as intact evidence.

Capsules contain the minimum evidence needed for current claims. They are not free-form model summaries presented as primary evidence. A quote capsule preserves exact relevant text with enough context to interpret it; a typed observation capsule preserves parsed fields and source mapping. If a model infers a cause, the capsule stores the observed facts and the claim stores the inference.

Relations are `supports`, `contradicts`, `derived_from`, `supersedes`, `applies_to`, and `related_to`. Arbitrary relationship types are not allowed in v1. Only support links with distinct underlying observation roots can increase corroboration. Relatedness and repeated delivery never do. Initial deterministic evidence mappings are `tool.exit_code`, `tool.reported_result`, and `config.exact_value`; each is registered in adapter code with an exact field/type contract. A reported tool result supports what that tool reported under the captured invocation, not a broader causal or correctness claim. Model-supplied mapping names without a registered validator are rejected.

### 6.1 Observation identity and root classes

`ObservationDescriptor = {origin_event_key: OriginEventKey, observation_kind: user_declaration|tool_result|artifact_snapshot, authority_actor_id: str|null, artifact_key: str|null, artifact_digest: Digest|null, action: ActionDescriptor|null, experiment_identity: str|null, dependencies: list[DependencyRef], dependency_coverage: complete|partial|unknown, forwarded_origin_keys: list[OriginEventKey]}`. Adapter/normalizer code sets this descriptor. The model cannot claim complete dependencies or create root IDs. A host adapter may set `complete` only for its certified bounded experiment domain; arbitrary shell runs normally remain partial/unknown.

Normalize an executable by the adapter's registered executable identity and preserve the actual argument array; replace only registered incidental run-ID fields. Do not remove arbitrary flags, change shell semantics, or sort order-sensitive arguments. Sort dependency keys only for canonical hashing. Artifact identity includes its registered workspace/source and path/property; equal byte digests for different unrelated objects do not establish one source.

`RootClass = {root_class_id: Id, canonical_origin: OriginEventKey, member_origin_keys: list[OriginEventKey], equivalence_reasons: list[origin_identity|provenance|artifact_snapshot|experiment_signature|same_authority|unknown_dependencies]}`. Class IDs use `root_` + SHA-256 of the lexicographically least canonical origin key in the equivalence component. When newly discovered equivalence changes a representative, retain an alias and resolve it before counting; merges can reduce counts and trigger revalidation. Export/import preserves origin descriptors and aliases rather than generating new roots. Never use a destination installation ID, delivery count, or timestamp as an independence discriminator.

`independent_roots(ctx, evidence, *, proposition_key)` resolves stored provenance, rejects cycles and ineligible roots, applies SYSTEM_SPEC §7.1.1 equivalence rules, and returns canonical class IDs. Missing descriptors may support a narrow observed report but cannot add an extra corroborating class. Same-user declarations about the given proposition collapse into one authority class; uncertain proposition equivalence cannot justify increased strength. Root classes are counted only for support links; contradictory outcomes remain attached and block corroboration until resolved. Ingestion registers each eligible root event (an authenticated user statement or a certified tool result without `derived_from`) with its exact equivalence tokens in the event's own transaction, so classes are the store-wide transitive closure; a merge of counted classes advances guidance epoch and queues revalidation of the live claims citing them. Lineage code derives descriptors from stored envelopes when an adapter sets none, and never treats memory telemetry, assistant text, a call without its result, a self-reporting command (`echo`/`printf`) or forwarded subagent output as a root (decision 0010).

### 6.2 Review batch identity

`ReviewBatch = {batch_id: Id, origin_job_id: Id|null, review_job_id: Id, candidate_refs: list[RecordRef], candidate_digests: dict[Id,Digest], evidence_digest: Digest, prompt_digest: Digest, evidence_index: list[ReviewEvidence], read_set: ReadSet}`. Code persists this immutable snapshot before launch; operator submissions use null `origin_job_id` and their declaration source as job input. `ReviewEvidence = {evidence_id: Id, link: EvidenceLink}` assigns compact, batch-local reference IDs (`evd_` + SHA-256 of the canonical link, decision 0009) to exact locators/typed evidence. The request preparer builds and persists the snapshot under the review job's lease fence before any reservation. The reviewer cannot add IDs or change their mapping. Batch IDs are `batch_` UUIDs; retries of an unchanged persisted batch reuse its ID, while external candidate/evidence changes require a fresh snapshot and revision-checked requeue. Evidence-expansion rounds keep the same job ID and cumulative two-round allowance, but persist a new batch snapshot ID/read set when selected evidence changes; expansion never resets its own budget.

Stable candidate order partitions one extraction job's candidates at eight candidates, 96 KiB total serialized input, or the 9,000-byte response budget. The response schema reserves at most 768 bytes per compact assessment operation and 2,000 bytes for the enclosing body, fitting eight assessments below 9,000 bytes. A terminal review uses only `assess_claim`; evidence-expansion responses use only bounded `request_evidence` operations and do not activate candidates. Larger evidence needs follow the existing two-expansion limit. Candidate-specific revisions, evidence, scope, and conditions are checked again before applying an assessment; a blanket batch verdict is invalid. The partitions are computed when the application that wrote the candidates schedules their review jobs (same transaction, stable proposal order, the exact serialized request size), and a candidate too large to review alone is recorded `deferred` instead of being truncated. The review request's read set names no candidate revision: each assessment is checked against its own candidate's snapshot digest and current head (`candidate_stale`), so one changed candidate cannot requeue the others; a candidate no longer at its scheduled revision is left out of the batch (its newer revision has its own review). Review evidence is never trimmed to fit (decision 0011).

## 7. Provider request and response

`ModelRequest` contains `request_schema: 1`, `job_id`, `purpose`, `prompt_version`, `instruction_text`, `events`, `episodes`, `claims`, `task_state`, `boundaries: list[BoundaryContext]`, `allowed_evidence_refs`, `read_set`, `output_schema`, `review_batch: ReviewBatch|null`, and `limits`. Each source collection is a bounded selected slice of the job's own installation; the serialized request is at most 96 KiB, bulky successful output being dropped first (decision 0009). All source text is framed as data; `instruction_text` is the job's pinned prompt version. Provider input does not contain credentials or executable adapters. `BoundaryContext = {candidate: TaskBoundaryCandidate, binding_revisions: dict[Id, Revision]}` presents a pending boundary candidate with the binding revisions its events have now, which a `resolve_task_binding` proposal names as `expected_binding_revisions`. `output_schema` lists exactly the purpose's permitted operation kinds and payload shapes.

`ModelResponse` contains `response_schema: 1`, `operations: list[ProposedOperation]`, `no_op_reason: str|null`, `usage: UsageReport`, and the adapter-owned `malformed: list[MalformedOperation]` (decision 0007). Provider adapter code appends resolved provider/model metadata; the model cannot vouch for that metadata. `MalformedOperation = {index: int, local_ref: str|null, depends_on: list[str], reason_code: str}` records one operation that failed strict validation or is not permitted for the purpose; its raw text is not retained, and `local_ref`/`depends_on` are kept only when they were themselves valid.

`UsageReport = {input_tokens: int|null, output_tokens: int|null, estimated_input_tokens: int, estimated_output_tokens: int, provider_request_id: str|null, duration_ms: int}`.

The model has no built-in tools. It may return `request_evidence` operations; the controller resolves them against allowed local evidence and calls the model again within the expansion budget. It cannot issue live arbitrary tools through that schema.

### 7.1 Proposed operations

Every operation has `local_ref: str`, `kind`, `depends_on: list[str]`, `target: RecordRef|null`, `payload: JsonObject`, `evidence: list[EvidenceLink]`, and `reason: str`.

| Kind | Payload / applicability |
|---|---|
| `update_task` | Explicit field patches plus task ID and expected revision |
| `resolve_task_binding` | `TaskBindingProposal`; code checks ranges, pending pairs, and expected binding revisions |
| `create_episode` | Episode body with existing source IDs |
| `revise_episode` | Explicit episode patch and expected revision |
| `propose_claim` | Claim body; IDs, strength, status, authority, and timestamps assigned/validated by code |
| `assess_claim` | Review-only: `{batch_id, candidate_ref, verdict: supported\|revise\|reject, objections: list[str], evidence_ids: list[Id]}`; at most two objections of 160 UTF-8 bytes each and two batch evidence IDs; whole serialized operation ≤768 bytes, empty `reason`/`evidence`/`depends_on`, target equal to candidate_ref; no proposition mutation |
| `attach_evidence` | Existing claim revision plus proposed supporting/contradicting refs |
| `revise_claim` | Supported proposition/scope/condition/dependency changes, and `retry_conditions: list[SupportedText]` for a failure lesson (decision 0012); the revision is a candidate reviewed again |
| `change_claim_status` | Requested status, replacement local ref or existing ref, and evidence |
| `request_evidence` | Enumerated `file_excerpt\|record\|dependency_diff\|event_range` request within allowed refs |
| `no_op` | Reason; no mutation |
| `create_task` | Controller-only (typed reduction): code-allocated `task_id`, `title`, `reason: new_session\|host_reset`, `session_ids`, `started_at` |
| `bind_events` | Controller-only: `task_id`, `expected_revision`, unbound `event_ids` (≤256), optional `boundary_id`, typed `patches` (≤256) citing the events; code derives `session_ids`, `last_activity_at` and reactivation |
| `record_boundary` | Controller-only: one pending `TaskBoundaryCandidate` |

The provider schema enumerates permitted payload keys for each kind and job purpose. `assess_claim` is valid only for the assigned review batch; it materializes one `ReviewAssessment` with resolved evidence links and code-assigned provenance. `supported` requires at least one valid evidence ID; `revise`/`reject` may cite none with a missing-evidence objection; `reject` with the exact `review_capacity` objection may also have an empty evidence-ID list because it makes no substantive evidence judgment. Duplicate, missing, or foreign candidate assessments cannot activate a claim. The review request contains only the candidate proposition/scope/conditions and permitted original evidence; remove all proposal `reason` keys and extractor rationales before serialization. Evidence quotations are not modified. It cannot return operator forget, policy changes, provider changes, shell execution, instruction-file edits, export, or cross-project import. A malformed operation fails its atomic dependency group; independent valid groups may continue. The decoded body is therefore validated in two levels: the byte cap and the enclosing object (`operations`, optional `no_op_reason`, no other keys) are strict and reject the whole body; each operation is then validated strictly on its own. Atomic groups are the connected components of the `depends_on` graph, applied in topological order inside one transaction, each within its own savepoint; a local ref named in a payload (such as `replacement_local_ref`) must also appear in `depends_on`. Ordinary proposed patches may not modify immutable source text, origin IDs, evidence-root identity, or capture authority.

`ReadSet` contains entity revisions, registered workspace identity, relevant branch/HEAD/config fingerprints, policy revision, and tombstone epoch. It is rechecked before applying. A changed unrelated record does not automatically invalidate the proposal; a changed consulted record, source scope, policy, or tombstone epoch does. Historical event/commit coordinates are immutable source context, not a requirement that the current checkout still have the old HEAD. Only live evidence read during curation requires current fingerprint equality. Historical curation may finish after a branch switch when its evidence is preserved and its resulting scope is still correctly bound.

`AdmissionDecision = {local_ref: str, outcome: apply|review_required|candidate_only|reject|requeue, reason_code: str, resolved_operation_id: Id|null}`.

## 8. Jobs, application, and forgetting

`Job` contains `job_id`, `kind`, `state: pending|leased|waiting_review|waiting_budget|completed|failed|cancelled`, `input_refs`, `input_digest`, `policy_revision`, `prompt_version`, `idempotency_key`, `priority`, `due_at`, `attempt`, `lease_owner`, `lease_generation`, `lease_until`, `proposal_ref|null`, and bounded `last_error_code`, `budget_pool: ordinary|protected|none`, `review_priority: correction_or_declaration|ordinary|null`, and optional `trigger_ref` for a debounced boundary.

Review priority is assigned by code from operator-correction/declaration provenance or an extracted decision/preference candidate with eligible direct user evidence under the declaration checks. It grants scheduling priority only, not confirmed authorship or admission. A batch with any such candidate uses `correction_or_declaration`; remaining candidates from that same extraction may stay in the bounded batch. Priority review still consumes the existing protected pool then ordinary capacity, never bypassing exhausted limits. Within a priority band order by due time then job ID; the complete model order is SYSTEM_SPEC §6.2.

`FailureTrigger = {trigger_id: Id, task_id: Id, failure_event_id: Id, action_family_digest: Digest|null, subsequent_event_count: int, due_at: UtcTime, state: pending|resolved|due}`. Task 9 owns task-local debounce; six relevant events or ten minutes makes an unresolved trigger due. A certified same-task/family success before that point resolves it. A null family is never resolved by success and becomes due only by time/count; lexical resemblance is insufficient. The reserved `expected_red` field does not exclude triggers in v1. Determinism (decision 0011): triggers are examined once per event in commit order after typed reduction, inside the ingest transaction, using event observation time (occurred, else recorded); relevant events are explicit user messages, artifact changes and completed certified tool results of the same task (the resolving success is not counted); a repeated failure of a known family joins its pending trigger, a null-family failure starts its own; a due trigger schedules one `extract_claims` job naming it in `trigger_ref`; the worker's sweep makes a pending trigger due once its ten minutes passed with no event, and a success observed before the due point but ingested later still resolves a time-due trigger whose extraction is not yet leased.

`review_candidates` handles the one persisted ReviewBatch assigned to `job`; its ordered `claim_ids` must match that batch. The scheduler partitions larger extraction output before creating review jobs; each invocation returns one ModelResponse.

`action_family_digest` hashes canonical `[workspace_id, cwd_path, registered_tool, registered_executable, normalized_ordered_argv]`, excluding task ID, dependency values, timestamps, and incidental run IDs removed only by the certified parser. The working directory is normalized relative to the registered workspace (`.` for its root); unknown working directory or parse gives null, so identical commands in different packages cannot falsely resolve one another. Task-local trigger identity includes task ID separately. Failure claim heads index this digest so later sessions can locate relevant lessons.

`FailureRecheck = {claim_ref: RecordRef, success_event_id: Id, supporting_failure_event_id: Id|null, reason: later_success|order_unknown, action_family_digest: Digest}`. On ingestion, a certified success with known matching family and compatible workspace/scope is compared with the latest supporting failure's certified source order; wall-clock receipt order alone is insufficient. For known later success, attach `context` evidence, revise freshness to `needs_revalidation`, advance guidance epoch, and enqueue/coalesce revalidation in the same transaction. Ambiguous order can conservatively suspend with `order_unknown`; known older events, duplicate replay, and imports do not create a later-success trigger. This does not automatically assert contradiction or falsify a historical failure. A null last-supporting-failure reference permits only an uncertainty trigger, never a fabricated chronology. Persist trigger metadata in the revalidation job/input refs and revision audit; no separate executable action is authorized. Certified order (decision 0012) is, in this order, the adapter's source sequence within one host session and origin stream, the adapter-reported occurrence time of both events, or the capture time of two live synchronous host hooks of one certified adapter; never commit or processing order. Each trigger is one `claim_rechecks` row (`rchk_` ID over claim, reason and observation; reasons `later_success|order_unknown|dependency_changed|source_conflict|review_due|consolidation`; states `pending|deferred|cleared` with an outcome code), its audit an `operations` row of kind `recheck` whose causal root is the observation; a candidate's rechecks wait `deferred` for the transaction that activates it. A revalidation result settles a recheck only when its read set names the recheck's observation and the still-current claim revision; a plain keep never settles a `later_success` of a failure lesson (`retain_requires_retry_condition`) or an unresolved source conflict.

`BudgetReservation` (`rsv_` reservation and `inv_` invocation IDs, one row per invocation in `provider_usage`) records job/invocation ID, UTC day, purpose, ordinary/protected allocations, `estimated_input_limit`, `estimated_output_limit`, `max_wire_stdout_bytes` (256 KiB), `max_response_body_bytes` (`3 × estimated_output_limit`), `max_stderr_bytes` (64 KiB), reported usage, local estimated usage, and reserved/charged state. Purpose defaults are 1,500 output estimates for task narrative, 8,000 for episode/extraction, and 3,000 for review/revalidation. Bound the wire while reading; unwrap only the certified host envelope, then count the decoded body's original UTF-8 bytes before DTO validation. Never compact or clip to pass. Budget pools/borrow direction and mixed-call arithmetic are SYSTEM_SPEC §6.3. Reserve before launch, count failures/expansions, retain interrupted unknown usage, and release only known unused reservations. Lease fencing prevents two workers spending the same allowance. A job that cannot reserve waits in `waiting_budget` with `last_error_code = budget_exhausted:<pool>.<dimension>` (`ordinary.` or `protected+ordinary.`); a pending model job with no certified backend shows `provider_unavailable` (decision 0006).

The idempotency key hashes kind + sorted exact input revisions + policy revision + prompt version + tombstone epoch. Operation IDs derive deterministically from job ID, persisted proposal digest, and local operation ref. The database has unique constraints on both keys. Duplicate application returns the original result without incrementing support or revisions again. The persisted proposal digest covers the operations, no-op reason and malformed entries, not usage or provenance; the persisted proposal also stores the `ReadSet` it was produced under. The application is recorded as one `operations` row (kind `apply_proposal`, or `apply_service` for a service writer) under the reserved ref `@apply`, holding the `ApplyResult`; a committed application returns it before any lease check, while new application requires the current lease generation. A revision or read-set conflict applies no operation of the proposal: a job is cancelled (`reevaluation_requeued`) and one coalesced re-evaluation job of the same kind is enqueued with current input revisions; after 3 re-evaluations along one chain the job fails with `reevaluation_limit`. A service writer receives `revision_conflict`. Exact duplicate claims are detected from canonical proposition, scope, conditions, and evidence-root identity; they reuse the existing head or attach genuinely new evidence. Semantic near-matches only generate comparison candidates and never imply confirmation or automatic merging.

`ApplyResult = {operation_ids: list[Id], changed_refs: list[RecordRef], decisions: list[AdmissionDecision], store_revision: int, requeued_job_ids: list[Id]}`. A worker supersession of active guidance naming a candidate replacement is admitted `review_required` (`replacement_pending_review`) and held in `pending_supersessions`; the replacement's supported review activates it and supersedes the target in one transaction, or marks the hold `stale` when the target moved (decision 0012).

`UndoPreview = {operation_id: Id, state: clean|partial|conflicted|nothing_to_undo, compensations: list[UndoChange], conflicts: list[UndoConflict], preview_digest: Digest}`; `UndoChange = {action: restore_fields|retire|remove_relation, ref: RecordRef|null, fields: list[str], relation: [source_id, target_id, relation]|null}`; `UndoConflict = {ref: RecordRef, undone_revision: int, current_revision: int, fields: list[str], reason: str}`. A preview restores only fields whose current value still equals what the undone operation wrote, reports every field a later revision changed as a conflict, retires a record the operation created (claims and episodes become `archived`) while its status is unchanged, and removes relations it added. The digest covers the compensation, conflicts and current head revisions; `--apply` recomputes the preview and requires the same digest, then appends revisions as one `undo` operation. Undo never restores a snapshot or removes intervening history (decision 0007).

`ForgetRequest` is operator-only: `selector: ForgetSelector`, `preview_digest: Digest`, `reason: str|null`. `ForgetSelector` enumerates record IDs, task IDs, source ranges, or a saved exact query result; it is not executable text. Preview lists affected records, derivatives, backups, and exports. Apply requires a matching current preview digest. It returns `ForgetResult = {operation_id: Id, purge_state: completed|cleanup_pending, purged_count: int, quarantined_count: int, tombstone_epoch: int, backup_state: verified|unavailable|pending, new_backup_id: Id|null, deleted_backup_ids: list[Id], external_copy_ids: list[Id], replay_suppression_coverage: JsonObject, error_codes: list[str]}`. A failed replacement backup does not reverse successful forgetting or preserve affected older backups. Remaining-root reconstruction is a later admitted job, never part of the purge transaction.

`Tombstone` stores target IDs, source identity/range digests, created time, epoch, and deletion scope. It contains no deleted prose. Replay of known source ranges is suppressed; semantically similar content from a truly new user statement is new evidence and can be admitted. Do not claim the engine can detect every paraphrase of forgotten content without retaining that content.

## 9. Context, retrieval, and feedback

`ContextQuery = {session_id: Id, task_id: Id|null, workspace_id: Id, purpose: session_start|prompt|pre_action|compact_restore|manual, text: str, action: ActionDescriptor|null, environment: EnvironmentValues, max_estimated_tokens: int|null, branch_ref: str|null}`. `branch_ref` is the current branch, consulted only by explicit `branch_ref` conditions; null is unknown (decision 0010).

`ActionDescriptor = {cwd_path: str|null, tool: str, action_kind: str|null, executable: str|null, argv: list[str]|null, paths: list[str], raw_digest: Digest|null, parse_status: exact|conservative|unknown, shell: str|null}`. The initial adapter-assigned action vocabulary is `read|write|delete|test|build|publish|version_control|other|unknown`; a missing kind behaves as unknown. Parser uncertainty is retained; unparsed shell text is not executed by retrieval.

`ContextPacket = {packet_schema: 1, project_id: Id, installation_id: Id, store_revision: int, guidance_epoch: int, policy_revision: int, tombstone_epoch: int, generated_at: UtcTime, purpose: str, items: list[ContextItem], omitted_count: int, estimated_tokens: int, pre_action_substitution_tokens: int, degraded_reasons: list[str]}`.

`ContextItem = {ref: RecordRef, text: str, advice: context|caution|conflict, basis: str, scope: Scope, applicability: true|false|unknown, freshness: str, why: list[str], evidence_refs: list[RecordRef], conditions_text: str|null, retry_text: str|null}`. Applicability values are the JSON strings `"true"`, `"false"`, and `"unknown"`, not mixed booleans and strings.

`pre_action_substitution_tokens` is zero except when a certified prompt path substitutes for unavailable pre-action injection and actually includes an eligible caution. It is the estimate for that caution portion, at most 400. An ordinary prompt then permits at most 1,000 other estimates plus that portion, 1,400 total. The bonus is not per item, repeated attempt, or queued tool. A restoration-purpose packet keeps its total 2,000 cap; caution allocation fits inside it. A caller-supplied lower maximum remains binding. Delivery receipts and scratch charge the complete `estimated_tokens`, including any substitution, against unchanged-session limits/suppression.

`ContextItem.why` is nonempty. Element 0 is a stable `ReasonCode`: `task_continuity|exact_action_match|dependency_match|path_match|lexical_match|explicit_query|conflict|revision_change|compaction_restore|recent_observation|tentative_context`. Remaining elements are bounded human-readable explanation. Evaluation consumes the code, not parsed prose.

Suppression keys are `(record_id, revision, condition_digest, purpose_class)` plus the session ID. `condition_digest` covers actually consulted current dependency values/applicability, not just branch name. A change invalidates an old suppression match even when the claim revision has not yet changed. Restorations are separately keyed by the unique compaction event ID. Unknown/unreadable current conditions cannot preserve an old caution.

`DeliveryReceipt` contains delivery/attempt ID, host/session/task identity, packet digest, emitted record revisions with condition digests, purpose, fence store revision, guidance/policy/tombstone epochs, generation time, emission time, and estimated tokens plus `pre_action_substitution_tokens`. Receipt state is `emitted|uncertain`; only `emitted` proves successful local stdout emission. Neither state proves model consumption. Canary observations are separate certification evidence. Hook receipts are ingested from `memory_delivered` spool events; the hook never inserts the deliveries table. An outcome link records observed follow-up events. Its outcome label is `unknown|acknowledged|challenged|action_changed|task_succeeded|task_failed`; only observed evidence assigns the latter labels. Agent obedience alone does not establish memory correctness.

## 10. Persistence schema

Implement ordered SQL migrations with explicit indexes. JSON fields use canonical serialization and validated DTOs; hot filters have typed columns. Foreign keys reference local IDs. Do not rely on SQLite JSON extensions for correctness. FTS is optional.

| Table | Key and critical contents |
|---|---|
| `installation_meta` | Singleton IDs, engine/schema versions, store revision, guidance epoch, policy revision, tombstone epoch |
| `workspaces` | Workspace ID, canonical root, branch metadata, attachment state |
| `sessions` | Session ID, adapter/host ID, workspace ID, registered sources, lifecycle state |
| `capture_sources` | Source registration ID, exact path/identity, durable and ingested cursors, coverage |
| `source_conflicts` | Conflict ID; unique adapter/source key/digest, original event ref, scrubbed conflicting payload, coverage, resolution state |
| `root_classes`, `root_members`, `root_aliases` | Canonical origin identity, equivalence reasons, imported descriptors, and merged-class aliases |
| `root_event_members`, `root_tokens` | Eligible root event → origin key, observation kind, authority actor, outcome, resolution; exact equivalence token → class (schema 4, decision 0010); identities and digests only |
| `task_boundaries`, `task_binding_revisions`, `task_binding_heads` | Boundary candidates and versioned event-to-task assignments; heads carry the event's commit sequence and session (schema 3) |
| `tool_calls` | Adapter + `tool_call_id` → first call and first result event (pair joins across splits and sessions) |
| `working_cursor`, `working_sessions`, `working_tasks` | Typed reducer bookkeeping: last reduced commit sequence, per-session detection state, per-task observed clusters and open episode range; derived, never served |
| `failure_triggers` | Pending/resolved debounced boundaries and deterministic action-family identity; schema 5 adds failure sequence/time, due reason, resolving event and scheduled extraction job (decision 0011) |
| `trigger_cursor` | Last reduced commit sequence the failure debounce examined (schema 5) |
| `environment_observations` | Allowlisted value/fingerprint, workspace/executable binding, source ref or config revision, freshness |
| `review_batches` | Immutable candidate revision/digest snapshots, evidence index, origin/review job IDs, read set |
| `review_requests`, `review_outcomes` | Review job → origin job or submission, origin class and partition; per-candidate-revision outcome and exact reason code (schema 5, decision 0011); IDs and codes only |
| `events` | Event ID; unique adapter/source key; digest, sequence, type, authority, payload, retention time, and payload state (`available`, `capsule_only`, `expired`, `forgotten`) |
| `task_revisions`, `task_heads` | `(task_id, revision)` bodies and current pointers |
| `episode_revisions`, `episode_heads` | `(episode_id, revision)` bodies and current pointers |
| `claim_revisions`, `claim_heads` | `(claim_id, revision)` bodies and current pointers; indexed status, kind, freshness |
| `evidence_links` | Owner record revision, source reference, relation, root identities |
| `evidence_capsules` | Capsule ID, exact preserved content, lineage, digest |
| `dependencies` | Claim revision, dependency kind/key/fingerprint; index by dependency key and by claim-dependency record (schema 6) |
| `claim_rechecks` | Why a claim needs revalidation: claim, reason, triggering observation, state, outcome code, job, causal root (schema 6, decision 0012); IDs and codes only |
| `pending_supersessions` | Explicit replacements of active guidance held until the replacement's review: replacement, target and its revision, state (schema 6) |
| `intent_questions` | One content-free open question per unresolved conflict of user declarations (claim IDs, proposition key, state) (schema 6) |
| `artifact_writes` | Certified writes/deletions by workspace path and commit sequence: the file dependency index's change source (schema 6) |
| `planner_state` | The deterministic planner's consolidation clock (schema 6) |
| `relations` | Source/target IDs and typed relation |
| `jobs` | Job ID, unique idempotency key, state, due time, lease generation |
| `proposals` | Proposal ID, job ID, input/read-set digest, output body, proposal digest, persisted read set, retention time |
| `operations` | Unique operation ID, atomic group ID, actor, inputs, changed revisions, reason, local ref, proposal digest; also the per-proposal application record (`@apply`), re-evaluation records and undo operations |
| `revision_chain` | Full profile: sequence, previous hash, operation/row digests, purge markers, epoch, entry hash; reserved/unpopulated in preview, not reported verified |
| `privacy_operations` | Purge/cleanup/backup phase, remaining work, protected new epoch, and resumable status |
| `deliveries`, `outcome_links` | Emitted revisions, session budget accounting, subsequent evidence |
| `tombstones` | Suppression targets, source digests, epoch; no prose |
| `imports`, `exports`, `backups` | Artifact IDs/digests, origins, schemas, privacy/retention metadata |
| `provider_usage` | Invocation reservations, actual/estimated usage, errors, provider/model IDs |
| `context_views` | Pre-rendered bounded item bodies keyed by workspace/task/purpose, source snapshot revision, guidance/policy/tombstone epochs, precomputed condition results and exact consulted input fingerprints; direct fallback still filters live heads and applicability |
| `lexical_index` / FTS tables | Disposable candidate index tied to store revision |

Migration 1 creates the full minimal schema; later tasks populate features incrementally. Each table carrying record bodies must participate in forgetting. Store backups include the tombstone ledger; a separate latest ledger copy enables suppression after restore of an older backup.

## 11. Component interfaces

The following are implementation signatures, not suggestions. Define DTOs in `src/recalith/contracts/`. Functions may be methods internally, but exported signatures and semantics must remain consistent. `Path`, `Iterable`, and `Sequence` are Python standard types; DTO names below are defined in this document or this section.

```python
resolve_installation(root: Path, *, actor: Actor) -> InstallationContext
initialize_installation(root: Path, config: ProjectConfig) -> InstallationContext
capture(ctx: InstallationContext, events: Sequence[EventEnvelope]) -> CaptureReceipt
ingest_ready(ctx: InstallationContext, *, limit: int = 100) -> IngestResult
open_store(ctx: InstallationContext, *, readonly: bool = False) -> Store
lease_next(ctx: InstallationContext, *, owner: str, now: UtcTime) -> Job | None
apply_proposal(ctx: InstallationContext, job: Job, response: ModelResponse) -> ApplyResult
evaluate_operation(ctx: InstallationContext, operation: ProposedOperation, read_set: ReadSet) -> AdmissionDecision
    # Task 5 helpers (decision 0007): persist before apply; service writes; compensating undo.
persist_proposal(store: Store, job: Job, response: ModelResponse, read_set: ReadSet, *, now: UtcTime) -> Id
apply_operations(ctx: InstallationContext, operations: Sequence[ProposedOperation], *, read_set: ReadSet, submission_id: Id) -> ApplyResult
apply_in_transaction(txn, ctx: InstallationContext, operations: Sequence[ProposedOperation], *, read_set: ReadSet, submission_id: Id, now: UtcTime, kind: str = "apply_reduction") -> ApplyResult
    # Task 6 (decision 0008): the same application inside a caller's write transaction (typed reduction in its fenced ingest job).
preview_undo(ctx: InstallationContext, operation_id: Id) -> UndoPreview
apply_undo(ctx: InstallationContext, operation_id: Id, *, preview_digest: Digest) -> ApplyResult
propose_task_boundaries(ctx: InstallationContext, events: Sequence[EventEnvelope]) -> list[TaskBoundaryCandidate]
resolve_task_binding(ctx: InstallationContext, proposal: TaskBindingProposal) -> ApplyResult
reduce_task(ctx: InstallationContext, task_id: Id, events: Sequence[EventEnvelope]) -> TaskState
independent_roots(ctx: InstallationContext, evidence: Sequence[EvidenceLink], *, proposition_key: JsonObject) -> set[Id]
    # Return canonical root-class IDs after resolving all aliases; never raw event IDs.
    # Task 8 (decision 0010): core.lineage.resolve(view, evidence, proposition_key=) -> Lineage adds contradiction/unstable classes,
    # unresolved and conflicted roots, cycles and corroboration_blocked; registration runs inside ingest_ready.
evaluate_conditions(conditions: Sequence[Condition], query: ContextQuery) -> str
    # Exactly "true" | "false" | "unknown"; core.conditions also provides scope_applicability, applicability, in_scope,
    # dependency_applicability and advice_for (decision 0010).
resolve_evidence(ctx: InstallationContext, link: EvidenceLink) -> ResolvedEvidence
build_episode(ctx: InstallationContext, task_id: Id, event_ids: Sequence[Id]) -> Episode
prepare_model_request(ctx: InstallationContext, job: Job) -> ModelRequest
    # Task 7 (decision 0009): keyword options store=, rounds= (evidence-expansion responses), now=, timeout_seconds=;
    # raises PrepareFailed(code, final) or NothingToPrepare (the lane cancels the job without a call).
complete(request: ModelRequest, config: ProviderConfig) -> ModelResponse
    # Only a currently certified route (route_status); the curator marker names config.installation_id.
review_candidates(ctx: InstallationContext, claim_ids: Sequence[Id], *, job: Job) -> ModelResponse
    # Task 9 (decision 0011): keyword options store=, launch= (default: the certified route through complete), now=;
    # snapshots or reuses the job's batch under its lease fence; claim_ids must be its candidates in order;
    # without a route raises capability_unavailable and changes nothing. Budget stays with the model lane.
revalidate_dependents(ctx: InstallationContext, changes: Sequence[DependencyChange]) -> list[Id]
    # Task 10 (decision 0012): keyword options store=, now=; marks live claims whose current revision depends on a changed
    # key (a new fingerprint equal to the recorded one preserves applicability), then their claim dependents (bounded,
    # cycle-safe), and enqueues their coalesced revalidation; returns the marked claim IDs. Ingestion applies the same
    # index to certified writes and environment observations, and FailureRecheck, in the event's own transaction.
retrieve(ctx: InstallationContext, query: ContextQuery) -> list[ContextItem]
compile_context(ctx: InstallationContext, query: ContextQuery) -> ContextPacket
record_delivery(ctx: InstallationContext, packet: ContextPacket, session_id: Id) -> DeliveryReceipt
declare(ctx: InstallationContext, kind: str, statement: str, scope: Scope) -> ApplyResult
correct(ctx: InstallationContext, claim_id: Id, *, expected_revision: int, statement: str) -> ApplyResult
preview_forget(ctx: InstallationContext, selector: ForgetSelector) -> ForgetPreview
apply_forget(ctx: InstallationContext, request: ForgetRequest) -> ForgetResult
backup(ctx: InstallationContext, destination: Path) -> ArtifactManifest
restore(ctx: InstallationContext, source: Path, *, expected_digest: Digest) -> RestoreResult
export_memory(ctx: InstallationContext, selection: ExportSelection, destination: Path) -> ArtifactManifest
import_memory(ctx: InstallationContext, source: Path, *, expected_digest: Digest) -> ImportResult
import_breadcrumbs(ctx: InstallationContext, source: Path) -> ImportResult
upgrade(ctx: InstallationContext, wheel: Path, *, expected_digest: Digest, release_profile: str | None = None) -> UpgradeResult
health(ctx: InstallationContext) -> HealthReport
run_worker(ctx: InstallationContext, *, mode: str) -> int
```

`ResolvedEvidence` contains original source identity, exact preserved text/typed observation, original locator, availability, canonical root-class IDs, and integrity status. A mismatch is an admission error, not a best-effort quote. `resolve_task_binding` delegates a persisted binding operation through the same revision/fencing path as other mutations; it does not bypass Task 5. `declare` accepts only guarded operator actors and kind `decision|preference`, records the exact statement, and returns a candidate plus queued review under the same no-bypass declaration policy; it is absent from agent MCP tools. `correct` atomically invalidates the expected current target, advances guidance epoch, and creates a replacement candidate linked to the correction source; it returns that immediate application result and the queued review. It does not wait for a provider. Replacement admission requires original-statement review and follows the target's type/evidence policy; it does not relabel a fact or failure as an observed fact merely because an operator proposed it. Both use the same guarded transport and revision checks. `record_delivery` is a service-side typed helper that serializes a receipt to the spool; ingestion owns the database row. The separate `hook_record_delivery` uses only the primitive fast-path implementation.

Auxiliary DTOs: `IngestResult` has accepted/duplicate/conflict counts, last store revision, and created job IDs. `ingest_ready(limit)` bounds the number of spool segments handled per call; each segment is ingested in one transaction with its cursor proposals and one deterministic `ingest` job for newly inserted events. `DependencyChange` has kind/key/old/new fingerprints and supporting event ID. `ArtifactManifest` has artifact ID/type, schemas, identity, creation time, file digests, and tombstone epoch. `RestoreResult` has applied schema, restored revision, preserved tombstone epoch, and suppressed-record count. `ImportResult` has created/updated/duplicate/disputed/rejected counts and resulting refs. `ForgetPreview` has affected refs/artifact IDs and preview digest. `HealthReport` has `release_profile: claude_preview|full`, `capabilities: dict[str, CapabilityState]`, worker state, coverage gaps, job/budget summaries, `retention_summary: RetentionSummary`, and `autonomous_ready: bool`. `RetentionSummary = {pinned_payload_bytes: int, unpinned_payload_bytes: int, live_owner_count: int, free_disk_bytes: int|null, deferred_compaction_count: int}` reports nonnegative measured counts; null free space means unavailable, never unlimited. `CapabilityState = {state: healthy|degraded|unavailable, required: bool, reason_codes: list[str], certified_version: str|null, certified_at: UtcTime|null, coverage: JsonObject}`. Register separate capture/inference/admission/recovery/forget/operator-guard/start-delivery/prompt-delivery/pre-action-delivery/compact-delivery capabilities, plus every deferred feature in SYSTEM_SPEC §1.2. Start and prompt are required; the latter two delivery paths are optional. Missing required capability makes readiness false. Preview can be operationally ready with explicitly unavailable deferred features; it cannot claim full evaluation completion.

`UpgradeResult = {operation_id: Id, source_profile: str, target_profile: str, source_engine: str, target_engine: str, state: not_activated|activated|rolled_back|recovery_required, preserved_installation_id: Id, verified_backup_id: Id|null, baseline_digest: Digest|null, retained_pin_count: int, error_codes: list[str]}`. An early refusal or backup failure is `not_activated`; `verified_backup_id` is null until a backup has actually been verified. No migration or activation may proceed without that verified backup. The full-release installer can invoke the guarded upgrade against an existing preview context; the old preview binary may return unavailable. The transition never creates a new installation ID. It stages schema/chain baseline, retention defaults, capsule conversion or retained pins, capabilities, policy/guidance epochs and activation/rollback under exclusive maintenance, preserving the newest tombstones. Only `claude_preview→full` or a same-profile upgrade is supported; a request to downgrade full to preview is exit 6.

`OperatorTokenFile = {schema: 1, token_id: Id, secret: str, created_at: UtcTime}` is a private JSON file of at most 4 KiB containing at least 256 bits of generated entropy encoded as text. Reject extra fields, invalid identifiers or time, oversized input, and malformed secret encoding before use. A pre-init token is provisioned by an unmarked operator TTY or supplied to trusted automation out of band, not verified against a nonexistent installation. First init checks shape, ownership/permissions where available and explicit supplied intent, then stores its one-way verifier in the new installation; it must never overwrite a live store. Existing installations require a matching active local verifier. Token creation/revocation and later administrative use follow §12; no file contents enter events or provider requests. Revocation state is installation-local; deleting/replacing the provisioned bootstrap input is how the operator stops future bootstrap use, without a global token registry.

`ProjectConfig` owns the defaults in SYSTEM_SPEC and records whether retention values are profile defaults or explicit operator overrides; `ProviderConfig` contains explicit backend/model/auth-reference/executable/certification/limits, the owning `installation_id`, `expected_api_key_source`, `network_env_keys` and nonsecret `nonsecret_env` switches; it lives in the installation's private `.recalith/provider.json`. Its `ProviderCertification` is `certified` only for a complete live observation with checked background-use eligibility and records host version, executable digest, auth key names, expected auth source, report digest and invocation digest; any difference from the current route makes the route unavailable until recertified (decision 0009). `ExportSelection` is a list of exact record references with allowed fields, inclusion of related evidence capsules, and visibility. `Store` advances guidance epoch for any serving-relevant mutation, including support/root changes and evidence expiry, but not receipt/queue bookkeeping. It is a repository interface with explicit read transactions and `transaction(expected: ReadSet)`; transport layers do not receive raw SQLite connections. Exact internal SQL method names may follow repository conventions without changing the public operations above.

## 12. CLI and adapter wire contracts

All machine commands support `--json`; JSON stdout contains one object and no progress text. Human diagnostics go to stderr without source bodies. Ordinary exit codes: 0 success, 2 invalid input, 3 revision conflict, 4 unavailable capability, 5 storage failure, 6 policy refusal, 7 `not_captured` (durability acknowledgment was not obtained), 8 `capability_degraded` (partial requested capability). `installation_relocated` (a moved or copied checkout awaiting operator rebind/discard; decision 0003) also exits 4. `observe` returns 7 for rejected durability even when input was valid. A successful partial receipt identifies accepted event IDs explicitly; never retry them under new identities. Hook adapters always convert operational failures into the host's nonblocking response and expose the reason through health.

Global `--project PATH` selects the installation explicitly when the project launcher does not supply it. Administrative forms accept global `--operator-token-file PATH` for the permitted noninteractive workflows below; pass only the file path, never a literal secret argument. First init supports this option. Token create/revoke still require the unmarked controlling TTY and cannot use a token as its substitute.

Required command forms:

```text
recalith init --project PATH --profile coding|general --release-profile claude_preview|full
recalith status --json
recalith doctor [--full-integrity] [--probe-host HOST] [--probe-provider PROVIDER]
recalith worker start|stop|run --mode persistent|session
recalith integrate HOST [--autostart] [--shared]
recalith integrate HOST --remove
recalith declare decision|preference --statement TEXT --scope FILE
recalith observe --stdin
recalith context --purpose PURPOSE --session ID [--task ID] --stdin
recalith search QUERY [--history]
recalith show ID [--revision N]
recalith tasks|episodes|claims [--status STATUS]
recalith correct ID --expected-revision N --statement TEXT
recalith undo OPERATION_ID --preview
recalith undo OPERATION_ID --apply --preview-digest DIGEST
recalith forget --selector FILE --preview
recalith forget --selector FILE --apply --preview-digest DIGEST
recalith jobs list|retry JOB_ID
recalith backup --output PATH
recalith restore PATH --expected-digest DIGEST
recalith export --selection FILE --output PATH
recalith import PATH --expected-digest DIGEST
recalith import breadcrumbs --source PATH
recalith upgrade --wheel PATH --expected-digest DIGEST [--release-profile full]
recalith workspace attach PATH
recalith workspace rebind
recalith workspace discard-copy
recalith project fork
recalith operator-token create --output PATH  # also before init; no installation lookup
recalith operator-token revoke TOKEN_ID
```

**Agent-refusable command forms (exit 6 `policy_refused`):** `init` including `--release-profile`; `declare`; `correct`; `undo --apply`; `forget --apply`; all `import`/`restore`/`upgrade`/`integrate` forms, including upgrade `--release-profile full`; `workspace attach|rebind|discard-copy`; `project fork`; `worker start|stop|run`; `jobs retry`; `backup`; `export`; `operator-token create|revoke`; and `doctor --probe-host|--probe-provider` because probes launch external processes. Inspection, status, search, context, show, list, `doctor` without probes, and undo/forget previews remain read-only. `observe` stays an agent assertion on agent transports, never an administrative declaration. No command accepts `--actor operator`.

Apply marker refusal before feature dispatch or child-environment construction. Deferred administrative forms are still refused from an agent channel; unmarked deferred forms return 4 after their guard. Do not clear the caller's markers to pass a guard. Missing, unreadable, malformed, mismatched or locally revoked token files are exit **6 `policy_refused`**, not 2; invalid option syntax remains 2. A supplied bad token never falls back to TTY authorization.

| Administrative form | Unmarked controlling TTY | Unmarked noninteractive caller | Any registered host/worker/curator marker |
|---|---|---|---|
| `operator-token create --output PATH`, before or after init | Allowed; create a private standalone file; after init may register verifier locally | Refuse; use an operator/CI-provisioned token input rather than minting through this CLI | Refuse, even with token/TTY |
| `operator-token revoke TOKEN_ID` | Allowed against existing installation; revoke local verifier | Refuse | Refuse |
| First `init`, including `--release-profile` | Allowed; validate a token if supplied | Require explicit pre-provisioned token file; install its verifier in the new store | Refuse |
| Existing-install admin forms, including upgrade/profile transition | Allowed; a supplied token must validate | Require active matching installed verifier through token file | Refuse |

These are same-user friction controls, not identity authentication. The verified bootstrap entry point exposes pre-init token/init forms without requiring a global engine. Existing-store init is refused rather than resetting memory. In an IDE terminal carrying a host marker, use an OS terminal launched outside the host-agent tree; the error explains that route, with no marker-clearing override. `RECALITH_WORKER_INSTALLATION` and `RECALITH_CURATOR_INSTALLATION` identify only the corresponding engine-owned child roles; host markers include tested `CLAUDECODE`/`CLAUDE_CODE_CHILD_SESSION` and only verified equivalents for later hosts. A healthy existing-store audit captures content-free refused-attempt telemetry; before a store exists, return bounded refusal metadata without creating a store solely to log it. Audit failure still refuses the requested operation.

Internal registered adapter/controller calls use their own restricted actors for normal automatic operation; hook worker startup uses the registered internal spawn function and never the `worker` CLI (A73 permitted-start control); they cannot call `declare`, `correct`, or privacy/administrative methods by supplying an operator DTO. This is a service policy boundary tested through real public entry points, not a claim that Python code is inaccessible to the same OS user.

The project-relative launcher supplies `--project` internally after installation. Host hooks invoke the pinned interpreter and a specific adapter entry point. MCP exposes `memory_context`, `memory_search`, `memory_show`, `memory_observe`, and `memory_feedback`; administrative commands are absent. MCP `memory_observe` is an agent assertion, not operator authority.

Each adapter normalizes incoming IDs and translates `ContextPacket` to that host's context format. The installed capability fixture must run the nonce protocol in SYSTEM_SPEC §9.3 for each injection path, including compaction recovery, and record observed assistant responses plus available host diagnostics. It must not claim direct visibility into an inaccessible model request. A hook returning successful JSON that the host ignores is not a passing delivery implementation.
