# Preview evaluation report (live)

**live working agent and certified inference route.** Counts toward the preview gate: **True**. Gate: **failed**.

- quality_targets_unmet:supported_precision,useful_recall,failed_approach_recall
- trial_errors:smoke-L4-ledgerlite-resume-refactor.candidate:bind_host_record_failed,smoke-R1-fieldnotes-check-env-fixed.candidate:bind_host_record_failed,smoke-R2-ledgerlite-import-fixed.candidate:bind_host_record_failed,smoke-R3-household-budget-correction.candidate:bind_host_record_failed,smoke-R4-fieldnotes-storage-conflict.candidate:bind_host_record_failed
- contaminated_arms:smoke-L4-ledgerlite-resume-refactor.candidate,smoke-R1-fieldnotes-check-env-fixed.candidate,smoke-R2-ledgerlite-import-fixed.candidate,smoke-R3-household-budget-correction.candidate,smoke-R4-fieldnotes-storage-conflict.candidate
- unsettled_gaps:smoke-C2-fieldnotes-tdd-expected-red.candidate:B:stalled:output_cap_reached,smoke-C2-fieldnotes-tdd-expected-red.candidate:measurement:deadline,smoke-C3-household-utilities-speculation.candidate:measurement:deadline,smoke-C4-cross-project-near-match.candidate:measurement:stalled:output_cap_reached,smoke-L1-ledgerlite-test-command.candidate:measurement:stalled:output_cap_reached,response_invalid,sm
- demonstrations_unmet:fresh_session_reuse,changed_condition_revision

## Paired outcomes (candidate vs clean no-memory baseline)

| Scenario | Success C/B | Repeated mistakes C/B | Detours C/B | Retry C/B | Foreground tok C/B | Background tok C | Elapsed s C/B | Labels C/B |
|---|---|---|---|---|---|---|---|---|
| smoke-C1-ledgerlite-routine-typo | yes/yes | 0/0 | 0/0 | –/– | 123906/123310 | 155849 | 19.8/19.4 | candidate/no_memory |
| smoke-C2-fieldnotes-tdd-expected-red | yes/no | 0/0 | 0/0 | –/– | 434011/267431 | 285069 | 65.9/53.0 | candidate/no_memory |
| smoke-C3-household-utilities-speculation | yes/yes | 0/0 | 0/0 | –/– | 71657/71414 | 19901 | 26.3/22.0 | candidate/no_memory |
| smoke-C4-cross-project-near-match | yes/yes | 0/0 | 0/1 | –/– | 204500/107689 | 164905 | 37.9/219461.3 | candidate/no_memory |
| smoke-L1-ledgerlite-test-command | yes/yes | 0/0 | 0/0 | –/– | 209653/182960 | 330251 | 33.7/29.0 | candidate/no_memory |
| smoke-L2-fieldnotes-iso-dates | yes/yes | 0/0 | 0/0 | –/– | 229793/130329 | 433588 | 48.3/30.4 | candidate/no_memory |
| smoke-L3-household-grocery-budget | yes/no | 0/0 | 0/0 | –/– | 234755/126124 | 284962 | 79.7/31.1 | candidate/no_memory |
| smoke-L4-ledgerlite-resume-refactor | no/yes | –/0 | –/0 | –/– | –/166424 | – | –/36.5 | contaminated/no_memory |
| smoke-R1-fieldnotes-check-env-fixed | no/yes | –/0 | –/0 | –/yes | –/125179 | – | –/19.4 | contaminated/no_memory |
| smoke-R2-ledgerlite-import-fixed | no/no | –/0 | –/0 | –/no | –/127775 | – | –/24.8 | contaminated/no_memory |
| smoke-R3-household-budget-correction | no/no | –/0 | –/0 | –/– | –/109753 | – | –/27.4 | contaminated/no_memory |
| smoke-R4-fieldnotes-storage-conflict | no/yes | –/0 | –/0 | –/– | –/147686 | – | –/28.9 | contaminated/no_memory |

Paired differences (candidate − baseline), mean with a 95 % interval from resampling whole scenarios:

