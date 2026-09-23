-- Phase 3: commerce, private pages, site passes, API keys and outbound webhooks.
CREATE TABLE IF NOT EXISTS carts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    token      TEXT NOT NULL UNIQUE,
    user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
    coupon     TEXT,
    country    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS carts_user ON carts(user_id);

CREATE TABLE IF NOT EXISTS cart_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    cart_id    INTEGER NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity   INTEGER NOT NULL DEFAULT 1,
    added_at   TEXT NOT NULL,
    UNIQUE (cart_id, product_id)
);

CREATE TABLE IF NOT EXISTS coupons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    kind        TEXT NOT NULL CHECK (kind IN ('percent','fixed')),
    amount      INTEGER NOT NULL,
    currency    TEXT NOT NULL DEFAULT '',
    max_uses    INTEGER NOT NULL DEFAULT 0,
    uses        INTEGER NOT NULL DEFAULT 0,
    expires_at  TEXT,
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tax_rates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    country    TEXT NOT NULL,
    region     TEXT NOT NULL DEFAULT '',
    name       TEXT NOT NULL,
    rate_bp    INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (country, region)
);

CREATE TABLE IF NOT EXISTS orders (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid           TEXT NOT NULL UNIQUE,
    number         TEXT NOT NULL UNIQUE,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status         TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','paid','refunded','cancelled','failed')),
    currency       TEXT NOT NULL,
    subtotal_cents INTEGER NOT NULL DEFAULT 0,
    discount_cents INTEGER NOT NULL DEFAULT 0,
    tax_cents      INTEGER NOT NULL DEFAULT 0,
    total_cents    INTEGER NOT NULL DEFAULT 0,
    coupon         TEXT,
    country        TEXT NOT NULL DEFAULT '',
    tax_name       TEXT NOT NULL DEFAULT '',
    tax_rate_bp    INTEGER NOT NULL DEFAULT 0,
    gateway        TEXT NOT NULL DEFAULT '',
    external_id    TEXT,
    paid_at        TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_user ON orders(user_id, status);

CREATE TABLE IF NOT EXISTS order_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id  INTEGER REFERENCES products(id) ON DELETE SET NULL,
    title       TEXT NOT NULL,
    type        TEXT NOT NULL,
    unit_cents  INTEGER NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 1,
    total_cents INTEGER NOT NULL,
    settings    TEXT
);

CREATE TABLE IF NOT EXISTS payments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    gateway     TEXT NOT NULL,
    external_id TEXT,
    amount_cents INTEGER NOT NULL,
    currency    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','succeeded','failed','refunded')),
    raw         TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refunds (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id   INTEGER NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
    amount_cents INTEGER NOT NULL,
    external_id  TEXT,
    reason       TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS receipts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   INTEGER NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
    number     TEXT NOT NULL UNIQUE,
    year       INTEGER NOT NULL,
    html       TEXT NOT NULL,
    pdf        BLOB NOT NULL,
    issued_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid         TEXT NOT NULL UNIQUE,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id   INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    order_id     INTEGER REFERENCES orders(id) ON DELETE SET NULL,
    gateway      TEXT NOT NULL,
    external_id  TEXT,
    interval     TEXT NOT NULL DEFAULT 'month',
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','past_due','cancelled','ended')),
    period_end   TEXT,
    cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gateway_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    gateway     TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    payload     TEXT,
    received_at TEXT NOT NULL,
    UNIQUE (gateway, event_id)
);

CREATE TABLE IF NOT EXISTS private_pages (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid               TEXT NOT NULL UNIQUE,
    title              TEXT NOT NULL,
    content            TEXT NOT NULL DEFAULT '',
    agreement          TEXT NOT NULL DEFAULT '',
    agreement_version  INTEGER NOT NULL DEFAULT 1,
    signup_template    TEXT NOT NULL DEFAULT 'simple_cta',
    protection         TEXT NOT NULL DEFAULT 'public' CHECK (protection IN ('public','members','paid','paid_key','invite')),
    product_id         INTEGER REFERENCES products(id) ON DELETE SET NULL,
    incentive          TEXT NOT NULL DEFAULT '',
    quiz_question      TEXT NOT NULL DEFAULT '',
    quiz_answer        TEXT NOT NULL DEFAULT '',
    jurisdiction       TEXT NOT NULL DEFAULT '',
    min_age            INTEGER NOT NULL DEFAULT 0,
    status             TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','archived')),
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agreements (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid              TEXT NOT NULL UNIQUE,
    page_id           INTEGER NOT NULL REFERENCES private_pages(id) ON DELETE CASCADE,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agreement_version INTEGER NOT NULL,
    agreement_hash    TEXT NOT NULL,
    signer_name       TEXT NOT NULL,
    method            TEXT NOT NULL,
    signature         TEXT,
    confirmations     TEXT NOT NULL DEFAULT '',
    ip                TEXT NOT NULL DEFAULT '',
    user_agent        TEXT NOT NULL DEFAULT '',
    pdf               BLOB,
    status            TEXT NOT NULL DEFAULT 'signed' CHECK (status IN ('signed','revoked','superseded')),
    signed_at         TEXT NOT NULL,
    UNIQUE (page_id, user_id, agreement_version)
);

CREATE TABLE IF NOT EXISTS access_keys (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id    INTEGER NOT NULL REFERENCES private_pages(id) ON DELETE CASCADE,
    key_hash   TEXT NOT NULL UNIQUE,
    hint       TEXT NOT NULL,
    max_uses   INTEGER NOT NULL DEFAULT 1,
    uses       INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,
    status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','used','revoked')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS access_attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    subject    TEXT NOT NULL,
    page_id    INTEGER,
    ok         INTEGER NOT NULL,
    at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS access_attempts_subject ON access_attempts(subject, at);

CREATE TABLE IF NOT EXISTS lockouts (
    subject    TEXT PRIMARY KEY,
    count      INTEGER NOT NULL DEFAULT 1,
    until      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pass_notices (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    entitlement_id INTEGER NOT NULL,
    days_left  INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (entitlement_id, days_left)
);

CREATE TABLE IF NOT EXISTS api_keys (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    key_hash   TEXT NOT NULL UNIQUE,
    prefix     TEXT NOT NULL,
    scopes     TEXT NOT NULL DEFAULT 'read',
    last_used  TEXT,
    status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_endpoints (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    url        TEXT NOT NULL,
    secret     TEXT NOT NULL,
    events     TEXT NOT NULL DEFAULT '*',
    status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint_id INTEGER NOT NULL REFERENCES webhook_endpoints(id) ON DELETE CASCADE,
    event       TEXT NOT NULL,
    payload     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','delivered','failed')),
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_status INTEGER,
    last_error  TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
