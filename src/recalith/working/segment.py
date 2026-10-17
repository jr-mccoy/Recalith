"""Deterministic task-boundary signals and the session continuity rule (SYSTEM_SPEC §3.2).

``working/segment.py`` owns binding decisions that need no model:

* **New session.** A session with no bound events starts a provisional task
  (``new_session``; ``host_reset`` when the host confirms a clear/reset).
* **Boundary candidates inside a session**, proposals only, never proof of a
  new objective: a user message starting with a configured pivot prefix
  (case-insensitive after leading whitespace; a quoted or pasted start such
  as ``>``, a quote mark or a code fence is not a pivot); five consecutive
  path-bearing actions in one cluster disjoint from the task's observed
  clusters; a user message after 30 minutes without activity. Until a model
  (or operator) confirms a candidate, later events stay provisionally with
  the current task.
* **Path clusters.** The first normalized path component, ``@root`` for root
  files; ``.recalith/`` and generated directories are excluded. The coding
  profile groups ``src``, ``test``, ``tests`` and ``docs`` into ``@code``;
  operator mappings (``segmentation.cluster_mappings``) extend it, longest
  prefix first. Ordinary source/test/documentation movement is therefore not
  a boundary.
* **Continuity.** :func:`continuity_step` counts a new session's first
  path-bearing actions; the reducer links the session to the single eligible
  task when all three lie inside that task's observed clusters (no model
  budget).

Everything here is a pure function of the events, the session's detection
state and the task's observed clusters; :func:`propose_task_boundaries`
evaluates events against the stored state without writing.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Sequence

from recalith.contracts.common import InstallationContext, derived_id, parse_utc
from recalith.contracts.config import CODE_CLUSTER_COMPONENTS, ProjectConfig, SegmentationConfig
from recalith.contracts.memory import TaskBoundaryCandidate
from recalith.working.tasks import Ev, ev_from_envelope

ROOT_CLUSTER = "@root"
CODE_CLUSTER = "@code"
# Excluded from clustering: the installation's own files and generated/tool directories.
EXCLUDED_COMPONENTS = frozenset({".recalith", ".git", "__pycache__", "node_modules", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache"})


# --------------------------------------------------------------------------
# Clusters


def path_cluster(path: str, *, domain_profile: str, mappings: dict[str, str]) -> str | None:
    """The cluster of one workspace-relative path; None when excluded or not a workspace path."""
    p = path.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    if not p or p.startswith("/") or ":" in p.split("/")[0]:
        return None
    parts = [part for part in p.split("/") if part not in ("", ".")]
    if not parts or ".." in parts or parts[0] in EXCLUDED_COMPONENTS or "__pycache__" in parts:
        return None
    joined = "/".join(parts)
    for prefix, name in sorted(mappings.items(), key=lambda kv: (-len(kv[0]), kv[0])):
        pre = prefix.replace("\\", "/").strip("/")
        if pre and (joined == pre or joined.startswith(pre + "/")):
            return name
    if len(parts) == 1:
        return ROOT_CLUSTER
    if domain_profile == "coding" and parts[0] in CODE_CLUSTER_COMPONENTS:
        return CODE_CLUSTER
    return parts[0]


def action_clusters(ev: Ev, config: ProjectConfig) -> frozenset[str]:
    """Clusters of a tool start's paths (empty: not a path-bearing action)."""
    if ev.kind != "tool_started":
        return frozenset()
    found = set()
    for path in ev.action.get("paths") or []:
        cluster = path_cluster(str(path), domain_profile=config.domain_profile, mappings=dict(config.segmentation.cluster_mappings))
        if cluster is not None:
            found.add(cluster)
    return frozenset(found)


# --------------------------------------------------------------------------
# Signals


def pivot_prefix(text: str, prefixes: Sequence[str]) -> str | None:
    """The configured pivot prefix a message starts with (after whitespace, case-insensitive).

    Only the message start counts, so a quoted (``>``, quote mark) or pasted
    (code fence, paste marker) start never matches.
    """
    low = text.lstrip().casefold()
    for prefix in prefixes:
        if low.startswith(prefix.strip().casefold()):
            return prefix
    return None


def minutes_between(earlier: str, later: str) -> float:
    return (parse_utc(later) - parse_utc(earlier)).total_seconds() / 60.0


