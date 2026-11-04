-- Raw OHLCV Cache (unconverted, auto-adjusted prices matching yfinance auto_adjust=True)
CREATE TABLE IF NOT EXISTS ticker_ohlcv_daily (
    ticker          TEXT            NOT NULL,
    date            DATE            NOT NULL,
    open            DOUBLE PRECISION,
    high            DOUBLE PRECISION,
    low             DOUBLE PRECISION,
    close           DOUBLE PRECISION NOT NULL,
    volume          DOUBLE PRECISION,
    source          TEXT            NOT NULL DEFAULT 'yfinance',  -- yfinance | stooq | synthetic
    fetched_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_date_desc
    ON ticker_ohlcv_daily (ticker, date DESC);

-- Ticker Metadata with a two-tier freshness policy (JSONB)
CREATE TABLE IF NOT EXISTS ticker_metadata (
    ticker              TEXT        PRIMARY KEY,
    info_json           JSONB       NOT NULL,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    quote_fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Thundering herd protection lock
CREATE TABLE IF NOT EXISTS ticker_fetch_locks (
    ticker          TEXT        PRIMARY KEY,
    locked_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_by       TEXT
);
