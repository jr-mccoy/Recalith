"""Task state helpers and the typed fact fold (SYSTEM_SPEC §3.2; DATA_CONTRACTS §3).

**Typed facts only.** :func:`fold_event` sets exactly what an event
supports, each item citing its supporting event: the user's first request as
the objective (``user_declared``, an exact quoted span); a started tool call
as a pending action awaiting its result; a finished call as a known result
(the pending action closes by its ID); a failing test/build as a blocker
that closes only when the same test/build later passes. An assistant's
intention is never a result, a pending call is never a success, and nothing
here sets ``next_action``, constraints, plan or completion: those are model
narrative patches through ``update_task`` (and completion needs completion
evidence). Fields may stay unknown. No field is cleared because a chunk did
not mention it; items close only by explicit ID.

**Item IDs.** Pending actions carry a code-assigned ``action_id``. Every
other list item (a ``SupportedText``) is identified by the digest of its
normalized content (``item_`` + SHA-256), so a patch can close it by ID and a
moved item keeps its ID in both tasks.

**Patch semantics** (:func:`patch_fields`) are shared by ``update_task``,
``bind_events`` and the in-memory reducer draft, so the reducer's view of a
task is computed with exactly the rules the application transaction applies.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from recalith.contracts.common import RecordRef, derived_id, digest_of, format_utc, parse_utc
from recalith.contracts.memory import SupportedText, TaskState
from recalith.storage import records

DEFAULT_TITLE = "Untitled task"
OBJECTIVE_MAX_CHARS = 1024
TITLE_MAX_CHARS = 80
LABEL_MAX_CHARS = 160
KNOWN_RESULTS_CAP = 24
BLOCKERS_CAP = 32
PENDING_CAP = 64
TEST_BUILD_KINDS = frozenset({"test", "build"})
ACTIVITY_KINDS = frozenset({"user_message", "assistant_message", "tool_started", "tool_finished", "artifact_changed"})
TASK_LIST_FIELDS = frozenset({"constraints", "plan", "pending_actions", "known_results", "blockers", "open_questions"})
# Event kinds that are never assigned to a task: delivery telemetry, refused
# operator attempts and operator administration are not task work.
UNBOUND_KINDS = frozenset({"memory_delivered", "agent_attempted_operator_command", "operator_declaration", "operator_correction", "operator_forget"})
MAX_REDIRECT_HOPS = 8


# --------------------------------------------------------------------------
# Events as the reducer sees them


@dataclass(frozen=True)
class Ev:
    event_id: str
    seq: int
    kind: str
    session_id: str
    adapter_id: str
    channel: str
    authority: str
    time: str
    task_hint: str | None
    payload: dict[str, Any]
    coverage: dict[str, Any]

    @property
    def tool_call_id(self) -> str | None:
        value = self.payload.get("tool_call_id") if self.kind in ("tool_started", "tool_finished") else None
        return value if isinstance(value, str) and value else None

    @property
    def action(self) -> dict[str, Any]:
        value = self.payload.get("action")
        return value if isinstance(value, dict) else {}

    @property
    def is_activity(self) -> bool:
        return self.kind in ACTIVITY_KINDS

    @property
    def is_user_request(self) -> bool:
        return self.kind == "user_message" and self.channel == "user" and self.authority == "explicit_user" and isinstance(self.payload.get("text"), str) and bool(self.payload["text"].strip())


EVENT_COLUMNS = "event_id, commit_sequence, envelope, payload"


def ev_from_row(row: Sequence[Any]) -> Ev:
    event_id, seq, envelope, payload = row
    env = json.loads(envelope)
    data = json.loads(payload) if payload is not None else {}
    return Ev(
        event_id=event_id, seq=seq, kind=env["kind"], session_id=env["session_id"], adapter_id=env["adapter_id"], channel=env["channel"], authority=env["authority"],
        time=env.get("occurred_at") or env["recorded_at"], task_hint=env.get("task_id"), payload=data, coverage=env.get("coverage") or {},
    )


def ev_from_envelope(envelope: Any, seq: int = 0) -> Ev:
    env = envelope.model_dump(mode="json") if hasattr(envelope, "model_dump") else dict(envelope)
    return Ev(
        event_id=env["event_id"], seq=seq, kind=env["kind"], session_id=env["session_id"], adapter_id=env["adapter_id"], channel=env["channel"], authority=env["authority"],
        time=env.get("occurred_at") or env["recorded_at"], task_hint=env.get("task_id"), payload=env.get("payload") or {}, coverage=env.get("coverage") or {},
    )


def load_events(q: Any, event_ids: Iterable[str]) -> list[Ev]:
    out = []
    for event_id in event_ids:
        row = q.execute(f"SELECT {EVENT_COLUMNS} FROM events WHERE event_id = ?", (event_id,)).fetchone()  # noqa: S608 - fixed columns
        if row is not None:
            out.append(ev_from_row(row))
    return sorted(out, key=lambda e: e.seq)


# --------------------------------------------------------------------------
# Evidence, labels and signatures


def event_link(ev: Ev, *, relation: str = "supports", field: str | None = None, length: int | None = None) -> dict[str, Any]:
    """A link to the event's own root, optionally quoting ``field[0:length]`` exactly."""
    locator = None
    if field is not None:
        text = ev.payload.get(field)
        if isinstance(text, str) and text:
            end = min(len(text), length or len(text))
            locator = {"field": field, "start": 0, "end": end, "text_digest": digest_of_text(text[:end])}
    return {"ref": {"kind": "event", "id": ev.event_id, "revision": 1}, "relation": relation, "root_event_ids": [ev.event_id], "locator": locator, "mapping": None}


