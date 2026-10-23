"""Task 15 full capsule slice: exact evidence capsules, link redirection and retained pins (A55, A35 full; decision 0025).

Full adds exact evidence capsules: a pinned payload past the 30-day unpinned
window is replaced by a capsule holding exactly what its live owners cite,
with the original coordinates; capsule insertion, link redirection and payload
removal commit together; when preservation is not sufficient the pin stays and
the sweep reports deferred compaction. Preview never compacts and keeps its
180-day behavior.

Real inputs: Claude Code 2.1.301 payloads through the real adapter, ingestion
and typed reduction; claims admitted through the real extraction/review path
with recorded proposals; the typed declaration through the guarded service;
retention through the real sweep at controlled times ahead of every capture;
forget, backup and restore through the service. Synthetic variants are named
where used (``retention_scenarios.capsule_owners``: the A55 prompt text, the
reruns of the failing pytest call). Full-profile stores are created through
the provisioning function with a full ``ProjectConfig`` (``claude_fixtures``'
test-only ``RELEASE_PROFILE``, decision 0024); ``init --release-profile full``
stays refused.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import retention_scenarios as rsn  # first: puts tests/, tests/integration and tests/platform on sys.path
import claude_fixtures as cf  # noqa: E402
import forget_scenarios as fs  # noqa: E402
import operation_scenarios as osc  # noqa: E402
import working_scenarios as wks  # noqa: E402
from recalith import service  # noqa: E402
from recalith.contracts.common import EvidenceLink, RecordRef, SpanLocator  # noqa: E402
from recalith.contracts.memory import EvidenceCapsule  # noqa: E402
from recalith.contracts.privacy import ForgetSelector  # noqa: E402
from recalith.controller import admission  # noqa: E402
from recalith.core import lineage  # noqa: E402
from recalith.errors import RecalithError  # noqa: E402
from recalith.operations import health as operations_health  # noqa: E402
from recalith.privacy import capsules, retention  # noqa: E402
from recalith.retrieval import search  # noqa: E402
from recalith.storage import db, failpoints, integrity, records  # noqa: E402

# Live owners' evidence a capsule keeps (decision 0025 §3): the whole declaration and typed statement, the A55
# quote, the located Edit quote, the typed exit-code mapping and the forwarded subagent result (identity only).
COMPACTED = ("decision", "typed", "quote", "edit", "observed", "sub_result")
DEFERRED = {
    "seq": "unlocated_reference", "write": "unlocated_reference", "read": "unlocated_reference", "pass": "unlocated_reference",
    "grep": "unlocated_reference",  # the candidate's pending review reads it as a claim input: that alone would not block (decision 0025 §3)
    "forward": "not_a_root", "echo": "not_a_root",  # the lineage walk reads these payloads (a forwarding result; an unregistered result)
    "fail": "owed_work", "long": "owed_work", "missing": "owed_work", "ls": "owed_work", "sleep": "owed_work",  # undebounced failures
    "b_start": "open_working_context", "b_prompt": "open_working_context", "b_call": "open_working_context", "b_result": "open_working_context",
}
NEEDLE = "Ünïcode fixture"  # only in the A55 quote (the claim's proposition does not contain it)


@pytest.fixture(autouse=True)
def _disarm():
    failpoints.disarm_all()
    yield
    failpoints.disarm_all()


@pytest.fixture
def full(monkeypatch):
    """New fixture installations get ``release_profile: full`` for this test."""
    monkeypatch.setattr(cf, "RELEASE_PROFILE", "full")


def build(tmp_path: Path, name: str = "capsules", **kw) -> rsn.Built:
    return rsn.build(tmp_path, name, capsules=True, **kw)


def sweep(p: wks.Project, now: str) -> retention.Report:
    with db.open_store(p.ctx) as store:
        return retention.sweep(store, p.ctx, now=now)


def worker_step(p: wks.Project, now: str) -> dict:
    """The worker's retention step (what health reports from): the sweep with its report recorded."""
    from recalith.core.identity import Layout, load_project_config

    with db.open_store(p.ctx) as store:
        return retention.run(store, p.ctx, load_project_config(Layout(p.root)), now=now)


def day(p: wks.Project, n: float) -> str:
    return rsn.day(p, n)


