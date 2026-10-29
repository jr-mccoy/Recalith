"""One smoke trial: one scenario, one arm (ACCEPTANCE_TESTS §6, §6.1; decision 0020).

A trial copies the scenario's seed project into a disposable workspace with a
private home, gives the candidate arm its own fresh, independent Recalith
installation (the clean ``no_memory`` arm gets none), and runs the scenario's
fresh sessions in order — A learns, B applies, C changes evidence — applying
each session's overlays first. Between sessions the candidate's worker drains
its queue on the trial's virtual clock (a deterministic acceleration of
scheduling only).

**No future evidence.** Before every session :func:`evidence_horizon` checks
that the installation's store holds events only from sessions that already
ran and none captured after the session's start time; a violation stops the
trial (``future_evidence``). Workspaces, stores and homes are per trial and
per arm, so no trial's retrieval store can contain another trial's sessions.

The task oracle (``evals/oracles/smoke.py``) judges the final artifacts and the
action log after the scenario's oracle session, never memory text.

Initialization routes for the candidate installation:

* ``operator_token`` — ``recalith init --operator-token-file FILE`` as a child
  process inheriting this harness's environment unchanged. The file is an
  operator- or CI-provisioned pre-init token (created at a real terminal with
  ``recalith operator-token create``); the harness never creates one. From a
  host-marked process the guard refuses (exit 6), and the trial reports that.
* ``test_fixture`` — the engine's own initializer in process, exactly as the
  test suites build installations. Allowed only for ``scripted`` runs and
  always labeled; it is not an operator workflow.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "evals" / "scenarios" / "smoke"
EVAL_PROJECT_IDS = {
    "ledgerlite": "proj_70707070-7070-4070-8070-707070707071",
    "fieldnotes": "proj_70707070-7070-4070-8070-707070707072",
    "household": "proj_70707070-7070-4070-8070-707070707073",
}
START = "2026-11-02T09:00:00.000000Z"
SESSION_GAP_SECONDS = 2 * 3600
IDLE_STEP_SECONDS = 30
IDLE_HORIZON_SECONDS = 3 * 3600
DELIVERY_PATHS = ["session_start", "prompt", "pre_action", "compact_restore"]
HOST_VERSION = "2.1.305"  # the reviewed fixture format the scripted payloads follow


class TrialError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def scenarios() -> dict[str, dict[str, Any]]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(SMOKE.glob("smoke-*.json"))}


def domain(project: str) -> str:
    return "general" if project == "household" else "coding"


def copy_seed(project: str, ws: Path) -> None:
    shutil.copytree(ROOT / "evals" / "projects" / project, ws, ignore=shutil.ignore_patterns(".git", "__pycache__", ".recalith"))


def apply_overlays(ws: Path, session: dict[str, Any]) -> list[str]:
    applied = []
    for target, ref in session.get("overlay_files", {}).items():
        dest = ws / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SMOKE / "overlays" / ref[len("@file:"):], dest)
        applied.append(target)
    return applied


# --------------------------------------------------------------------------
# Installations


def init_installation(ws: Path, project: str, *, route: str, token_file: Path | None, mode: str) -> dict[str, Any]:
    """Initialize the candidate's independent installation by the named route (see the module docstring)."""
    if route == "operator_token":
        if token_file is None:
            raise TrialError("operator_token_not_provisioned", "pass --operator-token-file: a pre-init token an operator created at a real terminal")
        launcher = [sys.executable, "-m", "recalith"]
        proc = subprocess.run([*launcher, "init", "--project", str(ws), "--profile", domain(project), "--release-profile", "claude_preview", "--operator-token-file", str(token_file), "--json"],
                              capture_output=True, text=True, encoding="utf-8", timeout=120, check=False, env=dict(os.environ))
        if proc.returncode != 0:
            reason = None
            try:
                reason = (json.loads(proc.stdout or "{}").get("refusal") or {}).get("reason")
            except ValueError:
                pass
            raise TrialError("operator_guard_refused" if proc.returncode == 6 else "init_failed", f"exit {proc.returncode}{': ' + reason if reason else ''}")
        return {"route": "operator_token", "exit": 0}
    if route == "test_fixture":
        if mode != "scripted":
            raise TrialError("test_fixture_route_refused", "the in-process initializer is a test fixture route, allowed only for scripted runs")
        from recalith import service

        service.initialize(ws, domain_profile=domain(project), release_profile="claude_preview")
        return {"route": "test_fixture", "label": "in-process engine initializer, as the test suites build installations; not an operator workflow"}
    raise TrialError("unknown_init_route", route)


