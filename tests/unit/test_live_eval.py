"""The live evaluation path (decision 0028): what can be checked without an account or a live session.

No model is called here. The live agent's stream parsing runs on the record
shape Claude Code 2.1.309 printed with ``--include-hook-events`` in request
capture (loopback endpoint, placeholder key; observed 2026-10-23 on native
Windows); the per-installation host-record binding runs against real
installations integrated with a synthetic ``claude`` that only answers
``--version``; a live trial runs with its provisioning, waits and agent
replaced by labeled fakes, so only the harness's own bookkeeping is under test.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "tools"), str(ROOT / "tests" / "integration")]

import probe_common as pc  # noqa: E402

# The 2.1.309 hook event records (request capture), session and hook ids as printed.
HOOK_STREAM = [
    {"type": "system", "subtype": "hook_started", "hook_id": "c3192ce8-74bf-4d41-8ac9-7a9aa8431e39", "hook_name": "SessionStart:startup", "hook_event": "SessionStart", "session_id": "3c604cd2-1676-4b48-ba81-5ace51e7e5cd"},
    {"type": "system", "subtype": "hook_response", "hook_id": "c3192ce8-74bf-4d41-8ac9-7a9aa8431e39", "hook_name": "SessionStart:startup", "hook_event": "SessionStart",
     "output": "{\"hookSpecificOutput\": {\"hookEventName\": \"SessionStart\", \"additionalContext\": \"CTXSTART7731\"}}\n",
     "stdout": "{\"hookSpecificOutput\": {\"hookEventName\": \"SessionStart\", \"additionalContext\": \"CTXSTART7731\"}}\n", "stderr": "", "exit_code": 0, "outcome": "success", "session_id": "3c604cd2-1676-4b48-ba81-5ace51e7e5cd"},
    {"type": "system", "subtype": "hook_response", "hook_id": "4317f5e1-bba9-4c0d-bec4-1b44118ea2e2", "hook_name": "UserPromptSubmit", "hook_event": "UserPromptSubmit",
     "output": "{\"hookSpecificOutput\": {\"hookEventName\": \"UserPromptSubmit\", \"additionalContext\": \"- [caution] Run the tests with PYTHONPATH=src.\"}}\n",
     "stdout": "{\"hookSpecificOutput\": {\"hookEventName\": \"UserPromptSubmit\", \"additionalContext\": \"- [caution] Run the tests with PYTHONPATH=src.\"}}\n", "stderr": "", "exit_code": 0, "outcome": "success", "session_id": "3c604cd2-1676-4b48-ba81-5ace51e7e5cd"},
    {"type": "system", "subtype": "hook_response", "hook_id": "02de03c8-3b03-4ac2-b52e-feeb29c4203f", "hook_name": "PreToolUse:Bash", "hook_event": "PreToolUse", "output": "", "stdout": "", "stderr": "",
     "exit_code": 0, "outcome": "success", "session_id": "3c604cd2-1676-4b48-ba81-5ace51e7e5cd"},
    {"type": "system", "subtype": "hook_response", "hook_name": "PostToolUse:Bash", "hook_event": "PostToolUse", "stdout": "", "exit_code": 0, "outcome": "success"},
]


def unmarked(monkeypatch) -> None:
    for marker in (*pc.DEFAULT_HOST_MARKERS, *pc.ROLE_MARKERS):
        monkeypatch.delenv(marker, raising=False)


# --------------------------------------------------------------------------
# The live agent's stream


def test_deliveries_come_from_the_hosts_hook_responses():
    from evals import agent

    got = agent.deliveries_from_stream(HOOK_STREAM)
    assert [(d.purpose, d.state) for d in got] == [("session_start", "emitted"), ("prompt", "emitted"), ("pre_action", "none")]  # PostToolUse delivers nothing
    assert got[0].context == "CTXSTART7731"
    assert [i.advice for i in agent.parse_items(got[1].context, "prompt")] == ["caution"]
    compact = dict(HOOK_STREAM[1], hook_name="SessionStart:compact")
    assert agent.deliveries_from_stream([compact])[0].purpose == "compact_restore"
    failed = dict(HOOK_STREAM[2], exit_code=1)
    assert agent.deliveries_from_stream([failed])[0].degradations == ["hook_exit_1"]
    assert agent.hook_records([failed])[0] == {"hook_event": "UserPromptSubmit", "hook_name": "UserPromptSubmit", "exit_code": 1, "outcome": "success"}  # no output kept


def test_actions_pair_tool_uses_with_results():
    from evals import agent

    stream = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "python -m unittest discover -s tests"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "Exit code 1\nModuleNotFoundError", "is_error": True}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "toolu_2", "name": "Bash", "input": {"command": "PYTHONPATH=src python -m unittest discover -s tests"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_2", "content": "OK", "is_error": False}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "toolu_3", "name": "Read", "input": {"file_path": "C:\\w\\README.md"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_3", "content": "1\tledger"}]}},
    ]
    actions = agent.actions_from_stream(stream, session="A")
    assert [(a.tool, a.exit_code) for a in actions] == [("Bash", 1), ("Bash", 0), ("Read", None)]
    assert actions[2].path == "C:\\w\\README.md"


def test_the_live_agent_runs_the_certified_session_shape():
    from evals import agent, live

    argv = agent.LiveClaudeAgent("claude.exe", "<agent-model>").argv()
    assert argv[0] == "claude.exe" and argv[1:1 + len(live.SESSION_FLAGS)] == list(live.SESSION_FLAGS)
    assert "--include-hook-events" in argv and "--strict-mcp-config" in argv and argv[argv.index("--model") + 1] == "<agent-model>"
    assert argv[argv.index("--allowedTools") + 1:] == list(live.AGENT_TOOLS)
    assert "--setting-sources" not in argv  # the disposable HOME's disabling settings must load (as the native-memory observation ran)


class Setup:
    """A labeled stand-in for ``live.LiveSetup`` (names only)."""

    def __init__(self, tmp: Path) -> None:
        self.token_file = tmp / "token.json"
        self.executable = "claude.exe"
        self.model = "<agent-model>"
        self.delivery = {"platform_env_keys": ["PATH", "SYSTEMROOT"], "network_env_keys": [], "auth_route": {"env_keys": ["RECALITH_TEST_AGENT_KEY"]}, "home_env": {"HOME": "{home}", "USERPROFILE": "{home}"},
                         "nonsecret_env": {"DISABLE_AUTOUPDATER": "1"}, "host_markers": list(pc.DEFAULT_HOST_MARKERS)}

    def label(self) -> dict:
        return {"backend": "anthropic_messages", "agent_model": "<agent-model>"}


def test_the_agent_environment_is_built_not_inherited(tmp_path, monkeypatch):
    from evals import baselines, live

    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("RECALITH_TEST_AGENT_KEY", "value-a")
    monkeypatch.setenv("RECALITH_TEST_CURATOR_KEY", "value-c")
    monkeypatch.setenv("RECALITH_TEST_UNRELATED", "x")
    env = live.agent_env(Setup(tmp_path), tmp_path / "h", route_keys=["RECALITH_TEST_CURATOR_KEY"])
    assert "CLAUDECODE" not in env and "RECALITH_TEST_UNRELATED" not in env
    assert env["RECALITH_TEST_AGENT_KEY"] == "value-a" and env["RECALITH_TEST_CURATOR_KEY"] == "value-c"  # the hook-started worker carries the route's keys
    assert env["HOME"] == env["USERPROFILE"] == str(tmp_path / "h") and env["DISABLE_AUTOUPDATER"] == "1"
    assert all(env[k] == v for k, v in baselines.DISABLE_ENV.items())
    assert env["PATH"].split(os.pathsep)[0] == live.python_dir() and "Scripts" not in Path(live.python_dir()).name


# --------------------------------------------------------------------------
# Quiescence between live sessions


def installation(tmp_path: Path) -> Path:
    from evals import trial

    ws = tmp_path / "ws"
    trial.copy_seed("ledgerlite", ws)
    trial.init_installation(ws, "ledgerlite", route="test_fixture", token_file=None, mode="scripted")
    return ws


def test_queue_state_reads_what_the_worker_still_owes(tmp_path):
    import time

    from evals import live

    ws = installation(tmp_path)
    now = time.time()
    assert live.queue_state(ws, now=now)["quiet"] is True
    conn = sqlite3.connect(ws / ".recalith" / "state" / "memory.sqlite")
    with conn:
        conn.execute("INSERT INTO jobs (job_id, kind, state, idempotency_key, priority, due_at, budget_pool, body) VALUES (?, 'extract_claims', 'pending', 'k1', 3, ?, 'ordinary', ?)",
                     ("job_test", live._utc(now + 90), json.dumps({"last_error_code": None})))
    conn.close()
    state = live.queue_state(ws, now=now)
    assert state["quiet"] is False and state["due_jobs"] == 1 and state["due_kinds"] == ["extract_claims"] and 80 <= state["next_due_in_s"] <= 100
    assert live.queue_state(ws, now=now, horizon=30)["quiet"] is True  # due beyond the horizon: the next session may start


def test_wait_quiescent_waits_for_due_work_and_reports_stalls(tmp_path, monkeypatch):
    from evals import live

    ws = tmp_path
    states = iter([{"quiet": False, "leased": 0, "next_due_in_s": 30.0, "progress": [1, 1, 0]}, {"quiet": False, "leased": 1, "next_due_in_s": 0.0, "progress": [2, 1, 0]},
                   {"quiet": True, "leased": 0, "next_due_in_s": None, "progress": [3, 1, 1]}])
    monkeypatch.setattr(live, "queue_state", lambda root, now, horizon: next(states))
    t = [0.0]
    slept: list[float] = []
    out = live.wait_quiescent(ws, clock=lambda: t[0], sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)), worker_running=lambda root: True)
    assert out["state"] == "quiet" and out["polls"] == 3 and slept == [30.0, live.POLL_SECONDS] and out["worker_seen"] is True
    stuck = {"quiet": False, "leased": 0, "next_due_in_s": 0.0, "progress": [5, 5, 5], "waiting_reasons": ["provider_unavailable"]}
    monkeypatch.setattr(live, "queue_state", lambda root, now, horizon: stuck)
    t[0] = 0.0
    out = live.wait_quiescent(ws, stall=60, clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s), worker_running=lambda root: False)
    assert out["state"] == "stalled" and out["worker_seen"] is False and out["last"]["waiting_reasons"] == ["provider_unavailable"]
    busy = iter(range(10_000))
    monkeypatch.setattr(live, "queue_state", lambda root, now, horizon: {"quiet": False, "leased": 0, "next_due_in_s": 0.0, "progress": [next(busy)]})
    t[0] = 0.0
    assert live.wait_quiescent(ws, deadline=120, clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s), worker_running=lambda root: True)["state"] == "deadline"


# --------------------------------------------------------------------------
# Host-record binding (tools/probe_delivery.py --bind-from)


def integrated(tmp_path: Path, name: str, exe: str):
    from recalith.contracts.common import Actor, new_id
    from recalith.contracts.config import ProjectConfig
    from recalith.core import identity
    from recalith.integrations import claude as integration

    root = tmp_path / name
    root.mkdir(parents=True)
    identity.initialize_installation(root, ProjectConfig.defaults_for(new_id("proj")))
    ctx = identity.resolve_installation(root, actor=Actor(kind="operator", id="test", channel="cli"))
    integration.integrate(ctx, executable=exe)
    return root, ctx


def certified_source(tmp_path: Path, exe: str, *, mode: str = "live") -> tuple[Path, dict]:
    """A source project with a host record written from a (synthetic) engine-mode report, and that report's section."""
    from recalith.contracts.common import digest_of
    from recalith.integrations import claude as integration

    root, ctx = integrated(tmp_path, "source", exe)
    digest = digest_of(["synthetic engine-mode report", mode])
    paths = {p: {"state": "healthy"} for p in ("session_start", "prompt", "pre_action", "compact")}
    record = integration.write_host_record(ctx, {"mode": mode, "host_version": "2.1.309", "report_digest": digest, "paths": paths, "command_rules": {"state": "denied_all_covered"}, "private_paths": {"state": "probed_limited"}})
    section = {"report_digest": digest, "host_version": "2.1.309", "live": {"status": "run" if mode == "live" else "not_run"}, "paths": paths, "host_record": record.model_dump(mode="json"),
               "request_capture": {"command_rules": {"state": "denied_all_covered"}, "private_paths": {"state": "probed_limited"}}, "tested_at": "2026-10-23T19:05:32.096230Z"}
    return root, {"sections": {"delivery_engine": {"claude_code": section}}}