def links_of(p: wks.Project, claim_id: str) -> list[tuple]:
    """(target_kind, target_id, locator, mapping, root_event_ids) of the claim head's normalized links."""
    with p.view() as v:
        revision = records.head(v, "claim", claim_id)[0]
        return sorted(v.execute(
            "SELECT target_kind, target_id, locator, mapping, root_event_ids FROM evidence_links WHERE owner_kind = 'claim' AND owner_id = ? AND owner_revision = ?", (claim_id, revision),
        ).fetchall())


def capsule_rows(p: wks.Project) -> dict[str, dict]:
    with p.view() as v:
        return {cid: json.loads(body) for cid, body in v.execute("SELECT capsule_id, body FROM evidence_capsules").fetchall()}


def head_links(p: wks.Project, claim_id: str) -> list[EvidenceLink]:
    """The claim head's frozen support links (event refs in its immutable revision body)."""
    body = rsn.cs.head(p, claim_id)
    return [EvidenceLink.model_validate(item) for item in body["supports"]]


def payload_slice(p: wks.Project, event_id: str, locator: dict) -> str:
    with p.view() as v:
        payload = json.loads(v.execute("SELECT payload FROM events WHERE event_id = ?", (event_id,)).fetchone()[0])
    value = payload
    for part in locator["field"].split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value[locator["start"] : locator["end"]]


def resolved_texts(p: wks.Project, claim_id: str) -> list[tuple[str, str | None]]:
    """(state, text) the resolver gives for each frozen support link of the claim head."""
    with p.view() as v:
        return [(r.state, r.text) for r in (capsules.resolve(v, link.ref, link.locator) for link in head_links(p, claim_id))]


def verified(p: wks.Project) -> dict:
    report = integrity.verify(p.ctx, full=True)
    assert report["state"] == "verified" and report["complete_coverage"] is True, report["findings"]
    return report


def gates(p: wks.Project, claim_id: str) -> dict:
    """Every deterministic admission gate a later revision of this claim would rerun, plus its strength."""
    body = rsn.cs.head(p, claim_id)
    supports = [EvidenceLink.model_validate(i) for i in body["supports"]]
    with p.view() as v:
        return {
            "check_link": [admission.check_link(v, link) for link in supports],
            "mapping": [admission.check_mapping(v, link) if link.mapping else None for link in supports],
            "declaration": [admission.declaration_refusal(v, link) if admission.user_channel_link(v, link) else None for link in supports],
            "activation": admission.activation_refusal(v, body) if body["head_status"] == "active" else None,
            "strength": admission.assign_strength(v, body),
            "classes": sorted(lineage.resolve(v, supports, proposition_key=body.get("proposition_key")).support_classes),
            "available": [lineage.chain_available(v, link) for link in supports],
        }


# ---------------------------------------------------------------------------
# Compaction: which payloads become capsules, and the A55 quote


