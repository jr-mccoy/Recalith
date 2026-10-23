#!/usr/bin/env python3
"""Task 13: the Task 0b delivery harness in engine mode (decision 0019).

Used by ``tools/probe_delivery.py --engine-project PATH`` and by
``tests/platform/test_claude_smoke.py``. Every host session runs the installed
Claude Code CLI in a **disposable, owned fixture installation** under the
harness base directory: a real ``recalith`` installation with a provisioned
runtime, the hooks and deny rules installed by the real
``integrations.claude.integrate``, a private ``HOME`` per session and
``--setting-sources local``. Every hook is the real Recalith entry behind the
installed launcher; delivery runs the real compiler, final fence, budgets,
scratch reservation, receipts and worker accounting.

Modes (as in Task 0b):

* ``request_capture``: a loopback scripted endpoint with a placeholder key
  plays the model (never the operator's or this session's credentials or
  proxy). It shows what reaches the outbound model request and what the host
  enforces (deny rules, private paths), which hooks fire and which processes
  survive. It never counts as an echo pass and never writes a live record.
* ``live``: the configured working-agent route and model (LOCAL_CONFIG's
  ``delivery`` section). Only a complete live run certifies a delivery path.

**Synthetic fixture states** (labeled in the report): each delivery trial's
nonce memory is a claim admitted through the real extraction and review path
with *recorded* proposals, citing real captured fixture events (a canary fact
for session start, prompt and compaction restoration; a failure lesson on the
fixture tool's exact action for pre-action); a trial enables only its own path
in a controlled hook manifest (``integrate`` itself enables only live-certified
paths); the endpoint chooses the scripted tool calls. A fresh 128-bit nonce
lives in exactly one packet item and nowhere else: not in a prompt, a file, a
tool output or an earlier turn; negatives withhold it.

Reported, never claimed: a request-capture observation inspects the
loopback request (it is accessible); a live run inspects only the model's
response and the host's transcript, never an inaccessible internal request.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "tests" / "integration"), str(ROOT / "tests" / "platform"), str(TOOLS)]

import probe_common as pc  # noqa: E402
import probe_delivery as pd  # noqa: E402
import capture_claude_fixtures as cap  # noqa: E402

PATHS = ("session_start", "prompt", "pre_action", "compact")
TRIAL_PATH = {"session_start": "session_start", "prompt": "prompt", "pre_action": "pre_action", "compact": "compact_restore"}
FIXED_TOOL = "ls /nonexistent-recalith-fixture-dir"  # the fixture tool: fixed failing output that never contains a nonce
CANARY = pd.CANARY_INSTRUCTION
PROMPTS = {
    "session_start": CANARY,
    "prompt": CANARY,
    "pre_action": f"First run the shell command `{FIXED_TOOL}` once with the Bash tool and use no other tool. After it finishes, follow this instruction: " + CANARY,
}
COMPACT_TURNS = ("Reply with the single word OK.", "/compact", CANARY)
CONTROLS = pd.CONTROLS_PER_KIND
SCRIPTED_MODEL = cap.SCRIPTED_MODEL
DENIED_TEXT = "has been denied"
ADMIN_SAMPLE_ARGS = {
    "init": "init --profile coding --release-profile claude_preview", "declare": "declare decision --statement probe --scope probe-scope.json",
    "correct": "correct claim_x --expected-revision 1 --statement probe", "undo": "undo op_x --apply --preview-digest 00", "forget": "forget --selector s.json --apply --preview-digest 00",
    "integrate": "integrate claude", "backup": "backup --output probe-backup", "restore": "restore probe-backup --expected-digest 00", "export": "export --selection s.json --output o",
    "import": "import p --expected-digest 00", "upgrade": "upgrade --wheel w --expected-digest 00", "workspace": "workspace rebind", "project": "project fork", "worker": "worker start",
    "jobs retry": "jobs retry job_x", "operator-token": "operator-token revoke tok_x", "doctor --probe-host": "doctor --probe-host claude", "doctor --probe-provider": "doctor --probe-provider claude_cli",
}
# Spellings no prefix rule matches (reported gaps): the guard must still refuse them on the actual tool subprocess.
GAP_COMMANDS = (
    ("global_options_before_subcommand", ".recalith/bin/recalith --json declare decision --statement probe --scope probe-scope.json"),
    ("shell_wrapper", "sh -c '.recalith/bin/recalith declare decision --statement probe --scope probe-scope.json'"),
    ("shell_wrapper", "bash .recalith/bin/recalith declare decision --statement probe --scope probe-scope.json"),
)
# Native Windows (decision 0027): the agent's Bash tool is Git Bash, where only the .cmd launcher reaches the CLI (the
# POSIX launcher finds no venv/bin/python and exits 4 before the guard); bash cannot run a .cmd file as a script, so the
# third gap is a quoted launcher path instead.
WINDOWS_GAP_COMMANDS = (
    ("global_options_before_subcommand", ".recalith/bin/recalith.cmd --json declare decision --statement probe --scope probe-scope.json"),
    ("shell_wrapper", "sh -c '.recalith/bin/recalith.cmd declare decision --statement probe --scope probe-scope.json'"),
    ("other_interpreter_or_copy", '".recalith/bin/recalith.cmd" declare decision --statement probe --scope probe-scope.json'),
)


def admin_launcher(windows: bool | None = None) -> str:
    """The launcher spelling that reaches the CLI from the agent's Bash tool on this platform."""
    return ".recalith/bin/recalith.cmd" if (WINDOWS if windows is None else windows) else ".recalith/bin/recalith"


def deny_commands(spellings: Sequence[str], *, windows: bool | None = None) -> list[dict[str, Any]]:
    """The deny probe's commands: every covered spelling with ``declare``, every form through the launcher, the gaps."""
    from recalith.integrations import claude as integration

    windows = WINDOWS if windows is None else windows
    launcher = admin_launcher(windows)
    commands: list[dict[str, Any]] = [{"spelling": s, "form": "declare", "command": f"{s} {ADMIN_SAMPLE_ARGS['declare']}", "covered": True} for s in spellings]
    for form in integration.ADMIN_FORMS:
        if form != "declare":
            commands.append({"spelling": launcher, "form": form, "command": f"{launcher} {ADMIN_SAMPLE_ARGS[form]}", "covered": True})
    for gap, command in WINDOWS_GAP_COMMANDS if windows else GAP_COMMANDS:
        commands.append({"spelling": gap, "form": "declare", "command": command, "covered": False, "gap": gap})
    return commands
