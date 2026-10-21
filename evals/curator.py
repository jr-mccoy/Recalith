"""The recorded curator: a labeled stand-in for a certified inference route (decision 0020).

Under B1 no certified route exists, so a recorded evaluation run answers the
worker's real model requests with **recorded proposals**: operations written
for these fixtures by the repository's coding agent (who has read SYSTEM_SPEC
§7), resolved against the request the real preparers built (event IDs,
locators and digests are taken from that request, never invented). It sits
behind the worker's ``Backend`` interface, so everything else is the real
engine: the queue, leases, budgets (charged at the engine's own estimates,
since this backend reports no provider usage), persisted proposals,
deterministic admission, review batches, revalidation, projections and
delivery.

It is not a model and measures no extraction or review quality. Two plans:

* :class:`SmokePlan` — per smoke scenario, the claims a correct curator would
  propose (``SMOKE``), each with evidence matchers, plus the review verdicts,
  task narratives and revalidation decisions for them.
* :class:`RulePlan` — generic rules for the workload days: a failing command
  followed by a working variant becomes a failure lesson and a procedure; a
  prompt starting with ``Decision:`` or ``Remember`` becomes a user declaration.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

PROVIDER_ID = "recorded_curator"
MODEL = "recorded-proposals (not a model)"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _command(event: dict[str, Any]) -> str:
    payload = event.get("payload") or {}
    arguments = payload.get("arguments") or {}
    return arguments.get("command") or arguments.get("file_path") or " ".join((payload.get("action") or {}).get("argv") or [])


def _outcome(event: dict[str, Any]) -> str | None:
    return (event.get("payload") or {}).get("outcome")


def _result_text(event: dict[str, Any]) -> str:
    payload = event.get("payload") or {}
    return payload.get("result_text") or payload.get("error_signature") or ""


@dataclass
class Match:
    """An evidence matcher over the request's events."""

    kind: str  # user_message | tool_finished
    contains: str = ""
    outcome: str | None = None  # success | failure (tool_finished only)
    quote: str | None = None  # user_message: the exact quoted span (a locator on the user's own words)
    relation: str = "supports"
    session: str | None = None

    def find(self, events: list[dict[str, Any]], sessions: dict[str, str]) -> dict[str, Any] | None:
        for ev in reversed(events):
            if ev.get("kind") != self.kind:
                continue
            if self.session is not None and sessions.get(self.session) not in (None, ev.get("host_session_id")):
                continue
            payload = ev.get("payload") or {}
            if self.kind == "user_message":
                text = payload.get("text") or ""
                if self.contains in text and (self.quote is None or self.quote in text):
                    return ev
            else:
                hay = _command(ev)
                if self.contains in hay and (self.outcome is None or _outcome(ev) == self.outcome or (self.outcome == "failure" and _outcome(ev) not in ("success", None))):
                    return ev
        return None

    def link(self, ev: dict[str, Any]) -> dict[str, Any]:
        locator = None
        if self.kind == "user_message" and self.quote is not None:
            text = (ev.get("payload") or {}).get("text") or ""
            start = text.index(self.quote)
            end = start + len(self.quote)
            locator = {"field": "text", "start": start, "end": end, "text_digest": _sha(text[start:end])}
        return {"ref": {"kind": "event", "id": ev["event_id"], "revision": 1}, "relation": self.relation, "root_event_ids": [ev["event_id"]], "locator": locator, "mapping": None}