def context(ws: Path):
    from recalith.contracts.common import Actor
    from recalith.core import identity

    return identity.resolve_installation(ws, actor=Actor(kind="controller", id="eval-harness", channel="worker"))


def controlled_manifest(ws: Path) -> dict[str, Any]:
    """Scripted runs only: a controlled hook manifest enabling delivery (never a certification of any path)."""
    from recalith.capture.hooks import write_hook_context

    write_hook_context(context(ws), adapter_id="claude_code", host_version=HOST_VERSION, worker_autostart=False, delivery_paths=DELIVERY_PATHS, session_notice=False)
    return {"kind": "controlled_test_manifest", "host_version": HOST_VERSION, "delivery_paths": DELIVERY_PATHS, "worker_autostart": False, "certified": False}


# --------------------------------------------------------------------------
# The worker on the virtual clock


class VirtualClock:
    """The worker's clock over the trial's capture clock (``agent.Clock``)."""

    def __init__(self, clock: Any) -> None:
        self.c = clock

    def now(self) -> str:
        return self.c.now()

    def wall(self) -> float:
        from recalith.contracts.common import parse_utc

        return parse_utc(self.c.now()).timestamp()

    def monotonic(self) -> float:
        return self.wall()

    def wait(self, seconds: float, event: threading.Event) -> bool:
        self.c.advance(seconds)
        return event.wait(0.0005)


class Drainer:
    """Drives the installation's real worker (deterministic lane and model lane) with a given backend."""

    def __init__(self, ws: Path, clock: Any, backend: Any, *, provider: Any = None) -> None:
        from recalith.controller import requests, worker
        from recalith.fast import process_env

        self.ws = ws
        self.clock = clock
        self.backend = backend
        self.ctx = context(ws)
        self.lock = process_env.InstallationLock(ws)
        if not self.lock.try_acquire():
            raise TrialError("worker_lock_held", "another worker holds this evaluation installation")
        vclock = VirtualClock(clock)
        runtime = worker.ModelRuntime(backend=backend, prepare=requests.runtime_preparer(self.ctx, now=clock.now))
        # ``provider``: the production supervisor of a certified route (live workload days); the lane launches only while it is available.
        self.w = worker.Worker(self.ctx, clock=vclock, model=runtime, owner="eval-harness", provider=provider)
        self.w.startup()
        self.busy_seconds = 0.0
        self.polls = 0

    def drain(self, *, horizon: float = IDLE_HORIZON_SECONDS, limit: int = 20000) -> dict[str, Any]:
        """Poll until nothing worked for ``horizon`` virtual seconds; returns what ran."""
        idle = 0.0
        worked_total = 0
        began = time.monotonic()
        for _ in range(limit):
            self.polls += 1
            worked = self.w.poll_once()
            launched = self.w.lane.step() if self.w.lane is not None else False
            if worked or launched:
                worked_total += 1
                idle = 0.0
                self.clock.advance(1)
                continue
            idle += IDLE_STEP_SECONDS
            if idle >= horizon:
                break
            self.clock.advance(IDLE_STEP_SECONDS)
        self.busy_seconds += time.monotonic() - began
        return {"worked_polls": worked_total, "virtual_idle_horizon_s": horizon}

    def close(self) -> None:
        try:
            self.w.close()
        finally:
            self.lock.release()


