"""Claude Code capture adapter for the exact host versions 2.1.301, 2.1.305, 2.1.306 and 2.1.309.

Standard library only. The mapping below was established from real hook
payloads of the installed host (``tests/fixtures/hosts/claude/2.1.301/``,
captured by ``tools/capture_claude_fixtures.py``); 2.1.305 was captured the
same way and reviewed field by field before it was added (decision 0019:
identical hook events, field sets and value formats; its transcripts add only
known metadata records), and 2.1.306 likewise (decision 0020: identical event
kinds, field sets and value types; only a background subagent's interleaving
differs), and 2.1.309 on native Windows (decision 0027: the same events, field
sets and types; values differ only by platform: Windows path separators and
CRLF in Windows subprocess output). A similar event name on another version is not
certification (DATA_CONTRACTS §2.3, SYSTEM_SPEC §9.2).

Hook event → normalized role → envelope kind:

========================  ===============  ===================================
``SessionStart``          session_start    ``session_started`` (startup, resume, clear);
                                           ``source=compact`` is ``compaction``
                                           (phase ``context_restored``)
``UserPromptSubmit``      prompt           ``user_message``; a host-generated
                                           ``<task-notification>`` prompt is a
                                           ``generic_observation``, never user authority
``PreToolUse``            pre_tool         ``tool_started``
``PostToolUse``           post_tool        ``tool_finished`` (outcome ``success``,
                                           exit code unknown: the host reports
                                           e.g. ``grep`` exit 1 as success)
``PostToolUseFailure``    post_tool        ``tool_finished`` (``failure`` or
                                           ``interrupted``; Bash ``Exit code N``)
``PreCompact``            compaction       ``compaction`` (phase ``pre``)
``PostCompact``           compaction       ``compaction`` (phase ``post``; the model
                                           summary text is not stored)
``Stop``                  stop             ``session_stopped`` (scope ``session``)
``SubagentStart``         subagent         ``session_started`` (scope ``subagent``)
``SubagentStop``          subagent         ``session_stopped`` (scope ``subagent``)
``SessionEnd``            end              ``session_ended``
anything else             unsupported      no event; an explicit coverage gap
========================  ===============  ===================================

Identity: each tool call keeps the host ``tool_use_id`` as its immutable
``tool_call_id``; its start and finish keys derive from it, so a late result
joins its own call. ``prompt_id`` is *not* unique on 2.1.301 (queued prompts
reuse it), so events without a host identity key on the session, event name,
qualifier and the transcript's byte length when the hook fired (the record
position in the registered source file, DATA_CONTRACTS §2.1).

Host output limits observed on 2.1.301: Bash stdout is head-capped at 30,000
characters (``persistedOutputSize`` reports the original size); failing output
is that capped text middle-truncated to about 10,000 characters with a
``... [N characters truncated] ...`` marker. Both are flagged as truncated
coverage, so a lost tail is never presented as complete evidence.

Unknown host versions are captured in conservative mode: no user/tool
authority, no version-specific exit-code parsing and incomplete parser
coverage (SYSTEM_SPEC §9.2: capture-only until smoke-tested).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys

from recalith.fast import redact
from recalith.fast.normalize import RawEvent, RecordGap
from recalith.fast.wire import derived_id, digest_of_text

ADAPTER_ID = "claude_code"
CERTIFIED_VERSIONS = frozenset({"2.1.301", "2.1.305", "2.1.306", "2.1.309"})
TRANSCRIPT_PARSER = "claude_code_transcript@2.1.301"

ROLES = {
    "SessionStart": "session_start",
    "UserPromptSubmit": "prompt",
    "PreToolUse": "pre_tool",
    "PostToolUse": "post_tool",
    "PostToolUseFailure": "post_tool",
    "PreCompact": "compaction",
    "PostCompact": "compaction",
    "Stop": "stop",
    "SubagentStart": "subagent",
    "SubagentStop": "subagent",
    "SessionEnd": "end",
}
_COMMON = {"session_id", "transcript_path", "cwd", "hook_event_name", "prompt_id", "permission_mode", "effort", "agent_id", "agent_type"}
_STOP = {"stop_hook_active", "last_assistant_message", "background_tasks", "session_crons"}
KNOWN_FIELDS = {
    "SessionStart": _COMMON | {"source", "model"},
    "UserPromptSubmit": _COMMON | {"prompt"},
    "PreToolUse": _COMMON | {"tool_name", "tool_input", "tool_use_id"},
    "PostToolUse": _COMMON | {"tool_name", "tool_input", "tool_response", "tool_use_id", "duration_ms"},
    "PostToolUseFailure": _COMMON | {"tool_name", "tool_input", "tool_use_id", "error", "is_interrupt", "duration_ms"},
    "PreCompact": _COMMON | {"trigger", "custom_instructions"},
    "PostCompact": _COMMON | {"trigger", "compact_summary"},
    "Stop": _COMMON | _STOP,
    "SubagentStart": _COMMON,
    "SubagentStop": _COMMON | _STOP | {"agent_transcript_path"},
    "SessionEnd": _COMMON | {"reason"},
}
# Structured host tools whose arguments are an exact object, not shell text.
READ_TOOLS = frozenset({"Read", "Glob", "Grep", "LS"})
WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
STRUCTURED_TOOLS = READ_TOOLS | WRITE_TOOLS | frozenset({"Agent", "Task", "WebFetch", "WebSearch", "TodoWrite"})
PATH_FIELDS = frozenset({"file_path", "filePath", "notebook_path", "path"})
TEST_RUNNERS = frozenset({"pytest", "py.test"})

_EXIT_CODE = re.compile(r"\AExit code (\d{1,10})\n")
_HOST_TRUNCATION = re.compile(r"\.\.\. \[\d+ characters truncated\] \.\.\.")
# Shell metacharacters that make a POSIX command line ambiguous for a static parse (A70).
_SHELL_AMBIGUOUS = re.compile(r"[|&;<>()$`\\*?\[\]{}~!#\n\r]")
_SAFE_NAME = re.compile(r"\A[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_TASK_NOTIFICATION = "<task-notification>"


class HookInputError(Exception):
    """The payload cannot be mapped; ``code`` is a content-free gap reason."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# --------------------------------------------------------------------------
