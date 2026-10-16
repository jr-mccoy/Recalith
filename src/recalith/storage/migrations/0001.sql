-- Recalith migration 0001: the full minimal schema (DATA_CONTRACTS §10).
-- Later tasks populate features incrementally. Every table carrying record
-- bodies participates in forgetting. JSON columns hold canonical serialized,
-- validated DTOs; hot filters have typed columns. No JSON1 dependency.

CREATE TABLE installation_meta (
    singleton        INTEGER PRIMARY KEY CHECK (singleton = 1),
    project_id       TEXT NOT NULL,
    installation_id  TEXT NOT NULL,
    engine_version   TEXT NOT NULL,
    schema_version   INTEGER NOT NULL,
    release_profile  TEXT NOT NULL CHECK (release_profile IN ('claude_preview', 'full')),
    store_revision   INTEGER NOT NULL DEFAULT 0 CHECK (store_revision >= 0),
    guidance_epoch   INTEGER NOT NULL DEFAULT 0 CHECK (guidance_epoch >= 0),
    policy_revision  INTEGER NOT NULL DEFAULT 1 CHECK (policy_revision >= 1),
    tombstone_epoch  INTEGER NOT NULL DEFAULT 0 CHECK (tombstone_epoch >= 0),
    created_at       TEXT NOT NULL
) STRICT;

CREATE TABLE workspaces (
    workspace_id      TEXT PRIMARY KEY,
    canonical_root    TEXT NOT NULL,
    root_identity     TEXT NOT NULL,
    branch_metadata   TEXT NOT NULL DEFAULT '{}',
    attachment_state  TEXT NOT NULL CHECK (attachment_state IN ('primary', 'attached', 'detached')),
    registered_at     TEXT NOT NULL,
    rebound_at        TEXT
) STRICT;

CREATE TABLE sessions (
    session_id       TEXT PRIMARY KEY,
    adapter_id       TEXT NOT NULL,
    host_session_id  TEXT NOT NULL,
    workspace_id     TEXT NOT NULL REFERENCES workspaces(workspace_id),
    state            TEXT NOT NULL CHECK (state IN ('active', 'stopped', 'ended', 'abandoned')),
    started_at       TEXT,
    ended_at         TEXT,
    UNIQUE (adapter_id, host_session_id)
) STRICT;

CREATE TABLE capture_sources (
    source_id        TEXT PRIMARY KEY,
    adapter_id       TEXT NOT NULL,
    session_id       TEXT REFERENCES sessions(session_id),
    source_kind      TEXT NOT NULL,
    locator          TEXT NOT NULL,
    durable_cursor   TEXT NOT NULL DEFAULT '{}',
    ingested_cursor  TEXT NOT NULL DEFAULT '{}',
    coverage         TEXT NOT NULL DEFAULT '{}',
    registered_at    TEXT NOT NULL,
    UNIQUE (adapter_id, locator)
) STRICT;

CREATE TABLE events (
    event_id          TEXT PRIMARY KEY,
    adapter_id        TEXT NOT NULL,
    source_event_key  TEXT NOT NULL,
    payload_digest    TEXT NOT NULL,
    source_sequence   INTEGER,
    commit_sequence   INTEGER NOT NULL UNIQUE,
    kind              TEXT NOT NULL,
    channel           TEXT NOT NULL,
    authority         TEXT NOT NULL,
    session_id        TEXT NOT NULL,
    workspace_id      TEXT NOT NULL REFERENCES workspaces(workspace_id),
    task_hint         TEXT,
    occurred_at       TEXT,
    recorded_at       TEXT NOT NULL,
    envelope          TEXT NOT NULL,
    payload           TEXT,
    payload_state     TEXT NOT NULL DEFAULT 'available' CHECK (payload_state IN ('available', 'capsule_only', 'expired', 'forgotten')),
    retention_after   TEXT,
    UNIQUE (adapter_id, source_event_key)
) STRICT;
CREATE INDEX events_session ON events (session_id, commit_sequence);
CREATE INDEX events_kind ON events (kind, commit_sequence);

