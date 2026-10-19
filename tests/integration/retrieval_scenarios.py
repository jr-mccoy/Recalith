"""Test-only builders for Task 11: retrieval, context packets, views and the hook compiler over real payloads.

Real inputs: every Claude event enters through the real 2.1.301 adapter
mapping, normalization, capture, ingestion and typed reduction
(``working_scenarios.Project``); claims are admitted through the real
extraction/review path with recorded proposals (``consolidation_scenarios``),
and the query actions are the real stored action descriptors of the captured
``pytest -q test_mid.py`` failure (``toolu_probe_0003``) and the other
lifecycle calls.

**Synthetic store states** (named at each use): where a claim state cannot be
reached through the preview's own paths yet (an expired or redacted support,
which Tasks 15/16 produce; a quarantined or forgotten head; a large ranking
corpus), :func:`seed` writes a claim revision directly in one store
transaction, copied from a really admitted claim of the same kind so its
review assessment, evidence and shape stay real, and advances the guidance
epoch as the owning write would. These test the compiler's response to the
state, never the path that produces it.

**Model behavior is recorded proposals** through the real persisted-proposal
path; nothing here measures live recall quality (ACCEPTANCE_TESTS §5/§6 stay
unavailable without a certified route, B1).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Sequence

import consolidation_scenarios as cs  # first: puts tests/, tests/integration and tests/platform on sys.path
import operation_scenarios as osc  # noqa: E402
import working_scenarios as wks  # noqa: E402
from recalith.contracts.common import RecordRef, new_id, utc_now  # noqa: E402
from recalith.contracts.context import ContextPacket, ContextQuery  # noqa: E402
from recalith.contracts.events import ActionDescriptor  # noqa: E402
from recalith.contracts.memory import ClaimRevision  # noqa: E402
from recalith.fast import cache, entry  # noqa: E402
from recalith.retrieval import compile as rc  # noqa: E402
from recalith.retrieval import index  # noqa: E402
from recalith.storage import db, records  # noqa: E402

MID = cs.MID
LESSON = cs.LESSON


def project(tmp: Path, name: str = "retrieval", **kw: Any) -> wks.Project:
    return cs.project(tmp, name, **kw)


def action(ev: dict[str, Any]) -> ActionDescriptor:
    return ActionDescriptor.model_validate(ev["payload"]["action"])


def mid_action(p: wks.Project) -> ActionDescriptor:
    return action(cs.failure(p))


def query(p: wks.Project, purpose: str = "pre_action", *, text: str = "", act: ActionDescriptor | None = None, task: str | None = None, session: str | None = None,
          environment: dict[str, str] | None = None, branch: str | None = None, max_tokens: int | None = None, workspace: str | None = None) -> ContextQuery:
    return ContextQuery(session_id=session or p.session_of(), task_id=task, workspace_id=workspace or p.ctx.workspace_id, purpose=purpose, text=text, action=act,
                        environment=environment or {}, branch_ref=branch, max_estimated_tokens=max_tokens)


def service(p: wks.Project, q: ContextQuery, **kw: Any) -> ContextPacket:
    return rc.compile_context(p.ctx, q, **kw)


def publish(p: wks.Project) -> dict[str, int]:
    """The worker's projection step, repeated until nothing is due (the index is bounded per transaction)."""
    total: dict[str, int] = {}
    with db.open_store(p.ctx) as store:
        for _ in range(100):
            did = rc.refresh_projection(store, p.ctx)
            if not did:
                return total
            for key, value in did.items():
                total[key] = total.get(key, 0) + value
    raise AssertionError("the projection never caught up")


def hook(p: wks.Project, q: ContextQuery, *, seconds: float = 2.0, **kw: Any) -> dict[str, Any]:
    ctx = entry.load_context(str(p.root), "claude_code")
    return cache.compile_packet(ctx, q.model_dump(mode="json"), deadline=time.monotonic() + seconds, **kw)


def ids(packet: ContextPacket | dict[str, Any]) -> list[str]:
    items = packet.items if isinstance(packet, ContextPacket) else packet["items"]
    return [(i.ref.id if hasattr(i, "ref") else i["ref"]["id"]) for i in items]


def by_id(packet: ContextPacket | dict[str, Any]) -> dict[str, dict[str, Any]]:
    data = packet.model_dump(mode="json") if isinstance(packet, ContextPacket) else packet
    return {i["ref"]["id"]: i for i in data["items"]}


