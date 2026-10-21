"""Test-only builders for Task 15 core: evidence retention with live pins and verified backups over real payloads.

Real inputs: every Claude event enters through the real 2.1.301 adapter
mapping, normalization, capture, ingestion and typed reduction
(``working_scenarios.Project``): the lifecycle session (prompts, the failing
``pytest -q test_mid.py``, ``seq``, ``grep``, ``Read``, ``Write``, ``echo``,
``sleep``, ``printf | tr``) and the subagent session (the ``Agent`` forwarding
result and the subagent's own tool results). Claims are admitted through the
real extraction/review path with recorded proposals
(``consolidation_scenarios``); the typed declaration goes through the guarded
service as an operator (the CLI tests run the real ``recalith`` child process);
task completion is a recorded ``update_task`` proposal citing the user's own
completion statement, and a dispute a recorded revalidation decision citing
contradicting evidence.

**Controlled time.** Events keep their real capture time. Retention runs at an
explicit later moment: a sweep's ``now`` or a worker ``FakeClock`` set *ahead*
of every capture (newest capture + N days). Nothing waits for wall time to reach
day 181 and no clock runs behind capture.

**Synthetic variants** (named at each use; payload shape, mapping and
normalization stay real): a second host session with its own prompt and a rerun
of a real call, prompt texts (a declaration, completion statements), the
resume ``SessionStart`` placed into an ended session, and synthetic-adapter
experiment events whose shared tokens merge two root classes
(``lineage_scenarios``). **Synthetic store states**: an open episode (the
fixtures never reach a 64-step flush), tombstone rows with their epoch (Task 16
owns forgetting), and corrupted or schema-forged copies of real backups.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import consolidation_scenarios as cs  # first: puts tests/, tests/integration and tests/platform on sys.path
import admission_scenarios as adm  # noqa: E402
import lineage_scenarios as ls  # noqa: E402
import operation_scenarios as osc  # noqa: E402
import working_scenarios as wks  # noqa: E402
from recalith import service  # noqa: E402
from recalith.contracts.common import RecordRef, Scope, canonical_json, format_utc, new_id, parse_utc, utc_now  # noqa: E402
from recalith.contracts.memory import Episode  # noqa: E402
from recalith.storage import db, records  # noqa: E402

COMPLETE = "The fixture lifecycle task is complete."
SUBAGENT_DONE = "The subagent task is complete."
TYPED = "Keep the fixture notes in notes.txt."
SESSION_B = wks.session_id(7)
SUBAGENT = "bbbb0015"
PROPS = {
    "lesson": cs.LESSON,
    "fact": "seq prints twelve thousand lines.",
    "decision": "The fixture tests stay on pytest.",
    "typed": TYPED,
    "candidate": "grep finds no marker in notes.txt.",
    "disputed": "notes.txt holds the fixture steps.",
    "shared1": "The Write created new.txt.",
    "shared2": "new.txt exists after the Write.",
    "forwarded": "The subagent echoed its marker.",
    "intermediary": "test_pass passes with output capture off.",
    "transitive": "The passing fixture test prints its output.",
}


@dataclass
class Built:
    p: wks.Project
    claims: dict[str, str] = field(default_factory=dict)
    events: dict[str, str] = field(default_factory=dict)
    tasks: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Time


def newest(p: wks.Project) -> str:
    """The latest capture time in the store: retention times are counted from here."""
    with p.view() as v:
        return v.execute("SELECT MAX(recorded_at) FROM events").fetchone()[0]


def oldest(p: wks.Project) -> str:
    with p.view() as v:
        return v.execute("SELECT MIN(recorded_at) FROM events").fetchone()[0]


def plus(moment: str, *, days: float = 0, seconds: float = 0) -> str:
    return format_utc(parse_utc(moment) + _dt.timedelta(days=days, seconds=seconds))


def day(p: wks.Project, n: float, *, seconds: float = 0) -> str:
    """``n`` days after the newest capture (``day(p, 181)`` is day 181 for every event)."""
    return plus(newest(p), days=n, seconds=seconds)


# --------------------------------------------------------------------------
# Building the owners


def operator(p: wks.Project):
    return osc.operator(p.root)


def typed_declaration(p: wks.Project, statement: str = TYPED, *, admit: bool = True) -> tuple[str, str]:
    """An operator's typed decision through the guarded service; admitted by its own recorded review."""
    submission = service.submit_declaration(operator(p), "decision", statement, Scope())
    claim_id = adm.created_claim(submission.result)
    if admit:
        adm.admit(p, claim_id)
    return claim_id, submission.event_id


