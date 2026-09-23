-- Phase 5: currency rates and charge-currency records.
CREATE TABLE IF NOT EXISTS currency_rates (
    code       TEXT PRIMARY KEY,
    rate       REAL NOT NULL,
    fetched_at TEXT NOT NULL
);
ALTER TABLE orders ADD COLUMN base_currency TEXT NOT NULL DEFAULT '';
ALTER TABLE orders ADD COLUMN fx_rate REAL NOT NULL DEFAULT 1;