# --------------------------------------------------------------------------
# Evidence horizon (test_replay_cannot_see_future_evidence)


def evidence_horizon(ws: Path, *, allowed_host_sessions: set[str], not_after: str, ingest: bool = True) -> dict[str, Any]:
    """The store holds only events of sessions that already ran, none captured after ``not_after``.

    Segments still in the spool are ingested first (what the worker would do next), so evidence waiting
    there is judged too. Delivery receipts are bookkeeping, not evidence, and are not judged. A live trial
    passes ``ingest=False``: its own hook-started worker ingests, and the check runs after the queue is
    quiet (``live.wait_quiescent`` reports the spool), read-only.
    """
    from recalith.capture import pipeline
    from recalith.storage import db

    if ingest:
        pipeline.ingest_ready(context(ws))
    with db.open_store(context(ws), readonly=True) as store, store.read() as view:
        rows = view.execute("SELECT s.host_session_id, MAX(e.recorded_at), COUNT(*) FROM events e LEFT JOIN sessions s ON s.session_id = e.session_id WHERE e.kind != 'memory_delivered' GROUP BY e.session_id").fetchall()
    foreign = sorted(h for h, _at, _n in rows if h is not None and h not in allowed_host_sessions)
    late = sorted(h for h, at, _n in rows if at is not None and at > not_after)
    if foreign or late:
        raise TrialError("future_evidence", f"{len(foreign)} later or foreign host sessions, {len(late)} sessions captured after {not_after}")
    return {"checked_at": not_after, "host_sessions": len(rows), "events": sum(n for _h, _at, n in rows)}


# --------------------------------------------------------------------------
# Retrieval points and measures


def retrieval_points(spec: dict[str, Any], sessions: dict[str, Any], *, terms: list[list[str]]) -> list[dict[str, Any]]:
    from evals.agent import parse_items

    out = []
    for point in spec["gold"].get("expected_retrieval_points", []):
        result = sessions.get(point["session"])
        if result is None:
            continue
        items = [i for d in result.deliveries if d.purpose == point["purpose"] and d.context for i in parse_items(d.context, d.purpose)]
        delivered = any(d.purpose == point["purpose"] for d in result.deliveries)
        satisfied: bool | None
        if "must_include" in point:
            satisfied = any(point["must_include"] in i.text for i in items)
        elif "must_not_include" in point:
            needle = point["must_not_include"]
            if needle.endswith(" as current"):
                needle = needle[: -len(" as current")].lstrip("$")
                satisfied = not any(needle in i.text and i.freshness == "current" and i.advice in ("caution", "context") for i in items)
            else:
                satisfied = not any(needle in i.text for i in items)
        elif "must_not_include_caution" in point:
            satisfied = not any(point["must_not_include_caution"] in i.text and i.advice == "caution" for i in items)
        elif "max_caution_items" in point:
            satisfied = sum(1 for i in items if i.advice == "caution") <= point["max_caution_items"]
        elif point.get("advice") == "conflict_or_freshness_label":
            needles = [t for ts in terms for t in ts] or [""]
            related = [i for i in items if any(n.lower() in i.text.lower() for n in needles)]
            satisfied = bool(related) and all(i.advice == "conflict" or i.freshness != "current" for i in related)
        else:
            satisfied = None
        out.append({"spec": point, "delivered": delivered, "items": [{"advice": i.advice, "freshness": i.freshness, "text": i.text[:160]} for i in items][:8], "satisfied": satisfied})
    return out


def claim_heads(ws: Path) -> list[dict[str, Any]]:
    from recalith.storage import db, records

    with db.open_store(context(ws), readonly=True) as store, store.read() as view:
        rows = view.execute("SELECT claim_id, revision, status FROM claim_heads ORDER BY claim_id").fetchall()
        out = []
        for claim_id, revision, status in rows:
            body = records.body(view, "claim", claim_id, revision) or {}
            out.append({"claim_id": claim_id, "status": status, "kind": body.get("kind"), "basis": body.get("basis"), "strength": body.get("strength"),
                        "freshness": body.get("freshness"), "proposition": body.get("proposition"), "revision": revision})
    return out


