# Preview evaluation report (live)

**live working agent and certified inference route.** Counts toward the preview gate: **True**. Gate: **failed**.

- claims_unadjudicated:32 (evals/run.py adjudicate)

## Paired outcomes (candidate vs clean no-memory baseline)

| Scenario | Success C/B | Repeated mistakes C/B | Detours C/B | Retry C/B | Foreground tok C/B | Background tok C | Elapsed s C/B | Labels C/B |
|---|---|---|---|---|---|---|---|---|
| smoke-C1-ledgerlite-routine-typo | yes/yes | 0/0 | 0/0 | –/– | 124771/123706 | 140954 | 19.6/15.0 | candidate/no_memory |
| smoke-C2-fieldnotes-tdd-expected-red | yes/yes | 0/0 | 0/0 | –/– | 288710/293750 | 345931 | 55.6/53.8 | candidate/no_memory |
| smoke-C3-household-utilities-speculation | yes/yes | 0/0 | 0/0 | –/– | 73360/71851 | 91511 | 24.7/22.0 | candidate/no_memory |
| smoke-C4-cross-project-near-match | yes/yes | 0/0 | 0/0 | –/– | 191613/161728 | 104262 | 31.1/21.8 | candidate/no_memory |
| smoke-L1-ledgerlite-test-command | yes/yes | 0/0 | 0/0 | –/– | 200199/166021 | 262020 | 25.4/23.7 | candidate/no_memory |
| smoke-L2-fieldnotes-iso-dates | yes/yes | 0/0 | 0/0 | –/– | 185470/152783 | 322105 | 32.6/27.8 | candidate/no_memory |
| smoke-L3-household-grocery-budget | yes/yes | 0/0 | 1/0 | –/– | 156495/150555 | 206660 | 43.3/37.7 | candidate/no_memory |
| smoke-L4-ledgerlite-resume-refactor | yes/yes | 0/0 | 0/0 | –/– | 169154/205102 | 232582 | 31.1/29.7 | candidate/no_memory |
| smoke-R1-fieldnotes-check-env-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 108795/125051 | 214806 | 21.1/17.3 | candidate/no_memory |
| smoke-R2-ledgerlite-import-fixed | yes/no | 0/0 | 0/0 | yes/no | 130152/126834 | 208572 | 23.1/19.1 | candidate/no_memory |
| smoke-R3-household-budget-correction | yes/yes | 0/0 | 0/0 | –/– | 56414/55502 | 95915 | 23.5/21.4 | candidate/no_memory |
| smoke-R4-fieldnotes-storage-conflict | yes/yes | 0/0 | 0/0 | –/– | 147158/148762 | 258528 | 29.9/25.8 | candidate/no_memory |

Paired differences (candidate − baseline), mean with a 95 % interval from resampling whole scenarios:

- task_success: n=12, mean=0.0833, CI95=(0.0, 0.25), inconclusive
- repeated_mistakes: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- detours: n=12, mean=0.0833, CI95=(0.0, 0.25), inconclusive
- legitimate_retry_success: n=2, mean=0.5, CI95=(0.0, 1.0), inconclusive
- foreground_tokens: n=12, mean=4220.5, CI95=(-6428.75, 14789.5833), inconclusive
- background_tokens: n=12, mean=206987.1667, CI95=(159855.75, 249683.9167)
- elapsed_seconds: n=12, mean=3.8368, CI95=(2.7348, 5.1292)
- operator_interventions: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- repeated failures on relevant scenarios: candidate 0, baseline 0, relative reduction None (>= 0.25 (Cut 2 gate; not a preview gate))

No superiority claim: a 12-scenario smoke run with one trial per arm cannot establish one (ACCEPTANCE_TESTS §6.1).

## §5.1 quality on the smoke population

| Measure | Value | Numerator/denominator | Wilson 95 % | Target | Met |
|---|---|---|---|---|---|
| supported_precision | – | 0/0 | None | >= 0.95 | None |
| useful_recall | – | 0/0 | None | >= 0.85 | None |
| failed_approach_recall | – | 0/0 | None | >= 0.9 | None |
| incorrect_confident_guidance | 0 | count over 12 | None | == 0 | True |
| conflict_uncertainty_preservation | 1 | 1/1 | (0.2065, 1.0) | >= 0.95 | True |
| legitimate_retry_discouraged | 0 | 0/2 | (0.0, 0.6576) | <= 0.05 | True |
| irrelevant_caution_quiet | 0 | 0/3 | (0.0, 0.5615) | <= 0.05 | True |
| routine_human_maintenance | 0 | count over 12 | None | == 0 | True |

