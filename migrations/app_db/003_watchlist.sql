-- Watchlist Tickers Table
CREATE TABLE IF NOT EXISTS watchlist_tickers (
    ticker          TEXT PRIMARY KEY,
    name            TEXT,
    asset_class     TEXT DEFAULT 'Equity',
    notes           TEXT,
    added_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active       BOOLEAN NOT NULL DEFAULT true
);

CREATE INDEX IF NOT EXISTS idx_watchlist_active ON watchlist_tickers (is_active);
