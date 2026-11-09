# Project Memory — Design Review

Oct 14, 2026 · @Jeremy Mccoy

## Verdict

The package is sound and unusually honest; build it. The epistemics (independent evidence roots, tri-state applicability, deterministic admission, content-free tombstones, fenced leases, idempotent operations) are the right core, and the five-document split with clear ownership is a good handoff. Nothing below argues for a different architecture.

The real risk is not correctness. It is that the system passes every blocking gate and is still too starved, too slow at the hook, or too fragmented to be useful: the 30-call daily budget is exhausted by mid-morning on an ordinary coding day, the 300 ms hook target is unrealistic with Pydantic on the hook path, task binding has no owner, and "independent root" is a required interface with only a prose definition. Those four are fixable in the documents before Task 1.

Two guiding changes run through the review: define the things the plan already names but no document pins down (roots, task boundaries, the delivery proof, the volatile/stable split, `relationship`, `assertions`), and reach a real host event stream earlier than Task 13 so the envelope is tested against reality before eleven tasks depend on it.

## Inconsistencies to resolve before implementation

The README says an implementer must stop when the documents disagree. These are the places where they will stop, so resolve them now. Each row names the owning document to change.

| # | Conflict or gap | Where | Resolution to adopt |
| --- | --- | --- | --- |
| 1 | Event ID derives from installation + adapter + source key, but an `event_identity_conflict` (same key, different digest) then has two payloads claiming one ID and no place to store the second | DATA\_CONTRACTS §1, §2.1 | Add a `source_conflicts` table keyed by (adapter\_id, source\_event\_key, payload\_digest). The original event keeps its ID; the conflict is a separate record with its own ID and is visible in health |
| 2 | Budget arithmetic: one episode = extract (1) + up to 2 expansion rounds + review (1) + its expansions = up to 6 invocations. 30/day ≈ 5 fully reviewed episodes. The "boundary to admitted knowledge ≤ 180 s" target is unreachable under normal load | SYSTEM\_SPEC §6.3 vs ACCEPTANCE §7 | Either raise the default (90/day with 1 concurrent is still bounded) or split budgets by job kind with preemption: ingest/task updates never consume model budget; review and revalidation have their own pools. Add "budget exhaustion rate on the live corpus" as a reported measure (see Evaluation) |
| 3 | "Volatile" vs "stable" claims get 30-day vs 180-day review, but nothing defines which is which | SYSTEM\_SPEC §6.3 | Deterministic rule: a claim with any `file`/`config`/`environment` dependency or a `failure_lesson` kind is volatile; `user_declared` decisions and preferences with no dependencies are stable |
| 4 | Claim kind `relationship` is listed but never defined | DATA\_CONTRACTS §5, SYSTEM\_SPEC §3.4 | Define it (a typed link between two subjects, e.g. "module X owns config Y") or drop it from v1. Dropping is cleaner; the `relations` table already covers record-to-record links |
| 5 | Tool payload has "optional `assertions`" and the `tool.reported_result` mapping depends on it, but its shape is undefined | DATA\_CONTRACTS §2.1, §6 | Minimal schema: `{kind: test_result\|exit_status\|parsed_value, identity: str, value: str, passed: bool\|null}`; adapters populate it only from parsed output they certify |
| 6 | Tracked `bin/` launchers and a hook entry in tracked `.claude/settings.json` point at an ignored `runtime/<release>/`. A collaborator who clones without bootstrapping gets a failing hook on every tool call | SYSTEM\_SPEC §2.2, Task 13 | Launcher exits 0 silently when the runtime is absent (one-time stderr hint). `integrate` writes hooks to `.claude/settings.local.json` (untracked) by default; `--shared` opts into the tracked file |
| 7 | `pmem integrate` has no uninstall form, but Task 13 requires one | DATA\_CONTRACTS §12 | Add `pmem integrate HOST --remove` |
| 8 | Three working names (`.project-brain/`, `project_memory`, `pmem`) for one thing | README | Pick one stem before the repository is named; it leaks into env markers, lock files and hook names |
| 9 | `Scope.environment` and `ContextQuery.environment` are open `dict[str,str]`; environment values routinely contain secrets and paths | DATA\_CONTRACTS §1.1, §9 | Make environment keys an adapter-registered allowlist (OS, arch, python/node versions, CI flag). Unregistered keys are dropped at capture, not scrubbed later |
| 10 | Capsules replace expired events, but `SpanLocator` offsets point into the event's field and nothing says who rewrites `EvidenceLink.locator` | DATA\_CONTRACTS §1.1, §6; SYSTEM\_SPEC §11 | Capsule stores the exact substring plus the original `(field, start, end, text_digest)`. Links are resolved by digest; the retention job rewrites `ref` to the capsule in the same transaction that expires the event |

