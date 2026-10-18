"""Evidence lineage: canonical origins, root classes and independent roots.

SYSTEM_SPEC §5.3, §7.1, §7.1.1, §13; DATA_CONTRACTS §1, §2.1, §6, §6.1 (decision 0010).

**Eligible roots.** Only an authenticated user statement (``user_message`` or
an operator declaration/correction on the user channel with ``explicit_user``
authority) or a certified tool *result* (``tool_finished``/``artifact_changed``
on the tool channel with ``observed_tool`` authority), without
``derived_from``, is a root. Assistant text, curator output, memory
telemetry, session lifecycle, host-generated prompts, a call without its
result, a self-reporting command (``echo``/``printf`` only restate their
arguments: agent text routed through a tool) and forwarded subagent output
are never roots. Forwarded and derived content resolves to the roots it came
from; it never adds one.

**Canonical descriptors.** Code builds every :class:`ObservationDescriptor`
from the stored, scrubbed envelope; a model never supplies one. An
adapter-set descriptor is honored only when it names the event's own origin
key, and it may claim ``complete`` dependency coverage only for an adapter in
:data:`CERTIFIED_EXPERIMENT_ADAPTERS` (none in this build) with a nonempty,
fully fingerprinted dependency set and an exact action; otherwise its coverage
is downgraded to ``partial``. For adapters without descriptors the registered
rules in :data:`ADAPTER_LINEAGE` apply (Claude Code 2.1.301, decision 0005):
a complete ``Read`` result is an artifact snapshot of that file; a ``Task``/
``Agent`` result forwards its subagent; every other result is an experiment
whose dependencies are unknown.

**Classes.** Ingestion registers each eligible root event (:func:`register_event`)
under its origin key with exact equivalence *tokens*: origin identity; an
artifact snapshot (workspace, artifact key, content digest); an experiment
signature (workspace, normalized action, experiment identity and the complete
sorted dependency fingerprints); or, when dependencies are partial or
unknown, one unresolved experiment family (workspace, normalized action,
experiment identity) — differing unknown fields never split it. Members
sharing a token are one class, so classes are the transitive closure over the
whole store. A class ID is ``root_`` + SHA-256 of the lexicographically least
canonical origin key; when a merge or a smaller new member changes it, the
old ID is kept as an alias. A merge of two existing classes can reduce a
claim's count, so it advances the guidance epoch and returns the live claims
citing the merged members for revalidation. No token contains a destination
installation, a delivery count, a session, a tool-call or run identifier, or
a timestamp.

**Counting** (:func:`resolve` / :func:`independent_roots`). Support links are
traversed through stored provenance (``derived_from``, record evidence,
forwarding) with cycle detection and bounds. Each eligible root maps to its
persisted class; then, per proposition, every user declaration of one
authority actor collapses into one class (rephrasing or repeating a
preference never corroborates it), and an invalid proposition key collapses
everything into one class. Roots whose descriptor could not be resolved add
no class when a resolved class exists, and form at most one otherwise. A root
whose source identity is in unresolved conflict is excluded and marks the
result ``needs_revalidation``. Contradicting links stay attached, and a class
holding both a success and a failure is unstable: either blocks
corroboration. Distinct classes are a necessary policy condition, not proof
of independence or causality.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from pydantic import ValidationError

from recalith.contracts.common import EvidenceLink, InstallationContext, OriginEventKey, RecordRef, canonical_json, derived_id, digest_of
from recalith.contracts.events import MEMORY_KINDS, ActionDescriptor, EventEnvelope, ObservationDescriptor
from recalith.contracts.memory import PropositionKey
from recalith.storage import failpoints, records

# Without verified distinct source authority, every user statement in an
# installation is one actor's (SYSTEM_SPEC §7.1.1).
USER_ACTOR = "user:local"
# Adapters certified to set ``dependency_coverage: complete`` for a bounded
# experiment domain. None is certified by this design alone.
CERTIFIED_EXPERIMENT_ADAPTERS: frozenset[str] = frozenset()
SELF_REPORTING_EXECUTABLES = frozenset({"echo", "printf"})
DECLARATION_KINDS = frozenset({"user_message", "operator_declaration", "operator_correction"})
TOOL_RESULT_KINDS = frozenset({"tool_finished", "artifact_changed"})
MAX_NODES = 2048
MAX_DEPTH = 32
MAX_FORWARDED_EVENTS = 512
_IN_CHUNK = 400


@dataclass(frozen=True)
class AdapterLineage:
    """Registered lineage facts of one exact host adapter (data, not an adapter import)."""

    versions: frozenset[str]
    artifact_tools: frozenset[str]  # a complete result is an exact snapshot of its one path
    forwarding_tools: frozenset[str]  # a result relays a subagent's output
    agent_extension_key: str  # extension field naming the subagent a tool event ran in
    forwarded_agent_field: str  # result field naming the subagent a forwarding result relays


# Claude Code 2.1.301 (decision 0005; the real ``subagent`` fixture): a ``Task``/
# ``Agent`` result names ``agentId`` and the subagent's own tool events carry
# ``extensions.claude_code.agent_id``.
ADAPTER_LINEAGE: dict[str, AdapterLineage] = {
    "claude_code": AdapterLineage(
        versions=frozenset({"2.1.301"}),
        artifact_tools=frozenset({"Read"}),
        forwarding_tools=frozenset({"Agent", "Task"}),
        agent_extension_key="agent_id",
        forwarded_agent_field="agentId",
    ),
}


# --------------------------------------------------------------------------
# Origins and class identity


def origin_key(env: EventEnvelope) -> OriginEventKey:
    """The event's canonical origin: its producing installation and adapter plus the host source key.

    Message parts share one origin (``origin.source_event_key`` is the
    unsplit key), so they are one observation.
    """
    return OriginEventKey(source_namespace=f"{env.installation_id}:{env.adapter_id}", source_event_key=env.origin.source_event_key)


def _order(key: OriginEventKey) -> tuple[str, str]:
    return (key.source_namespace, key.source_event_key)


def root_class_id(canonical: OriginEventKey) -> str:
    return derived_id("root", [canonical.source_namespace, canonical.source_event_key])


def _token(*parts: Any) -> str:
    return digest_of(list(parts))


# --------------------------------------------------------------------------
# Canonical observation descriptors


@dataclass(frozen=True)
class Observation:
    """What lineage code derives from one stored event."""

    reason: str  # "root" for an eligible root, else the ineligibility code
    descriptor: ObservationDescriptor | None = None
    resolution: str = "resolved"  # resolved | unresolved (a root whose descriptor could not be established)
    outcome: str | None = None
    certified_snapshot: bool = False  # a registered artifact rule, not an experiment
    forwards_agent: str | None = None
    forwarded_origins: tuple[OriginEventKey, ...] = ()

    @property
    def eligible(self) -> bool:
        return self.reason == "root"


def _executable_name(executable: str) -> str:
    base = executable.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return base[:-4] if base.endswith(".exe") else base


def _unresolved(origin: OriginEventKey, outcome: str | None) -> Observation:
    return Observation("root", ObservationDescriptor(origin_event_key=origin, observation_kind="tool_result", dependency_coverage="unknown"), resolution="unresolved", outcome=outcome)


def classify(env: EventEnvelope) -> Observation:
    """Eligibility and the canonical descriptor of one stored event (needs its payload)."""
    if env.kind in MEMORY_KINDS:
        return Observation("memory_telemetry")
    if env.derived_from:
        return Observation("derived")
    if env.channel == "assistant":
        return Observation("assistant_text")
    origin = origin_key(env)
    if env.kind in DECLARATION_KINDS:
        if env.channel != "user" or env.authority != "explicit_user":
            return Observation("no_user_authority")
        return Observation("root", ObservationDescriptor(origin_event_key=origin, observation_kind="user_declaration", authority_actor_id=USER_ACTOR, dependency_coverage="unknown"))
    if env.kind == "tool_started":
        return Observation("no_result")
    if env.kind not in TOOL_RESULT_KINDS:
        return Observation("not_an_observation")
    if env.channel != "tool" or env.authority != "observed_tool":
        return Observation("no_tool_authority")
    payload = env.payload
    outcome = payload.get("outcome") if isinstance(payload.get("outcome"), str) else None
    if payload.get("observation") is not None:
        return _adapter_descriptor(env, origin, payload["observation"], outcome)
    rules = ADAPTER_LINEAGE.get(env.adapter_id)
    try:
        action = ActionDescriptor.model_validate(payload.get("action")) if payload.get("action") is not None else None
    except ValidationError:
        return _unresolved(origin, outcome)
    tool = payload.get("tool_name")
    if rules is not None and tool in rules.forwarding_tools:
        return Observation("forwarded_content", forwards_agent=_forwarded_agent(payload, rules))
    if action is not None and action.parse_status == "exact" and action.executable is not None and _executable_name(action.executable) in SELF_REPORTING_EXECUTABLES:
        return Observation("agent_authored_output")
    if rules is not None and env.adapter_version in rules.versions and tool in rules.artifact_tools and _complete_result(env, action):
        assert action is not None
        digest = digest_of({"arguments": payload.get("arguments") or {}, "result_text": payload["result_text"]})
        descriptor = ObservationDescriptor(origin_event_key=origin, observation_kind="artifact_snapshot", artifact_key=f"file:{action.paths[0]}", artifact_digest=digest, action=action, dependency_coverage="unknown")
        return Observation("root", descriptor, outcome=outcome, certified_snapshot=True)
    if env.kind == "artifact_changed" or action is None:
        return _unresolved(origin, outcome)
    return Observation("root", ObservationDescriptor(origin_event_key=origin, observation_kind="tool_result", action=action, dependency_coverage="unknown"), outcome=outcome)


def _complete_result(env: EventEnvelope, action: ActionDescriptor | None) -> bool:
    payload = env.payload
    return (
        action is not None and action.parse_status == "exact" and len(action.paths) == 1
        and payload.get("result_received") is True and payload.get("outcome") == "success" and isinstance(payload.get("result_text"), str)
        and not env.coverage.truncated and not env.coverage.missing_context
    )


def _forwarded_agent(payload: Mapping[str, Any], rules: AdapterLineage) -> str | None:
    text = payload.get("result_text")
    if not isinstance(text, str) or payload.get("outcome") != "success":
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    agent = data.get(rules.forwarded_agent_field) if isinstance(data, dict) else None
    return agent if isinstance(agent, str) and 0 < len(agent) <= 256 else None


def _adapter_descriptor(env: EventEnvelope, origin: OriginEventKey, raw: Any, outcome: str | None) -> Observation:
    try:
        descriptor = ObservationDescriptor.model_validate(raw)
    except ValidationError:
        return _unresolved(origin, outcome)
    if descriptor.origin_event_key != origin or descriptor.observation_kind == "user_declaration":
        return _unresolved(origin, outcome)  # a tool channel never declares; a foreign origin is not this event
    if descriptor.forwarded_origin_keys:
        return Observation("forwarded_content", forwarded_origins=tuple(descriptor.forwarded_origin_keys))
    if descriptor.dependency_coverage == "complete" and not _complete_allowed(env, descriptor):
        descriptor = descriptor.model_copy(update={"dependency_coverage": "partial"})
    if descriptor.action is None and not (descriptor.artifact_key and descriptor.artifact_digest):
        return _unresolved(origin, outcome)
    return Observation("root", descriptor, outcome=outcome)


def _complete_allowed(env: EventEnvelope, descriptor: ObservationDescriptor) -> bool:
    return (
        env.adapter_id in CERTIFIED_EXPERIMENT_ADAPTERS
        and descriptor.action is not None and descriptor.action.parse_status == "exact"
        and bool(descriptor.dependencies) and all(d.fingerprint is not None for d in descriptor.dependencies)
    )


def action_signature(action: ActionDescriptor, arguments: Any) -> Any:
    """Normalized experiment identity of an action: argv order and flags are preserved."""
    if action.parse_status != "exact":
        return {"tool": action.tool, "parse": "unresolved"}  # unknown action identity never splits a family
    if action.argv is not None:
        return {"tool": action.tool, "executable": action.executable, "argv": list(action.argv), "cwd": action.cwd_path}
    return {"tool": action.tool, "arguments": arguments if isinstance(arguments, dict) else {}, "cwd": action.cwd_path}


def tokens(env: EventEnvelope, obs: Observation) -> list[tuple[str, str]]:
    """Exact equivalence tokens of an eligible root (origin first)."""
    assert obs.descriptor is not None
    desc = obs.descriptor
    origin = desc.origin_event_key
    out = [(_token("origin", origin.source_namespace, origin.source_event_key), "origin_identity")]
    if obs.resolution != "resolved" or desc.observation_kind == "user_declaration":
        return out
    workspace = env.workspace_id
    if desc.artifact_key and desc.artifact_digest:
        out.append((_token("artifact", workspace, desc.artifact_key, desc.artifact_digest), "artifact_snapshot"))
    if obs.certified_snapshot or desc.action is None:
        return out
    signature = action_signature(desc.action, env.payload.get("arguments"))
    if desc.dependency_coverage == "complete":
        deps = sorted([d.kind, d.key, d.fingerprint, None if d.record is None else [d.record.id, d.record.revision]] for d in desc.dependencies)
        out.append((_token("experiment", workspace, signature, desc.experiment_identity, deps), "experiment_signature"))
    else:
        out.append((_token("family", workspace, signature, desc.experiment_identity), "unknown_dependencies"))
    return out


# --------------------------------------------------------------------------
# Registration at ingestion


@dataclass(frozen=True)
class Registration:
    event_id: str
    root_class_id: str
    merged: tuple[str, ...]  # previous class IDs folded into this one (aliases now)
    affected_claims: tuple[RecordRef, ...]  # live claim heads citing members of a merged class


def register_event(txn: Any, env: EventEnvelope) -> Registration | None:
    """Register one newly inserted event as a root member; None when it is not an eligible root.

    Runs inside the ingestion transaction, so a crash leaves either the event
    with its membership, tokens and aliases or neither. Re-registration is a
    no-op.
    """
    obs = classify(env)
    if not obs.eligible:
        return None
    if txn.one("SELECT 1 FROM root_event_members WHERE event_id = ?", (env.event_id,)) is not None:
        return None
    assert obs.descriptor is not None
    origin = obs.descriptor.origin_event_key
    txn.execute(
        "INSERT INTO root_event_members (event_id, source_namespace, source_event_key, observation_kind, authority_actor, outcome, resolution) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (env.event_id, origin.source_namespace, origin.source_event_key, obs.descriptor.observation_kind, obs.descriptor.authority_actor_id, obs.outcome, obs.resolution),
    )
    toks = tokens(env, obs)
    found: dict[str, None] = {}
    reasons: set[str] = set()
    member = txn.one("SELECT root_class_id FROM root_members WHERE source_namespace = ? AND source_event_key = ?", (origin.source_namespace, origin.source_event_key))
    if member is not None:
        found[member[0]] = None
        reasons.add("origin_identity")
    new_tokens: list[tuple[str, str]] = []
    for token, reason in toks:
        row = txn.one("SELECT root_class_id FROM root_tokens WHERE token = ?", (token,))
        if row is None:
            new_tokens.append((token, reason))
        else:
            found[row[0]] = None
            reasons.add(reason)
    classes = sorted(found)
    canonicals = {origin: None}
    for cid in classes:
        ns, key, stored = txn.one("SELECT canonical_namespace, canonical_key, equivalence_reasons FROM root_classes WHERE root_class_id = ?", (cid,))
        canonicals[OriginEventKey(source_namespace=ns, source_event_key=key)] = None
        reasons.update(json.loads(stored))
    canonical = min(canonicals, key=_order)
    winner = root_class_id(canonical)
    reason_json = canonical_json(sorted(reasons)).decode()
    if winner in classes:
        txn.execute("UPDATE root_classes SET equivalence_reasons = ? WHERE root_class_id = ?", (reason_json, winner))
    else:
        txn.execute("DELETE FROM root_aliases WHERE alias_id = ?", (winner,))  # a canonical ID is never an alias
        txn.execute(
            "INSERT INTO root_classes (root_class_id, canonical_namespace, canonical_key, equivalence_reasons) VALUES (?, ?, ?, ?)",
            (winner, canonical.source_namespace, canonical.source_event_key, reason_json),
        )
    losers = [cid for cid in classes if cid != winner]
    for cid in losers:
        for table in ("root_members", "root_tokens", "root_aliases"):
            txn.execute(f"UPDATE {table} SET root_class_id = ? WHERE root_class_id = ?", (winner, cid))  # noqa: S608 - fixed names
        txn.execute(
            "INSERT INTO root_aliases (alias_id, root_class_id, merged_at_revision) VALUES (?, ?, ?) ON CONFLICT(alias_id) DO UPDATE SET root_class_id = excluded.root_class_id",
            (cid, winner, txn.next_store_revision),
        )
        txn.execute("DELETE FROM root_classes WHERE root_class_id = ?", (cid,))
    if member is None:
        txn.execute(
            "INSERT INTO root_members (source_namespace, source_event_key, root_class_id, descriptor) VALUES (?, ?, ?, ?)",
            (origin.source_namespace, origin.source_event_key, winner, canonical_json(obs.descriptor).decode()),
        )
    for token, reason in new_tokens:
        txn.execute("INSERT INTO root_tokens (token, reason, root_class_id) VALUES (?, ?, ?)", (token, reason, winner))
    affected: list[RecordRef] = []
    if len(classes) >= 2:
        # Two classes that were counted separately are now one: counts can drop.
        failpoints.hit(failpoints.ROOTS_AFTER_MERGE)
        affected = claims_citing(txn, class_events(txn, winner))
        txn.mutated(serving_relevant=True)
    elif losers or winner not in classes:
        txn.mutated(serving_relevant=False)
    return Registration(env.event_id, winner, tuple(losers), tuple(affected))


def class_events(q: Any, class_id: str) -> list[str]:
    rows = q.execute(
        "SELECT e.event_id FROM root_event_members e JOIN root_members m ON m.source_namespace = e.source_namespace AND m.source_event_key = e.source_event_key WHERE m.root_class_id = ? ORDER BY e.event_id",
        (class_id,),
    ).fetchall()
    return [r[0] for r in rows]


def _chunks(items: Sequence[Any]) -> Iterable[Sequence[Any]]:
    for i in range(0, len(items), _IN_CHUNK):
        yield items[i : i + _IN_CHUNK]


def claims_citing(q: Any, event_ids: Sequence[str]) -> list[RecordRef]:
    """Live claim heads whose current revision cites these events as support, directly or through one record."""
    owners: set[tuple[str, str, int]] = set()
    for chunk in _chunks(list(event_ids)):
        marks = ",".join("?" for _ in chunk)
        owners.update(q.execute(f"SELECT owner_kind, owner_id, owner_revision FROM evidence_links WHERE target_kind = 'event' AND relation = 'supports' AND target_id IN ({marks})", tuple(chunk)).fetchall())  # noqa: S608
    claims = {(i, r) for k, i, r in owners if k == "claim"}
    for kind, record_id, revision in sorted(owners):
        if kind in ("task", "episode", "claim"):
            rows = q.execute("SELECT owner_id, owner_revision FROM evidence_links WHERE owner_kind = 'claim' AND relation = 'supports' AND target_kind = ? AND target_id = ? AND target_revision = ?", (kind, record_id, revision)).fetchall()
            claims.update((i, r) for i, r in rows)
    out = []
    for claim_id, revision in sorted(claims):
        current = records.head(q, "claim", claim_id)
        if current is not None and current[0] == revision and current[1] in ("candidate", "active", "disputed"):
            out.append(RecordRef(kind="claim", id=claim_id, revision=revision))
    return out


# --------------------------------------------------------------------------
# Aliases and class lookup


def resolve_alias(q: Any, class_id: str) -> str | None:
    """The current class for a class ID or a retained alias; None when unknown."""
    seen: set[str] = set()
    current = class_id
    while current not in seen:
        seen.add(current)
        if q.execute("SELECT 1 FROM root_classes WHERE root_class_id = ?", (current,)).fetchone() is not None:
            return current
        row = q.execute("SELECT root_class_id FROM root_aliases WHERE alias_id = ?", (current,)).fetchone()
        if row is None:
            return None
        current = row[0]
    return None  # an alias cycle names no class


@dataclass(frozen=True)
class Member:
    event_id: str
    class_id: str
    origin: OriginEventKey
    observation_kind: str
    authority_actor: str | None
    resolution: str


def member(q: Any, event_id: str) -> Member | None:
    row = q.execute(
        "SELECT m.root_class_id, e.source_namespace, e.source_event_key, e.observation_kind, e.authority_actor, e.resolution FROM root_event_members e "
        "JOIN root_members m ON m.source_namespace = e.source_namespace AND m.source_event_key = e.source_event_key WHERE e.event_id = ?",
        (event_id,),
    ).fetchone()
    if row is None:
        return None
    return Member(event_id, row[0], OriginEventKey(source_namespace=row[1], source_event_key=row[2]), row[3], row[4], row[5])


def _canonical(q: Any, class_id: str) -> OriginEventKey:
    ns, key = q.execute("SELECT canonical_namespace, canonical_key FROM root_classes WHERE root_class_id = ?", (class_id,)).fetchone()
    return OriginEventKey(source_namespace=ns, source_event_key=key)


def _unstable(q: Any, class_id: str) -> bool:
    rows = q.execute(
        "SELECT DISTINCT e.outcome FROM root_event_members e JOIN root_members m ON m.source_namespace = e.source_namespace AND m.source_event_key = e.source_event_key WHERE m.root_class_id = ?",
        (class_id,),
    ).fetchall()
    return {"success", "failure"} <= {r[0] for r in rows}


def _conflicted(q: Any, event_id: str) -> bool:
    return q.execute(
        "SELECT 1 FROM source_conflicts c JOIN events e ON e.adapter_id = c.adapter_id AND e.source_event_key = c.source_event_key WHERE e.event_id = ? AND c.state = 'unresolved'",
        (event_id,),
    ).fetchone() is not None


# --------------------------------------------------------------------------
# Provenance traversal


def _envelope(q: Any, event_id: str) -> tuple[EventEnvelope | None, str | None]:
    row = q.execute("SELECT envelope, payload, payload_state FROM events WHERE event_id = ?", (event_id,)).fetchone()
    if row is None:
        return None, "missing"
    if row[2] != "available" or row[1] is None:
        return None, "payload_unavailable"
    body = json.loads(row[0])
    body["payload"] = json.loads(row[1])
    return EventEnvelope.model_validate(body), None


def _field_parent(data: Any, path: str) -> Any:
    """The object holding the located field (e.g. a SupportedText for ``steps.2.result.text``)."""
    parts = path.split(".")
    for part in parts[:-1]:
        if isinstance(data, dict) and part in data:
            data = data[part]
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return None
    return data


@dataclass
class _Walk:
    q: Any
    nodes: int = 0
    cycles: int = 0
    incomplete: bool = False
    reached: set[str] = field(default_factory=set)  # every non-telemetry event visited (admission's provenance closure)
    unregistered: set[str] = field(default_factory=set)
    ineligible: dict[str, str] = field(default_factory=dict)

    def link(self, link: EvidenceLink, path: tuple = ()) -> set[str]:
        roots = self.ref(link.ref, link.locator.field if link.locator is not None else None, path)
        if link.ref.kind != "event" and link.root_event_ids:
            roots &= set(link.root_event_ids)  # a record link names which of its roots it relies on
        return roots

    def ref(self, ref: RecordRef, located: str | None, path: tuple) -> set[str]:
        key = (ref.kind, ref.id, ref.revision, located)
        if any(k[:3] == key[:3] for k in path):
            self.cycles += 1  # a provenance cycle supports nothing
            return set()
        if len(path) >= MAX_DEPTH or self.nodes >= MAX_NODES:
            self.incomplete = True
            return set()
        self.nodes += 1
        path = (*path, key)
        if ref.kind == "event":
            return self.event(ref.id, path)
        if ref.kind == "capsule":
            self.ineligible[ref.id] = "capsule_unavailable"  # full-release capsules; none exist in preview
            return set()
        return self.record(ref, located, path)

    def event(self, event_id: str, path: tuple) -> set[str]:
        if self.q.execute("SELECT 1 FROM root_event_members WHERE event_id = ?", (event_id,)).fetchone() is not None:
            self.reached.add(event_id)
            return {event_id}
        env, missing = _envelope(self.q, event_id)
        if env is None:
            self.ineligible[event_id] = missing or "missing"
            return set()
        if env.kind not in MEMORY_KINDS:
            self.reached.add(event_id)
        obs = classify(env)
        if obs.eligible:
            self.unregistered.add(event_id)
            return {event_id}
        self.ineligible[event_id] = obs.reason
        roots: set[str] = set()
        if obs.reason == "derived":
            for parent in env.derived_from:
                roots |= self.ref(parent, None, path)
        elif obs.reason == "forwarded_content":
            for forwarded in self._forwarded(env, obs):
                roots |= self.ref(RecordRef(kind="event", id=forwarded, revision=1), None, path)
        return roots

    def _forwarded(self, env: EventEnvelope, obs: Observation) -> list[str]:
        if obs.forwarded_origins:
            out: list[str] = []
            for origin in obs.forwarded_origins:
                out += [r[0] for r in self.q.execute("SELECT event_id FROM root_event_members WHERE source_namespace = ? AND source_event_key = ? ORDER BY event_id", (origin.source_namespace, origin.source_event_key)).fetchall()]
            return out
        rules = ADAPTER_LINEAGE.get(env.adapter_id)
        if obs.forwards_agent is None or rules is None:
            return []
        rows = self.q.execute(
            "SELECT event_id, envelope FROM events WHERE session_id = ? AND kind = 'tool_finished' ORDER BY commit_sequence LIMIT ?",
            (env.session_id, MAX_FORWARDED_EVENTS + 1),
        ).fetchall()
        if len(rows) > MAX_FORWARDED_EVENTS:
            self.incomplete = True
        out = []
        for event_id, envelope in rows[:MAX_FORWARDED_EVENTS]:
            ext = json.loads(envelope).get("extensions", {}).get(env.adapter_id, {})
            if isinstance(ext, dict) and ext.get(rules.agent_extension_key) == obs.forwards_agent and event_id != env.event_id:
                out.append(event_id)
        return out

    def record(self, ref: RecordRef, located: str | None, path: tuple) -> set[str]:
        if ref.kind not in records.REVISION_TABLES:
            return set()
        data = records.body(self.q, ref.kind, ref.id, ref.revision)
        if data is None:
            self.ineligible[ref.id] = "record_unavailable"
            return set()
        if located is not None:
            holder = _field_parent(data, located)
            if isinstance(holder, dict) and isinstance(holder.get("evidence"), list):
                links = [EvidenceLink.model_validate(item) for item in holder["evidence"]]
            else:
                links = self._record_links(ref, data)
        else:
            links = self._record_links(ref, data)
        roots: set[str] = set()
        for link in links:
            if link.relation == "supports":
                roots |= self.link(link, path)
        return roots

    @staticmethod
    def _record_links(ref: RecordRef, data: dict[str, Any]) -> list[EvidenceLink]:
        if ref.kind == "claim":
            return [EvidenceLink.model_validate(item) for item in data.get("supports") or []]
        return [EvidenceLink.model_validate(item) for item in records._walk_links(data)]  # noqa: SLF001


def provenance_events(q: Any, link: EvidenceLink) -> set[str]:
    """Every non-telemetry event a link's provenance reaches (the roots a record link may name)."""
    walk = _Walk(q)
    walk.ref(link.ref, link.locator.field if link.locator is not None else None, ())
    return walk.reached


