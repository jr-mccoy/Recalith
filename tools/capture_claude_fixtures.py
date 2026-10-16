#!/usr/bin/env python3
"""Capture sanitized real Claude Code hook payloads and transcript boundaries.

    python tools/capture_claude_fixtures.py [--executable claude] [--output tests/fixtures/hosts/claude]
    python tools/capture_claude_fixtures.py --record-only 2.1.301 --report docs/host-compatibility.json

The installed Claude Code CLI runs scripted sessions in a disposable, owned
fixture workspace with a private ``HOME``. Owned capture-only recorder hooks
(``tools/fixtures/hook_recorder.py``) are appended to the workspace's
``.claude/settings.local.json`` next to deliberately planted unrelated settings,
and removed afterwards (also on failure) with the Task 0b ownership manifest.

Model responses come from a **loopback scripted endpoint** with a placeholder
key (Task 0 request-capture mode), so tool, subagent and compaction hooks fire
without any account. The fixtures are therefore labeled ``request_capture``:
real host hook payloads and transcript structure, but scripted model turns and
no live certification. This session's own host credentials and proxy are never
used: the child environment is built fresh from an allowlist.

Output: ``<output>/<version>/`` with ``manifest.json``, ``<scenario>.hooks.jsonl``
(exact hook stdin per firing, sanitized) and ``<scenario>.transcript.jsonl``
(sanitized transcript boundary records; non-message records are reduced to
type skeletons because they carry host system prompts and request blobs).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe_common as pc  # noqa: E402
import probe_delivery as pd  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RECORDER = Path(__file__).resolve().parent / "fixtures" / "hook_recorder.py"
PLACEHOLDER_KEY = "recalith-probe-placeholder-not-a-credential"
SCRIPTED_MODEL = "recalith-fixture-scripted-model"

# Every hook event name registered by the recorder. Names that never fire in
# these scenarios are reported as "registered, not observed", not unsupported.
HOOK_EVENTS = (
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest",
    "PermissionDenied", "Notification", "Stop", "StopFailure", "SubagentStart", "SubagentStop", "PreCompact",
    "PostCompact", "SessionEnd", "InstructionsLoaded", "ConfigChange", "CwdChanged", "FileChanged",
    "TaskCreated", "TaskCompleted", "Elicitation", "ElicitationResult",
)
TOOL_EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest", "PermissionDenied"}

# Output sizes chosen around the measured 2.1.301 host caps: successful Bash
# stdout is head-capped at 30,000 characters; failing output is that capped text
# middle-truncated to about 10,000 characters with a visible marker.
FIXTURE_TESTS = {
    "test_long.py": "def test_end():\n    for i in range(900):\n        print(f\"progress line {i:04d} \" + \"x\" * 40)\n    assert 1 + 1 == 3, \"fixture failure at the very end\"\n",
    "test_mid.py": "def test_mid():\n    for i in range(400):\n        print(f\"progress line {i:04d} \" + \"x\" * 40)\n    assert 1 + 1 == 3, \"fixture failure after mid-size output\"\n",
    "test_pass.py": "def test_pass():\n    for i in range(400):\n        print(f\"progress line {i:04d} \" + \"x\" * 40)\n",
}
SECRET_PROMPT = "FIXTURE secret: remember password=fixture-hunter2-not-real and reply OK."


def _tool(name: str, **inp: Any) -> tuple[str, Any]:
    return "tool_use", {"name": name, "input": inp}


def lifecycle_steps(ws: Path) -> list[tuple[str, Any]]:
    return [
        _tool("Bash", command="echo hello-fixture", description="fixture success"),
        _tool("Bash", command="pytest -q test_long.py", description="fixture long failing test (host loses the tail)"),
        _tool("Bash", command="pytest -q test_mid.py", description="fixture mid-size failing test (tail survives)"),
        _tool("Bash", command="pytest -q -s test_pass.py", description="fixture long passing test"),
        _tool("Bash", command="seq 1 12000", description="fixture output above the host stdout cap"),
        _tool("Bash", command="grep -c nomatch notes.txt", description="fixture no-match exit 1"),
        _tool("Read", file_path=str(ws / "notes.txt")),
        _tool("Read", file_path=str(ws / "missing.txt")),
        _tool("Write", file_path=str(ws / "new.txt"), content="alpha\n"),
        _tool("Edit", file_path=str(ws / "new.txt"), old_string="alpha", new_string="beta"),
        _tool("Bash", command="ls /nonexistent-recalith-fixture-dir", description="fixture exit 2"),
        _tool("Bash", command="sleep 5", description="fixture timeout", timeout=1000),
        _tool("Bash", command='printf "%s\\n" "ok" | tr a-z A-Z', description="fixture pipeline"),
    ]


SCENARIOS: dict[str, dict[str, Any]] = {
    "lifecycle": {
        "turns": ["FIXTURE lifecycle: run the scripted tools.", "/compact", "Reply OK."],
        "allowed": ["Bash", "Read", "Write", "Edit"],
        "description": "start, prompts, Bash success/failure/no-match/timeout/pipeline, Read success/failure, Write, Edit, manual compaction, stop and end",
    },
    "subagent": {
        "turns": ["FIXTURE subagent: delegate the scripted task."],
        "allowed": ["Bash", "Agent", "Task"],
        "description": "a subagent that runs one tool, then stops",
    },
    "denied": {
        "turns": ["FIXTURE denied: run the scripted tool."],
        "allowed": ["Read"],
        "description": "a Bash call that the permission configuration denies in non-interactive mode",
    },
    "secret_and_resume": {
        "turns": [SECRET_PROMPT, "/clear", "Reply OK."],
        "allowed": [],
        "resume_of": "lifecycle",
        "description": "resumed session, a credential-shaped prompt and /clear",
    },
}


def responder_for(ws: Path) -> Callable[[dict], tuple[str, Any]]:
    steps = lifecycle_steps(ws)

    def respond(body: dict) -> tuple[str, Any]:
        messages = body.get("messages") or []
        text = json.dumps(messages)
        system = json.dumps(body.get("system"))
        if "detailed summary" in text.lower() or "detailed summary" in system.lower():
            return "text", "SUMMARY: scripted fixture conversation."
        results = text.count('"tool_result"')
        first = json.dumps(messages[0]) if messages else ""
        if "SUBAGENT-TASK" in first:
            return (_tool("Bash", command="echo from-subagent", description="subagent fixture") if results == 0 else ("text", "subagent done"))
        if "FIXTURE lifecycle" in text and results < len(steps):
            return steps[results]
        if "FIXTURE subagent" in text and results == 0:
            return _tool("Agent", description="fixture subagent", prompt="SUBAGENT-TASK: run the scripted echo.", subagent_type="general-purpose")
        if "FIXTURE denied" in text and results == 0:
            return _tool("Bash", command="touch denied.txt", description="fixture denied call")
        return "text", "OK fixture reply"

    return respond


# --------------------------------------------------------------------------
# Sanitization


class Placeholders:
    def __init__(self, pairs: Mapping[str, str]) -> None:
        self.pairs = sorted(((k, v) for k, v in pairs.items() if k), key=lambda kv: len(kv[0]), reverse=True)

    def text(self, value: str) -> str:
        for old, new in self.pairs:
            value = value.replace(old, new)
        return value

    def value(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.text(obj)
        if isinstance(obj, list):
            return [self.value(v) for v in obj]
        if isinstance(obj, dict):
            return {self.text(k): self.value(v) for k, v in obj.items()}
        return obj


MESSAGE_TYPES = {"user", "assistant", "system", "summary"}
KEPT_FIELDS = ("type", "subtype", "uuid", "parentUuid", "logicalParentUuid", "promptId", "sessionId", "isSidechain", "isMeta", "toolUseResult", "version", "cwd")


def transcript_boundaries(path: Path, placeholders: Placeholders) -> list[dict[str, Any]]:
    """Message records kept (sanitized); other record types reduced to skeletons."""
    out = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        record = json.loads(raw_line)
        if record.get("type") in MESSAGE_TYPES:
            kept = {k: record[k] for k in KEPT_FIELDS if k in record}
            if isinstance(record.get("message"), dict):
                kept["message"] = {k: record["message"][k] for k in ("role", "content") if k in record["message"]}
            out.append(placeholders.value(kept))
        else:
            out.append({"type": record.get("type"), "recalith_fixture_skeleton": True, "fields": sorted(record)})
    return out


# --------------------------------------------------------------------------
# Running scenarios


def child_env(home: Path, endpoint: str) -> dict[str, str]:
    env = {k: os.environ[k] for k in pc.DEFAULT_PLATFORM_ENV_KEYS if k in os.environ}
    env.update({"HOME": str(home), "USERPROFILE": str(home), "ANTHROPIC_BASE_URL": endpoint, "ANTHROPIC_API_KEY": PLACEHOLDER_KEY, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
    venv_bin = REPO_ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    env["PATH"] = os.pathsep.join([str(venv_bin), env.get("PATH", os.defpath)])
    for marker in (*pc.DEFAULT_HOST_MARKERS, *pc.ROLE_MARKERS):
        env.pop(marker, None)
    return env


def session_argv(exe: str, allowed: list[str], resume: str | None) -> list[str]:
    argv = [exe, "-p", "--setting-sources", "local", "--strict-mcp-config", "--model", SCRIPTED_MODEL,
            "--output-format", "stream-json", "--verbose", "--input-format", "stream-json"]
    if allowed:
        argv += ["--allowedTools", *allowed]
    if resume:
        argv += ["--resume", resume]
    return argv


def stdin_turns(turns: list[str]) -> bytes:
    return "".join(json.dumps({"type": "user", "message": {"role": "user", "content": t}}) + "\n" for t in turns).encode()


def make_workspace(base: Path) -> tuple[Path, Path]:
    ws, home = base / "workspace", base / "home"
    (ws / ".claude").mkdir(parents=True)
    home.mkdir()
    (ws / "notes.txt").write_text("fixture notes\n", encoding="utf-8")
    for name, body in FIXTURE_TESTS.items():
        (ws / name).write_text(body, encoding="utf-8")
    git = shutil.which("git")
    if git:
        subprocess.run([git, "init", "-q", str(ws)], check=False, env={"PATH": os.environ.get("PATH", "")})
    return ws, home


def unrelated_settings() -> dict[str, Any]:
    return {
        "permissions": {"deny": ["Read(./unrelated-fixture.txt)"]},
        "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": f"{json.dumps(sys.executable)} -I -c pass"}]}]},
    }


def recorder_entries(log: Path) -> list[tuple[str, str | None, str]]:
    entries = []
    for event in HOOK_EVENTS:
        command = " ".join(json.dumps(x) for x in (sys.executable, "-I", str(RECORDER), "--log", str(log), "--event", event))
        entries.append((event, "*" if event in TOOL_EVENTS else None, command))
    return entries


def run_scenario(exe: str, name: str, ws: Path, home: Path, endpoint: str, resume: str | None, timeout_s: float = 180) -> dict[str, Any]:
    spec = SCENARIOS[name]
    run = pc.run_bounded(session_argv(exe, spec["allowed"], resume), env=child_env(home, endpoint), cwd=ws, stdin_data=stdin_turns(spec["turns"]), timeout_s=timeout_s)
    parsed = pd.parse_session_stream(run.stdout)
    session_id = None
    for line in run.stdout.decode("utf-8", "replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("session_id"):
            session_id = ev["session_id"]
            break
    return {"returncode": run.returncode, "timed_out": run.timed_out, "session_id": session_id, "timeline_kinds": [e["kind"] for e in parsed["timeline"]], "stderr_bytes": len(run.stderr)}


def claude_version(exe: str) -> str | None:
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False).stdout
    match = re.search(r"(\d+\.\d+\.\d+)", out)
    return match.group(1) if match else None


def capture(exe: str, output: Path) -> int:
    version = claude_version(exe)
    if version is None:
        print("capture_claude_fixtures: could not read the host version", file=sys.stderr)
        return 4
    base = Path(tempfile.mkdtemp(prefix="recalith-claude-fixture-"))
    ws, home = make_workspace(base)
    log = base / "hooks.jsonl"
    settings = ws / ".claude" / "settings.local.json"
    pd._write_settings(settings, unrelated_settings())
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(ws))
    host_tmp = Path(tempfile.gettempdir()) / f"claude-{os.getuid()}" if hasattr(os, "getuid") else None
    placeholders = Placeholders({str(host_tmp or ""): "<host-tmp>", tempfile.gettempdir(): "<tmp>", str(ws): "<workspace>", slug: "<workspace-slug>", str(home): "<home>", str(base): "<fixture-root>", str(REPO_ROOT): "<repo>", sys.executable: "<python>", str(Path.home()): "<user-home>"})
    manifest = pd.install_owned_hooks(settings, recorder_entries(log), timeout_s=10)
    results: dict[str, Any] = {}
    sessions: dict[str, str] = {}
    offsets: dict[str, tuple[int, int]] = {}
    try:
        with pc.RecordingEndpoint(responder_for(ws)) as endpoint:
            for name, spec in SCENARIOS.items():
                start = len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0
                resume = sessions.get(spec.get("resume_of", ""))
                results[name] = run_scenario(exe, name, ws, home, endpoint.url, resume)
                if results[name]["session_id"]:
                    sessions[name] = results[name]["session_id"]
                end = len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0
                offsets[name] = (start, end)
    finally:
        cleanup = pd.remove_owned_hooks(manifest)
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    target = output / version
    target.mkdir(parents=True, exist_ok=True)
    observed: dict[str, dict[str, int]] = {}
    written: set[str] = set()
    for name, (start, end) in offsets.items():
        with open(target / f"{name}.hooks.jsonl", "w", encoding="utf-8", newline="\n") as fh:
            for seq, rec in enumerate(records[start:end]):
                payload = json.loads(rec["stdin"])
                fh.write(json.dumps({"seq": seq, "event": rec["event"], "transcript_bytes": rec["transcript_bytes"], "payload": placeholders.value(payload)}, ensure_ascii=False, sort_keys=True) + "\n")
                observed.setdefault(name, {})
                observed[name][rec["event"]] = observed[name].get(rec["event"], 0) + 1
        session = sessions.get(name)
        transcripts = list(home.rglob(f"{session}.jsonl")) if session else []
        if transcripts and session not in written:
            written.add(session)
            files = [(f"{name}.transcript.jsonl", transcripts[0])]
            # Subagent transcripts are separate files under <session>/subagents/.
            files += [(f"{name}.{sub.stem}.transcript.jsonl", sub) for sub in sorted((transcripts[0].parent / session / "subagents").glob("agent-*.jsonl"))]
            for file_name, source in files:
                with open(target / file_name, "w", encoding="utf-8", newline="\n") as fh:
                    for rec in transcript_boundaries(source, placeholders):
                        fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    fired = {event for counts in observed.values() for event in counts}
    report = {
        "fixture_schema": 1,
        "host": "claude_code",
        "host_version": version,
        "captured_at": pc.utc_now(),
        "mode": "request_capture",
        "mode_note": "Real installed-host hook payloads and transcript structure; model turns came from a loopback scripted endpoint with a placeholder key. Not a live certification and not evidence of model-visible delivery.",
        "platform": pc.platform_facts(),
        "method": {
            "tool": "tools/capture_claude_fixtures.py",
            "recorder": "tools/fixtures/hook_recorder.py",
            "settings_scope": "workspace .claude/settings.local.json (--setting-sources local)",
            "session_args": session_argv("claude", ["<allowed tools>"], None)[1:],
        },
        "scenarios": {name: {**{k: v for k, v in SCENARIOS[name].items() if k != "turns"}, "turns": [placeholders.text(t) for t in SCENARIOS[name]["turns"]], "result": results.get(name), "events": observed.get(name, {})} for name in SCENARIOS},
        "events_observed": sorted(fired),
        "events_registered_not_observed": sorted(set(HOOK_EVENTS) - fired),
        "owned_hook_cleanup": cleanup,
        "sanitization": "Fixture paths replaced by <workspace>, <workspace-slug>, <home>, <host-tmp>, <tmp>, <fixture-root>, <repo>, <python>, <user-home>; transcript non-message records reduced to type skeletons; no credentials (placeholder key only, never sent to hooks).",
    }
    (target / "manifest.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    shutil.rmtree(base, ignore_errors=True)
    leaked = [p for p in target.iterdir() if str(base) in p.read_text(encoding="utf-8") or PLACEHOLDER_KEY in p.read_text(encoding="utf-8")]
    if leaked:
        print(f"capture_claude_fixtures: unsanitized content in {leaked}", file=sys.stderr)
        return 1
    print(json.dumps({"version": version, "observed": report["events_observed"], "not_observed": report["events_registered_not_observed"], "cleanup": cleanup}))
    return 0 if cleanup.get("unrelated_preserved") else 1


def capability_record(fixture_dir: Path) -> dict[str, Any]:
    """The host-registry entry (SYSTEM_SPEC §9.2) derived from committed fixtures and the adapter."""
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from recalith.fast import claude_capture

    manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))
    mapped = sorted(claude_capture.ROLES)
    return {
        "adapter_id": claude_capture.ADAPTER_ID,
        "adapter_module": "src/recalith/fast/claude_capture.py",
        "capture_state": "capture_only",
        "certified_capture_versions": sorted(claude_capture.CERTIFIED_VERSIONS),
        "observed_version": manifest["host_version"],
        "transcript_parser": claude_capture.TRANSCRIPT_PARSER,
        "evidence_mode": manifest["mode"],
        "evidence_note": manifest["mode_note"],
        "fixtures": str(fixture_dir.relative_to(REPO_ROOT)).replace(os.sep, "/"),
        "captured_at": manifest["captured_at"],
        "platform": manifest["platform"],
        "event_roles": dict(sorted(claude_capture.ROLES.items())),
        "events_observed": manifest["events_observed"],
        "events_observed_unmapped": sorted(set(manifest["events_observed"]) - set(mapped)),
        "events_registered_not_observed": manifest["events_registered_not_observed"],
        "unsupported_event_handling": "explicit content-free coverage gap (spool/gaps), no guessed mapping",
        "unknown_version_handling": "capture-only conservative mode: no user/tool authority, no version-specific exit-code parsing, parser coverage incomplete",
        "delivery": "unavailable in this build (Task 12b adds the branch; Task 13 certifies paths)",
        "host_output_limits": {
            "bash_stdout_head_cap_chars": 30000,
            "bash_failure_error_chars": "about 10000, middle-truncated with '... [N characters truncated] ...'",
            "flagged_as": "coverage.truncated + missing_context, warning host_output_truncated",
        },
        "latency": "docs/measurements/hook-latency-capture-only.json",
        "owned_hook_cleanup": manifest["owned_hook_cleanup"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--executable", default="claude")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "tests" / "fixtures" / "hosts" / "claude")
    parser.add_argument("--record-only", metavar="VERSION", help="skip capture; merge the capture registry entry for these committed fixtures into --report")
    parser.add_argument("--report", type=Path, default=REPO_ROOT / "docs" / "host-compatibility.json")
    args = parser.parse_args(argv)
    if args.record_only:
        pc.merge_report_section(args.report, "capture", "claude_code", capability_record(args.output / args.record_only))
        return 0
    exe = args.executable if os.path.isabs(args.executable) else shutil.which(args.executable)
    if not exe:
        print("capture_claude_fixtures: Claude Code CLI not found", file=sys.stderr)
        return 4
    return capture(exe, args.output)


if __name__ == "__main__":
    sys.exit(main())