def advice(packet: ContextPacket | dict[str, Any], record_id: str) -> str | None:
    item = by_id(packet).get(record_id)
    return None if item is None else item["advice"]


def epoch(p: wks.Project) -> int:
    return osc.meta(p.root).guidance_epoch


def store_revision(p: wks.Project) -> int:
    return osc.meta(p.root).store_revision


# --------------------------------------------------------------------------
# Synthetic store states (see the module docstring)


def body(p: wks.Project, claim_id: str) -> dict[str, Any]:
    with p.view() as v:
        revision, _status = records.head(v, "claim", claim_id)
        return records.body(v, "claim", claim_id, revision)


def seed(p: wks.Project, template: str, *, proposition: str | None = None, serving: bool = True, **changes: Any) -> str:
    """A new claim copied from an admitted ``template`` with ``changes`` (synthetic store state)."""
    data = body(p, template)
    data.update({"claim_id": new_id("claim"), "revision": 1, "recorded_at": utc_now(), "supersedes": [], "superseded_by": []})
    if proposition is not None:
        data["proposition"] = proposition
    data.update(changes)
    return _write(p, data, serving=serving)


def restate(p: wks.Project, claim_id: str, **changes: Any) -> int:
    """A new revision of an existing claim with ``changes`` (synthetic store state); returns the revision."""
    data = body(p, claim_id)
    data.update(changes)
    data["revision"] += 1
    data["recorded_at"] = utc_now()
    _write(p, data)
    return data["revision"]


def content_free(p: wks.Project, claim_id: str, status: str) -> None:
    """A quarantined or forgotten head: a content-free marker (synthetic store state)."""
    data = body(p, claim_id)
    data.update({"status": status, "proposition": "", "proposition_key": None, "supports": [], "contradicts": [], "context": [], "failure": None, "procedure": None,
                 "revision": data["revision"] + 1, "recorded_at": utc_now(), "review_assessment": None})
    if data["kind"] in ("failure_lesson", "procedure"):
        data["kind"] = "fact"
    _write(p, data)


def _write(p: wks.Project, data: dict[str, Any], *, serving: bool = True) -> str:
    claim = ClaimRevision.model_validate_json(json.dumps(data))
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        records.write_claim(txn, claim)
        txn.mutated(serving_relevant=serving)
    return claim.claim_id


def corpus(p: wks.Project, template: str, n: int, *, proposition: str, scope: dict[str, Any] | None = None, status: str | None = None, batch: int = 2000) -> list[str]:
    """``n`` claims copied from ``template`` in a few transactions (synthetic ranking corpus)."""
    base = body(p, template)
    out = []
    with db.open_store(p.ctx) as store:
        for start in range(0, n, batch):
            with store.transaction() as txn:
                for i in range(start, min(n, start + batch)):
                    data = dict(base, claim_id=new_id("claim"), revision=1, recorded_at=utc_now(), proposition=proposition.format(i=i), supersedes=[], superseded_by=[])
                    data["proposition_key"] = {"subject": f"corpus {i}", "predicate": "observed"}
                    if scope is not None:
                        data["scope"] = scope
                    if status is not None:
                        data["status"] = status
                    claim = ClaimRevision.model_validate_json(json.dumps(data))
                    records.write_claim(txn, claim)
                    out.append(claim.claim_id)
                txn.mutated(serving_relevant=True)
    return out


def set_payload_state(p: wks.Project, event_id: str, state: str) -> None:
    """An event payload expired or forgotten (synthetic: Tasks 15/16 own this write and its epoch advance)."""
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        txn.execute("UPDATE events SET payload_state = ? WHERE event_id = ?", (state, event_id))
        txn.mutated(serving_relevant=True)


# --------------------------------------------------------------------------
# The kill/restart scenario (driven by worker_scenarios.py)

SCENARIO = "retrieval.json"


def crash_project(tmp: Path, name: str) -> Path:
    """The Task 10 revision scenario with the projection under test.

    Built through the real paths without any worker poll after the claims were
    admitted, so nothing is indexed or published yet; the spooled segment's
    passing rerun, dependency write and second rerun then advance the guidance
    epoch again while revalidation and review jobs apply. The driver's worker
    must leave the index at the final store revision and the views at the
    final epochs, equal to a reference run.
    """
    root = cs.crash_project(tmp, name)
    (root / SCENARIO).write_text(json.dumps({"retrieval": True}), encoding="utf-8")
    return root


