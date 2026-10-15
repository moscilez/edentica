CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL, created TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS session_user_lookup ON sessions(user_id);
CREATE INDEX IF NOT EXISTS session_expiry ON sessions(expires);
CREATE TABLE IF NOT EXISTS user_suspensions (
    user_id TEXT PRIMARY KEY REFERENCES users(id), reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS learning_materials (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL,
    kind TEXT NOT NULL, size INTEGER NOT NULL CHECK (size BETWEEN 0 AND 5000000),
    text TEXT NOT NULL, truncated INTEGER NOT NULL DEFAULT 0,
    created TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS material_owner ON learning_materials(user_id, created DESC);
CREATE TABLE IF NOT EXISTS program_projects (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),
    document JSONB NOT NULL CHECK (jsonb_typeof(document)='object'),
    updated TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS program_owner_updated ON program_projects(owner, updated DESC);
CREATE TABLE IF NOT EXISTS program_events (
    sequence BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES program_projects(id),
    owner TEXT NOT NULL REFERENCES users(id), action TEXT NOT NULL,
    detail JSONB NOT NULL, created TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS event_project ON program_events(project_id, sequence DESC);
INSERT INTO schema_migrations(version) VALUES (1) ON CONFLICT DO NOTHING;
