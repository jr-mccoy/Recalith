"""Test-only builders for Task 12b: delivery accounting, the session overlay and corrections at the fence.

Real inputs: every Claude event enters through the real 2.1.301 adapter
mapping, normalization, capture, ingestion and typed reduction
(``working_scenarios.Project``); the failure lesson is admitted through the
real extraction/review path with recorded proposals
(``consolidation_scenarios``); delivery runs the real delivery branch of
``fast.entry.handle_hook``, in process (``hook``) or as a fresh ``python -I
-m recalith.fast.entry`` process (``process``), on the real payloads. Real
payloads used: the lifecycle session's ``SessionStart``, prompts,
``PreToolUse``/``PostToolUseFailure`` of the failing ``pytest -q
test_mid.py`` (``toolu_probe_0003``), the passing ``pytest -q -s
test_pass.py`` result, ``PreCompact``, ``SessionStart(compact)`` and
``PostCompact``.

**Synthetic variants** (named at each use; payload shape, mapping and
normalization stay real): a second host session (another session ID and
tool-use IDs), reruns of real calls under new tool-use IDs (with the real
passing result for a fixed failure), changed prompt texts, and a ``.git/HEAD``
file in the workspace. **Controlled manifests**: delivery is enabled only by
``enable`` (``write_hook_context(..., delivery_paths=...)``) in these test
installations; nothing here enables it for a real host installation, and a
hook returning JSON is not a delivery certification (Task 13).

**Model behavior is recorded proposals** through the real persisted-proposal
path; nothing here measures live recall quality (B1).
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import retrieval_scenarios as rs  # first: puts tests/, tests/integration and tests/platform on sys.path
import claude_fixtures as cf  # noqa: E402
import consolidation_scenarios as cs  # noqa: E402
import operation_scenarios as osc  # noqa: E402
import working_scenarios as wks  # noqa: E402
from recalith.capture import pipeline  # noqa: E402
from recalith.capture.hooks import write_hook_context  # noqa: E402
from recalith.fast import claude_capture, entry, session  # noqa: E402
from recalith.retrieval import delivery as rd  # noqa: E402
from recalith.storage import db  # noqa: E402

ALL_PATHS = ("session_start", "prompt", "pre_action", "compact_restore")
MID = cs.MID
PASS = cs.PASS
SRC = cf.SRC


def enable(p: wks.Project, paths=ALL_PATHS) -> None:
    """A controlled test manifest with delivery enabled for ``paths`` (never a real host installation)."""
    write_hook_context(p.ctx, adapter_id="claude_code", host_version=cf.VERSION, delivery_paths=list(paths))


def project(tmp: Path, name: str = "delivery", *, paths=ALL_PATHS, lesson: bool = True) -> tuple[wks.Project, dict[str, str]]:
    """The reduced lifecycle session, an admitted failure lesson for ``test_mid``, published views, delivery enabled."""
    p = rs.project(tmp, name)
    ids: dict[str, str] = {}
    if lesson:
        ids["lesson"] = cs.lesson(p)
    rs.publish(p)
    enable(p, paths)
    return p, ids


def record(event: str, tool_use_id: str | None = None, n: int = 0) -> dict[str, Any]:
    return wks.record("lifecycle", event, tool_use_id, n)


def in_session(rec: dict[str, Any], session: str | None, **kw: Any) -> dict[str, Any]:
    """A synthetic variant of a real record in another host session (or the real one)."""
    if session is None and not kw:
        return rec
    return wks.variant(rec, session=session, **kw)


def hook(p: wks.Project, rec: dict[str, Any], *, seconds: float = 5.0, at: str | None = None, emit=None) -> tuple[dict[str, Any], list[bytes]]:
    """The real ``handle_hook`` (capture, delivery, overlay) in process with a generous deadline; returns (reply, stdout writes)."""
    data = p.replay.prepare(rec)
    ctx = entry.load_context(str(p.root), "claude_code")
    request = claude_capture.map_hook(ctx, json.loads(data.decode("utf-8")), registered_event=rec["event"], recorded_at=at)
    outputs: list[bytes] = []
    reply = entry.handle_hook(ctx, entry.normalize_request(ctx, request), deadline=time.monotonic() + seconds, inherited={}, emit=emit or outputs.append)
    return reply, outputs


def context_text(output: bytes) -> str:
    data = json.loads(output.decode("utf-8"))
    assert set(data) == {"hookSpecificOutput"} and set(data["hookSpecificOutput"]) == {"hookEventName", "additionalContext"}, data
    return data["hookSpecificOutput"]["additionalContext"]


# Test-only driver: the real ``entry.main`` in a fresh ``python -I`` process with a generous soft deadline, and
# optionally one failpoint armed to kill it. These cases judge accounting and kill/emit outcomes, not latency: a
# shared CI runner can stall a hook past the production 250 ms deadline, and the hook then rightly sheds delivery
# (``deadline_delivery_skipped``, asserted by its own tests and measured per platform by
# tools/measure_release_latency.py). The production entry has no deadline or failpoint switch.
DRIVER = r"""
import io, json, sys
sys.path.insert(0, sys.argv[1])
from recalith.fast import entry, failpoints
entry.SOFT_DEADLINE_SECONDS = 5.0
if sys.argv[3]:
    failpoints.arm(sys.argv[3], failpoints.kill)
