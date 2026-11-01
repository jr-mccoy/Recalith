# Preview evaluation report (live)

**live working agent and certified inference route.** Counts toward the preview gate: **True**. Gate: **failed**.

- claims_unadjudicated:20 (evals/run.py adjudicate)

## Paired outcomes (candidate vs clean no-memory baseline)

| Scenario | Success C/B | Repeated mistakes C/B | Detours C/B | Retry C/B | Foreground tok C/B | Background tok C | Elapsed s C/B | Labels C/B |
|---|---|---|---|---|---|---|---|---|
| smoke-C1-ledgerlite-routine-typo | yes/yes | 0/0 | 0/0 | –/– | 124306/123541 | 138849 | 23.8/20.0 | candidate/no_memory |
| smoke-C2-fieldnotes-tdd-expected-red | yes/no | 0/0 | 0/1 | –/– | 417209/316313 | 396188 | 78.7/57.1 | candidate/no_memory |
| smoke-C3-household-utilities-speculation | yes/yes | 0/0 | 0/0 | –/– | 71854/72079 | 71632 | 26.9/27.0 | candidate/no_memory |
| smoke-C4-cross-project-near-match | yes/yes | 0/0 | 0/1 | –/– | 203859/196890 | 137297 | 36.0/24.3 | candidate/no_memory |
| smoke-L1-ledgerlite-test-command | yes/yes | 0/0 | 0/0 | –/– | 161999/166297 | 264437 | 31.3/27.7 | candidate/no_memory |
| smoke-L2-fieldnotes-iso-dates | yes/yes | 0/0 | 0/0 | –/– | 244487/171129 | 293063 | 43.0/30.2 | candidate/no_memory |
| smoke-L3-household-grocery-budget | yes/yes | 0/0 | 0/1 | –/– | 110703/162652 | 152027 | 41.5/33.7 | candidate/no_memory |
| smoke-L4-ledgerlite-resume-refactor | no/yes | 0/0 | 0/1 | –/– | 167265/185616 | 329343 | 37.1/33.8 | candidate/no_memory |
| smoke-R1-fieldnotes-check-env-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 108034/106280 | 219905 | 26.8/19.1 | candidate/no_memory |
| smoke-R2-ledgerlite-import-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 149565/126941 | 165446 | 29.7/24.3 | candidate/no_memory |
| smoke-R3-household-budget-correction | no/no | 0/0 | 0/0 | –/– | 54766/54035 | 70523 | 21.9/20.3 | candidate/no_memory |
| smoke-R4-fieldnotes-storage-conflict | yes/yes | 0/0 | 0/0 | –/– | 177871/148364 | 276985 | 36.2/29.2 | candidate/no_memory |

Paired differences (candidate − baseline), mean with a 95 % interval from resampling whole scenarios:

- task_success: n=12, mean=0.0, CI95=(-0.25, 0.25), inconclusive
- repeated_mistakes: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- detours: n=12, mean=-0.3333, CI95=(-0.5833, -0.0833)
- legitimate_retry_success: n=2, mean=0.0, CI95=(0.0, 0.0), inconclusive
- foreground_tokens: n=12, mean=13481.75, CI95=(-7231.75, 35754.0833), inconclusive
- background_tokens: n=12, mean=209641.25, CI95=(153869.0833, 265257.6667)
- elapsed_seconds: n=12, mean=7.1934, CI95=(4.1871, 10.6025)
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

