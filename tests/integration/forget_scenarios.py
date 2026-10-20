"""Test-only builders for Task 16: intentional forgetting and suppression-aware restore over real payloads.

Real inputs: every Claude event enters through the real 2.1.301 adapter
mapping, normalization, capture, ingestion and typed reduction
(``working_scenarios.Project``); claims are admitted through the real
extraction/review path with recorded proposals (``admission_scenarios``); the
episode is a recorded ``create_episode`` proposal through the real application
path; delivery runs the real hook branch (``entry.handle_hook``) into a
controlled test manifest (``delivery_scenarios.enable``); backups are real
``storage.backup`` directories; forget and restore run through the service as
an operator and through the real guarded ``recalith`` child process with an
explicitly provisioned fixture token (``cli_scenarios``).

**The marker.** :data:`MARK` is one fixture-specific token (assembled here so
no file holds it whole) that appears only in the forgotten host session: a
user prompt declaring it, an ``echo`` of it (its command and output), the
claims, episode and task derived from them, the published views, the lexical
index (one token, so the FTS shadow tables hold it too), a delivery's scratch
and receipt, a pending spool segment, proposal and operation bodies and the
backups taken before the forget. :func:`marker_locations` searches every table
and column (FTS shadow tables included), every file under ``.recalith/`` and
any extra directories for it, case-insensitively.

**Synthetic variants** (named at each use; payload shape, mapping and
normalization stay real): the forgotten host session ``SESSION_F`` with its
prompt texts and an ``echo`` rerun of a real call carrying the marker in its
command; a later independent session ``SESSION_N`` restating the text.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import consolidation_scenarios as cs  # first: puts tests/, tests/integration and tests/platform on sys.path
import admission_scenarios as adm  # noqa: E402
import delivery_scenarios as ds  # noqa: E402
import lineage_scenarios as ls  # noqa: E402
import operation_scenarios as osc  # noqa: E402
import retrieval_scenarios as rs  # noqa: E402
import working_scenarios as wks  # noqa: E402
from recalith.contracts.common import RecordRef, utc_now  # noqa: E402
from recalith.contracts.privacy import ForgetRequest, ForgetSelector  # noqa: E402
from recalith.storage import db, records  # noqa: E402

MARK = "Qzvorbelt" + "Marker" + "4471"  # one lexical token; never written whole into a tracked file
SESSION_F = wks.session_id(41)
SESSION_N = wks.session_id(42)
SAID = f"Remember: the {MARK} fixture listens on port 8123."
DECL = f"The {MARK} fixture listens on port 8123."
MULTI = f"The {MARK} fixture and the seq run share the fixture tree."
DERIVED = f"Port 8123 belongs to the {MARK} fixture service."
EPISODE = f"Recorded the {MARK} fixture port."


@dataclass
class Built:
    p: wks.Project
    claims: dict[str, str] = field(default_factory=dict)
    events: dict[str, str] = field(default_factory=dict)
    tasks: dict[str, str] = field(default_factory=dict)
    episode: str | None = None
    session: str = ""
    early: Any = None  # a backup taken before the forgotten session existed (unaffected by the forget)


def _supported(event_id: str, text: str, basis: str = "inferred") -> dict[str, Any]:
    return {"text": text, "evidence": [{"ref": {"kind": "event", "id": event_id, "revision": 1}, "relation": "supports", "root_event_ids": [event_id], "locator": None, "mapping": None}], "basis": basis}


def build(tmp: Path, name: str = "forget", *, deliver: bool = True, publish: bool = True, early_backup: Path | None = None) -> Built:
    """The reduced lifecycle session plus the forgotten host session ``SESSION_F`` and everything derived from it.

    Claims: ``lesson`` (the real failure lesson, unrelated, must survive),
    ``decl`` (a user-declared decision from the marker prompt: one forgotten
    root), ``multi`` (a fact supported by the marker prompt *and* the real
    ``seq`` result: a surviving root, A63), ``derived`` (a fact citing
    ``decl``'s revision through a record link only: transitive). The
    episode is a recorded checkpoint of the marker task. With ``deliver`` a
    prompt hook in ``SESSION_F`` emits ``decl`` and its receipt is accounted.
    """
    p = cs.project(tmp, name)
    b = Built(p, session=p.sid(SESSION_F))
    c, ev = b.claims, b.events
    c["lesson"] = cs.lesson(p)
    if early_backup is not None:
        from recalith.storage import backup

        b.early = backup.create(p.ctx, early_backup)
    seq = p.event("tool_finished", call="toolu_probe_0005")
    ev["seq"] = seq["id"]
    said = adm.prompt(p, SAID, session=SESSION_F)
    ev["said"] = said["id"]
    cs.send(p, "toolu_probe_0001", "fm", command=f"echo {MARK}", session=SESSION_F)  # synthetic variant: an echo of the marker
    p.drain()
    ev["echo"] = p.event("tool_finished", call="toolu_probe_0001_fm")["id"]
    ev["echo_start"] = p.event("tool_started", call="toolu_probe_0001_fm")["id"]
    b.tasks["forgotten"] = p.task_of(ev["said"])
    b.tasks["lifecycle"] = p.task_of(seq["id"])
    body = adm.claim(DECL, kind="decision", basis="user_declared", subject="fixture port")
    body["proposition_key"]["predicate"] = "chosen"
    c["decl"] = adm.created_claim(adm.extract(p, [osc.op("d", "propose_claim", body, evidence=[adm.link(said, field="text")])], input_refs=[RecordRef(kind="event", id=ev["said"], revision=1)]))
    adm.admit(p, c["decl"])
    multi = adm.claim(MULTI, subject="fixture tree")
    c["multi"] = adm.created_claim(adm.extract(p, [osc.op("m", "propose_claim", multi, evidence=[adm.link(said), adm.link(seq)])], input_refs=[RecordRef(kind="event", id=ev["said"], revision=1)]))
    adm.admit(p, c["multi"])
    revision = osc.head_ref(p.root, "claim", c["decl"]).revision
    c["derived"] = adm.created_claim(adm.extract(p, [osc.op("t", "propose_claim", adm.claim(DERIVED, subject="fixture service"), evidence=[ls.record_link("claim", c["decl"], revision, roots=[])])]))
    adm.admit(p, c["derived"])
    task = osc.head_ref(p.root, "task", b.tasks["forgotten"])
    episode = {
        "task_id": b.tasks["forgotten"], "title": "Fixture port", "state": "settled", "started_at": utc_now(), "ended_at": utc_now(),
        "objective": _supported(ev["said"], EPISODE), "steps": [{"ordinal": 0, "action": _supported(ev["echo"], f"echo {MARK}"), "outcome": "success"}],
        "outcome": _supported(ev["echo"], EPISODE), "source_event_ids": [ev["said"], ev["echo_start"], ev["echo"]],
    }
    result = p.propose("build_episode", [osc.op("e", "create_episode", episode)], input_refs=[task])
    assert result.decisions[0].outcome == "apply", result.decisions
    b.episode = [r.id for r in result.changed_refs if r.kind == "episode"][0]
    osc.cancel_trigger_extractions(p.root)
    if publish:
        rs.publish(p)
    if deliver:
        ds.enable(p)
        reply, out = ds.hook(p, ds.in_session(wks.record("lifecycle", "UserPromptSubmit"), SESSION_F, prompt="Which port does the fixture listen on? port 8123"))
        assert out and c["decl"] in ds.context_text(out[0]), reply
        ds.ingest(p)
        p.drain()
        rs.publish(p)
    return b


def task_selector(b: Built) -> ForgetSelector:
    return ForgetSelector(task_ids=[b.tasks["forgotten"]])


def range_selector(b: Built, first: int = 1, last: int = 10**6) -> ForgetSelector:
    return ForgetSelector.model_validate({"source_ranges": [{"adapter_id": "claude_code", "host_session_id": SESSION_F, "from_sequence": first, "to_sequence": last}]})


def operator(b: Built):
    return osc.operator(b.p.root)


def forget(b: Built, selector: ForgetSelector, *, ctx=None):
    """Preview then apply through the service as an operator; returns (preview, result)."""
    from recalith import service

    ctx = ctx or operator(b)
    preview = service.preview_forget(ctx, selector)
    return preview, service.apply_forget(ctx, ForgetRequest(selector=selector, preview_digest=preview.preview_digest))


def pending_marker_prompt(b: Built, text: str | None = None) -> dict[str, Any]:
    """A prompt in the forgotten session captured into the spool and not yet ingested (synthetic variant)."""
    rec = wks.variant(wks.record("lifecycle", "UserPromptSubmit"), prompt=text or f"Also note {MARK} uses TLS.", session=SESSION_F)
    b.p.send(rec)
    return rec


def head(p: wks.Project, kind: str, record_id: str) -> tuple[int, str, dict[str, Any] | None]:
    with p.view() as v:
        revision, status = records.head(v, kind, record_id)
        return revision, status, records.body(v, kind, record_id, revision)


# --------------------------------------------------------------------------
# Searching for the marker everywhere


def _db_hits(path: Path, needle: str) -> list[str]:
    """Every table.column of a database whose values hold the needle: text case-insensitively, blobs byte for byte.

    Blobs (the FTS segment b-trees in ``lexical_fts_data`` among them) are
    searched for the needle's tail too, because FTS5 stores a term after the
    prefix it shares with the previous term on the page.
    """
    hits: list[str] = []
    lowered = needle.lower()
    tail = lowered[4:].encode("utf-8")
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return [f"{path}:unreadable"]
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()]
        for table in tables:
            try:
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info('{table}')").fetchall()]
                rows = conn.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{table}"').fetchall() if cols else []  # noqa: S608
            except sqlite3.Error:
                continue
            for i, col in enumerate(cols):
                for row in rows:
                    value = row[i]
                    if (isinstance(value, str) and lowered in value.lower()) or (isinstance(value, bytes) and tail in value.lower()):
                        hits.append(f"{path.name}:{table}.{col}")
                        break
    finally:
        conn.close()
    return hits


def marker_locations(root: Path, *extra: Path, needle: str = MARK, raw_store: bool = False) -> list[str]:
    """Every logical place the marker survives: tables and columns (FTS shadow tables included), files, backups.

    Databases (the live store, backup snapshots) are searched logically, row
    by row; other files byte for byte (lowercased). ``raw_store`` also
    searches the live store's file bytes (free pages and the WAL; filesystem
    forensics are outside the logical guarantee, so only tests that control
    every connection ask for it).
    """
    out: list[str] = []
    lowered = needle.lower().encode("utf-8")
    for base in (root / ".recalith", *extra):
        if not base.exists():
            continue
        for path in sorted(x for x in base.rglob("*") if x.is_file()):
            if path.name.endswith((".sqlite", ".sqlite-wal", ".sqlite-shm", ".sqlite-journal")):
                if path.name.endswith(".sqlite"):
                    out += [f"{path.relative_to(base.parent)}::{h}" for h in _db_hits(path, needle)]
                if not raw_store or path.parent.name != "state":
                    continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if lowered in data.lower():
                out.append(str(path.relative_to(base.parent)))
    return out


def copy_backup(source: str | Path, target: Path) -> Path:
    """An operator's external copy of a backup directory (never recorded in the store: forgetting cannot see it)."""
    shutil.copytree(source, target)
    return target


