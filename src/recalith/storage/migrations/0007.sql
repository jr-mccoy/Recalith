-- Recalith migration 0007: retrieval projections (Task 11, decision 0013).
-- ``projection_state`` is the singleton the worker's projection step keeps:
-- which lexical backend is in use (``fts5`` when the SQLite build provides it,
-- else the deterministic ``tokens`` index), the store revision the lexical and
-- structural index covers, and the guidance/policy/tombstone epochs and store
-- revision the published ``context_views`` were built from. ``retrieval_docs``
-- is one row per indexed live record head: its eligibility hot columns
-- (status, workspace and task scope) so status and scope mismatches are
-- excluded before any candidate cap, and its lexical terms for ranking. When
-- the SQLite build has FTS5 the worker also keeps the virtual table
-- ``lexical_fts`` (created at runtime after capability detection, rowid =
-- the ``retrieval_docs`` rowid) as the lexical candidate source. Both are
-- disposable projections rebuilt from the authoritative heads; writing them
-- never advances the store revision or the guidance epoch. Their rows hold
-- identities, terms and rendered bodies derived from servable records, so
-- Task 16 forgetting must purge them with the records they came from.

CREATE TABLE projection_state (
    singleton                INTEGER PRIMARY KEY CHECK (singleton = 1),
    lexical_backend          TEXT NOT NULL CHECK (lexical_backend IN ('fts5', 'tokens')),
    indexed_store_revision   INTEGER NOT NULL DEFAULT 0,
    views_store_revision     INTEGER NOT NULL DEFAULT -1,
    views_guidance_epoch     INTEGER NOT NULL DEFAULT -1,
    views_policy_revision    INTEGER NOT NULL DEFAULT -1,
    views_tombstone_epoch    INTEGER NOT NULL DEFAULT -1,
    updated_at               TEXT NOT NULL
) STRICT;

CREATE TABLE retrieval_docs (
    record_kind      TEXT NOT NULL CHECK (record_kind IN ('task', 'episode', 'claim')),
    record_id        TEXT NOT NULL,
    record_revision  INTEGER NOT NULL,
    status           TEXT NOT NULL,
    workspace_ids    TEXT NOT NULL DEFAULT '[]',
    task_ids         TEXT NOT NULL DEFAULT '[]',
    terms            TEXT NOT NULL DEFAULT '[]',
    term_count       INTEGER NOT NULL DEFAULT 0,
    store_revision   INTEGER NOT NULL,
    PRIMARY KEY (record_kind, record_id)
) STRICT;

CREATE INDEX lexical_index_record ON lexical_index (record_kind, record_id);
CREATE INDEX claim_revisions_store ON claim_revisions (created_store_revision);
CREATE INDEX task_revisions_store ON task_revisions (created_store_revision);
CREATE INDEX episode_revisions_store ON episode_revisions (created_store_revision);
