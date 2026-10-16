"""Hook entry point: capture-only fast path (DATA_CONTRACTS §2.3; SYSTEM_SPEC §5.1).

    python -I -m recalith.fast.entry --project ROOT claude_code [--event NAME]

The project's hook launcher (``.recalith/bin/recalith-hook``) runs this with
the pinned interpreter. It imports only the standard library and
``recalith.fast``; it never opens SQLite, calls a model, touches the network
or probes a runtime. The one process it may launch is this installation's
worker, through the registered internal start path
(:func:`recalith.fast.process_env.ensure_worker`), after capture, only when
the manifest enables autostart and no worker holds the installation lock, and
without waiting for it. It always exits 0 with empty stdout: the host's
nonblocking empty success. Operational failures become content-free gap
records in ``spool/gaps/`` for health, never a blocked or failed host step.

One monotonic soft deadline starts at entry + 250 ms and is shared by every
substep. Durable capture has priority: once publication has begun it is never
abandoned because time ran out, and the receipt then reports
``capture_deadline_overrun``. Python's clock cannot interrupt a blocked
``fsync``/rename; the deadline schedules optional work, it does not bound
storage latency. After capture the optional work in this build is, in
priority order, the worker start (shed with ``deadline_worker_start_skipped``
below 30 ms of remaining time), the post-tool typed-outcome overlay and
pruning abandoned scratch at session start. Delivery is advertised
unavailable and no context is emitted (Task 12b adds delivery; Task 13
certifies it).
"""

from __future__ import annotations

import json
import os
import sys
import time

from recalith.fast import claude_capture, failpoints, process_env, redact, session, spool
from recalith.fast.normalize import normalize_raw
from recalith.fast.wire import LIMITS, WireError, canonical_json, derived_id, digest_of, is_id, is_valid, new_id, utc_now, validate

HOOK_CONTEXT_FILE = os.path.join(".recalith", "run", "hook-context.json")
SOFT_DEADLINE_SECONDS = LIMITS["HOOK_SOFT_DEADLINE_MS"] / 1000
SEGMENT_CAP = LIMITS["SEGMENT_CAP"]
SEGMENT_MARGIN = 4 * 1024
MAX_HOOK_INPUT = 4 * 1024 * 1024
CURATOR_MARKER = process_env.CURATOR_MARKER
ADAPTERS = ("claude_code",)
DELIVERY_UNAVAILABLE = {"state": "unavailable", "reason": "capture_only_build"}
PRUNE_MIN_REMAINING = 0.100


# --------------------------------------------------------------------------
# HookContextWire: read from the validated local manifest, never from input
#
# context_schema 2 adds ``worker = {autostart, route_keys}`` (decision 0006);
# a schema-1 manifest still captures, with worker autostart off.

MANIFEST_V1_KEYS = frozenset({"context_schema", "project_id", "installation_id", "workspace_id", "root", "workspace_root", "root_identity", "workspace_root_identity", "policy_revision", "adapters"})
MANIFEST_V2_KEYS = MANIFEST_V1_KEYS | {"worker"}


def _identity_of(path: str) -> str:
    st = os.stat(path)
    return f"{st.st_dev}:{st.st_ino}"


def load_context(root: str, adapter_id: str) -> dict:
    """The validated ``HookContextWire`` for ``adapter_id`` at exactly ``root``.

    Raises ``WireError``: ``capability_unavailable`` when no manifest exists
    (not integrated), ``invalid_schema`` when it is malformed, and
    ``installation_relocated`` when the checkout no longer is the recorded one.
    """
    path = os.path.join(root, HOOK_CONTEXT_FILE)
    try:
        with open(path, "rb") as fh:
            raw = json.loads(fh.read(64 * 1024).decode("utf-8"))
    except FileNotFoundError:
        raise WireError("capability_unavailable", "hook context manifest is absent") from None
    except (OSError, ValueError):
        raise WireError("invalid_schema", "hook context manifest is unreadable") from None
    if not valid_context_manifest(raw) or adapter_id not in raw["adapters"]:
        raise WireError("invalid_schema", "hook context manifest is invalid")
    try:
        if _identity_of(root) != raw["root_identity"] or _identity_of(raw["workspace_root"]) != raw["workspace_root_identity"]:
            raise WireError("installation_relocated", "the checkout is not the recorded installation root")
    except OSError:
        raise WireError("installation_relocated", "the recorded installation root is unavailable") from None
    adapter = raw["adapters"][adapter_id]
    worker = raw.get("worker") or {"autostart": False, "route_keys": []}
    return {
        "project_id": raw["project_id"],
        "installation_id": raw["installation_id"],
        "workspace_id": raw["workspace_id"],
        "root": root,
        "workspace_root": raw["workspace_root"],
        "root_identity": raw["root_identity"],
        "workspace_root_identity": raw["workspace_root_identity"],
        "policy_revision": raw["policy_revision"],
        "adapter_id": adapter_id,
        "host_version": adapter["host_version"],
        "delivery_enabled": False,  # capture-only build: never enabled, whatever the manifest says
        "worker_autostart": worker["autostart"],
        "worker_route_keys": list(worker["route_keys"]),
    }