def statuses(p: wks.Project, ids: Iterable[tuple[str, str]]) -> dict[str, str]:
    with p.view() as v:
        return {record_id: records.head(v, kind, record_id)[1] for kind, record_id in ids}


def maintenance_active(p: wks.Project) -> bool:
    from recalith.fast import session

    return os.path.exists(session.maintenance_path(p.root))


def cli_json(result) -> dict[str, Any]:
    return json.loads(result.stdout) if result.stdout else {}


def selector_file(tmp: Path, selector: ForgetSelector, name: str = "selector.json") -> Path:
    path = tmp / name
    path.write_text(selector.model_dump_json(), encoding="utf-8")
    return path


def db_path(p: wks.Project) -> Path:
    return p.root / ".recalith" / db.STATE_DB


# --------------------------------------------------------------------------
# The kill/restart scenario (driven by worker_scenarios.py)
#
# ``build`` over real payloads with delivery, a recorded backup taken before the
# forget (``old``) and an operator's external copy of it (``kept``), and a
# prompt of the forgotten session still in the spool. The operator script: the
# guarded forget of the task (preview digest computed at build), a worker
# drain, the restore of the external copy, a worker drain. After a kill the
# operator re-runs what did not complete (the forget is idempotent by its
# preview digest; a restore is complete once the store holds its audit) after
# finishing an interrupted restore the way the worker's start does.