# --------------------------------------------------------------------------
# Counting


@dataclass(frozen=True)
class Lineage:
    """Root classes of one proposition's evidence, with everything that blocks corroboration."""

    support_classes: frozenset[str] = frozenset()
    contradict_classes: frozenset[str] = frozenset()
    unstable_classes: frozenset[str] = frozenset()
    support_roots: frozenset[str] = frozenset()  # audit only; never counted
    unresolved_roots: frozenset[str] = frozenset()
    conflicted_roots: frozenset[str] = frozenset()
    ineligible: tuple[tuple[str, str], ...] = ()
    cycles: int = 0
    incomplete: bool = False
    uncertain_proposition: bool = False

    @property
    def corroboration_blocked(self) -> bool:
        return bool(self.contradict_classes or self.unstable_classes or self.conflicted_roots or self.cycles or self.incomplete)

    @property
    def needs_revalidation(self) -> bool:
        """An unresolved source-identity conflict: dependent guidance needs revalidation and no caution."""
        return bool(self.conflicted_roots)


def _proposition_certain(proposition_key: Mapping[str, Any] | None) -> bool:
    try:
        PropositionKey.model_validate(proposition_key)
    except ValidationError:
        return False
    return True


def _classes(q: Any, roots: set[str], *, certain: bool) -> tuple[set[str], set[str], set[str]]:
    """(classes, unresolved roots, conflicted roots) for a set of root events."""
    classes: dict[str, Member] = {}
    unresolved: dict[str, OriginEventKey] = {}
    conflicted: set[str] = set()
    by_class: dict[str, list[Member]] = {}
    for event_id in sorted(roots):
        if _conflicted(q, event_id):
            conflicted.add(event_id)
            continue
        m = member(q, event_id)
        if m is None:
            env, _ = _envelope(q, event_id)
            if env is not None:
                unresolved[event_id] = origin_key(env)
            continue
        if m.resolution != "resolved":
            unresolved[event_id] = m.origin
            continue
        by_class.setdefault(m.class_id, []).append(m)
        classes[m.class_id] = m
    groups: dict[Any, list[str]] = {}
    for class_id, members in by_class.items():
        actors = {m.authority_actor for m in members if m.observation_kind == "user_declaration"}
        if not certain:
            group: Any = "uncertain"
        elif len(actors) == 1 and all(m.observation_kind == "user_declaration" for m in members):
            group = ("authority", next(iter(actors)))
        else:
            group = ("class", class_id)
        groups.setdefault(group, []).append(class_id)
    out = {min(ids, key=lambda c: _order(_canonical(q, c))) if len(ids) > 1 else ids[0] for ids in groups.values()}
    if out and not certain:
        out = {min(out, key=lambda c: _order(_canonical(q, c)))}
    if not out and unresolved:
        out = {root_class_id(min(unresolved.values(), key=_order))}  # missing descriptors form at most one class
    return out, set(unresolved), conflicted


