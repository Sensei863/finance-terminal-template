# Screener Caching Plan — Expert Review & Revised Implementation (v2)

This document supersedes the scope and sequencing in `screener_caching_plan.md`. It preserves the original direction (persistent Supabase cache for screener data) and incorporates a full code review of the current backend, gaps in the v1 plan, and a phased implementation spec.

All changes remain restricted to the FastAPI backend (`backend/`). The Streamlit app is untouched.

---

## Part 1: Expert Review & Reasoning

### Verdict

**Yes, this work is needed — but only as part of a broader screener caching story, not as written in v1.**

The plan correctly identifies the real production problem: on Render, the screener's in-memory `@cache_data(ttl=3600)` is wiped on restart, does not share across workers, and does not help the first request after a deploy. Moving OHLCV and metadata to Supabase is the right architectural direction. Storage math is sound, and Critique 1 (do not reuse `portfolio_ticker_daily`) is correct.

What holds v1 back is **scope**: it covers roughly half of what `/api/screener/data` actually does, and it over-promises latency numbers. Treat v1 as a solid Phase 1 draft, not a complete implementation spec.

---

### What v1 Gets Right

#### 1. The problem is real

Today `fetch_screener_data` does a full `yf.download` for 2 years of OHLCV plus a per-ticker `.info` call on every in-memory cache miss:

```python
@cache_data(ttl=3600)
def fetch_screener_data(tickers, benchmark_symbol, period="2y"):
    data = yf.download(unique_tickers, period=period, ...)
    for t in unique_tickers:
        info_dict[t] = yf.Ticker(t).info
```

That in-process cache is not durable on Render. Persistent Supabase caching fixes that.

#### 2. Separate OHLCV table is correct

`portfolio_ticker_daily` stores account-scoped, GBP-converted close prices for TWR. The screener needs raw OHLCV for RSI/MACD/Bollinger and for the Technicals page. Mixing those concerns would create subtle bugs.

#### 3. Incremental fetch mirrors proven patterns

The recalc engine already does this via `_incremental_fetch` in `engine.py` (load DB → delta fetch → merge → upsert). Reusing that mental model is sensible.

#### 4. Storage sizing is conservative and accurate

~4.5 MB for 50 tickers × 2 years is negligible on Supabase free tier.

#### 5. Graceful degradation on 429/500

Serving stale cache instead of hard-failing is exactly what you want for a read-heavy UI endpoint.

---

### Where v1 Is Under-Thought

#### Gap 1: It does not cover the full request path

The Performance page hits `/api/screener/data`, which does more than `fetch_screener_data`:

| Call | External? | Covered by v1? |
|------|-----------|----------------|
| `fetch_screener_data` (OHLCV + info) | yfinance | Yes |
| `get_ticker_activity` | Another `yf.Ticker(t).info` + `.actions` | **No** |
| `_fetch_fx_close_series` (USD/EUR → GBP) | yfinance/Stooq | **No** |
| `storage.load_latest_portfolio` | DB only | N/A |

The v1 verification claim of "0 external network requests on second run" will **not** hold unless metadata is shared with `get_ticker_activity` and FX series are cached. After v1 as written, you will still see 2–3 yfinance calls per ticker switch on a cold in-memory cache.

#### Gap 2: The `<50ms` target is optimistic

Supabase round-trip from Render is typically **100–300ms**, not 50ms, especially on cold connections. You will still be ~10× faster than 3+ seconds, but do not bake 50ms into UX expectations. Revised target: **<300ms warm cache, <5s cold fetch**.

#### Gap 3: Metadata TTL needs nuance

30 days is fine for sector, industry, expense ratio, and AUM. It is too long for fields the UI displays that move frequently: `trailingPE`, `forwardPE`, `marketCap`, `dividendYield`, `beta`, `currency`.

**Recommendation:** store the full `.info` blob as JSONB, but use two TTL tiers — 30 days for structural fields, 24 hours for quote-sensitive refresh — or refresh metadata whenever OHLCV is refreshed.

#### Gap 4: Schema section is too thin

v1 names tables but does not specify primary keys, indexes, adjusted vs unadjusted prices, source tracking, or relationship to existing tables:

- `etf_kiid` — TER, index tracked, domicile for ETFs
- `constituent_metadata` — sector/industry with `fetched_at`
- `movers_price_cache` — precedent for price caching with TTL

The revised plan defines schema explicitly and documents how these tables interact.

#### Gap 5: `period` parameter is ignored

`fetch_screener_data` supports `"1mo"` through `"max"`. The Technicals page and Performance chart can need different horizons. v1 assumes 2y only. Explicit backfill logic is required: if cache has 2y but caller asks for 5y, fetch the gap — do not silently truncate.

#### Gap 6: Stooq fallback quality

