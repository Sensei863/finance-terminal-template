# Recalculation Optimization Plan — Review & Proposed Edits

This document reviews `recalculation_optimization_plan.md` against the current codebase and proposes edits before implementation. Intended for handoff to an implementing agent.

---

## Context

The finance terminal's recalculation pipeline runs sequentially across accounts (ISA → SIPP → others → Consolidated). Current end-to-end runtime is ~2.5 minutes. Target: **under 60 seconds** total, with no regressions to TWR, NAV, cash consolidation, or benchmark accuracy.

Key files:

| File | Role |
|------|------|
| `backend/services/engine.py` | `run_recalculation_pipeline`, `_incremental_fetch`, `build_trade_anchored_prices` |
| `benchmark_gen.py` | `BenchmarkSimulator.generate()` — full yfinance download |
| `performance.py` | `calculate_twr_series` — main TWR loop |
| `backend/services/storage.py` | `save_portfolio_run`, `save_benchmark_run` |
| `backend/scheduler.py` | `_recalculate_all_accounts`, `shared_price_cache` |

---

## Verdict

The original plan is **directionally correct**. Phase 1 (benchmark duplicate fetch) is the highest-value item. Phases 2 and 3 are valid but smaller wins. The plan needs several factual corrections, one major missing optimization, and a stronger accuracy contract before implementation.

---

## What the Original Plan Gets Right

### Phase 1 — Benchmark duplicate fetch (highest value)

`BenchmarkSimulator.generate()` still does a full-history `yf.download()` with no awareness of the pipeline price grid:

```python
# benchmark_gen.py
raw_prices = yf.download(
    all_tickers_to_fetch,
    start=self.start_date,
    end=today,
    auto_adjust=True,
    threads=False
)
```

The main pipeline already incremental-fetches via Stooq and **partially** prefetches benchmark constituents into `unique_tickers` in `run_recalculation_pipeline` (lines ~1203–1218 in `backend/services/engine.py`). Phase 1 is the right direction — it just isn't fully wired yet (FX pairs missing, simulator still re-downloads).

### Phase 3 — Hash map database serialization

`save_portfolio_run` already uses dict-based lookups (`df_prices.to_dict(orient="index")`). `save_benchmark_run` still uses nested `.loc` in a date × ticker loop. Hoisting `bm_nav` out of the inner ticker loop is a sensible micro-optimization. Mirroring the `save_portfolio_run` pattern is sufficient.

---

## Required Corrections to the Original Plan

### 1. Benchmark cost is multiplied across ALL accounts, not just Consolidated

**Original plan claim:** Duplicate fetching adds 30–40 seconds to the Consolidated account run.

**Reality:** The scheduler passes `active_bm_name` into **every** account run:

```python
# backend/scheduler.py
err = run_recalculation_pipeline(
    acct,
    force_full_prices=force_full_prices,
    active_bm_name=active_bm_name,
    price_cache=shared_price_cache,
)
```

With ISA → SIPP → Papa → Consolidated, this likely means **4 full `yf.download()` calls + 4 full benchmark TWR runs**, not one 30–40s hit on Consolidated alone. This is probably a bigger win than Phase 2 or 3 combined.

**Proposed edit — add Phase 0 (or Phase 1a):**

> Run synthetic benchmark simulation **once per refresh** (Consolidated only, or after all accounts finish), not inside every `run_recalculation_pipeline` call when `active_bm_name` is set by the scheduler.

UI-triggered single-account recalc can still run benchmark for that account if needed.

This pairs naturally with prefetching: fetch benchmark prices once, simulate once, persist once.

---

### 2. Section C mislabels the bottleneck

**Original plan title:** "TWR Calculations (Pandas Indexer Overhead)"

**Reality:** The main TWR loop is **already optimized** with dict lookups in `performance.py`:

```python
# OPTIMIZATION: Pre-convert df_prices to a nested dictionary for fast O(1) lookups
prices_dict = {}
if not df_prices.empty:
    prices_dict = {col: df_prices[col].to_dict() for col in df_prices.columns}
...
p = prices_dict[t].get(current_date, np.nan)
```

