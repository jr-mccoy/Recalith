# Preview evaluation report (live)

**live working agent and certified inference route.** Counts toward the preview gate: **True**. Gate: **failed**.

- quality_targets_unmet:conflict_uncertainty_preservation
- trial_errors:smoke-R3-household-budget-correction.candidate:route_failed
- contaminated_arms:smoke-R3-household-budget-correction.candidate,smoke-R4-fieldnotes-storage-conflict.candidate,smoke-R4-fieldnotes-storage-conflict.no_memory
- unsettled_gaps:smoke-L3-household-grocery-budget.candidate:B:stalled:response_invalid,smoke-L3-household-grocery-budget.candidate:measurement:deadline,smoke-L4-ledgerlite-resume-refactor.candidate:B:deadline,smoke-L4-ledgerlite-resume-refactor.candidate:measurement:stalled:endpoint_unreachable,smoke-R1-fieldnotes-check-env-fixed.candidate:measurement:stalled:endpoint_unreachable,smoke-R2-ledgerlite-import-fixed.
- demonstrations_unmet:fresh_session_reuse,changed_condition_revision
- suspended:smoke-L3-household-grocery-budget.candidate:wait before measurement,smoke-L4-ledgerlite-resume-refactor.candidate:session B,smoke-L4-ledgerlite-resume-refactor.candidate:wait before B
- claims_unadjudicated:17 (evals/run.py adjudicate)

## Paired outcomes (candidate vs clean no-memory baseline)

| Scenario | Success C/B | Repeated mistakes C/B | Detours C/B | Retry C/B | Foreground tok C/B | Background tok C | Elapsed s C/B | Labels C/B |
|---|---|---|---|---|---|---|---|---|
| smoke-C1-ledgerlite-routine-typo | yes/yes | 0/0 | 0/0 | –/– | 123620/123595 | 136799 | 24.3/24.0 | candidate/no_memory |
| smoke-C2-fieldnotes-tdd-expected-red | no/no | 0/0 | 1/0 | –/– | 425440/268037 | 399360 | 83.7/53.0 | candidate/no_memory |
| smoke-C3-household-utilities-speculation | yes/yes | 0/0 | 0/0 | –/– | 71839/71684 | 63216 | 31.6/31.0 | candidate/no_memory |
| smoke-C4-cross-project-near-match | yes/yes | 0/0 | 0/1 | –/– | 204674/179357 | 139308 | 39.5/36.0 | candidate/no_memory |
| smoke-L1-ledgerlite-test-command | yes/yes | 0/0 | 0/0 | –/– | 201170/183496 | 286086 | 35.4/32.7 | candidate/no_memory |
| smoke-L2-fieldnotes-iso-dates | yes/yes | 0/0 | 0/0 | –/– | 165058/150096 | 299650 | 41.0/41.0 | candidate/no_memory |
| smoke-L3-household-grocery-budget | yes/yes | 0/0 | 1/1 | –/– | 146454/144505 | 172857 | 41.5/37.0 | candidate/no_memory |
| smoke-L4-ledgerlite-resume-refactor | no/yes | 0/0 | 0/0 | –/– | 72260/185193 | 127320 | 51495.3/33.5 | candidate/no_memory |
| smoke-R1-fieldnotes-check-env-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 126687/125081 | 182344 | 27.1/41.0 | candidate/no_memory |
| smoke-R2-ledgerlite-import-fixed | no/yes | 0/0 | 0/0 | no/yes | 127988/126782 | 155769 | 26.2/22.5 | candidate/no_memory |
| smoke-R3-household-budget-correction | no/no | –/0 | –/0 | –/– | –/54820 | – | –/141.3 | contaminated/no_memory |
| smoke-R4-fieldnotes-storage-conflict | yes/yes | 0/0 | 0/0 | –/– | 203265/148498 | 295518 | 44.3/100.8 | contaminated/contaminated |

Paired differences (candidate − baseline), mean with a 95 % interval from resampling whole scenarios:

