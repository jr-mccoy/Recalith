-- Recalith migration 0002: mutation application (Task 5, decision 0007).
-- Persisted proposals keep the read set they were produced under and the
-- digest their operation IDs derive from. Operation rows name their local
-- ref and proposal digest. Claim heads index the exact-duplicate content key
-- (kind, proposition, proposition key, scope, conditions); evidence-root
-- identity is compared on the head's support links.

ALTER TABLE proposals ADD COLUMN proposal_digest TEXT;
ALTER TABLE proposals ADD COLUMN read_set TEXT;
CREATE INDEX proposals_job ON proposals (job_id);

ALTER TABLE operations ADD COLUMN local_ref TEXT;
ALTER TABLE operations ADD COLUMN proposal_digest TEXT;
CREATE INDEX operations_job ON operations (job_id, kind);
CREATE INDEX operations_kind ON operations (kind, store_revision);

ALTER TABLE claim_heads ADD COLUMN content_key TEXT;
CREATE INDEX claim_heads_content ON claim_heads (content_key);
