-- Recalith migration 0005: claim admission, review batches and failure debounce (Task 9, decision 0011).
-- ``review_requests`` records which application scheduled each review job:
-- the origin extraction job (or the service submission of a typed
-- declaration), the code-assigned origin class and the stable partition
-- index. ``review_outcomes`` keeps one exact, content-free outcome per
-- reviewed (or deferred) candidate revision: admitted, revise, rejected,
-- review capacity, or the reason a verdict could not count (missing,
-- duplicate, foreign, stale, refused) and deferral of a candidate too large
-- to review safely. ``failure_triggers`` gains the bookkeeping its
-- deterministic six-event / ten-minute debounce needs, and
-- ``trigger_cursor`` the last reduced commit sequence it has examined.

CREATE TABLE review_requests (
    review_job_id    TEXT PRIMARY KEY REFERENCES jobs(job_id),
    origin_job_id    TEXT,
    submission_id    TEXT,
    origin           TEXT NOT NULL CHECK (origin IN ('extracted', 'typed_declaration', 'operator_declaration', 'operator_correction')),
    partition_index  INTEGER NOT NULL CHECK (partition_index >= 0),
    created_at       TEXT NOT NULL
) STRICT;
CREATE INDEX review_requests_origin ON review_requests (origin_job_id);

CREATE TABLE review_outcomes (
    outcome_id      TEXT PRIMARY KEY,
    claim_id        TEXT NOT NULL,
    claim_revision  INTEGER NOT NULL CHECK (claim_revision >= 1),
    batch_id        TEXT,
    review_job_id   TEXT,
    outcome         TEXT NOT NULL CHECK (outcome IN ('admitted', 'revise', 'rejected', 'capacity', 'missing', 'duplicate', 'foreign', 'stale', 'refused', 'deferred')),
    reason_code     TEXT NOT NULL,
    recorded_at     TEXT NOT NULL
) STRICT;
CREATE INDEX review_outcomes_claim ON review_outcomes (claim_id, claim_revision);
CREATE INDEX review_batches_job ON review_batches (review_job_id, created_at);

ALTER TABLE failure_triggers ADD COLUMN failure_sequence INTEGER NOT NULL DEFAULT 0;
ALTER TABLE failure_triggers ADD COLUMN failure_at TEXT NOT NULL DEFAULT '';
ALTER TABLE failure_triggers ADD COLUMN due_reason TEXT CHECK (due_reason IS NULL OR due_reason IN ('count', 'time'));
ALTER TABLE failure_triggers ADD COLUMN resolved_by TEXT;
ALTER TABLE failure_triggers ADD COLUMN job_id TEXT;
CREATE INDEX failure_triggers_state ON failure_triggers (state, due_at);

CREATE TABLE trigger_cursor (
    singleton        INTEGER PRIMARY KEY CHECK (singleton = 1),
    commit_sequence  INTEGER NOT NULL
) STRICT;
INSERT INTO trigger_cursor (singleton, commit_sequence) VALUES (1, 0);
