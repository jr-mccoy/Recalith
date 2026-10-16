#!/usr/bin/env python3
"""Task 0b: probe real host delivery before engine construction.

Usage::

    python tools/probe_delivery.py --config LOCAL_CONFIG --output docs/host-compatibility.json

For each of the four delivery paths (session start, prompt, pre-action,
post-compaction) the probe installs a temporary, owned nonce-only stub hook
(``tools/fixtures/delivery_stub.py``) into a disposable workspace and runs the
SYSTEM_SPEC §9.3 protocol: three positive controls that inject a fresh 128-bit
nonce in one context item, and three negative controls that withhold it. A
positive passes only when the first eligible assistant text after the injection
contains the exact nonce; a successful hook process or stdout line is never
enough. A trial whose nonce reached the session through another channel
(prompt, tool output, workspace file, an unexpected tool) is rejected.

Modes:

* ``live`` runs real host sessions through the selected account route and
  model. Only live results can certify a path.
* ``request_capture`` points the installed host at a loopback recording
  endpoint and checks whether each injection reaches the outbound model
  request. It shows host-path feasibility without an account; it never counts
  as an echo pass.

Session start and prompt are required; pre-action and compaction are optional
and reported separately. Exit 0 when both required paths are healthy in live
mode, 4 when a required path is unavailable or could not be run, 8 when a
supported required path is degraded, 2 for invalid configuration. The provider
section of the report is preserved. No engine, memory database, or production
hook is used.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe_common as pc  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
STUB = Path(__file__).resolve().parent / "fixtures" / "delivery_stub.py"
SECTION = "delivery"
CONFIG_SCHEMA = 1
TOP_LEVEL = {"config_schema", "$comment", "provider", "delivery"}
MODES = ("request_capture", "live")
AUTH_KINDS = ("not_configured", "env_api_key", "env_oauth_token", "env_cloud")
PATHS = ("session_start", "prompt", "pre_action", "compact")
REQUIRED_PATHS = ("session_start", "prompt")
CONTROLS_PER_KIND = 3
FIXED_TOOL_COMMAND = "echo recalith-fixed-output"
FIXED_TOOL_OUTPUT = "recalith-fixed-output"
DUMMY_KEY = "recalith-probe-placeholder-not-a-credential"
UNSELECTED_MODEL = "recalith-probe-unselected-model"
NONCE_RE = re.compile(r"\b[0-9a-f]{32}\b")

CANARY_INSTRUCTION = (
    "If a canary value was supplied to you anywhere in your context, reply with exactly one line "
    "'CANARY <value>' using that value. Otherwise reply with exactly 'CANARY NONE'. Do not guess or invent a value."
)
PROMPTS = {
    "session_start": CANARY_INSTRUCTION,
    "prompt": CANARY_INSTRUCTION,
    "pre_action": (
        f"First run the shell command `{FIXED_TOOL_COMMAND}` once with the Bash tool and use no other tool. "
        "After it finishes, follow this instruction: " + CANARY_INSTRUCTION
    ),
}
COMPACT_TURNS = ("Reply with the single word OK.", "/compact", CANARY_INSTRUCTION)

# Claude Code 2.1.x event mapping for the stub. A similar name on another host
# or version is not certification; re-probe on change.
CLAUDE_HOOKS = {
    "session_start": ("SessionStart", "startup"),
    "prompt": ("UserPromptSubmit", None),
    "pre_action": ("PreToolUse", "Bash"),
    "compact": ("SessionStart", "compact"),
}

DEFAULTS: dict[str, Any] = {
    "expected_version": None,
    "model": None,
    "modes": ["request_capture", "live"],
    "session_args": [
        "-p", "--setting-sources", "local", "--strict-mcp-config",
        "--model", "{model}", "--output-format", "stream-json", "--verbose",
        "--allowedTools", f"Bash({FIXED_TOOL_COMMAND})",
    ],
    "multi_turn_args": ["--input-format", "stream-json"],
    "platform_env_keys": list(pc.DEFAULT_PLATFORM_ENV_KEYS),
    "network_env_keys": [],
    "nonsecret_env": {},
    "home_env": {"HOME": "{home}", "USERPROFILE": "{home}"},
    "request_capture_env": {
        "ANTHROPIC_BASE_URL": "{endpoint}",
        "ANTHROPIC_API_KEY": "{dummy_key}",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    },
    "host_markers": list(pc.DEFAULT_HOST_MARKERS),
    "limits": {},
}
DEFAULT_LIMITS = {"trial_timeout_seconds": 180, "capture_trial_timeout_seconds": 90, "hook_timeout_seconds": 10}
REQUIRED = ("host_id", "executable", "auth_route")


class ConfigError(ValueError):
    pass


# --------------------------------------------------------------------------
# Configuration


def _str_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{name} must be a list of strings")
    return list(value)


def _str_map(value: Any, name: str) -> dict[str, str]:
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ConfigError(f"{name} must be an object of string values")
    return dict(value)


def load_config(path: Path) -> dict[str, Any]:
    try:
        top = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except ValueError as exc:
        raise ConfigError(f"config is not valid JSON: {exc}") from exc
    if not isinstance(top, dict) or set(top) - TOP_LEVEL:
        raise ConfigError("config must be an object with config_schema, provider, delivery")
    if top.get("config_schema") != CONFIG_SCHEMA:
        raise ConfigError(f"config_schema must be {CONFIG_SCHEMA}")
    raw = top.get("delivery")
    if not isinstance(raw, dict):
        raise ConfigError("config has no delivery section")
    raw = {k: v for k, v in raw.items() if k != "$comment"}
    unknown = sorted(set(raw) - set(REQUIRED) - set(DEFAULTS))
    if unknown:
        raise ConfigError(f"unknown delivery fields: {unknown}")
    missing = [k for k in REQUIRED if k not in raw]
    if missing:
        raise ConfigError(f"missing delivery fields: {missing}")
    cfg = {**DEFAULTS, **raw}
    if not isinstance(cfg["host_id"], str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", cfg["host_id"]):
        raise ConfigError("host_id must be a lowercase identifier")
    if not isinstance(cfg["executable"], str) or not cfg["executable"]:
        raise ConfigError("executable must be a nonempty string")
    for key in ("expected_version", "model"):
        if cfg[key] is not None and not isinstance(cfg[key], str):
            raise ConfigError(f"{key} must be a string or null")
    for key in ("session_args", "multi_turn_args", "platform_env_keys", "network_env_keys", "host_markers", "modes"):
        cfg[key] = _str_list(cfg[key], key)
    if "{model}" not in cfg["session_args"]:
        raise ConfigError("session_args must pass the model through '{model}'")
    if not cfg["modes"] or any(m not in MODES for m in cfg["modes"]) or len(set(cfg["modes"])) != len(cfg["modes"]):
        raise ConfigError(f"modes must be a nonempty subset of {MODES}")
    for key in ("nonsecret_env", "home_env", "request_capture_env"):
        cfg[key] = _str_map(cfg[key], key)
    for key, value in cfg["nonsecret_env"].items():
        if key in cfg["host_markers"] or key in pc.ROLE_MARKERS:
            raise ConfigError(f"nonsecret_env may not set marker {key}")
        if pc._SECRETISH.search(value) or re.search(r"(KEY|TOKEN|SECRET|PASSWORD)", key, re.I):
            raise ConfigError(f"nonsecret_env must not carry credentials ({key})")
    limits = dict(DEFAULT_LIMITS)
    if not isinstance(cfg["limits"], dict):
        raise ConfigError("limits must be an object")
    for key, value in cfg["limits"].items():
        if key not in DEFAULT_LIMITS or not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ConfigError(f"invalid limit {key}")
        limits[key] = value
    cfg["limits"] = limits
    auth = cfg["auth_route"]
    if not isinstance(auth, dict) or set(auth) - {"kind", "billing", "env_keys", "description"}:
        raise ConfigError("auth_route must contain only kind, billing, env_keys, description")
    if auth.get("kind") not in AUTH_KINDS:
        raise ConfigError(f"auth_route.kind must be one of {AUTH_KINDS}")
    auth["env_keys"] = _str_list(auth.get("env_keys", []), "auth_route.env_keys")
    auth.setdefault("billing", "none")
    auth.setdefault("description", "")
    if (auth["kind"] == "not_configured") != (not auth["env_keys"]):
        raise ConfigError("auth_route env_keys must be empty exactly when kind is not_configured")
    if "live" in cfg["modes"] and auth["kind"] != "not_configured" and cfg["model"] is None:
        raise ConfigError("live mode with a configured route requires an explicit model")
    return cfg


# --------------------------------------------------------------------------
# Owned hook configuration


def _load_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _write_settings(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".recalith-probe.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def install_owned_hooks(settings_path: Path, entries: Sequence[tuple[str, str | None, str]], *, timeout_s: int) -> dict[str, Any]:
    """Append owned hook groups, preserving unrelated configuration.

    Returns an ownership manifest with the exact groups added and a canonical
    snapshot of the pre-install file so removal can prove nothing else moved.
    """
    before = _load_settings(settings_path)
    data = json.loads(json.dumps(before))
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("existing hooks setting is not an object")
    owned = []
    for event, matcher, command in entries:
        group: dict[str, Any] = {"hooks": [{"type": "command", "command": command, "timeout": timeout_s}]}
        if matcher is not None:
            group = {"matcher": matcher, **group}
        hooks.setdefault(event, []).append(group)
        owned.append({"event": event, "group": group})
    _write_settings(settings_path, data)
    return {
        "settings_path": str(settings_path),
        "before_digest": pc.sha256_bytes(pc.canonical_json(before)),
        "before": before,
        "owned": owned,
    }


def remove_owned_hooks(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Remove exactly the owned groups; report anything modified or missing."""
    path = Path(manifest["settings_path"])
    result = {"removed": 0, "missing": 0, "modified": 0, "unrelated_preserved": None}
    try:
        data = _load_settings(path)
    except (OSError, ValueError):
        result["error"] = "settings_unreadable"
        return result
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    for item in manifest["owned"]:
        groups = hooks.get(item["event"], [])
        if item["group"] in groups:
            groups.remove(item["group"])
            result["removed"] += 1
            continue
        command = item["group"]["hooks"][0]["command"]
        if any(command in json.dumps(g) for g in groups):
            result["modified"] += 1  # left in place for reconciliation
        else:
            result["missing"] += 1
    before = manifest["before"]
    before_hooks = before.get("hooks", {}) if isinstance(before.get("hooks"), dict) else {}
    for event in list(hooks):
        if not hooks[event] and event not in before_hooks:
            del hooks[event]
    if not hooks and "hooks" not in before:
        data.pop("hooks", None)
    _write_settings(path, data)
    if not before and not data:
        path.unlink()
    result["unrelated_preserved"] = pc.sha256_bytes(pc.canonical_json(data if path.exists() else {})) == manifest["before_digest"]
    return result


