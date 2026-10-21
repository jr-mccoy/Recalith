"""The §6.1 preview demonstrations, scripted and recorded (ACCEPTANCE_TESTS §6.1; decision 0020).

1. **Fresh-session reuse** — the L1 candidate learns the working test command
   in session A; fresh session B receives it without any remember
   instruction and does not repeat the failure, while the clean baseline does.
2. **Changed-condition revision with a legitimate retry** — R1/R2: the
   dependency changes before session C; no caution blocks the plain retry,
   the retry succeeds, and revalidation revises the lesson.
3. **Forgetting plus suppression-aware restore** — L3: a backup is taken, the
   preference is forgotten, the next prompt no longer delivers it, the old
   backup is restored, and the forgotten text is still absent from the store
   and from delivery.
4. **Isolation from a conflicting second project** — C4: two independent
   installations hold opposite test commands; neither installation's store,
   search or delivery returns the other's record, in either direction.
5. **Zero routine human memory-maintenance interventions** — across every
   smoke trial and workload day, no operator action was needed for memory to
   be formed, reviewed, revised or served.

Scripted mode uses the scripted agent and the recorded curator (labeled).
The forgetting demonstration's operator actions (backup, forget, restore) run
through the service with an operator actor, exactly as the Task 16 suites do
(a test-fixture route); the guarded CLI is also invoked from this process to
record that it refuses a host-marked caller. The live route is the operator's
terminal (B1).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _load(trials_dir: Path, sid: str, arm: str) -> dict[str, Any] | None:
    path = trials_dir / f"{sid}.{arm}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _trial(trials_dir: Path, work: Path, sid: str, arm: str) -> dict[str, Any]:
    from evals import trial

    return _load(trials_dir, sid, arm) or trial.run_trial(sid, arm, work)


def _delivered(record: dict[str, Any], session: str) -> list[dict[str, Any]]:
    for s in record.get("sessions", []):
        if s["name"] == session:
            return s.get("deliveries", [])
    return []


def fresh_session_reuse(trials_dir: Path, work: Path) -> dict[str, Any]:
    sid = "smoke-L1-ledgerlite-test-command"
    cand, base = _trial(trials_dir, work, sid, "candidate"), _trial(trials_dir, work, sid, "no_memory")
    points = cand.get("retrieval_points", [])
    b_actions = next((s["actions"] for s in cand["sessions"] if s["name"] == "B"), [])
    first_test = next((a["command"] for a in b_actions if a["command"] and "unittest" in a["command"]), None)
    return {
        "scenario": sid, "demonstrated": bool(cand["outcomes"]["task_success"]) and cand["outcomes"]["repeated_mistakes"] == 0 and (base["outcomes"]["repeated_mistakes"] or 0) > 0,
        "candidate_first_test_command_in_B": first_test, "candidate_repeated_mistakes": cand["outcomes"]["repeated_mistakes"], "baseline_repeated_mistakes": base["outcomes"]["repeated_mistakes"],
        "admitted": [c["proposition"] for c in cand.get("claims", []) if c["status"] == "active"], "remember_instruction": False,
        "retrieval_points": points, "note": "session B's knowledge came through delivered context (the scripted agent consults nothing else); the session-start point is unmet by design (decision 0013: a fresh start with no task binding carries only open intent questions) and the prompt packet carried it",
    }


def changed_condition_revision(trials_dir: Path, work: Path) -> dict[str, Any]:
    out = {}
    for sid in ("smoke-R1-fieldnotes-check-env-fixed", "smoke-R2-ledgerlite-import-fixed"):
        cand = _trial(trials_dir, work, sid, "candidate")
        calls = [c["purpose"] + ":" + ",".join(c["operations"]) for c in cand.get("curator_calls", [])]
        out[sid] = {
            "legitimate_retry_success": cand["outcomes"]["legitimate_retry_success"], "task_success": cand["outcomes"]["task_success"],
            "retry_point": [p for p in cand.get("retrieval_points", []) if "must_not_include_caution" in p["spec"]], "revalidation": [c for c in calls if c.startswith("revalidate")],
            "lesson": [(c["proposition"], c["status"], c["freshness"], c["revision"]) for c in cand.get("claims", [])],
        }
    ok = any(v["legitimate_retry_success"] and v["revalidation"] for v in out.values())
    return {"demonstrated": ok, "scenarios": out}


def _operator(ws: Path):
    from recalith.contracts.common import Actor
    from recalith.core import identity

    return identity.resolve_installation(ws, actor=Actor(kind="operator", id="eval-demo-fixture", channel="cli"))


def _store_text(ws: Path, needle: str) -> int:
    """Rows anywhere in the live store whose text or blob holds ``needle`` (FTS shadow tables included)."""
    import sqlite3

    path = ws / ".recalith" / "state" / "memory.sqlite"
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    hits = 0
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        for table in tables:
            try:
                for row in conn.execute(f'SELECT * FROM "{table}"'):  # noqa: S608 - names from sqlite_master
                    for value in row:
                        data = value if isinstance(value, bytes) else str(value).encode("utf-8") if value is not None else b""
                        hits += needle.encode("utf-8") in data
            except sqlite3.DatabaseError:
                continue
    finally:
        conn.close()
    return hits


def forgetting_and_restore(work: Path) -> dict[str, Any]:
    from evals import agent, trial
    from recalith import service
    from recalith.contracts.common import RecordRef
    from recalith.contracts.privacy import ForgetRequest, ForgetSelector
    from recalith.storage import db

    sid = "smoke-L3-household-grocery-budget"
    base = work / "forget"
    rec = trial.run_trial(sid, "candidate", base, init_route="test_fixture")
    ws = base / sid / "candidate" / "ws"
    out: dict[str, Any] = {"scenario": sid, "route": "service operator actor (test-fixture route, as the Task 16 suites)"}
    claims = [c for c in trial.claim_heads(ws) if c["status"] == "active" and "$600" in (c["proposition"] or "")]
    if not claims:
        return {**out, "demonstrated": False, "reason": "the preference was not admitted", "trial_error": rec.get("error")}
    target = claims[0]
    needle = "under $600 per month"
    guarded = subprocess.run([sys.executable, "-m", "recalith", "backup", "--project", str(ws), "--output", str(ws / ".recalith" / "backups" / "cli-attempt"), "--json"],
                             capture_output=True, text=True, encoding="utf-8", timeout=120, check=False, env=dict(os.environ))
    out["guarded_cli_from_this_process"] = {"exit": guarded.returncode, "refusal": (json.loads(guarded.stdout or "{}").get("refusal") or {}).get("reason") if guarded.stdout.startswith("{") else None}
    op = _operator(ws)
    made = service.submit_backup(op, ws / ".recalith" / "backups" / "before-forget")
    digest = made.manifest_digest
    external = base / "operator-external-copy"
    shutil.copytree(made.location, external)  # an operator's copy outside the installation (forgetting cannot reach it)
    out["backup_before"] = {"manifest_digest": digest, "store_hits_before": _store_text(ws, needle), "external_copy": True}
    # Forget the whole learning session's task: its prompt, events, task state, episode and the derived preference (A36).
    with db.open_store(trial.context(ws), readonly=True) as store, store.read() as view:
        task_ids = sorted({r[0] for r in view.execute("SELECT DISTINCT h.task_id FROM task_binding_heads h JOIN events e ON e.event_id = h.event_id JOIN sessions s ON s.session_id = e.session_id WHERE s.host_session_id = ?", (rec["sessions"][0]["host_session_id"],)).fetchall()})
    selector = ForgetSelector(record_refs=[RecordRef(kind="claim", id=target["claim_id"], revision=target["revision"])], task_ids=task_ids, source_ranges=[])
    out["selector"] = {"claims": 1, "tasks": len(task_ids)}
    preview = service.preview_forget(op, selector)
    result = service.apply_forget(op, ForgetRequest(selector=selector, preview_digest=preview.preview_digest, reason="demonstration"))
    out["forget"] = {"purge_state": result.purge_state, "purged": result.purged_count, "quarantined": result.quarantined_count, "backup_state": result.backup_state,
                     "deleted_backups": len(result.deleted_backup_ids), "recorded_pre_forget_backup_deleted": not Path(made.location).exists(), "limits": list(getattr(preview, "limits", []) or [])}
    out["store_hits_after_forget"] = _store_text(ws, needle)
    # Delivery after the forget: a fresh session's prompt about groceries.
    clock = agent.Clock("2026-11-09T09:00:00.000000Z")
    (base / "home-after").mkdir(exist_ok=True)
    host = agent.HookBridge(ws, base / "home-after", clock)
    s = agent.Session("D", ws, host, seed="forget-demo")
    s.start()
    s.prompt("Plan next month's groceries within the grocery budget.")
    s.stop()
    out["delivered_after_forget"] = any("600" in (d.context or "") for d in s.delivered)
    restored = service.restore(op, external, expected_digest=digest)  # the pre-forget snapshot, restored suppression-aware
    out["restore"] = restored.model_dump(mode="json")
    out["store_hits_after_restore"] = _store_text(ws, needle)
    s2 = agent.Session("E", ws, host, seed="forget-demo-2")
    s2.start()
    s2.prompt("What is the grocery budget? Plan groceries.")
    s2.stop()
    out["delivered_after_restore"] = any("600" in (d.context or "") for d in s2.delivered)
    out["demonstrated"] = (out["backup_before"]["store_hits_before"] > 0 and out["store_hits_after_forget"] == 0 and not out["delivered_after_forget"]
                           and out["restore"].get("source_contains_suppressed") and out["store_hits_after_restore"] == 0 and not out["delivered_after_restore"])
    return out


def isolation(trials_dir: Path, work: Path) -> dict[str, Any]:
    """C4's two independent installations with opposite test commands, checked in both directions."""
    from evals import agent, curator, trial
    from recalith import service
    from recalith.contracts.common import Actor

    sid = "smoke-C4-cross-project-near-match"
    base = work / "isolation"
    rec = trial.run_trial(sid, "candidate", base, init_route="test_fixture")
    fieldnotes = base / sid / "candidate" / "ws"
    ledger = base / sid / "candidate" / "second-project" / "ws"
    # The reverse direction: fieldnotes learns its own command (R1's recorded proposals) in a later session.
    clock = agent.Clock("2026-11-03T09:00:00.000000Z")
    drainer = trial.Drainer(fieldnotes, clock, curator.RecordedCurator(curator.SmokePlan("smoke-R1-fieldnotes-check-env-fixed")))
    try:
        (base / "home-r").mkdir(exist_ok=True)
        agent.run_scripted("r1", "A", ["Run the project checks with `python tools/check.py` and get them passing."], fieldnotes, agent.HookBridge(fieldnotes, base / "home-r", clock), seed="isolation-reverse")
        drainer.drain()
    finally:
        drainer.close()
    actor = Actor(kind="controller", id="eval-harness", channel="worker")
    a, b = service.resolve(ledger, actor=actor), service.resolve(fieldnotes, actor=actor)
    ledger_claims = {c["claim_id"]: c for c in trial.claim_heads(ledger) if c["status"] == "active"}
    fieldnotes_claims = {c["claim_id"]: c for c in trial.claim_heads(fieldnotes) if c["status"] == "active"}
    in_fieldnotes = json.dumps(service.search(b, "PYTHONPATH=src unittest discover"))
    in_ledger = json.dumps(service.search(a, "NOTES_HOME tools/check.py KeyError"))
    leaked = sorted([i for i in ledger_claims if i in in_fieldnotes] + [i for i in fieldnotes_claims if i in in_ledger])
    text_leaks = sorted(x for x, hay in (("PYTHONPATH=src", in_fieldnotes), ("NOTES_HOME", in_ledger)) if x in hay)
    delivered_b = [i["text"] for p in rec.get("retrieval_points", []) for i in p.get("items", [])]
    return {
        "scenario": sid, "installations": {"ledgerlite": a.installation_id, "fieldnotes": b.installation_id, "distinct": a.installation_id != b.installation_id and a.project_id != b.project_id},
        "ledgerlite_active_claims": [c["proposition"] for c in ledger_claims.values()], "fieldnotes_active_claims": [c["proposition"] for c in fieldnotes_claims.values()],
        "cross_record_ids": leaked, "cross_text_in_search": text_leaks, "fieldnotes_session_b_delivered": delivered_b,
        "task_success": rec["outcomes"]["task_success"], "cross_project_leak_commands": (rec.get("oracle") or {}).get("metrics", {}).get("cross_project_leak_commands"),
        "demonstrated": bool(ledger_claims) and bool(fieldnotes_claims) and not leaked and not text_leaks and not any("PYTHONPATH" in t for t in delivered_b)
                        and a.installation_id != b.installation_id and rec["outcomes"]["task_success"],
    }


