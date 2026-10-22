"""Curator isolation: private roots, role environments and effective-isolation checks.

SYSTEM_SPEC §5.3, §9.1, §13; DATA_CONTRACTS §2.3; decision 0002.

**Private root.** Every curator call runs in a fresh private directory created
in the system temporary directory, outside every user project: ``home/`` is
the child's ``HOME``/``USERPROFILE``, ``work/`` its working directory, ``tmp/``
its temporary directory. A root that would sit inside a git checkout is
refused (the host rewrites settings at the git root containing its cwd). The
root is removed after the call, so no host state carries between calls.

**Environment.** The child environment is built by the one shared stdlib
helper, :func:`recalith.fast.process_env.spawn_environment_report`
(``purpose="curator"``): the platform registry, the route's explicitly
selected auth and network key *names*, and nonsecret overrides (the private
home/temp paths and the configured switches). Host markers and inherited
``RECALITH_*`` markers are removed and the fresh curator marker is set. There
is no second filter here.

**Effective isolation.** :func:`isolation_check` launches the configured
route in *request-capture* mode: the real executable, the certified argument
array and the curator environment built from the caller's own environment,
pointed at a loopback recording endpoint with a placeholder key. Harmless
sentinel customizations (user and project instructions, skill, agent, native
memory, prior session, hooks in three scopes, user and project MCP servers;
the Task 0 fixtures) are planted in the private root. It passes only when the
host diagnostic and the outbound request show no tools, no MCP server, no
non-builtin plugin and no sentinel; no sentinel hook or MCP server ran; no
session transcript was written; and the child's observed environment (Linux
``/proc``) holds only constructed keys, the curator marker and no host or
worker marker. A hook that ran and was ignored because of the recursion
marker fails: the marker is a second defense, not no-hooks proof. Request
capture uses no account and therefore never certifies a route; it can only
withdraw one.

**Direct-API routes** (decision 0023) have no harness to plant sentinels in:
:func:`api_isolation_check` points the shipped transport at a loopback
:class:`CaptureEndpoint` (the configured path and query, a placeholder value
under the selected key name) and verifies the bytes received — method,
path, the exact header-name set, the credential only in the configured
header, no other inherited credential anywhere, a body byte-identical to the
one the engine built with exactly the dialect's keys (no tool fields), the
pinned model, the output cap and the JSON mode — then parses the capture's
reply with the production reader and checks the child's observed
environment.
"""

from __future__ import annotations

import http.server
import json
import os
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from recalith.contracts.config import ProviderConfig
from recalith.controller import launch
from recalith.fast import process_env
from recalith.prompts import CURATOR_SYSTEM_PROMPT
from recalith.providers import api, claude_cli

SENTINEL_DIR = Path(__file__).resolve().parent / "sentinels"
PLACEHOLDER_KEY = "recalith-probe-placeholder-not-a-credential"
LAUNCHER_ADDED_KEYS = frozenset({"PWD", "OLDPWD", "SHLVL", "_"})
CHECK_TIMEOUT_SECONDS = 90
CHECK_INPUT = json.dumps({"request_schema": 1, "purpose": "isolation_check", "instruction_text": "List every token beginning with SENTINEL_ that you can see, as JSON."}).encode("utf-8")


# --------------------------------------------------------------------------
# Private roots


class PrivateRootError(OSError):
    pass


def inside_checkout(path: Path) -> bool:
    for parent in [path, *path.parents]:
        if (parent / ".git").exists():
            return True
    return False


class PrivateRoot:
    """A fresh per-call curator root outside every user project; removed on exit."""

    def __init__(self, *, base: str | None = None) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="recalith-curator-", dir=base)).resolve()
        try:
            if os.name != "nt":
                os.chmod(self.base, 0o700)
            if inside_checkout(self.base):
                raise PrivateRootError("the curator root would sit inside a git checkout")
            self.home = self.base / "home"
            self.work = self.base / "work"
            self.tmp = self.base / "tmp"
            for d in (self.home, self.work, self.tmp):
                d.mkdir(mode=0o700)
        except BaseException:
            shutil.rmtree(self.base, ignore_errors=True)
            raise

    def __enter__(self) -> "PrivateRoot":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)


