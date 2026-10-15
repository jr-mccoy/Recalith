"""Deterministic stand-in for a Claude-like CLI, used only by probe unit tests.

It models the behaviors the provider probe must detect, so the harness logic is
testable without an installed host. It is never a certification subject: a
report produced against it is a test artifact, not host evidence.

Scenario (``FAKE_CLI_SCENARIO``):
  honors_flags   default; ``--bare`` disables customizations, ``--tools ""`` disables tools
  ignores_bare   loads every customization regardless of flags
  leaks_tools    always offers a Bash tool
  grandchild     spawns a long-lived grandchild process, then behaves normally
  stderr_flood   writes 200 KiB to stderr, then behaves normally

With ``ANTHROPIC_BASE_URL`` set it posts the assembled request to that endpoint
and prints the returned text. Without it (the "live" route in tests) it answers
``{"sentinels": [...], "tools": [...]}`` from what it actually loaded.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def flag_value(args: list[str], name: str) -> str | None:
    if name in args:
        i = args.index(name)
        return args[i + 1] if i + 1 < len(args) else ""
    return None


def ancestors(start: Path) -> list[Path]:
    return [start, *start.parents]


def slug(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def run_hooks(files: list[Path], event: str) -> None:
    for f in files:
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        for group in data.get("hooks", {}).get(event, []):
            for hook in group.get("hooks", []):
                subprocess.run(hook["command"], shell=True, input=b"{}", check=False)  # noqa: S602 - fixture hooks only


def mcp_tools(config_files: list[Path]) -> tuple[list[str], list[str]]:
    names, servers = [], []
    for f in config_files:
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        for name, spec in data.get("mcpServers", {}).items():
            servers.append(name)
            proc = subprocess.Popen([spec["command"], *spec.get("args", [])], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            assert proc.stdin and proc.stdout
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}) + "\n")
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
            proc.stdin.flush()
            proc.stdout.readline()
            listing = json.loads(proc.stdout.readline())
            names += [f"mcp__{name}__{t['name']}" for t in listing["result"]["tools"]]
            proc.kill()
            proc.wait()
    return names, servers


def main() -> int:
    args = sys.argv[1:]
    scenario = os.environ.get("FAKE_CLI_SCENARIO", "honors_flags")
    if "--version" in args:
        print("9.9.9 (Fake CLI)")
        return 0
    prompt = sys.stdin.read()
    home = Path(os.environ.get("HOME", "/nonexistent"))
    cwd = Path.cwd()
    bare = "--bare" in args and scenario != "ignores_bare"
    tools_flag = flag_value(args, "--tools")
    system = [flag_value(args, "--system-prompt") or ""]
    tools: list[str] = []
    servers: list[str] = []
    hook_files: list[Path] = []
    if scenario == "grandchild":
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    if scenario == "stderr_flood":
        sys.stderr.write("e" * (200 * 1024))
        sys.stderr.flush()
    if not bare:
        for f in [home / ".claude" / "CLAUDE.md"] + [d / n for d in ancestors(cwd) for n in ("CLAUDE.md", "CLAUDE.local.md")]:
            if f.is_file():
                system.append(f.read_text())
        for f in list((home / ".claude" / "skills").rglob("SKILL.md")) + list((home / ".claude" / "agents").glob("*.md")):
            system.append(f.read_text())
        mem = home / ".claude" / "projects" / slug(cwd) / "memory" / "MEMORY.md"
        if mem.is_file():
            system.append(mem.read_text())
        if "--continue" in args:
            for f in (home / ".claude" / "projects" / slug(cwd)).glob("*.jsonl"):
                system.append(f.read_text())
        hook_files = [home / ".claude" / "settings.json"] + [d / ".claude" / n for d in ancestors(cwd) for n in ("settings.json", "settings.local.json")]
        mcp_names, servers = mcp_tools([home / ".claude.json"] + [d / ".mcp.json" for d in ancestors(cwd)])
        tools += mcp_names
    if tools_flag != "" or scenario in ("ignores_bare", "leaks_tools"):
        tools = ["Bash", "Read"] + tools
    if scenario == "leaks_tools" and "Bash" not in tools:
        tools.append("Bash")
    if flag_value(args, "--json-schema") is not None:
        tools.append("StructuredOutput")
    run_hooks(hook_files, "SessionStart")
    run_hooks(hook_files, "UserPromptSubmit")

    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if base_url:
        body = {
            "model": flag_value(args, "--model"),
            "system": [{"type": "text", "text": s} for s in system],
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{"name": t} for t in tools],
            "max_tokens": 100,
        }
        req = urllib.request.Request(base_url + "/v1/messages", data=json.dumps(body).encode(), headers={"content-type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=600) as resp:
            reply = json.loads(resp.read())
        text = reply["content"][0]["text"]
    else:
        joined = "\n".join(system)
        text = json.dumps({"sentinels": sorted(set(re.findall(r"SENTINEL_[A-Z0-9_]+", joined))), "tools": tools})
    init = {
        "type": "system",
        "subtype": "init",
        "tools": tools,
        "mcp_servers": [{"name": s, "status": "connected"} for s in servers],
        "apiKeySource": "ANTHROPIC_API_KEY" if os.environ.get("ANTHROPIC_API_KEY") else "none",
        "claude_code_version": "9.9.9",
        "model": flag_value(args, "--model"),
        "plugins": [],
    }
    print(json.dumps(init), flush=True)
    print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}), flush=True)
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text, "num_turns": 1}), flush=True)
    run_hooks(hook_files, "Stop")
    run_hooks(hook_files, "SessionEnd")
    if scenario == "grandchild":
        time.sleep(0.05)
    return 0


if __name__ == "__main__":
    sys.exit(main())
