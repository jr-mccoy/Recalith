"""Test-only builders for Task 13: Claude Code integration (decision 0019).

Real inputs: ``recalith integrate claude`` and ``integrate claude --remove``
run as real child processes of the guarded CLI with an **explicitly
provisioned fixture token** (``cli_scenarios.token``, the evaluation/CI
bootstrap input; never committed); the installed hook commands are run
exactly as Claude Code runs them (``sh -c COMMAND`` with
``CLAUDE_PROJECT_DIR`` and the host marker, which 2.1.305 sets for hooks);
hook payloads are the real sanitized 2.1.301/2.1.305 fixtures; the hook is
the real ``python -I -m recalith.fast.entry`` behind the project launcher on
a provisioned runtime (``cli_scenarios.provision_runtime``).

**Synthetic states** (named at each use, never production evidence):

- :func:`fake_claude` is an executable named ``claude`` that only answers
  ``--version`` with the given host version: the installer asks the host for
  its version and nothing else; no host session runs here (the real host is
  ``tests/platform/test_claude_smoke.py``).
- :func:`live_record` writes a *controlled* ``.recalith/host.json``
  (``HostCertification``) claiming a live nonce certification that did not run
  here; ``request_capture_record`` writes the record the request-capture
  certification really produces.
- Unrelated host settings (permission rules, an unrelated hook, a theme) are
  planted fixtures in a disposable workspace under the test's temporary
  directory; no real user settings are read or written.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

import cli_scenarios as cs  # first: puts tests/, tests/integration and tests/platform on sys.path
import claude_fixtures as cf  # noqa: E402
from recalith.contracts.common import digest_of  # noqa: E402

SETTINGS = Path(".claude") / "settings.local.json"
OWNERSHIP = Path(".recalith") / "run" / "integrations" / "claude_code.json"
HOST_FILE = Path(".recalith") / "host.json"
MANIFEST = Path(".recalith") / "run" / "hook-context.json"
VERSION = "2.1.305"
DELIVERY_PATHS = ("session_start", "prompt", "pre_action", "compact_restore")
LAUNCHER_MARK = ".recalith/bin/recalith-hook"

# Planted unrelated settings in Claude Code's own on-disk format (two-space JSON).
UNRELATED = {
    "permissions": {"allow": ["Bash(npm test:*)"], "deny": ["Read(./secrets/**)", "Bash(rm -rf:*)"], "defaultMode": "default"},
    "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "echo unrelated-user-hook"}]}], "Notification": [{"hooks": [{"type": "command", "command": "true"}]}]},
    "theme": "dark",
}


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(root.parent), "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, env=env, timeout=60, check=False)


def has_git() -> bool:
    return shutil.which("git") is not None


def fake_claude(directory: Path, version: str = VERSION) -> Path:
    """Synthetic: an executable named ``claude`` that only answers ``--version``."""
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        exe = directory / "claude.cmd"
        exe.write_text(f"@echo {version} (Claude Code)\r\n", encoding="utf-8")
    else:
        exe = directory / "claude"
        exe.write_text(f"#!/bin/sh\necho '{version} (Claude Code)'\n", encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return exe


def project(tmp: Path, name: str = "integrate", *, git_repo: bool = True, unrelated: dict[str, Any] | None = UNRELATED, raw: bytes | None = None) -> Path:
    """A real installation in a disposable workspace, a git checkout with planted unrelated host settings."""
    root = cs.init_project(tmp, name)
    if git_repo and has_git():
        git(root, "init", "-q")
    if raw is not None or unrelated is not None:
        (root / SETTINGS).parent.mkdir(parents=True, exist_ok=True)
        (root / SETTINGS).write_bytes(raw if raw is not None else (json.dumps(unrelated, indent=2) + "\n").encode("utf-8"))
    return root


class Operator:
    """The guarded CLI as a real child process, with a provisioned fixture token and a synthetic ``claude`` on PATH."""

    def __init__(self, root: Path, tmp: Path, *, version: str = VERSION) -> None:
        self.root = root
        self.token_path = tmp / f"{root.name}-op.token"
        if not self.token_path.exists():
            cs.register(root, cs.token(self.token_path))
        self.bin = tmp / f"{root.name}-hostbin"
        fake_claude(self.bin, version)

    def set_version(self, version: str) -> None:
        fake_claude(self.bin, version)

    def env(self, **extra: str) -> dict[str, str]:
        return cs.base_env(PATH=os.pathsep.join([str(self.bin), os.environ.get("PATH", "")]), **extra)

    def run(self, *args: str, env: dict[str, str] | None = None, token: bool = True) -> cs.Result:
        argv = list(args) + (["--operator-token-file", str(self.token_path)] if token else []) + ["--json"]
        return cs.cli(self.root, *argv, env=env or self.env())

    def integrate(self, *extra: str, **kw: Any) -> cs.Result:
        return self.run("integrate", "claude", *extra, **kw)

    def remove(self, **kw: Any) -> cs.Result:
        return self.run("integrate", "claude", "--remove", **kw)


def settings(root: Path) -> dict[str, Any]:
    return json.loads((root / SETTINGS).read_text(encoding="utf-8"))


def owned_groups(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for event, groups in (data.get("hooks") or {}).items():
        for group in groups:
            if any(LAUNCHER_MARK in h.get("command", "") for h in group.get("hooks", [])):
                out.setdefault(event, []).append(group)
    return out


def without_owned(data: dict[str, Any], deny: Iterable[str]) -> dict[str, Any]:
    """The settings minus Recalith's owned hook groups and deny rules (for semantic comparisons)."""
    out = json.loads(json.dumps(data))
    for event in list((out.get("hooks") or {})):
        out["hooks"][event] = [g for g in out["hooks"][event] if not any(LAUNCHER_MARK in h.get("command", "") for h in g.get("hooks", []))]
        if not out["hooks"][event]:
            del out["hooks"][event]
    owned = set(deny)
    if "permissions" in out and "deny" in out["permissions"]:
        out["permissions"]["deny"] = [r for r in out["permissions"]["deny"] if r not in owned]
    return out


