"""Applicability: tri-state scope and condition evaluation (SYSTEM_SPEC §7.4, §8.1, §13; DATA_CONTRACTS §1.1, §5, §9).

Every predicate returns exactly ``"true"``, ``"false"`` or ``"unknown"``.
Conditions combine with AND (Kleene: any ``false`` is false, otherwise any
``unknown`` is unknown), including explicit exclusions, which negate a known
result and leave ``unknown`` unknown. Nothing here executes, globs or matches a
regular expression from a condition value:

* ``path`` matches the query action's portable paths exactly, or as a
  directory prefix when the value ends in ``/``. A name that differs only by
  case or Unicode normalization (Windows and macOS file systems may treat it as
  the same file) is ``unknown``, never a guessed match or mismatch; paths are
  never lowercased to compare them.
* ``environment_equals`` compares one registered nonsecret key exactly; a key
  the query does not carry is unknown. Query environments come from
  :func:`recalith.capture.provenance.environment_values`, which omits missing,
  stale, unbound and conflicting runtime provenance, so those evaluate
  unknown.
* ``version_range`` is an inclusive PEP 440 range through the pinned
  ``packaging`` dependency: ``value`` is the lower bound and ``upper`` the
  upper bound (absent: unbounded above). A version outside the PEP 440 grammar
  is unknown unless the condition specifies exact comparison (``upper ==
  value``), which then compares the exact strings. There is no lexicographic
  fallback.
* ``action_kind`` and ``tool`` use the adapter-assigned action descriptor; an
  unparsed or conservative action has no known kind.
* ``branch_ref`` is an explicit branch predicate against the query's current
  branch; ``Scope.branch_refs`` are recall annotations and never consulted.

Scope eligibility (:func:`scope_applicability`) precedes any similarity: a
record outside the query's workspace, task, paths or environment is
``false`` however closely its text matches. Advice (:func:`advice_for`) can be
a caution only for applicability ``true`` and current freshness; ``unknown``
is at most labeled context. The failure-lesson gate
(:func:`dependency_applicability`) treats empty or unfingerprinted
dependencies as unknown and a changed fingerprint as ``false`` on any branch.
"""

from __future__ import annotations

import unicodedata
from typing import Iterable, Mapping, Sequence

from packaging.version import InvalidVersion, Version

from recalith.contracts.common import ENVIRONMENT_GRAMMAR, Condition, DependencyRef, Scope
from recalith.contracts.context import ContextQuery

TRUE, FALSE, UNKNOWN = "true", "false", "unknown"


def all_of(results: Iterable[str]) -> str:
    """Kleene AND over tri-state results."""
    out = TRUE
    for result in results:
        if result == FALSE:
            return FALSE
        if result != TRUE:
            out = UNKNOWN
    return out


def any_of(results: Iterable[str]) -> str:
    """Kleene OR over tri-state results."""
    out = FALSE
    for result in results:
        if result == TRUE:
            return TRUE
        if result != FALSE:
            out = UNKNOWN
    return out


def _negate(result: str) -> str:
    return {TRUE: FALSE, FALSE: TRUE}.get(result, UNKNOWN)