def bind_cfg() -> dict:
    return {"host_markers": list(pc.DEFAULT_HOST_MARKERS), "host_id": "claude_code"}


def test_bind_writes_the_targets_record_from_the_certified_run(tmp_path, monkeypatch):
    import claude_scenarios as ccs
    import probe_delivery as pd
    from recalith.integrations import claude as integration
    from recalith.operations.health import load_host_certification

    unmarked(monkeypatch)
    exe = str(ccs.fake_claude(tmp_path / "bin", version="2.1.309"))
    source, evidence = certified_source(tmp_path, exe)
    target, tctx = integrated(tmp_path, "target", exe)
    assert integration.certified_paths(tctx, "2.1.309")[0] == []  # before: delivery off
    entry = pd.bind_record(bind_cfg(), source, target, evidence, executable=exe)
    state, record = load_host_certification(target, tctx.installation_id)
    assert state == "ok" and record.mode == "live" and record.installation_id == tctx.installation_id and record.command_rules == "installed"
    assert record.report_digest == evidence["sections"]["delivery_engine"]["claude_code"]["report_digest"]
    assert integration.certified_paths(tctx, "2.1.309") == (["session_start", "prompt", "pre_action", "compact_restore"], [])
    manifest = json.loads((target / ".recalith" / "run" / "hook-context.json").read_text(encoding="utf-8"))
    assert set(manifest["adapters"]["claude_code"]["delivery_paths"]) == {"session_start", "prompt", "pre_action", "compact_restore"}  # integrate re-ran
    assert entry["source_installation_id"] != entry["target_installation_id"] and entry["method"].startswith("bound from the live engine-mode certification")
    assert load_host_certification(source, record.installation_id)[0] == "invalid"  # the bound record is the target's own, not a copy


