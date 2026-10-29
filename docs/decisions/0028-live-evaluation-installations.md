# Decision 0028: Live evaluation installations and the live trial path

Status: accepted (Task 18 preview slice, live path); item 2 open for the owner's review; items 12–16 added after the first live gate, item 17 after the second · Date: 2026-10-23, amended 2026-10-26 and 2026-10-29 · Host: Claude Code 2.1.309, then 2.1.310, on native Windows; three one-scenario pilots and two failed live gates have run

## Context

Decision 0020 built the harness with `live` mode refusing under B1. B1 has now cleared on native Windows: one project (the owner's pilot) holds a live-certified curator route and a live engine-mode host record (BUILD_PROGRESS, 2026-10-23). A live trial still could not run, for four reasons the documents did not settle.

- **Records bound to one installation.** Each trial needs its own fresh installation (ACCEPTANCE_TESTS §5, §6.1, §6.2), but both records are bound to an `installation_id`. A copied `provider.json` is `foreign_provider_config` (decision 0009 item 1). Another installation's `host.json` is `invalid` (decision 0019 item 9; `health.load_host_certification`).
- **Hooks need a runtime.** The installed hooks run only on the project's provisioned runtime. Without it the launcher is a silent no-op (A53).
- **Capture uses real time.** Live hook capture stamps real time, so the scripted harness's virtual clock cannot drive a live trial's worker.
- **No delivered text.** A live session had no record of what the hooks delivered: receipts hold item identities, not text.

Where a rule was ambiguous the stricter reading was kept, and no gate, target or fixture changed.

## Decisions

1. **The route is certified per installation.** A complete live run of the unchanged `tools/probe_provider.py --route-out` certifies each live candidate installation's curator route. The probe runs as a child of the harness, inherits its environment unchanged, and is refused from a host-marked process (exit 6). Nothing is copied, and `foreign_provider_config` still holds. The probe's reports go to the run directory (`certification/<trial>.route.json`), never to the tracked report. The cost is three small live calls per installation with the Messages backend.
2. **The host record is bound, not re-observed.** SYSTEM_SPEC §9.3 scopes delivery certification to the host version and path: "For each host version…", "Readiness is scoped to the certified path/version set, and host/model/config changes require re-probing". Task 13's engine-mode protocol runs in disposable fixture installations and never in the target project. A target's record therefore says that this installation is integrated with a host version, model and configuration that the protocol certified live.

   The certification harness writes the target's record from the certified project's live record (so decision 0019 item 9 still holds): `tools/probe_delivery.py --engine-project TARGET --bind-from CERTIFIED --evidence REPORT --output BINDINGS`. It runs no session and binds only when every check passes:
   - The source record is `live` for the source installation, with start and prompt certified.
   - The evidence report's `delivery_engine` section names that same run: its digest, and the held record's installation and digest, with live status `run`.
   - The installed host's version equals the record's version and the target's integrated version.
   - The caller is unmarked (otherwise exit 6).

   The bound record carries the source's report digest. The binding (both installations, the digest and the times) goes to `--output` under `sections.delivery_binding`; the evidence report is only read. `integrate` then re-runs, so exactly the certified paths are enabled. Unchanged rules:
   - A copied `host.json` is still invalid.
   - A request-capture record still enables nothing.
   - Another host version, model or configuration still needs a full `--engine-project` run.

   Re-running the protocol per installation would mean 24 live host sessions for each of 13 candidate installations, about ten times the comparative smoke itself, and it would add no evidence about the installation, because the protocol never runs inside it. **Owner review:** if the owner rejects binding, the strict alternative is a full `--engine-project` run per trial installation, which the harness does not automate.
3. **Provisioning** (`evals/live.py: provision`) runs the operator's own tools, each as a child of the harness:
   - `recalith init --operator-token-file`, with the pre-init token. It is never minted here.
   - `bootstrap.py install` with the verified wheel and the hash-locked wheelhouse. The wheel's digest must equal the certified project's `engine.lock`, so trial hooks run the certified build.
   - The route probe (item 1).
   - `integrate claude --operator-token-file`.
   - The bind (item 2).

   A failed step is recorded with the step log, and the trial reports it. It is never dropped and never retried with weaker settings.
4. **The live working agent** is `claude` with the certified engine-mode session flags: `-p --strict-mcp-config --output-format stream-json --verbose --include-hook-events`. It adds the configured working-agent model, `--permission-mode acceptEdits` and `--allowedTools Bash Read Edit Write`, and receives the prompt on standard input.
   - Each session gets a disposable `HOME` with native memory disabled.
   - The environment is built from the delivery configuration's key names plus the installation route's key names, which the hook-started worker carries to its curator. It holds no host or role marker.
   - The default setting sources load, not `--setting-sources local`, so the disposable `HOME`'s disabling settings apply. `baselines.observe_native_memory` now runs with these same flags. On 2.1.309 in request capture the control loaded the planted sentinel and the disabled run did not: `disabled`.
   - The base interpreter's directory leads `PATH`, so `python` is a plain interpreter without engine entry points. Both arms get the same.
   - The environment keeps the platform's temp-directory variables (`TEMP`, `TMP`, `TMPDIR`), as every real host session has them. The first live pilot (2026-10-23) ran without them. The hooks and the worker they started then had no temp directory, so Windows fell back to its own directory, SQLite could not open a temporary file, and every typed reduction failed. The worker recorded these only as `handler_error`.
5. **The product's worker on real time.** The hooks' registered start launches the installation's worker, which curates on the installation's own certified route, isolation recheck included. Between sessions and after the last one, the harness reads the store read-only (`live.wait_quiescent`). It waits until nothing is due within 20 minutes (beyond the 600 s failure debounce and the 300 s quiet window), no job is leased and the spool is empty. The wait also ends, with that state recorded, after 45 minutes or after 5 minutes without store progress.
   - The evidence horizon is checked read-only before every session (`evidence_horizon(..., ingest=False)`).
   - The worker is stopped at the end with `recalith worker stop --operator-token-file`.
   - The scenarios' two-hour gaps are not reproduced, and this is stated as a limitation.
6. **What was delivered** comes from the host's own `hook_response` records (`--include-hook-events`), which carry each hook's exact stdout. The trial reads `additionalContext` from them; the 2.1.309 record shape was observed in request capture and is pinned in `tests/unit/test_live_eval.py`. This is emission as the host received it; model visibility is the canary certification's. The action log pairs the stream's `tool_use`/`tool_result` blocks, with paths made workspace-relative for the frozen oracle.
7. **Live workload days** replay the recorded timeline in process through the real stdlib hook path, with no host.
   - The installation is initialized with the token and gets its own certified route. No bootstrap or integration is needed.
   - The harness worker runs on the day's virtual clock, with the route behind the production `ProviderSupervisor`. Its isolation recheck must pass before any call.
   - Every call is timed (`live.CallRecorder`). ACCEPTANCE_TESTS §5.2 allows the virtual clock for scheduling; calls and usage stay real.
8. **Live demonstrations** use only this run's live trials.
   - Fresh-session reuse and the changed-condition revision come from the live trials. A missing live trial fails the demonstration; there is never a scripted fallback.
   - Forgetting with restore, and isolation, run on the kept live L3 and C4 workspaces. Privacy operations go through each installation's guarded CLI with the operator token, with the worker stopped around them.
   - Delivery after forget and after restore is read from fresh live sessions.
9. **Parallel slots** (`--slots N`) run trials at once, each in its own installation (ACCEPTANCE_TESTS §6.2).
10. **Labels.** Records carry the `<agent-model>`/`<curator-model>` placeholders, paths relative to the run, the backend and the wheel digest; no model identifier appears (decision 0027). The report adds the host's reported foreground session cost and the ledger's background tokens.
11. **A live gate passes only on a complete run.** `report.completeness` requires everything ACCEPTANCE_TESTS §6.1 says must run:
    - all 12 smoke scenarios in both arms, without a run error and each with its intended clean label;
    - every live candidate wait that ended `quiet`. A `stalled` or `deadline` wait means the next session ran before the worker had processed the last one, so the protocol did not run (reason `unsettled_gaps`, with the jobs' waiting codes);
    - three workload days with measures;
    - all five demonstrations shown.

    Anything missing fails the gate, with one reason per gap: `smoke_trials_missing`, `trial_errors`, `contaminated_arms`, `workload_days_short`, `demonstrations_unmet`. A task the agent failed is an outcome, not a gap. Before this change a live report could reach `passed_smoke` with trials, days or demonstrations absent, because the gate read only the §5.1 measures. A workload day that did not run is now listed (`days_not_run`) instead of crashing the report.

The first live gate (2026-10-23 to 2026-10-26, BUILD_PROGRESS) failed, and four of its causes were the harness's to close. None of the following changes a gate, a target or a fixture:

12. **Every live session runs on the certified host version.** The host updated itself from 2.1.309 to 2.1.310 partway through the run. The bind refused the five candidates provisioned after that (`host_version_changed`). But sessions of installations provisioned earlier, and every later baseline session, ran on 2.1.310 unnoticed; only the host's own transcripts showed it.
    - The setup now carries the version the source project's live host record certifies, and refuses without one (`host_version_unknown`).
    - Every live trial checks `claude --version` against it, before provisioning (so no route certification is spent) and before every session, including the second project's and the demonstrations' fresh sessions. A mismatch is the trial error `host_version_changed`.
    - Each session records its host version. `smoke` schedules no further trial after a mismatch, and `gate` then writes the report of what ran (exit 8).
    - Completeness fails any live session whose version is absent or differs (`host_version_mismatches`).
13. **A suspension of the machine is recorded and fails the gate.** The laptop slept over a weekend: one baseline session measured 61 hours under its 900-second bound, and two final waits ended `deadline` after about 5,300 s.
    - A session that outlasted its own timeouts by more than 120 s is `suspended`. So is a wait whose poll came back more than 120 s after its sleep ended (`suspended_s`).
    - Completeness fails on either (`suspended`).
    - A live run asks the platform not to idle-sleep while it lasts (Windows `SetThreadExecutionState`, macOS `caffeinate -i`), and `run.json` records what was granted. A lid close or an explicit sleep is still possible, and is still recorded.
14. **Live §5.1 support and recall come from reviewers' labels.** The report scored each admitted claim by whether its text contains the scenario's frozen gold terms (`GOLD_TERMS`). That fits the recorded curator, whose proposals were written with the gold. For a live curator the same test fails in both directions:
    - It scored true claims outside the gold as unsupported. Examples: L1's `python -m pytest` fails because pytest is not installed; fieldnotes' checks enforce a 100-character line limit.
    - It scored L1's failure lesson as recalled from the procedure claim, although that run's agent never made the failing call.

    ACCEPTANCE_TESTS §5 says a model judge may assist but does not solely adjudicate support. So in live mode:
    - `supported_precision`, `useful_recall` and `failed_approach_recall` come from `adjudication.json` in the results directory. Each admitted claim is labeled `supported` or `unsupported` (a prohibited generalization is unsupported). Each gold lesson is labeled `recalled`, `missed` or `evidence_absent`.
    - `evidence_absent` (the trial's sessions never produced the lesson's evidence) leaves the denominators and is listed. The spec counts abstention as missed recall only "when the evidence was sufficient".
    - A trial that did not run recalled nothing.
    - Unlabeled items leave the measures unestablished, and the gate fails with `claims_unadjudicated`.
    - `evals/run.py adjudicate DIR` writes the sheet and a template whose term-match fields are suggestions, never labels. The report keeps the term match as `term_match_provisional`, and states the single-reviewer limitation when fewer than two reviewers are named.
    - Scripted runs keep the term match unchanged.
15. **Curator call outcomes stay in the record.** Each live candidate trial and live workload day records, per purpose, its charged calls, the calls that ended at the output cap, provider-reported input and output, and the visible reply's local estimate (`live.provider_outcomes`), plus the curation jobs' failure codes. The report sums them (`curator_call_outcomes`). In the first gate, the workload stores were removed with the run and these counts could not be recovered.
16. **Fresh-session reuse counts any learning scenario.** ACCEPTANCE_TESTS §6.1 asks for "at least one fresh-session reuse"; the harness had pinned it to L1, whose failure a capable live agent avoids without memory: the first gate's baseline inspected the project and ran the working command first.
    - The demonstration now holds when any of the four learning scenarios meets all three conditions, each read from that run's own trials:
      - the candidate succeeded with no repeated mistake;
      - a packet delivered in its fresh session B carried the scenario's session-B gold text (any packet, because L1's session-start point is unmet by design, decision 0013, and its prompt packet carries the lesson);
      - the clean baseline, in the same session, failed the task or repeated session A's mistake.
    - The record lists every learning scenario with its evaluation, and `met_by`. A live pair that did not run is listed under `not_run`, never replaced by a scripted trial.
    - Compared with the L1-only rule, two conditions change.
      - The baseline can show the gap by failing the task as well as by repeating the mistake. A preference or decision it never received shows as a failed task, not a repeat.
      - Delivery of the gold text in session B is now required; it was implicit for the scripted agent.
    - Decided before the rerun. Applied to the first gate's records, it counts L3: its baseline failed and its candidate's session-B prompt packet carried the $600 preference. That session ran on 2.1.310, which item 12 now refuses. On the recorded scripted run, L1, L2 and L3 meet it.
17. **A retry that clears the variable is a plain retry (the R1 and R2 oracles).** In the second live gate, R2's candidate ran `env -u PYTHONPATH python -m unittest discover -s tests -t .` in session C. That is the plain retry the scenario asks for, with the variable cleared explicitly, and it passed. The oracle counted every command that named `PYTHONPATH` as not plain, so it scored the candidate's task as failed. R1's oracle had the same test for `NOTES_HOME`.
    - A command is now not plain only when it gives the variable a non-empty value (`NAME=v`, `export NAME=v`, `env NAME=v`). `env -u NAME`, `unset NAME` and `NAME=` are plain (`smoke.sets_variable`).
    - The tasks, the gold and the other checks are unchanged, and the rule applies to both arms alike from the next run.
    - The second gate's record keeps the score it was given. R2's candidate is a failed task there; BUILD_PROGRESS (2026-10-29) calls it an oracle false negative.
18. **A session's overlay lands after the earlier sessions' curation.** The live trial applied each session's overlay first and only then waited for the worker to go quiet. A recorded run drains after each session and applies the next session's overlay afterwards. In the third R4 rerun (engine `0.1.0.dev3`), C's overlay replaced `fieldnotes/store.py` 12 s after session A ended, and A's extraction ran about five minutes later. The extractor declared the file as asked (decision 0031), but its fingerprint was taken at admission, so it recorded the new bytes, and C's prompt showed the stale fact as `current`.
    - The live trial now waits for quiet before it applies the next session's overlay, then checks the evidence horizon, then runs the session. The overlay is still applied before the session, and the no-memory arm, which has no gap, is unchanged.
    - The earlier R4 records keep their result. Each rerun had the overlay land before A's extraction: in the first, the claim declared no dependency; in the second, none could be tied to the file; in the third, the dependency recorded the changed bytes.
    - The race the old order exposed is real and stays open: a change outside any captured tool between an observation and its curation becomes the claim's recorded state (decision 0030 Limits). R4 tests a change after curation, as its recorded run does; that race is an owner decision (BUILD_PROGRESS, 2026-10-29), not fixed here.

## Consequences

Built: the live path for smoke trials, workload days and demonstrations, the bind, and tests with labeled fakes and the observed 2.1.309 hook-event shape (`tests/unit/test_live_eval.py`). After the first live gate: the host-version check, suspension records and keep-awake, the adjudicated live quality measures and `evals/run.py adjudicate`, the curator call outcomes, and fresh-session reuse over every learning scenario (items 12–16). After the second: the plain-retry rule of the R1 and R2 oracles (item 17). After the third R4 rerun: the overlay after the gap (item 18).

Run: three one-scenario pilots and two full live gates, all by the owner from an ordinary terminal. Both gates failed (BUILD_PROGRESS, 2026-10-26 and 2026-10-29; the sanitized records are in `docs/evaluations/preview-live-2026-10-26/` and `docs/evaluations/preview-live-2026-10-29/`).

Limits:
- Real-time gaps, not the scenarios' two hours.
- Delivered context is what the host received; model visibility is not re-checked per trial.
- One trial per arm.
- Gold labels and scenarios are not independent.
- On native Windows the hook-started worker runs inside the venv redirector's job (decision 0027 item 8).