def scenario(root: Path) -> bool:
    return (root / SCENARIO).exists()


def outstanding(root: Path) -> str:
    """``1`` while projection work is owed, or Task 10 work is unfinished (read-only).

    Owed, whatever ``projection_state`` claims: a servable head without its
    current index document (or a document of an older revision), and view rows
    missing or labeled with other epochs than the store's. The recorded state's
    own lag counts too.
    """
    import sqlite3

    path = root / ".recalith" / db.STATE_DB
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        meta = conn.execute("SELECT store_revision, guidance_epoch, policy_revision, tombstone_epoch FROM installation_meta").fetchone()
        state = conn.execute("SELECT indexed_store_revision, views_guidance_epoch, views_policy_revision, views_tombstone_epoch FROM projection_state").fetchone()
        lag = state is None or state[0] != meta[0] or tuple(state[1:]) != tuple(meta[1:])
        owed_docs = 0
        for kind, (heads, _revisions, key, column, ok) in index.HEADS.items():
            marks = ",".join("?" for _ in ok)
            owed_docs += conn.execute(
                f"SELECT COUNT(*) FROM {heads} h LEFT JOIN retrieval_docs d ON d.record_kind = ? AND d.record_id = h.{key} AND d.record_revision = h.revision "  # noqa: S608
                f"WHERE h.{column} IN ({marks}) AND d.record_id IS NULL" + (" AND h.redirect_task_id IS NULL" if kind == "task" else ""),
                (kind, *ok),
            ).fetchone()[0]
        views = conn.execute("SELECT COUNT(*), SUM(guidance_epoch != ? OR policy_revision != ? OR tombstone_epoch != ?) FROM context_views", tuple(meta[1:])).fetchone()
        owed_views = views[0] == 0 or bool(views[1])
    except sqlite3.Error:
        lag, owed_docs, owed_views = True, 1, True
    finally:
        conn.close()
    return "1" if lag or owed_docs or owed_views or cs.outstanding(root) == "1" else "0"


ID_PATTERNS = (r"claim_[0-9a-f-]{36}", r"task_[0-9a-f-]{36}", r"ep_[0-9a-f-]{36}", r"qst_[0-9a-f]{64}")


def projection_state(root: Path) -> dict[str, Any]:
    """The projection, normalized: index terms and docs, views and fallback rows, and the packets they compile to.

    Claim IDs become their propositions, other generated IDs placeholders and
    store revisions are dropped (bookkeeping differs across restarts); epochs
    stay.
    """
    ctx = osc.context(root)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        meta = store.meta()
        state = index.state(view)
        names = {cid: json.loads(b)["proposition"] for cid, b in view.execute("SELECT h.claim_id, r.body FROM claim_heads h JOIN claim_revisions r ON r.claim_id = h.claim_id AND r.revision = h.revision").fetchall()}
        names.update({tid: "TASK:" + json.loads(b)["title"] for tid, b in view.execute("SELECT h.task_id, r.body FROM task_heads h JOIN task_revisions r ON r.task_id = h.task_id AND r.revision = h.revision").fetchall()})
        names.update({eid: "EPISODE:" + json.loads(b)["title"] for eid, b in view.execute("SELECT h.episode_id, r.body FROM episode_heads h JOIN episode_revisions r ON r.episode_id = h.episode_id AND r.revision = h.revision").fetchall()})
        keys = dict(view.execute("SELECT event_id, source_event_key FROM events").fetchall())
        # Installation-derived digests: action families (workspace ID) and claim-dependency fingerprints (claim ID).
        from recalith.controller import revalidate

        for cid, family in view.execute("SELECT claim_id, action_family_digest FROM claim_heads WHERE action_family_digest IS NOT NULL").fetchall():
            keys[family] = "FAMILY:" + names.get(cid, cid)
        for (cid,) in view.execute("SELECT claim_id FROM claim_heads").fetchall():
            fp = revalidate.claim_fingerprint(view, cid)
            if fp:
                keys[fp] = "CLAIMFP:" + names.get(cid, cid)
        for (fp,) in view.execute("SELECT DISTINCT fingerprint FROM dependencies WHERE kind = 'claim' AND fingerprint IS NOT NULL").fetchall():
            keys.setdefault(fp, "CLAIMFP:recorded")
        terms = sorted((_norm(t, names, keys, ctx), k, names.get(r, r)) for t, k, r in view.execute("SELECT term, record_kind, record_id FROM lexical_index").fetchall())
        docs = sorted((k, names.get(r, r), s, n) for k, r, s, n in view.execute("SELECT record_kind, record_id, status, term_count FROM retrieval_docs").fetchall())
        rows = view.execute("SELECT view_id, purpose, guidance_epoch, policy_revision, tombstone_epoch, body FROM context_views ORDER BY view_id").fetchall()
    out_views = sorted((re.sub(r":\d{4}:", ":RANK:", _norm(v, names, keys, ctx)), purpose, g, pol, t, _sorted_candidates(_norm(_strip_revisions(b), names, keys, ctx))) for v, purpose, g, pol, t, b in rows)
    current = state is not None and state["indexed"] == meta.store_revision and (state["views_guidance"], state["views_policy"], state["views_tombstone"]) == (meta.guidance_epoch, meta.policy_revision, meta.tombstone_epoch)
    return {"current": current, "backend": state and state["backend"], "terms": terms, "docs": docs, "views": out_views, "epoch": meta.guidance_epoch}