def test_a55_quote_at_offset_900_with_unicode_survives_source_expiry(tmp_path, full):
    """A retained quote beginning at code point 900, with Unicode before and inside it, after its source payload goes (A55).

    The capsule returns the exact original substring by origin locator and
    digest; the capsule never holds the text at the old offsets, and the
    resolver never slices it there; the link redirection and the payload
    removal are one transaction.
    """
    b = build(tmp_path)
    p, ev = b.p, b.events
    claim_id = b.claims["quote"]
    [link] = head_links(p, claim_id)
    assert (link.locator.field, link.locator.start) == ("text", 900)
    original = payload_slice(p, ev["quote"], link.locator.model_dump())
    assert original == rsn.A55_QUOTE and len(original.encode("utf-8")) > len(original)  # multibyte inside the span
    full_text = rsn.a55_text()
    assert len(full_text[:900].encode("utf-8")) > 900  # code points, not bytes or UTF-16 units, before the span
    before = rsn.claim_state(p, claim_id)
    revision_before = rsn.meta(p).store_revision

    report = sweep(p, day(p, 31))

    assert ev["quote"] in report.compacted
    assert rsn.payload_state(p, ev["quote"]) == ("capsule_only", False)
    cid = capsules.capsule_id(ev["quote"])
    capsule = EvidenceCapsule.model_validate(capsule_rows(p)[cid])
    [span] = [s for s in capsule.spans if s.original_locator == link.locator]
    assert span.text == original and span.text_digest == link.locator.text_digest == hashlib.sha256(original.encode("utf-8")).hexdigest()
    assert span.origin_ref == RecordRef(kind="event", id=ev["quote"], revision=1)
    assert len(span.context_before) <= capsules.CONTEXT_CODE_POINTS and len(span.context_after) <= capsules.CONTEXT_CODE_POINTS
    assert full_text[900 - len(span.context_before) : 900] == span.context_before and full_text.startswith(span.context_after, 900 + len(original))
    assert full_text[:600] not in json.dumps(capsule.model_dump(mode="json"), ensure_ascii=False)  # the span and bounded context, not the text
    # Old offsets applied to any capsule text give something else: the resolver must use the origin locator.
    for text in (span.text, span.context_before + span.text + span.context_after):
        assert text[900:953] != original
    with p.view() as v:
        by_event = capsules.resolve(v, link.ref, link.locator)
        by_capsule = capsules.resolve(v, RecordRef(kind="capsule", id=cid, revision=1), link.locator)
    assert (by_event.state, by_event.text, by_event.source) == ("capsule_only", original, "capsule")
    assert (by_capsule.state, by_capsule.text) == ("capsule_only", original)
    # Redirected with the original coordinates; the claim keeps its revision, strength and guidance.
    [(kind, target, locator, mapping, roots)] = links_of(p, claim_id)
    assert (kind, target, json.loads(locator), mapping, json.loads(roots)) == ("capsule", cid, link.locator.model_dump(mode="json"), None, [ev["quote"]])
    assert rsn.claim_state(p, claim_id) == before
    assert rsn.cs.head(p, claim_id)["revision"] == 2  # no new claim revision
    assert rsn.meta(p).store_revision > revision_before
    verified(p)


def test_expiry_preserves_required_capsule_and_retains_insufficient_pins(tmp_path, full):
    """Day 31 in full: unpinned payloads expire; required payloads become exact capsules or stay pinned with a reason (A35 full).

    Located, whole-statement and typed references are kept exactly; a tool
    result cited without a locator or mapping, a non-root forwarding result,
    owed work and an open working range keep their payloads (the reasons are
    reported, guidance is not weakened). Day 30 is not yet past the window.
    """
    b = build(tmp_path)
    p, ev = b.p, b.events
    before = rsn.guidance(p)
    texts = {role: resolved_texts(p, b.claims[role]) for role in ("decision", "typed", "quote", "located")}
    assert all(state == "available" and text for role in texts for state, text in texts[role])

    quiet = sweep(p, rsn.plus(rsn.oldest(p), days=30))  # strictly older than 30 days by capture time compacts
    assert quiet.compacted == [] and capsule_rows(p) == {}

    report = sweep(p, day(p, 31))
    compacted = {ev[r] for r in COMPACTED}
    assert set(report.compacted) == compacted, sorted((k for k, v in ev.items() if v in set(report.compacted) ^ compacted))
    for role in COMPACTED:
        assert rsn.payload_state(p, ev[role]) == ("capsule_only", False), role
    for role in DEFERRED:
        assert rsn.payload_state(p, ev[role]) == ("available", True), role
    assert {role: report.compaction_reasons.get(ev[role]) for role in DEFERRED} == DEFERRED
    assert sum(report.compaction_deferred.values()) == len(report.compaction_reasons) and set(report.compaction_reasons) & set(report.compacted) == set()
    for role in ("session_start", "reply_ok", "printf", "complete"):
        assert rsn.payload_state(p, ev[role]) == ("expired", False), role  # unpinned past 30 days
    # Retention alone lowers nothing and the exact cited text still resolves.
    assert rsn.guidance(p) == before
    for role, expected in texts.items():
        assert [(s, t) for s, t in resolved_texts(p, b.claims[role])] == [("capsule_only", t) for _s, t in expected], role
    with p.view() as v:
        pinned = retention.pinned_events(v)
        summary = retention.summary(v, p.ctx, now=day(p, 31), config=retention.retention_config(p.ctx))
    held = pinned & {e for e, s in rsn.states(p).items() if s == "available"}
    assert {ev[r] for r in DEFERRED} <= held and summary.deferred_compaction_count == len(held)  # pinned, past the window, still held in full
    # Rendering: capsule-backed support is servable context, labeled capsule_only.
    with p.view() as v:
        rendered = search.evidence_state(v, rsn.cs.head(p, b.claims["quote"]))
    assert rendered == "capsule_only"
    # Idempotent: a second sweep compacts nothing new and changes nothing.
    rows = capsule_rows(p)
    again = sweep(p, day(p, 32))
    assert again.compacted == [] and capsule_rows(p) == rows and rsn.guidance(p) == before
    verified(p)


