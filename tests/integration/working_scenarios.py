"""Test-only builders for Task 6: real captured hook payloads, variants and recorded proposals.

Every event enters through the real Claude Code 2.1.301 adapter mapping and
normalization (``claude_capture.map_hook`` → ``entry.normalize_request`` →
``entry.handle_hook``) and is ingested and reduced by a real worker. Where no
real payload exists, a test uses a **synthetic variant** of a real record and
says so: a second host session (another session ID and tool-use IDs) for
parallel or resumed work, a changed prompt text (a pivot, a completion
statement), a changed file path (src/tests/docs or ``web/`` clusters), a
changed command, or a controlled ``recorded_at`` for a 30-minute or 24-hour
gap. The payload shape, mapping and normalization stay the real ones.

Model narrative and binding decisions are *recorded proposals*: they exercise
the application mechanics (Task 5 path), not live segmentation quality.
"""

from __future__ import annotations

import copy
import hashlib
import datetime as _dt
import json
import time
from pathlib import Path
from typing import Any

import operation_scenarios as osc  # first: puts tests/ and tests/platform on sys.path
import worker_scenarios as ws  # noqa: E402
import claude_fixtures as cf  # noqa: E402
from recalith.contracts.common import RecordRef, format_utc, parse_utc, utc_now  # noqa: E402
from recalith.controller import apply, worker  # noqa: E402
from recalith.fast import claude_capture, entry  # noqa: E402
from recalith.storage import db, records  # noqa: E402
from recalith.working import bindings  # noqa: E402

LIFECYCLE_SESSION = "d872a981-1398-4972-82f0-c635e3c8bacf"


def later(hours: float = 0, minutes: float = 0, base: str | None = None) -> str:
    return format_utc(parse_utc(base or utc_now()) + _dt.timedelta(hours=hours, minutes=minutes))


def record(scenario: str, event: str, tool_use_id: str | None = None, n: int = 0) -> dict[str, Any]:
    """The n-th real hook record of ``event`` (optionally for one tool call)."""
    found = [r for r in cf.records(scenario) if r["event"] == event and (tool_use_id is None or r["payload"].get("tool_use_id") == tool_use_id)]
    return copy.deepcopy(found[n])


def variant(rec: dict[str, Any], *, session: str | None = None, tool_suffix: str | None = None, prompt: str | None = None, replace: dict[str, str] | None = None, command: str | None = None, interrupt: bool | None = None) -> dict[str, Any]:
    """A synthetic variant of a real record (see the module docstring)."""
    text = json.dumps(rec, ensure_ascii=False)
    for old, new in (replace or {}).items():
        text = text.replace(old, new)
    if session is not None:
        text = text.replace(rec["payload"]["session_id"], session)
    out = json.loads(text)
    payload = out["payload"]
    if tool_suffix is not None and payload.get("tool_use_id"):
        payload["tool_use_id"] = f"{payload['tool_use_id']}_{tool_suffix}"
    if prompt is not None:
        payload["prompt"] = prompt
        # The host keys a prompt by prompt_id and transcript position; a new prompt needs its own identity.
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        payload["prompt_id"] = f"{digest[:8]}-{digest[8:12]}-4{digest[13:16]}-8{digest[17:20]}-{digest[20:32]}"
    if command is not None:
        payload["tool_input"]["command"] = command
    if interrupt is not None:
        payload["is_interrupt"] = interrupt
    return out


