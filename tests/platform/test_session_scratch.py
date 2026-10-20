"""Session scratch on each native platform (SYSTEM_SPEC §5.1.2; DATA_CONTRACTS §2.3; decision 0015).

The per-session lock is ``flock`` on POSIX and ``msvcrt.locking`` on Windows;
these tests run natively on every CI runner, so a Windows behavior is claimed
only from the Windows job. Hooks run the real delivery branch over real
Claude 2.1.301 payloads (``delivery_scenarios``); scratch files built by hand
are **synthetic scratch states**, named at each use.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "integration"))

import delivery_scenarios as ds  # noqa: E402
from recalith.contracts.common import new_id, utc_now  # noqa: E402
from recalith.fast import delivery as fd  # noqa: E402
from recalith.fast import session, wire  # noqa: E402
from recalith.storage import db  # noqa: E402

B = ds.fresh_session(1)
HOLDER = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from recalith.fast import session
lock = session.SessionLock(sys.argv[2], sys.argv[3])
assert lock.acquire(5)
print("held", flush=True)
time.sleep(float(sys.argv[4]))
"""


@pytest.fixture
def built(tmp_path):
    return ds.project(tmp_path)


def _hold(root, session_id: str, seconds: float) -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "-I", "-c", HOLDER, ds.SRC, str(root), session_id, str(seconds)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout.readline().strip() == b"held", proc.stderr.read()
    return proc


def _stop(proc: subprocess.Popen) -> None:
    proc.kill()
    proc.communicate(timeout=30)


def _pre(session_: str, suffix: str | None = None):
    rec = ds.record("PreToolUse", ds.MID)
    return ds.in_session(rec, session_, tool_suffix=suffix) if suffix else ds.in_session(rec, session_)


def test_lock_is_exclusive_across_processes_and_bounded(tmp_path):
    """Another process holds the session lock: acquisition gives up within its bound; the OS releases it when the holder dies."""
    sid = new_id("sess")
    holder = _hold(tmp_path, sid, 30)
    try:
        lock = session.SessionLock(tmp_path, sid)
        started = time.monotonic()
        assert lock.acquire(session.LOCK_WAIT_SECONDS) is False
        assert time.monotonic() - started < 0.5  # 20 ms nominal, scheduling slack only
    finally:
        _stop(holder)
    lock = session.SessionLock(tmp_path, sid)
    assert lock.acquire(2.0) is True
    lock.release()


def test_lock_timeout_skips_delivery_never_capture(built):
    """A held session lock: the hook still captures durably and skips delivery with a reason (no unlocked write)."""
    p, _ids = built
    sid = p.sid(B)
    holder = _hold(p.root, sid, 30)
    try:
        started = time.monotonic()
        reply, out = ds.hook(p, _pre(B))
        assert reply["receipt"]["status"] == "accepted" and out == []
        assert reply["delivery"]["reason"] == "scratch_lock_timeout" and "scratch_lock_timeout" in reply["degradations"]
        assert ds.scratch(p, sid) is None and time.monotonic() - started < 3
    finally:
        _stop(holder)
    reply, out = ds.hook(p, _pre(B, "after"))
    assert reply["delivery"]["state"] == "emitted" and out


def test_unsupported_lock_disables_scratch_delivery(built, monkeypatch):
    p, _ids = built
    monkeypatch.setattr(session, "locking_supported", lambda: False)
    reply, out = ds.hook(p, _pre(B))
    assert reply["receipt"]["status"] == "accepted" and out == [] and reply["delivery"]["reason"] == "scratch_lock_unsupported"


def test_atomic_replace_survives_an_interrupted_write(built):
    """A writer that died before its rename leaves the previous scratch intact; the next locked write replaces it whole."""
    p, _ids = built
    reply, _ = ds.hook(p, _pre(B))
    sid = p.sid(B)
    before = ds.scratch(p, sid)
    path = Path(session.scratch_path(p.root, sid))
    (path.parent / f"{path.name}.99999.tmp").write_bytes(path.read_bytes()[:40])  # a torn temp file of a dead writer
    assert ds.scratch(p, sid) == before
    _pre_rec, post = ds.call_records(ds.MID, "t1", session=B)
    ds.hook(p, post)  # the next locked writer: the typed-outcome overlay
    after = ds.scratch(p, sid)
    assert after is not None and after["state_revision"] > before["state_revision"] and after["reserved_tokens"] == before["reserved_tokens"]


