# Preview evaluation report (live)

**live working agent and certified inference route.** Counts toward the preview gate: **True**. Gate: **failed**.

- quality_targets_unmet:incorrect_confident_guidance
- claims_unadjudicated:22 (evals/run.py adjudicate)

## Paired outcomes (candidate vs clean no-memory baseline)

| Scenario | Success C/B | Repeated mistakes C/B | Detours C/B | Retry C/B | Foreground tok C/B | Background tok C | Elapsed s C/B | Labels C/B |
|---|---|---|---|---|---|---|---|---|
| smoke-C1-ledgerlite-routine-typo | yes/yes | 0/0 | 0/0 | –/– | 124455/123595 | 140784 | 21.1/18.7 | candidate/no_memory |
| smoke-C2-fieldnotes-tdd-expected-red | yes/yes | 0/0 | 2/0 | –/– | 359148/249973 | 451772 | 79.8/54.9 | candidate/no_memory |
| smoke-C3-household-utilities-speculation | yes/yes | 0/0 | 0/0 | –/– | 72862/71971 | 93845 | 23.5/23.6 | candidate/no_memory |
| smoke-C4-cross-project-near-match | yes/yes | 0/0 | 1/1 | –/– | 212757/198967 | 144535 | 35.2/30.0 | candidate/no_memory |
| smoke-L1-ledgerlite-test-command | yes/yes | 0/0 | 0/0 | –/– | 202028/165977 | 391907 | 33.3/23.8 | candidate/no_memory |
| smoke-L2-fieldnotes-iso-dates | yes/yes | 0/0 | 0/0 | –/– | 194060/131397 | 397087 | 37.3/29.4 | candidate/no_memory |
| smoke-L3-household-grocery-budget | yes/yes | 0/0 | 1/0 | –/– | 127610/146595 | 174127 | 29.8/31.1 | candidate/no_memory |
| smoke-L4-ledgerlite-resume-refactor | yes/yes | 0/0 | 0/1 | –/– | 227093/163435 | 274897 | 39.4/30.7 | candidate/no_memory |
| smoke-R1-fieldnotes-check-env-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 127156/124889 | 238932 | 22.9/19.1 | candidate/no_memory |
| smoke-R2-ledgerlite-import-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 128006/108773 | 156444 | 22.3/19.6 | candidate/no_memory |
| smoke-R3-household-budget-correction | no/yes | 0/0 | 0/0 | –/– | 57111/54587 | 96151 | 25.9/18.6 | candidate/no_memory |
| smoke-R4-fieldnotes-storage-conflict | yes/yes | 0/0 | 0/0 | –/– | 202143/148802 | 277273 | 32.1/28.3 | candidate/no_memory |

Paired differences (candidate − baseline), mean with a 95 % interval from resampling whole scenarios:

- task_success: n=12, mean=-0.0833, CI95=(-0.25, 0.0), inconclusive
- repeated_mistakes: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- detours: n=12, mean=0.1667, CI95=(-0.1667, 0.5833), inconclusive
- legitimate_retry_success: n=2, mean=0.0, CI95=(0.0, 0.0), inconclusive
- foreground_tokens: n=12, mean=28789.0, CI95=(10167.3333, 48657.6667)
- background_tokens: n=12, mean=236479.5, CI95=(172505.9167, 301553.8333)
- elapsed_seconds: n=12, mean=6.2366, CI95=(3.1235, 10.0858)
- operator_interventions: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- repeated failures on relevant scenarios: candidate 0, baseline 0, relative reduction None (>= 0.25 (Cut 2 gate; not a preview gate))

No superiority claim: a 12-scenario smoke run with one trial per arm cannot establish one (ACCEPTANCE_TESTS §6.1).

## §5.1 quality on the smoke population

| Measure | Value | Numerator/denominator | Wilson 95 % | Target | Met |
|---|---|---|---|---|---|
| supported_precision | – | 0/0 | None | >= 0.95 | None |
| useful_recall | – | 0/0 | None | >= 0.85 | None |
| failed_approach_recall | – | 0/0 | None | >= 0.9 | None |
| incorrect_confident_guidance | 1 | count over 12 | None | == 0 | False |
| conflict_uncertainty_preservation | 1 | 1/1 | (0.2065, 1.0) | >= 0.95 | True |
| legitimate_retry_discouraged | 0 | 0/2 | (0.0, 0.6576) | <= 0.05 | True |
| irrelevant_caution_quiet | 0 | 0/3 | (0.0, 0.5615) | <= 0.05 | True |
| routine_human_maintenance | 0 | count over 12 | None | == 0 | True |

