"""Task 15 core (preview): evidence retention with live pins and verified backups (A35, A40 preview variants).

Real inputs: Claude Code 2.1.301 payloads through the real adapter, ingestion
and typed reduction; claims admitted through the real extraction/review path
with recorded proposals; a typed declaration and a correction through the
guarded service as an operator; backups through the service and the real
guarded ``recalith`` child process with an explicitly provisioned fixture
token (``cli_scenarios``). Retention runs at controlled times ahead of every
capture (``retention_scenarios``). Named synthetic variants and synthetic store
states are labeled where used. The backup parts A36/A37 will build on (the
ledger in every backup, the latest ledger copy, verification before any
restore) are asserted here without claiming A36/A37: forgetting and
suppression-aware restore are Task 16.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path

import pytest

import retention_scenarios as rsn  # first: puts tests/, tests/integration and tests/platform on sys.path
import admission_scenarios as adm  # noqa: E402
import cli_scenarios as cli  # noqa: E402
import consolidation_scenarios as cs  # noqa: E402
import delivery_scenarios as ds  # noqa: E402
import lineage_scenarios as ls  # noqa: E402
import operation_scenarios as osc  # noqa: E402
import retrieval_scenarios as rs  # noqa: E402
import worker_scenarios as ws  # noqa: E402
import working_scenarios as wks  # noqa: E402
from recalith import service  # noqa: E402
from recalith.contracts.common import RecordRef, utc_now  # noqa: E402
from recalith.contracts.config import ProjectConfig  # noqa: E402
from recalith.contracts.health import RetentionSummary  # noqa: E402
from recalith.contracts.transfers import ArtifactManifest  # noqa: E402
from recalith.controller import apply, jobs  # noqa: E402
from recalith.errors import RecalithError  # noqa: E402
from recalith.fast import session  # noqa: E402
from recalith.privacy import retention  # noqa: E402
from recalith.storage import backup, db, failpoints  # noqa: E402

PINNED_ROLES = ("fail", "seq", "decision", "typed", "grep", "read", "echo", "write", "forward", "sub_result", "pass", "b_prompt", "b_result", "b_call", "b_start")
UNPINNED_ROLES = ("session_start", "reply_ok", "edit", "printf", "fail_start", "complete")
OWED_ROLES = ("long", "missing", "ls", "sleep")  # failures whose debounce trigger is still pending: their extraction will read them


@pytest.fixture(autouse=True)
def _disarm():
    failpoints.disarm_all()
    yield
    failpoints.disarm_all()


def sweep(p: wks.Project, now: str, **kw) -> retention.Report:
    with db.open_store(p.ctx) as store:
        return retention.sweep(store, p.ctx, now=now, **kw)


def available(p: wks.Project, *event_ids: str) -> bool:
    return all(rsn.payload_state(p, e) == ("available", True) for e in event_ids)


def expired(p: wks.Project, *event_ids: str) -> bool:
    return all(rsn.payload_state(p, e) == ("expired", False) for e in event_ids)


def direct_citations(p: wks.Project) -> set[str]:
    """Events a live claim head's current revision cites directly (an independent oracle for the pin closure's floor)."""
    with p.view() as v:
        return {r[0] for r in v.execute(
            "SELECT l.target_id FROM evidence_links l JOIN claim_heads h ON h.claim_id = l.owner_id AND h.revision = l.owner_revision "
            "WHERE l.owner_kind = 'claim' AND l.target_kind = 'event' AND h.status IN ('candidate', 'active', 'disputed')"
        ).fetchall()}


_ACTIONS: dict[str, object] = {}


def mid_action(p: wks.Project):
    """The real stored action of the failing ``test_mid`` call (read before its payload can expire)."""
    key = str(p.root)
    if key not in _ACTIONS:
        _ACTIONS[key] = rs.mid_action(p)
    return _ACTIONS[key]


def caution_ids(p: wks.Project) -> list[str]:
    packet = rs.service(p, rs.query(p, "pre_action", text="pytest -q test_mid.py", act=mid_action(p)))
    return [i.ref.id for i in packet.items if i.advice == "caution"]


# ---------------------------------------------------------------------------
# A35: age expiry of unpinned payloads only


def test_unreferenced_payloads_expire_at_180_days(tmp_path):
    """Day 181: every eligible unpinned payload expires, reported; pinned evidence, strength and guidance stay (A35).

    Owners over real payloads: an active failure lesson, fact, declaration and
    operator typed declaration, a candidate, a disputed claim (its support and
    its contradiction), two claims sharing one root, a forwarded subagent
    result, a claim citing an archived intermediary, and an open second host
    session's task. Both original sessions' tasks were completed (no task pin).
    """
    b = rsn.build(tmp_path)
    p, ev = b.p, b.events
    before = rsn.guidance(p)
    cautions = caution_ids(p)
    assert b.claims["lesson"] in cautions
    first = rsn.oldest(p)
    # Day 180 is not yet past the threshold (strictly older than 180 days expires): nothing changes.
    for moment in (rsn.plus(first, days=179), rsn.plus(first, days=180)):
        report = sweep(p, moment)
        assert report.expired == [] and rsn.states(p) == {e: "available" for e in rsn.states(p)}
    epoch = rsn.meta(p).guidance_epoch
    # One second into day 181 for the oldest event: it expires (it is unreferenced). Younger events may
    # expire in the same sweep when the fixture was captured within one second, so expiry is counted
    # across both sweeps below rather than per sweep.
    early = sweep(p, rsn.plus(first, days=180, seconds=1))
    assert ev["session_start"] in early.expired and expired(p, ev["session_start"])
    # Day 181 for every event.
    report = sweep(p, rsn.day(p, 181))
    assert available(p, *(ev[r] for r in PINNED_ROLES))
    assert available(p, *(ev[r] for r in OWED_ROLES))
    assert expired(p, *(ev[r] for r in UNPINNED_ROLES))
    assert direct_citations(p) <= {e for e, s in rsn.states(p).items() if s == "available"}
    # Exactly the age-eligible events outside the pin closure and owed work expired, and the report says so.
    with p.view() as v:
        pinned = retention.pinned_events(v)
    assert {e for e, s in rsn.states(p).items() if s == "expired"} == set(rsn.states(p)) - pinned
    assert not set(early.expired) & set(report.expired)  # each payload is reported once, by the sweep that expired it
    assert set(early.expired) | set(report.expired) == set(rsn.states(p)) - pinned
    # Retention alone lowers nothing: every claim keeps status, strength, freshness and availability; the lesson still cautions.
    assert rsn.guidance(p) == before
    assert caution_ids(p) == cautions
    assert rsn.meta(p).guidance_epoch > epoch  # expiry is serving-relevant (DATA_CONTRACTS §11)
    with p.view() as v:
        audits = v.execute("SELECT inputs FROM operations WHERE kind = 'retention_expiry' ORDER BY store_revision").fetchall()
    assert audits and sum(json.loads(a[0])["expired_count"] for a in audits) == sum(1 for s in rsn.states(p).values() if s == "expired")
    # Pins are storage, reported, never a fixed bound.
    summary = report.summary
    assert isinstance(summary, RetentionSummary)
    assert summary.pinned_payload_bytes > 0 and summary.unpinned_payload_bytes == 0
    assert summary.live_owner_count >= len([c for c, s in rsn.guidance(p).items() if s[0] in ("candidate", "active", "disputed")]) + 1
    assert summary.deferred_compaction_count == len(pinned & {e for e, s in rsn.states(p).items() if s == "available"})
    assert summary.free_disk_bytes is None or summary.free_disk_bytes > 0
    # An expired payload's metadata stays; its body is gone everywhere it was kept.
    shown = service.show(osc.context(p.root), ev["edit"])
    assert shown["body"]["payload"] is None and shown["body"]["kind"] == "tool_finished"
    # A second sweep at the same time is a no-op (idempotent, nothing silent).
    again = sweep(p, rsn.day(p, 181))
    assert again.expired == [] and rsn.guidance(p) == before


def test_worker_expires_at_day_181_and_republishes(tmp_path):
    """The real worker's retention step at day 181 (a clock ahead of every capture): the same outcome, views follow."""
    b = rsn.build(tmp_path)
    p, ev = b.p, b.events
    before = rsn.guidance(p)
    rs.publish(p)
    w = p.drain(clock=ws.FakeClock(rsn.day(p, 181)))
    assert w.last_error is None
    assert available(p, *(ev[r] for r in PINNED_ROLES)) and expired(p, *(ev[r] for r in UNPINNED_ROLES))
    assert available(p, *(ev[r] for r in OWED_ROLES))  # now the inputs of the extractions the debounce scheduled
    assert {c: s for c, s in rsn.guidance(p).items()} == before
    m = rsn.meta(p)
    with p.view() as v:
        state = v.execute("SELECT views_guidance_epoch, indexed_store_revision FROM projection_state").fetchone()
        last = json.loads(v.execute("SELECT report FROM retention_state").fetchone()[0])
    assert state[0] == m.guidance_epoch  # the views were republished after the expiry moved the epoch
    assert last["expired_count"] >= len(UNPINNED_ROLES) and last["summary"]["pinned_payload_bytes"] > 0
    hook = rs.hook(p, rs.query(p, "pre_action", text="pytest -q test_mid.py", act=mid_action(p)))
    # The session's own task is completed, so its view is missing (Task 11 keeps views for active tasks); none is stale.
    assert "view_stale" not in hook["packet"]["degraded_reasons"] and b.claims["lesson"] in rs.ids(hook["packet"])
    status = service.status(osc.context(p.root), inherited={})
    assert status["retention"]["last_sweep"]["expired_count"] == last["expired_count"]