@dataclass
class Proposal:
    """One recorded claim proposal."""

    key: str
    kind: str
    proposition: str
    basis: str
    subject: str
    predicate: str
    evidence: list[Match]
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    failure: dict[str, Any] | None = None
    procedure_steps: list[str] | None = None
    supersedes: str | None = None  # a substring of a live claim this one replaces (same proposition key)
    retry_on_success: Match | None = None  # revalidation: a later success adds this retry condition
    dispute_on: Match | None = None  # revalidation: this evidence contradicts the claim

    def payload(self, links: list[dict[str, Any]]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "kind": self.kind, "proposition": self.proposition, "proposition_key": {"subject": self.subject, "predicate": self.predicate},
            "basis": self.basis, "dependencies": [{"fingerprint": None, "record": None, **d} for d in self.dependencies],
        }
        support = links[0]
        if self.kind == "failure_lesson":
            spec = dict(self.failure or {})
            body["failure"] = {
                "action_family_digest": None, "last_supporting_failure_event_id": None,
                "observed_failure": {"text": spec.get("observed", "The command failed."), "evidence": [support], "basis": "observed"},
                "alternative": {"text": spec["alternative"], "evidence": [links[-1]], "basis": "inferred"} if spec.get("alternative") else None,
                "retry_conditions": [{"text": t, "evidence": [support], "basis": "inferred"} for t in spec.get("retry", [])],
            }
        if self.kind == "procedure":
            body["procedure"] = {"steps": [{"text": s, "evidence": [links[-1]], "basis": "inferred"} for s in (self.procedure_steps or [self.proposition])]}
        return body


def op(local_ref: str, kind: str, payload: dict[str, Any], *, evidence: list[dict[str, Any]] | None = None, target: dict[str, Any] | None = None, depends_on: list[str] | None = None, reason: str = "recorded proposal") -> dict[str, Any]:
    return {"local_ref": local_ref, "kind": kind, "depends_on": depends_on or [], "target": target, "payload": payload, "evidence": evidence or [], "reason": reason}


# --------------------------------------------------------------------------
# Plans