# Paths and platform facts


def _identity(st: os.stat_result) -> tuple[int, int]:
    return (st.st_dev, st.st_ino)


def relative_to_workspace(path: str, workspace_identity: tuple[int, int]) -> str | None:
    """Portable POSIX path of ``path`` inside the workspace, else None.

    Containment is proven by file identity of an existing ancestor (never by
    lowercasing), after resolving symlinks.
    """
    if not isinstance(path, str) or not path or "\x00" in path or not os.path.isabs(path):
        return None
    current = os.path.realpath(path)
    tail: list[str] = []
    for _ in range(128):
        try:
            if _identity(os.stat(current)) == workspace_identity:
                rel = "/".join(reversed(tail))
                return rel or "."
        except OSError:
            pass
        parent, name = os.path.split(current)
        if parent == current or not name:
            return None
        tail.append(name)
        current = parent
    return None


def platform_facts() -> dict[str, str]:
    os_name = "linux" if sys.platform.startswith("linux") else "macos" if sys.platform == "darwin" else "windows" if sys.platform == "win32" else "other"
    machine = os.uname().machine.lower() if hasattr(os, "uname") else os.environ.get("PROCESSOR_ARCHITECTURE", "").lower()
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(machine, "other")
    return {"os": os_name, "arch": arch}


def exact_locator(path: str) -> str:
    """Same canonical form as ``capture.sources``: resolved parent plus file name."""
    absolute = os.path.abspath(path)
    return os.path.join(os.path.realpath(os.path.dirname(absolute)), os.path.basename(absolute))


def file_position(path) -> str:
    """The transcript's byte length when the hook fired, or ``-`` when unknown."""
    if not isinstance(path, str) or not os.path.isabs(path):
        return "-"
    try:
        st = os.lstat(path)
    except OSError:
        return "-"
    return str(st.st_size) if os.path.isfile(path) and not os.path.islink(path) else "-"


# --------------------------------------------------------------------------
# Actions (A70)


def parse_posix_command(command: str) -> list[str] | None:
    """An exact argv for a plain command line, or None when ambiguous.

    Pipelines, redirection, expansion, globbing, escapes, comments, multiple
    commands and leading environment assignments are not resolved statically.
    """
    if not command.strip() or _SHELL_AMBIGUOUS.search(command):
        return None
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        return None
    if not argv or "=" in argv[0]:
        return None
    return argv


def _executable_name(executable: str) -> str:
    base = re.split(r"[\\/]", executable)[-1].lower()
    return base[:-4] if base.endswith(".exe") else base