def test_referenced_roots_do_not_expire(tmp_path):
    """Live owners pin their whole evidence chain: transitive, forwarded, shared and aliased roots, open and paused work (A35)."""
    b = rsn.build(tmp_path)
    p, ev, c = b.p, b.events, b.claims
    # The open host session's task becomes paused (24 h idle, real path): paused work still pins its range.
    p.drain(clock=ws.FakeClock(rsn.day(p, 2)))
    assert p.task(b.tasks["open"])["head_status"] == "paused"
    # An open episode (synthetic store state) pins its evidence even after its task's events are otherwise unpinned.
    episode = rsn.open_episode(p, b.tasks["lifecycle"], [ev["printf"]])
    # Two classes merged by a bridge event (synthetic adapter events, real normalization and ingestion): the old class
    # IDs become aliases; each claim's cited members stay pinned.
    ctx = osc.context(p.root)
    x = ls.experiment_envelope(ctx, "r-x", deps={}, coverage="unknown", argv=("pytest", "-q", "a.py"))
    y = ls.experiment_envelope(ctx, "r-y", deps={}, coverage="unknown", argv=("pytest", "-q", "b.py"), artifact=("file:report.xml", "3" * 64))
    ls.ingest(ctx, [x, y])
    p.drain()
    both = ls.propose(p, "Both suites pass.", [ls.link(x.event_id), ls.link(y.event_id)])
    bridge = ls.experiment_envelope(ctx, "r-b", deps={}, coverage="unknown", argv=("pytest", "-q", "a.py"), artifact=("file:report.xml", "3" * 64))
    ls.ingest(ctx, [bridge])
    p.drain()
    with p.view() as v:
        assert v.execute("SELECT COUNT(*) FROM root_aliases").fetchone()[0] >= 1
    # An unfinished job's input is owed (here an extraction naming the old "Reply OK." prompt).
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        job_id, _created = jobs.enqueue(txn, kind="extract_claims", input_refs=[RecordRef(kind="event", id=ev["reply_ok"], revision=1)], now=utc_now(), prompt_version="extract_claims@1")
    report = sweep(p, rsn.day(p, 400))
    pinned_now = [ev[r] for r in PINNED_ROLES] + [ev["printf"], x.event_id, y.event_id]
    assert available(p, *pinned_now), [rsn.payload_state(p, e) for e in pinned_now]
    assert expired(p, ev["edit"])  # cited by nothing
    assert set(report.expired).isdisjoint(pinned_now)
    assert available(p, ev["reply_ok"])  # the unfinished job's input
    # The chain behind each kind of owner, by role:
    with p.view() as v:
        pins = retention.pinned_events(v)
    assert ev["sub_result"] in pins and ev["forward"] in pins  # a forwarding result pins what it relays
    assert ev["pass"] in pins  # through the archived intermediary claim
    assert {ev["b_prompt"], ev["b_result"], ev["b_call"], ev["b_start"]} <= pins  # paused work: its revision and its open range
    assert ev["printf"] in pins  # the open episode
    assert rsn.claim_state(p, both)[0] == "candidate" and {x.event_id, y.event_id} <= pins
    # The unfinished job is cancelled: its input is released.
    with p.view() as v:
        assert ev["reply_ok"] in retention.pins(v).owed and available(p, ev["reply_ok"])
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        jobs.supersede(txn, jobs.get_job(txn, job_id), "test_cancelled")
    sweep(p, rsn.day(p, 400))
    assert expired(p, ev["reply_ok"])
    # A link's named roots stay pinned even when the cited record's own links are gone (synthetic store state: a
    # record link naming ``pass`` on a copy of the fact, and the intermediary's normalized links removed, as Task 16
    # will purge bodies).
    seeded = rs.seed(p, c["fact"], proposition="A seeded claim citing the intermediary.", supports=[ls.record_link("claim", c["intermediary"], osc.head_ref(p.root, "claim", c["intermediary"]).revision, roots=[ev["pass"]])])
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        txn.execute("DELETE FROM evidence_links WHERE owner_kind = 'claim' AND owner_id = ?", (c["intermediary"],))
        txn.mutated(serving_relevant=True)
    with p.view() as v:
        assert ev["pass"] in retention.pins(v).owned and seeded
    sweep(p, rsn.day(p, 400))
    assert available(p, ev["pass"])
    # The episode settles: its pin is released and the payload expires on the next sweep, with no new 180-day wait.
    rsn.settle_episode(p, episode)
    sweep(p, rsn.day(p, 400))
    assert expired(p, ev["printf"])
    assert available(p, *(ev[r] for r in PINNED_ROLES))