def background_usage(ws: Path) -> dict[str, Any]:
    """Model calls and the engine's charged estimates (the recorded backend reports no provider usage)."""
    from recalith.controller import budgets
    from recalith.storage import db

    calls = tokens_in = tokens_out = 0
    by_purpose: dict[str, int] = {}
    with db.open_store(context(ws), readonly=True) as store, store.read() as view:
        days = [r[0] for r in view.execute("SELECT DISTINCT utc_day FROM provider_usage").fetchall()]
        for day in days:
            for res in budgets.reservations(view, day):
                if res.state != "charged":
                    continue
                used_in, used_out = budgets.actual_usage(res)
                calls += 1
                tokens_in += used_in
                tokens_out += used_out
                by_purpose[res.purpose] = by_purpose.get(res.purpose, 0) + 1
        jobs = dict(view.execute("SELECT state, COUNT(*) FROM jobs WHERE kind != 'ingest' GROUP BY state").fetchall())
    return {"model_calls": calls, "estimated_input_tokens": tokens_in, "estimated_output_tokens": tokens_out, "tokens": tokens_in + tokens_out, "calls_by_purpose": by_purpose, "jobs_by_state": jobs,
            "usage_source": "engine estimates charged by the budget ledger (no provider usage reported)"}


def same_session_learning(result: Any) -> list[dict[str, Any]]:
    """After a failure, the next action's pre-action packet in the same session: did it carry a caution? (scripted timing)."""
    out = []
    pre = [d for d in result.deliveries if d.purpose == "pre_action"]
    for i, action in enumerate(result.actions):
        if action.tool != "Bash" or not action.exit_code:
            continue
        later = pre[i + 1:i + 2]
        if later:
            out.append({"failure": action.command, "next_pre_action_state": later[0].state, "caution_delivered": "[caution]" in (later[0].context or "")})
    return out


def outcomes(spec: dict[str, Any], sessions: dict[str, Any], judged: dict[str, Any], background: dict[str, Any]) -> dict[str, Any]:
    order = [s["name"] for s in spec["sessions"]]
    failed_before: set[str] = set()
    repeated = detours = 0
    for name in order:
        result = sessions.get(name)
        if result is None:
            continue
        for action in result.actions:
            if action.tool == "Bash" and action.exit_code:
                if name != order[0] and action.command in failed_before:
                    repeated += 1
                elif name != order[0]:
                    detours += 1
        failed_before |= {a.command for a in result.actions if a.tool == "Bash" and a.exit_code}
    checks = judged.get("checks", {})
    retry = checks.get("plain_retry_succeeded") if "plain_retry_succeeded" in checks else None
    return {
        "task_success": bool(judged.get("passed")), "repeated_mistakes": repeated, "detours": detours, "legitimate_retry_success": retry,
        "foreground_tokens": sum(r.foreground_tokens_estimate for r in sessions.values()), "background_tokens": background.get("tokens", 0),
        "elapsed_seconds": round(sum(r.elapsed_seconds for r in sessions.values()), 3), "operator_interventions": 0,
    }


# --------------------------------------------------------------------------
# The trial


