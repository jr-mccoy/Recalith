"""Context composition primitives shared by the worker and the stdlib hook compiler (SYSTEM_SPEC §5.1.1, §7.4, §8; DATA_CONTRACTS §9).

This module is standard library only and imports nothing outside
``recalith.fast``. It holds everything the two compilers must agree on byte
for byte, so a packet compiled by the worker/service (``recalith.retrieval``)
and one compiled by the hook from a pre-serialized view are the same
function of the same inputs:

* :func:`terms`, the deterministic lexical tokenizer behind the token index,
  the FTS5 candidate query and the hook's bounded term overlap;
* :func:`render_item`/:func:`render_packet`, the exact text a packet is
  emitted as, and :func:`estimate_tokens`, the estimate
  ``ceil(UTF-8 bytes / 3)`` (an estimate, never provider usage);
* the stdlib twin of :mod:`recalith.core.conditions` (tri-state scope and
  conditions; PEP 440 ranges are *not* reimplemented: a version result is
  reused only while the exact consulted value matches the precomputed one,
  otherwise it is unknown) and of the advice gate
  :func:`recalith.controller.revalidate.guidance`;
* the bounded live dependency check (at most 16 local files and 1 MiB within
  a 50 ms sub-budget and the caller's deadline; never a command);
* :func:`assemble`, the budgeted packet assembly with the one shared
  pre-action substitution allowance.

:func:`hook_compile_context` (DATA_CONTRACTS §2.3) is the hook-side compiler:
it reads the worker's pre-serialized views through read-only snapshots
(:mod:`recalith.fast.cache`), falls back to at most 32 live-filtered rows, and
validates the result at a fresh final fence (:mod:`recalith.fast.fence`). It
emits nothing: session reservation, stdout emission and receipts are the
delivery branch of ``handle_hook`` (Task 12b).
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import stat
import time
import unicodedata

from recalith.fast.wire import ENVIRONMENT_GRAMMAR, digest_of, utc_now, utf8_len

# --------------------------------------------------------------------------
# Budgets (SYSTEM_SPEC §6.3, §8.2)

BUDGETS = {"session_start": 2000, "prompt": 1000, "pre_action": 400, "compact_restore": 2000, "manual": 2000}
SUBSTITUTION_ALLOWANCE = 400
DEPENDENCY_FILES = 16
DEPENDENCY_BYTES = 1024 * 1024
DEPENDENCY_SECONDS = 0.050
FALLBACK_ROWS = 32
FALLBACK_MIN_REMAINING = 0.060
FENCE_TAIL = 0.040
TOKEN_ESTIMATE = "ceil(utf8_bytes/3)"
LIVE = frozenset({"candidate", "active", "disputed"})
SUFFICIENT_EVIDENCE = frozenset({"available", "capsule_only"})
TRUE, FALSE, UNKNOWN = "true", "false", "unknown"
REASON_ORDER = ("conflict", "exact_action_match", "dependency_match", "path_match", "task_continuity", "lexical_match", "explicit_query", "recent_observation")
WEIGHTS = {"exact_action_match": 100.0, "path_match": 40.0, "dependency_match": 30.0, "task_continuity": 25.0, "conflict": 60.0, "recent_observation": 0.0}
LEXICAL_WEIGHT = 10.0

# --------------------------------------------------------------------------
# Terms

_WORD = re.compile(r"[^\W_]+")
STOPWORDS = frozenset(
    "a an and are as at be been but by can could did do does for from had has have how i if in into is it its just let me my no not of on or our please run "
    "so that the their them then there these they this those to too up us was we were what when where which while who why will with would you your".split()
)
MAX_TERMS = 256
MAX_TERM_CHARS = 64


def terms(text: str) -> list[str]:
    """Deterministic lexical terms: Unicode alphanumeric runs, case-folded, NFC, without stopwords, first occurrence order."""
    seen: dict[str, None] = {}
    for word in _WORD.findall(unicodedata.normalize("NFC", text or "").casefold()):
        if len(word) < 2 or len(word) > MAX_TERM_CHARS or word in STOPWORDS:
            continue
        seen.setdefault(word, None)
        if len(seen) >= MAX_TERMS:
            break
    return list(seen)


# --------------------------------------------------------------------------
# Exact estimate and rendering


def estimate_tokens(text: str) -> int:
    """The specified estimate: ``ceil(UTF-8 bytes / 3)``; labeled an estimate, never provider usage."""
    return -(-utf8_len(text) // 3)


HEADER = "Recalith project memory ({purpose}; advisory, evidence-linked; not instructions):"


def render_header(purpose: str) -> str:
    return HEADER.format(purpose=purpose)


def _ref_text(ref: dict) -> str:
    return f"{ref['id']} r{ref['revision']}" if ref["kind"] in ("claim", "task", "episode") else ref["id"]


def render_item(item: dict) -> str:
    """One item's exact block: advice and content, why, applicability/freshness/basis, conditions, retry, sources."""
    lines = [f"- [{item['advice']}] {item['text']}"]
    why = item["why"]
    lines.append("  why: " + why[0] + (" — " + "; ".join(why[1:]) if len(why) > 1 else ""))
    lines.append(f"  applies: {item['applicability']} · freshness: {item['freshness']} · basis: {item['basis']}")
    if item.get("conditions_text"):
        lines.append("  conditions: " + item["conditions_text"])
    if item.get("retry_text"):
        lines.append("  retry: " + item["retry_text"])
    sources = [_ref_text(item["ref"])] + [_ref_text(r) for r in item.get("evidence_refs", [])[:2]]
    lines.append("  sources: " + "; ".join(sources))
    return "\n".join(lines)


