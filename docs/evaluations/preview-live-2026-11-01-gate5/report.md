# Preview evaluation report (live)

**live working agent and certified inference route.** Counts toward the preview gate: **True**. Gate: **failed**.

- claims_unadjudicated:26 (evals/run.py adjudicate)

## Paired outcomes (candidate vs clean no-memory baseline)

| Scenario | Success C/B | Repeated mistakes C/B | Detours C/B | Retry C/B | Foreground tok C/B | Background tok C | Elapsed s C/B | Labels C/B |
|---|---|---|---|---|---|---|---|---|
| smoke-C1-ledgerlite-routine-typo | yes/yes | 0/0 | 0/0 | –/– | 125577/123604 | 138427 | 23.4/21.9 | candidate/no_memory |
| smoke-C2-fieldnotes-tdd-expected-red | yes/yes | 0/0 | 0/0 | –/– | 327762/253307 | 378154 | 59.7/56.5 | candidate/no_memory |
| smoke-C3-household-utilities-speculation | yes/yes | 0/0 | 0/0 | –/– | 72841/72131 | 88238 | 28.1/26.8 | candidate/no_memory |
| smoke-C4-cross-project-near-match | yes/yes | 0/0 | 0/0 | –/– | 205127/164941 | 126142 | 33.0/27.4 | candidate/no_memory |
| smoke-L1-ledgerlite-test-command | yes/yes | 0/0 | 0/0 | –/– | 179230/165983 | 326505 | 33.6/28.4 | candidate/no_memory |
| smoke-L2-fieldnotes-iso-dates | yes/yes | 0/0 | 0/0 | –/– | 166280/169907 | 321315 | 35.6/33.3 | candidate/no_memory |
| smoke-L3-household-grocery-budget | no/yes | 0/0 | 1/0 | –/– | 128422/151349 | 167034 | 33.2/44.7 | candidate/no_memory |
| smoke-L4-ledgerlite-resume-refactor | yes/yes | 0/0 | 0/0 | –/– | 235057/163551 | 300796 | 39.7/34.1 | candidate/no_memory |
| smoke-R1-fieldnotes-check-env-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 127701/125065 | 230901 | 26.6/22.4 | candidate/no_memory |
| smoke-R2-ledgerlite-import-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 129150/146828 | 147845 | 23.7/21.6 | candidate/no_memory |
| smoke-R3-household-budget-correction | yes/no | 0/0 | 0/0 | –/– | 56144/74734 | 118528 | 25.8/26.5 | candidate/no_memory |
| smoke-R4-fieldnotes-storage-conflict | yes/yes | 0/0 | 0/0 | –/– | 177590/147366 | 245187 | 33.2/29.7 | candidate/no_memory |

Paired differences (candidate − baseline), mean with a 95 % interval from resampling whole scenarios:

- task_success: n=12, mean=0.0, CI95=(-0.25, 0.25), inconclusive
- repeated_mistakes: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- detours: n=12, mean=0.0833, CI95=(0.0, 0.25), inconclusive
- legitimate_retry_success: n=2, mean=0.0, CI95=(0.0, 0.0), inconclusive
- foreground_tokens: n=12, mean=14342.9167, CI95=(-2457.5833, 32946.3333), inconclusive
- background_tokens: n=12, mean=215756.0, CI95=(163404.5833, 267475.4167)
- elapsed_seconds: n=12, mean=1.8405, CI95=(-0.9417, 3.8408), inconclusive
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