def test_bind_refuses_what_the_evidence_does_not_support(tmp_path, monkeypatch):
    import claude_scenarios as ccs
    import probe_delivery as pd

    unmarked(monkeypatch)
    exe = str(ccs.fake_claude(tmp_path / "bin", version="2.1.309"))
    source, evidence = certified_source(tmp_path, exe)
    target, _ctx = integrated(tmp_path, "target", exe)
    section = evidence["sections"]["delivery_engine"]["claude_code"]

    def refused(ev, *, executable=exe, src=source, dst=target) -> tuple[int, str]:
        with pytest.raises(pd.BindRefused) as exc:
            pd.bind_record(bind_cfg(), src, dst, ev, executable=executable)
        return exc.value.code, exc.value.reason

    assert refused({"sections": {}}) == (4, "evidence_section_missing")
    assert refused({"sections": {"delivery_engine": {"claude_code": {**section, "report_digest": "0" * 64}}}}) == (4, "evidence_digest_mismatch")
    assert refused({"sections": {"delivery_engine": {"claude_code": {**section, "live": {"status": "not_run"}}}}}) == (4, "evidence_not_a_live_run")
    newer = str(ccs.fake_claude(tmp_path / "bin2", version="2.1.310"))
    assert refused(evidence, executable=newer)[1].startswith("host_version_changed")  # another installed version needs its own certification
    assert refused(evidence, dst=source)[0] == 2  # the certified installation itself
    rc_root, rc_evidence = certified_source(tmp_path / "rc", exe, mode="request_capture")
    assert refused(rc_evidence, src=rc_root) == (4, "source_record_not_live")
    monkeypatch.setenv("CLAUDECODE", "1")
    assert refused(evidence)[0] == 6  # an operator action: never from a host-marked process
    assert not (target / ".recalith" / "host.json").exists()


