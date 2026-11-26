# Decision 0052: A review sees what a lesson's own text cites

Status: accepted (Task 9 review, preview) · Date: 2026-11-26 · Engine: `0.1.0.dev19` · Observed: the thirteenth live gate's R1 (2026-11-22, [record](../evaluations/preview-live-2026-11-22-gate13/report.md))

## Context

The thirteenth live gate failed on two demonstrations, the changed-condition revision and isolation, and on 21 unlabeled claims. Every measure that needs no labels was met. Isolation failed because the machine slept during its wait (decision 0028 item 34). The revision demonstration failed on R1 as follows.

1. In session A, `python tools/check.py` failed with `KeyError: 'NOTES_HOME'`. The agent read the script, set `NOTES_HOME` to a temporary directory, and the check passed.
2. The extraction proposed a failure lesson. Its support was the failed run. Its retry condition, "set NOTES_HOME to a writable directory", cited the passing run, which is no support for a failure, so that run was in the retry condition's own evidence and not among the claim's support links.
3. The review batch held only support and contradiction links (`review.snapshot`), so the reviewer never saw the passing run. It returned `revise`: "Retry text requires a writable directory; batch evidence shows only the KeyError, not writability" and "Retry evidence evt_… is not in this batch's evidence index." The lesson stayed a weak candidate.
4. In session C, after the overlay changed the script, the plain run succeeded. That certified success would have marked an active lesson `later_success` and queued its revalidation. On a candidate it is deferred until activation (decision 0012), so no revalidation ran.
5. The demonstration needs a legitimate retry and a revalidation in R1 or R2. R2's candidate retried plainly, but its oracle misread the command (decision 0028 item 34), and neither of its lessons was active. So the demonstration failed. It had passed in every gate since 2026-10-31, each time through R1's active lesson.

The review prompt asks the reviewer to object when a failure lesson is "missing the condition under which a retry could succeed", and to judge each candidate "against its own batch evidence". The batch left out the evidence for that condition. A procedure's steps cite evidence the same way, and so do the counter-observations a revised lesson carries (`context`, decision 0012).

## Decisions

1. **A review batch carries what each candidate's record cites.** The evidence index holds:
   - the candidate's support and contradiction links, as before;
   - then, as `context`, its counter-observations and the evidence behind each supported text of its body, unless that record is already one of its support or contradiction links. For a failure lesson that is the observed failure, consequence, alternative and retry conditions. For a procedure it is the preconditions, steps, expected outcomes and stop conditions.
   - Their events are loaded into the request like any batch evidence and never trimmed. Partitions are sized from the same snapshot, so a batch that no longer fits is split or deferred as before.
2. **Context never stands in for support.**
   - A reviewer may cite a context id among its two evidence ids.
   - A `supported` verdict still has to cite a support link, and every activation gate is unchanged.
   - The claim's own links are unchanged: a success is still no support for a failure.
3. **Unchanged: the prompt, contracts and store.**
   - `review_claims@2` already tells the reviewer that a supported verdict cites a supporting link, and each index entry carries its relation.
   - No prompt digest, contract field, schema or migration changes. A batch persisted before the upgrade is reused only while it equals a fresh snapshot (the existing rule); otherwise a fresh one is made.
4. **Engine `0.1.0.dev19`.** It carries this change. The harness changes found by the same gate are decision 0028 item 34.

## Specification

DATA_CONTRACTS §6.2's `ReviewBatch` paragraph now says what the evidence index holds. SYSTEM_SPEC is unchanged: §7.2 already asks the reviewer to judge a missing retry condition, and this decision gives the reviewer that condition's evidence.

## Found, not changed

- **An edit outside any captured tool is only seen at delivery.**
  - R1's admitted fact ("tools/check.py reads NOTES_HOME with `os.environ["NOTES_HOME"]` at line 25") was delivered in session C labeled `needs_revalidation`, because the live dependency check compared the changed bytes.
  - It was never revalidated. The overlay is an outside edit, and session C ran the script without reading it, so the store never observed the change. The October build log records this limit: file changes outside captured tools are not observed as dependency changes, and the live check at delivery still compares the current bytes.
  - Recording the hook's own check as an observation would mean writing on the hook path, which never writes the store. It would also make a file observation that comes from no certified read (decision 0033). So the delivery label remains the guarantee in the preview.
- **R2's two lessons were returned `revise`.** The cited runs do not show whether `tests/__init__.py` existed at the time. The reviewer judged evidence the batch did hold, so nothing changes.
- **L3's candidate wrote a grocery list that does not parse**, judged a failed check (decision 0028 item 24). It is a task outcome.

## Tests

- `test_a_lessons_retry_evidence_is_in_its_review_batch_as_context` reproduces R1. A failure lesson's retry condition cites a later success that is not one of its support links.
  - **Before the fix:** the batch has no context entry.
  - **Now:**
    - the success is in the index as `context`, and in the request's events and allowed references;
    - a `supported` verdict that cites only that entry is refused (`supported_requires_support_evidence`);
    - a verdict that cites the support link as well is admitted;
    - the lesson's support links are unchanged.