def valid_context_manifest(raw) -> bool:
    if not isinstance(raw, dict) or type(raw.get("context_schema")) is not int:
        return False
    if (raw["context_schema"], set(raw)) not in ((1, MANIFEST_V1_KEYS), (2, MANIFEST_V2_KEYS)):
        return False
    if type(raw["policy_revision"]) is not int or raw["policy_revision"] < 1:
        return False
    if raw["context_schema"] == 2 and not valid_worker_section(raw["worker"]):
        return False
    for key, prefix in (("project_id", "proj_"), ("installation_id", "inst_"), ("workspace_id", "ws_")):
        if not (isinstance(raw[key], str) and raw[key].startswith(prefix) and is_id(raw[key])):
            return False
    for key in ("root", "workspace_root"):
        if not isinstance(raw[key], str) or not os.path.isabs(raw[key]):
            return False
    for key in ("root_identity", "workspace_root_identity"):
        if not isinstance(raw[key], str) or raw[key].count(":") != 1:
            return False
    adapters = raw["adapters"]
    if not isinstance(adapters, dict):
        return False
    for name, entry in adapters.items():
        if name not in ADAPTERS or not isinstance(entry, dict) or set(entry) != {"host_version", "delivery_enabled"}:
            return False
        if not (entry["host_version"] is None or (isinstance(entry["host_version"], str) and 1 <= len(entry["host_version"]) <= 64)) or entry["delivery_enabled"] is not False:
            return False
    return True


def valid_worker_section(worker) -> bool:
    """``{autostart: bool, route_keys: [names]}``; route keys may never name a marker."""
    if not isinstance(worker, dict) or set(worker) != {"autostart", "route_keys"} or type(worker["autostart"]) is not bool:
        return False
    keys = worker["route_keys"]
    if not isinstance(keys, list) or len(keys) > process_env.MAX_KEYS:
        return False
    return all(isinstance(k, str) and process_env._NAME.match(k) and not process_env._forbidden(k) for k in keys)


# --------------------------------------------------------------------------
# hook_capture: the stdlib spool producer


def _not_captured(reason: str, *, error_code: str = "not_captured", **coverage) -> dict:
    return {"status": "not_captured", "segment_id": None, "event_ids": [], "coverage": {"reason": reason, **coverage}, "error_code": error_code}


def _pack(envelopes: list, registrations: list) -> list:
    """≤256 KiB segments; source registrations ride in the last one."""
    budget = SEGMENT_CAP - SEGMENT_MARGIN - len(canonical_json(registrations))
    groups: list[list] = [[]]
    used = 0
    for env in envelopes:
        size = len(canonical_json(env)) + 1
        if groups[-1] and used + size > budget:
            groups.append([])
            used = 0
        groups[-1].append(env)
        used += size
    return [(group, registrations if index == len(groups) - 1 else []) for index, group in enumerate(groups)]


