# Decision 0045: Retrieval holds at corpus scale; applicability comes before every candidate cap

Status: accepted (Tasks 4, 11, 12b and 13, preview) · Date: 2026-11-08 · Engine: `0.1.0.dev13` · Observed: the pre-publication audit of `0.1.0.dev10` ([report](../audits/2026-11-06-memory-system-audit.md), Phase 2 of [the fix plan](../audits/2026-11-06-fix-plan.md))

## Context

The audit reproduced, on real stores, retrieval defects that a small store hides and a store of a few months shows.

- **RET-1 (high): inapplicable claims took the candidate slots.** The service search cut its seeds to 96 by lexical score and judged scope and conditions only afterwards; the hook's lookup took 64 postings per term by static score (which rewards a narrow scope) before applicability. One applicable fact plus 200 same-topic claims scoped to another OS gave an empty packet on both paths, `omitted_count` 0 and no degraded reason. SYSTEM_SPEC §8.1 step 2 and decision 0013 ("a `false` never occupies a slot") were violated.
- **RET-2 (high): the current action's caution disappeared behind 64 other lessons.** The pre-action view held the 64 strongest action-family claims across every family, query-independent, and the hook ran no lookup for pre-action. Seventy corroborated lessons of other commands removed the caution for the command about to run, while the hook reported a healthy view.
- **RET-3 (medium): the query missed its budget where words are common.** At 10,000 heads all sharing the query words, one SELECT per hit and 96 Pydantic loads gave p50 167 ms, max 217 ms, against p95 ≤ 150 ms (ACCEPTANCE_TESTS §7).
- **RET-4 (medium): a lesson hid an outside edit.** The live dependency check ran for a failure lesson only when its applicability was true, so at every prompt (no action: `unknown`) an edited lesson showed `current` beside a fact with the same dependency showing `needs_revalidation`. Decision 0020 says every live claim with dependencies is checked.
- **RET-5 (medium): the lexical backend was sticky.** A store indexed with FTS5 and opened by a SQLite build without it kept `fts5`: every refresh, service search and forget's `optimize` then failed, so forgetting was blocked.
- **RET-6, RET-7, RET-8 (low).** The session allowance's reassembly forgot the packet cap's omissions; a disputed fallback row kept quoting a contradiction that had since expired; two conflict texts told the agent what to do inside an advisory packet.
- **CAP-6 (medium): shared folders passed the local-filesystem guard.** VirtualBox, VMware, Parallels, WSL and unknown FUSE mounts were accepted on Linux, and macOS and Windows were not checked; SQLite's locking is unreliable on all of them.
- **CAP-8, CAP-9, CAP-12 (low).** The schema snapshots omitted every operation payload, the tool payload and its observations; `<pre>`/`<code>` blocks and `%`, `#` and `user@host` prompts were not regions; an episode could quote nothing but the capture's omission marker.

## Decisions

1. **Statically inapplicable claims are skipped before the seed cap.** The service search ranks the lexical candidates in SQL, scope-filtered by workspace and task, takes at most 768 (eight times the 96 seeds), and walks them in score order, loading each and skipping a claim whose scope, path or conditions evaluate `false` for the query, until 96 remain. Passing the 768 records `candidate_scan_bounded`. The hook's lookup row of a claim that is `false` in its workspace's recorded environment has a null body and no postings, so it never occupies one of the 64 postings or 16 rows. `unknown` still passes, as before.
2. **A pre-action compile reads its own action family.** With a pending action, the hook reads the `lookup_candidates` rows of the live claims whose `action_family_digest` is that action's (indexed on `claim_heads`; at most 16, the same live filters, decision and fence), with the lookup's 60 ms floor (`deadline_lookup_skipped` otherwise). The views keep their slice unchanged; the caution no longer depends on it.
3. **The dependency check runs for every live claim with dependencies and current freshness**, in both compilers, whatever its applicability. The caution gate is unchanged: an `unknown` lesson is still context, never caution.
4. **The query is ranked before it is loaded.** One grouped SQL statement scores the claims by the query terms' idf, with the scope filter in the same statement; documents are fetched in chunks of 500 per kind without their term lists. Measured on the test container (4 vCPU): p50 64–73 ms, p95 100–118 ms at 10,000 heads all sharing the query words, two runs; the test asserts p95 under 1 s for slower CI machines and that no more than 832 documents are loaded per query.
5. **A store that loses FTS5 falls back to the token index.** `index.refresh` rebuilds on `tokens` when the recorded backend is `fts5` and this build has no FTS5. Without the module the FTS shadow tables (`lexical_fts_data`, `_idx`, `_content`, `_docsize`) are emptied directly, since they are ordinary tables holding every indexed word, forgotten ones included. Forget, retention and restore merge or clear FTS through one helper that does the same.
6. **Counts, quotes and wording.** `fit()` reports the packet cap's omissions plus every allowance cut. A fallback row records the IDs it cites (`cited_ids`) and the payload states of the events a disputed claim's text quotes (`quoted_states`); the hook drops it once one changes or is tombstoned, as for a lookup row. The two conflict texts state the conflict: "Unresolved: the evidence supports neither side over the other." and "Unresolved: Recalith has not chosen between them, and no later user decision has."
7. **The local-filesystem guard covers shared folders on every platform.** Linux adds `smb2`, `ncpfs`, `vboxsf`, `virtiofs`, `vmhgfs`, `fuse.vmhgfs-fuse`, `prl_fs`, `drvfs`, `wslfs` and the macOS names, decodes every mountinfo octal escape, and refuses a bare `fuse` mount unless its source is a known local FUSE filesystem (gocryptfs, encfs, bindfs, ntfs-3g, securefs, cryfs). macOS asks statfs(2) for `MNT_LOCAL`. Windows refuses a UNC root and a drive `GetDriveTypeW` reports as remote. An unreadable answer is not a refusal. The refusal names the filesystem.
8. **Snapshots, regions and excerpts.** `tools/generate_schemas.py` snapshots every operation payload model, `ToolPayload`, `ObservationDescriptor` and `AgentAttemptPayload` (63 snapshots). `<pre>`, `<code>`, `<blockquote>` and `<details>` open attachment regions. `%`, `#` and `user@host` prompts are shell regions only for a lowercase command word followed by an output line, since `#` also opens a Markdown heading. A result bounded at capture is quoted only from its kept head; with none, the episode quotes no excerpt.
9. **No schema change.** The plan proposed hot scope columns and per-family view rows (schema 13). A null lookup body for an inapplicable claim, the indexed family column the store already has, and fallback bodies that carry their own quote states do the same within the existing tables.
10. **Engine `0.1.0.dev13`.** No adapter changed, so a certified route needs no recertification for this engine. The release checklist's smoke gate stays blocked (decision 0043).

