"""Task 5 full slice: the revision hash chain and the integrity scanner (A65; decision 0024).

Preview reserves the ``revision_chain`` table and never writes it: no chain
entry, no verification, every integrity form reports
``unavailable_in_preview``. The full profile (``release_profile: full``)
appends one content-digest entry per write transaction in that transaction and
verifies it incrementally (``doctor``) or over every current row
(``doctor --full-integrity``).

Real inputs: the stores hold real captured Claude 2.1.301 events, real
applications through ``apply_operations``/undo, the real forget/backup/restore
paths and the real worker. ``init --release-profile full`` stays refused until
the full release, so full-profile fixtures are created through the same
provisioning function with a full ``ProjectConfig`` (``claude_fixtures``'
test-only ``RELEASE_PROFILE``). Out-of-band mutations are made by a separate
plain SQLite connection, i.e. a same-user process outside the engine. The
entry, row and key digests are recomputed here from the documented
canonicalization, independently of ``storage/integrity.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

import operation_scenarios as osc
import worker_scenarios as ws
import claude_fixtures as cf
from recalith import service
from recalith.contracts.common import new_id
from recalith.contracts.config import ProjectConfig
from recalith.contracts.operations import ProposedOperation
from recalith.controller import apply
from recalith.core import identity
from recalith.errors import RecalithError
from recalith.storage import backup, db, integrity

GENESIS = "0" * 64


@pytest.fixture
def full(monkeypatch):
    """New fixture installations get ``release_profile: full`` for this test."""
    monkeypatch.setattr(cf, "RELEASE_PROFILE", "full")


# ---------------------------------------------------------------------------
# Independent canonicalization (DATA_CONTRACTS §11, decision 0024)


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(value: Any) -> str:
    return hashlib.sha256(canon(value)).hexdigest()


def typed(value: Any) -> list[Any]:
    if value is None:
        return ["n"]
    if isinstance(value, int):
        return ["i", value]
    if isinstance(value, float):
        return ["r", value.hex()]
    if isinstance(value, str):
        return ["t", value]
    return ["b", bytes(value).hex()]


def entry_hash(row: tuple) -> str:
    sequence, previous, operation_id, row_digests, purge, epoch = row[:6]
    return sha([sequence, previous, operation_id, row_digests, purge, epoch])


def raw(root: Path) -> sqlite3.Connection:
    """A same-user process outside the engine: a plain connection with no chain triggers."""
    return sqlite3.connect(root / ".recalith" / db.STATE_DB, isolation_level=None)


def chain(root: Path) -> list[tuple]:
    conn = raw(root)
    try:
        return conn.execute("SELECT sequence, previous_hash, operation_id, row_digests, purge_marker, tombstone_epoch, entry_hash FROM revision_chain ORDER BY sequence").fetchall()
    finally:
        conn.close()


def body(row: tuple) -> dict[str, Any]:
    return json.loads(row[3])


def chained_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("PRAGMA main.table_list").fetchall()
    return sorted(name for _schema, name, kind, *_ in rows if kind == "table" and not name.startswith("sqlite_") and name != "revision_chain")


def primary_key(conn: sqlite3.Connection, table: str) -> list[str]:
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [c[1] for c in sorted(cols, key=lambda c: c[5]) if c[5]]


def current_digests(root: Path) -> dict[str, tuple[str, str]]:
    """key digest -> (table, row digest) for every current row of every chained table."""
    conn = raw(root)
    out: dict[str, tuple[str, str]] = {}
    try:
        for table in chained_tables(conn):
            pk = primary_key(conn, table)
            key_sql = "json_array(" + (", ".join(f'"{c}"' for c in pk) if pk else "rowid") + ")"
            cur = conn.execute(f"SELECT {key_sql}, * FROM {table}")  # noqa: S608 - names from the schema
            names = [d[0] for d in cur.description][1:]
            for key, *values in cur.fetchall():
                out[sha(["key", table, json.loads(key)])] = (table, sha([table, [[n, typed(v)] for n, v in zip(names, values, strict=True)]]))
    finally:
        conn.close()
    return out


def replayed(root: Path) -> dict[str, tuple[str, str | None]]:
    """key digest -> (table, latest recorded row digest or None) from the whole chain."""
    latest: dict[str, tuple[str, str | None]] = {}
    for row in chain(root):
        for table, key, _rowid, digest in body(row)["rows"]:
            latest[key] = (table, digest)
    return latest


def verify(root: Path, *, full: bool = False) -> dict[str, Any]:
    return integrity.verify(osc.context(root), full=full)


def codes(report: dict[str, Any]) -> set[str]:
    return {f["code"] for f in report["findings"]}


def full_init(tmp: Path, name: str = "fresh") -> Path:
    root = tmp / name
    root.mkdir()
    identity.initialize_installation(root, ProjectConfig.defaults_for(ws.PROJECT_ID, release_profile="full"))
    return root


def new_claim(root: Path, text: str):
    return apply.apply_operations(
        osc.operator(root), [ProposedOperation.model_validate(osc.op("c", "propose_claim", osc.claim(text), evidence=[osc.link(root, "fail")]))],
        read_set=osc.read_set(root), submission_id=new_id("op"), now=ws.START,
    )


def checkpoint_file(root: Path) -> Path:
    return root / ".recalith" / integrity.CHECKPOINT


# ---------------------------------------------------------------------------
# Preview: reserved, never written, explicitly unavailable


def test_preview_revision_chain_is_reserved_and_unpopulated(tmp_path):
    """Real applications, a service write and an undo commit with no chain entries; every integrity form is unavailable."""
    root = osc.project(tmp_path)
    created = apply.apply_operations(
        osc.operator(root), [ProposedOperation.model_validate(osc.op("c", "propose_claim", osc.claim(osc.ORIGINAL), evidence=[osc.link(root, "fail")]))],
        read_set=osc.read_set(root), submission_id=new_id("op"), now=ws.START,
    )
    preview = apply.preview_undo(osc.context(root), created.operation_ids[0])
    apply.apply_undo(osc.operator(root), created.operation_ids[0], preview_digest=preview.preview_digest, now=ws.START)
    with db.open_store(osc.context(root), readonly=True) as store, store.read() as view:
        columns = [r[1] for r in view.execute("PRAGMA table_info(revision_chain)").fetchall()]
        entries = view.execute("SELECT COUNT(*) FROM revision_chain").fetchone()[0]
    assert columns == ["sequence", "previous_hash", "operation_id", "row_digests", "purge_marker", "tombstone_epoch", "entry_hash"]
    assert entries == 0 and osc.meta(root).store_revision > 0
    for full_check in (False, True):
        with pytest.raises(RecalithError) as refused:
            verify(root, full=full_check)
        assert refused.value.code == "capability_unavailable" and "unavailable_in_preview" in refused.value.message
    assert integrity.chain_state(osc.context(root))["state"] == "unavailable_in_preview"
    with db.open_store(osc.context(root)) as store, store.transaction() as txn, pytest.raises(RecalithError) as baseline:
        integrity.establish_baseline(txn, reason="activation")
    assert baseline.value.code == "capability_unavailable"
    assert not checkpoint_file(root).exists() and chain(root) == []


# ---------------------------------------------------------------------------
# Full: one entry per write transaction, continuous and canonical


def test_full_store_starts_with_an_init_baseline(tmp_path):
    root = full_init(tmp_path)
    rows = chain(root)
    assert len(rows) == 1
    (first,) = rows
    entry = body(first)
    assert first[0] == 1 and first[1] == GENESIS and first[2] is None and first[4] == 0 and first[6] == entry_hash(first)
    assert entry["entry_schema"] == 1 and entry["kind"] == "baseline" and entry["reason"] == "init" and entry["store_revision"] == 0
    conn = raw(root)
    try:
        assert entry["tables"] == chained_tables(conn) and "revision_chain" not in entry["tables"]
    finally:
        conn.close()
    assert {"installation_meta", "workspaces"} <= {table for table, *_ in entry["rows"]} == {table for table, _d in current_digests(root).values()}
    assert {k: (t, d) for t, k, _r, d in entry["rows"]} == current_digests(root)
    assert entry["metadata_hash"] == current_digests(root)[sha(["key", "installation_meta", [1]])][1]
    report = verify(root, full=True)
    assert report["state"] == "verified" and report["findings"] == [] and report["complete_coverage"] is True
    assert report["baseline"] == {"sequence": 1, "store_revision": 0, "reason": "init"} and report["pre_baseline_history"] == "none"


def test_chain_records_every_committed_mutation(tmp_path, full):
    """Continuity across real captures, ingestion, applications, undo and the worker; each entry is canonical."""
    root = osc.project(tmp_path)
    created = new_claim(root, osc.ORIGINAL)
    preview = apply.preview_undo(osc.context(root), created.operation_ids[0])
    apply.apply_undo(osc.operator(root), created.operation_ids[0], preview_digest=preview.preview_digest, now=ws.START)
    osc._drain_ingest(root)
    rows = chain(root)
    assert [r[0] for r in rows] == list(range(1, len(rows) + 1)) and len(rows) > 5
    previous = GENESIS
    for row in rows:
        assert row[1] == previous and row[6] == entry_hash(row), row[0]
        previous = row[6]
        entry = body(row)
        assert entry["entry_schema"] == 1 and entry["kind"] in ("baseline", "mutation", "purge")
        assert entry["rows"] == sorted(entry["rows"], key=lambda item: (item[0], item[1]))
        assert row[2] == (entry["operation_ids"][0] if entry["operation_ids"] else None)
        assert row[4] == (1 if entry["kind"] == "purge" else 0)
    revisions = [body(r)["store_revision"] for r in rows]
    meta = osc.meta(root)
    assert revisions == sorted(revisions) and revisions[-1] == meta.store_revision
    assert set(range(0, meta.store_revision + 1)) <= set(revisions)  # every store revision advance has its entry
    conn = raw(root)
    try:
        operation_ids = {r[0] for r in conn.execute("SELECT operation_id FROM operations").fetchall()}
    finally:
        conn.close()
    assert operation_ids <= {o for r in rows for o in body(r)["operation_ids"]}
    latest = replayed(root)
    assert {k: v for k, v in latest.items() if v[1] is not None} == current_digests(root)  # chain replay equals the store
    before = len(chain(root))
    service.search(osc.context(root), "pytest")
    service.health(osc.context(root), inherited={})
    assert len(chain(root)) == before  # reads append nothing
    assert verify(root)["state"] == "verified" and verify(root, full=True)["state"] == "verified"


def test_entry_content_is_digests_only(tmp_path, full):
    """No entry holds prose: only table names, digests, rowids, operation IDs and counters."""
    root = osc.project(tmp_path)
    new_claim(root, osc.ORIGINAL)
    text = json.dumps(chain(root))
    assert osc.ORIGINAL not in text and "pytest" not in text
    for row in chain(root):
        for table, key, rowid, digest in body(row)["rows"]:
            assert isinstance(table, str) and len(key) == 64 and isinstance(rowid, int) and (digest is None or len(digest) == 64)


# ---------------------------------------------------------------------------
# Detection


def test_unlogged_row_mutation_is_detected(tmp_path, full):
    """An out-of-band edit, insert or delete is reported, content-free; a check with findings never advances the checkpoint."""
    root = osc.project(tmp_path)
    assert verify(root, full=True)["state"] == "verified"
    saved = json.loads(checkpoint_file(root).read_text(encoding="utf-8"))
    created = new_claim(root, osc.ORIGINAL)
    claim_id = created.changed_refs[0].id
    conn = raw(root)
    try:
        original = conn.execute("SELECT body FROM claim_revisions WHERE claim_id = ?", (claim_id,)).fetchone()[0]
        conn.execute("UPDATE claim_revisions SET body = ? WHERE claim_id = ?", (original.replace("flaky", "stable"), claim_id))
    finally:
        conn.close()
    incremental = verify(root)
    assert incremental["state"] == "findings" and "row_digest_mismatch" in codes(incremental)
    hit = [f for f in incremental["findings"] if f["code"] == "row_digest_mismatch"]
    assert {f["table"] for f in hit} == {"claim_revisions"} and all(len(f["key_digest"]) == 64 for f in hit)
    assert "stable" not in json.dumps(incremental) and "flaky" not in json.dumps(incremental)
    assert json.loads(checkpoint_file(root).read_text(encoding="utf-8"))["sequence"] == saved["sequence"]
    assert "row_digest_mismatch" in codes(verify(root, full=True))
    conn = raw(root)
    try:
        conn.execute("UPDATE claim_revisions SET body = ? WHERE claim_id = ?", (original, claim_id))  # the same bytes again
    finally:
        conn.close()
    assert verify(root)["state"] == "verified"
    conn = raw(root)
    try:
        conn.execute("INSERT INTO relations (source_id, target_id, relation, created_revision) VALUES ('clm_x', 'clm_y', 'contradicts', 1)")
        link = conn.execute("SELECT link_id FROM evidence_links ORDER BY link_id LIMIT 1").fetchone()[0]
        conn.execute("DELETE FROM evidence_links WHERE link_id = ?", (link,))
    finally:
        conn.close()
    full_report = verify(root, full=True)
    assert {"unlogged_row", "unlogged_deletion"} <= codes(full_report)
    assert {f["table"] for f in full_report["findings"]} == {"relations", "evidence_links"}
    assert full_report["complete_coverage"] is False


@pytest.mark.parametrize("tamper", ["altered", "deleted", "reordered", "inserted", "forged_tail"])
def test_altered_deleted_reordered_or_inserted_entry_is_detected(tmp_path, full, tamper):
    root = osc.project(tmp_path)
    new_claim(root, osc.ORIGINAL)
    rows = chain(root)
    k = len(rows) // 2
    conn = raw(root)
    try:
        if tamper == "altered":
            conn.execute("UPDATE revision_chain SET row_digests = replace(row_digests, '\"store_revision\":', '\"store_revision\": ') WHERE sequence = ?", (k,))
        elif tamper == "deleted":
            conn.execute("DELETE FROM revision_chain WHERE sequence = ?", (k,))
        elif tamper == "reordered":
            a, b = rows[k - 1], rows[k]
            conn.execute("UPDATE revision_chain SET sequence = -1 WHERE sequence = ?", (a[0],))
            conn.execute("UPDATE revision_chain SET sequence = ? WHERE sequence = ?", (a[0], b[0]))
            conn.execute("UPDATE revision_chain SET sequence = ? WHERE sequence = -1", (b[0],))
        elif tamper == "inserted":
            for seq in range(len(rows), k - 1, -1):
                conn.execute("UPDATE revision_chain SET sequence = sequence + 1 WHERE sequence = ?", (seq,))
            forged = (k, rows[k - 2][6], None, json.dumps({"entry_schema": 1, "kind": "mutation", "rows": []}), 0, 0)
            conn.execute("INSERT INTO revision_chain VALUES (?, ?, ?, ?, ?, ?, ?)", (*forged, entry_hash(forged)))
        else:  # a well-formed entry appended after the head that claims a row state the store does not have
            last = rows[-1]
            claimed = body(last)
            claimed.update(kind="mutation", operation_ids=[], rows=[[t, key, r, "f" * 64] for t, key, r, _d in claimed["rows"]][:1])
            forged = (last[0] + 1, last[6], None, canon(claimed).decode("utf-8"), 0, last[5])
            conn.execute("INSERT INTO revision_chain VALUES (?, ?, ?, ?, ?, ?, ?)", (*forged, entry_hash(forged)))
    finally:
        conn.close()
    report = verify(root, full=True)
    assert report["state"] == "findings" and report["complete_coverage"] is False
    expected = {
        "altered": {"entry_hash_mismatch"}, "deleted": {"sequence_gap"}, "reordered": {"chain_link_broken"},
        "inserted": {"chain_link_broken"}, "forged_tail": {"row_digest_mismatch"},
    }[tamper]
    assert expected <= codes(report), report["findings"]


def test_checkpoint_that_no_longer_matches_the_chain_is_untrusted(tmp_path, full):
    root = osc.project(tmp_path)
    assert verify(root, full=True)["complete_coverage"] is True
    data = json.loads(checkpoint_file(root).read_text(encoding="utf-8"))
    data["entry_hash"] = "e" * 64
    checkpoint_file(root).write_text(json.dumps(data), encoding="utf-8")
    report = verify(root)
    assert report["checkpoint"]["state"] == "untrusted" and report["complete_coverage"] is False and report["full_integrity_required"] is True
    assert report["checked_range"]["from_sequence"] == 1  # the whole chain is re-linked; untouched rows are still not covered
    assert verify(root, full=True)["complete_coverage"] is True
    assert verify(root)["checkpoint"]["state"] == "trusted"


def test_incremental_verification_reports_range_and_coverage(tmp_path, full):
    """Default checks cover the entries since the persisted verified head and the rows they touched, nothing more."""
    root = osc.project(tmp_path)
    first = verify(root)
    assert first["mode"] == "incremental" and first["checkpoint"]["state"] == "missing"
    assert first["complete_coverage"] is False and first["full_integrity_required"] is True and first["state"] == "verified"
    full_report = verify(root, full=True)
    head = full_report["head"]["sequence"]
    assert full_report["complete_coverage"] is True and json.loads(checkpoint_file(root).read_text(encoding="utf-8"))["sequence"] == head
    if os.name != "nt":
        assert checkpoint_file(root).stat().st_mode & 0o777 == 0o600
    created = new_claim(root, osc.REPLACEMENT)
    rows = chain(root)
    touched = {key for row in rows if row[0] > head for _t, key, _r, _d in body(row)["rows"]}
    report = verify(root)
    assert report["checked_range"] == {"from_sequence": head + 1, "to_sequence": rows[-1][0]}
    assert report["entries_checked"] == rows[-1][0] - head and report["rows_checked"] == len(touched)
    assert report["coverage"] == "rows_touched_in_range" and report["complete_coverage"] is True and report["full_integrity_required"] is False
    assert report["checkpoint"] == {"state": "trusted", "sequence": head, "complete": True}
    again = verify(root)
    assert again["checked_range"] is None and again["entries_checked"] == 0 and again["complete_coverage"] is True
    # An edit to a row no entry since the checkpoint touched is outside incremental coverage (SYSTEM_SPEC §10) ...
    conn = raw(root)
    try:
        event = conn.execute("SELECT event_id FROM events ORDER BY commit_sequence LIMIT 1").fetchone()[0]
        conn.execute("UPDATE events SET kind = kind || '' , channel = channel WHERE event_id = ?", (event,))  # a no-op rewrite
        conn.execute("UPDATE events SET task_hint = 'tampered' WHERE event_id = ?", (event,))
    finally:
        conn.close()
    assert verify(root)["state"] == "verified"
    # ... and the full check finds it.
    assert "row_digest_mismatch" in codes(verify(root, full=True))
    assert created.changed_refs  # the new claim stayed covered throughout


def test_full_integrity_checks_every_current_row(tmp_path, full):
    root = osc.project(tmp_path)
    new_claim(root, osc.ORIGINAL)
    conn = raw(root)
    try:
        tables = chained_tables(conn)
        total = sum(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables)  # noqa: S608
    finally:
        conn.close()
    report = verify(root, full=True)
    assert report["mode"] == "full" and report["coverage"] == "every_current_row" and report["state"] == "verified"
    assert report["cost"]["rows_scanned"] == total and report["cost"]["tables"] == len(tables) and report["cost"]["entries"] == len(chain(root))
    assert report["cost"]["seconds"] >= 0 and report["checked_range"] == {"from_sequence": 1, "to_sequence": len(chain(root))}
    conn = raw(root)
    try:
        conn.execute("UPDATE workspaces SET registered_at = '2000-01-01T00:00:00.000000Z'")  # untouched since the baseline
    finally:
        conn.close()
    assert {"row_digest_mismatch"} == codes(verify(root, full=True))


# ---------------------------------------------------------------------------
# Forgetting, backup and restore


def test_authorized_purge_extends_chain(tmp_path, full):
    """Forgetting appends purge entries; earlier entries are untouched and no entry holds forgotten text."""
    import forget_scenarios as fsc

    b = fsc.build(tmp_path, deliver=False)
    root = b.p.root
    before = chain(root)
    assert fsc.MARK not in json.dumps(before)
    assert verify(root, full=True)["state"] == "verified"
    fsc.forget(b, fsc.task_selector(b))
    after = chain(root)
    assert after[: len(before)] == before  # history is appended to, never rewritten
    purges = [r for r in after[len(before):] if r[4] == 1]
    assert purges and all(body(r)["kind"] == "purge" for r in purges)
    assert any(d is None for r in purges for _t, _k, _r, d in body(r)["rows"])  # removed rows are recorded as removed
    assert fsc.marker_locations(root) == []  # every table, revision_chain included
    report = verify(root, full=True)
    assert report["state"] == "verified" and report["purge_entries"] >= 1


def test_restore_keeps_the_snapshot_chain_and_suppresses_without_resurrecting(tmp_path, full):
    """A backup preserves the head; restoring it after a forget appends one purge entry and verifies."""
    import forget_scenarios as fsc

    b = fsc.build(tmp_path, deliver=False)
    root = b.p.root
    old = backup.create(b.p.ctx, tmp_path / "before-forget")
    kept = fsc.copy_backup(old.location, tmp_path / "operator-kept-copy")
    snapshot = sqlite3.connect((kept / "memory.sqlite").as_uri() + "?mode=ro", uri=True)
    try:
        snapshot_chain = snapshot.execute("SELECT sequence, previous_hash, operation_id, row_digests, purge_marker, tombstone_epoch, entry_hash FROM revision_chain ORDER BY sequence").fetchall()
    finally:
        snapshot.close()
    assert snapshot_chain and snapshot_chain == chain(root)[: len(snapshot_chain)]
    fsc.forget(b, fsc.task_selector(b))
    assert verify(root, full=True)["state"] == "verified"
    head_before_restore = chain(root)[-1][0]
    assert head_before_restore > len(snapshot_chain)
    service.restore(fsc.operator(b), kept, expected_digest=old.manifest_digest)
    restored = chain(root)
    assert restored[: len(snapshot_chain)] == snapshot_chain
    tail = restored[len(snapshot_chain):]
    # The staged restore's suppression is one purge entry; the ledger and backup policy after the swap are ordinary entries.
    assert tail and tail[0][4] == 1 and body(tail[0])["kind"] == "purge" and all(r[4] == 0 for r in tail[1:])
    assert fsc.marker_locations(root) == []
    report = verify(root)
    assert report["checkpoint"]["state"] == "untrusted" and report["full_integrity_required"] is True  # the store was replaced
    assert report["state"] == "verified"
    assert verify(root, full=True)["complete_coverage"] is True
    b.p.drain()  # the worker continues the restored chain
    assert verify(root)["state"] == "verified" and verify(root, full=True)["state"] == "verified"
    assert fsc.marker_locations(root) == []


# ---------------------------------------------------------------------------
# Activation on a preview store, raw-connection writers


def test_preview_store_gets_an_honest_baseline_when_chain_activates(tmp_path):
    """The activation baseline covers current rows only; nothing claims the preview history was chained."""
    root = osc.project(tmp_path)
    new_claim(root, osc.ORIGINAL)
    revision = osc.meta(root).store_revision
    assert chain(root) == []
    # The full-release upgrade's activation step (SYSTEM_SPEC §10.1; not built here) flips the profile and baselines in one transaction.
    with db.open_store(osc.context(root)) as store, store.transaction() as txn:
        txn.execute("UPDATE installation_meta SET release_profile = 'full' WHERE singleton = 1")
        assert integrity.establish_baseline(txn, reason="activation") == 1
    (only,) = chain(root)
    entry = body(only)
    assert entry["kind"] == "baseline" and entry["reason"] == "activation" and entry["store_revision"] == revision and only[1] == GENESIS
    assert {k: (t, d) for t, k, _r, d in entry["rows"]} == current_digests(root)
    report = verify(root, full=True)
    assert report["state"] == "verified" and report["pre_baseline_history"] == "not_chained"
    assert report["baseline"] == {"sequence": 1, "store_revision": revision, "reason": "activation"}
    new_claim(root, osc.REPLACEMENT)  # later writes are chained
    assert len(chain(root)) > 1 and verify(root)["state"] == "verified" and verify(root, full=True)["state"] == "verified"
    with db.open_store(osc.context(root)) as store, store.transaction() as txn, pytest.raises(RecalithError) as again:
        integrity.establish_baseline(txn, reason="activation")
    assert again.value.code == "policy_refused"


def test_raw_connection_writers_are_chained(tmp_path, full):
    """Init's store creation and an operator rebind write outside ``Store.transaction`` and still append entries."""
    root = osc.project(tmp_path, "before-move")
    moved = tmp_path / "after-move"
    shutil.move(str(root), str(moved))
    identity.rebind_installation(moved, actor=osc.OPERATOR)
    last = chain(moved)[-1]
    conn = raw(moved)
    try:
        rebind = conn.execute("SELECT operation_id FROM operations WHERE kind = 'workspace_rebind'").fetchone()[0]
    finally:
        conn.close()
    assert body(last)["operation_ids"] == [rebind] and "workspaces" in {t for t, *_ in body(last)["rows"]}
    assert verify(moved, full=True)["state"] == "verified"


