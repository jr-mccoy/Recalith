# Evaluation fixtures

| Path | Contents |
|---|---|
| `projects/ledgerlite/` | Coding project (src-layout Python library, unittest) |
| `projects/fieldnotes/` | Coding project (Python CLI; checks via `tools/check.py`, needs `NOTES_HOME`) |
| `projects/household/` | General planning workspace (Markdown/CSV, no code) |
| `scenarios/smoke/` | The 12 **non-held-out** smoke scenarios: 4 learning, 4 revision, 4 control, with gold labels and overlays |
| `scenarios/held_out/` | Reserved for the 12 held-out scenarios of the full release; intentionally empty |
| `oracles/smoke.py` | Task oracles that judge final artifacts and the action log, never memory text |

Scenario files: `sessions` lists fresh sessions (A learns, B applies, C changes evidence). `overlay_files` are applied to the workspace before that session. `gold` holds exact observations, supported lessons, acceptable uncertainty, prohibited generalizations and expected retrieval points; control scenarios are `quiet`. The oracle runs on a copy of the workspace after the named session.

Authorship: these smoke scenarios were written by the repository's coding agent, who has read SYSTEM_SPEC §7. They are development fixtures only. Held-out scenarios must come from sanitized authorized real sessions or an independent author who has not read SYSTEM_SPEC §7 (ACCEPTANCE_TESTS §5); none exist yet.

The preview gate runs each smoke scenario once for the candidate and once for a clean no-memory baseline (ACCEPTANCE_TESTS §6.1). The live evaluation harness (`evals/run.py`) arrives with Tasks 7–18; `tests/unit/test_smoke_scenarios.py` proves every oracle fails on the untouched seed and passes on a reference solution.