class Plan:
    """What the recorded curator proposes for each request purpose."""

    def __init__(self) -> None:
        self.proposed: set[str] = set()
        self.sessions: dict[str, str] = {}  # scenario session name -> host session id (set by the harness)

    def proposals(self) -> list[Proposal]:
        return []

    def narrative(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    # extraction -----------------------------------------------------

    def extract(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        events = request.get("events") or []
        allowed = {r["id"] for r in request.get("allowed_evidence_refs") or [] if r["kind"] == "event"}
        events = [e for e in events if e["event_id"] in allowed]
        live = {c["claim_id"]: c for c in request.get("claims") or []}
        out = []
        for p in self.proposals():
            if p.key in self.proposed or any(c.get("proposition") == p.proposition for c in live.values()):
                continue
            found = [m.find(events, self.sessions) for m in p.evidence]
            if not all(found):
                continue
            links = [m.link(ev) for m, ev in zip(p.evidence, found, strict=True)]
            local = re.sub(r"[^a-z0-9_-]", "-", p.key.lower())[:60]
            out.append(op(local, "propose_claim", p.payload(links), evidence=links))
            if p.supersedes:
                old = next((c for c in live.values() if p.supersedes in (c.get("proposition") or "") and c.get("proposition") != p.proposition), None)
                if old is not None:
                    ref = {"kind": "claim", "id": old["claim_id"], "revision": old["revision"]}
                    out.append(op(local + "-sup", "change_claim_status", {"claim_ref": ref, "status": "superseded", "replacement_local_ref": local}, target=ref, depends_on=[local]))
            self.proposed.add(p.key)
        return out

    # review ---------------------------------------------------------

    def review(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        batch = request["review_batch"]
        claims = {c["claim_id"]: c for c in request.get("claims") or []}
        known = {p.proposition for p in self.proposals()}
        out = []
        for i, ref in enumerate(batch["candidate_refs"]):
            claim = claims.get(ref["id"]) or {}
            supports = [json.dumps(link, sort_keys=True) for link in claim.get("supports") or []]
            ids = [e["evidence_id"] for e in batch.get("evidence_index") or [] if json.dumps(e.get("link"), sort_keys=True) in supports][:2]
            supported = bool(ids) and (claim.get("proposition") in known or claim.get("basis") == "user_declared" and self.accepts_declaration(claim))
            payload = {"batch_id": batch["batch_id"], "candidate_ref": ref, "verdict": "supported" if supported else "reject", "objections": [] if supported else ["not supported as written by its cited evidence"], "evidence_ids": ids if supported else []}
            out.append({"local_ref": f"a{i}", "kind": "assess_claim", "depends_on": [], "target": ref, "payload": payload, "evidence": [], "reason": ""})
        return out

    def accepts_declaration(self, claim: dict[str, Any]) -> bool:
        return False

    # revalidation ---------------------------------------------------

    def revalidate(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        events = request.get("events") or []
        out = []
        for i, claim in enumerate(request.get("claims") or []):
            p = next((x for x in self.proposals() if x.proposition == claim.get("proposition")), None)
            if p is None:
                continue
            ref = {"kind": "claim", "id": claim["claim_id"], "revision": claim["revision"]}
            if p.retry_on_success is not None and (ev := p.retry_on_success.find(events, self.sessions)) is not None:
                link = p.retry_on_success.link(ev)
                text = (p.failure or {}).get("retry_after_change") or "A retry can succeed after the dependency changed."
                out.append(op(f"r{i}", "revise_claim", {"claim_ref": ref, "retry_conditions": [{"text": text, "evidence": [link], "basis": "inferred"}]}, target=ref, evidence=[link]))
            elif p.dispute_on is not None and (ev := p.dispute_on.find(events, self.sessions)) is not None:
                link = {**p.dispute_on.link(ev), "relation": "contradicts"}
                out.append(op(f"d{i}", "change_claim_status", {"claim_ref": ref, "status": "disputed"}, target=ref, evidence=[link]))
        return out


NOTES_DEP = [{"kind": "file", "key": "tools/check.py"}]


class SmokePlan(Plan):
    """Recorded proposals for one smoke scenario (``SMOKE``)."""

    def __init__(self, scenario_id: str) -> None:
        super().__init__()
        self.scenario_id = scenario_id

    def proposals(self) -> list[Proposal]:
        return SMOKE.get(self.scenario_id, [])

    def narrative(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        spec = NARRATIVE.get(self.scenario_id)
        task = request.get("task_state")
        if spec is None or task is None or request.get("purpose") != "update_task":
            return []
        match: Match = spec["evidence"]
        ev = match.find(request.get("events") or [], self.sessions)
        if ev is None or task.get("next_action"):
            return []
        link = match.link(ev)
        ref = {"kind": "task", "id": task["task_id"], "revision": task["revision"]}
        patch = {"op": "set", "field": "next_action", "value": {"text": spec["next_action"], "evidence": [link], "basis": "user_declared"}}
        return [op("narrative", "update_task", {"task_id": task["task_id"], "expected_revision": task["revision"], "patches": [patch]}, target=ref)]


SMOKE: dict[str, list[Proposal]] = {
    "smoke-L1-ledgerlite-test-command": [
        Proposal(
            "l1-procedure", "procedure", "Run the ledgerlite tests with `PYTHONPATH=src python -m unittest discover -s tests` from the project root.", "inferred",
            "ledgerlite tests", "run_command", [Match("tool_finished", "PYTHONPATH=src", "success")],
            procedure_steps=["From the project root run `PYTHONPATH=src python -m unittest discover -s tests`."],
        ),
        Proposal(
            "l1-failure", "failure_lesson", "Without PYTHONPATH=src the src-layout package is not importable from tests; plain discovery fails or runs nothing.", "inferred",
            "ledgerlite tests", "fails_without_pythonpath", [Match("tool_finished", "unittest", "failure"), Match("tool_finished", "PYTHONPATH=src", "success")],
            failure={"observed": "Plain `python -m unittest discover -s tests` failed with ModuleNotFoundError: No module named 'ledgerlite'.", "alternative": "Set PYTHONPATH=src.", "retry": ["Retry plain discovery if the tests add src to sys.path."]},
        ),
    ],
    "smoke-L2-fieldnotes-iso-dates": [
        Proposal(
            "l2-decision", "decision", "All dates printed by fieldnotes use ISO-8601; locale formats are not allowed.", "user_declared", "fieldnotes date format", "chosen",
            [Match("user_message", "ISO-8601", quote="every date fieldnotes prints must be ISO-8601")],
        ),
    ],
    "smoke-L3-household-grocery-budget": [
        Proposal(
            "l3-preference", "preference", "Grocery spending stays under $600 per month; plans that exceed it are flagged.", "user_declared", "grocery budget", "monthly_limit",
            [Match("user_message", "$600", quote="keep the grocery budget under $600 per month")],
        ),
    ],
    "smoke-L4-ledgerlite-resume-refactor": [],
    "smoke-R1-fieldnotes-check-env-fixed": [
        Proposal(
            "r1-failure", "failure_lesson", "tools/check.py fails with KeyError unless NOTES_HOME is set.", "inferred", "fieldnotes checks", "fails_without_notes_home",
            [Match("tool_finished", "tools/check.py", "failure"), Match("tool_finished", "NOTES_HOME=", "success")], dependencies=NOTES_DEP,
            failure={"observed": "`python tools/check.py` failed with KeyError: 'NOTES_HOME'.", "alternative": "Set NOTES_HOME to a scratch directory.", "retry": ["Retry without NOTES_HOME if tools/check.py changes."], "retry_after_change": "tools/check.py now defaults NOTES_HOME; a plain run succeeds."},
            retry_on_success=Match("tool_finished", "python tools/check.py", "success", session="C"),
        ),
    ],
    "smoke-R2-ledgerlite-import-fixed": [
        Proposal(
            "r2-failure", "failure_lesson", "Plain discovery fails to import ledgerlite without PYTHONPATH=src.", "inferred", "ledgerlite tests", "fails_without_pythonpath",
            [Match("tool_finished", "-t .", "failure"), Match("tool_finished", "PYTHONPATH=src", "success")], dependencies=[{"kind": "file", "key": "tests/__init__.py"}],
            failure={"observed": "`python -m unittest discover -s tests -t .` failed: the tests directory and ledgerlite are not importable without help.", "alternative": "Set PYTHONPATH=src.", "retry": ["Retry plain discovery if tests/__init__.py adds src to sys.path."], "retry_after_change": "tests/__init__.py now adds src to sys.path; plain discovery passes."},
            retry_on_success=Match("tool_finished", "-t .", "success", session="C"),
        ),
    ],
    "smoke-R3-household-budget-correction": [
        Proposal(
            "r3-old", "preference", "Grocery budget is $600 per month.", "user_declared", "grocery budget", "monthly_limit",
            [Match("user_message", "$600", quote="Keep the grocery budget under $600 per month")],
        ),
        Proposal(
            "r3-new", "preference", "Grocery budget is $700 per month.", "user_declared", "grocery budget", "monthly_limit",
            [Match("user_message", "$700", quote="the grocery budget is now $700 per month")], supersedes="$600",
        ),
    ],
    "smoke-R4-fieldnotes-storage-conflict": [
        Proposal(
            "r4-fact", "fact", "Notes are stored in notes.json under NOTES_HOME.", "user_declared", "fieldnotes storage", "location",
            [Match("user_message", "notes.json", quote="notes are stored in notes.json under NOTES_HOME")], dependencies=[{"kind": "file", "key": "fieldnotes/store.py"}],
            dispute_on=Match("tool_finished", "store.py", session="C"),
        ),
    ],
    # Controls: a correct curator proposes nothing durable.
    "smoke-C1-ledgerlite-routine-typo": [],
    "smoke-C2-fieldnotes-tdd-expected-red": [],
    "smoke-C3-household-utilities-speculation": [],
    "smoke-C4-cross-project-near-match": [],
}
# C4's session A runs in the separate ledgerlite installation: its curator is L1's (the conflicting second project).
SMOKE["smoke-C4-cross-project-near-match:ledgerlite"] = SMOKE["smoke-L1-ledgerlite-test-command"]

NARRATIVE: dict[str, dict[str, Any]] = {
    "smoke-L4-ledgerlite-resume-refactor": {
        "next_action": "Step 2 of the refactor: make Ledger.transfer use money.parse (then step 3 adds tests/test_money.py).",
        "evidence": Match("user_message", "three steps", quote="(2) make Ledger.transfer use money.parse"),
    },
}


class RulePlan(Plan):
    """Generic recorded rules for the workload days (volume and scheduling, not quality)."""

    def __init__(self) -> None:
        super().__init__()
        self._dynamic: list[Proposal] = []

    def proposals(self) -> list[Proposal]:
        return self._dynamic

    def extract(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        events = request.get("events") or []
        self._dynamic = []
        for i, ev in enumerate(events):
            if ev.get("kind") == "tool_finished" and _outcome(ev) not in ("success", None):
                failing = _command(ev)
                core = failing.split()[-1] if failing.split() else ""
                fix = next((e for e in events[i + 1:] if e.get("kind") == "tool_finished" and _outcome(e) == "success" and core and core in _command(e) and _command(e) != failing), None)
                if fix is None:
                    continue
                key = "rule-" + _sha(failing)[:16]
                self._dynamic.append(Proposal(
                    key, "failure_lesson", f"`{failing[:200]}` fails here; `{_command(fix)[:200]}` works.", "inferred", f"command {core[:60]}", "fails_without_fix",
                    [Match("tool_finished", failing, "failure"), Match("tool_finished", _command(fix), "success")],
                    failure={"observed": f"`{failing[:200]}` failed.", "alternative": f"Use `{_command(fix)[:200]}`.", "retry": ["Retry the plain command if its dependencies change."]},
                ))
            if ev.get("kind") == "user_message":
                text = (ev.get("payload") or {}).get("text") or ""
                m = re.match(r"(Decision|Remember)[^:]*:\s*(.{8,200}?)(?:\.|$)", text)
                if m:
                    quote = m.group(2)
                    key = "rule-" + _sha(quote)[:16]
                    self._dynamic.append(Proposal(key, "decision", quote.rstrip(".") + ".", "user_declared", quote[:60], "chosen", [Match("user_message", quote, quote=quote)]))
        return super().extract(request)


# --------------------------------------------------------------------------
# The backend


class RecordedCurator:
    """The worker ``Backend``: decodes the real request, answers with a recorded body, reports no provider usage."""

    provider_id = PROVIDER_ID
    configured_model = MODEL

    def __init__(self, plan: Plan, *, on_call: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.plan = plan
        self.calls: list[dict[str, Any]] = []
        self.on_call = on_call

    def launch(self, request: bytes, *, timeout_s: float, purpose: str):
        from recalith.controller.worker import LaunchOutcome

        began = time.monotonic()
        data = json.loads(request.decode("utf-8"))
        handlers = {"extract_claims": self.plan.extract, "review_claims": self.plan.review, "revalidate": self.plan.revalidate, "update_task": self.plan.narrative, "build_episode": self.plan.narrative}
        ops = handlers.get(purpose, lambda r: [])(data)
        body: dict[str, Any] = {"operations": ops}
        if not ops:
            body["no_op_reason"] = "recorded curator: nothing to propose"
        raw = json.dumps(body)
        record = {"purpose": purpose, "request_bytes": len(request), "operations": [o["kind"] for o in ops], "job_id": data.get("job_id")}
        self.calls.append(record)
        if self.on_call is not None:
            self.on_call(record)
        envelope = json.dumps({"type": "result", "result": raw, "usage": None}).encode("utf-8")
        return LaunchOutcome(stdout=envelope, overflowed=False, timed_out=False, returncode=0, duration_ms=int((time.monotonic() - began) * 1000), stderr=b"", tree_bound=True)

    def unwrap(self, stdout: bytes) -> tuple[bytes, dict[str, Any]]:
        data = json.loads(stdout.decode("utf-8"))
        if data.get("type") != "result" or not isinstance(data.get("result"), str):
            raise ValueError("recorded envelope malformed")
        return data["result"].encode("utf-8"), {}
