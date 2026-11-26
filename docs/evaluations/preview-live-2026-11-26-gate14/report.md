# Preview evaluation report (live)

**live working agent and certified inference route.** Counts toward the preview gate: **True**. Gate: **passed_smoke**.


## Paired outcomes (candidate vs clean no-memory baseline)

| Scenario | Success C/B | Repeated mistakes C/B | Detours C/B | Retry C/B | Foreground tok C/B | Background tok C | Elapsed s C/B | Labels C/B |
|---|---|---|---|---|---|---|---|---|
| smoke-C1-ledgerlite-routine-typo | yes/yes | 0/0 | 0/0 | –/– | 144303/123895 | 165758 | 25.4/13.5 | candidate/no_memory |
| smoke-C2-fieldnotes-tdd-expected-red | yes/yes | 0/0 | 0/0 | –/– | 416122/268116 | 339039 | 66.3/42.6 | candidate/no_memory |
| smoke-C3-household-utilities-speculation | yes/yes | 0/0 | 0/0 | –/– | 73173/71926 | 93725 | 22.4/17.7 | candidate/no_memory |
| smoke-C4-cross-project-near-match | yes/yes | 0/0 | 0/0 | –/– | 205285/179143 | 115643 | 29.8/21.1 | candidate/no_memory |
| smoke-L1-ledgerlite-test-command | yes/yes | 0/0 | 0/0 | –/– | 186323/183645 | 286542 | 32.1/26.1 | candidate/no_memory |
| smoke-L2-fieldnotes-iso-dates | yes/yes | 0/0 | 0/0 | –/– | 196494/152640 | 353864 | 34.1/25.3 | candidate/no_memory |
| smoke-L3-household-grocery-budget | yes/yes | 0/0 | 1/0 | –/– | 196555/126573 | 252703 | 40.7/24.5 | candidate/no_memory |
| smoke-L4-ledgerlite-resume-refactor | yes/yes | 0/0 | 0/0 | –/– | 170519/164385 | 218219 | 29.9/26.8 | candidate/no_memory |
| smoke-R1-fieldnotes-check-env-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 107731/106569 | 234941 | 21.6/11.9 | candidate/no_memory |
| smoke-R2-ledgerlite-import-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 152032/146938 | 173033 | 22.0/15.1 | candidate/no_memory |
| smoke-R3-household-budget-correction | yes/yes | 0/0 | 0/1 | –/– | 55946/129138 | 109813 | 19.8/20.6 | candidate/no_memory |
| smoke-R4-fieldnotes-storage-conflict | yes/yes | 0/0 | 0/0 | –/– | 278145/149174 | 315781 | 36.2/24.3 | candidate/no_memory |

Paired differences (candidate − baseline), mean with a 95 % interval from resampling whole scenarios:

- task_success: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- repeated_mistakes: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- detours: n=12, mean=0.0, CI95=(-0.25, 0.25), inconclusive
- legitimate_retry_success: n=2, mean=0.0, CI95=(0.0, 0.0), inconclusive
- foreground_tokens: n=12, mean=31707.1667, CI95=(97.6667, 64966.3333)
- background_tokens: n=12, mean=221588.4167, CI95=(171269.5, 267945.6667)
- elapsed_seconds: n=12, mean=9.2409, CI95=(6.0339, 12.7476)
- operator_interventions: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- repeated failures on relevant scenarios: candidate 0, baseline 0, relative reduction None (>= 0.25 (Cut 2 gate; not a preview gate))

No superiority claim: a 12-scenario smoke run with one trial per arm cannot establish one (ACCEPTANCE_TESTS §6.1).

## Baseline-sensitivity set (decision 0049; not part of the gate)

| Scenario | Success C/B | Repeated named mistake C/B | Repeated mistakes C/B | Foreground tok C/B | Errors |
|---|---|---|---|---|---|
| sens-S1-ledgerlite-amounts-in-cents | yes/no | 0/1 | 0/0 | 314806/189855 |  |
| sens-S2-household-no-prices-in-meal-plan | yes/no | 0/1 | 0/0 | 213430/187894 |  |
| sens-S3-fieldnotes-checks-one-job | no/no | 1/1 | 0/0 | 300134/313613 |  |
| sens-S4-fieldnotes-frozen-notes-format | yes/no | 0/1 | 0/0 | 297091/266423 |  |