def _sorted_candidates(text: str) -> str:
    """Candidate order inside a view breaks score ties by (random) record ID; the set and each candidate must match."""
    data = json.loads(text)
    if isinstance(data.get("candidates"), list):
        data["candidates"] = sorted(data["candidates"], key=lambda c: json.dumps(c, sort_keys=True))
    return json.dumps(data, sort_keys=True)


def _strip_revisions(text: str) -> str:
    data = json.loads(text)
    data.pop("store_revision", None)
    return json.dumps(data, sort_keys=True)


def _norm(text: str, names: dict[str, str], keys: dict[str, str], ctx: Any) -> str:
    for pattern in ID_PATTERNS:
        text = re.sub(pattern, lambda m: names.get(m.group(0), "ID"), text)
    text = re.sub(r"evt_[0-9a-f]{64}", lambda m: keys.get(m.group(0), "EVT"), text)
    text = re.sub(r"(?<![0-9a-f_])[0-9a-f]{64}(?![0-9a-f])", lambda m: keys.get(m.group(0), m.group(0)), text)
    text = re.sub(r"(sess|ses)_[0-9a-f]{64}", "SESS", text)
    for value, label in ((ctx.installation_id, "INST"), (ctx.project_id, "PROJ"), (ctx.workspace_id, "WKS")):
        text = text.replace(value, label)
    return text


def packets(root: Path) -> list[Any]:
    """The service and hook packets for the scenario's real ``test_mid`` action (items normalized)."""
    ctx = osc.context(root)
    p = wks.Project.__new__(wks.Project)
    p.root, p.ctx = root, ctx
    p.replay = None  # type: ignore[assignment]
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        names = {cid: json.loads(b)["proposition"] for cid, b in view.execute("SELECT h.claim_id, r.body FROM claim_heads h JOIN claim_revisions r ON r.claim_id = h.claim_id AND r.revision = h.revision").fetchall()}
        row = view.execute("SELECT payload, session_id FROM events WHERE kind = 'tool_finished' AND payload LIKE '%test_mid.py%' ORDER BY commit_sequence LIMIT 1").fetchone()
    act = ActionDescriptor.model_validate(json.loads(row[0])["action"])
    q = ContextQuery(session_id=row[1], task_id=None, workspace_id=ctx.workspace_id, purpose="pre_action", text="pytest test_mid fixture", action=act)
    svc = rc.compile_context(ctx, q)
    hk = cache.compile_packet(entry.load_context(str(root), "claude_code"), q.model_dump(mode="json"), deadline=time.monotonic() + 5)
    norm = lambda items: sorted((names.get(i["ref"]["id"], i["ref"]["kind"]), i["advice"], i["why"][0]) for i in items)  # noqa: E731
    return [norm(svc.model_dump(mode="json")["items"]), hk["source"], norm(hk["packet"]["items"])]


def view_count(p: wks.Project) -> int:
    with db.open_store(p.ctx, readonly=True) as store:
        return len(rc.views(store))


def refs(*claim_ids: str) -> list[RecordRef]:
    return [RecordRef(kind="claim", id=c, revision=1) for c in claim_ids]


def fixed_seconds(fn, *args: Any, repeat: int = 5, **kw: Any) -> list[float]:
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn(*args, **kw)
        times.append(time.perf_counter() - start)
    return times


__all__: Sequence[str] = ()
