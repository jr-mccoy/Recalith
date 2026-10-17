"""Test-only builders for Task 8: lineage over real captured payloads and named synthetic variants.

Real inputs: every Claude event enters through the real 2.1.301 adapter
mapping, normalization, capture and ingestion (``working_scenarios.Project``),
so root registration runs exactly as in production. Real payloads used: the
lifecycle session (prompts; the failing ``pytest -q test_mid.py``; the passing
``pytest -q -s test_pass.py``; ``Read notes.txt``; ``echo``; the ``printf |
tr`` pipeline), the subagent session (``Agent`` forwarding result, the
subagent's own ``echo``, the host ``<task-notification>`` prompt).

**Synthetic variants** (named at each use; the payload shape, mapping and
normalization stay real): a rerun of a real call under a new tool-use ID
(``tool_suffix``) or a smaller one (``rename_call``), a rerun whose outcome is
replaced by the real passing result (contradictory rerun), a changed command,
a ``Read`` of another path or of changed content, a real tool call placed
inside a subagent (``in_subagent``: the host's ``agent_id``/``agent_type``
fields), a changed prompt text, and a second host session.

**Synthetic experiment domain**: no host adapter certifies complete
dependency coverage (DATA_CONTRACTS §6.1), so the "genuinely new experiment"
and "missing dependency" cases use :data:`SYNTHETIC_ADAPTER`, a test-only
adapter whose descriptors claim ``complete`` coverage, and register it as a
certified experiment adapter *programmatically in the test process only*
(``certified_domain``), the way failpoints are armed. Production has no such
registration.
"""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from typing import Any, Iterator

import working_scenarios as wks  # first: puts tests/, tests/integration and tests/platform on sys.path
import operation_scenarios as osc  # noqa: E402
import claude_fixtures as cf  # noqa: E402
from recalith.capture import pipeline  # noqa: E402
from recalith.capture.normalize import RawEvent, normalize_event  # noqa: E402
from recalith.contracts.common import EvidenceLink, RecordRef, derived_id, digest_of, utc_now  # noqa: E402
from recalith.core import lineage  # noqa: E402
from recalith.storage import db, records  # noqa: E402

KEY = {"subject": "fixture tests", "predicate": "observed"}
SYNTHETIC_ADAPTER = "fixture_experiment"
LIFECYCLE = wks.LIFECYCLE_SESSION
SUBAGENT_SESSION = "69ae6119-1fa5-4fa6-bb80-1d63625ddc81"
REAL_AGENT = "a6697bd76696bfb0a"


def project(tmp: Path, name: str = "lineage", *, scenarios: tuple[str, ...] = ("lifecycle",)) -> wks.Project:
    p = wks.Project(tmp, name)
    for scenario in scenarios:
        p.scenario(scenario)
    p.drain()
    return p


# --------------------------------------------------------------------------
# Synthetic variants of real records


def rerun(call: str, suffix: str, *, scenario: str = "lifecycle", session: str | None = None, command: str | None = None) -> list[dict[str, Any]]:
    """A real call's Pre/Post records under a new tool-use ID (a rerun)."""
    out = []
    for event in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
        found = [r for r in cf.records(scenario) if r["event"] == event and r["payload"].get("tool_use_id") == call]
        for rec in found:
            out.append(wks.variant(rec, tool_suffix=suffix, session=session, command=command))
    return out


def rename_call(call: str, new_id: str, *, scenario: str = "lifecycle") -> list[dict[str, Any]]:
    """A real call's records under a different (e.g. lexicographically smaller) tool-use ID."""
    return [wks.variant(r, replace={call: new_id}) for r in cf.records(scenario) if r["payload"].get("tool_use_id") == call]


def passing_rerun(call: str, suffix: str) -> list[dict[str, Any]]:
    """A rerun of a failing real pytest call whose result is the real passing result (contradictory rerun)."""
    start = wks.variant(wks.record("lifecycle", "PreToolUse", call), tool_suffix=suffix)
    passing = wks.record("lifecycle", "PostToolUse", "toolu_probe_0004")
    finish = wks.variant(passing, replace={"toolu_probe_0004": f"{call}_{suffix}"})
    finish["payload"]["tool_input"] = dict(start["payload"]["tool_input"])
    return [start, finish]


def read_variant(suffix: str, *, path: str | None = None, content: str | None = None) -> list[dict[str, Any]]:
    """The real ``Read notes.txt`` call under a new ID, optionally of another path or changed content."""
    recs = rerun("toolu_probe_0007", suffix)
    for rec in recs:
        payload = rec["payload"]
        if path is not None:
            payload["tool_input"]["file_path"] = f"<workspace>/{path}"
            if "tool_response" in payload:
                payload["tool_response"]["file"]["filePath"] = f"<workspace>/{path}"
        if content is not None and "tool_response" in payload:
            payload["tool_response"]["file"]["content"] = content
    return recs


