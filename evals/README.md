# Evaluation fixtures and harness

| Path | Contents |
|---|---|
| `projects/ledgerlite/` | Coding project (src-layout Python library, unittest) |
| `projects/fieldnotes/` | Coding project (Python CLI; checks via `tools/check.py`, needs `NOTES_HOME`) |
| `projects/household/` | General planning workspace (Markdown/CSV, no code) |
| `scenarios/smoke/` | The 12 **non-held-out** smoke scenarios: 4 learning, 4 revision, 4 control, with gold labels and overlays |
| `scenarios/held_out/` | Reserved for the 12 held-out scenarios of the full release; intentionally empty |
| `oracles/smoke.py` | Task oracles that judge final artifacts and the action log, never memory text |
| `run.py` | The harness CLI: `preflight`, `prepare`, `smoke`, `workload`, `demonstrate`, `report`, `gate` (decision 0020) |
| `agent.py` | The scripted working agent (fixed per-scenario policies) and the live Claude Code agent wrapper |
| `curator.py` | Recorded curator proposals at the worker's `Backend` interface (scripted mode only) |
| `trial.py` | One trial per scenario and arm: own workspace, home and store; evidence horizons; outcomes |
| `baselines.py` | The clean no-memory arm and the observed host-native memory setting |
| `workload.py`, `workload/days/` | Three seeded eight-hour workload days, one per project, replayed on a virtual clock |
| `demos.py` | The ACCEPTANCE_TESTS §6.1 demonstrations |
| `report.py` | §5.1/§5.2 measures, paired outcomes, Wilson intervals and seeded resampling |

Scenario files: `sessions` lists fresh sessions (A learns, B applies, C changes evidence). `overlay_files` are applied to the workspace before that session. `gold` holds exact observations, supported lessons, acceptable uncertainty, prohibited generalizations and expected retrieval points; control scenarios are `quiet`. The oracle runs on a copy of the workspace after the named session.

Authorship: these smoke scenarios, their gold and the workload days were written by the repository's coding agent, who has read SYSTEM_SPEC §7. They are development fixtures only. Held-out scenarios must come from sanitized authorized real sessions or an independent author who has not read SYSTEM_SPEC §7 (ACCEPTANCE_TESTS §5); none exist yet.

The preview gate runs each smoke scenario once for the candidate and once for a clean no-memory baseline (ACCEPTANCE_TESTS §6.1). Two modes:

- `--mode live` uses the installed Claude Code CLI and the installation's certified route. It refuses (exit 4, printing the operator commands) until `preflight` finds a certified route and a `live` host record.
- `--mode scripted` replaces only the working agent and the model. It is mechanics evidence, labeled in every output, and never counts toward the gate.

Evaluation installations are initialized with an operator- or CI-provisioned pre-init token file (`--init-route operator_token --operator-token-file FILE`); the harness never mints one. A scripted run's recorded outputs are in `docs/evaluations/`.

```
python evals/run.py preflight
python evals/run.py gate --mode scripted --init-route test_fixture --out DIR
python evals/run.py gate --mode live --route PROJECT/.recalith/provider.json --host-record PROJECT/.recalith/host.json \
    --init-route operator_token --operator-token-file FILE --out DIR   # after B1
```
