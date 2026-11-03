# Preview evaluation report (live)

**live working agent and certified inference route.** Counts toward the preview gate: **True**. Gate: **failed**.

- demonstrations_unmet:forgetting_and_restore
- claims_unadjudicated:22 (evals/run.py adjudicate)

## Paired outcomes (candidate vs clean no-memory baseline)

| Scenario | Success C/B | Repeated mistakes C/B | Detours C/B | Retry C/B | Foreground tok C/B | Background tok C | Elapsed s C/B | Labels C/B |
|---|---|---|---|---|---|---|---|---|
| smoke-C1-ledgerlite-routine-typo | yes/yes | 0/0 | 0/0 | –/– | 127061/123526 | 148589 | 19.6/16.7 | candidate/no_memory |
| smoke-C2-fieldnotes-tdd-expected-red | yes/yes | 0/0 | 0/1 | –/– | 382727/315556 | 337056 | 62.5/56.2 | candidate/no_memory |
| smoke-C3-household-utilities-speculation | yes/yes | 0/0 | 0/0 | –/– | 73492/71798 | 91927 | 25.4/20.8 | candidate/no_memory |
| smoke-C4-cross-project-near-match | yes/yes | 0/0 | 1/0 | –/– | 191180/179394 | 136007 | 28.2/25.0 | candidate/no_memory |
| smoke-L1-ledgerlite-test-command | yes/yes | 0/0 | 0/0 | –/– | 204320/165055 | 334509 | 27.4/21.2 | candidate/no_memory |
| smoke-L2-fieldnotes-iso-dates | yes/yes | 0/0 | 0/0 | –/– | 179412/151972 | 269697 | 31.1/31.2 | candidate/no_memory |
| smoke-L3-household-grocery-budget | no/yes | 0/0 | 1/1 | –/– | 170505/143025 | 204272 | 42.6/27.2 | candidate/no_memory |
| smoke-L4-ledgerlite-resume-refactor | yes/yes | 0/0 | 0/0 | –/– | 220191/184933 | 328480 | 36.8/30.1 | candidate/no_memory |
| smoke-R1-fieldnotes-check-env-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 127546/106304 | 216676 | 21.9/16.6 | candidate/no_memory |
| smoke-R2-ledgerlite-import-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 128849/127438 | 160774 | 21.2/20.4 | candidate/no_memory |
| smoke-R3-household-budget-correction | yes/yes | 0/0 | 0/0 | –/– | 55777/54876 | 93880 | 20.4/17.7 | candidate/no_memory |
| smoke-R4-fieldnotes-storage-conflict | yes/yes | 0/0 | 0/0 | –/– | 202059/149242 | 272434 | 31.3/23.8 | candidate/no_memory |

Paired differences (candidate − baseline), mean with a 95 % interval from resampling whole scenarios:

- task_success: n=12, mean=-0.0833, CI95=(-0.25, 0.0), inconclusive
- repeated_mistakes: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- detours: n=12, mean=0.0, CI95=(-0.25, 0.25), inconclusive
- legitimate_retry_success: n=2, mean=0.0, CI95=(0.0, 0.0), inconclusive
- foreground_tokens: n=12, mean=24166.6667, CI95=(12546.5, 36204.75)
- background_tokens: n=12, mean=216191.75, CI95=(165983.3333, 263733.8333)
- elapsed_seconds: n=12, mean=5.1447, CI95=(3.2358, 7.5763)
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

