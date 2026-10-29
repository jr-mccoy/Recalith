# Decision 0031: The extraction prompt asks for the files a claim describes

Status: accepted (Task 9 prompt slice, preview) · Date: 2026-10-29 · Engine: `0.1.0.dev3` · Observed: the owner's R4 rerun on the third pilot (`0.1.0.dev2`) with kept workspaces, whose store was read read-only

## Context

Decision 0030 made code record the file dependency of a supporting read of a scoped file. The owner then provisioned a third pilot on `0.1.0.dev2`: route certified, runtime check certified, all four delivery paths request-visible on Claude Code 2.1.310, health `ready`. They reran R4 on its own with `--keep-workspaces`. Both arms succeeded with no contamination. The candidate again delivered its one claim to session C's prompt as `context`/`current`, so the `conflict_or_freshness_label` retrieval point was not met.

The kept store shows a different claim shape from the first rerun:

- **The user's words, nothing else.** The extractor proposed "Notes are stored in notes.json under the NOTES_HOME directory." with basis `user_declared`, which is the gold's own basis. It cited only the user's sentence in session A. Its scope has no paths and its `dependencies` are empty.
- **The read was there but not cited.** Session A had read `fieldnotes/store.py` (a certified, exactly parsed read). The claim names neither that read nor the path, so decision 0030's rule had nothing to apply to. No code rule can tie a user's sentence to a file without guessing.
- **The contradiction again changed nothing.** After C, extraction attached C's `cat` of the new `store.py` as `contradicts`. The claim stayed `active` and `current` (decision 0030 Limits).

The recorded curator's R4 proposal declares the same user statement with `{"kind": "file", "key": "fieldnotes/store.py"}`, and it meets this retrieval point in the recorded run (`docs/evaluations/preview-recorded-2026-10-21/report.md`). The live extractor never declares one, because `extract_claims@1` never mentions dependencies.

## Decisions

1. **`extract_claims@2`.** `prompts/extract_v2.md` is `extract_v1.md` plus one paragraph:
   - **What to declare.** When a fact, procedure or failure lesson states what a workspace file contains or how the code in it behaves, whether a tool result showed it or the user stated it, list each file the events show it describes. Each goes in `dependencies` as `{"kind": "file", "key": "<path>", "fingerprint": null, "record": null}`, with the path exactly as an event's `payload.action.paths` gives it.
   - **What not to declare.** No guessed or absolute path, and no config or environment dependency. An unportable path or an unregistered environment key fails the operation's validation, and the claim is lost. A decision or preference has none unless its own words make it conditional on a file.
   - **Versions.** New extraction jobs pin `@2`. `@1` stays in the build unchanged, under its golden digest, so a job that pinned it is served the same text.
   - **Scope of the change.** This amends decision 0030 item 1's "The prompt is unchanged." Code is unchanged. A declared dependency already resolves by the registered rule (DATA_CONTRACTS §5), which for a declaration means the bytes at admission.
2. **Engine `0.1.0.dev3`.** The wheel changes, so the next live run needs a fresh pilot (decision 0030 item 2).

## Tests

- `test_prompt_digests_are_pinned_separately` (integration, admission) checks:
  - `@2` is current, with its golden digest and its dependency paragraph;
  - `@1`'s digest is unchanged, and `@1` has no dependency text.
- `test_a_declared_fact_with_its_declared_file_is_labeled_when_the_file_changes` (integration, retrieval) runs the second rerun's shape with the dependency `@2` asks for.
  - The claim is a `user_declared` fact that cites only the user's words and has no scope.
  - Its dependency resolves at admission. After a change outside the host, the item is `needs_revalidation` with `dependency_false` in the service packet and the hook packet.
  - It passes without the prompt change. It shows the mechanics the prompt relies on, not that a live model follows the prompt.
- `test_reduction_schedules_narrative_within_the_ordinary_budget` (integration, requests) now expects engine-scheduled extraction jobs to pin `@2`. The jobs that file pins itself stay on `@1` and are served `@1`'s text.
- The deny-spelling test is re-pinned to `0.1.0.dev3`.

## Limits

- **A prompt is not a guarantee.** Whether the live extractor declares the file is model behavior, which only a live run shows. Two R4 reruns produced two different claim shapes, and each run is one trial.
- **A wrong but real file can be declared.** Its later change labels the claim for revalidation, the cautious direction; it can never make a claim current.
- **The attached contradiction is still not a trigger** (decision 0030 Limits). Making it one would label later sessions, not C's prompt.
- **The fingerprint is taken at admission** (decision 0030 Limits).

## Consequences

The owner provisions a fourth pilot from `dist\recalith-0.1.0.dev3-py3-none-any.whl`, certifies its route and runs the engine-mode delivery probe (BUILD_PROGRESS handoff). R4 alone with `--keep-workspaces` then shows whether the live extractor declares the file and the label reaches C's prompt. The full gate waits for that. The third pilot (`0.1.0.dev2`) and its kept R4 workspaces stay as the record of this rerun.

Observed afterwards (the fourth pilot's R4, 2026-10-29): every claim pinned `@2` and declared the files it describes, `fieldnotes/store.py` among them. The label was still missing, because the live trial changed the file before session A's curation (decision 0028 item 18).