def run_trial(sid: str, arm: str, out_dir: Path, *, mode: str = "scripted", init_route: str = "test_fixture", token_file: Path | None = None, native_memory: dict[str, Any] | None = None,
              live: Any = None, agent_factory: Any = None) -> dict[str, Any]:
    from evals import agent, baselines, curator
    from evals.oracles import smoke
    from evals.report import GOLD_TERMS

    spec = scenarios()[sid]
    if mode == "live":
        if live is None:
            raise TrialError("live_setup_missing", "a live trial needs the operator's live setup (evals/run.py --mode live)")
        return run_live_trial(sid, arm, out_dir, spec=spec, setup=live, native_memory=native_memory or {}, agent_factory=agent_factory)
    if mode != "scripted":
        raise TrialError("unknown_mode", mode)
    base = out_dir / sid / arm
    if base.exists():
        shutil.rmtree(base)
    ws, home = base / "ws", base / "home"
    home.mkdir(parents=True)
    copy_seed(spec["project"], ws)
    baselines.prepare_home(home)
    clock = agent.Clock(START)
    record: dict[str, Any] = {"trial_schema": 1, "scenario": sid, "arm": arm, "category": spec["category"], "project": spec["project"], "mode": mode, "gold": spec["gold"],
                              "authorship": spec["authorship"], "sessions": [], "horizon_checks": []}
    drainers: list[Any] = []
    installation = None
    side: dict[str, Any] = {}
    try:
        if arm == "candidate":
            installation = {"init": init_installation(ws, spec["project"], route=init_route, token_file=token_file, mode=mode), "manifest": controlled_manifest(ws)}
            ctx = context(ws)
            installation.update(installation_id=ctx.installation_id, project_id=ctx.project_id)
            plan = curator.SmokePlan(sid)
            backend = curator.RecordedCurator(plan)
            main = Drainer(ws, clock, backend)
            drainers.append(main)
            host: Any = agent.HookBridge(ws, home, clock)
        else:
            plan, backend, main, host = None, None, None, agent.NoHost(home, clock)
        results: dict[str, Any] = {}
        ran_host_sessions: set[str] = set()
        for index, session in enumerate(spec["sessions"]):
            name = session["name"]
            if index:
                clock.advance(SESSION_GAP_SECONDS)
            overlays = apply_overlays(ws, session)
            if sid == "smoke-C4-cross-project-near-match" and name == "A":
                # Session A belongs to the separate ledgerlite project with its own installation (the conflicting second project).
                result, side = _second_project_session(spec, session, arm, base, clock, mode=mode, init_route=init_route, token_file=token_file)
                results[name] = result
                record["sessions"].append({"name": name, "project": "ledgerlite", "host_session_id": result.session_id, "overlays": overlays, "second_project": True, "actions": [a.log() for a in result.actions]})
                continue
            if main is not None:
                record["horizon_checks"].append({"before": name, **evidence_horizon(ws, allowed_host_sessions=ran_host_sessions, not_after=clock.now())})
            seed = f"{sid}:{arm}"
            if plan is not None:
                import uuid

                plan.sessions[name] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"recalith-eval:{seed}:{name}"))
            result = agent.run_scripted(spec["oracle"]["check"], name, session["prompts"], ws, host, seed=seed)
            results[name] = result
            ran_host_sessions.add(result.session_id)
            drained = main.drain() if main is not None else None
            record["sessions"].append({"name": name, "project": spec["project"], "host_session_id": result.session_id, "overlays": overlays, "actions": [a.log() for a in result.actions],
                                       "deliveries": [{"purpose": d.purpose, "state": d.state, "at": d.at, "items": len(agent.parse_items(d.context or "", d.purpose)), "degradations": d.degradations,
                                                       "context": (d.context or "")[:4000] or None} for d in result.deliveries],
                                       "elapsed_seconds": round(result.elapsed_seconds, 3), "reply": result.reply, "drain": drained})
            if name == spec["oracle"]["session"]:
                break
        actions = [a.log() for r in results.values() for a in r.actions]
        judged = smoke.judge(spec["oracle"]["check"], ws, actions, spec["oracle"]["session"])
        background = background_usage(ws) if main is not None else {"model_calls": 0, "tokens": 0}
        record["oracle"] = judged
        record["outcomes"] = outcomes(spec, results, judged, background)
        record["background"] = {**background, "harness_drain_seconds": round(sum(d.busy_seconds for d in drainers), 3)}
        record["curator_calls"] = backend.calls if backend is not None else []
        record["claims"] = claim_heads(ws) if main is not None else []
        record["retrieval_points"] = retrieval_points(spec, results, terms=GOLD_TERMS.get(sid, [])) if main is not None else []
        record["same_session_learning"] = [x for r in results.values() for x in same_session_learning(r)] if main is not None else []
        record["second_project"] = side or None
        record["hook_replies"] = len(host.replies)
        record["manifest"] = {arm: baselines.manifest(arm, mode=mode, ws=ws, home=home, native_memory=native_memory or {}, installation=installation,
                                                          agent={"kind": "scripted", "policy": f"evals/agent.py:{spec['oracle']['check']}", "live": False})}
    except TrialError as exc:
        record["error"] = exc.code
        record["error_detail"] = exc.detail
        record.setdefault("outcomes", {"task_success": False, "repeated_mistakes": None, "detours": None, "legitimate_retry_success": None, "foreground_tokens": None, "background_tokens": None, "elapsed_seconds": None, "operator_interventions": 0})
        record.setdefault("manifest", {arm: baselines.manifest(arm, mode=mode, ws=ws, home=home, native_memory=native_memory or {}, installation=installation, agent={"kind": "scripted", "live": False})})
    finally:
        for d in drainers:
            d.close()
    return record