When yfinance fails, the screener copies Close into Open/High/Low and sets Volume to 0. If you persist that to Supabase, bad OHLCV gets frozen. The revised plan flags synthetic rows or refuses to cache incomplete bars.

#### Gap 7: Concurrency / thundering herd

Two simultaneous requests for a new ticker will both miss cache and both hit yfinance. Upsert idempotency alone is not enough; add a simple in-flight lock per ticker.

#### Gap 8: No proactive warming

The nightly scheduler already knows every held ticker. Warming `ticker_ohlcv_daily` during the scheduler run means the screener rarely hits a cold yfinance path. v1 is purely reactive (fetch on page load).

---

### Relationship to the Recalculation Optimization Plan

These plans are **orthogonal and both valid**, but different priority:

| Plan | Pain | Frequency | Impact |
|------|------|-----------|--------|
| Recalculation optimization | ~2.5 min scheduler, redundant 9y benchmark downloads | Nightly | High — backend cost, rate limits |
| Screener caching | ~3s page loads, 429 on Render | Every ticker click | Medium — UX, reliability |

**Priority guidance:**

- Do screener caching first if 429s are blocking daily use of Performance/Technicals.
- Do recalc optimization first if scheduler runtime is the main bottleneck.
- Long term: share price-fetch infrastructure between screener cache and `_incremental_fetch` rather than growing a third independent fetch path.

---

### Summary Table

| Question | Answer |
|----------|--------|
| Is it needed? | **Yes**, for Render reliability and UX — the in-memory cache is not production-grade. |
| Is v1 properly thought out? | **Partially.** Core architecture is sound; scope, latency claims, and edge cases need work. |
| Biggest gap? | Only caches half the screener endpoint — metadata duplication in `get_ticker_activity` and uncached FX fetches. |
| Biggest risk? | Persisting low-quality Stooq fallback OHLCV; unspecified period/backfill logic. |
| Priority vs recalc plan? | Medium. Context-dependent (see above). |

---

## Part 2: Revised Implementation Plan (v2)

### Objectives

1. **Reliability:** Serve screener data from Supabase when yfinance/Stooq fail or rate-limit on Render.
2. **Latency:** Reduce `/api/screener/data` end-to-end time from 3+ seconds to **<300ms** on warm cache (DB hit only).
3. **Correctness:** Preserve existing metric values (RSI, MACD, 1Y return, etc.) — golden-test parity with pre-cache behaviour.
4. **Maintainability:** Reuse fetch patterns from `engine.py` where possible; avoid a third divergent price-fetch code path long term.

### Non-Goals

- Changing TWR/recalculation logic or `portfolio_ticker_daily` schema.
- Modifying the Streamlit app or Next.js frontend (backend-only).
- Replacing `etf_kiid` or `constituent_metadata` — complement them, do not duplicate unnecessarily.

---

### Phase 0: Schema & Storage Layer

#### [NEW] `migrations/app_db/002_screener_cache.sql`

```sql
-- Raw OHLCV cache (unconverted, auto-adjusted prices matching yfinance auto_adjust=True)
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

-- Full yfinance .info blob + tiered freshness
CREATE TABLE IF NOT EXISTS ticker_metadata (
    ticker              TEXT        PRIMARY KEY,
    info_json           JSONB       NOT NULL,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    quote_fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now()  -- refreshed with OHLCV or daily
);

-- Optional: track in-flight fetches to prevent thundering herd (simple advisory)
CREATE TABLE IF NOT EXISTS ticker_fetch_locks (
    ticker          TEXT        PRIMARY KEY,
    locked_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_by       TEXT
);
```

**Storage estimate (unchanged from v1):** 50 tickers × 2y ≈ 4.5 MB OHLCV + ~25 KB metadata ≈ **<1% of Supabase free tier**.

**Design notes:**

- Prices stored **unconverted** in native listing currency, matching current screener behaviour before FX normalization in the router.
- `source = 'synthetic'` marks Stooq fallback rows where O/H/L were copied from Close — these must not overwrite real yfinance rows on subsequent fetches.
- FX pairs (`GBPUSD=X`, `EURGBP=X`) use the same `ticker_ohlcv_daily` table (close-only rows are fine).

#### [MODIFY] `backend/services/storage.py`

Add helpers:

| Function | Purpose |
|----------|---------|
| `save_ticker_ohlcv(ticker, df, source='yfinance')` | Bulk upsert via `execute_values`; skip upsert when `source='synthetic'` would downgrade an existing `yfinance` row |
| `load_ticker_ohlcv(ticker, start_date) -> pd.DataFrame` | Returns MultiIndex-compatible DataFrame (columns: Open, High, Low, Close, Volume) |
| `get_latest_ohlcv_date(ticker) -> date \| None` | Fast lookup via index |
| `save_ticker_metadata(ticker, info: dict)` | Upsert JSONB + update both timestamps |
| `load_ticker_metadata(ticker, max_age_days=30) -> dict \| None` | Returns cached info if within structural TTL |
| `load_ticker_metadata_quote(ticker, max_age_hours=24) -> dict \| None` | Returns cached info if quote fields are fresh enough |
| `merge_metadata_with_etf_kiid(ticker, info) -> dict` | For `.L` ETFs, overlay TER/index from `etf_kiid` before saving |