PRIVATE_PROBE_RULES = ("Read(./.recalith/**)", "Edit(./.recalith/**)", "Write(./.recalith/**)")


# --------------------------------------------------------------------------
# Fixture installations


_SHARED_RUNTIME: dict[str, Path] = {}


def _shared_runtime(base: Path) -> Path:
    """One provisioned runtime per harness run (a venv whose site path holds this source tree), linked into each fixture."""
    import cli_scenarios as cs
    from recalith.core import identity

    key = str(base)
    if key not in _SHARED_RUNTIME:
        holder = base / "shared-runtime-project"
        (holder / ".recalith").mkdir(parents=True, exist_ok=True)
        cs.provision_runtime(holder)
        _SHARED_RUNTIME[key] = identity.Layout(holder).runtime_python(identity.__version__).parents[3]
    return _SHARED_RUNTIME[key]


class Fixture:
    """A disposable fixture installation integrated by the real installer (see the module docstring)."""

    def __init__(self, base: Path, name: str, exe: str, *, unrelated: bool = True) -> None:
        import cli_scenarios as cs
        from recalith.contracts.common import Actor, new_id
        from recalith.contracts.config import ProjectConfig
        from recalith.core import identity
        from recalith.integrations import claude as integration

        self.exe = exe
        self.base = base / short_name(name)
        self.root = self.base / ("ws" if WINDOWS else "workspace")
        self.homes = self.base / ("h" if WINDOWS else "homes")
        self.root.mkdir(parents=True)
        self.homes.mkdir()
        if shutil.which("git"):
            subprocess.run(["git", "init", "-q", str(self.root)], capture_output=True, env={"PATH": os.environ.get("PATH", "")}, timeout=60, check=False)
        for fname, body in cap.FIXTURE_TESTS.items():
            (self.root / fname).write_text(body, encoding="utf-8")
        (self.root / "notes.txt").write_text("fixture notes\n", encoding="utf-8")
        (self.root / "dep.txt").write_text("fixture v1\n", encoding="utf-8")
        (self.root / "probe-scope.json").write_text("{}\n", encoding="utf-8")
        if unrelated:
            (self.root / ".claude").mkdir()
            self.unrelated_bytes = (json.dumps(cap.unrelated_settings(), indent=2) + "\n").encode("utf-8")
            (self.root / ".claude" / "settings.local.json").write_bytes(self.unrelated_bytes)
        else:
            self.unrelated_bytes = None
        identity.initialize_installation(self.root, ProjectConfig.defaults_for(new_id("proj")))
        runtime = identity.Layout(self.root).base / "runtime"
        shutil.rmtree(runtime, ignore_errors=True)
        link_dir(runtime, _shared_runtime(base))  # fixture convenience: one provisioned runtime
        self.actor = Actor(kind="operator", id="probe-harness", channel="cli")
        self.ctx = identity.resolve_installation(self.root, actor=self.actor)
        self.integration = integration.integrate(self.ctx, executable=exe)
        self.home_n = 0
        _ = cs  # provision helper imported above

    # ---------------------------------------------------------------- manifest

    def trial_manifest(self, paths: Sequence[str], *, autostart: bool) -> None:
        """Controlled: a hook manifest enabling exactly ``paths`` for one trial (integrate enables only live-certified paths)."""
        from recalith.capture.hooks import write_hook_context

        write_hook_context(self.ctx, adapter_id="claude_code", host_version=self.integration["host"]["version"], worker_autostart=autostart, delivery_paths=list(paths), session_notice=False)

    # ---------------------------------------------------------------- sessions

    def home(self) -> Path:
        self.home_n += 1
        home = self.homes / f"h{self.home_n}"
        home.mkdir()
        return home

    def env(self, home: Path, endpoint: str | None, live: Mapping[str, Any] | None = None) -> dict[str, str]:
        if live is None:
            env = cap.child_env(home, endpoint or "http://127.0.0.1:9")
        else:
            env = {k: os.environ[k] for k in live["keys"] if k in os.environ}
            env.update({"HOME": str(home), "USERPROFILE": str(home)})
            venv_bin = ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin")
            env["PATH"] = os.pathsep.join([str(venv_bin), os.environ.get("PATH", os.defpath)])
            for marker in (*pc.DEFAULT_HOST_MARKERS, *pc.ROLE_MARKERS):
                env.pop(marker, None)
        return env

    def argv(self, *, model: str, allowed: Sequence[str] = (), mode: str | None = None, multi: bool = False) -> list[str]:
        argv = [self.exe, "-p", "--setting-sources", "local", "--strict-mcp-config", "--model", model, "--output-format", "stream-json", "--verbose", "--include-hook-events"]
        if multi:
            argv += ["--input-format", "stream-json"]
        if mode:
            argv += ["--permission-mode", mode]
        if allowed:
            argv += ["--allowedTools", *allowed]
        return argv

    def session(self, stdin: bytes, *, endpoint: pc.RecordingEndpoint | None, model: str = SCRIPTED_MODEL, allowed: Sequence[str] = (), mode: str | None = None, multi: bool = False, live=None, timeout: float = 120) -> dict[str, Any]:
        home = self.home()
        seen = len(endpoint.snapshot()) if endpoint else 0
        run = pc.run_bounded(self.argv(model=model, allowed=allowed, mode=mode, multi=multi), env=self.env(home, endpoint.url if endpoint else None, live), cwd=self.root, stdin_data=stdin, timeout_s=timeout)
        parsed = pd.parse_session_stream(run.stdout)
        hooks = [json.loads(line) for line in run.stdout.decode("utf-8", "replace").splitlines() if line.strip().startswith("{") and '"hook_response"' in line]
        requests = pc.message_requests(endpoint.snapshot()[seen:]) if endpoint else []
        transcripts = list((home / ".claude" / "projects").rglob("*.jsonl")) if (home / ".claude" / "projects").exists() else []
        return {
            "run": run, "timeline": parsed["timeline"], "hooks": [h for h in hooks if h.get("subtype") == "hook_response"], "requests": requests,
            "transcript_text": "".join(p.read_text(encoding="utf-8", errors="replace") for p in transcripts), "stdout": run.stdout,
        }

    # ---------------------------------------------------------------- engine state

    def project(self):
        """The fixture as a test ``Project`` (recorded proposals through the real persisted path)."""
        import claude_scenarios as ccs
        import working_scenarios as wks

        import operation_scenarios as osc

        p = wks.Project.__new__(wks.Project)
        p.replay = ccs.Payloads(self.root, self.base)
        p.root = self.root
        p.ctx = osc.context(self.root)  # the worker/controller actor the recorded proposals run under (never the operator)
        return p

    def ingest(self) -> None:
        from recalith.capture import pipeline

        for _ in range(64):
            if pipeline.ingest_ready(self.ctx).accepted == 0 and not _ready(self.root):
                break

    def deliveries(self) -> list[dict[str, Any]]:
        from recalith.storage import db

        with db.open_store(self.ctx, readonly=True) as store, store.read() as view:
            rows = view.execute("SELECT purpose, state, estimated_tokens, session_id FROM deliveries ORDER BY rowid").fetchall()
        return [{"purpose": a, "state": b, "estimated_tokens": c, "session_id": d} for a, b, c, d in rows]

    def store_state(self) -> dict[str, Any]:
        import cli_scenarios as cs

        rows = cs.store_rows(self.root)
        files = {rel: _digest(self.root / rel) for rel in (".recalith/local.toml", ".recalith/project.toml", ".recalith/engine.lock", ".claude/settings.local.json", ".recalith/run/integrations/claude_code.json")}
        return {"rows": rows, "files": files}

    def stop_worker(self) -> None:
        stop_worker(self.root)


