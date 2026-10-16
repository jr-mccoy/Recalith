# Claude Code 2.1.301 capture fixtures (request-capture, sanitized)

Recorded on 2026-10-16 from the installed Claude Code CLI **2.1.301** on Linux
x86_64 by `tools/capture_claude_fixtures.py` (decision 0005). Each scenario ran
in a disposable, owned workspace with a private `HOME`. Owned capture-only
recorder hooks (`tools/fixtures/hook_recorder.py`) were appended to the
workspace's `.claude/settings.local.json` beside planted unrelated settings.
Afterwards they were removed: 23 owned entries removed, unrelated settings
preserved byte for byte.

**Mode: `request_capture`.** The hook payloads and transcript structure are
the real host's. The model turns came from a loopback scripted endpoint with a
placeholder key, so tool, subagent and compaction hooks could fire without an
account. These files are host-format evidence, not a live certification. They
say nothing about model-visible delivery, and no session credentials or proxy
were used.

| File | Contents |
|---|---|
| `manifest.json` | Host version, method, per-scenario event counts, events observed and not observed, cleanup result |
| `<scenario>.hooks.jsonl` | One record per hook firing: the event name it was registered for, the transcript's byte length when it fired, and the exact sanitized stdin payload |
| `<scenario>.transcript.jsonl` | Transcript boundary records: `user`/`assistant`/`system` records kept (sanitized); other record types reduced to `{type, fields}` skeletons because they hold host system prompts and API request blobs |
| `subagent.agent-<id>.transcript.jsonl` | The subagent's separate transcript (`<session>/subagents/agent-<id>.jsonl`) |

Scenarios:

- `lifecycle`: startup, two prompts (the second was queued and reuses the
  first's `prompt_id`), and 13 tool calls. The calls include Bash success, a failing pytest at three
  output sizes, `grep` no-match, a `seq` above the stdout cap, Read
  success/failure, Write, Edit, `ls` exit 2, a 1 s timeout and a pipeline.
  Then manual `/compact`, stop and end.
- `subagent`: an `Agent` call that runs in the background, its own tool call
  and stop, and the host-generated `<task-notification>` prompt.
- `denied`: a Bash call not in `--allowedTools`. `PreToolUse` and
  `PermissionRequest` fire, and no post-tool hook follows.
- `secret_and_resume`: `--resume` of the lifecycle session, a credential-shaped
  prompt (`password=fixture-hunter2-not-real`, a synthetic placeholder), then
  `/clear`, which ends that session and starts a new one.

Placeholders: `<workspace>`, `<workspace-slug>`, `<home>`, `<host-tmp>`,
`<tmp>`, `<fixture-root>`, `<repo>`, `<python>` and `<user-home>`.
`tests/platform/claude_fixtures.py` replaces them with real temporary paths
on replay.

## Observed versus not observed

Observed: `SessionStart` (`startup`, `resume`, `clear`, `compact`),
`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`,
`PermissionRequest`, `Stop`, `SubagentStart`, `SubagentStop` (also fired for
the compaction summarizer, with an empty `agent_type`), `PreCompact`,
`PostCompact`, `SessionEnd` (`other`, `clear`).

Registered but not observed in these scenarios: `Notification`,
`PermissionDenied`, `StopFailure`, `InstructionsLoaded`, `ConfigChange`,
`CwdChanged`, `FileChanged`, `TaskCreated`, `TaskCompleted`, `Elicitation`,
`ElicitationResult`. Not reproducible without an interactive terminal: a
user interrupt (`is_interrupt: true`) and an auto-compaction trigger.

## Host facts these fixtures pin (2.1.301)

- No hook payload carries the host version; the adapter takes it from the
  integration manifest.
- `prompt_id` is not unique: queued prompts reuse it.
- `PostToolUse` for Bash has no exit code. A nonzero exit can still arrive as
  success with `returnCodeInterpretation` (`grep` exit 1: "No matches
  found").
- `PostToolUseFailure.error` for Bash starts `Exit code N\n` (143 for the
  timeout).
- Bash stdout is head-capped at 30,000 characters. `persistedOutputSize`
  reports the original size, and `persistedOutputPath` names a host file that
  Recalith does not read.
- Failing output is that capped text, middle-truncated to about 10,000
  characters with `... [N characters truncated] ...`. A failure line at the
  end therefore survives only when the whole output is under about 30,000
  characters.
- A denied call gets `PermissionRequest` (no `tool_use_id`, no outcome) and
  no post-tool hook.

Re-capture after any host version change into a new `<version>/` directory;
never edit these files by hand.