- task_success: n=12, mean=-0.0833, CI95=(-0.4167, 0.25), inconclusive
- repeated_mistakes: n=7, mean=0.0, CI95=(0.0, 0.0), inconclusive
- detours: n=7, mean=-0.1429, CI95=(-0.4286, 0.0), inconclusive
- legitimate_retry_success: n=0, mean=None, CI95=None
- foreground_tokens: n=7, mean=71288.2857, CI95=(32092.2857, 114605.1429)
- background_tokens: n=7, mean=239217.8571, CI95=(146438.2857, 333927.0)
- elapsed_seconds: n=7, mean=-31333.5, CI95=(-94032.9541, 25.308), inconclusive
- operator_interventions: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- repeated failures on relevant scenarios: candidate 0, baseline 0, relative reduction None (>= 0.25 (Cut 2 gate; not a preview gate))

No superiority claim: a 12-scenario smoke run with one trial per arm cannot establish one (ACCEPTANCE_TESTS §6.1).

## §5.1 quality on the smoke population

| Measure | Value | Numerator/denominator | Wilson 95 % | Target | Met |
|---|---|---|---|---|---|
| supported_precision | 0.4 | 4/10 | (0.1682, 0.6873) | >= 0.95 | False |
| useful_recall | 0.5 | 4/8 | (0.2152, 0.7848) | >= 0.85 | False |
| failed_approach_recall | 0.3333 | 1/3 | (0.0615, 0.7923) | >= 0.9 | False |
| incorrect_confident_guidance | 0 | count over 12 | None | == 0 | True |
| conflict_uncertainty_preservation | – | 0/0 | None | >= 0.95 | None |
| legitimate_retry_discouraged | – | 0/0 | None | <= 0.05 | None |
| irrelevant_caution_quiet | 0 | 0/3 | (0.0, 0.5615) | <= 0.05 | True |
| routine_human_maintenance | 0 | count over 12 | None | == 0 | True |

## §5.2 operational measures

```json
{
 "budget_exhaustion": {
  "backlog_at_day_end": {
   "fieldnotes": {
    "jobs": 19,
    "kinds": [
     "build_episode",
     "extract_claims",
     "update_task"
    ],
    "oldest_age_seconds": 15119.0
   },
   "household": {
    "jobs": 1,
    "kinds": [
     "update_task"
    ],
    "oldest_age_seconds": 1068.0
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
   "numerator": 3,
   "value": 1.0,
   "wilson_95": [
    0.4385,
    1.0
   ]
  },
  "days_not_run": [],
  "median_hours_to_exhaustion": 3.894,
  "nonexhausted_censored_days": 0,
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
    "n": 74,
    "p50": 1.0,
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
   "calls": 29,
   "calls_by_purpose": {
    "build_episode": 4,
    "extract_claims": 9,
    "review_claims": 2,
    "update_task": 14
   },
   "calls_per_admitted_claim": 14.5,
   "calls_per_settled_episode": 3.222,
   "estimated_tokens_by_purpose": {
    "build_episode": 57136,
    "extract_claims": 148861,
    "review_claims": 8520,
    "update_task": 198609
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 17.778,
     "n": 29,
     "p50": 8.126,
     "p95": 14.102
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
     "purpose": "update_task"
    },
    {
     "body_retained": true,
     "operations": [],
     "purpose": "extract_claims"
    }
   ],
   "queue_wait_seconds": {
    "max": 4.0,
    "n": 29,
    "p50": 1.0,
    "p95": 4.0
   },
   "settled_episodes": 9
  },
  "household": {
   "admitted_claims": 2,
   "calls": 30,
   "calls_by_purpose": {
    "build_episode": 8,
    "extract_claims": 10,
    "review_claims": 3,
    "update_task": 9
   },
   "calls_per_admitted_claim": 15.0,
   "calls_per_settled_episode": 3.75,
   "estimated_tokens_by_purpose": {
    "build_episode": 108867,
    "extract_claims": 155987,
    "review_claims": 10410,
    "update_task": 129209
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 19.127,
     "n": 30,
     "p50": 7.889,
     "p95": 16.784
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
    }
   ],
   "queue_wait_seconds": {
    "max": 3.0,
    "n": 30,
    "p50": 2.0,
    "p95": 3.0
   },
   "settled_episodes": 8
  },
  "ledgerlite": {
   "admitted_claims": 1,
   "calls": 21,
   "calls_by_purpose": {
    "build_episode": 5,
    "extract_claims": 12,
    "review_claims": 1,
    "update_task": 3
   },
   "calls_per_admitted_claim": 21.0,
   "calls_per_settled_episode": 3.0,
   "estimated_tokens_by_purpose": {
    "build_episode": 112401,
    "extract_claims": 219968,
    "review_claims": 4639,
    "update_task": 61750
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 21.644,
     "n": 21,
     "p50": 6.725,
     "p95": 17.808
    }
   },
   "proposals": [
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
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    },
    {
     "body_retained": true,
     "operations": [
      "revise_episode"
     ],
     "purpose": "build_episode"
    }
   ],
   "queue_wait_seconds": {
    "max": 3.0,
    "n": 21,
    "p50": 0.0,
    "p95": 3.0
   },
   "settled_episodes": 7
  }
 },
 "delivery_visibility": {
  "paths": {
   "claude_code": {
    "contaminated_runs": "none recorded",
    "host_version": "2.1.309",
    "live": "run",
    "paths": {
     "compact": {
      "live": {
       "negatives_passed": 3,
       "negatives_run": 3,
       "positives_passed": 3,
       "positives_run": 3,
       "reasons": [],
       "required": false,
       "state": "healthy"
      },
      "request_capture": {
       "negatives_clean": 3,
       "positives_hook_emitted": 3,
       "positives_visible_in_request": 3,
       "state": "request_visible"
      }
     },
     "pre_action": {
      "live": {
       "negatives_passed": 3,
       "negatives_run": 3,
       "positives_passed": 3,
       "positives_run": 3,
       "reasons": [],
       "required": false,
       "state": "healthy"
      },
      "request_capture": {
       "negatives_clean": 3,
       "positives_hook_emitted": 3,
       "positives_visible_in_request": 3,
       "state": "request_visible"
      }
     },
     "prompt": {
      "live": {
       "negatives_passed": 3,
       "negatives_run": 3,
       "positives_passed": 3,
       "positives_run": 3,
       "reasons": [],
       "required": true,
       "state": "healthy"
      },
      "request_capture": {
       "negatives_clean": 3,
       "positives_hook_emitted": 3,
       "positives_visible_in_request": 3,
       "state": "request_visible"
      }
     },
     "session_start": {
      "live": {
       "negatives
```

