# Preview evaluation report (live)

**live working agent and certified inference route.** Counts toward the preview gate: **True**. Gate: **failed**.

- demonstrations_unmet:forgetting_and_restore
- claims_unadjudicated:21 (evals/run.py adjudicate)

## Paired outcomes (candidate vs clean no-memory baseline)

| Scenario | Success C/B | Repeated mistakes C/B | Detours C/B | Retry C/B | Foreground tok C/B | Background tok C | Elapsed s C/B | Labels C/B |
|---|---|---|---|---|---|---|---|---|
| smoke-C1-ledgerlite-routine-typo | yes/yes | 0/0 | 0/0 | –/– | 126932/123594 | 149652 | 21.0/17.7 | candidate/no_memory |
| smoke-C2-fieldnotes-tdd-expected-red | no/yes | 0/0 | 0/0 | –/– | 391628/253069 | 383616 | 61.3/50.7 | candidate/no_memory |
| smoke-C3-household-utilities-speculation | yes/yes | 0/0 | 0/0 | –/– | 72974/71619 | 91784 | 23.2/20.5 | candidate/no_memory |
| smoke-C4-cross-project-near-match | yes/yes | 0/0 | 1/1 | –/– | 212149/178497 | 133083 | 32.6/20.3 | candidate/no_memory |
| smoke-L1-ledgerlite-test-command | yes/yes | 0/0 | 0/0 | –/– | 204489/166112 | 315994 | 32.7/23.0 | candidate/no_memory |
| smoke-L2-fieldnotes-iso-dates | yes/yes | 0/0 | 0/0 | –/– | 195252/151264 | 307165 | 31.4/28.2 | candidate/no_memory |
| smoke-L3-household-grocery-budget | yes/yes | 0/0 | 0/1 | –/– | 148098/126474 | 170372 | 42.7/30.5 | candidate/no_memory |
| smoke-L4-ledgerlite-resume-refactor | yes/yes | 0/0 | 0/0 | –/– | 227517/183210 | 266267 | 33.3/34.5 | candidate/no_memory |
| smoke-R1-fieldnotes-check-env-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 128265/125027 | 235002 | 20.6/18.0 | candidate/no_memory |
| smoke-R2-ledgerlite-import-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 130036/147276 | 150610 | 23.8/19.9 | candidate/no_memory |
| smoke-R3-household-budget-correction | yes/yes | 0/0 | 0/0 | –/– | 55594/53965 | 120934 | 18.2/16.9 | candidate/no_memory |
| smoke-R4-fieldnotes-storage-conflict | yes/yes | 0/0 | 0/0 | –/– | 177939/148908 | 264110 | 29.5/24.3 | candidate/no_memory |

Paired differences (candidate − baseline), mean with a 95 % interval from resampling whole scenarios:

- task_success: n=12, mean=-0.0833, CI95=(-0.25, 0.0), inconclusive
- repeated_mistakes: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- detours: n=12, mean=-0.0833, CI95=(-0.25, 0.0), inconclusive
- legitimate_retry_success: n=2, mean=0.0, CI95=(0.0, 0.0), inconclusive
- foreground_tokens: n=12, mean=28488.1667, CI95=(10277.5833, 52313.9167)
- background_tokens: n=12, mean=215715.75, CI95=(166383.0, 265175.3333)
- elapsed_seconds: n=12, mean=5.4854, CI95=(3.047, 7.9261)
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

