-- Recalith migration 0009: retention with live pins and verified backups (Task 15 core, decision 0016).
-- ``claim_rechecks`` gains the reason ``support_lost``: a live claim whose
-- required evidence payload is no longer available (an explicit forgetting
-- override or a reactivation over expired support) is downgraded and queued
-- for revalidation through the ordinary recheck path. SQLite cannot alter a
-- CHECK constraint, so the table is rebuilt with its rows and indexes.
-- ``backups`` records where each verified backup was published, the digest
-- of its manifest (the restore form's ``--expected-digest``) and its size, so
-- bounded backup retention can delete exactly what it created.
-- ``retention_state`` is the singleton the worker's retention step keeps: when
-- it last swept, its last content-free report (counts, never payloads) and the
-- tombstone epoch of the latest ledger copy it wrote. The indexes serve the
-- age sweep (payload state and capture time), the delivery-metadata sweep and
-- the backup sweep.

CREATE TABLE claim_rechecks_0009 (
    recheck_id      TEXT PRIMARY KEY,
    claim_id        TEXT NOT NULL,
    claim_revision  INTEGER,
    reason          TEXT NOT NULL CHECK (reason IN ('later_success', 'order_unknown', 'dependency_changed', 'source_conflict', 'review_due', 'consolidation', 'support_lost')),
    event_id        TEXT,
    detail          TEXT NOT NULL DEFAULT '{}',
    state           TEXT NOT NULL CHECK (state IN ('pending', 'deferred', 'cleared')),
    outcome         TEXT,
    job_id          TEXT,
    causal_root     TEXT,
    created_at      TEXT NOT NULL,
    settled_at      TEXT
) STRICT;
INSERT INTO claim_rechecks_0009 (recheck_id, claim_id, claim_revision, reason, event_id, detail, state, outcome, job_id, causal_root, created_at, settled_at)
    SELECT recheck_id, claim_id, claim_revision, reason, event_id, detail, state, outcome, job_id, causal_root, created_at, settled_at FROM claim_rechecks;
DROP TABLE claim_rechecks;
ALTER TABLE claim_rechecks_0009 RENAME TO claim_rechecks;
CREATE INDEX claim_rechecks_claim ON claim_rechecks (claim_id, state);
CREATE INDEX claim_rechecks_state ON claim_rechecks (state, reason);

ALTER TABLE backups ADD COLUMN location TEXT;
ALTER TABLE backups ADD COLUMN manifest_digest TEXT;
ALTER TABLE backups ADD COLUMN bytes INTEGER;
CREATE INDEX backups_state ON backups (state, created_at);

CREATE TABLE retention_state (
    singleton     INTEGER PRIMARY KEY CHECK (singleton = 1),
    swept_at      TEXT,
    report        TEXT NOT NULL DEFAULT '{}',
    ledger_epoch  INTEGER NOT NULL DEFAULT -1
) STRICT;
INSERT INTO retention_state (singleton) VALUES (1);

CREATE INDEX events_retention ON events (payload_state, recorded_at);
CREATE INDEX deliveries_generated ON deliveries (generated_at);
CREATE INDEX outcome_links_delivery ON outcome_links (delivery_id);
CREATE INDEX evidence_links_owner_target ON evidence_links (target_kind, target_id, owner_kind);