def build_action(tool_name: str, tool_input: dict, cwd_path: str, workspace_identity: tuple[int, int], warn) -> dict:
    action = {"cwd_path": cwd_path, "tool": tool_name, "action_kind": None, "executable": None, "argv": None, "paths": [], "raw_digest": None, "parse_status": "unknown", "shell": None}
    if tool_name == "Bash":
        command = tool_input.get("command")
        action["shell"] = "posix"
        if isinstance(command, str):
            # Digest the scrubbed text: a hash of a low-entropy secret could be brute-forced.
            action["raw_digest"] = digest_of_text(redact.scrub_text(command)[0])
            argv = parse_posix_command(command)
            if argv is not None and all(len(a) <= 8192 for a in argv) and len(argv[0]) <= 1024:
                action.update(parse_status="exact", argv=argv, executable=argv[0])
                exe = _executable_name(argv[0])
                if exe in TEST_RUNNERS or (exe.startswith("python") and argv[1:3] in (["-m", "pytest"], ["-m", "unittest"])):
                    action["action_kind"] = "test"
            else:
                warn("command_parse_ambiguous")
        return action
    if tool_name in STRUCTURED_TOOLS:
        action["parse_status"] = "exact"
        action["action_kind"] = "read" if tool_name in READ_TOOLS else "write" if tool_name in WRITE_TOOLS else "other"
        for key in ("file_path", "notebook_path", "path"):
            value = tool_input.get(key)
            if isinstance(value, str):
                rel = relative_to_workspace(value, workspace_identity)
                if rel is not None and rel != ".":
                    action["paths"] = [rel]
                elif rel is None:
                    warn("path_outside_workspace")
                break
        return action
    action["parse_status"] = "conservative"
    return action


def relativize_paths(value, workspace_identity: tuple[int, int], warn, key: str | None = None):
    """Exact absolute path *fields* inside the workspace become workspace-relative."""
    if isinstance(value, dict):
        return {k: relativize_paths(v, workspace_identity, warn, k) for k, v in value.items()}
    if isinstance(value, list):
        return [relativize_paths(v, workspace_identity, warn, None) for v in value]
    if isinstance(value, str) and key in PATH_FIELDS and os.path.isabs(value):
        rel = relative_to_workspace(value, workspace_identity)
        return rel if rel is not None else value
    return value


# --------------------------------------------------------------------------
# Hook payload → HookRequestWire


class Mapper:
    def __init__(self, ctx: dict, payload: dict, *, workspace_identity: tuple[int, int], recorded_at: str | None = None) -> None:
        self.ctx = ctx
        self.payload = payload
        self.workspace_identity = workspace_identity
        self.recorded_at = recorded_at
        self.version = ctx.get("host_version") or "unknown"
        self.certified = self.version in CERTIFIED_VERSIONS
        self.warnings: dict[str, int] = {}
        self.flags = {"truncated": False, "missing_context": False, "parser_incomplete": not self.certified}
        if not self.certified:
            self.warn("uncertified_host_version")

    def warn(self, code: str, n: int = 1) -> None:
        self.warnings[code] = self.warnings.get(code, 0) + n

    def coverage(self) -> dict:
        return {**self.flags, "warnings": dict(self.warnings)}

    def raw(self, kind: str, key: str, payload: dict, *, extensions: dict | None = None) -> RawEvent:
        host_session = self.payload["session_id"]
        return RawEvent(
            adapter_id=ADAPTER_ID,
            adapter_version=self.version[:64],
            source_event_key=key,
            session_id=session_id_for(self.ctx["installation_id"], host_session),
            host_session_id=host_session,
            kind=kind,
            payload=payload,
            certified=self.certified,
            origin_kind="hook",
            recorded_at=self.recorded_at,
            extensions={ADAPTER_ID: extensions} if extensions else None,
            adapter_coverage=self.coverage(),
        )


def session_id_for(installation_id: str, host_session_id: str) -> str:
    return derived_id("sess", [installation_id, ADAPTER_ID, host_session_id])


