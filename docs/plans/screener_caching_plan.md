# Screener Caching & Robustness Plan (v2 Final + Unified Fetcher)

This plan implements a shared, durable cache layer in Supabase for ticker price series (OHLCV) and fundamental metadata. It resolves performance bottlenecks on Render, handles rate limits gracefully with cached fallbacks, speeds up Screener/Performance loads to **<300ms** on warm hits, and **unifies the price fetching infrastructure** across the entire backend.

All changes are restricted to the FastAPI backend (`backend/`). The Streamlit app remains completely untouched.

---

## Proposed Changes

### 1. Supabase Schema Update (New Tables DDL)

#### [NEW] [002_screener_cache.sql](file:///c:/Users/divit/Desktop/Finance%20Tool/migrations/app_db/002_screener_cache.sql)
```sql
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
```

---

### 2. Consolidated Price Ingestion Infrastructure

#### [NEW] [price_fetcher.py](file:///c:/Users/divit/Desktop/Finance%20Tool/backend/services/price_fetcher.py)
A unified, low-level data fetcher module shared across the recalculation engine and the screener:
* Move `_fetch_stooq` (PDR & CSV) and `_fetch_yahoo` from `engine.py` into this module.
* Upgrade these functions to return full **OHLCV DataFrames** (Open, High, Low, Close, Volume) instead of only a Close series.
* Implement a shared pence-to-pound multiplier cleanse helper that scales all price columns (`Open`, `High`, `Low`, `Close`) uniformly.
* Expose `fetch_ohlcv_raw(ticker: str, start_date: datetime) -> tuple[pd.DataFrame, str]`: Handles format conversions, tries Stooq first, falls back to Yahoo, applies the price cleanse, and returns the DataFrame plus the source tag.

#### [MODIFY] [engine.py](file:///c:/Users/divit/Desktop/Finance%20Tool/backend/services/engine.py)
* Remove the duplicate low-level fetch methods (`_fetch_stooq`, `_fetch_stooq_pdr`, `_fetch_stooq_csv`, `_fetch_yahoo`, `_to_stooq`).
* Refactor `fetch_portfolio_history_and_currency` to call `price_fetcher.fetch_ohlcv_raw` under the hood, extract the `"Close"` series from the returned DataFrame, and continue with its base-currency and FX operations as normal.

---

### 3. Backend Service (Storage Layer)

#### [MODIFY] [storage.py](file:///c:/Users/divit/Desktop/Finance%20Tool/backend/services/storage.py)
Implement database read/writes for the new caching tables:
* `save_ticker_ohlcv(ticker: str, df: pd.DataFrame, source='yfinance')`: Upsert OHLCV data. Ensure `synthetic` (Stooq fallback) rows do not overwrite existing high-quality `yfinance` records.
* `load_ticker_ohlcv(ticker: str, start_date: datetime) -> pd.DataFrame`: Load prices returning an OHLCV multi-index DataFrame.
* `get_latest_ohlcv_date(ticker: str) -> date | None`: Fast lookup to check cache currency.
* `save_ticker_metadata(ticker: str, info: dict)`: Store the full metadata dictionary.
* `load_ticker_metadata(ticker: str) -> dict | None`: Retrieve metadata if younger than 30 days (structural) / 24 hours (quote-sensitive fields).
* `try_acquire_fetch_lock(ticker: str, owner: str) -> bool` / `release_fetch_lock(ticker: str)`: Mutex lock helpers.

---

### 4. Backend Service (Screener Logic)

#### [MODIFY] [screener.py](file:///c:/Users/divit/Desktop/Finance%20Tool/backend/services/screener.py)
Refactor `fetch_screener_data` to integrate caching:
1. Lookup metadata from `ticker_metadata`. If missing or stale (>24h for quotes/30d for structural), fetch from `yf.Ticker(t).info` and save.
2. Check `ticker_ohlcv_daily` for existing dates. 
3. If dates are complete, serve from DB.
4. If missing/stale, run an incremental download using `price_fetcher.fetch_ohlcv_raw` (fetching only from the last stored date to today).
5. If a wider period is requested (e.g. 5y requested but only 2y stored), trigger a backfill fetch.
6. Serve cached prices/metadata as a fallback if the live fetch fails (rate-limited/Render offline).
7. Optimize `get_ticker_activity` to accept pre-fetched info dictionary to eliminate the duplicate `yf.Ticker` call.

---

### 5. API Router & FX Cache

#### [MODIFY] [screener.py](file:///c:/Users/divit/Desktop/Finance%20Tool/backend/routers/screener.py)
* Refactor FX downloads (`GBPUSD=X`, `EURGBP=X`) to use the standard cache pipeline (`load_ticker_ohlcv` / `save_ticker_ohlcv`) rather than fetching live on every routing call.
* Pass the fetched metadata dictionary from the router to `get_ticker_activity` to achieve a 100% warm request path.

---

### 6. Proactive Warming (Scheduler)

#### [MODIFY] [scheduler.py](file:///c:/Users/divit/Desktop/Finance%20Tool/backend/scheduler.py)
Add a post-recalculation cache warmer task:
* Scan for held tickers, benchmark components, and recent exited tickers.
* Fetch/update their OHLCV and metadata in the database cache during the nightly scheduler run, ensuring daytime users hit warm cache rows instantly.

---

## Verification Plan

### Automated Tests (`scratch/test_screener_cache.py`)
1. **Cold Fetch:** Measure first load speed for a new ticker (2-4 seconds) and check database row creation.
2. **Warm Fetch:** Verify subsequent loads take `<300ms` with zero outbound network calls (mock out `yf.download`).
3. **Period Backfill:** Cache 2y of data, request 5y, and check that backfilling is triggered.
4. **Resiliency Fallback:** Mock network failure and verify that stale cache data is returned gracefully.
5. **Thundering Herd:** Test parallel identical ticker fetches and verify only one fetch gets executed.

### Manual Verification
1. Run SQL statements in the Supabase SQL editor.
2. Run backend locally and verify Performance tab switches tickers in `<300ms`.
3. Check Supabase query logs and tables to ensure rows are populated.