Support and recall come from reviewer labels (`adjudication.json`); 32 item(s) unlabeled (`evals/run.py adjudicate`). Lessons whose evidence never occurred: 0. fewer than two independent reviewers (ACCEPTANCE_TESTS §5: report the limitation)
Term match (provisional, frozen against the recorded curator's wording): supported_precision 7/24, useful_recall 6/8, failed_approach_recall 2/3

## Curator call outcomes

```json
{
 "smoke": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 21,
    "replies_parsed": 21,
    "reported_input_tokens": 600541,
    "reported_output_tokens": 38639,
    "visible_output_estimate": 12482
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 26,
    "replies_parsed": 26,
    "reported_input_tokens": 831528,
    "reported_output_tokens": 66969,
    "visible_output_estimate": 14021
   },
   "revalidate": {
    "at_output_cap": 0,
    "calls": 6,
    "replies_parsed": 6,
    "reported_input_tokens": 79494,
    "reported_output_tokens": 7827,
    "visible_output_estimate": 1431
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 17,
    "replies_parsed": 17,
    "reported_input_tokens": 150418,
    "reported_output_tokens": 24497,
    "visible_output_estimate": 5667
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 23,
    "replies_parsed": 23,
    "reported_input_tokens": 635464,
    "reported_output_tokens": 48469,
    "visible_output_estimate": 13109
   }
  },
  "job_errors": {
   "revalidate:coalesced": 3
  }
 },
 "workload": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 28,
    "replies_parsed": 25,
    "reported_input_tokens": 638489,
    "reported_output_tokens": 51781,
    "visible_output_estimate": 14802
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 47,
    "replies_parsed": 46,
    "reported_input_tokens": 1287548,
    "reported_output_tokens": 52994,
    "visible_output_estimate": 8586
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 8,
    "replies_parsed": 7,
    "reported_input_tokens": 44684,
    "reported_output_tokens": 7944,
    "visible_output_estimate": 1831
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 24,
    "replies_parsed": 23,
    "reported_input_tokens": 534687,
    "reported_output_tokens": 46310,
    "visible_output_estimate": 12534
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
    "n": 6,
    "p50": 1.0,
    "p95": 1.0
   },
   "ordinary": {
    "max": 4.0,
    "n": 99,
    "p50": 1.0,
    "p95": 4.0
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
   "admitted_claims": 3,
   "calls": 42,
   "calls_by_purpose": {
    "build_episode": 11,
    "extract_claims": 20,
    "review_claims": 2,
    "update_task": 9
   },
   "calls_per_admitted_claim": 14.0,
   "calls_per_settled_episode": 4.667,
   "estimated_tokens_by_purpose": {
    "build_episode": 253409,
    "extract_claims": 406969,
    "review_claims": 9352,
    "update_task": 138175
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 26.138,
     "n": 42,
     "p50": 8.51,
     "p95": 16.811
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
       "kind": "propose_claim",
       "outcome": "apply",
       "reason": "observed_mapping"
      },
      {
       "kind": "propose_claim",
       "outcome": "candidate_only",
       "reason": "candidate_pending_review"
      },
      {
       "kind": "propose_claim",
       "outcome": "candidate_only",
       "reason": "candidate_pending_review"
      }
     ],
     "operations": [
      "propose_claim",
      "propose_claim",
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
      },
      {
       "kind": "assess_claim",
       "outcome": "apply",
       "reason": "review_rejected"
      }
     ],
     "operations": [
      "assess_claim",
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
     "decisions": [],
     "no_op_reason": "The existing failure_lesson and exit-code fact already cover the KeyError on the unset-NOTES_HOME run. The later passing rerun has no exact exit code or parsed assertion, and its output reports a NOTES_HOME value that differs from the one set, so it does not support a durable claim.",
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
     "no_op_reason": "Durable knowledge from this session is already recorded: the NOTES_HOME failure lesson, the first-run exit code, and the ISO-8601 date decision. The passing run's command was unparsed, and the Jan 02 date-format cause is unverified.",
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
     "no_op_reason": "The durable facts from this session are already recorded as active claims: the NOTES_HOME KeyError failure lesson, the exit-code-1 fact, and the ISO-8601 date decision. The test_export failure is a transient in-progress result with an unexplained test-count discrepancy, so it is too weak to propose.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's only durable-looking results are a failing run (test_export printing 'Jan 02' instead of ISO) and a passing run reporting a different test count, with the discrepancy unexplained. Neither supports a claim without overreaching, and the NOTES_HOME failure is already recorded by an existing claim. The user's stated objective is not citable from the allowed evidence refs.",
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
     "no_op_reason": "The session carried out one task-specific TDD change; its user message is a task instruction, not a standing project rule. The durable items it touches (NOTES_HOME failure, check.py exit behavior) are already recorded as existing claims.",
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
     "no_op_reason": "Existing claims already cover the NOTES_HOME failure, the first exit code 1, and the ISO-8601 date rule. The session's remaining results are a Bash run with no exact argv and no numeric exit code, and an Edit with no durable project statement. The TDD constraint cites an event that is not in allowed_evidence_refs, so it cannot be proposed.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's new evidence is one failing test run, already covered by existing claims, plus routine file reads and an edit. The stated objective cites an event that is not in allowed_evidence_refs, so it cannot be proposed here.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's tool results cover work in progress: a test failure in an unfinished change and reads of files. No new durable project fact, decision, preference or lesson is stated, and the existing claims already cover the NOTES_HOME failure and the exit-code observation.",
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
     "no_op_reason": "No new durable project knowledge: the session's one command exit and test failure are weak, unparsed observations, the task objective is not a project-wide declaration, and existing claims already cover the stated facts and decisions.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's durable knowledge is already captured by existing claims. The storage move is unfinished and the test is still failing, so no new durable fact, decision, or lesson is established.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "This session only read files, made one edit to fieldnotes/store.py, and ran one failing check; none of it yields a durable project fact, decision, or preference citable from allowed evidence. The task objective's source event is not in allowed_evidence_refs, and the existing NOTES_HOME failure lesson is already recorded.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "Narrative fields are empty and the evidence does not establish a clear plan, constraints, open questions, or next action; the latest episode shows passing tests, but completion is not established.",
     "operations": [],
     "purpose": "update_task"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The only tool-result event in allowed_evidence_refs is a failing test run whose output does not support a durable project fact, and the user's storage-change objective cites an event that is not in allowed_evidence_refs.",
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
     "
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
       "Running `python tools/check.py` from the project, without NOTES_HOME set, fails with KeyError: 'NOTES_HOME'.",
       "candidate",
       "current",
       9
      ],
      [
       "tools/check.py reads the NOTES_HOME environment variable directly and has no fallback when it is unset.",
       "active",
       "current",
       5
      ]
     ],
     "retry_point": [
      {
       "delivered": true,
       "items": [
        {
         "advice": "context",
         "freshness": "needs_revalidation",
         "text": "Fact: tools/check.py reads the NOTES_HOME environment variable directly and has no fallback when it is unset."
        },
        {
         "advice": "context",
         "freshness": "current",
         "text": "Failure lesson: Running `python tools/check.py` from the project, without NOTES_HOME set, fails with KeyError: 'NOTES_HOME'. Observed: Running `python tools/che"
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
      "revalidate:revise_claim"
     ],
     "task_success": true
    },
    "smoke-R2-ledgerlite-import-fixed": {
     "legitimate_retry_success": true,
     "lesson": [
      [
       "The user prefers the test command `python -m unittest discover -s tests -t .` to stay unchanged if possible, and otherwise wants to be told which command works.",
       "active",
       "current",
       2
      ],
      [
       "With a tests/__init__.py that inserts the sibling src directory into sys.path, running `python -m unittest discover -s tests -t .` from the project root reported 'Ran 2 tests' and 'OK'.",
       "active",
       "current",
       2
      ],
      [
       "The project keeps the ledgerlite package under src/ledgerlite and its unittest module under tests/test_ledger.py.",
       "active",
       "current",
       2
      ],
      [
       "Running `python -m unittest discover -s tests -t .` from the project root, while tests/ has no __init__.py, fails with 'ImportError: Start directory is not importable'.",
       "candidate",
       "current",
       2
      ],
      [
       "Running `python -m unittest discover -s tests -t .` from the project root, with an empty tests/__init__.py and no path setup for src/, fails with 'ModuleNotFoundError: No module named 'ledgerlite''.",
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
         "text": "Current task: Untitled task."
        },
        {
         "advice": "context",
         "freshness": "current",
         "text": "Fact: Running `python -m unittest discover -s tests -t .` from the project root, with an empty tests/__init__.py and no path setup for src/, fails with 'ModuleN"
        },
        {
         "advice": "context",
         "freshness": "current",
         "text": "Preference: The user prefers the test command `python -m unittest discover -s tests -t .` to stay unchanged if possible, and otherwise wants to be told which co"
        },
        {
         "advice": "context",
         "freshness": "current",
         "text": "Fact: The project keeps the ledgerlite package under src/ledgerlite and its unittest module under tests/test_ledger.py."
        },
        {
         "advice": "context",
         "freshness": "current",
         "text": "Fact: With a tests/__init__.py that inserts the sibling src directory into sys.path, running `python -m unittest discover -s tests -t .` from the project root r"
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
      "command": "ls -la && cat groceries.csv 2>&1 | head -60",
      "exit_code": 0,
      "path": null,
      "tool": "Bash"
     },
     {
      "command": "awk -F, 'NR>1{s+=$2;n++}END{print n, s}' groceries.csv",
      "exit_code": 0,
      "path": null,
      "tool": "Bash"
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
      "path": "<run>\\work\\L3\\c\\w\\README.md",
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
      "path": null,
      "tool": "Glob"
     },
     {
      "command": "cd \"<run>/work/L3/c/w\" && ls -p | grep -v /; ls -p | grep /; cat groceries.csv 2>&1 | head -60",
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
    "manifest_digest": "4f6e1601855310a604a3db1caa6e19a97aec53ef7047b00c29933f3d6efacccf",
    "store_hits_before": 12
   },
   "delivered_after_forget": false,
   "delivered_after_restore": false,
   "demonstrated": true,
   "forget": {
    "backup_state": "verified",
    "purge_state": "completed",
    "purged_count": 14,
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
    "restored_revision": 132,
    "source_contains_suppressed": true,
    "suppressed_record_count": 14
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
   "store_hits_after_restore": 0
  },
  "fresh_session_reuse": {
   "criterion": "a learning scenario whose candidate succeeded with no repeated mistake and whose fresh session B carried the scenario's gold text in a delivered packet; any one of the learning scenarios demonstrates it (decision 0028 items 16
```

## Unsuccessful runs

- {'scenario': 'smoke-R2-ledgerlite-import-fixed', 'arm': 'no_memory', 'reason': 'task_failed'}

## Cost and time

```json
{
 "actual": {
  "background_model_calls": 200,
  "background_tokens": 4336418,
  "elapsed_seconds": 676.0,
  "foreground_cost_usd": 1.6892,
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
   "host_version": "2.1.310 (Claude Code)",
   "method": "request capture (loopback endpoint, placeholder key); planted MEMORY.md sentinel",
   "state": "disabled"
  }
 },
 "versions": {
  "certified_capture_versions": [
   "2.1.301",
   "2.1.305",
   "2.1.306",
   "2.1.309",
   "2.1.310"
  ],
  "commit": "b17c75c1b6c1a32f0163e9056eeec6d089ad12d7",
  "engine": "0.1.0.dev9",
  "installed_host": "2.1.310 (Claude Code)",
  "platform": "Windows 11 AMD64",
  "prompts": {
   "build_episode": "build_episode@2",
   "extract_claims": "extract_claims@6",
   "revalidate": "revalidate@3",
   "review_claims": "review_claims@1",
   "update_task": "update_task@2"
  },
  "python": "3.13.15",
  "schema": 12,
  "scripted_payload_format": "Claude Code 2.1.305 (reviewed fixtures)",
  "sqlite": "3.50.4",
  "tree_clean": false
 }
}
```

## Limitations

- Smoke scenarios, gold labels and workload days were authored by the coding agent, who has read SYSTEM_SPEC §7; no held-out or independent corpus exists.
- One trial per arm and 12 scenarios: intervals are wide and inconclusive by construction; no superiority claim is made.
- Each candidate installation's route is certified live for that installation; its host record is bound from the source project's live engine-mode certification for the same host version, model and configuration (decision 0028), not re-observed per installation.
- Sessions run on real time. Between sessions the harness waits until the hook-started worker owes nothing due within 20 minutes (or 45 minutes pass, or progress stalls for 5); the scenarios' two-hour gaps are not reproduced.
- Delivered context is read from the host's hook_response records (the hook's exact stdout as the host received it); that the model saw it is the separate canary certification, not re-checked per trial.
- Workload days replay synthetic recorded timelines in process through the real stdlib hook path (no host session); scheduling runs on the day's virtual clock while every curator call is real.
- Background tokens come from the budget ledger (provider-reported where the call reported usage); foreground cost is the host's own reported session cost.
- On native Windows a hook-started worker runs inside the venv redirector's job (decision 0027 item 8): recovery is degraded while it runs.
