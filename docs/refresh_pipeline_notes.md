# Refresh Pipeline Technical Notes

Date: 2026-05-20

## Context

The portfolio dashboard has two recalculation modes:

- Normal refresh: reuses the local SQLite price cache and fetches only a recent price delta.
- Repair mode: fetches full price history and rebuilds the calculation from source data.

After investigation, repair mode produced the expected smoother chart because it rebuilt the full trade-anchored/interpolated price grid from the ledger. Normal refresh previously degraded the chart because it reloaded an imperfect cached grid.

## Fixed Issue

The key bug was that trade-anchored interpolation happened inside `calculate_twr_series()`, but the repaired price grid was not returned to the caller. The pipeline then persisted the pre-repair grid, so the next normal refresh reused the wrong data.

Current fix:

- `performance.calculate_twr_series(..., return_prices=True)` can return the repaired grid.
- `engine.run_recalculation_pipeline()` now saves the repaired grid.
- `storage.save_portfolio_run()` now keeps price rows for all computed price-grid tickers, including tickers sold out by the end of the run.

Practical effect: run repair mode once to reseed the cache; subsequent normal refresh should preserve the repair-mode chart behavior.

## Remaining Technical Debt

### 1. `portfolio_ticker_daily` Has Mixed Responsibilities

The table currently acts as:

- a price cache for incremental refresh,
- a source of current positions for dashboard fast-path loading,
- a pseudo historical holdings table for diagnostics and optimization pages.

This is fragile. `price_gbp` is useful as a repaired price cache, but `shares`, `value_gbp`, and `weight` should not be assumed to represent true historical daily holdings unless the persistence model is changed to store positions as-of each date.

Expected impact today: low to medium. It is unlikely to cause large TWR chart discrepancies after the repaired-grid fix, but it can mislead diagnostics or downstream tools that interpret the table as daily holdings history.

### 2. Cached Prices Are Already Repaired

Normal refresh now loads repaired/interpolated prices and then passes them through the repair/smoothing process again. This is much better than losing the interpolation, but repeated normal refreshes could theoretically over-smooth older cached values.

Expected impact today: low unless repeated refreshes materially alter the same historical windows.

Future design:

- Store raw/provider prices separately.
- Store repaired/engine prices separately.
- Make incremental refresh merge raw prices first, then run repair exactly once to produce the engine price grid.

### 3. Dashboard Headline NAV vs Chart Series

The dashboard headline NAV is rebuilt from `last_prices`, while the chart uses persisted `df_perf` / `TWR_Index`. Tiny differences can appear if the latest price snapshot and the latest performance row are not perfectly aligned.

Expected impact today: low. This is more likely to create small display differences than major performance discrepancies.

### 4. Cache Clearing Does Not Clear `last_prices`

`clear_account_data()` clears portfolio and benchmark history tables, but not `last_prices`. Active-position filtering usually hides stale tickers, but the cache boundary is conceptually incomplete.

Expected impact today: low. Worth cleaning when the storage layer is refactored.

## Suggested Later Refactor

Create clearer persistence tables:

1. `price_raw_daily`
   - account or global scope
   - ticker
   - date
   - raw provider close
   - source
   - quote currency / multiplier metadata where useful

2. `price_engine_daily`
   - account
   - ticker
   - date
   - repaired price used by TWR
   - repair flags such as anchored/interpolated/smoothed/provider

3. `portfolio_position_daily`
   - account
   - date
   - ticker
   - actual shares as of that date
   - value and weight derived from engine prices

4. `portfolio_snapshots`
   - keep as current portfolio-level output table.

This would make normal refresh and repair mode deterministic:

1. Load raw price history from DB.
2. Fetch missing/new raw price windows.
3. Run one repair/anchoring pass.
4. Save repaired prices and true daily positions.
5. Compute and persist portfolio snapshots.

## Priority

Not urgent after the repaired-grid fix. Revisit if:

- normal refresh starts diverging again from repair mode,
- diagnostics/optimization need reliable historical holdings,
- year-end values need broker-grade reconciliation,
- or the price cache becomes hard to reason about when adding more accounts/tickers.