def session_id(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


class Project:
    """A Recalith installation fed by real (or variant) hook records."""

    def __init__(self, tmp: Path, name: str = "work") -> None:
        self.replay = cf.Replay(tmp / name)
        self.root = self.replay.root
        self.ctx = osc.context(self.root)

    # ------------------------------------------------------------ capture

    def send(self, rec: dict[str, Any], *, at: str | None = None) -> dict[str, Any]:
        data = self.replay.prepare(rec)
        payload = json.loads(data.decode("utf-8"))
        hook_ctx = entry.load_context(str(self.root), "claude_code")
        request = claude_capture.map_hook(hook_ctx, payload, registered_event=rec["event"], recorded_at=at)
        reply = entry.handle_hook(hook_ctx, entry.normalize_request(hook_ctx, request), deadline=time.monotonic() + 5, inherited={})
        assert reply["receipt"] is None or reply["receipt"]["status"] == "accepted", reply
        return reply

    def send_all(self, recs, *, at: str | None = None) -> None:
        for rec in recs:
            self.send(rec, at=at)

    def scenario(self, name: str) -> None:
        self.send_all(cf.records(name))

    # ------------------------------------------------------------ worker

    def drain(self, *, clock: worker.Clock | None = None, model=None, polls: int = 40) -> worker.Worker:
        """Real worker polls until a poll finds nothing; typed reduction runs in its ingest jobs."""
        w = worker.Worker(osc.context(self.root), clock=clock, model=model)
        try:
            for _ in range(polls):
                if not w.poll_once():
                    break
            assert w.last_error is None, w.last_error
        finally:
            w.close()
        return w

    # ------------------------------------------------------------ queries

    def view(self):
        store = db.open_store(self.ctx, readonly=True)
        return _View(store)

    def events(self, kind: str | None = None, session: str | None = None) -> list[dict[str, Any]]:
        with self.view() as v:
            rows = v.execute("SELECT event_id, kind, session_id, payload, commit_sequence FROM events ORDER BY commit_sequence").fetchall()
        out = [{"id": r[0], "kind": r[1], "session_id": r[2], "payload": json.loads(r[3]), "seq": r[4]} for r in rows]
        return [e for e in out if (kind is None or e["kind"] == kind) and (session is None or e["session_id"] == session)]

    def event(self, kind: str, *, call: str | None = None, text: str | None = None, n: int = 0) -> dict[str, Any]:
        found = [e for e in self.events(kind) if (call is None or e["payload"].get("tool_call_id") == call) and (text is None or text in (e["payload"].get("text") or ""))]
        return found[n]

    def binding(self, event_id: str) -> dict[str, Any] | None:
        with self.view() as v:
            return bindings.binding_head(v, event_id)

    def task_of(self, event_id: str) -> str:
        head = self.binding(event_id)
        assert head is not None, "event is not bound"
        return head["task_id"]

    def task(self, task_id: str) -> dict[str, Any]:
        with self.view() as v:
            revision, status = records.head(v, "task", task_id)
            return {**records.body(v, "task", task_id, revision), "head_status": status}

    def tasks(self) -> list[dict[str, Any]]:
        with self.view() as v:
            ids = [r[0] for r in v.execute("SELECT task_id FROM task_heads ORDER BY task_id").fetchall()]
        return [self.task(t) for t in ids]

    def boundaries(self, reason: str | None = None) -> list[dict[str, Any]]:
        with self.view() as v:
            rows = [json.loads(r[0]) for r in v.execute("SELECT body FROM task_boundaries ORDER BY rowid").fetchall()]
        return [b for b in rows if reason is None or b["reason"] == reason]

    def episodes(self, task_id: str | None = None) -> list[dict[str, Any]]:
        with self.view() as v:
            rows = v.execute("SELECT h.episode_id, h.revision, h.state FROM episode_heads h ORDER BY h.episode_id").fetchall()
            out = [{**records.body(v, "episode", e, r), "head_state": s} for e, r, s in rows]
        out.sort(key=lambda e: e["started_at"])
        return [e for e in out if task_id is None or e["task_id"] == task_id]

    def count(self, sql: str, params: tuple = ()) -> int:
        with self.view() as v:
            return v.execute(sql, params).fetchone()[0]

    def session_events(self, task_id: str, session: str) -> list[str]:
        with self.view() as v:
            return [e for e, _s in bindings.task_session_events(v, task_id, session)]

    def expected(self, event_ids) -> dict[str, int]:
        with self.view() as v:
            return bindings.expected_revisions(v, list(event_ids))

    def sid(self, host_session_id: str) -> str:
        """The Recalith session ID of a host session in this installation."""
        return claude_capture.session_id_for(self.ctx.installation_id, host_session_id)

    def session_of(self, kind: str = "session_started", n: int = 0) -> str:
        return self.events(kind)[n]["session_id"]

    # ------------------------------------------------------------ recorded model proposals

    def propose(self, kind: str, ops: list[dict[str, Any]], *, purpose: str | None = None, input_refs: list[RecordRef] | None = None):
        """A recorded model proposal through the worker's real path: lease, persist under the fence, apply."""
        job = osc.leased(self.root, kind, input_refs=input_refs or [RecordRef(kind="task", id=self.tasks()[0]["task_id"], revision=1)], now=utc_now())
        response = osc.response(ops, purpose=purpose or kind)
        with db.open_store(osc.context(self.root)) as store:
            apply.persist_proposal(store, job, response, osc.read_set(self.root), now=utc_now())
            return apply.apply_proposal(osc.context(self.root), job, response, store=store, now=utc_now())

    def binding_op(self, local_ref: str, decision: str, boundary_id: str, event_ids: list[str], *, target: str | None = None, evidence_event: str | None = None) -> dict[str, Any]:
        ev = evidence_event or event_ids[0]
        link = {"ref": {"kind": "event", "id": ev, "revision": 1}, "relation": "supports", "root_event_ids": [ev], "locator": None, "mapping": None}
        payload = {"boundary_id": boundary_id, "decision": decision, "event_ids": event_ids, "target_task_id": target, "expected_binding_revisions": self.expected(event_ids), "evidence": [link]}
        return osc.op(local_ref, "resolve_task_binding", payload)


class _View:
    def __init__(self, store) -> None:
        self.store = store
        self._cm = store.read()

    def __enter__(self):
        return self._cm.__enter__()

    def __exit__(self, *exc) -> None:
        self._cm.__exit__(*exc)
        self.store.close()


def supported(ev: dict[str, Any], text: str, basis: str = "inferred") -> dict[str, Any]:
    return {"text": text, "evidence": [{"ref": {"kind": "event", "id": ev["id"], "revision": 1}, "relation": "supports", "root_event_ids": [ev["id"]], "locator": None, "mapping": None}], "basis": basis}


def fake_clock_at(moment: str) -> ws.FakeClock:
    return ws.FakeClock(moment)


# --------------------------------------------------------------------------
# The kill/restart scenario for typed reduction and binding application


def crash_project(tmp: Path, name: str) -> Path:
    """Captured but not yet ingested: typed reduction runs inside the driver's ingest jobs.

    Session A is the real lifecycle session with a pivot (variant prompt) and
    one more call inserted before its stop/compaction/end; session B is a
    second host session (variant) whose first three path actions lie in A's
    clusters, so reduction links it deterministically. One ``update_task``
    model job then splits A's range at the pivot (``split_body``).
    """
    from recalith.controller import jobs

    p = Project(tmp, name)
    lifecycle = cf.records("lifecycle")
    stop = next(i for i, r in enumerate(lifecycle) if r["event"] == "Stop")
    p.send_all(lifecycle[:stop])
    p.send(variant(record("lifecycle", "UserPromptSubmit"), prompt="new task: tidy the fixture notes"))
    p.send(variant(record("lifecycle", "PreToolUse", "toolu_probe_0001"), tool_suffix="p"))
    p.send(variant(record("lifecycle", "PostToolUse", "toolu_probe_0001"), tool_suffix="p"))
    p.send_all(lifecycle[stop:])
    b = session_id(2)
    p.send(variant(record("lifecycle", "SessionStart"), session=b))
    p.send(variant(record("lifecycle", "UserPromptSubmit"), session=b, prompt="Continue with the fixture notes."))
    for call in ("toolu_probe_0007", "toolu_probe_0009", "toolu_probe_0010"):
        p.send(variant(record("lifecycle", "PreToolUse", call), session=b, tool_suffix="b"))
        p.send(variant(record("lifecycle", "PostToolUse", call), session=b, tool_suffix="b"))
    with db.open_store(osc.context(p.root)) as store, store.transaction() as txn:
        jobs.enqueue(txn, kind="update_task", input_refs=[], now=ws.START, prompt_version="test@1")
    (p.root / osc.SCENARIO).write_text(json.dumps({"bodies": {}, "split_pivot": True}), encoding="utf-8")
    return p.root


def dynamic(root: Path) -> bool:
    path = root / osc.SCENARIO
    return path.exists() and bool(json.loads(path.read_text(encoding="utf-8")).get("split_pivot"))


def split_body(root: Path) -> bytes:
    """The recorded decision: split session A's range at its pending pivot candidate."""
    ctx = osc.context(root)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        row = view.execute("SELECT body FROM task_boundaries WHERE reason = 'pivot_prefix' AND state = 'pending'").fetchone()
        if row is None:
            return osc.body([], "no pending pivot").decode().encode("utf-8")
        candidate = json.loads(row[0])
        from recalith.working import tasks as wt

        source = wt.resolve_task(view, candidate["source_task_id"])
        order = [e for e, _s in bindings.task_session_events(view, source, candidate["session_id"])]
        start = order.index(candidate["proposed_event_ids"][0])
        event_ids = order[start:]
        expected = bindings.expected_revisions(view, event_ids)
    link = {"ref": {"kind": "event", "id": event_ids[0], "revision": 1}, "relation": "supports", "root_event_ids": [event_ids[0]], "locator": None, "mapping": None}
    payload = {"boundary_id": candidate["boundary_id"], "decision": "confirm_split", "event_ids": event_ids, "target_task_id": None, "expected_binding_revisions": expected, "evidence": [link]}
    return osc.body([osc.op("split", "resolve_task_binding", payload)])
