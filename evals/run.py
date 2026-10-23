#!/usr/bin/env python3
"""The preview evaluation harness (ACCEPTANCE_TESTS §5.2, §6.1, §6.2, §7, §8; decision 0020).

    python evals/run.py preflight [--route PROVIDER_JSON] [--host-record HOST_JSON]
    python evals/run.py prepare SCENARIO_ID --out DIR
    python evals/run.py smoke --out DIR [--mode scripted|live] [--init-route test_fixture|operator_token]
                              [--operator-token-file FILE] [--scenario ID ...] [--slots N]
    python evals/run.py workload --out DIR [--mode scripted|live] [--project NAME ...]
    python evals/run.py demonstrate --out DIR [--mode scripted|live]
    python evals/run.py report DIR
    python evals/run.py gate --out DIR [--mode scripted|live] [...]

    live inputs: --config LOCAL_CONFIG --operator-token-file FILE --source-project CERTIFIED_PROJECT
                 --wheel WHEEL --wheelhouse DIR [--evidence docs/host-compatibility.json]

``preflight`` states, per smoke scenario, whether a *live* candidate run can
happen now and why not: it needs a certified inference route (the production
``route_status``; ``--route`` names a project's ``.recalith/provider.json``)
and a live host certification of start and prompt delivery for the installed
host version (``--host-record`` names a ``.recalith/host.json`` written by
``tools/probe_delivery.py --engine-project``). The clean no-memory baseline
needs neither. Exit 0 only when every live candidate run is possible; 4
otherwise. Nothing is launched and no model is called.

``prepare`` materializes one scenario: an independent candidate copy with its
own fresh installation and a baseline copy with none; the untouched seed must
fail its oracle (a smoke run cannot pass vacuously).

``smoke`` runs the 12 smoke scenarios, one fresh trial per arm (candidate and
clean no-memory baseline), and writes ``trials/*.json`` and ``run.json``.
``workload`` replays the three eight-hour activity days under default budgets
(``evals/workload.py``). ``demonstrate`` runs the scripted §6.1
demonstrations (``evals/demos.py``). ``report`` writes ``report.json`` and
``report.md`` (``evals/report.py``). ``gate`` does all of them.

Modes. ``live`` uses the real Claude Code CLI as the working agent and the
installation's certified route as the curator; it refuses to start (exit 4)
until preflight passes, and never falls back. ``scripted`` uses the scripted
working agent (``evals/agent.py``) and the recorded curator
(``evals/curator.py``) through the real engine; its results are mechanics
evidence, always labeled, and never a live pass.

A live run (decision 0028) is started by the operator from an ordinary
terminal with the selected keys exported. ``--source-project`` is the project
whose route and host record ``preflight`` checks (its ``provider.json`` and
``host.json`` by default). Every candidate installation is provisioned by the
operator's own tools as children of this process (``evals/live.py``): init
with the pre-init token, the release bootstrap with ``--wheel`` (its digest
must equal the source project's ``engine.lock``) and ``--wheelhouse``, a live
route certification of its own, ``integrate claude``, and its host record
bound from the source project's live engine-mode record. ``--slots`` runs that
many trials at once, each in its own installation (ACCEPTANCE_TESTS §6.2).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMOKE = ROOT / "evals" / "scenarios" / "smoke"
for extra in (ROOT / "src", ROOT):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

EXIT_OK, EXIT_USAGE, EXIT_UNAVAILABLE, EXIT_GATE = 0, 2, 4, 8
EVAL_PROJECT_ID = "proj_70707070-7070-4070-8070-707070707070"
OPERATOR_STEPS = [
    "From an ordinary OS terminal outside any agent session (no CLAUDECODE or other host marker in its environment):",
    "1. cp tools/probe_config.example.json probe-private/local-config.json and choose the curator backend in its provider section (docs/probes/LOCAL_CONFIG.md): claude_cli (executable, expected_version = the installed `claude --version`, the certified argument array), anthropic_messages or openai_compatible (an endpoint object; no executable), with the explicit model, an auth_route naming only the key's environment variable (or none for a loopback local server), and operator_attestation checked_eligible with basis/checked_on after checking the provider's terms for unattended background use (not_applicable_local only for a loopback server). Set the delivery section for the working agent's Claude Code host.",
    "2. export THE_SELECTED_KEY_NAME=... in that terminal only (the name the auth_route selects).",
    "3. python tools/probe_provider.py --config probe-private/local-config.json --backend BACKEND --output docs/host-compatibility.json --route-out /path/to/project   (expect exit 0)",
    "4. python tools/check_provider_runtime.py --config probe-private/local-config.json --backend BACKEND --output docs/host-compatibility.json   (expect exit 0)",
    "5. In the project: .recalith/bin/recalith integrate claude",
    "6. python tools/probe_delivery.py --config probe-private/local-config.json --engine-project /path/to/project --output docs/host-compatibility.json   (expect exit 0: live start/prompt)",
    "7. .recalith/bin/recalith operator-token create --output /secure/eval-token.json   (at that terminal; the harness never mints one)",
    "8. python evals/run.py gate --mode live --config probe-private/local-config.json --operator-token-file /secure/eval-token.json --source-project /path/to/project --wheel dist/recalith-VERSION-py3-none-any.whl --wheelhouse wheelhouse --out /short/results   (decision 0028)",
]


def scenarios() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(SMOKE.glob("smoke-*.json"))}


# --------------------------------------------------------------------------
# Preflight


def host_certification(path: Path | None) -> dict:
    """Live start/prompt certification from a host record (``.recalith/host.json``), for the installed host version."""
    if path is None:
        return {"state": "unavailable", "reasons": ["start_prompt_delivery_not_certified: no host record given (B1: live nonce certification not run)"]}
    from recalith.contracts.health import HostCertification

    try:
        # The contract's own shape, as tools/probe_delivery.py writes it and health reads it (a ValidationError is a ValueError).
        record = HostCertification.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"state": "unavailable", "reasons": [f"host_record_invalid:{type(exc).__name__}"]}
    if record.mode != "live":
        return {"state": "unavailable", "reasons": [f"delivery_{record.mode}_only"]}
    missing = [p for p in ("session_start", "prompt") if record.delivery[p] != "certified"]
    if missing:
        return {"state": "unavailable", "reasons": [f"required_path_not_certified:{p}" for p in missing]}
    return {"state": "certified", "reasons": [], "host_version": record.host_version}


def preflight(route: Path | None, host_record: Path | None = None) -> tuple[int, dict]:
    from recalith.contracts.config import ProviderConfig
    from recalith.providers import base

    if route is None:
        status = base.route_status(None, installation_id="", inherited=os.environ)
    else:
        try:
            data = json.loads(route.read_text(encoding="utf-8"))
            config = ProviderConfig.model_validate(data["provider"])
            status = base.route_status(config, installation_id=config.installation_id, inherited=os.environ)
        except (OSError, ValueError, KeyError) as exc:
            status = base.RouteStatus("unavailable", [f"provider_config_invalid:{type(exc).__name__}"])
    inference = {"state": status.state, "reasons": status.reasons}
    delivery = host_certification(host_record)
    out = {"inference": inference, "delivery": delivery, "scenarios": {}}
    ready = status.certified and delivery["state"] == "certified"
    for sid, spec in scenarios().items():
        out["scenarios"][sid] = {
            "category": spec["category"], "project": spec["project"], "sessions": [s["name"] for s in spec["sessions"]],
            "candidate": "ready" if ready else "unavailable", "baseline": "ready",
        }
    out["verdict"] = "ready" if ready else "unavailable"
    if not ready:
        out["operator_action"] = OPERATOR_STEPS
    return (EXIT_OK if ready else EXIT_UNAVAILABLE), out


# --------------------------------------------------------------------------
# Prepare


def prepare(sid: str, out_dir: Path) -> tuple[int, dict]:
    from recalith.contracts.common import Actor
    from recalith.contracts.config import ProjectConfig
    from recalith.core import identity

    spec = scenarios().get(sid)
    if spec is None:
        raise KeyError(sid)
    seed = ROOT / "evals" / "projects" / spec["project"]
    ignore = shutil.ignore_patterns(".git", "__pycache__", ".recalith")
    result = {"scenario": sid, "project": spec["project"]}
    for arm in ("candidate", "baseline"):
        ws = out_dir / arm / "ws"
        shutil.copytree(seed, ws, ignore=ignore)
        result[arm] = {"workspace": str(ws)}
    domain = "general" if spec["project"] == "household" else "coding"
    candidate = out_dir / "candidate" / "ws"
    identity.initialize_installation(candidate, ProjectConfig.defaults_for(EVAL_PROJECT_ID, domain_profile=domain))
    ctx = identity.resolve_installation(candidate, actor=Actor(kind="controller", id="eval-harness", channel="worker"))
    result["candidate"]["installation_id"] = ctx.installation_id
    result["baseline"]["installation_id"] = None  # the clean no-memory baseline has no installation at all
    oracle = spec["oracle"]
    actions = out_dir / "seed-actions.json"
    actions.write_text("[]", encoding="utf-8")
    judged = subprocess.run(
        [sys.executable, str(ROOT / oracle["script"]), oracle["check"], "--workspace", str(out_dir / "baseline" / "ws"), "--actions", str(actions)],
        capture_output=True, text=True, encoding="utf-8", timeout=300, check=False,
    )
    result["seed_oracle"] = {"exit": judged.returncode, "passed": judged.returncode == 0}
    (out_dir / "prepared.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return (EXIT_OK if judged.returncode == 1 else EXIT_UNAVAILABLE), result


# --------------------------------------------------------------------------
# Run metadata


def versions() -> dict:
    from recalith import __version__, prompts
    from recalith.fast import claude_capture
    from recalith.storage import db

    def git(*args: str) -> str | None:
        try:
            return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False).stdout.strip() or None
        except OSError:
            return None

    host = shutil.which("claude")
    host_version = None
    if host:
        try:
            host_version = subprocess.run([host, "--version"], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            host_version = None
    return {
        "engine": __version__, "commit": git("rev-parse", "HEAD"), "tree_clean": git("status", "--porcelain") == None,  # noqa: E711 - "" is clean
        "schema": db.SCHEMA_VERSION, "prompts": dict(prompts.CURRENT), "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
        "platform": f"{platform.system()} {platform.release()} {platform.machine()}", "installed_host": host_version,
        "scripted_payload_format": "Claude Code 2.1.305 (reviewed fixtures)", "certified_capture_versions": sorted(claude_capture.CERTIFIED_VERSIONS),
    }


def authorship() -> dict:
    specs = scenarios()
    routes = sorted({s["authorship"]["route"] for s in specs.values()})
    return {
        "smoke": {"route": routes, "independent_of_system_spec_7": False, "note": "the 12 smoke scenarios were written by the repository's coding agent, who has read SYSTEM_SPEC §7; development fixtures, not held out"},
        "held_out": "none (full release; intentionally empty)",
        "workload_days": "synthetic representative days authored by the coding agent (evals/workload/days); not recorded real sessions",
        "recorded_proposals": "evals/curator.py, authored by the coding agent; not a model",
    }


LIMITATIONS_SCRIPTED = [
    "B1: no certified inference route and no live host certification, so no live trial ran; every number here is recorded-mode mechanics, not a live measurement.",
    "The working agent is a fixed scripted policy (evals/agent.py) that reads only the delivered context at its branch points; it measures whether the engine delivered the right thing, not how a live agent uses it.",
    "The curator is recorded proposals (evals/curator.py) written with knowledge of the gold; §5.1 extraction quality is therefore not measured (precision and recall reflect the deterministic pipeline admitting or rejecting those proposals).",
    "Hooks run in process through the real stdlib hook path with Claude Code 2.1.305-shaped payloads (map_hook, handle_hook) and a controlled delivery manifest; the installed launcher and the real host are not in the loop.",
    "Scheduling runs on a virtual clock (sessions two hours apart, worker drains to a three-hour idle horizon); provider latency and queue time are not real.",
    "Background tokens are the engine's own charged estimates (ceil(bytes/3) and output allowances); the recorded backend reports no provider usage.",
    "Smoke scenarios, gold labels and workload days were authored by the coding agent, who has read SYSTEM_SPEC §7; no held-out or independent corpus exists.",
    "One trial per arm and 12 scenarios: intervals are wide and inconclusive by construction; no superiority claim is made.",
    "Each smoke store holds only a few claims, so hook views always contain every relevant claim here; at reference scale (10,000 heads) the hook's query-independent views omit prompt-specific facts (decision 0020 item 15, docs/measurements/release-gate-latency-linux.json), which this run cannot show.",
]


LIMITATIONS_LIVE = [
    "Smoke scenarios, gold labels and workload days were authored by the coding agent, who has read SYSTEM_SPEC §7; no held-out or independent corpus exists.",
    "One trial per arm and 12 scenarios: intervals are wide and inconclusive by construction; no superiority claim is made.",
    "Each candidate installation's route is certified live for that installation; its host record is bound from the source project's live engine-mode certification for the same host version, model and configuration (decision 0028), not re-observed per installation.",
    "Sessions run on real time. Between sessions the harness waits until the hook-started worker owes nothing due within 20 minutes (or 45 minutes pass, or progress stalls for 5); the scenarios' two-hour gaps are not reproduced.",
    "Delivered context is read from the host's hook_response records (the hook's exact stdout as the host received it); that the model saw it is the separate canary certification, not re-checked per trial.",
    "Workload days replay synthetic recorded timelines in process through the real stdlib hook path (no host session); scheduling runs on the day's virtual clock while every curator call is real.",
    "Background tokens come from the budget ledger (provider-reported where the call reported usage); foreground cost is the host's own reported session cost.",
    "On native Windows a hook-started worker runs inside the venv redirector's job (decision 0027 item 8): recovery is degraded while it runs.",
]


def write_run(out_dir: Path, mode: str, *, native_memory: dict, init_route: str, route: Path | None = None, host_record: Path | None = None, setup=None) -> dict:
    code, pre = preflight(route, host_record) if mode == "live" else preflight(None)
    run = {
        "run_schema": 1, "mode": mode, "profile": "claude_preview", "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "versions": versions(), "authorship": authorship(),
        "native_memory": {"installed_host_observation": native_memory, "scripted_arms": "not applicable: the scripted agent has no host-native memory"} if mode == "scripted" else
                         {"installed_host_observation": native_memory, "configuration": "the live trials' own session flags, disposable HOME and environment"},
        "init_route": init_route, "preflight": {"exit": code, "inference": pre["inference"], "delivery": pre["delivery"]},
        "blockers": [] if code == 0 else ["B1: " + "; ".join(pre["inference"]["reasons"] + pre["delivery"]["reasons"])],
        "limitations": LIMITATIONS_SCRIPTED if mode == "scripted" else LIMITATIONS_LIVE, "operator_action": pre.get("operator_action"),
    }
    if setup is not None:
        run["live"] = setup.label()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run.json").write_text(json.dumps(run, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return run


def live_inputs(ns: argparse.Namespace) -> tuple[Path | None, Path | None]:
    """The route and host record preflight checks: given explicitly, else the source project's own."""
    source = getattr(ns, "source_project", None)
    route = ns.route or (source / ".recalith" / "provider.json" if source else None)
    host = ns.host_record or (source / ".recalith" / "host.json" if source else None)
    return route, host