## Rejected

- **Hot scope columns on `retrieval_docs` and `lookup_candidates`** (the plan's 2.1). Loading at most 768 ranked claims meets the budget, and the full tri-state evaluation stays in one place, `core.conditions`; a second copy of it in SQL could drift.
- **A per-family pre-action view slice with `view_action_slice_truncated`** (the plan's 2.2). It needs a schema change and still bounds each family; the direct family read is exact and already fenced.
- **Dropping the FTS virtual table when the module is absent.** `DROP TABLE` on a virtual table needs the module; emptying the shadow tables removes the words without it.

## Tests

- `tests/integration/test_retrieval.py`: 200 claims scoped to another OS leave the applicable fact in both the service and the hook packet; 70 lessons of other families leave the current action's caution on the hook; a lesson and a fact sharing an edited dependency both show `needs_revalidation` at a prompt; 10,000 claims sharing the query words load at most 832 documents with p95 under 1 s; a store that loses FTS5 rebuilds on `tokens` with empty shadow tables, still searches, and purges and resets without the module; a disputed fallback row is dropped once its quoted contradiction expires; no conflict text carries an instruction (each fails on `0.1.0.dev12`).
- `tests/integration/test_delivery.py`: a packet cut by the allowance still counts the cap's omissions (fails on `0.1.0.dev12`).
- `tests/integration/test_installations.py`: nine network, shared-folder and unknown-FUSE mount entries (with an escaped tab and space in the mount point) are refused at `init`, naming the type; four local ones are accepted; the macOS and Windows branches answer from patched platform calls.
- `tests/unit/test_schemas.py`: the snapshots cover every operation payload and the tool payload models.
- `tests/integration/test_claim_admission.py`: HTML code and quote blocks and the new prompts are regions; headings, one-line `#` notes, percentages and email addresses are not.
- `tests/integration/test_episodes.py`: a result bounded to its tail quotes no excerpt; a kept head is quoted (fails on `0.1.0.dev12`).

## Limits

- **The query budget is measured by a test, not by a tracked measurement tool.** The figures in item 4 come from the test container; the release measurement covers the hook path only. A slower machine may still exceed 150 ms; the test's 1 s bound guards against a regression in kind, not the gate itself.
- **The macOS and Windows filesystem branches are tested with patched platform calls.** The statfs structure layout is the 64-bit-inode one; no macOS machine ran it here.
- **`unknown` applicability still takes slots.** Only a static `false` is skipped before the caps; a claim whose conditions need the pending action stays a candidate at a prompt, as SYSTEM_SPEC §8.1 requires.
- **The shell-prompt guard trades recall for precision.** A one-line `% cmd` without output, or a capitalized command after `#`, is not marked; a lowercase Markdown heading followed by text is.

## Consequences

The owner provisions a fresh pilot from the `0.1.0.dev13` wheel (or a later Phase engine) before any live run. Phase 3 (an install path a stranger can follow) is next; the smoke gate is re-run after it (fix plan Phase 5).