@dataclass
class SessionState:
    """Per-session detection state (reducer bookkeeping; derived, never served)."""

    session_id: str
    task_id: str
    provisional_task_id: str | None = None
    origin: str = "new_session"  # new_session | host_reset | resumed | host_binding
    last_activity_at: str | None = None
    last_event_id: str | None = None
    continuity: str = "pending"  # pending | blocked | declined | linked | none
    path_event_ids: list[str] = field(default_factory=list)
    path_clusters: list[list[str]] = field(default_factory=list)
    run_clusters: list[str] = field(default_factory=list)
    run_event_ids: list[str] = field(default_factory=list)
    run_after: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> "SessionState":
        return cls(**json.loads(text))


@dataclass(frozen=True)
class Signal:
    reason: str
    after_event_id: str | None
    proposed_event_ids: tuple[str, ...]
    detail: dict[str, Any]


def observe(state: SessionState, ev: Ev, clusters: set[str], config: ProjectConfig) -> list[Signal]:
    """Within-session boundary signals for one event bound to the session's current task.

    ``clusters`` is the current task's observed cluster set and is updated in
    place (actions that do not reach a candidate join the task's clusters).
    """
    seg: SegmentationConfig = config.segmentation
    out: list[Signal] = []
    if ev.is_user_request:
        text = ev.payload["text"]
        prefix = pivot_prefix(text, seg.pivot_prefixes)
        if prefix is not None:
            if state.continuity == "pending":
                state.continuity = "blocked"  # an explicit new-task statement conflicts with automatic linking
            if state.last_event_id is not None and not _first_request(state):
                out.append(Signal("pivot_prefix", state.last_event_id, (ev.event_id,), {"prefix": prefix}))
        elif state.last_activity_at is not None and minutes_between(state.last_activity_at, ev.time) >= seg.idle_boundary_minutes:
            out.append(Signal("idle_resume", state.last_event_id, (ev.event_id,), {"idle_minutes": int(minutes_between(state.last_activity_at, ev.time)), "threshold_minutes": seg.idle_boundary_minutes}))
    found = action_clusters(ev, config)
    if found:
        out.extend(_disjoint(state, ev, found, clusters, seg))
    if ev.is_activity:
        state.last_activity_at = ev.time if state.last_activity_at is None or ev.time > state.last_activity_at else state.last_activity_at
    state.last_event_id = ev.event_id
    return out


def _first_request(state: SessionState) -> bool:
    """A pivot as the session's first activity: the new session already is the new task."""
    return state.last_activity_at is None


def _disjoint(state: SessionState, ev: Ev, found: frozenset[str], clusters: set[str], seg: SegmentationConfig) -> list[Signal]:
    if not clusters:
        clusters.update(found)  # the task's first path actions establish its clusters
        return []
    if found & clusters:
        clusters.update(state.run_clusters)
        clusters.update(found)
        _reset_run(state)
        return []
    common = set(state.run_clusters) & found if state.run_event_ids else set(found)
    if not common:
        clusters.update(state.run_clusters)  # the earlier run ended without reaching a candidate
        _reset_run(state)
        common = set(found)
    if not state.run_event_ids:
        state.run_after = state.last_event_id
    state.run_clusters = sorted(common)
    state.run_event_ids.append(ev.event_id)
    if len(state.run_event_ids) < seg.disjoint_action_count:
        return []
    signal = Signal("disjoint_paths", state.run_after, tuple(state.run_event_ids), {"clusters": state.run_clusters, "observed_clusters": sorted(clusters), "count": len(state.run_event_ids)})
    clusters.update(state.run_clusters)
    _reset_run(state)
    return [signal]


def _reset_run(state: SessionState) -> None:
    state.run_clusters, state.run_event_ids, state.run_after = [], [], None


def continuity_step(state: SessionState, ev: Ev, config: ProjectConfig) -> bool:
    """Count a new session's path-bearing actions; True when the decisive count is reached."""
    if state.continuity != "pending":
        return False
    found = action_clusters(ev, config)
    if not found:
        return False
    state.path_event_ids.append(ev.event_id)
    state.path_clusters.append(sorted(found))
    return len(state.path_event_ids) == config.segmentation.continuity_path_actions


def continuity_fits(state: SessionState, target_clusters: Iterable[str]) -> bool:
    allowed = set(target_clusters)
    return bool(allowed) and all(set(c) <= allowed for c in state.path_clusters)