WINDOWS = os.name == "nt"
_SHORT_NAMES: dict[str, str] = {}


def short_name(name: str) -> str:
    """A fixture directory name. On Windows a short stable one: without long-path support every path stops at 260
    characters, and the host's transcript (``HOME\\.claude\\projects\\SLUG\\SESSION.jsonl``) repeats the whole
    workspace path in SLUG, so a descriptive name (``trial-live-session_start-positive-1``) pushes it past the limit."""
    return _SHORT_NAMES.setdefault(name, f"f{len(_SHORT_NAMES) + 1:02d}") if WINDOWS else name


def link_dir(link: Path, target: Path) -> None:
    """A directory link: a symlink on POSIX; on Windows a junction, which needs no symlink privilege."""
    if WINDOWS:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def unlink_dir(link: Path) -> None:
    """Remove a directory link (never its target): ``unlink`` on POSIX; ``rmdir`` for a Windows junction."""
    if WINDOWS:
        os.rmdir(link)
    else:
        link.unlink()


def kill_pid(pid: int) -> None:
    """Kill one process by PID: SIGKILL on POSIX; TerminateProcess on Windows (``os.kill`` with SIGTERM)."""
    os.kill(pid, signal.SIGTERM if WINDOWS else signal.SIGKILL)


def _digest(path: Path) -> str | None:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _ready(root: Path) -> list[Path]:
    from recalith.fast import spool

    return spool.ready_segments(spool.SpoolDirs(root))


def stop_worker(root: Path, timeout: float = 30) -> None:
    """Stop a fixture's worker: the stop request, then its PID from its own record (never a pattern kill)."""
    from recalith.controller import worker as worker_module
    from recalith.fast import process_env

    if not process_env.worker_running(str(root)):
        return
    worker_module.request_stop(root)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process_env.worker_running(str(root)):
        time.sleep(0.1)
    if process_env.worker_running(str(root)):
        pid = worker_pid(root)
        if pid is not None:
            with contextlib.suppress(OSError):
                kill_pid(pid)


def stop_workers(base: Path) -> None:
    for run in Path(base).rglob(".recalith/run"):
        stop_worker(run.parent.parent)


