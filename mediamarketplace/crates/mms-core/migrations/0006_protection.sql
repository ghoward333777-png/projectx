-- Phase 4: forensic watermarking, copyright protection, violations and takedowns.
CREATE TABLE IF NOT EXISTS mark_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        INTEGER NOT NULL UNIQUE,
    uuid        TEXT NOT NULL UNIQUE,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    media_id    INTEGER REFERENCES media(id) ON DELETE SET NULL,
    product_id  INTEGER REFERENCES products(id) ON DELETE SET NULL,
    level       INTEGER NOT NULL DEFAULT 2,
    kind        TEXT NOT NULL,
    ip          TEXT NOT NULL DEFAULT '',
    user_agent  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS mark_sessions_user ON mark_sessions(user_id, media_id);

CREATE TABLE IF NOT EXISTS copyright_scans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id    INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    service     TEXT NOT NULL,
    mode        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','done','failed','manual')),
    result      TEXT,
    matches     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS violations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid          TEXT NOT NULL UNIQUE,
    media_id      INTEGER REFERENCES media(id) ON DELETE SET NULL,
    product_id    INTEGER REFERENCES products(id) ON DELETE SET NULL,
    url           TEXT NOT NULL,
    host          TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT 'manual',
    evidence_note TEXT NOT NULL DEFAULT '',
    evidence_hash TEXT NOT NULL DEFAULT '',
    mark_session  INTEGER REFERENCES mark_sessions(id) ON DELETE SET NULL,
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','notice_sent','removed','disputed','ignored')),
    notice_pdf    BLOB,
    notice_sent_at TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS violation_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    violation_id INTEGER NOT NULL REFERENCES violations(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,
    note         TEXT NOT NULL DEFAULT '',
    at           TEXT NOT NULL
);
