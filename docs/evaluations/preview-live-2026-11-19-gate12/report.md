# Preview evaluation report (live)

**live working agent and certified inference route.** Counts toward the preview gate: **True**. Gate: **failed**.

- quality_targets_unmet:conflict_uncertainty_preservation
- contaminated_arms:smoke-R4-fieldnotes-storage-conflict.candidate
- claims_unadjudicated:20 (evals/run.py adjudicate)

## Paired outcomes (candidate vs clean no-memory baseline)

| Scenario | Success C/B | Repeated mistakes C/B | Detours C/B | Retry C/B | Foreground tok C/B | Background tok C | Elapsed s C/B | Labels C/B |
|---|---|---|---|---|---|---|---|---|
| smoke-C1-ledgerlite-routine-typo | yes/yes | 0/0 | 0/0 | –/– | 124073/123421 | 140880 | 15.9/13.1 | candidate/no_memory |
| smoke-C2-fieldnotes-tdd-expected-red | yes/yes | 0/0 | 0/0 | –/– | 328798/251907 | 273191 | 49.0/42.9 | candidate/no_memory |
| smoke-C3-household-utilities-speculation | yes/yes | 0/0 | 0/0 | –/– | 73903/72153 | 95749 | 24.0/23.7 | candidate/no_memory |
| smoke-C4-cross-project-near-match | yes/yes | 0/0 | 0/1 | –/– | 204719/179521 | 95952 | 32.8/20.9 | candidate/no_memory |
| smoke-L1-ledgerlite-test-command | yes/yes | 0/0 | 0/0 | –/– | 174159/164232 | 274113 | 26.0/20.6 | candidate/no_memory |
| smoke-L2-fieldnotes-iso-dates | yes/yes | 0/0 | 0/0 | –/– | 218292/171163 | 338929 | 35.7/24.3 | candidate/no_memory |
| smoke-L3-household-grocery-budget | yes/yes | 0/0 | 0/1 | –/– | 259977/162371 | 228820 | 39.9/25.1 | candidate/no_memory |
| smoke-L4-ledgerlite-resume-refactor | yes/yes | 0/0 | 0/0 | –/– | 225429/166252 | 231697 | 33.9/25.3 | candidate/no_memory |
| smoke-R1-fieldnotes-check-env-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 108639/106579 | 189528 | 17.6/14.7 | candidate/no_memory |
| smoke-R2-ledgerlite-import-fixed | yes/yes | 0/0 | 0/0 | yes/yes | 128619/127250 | 155788 | 23.4/16.4 | candidate/no_memory |
| smoke-R3-household-budget-correction | yes/yes | 0/0 | 0/1 | –/– | 56808/109657 | 110340 | 20.3/18.6 | candidate/no_memory |
| smoke-R4-fieldnotes-storage-conflict | yes/yes | 0/0 | 0/0 | –/– | 214403/168166 | 323339 | 34.4/25.5 | contaminated/no_memory |

Paired differences (candidate − baseline), mean with a 95 % interval from resampling whole scenarios:

- task_success: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- repeated_mistakes: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- detours: n=12, mean=-0.25, CI95=(-0.5, 0.0), inconclusive
- legitimate_retry_success: n=2, mean=0.0, CI95=(0.0, 0.0), inconclusive
- foreground_tokens: n=12, mean=26262.25, CI95=(4307.0, 48350.25)
- background_tokens: n=12, mean=204860.5, CI95=(158118.1667, 250099.4167)
- elapsed_seconds: n=12, mean=6.8218, CI95=(4.4332, 9.3492)
- operator_interventions: n=12, mean=0.0, CI95=(0.0, 0.0), inconclusive
- repeated failures on relevant scenarios: candidate 0, baseline 0, relative reduction None (>= 0.25 (Cut 2 gate; not a preview gate))

No superiority claim: a 12-scenario smoke run with one trial per arm cannot establish one (ACCEPTANCE_TESTS §6.1).

## Baseline-sensitivity set (decision 0049; not part of the gate)

| Scenario | Success C/B | Repeated named mistake C/B | Repeated mistakes C/B | Foreground tok C/B | Errors |
|---|---|---|---|---|---|
| sens-S1-ledgerlite-amounts-in-cents | yes/no | 0/1 | 0/0 | 235293/191018 |  |
| sens-S2-household-no-prices-in-meal-plan | yes/no | 0/1 | 0/0 | 193248/230011 |  |
| sens-S3-fieldnotes-checks-one-job | no/no | 1/1 | 0/0 | 301500/269141 |  |
| sens-S4-fieldnotes-frozen-notes-format | yes/no | 0/1 | 0/0 | 321217/222167 |  |

Repeated named mistakes over 4 pair(s): candidate 1, baseline 4, relative reduction 0.75; task success candidate 3, baseline 0.

Not part of the preview gate (ACCEPTANCE_TESTS §6.1 fixes it at the frozen 12). Four scenarios, one trial per arm, written by the coding agent: this shows whether the corpus can register a repeated mistake, not that memory helps; no superiority claim.

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