def test_last_owner_release_allows_expiry(tmp_path):
    """A shared root stays while any owner lives; the last release makes the already-old payload expire at once (A35)."""
    b = rsn.build(tmp_path)
    p, ev, c = b.p, b.events, b.claims
    late = rsn.day(p, 200)
    sweep(p, late)
    assert available(p, ev["write"], ev["pass"], ev["b_result"])
    # The first owner is retired by a guarded operator correction: the other owner still pins the shared root.
    head = cs.head(p, c["shared1"])
    service.submit_correction(osc.operator(p.root), c["shared1"], expected_revision=head["revision"], statement="new.txt was written by the Edit, not the Write.")
    assert rsn.claim_state(p, c["shared1"])[0] == "invalidated"
    sweep(p, late)
    assert available(p, ev["write"])
    # The last owner is archived by a recorded revalidation decision: the same sweep time now expires it.
    rsn.status_change(p, c["shared2"], "archived")
    report = sweep(p, late)
    assert ev["write"] in report.expired and expired(p, ev["write"])
    # Releasing the transitive owner releases its chain through the archived intermediary.
    rsn.status_change(p, c["transitive"], "archived")
    sweep(p, late)
    assert expired(p, ev["pass"])
    # Completing the open host session's task releases its working range.
    rsn.complete(p, rsn.SESSION_B, "Session B is complete.")
    sweep(p, rsn.day(p, 200))
    assert expired(p, ev["b_prompt"], ev["b_result"], ev["b_call"], ev["b_start"])
    # Nothing still owned was touched.
    assert available(p, ev["fail"], ev["seq"], ev["decision"], ev["typed"], ev["grep"], ev["read"], ev["echo"], ev["forward"], ev["sub_result"])


def test_pin_expiry_race_never_admits_missing_support(tmp_path):
    """The pin recheck is in the expiry transaction: a concurrent new reference wins, a stale one fails admission (A35)."""
    b = rsn.build(tmp_path)
    p, ev = b.p, b.events
    late = rsn.day(p, 181)
    edit = p.event("tool_finished", call="toolu_probe_0010")  # unreferenced, old enough at ``late``
    printf = p.event("tool_finished", call="toolu_probe_0013")  # likewise
    # (a) A reference committed between candidate selection and the expiry transaction pins the payload first.
    made: list[str] = []

    def concurrent_reference(_name: str) -> None:
        made.append(adm.created_claim(adm.extract(p, [osc.op("r", "propose_claim", adm.claim("The Edit rewrote new.txt.", subject="edit"), evidence=[adm.link(edit)])])))

    failpoints.arm(failpoints.RETENTION_AFTER_SELECT, concurrent_reference)
    report = sweep(p, late)
    assert made and ev["edit"] in report.repinned and ev["edit"] not in report.expired
    assert available(p, ev["edit"]) and rsn.claim_state(p, made[0]) == ("candidate", "weak", "current", "available")
    assert ev["printf"] in report.expired  # nothing referenced it in time
    # (b) Expiry commits first: a proposal prepared on the earlier read (stale) fails admission against the expired source.
    job = osc.leased(p.root, "extract_claims", input_refs=[RecordRef(kind="event", id=printf["id"], revision=1)], now=utc_now())
    response = osc.response([osc.op("e", "propose_claim", adm.claim("printf printed OK.", subject="printf"), evidence=[adm.link(printf)])], purpose="extract_claims")
    stale = osc.read_set(p.root)
    with db.open_store(p.ctx) as store:
        apply.persist_proposal(store, job, response, stale, now=utc_now())
    with db.open_store(p.ctx) as store:
        result = apply.apply_proposal(p.ctx, job, response, store=store, now=utc_now())
    assert [(d.outcome, d.reason_code) for d in result.decisions] == [("reject", "evidence_unavailable")]
    assert not [cid for cid in rsn.claim_ids(p) if cs.head(p, cid)["proposition"] == "printf printed OK."]
    # (c) Concurrent sweeps and references on separate connections: no live claim ever cites an expired payload.
    # Synthetic variants: six reruns of the real ``seq`` call, unreferenced and (at the sweep's time) old enough to expire.
    for i in range(6):
        adm.send_call(p, "toolu_probe_0005", f"race{i}")
    p.drain()
    candidates = [p.event("tool_finished", call=f"toolu_probe_0005_race{i}") for i in range(6)]
    late = rsn.day(p, 181)
    stop = threading.Event()
    errors: list[BaseException] = []
    sweeps = {"completed": 0, "busy": 0}

    def sweeper() -> None:
        # A sweep refused by the 250 ms busy timeout applies nothing, exactly like a refused extraction below;
        # on a stalled runner either writer can be refused (Windows CI, decision 0022). Anything else is a failure.
        try:
            while not stop.is_set():
                try:
                    sweep(p, late)
                    sweeps["completed"] += 1
                except RecalithError as exc:
                    if exc.code != "storage_failure":
                        raise
                    sweeps["busy"] += 1
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    thread = threading.Thread(target=sweeper)
    thread.start()
    try:
        for i, target in enumerate(candidates):
            try:
                adm.extract(p, [osc.op(f"c{i}", "propose_claim", adm.claim(f"Race claim {i}.", subject=f"race{i}"), evidence=[adm.link(target)])])
            except RecalithError as exc:
                assert exc.code == "storage_failure", exc  # busy: nothing applied
    finally:
        stop.set()
        thread.join(30)
    assert not thread.is_alive() and not errors, errors
    assert sweeps["completed"] >= 1, sweeps  # the race was exercised by at least one committed sweep
    sweep(p, late)
    live = {e: s for e, s in rsn.states(p).items()}
    with p.view() as v:
        cited = v.execute(
            "SELECT l.target_id FROM evidence_links l JOIN claim_heads h ON h.claim_id = l.owner_id AND h.revision = l.owner_revision "
            "WHERE l.owner_kind = 'claim' AND l.target_kind = 'event' AND l.relation = 'supports' AND h.status IN ('candidate', 'active', 'disputed')"
        ).fetchall()
    assert all(live[e] == "available" for (e,) in cited), [e for (e,) in cited if live[e] != "available"]