Lock helpers (optional but recommended):

| Function | Purpose |
|----------|---------|
| `try_acquire_fetch_lock(ticker, owner) -> bool` | INSERT … ON CONFLICT DO NOTHING |
| `release_fetch_lock(ticker)` | DELETE lock row |
| `wait_for_fetch_lock(ticker, timeout_sec=30)` | Poll until lock released or timeout |

---

### Phase 1: Cache-Backed `fetch_screener_data`

#### [MODIFY] `backend/services/screener.py`

Refactor `fetch_screener_data(tickers, benchmark_symbol, period="2y")`:

```
For each ticker in (tickers + benchmark):
  1. Map period → required start_date (existing days_back logic)
  2. Load OHLCV from ticker_ohlcv_daily WHERE date >= start_date
  3. Determine staleness:
       - latest_cached_date < last_expected_trading_day → needs delta fetch
       - earliest_cached_date > start_date + 10 days → needs backfill
  4. If stale/missing AND lock acquired:
       - Delta: fetch from (latest_cached_date - 5 days) to today via yfinance
       - Backfill: fetch full range from start_date via yfinance, then Stooq fallback
       - Save new rows (mark source appropriately)
       - Release lock
  5. If stale/missing AND lock NOT acquired:
       - Wait for other request, then reload from DB
  6. If external fetch fails (429/500/timeout):
       - Return best available cached data
       - Set internal flag: served_stale=True (propagate to API response)
  7. Metadata:
       - Try load_ticker_metadata_quote (24h) → else load_ticker_metadata (30d)
       - For ETFs: merge etf_kiid before returning
       - If stale/missing: fetch yf.Ticker(t).info, save, return
       - On fetch failure: return cached metadata regardless of age
  8. Assemble MultiIndex DataFrame matching current return shape
```

**Period backfill:** If caller requests `period="5y"` but cache only has 2y, detect `earliest_cached_date > start_date + 10d` and trigger backfill — same pattern as `_incremental_fetch` in `engine.py`.

**Keep `@cache_data(ttl=3600)`** as a second layer for same-process dedup within the hour. DB cache is the durable layer.

**Return signature extension (internal):** Optionally return `(data, info_dict, cache_meta)` where `cache_meta = { "served_stale": bool, "ohlcv_age_hours": float, "metadata_age_hours": float }`. Router can expose this in JSON for debugging.

---

### Phase 1b: Complete the `/api/screener/data` Request Path

These changes are required for the "zero external calls on warm cache" goal. Implement in the same PR or immediately after Phase 1.

#### [MODIFY] `backend/services/screener.py` — `get_ticker_activity`

Currently makes a **second** `yf.Ticker(ticker).info` call. Change to:

1. Accept optional `cached_info: dict | None` parameter from the router.
2. If not provided, call `storage.load_ticker_metadata_quote` / shared metadata loader used by `fetch_screener_data`.
3. Only hit yfinance for `.actions` (dividends) — cache dividend actions separately or accept that dividends refresh on a 24h TTL in a new `ticker_dividends` table (optional Phase 1b stretch).

Minimum viable: eliminate duplicate `.info` call by passing info from router.

#### [MODIFY] `backend/routers/screener.py` — FX conversion

Currently calls `_fetch_fx_close_series("GBPUSD=X", start_date)` on every USD→GBP conversion.

Change to:

1. Load `GBPUSD=X` / `EURGBP=X` from `ticker_ohlcv_daily` via `load_ticker_ohlcv`.
2. If stale, fetch delta via existing `_fetch_fx_close_series`, then `save_ticker_ohlcv`.
3. On fetch failure, use cached FX even if slightly stale.

#### [MODIFY] `backend/routers/screener.py` — response envelope

Add optional cache diagnostics to JSON response:

```json
{
  "metrics": { ... },
  "info": { ... },
  "cache": {
    "served_stale": false,
    "ohlcv_age_hours": 4.2,
    "metadata_age_hours": 6.1,
    "source": "supabase"
  }
}
```

Frontend can ignore this; useful for Render debugging.

---

### Phase 2: Proactive Cache Warming (Scheduler)

#### [MODIFY] `backend/scheduler.py`

After nightly recalculation completes, warm screener cache for:

```
warm_tickers = held_tickers ∪ benchmark_constituents ∪ recent_exited_tickers ∪ {IUSA.L}
```

For each ticker:

1. Call the same incremental OHLCV refresh logic extracted from `fetch_screener_data` (shared function in `screener.py` or `storage.py`).
2. Refresh metadata if quote TTL expired.
3. Log counts: warmed, skipped (fresh), failed (with stale fallback note).

**Benefit:** First user click after deploy/scheduler run hits warm Supabase cache, not yfinance.

**Coordination with recalc plan:** When recalc Phase 1 adds benchmark tickers to `unique_tickers`, those tickers are automatically warmed here too.

---

### Phase 3: Fetch Path Consolidation (Optional, Post-MVP)

Long-term maintainability — do after Phases 1–2 are stable.

1. Extract shared `_fetch_price_series` / `_incremental_fetch` delta logic into a module (e.g. `backend/services/price_fetch.py`).
2. Screener cache and recalc engine both call the same low-level fetch + source tagging.
3. Document the contract: screener stores raw OHLCV; recalc stores GBP close in `portfolio_ticker_daily` — different tables, same fetcher.

---

## Verification Plan (Revised)

### Automated Tests — `scratch/test_screener_cache.py`

| # | Test | Expected |
|---|------|----------|
| 1 | Cold fetch for new ticker (e.g. `AAPL`) | ~2–5s; rows in `ticker_ohlcv_daily` and `ticker_metadata` |
| 2 | Warm fetch same ticker | <300ms; no yfinance calls (mock/patch `yf.download` to assert not called) |
| 3 | Golden metrics parity | RSI, MACD, 1Y return for 3–5 tickers match pre-cache baseline within 1e-6 |
| 4 | Period backfill | Cache 2y, request 5y → backfill triggered, full range returned |
| 5 | API failure fallback | Mock yfinance 429 → returns stale cache, `served_stale=true` |
| 6 | Synthetic row handling | Stooq fallback marked `source=synthetic`; subsequent yfinance fetch overwrites |
| 7 | End-to-end `/api/screener/data` | Warm path: 0 external calls including FX and metadata |
| 8 | Concurrent cold fetch | Two parallel requests for new ticker → only one yfinance fetch (lock works) |

### Manual Verification

1. Run DDL in Supabase SQL editor (`002_screener_cache.sql`).
2. Deploy to Render.
3. Load Performance page — first ticker click may take 2–5s (cold).
4. Switch tickers — should feel instant (<300ms).
5. Simulate yfinance outage (block outbound or use bad ticker) — page loads with stale data, no 500.
6. Check scheduler logs after nightly run — cache warming counts present.

---

## File Change Summary

| File | Action | Phase |
|------|--------|-------|
| `migrations/app_db/002_screener_cache.sql` | NEW | 0 |
| `backend/services/storage.py` | MODIFY — cache helpers + locks | 0 |
| `backend/services/screener.py` | MODIFY — cache-backed fetch + shared warm function | 1, 1b, 2 |
| `backend/routers/screener.py` | MODIFY — FX cache, pass metadata, cache diagnostics | 1b |
| `backend/scheduler.py` | MODIFY — post-recalc cache warming | 2 |
| `scratch/test_screener_cache.py` | NEW | 1 |
| `backend/services/price_fetch.py` | NEW (optional) | 3 |

---

## Implementation Order (Recommended)

```
Phase 0  →  DDL + storage helpers                          (~1 session)
Phase 1  →  fetch_screener_data cache-backed               (~1–2 sessions)
Phase 1b →  get_ticker_activity + FX cache + API envelope  (~1 session)
           ↑ Ship here for meaningful UX improvement
Phase 2  →  Scheduler warming                              (~0.5 session)
Phase 3  →  Fetch consolidation with engine.py             (future, optional)
```

---

## Resolved Design Decisions (from v1 critiques)

> **Critique 1: Reusing `portfolio_ticker_daily`**
> **Resolution (unchanged):** New `ticker_ohlcv_daily` table for raw OHLCV. Portfolio table remains for TWR only.

> **Critique 2: Metadata staleness**
> **Resolution (revised):** Two-tier TTL — 30 days structural, 24 hours quote-sensitive. Refresh metadata when OHLCV is refreshed. Overlay `etf_kiid` for known ETFs before hitting yfinance.

> **Latency target (revised):** <300ms warm cache (not <50ms). <5s acceptable on cold fetch.

> **Supabase storage (unchanged):** <2% of free tier for 50 tickers. No concern.

---

## References

- Original plan: `screener_caching_plan.md`
- Recalculation optimization (separate concern): `recalculation_optimization_plan.md`
- Current screener fetch: `backend/services/screener.py` — `fetch_screener_data`
- Current API router: `backend/routers/screener.py` — `/api/screener/data`
- Incremental fetch precedent: `backend/services/engine.py` — `_incremental_fetch`
- Existing cache patterns: `migrations/app_db/001_cache_core.sql` — `constituent_metadata`, `movers_price_cache`, `etf_kiid`
