"""Evaluation arms and their trial manifests (ACCEPTANCE_TESTS §6, §6.1; decision 0020).

Preview compares exactly two arms per smoke scenario, one fresh trial each:

* ``no_memory`` — the clean no-memory baseline: the seed project with its
  normal files and tools, **no Recalith installation**, no supplied notes, and
  host-native automatic memory disabled.
* ``candidate`` — the same seed with its own fresh, independent Recalith
  installation (initialized noninteractively with an operator/CI-provisioned
  pre-init token file, or the labeled test-fixture route in a recorded run),
  host-native automatic memory disabled, and no memory-maintenance
  instruction to the agent.

Breadcrumbs and the notes baseline are full-release comparisons and are not
run for preview (their absence is intentional, not missing data).

Every trial manifest records the effective native-memory setting, the
inherited instructions and the retrieval services the working agent could
reach. A trial whose native memory is not observed disabled, or whose
workspace or home carries inherited instructions or a retrieval service the
arm does not intend, is labeled **contaminated** and is never reported as
"no memory" (ACCEPTANCE_TESTS §6).

The effective setting is *observed*, not assumed: :func:`observe_native_memory`
launches the installed Claude Code CLI against a loopback recording endpoint
with a placeholder key (request capture: no account, no model) and a planted
``MEMORY.md`` sentinel, once with the disabling settings and once without
(the positive control). Only "control saw it, disabled run did not" is
``disabled``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARMS = ("candidate", "no_memory")
NOT_RUN = {"breadcrumbs": "full release only (ACCEPTANCE_TESTS §6.1)", "notes": "full release only (ACCEPTANCE_TESTS §6.1)"}
# The disabling configuration for Claude Code's automatic memory, applied in the disposable HOME and environment.
DISABLE_SETTINGS = {"autoMemoryEnabled": False}
DISABLE_ENV = {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
INSTRUCTION_FILES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", ".claude/CLAUDE.md")
PLACEHOLDER_KEY = "placeholder" + "-request-capture-" + "not-a-credential"


def _slug(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def prepare_home(home: Path) -> Path:
    """A disposable private HOME with host-native automatic memory disabled; returns its settings file."""
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(DISABLE_SETTINGS, indent=1) + "\n", encoding="utf-8")
    return settings


def inherited_instructions(ws: Path, home: Path) -> list[str]:
    """Instruction and customization files the working agent would inherit (relative names only)."""
    found = []
    for base, label in ((ws, "workspace"), (home, "home")):
        for name in INSTRUCTION_FILES:
            if (base / name).exists():
                found.append(f"{label}:{name}")
        for sub in ("skills", "agents", "commands"):
            if (base / ".claude" / sub).is_dir() and any((base / ".claude" / sub).iterdir()):
                found.append(f"{label}:.claude/{sub}")
    memory = home / ".claude" / "projects"
    if memory.is_dir():
        found += [f"home:native_memory:{p.parent.parent.name[:24]}" for p in memory.glob("*/memory/MEMORY.md")]
    return sorted(found)


def retrieval_services(ws: Path, home: Path) -> list[str]:
    """MCP or other retrieval services configured for the working agent (names of their config files)."""
    out = []
    for path in (ws / ".mcp.json", home / ".claude.json", ws / ".claude" / "settings.json", ws / ".claude" / "settings.local.json", home / ".claude" / "settings.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("mcpServers"):
            out.append(f"{path.name}:mcpServers")
    return out


def observe_native_memory(executable: str | None, *, timeout: float = 90.0, session_args: list[str] | None = None) -> dict[str, Any]:
    """Observe whether the installed host loads a planted native-memory sentinel, with and without the disabling settings.

    Request capture only: a loopback endpoint and a placeholder key; no
    account, model or credential of this session is used. ``session_args``
    are the live trials' own session flags (``evals/live.py``), so the
    observation is of the configuration the trials run; the prompt then goes
    in on standard input, as in those trials.
    """
    if not executable:
        return {"state": "not_observed", "reason": "host_executable_missing"}
    sys.path.insert(0, str(ROOT / "tools"))
    import probe_common as pc  # noqa: E402 - the Task 0 recorder

    version = None
    try:
        version = subprocess.run([executable, "--version"], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return {"state": "not_observed", "reason": "host_executable_unrunnable"}
    out: dict[str, Any] = {"host_version": version, "method": "request capture (loopback endpoint, placeholder key); planted MEMORY.md sentinel"}
    with tempfile.TemporaryDirectory(prefix="recalith-native-memory-") as tmp:
        for arm, disable in (("control", False), ("disabled", True)):
            base = Path(tmp) / arm
            home, ws = base / "home", base / "ws"
            ws.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(ws)], check=False, capture_output=True)
            sentinel = f"RECALITH_NATIVE_MEMORY_SENTINEL_{arm.upper()}_7f3a"
            for where in {ws, ws.resolve()}:
                mem = home / ".claude" / "projects" / _slug(where) / "memory" / "MEMORY.md"
                mem.parent.mkdir(parents=True, exist_ok=True)
                mem.write_text(f"- Remember {sentinel}\n", encoding="utf-8")
            env = {k: os.environ[k] for k in (*pc.DEFAULT_PLATFORM_ENV_KEYS, "TMPDIR", "TEMP", "TMP") if k in os.environ}
            env.update(HOME=str(home), USERPROFILE=str(home), ANTHROPIC_API_KEY=PLACEHOLDER_KEY, NO_PROXY="127.0.0.1,localhost", DISABLE_AUTOUPDATER="1", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
            if disable:
                prepare_home(home)
                env.update(DISABLE_ENV)
            with pc.RecordingEndpoint(lambda body: ("text", "OK")) as ep:
                env["ANTHROPIC_BASE_URL"] = ep.url
                argv = [executable, "-p", "Reply OK.", "--output-format", "json"] if session_args is None else [executable, *session_args]
                try:
                    proc = subprocess.run(argv, cwd=ws, env=env, input=None if session_args is None else "Reply OK.", capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False)
                    code = proc.returncode
                except subprocess.TimeoutExpired:
                    code = None
                bodies = pc.message_requests(ep.snapshot())
            out[arm] = {"exit": code, "message_requests": len(bodies), "sentinel_seen": sentinel in json.dumps(bodies)}
    control, disabled = out["control"], out["disabled"]
    if not control["message_requests"] or not disabled["message_requests"]:
        out["state"] = "not_observed"
        out["reason"] = "no_model_request_captured"
    elif not control["sentinel_seen"]:
        out["state"] = "detector_unvalidated"  # the control did not load the sentinel: absence proves nothing
    elif disabled["sentinel_seen"]:
        out["state"] = "not_disableable"  # a contaminated configuration: never a clean no-memory run
    else:
        out["state"] = "disabled"
    out["configuration"] = {"settings": DISABLE_SETTINGS, "env": sorted(DISABLE_ENV), "session_args": "default (-p PROMPT --output-format json)" if session_args is None else "the live trials' session flags"}
    return out


def manifest(arm: str, *, mode: str, ws: Path, home: Path, native_memory: dict[str, Any], installation: dict[str, Any] | None, agent: dict[str, Any]) -> dict[str, Any]:
    """The trial manifest's arm section; ``label`` is ``no_memory`` only for a verified clean baseline."""
    instructions = inherited_instructions(ws, home)
    services = retrieval_services(ws, home)
    if mode == "scripted":
        # The scripted agent is a fixed policy with no host-native memory of its own; nothing is loaded behind its back.
        effective = {"state": "not_applicable", "reason": "scripted agent: no host session, no host-native memory"}
        clean_memory = True
    else:
        effective = native_memory
        clean_memory = native_memory.get("state") == "disabled"
    intended_recalith = arm == "candidate"
    has_recalith = installation is not None
    contaminated = (not clean_memory) or bool(instructions) or bool(services) or (has_recalith != intended_recalith)
    reasons = []
    if not clean_memory:
        reasons.append(f"native_memory_{effective.get('state')}")
    if instructions:
        reasons.append("inherited_instructions")
    if services:
        reasons.append("retrieval_services")
    if has_recalith != intended_recalith:
        reasons.append("installation_mismatch")
    label = ("contaminated" if contaminated else arm)
    return {
        "arm": arm, "label": label, "contamination": reasons, "native_memory": effective, "inherited_instructions": instructions,
        "retrieval_services": services, "recalith_installation": installation, "agent": agent, "memory_maintenance_instructions": [],
    }
