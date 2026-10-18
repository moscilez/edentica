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
ALTER TABLE users ADD COLUMN IF NOT EXISTS login TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'methodist' CHECK (role IN ('methodist','expert','learner'));
UPDATE users SET login=lower(email) WHERE login IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS user_login_unique ON users(lower(login));
CREATE TABLE IF NOT EXISTS model_connections (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL, base_url TEXT NOT NULL, model TEXT NOT NULL, encrypted_key TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true, output_limit INTEGER NOT NULL DEFAULT 6000,
    created TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(user_id,name)
);
CREATE TABLE IF NOT EXISTS publications (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES program_projects(id),
    owner TEXT NOT NULL REFERENCES users(id), expert TEXT NOT NULL REFERENCES users(id),
    digest TEXT NOT NULL, visibility TEXT NOT NULL CHECK (visibility IN ('public','private')),
    title TEXT NOT NULL, description TEXT NOT NULL, snapshot JSONB NOT NULL,
    created TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(project_id,digest), CHECK (owner <> expert)
);
CREATE INDEX IF NOT EXISTS publication_catalog ON publications(visibility,created DESC);
CREATE TABLE IF NOT EXISTS program_reviews (
    project_id TEXT PRIMARY KEY REFERENCES program_projects(id) ON DELETE CASCADE,
    expert TEXT NOT NULL REFERENCES users(id), digest TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','changes_requested')),
    reviewed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS review_comments (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES program_projects(id) ON DELETE CASCADE,
    author TEXT NOT NULL REFERENCES users(id), scope TEXT NOT NULL, message TEXT NOT NULL,
    resolved BOOLEAN NOT NULL DEFAULT false, created TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS course_reviews (
    publication_id TEXT NOT NULL REFERENCES publications(id), user_id TEXT NOT NULL REFERENCES users(id),
    rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5), comment TEXT NOT NULL,
    created TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(publication_id,user_id)
);
CREATE TABLE IF NOT EXISTS study_groups (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), title TEXT NOT NULL,
    created TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS group_members (
    group_id TEXT NOT NULL REFERENCES study_groups(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id), PRIMARY KEY(group_id,user_id)
);
CREATE TABLE IF NOT EXISTS enrollments (
    id TEXT PRIMARY KEY, publication_id TEXT NOT NULL REFERENCES publications(id),
    user_id TEXT NOT NULL REFERENCES users(id), assigned_by TEXT REFERENCES users(id),
    group_id TEXT REFERENCES study_groups(id), deadline TIMESTAMPTZ, required BOOLEAN NOT NULL DEFAULT false,
    created TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(publication_id,user_id)
);
CREATE TABLE IF NOT EXISTS lesson_progress (
    enrollment_id TEXT NOT NULL REFERENCES enrollments(id) ON DELETE CASCADE,
    lesson_id TEXT NOT NULL, completed BOOLEAN NOT NULL DEFAULT false, score INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0, updated TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(enrollment_id,lesson_id)
);
CREATE TABLE IF NOT EXISTS agent_messages (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES program_projects(id) ON DELETE CASCADE,
    author TEXT NOT NULL REFERENCES users(id), role TEXT NOT NULL, message TEXT NOT NULL,
    proposal JSONB, created TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS llm_cache (
    owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, digest TEXT NOT NULL,
    value JSONB NOT NULL, created TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(owner,digest)
);
INSERT INTO schema_migrations(version) VALUES (2) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS llm_usage_events (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, skill TEXT NOT NULL,
    input_tokens BIGINT NOT NULL CHECK(input_tokens>=0), output_tokens BIGINT NOT NULL CHECK(output_tokens>=0),
    usage_known BOOLEAN NOT NULL, status TEXT NOT NULL CHECK(status IN ('completed','failed')),
    created TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS llm_usage_owner_created ON llm_usage_events(owner,created);
CREATE TABLE IF NOT EXISTS llm_usage_baselines (
    project_id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    input_tokens BIGINT NOT NULL, output_tokens BIGINT NOT NULL, calls BIGINT NOT NULL,
    created TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Old counters have no reliable daily timestamps. Keep them separate, never
-- attribute the whole course's historical consumption to its last edit date.
INSERT INTO llm_usage_baselines(project_id,owner,input_tokens,output_tokens,calls)
SELECT p.id,p.owner,
    greatest(0,CASE WHEN jsonb_typeof(document->'usage'->'inputTokens')='number'
        THEN least((document->'usage'->>'inputTokens')::numeric,9000000000000)::bigint ELSE 0 END-coalesce(e.incoming,0)),
    greatest(0,CASE WHEN jsonb_typeof(document->'usage'->'outputTokens')='number'
        THEN least((document->'usage'->>'outputTokens')::numeric,9000000000000)::bigint ELSE 0 END-coalesce(e.outgoing,0)),
    greatest(0,CASE WHEN jsonb_typeof(document->'usage'->'calls')='number'
        THEN least((document->'usage'->>'calls')::numeric,9000000000000)::bigint ELSE 0 END-coalesce(e.calls,0))
FROM program_projects p LEFT JOIN (
    SELECT project_id,sum(input_tokens) AS incoming,sum(output_tokens) AS outgoing,count(*) AS calls
    FROM llm_usage_events GROUP BY project_id
) e ON e.project_id=p.id ON CONFLICT(project_id) DO NOTHING;
INSERT INTO schema_migrations(version) VALUES (3) ON CONFLICT DO NOTHING;
