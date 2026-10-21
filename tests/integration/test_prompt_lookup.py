"""Decision 0021: the bounded lexical lookup behind the hook's prompt context at corpus scale (Task 11 follow-up; A58, A23–A25, A01).

Real inputs: the Task 11 builders (``retrieval_scenarios``): facts admitted
through the real extraction/review path with recorded proposals, the real
worker projection step (``refresh_projection``: index, views, lookup) and
the real hook compiler (``fast.cache.compile_packet``) against the
installation's store; one test runs the real hook entry in fresh ``python -I``
processes. **Synthetic store states**, named at each use: the ranking corpus
(claims copied from an admitted fact), a corroborated corpus template (so
the static view slice is provably full of corpus heads), content-free
quarantined/forgotten heads, a direct policy-revision bump, a synthetic
tombstone and a synthetic lookup row of another workspace. Deterministic
mechanics only; no live recall quality (B1).
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time

import pytest

import retrieval_scenarios as rs  # first: puts tests/, tests/integration and tests/platform on sys.path
import claude_fixtures as cf  # noqa: E402
import consolidation_scenarios as cs  # noqa: E402
import delivery_scenarios as ds  # noqa: E402
import operation_scenarios as osc  # noqa: E402
from recalith import service  # noqa: E402
from recalith.contracts.common import RecordRef, new_id  # noqa: E402
from recalith.contracts.privacy import ForgetRequest, ForgetSelector  # noqa: E402
from recalith.fast import context as fc  # noqa: E402
from recalith.retrieval import compile as rc  # noqa: E402
from recalith.retrieval import search  # noqa: E402
from recalith.storage import db, records  # noqa: E402

FACT = "The fixture teardown must close the sqlite connection."
CORPUS = "Corpus {i}: deployment notes for the staging bucket and cache warmup."
PROMPT = "How should the fixture teardown close the sqlite connection before test_mid? #{i}"
SCOPE = {"workspace_ids": [], "task_ids": [], "branch_refs": [], "paths": [], "environment": {}}


def _prompt(p, text, **kw):
    return rs.query(p, "prompt", text=text, session=new_id("sess"), **kw)


def _strong_corpus(p, template: str, n: int) -> None:
    """``n`` corroborated corpus heads (synthetic): every static view and fallback slot ranks them first."""
    strong = rs.seed(p, template, proposition="Corpus template: deployment notes for the staging bucket.", strength="corroborated")
    rs.corpus(p, strong, n, proposition=CORPUS)


def _view_ids(p, purpose: str = "prompt") -> set[str]:
    """The workspace view the hook serves for an unbound ``purpose`` query."""
    with db.open_store(p.ctx, readonly=True) as store:
        for view in rc.views(store):
            if view["view_id"] == rc.view_id(p.ctx.workspace_id, None, purpose):
                return {c["ref"]["id"] for c in view["body"]["candidates"]}
    return set()


def _static_ids(p) -> set[str]:
    """Every claim the query-independent views and fallback rows hold (what the hook could see before decision 0021)."""
    with db.open_store(p.ctx, readonly=True) as store:
        out = set()
        for view in rc.views(store):
            body = view["body"]
            for cand in body.get("candidates") or ([body["candidate"]] if "candidate" in body else []):
                out.add(cand["ref"]["id"])
    return out


def _lookup_rows(p, claim_id: str) -> tuple[int, int]:
    with db.open_store(p.ctx, readonly=True) as store, store.read() as v:
        rows = v.execute("SELECT COUNT(*) FROM lookup_candidates WHERE claim_id = ? AND body IS NOT NULL", (claim_id,)).fetchone()[0]
        postings = v.execute("SELECT COUNT(*) FROM lookup_postings WHERE claim_id = ?", (claim_id,)).fetchone()[0]
    return rows, postings


def _drop_views(p) -> None:
    """A missing packet cache, as ``tools/measure_release_latency.py`` makes it: views gone, fallback rows and the lookup kept."""
    conn = sqlite3.connect(p.root / ".recalith" / db.STATE_DB, timeout=5)
    try:
        conn.execute("DELETE FROM context_views WHERE purpose != 'fallback'")
        conn.execute("UPDATE projection_state SET views_store_revision = -1, views_guidance_epoch = -1")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module")
def corpus10k(tmp_path_factory):
    """One relevant fact among 10,000 near-identical heads (the §7 gate's corpus), projected by the worker step."""
    p = rs.project(tmp_path_factory.mktemp("lookup10k"))
    fact = cs.fact(p, FACT, subject="teardown sqlite")
    rs.corpus(p, fact, 10_000, proposition=CORPUS)
    rs.publish(p)
    return p, fact


# --------------------------------------------------------------------------
# Recall at corpus scale


def test_prompt_fact_recall_from_warm_views_at_ten_thousand_heads(corpus10k):
    """Warm views: the prompt-specific fact reaches the hook through the bounded lookup, as it reaches the service."""
    p, fact = corpus10k
    with p.view() as v:
        assert v.execute("SELECT COUNT(*) FROM claim_heads WHERE status = 'active'").fetchone()[0] >= 10_001
    for i in range(6):
        q = _prompt(p, PROMPT.format(i=i))
        assert fact in rs.ids(rs.service(p, q))
        warm = rs.hook(p, q)
        assert warm["source"] == "view" and warm["packet"]["degraded_reasons"] == []
        assert fact in rs.ids(warm["packet"]) and FACT in json.dumps(warm["packet"])
        assert rs.advice(warm["packet"], fact) == "context"
    # Less than the lookup's 60 ms left when it would start: shed with its reason; the view's own content is still served.
    from recalith.fast import lookup as fl

    short = rs.hook(p, _prompt(p, PROMPT.format(i=99)), seconds=fl.MIN_REMAINING - 0.002)
    assert short["source"] == "view" and fact not in rs.ids(short["packet"]) and short["lookup"] == []
    assert "deadline_lookup_skipped" in short["packet"]["degraded_reasons"]


def test_prompt_fact_recall_from_cold_views_at_ten_thousand_heads(corpus10k, tmp_path):
    """Cold/missing views: the bounded fallback plus the lookup still deliver the fact; only ``view_missing`` is reported."""
    p, fact = corpus10k
    _drop_views(p)
    try:
        for i in range(6):
            cold = rs.hook(p, _prompt(p, PROMPT.format(i=i)))
            assert cold["source"] == "fallback" and cold["packet"]["degraded_reasons"] == ["view_missing"]
            assert fact in rs.ids(cold["packet"])
    finally:
        rs.publish(p)
    assert rs.hook(p, _prompt(p, PROMPT.format(i=7)))["source"] == "view"


@pytest.mark.parametrize("n", [0, 50, 200])
def test_prompt_fact_recall_does_not_depend_on_the_static_slice(tmp_path, n):
    """Decision 0020 item 15's sizes: with a corroborated corpus the fact is never in a static view, yet the hook emits it."""
    p = rs.project(tmp_path)
    fact = cs.fact(p, FACT, subject="teardown sqlite")
    if n:
        _strong_corpus(p, fact, n)
    rs.publish(p)
    if n >= 200:
        assert fact not in _static_ids(p)  # outside every query-independent slice
    q = _prompt(p, PROMPT.format(i=1))
    hooked = rs.hook(p, q)
    assert fact in rs.ids(hooked["packet"]) and fact in rs.ids(rs.service(p, q))
    assert (fact in hooked["lookup"]) == (fact not in _view_ids(p))


def test_quiet_prompts_stay_quiet_at_ten_thousand_heads(corpus10k):
    """Correctly quiet prompts: no shared term, or stopwords only, add nothing through the lookup (A23 relevance)."""
    p, _fact = corpus10k
    for text in ("thanks, that is all for now", "please refactor the login banner colours", "what is it", "#"):
        q = _prompt(p, text)
        hooked = rs.hook(p, q)
        assert hooked["packet"]["items"] == [] and hooked["lookup"] == [], text
        assert rs.service(p, q).items == []


def test_hook_and_service_agree_on_lookup_eligibility(corpus10k):
    """Every lookup candidate the hook decides eligible, the service decides eligible with the same item (and the reverse within the caps)."""
    p, fact = corpus10k
    texts = [PROMPT.format(i=i) for i in (3, 4)] + ["teardown sqlite connection", "fixture close", "deployment staging bucket warmup 17", "Corpus 9999 cache"]
    for text in texts:
        q = _prompt(p, text)
        hooked = rs.hook(p, q)
        svc = {i["ref"]["id"]: i for i in rs.service(p, q).model_dump(mode="json")["items"]}
        assert hooked["lookup"], text
        for item in hooked["packet"]["items"]:
            if item["ref"]["id"] in hooked["lookup"]:
                strict = _strict_item(p, q, item["ref"]["id"])
                assert strict is not None and {k: strict[k] for k in ("advice", "applicability", "freshness", "text")} == {k: item[k] for k in ("advice", "applicability", "freshness", "text")}
                if item["ref"]["id"] in svc:
                    assert svc[item["ref"]["id"]]["advice"] == item["advice"]


def _strict_item(p, q, claim_id):
    """The service's strict decision (core.conditions, revalidate.guidance) for one claim under ``q``."""
    with db.open_store(p.ctx, readonly=True) as store, store.read() as v:
        claim = records.load(v, "claim", claim_id, records.head(v, "claim", claim_id)[0])
        cand = search.servable_candidate(v, p.ctx, claim, environment=q.environment, workspace_id=q.workspace_id)
        if cand is None:
            return None
        decided = search.decide(v, p.ctx, cand, q, family=None, query_terms=set(fc.terms(q.text)), budget=fc.DependencyBudget(None), claim=claim)
        return decided["item"] if decided else None


# --------------------------------------------------------------------------
# Filters, fences and isolation


def test_lookup_never_serves_retired_forgotten_or_superseded_content(tmp_path):
    """Superseded, archived, quarantined and forgotten claims are never served through the lookup, before or after republication."""
    p = rs.project(tmp_path)
    anchor = cs.fact(p, FACT, subject="teardown sqlite")
    facts = {word: cs.fact(p, f"The {word} fixture keeps its own sqlite file.", subject=f"{word} fixture") for word in ("zephyr", "quasar", "nimbus", "tundra", "fjord")}
    _strong_corpus(p, anchor, 160)
    rs.publish(p)
    for word, claim_id in facts.items():
        hooked = rs.hook(p, _prompt(p, f"Where does the {word} fixture keep its sqlite file?"))
        assert claim_id in hooked["lookup"] and claim_id in rs.ids(hooked["packet"]), word  # the lookup is the only path here
    rs.restate(p, facts["zephyr"], status="superseded")
    rs.restate(p, facts["quasar"], status="archived")
    rs.content_free(p, facts["nimbus"], "quarantined")
    rs.content_free(p, facts["tundra"], "forgotten")
    revision = osc.head_ref(p.root, "claim", facts["fjord"]).revision
    ctx = osc.operator(p.root)
    selector = ForgetSelector(record_refs=[RecordRef(kind="claim", id=facts["fjord"], revision=revision)])
    preview = service.preview_forget(ctx, selector)
    service.apply_forget(ctx, ForgetRequest(selector=selector, preview_digest=preview.preview_digest))
    assert _lookup_rows(p, facts["fjord"]) == (0, 0)  # purged in the forget transaction itself
    for stage in ("stale rows", "republished"):
        for word, claim_id in facts.items():
            q = _prompt(p, f"Where does the {word} fixture keep its sqlite file?")
            hooked = rs.hook(p, q)
            assert claim_id not in rs.ids(hooked["packet"]) and claim_id not in hooked["lookup"], (stage, word)
            assert claim_id not in rs.ids(rs.service(p, q)), (stage, word)
        rs.publish(p)
    for claim_id in facts.values():
        assert _lookup_rows(p, claim_id) == (0, 0)


def test_lookup_rows_follow_expired_support_and_scope(tmp_path):
    """Expired support and another workspace's scope keep a claim out of the lookup; restored support brings it back."""
    p = rs.project(tmp_path)
    anchor = cs.fact(p, FACT, subject="teardown sqlite")
    _strong_corpus(p, anchor, 160)
    seq = p.event("tool_finished", call="toolu_probe_0005")  # its own support event (the real seq result)
    own = cs.fact(p, "The glacier fixture keeps its own sqlite file.", subject="glacier fixture", evidence=seq)
    other = rs.seed(p, own, proposition="The glacier fixture keeps another workspace's sqlite file.", scope=dict(SCOPE, workspace_ids=[new_id("ws")]))
    rs.publish(p)
    q = _prompt(p, "Where does the glacier fixture keep its sqlite file?")
    assert own in rs.hook(p, q)["lookup"] and other not in rs.hook(p, q)["lookup"]
    assert _lookup_rows(p, other) == (0, 0)
    support = [link["ref"]["id"] for link in rs.body(p, own)["supports"] if link["ref"]["kind"] == "event"]
    for event_id in support:
        rs.set_payload_state(p, event_id, "expired")
    for _stage in ("stale rows", "republished"):
        assert own not in rs.ids(rs.hook(p, q)["packet"]) and own not in rs.ids(rs.service(p, q))
        rs.publish(p)
    for event_id in support:
        rs.set_payload_state(p, event_id, "available")
    rs.publish(p)
    assert own in rs.hook(p, q)["lookup"]


def test_lookup_refuses_stale_epochs_and_revisions(tmp_path):
    """A changed revision, a newer tombstone and a policy change are refused; nothing older than the store is served."""
    p = rs.project(tmp_path)
    anchor = cs.fact(p, FACT, subject="teardown sqlite")
    fact = cs.fact(p, "The aurora fixture keeps its own sqlite file.", subject="aurora fixture")
    _strong_corpus(p, anchor, 160)
    rs.publish(p)
    q = _prompt(p, "Where does the aurora fixture keep its sqlite file?")
    assert fact in rs.hook(p, q)["lookup"]
    # A new revision: the old row is stale until the worker re-renders it.
    rs.restate(p, fact, proposition="The aurora fixture now keeps a shared sqlite file.")
    stale = rs.hook(p, q)
    assert stale["source"] == "fallback" and fact not in rs.ids(stale["packet"])
    rs.publish(p)
    fresh = rs.hook(p, q)
    assert fact in fresh["lookup"] and "shared sqlite file" in json.dumps(fresh["packet"])
    # A newer tombstone naming the claim's support (synthetic): refused before any republication.
    support = sorted(link["ref"]["id"] for link in rs.body(p, fact)["supports"] if link["ref"]["kind"] == "event")
    raw = sqlite3.connect(p.root / ".recalith" / db.STATE_DB, timeout=5)
    try:
        epoch = raw.execute("SELECT tombstone_epoch FROM installation_meta").fetchone()[0] + 1
        raw.execute("INSERT INTO tombstones (tombstone_id, epoch, target_ids, source_digests, deletion_scope, created_at) VALUES (?, ?, ?, '[]', 'record', '2026-10-21T00:00:00Z')",
                    ("tomb_synthetic", epoch, json.dumps(support)))
        for target in support:
            raw.execute("INSERT OR IGNORE INTO tombstone_targets (target_id, tombstone_id, epoch) VALUES (?, 'tomb_synthetic', ?)", (target, epoch))
        raw.execute("UPDATE installation_meta SET tombstone_epoch = ?", (epoch,))
        raw.commit()
    finally:
        raw.close()
    tombed = rs.hook(p, q)
    assert fact not in rs.ids(tombed["packet"]) and fact not in tombed["lookup"]
    # A policy change (synthetic bump): the lookup, like the fallback, is refused outright.
    raw = sqlite3.connect(p.root / ".recalith" / db.STATE_DB, timeout=5)
    try:
        raw.execute("UPDATE installation_meta SET policy_revision = policy_revision + 1")
        raw.commit()
    finally:
        raw.close()
    other = rs.hook(p, _prompt(p, "Where does the teardown close the sqlite connection?"))
    assert other["packet"]["items"] == [] and {"fallback_policy_changed", "lookup_policy_changed"} <= set(other["packet"]["degraded_reasons"])


def test_lookup_is_isolated_per_workspace_and_installation(tmp_path):
    """Rows are keyed by workspace and read only from the hook's own store; another installation's fact never appears."""
    a, b = rs.project(tmp_path, "proj-a"), rs.project(tmp_path, "proj-b")
    fact_a = cs.fact(a, "The borealis fixture keeps its own sqlite file.", subject="borealis fixture")
    anchor_b = cs.fact(b, FACT, subject="teardown sqlite")
    for proj, anchor in ((a, fact_a), (b, anchor_b)):
        _strong_corpus(proj, anchor, 160)
        rs.publish(proj)
    q_a = _prompt(a, "Where does the borealis fixture keep its sqlite file?")
    assert fact_a in rs.hook(a, q_a)["lookup"]
    q_b = _prompt(b, "Where does the borealis fixture keep its sqlite file?")
    hooked = rs.hook(b, q_b)
    assert fact_a not in json.dumps(hooked) and "borealis" not in json.dumps(hooked["packet"]["items"])
    assert rs.hook(b, rs.query(b, "prompt", text="borealis fixture", workspace=a.ctx.workspace_id))["packet"]["degraded_reasons"] == ["foreign_installation"]
    # A row of another workspace (synthetic) is never read for this one, even with a matching posting.
    body = None
    with db.open_store(a.ctx, readonly=True) as store, store.read() as v:
        body, base = v.execute("SELECT body, (SELECT base FROM lookup_postings WHERE claim_id = ? LIMIT 1) FROM lookup_candidates WHERE claim_id = ?", (fact_a, fact_a)).fetchone()
    raw = sqlite3.connect(b.root / ".recalith" / db.STATE_DB, timeout=5)
    try:
        cols = [r[1] for r in raw.execute("PRAGMA table_info(lookup_candidates)").fetchall()]
        row = raw.execute("SELECT * FROM lookup_candidates LIMIT 1").fetchone()
        values = dict(zip(cols, row, strict=True), workspace_id="ws_elsewhere", claim_id=fact_a, body=body)
        raw.execute(f"INSERT INTO lookup_candidates ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [values[c] for c in cols])  # noqa: S608
        raw.execute("INSERT INTO lookup_postings (workspace_id, term, base, claim_id) VALUES ('ws_elsewhere', 'borealis', ?, ?)", (base, fact_a))
        raw.commit()
    finally:
        raw.close()
    assert fact_a not in json.dumps(rs.hook(b, q_b))


# --------------------------------------------------------------------------
# The worker side


def test_lookup_refresh_is_bounded_idempotent_and_never_advances_epochs(tmp_path):
    """The reconciler renders in bounded batches outside the write lock, records its epochs only when complete, and then idles."""
    p = rs.project(tmp_path)
    fact = cs.fact(p, FACT, subject="teardown sqlite")
    rs.corpus(p, fact, 1_300, proposition=CORPUS)
    before = osc.meta(p.root)
    from recalith.retrieval import lookup as rl

    with db.open_store(p.ctx) as store:
        batches = []
        while any(rc.projection_due(store).values()):
            batches.append(rc.refresh_projection(store, p.ctx).get("lookup", 0))
        assert len([b for b in batches if b]) >= 3 and max(batches) <= rl.BATCH and sum(batches) >= 1_301
        assert rc.projection_due(store) == {"index": False, "views": False, "lookup": False}
        assert rc.refresh_projection(store, p.ctx) == {}
    after = osc.meta(p.root)
    assert (after.guidance_epoch, after.store_revision) == (before.guidance_epoch, before.store_revision)


def test_lookup_batch_is_discarded_when_the_epochs_move(tmp_path, monkeypatch):
    """A batch rendered from a snapshot whose epochs moved before its write is discarded, never written over newer state."""
    from recalith.retrieval import lookup as rl

    p = rs.project(tmp_path)
    fact = cs.fact(p, FACT, subject="teardown sqlite")  # nothing projected yet: the lookup is owed
    rendered = rl.plan

    def racing(q, ctx, meta):
        out = rendered(q, ctx, meta)
        rs.restate(p, fact, status="archived")  # commits between the read and the write
        return out

    monkeypatch.setattr(rl, "plan", racing)
    with db.open_store(p.ctx) as store:
        assert rl.refresh(store, p.ctx) == {"lookup_retry": 1}
    monkeypatch.setattr(rl, "plan", rendered)
    assert _lookup_rows(p, fact) == (0, 0)
    rs.publish(p)
    assert _lookup_rows(p, fact) == (0, 0)


# --------------------------------------------------------------------------
# Fresh processes


def test_fresh_hook_processes_emit_the_fact_warm_and_cold(tmp_path):
    """The real ``python -I -m recalith.fast.entry`` emits the prompt-specific fact at 2,000 heads, warm and with the views missing."""
    p, _ids = ds.project(tmp_path)
    fact = cs.fact(p, FACT, subject="teardown sqlite")
    _strong_corpus(p, fact, 2_000)
    rs.publish(p)
    ds.enable(p)
    for regime in ("warm", "cold"):
        if regime == "cold":
            _drop_views(p)
        rec = ds.wks.variant(ds.record("UserPromptSubmit"), session=f"00000000-0000-4000-8109-{0 if regime == 'warm' else 1:012d}", prompt=PROMPT.format(i=5))
        reply = tmp_path / f"reply-{regime}.json"
        argv = [sys.executable, "-I", "-m", "recalith.fast.entry", "--project", str(p.root), "claude_code", "--event", rec["event"], "--reply-file", str(reply)]
        started = time.perf_counter()
        proc = subprocess.run(argv, input=p.replay.prepare(rec), capture_output=True, env=cf.child_env(), timeout=60, check=False)
        assert proc.returncode == 0, proc.stderr[-2000:]
        body = json.loads(reply.read_text(encoding="utf-8"))
        assert body["delivery"]["state"] == "emitted", (regime, body, time.perf_counter() - started)
        assert "sqlite connection" in proc.stdout.decode("utf-8"), regime