def test_forget_overrides_pin(tmp_path):
    """The override interface Task 16's forgetting calls: a pinned payload is released; lost support downgrades honestly.

    **Synthetic caller until Task 16**: the test calls
    ``retention.release_payloads`` in a store transaction the way
    ``apply_forget`` will; tombstones, derivative purge and quarantine are
    Task 16. What is asserted is the Task 15 contract: pins never block the
    override, and every live claim that lost support is downgraded in the same
    transaction (strength from the support that is left, availability, a
    ``support_lost`` recheck, a revalidation job, the guidance epoch).
    """
    b = rsn.build(tmp_path, open_work=False)
    p, ev, c = b.p, b.events, b.claims
    mid_action(p)  # cached before the payload it reads is released
    fail = cs.failure(p)
    # A claim with two independent supports: losing one leaves it supported by the other.
    two = cs.fact(p, "seq and grep ran in the fixture.", subject="two", evidence=p.event("tool_finished", call="toolu_probe_0005"))
    adm_result = ls.attach(p, two, [adm.link(p.event("tool_finished", call="toolu_probe_0006"))])
    assert adm_result.decisions[0].outcome == "apply"
    with p.view() as v:
        assert ev["fail"] in retention.pinned_events(v)
    m0 = rsn.meta(p)
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        lost = retention.release_payloads(txn, p.ctx, [ev["fail"], ev["seq"]], now=utc_now())
    m1 = rsn.meta(p)
    assert (m1.store_revision, m1.guidance_epoch) == (m0.store_revision + 1, m0.guidance_epoch + 1)  # one transaction, epoch advanced
    assert rsn.payload_state(p, ev["fail"]) == ("forgotten", False) and rsn.payload_state(p, ev["seq"]) == ("forgotten", False)
    assert {r.id for r in lost} >= {c["lesson"], c["fact"], two}
    assert rsn.claim_state(p, c["lesson"]) == ("active", "weak", "needs_revalidation", "redacted")
    assert rsn.claim_state(p, c["fact"]) == ("active", "weak", "needs_revalidation", "redacted")
    assert rsn.claim_state(p, two) == ("active", "supported", "needs_revalidation", "available")  # one class left
    reasons = {(r["claim_id"], r["reason"], r["state"]) for r in cs.rechecks(p)}
    assert {(c["lesson"], "support_lost", "pending"), (c["fact"], "support_lost", "pending")} <= reasons
    assert [j for j in cs.jobs_of(p, "revalidate", c["lesson"], states=("pending", "waiting_budget"))]
    # Guidance without support is withdrawn from both compilers and the views.
    assert c["lesson"] not in caution_ids(p) and c["lesson"] not in rs.ids(rs.service(p, rs.query(p, "manual", text="test_mid fixture")))
    rs.publish(p)
    hook = rs.hook(p, rs.query(p, "pre_action", text="pytest -q test_mid.py", act=mid_action(p)))
    assert c["lesson"] not in rs.ids(hook["packet"])
    # A plain keep of the support_lost recheck never raises strength from support that is gone.
    (job,) = cs.jobs_of(p, "revalidate", c["fact"], states=("pending", "waiting_budget"))
    cs.run_revalidation(p, job.job_id, cs.keep)
    assert rsn.claim_state(p, c["fact"])[1] == "weak" and rsn.claim_state(p, c["fact"])[3] == "redacted"
    # A new reference to a released payload fails admission, directly or through a record whose chain needs it.
    again = adm.extract(p, [osc.op("g", "propose_claim", adm.claim("test_mid fails again.", subject="again"), evidence=[adm.link(fail)])])
    assert [(d.outcome, d.reason_code) for d in again.decisions] == [("reject", "evidence_unavailable")]
    revision = osc.head_ref(p.root, "claim", c["lesson"]).revision
    through = adm.extract(p, [osc.op("h", "propose_claim", adm.claim("The fixture lesson still holds.", subject="through"), evidence=[ls.record_link("claim", c["lesson"], revision, roots=[ev["fail"]])])])
    assert [(d.outcome, d.reason_code) for d in through.decisions] == [("reject", "evidence_unavailable")]


def test_lost_support_after_undo_is_downgraded(tmp_path):
    """Undo cannot revive guidance on expired support: the reactivated claim is downgraded in the undo's transaction."""
    b = rsn.build(tmp_path, open_work=False)
    p, ev, c = b.p, b.events, b.claims
    rsn.status_change(p, c["fact"], "archived")
    with p.view() as v:
        op = v.execute("SELECT operation_id FROM operations WHERE kind = 'change_claim_status' ORDER BY store_revision DESC LIMIT 1").fetchone()[0]
    sweep(p, rsn.day(p, 181))
    assert expired(p, ev["seq"])
    operator_ctx = osc.operator(p.root)
    preview = apply.preview_undo(operator_ctx, op)
    epoch = rsn.meta(p).guidance_epoch
    apply.apply_undo(operator_ctx, op, preview_digest=preview.preview_digest)
    assert rsn.claim_state(p, c["fact"]) == ("active", "weak", "needs_revalidation", "expired")
    assert rsn.meta(p).guidance_epoch > epoch
    assert c["fact"] not in rs.ids(rs.service(p, rs.query(p, "manual", text="seq prints lines")))


def test_replayed_source_after_expiry_does_not_resurrect(tmp_path):
    """Review focus 1: replaying expired source events adds no payload, root, support or claim."""
    b = rsn.build(tmp_path, open_work=False)
    p, ev = b.p, b.events
    sweep(p, rsn.day(p, 181))
    assert expired(p, ev["edit"], ev["reply_ok"])
    with p.view() as v:
        before = (v.execute("SELECT COUNT(*) FROM events").fetchone()[0], v.execute("SELECT COUNT(*) FROM root_event_members").fetchone()[0],
                  v.execute("SELECT COUNT(*) FROM claim_revisions").fetchone()[0], v.execute("SELECT COUNT(*) FROM source_conflicts").fetchone()[0])
    p.scenario("lifecycle")  # the same real hook records again
    p.drain()
    with p.view() as v:
        after = (v.execute("SELECT COUNT(*) FROM events").fetchone()[0], v.execute("SELECT COUNT(*) FROM root_event_members").fetchone()[0],
                 v.execute("SELECT COUNT(*) FROM claim_revisions").fetchone()[0], v.execute("SELECT COUNT(*) FROM source_conflicts").fetchone()[0])
    assert after == before
    assert expired(p, ev["edit"], ev["reply_ok"])
    # A replay with changed content under the expired event's source key (synthetic variant) is a source conflict,
    # never a resurrection; its body is about a payload that is gone and goes at the next sweep.
    changed = wks.variant(wks.record("lifecycle", "PostToolUse", "toolu_probe_0010"), replace={"new.txt": "new-changed.txt"})
    p.send(changed)
    p.drain()
    assert expired(p, ev["edit"])
    with p.view() as v:
        bodies = v.execute("SELECT COUNT(*), SUM(scrubbed_payload IS NOT NULL) FROM source_conflicts WHERE original_event_id = ?", (ev["edit"],)).fetchone()
    assert tuple(bodies) == (1, 1)  # recorded, with its scrubbed body
    sweep(p, rsn.day(p, 181))
    with p.view() as v:
        assert v.execute("SELECT COUNT(*) FROM source_conflicts WHERE original_event_id = ? AND scrubbed_payload IS NOT NULL", (ev["edit"],)).fetchone()[0] == 0
        assert v.execute("SELECT COUNT(*) FROM root_event_members").fetchone()[0] == before[1]


# ---------------------------------------------------------------------------
# Receipts, outcome links and scratch follow retention


