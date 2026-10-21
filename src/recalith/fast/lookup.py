"""The hook's bounded lexical lookup into worker-published candidate rows (SYSTEM_SPEC §5.1.1; DATA_CONTRACTS §2.3, §10; decision 0021).

Standard library and ``recalith.fast`` only; nothing here imports
``sqlite3`` (the caller's read-only snapshot connection is passed in),
Pydantic, the service layer or the full search/ranking modules.

The worker keeps, per workspace, one pre-rendered candidate row for every
live claim head (``lookup_candidates``, in the primitive form views carry)
and a posting for every term of a servable row (``lookup_postings``). The
terms are the candidate's own ``terms``, produced by
:func:`recalith.fast.context.terms`: the indexer and this reader use one
tokenizer. For a prompt compile :func:`candidates` reads, inside the hook's
existing snapshot and deadline:

* the first :data:`QUERY_TERMS` distinct query terms, each with a document
  frequency counted up to :data:`DF_CAP` + 1;
* the :data:`TERMS` rarest present terms' posting lists, at most
  :data:`POSTINGS` entries each, strongest static score first;
* at most :data:`ROWS` candidate rows, by summed term weight
  ``1 + ln((DF_CAP + 1) / df)``, skipping claims the view or fallback rows
  already hold.

A row is kept only when its policy revision is the store's (otherwise the
lookup is refused for the compile: ``lookup_policy_changed``), its
environment digest is that of the environment the compile uses, no
tombstone newer than its render names the claim or anything it cites, the
claim head is still at its revision, status and freshness and is live, some
support event still holds sufficient evidence, every event it quotes is in
the payload state it was rendered from, and every version condition with a
known current value has a precomputed result for exactly that value. Bound
tasks are re-read live. Survivors go through the same
:func:`recalith.fast.context.decide`, budget and fresh final fence as view
candidates. A stale row is never served as current.
"""

from __future__ import annotations

import json
import math

from recalith.fast import context as fc
from recalith.fast.wire import digest_of

QUERY_TERMS = 32
TERMS = 8
POSTINGS = 64
DF_CAP = 1024
ROWS = 16
MIN_REMAINING = 0.060
PURPOSES = frozenset({"prompt"})


def environment_digest(environment) -> str:
    """The digest a row records for the workspace environment it was rendered with (both sides compute it)."""
    return digest_of(["lookup_environment", sorted([k, v] for k, v in (environment or {}).items())])


def term_weight(df: int) -> float:
    return 1.0 + math.log((DF_CAP + 1) / max(1, df))


def select(conn, workspace_id: str, text: str, *, exclude=frozenset()) -> list:
    """At most :data:`ROWS` claim IDs for ``text``: the rarest present terms' strongest postings, by summed weight."""
    present = []
    for position, term in enumerate(fc.terms(text)[:QUERY_TERMS]):
        df = conn.execute("SELECT COUNT(*) FROM (SELECT 1 FROM lookup_postings WHERE workspace_id = ? AND term = ? LIMIT ?)", (workspace_id, term, DF_CAP + 1)).fetchone()[0]
        if df:
            present.append((df, position, term))
    present.sort()
    scores: dict = {}
    for df, _position, term in present[:TERMS]:
        weight = term_weight(df)
        rows = conn.execute("SELECT claim_id, base FROM lookup_postings WHERE workspace_id = ? AND term = ? ORDER BY base DESC, claim_id LIMIT ?", (workspace_id, term, POSTINGS)).fetchall()
        for claim_id, base in rows:
            if claim_id in exclude:
                continue
            slot = scores.setdefault(claim_id, [0.0, base])
            slot[0] += weight
    ranked = sorted(scores.items(), key=lambda kv: (-round(kv[1][0], 9), -kv[1][1], kv[0]))
    return [claim_id for claim_id, _score in ranked[:ROWS]]


def _marks(n: int) -> str:
    return ",".join("?" for _ in range(n))


def _tombstoned_after(conn, ids) -> dict:
    """Target ID → tombstone epoch for the given IDs (``tombstone_targets``; bounded by the IDs)."""
    ids = sorted(set(ids))
    if not ids:
        return {}
    return dict(conn.execute(f"SELECT target_id, epoch FROM tombstone_targets WHERE target_id IN ({_marks(len(ids))})", ids).fetchall())  # noqa: S608