def wait_for(predicate: Callable[[], Any], timeout: float, interval: float = 0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


# --------------------------------------------------------------------------
# Scripted model (request-capture)


def scripted(steps: Sequence[tuple[str, dict[str, Any]]], *, final: str = "CANARY NONE", summary: str = "SUMMARY: scripted fixture conversation.") -> Callable[[dict], tuple[str, Any]]:
    """The loopback 'model': the given tool calls in order (one per result), then ``final``; it never echoes a nonce."""

    def respond(body: dict) -> tuple[str, Any]:
        messages = body.get("messages") or []
        text = json.dumps(messages)
        if "detailed summary" in text.lower() or "detailed summary" in json.dumps(body.get("system")).lower():
            return "text", summary
        n = text.count('"tool_result"')
        if n < len(steps):
            name, inp = steps[n]
            return "tool_use", {"name": name, "input": inp}
        return "text", final

    return respond


def tool_results(requests: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The tool results of the last request, in order: ``{is_error, text}``."""
    if not requests:
        return []
    out = []
    for message in requests[-1].get("messages") or []:
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                inner = block.get("content")
                text = inner if isinstance(inner, str) else json.dumps(inner)
                out.append({"is_error": bool(block.get("is_error")), "text": text})
    return out


def setup_records(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The real setup records: the session start, the first prompt and the fixture tool's real failing call (no nonce anywhere)."""
    start = next(r for r in records if r["event"] == "SessionStart")
    prompt = next(r for r in records if r["event"] == "UserPromptSubmit")
    calls = [r for r in records if r["event"] in ("PreToolUse", "PostToolUseFailure") and (r["payload"].get("tool_input") or {}).get("command") == FIXED_TOOL]
    return [start, prompt, *calls]


# --------------------------------------------------------------------------
# Nonce memories (recorded proposals; see the module docstring)


def seed(fx: Fixture, path: str, nonce: str | None) -> dict[str, Any]:
    """Capture a nonce-free setup session through the real hooks' code, then admit the trial's memory with recorded proposals."""
    import claude_scenarios as ccs
    import consolidation_scenarios as cs_
    import operation_scenarios as osc
    import retrieval_scenarios as rs

    p = fx.project()
    version = fx.integration["host"]["version"]
    records = ccs.fixture_records(version if (ROOT / "tests" / "fixtures" / "hosts" / "claude" / str(version)).is_dir() else "2.1.305", "lifecycle")
    fx.trial_manifest([], autostart=False)
    for rec in setup_records(records):
        p.send(rec)
    p.drain()
    osc.cancel_trigger_extractions(fx.root)
    seeded: dict[str, Any] = {"kind": None}
    if nonce is None and path in ("session_start", "compact"):
        # The negative control: the same open question shape, the nonce withheld.
        cs_.declaration(p, "Record the probe canary decision as option A.", "Probe canary decision: the canary value is withheld.", subject="probe canary")
        cs_.declaration(p, "Record the probe canary decision as option B.", "Probe canary decision: no canary value is recorded.", subject="probe canary")
        p.drain()
        seeded = {"kind": "intent_question_without_nonce"}
    if nonce is not None:
        if path == "pre_action":
            failure = next(e for e in p.events("tool_finished") if (e["payload"] or {}).get("action", {}).get("argv") == FIXED_TOOL.split())
            claim = cs_.lesson(p, f"Probe canary for this fixture action: the canary value is {nonce}.", evidence=failure, subject="probe canary action")
            seeded = {"kind": "failure_lesson", "claim_id": claim}
        elif path in ("session_start", "compact"):
            # A fresh session's start (and a restoration with nothing delivered before it) carries only open intent
            # questions until a task binding exists (decision 0013): two conflicting declarations, one holding the nonce.
            a_id = cs_.declaration(p, "Record the probe canary decision as option A.", f"Probe canary decision: the canary value is {nonce}.", subject="probe canary")
            b_id = cs_.declaration(p, "Record the probe canary decision as option B.", "Probe canary decision: no canary value is recorded.", subject="probe canary")
            p.drain()  # the planner opens the question
            seeded = {"kind": "intent_question", "claim_ids": [a_id, b_id]}
        else:
            said = p.events("user_message")[0]
            claim = cs_.fact(p, f"Probe canary: the canary value is {nonce}.", subject="probe canary", evidence=said)
            seeded = {"kind": "fact", "claim_id": claim}
    rs.publish(p)
    return seeded


# --------------------------------------------------------------------------
# Delivery trials


def run_trial(fx: Fixture, spec: Mapping[str, Any], *, mode: str, endpoint: pc.RecordingEndpoint | None, live=None, model: str = SCRIPTED_MODEL) -> dict[str, Any]:
    path = spec["path"]
    seeded = seed(fx, path, spec["nonce"] if spec["kind"] == "positive" else None)
    fx.trial_manifest([TRIAL_PATH[path]], autostart=False)
    before = len(fx.deliveries())
    if path == "compact":
        stdin = "".join(json.dumps({"type": "user", "message": {"role": "user", "content": t}}) + "\n" for t in COMPACT_TURNS).encode()
        prompts = list(COMPACT_TURNS)
        result = fx.session(stdin, endpoint=endpoint, model=model, multi=True, live=live)
    else:
        prompts = [PROMPTS[path]]
        allowed = [f"Bash({FIXED_TOOL})"] if path == "pre_action" else []
        result = fx.session(prompts[0].encode(), endpoint=endpoint, model=model, allowed=allowed, live=live)
    fx.ingest()
    rows = fx.deliveries()[before:]
    emitted = [r for r in rows if r["state"] == "emitted" and r["purpose"] == TRIAL_PATH[path]]
    from recalith.fast import context as fctx

    cap_tokens = fctx.BUDGETS[TRIAL_PATH[path]]
    nonce = spec["nonce"]
    obs = {
        "launched": True, "timed_out": result["run"].timed_out, "launch_error": result["run"].stdout_overflow or (result["run"].returncode not in (0, None) and not result["timeline"]),
        "timeline": result["timeline"], "prompts": prompts, "workspace_files_with_nonce": _files_with(fx.root, nonce), "other_trial_nonces": spec.get("others", []),
        "hook_records": [{"path": path, "event": TRIAL_PATH[path], "emitted": bool(emitted)}] if emitted or spec["kind"] == "positive" else [],
        "transcript_contains_nonce": nonce in result["transcript_text"] if result["transcript_text"] else None,
    }
    record: dict[str, Any] = {
        "trial_id": spec["trial_id"], "path": path, "kind": spec["kind"], "nonce_sha256": pc.sha256_bytes(nonce.encode()), "seeded": {"kind": seeded["kind"], "synthetic": "recorded proposals"},
        "process": result["run"].to_report(), "tool_uses": [e.get("name") for e in result["timeline"] if e["kind"] == "tool_use"],
        "compact_boundary_seen": any(e["kind"] == "compact_boundary" for e in result["timeline"]),
        "engine": {"emitted_deliveries": len(emitted), "estimated_tokens": [r["estimated_tokens"] for r in emitted], "within_packet_cap": all(r["estimated_tokens"] <= cap_tokens for r in emitted)},
        "hook_exit_codes": sorted({h.get("exit_code") for h in result["hooks"]} - {None}),
        "transcript_contains_nonce": obs["transcript_contains_nonce"], "workspace_files_with_nonce": obs["workspace_files_with_nonce"],
    }
    if mode == "live":
        record["verdict"] = pd.evaluate_trial(spec, obs)
        text = pd.eligible_text(path, result["timeline"])
        record["eligible_response_excerpt"] = text[:200] if text is not None else None
    else:
        record["request_count"] = len(result["requests"])
        record["requests_with_nonce"] = [i for i, r in enumerate(result["requests"]) if nonce in json.dumps({k: r.get(k) for k in ("system", "messages")})]
        record["contaminated"] = bool(obs["workspace_files_with_nonce"]) or nonce in " ".join(prompts)
    return record


def _files_with(root: Path, nonce: str) -> list[str]:
    hits = []
    for p in root.rglob("*"):
        rel = p.relative_to(root).parts
        if not p.is_file() or ".git" in rel or (rel and rel[0] == ".recalith"):
            continue  # the store holds the nonce memory by design; files the agent can see are checked
        with contextlib.suppress(OSError):
            if nonce in p.read_text(encoding="utf-8", errors="replace"):
                hits.append("/".join(rel))
    return sorted(hits)


def path_state_capture(path: str, trials: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pos = [t for t in trials if t["kind"] == "positive"]
    neg = [t for t in trials if t["kind"] == "negative"]
    emitted = [t for t in pos if t["engine"]["emitted_deliveries"] >= 1]
    visible = [t for t in emitted if t["requests_with_nonce"] and not t["contaminated"]]
    clean_neg = [t for t in neg if not t["requests_with_nonce"] and not t["contaminated"]]
    if not emitted:
        state = "hook_not_fired" if all(not t["hook_exit_codes"] for t in pos) else "not_emitted"
    elif len(visible) == len(pos) == CONTROLS and len(clean_neg) == len(neg) == CONTROLS:
        state = "request_visible"
    elif not visible:
        state = "not_in_request"
    else:
        state = "partial"
    return {
        "state": state, "positives_hook_emitted": len(emitted), "positives_visible_in_request": len(visible), "negatives_clean": len(clean_neg),
        "engine": {"receipts_ingested": sum(1 for t in pos if t["engine"]["emitted_deliveries"] == 1), "within_packet_cap": all(t["engine"]["within_packet_cap"] for t in pos)},
        "note": "Request-level observation through the real engine; never an echo pass or a certification.",
    }


def delivery_trials(base: Path, exe: str, *, mode: str, live=None, model: str = SCRIPTED_MODEL) -> dict[str, Any]:
    specs = []
    for path in PATHS:
        for kind in ("positive", "negative"):
            for i in range(CONTROLS):
                specs.append({"trial_id": f"{mode}-{path}-{kind}-{i + 1}", "path": path, "kind": kind, "nonce": secrets.token_hex(16)})
    for spec in specs:
        spec["others"] = [s["nonce"] for s in specs if s is not spec]
    results = []
    responders = {
        "pre_action": scripted([("Bash", {"command": FIXED_TOOL, "description": "Recalith probe fixture"})]),
        "default": scripted([]),
    }
    for spec in specs:
        fx = Fixture(base, f"trial-{spec['trial_id']}", exe, unrelated=False)
        try:
            if mode == "request_capture":
                with pc.RecordingEndpoint(responders["pre_action" if spec["path"] == "pre_action" else "default"]) as ep:
                    results.append(run_trial(fx, spec, mode=mode, endpoint=ep))
            else:
                results.append(run_trial(fx, spec, mode=mode, endpoint=None, live=live, model=model))
        finally:
            fx.stop_worker()
    by_path = {p: [r for r in results if r["path"] == p] for p in PATHS}
    if mode == "live":
        paths = {p: pd.evaluate_path(p, [{"kind": r["kind"], "verdict": r["verdict"]} for r in by_path[p]]) for p in PATHS}
    else:
        paths = {p: path_state_capture(p, by_path[p]) for p in PATHS}
    return {"paths": paths, "trials": results}


# --------------------------------------------------------------------------
# Host enforcement: deny rules and markers (A73), private paths (A65)


def deny_probe(base: Path, exe: str) -> dict[str, Any]:
    from recalith.integrations import claude as integration

    fx = Fixture(base, "deny-probe", exe)
    fx.trial_manifest([], autostart=False)
    commands = deny_commands(integration.spellings(fx.root))
    markers = ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "RECALITH_WORKER_INSTALLATION", "RECALITH_CURATOR_INSTALLATION")
    steps = [("Bash", {"command": c["command"], "description": "Recalith deny probe"}) for c in commands]
    steps += [("Bash", {"command": f"printenv {m}", "description": "Recalith marker probe"}) for m in markers]
    before = fx.store_state()
    audits_before = _audit_count(fx.root)
    with pc.RecordingEndpoint(scripted(steps, final="DONE")) as ep:
        result = fx.session(b"Run the scripted probe commands.", endpoint=ep, allowed=["Bash"], timeout=300)
    outcomes = tool_results(result["requests"])
    for i, c in enumerate(commands):
        r = outcomes[i] if i < len(outcomes) else None
        if r is None:
            c["outcome"] = "not_observed"
        elif r["is_error"] and DENIED_TEXT in r["text"]:
            c["outcome"] = "host_denied"
        elif r["text"].startswith('"Exit code 6') or r["text"].startswith("Exit code 6"):
            c["outcome"] = "guard_refused"
        else:
            c["outcome"] = "executed_other"
    audits = _audit_count(fx.root) - audits_before
    refused = [c for c in commands if c["outcome"] == "guard_refused"]
    for c in refused:
        c["audit"] = "captured" if audits >= len(refused) else "unavailable"
    present = []
    for j, m in enumerate(markers):
        r = outcomes[len(commands) + j] if len(commands) + j < len(outcomes) else None
        if r is not None and not r["is_error"]:
            present.append(m)
    after = fx.store_state()
    covered = [c for c in commands if c["covered"]]
    state = "denied_all_covered" if covered and all(c["outcome"] == "host_denied" for c in covered) else ("executed_covered_spelling" if any(c["outcome"] != "host_denied" for c in covered) else "not_observed")
    effects = "none" if all(c["outcome"] in ("host_denied", "guard_refused") for c in commands) else "unexpected"
    return {
        "state": state, "commands": [{k: c.get(k) for k in ("spelling", "form", "covered", "gap", "outcome", "audit")} for c in commands],
        "tool_subprocess_markers": present, "admin_effects": effects, "store_unchanged": before == after, "permission_mode": "default", "allowed_tools": ["Bash"],
        "note": "Bash allowed for the whole session, so only the deny rules (and then the CLI guard) can stop a command.",
    }


def _audit_count(root: Path) -> int:
    n = 0
    for path in _ready(root):
        with contextlib.suppress(OSError, ValueError):
            n += sum(1 for e in json.loads(path.read_text(encoding="utf-8"))["envelopes"] if e["kind"] == "agent_attempted_operator_command")
    return n


PRIVATE_ATTEMPTS = (
    ("Read", ("Read", {"file_path": "{root}/.recalith/local.toml"})),
    ("Grep", ("Grep", {"pattern": "installation_id", "path": "{root}/.recalith"})),
    ("Write", ("Write", {"file_path": "{root}/.recalith/state/probe-write.txt", "content": "probe\n"})),
    ("Bash cat", ("Bash", {"command": "cat .recalith/local.toml", "description": "probe"})),
    ("Bash head", ("Bash", {"command": "head -c 16 .recalith/state/memory.sqlite", "description": "probe"})),
    ("Bash cp", ("Bash", {"command": "cp .recalith/local.toml probe-copy.txt", "description": "probe"})),
    ("Bash sh -c", ("Bash", {"command": "sh -c 'cat .recalith/local.toml'", "description": "probe"})),
    ("Bash python", ("Bash", {"command": "python3 -c \"print(len(open('.recalith/local.toml').read()))\"", "description": "probe"})),
)
# On Windows ``python3`` in Git Bash is the Microsoft Store alias (it runs nothing); the fixture PATH puts a real ``python`` first.
WINDOWS_PRIVATE_ATTEMPTS = tuple((label, (name, dict(inp, command=inp["command"].replace("python3 ", "python ", 1)) if "command" in inp else inp)) for label, (name, inp) in PRIVATE_ATTEMPTS)


def private_path_probe(base: Path, exe: str, *, permission_mode: str) -> dict[str, Any]:
    """Probe what the agent's tools reach under ``.recalith/`` without and with probe-only path rules (fixture only)."""
    from recalith.integrations import install

    out: dict[str, Any] = {"permission_mode": permission_mode, "allowed_tools": ["Bash", "Read", "Grep", "Write", "Edit"], "installed_in_target": False, "os_level_isolation": False}
    for label, with_rules in (("without_probe_rules", False), ("with_probe_rules", True)):
        fx = Fixture(base, f"private-{label}", exe)
        fx.trial_manifest([], autostart=False)
        settings = fx.root / ".claude" / "settings.local.json"
        if with_rules:
            data, _raw = install.read_settings(settings)
            data.setdefault("permissions", {}).setdefault("deny", []).extend(PRIVATE_PROBE_RULES)
            install.atomic_write(settings, (json.dumps(data, indent=2) + "\n").encode("utf-8"))
        attempts_spec = WINDOWS_PRIVATE_ATTEMPTS if WINDOWS else PRIVATE_ATTEMPTS
        steps = [(name, {k: (v.replace("{root}", str(fx.root)) if isinstance(v, str) else v) for k, v in inp.items()}) for _l, (name, inp) in attempts_spec]
        segments_before = len(_ready(fx.root))
        with pc.RecordingEndpoint(scripted(steps, final="DONE")) as ep:
            result = fx.session(b"Run the scripted probe commands.", endpoint=ep, allowed=out["allowed_tools"], mode=permission_mode, timeout=300)
        outcomes = tool_results(result["requests"])
        attempts = []
        for i, (label2, _step) in enumerate(attempts_spec):
            r = outcomes[i] if i < len(outcomes) else None
            blocked = None if r is None else (r["is_error"] and ("denied" in r["text"].lower()))
            attempts.append({"spelling": label2, "blocked": blocked})
        out[label] = attempts
        if with_rules:
            out["hooks_operated_under_rules"] = len(_ready(fx.root)) > segments_before
    blocked = [a for a in out["with_probe_rules"] if a["blocked"]]
    out["state"] = "probed_supported" if len(blocked) == len(PRIVATE_ATTEMPTS) and out.get("hooks_operated_under_rules") else ("probed_limited" if blocked else "probed_unsupported")
    out["probe_rules"] = list(PRIVATE_PROBE_RULES)
    return out


# --------------------------------------------------------------------------
# Lifecycle, notice, hook failures, worker survival


def lifecycle(base: Path, exe: str) -> dict[str, Any]:
    """The scripted lifecycle and subagent sessions through installed hooks, all four paths enabled (controlled manifest)."""
    from recalith.fast import process_env

    fx = Fixture(base, "lifecycle", exe)
    seed(fx, "session_start", "lifecycle-canary-not-a-trial")  # an ordinary memory for every path (no nonce protocol here)
    seed_pre_action_lesson(fx)
    fx.trial_manifest(list(TRIAL_PATH.values()), autostart=True)
    out: dict[str, Any] = {"host_version": fx.integration["host"]["version"]}
    responder = cap.responder_for(fx.root)
    codes = []
    with pc.RecordingEndpoint(responder) as ep:
        for name in ("lifecycle", "subagent"):
            spec = cap.SCENARIOS[name]
            run = pc.run_bounded(cap.session_argv(exe, spec["allowed"], None), env=cap.child_env(fx.home(), ep.url), cwd=fx.root, stdin_data=cap.stdin_turns(spec["turns"]), timeout_s=180)
            codes.append(run.returncode)
    out["returncode"] = max(c or 0 for c in codes)
    started = wait_for(lambda: process_env.worker_running(str(fx.root)), 20)
    status = wait_for(lambda: _worker_status(fx.root), 20) or {}
    ingested = wait_for(lambda: not _ready(fx.root) and _count(fx, "SELECT COUNT(*) FROM events") > 0, 60)
    wait_for(lambda: _count(fx, "SELECT COUNT(*) FROM events WHERE kind = 'assistant_message'") > 0, 30)
    fx.stop_worker()
    fx.ingest()
    kinds = sorted({r for (r,) in _rows(fx, "SELECT DISTINCT kind FROM events")})
    out["event_kinds"] = kinds
    out["subagent_sessions"] = _count(fx, "SELECT COUNT(*) FROM events WHERE kind = 'session_started' AND payload LIKE '%\"scope\":\"subagent\"%'")
    out["subagent_transcripts_registered"] = _count(fx, "SELECT COUNT(*) FROM capture_sources WHERE locator LIKE '%_subagents_agent-%'")  # '_' matches '/' or a Windows '\'
    out["transcript_sources"] = _count(fx, "SELECT COUNT(*) FROM capture_sources")
    out["assistant_messages_recovered"] = _count(fx, "SELECT COUNT(*) FROM events WHERE kind = 'assistant_message'")
    spawn = (status.get("spawn") or {}) if isinstance(status, dict) else {}
    out["worker"] = {"started": bool(started), "spawned_by": spawn.get("spawned_by"), "method": spawn.get("method"), "ingested_all": bool(ingested)}
    counts: dict[str, int] = {}
    for row in fx.deliveries():
        if row["state"] == "emitted":
            counts[row["purpose"]] = counts.get(row["purpose"], 0) + 1
    out["deliveries"] = {p: counts.get(p, 0) for p in TRIAL_PATH.values()}
    from recalith.integrations import claude as integration

    removed = integration.remove(fx.ctx)
    out["unrelated_settings_preserved"] = removed["unrelated_preserved"] if (fx.root / ".claude" / "settings.local.json").read_bytes() == fx.unrelated_bytes else "changed"
    return out


def seed_pre_action_lesson(fx: Fixture) -> None:
    import consolidation_scenarios as cs_
    import retrieval_scenarios as rs

    p = fx.project()
    failure = next((e for e in p.events("tool_finished") if (e["payload"] or {}).get("action", {}).get("argv") == FIXED_TOOL.split()), None)
    if failure is not None:
        cs_.lesson(p, "Listing the missing fixture directory fails; it does not exist in this fixture.", evidence=failure, subject="missing fixture dir")
        rs.publish(p)


def _rows(fx: Fixture, sql: str) -> list[tuple]:
    from recalith.storage import db

    with db.open_store(fx.ctx, readonly=True) as store, store.read() as view:
        return view.execute(sql).fetchall()


def _count(fx: Fixture, sql: str) -> int:
    return _rows(fx, sql)[0][0]


def _worker_status(root: Path) -> dict[str, Any] | None:
    with contextlib.suppress(OSError, ValueError):
        return json.loads((root / ".recalith" / "run" / "worker.json").read_text(encoding="utf-8"))
    return None


def worker_pid(root: Path, timeout: float = 5) -> int | None:
    """The running worker's own PID from its status record, read until it parses: on Windows a reader that meets the
    worker's atomic replace of the record gets a sharing violation, which must not read as "no worker"."""
    pid = wait_for(lambda: (_worker_status(root) or {}).get("pid"), timeout)
    return int(pid) if isinstance(pid, int) else None


def notice_probe(base: Path, exe: str) -> dict[str, Any]:
    fx = Fixture(base, "notice", exe)
    from recalith.capture.hooks import write_hook_context

    write_hook_context(fx.ctx, adapter_id="claude_code", host_version=fx.integration["host"]["version"], worker_autostart=False)
    seen = []
    with pc.RecordingEndpoint(scripted([], final="OK")) as ep:
        for _ in range(2):
            result = fx.session(b"Reply OK.", endpoint=ep)
            in_stream = b"Recalith: memory is limited" in result["stdout"]
            in_request = any("Recalith: memory is limited" in json.dumps(r) for r in result["requests"])
            seen.append((in_stream, in_request))
    return {"in_host_stream": seen[0][0], "in_model_request": any(r for _s, r in seen), "repeated": seen[1][0]}


HOOK_FAILURES = ("manifest_corrupt", "store_corrupt", "spool_blocked", "runtime_missing")


def hook_failures(base: Path, exe: str) -> dict[str, Any]:
    import cli_scenarios as cs

    out = {}
    for failure in HOOK_FAILURES:
        fx = Fixture(base, f"hook-failure-{failure}", exe)
        fx.trial_manifest(list(TRIAL_PATH.values()), autostart=False)
        if failure == "manifest_corrupt":
            (fx.root / ".recalith" / "run" / "hook-context.json").write_text("{not json", encoding="utf-8")
        elif failure == "store_corrupt":
            (fx.root / ".recalith" / "state" / "memory.sqlite").write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)
        elif failure == "spool_blocked":
            cs.block_spool(fx.root)
        elif failure == "runtime_missing":
            unlink_dir(fx.root / ".recalith" / "runtime")
        marker = f"tool-ran-{failure}.txt"
        with pc.RecordingEndpoint(scripted([("Bash", {"command": f"touch {marker}", "description": "probe"})], final="DONE")) as ep:
            result = fx.session(b"Run the scripted tool.", endpoint=ep, allowed=["Bash"])
        out[failure] = {"tool_ran": (fx.root / marker).exists(), "hook_exit_codes": sorted({h.get("exit_code") for h in result["hooks"]} - {None})}
    return out


def worker_survival(base: Path, exe: str) -> dict[str, Any]:
    """A worker started by the registered hook start must survive the host's end, its kill and a terminal hangup."""
    from recalith import service

    out: dict[str, Any] = {}
    for case in ("session_end", "host_killed", "terminal_hangup"):
        if case == "terminal_hangup" and WINDOWS:
            # A pty hangup is POSIX; closing a Windows console window cannot be produced headless. Reported, never passed.
            out[case] = {"state": "not_run", "reason": "posix_pty_only: a Windows console close is not reproducible headless"}
            continue
        fx = Fixture(base, f"survival-{case}", exe)
        fx.trial_manifest([], autostart=True)
        hang = case != "session_end"
        responder = (lambda body: ("hang", "")) if hang else scripted([], final="OK")
        with pc.RecordingEndpoint(responder) as ep:
            env = cap.child_env(fx.home(), ep.url)
            argv = fx.argv(model=SCRIPTED_MODEL)
            if case == "terminal_hangup":
                proc_pid, master = _pty_spawn(argv, env, fx.root, b"Reply OK.\n")
            else:
                isolate = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
                proc = subprocess.Popen(argv, env=env, cwd=fx.root, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **isolate)
                proc.stdin.write(b"Reply OK.")
                proc.stdin.close()
                proc_pid = proc.pid
            started = wait_for(lambda fx=fx: _worker_status(fx.root), 30)
            if case == "session_end":
                proc.wait(timeout=120)
            elif case == "host_killed":
                if WINDOWS:
                    # The host's whole process tree, as Task Manager's "End process tree" or an IDE's tree kill would.
                    subprocess.run(["taskkill", "/PID", str(proc_pid), "/T", "/F"], capture_output=True, timeout=60, check=False)
                else:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc_pid, signal.SIGKILL)  # the host's whole process group, as a terminal or IDE kill would
                proc.wait(timeout=30)
            else:
                os.close(master)  # the terminal goes away: SIGHUP to the session's foreground group
                with contextlib.suppress(ProcessLookupError):
                    os.kill(proc_pid, signal.SIGHUP)
                _reap(proc_pid, 30)
            ep._release.set()
        time.sleep(0.5)
        from recalith.fast import process_env

        alive = process_env.worker_running(str(fx.root))
        spawn = ((started or {}).get("spawn") or {})
        ctx = fx.ctx
        service.observe(ctx, [{"source_event_key": f"survival-{case}", "text": "after the host ended"}])
        ingested = wait_for(lambda fx=fx, case=case: _count(fx, f"SELECT COUNT(*) FROM events WHERE source_event_key LIKE '%survival-{case}%'") > 0, 30)
        out[case] = {"spawned_by": spawn.get("spawned_by"), "method": spawn.get("method"), "independence": spawn.get("state"), "degraded_reasons": spawn.get("degraded_reasons"), "in_job": spawn.get("in_job"), "alive_after": bool(alive), "ingested_after": bool(ingested)}
        if case == "host_killed":
            out[case]["host_end"] = "process_tree_taskkill" if WINDOWS else "process_group_sigkill"
        if case == "host_killed":
            out["worker_killed_then_next_session"] = _recovery(fx)
        fx.stop_worker()
    return out