## Major design gaps and proposed changes

Ranked by how much they would cost if discovered during implementation rather than now.

### 1. Define "independent root" precisely

`independent_roots()` is a required interface and `corroborated` strength depends on it, yet no document gives a rule an engineer can code without guessing. Proposed definition for SYSTEM\_SPEC §7.1 and DATA\_CONTRACTS §6:

- A root is an event with channel `user` or `tool`, authority `explicit_user` or `observed_tool`, and no `derived_from`. Assistant text, memory deliveries and curator output are never roots.
- Two roots are the same root class when any holds: one is in the other's provenance chain; both observe an artifact with the same content fingerprint (same file digest, same config value); or both are tool invocations with the same normalized executable, arguments and dependency fingerprints in the `ReadSet`. Rerunning an unchanged test on an unchanged tree is one class.
- Corroboration counts root classes, not roots. Subagent fan-out collapses into the parent's class (A16). A rerun after a dependency changed is a new class.

This makes `test_shared_subagent_source_counts_once` and `test_new_observation_after_retrieval_can_support` codable from the spec, and it closes the flaky-test loophole where three identical reruns would otherwise corroborate a causal claim.

### 2. Task binding has no owner

SYSTEM\_SPEC §3.2 says the host supplies a task ID "where available", but neither certified host supplies one. In practice every session becomes one task, and `reduce_task(ctx, task_id, events)` assumes the binding already happened. A10 (two concurrent tasks in one project) cannot pass without a component that does not exist in the plan.

Add a `working/segment.py` responsibility to Task 6: deterministic boundary candidates (explicit user pivot phrases, a new disjoint file cluster, idle beyond a threshold, a `/clear` or new session) create a *proposed* split; the next extraction job confirms, rejects or links it. Until confirmed, events attach to the current task with a `binding: provisional` flag so a later split can reassign them without a destructive rewrite. Add an over-fragmentation measure to the evaluation (see Evaluation) because "separate tasks, not a destructive merge" has a cost the gates do not see.

### 3. The hook path cannot afford Pydantic

P95 ≤ 300 ms including process startup, on Windows, is already tight for a bare interpreter in a venv. Importing Pydantic v2 plus the contracts package adds 100–250 ms cold. The hook will miss the gate and the team will then be tempted to relax it.

Make it a design rule, not an optimization: the hook entry points (`capture`, `compile_context` for hooks, `record_delivery`) import only the standard library. The packet cache in `cache/` is pre-serialized by the worker; the hook validates `store_revision` with one `sqlite3` read, writes the spool segment, and returns. Add a unit test that asserts the hook module's transitive import set, so the constraint survives refactors. Also: hooks never write to SQLite. Delivery receipts are already an event kind (`memory_delivered`); route them through the spool and let the worker ingest them. That removes the busy-timeout path from every tool call.

### 4. Suppression and overlay need a session-local view of unprocessed events

Two consequences follow from hooks writing only to the spool. First, "unchanged warnings are suppressed after delivery" needs the set of already-emitted (record, revision) pairs, and the worker may not have ingested the last delivery event before the next tool call fires. Second, the short-term observation overlay ("this exact command just failed") is only useful if it sees the failure *before* the worker ingests it; otherwise the agent retries during the lag.