def in_subagent(recs: list[dict[str, Any]], agent: str, *, host_session: str = SUBAGENT_SESSION) -> list[dict[str, Any]]:
    """Real tool records placed inside a subagent of ``host_session`` (the host's agent fields)."""
    out = []
    for rec in recs:
        rec = wks.variant(rec, session=host_session)
        rec["payload"]["agent_id"] = agent
        rec["payload"]["agent_type"] = "general-purpose"
        out.append(rec)
    return out


def forwarding(agent: str, suffix: str) -> list[dict[str, Any]]:
    """The real ``Agent`` call and its forwarding result, relaying subagent ``agent``."""
    recs = [r for r in cf.records("subagent") if r["payload"].get("tool_use_id") == "toolu_probe_0014"]
    return [wks.variant(r, tool_suffix=suffix, replace={REAL_AGENT: agent}) for r in recs]


# --------------------------------------------------------------------------
# Events and links


def finished(p: wks.Project, call: str) -> str:
    return p.event("tool_finished", call=call)["id"]


def user(p: wks.Project, text: str) -> str:
    return p.event("user_message", text=text)["id"]


def link(event_id: str, relation: str = "supports", *, roots: list[str] | None = None) -> dict[str, Any]:
    return {"ref": {"kind": "event", "id": event_id, "revision": 1}, "relation": relation, "root_event_ids": [event_id] if roots is None else roots, "locator": None, "mapping": None}


def record_link(kind: str, record_id: str, revision: int, *, roots: list[str] | None = None, relation: str = "supports") -> dict[str, Any]:
    return {"ref": {"kind": kind, "id": record_id, "revision": revision}, "relation": relation, "root_event_ids": roots or [], "locator": None, "mapping": None}


def links(*items: dict[str, Any]) -> list[EvidenceLink]:
    return [EvidenceLink.model_validate(i) for i in items]


def resolve(p: wks.Project, items: list[dict[str, Any]], key: Any = KEY) -> lineage.Lineage:
    with p.view() as v:
        return lineage.resolve(v, links(*items), proposition_key=key)


def roots(p: wks.Project, items: list[dict[str, Any]], key: Any = KEY) -> set[str]:
    return lineage.independent_roots(osc.context(p.root), links(*items), proposition_key=key)


def class_of(p: wks.Project, event_id: str) -> str | None:
    with p.view() as v:
        m = lineage.member(v, event_id)
    return None if m is None else m.class_id


# --------------------------------------------------------------------------
# Claims through the real application path


def propose(p: wks.Project, proposition: str, evidence: list[dict[str, Any]], *, kind: str = "fact", basis: str = "inferred") -> str:
    result = p.propose("extract_claims", [osc.op("c", "propose_claim", osc.claim(proposition, kind=kind, basis=basis), evidence=evidence)])
    assert result.decisions[0].outcome == "candidate_only", result.decisions
    return claim_id(p, proposition)


def claim_id(p: wks.Project, proposition: str) -> str:
    return osc.claim_by_text(p.root, proposition)["claim_id"]


def claim(p: wks.Project, cid: str) -> dict[str, Any]:
    with p.view() as v:
        revision, _status = records.head(v, "claim", cid)
        return records.body(v, "claim", cid, revision)


def attach(p: wks.Project, cid: str, evidence: list[dict[str, Any]], relation: str = "supports"):
    ref = osc.head_ref(p.root, "claim", cid)
    return p.propose("extract_claims", [osc.op("a", "attach_evidence", {"claim_ref": ref.model_dump(mode="json"), "relation": relation}, evidence=evidence)])


# --------------------------------------------------------------------------
# Non-hook events through the real normalization and ingestion


def raw_event(p: wks.Project, kind: str, key: str, payload: dict[str, Any], *, adapter: str = "claude_code", version: str = "2.1.301", host_session: str | None = None, at: str | None = None) -> str:
    """One event through ``normalize_event`` → ``capture`` → ``ingest_ready`` (certified routing for ``kind``)."""
    ctx = osc.context(p.root)
    envelope = raw_envelope(ctx, kind, key, payload, adapter=adapter, version=version, host_session=host_session, at=at)
    ingest(ctx, [envelope])
    return envelope.event_id


def raw_envelope(ctx, kind: str, key: str, payload: dict[str, Any], *, adapter: str = "claude_code", version: str = "2.1.301", host_session: str | None = None, at: str | None = None):
    host_session = host_session or (LIFECYCLE if adapter == "claude_code" else "fixture-host-session")
    raw = RawEvent(
        adapter_id=adapter, adapter_version=version, source_event_key=key, session_id=derived_id("sess", [ctx.installation_id, adapter, host_session]),
        host_session_id=host_session, kind=kind, payload=payload, occurred_at=at, recorded_at=at,
    )
    (envelope,), _ = normalize_event(ctx, raw)
    return envelope


