"""Task 16 (preview): intentional forgetting (A25, A36, A48, A63, A64; A37's forget side).

Real inputs: Claude Code 2.1.301 payloads through the real adapter, ingestion
and typed reduction; claims admitted through the real extraction/review path
with recorded proposals; a recorded ``create_episode`` proposal; delivery
through the real hook branch into a controlled test manifest; real backups.
``forget`` runs through the service as an operator and through the real
guarded ``recalith`` child process with an explicitly provisioned fixture
token (``cli_scenarios``). The forgotten content is the synthetic host session
``forget_scenarios.SESSION_F`` carrying one fixture-specific marker token
(:data:`forget_scenarios.MARK`); every other synthetic variant or store state
is named where it is used.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import forget_scenarios as fs  # first: puts tests/, tests/integration and tests/platform on sys.path
import admission_scenarios as adm  # noqa: E402
import cli_scenarios as cli  # noqa: E402
import consolidation_scenarios as cs  # noqa: E402
import delivery_scenarios as ds  # noqa: E402
import operation_scenarios as osc  # noqa: E402
import retention_scenarios as rsn  # noqa: E402
import retrieval_scenarios as rs  # noqa: E402
import worker_scenarios as ws  # noqa: E402
import working_scenarios as wks  # noqa: E402
from recalith import service  # noqa: E402
from recalith.contracts.common import ReadSet, RecordRef, Scope, digest_of, utc_now  # noqa: E402
from recalith.contracts.privacy import ForgetPreview, ForgetRequest, ForgetResult, ForgetSelector  # noqa: E402
from recalith.controller import apply, jobs, worker  # noqa: E402
from recalith.errors import RecalithError  # noqa: E402
from recalith.fast import spool  # noqa: E402
from recalith.privacy import forget  # noqa: E402
from recalith.storage import backup, db, failpoints  # noqa: E402

PURGED_STATES = ("forgotten", "quarantined")


@pytest.fixture(autouse=True)
def _disarm():
    failpoints.disarm_all()
    yield
    failpoints.disarm_all()


def _bodies(p: wks.Project, kind: str, record_id: str) -> list:
    table, key = {"claim": ("claim_revisions", "claim_id"), "task": ("task_revisions", "task_id"), "episode": ("episode_revisions", "episode_id")}[kind]
    with p.view() as v:
        return [r[0] for r in v.execute(f"SELECT body FROM {table} WHERE {key} = ? ORDER BY revision", (record_id,)).fetchall()]  # noqa: S608


def _served(p: wks.Project, text: str) -> list[str]:
    return rs.ids(rs.service(p, rs.query(p, "manual", text=text)))


def _token(b: fs.Built, tmp: Path) -> Path:
    tok = tmp / "operator.token"
    if not tok.exists():
        cli.register(b.p.root, cli.token(tok))
    return tok


def _cli_forget(b: fs.Built, tmp: Path, selector: ForgetSelector, *, env=None) -> tuple[ForgetPreview, cli.Result]:
    sel = fs.selector_file(tmp, selector)
    tok = _token(b, tmp)
    shown = cli.cli(b.p.root, "--json", "forget", "--selector", str(sel), "--preview", env=env)
    assert shown.code == 0, shown.stdout + shown.stderr
    preview = ForgetPreview.model_validate(shown.obj["result"])
    applied = cli.cli(b.p.root, "--json", "--operator-token-file", str(tok), "forget", "--selector", str(sel), "--apply", "--preview-digest", preview.preview_digest, env=env)
    return preview, applied


def _backup_location(p: wks.Project, backup_id: str) -> Path:
    with p.view() as v:
        return Path(v.execute("SELECT location FROM backups WHERE backup_id = ?", (backup_id,)).fetchone()[0])


# ---------------------------------------------------------------------------
# A36: the derivative closure is purged or content-free quarantined in the transaction


def test_forget_purges_all_derivatives(tmp_path):
    """A36/A64 success through the real guarded CLI: a task's text is gone from every table, index, cache, file and backup.

    The marker task's prompt and ``echo`` appear in claims (direct, multi-root
    and record-transitive), an episode, task revisions, proposal and operation
    bodies, views, the lexical index and its FTS shadow tables, a delivery's
    scratch and receipt, a pending spool segment and an older backup. After
    the forget nothing holds the marker; the multi-root claim is a
    content-free quarantined head; the unrelated lesson is untouched; a fresh
    post-forget backup verified before the affected older backup was deleted.
    """
    b = fs.build(tmp_path)
    p, c, ev = b.p, b.claims, b.events
    old = backup.create(p.ctx, tmp_path / "before-forget")
    fs.pending_marker_prompt(b)  # captured into the spool, not yet ingested
    before = fs.marker_locations(p.root, Path(old.location))
    for place in ("events.payload", "claim_revisions.body", "task_revisions.body", "episode_revisions.body", "proposals.body", "operations.inputs",
                  "context_views.body", "lexical_index.term", "lexical_fts_content", "retrieval_docs.terms"):
        assert any(place in loc for loc in before), (place, before)
    assert any("/run/sessions/" in loc.replace("\\", "/") for loc in before) and any("/spool/" in loc.replace("\\", "/") for loc in before)
    assert any("before-forget" in loc for loc in before)
    lesson_before = fs.head(p, "claim", c["lesson"])
    preview, applied = _cli_forget(b, tmp_path, fs.task_selector(b))
    refs = {(r.kind, r.id) for r in preview.affected_refs + preview.derivative_refs}
    assert {("task", b.tasks["forgotten"]), ("event", ev["said"]), ("event", ev["echo"]), ("claim", c["decl"]), ("claim", c["multi"]), ("claim", c["derived"]), ("episode", b.episode)} <= refs
    assert ("claim", c["lesson"]) not in refs and ("task", b.tasks["lifecycle"]) not in refs
    assert [r.id for r in preview.quarantined_refs] == [c["multi"]]
    assert preview.backup_ids == [old.manifest.artifact_id]
    assert {"external_exports_not_recallable", "remote_provider_copies_not_recallable", "filesystem_forensics_outside_guarantee", "ledger_digest_membership_disclosure"} <= set(preview.limits)
    assert applied.code == 0, applied.stdout + applied.stderr
    result = ForgetResult.model_validate(applied.obj["result"])
    assert result.purge_state == "completed" and result.backup_state == "verified" and result.error_codes == []
    assert result.deleted_backup_ids == [old.manifest.artifact_id] and result.quarantined_count == 1 and result.purged_count >= 6
    assert result.replay_suppression_coverage["match"] == "source_identity" and result.replay_suppression_coverage["paraphrase_detection"] is False
    statuses = fs.statuses(p, [("claim", c["decl"]), ("claim", c["derived"]), ("claim", c["multi"]), ("task", b.tasks["forgotten"]), ("episode", b.episode), ("claim", c["lesson"])])
    assert statuses == {c["decl"]: "forgotten", c["derived"]: "forgotten", c["multi"]: "quarantined", b.tasks["forgotten"]: "forgotten", b.episode: "forgotten", c["lesson"]: "active"}
    for kind, record_id in (("claim", c["decl"]), ("claim", c["derived"]), ("claim", c["multi"]), ("task", b.tasks["forgotten"]), ("episode", b.episode)):
        assert set(_bodies(p, kind, record_id)) == {None}, (kind, record_id)  # every revision, not only the head
    assert fs.head(p, "claim", c["lesson"]) == lesson_before
    assert not fs.maintenance_active(p)  # delivery resumed after the required logical cleanup
    with p.view() as v:  # delivery rows, outcome links and receipts of forgotten records are gone too
        names = " ".join(r[0] for r in v.execute("SELECT items FROM deliveries").fetchall())
        receipts = v.execute("SELECT COUNT(*) FROM events WHERE kind = 'memory_delivered' AND payload IS NOT NULL AND payload LIKE ?", (f"%{c['decl']}%",)).fetchone()[0]
    assert c["decl"] not in names and receipts == 0
    with p.view() as v:  # a forgotten event keeps a content-free envelope: identities, times and coverage only
        for event_id in (ev["said"], ev["echo"]):
            envelope = json.loads(v.execute("SELECT envelope FROM events WHERE event_id = ?", (event_id,)).fetchone()[0])
            assert envelope["forgotten"] is True and envelope["extensions"] == {} and "locator" not in envelope["origin"], envelope
    new = _backup_location(p, result.new_backup_id)
    assert not Path(old.location).exists()
    assert fs.marker_locations(p.root, tmp_path / "before-forget", new) == []
    verified = backup.verify(new, ctx=p.ctx)
    assert verified.manifest.tombstone_epoch == result.tombstone_epoch
    assert rsn.snapshot_rows(new / "memory.sqlite", "SELECT status FROM claim_heads WHERE claim_id = ?", (c["multi"],)) == [("quarantined",)]
    ledger = backup.read_latest_ledger(p.root)
    assert ledger["tombstone_epoch"] == result.tombstone_epoch and fs.MARK.lower() not in json.dumps(ledger).lower()
    # Nothing comes back: the worker ingests the spool (the pending prompt is suppressed), reduces and republishes.
    p.drain()
    rs.publish(p)
    assert fs.marker_locations(p.root, new) == []
    assert not {c["decl"], c["multi"], c["derived"]} & set(_served(p, "fixture port 8123 seq tree service"))
    assert c["lesson"] in rs.ids(rs.service(p, cs.query(p)))
    _reply, out = ds.hook(p, ds.in_session(wks.record("lifecycle", "UserPromptSubmit"), fs.SESSION_F, prompt="Which port does the fixture listen on? port 8123 again"))
    assert all(fs.MARK.lower() not in ds.context_text(o).lower() and c["decl"] not in ds.context_text(o) for o in out)
    # ``show`` returns the content-free marker instead of a body.
    shown = cli.cli(p.root, "--json", "show", c["decl"])
    assert shown.code == 0 and shown.obj["result"]["body"] is None and shown.obj["result"]["head_status"] == "forgotten"


def test_source_range_selects_by_capture_ordinal_and_spool(tmp_path):
    """A source range (adapter, host session, capture ordinals) forgets exactly its events and what derives from them.

    Claude Code 2.1.301 reports no source sequence, so a range counts the host
    session's events in capture order (1-based), spooled events after stored
    ones. The first event alone is the marker prompt: the ``echo`` (event 2,
    3) survives and its claims are untouched.
    """
    b = fs.build(tmp_path, deliver=False)
    p, c, ev = b.p, b.claims, b.events
    preview = service.preview_forget(fs.operator(b), fs.range_selector(b, 1, 1))
    assert [(r.kind, r.id) for r in preview.affected_refs] == [("event", ev["said"])]
    _preview, result = fs.forget(b, fs.range_selector(b, 1, 1))
    assert result.purge_state == "completed"
    assert rsn.payload_state(p, ev["said"]) == ("forgotten", False) and rsn.payload_state(p, ev["echo"]) == ("available", True)
    assert fs.statuses(p, [("claim", c["decl"]), ("claim", c["multi"]), ("claim", c["derived"])]) == {c["decl"]: "forgotten", c["multi"]: "quarantined", c["derived"]: "forgotten"}
    # The task and episode cite the prompt and the echo: content-free quarantine with surviving roots.
    assert fs.statuses(p, [("task", b.tasks["forgotten"]), ("episode", b.episode)]) == {b.tasks["forgotten"]: "quarantined", b.episode: "quarantined"}
    # A later range covering the rest, including a prompt still in the spool.
    fs.pending_marker_prompt(b)
    whole = service.preview_forget(fs.operator(b), fs.range_selector(b))
    assert len([r for r in whole.affected_refs if r.kind == "event"]) >= 4  # stored echo call/result, the delivery-free prompt, the spooled prompt
    fs.forget(b, fs.range_selector(b))
    assert not any(fs.MARK.encode() in path.read_bytes() for path in spool.ready_segments(spool.SpoolDirs(p.root)))
    p.drain()
    assert fs.marker_locations(p.root) == []


# ---------------------------------------------------------------------------
# Old jobs, late proposals and replay (A36; review focus 1)


def test_old_job_cannot_resurrect_forgotten_source(tmp_path):
    """Pending and in-flight jobs over forgotten input are cancelled; a late proposal is fenced; known source replay is suppressed.

    The pending extraction names the forgotten prompt (as the trigger and
    episode schedulers do); the in-flight one was leased before the forget and
    its recorded response restates the marker. An unrelated job leased before
    the forget carries the old tombstone epoch in its read set and is
    re-evaluated, never applied. The replays are the same real records again,
    one with changed content under the forgotten source key (synthetic
    variant), and the spool segment captured before the forget put back.
    """
    b = fs.build(tmp_path, deliver=False)
    p, c, ev = b.p, b.claims, b.events
    said_ref = RecordRef(kind="event", id=ev["said"], revision=1)
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        pending_id, _ = jobs.enqueue(txn, kind="extract_claims", input_refs=[said_ref], now=utc_now(), prompt_version="extract_claims@1", idempotency=digest_of("pending-over-forgotten"))
    in_flight = osc.leased(p.root, "extract_claims", input_refs=[said_ref], now=utc_now())
    unrelated = osc.leased(p.root, "extract_claims", input_refs=[RecordRef(kind="event", id=ev["seq"], revision=1)], now=utc_now(), owner="worker-unrelated")
    old_read_set = osc.read_set(p.root)  # tombstone epoch 0: prepared before the forget
    late = osc.response([osc.op("x", "propose_claim", adm.claim(f"The {fs.MARK} fixture still listens on 8123.", subject="late"), evidence=[{"ref": said_ref.model_dump(), "relation": "supports", "root_event_ids": [ev["said"]], "locator": None, "mapping": None}])], purpose="extract_claims")
    paraphrase = osc.response([osc.op("y", "propose_claim", adm.claim(f"The {fs.MARK} fixture uses the seq tree.", subject="para"), evidence=[adm.link(p.event("tool_finished", call="toolu_probe_0005"))])], purpose="extract_claims")
    rec = fs.pending_marker_prompt(b)
    segments = [Path(x) for x in spool.ready_segments(spool.SpoolDirs(p.root))]
    kept = [(x.name, x.read_bytes()) for x in segments]
    _preview, result = fs.forget(b, fs.task_selector(b))
    assert result.purge_state == "completed"
    with p.view() as v:
        for job_id in (pending_id, in_flight.job_id):
            job = jobs.get_job(v, job_id)
            assert (job.state, job.last_error_code) == ("cancelled", "forgotten_input"), job
    # The late result of the in-flight job never persists: its lease is fenced.
    with db.open_store(p.ctx) as store:
        with pytest.raises(RecalithError, match="lease fenced"):
            apply.persist_proposal(store, in_flight, late, old_read_set, now=utc_now())
    with p.view() as v:
        assert v.execute("SELECT COUNT(*) FROM proposals WHERE job_id = ?", (in_flight.job_id,)).fetchone()[0] == 0
    # The unrelated job's proposal was produced under the old tombstone epoch: re-evaluated, nothing applied.
    with db.open_store(p.ctx) as store:
        apply.persist_proposal(store, unrelated, paraphrase, old_read_set, now=utc_now())
        outcome = apply.apply_proposal(p.ctx, unrelated, paraphrase, store=store, now=utc_now())
    assert outcome.operation_ids == [] and outcome.requeued_job_ids
    # Known source replay: the same real records, a changed result under the same key, the old spool segment.
    with p.view() as v:
        counts = (v.execute("SELECT COUNT(*) FROM events").fetchone()[0], v.execute("SELECT COUNT(*) FROM source_conflicts").fetchone()[0], v.execute("SELECT COUNT(*) FROM claim_revisions").fetchone()[0])
    p.send(wks.variant(wks.record("lifecycle", "UserPromptSubmit"), prompt=fs.SAID, session=fs.SESSION_F))
    cs.send(p, "toolu_probe_0001", "fm", command=f"echo {fs.MARK}", session=fs.SESSION_F)
    cs.send(p, "toolu_probe_0001", "fm", command=f"echo {fs.MARK} changed", session=fs.SESSION_F)
    p.send(rec)
    for name, data in kept:
        (spool.SpoolDirs(p.root).ready / name).write_bytes(data)
    p.drain()
    with p.view() as v:
        after = (v.execute("SELECT COUNT(*) FROM events").fetchone()[0], v.execute("SELECT COUNT(*) FROM source_conflicts").fetchone()[0], v.execute("SELECT COUNT(*) FROM claim_revisions").fetchone()[0])
    assert after[:2] == counts[:2]
    assert fs.marker_locations(p.root) == []
    assert fs.statuses(p, [("claim", c["decl"]), ("claim", c["multi"])]) == {c["decl"]: "forgotten", c["multi"]: "quarantined"}
    # A duplicate application of an old proposal returns its original, content-free result and recreates nothing.
    with p.view() as v:
        row = v.execute("SELECT job_id FROM operations WHERE kind = 'apply_proposal' AND changed LIKE ?", (f"%{c['decl']}%",)).fetchone()
    assert row is not None


def test_new_independent_statement_is_allowed(tmp_path):
    """A truly new statement after the forget is new evidence: captured, extracted, reviewed and served.

    Synthetic variant: the same text typed in a new host session
    (``SESSION_N``): a different source identity, so it is not a replay. The
    guarded typed declaration of a forgotten statement is re-keyed by the new
    tombstone epoch, so it is recorded again instead of being suppressed.
    """
    b = fs.build(tmp_path, deliver=False)
    p = b.p
    fs.forget(b, fs.task_selector(b))
    said = adm.prompt(p, fs.SAID, session=fs.SESSION_N)
    assert said["id"] != b.events["said"] and said["payload"]["text"] == fs.SAID
    body = adm.claim(fs.DECL, kind="decision", basis="user_declared", subject="fixture port again")
    body["proposition_key"]["predicate"] = "chosen"
    again = adm.created_claim(adm.extract(p, [osc.op("d", "propose_claim", body, evidence=[adm.link(said, field="text")])], input_refs=[RecordRef(kind="event", id=said["id"], revision=1)]))
    adm.admit(p, again)
    assert fs.statuses(p, [("claim", again)]) == {again: "active"}
    assert again in _served(p, "fixture port 8123")
    # The typed declaration path: an exact statement whose earlier declaration was forgotten.
    ctx = fs.operator(b)
    first = service.submit_declaration(ctx, "decision", f"Keep {fs.MARK} on port 9000.", Scope())
    claim_id = adm.created_claim(first.result)
    fs.forget(b, ForgetSelector(record_refs=[RecordRef(kind="event", id=first.event_id, revision=1)]))
    assert fs.statuses(p, [("claim", claim_id)]) == {claim_id: "forgotten"}
    second = service.submit_declaration(ctx, "decision", f"Keep {fs.MARK} on port 9000.", Scope())
    assert second.event_id != first.event_id and not second.duplicate
    assert fs.statuses(p, [("claim", adm.created_claim(second.result))])[adm.created_claim(second.result)] == "candidate"


# ---------------------------------------------------------------------------
# A63: a derivative with surviving roots is quarantined until a new reviewed revision exists


def test_surviving_root_derivative_is_quarantined_until_reviewed(tmp_path):
    """A63: the multi-root claim loses its body inside the purge transaction and stays unserved while no budget exists.

    The reconstruction is a later extraction job over the surviving root only
    (no provider: it waits; never part of the purge). Once a recorded
    extraction proposes a claim from the surviving root and its recorded
    review admits it, that new revision is served; the placeholder stays a
    content-free quarantined head.
    """
    b = fs.build(tmp_path, deliver=False)
    p, c, ev = b.p, b.claims, b.events
    _preview, result = fs.forget(b, fs.task_selector(b))
    revision, status, body = fs.head(p, "claim", c["multi"])
    assert status == "quarantined" and body is None
    with p.view() as v:
        marker_rev = v.execute("SELECT created_store_revision FROM claim_revisions WHERE claim_id = ? AND revision = ?", (c["multi"], revision)).fetchone()[0]
        forget_rev = v.execute("SELECT store_revision FROM operations WHERE kind = 'forget' ORDER BY store_revision DESC LIMIT 1").fetchone()[0]
        tomb = v.execute("SELECT MAX(epoch) FROM tombstones").fetchone()[0]
    assert marker_rev == forget_rev and tomb == result.tombstone_epoch  # quarantined in the purge transaction itself
    assert c["multi"] not in _served(p, "seq tree fixture")
    rs.publish(p)
    assert c["multi"] not in rs.ids(rs.hook(p, rs.query(p, "prompt", text="seq tree fixture"))["packet"])
    (job,) = [j for j in cs.jobs_of(p, "extract_claims", states=("pending", "waiting_budget")) if {r.id for r in j.input_refs} == {ev["seq"]}]
    # No certified backend (B1): the worker leaves it waiting, visibly; the placeholder stays unserved.
    p.drain()
    with p.view() as v:
        assert jobs.get_job(v, job.job_id).state in ("pending", "waiting_budget")
    assert c["multi"] not in _served(p, "seq tree fixture")
    # The reconstruction job runs (recorded proposal over the surviving root) and its review admits the new claim.
    leased = osc.leased(p.root, "extract_claims", input_refs=job.input_refs, now=utc_now())
    response = osc.response([osc.op("r", "propose_claim", adm.claim("The seq run shares the fixture tree.", subject="fixture tree"), evidence=[adm.link(p.event("tool_finished", call="toolu_probe_0005"))])], purpose="extract_claims")
    current = ReadSet(workspace_id=p.ctx.workspace_id, policy_revision=1, tombstone_epoch=rsn.meta(p).tombstone_epoch)  # prepared after the forget
    with db.open_store(p.ctx) as store:
        apply.persist_proposal(store, leased, response, current, now=utc_now())
        rebuilt = adm.created_claim(apply.apply_proposal(p.ctx, leased, response, store=store, now=utc_now()))
    assert fs.statuses(p, [("claim", rebuilt)]) == {rebuilt: "candidate"}  # ordinary admission: a weak candidate until its review
    adm.admit(p, rebuilt)
    assert rebuilt in _served(p, "seq tree fixture") and fs.statuses(p, [("claim", c["multi"])]) == {c["multi"]: "quarantined"}


# ---------------------------------------------------------------------------
# A48: archive versus forget


def test_archive_preserves_history_and_forget_removes_content(tmp_path):
    """A48: an archived claim keeps every revision and its history search; a forgotten one keeps only content-free metadata."""
    b = fs.build(tmp_path, deliver=False)
    p, c = b.p, b.claims
    rsn.status_change(p, c["lesson"], "archived")
    lesson_bodies = _bodies(p, "claim", c["lesson"])
    assert all(x is not None for x in lesson_bodies)
    revision = fs.head(p, "claim", c["lesson"])[0]
    old = service.show(osc.context(p.root), c["lesson"], revision=1)
    assert old["body"]["proposition"] == cs.LESSON
    assert any(h["id"] == c["lesson"] for h in service.search(osc.context(p.root), "test_mid fails", history=True)["history"])
    fs.forget(b, ForgetSelector(record_refs=[RecordRef(kind="claim", id=c["decl"], revision=1)]))
    assert set(_bodies(p, "claim", c["decl"])) == {None} and _bodies(p, "claim", c["lesson"]) == lesson_bodies and revision == fs.head(p, "claim", c["lesson"])[0]
    shown = service.show(osc.context(p.root), c["decl"])
    assert shown["head_status"] == "forgotten" and shown["body"] is None
    with pytest.raises(RecalithError):
        service.show(osc.context(p.root), c["decl"], revision=1)
    with p.view() as v:
        tombstones = v.execute("SELECT target_ids, source_digests, deletion_scope FROM tombstones").fetchall()
    assert tombstones and all(fs.MARK.lower() not in json.dumps(t).lower() for t in tombstones)
    assert any(c["decl"] in json.loads(t[0]) for t in tombstones)
    assert not any(h["id"] == c["decl"] for h in service.search(osc.context(p.root), "fixture port", history=True)["history"])


# ---------------------------------------------------------------------------
# A25: forget at the final delivery fence


def test_forget_before_fence_excludes_and_after_fence_is_in_flight(tmp_path):
    """A25: a forget committed before the fence withdraws the reservation; one committed after it is recorded in flight.

    The forget runs inside the hook at the delivery failpoint (synthetic
    interleaving: the operator's command and the hook's delivery race). The
    hook holds its session lock, so the forget's scratch cleanup for that
    session stays owed and delivery stays paused (maintenance) until the
    worker resumes it.
    """
    b = fs.build(tmp_path, deliver=False)
    p, c = b.p, b.claims
    ds.enable(p)
    rs.publish(p)
    selector = ForgetSelector(record_refs=[RecordRef(kind="claim", id=c["decl"], revision=1)])

    def run_forget(_name: str) -> None:
        fs.forget(b, selector)

    failpoints.arm(failpoints.DELIVERY_AFTER_RESERVE, run_forget)
    reply, out = ds.hook(p, ds.in_session(wks.record("lifecycle", "UserPromptSubmit"), fs.SESSION_N, prompt="Which port does the fixture listen on? port 8123"))
    assert out == [] and reply["delivery"]["state"] == "fenced_out"
    assert fs.statuses(p, [("claim", c["decl"])]) == {c["decl"]: "forgotten"}
    with p.view() as v:
        ops = v.execute("SELECT status FROM privacy_operations").fetchall()
    assert ops == [("cleanup_pending",)] and fs.maintenance_active(p)  # the hook held the scratch lock
    paused, _ = ds.hook(p, ds.in_session(wks.record("lifecycle", "UserPromptSubmit"), wks.session_id(43), prompt="fixture tree seq"))
    assert paused["delivery"]["reason"] == "maintenance_in_progress"
    p.drain()  # the worker resumes the owed cleanup, then delivery resumes
    assert not fs.maintenance_active(p)
    with p.view() as v:
        assert v.execute("SELECT status FROM privacy_operations").fetchall() == [("completed",)]
    # After the fence: the output was already in flight; it is recorded as such and never claimed retracted.
    rs.publish(p)
    failpoints.arm(failpoints.DELIVERY_AFTER_FENCE, lambda _n: fs.forget(b, ForgetSelector(record_refs=[RecordRef(kind="claim", id=c["multi"], revision=1)])))
    reply, out = ds.hook(p, ds.in_session(wks.record("lifecycle", "UserPromptSubmit"), wks.session_id(44), prompt="seq tree fixture share"))
    assert out and c["multi"] in ds.context_text(out[0]) and reply["delivery"]["state"] == "emitted" and reply["delivery"]["in_flight_change"] is True
    ds.ingest(p)
    p.drain()
    rows = [r for r in ds.deliveries(p, p.sid(wks.session_id(44)))]
    assert rows and rows[0]["state"] == "emitted" and rows[0]["in_flight_change"] in (1, True)
    assert fs.statuses(p, [("claim", c["multi"])]) == {c["multi"]: "forgotten"}


# ---------------------------------------------------------------------------
# A64: the post-forget backup succeeds or fails


def test_failed_post_forget_backup_still_deletes_affected_backups(tmp_path):
    """A64 failure: the replacement backup fails; affected older backups are deleted anyway; purge and ledger stay.

    The failure is injected at the backup's snapshot step (an ``OSError``
    from a failpoint, as a full disk would). A backup taken before the
    forgotten session existed is unaffected and stays.
    """
    b = fs.build(tmp_path, deliver=False, early_backup=tmp_path / "early")
    p = b.p
    affected = backup.create(p.ctx, tmp_path / "affected")

    def boom(_name: str) -> None:
        raise OSError("injected: no space left for the post-forget backup")

    failpoints.arm(failpoints.BACKUP_AFTER_SNAPSHOT, boom)
    preview, result = fs.forget(b, fs.task_selector(b))
    assert affected.manifest.artifact_id in preview.backup_ids and b.early.manifest.artifact_id not in preview.backup_ids
    assert result.backup_state == "unavailable" and result.new_backup_id is None and "backup_unavailable_after_forget" in result.error_codes
    assert result.purge_state == "completed" and result.deleted_backup_ids == [affected.manifest.artifact_id]
    assert not Path(affected.location).exists() and Path(b.early.location).exists()
    assert fs.marker_locations(p.root, tmp_path / "affected", Path(b.early.location)) == []
    ledger = backup.read_latest_ledger(p.root)
    assert ledger["tombstone_epoch"] == result.tombstone_epoch == rsn.meta(p).tombstone_epoch
    assert not fs.maintenance_active(p)
    with p.view() as v:
        states = dict(v.execute("SELECT backup_id, state FROM backups").fetchall())
    assert states[affected.manifest.artifact_id] == "deleted" and states[b.early.manifest.artifact_id] == "verified"


def test_post_forget_backup_verifies_before_old_ones_are_deleted(tmp_path):
    """A64 success order: at the moment affected backups start to go, the new backup is already recorded and verifies."""
    b = fs.build(tmp_path, deliver=False)
    p = b.p
    old = backup.create(p.ctx, tmp_path / "old")
    seen: dict[str, object] = {}

    def check(_name: str) -> None:
        rows = backup.recorded(db.open_store(p.ctx))
        fresh = [r for r in rows if r["backup_id"] != old.manifest.artifact_id and r["state"] == "verified"]
        seen["old_exists"] = Path(old.location).exists()
        seen["fresh"] = bool(fresh) and backup.verify(Path(fresh[0]["location"]), expected_digest=fresh[0]["manifest_digest"], ctx=p.ctx) is not None

    failpoints.arm(failpoints.FORGET_AFTER_BACKUP, check)
    _preview, result = fs.forget(b, fs.task_selector(b))
    assert seen == {"old_exists": True, "fresh": True} and result.backup_state == "verified"
    assert not Path(old.location).exists()


# ---------------------------------------------------------------------------
# The preview digest, the guard and maintenance


def test_apply_requires_the_current_preview_digest_and_the_guard(tmp_path):
    """A stale preview digest applies nothing (exit 3); a marked caller is refused (exit 6) while its preview stays read-only."""
    b = fs.build(tmp_path, deliver=False)
    p, ev = b.p, b.events
    sel = fs.selector_file(tmp_path, fs.task_selector(b))
    tok = _token(b, tmp_path)
    shown = cli.cli(p.root, "--json", "forget", "--selector", str(sel), "--preview", env=cli.marked_env("CLAUDECODE"))
    assert shown.code == 0  # previews are read-only inspection, allowed for any caller
    digest = shown.obj["result"]["preview_digest"]
    refused = cli.cli(p.root, "--json", "--operator-token-file", str(tok), "forget", "--selector", str(sel), "--apply", "--preview-digest", digest, env=cli.marked_env("CLAUDECODE"))
    assert refused.code == 6
    # A new derivative after the preview changes the closure.
    adm.created_claim(adm.extract(p, [osc.op("n", "propose_claim", adm.claim(f"{fs.MARK} again.", subject="again"), evidence=[adm.link(p.event("user_message", text="Remember: the"))])], input_refs=[RecordRef(kind="event", id=ev["said"], revision=1)]))
    before = (cli.store_rows(p.root), fs.marker_locations(p.root))
    stale = cli.cli(p.root, "--json", "--operator-token-file", str(tok), "forget", "--selector", str(sel), "--apply", "--preview-digest", digest)
    assert stale.code == 3 and stale.obj["error"] == "revision_conflict", stale.stdout
    assert (cli.store_rows(p.root), fs.marker_locations(p.root)) == before and not fs.maintenance_active(p)
    with pytest.raises(RecalithError) as agent:
        service.apply_forget(osc.context(p.root), ForgetRequest(selector=fs.task_selector(b), preview_digest=digest))
    assert agent.value.code == "policy_refused"


def test_model_launches_pause_during_maintenance(tmp_path):
    """While a privacy maintenance marker exists the model lane leases nothing; afterwards it resumes."""
    b = fs.build(tmp_path, deliver=False)
    p = b.p
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        jobs.enqueue(txn, kind="extract_claims", input_refs=[RecordRef(kind="event", id=b.events["seq"], revision=1)], now=utc_now(), prompt_version="extract_claims@1", idempotency=digest_of("maintenance-pause"))
    backend = ws.FakeBackend()
    w = worker.Worker(osc.context(p.root), model=ws.runtime(backend))
    try:
        forget.write_marker(p.ctx, kind="forget", operation_id="frg_" + "0" * 64)
        assert w.lane.step() is False and backend.calls == []
        forget.clear_marker(p.ctx)
        assert w.lane.step() is True
    finally:
        w.close()


def test_interrupted_forget_resumes_before_delivery(tmp_path):
    """A forget that stops after its purge commit leaves delivery paused; the next worker poll finishes every phase."""
    b = fs.build(tmp_path, deliver=False)
    p = b.p
    old = backup.create(p.ctx, tmp_path / "old")

    def stop(_name: str) -> None:
        raise RuntimeError("interrupted after the purge commit")

    failpoints.arm(failpoints.FORGET_AFTER_COMMIT, stop)
    with pytest.raises(RuntimeError):
        fs.forget(b, fs.task_selector(b))
    assert fs.maintenance_active(p) and fs.marker_locations(p.root, tmp_path / "old") and Path(old.location).exists()
    assert not [loc for loc in fs.marker_locations(p.root) if "memory.sqlite" in loc]  # the store was purged in the committed transaction
    p.drain()
    assert not fs.maintenance_active(p) and not Path(old.location).exists()
    assert fs.marker_locations(p.root, tmp_path / "old") == []
    with p.view() as v:
        assert v.execute("SELECT status FROM privacy_operations").fetchall() == [("completed",)]
        assert v.execute("SELECT COUNT(*) FROM backups WHERE state = 'verified'").fetchone()[0] == 1


def test_late_result_of_a_forgotten_call_joins_a_live_task(tmp_path):
    """A call whose start was forgotten gets its result later: the result is new capture, bound to a live task, never the forgotten one.

    Synthetic variant: a rerun of the real ``seq`` call in the forgotten
    session whose result arrives only after the forget of the call's start.
    """
    b = fs.build(tmp_path, deliver=False)
    p = b.p
    pre, post = ds.call_records("toolu_probe_0005", "late", session=fs.SESSION_F)
    p.send(pre)
    p.drain()
    start = p.event("tool_started", call="toolu_probe_0005_late")["id"]
    fs.forget(b, ForgetSelector(record_refs=[RecordRef(kind="event", id=start, revision=1)]))
    assert fs.statuses(p, [("task", b.tasks["forgotten"])])[b.tasks["forgotten"]] in ("quarantined", "forgotten")
    p.send(post)
    p.drain()  # the reducer must neither bind to nor revise a forgotten or quarantined task
    result = p.event("tool_finished", call="toolu_probe_0005_late")["id"]
    task = p.task_of(result)
    assert fs.statuses(p, [("task", task)])[task] in ("active", "paused")
