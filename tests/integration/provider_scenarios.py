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

Decision 0023 adds the direct-API variant: ``crash_project(..., api_url=URL)``
records a loopback fake provider (``fake_api_server.FakeProvider`` in
``narrative`` mode, owned by the test process and alive across the kill and
the restart) and the driver launches the production stdlib HTTP transport
through the same ``ProviderBackend``; each transport child's pid is logged so
the test can prove none outlives a crashed worker.
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
from recalith.controller import apply, requests
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


def crash_project(tmp: Path, name: str, *, api_url: str | None = None) -> Path:
    p = wks.Project(tmp, name)
    p.scenario("lifecycle")
    p.drain()
    p.send_all(green_reruns())
    p.drain()
    # An inferred candidate: its application schedules its own review job (Task 9), which runs through the production preparer.
    op = osc.op("c", "propose_claim", osc.claim(CLAIM), evidence=[osc.link(p.root, "fail", quote="FAILURES")])
    apply.apply_operations(osc.operator(p.root), [osc._op(op)], read_set=osc.read_set(p.root), submission_id=derived_id("op", [name, "claim"]), now=utc_now())
    latest = max(t["last_activity_at"] for t in p.tasks())
    clock = format_utc(parse_utc(latest) + _dt.timedelta(hours=1))  # every narrative job is due and its task quiet
    spec = {"clock": clock, "pidlog": str(tmp / f"{name}.pids")}
    if api_url is not None:
        spec["api_url"] = api_url
    (p.root / SCENARIO).write_text(json.dumps(spec), encoding="utf-8")
    return p.root


def scenario(root: Path) -> dict[str, Any] | None:
    path = root / SCENARIO
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def backend_config(ctx: Any, pidlog: str) -> ProviderConfig:
    return ProviderConfig(
        provider_id="fake_process", installation_id=ctx.installation_id, backend="json_process", executable=sys.executable, configured_model="fake-model",
        auth_route="env_api_key", auth_env_keys=["LOCAL_MODEL_ROUTE"], invocation_args=["-I", str(FAKE_BACKEND), "narrative", pidlog, "0.3"], certification={"certified": False},
    )


def api_config(ctx: Any, url: str) -> ProviderConfig:
    """A loopback (local-server) Chat Completions route without auth; never certified."""
    return ProviderConfig(
        provider_id="fake_api", installation_id=ctx.installation_id, backend="openai_compatible", executable=None, configured_model="fake-model",
        auth_route="none", auth_env_keys=[], invocation_args=[],
        endpoint={"url": url, "dialect": "chat_completions", "auth_header": "none", "output_cap_field": "max_completion_tokens", "json_mode": "json_object", "api_version": None},
        certification={"certified": False},
    )


def api_backend(ctx: Any, url: str, pidlog: str | None = None):
    """The production backend for the API route; logs each transport child's pid (test-only subclass)."""
    import os

    from recalith.providers import base

    class LoggingBackend(base.ProviderBackend):
        def _spawned(self, pid: int, pgid: int | None, root: Path) -> Path | None:
            if pidlog is not None:
                with open(pidlog, "a", encoding="utf-8") as fh:
                    fh.write(f"{pid}\n")
            return super()._spawned(pid, pgid, root)

    inherited = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP", "TMPDIR") if k in os.environ}
    return LoggingBackend(api_config(ctx, url), inherited=inherited, mode="live", run_dir=Path(ctx.root) / ".recalith" / "run")


def runtime(ctx: Any, spec: dict[str, Any], clock: Any):
    """The production backend and preparer (request capture: no route keys; a fake is never certified)."""
    from recalith.controller import worker
    from recalith.providers import base

    if spec.get("api_url"):
        backend = api_backend(ctx, spec["api_url"], spec["pidlog"])
    else:
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


__all__ = ["crash_project", "scenario", "runtime", "api_config", "api_backend", "outstanding", "extra_state", "RecordRef"]