def _fold(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def path_matches(pattern: str, path: str) -> str:
    """Exact path, or directory prefix for a pattern ending in ``/``; near-misses by case/normalization are unknown."""
    if not pattern or pattern == "." or not path or path == ".":
        return UNKNOWN
    if pattern.endswith("/"):
        if path.startswith(pattern):
            return TRUE
        return UNKNOWN if _fold(path).startswith(_fold(pattern)) else FALSE
    if path == pattern:
        return TRUE
    return UNKNOWN if _fold(path) == _fold(pattern) else FALSE


def _query_paths(query: ContextQuery) -> list[str] | None:
    action = query.action
    if action is None or action.parse_status != "exact" or not action.paths:
        return None
    return list(action.paths)


def _version(text: str) -> Version | None:
    try:
        return Version(text)
    except InvalidVersion:
        return None


def version_in_range(current: str, lower: str, upper: str | None) -> str:
    exact = upper is not None and upper == lower
    have, low = _version(current), _version(lower)
    high = _version(upper) if upper is not None else None
    if have is None or low is None or (upper is not None and high is None):
        if exact:
            return TRUE if current == lower else FALSE  # the condition specified exact comparison
        return UNKNOWN
    if high is not None and high < low:
        return UNKNOWN  # an inverted range states nothing
    if have < low:
        return FALSE
    if high is not None and have > high:
        return FALSE
    return TRUE


def evaluate_condition(condition: Condition, query: ContextQuery) -> str:
    result = _evaluate(condition, query)
    return _negate(result) if condition.exclude else result


def _evaluate(condition: Condition, query: ContextQuery) -> str:
    kind = condition.kind
    if kind == "path":
        paths = _query_paths(query)
        if paths is None:
            return UNKNOWN
        return any_of(path_matches(condition.value, p) for p in paths)
    if kind == "environment_equals":
        if condition.key not in ENVIRONMENT_GRAMMAR:
            return UNKNOWN
        current = query.environment.get(condition.key)
        if current is None or current == "unknown" or condition.value == "unknown":
            return UNKNOWN
        return TRUE if current == condition.value else FALSE
    if kind == "version_range":
        current = query.environment.get(condition.key)
        if current is None:
            return UNKNOWN
        return version_in_range(current, condition.value, condition.upper)
    if kind == "action_kind":
        action = query.action
        if action is None or action.parse_status != "exact" or action.action_kind in (None, "unknown") or condition.value == "unknown":
            return UNKNOWN
        return TRUE if action.action_kind == condition.value else FALSE
    if kind == "tool":
        if query.action is None or not condition.value:
            return UNKNOWN
        return TRUE if query.action.tool == condition.value else FALSE
    if kind == "branch_ref":
        if query.branch_ref is None or not condition.value:
            return UNKNOWN
        return TRUE if query.branch_ref == condition.value else FALSE
    return UNKNOWN


def evaluate_conditions(conditions: Sequence[Condition], query: ContextQuery) -> str:
    """DATA_CONTRACTS §11: exactly ``"true"``, ``"false"`` or ``"unknown"``; conditions combine with AND."""
    return all_of(evaluate_condition(c, query) for c in conditions)


def scope_applicability(scope: Scope, query: ContextQuery) -> str:
    """Scope eligibility: dimensions combine with AND, values within one with OR; empty is unrestricted."""
    results = []
    if scope.workspace_ids:
        results.append(TRUE if query.workspace_id in scope.workspace_ids else FALSE)
    if scope.task_ids:
        results.append(UNKNOWN if query.task_id is None else TRUE if query.task_id in scope.task_ids else FALSE)
    if scope.paths:
        paths = _query_paths(query)
        results.append(UNKNOWN if paths is None else any_of(path_matches(pattern, p) for pattern in scope.paths for p in paths))
    for key, value in sorted(scope.environment.items()):
        current = query.environment.get(key)
        results.append(UNKNOWN if current is None or current == "unknown" or value == "unknown" else TRUE if current == value else FALSE)
    return all_of(results)


def applicability(scope: Scope, conditions: Sequence[Condition], query: ContextQuery) -> str:
    """Scope first, then conditions; ``false`` excludes the record regardless of similarity."""
    return all_of([scope_applicability(scope, query), evaluate_conditions(conditions, query)])


def in_scope(candidates: Iterable[tuple[Scope, Sequence[Condition]]], query: ContextQuery) -> list[int]:
    """Indices of candidates that remain eligible; similarity ranking applies only to these."""
    return [i for i, (scope, conditions) in enumerate(candidates) if applicability(scope, conditions, query) != FALSE]


def dependency_applicability(dependencies: Sequence[DependencyRef], current: Mapping[str, str | None]) -> str:
    """The failure-lesson caution gate over declared dependency fingerprints (SYSTEM_SPEC §7.4).

    ``current`` maps ``"<kind>:<key>"`` to the consulted current fingerprint
    (None when unreadable or unavailable). Empty dependencies are unknown, not
    vacuously true; a null or missing fingerprint is unknown; any changed
    fingerprint is ``false`` (caution suppressed pending revalidation) on any
    branch; only complete matching fingerprints are ``true``, across branches.
    """
    if not dependencies:
        return UNKNOWN
    results = []
    for dep in dependencies:
        now = current.get(f"{dep.kind}:{dep.key}")
        if dep.fingerprint is None or now is None:
            results.append(UNKNOWN)
        else:
            results.append(TRUE if now == dep.fingerprint else FALSE)
    return all_of(results)


def advice_for(applicability_result: str, freshness: str, *, caution_candidate: bool) -> str | None:
    """``caution`` only for true applicability and current freshness; ``false`` is excluded (None)."""
    if applicability_result == FALSE:
        return None
    if caution_candidate and applicability_result == TRUE and freshness == "current":
        return "caution"
    return "context"
