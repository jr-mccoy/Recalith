# Decision 0048: The Windows launcher parses

Status: accepted (Tasks 2 and 18, preview) · Date: 2026-11-09 · Engine: `0.1.0.dev16` · Observed: CI on `main` red on Windows from `412cb9e` (`0.1.0.dev14`, decision 0046) to `8052a8b` (`0.1.0.dev15`); the release workflow red on the same commits

## Context

Decision 0046 made the launchers name the bootstrap form. In the `.cmd` launcher the new text sat inside the `if not exist "%PY%" ( … )` block and contained its own parentheses: `(python bootstrap.py install --project "%ROOT%" … --wheelhouse DIR)`. cmd.exe parses a whole parenthesized block before it runs any of it, and an unquoted `)` ends the block. The rest of the line then failed to parse (`. was unexpected at this time.`), so **every** invocation of `.recalith\bin\recalith.cmd` exited 255, with or without a provisioned runtime. The same would have happened under a project path holding a `)`, such as `C:\Program Files (x86)\…`, because `%ROOT%` is expanded inside the block before parsing.

The Phase 3 and Phase 4 checkpoints recorded the deterministic suite on Linux only, where the `sh` launcher was unaffected, and the Windows CI job's 84 failures (82 operator-guard cases through the launcher, the missing-runtime case, and one notice assertion) went unread. The owner's next step, walking OPERATIONS §4 on native Windows, would have stopped at its first `recalith.cmd` command.

Two failures on the same commits were not engine defects:

- The session-start notice test asserted the POSIX spelling `recalith status`; on Windows the notice correctly names `.recalith\bin\recalith.cmd status` (decision 0046 item 8). The notice text was complete; pytest's own shortening of a long string in the assertion message made it look truncated.
- The release workflow's offline walk chose the `cp313` wheelhouse but ran the runner's `python3`, which the Ubuntu image had moved to 3.14. `bootstrap.py` refused correctly and named the mismatch. OPERATIONS §4 and the README showed the same fixed `cp313` beside a bare `python3`, which a stranger with Ubuntu's 3.12 would also have tripped on.

## Decisions

1. **The `.cmd` launcher has no parenthesized block.** It tests `if exist "%PY%" goto run`, prints the refusal and exits 4 at top level, and runs the runtime after the `:run` label. Nothing in the message or the expanded path can end a block. The hook launcher already used single-line `if … exit /b 0` and is unchanged.
2. **Tests:** the missing-runtime refusal under project paths containing `(x86)`, `R&D (copy)` and `a)b` exits 4 with the message and the path (Windows only, invoked as OPERATIONS §4 does, from the project by relative path); a structural check that no Windows launcher line opens or closes a block; the launcher digest re-pinned. The notice test expects the spelling of the platform it runs on.
3. **The wheelhouse tag follows the interpreter.** The release workflow's walk, README and OPERATIONS §4 (Linux) derive the tag from the `python3` that runs the bootstrap. The Windows steps already name their interpreter (`py -3.13`) and its wheelhouse.
4. **Engine `0.1.0.dev16`.** A new installation's tracked launcher changes bytes. A Windows project initialized by `0.1.0.dev14` or `0.1.0.dev15` keeps the broken launcher: `init` never touches an existing installation, and moving a project between engines is not built for the preview (Task 17, full-only). No real installation runs those engines (the owner's last pilots ran `0.1.0.dev10`), so the next pilot is provisioned fresh on this engine. No adapter, schema, contract or policy changed.

## Rejected

- **Escape the parentheses (`^(`, `^)`) in the message.** It fixes the message but not a `)` arriving through `%ROOT%`, which is expanded before the block is parsed.
- **Delayed expansion (`!ROOT!`).** It would protect the path inside a block, but it changes how `!` in a path or argument is read; the block is unnecessary.