# --------------------------------------------------------------------------
# Stream parsing and trial evaluation


def parse_session_stream(stdout: bytes) -> dict[str, Any]:
    """Ordered assistant text, tool calls/results and compaction boundaries."""
    timeline: list[dict[str, Any]] = []
    errors: list[str] = []
    for line in stdout.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            errors.append("stream_line_not_json")
            continue
        if not isinstance(ev, dict):
            continue
        etype = ev.get("type")
        if etype == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    timeline.append({"kind": "text", "text": str(block.get("text", ""))})
                elif block.get("type") == "tool_use":
                    timeline.append({"kind": "tool_use", "name": block.get("name"), "input": block.get("input")})
        elif etype == "user":
            content = (ev.get("message") or {}).get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        timeline.append({"kind": "tool_result", "text": json.dumps(block.get("content"))})
        elif etype == "system" and ev.get("subtype") == "compact_boundary":
            timeline.append({"kind": "compact_boundary"})
        elif etype == "system" and ev.get("subtype") == "init":
            timeline.append({"kind": "init", "version": ev.get("claude_code_version"), "model": ev.get("model")})
        elif etype == "result":
            timeline.append({"kind": "result", "subtype": ev.get("subtype"), "is_error": ev.get("is_error")})
    return {"timeline": timeline, "errors": errors}