Support and recall come from reviewer labels (`adjudication.json`); 26 item(s) unlabeled (`evals/run.py adjudicate`). Lessons whose evidence never occurred: 0. fewer than two independent reviewers (ACCEPTANCE_TESTS §5: report the limitation)
Term match (provisional, frozen against the recorded curator's wording): supported_precision 7/18, useful_recall 7/8, failed_approach_recall 2/3

## Curator call outcomes

```json
{
 "smoke": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 22,
    "replies_parsed": 22,
    "reported_input_tokens": 697721,
    "reported_output_tokens": 41839,
    "visible_output_estimate": 11989
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 26,
    "replies_parsed": 26,
    "reported_input_tokens": 840168,
    "reported_output_tokens": 57468,
    "visible_output_estimate": 12010
   },
   "revalidate": {
    "at_output_cap": 0,
    "calls": 5,
    "replies_parsed": 5,
    "reported_input_tokens": 68750,
    "reported_output_tokens": 7693,
    "visible_output_estimate": 1489
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 17,
    "replies_parsed": 17,
    "reported_input_tokens": 142231,
    "reported_output_tokens": 25007,
    "visible_output_estimate": 5358
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 23,
    "replies_parsed": 23,
    "reported_input_tokens": 669768,
    "reported_output_tokens": 38427,
    "visible_output_estimate": 10570
   }
  },
  "job_errors": {
   "revalidate:coalesced": 5
  }
 },
 "workload": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 25,
    "replies_parsed": 25,
    "reported_input_tokens": 644667,
    "reported_output_tokens": 50392,
    "visible_output_estimate": 14466
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 48,
    "replies_parsed": 48,
    "reported_input_tokens": 1275419,
    "reported_output_tokens": 56428,
    "visible_output_estimate": 9409
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 6,
    "replies_parsed": 6,
    "reported_input_tokens": 32927,
    "reported_output_tokens": 5639,
    "visible_output_estimate": 1107
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 22,
    "replies_parsed": 22,
    "reported_input_tokens": 524144,
    "reported_output_tokens": 33505,
    "visible_output_estimate": 9950
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
    "p95": 3.0
   },
   "ordinary_review": {
    "max": 1.0,
    "n": 1,
    "p50": 1.0,
    "p95": 1.0
   }
  }
 },
 "curation_throughput": {
  "fieldnotes": {
   "admitted_claims": 1,
   "calls": 39,
   "calls_by_purpose": {
    "build_episode": 9,
    "extract_claims": 20,
    "review_claims": 2,
    "update_task": 8
   },
   "calls_per_admitted_claim": 39.0,
   "calls_per_settled_episode": 4.333,
   "estimated_tokens_by_purpose": {
    "build_episode": 157760,
    "extract_claims": 375143,
    "review_claims": 9234,
    "update_task": 124314
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 26.309,
     "n": 39,
     "p50": 7.171,
     "p95": 21.381
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
       "reason": "review_revise"
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
     "no_op_reason": "The existing failure lesson already covers the NOTES_HOME KeyError, and the later run with NOTES_HOME set exposes no new durable project fact, user declaration, or observed reported result. The user objective is not citable from the allowed evidence refs.",
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
     "no_op_reason": "The session's durable content is already recorded: the ISO-8601 date decision (claim_0b857a66) is active, and the NOTES_HOME failure lesson (claim_291d05af) is already a candidate with its failure evidence. The remaining events are routine edits and a test-file write, and the export test failure's invocation is unparsed, so it is too weak to propose a new claim.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "update_task",
       "outcome": "reject",
       "reason": "invalid_result"
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
     "no_op_reason": "No new durable project knowledge: the NOTES_HOME failure is already recorded as claim_291d05af, the ISO-8601 date rule is already active as claim_0b857a66, and the remaining events are task-specific or lack a user declaration.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "This session has no user-stated project rule, preference, or decision. Its events show an in-progress task edit, a failing check run with exit code 1, and a later passing run, which are transient and not durable project knowledge. The existing claims are not contradicted by these events, so nothing should change.",
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
     "no_op_reason": "The session's durable content is task-specific: the user's TDD objective for one delete INDEX command, test-run results that are already covered by existing claims, and no standing project rule, decision, or preference stated for this project.",
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
     "no_op_reason": "The session's only user-stated objective (a TDD delete INDEX command) is not citable from allowed_evidence_refs, and the tool results show a transient test failure and a passing rerun without a durable lesson. Existing claims already cover the date format and the NOTES_HOME failure.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "Session events show only a failing Bash test run, file reads and one Edit, with no user statement of a rule, decision or preference. The failure's cause is not established by cited evidence, and the existing failure_lesson candidate cites events outside allowed_evidence_refs.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session only read files and made one unexplained Edit with a failing test run. The stated storage objective is not among the allowed evidence refs, and the failure cause is not established, so no durable claim is supported.",
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
     "no_op_reason": "The user's stated objective is cited only by an event that is not in allowed_evidence_refs, so it cannot be recorded. The tool results show only a single failing test run and file edits, with no durable project fact, decision, preference or cited failure lesson that a later session needs.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's only user statement is a task objective ('Move storage to notes.jsonl...') with the work still in progress, not a settled project decision or a statement of current state. The failure results are session-specific, and the existing candidate failure lesson already covers the NOTES_HOME failure.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The events show a session start, a Bash run that exited 1 on an unparsed inline command, and Read/Edit calls on fieldnotes/store.py and cli.py. None of these is a durable user statement, a checkable observed result, or a fact the existing claims lack. The task objective is not cited as a user statement because its evidence event is not in allowed_evidence_refs. The session boundary is left pending",
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
     "operations": [],
     "purpose": "update_task"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "No new durable project knowledge: the existing claims already cover the ISO-8601 date rule and the NOTES_HOME check failure, and the session's remaining results are unassessed one-off test runs or cite no user declaration.",
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
     "no_op_reason": "The session's durable failure (check.py fails without NOTES_HOME) is already captured by existing candidate claim_291d05af, and the passing run adds no new durable rule. The count command's behavior is unverified, and the ISO date decision is already active. The user's objective is task state, not a durable preference.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "update_task",
       "outcome": "reject",
       "reason": "invalid_result"
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
     "no_op_reason": "The failure lesson about NOTES_HOME is already recorded as cla
```

## Expected retrieval points (candidate)

11/12 satisfied (Wilson 95 % (0.6461, 0.9851)). Unmet:

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
       "To run the project checks, set NOTES_HOME to a temporary directory outside the project, then run python tools/check.py.",
       "candidate",
       "current",
       2
      ],
      [
       "Running python tools/check.py with NOTES_HOME unset fails with KeyError: 'NOTES_HOME'.",
       "active",
       "current",
       9
      ],
      [
       "tools/check.py reads the NOTES_HOME environment variable and fails with KeyError when it is unset.",
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
         "text": "Fact: tools/check.py reads the NOTES_HOME environment variable and fails with KeyError when it is unset."
        },
        {
         "advice": "context",
         "freshness": "current",
         "text": "Failure lesson: Running python tools/check.py with NOTES_HOME unset fails with KeyError: 'NOTES_HOME'. Observed: python tools/check.py failed with KeyError: 'NO"
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
     "lesson": [],
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
     "task_success": true
    }
   }
  },
  "forgetting_and_restore": {
   "backup_before": {
    "external_copy": true,
    "manifest_digest": "81f798d60c61fa2050b567a7be9cdd10704514be16acccef7c676c096ac3e5dd",
    "store_hits_before": 15
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
    "restored_revision": 114,
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
    "smoke-L4-ledgerlite-resume-refactor"
   ],
   "not_run": [],
   "note": "one trial per arm: a demonstration that reuse happened, not an estimate of its benefit (a Cut 2 comparison). The gold text may arrive in any packet of session B (L1's session-start point is unmet by design, decision 0013, and its prompt packet carries the lesson)",
   "remember_instruction": false,
   "scenarios": {
    "smoke-L1-ledgerlite-test-command": {
     "admitted": [
      "tests/test_ledger.py defines three unit tests in class LedgerTests: test_transfer_preserves_total, test_rejects_non_positive_amount and test_close_requires_zero_balance.",
      "To run the ledgerlite unit tests, run PYTHONPATH=src python -m unittest discover -s tests -v from the project root; that run's output showed both tests ok.",
      "Ledger.close(name) in src/ledgerlite/__init__.py raises ValueError when the account's balance is not zero, and otherwise deletes the account."
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
      "Every date fieldnotes prints must be ISO-8601 (YYYY-MM-DD...). Locale formats such as 'Jan 2' or '02/01/2026' must never be used.",
      "tools/check.py runs the unittest suite in tests/ and reports failure when any line in fieldnotes/**/*.py is longer than 100 characters.",
      "The fieldnotes list command prints each stored note's created value unchanged, with no date formatting. The add command prints no date.",
      "The fieldnotes export command prints one line per stored note in the form `created: text`, with created printed unchanged. export_lines() in fieldnotes/cli.py builds these lines."
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
      "For household planning, the user keeps the grocery budget under $600 per month and wants anything that would push it over flagged."
     ],
     "baseline_repeated_mistakes": 0,
     "baseline_task_success": true,
     "candidate_repeated_mistakes": 0,
     "candidate_task_success": false,
     "carried_in_session_b": [
      "600"
     ],
     "errors": [],
     "gold_in_session_b": [
      "600"
     ],
     "made_a_difference": false,
     "met": false
    },
    "smoke-L4-ledgerlite-resume-refactor": {
     "admitted": [
      "Running pytest with PYTHONPATH=src printed 'No module named pytest' in the workspace's Python 3.13 environment, so pytest was not available there; running PYTHONPATH=src python -m unittest discover -s tests reported 2 tests passing.",
      "src/ledgerlite/money.py defines parse(value: str | Decimal) -> Decimal, which raises TypeError for values that are neither str nor Decimal, raises ValueError for strings that are not valid decimals, and raises ValueError for non-finite or non-positive amounts."
     ],
     "baseline_repeated_mistakes": 0,
     "baseline_task_success": true,
     "candidate_repeated_mistakes": 0,
     "candidate_task_success": true,
     "carried_in_session_b": [
      "money.parse"
     ],
     "errors": [],
     "gold_in_session_b": [
      "money.parse"
     ],
     "made_a_difference": false,
     "met": true
    }
   }
  },
  "isolation": {
   "cross_project_leak_commands": 0,
   "cross_record_ids": [],
   "c
```

## Unsuccessful runs

- {'scenario': 'smoke-L3-household-grocery-budget', 'arm': 'candidate', 'reason': 'task_failed'}
- {'scenario': 'smoke-R3-household-budget-correction', 'arm': 'no_memory', 'reason': 'task_failed'}

## Cost and time

```json
{
 "actual": {
  "background_model_calls": 194,
  "background_tokens": 4227836,
  "elapsed_seconds": 769.0,
  "foreground_cost_usd": 1.729,
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
  "commit": "4e83f8ff37cabd63ac09c6496f36ae0a13e9ea08",
  "engine": "0.1.0.dev6",
  "installed_host": "2.1.310 (Claude Code)",
  "platform": "Windows 11 AMD64",
  "prompts": {
   "build_episode": "build_episode@1",
   "extract_claims": "extract_claims@4",
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