Support and recall come from reviewer labels (`adjudication.json`); 21 item(s) unlabeled (`evals/run.py adjudicate`). Lessons whose evidence never occurred: 0. fewer than two independent reviewers (ACCEPTANCE_TESTS §5: report the limitation)
Term match (provisional, frozen against the recorded curator's wording): supported_precision 6/13, useful_recall 5/8, failed_approach_recall 2/3

## Curator call outcomes

```json
{
 "smoke": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 21,
    "replies_parsed": 21,
    "reported_input_tokens": 675145,
    "reported_output_tokens": 40324,
    "visible_output_estimate": 11096
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 26,
    "replies_parsed": 26,
    "reported_input_tokens": 855299,
    "reported_output_tokens": 50019,
    "visible_output_estimate": 9821
   },
   "revalidate": {
    "at_output_cap": 0,
    "calls": 5,
    "replies_parsed": 5,
    "reported_input_tokens": 82267,
    "reported_output_tokens": 6981,
    "visible_output_estimate": 1661
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 14,
    "replies_parsed": 14,
    "reported_input_tokens": 103849,
    "reported_output_tokens": 15889,
    "visible_output_estimate": 3131
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 24,
    "replies_parsed": 24,
    "reported_input_tokens": 713425,
    "reported_output_tokens": 45391,
    "visible_output_estimate": 12738
   }
  },
  "job_errors": {
   "revalidate:coalesced": 3,
   "revalidate:reevaluation_requeued": 1
  }
 },
 "workload": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 24,
    "replies_parsed": 24,
    "reported_input_tokens": 620748,
    "reported_output_tokens": 49855,
    "visible_output_estimate": 13354
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 46,
    "replies_parsed": 46,
    "reported_input_tokens": 1277198,
    "reported_output_tokens": 54387,
    "visible_output_estimate": 8381
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 10,
    "replies_parsed": 10,
    "reported_input_tokens": 59706,
    "reported_output_tokens": 10197,
    "visible_output_estimate": 2106
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 23,
    "replies_parsed": 23,
    "reported_input_tokens": 541922,
    "reported_output_tokens": 34891,
    "visible_output_estimate": 9123
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
    "n": 5,
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
    "build_episode": 9,
    "extract_claims": 19,
    "review_claims": 4,
    "update_task": 8
   },
   "calls_per_admitted_claim": 20.0,
   "calls_per_settled_episode": 4.444,
   "estimated_tokens_by_purpose": {
    "build_episode": 158461,
    "extract_claims": 361710,
    "review_claims": 20154,
    "update_task": 123268
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 23.551,
     "n": 40,
     "p50": 6.601,
     "p95": 20.73
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
       "reason": "review_revise"
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
     "no_op_reason": "The session's failure and passing run are already captured by existing claims, and the passing run's output is not a typed observed result, so no new durable claim is warranted.",
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
     "no_op_reason": "Durable items are already recorded: the NOTES_HOME failure lesson, the ISO-8601 date decision, and a candidate passing-run fact. The date-format failure and the 3-test versus 1-test run difference are not shown clearly enough to state as a project fact.",
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
     "no_op_reason": "No new durable knowledge beyond existing claims. The NOTES_HOME failure and the passing NOTES_HOME run are already covered by active or candidate claims. The export test failure is in-progress task work, and the user's text is a task objective, not a stated rule or decision.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's events show an in-progress export task and test runs. The user made no explicit durable statement, and the claims already in the read set cover the project's date format and the check.py behavior. Nothing new is durable enough to propose.",
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
     "no_op_reason": "Session only contains a task-level TDD request and tool runs with no new durable project statement; existing claims already cover the printed-date rule and the NOTES_HOME check results.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "Title already matches the user objective; the recorded actions do not establish a clear plan, constraints, open questions, or next action, and completion is not supported by the evidence.",
     "operations": [],
     "purpose": "update_task"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's durable content is already captured by existing claims (ISO date format, the NOTES_HOME failure lesson and passing-form fact). The user's TDD objective is task-scoped and not a standing project rule, and the edit and test-run events add no new durable project knowledge.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "No new durable project knowledge: the session's only user statement is the task objective, which is not in allowed_evidence_refs, and the tool results are a transient test failure and unrelated reads and edits. The existing claims already cover the ISO date rule and the NOTES_HOME failure.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
      {
       "kind": "attach_evidence",
       "outcome": "apply",
       "reason": "admitted"
      }
     ],
     "operations": [
      "attach_evidence"
     ],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "operations": [],
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
     "decisions": [
      {
       "kind": "attach_evidence",
       "outcome": "apply",
       "reason": "admitted"
      }
     ],
     "operations": [
      "attach_evidence"
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
       "reason": "review_rejected"
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
     "no_op_reason": "The session's durable-looking items are a task objective (moving storage to notes.jsonl, not yet confirmed complete) and repeated test_roundtrip failures whose cause is unassessed. Neither is a settled project fact, decision or preference, and the existing NOTES_HOME failure lesson already covers the one established failure condition.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's events show only a failing check run with a test failure, file reads, and one edit to fieldnotes/store.py. No user declaration of a durable project rule, decision, or preference appears in the events, and the failure does not add a lesson beyond existing claims.",
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
     "no_op_reason": "The session's durable candidates are already recorded (ISO-8601 date decision, NOTES_HOME failure lesson). The user's storage objective is an unfinished task goal rather than a stated project fact, and the single test_roundtrip failure has no established cause, so no new claim is warranted. The new-session boundary stays pending.",
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
     "no_op_reason": "Narrative fields are already consistent with the evidence; the title matches the user objective, and the events do not establish a next action, plan, constraints, or open questions. The boundary binding stays pending.",
     "operations": [],
     "purpose": "update_task"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's durable failure lesson about tools/check.py and NOTES_HOME is already recorded as an active supported claim, and the request contains no new user declaration of a rule, decision, or preference. The later passing run has no assertion-level tool result, so it does not support a new observed or durable claim.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [
```

## Expected retrieval points (candidate)

9/12 satisfied (Wilson 95 % (0.4677, 0.9111)). Unmet:

- smoke-L2-fieldnotes-iso-dates: {"must_include": "ISO-8601", "purpose": "prompt", "session": "B"} (0 items delivered at that point)
- smoke-L3-household-grocery-budget: {"must_include": "600", "purpose": "prompt", "session": "B"} (0 items delivered at that point)
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
       "tools/check.py reads the NOTES_HOME environment variable at line 24 and raises KeyError when it is unset.",
       "active",
       "current",
       5
      ],
      [
       "Running `python tools/check.py` without NOTES_HOME set fails with KeyError: 'NOTES_HOME'.",
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
         "freshness": "needs_revalidation",
         "text": "Fact: tools/check.py reads the NOTES_HOME environment variable at line 24 and raises KeyError when it is unset."
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
   "demonstrated": false,
   "reason": "the live curator admitted no claim naming the $600 limit",
   "route": "the guarded CLI with the operator token (live)",
   "scenario": "smoke-L3-household-grocery-budget",
   "trial_error": null
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
      "Running `.recalith/runtime/0.1.0.dev7/venv/Scripts/python.exe -m unittest discover -s tests -v` from the project root with PYTHONPATH=src ran 2 tests and reported OK in the run recorded at 2026-11-02T22:50:42Z, before tests/test_ledger.py was edited to add a third test.",
      "Running `.recalith/runtime/0.1.0.dev7/venv/Scripts/python.exe -m unittest discover -s tests -v` from the project root, without PYTHONPATH=src, fails with \"ModuleNotFoundError: No module named 'ledgerlite'\".",
      "Ledger.close(name) in src/ledgerlite/__init__.py deletes the named account when its balance is zero and raises ValueError when the balance is not zero."
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
      "fieldnotes stores its notes as a JSON array in notes.json inside the directory named by the NOTES_HOME environment variable.",
      "The project check script tools/check.py reads the NOTES_HOME environment variable with os.environ, so NOTES_HOME must be set when it runs; it also runs the unittest suite under tests/ and enforces a 100-character line limit on fieldnotes/**/*.py."
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
     "admitted": [],
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
      "src/ledgerlite/money.py defines parse(value), which raises TypeError for values that are neither str nor Decimal and raises ValueError for amounts that are not finite or are not positive.",
      "The ledgerlite refactor is planned in three steps: (1) add src/ledgerlite/money.py with parse(value) -> Decimal accepting str or Decimal and rejecting non-positive values; (2) make Ledger.transfer use money.parse; (3) add tests/test_money.py."
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
   "cross_text_in_search": [],
   "demonstrated": true,
   "fieldnotes_active_claims": [
    "Running `python tools/check.py` from the project root, without NOTES_HOME set, fails with KeyError: 'NOTES_HOME'.",
    "Running `python tools/check.py` with NOTES_HOME set to a temporary directory ran 1 unit test (OK) and exited 0.",
    "tools/check.py reads the NOTES_HOME environment variable with os.environ[\"NOTES_HOME\"] and has no default, so it raises KeyError when NOTES_HOME is unset."
   ],
   "fieldnotes_session_b_delivered": [],
   "installations": {
    "distinct": true,
    "fieldnotes": "inst_504321c7-e748-49ba-99e9-f9eb71cec39d",
    "ledgerlite": "inst_04569b68-8f06-4765-8e5a-bef42397a2ae"
   },
   "ledgerlite_active_claims": [
    "Running `PYTHONPATH=src python -m unittest discover -s tests -v` from the project root runs the two ledgerlite unit tests and reports both passing.",
    "Running `PYTHONPATH=src python -m pytest tests -q` from the project root fails in the Windows Python 3.13 environment because the pytest module is not installed."
   ],
   "reverse_session": {
    "actions": 3,
    "gap": {
     "last": {
      "due_jobs": 0,
      "due_kinds": [],
      "leased": 0,
      "next_due_in_s": null,
      "pending_triggers": 0,
      "progress": [
       44,
       32,
       40
      ],
      "quiet": true,
      "spool_ready": 0,
      "waiting_reasons": []
     },
     "polls": 21,
     "state": "quiet",
     "suspended_s": 0.0,
     "waited_s": 422.0,
     "worker_seen": true
    }
   },
   "scenario": "smoke-C4-cross-project-near-ma
```

## Unsuccessful runs

- {'scenario': 'smoke-C2-fieldnotes-tdd-expected-red', 'arm': 'candidate', 'reason': 'task_failed'}

## Cost and time

```json
{
 "actual": {
  "background_model_calls": 193,
  "background_tokens": 4239913,
  "elapsed_seconds": 674.8,
  "foreground_cost_usd": 1.7327,
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
  "commit": "3a0fc06590963ae0ae28a6072c2a9ce96739e82f",
  "engine": "0.1.0.dev7",
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