Specify a bounded per-session scratch file in `run/<session_id>.json`: emitted pairs plus the last N typed tool outcomes, written by the hook, discarded at session end. The pre-action hook reads the DB and this file; the worker is still the only writer to SQLite. This is also what makes the "legitimate retry" case observable within a session rather than only across sessions.

### 5. `user_declared` is admitted automatically on a model's judgment

A32 covers hostile text acquiring authority by paraphrase. The gap is the opposite direction: a user pastes a document or a colleague's message, and the extractor classifies a sentence inside it as the user's own preference. `user_declared` claims then bypass the review pass and can immediately produce `caution` items or supersede a prior decision.

Tighten the operation policy: a `user_declared` claim is auto-admitted only when its `SpanLocator` points into a `user`-channel event *and* a deterministic pre-check finds the span outside any fenced block, blockquote, or pasted-content heuristic (long run of lines with no first-person verbs, email headers, diff markers). Anything else is admitted as `inferred` and takes the review pass. Any `user_declared` claim that would supersede an existing decision or produce `caution` takes the review pass regardless.

### 6. "Proof that context reached the model" has no defined method

Tasks 13 and 14, the probe report (§5 item 8), A27 and the `autonomous_ready` flag all rest on it, but no document says how to establish it. External hooks cannot see the host's model request.

Define a canary protocol: the smoke test places a unique nonce in a packet item, the test prompt asks the agent to repeat any nonce it was given, and delivery passes only if the nonce appears in the assistant's next message in the transcript. Run it for session start, prompt, pre-action and post-compaction separately; each is a distinct injection path on each host. Where the host writes injected context into its transcript, use that as a second, cheaper check. Record the method and host version in `docs/host-compatibility.json`.

### 7. Prefer dependency fingerprints over branch names for applicability

`Scope.branch_refs` means a lesson learned on `feature/x` stops applying when the branch is merged to `main`, and a lesson learned on `main` fires on an unrelated branch that has reverted the relevant file. Branch identity is a poor proxy for the condition that actually governs applicability.

Keep `branch_refs` for recall and explanation, but make `dependencies` (file and config fingerprints, already in the contract) the primary applicability input for `caution`. A `failure_lesson` whose dependency fingerprints all still match is applicable on any branch; one whose fingerprints changed is `needs_revalidation` on any branch. This also makes A43 ("fixed failure becomes retryable") deterministic instead of model-mediated.

### 8. Forgetting: order the purge before the rebuild, and stop wiping backup history

Two refinements. Rewriting a derived record that still has other evidence requires a model call, which cannot run inside the forget transaction. Specify the sequence: in the transaction, purge the body to a content-free placeholder and set status `quarantined`; after commit, queue a re-extraction job over the remaining roots; a record with zero remaining roots becomes `forgotten`. The record is unservable in the gap, which is the correct failure direction.

"Delete affected private backups" means one forget request erases every restore point older than the request. Add to the forget sequence: take a fresh consistent backup immediately after the transaction commits, verify it, then delete older ones. The ledger-on-restore rule (A37) already covers the restore path; this preserves the ability to restore at all.

### 9. Protect the memory directory from the working agent

The threat model excludes same-user processes, but the working agent *is* a same-user process with file tools and the memory store sits inside its repository. A confused agent can `cat` the spool, edit `memory.sqlite`, or read another session's scrubbed-but-private task content.

`integrate` should install a host deny rule for `.project-brain/` (both hosts support path-based tool restrictions in their permission config), and the store should keep a hash-chained revision log so tampering is at least detectable in `doctor`. Say in the spec that this is detection and friction, not protection.

### 10. Trigger debouncing for failure boundaries

A failure boundary "can trigger earlier extraction". In test-driven work a failure occurs every few minutes, which, combined with gap 2 in the inconsistency table, drains the budget on red-green cycles that A13 says should produce nothing. Define the trigger as a failure not followed by a success of the same root class within N events or M minutes (defaults: 6 events, 10 minutes), plus task completion, compaction and session end. Expected-red tests then never reach the model.

### 11. Curator isolation must also cover user-level host configuration