Support and recall come from reviewer labels (`adjudication.json`); 22 item(s) unlabeled (`evals/run.py adjudicate`). Lessons whose evidence never occurred: 0. fewer than two independent reviewers (ACCEPTANCE_TESTS §5: report the limitation)
Term match (provisional, frozen against the recorded curator's wording): supported_precision 7/14, useful_recall 7/8, failed_approach_recall 2/3

## Curator call outcomes

```json
{
 "smoke": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 24,
    "replies_parsed": 24,
    "reported_input_tokens": 791461,
    "reported_output_tokens": 45918,
    "visible_output_estimate": 13872
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 28,
    "replies_parsed": 28,
    "reported_input_tokens": 970735,
    "reported_output_tokens": 55556,
    "visible_output_estimate": 11333
   },
   "revalidate": {
    "at_output_cap": 0,
    "calls": 4,
    "replies_parsed": 4,
    "reported_input_tokens": 60085,
    "reported_output_tokens": 8009,
    "visible_output_estimate": 1707
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 18,
    "replies_parsed": 18,
    "reported_input_tokens": 142295,
    "reported_output_tokens": 22268,
    "visible_output_estimate": 4640
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 23,
    "replies_parsed": 23,
    "reported_input_tokens": 692238,
    "reported_output_tokens": 49189,
    "visible_output_estimate": 13841
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
    "reported_input_tokens": 617074,
    "reported_output_tokens": 48681,
    "visible_output_estimate": 14582
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 46,
    "replies_parsed": 46,
    "reported_input_tokens": 1268570,
    "reported_output_tokens": 54847,
    "visible_output_estimate": 8058
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 8,
    "replies_parsed": 8,
    "reported_input_tokens": 43753,
    "reported_output_tokens": 7272,
    "visible_output_estimate": 1440
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 23,
    "replies_parsed": 23,
    "reported_input_tokens": 536687,
    "reported_output_tokens": 39820,
    "visible_output_estimate": 11135
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
    "n": 94,
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
   "admitted_claims": 2,
   "calls": 39,
   "calls_by_purpose": {
    "build_episode": 9,
    "extract_claims": 19,
    "review_claims": 2,
    "update_task": 9
   },
   "calls_per_admitted_claim": 19.5,
   "calls_per_settled_episode": 4.333,
   "estimated_tokens_by_purpose": {
    "build_episode": 143786,
    "extract_claims": 362139,
    "review_claims": 7613,
    "update_task": 131753
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 20.495,
     "n": 39,
     "p50": 6.639,
     "p95": 18.487
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
     "decisions": [],
     "no_op_reason": "The narrative fields already fit the evidence. The later run reported OK, but its command (NOTES_HOME=/tmp/notes) differs from the printed value (/tmp/fieldnotes-check), so completion is not clearly shown and no change is warranted yet.",
     "operations": [],
     "purpose": "update_task"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "Existing active claim claim_984a69b2 already records the NOTES_HOME failure and its retry condition. The session had no user declaration, and the passing NOTES_HOME run is already covered by that claim's retry condition, so no new durable claim is warranted.",
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
     "no_op_reason": "Existing active claims already cover the NOTES_HOME failure and the ISO date rule. The remaining signals are task progress and an unresolved test failure whose fix status is unknown, which is not durable knowledge.",
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
     "no_op_reason": "The events add no new durable project knowledge beyond the existing claims. The NOTES_HOME failure is already captured by claim_984a69b2, the ISO date rule by claim_71b8c552, and the passing run that printed a different NOTES_HOME value is ambiguous, so no claim is proposed.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session records a date-format test failure, two edits to fieldnotes/cli.py and a passing run, but no durable project rule, decision, preference or procedure was stated. The existing claims already cover the ISO date format and the NOTES_HOME failure, and this session's evidence does not support either further.",
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
     "no_op_reason": "The session is a task-scoped TDD request with no durable project rule, decision, or preference stated, and the observed failures are already covered by an existing claim.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "This session's events show a failing test run, an Edit to fieldnotes/cli.py, and a passing NOTES_HOME run with unparsed command output. The NOTES_HOME failure lesson is already recorded, and the other events are transient progress rather than durable project knowledge. The only user-stated constraint is cited by an event not in allowed_evidence_refs, so it cannot be cited here.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "This session's events are tool reads, one edit, and one failed Bash run with an unparsed command, with no user statement of a durable rule, decision, or project fact citable from allowed_evidence_refs. The one exit-code result cannot be stated as a durable fact without an exact argv, and the existing NOTES_HOME claims already cover that check.py behavior.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The request's events are tool calls and file reads with no user statement of intent or preference in allowed evidence, and the task objective's source event is not in allowed_evidence_refs. The one failing check run is not a durable project fact.",
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
     "no_op_reason": "The session shows in-progress work on a storage change: one failing test run, one edit and some reads. It contains no user-stated decision, preference or fact about the project, and no settled failure lesson.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The user's statement is a task objective to move storage to notes.jsonl, not a durable project rule, decision or preference. The episode's outcome is unverified, with a roundtrip test still failing, and the existing claims need no change from this session.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "No durable project knowledge in this session: the only user statement, the task objective, is not in allowed_evidence_refs, and the one failing run shows a test failure unrelated to NOTES_HOME. Existing claims gained no new support.",
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
     "no_op_reason": "The session's objective is an in-progress storage change, not a stated project rule, decision or preference. The one failed run concerns an unfinished code change and an inferred cause, and the existing NOTES_HOME claim already covers the setting-related failure. No new durable project fact was established.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "Narrative fields have no supported new content: plan, constraints and open questions are not stated in the events, the objective is already recorded, the task is not complete, and the failed round-trip run is followed by a passing run. The boundary stays pending.",
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
     "no_op_reason": "The durable NOTES_HOME failure lesson for tools/check.py is already recorded as claim_984a69b2, and the Edit and count-command steps are task-specific, so nothing new is durable.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": 
```

## Expected retrieval points (candidate)

10/12 satisfied (Wilson 95 % (0.552, 0.953)). Unmet:

- smoke-L1-ledgerlite-test-command: {"must_include": "PYTHONPATH=src", "purpose": "session_start", "session": "B"} (0 items delivered at that point)
- smoke-R3-household-budget-correction: {"must_not_include": "$600 as current", "purpose": "prompt", "session": "C"} (2 items delivered at that point)

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
       9
      ],
      [
       "tools/check.py reads the NOTES_HOME environment variable and requires it to be set.",
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
         "text": "Fact: tools/check.py reads the NOTES_HOME environment variable and requires it to be set."
        },
        {
         "advice": "context",
         "freshness": "current",
         "text": "Failure lesson: Running `python tools/check.py` without NOTES_HOME set fails with KeyError: 'NOTES_HOME'. Observed: Running `python tools/check.py` without NOTE"
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
       "Running `python -m unittest discover -s tests -t .` from the project root, without tests/__init__.py, fails with ImportError: Start directory is not importable.",
       "candidate",
       "current",
       2
      ],
      [
       "Running `python -m unittest discover -s tests -t .` from the project root, with tests/__init__.py present, reports Ran 2 tests, OK.",
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
         "text": "Fact: Running `python -m unittest discover -s tests -t .` from the project root, with tests/__init__.py present, reports Ran 2 tests, OK."
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
      "command": "cd \"<run>/work/L3/c/w\" && ls && cat groceries.csv 2>/dev/null",
      "exit_code": 0,
      "path": null,
      "tool": "Bash"
     },
     {
      "command": "cd \"<run>/work/L3/c/w\" && awk -F, 'NR>1{s+=$2}END{print s}' groceries.csv",
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
      "command": "cd \"<run>/work/L3/c/w\" && ls && cat groceries.csv 2>/dev/null",
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
    "manifest_digest": "0abc3940f0381f4fe73381951d03f94e7b05ad411eed49ef9b08040086d04f33",
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
    "restored_revision": 114,
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
      "Running `python -m unittest discover -s tests -v` from the ledgerlite project root, without PYTHONPATH=src, fails with ModuleNotFoundError: No module named 'ledgerlite'.",
      "Ledger.close(name) in src/ledgerlite/__init__.py raises ValueError when the account's balance is not zero and otherwise deletes the account from the ledger."
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
      "fieldnotes export prints one line per stored note in the form `<created>: <text>`, where <created> is the stored 
```

## Unsuccessful runs

- {'scenario': 'smoke-R3-household-budget-correction', 'arm': 'candidate', 'reason': 'task_failed'}

## Cost and time

```json
{
 "actual": {
  "background_model_calls": 199,
  "background_tokens": 4479687,
  "elapsed_seconds": 730.4,
  "foreground_cost_usd": 1.7446,
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
  "commit": "614944c2d33f87cb3b670314ba2a45717d90e72a",
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
