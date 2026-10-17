#!/usr/bin/env python3
"""Smoke evaluation harness (ACCEPTANCE_TESTS §6.1), built incrementally from Task 7.

    python evals/run.py preflight [--route PROVIDER_JSON]
    python evals/run.py prepare SCENARIO_ID --out DIR

``preflight`` states, per smoke scenario, whether a *candidate* run (Recalith
installed) can happen now and why not: it needs a certified inference route
(checked with the production ``route_status``; ``--route`` names a project's
``.recalith/provider.json``) and certified start/prompt delivery (Task 13; not
built yet, reported unavailable). The clean no-memory *baseline* needs neither.
Exit 0 only when every candidate run is possible; 4 otherwise. Nothing is
launched and no model is called.

``prepare`` materializes one scenario: two independent copies of its seed
project, ``candidate/ws`` with its own fresh Recalith installation and
``baseline/ws`` with none, and judges the untouched seed with the scenario's
oracle, which must fail (a smoke run cannot pass vacuously). The live agent
sessions, transcript action logs and comparative scoring arrive with Tasks
9–13 and 18; an unavailable capability is never reported as a pass.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMOKE = ROOT / "evals" / "scenarios" / "smoke"
sys.path.insert(0, str(ROOT / "src"))

EXIT_OK, EXIT_USAGE, EXIT_UNAVAILABLE = 0, 2, 4
EVAL_PROJECT_ID = "proj_70707070-7070-4070-8070-707070707070"


def scenarios() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(SMOKE.glob("smoke-*.json"))}


def preflight(route: Path | None) -> tuple[int, dict]:
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
    delivery = {"state": "unavailable", "reasons": ["start_prompt_delivery_not_certified (Task 13)"]}
    out = {"inference": inference, "delivery": delivery, "scenarios": {}}
    ready = status.certified and delivery["state"] == "certified"
    for sid, spec in scenarios().items():
        out["scenarios"][sid] = {
            "category": spec["category"], "project": spec["project"], "sessions": [s["name"] for s in spec["sessions"]],
            "candidate": "ready" if ready else "unavailable", "baseline": "ready",
        }
    out["verdict"] = "ready" if ready else "unavailable"
    return (EXIT_OK if ready else EXIT_UNAVAILABLE), out


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    pre = sub.add_parser("preflight")
    pre.add_argument("--route", type=Path, default=None)
    prep = sub.add_parser("prepare")
    prep.add_argument("scenario")
    prep.add_argument("--out", type=Path, required=True)
    ns = parser.parse_args(argv)
    try:
        if ns.command == "preflight":
            code, out = preflight(ns.route)
        else:
            code, out = prepare(ns.scenario, ns.out)
    except KeyError as exc:
        print(f"error: unknown scenario {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(json.dumps(out, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