The real CPU hotspot in that area is `build_trade_anchored_prices` (the 20% daily-move guard using `.iloc`), plus the per-column 5-day rolling median at the end.

**Proposed edit:** Rename section C to **"Price repair loop (`build_trade_anchored_prices`)"** so effort isn't duplicated in the wrong place.

Also note: `filter_price_spikes` already uses NumPy (`.to_numpy()`). Phase 2 should follow that existing pattern rather than inventing a parallel approach.

For Phase 2, consider **vectorized `pct_change()`** with an anchor-date mask instead of a raw NumPy loop. Same performance benefit, less code, easier to maintain.

---

### 3. Phase 1 needs a price-normalization contract, not just "pass df_prices"

The portfolio path uses **Stooq + `currency_utils.normalize_series`**. The benchmark path uses **yfinance `auto_adjust` + its own FX logic**. Blindly substituting prefetched Stooq prices can change benchmark NAV/TWR even if the pipeline is faster.

**Proposed additions to Phase 1:**

1. Extract constituent series from `df_prices` **after** the same cleanse/repair path used for portfolio prices (or explicitly document that benchmark uses pre-repair raw grid — pick one and stick to it).
2. Add required **FX pairs** to `unique_tickers` (e.g. `GBPUSD=X`, `GBPEUR=X`) — constituents alone are not enough.
3. Add benchmark-only tickers to `always_update_tickers` in `_incremental_fetch` so they get delta updates even when not in `active_tickers` (portfolio holdings).
4. Define fallback: missing column → targeted fetch for that ticker only (original plan mentions this; keep it).

Without this, the "100% data accuracy" objective is at risk.

---

### 4. `shared_price_cache` already exists — extend it, don't reinvent

The scheduler already passes `shared_price_cache` across accounts. Phase 1 should explicitly say: extend that cache for benchmark FX/constituents and optionally hoist a **single shared benchmark price slice** at the scheduler level, rather than only threading through `generate(prefetched_prices=...)`.

---

### 5. Verification section references scripts that don't exist

**Original plan references:**

- `scratch/diagnose_scheduler.py`
- `scratch/test_scheduler_refresh.py`

Neither exists in the repo.

**Proposed edit:** Either create these scripts as part of the work, or point to existing tooling and define concrete checks:

| Check | Method |
|-------|--------|
| **Performance** | Wall-clock for `_recalculate_all_accounts()` before/after |
| **Correctness** | Tolerance-based compare of `portfolio_snapshots` and `benchmark_snapshots` for all accounts (golden run) |
| **Regression** | Consolidated cash = sum of individual account cash |

Also note: `verify_backend.py` still assumes SQLite/local paths; production storage is PostgreSQL via `backend/services/storage.py` — tests should match the real backend.

---

### 6. Minor factual fixes

| Original plan says | Reality |
|--------------------|---------|
| Duplicate fetch only on Consolidated | Runs on every account when scheduler sets `active_bm_name` |
| `save_benchmark_run` uses PostgreSQL | Correct for `backend/services/storage.py` |
| `_incremental_fetch` loads from SQLite | Comments say SQLite; verify against actual `load_full_price_grid` backend — doc may be stale |
| 152s → 45s target | Reasonable if benchmark dedup + prefetch land; Phase 2+3 alone won't get there |

---

## Alternative / Complementary Implementations

### A. Scheduler-level benchmark (recommended, alongside Phase 1)

Move benchmark out of `run_recalculation_pipeline` when called from `_recalculate_all_accounts`. Keep benchmark inside the pipeline for UI-triggered single-account recalc if needed.

### B. Single global price fetch before the account loop

Collect union of all tickers (all accounts + benchmark + FX + index lines), fetch once with `shared_price_cache`, pass into each pipeline call. Reduces duplicate Stooq work across accounts, not just benchmark yfinance work.

### C. Parallelize independent accounts

ISA, SIPP, Papa are independent; only Consolidated depends on merged ledger. Running the first three concurrently (with a shared read-only price cache) could cut wall-clock significantly without touching math.

### D. GSheet latency (not in original plan)

Nightly run calls `clear_all_caches()` before recalc — intentional for freshness, but potentially a large hidden cost. Worth timing separately.

