"""Deterministic stand-in for a Claude Code session, for delivery-probe tests only.

It reads the workspace's ``.claude/settings.local.json`` hooks, fires the four
delivery events with Claude-shaped payloads, collects ``additionalContext`` and
plays a "model" that echoes a delivered canary. Results against this fake are
harness tests, never host certification.

``FAKE_HOST_SCENARIO``:
  echo              default: hook context reaches the model, which echoes it
  ignore_context    hooks run and print context, but the model never sees it
  no_prompt_hook    the host never fires UserPromptSubmit
  no_pre_action     the host never fires PreToolUse
  leak_tool_output  the fixture tool's output repeats the delivered context
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path

SCENARIO = os.environ.get("FAKE_HOST_SCENARIO", "echo")
CANARY = re.compile(r"Recalith delivery canary: ([0-9a-f]{32})")


def emit(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


def hooks_for(event: str, matcher_value: str | None) -> list[str]:
    path = Path.cwd() / ".claude" / "settings.local.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    out = []
    for group in data.get("hooks", {}).get(event, []):
        m = group.get("matcher")
        if m is not None and matcher_value is not None and m != matcher_value:
            continue
        out += [h["command"] for h in group.get("hooks", []) if h.get("type") == "command"]
    return out


def fire(event: str, matcher_value: str | None, payload: dict) -> list[str]:
    contexts = []
    for command in hooks_for(event, matcher_value):
        proc = subprocess.run(command, shell=True, input=json.dumps({"hook_event_name": event, **payload}).encode(), capture_output=True, check=False)  # noqa: S602 - fixture
        out = proc.stdout.decode().strip()
        if out.startswith("{"):
            try:
                ctx = json.loads(out).get("hookSpecificOutput", {}).get("additionalContext")
            except ValueError:
                ctx = None
            if ctx:
                contexts.append(ctx)
    return contexts if SCENARIO != "ignore_context" else []


class Session:
    def __init__(self) -> None:
        self.context: list[str] = []
        self.messages: list[dict] = []
        self.session_id = str(uuid.uuid4())
        home = Path(os.environ.get("HOME", "."))
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(Path.cwd()))
        self.transcript = home / ".claude" / "projects" / slug / f"{self.session_id}.jsonl"
        self.transcript.parent.mkdir(parents=True, exist_ok=True)

    def record(self, entry: dict) -> None:
        with open(self.transcript, "a") as fh:
            fh.write(json.dumps(entry) + "\n")

    def add_context(self, items: list[str]) -> None:
        for item in items:
            self.context.append(item)
            self.record({"type": "attachment", "content": item})

    def model(self, turn: str) -> dict:
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        if base_url:
            body = {"model": "fake", "stream": False, "system": [{"type": "text", "text": c} for c in self.context], "messages": self.messages + [{"role": "user", "content": turn}]}
            req = urllib.request.Request(base_url + "/v1/messages", data=json.dumps(body).encode(), headers={"content-type": "application/json"})
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=60) as resp:
                block = json.loads(resp.read())["content"][0]
            return block
        if "echo recalith-fixed-output" in turn and not any("tool_result" in json.dumps(m) for m in self.messages):
            return {"type": "tool_use", "name": "Bash", "input": {"command": "echo recalith-fixed-output"}}
        if turn.startswith("Reply with the single word OK"):
            return {"type": "text", "text": "OK"}
        found = [m.group(1) for c in self.context for m in CANARY.finditer(c)]
        return {"type": "text", "text": f"CANARY {found[-1]}" if found else "CANARY NONE"}

    def turn(self, text: str) -> None:
        if text == "/compact":
            self.context = []
            self.messages = []
            emit({"type": "system", "subtype": "compact_boundary"})
            self.add_context(fire("SessionStart", "compact", {"source": "compact"}))
            return
        if SCENARIO != "no_prompt_hook":
            self.add_context(fire("UserPromptSubmit", None, {"prompt": text}))
        self.record({"type": "user", "content": text})
        block = self.model(text)
        if block["type"] == "tool_use":
            emit({"type": "assistant", "message": {"content": [block]}})
            if SCENARIO != "no_pre_action":
                self.add_context(fire("PreToolUse", "Bash", {"tool_name": "Bash", "tool_input": block["input"]}))
            output = "recalith-fixed-output"
            if SCENARIO == "leak_tool_output":
                output += " " + " ".join(self.context)
            emit({"type": "user", "message": {"content": [{"type": "tool_result", "content": output}]}})
            self.messages += [{"role": "user", "content": text}, {"role": "assistant", "content": [block]}, {"role": "user", "content": [{"type": "tool_result", "content": output}]}]
            block = self.model(text)
        emit({"type": "assistant", "message": {"content": [block]}})
        self.record({"type": "assistant", "content": block})


def main() -> int:
    args = sys.argv[1:]
    if "--version" in args:
        print("9.9.9 (Fake Host)")
        return 0
    raw = sys.stdin.read()
    if "--input-format" in args:
        turns = [json.loads(line)["message"]["content"] for line in raw.splitlines() if line.strip()]
    else:
        turns = [raw]
    session = Session()
    emit({"type": "system", "subtype": "init", "claude_code_version": "9.9.9", "model": args[args.index("--model") + 1] if "--model" in args else None})
    session.add_context(fire("SessionStart", "startup", {"source": "startup"}))
    for t in turns:
        session.turn(t)
    emit({"type": "result", "subtype": "success", "is_error": False})
    return 0


if __name__ == "__main__":
    sys.exit(main())