def _second_project_session(spec: dict[str, Any], session: dict[str, Any], arm: str, base: Path, clock: Any, *, mode: str, init_route: str, token_file: Path | None) -> tuple[Any, dict[str, Any]]:
    """C4 session A in an independent ledgerlite workspace (an installation of its own for the candidate)."""
    from evals import agent, curator

    ws2 = base / "second-project" / "ws"
    home2 = base / "second-project" / "home"
    home2.mkdir(parents=True)
    copy_seed("ledgerlite", ws2)
    info: dict[str, Any] = {"project": "ledgerlite"}
    if arm == "candidate":
        info["init"] = init_installation(ws2, "ledgerlite", route=init_route, token_file=token_file, mode=mode)
        info["manifest"] = controlled_manifest(ws2)
        info["installation_id"] = context(ws2).installation_id
        backend = curator.RecordedCurator(curator.SmokePlan(spec["id"] + ":ledgerlite"))
        drainer = Drainer(ws2, clock, backend)
        try:
            result = agent.run_scripted("c4", "A", session["prompts"], ws2, agent.HookBridge(ws2, home2, clock), seed=f"{spec['id']}:{arm}:second")
            drainer.drain()
        finally:
            drainer.close()
        info["claims"] = claim_heads(ws2)
        info["curator_calls"] = backend.calls
    else:
        result = agent.run_scripted("c4", "A", session["prompts"], ws2, agent.NoHost(home2, clock), seed=f"{spec['id']}:{arm}:second")
    return result, info


# --------------------------------------------------------------------------
# The live trial (decisions 0020, 0028)


def curator_calls(ws: Path) -> list[dict[str, Any]]:
    """The worker's model calls as the store recorded them: each persisted proposal's purpose and operation kinds."""
    from recalith.storage import db

    out = []
    with db.open_store(context(ws), readonly=True) as store, store.read() as view:
        for kind, body in view.execute("SELECT j.kind, p.body FROM proposals p JOIN jobs j ON j.job_id = p.job_id ORDER BY p.rowid").fetchall():
            try:
                ops = [o.get("kind") for o in (json.loads(body) or {}).get("operations", [])] if body else []
            except (ValueError, AttributeError):
                ops = []
            out.append({"purpose": kind, "operations": ops, "body_retained": body is not None})
    return out


def _relative_paths(result: Any, ws: Path) -> None:
    """The live action log names files as the host did (absolute); the oracle's log is workspace-relative."""
    roots = sorted({str(ws), str(ws).replace("\\", "/"), str(ws.resolve()), str(ws.resolve()).replace("\\", "/")}, key=len, reverse=True)
    for action in result.actions:
        if action.path:
            for root in roots:
                if action.path.lower().startswith(root.lower()) if os.name == "nt" else action.path.startswith(root):
                    action.path = action.path[len(root):].lstrip("/\\").replace("\\", "/")
                    break