def test_compaction_commits_atomically_with_one_purge_entry(tmp_path, full):
    """Capsule insertion, link redirection and payload removal commit together or not at all.

    An exception at ``capsule.before_commit`` (everything written, commit
    pending) leaves no capsule, no redirected link and every payload; the next
    sweep commits all of them in one transaction whose chain entry is a purge
    entry naming the capsule, link and event rows.
    """
    b = build(tmp_path)
    p, ev = b.p, b.events
    with p.view() as v:
        links_before = v.execute("SELECT link_id, target_kind, target_id FROM evidence_links ORDER BY link_id").fetchall()
        head_before = v.execute("SELECT MAX(sequence) FROM revision_chain").fetchone()[0]

    def boom(name):
        raise RuntimeError(name)

    failpoints.arm(failpoints.CAPSULE_BEFORE_COMMIT, boom)
    with pytest.raises(RuntimeError):
        sweep(p, day(p, 31))
    assert capsule_rows(p) == {}
    for role in COMPACTED:
        assert rsn.payload_state(p, ev[role]) == ("available", True), role
    with p.view() as v:
        assert v.execute("SELECT link_id, target_kind, target_id FROM evidence_links ORDER BY link_id").fetchall() == links_before
        assert v.execute("SELECT COUNT(*) FROM operations WHERE kind = ?", (capsules.KIND,)).fetchone()[0] == 0
    verified(p)

    report = sweep(p, day(p, 31))
    assert set(report.compacted) == {ev[r] for r in COMPACTED} and report.links_redirected >= len(COMPACTED) - 1
    with p.view() as v:
        audits = v.execute("SELECT store_revision, inputs FROM operations WHERE kind = ?", (capsules.KIND,)).fetchall()
        assert len(audits) == 1
        entries = v.execute("SELECT sequence, operation_id, row_digests, purge_marker FROM revision_chain WHERE sequence > ? ORDER BY sequence", (head_before,)).fetchall()
    capsule_entries = [e for e in entries if any(r[0] == "evidence_capsules" for r in json.loads(e[2])["rows"])]
    assert len(capsule_entries) == 1
    seq, _op, body, purge = capsule_entries[0]
    tables = {r[0] for r in json.loads(body)["rows"]}
    assert purge == 1 and {"evidence_capsules", "evidence_links", "events", "operations"} <= tables
    assert json.loads(body)["store_revision"] == audits[0][0]
    inputs = json.loads(audits[0][1])
    assert inputs["capsule_count"] == len(COMPACTED) and NEEDLE not in audits[0][1]  # content-free
    verified(p)


