# Preview evaluation report (live)

**live working agent and certified inference route.** Counts toward the preview gate: **True**. Gate: **failed**.

- quality_targets_unmet:conflict_uncertainty_preservation
- claims_unadjudicated:31 (evals/run.py adjudicate)

## Paired outcomes (candidate vs clean no-memory baseline)

| Scenario | Success C/B | Repeated mistakes C/B | Detours C/B | Retry C/B | Foreground tok C/B | Background tok C | Elapsed s C/B | Labels C/B |
|---|---|---|---|---|---|---|---|---|
| smoke-C1-ledgerlite-routine-typo | yes/yes | 0/0 | 0/0 | –/– | 124446/123609 | 138439 | 32.6/24.3 | candidate/no_memory |
| smoke-C2-fieldnotes-tdd-expected-red | yes/yes | 0/0 | 2/0 | –/– | 406931/248847 | 475521 | 91.6/62.0 | candidate/no_memory |
| smoke-C3-household-utilities-speculation | yes/yes | 0/0 | 0/0 | –/– | 71964/71796 | 63115 | 39.8/28.4 | candidate/no_memory |
| smoke-C4-cross-project-near-match | yes/yes | 0/0 | 0/1 | –/– | 195586/181857 | 145414 | 31.7/37.2 | candidate/no_memory |
| smoke-L1-ledgerlite-test-command | yes/yes | 0/0 | 0/0 | –/– | 174523/164775 | 296286 | 34.0/31.8 | candidate/no_memory |
| smoke-L2-fieldnotes-iso-dates | yes/yes | 0/0 | 0/0 | –/– | 228533/150023 | 340017 | 42.9/35.2 | candidate/no_memory |
| smoke-L3-household-grocery-budget | yes/yes | 0/0 | 0/0 | –/– | 147073/128515 | 160323 | 32.8/35.0 | candidate/no_memory |
| smoke-L4-ledgerlite-resume-refactor | no/yes | 0/0 | 0/0 | –/– | 174397/187760 | 290932 | 34.3/32.4 | candidate/no_memory |
| smoke-R1-fieldnotes-check-env-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 127172/125084 | 238494 | 26.3/22.2 | candidate/no_memory |
| smoke-R2-ledgerlite-import-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 154952/127330 | 170747 | 29.0/21.7 | candidate/no_memory |
| smoke-R3-household-budget-correction | no/yes | 0/0 | 0/0 | –/– | 54306/55272 | 72521 | 21.2/22.7 | candidate/no_memory |
| smoke-R4-fieldnotes-storage-conflict | yes/yes | 0/0 | 0/0 | –/– | 201441/149720 | 286787 | 38.0/31.3 | candidate/no_memory |

Paired differences (candidate − baseline), mean with a 95 % interval from resampling whole scenarios:

- task_success: n=12, mean=-0.1667, CI95=(-0.4167, 0.0), inconclusive
- repeated_mistakes: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- detours: n=12, mean=0.0833, CI95=(-0.25, 0.5), inconclusive
- legitimate_retry_success: n=2, mean=0.0, CI95=(0.0, 0.0), inconclusive
- foreground_tokens: n=12, mean=28894.6667, CI95=(5716.3333, 56622.6667)
- background_tokens: n=12, mean=223216.3333, CI95=(158859.4167, 287251.75)
- elapsed_seconds: n=12, mean=5.8363, CI95=(1.5665, 10.8384)
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
| conflict_uncertainty_preservation | 0 | 0/1 | (0.0, 0.7935) | >= 0.95 | False |
| legitimate_retry_discouraged | 0 | 0/2 | (0.0, 0.6576) | <= 0.05 | True |
| irrelevant_caution_quiet | 0 | 0/3 | (0.0, 0.5615) | <= 0.05 | True |
| routine_human_maintenance | 0 | count over 12 | None | == 0 | True |

