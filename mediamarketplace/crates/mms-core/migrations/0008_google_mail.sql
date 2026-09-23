-- Phase 6 and 7: Google Business Profile, outgoing mail log, GDPR requests, backups.
CREATE TABLE IF NOT EXISTS google_accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL DEFAULT '',
    refresh_token TEXT NOT NULL,
    access_token  TEXT NOT NULL DEFAULT '',
    expires_at    TEXT NOT NULL DEFAULT '',
    account_name  TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS google_locations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    address     TEXT NOT NULL DEFAULT '',
    place_id    TEXT NOT NULL DEFAULT '',
    maps_url    TEXT NOT NULL DEFAULT '',
    synced_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS google_posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid         TEXT NOT NULL UNIQUE,
    location     TEXT NOT NULL,
    summary      TEXT NOT NULL,
    cta_type     TEXT NOT NULL DEFAULT '',
    cta_url      TEXT NOT NULL DEFAULT '',
    media_url    TEXT NOT NULL DEFAULT '',
    scheduled_at TEXT,
    status       TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','scheduled','published','failed')),
    remote_name  TEXT NOT NULL DEFAULT '',
    error        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS google_reviews (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    remote_name  TEXT NOT NULL UNIQUE,
    location     TEXT NOT NULL,
    reviewer     TEXT NOT NULL DEFAULT '',
    rating       INTEGER NOT NULL DEFAULT 0,
    comment      TEXT NOT NULL DEFAULT '',
    reply        TEXT NOT NULL DEFAULT '',
    draft_reply  TEXT NOT NULL DEFAULT '',
    reply_status TEXT NOT NULL DEFAULT 'none' CHECK (reply_status IN ('none','drafted','approved','posted','failed')),
    reviewed_at  TEXT NOT NULL DEFAULT '',
    synced_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mail_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    to_addr    TEXT NOT NULL,
    subject    TEXT NOT NULL,
    kind       TEXT NOT NULL,
    status     TEXT NOT NULL,
    error      TEXT NOT NULL DEFAULT '',
    sent_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS privacy_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('export','erase')),
    status      TEXT NOT NULL DEFAULT 'done',
    detail      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
