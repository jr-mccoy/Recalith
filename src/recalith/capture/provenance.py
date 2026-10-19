"""Declared versus observed runtime provenance (SYSTEM_SPEC §13; DATA_CONTRACTS §1.1; A52, A54).

* ``os``/``arch``/``ci`` come from normalized adapter platform facts.
* ``python_version``/``node_version`` come only from an operator declaration
  (``operator_config``, current while its config revision is current) or a
  certified version-command result (``certified_tool``) tied to a registered
  executable in the workspace. Recalith's own interpreter is never consulted.
* An observed version is ``stale`` when its executable's registered
  fingerprint changed or it predates the registered change; a tool
  observation without a registered executable binding is ``unknown``. Stale
  and unknown values resolve as unknown until a new certified observation or
  applicable declaration exists.
* Hooks read persisted values only; nothing here launches a version command.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from recalith.fast import parsers
from recalith.contracts.common import DIGEST_RE, InstallationContext, RecordRef, derived_id, digest_of, utc_now
from recalith.contracts.events import EnvironmentObservation, EventEnvelope
from recalith.errors import RecalithError
from recalith.storage.db import Store, Txn

PLATFORM_KEYS = ("os", "arch", "ci")
RUNTIME_KEYS = ("python_version", "node_version")
VERSION_PARSERS = frozenset({"python_version", "node_version"})


def executable_id_for(ctx: InstallationContext, workspace_id: str, identity: str) -> str:
    return "exe_" + digest_of([ctx.installation_id, workspace_id, identity])


def fingerprint_file(path: Path | str) -> str:
    """Content plus resolved-target fingerprint of an executable (operator/worker use)."""
    real = os.path.realpath(path)
    digest = hashlib.sha256()
    with open(real, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest_of([real, digest.hexdigest()])


def register_executable(store: Store, ctx: InstallationContext, *, identity: str, fingerprint: str, workspace_id: str | None = None) -> str:
    """Register or refresh an executable; a changed fingerprint makes older observations stale."""
    if ctx.actor.kind not in ("operator", "controller"):
        raise RecalithError("policy_refused", "executables are registered by the operator or the controller")
    if not DIGEST_RE.match(fingerprint):
        raise RecalithError("invalid_schema", "an executable fingerprint is a SHA-256 digest")
    workspace_id = workspace_id or ctx.workspace_id
    executable_id = executable_id_for(ctx, workspace_id, identity)
    with store.transaction() as txn:
        row = txn.one("SELECT fingerprint FROM executables WHERE executable_id = ?", (executable_id,))
        if row is None:
            txn.execute("INSERT INTO executables (executable_id, workspace_id, identity, fingerprint) VALUES (?, ?, ?, ?)", (executable_id, workspace_id, identity, fingerprint))
            txn.mutated(serving_relevant=False)
        elif row[0] != fingerprint:
            txn.execute(
                "UPDATE executables SET fingerprint = ?, fingerprint_changed_at = ?, changed_store_revision = ? WHERE executable_id = ?",
                (fingerprint, utc_now(), txn.next_store_revision, executable_id),
            )
            txn.execute(
                "UPDATE environment_observations SET freshness = 'stale' WHERE executable_id = ? AND source_kind = 'certified_tool' AND freshness = 'current'",
                (executable_id,),
            )
            txn.mutated(serving_relevant=True)  # affected runtime predicates become unknown
    return executable_id


def _insert(txn: Txn, observation_id: str, obs: EnvironmentObservation) -> bool:
    if txn.one("SELECT 1 FROM environment_observations WHERE observation_id = ?", (observation_id,)) is not None:
        return False
    txn.execute(
        "INSERT INTO environment_observations (observation_id, workspace_id, key, value, executable_id, source_kind, source_event_id, config_revision, observed_at, fingerprint, executable_fingerprint, freshness) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            observation_id, obs.workspace_id, obs.key, obs.value, obs.executable_id, obs.source_kind,
            obs.source_ref.id if obs.source_ref else None, obs.config_revision, obs.observed_at, obs.fingerprint,
            obs.executable_fingerprint, obs.freshness,
        ),
    )
    txn.mutated(serving_relevant=True)
    return True


def record_declared_runtime(store: Store, ctx: InstallationContext, *, key: str, value: str, config_revision: int) -> str:
    """Record an operator ``project.toml`` runtime declaration for one config revision."""
    if ctx.actor.kind not in ("operator", "controller"):
        raise RecalithError("policy_refused", "runtime declarations come from operator configuration")
    if key not in RUNTIME_KEYS:
        raise RecalithError("invalid_schema", "only runtime version keys are declared")
    observation_id = derived_id("obs", [ctx.installation_id, ctx.workspace_id, key, "operator_config", config_revision])
    obs = EnvironmentObservation(
        key=key, value=value, workspace_id=ctx.workspace_id, executable_id=None, source_kind="operator_config", source_ref=None,
        config_revision=config_revision, observed_at=utc_now(), fingerprint=digest_of([key, value]), executable_fingerprint=None, freshness="current",
    )
    with store.transaction() as txn:
        _insert(txn, observation_id, obs)
    return observation_id


def observe_event(txn: Txn, ctx: InstallationContext, env: EventEnvelope) -> list[str]:
    """Ingestion: derive environment observations from one newly inserted event."""
    created: list[str] = []
    observed_at = env.occurred_at or env.recorded_at
    ref = RecordRef(kind="event", id=env.event_id, revision=1)
    if env.kind == "session_started" and isinstance(env.payload.get("environment"), dict):
        for key in PLATFORM_KEYS:
            value = env.payload["environment"].get(key)
            if not isinstance(value, str):
                continue
            try:
                obs = EnvironmentObservation(
                    key=key, value=value, workspace_id=env.workspace_id, executable_id=None, source_kind="adapter_platform", source_ref=ref,
                    config_revision=None, observed_at=observed_at, fingerprint=digest_of([key, value]), executable_fingerprint=None, freshness="current",
                )
            except ValueError:
                continue
            oid = derived_id("obs", [env.event_id, key])
            if _insert(txn, oid, obs):
                created.append(oid)
    if env.kind == "tool_finished" and env.authority == "observed_tool":
        try:
            created += _observe_version(txn, ctx, env, ref, observed_at)
        except ValueError:
            pass  # fail closed: an observation that cannot validate certifies nothing
    return created


def _observe_version(txn: Txn, ctx: InstallationContext, env: EventEnvelope, ref: RecordRef, observed_at: str) -> list[str]:
    payload = env.payload
    action = payload.get("action") or {}
    spec = parsers.applicable_parser(action)
    if spec is None or spec.parser_id not in VERSION_PARSERS:
        return []  # an assertion from any other parser or source certifies nothing
    if not payload.get("result_received") or payload.get("outcome") != "success" or env.coverage.truncated or not isinstance(payload.get("result_text"), str):
        return []
    parsed = spec.parse(payload["result_text"], payload.get("exit_code"))
    if not parsed.recognized:
        return []
    key, value = next(iter(parsed.runtime.items()))
    identity = action.get("executable") or action["argv"][0]
    row = txn.one("SELECT executable_id, fingerprint, fingerprint_changed_at FROM executables WHERE workspace_id = ? AND identity = ?", (env.workspace_id, identity))
    if row is None or row[1] is None:
        executable_id = fingerprint = None
        freshness = "unknown"
    else:
        executable_id, fingerprint, changed_at = row
        freshness = "stale" if changed_at is not None and observed_at < changed_at else "current"
    obs = EnvironmentObservation(
        key=key, value=value, workspace_id=env.workspace_id, executable_id=executable_id, source_kind="certified_tool", source_ref=ref,
        config_revision=None, observed_at=observed_at, fingerprint=digest_of([key, value, spec.qualified_id]), executable_fingerprint=fingerprint, freshness=freshness,
    )
    oid = derived_id("obs", [env.event_id, key])
    return [oid] if _insert(txn, oid, obs) else []


# --------------------------------------------------------------------------
# Resolution at query time


@dataclass(frozen=True)
class ResolvedValue:
    key: str
    value: str | None
    reason: str  # declared | observed | platform | missing | stale | unbound | conflict
    observation_ids: tuple[str, ...] = ()

    @property
    def known(self) -> bool:
        return self.value is not None


def _rows(view: Any, sql: str, params: tuple) -> list[tuple]:
    return view.execute(sql, params).fetchall()


def resolve(store: Store, ctx: InstallationContext, key: str, *, executable_identity: str | None = None, workspace_id: str | None = None) -> ResolvedValue:
    """Resolve one environment key for a query; anything uncertain is unknown."""
    with store.read() as view:
        return resolve_in(view, ctx, key, executable_identity=executable_identity, workspace_id=workspace_id)


def resolve_in(view: Any, ctx: InstallationContext, key: str, *, executable_identity: str | None = None, workspace_id: str | None = None) -> ResolvedValue:
    """:func:`resolve` inside the caller's read snapshot or transaction."""
    workspace_id = workspace_id or ctx.workspace_id
    policy_revision = view.execute("SELECT policy_revision FROM installation_meta WHERE singleton = 1").fetchone()[0]
    if key in PLATFORM_KEYS:
        rows = _rows(view, "SELECT observation_id, value FROM environment_observations WHERE workspace_id = ? AND key = ? AND source_kind = 'adapter_platform' AND freshness = 'current' ORDER BY observed_at DESC, observation_id LIMIT 1", (workspace_id, key))
        return ResolvedValue(key, rows[0][1], "platform", (rows[0][0],)) if rows else ResolvedValue(key, None, "missing")
    if key not in RUNTIME_KEYS:
        return ResolvedValue(key, None, "missing")
    declared = _rows(view, "SELECT observation_id, value, config_revision FROM environment_observations WHERE workspace_id = ? AND key = ? AND source_kind = 'operator_config' ORDER BY observed_at DESC", (workspace_id, key))
    current_declared = [(oid, v) for oid, v, rev in declared if rev == policy_revision]
    exe_rows = _rows(view, "SELECT executable_id, identity, fingerprint, fingerprint_changed_at FROM executables WHERE workspace_id = ?", (workspace_id,))
    executables = {r[0]: r for r in exe_rows}
    tool_rows = _rows(
        view,
        "SELECT observation_id, value, executable_id, executable_fingerprint, observed_at, freshness FROM environment_observations WHERE workspace_id = ? AND key = ? AND source_kind = 'certified_tool' ORDER BY observed_at DESC, observation_id",
        (workspace_id, key),
    )
    latest: dict[str, tuple] = {}
    for row in tool_rows:
        if row[2] is not None and row[2] not in latest:
            latest[row[2]] = row

    def effective(row: tuple) -> str:
        exe = executables.get(row[2])
        if exe is None or row[3] is None or exe[2] is None:
            return "unknown"
        if row[5] != "current" or exe[2] != row[3] or (exe[3] is not None and row[4] < exe[3]):
            return "stale"
        return "current"

    if executable_identity is not None:
        exe_id = executable_id_for(ctx, workspace_id, executable_identity)
        row = latest.get(exe_id)
        if row is not None and effective(row) == "current":
            if any(v != row[1] for _, v in current_declared):
                return ResolvedValue(key, None, "conflict", (row[0], *[o for o, _ in current_declared]))
            return ResolvedValue(key, row[1], "observed", (row[0],))
        if row is not None:
            return ResolvedValue(key, None, effective(row), (row[0],))
        if exe_id not in executables:
            return ResolvedValue(key, None, "unbound")
        if current_declared:
            return ResolvedValue(key, current_declared[0][1], "declared", (current_declared[0][0],))
        return ResolvedValue(key, None, "missing")
    values: dict[str, list[str]] = {}
    for oid, value in current_declared[:1]:
        values.setdefault(value, []).append(oid)
    stale = []
    for row in latest.values():
        state = effective(row)
        if state == "current":
            values.setdefault(row[1], []).append(row[0])
        else:
            stale.append(row[0])
    if len(values) == 1:
        value, ids = next(iter(values.items()))
        declared_ids = {oid for oid, _ in current_declared}
        return ResolvedValue(key, value, "observed" if any(i not in declared_ids for i in ids) else "declared", tuple(ids))
    if len(values) > 1:
        return ResolvedValue(key, None, "conflict", tuple(i for ids in values.values() for i in ids))
    return ResolvedValue(key, None, "stale" if stale else "missing", tuple(stale))


def environment_values(store: Store, ctx: InstallationContext) -> dict[str, str]:
    """The query's EnvironmentValues: only resolved keys; absent means unknown."""
    with store.read() as view:
        return environment_values_in(view, ctx)


def environment_values_in(view: Any, ctx: InstallationContext, *, workspace_id: str | None = None) -> dict[str, str]:
    """:func:`environment_values` inside the caller's read snapshot or transaction (one consistent read)."""
    resolved = (resolve_in(view, ctx, key, workspace_id=workspace_id) for key in PLATFORM_KEYS + RUNTIME_KEYS)
    return {r.key: r.value for r in resolved if r.value is not None}
