-- Phase 2: widgets, templates, brand kit, colour schemes, site template applications.
CREATE TABLE IF NOT EXISTS widgets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid          TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    definition    TEXT NOT NULL,
    template_slug TEXT,
    custom_css    TEXT NOT NULL DEFAULT '',
    theme         TEXT NOT NULL DEFAULT 'auto',
    scheme        TEXT NOT NULL DEFAULT 'default',
    status        TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','archived')),
    version       INTEGER NOT NULL DEFAULT 1,
    created_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS widget_versions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    widget_id  INTEGER NOT NULL REFERENCES widgets(id) ON DELETE CASCADE,
    version    INTEGER NOT NULL,
    definition TEXT NOT NULL,
    custom_css TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (widget_id, version)
);

-- User-saved widget templates (built-in ones are embedded in the binary).
CREATE TABLE IF NOT EXISTS user_templates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    slug       TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    category   TEXT NOT NULL,
    definition TEXT NOT NULL,
    custom_css TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS colour_schemes (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    slug    TEXT NOT NULL UNIQUE,
    name    TEXT NOT NULL,
    vars    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Records what a site template created so it can be rolled back.
CREATE TABLE IF NOT EXISTS site_applications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    template    TEXT NOT NULL,
    widget_ids  TEXT NOT NULL,
    scheme_slug TEXT,
    applied_at  TEXT NOT NULL,
    rolled_back INTEGER NOT NULL DEFAULT 0
);