def test_insufficient_capsule_keeps_pin_and_never_weakens_evidence(tmp_path, full):
    """A capsule that cannot reproduce a cited span exactly is never created; the pin stays and deferral is reported.

    Synthetic store state: the normalized link of the located Edit quote is
    given a locator whose digest no longer matches its payload (as a damaged
    row would), so the capsule verification cannot reproduce it.
    """
    b = build(tmp_path)
    p, ev = b.p, b.events
    claim_id = b.claims["located"]
    before = rsn.guidance(p)
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        rows = txn.execute("SELECT link_id, locator FROM evidence_links WHERE owner_kind = 'claim' AND owner_id = ? AND target_id = ?", (claim_id, ev["edit"])).fetchall()
        assert len(rows) == 2  # the claim's two revisions
        for link_id, locator in rows:
            loc = json.loads(locator)
            loc["text_digest"] = "0" * 64
            txn.execute("UPDATE evidence_links SET locator = ? WHERE link_id = ?", (json.dumps(loc, sort_keys=True, separators=(",", ":")), link_id))
        txn.mutated(serving_relevant=False)
    report = worker_step(p, day(p, 31))["sweep"]
    assert report["compacted_count"] == len(COMPACTED) - 1 and report["compaction_deferred"].get("locator_unresolved") == 1
    assert rsn.payload_state(p, ev["edit"]) == ("available", True)
    assert capsules.capsule_id(ev["edit"]) not in capsule_rows(p)
    assert rsn.guidance(p) == before  # neither this claim nor any other is weakened
    with p.view() as v:
        assert all(lineage.chain_available(v, link) for link in head_links(p, claim_id))
        summary = retention.summary(v, p.ctx, now=day(p, 31), config=retention.retention_config(p.ctx))
    assert summary.deferred_compaction_count >= 1
    capsule_cap = operations_health.health(p.ctx, now=day(p, 31)).capabilities["capsules"]
    assert capsule_cap.state == "healthy" and capsule_cap.coverage["deferred_compaction_count"] == summary.deferred_compaction_count
    assert capsule_cap.coverage["last_compaction"]["deferred"]["locator_unresolved"] == 1
    verified(p)


# ---------------------------------------------------------------------------
# The resolver, admission and strength


def test_resolver_dispatches_by_record_ref_kind(tmp_path, full):
    """Event refs read the payload while available and the capsule once capsule-only; capsule refs read the capsule.

    A locator the capsule does not hold is unavailable (never a nearby slice);
    an unknown capsule is missing; ``show`` returns the capsule and the
    capsule-only event with it.
    """
    b = build(tmp_path)
    p, ev = b.p, b.events
    [link] = head_links(p, b.claims["decision"])
    with p.view() as v:
        live = capsules.resolve(v, link.ref, link.locator)
    assert (live.state, live.source) == ("available", "payload") and live.text
    sweep(p, day(p, 31))
    cid = capsules.capsule_id(ev["decision"])
    shifted = SpanLocator(field=link.locator.field, start=link.locator.start + 1, end=link.locator.end, text_digest=hashlib.sha256(live.text[1:].encode("utf-8")).hexdigest())
    with p.view() as v:
        assert capsules.origin_event(v, cid) == ev["decision"]
        compact = capsules.resolve(v, link.ref, link.locator)
        direct = capsules.resolve(v, RecordRef(kind="capsule", id=cid, revision=1), link.locator)
        uncovered = capsules.resolve(v, link.ref, shifted)
        unknown = capsules.resolve(v, RecordRef(kind="capsule", id=capsules.capsule_id(ev["reply_ok"]), revision=1), link.locator)
        expired = capsules.resolve(v, RecordRef(kind="event", id=ev["reply_ok"], revision=1), None)
        whole = capsules.resolve(v, link.ref, None)
    assert (compact.state, compact.source, compact.text) == ("capsule_only", "capsule", live.text)
    assert (direct.state, direct.text) == ("capsule_only", live.text)
    assert (uncovered.state, uncovered.text) == ("uncovered", None)
    assert unknown.state == "missing" and expired.state == "expired"
    assert (whole.state, whole.text) == ("capsule_only", live.text)  # a null locator on a statement cites the whole field
    shown = service.show(p.ctx, cid)
    assert shown["kind"] == "capsule" and EvidenceCapsule.model_validate(shown["body"]).capsule_id == cid
    event = service.show(p.ctx, ev["decision"])
    assert event["body"]["payload"] is None and event["capsule"]["capsule_id"] == cid