Support and recall come from reviewer labels (`adjudication.json`); 22 item(s) unlabeled (`evals/run.py adjudicate`). Lessons whose evidence never occurred: 0. fewer than two independent reviewers (ACCEPTANCE_TESTS §5: report the limitation)
Term match (provisional, frozen against the recorded curator's wording): supported_precision 5/14, useful_recall 6/8, failed_approach_recall 2/3

## Curator call outcomes

```json
{
 "smoke": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 21,
    "replies_parsed": 21,
    "reported_input_tokens": 679360,
    "reported_output_tokens": 40335,
    "visible_output_estimate": 11832
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 26,
    "replies_parsed": 26,
    "reported_input_tokens": 880387,
    "reported_output_tokens": 58846,
    "visible_output_estimate": 11409
   },
   "revalidate": {
    "at_output_cap": 0,
    "calls": 4,
    "replies_parsed": 4,
    "reported_input_tokens": 50414,
    "reported_output_tokens": 7633,
    "visible_output_estimate": 1723
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 15,
    "replies_parsed": 15,
    "reported_input_tokens": 120098,
    "reported_output_tokens": 19622,
    "visible_output_estimate": 4441
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 23,
    "replies_parsed": 23,
    "reported_input_tokens": 698843,
    "reported_output_tokens": 38763,
    "visible_output_estimate": 10541
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
    "calls": 24,
    "replies_parsed": 24,
    "reported_input_tokens": 618534,
    "reported_output_tokens": 45649,
    "visible_output_estimate": 13457
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 47,
    "replies_parsed": 47,
    "reported_input_tokens": 1274598,
    "reported_output_tokens": 62752,
    "visible_output_estimate": 9593
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 9,
    "replies_parsed": 9,
    "reported_input_tokens": 47380,
    "reported_output_tokens": 8414,
    "visible_output_estimate": 1573
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 22,
    "replies_parsed": 22,
    "reported_input_tokens": 523410,
    "reported_output_tokens": 36046,
    "visible_output_estimate": 10156
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
    "n": 4,
    "p50": 1.0,
    "p95": 1.0
   }
  }
 },
 "curation_throughput": {
  "fieldnotes": {
   "admitted_claims": 1,
   "calls": 40,
   "calls_by_purpose": {
    "build_episode": 9,
    "extract_claims": 20,
    "review_claims": 3,
    "update_task": 8
   },
   "calls_per_admitted_claim": 40.0,
   "calls_per_settled_episode": 4.444,
   "estimated_tokens_by_purpose": {
    "build_episode": 157979,
    "extract_claims": 370965,
    "review_claims": 11787,
    "update_task": 123773
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 22.116,
     "n": 40,
     "p50": 8.353,
     "p95": 20.114
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
       "outcome": "reject",
       "proposed": {
        "basis": "inferred",
        "cited": [],
        "claim_kind": "failure_lesson",
        "proposition": "Running `python tools/check.py` without NOTES_HOME set fails with KeyError: 'NOTES_HOME'."
       },
       "reason": "inferred_requires_support"
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
     "decisions": [],
     "malformed": [
      {
       "detail": "patches.0:value_error(append adds one item to a list field)",
       "index": 0,
       "local_ref": "update-task-main",
       "reason": "malformed_operation"
      }
     ],
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
       "detail": "patches.1:value_error(append adds one item to a list field); patches.2:value_error(append adds one item to a list field); patches.3:value_error(append adds one item to a list field)",
       "index": 0,
       "local_ref": "update-narrative-1",
       "reason": "malformed_operation"
      }
     ],
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
     "no_op_reason": "Existing candidate claim_0c1f9f54 already records the NOTES_HOME failure. The date-format test failure is not an observed assertion, and the export's completion is unestablished, so no new durable claim is supported.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "malformed": [
      {
       "detail": "patches.1:value_error(append adds one item to a list field)",
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
     "no_op_reason": "The session produced only in-progress work on the export task. The existing KeyError lesson and ISO-8601 decision already cover the durable facts, and the remaining runs are unresolved or not durable.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The events show a failing and a passing run of tools/check.py and an edit, but no user statement of intent, preference, or durable project fact. The existing NOTES_HOME failure claim already covers the recorded failure, so no new claim is warranted.",
     "operations": [],
     "purpose": "extract_claims"
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
     "no_op_reason": "The session's user message is a one-off task request (add a delete INDEX command with TDD), not a stated project rule, decision or preference. Its tool results show a test failure, a passing run and a passing check with NOTES_HOME set, and nothing here adds a new durable project fact. The existing claims already cover the ISO-8601 date rule and the candidate NOTES_HOME failure lesson.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "malformed": [
      {
       "detail": "patches.0:value_error(append adds one item to a list field)",
       "index": 0,
       "local_ref": "append-tdd-constraint",
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
     "no_op_reason": "The session shows a TDD task in progress and a single failing test run, but no user-declared project rule, decision or preference is cited in allowed_evidence_refs, and the only failure result has no exact argv or test-result assertion to support a durable observed fact or lesson.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's recorded tool results show only an unparsed Bash exit 1 with a unittest AssertionError, file reads, and an in-progress Edit of fieldnotes/store.py. None is a durable project fact, decision, or failure lesson with a cited basis, and the task objective's event is not in allowed_evidence_refs.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The events show only reads, one edit, and one failing unparsed Bash run; no new durable fact, decision, preference, or failure lesson is stated or supported by an allowed record. The boundary stays pending.",
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
     "no_op_reason": "The session's events show one failing check run with a test failure, an unparsed command with no exact argv, and file reads and an edit. None states a durable project rule, decision, or preference, and the user's objective cites an event that is not in allowed_evidence_refs. The existing KeyError candidate claim needs no change from these events.",
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
     "no_op_reason": "The only failure evidence is one unparsed Bash exit-1 call, already covered by existing candidate claims, and the user objective cites an event not in allowed_evidence_refs. No new durable claim is supported.",
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
     "no_op_reason": "Existing candidate claims already cover the recorded failures. The passing test runs have no numeric exit code, so they cannot support an observed claim. The objective to move storage to notes.jsonl is a task plan, not a stated project decision or current fact.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "malformed": [
      {
       "detail": "patches.1:value_error(append adds one item to a list field); patches.2:value_error(append adds one item to a list field)",
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
     "decisions": [
      {
       "kind": "revise_episode",
       "outco
```

## Expected retrieval points (candidate)

10/12 satisfied (Wilson 95 % (0.552, 0.953)). Unmet:

- smoke-L2-fieldnotes-iso-dates: {"must_include": "ISO-8601", "purpose": "prompt", "session": "B"} (0 items delivered at that point)
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
       "tools/check.py reads the NOTES_HOME environment variable and uses it as the scratch notes directory.",
       "active",
       "current",
       2
      ],
      [
       "Running `python tools/check.py` without NOTES_HOME set fails with KeyError: 'NOTES_HOME'.",
       "candidate",
       "current",
       6
      ]
     ],
     "retry_point": [
      {
       "delivered": true,
       "items": [
        {
         "advice": "context",
         "freshness": "needs_revalidation",
         "text": "Fact: tools/check.py reads the NOTES_HOME environment variable and uses it as the scratch notes directory."
        },
        {
         "advice": "context",
         "freshness": "current",
         "text": "Failure lesson: Running `python tools/check.py` without NOTES_HOME set fails with KeyError: 'NOTES_HOME'. Observed: `python tools/check.py` exited with code 1."
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
      "revalidate:",
      "revalidate:revise_claim"
     ],
     "task_success": true
    },
    "smoke-R2-ledgerlite-import-fixed": {
     "legitimate_retry_success": true,
     "lesson": [
      [
       "Running `python -m unittest discover -s tests -t .` from the project root, with no PYTHONPATH set, runs 2 tests and reports OK.",
       "candidate",
       "current",
       2
      ],
      [
       "After tests/__init__.py is added to insert src into sys.path, running `python -m unittest discover -s tests -t .` from the project root runs 2 tests and reports OK.",
       "active",
       "current",
       2
      ],
      [
       "The project's tests are run with `python -m unittest discover -s tests -t .`.",
       "candidate",
       "current",
       2
      ],
      [
       "Running `python -m unittest discover -s tests -t .` from the project root, without tests/__init__.py, fails with ImportError: Start directory is not importable.",
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
         "text": "Fact: After tests/__init__.py is added to insert src into sys.path, running `python -m unittest discover -s tests -t .` from the project root runs 2 tests and r"
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
    "manifest_digest": "818c07f31889b68331eaf3c227dbfe7eccc862335df76bba91664ef38fe8207d",
    "store_hits_before": 15
   },
   "delivered_after_forget": true,
   "delivered_after_restore": false,
   "demonstrated": false,
   "forget": {
    "backup_state": "verified",
    "purge_state": "completed",
    "purged_count": 17,
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
    "suppressed_record_count": 17
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
      "Ledger.close(name) in src/ledgerlite/__init__.py raises ValueError when the account balance is non-zero and otherwise removes the account.",
      "Running `python -m unittest discover -s tests -v` from the project root, without PYTHONPATH=src, fails with a ModuleNotFoundError for the ledgerlite package."
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
      "tools/check.py requires the NOTES_HOME environment variable to be set, because it reads os.environ[\"NOTES_HOME\"] directly."
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
      "For the user's household planning, the grocery budget is kept under $600 per month, and anything that would push it over is flagged."
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
      "src/ledgerlite/money.py defines parse(value), which returns a finite, positive Decimal for str or Decimal input, raises TypeError for other types, and raises ValueError for unparseable, non-finite or non-positive values.",
      "Ledger.transfer in src/ledgerlite/__init__.py calls money.parse(amount) to validate the amount and no longer contains its own Decimal conversion and positivity check."
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
     "made_a_di
```

## Unsuccessful runs

- {'scenario': 'smoke-L3-household-grocery-budget', 'arm': 'candidate', 'reason': 'task_failed'}

## Cost and time

```json
{
 "actual": {
  "background_model_calls": 191,
  "background_tokens": 4228235,
  "elapsed_seconds": 675.3,
  "foreground_cost_usd": 1.7406,
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
  "commit": "e5b649fc0d2a032915a02b75d5949497637e8208",
  "engine": "0.1.0.dev8",
  "installed_host": "2.1.310 (Claude Code)",
  "platform": "Windows 11 AMD64",
  "prompts": {
   "build_episode": "build_episode@1",
   "extract_claims": "extract_claims@5",
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
