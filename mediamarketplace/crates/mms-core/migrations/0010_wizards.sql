-- Setup Wizards: AI agent sessions, their transcripts and the proposals they make.
-- Proposals are applied only by an administrator; nothing here writes settings directly.
CREATE TABLE IF NOT EXISTS wizard_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    wizard TEXT NOT NULL,
    parent_id INTEGER REFERENCES wizard_sessions(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    brief TEXT NOT NULL DEFAULT '',
    context TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    checklist TEXT NOT NULL DEFAULT '[]',
    questions TEXT NOT NULL DEFAULT '[]',
    pending_tool_use TEXT NOT NULL DEFAULT '',
    plan TEXT NOT NULL DEFAULT '[]',
    error TEXT NOT NULL DEFAULT '',
    turns INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wizard_sessions_status ON wizard_sessions(status);

CREATE TABLE IF NOT EXISTS wizard_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES wizard_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wizard_messages_session ON wizard_messages(session_id);

CREATE TABLE IF NOT EXISTS wizard_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    session_id INTEGER NOT NULL REFERENCES wizard_sessions(id) ON DELETE CASCADE,
    wizard TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL,
    needs_input INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'proposed',
    result TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    applied_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_wizard_proposals_session ON wizard_proposals(session_id);
