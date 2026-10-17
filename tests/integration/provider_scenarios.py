"""Test-only builder for the Task 7 kill/restart scenario: real request preparation and provider launches.

The project holds the real Claude Code 2.1.301 lifecycle session plus two
synthetic green reruns (named variants, as in ``test_requests.py``), so typed
reduction settles an episode and schedules its narrative (one
``build_episode`` and one ``update_task`` job, decision 0009). An
operator-seeded claim gets a ``review_claims`` job. The driver
(``worker_scenarios.py``) runs these jobs through the production path: the
preparer (``controller.requests``), a persisted review batch, the budget
reservation, a real bounded child through ``providers.base.ProviderBackend``
(the fake JSON process in ``narrative`` mode: it answers the request it
received and keeps a sleeping grandchild, a tree that must not outlive a
crashed worker), proposal persistence and application.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

import operation_scenarios as osc
import working_scenarios as wks
from working_scenarios import record, variant
from recalith.contracts.common import RecordRef, derived_id, format_utc, parse_utc, utc_now
from recalith.contracts.config import ProviderConfig
from recalith.controller import apply, jobs, requests
from recalith.storage import db

SCENARIO = "provider-scenario.json"
FAKE_BACKEND = Path(__file__).resolve().parents[1] / "fixtures" / "providers" / "fake_backend.py"
CLAIM = "The scripted pytest run fails with exit code 1."


def green_reruns() -> list[dict[str, Any]]:
    out = []
    for call, command in (("toolu_probe_0002", "pytest -q test_long.py"), ("toolu_probe_0003", "pytest -q test_mid.py")):
        out += [
            variant(record("lifecycle", "PreToolUse", call), tool_suffix="green"),
            variant(record("lifecycle", "PostToolUse", "toolu_probe_0004"), replace={"toolu_probe_0004": f"{call}_green", "pytest -q -s test_pass.py": command}),
        ]
    return out


def crash_project(tmp: Path, name: str) -> Path:
    p = wks.Project(tmp, name)
    p.scenario("lifecycle")
    p.drain()
    p.send_all(green_reruns())
    p.drain()
    op = osc.op("c", "propose_claim", osc.claim(CLAIM, basis="observed"), evidence=[osc.link(p.root, "fail", quote="FAILURES", mapping="tool.exit_code")])
    seeded = apply.apply_operations(osc.operator(p.root), [osc._op(op)], read_set=osc.read_set(p.root), submission_id=derived_id("op", [name, "claim"]), now=utc_now())
    claim = next(r for r in seeded.changed_refs if r.kind == "claim")
    latest = max(t["last_activity_at"] for t in p.tasks())
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        jobs.enqueue(txn, kind="review_claims", input_refs=[claim], now=latest, prompt_version="review_claims@1", review_candidates=[jobs.ReviewCandidate(claim_id=claim.id, origin="extracted", claim_kind="fact")])
    clock = format_utc(parse_utc(latest) + _dt.timedelta(hours=1))  # every narrative job is due and its task quiet
    (p.root / SCENARIO).write_text(json.dumps({"clock": clock, "pidlog": str(tmp / f"{name}.pids")}), encoding="utf-8")
    return p.root


def scenario(root: Path) -> dict[str, Any] | None:
    path = root / SCENARIO
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def backend_config(ctx: Any, pidlog: str) -> ProviderConfig:
    return ProviderConfig(
        provider_id="fake_process", installation_id=ctx.installation_id, backend="json_process", executable=sys.executable, configured_model="fake-model",
        auth_route="env_api_key", auth_env_keys=["LOCAL_MODEL_ROUTE"], invocation_args=["-I", str(FAKE_BACKEND), "narrative", pidlog, "0.3"], certification={"certified": False},
    )


def runtime(ctx: Any, spec: dict[str, Any], clock: Any):
    """The production backend and preparer (request capture: no route keys; a fake is never certified)."""
    from recalith.controller import worker
    from recalith.providers import base

    backend = base.ProviderBackend(backend_config(ctx, spec["pidlog"]), mode="request_capture", run_dir=Path(ctx.root) / ".recalith" / "run")
    return worker.ModelRuntime(backend=backend, prepare=requests.runtime_preparer(ctx, now=clock.now))


def outstanding(root: Path) -> str:
    """``1`` while any model job of the scenario is unfinished (read-only peek)."""
    import sqlite3

    conn = sqlite3.connect((root / ".recalith" / db.STATE_DB).as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        n = conn.execute("SELECT COUNT(*) FROM jobs WHERE kind IN ('update_task', 'build_episode', 'review_claims') AND state NOT IN ('completed', 'cancelled', 'failed')").fetchone()[0]
        return "1" if n else "0"
    except sqlite3.Error:
        return "1"
    finally:
        conn.close()


def extra_state(root: Path) -> dict[str, Any]:
    """Provider-path state the generic normalization does not cover."""
    ctx = osc.context(root)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        batches = view.execute("SELECT COUNT(*), COUNT(DISTINCT review_job_id) FROM review_batches").fetchone()
        titles = sorted(json.loads(r[0])["title"] for r in view.execute("SELECT r.body FROM episode_heads h JOIN episode_revisions r ON r.episode_id = h.episode_id AND r.revision = h.revision").fetchall())
        next_actions = sorted(str((json.loads(r[0]).get("next_action") or {}).get("text")) for r in view.execute("SELECT r.body FROM task_heads h JOIN task_revisions r ON r.task_id = h.task_id AND r.revision = h.revision").fetchall())
    return {"review_batches": tuple(batches), "episode_titles": titles, "next_actions": next_actions}


__all__ = ["crash_project", "scenario", "runtime", "outstanding", "extra_state", "RecordRef"]