def eligible_text(path: str, timeline: Sequence[Mapping[str, Any]]) -> str | None:
    """First assistant text after the injection point for ``path``."""
    start = 0
    if path == "pre_action":
        idx = [i for i, e in enumerate(timeline) if e["kind"] == "tool_use"]
        if not idx:
            return None
        start = idx[0] + 1
    elif path == "compact":
        idx = [i for i, e in enumerate(timeline) if e["kind"] == "compact_boundary"]
        if not idx:
            return None
        start = idx[-1] + 1
    for e in timeline[start:]:
        if e["kind"] == "text" and e["text"].strip():
            return e["text"]
    return None


def evaluate_trial(spec: Mapping[str, Any], obs: Mapping[str, Any]) -> dict[str, Any]:
    """Judge one control. Pure function of the observation; no host access."""
    reasons: list[str] = []
    nonce = spec["nonce"]
    path = spec["path"]
    if not obs.get("launched") or obs.get("timed_out") or obs.get("launch_error"):
        return {"valid": False, "passed": False, "reasons": ["launch_failed"]}
    timeline = obs.get("timeline", [])
    emissions = [h for h in obs.get("hook_records", []) if h.get("emitted")]
    target_fired = [h for h in obs.get("hook_records", []) if h.get("path") == path]
    # Contamination: the nonce may only arrive through the injected context item.
    contaminated = []
    if nonce in " ".join(obs.get("prompts", [])):
        contaminated.append("nonce_in_prompt")
    if any(e["kind"] == "tool_result" and nonce in e["text"] for e in timeline):
        contaminated.append("nonce_in_tool_output")
    if obs.get("workspace_files_with_nonce"):
        contaminated.append("nonce_in_workspace_file")
    other = set(obs.get("other_trial_nonces", []))
    if any(e["kind"] == "text" and any(o in e["text"] for o in other) for e in timeline):
        contaminated.append("other_trial_nonce_in_response")
    expected_tools = 1 if path == "pre_action" else 0
    tool_uses = [e for e in timeline if e["kind"] == "tool_use"]
    bad_tools = [e for e in tool_uses if not (path == "pre_action" and e.get("name") == "Bash" and FIXED_TOOL_COMMAND in json.dumps(e.get("input")))]
    if bad_tools or len(tool_uses) > expected_tools:
        contaminated.append("unexpected_tool_use")
    if path == "compact" and not any(e["kind"] == "compact_boundary" for e in timeline):
        return {"valid": False, "passed": False, "reasons": ["compaction_not_triggered"] + contaminated}
    if path == "pre_action" and not tool_uses:
        return {"valid": False, "passed": False, "reasons": ["fixture_tool_not_called"] + contaminated}
    if spec["kind"] == "negative" and emissions:
        contaminated.append("negative_control_injected")
    if spec["kind"] == "negative" and obs.get("transcript_contains_nonce"):
        contaminated.append("nonce_in_negative_transcript")
    if contaminated:
        return {"valid": False, "passed": False, "reasons": sorted(set(contaminated))}
    text = eligible_text(path, timeline)
    if spec["kind"] == "positive":
        if not target_fired:
            return {"valid": True, "passed": False, "reasons": ["hook_not_fired"]}
        if not any(h.get("emitted") and h.get("path") == path for h in emissions):
            return {"valid": True, "passed": False, "reasons": ["stub_did_not_emit"]}
        if text is None:
            return {"valid": True, "passed": False, "reasons": ["no_eligible_assistant_text"]}
        if nonce not in text:
            # The hook ran and printed context, but the model did not see it:
            # a stdout-only success is not delivery.
            return {"valid": True, "passed": False, "reasons": ["stdout_only_no_model_echo"]}
        return {"valid": True, "passed": True, "reasons": reasons}
    if any(e["kind"] == "text" and nonce in e["text"] for e in timeline):
        return {"valid": True, "passed": False, "reasons": ["fabricated_withheld_nonce"]}
    if text is None:
        return {"valid": True, "passed": False, "reasons": ["no_eligible_assistant_text"]}
    return {"valid": True, "passed": True, "reasons": reasons}