data = open(sys.argv[2], "rb").read()
entry.main(json.loads(sys.argv[4]), stdin=io.BytesIO(data))
"""


def _driver(p: wks.Project, rec: dict[str, Any], tmp: Path, argv: list[str], *, failpoint: str = "", env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    payload = tmp / f"payload-{rec['seq']}-{time.monotonic_ns()}.json"
    payload.write_bytes(p.replay.prepare(rec))
    return subprocess.run([sys.executable, "-I", "-c", DRIVER, SRC, str(payload), failpoint, json.dumps(argv)], capture_output=True, env=cf.child_env() if env is None else env, timeout=60, check=False)


def process(p: wks.Project, rec: dict[str, Any], tmp: Path, *, tag: str = "", env: dict[str, str] | None = None) -> tuple[subprocess.CompletedProcess, dict[str, Any]]:
    """The real entry in a fresh ``python -I`` process (the test driver's generous deadline); returns (process, reply)."""
    reply_path = tmp / f"reply-{rec['seq']}-{tag or time.monotonic_ns()}.json"
    proc = _driver(p, rec, tmp, ["--project", str(p.root), "claude_code", "--event", rec["event"], "--reply-file", str(reply_path)], env=env)
    reply = json.loads(reply_path.read_text(encoding="utf-8")) if reply_path.exists() else {}
    return proc, reply


def killed_process(p: wks.Project, rec: dict[str, Any], tmp: Path, failpoint: str) -> subprocess.CompletedProcess:
    """The real entry in a fresh process, killed (``os._exit``) at one delivery failpoint; stdout is what reached the host."""
    return _driver(p, rec, tmp, ["--project", str(p.root), "claude_code", "--event", rec["event"]], failpoint=failpoint)


# --------------------------------------------------------------------------
# State


def scratch(p: wks.Project, session_id: str) -> dict[str, Any] | None:
    return session.read_scratch(p.root, session_id)


def deliveries(p: wks.Project, session_id: str | None = None) -> list[dict[str, Any]]:
    with p.view() as v:
        rows = v.execute(
            "SELECT delivery_id, attempt_id, session_id, purpose, state, estimated_tokens, substitution_tokens, items, restoration_key, trigger_event_id, in_flight_change, fenced_at, emitted_at "
            "FROM deliveries ORDER BY rowid"
        ).fetchall()
    keys = ("delivery_id", "attempt_id", "session_id", "purpose", "state", "estimated_tokens", "substitution_tokens", "items", "restoration_key", "trigger_event_id", "in_flight_change", "fenced_at", "emitted_at")
    out = [dict(zip(keys, r, strict=True)) for r in rows]
    for row in out:
        row["items"] = json.loads(row["items"])
    return [r for r in out if session_id is None or r["session_id"] == session_id]


def accounting(p: wks.Project, session_id: str) -> dict[str, Any]:
    with p.view() as v:
        return rd.session_accounting(v, session_id)


def links(p: wks.Project) -> list[tuple[str, str, list[str]]]:
    with p.view() as v:
        return [(d, label, json.loads(o)) for d, label, o in v.execute("SELECT delivery_id, label, observed_event_ids FROM outcome_links ORDER BY link_id").fetchall()]


def ingest(p: wks.Project) -> None:
    """Receipt and event ingestion only (no model, no budget)."""
    pipeline.ingest_ready(p.ctx)


def ids_in(text: str, *record_ids: str) -> list[str]:
    return [r for r in record_ids if r in text]


def session_of(p: wks.Project, host_session: str) -> str:
    return p.sid(host_session)


def charged(p: wks.Project, session_id: str) -> int:
    s = scratch(p, session_id)
    return 0 if s is None else s["reserved_tokens"]


def fresh_session(n: int) -> str:
    return wks.session_id(100 + n)


def meta(p: wks.Project) -> db.Meta:
    return osc.meta(p.root)


def call_records(tool_use_id: str, suffix: str, *, session: str | None = None, outcome_of: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """A rerun of a real call (synthetic variant: new tool-use ID; optionally the real result of another call)."""
    lifecycle = cf.records("lifecycle")
    pre = next(r for r in lifecycle if r["event"] == "PreToolUse" and r["payload"].get("tool_use_id") == tool_use_id)
    source = outcome_of or tool_use_id
    post = next(r for r in lifecycle if r["event"] in ("PostToolUse", "PostToolUseFailure") and r["payload"].get("tool_use_id") == source)
    if outcome_of:
        post = wks.variant(post, replace={source: tool_use_id})
        post["payload"]["tool_input"] = json.loads(json.dumps(pre["payload"]["tool_input"]))
    return wks.variant(pre, tool_suffix=suffix, session=session), wks.variant(post, tool_suffix=suffix, session=session)


def finish_event_id(p: wks.Project, rec: dict[str, Any]) -> str:
    """The event ID the adapter derives for a finished-tool record (whether or not it is ingested yet)."""
    from recalith.contracts.common import derived_id

    payload = rec["payload"]
    return derived_id("evt", [p.ctx.installation_id, "claude_code", f"{payload['session_id']}:tool:{payload['tool_use_id']}:finish"])


def event_in_store(p: wks.Project, event_id: str) -> bool:
    with p.view() as v:
        return v.execute("SELECT 1 FROM events WHERE event_id = ?", (event_id,)).fetchone() is not None


# --------------------------------------------------------------------------
# The kill/restart scenario (driven by worker_scenarios.py)
#
# A host session replayed through the real delivery branch, hook by hook, then
# a worker drain that ingests the receipts. The host never retries a killed
# hook: after a kill the driver goes on with the next hook (``progress``), as a
# real host does, then drains. Every hook's stdout is kept in ``outputs/<i>``
# (written and flushed by the hook's own emit, so it survives ``os._exit``).

SCENARIO = "delivery.json"
CRASH_SESSION = "00000000-0000-4000-8000-000000000777"


def crash_project(tmp: Path, name: str) -> Path:
    """Built, published and delivery-enabled; the script is a variant host session over real records."""
    p, ids = project(tmp / name)
    osc.cancel_trigger_extractions(p.root)
    pre_a, post_a = call_records(MID, "ca", session=CRASH_SESSION)
    pre_b, _ = call_records(MID, "cb", session=CRASH_SESSION)
    script = [
        in_session(record("SessionStart"), CRASH_SESSION),
        wks.variant(record("UserPromptSubmit"), session=CRASH_SESSION, prompt="Fix the fixture so test_mid passes."),
        pre_a, post_a, pre_b,
        in_session(record("PreCompact"), CRASH_SESSION),
        in_session(record("SessionStart", n=1), CRASH_SESSION),
        wks.variant(record("UserPromptSubmit"), session=CRASH_SESSION, prompt="Run test_mid once more."),
    ]
    (p.root / SCENARIO).write_text(json.dumps({"script": script, "lesson": ids["lesson"]}), encoding="utf-8")
    return p.root


def scenario(root: Path) -> dict[str, Any] | None:
    path = root / SCENARIO
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _replayer(root: Path) -> cf.Replay:
    replay = cf.Replay.__new__(cf.Replay)
    replay.root, replay.home, replay.host_tmp, replay.slug = root, root.parent / "home", root.parent / "host-tmp", "-replay-workspace"
    return replay


def run_script(root: Path, spec: dict[str, Any]) -> None:
    """Run the remaining hooks (the next one after the last started), each with its stdout file."""
    replay = _replayer(root)
    progress = root / "delivery-progress.json"
    outputs = root / "delivery-outputs"
    outputs.mkdir(exist_ok=True)
    start = json.loads(progress.read_text(encoding="utf-8"))["next"] if progress.exists() else 0
    for i in range(start, len(spec["script"])):
        rec = spec["script"][i]
        data = replay.prepare(rec)
        ctx = entry.load_context(str(root), "claude_code")
        request = entry.normalize_request(ctx, claude_capture.map_hook(ctx, json.loads(data.decode("utf-8")), registered_event=rec["event"]))
        trigger = request["events"][0]["event_id"] if request["events"] else None
        progress.write_text(json.dumps({"next": i + 1, "triggers": {**(json.loads(progress.read_text(encoding="utf-8"))["triggers"] if progress.exists() else {}), str(i): trigger}}), encoding="utf-8")
        with open(outputs / f"{i}.out", "wb") as fh:
            def emit(chunk: bytes, fh=fh) -> None:
                fh.write(chunk)
                fh.flush()

            entry.run(str(root), "claude_code", data, registered_event=rec["event"], env={}, deadline=time.monotonic() + 5, emit=emit)


def _scratches(root: Path) -> list[dict[str, Any]]:
    folder = Path(session.sessions_dir(root))
    out = []
    for path in sorted(folder.glob("sess_*.json")) if folder.is_dir() else []:
        data = session.read_scratch(root, path.stem)
        if data is not None:
            out.append(data)
    return out


def _spooled_receipts(root: Path) -> dict[str, set[str]]:
    """attempt ID → receipt states waiting in the spool (read from the segments themselves)."""
    out: dict[str, set[str]] = {}
    for path in (root / ".recalith" / "spool" / "ready").glob("*.json"):
        try:
            segment = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for env in segment.get("envelopes", []):
            if env.get("kind") == "memory_delivered":
                out.setdefault(env["payload"]["attempt_id"], set()).add(env["payload"]["state"])
    return out


def _rows(root: Path) -> dict[str, dict[str, Any]]:
    path = root / ".recalith" / db.STATE_DB
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        rows = conn.execute("SELECT attempt_id, session_id, state, estimated_tokens, trigger_event_id FROM deliveries").fetchall()
    finally:
        conn.close()
    return {a: {"session_id": s, "state": st, "tokens": t, "trigger": tr} for a, s, st, t, tr in rows}


def outstanding(root: Path) -> str:
    """``1`` while delivery accounting is owed, judged from the effects (read-only; scratch states are not trusted alone).

    Owed: an attempt still ``reserved``; any scratch attempt with no receipt in
    the spool and no accounting row; a spooled receipt not yet accounted.
    Complete by design: a receipt already accounted (e.g. ``ingest.after_commit``
    before the segment is unlinked).
    """
    try:
        rows = _rows(root)
    except sqlite3.Error:
        return "1"
    spooled = _spooled_receipts(root)
    for s in _scratches(root):
        for e in s["entries"]:
            if e["state"] == "reserved" or (e["attempt_id"] not in rows and e["attempt_id"] not in spooled):
                return "1"
    for attempt, states in spooled.items():
        row = rows.get(attempt)
        if row is None or ("emitted" in states and row["state"] != "emitted"):
            return "1"
    return "0"


def delivery_state(root: Path) -> dict[str, Any]:
    """The memory state (receipt events aside) plus the delivery accounting invariants, all of which must be zero/true.

    * ``reserved``: attempts left unresolved; ``unaccounted``: scratch attempts
      with no accounting row; ``double``: rows whose tokens differ from the
      attempt's charge (an attempt is one row by key, so a double charge shows as
      a total mismatch); ``charge_mismatch``: sessions whose scratch total
      differs from their accounted total; ``emitted_lt``: sessions whose
      accounted emitted tokens are below the scratch's (an emitted attempt lost);
    * ``emitted_without_output``: an emitted row whose hook wrote nothing to
      stdout (claimed emitted, never emitted); ``output_without_charge``: a hook
      that wrote context with no charged attempt for its event (an uncharged
      emission); ``spool_pending``: receipts never accounted.
    """
    memory = osc.normalized(root)
    ctx = osc.context(root)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        memory["counts"]["events"] = view.execute("SELECT COUNT(*) FROM events WHERE kind != 'memory_delivered'").fetchone()[0]
        sequences = [r[0] for r in view.execute("SELECT commit_sequence FROM events WHERE kind != 'memory_delivered' ORDER BY commit_sequence").fetchall()]
    # Receipt events take commit sequences too (a killed hook adds an uncertain one): compare the memory by
    # the order of the other events, never by raw sequence numbers.
    rank = {seq: i for i, seq in enumerate(sequences)}
    memory["bindings"] = sorted((kind, rank.get(seq), rank.get(first), binding) for kind, seq, first, binding in memory["bindings"])
    memory["reduction_cursor"] = bool(sequences) and memory["reduction_cursor"] >= sequences[-1]
    rows = _rows(root)
    scratches = _scratches(root)
    entries = {e["attempt_id"]: e for s in scratches for e in s["entries"]}
    progress_path = root / "delivery-progress.json"
    triggers = json.loads(progress_path.read_text(encoding="utf-8"))["triggers"] if progress_path.exists() else {}
    outputs = {i: (root / "delivery-outputs" / f"{i}.out") for i in triggers}
    wrote = {triggers[i] for i, path in outputs.items() if path.exists() and path.stat().st_size > 0}
    charged_triggers = {e.get("trigger_event_id") for e in entries.values()} | {r["trigger"] for r in rows.values()}
    inv = {
        "reserved": sum(1 for e in entries.values() if e["state"] == "reserved"),
        "unaccounted": sum(1 for a in entries if a not in rows),
        "double": sum(1 for a, e in entries.items() if a in rows and rows[a]["tokens"] != e["estimated_tokens"]),
        "charge_mismatch": sum(1 for s in scratches if s["reserved_tokens"] != sum(r["tokens"] for r in rows.values() if r["session_id"] == s["session_id"])),
        "emitted_lt": sum(1 for s in scratches if sum(r["tokens"] for r in rows.values() if r["session_id"] == s["session_id"] and r["state"] == "emitted") < s["emitted_tokens"]),
        "emitted_without_output": sum(1 for r in rows.values() if r["state"] == "emitted" and r["trigger"] not in wrote),
        "output_without_charge": sum(1 for t in wrote if t not in charged_triggers),
        "spool_pending": sum(1 for a, states in _spooled_receipts(root).items() if a not in rows),
    }
    return {"memory": memory, "invariants": inv, "hooks_run": len(triggers)}


def killed_attempt_states(root: Path) -> list[str]:
    """Accounted states of the attempts whose hooks wrote no completed mark (for the per-failpoint expectation)."""
    return sorted(r["state"] for r in _rows(root).values())