CREATE TABLE source_conflicts (
    conflict_id        TEXT PRIMARY KEY,
    original_event_id  TEXT NOT NULL REFERENCES events(event_id),
    adapter_id         TEXT NOT NULL,
    source_event_key   TEXT NOT NULL,
    payload_digest     TEXT NOT NULL,
    scrubbed_payload   TEXT,
    coverage           TEXT NOT NULL DEFAULT '{}',
    first_seen_at      TEXT NOT NULL,
    state              TEXT NOT NULL CHECK (state IN ('unresolved', 'resolved', 'forgotten')),
    UNIQUE (adapter_id, source_event_key, payload_digest)
) STRICT;

CREATE TABLE root_classes (
    root_class_id        TEXT PRIMARY KEY,
    canonical_namespace  TEXT NOT NULL,
    canonical_key        TEXT NOT NULL,
    equivalence_reasons  TEXT NOT NULL DEFAULT '[]'
) STRICT;

CREATE TABLE root_members (
    source_namespace  TEXT NOT NULL,
    source_event_key  TEXT NOT NULL,
    root_class_id     TEXT NOT NULL REFERENCES root_classes(root_class_id),
    descriptor        TEXT,
    PRIMARY KEY (source_namespace, source_event_key)
) STRICT;

CREATE TABLE root_aliases (
    alias_id          TEXT PRIMARY KEY,
    root_class_id     TEXT NOT NULL REFERENCES root_classes(root_class_id),
    merged_at_revision INTEGER NOT NULL
) STRICT;

CREATE TABLE task_boundaries (
    boundary_id      TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL,
    after_event_id   TEXT,
    source_task_id   TEXT NOT NULL,
    reason           TEXT NOT NULL,
    state            TEXT NOT NULL CHECK (state IN ('pending', 'confirmed', 'rejected', 'linked')),
    policy_revision  INTEGER NOT NULL,
    body             TEXT NOT NULL
) STRICT;

CREATE TABLE task_binding_revisions (
    binding_id             TEXT NOT NULL,
    revision               INTEGER NOT NULL CHECK (revision >= 1),
    event_id               TEXT NOT NULL REFERENCES events(event_id),
    task_id                TEXT NOT NULL,
    binding                TEXT NOT NULL CHECK (binding IN ('provisional', 'confirmed')),
    boundary_id            TEXT,
    assigned_by_operation  TEXT NOT NULL,
    previous_revision      INTEGER,
    PRIMARY KEY (binding_id, revision)
) STRICT;

CREATE TABLE task_binding_heads (
    event_id    TEXT PRIMARY KEY REFERENCES events(event_id),
    binding_id  TEXT NOT NULL,
    revision    INTEGER NOT NULL,
    task_id     TEXT NOT NULL
) STRICT;
CREATE INDEX task_binding_heads_task ON task_binding_heads (task_id);

CREATE TABLE failure_triggers (
    trigger_id              TEXT PRIMARY KEY,
    task_id                 TEXT NOT NULL,
    failure_event_id        TEXT NOT NULL REFERENCES events(event_id),
    action_family_digest    TEXT,
    subsequent_event_count  INTEGER NOT NULL DEFAULT 0,
    due_at                  TEXT NOT NULL,
    state                   TEXT NOT NULL CHECK (state IN ('pending', 'resolved', 'due'))
) STRICT;
CREATE INDEX failure_triggers_family ON failure_triggers (task_id, action_family_digest, state);

CREATE TABLE executables (
    executable_id           TEXT PRIMARY KEY,
    workspace_id            TEXT NOT NULL REFERENCES workspaces(workspace_id),
    identity                TEXT NOT NULL,
    fingerprint             TEXT,
    fingerprint_changed_at  TEXT,
    changed_store_revision  INTEGER
) STRICT;

CREATE TABLE environment_observations (
    observation_id          TEXT PRIMARY KEY,
    workspace_id            TEXT NOT NULL REFERENCES workspaces(workspace_id),
    key                     TEXT NOT NULL CHECK (key IN ('os', 'arch', 'python_version', 'node_version', 'ci')),
    value                   TEXT NOT NULL,
    executable_id           TEXT,
    source_kind             TEXT NOT NULL CHECK (source_kind IN ('operator_config', 'certified_tool', 'adapter_platform')),
    source_event_id         TEXT,
    config_revision         INTEGER,
    observed_at             TEXT NOT NULL,
    fingerprint             TEXT NOT NULL,
    executable_fingerprint  TEXT,
    freshness               TEXT NOT NULL CHECK (freshness IN ('current', 'stale', 'unknown'))
) STRICT;