def _entry(tokens: int, state: str = "emitted", *, spooled: bool = True) -> dict:
    return {
        "attempt_id": new_id("att"), "packet_digest": "0" * 64, "items": [{"record_id": new_id("claim"), "revision": 1, "condition_digest": "1" * 64}],
        "state": state, "purpose": "prompt", "estimated_tokens": tokens, "time": utc_now(), "substitution_tokens": 0, "task_id": None, "restoration_key": None,
        "trigger_event_id": None, "generated_at": utc_now(), "fence_store_revision": 1, "guidance_epoch": 1, "policy_revision": 1, "tombstone_epoch": 0, "receipt_spooled": spooled,
        "emitted_at": utc_now() if state == "emitted" else None, "fenced_at": None, "in_flight_change": None,
    }


def test_eviction_never_resets_totals():
    """Pruning drops only durably accounted entries; the running totals and the durable floor never go down (synthetic scratch state)."""
    sid = new_id("sess")
    s = session.empty_scratch(sid, 1)
    while len(wire.canonical_json(s)) < session.SCRATCH_CAP - 2048:
        s["entries"].append(_entry(10))  # synthetic scratch state at its size cap
    total = 10 * len(s["entries"])
    s["reserved_tokens"] = s["emitted_tokens"] = total
    assert wire.is_valid("SessionScratch", s)
    everything = {e["attempt_id"] for e in s["entries"]}
    durable = {e["attempt_id"] for e in s["entries"][:100]}
    fd._prune(s, durable)
    removed = everything - {e["attempt_id"] for e in s["entries"]}
    assert removed and removed <= durable
    assert s["reserved_tokens"] == total  # counters never reset on pruning
    rows = [{"attempt_id": a, "estimated_tokens": 10, "restoration_key": None} for a in durable]
    assert fd.charged_ordinary(s, rows) == total
    # Nothing durable yet at capacity: nothing is pruned (the hook then withholds optional output: ``scratch_capacity``).
    full = session.empty_scratch(sid, 1)
    while len(wire.canonical_json(full)) < session.SCRATCH_CAP - 2048:
        full["entries"].append(_entry(10))
    count = len(full["entries"])
    fd._prune(full, set())
    assert len(full["entries"]) == count


def test_capacity_withholds_output_until_accounting_catches_up(built):
    """A full scratch whose entries are not yet durably accounted: no reservation, no output, no exceeded limit."""
    p, _ids = built
    sid = p.sid(B)
    s = session.empty_scratch(sid, 1)
    while len(s["entries"]) < session.MAX_ENTRIES and len(wire.canonical_json(s)) < session.SCRATCH_CAP - fd.SCRATCH_HEADROOM // 2:
        s["entries"].append(_entry(1))  # synthetic scratch state: full by size, nothing durable yet
    s["reserved_tokens"] = s["emitted_tokens"] = len(s["entries"])
    Path(session.sessions_dir(p.root)).mkdir(parents=True, exist_ok=True)
    session.write(p.root, s)
    reply, out = ds.hook(p, _pre(B))
    assert out == [] and reply["delivery"]["reason"] == "scratch_capacity"
    assert ds.scratch(p, sid)["reserved_tokens"] == len(s["entries"])


def test_resumed_session_recovers_accounting_from_receipts(built):
    """After session end the scratch is gone; the resumed session's totals and suppression come from durable receipts; idle files expire after 24 h."""
    p, ids = built
    sid = p.sid(B)
    first, out = ds.hook(p, _pre(B))
    assert out
    charged = ds.scratch(p, sid)["reserved_tokens"]
    ds.hook(p, ds.in_session(ds.record("SessionEnd"), B))
    assert ds.scratch(p, sid) is None
    ds.ingest(p)
    resumed, out2 = ds.hook(p, _pre(B, "resumed"))  # same host session: the same Recalith session
    assert out2 == [] and resumed["delivery"]["suppressed"] == 1  # the durable emitted receipt still suppresses
    scratch = ds.scratch(p, sid)
    with p.view() as v:
        durable = [{"attempt_id": a, "estimated_tokens": t, "restoration_key": k} for a, t, k in v.execute("SELECT attempt_id, estimated_tokens, restoration_key FROM deliveries WHERE session_id = ?", (sid,)).fetchall()]
    assert fd.charged_ordinary(scratch, durable) == charged
    # Abandoned scratch: removed after 24 hours without activity (counters live on in the durable receipts).
    assert session.prune_abandoned(p.root, now=time.time() + 25 * 3600) >= 1
    assert ds.scratch(p, sid) is None