def digest_of_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def supported(text: str, links: Sequence[dict[str, Any]], basis: str) -> dict[str, Any]:
    """A normalized SupportedText dict (normalized so its item ID is stable)."""
    return SupportedText.model_validate({"text": text[:8192] or "-", "evidence": list(links), "basis": basis}).model_dump(mode="json")


def action_label(ev: Ev) -> str:
    action = ev.action
    tool = action.get("tool") or ev.payload.get("tool_name") or "tool"
    argv = action.get("argv")
    if isinstance(argv, list) and argv:
        detail = " ".join(str(a) for a in argv)
        text = f"{tool} `{detail}`"
    elif action.get("paths"):
        text = f"{tool} {', '.join(action['paths'])}"
    else:
        text = f"{tool} (unparsed command)" if action.get("parse_status") in (None, "unknown") and tool == "Bash" else str(tool)
    return text if len(text) <= LABEL_MAX_CHARS else text[: LABEL_MAX_CHARS - 1] + "…"


def action_signature(ev: Ev) -> str:
    """Same tool, working directory, argument array and paths: the same action (raw digest when unparsed)."""
    action = ev.action
    argv = action.get("argv")
    return digest_of([action.get("tool") or ev.payload.get("tool_name"), action.get("cwd_path"), argv, action.get("paths") or [], None if argv else action.get("raw_digest")])


def action_kind(ev: Ev) -> str | None:
    return ev.action.get("action_kind")


def assertion_summary(payload: dict[str, Any]) -> str | None:
    verdicts = [a.get("passed") for a in payload.get("assertions") or [] if a.get("kind") == "test_result" and a.get("passed") is not None]
    if not verdicts:
        return None
    passed = sum(1 for v in verdicts if v)
    return f"{passed}/{len(verdicts)} test assertions passed"


def result_summary(ev: Ev) -> str:
    """Outcome, exit code, certified assertions and error signature: never a bare 'ok'."""
    payload = ev.payload
    parts = [f"{action_label(ev)}: {payload.get('outcome') or 'unknown'}"]
    if payload.get("exit_code") is not None:
        parts.append(f"exit {payload['exit_code']}")
    summary = assertion_summary(payload)
    if summary:
        parts.append(summary)
    if ev.coverage.get("truncated"):
        parts.append("output truncated")
    text = "; ".join(parts)
    signature = payload.get("error_signature")
    if isinstance(signature, str) and signature:
        text += f" — {signature[:300]}"
    return text


def result_link(ev: Ev) -> dict[str, Any]:
    """The finish event, quoting its certified error signature when one exists."""
    if isinstance(ev.payload.get("error_signature"), str) and ev.payload["error_signature"]:
        return event_link(ev, field="error_signature")
    return event_link(ev)


# --------------------------------------------------------------------------
# Item identity and patch semantics


def item_id(field_name: str, item: dict[str, Any]) -> str:
    if field_name == "pending_actions":
        return item["action_id"]
    return derived_id("item", item)