def test_receipts_and_outcome_links_follow_delivery_retention(tmp_path):
    """Delivery metadata (receipt rows, outcome links, receipt payloads) keeps 90 days; the lesson it delivered stays."""
    p, ids = ds.project(tmp_path)
    sid = p.sid(ds.fresh_session(1))
    session_b = ds.fresh_session(1)
    ds.hook(p, ds.in_session(ds.record("SessionStart"), session_b))
    pre, post = ds.call_records(ds.MID, "r1", session=session_b)
    _reply, out = ds.hook(p, pre)
    assert out
    ds.hook(p, post)
    ds.ingest(p)
    p.drain()
    rows = ds.deliveries(p, sid)
    assert rows and ds.links(p)
    with p.view() as v:
        receipts = [r[0] for r in v.execute("SELECT event_id FROM events WHERE kind = 'memory_delivered'").fetchall()]
        generated = v.execute("SELECT MAX(generated_at) FROM deliveries").fetchone()[0]
        newest_receipt = v.execute("SELECT MAX(recorded_at) FROM events WHERE kind = 'memory_delivered'").fetchone()[0]
    generated = max(generated, newest_receipt)
    assert receipts
    sweep(p, rsn.plus(generated, days=89))
    assert ds.deliveries(p, sid) and available(p, *receipts)
    report = sweep(p, rsn.plus(generated, days=91))
    assert ds.deliveries(p, sid) == [] and ds.links(p) == []
    assert expired(p, *receipts)
    assert report.deliveries_removed == len(rows)
    assert rsn.claim_state(p, ids["lesson"])[:2] == ("active", "supported")


def test_abandoned_scratch_is_settled_before_pruning(tmp_path):
    """A dead hook's reservation in abandoned scratch is settled (uncertain, still charged) before the file goes."""
    p, ids = ds.project(tmp_path)
    session_b = ds.fresh_session(2)
    sid = p.sid(session_b)
    ds.hook(p, ds.in_session(ds.record("SessionStart"), session_b))
    pre, _post = ds.call_records(ds.MID, "k1", session=session_b)
    killed = ds.killed_process(p, pre, tmp_path, failpoints.DELIVERY_AFTER_EMIT)
    assert killed.returncode == failpoints.KILL_STATUS
    scratch = ds.scratch(p, sid)
    assert scratch and [e["state"] for e in scratch["entries"]] == ["reserved"]
    path = Path(session.scratch_path(p.root, sid))
    old = time.time() - 25 * 3600
    os.utime(path, (old, old))
    # The hook-side prune never drops scratch whose receipts are still owed.
    session.prune_abandoned(p.root)
    assert path.exists()
    # The worker's retention step (after its ingestion, which registers the session) settles it, then prunes it.
    ds.ingest(p)
    with db.open_store(p.ctx) as store:
        retention.prune_scratch(store, p.ctx)
    assert not path.exists()
    ds.ingest(p)
    assert [r["state"] for r in ds.deliveries(p, sid)] == ["uncertain"]


# ---------------------------------------------------------------------------
# Expiry and lost support leave projections and delivery


def test_expired_support_leaves_projections_and_packets(tmp_path):
    """Views are republished on the expiry epoch; stale views are not served; fallback rows and packets omit lost support."""
    p, ids = ds.project(tmp_path)
    lesson = ids["lesson"]
    q = rs.query(p, "pre_action", text="pytest -q test_mid.py", act=mid_action(p))
    assert lesson in rs.ids(rs.hook(p, q)["packet"])
    fail = cs.failure(p)["id"]
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        retention.release_payloads(txn, p.ctx, [fail], now=utc_now())  # synthetic caller until Task 16 (see test_forget_overrides_pin)
    stale = rs.hook(p, q)
    assert stale["source"] != "view" and lesson not in rs.ids(stale["packet"])  # old views are not served; fallback rows are filtered
    assert lesson not in rs.ids(rs.service(p, q))
    rs.publish(p)
    fresh = rs.hook(p, q)
    assert fresh["source"] == "view" and lesson not in rs.ids(fresh["packet"])
    with p.view() as v:
        bodies = " ".join(r[0] for r in v.execute("SELECT body FROM context_views").fetchall())
    assert lesson not in bodies


# ---------------------------------------------------------------------------
# Backups (A40 preview; the backup parts A36/A37 rely on)


def test_backup_is_consistent(tmp_path):
    """A snapshot under concurrent writes is one consistent store revision, verified, with digests in the manifest."""
    b = rsn.build(tmp_path, open_work=False)
    p = b.p
    template = b.claims["fact"]
    stop = threading.Event()
    written: list[int] = []
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            while not stop.is_set():
                rs.seed(p, template, proposition=f"Concurrent claim {len(written)}.")
                written.append(1)
                # Writes keep landing during the backup, but a loop that re-takes the lock at once can starve the
                # backup's own short record write past the busy timeout on a slow runner (CI Windows); the worker,
                # the store's real writer, never writes back to back like that.
                time.sleep(0.005)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    # A connection held open (as the running worker holds one) keeps recent commits in the WAL, unmerged into the
    # main database file: only the backup interface sees them; a plain file copy would not.
    holder = db.open_store(p.ctx)
    with holder.read() as view:
        view.execute("SELECT COUNT(*) FROM claim_heads").fetchone()
    thread = threading.Thread(target=writer)
    thread.start()
    try:
        while len(written) < 3:
            time.sleep(0.01)
        before_backup = rsn.meta(p).store_revision
        result = backup.create(p.ctx, tmp_path / "backup-1")
        target = len(written) + 2
        while len(written) < target:
            time.sleep(0.01)
    finally:
        stop.set()
        thread.join(30)
        holder.close()
    assert not errors, errors
    location = Path(result.location)
    verified = backup.verify(location, expected_digest=result.manifest_digest, ctx=p.ctx)
    manifest = verified.manifest
    assert isinstance(manifest, ArtifactManifest) and manifest.artifact_type == "backup"
    assert manifest.file_digests == {name: rsn.file_digest(location / name) for name in ("ledger.json", "memory.sqlite")}
    assert result.manifest_digest == rsn.file_digest(location / "manifest.json")
    snap = location / "memory.sqlite"
    (revision,) = rsn.snapshot_rows(snap, "SELECT store_revision FROM installation_meta")[0]
    assert revision >= before_backup  # every commit before the backup started is in it
    assert rsn.snapshot_rows(snap, "PRAGMA integrity_check") == [("ok",)] and rsn.snapshot_rows(snap, "PRAGMA foreign_key_check") == []
    assert rsn.snapshot_rows(snap, "PRAGMA journal_mode")[0][0].lower() != "wal"  # self-contained file
    # The snapshot is exactly the live store's content up to its revision: nothing later, nothing missing.
    snap_claims = sorted(rsn.snapshot_rows(snap, "SELECT claim_id, revision, body FROM claim_revisions"))
    with p.view() as v:
        live_claims = sorted(v.execute("SELECT claim_id, revision, body FROM claim_revisions WHERE created_store_revision <= ?", (revision,)).fetchall())
        assert v.execute("SELECT COUNT(*) FROM claim_revisions WHERE created_store_revision > ?", (revision,)).fetchone()[0] >= 2  # writes went on
    assert snap_claims == live_claims
    assert max(r[0] for r in rsn.snapshot_rows(snap, "SELECT created_store_revision FROM claim_revisions")) <= revision
    with p.view() as v:
        row = v.execute("SELECT state, location, manifest_digest, tombstone_epoch FROM backups WHERE backup_id = ?", (manifest.artifact_id,)).fetchone()
    assert (row[0], Path(row[1]).resolve(), row[2], row[3]) == ("verified", location.resolve(), result.manifest_digest, manifest.tombstone_epoch)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits; Windows relies on the user profile's ACLs")
