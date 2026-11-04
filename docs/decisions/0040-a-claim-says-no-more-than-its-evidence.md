# Decision 0040: A claim says no more than its evidence, and the review tests every clause

Status: accepted (Task 9 extraction and Task 10 review, preview) · Date: 2026-11-04 · Engine: `0.1.0.dev10` · Observed: the ninth live gate (`0.1.0.dev9`, Claude Code 2.1.310, 6 slots)

## Context

The ninth gate met every measure that needs no labels and both recall measures, and showed all five demonstrations. With the owner's recorded labels, it failed on supported precision: 22 of 24 admitted claims were supported, against 0.95. Two model reviews agreed on the labels (decision 0028 item 31).

Both unsupported claims are true in substance and add a detail their evidence does not show:
- **C2 `claim_a72bb89c`:** "…so the checks need `NOTES_HOME` set to a directory". `tools/check.py` only reads and prints the variable; any value works.
- **L2 `claim_7928f95d`:** "store.add writes that value with datetime.isoformat() in UTC, so list output is ISO-8601 only for notes written through store.add". UTC is the default only when no `now` is passed, and "only" claims an exclusivity the code does not show.

The review supported both.

R3's recall miss is the same fault the other way round:
- After session C, the extraction proposed the user's correction as "The user wants the grocery budget kept under $700 per month". That carried over the replaced claim's "kept under" framing; the user's words were "the grocery budget is now $700 per month, not $600".
- The review returned `revise`, rightly ("adds a ceiling framing the text does not state"). The correction stayed a candidate, and the $600 claim stayed active.
- In the eighth gate the same correction, worded from the user's words ("is $700 per month, replacing the earlier $600"), was reviewed supported.

With about 24 claims, 0.95 allows one unsupported claim. Incidental code-behavior facts carry that risk without adding recall: none of these claims holds a gold lesson.

## Decisions

1. **`extract_claims@7`** (`extract_v7.md`) is `@6` plus two sentences:
   - Say no more than the cited evidence shows. Add no requirement, type, unit, time zone, default, consequence or limit it does not state (such as "to a directory", "in UTC", or only, always, every and never), and never present a parameter's default as what always happens.
   - Word a user's declaration or correction from the user's own words. A claim replacing an existing one states the new value as the user stated it, not in the replaced claim's framing.
2. **`review_claims@2`** (`review_v2.md`) is `@1` plus one sentence. It tests every clause of the proposition against the evidence, including:
   - qualifiers such as only, always, every and never;
   - stated types, units and time zones;
   - a default presented as what always happens;
   - a consequence introduced by "so" or "because".

   A clause the evidence does not show is an objection.
3. **The pinned versions.** New jobs pin `extract_claims@7` and `review_claims@2`. A job or review batch that pinned an older version is still served its text, and a batch's `prompt_digest` keeps meaning one text.
4. **Engine `0.1.0.dev10`.** The wheel changes, so the next live run needs a fresh pilot (decision 0030 item 2).

## Rejected

- **Relax the review for a user's correction.** Its objection in R3 was correct: the proposition said more than the user did. The extraction's wording is what changes.
- **Drop incidental code-behavior facts from extraction.** Some gold lessons are facts about code, such as R1's and R4's. The fix is to state exactly what was shown, not to stop stating it.
- **Change the precision target or the count.** ACCEPTANCE_TESTS §5.1 fixes 0.95. Review threshold changes require a new versioned evaluation run, and none is proposed.

## Tests

The golden-digest test pins `extract_claims@7` and `review_claims@2`. It checks that each is its predecessor plus exactly the new text, and it keeps the older digests. The scheduling expectations name the new versions. The deny-spelling test is re-pinned to `0.1.0.dev10`.

## Limits

- **Instructions, not enforcement.** Exactness of wording is a model judgment. Only a live run shows whether the extraction words claims more exactly, and whether a stricter review costs recall.
- **The margins stay thin.** One overstated claim or one more missed lesson still decides a gate of this size.

## Consequences

The owner provisions a twelfth pilot from `dist\recalith-0.1.0.dev10-py3-none-any.whl` and runs the tenth gate, in one command (`probe-private\run-pilot12-gate10.ps1`, BUILD_PROGRESS handoff). Its labels can again be drafted here, reviewed by an outside model from a packet without this session's suggestions, and settled by the owner where the two reviews differ (decision 0028 item 31).