def _registration(ctx: dict, host_session_id: str, path, *, expected_name: str, subagent_of: str | None = None) -> dict | None:
    if not isinstance(path, str) or not os.path.isabs(path) or os.path.basename(path) != expected_name:
        return None
    if subagent_of is not None:
        parent = os.path.dirname(path)
        if os.path.basename(parent) != "subagents" or os.path.basename(os.path.dirname(parent)) != subagent_of:
            return None
    locator = exact_locator(path)
    if len(locator) > 1024:
        return None
    return {
        "source_id": derived_id("src", [ctx["installation_id"], ADAPTER_ID, locator]),
        "adapter_id": ADAPTER_ID,
        "session_id": session_id_for(ctx["installation_id"], host_session_id),
        "host_session_id": host_session_id,
        "source_kind": "transcript_jsonl",
        "locator": locator,
        "parser": TRANSCRIPT_PARSER,
    }


def map_hook(ctx: dict, payload: dict, *, registered_event: str | None = None, recorded_at: str | None = None) -> dict:
    """Map one 2.1.301 hook payload to a ``HookRequestWire`` (``delivery_enabled`` comes from the manifest, never the payload).

    Raises :class:`HookInputError` when the payload has no usable identity or
    comes from outside the registered workspace.
    """
    if not isinstance(payload, dict):
        raise HookInputError("payload_not_object")
    event = payload.get("hook_event_name")
    if not isinstance(event, str) or not _SAFE_NAME.match(event):
        raise HookInputError("event_name_invalid")
    if registered_event is not None and registered_event != event:
        raise HookInputError("event_name_mismatch")
    host_session = payload.get("session_id")
    if not isinstance(host_session, str) or not 1 <= len(host_session) <= 256 or not _SAFE_KEY.match(host_session):
        raise HookInputError("session_identity_missing")
    request = {"event_role": ROLES.get(event, "unsupported"), "host_event": event, "delivery_enabled": bool(ctx.get("delivery_enabled")), "events": [], "raw_events": [], "source_registrations": [], "coverage_gaps": [], "query": None}
    if event not in ROLES:
        request["coverage_gaps"].append({"code": "unsupported_host_event", "reason": event})
        return request
    try:
        root_identity = tuple(int(x) for x in ctx["workspace_root_identity"].split(":"))
    except (KeyError, ValueError):
        raise HookInputError("hook_context_invalid") from None
    cwd = relative_to_workspace(payload.get("cwd"), root_identity)  # type: ignore[arg-type]
    if cwd is None:
        raise HookInputError("foreign_workspace")
    mapper = Mapper(ctx, payload, workspace_identity=root_identity, recorded_at=recorded_at)
    unknown = sorted(set(payload) - KNOWN_FIELDS[event])
    if unknown:
        mapper.warn("unsupported_host_field", len(unknown))
        mapper.flags["parser_incomplete"] = True
    transcript = payload.get("transcript_path")
    position = file_position(transcript)
    prompt_id = payload.get("prompt_id") if isinstance(payload.get("prompt_id"), str) and _SAFE_KEY.match(payload["prompt_id"]) else "-"
    prefix = f"{host_session}:{event}"
    agent = _agent(payload)
    registration = _registration(ctx, host_session, transcript, expected_name=f"{host_session}.jsonl")
    if transcript is not None and registration is None:
        mapper.warn("transcript_path_unrecognized")
    raws: list[RawEvent] = []
    registrations = [registration] if registration and event in ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd", "SubagentStop") else []

    if event == "SessionStart":
        source = payload.get("source") if isinstance(payload.get("source"), str) and _SAFE_NAME.match(payload["source"]) else "unknown"
        key = f"{prefix}:{source}:{prompt_id}@{position}"
        if source == "compact":
            raws.append(mapper.raw("compaction", key, {"phase": "context_restored", "source": "compact"}))
        else:
            raws.append(mapper.raw("session_started", key, {"scope": "session", "source": source, "environment": platform_facts()}))
    elif event == "UserPromptSubmit":
        prompt = payload.get("prompt")
        if not isinstance(prompt, str):
            raise HookInputError("prompt_missing")
        key = f"{prefix}:{prompt_id}@{position}"
        if prompt.lstrip().startswith(_TASK_NOTIFICATION):
            mapper.warn("host_generated_prompt")
            raws.append(mapper.raw("generic_observation", key, {"text": prompt, "host_origin": "task_notification"}))
        else:
            raws.append(mapper.raw("user_message", key, {"text": prompt}))
    elif event in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
        raws.append(_tool_event(mapper, event, payload, cwd, host_session, agent))
    elif event in ("PreCompact", "PostCompact"):
        trigger = payload.get("trigger") if payload.get("trigger") in ("manual", "auto") else "unknown"
        key = f"{prefix}:{trigger}:{prompt_id}@{position}"
        if event == "PreCompact":
            body = {"phase": "pre", "trigger": trigger, "custom_instructions_present": bool(payload.get("custom_instructions"))}
        else:
            summary = payload.get("compact_summary")
            body = {"phase": "post", "trigger": trigger, "summary_received": isinstance(summary, str) and bool(summary)}
        raws.append(mapper.raw("compaction", key, body))
    elif event == "Stop":
        tasks = payload.get("background_tasks")
        raws.append(mapper.raw("session_stopped", f"{prefix}:{prompt_id}@{position}", {"scope": "session", "stop_hook_active": payload.get("stop_hook_active") is True, "background_task_count": len(tasks) if isinstance(tasks, list) else 0}))
    elif event in ("SubagentStart", "SubagentStop"):
        if agent is None:
            raise HookInputError("agent_identity_missing")
        body = {"scope": "subagent", **agent}
        if event == "SubagentStart":
            raws.append(mapper.raw("session_started", f"{prefix}:{agent['agent_id']}", dict(body, source="subagent")))
        else:
            raws.append(mapper.raw("session_stopped", f"{prefix}:{agent['agent_id']}@{position}", dict(body, stop_hook_active=payload.get("stop_hook_active") is True)))
            sub = _registration(ctx, host_session, payload.get("agent_transcript_path"), expected_name=f"agent-{agent['agent_id']}.jsonl", subagent_of=host_session)
            if sub is not None:
                registrations.append(sub)
    elif event == "SessionEnd":
        reason = payload.get("reason") if isinstance(payload.get("reason"), str) and _SAFE_NAME.match(payload["reason"]) else "unknown"
        raws.append(mapper.raw("session_ended", f"{prefix}:{reason}:{prompt_id}@{position}", {"reason": reason}))
    request["raw_events"] = raws
    request["source_registrations"] = registrations
    return request