Support and recall come from reviewer labels (`adjudication.json`); 20 item(s) unlabeled (`evals/run.py adjudicate`). Lessons whose evidence never occurred: 0. fewer than two independent reviewers (ACCEPTANCE_TESTS §5: report the limitation)
Term match (provisional, frozen against the recorded curator's wording): supported_precision 6/12, useful_recall 6/8, failed_approach_recall 2/3

## Curator call outcomes

```json
{
 "smoke": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 21,
    "replies_parsed": 21,
    "reported_input_tokens": 672813,
    "reported_output_tokens": 38845,
    "visible_output_estimate": 11212
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 23,
    "replies_parsed": 23,
    "reported_input_tokens": 831238,
    "reported_output_tokens": 63338,
    "visible_output_estimate": 14579
   },
   "revalidate": {
    "at_output_cap": 0,
    "calls": 5,
    "replies_parsed": 5,
    "reported_input_tokens": 62244,
    "reported_output_tokens": 6732,
    "visible_output_estimate": 1334
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 16,
    "replies_parsed": 16,
    "reported_input_tokens": 111614,
    "reported_output_tokens": 19147,
    "visible_output_estimate": 3924
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 21,
    "replies_parsed": 21,
    "reported_input_tokens": 671365,
    "reported_output_tokens": 38359,
    "visible_output_estimate": 10806
   }
  },
  "job_errors": {
   "revalidate:coalesced": 1
  }
 },
 "workload": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 25,
    "replies_parsed": 25,
    "reported_input_tokens": 637229,
    "reported_output_tokens": 50195,
    "visible_output_estimate": 13753
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 46,
    "replies_parsed": 46,
    "reported_input_tokens": 1243830,
    "reported_output_tokens": 63111,
    "visible_output_estimate": 10061
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 8,
    "replies_parsed": 8,
    "reported_input_tokens": 45089,
    "reported_output_tokens": 9051,
    "visible_output_estimate": 1642
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 22,
    "replies_parsed": 22,
    "reported_input_tokens": 523341,
    "reported_output_tokens": 30743,
    "visible_output_estimate": 8746
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
    "n": 3,
    "p50": 1.0,
    "p95": 1.0
   }
  }
 },
 "curation_throughput": {
  "fieldnotes": {
   "admitted_claims": 3,
   "calls": 39,
   "calls_by_purpose": {
    "build_episode": 10,
    "extract_claims": 19,
    "review_claims": 2,
    "update_task": 8
   },
   "calls_per_admitted_claim": 13.0,
   "calls_per_settled_episode": 4.333,
   "estimated_tokens_by_purpose": {
    "build_episode": 169808,
    "extract_claims": 353662,
    "review_claims": 7468,
    "update_task": 123471
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 20.376,
     "n": 39,
     "p50": 6.9,
     "p95": 18.739
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
     "operations": [],
     "purpose": "update_task"
    },
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
     "operations": [],
     "purpose": "extract_claims"
    }
   ],
   "provider_outcomes": {
    "by_purpose": {
     "build_episode": {
      "at_output_cap": 0,
      "calls": 10,
      "replies_parsed": 10,
      "reported_input_tokens": 260356,
      "reported_output_tokens": 19910,
      "visible_output_estimate": 5396
     },
     "extract_claims": {
      "at_output_cap": 0,
      "calls": 19,
      "replies_parsed": 19,
      "reported_input_tokens": 533051,
      "reported_output_tokens": 23873,
      "visible_output_estimate": 4041
     },
     "review_claims": {
      "at_output_cap": 0,
      "calls": 2,
      "replies_parsed": 2,
      "reported_input_tokens": 10615,
      "reported_output_tokens": 1976,
      "visible_output_estimate": 328
     },
     "update_task": {
      "at_output_cap": 0,
      "calls": 8,
      "replies_parsed": 8,
      "reported_input_tokens": 190371,
      "reported_output_tokens": 10882,
      "visible_output_estimate": 2920
     }
    },
    "job_errors": {
     "update_task:coalesced": 1
    }
   },
   "queue_wait_seconds": {
    "max": 4.0,
    "n": 39,
    "p50": 0.0,
    "p95": 3.0
   },
   "settled_episodes": 9
  },
  "household": {
   "admitted_claims": 2,
   "calls": 29,
   "calls_by_purpose": {
    "build_episode": 8,
    "extract_claims": 9,
    "review_claims": 4,
    "update_task": 8
   },
   "calls_per_admitted_claim": 14.5,
   "calls_per_settled_episode": 3.625,
   "estimated_tokens_by_purpose": {
    "build_episode": 108721,
    "extract_claims": 152412,
    "review_claims": 16759,
    "update_task": 113258
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 16.017,
     "n": 29,
     "p50": 7.533,
     "p95": 15.927
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
     "operations": [],
     "purpose": "update_task"
    },
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
      "assess_claim",
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
      "update_task"
     ],
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
    }
   ],
   "provider_outcomes": {
    "by_purpose": {
     "build_episode": {
      "at_output_cap": 0,
      "calls": 8,
      "replies_parsed": 8,
      "reported_input_tokens": 165841,
      "reported_output_tokens": 14516,
      "visible_output_estimate": 4173
     },
     "extract_claims": {
      "at_output_cap": 0,
      "calls": 9,
      "replies_parsed": 9,
      "reported_input_tokens": 229547,
      "reported_output_tokens": 12976,
      "visible_output_estimate": 2307
     },
     "review_claims": {
      "at_output_cap": 0,
      "calls": 4,
      "replies_parsed": 4,
      "reported_input_tokens": 23758,
      "reported_output_tokens": 4845,
      "visible_output_estimate": 942
     },
     "update_task": {
      "at_output_cap": 0,
      "calls": 8,
      "replies_parsed": 8,
      "reported_input_tokens": 173882,
      "reported_output_tokens": 12407,
      "visible_output_estimate": 3810
     }
    },
    "job_errors": {}
   },
   "queue_wait_seconds": {
    "max": 4.0,
    "n": 29,
    "p50": 1.0,
    "p95": 3.0
   },
   "settled_episodes": 8
  },
  "ledgerlite": {
   "admitted_claims": 1,
   "calls": 33,
   "calls_by_purpose": {
    "build_episode": 7,
    "extract_claims"
```

## Expected retrieval points (candidate)

9/12 satisfied (Wilson 95 % (0.4677, 0.9111)). Unmet:

- smoke-L1-ledgerlite-test-command: {"must_include": "PYTHONPATH=src", "purpose": "session_start", "session": "B"} (0 items delivered at that point)
- smoke-L2-fieldnotes-iso-dates: {"must_include": "ISO-8601", "purpose": "prompt", "session": "B"} (0 items delivered at that point)
- smoke-L4-ledgerlite-resume-refactor: {"must_include": "money.parse", "purpose": "session_start", "session": "B"} (0 items delivered at that point)

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
       "Running python tools/check.py without NOTES_HOME set fails with KeyError: 'NOTES_HOME'.",
       "active",
       "current",
       9
      ],
      [
       "Running python tools/check.py with NOTES_HOME unset finished successfully with one test reported OK.",
       "archived",
       "current",
       2
      ],
      [
       "Run python tools/check.py with NOTES_HOME set to a temp directory to get it passing.",
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
         "freshness": "needs_revalidation",
         "text": "Procedure: Run python tools/check.py with NOTES_HOME set to a temp directory to get it passing. Steps: 1. In one shell command, set a scratch directory: export "
        },
        {
         "advice": "context",
         "freshness": "current",
         "text": "Failure lesson: Running python tools/check.py without NOTES_HOME set fails with KeyError: 'NOTES_HOME'. Observed: Running python tools/check.py with NOTES_HOME "
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
       "After tests/__init__.py was added, `python -m unittest discover -s tests -t .` ran 2 tests and reported OK.",
       "active",
       "current",
       2
      ],
      [
       "The user prefers that the project's tests pass without changing the test command `python -m unittest discover -s tests -t .`, and asked to be told a working command if that is not possible.",
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
         "text": "Preference: The user prefers that the project's tests pass without changing the test command `python -m unittest discover -s tests -t .`, and asked to be told a"
        },
        {
         "advice": "context",
         "freshness": "needs_revalidation",
         "text": "Fact: After tests/__init__.py was added, `python -m unittest discover -s tests -t .` ran 2 tests and reported OK."
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
   "backup_before": {
    "external_copy": true,
    "manifest_digest": "2d4b9ca22d50a466ad80ffe2054ae1cdc4edee9a4e1c830bc0a95164d434b5b9",
    "store_hits_before": 15
   },
   "delivered_after_forget": false,
   "delivered_after_restore": false,
   "demonstrated": true,
   "forget": {
    "backup_state": "verified",
    "purge_state": "completed",
    "purged_count": 18,
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
    "restored_revision": 108,
    "source_contains_suppressed": true,
    "suppressed_record_count": 18
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
    "smoke-L3-household-grocery-budget"
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
     "admitted": [],
     "baseline_repeated_mistakes": 0,
     "baseline_task_success": true,
     "candidate_repeated_mistakes": 0,
     "candidate_task_success": true,
     "carried_in_session_b": [],
     "errors": [],
     "gold_in_session_b": [
      "ISO-8601"
     ],
     "made_a_difference": false,
     "met": false
    },
    "smoke-L3-household-grocery-budget": {
     "admitted": [
      "The household grocery budget is kept under $600 per month, and any spending that would push it over is flagged."
     ],
     "baseline_repeated_mistakes": 0,
     "baseline_task_success": true,
     "candidate_repeated_mistakes": 0,
     "candidate_task_success": true,
     "carried_in_session_b": [
      "600"
     ],
     "errors": [],
     "gold_in_session_b": [
      "600"
     ],
     "made_a_difference": false,
     "met": true
    },
    "smoke-L4-ledgerlite-resume-refactor": {
     "admitted": [
      "The ledgerlite refactor is planned in three steps: add src/ledgerlite/money.py with parse, make Ledger.transfer use money.parse, and add tests/test_money.py. Only step 1 was authorized for that session, after which work stops to report the next step."
     ],
     "baseline_repeated_mistakes": 0,
     "baseline_task_success": true,
     "candidate_repeated_mistakes": 0,
     "candidate_task_success": false,
     "carried_in_session_b": [
      "money.parse"
     ],
     "errors": [],
     "gold_in_session_b": [
      "money.parse"
     ],
     "made_a_difference": false,
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
    "tools/check.py reads NOTES_HOME with os.environ[\"NOTES_HOME\"], so the check requires NOTES_HOME to be set in the environment."
   ],
   "fieldnotes_session_b_delivered": [],
   "installations": {
    "distinct": true,
    "fieldnotes": "inst_b9e706cd-9cc2-4e58-8fc
```

## Unsuccessful runs

- {'scenario': 'smoke-C2-fieldnotes-tdd-expected-red', 'arm': 'no_memory', 'reason': 'task_failed'}
- {'scenario': 'smoke-L4-ledgerlite-resume-refactor', 'arm': 'candidate', 'reason': 'task_failed'}
- {'scenario': 'smoke-R3-household-budget-correction', 'arm': 'candidate', 'reason': 'task_failed'}
- {'scenario': 'smoke-R3-household-budget-correction', 'arm': 'no_memory', 'reason': 'task_failed'}

## Cost and time

```json
{
 "actual": {
  "background_model_calls": 187,
  "background_tokens": 4131924,
  "elapsed_seconds": 779.6,
  "foreground_cost_usd": 1.7856,
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
  "commit": "7e6ad94f872592f4bd95e76039a0a4c4f6daea76",
  "engine": "0.1.0.dev4",
  "installed_host": "2.1.310 (Claude Code)",
  "platform": "Windows 11 AMD64",
  "prompts": {
   "build_episode": "build_episode@1",
   "extract_claims": "extract_claims@2",
   "revalidate": "revalidate@2",
   "review_claims": "review_claims@1",
   "update_task": "update_task@1"
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
- Each candidate installation's route is certified live for that installation; its host record is bound from the source project's live engine-mode certification for the same host version, model and configuration (decision 0028), not re-observed per installation.
- Sessions run on real time. Between sessions the harness waits until the hook-started worker owes nothing due within 20 minutes (or 45 minutes pass, or progress stalls for 5); the scenarios' two-hour gaps are not reproduced.
- Delivered context is read from the host's hook_response records (the hook's exact stdout as the host received it); that the model saw it is the separate canary certification, not re-checked per trial.
- Workload days replay synthetic recorded timelines in process through the real stdlib hook path (no host session); scheduling runs on the day's virtual clock while every curator call is real.
- Background tokens come from the budget ledger (provider-reported where the call reported usage); foreground cost is the host's own reported session cost.
- On native Windows a hook-started worker runs inside the venv redirector's job (decision 0027 item 8): recovery is degraded while it runs.
