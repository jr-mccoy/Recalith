"""Task 7: isolated inference through real bounded launches (A28, A29, A30, A47, A67).

Every launch here is a real child process through the production path
(``providers.base.ProviderBackend`` → ``controller.launch.run_bounded`` with
the curator environment from ``fast.process_env.spawn_environment`` in a fresh
private root). The children are the deterministic fake JSON process
(``tests/fixtures/providers/fake_backend.py``), the fake Claude-like CLI
(``fake_cli.py``) and, where installed, the real Claude Code CLI in
request-capture mode (loopback endpoint, placeholder key). Fakes are never
certification subjects and request capture never certifies a route: these
tests prove containment, isolation detection and the gates around them.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

import claude_fixtures as cf
import worker_hosts as wh
from recalith.contracts.common import RecordRef, digest_of, new_id
from recalith.contracts.config import STDERR_CAP, ProviderConfig
from recalith.contracts.operations import ModelRequest, RequestLimits
from recalith.contracts.common import ReadSet
from recalith.controller import jobs, requests, worker
from recalith.fast import process_env
from recalith.providers import base, claude_cli, isolation
from recalith.providers.errors import ProviderCallFailed

FIXTURES = cf.ROOT / "tests" / "fixtures" / "providers"
FAKE_BACKEND = FIXTURES / "fake_backend.py"
FAKE_CLI = FIXTURES / "fake_cli.py"
INSTALLATION = "inst_41414141-4141-4141-8141-414141414141"
DECOYS = {"ANTHROPIC_AUTH_TOKEN": "dec" + "oy-auth", "AWS_PROFILE": "decoy-profile", "OPENAI_API_KEY": "dec" + "oy-openai", "CLAUDE_CODE_USE_BEDROCK": "1"}


def installed_claude() -> str | None:
    exe = shutil.which("claude")
    return exe if exe and os.name != "nt" else None


def json_config(mode: str, *args: str, installation_id: str = INSTALLATION) -> ProviderConfig:
    return ProviderConfig(
        provider_id="fake_process", installation_id=installation_id, backend="json_process", executable=sys.executable, configured_model="fake-model",
        auth_route="env_api_key", auth_env_keys=["LOCAL_MODEL_ROUTE"], invocation_args=["-I", str(FAKE_BACKEND), mode, *args], certification={"certified": False},
    )


def cli_config(*, scenario: str | None = None, installation_id: str = INSTALLATION, executable: str | None = None) -> ProviderConfig:
    """The certified Claude argument array; the fake CLI runs as ``python -I fake_cli.py`` on every platform."""
    args = list(claude_cli.ISOLATION_ARGS) if executable else ["-I", str(FAKE_CLI), *claude_cli.ISOLATION_ARGS]
    extra = {"FAKE_CLI_SCENARIO": scenario} if scenario else {}
    return ProviderConfig(
        provider_id="claude_cli", installation_id=installation_id, backend="claude_cli", executable=executable or sys.executable, configured_model="recalith-probe-unselected-model",
        auth_route="env_api_key", auth_env_keys=["ANTHROPIC_API_KEY"], invocation_args=args, nonsecret_env={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1", **extra},
        certification={"certified": False},
    )


def request(purpose: str = "update_task", *, timeout: int = 120) -> ModelRequest:
    from recalith.contracts.config import PURPOSE_OUTPUT_ALLOWANCE, body_cap_for

    limits = RequestLimits(max_input_bytes=96 * 1024, reserved_output_estimate=PURPOSE_OUTPUT_ALLOWANCE[purpose], max_body_bytes=body_cap_for(purpose), max_wire_stdout_bytes=262144, max_stderr_bytes=65536, timeout_seconds=timeout)
    return ModelRequest(request_schema=1, job_id=new_id("job"), purpose=purpose, prompt_version=f"{purpose}@1", instruction_text="test", read_set=ReadSet(workspace_id=new_id("ws"), policy_revision=1, tombstone_epoch=0), output_schema={"type": "object"}, limits=limits)


def curator_roots() -> set[str]:
    return {p.name for p in Path(tempfile.gettempdir()).glob("recalith-curator-*")}


def read_pids(path: Path) -> list[int]:
    return [int(x) for x in path.read_text(encoding="utf-8").split()] if path.exists() else []


# ---------------------------------------------------------------------------
# A30: bounded process trees and output


def test_timeout_terminates_process_tree(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    backend = base.ProviderBackend(json_config("grandchild", str(pidfile)), mode="request_capture", run_dir=tmp_path / "run")
    before = curator_roots()
    started = time.monotonic()
    with pytest.raises(ProviderCallFailed) as err:
        base.complete(request(timeout=3), backend.config, backend=backend)
    assert err.value.code == "provider_timeout" and time.monotonic() - started < 30
    result = backend.last_result
    assert result.timed_out and result.killed and result.tree_bound == "contained"
    grandchild = int(pidfile.read_text(encoding="utf-8"))
    assert wh.wait_for(lambda: not wh.pid_alive(grandchild) and not wh.pid_alive(result.pid), 10), "the provider's process tree outlived its timeout"
    assert result.tree_cleaned is not False
    assert curator_roots() == before and not list((tmp_path / "run" / "curators").glob("*.json"))  # private root and spawn record removed


def test_output_flood_is_bounded(tmp_path):
    flood = base.ProviderBackend(json_config("flood"), mode="request_capture")
    with pytest.raises(ProviderCallFailed) as err:
        base.complete(request(), flood.config, backend=flood)
    assert err.value.code == "wire_stdout_oversized"
    assert flood.last_result.stdout_overflow and flood.last_result.stdout == b"" and flood.last_result.tree_cleaned is not False
    noisy = base.ProviderBackend(json_config("stderr_flood"), mode="request_capture")
    response = base.complete(request(), noisy.config, backend=noisy)
    assert response.no_op_reason == "nothing new"
    assert len(noisy.last_result.stderr) == STDERR_CAP and noisy.last_result.stderr_truncated


def test_15kb_episode_response_is_accepted_through_a_real_launch(tmp_path):
    backend = base.ProviderBackend(json_config("stream", "16500", "60000"), mode="request_capture")
    backend.adapter = claude_cli  # the fake writes Claude's stream-json envelope
    backend.expect = claude_cli.Expectations(host_version="9.9.9")
    response = base.complete(request("build_episode"), backend.config, backend=backend)
    assert [op.kind for op in response.operations] == ["create_episode"]
    assert len(backend.last_result.stdout) > 60_000 and response.provenance.resolved_model == "fake-resolved-model"


# ---------------------------------------------------------------------------
# A28 data side: a request carries only its own installation's records


def test_provider_never_receives_other_project(tmp_path):
    sys.path.insert(0, str(cf.ROOT / "tests" / "integration"))
    import working_scenarios as wks
    from working_scenarios import record, variant

    marker = "PROJECT_B_PRIVATE_" + "MARKER_7731"
    a, b = wks.Project(tmp_path, "a"), wks.Project(tmp_path, "b")
    a.scenario("lifecycle")
    b.scenario("lifecycle")
    b.send(variant(record("lifecycle", "UserPromptSubmit"), prompt=f"FIXTURE: remember {marker}."))
    a.drain()
    b.drain()
    log = tmp_path / "requests.jsonl"
    backend = base.ProviderBackend(json_config("record", str(log), installation_id=a.ctx.installation_id), mode="request_capture", inherited={**os.environ, **DECOYS, "HOME": str(b.root)})
    a_task, b_task = a.tasks()[0]["task_id"], b.tasks()[0]["task_id"]
    with __import__("recalith.storage.db", fromlist=["db"]).open_store(a.ctx) as store, store.transaction() as txn:
        own, _ = jobs.enqueue(txn, kind="extract_claims", input_refs=[RecordRef(kind="task", id=a_task, revision=1)], now="2000-01-01T00:00:00.000000Z", prompt_version="extract_claims@1")
        foreign, _ = jobs.enqueue(txn, kind="update_task", input_refs=[RecordRef(kind="task", id=b_task, revision=1)], now="2000-01-01T00:00:00.000000Z", prompt_version="update_task@1")
    w = worker.Worker(a.ctx, model=worker.ModelRuntime(backend, requests.runtime_preparer(a.ctx)))
    try:
        for _ in range(10):
            if not w.lane.step():
                break
    finally:
        w.close()
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert calls, "the provider was never launched"
    with a.view() as v:
        assert jobs.get_job(v, own).state == "completed"
        refused = jobs.get_job(v, foreign)
    assert refused.state == "failed" and refused.last_error_code == "request_input_missing"  # never looked up elsewhere
    for call in calls:
        sent = call["request"]
        assert marker not in sent and b.ctx.installation_id not in sent and str(b.root) not in sent and b_task not in sent
        assert all(v not in sent for v in DECOYS.values() if len(v) > 4)
        cwd = Path(call["cwd"])
        assert cwd.parent.name.startswith("recalith-curator-") and not str(cwd).startswith((str(a.root), str(b.root)))
        assert call["home"] != str(b.root) and Path(call["home"]).parent == cwd.parent  # the private home, never the caller's
        assert not set(DECOYS) & set(call["keys"]) and process_env.WORKER_MARKER not in call["keys"]
        assert process_env.CURATOR_MARKER in call["keys"]
    requested = {json.loads(c["request"])["job_id"] for c in calls}
    assert foreign not in requested


# ---------------------------------------------------------------------------
# A28 / A67: effective customization and tool isolation


def test_user_level_hooks_and_memory_are_absent(tmp_path):
    """User-level hooks, native memory, instructions, skills and MCP servers are planted and must not load."""
    marked = {**os.environ, "CLAUDECODE": "1", "CLAUDE_CODE_CHILD_SESSION": "1", **DECOYS}
    check = isolation.isolation_check(cli_config(), inherited=marked)
    assert check["verdict"] == "pass", check["failures"]
    assert check["hooks_fired"] == [] and check["mcp_servers_started"] == [] and check["session_transcripts_written"] == []
    assert check["request_capture"]["sentinels_visible"] == [] and check["request_capture"]["model_visible_tools"] == []
    env = check["environment"]
    assert env["host_markers_present"] == [] and env["curator_marker_names_installation"] and not env["worker_marker_present"]
    assert not set(DECOYS) & set(env["child_keys"])
    # Positive control: the same planted fixture through a host that ignores --bare loads them, so the
    # detectors that found nothing above are live.
    control = isolation.isolation_check(cli_config(scenario="ignores_bare"), inherited=marked)
    assert control["verdict"] == "fail"
    assert {"sentinel_hook_ran", "sentinel_mcp_started", "request_contains_sentinel", "request_offers_tools"} <= set(control["failures"])
    assert "native_memory" in control["request_capture"]["sentinels_visible"] and "user_instruction" in control["request_capture"]["sentinels_visible"]
    assert any(h.startswith("user-") for h in control["hooks_fired"])


@pytest.mark.skipif(installed_claude() is None, reason="the Claude Code CLI is not installed here; the fake CLI covers this platform")
def test_installed_cli_isolation_from_a_host_marked_parent():
    """The installed host in request-capture mode (loopback, placeholder key; this session's route is never used)."""
    exe = installed_claude()
    inherited = {**os.environ, "CLAUDECODE": "1", "CLAUDE_CODE_CHILD_SESSION": "1", **DECOYS}
    check = isolation.isolation_check(cli_config(executable=exe), inherited=inherited)
    assert check["verdict"] == "pass", check["failures"]
    assert check["init"]["tools"] == [] and check["init"]["mcp_servers"] == [] and check["init"]["non_builtin_plugins"] == []
    assert check["environment"]["method"] == "linux_proc_environ" if sys.platform.startswith("linux") else True
    assert check["environment"]["host_markers_present"] == [] and not set(DECOYS) & set(check["environment"]["child_keys"])
    assert check["certifies"] is False and check["host_version"]


def test_recursion_marker_is_not_no_hooks_proof(tmp_path):
    """A hook that runs in a curator carrying the recursion marker still fails isolation and withdraws the route."""
    check = isolation.isolation_check(cli_config(scenario="ignores_bare"), inherited=dict(os.environ))
    assert check["environment"]["curator_marker_names_installation"]  # the marker was there ...
    assert "sentinel_hook_ran" in check["failures"] and check["verdict"] == "fail"  # ... and the hook still ran: not isolated
    # A route whose (controlled, unit-constructed) certification still matches is withdrawn by the failed recheck.
    from recalith.contracts.config import ProjectConfig
    from recalith.contracts.common import Actor
    from recalith.core import identity

    root = tmp_path / "project"
    root.mkdir()
    identity.initialize_installation(root, ProjectConfig.defaults_for("proj_41414141-4141-4141-8141-414141414141"))
    ctx = identity.resolve_installation(root, actor=Actor(kind="controller", id="t", channel="worker"))
    cfg = cli_config(scenario="ignores_bare", installation_id=ctx.installation_id)
    version = base.observe_version(cfg, sys.executable, os.environ)
    cert = {
        "certified": True, "certified_at": "2026-10-17T00:00:00.000000Z", "host_version": version, "report_digest": digest_of(["unit"]), "executable_sha256": base.executable_digest(sys.executable),
        "mode": "live", "operator_attestation": "checked_eligible", "auth_env_keys": ["ANTHROPIC_API_KEY"], "expected_api_key_source": None, "invocation_digest": base.invocation_digest(cfg),
    }
    base.save_provider_config(root, ProviderConfig.model_validate({**cfg.model_dump(mode="json"), "certification": cert}))
    provider = base.ProviderSupervisor(ctx, inherited={**os.environ, "ANTHROPIC_API_KEY": "unit-" + "route"})
    assert provider.status.certified and provider.backend is not None
    provider.start()
    assert provider.ready.wait(120)
    assert not provider.available and provider.backend.unavailable_reason == "isolation_recheck_failed"
    record = base.read_check(root)
    assert record["route"]["state"] == "unavailable" and "sentinel_hook_ran" in record["isolation_check"]["failures"]


# ---------------------------------------------------------------------------
# A67: hook → worker → curator, from a host-marked parent


@pytest.fixture
def started():
    roots: list[Path] = []
    yield roots
    leftovers = [str(r) for r in roots if not wh.stop_worker(r)]
    assert not leftovers, f"workers did not stop on request and were killed: {leftovers}"


def test_hook_started_worker_rechecks_curator_isolation(tmp_path, started):
    """The real hook entry, run from a host-marked parent with decoy credentials, starts the worker; the
    worker's own provider recheck launches the configured curator from the worker's environment."""
    replayer = cf.Replay(tmp_path / "replay")
    wh.enable_autostart(replayer)
    started.append(replayer.root)
    ctx = replayer.ctx
    exe = installed_claude()
    cfg = cli_config(installation_id=ctx.installation_id, executable=exe)
    base.save_provider_config(replayer.root, cfg)
    env = wh.marked_env(**DECOYS, RECALITH_WORKER_INSTALLATION="inst_99999999-9999-4999-8999-999999999999", HOME=str(tmp_path))
    records = iter([wh.start_record()] + [wh.prompt_record()] * 4)

    def run() -> str:
        rec = next(records)
        reply = tmp_path / f"reply-{time.monotonic_ns()}.json"
        proc, _wall = cf.run_hook(replayer.root, replayer.prepare(rec), event=rec["event"], reply=reply, env=env)
        assert proc.returncode == 0, proc.stderr[-2000:]
        return json.loads(reply.read_text(encoding="utf-8"))["worker"]

    statuses = wh.start_via_hook(run)
    assert statuses[-1] == "worker_started", statuses
    record = wh.wait_for(lambda: (base.read_check(replayer.root) or {}).get("isolation_check") and base.read_check(replayer.root), 120)
    assert record, "the hook-started worker never reported its provider recheck"
    check = record["isolation_check"]
    assert check["verdict"] == "pass", check["failures"]
    envr = check["environment"]
    assert envr["host_markers_present"] == [] and not envr["worker_marker_present"] and envr["curator_marker_names_installation"]
    assert not set(DECOYS) & set(envr["child_keys"]) and "CLAUDECODE" not in envr["child_keys"]
    if sys.platform.startswith("linux"):
        assert envr["method"] == "linux_proc_environ"
    # Recheck never certifies: the uncertified route stays unavailable and model jobs wait visibly.
    assert record["route"]["state"] == "unavailable" and "route_uncertified" in record["route"]["reasons"]
    status = wh.wait_for(lambda: (wh.status(replayer.root) or {}).get("provider", {}).get("isolation_recheck") and wh.status(replayer.root), 30)
    assert status and status["environment"]["host_markers_present"] == [] and status["environment"]["role_marker"] == ctx.installation_id
    assert status["model_lane"] == "provider_unavailable" and status["provider"]["isolation_recheck"]["verdict"] == "pass"