def hook_capture(ctx: dict, events, *, source_registrations=(), deadline: float | None = None, platform: str = os.name, scrubbed_in_process=frozenset()) -> dict:
    """Durably spool normalized envelope dicts; acknowledge only after publication.

    Returns a ``CaptureReceipt`` dict. Re-checks ownership, derived identity,
    identity-field secrets and scrubbing, and validates every envelope and
    segment with the generated wire validators. Never raises for I/O.
    ``scrubbed_in_process`` names events that ``normalize_raw`` produced in
    this same call (it scrubs before anything else), so their payload re-scan
    is skipped; every other caller's events are re-scanned.
    """
    deadline = time.monotonic() + SOFT_DEADLINE_SECONDS if deadline is None else deadline
    dirs = spool.SpoolDirs(ctx["root"])
    registrations = [dict(r) for r in source_registrations]
    accepted: list = []
    rejected: dict[str, int] = {}
    for env in events:
        errors, env = validate("EventEnvelope", env)
        if errors:
            rejected["invalid_schema"] = rejected.get("invalid_schema", 0) + 1
            continue
        if (env["installation_id"], env["project_id"], env["workspace_id"]) != (ctx["installation_id"], ctx["project_id"], ctx["workspace_id"]):
            return _not_captured("foreign_installation", error_code="foreign_installation")
        if env["event_id"] != derived_id("evt", [ctx["installation_id"], env["adapter_id"], env["source_event_key"]]):
            return _not_captured("event_identity_conflict", error_code="event_identity_conflict")
        origin = env["origin"]
        if any(redact.contains_secret(v) for v in (origin["source_event_key"], origin["host_session_id"], origin["locator"] or "")) or not identity_is_clean_env(env):
            rejected["policy_refused"] = rejected.get("policy_refused", 0) + 1
            continue
        if env["event_id"] not in scrubbed_in_process and (redact.scrub_json(env["payload"])[1].total or (env["extensions"] and redact.scrub_json(env["extensions"])[1].total)):
            rejected["invalid_schema"] = rejected.get("invalid_schema", 0) + 1  # never spool unscrubbed bytes
            continue
        accepted.append(env)
    for reg in registrations:
        if not is_valid("SourceRegistrationProposal", reg):
            return _not_captured("registration_invalid", error_code="invalid_schema")
    if not accepted:
        error = "policy_refused" if rejected.get("policy_refused") else "invalid_schema"
        return _not_captured("no_capturable_events", error_code=error, rejected=rejected)
    segment_ids: list[str] = []
    rename_retried = overrun = False
    dir_synced = True
    for envelopes, segment_registrations in _pack(accepted, registrations):
        segment_id = new_id("seg")
        created_at = utc_now()
        segment = {
            "segment_schema": 1,
            "segment_id": segment_id,
            "project_id": ctx["project_id"],
            "installation_id": ctx["installation_id"],
            "envelopes": envelopes,
            "cursor_proposals": [],
            "source_registrations": segment_registrations,
            "created_at": created_at,
            "content_digest": digest_of(spool.segment_body(envelopes, [], segment_registrations)),
        }
        if validate("Segment", segment)[0]:
            return _not_captured("segment_invalid", error_code="invalid_schema")
        outcome = spool.publish(dirs, spool.segment_file_name(created_at, segment_id), canonical_json(segment), deadline=deadline, platform=platform)
        if not outcome.ok:
            spool.record_gap(dirs, code="not_captured", reason=outcome.reason or "io_error", event_count=len(accepted), at=utc_now())
            return _not_captured(outcome.reason or "io_error", published_unacknowledged=len(segment_ids), rename_retried=outcome.rename_retried)
        segment_ids.append(segment_id)
        rename_retried = rename_retried or outcome.rename_retried
        overrun = overrun or outcome.deadline_overrun
        dir_synced = dir_synced and outcome.dir_synced
    failpoints.hit(failpoints.SPOOL_AFTER_PUBLISH)
    coverage: dict = {"segment_ids": segment_ids, "dir_synced": dir_synced, "cursors_persisted": True}
    if rejected:
        coverage["rejected"] = rejected
    if rename_retried:
        coverage["rename_retried"] = True
    if overrun or time.monotonic() > deadline:
        coverage["degraded"] = ["capture_deadline_overrun"]
    return {"status": "accepted", "segment_id": segment_ids[-1], "event_ids": [e["event_id"] for e in accepted], "coverage": coverage, "error_code": None}


def identity_is_clean_env(env: dict) -> bool:
    return not any(redact.contains_secret(v) for v in (env["source_event_key"], env["host_session_id"], env["adapter_version"]))


# --------------------------------------------------------------------------
# handle_hook: the capture branch


def _gap(ctx: dict, code: str, reason: str, count: int = 1) -> None:
    spool.record_gap(spool.SpoolDirs(ctx["root"]), code=code, reason=reason, event_count=count, at=utc_now())


def normalize_request(ctx: dict, request: dict) -> dict:
    """Normalize the adapter's raw events into validated envelope dicts (in place)."""
    ids = {"project_id": ctx["project_id"], "installation_id": ctx["installation_id"], "workspace_id": ctx["workspace_id"]}
    events = list(request.get("events") or [])
    produced = set()
    for raw in request.pop("raw_events", []):
        try:
            envelopes, _notes = normalize_raw(ids, raw)
        except WireError as exc:
            request["coverage_gaps"].append({"code": "event_refused", "reason": exc.code})
            continue
        events.extend(envelopes)
        produced.update(id(env) for env in envelopes)
    request["events"] = events
    request["_scrubbed_in_process"] = produced
    return request


WORKER_DEGRADATIONS = frozenset({"worker_independence_degraded", "deadline_worker_start_skipped", "worker_start_unavailable", "worker_start_failed"})


def _start_worker(ctx: dict, reply: dict, *, deadline: float, inherited) -> None:
    """The registered internal worker start (never the ``recalith worker`` CLI)."""
    try:
        status = process_env.ensure_worker(ctx, deadline=deadline, inherited=inherited)
    except Exception:  # noqa: BLE001 - starting the worker never fails the hook
        status = "worker_start_failed"
    reply["worker"] = status
    if status in WORKER_DEGRADATIONS:
        reply["degradations"].append(status)