Support and recall come from reviewer labels (`adjudication.json`); 31 item(s) unlabeled (`evals/run.py adjudicate`). Lessons whose evidence never occurred: 0. fewer than two independent reviewers (ACCEPTANCE_TESTS §5: report the limitation)
Term match (provisional, frozen against the recorded curator's wording): supported_precision 11/23, useful_recall 7/8, failed_approach_recall 2/3

## Curator call outcomes

```json
{
 "smoke": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 21,
    "replies_parsed": 21,
    "reported_input_tokens": 666450,
    "reported_output_tokens": 37816,
    "visible_output_estimate": 11724
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 26,
    "replies_parsed": 26,
    "reported_input_tokens": 947953,
    "reported_output_tokens": 73930,
    "visible_output_estimate": 15730
   },
   "revalidate": {
    "at_output_cap": 0,
    "calls": 4,
    "replies_parsed": 4,
    "reported_input_tokens": 46157,
    "reported_output_tokens": 4531,
    "visible_output_estimate": 1058
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 18,
    "replies_parsed": 18,
    "reported_input_tokens": 163273,
    "reported_output_tokens": 27783,
    "visible_output_estimate": 5440
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 21,
    "replies_parsed": 21,
    "reported_input_tokens": 671618,
    "reported_output_tokens": 39085,
    "visible_output_estimate": 10695
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
    "calls": 26,
    "replies_parsed": 26,
    "reported_input_tokens": 688331,
    "reported_output_tokens": 54890,
    "visible_output_estimate": 15625
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 46,
    "replies_parsed": 46,
    "reported_input_tokens": 1271741,
    "reported_output_tokens": 59156,
    "visible_output_estimate": 8280
   },
   "revalidate": {
    "at_output_cap": 0,
    "calls": 2,
    "replies_parsed": 2,
    "reported_input_tokens": 17540,
    "reported_output_tokens": 3206,
    "visible_output_estimate": 817
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 7,
    "replies_parsed": 7,
    "reported_input_tokens": 40731,
    "reported_output_tokens": 6610,
    "visible_output_estimate": 1312
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 23,
    "replies_parsed": 23,
    "reported_input_tokens": 542829,
    "reported_output_tokens": 33467,
    "visible_output_estimate": 9378
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
    "n": 97,
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
   "admitted_claims": 4,
   "calls": 43,
   "calls_by_purpose": {
    "build_episode": 10,
    "extract_claims": 19,
    "revalidate": 2,
    "review_claims": 3,
    "update_task": 9
   },
   "calls_per_admitted_claim": 10.75,
   "calls_per_settled_episode": 4.778,
   "estimated_tokens_by_purpose": {
    "build_episode": 170617,
    "extract_claims": 367595,
    "revalidate": 12907,
    "review_claims": 13894,
    "update_task": 136726
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 21.158,
     "n": 43,
     "p50": 8.069,
     "p95": 15.963
    }
   },
   "proposals": [
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "revise_episode",
       "outcome": "reject",
       "reason": "invalid_result"
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
     "operations": [],
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
     "no_op_reason": "The existing failure_lesson claim already cites the NOTES_HOME KeyError failure and the supporting successful run with NOTES_HOME set. The session adds no new durable fact, decision, or preference beyond what the claim records.",
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
     "decisions": [],
     "operations": [],
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
     "operations": [],
     "purpose": "update_task"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "Durable outcomes are already covered: the NOTES_HOME failure lesson and the ISO-8601 date decision exist as active claims. The remaining items (the date-format test failure and the passing run) lack an exact observed proposition or a file-level basis, so proposing them would be weak.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's only durable failure, the NOTES_HOME requirement, is already recorded as an active claim. The export test failure has no numeric exit code, so it cannot be recorded as observed, and the session contains no user statement of a project rule or preference.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "No new durable project knowledge: the session's events show a transient test failure, an edit and a passing check, and the user declarations and NOTES_HOME lesson are already recorded as claims.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "operations": [],
     "purpose": "build_episode"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's durable-looking content is a one-off task instruction already captured in the task, and the tool results show an expected TDD red test, a passing run, and no reusable lesson or project-wide decision.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "operations": [],
     "purpose": "update_task"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's durable content is already captured: the ISO-8601 date decision and the NOTES_HOME failure lesson exist. The remaining events are transient TDD steps, and the user's task objective is not citable from allowed_evidence_refs. The session boundary stays pending.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's events show only reads, one Edit of a placeholder body, and a failing Bash run with no stated cause. No user declaration of a rule, decision or preference appears in the events, and the one failed run is transient rather than durable project knowledge.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's only durable-looking material is a test failure from an unparsed Bash command with no exact argv, an Edit whose result is ambiguous, and read-only tool calls. The user's objective cites an event outside allowed_evidence_refs, and the existing claims already cover the ISO date rule and the NOTES_HOME failure. Nothing here meets the bar for a new claim.",
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
     "no_op_reason": "This session only read files, made one Edit, and ran one failing Bash check whose output is a transient test failure. The user's storage-migration objective is not citable from an allowed evidence record, and no explicit user declaration of a rule or preference appears in the request's events.",
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
     "decisions": [],
     "no_op_reason": "Session only re-ran a failing check and read/edited files; the test failure, NOTES_HOME lesson, storage decision and ISO-date rule are already recorded, and the single-run exit code is transient, so nothing new is durable.",
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
     "no_op_reason": "The durable outcomes are already recorded as active claims: the notes.jsonl storage decision (claim_e9b30dd5), the ISO-8601 date rule, the NOTES_HOME failure lesson, and the test_roundtrip failure claim. The remaining events are routine reads and edits, and the test runs passed or failed as already captured.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "operations": [],
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
     "no_op_reason": "Existing claims already cover the NOTES_HOME failure and the test failure. The session's remaining results are one-off outcomes, and the user's message is a task request, not a durable rule or preference.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session shows only a partial edit and test reruns; no narrative field (title, plan, constraints, open questions, next action) needs changing. The boundary stays pending.",
     "operations": [],
     "purpose": "update_task"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The failure lesson for tools/check.py without NOTES_HOME is already recorded as claim_20bf5785. The later successful run with NOTES_HOME set does not clearly contradict the existing test_roundtrip claim, and nothing else in this session is a new durable rule, decisi
```

## Expected retrieval points (candidate)

9/12 satisfied (Wilson 95 % (0.4677, 0.9111)). Unmet:

- smoke-L1-ledgerlite-test-command: {"must_include": "PYTHONPATH=src", "purpose": "session_start", "session": "B"} (0 items delivered at that point)
- smoke-L4-ledgerlite-resume-refactor: {"must_include": "money.parse", "purpose": "session_start", "session": "B"} (0 items delivered at that point)
- smoke-R4-fieldnotes-storage-conflict: {"advice": "conflict_or_freshness_label", "purpose": "prompt", "session": "C"} (2 items delivered at that point)

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
       "With NOTES_HOME set to a temporary directory, the python tools/check.py run reported its one unit test as OK; the exit status of that run was not recorded.",
       "active",
       "current",
       2
      ],
      [
       "Running python tools/check.py without NOTES_HOME set exits with code 1 and a KeyError for NOTES_HOME.",
       "active",
       "current",
       9
      ]
     ],
     "retry_point": [
      {
       "delivered": true,
       "items": [
        {
         "advice": "context",
         "freshness": "current",
         "text": "Failure lesson: Running python tools/check.py without NOTES_HOME set exits with code 1 and a KeyError for NOTES_HOME. Observed: The run of python tools/check.py"
        },
        {
         "advice": "context",
         "freshness": "current",
         "text": "Fact: With NOTES_HOME set to a temporary directory, the python tools/check.py run reported its one unit test as OK; the exit status of that run was not recorded"
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
       "In the session, after tests/__init__.py was added, the command `python -m unittest discover -s tests -t .` printed 'Ran 2 tests' and 'OK'.",
       "active",
       "current",
       2
      ],
      [
       "Before tests/__init__.py was added, the output of `python -m unittest discover -s tests -t .` included 'ImportError: Start directory is not importable' for the tests directory.",
       "active",
       "current",
       2
      ],
      [
       "The user prefers that the test command `python -m unittest discover -s tests -t .` stay unchanged when making the ledgerlite tests pass, and would change it only if no other fix works.",
       "candidate",
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
         "text": "Fact: In the session, after tests/__init__.py was added, the command `python -m unittest discover -s tests -t .` printed 'Ran 2 tests' and 'OK'."
        },
        {
         "advice": "context",
         "freshness": "current",
         "text": "Fact: Before tests/__init__.py was added, the output of `python -m unittest discover -s tests -t .` included 'ImportError: Start directory is not importable' fo"
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
    "manifest_digest": "baa87f0067986c7af6b7400d8f4c9d51c2e70b600dc9458b4ac75d21b5b5a79c",
    "store_hits_before": 15
   },
   "delivered_after_forget": false,
   "delivered_after_restore": false,
   "demonstrated": true,
   "forget": {
    "backup_state": "verified",
    "purge_state": "completed",
    "purged_count": 13,
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
    "restored_revision": 120,
    "source_contains_suppressed": true,
    "suppressed_record_count": 13
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
    "smoke-L3-household-grocery-budget"
   ],
   "not_run": [],
   "note": "one trial per arm: a demonstration that reuse happened, not an estimate of its benefit (a Cut 2 comparison). The gold text may arrive in any packet of session B (L1's session-start point is unmet by design, decision 0013, and its prompt packet carries the lesson)",
   "remember_instruction": false,
   "scenarios": {
    "smoke-L1-ledgerlite-test-command": {
     "admitted": [
      "tests/test_ledger.py defines test_close_requires_zero_balance, which checks that closing a non-zero account raises ValueError and leaves the account in place, and that the account is removed after its balance is returned to zero.",
      "The captured output of running PYTHONPATH=src python -m unittest discover -s tests -v from the project root ends with 'Ran 3 tests' and 'OK', listing test_close_requires_zero_balance, test_rejects_non_positive_amount and test_transfer_preserves_total as ok.",
      "Running `python -m unittest discover -s tests -v` from the project root, without PYTHONPATH=src, fails on import with ModuleNotFoundError: No module named 'ledgerlite' in the captured output.",
      "Ledger.close(name) in src/ledgerlite/__init__.py raises ValueError when the account's balance is not zero and otherwise deletes that account from Ledger.accounts."
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
      "Every date fieldnotes prints must be ISO-8601 (YYYY-MM-DD...); locale formats such as 'Jan 2' or '02/01/2026' must not be used.",
      "fieldnotes export prints one line per stored note in the form 'DATE: TEXT', where DATE is the first 10 characters of the note's stored 'created' value (the ISO-8601 date part). The formatting is in store.export_lines(), which cli.py calls for the export command.",
      "To run the fieldnotes project checks, run `python tools/check.py` from the project root with the NOTES_HOME environment variable set to a scratch directory, because tools/check.py reads os.environ['NOTES_HOME']."
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
   
```

## Unsuccessful runs

- {'scenario': 'smoke-L4-ledgerlite-resume-refactor', 'arm': 'candidate', 'reason': 'task_failed'}
- {'scenario': 'smoke-R3-household-budget-correction', 'arm': 'candidate', 'reason': 'task_failed'}

## Cost and time

```json
{
 "actual": {
  "background_model_calls": 194,
  "background_tokens": 4371430,
  "elapsed_seconds": 838.3,
  "foreground_cost_usd": 1.7837,
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
  "commit": "0510cf2a1ef3bcd9bcc33a4de9a1655a0d928c0f",
  "engine": "0.1.0.dev5",
  "installed_host": "2.1.310 (Claude Code)",
  "platform": "Windows 11 AMD64",
  "prompts": {
   "build_episode": "build_episode@1",
   "extract_claims": "extract_claims@3",
   "revalidate": "revalidate@2",
   "review_claims": "review_claims@1",
   "update_task": "update_task@1"
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