Repeated named mistakes over 4 pair(s): candidate 1, baseline 4, relative reduction 0.75; task success candidate 3, baseline 0.

Not part of the preview gate (ACCEPTANCE_TESTS §6.1 fixes it at the frozen 12). Four scenarios, one trial per arm, written by the coding agent: this shows whether the corpus can register a repeated mistake, not that memory helps; no superiority claim.

## §5.1 quality on the smoke population

| Measure | Value | Numerator/denominator | Wilson 95 % | Target | Met |
|---|---|---|---|---|---|
| supported_precision | 1 | 14/14 | (0.7847, 1.0) | >= 0.95 | True |
| useful_recall | 1 | 7/7 | (0.6457, 1.0) | >= 0.85 | True |
| failed_approach_recall | 1 | 2/2 | (0.3424, 1.0) | >= 0.9 | True |
| incorrect_confident_guidance | 0 | count over 12 | None | == 0 | True |
| conflict_uncertainty_preservation | 1 | 1/1 | (0.2065, 1.0) | >= 0.95 | True |
| legitimate_retry_discouraged | 0 | 0/2 | (0.0, 0.6576) | <= 0.05 | True |
| irrelevant_caution_quiet | 0 | 0/3 | (0.0, 0.5615) | <= 0.05 | True |
| routine_human_maintenance | 0 | count over 12 | None | == 0 | True |

