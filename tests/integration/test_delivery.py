"""Task 12b: delivery accounting, the session overlay and corrections at the final fence (SYSTEM_SPEC §5.1.1–§5.1.2, §8.2–§8.3; DATA_CONTRACTS §2.3, §9–§11; decision 0015).

Inputs are real Claude 2.1.301 payloads through the real adapter, capture,
ingestion, typed reduction and the real extraction/review path with recorded
proposals (``delivery_scenarios``); synthetic variants (a second host
session, reruns under new tool-use IDs, prompt texts) and synthetic store
states are named at each use. Delivery is enabled only in these controlled
test manifests. A hook writing a context envelope is local emission, never a
delivery certification: the nonce protocol and real-host certification are
Task 13 and stay unavailable without a certified route (B1).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import pytest

import delivery_scenarios as ds  # first: puts tests/, tests/integration and tests/platform on sys.path
import admission_scenarios as adm  # noqa: E402
import cli_scenarios as cli  # noqa: E402
import consolidation_scenarios as cs  # noqa: E402
import retrieval_scenarios as rs  # noqa: E402
from recalith.capture import pipeline  # noqa: E402
from recalith.capture.normalize import RawEvent, normalize_event  # noqa: E402
from recalith.contracts.common import REASON_CODES, new_id  # noqa: E402
from recalith.contracts.context import DeliveryReceipt  # noqa: E402
from recalith.errors import RecalithError  # noqa: E402
from recalith.fast import delivery as fd  # noqa: E402
from recalith.fast import entry, failpoints, wire  # noqa: E402
from recalith.fast import context as fc  # noqa: E402
from recalith.retrieval import compile as rc  # noqa: E402
from recalith import service  # noqa: E402
from recalith.storage import db  # noqa: E402

B = ds.fresh_session(1)
C = ds.fresh_session(2)


@pytest.fixture
def built(tmp_path):
    return ds.project(tmp_path)


@pytest.fixture(autouse=True)
def _disarm():
    yield
    failpoints.disarm_all()


def _pre(session: str | None, suffix: str | None = None):
    rec = ds.record("PreToolUse", ds.MID)
    return ds.in_session(rec, session, tool_suffix=suffix) if suffix else ds.in_session(rec, session)


def _caution_tokens(text: str) -> int:
    """Estimated tokens of the rendered caution blocks (each block starts with ``- [advice]``)."""
    blocks = ("\n" + text).split("\n- [")[1:]
    return fc.estimate_tokens("".join("\n- [" + b for b in blocks if b.startswith("caution]")))


def _texts(outputs) -> str:
    return "\n".join(ds.context_text(o) for o in outputs)


# --------------------------------------------------------------------------
# Plan-named tests


def test_counts_only_emitted_revisions(built):
    """Receipts carry exactly the emitted (record, revision, condition digest) items; uncertain attempts are charged, never seen (A24, A59)."""
    p, ids = built
    lesson = ids["lesson"]
    first, out = ds.hook(p, _pre(B))
    assert first["delivery"]["state"] == "emitted" and lesson in _texts(out)
    sid_b = p.sid(B)
    entry_b = ds.scratch(p, sid_b)["entries"][0]
    assert entry_b["state"] == "emitted" and [i["record_id"] for i in entry_b["items"]] == [lesson]
    # The identical next pre-action is suppressed: the emitted key was seen.
    again, out2 = ds.hook(p, _pre(B, "again"))
    assert out2 == [] and again["delivery"]["suppressed"] == 1
    # A failed stdout write (session C) leaves an uncertain attempt: charged, never counted as seen.
    def broken(_data):
        raise OSError("stdout closed")

    failed, _ = ds.hook(p, _pre(C), emit=broken)
    assert failed["delivery"]["state"] == "uncertain" and failed["delivery"]["reason"] == "emission_failed"
    retried, out3 = ds.hook(p, _pre(C, "retry"))
    assert retried["delivery"]["state"] == "emitted" and lesson in _texts(out3)  # repeated: the uncertain one was never seen
    ds.ingest(p)
    rows_b, rows_c = ds.deliveries(p, sid_b), ds.deliveries(p, p.sid(C))
    assert [(r["state"], [i["record_id"] for i in r["items"]]) for r in rows_b] == [("emitted", [lesson])]
    assert rows_b[0]["items"] == entry_b["items"] and rows_b[0]["attempt_id"] == entry_b["attempt_id"]
    assert sorted(r["state"] for r in rows_c) == ["emitted", "uncertain"]
    acc = ds.accounting(p, p.sid(C))
    assert acc["charged"] == ds.scratch(p, p.sid(C))["reserved_tokens"] == sum(r["estimated_tokens"] for r in rows_c)
    assert acc["emitted"] == ds.scratch(p, p.sid(C))["emitted_tokens"] == next(r["estimated_tokens"] for r in rows_c if r["state"] == "emitted")
    # A changed revision resurfaces (synthetic store state: a new revision of the lesson), labeled revision_change.
    revision = rs.restate(p, lesson)
    rs.publish(p)
    changed, out4 = ds.hook(p, _pre(B, "rev"))
    assert changed["delivery"]["state"] == "emitted" and "why: revision_change" in _texts(out4)
    ds.ingest(p)
    assert [i["revision"] for r in ds.deliveries(p, sid_b) for i in r["items"]] == [entry_b["items"][0]["revision"], revision]


def test_concurrent_hooks_preserve_budget(built, monkeypatch):
    """Concurrent hooks of one session: one lock, no lost reservation, no double emission, the allowance holds (A59)."""
    p, ids = built
    _facts = [cs.fact(p, f"The fixture settings file {w} is read before test_mid runs.", subject=f"settings {w}") for w in ("alpha", "beta", "gamma", "delta")]
    rs.publish(p)
    monkeypatch.setattr(fd, "UNCHANGED_SESSION_TOTAL", 450)  # a small allowance so the racing hooks contend for it
    prompts = [wks_prompt(B, f"Check the fixture settings file alpha beta gamma delta before test_mid ({n}).") for n in range(8)]
    for rec in prompts:  # materialize transcripts before the race
        p.replay.prepare(rec)
    results: list = [None] * len(prompts)
    barrier = threading.Barrier(len(prompts))

    def run(i):
        barrier.wait()
        results[i] = ds.hook(p, prompts[i], seconds=5.0)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(prompts))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    sid = p.sid(B)
    s = ds.scratch(p, sid)
    states = [r[0]["delivery"]["state"] for r in results]
    assert set(states) <= {"emitted", "none", "skipped"} and "emitted" in states
    emitted = [r for r in results if r[0]["delivery"]["state"] == "emitted"]
    assert len(emitted) == sum(len(r[1]) for r in results) == len([e for e in s["entries"] if e["state"] == "emitted"])
    assert s["reserved_tokens"] == sum(e["estimated_tokens"] for e in s["entries"]) == s["emitted_tokens"]
    keys = [(i["record_id"], i["revision"], i["condition_digest"]) for e in s["entries"] for i in e["items"]]
    assert len(keys) == len(set(keys))  # an unchanged item is emitted at most once in the session
    assert s["reserved_tokens"] <= 450  # context items only: none may exceed the allowance
    reasons = [r[0]["delivery"].get("reason") for r in results]
    assert all(r in (None, "scratch_lock_timeout", "nothing_to_deliver") for r in reasons), reasons
    ds.ingest(p)
    assert ds.accounting(p, sid)["charged"] == s["reserved_tokens"]
    # Real hook processes racing one pre-action caution in another session: emitted once, accounting consistent.
    procs = []
    for n in range(6):
        rec = _pre(C, f"race{n}")
        path = p.root.parent / f"race-{n}.json"
        procs.append((subprocess.Popen(ds.cf.hook_command(p.root, rec["event"], path), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ds.cf.child_env()), rec, path))
    outs = []
    for proc, rec, _path in procs:
        out, err = proc.communicate(p.replay.prepare(rec), timeout=60)
        assert proc.returncode == 0 and err == b"", err
        outs.append(out)
    sc = ds.scratch(p, p.sid(C))
    emitted_c = [o for o in outs if o]
    replies = [json.loads(path.read_text(encoding="utf-8"))["delivery"] for _proc, _rec, path in procs]
    entries_c = [e for e in sc["entries"] if e["state"] == "emitted"]
    assert len(emitted_c) == len(entries_c) == len([r for r in replies if r["state"] == "emitted"]) >= 1
    keys_c = [(i["record_id"], i["revision"], i["condition_digest"]) for e in entries_c for i in e["items"]]
    assert len(keys_c) == len(set(keys_c))  # never the same caution under the same condition twice
    # One emission per distinct condition. A racing hook whose 50 ms dependency budget ran out (a loaded host)
    # downgrades the caution, and an unknown dependency never matches a checked one (SYSTEM_SPEC §5.1): that
    # emission is a different delivery and must say so; at most one hook emits the checked caution.
    checked = [r for r in replies if r["state"] == "emitted" and "deadline_dependency_unknown" not in r.get("degraded", [])]
    assert len(checked) <= 1
    assert all(ids["lesson"] in ds.context_text(o) for o in emitted_c) and sc["reserved_tokens"] == sum(e["estimated_tokens"] for e in sc["entries"])


def test_unknown_dependency_caution_is_a_distinct_delivery(built, monkeypatch):
    """A hook whose dependency budget is spent downgrades the caution under its own suppression key (A59, SYSTEM_SPEC §5.1).

    Synthetic timing: the budget's stop time is set in the past, as on a
    loaded host. The downgraded caution and the checked caution are each
    emitted once; a repeat of either is suppressed.
    """
    p, ids = built
    real = fc.DependencyBudget.__init__

    def starved(self, deadline=None, **kw):
        real(self, deadline, **kw)
        self.stop = 0.0

    def run(n: int, *, spent: bool):
        monkeypatch.setattr(fc.DependencyBudget, "__init__", starved if spent else real)
        return ds.hook(p, _pre(C, f"dep{n}"))

    first, out1 = run(0, spent=True)
    assert first["delivery"]["state"] == "emitted" and "deadline_dependency_unknown" in first["delivery"]["degraded"]
    checked, out2 = run(1, spent=False)
    assert checked["delivery"]["state"] == "emitted" and "deadline_dependency_unknown" not in checked["delivery"]["degraded"]
    assert ids["lesson"] in _texts(out1) and ids["lesson"] in _texts(out2)
    for n, spent in ((2, False), (3, True)):
        again, out = run(n, spent=spent)
        assert again["delivery"]["state"] == "none" and again["delivery"]["suppressed"] == 1 and out == []
    entries = [e for e in ds.scratch(p, p.sid(C))["entries"] if e["state"] == "emitted"]
    digests = [i["condition_digest"] for e in entries for i in e["items"] if i["record_id"] == ids["lesson"]]
    assert len(entries) == 2 and len(set(digests)) == 2


def wks_prompt(session: str, text: str):
    return ds.wks.variant(ds.record("UserPromptSubmit"), session=session, prompt=text)


def test_failure_overlay_precedes_ingestion(built):
    """A typed failure reaches the next matching pre-action from scratch before ingestion; a later success downgrades the caution (A59)."""
    p, ids = built
    lesson = ids["lesson"]
    pre, post = ds.call_records(ds.MID, "o1", session=B)
    first, out = ds.hook(p, pre)
    assert first["delivery"]["state"] == "emitted" and "[caution]" in _texts(out)
    ds.hook(p, post)  # PostToolUseFailure: the overlay records the typed failure (no worker, no ingestion)
    failure_id = ds.finish_event_id(p, post)
    assert not ds.event_in_store(p, failure_id)
    outcome = ds.scratch(p, p.sid(B))["outcomes"][-1]
    assert outcome["event_id"] == failure_id and outcome["outcome"] == "failure"
    pre2, _ = ds.call_records(ds.MID, "o2", session=B)
    nxt, out2 = ds.hook(p, pre2)
    text = _texts(out2)
    assert nxt["delivery"]["state"] == "emitted" and failure_id in text and "why: recent_observation" in text and "not a durable lesson" in text
    assert lesson not in text  # the unchanged caution stays suppressed
    assert not ds.event_in_store(p, failure_id)  # still ahead of ingestion
    # A later success of the same action family (the real passing result) downgrades the older caution before ingestion.
    pre3, post3 = ds.call_records(ds.MID, "ok", session=C, outcome_of=ds.PASS)
    ds.hook(p, pre3)
    ds.hook(p, post3)
    pre4, _ = ds.call_records(ds.MID, "o4", session=C)
    later, out4 = ds.hook(p, pre4)
    text4 = _texts(out4)
    assert later["delivery"]["state"] == "emitted" and lesson in text4 and "[context]" in text4 and "[caution]" not in text4
    assert "a later run of this action succeeded in this session" in text4


def test_emission_crash_is_uncertain(built, tmp_path):
    """A hook killed between reservation and mark leaves an uncertain, still-charged attempt: never emitted, never lost, never twice (A59)."""
    p, ids = built
    lesson = ids["lesson"]
    for n, (failpoint, stdout_expected) in enumerate(((failpoints.DELIVERY_AFTER_RESERVE, False), (failpoints.DELIVERY_AFTER_EMIT, True), (failpoints.DELIVERY_AFTER_RECEIPT, True))):
        host = ds.fresh_session(10 + n)
        sid = p.sid(host)
        killed = ds.killed_process(p, _pre(host, "k"), tmp_path, failpoint)
        assert killed.returncode == failpoints.KILL_STATUS, killed.stderr[-2000:]
        assert bool(killed.stdout) == stdout_expected and (not killed.stdout or lesson in ds.context_text(killed.stdout))
        s = ds.scratch(p, sid)
        (attempt,) = s["entries"]
        assert attempt["state"] == "reserved" and s["reserved_tokens"] == attempt["estimated_tokens"] and s["emitted_tokens"] == 0
        nxt, out = ds.hook(p, _pre(host, "next"))
        s = ds.scratch(p, sid)
        assert s["entries"][0]["state"] == "uncertain" and s["entries"][0]["receipt_spooled"]
        assert nxt["delivery"]["state"] == "emitted" and lesson in _texts(out)  # never counted as seen: delivered again
        assert s["reserved_tokens"] == sum(e["estimated_tokens"] for e in s["entries"]) and s["emitted_tokens"] == s["entries"][1]["estimated_tokens"]
        ds.ingest(p)
        rows = {r["attempt_id"]: r for r in ds.deliveries(p, sid)}
        assert set(rows) == {attempt["attempt_id"], s["entries"][1]["attempt_id"]}  # one row per attempt: no double count, no lost charge
        # After the receipt was spooled, the emitted receipt wins over the later uncertain one (emitted output is proven).
        expected = "emitted" if failpoint == failpoints.DELIVERY_AFTER_RECEIPT else "uncertain"
        assert rows[attempt["attempt_id"]]["state"] == expected
        acc = ds.accounting(p, sid)
        assert acc["charged"] == s["reserved_tokens"] and acc["attempts"] == 2


def test_compaction_restores_once(built):
    """A host-confirmed compaction restores once per cycle, up to 2,000 including cautions, outside the unchanged allowance (A26, A27 mechanics)."""
    p, ids = built
    lesson = ids["lesson"]
    first, out = ds.hook(p, _pre(B))
    assert lesson in _texts(out)
    pre_compact = ds.in_session(ds.record("PreCompact"), B)
    ds.hook(p, pre_compact)
    restore_rec = ds.in_session(ds.record("SessionStart", n=1), B)  # the real SessionStart(source=compact)
    assert restore_rec["payload"]["source"] == "compact"
    restored, out2 = ds.hook(p, restore_rec)
    text = _texts(out2)
    d = restored["delivery"]
    assert d["state"] == "emitted" and d["purpose"] == "compact_restore" and lesson in text  # repeats what compaction removed
    assert d["estimated_tokens"] <= 2000 and d["substitution_tokens"] == 0
    s = ds.scratch(p, p.sid(B))
    key = s["compaction_key"]
    assert key in s["restored"] and d["restoration_key"] == key and s["restoration_tokens"] == d["estimated_tokens"]
    again, out3 = ds.hook(p, restore_rec)  # the same restoration event again (a host re-fire)
    assert out3 == [] and again["delivery"]["reason"] == "restoration_already_delivered"
    post, out4 = ds.hook(p, ds.in_session(ds.record("PostCompact"), B))
    assert out4 == [] and post["delivery"]["state"] == "none"
    prompt, _ = ds.hook(p, wks_prompt(B, "Run the fixture tests again."))
    assert prompt["delivery"].get("purpose") in (None, "prompt")  # ordinary again
    ds.ingest(p)
    acc = ds.accounting(p, p.sid(B))
    assert acc["restoration"] == d["estimated_tokens"] and acc["ordinary"] == acc["charged"] - acc["restoration"]
    assert fd.charged_ordinary(ds.scratch(p, p.sid(B)), []) == acc["ordinary"]  # the restoration is charged separately
    # Without the compact injection path: the next certified prompt carries the one keyed restoration, once.
    ds.enable(p, ("session_start", "prompt", "pre_action"))
    ds.hook(p, ds.in_session(ds.record("PreCompact"), C))
    unavailable, out5 = ds.hook(p, ds.in_session(ds.record("SessionStart", n=1), C))
    assert out5 == [] and unavailable["delivery"]["state"] == "unavailable"
    fallback, out6 = ds.hook(p, wks_prompt(C, "Continue with the fixture tests."))
    assert fallback["delivery"]["purpose"] == "compact_restore" and fallback["delivery"]["state"] in ("emitted", "none")
    later, _ = ds.hook(p, wks_prompt(C, "And the next step for the fixture tests?"))
    assert later["delivery"]["purpose"] == "prompt"


def test_correction_before_fence_removes_guidance(built, tmp_path):
    """A correction through the real guarded CLI committed before the final fence suppresses the old text; one committed after it is recorded as in flight (A25)."""
    p, ids = built
    lesson = ids["lesson"]
    token = tmp_path / "op.token"
    cli.register(p.root, cli.token(token))
    rev = adm.head(p, lesson)["revision"]

    def correct(claim_id: str, revision: int):
        def action(_name: str) -> None:
            result = cli.cli(p.root, "--json", "--operator-token-file", str(token), "correct", claim_id, "--expected-revision", str(revision), "--statement", "Rerunning test_mid is fine once the fixture is fixed.")
            assert result.code == 0, result.stdout + result.stderr

        return action

    epoch = ds.meta(p).guidance_epoch
    failpoints.arm(failpoints.DELIVERY_AFTER_RESERVE, correct(lesson, rev))
    raced, out = ds.hook(p, _pre(B))
    assert ds.meta(p).guidance_epoch > epoch and adm.head(p, lesson)["status"] == "invalidated"  # committed before the fence
    assert out == [] and raced["delivery"]["state"] == "fenced_out" and raced["delivery"]["reason"] == "fence_epoch_changed"
    s = ds.scratch(p, p.sid(B))
    assert s["entries"] == [] and s["reserved_tokens"] == 0  # no output, so the reservation is withdrawn
    after, out2 = ds.hook(p, _pre(B, "after"))
    assert lesson not in _texts(out2)  # the old guidance never reaches the host
    # In flight: a correction committed after the fence and before stdout races the emission; recorded, never claimed retracted.
    other = cs.lesson(p, "Rerunning test_mid without the fixture value fails again.", subject="mid again")
    rs.publish(p)
    failpoints.arm(failpoints.DELIVERY_AFTER_FENCE, correct(other, adm.head(p, other)["revision"]))
    flight, out3 = ds.hook(p, _pre(C))
    assert flight["delivery"]["state"] == "emitted" and other in _texts(out3) and flight["delivery"]["in_flight_change"] is True
    assert adm.head(p, other)["status"] == "invalidated"
    ds.ingest(p)
    (row,) = ds.deliveries(p, p.sid(C))
    assert row["state"] == "emitted" and row["in_flight_change"] == 1 and row["fenced_at"] <= row["emitted_at"]
    nxt, out4 = ds.hook(p, _pre(C, "next"))
    assert other not in _texts(out4)  # the next delivery excludes it


# --------------------------------------------------------------------------
# Real hook processes on real payloads (A24–A27 mechanics, A41, A59, A72)


def test_real_hook_processes_deliver_and_account(built, tmp_path):
    """The lifecycle replayed through real hook processes with delivery enabled in a controlled manifest."""
    p, ids = built
    lesson = ids["lesson"]
    host = ds.fresh_session(30)
    sid = p.sid(host)
    epoch = ds.meta(p).guidance_epoch
    pre, post = ds.call_records(ds.MID, "rp", session=host)
    pre2, _ = ds.call_records(ds.MID, "rp2", session=host)
    script = [
        ds.in_session(ds.record("SessionStart"), host), wks_prompt(host, "Fix the fixture so test_mid passes."), pre, post, pre2,
        ds.in_session(ds.record("Stop"), host),
        ds.in_session(ds.record("PreCompact"), host), ds.in_session(ds.record("SessionStart", n=1), host), ds.in_session(ds.record("PostCompact"), host),
    ]
    replies, outputs = [], []
    for n, rec in enumerate(script):
        proc, reply = ds.process(p, rec, tmp_path, tag=str(n))
        assert proc.returncode == 0 and proc.stderr == b"", proc.stderr[-2000:]  # nonblocking success, always (A72)
        if proc.stdout:
            data = json.loads(proc.stdout.decode("utf-8"))
            assert set(data) == {"hookSpecificOutput"} and set(data["hookSpecificOutput"]) == {"hookEventName", "additionalContext"}  # never a decision or block
            assert data["hookSpecificOutput"]["hookEventName"] == rec["event"]
        assert reply["receipt"]["status"] == "accepted"
        assert reply["delivery"]["state"] != "skipped", (rec["event"], reply["delivery"], reply.get("elapsed_ms"))
        replies.append(reply)
        outputs.append(proc.stdout)
    start, prompt, pre_r, post_r, pre2_r, stop_r, _pc, restore_r, _post = replies
    assert start["delivery"]["purpose"] == "session_start"  # workspace-only lookup without a binding (no task yet)
    assert pre_r["delivery"]["state"] == "emitted" and "[caution]" in ds.context_text(outputs[2]) and lesson in ds.context_text(outputs[2])
    assert post_r["delivery"]["state"] == "none" and stop_r["delivery"]["state"] == "none"
    text2 = ds.context_text(outputs[4])
    assert pre2_r["delivery"]["state"] == "emitted" and lesson not in text2 and "recent_observation" in text2  # suppressed caution; overlay failure
    assert restore_r["delivery"]["purpose"] == "compact_restore" and lesson in ds.context_text(outputs[7])
    for out in outputs:
        if out:
            item_whys = [line.split("why: ")[1].split(" ")[0] for line in ds.context_text(out).splitlines() if line.strip().startswith("why: ")]
            assert item_whys and set(item_whys) <= set(REASON_CODES)  # first why is a registered reason code (A72)
    p.drain()  # the worker ingests the receipts as bookkeeping
    rows = ds.deliveries(p, sid)
    emitted_replies = [r for r in replies if r["delivery"]["state"] == "emitted"]
    assert sorted(r["attempt_id"] for r in rows) == sorted(r["delivery"]["attempt_id"] for r in emitted_replies)
    assert all(r["state"] == "emitted" for r in rows)
    # The session's own events (a failure, a task) moved the guidance epoch; the worker republished; receipts alone
    # never do (isolated in test_receipts_are_bookkeeping_and_views_stay_valid, A41).
    assert ds.meta(p).guidance_epoch >= epoch
    with db.open_store(p.ctx, readonly=True) as store:
        assert rc.projection_due(store)["views"] is False
    with p.view() as v:
        receipts = [r[0] for r in v.execute("SELECT event_id FROM events WHERE kind = 'memory_delivered'").fetchall()]
        marks = ",".join("?" for _ in receipts)
        assert receipts and v.execute(f"SELECT COUNT(*) FROM root_event_members WHERE event_id IN ({marks})", receipts).fetchone()[0] == 0  # noqa: S608 - never a root
    _proc, end = ds.process(p, ds.in_session(ds.record("SessionEnd"), host), tmp_path, tag="end")
    assert end["receipt"]["status"] == "accepted" and ds.scratch(p, sid) is None  # discarded at session end


def test_session_start_without_binding_uses_workspace_lookup(built):
    """With no worker-established binding, session start reads the (workspace, null task, session_start) view (A58)."""
    p, _ids = built
    host = ds.fresh_session(40)
    reply, _ = ds.hook(p, ds.in_session(ds.record("SessionStart"), host))
    assert reply["delivery"]["purpose"] == "session_start"
    q = fd.build_query(entry.load_context(str(p.root), "claude_code"), {"events": [{"session_id": p.sid(host), "payload": {}, "kind": "session_started"}]}, "session_start")
    compiled = ds.rs.cache.compile_packet(entry.load_context(str(p.root), "claude_code"), q, deadline=time.monotonic() + 5)
    assert compiled["task_id"] is None and compiled["source"] == "view"
    # The real lifecycle session has a binding: its resumed start is task-scoped.
    bound = fd.build_query(entry.load_context(str(p.root), "claude_code"), {"events": [{"session_id": p.session_of(), "payload": {}, "kind": "session_started"}]}, "session_start")
    assert ds.rs.cache.compile_packet(entry.load_context(str(p.root), "claude_code"), bound, deadline=time.monotonic() + 5)["task_id"] is not None


# --------------------------------------------------------------------------
# Budgets and suppression (A26, A59)


def test_prompt_substitution_is_one_shared_allowance(built):
    """Without pre-action injection the next prompt carries the caution in one shared ≤400 allowance, ≤1,400 total; no multiplier, no bonus without a caution."""
    p, ids = built
    second = cs.lesson(p, "Rerunning test_mid without the fixture value fails again.", subject="mid again")
    third = cs.lesson(p, "Rerunning test_mid while dep.txt is unchanged fails the same way every time.", subject="mid unchanged")
    rs.publish(p)
    ds.enable(p, ("session_start", "prompt"))
    plain, out0 = ds.hook(p, wks_prompt(B, "Explain the fixture layout."))
    assert plain["delivery"].get("substitution_tokens", 0) == 0  # no action yet: no caution, no bonus
    pre, post = ds.call_records(ds.MID, "s1", session=B)
    unavailable, out1 = ds.hook(p, pre)
    assert out1 == [] and unavailable["delivery"] == {"state": "unavailable", "purpose": "pre_action", "reason": "path_not_installed"}
    ds.hook(p, post)
    reply, out = ds.hook(p, wks_prompt(B, "Run test_mid again."))
    d = reply["delivery"]
    text = _texts(out)
    assert d["state"] == "emitted" and "[caution]" in text
    assert 0 < d["substitution_tokens"] <= 400 and d["estimated_tokens"] <= 1400 and d["estimated_tokens"] - d["substitution_tokens"] <= 1000
    cautions = text.count("[caution]")
    # Three eligible cautions (each about 200 estimated tokens) share the one allowance; any excess rides the
    # ordinary 1,000 or is omitted, never a second 400 (no per-caution multiplier).
    assert cautions >= 2 and sum(x in text for x in (ids["lesson"], second, third)) >= 2
    assert _caution_tokens(text) > 400 >= d["substitution_tokens"]  # more caution text than one allowance, still one allowance
    entry_ = ds.scratch(p, p.sid(B))["entries"][-1]
    assert entry_["estimated_tokens"] == d["estimated_tokens"] and entry_["substitution_tokens"] == d["substitution_tokens"]  # complete charging
    assert d["estimated_tokens"] == fc.estimate_tokens(text)


def test_condition_aware_suppression(built):
    """Unchanged deliveries are suppressed; a changed consulted condition or revision resurfaces; the branch alone does not (A26)."""
    p, ids = built
    lesson = ids["lesson"]
    first, out = ds.hook(p, _pre(B))
    assert "[caution]" in _texts(out)
    same, out2 = ds.hook(p, _pre(B, "s2"))
    assert out2 == [] and same["delivery"]["suppressed"] == 1
    (p.root / ".git").mkdir()
    (p.root / ".git" / "HEAD").write_text("ref: refs/heads/feature-x\n", encoding="utf-8")  # synthetic variant: a branch
    assert fd.read_branch(str(p.root)) == "feature-x"
    branch, out3 = ds.hook(p, _pre(B, "s3"))
    assert out3 == []  # no claim consults the branch: the branch name alone never resurfaces a caution
    (p.root / cs.DEP).write_bytes(b"fixture v2\n")  # the lesson's live dependency changed (outside any captured tool)
    dep, out4 = ds.hook(p, _pre(B, "s4"))
    text4 = _texts(out4)
    assert lesson in text4 and "[caution]" not in text4  # a changed consulted value: a new key, downgraded to context
    (p.root / cs.DEP).write_bytes(b"fixture v1\n")
    back, out5 = ds.hook(p, _pre(B, "s5"))
    assert out5 == []  # back to the delivered caution's exact key: still suppressed


def test_open_question_is_delivered_once_per_session(built):
    """An open intent question is one conflict item, delivered once per session across purposes; new members resurface it (A26)."""
    p, _ids = built
    cs.declaration(p, "We use tabs for indentation in this repository.", "Indentation uses tabs.", subject="indentation")
    b = cs.declaration(p, "We use spaces for indentation in this repository.", "Indentation uses spaces.", subject="indentation")
    p.drain()  # the planner opens the question
    rs.publish(p)
    start, out = ds.hook(p, ds.in_session(ds.record("SessionStart"), B))
    text = _texts(out)
    assert start["delivery"]["state"] == "emitted" and text.count("[conflict]") == 1 and "Open question" in text
    prompt, out2 = ds.hook(p, wks_prompt(B, "Should the fixture use tabs or spaces for indentation?"))
    assert "Open question" not in _texts(out2) and prompt["delivery"].get("suppressed", 0) >= 1  # deduplicated in this session
    other, out3 = ds.hook(p, ds.in_session(ds.record("SessionStart"), C))
    assert "Open question" in _texts(out3)  # another session sees it once too
    # A changed member revision (synthetic store state) is a changed question: it resurfaces.
    rs.restate(p, b)
    rs.publish(p)
    again, out4 = ds.hook(p, wks_prompt(B, "Tabs or spaces for indentation, again?"))
    assert again["delivery"]["state"] == "emitted" and "Open question" in _texts(out4)


def test_zero_budget_and_deadline_shedding(built, monkeypatch):
    """Zero allowance, an elapsed deadline and a slow filesystem: capture first, no reservation without time, exit 0 (A58)."""
    p, ids = built
    # An exhausted unchanged-memory allowance: ordinary context is withheld, a caution (critical) still goes and is charged.
    monkeypatch.setattr(fd, "UNCHANGED_SESSION_TOTAL", 0)
    ctx_only, out = ds.hook(p, wks_prompt(B, "Explain the fixture test_mid lesson."))
    assert out == [] and ctx_only["delivery"]["state"] == "none" and "session_budget_exhausted" in ctx_only["delivery"]["degraded"]
    assert ds.scratch(p, p.sid(B)) is None or ds.scratch(p, p.sid(B))["reserved_tokens"] == 0
    caution, out2 = ds.hook(p, _pre(B))
    assert caution["delivery"]["state"] == "emitted" and "[caution]" in _texts(out2)
    assert ds.scratch(p, p.sid(B))["reserved_tokens"] == caution["delivery"]["estimated_tokens"] > 0
    monkeypatch.undo()
    # The soft deadline has already elapsed: capture is still durable; delivery is skipped with no reservation.
    late, out3 = ds.hook(p, _pre(C), seconds=-0.01)
    assert late["receipt"]["status"] == "accepted" and out3 == [] and late["delivery"]["reason"] == "deadline_delivery_skipped"
    assert ds.scratch(p, p.sid(C)) is None
    # A slow filesystem (every fsync takes 300 ms): capture overruns and is still acknowledged; delivery and the overlay are shed.
    real_fsync = os.fsync

    def slow(fd_):
        time.sleep(0.3)
        return real_fsync(fd_)

    monkeypatch.setattr(os, "fsync", slow)
    started = time.monotonic()
    slow_reply, out4 = ds.hook(p, _pre(ds.fresh_session(50)), seconds=0.25)
    assert slow_reply["receipt"]["status"] == "accepted" and "capture_deadline_overrun" in slow_reply["degradations"]
    assert out4 == [] and slow_reply["delivery"]["reason"] == "deadline_delivery_skipped"
    assert time.monotonic() - started < 5


def test_receipts_are_bookkeeping_and_views_stay_valid(built):
    """Receipt ingestion advances only the store revision; the next hook still serves the same view (A41)."""
    p, ids = built
    ds.hook(p, _pre(B))
    before = ds.meta(p)
    ds.ingest(p)
    after = ds.meta(p)
    assert after.store_revision > before.store_revision and after.guidance_epoch == before.guidance_epoch
    with db.open_store(p.ctx, readonly=True) as store:
        assert rc.projection_due(store)["views"] is False
    nxt, out = ds.hook(p, _pre(C))
    assert nxt["delivery"]["source"] == "view" and ids["lesson"] in _texts(out)


# --------------------------------------------------------------------------
# Outcome links, service receipts, gating and schema


def test_outcome_links_record_observations_never_support(built):
    """Follow-up events are linked by observed evidence only; an agent acknowledgment is never support or task success."""
    p, ids = built
    lesson = ids["lesson"]
    pre, post = ds.call_records(ds.MID, "l1", session=B)
    reply, _ = ds.hook(p, pre)
    ds.hook(p, post)
    before = cs.claim(p, lesson)
    raw = RawEvent(adapter_id="claude_code", adapter_version="2.1.301", source_event_key=f"{B}:transcript:ack-1", session_id=p.sid(B), host_session_id=B, kind="assistant_message",
                   payload={"text": f"Following the memory ({lesson}), I will not rerun test_mid until the fixture is fixed.", "sidechain": False}, origin_kind="transcript")
    envelopes, _ = normalize_event(p.ctx, raw)  # synthetic variant of a transcript-supplement assistant record
    assert pipeline.capture(p.ctx, envelopes).status == "accepted"
    p.drain()
    delivery_id = fd.delivery_id_of(reply["delivery"]["attempt_id"])
    labels = {(label, tuple(obs)) for d, label, obs in ds.links(p) if d == delivery_id}
    assert ("task_failed", (ds.finish_event_id(p, post),)) in labels  # the certified failing test result
    assert ("acknowledged", (envelopes[0].event_id,)) in labels
    assert not any(label == "task_succeeded" for label, _ in labels)
    after = cs.claim(p, lesson)
    assert (after.revision, after.strength, after.status, after.supports) == (before.revision, before.strength, before.status, before.supports)
    with p.view() as v:
        receipts = {r[0] for r in v.execute("SELECT event_id FROM events WHERE kind = 'memory_delivered'").fetchall()}
        cited = {r[0] for r in v.execute("SELECT target_id FROM evidence_links WHERE relation = 'supports'").fetchall()}
        roots = {r[0] for r in v.execute("SELECT event_id FROM root_event_members").fetchall()}
    assert receipts and not (receipts | {envelopes[0].event_id}) & cited and not receipts & roots  # never support, never a root


def test_service_record_delivery_spools_and_ingestion_accounts_once(built):
    """``record_delivery`` spools a receipt; ingestion owns the row; retries are duplicates; emitted wins over uncertain."""
    p, ids = built
    q = rs.query(p, act=rs.mid_action(p))
    packet = rc.compile_context(p.ctx, q)
    sid = new_id("sess")
    attempt = new_id("att")
    uncertain = service.record_delivery(p.ctx, packet, sid, emitted=False, attempt_id=attempt)
    assert isinstance(uncertain, DeliveryReceipt) and uncertain.state == "uncertain" and ds.deliveries(p, sid) == []  # not until ingestion
    ds.ingest(p)
    assert [r["state"] for r in ds.deliveries(p, sid)] == ["uncertain"]
    service.record_delivery(p.ctx, packet, sid, attempt_id=attempt)
    service.record_delivery(p.ctx, packet, sid, attempt_id=attempt)  # a retry: a duplicate event
    ds.ingest(p)
    rows = ds.deliveries(p, sid)
    assert [r["state"] for r in rows] == ["emitted"] and ds.accounting(p, sid)["charged"] == packet.estimated_tokens
    service.record_delivery(p.ctx, packet, sid, emitted=False, attempt_id=attempt)
    ds.ingest(p)
    assert [r["state"] for r in ds.deliveries(p, sid)] == ["emitted"]  # never downgraded
    foreign = packet.model_copy(update={"installation_id": new_id("inst")})
    with pytest.raises(RecalithError):
        service.record_delivery(p.ctx, foreign, sid)


def test_delivery_stays_gated(built, tmp_path):
    """Delivery needs an explicit manifest path and a certified host version; schemas 1–2 never deliver."""
    p, _ids = built
    ds.enable(p, ())
    off, out = ds.hook(p, _pre(B))
    assert out == [] and off["delivery"] == {"state": "unavailable", "reason": "delivery_not_enabled"}
    ds.write_hook_context(p.ctx, adapter_id="claude_code", host_version="2.1.303", delivery_paths=list(ds.ALL_PATHS))
    newer, out2 = ds.hook(p, _pre(B, "v"))
    assert out2 == [] and newer["delivery"]["reason"] == "host_version_uncertified"
    manifest = json.loads((p.root / entry.HOOK_CONTEXT_FILE).read_text(encoding="utf-8"))
    for bad in (
        {**manifest, "context_schema": 2},
        {**manifest, "adapters": {"claude_code": {"host_version": "2.1.301", "delivery_enabled": True, "delivery_paths": ["everything"]}}},
        {**manifest, "adapters": {"claude_code": {"host_version": "2.1.301", "delivery_enabled": False, "delivery_paths": ["prompt"]}}},
        {**manifest, "context_schema": 2, "adapters": {"claude_code": {"host_version": "2.1.301", "delivery_enabled": True}}},
    ):
        assert not entry.valid_context_manifest(bad)
    with pytest.raises(RecalithError):
        ds.write_hook_context(p.ctx, adapter_id="claude_code", host_version="2.1.301", delivery_paths=["everything"])


def test_receipt_wire_agrees_with_strict_contract(built):
    """The stdlib receipt the hook spools validates under both the generated wire tables and the strict model."""
    p, ids = built
    reply, _ = ds.hook(p, _pre(B))
    receipt = reply["emitted_receipt"]
    assert wire.is_valid("DeliveryReceipt", receipt)
    DeliveryReceipt.model_validate(receipt)
    for bad in ({**receipt, "state": "uncertain"}, {**receipt, "restoration_key": receipt["trigger_event_id"]}, {**receipt, "pre_action_substitution_tokens": receipt["estimated_tokens"] + 1}):
        assert not wire.is_valid("DeliveryReceipt", bad)
        with pytest.raises(ValueError):
            DeliveryReceipt.model_validate(bad)


def test_older_development_store_is_refused(tmp_path):
    """Schema 8 refuses a schema-7 development store; it is never migrated silently (decisions 0007–0015)."""
    p = rs.project(tmp_path)
    path = p.root / ".recalith" / db.STATE_DB
    raw = db.sqlite3.connect(path)
    raw.execute("UPDATE installation_meta SET schema_version = 7")
    raw.execute("PRAGMA user_version = 7")
    raw.commit()
    raw.close()
    with pytest.raises(RecalithError) as refused:
        db.open_store(p.ctx)
    assert refused.value.code == "invalid_schema"


# --------------------------------------------------------------------------
# WAL/SHM and a live checkpoint (A58, delivery side)

# A bookkeeping-only write (SQLite skips rewriting identical rows, so the value really changes): a worker's
# transaction that never touches servable state, so the hook's packets stay valid across it.
WRITER = r"""
import sqlite3, sys, time, os
conn = sqlite3.connect(sys.argv[1], isolation_level=None, timeout=5)
conn.execute("PRAGMA wal_autocheckpoint = 0")
mode = sys.argv[2]
def write(n):
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("UPDATE projection_state SET updated_at = ? WHERE singleton = 1", ("2026-01-01T00:00:%02d.000000Z" % (n % 60),))
    conn.execute("COMMIT")