An isolated cwd keeps the curator's Claude CLI away from project hooks, but user-level `~/.claude` hooks, plugins and memory still load unless the launch explicitly restricts setting sources. The SOURCES review already notes that separate flags do not certify a combined launch. Make the certification probe assert the *effective* set: no hooks fired (checked by the recursion marker), no CLAUDE.md or user memory in the first request, no MCP servers, and record which flags achieved it on which version. If any native host memory feature is on, it must be disabled for the curator and treated as a confound in the evaluation (see Evaluation).

## Evaluation and release-gate improvements

The acceptance document is the strongest of the five; the fixes are additions, not corrections.

**Measures the gates cannot currently see.** Add these to §5.1 or §7 as reported (not necessarily gated) values on every release run:

| Measure | Why it matters | Proposed reporting |
| --- | --- | --- |
| Budget exhaustion rate | A system that is correct but budget-starved passes all gates and never learns on a real day | Fraction of live-corpus scenario-days that hit any model budget; median hours-to-exhaustion |
| Task over-fragmentation | "Separate tasks, never merge" has no measured cost | Tasks created per gold-labeled task; a split that severs an attempt from its result counts as a continuity failure |
| Delivery visibility rate | A hook that returns JSON the host ignores is a silent total failure | Canary pass rate per injection path per host version (gap 6) |
| False suppression | A warning correctly suppressed, then wrongly kept suppressed after conditions changed | Count on the revision scenarios; pairs with A26 |
| Same-session learning latency | The spec promises an overlay but measures only cross-session recall | Time from captured failure to its appearance in the next pre-action packet of the same session |

**Confounds to control in §6.** If the working agent's host has a native memory feature, every baseline is contaminated unless it is explicitly off, and "no memory" is not what it claims. Record the host memory setting in each trial's configuration and disable it in baselines 1, 2 and 4. If it cannot be disabled, it becomes the fifth baseline rather than noise.

**Scenario authorship.** Scenarios written by the people who designed the admission rules will be shaped by them. Source at least the 12 held-out scenarios from sanitized real Breadcrumbs sessions or from a person who has not read SYSTEM\_SPEC §7, and say which in the report.

**Review-pass diversity.** The spec correctly says a review by the same model is not independent proof. A cheap improvement that does buy some diversity: the review prompt is adversarial by construction ("list the strongest reasons this proposal is unsupported by the cited evidence") rather than a yes/no on the extractor's rationale. Pin it as `review_v1.md` and version it separately from extraction.

**Cost.** 48 scenarios × 3 trials × 4–5 baselines × 2–3 sessions is roughly 1,700–2,200 agent sessions per full release run. Put a dollar and wall-clock estimate in §6 now so the 12-scenario smoke subset is understood as the everyday loop and the full run is budgeted, not improvised.

## Implementation plan sequencing

The task order is logically correct and the gates are good. The single structural change worth making: no real host event reaches the system until Task 13, so Tasks 3 through 12 are built against synthetic envelopes. If the Claude Code payload shape, transcript path handling or compaction semantics differ from the fixtures, eleven tasks of assumptions are discovered late.