def ownership(root: Path) -> dict[str, Any] | None:
    path = root / OWNERSHIP
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def manifest(root: Path) -> dict[str, Any] | None:
    path = root / MANIFEST
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def live_record(root: Path, installation_id: str, *, version: str = VERSION, delivery: dict[str, str] | None = None, mode: str = "live", command_rules: str = "installed", private_paths: str = "probed_limited") -> Path:
    """Synthetic: a ``HostCertification`` claiming a live nonce certification that did not run here."""
    states = {"session_start": "certified", "prompt": "certified", "pre_action": "unavailable", "compact_restore": "unavailable"}
    states.update(delivery or {})
    record = {
        "certification_schema": 1, "installation_id": installation_id, "host_id": "claude_code", "host_version": version, "mode": mode,
        "certified_at": "2026-10-21T00:00:00.000000Z", "report_digest": digest_of(["synthetic host certification", version, mode]),
        "delivery": states, "command_rules": command_rules, "private_paths": private_paths,
    }
    path = root / HOST_FILE
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True))
    return path


# --------------------------------------------------------------------------
# The installed hook commands, run as the host runs them


def installed_command(root: Path, event: str) -> str:
    """The exact command string the installed settings register for ``event``."""
    (group,) = owned_groups(settings(root))[event]
    (hook,) = group["hooks"]
    return hook["command"]


def host_env(root: Path, **extra: str) -> dict[str, str]:
    """What Claude Code 2.1.305 gives a hook process (observed): its own marker and the project directory."""
    return cf.child_env(CLAUDECODE="1", CLAUDE_PROJECT_DIR=str(root), **extra)


def run_installed(root: Path, event: str, payload: bytes, *, env: dict[str, str] | None = None, cwd: Path | None = None, reply: Path | None = None) -> subprocess.CompletedProcess:
    """Run the installed command through ``sh -c`` like the host (POSIX; Windows host execution is uncertified)."""
    command = installed_command(root, event)
    if reply is not None:
        command += " --reply-file " + json.dumps(str(reply))
    return subprocess.run(["sh", "-c", command], input=payload, capture_output=True, env=env or host_env(root), cwd=cwd or root, timeout=60, check=False)


def fixture_records(version: str, scenario: str) -> list[dict[str, Any]]:
    path = cf.ROOT / "tests" / "fixtures" / "hosts" / "claude" / version / f"{scenario}.hooks.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class Payloads(cf.Replay):
    """Fixture payload materialization for an installation that already exists at ``root``."""

    def __init__(self, root: Path, tmp: Path) -> None:  # noqa: D107 - no init of a new installation
        self.root = root
        self.home = tmp / f"{root.name}-home"
        self.home.mkdir(exist_ok=True)
        self.host_tmp = tmp / f"{root.name}-host-tmp"
        self.host_tmp.mkdir(exist_ok=True)
        self.slug = "-replay-workspace"


def response(proc: subprocess.CompletedProcess) -> dict[str, Any] | None:
    """The single host JSON object on stdout, or None when stdout is empty."""
    text = proc.stdout.decode("utf-8")
    if not text.strip():
        return None
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 1, text
    obj = json.loads(lines[0])
    assert isinstance(obj, dict)
    return obj


BLOCKING_KEYS = ("decision", "permissionDecision", "continue", "stopReason", "updatedInput", "reason")


def never_blocks(proc: subprocess.CompletedProcess) -> None:
    """A hook result Claude Code treats as nonblocking success: exit 0, and at most context and a user notice."""
    assert proc.returncode == 0, (proc.returncode, proc.stderr[-2000:])
    obj = response(proc)
    if obj is None:
        return
    assert set(obj) <= {"hookSpecificOutput", "systemMessage"}, obj
    specific = obj.get("hookSpecificOutput") or {}
    assert set(specific) <= {"hookEventName", "additionalContext"}, specific
    assert not any(k in json.dumps(obj) for k in ('"permissionDecision"', '"decision"')), obj


def python_on_path() -> dict[str, str]:
    """An environment whose ``python`` runs this interpreter (for module spellings)."""
    return {"PATH": os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")])}