def _live_session_log(name: str, project: str, result: Any, overlays: list[str], host_version: str) -> dict[str, Any]:
    from evals import agent

    return {"name": name, "project": project, "host_session_id": result.session_id, "overlays": overlays, "actions": [a.log() for a in result.actions],
            "deliveries": [{"purpose": d.purpose, "state": d.state, "at": d.at, "items": len(agent.parse_items(d.context or "", d.purpose)), "degradations": d.degradations,
                            "context": (d.context or "")[:4000] or None} for d in result.deliveries],
            "elapsed_seconds": round(result.elapsed_seconds, 3), "reply": result.reply, "agent": result.extra, "foreground_tokens": result.foreground_tokens_estimate,
            "host_version": host_version, "suspended": bool(result.extra.get("suspended"))}


def run_live_trial(sid: str, arm: str, out_dir: Path, *, spec: dict[str, Any], setup: Any, native_memory: dict[str, Any], agent_factory: Any = None) -> dict[str, Any]:
    """One live trial: the real Claude Code CLI as the working agent, real installed hooks, the hook-started worker on the
    installation's own certified route, on real time. Between sessions the queue is waited quiet (``live.wait_quiescent``)."""
    from recalith.contracts.common import utc_now

    from evals import agent, baselines, live
    from evals.oracles import smoke
    from evals.report import GOLD_TERMS

    base, ws_name, home_name = live.trial_dirs(out_dir, sid, arm)
    if base.exists():
        shutil.rmtree(base)
    ws, home = base / ws_name, base / home_name
    home.mkdir(parents=True)
    copy_seed(spec["project"], ws)
    baselines.prepare_home(home)
    worker = agent_factory() if agent_factory is not None else agent.LiveClaudeAgent(setup.executable, setup.model)
    record: dict[str, Any] = {"trial_schema": 1, "scenario": sid, "arm": arm, "category": spec["category"], "project": spec["project"], "mode": "live", "gold": spec["gold"],
                              "authorship": spec["authorship"], "sessions": [], "horizon_checks": [], "gaps": [], "live": setup.label(), "workspace": ws.relative_to(out_dir).as_posix()}
    owned: list[Path] = []
    installation: dict[str, Any] | None = None
    side: dict[str, Any] = {}
    agent_record = {"kind": "claude_code", "live": True, "model": "<agent-model>", "invocation": [*live.SESSION_FLAGS, "--permission-mode", "acceptEdits", "--allowedTools", *live.AGENT_TOOLS]}
    try:
        live.check_host(setup, worker)  # before provisioning spends the route certification's calls
        if arm == "candidate":
            installation = {"init": live.provision(ws, spec["project"], setup, label=f"{sid}.{arm}"), "manifest": {"kind": "integrate claude", "delivery": "bound live record (decision 0028)"}}
            owned.append(ws)
            ctx = context(ws)
            installation.update(installation_id=ctx.installation_id, project_id=ctx.project_id)
        results: dict[str, Any] = {}
        ran: set[str] = set()
        for index, session in enumerate(spec["sessions"]):
            name = session["name"]
            if installation is not None and index:
                # The earlier sessions' curation settles on the files they saw, as a recorded run drains before the next overlay.
                record["gaps"].append({"before": name, **live.wait_quiescent(ws)})
            overlays = apply_overlays(ws, session)
            if sid == "smoke-C4-cross-project-near-match" and name == "A":
                result, side, version = _live_second_project(spec, session, arm, base, setup, worker, owned)
                results[name] = result
                record["sessions"].append({**_live_session_log(name, "ledgerlite", result, overlays, version), "second_project": True})
                continue
            if installation is not None:
                record["horizon_checks"].append({"before": name, **evidence_horizon(ws, allowed_host_sessions=ran, not_after=utc_now(), ingest=False)})
            version = live.check_host(setup, worker)
            env = live.agent_env(setup, home, route_keys=live.route_keys(ws) if installation is not None else [])
            result = worker.run_session(name, session["prompts"], ws, home, env=env)
            _relative_paths(result, ws)
            results[name] = result
            ran.add(result.session_id)
            record["sessions"].append(_live_session_log(name, spec["project"], result, overlays, version))
            if name == spec["oracle"]["session"]:
                break
        if installation is not None:
            record["gaps"].append({"before": "measurement", **live.wait_quiescent(ws)})
            record["provider_outcomes"] = live.provider_outcomes(ws)
        actions = [a.log() for r in results.values() for a in r.actions]
        judged = smoke.judge(spec["oracle"]["check"], ws, actions, spec["oracle"]["session"])
        background = background_usage(ws) if installation is not None else {"model_calls": 0, "tokens": 0}
        if installation is not None:
            background["usage_source"] = "the budget ledger: provider-reported usage where the call reported it, else the engine's charged estimate"
        record["oracle"] = judged
        record["outcomes"] = outcomes(spec, results, judged, background)
        record["outcomes"]["foreground_cost_usd"] = round(sum(float(r.extra.get("cost_usd") or 0.0) for r in results.values()), 6)
        record["background"] = background
        record["curator_calls"] = curator_calls(ws) if installation is not None else []
        record["claims"] = claim_heads(ws) if installation is not None else []
        record["retrieval_points"] = retrieval_points(spec, results, terms=GOLD_TERMS.get(sid, [])) if installation is not None else []
        record["same_session_learning"] = [x for r in results.values() for x in same_session_learning(r)] if installation is not None else []
        record["second_project"] = side or None
        record["hook_replies"] = sum(len(r.deliveries) for r in results.values())
        record["manifest"] = {arm: baselines.manifest(arm, mode="live", ws=ws, home=home, native_memory=native_memory, installation=installation, agent=agent_record)}
    except (TrialError, live.LiveError) as exc:
        record["error"] = exc.code
        record["error_detail"] = exc.detail
        if isinstance(exc, live.LiveError) and exc.steps:
            record["provisioning_steps"] = exc.steps
        record.setdefault("outcomes", {"task_success": False, "repeated_mistakes": None, "detours": None, "legitimate_retry_success": None, "foreground_tokens": None, "background_tokens": None, "elapsed_seconds": None, "operator_interventions": 0})
        record.setdefault("manifest", {arm: baselines.manifest(arm, mode="live", ws=ws, home=home, native_memory=native_memory, installation=installation, agent=agent_record)})
    finally:
        record["worker_stop"] = [live.stop_worker(root, setup) for root in owned]
    return record