def live_setup(ns: argparse.Namespace):
    """``(setup, None)`` or ``(None, refusal)`` after preflight passed (decision 0028)."""
    from evals import live

    route, host = live_inputs(ns)
    code, pre = preflight(route, host)
    if code != EXIT_OK:
        return None, {"verdict": "unavailable", "inference": pre["inference"], "delivery": pre["delivery"], "operator_action": OPERATOR_STEPS}
    try:
        setup = live.load_setup(config=ns.config, token_file=ns.operator_token_file, source_project=ns.source_project, evidence=ns.evidence, wheel=ns.wheel, wheelhouse=ns.wheelhouse, run_dir=ns.out)
    except live.LiveError as exc:
        return None, {"verdict": "unavailable", "reason": exc.code, "detail": exc.detail, "operator_action": OPERATOR_STEPS}
    return setup, None


# --------------------------------------------------------------------------
# Commands


def cmd_smoke(ns: argparse.Namespace) -> int:
    from concurrent.futures import ThreadPoolExecutor

    from evals import baselines, live, trial

    setup = None
    if ns.mode == "live":
        setup, refusal = live_setup(ns)
        if setup is None:
            print(json.dumps(refusal, sort_keys=True))
            return EXIT_UNAVAILABLE
    if not ns.observe_native_memory:
        native = {"state": "not_observed", "reason": "skipped (--no-native-memory-observation)"}
    elif setup is not None:
        native = baselines.observe_native_memory(setup.executable, session_args=[*live.SESSION_FLAGS, "--model", setup.model])
    else:
        native = baselines.observe_native_memory(shutil.which("claude"))
    route, host = live_inputs(ns)
    write_run(ns.out, ns.mode, native_memory=native, init_route=ns.init_route if setup is None else "operator_token", route=route, host_record=host, setup=setup)
    trials_dir = ns.out / "trials"
    trials_dir.mkdir(parents=True, exist_ok=True)
    work = ns.out / "work"
    chosen = ns.scenario or sorted(scenarios())

    def one(job: tuple[str, str]) -> dict:
        sid, arm = job
        record = trial.run_trial(sid, arm, work, mode=ns.mode, init_route=ns.init_route, token_file=ns.operator_token_file, native_memory=native, live=setup)
        (trials_dir / f"{sid}.{arm}.json").write_text(json.dumps(record, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
        return {"scenario": sid, "arm": arm, "success": record["outcomes"].get("task_success"), "error": record.get("error")}

    jobs = [(sid, arm) for sid in chosen for arm in ("no_memory", "candidate")]
    slots = max(1, int(ns.slots or 1)) if ns.mode == "live" else 1
    with ThreadPoolExecutor(max_workers=slots) as pool:  # each trial has its own workspace, home and installation
        summary = list(pool.map(one, jobs))
    if not ns.keep_workspaces and not getattr(ns, "gate_keeps_work", False):
        shutil.rmtree(work, ignore_errors=True)
    print(json.dumps({"mode": ns.mode, "trials": summary}, sort_keys=True))
    return EXIT_OK


def cmd_workload(ns: argparse.Namespace) -> int:
    from evals import workload

    setup = None
    if ns.mode == "live":
        setup, refusal = live_setup(ns)
        if setup is None:
            print(json.dumps(refusal, sort_keys=True))
            return EXIT_UNAVAILABLE
    out = ns.out / "workload"
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for project in ns.project or workload.PROJECTS:
        record = workload.run_day(project, ns.out / "work-days", mode=ns.mode, live_setup=setup)
        (out / f"{project}.json").write_text(json.dumps(record, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
        results.append({"project": project, "events": record.get("events"), "calls": record.get("curation", {}).get("calls"), "exhausted_at_hours": record.get("budget", {}).get("exhausted_at_hours"), "error": record.get("error")})
    if not ns.keep_workspaces:
        shutil.rmtree(ns.out / "work-days", ignore_errors=True)
    print(json.dumps({"mode": ns.mode, "days": results}, sort_keys=True))
    return EXIT_OK


def cmd_demonstrate(ns: argparse.Namespace) -> int:
    from evals import demos

    setup = None
    if ns.mode == "live":
        setup, refusal = live_setup(ns)
        if setup is None:
            print(json.dumps(refusal, sort_keys=True))
            return EXIT_UNAVAILABLE
        if not (ns.out / "work").is_dir():
            print(json.dumps({"verdict": "unavailable", "reason": "live demonstrations run on this run's kept live smoke workspaces: run `gate`, or `smoke --keep-workspaces` first"}, sort_keys=True))
            return EXIT_UNAVAILABLE
    result = demos.run_all(ns.out / "work-demos", trials_dir=ns.out / "trials", mode=ns.mode, live_setup=setup, live_work=ns.out / "work")
    (ns.out / "demonstrations.json").write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    if not ns.keep_workspaces:
        shutil.rmtree(ns.out / "work-demos", ignore_errors=True)
        if getattr(ns, "gate_keeps_work", False):
            shutil.rmtree(ns.out / "work", ignore_errors=True)
    print(json.dumps({k: v.get("demonstrated") for k, v in result["demonstrations"].items()}, sort_keys=True))
    return EXIT_OK


def cmd_report(directory: Path) -> int:
    from evals import report

    built = report.build(directory)
    (directory / "report.json").write_text(json.dumps(built, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (directory / "report.md").write_text(report.markdown(built), encoding="utf-8")
    print(json.dumps({"mode": built["mode"], "gate": built["gate"]}, sort_keys=True))
    return EXIT_OK if built["gate"]["state"] == "passed_smoke" else EXIT_GATE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    pre = sub.add_parser("preflight")
    pre.add_argument("--route", type=Path, default=None)
    pre.add_argument("--host-record", type=Path, default=None)
    prep = sub.add_parser("prepare")
    prep.add_argument("scenario")
    prep.add_argument("--out", type=Path, required=True)
    for name in ("smoke", "workload", "demonstrate", "gate"):
        p = sub.add_parser(name)
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--mode", choices=("scripted", "live"), default="scripted")
        p.add_argument("--route", type=Path, default=None)
        p.add_argument("--host-record", type=Path, default=None)
        p.add_argument("--init-route", choices=("test_fixture", "operator_token"), default="test_fixture")
        p.add_argument("--operator-token-file", type=Path, default=None)
        p.add_argument("--scenario", action="append")
        p.add_argument("--project", action="append")
        p.add_argument("--keep-workspaces", action="store_true")
        p.add_argument("--no-native-memory-observation", dest="observe_native_memory", action="store_false")
        p.add_argument("--config", type=Path, default=None, help="live: the local probe configuration (names only)")
        p.add_argument("--source-project", type=Path, default=None, help="live: the certified project (its provider.json and host.json)")
        p.add_argument("--evidence", type=Path, default=None, help="live: the report holding the source project's delivery_engine section (default docs/host-compatibility.json)")
        p.add_argument("--wheel", type=Path, default=None, help="live: the verified release wheel the trial installations are provisioned with")
        p.add_argument("--wheelhouse", type=Path, default=None, help="live: the hash-locked wheelhouse for the release bootstrap")
        p.add_argument("--slots", type=int, default=1, help="live: trials run at once, each in its own installation")
    rep = sub.add_parser("report")
    rep.add_argument("results", type=Path)
    ns = parser.parse_args(argv)
    try:
        if ns.command == "preflight":
            code, out = preflight(ns.route, ns.host_record)
            print(json.dumps(out, sort_keys=True))
            return code
        if ns.command == "prepare":
            code, out = prepare(ns.scenario, ns.out)
            print(json.dumps(out, sort_keys=True))
            return code
        if ns.command in ("smoke", "workload", "demonstrate", "gate") and ns.mode == "scripted" and ns.init_route != "test_fixture" and ns.operator_token_file is None:
            print("error: --init-route operator_token needs --operator-token-file", file=sys.stderr)
            return EXIT_USAGE
        if ns.command == "smoke":
            return cmd_smoke(ns)
        if ns.command == "workload":
            return cmd_workload(ns)
        if ns.command == "demonstrate":
            return cmd_demonstrate(ns)
        if ns.command == "report":
            return cmd_report(ns.results)
        ns.gate_keeps_work = True  # the live demonstrations run on the smoke trials' kept workspaces
        for step in (cmd_smoke, cmd_workload, cmd_demonstrate):
            code = step(ns)
            if code != EXIT_OK:
                return code
        return cmd_report(ns.out)
    except KeyError as exc:
        print(f"error: unknown scenario {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
