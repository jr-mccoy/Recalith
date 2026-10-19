"""The final read-only fence before emission (SYSTEM_SPEC §8.3; DATA_CONTRACTS §2.3, §9).

Standard library and ``recalith.fast`` only. The fence opens a **fresh**
read-only snapshot (never the snapshot the packet was compiled from) with
``mode=ro``, ``query_only``, ``busy_timeout=0`` and a write-denying
authorizer, and accepts the packet only when the store's guidance, policy and
tombstone epochs still equal the packet's and every served record head is
still at the served revision in a servable state. It is the delivery
linearization point: a correction, forget, recheck or retirement committed
before it excludes the old guidance. A change committed after it may race with
output that has already started, which cannot be retracted; the timing is
returned so tests and delivery receipts record it rather than claim
otherwise. The fence never waits for a lock and never repairs the store: an
unavailable snapshot fails closed (``store_snapshot_unavailable``).
"""

from __future__ import annotations

import time

from recalith.fast import cache
from recalith.fast.wire import utc_now

SERVABLE = {"claim": ("claim_heads", "claim_id", "status", ("candidate", "active", "disputed")), "task": ("task_heads", "task_id", "status", ("active", "paused", "completed")), "episode": ("episode_heads", "episode_id", "state", ("open", "settled"))}


def check(root: str, packet: dict, *, deadline: float, overlay_ids=frozenset()) -> dict:
    """``{"ok", "reason", "fenced_at", "fence_ms"}`` for ``packet`` against a fresh snapshot.

    ``overlay_ids`` names event items the delivery branch took from the session
    overlay (typed outcomes captured but possibly not yet ingested): such an
    event may still be absent from the store, but once ingested it must hold
    available evidence like any other event item; the equal tombstone epoch
    fences forgetting for both (decision 0015).
    """
    started = time.monotonic()
    out = {"ok": False, "reason": None, "fenced_at": None, "fence_ms": None}
    try:
        conn = cache.open_snapshot(root)
    except cache.SnapshotUnavailable:
        out["reason"] = "store_snapshot_unavailable"
        return out
    try:
        meta = cache.read_meta(conn)
        if meta is None or (meta["project_id"], meta["installation_id"]) != (packet["project_id"], packet["installation_id"]):
            out["reason"] = "store_snapshot_unavailable"
            return out
        if any(meta[k] != packet[k] for k in ("guidance_epoch", "policy_revision", "tombstone_epoch")):
            out["reason"] = "fence_epoch_changed"
            return out
        for item in packet["items"]:
            ref = item["ref"]
            if ref["kind"] in SERVABLE:
                table, key, column, ok = SERVABLE[ref["kind"]]
                row = conn.execute(f"SELECT revision, {column} FROM {table} WHERE {key} = ?", (ref["id"],)).fetchone()  # noqa: S608 - fixed names
                if row is None or row[0] != ref["revision"] or row[1] not in ok:
                    out["reason"] = "fence_record_changed"
                    return out
            elif ref["kind"] == "event":
                row = conn.execute("SELECT payload_state FROM events WHERE event_id = ?", (ref["id"],)).fetchone()
                if row is None and ref["id"] in overlay_ids:
                    continue
                if row is None or row[0] != "available":
                    out["reason"] = "fence_record_changed"
                    return out
        out["ok"] = True
        return out
    except cache.sqlite3.Error:
        out["reason"] = "store_snapshot_unavailable"
        return out
    finally:
        cache.close(conn)
        out["fenced_at"] = utc_now()
        out["fence_ms"] = round((time.monotonic() - started) * 1000, 3)
        if time.monotonic() > deadline and out["ok"]:
            out["late"] = True  # the fence held, but after the soft deadline: delivery decides whether to emit