def test_bind_mode_writes_only_the_bindings_report(tmp_path, monkeypatch):
    import claude_scenarios as ccs
    import probe_delivery as pd

    unmarked(monkeypatch)
    exe = str(ccs.fake_claude(tmp_path / "bin", version="2.1.309"))
    source, evidence = certified_source(tmp_path, exe)
    target, tctx = integrated(tmp_path, "target", exe)
    config = json.loads((ROOT / "tools" / "probe_config.anthropic_messages.example.json").read_text(encoding="utf-8"))
    config["delivery"]["executable"] = exe
    cfg_path, ev_path, out_path = tmp_path / "config.json", tmp_path / "evidence.json", tmp_path / "bindings.json"
    cfg_path.write_text(json.dumps(config), encoding="utf-8")
    ev_path.write_text(json.dumps(evidence), encoding="utf-8")
    before = ev_path.read_bytes()
    assert pd.main(["--config", str(cfg_path), "--engine-project", str(target), "--bind-from", str(source), "--evidence", str(ev_path), "--output", str(out_path)]) == 0
    assert ev_path.read_bytes() == before  # the evidence report is only read
    bound = json.loads(out_path.read_text(encoding="utf-8"))["sections"]["delivery_binding"][tctx.installation_id]
    assert bound["delivery"]["session_start"] == "certified" and str(target) not in json.dumps(bound) and str(tmp_path) not in json.dumps(bound)
    assert pd.main(["--config", str(cfg_path), "--engine-project", str(target), "--bind-from", str(source), "--output", str(out_path)]) == 2  # --evidence is required