def complete(p: wks.Project, host_session: str, statement: str) -> str:
    """The user states completion in ``host_session`` (resumed), and a recorded proposal completes its task.

    Synthetic variants: the resume ``SessionStart`` and the statement are
    placed into the (ended) host session; the completion basis cites the
    user's own statement. Returns the completed task's ID.
    """
    p.send(wks.variant(wks.record("secret_and_resume", "SessionStart"), session=host_session))
    p.send(wks.variant(wks.record("lifecycle", "UserPromptSubmit"), prompt=statement, session=host_session))
    p.drain()
    said = p.event("user_message", text=statement)
    task_id = p.task_of(said["id"])
    task = p.task(task_id)
    done = osc.op("done", "update_task", {"task_id": task_id, "expected_revision": task["revision"], "patches": [
        {"op": "set", "field": "completion_basis", "value": wks.supported(said, "The user stated the task is complete.", basis="user_declared")},
        {"op": "status", "status": "completed"},
    ]})
    result = p.propose("update_task", [done], input_refs=[RecordRef(kind="task", id=task_id, revision=task["revision"])])
    assert result.decisions[0].outcome == "apply", result.decisions
    assert p.task(task_id)["head_status"] == "completed"
    return task_id


def status_change(p: wks.Project, claim_id: str, status: str, *, evidence=()) -> None:
    """A recorded revalidation decision changing a claim's status (the real application path)."""
    ref = osc.head_ref(p.root, "claim", claim_id)
    result = p.propose("revalidate", [cs.status_op(p, "s", claim_id, status, evidence=list(evidence))], input_refs=[ref])
    assert result.decisions[0].outcome == "apply", result.decisions
    assert cs.head(p, claim_id)["head_status"] == status


def record_claim(p: wks.Project, proposition: str, target_kind: str, target_id: str, roots: list[str], *, subject: str) -> str:
    """A claim whose support is a record link to another record's revision (transitive evidence), admitted by review."""
    revision = osc.head_ref(p.root, target_kind, target_id).revision
    link = ls.record_link(target_kind, target_id, revision, roots=roots)
    claim_id = adm.created_claim(adm.extract(p, [osc.op("t", "propose_claim", adm.claim(proposition, subject=subject), evidence=[link])]))
    adm.admit(p, claim_id)
    return claim_id


def subagent_results(p: wks.Project) -> list[str]:
    """The subagent's own tool results (what the forwarding result relays)."""
    with p.view() as v:
        rows = v.execute("SELECT event_id, envelope FROM events WHERE kind = 'tool_finished' ORDER BY commit_sequence").fetchall()
    out = []
    for event_id, envelope in rows:
        ext = json.loads(envelope).get("extensions", {}).get("claude_code", {})
        if isinstance(ext, dict) and ext.get("agent_id") == ls.REAL_AGENT:
            out.append(event_id)
    return out