def memory_delivered(p: wks.Project, key: str, claim_ref: RecordRef) -> str:
    """Delivery telemetry naming a delivered claim (Task 12b produces these from hook receipts)."""
    return raw_event(p, "memory_delivered", key, {"delivery_id": f"dlv_{digest_of(key)[:8]}-0000-4000-8000-000000000000", "items": [claim_ref.model_dump(mode="json")]})


def assistant(p: wks.Project, key: str, text: str) -> str:
    return raw_event(p, "assistant_message", key, {"text": text, "sidechain": False})


def experiment(p: wks.Project, key: str, **kw: Any) -> str:
    """A synthetic certified-domain experiment result through the real normalization and ingestion."""
    envelope = experiment_envelope(osc.context(p.root), key, **kw)
    ingest(osc.context(p.root), [envelope])
    return envelope.event_id


def ingest(ctx, envelopes) -> None:
    assert pipeline.capture(ctx, list(envelopes), deadline=time.monotonic() + 5).status == "accepted"
    pipeline.ingest_ready(ctx)


def experiment_envelope(
    ctx, key: str, *, deps: dict[str, str | None], outcome: str = "success", coverage: str = "complete", run_id: str = "run-1",
    argv: tuple[str, ...] = ("pytest", "-q", "tests/test_core.py"), artifact: tuple[str, str] | None = None, origin_key: str | None = None, at: str | None = None,
):
    """A synthetic adapter's tool result with an adapter-set descriptor; ``run_id`` is an incidental field."""
    action = {"cwd_path": ".", "tool": "Bash", "action_kind": "test", "executable": argv[0], "argv": list(argv), "paths": [], "raw_digest": None, "parse_status": "exact", "shell": "posix"}
    descriptor = {
        "origin_event_key": {"source_namespace": f"{ctx.installation_id}:{SYNTHETIC_ADAPTER}", "source_event_key": origin_key or key},
        "observation_kind": "tool_result" if artifact is None else "artifact_snapshot",
        "authority_actor_id": None,
        "artifact_key": None if artifact is None else artifact[0],
        "artifact_digest": None if artifact is None else artifact[1],
        "action": action,
        "experiment_identity": "tests/test_core.py",
        "dependencies": [{"kind": "file", "key": k, "fingerprint": v, "record": None} for k, v in sorted(deps.items())],
        "dependency_coverage": coverage,
        "forwarded_origin_keys": [],
    }
    payload = {
        "tool_call_id": key, "tool_name": "Bash", "arguments": {"command": " ".join(argv), "run_id": run_id}, "result_received": True, "outcome": outcome,
        "exit_code": 0 if outcome == "success" else 1, "result_text": f"run {run_id}: {outcome}", "action": action, "observation": descriptor,
    }
    return raw_envelope(ctx, "tool_finished", key, payload, adapter=SYNTHETIC_ADAPTER, version="1", at=at)


@contextlib.contextmanager
def certified_domain(monkeypatch) -> Iterator[None]:
    """Register the synthetic adapter as a certified complete-dependency domain in this test process only."""
    previous = lineage.CERTIFIED_EXPERIMENT_ADAPTERS
    monkeypatch.setattr(lineage, "CERTIFIED_EXPERIMENT_ADAPTERS", frozenset({SYNTHETIC_ADAPTER}))
    try:
        yield
    finally:
        monkeypatch.setattr(lineage, "CERTIFIED_EXPERIMENT_ADAPTERS", previous)


def jobs_of(p: wks.Project, kind: str) -> list[dict[str, Any]]:
    with p.view() as v:
        return [json.loads(b) for (b,) in v.execute("SELECT body FROM jobs WHERE kind = ? ORDER BY job_id", (kind,)).fetchall()]


def meta(p: wks.Project) -> db.Meta:
    return osc.meta(p.root)


def now() -> str:
    return utc_now()


# --------------------------------------------------------------------------
# The kill/restart scenario for root-class merges at ingestion


MARKER = "lineage.json"