def zero_interventions(trials_dir: Path, workload_dir: Path) -> dict[str, Any]:
    trials = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(trials_dir.glob("*.json"))] if trials_dir.is_dir() else []
    days = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(workload_dir.glob("*.json"))] if workload_dir.is_dir() else []
    interventions = sum(int(t["outcomes"].get("operator_interventions") or 0) for t in trials)
    waiting_human = sum(int((t.get("background") or {}).get("jobs_by_state", {}).get("awaiting_operator", 0)) for t in trials)
    return {"trials": len(trials), "workload_days": len(days), "operator_interventions": interventions, "jobs_awaiting_a_human": waiting_human,
            "demonstrated": bool(trials) and interventions == 0 and waiting_human == 0,
            "note": "memory formation, review, revision and delivery ran without any operator command; the forgetting demonstration's backup/forget/restore are intentional privacy operations, not routine maintenance"}


def run_all(work: Path, *, trials_dir: Path) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    demos: dict[str, Any] = {}
    for name, fn in (("fresh_session_reuse", lambda: fresh_session_reuse(trials_dir, work)), ("changed_condition_revision", lambda: changed_condition_revision(trials_dir, work)),
                     ("forgetting_and_restore", lambda: forgetting_and_restore(work)), ("isolation", lambda: isolation(trials_dir, work)),
                     ("zero_interventions", lambda: zero_interventions(trials_dir, trials_dir.parent / "workload"))):
        try:
            demos[name] = fn()
        except Exception as exc:  # noqa: BLE001 - a failed demonstration is reported, never dropped
            demos[name] = {"demonstrated": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    return {"mode": "scripted", "label": "scripted agent + recorded curator through the real engine; not a live demonstration (B1)", "demonstrations": demos}