---

## Proposed Revised Phase Order

Replace the original 3-phase structure with:

### Phase 0 — Dedupe benchmark execution
- Run benchmark simulation **once per full refresh** (Consolidated only).
- Scheduler passes `active_bm_name=None` to individual account runs; runs benchmark after Consolidated completes.

### Phase 1 — In-memory benchmark price prefetching
1. Extend `unique_tickers`: add benchmark constituents **and** required FX pairs.
2. Add benchmark tickers to `always_update_tickers` in `_incremental_fetch`.
3. Extend `shared_price_cache` at scheduler level for cross-account reuse.
4. Pass fetched `df_prices` into `BenchmarkSimulator.generate(prefetched_prices=df_prices)`.
5. Modify `generate()` to extract constituent/FX series from the passed DataFrame.
6. Apply the same normalization contract as portfolio prices (Stooq + `currency_utils`).
7. Fall back to targeted `yf.download` only for missing tickers.

### Phase 2 — Vectorize price repair safety checks
1. In `build_trade_anchored_prices` (not the TWR loop), vectorize the 20% spike check using `pct_change()` with anchor-date mask, or NumPy following the existing `filter_price_spikes` pattern.
2. Do **not** re-optimize `calculate_twr_series` — it already uses dict lookups.

### Phase 3 — Hash map database serialization
1. In `save_benchmark_run`, mirror `save_portfolio_run`: `bm_prices.to_dict(orient="index")`.
2. Hoist `bm_nav` retrieval to the outer date loop.

### Phase 4 (optional) — If still above 60s target
1. Union ticker prefetch before account loop (single global fetch).
2. Parallelize ISA / SIPP / Papa account runs.
3. Profile GSheet fetch latency separately.

---

## Verification & Testing Strategy (revised)

### Performance benchmark
- Instrument `_recalculate_all_accounts()` with per-phase timing (GSheet, price fetch, TWR, benchmark, DB write).
- Target: full run drops from ~152s to **under 60s** (stretch: under 45s).
- Log timing to scheduler run_entry diagnostics.

### Correctness regression
- Before implementing: capture golden snapshots of `portfolio_snapshots` and `benchmark_snapshots` for all accounts.
- After each phase: compare NAV, cash, TWR_Index, Daily_Return within tolerance (exact match preferred for TWR_Index).
- Verify Consolidated cash = sum of individual account cash.

### Scripts to create (if not using existing tooling)
- `scratch/diagnose_scheduler.py` — runs full refresh, prints per-account and per-phase timings.
- `scratch/test_scheduler_refresh.py` — compares DB snapshots against golden baseline.

---

## Implementation Notes for the Agent

1. **Do not change TWR math, cash consolidation logic, or currency normalization rules** unless explicitly required for the normalization contract in Phase 1.
2. **Minimize scope per phase** — each phase should be independently verifiable.
3. **`benchmark_gen.py` lives at repo root**, imported as `from benchmark_gen import BenchmarkSimulator` in `backend/services/engine.py`.
4. **`performance.py` lives at repo root**, imported from engine.
5. The scheduler's `shared_price_cache` is a dict keyed by `(ticker, start_date)` tuples for Stooq fetches and FX series keys like `("GBPEUR=X", start_date)`.
6. Benchmark definitions are loaded via `storage.load_benchmark_definitions()`; scheduler uses the newest definition by `updated_at`.

---

## Summary of Edits to Apply to `recalculation_optimization_plan.md`

1. Add **Phase 0**: dedupe benchmark execution across accounts (run once on Consolidated).
2. Fix **Consolidated-only** assumption — benchmark currently runs on every account.
3. Retitle **section C** from "TWR Calculations" to **"Price repair (`build_trade_anchored_prices`)"**.
4. Add **FX pairs + normalization contract** to Phase 1.
5. Acknowledge **`shared_price_cache`** and extend it rather than building parallel caching.
6. Replace or create **verification scripts**; add golden snapshot comparison.
7. Add optional **Phase 4** (union prefetch, parallel accounts, GSheet profiling) if 60s SLA not met after Phases 0–3.