SCENARIO = "forget.json"
CRASH_ROLES = ("decl", "multi", "derived", "lesson")


def crash_project(tmp: Path, name: str) -> Path:
    from recalith import service
    from recalith.storage import backup

    b = build(tmp, name)
    p = b.p
    old = backup.create(p.ctx, tmp / f"{name}-old")
    kept = copy_backup(old.location, tmp / f"{name}-kept")
    pending_marker_prompt(b)
    selector = task_selector(b)
    preview = service.preview_forget(operator(b), selector)
    roles = {**{k: ["claim", v] for k, v in b.claims.items()}, "task": ["task", b.tasks["forgotten"]], "lifecycle": ["task", b.tasks["lifecycle"]], "episode": ["episode", b.episode]}
    spec = {
        "selector": selector.model_dump(mode="json"), "digest": preview.preview_digest, "old": str(Path(old.location).resolve()), "kept": str(kept.resolve()),
        "kept_digest": old.manifest_digest, "roles": roles, "events": dict(b.events),
    }
    (p.root / SCENARIO).write_text(json.dumps(spec), encoding="utf-8")
    return p.root


def scenario(root: Path) -> dict[str, Any] | None:
    path = root / SCENARIO
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _drain_worker(root: Path) -> None:
    from recalith.controller import worker
    from recalith.contracts.common import new_id
    from recalith.fast import process_env

    import worker_scenarios as ws

    ctx = osc.context(root)
    w = worker.Worker(ctx, owner=f"driver:{new_id('act')[4:12]}")
    lock = process_env.InstallationLock(root)
    assert lock.try_acquire(), "another worker holds the installation"
    try:
        from recalith.privacy import forget as forget_module

        forget_module.recover_restore(ctx)  # as the worker's start does, before it opens the store
        w.startup()
        ws.drain(w)
    finally:
        w.close()
        lock.release()