## Expected retrieval points (candidate)

6/7 satisfied (Wilson 95 % (0.4869, 0.9743)). Unmet:

- smoke-L1-ledgerlite-test-command: {"must_include": "PYTHONPATH=src", "purpose": "session_start", "session": "B"} (0 items delivered at that point)

## §6.1 demonstrations

```json
{
 "demonstrations": {
  "changed_condition_revision": {
   "demonstrated": false,
   "scenarios": {
    "smoke-R1-fieldnotes-check-env-fixed": {
     "legitimate_retry_success": null,
     "lesson": [],
     "retry_point": [],
     "revalidation": [],
     "task_success": false
    },
    "smoke-R2-ledgerlite-import-fixed": {
     "legitimate_retry_success": null,
     "lesson": [],
     "retry_point": [],
     "revalidation": [],
     "task_success": false
    }
   }
  },
  "forgetting_and_restore": {
   "backup_before": {
    "external_copy": true,
    "manifest_digest": "4e75cbd8e5aa1d810322053aa3ff18b23f88e5c1857150b9eb96640dd7da6568",
    "store_hits_before": 12
   },
   "delivered_after_forget": false,
   "delivered_after_restore": false,
   "demonstrated": true,
   "forget": {
    "backup_state": "verified",
    "purge_state": "completed",
    "purged_count": 45,
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
    "restored_revision": 159,
    "source_contains_suppressed": true,
    "suppressed_record_count": 45
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
   "admitted": [
    "In the ledgerlite project, the unit tests run successfully with `PYTHONPATH=src python -m unittest discover -s tests -v`.",
    "In this ledgerlite environment, pytest is not installed; `python -m pytest` fails with \"No module named pytest\"."
   ],
   "baseline_repeated_mistakes": 0,
   "candidate_first_test_command_in_B": "cd <run>/work/L1/c/w && PYTHONPATH=src python -m unittest discover -s tests -v 2>&1 | tail -15",
   "candidate_repeated_mistakes": 0,
   "demonstrated": false,
   "note": "session B's knowledge came through delivered context (the scripted agent consults nothing else); the session-start point is unmet by design (decision 0013: a fresh start with no task binding carries only open intent questions) and the prompt packet carried it",
   "remember_instruction": false,
   "retrieval_points": [
    {
     "delivered": true,
     "items": [],
     "satisfied": false,
     "spec": {
      "must_include": "PYTHONPATH=src",
      "purpose": "session_start",
      "session": "B"
     }
    }
   ],
   "scenario": "smoke-L1-ledgerlite-test-command"
  },
  "isolation": {
   "cross_project_leak_commands": 0,
   "cross_record_ids": [],
   "cross_text_in_search": [],
   "demonstrated": true,
   "fieldnotes_active_claims": [
    "Running tools/check.py without NOTES_HOME set exits with code 1; setting NOTES_HOME to a temporary directory allowed the run to pass.",
    "`python tools/check.py` exited with code 1."
   ],
   "fieldnotes_session_b_delivered": [],
   "installations": {
    "distinct": true,
    "fieldnotes": "inst_5cc5e438-1931-4cc4-9bc6-9d3765b98579",
    "ledgerlite": "inst_899a6783-0925-49dc-99fd-704f085ea132"
   },
   "ledgerlite_active_claims": [
    "Running `PYTHONPATH=src python -m unittest discover -s tests -v` from the ledgerlite project root ran the two ledgerlite unit tests and reported OK.",
    "`python -m pytest` fails in the ledgerlite project because pytest is not installed for the Python 3.13 interpreter."
   ],
   "reverse_session": {
    "actions": 4,
    "gap": {
     "last": {
      "due_jobs": 0,
      "due_kinds": [],
      "leased": 0,
      "next_due_in_s": null,
      "pending_triggers": 0,
      "progress": [
       45,
       36,
       44
      ],
      "quiet": true,
      "spool_ready": 0,
      "waiting_reasons": []
     },
     "polls": 18,
     "state": "quiet",
     "waited_s": 599.0,
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
 "label": "live working agent, real installed hooks, the installations' certified routes; privacy operations through the guarded CLI with the operator token",
 "mode": "live"
}
```

