-- Optional "sell through" mode: the CMS shop (WooCommerce or VirtueMart) takes the
-- money and the store grants access. Mappings between store products and shop products.
CREATE TABLE IF NOT EXISTS external_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    system TEXT NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,
    external_url TEXT NOT NULL DEFAULT '',
    synced_at TEXT NOT NULL,
    UNIQUE(system, product_id),
    UNIQUE(system, external_id)
);
CREATE INDEX IF NOT EXISTS idx_external_products_system ON external_products(system);

-- Every message the shop sent (orders, subscriptions), for the admin page and for support.
CREATE TABLE IF NOT EXISTS bridge_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    system TEXT NOT NULL,
    kind TEXT NOT NULL,
    external_id TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL
);
