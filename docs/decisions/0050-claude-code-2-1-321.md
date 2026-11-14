# Decision 0050: Claude Code 2.1.321

Status: accepted (Task 3b capture review, preview) · Date: 2026-11-14 · Engine: `0.1.0.dev17` · Observed: Claude Code 2.1.321 on native Windows in request capture (loopback scripted endpoint, placeholder key, private `HOME`; this session's credentials and proxy never used)

## Context

The installed host updated itself from 2.1.310 to 2.1.321 after the tenth gate. The engine certifies capture only for the versions in `claude_capture.CERTIFIED_VERSIONS`. The eleventh gate checks the installed host against the certified version before every session and stops on a change, so it cannot run on 2.1.321 until that version is reviewed (OPERATIONS §6: "A new version then needs its own capture review and live certification before another gate").

## Decisions

1. **Capture certification of Claude Code 2.1.321** (decision 0019 procedure, as decision 0029 did for 2.1.310).
   - **Captured** with `tools/capture_claude_fixtures.py` → exit 0. It observed the same 12 hook events as 2.1.310 and the same 11 not observed. Cleanup removed 23 owned hooks, left none modified and preserved the unrelated settings.
   - **Reviewed against the 2.1.310 capture on the same laptop:**
     - Every hook payload has the same field set and value types, compared recursively.
     - The denied, subagent and secret-and-resume scenarios have the same event sequences.
     - The lifecycle scenario has one more `SubagentStop`, adjacent to the first, with an identical payload shape. Compaction ran a second summary subagent, with its own `agent_id` and transcript path. Its source key is distinct, so it is captured as its own event, as any subagent stop is.
   - **Transcripts add one record type, `tools-used`** (`sessionId`, `tools`, `type`). It lists the tool names used before a compaction summary. The hooks already captured each of those calls, so the transcript supplement now skips it as a known type. Without that it would have been an explicit `unsupported_record_type` gap on every compacted session.
   - **The subagent transcript adds a `user` record with `isMeta: true`,** a host system reminder naming the tools used before the summary. The supplement maps assistant text only, and user messages come from the `UserPromptSubmit` hook, so a meta user record never becomes the user's words. That holds for this record and for the `local-command-caveat` record 2.1.310 already wrote.
   - **The adapter maps every record identically to 2.1.310,** apart from the one extra `SubagentStop`. The subagent scenario compares as a multiset, as before. The transcripts parse to the same assistant-message counts.
   - 2.1.321 joins `claude_capture.CERTIFIED_VERSIONS` and the lineage rules' version set, which a test keeps equal. Its fixtures are `tests/fixtures/hosts/claude/2.1.321/`.
   - This is not a live certification. The live delivery certification of 2.1.321 is the owner's engine-mode run on the next fresh pilot (`tools/probe_delivery.py --engine-project`), as for 2.1.309 and 2.1.310.
2. **Engine `0.1.0.dev17`.** The certified-version set and the transcript type list are in the wheel. No contract, schema or policy changed. The deny-spelling test is re-pinned to `0.1.0.dev17`.

## Tests

- `test_reviewed_2_1_321_fixtures_map_like_2_1_310` (four scenarios; the lifecycle comparison removes the one extra, identical `SubagentStop`).
- `test_reviewed_2_1_321_transcripts_parse_like_2_1_310`.
- `test_a_tools_used_record_is_skipped_not_a_gap`: the fixtures keep only the record's skeleton, so a real record is parsed here, and an unknown type is still a gap.
- `test_reviewed_2_1_321_fixtures_are_sanitized`.
- Native Windows, Python 3.13.15: `tests/integration/test_claude_adapter.py`, `tests/platform/test_claude_smoke.py`, `tests/platform/test_capture_only_claude.py`, `tests/unit/test_lineage.py`, `tests/unit/test_live_eval.py`, `tests/unit/test_delivery_probe.py`, `tests/integration/test_installations.py` → 248 passed, 29 skipped.
