# Recalculation Optimization Plan (Revised)

This document details the architectural analysis, key components, bottlenecks, and a proposed optimization plan for the finance terminal's recalculation engine. This revised plan incorporates the findings from the code review in `recalculation_optimization_plan_review.md`.

---

## 1. Key Objectives

Our optimizations are designed around three key pillars:
1. **Speed & Latency Reduction**: Minimize the overall end-to-end runtime of the recalculation process (currently ~2.5 minutes sequentially for all accounts) to **under 60 seconds** (target: **under 45 seconds**).
2. **Resource & Network Strain Mitigation**: Prevent redundant network connections and download payloads. This prevents yfinance/Stooq rate-limiting, handles delisted assets gracefully, and keeps the server's resource footprint light.
3. **100% Data Accuracy & Integrity**: Ensure that the mathematical calculations (TWR, mark-to-market valuations, currency normalization) and database storage remain completely unchanged and accurate. Cash consolidation logic (Consolidated cash = sum of individual accounts cash) must be maintained perfectly.

---

## 2. Pipeline Components & Bottleneck Analysis

The recalculation pipeline executes sequentially across accounts: `ISA` ➔ `SIPP` ➔ `Papa` ➔ `Consolidated`.

### A. Ticker Identification
- **Current State**: Determines the universe of tickers by merging ledger tickers, snapshot quantities, and active benchmark constituents. Traces positions day-by-day in `run_recalculation_pipeline` to find `active_tickers` (holding > 0.01 shares) so exited assets skip delta price checks.
- **Analysis**: Already optimized. Taking <1ms, it saves minutes of timeouts on exited/delisted tickers.

### B. Price Fetching & Benchmark Simulation (The Main Bottlenecks)
- **Current State**: Uses `_incremental_fetch` to load existing prices from the database, then fetches a tiny delta (15 days) from Stooq/Yahoo for active assets.
- **Bottlenecks**:
  1. **Redundant Downloads**: `BenchmarkSimulator.generate()` (in `benchmark_gen.py`) has no awareness of the database price grid or the scheduler's price cache. It downloads the **entire 9-year historical range** of prices from yfinance for all benchmark constituents and currency pairs every time a benchmark is simulated.
  2. **Multiplied Across Accounts**: Because the scheduler passes `active_bm_name` into every account's `run_recalculation_pipeline`, this 9-year download is executed **4 times** (once for ISA, SIPP, Papa, and Consolidated) on every full scheduler run.