def _restored(root: Path) -> bool:
    conn = sqlite3.connect((root / ".recalith" / db.STATE_DB).as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        return conn.execute("SELECT COUNT(*) FROM operations WHERE kind = 'restore'").fetchone()[0] > 0
    finally:
        conn.close()


def run_script(root: Path, spec: dict[str, Any]) -> None:
    """The operator's commands that did not complete, with worker drains between them."""
    from recalith import service
    from recalith.contracts.privacy import ForgetRequest

    from recalith.privacy import forget as forget_module

    forget_module.recover_restore(osc.context(root))  # as the worker's start would, before anything opens the store
    ctx = osc.operator(root)  # a re-run forget resumes its own persisted operation (idempotent by preview digest)
    service.apply_forget(ctx, ForgetRequest(selector=ForgetSelector.model_validate(spec["selector"]), preview_digest=spec["digest"]))
    _drain_worker(root)
    if not _restored(root):
        service.restore(osc.operator(root), Path(spec["kept"]), expected_digest=spec["kept_digest"])
    _drain_worker(root)


def _independently_verified(directory: Path) -> bool:
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        names = {x.name for x in directory.iterdir()}
        import hashlib

        return names == {"manifest.json", *manifest["file_digests"]} and all(hashlib.sha256((directory / n).read_bytes()).hexdigest() == d for n, d in manifest["file_digests"].items())
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def _live_hits(root: Path) -> list[str]:
    """The marker in the live store (logically), the spool, the scratch, views and ledger: never after the purge commit."""
    return [loc for loc in marker_locations(root) if "/backups/" not in loc.replace("\\", "/")]


def outstanding(root: Path) -> str:
    """``1`` while forget or restore work is owed, judged from the effects on disk and in the store (read-only).

    Owed: no tombstone yet; the marker anywhere in the store, spool, scratch or
    a backup under ``.recalith``; the recorded older backup still on disk or
    not marked deleted; no post-forget backup that verifies by the test's own
    hashing; the latest ledger copy missing or behind the store; the
    maintenance marker present (delivery paused); a restore journal or staged
    file left; the store holding no restore audit; no reconstruction job over
    the surviving root. ``privacy_operations`` (the code's own progress) is
    never trusted.
    """
    spec = scenario(root) or {}
    try:
        conn = sqlite3.connect((root / ".recalith" / db.STATE_DB).as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            tombstones = conn.execute("SELECT COUNT(*) FROM tombstones").fetchone()[0]
            epoch = conn.execute("SELECT tombstone_epoch FROM installation_meta").fetchone()[0]
            rows = {loc: state for loc, state in conn.execute("SELECT location, state FROM backups").fetchall()}
            restored = conn.execute("SELECT COUNT(*) FROM operations WHERE kind = 'restore'").fetchone()[0]
            jobs = [json.loads(b) for (b,) in conn.execute("SELECT body FROM jobs WHERE kind = 'extract_claims' AND state IN ('pending', 'waiting_budget')").fetchall()]
        finally:
            conn.close()
    except sqlite3.Error:
        return "1"
    seq = spec["events"]["seq"]
    owed = tombstones == 0 or bool(marker_locations(root))
    old = Path(spec["old"])
    owed = owed or old.exists() or rows.get(str(old)) != "deleted"
    forget_backups = [Path(loc) for loc, state in rows.items() if state == "verified" and "forget-" in Path(loc).name]
    owed = owed or len(forget_backups) != 1 or not _independently_verified(forget_backups[0])
    ledger = None
    try:
        ledger = json.loads((root / ".recalith" / "state" / "ledger.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    owed = owed or ledger is None or ledger.get("tombstone_epoch") != epoch
    owed = owed or maintenance_active_root(root) or (root / ".recalith" / "run" / "restore.json").exists() or bool(list((root / ".recalith" / "state").glob("restore-*")))
    owed = owed or restored == 0 or not any({r["id"] for r in j.get("input_refs") or []} == {seq} for j in jobs)
    return "1" if owed else "0"


def maintenance_active_root(root: Path) -> bool:
    from recalith.fast import session

    return os.path.exists(session.maintenance_path(root))


def forget_state(root: Path) -> dict[str, Any]:
    """Statuses and bodies by role, payload states by role, backups by role, tombstones, the ledger, files, audits."""
    spec = scenario(root) or {}
    ctx = osc.context(root)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        heads = {}
        for role, (kind, record_id) in sorted(spec["roles"].items()):
            revision, status = records.head(view, kind, record_id)
            table, key = records.REVISION_TABLES[kind]
            bodies = sorted({b is None for (b,) in view.execute(f"SELECT body FROM {table} WHERE {key} = ?", (record_id,)).fetchall()})  # noqa: S608
            heads[role] = (status, bodies)
        events = {role: view.execute("SELECT payload_state FROM events WHERE event_id = ?", (eid,)).fetchone() for role, eid in sorted(spec["events"].items())}
        roles = {spec["old"]: "old"}
        backups = sorted((roles.get(loc, "forget" if "forget-" in Path(loc).name else "other"), state) for loc, state in view.execute("SELECT location, state FROM backups").fetchall())
        tombstones = view.execute("SELECT COUNT(*), MAX(epoch) FROM tombstones").fetchone()
        meta = view.execute("SELECT tombstone_epoch FROM installation_meta").fetchone()[0]
        audits = dict(view.execute("SELECT kind, COUNT(*) FROM operations WHERE kind IN ('forget', 'restore') GROUP BY kind").fetchall())
        privacy = sorted(r[0] for r in view.execute("SELECT status FROM privacy_operations").fetchall())
        reconstruct = sum(1 for (b,) in view.execute("SELECT body FROM jobs WHERE kind = 'extract_claims' AND state IN ('pending', 'waiting_budget')").fetchall()
                          if {r["id"] for r in json.loads(b).get("input_refs") or []} == {spec["events"]["seq"]})
    ledger = json.loads((root / ".recalith" / "state" / "ledger.json").read_text(encoding="utf-8")) if (root / ".recalith" / "state" / "ledger.json").exists() else None
    forget_dirs = sorted((root / ".recalith" / "backups").glob("forget-*")) if (root / ".recalith" / "backups").exists() else []
    return {
        "heads": heads, "events": events, "backups": backups, "tombstones": tuple(tombstones), "tombstone_epoch": meta, "audits": audits, "privacy": privacy,
        "reconstruct": reconstruct, "ledger": None if ledger is None else (ledger["tombstone_epoch"], len(ledger["tombstones"])),
        "files": {"old": Path(spec["old"]).exists(), "forget_backups": [_independently_verified(d) for d in forget_dirs], "marker": marker_locations(root),
                  "maintenance": maintenance_active_root(root), "journal": (root / ".recalith" / "run" / "restore.json").exists(),
                  "staged": len(list((root / ".recalith" / "state").glob("restore-*")))},
    }


def kill_invariants(root: Path) -> list[str]:
    """What a kill may never leave: forgotten text in the live store, spool or scratch after the purge commit; an output that does not verify; served text."""
    problems = []
    try:
        conn = sqlite3.connect((root / ".recalith" / db.STATE_DB).as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            committed = conn.execute("SELECT COUNT(*) FROM tombstones").fetchone()[0] > 0
        finally:
            conn.close()
    except sqlite3.Error:
        return ["store_unreadable"]
    if committed and _live_hits(root):
        problems.append("forgotten_text_after_purge:" + ",".join(_live_hits(root)))
    if committed and not maintenance_active_root(root) and (outstanding(root) == "1"):
        # Delivery may resume only once the required logical cleanup finished: then nothing but the restore may be owed.
        spec = scenario(root) or {}
        if Path(spec.get("old", "")).exists():
            problems.append("delivery_resumed_before_cleanup")
    backups = root / ".recalith" / "backups"
    for directory in sorted(backups.glob("forget-*")) if backups.exists() else []:
        if not _independently_verified(directory):
            problems.append(f"backup_does_not_verify:{directory.name}")
    return problems
