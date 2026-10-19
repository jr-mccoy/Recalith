"""The hook's delivery branch: reservation, final fence, emission and receipts (SYSTEM_SPEC §5.1.1–§5.1.2, §8.2–§8.3; DATA_CONTRACTS §2.3, §9; decision 0015).

Standard library and ``recalith.fast`` only; the hook never writes SQLite.
Every store read is a bounded read-only snapshot (:mod:`recalith.fast.cache`);
accounting reaches the database only when the worker ingests the spooled
``memory_delivered`` receipt (:mod:`recalith.retrieval.delivery`).

One delivery, under the shared soft deadline that :func:`entry.handle_hook`
started at entry:

1. compile the packet from the worker's views or the bounded fallback rows
   (:func:`recalith.fast.cache.compile_packet`), each item with its
   suppression identity ``(record_id, revision, condition_digest)``;
2. take the per-session lock (at most 20 ms; a timeout skips delivery, never
   capture) and read the scratch and, in a fresh read-only snapshot, the
   session's durable receipts;
3. turn any attempt a dead predecessor left ``reserved`` into an
   ``uncertain`` one (still charged, never counted as emitted or seen) and
   spool its receipt;
4. drop items an emitted entry or an ingested emitted receipt already
   delivered under the same key and purpose class (restorations are keyed by
   their compaction cycle and repeat what compaction removed); add the
   session overlay's typed failures for this action and let its later
   successes and changed paths downgrade an older caution (labeled
   observations, never lessons);
5. fit the unchanged-memory allowance (4,000 per session; a caution, a
   conflict or a changed revision may exceed it within its packet cap;
   restorations are charged separately) and the packet caps, with the single
   shared 400-token substitution for an ordinary prompt when pre-action
   injection is unavailable;
6. **reserve**: write the attempt (state ``reserved``) and its full estimate
   to scratch before any output;
7. **final fence**: a fresh snapshot must still show the packet's guidance,
   policy and tombstone epochs and every served head; otherwise nothing is
   emitted and the reservation, which provably produced no output, is
   withdrawn. This is the linearization point: a correction, undo or forget
   committed before it excludes the old text;
8. write and flush stdout (the host's nonblocking context envelope); a fresh
   snapshot right after the flush records whether a change committed after
   the fence while the output was in flight (``in_flight_change``; never
   claimed retractable);
9. spool the emitted receipt, then mark the entry ``emitted``; release.

A crash anywhere between 6 and 9 leaves the attempt ``reserved``: the next
hook resolves it to ``uncertain``. Exactly-once stdout is not promised.
"""

from __future__ import annotations

import json
import os
import time

from recalith.fast import cache, claude_capture, failpoints, fence, session
from recalith.fast import context as fc
from recalith.fast.normalize import RawEvent, normalize_raw
from recalith.fast.wire import LIMITS, WireError, canonical_json, digest_of, is_valid, new_id, utc_now

PURPOSES = ("session_start", "prompt", "pre_action", "compact_restore")
UNCHANGED_SESSION_TOTAL = 4000  # SYSTEM_SPEC §8.2 default (ContextBudgetConfig.unchanged_session_total)
DURABLE_ROWS = 1024
OVERLAY_ITEMS = 2
RESPOOL_PER_HOOK = 4
RESPOOL_MIN_REMAINING = 0.100
SCRATCH_HEADROOM = 16 * 1024
WIRE_STDOUT_CAP = LIMITS["WIRE_STDOUT_CAP"]
BRANCH_BYTES = 512
CRITICAL = frozenset({"caution", "conflict"})


def _result(state: str, purpose=None, **extra) -> dict:
    out = {"state": state, "purpose": purpose}
    out.update(extra)
    return out


# --------------------------------------------------------------------------
# Query (the hook supplies the action, environment, branch and substitution)