def test_provisioning_runs_the_operators_own_tools_in_order(tmp_path, monkeypatch):
    from evals import live, trial

    argvs: list[list[str]] = []
    monkeypatch.setattr(trial, "init_installation", lambda ws, project, *, route, token_file, mode: argvs.append(["init", route, str(token_file), mode]))
    monkeypatch.setattr(live, "_child", lambda argv, *, step, steps, **kw: (argvs.append([step, *argv]), steps.append({"step": step, "exit": 0})))
    setup = live.LiveSetup(config=tmp_path / "c.json", token_file=tmp_path / "t.json", source_project=tmp_path / "pilot", evidence=tmp_path / "e.json", wheel=tmp_path / "r.whl",
                           expected_digest="d" * 64, wheelhouse=tmp_path / "wh", run_dir=tmp_path / "run", backend="anthropic_messages", executable="claude.exe", model="<agent-model>")
    ws = tmp_path / "ws"
    out = live.provision(ws, "ledgerlite", setup, label="smoke-L1.candidate")
    assert [a[0] for a in argvs] == ["init", "bootstrap", "route", "integrate", "bind_host_record"] and [s["step"] for s in out["steps"]] == ["init", "bootstrap", "route", "integrate", "bind_host_record"]
    assert argvs[0][1:] == ["operator_token", str(setup.token_file), "live"]  # the pre-init token; never the test-fixture route
    boot, route, integrate, bind = argvs[1], argvs[2], argvs[3], argvs[4]
    assert boot[boot.index("--wheel") + 1] == str(setup.wheel) and boot[boot.index("--expected-digest") + 1] == "d" * 64 and boot[boot.index("--wheelhouse") + 1] == str(setup.wheelhouse)
    assert route[2].endswith("probe_provider.py") and route[route.index("--route-out") + 1] == str(ws) and route[route.index("--backend") + 1] == "anthropic_messages"
    assert Path(route[route.index("--output") + 1]).parent == setup.run_dir / "certification"  # never the tracked report
    assert integrate[1] == str(live.launcher(ws)) and integrate[2:4] == ["integrate", "claude"] and integrate[integrate.index("--operator-token-file") + 1] == str(setup.token_file)
    assert bind[bind.index("--bind-from") + 1] == str(setup.source_project) and bind[bind.index("--engine-project") + 1] == str(ws) and bind[bind.index("--evidence") + 1] == str(setup.evidence)
    argvs.clear()
    live.provision(tmp_path / "day", "ledgerlite", setup, label="workload.ledgerlite", host=False)
    assert [a[0] for a in argvs] == ["init", "route"]  # a workload day has no host: no runtime, integration or host record


