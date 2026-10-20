-- Recalith migration 0010: intentional forgetting and suppression-aware restore (Task 16, decision 0017).
-- A forgotten or content-free quarantined task or episode keeps a head row
-- that points at a body-less marker revision (claims could already take those
-- statuses), so ``task_heads`` and ``episode_heads`` are rebuilt with the two
-- new head states (SQLite cannot alter a CHECK constraint; rows and indexes are
-- kept). ``tombstone_targets`` indexes every tombstone's target identifiers
-- (forgotten event and record IDs) so ingestion suppresses a replay of a known
-- source in its own transaction and restore can tell which tombstones a
-- snapshot lacks. It is derived from ``tombstones`` and holds opaque IDs only.

CREATE TABLE task_heads_0010 (
    task_id           TEXT PRIMARY KEY,
    revision          INTEGER NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('active', 'paused', 'completed', 'abandoned', 'linked', 'quarantined', 'forgotten')),
    workspace_id      TEXT NOT NULL REFERENCES workspaces(workspace_id),
    redirect_task_id  TEXT,
    last_activity_at  TEXT NOT NULL,
    FOREIGN KEY (task_id, revision) REFERENCES task_revisions(task_id, revision)
) STRICT;
INSERT INTO task_heads_0010 (task_id, revision, status, workspace_id, redirect_task_id, last_activity_at)
    SELECT task_id, revision, status, workspace_id, redirect_task_id, last_activity_at FROM task_heads;
DROP TABLE task_heads;
ALTER TABLE task_heads_0010 RENAME TO task_heads;
CREATE INDEX task_heads_activity ON task_heads (workspace_id, status, last_activity_at);

CREATE TABLE episode_heads_0010 (
    episode_id  TEXT PRIMARY KEY,
    revision    INTEGER NOT NULL,
    state       TEXT NOT NULL CHECK (state IN ('open', 'settled', 'archived', 'quarantined', 'forgotten')),
    task_id     TEXT NOT NULL,
    FOREIGN KEY (episode_id, revision) REFERENCES episode_revisions(episode_id, revision)
) STRICT;
INSERT INTO episode_heads_0010 (episode_id, revision, state, task_id)
    SELECT episode_id, revision, state, task_id FROM episode_heads;
DROP TABLE episode_heads;
ALTER TABLE episode_heads_0010 RENAME TO episode_heads;
CREATE INDEX episode_heads_task ON episode_heads (task_id, state);

CREATE TABLE tombstone_targets (
    target_id     TEXT PRIMARY KEY,
    tombstone_id  TEXT NOT NULL REFERENCES tombstones(tombstone_id),
    epoch         INTEGER NOT NULL CHECK (epoch >= 1)
) STRICT;
CREATE INDEX tombstone_targets_tombstone ON tombstone_targets (tombstone_id);
CREATE INDEX privacy_operations_status ON privacy_operations (status, created_at);
