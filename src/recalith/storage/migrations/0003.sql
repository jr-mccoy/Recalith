-- Recalith migration 0003: tasks, bindings and connected episodes (Task 6, decision 0008).
-- Binding heads carry the event's commit sequence and session so explicit
-- ranges, contiguity and episode ranges are index lookups. ``tool_calls`` joins
-- a tool result to its call by tool_call_id across splits and sessions.
-- ``working_cursor``, ``working_sessions`` and ``working_tasks`` are the typed
-- reducer's deterministic bookkeeping (reduction cursor, per-session detection
-- state, per-task observed path clusters and open episode range). They are
-- derived from events and bindings, never served, and never advance guidance.

ALTER TABLE task_binding_heads ADD COLUMN commit_sequence INTEGER;
ALTER TABLE task_binding_heads ADD COLUMN session_id TEXT;
CREATE INDEX task_binding_heads_task_seq ON task_binding_heads (task_id, commit_sequence);
CREATE INDEX task_binding_heads_session ON task_binding_heads (session_id, commit_sequence);
CREATE INDEX task_binding_revisions_event ON task_binding_revisions (event_id, revision);
CREATE INDEX task_boundaries_session ON task_boundaries (session_id, state);
CREATE INDEX task_heads_activity ON task_heads (workspace_id, status, last_activity_at);
CREATE INDEX episode_heads_task ON episode_heads (task_id, state);

CREATE TABLE tool_calls (
    adapter_id       TEXT NOT NULL,
    tool_call_id     TEXT NOT NULL,
    start_event_id   TEXT REFERENCES events(event_id),
    finish_event_id  TEXT REFERENCES events(event_id),
    PRIMARY KEY (adapter_id, tool_call_id)
) STRICT;
CREATE INDEX tool_calls_start ON tool_calls (start_event_id);
CREATE INDEX tool_calls_finish ON tool_calls (finish_event_id);

CREATE TABLE working_cursor (
    singleton        INTEGER PRIMARY KEY CHECK (singleton = 1),
    commit_sequence  INTEGER NOT NULL DEFAULT 0 CHECK (commit_sequence >= 0)
) STRICT;
INSERT INTO working_cursor (singleton, commit_sequence) VALUES (1, 0);

CREATE TABLE working_sessions (
    session_id  TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL,
    body        TEXT NOT NULL
) STRICT;

CREATE TABLE working_tasks (
    task_id  TEXT PRIMARY KEY,
    body     TEXT NOT NULL
) STRICT;