def test_compaction_is_not_new_support_and_keeps_admission(tmp_path, full):
    """Every admission gate and the strength give the same answer before and after compaction; a capsule is never a new root.

    A new fact citing the capsule ref is admitted through the real path with
    the same root class as one citing the event, and citing both does not
    corroborate.
    """
    b = build(tmp_path)
    p, ev = b.p, b.events
    roles = ("decision", "typed", "quote", "located", "observed")
    before = {role: gates(p, b.claims[role]) for role in roles}
    assert all(g["activation"] is None and g["strength"] == "supported" for g in before.values()), before
    times = {role: rsn.cs.head(p, b.claims[role])["last_supported_at"] for role in roles}
    with p.view() as v:
        roots_before = v.execute("SELECT COUNT(*) FROM root_event_members").fetchone()[0], v.execute("SELECT COUNT(*) FROM root_classes").fetchone()[0]
    sweep(p, day(p, 31))
    for role in roles:
        assert gates(p, b.claims[role]) == before[role], role
        assert rsn.cs.head(p, b.claims[role])["last_supported_at"] == times[role]
    with p.view() as v:
        assert (v.execute("SELECT COUNT(*) FROM root_event_members").fetchone()[0], v.execute("SELECT COUNT(*) FROM root_classes").fetchone()[0]) == roots_before
    # A new claim citing the capsule: admitted, one class, the same as the event's.
    [link] = head_links(p, b.claims["quote"])
    cid = capsules.capsule_id(ev["quote"])
    cap_link = {"ref": {"kind": "capsule", "id": cid, "revision": 1}, "relation": "supports", "root_event_ids": [ev["quote"]], "locator": link.locator.model_dump(mode="json"), "mapping": None}
    new_id = rsn.located_fact(p, "The Unicode note quotes a kept span.", cap_link, subject="unicode2")
    body = rsn.cs.head(p, new_id)
    assert (body["head_status"], body["strength"]) == ("active", "supported")
    with p.view() as v:
        via_capsule = lineage.resolve(v, [EvidenceLink.model_validate(cap_link)], proposition_key=body["proposition_key"]).support_classes
        both = lineage.resolve(v, [EvidenceLink.model_validate(cap_link), link], proposition_key=body["proposition_key"])
        bad_root = admission.check_link(v, EvidenceLink.model_validate({**cap_link, "root_event_ids": [ev["decision"]]}))
    assert via_capsule == set(before["quote"]["classes"]) and both.support_classes == via_capsule
    assert bad_root == "root_mismatch"  # a capsule ref may name only its origin event as its root


# ---------------------------------------------------------------------------
# Release, forgetting, backup and restore


def test_released_capsule_expires_and_its_links_revert(tmp_path, full):
    """When the last live owner releases a capsule-only event, the next sweep expires it: capsule gone, links back to the event."""
    b = build(tmp_path)
    p, ev = b.p, b.events
    sweep(p, day(p, 31))
    cid = capsules.capsule_id(ev["quote"])
    assert cid in capsule_rows(p)
    rsn.status_change(p, b.claims["quote"], "archived")
    report = sweep(p, day(p, 32))
    assert ev["quote"] in report.expired
    assert rsn.payload_state(p, ev["quote"]) == ("expired", False) and cid not in capsule_rows(p)
    with p.view() as v:
        targets = v.execute("SELECT target_kind, target_id FROM evidence_links WHERE target_id = ?", (cid,)).fetchall()
        reverted = v.execute("SELECT COUNT(*) FROM evidence_links WHERE target_kind = 'event' AND target_id = ?", (ev["quote"],)).fetchone()[0]
        state = capsules.resolve(v, RecordRef(kind="event", id=ev["quote"], revision=1), head_links(p, b.claims["quote"])[0].locator).state
    assert targets == [] and reverted >= 1 and state == "expired"
    assert fs.marker_locations(p.root, needle=NEEDLE) == []
    verified(p)


