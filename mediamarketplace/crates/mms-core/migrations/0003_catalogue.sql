-- Phase 1: categories, ratings, bookings, playback sessions.
CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    slug       TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    icon       TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_categories (
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    PRIMARY KEY (product_id, category_id)
);

CREATE TABLE IF NOT EXISTS ratings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stars      INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5),
    review     TEXT,
    status     TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    created_at TEXT NOT NULL,
    UNIQUE (product_id, user_id)
);

CREATE TABLE IF NOT EXISTS bookings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    slot_start TEXT NOT NULL,
    slot_end   TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','confirmed','cancelled')),
    created_at TEXT NOT NULL,
    UNIQUE (product_id, slot_start)
);

CREATE TABLE IF NOT EXISTS playback_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid        TEXT NOT NULL UNIQUE,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    media_id    INTEGER REFERENCES media(id) ON DELETE SET NULL,
    player      TEXT NOT NULL DEFAULT '',
    position_ms INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    started_at  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    ended_at    TEXT
);
CREATE INDEX IF NOT EXISTS playback_user ON playback_sessions(user_id, product_id);