CREATE TABLE review_batches (
    batch_id       TEXT PRIMARY KEY,
    origin_job_id  TEXT,
    review_job_id  TEXT NOT NULL,
    body           TEXT NOT NULL,
    created_at     TEXT NOT NULL
) STRICT;

CREATE TABLE task_revisions (
    task_id                 TEXT NOT NULL,
    revision                INTEGER NOT NULL CHECK (revision >= 1),
    status                  TEXT NOT NULL,
    body                    TEXT,
    created_store_revision  INTEGER NOT NULL,
    PRIMARY KEY (task_id, revision)
) STRICT;

CREATE TABLE task_heads (
    task_id           TEXT PRIMARY KEY,
    revision          INTEGER NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('active', 'paused', 'completed', 'abandoned', 'linked')),
    workspace_id      TEXT NOT NULL REFERENCES workspaces(workspace_id),
    redirect_task_id  TEXT,
    last_activity_at  TEXT NOT NULL,
    FOREIGN KEY (task_id, revision) REFERENCES task_revisions(task_id, revision)
) STRICT;

CREATE TABLE episode_revisions (
    episode_id              TEXT NOT NULL,
    revision                INTEGER NOT NULL CHECK (revision >= 1),
    state                   TEXT NOT NULL,
    body                    TEXT,
    created_store_revision  INTEGER NOT NULL,
    PRIMARY KEY (episode_id, revision)
) STRICT;

CREATE TABLE episode_heads (
    episode_id  TEXT PRIMARY KEY,
    revision    INTEGER NOT NULL,
    state       TEXT NOT NULL CHECK (state IN ('open', 'settled', 'archived')),
    task_id     TEXT NOT NULL,
    FOREIGN KEY (episode_id, revision) REFERENCES episode_revisions(episode_id, revision)
) STRICT;

CREATE TABLE claim_revisions (
    claim_id                TEXT NOT NULL,
    revision                INTEGER NOT NULL CHECK (revision >= 1),
    kind                    TEXT NOT NULL,
    status                  TEXT NOT NULL,
    body                    TEXT,
    created_store_revision  INTEGER NOT NULL,
    PRIMARY KEY (claim_id, revision)
) STRICT;

CREATE TABLE claim_heads (
    claim_id              TEXT PRIMARY KEY,
    revision              INTEGER NOT NULL,
    kind                  TEXT NOT NULL CHECK (kind IN ('fact', 'decision', 'preference', 'failure_lesson', 'procedure')),
    status                TEXT NOT NULL CHECK (status IN ('candidate', 'active', 'disputed', 'superseded', 'invalidated', 'archived', 'quarantined', 'forgotten')),
    freshness             TEXT NOT NULL CHECK (freshness IN ('current', 'needs_revalidation', 'unknown')),
    strength              TEXT NOT NULL CHECK (strength IN ('weak', 'supported', 'corroborated')),
    basis                 TEXT NOT NULL CHECK (basis IN ('observed', 'user_declared', 'inferred')),
    review_due_at         TEXT,
    action_family_digest  TEXT,
    FOREIGN KEY (claim_id, revision) REFERENCES claim_revisions(claim_id, revision)
) STRICT;
CREATE INDEX claim_heads_status ON claim_heads (status, kind, freshness);
CREATE INDEX claim_heads_family ON claim_heads (action_family_digest);

CREATE TABLE evidence_links (
    link_id          INTEGER PRIMARY KEY,
    owner_kind       TEXT NOT NULL CHECK (owner_kind IN ('task', 'episode', 'claim')),
    owner_id         TEXT NOT NULL,
    owner_revision   INTEGER NOT NULL,
    target_kind      TEXT NOT NULL CHECK (target_kind IN ('event', 'task', 'episode', 'claim', 'capsule')),
    target_id        TEXT NOT NULL,
    target_revision  INTEGER NOT NULL,
    relation         TEXT NOT NULL CHECK (relation IN ('supports', 'contradicts', 'context')),
    root_event_ids   TEXT NOT NULL DEFAULT '[]',
    locator          TEXT,
    mapping          TEXT
) STRICT;
CREATE INDEX evidence_links_owner ON evidence_links (owner_kind, owner_id, owner_revision);
CREATE INDEX evidence_links_target ON evidence_links (target_kind, target_id);

