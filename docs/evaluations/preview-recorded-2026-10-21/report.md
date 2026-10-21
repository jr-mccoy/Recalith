# Preview evaluation report (scripted)

**MECHANICS ONLY: scripted working agent and recorded curator proposals through the real engine; never a live pass.** Counts toward the preview gate: **False**. Gate: **blocked**.

- B1: provider_not_configured; start_prompt_delivery_not_certified: no host record given (B1: live nonce certification not run)
- not_live: scripted/recorded runs cannot pass the preview gate

## Paired outcomes (candidate vs clean no-memory baseline)

| Scenario | Success C/B | Repeated mistakes C/B | Detours C/B | Retry C/B | Foreground tok C/B | Background tok C | Elapsed s C/B | Labels C/B |
|---|---|---|---|---|---|---|---|---|
| smoke-C1-ledgerlite-routine-typo | yes/yes | 0/0 | 1/1 | –/– | 375/375 | 42774 | 0.264/0.162 | candidate/no_memory |
| smoke-C2-fieldnotes-tdd-expected-red | yes/yes | 0/0 | 1/1 | –/– | 716/716 | 112170 | 0.531/0.432 | candidate/no_memory |
| smoke-C3-household-utilities-speculation | yes/yes | 0/0 | 0/0 | –/– | 76/76 | 58936 | 0.072/0 | candidate/no_memory |
| smoke-C4-cross-project-near-match | yes/yes | 0/0 | 1/1 | –/– | 690/690 | 43428 | 0.464/0.334 | candidate/no_memory |
| smoke-L1-ledgerlite-test-command | yes/yes | 0/1 | 0/0 | –/– | 718/779 | 70494 | 0.401/0.313 | candidate/no_memory |
| smoke-L2-fieldnotes-iso-dates | yes/no | 0/0 | 1/2 | –/– | 550/429 | 97528 | 0.285/0.169 | candidate/no_memory |
| smoke-L3-household-grocery-budget | yes/no | 0/0 | 0/0 | –/– | 234/95 | 86182 | 0.145/0.001 | candidate/no_memory |
| smoke-L4-ledgerlite-resume-refactor | no/no | 0/0 | 1/1 | –/– | 747/747 | 39069 | 0.284/0.135 | candidate/no_memory |
| smoke-R1-fieldnotes-check-env-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 677/421 | 101875 | 0.378/0.285 | candidate/no_memory |
| smoke-R2-ledgerlite-import-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 859/579 | 61421 | 0.366/0.204 | candidate/no_memory |
| smoke-R3-household-budget-correction | yes/yes | 0/0 | 0/0 | –/– | 217/89 | 67511 | 0.157/0.001 | candidate/no_memory |
| smoke-R4-fieldnotes-storage-conflict | yes/yes | 0/0 | 0/0 | –/– | 247/83 | 81411 | 0.341/0.152 | candidate/no_memory |

Paired differences (candidate − baseline), mean with a 95 % interval from resampling whole scenarios:

- task_success: n=12, mean=0.1667, CI95=(0.0, 0.4167), inconclusive
- repeated_mistakes: n=12, mean=-0.0833, CI95=(-0.25, 0.0), inconclusive
- detours: n=12, mean=-0.0833, CI95=(-0.25, 0.0), inconclusive
- legitimate_retry_success: n=2, mean=0.0, CI95=(0.0, 0.0), inconclusive
- foreground_tokens: n=12, mean=85.5833, CI95=(24.8333, 148.0833)
- background_tokens: n=12, mean=71899.9167, CI95=(58882.6667, 84460.5)
- elapsed_seconds: n=12, mean=0.125, CI95=(0.1063, 0.1451)
- operator_interventions: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- repeated failures on relevant scenarios: candidate 0, baseline 1, relative reduction 1.0 (>= 0.25 (Cut 2 gate; not a preview gate))

No superiority claim: a 12-scenario smoke run with one trial per arm cannot establish one (ACCEPTANCE_TESTS §6.1).

## §5.1 quality on the smoke population