Support and recall come from reviewer labels (`adjudication.json`); 20 item(s) unlabeled (`evals/run.py adjudicate`). Lessons whose evidence never occurred: 0. fewer than two independent reviewers (ACCEPTANCE_TESTS §5: report the limitation)
Term match (provisional, frozen against the recorded curator's wording): supported_precision 7/12, useful_recall 7/8, failed_approach_recall 2/3

## Curator call outcomes

```json
{
 "smoke": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 22,
    "replies_parsed": 22,
    "reported_input_tokens": 673860,
    "reported_output_tokens": 41711,
    "visible_output_estimate": 11947
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 26,
    "replies_parsed": 26,
    "reported_input_tokens": 848397,
    "reported_output_tokens": 39992,
    "visible_output_estimate": 7403
   },
   "revalidate": {
    "at_output_cap": 0,
    "calls": 3,
    "replies_parsed": 3,
    "reported_input_tokens": 40646,
    "reported_output_tokens": 3017,
    "visible_output_estimate": 537
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 11,
    "replies_parsed": 11,
    "reported_input_tokens": 77277,
    "reported_output_tokens": 13106,
    "visible_output_estimate": 2692
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 23,
    "replies_parsed": 23,
    "reported_input_tokens": 672997,
    "reported_output_tokens": 47323,
    "visible_output_estimate": 13483
   }
  },
  "job_errors": {
   "revalidate:coalesced": 2
  }
 },
 "workload": {
  "by_purpose": {
   "build_episode": {
    "at_output_cap": 0,
    "calls": 25,
    "replies_parsed": 25,
    "reported_input_tokens": 676868,
    "reported_output_tokens": 51280,
    "visible_output_estimate": 14747
   },
   "extract_claims": {
    "at_output_cap": 0,
    "calls": 46,
    "replies_parsed": 46,
    "reported_input_tokens": 1291125,
    "reported_output_tokens": 48879,
    "visible_output_estimate": 7202
   },
   "review_claims": {
    "at_output_cap": 0,
    "calls": 7,
    "replies_parsed": 7,
    "reported_input_tokens": 38786,
    "reported_output_tokens": 6544,
    "visible_output_estimate": 1312
   },
   "update_task": {
    "at_output_cap": 0,
    "calls": 22,
    "replies_parsed": 22,
    "reported_input_tokens": 504895,
    "reported_output_tokens": 45363,
    "visible_output_estimate": 13555
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
    "n": 4,
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
   "admitted_claims": 2,
   "calls": 38,
   "calls_by_purpose": {
    "build_episode": 9,
    "extract_claims": 19,
    "review_claims": 2,
    "update_task": 8
   },
   "calls_per_admitted_claim": 19.0,
   "calls_per_settled_episode": 4.222,
   "estimated_tokens_by_purpose": {
    "build_episode": 160347,
    "extract_claims": 366260,
    "review_claims": 7837,
    "update_task": 113097
   },
   "processing": {
    "note": "real provider call durations; queue wait is on the virtual clock",
    "real_seconds": {
     "max": 20.781,
     "n": 38,
     "p50": 6.567,
     "p95": 19.808
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
     "decisions": [],
     "no_op_reason": "The failure without NOTES_HOME is already recorded by existing claim revision 2, and the passing run's output conflicts with its launch setting, so no new durable claim is supported.",
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
     "decisions": [
      {
       "kind": "update_task",
       "outcome": "apply",
       "reason": "admitted"
      },
      {
       "kind": "update_task",
       "outcome": "apply",
       "reason": "admitted"
      }
     ],
     "operations": [
      "update_task",
      "update_task"
     ],
     "purpose": "update_task"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The NOTES_HOME failure and the ISO-8601 date decision are already recorded as active claims. The remaining export date-format issue is an unconfirmed inferred cause and is not yet durable project knowledge.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's durable facts are already covered by active claims: the NOTES_HOME failure lesson (claim_96158384) and the ISO-8601 printed-dates decision (claim_4128fe65). The test_export date-format failure is an unconfirmed open question, and the later NOTES_HOME=/tmp/notes runs add no new durable project fact. The new-session boundary stays pending.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's events show only a failing unit test with NOTES_HOME set, a successful edit and a passing rerun. None of it states a durable project fact, decision, preference or procedure that is not already recorded, and the test failure's cause is unconfirmed. The boundary stays pending.",
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
     "no_op_reason": "The session's only user statement is a task-scoped TDD instruction for one command, not a stated project-level rule. The check results and the cli.py stub replacement are session-specific, and the check's own output names a different NOTES_HOME path than the command ran with, so no durable project claim is well supported.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's only user statements of intent are in the task objective and TDD constraint, which cite an event not in allowed_evidence_refs. The tool results show a test failure and an edit, with no durable project fact, decision or preference that a later session needs. The existing KeyError lesson is not contradicted here, since NOTES_HOME was set.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's events are an in-progress edit and test run with no user declaration, decision, or durable project fact in the cited evidence; the one failing test run is transient and the existing claims already cover the stored facts.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's events are reads, one edit, and one failed test run with no user statement of intent or preference citable from allowed_evidence_refs, so nothing durable is proposed.",
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
     "no_op_reason": "The session only reads files, makes one failing test run with an unparsed command, and edits one file in progress; none of it is durable project knowledge, and the task objective cites an event not in allowed_evidence_refs.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's only user statement is the task objective, which is not a stated rule, decision or preference for this project. The failing test run is still unresolved and its cause is inferred, and the existing claims already cover the printed-date format and the NOTES_HOME failure.",
     "operations": [],
     "purpose": "extract_claims"
    },
    {
     "applied": true,
     "body_retained": true,
     "decisions": [],
     "no_op_reason": "The session's events are an in-progress storage task: one failing test run with an ambiguous command, file reads, and an edit. None of it states a durable project fact, decision, preference or procedure. The user's objective is not among the citable evidence records, and the NOTES_HOME failure is already recorded as a claim.",
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
     "no_op_reason": "The episode's durable-looking content is either already covered by existing claims (the ISO-8601 date decision and the NOTES_HOME failure lesson), or too weak to propose: the storage move is a task objective rather than a stated project rule, and the test_roundtrip failure has only an inferred cause and no recorded resolution.",
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
     "no_op_reason": "The session's durable failure (python tools/check.py failing without NOTES_HOME) is already captured by active claim_96158384. The count-command objective is unverified, an
```

## Expected retrieval points (candidate)

9/12 satisfied (Wilson 95 % (0.4677, 0.9111)). Unmet:

- smoke-L1-ledgerlite-test-command: {"must_include": "PYTHONPATH=src", "purpose": "session_start", "session": "B"} (0 items delivered at that point)
- smoke-R3-household-budget-correction: {"must_not_include": "$600 as current", "purpose": "prompt", "session": "C"} (1 items delivered at that point)
- smoke-R4-fieldnotes-storage-conflict: {"advice": "conflict_or_freshness_label", "purpose": "prompt", "session": "C"} (1 items delivered at that point)

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
       "Running `python tools/check.py` without NOTES_HOME set fails with KeyError: 'NOTES_HOME' at tools/check.py line 25.",
       "active",
       "current",
       5
      ],
      [
       "tools/check.py reads NOTES_HOME from the environment with os.environ[\"NOTES_HOME\"] at line 25 and uses it as the directory for scratch notes.",
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
         "freshness": "needs_revalidation",
         "text": "Failure lesson: Running `python tools/check.py` without NOTES_HOME set fails with KeyError: 'NOTES_HOME' at tools/check.py line 25. Observed: `python tools/chec"
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
       "Running `python -m unittest discover -s tests -t .` from the project root, with tests/__init__.py present and inserting src/ onto sys.path, ran 2 tests with OK.",
       "active",
       "current",
       2
      ],
      [
       "Running `python -m unittest discover -s tests -t .` from the project root, with tests/__init__.py present but no src/ directory on the import path, fails with \"ModuleNotFoundError: No module named 'ledgerlite'\".",
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
         "text": "Fact: Running `python -m unittest discover -s tests -t .` from the project root, with tests/__init__.py present and inserting src/ onto sys.path, ran 2 tests wi"
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
      "command": null,
      "exit_code": null,
      "path": "<run>\\work\\L3\\c\\w\\utilities-log.csv",
      "tool": "Read"
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
      "path": "<run>\\work\\L3\\c\\w\\groceries.csv",
      "tool": "Read"
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
      "command": "cd \"<run>/work/L3/c/w\" && ls && cat groceries.csv 2>&1 | head -100",
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
    "manifest_digest": "2384cf0394d8b71b561eb566dda2c272ea936592a438cd9b4271e1c8cc1c1da8",
    "store_hits_before": 12
   },
   "delivered_after_forget": false,
   "delivered_after_restore": false,
   "demonstrated": true,
   "forget": {
    "backup_state": "verified",
    "purge_state": "completed",
    "purged_count": 46,
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
    "restored_revision": 162,
    "source_contains_suppressed": true,
    "suppressed_record_count": 46
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
      "Running `PYTHONPATH=src python -m unittest discover -s tests -v` from the project root ran 2 tests in tests/test_ledger.py and reported them passing (Ran 2 tests, OK)."
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
      "`tools/check.py` reads `NOTES_HOME` from the environment and requires it to be set.",
      "`fieldnotes export` prints each note as its stored `created` value, then `: `, then the note's `text`.",
      "`fieldnotes list` prints each note's stored `created`
```

## Unsuccessful runs


## Cost and time

```json
{
 "actual": {
  "background_model_calls": 185,
  "background_tokens": 4131133,
  "elapsed_seconds": 624.0,
  "foreground_cost_usd": 1.7237,
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
  "commit": "23cdff43edaa301f330b5c1769f3aec067c8c3f4",
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
