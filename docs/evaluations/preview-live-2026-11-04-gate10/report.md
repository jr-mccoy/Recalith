# Preview evaluation report (live)

**live working agent and certified inference route.** Counts toward the preview gate: **True**. Gate: **failed**.

- claims_unadjudicated:30 (evals/run.py adjudicate)

## Paired outcomes (candidate vs clean no-memory baseline)

| Scenario | Success C/B | Repeated mistakes C/B | Detours C/B | Retry C/B | Foreground tok C/B | Background tok C | Elapsed s C/B | Labels C/B |
|---|---|---|---|---|---|---|---|---|
| smoke-C1-ledgerlite-routine-typo | yes/yes | 0/0 | 0/0 | –/– | 124023/123540 | 142782 | 22.4/17.3 | candidate/no_memory |
| smoke-C2-fieldnotes-tdd-expected-red | yes/yes | 0/0 | 1/0 | –/– | 398066/250259 | 367352 | 79.0/51.5 | candidate/no_memory |
| smoke-C3-household-utilities-speculation | yes/yes | 0/0 | 0/0 | –/– | 72137/71712 | 92712 | 23.5/21.9 | candidate/no_memory |
| smoke-C4-cross-project-near-match | yes/yes | 0/0 | 0/0 | –/– | 205553/180073 | 151429 | 32.0/27.4 | candidate/no_memory |
| smoke-L1-ledgerlite-test-command | yes/yes | 0/0 | 0/0 | –/– | 186831/166049 | 285465 | 32.5/26.2 | candidate/no_memory |
| smoke-L2-fieldnotes-iso-dates | yes/yes | 0/0 | 0/0 | –/– | 202964/151390 | 394440 | 34.1/26.7 | candidate/no_memory |
| smoke-L3-household-grocery-budget | yes/yes | 0/0 | 0/1 | –/– | 150987/144239 | 168620 | 39.1/30.9 | candidate/no_memory |
| smoke-L4-ledgerlite-resume-refactor | yes/yes | 0/0 | 0/0 | –/– | 170022/184308 | 236381 | 31.5/30.9 | candidate/no_memory |
| smoke-R1-fieldnotes-check-env-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 128369/106222 | 221301 | 27.5/17.5 | candidate/no_memory |
| smoke-R2-ledgerlite-import-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 129316/146865 | 177140 | 22.5/21.1 | candidate/no_memory |
| smoke-R3-household-budget-correction | yes/no | 0/0 | 0/0 | –/– | 55176/54113 | 94721 | 20.9/15.9 | candidate/no_memory |
| smoke-R4-fieldnotes-storage-conflict | yes/yes | 0/0 | 0/0 | –/– | 225588/148861 | 300600 | 33.8/29.6 | candidate/no_memory |

Paired differences (candidate − baseline), mean with a 95 % interval from resampling whole scenarios:

- task_success: n=12, mean=0.0833, CI95=(0.0, 0.25), inconclusive
- repeated_mistakes: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- detours: n=12, mean=0.0, CI95=(-0.25, 0.25), inconclusive
- legitimate_retry_success: n=2, mean=0.0, CI95=(0.0, 0.0), inconclusive
- foreground_tokens: n=12, mean=26783.4167, CI95=(4570.0833, 52757.8333)
- background_tokens: n=12, mean=219411.9167, CI95=(165692.0833, 273038.25)
- elapsed_seconds: n=12, mean=6.828, CI95=(3.7277, 11.0004)
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