def read_branch(workspace_root: str):
    """The current branch from ``.git/HEAD`` inside the registered workspace, else None (unknown).

    A bounded, no-follow read of one regular file; a linked worktree (``.git``
    is a file pointing outside the workspace), a detached head or anything
    unreadable is unknown. Never runs git.
    """
    git = os.path.join(workspace_root, ".git")
    try:
        if not os.path.isdir(git) or os.path.islink(git):
            return None
        fd = os.open(os.path.join(git, "HEAD"), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    except OSError:
        return None
    try:
        data = os.read(fd, BRANCH_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(fd)
    if len(data) > BRANCH_BYTES:
        return None
    try:
        text = data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    if not text.startswith("ref: refs/heads/"):
        return None
    branch = text[len("ref: refs/heads/"):]
    if not 1 <= len(branch) <= 256 or any(ord(ch) < 32 or ord(ch) == 127 for ch in branch):
        return None
    return branch


def purpose_for(ctx: dict, request: dict):
    """The delivery purpose of this hook from its registered role and the installed paths (DATA_CONTRACTS §2.3)."""
    events = request.get("events") or []
    if not events:
        return None
    kind = events[0]["kind"]
    role = request.get("event_role")
    if role == "session_start" and kind == "session_started":
        return "session_start"
    if role == "session_start" and kind == "compaction" and events[0]["payload"].get("phase") == "context_restored":
        return "compact_restore"
    if role == "prompt" and kind == "user_message":
        return "prompt"
    if role == "pre_tool" and kind == "tool_started":
        return "pre_action"
    return None


def build_query(ctx: dict, request: dict, purpose: str) -> dict:
    first = request["events"][0]
    payload = first["payload"]
    text = payload.get("text") if purpose in ("prompt", "compact_restore") and isinstance(payload.get("text"), str) else ""
    action = payload.get("action") if purpose == "pre_action" else None
    return {
        "session_id": first["session_id"], "task_id": None, "workspace_id": ctx["workspace_id"], "purpose": purpose, "text": text[:16384],
        "action": action, "environment": claude_capture.platform_facts(), "max_estimated_tokens": None, "branch_ref": read_branch(ctx["workspace_root"]),
    }


# --------------------------------------------------------------------------
# Receipts (hook_record_delivery: DATA_CONTRACTS §2.3)


def delivery_id_of(attempt_id: str) -> str:
    return "dlv_" + attempt_id.split("_", 1)[1]


def receipt_of(ctx: dict, session_id: str, entry: dict, *, emitted: bool, emitted_at=None, fenced_at=None, in_flight_change=None) -> dict:
    """The ``DeliveryReceipt`` primitive for one scratch attempt."""
    return {
        "delivery_id": delivery_id_of(entry["attempt_id"]), "attempt_id": entry["attempt_id"], "host_id": ctx["adapter_id"], "session_id": session_id,
        "task_id": entry.get("task_id"), "packet_digest": entry["packet_digest"], "items": [dict(i) for i in entry["items"]], "purpose": entry["purpose"],
        "fence_store_revision": entry.get("fence_store_revision", 0), "guidance_epoch": entry.get("guidance_epoch", 0), "policy_revision": entry.get("policy_revision", 1),
        "tombstone_epoch": entry.get("tombstone_epoch", 0), "generated_at": entry.get("generated_at") or entry["time"], "emitted_at": emitted_at if emitted else None,
        "estimated_tokens": entry["estimated_tokens"], "pre_action_substitution_tokens": entry.get("substitution_tokens", 0), "state": "emitted" if emitted else "uncertain",
        "restoration_key": entry.get("restoration_key"), "trigger_event_id": entry.get("trigger_event_id"), "fenced_at": fenced_at if emitted else None,
        "in_flight_change": in_flight_change if emitted else None,
    }


def hook_record_delivery(ctx: dict, attempt: dict, *, emitted: bool, deadline: float | None = None) -> dict:
    """Spool one attempt's receipt as a ``memory_delivered`` event; returns ``{"receipt", "capture"}``.

    ``attempt`` is a scratch entry plus ``session_id`` and ``host_session_id``
    (and, for an emitted one, ``emitted_at``, ``fenced_at`` and
    ``in_flight_change``). The event key names the attempt and state, so a
    re-spooled receipt is a duplicate at ingestion, and an emitted receipt and
    an uncertain one for the same attempt are accounted once (the emitted one
    wins). The receipt holds identities, digests and counts only.
    """
    from recalith.fast import entry as fast_entry

    receipt = receipt_of(ctx, attempt["session_id"], attempt, emitted=emitted, emitted_at=attempt.get("emitted_at"), fenced_at=attempt.get("fenced_at"), in_flight_change=attempt.get("in_flight_change"))
    if not is_valid("DeliveryReceipt", receipt):
        return {"receipt": None, "capture": {"status": "not_captured", "segment_id": None, "event_ids": [], "coverage": {"reason": "receipt_invalid"}, "error_code": "invalid_schema"}}
    raw = RawEvent(
        adapter_id=ctx["adapter_id"], adapter_version=(ctx.get("host_version") or "unknown")[:64], source_event_key=f"delivery:{attempt['attempt_id']}:{receipt['state']}",
        session_id=attempt["session_id"], host_session_id=attempt["host_session_id"], kind="memory_delivered", payload=receipt, certified=True, origin_kind="hook",
    )
    ids = {"project_id": ctx["project_id"], "installation_id": ctx["installation_id"], "workspace_id": ctx["workspace_id"]}
    try:
        envelopes, _notes = normalize_raw(ids, raw)
    except WireError as exc:
        return {"receipt": receipt, "capture": {"status": "not_captured", "segment_id": None, "event_ids": [], "coverage": {"reason": exc.code}, "error_code": exc.code}}
    capture = fast_entry.hook_capture(ctx, envelopes, deadline=deadline, scrubbed_in_process=frozenset(e["event_id"] for e in envelopes))
    return {"receipt": receipt, "capture": capture}


# --------------------------------------------------------------------------
# Durable accounting (read-only)


def durable_receipts(conn, session_id: str) -> list:
    rows = conn.execute(
        "SELECT attempt_id, state, purpose, estimated_tokens, restoration_key, items FROM deliveries WHERE session_id = ? ORDER BY rowid LIMIT ?", (session_id, DURABLE_ROWS)
    ).fetchall()
    out = []
    for attempt, state, purpose, tokens, key, items in rows:
        try:
            parsed = json.loads(items)
        except ValueError:
            parsed = []
        out.append({"attempt_id": attempt, "state": state, "purpose": purpose, "estimated_tokens": tokens, "restoration_key": key, "items": parsed if isinstance(parsed, list) else []})
    return out


def purpose_class(purpose: str, restoration_key) -> str:
    """Suppression class: a restoration is keyed by its compaction cycle; everything else is ordinary."""
    return f"restore:{restoration_key}" if purpose == "compact_restore" else "ordinary"


def seen_keys(entries: list, durable: list) -> tuple:
    """Emitted ``(record_id, revision, condition_digest, class)`` keys and last emitted revisions per record."""
    keys, revisions = set(), {}
    for row in [*entries, *durable]:
        if row["state"] != "emitted":
            continue  # reserved and uncertain attempts are charged, never seen
        cls = purpose_class(row["purpose"], row.get("restoration_key"))
        for item in row["items"]:
            if not isinstance(item, dict):
                continue
            keys.add((item.get("record_id"), item.get("revision"), item.get("condition_digest"), cls))
            if cls == "ordinary":
                revisions[item.get("record_id")] = max(revisions.get(item.get("record_id"), 0), item.get("revision") or 0)
    return keys, revisions


def charged_ordinary(scratch: dict, durable: list) -> int:
    """Unchanged-memory tokens charged in this session: scratch counters floored by the durable receipts.

    The durable rows plus the scratch attempts not yet durable; the scratch's
    own running total wins when larger (pruning never lowers it). An attempt is
    counted once by its attempt ID.
    """
    durable_ids = {r["attempt_id"] for r in durable}
    union = sum(r["estimated_tokens"] for r in durable if r["restoration_key"] is None)
    union += sum(e["estimated_tokens"] for e in scratch["entries"] if e["attempt_id"] not in durable_ids and e.get("restoration_key") is None)
    return max(scratch["reserved_tokens"] - scratch["restoration_tokens"], union)


# --------------------------------------------------------------------------
# The session overlay


def _outcome_text(outcome: dict) -> str:
    action = outcome["action"]
    command = " ".join(action["argv"]) if action.get("argv") else action.get("tool") or "a tool call"
    word = {"failure": "failed", "interrupted": "was interrupted"}.get(outcome["outcome"], outcome["outcome"])
    cov = outcome.get("coverage") or {}
    note = " (output truncated: incomplete)" if cov.get("truncated") else ""
    return fc.bounded(f"Observed in this session, not yet ingested: `{fc.bounded(command, 240)}` {word}{note}. An observation, not a durable lesson.", 700)


def _paths(action) -> set:
    return set((action or {}).get("paths") or [])


def overlay_items(ctx: dict, scratch: dict, query: dict, purpose: str, present: set) -> list:
    """At most two recent typed failures from scratch, relevant to this delivery, as labeled observations."""
    family = fc.action_family(ctx["workspace_id"], query.get("action"))
    query_paths = _paths(query.get("action")) if (query.get("action") or {}).get("parse_status") == "exact" else set()
    out = []
    for outcome in reversed(scratch["outcomes"]):
        if outcome["event_id"] in present or outcome["outcome"] not in ("failure", "interrupted"):
            continue
        if purpose == "pre_action":
            same = family is not None and fc.action_family(ctx["workspace_id"], outcome["action"]) == family
            if not same and not (query_paths & _paths(outcome["action"])):
                continue
            app = fc.TRUE if same else fc.UNKNOWN
        elif purpose in ("prompt", "compact_restore"):
            app = fc.UNKNOWN
        else:
            continue
        why = ["recent_observation", "this session's own typed tool outcome from the overlay, ahead of worker ingestion"]
        item = {"ref": {"kind": "event", "id": outcome["event_id"], "revision": 1}, "text": _outcome_text(outcome), "advice": "context", "basis": "observed", "scope": {},
                "applicability": app, "freshness": "current", "why": why, "evidence_refs": [], "conditions_text": None, "retry_text": None}
        # The observation itself is the key (its label differs by purpose): delivered once per session.
        key = {"record_id": outcome["event_id"], "revision": 1, "condition_digest": digest_of(["overlay", outcome["outcome"], outcome.get("coverage") or {}]), "family": None, "paths": []}
        out.append((item, key))
        if len(out) >= OVERLAY_ITEMS:
            break
    return out


def overlay_invalidations(ctx: dict, scratch: dict) -> tuple:
    """Action families that later succeeded and paths that changed in this session's overlay."""
    succeeded, changed = set(), set()
    for outcome in scratch["outcomes"]:
        if outcome["outcome"] == "success":
            family = fc.action_family(ctx["workspace_id"], outcome["action"])
            if family is not None:
                succeeded.add(family)
        changed.update(outcome.get("changed_paths") or [])
    return succeeded, changed


def _downgrade(item: dict, key: dict, reason: str) -> tuple:
    why = (list(item["why"]) + [reason])[:8]
    return dict(item, advice="context", why=why), dict(key, condition_digest=digest_of([key["condition_digest"], "overlay", reason]))


# --------------------------------------------------------------------------
# Assembly under the session allowance


def _critical(item: dict) -> bool:
    return item["advice"] in CRITICAL or item["why"][0] == "revision_change"


def fit(purpose: str, pairs: list, *, remaining: int, substitute: bool, max_tokens) -> tuple:
    """Packet caps first, then the unchanged allowance: ordinary items drop from the end until the packet fits.

    A caution, a conflict or a changed revision may exceed the allowance
    within its packet cap; the whole estimate is charged either way.
    Restorations are outside the allowance.
    """
    items = [i for i, _k in pairs]
    keys = {id(i): k for i, k in pairs}
    assembled = fc.assemble(purpose, items, max_estimated_tokens=max_tokens, substitute_pre_action=substitute and purpose == "prompt")
    budget_cut = 0
    if purpose != "compact_restore":
        chosen = list(assembled["items"])
        while chosen and assembled["estimated_tokens"] > remaining and any(not _critical(i) for i in chosen):
            drop = max(i for i, item in enumerate(chosen) if not _critical(item))
            chosen.pop(drop)
            budget_cut += 1
            assembled = fc.assemble(purpose, chosen, max_estimated_tokens=max_tokens, substitute_pre_action=substitute and purpose == "prompt")
            chosen = list(assembled["items"])
    assembled["omitted_count"] += budget_cut
    return assembled, [keys[id(i)] for i in assembled["items"]], budget_cut


# --------------------------------------------------------------------------
# The delivery branch


def _save(root, scratch: dict) -> None:
    scratch["state_revision"] += 1
    session.write(root, scratch)


def _respool(ctx: dict, scratch: dict, durable_ids: set, host_session_id: str, deadline: float, *, limit: int) -> int:
    """Spool receipts a predecessor could not (disk full, crash): uncertain or emitted, idempotent by key."""
    done = 0
    for entry in scratch["entries"]:
        if done >= limit or deadline - time.monotonic() < RESPOOL_MIN_REMAINING:
            break
        if entry["receipt_spooled"] or entry["state"] == "reserved" or entry["attempt_id"] in durable_ids:
            continue
        attempt = dict(entry, session_id=scratch["session_id"], host_session_id=host_session_id)
        result = hook_record_delivery(ctx, attempt, emitted=entry["state"] == "emitted", deadline=deadline)
        if result["capture"]["status"] == "accepted":
            entry["receipt_spooled"] = True
        done += 1
    return done


def _prune(scratch: dict, durable_ids: set) -> None:
    """Drop the oldest durably accounted entries until the next entry fits (counters unchanged)."""
    while scratch["entries"] and (len(scratch["entries"]) >= session.MAX_ENTRIES or len(canonical_json(scratch)) > session.SCRATCH_CAP - SCRATCH_HEADROOM):
        index = next((i for i, e in enumerate(scratch["entries"]) if e["attempt_id"] in durable_ids and e["state"] != "reserved"), None)
        if index is None:
            return
        scratch["entries"].pop(index)


def settle(ctx: dict, session_id: str, host_session_id: str, *, deadline: float) -> str:
    """Before a finished session's scratch is discarded: resolve dead reservations and spool every receipt still owed.

    Returns ``settled`` or a content-free degradation; the scratch is left in
    place (not discarded) when a receipt could not be spooled.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return "deadline_overlay_skipped"
    if not session.locking_supported():
        return "scratch_lock_unsupported"
    lock = session.SessionLock(ctx["root"], session_id)
    try:
        if not lock.acquire(min(session.LOCK_WAIT_SECONDS, remaining)):
            return "scratch_lock_timeout"
        scratch, state = session.load(ctx["root"], session_id, ctx["policy_revision"])
        if state != "present":
            return "settled"
        for entry in scratch["entries"]:
            if entry["state"] == "reserved":
                entry["state"], entry["receipt_spooled"] = "uncertain", False
        _respool(ctx, scratch, set(), host_session_id, deadline + RESPOOL_MIN_REMAINING, limit=len(scratch["entries"]))
        _save(ctx["root"], scratch)
        return "settled" if all(e["receipt_spooled"] for e in scratch["entries"]) else "receipt_not_captured"
    except (OSError, ValueError):
        return "scratch_io_error"
    finally:
        lock.release()


def deliver(ctx: dict, request: dict, *, deadline: float, emit) -> dict:
    """One hook's delivery (see the module docstring); returns the reply's ``delivery`` state. Never raises."""
    purpose = purpose_for(ctx, request)
    if purpose is None:
        return _result("none")
    events = request["events"]
    first = events[0]
    session_id, host_session_id = first["session_id"], first["host_session_id"]
    root = ctx["root"]
    paths = ctx.get("delivery_paths") or []
    if purpose == "compact_restore" and "compact_restore" not in paths:
        return _result("unavailable", purpose, reason="path_not_installed")
    if purpose == "prompt" and "compact_restore" not in paths:
        hint = session.read_scratch(root, session_id)  # an unlocked hint; rechecked under the lock
        if hint and hint["compaction_key"] and hint["compaction_key"] not in hint["restored"]:
            purpose = "compact_restore"  # the one keyed restoration falls back to the next certified prompt path
    if purpose not in paths and not (purpose == "compact_restore" and "prompt" in paths):
        return _result("unavailable", purpose, reason="path_not_installed")
    if emit is None:
        return _result("unavailable", purpose, reason="no_output_channel")
    if deadline - time.monotonic() < fc.FENCE_TAIL:
        return _result("skipped", purpose, reason="deadline_delivery_skipped")
    if not session.locking_supported():
        return _result("skipped", purpose, reason="scratch_lock_unsupported")
    query = build_query(ctx, request, purpose)
    substitute = purpose in ("prompt", "compact_restore") and "pre_action" not in paths
    if substitute and purpose == "prompt":
        # Pre-action injection is unavailable: the prompt carries the caution for the session's latest action
        # (its typed outcome from the overlay), in the one shared 400-token substitution allowance.
        hint = session.read_scratch(root, session_id)
        latest = hint["outcomes"][-1]["action"] if hint and hint["outcomes"] else None
        if latest is not None and latest.get("parse_status") == "exact":
            query["action"] = latest
    restore = frozenset()
    if purpose == "compact_restore":
        hint = session.read_scratch(root, session_id)
        restore = frozenset(i["record_id"] for e in (hint or {}).get("entries", []) if e["state"] == "emitted" for i in e["items"])
    compiled = cache.compile_packet(ctx, query, deadline=deadline, substitute_pre_action=substitute and purpose == "prompt", restore_ids=restore)
    packet = compiled["packet"]
    reasons = list(packet["degraded_reasons"])
    lock = session.SessionLock(root, session_id)
    wait = min(session.LOCK_WAIT_SECONDS, deadline - time.monotonic() - fc.FENCE_TAIL / 2)
    try:
        acquired = wait > 0 and lock.acquire(wait)
    except OSError:
        acquired = False
    if not acquired:
        return _result("skipped", purpose, reason="scratch_lock_timeout", degraded=reasons)
    try:
        return _locked(ctx, request, purpose, query, compiled, reasons, session_id=session_id, host_session_id=host_session_id, substitute=substitute, deadline=deadline, emit=emit)
    except Exception:  # noqa: BLE001 - delivery never fails the hook; an unresolved reservation stays charged
        return _result("skipped", purpose, reason="delivery_internal_error", degraded=reasons)
    finally:
        lock.release()


def _locked(ctx, request, purpose, query, compiled, reasons, *, session_id, host_session_id, substitute, deadline, emit) -> dict:
    root = ctx["root"]
    scratch, state = session.load(root, session_id, ctx["policy_revision"])
    if state == "invalid":
        reasons.append("scratch_invalid")
    try:
        conn = cache.open_snapshot(root)
    except cache.SnapshotUnavailable:
        return _result("skipped", purpose, reason="store_snapshot_unavailable", degraded=reasons)
    try:
        meta = cache.read_meta(conn)
        durable = durable_receipts(conn, session_id)
    except cache.sqlite3.Error:
        return _result("skipped", purpose, reason="store_snapshot_unavailable", degraded=reasons)
    finally:
        cache.close(conn)
    if meta is None:
        return _result("skipped", purpose, reason="store_snapshot_unavailable", degraded=reasons)
    durable_ids = {r["attempt_id"] for r in durable}
    dirty = state != "present"
    if (scratch["policy_revision"], scratch["tombstone_epoch"]) != (meta["policy_revision"], meta["tombstone_epoch"]) and state == "present":
        scratch["outcomes"] = []  # old overlay content is invalid after a policy/tombstone change; totals stay
        reasons.append("scratch_epoch_reset")
        dirty = True
    for key in ("store_revision", "guidance_epoch", "policy_revision", "tombstone_epoch"):
        scratch[key] = meta[key]
    for entry in scratch["entries"]:
        if entry["state"] == "reserved":  # its hook died between reservation and mark: charged, never seen
            entry["state"] = "uncertain"
            entry["receipt_spooled"] = False
            dirty = True
    if any(not e["receipt_spooled"] and e["state"] != "reserved" and e["attempt_id"] not in durable_ids for e in scratch["entries"]):
        if _respool(ctx, scratch, durable_ids, host_session_id, deadline, limit=RESPOOL_PER_HOOK):
            dirty = True

    def finish(result: dict) -> dict:
        if dirty:
            _save(root, scratch)
        return result

    restoration = None
    if purpose == "compact_restore":
        restoration = scratch["compaction_key"]
        delivered = set(scratch["restored"]) | {r["restoration_key"] for r in durable if r["restoration_key"]}
        if restoration is None or restoration in delivered:
            return finish(_result("none", purpose, reason="restoration_already_delivered" if restoration else "no_compaction_cycle", degraded=reasons))
    packet = compiled["packet"]
    keys = compiled.get("keys") or []
    seen, revisions = seen_keys(scratch["entries"], durable)
    cls = purpose_class(purpose, restoration)
    succeeded, changed = overlay_invalidations(ctx, scratch)
    pairs, suppressed = [], 0
    for item, key in zip(packet["items"], keys, strict=True):
        if item["advice"] == "caution":
            if key["family"] is not None and key["family"] in succeeded:
                item, key = _downgrade(item, key, "a later run of this action succeeded in this session (pending revalidation)")
            elif set(key["paths"]) & changed:
                item, key = _downgrade(item, key, "a dependency changed in this session (pending revalidation)")
        if (key["record_id"], key["revision"], key["condition_digest"], cls) in seen:
            suppressed += 1
            continue
        if cls == "ordinary" and 0 < revisions.get(key["record_id"], 0) < key["revision"]:
            item = dict(item, why=["revision_change", f"{item['why'][0]}: changed since revision {revisions[key['record_id']]} was delivered in this session", *item["why"][1:]][:8])
        pairs.append((item, key))
    present = {i["ref"]["id"] for i, _k in pairs} | {i["ref"]["id"] for i in packet["items"]}
    overlay_refs = set()
    for item, key in overlay_items(ctx, scratch, query, purpose, present):
        if (key["record_id"], key["revision"], key["condition_digest"], cls) in seen:
            suppressed += 1
            continue
        pairs.append((item, key))
        overlay_refs.add(key["record_id"])
    remaining = UNCHANGED_SESSION_TOTAL - charged_ordinary(scratch, durable)
    assembled, chosen_keys, cut = fit(purpose, pairs, remaining=remaining, substitute=substitute, max_tokens=query.get("max_estimated_tokens"))
    if cut:
        reasons.append("session_budget_exhausted")
    if not assembled["items"]:
        return finish(_result("none", purpose, suppressed=suppressed, degraded=sorted(set(reasons)), reason="nothing_to_deliver"))
    meta_of_packet = {k: packet[k] for k in ("store_revision", "guidance_epoch", "policy_revision", "tombstone_epoch")}
    final = fc.packet(ctx, purpose, meta_of_packet, assembled, reasons, generated_at=packet["generated_at"])
    if not is_valid("ContextPacket", final):
        return finish(_result("skipped", purpose, reason="packet_invalid", degraded=reasons))
    _prune(scratch, durable_ids)
    if len(scratch["entries"]) >= session.MAX_ENTRIES or len(canonical_json(scratch)) > session.SCRATCH_CAP - SCRATCH_HEADROOM:
        return finish(_result("skipped", purpose, reason="scratch_capacity", degraded=reasons))  # wait for worker accounting
    attempt_id = new_id("att")
    entry = {
        "attempt_id": attempt_id, "packet_digest": digest_of(final), "items": [{"record_id": k["record_id"], "revision": k["revision"], "condition_digest": k["condition_digest"]} for k in chosen_keys],
        "state": "reserved", "purpose": purpose, "estimated_tokens": final["estimated_tokens"], "time": utc_now(), "substitution_tokens": final["pre_action_substitution_tokens"],
        "task_id": compiled.get("task_id"), "restoration_key": restoration, "trigger_event_id": request["events"][0]["event_id"], "generated_at": final["generated_at"],
        "fence_store_revision": final["store_revision"], "guidance_epoch": final["guidance_epoch"], "policy_revision": final["policy_revision"],
        "tombstone_epoch": final["tombstone_epoch"], "receipt_spooled": False, "emitted_at": None, "fenced_at": None, "in_flight_change": None,
    }
    scratch["entries"].append(entry)
    scratch["reserved_tokens"] += entry["estimated_tokens"]
    if restoration is not None:
        scratch["restoration_tokens"] += entry["estimated_tokens"]
        scratch["restored"] = (scratch["restored"] + [restoration])[-session.MAX_RESTORED:]
    _save(root, scratch)  # the reservation: before any byte reaches stdout
    dirty = False
    failpoints.hit(failpoints.DELIVERY_AFTER_RESERVE)
    fenced = fence.check(root, final, deadline=deadline, overlay_ids=frozenset(overlay_refs))
    if not fenced["ok"]:
        # Nothing was written: withdraw the reservation (it never emitted) and emit no memory.
        scratch["entries"].remove(entry)
        scratch["reserved_tokens"] -= entry["estimated_tokens"]
        if restoration is not None:
            scratch["restoration_tokens"] -= entry["estimated_tokens"]
            scratch["restored"] = [k for k in scratch["restored"] if k != restoration]
        _save(root, scratch)
        return _result("fenced_out", purpose, reason=fenced["reason"], degraded=sorted(set(reasons + [fenced["reason"]])), fence_ms=fenced["fence_ms"])
    failpoints.hit(failpoints.DELIVERY_AFTER_FENCE)
    output = claude_capture.context_output(request.get("host_event") or claude_capture.DELIVERY_EVENTS[purpose], fc.render_packet(purpose, final["items"]))
    data = json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > WIRE_STDOUT_CAP:
        scratch["entries"].remove(entry)
        scratch["reserved_tokens"] -= entry["estimated_tokens"]
        _save(root, scratch)
        return _result("skipped", purpose, reason="host_output_oversized", degraded=reasons)
    try:
        emit(data)
    except Exception:  # noqa: BLE001 - a partial write may have reached the host: uncertain, still charged
        entry["state"] = "uncertain"
        attempt = dict(entry, session_id=session_id, host_session_id=host_session_id)
        entry["receipt_spooled"] = hook_record_delivery(ctx, attempt, emitted=False, deadline=deadline)["capture"]["status"] == "accepted"
        _save(root, scratch)
        return _result("uncertain", purpose, attempt_id=attempt_id, reason="emission_failed", estimated_tokens=entry["estimated_tokens"], degraded=reasons)
    emitted_at = utc_now()
    failpoints.hit(failpoints.DELIVERY_AFTER_EMIT)
    in_flight = _in_flight_change(root, final)
    entry.update(emitted_at=emitted_at, fenced_at=fenced["fenced_at"], in_flight_change=in_flight)
    attempt = dict(entry, session_id=session_id, host_session_id=host_session_id)
    spooled = hook_record_delivery(ctx, attempt, emitted=True, deadline=deadline)
    failpoints.hit(failpoints.DELIVERY_AFTER_RECEIPT)
    entry["state"] = "emitted"
    entry["receipt_spooled"] = spooled["capture"]["status"] == "accepted"
    scratch["emitted_tokens"] += entry["estimated_tokens"]
    _save(root, scratch)
    failpoints.hit(failpoints.DELIVERY_AFTER_MARK)
    if not entry["receipt_spooled"]:
        reasons.append("receipt_not_captured")
    if fenced.get("late"):
        reasons.append("delivery_deadline_overrun")
    return _result(
        "emitted", purpose, attempt_id=attempt_id, estimated_tokens=entry["estimated_tokens"], substitution_tokens=entry["substitution_tokens"], items=len(final["items"]),
        suppressed=suppressed, source=compiled.get("source"), restoration_key=restoration, in_flight_change=in_flight, fence_ms=fenced["fence_ms"],
        receipt=spooled["receipt"], degraded=sorted(set(reasons)), host_output=output,
    )


def _in_flight_change(root: str, packet: dict):
    """After the flush: did a change commit after the fence while the output was in flight? (None: not observable)."""
    try:
        conn = cache.open_snapshot(root)
    except cache.SnapshotUnavailable:
        return None
    try:
        meta = cache.read_meta(conn)
    except cache.sqlite3.Error:
        return None
    finally:
        cache.close(conn)
    if meta is None:
        return None
    return any(meta[k] != packet[k] for k in ("guidance_epoch", "policy_revision", "tombstone_epoch"))