def test_forget_reaches_capsules_and_restore_does_not_resurrect(tmp_path, full):
    """Forgetting a capsule's source (selected by the capsule ref) purges the capsule; no backup or restore brings it back.

    The capsule's text is in a recorded backup and an operator's external copy
    taken after compaction. The forget leaves content-free tombstones naming
    the event and the capsule, deletes the affected recorded backup, and the
    suppression-aware restore of the external copy purges the capsule before
    the swap.
    """
    b = build(tmp_path)
    p, ev = b.p, b.events
    sweep(p, day(p, 31))
    cid = capsules.capsule_id(ev["quote"])
    recorded = service.submit_backup(fs.operator(b), tmp_path / "recorded")
    external = fs.copy_backup(recorded.location, tmp_path / "external")
    assert fs._db_hits(Path(recorded.location) / "memory.sqlite", NEEDLE)  # noqa: SLF001 - the test's own search
    selector = ForgetSelector.model_validate({"record_refs": [{"kind": "capsule", "id": cid, "revision": 1}]})
    fs.forget(b, selector)
    assert rsn.payload_state(p, ev["quote"]) == ("forgotten", False) and cid not in capsule_rows(p)
    with p.view() as v:
        targets = {t for (row,) in v.execute("SELECT target_ids FROM tombstones").fetchall() for t in json.loads(row)}
        assert {ev["quote"], cid} <= targets
        assert v.execute("SELECT COUNT(*) FROM evidence_links WHERE target_id = ?", (cid,)).fetchone()[0] == 0
    assert records_status(p, b.claims["quote"]) == "forgotten"
    assert fs.marker_locations(p.root, needle=NEEDLE) == []
    assert not Path(recorded.location).exists()  # the recorded backup held the capsule: deleted by the forget
    verified(p)
    service.restore(fs.operator(b), external, expected_digest=recorded.manifest_digest)
    assert cid not in capsule_rows(p) and rsn.payload_state(p, ev["quote"])[0] == "forgotten"
    assert fs.marker_locations(p.root, needle=NEEDLE) == []
    for role in ("decision", "typed", "located"):  # the other capsules came back with the snapshot
        assert capsules.capsule_id(ev[role if role != "located" else "edit"]) in capsule_rows(p)
        assert [s for s, _t in resolved_texts(p, b.claims[role])] == ["capsule_only"], role


def records_status(p: wks.Project, claim_id: str) -> str:
    with p.view() as v:
        return records.head(v, "claim", claim_id)[1]