Support and recall come from reviewer labels (`adjudication.json`); 30 item(s) unlabeled (`evals/run.py adjudicate`). Lessons whose evidence never occurred: 0. fewer than two independent reviewers (ACCEPTANCE_TESTS §5: report the limitation)
Term match (provisional, frozen against the recorded curator's wording): supported_precision 9/22, useful_recall 7/8, failed_approach_recall 2/3

## Curator call outcomes

```json
{
 "smoke": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 22,
    "replies_parsed": 22,
    "reported_input_tokens": 711445,
    "reported_output_tokens": 38545,
    "visible_output_estimate": 11833
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 25,
    "replies_parsed": 25,
    "reported_input_tokens": 866256,
    "reported_output_tokens": 57686,
    "visible_output_estimate": 10960
   },
   "revalidate": {
    "at_output_cap": 0,
    "calls": 5,
    "replies_parsed": 5,
    "reported_input_tokens": 60845,
    "reported_output_tokens": 4753,
    "visible_output_estimate": 941
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 15,
    "replies_parsed": 15,
    "reported_input_tokens": 122263,
    "reported_output_tokens": 24131,
    "visible_output_estimate": 5011
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 23,
    "replies_parsed": 23,
    "reported_input_tokens": 695768,
    "reported_output_tokens": 51251,
    "visible_output_estimate": 14060
   }
  },
  "job_errors": {
   "revalidate:coalesced": 2
  }
 },
 "workload": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 25,
    "replies_parsed": 25,
    "reported_input_tokens": 618937,
    "reported_output_tokens": 49537,
    "visible_output_estimate": 14463
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 46,
    "replies_parsed": 46,
    "reported_input_tokens": 1313720,
    "reported_output_tokens": 52132,
    "visible_output_estimate": 7997
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 8,
    "replies_parsed": 8,
    "reported_input_tokens": 43357,
    "reported_output_tokens": 8949,
    "visible_output_estimate": 1556
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 22,
    "replies_parsed": 22,
    "reported_input_tokens": 503885,
    "reported_output_tokens": 44880,
    "visible_output_estimate": 12816
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
    "n": 93,
    "p50": 0.0,
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
   "admitted_claims": 4,
   "calls": 40,
   "calls_by_purpose": {
    "build_episode": 10,
    "extract_claims": 19,
    "review_claims": 3,
    "update_task": 8
   },
   "calls_per_admitted_claim": 10.0,
   "calls_per_settled_episode": 4.444,
   "estimated_tokens_by_purpose": {
    "build_episode": 158583,
    "extract_claims": 384037,
    "review_claims": 12131,
    "update_task": 112858
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 26.552,
     "n": 40,
     "p50": 8.842,
     "p95": 16.565
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
       "reason": "review_supported"
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
     "no_op_reason": "The NOTES_HOME failure and the file-reads-NOTES_HOME fact are already recorded as active claims, and the session contains no user declaration or new durable project knowledge.",
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
     "no_op_reason": "Durable knowledge from this session is already recorded: the NOTES_HOME failure lesson, the check.py NOTES_HOME fact, and the ISO date decision. The date-format failure is not shown to be fixed and its cause is unconfirmed, so no new claim is supported.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's durable knowledge (check.py needs NOTES_HOME, and reads it) is already recorded as active claims. The export test failure on the date format is a single unresolved failure whose cause is not shown, and the user's date decision is already recorded, so no new claim is well supported.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The request's events show a failing check run and a test traceback, but the durable project facts they support (the NOTES_HOME dependency and the NOTES_HOME failure lesson) are already recorded as active claims, and the date-format decision is already recorded. The remaining test-output finding is an unexplained, in-progress result with no declared file path in the events, so it is not recorded as",
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
     "malformed": [
      {
       "detail": "reason:missing",
       "index": 0,
       "local_ref": "update-task-narrative",
       "reason": "malformed_operation"
      }
     ],
     "operations": [],
     "purpose": "update_task"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's only user statement is a task-level instruction to use TDD for one feature, which is not a durable project rule. The delete-command test failure was a single unresolved run with no proven cause, and the NOTES_HOME facts it touches are already recorded as claims.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "No new durable project knowledge: the session's events are tool calls and session lifecycle with no citable user declaration, and the failing run is an in-progress TDD red test rather than a lasting lesson. Existing claims already cover the NOTES_HOME behavior and the date format decision.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "No durable project knowledge is supported by the allowed evidence. The task objective cites an event outside allowed_evidence_refs, the recorded test failure has no exact argv and is one call's result, and the file reads and edits show no lasting project fact.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "This session's events are file reads, one edit, and one unparsed Bash run that failed with a unittest traceback. None of it is a user statement, and the run does not support a new durable project claim.",
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
     "no_op_reason": "The request's events show a failing check run, reads and one in-progress edit, but no durable user declaration or verified project fact beyond what existing claims already record. The task objective cites an event that is not in allowed_evidence_refs, so it cannot be used.",
     "operations": [],
     "purpose": "extract_claims"
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
     "no_op_reason": "The request's events show only tool reads and edits, one failing Bash run whose recorded command is unparsed, and no user statement in the cited events. Nothing new is durable beyond the existing claims.",
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
     "decisions": [],
     "no_op_reason": "The only user statement is the session objective, already recorded as claim_865f39cc. The remaining events are file reads, edits, and one unresolved test_roundtrip failure whose cause is not shown, so no new durable claim is supported.",
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
       "tools/check.py reads the NOTES_HOME environment variable at line 24.",
       "active",
       "current",
       2
      ],
      [
       "Running `python tools/check.py` with NOTES_HOME unset fails with KeyError: 'NOTES_HOME' at tools/check.py:24.",
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
         "text": "Fact: tools/check.py reads the NOTES_HOME environment variable at line 24."
        },
        {
         "advice": "context",
         "freshness": "current",
         "text": "Failure lesson: Running `python tools/check.py` with NOTES_HOME unset fails with KeyError: 'NOTES_HOME' at tools/check.py:24. Observed: Running `python tools/ch"
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
       "The user runs this project's tests with `python -m unittest discover -s tests -t .`.",
       "candidate",
       "current",
       2
      ],
      [
       "The user prefers that the test command not be changed if possible.",
       "active",
       "current",
       2
      ],
      [
       "tests/__init__.py inserts the src/ directory into sys.path so that the ledgerlite package can be imported by the tests.",
       "candidate",
       "current",
       2
      ],
      [
       "Running `python -m unittest discover -s tests -t .` with tests/__init__.py present ends with 'Ran 2 tests' and 'OK'.",
       "active",
       "current",
       2
      ],
      [
       "Running `python -m unittest discover -s tests -t .` without tests/__init__.py fails with 'Start directory is not importable'.",
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
         "text": "Fact: Running `python -m unittest discover -s tests -t .` without tests/__init__.py fails with 'Start directory is not importable'."
        },
        {
         "advice": "context",
         "freshness": "needs_revalidation",
         "text": "Fact: Running `python -m unittest discover -s tests -t .` with tests/__init__.py present ends with 'Ran 2 tests' and 'OK'."
        },
        {
         "advice": "context",
         "freshness": "current",
         "text": "Preference: The user prefers that the test command not be changed if possible."
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
      "command": "ls && cat groceries.csv 2>/dev/null | head -100",
      "exit_code": 0,
      "path": null,
      "tool": "Bash"
     },
     {
      "command": "cd <run>/work/L3/c/w && awk -F, 'NR>1{s+=$2}END{print s}' groceries.csv",
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
      "command": "cd \"<run>/work/L3/c/w\" && ls && cat groceries.csv 2>/dev/null | head -80",
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
    "manifest_digest": "ddac1c7ed92dd3372b56ce8ae1862b757b76946bcd8447406116c1254b12f853",
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
    "restored_revision": 123,
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
      "In the recorded run, running `PYTHONPATH=src python -m unittest 
```

## Unsuccessful runs

- {'scenario': 'smoke-R3-household-budget-correction', 'arm': 'no_memory', 'reason': 'task_failed'}

## Cost and time

```json
{
 "actual": {
  "background_model_calls": 191,
  "background_tokens": 4289417,
  "elapsed_seconds": 715.4,
  "foreground_cost_usd": 1.7537,
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
  "commit": "d8a4bbcb7d8fb19c9f0850a49d5eb858585b4702",
  "engine": "0.1.0.dev10",
  "installed_host": "2.1.310 (Claude Code)",
  "platform": "Windows 11 AMD64",
  "prompts": {
   "build_episode": "build_episode@2",
   "extract_claims": "extract_claims@7",
   "revalidate": "revalidate@3",
   "review_claims": "review_claims@2",
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