- task_success: n=12, mean=-0.1667, CI95=(-0.4167, 0.0), inconclusive
- repeated_mistakes: n=11, mean=0.0, CI95=(0.0, 0.0), inconclusive
- detours: n=11, mean=0.0, CI95=(-0.2727, 0.2727), inconclusive
- legitimate_retry_success: n=2, mean=-0.5, CI95=(-1.0, 0.0), inconclusive
- foreground_tokens: n=11, mean=14739.1818, CI95=(-18232.4545, 48705.5455), inconclusive
- background_tokens: n=11, mean=205293.3636, CI95=(151637.3636, 260175.6364)
- elapsed_seconds: n=11, mean=4676.1288, CI95=(-11.453, 14037.5332), inconclusive
- operator_interventions: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- repeated failures on relevant scenarios: candidate 0, baseline 0, relative reduction None (>= 0.25 (Cut 2 gate; not a preview gate))

No superiority claim: a 12-scenario smoke run with one trial per arm cannot establish one (ACCEPTANCE_TESTS §6.1).

## §5.1 quality on the smoke population

| Measure | Value | Numerator/denominator | Wilson 95 % | Target | Met |
|---|---|---|---|---|---|
| supported_precision | – | 0/0 | None | >= 0.95 | None |
| useful_recall | 0 | 0/1 | (0.0, 0.7935) | >= 0.85 | None |
| failed_approach_recall | – | 0/0 | None | >= 0.9 | None |
| incorrect_confident_guidance | 0 | count over 12 | None | == 0 | True |
| conflict_uncertainty_preservation | 0 | 0/1 | (0.0, 0.7935) | >= 0.95 | False |
| legitimate_retry_discouraged | 0 | 0/2 | (0.0, 0.6576) | <= 0.05 | True |
| irrelevant_caution_quiet | 0 | 0/3 | (0.0, 0.5615) | <= 0.05 | True |
| routine_human_maintenance | 0 | count over 12 | None | == 0 | True |