- **Opportunity**: 
  - Add benchmark constituents and required FX currency pairs directly to the main `unique_tickers` list.
  - Add benchmark-only tickers to `always_update_tickers` in `_incremental_fetch` so they get delta updates even when not in active positions.
  - Pass the fully fetched and cleaned `df_prices` (or use the scheduler's `shared_price_cache`) to the benchmark simulator so it runs 100% locally in-memory.

### C. Price Repair Loop (`build_trade_anchored_prices`)
- **Current State**: Evaluates daily mark-to-market prices and TWR compounding in a loop for ~3,200 days from the snapshot date to today.
- **Bottleneck**: Inside the price safety check (`build_trade_anchored_prices` in `engine.py`), the loop checks daily returns for >20% spikes using Pandas `.iloc` or `.loc` indexing (e.g. `combined.iloc[i]` / `combined.iloc[i-1]`). 
- **Impact**: Pandas indexers have heavy internal type checking. Executing them 64,000 times inside nested loops consumes significant CPU cycles. (Note: The main TWR loop `calculate_twr_series` is already optimized with dict lookups; do not touch it).
- **Opportunity**: Convert the Pandas Series to a raw NumPy array (`.to_numpy()`) or use vectorized `pct_change()` before running the safety checks.

### D. Database Storage
- **Current State**: Saves run snapshots and daily ticker statistics. Batch writes are fast via `execute_values`.
- **Bottleneck**: Inside `save_benchmark_run` in `storage.py`, the nested loop over dates and benchmark constituents uses Pandas `.loc` indexers (e.g. `bm_prices.loc[date_idx, ticker]`) to fetch historical prices.
- **Impact**: Running 16,000 `.loc` queries takes several seconds of CPU time and blocks the database connection.
- **Opportunity**: Pre-convert dataframes to dictionary lookups (dict of dicts) before running the serialization loops, matching the pattern already used in `save_portfolio_run`.

---

## 3. Step-by-Step Optimization Proposals

### Phase 0: Deduplicate Benchmark Simulation
- **Action**: Modify `backend/scheduler.py` to only pass the `active_bm_name` to `Consolidated` (or run it once after all accounts complete) during nightly scheduler runs. Pass `active_bm_name=None` to individual accounts. 
- *Note*: Single-account manual recalcs from the UI will still simulate the benchmark for that specific account.

### Phase 1: In-Memory Benchmark Price Prefetching & Cache Extension
1. **Extend `unique_tickers`**: In `run_recalculation_pipeline` (in `backend/services/engine.py`), scan the active benchmark definition, determine the required FX currency pairs (e.g., `GBPUSD=X`, `GBPEUR=X`), and append them along with the constituents directly to the main `unique_tickers` array.
2. **Always-Update Benchmark Tickers**: Add benchmark-only constituents (like `AGGG.L`, `MEUD.L`) to `always_update_tickers` in `_incremental_fetch` so they get delta updates even when not in active positions.
3. **Use Scheduler Cache**: Ensure `shared_price_cache` is extended to cache benchmark FX/constituents at the scheduler level to avoid cross-account duplicate Stooq fetches.
4. **Cleanse & Repair Contract**: Ensure that the benchmark simulator consumes the **cleansed and repaired** price series (`df_prices` from `calculate_twr_series`) to preserve 100% price normalization and TWR accuracy, rather than using raw unadjusted yfinance prices.
5. **Inject Prefetched Prices**: Modify `BenchmarkSimulator.generate()` in `benchmark_gen.py` to accept a `prefetched_prices` DataFrame and run locally. If any column is missing, perform a targeted yfinance fallback fetch.

### Phase 2: Vectorization of Loop Safety Checks
1. **Convert to NumPy / Vectorize**: Optimize `build_trade_anchored_prices` in `backend/services/engine.py` by converting Series to NumPy arrays before running the 20% spike check, following the pattern in `filter_price_spikes`.

### Phase 3: Hash Map Database Serialization
1. **Eliminate `.loc` inside `save_benchmark_run`**: In `backend/services/storage.py`, pre-convert `bm_prices` to a Python dict of dicts.
2. **Hoist Queries**: Retrieve `bm_nav` in the outer date loop instead of the inner ticker loop.

### Phase 4 (Optional Fallback): Union Prefetch & Concurrent Runs
- If the 60-second target is still not met:
  1. Build a union ticker prefetch at the scheduler level (single global fetch).
  2. Parallelize independent account recalcs (ISA, SIPP, Papa) since they don't depend on each other.
  3. Profile Google Sheets fetch latency.

---

## 4. Verification & Testing Strategy

To ensure zero regressions and verify performance gains, we will run:
1. **Performance benchmark**: Instrument `_recalculate_all_accounts()` with per-phase timing (GSheet, price fetch, TWR, benchmark, DB write) and log to scheduler run_entry diagnostics.
2. **Correctness check**: Capture baseline golden snapshots of `portfolio_snapshots` and `benchmark_snapshots` for all accounts. Verify TWR, NAV, and cash balances match baseline numbers exactly post-optimization.
3. **Verification Scripts**:
   - `scratch/diagnose_scheduler.py`: Runs full refresh, prints per-account and per-phase timings.
   - `scratch/test_scheduler_refresh.py`: Compares DB snapshots against baseline and verifies Consolidated cash balance.