# --------------------------------------------------------------------------
# One live trial with labeled fakes (the harness's bookkeeping only)


class FakeLiveAgent:
    """Synthetic: returns a fixed session result in the live agent's shape; runs nothing."""

    def __init__(self) -> None:
        self.envs: list[dict] = []

    def run_session(self, name, prompts, ws, home, *, env):
        from evals import agent

        self.envs.append(env)
        actions = [agent.Action(name, "Bash", "python -m unittest discover -s tests", 1, None, "ModuleNotFoundError", 0, f"t{name}1"),
                   agent.Action(name, "Read", None, None, str(ws / "README.md"), "", 0, f"t{name}2")]
        deliveries = [agent.Delivery("prompt", "UserPromptSubmit", "- [context] Run the tests with PYTHONPATH=src.", None, "emitted", [], "")]
        return agent.SessionResult(name, f"host-session-{name}", actions, deliveries, 1.5, "Done.", 120, extra={"cost_usd": 0.0125, "runs": [{"exit": 0}]})


def fake_live(monkeypatch, calls: dict):
    from evals import live, trial

    def provision(ws, project, setup, *, label, host=True):
        calls.setdefault("provision", []).append(label)
        trial.init_installation(ws, project, route="test_fixture", token_file=None, mode="scripted")  # labeled stand-in for the operator's tools
        return {"route": "operator_token", "steps": [{"step": "init", "exit": 0}], "host": host, "stand_in": True}

    monkeypatch.setattr(live, "provision", provision)
    monkeypatch.setattr(live, "wait_quiescent", lambda ws, **kw: {"state": "quiet", "waited_s": 0.0})
    monkeypatch.setattr(live, "stop_worker", lambda ws, setup: calls.setdefault("stopped", []).append(ws.name) or {"state": "not_running"})
    monkeypatch.setattr(live, "agent_env", lambda setup, home, route_keys: {"HOME": str(home), "ROUTE_KEYS": ",".join(route_keys)})


def test_a_live_trial_records_its_sessions_gaps_and_manifest(tmp_path, monkeypatch):
    from evals import trial

    calls: dict = {}
    fake_live(monkeypatch, calls)
    fake = FakeLiveAgent()
    native = {"state": "disabled"}
    record = trial.run_trial("smoke-L1-ledgerlite-test-command", "candidate", tmp_path / "work", mode="live", native_memory=native, live=Setup(tmp_path), agent_factory=lambda: fake)
    assert "error" not in record, record.get("error_detail")
    assert record["mode"] == "live" and [s["name"] for s in record["sessions"]] == ["A", "B"]
    assert [g["before"] for g in record["gaps"]] == ["B", "measurement"] and len(record["horizon_checks"]) == 2
    assert record["sessions"][0]["actions"][1]["path"] == "README.md"  # workspace-relative, as the oracle's log
    assert record["sessions"][1]["deliveries"][0]["purpose"] == "prompt" and record["outcomes"]["foreground_cost_usd"] == 0.025
    assert record["outcomes"]["repeated_mistakes"] == 1  # session B repeated A's failed command
    manifest = record["manifest"]["candidate"]
    assert manifest["agent"]["live"] is True and manifest["agent"]["model"] == "<agent-model>" and manifest["native_memory"] == native
    assert manifest["recalith_installation"]["installation_id"].startswith("inst_") and calls["provision"] == ["smoke-L1-ledgerlite-test-command.candidate"]
    assert len(calls["stopped"]) == 1 and record["worker_stop"] == [{"state": "not_running"}]
    assert "oracle" in record and record["curator_calls"] == [] and isinstance(record["claims"], list)
    baseline = trial.run_trial("smoke-L1-ledgerlite-test-command", "no_memory", tmp_path / "work", mode="live", native_memory=native, live=Setup(tmp_path), agent_factory=lambda: fake)
    assert baseline["gaps"] == [] and baseline["manifest"]["no_memory"]["recalith_installation"] is None and baseline["worker_stop"] == []
    assert baseline["manifest"]["no_memory"]["label"] == "no_memory" and fake.envs[-1]["ROUTE_KEYS"] == ""