| Measure | Value | Numerator/denominator | Wilson 95 % | Target | Met |
|---|---|---|---|---|---|
| supported_precision | 1 | 8/8 | (0.6756, 1.0) | >= 0.95 | True |
| useful_recall | 1 | 8/8 | (0.6756, 1.0) | >= 0.85 | True |
| failed_approach_recall | 1 | 3/3 | (0.4385, 1.0) | >= 0.9 | True |
| incorrect_confident_guidance | 0 | count over 12 | None | == 0 | True |
| conflict_uncertainty_preservation | 1 | 1/1 | (0.2065, 1.0) | >= 0.95 | True |
| legitimate_retry_discouraged | 0 | 0/2 | (0.0, 0.6576) | <= 0.05 | True |
| irrelevant_caution_quiet | 0 | 0/3 | (0.0, 0.5615) | <= 0.05 | True |
| routine_human_maintenance | 0 | count over 12 | None | == 0 | True |

## §5.2 operational measures

```json
{
 "budget_exhaustion": {
  "backlog_at_day_end": {
   "fieldnotes": {
    "jobs": 2,
    "kinds": [
     "extract_claims",
     "update_task"
    ],
    "oldest_age_seconds": 1591.0
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
   "numerator": 1,
   "value": 0.3333,
   "wilson_95": [
    0.0615,
    0.7923
   ]
  },
  "median_hours_to_exhaustion": 7.575,
  "nonexhausted_censored_days": 2,
  "pools_hit": [
   "ordinary.input_estimate"
  ],
  "priority_inversions": 0,
  "scenario_days": 3,
  "waiting_seconds": {
   "correction_declaration_review": {
    "max": 1.0,
    "n": 3,
    "p50": 1.0,
    "p95": 1.0
   },
   "ordinary": {
    "max": 3.0,
    "n": 90,
    "p50": 0.0,
    "p95": 2.0
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
   "admitted_claims": 2,
   "calls": 36,
   "calls_by_purpose": {
    "build_episode": 9,
    "extract_claims": 18,
    "review_claims": 2,
    "update_task": 7
   },
   "calls_per_admitted_claim": 18.0,
   "calls_per_settled_episode": 4.0,
   "estimated_tokens_by_purpose": {
    "build_episode": 153317,
    "extract_claims": 326579,
    "review_claims": 8451,
    "update_task": 109922
   },
   "processing": "recorded backend: immediate (no provider latency)",
   "queue_wait_seconds": {
    "max": 3.0,
    "n": 36,
    "p50": 0.0,
    "p95": 2.0
   },
   "settled_episodes": 9
  },
  "household": {
   "admitted_claims": 1,
   "calls": 26,
   "calls_by_purpose": {
    "build_episode": 8,
    "extract_claims": 9,
    "review_claims": 1,
    "update_task": 8
   },
   "calls_per_admitted_claim": 26.0,
   "calls_per_settled_episode": 3.25,
   "estimated_tokens_by_purpose": {
    "build_episode": 104721,
    "extract_claims": 134288,
    "review_claims": 3462,
    "update_task": 108878
   },
   "processing": "recorded backend: immediate (no provider latency)",
   "queue_wait_seconds": {
    "max": 2.0,
    "n": 26,
    "p50": 1.0,
    "p95": 2.0
   },
   "settled_episodes": 8
  },
  "ledgerlite": {
   "admitted_claims": 3,
   "calls": 34,
   "calls_by_purpose": {
    "build_episode": 7,
    "extract_claims": 18,
    "review_claims": 3,
    "update_task": 6
   },
   "calls_per_admitted_claim": 11.333,
   "calls_per_settled_episode": 4.857,
   "estimated_tokens_by_purpose": {
    "build_episode": 133389,
    "extract_claims": 334544,
    "review_claims": 13823,
    "update_task": 100780
   },
   "processing": "recorded backend: immediate (no provider latency)",
   "queue_wait_seconds": {
    "max": 2.0,
    "n": 34,
    "p50": 0.0,
    "p95": 2.0
   },
   "settled_episodes": 7
  }
 },
 "delivery_visibility": {
  "paths": {
   "claude_code": {
    "contaminated_runs": "none recorded",
    "host_version": "2.1.306",
    "live": "not_run",
    "paths": {
     "compact": {
      "live": "not_run",
      "request_capture": {
       "negatives_clean": 3,
       "positives_hook_emitted": 3,
       "positives_visible_in_request": 3,
       "state": "request_visible"
      }
     },
     "pre_action": {
      "live": "not_run",
      "request_capture": {
       "negatives_clean": 3,
       "positives_hook_emitted": 3,
       "positives_visible_in_request": 3,
       "state": "request_visible"
      }
     },
     "prompt": {
      "live": "not_run",
      "request_capture": {
       "negatives_clean": 3,
       "positives_hook_emitted": 3,
       "positives_visible_in_request": 3,
       "state": "request_visible"
      }
     },
     "session_start": {
      "live": "not_run",
      "request_capture": {
       "negatives_clean": 3,
       "positives_hook_emitted": 3,
       "positives_visible_in_request": 3,
       "state": "request_visible"
      }
     }
    }
   }
  },
  "source": "docs/host-compatibility.json (sections.delivery_engine)"
 },
 "evidence_strength_distribution": {
  "fieldnotes": {
   "day_end": {
    "corroborated:inferred": 1,
    "supported:user_declared": 1
   },
   "first_admission": {
    "corroborated:inferred": 1,
    "supported:user_declared": 1
   }
  },
  "household": {
   "day_end": {
    "supported:user_declared": 1
   },
   "first_admission": {
    "supported:user_declared": 1
   }
  },
  "ledgerlite": {
   "day_end": {
    "corroborated:inferred": 1,
    "supported:inferred": 1,
    "supported:user_declared": 1
   },
   "first_admission": {
    "corroborated:inferred": 1,
    "supported:inferred": 1,
    "supported:user_declared": 1
   }
  },
  "smoke": {
   "active:corroborated:inferred": 1,
   "active:supported:inferred": 3,
   "active:supported:user_declared": 4,
   "superseded:supported:user_declared": 1
  }
 },
 "false_suppression": {
  "denominator": 1,
  "examples": [],
  "numerator": 0,
  "value": 0.0,
  "wilson_95": [
   0.0,
   0.7935
  ]
 },
 "same_session_learning_latency": {
  "smoke": {
   "count": 10,
   "observations": [
    {
     "caution_delivered": false,
     "failure": "python -m unittest discover -s tests",
     "next_pre_action_state": "none"
    },
    {
     "caution_delivered": false,
     "failure": "NOTES_HOME='~/notes' python -m unittest tests.test_delete",
     "next_pre_action_state": "none"
    },
    {
     "caution_delivered": false,
     "failure": "python tools/check.py",
     "next_pre_action_state": "none"
    },
    {
     "caution_delivered": false,
     "failure": "python -m unittest discover -s tests",
     "next_pre_action_state": "none"
    },
    {
     "caution_delivered": false,
     "failure": "python tools/check.py",
     "next_pre_action_state": "none"
    },
    {
     "caution_delivered": false,
     "failure": "python -m unittest discover -s tests",
     "next_pre_action_state": "none"
    },
    {
     "caution_delivered": false,
     "failure": "python tools/check.py",
     "next_pre_action_state": "none"
    },
    {
     "caution_delivered": false,
     "failure": "python -m unittest discover -s tests",
     "next_pre_action_state": "none"
    },
    {
     "caution_delivered": false,
     "failure": "python tools/check.py",
     "next_pre_action_state": "none"
    },
    {
     "caution_delivered": false,
     "failure": "python -m unittest discover -s tests -t .",
     "next_pre_action_state": "none"
    }
   ]
  },
  "workload": {
   "fieldnotes": {
    "count": 10,
    "observations": [
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 16.0,
      "mentions_failure": true,
      "session": "S1",
      "state": "emitted"
     },
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 22.0,
      "mentions_failure": true,
      "session": "S3",
      "state": "emitted"
     },
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 25.0,
      "mentions_failure": false,
      "session": "S3",
      "state": "emitted"
     },
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 43.0,
      "mentions_failure": false,
      "session": "S4",
      "state": "emitted"
     },
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 44.0,
      "mentions_failure": false,
      "session": "S5",
      "state": "emitted"
     },
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 69.0,
      "mentions_failure": false,
      "session": "S5",
      "state": "emitted"
     },
     {
      "degraded": [],
      "delivered": false,
      "interval_s": 138.0,
      "mentions_failure": false,
      "session": "S5",
      "state": "none"
     },
     {
      "degraded": [],
      "delivered": false,
      "interval_s": 34.0,
      "mentions_failure": false,
      "session": "S5",
      "state": "none"
     },
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 44.0,
      "mentions_failure": true,
      "session": "S6",
      "state": "emitted"
     },
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 46.0,
      "mentions_failure": false,
      "session": "S7",
      "state": "emitted"
     }
    ],
    "pre_action_vs_prompt": "pre-action path measured; prompt fallback not exercised (pre-action enabled)"
   },
   "household": {
    "count": 1,
    "observations": [
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 68.0,
      "mentions_failure": true,
      "session": "S4",
      "state": "emitted"
     }
    ],
    "pre_action_vs_prompt": "pre-action path measured; prompt fallback not exercised (pre-action enabled)"
   },
   "ledgerlite": {
    "count": 11,
    "observations": [
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 43.0,
      "mentions_failure": true,
      "session": "S1",
      "state": "emitted"
     },
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 38.0,
      "mentions_failure": true,
      "session": "S2",
      "state": "emitted"
     },
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 48.0,
      "mentions_failure": false,
      "session": "S2",
      "state": "emitted"
     },
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 55.0,
      "mentions_failure": false,
      "session": "S4",
      "state": "emitted"
     },
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 49.0,
      "mentions_failure": false,
      "session": "S4",
      "state": "emitted"
     },
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 47.0,
      "mentions_failure": false,
      "session": "S4",
      "state": "emitted"
     },
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 9.0,
      "mentions_failure": false,
      "session": "S5",
      "state": "emitted"
     },
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 34.0,
      "mentions_failure": false,
      "session": "S5",
      "state": "emitted"
     },
     {
      "degraded": [],
      "delivered": false,
      "interval_s": 26.0,
      "mentions_failure": false,
      "session": "S5",
      "state": "none"
     },
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 12.0,
      "mentions_failure": true,
      "session": "S7",
      "state": "emitted"
     },
     {
      "degraded": [],
      "delivered": true,
      "interval_s": 27.0,
      "mentions_failure": false,
      "session": "S8",
      "state": "emitted"
     }
    ],
    "pre_action_vs_prompt": "pre-action path measured; prompt fallback not exercised (pre-action enabled)"
   }
  }
 },
 "task_over_fragmentation": {
  "fieldnotes": {
   "attempt_result_severed": 0,
   "boundary_precision": null,
   "boundary_recall": null,
   "confirmed": 0,
   "created_tasks": 8,
   "current_nonredirected_heads": 8,
   "deterministic_link_reversals": 0,
   "gold_tasks": 7,
   "linked_placeholders": 0,
   "provisional": 195,
   "ratio": 1.143
  },
  "household": {
   "attempt_result_severed": 0,
   "boundary_precision": null,
   "boundary_recall": null,
   "confirmed": 0,
   "created_tasks": 8,
   "current_nonredirected_heads": 7,
   "deterministic_link_reversals": 0,
   "gold_tasks": 4,
   "linked_placeholders": 1,
   "provisional": 95,
   "ratio": 2.0
  },
  "ledgerlite": {
   "attempt_result_severed": 0,
   "boundary_precision": null,
   "boundary_recall": null,
   "confirmed": 0,
   "created_tasks": 9,
   "current_nonredirected_heads": 9,
   "deterministic_link_reversals": 0,
   "gold_tasks": 7,
   "linked_placeholders": 0,
   "provisional": 197,
   "ratio": 1.286
  }
 }
}
```

