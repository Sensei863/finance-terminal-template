# Optimization Tickets for Recalculation Engine Latency

To ensure a structured, incremental approach with zero risk of calculation regression, the recalculation pipeline optimizations are broken down into **4 independent tickets**. Each ticket details the target code, specific modifications, and a dedicated testing suite.

---

## Ticket 1: Phase 0 — Deduplicate Benchmark Simulation

### Description
Currently, `_recalculate_all_accounts` in the scheduler passes the active benchmark name to the pipeline run of **every** account (ISA, SIPP, Papa, Consolidated). This causes 4 separate full benchmark simulations and database writes per scheduler refresh. Because the benchmark simulation is only viewed/needed for `Consolidated` performance overlays, we will deduplicate this execution.

### Target Files
- [backend/scheduler.py](file:///c:/Users/divit/Desktop/Finance%20Tool/backend/scheduler.py)

### Modifications
- Modify `_recalculate_all_accounts` to only pass `active_bm_name` when `acct == "Consolidated"`.
- Pass `active_bm_name=None` for `ISA`, `SIPP`, and `Papa`.
- *Note*: Single-account manual recalcs from the UI will still trigger benchmark simulation for that specific account.

### Testing Suite
1. **Database Baseline Verification**:
   - Query `benchmark_snapshots` to check that new entries are written **only** for `Consolidated` after a scheduler run.
2. **Speed Diagnostics**:
   - Run `python scratch/diagnose_scheduler.py` before and after this change.
   - Verify that SIPP, ISA, and Papa execution times drop immediately (since they skip benchmark generation completely).
3. **Correctness Check**:
   - Run `python scratch/test_scheduler_refresh.py` and verify that the latest snapshots for all accounts (cash and portfolio NAVs) remain exactly correct.

---

## Ticket 2: Phase 1 — In-Memory Benchmark Price Prefetching & Cache Extension

### Description
Currently, the benchmark simulator makes a duplicate yfinance query download for the entire 9-year constituent history. We will fetch these prices (including benchmark-specific constituents and FX currency pairs) once during the main price fetch step and pass the cleaned, repaired price grid to the simulator to run locally in-memory.

### Target Files
- [backend/services/engine.py](file:///c:/Users/divit/Desktop/Finance%20Tool/backend/services/engine.py)
- [benchmark_gen.py](file:///c:/Users/divit/Desktop/Finance%20Tool/benchmark_gen.py)

### Modifications
1. **Extend `unique_tickers`**: In `run_recalculation_pipeline`, parse the benchmark definition first. If a benchmark is active, extract its constituents and find any required currency FX pairs (e.g. `GBPUSD=X`, `GBPEUR=X` if currency maps do not match the account's base currency). Append these to `unique_tickers`.
2. **Always-Update Benchmark Tickers**: Add the benchmark constituents to `always_update_tickers` in `_incremental_fetch` so they get delta updates in incremental mode.
3. **Extend Cache**: Reuse/extend `shared_price_cache` to cache cross-account benchmark constituent prices.
4. **Modify Simulator**: Update `BenchmarkSimulator.generate()` in `benchmark_gen.py` to accept `prefetched_prices: pd.DataFrame = None`. If provided and all required columns are present, extract them locally and skip `yf.download`. Implement a targeted yfinance download fallback if any column is missing.
5. **Feed Repaired Grid**: In `run_recalculation_pipeline`, pass the cleansed, repaired `df_prices` (which has currency normalizations and median filters already applied) to `generate(prefetched_prices=df_prices)`.

### Testing Suite
1. **In-Memory Generation Match Test**:
   - Write a temporary test script that instantiates `BenchmarkSimulator` and calls `generate()` twice: once normally (using yfinance download) and once passing a mock `prefetched_prices` dataframe.
   - Verify that the resulting synthetic ledgers and prices returned are **identical** (exact float match).
2. **Network Bypass Verification**:
   - Run the simulation with internet access disabled or mock `yfinance.download` to throw an exception.
   - Verify that `generate()` succeeds without making any network calls when prefetched prices are provided.
3. **Missing Column Fallback Test**:
   - Pass a `prefetched_prices` dataframe with one constituent column deleted.
   - Verify that the simulator falls back to yfinance download to fetch only that missing constituent, succeeding without crashing.

---

## Ticket 3: Phase 2 — Vectorize Spike Checks in `build_trade_anchored_prices`

### Description
The 20% spike check loop inside `build_trade_anchored_prices` checks for anomalies day-by-day. Because it uses Pandas `.iloc[i]` and `.iloc[i-1]` in a loop across thousands of rows and multiple columns, it incurs high indexing overhead. We will vectorize this safety check.

### Target Files
- [backend/services/engine.py](file:///c:/Users/divit/Desktop/Finance%20Tool/backend/services/engine.py) (specifically `build_trade_anchored_prices`)

### Modifications
- Convert the Pandas Series to a NumPy array (`.to_numpy()`) before starting the loop.
- Convert the index and anchors keys to a set of timestamps for O(1) membership checks.
- Loop using raw index offsets on the NumPy array, assign corrected values, and reconstruct the Pandas Series.

### Testing Suite
1. **Mathematical Equivalence Test**:
   - Create a test script containing the original `.iloc`-based loop and the new vectorized NumPy loop.
   - Run both loops over a mock dataframe of 5,000 rows containing simulated price series, trade anchors, and extreme price spikes (>20% jumps).
   - Assert that the returned price grids are **identical** to 6 decimal places.
2. **Performance Benchmark**:
   - Profile the safety check loop before and after vectorization.
   - Verify a speedup of at least **30x** for the spike-check phase itself.

---

## Ticket 4: Phase 3 — Hash Map Database Serialization & Hoisting

### Description
`save_benchmark_run` writes daily benchmark details to the database. Inside its nested loops over dates and constituents, it makes slow `.loc` indexer calls on the prices dataframe and repeatedly queries the NAV dataframe. We will optimize this phase.

### Target Files
- [backend/services/storage.py](file:///c:/Users/divit/Desktop/Finance%20Tool/backend/services/storage.py) (specifically `save_benchmark_run`)

### Modifications
1. **Hoisting**: Move the `bm_nav` query out of the inner constituent loop into the outer date loop.
2. **Hash Map Lookups**: Convert `bm_prices` into a Python dictionary of dictionaries (`{ticker: {date: price}}`) before starting the loops, allowing O(1) lookups instead of `.loc[date_idx, ticker]`.

### Testing Suite
1. **Output Accuracy Check**:
   - Capture a copy of the `benchmark_ticker_daily` records written for an account pre-optimization.
   - Run the optimized `save_benchmark_run` script.
   - Query the table and verify that the values for target weights, prices, and values match the pre-optimization baseline **exactly**.
2. **CPU Profiling**:
   - Measure the execution time of `save_benchmark_run` for a 3,200-day run with 5 constituents.
   - Verify that execution time drops to **sub-second** levels.