Support and recall come from reviewer labels (`adjudication.json`); 0 item(s) unlabeled (`evals/run.py adjudicate`). Lessons whose evidence never occurred: 1. fewer than two independent reviewers (ACCEPTANCE_TESTS §5: report the limitation)
Term match (provisional, frozen against the recorded curator's wording): supported_precision 7/14, useful_recall 7/8, failed_approach_recall 2/3

## Curator call outcomes

```json
{
 "smoke": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 23,
    "replies_parsed": 23,
    "reported_input_tokens": 738984,
    "reported_output_tokens": 48160,
    "visible_output_estimate": 14063
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 27,
    "replies_parsed": 27,
    "reported_input_tokens": 890942,
    "reported_output_tokens": 56907,
    "visible_output_estimate": 9774
   },
   "revalidate": {
    "at_output_cap": 0,
    "calls": 2,
    "replies_parsed": 2,
    "reported_input_tokens": 26142,
    "reported_output_tokens": 3684,
    "visible_output_estimate": 526
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 14,
    "replies_parsed": 14,
    "reported_input_tokens": 111847,
    "reported_output_tokens": 22963,
    "visible_output_estimate": 4293
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 23,
    "replies_parsed": 23,
    "reported_input_tokens": 709104,
    "reported_output_tokens": 50328,
    "visible_output_estimate": 13505
   }
  },
  "job_errors": {
   "extract_claims:reevaluation_requeued": 1
  }
 },
 "workload": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 25,
    "replies_parsed": 25,
    "reported_input_tokens": 676303,
    "reported_output_tokens": 49245,
    "visible_output_estimate": 13892
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 46,
    "replies_parsed": 46,
    "reported_input_tokens": 1259380,
    "reported_output_tokens": 54629,
    "visible_output_estimate": 6771
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 7,
    "replies_parsed": 7,
    "reported_input_tokens": 37758,
    "reported_output_tokens": 6926,
    "visible_output_estimate": 1248
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 22,
    "replies_parsed": 22,
    "reported_input_tokens": 530896,
    "reported_output_tokens": 38110,
    "visible_output_estimate": 10196
   }
  },
  "job_errors": {
   "update_task:coalesced": 2
  }
 }
}
```

## §5.2 operational measures

```json
{
 "budget_exhaustion": {
  "backlog_at_day_end": {
   "fieldnotes": {
    "jobs": 0,
    "kinds": [],
    "oldest_age_seconds": 0.0
   },
   "household": {
    "jobs": 0,
    "kinds": [],
    "oldest_age_seconds": 0.0
   },
   "ledgerlite": {
    "jobs": 0,
    "kinds": [],
    "oldest_age_seconds": 0.0
   }
  },
  "days_hitting_any_pool": {
   "denominator": 3,
   "numerator": 0,
   "value": 0.0,
   "wilson_95": [
    0.0,
    0.5615
   ]
  },
  "days_not_run": [],
  "median_hours_to_exhaustion": null,
  "nonexhausted_censored_days": 3,
  "pools_hit": [],
  "priority_inversions": 0,
  "scenario_days": 3,
  "waiting_seconds": {
   "correction_declaration_review": {
    "max": 1.0,
    "n": 5,
    "p50": 1.0,
    "p95": 1.0
   },
   "ordinary": {
    "max": 4.0,
    "n": 93,
    "p50": 0.0,
    "p95": 3.0
   },
   "ordinary_review": {
    "max": 1.0,
    "n": 2,
    "p50": 1.0,
    "p95": 1.0
   }
  }
 },
 "curation_throughput": {
  "fieldnotes": {
   "admitted_claims": 2,
   "calls": 39,
   "calls_by_purpose": {
    "build_episode": 10,
    "extract_claims": 19,
    "review_claims": 2,
    "update_task": 8
   },
   "calls_per_admitted_claim": 19.5,
   "calls_per_settled_episode": 4.333,
   "estimated_tokens_by_purpose": {
    "build_episode": 192808,
    "extract_claims": 358914,
    "review_claims": 7524,
    "update_task": 127239
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 16.825,
     "n": 39,
     "p50": 6.82,
     "p95": 16.217
    }
   },
   "proposals": [
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "revise_episode",
       "outcome": "apply",
       "reason": "admitted"
      }
     ],
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "update_task",
       "outcome": "apply",
       "reason": "admitted"
      }
     ],
     "operations": [
      "update_task"
     ],
     "purpose": "update_task"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "propose_claim",
       "outcome": "candidate_only",
       "reason": "candidate_pending_review"
      }
     ],
     "operations": [
      "propose_claim"
     ],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "assess_claim",
       "outcome": "apply",
       "reason": "review_supported"
      }
     ],
     "operations": [
      "assess_claim"
     ],
     "purpose": "review_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The only durable finding, that running tools/check.py without NOTES_HOME fails, is already recorded as active claim claim_52f67b28. The later run with NOTES_HOME set has no exit code and an ambiguous command association, and its output names a different path, so it does not support a new claim. No user declaration appears in the events.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "revise_episode",
       "outcome": "apply",
       "reason": "admitted"
      }
     ],
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "propose_claim",
       "outcome": "candidate_only",
       "reason": "candidate_pending_review"
      }
     ],
     "operations": [
      "propose_claim"
     ],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "assess_claim",
       "outcome": "apply",
       "reason": "review_supported"
      }
     ],
     "operations": [
      "assess_claim"
     ],
     "purpose": "review_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "update_task",
       "outcome": "apply",
       "reason": "admitted"
      }
     ],
     "operations": [
      "update_task"
     ],
     "purpose": "update_task"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "revise_episode",
       "outcome": "apply",
       "reason": "admitted"
      }
     ],
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's durable content is already recorded: the NOTES_HOME requirement for tools/check.py is in active claim claim_52f67b28, and the ISO-8601 date rule is in active decision claim_6880866f. The remaining test failure and the edits are episode-specific, with no stated user rule, decision or preference.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "update_task",
       "outcome": "apply",
       "reason": "admitted"
      }
     ],
     "operations": [
      "update_task"
     ],
     "purpose": "update_task"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The NOTES_HOME failure is already recorded as an active failure_lesson. The later test_export failure is a single in-progress result with no durable project fact, and the user made no explicit statement this session.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's events show only tool runs (an Edit to fieldnotes/cli.py, two runs of tools/check.py with differing outcomes, and a failing test with an unresolved date-format mismatch). No user statement of intent or preference appears in the cited events, and no tool result gives an observed fact that restates an exact exit code or reported result. The failure is still open and was followed by a p",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "revise_episode",
       "outcome": "apply",
       "reason": "admitted"
      }
     ],
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The episode records one task to add a delete INDEX command test-first. Its failing run is an expected-red test failure, not a recorded NOTES_HOME failure, and the existing failure lesson already covers NOTES_HOME. The user's message is a task instruction, not a durable project rule, decision or preference.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "update_task",
       "outcome": "apply",
       "reason": "admitted"
      }
     ],
     "operations": [
      "update_task"
     ],
     "purpose": "update_task"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "No durable project knowledge in the cited events: the only failed check run's failure is already covered by an existing claim, the later passing run adds no new fact, and the task objective is not an allowed user-declaration citation.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session shows in-progress edits and one failing check run, with no durable user declaration in the cited evidence. The user objective is task state, and the failing run's test failure is transient.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's events are tool reads and an edit plus one failing Bash check with no user declaration in the cited evidence, so nothing durable is shown. The pending session boundary is left unresolved.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "revise_episode",
       "outcome": "apply",
       "reason": "admitted"
      }
     ],
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The cited events show reads, one edit and a failing test run, but no durable project fact, decision or preference. The user's objective is not in allowed_evidence_refs, so it cannot be cited.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The user's objective describes a task to move storage to notes.jsonl, not a standing rule, decision, or statement of current project state. The recorded test failure does not establish a durable lesson beyond the existing claims.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "This session's events show one unparsed Bash test run that exited 1, reads, and two identical edits to fieldnotes/store.py. None of it states a durable project fact, decision, preference or procedure, and the task objective's evidence is not in allowed_evidence_refs. The existing claims already cover the stable items.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "revise_episode",
       "outcome": "apply",
       "reason": "admitted"
      }
     ],
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The user's storage objective is task-scoped and its cited event is not in allowed_evidence_refs. The one failing run (ordinal 14) shows an AssertionError, not the KeyError in the existing check.py claim, so no new failure lesson is supported. Existing claims have no contradicting evidence in this episode.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "update_task",
       "outcome": "apply",
       "reason": "admitted"
      }
     ],
     "operations": [
      "update_task"
     ],
     "purpose": "update_task"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "revise_episode",
       "outcome": "apply",
       "reason": "admitted"
      }
     ],
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "update_task",
       "outcome": "apply",
       "reason": "admitted"
      }
     ],
     "operations": [
      "update_task"
     ],
     "purpose": "update_task"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The failing run without NOTES_HOME is already captured by the active failure_lesson claim_52f67b28, and the episode's other events show no new user declaration, decision, preference or durable fact.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
   
```

## Expected retrieval points (candidate)

10/12 satisfied (Wilson 95 % (0.552, 0.953)). Unmet:

- smoke-L1-ledgerlite-test-command: {"must_include": "PYTHONPATH=src", "purpose": "session_start", "session": "B"} (0 items delivered at that point)
- smoke-R3-household-budget-correction: {"must_not_include": "$600 as current", "purpose": "prompt", "session": "C"} (1 items delivered at that point)

## §6.1 demonstrations

```json
{
 "demonstrations": {
  "changed_condition_revision": {
   "demonstrated": true,
   "scenarios": {
    "smoke-R1-fieldnotes-check-env-fixed": {
     "legitimate_retry_success": true,
     "lesson": [
      [
       "Running `python tools/check.py` without NOTES_HOME set fails with KeyError: 'NOTES_HOME'.",
       "active",
       "current",
       8
      ]
     ],
     "retry_point": [
      {
       "delivered": true,
       "items": [
        {
         "advice": "context",
         "freshness": "needs_revalidation",
         "text": "Failure lesson: Running `python tools/check.py` without NOTES_HOME set fails with KeyError: 'NOTES_HOME'. Observed: `python tools/check.py` exited with code 1."
        }
       ],
       "satisfied": true,
       "spec": {
        "must_not_include_caution": "NOTES_HOME",
        "purpose": "prompt",
        "session": "C"
       }
      }
     ],
     "revalidation": [
      "revalidate:revise_claim",
      "revalidate:"
     ],
     "task_success": true
    },
    "smoke-R2-ledgerlite-import-fixed": {
     "legitimate_retry_success": true,
     "lesson": [
      [
       "Running `python -m unittest discover -s tests -t .` in this project, where tests/ has no __init__.py, fails with \"ImportError: Start directory is not importable\".",
       "active",
       "current",
       2
      ],
      [
       "Running `python -m unittest discover -s tests -t .` with a tests/__init__.py file present reports \"Ran 2 tests\" and \"OK\".",
       "active",
       "current",
       2
      ]
     ],
     "retry_point": [
      {
       "delivered": true,
       "items": [
        {
         "advice": "context",
         "freshness": "current",
         "text": "Fact: Running `python -m unittest discover -s tests -t .` in this project, where tests/ has no __init__.py, fails with \"ImportError: Start directory is not impo"
        },
        {
         "advice": "context",
         "freshness": "current",
         "text": "Fact: Running `python -m unittest discover -s tests -t .` with a tests/__init__.py file present reports \"Ran 2 tests\" and \"OK\"."
        }
       ],
       "satisfied": true,
       "spec": {
        "must_not_include_caution": "PYTHONPATH",
        "purpose": "prompt",
        "session": "C"
       }
      }
     ],
     "revalidation": [],
     "task_success": true
    }
   }
  },
  "forgetting_and_restore": {
   "after_forget": {
    "actions": [
     {
      "command": null,
      "exit_code": null,
      "path": null,
      "tool": "Glob"
     },
     {
      "command": null,
      "exit_code": null,
      "path": null,
      "tool": "Grep"
     },
     {
      "command": null,
      "exit_code": null,
      "path": "<run>\\work\\L3\\c\\w\\budget.csv",
      "tool": "Read"
     },
     {
      "command": null,
      "exit_code": null,
      "path": "<run>\\work\\L3\\c\\w\\meal-plan.md",
      "tool": "Read"
     },
     {
      "command": null,
      "exit_code": null,
      "path": "<run>\\work\\L3\\c\\w\\README.md",
      "tool": "Read"
     },
     {
      "command": "ls -la \"<run>/work/L3/c/w\"",
      "exit_code": 0,
      "path": null,
      "tool": "Bash"
     },
     {
      "command": null,
      "exit_code": null,
      "path": "<run>\\work\\L3\\c\\w\\groceries.csv",
      "tool": "Read"
     }
    ],
    "relearned": [],
    "resurfaced": []
   },
   "after_restore": {
    "actions": [
     {
      "command": null,
      "exit_code": null,
      "path": null,
      "tool": "Grep"
     },
     {
      "command": null,
      "exit_code": null,
      "path": null,
      "tool": "Glob"
     },
     {
      "command": null,
      "exit_code": null,
      "path": "<run>\\work\\L3\\c\\w\\budget.csv",
      "tool": "Read"
     },
     {
      "command": null,
      "exit_code": null,
      "path": "<run>\\work\\L3\\c\\w\\meal-plan.md",
      "tool": "Read"
     },
     {
      "command": null,
      "exit_code": null,
      "path": "<run>\\work\\L3\\c\\w\\README.md",
      "tool": "Read"
     },
     {
      "command": "ls && cat groceries.csv 2>/dev/null",
      "exit_code": 0,
      "path": null,
      "tool": "Bash"
     }
    ],
    "relearned": [],
    "resurfaced": []
   },
   "backup_before": {
    "external_copy": true,
    "manifest_digest": "b53f700401d744108f0aef36267fc1c915202a8027ab574e4e3f4c4ad907207b",
    "store_hits_before": 12
   },
   "delivered_after_forget": false,
   "delivered_after_restore": false,
   "demonstrated": true,
   "forget": {
    "backup_state": "verified",
    "purge_state": "completed",
    "purged_count": 15,
    "quarantined_count": 0
   },
   "restore": {
    "applied_schema": 12,
    "deleted_backup_ids": [],
    "limits": [
     "external_copy_holds_suppressed_content",
     "external_exports_not_recallable",
     "remote_provider_copies_not_recallable",
     "operator_backup_copies_not_recallable",
     "filesystem_forensics_outside_guarantee",
     "ledger_digest_membership_disclosure",
     "paraphrase_not_detected"
    ],
    "preserved_tombstone_epoch": 1,
    "restored_revision": 160,
    "source_contains_suppressed": true,
    "suppressed_record_count": 15
   },
   "route": "the guarded CLI with the operator token (live)",
   "scenario": "smoke-L3-household-grocery-budget",
   "selector": {
    "claims": 1,
    "tasks": 1
   },
   "stopped_after": {
    "exit": 0,
    "state": "stopped"
   },
   "stopped_before_backup": {
    "exit": 0,
    "state": "not_running"
   },
   "stopped_before_restore": {
    "exit": 0,
    "state": "stopped"
   },
   "store_hits_after_forget": 0,
   "store_hits_after_restore": 0,
   "suspended": []
  },
  "fresh_session_reuse": {
   "criterion": "a learning scenario whose candidate succeeded with no repeated mistake and whose fresh session B carried the scenario's gold text in a delivered packet; any one of the learning scenarios demonstrates it (decision 0028 items 16 and 20). Whether the clean baseline, in the same session, failed or repeated session A's mistake is reported as made_a_difference, never required: the frozen scenarios leave each answer in the repository, so a capable agent can recover it without memory",
   "demonstrated": true,
   "made_a_difference_in": [],
   "met_by": [
    "smoke-L1-ledgerlite-test-command",
    "smoke-L2-fieldnotes-iso-dates",
    "smoke-L3-household-grocery-budget",
    "smoke-L4-ledgerlite-resume-refactor"
   ],
   "not_run": [],
   "note": "one trial per arm: a demonstration that reuse happened, not an estimate of its benefit (a Cut 2 comparison). The gold text may arrive in any packet of session B (L1's session-start point is unmet by design, decision 0013, and its prompt packet carries the lesson)",
   "remember_instruction": false,
   "scenarios": {
    "smoke-L1-ledgerlite-test-command": {
     "admitted": [
      "Running `python -m unittest discover -s tests` from the project root, without PYTHONPATH=src, ends with FAILED (errors=1).",
      "Running `PYTHONPATH=src python -m unittest discover -s tests -v` from the project root reports Ran 2 tests and OK."
     ],
     "baseline_repeated_mistakes": 0,
     "baseline_task_success": true,
     "candidate_repeated_mistakes": 0,
     "candidate_task_success": true,
     "carried_in_session_b": [
      "PYTHONPATH=src"
     ],
     "errors": [],
     "gold_in_session_b": [
      "PYTHONPATH=src"
     ],
     "made_a_difference": false,
     "met": true
    },
    "smoke-L2-fieldnotes-iso-dates": {
     "admitted": [
      "Reading the code, tools/check.py gets NOTES_HOME from the environment as os.environ[\"NOTES_HOME\"] and sets no default for it.",
      "Every date fieldnotes prints must be ISO-8601 (YYYY-MM-DD...). Never use locale formats like 'Jan 2' or '02/01/2026'."
     ],
     "baseline_repeated_mistakes": 0,
     "baseline_task_success": true,
     "candidate_repeated_mistakes": 0,
     "candidate_task_su
```

## Unsuccessful runs


## Cost and time

```json
{
 "actual": {
  "background_model_calls": 189,
  "background_tokens": 4325051,
  "elapsed_seconds": 650.0,
  "foreground_cost_usd": 1.7641,
  "foreground_sessions": 48,
  "mode": "live",
  "provider_cost_note": "foreground: the host's reported session cost; background: tokens from the budget ledger (provider-reported where available), not priced here",
  "provider_cost_usd": null
 },
 "illustrative_estimate": {
  "comparative_smoke_cost_usd": 28.12,
  "comparative_smoke_sessions": 60.0,
  "inputs": {
   "background_share": 0.25,
   "foreground_cost_per_session_usd": 0.3,
   "minutes_per_session": 4,
   "overhead": 0.25,
   "sessions_per_scenario": 2.5
  },
  "label": "ACCEPTANCE_TESTS \u00a76.2 arithmetic, not measured costs or current prices",
  "serial_hours": 4.0
 },
 "pilot": {
  "reason": null,
  "state": "see actual"
 }
}
```

## Versions, authorship and native memory

```json
{
 "authorship": {
  "held_out": "none (full release; intentionally empty)",
  "recorded_proposals": "evals/curator.py, authored by the coding agent; not a model",
  "sensitivity": "the four baseline-sensitivity scenarios (decision 0049), written by the same coding agent; reported beside the gate, never part of it",
  "smoke": {
   "independent_of_system_spec_7": false,
   "note": "the 12 smoke scenarios were written by the repository's coding agent, who has read SYSTEM_SPEC \u00a77; development fixtures, not held out",
   "route": [
    "repository author (coding agent)"
   ]
  },
  "workload_days": "synthetic representative days authored by the coding agent (evals/workload/days); not recorded real sessions"
 },
 "baselines": {
  "not_run": {
   "breadcrumbs": "full release only",
   "notes": "full release only"
  },
  "run": [
   "candidate",
   "no_memory"
  ]
 },
 "native_memory": {
  "configuration": "the live trials' own session flags, disposable HOME and environment",
  "installed_host_observation": {
   "configuration": {
    "env": [
     "CLAUDE_CODE_DISABLE_AUTO_MEMORY"
    ],
    "session_args": "the live trials' session flags",
    "settings": {
     "autoMemoryEnabled": false
    }
   },
   "control": {
    "exit": 0,
    "message_requests": 1,
    "sentinel_seen": true
   },
   "disabled": {
    "exit": 0,
    "message_requests": 1,
    "sentinel_seen": false
   },
   "host_version": "2.1.321 (Claude Code)",
   "method": "request capture (loopback endpoint, placeholder key); planted MEMORY.md sentinel",
   "state": "disabled"
  }
 },
 "versions": {
  "allow_dirty": false,
  "certified_capture_versions": [
   "2.1.301",
   "2.1.305",
   "2.1.306",
   "2.1.309",
   "2.1.310",
   "2.1.321"
  ],
  "commit": "e311bc79be6bbcd3a40de08f188c656192ee4456",
  "engine": "0.1.0.dev19",
  "inputs": {
   "oracles": {
    "evals/oracles/__init__.py": "1ca86d254ffd5a82dd797a1adde945256b5f6162d69af4b41fe2c9e3bcf66170",
    "evals/oracles/smoke.py": "e4381d7b5a7b4fe83ff57e5bcb0fdadabeb15d5fe434cf8abc5ff93e3b1440bf"
   },
   "overlays": {
    "evals/scenarios/smoke/overlays/fieldnotes_check_default_home.py": "f0d5358e316c54ed711a1d823b25005e0c4e397ad5b7bd95b1ce6deb673a9834",
    "evals/scenarios/smoke/overlays/fieldnotes_store_jsonl.py": "a8f7de820597d7876d48c1ebe28c3cefd786272e81b605e6285dda115f520afa",
    "evals/scenarios/smoke/overlays/ledgerlite_readme_typo.md": "3122301a17fb3963d92a5e1d671780e332d835c6a8b9db292706c027d3da6ebd",
    "evals/scenarios/smoke/overlays/ledgerlite_tests_init.py": "9a18dee89eb8357038b5af329467d086a2ec0c22b51ed721232ba4dfa526fe13"
   },
   "recorded_curator": "377201c115b6050b35e1981692c524e37fa81594a97178f5092429684baa39f2",
   "scenarios": {
    "evals/scenarios/smoke/smoke-C1-ledgerlite-routine-typo.json": "b52bf3d286098a9deffeebb3ec75345061b82dc7d5efe98282247cf80e4e9c79",
    "evals/scenarios/smoke/smoke-C2-fieldnotes-tdd-expected-red.json": "dcceeeee183e599b20c308d544720f4ebcf1be319cba466eb81362fdf990847f",
    "evals/scenarios/smoke/smoke-C3-household-utilities-speculation.json": "9ef57aedb0e6a019b96885766e801331e0d6641b0f729a8aadf43c970cc50c77",
    "evals/scenarios/smoke/smoke-C4-cross-project-near-match.json": "b5581a217f7f7f19c06331dd3236271ae3a29884447e6818477bfbd291ee7613",
    "evals/scenarios/smoke/smoke-L1-ledgerlite-test-command.json": "38dd1104695a3f5ee94ccc6f26df902665b256406e9894bb568b319b119a20f9",
    "evals/scenarios/smoke/smoke-L2-fieldnotes-iso-dates.json": "1f2014466e8cef72c8ff0b7cf23c417a0d85d650dc66c14fc33122995b476d88",
    "evals/scenarios/smoke/smoke-L3-household-grocery-budget.json": "c043dd76d215c3cca093421b5c94e1de10a594b6c1a6c13547efe1e5ef6121bf",
    "evals/scenarios/smoke/smoke-L4-ledgerlite-resume-refactor.json": "7e02049980670e66a31eca5dd5bb4c7ea9accffac92019c9ae11be3e31d32655",
    "evals/scenarios/smoke/smoke-R1-fieldnotes-check-env-fixed.json": "230e096b7f4112b6e8dbf7ddf35177a5f21080357ee23c078f5ee20b423fb01c",
    "evals/scenarios/smoke/smoke-R2-ledgerlite-import-fixed.json": "0101125197bfa2075ab6a92a0f9a93be426a6681286b35758cf8549b370883dd",
    "evals/scenarios/smoke/smoke-R3-household-budget-correction.json": "5a1130dee2838b609bced574e45b78a89c1c5908027035ae6c91341a464878e7",
    "evals/scenarios/smoke/smoke-R4-fieldnotes-storage-conflict.json": "d32b42b3e0a702f36ef0a26b74d207dc843eeec347fcfcb94d53436439f0388d"
   },
   "scripted_agent": "cfbb1192704ee8c0150b91446ab5749d4ed42e4a8daea73eab9b74fbf6eb780b",
   "sensitivity_overlays": {
    "evals/scenarios/sensitivity/overlays/fieldnotes_check_jobs.py": "2d8d3756e25dacceb5fce81b2aaca5684e608ea03d5f6b2c3bccd284eeb3420e",
    "evals/scenarios/sensitivity/overlays/household_meal_plan_next_week.md": "a00410e07080203a74b8a3f5c8ad180e6ac5ef648c4721d3cb10e8dfc5a422fe"
   },
   "sensitivity_scenarios": {
    "evals/scenarios/sensitivity/sens-S1-ledgerlite-amounts-in-cents.json": "52f6345fd81cc180c6ce33220e155a979bb6ce6dc78697fdac760f0b693c4c25",
    "evals/scenarios/sensitivity/sens-S2-household-no-prices-in-meal-plan.json": "782eba1db7761fd993220e6202031930f6ce3bb5f4ab9a141713c7c458e4edfd",
    "evals/scenarios/sensitivity/sens-S3-fieldnotes-checks-one-job.json": "c3febdb851e686112d30a74febe3712d4590b11b8c562a56af008314b46ec2b3",
    "evals/scenarios/sensitivity/sens-S4-fieldnotes-frozen-notes-format.json": "c2a5961037610ac8a3c10deb59339caeb0bf2307b254223b094118332fb61489"
   },
   "workload_days": {
    "evals/workload/days/fieldnotes.json": "17dbdef0be4e606f5e8929e9142d467352514f30e1ceb4a2fab00e0426cb3d93",
    "evals/workload/days/household.json": "bfc4216746f30869394c8547af3bece4a73698824270cbff001bf333e7125122",
    "evals/workload/days/ledgerlite.json": "c597a60438c2ab7feebe9ce438cf277f5d6a1199d6315efd4c669e8914851de9"
   }
  },
  "installed_host": "2.1.321 (Claude Code)",
  "platform": "Windows 11 AMD64",
  "prompts": {
   "build_episode": "build_episode@2",
   "extract_claims": "extract_claims@7",
   "revalidate": "revalidate@4",
   "review_claims": "review_claims@2",
   "update_task": "update_task@2"
  },
  "python": "3.13.15",
  "schema": 12,
  "scripted_payload_format": "Claude Code 2.1.305 (reviewed fixtures)",
  "sqlite": "3.50.4",
  "tree_clean": true
 }
}
```

## Limitations

- Smoke scenarios, gold labels and workload days were authored by the coding agent, who has read SYSTEM_SPEC §7; no held-out or independent corpus exists.
- One trial per arm and 12 scenarios: intervals are wide and inconclusive by construction; no superiority claim is made.
- The four baseline-sensitivity scenarios (decision 0049) are reported in their own section and never count toward the gate; the same coding agent wrote them, and their named-mistake measure is one trial per arm.
- Each candidate installation's route is certified live for that installation; its host record is bound from the source project's live engine-mode certification for the same host version, model and configuration (decision 0028), not re-observed per installation.
- Sessions run on real time. Between sessions the harness waits until the hook-started worker owes nothing due within 20 minutes (or 45 minutes pass, or progress stalls for 5); the scenarios' two-hour gaps are not reproduced.
- Delivered context is read from the host's hook_response records (the hook's exact stdout as the host received it); that the model saw it is the separate canary certification, not re-checked per trial.
- Workload days replay synthetic recorded timelines in process through the real stdlib hook path (no host session); scheduling runs on the day's virtual clock while every curator call is real.
- Background tokens come from the budget ledger (provider-reported where the call reported usage); foreground cost is the host's own reported session cost.
- On native Windows a hook-started worker runs inside the venv redirector's job (decision 0027 item 8): recovery is degraded while it runs.