def _recovery(fx: Fixture) -> dict[str, Any]:
    """The worker itself is killed; work spooled meanwhile waits; the next host session's hook restarts it and it drains the backlog."""
    from recalith import service
    from recalith.fast import process_env

    pid = worker_pid(fx.root)
    if pid is not None:
        with contextlib.suppress(OSError):
            kill_pid(pid)
    gone = wait_for(lambda: not process_env.worker_running(str(fx.root)), 20)
    with contextlib.suppress(OSError):
        (fx.root / ".recalith" / "run" / process_env.START_STAMP).unlink()  # the 10 s start throttle is not what is under test
    service.observe(fx.ctx, [{"source_event_key": "recovery-backlog", "text": "spooled while no worker ran"}])
    with pc.RecordingEndpoint(scripted([], final="OK")) as ep:
        fx.session(b"Reply OK.", endpoint=ep)
    restarted = wait_for(lambda: process_env.worker_running(str(fx.root)), 30)
    spawn = ((_worker_status(fx.root) or {}).get("spawn") or {})
    drained = wait_for(lambda: _count(fx, "SELECT COUNT(*) FROM events WHERE source_event_key LIKE '%recovery-backlog%'") > 0, 30)
    return {"worker_killed": bool(gone), "worker_pid_read": pid is not None, "restarted_by": spawn.get("spawned_by") if restarted else None, "backlog_ingested": bool(drained)}


