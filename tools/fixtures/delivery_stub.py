"""Nonce-only delivery stub hook for the Task 0b probe (not a product hook).

Invoked by the host as::

    python -I delivery_stub.py --plan PLAN_FILE --log LOG_FILE --path PATH

``PLAN_FILE`` (owned by the probe, outside the workspace) names the current
trial and, for a positive control, the one path that may inject and its nonce.
The stub emits a single bounded context item for that path and nothing in any
other case. It never writes the nonce anywhere except stdout to the host, never
blocks, and always exits 0 so a stub failure cannot deny a tool.

Stdlib only. Output follows the Claude Code ``hookSpecificOutput`` shape.
"""

from __future__ import annotations

import argparse
import json
import sys

MAX_INPUT = 64 * 1024
CONTEXT_TEMPLATE = "Recalith delivery canary: {nonce}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--path", required=True)
    try:
        ns = parser.parse_args(argv)
    except SystemExit:
        return 0
    try:
        raw = sys.stdin.read(MAX_INPUT)
        event = json.loads(raw) if raw.strip() else {}
    except (OSError, ValueError):
        event = {}
    if not isinstance(event, dict):
        event = {}
    try:
        with open(ns.plan, encoding="utf-8") as fh:
            plan = json.load(fh)
    except (OSError, ValueError):
        plan = {}
    hook_event = event.get("hook_event_name")
    emit = bool(plan.get("inject_path") == ns.path and isinstance(plan.get("nonce"), str) and plan["nonce"])
    record = {
        "trial_id": plan.get("trial_id"),
        "path": ns.path,
        "event": hook_event if isinstance(hook_event, str) else None,
        "source": event.get("source") if isinstance(event.get("source"), str) else None,
        "tool_name": event.get("tool_name") if isinstance(event.get("tool_name"), str) else None,
        "emitted": emit,
    }
    try:
        with open(ns.log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass
    if emit:
        reply = {"hookSpecificOutput": {"hookEventName": hook_event or "", "additionalContext": CONTEXT_TEMPLATE.format(nonce=plan["nonce"])}}
        sys.stdout.write(json.dumps(reply))
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