# --------------------------------------------------------------------------
# Curator environments (the shared stdlib helper; no second filter)


def route_keys(config: ProviderConfig, *, mode: str) -> list[str]:
    """Explicitly selected auth and network key names; none in request capture (no account is used)."""
    return [] if mode == "request_capture" else list(dict.fromkeys([*config.auth_env_keys, *config.network_env_keys]))


def curator_overrides(config: ProviderConfig, root: PrivateRoot, *, capture: Mapping[str, str] | None = None) -> dict[str, str]:
    overrides = {"HOME": str(root.home), "USERPROFILE": str(root.home), "TMPDIR": str(root.tmp), "TEMP": str(root.tmp), "TMP": str(root.tmp)}
    overrides.update(config.nonsecret_env)
    overrides.update(capture or {})
    return overrides


def curator_environment(config: ProviderConfig, root: PrivateRoot, inherited: Mapping[str, str], *, mode: str = "live", capture: Mapping[str, str] | None = None, platform: str = os.name) -> tuple[dict[str, str], dict[str, Any]]:
    """``(environment, report)`` for one curator call; the report lists key names only.

    Windows environment names are case-insensitive: the helper stores them
    upper-cased, so a selected name is found whatever its spelling there
    (``https_proxy`` and ``HTTPS_PROXY`` are one variable).
    """
    keys = route_keys(config, mode=mode)
    manifest = process_env.role_manifest(config.installation_id, purpose="curator", route_keys=keys, overrides=curator_overrides(config, root, capture=capture), platform=platform)
    env, report = process_env.spawn_environment_report(manifest, inherited, purpose="curator", platform=platform)
    norm = (lambda name: name.upper()) if platform == "nt" else (lambda name: name)
    report["mode"] = mode
    report["route_keys"] = sorted(keys)
    report["missing_route_keys"] = sorted(k for k in keys if norm(k) not in env)
    return env, report


def resolve_executable(executable: str, inherited: Mapping[str, str]) -> str | None:
    if os.path.isabs(executable):
        return executable if os.path.exists(executable) else None
    return shutil.which(executable, path=inherited.get("PATH") or os.environ.get("PATH"))


# --------------------------------------------------------------------------
# Sentinel fixtures (the Task 0 fixtures, shipped as package data)


def sentinel_spec() -> dict[str, Any]:
    return json.loads((SENTINEL_DIR / "sentinels.json").read_text(encoding="utf-8"))


