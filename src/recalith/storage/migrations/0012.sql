-- Recalith migration 0012: contradiction rechecks and observed file bytes (decisions 0032, 0033).
-- ``claim_rechecks`` gains the reason ``contradiction``: evidence attached to
-- live guidance as ``contradicts`` makes it need revalidation, as SYSTEM_SPEC
-- §3.5 lists. SQLite cannot alter a CHECK constraint, so the table is rebuilt
-- with its rows and indexes (as in 0009).
-- ``file_observations`` records, per live certified read, the SHA-256 of the
-- bytes it read, taken in the read's ingestion transaction and only while
-- nothing can have changed them since (decision 0033). A file dependency
-- resolves to the bytes its evidence observed, not to whatever the file holds
-- when a claim is admitted minutes later. Fingerprints only, never content;
-- forgetting purges the rows of the events it purges.

CREATE TABLE claim_rechecks_0012 (
    recheck_id      TEXT PRIMARY KEY,
    claim_id        TEXT NOT NULL,
    claim_revision  INTEGER,
    reason          TEXT NOT NULL CHECK (reason IN ('later_success', 'order_unknown', 'dependency_changed', 'source_conflict', 'review_due', 'consolidation', 'support_lost', 'contradiction')),
    event_id        TEXT,
    detail          TEXT NOT NULL DEFAULT '{}',
    state           TEXT NOT NULL CHECK (state IN ('pending', 'deferred', 'cleared')),
    outcome         TEXT,
    job_id          TEXT,
    causal_root     TEXT,
    created_at      TEXT NOT NULL,
    settled_at      TEXT
) STRICT;
INSERT INTO claim_rechecks_0012 (recheck_id, claim_id, claim_revision, reason, event_id, detail, state, outcome, job_id, causal_root, created_at, settled_at)
    SELECT recheck_id, claim_id, claim_revision, reason, event_id, detail, state, outcome, job_id, causal_root, created_at, settled_at FROM claim_rechecks;
DROP TABLE claim_rechecks;
ALTER TABLE claim_rechecks_0012 RENAME TO claim_rechecks;
CREATE INDEX claim_rechecks_claim ON claim_rechecks (claim_id, state);
CREATE INDEX claim_rechecks_state ON claim_rechecks (state, reason);

CREATE TABLE file_observations (
    event_id         TEXT NOT NULL,
    path             TEXT NOT NULL,
    fingerprint      TEXT NOT NULL,
    commit_sequence  INTEGER NOT NULL,
    PRIMARY KEY (event_id, path)
) STRICT;
CREATE INDEX file_observations_path ON file_observations (path, commit_sequence);