1. Add **Task 3b, capture-only Claude Code adapter**, inside Subproject A: real hook payloads for start, prompt, tool, compaction and end, normalized into the envelope and written to the spool. No delivery, no worker changes. Its fixtures become the fixtures Task 13 extends. This also produces the hook-latency number (gap 3) in week two instead of month four.
2. Make the **import-set test** for hook entry points part of Task 3b's definition of done, so the stdlib-only rule is enforced from the first real hook.
3. Move **certification probing of at least one provider** (Task 7's real-CLI probe) to run in parallel with Subproject A as a spike with a throwaway harness. It is the one external dependency that can block the autonomous release outright, and it needs no engine code to answer.
4. Split **Task 12** (delivery accounting, feedback, service layer, CLI) into 12a service + CLI and 12b delivery accounting + corrections. It is the largest task in the plan and its two halves have different reviewers.
5. Add `working/segment.py` and the provisional-binding tests to **Task 6** (gap 2) and the deterministic trigger debounce to **Task 9** (gap 10).
6. State in the plan header that **Review focus** items 1–5 are rechecked at every subproject gate, not only in their owning tasks; two of them (3 and 4) span tasks in different subprojects.

## Smaller fixes by document

**SYSTEM\_SPEC**

- §3.3: when `result_text` is bounded, specify head + tail preservation (the failing assertion is usually at the end) and an adapter-extracted error signature line. A head-only cut loses the one line that matters.
- §8.2: add a table for when `context` items are shown at all, by strength × freshness × evidence availability. `caution` is fully specified; `context` is not, so the compiler will invent its own cut-off.
- §7.4: shell parsing differs on Windows; say that `argv` reconstruction uses the host's reported argument array where available and a conservative tokenizer otherwise, and that mismatch yields `unknown`, never a guessed `action_kind`.
- §9.1: add "confirm the account's terms permit non-interactive background invocation" to the certification probe; subscription CLIs are not uniformly licensed for unattended automation.
- §5.1: name the Windows antivirus/indexer case where `os.replace` into `spool/ready/` fails transiently; one bounded retry, then `not_captured`.
- §11: note that tombstone source digests are an oracle (anyone with the ledger can test whether a candidate text matches forgotten content). Acceptable, but it belongs in the stated limits.

**DATA\_CONTRACTS**

- §1.1: `EvidenceLink.mapping` is a free string with registered validators; enumerate the three registered names in the contract rather than only in prose.
- §2.1: event IDs for imported stubs must derive from origin identity, not the local installation, or re-import under a new installation ID breaks the lineage mapping that §5 promises is stable.
- §9: `ContextItem.why` is `list[str]`; make the first element a stable reason code and the rest human text, so the evaluation can count match reasons without parsing prose.
- §12: add the exit code for `not_captured` on `observe` (it is not invalid input, storage failure or policy refusal as written).

**ACCEPTANCE\_TESTS**

- A12 and A10 are correctness properties that depend on a model; say explicitly that their deterministic form uses recorded proposals and their live form is in §5, so nobody tries to make them blocking with a mock.
- §7: the 300 ms hook gate should state the reference hardware class and that the number is measured with the packet cache warm and cold separately, since the cold number is dominated by interpreter startup.

**IMPLEMENTATION\_PLAN**

- Task 1 names `ProjectMemoryError` codes; add `not_captured` and `capability_degraded` so health and hooks have a code to return.
- Task 2: "use a native Windows fixture for junction handling" should also cover a workspace on a case-insensitive filesystem on Linux and macOS (`ext4` with casefold, APFS case-insensitive), since A33 names case variation.

**SOURCES\_AND\_REUSE**

- The Codex section says a no-tools inference invocation was not established. Make the consequence explicit in the plan: Codex is a capture host in v1 and a provider only if a later probe certifies it. Right now the plan's Task 7 file list includes `codex_cli.py` as if it were expected to pass.

## What to leave alone

These are the decisions an implementer under schedule pressure will be tempted to soften. They are right as written and the review recommends no change.

- **Retrieval and delivery never increase evidence strength.** This is the single rule that keeps the system from confirming itself. Every shortcut that "just counts a hit" breaks it.
- **No model call inside a write transaction; persist the proposal before applying it.** This is what makes crash recovery free of a second model call and makes the failure-injection matrix tractable.
- **Installation isolation with no shared daemon.** The temptation to add a global registry will arrive the first time two projects need a shared worker. Resist it; the per-project cost is small and the isolation guarantees are the product.
- **Durable knowledge stays in the store; instruction files are an explicit export.** This is the correct inversion of the Breadcrumbs design and the reason revision and forgetting can work at all.
- **Tri-state applicability where `unknown` never cautions.** Weakening this to "unknown is probably fine" is how memory systems become nagware.
- **Honesty about what passes.** "Passing does not prove absence of failures outside that population" and "do not lower a gate to manufacture success" should survive into the release process verbatim.
- **Starting fresh with selective reuse and a one-way importer.** The reuse table in SOURCES\_AND\_REUSE is the right granularity; the plan's warning against a wholesale clone is correct.