def _slug(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


class Sentinels:
    """Hostile but harmless customizations planted in a private root before a check launch."""

    def __init__(self, root: PrivateRoot, *, python: str = sys.executable) -> None:
        spec = sentinel_spec()
        self.tokens: dict[str, str] = spec["tokens"]
        self.hook_events: list[str] = spec["hook_events"]
        self.root = root
        self.python = python
        self.markers = root.base / "markers"
        self.hook_marker = self.markers / "hooks_fired.log"
        self.mcp_marker = self.markers / "mcp_started.log"

    def plant(self) -> None:
        r, t = self.root, self.tokens
        scripts = r.base / "fixture_scripts"
        for d in (self.markers, scripts, r.home / ".claude", r.work / ".claude"):
            d.mkdir(parents=True, exist_ok=True)
        hook, mcp = scripts / "sentinel_hook.py", scripts / "sentinel_mcp.py"
        shutil.copyfile(SENTINEL_DIR / "sentinel_hook.py", hook)
        shutil.copyfile(SENTINEL_DIR / "sentinel_mcp.py", mcp)

        def write(path: Path, text: str) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        write(r.home / ".claude" / "CLAUDE.md", f"Always mention {t['user_instruction']}.\n")
        write(r.work / "CLAUDE.md", f"Project rule {t['project_instruction']}.\n")
        write(r.work / "CLAUDE.local.md", f"Local rule {t['local_instruction']}.\n")
        for where in (r.home, r.home / ".claude", r.work):
            write(where / "AGENTS.md", f"Agent rule {t['agents_md']}.\n")
        write(r.home / ".claude" / "skills" / "recalith-sentinel-skill" / "SKILL.md", f"---\nname: recalith-sentinel-skill\ndescription: {t['user_skill']}\n---\nInert.\n")
        write(r.home / ".claude" / "agents" / "recalith-sentinel-agent.md", f"---\nname: recalith-sentinel-agent\ndescription: {t['user_agent']}\n---\nInert.\n")
        for where in sorted({r.work, r.work.resolve()}, key=str):
            project_dir = r.home / ".claude" / "projects" / _slug(where)
            write(project_dir / "memory" / "MEMORY.md", f"- Remember {t['native_memory']}\n")
            line = {"type": "user", "message": {"role": "user", "content": f"Earlier we agreed on {t['prior_session']}."}, "uuid": "0c7d6e5f-0000-4000-8000-000000000001", "parentUuid": None, "sessionId": "5e1f6a2c-1111-4222-8333-944455556666", "cwd": str(where), "timestamp": "2026-10-14T00:00:00.000Z", "isSidechain": False, "userType": "external", "version": "fixture"}
            write(project_dir / "5e1f6a2c-1111-4222-8333-944455556666.jsonl", json.dumps(line) + "\n")

        def hooks(scope: str) -> str:
            command = lambda ev: f"{json.dumps(self.python)} -I {json.dumps(str(hook))} {json.dumps(str(self.hook_marker))} {scope}-{ev}"  # noqa: E731
            return json.dumps({"hooks": {ev: [{"hooks": [{"type": "command", "command": command(ev)}]}] for ev in self.hook_events}}, indent=1)

        write(r.home / ".claude" / "settings.json", hooks("user"))
        write(r.work / ".claude" / "settings.json", hooks("project"))
        write(r.work / ".claude" / "settings.local.json", hooks("local"))
        user = {"mcpServers": {"recalith-sentinel-user": {"command": self.python, "args": ["-I", str(mcp), str(self.mcp_marker), t["user_mcp_tool"]]}}}
        user["projects"] = {str(r.work): {"hasTrustDialogAccepted": True, "enabledMcpjsonServers": ["recalith-sentinel-project"], "hasCompletedProjectOnboarding": True}}
        write(r.home / ".claude.json", json.dumps(user, indent=1))
        write(r.work / ".mcp.json", json.dumps({"mcpServers": {"recalith-sentinel-project": {"command": self.python, "args": ["-I", str(mcp), str(self.mcp_marker), t["project_mcp_tool"]]}}}, indent=1))

    def fired(self) -> tuple[list[str], list[str]]:
        def read(p: Path) -> list[str]:
            return sorted({ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()}) if p.exists() else []

        return read(self.hook_marker), read(self.mcp_marker)

    def visible(self, text: str) -> list[str]:
        return sorted(name for name, token in self.tokens.items() if token in text)

    def transcripts(self) -> list[str]:
        projects = self.root.home / ".claude" / "projects"
        seeded = "5e1f6a2c-1111-4222-8333-944455556666.jsonl"
        return sorted(str(p.relative_to(self.root.home)) for p in projects.rglob("*.jsonl") if p.name != seeded) if projects.exists() else []


# --------------------------------------------------------------------------
# Loopback recording endpoint (request capture: no account, placeholder key)


class RecordingEndpoint:
    """Loopback Messages-compatible endpoint recording request bodies (never credentials)."""

    def __init__(self, reply_text: str | Callable[[dict], str]) -> None:
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        endpoint = self
        reply = reply_text if callable(reply_text) else (lambda body: reply_text)

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                self._send(404, b"", "application/json")

            def do_HEAD(self) -> None:  # noqa: N802
                self._send(200, b"", "application/json")

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = {}
                if not self.path.startswith("/v1/messages") or "count_tokens" in self.path:
                    self._send(200, b'{"input_tokens": 1}', "application/json")
                    return
                if isinstance(body, dict):
                    with endpoint._lock:
                        endpoint.requests.append(body)
                text = reply(body if isinstance(body, dict) else {})
                model = body.get("model") if isinstance(body, dict) else None
                if isinstance(body, dict) and body.get("stream"):
                    events = [
                        ("message_start", {"type": "message_start", "message": {"id": "msg_check", "type": "message", "role": "assistant", "model": model, "content": [], "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}}),
                        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
                        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}),
                        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 1}}),
                        ("message_stop", {"type": "message_stop"}),
                    ]
                    payload = b"".join(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode() for name, data in events)
                    self._send(200, payload, "text/event-stream")
                else:
                    message = {"id": "msg_check", "type": "message", "role": "assistant", "model": model, "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}
                    self._send(200, json.dumps(message).encode(), "application/json")

            def _send(self, status: int, data: bytes, ctype: str) -> None:
                self.send_response(status)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "RecordingEndpoint":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._server.shutdown()
        self._server.server_close()

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.requests)


