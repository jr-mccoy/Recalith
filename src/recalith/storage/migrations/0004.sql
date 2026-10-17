-- Recalith migration 0004: evidence lineage and root classes (Task 8, decision 0010).
-- Ingestion registers every eligible root event (an authenticated user
-- statement or a certified tool result without ``derived_from``) under its
-- canonical origin key. ``root_tokens`` holds the exact equivalence keys
-- (origin identity, artifact snapshot, experiment signature, unresolved
-- experiment family); members sharing a token are one class, so the classes
-- are the transitive closure over the whole store. A class ID is ``root_`` +
-- SHA-256 of its lexicographically least canonical origin key; when a merge or
-- a new least member changes it, the old ID stays in ``root_aliases``. These
-- tables hold identities and digests only, no event content.

CREATE TABLE root_event_members (
    event_id          TEXT PRIMARY KEY REFERENCES events(event_id),
    source_namespace  TEXT NOT NULL,
    source_event_key  TEXT NOT NULL,
    observation_kind  TEXT NOT NULL CHECK (observation_kind IN ('user_declaration', 'tool_result', 'artifact_snapshot')),
    authority_actor   TEXT,
    outcome           TEXT,
    resolution        TEXT NOT NULL CHECK (resolution IN ('resolved', 'unresolved'))
) STRICT;
CREATE INDEX root_event_members_origin ON root_event_members (source_namespace, source_event_key);

CREATE TABLE root_tokens (
    token          TEXT PRIMARY KEY,
    reason         TEXT NOT NULL,
    root_class_id  TEXT NOT NULL REFERENCES root_classes(root_class_id)
) STRICT;
CREATE INDEX root_tokens_class ON root_tokens (root_class_id);
CREATE INDEX root_members_class ON root_members (root_class_id);
CREATE INDEX root_aliases_class ON root_aliases (root_class_id);
