-- Recalith migration 0006: consolidation and autonomous revision (Task 10, decision 0012).
-- ``claim_rechecks`` records why a claim needs revalidation, one row per
-- claim, reason and triggering observation: a certified later success of a
-- failure lesson's action family (FailureRecheck ``later_success`` or
-- ``order_unknown``), a changed dependency, an unresolved source conflict, a
-- due review or a consolidation group. ``deferred`` rows wait for a
-- candidate's activation; ``pending`` rows hold the claim's
-- ``needs_revalidation`` freshness (reviews and consolidation leave freshness
-- alone) until a revalidation result whose read set includes the row's event
-- and the still-current claim revision settles them. ``pending_supersessions``
-- holds an explicit replacement of active guidance until the replacement's own
-- review activates it; activation and supersession then commit together.
-- ``intent_questions`` is one content-free question per unresolved conflict
-- between user declarations. ``artifact_writes`` indexes certified writes and
-- deletions by path (the file dependency index's change source).
-- ``planner_state`` is the deterministic planner's consolidation clock. These
-- tables hold identities, digests and reason codes only.

CREATE TABLE claim_rechecks (
    recheck_id      TEXT PRIMARY KEY,
    claim_id        TEXT NOT NULL,
    claim_revision  INTEGER,
    reason          TEXT NOT NULL CHECK (reason IN ('later_success', 'order_unknown', 'dependency_changed', 'source_conflict', 'review_due', 'consolidation')),
    event_id        TEXT,
    detail          TEXT NOT NULL DEFAULT '{}',
    state           TEXT NOT NULL CHECK (state IN ('pending', 'deferred', 'cleared')),
    outcome         TEXT,
    job_id          TEXT,
    causal_root     TEXT,
    created_at      TEXT NOT NULL,
    settled_at      TEXT
) STRICT;
CREATE INDEX claim_rechecks_claim ON claim_rechecks (claim_id, state);
CREATE INDEX claim_rechecks_state ON claim_rechecks (state, reason);

CREATE TABLE pending_supersessions (
    replacement_id   TEXT NOT NULL,
    target_id        TEXT NOT NULL,
    target_revision  INTEGER NOT NULL CHECK (target_revision >= 1),
    operation_id     TEXT NOT NULL,
    state            TEXT NOT NULL CHECK (state IN ('pending', 'applied', 'stale', 'withdrawn')),
    created_at       TEXT NOT NULL,
    decided_at       TEXT,
    PRIMARY KEY (replacement_id, target_id)
) STRICT;
CREATE INDEX pending_supersessions_target ON pending_supersessions (target_id, state);

CREATE TABLE intent_questions (
    question_id      TEXT PRIMARY KEY,
    claim_ids        TEXT NOT NULL,
    proposition_key  TEXT NOT NULL,
    state            TEXT NOT NULL CHECK (state IN ('open', 'resolved')),
    created_at       TEXT NOT NULL,
    resolved_at      TEXT
) STRICT;
CREATE INDEX intent_questions_state ON intent_questions (state);

CREATE TABLE artifact_writes (
    event_id         TEXT NOT NULL REFERENCES events(event_id),
    path             TEXT NOT NULL,
    commit_sequence  INTEGER NOT NULL,
    PRIMARY KEY (event_id, path)
) STRICT;
CREATE INDEX artifact_writes_path ON artifact_writes (path, commit_sequence);

CREATE TABLE planner_state (
    singleton         INTEGER PRIMARY KEY CHECK (singleton = 1),
    consolidated_at   TEXT,
    settled_episodes  INTEGER NOT NULL DEFAULT 0,
    evidence_mark     INTEGER NOT NULL DEFAULT 0
) STRICT;
INSERT INTO planner_state (singleton) VALUES (1);

CREATE INDEX dependencies_record ON dependencies (kind, record_id);
CREATE INDEX claim_heads_due ON claim_heads (status, review_due_at);
