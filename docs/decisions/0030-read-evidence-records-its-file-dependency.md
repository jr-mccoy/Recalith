# Decision 0030: A supporting read records its file dependency

Status: accepted (Task 9/10 engine slice, preview) · Date: 2026-10-29 · Engine: `0.1.0.dev2` · Observed: the second live gate's R4 (2026-10-29), then the owner's R4 rerun on its own with kept workspaces, whose store was read read-only

## Context

The second live gate failed one quality target, `conflict_uncertainty_preservation`, on R4 (BUILD_PROGRESS, 2026-10-29 checkpoint). Session C's prompt got the fact "notes are stored in notes.json" as `current`, although the session's overlay had moved `fieldnotes/store.py` to `notes.jsonl`. The gate deletes its workspaces, so the owner reran R4 on its own with `--keep-workspaces`. It reproduced with no contamination. Both arms succeeded, the candidate's one claim reached C's prompt as `context`/`current`, and the expected `conflict_or_freshness_label` retrieval point was not met.

The kept store shows the cause:

- **No dependency was recorded.** The extractor's only support was session A's certified `Read` of `fieldnotes/store.py`, the `notes.json` version. It scoped the fact to `fieldnotes/store.py` and declared `dependencies: []`, and the `dependencies` table was empty. The extraction prompt never mentions dependencies. Decision 0020 item 13's live check runs only on registered dependencies. So the overlay's change, made outside any captured tool as a pull or an editor would, had nothing to compare.
- **An attached contradiction changed nothing.** After C, extraction attached C's `Read` of the new `store.py` as `contradicts`, and admission accepted it. The claim stayed `active`, `current` and `supported`, and no recheck or revalidation was queued. This is not fixed here (Limits).

## Decisions

1. **Code records the file dependency of a supporting read.**
   - **The rule.** A claim's support may include a certified read that named an exact scope path of the claim (a scope path that does not end in `/`). That path becomes a `file` dependency of the claim unless one is already declared. A certified read is a `tool_finished` event under `observed_tool` authority, not derived, with its result received, parsed exactly, with `action_kind` `read`.
   - **Where it applies.** Code applies the rule wherever it writes a claim's dependencies or support: a new claim; an exact duplicate that merges new support; `attach_evidence` with `supports`; and `revise_claim`, including one that replaces the dependencies.
   - **Resolution.** Each added dependency resolves by the registered rule (DATA_CONTRACTS §5), against the reads that named it. Its fingerprint is the current workspace bytes, or null when a certified write to the path came after the latest of those reads. The fingerprint is not resolved against the claim's other evidence: a later user message must not make bytes written after the read look current.
   - **Exclusions.** Decisions and preferences add nothing, because they state intent, not a file's contents. A read of another file, a directory scope and an unscoped claim add nothing either. So the hook's 16-file live check is bounded by the claim's own scope.
   - **The prompt is unchanged.** A model may still declare other dependencies.
   - **Effects.**
     - A later change to the file shows the item `needs_revalidation`, with `dependency_false`, in both compilers (decision 0020 item 13).
     - A certified write to the file records a `dependency_changed` recheck and queues revalidation (decision 0012 item 4).
     - Review classes do not move, because every kind this rule applies to was already volatile.
2. **Engine `0.1.0.dev2`.** The wheel changes. The bootstrap refuses a different artifact under a version it has already provisioned, and `0.1.0.dev1` is provisioned in the second pilot. So the next live run needs a fresh pilot on the new wheel, as in decision 0029 item 4.

## Tests

- `test_a_supporting_read_of_a_scoped_file_records_its_dependency` (integration, consolidation) covers:
  - the dependency and its fingerprint;
  - a declared dependency recorded only once;
  - the cases that add nothing: unscoped, another path, a directory scope, support that is not a read, and a decision or preference;
  - a revision that empties the dependencies;
  - a write after the read, which resolves unknown.
- `test_a_fact_read_from_its_scoped_file_is_labeled_when_the_file_changes` (integration, retrieval) runs R4's shape end to end: no declared dependency, a change outside the host, and the label in the service packet and the hook packet. Before the fix both tests fail, the second exactly as the live run did (`current`).
- The deny-spelling test is re-pinned to `0.1.0.dev2`.

## Limits

- **An attached contradiction still leaves an active claim as it was.**
  - SYSTEM_SPEC §3.5 lists a contradiction as a revalidation trigger. But decision 0012 item 1's recheck reasons do not include one, and the extraction prompt offers only `attach_evidence` and `revise_claim` for an existing claim.
  - Closing this needs a recheck reason, which is a schema migration, so it is left for the owner.
  - It does not affect R4's measured point, C's prompt, which comes before C's read.
- **The fingerprint is taken at admission.** It is the bytes when the claim is admitted, not the bytes that were read. A change outside any captured tool between the read and the extraction, minutes later, becomes the claim's recorded state. The same holds for declared dependencies.
- **Only reads count.** A fact supported by the agent's own `Edit` or `Write` adds nothing: the host does not report the written bytes.
- **R4's gold basis is `user_declared`.** The live extractor inferred the fact from the read instead. Nothing here changes that, and adjudication reads it.

## Consequences

The owner provisions a fresh pilot from `dist\recalith-0.1.0.dev2-py3-none-any.whl`, certifies its route, and runs the engine-mode delivery probe on the installed 2.1.310 (BUILD_PROGRESS handoff). Then the R4 rerun shows whether the label now reaches C's prompt live, before any full gate. The second pilot (`0.1.0.dev1`) stays as the record of the second gate.