def patch_fields(
    data: dict[str, Any],
    patches: Sequence[Any],
    *,
    list_fields: frozenset[str],
    op_id: str,
    ids: dict[str, str] | None = None,
    keep_ids: bool = False,
) -> None:
    """Apply explicit patches in place: set a field, append an item, close an item by ID, or change status.

    ``ids`` names the list fields whose items carry an explicit ID key; code
    assigns those IDs (``act_`` + operation ID + patch index) unless
    ``keep_ids`` (the controller reducer supplies deterministic IDs). Other
    list items close by their content ID (:func:`item_id`).
    """
    ids = ids or {}
    for index, patch in enumerate(patches):
        if patch.op == "status":
            data["status"] = patch.status
            continue
        name = patch.field
        if patch.op == "set":
            if name in list_fields:
                raise ValueError("list fields change by append/close, not set")
            data[name] = patch.value
        elif patch.op == "append":
            if name not in list_fields:
                raise ValueError("append applies to list fields")
            value = patch.value
            if name in ids:
                assert isinstance(value, dict)
                if not (keep_ids and isinstance(value.get(ids[name]), str)):
                    value = {**value, ids[name]: derived_id("act", [op_id, index])}
                if any(existing.get(ids[name]) == value[ids[name]] for existing in data.get(name, [])):
                    raise ValueError("list item ids are unique")
            data[name] = [*data.get(name, []), value]
        elif patch.op == "close":
            if name not in list_fields:
                raise ValueError("only list items can be closed")
            key = ids.get(name)
            current = data.get(name, [])
            kept = [item for item in current if (item.get(key) if key else derived_id("item", item)) != patch.item_id]
            if len(kept) == len(current):
                raise ValueError("no list item has that id")
            data[name] = kept


# --------------------------------------------------------------------------
# The typed fact fold


class Draft:
    """A task body plus the typed patches that produced it from the stored head.

    The draft applies each patch with :func:`patch_fields` as it is recorded,
    so later events see earlier ones (a result closes the pending action its
    start opened in the same pass).
    """

    def __init__(self, data: dict[str, Any], *, signature_of: Callable[[str], str | None]) -> None:
        self.data = json.loads(json.dumps(data))
        self.patches: list[dict[str, Any]] = []
        self._signature_of = signature_of
        self._known_sigs: dict[str, str] = {}

    def _apply(self, patch: dict[str, Any]) -> None:
        from recalith.contracts.operations import TaskPatch

        typed = TaskPatch.model_validate(patch)
        patch_fields(self.data, [typed], list_fields=TASK_LIST_FIELDS, op_id="", ids={"pending_actions": "action_id"}, keep_ids=True)
        self.patches.append(typed.model_dump(mode="json", exclude_none=True))

    def set(self, name: str, value: Any) -> None:
        self._apply({"op": "set", "field": name, "value": value})

    def append(self, name: str, value: dict[str, Any], *, signature: str | None = None) -> None:
        self._apply({"op": "append", "field": name, "value": value})
        if signature is not None and name != "pending_actions":
            self._known_sigs[item_id(name, value)] = signature

    def close(self, name: str, identifier: str) -> None:
        self._apply({"op": "close", "field": name, "item_id": identifier})

    def items(self, name: str) -> list[dict[str, Any]]:
        return list(self.data.get(name) or [])

    def owned_signature(self, name: str, item: dict[str, Any]) -> str | None:
        """The action signature of a reducer-owned result/blocker item, else None."""
        identifier = item_id(name, item)
        if identifier in self._known_sigs:
            return self._known_sigs[identifier]
        evidence = item.get("evidence") or []
        if item.get("basis") != "observed" or len(evidence) != 1 or evidence[0]["ref"]["kind"] != "event":
            return None
        return self._signature_of(evidence[0]["ref"]["id"])


def fold_event(draft: Draft, ev: Ev) -> None:
    """Record the typed facts one event supports (see module docstring)."""
    if ev.is_user_request:
        if draft.data.get("objective") is None:
            text = ev.payload["text"]
            n = min(len(text), OBJECTIVE_MAX_CHARS)
            draft.set("objective", supported(text[:n], [event_link(ev, field="text", length=n)], "user_declared"))
            if draft.data.get("title") == DEFAULT_TITLE:
                draft.set("title", title_from(text))
        return
    call = ev.tool_call_id
    if ev.kind == "tool_started" and call:
        if any(p.get("tool_call_id") == call for p in draft.items("pending_actions")):
            return
        if len(draft.items("pending_actions")) >= PENDING_CAP:
            return  # bounded; the call stays visible in its episode and binding
        draft.append("pending_actions", {"action_id": pending_action_id(ev.adapter_id, call), "description": supported(action_label(ev), [event_link(ev)], "observed"), "tool_call_id": call[:256], "state": "awaiting_result"})
        return
    if ev.kind != "tool_finished":
        return
    if call:
        for pending in draft.items("pending_actions"):
            if pending.get("tool_call_id") == call:
                draft.close("pending_actions", pending["action_id"])
    signature = action_signature(ev)
    for item in draft.items("known_results"):
        if draft.owned_signature("known_results", item) == signature:
            draft.close("known_results", item_id("known_results", item))
    result = supported(result_summary(ev), [result_link(ev)], "observed")
    if item_id("known_results", result) not in {item_id("known_results", i) for i in draft.items("known_results")}:
        draft.append("known_results", result, signature=signature)
    owned = [i for i in draft.items("known_results") if draft.owned_signature("known_results", i) is not None]
    while len(draft.items("known_results")) > KNOWN_RESULTS_CAP and owned:
        draft.close("known_results", item_id("known_results", owned.pop(0)))
    if action_kind(ev) not in TEST_BUILD_KINDS:
        return
    outcome = ev.payload.get("outcome")
    open_blockers = [i for i in draft.items("blockers") if draft.owned_signature("blockers", i) == signature]
    if outcome == "success":
        for item in open_blockers:
            draft.close("blockers", item_id("blockers", item))
    elif outcome == "failure" and not open_blockers and len(draft.items("blockers")) < BLOCKERS_CAP:
        draft.append("blockers", supported(f"{action_label(ev)} fails" + (f" (exit {ev.payload['exit_code']})" if ev.payload.get("exit_code") is not None else ""), [result_link(ev)], "observed"), signature=signature)


