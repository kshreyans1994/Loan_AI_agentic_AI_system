-- Long-term memory: durable facts about a user, recalled across sessions.
-- Distinct from `applications` (one row per session/application) — this
-- table is keyed by user_id and survives across many sessions/applications.
CREATE TABLE IF NOT EXISTS user_memory_facts (
    id           SERIAL PRIMARY KEY,
    user_id       TEXT NOT NULL,
    fact           TEXT NOT NULL,
    category        TEXT NOT NULL CHECK (category IN ('profile', 'application_history', 'preference')),
    confidence       NUMERIC DEFAULT 1.0,
    created_at        TIMESTAMPTZ DEFAULT now(),
    -- Prevent unbounded duplicate facts from repeated saves of the same info
    UNIQUE (user_id, fact)
);

CREATE INDEX IF NOT EXISTS user_memory_facts_user_id_idx ON user_memory_facts (user_id);

-- Rolling conversation summaries — one row per completed session, so long-
-- term recall doesn't require replaying full transcripts. Summarization
-- keeps this bounded regardless of how long/many past sessions a user has.
CREATE TABLE IF NOT EXISTS session_summaries (
    id            SERIAL PRIMARY KEY,
    user_id        TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    summary          TEXT NOT NULL,
    created_at        TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS session_summaries_user_id_idx ON session_summaries (user_id);