def test_the_report_reads_live_records(tmp_path, monkeypatch):
    """Live-shaped trial records (labeled fakes) and a failed live workload day go through the real report."""
    from evals import report, trial

    fake_live(monkeypatch, {})
    out = tmp_path / "results"
    (out / "trials").mkdir(parents=True)
    (out / "workload").mkdir()
    (out / "run.json").write_text(json.dumps({"run_schema": 1, "mode": "live", "versions": {}, "authorship": {}, "limitations": []}), encoding="utf-8")
    for arm in ("no_memory", "candidate"):
        record = trial.run_trial("smoke-L1-ledgerlite-test-command", arm, out / "work", mode="live", native_memory={"state": "disabled"}, live=Setup(tmp_path), agent_factory=FakeLiveAgent)
        (out / "trials" / f"smoke-L1-ledgerlite-test-command.{arm}.json").write_text(json.dumps(record, default=str), encoding="utf-8")
    (out / "workload" / "ledgerlite.json").write_text(json.dumps({"kind": "workload_day", "project": "ledgerlite", "mode": "live", "error": "route_failed"}), encoding="utf-8")
    built = report.build(out)
    assert built["mode"] == "live" and built["counts_toward_gate"] is True
    assert built["gate"]["state"] == "failed" and built["gate"]["superiority_claim"] is False
    assert built["cost_and_time"]["actual"]["foreground_cost_usd"] == 0.05  # two fake sessions per arm at 0.0125
    assert built["operational_5_2"]["budget_exhaustion"]["days_not_run"] == [{"project": "ledgerlite", "error": "route_failed", "detail": None}]
    report.markdown(built)
    # A live run that is incomplete fails its gate by omission, never passes it (ACCEPTANCE_TESTS §6.1).
    done = built["completeness"]
    assert done["smoke_trials_missing"] == 22 and done["workload_days_run"] == 0 and done["workload_days_not_run"] == ["ledgerlite"]
    assert set(done["demonstrations_unmet"]) == {"fresh_session_reuse", "changed_condition_revision", "forgetting_and_restore", "isolation", "zero_interventions"}
    reasons = built["gate"]["reasons"]
    assert any(r.startswith("smoke_trials_missing:22") for r in reasons) and any(r.startswith("workload_days_short:0/3") for r in reasons) and any(r.startswith("demonstrations_unmet:") for r in reasons)


def test_completeness_names_errors_and_contamination():
    from evals import report

    trials = [{"scenario": sid, "arm": arm, "manifest": {arm: {"label": arm}}} for sid in report.SMOKE_IDS for arm in ("candidate", "no_memory")]
    trials[0]["error"] = "route_failed"
    trials[1]["manifest"] = {"no_memory": {"label": "contaminated"}}
    days = [{"kind": "workload_day", "project": p, "budget": {}} for p in ("ledgerlite", "fieldnotes", "household")]
    demos = {"demonstrations": {n: {"demonstrated": True} for n in report.DEMONSTRATIONS}}
    done = report.completeness(trials, days, demos)
    assert done["smoke_trials_missing"] == 0 and done["trial_errors"] == [f"{trials[0]['scenario']}.candidate:route_failed"]
    assert done["contaminated_arms"] == [f"{trials[1]['scenario']}.no_memory"] and done["workload_days_run"] == 3 and done["demonstrations_unmet"] == []
    clean = report.completeness([dict(t, error=None, manifest={t["arm"]: {"label": t["arm"]}}) for t in trials], days, demos)
    assert clean["complete"] is True