# ---------------------------------------------------------------------------
# doctor and health in the full profile


def test_doctor_and_health_report_the_chain(tmp_path, full):
    import cli_scenarios as cs
    import health_scenarios as hs

    p = hs.project(tmp_path)
    rep = hs.report(p)
    cap = rep.capabilities["revision_chain"]
    assert cap.state == "degraded" and not cap.required and "revision_chain_not_verified" in cap.reason_codes
    assert cap.coverage["head_sequence"] == len(chain(p.root)) and cap.coverage["baseline"]["reason"] == "init"
    assert "revision_chain_unavailable_in_preview" not in rep.coverage_gaps
    done = cs.cli(p.root, "--json", "doctor", "--full-integrity")
    checks = done.obj["result"]["checks"]["revision_chain"]
    assert checks["mode"] == "full" and checks["state"] == "verified" and checks["complete_coverage"] is True, done.stdout
    assert "revision_chain_findings" not in (done.obj.get("degraded") or [])
    assert hs.report(p).capabilities["revision_chain"].state == "healthy"
    new_claim(p.root, osc.ORIGINAL)
    conn = raw(p.root)
    try:
        conn.execute("UPDATE claim_heads SET review_due_at = '2099-01-01T00:00:00.000000Z'")
    finally:
        conn.close()
    doctor = cs.cli(p.root, "--json", "doctor")
    checks = doctor.obj["result"]["checks"]["revision_chain"]
    assert doctor.code == 8 and checks["mode"] == "incremental" and checks["state"] == "findings"
    assert "revision_chain_findings" in doctor.obj["degraded"]
    after = hs.report(p).capabilities["revision_chain"]
    assert after.state == "degraded" and "revision_chain_findings" in after.reason_codes
