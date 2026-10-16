"""Task 3: declared vs observed runtime provenance and allowlisted environment (A52, A54)."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

import capture_scenarios as cs
from recalith.capture import pipeline, provenance
from recalith.capture.normalize import RawEvent, normalize_event
from recalith.contracts.common import Actor, digest_of
from recalith.contracts.events import EventEnvelope
from recalith.core import identity
from recalith.errors import RecalithError
from recalith.storage import db

CONTROLLER = Actor(kind="controller", id="worker", channel="worker")
FP1, FP2 = "1" * 64, "2" * 64


@pytest.fixture
def root(tmp_path):
    return cs.init_project(tmp_path, "proj")


def controller(root):
    return identity.resolve_installation(root, actor=CONTROLLER)


def version_event(ctx, key, *, exe="python", output="Python 3.12.4", at="2026-10-16T10:00:00.000000Z", certified=True, argv=None):
    argv = argv or [exe, "--version"]
    raw = RawEvent(
        adapter_id=cs.ADAPTER, adapter_version="1", source_event_key=key, session_id=cs.SESSION, host_session_id=cs.HOST_SESSION, kind="tool_finished", occurred_at=at, certified=certified,
        payload={"tool_call_id": key, "tool_name": "Bash", "arguments": {"command": " ".join(argv)}, "result_received": True, "outcome": "success", "exit_code": 0, "result_text": output, "action": cs.action(argv), "observation": None},
    )
    return normalize_event(ctx, raw)[0]


def ingest(ctx, events):
    assert pipeline.capture(ctx, events).status == "accepted"
    return pipeline.ingest_ready(ctx)


def resolve(root, key, **kw):
    ctx = controller(root)
    with db.open_store(ctx, readonly=True) as store:
        return provenance.resolve(store, ctx, key, **kw)


def register(root, identity_, fingerprint):
    ctx = controller(root)
    with db.open_store(ctx) as store:
        return provenance.register_executable(store, ctx, identity=identity_, fingerprint=fingerprint)


def guidance_epoch(root):
    with db.open_store(controller(root), readonly=True) as store:
        return store.meta().guidance_epoch


def test_recalith_interpreter_is_never_project_python(root):
    resolved = resolve(root, "python_version")
    assert resolved.value is None and resolved.reason == "missing"
    with db.open_store(controller(root), readonly=True) as store:
        values = provenance.environment_values(store, controller(root))
    assert "python_version" not in values
    assert sys.version.split()[0] not in values.values()


def test_declared_runtime_is_current_only_for_its_config_revision(root):
    ctx = controller(root)
    with db.open_store(ctx) as store:
        provenance.record_declared_runtime(store, ctx, key="python_version", value="3.12.4", config_revision=1)
    assert resolve(root, "python_version").value == "3.12.4" and resolve(root, "python_version").reason == "declared"
    # A new policy/config revision without a matching declaration makes it non-current.
    conn = sqlite3.connect(root / ".recalith/state/memory.sqlite")  # controlled-state fixture
    try:
        with conn:
            conn.execute("UPDATE installation_meta SET policy_revision = 2")
    finally:
        conn.close()
    assert resolve(root, "python_version").value is None


def test_observed_version_requires_a_registered_executable(root):
    ctx = controller(root)
    ingest(ctx, version_event(ctx, "v1"))
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        row = view.execute("SELECT executable_id, executable_fingerprint, freshness, source_kind FROM environment_observations WHERE key = 'python_version'").fetchone()
    assert row == (None, None, "unknown", "certified_tool")
    assert resolve(root, "python_version").value is None  # unknown binding certifies nothing


def test_fingerprint_change_makes_older_observation_stale(root):
    ctx = controller(root)
    register(root, "python", FP1)
    ingest(ctx, version_event(ctx, "v1"))
    assert resolve(root, "python_version").value == "3.12.4" and resolve(root, "python_version").reason == "observed"
    assert resolve(root, "python_version", executable_identity="python").value == "3.12.4"
    epoch = guidance_epoch(root)
    register(root, "python", FP2)  # executable upgraded
    assert guidance_epoch(root) > epoch
    stale = resolve(root, "python_version")
    assert stale.value is None and stale.reason == "stale"
    assert resolve(root, "python_version", executable_identity="python").value is None
    # A fresh certified observation after the change restores a current value.
    ingest(ctx, version_event(ctx, "v2", output="Python 3.13.0", at="2099-01-01T00:00:00.000000Z"))
    assert resolve(root, "python_version").value == "3.13.0"


def test_observation_predating_registered_change_is_stale(root):
    ctx = controller(root)
    register(root, "python", FP1)
    register(root, "python", FP2)  # change registered "now"
    ingest(ctx, version_event(ctx, "old", at="2001-01-01T00:00:00.000000Z"))  # observed long before
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        assert view.execute("SELECT freshness FROM environment_observations").fetchone()[0] == "stale"
    assert resolve(root, "python_version").value is None


def test_untrusted_or_uncertified_sources_cannot_certify_a_runtime(root):
    ctx = controller(root)
    register(root, "python", FP1)
    register(root, "echo", FP1)
    # Same text printed by an arbitrary command.
    ingest(ctx, version_event(ctx, "echo", exe="echo", argv=["echo", "Python", "3.9.0"], output="Python 3.9.0"))
    # An uncertified source running the real command.
    ingest(ctx, version_event(ctx, "uncertified", certified=False))
    # A hand-made parsed_value assertion smuggled into an envelope for a non-version action.
    (env,) = version_event(ctx, "smuggled", exe="make", argv=["make", "test"], output="ok")
    data = env.model_dump(mode="json")
    data["payload"]["assertions"].append({"kind": "parsed_value", "identity": "python_version", "value": "2.7.18", "passed": None})
    data["payload_digest"] = digest_of(data["payload"])
    ingest(ctx, [EventEnvelope.model_validate(data)])
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        assert view.execute("SELECT COUNT(*) FROM environment_observations").fetchone()[0] == 0
    assert resolve(root, "python_version").value is None


def test_conflicting_sources_resolve_unknown(root):
    ctx = controller(root)
    register(root, "python", FP1)
    register(root, ".venv/bin/python", FP1)
    ingest(ctx, version_event(ctx, "a", exe="python", output="Python 3.11.9"))
    ingest(ctx, version_event(ctx, "b", exe=".venv/bin/python", output="Python 3.12.4"))
    assert resolve(root, "python_version").reason == "conflict" and resolve(root, "python_version").value is None
    assert resolve(root, "python_version", executable_identity=".venv/bin/python").value == "3.12.4"
    with db.open_store(ctx) as store:
        provenance.record_declared_runtime(store, ctx, key="python_version", value="3.12.4", config_revision=1)
    assert resolve(root, "python_version", executable_identity="python").reason == "conflict"
    assert resolve(root, "python_version", executable_identity="unregistered-python").reason == "unbound"


def test_platform_facts_resolve_and_missing_keys_stay_unknown(root):
    ctx = controller(root)
    raw = RawEvent(adapter_id=cs.ADAPTER, adapter_version="1", source_event_key="start", session_id=cs.SESSION, host_session_id=cs.HOST_SESSION, kind="session_started",
                   payload={"environment": {"os": "macos", "arch": "aarch64", "python_version": "3.12.4", "PATH": "/usr/bin"}})
    ingest(ctx, normalize_event(ctx, raw)[0])
    with db.open_store(ctx, readonly=True) as store:
        values = provenance.environment_values(store, ctx)
    assert values == {"os": "macos", "arch": "aarch64"}  # ci missing → unknown; no runtime from platform


def test_only_operator_or_controller_registers_executables(root):
    agent_ctx = identity.resolve_installation(root, actor=Actor(kind="host_agent", id="agent", channel="mcp"))
    with db.open_store(agent_ctx) as store, pytest.raises(RecalithError, match="policy_refused"):
        provenance.register_executable(store, agent_ctx, identity="python", fingerprint=FP1)


def test_capture_modules_never_launch_processes():
    """Hooks and capture read persisted values; nothing here runs a version command."""
    src = Path(__file__).resolve().parents[2] / "src" / "recalith"
    for module in [*sorted((src / "capture").glob("*.py")), src / "storage" / "spool.py", src / "storage" / "failpoints.py"]:
        text = module.read_text(encoding="utf-8")
        assert "subprocess" not in text and "os.system" not in text and "popen" not in text.lower(), module


def test_executable_fingerprint_must_be_a_digest(root):
    with pytest.raises(RecalithError, match="invalid_schema"):
        register(root, "python", "not-a-digest")