def build(tmp: Path, name: str = "retention", *, open_work: bool = True) -> Built:
    """Every kind of live owner A35 names, over real payloads; both host sessions' tasks completed (no task pins).

    Owners: an active failure lesson, fact, declaration and operator typed
    declaration; a candidate; a disputed claim (supports and contradicts); two
    claims sharing one root; a claim citing the subagent's forwarding result;
    a claim citing an archived intermediary claim (transitive). With
    ``open_work`` a second host session stays open (an active task's range).
    """
    p = cs.project(tmp, name)
    p.scenario("subagent")
    p.drain()
    osc.cancel_trigger_extractions(p.root)
    b = Built(p)
    ev = b.events
    for role, call in (("fail", cs.MID), ("long", "toolu_probe_0002"), ("echo", "toolu_probe_0001"), ("seq", "toolu_probe_0005"), ("grep", "toolu_probe_0006"),
                       ("read", "toolu_probe_0007"), ("missing", "toolu_probe_0008"), ("write", "toolu_probe_0009"), ("edit", "toolu_probe_0010"),
                       ("ls", "toolu_probe_0011"), ("sleep", "toolu_probe_0012"), ("printf", "toolu_probe_0013"), ("pass", cs.PASS)):
        ev[role] = p.event("tool_finished", call=call)["id"]
    ev["fail_start"] = p.event("tool_started", call=cs.MID)["id"]
    ev["reply_ok"] = p.event("user_message", text="Reply OK.")["id"]
    ev["session_start"] = p.events("session_started")[0]["id"]
    c = b.claims
    c["lesson"] = cs.lesson(p)
    c["fact"] = cs.fact(p, PROPS["fact"], subject="seq", evidence=p.event("tool_finished", call="toolu_probe_0005"))
    c["decision"] = cs.declaration(p, "We decided: keep the fixture tests on pytest.", PROPS["decision"], subject="runner")
    ev["decision"] = p.event("user_message", text="We decided: keep")["id"]
    c["typed"], ev["typed"] = typed_declaration(p)
    c["candidate"] = cs.fact(p, PROPS["candidate"], subject="grep", evidence=p.event("tool_finished", call="toolu_probe_0006"), admit=False)
    c["disputed"] = cs.fact(p, PROPS["disputed"], subject="notes", evidence=p.event("tool_finished", call="toolu_probe_0007"))
    status_change(p, c["disputed"], "disputed", evidence=[cs.link(p.event("tool_finished", call="toolu_probe_0001"), relation="contradicts")])
    write = p.event("tool_finished", call="toolu_probe_0009")
    c["shared1"] = cs.fact(p, PROPS["shared1"], subject="new", evidence=write)
    c["shared2"] = cs.fact(p, PROPS["shared2"], subject="new2", evidence=write)
    # Synthetic variants (as in the lineage tests): another subagent runs the real passing pytest call, and the real
    # Agent call forwards its output. The claim cites only the forwarding result; its root is the subagent's result.
    p.send_all(ls.forwarding(SUBAGENT, "f"))
    p.send_all(ls.in_subagent(ls.rerun("toolu_probe_0004", "sub"), SUBAGENT))
    p.drain()
    ev["forward"] = ls.finished(p, "toolu_probe_0014_f")
    ev["sub_result"] = ls.finished(p, "toolu_probe_0004_sub")
    c["forwarded"] = cs.fact(p, PROPS["forwarded"], subject="subagent", evidence=p.event("tool_finished", call="toolu_probe_0014_f"))
    c["intermediary"] = cs.fact(p, PROPS["intermediary"], subject="pass", evidence=p.event("tool_finished", call=cs.PASS))
    c["transitive"] = record_claim(p, PROPS["transitive"], "claim", c["intermediary"], [], subject="output")  # no named roots: only the record chain pins
    status_change(p, c["intermediary"], "archived")
    osc.cancel_trigger_extractions(p.root)
    b.tasks["lifecycle"] = complete(p, wks.LIFECYCLE_SESSION, COMPLETE)
    b.tasks["subagent"] = complete(p, ls.SUBAGENT_SESSION, SUBAGENT_DONE)
    ev["complete"] = p.event("user_message", text=COMPLETE)["id"]
    if open_work:
        p.send(wks.variant(wks.record("lifecycle", "SessionStart"), session=SESSION_B))
        p.send(wks.variant(wks.record("lifecycle", "UserPromptSubmit"), prompt="Session B: tidy the fixture notes.", session=SESSION_B))
        for rec in ls.rerun("toolu_probe_0013", "b", session=SESSION_B):
            p.send(rec)
        p.drain()
        ev["b_prompt"] = p.event("user_message", text="Session B: tidy")["id"]
        ev["b_result"] = p.event("tool_finished", call="toolu_probe_0013_b")["id"]
        ev["b_call"] = p.event("tool_started", call="toolu_probe_0013_b")["id"]  # cited by no revision: only the open range pins it
        ev["b_start"] = [e for e in p.events("session_started") if e["session_id"] == p.sid(SESSION_B)][0]["id"]
        b.tasks["open"] = p.task_of(ev["b_prompt"])
    osc.cancel_trigger_extractions(p.root)
    p.drain()
    return b