def _pty_spawn(argv: list[str], env: dict[str, str], cwd: Path, data: bytes) -> tuple[int, int]:
    import pty
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # the child only chdirs and execs (async-signal-safe), despite the endpoint's thread
        pid, master = pty.fork()
    if pid == 0:  # pragma: no cover - child
        os.chdir(cwd)
        os.execve(argv[0], argv, env)
    os.write(master, data)
    os.write(master, b"\x04")
    return pid, master


def _reap(pid: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        done, _status = os.waitpid(pid, os.WNOHANG)
        if done:
            return
        time.sleep(0.1)
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)


# --------------------------------------------------------------------------
# Target project and the whole certification


def fixture_target(root: Path, exe: str | None = None) -> Path:
    """A disposable target project integrated by the real installer (what an operator's project would be)."""
    from recalith.contracts.common import Actor, new_id
    from recalith.contracts.config import ProjectConfig
    from recalith.core import identity
    from recalith.integrations import claude as integration

    root.mkdir(parents=True)
    if shutil.which("git"):
        subprocess.run(["git", "init", "-q", str(root)], capture_output=True, env={"PATH": os.environ.get("PATH", "")}, timeout=60, check=False)
    identity.initialize_installation(root, ProjectConfig.defaults_for(new_id("proj")))
    ctx = identity.resolve_installation(root, actor=Actor(kind="operator", id="probe-harness", channel="cli"))
    integration.integrate(ctx, executable=exe)
    return root