def resolve(q: Any, evidence: Sequence[EvidenceLink], *, proposition_key: Mapping[str, Any] | None) -> Lineage:
    """Classes of the support and contradiction links of one scoped proposition (read-only)."""
    certain = _proposition_certain(proposition_key)
    walk = _Walk(q)
    support: set[str] = set()
    contra: set[str] = set()
    for link in evidence:
        if link.relation == "supports":
            support |= walk.link(link)
        elif link.relation == "contradicts":
            contra |= walk.link(link)
    support_classes, unresolved, conflicted = _classes(q, support, certain=certain)
    contradict_classes, c_unresolved, c_conflicted = _classes(q, contra, certain=certain)
    unstable = {c for c in support_classes if q.execute("SELECT 1 FROM root_classes WHERE root_class_id = ?", (c,)).fetchone() is not None and _unstable(q, c)}
    unstable |= support_classes & contradict_classes
    return Lineage(
        support_classes=frozenset(support_classes),
        contradict_classes=frozenset(contradict_classes),
        unstable_classes=frozenset(unstable),
        support_roots=frozenset(support),
        unresolved_roots=frozenset(unresolved | c_unresolved),
        conflicted_roots=frozenset(conflicted | c_conflicted),
        ineligible=tuple(sorted(walk.ineligible.items())),
        cycles=walk.cycles,
        incomplete=walk.incomplete,
        uncertain_proposition=not certain,
    )


def independent_roots(ctx: InstallationContext, evidence: Sequence[EvidenceLink], *, proposition_key: Mapping[str, Any] | None, store: Any | None = None) -> set[str]:
    """Canonical root-class IDs of the support links (DATA_CONTRACTS §11); never raw event IDs."""
    from recalith.storage.db import open_store

    own = store is None
    store = store or open_store(ctx, readonly=True)
    try:
        with store.read() as view:
            return set(resolve(view, evidence, proposition_key=proposition_key).support_classes)
    finally:
        if own:
            store.close()


def observed_at(q: Any, event_ids: Iterable[str]) -> str | None:
    """Latest observation time of these events (occurred, else recorded); never a discriminator."""
    latest = None
    for chunk in _chunks(sorted(set(event_ids))):
        marks = ",".join("?" for _ in chunk)
        row = q.execute(f"SELECT MAX(COALESCE(occurred_at, recorded_at)) FROM events WHERE event_id IN ({marks})", tuple(chunk)).fetchone()  # noqa: S608
        if row and row[0] and (latest is None or row[0] > latest):
            latest = row[0]
    return latest
