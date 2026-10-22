-- Recalith migration 0011: the hook's bounded lexical lookup (Task 11 follow-up, decision 0021).
-- ``lookup_candidates`` holds, per workspace, one row for every live claim
-- head the worker has reconciled: the claim revision, the digest of the
-- workspace environment it was rendered with, the guidance/policy/tombstone
-- epochs of its read snapshot, whether its text is volatile (disputed, or
-- freshness other than current), the IDs its content derives from, the
-- payload states of the events it quotes and, when the claim is servable in
-- that workspace, the pre-rendered candidate (else a null body).
-- ``lookup_postings`` holds one (workspace, term, claim, static score) row
-- per term of a servable row's candidate; the hook reads at most a bounded
-- number of them per prompt through ``lookup_postings_rank``.
-- ``projection_state`` gains the epochs at which the lookup was last
-- complete. Both tables are disposable projections rebuilt from the
-- authoritative heads: writing them never advances the store revision or the
-- guidance epoch, and forgetting purges their rows with the records they
-- render.

CREATE TABLE lookup_candidates (
    workspace_id        TEXT NOT NULL,
    claim_id            TEXT NOT NULL,
    claim_revision      INTEGER NOT NULL,
    environment_digest  TEXT NOT NULL,
    volatile            INTEGER NOT NULL CHECK (volatile IN (0, 1)),
    guidance_epoch      INTEGER NOT NULL,
    policy_revision     INTEGER NOT NULL,
    tombstone_epoch     INTEGER NOT NULL,
    cited_ids           TEXT NOT NULL DEFAULT '[]',
    quoted_states       TEXT NOT NULL DEFAULT '{}',
    body                TEXT,
    PRIMARY KEY (workspace_id, claim_id)
) STRICT;

CREATE TABLE lookup_postings (
    workspace_id  TEXT NOT NULL,
    term          TEXT NOT NULL,
    base          REAL NOT NULL,
    claim_id      TEXT NOT NULL,
    PRIMARY KEY (workspace_id, term, claim_id)
) STRICT;

CREATE INDEX lookup_postings_rank ON lookup_postings (workspace_id, term, base DESC, claim_id);
CREATE INDEX lookup_postings_claim ON lookup_postings (workspace_id, claim_id);

ALTER TABLE projection_state ADD COLUMN lookup_guidance_epoch INTEGER NOT NULL DEFAULT -1;
ALTER TABLE projection_state ADD COLUMN lookup_policy_revision INTEGER NOT NULL DEFAULT -1;
ALTER TABLE projection_state ADD COLUMN lookup_tombstone_epoch INTEGER NOT NULL DEFAULT -1;