## Expected retrieval points (candidate)

9/12 satisfied (Wilson 95 % (0.4677, 0.9111)). Unmet:

- smoke-L1-ledgerlite-test-command: {"must_include": "PYTHONPATH=src", "purpose": "session_start", "session": "B"} (0 items delivered at that point)
- smoke-L4-ledgerlite-resume-refactor: {"must_include": "money.parse", "purpose": "session_start", "session": "B"} (0 items delivered at that point)
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
       "tools/check.py fails with KeyError unless NOTES_HOME is set.",
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
         "text": "Failure lesson: tools/check.py fails with KeyError unless NOTES_HOME is set. Observed: `python tools/check.py` failed with KeyError: 'NOTES_HOME'. Alternative: "
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
      "revalidate:revise_claim"
     ],
     "task_success": true
    },
    "smoke-R2-ledgerlite-import-fixed": {
     "legitimate_retry_success": true,
     "lesson": [
      [
       "Plain discovery fails to import ledgerlite without PYTHONPATH=src.",
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
         "text": "Failure lesson: Plain discovery fails to import ledgerlite without PYTHONPATH=src. Observed: `python -m unittest discover -s tests -t .` failed: the tests direc"
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
     "revalidation": [
      "revalidate:revise_claim"
     ],
     "task_success": true
    }
   }
  },
  "forgetting_and_restore": {
   "backup_before": {
    "external_copy": true,
    "manifest_digest": "636e95f570ad8fb756997ecb199a3c5616abfded194d3562868015bb57d4ec5d",
    "store_hits_before": 20
   },
   "delivered_after_forget": false,
   "delivered_after_restore": false,
   "demonstrated": true,
   "forget": {
    "backup_state": "verified",
    "deleted_backups": 1,
    "limits": [
     "external_exports_not_recallable",
     "remote_provider_copies_not_recallable",
     "operator_backup_copies_not_recallable",
     "filesystem_forensics_outside_guarantee",
     "ledger_digest_membership_disclosure",
     "paraphrase_not_detected"
    ],
    "purge_state": "completed",
    "purged": 24,
    "quarantined": 0,
    "recorded_pre_forget_backup_deleted": true
   },
   "guarded_cli_from_this_process": {
    "exit": 6,
    "refusal": "host_marker_present"
   },
   "restore": {
    "applied_schema": 10,
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
    "restored_revision": 97,
    "source_contains_suppressed": true,
    "suppressed_record_count": 24
   },
   "route": "service operator actor (test-fixture route, as the Task 16 suites)",
   "scenario": "smoke-L3-household-grocery-budget",
   "selector": {
    "claims": 1,
    "tasks": 1
   },
   "store_hits_after_forget": 0,
   "store_hits_after_restore": 0
  },
  "fresh_session_reuse": {
   "admitted": [
    "Without PYTHONPATH=src the src-layout package is not importable from tests; plain discovery fails or runs nothing.",
    "Run the ledgerlite tests with `PYTHONPATH=src python -m unittest discover -s tests` from the project root."
   ],
   "baseline_repeated_mistakes": 1,
   "candidate_first_test_command_in_B": "PYTHONPATH=src python -m unittest discover -s tests",
   "candidate_repeated_mistakes": 0,
   "demonstrated": true,
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
    "tools/check.py fails with KeyError unless NOTES_HOME is set."
   ],
   "fieldnotes_session_b_delivered": [],
   "installations": {
    "distinct": true,
    "fieldnotes": "inst_8c437d36-96b2-450a-a661-173fdfddbbc1",
    "ledgerlite": "inst_d092ef80-d9e7-4ba4-a460-b5119b89c481"
   },
   "ledgerlite_active_claims": [
    "Without PYTHONPATH=src the src-layout package is not importable from tests; plain discovery fails or runs nothing.",
    "Run the ledgerlite tests with `PYTHONPATH=src python -m unittest discover -s tests` from the project root."
   ],
   "scenario": "smoke-C4-cross-project-near-match",
   "task_success": true
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
 "label": "scripted agent + recorded curator through the real engine; not a live demonstration (B1)",
 "mode": "scripted"
}
```

## Unsuccessful runs

- {'scenario': 'smoke-L2-fieldnotes-iso-dates', 'arm': 'no_memory', 'reason': 'task_failed'}
- {'scenario': 'smoke-L3-household-grocery-budget', 'arm': 'no_memory', 'reason': 'task_failed'}
- {'scenario': 'smoke-L4-ledgerlite-resume-refactor', 'arm': 'candidate', 'reason': 'task_failed'}
- {'scenario': 'smoke-L4-ledgerlite-resume-refactor', 'arm': 'no_memory', 'reason': 'task_failed'}

## Cost and time

```json
{
 "actual": {
  "background_model_calls": 174,
  "elapsed_seconds": 5.9,
  "foreground_sessions": 48,
  "mode": "scripted",
  "provider_cost_note": "recorded mode: no provider call was made; the background calls were answered by the recorded curator",
  "provider_cost_usd": 0.0
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
  "reason": "a live pilot needs a certified route (B1)",
  "state": "not_run"
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
  "installed_host_observation": {
   "configuration": {
    "env": [
     "CLAUDE_CODE_DISABLE_AUTO_MEMORY"
    ],
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
   "host_version": "2.1.306 (Claude Code)",
   "method": "request capture (loopback endpoint, placeholder key); planted MEMORY.md sentinel",
   "state": "disabled"
  },
  "scripted_arms": "not applicable: the scripted agent has no host-native memory"
 },
 "versions": {
  "certified_capture_versions": [
   "2.1.301",
   "2.1.305",
   "2.1.306"
  ],
  "commit": "b6598eedd242b851ec5a5e99452b3f35cbd41ada",
  "engine": "0.1.0.dev0",
  "installed_host": "2.1.306 (Claude Code)",
  "platform": "Linux 6.18.44-fc-v139 x86_64",
  "prompts": {
   "build_episode": "build_episode@1",
   "extract_claims": "extract_claims@1",
   "revalidate": "revalidate@1",
   "review_claims": "review_claims@1",
   "update_task": "update_task@1"
  },
  "python": "3.13.16",
  "schema": 10,
  "scripted_payload_format": "Claude Code 2.1.305 (reviewed fixtures)",
  "sqlite": "3.45.1",
  "tree_clean": false
 }
}
```

## Limitations

- B1: no certified inference route and no live host certification, so no live trial ran; every number here is recorded-mode mechanics, not a live measurement.
- The working agent is a fixed scripted policy (evals/agent.py) that reads only the delivered context at its branch points; it measures whether the engine delivered the right thing, not how a live agent uses it.
- The curator is recorded proposals (evals/curator.py) written with knowledge of the gold; §5.1 extraction quality is therefore not measured (precision and recall reflect the deterministic pipeline admitting or rejecting those proposals).
- Hooks run in process through the real stdlib hook path with Claude Code 2.1.305-shaped payloads (map_hook, handle_hook) and a controlled delivery manifest; the installed launcher and the real host are not in the loop.
- Scheduling runs on a virtual clock (sessions two hours apart, worker drains to a three-hour idle horizon); provider latency and queue time are not real.
- Background tokens are the engine's own charged estimates (ceil(bytes/3) and output allowances); the recorded backend reports no provider usage.
- Smoke scenarios, gold labels and workload days were authored by the coding agent, who has read SYSTEM_SPEC §7; no held-out or independent corpus exists.
- One trial per arm and 12 scenarios: intervals are wide and inconclusive by construction; no superiority claim is made.
- Each smoke store holds only a few claims, so hook views always contain every relevant claim here; at reference scale (10,000 heads) the hook's query-independent views omit prompt-specific facts (decision 0020 item 15, docs/measurements/release-gate-latency-linux.json), which this run cannot show.