def crash_project(tmp: Path, name: str) -> Path:
    """Two counted classes and live claims are committed; the segment that merges them waits in the spool.

    Synthetic adapter events (unknown dependency coverage): ``m-x`` and
    ``m-y`` are separate classes supporting one claim (and ``m-x`` a second);
    ``m-w`` supports an unrelated third claim. The spooled segment holds the
    bridge ``m-b`` (it shares ``m-x``'s experiment family and ``m-y``'s
    artifact snapshot, and has the least origin key, so both old IDs become
    aliases), an unchanged rerun of ``m-x`` (a join, not a merge) and an
    assistant message (never a root). The driver's worker ingests it, which
    merges the classes and enqueues one revalidation job for the two affected
    claims, then runs that job against a no-op body.
    """
    from recalith.controller import apply

    root = osc.ws.init_project(tmp, name)
    ctx = osc.context(root)
    x = experiment_envelope(ctx, "m-x", deps={}, coverage="unknown", argv=("pytest", "-q", "a.py"))
    y = experiment_envelope(ctx, "m-y", deps={}, coverage="unknown", argv=("pytest", "-q", "b.py"), artifact=("file:report.xml", "3" * 64))
    w = experiment_envelope(ctx, "m-w", deps={}, coverage="unknown", argv=("pytest", "-q", "c.py"))
    ingest(ctx, [x, y, w])
    osc._drain_ingest(root)  # noqa: SLF001 - the kill points must land on the merging segment, not earlier typed ingestion
    claims = [("Both suites pass.", [x, y]), ("Suite a passes.", [x]), ("Suite c passes.", [w])]
    ops = [osc._op(osc.op(f"c{i}", "propose_claim", osc.claim(text), evidence=[link(e.event_id) for e in evs])) for i, (text, evs) in enumerate(claims)]  # noqa: SLF001
    apply.apply_operations(osc.operator(root), ops, read_set=osc.read_set(root), submission_id=derived_id("op", [name, "seed"]), now=osc.ws.START)
    bridge = experiment_envelope(ctx, "m-b", deps={}, coverage="unknown", argv=("pytest", "-q", "a.py"), artifact=("file:report.xml", "3" * 64))
    again = experiment_envelope(ctx, "m-x2", deps={}, coverage="unknown", argv=("pytest", "-q", "a.py"), run_id="run-2")
    said = raw_envelope(ctx, "assistant_message", "m-say", {"text": "Both suites pass, as I remembered.", "sidechain": False}, adapter=SYNTHETIC_ADAPTER, version="1")
    assert pipeline.capture(ctx, [bridge, again, said], deadline=time.monotonic() + 5).status == "accepted"
    (root / osc.SCENARIO).write_text(json.dumps({"bodies": {"revalidate": osc.body([], "nothing changed").decode()}}), encoding="utf-8")
    (root / MARKER).write_text("{}", encoding="utf-8")
    return root


def outstanding(root: Path) -> str:
    """``1`` while the merging segment is unspooled or the revalidation job is unfinished (read-only peek)."""
    import sqlite3

    if any((root / ".recalith" / "spool" / "ready").glob("*.json")):
        return "1"
    conn = sqlite3.connect((root / ".recalith" / db.STATE_DB).as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        left = conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'revalidate' AND state NOT IN ('completed', 'cancelled', 'failed')").fetchone()[0]
        made = conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'revalidate'").fetchone()[0]
        return "1" if left or not made else "0"
    except sqlite3.Error:
        return "1"
    finally:
        conn.close()


def lineage_state(root: Path) -> dict[str, Any]:
    """Root classes, members, aliases and tokens with installation-specific IDs mapped to origin keys."""
    ctx = osc.context(root)
    with db.open_store(ctx, readonly=True) as store, store.read() as v:
        origins = v.execute("SELECT source_namespace, source_event_key, root_class_id FROM root_members").fetchall()
        names = {lineage.root_class_id(lineage.OriginEventKey(source_namespace=ns, source_event_key=k)): k for ns, k, _c in origins}
        classes = sorted((k, r) for _id, k, r in v.execute("SELECT root_class_id, canonical_key, equivalence_reasons FROM root_classes").fetchall())
        members = sorted((k, names.get(c, "?")) for _ns, k, c in origins)
        aliases = sorted((names.get(a, "?"), names.get(c, "?")) for a, c in v.execute("SELECT alias_id, root_class_id FROM root_aliases").fetchall())
        tokens = sorted(v.execute("SELECT reason, COUNT(*) FROM root_tokens GROUP BY reason").fetchall())
        events = sorted(v.execute("SELECT source_event_key, observation_kind, outcome, resolution FROM root_event_members").fetchall())
        revalidate = sorted(sorted(r["id"] for r in json.loads(b)["input_refs"]) for (b,) in v.execute("SELECT body FROM jobs WHERE kind = 'revalidate'").fetchall())
        claim_names = dict(v.execute("SELECT h.claim_id, r.body FROM claim_heads h JOIN claim_revisions r ON r.claim_id = h.claim_id AND r.revision = h.revision").fetchall())
    texts = {cid: json.loads(b)["proposition"] for cid, b in claim_names.items()}
    return {"classes": classes, "members": members, "aliases": aliases, "tokens": tokens, "events": events, "revalidate": sorted(sorted(texts.get(c, c) for c in refs) for refs in revalidate)}