_SAFE_KEY = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")


def _agent(payload: dict) -> dict | None:
    agent_id = payload.get("agent_id")
    if not isinstance(agent_id, str) or not _SAFE_KEY.match(agent_id):
        return None
    agent_type = payload.get("agent_type")
    agent_type = agent_type[:128] if isinstance(agent_type, str) and agent_type else "internal"
    return {"agent_id": agent_id, "agent_type": agent_type}


def _tool_event(mapper: Mapper, event: str, payload: dict, cwd: str, host_session: str, agent: dict | None) -> RawEvent:
    tool_use_id = payload.get("tool_use_id")
    tool_name = payload.get("tool_name")
    if not isinstance(tool_use_id, str) or not _SAFE_KEY.match(tool_use_id):
        raise HookInputError("tool_identity_missing")
    if not isinstance(tool_name, str) or not 1 <= len(tool_name) <= 256:
        raise HookInputError("tool_name_missing")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    action = build_action(tool_name, tool_input, cwd, mapper.workspace_identity, mapper.warn)
    arguments = relativize_paths(tool_input, mapper.workspace_identity, mapper.warn)
    finished = event != "PreToolUse"
    body = {"tool_call_id": tool_use_id, "tool_name": tool_name, "arguments": arguments, "result_received": finished, "outcome": "unknown", "exit_code": None, "result_text": None, "action": action, "observation": None}
    if event == "PostToolUse":
        body["outcome"], body["result_text"] = _success_result(mapper, tool_name, payload.get("tool_response"))
    elif event == "PostToolUseFailure":
        body["outcome"] = "interrupted" if payload.get("is_interrupt") is True else "failure"
        body["exit_code"], body["result_text"] = _failure_result(mapper, tool_name, payload.get("error"))
    key = f"{host_session}:tool:{tool_use_id}:{'finish' if finished else 'start'}"
    return mapper.raw("tool_finished" if finished else "tool_started", key, body, extensions=agent)


