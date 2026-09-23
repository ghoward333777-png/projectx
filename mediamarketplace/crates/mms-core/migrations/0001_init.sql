-- MediaMarketplace Studio: initial schema (SQLite).
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid          TEXT NOT NULL UNIQUE,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name          TEXT NOT NULL DEFAULT '',
    password_hash TEXT,
    role          TEXT NOT NULL DEFAULT 'customer' CHECK (role IN ('admin','staff','customer')),
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- Links a local user to an identity on a bridged host (WordPress / Joomla) for single sign-on.
CREATE TABLE IF NOT EXISTS user_identities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    host        TEXT NOT NULL,
    external_id TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (host, external_id)
);

CREATE TABLE IF NOT EXISTS settings (
    name       TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT NOT NULL
);

-- Bridged sites allowed to embed content and sign SSO tokens.
CREATE TABLE IF NOT EXISTS bridge_sites (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid       TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    host       TEXT NOT NULL CHECK (host IN ('wordpress','joomla','other')),
    origin     TEXT NOT NULL,
    secret_enc TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media_folders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    slug       TEXT NOT NULL UNIQUE,
    parent_id  INTEGER REFERENCES media_folders(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid           TEXT NOT NULL UNIQUE,
    type           TEXT NOT NULL CHECK (type IN ('image','video','audio','pdf')),
    original_path  TEXT NOT NULL,
    private        INTEGER NOT NULL DEFAULT 0,
    mime           TEXT NOT NULL,
    bytes          INTEGER NOT NULL DEFAULT 0,
    width          INTEGER,
    height         INTEGER,
    duration_ms    INTEGER,
    hash_sha256    TEXT NOT NULL,
    phash          TEXT,
    title          TEXT,
    alt            TEXT,
    caption        TEXT,
    tags           TEXT,
    metadata       TEXT,
    variants       TEXT,
    thumbnail_path TEXT,
    folder_id      INTEGER REFERENCES media_folders(id) ON DELETE SET NULL,
    uploader_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    status         TEXT NOT NULL DEFAULT 'processing' CHECK (status IN ('processing','ready','failed')),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS media_type ON media(type);
CREATE INDEX IF NOT EXISTS media_folder ON media(folder_id);
CREATE INDEX IF NOT EXISTS media_hash ON media(hash_sha256);

CREATE TABLE IF NOT EXISTS products (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid             TEXT NOT NULL UNIQUE,
    slug             TEXT NOT NULL UNIQUE,
    type             TEXT NOT NULL CHECK (type IN ('video','audio','image','pdf','live','private_page','site_pass','meeting','consultation','external')),
    title            TEXT NOT NULL,
    description      TEXT,
    price_cents      INTEGER NOT NULL DEFAULT 0,
    currency         TEXT NOT NULL DEFAULT 'USD',
    media_id         INTEGER REFERENCES media(id) ON DELETE SET NULL,
    preview_media_id INTEGER REFERENCES media(id) ON DELETE SET NULL,
    settings         TEXT,
    featured         INTEGER NOT NULL DEFAULT 0,
    rating_avg       REAL NOT NULL DEFAULT 0,
    rating_count     INTEGER NOT NULL DEFAULT 0,
    purchases        INTEGER NOT NULL DEFAULT 0,
    views            INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','archived')),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS products_type ON products(type);
CREATE INDEX IF NOT EXISTS products_status ON products(status, featured);

CREATE TABLE IF NOT EXISTS entitlements (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    scope      TEXT NOT NULL CHECK (scope IN ('product','page','site','category')),
    scope_ref  TEXT NOT NULL DEFAULT '',
    source     TEXT NOT NULL CHECK (source IN ('order','subscription','pass','manual','free')),
    source_ref TEXT NOT NULL,
    starts_at  TEXT NOT NULL,
    ends_at    TEXT,
    status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','expired','revoked')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source, source_ref, user_id, scope, scope_ref)
);
CREATE INDEX IF NOT EXISTS entitlements_user ON entitlements(user_id, status);

CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id     INTEGER,
    action       TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id   TEXT,
    ip           TEXT,
    user_agent   TEXT,
    details      TEXT,
    logged_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_action ON audit_log(action, logged_at);

CREATE TABLE IF NOT EXISTS jobs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    type       TEXT NOT NULL,
    args       TEXT,
    status     TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed')),
    attempts   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    run_at     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_due ON jobs(status, run_at);
