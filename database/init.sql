CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    time_start TIMESTAMPTZ NOT NULL,
    time_end TIMESTAMPTZ NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    CONSTRAINT events_time_order CHECK (time_end > time_start)
);

CREATE INDEX IF NOT EXISTS events_user_time_start_idx
    ON events (user_id, time_start);

CREATE INDEX IF NOT EXISTS events_user_time_end_idx
    ON events (user_id, time_end);
