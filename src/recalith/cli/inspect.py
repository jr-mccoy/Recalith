"""Read-only CLI forms (DATA_CONTRACTS §12): no operator guard, no authority, bounded output.

``status``, ``doctor`` (no probes), ``observe``, ``context``, ``search``,
``show``, ``tasks|episodes|claims``, ``jobs list`` and the undo/forget
previews. The caller is a ``host_agent`` reader (``observe`` an agent
assertion); nothing here can write memory, and later-stage forms answer with
an explicit unavailable result.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Mapping, Sequence

from recalith import service
from recalith.cli.main import Form, Output, project_root
from recalith.errors import EXIT_CODES, RecalithError

MAX_STDIN_BYTES = 1024 * 1024
MAX_SELECTOR_BYTES = 1024 * 1024
CONTEXT_FIELDS = frozenset({"text", "action", "environment", "max_estimated_tokens", "branch_ref"})


def read_stdin_json() -> Any:
    data = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
    if len(data) > MAX_STDIN_BYTES:
        raise RecalithError("invalid_schema", "stdin exceeds 1 MiB")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise RecalithError("invalid_schema", "stdin is not a UTF-8 JSON value") from None


def read_selector(path: str):
    """A ``ForgetSelector`` file: bounded, strict, enumerated identifiers only (never executable text)."""
    from pydantic import ValidationError

    from recalith.contracts.privacy import ForgetSelector

    try:
        with open(path, "rb") as fh:
            raw = fh.read(MAX_SELECTOR_BYTES + 1)
    except OSError:
        raise RecalithError("invalid_schema", "the --selector file cannot be read") from None
    if len(raw) > MAX_SELECTOR_BYTES:
        raise RecalithError("invalid_schema", "the --selector file exceeds 1 MiB")
    try:
        return ForgetSelector.model_validate(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, ValueError, ValidationError):
        raise RecalithError("invalid_schema", "the --selector file is not a valid ForgetSelector") from None


def _integrity_progress(step: dict[str, Any]) -> None:
    """``doctor --full-integrity`` progress on stderr (table names and counts only; stdout stays one JSON object)."""
    print(f"integrity: {step['tables_done']}/{step['tables']} tables, {step['rows_scanned']} rows ({step['table']})", file=sys.stderr, flush=True)


def health_output(command: str, out: Output, ctx: Any, environ: Mapping[str, str], *, full_integrity: bool = False) -> int:
    """``status`` and ``doctor``: the JSON report under ``--json``; otherwise a one-screen header that names the next command.

    Exit 0 only when every required capability is healthy; otherwise 8 naming what is not (DATA_CONTRACTS §12)."""
    from recalith.contracts.health import HealthReport
    from recalith.operations.health import degraded_codes

    if command == "status":
        report = service.status(ctx, inherited=environ)
    else:
        report = service.doctor(ctx, inherited=environ, full_integrity=full_integrity, progress=_integrity_progress if full_integrity else None)
    verdict = HealthReport.model_validate(report["health"])
    degraded = [] if verdict.autonomous_ready else degraded_codes(verdict)
    chain = (report.get("checks") or {}).get("revision_chain")
    if isinstance(chain, dict) and chain.get("state") == "findings":
        degraded.append("revision_chain_findings")  # a detected out-of-band mutation is never exit 0 (decision 0024)
    if out.as_json:
        return out.success(report, degraded=degraded)
    out.text(human_summary(command, report, verdict, degraded))
    return 8 if degraded else 0


def human_summary(command: str, report: Mapping[str, Any], verdict: Any, degraded: Sequence[str]) -> list[str]:
    """The human form (audit 2026-11-06 REL-10): readiness, each required capability that is not healthy with its reasons'
    meanings and actions, the one next command, and where the full report is."""
    from recalith.contracts.health import DEFERRED_FULL_CAPABILITIES, REQUIRED_CAPABILITIES
    from recalith.operations import reasons

    lines = [
        f"Recalith {command}: readiness {verdict.readiness}" + ("" if verdict.autonomous_ready else " (not autonomous_ready)"),
        f"  engine {report.get('engine_version')} · profile {report.get('release_profile')} · store schema {report.get('schema_version')} · worker {report.get('worker_state')}",
    ]
    next_action: str | None = None
    if degraded:
        lines.append("Required capabilities that are not healthy:")
        # The next command follows the setup order of OPERATIONS §4: the curator route first, then the host.
        for name in sorted(REQUIRED_CAPABILITIES, key=lambda n: (n != "inference", REQUIRED_CAPABILITIES.index(n))):
            cap = verdict.capabilities[name]
            if cap.state == "healthy":
                continue
            lines.append(f"  {name}: {cap.state}")
            for code in cap.reason_codes:
                meaning, action = reasons.explain(code, cap.coverage)
                lines.append(f"    - {code}: {meaning}")
                lines.append(f"      do: {action}")
                if next_action is None and not action.startswith("see the"):
                    next_action = action
        for code in degraded:
            if code not in {c for name in REQUIRED_CAPABILITIES for c in verdict.capabilities[name].reason_codes}:
                meaning, action = reasons.explain(code)
                lines.append(f"  - {code}: {meaning}")
                lines.append(f"    do: {action}")
                next_action = next_action or action
    optional = [f"{name} ({', '.join(verdict.capabilities[name].reason_codes) or verdict.capabilities[name].state})" for name in verdict.capabilities if name not in REQUIRED_CAPABILITIES and name not in DEFERRED_FULL_CAPABILITIES and verdict.capabilities[name].state != "healthy"]
    if optional:
        lines.append("Optional capabilities not healthy (never gate readiness): " + "; ".join(optional))
    deferred = [name for name in DEFERRED_FULL_CAPABILITIES if name in verdict.capabilities]
    if deferred:
        lines.append(f"Deferred to the full release ({len(deferred)} features; OPERATIONS §3): never counted as passed")
    if command == "doctor":
        checks = report.get("checks") or {}
        lines.append("Checks: " + "; ".join(f"{k} {v.get('state') if isinstance(v, dict) else v}" for k, v in checks.items()))
    lines.append(f"Next: {next_action}" if next_action else "Next: nothing; the installation is ready")
    lines.append(f"Full report: recalith {command} --json · guide: {reasons.GUIDE}")
    return lines


def run(args: argparse.Namespace, form: Form, out: Output, environ: Mapping[str, str]) -> int:
    root = project_root(args)
    c = args.command
    actor = service.OBSERVER if c == "observe" else service.READER
    ctx = service.resolve(root, actor=actor)
    if c in ("status", "doctor"):
        return health_output(c, out, ctx, environ)
    if c == "observe":
        payload = read_stdin_json()
        items = payload.get("observations") if isinstance(payload, dict) and "observations" in payload else [payload]
        if not isinstance(items, list):
            raise RecalithError("invalid_schema", "observations is a list")
        receipt = service.observe(ctx, items)
        result = receipt.model_dump(mode="json")
        if receipt.status == "not_captured":
            code = receipt.error_code or "not_captured"
            exit_code = EXIT_CODES.get(code, 5)  # as RecalithError.exit_code; 7 for a durability failure even when the input was valid
            return out.failure(code, "the observation was not durably captured" if exit_code == 7 else "the observation was refused", exit_code, receipt=result)
        return out.success(result)
    if c == "context":
        payload = read_stdin_json()
        if not isinstance(payload, dict) or set(payload) - CONTEXT_FIELDS:
            raise RecalithError("invalid_schema", f"context stdin is an object with {sorted(CONTEXT_FIELDS)}")
        query = service.manual_query(ctx, payload.get("text", ""), purpose=args.purpose, session_id=args.session, task_id=args.task, **{k: v for k, v in payload.items() if k != "text"})
        packet = service.context(ctx, query)
        return out.success(packet.model_dump(mode="json"), degraded=packet.degraded_reasons)
    if c == "search":
        return out.success(service.search(ctx, args.query, history=args.history, limit=args.limit))
    if c == "show":
        return out.success(service.show(ctx, args.id, revision=args.revision))
    if c in service.LIST_KINDS:
        return out.success(service.list_records(ctx, c, status=args.status, limit=args.limit, after=args.after))
    if c == "jobs":
        return out.success(service.list_jobs(ctx, limit=args.limit))
    if c == "undo":
        return out.success(service.undo_preview(ctx, args.operation_id).model_dump(mode="json"))
    if c == "forget":
        return out.success(service.preview_forget(ctx, read_selector(args.selector)).model_dump(mode="json"))
    raise RecalithError("invalid_schema", "unknown command")
