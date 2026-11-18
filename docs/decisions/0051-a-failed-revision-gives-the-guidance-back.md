# Decision 0051: A failed revision gives the guidance back

Status: accepted (Task 10 revalidation, preview) · Date: 2026-11-18 · Engine: `0.1.0.dev18` · Observed: the eleventh live gate's L1 (2026-11-14, [record](../evaluations/preview-live-2026-11-14-gate11/report.md)) and the ninth gate's R1 (2026-11-04, [record](../evaluations/preview-live-2026-11-04/report.md))

## Context

The eleventh live gate failed on useful recall, 5/6, by the owner's label on L1 #0.

1. Session A ran the ledgerlite tests with `PYTHONPATH=src … -m unittest discover -s tests -v`. The extraction admitted it as a fact with file dependencies on `tests/test_ledger.py` and `src/ledgerlite/__init__.py`.
2. The fact was delivered at session B's prompt, and B used the command on the first try.
3. B's task was to add `close()` and two tests, so B edited both dependency files. That marked the fact `needs_revalidation`, as SYSTEM_SPEC §7.3 requires.
4. Revalidation proposed `revise_claim`, rewording the fact as history: "before the close() method and its two tests were added".
5. The revision's own review returned `revise` ("Cited event does not show close() or its two tests were absent when the run occurred").
6. The trial ended with the claim a weak candidate. No admitted claim held the command, although it still worked.

The ninth gate's R1 lost a failure lesson the same way. After a later success, revalidation added a retry condition. Its review did not support the condition, and the lesson was left a weak candidate.

The documents produced this outcome:
- A `revise_claim` revision is a candidate reviewed again (DATA_CONTRACTS §8; decision 0012). Its head is the claim's head, so the guidance stops at once.
- Decision 0011's verdict effects then apply as for a new candidate:
  - `revise` leaves it a candidate;
  - a substantive `reject` archives it.

So a revision that its review does not support leaves the claim with no guidance at all, or archives it. That happens although the content it replaced had been reviewed `supported` and nothing refuted it. SYSTEM_SPEC §7.3 says the opposite of that effect: "Dependency changes set freshness to `needs_revalidation`; they do not automatically make a claim false." The failed review judged the revision, not the claim it revised.

A scripted reproduction (below) showed both outcomes before the fix. A `revise` left the reworded candidate, and a `reject` archived the claim.

## Decisions

1. **A revision of guidance that its review does not support restores the guidance it replaced.**
   - **When.** A revision of live guidance is a candidate revision whose earlier revisions lead back, through candidates only, to an `active` or `disputed` revision. Only `revise_claim` turns guidance into a candidate. The restore happens when the verdict on such a revision is `revise` or a substantive `reject`. It also happens when the revision is deferred unreviewed: too large to review (`review_input_oversized`), or past the bounded retries (`review_retry_limit`, decision 0044).
   - **What comes back.** The next revision restores, from that guidance revision:
     - its status;
     - its content: proposition, key, scope, conditions, dependencies, support, failure and procedure bodies;
     - its review assessment, which is the review that admitted that content.
   - **What stays from the head:** the kind, basis, context links, contradictions and relations. A counter-observation therefore stays attached as context.
   - **How it is labeled.**
     - Freshness is `needs_revalidation`: the change that prompted the revision has still not been examined, so the claim is delivered as context with its freshness label, never as caution.
     - Strength comes from lineage.
     - The activation gate a supported review applies must pass; otherwise nothing is restored.
     - Rechecks recorded while it was a candidate are folded in and become pending, as at an activation.
   - **No loop.** The next review is due a full period later (30 days for volatile claims), not now. A revision that keeps failing its review therefore cannot loop.
   - **History.** The failed revision and the verdict on it stay in history.
     - On the verdict path the restore is part of the review's application, so `undo` covers it.
     - On the two deferral paths it is an audited deterministic revision (`operations.kind = restore_guidance`).
