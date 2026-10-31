# Decision 0033: A file dependency records the bytes its read observed

Status: accepted (Task 10 slice, preview) · Date: 2026-10-29 · Engine: `0.1.0.dev4` · Schema: 12 · Decided by: the owner's delegation

## Context

A file dependency's fingerprint was the file's bytes when the claim was admitted (DATA_CONTRACTS §5). Admission comes minutes after the session, after the extraction debounce and the review. In the third live R4 rerun, the extractor declared `fieldnotes/store.py` as asked (decision 0031):

- session A read the file at 21:27:03Z;
- it changed outside any captured tool at 21:27:15Z;
- the claim was admitted at 21:32:40Z.

So the recorded fingerprint was of the changed file, and session C's prompt showed the stale fact as `current`. Decision 0028 item 18 fixed the harness order that caused this in the trial. But the race is real in use: a `git pull`, a branch switch or an editor save right after a session does the same.

There was a second hole. When a certified write followed the claim's evidence, the fingerprint was null, which the live check treats as unknown. A claim admitted after the agent itself edited the file was therefore shown as `current`.

## Decisions

1. **A live certified read records what it read.** In the read's ingestion transaction, code records the SHA-256 of each path a certified, exactly parsed `read` named, as `file_observations` (event, path, fingerprint, commit sequence; schema 12). This happens only when nothing can have changed the bytes since:
   - the read succeeded and a live hook captured it, in this workspace;
   - it is ingested within 120 s of its capture, so a replay, a recovery or a late segment records nothing;
   - the target is a regular file inside the workspace, read under the path policy, within the bounded fingerprint size;
   - its modification time is not later than the capture.

   At most 16 paths are recorded per read, as in the hook's live check.
2. **A file dependency resolves to those bytes.** The fingerprint is the latest recorded read of the path among the claim's cited events. Failing that, it is the latest among the events the proposal read (its read set), which covers a declaration that cites only the user's words. With neither, the earlier rule applies: the current bytes, or null after a certified write. A later change, captured or not, then shows in the live check as `needs_revalidation` with `dependency_false` (decision 0020 item 13).
3. **Forgetting** purges the observations of the reads it purges. The rows are fingerprints only, never content.

## Tests

- `test_a_file_dependency_records_the_bytes_its_read_observed` (integration, consolidation) covers:
  - the observation;
  - the cited and the consulted resolution, with the file changed before curation;
  - the late read and the read whose file changed after capture, both of which record nothing and fall back to the earlier rule.
- `test_a_fact_whose_file_changed_before_its_curation_is_labeled` (integration, retrieval) runs the third rerun's shape end to end, in the service packet and the hook packet.

Both failed before the change, the second exactly as the live run did (`current`).

## Limits

- **The observation is taken at ingestion, not at the read.** The hook-started worker normally ingests within seconds. A change inside that gap is invisible, except through the modification-time check. Fingerprinting in the hook itself would close the gap, but it would change the audited stdlib hook path, so it is not done here.
- **A modification time can be preserved** by a copy that keeps it (`cp -p`, some archive tools). Such a change before ingestion is missed.
- **A file changed after the read but before admission is labeled by the live check, but no recheck row is recorded.** Revalidation then waits for the next certified write to the file or for the due review.
- **Only reads count.** A claim supported only by the agent's own edits keeps the earlier rule.

## Consequences

Engine `0.1.0.dev4` and schema 12 (with decision 0032); a fresh pilot.