def _live_second_project(spec: dict[str, Any], session: dict[str, Any], arm: str, base: Path, setup: Any, worker: Any, owned: list[Path]) -> tuple[Any, dict[str, Any], str]:
    """C4 session A, live, in an independent ledgerlite workspace (an installation of its own for the candidate)."""
    from evals import baselines, live

    second = base / ("p2" if os.name == "nt" else "second-project")
    ws2, home2 = second / ("w" if os.name == "nt" else "ws"), second / ("h" if os.name == "nt" else "home")
    home2.mkdir(parents=True)
    copy_seed("ledgerlite", ws2)
    baselines.prepare_home(home2)
    info: dict[str, Any] = {"project": "ledgerlite", "workspace": ws2.relative_to(base.parent.parent).as_posix()}
    if arm == "candidate":
        info["init"] = live.provision(ws2, "ledgerlite", setup, label=f"{spec['id']}.{arm}.second")
        owned.append(ws2)
        info["installation_id"] = context(ws2).installation_id
    version = live.check_host(setup, worker)
    result = worker.run_session("A", session["prompts"], ws2, home2, env=live.agent_env(setup, home2, route_keys=live.route_keys(ws2) if arm == "candidate" else []))
    _relative_paths(result, ws2)
    if arm == "candidate":
        info["gap"] = live.wait_quiescent(ws2)
        info["claims"] = claim_heads(ws2)
        info["curator_calls"] = curator_calls(ws2)
    return result, info, version