def _versions_exact(cand: dict, environment: dict) -> bool:
    """Every version condition with a known current value carries the worker's result for exactly that value."""
    pre = cand.get("precomputed") or {}
    for i, c in enumerate(cand.get("conditions") or []):
        if c["kind"] != "version_range" or environment.get(c["key"]) is None:
            continue
        result = pre.get(str(i))
        if not result or result.get("value_digest") != fc.value_digest(c["key"], environment[c["key"]]):
            return False
    return True


def _live(conn, cand: dict, row: dict, tombs: dict, environment: dict) -> bool:
    ref = cand["ref"]
    if ref["kind"] != "claim" or cand.get("members"):
        return False
    for target in [ref["id"], *row["cited"]]:
        if tombs.get(target, -1) > row["tombstone_epoch"]:
            return False
    head = conn.execute("SELECT revision, status, freshness FROM claim_heads WHERE claim_id = ?", (ref["id"],)).fetchone()
    if head is None or head[0] != ref["revision"] or head[1] != cand["status"] or head[2] != cand["freshness"] or head[1] not in fc.LIVE:
        return False
    support = list(cand.get("support_events") or ())
    quoted = row["quoted"]
    events = sorted(set(support) | set(quoted))
    states = dict(conn.execute(f"SELECT event_id, payload_state FROM events WHERE event_id IN ({_marks(len(events))})", events).fetchall()) if events else {}  # noqa: S608
    if support and not {states.get(e) for e in support} & fc.SUFFICIENT_EVIDENCE:
        return False
    if any(states.get(e) != state for e, state in quoted.items()):
        return False
    return _versions_exact(cand, environment)


def _bound_tasks(conn, events: list) -> list:
    if not events:
        return []
    return sorted({r[0] for r in conn.execute(f"SELECT task_id FROM task_binding_heads WHERE event_id IN ({_marks(len(events))})", sorted(set(events))).fetchall()})  # noqa: S608


def candidates(conn, workspace_id: str, text: str, meta: dict, environment: dict, *, base_environment, exclude=frozenset()) -> tuple:
    """``(candidates, reasons)``: live-filtered lookup candidates for one prompt compile (bounded; see the module docstring)."""
    ids = select(conn, workspace_id, text, exclude=exclude)
    if not ids:
        return [], []
    rows = conn.execute(
        f"SELECT claim_id, claim_revision, environment_digest, policy_revision, tombstone_epoch, cited_ids, quoted_states, body FROM lookup_candidates "  # noqa: S608
        f"WHERE workspace_id = ? AND claim_id IN ({_marks(len(ids))}) AND body IS NOT NULL",
        (workspace_id, *ids),
    ).fetchall()
    if any(r[3] != meta["policy_revision"] for r in rows):
        return [], ["lookup_policy_changed"]
    digest = environment_digest(base_environment)
    parsed = []
    for claim_id, revision, env_digest, _policy, tomb_epoch, cited, quoted, body in rows:
        if env_digest != digest:
            continue
        try:
            row = {"claim_id": claim_id, "revision": revision, "tombstone_epoch": tomb_epoch, "cited": json.loads(cited), "quoted": json.loads(quoted)}
            cand = json.loads(body)
        except ValueError:
            continue
        if cand.get("ref", {}).get("id") != claim_id or cand["ref"].get("revision") != revision:
            continue
        parsed.append((row, cand))
    tombs = _tombstoned_after(conn, [x for row, _c in parsed for x in [row["claim_id"], *row["cited"]]])
    order = {claim_id: i for i, claim_id in enumerate(ids)}
    out = []
    for row, cand in sorted(parsed, key=lambda rc: order[rc[0]["claim_id"]]):
        if not _live(conn, cand, row, tombs, environment):
            continue
        cand["task_ids"] = sorted(set((cand.get("scope") or {}).get("task_ids") or ()) | set(_bound_tasks(conn, list(cand.get("support_events") or ()))))
        cand["lookup"] = True
        out.append(cand)
    return out, []