if mode == "crash":
    write(1)
    os._exit(9)  # leaves the WAL (and its SHM) behind, no checkpoint
stop = time.monotonic() + float(sys.argv[3])
print("ready", flush=True)
n = 0
while time.monotonic() < stop:
    n += 1
    write(n)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
"""


def _store(p) -> str:
    return str(p.root / ".recalith" / db.STATE_DB)


def _delivers_or_degrades(p, rec, *, seconds: float = 1.0):
    started = time.monotonic()
    reply, out = ds.hook(p, rec, seconds=seconds)
    elapsed = time.monotonic() - started
    assert elapsed < 2.0 and reply["receipt"]["status"] == "accepted"
    d = reply["delivery"]
    assert d["state"] in ("emitted", "none", "skipped", "fenced_out"), d
    if d["state"] != "emitted":
        assert out == []
    return reply, out


@pytest.mark.parametrize("shm", ["present", "missing", "unreadable"])
def test_crashed_worker_wal_never_repaired_by_the_hook(built, shm):
    """A crashed writer left its WAL: the hook delivers or degrades at once and never checkpoints or recovers (A58)."""
    p, _ids = built
    if shm == "unreadable" and (os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0)):
        pytest.skip("permission bits do not bind here (Windows ACLs or root); the present/missing variants run")
    crashed = subprocess.run([sys.executable, "-I", "-c", WRITER, _store(p), "crash"], capture_output=True, timeout=60)
    assert crashed.returncode == 9, crashed.stderr
    wal = _store(p) + "-wal"
    shm_path = _store(p) + "-shm"
    assert os.path.exists(wal) and os.path.getsize(wal) > 0
    if shm == "missing" and os.path.exists(shm_path):
        os.remove(shm_path)
    if shm == "unreadable":
        os.chmod(shm_path, 0)
    db_bytes = (p.root / ".recalith" / db.STATE_DB).read_bytes()
    wal_size = os.path.getsize(wal)
    try:
        _delivers_or_degrades(p, _pre(B))
        assert (p.root / ".recalith" / db.STATE_DB).read_bytes() == db_bytes and os.path.getsize(wal) == wal_size  # no checkpoint or recovery write
    finally:
        if shm == "unreadable":
            os.chmod(shm_path, 0o600)


def test_live_worker_mid_checkpoint(built):
    """A live writer checkpointing in a loop: hooks deliver or degrade within their bound and never wait or fail (A58)."""
    p, ids = built
    writer = subprocess.Popen([sys.executable, "-I", "-c", WRITER, _store(p), "loop", "6"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert writer.stdout.readline().strip() == b"ready"
        states = []
        for n in range(8):
            reply, out = _delivers_or_degrades(p, _pre(ds.fresh_session(60 + n)))
            states.append(reply["delivery"]["state"])
            if out:
                assert ids["lesson"] in _texts(out)
        assert "emitted" in states or all(s in ("skipped", "fenced_out") for s in states)
    finally:
        writer.kill()
        writer.communicate(timeout=30)