def candidate(signal: Signal, *, session_id: str, source_task_id: str, policy_revision: int, state: str = "pending") -> TaskBoundaryCandidate:
    """A boundary candidate with a deterministic ID (one per signal and source event)."""
    boundary_id = derived_id("bnd", [session_id, signal.reason, list(signal.proposed_event_ids), source_task_id])
    return TaskBoundaryCandidate(
        boundary_id=boundary_id, session_id=session_id, after_event_id=signal.after_event_id, proposed_event_ids=list(signal.proposed_event_ids),
        reason=signal.reason, source_task_id=source_task_id, state=state, signal=signal.detail, policy_revision=policy_revision,  # type: ignore[arg-type]
    )


def session_candidate(reason: str, *, session_id: str, first_event_id: str, task_id: str, policy_revision: int, detail: dict[str, Any] | None = None) -> TaskBoundaryCandidate:
    return candidate(Signal(reason, None, (first_event_id,), detail or {}), session_id=session_id, source_task_id=task_id, policy_revision=policy_revision)


# --------------------------------------------------------------------------
# Public read-only evaluation


def propose_task_boundaries(ctx: InstallationContext, events: Sequence[Any], *, config: ProjectConfig | None = None, store: Any = None) -> list[TaskBoundaryCandidate]:
    """Boundary candidates these events would propose next, against the stored session state.

    Read-only (DATA_CONTRACTS §11): it simulates the deterministic signals over
    copies of each session's detection state and its task's observed
    clusters; the worker's reducer records the same candidates when it
    reduces the events. A new session yields its ``new_session`` (or
    ``host_reset``) candidate.
    """
    from recalith.storage.db import open_store

    config = config or _config(ctx)
    own = store is None
    store = store or open_store(ctx, readonly=True)
    try:
        with store.read() as view:
            policy_revision = view.execute("SELECT policy_revision FROM installation_meta WHERE singleton = 1").fetchone()[0]
            sessions: dict[str, SessionState] = {}
            clusters: dict[str, set[str]] = {}
            out: list[TaskBoundaryCandidate] = []
            for item in events:
                ev = item if isinstance(item, Ev) else ev_from_envelope(item)
                state = sessions.get(ev.session_id) or load_session(view, ev.session_id)
                if state is None:
                    placeholder = derived_id("task", ["proposed", ev.session_id])
                    reason = "host_reset" if ev.kind == "session_started" and ev.payload.get("source") == "clear" else "new_session"
                    state = SessionState(session_id=ev.session_id, task_id=placeholder, provisional_task_id=placeholder, origin=reason, continuity="blocked" if reason == "host_reset" else "pending")
                    out.append(session_candidate(reason, session_id=ev.session_id, first_event_id=ev.event_id, task_id=placeholder, policy_revision=policy_revision))
                sessions[ev.session_id] = state
                task_clusters = clusters.setdefault(state.task_id, set(load_clusters(view, state.task_id)))
                for signal in observe(state, ev, task_clusters, config):
                    out.append(candidate(signal, session_id=ev.session_id, source_task_id=state.task_id, policy_revision=policy_revision))
            return out
    finally:
        if own:
            store.close()


def load_session(q: Any, session_id: str) -> SessionState | None:
    row = q.execute("SELECT body FROM working_sessions WHERE session_id = ?", (session_id,)).fetchone()
    return None if row is None else SessionState.from_json(row[0])


def load_clusters(q: Any, task_id: str) -> list[str]:
    row = q.execute("SELECT body FROM working_tasks WHERE task_id = ?", (task_id,)).fetchone()
    return [] if row is None else list(json.loads(row[0]).get("clusters") or [])


def _config(ctx: InstallationContext) -> ProjectConfig:
    from pathlib import Path

    from recalith.core.identity import Layout, load_project_config

    return load_project_config(Layout(Path(ctx.root)))


def pending_candidates(q: Any, task_id: str) -> list[TaskBoundaryCandidate]:
    """Pending candidates of a task: the weak proposals the next extraction job folds in (Task 9)."""
    rows = q.execute("SELECT body FROM task_boundaries WHERE source_task_id = ? AND state = 'pending' ORDER BY rowid", (task_id,)).fetchall()
    return [TaskBoundaryCandidate.model_validate_json(r[0]) for r in rows]