def evaluate_path(path: str, trials: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """healthy | degraded | unavailable | not_run for one delivery path."""
    required = path in REQUIRED_PATHS
    if not trials:
        return {"state": "not_run", "required": required, "positives_passed": 0, "negatives_passed": 0, "reasons": ["not_run"]}
    pos = [t for t in trials if t["kind"] == "positive"]
    neg = [t for t in trials if t["kind"] == "negative"]
    pos_ok = sum(1 for t in pos if t["verdict"]["valid"] and t["verdict"]["passed"])
    neg_ok = sum(1 for t in neg if t["verdict"]["valid"] and t["verdict"]["passed"])
    reasons = sorted({r for t in trials for r in t["verdict"]["reasons"]})
    if pos and all(t["verdict"]["reasons"] == ["hook_not_fired"] for t in pos):
        state = "unavailable"
    elif pos and all(set(t["verdict"]["reasons"]) & {"compaction_not_triggered", "fixture_tool_not_called"} for t in pos):
        state = "unavailable"
    elif len(pos) == CONTROLS_PER_KIND and len(neg) == CONTROLS_PER_KIND and pos_ok == CONTROLS_PER_KIND and neg_ok == CONTROLS_PER_KIND:
        state = "healthy"
    else:
        state = "degraded"
    return {"state": state, "required": required, "positives_passed": pos_ok, "negatives_passed": neg_ok, "positives_run": len(pos), "negatives_run": len(neg), "reasons": reasons}


def exit_code_for(paths: Mapping[str, Mapping[str, Any]]) -> int:
    states = [paths[p]["state"] for p in REQUIRED_PATHS]
    if all(s == "healthy" for s in states):
        return pc.EXIT_CERTIFIED
    if any(s in ("unavailable", "not_run") for s in states):
        return pc.EXIT_UNAVAILABLE
    return pc.EXIT_DEGRADED


# --------------------------------------------------------------------------
# Host driver


class Workspace:
    """Disposable owned fixture workspace plus private probe state."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.workspace = base / "workspace"
        self.state = base / "probe-state"  # outside the workspace: plan + stub log
        self.homes = base / "homes"
        self.plan = self.state / "plan.json"
        self.log = self.state / "stub-log.jsonl"
        self.settings = self.workspace / ".claude" / "settings.local.json"
        self.unrelated = {
            "permissions": {"deny": ["Read(./unrelated-fixture.txt)"]},
            "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": f"{json.dumps(sys.executable)} -I -c pass"}]}]},
        }

    def create(self) -> None:
        for d in (self.workspace / ".claude", self.state, self.homes):
            d.mkdir(parents=True, exist_ok=True)
        (self.workspace / "README.txt").write_text("Disposable Recalith delivery-probe workspace.\n", encoding="utf-8")
        (self.workspace / "unrelated-fixture.txt").write_text("unrelated\n", encoding="utf-8")
        _write_settings(self.settings, self.unrelated)
        git = shutil.which("git")
        if git:
            pc.run_bounded([git, "init", "-q", str(self.workspace)], env={"PATH": os.environ.get("PATH", "")}, cwd=self.base, stdin_data=b"", timeout_s=30)

    def hook_entries(self) -> list[tuple[str, str | None, str]]:
        entries = []
        for path, (event, matcher) in CLAUDE_HOOKS.items():
            cmd = " ".join(json.dumps(x) for x in (sys.executable, "-I", str(STUB), "--plan", str(self.plan), "--log", str(self.log), "--path", path))
            entries.append((event, matcher, cmd))
        return entries

    def files_containing(self, nonce: str) -> list[str]:
        hits = []
        for p in self.workspace.rglob("*"):
            if p.is_file() and ".git" not in p.relative_to(self.workspace).parts:
                try:
                    if nonce in p.read_text(encoding="utf-8", errors="replace"):
                        hits.append(str(p.relative_to(self.workspace)))
                except OSError:
                    continue
        return sorted(hits)

    def hook_records(self, trial_id: str) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        out = []
        for line in self.log.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("trial_id") == trial_id:
                out.append(rec)
        return out


class Driver:
    def __init__(self, cfg: dict[str, Any], ws: Workspace, exe: str) -> None:
        self.cfg = cfg
        self.ws = ws
        self.exe = exe

    def env(self, home: Path, mode: str, endpoint: str | None) -> dict[str, str]:
        subst = {"{home}": str(home), "{endpoint}": endpoint or "", "{dummy_key}": DUMMY_KEY}

        def fill(v: str) -> str:
            for k, s in subst.items():
                v = v.replace(k, s)
            return v

        inherited = dict(os.environ)
        keys = list(self.cfg["platform_env_keys"])
        if mode == "live":
            keys += self.cfg["network_env_keys"] + self.cfg["auth_route"]["env_keys"]
        child = {k: inherited[k] for k in keys if k in inherited}
        child.update({k: fill(v) for k, v in self.cfg["home_env"].items()})
        child.update(self.cfg["nonsecret_env"])
        if mode == "request_capture":
            child.update({k: fill(v) for k, v in self.cfg["request_capture_env"].items()})
        # The probe session is a top-level host session, not a nested child.
        for marker in list(self.cfg["host_markers"]) + list(pc.ROLE_MARKERS):
            child.pop(marker, None)
        return child

    def run_trial(self, spec: Mapping[str, Any], mode: str, endpoint: pc.RecordingEndpoint | None, other_nonces: Sequence[str]) -> dict[str, Any]:
        home = self.ws.homes / spec["trial_id"]
        home.mkdir(parents=True, exist_ok=True)
        plan = {"trial_id": spec["trial_id"], "inject_path": spec["path"] if spec["kind"] == "positive" else None, "nonce": spec["nonce"] if spec["kind"] == "positive" else None}
        self.ws.plan.write_text(json.dumps(plan), encoding="utf-8")
        model = self.cfg["model"] or UNSELECTED_MODEL
        argv = [self.exe] + [a.replace("{model}", model) for a in self.cfg["session_args"]]
        if spec["path"] == "compact":
            argv += self.cfg["multi_turn_args"]
            prompts = list(COMPACT_TURNS)
            stdin = "".join(json.dumps({"type": "user", "message": {"role": "user", "content": t}}) + "\n" for t in prompts)
        else:
            prompts = [PROMPTS[spec["path"]]]
            stdin = prompts[0]
        timeout = self.cfg["limits"]["trial_timeout_seconds" if mode == "live" else "capture_trial_timeout_seconds"]
        seen = len(endpoint.snapshot()) if endpoint else 0
        run = pc.run_bounded(argv, env=self.env(home, mode, endpoint.url if endpoint else None), cwd=self.ws.workspace, stdin_data=stdin.encode(), timeout_s=timeout)
        self.ws.plan.write_text(json.dumps({"trial_id": None, "inject_path": None, "nonce": None}), encoding="utf-8")
        parsed = parse_session_stream(run.stdout)
        transcripts = list((home / ".claude" / "projects").rglob("*.jsonl")) if (home / ".claude" / "projects").exists() else []
        transcript_text = "".join(p.read_text(encoding="utf-8", errors="replace") for p in transcripts)
        obs: dict[str, Any] = {
            "launched": True,
            "timed_out": run.timed_out,
            "launch_error": run.stdout_overflow or (run.returncode not in (0, None) and not parsed["timeline"]),
            "process": run.to_report(),
            "timeline": parsed["timeline"],
            "stream_errors": parsed["errors"],
            "hook_records": self.ws.hook_records(spec["trial_id"]),
            "prompts": prompts,
            "workspace_files_with_nonce": self.ws.files_containing(spec["nonce"]),
            "other_trial_nonces": list(other_nonces),
            "transcript_files": len(transcripts),
            "transcript_contains_nonce": spec["nonce"] in transcript_text if transcripts else None,
        }
        if endpoint is not None:
            reqs = pc.message_requests(endpoint.snapshot()[seen:])
            obs["request_count"] = len(reqs)
            obs["requests_with_nonce"] = [i for i, r in enumerate(reqs) if spec["nonce"] in json.dumps({k: r.get(k) for k in ("system", "messages")})]
        return obs


def capture_responder(body: Mapping[str, Any]) -> tuple[str, Any]:
    """Loopback 'model': requests the fixture tool once, otherwise says NONE.

    It never echoes a nonce, so request-capture runs cannot pass the echo test.
    """
    messages = body.get("messages") or []
    text = json.dumps(messages)
    if FIXED_TOOL_COMMAND in text and "tool_result" not in text:
        return "tool_use", {"name": "Bash", "input": {"command": FIXED_TOOL_COMMAND, "description": "Recalith probe fixture"}}
    return "text", "CANARY NONE"


def summarize_trial(spec: Mapping[str, Any], obs: Mapping[str, Any], verdict: Mapping[str, Any] | None, mode: str) -> dict[str, Any]:
    timeline = obs.get("timeline", [])
    eligible = eligible_text(spec["path"], timeline)
    rec: dict[str, Any] = {
        "trial_id": spec["trial_id"],
        "path": spec["path"],
        "kind": spec["kind"],
        "nonce_sha256": pc.sha256_bytes(spec["nonce"].encode()),
        "process": obs.get("process"),
        "hook_records": [{k: h.get(k) for k in ("path", "event", "source", "tool_name", "emitted")} for h in obs.get("hook_records", [])],
        "tool_uses": [e.get("name") for e in timeline if e["kind"] == "tool_use"],
        "compact_boundary_seen": any(e["kind"] == "compact_boundary" for e in timeline),
        "eligible_response_sha256": pc.sha256_bytes(eligible.encode()) if eligible is not None else None,
        "eligible_response_contains_nonce": (spec["nonce"] in eligible) if eligible is not None else None,
        "transcript_contains_nonce": obs.get("transcript_contains_nonce"),
        "workspace_files_with_nonce": obs.get("workspace_files_with_nonce"),
    }
    if mode == "live":
        rec["verdict"] = verdict
        # The exact response is retained as evidence: it echoes only a fresh
        # random nonce or 'CANARY NONE' from a disposable fixture session.
        rec["eligible_response_excerpt"] = eligible[:200] if eligible is not None else None
        rec["host_version"] = next((e.get("version") for e in timeline if e["kind"] == "init"), None)
        rec["model"] = next((e.get("model") for e in timeline if e["kind"] == "init"), None)
    else:
        rec["request_count"] = obs.get("request_count")
        rec["requests_with_nonce"] = obs.get("requests_with_nonce")
    return rec


def capture_path_state(path: str, trials: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pos = [t for t in trials if t["kind"] == "positive"]
    neg = [t for t in trials if t["kind"] == "negative"]
    fired = [t for t in pos if any(h["path"] == path and h["emitted"] for h in t["hook_records"])]
    visible = [t for t in fired if t["requests_with_nonce"]]
    clean_neg = [t for t in neg if not t["requests_with_nonce"] and not any(h["emitted"] for h in t["hook_records"])]
    if not fired:
        state = "hook_not_fired"
    elif len(visible) == len(pos) == CONTROLS_PER_KIND and len(clean_neg) == len(neg) == CONTROLS_PER_KIND:
        state = "request_visible"
    elif not visible:
        state = "not_in_request"
    else:
        state = "partial"
    return {"state": state, "positives_hook_emitted": len(fired), "positives_visible_in_request": len(visible), "negatives_clean": len(clean_neg), "note": "Request-level feasibility only; never an echo pass or certification."}


def run_mode(cfg: dict[str, Any], ws: Workspace, exe: str, mode: str) -> dict[str, Any]:
    driver = Driver(cfg, ws, exe)
    specs = []
    for path in PATHS:
        for kind in ("positive", "negative"):
            for i in range(CONTROLS_PER_KIND):
                specs.append({"trial_id": f"{mode}-{path}-{kind}-{i + 1}", "path": path, "kind": kind, "nonce": secrets.token_hex(16)})
    manifest = install_owned_hooks(ws.settings, ws.hook_entries(), timeout_s=cfg["limits"]["hook_timeout_seconds"])
    results: list[dict[str, Any]] = []
    try:
        ep_cm = pc.RecordingEndpoint(capture_responder) if mode == "request_capture" else None
        if ep_cm is not None:
            ep_cm.__enter__()
        try:
            for spec in specs:
                others = [s["nonce"] for s in specs if s is not spec]
                obs = driver.run_trial(spec, mode, ep_cm, others)
                verdict = evaluate_trial(spec, obs) if mode == "live" else None
                results.append(summarize_trial(spec, obs, verdict, mode))
        finally:
            if ep_cm is not None:
                ep_cm.__exit__(None, None, None)
    finally:
        cleanup = remove_owned_hooks(manifest)
    by_path = {p: [r for r in results if r["path"] == p] for p in PATHS}
    if mode == "live":
        paths = {p: evaluate_path(p, [{"kind": r["kind"], "verdict": r["verdict"]} for r in by_path[p]]) for p in PATHS}
    else:
        paths = {p: capture_path_state(p, by_path[p]) for p in PATHS}
    return {"paths": paths, "trials": results, "owned_hook_cleanup": cleanup}


# --------------------------------------------------------------------------
# Entry point


def probe_delivery(config_path: Path, output_path: Path, *, keep_workspace: bool = False) -> int:
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        return pc.die_usage(str(exc))
    exe = cfg["executable"]
    resolved = exe if os.path.isabs(exe) else shutil.which(exe)
    base = Path(tempfile.mkdtemp(prefix="recalith-delivery-probe-"))
    sanitizer = pc.Sanitizer({str(base): "<workspace-root>", str(Path.home()): "<home>", str(REPO_ROOT): "<repo>"}, secrets=[os.environ.get(k, "") for k in cfg["auth_route"]["env_keys"]])
    report: dict[str, Any] = {
        "probe": "tools/probe_delivery.py",
        "probe_schema": 1,
        "tested_at": pc.utc_now(),
        "platform": pc.platform_facts(),
        "host_id": cfg["host_id"],
        "engine_build": None,
        "stub": {"path": "tools/fixtures/delivery_stub.py", "sha256": pc.sha256_file(STUB), "note": "Nonce-only feasibility stub; Task 13 must recertify with the real engine, fences, budgets and accounting."},
        "configured_model": cfg["model"],
        "auth_route": {"kind": cfg["auth_route"]["kind"], "billing": cfg["auth_route"]["billing"], "selected_env_key_names": cfg["auth_route"]["env_keys"], "description": cfg["auth_route"]["description"]},
        "protocol": {
            "controls_per_kind": CONTROLS_PER_KIND,
            "required_paths": list(REQUIRED_PATHS),
            "optional_paths": [p for p in PATHS if p not in REQUIRED_PATHS],
            "hook_mapping": {p: {"event": e, "matcher": m} for p, (e, m) in CLAUDE_HOOKS.items()},
            "nonce": "fresh 128-bit hex per trial; only the SHA-256 is reported",
            "eligible_text": "first assistant text after the injection point (session start/prompt: first text; pre-action: after the fixture tool call; compact: after the compaction boundary)",
            "prompt_sha256": {k: pc.sha256_bytes(v.encode()) for k, v in PROMPTS.items()},
        },
    }
    try:
        if resolved is None or not os.path.exists(resolved):
            report.update({"verdict": "unavailable", "paths": {p: {"state": "unavailable", "required": p in REQUIRED_PATHS, "reasons": ["executable_missing"]} for p in PATHS}})
            pc.merge_report_section(output_path, SECTION, cfg["host_id"], sanitizer.value(report))
            print(json.dumps({"verdict": "unavailable", "reason": "executable_missing"}))
            return pc.EXIT_UNAVAILABLE
        ws = Workspace(base)
        ws.create()
        report["invocation"] = {"executable": resolved, "executable_sha256": pc.sha256_file(Path(os.path.realpath(resolved))), "session_args": cfg["session_args"], "multi_turn_args": cfg["multi_turn_args"], "cwd": "<workspace-root>/workspace (disposable git checkout)"}
        vrun = pc.run_bounded([resolved, "--version"], env=Driver(cfg, ws, resolved).env(ws.homes, "request_capture", "http://127.0.0.1:9"), cwd=ws.workspace, stdin_data=b"", timeout_s=30)
        observed_version = vrun.stdout.decode("utf-8", "replace").strip()[:200] or None
        report["host_version"] = {"observed": observed_version, "expected": cfg["expected_version"]}
        version_ok = observed_version is not None and (not cfg["expected_version"] or cfg["expected_version"] in observed_version)
        if "request_capture" in cfg["modes"]:
            report["request_capture"] = run_mode(cfg, ws, resolved, "request_capture")
        live_reason = None
        if "live" in cfg["modes"]:
            missing = [k for k in cfg["auth_route"]["env_keys"] if k not in os.environ]
            if cfg["auth_route"]["kind"] == "not_configured":
                live_reason = "no_auth_route_configured"
            elif missing:
                live_reason = "selected_auth_env_missing"
            elif not version_ok:
                live_reason = "host_version_mismatch"
            else:
                report["live"] = run_mode(cfg, ws, resolved, "live")
        else:
            live_reason = "live mode not selected in config"
        if live_reason is not None:
            report["live"] = {"status": "not_run", "reason": live_reason}
            paths = {p: {"state": "not_run", "required": p in REQUIRED_PATHS, "reasons": [live_reason]} for p in PATHS}
        else:
            paths = report["live"]["paths"]
        report["paths"] = paths
        code = exit_code_for(paths)
        report["verdict"] = {pc.EXIT_CERTIFIED: "required_paths_healthy", pc.EXIT_UNAVAILABLE: "required_path_unavailable", pc.EXIT_DEGRADED: "required_path_degraded"}[code]
        report["certification_scope"] = "Stub feasibility for this host/model/config only; not product readiness."
        pc.merge_report_section(output_path, SECTION, cfg["host_id"], sanitizer.value(report))
        print(json.dumps({"verdict": report["verdict"], "paths": {p: v["state"] for p, v in paths.items()}}))
        return code
    finally:
        if keep_workspace:
            print(f"workspace kept at {base}", file=sys.stderr)
        else:
            shutil.rmtree(base, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--keep-workspace", action="store_true")
    ns = parser.parse_args(argv)
    return probe_delivery(ns.config, ns.output, keep_workspace=ns.keep_workspace)


if __name__ == "__main__":
    sys.exit(main())