## Unsuccessful runs

- {'scenario': 'smoke-C2-fieldnotes-tdd-expected-red', 'arm': 'no_memory', 'reason': 'task_failed'}
- {'scenario': 'smoke-L3-household-grocery-budget', 'arm': 'no_memory', 'reason': 'task_failed'}
- {'scenario': 'smoke-L4-ledgerlite-resume-refactor', 'arm': 'candidate', 'reason': 'bind_host_record_failed'}
- {'scenario': 'smoke-R1-fieldnotes-check-env-fixed', 'arm': 'candidate', 'reason': 'bind_host_record_failed'}
- {'scenario': 'smoke-R2-ledgerlite-import-fixed', 'arm': 'candidate', 'reason': 'bind_host_record_failed'}
- {'scenario': 'smoke-R2-ledgerlite-import-fixed', 'arm': 'no_memory', 'reason': 'task_failed'}
- {'scenario': 'smoke-R3-household-budget-correction', 'arm': 'candidate', 'reason': 'bind_host_record_failed'}
- {'scenario': 'smoke-R3-household-budget-correction', 'arm': 'no_memory', 'reason': 'task_failed'}
- {'scenario': 'smoke-R4-fieldnotes-storage-conflict', 'arm': 'candidate', 'reason': 'bind_host_record_failed'}

## Cost and time

```json
{
 "actual": {
  "background_model_calls": 128,
  "background_tokens": 2890882,
  "elapsed_seconds": 220094.7,
  "foreground_cost_usd": 1.5116,
  "foreground_sessions": 38,
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
   "host_version": "2.1.309 (Claude Code)",
   "method": "request capture (loopback endpoint, placeholder key); planted MEMORY.md sentinel",
   "state": "disabled"
  }
 },
 "versions": {
  "certified_capture_versions": [
   "2.1.301",
   "2.1.305",
   "2.1.306",
   "2.1.309"
  ],
  "commit": "98bf674ba26de4f57347e9f4ae7367a54943061f",
  "engine": "0.1.0.dev0",
  "installed_host": "2.1.309 (Claude Code)",
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