def test_backup_and_restore_preserve_capsules(tmp_path, full):
    """A verified backup carries the capsules and their redirected links; restoring it keeps every capsule exact and resolvable."""
    b = build(tmp_path)
    p, ev = b.p, b.events
    sweep(p, day(p, 31))
    rows = capsule_rows(p)
    assert len(rows) == len(COMPACTED)
    with p.view() as v:
        redirected = v.execute("SELECT owner_id, owner_revision, target_id, locator FROM evidence_links WHERE target_kind = 'capsule' ORDER BY link_id").fetchall()
    taken = service.submit_backup(fs.operator(b), tmp_path / "bk")
    conn = sqlite3.connect((Path(taken.location) / "memory.sqlite").as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        assert {c: json.loads(body) for c, body in conn.execute("SELECT capsule_id, body FROM evidence_capsules").fetchall()} == rows
    finally:
        conn.close()
    texts = {role: resolved_texts(p, b.claims[role]) for role in ("decision", "typed", "quote", "located")}
    rsn.status_change(p, b.claims["located"], "archived")
    sweep(p, day(p, 32))  # the Edit capsule is released and expires in the live store
    assert capsules.capsule_id(ev["edit"]) not in capsule_rows(p)
    service.restore(fs.operator(b), Path(taken.location), expected_digest=taken.manifest_digest)
    assert capsule_rows(p) == rows
    with p.view() as v:
        assert v.execute("SELECT owner_id, owner_revision, target_id, locator FROM evidence_links WHERE target_kind = 'capsule' ORDER BY link_id").fetchall() == redirected
    for role, expected in texts.items():
        assert resolved_texts(p, b.claims[role]) == expected, role
    verified(p)


# ---------------------------------------------------------------------------
# Profiles


def test_preview_keeps_180_day_pins_and_reports_capsules_unavailable(tmp_path):
    """Preview: no compaction at any age, pinned payloads stay available past day 181, capsules are reported unavailable."""
    b = build(tmp_path, "preview")
    p, ev = b.p, b.events
    assert rsn.meta(p).release_profile == "claude_preview"
    report = sweep(p, day(p, 31))
    assert report.compacted == [] and report.expired == []  # nothing is past preview's window yet
    report = sweep(p, day(p, 181))
    assert report.compacted == [] and report.compaction_deferred == {}
    assert capsule_rows(p) == {} and "capsule_only" not in set(rsn.states(p).values())
    for role in COMPACTED:
        assert rsn.payload_state(p, ev[role]) == ("available", True), role
    cap = operations_health.health(p.ctx).capabilities["capsules"]
    assert cap.state == "unavailable" and "deferred_full_release" in cap.reason_codes
    with pytest.raises(RecalithError) as refused:
        service.show(p.ctx, capsules.capsule_id(ev["quote"]))
    assert refused.value.code == "capability_unavailable"
    with pytest.raises(RecalithError) as selected:
        service.preview_forget(fs.operator(b), ForgetSelector.model_validate({"record_refs": [{"kind": "capsule", "id": capsules.capsule_id(ev["quote"]), "revision": 1}]}))
    assert selected.value.code == "invalid_schema"


def test_full_health_reports_capsules(tmp_path, full):
    """Full: health reports ``capsules`` healthy with its counts; it never gates readiness."""
    b = build(tmp_path)
    p = b.p
    cap = operations_health.health(p.ctx).capabilities["capsules"]
    assert cap.state == "healthy" and cap.required is False and cap.coverage["capsule_count"] == 0
    worker_step(p, day(p, 31))
    report = operations_health.health(p.ctx, now=day(p, 31))
    cap = report.capabilities["capsules"]
    assert cap.state == "healthy" and cap.coverage["capsule_count"] == len(COMPACTED) and cap.coverage["capsule_bytes"] > 0
    assert cap.coverage["last_compaction"]["compacted_count"] == len(COMPACTED)
    assert cap.coverage["deferred_compaction_count"] == report.retention_summary.deferred_compaction_count


def test_model_requests_carry_capsule_only_evidence(tmp_path, full):
    """A later model job over a compacted claim shows the curator the kept spans, never a request without its evidence.

    A revalidation of the A55 claim (synthetic store state: one pending
    ``review_due`` recheck, as the request tests use) carries the event's
    capsule and allows citing the event and the capsule; a request with no
    capsule-only evidence serializes byte for byte as before (no field).
    """
    from recalith import prompts as _prompts
    from recalith.contracts.common import canonical_json, derived_id, utc_now
    from recalith.controller import jobs, requests

    b = build(tmp_path)
    p, ev = b.p, b.events
    claim = osc.head_ref(p.root, "claim", b.claims["quote"])

    def revalidation() -> object:
        now = utc_now()
        with db.open_store(p.ctx) as store, store.transaction() as txn:
            txn.execute("DELETE FROM claim_rechecks WHERE claim_id = ?", (claim.id,))
            txn.execute(
                "INSERT INTO claim_rechecks (recheck_id, claim_id, claim_revision, reason, event_id, detail, state, created_at) VALUES (?, ?, ?, 'review_due', ?, '{}', 'pending', ?)",
                (derived_id("rchk", [claim.id, now]), claim.id, claim.revision, ev["fixed"], now),
            )
            job_id, _ = jobs.enqueue(txn, kind="revalidate", input_refs=[claim], now=now, due_at=now, prompt_version=_prompts.CURRENT["revalidate"], idempotency=hashlib.sha256(now.encode("utf-8")).hexdigest())
            txn.mutated(serving_relevant=False)
        with p.view() as v:
            job = jobs.get_job(v, job_id)
        request = requests.prepare_model_request(p.ctx, job, now=utc_now())
        with db.open_store(p.ctx) as store, store.transaction() as txn:  # done with it: unfinished work would pin its inputs
            jobs.supersede(txn, job, "scenario_setup")
            txn.execute("UPDATE claim_rechecks SET state = 'cleared', outcome = 'scenario_setup', settled_at = ? WHERE claim_id = ?", (now, claim.id))
            txn.mutated(serving_relevant=False)
        return request

    before = revalidation()
    assert "capsules" not in json.loads(canonical_json(before.model_dump(mode="json")))  # nothing capsule-only: unchanged bytes
    assert ev["quote"] in [e.event_id for e in before.events]
    sweep(p, day(p, 31))
    after = revalidation()
    cid = capsules.capsule_id(ev["quote"])
    assert ev["quote"] not in [e.event_id for e in after.events]
    [kept] = [c for c in after.capsules if c.capsule_id == cid]
    assert [s.text for s in kept.spans] == [rsn.A55_QUOTE]
    allowed = {(r.kind, r.id) for r in after.allowed_evidence_refs}
    assert {("event", ev["quote"]), ("capsule", cid)} <= allowed
    assert json.loads(canonical_json(after.model_dump(mode="json")))["capsules"][0]["capsule_id"] == cid
