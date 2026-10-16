"""Test factories: build *valid* contract objects for tests.

Factories only assemble well-formed inputs. They never implement production
decisions (admission, retrieval, forgetting) and must not be used as such.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from recalith.contracts.common import (
    Actor,
    InstallationContext,
    RecordRef,
    SourceRef,
    derived_id,
    digest_of,
    new_id,
    utc_now,
)
from recalith.contracts.config import ProjectConfig

PROJECT = "proj_11111111-1111-4111-8111-111111111111"
INSTALL = "inst_22222222-2222-4222-8222-222222222222"
WORKSPACE = "ws_33333333-3333-4333-8333-333333333333"
SESSION = "sess_44444444-4444-4444-8444-444444444444"
TIME = "2026-10-15T12:00:00.000000Z"
ADAPTER = "claude_code"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def event_id(key: str, *, installation: str = INSTALL, adapter: str = ADAPTER) -> str:
    return derived_id("evt", [installation, adapter, key])


def actor(kind: str = "adapter", channel: str = "hook") -> Actor:
    return Actor(kind=kind, id=f"{kind}-1", channel=channel)


def context(tmp: Path, **overrides: Any) -> InstallationContext:
    data: dict[str, Any] = dict(
        project_id=PROJECT,
        installation_id=INSTALL,
        root=tmp,
        workspace_id=WORKSPACE,
        workspace_root=tmp,
        engine_version="0.1.0.dev0",
        schema_version=1,
        policy_revision=1,
        actor=actor(),
    )
    data.update(overrides)
    return InstallationContext(**data)


def action(**overrides: Any) -> dict[str, Any]:
    data = {"cwd_path": ".", "tool": "Bash", "action_kind": "test", "executable": "python", "argv": ["python", "-m", "unittest"], "paths": [], "raw_digest": None, "parse_status": "exact", "shell": "bash"}
    data.update(overrides)
    return data


def tool_payload(**overrides: Any) -> dict[str, Any]:
    data = {
        "tool_call_id": "call-1",
        "tool_name": "Bash",
        "arguments": {"command": "python -m unittest"},
        "result_received": True,
        "outcome": "failure",
        "exit_code": 1,
        "result_text": "FAILED (errors=1)",
        "assertions": [{"kind": "exit_status", "identity": "exit", "value": "1", "passed": None}],
        "action": action(),
        "observation": None,
        "text_chunks": [],
        "error_signature": "ModuleNotFoundError: No module named 'ledgerlite'",
        "expected_red": False,
    }
    data.update(overrides)
    return data


def envelope(kind: str = "tool_finished", payload: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    """A valid wire-shaped event envelope as plain JSON data."""
    defaults: dict[str, tuple[str, str, dict[str, Any]]] = {
        "tool_finished": ("tool", "observed_tool", tool_payload()),
        "tool_started": ("tool", "observed_tool", tool_payload(result_received=False, outcome="unknown", exit_code=None, result_text=None, assertions=[], error_signature=None)),
        "user_message": ("user", "explicit_user", {"text": "Please run the tests."}),
        "assistant_message": ("assistant", "untrusted", {"text": "Running the tests now."}),
        "session_started": ("external", "untrusted", {"source": "startup"}),
        "memory_delivered": ("memory", "derived", {"delivery_id": "dlv_55555555-5555-4555-8555-555555555555"}),
        "agent_attempted_operator_command": ("memory", "derived", {"command_kind": "declare", "marker_category": "host_agent", "reason_code": "policy_refused"}),
    }
    channel, authority, default_payload = defaults[kind]
    body = payload if payload is not None else default_payload
    key = overrides.pop("source_event_key", f"{kind}-1")
    data: dict[str, Any] = {
        "schema_version": 1,
        "event_id": event_id(key),
        "project_id": PROJECT,
        "installation_id": INSTALL,
        "workspace_id": WORKSPACE,
        "adapter_id": ADAPTER,
        "adapter_version": "2.1.301",
        "source_event_key": key,
        "session_id": SESSION,
        "host_session_id": "host-session-1",
        "task_id": None,
        "source_sequence": 1,
        "occurred_at": TIME,
        "recorded_at": TIME,
        "kind": kind,
        "channel": channel,
        "origin": {"adapter_id": ADAPTER, "source_event_key": key, "host_session_id": "host-session-1", "origin_kind": "hook", "source_digest": digest_of(body), "locator": None},
        "authority": authority,
        "derived_from": [],
        "root_event_ids": [],
        "payload": body,
        "payload_digest": digest_of(body),
        "coverage": {"truncated": False, "redacted": False, "missing_context": False, "parser_complete": True},
        "extensions": {},
    }
    data.update(overrides)
    if "payload" in overrides and "payload_digest" not in overrides:
        data["payload_digest"] = digest_of(overrides["payload"])
    return data


def ref(kind: str = "claim", rid: str | None = None, revision: int = 1) -> dict[str, Any]:
    prefix = {"claim": "claim", "event": "evt", "task": "task", "episode": "ep", "capsule": "cap"}[kind]
    if rid is None:
        rid = new_id(prefix) if prefix != "evt" else event_id("ref-event")
    return {"kind": kind, "id": rid, "revision": revision}


def evidence_link(**overrides: Any) -> dict[str, Any]:
    data = {"ref": ref("event", event_id("tool_finished-1")), "relation": "supports", "root_event_ids": [event_id("tool_finished-1")], "locator": None, "mapping": "tool.exit_code"}
    data.update(overrides)
    return data


def supported(text: str = "The tests failed with an import error.", basis: str = "observed") -> dict[str, Any]:
    return {"text": text, "evidence": [evidence_link()], "basis": basis}


def review(verdict: str = "supported", candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "review_job_id": new_id("job"),
        "batch_id": new_id("batch"),
        "candidate_ref": candidate or ref("claim"),
        "proposal_digest": sha("proposal"),
        "evidence_digest": sha("evidence"),
        "prompt_digest": sha("review_v1"),
        "verdict": verdict,
        "objections": [],
        "evidence_refs": [evidence_link()] if verdict == "supported" else [],
        "reviewed_at": TIME,
    }


def claim(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "claim_id": new_id("claim"),
        "project_id": PROJECT,
        "installation_id": INSTALL,
        "revision": 1,
        "kind": "fact",
        "proposition": "Tests run with `python -m unittest discover -s tests -t .`.",
        "proposition_key": {"subject": "test command", "predicate": "works"},
        "scope": {},
        "conditions": [],
        "basis": "observed",
        "strength": "supported",
        "status": "active",
        "freshness": "current",
        "supports": [evidence_link()],
        "contradicts": [],
        "evidence_availability": "available",
        "recorded_at": TIME,
        "dependencies": [],
        "review_class": "volatile",
    }
    data.update(overrides)
    return data


def operation(kind: str, payload: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    data = {"local_ref": overrides.pop("local_ref", "op1"), "kind": kind, "depends_on": [], "target": None, "payload": payload, "evidence": [], "reason": "because"}
    data.update(overrides)
    return data


def claim_payload(**overrides: Any) -> dict[str, Any]:
    data = {"kind": "fact", "proposition": "The package uses a src layout.", "proposition_key": {"subject": "layout", "predicate": "is"}, "basis": "observed"}
    data.update(overrides)
    return data


def config(**overrides: Any) -> ProjectConfig:
    return ProjectConfig.defaults_for(PROJECT, **overrides)


def now() -> str:
    return utc_now()


SOURCE_REF = SourceRef(adapter_id=ADAPTER, source_event_key="k", host_session_id="h", origin_kind="hook", source_digest=sha("x"))
RECORD = RecordRef(kind="claim", id="claim_66666666-6666-4666-8666-666666666666", revision=1)