def pending_action_id(adapter_id: str, tool_call_id: str) -> str:
    return derived_id("act", [adapter_id, tool_call_id])


def title_from(text: str, prefixes: Sequence[str] = ()) -> str:
    line = text.strip().splitlines()[0] if text.strip() else DEFAULT_TITLE
    low = line.casefold()
    for prefix in prefixes:
        if low.startswith(prefix.casefold()):
            line = line[len(prefix) :].strip() or line
            break
    return line if len(line) <= TITLE_MAX_CHARS else line[: TITLE_MAX_CHARS - 1] + "…"


# --------------------------------------------------------------------------
# Task records


def new_task(ctx: Any, *, task_id: str, title: str, session_ids: Sequence[str], started_at: str) -> TaskState:
    return TaskState(
        task_id=task_id, project_id=ctx.project_id, installation_id=ctx.installation_id, revision=1, status="active", title=title,
        objective=None, session_ids=list(dict.fromkeys(session_ids)), updated_at=started_at, last_activity_at=started_at,
    )


def head_state(q: Any, task_id: str) -> tuple[int, str, dict[str, Any]] | None:
    """(revision, status, body) of a task head."""
    current = records.head(q, "task", task_id)
    if current is None:
        return None
    body = records.body(q, "task", task_id, current[0])
    return None if body is None else (current[0], current[1], body)


def resolve_task(q: Any, task_id: str | None) -> str | None:
    """Follow linked placeholders to the nonredirected task (never a cycle)."""
    hops = 0
    while task_id is not None and hops <= MAX_REDIRECT_HOPS:
        row = q.execute("SELECT status, redirect_task_id FROM task_heads WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        if row[0] != "linked":
            return task_id
        task_id, hops = row[1], hops + 1
    return None


def task_counts(q: Any, workspace_id: str) -> dict[str, int]:
    """Nonredirected heads and linked placeholders, counted separately (DATA_CONTRACTS §3.1)."""
    counts = {status: 0 for status in ("active", "paused", "completed", "abandoned", "linked")}
    for status, n in q.execute("SELECT status, COUNT(*) FROM task_heads WHERE workspace_id = ? GROUP BY status", (workspace_id,)).fetchall():
        counts[status] = n
    return {"active": counts["active"], "paused": counts["paused"], "completed": counts["completed"], "abandoned": counts["abandoned"], "placeholders": counts["linked"], "nonredirected": sum(v for k, v in counts.items() if k != "linked")}


def continuity_candidates(q: Any, workspace_id: str, *, exclude: Iterable[str], now: str, pause_hours: int) -> list[str]:
    """Nonredirected tasks that are active, or were paused within ``pause_hours`` (SYSTEM_SPEC §3.2)."""
    excluded = set(exclude)
    since = format_utc(parse_utc(now) - _dt.timedelta(hours=pause_hours))
    out = []
    for task_id, revision, status in q.execute("SELECT task_id, revision, status FROM task_heads WHERE workspace_id = ? AND status IN ('active', 'paused') ORDER BY task_id", (workspace_id,)).fetchall():
        if task_id in excluded:
            continue
        if status == "paused":
            body = records.body(q, "task", task_id, revision) or {}
            if (body.get("updated_at") or "") < since:
                continue
        out.append(task_id)
    return out


def completion_supported(data: dict[str, Any]) -> bool:
    """Completion needs completion evidence: a completion basis citing at least one record."""
    basis = data.get("completion_basis")
    return isinstance(basis, dict) and bool(basis.get("evidence"))


def task_ref(task_id: str, revision: int) -> RecordRef:
    return RecordRef(kind="task", id=task_id, revision=revision)


__all__ = [
    "Draft", "Ev", "fold_event", "patch_fields", "item_id", "action_label", "action_signature", "result_summary", "supported", "event_link",
    "new_task", "head_state", "resolve_task", "task_counts", "continuity_candidates", "completion_supported",
]