def test_epoch_mismatch_invalidates_overlay_not_totals(built):
    """A tombstone epoch change (synthetic store state; Task 16 owns forgetting) clears old overlay content; the totals stay."""
    p, _ids = built
    sid = p.sid(B)
    pre, post = ds.call_records(ds.MID, "e1", session=B)
    ds.hook(p, pre)
    ds.hook(p, post)
    before = ds.scratch(p, sid)
    assert before["outcomes"] and before["reserved_tokens"] > 0
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        txn.execute("UPDATE installation_meta SET tombstone_epoch = tombstone_epoch + 1 WHERE singleton = 1")
        txn.mutated(serving_relevant=True)
    ds.rs.publish(p)
    reply, out = ds.hook(p, _pre(B, "e2"))
    after = ds.scratch(p, sid)
    assert after["outcomes"] == [] and after["reserved_tokens"] >= before["reserved_tokens"]
    assert "scratch_epoch_reset" in reply["delivery"].get("degraded", [])
    assert ds.finish_event_id(p, post) not in "".join(ds.context_text(o) for o in out)  # old overlay bytes never bypass the fence


def test_invalid_scratch_is_floored_by_durable_receipts(built):
    """An unreadable or invalid scratch is never trusted; the durable receipts floor the session's totals."""
    p, _ids = built
    sid = p.sid(B)
    ds.hook(p, _pre(B))
    charged = ds.scratch(p, sid)["reserved_tokens"]
    ds.ingest(p)
    Path(session.scratch_path(p.root, sid)).write_text("{not json", encoding="utf-8")
    reply, out = ds.hook(p, _pre(B, "inv"))
    assert "scratch_invalid" in reply["delivery"].get("degraded", [])
    assert out == []  # suppression still comes from the durable emitted receipt
    with p.view() as v:
        durable = [{"attempt_id": a, "estimated_tokens": t, "restoration_key": k} for a, t, k in v.execute("SELECT attempt_id, estimated_tokens, restoration_key FROM deliveries WHERE session_id = ?", (sid,)).fetchall()]
    assert fd.charged_ordinary(ds.scratch(p, sid), durable) >= charged


def test_receipts_owed_are_respooled_and_settled_before_discard(built, tmp_path):
    """A receipt the spool refused (disk full) is re-spooled by the next hook; session end settles dead reservations before discarding."""
    from recalith.fast import failpoints

    p, _ids = built
    sid = p.sid(B)
    failpoints.arm(failpoints.DELIVERY_AFTER_EMIT, lambda _n: failpoints.arm(failpoints.SPOOL_FSYNC, failpoints.DISK_FULL))
    try:
        reply, out = ds.hook(p, _pre(B))
    finally:
        failpoints.disarm_all()
    assert out and reply["delivery"]["state"] == "emitted" and "receipt_not_captured" in reply["delivery"]["degraded"]
    (entry,) = ds.scratch(p, sid)["entries"]
    assert entry["state"] == "emitted" and not entry["receipt_spooled"] and entry["emitted_at"]
    _pre_rec, post = ds.call_records(ds.MID, "r1", session=B)
    nxt, _ = ds.hook(p, _pre(B, "r2"))  # the next delivery attempt re-spools the owed receipt
    assert ds.scratch(p, sid)["entries"][0]["receipt_spooled"]
    ds.ingest(p)
    assert [(r["attempt_id"], r["state"]) for r in ds.deliveries(p, sid)][:1] == [(entry["attempt_id"], "emitted")]
    # A hook killed after its reservation, then the session ends: the uncertain receipt is spooled before the scratch goes.
    host = ds.fresh_session(9)
    killed = ds.killed_process(p, _pre(host, "k"), tmp_path, failpoints.DELIVERY_AFTER_FENCE)
    assert killed.returncode == failpoints.KILL_STATUS and killed.stdout == b""
    end, _ = ds.hook(p, ds.in_session(ds.record("SessionEnd"), host))
    assert end["receipt"]["status"] == "accepted" and ds.scratch(p, p.sid(host)) is None
    ds.ingest(p)
    assert [r["state"] for r in ds.deliveries(p, p.sid(host))] == ["uncertain"]
    assert ds.accounting(p, p.sid(host))["charged"] > 0 and ds.accounting(p, p.sid(host))["emitted"] == 0