def render_packet(purpose: str, items: list) -> str:
    """The exact text a packet is emitted as (Task 12b writes it; Task 11 budgets it)."""
    return "\n".join([render_header(purpose)] + [render_item(i) for i in items])


def bounded(text: str, limit: int) -> str:
    """At most ``limit`` code points, cut with an explicit omission marker (never silently)."""
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 3)].rstrip() + " […]"


# --------------------------------------------------------------------------
# Applicability twin (core.conditions without packaging)


def all_of(results) -> str:
    out = TRUE
    for r in results:
        if r == FALSE:
            return FALSE
        if r != TRUE:
            out = UNKNOWN
    return out


def any_of(results) -> str:
    out = FALSE
    for r in results:
        if r == TRUE:
            return TRUE
        if r != FALSE:
            out = UNKNOWN
    return out


def _fold(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def path_matches(pattern: str, path: str) -> str:
    if not pattern or pattern == "." or not path or path == ".":
        return UNKNOWN
    if pattern.endswith("/"):
        if path.startswith(pattern):
            return TRUE
        return UNKNOWN if _fold(path).startswith(_fold(pattern)) else FALSE
    if path == pattern:
        return TRUE
    return UNKNOWN if _fold(path) == _fold(pattern) else FALSE


def _query_paths(query: dict):
    action = query.get("action")
    if not action or action.get("parse_status") != "exact" or not action.get("paths"):
        return None
    return list(action["paths"])


def value_digest(key: str, value: str) -> str:
    return digest_of(["environment", key, value])


def evaluate_condition(condition: dict, query: dict, environment: dict, precomputed=None) -> str:
    result = _evaluate(condition, query, environment, precomputed)
    if condition.get("exclude"):
        return {TRUE: FALSE, FALSE: TRUE}.get(result, UNKNOWN)
    return result


def _evaluate(condition: dict, query: dict, environment: dict, precomputed) -> str:
    kind, value = condition["kind"], condition["value"]
    if kind == "path":
        paths = _query_paths(query)
        return UNKNOWN if paths is None else any_of(path_matches(value, p) for p in paths)
    if kind == "environment_equals":
        if condition["key"] not in ENVIRONMENT_GRAMMAR:
            return UNKNOWN
        current = environment.get(condition["key"])
        if current is None or current == "unknown" or value == "unknown":
            return UNKNOWN
        return TRUE if current == value else FALSE
    if kind == "version_range":
        # PEP 440 stays in the worker: reuse its result only for the exact value it consulted.
        current = environment.get(condition["key"])
        if current is None or not precomputed:
            return UNKNOWN
        if precomputed.get("value_digest") != value_digest(condition["key"], current):
            return UNKNOWN
        return precomputed.get("result", UNKNOWN)
    if kind == "action_kind":
        action = query.get("action")
        if not action or action.get("parse_status") != "exact" or action.get("action_kind") in (None, "unknown") or value == "unknown":
            return UNKNOWN
        return TRUE if action["action_kind"] == value else FALSE
    if kind == "tool":
        action = query.get("action")
        if not action or not value:
            return UNKNOWN
        return TRUE if action.get("tool") == value else FALSE
    if kind == "branch_ref":
        branch = query.get("branch_ref")
        if branch is None or not value:
            return UNKNOWN
        return TRUE if branch == value else FALSE
    return UNKNOWN


def evaluate_conditions(conditions: list, query: dict, environment: dict, precomputed=None) -> str:
    pre = precomputed or {}
    return all_of(evaluate_condition(c, query, environment, pre.get(str(i))) for i, c in enumerate(conditions))


def scope_applicability(scope: dict, query: dict, environment: dict) -> str:
    results = []
    if scope.get("workspace_ids"):
        results.append(TRUE if query["workspace_id"] in scope["workspace_ids"] else FALSE)
    if scope.get("task_ids"):
        task = query.get("task_id")
        results.append(UNKNOWN if task is None else TRUE if task in scope["task_ids"] else FALSE)
    if scope.get("paths"):
        paths = _query_paths(query)
        results.append(UNKNOWN if paths is None else any_of(path_matches(pattern, p) for pattern in scope["paths"] for p in paths))
    for key, value in sorted((scope.get("environment") or {}).items()):
        current = environment.get(key)
        results.append(UNKNOWN if current is None or current == "unknown" or value == "unknown" else TRUE if current == value else FALSE)
    return all_of(results)


def applicability(scope: dict, conditions: list, query: dict, environment: dict, precomputed=None) -> str:
    return all_of([scope_applicability(scope, query, environment), evaluate_conditions(conditions, query, environment, precomputed)])


def dependency_applicability(dependencies: list, current: dict) -> str:
    if not dependencies:
        return UNKNOWN
    results = []
    for dep in dependencies:
        now = current.get(f"{dep['kind']}:{dep['key']}")
        results.append(UNKNOWN if dep.get("fingerprint") is None or now is None else TRUE if now == dep["fingerprint"] else FALSE)
    return all_of(results)


def guidance(item: dict, app: str, current: dict) -> tuple:
    """Stdlib twin of ``revalidate.guidance``: (advice or None, dependency result, reasons)."""
    reasons = []
    status, freshness = item["status"], item["freshness"]
    if status not in LIVE:
        return None, None, ("retired",)
    dependency = None
    if item.get("claim_kind") == "failure_lesson":
        dependency = dependency_applicability(item.get("dependencies") or [], current)
        if dependency != TRUE:
            reasons.append(f"dependency_{dependency}")
    if freshness != "current":
        reasons.append(f"freshness_{freshness}")
    if status == "disputed":
        return ("conflict" if app != FALSE else None), dependency, tuple(reasons + ["disputed"])
    if status == "candidate":
        return ("context" if app != FALSE else None), dependency, tuple(reasons + ["candidate"])
    if app == FALSE:
        return None, dependency, tuple(reasons)
    capable = item.get("claim_kind") == "failure_lesson" and item.get("strength") in ("supported", "corroborated") and dependency == TRUE
    return ("caution" if capable and app == TRUE and freshness == "current" else "context"), dependency, tuple(reasons)


# --------------------------------------------------------------------------
# Actions


def action_family(workspace_id: str, action) -> str | None:
    """Stdlib twin of ``capture.normalize.action_family_digest``."""
    if not action or action.get("parse_status") != "exact" or action.get("cwd_path") is None or action.get("argv") is None:
        return None
    return digest_of([workspace_id, action["cwd_path"], action["tool"], action.get("executable"), action["argv"]])


# --------------------------------------------------------------------------
# Bounded live dependency check (SYSTEM_SPEC §7.4)


def _safe_relative(rel: str) -> bool:
    if not rel or rel.startswith("/") or "\\" in rel or "\x00" in rel or ":" in rel.split("/")[0]:
        return False
    return ".." not in rel.split("/")


def _contained(target: str, root: str) -> bool:
    try:
        return os.path.commonpath([target, root]) == root
    except ValueError:
        return False


def file_fingerprint(workspace_root: str, rel: str, *, limit: int):
    """(digest or None, bytes read): the same value as ``admission.fingerprint_file`` within ``limit`` bytes."""
    if not _safe_relative(rel):
        return None, 0
    root = os.path.realpath(workspace_root)
    target = os.path.realpath(os.path.join(root, *rel.split("/")))
    if not _contained(target, root):
        return None, 0
    try:
        os.lstat(target)
    except FileNotFoundError:
        return digest_of({"absent": rel}), 0
    except OSError:
        return None, 0
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(target, flags)
    except OSError:
        return None, 0
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            return None, 0
        with os.fdopen(fd, "rb", closefd=False) as fh:
            data = fh.read(limit + 1)
    except OSError:
        return None, 0
    finally:
        os.close(fd)
    if len(data) > limit:
        return None, len(data)
    return hashlib.sha256(data).hexdigest(), len(data)


class DependencyBudget:
    """One bounded check per compile: 16 files, 1 MiB and 50 ms within the shared deadline."""

    def __init__(self, deadline: float | None = None, *, files: int = DEPENDENCY_FILES, size: int = DEPENDENCY_BYTES, seconds: float = DEPENDENCY_SECONDS) -> None:
        now = time.monotonic()
        stop = now + seconds
        self.stop = stop if deadline is None else min(stop, deadline - FENCE_TAIL)
        self.files = files
        self.bytes = size
        self.cache: dict = {}
        self.skipped = False
        self.exceeded = False

    def file(self, workspace_root: str, rel: str):
        key = "file:" + rel
        if key in self.cache:
            return self.cache[key]
        if time.monotonic() >= self.stop:
            self.skipped = True
            return None
        if self.files <= 0 or self.bytes <= 0:
            self.exceeded = True
            return None
        self.files -= 1
        value, used = file_fingerprint(workspace_root, rel, limit=self.bytes)
        self.bytes -= used
        if value is None and used:
            self.exceeded = True
        self.cache[key] = value
        return value


def current_dependencies(dependencies: list, *, workspace_root: str, environment: dict, budget: DependencyBudget, claim_values=None) -> dict:
    """Current values for the dependency gate: live file bytes (bounded), the environment, claim content; config unknown."""
    out = {}
    for dep in dependencies:
        key = f"{dep['kind']}:{dep['key']}"
        if dep["kind"] == "file":
            out[key] = budget.file(workspace_root, dep["key"])
        elif dep["kind"] == "environment":
            value = environment.get(dep["key"])
            out[key] = value_digest(dep["key"], value) if value is not None else None
        elif dep["kind"] == "claim":
            out[key] = (claim_values or {}).get(key)
        else:
            out[key] = None
    return out


# --------------------------------------------------------------------------
# Candidate decisions and ranking (both compilers)

ITEM_FIELDS = ("ref", "text", "advice", "basis", "scope", "applicability", "freshness", "why", "evidence_refs", "conditions_text", "retry_text")


def relevance(cand: dict, query: dict, *, query_terms, family, idf=None) -> dict:
    """Query-dependent match reasons and score for one candidate (pure)."""
    reasons: dict = {}
    if family is not None and cand.get("family") == family:
        reasons["exact_action_match"] = "same action family (workspace, directory, tool, argv)"
    paths = _query_paths(query) or []
    if paths:
        dep_paths = [d["key"] for d in cand.get("dependencies") or [] if d["kind"] == "file"]
        if any(path_matches(d, p) == TRUE for d in dep_paths for p in paths):
            reasons["dependency_match"] = "the action touches a declared dependency"
        scoped = list((cand.get("scope") or {}).get("paths") or []) + [c["value"] for c in cand.get("conditions") or [] if c["kind"] == "path" and not c.get("exclude")]
        if any(path_matches(s, p) == TRUE for s in scoped for p in paths):
            reasons["path_match"] = "the action's paths are in scope"
    task = query.get("task_id")
    if task is not None and task in (cand.get("task_ids") or ()):
        reasons["task_continuity"] = "bound to the current task"
    matched = [t for t in cand.get("terms") or () if t in query_terms]
    score = cand.get("base", 0.0)
    for code in reasons:
        score += WEIGHTS.get(code, 0.0)
    if matched:
        weight = sum((idf or {}).get(t, 1.0) for t in matched)
        score += LEXICAL_WEIGHT * weight / math.sqrt(max(1, cand.get("term_count") or len(cand.get("terms") or ()) or 1))
        if query.get("purpose") == "manual":
            reasons["explicit_query"] = f"matches {len(matched)} query term(s)"
        else:
            reasons["lexical_match"] = "matches " + ", ".join(matched[:4])
    if cand.get("linked"):
        reasons.setdefault("dependency_match", f"linked by a claim dependency to {cand['linked']}")
        score += WEIGHTS["dependency_match"]
    for code, text in (cand.get("member_reasons") or {}).items():
        reasons.setdefault(code, text)
    if cand.get("members") and query.get("purpose") in ("session_start", "compact_restore"):
        reasons.setdefault("conflict", "an open question about this workspace's user decisions")
    if cand.get("group") == "conflict":
        score += WEIGHTS["conflict"]
    if cand.get("group") == "observation":
        score += WEIGHTS["recent_observation"]
    return {"reasons": reasons, "score": round(score, 6), "matched": matched}


def relevant(cand: dict, match: dict) -> bool:
    """Direct relevance (§8.2 table: all rows require it); tentative content only for the bound task or an exact action."""
    reasons = match["reasons"]
    if cand.get("tentative"):
        return "task_continuity" in reasons or "exact_action_match" in reasons
    if cand.get("group") in ("task", "episode", "observation"):
        return "task_continuity" in reasons
    return bool(reasons)


def finish_item(cand: dict, advice: str, app: str, match: dict, query: dict, extra_reasons=()) -> dict:
    """The ContextItem primitive: why[0] is the strongest registered reason code."""
    reasons = match["reasons"]
    if cand.get("tentative"):
        code, explanation = "tentative_context", "unreviewed candidate; " + next(iter(reasons.values()), "relevant")
    elif advice == "conflict":
        code = "conflict"
        explanation = "unresolved; " + next(iter(reasons.values()), "disputed")
    elif cand.get("group") == "observation":
        code, explanation = "recent_observation", "captured in this task; an observation, not a durable lesson"
    else:
        code = next((c for c in REASON_ORDER if c in reasons), "lexical_match")
        explanation = reasons.get(code, "")
    if query.get("purpose") == "compact_restore" and advice == "context" and code not in ("tentative_context",):
        explanation, code = f"{code}: {explanation}", "compaction_restore"
    why = [code] + [x for x in [explanation, *extra_reasons] if x][:6]
    item = {
        "ref": cand["ref"], "text": cand["text"], "advice": advice, "basis": cand["basis"], "scope": cand.get("scope") or {},
        "applicability": app, "freshness": cand["freshness"], "why": [w[:512] for w in why], "evidence_refs": cand.get("evidence_refs") or [],
        "conditions_text": cand.get("conditions_text"), "retry_text": cand.get("retry_text") if advice == "caution" or cand.get("claim_kind") == "failure_lesson" else None,
    }
    return item


def order(entries: list) -> list:
    """Deterministic ranking: score, then group priority, then record ID; repeated subjects lose half their score once."""
    entries = sorted(entries, key=lambda e: (-e["score"], e["rank_group"], e["item"]["ref"]["id"]))
    seen: set = set()
    for e in entries:
        subject = e.get("subject")
        if subject and subject in seen:
            e["score"] = round(e["score"] / 2, 6)
        elif subject:
            seen.add(subject)
    return sorted(entries, key=lambda e: (-e["score"], e["rank_group"], e["item"]["ref"]["id"]))


# --------------------------------------------------------------------------
# Budgeted assembly


def packet_limit(purpose: str, max_estimated_tokens) -> int:
    base = BUDGETS[purpose]
    return base if max_estimated_tokens is None else min(base, max_estimated_tokens)


def assemble(purpose: str, items: list, *, max_estimated_tokens=None, substitute_pre_action: bool = False) -> dict:
    """Fit ranked items into the exact budget; returns items, omitted count, estimate and substitution portion.

    The estimate is computed on the exact rendered text. A prompt packet that
    substitutes for unavailable pre-action injection gets one shared extra
    allowance of at most 400 for its cautions (1,400 total), only when a
    caution is actually included; a caller's lower maximum stays binding.
    """
    base = packet_limit(purpose, max_estimated_tokens)
    substituting = substitute_pre_action and purpose == "prompt" and any(i["advice"] == "caution" for i in items)
    total_cap = base + SUBSTITUTION_ALLOWANCE if substituting else base
    if max_estimated_tokens is not None:
        total_cap = min(total_cap, max_estimated_tokens)
    header = utf8_len(render_header(purpose))
    ordinary_bytes, caution_bytes = header, 0
    chosen, omitted = [], 0
    for item in items:
        size = 1 + utf8_len(render_item(item))  # newline + block
        if substituting and item["advice"] == "caution" and -(-(caution_bytes + size) // 3) <= SUBSTITUTION_ALLOWANCE and -(-(ordinary_bytes + caution_bytes + size) // 3) <= total_cap:
            caution_bytes += size
            chosen.append(item)
        elif -(-(ordinary_bytes + size) // 3) <= base and -(-(ordinary_bytes + caution_bytes + size) // 3) <= total_cap:
            ordinary_bytes += size
            chosen.append(item)
        else:
            omitted += 1
    if not chosen:
        return {"items": [], "omitted_count": omitted, "estimated_tokens": 0, "pre_action_substitution_tokens": 0}
    estimated = estimate_tokens(render_packet(purpose, chosen))
    substitution = min(SUBSTITUTION_ALLOWANCE, -(-caution_bytes // 3)) if caution_bytes else 0
    return {"items": chosen, "omitted_count": omitted, "estimated_tokens": estimated, "pre_action_substitution_tokens": min(substitution, estimated)}


def empty_packet(ctx: dict, purpose: str, meta, reasons) -> dict:
    return packet(ctx, purpose, meta, {"items": [], "omitted_count": 0, "estimated_tokens": 0, "pre_action_substitution_tokens": 0}, reasons)


def packet(ctx: dict, purpose: str, meta, assembled: dict, reasons, *, generated_at: str | None = None) -> dict:
    """The ``ContextPacket`` primitive (packet_schema 1)."""
    meta = meta or {"store_revision": 0, "guidance_epoch": 0, "policy_revision": ctx.get("policy_revision", 1), "tombstone_epoch": 0}
    return {
        "packet_schema": 1, "project_id": ctx["project_id"], "installation_id": ctx["installation_id"],
        "store_revision": meta["store_revision"], "guidance_epoch": meta["guidance_epoch"], "policy_revision": meta["policy_revision"], "tombstone_epoch": meta["tombstone_epoch"],
        "generated_at": generated_at or utc_now(), "purpose": purpose, "items": assembled["items"], "omitted_count": assembled["omitted_count"],
        "estimated_tokens": assembled["estimated_tokens"], "pre_action_substitution_tokens": assembled["pre_action_substitution_tokens"],
        "degraded_reasons": sorted(set(reasons)),
    }


def decide(cand: dict, query: dict, environment: dict, *, family, query_terms, workspace_root: str, budget: DependencyBudget, claim_values=None, idf=None):
    """One candidate under one query: (entry or None). Mirrors the service path; used by the hook compiler."""
    if cand.get("evidence") not in (None, *SUFFICIENT_EVIDENCE):
        return None  # expired/redacted inadequate support never enters automatic context
    app = applicability(cand.get("scope") or {}, cand.get("conditions") or [], query, environment, cand.get("precomputed"))
    if app == FALSE:
        return None
    match = relevance(cand, query, query_terms=query_terms, family=family, idf=idf)
    if not relevant(cand, match):
        return None
    if cand.get("ref", {}).get("kind") == "claim" and not cand.get("members"):  # a claim (disputed ones too); questions carry members
        current = {}
        if cand.get("claim_kind") == "failure_lesson" and cand.get("status") == "active" and cand.get("freshness") == "current" and app == TRUE:
            current = current_dependencies(cand.get("dependencies") or [], workspace_root=workspace_root, environment=environment, budget=budget, claim_values=claim_values)
        advice, dependency, why_extra = guidance(cand, app, current)
        if advice is None:
            return None
        if advice == "caution" and "exact_action_match" not in match["reasons"] and not _action_conditions_true(cand, query, environment):
            advice = "context"  # caution needs an action-specific match
    else:
        advice, why_extra = cand.get("advice_ceiling", "context"), ()
    extra = [r for r in why_extra if r not in ("candidate",)]
    item = finish_item(cand, advice, app, match, query, extra)
    return {"item": item, "score": match["score"], "rank_group": 0 if advice in ("caution", "conflict") else 1, "subject": cand.get("subject")}


def _action_conditions_true(cand: dict, query: dict, environment: dict) -> bool:
    actionish = [c for c in cand.get("conditions") or [] if c["kind"] in ("action_kind", "tool", "path") and not c.get("exclude")]
    return bool(actionish) and all(evaluate_condition(c, query, environment) == TRUE for c in actionish)


# --------------------------------------------------------------------------
# The hook-side compiler


def hook_compile_context(ctx: dict, query: dict, *, deadline: float | None = None, substitute_pre_action: bool = False) -> dict:
    """DATA_CONTRACTS §2.3: a ``ContextPacket`` primitive from views or bounded fallback, validated at a fresh fence.

    Never writes SQLite, never waits for a lock, never calls a model; an
    unavailable snapshot or an exhausted deadline returns an empty packet with
    the degradation reason. The packet is not emitted here (Task 12b).
    """
    from recalith.fast import cache

    deadline = time.monotonic() + 0.250 if deadline is None else deadline
    return cache.compile_packet(ctx, query, deadline=deadline, substitute_pre_action=substitute_pre_action)["packet"]