2. **What does not change.**
   - A supported review of a revision makes the revision the guidance, as before.
   - A claim that was never guidance keeps decision 0011's effects: an extraction's new candidate stays a candidate on `revise`, and is archived on `reject`.
   - A capacity `reject` before the retry limit leaves the candidate while it is retried.
   - Between the revision and its review, the claim is still an unreviewed candidate, delivered at most as tentative context. A session that starts in that window gets the tentative revision, not the restored guidance.
   - A failure lesson that comes back after a later success is context only. Caution after a later success still needs a reviewed retry condition, a narrowing, a retirement, a dispute or a newer failure (SYSTEM_SPEC §7.3).
3. **`revalidate@4`** (`revalidate_v4.md`) is `@3` plus one paragraph, aimed at the wording that started L1's loss. It says:
   - a changed dependency is a reason to look again, not evidence against a claim;
   - when the events show a fact or procedure still holds after the change, keep it; when only a detail changed, revise that detail and cite the later event;
   - never reword a current fact or procedure into history.
   - Failure lessons are unaffected: their failure stays true as history, and the existing rules for them apply.
   - New revalidation jobs pin `@4`. A job that pinned `@1`–`@3` is still served its text. The extraction and review prompts are unchanged.
4. **Engine `0.1.0.dev18`.** It carries the restore and `revalidate@4`. The comment on the `tools-used` transcript record in `claude_capture.py` now says what decision 0050's correction found: the record is written between model requests. Skipping it is unchanged. No contract field, schema or store migration changed.

## Specification

DATA_CONTRACTS §5's verdict effects and §8's `revise_claim` row now name the restore. SYSTEM_SPEC is unchanged: §7.3 already says a dependency change does not make a claim false, and this decision makes a failed revision honor that.

## Found, not changed

- **The remembered command named Recalith's own interpreter.** L1's candidate agent read `.recalith/project.toml`, found Recalith's runtime and ran the tests with `.recalith/runtime/0.1.0.dev17/venv/Scripts/python.exe`, so the admitted fact named that path.
  - In the preview it stays usable. Old runtimes are never deleted (`bootstrap.py` removes only its staging directory), and in-place upgrade is not available (OPERATIONS §3).
  - Telling the extraction to restate such a command without the path would make the claim differ from what the cited event shows. The stricter review objects to exactly that kind of difference: support failed the ninth gate on two overstated details. So the extraction prompt is unchanged.
  - Revisit when in-place upgrades exist (full release).
- **S4's user rule was never extracted** (the November build log, 2026-11-15). After session A the extraction returned no operation. It called the user's frozen-format rule "a task objective, not a durable preference or decision", and said a user_declared claim "cannot be cited with the exact locator and SHA-256 digest required". This concerns extraction, which this decision does not change. S4 is in the sensitivity set, so it does not decide the gate.

## Tests

- `test_a_revision_of_guidance_that_fails_its_review_restores_the_guidance[revise|reject]`, the L1 reproduction:
  - an admitted fact with a file dependency, then an ordinary edit of the file;
  - revalidation rewords the fact as history, and the reworded revision's review returns `revise` or a substantive `reject`.
  - **Before the fix:** the head was the reworded candidate, or the archived claim.
  - **Now:** the original fact is active and `needs_revalidation`, with its support, dependencies, admitting review and strength. It is delivered as context, its next review is a full period away, and no revalidation is queued. History keeps the reworded revision and its verdict.
- `test_a_failure_lesson_whose_retry_revision_fails_review_returns_without_caution`, as in R1: the lesson comes back as context only, its counter-observation kept and the later-success recheck cleared.
- `test_a_revision_of_guidance_left_unreviewed_at_the_retry_limit_restores_the_guidance`: one audited `restore_guidance` operation, and no further review.
- `test_a_supported_revision_of_guidance_replaces_it`: the supported path is unchanged.
- `revalidate@4` is pinned by its golden digest. It is `@3` plus exactly the new paragraph, and the older digests are kept.