def handle_hook(ctx: dict, request: dict, *, deadline: float, inherited=None) -> dict:
    """Capture branch of DATA_CONTRACTS §2.3 ``handle_hook``; returns ``HookReplyWire``.

    ``inherited`` is the hook's own environment, the source for the worker's
    fresh allowlisted environment; it is never modified.
    """
    reply: dict = {"receipt": None, "host_output": None, "delivery_attempt_id": None, "emitted_receipt": None, "delivery": dict(DELIVERY_UNAVAILABLE), "degradations": [], "worker": None}
    for gap in request.get("coverage_gaps", []):
        _gap(ctx, gap["code"], gap["reason"])
        if gap["code"] not in reply["degradations"]:
            reply["degradations"].append(gap["code"])
    if request.get("events"):
        produced = request.get("_scrubbed_in_process", set())
        scrubbed = frozenset(env["event_id"] for env in request["events"] if id(env) in produced)
        receipt = hook_capture(ctx, request["events"], source_registrations=request.get("source_registrations", ()), deadline=deadline, scrubbed_in_process=scrubbed)
        reply["receipt"] = receipt
        reply["degradations"].extend(receipt["coverage"].get("degraded", []))
    # Capture has finished (acknowledged or not): only now may the worker start.
    _start_worker(ctx, reply, deadline=deadline, inherited=inherited)
    if request.get("events"):
        receipt = reply["receipt"]
        if receipt["status"] != "accepted":
            reply["degradations"].append("capture_not_acknowledged")
            return reply
        role = request.get("event_role")
        first = request["events"][0]
        if role == "post_tool" and first["kind"] == "tool_finished":
            status = session.record_outcome(ctx["root"], first["session_id"], session.outcome_from_envelope(first), policy_revision=ctx["policy_revision"], deadline=deadline)
            if status != "updated":
                reply["degradations"].append(status)
        elif role == "end":
            status = session.discard(ctx["root"], first["session_id"], deadline=deadline)
            if status != "discarded":
                reply["degradations"].append(status)
        elif role == "session_start" and deadline - time.monotonic() > PRUNE_MIN_REMAINING:
            session.prune_abandoned(ctx["root"])
    return reply


# --------------------------------------------------------------------------
# Process entry


def run(root: str, adapter_id: str, data: bytes, *, registered_event: str | None, env, deadline: float) -> dict:
    """Everything after argument parsing; returns the ``HookReplyWire``."""
    base = {"receipt": None, "host_output": None, "delivery_attempt_id": None, "emitted_receipt": None, "delivery": dict(DELIVERY_UNAVAILABLE), "degradations": [], "worker": None}
    if env.get(CURATOR_MARKER):
        base["degradations"].append("curator_session_ignored")  # SYSTEM_SPEC §5.3: never evidence
        return base
    if adapter_id not in ADAPTERS:
        base["degradations"].append("adapter_unavailable")
        return base
    try:
        ctx = load_context(root, adapter_id)
    except WireError as exc:
        base["degradations"].append(exc.code)
        return base
    if len(data) > MAX_HOOK_INPUT:
        _gap(ctx, "not_captured", "host_payload_too_large")
        base["degradations"].append("host_payload_too_large")
        return base
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        _gap(ctx, "not_captured", "host_payload_malformed")
        base["degradations"].append("host_payload_malformed")
        return base
    try:
        request = claude_capture.map_hook(ctx, payload, registered_event=registered_event)
    except claude_capture.HookInputError as exc:
        _gap(ctx, "not_captured", exc.code)
        base["degradations"].append(exc.code)
        return base
    return handle_hook(ctx, normalize_request(ctx, request), deadline=deadline, inherited=env)


def _parse_args(argv: list) -> tuple:
    root = adapter = event = reply_file = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--project", "--event", "--reply-file") and i + 1 < len(argv):
            value = argv[i + 1]
            if arg == "--project":
                root = value
            elif arg == "--event":
                event = value
            else:
                reply_file = value
            i += 2
            continue
        if adapter is None and not arg.startswith("-"):
            adapter = arg
        i += 1
    return root, adapter, event, reply_file


def main(argv: list | None = None, *, stdin=None, env=None) -> int:
    start = time.monotonic()
    deadline = start + SOFT_DEADLINE_SECONDS
    reply = None
    root, adapter, event, reply_file = _parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        stream = stdin if stdin is not None else sys.stdin.buffer
        data = stream.read(MAX_HOOK_INPUT + 1)
        if root and adapter:
            reply = run(os.path.realpath(root), adapter, data, registered_event=event, env=os.environ if env is None else env, deadline=deadline)
    except Exception:  # noqa: BLE001 - a hook never fails the host
        reply = {"degradations": ["hook_internal_error"]}
    if reply_file:
        try:
            reply = dict(reply or {}, elapsed_ms=round((time.monotonic() - start) * 1000, 3))
            with open(reply_file, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(reply, sort_keys=True))
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
