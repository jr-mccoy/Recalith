-- Recalith migration 0008: delivery accounting (Task 12b, decision 0015).
-- Hooks never write SQLite: a delivery reaches ``deliveries`` only when the
-- worker ingests its ``memory_delivered`` receipt event (emitted or
-- uncertain), in that event's ingestion transaction, as bookkeeping (the
-- store revision advances, the guidance epoch does not). One row per attempt
-- (``attempt_id`` is unique since migration 1): an emitted receipt upgrades an
-- uncertain row for the same attempt and an uncertain receipt never
-- downgrades an emitted one, so an attempt is charged exactly once. The new
-- columns carry the receipt's host identity, the compaction cycle a
-- restoration answers (restore once per key), the captured event whose hook
-- delivered, when the final fence held, whether output was already in flight
-- when a change committed after that fence, and the receipt event itself.
-- ``outcome_links`` gains a uniqueness rule so a replayed follow-up event
-- cannot link twice. Rows hold identities, digests and counts only.

ALTER TABLE deliveries ADD COLUMN host_id TEXT NOT NULL DEFAULT '';
ALTER TABLE deliveries ADD COLUMN restoration_key TEXT;
ALTER TABLE deliveries ADD COLUMN trigger_event_id TEXT;
ALTER TABLE deliveries ADD COLUMN fenced_at TEXT;
ALTER TABLE deliveries ADD COLUMN in_flight_change INTEGER;
ALTER TABLE deliveries ADD COLUMN receipt_event_id TEXT;
CREATE INDEX deliveries_session_state ON deliveries (session_id, state);
CREATE INDEX deliveries_trigger ON deliveries (trigger_event_id);
CREATE UNIQUE INDEX outcome_links_once ON outcome_links (delivery_id, label, observed_event_ids);