CREATE TABLE evidence_capsules (
    capsule_id        TEXT PRIMARY KEY,
    source_namespace  TEXT NOT NULL,
    source_event_key  TEXT NOT NULL,
    content_digest    TEXT NOT NULL,
    body              TEXT
) STRICT;

CREATE TABLE dependencies (
    claim_id         TEXT NOT NULL,
    claim_revision   INTEGER NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN ('file', 'config', 'environment', 'claim')),
    key              TEXT NOT NULL,
    fingerprint      TEXT,
    record_id        TEXT,
    record_revision  INTEGER,
    FOREIGN KEY (claim_id, claim_revision) REFERENCES claim_revisions(claim_id, revision)
) STRICT;
CREATE INDEX dependencies_key ON dependencies (kind, key);

CREATE TABLE relations (
    source_id          TEXT NOT NULL,
    target_id          TEXT NOT NULL,
    relation           TEXT NOT NULL CHECK (relation IN ('supports', 'contradicts', 'derived_from', 'supersedes', 'applies_to', 'related_to')),
    created_revision   INTEGER NOT NULL,
    PRIMARY KEY (source_id, target_id, relation)
) STRICT;

CREATE TABLE jobs (
    job_id            TEXT PRIMARY KEY,
    kind              TEXT NOT NULL,
    state             TEXT NOT NULL CHECK (state IN ('pending', 'leased', 'waiting_review', 'waiting_budget', 'completed', 'failed', 'cancelled')),
    idempotency_key   TEXT NOT NULL UNIQUE,
    priority          INTEGER NOT NULL,
    due_at            TEXT NOT NULL,
    attempt           INTEGER NOT NULL DEFAULT 0,
    lease_owner       TEXT,
    lease_generation  INTEGER NOT NULL DEFAULT 0,
    lease_until       TEXT,
    budget_pool       TEXT NOT NULL CHECK (budget_pool IN ('ordinary', 'protected', 'none')),
    review_priority   TEXT,
    body              TEXT NOT NULL
) STRICT;
CREATE INDEX jobs_due ON jobs (state, due_at, job_id);

CREATE TABLE proposals (
    proposal_id      TEXT PRIMARY KEY,
    job_id           TEXT NOT NULL REFERENCES jobs(job_id),
    input_digest     TEXT NOT NULL,
    read_set_digest  TEXT NOT NULL,
    body             TEXT,
    retention_after  TEXT
) STRICT;

CREATE TABLE operations (
    operation_id     TEXT PRIMARY KEY,
    job_id           TEXT,
    proposal_id      TEXT,
    atomic_group_id  TEXT,
    actor            TEXT NOT NULL,
    kind             TEXT NOT NULL,
    inputs           TEXT NOT NULL DEFAULT '{}',
    changed          TEXT NOT NULL DEFAULT '[]',
    reason           TEXT,
    causal_root      TEXT,
    store_revision   INTEGER NOT NULL,
    created_at       TEXT NOT NULL
) STRICT;

-- Full profile only; reserved and unpopulated in preview (never reported verified).
CREATE TABLE revision_chain (
    sequence         INTEGER PRIMARY KEY,
    previous_hash    TEXT NOT NULL,
    operation_id     TEXT,
    row_digests      TEXT NOT NULL,
    purge_marker     INTEGER NOT NULL DEFAULT 0,
    tombstone_epoch  INTEGER NOT NULL,
    entry_hash       TEXT NOT NULL
) STRICT;

CREATE TABLE privacy_operations (
    privacy_operation_id  TEXT PRIMARY KEY,
    phase                 TEXT NOT NULL,
    remaining             TEXT NOT NULL DEFAULT '{}',
    new_epoch             INTEGER NOT NULL,
    status                TEXT NOT NULL CHECK (status IN ('running', 'cleanup_pending', 'completed')),
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
) STRICT;