def certify(exe: str, *, base: Path, modes: Sequence[str], target_root: Path | None, cfg: Mapping[str, Any] | None, live_reason: str | None = None) -> dict[str, Any]:
    """The whole engine-mode certification; writes the target's host record (``live`` only for a complete live run)."""
    from recalith.contracts.common import Actor, digest_of
    from recalith.core import identity
    from recalith.integrations import claude as integration

    base.mkdir(parents=True, exist_ok=True)
    version = integration.host_version(exe)["version"]
    report: dict[str, Any] = {"host_version": version, "engine_mode": True, "synthetic_states": [
        "nonce memories admitted with recorded proposals over real captured fixture events",
        "each trial enables only its own path in a controlled hook manifest",
        "the request-capture model is a loopback scripted endpoint",
    ]}
    target_mode = integration.configured_permission_mode(target_root) if target_root is not None else "default"
    if "request_capture" in modes:
        rc: dict[str, Any] = {}
        rc["lifecycle"] = lifecycle(base / "rc", exe)
        rc.update(delivery_trials(base / "rc", exe, mode="request_capture"))
        rc["command_rules"] = deny_probe(base / "rc", exe)
        rc["private_paths"] = private_path_probe(base / "rc", exe, permission_mode=target_mode)
        rc["notice"] = notice_probe(base / "rc", exe)
        rc["hook_failures"] = hook_failures(base / "rc", exe)
        rc["worker_survival"] = worker_survival(base / "rc", exe)
        report["request_capture"] = rc
    if "live" in modes and cfg is not None and live_reason is None:
        live = {"keys": list(cfg["platform_env_keys"]) + list(cfg["network_env_keys"]) + list(cfg["auth_route"]["env_keys"])}
        report["live"] = delivery_trials(base / "live", exe, mode="live", live=live, model=cfg["model"])
        report["live"]["status"] = "run"
    else:
        report["live"] = {"status": "not_run", "reason": live_reason or "live mode not selected"}
    report["report_digest"] = digest_of(json.loads(json.dumps(report, default=str)))
    if target_root is not None:
        ctx = identity.resolve_installation(target_root, actor=Actor(kind="operator", id="probe-harness", channel="cli"))
        rc = report.get("request_capture") or {}
        live = report["live"] if report["live"].get("status") == "run" else None
        summary = {
            "mode": "live" if live else "request_capture", "host_version": version, "report_digest": report["report_digest"],
            "paths": {p: {"state": (live["paths"][p]["state"] if live else (rc.get("paths") or {}).get(p, {}).get("state", "not_run"))} for p in PATHS},
            "command_rules": {"state": (rc.get("command_rules") or {}).get("state")}, "private_paths": {"state": (rc.get("private_paths") or {}).get("state")},
        }
        record = integration.write_host_record(ctx, summary)
        report["host_record"] = record.model_dump(mode="json")
        integration.integrate(ctx, executable=exe)  # re-run: enables exactly the paths the new record certifies
    return report


__all__ = ["certify", "fixture_target", "stop_workers", "Fixture", "delivery_trials", "deny_probe", "private_path_probe", "lifecycle", "worker_survival"]