# --------------------------------------------------------------------------
# Observations


def payload_state(p: wks.Project, event_id: str) -> tuple[str, bool]:
    """(payload_state, payload present)."""
    with p.view() as v:
        row = v.execute("SELECT payload_state, payload IS NOT NULL FROM events WHERE event_id = ?", (event_id,)).fetchone()
    return row[0], bool(row[1])


def states(p: wks.Project) -> dict[str, str]:
    with p.view() as v:
        return dict(v.execute("SELECT event_id, payload_state FROM events").fetchall())


def claim_state(p: wks.Project, claim_id: str) -> tuple[str, str, str, str]:
    """(status, strength, freshness, evidence_availability) of the current head."""
    body = cs.head(p, claim_id)
    return body["head_status"], body["strength"], body["freshness"], body["evidence_availability"]


def guidance(p: wks.Project) -> dict[str, tuple]:
    return {cid: claim_state(p, cid) for cid in claim_ids(p)}


def claim_ids(p: wks.Project) -> list[str]:
    with p.view() as v:
        return [r[0] for r in v.execute("SELECT claim_id FROM claim_heads ORDER BY claim_id").fetchall()]


def meta(p: wks.Project) -> db.Meta:
    return osc.meta(p.root)


def open_episode(p: wks.Project, task_id: str, event_ids: list[str]) -> str:
    """An open episode citing ``event_ids`` (synthetic store state: the fixtures never reach a 64-step flush)."""
    ctx = osc.context(p.root)
    first = event_ids[0]
    support = [{"ref": {"kind": "event", "id": e, "revision": 1}, "relation": "supports", "root_event_ids": [e], "locator": None, "mapping": None} for e in event_ids]
    text = {"text": "Session B is tidying the fixture notes.", "evidence": support, "basis": "inferred"}
    episode = Episode.model_validate({
        "episode_id": new_id("ep"), "project_id": ctx.project_id, "installation_id": ctx.installation_id, "revision": 1, "task_id": task_id,
        "title": "Tidy the fixture notes", "started_at": utc_now(), "ended_at": None, "state": "open", "objective": text,
        "steps": [], "outcome": text, "source_event_ids": [first],
    })
    with db.open_store(ctx) as store, store.transaction() as txn:
        records.write_episode(txn, episode)
        txn.mutated(serving_relevant=True)
    return episode.episode_id


def settle_episode(p: wks.Project, episode_id: str) -> None:
    """The open episode settles (synthetic store state, as :func:`open_episode`)."""
    ctx = osc.context(p.root)
    with db.open_store(ctx) as store, store.transaction() as txn:
        revision, _state = records.head(txn, "episode", episode_id)
        data = records.body(txn, "episode", episode_id, revision)
        data.update({"revision": revision + 1, "state": "settled", "ended_at": utc_now()})
        records.write_episode(txn, Episode.model_validate(data))
        txn.mutated(serving_relevant=True)


def tombstone(p: wks.Project, target_ids: list[str]) -> int:
    """A content-free tombstone and a new tombstone epoch (synthetic store state: Task 16 owns forgetting)."""
    ctx = osc.context(p.root)
    with db.open_store(ctx) as store, store.transaction() as txn:
        epoch = txn.meta.tombstone_epoch + 1
        txn.execute(
            "INSERT INTO tombstones (tombstone_id, epoch, target_ids, source_digests, deletion_scope, created_at) VALUES (?, ?, ?, ?, 'record', ?)",
            (new_id("frg"), epoch, canonical_json(sorted(target_ids)).decode(), canonical_json([hashlib.sha256(t.encode()).hexdigest() for t in sorted(target_ids)]).decode(), utc_now()),
        )
        txn.execute("UPDATE installation_meta SET tombstone_epoch = ? WHERE singleton = 1", (epoch,))
        txn.mutated(serving_relevant=True)
    return epoch


