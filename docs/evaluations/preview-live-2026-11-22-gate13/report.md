# Preview evaluation report (live)

**live working agent and certified inference route.** Counts toward the preview gate: **True**. Gate: **failed**.

- demonstrations_unmet:changed_condition_revision,isolation
- claims_unadjudicated:21 (evals/run.py adjudicate)

## Paired outcomes (candidate vs clean no-memory baseline)

| Scenario | Success C/B | Repeated mistakes C/B | Detours C/B | Retry C/B | Foreground tok C/B | Background tok C | Elapsed s C/B | Labels C/B |
|---|---|---|---|---|---|---|---|---|
| smoke-C1-ledgerlite-routine-typo | yes/yes | 0/0 | 0/0 | –/– | 124103/123456 | 140872 | 22.8/30.1 | candidate/no_memory |
| smoke-C2-fieldnotes-tdd-expected-red | yes/yes | 0/0 | 2/0 | –/– | 399965/317912 | 473496 | 88.6/64.2 | candidate/no_memory |
| smoke-C3-household-utilities-speculation | yes/yes | 0/0 | 0/0 | –/– | 73206/72011 | 94000 | 22.3/32.6 | candidate/no_memory |
| smoke-C4-cross-project-near-match | yes/yes | 0/0 | 0/1 | –/– | 191280/178398 | 92677 | 28.4/27.2 | candidate/no_memory |
| smoke-L1-ledgerlite-test-command | yes/yes | 0/0 | 0/0 | –/– | 211648/164397 | 376668 | 30.2/26.1 | candidate/no_memory |
| smoke-L2-fieldnotes-iso-dates | yes/yes | 0/0 | 0/0 | –/– | 157380/153018 | 341066 | 24.9/26.6 | candidate/no_memory |
| smoke-L3-household-grocery-budget | no/yes | 0/0 | 0/1 | –/– | 145807/161561 | 159290 | 29.0/33.1 | candidate/no_memory |
| smoke-L4-ledgerlite-resume-refactor | yes/yes | 0/0 | 0/0 | –/– | 203764/164837 | 254181 | 28.6/29.0 | candidate/no_memory |
| smoke-R1-fieldnotes-check-env-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 109386/106552 | 169818 | 17.0/12.9 | candidate/no_memory |
| smoke-R2-ledgerlite-import-fixed | no/yes | 0/0 | 0/0 | no/yes | 154727/128733 | 177684 | 24.1/13.9 | candidate/no_memory |
| smoke-R3-household-budget-correction | yes/yes | 0/0 | 1/1 | –/– | 77275/129334 | 120360 | 23.9/24.6 | candidate/no_memory |
| smoke-R4-fieldnotes-storage-conflict | yes/yes | 0/0 | 0/0 | –/– | 162957/149211 | 227790 | 26.9/25.6 | candidate/no_memory |

Paired differences (candidate − baseline), mean with a 95 % interval from resampling whole scenarios:

- task_success: n=12, mean=-0.1667, CI95=(-0.4167, 0.0), inconclusive
- repeated_mistakes: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- detours: n=12, mean=0.0, CI95=(-0.3333, 0.4167), inconclusive
- legitimate_retry_success: n=2, mean=-0.5, CI95=(-1.0, 0.0), inconclusive
- foreground_tokens: n=12, mean=13506.5, CI95=(-4026.8333, 32123.0833), inconclusive
- background_tokens: n=12, mean=218991.8333, CI95=(157668.25, 285032.9167)
- elapsed_seconds: n=12, mean=1.7267, CI95=(-2.7514, 6.6642), inconclusive
- operator_interventions: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- repeated failures on relevant scenarios: candidate 0, baseline 0, relative reduction None (>= 0.25 (Cut 2 gate; not a preview gate))

No superiority claim: a 12-scenario smoke run with one trial per arm cannot establish one (ACCEPTANCE_TESTS §6.1).

## Baseline-sensitivity set (decision 0049; not part of the gate)