def test_a_failed_provisioning_is_recorded_never_dropped(tmp_path, monkeypatch):
    from evals import live, trial

    calls: dict = {}
    fake_live(monkeypatch, calls)

    def refused(ws, project, setup, *, label, host=True):
        raise live.LiveError("route_failed", "exit 4: uncertified", [{"step": "init", "exit": 0}, {"step": "bootstrap", "exit": 0}, {"step": "route", "exit": 4}])

    monkeypatch.setattr(live, "provision", refused)
    record = trial.run_trial("smoke-L1-ledgerlite-test-command", "candidate", tmp_path / "work", mode="live", live=Setup(tmp_path), agent_factory=FakeLiveAgent)
    assert record["error"] == "route_failed" and record["provisioning_steps"][-1] == {"step": "route", "exit": 4}
    assert record["outcomes"]["task_success"] is False and record["sessions"] == [] and record["worker_stop"] == []
    with pytest.raises(trial.TrialError) as missing:
        trial.run_trial("smoke-L1-ledgerlite-test-command", "candidate", tmp_path / "w2", mode="live")
    assert missing.value.code == "live_setup_missing"


def test_live_setup_refuses_missing_or_uncertified_inputs(tmp_path):
    from evals import live

    with pytest.raises(live.LiveError) as missing:
        live.load_setup(config=None, token_file=None, source_project=None, evidence=None, wheel=None, wheelhouse=None, run_dir=tmp_path)
    assert missing.value.code == "live_inputs_missing" and "--operator-token-file" in missing.value.detail
    token, wheel, house = tmp_path / "token.json", tmp_path / "recalith-0.1.0.dev0-py3-none-any.whl", tmp_path / "wheelhouse"
    token.write_text("{}", encoding="utf-8")
    wheel.write_bytes(b"not the certified build")
    house.mkdir()
    source = tmp_path / "source" / ".recalith"
    source.mkdir(parents=True)
    (source / "engine.lock").write_text('lock_schema = 1\nengine_version = "0.1.0.dev0"\nartifact_sha256 = "' + "a" * 64 + '"\n', encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text((ROOT / "tools" / "probe_config.anthropic_messages.example.json").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(live.LiveError) as build:
        live.load_setup(config=config, token_file=token, source_project=tmp_path / "source", evidence=None, wheel=wheel, wheelhouse=house, run_dir=tmp_path)
    assert build.value.code == "wheel_not_certified_build"  # the trial installations run the certified project's own build


def test_the_certified_route_backend_records_calls_and_forwards_the_rest(tmp_path):
    from evals import live, trial

    class Backend:
        provider_id = "p"
        unavailable_reason = None

        def launch(self, request, *, timeout_s, purpose):
            from recalith.controller.worker import LaunchOutcome

            return LaunchOutcome(stdout=b"{}", overflowed=False, timed_out=False, returncode=0, duration_ms=1, stderr=b"", tree_bound=True)

    seen = []
    rec = live.CallRecorder(Backend(), on_call=seen.append)
    rec.launch(json.dumps({"job_id": "job_1"}).encode("utf-8"), timeout_s=5, purpose="extract_claims")
    assert rec.provider_id == "p" and rec.unavailable_reason is None
    assert seen[0]["purpose"] == "extract_claims" and seen[0]["job_id"] == "job_1" and seen[0]["returncode"] == 0
    ws = installation(tmp_path)
    with pytest.raises(live.LiveError) as uncertified:
        live.certified_backend(trial.context(ws))
    assert uncertified.value.code == "route_uncertified" and "provider_not_configured" in uncertified.value.detail


def test_live_demonstrations_never_fall_back_to_scripted_trials(tmp_path):
    from evals import demos

    trials = tmp_path / "trials"
    trials.mkdir()
    (trials / "smoke-L1-ledgerlite-test-command.candidate.json").write_text(json.dumps({"mode": "scripted", "outcomes": {}}), encoding="utf-8")
    out = demos.run_all(tmp_path / "work-demos", trials_dir=trials, mode="live", live_setup=Setup(tmp_path), live_work=tmp_path / "work")
    assert out["mode"] == "live"
    for name in ("fresh_session_reuse", "changed_condition_revision", "forgetting_and_restore", "isolation"):
        assert out["demonstrations"][name]["demonstrated"] is False and "LookupError" in out["demonstrations"][name]["error"], name


def test_live_workload_days_need_the_live_setup(tmp_path):
    from evals import workload

    assert workload.run_day("ledgerlite", tmp_path, mode="live")["error"] == "live_setup_missing"
    assert workload.run_day("ledgerlite", tmp_path, mode="other")["error"] == "unknown_mode"