Support and recall come from reviewer labels (`adjudication.json`); 17 item(s) unlabeled (`evals/run.py adjudicate`). Lessons whose evidence never occurred: 0. fewer than two independent reviewers (ACCEPTANCE_TESTS §5: report the limitation)
Term match (provisional, frozen against the recorded curator's wording): supported_precision 4/10, useful_recall 4/8, failed_approach_recall 1/3

## Curator call outcomes

```json
{
 "smoke": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 19,
    "replies_parsed": 19,
    "reported_input_tokens": 603196,
    "reported_output_tokens": 35605,
    "visible_output_estimate": 10523
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 23,
    "replies_parsed": 19,
    "reported_input_tokens": 691100,
    "reported_output_tokens": 50701,
    "visible_output_estimate": 11519
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 11,
    "replies_parsed": 11,
    "reported_input_tokens": 83354,
    "reported_output_tokens": 13681,
    "visible_output_estimate": 2634
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 19,
    "replies_parsed": 15,
    "reported_input_tokens": 529753,
    "reported_output_tokens": 26930,
    "visible_output_estimate": 7100
   }
  },
  "job_errors": {
   "extract_claims:endpoint_unreachable": 3,
   "update_task:endpoint_unreachable": 3
  }
 },
 "workload": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 17,
    "replies_parsed": 17,
    "reported_input_tokens": 462267,
    "reported_output_tokens": 34694,
    "visible_output_estimate": 9807
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 35,
    "replies_parsed": 35,
    "reported_input_tokens": 970129,
    "reported_output_tokens": 42675,
    "visible_output_estimate": 6404
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 6,
    "replies_parsed": 6,
    "reported_input_tokens": 35159,
    "reported_output_tokens": 5301,
    "visible_output_estimate": 1000
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 14,
    "replies_parsed": 14,
    "reported_input_tokens": 316792,
    "reported_output_tokens": 25697,
    "visible_output_estimate": 7428
   }
  },
  "job_errors": {
   "build_episode:budget_exhausted:ordinary.input_estimate": 4,
   "extract_claims:budget_exhausted:ordinary.input_estimate": 5,
   "update_task:budget_exhausted:ordinary.input_estimate": 4,
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
    "jobs": 14,
    "kinds": [
     "build_episode",
     "extract_claims",
     "update_task"
    ],
    "oldest_age_seconds": 13720.0
   },
   "household": {
    "jobs": 0,
    "kinds": [],
    "oldest_age_seconds": 0.0
   },
   "ledgerlite": {
    "jobs": 12,
    "kinds": [
     "build_episode",
     "extract_claims",
     "update_task"
    ],
    "oldest_age_seconds": 14841.0
   }
  },
  "days_hitting_any_pool": {
   "denominator": 3,
   "numerator": 2,
   "value": 0.6667,
   "wilson_95": [
    0.2077,
    0.9385
   ]
  },
  "days_not_run": [],
  "median_hours_to_exhaustion": 4.0825000000000005,
  "nonexhausted_censored_days": 1,
  "pools_hit": [
   "ordinary.input_estimate"
  ],
  "priority_inversions": 0,
  "scenario_days": 3,
  "waiting_seconds": {
   "correction_declaration_review": {
    "max": 1.0,
    "n": 4,
    "p50": 1.0,
    "p95": 1.0
   },
   "ordinary": {
    "max": 4.0,
    "n": 66,
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
   "calls": 24,
   "calls_by_purpose": {
    "build_episode": 5,
    "extract_claims": 13,
    "review_claims": 2,
    "update_task": 4
   },
   "calls_per_admitted_claim": 12.0,
   "calls_per_settled_episode": 2.667,
   "estimated_tokens_by_purpose": {
    "build_episode": 89506,
    "extract_claims": 239446,
    "review_claims": 8710,
    "update_task": 57524
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 29.723,
     "n": 24,
     "p50": 8.328,
     "p95": 24.167
    }
   },
   "proposals": [
    {
     "body_retained": true,
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "body_retained": true,
     "operations": [
      "propose_claim"
     ],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [
      "assess_claim"
     ],
     "purpose": "review_claims"
    },
    {
     "body_retained": true,
     "operations": [
      "update_task"
     ],
     "purpose": "update_task"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "body_retained": true,
     "operations": [
      "update_task",
      "update_task"
     ],
     "purpose": "update_task"
    },
    {
     "body_retained": true,
     "operations": [
      "propose_claim"
     ],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [
      "assess_claim"
     ],
     "purpose": "review_claims"
    },
    {
     "body_retained": true,
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "body_retained": true,
     "operations": [
      "update_task"
     ],
     "purpose": "update_task"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [
      "update_task"
     ],
     "purpose": "update_task"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    }
   ],
   "provider_outcomes": {
    "by_purpose": {
     "build_episode": {
      "at_output_cap": 0,
      "calls": 5,
      "replies_parsed": 5,
      "reported_input_tokens": 137733,
      "reported_output_tokens": 10413,
      "visible_output_estimate": 2511
     },
     "extract_claims": {
      "at_output_cap": 0,
      "calls": 13,
      "replies_parsed": 13,
      "reported_input_tokens": 364101,
      "reported_output_tokens": 17939,
      "visible_output_estimate": 2359
     },
     "review_claims": {
      "at_output_cap": 0,
      "calls": 2,
      "replies_parsed": 2,
      "reported_input_tokens": 12536,
      "reported_output_tokens": 1732,
      "visible_output_estimate": 328
     },
     "update_task": {
      "at_output_cap": 0,
      "calls": 4,
      "replies_parsed": 4,
      "reported_input_tokens": 86363,
      "reported_output_tokens": 8178,
      "visible_output_estimate": 2689
     }
    },
    "job_errors": {
     "build_episode:budget_exhausted:ordinary.input_estimate": 1,
     "update_task:coalesced": 1
    }
   },
   "queue_wait_seconds": {
    "max": 4.0,
    "n": 24,
    "p50": 0.0,
    "p95": 3.0
   },
   "settled_episodes": 9
  },
  "household": {
   "admitted_claims": 2,
   "calls": 28,
   "calls_by_purpose": {
    "build_episode": 8,
    "extract_claims": 9,
    "review_claims": 3,
    "update_task": 8
   },
   "calls_per_admitted_claim": 14.0,
   "calls_per_settled_episode": 3.5,
   "estimated_tokens_by_purpose": {
    "build_episode": 109427,
    "extract_claims": 142525,
    "review_claims": 10397,
    "update_task": 113513
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 14.293,
     "n": 28,
     "p50": 9.226,
     "p95": 14.229
    }
   },
   "proposals": [
    {
     "body_retained": true,
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "body_retained": true,
     "operations": [
      "propose_claim"
     ],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [
      "assess_claim"
     ],
     "purpose": "review_claims"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "update_task"
    },
    {
     "body_retained": true,
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "update_task"
    },
    {
     "body_retained": true,
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "update_task"
    },
    {
     "body_retained": true,
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "update_task"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "update_task"
    },
    {
     "body_retained": true,
     "operations": [
      "propose_claim",
      "change_claim_status"
     ],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [
      "assess_claim"
     ],
     "purpose": "review_claims"
    },
    {
     "body_retained": true,
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "update_task"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "update_task"
    },
    {
     "body_retained": true,
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "body_retained": true,
     "operations": [
      "propose_claim"
     ],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [
      "assess_claim"
     ],
     "purpose": "review_claims"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "update_task"
    }
   ],
   "provider_outcomes": {
    "by_purpose": {
     "build_episode": {
      "at_output_cap": 0,
      "calls": 8,
      "replies_parsed": 8,
      "reported_input_tokens": 166581,
      "reported_output_tokens": 15631,
      "visible_output_estimate": 4795
     },
     "extract_claims": {
      "at_output_cap": 0,
      "calls": 9,
      "replies_parsed": 9,
      "reported_input_tokens": 217808,
      "reported_output_tokens": 8656,
      "visible_output_estimate": 1658
     },
     "review_claims": {
      "at_output_cap": 0,
      "calls": 3,
      "replies_parsed": 3,
      "reported_input_tokens": 14723,
      "reported_output_tokens": 2458,
      "visible_output_estimate": 499
     },
     "update_task": {
      "at_output_cap": 0,
      "calls": 8,
      "replies_parsed": 8,
      "reported_input_tokens": 175256,
      "reported_output_tokens": 13993,
      "visible_output_estimate": 3677
     }
    },
    "job_errors": {}
   },
   "queue_wait_seconds": {
    "max": 4.0,
    "n": 28,
    "p50": 2.0,
    "p95": 4.0
   },
   "settled_episodes": 8
  },
  "ledgerlite": {
   "admitted_claims": 2,
   "calls": 20,
   "calls_by_purpose": {
    "build_episode": 4,
    "extract_claims": 13,
    "review_claims": 1,
    "update_task": 2
   },
   "calls_per_admitted_claim": 10.0,
   "calls_per_settled_episode": 2.857,
   "estimated_tokens_by_purpose": {
    "build_episode": 102696,
    "extract_claims": 257839,
    "review_claims": 5513,
    "update_task": 36720
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 22.905,
     "n": 20,
     "p50": 7.474,
     "p95": 22.905
    }
   },
   "proposals": [
    {
     "body_retained": true,
     "operations": [
      "propose_claim",
      "propose_claim"
     ],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [
      "assess_claim"
     ],
     "purpose": "review_claims"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "body_retained": true,
     "operations": [
      "update_task"
     ],
     "purpose": "update_task"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_cl
```

## Expected retrieval points (candidate)

7/11 satisfied (Wilson 95 % (0.3538, 0.8483)). Unmet:

- smoke-L1-ledgerlite-test-command: {"must_include": "PYTHONPATH=src", "purpose": "session_start", "session": "B"} (0 items delivered at that point)
- smoke-L3-household-grocery-budget: {"must_include": "600", "purpose": "prompt", "session": "B"} (0 items delivered at that point)
- smoke-L4-ledgerlite-resume-refactor: {"must_include": "money.parse", "purpose": "session_start", "session": "B"} (0 items delivered at that point)
- smoke-R4-fieldnotes-storage-conflict: {"advice": "conflict_or_freshness_label", "purpose": "prompt", "session": "C"} (1 items delivered at that point)

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
       "Running python tools/check.py without NOTES_HOME set fails.",
       "candidate",
       "current",
       2
      ],
      [
       "tools/check.py requires the NOTES_HOME environment variable to be set.",
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
         "text": "Fact: tools/check.py requires the NOTES_HOME environment variable to be set."
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
       "With tests/__init__.py in place (it inserts the src directory onto sys.path), `python -m unittest discover -s tests -t .` runs the 2 ledgerlite tests and both pass.",
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
         "text": "Fact: With tests/__init__.py in place (it inserts the src directory onto sys.path), `python -m unittest discover -s tests -t .` runs the 2 ledgerlite tests and "
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
     "task_success": false
    }
   }
  },
  "forgetting_and_restore": {
   "backup_before": {
    "external_copy": true,
    "manifest_digest": "dee7030c8964754c31c45cb2fde45714c330cfecd0de8ad822e2d2baec2dfd53",
    "store_hits_before": 15
   },
   "delivered_after_forget": false,
   "delivered_after_restore": false,
   "demonstrated": true,
   "forget": {
    "backup_state": "verified",
    "purge_state": "completed",
    "purged_count": 12,
    "quarantined_count": 0
   },
   "restore": {
    "applied_schema": 11,
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
    "suppressed_record_count": 12
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
   "criterion": "a learning scenario whose candidate succeeded with no repeated mistake, whose fresh session B carried the scenario's gold text in a delivered packet, and whose clean baseline, in the same session, failed or repeated session A's mistake; any one of the learning scenarios demonstrates it (decision 0028 item 16)",
   "demonstrated": false,
   "met_by": [],
   "not_run": [],
   "note": "one trial per arm: a demonstration, not an estimate. The gold text may arrive in any packet of session B (L1's session-start point is unmet by design, decision 0013, and its prompt packet carries the lesson)",
   "remember_instruction": false,
   "scenarios": {
    "smoke-L1-ledgerlite-test-command": {
     "admitted": [],
     "baseline_repeated_mistakes": 0,
     "baseline_task_success": true,
     "candidate_repeated_mistakes": 0,
     "candidate_task_success": true,
     "carried_in_session_b": [],
     "errors": [],
     "gold_in_session_b": [
      "PYTHONPATH=src"
     ],
     "met": false
    },
    "smoke-L2-fieldnotes-iso-dates": {
     "admitted": [
      "Every date fieldnotes prints must be ISO-8601 (YYYY-MM-DD...). Locale formats such as 'Jan 2' or '02/01/2026' must not be used.",
      "tools/check.py requires the NOTES_HOME environment variable to be set before it runs."
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
     "met": false
    },
    "smoke-L3-household-grocery-budget": {
     "admitted": [
      "The user wants the household grocery budget kept under $600 per month, and wants anything that would push grocery spending over that amount flagged."
     ],
     "baseline_repeated_mistakes": 0,
     "baseline_task_success": true,
     "candidate_repeated_mistakes": 0,
     "candidate_task_success": true,
     "carried_in_session_b": [],
     "errors": [],
     "gold_in_session_b": [
      "600"
     ],
     "met": false
    },
    "smoke-L4-ledgerlite-resume-refactor": {
     "admitted": [],
     "baseline_repeated_mistakes": 0,
     "baseline_task_success": true,
     "candidate_repeated_mistakes": 0,
     "candidate_task_success": false,
     "carried_in_session_b": [],
     "errors": [],
     "gold_in_session_b": [
      "money.parse"
     ],
     "met": false
    }
   }
  },
  "isolation": {
   "cross_project_leak_commands": 0,
   "cross_record_ids": [],
   "cross_text_in_search": [],
   "demonstrated": true,
   "fieldnotes_active_claims": [
    "tools/check.py requires the NOTES_HOME environment variable to be set, because it reads NOTES_HOME directly from the environment.",
    "To run this project's checks and tests, set NOTES_HOME to a temporary directory if it is unset, then run `python tools/check.py` from the project root."
   ],
   "fieldnotes_session_b_delivered": [],
   "installations": {
    "distinct": true,
    "fieldnotes": "inst_c7a5a258-9ddd-402a-9d11-652dae5a7549",
    "ledgerlite": "inst_7a0cb238-12dc-4375-a98f-bc032615cda6"
   },
   "ledgerlite_active_claims": [
    "pytest is not installed in the Python 3.13 interpreter used for this project, so python -m pytest fails; the ledgerlite tests use unittest.",
    "Ledgerlite unit tests run from the project root with PYTHONPATH=src python -m unittest discover -s tests -v and report 2 tests OK."
   ],
   "reverse_session": {
    "actions": 1,
    "gap": {
     "last": {
      "due_jobs": 0,
      "due_kinds": [],
      "leased": 0,
      "next_due_in_s": null,
      "pending_triggers": 0,
      "progress": [
       37,
       28,
       37
      ],
      "quiet": true,
      "spool_ready": 0,
      "waiting_reasons": []
     },
     "polls": 10,
     "state": "quiet",
     "suspended_s": 0.0,
     "waited_s": 315.4,
     "worker_seen": true
    }
   },
   "scenario": "smoke-C4-cross-project-near-match",
   "task_success": true,
   "worker_stop": [
    {
     "exit": 0,
     "state": "stopped"
    },
    {
     "exit": 0,
     "state": "not_running"
    }
   ]
  },
  "zero_interventions": {
   "demonstrated": true,
   "jobs_awaiting_a_human": 0,
   "note": "memory formation, review, revision and delivery ran without any operator command; the forgetting demonstration's backup/forget/restore are intentional privacy operations, not routine maintenance",
   "operator_interventions": 0,
   "trials": 24,
   "workload_days": 3
  }
 },
 "label": "live working agent, real installed hooks, the installations' certified routes; privacy op
```

## Unsuccessful runs

- {'scenario': 'smoke-C2-fieldnotes-tdd-expected-red', 'arm': 'candidate', 'reason': 'task_failed'}
- {'scenario': 'smoke-C2-fieldnotes-tdd-expected-red', 'arm': 'no_memory', 'reason': 'task_failed'}
- {'scenario': 'smoke-L4-ledgerlite-resume-refactor', 'arm': 'candidate', 'reason': 'task_failed'}
- {'scenario': 'smoke-R2-ledgerlite-import-fixed', 'arm': 'candidate', 'reason': 'task_failed'}
- {'scenario': 'smoke-R3-household-budget-correction', 'arm': 'candidate', 'reason': 'route_failed'}
- {'scenario': 'smoke-R3-household-budget-correction', 'arm': 'no_memory', 'reason': 'task_failed'}

## Cost and time

```json
{
 "actual": {
  "background_model_calls": 145,
  "background_tokens": 3432043,
  "elapsed_seconds": 52483.8,
  "foreground_cost_usd": 1.858,
  "foreground_sessions": 46,
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
  "commit": "f8b9d74cd0660cf80b7ac97e8a471e195a957d0c",
  "engine": "0.1.0.dev1",
  "installed_host": "2.1.310 (Claude Code)",
  "platform": "Windows 11 AMD64",
  "prompts": {
   "build_episode": "build_episode@1",
   "extract_claims": "extract_claims@1",
   "revalidate": "revalidate@1",
   "review_claims": "review_claims@1",
   "update_task": "update_task@1"
  },
  "python": "3.13.15",
  "schema": 11,
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