# --------------------------------------------------------------------------
# Backup artifacts


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_rows(path: Path, sql: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def corrupt_copy(source: Path, target: Path, *, member: str = "memory.sqlite", offset: int = 4096) -> Path:
    """A copy of a real backup with one byte of ``member`` flipped (synthetic corruption)."""
    shutil.copytree(source, target)
    path = target / member
    data = bytearray(path.read_bytes())
    data[min(offset, len(data) - 1)] ^= 0xFF
    path.write_bytes(bytes(data))
    return target


def reseal(directory: Path) -> str:
    """Recompute a (tampered) backup's file digests into its manifest; returns the new manifest digest."""
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["file_digests"] = {name: file_digest(directory / name) for name in manifest["file_digests"]}
    manifest_path.write_bytes(canonical_json(manifest))
    return file_digest(manifest_path)


def forge_schema(source: Path, target: Path, version: int) -> str:
    """A copy whose snapshot claims another schema version, resealed so its digests match (synthetic)."""
    shutil.copytree(source, target)
    conn = sqlite3.connect(target / "memory.sqlite")
    try:
        conn.execute(f"PRAGMA user_version = {int(version)}")
        conn.execute("UPDATE installation_meta SET schema_version = ?", (version,))
        conn.commit()
    finally:
        conn.close()
    return reseal(target)



# --------------------------------------------------------------------------
# The kill/restart scenario (driven by worker_scenarios.py)
#
# Real owners over real payloads (``build`` without the open session), one
# synthetic tombstone (the ledger has content), then an operator script: a
# backup taken 40 days before day 181 (``old``), the worker at day 181 (a clock
# ahead of every capture, no provider: B1) whose retention step expires the
# unpinned payloads, deletes the aged backup and refreshes the ledger copy, and
# a backup at day 181 (``new``). After a kill the operator re-runs the commands
# that did not complete (a backup is complete once a ``backups`` row names its
# output) and the worker drains again.

SCENARIO = "retention.json"


def crash_project(tmp: Path, name: str) -> Path:
    b = build(tmp, name, open_work=False)
    p = b.p
    tombstone(p, [b.claims["candidate"]])
    clock = day(p, 181)
    spec = {
        "clock": clock,
        "old": {"output": str((tmp / f"{name}-old").resolve()), "at": plus(clock, days=-40)},
        "new": {"output": str((tmp / f"{name}-new").resolve()), "at": clock},
        "expect_expired": None,  # written by the test from its reference run (the probe's effect oracle)
    }
    (p.root / SCENARIO).write_text(json.dumps(spec), encoding="utf-8")
    return p.root


def scenario(root: Path) -> dict[str, Any] | None:
    path = root / SCENARIO
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def expect(root: Path, expired_keys: list[str], derived: dict[str, int] | None = None) -> None:
    spec = scenario(root)
    assert spec is not None
    spec["expect_expired"] = sorted(expired_keys)
    spec["expect_derived"] = derived
    (root / SCENARIO).write_text(json.dumps(spec), encoding="utf-8")


def _rows(root: Path) -> dict[str, tuple]:
    conn = sqlite3.connect((root / ".recalith" / db.STATE_DB).as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        return {loc: (state, epoch) for loc, state, epoch in conn.execute("SELECT location, state, tombstone_epoch FROM backups").fetchall()}
    finally:
        conn.close()


def run_script(root: Path, spec: dict[str, Any]) -> None:
    """The operator's commands that did not complete yet, and a worker drain at day 181 between the backups."""
    from recalith.controller import worker
    from recalith.fast import process_env
    from recalith.storage import backup

    import worker_scenarios as ws

    ctx = osc.context(root)
    with db.open_store(ctx) as store:
        backup.recover(ctx, store)
    if spec["old"]["output"] not in _rows(root):
        backup.create(ctx, Path(spec["old"]["output"]), now=spec["old"]["at"])
    w = worker.Worker(ctx, clock=ws.FakeClock(spec["clock"]), owner=f"driver:{new_id('act')[4:12]}")
    lock = process_env.InstallationLock(root)
    assert lock.try_acquire(), "another worker holds the installation"
    try:
        w.startup()
        ws.drain(w)
    finally:
        w.close()
        lock.release()
    with db.open_store(ctx) as store:
        backup.recover(ctx, store)
    if spec["new"]["output"] not in _rows(root):
        backup.create(ctx, Path(spec["new"]["output"]), now=spec["new"]["at"])


def _partials(spec: dict[str, Any]) -> list[Path]:
    """Staging directories left beside this scenario's outputs."""
    out = []
    for key in ("old", "new"):
        target = Path(spec[key]["output"])
        out += [x for x in target.parent.iterdir() if x.name.startswith(f".{target.name}.") and x.name.endswith(".partial")]
    return out


def _independently_verified(directory: Path) -> bool:
    """Every file the manifest names hashes to its digest (the test's own check, not the code under test)."""
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        names = {p.name for p in directory.iterdir()}
        return names == {"manifest.json", *manifest["file_digests"]} and all(file_digest(directory / n) == d for n, d in manifest["file_digests"].items())
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def derived_state(conn: sqlite3.Connection) -> dict[str, int]:
    """Derived revision bodies left and projection rows of body-less heads (decision 0020), counted from the store itself."""
    task_bodies = conn.execute("SELECT COUNT(*) FROM task_revisions r JOIN task_heads h ON h.task_id = r.task_id WHERE h.status IN ('completed', 'abandoned') AND r.body IS NOT NULL").fetchone()[0]
    episode_bodies = conn.execute("SELECT COUNT(*) FROM episode_revisions WHERE body IS NOT NULL").fetchone()[0]
    stale = 0
    for kind, table, key, head_table in (("task", "task_revisions", "task_id", "task_heads"), ("episode", "episode_revisions", "episode_id", "episode_heads")):
        stale += conn.execute(
            f"SELECT COUNT(*) FROM retrieval_docs d JOIN {head_table} h ON h.{key} = d.record_id JOIN {table} r ON r.{key} = h.{key} AND r.revision = h.revision "  # noqa: S608 - fixed names
            "WHERE d.record_kind = ? AND r.body IS NULL", (kind,)).fetchone()[0]
        stale += conn.execute(
            f"SELECT COUNT(*) FROM lexical_index l JOIN {head_table} h ON h.{key} = l.record_id JOIN {table} r ON r.{key} = h.{key} AND r.revision = h.revision "  # noqa: S608
            "WHERE l.record_kind = ? AND r.body IS NULL", (kind,)).fetchone()[0]
    orphans = 0
    for kind, table, key in (("task", "task_revisions", "task_id"), ("episode", "episode_revisions", "episode_id")):
        orphans += conn.execute(
            f"SELECT COUNT(*) FROM evidence_links l JOIN {table} r ON r.{key} = l.owner_id AND r.revision = l.owner_revision WHERE l.owner_kind = ? AND r.body IS NULL",  # noqa: S608
            (kind,)).fetchone()[0]
    return {"task_bodies": task_bodies, "episode_bodies": episode_bodies, "stale_projection_rows": stale, "orphan_links": orphans}


def outstanding(root: Path) -> str:
    """``1`` while retention or backup work is owed, judged from the effects (read-only).

    Owed: a payload the reference run expired still available; the aged
    backup's output still on disk or its row not ``deleted``; the new backup's
    output missing, not verifying (checked here by hashing) or unrecorded; a
    staging directory left beside an output; the latest ledger copy missing or
    behind the store's tombstone epoch. A state row the code writes about its
    own progress (``retention_state``) is never trusted.
    """
    spec = scenario(root) or {}
    expected = set(spec.get("expect_expired") or [])
    try:
        conn = sqlite3.connect((root / ".recalith" / db.STATE_DB).as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            states = dict(conn.execute("SELECT source_event_key, payload_state FROM events").fetchall())
            epoch = conn.execute("SELECT tombstone_epoch FROM installation_meta").fetchone()[0]
            rows = {loc: state for loc, state in conn.execute("SELECT location, state FROM backups").fetchall()}
            derived = derived_state(conn)
        finally:
            conn.close()
    except sqlite3.Error:
        return "1"
    old, new = Path(spec["old"]["output"]), Path(spec["new"]["output"])
    owed = any(states.get(k) == "available" for k in expected)
    owed = owed or rows.get(str(old)) != "deleted" or old.exists()
    owed = owed or rows.get(str(new)) != "verified" or not _independently_verified(new)
    owed = owed or bool(_partials(spec))
    want = spec.get("expect_derived")
    if want is not None:  # derived bodies the reference aged still present, or projection rows left for an aged head
        owed = owed or derived["task_bodies"] > want["task_bodies"] or derived["episode_bodies"] > want["episode_bodies"] or derived["stale_projection_rows"] > 0 or derived["orphan_links"] > 0
    ledger = None
    try:
        ledger = json.loads((root / ".recalith" / "state" / "ledger.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    owed = owed or ledger is None or ledger.get("tombstone_epoch") != epoch
    return "1" if owed else "0"


def retention_state(root: Path) -> dict[str, Any]:
    """Payload states by source key, claims by proposition, backups by output name, files, the ledger copy, audits."""
    ctx = osc.context(root)
    spec = scenario(root) or {}
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        states = sorted(view.execute("SELECT source_event_key, payload_state, payload IS NULL FROM events").fetchall())
        claims = []
        for claim_id, revision, status in view.execute("SELECT claim_id, revision, status FROM claim_heads").fetchall():
            body = records.body(view, "claim", claim_id, revision)
            claims.append((body["proposition"], status, body["strength"], body["freshness"], body["evidence_availability"]))
        roles = {spec["old"]["output"]: "old", spec["new"]["output"]: "new"}
        rows = sorted((roles.get(loc, "other"), state, epoch) for loc, state, epoch in view.execute("SELECT location, state, tombstone_epoch FROM backups").fetchall())
        audits = view.execute("SELECT COUNT(*) FROM operations WHERE kind IN ('retention_expiry', 'retention_record_aging')").fetchone()[0]
        epochs = view.execute("SELECT tombstone_epoch FROM installation_meta").fetchone()
    old, new = Path(spec["old"]["output"]), Path(spec["new"]["output"])
    ledger = json.loads((root / ".recalith" / "state" / "ledger.json").read_text(encoding="utf-8")) if (root / ".recalith" / "state" / "ledger.json").exists() else None
    new_ledger = json.loads((new / "ledger.json").read_text(encoding="utf-8")) if (new / "ledger.json").exists() else None
    snapshot_states = sorted(snapshot_rows(new / "memory.sqlite", "SELECT source_event_key, payload_state FROM events")) if (new / "memory.sqlite").exists() else None
    conn = sqlite3.connect((root / ".recalith" / db.STATE_DB).as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        derived = derived_state(conn)
    finally:
        conn.close()
    return {
        "payloads": states, "claims": sorted(claims), "backups": rows, "audits": audits, "derived": derived,
        "files": {"old": old.exists(), "new": _independently_verified(new), "partials": len(_partials(spec))},
        "ledger": None if ledger is None else (ledger["tombstone_epoch"], len(ledger["tombstones"])), "tombstone_epoch": epochs[0],
        "new_backup": None if new_ledger is None else (new_ledger["tombstone_epoch"], len(new_ledger["tombstones"]), snapshot_states),
    }


def kill_invariants(root: Path, reference: dict[str, Any]) -> list[str]:
    """What a kill may never leave: an output that exists but does not verify, a pinned payload gone, a downgraded claim."""
    spec = scenario(root) or {}
    problems = []
    for key in ("old", "new"):
        out = Path(spec[key]["output"])
        if out.exists() and not _independently_verified(out):
            problems.append(f"{key}_output_does_not_verify")
    kept = {k for k, state, _null in reference["payloads"] if state == "available"}
    ctx = osc.context(root)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        now = dict(view.execute("SELECT source_event_key, payload_state FROM events").fetchall())
        claims = []
        for claim_id, revision, status in view.execute("SELECT claim_id, revision, status FROM claim_heads").fetchall():
            body = records.body(view, "claim", claim_id, revision)
            claims.append((body["proposition"], status, body["strength"], body["freshness"], body["evidence_availability"]))
    if any(now.get(k) != "available" for k in kept):
        problems.append("pinned_payload_expired")
    if sorted(claims) != reference["claims"]:
        problems.append("claims_changed")
    return problems

__all__ = ["Built", "build", "plus", "day", "newest"]