CREATE TABLE deliveries (
    delivery_id           TEXT PRIMARY KEY,
    attempt_id            TEXT NOT NULL UNIQUE,
    session_id            TEXT NOT NULL,
    task_id               TEXT,
    purpose               TEXT NOT NULL,
    state                 TEXT NOT NULL CHECK (state IN ('emitted', 'uncertain')),
    packet_digest         TEXT NOT NULL,
    fence_store_revision  INTEGER NOT NULL,
    guidance_epoch        INTEGER NOT NULL,
    policy_revision       INTEGER NOT NULL,
    tombstone_epoch       INTEGER NOT NULL,
    estimated_tokens      INTEGER NOT NULL,
    substitution_tokens   INTEGER NOT NULL DEFAULT 0,
    generated_at          TEXT NOT NULL,
    emitted_at            TEXT,
    items                 TEXT NOT NULL
) STRICT;
CREATE INDEX deliveries_session ON deliveries (session_id);

CREATE TABLE outcome_links (
    link_id             INTEGER PRIMARY KEY,
    delivery_id         TEXT NOT NULL REFERENCES deliveries(delivery_id),
    label               TEXT NOT NULL,
    observed_event_ids  TEXT NOT NULL DEFAULT '[]',
    created_at          TEXT NOT NULL
) STRICT;

CREATE TABLE tombstones (
    tombstone_id    TEXT PRIMARY KEY,
    epoch           INTEGER NOT NULL CHECK (epoch >= 1),
    target_ids      TEXT NOT NULL,
    source_digests  TEXT NOT NULL DEFAULT '[]',
    deletion_scope  TEXT NOT NULL CHECK (deletion_scope IN ('record', 'task', 'source_range', 'saved_query')),
    created_at      TEXT NOT NULL
) STRICT;

CREATE TABLE imports (
    import_id      TEXT PRIMARY KEY,
    source_digest  TEXT NOT NULL,
    origin         TEXT NOT NULL,
    schema_versions TEXT NOT NULL,
    created_at     TEXT NOT NULL
) STRICT;

CREATE TABLE exports (
    export_id        TEXT PRIMARY KEY,
    manifest         TEXT NOT NULL,
    visibility       TEXT NOT NULL,
    tombstone_epoch  INTEGER NOT NULL,
    created_at       TEXT NOT NULL
) STRICT;

CREATE TABLE backups (
    backup_id        TEXT PRIMARY KEY,
    manifest         TEXT NOT NULL,
    tombstone_epoch  INTEGER NOT NULL,
    state            TEXT NOT NULL CHECK (state IN ('verified', 'failed', 'deleted')),
    created_at       TEXT NOT NULL
) STRICT;

CREATE TABLE provider_usage (
    reservation_id  TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL,
    invocation_id   TEXT NOT NULL,
    utc_day         TEXT NOT NULL,
    purpose         TEXT NOT NULL,
    state           TEXT NOT NULL CHECK (state IN ('reserved', 'charged', 'released')),
    provider_id     TEXT,
    model           TEXT,
    body            TEXT NOT NULL
) STRICT;
CREATE INDEX provider_usage_day ON provider_usage (utc_day, state);

CREATE TABLE context_views (
    view_id                TEXT PRIMARY KEY,
    workspace_id           TEXT NOT NULL,
    task_id                TEXT,
    purpose                TEXT NOT NULL,
    source_store_revision  INTEGER NOT NULL,
    guidance_epoch         INTEGER NOT NULL,
    policy_revision        INTEGER NOT NULL,
    tombstone_epoch        INTEGER NOT NULL,
    condition_results      TEXT NOT NULL DEFAULT '{}',
    input_fingerprints     TEXT NOT NULL DEFAULT '{}',
    body                   TEXT NOT NULL
) STRICT;
CREATE INDEX context_views_key ON context_views (workspace_id, task_id, purpose);

-- Disposable candidate index tied to store revision; FTS5 is optional (Task 11).
CREATE TABLE lexical_index (
    term             TEXT NOT NULL,
    record_kind      TEXT NOT NULL,
    record_id        TEXT NOT NULL,
    record_revision  INTEGER NOT NULL,
    store_revision   INTEGER NOT NULL
) STRICT;
CREATE INDEX lexical_index_term ON lexical_index (term);