def episode_body(size: int) -> str:
    """A strictly valid ``build_episode`` body of about ``size`` UTF-8 bytes (the probe's 15 KB bounds case)."""
    count = max(2, -(-size // 6000))
    per_step = max(100, (size - 1200) // count - 260)
    supported = lambda text: {"text": text, "evidence": [], "basis": "observed"}  # noqa: E731
    episode = {
        "task_id": "task_00000000-0000-4000-8000-000000000000", "title": "Probe episode", "started_at": "2026-10-15T12:00:00.000000Z",
        "objective": supported("Exercise the decoded-body allowance."),
        "steps": [{"ordinal": i, "action": supported("x" * per_step), "outcome": "failure" if i % 2 == 0 else "success"} for i in range(count)],
        "outcome": supported("Bounded."), "source_event_ids": ["evt_" + "0" * 64],
    }
    return json.dumps({"operations": [{"local_ref": "op1", "kind": "create_episode", "depends_on": [], "target": None, "payload": episode, "evidence": [], "reason": "probe"}]})


class CaptureEndpoint:
    """Loopback capture of one direct-API request: method, path, header names and values, raw body.

    It answers in the configured dialect with the expected model.
    ``behavior`` drives the probe's bounds checks: ``ok`` (a valid no-op),
    ``large`` (a valid 15 KB episode body), ``hang``, ``flood`` (a body past
    the wire cap), ``oversize`` (a valid reply whose body exceeds the purpose
    cap) and ``malformed``. Credentials sent to it are the placeholder.
    """

    def __init__(self, config: ProviderConfig, *, behavior: str = "ok") -> None:
        self.records: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._closing = threading.Event()
        self.behavior = behavior
        capture = self
        dialect = config.endpoint.dialect if config.endpoint is not None else "chat_completions"
        model = api.expected_model(config)

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                self._record(b"")
                self._send(404, b"{}")

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length) if length else b""
                self._record(raw)
                if capture.behavior == "hang":
                    capture._closing.wait(600)
                    return
                if capture.behavior == "flood":
                    self._send(200, b"{\"pad\": \"" + b"z" * (300 * 1024) + b"\"}")
                    return
                if capture.behavior == "malformed":
                    self._send(200, b"{\"id\": \"msg_check\", \"type\": \"mess")
                    return
                text = json.dumps({"operations": [], "no_op_reason": "isolation check"})
                if capture.behavior in ("large", "oversize"):
                    text = episode_body(16_800 if capture.behavior == "large" else 30_000)
                if dialect == "messages":
                    reply = {"id": "msg_check", "type": "message", "role": "assistant", "model": model, "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}
                else:
                    reply = {"id": "chatcmpl-check", "object": "chat.completion", "model": model, "choices": [{"index": 0, "message": {"role": "assistant", "content": text, "refusal": None}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
                self._send(200, json.dumps(reply).encode("utf-8"))

            def _record(self, raw: bytes) -> None:
                with capture._lock:
                    capture.records.append({"method": self.command, "path": self.path, "headers": [(k.lower(), v) for k, v in self.headers.items()], "body": raw})

            def _send(self, status: int, data: bytes) -> None:
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "CaptureEndpoint":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._closing.set()
        self._server.shutdown()
        self._server.server_close()

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.records)


def capture_overrides(endpoint_url: str) -> dict[str, str]:
    return {"ANTHROPIC_BASE_URL": endpoint_url, "ANTHROPIC_API_KEY": PLACEHOLDER_KEY, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}


# --------------------------------------------------------------------------
# Effective-isolation check (request capture)


def environment_failures(observed: Sequence[str] | None, constructed: Mapping[str, str], report: Mapping[str, Any], *, installation_id: str) -> tuple[list[str], dict[str, Any]]:
    keys = list(observed) if observed is not None else sorted(constructed)
    failures = []
    if any(k in keys for k in process_env.HOST_MARKERS):
        failures.append("host_marker_present")
    if process_env.CURATOR_MARKER not in keys or constructed.get(process_env.CURATOR_MARKER) != installation_id:
        failures.append("curator_marker_missing")
    if process_env.WORKER_MARKER in keys:
        failures.append("worker_marker_present")
    inherited_extra = sorted(set(keys) & set(report.get("inherited_not_permitted", ())) - LAUNCHER_ADDED_KEYS)
    if inherited_extra:
        failures.append("unpermitted_inherited_key_present")
    if observed is not None and (set(observed) - set(constructed) - LAUNCHER_ADDED_KEYS or set(constructed) - set(observed)):
        failures.append("observed_env_differs_from_constructed")
    detail = {
        "method": "linux_proc_environ" if observed is not None else "constructed_map_only",
        "child_keys": keys,
        "constructed_keys": sorted(constructed),
        "host_markers_present": sorted(k for k in process_env.HOST_MARKERS if k in keys),
        "curator_marker_names_installation": constructed.get(process_env.CURATOR_MARKER) == installation_id,
        "worker_marker_present": process_env.WORKER_MARKER in keys,
        "removed_allowlisted_markers": list(report.get("removed_allowlisted_markers", ())),
        "inherited_not_permitted_count": len(report.get("inherited_not_permitted", ())),
    }
    return failures, detail


def isolation_check(config: ProviderConfig, *, inherited: Mapping[str, str], timeout_s: float = CHECK_TIMEOUT_SECONDS, python: str = sys.executable) -> dict[str, Any]:
    """One request-capture launch of the configured route with planted sentinels (never certifies)."""
    if config.backend in api_backends():
        return api_isolation_check(config, inherited=inherited, timeout_s=timeout_s)
    out: dict[str, Any] = {"mode": "request_capture", "backend": config.backend, "certifies": False, "failures": []}
    if config.backend != "claude_cli":
        out.update(verdict="unavailable", failures=["backend_certification_unavailable"])
        return out
    problems = claude_cli.argument_problems(config.invocation_args)
    executable = resolve_executable(config.executable, inherited)
    if executable is None:
        out.update(verdict="unavailable", failures=["executable_missing"])
        return out
    out["argument_problems"] = problems
    reply = json.dumps({"operations": [], "no_op_reason": "isolation check"})
    with RecordingEndpoint(reply) as endpoint, PrivateRoot() as root:
        sentinels = Sentinels(root, python=python)
        sentinels.plant()
        env, report = curator_environment(config, root, inherited, mode="request_capture", capture=capture_overrides(endpoint.url))
        argv = claude_cli.argv(executable, config.invocation_args, model=config.configured_model, system_prompt=CURATOR_SYSTEM_PROMPT)
        result = launch.run_bounded(argv, env=env, cwd=root.work, stdin_data=CHECK_INPUT, timeout_s=timeout_s, observe_env=True)
        hooks, mcps = sentinels.fired()
        requests = endpoint.snapshot()
        transcripts = sentinels.transcripts()
        f = out["failures"]
        f.extend(problems)
        if result.timed_out:
            f.append("timeout")
        if result.stdout_overflow:
            f.append("wire_stdout_oversized")
        if result.tree_cleaned is False:
            f.append("process_tree_survived")
        env_failures, env_detail = environment_failures(result.observed_env_keys, env, report, installation_id=config.installation_id)
        f.extend(env_failures)
        if hooks:
            f.append("sentinel_hook_ran")
        if mcps:
            f.append("sentinel_mcp_started")
        if transcripts:
            f.append("session_state_written")
        init_summary = None
        try:
            init, _result = claude_cli.parse_envelope(result.stdout)
            init_summary = claude_cli.summarize_init(init) if init is not None else None
        except (ValueError, UnicodeDecodeError):
            f.append("envelope_invalid")
        if init_summary is None:
            f.append("isolation_init_missing")
        else:
            if init_summary["tools"]:
                f.append("isolation_tools_exposed")
            if init_summary["mcp_servers"]:
                f.append("isolation_mcp_present")
            if init_summary["non_builtin_plugins"]:
                f.append("isolation_plugins_present")
        tool_names = sorted({str(t.get("name")) for r in requests for t in (r.get("tools") or []) if isinstance(t, dict)})
        visible = sorted({s for r in requests for s in sentinels.visible(json.dumps({k: r.get(k) for k in ("system", "messages", "tools")}))})
        if not requests:
            f.append("no_model_request_observed")
        if tool_names:
            f.append("request_offers_tools")
        if visible:
            f.append("request_contains_sentinel")
        out.update(
            {
                "host_version": init_summary["host_version"] if init_summary else None,
                "init": init_summary,
                "environment": env_detail,
                "hooks_fired": hooks,
                "mcp_servers_started": mcps,
                "session_transcripts_written": transcripts,
                "request_capture": {"message_request_count": len(requests), "model_visible_tools": tool_names, "sentinels_visible": visible},
                "process": {"returncode": result.returncode, "timed_out": result.timed_out, "stdout_overflow": result.stdout_overflow, "tree_bound": result.tree_bound, "tree_cleaned": result.tree_cleaned, "duration_ms": result.duration_ms},
            }
        )
    out["failures"] = sorted(set(out["failures"]))
    out["verdict"] = "fail" if out["failures"] else "pass"
    return out


# --------------------------------------------------------------------------
# Direct-API request capture (decision 0023)


CREDENTIAL_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.I)
TOOL_FIELDS = frozenset({"tools", "tool_choice", "functions", "function_call", "parallel_tool_calls", "tool_config", "mcp_servers"})


def api_backends() -> frozenset:
    from recalith.contracts.config import API_BACKENDS

    return API_BACKENDS


def endpoint_path(url: str) -> str:
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


def capture_launch(config: ProviderConfig, *, inherited: Mapping[str, str], behavior: str = "ok", timeout_s: float = CHECK_TIMEOUT_SECONDS, request: bytes = CHECK_INPUT, output_cap: int | None = None) -> tuple[Any, Any, list[dict[str, Any]], Any]:
    """One request-capture launch of an API route: ``(backend, launch outcome, captured records, unwrap result or failure)``."""
    from recalith.providers import base

    cap = base.CHECK_OUTPUT_CAP if output_cap is None else output_cap
    with CaptureEndpoint(config, behavior=behavior) as endpoint:
        overrides = {key: PLACEHOLDER_KEY for key in config.auth_env_keys}
        overrides.update({"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
        backend = base.ProviderBackend(config, inherited=inherited, mode="request_capture", capture=overrides, endpoint_url=endpoint.url + endpoint_path(config.endpoint.url))
        outcome = backend.launch(request, timeout_s=timeout_s, purpose="isolation_check", output_cap=cap)
        records = endpoint.snapshot()
    try:
        parsed: Any = backend.adapter.unwrap(outcome.stdout, expect=backend.expect)
    except Exception as exc:  # noqa: BLE001 - reported as the reply's failure code
        parsed = exc
    return backend, outcome, records, parsed


def api_isolation_check(config: ProviderConfig, *, inherited: Mapping[str, str], timeout_s: float = CHECK_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Request capture for a direct-API route: the engine sent exactly the certified request, and nothing else."""
    from recalith.providers import base

    out: dict[str, Any] = {"mode": "request_capture", "backend": config.backend, "certifies": False, "failures": []}
    assert config.endpoint is not None
    backend, result, records, parsed = capture_launch(config, inherited=inherited, timeout_s=timeout_s)
    f = out["failures"]
    if result.timed_out:
        f.append("timeout")
    if result.overflowed:
        f.append("wire_stdout_oversized")
    if result.tree_cleaned is False:
        f.append("process_tree_survived")
    report = backend.last_environment_report or {}
    constructed = {k: "" for k in report.get("permitted", [])}
    constructed[process_env.CURATOR_MARKER] = backend.last_curator_marker or ""
    env_failures, env_detail = environment_failures(result.observed_env_keys, constructed, report, installation_id=config.installation_id)
    f.extend(env_failures)
    expected_body = api.build_body(config, CHECK_INPUT, output_cap=base.CHECK_OUTPUT_CAP)
    detail: dict[str, Any] = {"message_request_count": len(records), "model_visible_tools": [], "body_identical": False}
    if len(records) != 1:
        f.append("no_model_request_observed" if not records else "multiple_requests_sent")
    if records:
        record = records[0]
        names = sorted({k for k, _ in record["headers"]})
        expected_names = api.expected_header_names(config)
        wire = record["body"] + json.dumps(record["headers"]).encode("utf-8")
        detail.update(path=record["path"], method=record["method"], header_names=names, unexpected_header_names=sorted(set(names) - set(expected_names)), missing_header_names=sorted(set(expected_names) - set(names)))
        if record["method"] != "POST":
            f.append("request_method_unexpected")
        if record["path"] != endpoint_path(config.endpoint.url):
            f.append("request_path_mismatch")
        if detail["unexpected_header_names"] or detail["missing_header_names"]:
            f.append("request_header_names_unexpected")
        auth = api.auth_spec(config)
        values = dict(record["headers"])
        carriers = sorted(k for k, v in record["headers"] if PLACEHOLDER_KEY in v)
        if auth is not None:
            wanted = f"Bearer {PLACEHOLDER_KEY}" if auth["scheme"] == "bearer" else PLACEHOLDER_KEY
            if values.get(auth["header"]) != wanted:
                f.append("auth_header_mismatch")
            carriers = [k for k in carriers if k != auth["header"]]
        if carriers or PLACEHOLDER_KEY.encode("utf-8") in record["body"]:
            f.append("credential_outside_selected_header")
        selected = set(config.auth_env_keys)
        leaked = sorted(k for k, v in inherited.items() if k not in selected and CREDENTIAL_NAME.search(k) and isinstance(v, str) and len(v) >= 8 and v.encode("utf-8") in wire)
        if leaked:
            f.append("unselected_credential_present")
        detail["unselected_credential_names"] = leaked
        detail["body_identical"] = record["body"] == expected_body
        if not detail["body_identical"]:
            f.append("request_body_differs")
        try:
            body = json.loads(record["body"])
        except ValueError:
            body = None
        if not isinstance(body, dict):
            f.append("request_body_invalid")
        else:
            keys = set(body)
            detail["body_keys"] = sorted(keys)
            detail["model_visible_tools"] = sorted(keys & TOOL_FIELDS)
            if detail["model_visible_tools"]:
                f.append("request_offers_tools")
            if keys != api.expected_body_keys(config):
                f.append("request_body_keys_unexpected")
            if body.get("model") != config.configured_model:
                f.append("request_model_mismatch")
            if body.get(config.endpoint.output_cap_field) != base.CHECK_OUTPUT_CAP:
                f.append("output_cap_missing")
            if (body.get("response_format") == {"type": "json_object"}) != (config.endpoint.json_mode == "json_object"):
                f.append("json_mode_mismatch")
            text = CHECK_INPUT.decode("utf-8")
            if config.endpoint.dialect == "messages":
                shaped = body.get("system") == CURATOR_SYSTEM_PROMPT and body.get("messages") == [{"role": "user", "content": text}]
            else:
                shaped = body.get("messages") == [{"role": "system", "content": CURATOR_SYSTEM_PROMPT}, {"role": "user", "content": text}]
            if not shaped:
                f.append("request_messages_unexpected")
    if isinstance(parsed, Exception):
        f.append(f"reply_unparsed:{getattr(parsed, 'code', type(parsed).__name__)}"[:64])
    out.update(
        {
            "host_version": None,
            "endpoint": {"path": endpoint_path(config.endpoint.url), "dialect": config.endpoint.dialect, "auth_header": config.endpoint.auth_header},
            "environment": env_detail,
            "request_capture": detail,
            "process": {"returncode": result.returncode, "timed_out": result.timed_out, "stdout_overflow": result.overflowed, "tree_bound": result.tree_bound, "tree_cleaned": result.tree_cleaned, "duration_ms": result.duration_ms},
        }
    )
    out["failures"] = sorted(set(out["failures"]))
    out["verdict"] = "fail" if out["failures"] else "pass"
    return out


__all__ = ["CaptureEndpoint", "api_isolation_check", "capture_launch", "endpoint_path", "PrivateRoot", "PrivateRootError", "curator_environment", "route_keys", "Sentinels", "RecordingEndpoint", "isolation_check", "environment_failures", "resolve_executable", "sentinel_spec"]
