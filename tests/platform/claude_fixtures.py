"""Replay of the sanitized real Claude Code 2.1.301 hook fixtures (test helper).

``tests/fixtures/hosts/claude/2.1.301/*.hooks.jsonl`` holds the exact hook
stdin the installed host produced (paths replaced by placeholders). Replay
puts the placeholders back as real temporary paths, sizes each session's
transcript file to the byte length the recorder observed when the hook fired,
and runs the real entry point in a fresh interpreter, exactly as the hook
launcher would.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from recalith.capture.hooks import write_hook_context
from recalith.contracts.common import Actor
from recalith.contracts.config import ProjectConfig
from recalith.core import identity

ROOT = Path(__file__).resolve().parents[2]
VERSION = "2.1.301"
FIXTURES = ROOT / "tests" / "fixtures" / "hosts" / "claude" / VERSION
ADAPTER_ACTOR = Actor(kind="adapter", id="claude-hook", channel="hook")
PROJECT_ID = "proj_99999999-9999-4999-8999-999999999999"
SRC = str(ROOT / "src")
# The release profile new fixture installations get. Full-profile tests (decision 0024) set it to "full" for one
# test with monkeypatch; ``init --release-profile full`` itself stays refused until the full release (Cut 2).
RELEASE_PROFILE = "claude_preview"


def records(scenario: str) -> list[dict[str, Any]]:
    path = FIXTURES / f"{scenario}.hooks.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def manifest() -> dict[str, Any]:
    return json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


class Replay:
    """A project installation plus the host-side paths the fixtures refer to."""

    def __init__(self, tmp: Path, *, host_version: str | None = VERSION, init: bool = True) -> None:
        self.root = tmp / "project"
        self.root.mkdir(parents=True)
        self.home = tmp / "home"
        self.home.mkdir()
        self.host_tmp = tmp / "host-tmp"
        self.host_tmp.mkdir()
        if init:
            identity.initialize_installation(self.root, ProjectConfig.defaults_for(PROJECT_ID, release_profile=RELEASE_PROFILE))
            self.ctx = identity.resolve_installation(self.root, actor=ADAPTER_ACTOR)
            write_hook_context(self.ctx, adapter_id="claude_code", host_version=host_version)
        self.slug = "-replay-workspace"

    def placeholders(self) -> dict[str, str]:
        return {"<workspace-slug>": self.slug, "<workspace>": str(self.root), "<home>": str(self.home), "<host-tmp>": str(self.host_tmp), "<tmp>": str(self.host_tmp), "<repo>": str(ROOT), "<python>": sys.executable, "<user-home>": str(self.home)}

    def payload(self, record: dict[str, Any]) -> dict[str, Any]:
        text = json.dumps(record["payload"], ensure_ascii=False)
        for placeholder, real in self.placeholders().items():
            text = text.replace(placeholder, json.dumps(real)[1:-1])
        return json.loads(text)

    def prepare(self, record: dict[str, Any]) -> bytes:
        """Materialize one hook payload; size its transcript as recorded."""
        payload = self.payload(record)
        path = payload.get("transcript_path")
        if isinstance(path, str):
            transcript = Path(path)
            if record["transcript_bytes"] is None:
                transcript.unlink(missing_ok=True)
            else:
                transcript.parent.mkdir(parents=True, exist_ok=True)
                with open(transcript, "ab") as fh:
                    fh.truncate(record["transcript_bytes"])
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def hook_command(root: Path, event: str | None = None, reply: Path | None = None) -> list[str]:
    argv = [sys.executable, "-I", "-m", "recalith.fast.entry", "--project", str(root), "claude_code"]
    if event:
        argv += ["--event", event]
    if reply:
        argv += ["--reply-file", str(reply)]
    return argv


def child_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("RECALITH_", "CLAUDE"))}
    env.pop("PYTHONPATH", None)
    env.update(extra)
    return env


def run_hook(root: Path, data: bytes, *, event: str | None = None, reply: Path | None = None, env: dict[str, str] | None = None) -> tuple[subprocess.CompletedProcess, float]:
    """Run the real entry in a fresh process; returns (process, wall seconds)."""
    start = time.perf_counter()
    proc = subprocess.run(hook_command(root, event, reply), input=data, capture_output=True, env=child_env() if env is None else env, timeout=60, check=False)
    return proc, time.perf_counter() - start


def replay(replayer: Replay, scenario: str, tmp: Path) -> list[dict[str, Any]]:
    """Replay every hook of ``scenario``; returns the reply per hook."""
    replies = []
    for record in records(scenario):
        reply_path = tmp / f"reply-{scenario}-{record['seq']}.json"
        proc, _ = run_hook(replayer.root, replayer.prepare(record), event=record["event"], reply=reply_path)
        assert proc.returncode == 0 and proc.stdout == b"" and proc.stderr == b"", (record["event"], proc.stderr[-2000:])
        replies.append(json.loads(reply_path.read_text(encoding="utf-8")))
    return replies