| Scenario | Success C/B | Repeated named mistake C/B | Repeated mistakes C/B | Foreground tok C/B | Errors |
|---|---|---|---|---|---|
| sens-S1-ledgerlite-amounts-in-cents | no/no | 1/1 | 0/0 | 284119/190879 |  |
| sens-S2-household-no-prices-in-meal-plan | yes/no | 0/1 | 0/0 | 196829/211205 |  |
| sens-S3-fieldnotes-checks-one-job | yes/no | 0/1 | 0/0 | 354007/270122 |  |
| sens-S4-fieldnotes-frozen-notes-format | yes/no | 0/1 | 0/0 | 329905/290957 |  |

Repeated named mistakes over 4 pair(s): candidate 1, baseline 4, relative reduction 0.75; task success candidate 3, baseline 0.

Not part of the preview gate (ACCEPTANCE_TESTS §6.1 fixes it at the frozen 12). Four scenarios, one trial per arm, written by the coding agent: this shows whether the corpus can register a repeated mistake, not that memory helps; no superiority claim.

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

Support and recall come from reviewer labels (`adjudication.json`); 21 item(s) unlabeled (`evals/run.py adjudicate`). Lessons whose evidence never occurred: 0. fewer than two independent reviewers (ACCEPTANCE_TESTS §5: report the limitation)
Term match (provisional, frozen against the recorded curator's wording): supported_precision 7/13, useful_recall 7/8, failed_approach_recall 2/3

## Curator call outcomes

```json
{
 "smoke": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 23,
    "replies_parsed": 23,
    "reported_input_tokens": 722052,
    "reported_output_tokens": 46567,
    "visible_output_estimate": 14052
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 28,
    "replies_parsed": 28,
    "reported_input_tokens": 912874,
    "reported_output_tokens": 55468,
    "visible_output_estimate": 9593
   },
   "revalidate": {
    "at_output_cap": 0,
    "calls": 3,
    "replies_parsed": 3,
    "reported_input_tokens": 38901,
    "reported_output_tokens": 3772,
    "visible_output_estimate": 544
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 14,
    "replies_parsed": 13,
    "reported_input_tokens": 85667,
    "reported_output_tokens": 15004,
    "visible_output_estimate": 3220
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 24,
    "replies_parsed": 24,
    "reported_input_tokens": 682478,
    "reported_output_tokens": 51625,
    "visible_output_estimate": 13961
   }
  },
  "job_errors": {
   "extract_claims:reevaluation_requeued": 1,
   "revalidate:coalesced": 1
  }
 },
 "workload": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 26,
    "replies_parsed": 26,
    "reported_input_tokens": 680953,
    "reported_output_tokens": 53896,
    "visible_output_estimate": 15393
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 46,
    "replies_parsed": 46,
    "reported_input_tokens": 1271154,
    "reported_output_tokens": 48596,
    "visible_output_estimate": 6948
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 7,
    "replies_parsed": 7,
    "reported_input_tokens": 37004,
    "reported_output_tokens": 6976,
    "visible_output_estimate": 1212
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 23,
    "replies_parsed": 23,
    "reported_input_tokens": 520705,
    "reported_output_tokens": 52077,
    "visible_output_estimate": 15447
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
    "n": 95,
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
   "admitted_claims": 2,
   "calls": 40,
   "calls_by_purpose": {
    "build_episode": 10,
    "extract_claims": 19,
    "review_claims": 2,
    "update_task": 9
   },
   "calls_per_admitted_claim": 20.0,
   "calls_per_settled_episode": 4.444,
   "estimated_tokens_by_purpose": {
    "build_episode": 172656,
    "extract_claims": 364767,
    "review_claims": 7823,
    "update_task": 123398
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 26.033,
     "n": 40,
     "p50": 7.114,
     "p95": 19.164
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
     "decisions": [],
     "no_op_reason": "The failure lesson for tools/check.py missing NOTES_HOME is already recorded as active claim claim_f82ab559 (revision 2). The later passing run shows no exit code or parsed assertion, so it supports no new observed fact, and the task objective is not a durable project fact.",
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
     "no_op_reason": "The durable failure lesson (NOTES_HOME KeyError) and the ISO-8601 date decision already exist as active claims. The session's remaining findings are one-off task progress and inferred test-output details, which are too weak to propose.",
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
     "no_op_reason": "The session's durable content is already covered by existing claims. The NOTES_HOME failure lesson is recorded, the ISO-8601 date decision is recorded, and the remaining events are a test-output mismatch and an unexplained test count without a stated project rule.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's events record no new user declaration, decision, or preference. The NOTES_HOME failure and the date-format rule are already captured by existing claims, and the later test output alone does not justify a new or contradicting claim.",
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
     "no_op_reason": "The session's durable content is already recorded: the ISO-8601 date decision and the NOTES_HOME failure lesson exist as claims. The delete-command work is task-specific progress, not a standing project fact, decision or preference.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "This session's events show only a test-failure run, an unparsed Bash run with exit status not recorded, and an edit. The only user statement of intent is in the task objective, whose evidence is not in allowed_evidence_refs, so nothing durable can be cited. The existing claims already cover the date format and the NOTES_HOME failure.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "This session only read files, made one Edit to fieldnotes/store.py, and ran a Bash check that exited 1. The user's storage objective is not cited by any allowed evidence ref, and the existing claims already cover the ISO date format and the NOTES_HOME failure.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's events show a storage-migration task in progress, a failing check run, and file reads and edits. None of it states a durable project fact, decision, preference or procedure beyond what existing claims already cover, and the one failing check result is transient.",
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
     "no_op_reason": "The session's events are file reads, one edit, and one failing test run with no user statement of a project rule, decision, or preference in the cited events, and the existing claims already cover the relevant facts.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's durable content is the in-progress task to move storage to notes.jsonl, which the task state already tracks. The test failure is an unexplained run without a confirmed cause, and the NOTES_HOME failure is already recorded in an existing claim.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "No new durable project knowledge: the session's tool results are a failing test run, reads, and two identical Edit calls, and the existing claims already cover the ISO date format and the NOTES_HOME failure. The task objective is not among the allowed evidence refs, so it cannot be cited. The boundary stays pending.",
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
     "no_op_reason": "No new durable user statement or verified project fact; the episode's objective is a task goal, the failed run's cause is unconfirmed, and existing claims already cover the stated facts.",
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
     "no_op_reason": "The session's durable failure fact is already recorded as claim_f82ab559, and the user's message is a task request rather than a stated project rule, decision, or preference. The cause of the first failure is unconfirmed, so no new lesson is warranted.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "Nothing new and durable: the NOTES_HOME failure is already
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
   "demonstrated": false,
   "scenarios": {
    "smoke-R1-fieldnotes-check-env-fixed": {
     "legitimate_retry_success": true,
     "lesson": [
      [
       "Running `python tools/check.py` without NOTES_HOME set fails with KeyError: 'NOTES_HOME' at tools/check.py line 25.",
       "candidate",
       "current",
       3
      ],
      [
       "tools/check.py reads the NOTES_HOME environment variable with os.environ[\"NOTES_HOME\"] at line 25 and prints it as \"using NOTES_HOME=...\".",
       "active",
       "current",
       3
      ]
     ],
     "retry_point": [
      {
       "delivered": true,
       "items": [
        {
         "advice": "context",
         "freshness": "needs_revalidation",
         "text": "Fact: tools/check.py reads the NOTES_HOME environment variable with os.environ[\"NOTES_HOME\"] at line 25 and prints it as \"using NOTES_HOME=...\"."
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
     "revalidation": [],
     "task_success": true
    },
    "smoke-R2-ledgerlite-import-fixed": {
     "legitimate_retry_success": false,
     "lesson": [
      [
       "The ledgerlite tests run with `python -m unittest discover -s tests -t .` from the project root once tests/__init__.py exists, and that run reported Ran 2 tests and OK.",
       "candidate",
       "current",
       2
      ],
      [
       "Running `python -m unittest discover -s tests -t .` from the project root, when tests/__init__.py is absent, fails with ImportError: Start directory is not importable.",
       "candidate",
       "current",
       2
      ]
     ],
     "retry_point": [
      {
       "delivered": true,
       "items": [],
       "satisfied": true,
       "spec": {
        "must_not_include_caution": "PYTHONPATH",
        "purpose": "prompt",
        "session": "C"
       }
      }
     ],
     "revalidation": [],
     "task_success": false
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
      "path": "<run>\\work\\L3\\c\\w\\README.md",
      "tool": "Read"
     },
     {
      "command": null,
      "exit_code": null,
      "path": "<run>\\work\\L3\\c\\w\\utilities-log.csv",
      "tool": "Read"
     },
     {
      "command": null,
      "exit_code": null,
      "path": "<run>\\work\\L3\\c\\w\\trip-ideas.md",
      "tool": "Read"
     },
     {
      "command": null,
      "exit_code": null,
      "path": null,
      "tool": "Grep"
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
      "command": "ls \"<run>/work/L3/c/w\"",
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
   "backup_before": {
    "external_copy": true,
    "manifest_digest": "845c7111e412155675ca20b73b01da781bf8a182b7e4fdd78009549baeed76a6",
    "store_hits_before": 15
   },
   "delivered_after_forget": false,
   "delivered_after_restore": false,
   "demonstrated": true,
   "forget": {
    "backup_state": "verified",
    "purge_state": "completed",
    "purged_count": 16,
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
    "restored_revision": 117,
    "source_contains_suppressed": true,
    "suppressed_record_count": 16
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
    "smoke-L4-ledgerlite-resume-refactor"
   ],
   "not_run": [],
   "note": "one trial per arm: a demonstration that reuse happened, not an estimate of its benefit (a Cut 2 comparison). The gold text may arrive in any packet of session B (L1's session-start point is unmet by design, decision 0013, and its prompt packet carries the lesson)",
   "remember_instruction": false,
   "scenarios": {
    "smoke-L1-ledgerlite-test-command": {
     "admitted": [
      "To run the ledgerlite unit tests, run `PYTHONPATH=src python -m unittest discover -s tests -v` from the project root."
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
      "tools/check.py reads NOTES_HOME with os.environ[\"NOTES_HOME\"] and prints it before running the unit tests.",
      "Every date fieldnotes prints must be ISO-8601 (YYYY-MM-DD...). Never use locale formats like 'Jan 2' or '02/01/2026'.",
      "The line-length rule in tools/check.py fails the check when any line in fieldnotes/**/*.py is longer than 100 characters."
     ],
     "baseline_repeated_mistakes": 0,
     "baseline_task_success": true,
     "candidate_repeated_mistakes": 0,
     "candidate_task_success": true,
     "carried_in_session_b": [
      "ISO-8601"
     ],
     "errors": [],
     "gold_in_session_b": [
      "ISO-8601"
     ],
     "made_a_difference": false,
     "met": true
    },
    "smoke-L3-household-grocery-budget": {
     "admitted": [
      "The user's household grocery budget is to be kept under $600 per month, and anything that would push grocery spending over it is to be flagged."
     ],
     "baseline_repeated_mistakes": 0,
     "baseline_task_success"
```

## Unsuccessful runs

- {'scenario': 'smoke-L3-household-grocery-budget', 'arm': 'candidate', 'reason': 'task_failed'}
- {'scenario': 'smoke-R2-ledgerlite-import-fixed', 'arm': 'candidate', 'reason': 'task_failed'}

## Cost and time

```json
{
 "actual": {
  "background_model_calls": 194,
  "background_tokens": 4304173,
  "elapsed_seconds": 712.8,
  "foreground_cost_usd": 1.7496,
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
  "commit": "7dc68d3fcddd4adc2c9946933649edaf2ba3e021",
  "engine": "0.1.0.dev18",
  "inputs": {
   "oracles": {
    "evals/oracles/__init__.py": "1ca86d254ffd5a82dd797a1adde945256b5f6162d69af4b41fe2c9e3bcf66170",
    "evals/oracles/smoke.py": "61dba5097b7b7775c69d7ae32e8869c09a88c56746c8129aa11ae172531d03cd"
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