def test_backup_files_are_private(tmp_path):
    """A backup directory is owner-only (0700) and its files owner-read/write (0600), like the store it copies."""
    p = cs.project(tmp_path, "private-backup")
    result = backup.create(p.ctx, tmp_path / "private")
    location = Path(result.location)
    assert location.stat().st_mode & 0o777 == 0o700
    assert {name: (location / name).stat().st_mode & 0o777 for name in ("manifest.json", "ledger.json", "memory.sqlite")} == dict.fromkeys(("manifest.json", "ledger.json", "memory.sqlite"), 0o600)
    latest = p.root / backup.LATEST_LEDGER
    assert latest.stat().st_mode & 0o077 == 0


def test_backup_contains_current_ledger(tmp_path):
    """Every backup carries the tombstone ledger of its snapshot; the latest ledger copy is always the newest (A36/A37 parts).

    Tombstones are synthetic store states (content-free rows and a new epoch;
    Task 16 owns forgetting and suppression-aware restore).
    """
    b = rsn.build(tmp_path, open_work=False)
    p = b.p
    epoch = rsn.tombstone(p, [b.claims["candidate"]])
    first = backup.create(p.ctx, tmp_path / "with-ledger")
    location = Path(first.location)
    ledger = json.loads((location / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["tombstone_epoch"] == epoch == first.manifest.tombstone_epoch
    assert [t["target_ids"] for t in ledger["tombstones"]] == [[b.claims["candidate"]]]
    assert "proposition" not in json.dumps(ledger)  # content-free
    snap = rsn.snapshot_rows(location / "memory.sqlite", "SELECT tombstone_id, epoch FROM tombstones")
    assert sorted((t["tombstone_id"], t["epoch"]) for t in ledger["tombstones"]) == sorted(snap)
    latest = backup.read_latest_ledger(p.root)
    assert latest is not None and latest["tombstone_epoch"] == epoch and latest["tombstones"] == ledger["tombstones"]
    # A newer tombstone after the backup: the old backup keeps its own ledger, the latest copy follows the store.
    newer = rsn.tombstone(p, [b.claims["typed"]])
    with db.open_store(p.ctx) as store:
        retention.run(store, p.ctx, ProjectConfig.defaults_for(p.ctx.project_id), now=rsn.day(p, 1))
    latest = backup.read_latest_ledger(p.root)
    assert latest["tombstone_epoch"] == newer > epoch and len(latest["tombstones"]) == 2
    assert json.loads((location / "ledger.json").read_text(encoding="utf-8"))["tombstone_epoch"] == epoch
    second = backup.create(p.ctx, tmp_path / "newer")
    assert second.manifest.tombstone_epoch == newer


def test_guarded_cli_backup_verifies_and_corrupt_copy_is_rejected(tmp_path):
    """``recalith backup`` through the real guarded CLI; ``restore`` verifies first, rejects corrupt copies (A40), restores a good one."""
    p = cs.project(tmp_path, "cli-retention")  # the real lifecycle session, reduced
    cs.lesson(p)
    root = p.root
    tok = tmp_path / "operator.token"
    cli.register(root, cli.token(tok))
    out = tmp_path / "cli-backup"
    made = cli.cli(root, "--json", "--operator-token-file", str(tok), "backup", "--output", str(out))
    assert made.code == 0, made.stdout + made.stderr
    result = made.obj["result"]
    manifest = ArtifactManifest.model_validate(result["manifest"])
    assert Path(result["location"]).resolve() == out.resolve() and manifest.installation_id == p.ctx.installation_id
    assert backup.verify(out, expected_digest=result["manifest_digest"], ctx=p.ctx).manifest == manifest
    # A marked caller is refused before any effect (A73 guard; nothing written).
    refused = cli.cli(root, "--json", "--operator-token-file", str(tok), "backup", "--output", str(tmp_path / "marked"), env=cli.marked_env("CLAUDECODE"))
    assert refused.code == 6 and not (tmp_path / "marked").exists()
    # An existing output is never overwritten.
    again = cli.cli(root, "--json", "--operator-token-file", str(tok), "backup", "--output", str(out))
    assert again.code == 2 and again.obj["error"] == "invalid_schema"
    # Restore verifies before anything else: corrupt copies are rejected and the live store is never touched.
    before = (cli.tree(root), cli.store_rows(root))
    cases = {
        "backup_file_digest_mismatch": rsn.corrupt_copy(out, tmp_path / "corrupt-db"),
        "backup_file_digest_mismatch ": rsn.corrupt_copy(out, tmp_path / "corrupt-ledger", member="ledger.json", offset=5),
        "backup_digest_mismatch": rsn.corrupt_copy(out, tmp_path / "corrupt-manifest", member="manifest.json", offset=3),
    }
    extra = Path(shutil.copytree(out, tmp_path / "extra-file"))
    (extra / "notes.txt").write_text("not part of a backup", encoding="utf-8")
    cases["backup_unexpected_file"] = extra
    missing = Path(shutil.copytree(out, tmp_path / "missing-file"))
    (missing / "ledger.json").unlink()
    cases["backup_missing_file"] = missing
    for reason, path in cases.items():
        bad = cli.cli(root, "--json", "--operator-token-file", str(tok), "restore", str(path), "--expected-digest", result["manifest_digest"])
        assert bad.code == 2 and bad.obj["error"] == "invalid_schema" and reason.strip() in bad.obj["message"], (reason, bad.stdout)
    # A resealed copy whose database pages were damaged passes the digests but fails the snapshot integrity check.
    resealed = rsn.corrupt_copy(out, tmp_path / "resealed", offset=4096)  # page 2's b-tree page header
    digest = rsn.reseal(resealed)
    bad = cli.cli(root, "--json", "--operator-token-file", str(tok), "restore", str(resealed), "--expected-digest", digest)
    assert bad.code == 2 and ("backup_integrity_failed" in bad.obj["message"] or "backup_snapshot_unreadable" in bad.obj["message"]), bad.stdout
    wrong = cli.cli(root, "--json", "--operator-token-file", str(tok), "restore", str(out), "--expected-digest", "0" * 64)
    assert wrong.code == 2 and "backup_digest_mismatch" in wrong.obj["message"]
    assert (cli.tree(root), cli.store_rows(root)) == before  # the live store is never touched
    # The verified backup restores (Task 16: suppression-aware restore; test_restore owns its behavior).
    good = cli.cli(root, "--json", "--operator-token-file", str(tok), "restore", str(out), "--expected-digest", result["manifest_digest"])
    assert good.code == 0 and good.obj["result"]["restored_revision"] >= 1, good.stdout + good.stderr


def test_unsupported_schema_is_refused(tmp_path):
    """A backup claiming another schema is rejected; a live store of another schema refuses the backup write (A40)."""
    b = rsn.build(tmp_path, open_work=False)
    p = b.p
    good = backup.create(p.ctx, tmp_path / "good")
    forged = tmp_path / "forged"
    digest = rsn.forge_schema(Path(good.location), forged, db.SCHEMA_VERSION + 1)
    with pytest.raises(RecalithError) as refused:
        backup.verify(forged, expected_digest=digest, ctx=p.ctx)
    assert refused.value.code == "invalid_schema" and "backup_schema_unsupported" in refused.value.message
    older = tmp_path / "older"
    digest = rsn.forge_schema(Path(good.location), older, db.SCHEMA_VERSION - 1)
    with pytest.raises(RecalithError) as refused:
        backup.verify(older, expected_digest=digest, ctx=p.ctx)
    assert "backup_schema_unsupported" in refused.value.message
    # A live store whose schema is not this engine's is never written, not even by a backup's bookkeeping.
    path = p.root / ".recalith" / db.STATE_DB
    conn = sqlite3.connect(path)
    try:
        conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION - 1}")
        conn.execute("UPDATE installation_meta SET schema_version = ?", (db.SCHEMA_VERSION - 1,))
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(RecalithError) as refused:
        backup.create(p.ctx, tmp_path / "from-old-schema")
    assert refused.value.code == "invalid_schema" and not (tmp_path / "from-old-schema").exists()


def test_backup_retention_is_bounded(tmp_path):
    """Private backups older than 30 days are deleted (files first, then the row); younger ones and foreign data stay."""
    b = rsn.build(tmp_path, open_work=False)
    p = b.p
    now = utc_now()
    old = backup.create(p.ctx, tmp_path / "old", now=rsn.plus(now, days=-31))
    young = backup.create(p.ctx, tmp_path / "young", now=rsn.plus(now, days=-29))
    foreign = backup.create(p.ctx, tmp_path / "foreign", now=rsn.plus(now, days=-40))
    # Someone replaced the third location with unrelated data: it is never deleted on the row's word alone.
    shutil.rmtree(foreign.location)
    Path(foreign.location).mkdir()
    (Path(foreign.location) / "notes.txt").write_text("unrelated", encoding="utf-8")
    with db.open_store(p.ctx) as store:
        deleted = backup.prune(store, p.ctx, now=now, days=30)
    assert deleted == [old.manifest.artifact_id]
    assert not Path(old.location).exists() and Path(young.location).exists() and (Path(foreign.location) / "notes.txt").exists()
    with p.view() as v:
        states = dict(v.execute("SELECT backup_id, state FROM backups").fetchall())
    assert states[old.manifest.artifact_id] == "deleted" and states[young.manifest.artifact_id] == "verified"
    assert backup.verify(Path(young.location), expected_digest=young.manifest_digest, ctx=p.ctx)


def test_interrupted_backup_never_verifies_and_is_recovered(tmp_path):
    """A backup that fails before publication leaves nothing that verifies at its output; recovery removes the staging."""
    b = rsn.build(tmp_path, open_work=False)
    p = b.p

    def boom(_name: str) -> None:
        raise OSError("injected failure")

    for point in (failpoints.BACKUP_AFTER_SNAPSHOT, failpoints.BACKUP_AFTER_MANIFEST):
        target = tmp_path / f"out-{point}"
        failpoints.arm(point, boom)
        with pytest.raises(RecalithError) as failed:
            backup.create(p.ctx, target)
        assert failed.value.code == "storage_failure"
        assert not target.exists()
        with db.open_store(p.ctx) as store:
            backup.recover(p.ctx, store)
        assert [x for x in tmp_path.iterdir() if ".partial" in x.name] == []
        with p.view() as v:
            assert v.execute("SELECT COUNT(*) FROM backups").fetchone()[0] == 0
    # Published but not yet recorded: recovery verifies and records it.
    target = tmp_path / "published"
    failpoints.arm(failpoints.BACKUP_AFTER_PUBLISH, boom)
    with pytest.raises(RecalithError):
        backup.create(p.ctx, target)
    with db.open_store(p.ctx) as store:
        recovered = backup.recover(p.ctx, store)
    assert target.exists() and recovered
    with p.view() as v:
        assert [(state, Path(loc).resolve()) for state, loc in v.execute("SELECT state, location FROM backups").fetchall()] == [("verified", target.resolve())]


# ---------------------------------------------------------------------------
# Derived revision bodies (SYSTEM_SPEC §11: closed task history 90 days, episode bodies 180 days after task closure;
# never over a live pin). Open since Task 15; preview requires it (the §11 defaults apply to both profiles).


def _closed_task(tmp_path, name: str = "aging"):
    """The real lifecycle session's task, completed by a recorded proposal citing the user's statement."""
    p = cs.project(tmp_path, name)
    task_id = rsn.complete(p, wks.LIFECYCLE_SESSION, rsn.COMPLETE)
    with p.view() as v:
        closed_at = json.loads(v.execute("SELECT body FROM task_revisions WHERE task_id = ? AND status = 'completed' ORDER BY revision LIMIT 1", (task_id,)).fetchone()[0])["updated_at"]
    return p, task_id, closed_at


def _bodies(p, kind: str, record_id: str) -> list[bool]:
    table, key = {"task": ("task_revisions", "task_id"), "episode": ("episode_revisions", "episode_id")}[kind]
    with p.view() as v:
        return [row[0] is not None for row in v.execute(f"SELECT body FROM {table} WHERE {key} = ? ORDER BY revision", (record_id,)).fetchall()]  # noqa: S608


def _settled_episode(p, task_id: str) -> str:
    """A settled episode of ``task_id`` (synthetic store state, as ``retention_scenarios.open_episode``)."""
    events = [p.event("tool_finished", call=cs.MID)["id"]]
    episode_id = rsn.open_episode(p, task_id, events)
    rsn.settle_episode(p, episode_id)
    return episode_id


def _indexed(p, record_id: str) -> int:
    with p.view() as v:
        return v.execute("SELECT COUNT(*) FROM retrieval_docs WHERE record_id = ?", (record_id,)).fetchone()[0] + v.execute("SELECT COUNT(*) FROM lexical_index WHERE record_id = ?", (record_id,)).fetchone()[0]


def test_closed_task_history_ages_after_90_days(tmp_path):
    p, task_id, closed_at = _closed_task(tmp_path)
    rs.publish(p)
    assert all(_bodies(p, "task", task_id))
    epoch = rsn.meta(p).guidance_epoch
    kept = sweep(p, rsn.plus(closed_at, days=90))  # day 90 exactly is retained
    assert kept.records_aged == {"task": 0, "episode": 0} and all(_bodies(p, "task", task_id))
    aged = sweep(p, rsn.plus(closed_at, days=90, seconds=1))
    revisions = len(_bodies(p, "task", task_id))
    assert aged.records_aged["task"] == revisions and not any(_bodies(p, "task", task_id))
    with p.view() as v:
        head = v.execute("SELECT status FROM task_heads WHERE task_id = ?", (task_id,)).fetchone()[0]
        audit = v.execute("SELECT inputs FROM operations WHERE kind = 'retention_record_aging'").fetchall()
        links = v.execute("SELECT COUNT(*) FROM evidence_links WHERE owner_kind = 'task' AND owner_id = ?", (task_id,)).fetchone()[0]
    assert head == "completed" and links == 0 and _indexed(p, task_id) == 0  # the head stays; its text, links and index rows go
    assert len(audit) == 1 and "fixture" not in audit[0][0].lower() and task_id in audit[0][0]  # content-free: identifiers and counts
    assert rsn.meta(p).guidance_epoch > epoch
    shown = service.show(osc.context(p.root), task_id)
    assert shown["body"] is None and shown["content"] == "expired"
    assert sweep(p, rsn.plus(closed_at, days=91)).records_aged == {"task": 0, "episode": 0}  # idempotent


def test_sweep_takes_no_aging_transaction_when_nothing_can_age(tmp_path, monkeypatch):
    """The candidates come from the read snapshot; the write lock (and its pin closure) is taken only when a body can age."""
    p, task_id, closed_at = _closed_task(tmp_path)
    calls: list[str] = []
    real = retention.age_records
    monkeypatch.setattr(retention, "age_records", lambda *a, **kw: (calls.append("aging"), real(*a, **kw))[1])
    sweep(p, rsn.plus(closed_at, days=90))  # not yet past the cutoff
    assert calls == []
    sweep(p, rsn.plus(closed_at, days=90, seconds=1))
    assert calls == ["aging"] and not any(_bodies(p, "task", task_id))
    sweep(p, rsn.plus(closed_at, days=91))  # everything already aged
    assert calls == ["aging"]


def test_episode_bodies_age_180_days_after_task_closure(tmp_path):
    p, task_id, closed_at = _closed_task(tmp_path)
    episode_id = _settled_episode(p, task_id)
    # Another host session's task stays active: its settled episode is kept whatever its age.
    p.send(wks.variant(wks.record("lifecycle", "SessionStart"), session=rsn.SESSION_B))
    p.send(wks.variant(wks.record("lifecycle", "UserPromptSubmit"), prompt="Session B: keep working.", session=rsn.SESSION_B))
    p.drain()
    open_task = p.task_of(p.event("user_message", text="Session B: keep")["id"])
    other = _settled_episode(p, open_task)
    sweep(p, rsn.plus(closed_at, days=120))  # the task's own history is gone by now: closure comes from its operations
    assert not any(_bodies(p, "task", task_id)) and all(_bodies(p, "episode", episode_id))
    assert sweep(p, rsn.plus(closed_at, days=180)).records_aged["episode"] == 0 and all(_bodies(p, "episode", episode_id))
    aged = sweep(p, rsn.plus(closed_at, days=180, seconds=1))
    assert aged.records_aged["episode"] == len(_bodies(p, "episode", episode_id)) and not any(_bodies(p, "episode", episode_id))
    with p.view() as v:
        assert v.execute("SELECT state FROM episode_heads WHERE episode_id = ?", (episode_id,)).fetchone()[0] == "settled"
    assert all(_bodies(p, "episode", other)) and all(_bodies(p, "task", open_task))


def test_live_claims_pin_the_record_revisions_they_cite(tmp_path):
    p, task_id, closed_at = _closed_task(tmp_path)
    episode_id = _settled_episode(p, task_id)
    task_revision = osc.head_ref(p.root, "task", task_id).revision
    episode_revision = osc.head_ref(p.root, "episode", episode_id).revision
    on_episode = rsn.record_claim(p, "The fixture lifecycle episode settled.", "episode", episode_id, [], subject="episode")
    on_task = rsn.record_claim(p, "The fixture lifecycle task was completed.", "task", task_id, [], subject="task")
    sweep(p, rsn.plus(closed_at, days=181))
    with p.view() as v:
        def body(table, key, rid, rev):
            return v.execute(f"SELECT body IS NOT NULL FROM {table} WHERE {key} = ? AND revision = ?", (rid, rev)).fetchone()[0]  # noqa: S608
        assert body("task_revisions", "task_id", task_id, task_revision) and body("episode_revisions", "episode_id", episode_id, episode_revision)
    assert _bodies(p, "task", task_id).count(True) == 1  # only the cited revision of the history survives
    rsn.status_change(p, on_episode, "archived")
    rsn.status_change(p, on_task, "archived")
    released = sweep(p, rsn.plus(closed_at, days=182))
    assert released.records_aged == {"task": 1, "episode": 1}
    assert not any(_bodies(p, "task", task_id)) and not any(_bodies(p, "episode", episode_id))


def test_undo_over_an_aged_body_is_a_conflict(tmp_path):
    p, task_id, closed_at = _closed_task(tmp_path)
    with p.view() as v:
        completion = v.execute("SELECT operation_id FROM operations WHERE kind = 'update_task' AND local_ref = 'done'").fetchone()[0]
    sweep(p, rsn.plus(closed_at, days=91))
    preview = apply.preview_undo(osc.operator(p.root), completion)
    assert preview.state == "conflicted" and {c.reason for c in preview.conflicts} == {"body_unavailable"}
    with pytest.raises(RecalithError) as refused:
        apply.apply_undo(osc.operator(p.root), completion, preview_digest=preview.preview_digest)
    assert refused.value.code == "revision_conflict"
    assert not any(_bodies(p, "task", task_id))  # nothing is resurrected


def test_late_event_of_an_aged_task_is_reduced_without_reviving_it(tmp_path):
    p, task_id, closed_at = _closed_task(tmp_path)
    sweep(p, rsn.plus(closed_at, days=91))
    p.send(wks.variant(wks.record("lifecycle", "UserPromptSubmit"), prompt="One more thing after the task closed.", session=wks.LIFECYCLE_SESSION))
    p.drain()
    with p.view() as v:
        failed = v.execute("SELECT body FROM jobs WHERE kind = 'ingest' AND state != 'completed'").fetchall()
    assert failed == [], failed
    assert p.task_of(p.event("user_message", text="One more thing after")["id"]) != task_id  # a new task, as after forgetting
    assert not any(_bodies(p, "task", task_id))


# ---------------------------------------------------------------------------
# Full profile: exact capsules (Task 15 full capsule slice, decision 0025; the rest is tests/integration/test_capsules.py)


def test_expiry_preserves_required_capsule(tmp_path, monkeypatch):
    """Full profile, day 31: a pinned payload past the 30-day window becomes an exact capsule; its owner keeps its evidence (A35 full).

    The decision's whole user statement is kept as one exact span and its link
    is redirected to the capsule; unpinned payloads expire; no claim changes.
    Full-profile store through the provisioning function (test-only
    ``RELEASE_PROFILE``, decision 0024).
    """
    import claude_fixtures as cf
    from recalith.privacy import capsules

    monkeypatch.setattr(cf, "RELEASE_PROFILE", "full")
    b = rsn.build(tmp_path, capsules=True)
    p, ev = b.p, b.events
    before = rsn.guidance(p)
    said = p.event("user_message", text="We decided: keep")["payload"]["text"]
    report = sweep(p, rsn.day(p, 31))
    assert ev["decision"] in report.compacted and rsn.payload_state(p, ev["decision"]) == ("capsule_only", False)
    assert expired(p, ev["session_start"], ev["reply_ok"], ev["complete"])
    with p.view() as v:
        capsule = capsules.for_event(v, ev["decision"])
        link = [r for r in v.execute("SELECT target_kind, target_id, locator FROM evidence_links WHERE owner_kind = 'claim' AND owner_id = ?", (b.claims["decision"],)).fetchall()]
    assert [s.text for s in capsule.spans] == [said]
    assert {(k, t) for k, t, _l in link} == {("capsule", capsule.capsule_id)}
    assert rsn.guidance(p) == before