def _success_result(mapper: Mapper, tool_name: str, response) -> tuple[str, str | None]:
    if tool_name == "Bash" and isinstance(response, dict):
        stdout = response.get("stdout") if isinstance(response.get("stdout"), str) else ""
        stderr = response.get("stderr") if isinstance(response.get("stderr"), str) else ""
        size = response.get("persistedOutputSize")
        if isinstance(size, int) and not isinstance(size, bool) and size > len(stdout):
            mapper.flags["truncated"] = mapper.flags["missing_context"] = True
            mapper.warn("host_output_truncated")
        if "persistedOutputPath" in response:
            mapper.warn("host_persisted_output_not_read")
        if "returnCodeInterpretation" in response:
            mapper.warn("host_return_code_interpreted")
        outcome = "interrupted" if response.get("interrupted") is True else "success"
        return outcome, stdout + ("\n" + stderr if stderr else "")
    if response is None:
        return "success", None
    if isinstance(response, str):
        return "success", response
    rendered = relativize_paths(response, mapper.workspace_identity, mapper.warn)
    rendered = {k: v for k, v in rendered.items() if k != "persistedOutputPath"} if isinstance(rendered, dict) else rendered
    return "success", json.dumps(rendered, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _failure_result(mapper: Mapper, tool_name: str, error) -> tuple[int | None, str | None]:
    if not isinstance(error, str):
        mapper.flags["missing_context"] = True
        return None, None
    if _HOST_TRUNCATION.search(error):
        mapper.flags["truncated"] = mapper.flags["missing_context"] = True
        mapper.warn("host_output_truncated")
    if tool_name == "Bash" and mapper.certified:
        match = _EXIT_CODE.match(error)
        if match:
            return int(match.group(1)), error[match.end():]
        mapper.warn("exit_code_unrecognized")
    return None, error


# --------------------------------------------------------------------------
# Delivery output (Task 12b; certification of each path is Task 13)

# The hook events whose ``hookSpecificOutput.additionalContext`` reached the
# outbound model request on 2.1.301 in the Task 0b request-capture probe (a
# feasibility observation, never a delivery certification), by purpose.
DELIVERY_EVENTS = {"session_start": "SessionStart", "prompt": "UserPromptSubmit", "pre_action": "PreToolUse", "compact_restore": "SessionStart"}


def context_output(hook_event: str, text: str, *, notice: str | None = None) -> dict:
    """The nonblocking host envelope: additional context (and an optional user notice), never a permission decision or a block."""
    from recalith.fast import claude

    return claude.host_output(hook_event, text, notice=notice)


# --------------------------------------------------------------------------
# Transcript supplement (worker-side recovery of registered sources)

# Record types observed in 2.1.301 transcripts that carry nothing the hooks do
# not already capture (or that hold host request blobs); they are skipped.
KNOWN_TRANSCRIPT_TYPES = frozenset({
    "user", "assistant", "system", "summary", "attachment", "queue-operation", "atis-latch", "api-request-shape",
    "api-request-blob", "api-request", "last-prompt", "cost-state",
})


class UnsupportedRecord(RecordGap):
    """A transcript record the exact-version parser does not map (an explicit gap)."""


def transcript_line_parser(installation_id: str, *, host_version: str = "2.1.301"):
    """A ``LineParser`` for registered 2.1.301 transcripts: assistant text only.

    Hooks capture prompts, tools, compaction and lifecycle; the transcript adds
    the assistant's text, which no 2.1.301 hook delivers in full. Keys are
    the host record ``uuid``, so repeated reads deduplicate.
    """
    certified = host_version in CERTIFIED_VERSIONS

    def parse(record: dict, line) -> list:
        kind = record.get("type")
        if record.get("recalith_fixture_skeleton"):
            return []
        if kind not in KNOWN_TRANSCRIPT_TYPES:
            raise UnsupportedRecord("unsupported_record_type")
        if kind != "assistant":
            return []
        uuid = record.get("uuid")
        host_session = record.get("sessionId")
        message = record.get("message")
        if not isinstance(uuid, str) or not _SAFE_KEY.match(uuid) or not isinstance(host_session, str) or not _SAFE_KEY.match(host_session) or not isinstance(message, dict):
            raise UnsupportedRecord("record_identity_missing")
        content = message.get("content")
        texts = [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)] if isinstance(content, list) else []
        text = "\n\n".join(t for t in texts if t)
        if not text:
            return []
        return [
            RawEvent(
                adapter_id=ADAPTER_ID,
                adapter_version=host_version[:64],
                source_event_key=f"{host_session}:transcript:{uuid}",
                session_id=session_id_for(installation_id, host_session),
                host_session_id=host_session,
                kind="assistant_message",
                payload={"text": text, "sidechain": record.get("isSidechain") is True},
                certified=certified,
                origin_kind="transcript",
                adapter_coverage=None if certified else {"parser_incomplete": True, "warnings": {"uncertified_host_version": 1}},
            )
        ]

    return parse
