"""
newsletter_ui.py  —  v3
────────────────────────
Faraglioni & Aegis  ·  Weekly Investor Letter  (Streamlit tab module)

Integration with app.py
────────────────────────
1.  import newsletter_ui

2.  st.tabs() → add "📰 Newsletter" tab, unpack tab_news

3.  with tab_news:
        newsletter_ui.render_newsletter_tab(
            account_view      = account_view,
            df_perf           = df_perf,
            positions         = positions,
            df_prices         = df_prices,
            df_benchmark_perf = df_benchmark_perf,
            api_key           = api_key,
        )
"""

import datetime
import glob
import json
import logging
import os
import re
import smtplib

import subprocess
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import numpy           as np
from backend.services import gemini_util
from backend.config import get_secrets
from backend.services.file_utils import atomic_write_json
import pandas as pd
import time
import functools
import threading
from collections import OrderedDict

class _SimpleTTLCache:
    """Thread-safe LRU cache with time-to-live (TTL) expiration to prevent memory leaks."""
    def __init__(self, maxsize: int = 256, ttl_seconds: float = 3600.0):
        self.maxsize = maxsize
        self.ttl = ttl_seconds
        self.data = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            if key not in self.data:
                return None
            val, expiry = self.data[key]
            if self.ttl and time.time() > expiry:
                del self.data[key]
                return None
            self.data.move_to_end(key)
            return val

    def set(self, key, val):
        with self.lock:
            if key in self.data:
                del self.data[key]
            elif len(self.data) >= self.maxsize:
                self.data.popitem(last=False)
            expiry = time.time() + (self.ttl if self.ttl is not None else 3600.0)
            self.data[key] = (val, expiry)

def cache_data(ttl: float = 3600.0, show_spinner: bool = False, maxsize: int = 256):
    """Bounded, TTL-aware replacement for streamlit.cache_data."""
    def decorator(func):
        cache = _SimpleTTLCache(maxsize=maxsize, ttl_seconds=ttl or 3600.0)
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted((k, str(v)) for k, v in kwargs.items())))
            cached = cache.get(key)
            if cached is not None:
                return cached
            result = func(*args, **kwargs)
            cache.set(key, result)
            return result
        return wrapper
    return decorator

def cache_resource(func):
    """Thread-safe singleton/resource cache with 24h TTL."""
    return cache_data(ttl=86400.0, maxsize=64)(func)

import yfinance as yf

from backend.services import storage
from backend.services.technicals_service import (
    _build_technical_snapshot,
    _build_prompt as _tech_prompt,
    _fetch_ohlcv,
)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
_BASE_DIR        = Path(__file__).resolve().parent.parent.parent
_SNAPSHOTS_ROOT  = _BASE_DIR / "Scraper" / "snapshots"
_TEMPLATE_PATH   = _BASE_DIR / "Newsletter template" / "faraglioni_FINAL.html"
_OUTPUT_PATH     = _BASE_DIR / "Newsletter template" / "newsletter_latest.html"
_SCHEDULE_FILE   = _BASE_DIR / "backend_newsletter_schedule.json"
_INDEX_BENCHMARK = "IUSA.L"   # Global fallback for chart lines

_sec = get_secrets()
RECIPIENT_EMAIL    = os.environ.get("RECIPIENT_EMAIL") or os.environ.get("recipient_email") or _sec.get("recipient_email", "")
SENDER_EMAIL       = os.environ.get("SENDER_EMAIL") or os.environ.get("sender_email") or _sec.get("sender_email", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD") or os.environ.get("gmail_app_password") or _sec.get("gmail_app_password", "")
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY") or _sec.get("gemini_api_key", "")

_STALE_HOURS = 24   # hours before DB data is considered stale

_SIGNAL_WEIGHTS = {
    "macd_crossover":     3,
    "rsi_extreme":        2,
    "golden_death_cross": 2,
    "bb_breakout":        2,
    "bb_squeeze":         1,
}

# Tickers to never feature in the technical spotlight — physical commodities,
# currency hedged variants, and money-market instruments whose price series
# are driven by spot commodity moves or FX, not equity technicals.
_TECHNICAL_EXCLUDE = {
    "SGLN.L",   # iShares Physical Gold ETC
    "IGLH.L",   # iShares Gold CHF Hedged
    "PPFB.L",   # Invesco Physical Gold ETC
    "PHGP.L",   # WisdomTree Physical Gold
    "PHAU.L",   # WisdomTree Physical Gold USD
    "ERNS.L",   # iShares £ Ultrashort Bond (money market)
    "IBCI.L",   # iShares € Inflation Linked Govt Bond
}

# ─────────────────────────────────────────────────────────────────────────────
# 1.  TECHNICAL INTERESTINGNESS SCORER
# ─────────────────────────────────────────────────────────────────────────────

def score_ticker_interestingness(snap: dict) -> tuple:
    score, signals = 0, []

    cross = snap.get("macd_cross", "")
    if "BULLISH CROSSOVER" in cross.upper():
        score += _SIGNAL_WEIGHTS["macd_crossover"]; signals.append("MACD Bullish Cross")
    elif "BEARISH CROSSOVER" in cross.upper():
        score += _SIGNAL_WEIGHTS["macd_crossover"]; signals.append("MACD Bearish Cross")

    rsi = snap.get("rsi_now", 50.0)
    if not np.isnan(rsi) and (rsi > 65 or rsi < 35):
        score += _SIGNAL_WEIGHTS["rsi_extreme"]
        signals.append(f"RSI {rsi:.0f} ({'overbought' if rsi > 65 else 'oversold'})")

    sma50  = snap.get("sma50",  np.nan)
    sma200 = snap.get("sma200", np.nan)
    if not (np.isnan(sma50) or np.isnan(sma200)):
        gap_pct = abs(sma50 - sma200) / sma200 * 100
        if gap_pct < 1.5:
            score += _SIGNAL_WEIGHTS["golden_death_cross"]
            signals.append("Golden Cross (forming)" if sma50 > sma200 else "Death Cross (forming)")

    bb_pos = snap.get("bb_position_pct", 50.0)
    if not np.isnan(bb_pos) and (bb_pos > 100 or bb_pos < 0):
        score += _SIGNAL_WEIGHTS["bb_breakout"]
        signals.append(f"BB {'Upper' if bb_pos > 100 else 'Lower'} Breakout")

    bb_bw = snap.get("bb_bandwidth_pct", 99.0)
    if not np.isnan(bb_bw) and bb_bw < 10.0:
        score += _SIGNAL_WEIGHTS["bb_squeeze"]
        signals.append(f"BB Squeeze (bw={bb_bw:.1f}%)")

    return score, signals


def _correct_pence_ohlcv(df_ohlcv: pd.DataFrame, base_currency: str = "GBP") -> pd.DataFrame:
    """Delegated to currency_utils."""
    from backend.services import currency_utils
    return currency_utils.normalize_ohlcv(None, df_ohlcv, base_currency=base_currency)


def pick_featured_ticker(positions, df_prices, ohlcv_data):
    """Select the most technically interesting *equity* ticker from the portfolio.

    Excluded from candidacy:
    - Tickers in _TECHNICAL_EXCLUDE (physical commodity ETCs, money-market)
    - Ultra-low-vol instruments (annualised vol < 1%) — permanent BB Squeeze noise
    """
    best_ticker = best_snap = None
    best_score  = -1
    best_signals = []
    largest_ticker, largest_value = None, -1

    for ticker, shares in positions.items():
        if shares < 0.01 or ticker not in ohlcv_data:
            continue

        # Skip commodities, physical ETCs, and money-market instruments
        if ticker in _TECHNICAL_EXCLUDE:
            continue

        # Apply pence→GBP correction to raw yfinance OHLCV
        from backend.services import currency_utils
        ohlcv_corrected = currency_utils.normalize_ohlcv(ticker, ohlcv_data[ticker])

        # ── Track the largest position as a fallback ──────────────────
        # Use pence-corrected last close price for a meaningful £ value
        try:
            last_price_gbp = float(ohlcv_corrected["Close"].dropna().iloc[-1])
            val = shares * last_price_gbp
        except Exception:
            val = 0
        if val > largest_value:
            largest_value = val; largest_ticker = ticker

        # ── Volatility gate — skip money-market / cash-equivalent ETFs ─
        try:
            ann_vol = ohlcv_corrected["Close"].pct_change().std() * (252 ** 0.5) * 100
            if ann_vol < 1.0:
                continue
        except Exception:
            pass

        try:
            snap = _build_technical_snapshot(ohlcv_corrected, ticker, shares)
            score, signals = score_ticker_interestingness(snap)
            if score > best_score:
                best_score = score; best_ticker = ticker
                best_snap  = snap;  best_signals = signals
        except Exception:
            continue

    if best_ticker is None or best_score == 0:
        fb = largest_ticker or (list(positions.keys())[0] if positions else "SWDA.L")
        if fb in ohlcv_data:
            try:
                from backend.services import currency_utils
                ohlcv_corrected = currency_utils.normalize_ohlcv(fb, ohlcv_data[fb])
                best_snap    = _build_technical_snapshot(ohlcv_corrected, fb, positions.get(fb, 1.0))
                best_signals = ["Largest position (no active signal)"]
            except Exception:
                best_snap = {}
        best_ticker = fb

    return best_ticker, best_snap or {}, best_signals


# ─────────────────────────────────────────────────────────────────────────────
# 2.  PORTFOLIO DATA
# ─────────────────────────────────────────────────────────────────────────────

def _get_db_freshness(account: str):
    """Return (last_saved_dt, is_fresh)."""
    try:
        ts_str = storage.get_latest_account_run_timestamp(account)
        if not ts_str:
            return None, False
            
        last_dt = pd.to_datetime(ts_str)
        if last_dt.tzinfo is None:
            last_dt = last_dt.tz_localize("UTC")
            
        now = datetime.datetime.now(datetime.timezone.utc)
        is_fresh = (now - last_dt).total_seconds() < _STALE_HOURS * 3600
        return last_dt, is_fresh
    except Exception as exc:
        log.error("_get_db_freshness error: %s", exc)
        return None, False


def _load_account_stats(account: str):
    """Pull perf stats. 1M/YTD/Sharpe = None when history is too short."""
    try:
        cached = storage.load_latest_portfolio(account)
        if cached is None:
            return None
        df = cached["df_perf"]
        if df.empty or "TWR_Index" not in df.columns:
            return None

        twr   = df["TWR_Index"]
        nav   = float(df["Total NAV"].iloc[-1])
        today = df.index[-1]

        # Weekly — last 6 index positions (5 trading days)
        week_ago_idx = max(0, len(twr) - 6)
        weekly = float(twr.iloc[-1] / twr.iloc[week_ago_idx] - 1) if twr.iloc[week_ago_idx] > 0 else 0.0

        # 1 Month — last 30 rows, identical to visuals.py _pr(30)
        last_month = float(twr.iloc[-1] / twr.iloc[-30] - 1) if len(twr) >= 30 else None

        # YTD — only if data existed before Jan 1
        first_of_year = pd.Timestamp(today.replace(month=1, day=1))
        if df.index[0] < first_of_year:
            seg = df[df.index >= first_of_year]
            s   = float(seg["TWR_Index"].iloc[0]) if not seg.empty else None
            ytd = float(twr.iloc[-1] / s - 1) if s and s > 0 else None
        else:
            ytd = None

        # Sharpe — only with >=3 months
        # Exclude zero returns (weekends/non-trading days stored as 0.0 not NaN)
        months = (df.index[-1] - df.index[0]).days / 30.44
        if months >= 3 and "Daily_Return" in df.columns:
            dr  = df["Daily_Return"].replace(0, pd.NA).dropna().tail(252)
            exc = dr - 0.04 / 252
            sharpe = round(float(exc.mean() / exc.std() * 252 ** 0.5), 2) if len(dr) > 1 and exc.std() > 0 else None
        else:
            sharpe = None

        last_saved, is_fresh = _get_db_freshness(account)
        return {
            "account": account, "nav": nav, "weekly": weekly,
            "last_month": last_month, "ytd": ytd, "sharpe": sharpe,
            "months": months, "positions": cached["positions"],
            "df_perf": df, "last_saved": last_saved, "is_fresh": is_fresh,
        }
    except Exception:
        return None


def _load_ticker_weekly_pnl(account: str) -> list:
    """Per-ticker weekly £ PnL, sorted best→worst.

    Weight is derived from value_gbp / total_nav_gbp (joined from
    portfolio_snapshots) rather than the stored weight column, which is
    often NULL for historical rows because save_portfolio_run() only knows
    the *final* positions dict and cannot reconstruct per-date holdings.
    """
    try:
        from backend.services.database import get_app_connection
        cutoff = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
        with get_app_connection() as conn:
            df = pd.read_sql_query(
                """
                SELECT t.date, t.ticker, t.value_gbp,
                       s.total_nav_gbp
                FROM   portfolio_ticker_daily t
                LEFT JOIN portfolio_snapshots s
                       ON s.account = t.account AND s.date = t.date
                WHERE  t.account=%s AND t.date>=%s
                ORDER  BY t.date ASC
                """,
                conn, params=(account, cutoff),
            )
        if df.empty:
            return []

        df["date"] = pd.to_datetime(df["date"])

        wide_val = df.pivot(index="date", columns="ticker", values="value_gbp").ffill()
        # Recompute weight live: ticker_value / total_nav on that date
        nav_by_date = df.drop_duplicates("date").set_index("date")["total_nav_gbp"]

        results = []
        for t in wide_val.columns:
            s = wide_val[t].dropna()
            if len(s) < 2:
                continue
            start = float(s.iloc[max(0, len(s) - 6)])
            end   = float(s.iloc[-1])
            if start <= 0:
                continue
            last_date = s.index[-1]
            nav       = nav_by_date.get(last_date, 0.0) or 0.0
            weight    = end / nav if nav > 0 else 0.0
            results.append({
                "ticker":         t,
                "weekly_pct":     (end / start) - 1,
                "weekly_pnl_gbp": end - start,
                "value_gbp":      end,
                "weight":         weight,
            })
        return sorted(results, key=lambda x: x["weekly_pnl_gbp"], reverse=True)
    except Exception:
        return []


def _load_ticker_weights(account: str) -> pd.DataFrame:
    """Return the latest per-ticker weights/values for `account`.

    Uses the exact same sources as visuals.py's holdings table:
      positions — storage.load_latest_portfolio()  (always current)
      prices    — storage.load_last_prices()        (pence-corrected GBP)

    Bypasses portfolio_ticker_daily entirely — that table has stale/NULL
    weights after trades and cannot be trusted for weight calculations.
    """
    try:
        cached = storage.load_latest_portfolio(account)
        if cached is None:
            return pd.DataFrame()
        positions = cached.get("positions", {})
        if not positions:
            return pd.DataFrame()

        last_px_df = storage.load_last_prices(account)
        if last_px_df.empty:
            return pd.DataFrame()
        last_px = last_px_df.iloc[-1].to_dict()

        rows = []
        total_equity = 0.0
        for ticker, shares in positions.items():
            if shares <= 0.001:
                continue
            price = last_px.get(ticker)
            if price is None or pd.isna(price) or price <= 0:
                continue
            value = shares * price
            total_equity += value
            rows.append({"ticker": ticker, "shares": shares,
                         "price_gbp": price, "value_gbp": value})

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        # Include cash so weights sum correctly (matching visuals.py denominator)
        df_perf = cached.get("df_perf", pd.DataFrame())
        cash = 0.0
        if not df_perf.empty and "Cash" in df_perf.columns:
            val = df_perf["Cash"].iloc[-1]
            cash = float(val) if val is not None and not (isinstance(val, float) and np.isnan(val)) else 0.0
        total_nav = total_equity + cash
        df["weight"] = df["value_gbp"] / total_nav if total_nav > 0 else 0.0
        return df.sort_values("value_gbp", ascending=False).reset_index(drop=True)

    except Exception as exc:
        log.error("_load_ticker_weights(%s) failed: %s", account, exc, exc_info=True)
        return pd.DataFrame()


def _perf_from_index(series, label=None):
    """Weekly / MTD / YTD from a rebased index pd.Series (base=100)."""
    today      = series.index[-1]
    week_ago   = max(0, len(series) - 6)
    weekly     = float(series.iloc[-1] / series.iloc[week_ago] - 1) if series.iloc[week_ago] > 0 else None
    mtd_s      = series[series.index >= pd.Timestamp(today.year, today.month, 1)]
    last_month = float(series.iloc[-1] / mtd_s.iloc[0] - 1) if (not mtd_s.empty and mtd_s.iloc[0] > 0) else None
    ytd_s      = series[series.index >= pd.Timestamp(today.year, 1, 1)]
    ytd        = float(series.iloc[-1] / ytd_s.iloc[0] - 1) if (not ytd_s.empty and ytd_s.iloc[0] > 0) else None
    out = {"weekly": weekly, "last_month": last_month, "ytd": ytd}
    if label is not None:
        out["label"] = label
    return out


def _load_iusa_stats(accounts: list, df_prices: pd.DataFrame | None = None, benchmark_ticker: str = "IUSA.L") -> dict | None:
    """Compute benchmark stats from the live df_prices series for the given ticker.
    Mainly used for IUSA variants (IUSA.L for GBP, IUSA.DE for EUR).

    Slices df_prices[benchmark_ticker], rebases to 100 on first valid date, then
    applies the same weekly/MTD/YTD window logic as _perf_from_index().
    Sharpe is computed from daily returns of the price series when >=3 months
    of data are available (same 4% risk-free rate, annualised, trailing 252 days).

    Falls back to reading Bench_NAV from portfolio_snapshots if df_prices
    is unavailable (headless scheduler path).
    """
    def _sharpe_from_prices(price_series: pd.Series) -> float | None:
        """Annualised Sharpe from a raw price series (4% risk-free, trailing 252 days)."""
        months = (price_series.index[-1] - price_series.index[0]).days / 30.44
        if months < 3:
            return None
        dr = price_series.pct_change().replace(0, pd.NA).dropna().tail(252)
        exc = dr - 0.04 / 252
        if len(dr) < 2 or exc.std() == 0:
            return None
        return round(float(exc.mean() / exc.std() * 252 ** 0.5), 2)

    def _fetch_series(ticker: str) -> pd.Series | None:
        """Fetch price history directly from yfinance (2y period)."""
        try:
            raw = yf.download(ticker, period="2y", auto_adjust=True, threads=False)
            if raw.empty:
                return None
            close = raw["Close"].squeeze().dropna()
            # Convert pence → GBP if London ticker
            from backend.services import currency_utils
            close = currency_utils.normalize_series(ticker, close)
            return close
        except Exception as e:
            log.warning("_load_iusa_stats yfinance fetch failed for %s: %s", ticker, e)
            return None

    try:
        # ── Primary path: use live df_prices if it has the requested ticker ──
        if df_prices is not None and not df_prices.empty and benchmark_ticker in df_prices.columns:
            series = df_prices[benchmark_ticker].dropna()
            if len(series) >= 60:   # need at least ~3 months
                rebased = series / series.iloc[0] * 100.0
                stats = _perf_from_index(rebased)
                stats["sharpe"] = _sharpe_from_prices(series)
                return stats

        # ── Secondary path: fetch directly from yfinance ─────────────────
        series = _fetch_series(benchmark_ticker)
        if series is not None and len(series) >= 60:
            rebased = series / series.iloc[0] * 100.0
            stats = _perf_from_index(rebased)
            stats["sharpe"] = _sharpe_from_prices(series)
            return stats

        # ── Fallback: read Bench_NAV stored during last engine run ────────
        best_df = None
        best_ts = ""
        for acct in accounts:
            cached = storage.load_latest_portfolio(acct)
            if cached is None:
                continue
            ts = cached.get("run_timestamp", "") or ""
            if ts > best_ts:
                best_ts = ts
                best_df = cached.get("df_perf")

        if best_df is None or best_df.empty or "Bench_NAV" not in best_df.columns:
            return None

        series = best_df["Bench_NAV"].dropna()
        if len(series) < 6:
            return None

        stats = _perf_from_index(series)
        stats["sharpe"] = _sharpe_from_prices(series)
        return stats

    except Exception as exc:
        log.warning("_load_iusa_stats failed for %s: %s", benchmark_ticker, exc)
        return None


# Labels that identify the simple IUSA.L index line stored in
# benchmark_snapshots — must NOT appear as the synthetic benchmark row.
_IUSA_LABELS = {"S&P 500 (IUSA.L)", "IUSA.L", "S&P 500"}


def _load_benchmark_stats(
    accounts: list,
    df_benchmark_perf_session=None,
    benchmark_label_session: str = "Synthetic Benchmark",
    synthetic_benchmark: str | None = None,
) -> dict | None:
    """Return synthetic benchmark stats for the performance table.

    Priority order (per spec):
      1. Live session df_benchmark_perf  — passed directly from app.py;
         always current, always reflects what the user last ran.
      2. DB (benchmark_snapshots)        — fallback for the headless scheduler
         or when the user hasn't run the Benchmark Builder this session.
      3. NA sentinel dict                — when neither is available; renders
         as N/A cells with a tooltip rather than hiding the row entirely.

    Filters out IUSA.L / S&P 500 index-line entries (shown separately via
    _load_iusa_stats).
    """
    def _sharpe_from_df(df):
        months = (df.index[-1] - df.index[0]).days / 30.44
        if months >= 3 and "Daily_Return" in df.columns:
            dr  = df["Daily_Return"].replace(0, pd.NA).dropna().tail(252)
            exc = dr - 0.04 / 252
            return round(float(exc.mean() / exc.std() * 252 ** 0.5), 2) if len(dr) > 1 and exc.std() > 0 else None
        return None

    try:
        # ── Priority 1: live session DataFrame ───────────────────────────
        if df_benchmark_perf_session is not None and not df_benchmark_perf_session.empty:
            if "TWR_Index" in df_benchmark_perf_session.columns:
                twr = df_benchmark_perf_session["TWR_Index"].dropna()
                if len(twr) >= 6:
                    label = benchmark_label_session
                    if label not in _IUSA_LABELS:
                        stats = _perf_from_index(twr, label=label)
                        stats["sharpe"] = _sharpe_from_df(df_benchmark_perf_session)
                        return stats

        # ── Priority 2: DB (benchmark_snapshots) ─────────────────────────
        best_result = None
        best_ts     = None

        search_accounts = list(accounts)
        if "Consolidated" not in search_accounts:
            search_accounts.append("Consolidated")

        # Pass A: If an explicit synthetic benchmark is requested, look specifically for that
        if synthetic_benchmark and synthetic_benchmark not in _IUSA_LABELS:
            for acct in search_accounts:
                cached = storage.load_latest_benchmark(acct, benchmark_label=synthetic_benchmark)
                if cached is not None:
                    ts = cached.get("run_timestamp")
                    if ts is not None:
                        ts_dt = pd.to_datetime(ts)
                        if best_ts is None or ts_dt > best_ts:
                            best_ts     = ts_dt
                            best_result = cached

        # Pass B: Fallback to latest non-IUSA benchmark if not specified or not yet found
        if best_result is None:
            for acct in search_accounts:
                cached = storage.load_latest_benchmark(acct)
                if cached is None:
                    continue
                lbl = cached.get("benchmark_label", "")
                if lbl in _IUSA_LABELS:
                    continue          # skip IUSA index-line entries
                ts = cached.get("run_timestamp")
                if ts is not None:
                    ts_dt = pd.to_datetime(ts)
                    if best_ts is None or ts_dt > best_ts:
                        best_ts     = ts_dt
                        best_result = cached

        if best_result is not None:
            df    = best_result["df_benchmark_perf"]
            label = best_result.get("benchmark_label", synthetic_benchmark or "Synthetic Benchmark")
            if not df.empty and "TWR_Index" in df.columns:
                twr = df["TWR_Index"].dropna()
                if len(twr) >= 6:
                    stats = _perf_from_index(twr, label=label)
                    stats["sharpe"] = _sharpe_from_df(df)
                    return stats

        # ── Priority 3: NA sentinel — row shown with N/A values ──────────
        display_label = synthetic_benchmark or benchmark_label_session
        if display_label in _IUSA_LABELS:
            display_label = "Synthetic Benchmark"
        return {
            "label":      display_label,
            "weekly":     None,
            "last_month": None,
            "ytd":        None,
            "sharpe":     None,
            "na_tooltip": "Visit the Benchmark Builder tab and click Recalculate to populate this row.",
        }

    except Exception as exc:
        log.warning("_load_benchmark_stats failed: %s", exc)
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 3.  SNAPSHOT FOLDER AUTO-SELECTOR
# ─────────────────────────────────────────────────────────────────────────────

def _find_snapshot_folders() -> list:
    """Return [(Path, mtime_dt)] sorted newest first.

    A folder qualifies if it contains at least one .md or .pdf file —
    supporting the mobile-upload use case where only a PDF is dropped in
    (e.g. via Google Drive sync) without a corresponding .md file.
    """
    def _folder_mtime(folder: Path):
        files = list(folder.glob("*.md")) + list(folder.glob("*.pdf"))
        if not files:
            return None
        return datetime.datetime.fromtimestamp(max(f.stat().st_mtime for f in files))

    candidates = []
    if not _SNAPSHOTS_ROOT.exists():
        return candidates
    # Root itself
    mt = _folder_mtime(_SNAPSHOTS_ROOT)
    if mt:
        candidates.append((_SNAPSHOTS_ROOT, mt))
    # Sub-dirs
    for sub in _SNAPSHOTS_ROOT.iterdir():
        if sub.is_dir():
            mt = _folder_mtime(sub)
            if mt:
                candidates.append((sub, mt))
    return sorted(candidates, key=lambda x: x[1], reverse=True)


def _load_articles_from_folder(folder: Path, max_articles: int = 10) -> tuple:
    articles_text, n_art = _load_articles_raw(folder, max_articles)
    return articles_text, n_art


def _load_articles_raw(folder: Path, max_articles: int = 10) -> tuple:
    """Load .md and .pdf files from folder, returning (combined_text, count).

    PDFs are extracted via pdfplumber (text-only, no graphics — matching the
    stripped PDFs saved from Barclays Live).  .md files are read directly.
    Files are sorted newest-first; the newest single file that looks like a
    Barclays PM Digest (detected by _is_pm_digest) is always included first
    regardless of position in the sort order.
    """
    all_files = sorted(
        list(folder.glob("*.md")) + list(folder.glob("*.pdf")),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )[:max_articles]

    if not all_files:
        return "No research articles found.", 0

    def _read(p: Path) -> str:
        if p.suffix.lower() == ".pdf":
            try:
                import pdfplumber
                pages = []
                with pdfplumber.open(p) as pdf:
                    for page in pdf.pages:
                        t = page.extract_text()
                        if t:
                            pages.append(t)
                return "\n\n".join(pages)
            except Exception as exc:
                log.warning("_load_articles_raw: PDF extract failed for %s: %s", p.name, exc)
                return ""
        return p.read_text(encoding="utf-8", errors="ignore")

    blocks = []
    for p in all_files:
        text = _read(p)
        if text:
            blocks.append(f"=== {p.stem} ===\n{text[:150_000]}")

    return "\n\n".join(blocks), len(blocks)


# PM Digest detection — these substrings appear consistently in the header/TOC
_DIGEST_SIGNALS = [
    "Global Portfolio Manager",
    "Thinking Macro",
    "Global Strategy & Economic Outlook",
    "Equity Strategy",
    "Rates Strategy",
    "Economic Outlook",
    "Emerging Markets Strategy",
]

# Maps digest ## section headers to labelled injection blocks
# Each entry: (list_of_substrings_to_match, label_string)
_DIGEST_SECTION_MAP = [
    (["Thinking Macro", "Global Macro Thoughts"],                       "[MACRO SECTION]"),
    (["Global Strategy & Economic Outlook", "Economic Outlook",
      "EA and UK Themes"],                                               "[MACRO SECTION]"),
    (["Equity Strategy", "U.S. Equities", "United States", "Europe",
      "Best of Barclays", "U.S. Internet"],                              "[EQUITY SECTION]"),
    (["Emerging Markets Strategy", "FX and EM Views",
      "Emerging Markets"],                                               "[EM/FX SECTION]"),
    (["Rates Strategy", "Credit Strategy"],                             "[RATES/CREDIT — CONTEXT ONLY]"),
    (["Regulars", "Events", "Conference Calls",
      "Product Management Group"],                                       "[SKIP]"),
]


def _is_pm_digest(text: str) -> bool:
    """Return True if text looks like a Barclays PM Digest."""
    hits = sum(1 for s in _DIGEST_SIGNALS if s.lower() in text.lower())
    return hits >= 3


def _parse_digest(text: str) -> str:
    """Parse a Barclays PM Digest into labelled injection blocks.

    Splits the text on ## level headers (the stable top-level sections),
    maps each section to its label, then concatenates into a structured
    string ready for prompt injection.

    If the text is not a PM Digest, returns it unchanged (fallback path).
    """
    if not _is_pm_digest(text):
        return text

    # Split on lines beginning with exactly "## " (top-level sections)
    sections: list[tuple[str, str]] = []   # (header, body)
    current_header = "__preamble__"
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            sections.append((current_header, "\n".join(current_lines)))
            current_header = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    sections.append((current_header, "\n".join(current_lines)))

    # Bucket each section into a labelled block
    labelled: dict[str, list[str]] = {
        "[MACRO SECTION]":                  [],
        "[EQUITY SECTION]":                 [],
        "[EM/FX SECTION]":                  [],
        "[RATES/CREDIT — CONTEXT ONLY]":    [],
    }

    for header, body in sections:
        label = None
        for substrings, lbl in _DIGEST_SECTION_MAP:
            if any(s.lower() in header.lower() for s in substrings):
                label = lbl
                break
        if label == "[SKIP]" or label is None:
            continue
        chunk = f"### {header}\n{body.strip()}"
        labelled[label].append(chunk)

    # Build output — only include labels that have content
    out_parts = []
    for label, chunks in labelled.items():
        if chunks:
            out_parts.append(f"{label}\n\n" + "\n\n".join(chunks))

    if not out_parts:
        return text  # nothing was bucketed — return raw

    return "\n\n" + "\n\n─────────────────────────────────────────\n\n".join(out_parts)



_distil_last_error: str = ""   # module-level, set on each call for UI debugging


def distil_digest(articles: str, api_key: str) -> dict | None:
    """Call 1 of 2 — distil the PM Digest into a structured brief.

    Reads the raw (or parsed) digest text and asks Gemini to return a
    compact JSON brief.  The brief is then injected into the main prompt
    (Call 2) instead of the raw 74k-char document, giving the main
    generation step clean, pre-digested signal rather than raw markdown.

    Returns a dict with keys:
        dominant_theme   str   — one sentence, the week's single biggest development
        macro_notes      list  — 4-6 str bullets from the macro section
        equity_notes     list  — 4-6 str bullets from the equity section
        em_fx_notes      list  — 2-3 str bullets from EM/FX section
        tail_risks       list  — exactly 3 named risk strings
        article_list     list  — [{title, url, section}] for Additional Reading

    Returns None on failure (caller falls back to raw articles injection).
    Retries once after a short delay on transient API / JSON-parse failures.
    """
    global _distil_last_error
    import time

    def _attempt(parsed_text: str) -> dict | None:
        prompt = f"""You are a senior research analyst. Read the following Barclays research content and return a structured JSON brief for a portfolio manager.

{parsed_text}

Return ONLY valid JSON, no markdown fences:
{{
  "dominant_theme": "One sentence — the single most market-moving development in this digest.",
  "macro_notes": [
    "Bullet 1 — specific data point, central bank signal, or directional view with level",
    "Bullet 2",
    "Bullet 3",
    "Bullet 4",
    "Bullet 5",
    "Bullet 6"
  ],
  "equity_notes": [
    "Bullet 1 — specific regional move, sector rotation, or factor view",
    "Bullet 2",
    "Bullet 3",
    "Bullet 4",
    "Bullet 5",
    "Bullet 6"
  ],
  "em_fx_notes": [
    "Bullet 1 — EM or FX specific view",
    "Bullet 2"
  ],
  "tail_risks": [
    "Named risk 1 — specific, not generic",
    "Named risk 2",
    "Named risk 3"
  ],
  "article_list": [
    {{"title": "Full article title", "url": "https://... or empty string if not available", "section": "Macro|Equity|EM/FX|Rates/Credit"}}
  ]
}}

Rules:
- macro_notes: draw only from [MACRO SECTION] content. Include specific numbers, dates, levels where cited.
- equity_notes: draw only from [EQUITY SECTION]. Name specific regions (SPX, SX5E, Nikkei, FTSE, EM) and sectors.
- em_fx_notes: draw from [EM/FX SECTION]. If absent, return 1-2 bullets from macro with EM/FX colour.
- tail_risks: must be named scenarios from the digest, not generic phrases like "geopolitical risk".
- article_list: FIRST entry must always be the PM Digest publication itself — use title "Barclays Global Portfolio Manager's Digest" and for url extract the source URL from the frontmatter (look for "source: https://..." near the top of the document), otherwise empty string, section "Digest". Then extract every distinct article title mentioned in the digest. For each article url, use the full https://live.barcap.com URL if present in the source text next to that article, otherwise use empty string. For section, classify as one of: Macro, Equity, EM/FX, Rates/Credit, Other.
- Return between 6-10 bullets for macro_notes and equity_notes. Do not pad with vague sentences.
"""
        model = _gemini_model(api_key)
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.2},
        )
        raw = re.sub(r"^```json\s*|^```\s*|\s*```$", "", response.text.strip(), flags=re.MULTILINE).strip()

        def _try_parse(s: str):
            """Attempt JSON parse with progressive cleaning."""
            # Helper to escape literal newlines inside string literals in JSON
            def _escape_strings(text: str) -> str:
                parts = []
                in_string = False
                escaped = False
                current_chunk = []
                for char in text:
                    if in_string:
                        if escaped:
                            current_chunk.append(char)
                            escaped = False
                        elif char == '\\':
                            current_chunk.append(char)
                            escaped = True
                        elif char == '"':
                            current_chunk.append(char)
                            parts.append("".join(current_chunk))
                            current_chunk = []
                            in_string = False
                        elif char == '\n':
                            current_chunk.append('\\n')
                        elif char == '\r':
                            current_chunk.append('\\r')
                        else:
                            current_chunk.append(char)
                    else:
                        if char == '"':
                            in_string = True
                            current_chunk.append(char)
                        else:
                            parts.append(char)
                if current_chunk:
                    parts.append("".join(current_chunk))
                return "".join(parts)

            # Pass 1 — direct
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                pass

            # Pass 1.5 — direct after escaping literal newlines
            try:
                return json.loads(_escape_strings(s))
            except json.JSONDecodeError:
                pass

            # Pass 2 — extract outermost { ... }
            start = s.find("{"); end = s.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(_escape_strings(s[start:end+1]))
                except json.JSONDecodeError:
                    pass

            # Pass 3 — replace smart quotes and clean control chars
            cleaned = (s
                .replace("\u2018", "'").replace("\u2019", "'")
                .replace("\u201c", '"').replace("\u201d", '"')
                .replace("\u2013", "-").replace("\u2014", "-")
            )
            escaped_cleaned = _escape_strings(cleaned)
            start = escaped_cleaned.find("{"); end = escaped_cleaned.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(escaped_cleaned[start:end+1])
                except json.JSONDecodeError:
                    pass

            # Pass 4 — strip the article_list (most error-prone field) and return partial
            # This ensures dominant_theme + notes + risks are never lost due to a bad URL
            try:
                no_articles = re.sub(
                    r',?\s*"article_list"\s*:\s*\[.*?\]',
                    '', s, flags=re.DOTALL
                )
                escaped_no_articles = _escape_strings(no_articles)
                start = escaped_no_articles.find("{"); end = escaped_no_articles.rfind("}")
                if start != -1 and end > start:
                    partial = json.loads(escaped_no_articles[start:end+1])
                    partial["article_list"] = []   # empty but present
                    log.warning("distil_digest: recovered partial result (article_list stripped)")
                    return partial
            except Exception:
                pass
            return None

        result = _try_parse(raw)
        if result is not None:
            return result
        log.warning("distil_digest: all parse passes failed. Raw (first 400 chars): %s", raw[:400])
        return None

    parsed = _parse_digest(articles)

    # Extract the digest's own source URL directly from the raw frontmatter —
    # _parse_digest drops the preamble so Gemini never sees this line.
    _source_match = re.search(r'(?m)^source:\s*(https?://\S+)', articles)
    _digest_url = ""
    if _source_match:
        _digest_url = _source_match.group(1).strip()
    else:
        # Fallback: search for publication URL containing pubId
        pub_match = re.search(r'https?://live\.barcap\.com/[^)\s]*pubId=[a-zA-Z0-9]+[^)\s]*', articles[:2000])
        if pub_match:
            _digest_url = pub_match.group(0).rstrip("#")

    # Try with full parsed text first; if that fails, retry with a shorter slice
    # and a brief pause (handles transient rate-limit / context-window issues)
    for attempt, text_slice in enumerate([parsed[:120_000], parsed[:60_000]], start=1):
        try:
            result = _attempt(text_slice)
            if result is not None:
                # Patch the digest entry URL — always use the Python-extracted value
                # regardless of what Gemini put in article_list
                art_list = result.get("article_list")
                if not isinstance(art_list, list):
                    art_list = []
                    result["article_list"] = art_list

                # Check if there is a Digest entry and update it, or prepend it if missing
                digest_idx = -1
                for idx, art in enumerate(art_list):
                    if isinstance(art, dict) and art.get("section") == "Digest":
                        digest_idx = idx
                        break

                if digest_idx != -1:
                    if _digest_url:
                        art_list[digest_idx]["url"] = _digest_url
                elif _digest_url:
                    art_list.insert(0, {
                        "title": "Barclays Global Portfolio Manager's Digest",
                        "url": _digest_url,
                        "section": "Digest",
                    })
                return result
            log.warning("distil_digest attempt %d returned None — %s",
                        attempt, "retrying with shorter input" if attempt == 1 else "giving up")
            _distil_last_error = f"Attempt {attempt}: Gemini returned None or unparseable JSON"
        except Exception as exc:
            log.warning("distil_digest attempt %d exception: %s", attempt, exc)
            _distil_last_error = f"Attempt {attempt}: {type(exc).__name__}: {exc}"
        if attempt == 1:
            time.sleep(3)   # brief pause before retry

    return None


def _format_digest_brief(brief: dict) -> str:
    """Format the distillation brief into a compact prompt-ready string."""
    lines = []
    if brief.get("dominant_theme"):
        lines.append(f"DOMINANT THEME THIS WEEK:\n{brief['dominant_theme']}\n")
    if brief.get("macro_notes"):
        lines.append("MACRO HIGHLIGHTS:\n" + "\n".join(f"• {b}" for b in brief["macro_notes"]))
    if brief.get("equity_notes"):
        lines.append("\nEQUITY HIGHLIGHTS:\n" + "\n".join(f"• {b}" for b in brief["equity_notes"]))
    if brief.get("em_fx_notes"):
        lines.append("\nEM / FX HIGHLIGHTS:\n" + "\n".join(f"• {b}" for b in brief["em_fx_notes"]))
    if brief.get("tail_risks"):
        lines.append("\nTAIL RISKS NAMED IN THE DIGEST:\n" + "\n".join(f"• {r}" for r in brief["tail_risks"]))
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 4.  ETF NAME LOOKUP
# ─────────────────────────────────────────────────────────────────────────────

@cache_data(ttl=86400, show_spinner=False)
def _get_etf_names(tickers: tuple) -> dict:
    names = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).info
            names[t] = info.get("longName") or info.get("shortName") or t
        except Exception:
            names[t] = t
    return names


# ─────────────────────────────────────────────────────────────────────────────
# 4b. WEEKLY TRADE LEDGER LOOKUP  (Part A — no AI)
# ─────────────────────────────────────────────────────────────────────────────

def _last_n_trading_days(n: int = 5) -> datetime.date:
    """Return the date N trading days (Mon–Fri) ago from today."""
    today  = datetime.date.today()
    count  = 0
    cursor = today
    while count < n:
        cursor -= datetime.timedelta(days=1)
        if cursor.weekday() < 5:   # Mon=0 … Fri=4
            count += 1
    return cursor


def _load_weekly_trades(accounts: list) -> list[dict]:
    """Return ledger rows (Buy/Sell/Dividend/Fee) from the last 7 calendar days.

    Uses a 7-calendar-day lookback to match the reporting window shown in the
    newsletter header (e.g. "17 May – 24 May 2026").  The previous 5-trading-day
    window was narrower and could exclude trades made early in the week when the
    newsletter is generated on a Saturday.

    Reuses:
      - data_handler.get_sanitized_ledger()  — loads & date-parses the GSheet
      - engine.parse_transaction()           — extracts Action/Asset/Qty/Price
      - data_handler.apply_ticker_map()      — maps asset name → ticker
      - data_handler.get_ticker_map()        — for the ticker map

    Returns a list of dicts with keys:
      date, account, ticker, asset_name, direction, shares, price_gbp,
      consideration_gbp, row_type  ('trade' | 'dividend' | 'fee')
    Sorted by date descending.
    """
    from backend.services.data_handler import (
        get_sanitized_ledger,
        apply_ticker_map,
        get_ticker_map,
    )
    from backend.services.engine import parse_transaction

    # Use the same 7-calendar-day window the newsletter header label displays,
    # so trades are never silently excluded by a shorter lookback.
    period_end   = datetime.date.today()
    period_start = period_end - datetime.timedelta(days=7)

    try:
        ticker_map = get_ticker_map()
    except Exception:
        ticker_map = pd.DataFrame()

    results = []
    _INCLUDE_ACTIONS = {"Buy", "Sell", "Dividend", "Fee"}

    for account in accounts:
        try:
            df_ledger, is_sipp, _ = get_sanitized_ledger(account)
            if df_ledger.empty or "Date" not in df_ledger.columns:
                continue

            # Filter to reporting window
            df_ledger["Date"] = pd.to_datetime(df_ledger["Date"])
            mask = (
                (df_ledger["Date"].dt.date >= period_start) &
                (df_ledger["Date"].dt.date <= period_end)
            )
            df_window = df_ledger[mask].copy()
            if df_window.empty:
                continue

            # Parse each row
            parsed = df_window.apply(
                lambda r: parse_transaction(r, is_sipp=is_sipp), axis=1
            )
            parsed.columns = ["Action", "Asset Name", "Qty", "Price",
                               "Net Amount", "Auto Ticker"]
            df_window = pd.concat(
                [df_window.reset_index(drop=True),
                 parsed.reset_index(drop=True)], axis=1
            )

            # Apply ticker map so Auto Ticker is filled where possible
            df_window = apply_ticker_map(df_window, ticker_map)

            for _, row in df_window.iterrows():
                action = str(row.get("Action", "")).strip()
                if action not in _INCLUDE_ACTIONS:
                    continue

                net    = float(row.get("Net Amount", 0) or 0)
                qty    = float(row.get("Qty",        0) or 0)
                price  = float(row.get("Price",      0) or 0)

                ticker     = str(row.get("Auto Ticker", "") or "").strip()
                asset_name = str(row.get("Asset Name",  "") or "").strip()

                # Prices from the ledger are in GBX (pence) for LSE stocks —
                # convert to GBP for display.
                from backend.services import currency_utils
                price_gbp = currency_utils.normalize_price(ticker, price)

                ticker     = str(row.get("Auto Ticker", "") or "").strip()
                asset_name = str(row.get("Asset Name",  "") or "").strip()

                if action == "Buy":
                    direction = "BUY"
                    row_type  = "trade"
                elif action == "Sell":
                    direction = "SELL"
                    row_type  = "trade"
                elif action == "Dividend":
                    direction = "DIV"
                    row_type  = "dividend"
                else:   # Fee
                    direction = "FEE"
                    row_type  = "fee"

                results.append({
                    "date":              row["Date"].strftime("%d %b"),
                    "account":           account,
                    "ticker":            ticker or asset_name[:20],
                    "asset_name":        asset_name,
                    "direction":         direction,
                    "shares":            qty,
                    "price_gbp":         price_gbp,
                    "consideration_gbp": abs(net),
                    "row_type":          row_type,
                })

        except Exception as exc:
            log.warning("_load_weekly_trades(%s) failed: %s", account, exc)

    return sorted(results, key=lambda x: x["date"], reverse=True)



# ─────────────────────────────────────────────────────────────────────────────

def recalculate_single_account(
    acct: str,
    registry: pd.DataFrame = None,
    ticker_map: pd.DataFrame = None,
    active_bm_def: dict | None = None,
    active_bm_name: str = ""
) -> str | None:
    """
    Unified TWR engine entry point for a single account. 
    Now delegates to engine.run_recalculation_pipeline to ensure consistency.
    """
    try:
        from backend.services.engine import run_recalculation_pipeline
        return run_recalculation_pipeline(acct, force_full_prices=False, active_bm_name=active_bm_name)
    except Exception as e:
        import logging
        logging.getLogger("newsletter_ui").error(f"recalculate_single_account failed for {acct}: {e}", exc_info=True)
        return str(e)



def _recalculate_all_accounts() -> list[str]:
    """Run the full TWR engine for every registered account and save to DB."""
    errors = []
    try:
        from backend.services.data_handler import get_account_registry, get_ticker_map
        registry = get_account_registry()
        if registry.empty:
            return ["No accounts in registry — skipping recalculate."]

        try:
            ticker_map = get_ticker_map()
        except:
            ticker_map = pd.DataFrame()

        _registry_accounts = registry["Account Name"].tolist()
        all_accounts = list(dict.fromkeys(["Consolidated"] + _registry_accounts))
        log.info("Scheduler: recalculating %d account(s): %s", len(all_accounts), all_accounts)

        # ── Recalculate all saved synthetic benchmarks ─────────────────────
        active_bm_name = "__all__"

        for acct in all_accounts:
            err = recalculate_single_account(acct, registry, ticker_map, None, active_bm_name)
            if err:
                errors.append(err)

    except Exception as outer:
        errors.append(f"Recalculate ALL failed: {outer}")
        log.error("_recalculate_all_accounts error: %s", outer, exc_info=True)

    return errors


# ─────────────────────────────────────────────────────────────────────────────
# 5.  SCHEDULE PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

def _load_all_products() -> list[dict]:
    try:
        if _SCHEDULE_FILE.exists():
            data = json.loads(_SCHEDULE_FILE.read_text())
            if "products" in data and len(data["products"]) > 0:
                return data["products"]
            
            # Migration from legacy flat format
            if "day" in data or "hour" in data:
                migrated = [
                    {
                        "product_id": "faraglioni_en",
                        "display_name": "Faraglioni & Aegis (EN)",
                        "accounts": ["ISA", "SIPP"],
                        "language": "en",
                        "currency": "GBP",
                        "ccy_symbol": "£",
                        "benchmark_label": "S&P 500 (IUSA.L)",
                        "synthetic_benchmark": "Global 80/20",
                        "template_filename": "faraglioni_FINAL.html",
                        "output_filename": "newsletter_latest.html",
                        "recipients": data.get("additional_recipients", []),
                        "schedule": {
                            "day": data.get("day", "Saturday"),
                            "hour": data.get("hour", 8),
                            "minute": data.get("minute", 0),
                            "enabled": data.get("enabled", False),
                            "refresh_hours": data.get("refresh_hours", 2)
                        },
                        "product_type": "weekly",
                        "last_sent": data.get("last_sent")
                    },
                    {
                        "product_id": "faraglioni_it",
                        "display_name": "Faraglioni Gestioni (IT)",
                        "accounts": ["Papa IT"],
                        "language": "it",
                        "currency": "EUR",
                        "ccy_symbol": "€",
                        "benchmark_label": "Euro Stoxx 50 (MEUD.MI)",
                        "synthetic_benchmark": "Global 80/20",
                        "template_filename": "faraglioni_it_FINAL.html",
                        "output_filename": "newsletter_it_latest.html",
                        "recipients": [],
                        "schedule": {"day": "Saturday", "hour": 9, "minute": 0, "enabled": False, "refresh_hours": 2},
                        "product_type": "weekly",
                        "last_sent": None
                    }
                ]
                return migrated
    except Exception:
        pass
    
    # Default initial state
    return [
        {
            "product_id": "faraglioni_en",
            "display_name": "Faraglioni & Aegis (EN)",
            "accounts": ["ISA", "SIPP"],
            "language": "en",
            "currency": "GBP",
            "ccy_symbol": "£",
            "benchmark_label": "S&P 500 (IUSA.L)",
            "synthetic_benchmark": "Global 80/20",
            "template_filename": "faraglioni_FINAL.html",
            "output_filename": "newsletter_latest.html",
            "recipients": [],
            "schedule": {"day": "Saturday", "hour": 8, "minute": 0, "enabled": False, "refresh_hours": 2},
            "product_type": "weekly",
            "last_sent": None
        },
        {
            "product_id": "faraglioni_it",
            "display_name": "Faraglioni Gestioni (IT)",
            "accounts": ["Papa IT"],
            "language": "it",
            "currency": "EUR",
            "ccy_symbol": "€",
            "benchmark_label": "Euro Stoxx 50 (MEUD.MI)",
            "synthetic_benchmark": "Global 80/20",
            "template_filename": "faraglioni_it_FINAL.html",
            "output_filename": "newsletter_it_latest.html",
            "recipients": [],
            "schedule": {"day": "Saturday", "hour": 9, "minute": 0, "enabled": False, "refresh_hours": 2},
            "product_type": "weekly",
            "last_sent": None
        }
    ]

def _save_all_products(products: list[dict]) -> None:
    existing = {}
    try:
        if _SCHEDULE_FILE.exists():
            existing = json.loads(_SCHEDULE_FILE.read_text())
    except Exception:
        pass
    existing["products"] = products
    try:
        atomic_write_json(_SCHEDULE_FILE, existing)
    except Exception as e:
        log.warning(f"Could not save products: {e}")

def _load_schedule(product_id: str | None = None) -> dict:
    """Load schedule. If product_id is provided, load for that product. 
    Otherwise returns first product's schedule (legacy behavior)."""
    products = _load_all_products()
    if not products:
        # Default fallback
        return {"day": "Saturday", "hour": 8, "minute": 0, "enabled": False, "refresh_hours": 2, "last_sent": None}
    
    selected = products[0]
    if product_id:
        for p in products:
            if p.get("product_id") == product_id:
                selected = p
                break
    
    sched = dict(selected.get("schedule", {}))
    # Map product-level fields to flat legacy structure for backward compat
    sched["additional_recipients"] = selected.get("recipients", [])
    sched["last_sent"] = selected.get("last_sent")
    return sched


def _save_schedule(cfg: dict, product_id: str | None = None) -> None:
    """Save schedule to the JSON file. 
    Updates both the product-specific entry and root-level keys for compatibility.
    """
    existing = {}
    try:
        if _SCHEDULE_FILE.exists():
            existing = json.loads(_SCHEDULE_FILE.read_text())
    except Exception:
        pass

    # 1. Update root-level keys (legacy/global settings like auto_refresh)
    # Filter cfg to only include what was passed, avoiding overwriting other root keys
    for k, v in cfg.items():
        if k not in ["products"]: # Don't accidentally overwrite products list
            existing[k] = v

    # 2. Update product-specific entry
    products = existing.get("products", [])
    if not products:
        # If no products, we can't update specific ones, but existing root update is enough
        pass
    else:
        # If no product_id provided, default to first product for legacy compatibility
        target_pid = product_id or products[0].get("product_id")
        for p in products:
            if p.get("product_id") == target_pid:
                # Update product sub-fields
                p["schedule"] = {
                    "day": cfg.get("day", p["schedule"]["day"]),
                    "hour": cfg.get("hour", p["schedule"]["hour"]),
                    "minute": cfg.get("minute", p["schedule"]["minute"]),
                    "enabled": cfg.get("enabled", p["schedule"].get("enabled", False)),
                    "refresh_hours": cfg.get("refresh_hours", p["schedule"].get("refresh_hours", 2))
                }
                if "additional_recipients" in cfg:
                    p["recipients"] = cfg["additional_recipients"]
                if "last_sent" in cfg:
                    p["last_sent"] = cfg["last_sent"]
                break

    try:
        atomic_write_json(_SCHEDULE_FILE, existing)
    except Exception as e:
        log.warning(f"Could not save schedule: {e}")


def _run_newsletter_from_thread(product: dict | None = None, chosen_folder=None) -> None:
    """Generate and send the newsletter for a specific product.

    Used by: the in-app auto-scheduler thread, and the 🚀 Generate & Send Now button.
    Delegates all data assembly to assemble_newsletter_data() — guaranteed identical
    output to the UI Generate button.
    """
    import datetime as _dt
    import pandas as pd

    today        = _dt.date.today()
    period_start = today - _dt.timedelta(days=7)
    api_key      = GEMINI_API_KEY

    if product is None:
        products = _load_all_products()
        product = products[0] if products else {"currency": "GBP", "language": "en"}

    from backend.services.data_handler import get_account_registry
    registry = get_account_registry()
    all_known = registry[registry["Classification"] != "Sandbox"]["Account Name"].tolist()
    
    # Use product accounts if defined, otherwise fallback to all known accounts with data
    accounts_used = product.get("accounts")
    if not accounts_used:
        accounts_used = [a for a in all_known if _load_account_stats(a) is not None]
    else:
        # verify they have data
        accounts_used = [a for a in accounts_used if _load_account_stats(a) is not None]

    if not accounts_used:
        raise RuntimeError(f"No account data found for product {product.get('product_id')}. Run Recalculate & Save first.")

    log.info("Newsletter: assembling data for %d accounts…", len(accounts_used))
    data = assemble_newsletter_data(product, chosen_folder=chosen_folder, df_prices=None)  # df_prices not available headless — uses yfinance fallback
    if data is None:
        raise RuntimeError("assemble_newsletter_data returned None — check account data.")

    ft, ts, fs = pick_featured_ticker(data["all_pos"], pd.DataFrame(), data["ohlcv_data"])
    fn = data["names"].get(ft, ft)
    log.info("Newsletter: featured ticker = %s", ft)

    log.info("Newsletter: distilling digest…")
    digest_brief = None
    if data.get("articles") and _is_pm_digest(data["articles"]):
        digest_brief = distil_digest(data["articles"], api_key)
        if digest_brief:
            log.info("Newsletter: digest distilled — %d article(s)", len(digest_brief.get("article_list", [])))
        else:
            log.warning("Newsletter: digest distillation failed — falling back to raw articles")

    if product.get("language") == "it":
        prompt = _build_prompt_it(
            data["accounts_used"], data["stats_map"], data["ticker_ctx"], data["ranked_pnl"],
            _tech_prompt(ts) if ts else "Nessun dato tecnico.",
            ft, fn, fs, data["articles"], today, period_start,
            iusa_stats=data.get("iusa_stats"), benchmark_stats=data.get("benchmark_stats"),
            digest_brief=digest_brief,
        )
    else:
        prompt = _build_prompt(
            data["accounts_used"], data["stats_map"], data["ticker_ctx"], data["ranked_pnl"],
            _tech_prompt(ts) if ts else "No technical data available.",
            ft, fn, fs, data["articles"], today, period_start,
            iusa_stats=data.get("iusa_stats"), benchmark_stats=data.get("benchmark_stats"),
            digest_brief=digest_brief,
        )

    log.info("Newsletter: generating content…")
    content = generate_content(prompt, api_key)

    log.info("Newsletter: building HTML…")
    weekly_trades = _load_weekly_trades(data["accounts_used"])
    final_html = build_html(
        product, stats_map=data["stats_map"],
        content=content, technicals=ts,
        featured_ticker=ft, featured_name=fn, featured_signals=fs,
        ranked_pnl_all=data["ranked_pnl"],
        report_date=today, period_start=period_start,
        iusa_stats=data.get("iusa_stats"), benchmark_stats=data.get("benchmark_stats"),
        weekly_trades=weekly_trades,
        digest_brief=digest_brief,
    )

    out_file = _OUTPUT_PATH.parent / product.get("output_filename", "newsletter.html")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(final_html, encoding="utf-8")

    subj_template = product.get("subject_template", "Faraglioni & Aegis · Weekly Investor Letter · {date}")
    subject = subj_template.format(date=today.strftime('%d %B %Y'))
    
    _all_recipients = [RECIPIENT_EMAIL] + product.get("recipients", [])
    log.info("Newsletter: sending to %d recipient(s): %s…", len(_all_recipients), ", ".join(_all_recipients))
    ok = send_email(final_html, subject, recipients=_all_recipients, _from_thread=True)
    if not ok:
        raise RuntimeError("send_email returned False — check GMAIL_APP_PASSWORD")


class NewsletterSchedulerManager:
    """Process-global manager to track the single weekly newsletter scheduler thread."""
    def __init__(self):
        self.thread = None
        self.stop_event = None


@cache_resource
def get_newsletter_scheduler_manager() -> NewsletterSchedulerManager:
    """Return the global NewsletterSchedulerManager instance shared across all sessions."""
    return NewsletterSchedulerManager()


def _update_task_scheduler(cfg: dict | None = None) -> str:
    """Register the schedule using a pure-Python background thread.

    This replaces the schtasks approach entirely — no admin rights needed.
    The thread wakes every minute, checks whether it is time to send, and
    fires newsletter_scheduler.run() directly inside the Streamlit process.
    The thread is a daemon so it dies automatically when the app exits.
    """
    import threading

    manager = get_newsletter_scheduler_manager()

    # ── Stop any previously running scheduler thread globally ────────────────
    if manager.stop_event:
        manager.stop_event.set()   # signals the old thread to exit cleanly

    # Use a threading.Event so the loop can be stopped cleanly globally
    stop_event = threading.Event()
    manager.stop_event = stop_event

    def _scheduler_loop():
        import datetime as _dt
        refreshed_date = None   # date on which we last ran recalculate
        fired_dict     = {}

        _DAYS = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        def _offset_day(day_name: str, offset: int) -> str:
            idx = _DAYS.index(day_name)
            return _DAYS[(idx + offset) % 7]

        while not stop_event.is_set():
            now = _dt.datetime.now()
            today = now.date()
            now_time = now.time().replace(second=0, microsecond=0)
            
            all_products = _load_all_products()
            any_refresh_due = False

            for prod in all_products:
                sched = prod.get("schedule", {})
                if not sched.get("enabled"):
                    continue
                
                t_day = sched.get("day", "Saturday")
                t_h   = int(sched.get("hour", 8))
                t_m   = int(sched.get("minute", 0))
                r_h   = int(sched.get("refresh_hours", 2))
                
                _send_dt = _dt.datetime(2000, 1, 1, t_h, t_m)
                _refresh_dt = _send_dt - _dt.timedelta(hours=r_h)
                r_hour = _refresh_dt.hour
                r_minute = _refresh_dt.minute
                # If subtracting hours crosses midnight the day shifts — handle that
                r_day_offset = (_refresh_dt.date() - _dt.date(2000, 1, 1)).days
                r_day = _offset_day(t_day, r_day_offset)
                
                # ── Step 1: Refresh accounts ──
                refresh_target = _dt.time(r_hour, r_minute)
                if now.strftime("%A") == r_day and abs((_dt.datetime.combine(today, now_time) - _dt.datetime.combine(today, refresh_target)).total_seconds()) <= 60:
                    any_refresh_due = True
                    
                # ── Step 2: Send newsletter ──
                send_target = _dt.time(t_h, t_m)
                if now.strftime("%A") == t_day and abs((_dt.datetime.combine(today, now_time) - _dt.datetime.combine(today, send_target)).total_seconds()) <= 60:
                    pid = prod.get("product_id")
                    if fired_dict.get(pid) != today and prod.get("last_sent") != str(today):
                        log.info("Scheduler: sending newsletter for product %s", pid)
                        try:
                            _run_newsletter_from_thread(prod)
                            fired_dict[pid] = today
                            prod["last_sent"] = str(today)
                            _save_all_products(all_products)
                        except Exception as exc:
                            log.error("Scheduler: send failed for %s: %s", pid, exc, exc_info=True)
                            
            if any_refresh_due and refreshed_date != today:
                log.info("Scheduler: recalculating all accounts (refresh window)…")
                errs = _recalculate_all_accounts()
                refreshed_date = today
                if errs:
                    log.warning("Scheduler: recalc errors — %s", "; ".join(errs))
                else:
                    log.info("Scheduler: all accounts recalculated OK")

            # Sleep 30 s — fine-grained enough with the ±60 s window above
            stop_event.wait(timeout=30)
            
    thread = threading.Thread(target=_scheduler_loop, daemon=True, name="nl_scheduler")
    thread.start()
    manager.thread = thread
    return "Scheduler restarted for all active products."


# ─────────────────────────────────────────────────────────────────────────────
# 6.  GEMINI CONTENT GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def _gemini_model(api_key: str):
    return gemini_util.get_best_gemini_model(api_key)


def _fmt_pct(v, d: int = 1) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{'+' if v >= 0 else ''}{v * 100:.{d}f}%"

def _fmt_gbp(v: float) -> str:
    return f"£{v:,.0f}"

def _fmt_eur(v: float) -> str:
    return f"€{v:,.0f}"

def _fmt_eur_pct(v, d: int = 1) -> str:
    return _fmt_pct(v, d)


def assemble_newsletter_data(
    accounts_or_product,
    chosen_folder=None,
    df_prices: pd.DataFrame | None = None,
    df_benchmark_perf=None,
    benchmark_label: str = "Synthetic Benchmark",
) -> dict | None:
    """Single source-of-truth data assembly — used by the UI Generate button,
    the in-app auto-scheduler thread, and the 🚀 Generate & Send Now button.

    Returns a dict with keys:
        accounts_used, stats_map, ranked_pnl, all_pos,
        ohlcv_data, ticker_ctx, articles, n_art, names,
        iusa_stats, benchmark_stats
    """
    if isinstance(accounts_or_product, dict):
        accounts = accounts_or_product.get("accounts", [])
        benchmark_label = accounts_or_product.get("benchmark_label", benchmark_label)
        product = accounts_or_product
    else:
        accounts = accounts_or_product
        product = {"currency": "GBP"}
        
    stats_map = {}
    for acc in accounts:
        s = _load_account_stats(acc)
        if s is None:
            log.error("assemble_newsletter_data: missing or unparseable data for account '%s'", acc)
            log.warning(f"Account '{acc}' has no stored performance data.")
            return None
        stats_map[acc] = s

    # Cross-account P&L merge — handles tickers held in multiple accounts
    combined: dict = {}
    for acc in accounts:
        for r in _load_ticker_weekly_pnl(acc):
            t = r["ticker"]
            if t in combined:
                combined[t]["weekly_pnl_gbp"] += r["weekly_pnl_gbp"]
                old_start   = combined[t]["value_gbp"] - combined[t]["weekly_pnl_gbp"]
                new_start   = r["value_gbp"] - r["weekly_pnl_gbp"]
                total_start = old_start + new_start
                combined[t]["value_gbp"] += r["value_gbp"]
                combined[t]["weekly_pct"] = (combined[t]["weekly_pnl_gbp"] / total_start
                                             if total_start > 0 else 0)
                combined[t]["weight"] = max(combined[t]["weight"], r["weight"])
            else:
                combined[t] = dict(r)

    ranked_pnl = sorted(combined.values(), key=lambda x: x["weekly_pnl_gbp"], reverse=True)

    all_pos: dict = {}
    for acc in accounts:
        for t, s in stats_map[acc].get("positions", {}).items():
            all_pos[t] = all_pos.get(t, 0) + s

    all_tickers = tuple(sorted(t for t, s in all_pos.items() if s > 0.01))
    ohlcv_data  = _fetch_ohlcv(all_tickers) if all_tickers else {}
    names       = _get_etf_names(all_tickers) if all_tickers else {}

    for r in ranked_pnl:
        r["name"] = names.get(r["ticker"], r["ticker"])

    lines = []
    for acc in accounts:
        wdf = _load_ticker_weights(acc)
        if wdf.empty:
            continue
        for _, row in wdf.iterrows():
            t     = row["ticker"]
            pnl_r = combined.get(t)
            ret_s = _fmt_pct(pnl_r["weekly_pct"]) if pnl_r else "N/A"
            ccy_fmt = _fmt_gbp if product.get("currency", "GBP") == "GBP" else _fmt_eur
            ccy_sym = product.get("ccy_symbol", "£")
            v_val = row.get('value_gbp', 0) or 0
            lines.append(
                f"  {t} — {names.get(t, t)} ({acc}): "
                f"weight {(row.get('weight', 0) or 0)*100:.1f}% | "
                f"value {ccy_fmt(v_val)} | weekly {ret_s}"
            )
    ticker_ctx = "\n".join(lines) or "No holdings data."

    if chosen_folder is None:
        folders = _find_snapshot_folders()
        chosen_folder = folders[0][0] if folders else None

    articles, n_art = "No research articles found.", 0
    if chosen_folder:
        articles, n_art = _load_articles_from_folder(chosen_folder)

    # ── Section 1 benchmark rows ─────────────────────────────────────────
    # Pick appropriate benchmark ticker based on product currency
    # User requested IUSA (EUR denominated) for Italianportfolios.
    bench_ticker = "IUSA.L"
    if product.get("currency") == "EUR":
        bench_ticker = "IUSA.DE" # iShares S&P 500 EUR Dist (XETRA)
        
    iusa_stats = _load_iusa_stats(accounts, df_prices=df_prices, benchmark_ticker=bench_ticker)
    synthetic_bm = product.get("synthetic_benchmark") if isinstance(product, dict) else None
    benchmark_stats = _load_benchmark_stats(
        accounts,
        df_benchmark_perf_session=df_benchmark_perf,
        benchmark_label_session=benchmark_label,
        synthetic_benchmark=synthetic_bm,
    )

    return dict(
        accounts_used=accounts,
        product=product,
        stats_map=stats_map,
        ranked_pnl=ranked_pnl,
        all_pos=all_pos,
        ohlcv_data=ohlcv_data,
        ticker_ctx=ticker_ctx,
        articles=articles,
        n_art=n_art,
        names=names,
        iusa_stats=iusa_stats,
        benchmark_stats=benchmark_stats,
    )


def _build_prompt_it(
    accounts_used, stats_map, ticker_context, ranked_pnl,
    tech_prompt, featured_ticker, featured_name, featured_signals,
    articles, report_date, period_start,
    iusa_stats=None, benchmark_stats=None,
    digest_brief: dict | None = None,
) -> str:
    perf_lines = []
    for acc in accounts_used:
        s = stats_map[acc]
        perf_lines.append(
            f"{acc}: Weekly {_fmt_pct(s['weekly'])} | 1M {_fmt_pct(s.get('last_month'))} | "
            f"YTD {_fmt_pct(s['ytd'])} | Sharpe {s['sharpe'] if s['sharpe'] is not None else 'N/A'} | "
            f"NAV {_fmt_eur(s['nav'])}"
        )

    if iusa_stats:
        perf_lines.append(
            f"IUSA.DE (iShares S&P 500 EUR, benchmark): "
            f"Weekly {_fmt_pct(iusa_stats.get('weekly'))} | "
            f"MTD {_fmt_pct(iusa_stats.get('last_month'))} | "
            f"YTD {_fmt_pct(iusa_stats.get('ytd'))} | Sharpe {iusa_stats['sharpe'] if iusa_stats.get('sharpe') is not None else '—'}"
        )

    if benchmark_stats:
        bm_label = benchmark_stats.get("label", "Synthetic Benchmark")
        perf_lines.append(
            f"{bm_label} (benchmark sintetico): "
            f"Weekly {_fmt_pct(benchmark_stats.get('weekly'))} | "
            f"MTD {_fmt_pct(benchmark_stats.get('last_month'))} | "
            f"YTD {_fmt_pct(benchmark_stats.get('ytd'))} | Sharpe {benchmark_stats['sharpe'] if benchmark_stats.get('sharpe') is not None else 'N/A'}"
        )

    top3 = [r for r in ranked_pnl if r["weekly_pnl_gbp"] >= 0][:3]
    bot3 = list(reversed([r for r in ranked_pnl if r["weekly_pnl_gbp"] < 0]))[:3]

    def pnl_line(r):
        return (f"  {r['ticker']} — {r.get('name', r['ticker'])}: "
                f"{_fmt_pct(r['weekly_pct'])} / €{r['weekly_pnl_gbp']:+,.0f} PnL / "
                f"weight {r['weight']*100:.1f}%")

    pnl_block = ("TOP PERFORMERS (ordinati per PnL in €, dal più grande):\n"
                 + ("\n".join(pnl_line(r) for r in top3) or "  Nessuno positivo")
                 + "\n\nLAGGARDS (ordinati per PnL in €, dal peggiore):\n"
                 + ("\n".join(pnl_line(r) for r in bot3) or "  Nessuno negativo"))

    signals_str = ", ".join(featured_signals) if featured_signals else "nessun segnale"
    d2 = report_date + datetime.timedelta(days=2)

    return f"""Sei il Chief Investment Officer del Faraglioni Family Office. Stai scrivendo la lettera settimanale agli investitori.
Oggi: {report_date.strftime("%d %B %Y")}. Periodo: {period_start.strftime("%d %b")} – {report_date.strftime("%d %b %Y")}.
La lettera deve essere integralmente in LINGUA ITALIANA.

Tono: autorevole, professionale, senza ipotetici. Assumi che il lettore sia sofisticato. Usa i tag <strong> intorno alla frase chiave di ogni paragrafo.

═══ A: PERFORMANCE PORTAFOGLIO — NON ALTERARE QUESTI NUMERI ═══
{chr(10).join(perf_lines)}

═══ B: P&L DELLE POSIZIONI — ORDINE PER PnL IN €, MANTIENI ORDINE ═══
{pnl_block}

Contesto totale portafoglio:
{ticker_context}

CRITICAL: Per top_performers e laggards array, USA SOLO ticker dalla Sezione B. Mantieni i valori esatti in €.

═══ C: ANALISI TECNICA — {featured_ticker} ({featured_name}) ═══
Segnali attivi: {signals_str}
{tech_prompt}

═══ D: RICERCA MACRO ═══
{_format_digest_brief(digest_brief) if digest_brief else _parse_digest(articles)[:35_000]}

═══ REGOLE DI GENERAZIONE ═══
TUTTO L'OUTPUT (tranne chiavi JSON) DEVE ESSERE IN LINGUA ITALIANA.
macro_commentary.global_macro: 3–4 frasi in italiano. Focus sul quadro macroeconomico. 1 tag <strong>.
macro_commentary.equity_strategy: 3–4 frasi in italiano, strategia azionaria. 1 tag <strong>.
macro_commentary.portfolio_impact: 3–4 frasi in italiano. Impatto sul portafoglio nominando 2-3 ticker reali dalla Sez. B. 1 tag <strong>.

tech_featured_note: 2-3 frasi in italiano di analisi tecnica per {featured_ticker}.
trades: descrizioni in italiano basate sulla Sez. D. Action 'Acquisto', 'Vendita' o 'Monitoraggio'.
calendar: traduci event in italiano. days: Lun, Mar, Mer, Gio, Ven.
risks: 3 rischi specifici dalla Sez D.

Return ONLY valid JSON. Do not include markdown code blocks. Do not include text before or after the JSON object.
JSON Structure:
{{
  "macro_commentary": {{
    "global_macro": "...",
    "equity_strategy": "...",
    "portfolio_impact": "..."
  }},
  "top_performers": [
    {{"ticker":"X","name":"X","contribution":"+X%","pnl_gbp":"+€X","driver":"una frase in IT"}}
  ],
  "laggards": [
    {{"ticker":"X","name":"X","contribution":"-X%","pnl_gbp":"-€X","driver":"una frase in IT"}}
  ],
  "tech_featured_note": "...",
  "trades": [
    {{"tag":"Breakout","title":"Titolo IT","desc":"Desc IT","condition":"Trigger X Target Y Instrument Z"}}
  ],
  "calendar": [
    {{"day":"Lun {d2.strftime('%d %b')}","event":"...","impact":"high"}}
  ],
  "risks": "Rischio 1 · Rischio 2 · Rischio 3"
}}"""

def _build_prompt(
    accounts_used, stats_map, ticker_context, ranked_pnl,
    tech_prompt, featured_ticker, featured_name, featured_signals,
    articles, report_date, period_start,
    iusa_stats=None, benchmark_stats=None,
    digest_brief: dict | None = None,
) -> str:
    """Separated from generate_content() so the UI can preview it without an API call.

    digest_brief — optional pre-distilled brief from distil_digest().
    When present, Section D injects the formatted brief (~600 words) instead
    of the raw article text (~74k chars), producing sharper commentary.
    """

    perf_lines = []
    for acc in accounts_used:
        s = stats_map[acc]
        perf_lines.append(
            f"{acc}: Weekly {_fmt_pct(s['weekly'])} | 1M {_fmt_pct(s.get('last_month'))} | "
            f"YTD {_fmt_pct(s['ytd'])} | Sharpe {s['sharpe'] if s['sharpe'] is not None else 'N/A'} | "
            f"NAV {_fmt_gbp(s['nav'])}"
        )

    # Benchmark reference rows (context for the macro commentary — do not alter)
    if iusa_stats:
        perf_lines.append(
            f"IUSA.L (iShares S&P 500 GBP, benchmark): "
            f"Weekly {_fmt_pct(iusa_stats.get('weekly'))} | "
            f"MTD {_fmt_pct(iusa_stats.get('last_month'))} | "
            f"YTD {_fmt_pct(iusa_stats.get('ytd'))} | Sharpe {iusa_stats['sharpe'] if iusa_stats.get('sharpe') is not None else '—'}"
        )
    if benchmark_stats:
        bm_label = benchmark_stats.get("label", "Synthetic Benchmark")
        perf_lines.append(
            f"{bm_label} (synthetic benchmark): "
            f"Weekly {_fmt_pct(benchmark_stats.get('weekly'))} | "
            f"MTD {_fmt_pct(benchmark_stats.get('last_month'))} | "
            f"YTD {_fmt_pct(benchmark_stats.get('ytd'))} | Sharpe {benchmark_stats['sharpe'] if benchmark_stats.get('sharpe') is not None else 'N/A'}"
        )

    top3 = [r for r in ranked_pnl if r["weekly_pnl_gbp"] >= 0][:3]
    bot3 = list(reversed([r for r in ranked_pnl if r["weekly_pnl_gbp"] < 0]))[:3]

    def pnl_line(r):
        return (f"  {r['ticker']} — {r.get('name', r['ticker'])}: "
                f"{_fmt_pct(r['weekly_pct'])} / £{r['weekly_pnl_gbp']:+,.0f} PnL / "
                f"weight {r['weight']*100:.1f}%")

    pnl_block = ("TOP PERFORMERS (sorted by £ PnL, largest first):\n"
                 + ("\n".join(pnl_line(r) for r in top3) or "  None positive")
                 + "\n\nLAGGARDS (sorted by £ PnL, worst first):\n"
                 + ("\n".join(pnl_line(r) for r in bot3) or "  None negative"))

    signals_str = ", ".join(featured_signals) if featured_signals else "no dominant signal"
    d2 = report_date + datetime.timedelta(days=2)

    return f"""You are the Chief Investment Officer of Faraglioni & Aegis Family Office, writing the weekly investor letter.
Today: {report_date.strftime("%A, %d %B %Y")}. Period: {period_start.strftime("%d %b")} – {report_date.strftime("%d %b %Y")}.

Tone: authoritative, cross-asset, no fluff, no hedging language. Assume the reader knows what a bund is. This is a sophisticated private investor, not a retail client. Be opinionated and specific. Use <strong> tags around the single most important phrase per paragraph.

═══ A: PORTFOLIO PERFORMANCE — DO NOT ALTER THESE NUMBERS ═══
{chr(10).join(perf_lines)}
Note: "N/A" = insufficient history. Write "N/A" in output — do not fabricate.

═══ B: HOLDINGS P&L — ORDERED BY £ IMPACT, PRESERVE THIS ORDER ═══
{pnl_block}

Full holdings context:
{ticker_context}

CRITICAL: For top_performers and laggards arrays, ONLY use tickers from Section B. Preserve the sort order shown above exactly. Use the actual £ PnL and % figures.

═══ C: TECHNICAL ANALYSIS — {featured_ticker} ({featured_name}) ═══
Active signals firing this week: {signals_str}

{tech_prompt}

═══ D: BARCLAYS MACRO RESEARCH ═══
{_format_digest_brief(digest_brief) if digest_brief else _parse_digest(articles)[:35_000]}

═══ GENERATION RULES ═══

SECTION D SOURCE GUIDANCE (apply when Section D is a Barclays PM Digest):
  • [MACRO SECTION] → primary source for macro_commentary.global_macro
  • [EQUITY SECTION] → primary source for macro_commentary.equity_strategy
  • [EM/FX SECTION] → supporting colour for equity_strategy where relevant
  • [RATES/CREDIT — CONTEXT ONLY] → background only; do NOT make it the primary narrative focus for this equity-led portfolio
  If Section D is unstructured articles, apply the same logic by topic.

macro_commentary.global_macro: 3–4 sentences, NO bullet points. Lead with the single dominant theme from [MACRO SECTION]. Include cross-asset implications (rates, FX, credit) subordinately. State the CIO's forward base case with a specific directional view and name one risk scenario. One <strong> tag around the key phrase.
macro_commentary.equity_strategy: 3–4 sentences, equity-focused, NO bullet points. Source primarily from [EQUITY SECTION]. Name at least two regions (e.g. SPX, SX5E, EM, UK) with a directional characterisation for each. Include sector-level colour where material. One forward-looking sentence on where equity risk/reward sits from here. Reference rates or credit only where directly equity-relevant. One <strong> tag around the key phrase.
macro_commentary.portfolio_impact: 3–4 sentences, forward-looking, NO bullet points. Given the macro backdrop above, state what it implies for the coming week for the specific holdings in this portfolio. Must name 2–3 tickers explicitly from Section B. This is NOT attribution (that is handled by top_performers/laggards) — it is the read-through from macro to positioning. One <strong> tag around the key phrase.

top_performers / laggards: preserve the Section B order. Use exact figures.
tech_featured_note: 2–3 sentences on why {featured_ticker} is the most interesting technical setup this week. Reference specific signal values from Section C (e.g. "RSI at 68.2 and rising", "MACD crossed above signal on Tuesday"). Be concrete.
trades: every trade must cite a specific named article from Section D. No invented trades.
INVESTABLE UNIVERSE RULES — every entry in the 'trades' array MUST satisfy ALL of the following:
  1. Instrument type: ETF, investment trust, or index fund only. No single stocks, no bespoke derivatives, no structured products.
  2. Actionable: can be purchased in a UK ISA or SIPP account without special permissions.
  3. Grounded: must cite a named Barclays article from Section D above.
  4. Directional: state whether this is a new position, an add to an existing holding, a reduction, or a hedge via a specific named ETF. Use the tag 'Reduce' for trimming existing positions.
  5. Relevant: directly related to a theme affecting the current holdings in Section B.
  6. Include an 'Instrument' sub-field in the condition naming a specific ETF ticker (e.g. 'Instrument: SGLN.L or IGLN.L').
  If fewer than 2 valid ideas exist that meet all criteria, return only those that do — do not fabricate ideas.
calendar: Populate the calendar array with the most important scheduled macro events for the week of {d2.strftime('%d %b %Y')} (Mon–Fri). Use your knowledge of the standard macro release calendar for that specific week. Include only: central bank decisions (Fed/ECB/BoE/BoJ/BoC/RBA/SNB), inflation data (CPI/PCE/PPI/HICP/RPI), employment data (NFP/ADP/unemployment/initial claims/wages), PMI releases (ISM/S&P Global/Markit), GDP releases, retail sales, consumer confidence (Michigan/Conference Board). Exclude: earnings, company events, Barclays calls, any event with no confirmed date. The 'day' field is pre-filled below — do NOT change the day strings, only fill in 'event' and 'impact'. If a day has no qualifying event, use {{"day":"...", "event":"No major releases", "impact":"low"}}. Return all 5 days.
risks: one sentence, 3 specific named risks drawn from Section D — not generic phrases.

Return ONLY valid JSON. Do not include markdown code blocks. Do not include text before or after the JSON object.
JSON Structure:
{{
  "macro_commentary": {{
    "global_macro": "3–4 sentences. One <strong> tag.",
    "equity_strategy": "3–4 sentences. Two named regions with direction. One <strong> tag.",
    "portfolio_impact": "3–4 sentences. Name 2–3 tickers from Section B explicitly. One <strong> tag."
  }},
  "top_performers": [
    {{"ticker":"X","name":"Full ETF name","contribution":"+X.X%","pnl_gbp":"+£X,XXX","driver":"one sentence grounded in Section D"}},
    {{"ticker":"X","name":"Full ETF name","contribution":"+X.X%","pnl_gbp":"+£X,XXX","driver":"one sentence"}},
    {{"ticker":"X","name":"Full ETF name","contribution":"+X.X%","pnl_gbp":"+£X,XXX","driver":"one sentence"}}
  ],
  "laggards": [
    {{"ticker":"X","name":"Full ETF name","contribution":"-X.X%","pnl_gbp":"-£X,XXX","driver":"one sentence"}},
    {{"ticker":"X","name":"Full ETF name","contribution":"-X.X%","pnl_gbp":"-£X,XXX","driver":"one sentence"}}
  ],
  "tech_featured_note": "2-3 precise sentences with specific values from Section C.",
  "trades": [
    {{"tag":"Breakout","title":"Title from Barclays","desc":"Cite article name and specific view.","condition":"Trigger: X · Target: Y · Risk: Z · Instrument: ETF ticker"}},
    {{"tag":"Hedge","title":"Title","desc":"Cite article name.","condition":"Trigger: X · Instrument: ETF ticker"}},
    {{"tag":"Watch","title":"Title","desc":"Cite article name.","condition":"View: X · Target: Y · Risk: Z · Instrument: ETF ticker"}},
    {{"tag":"Reduce","title":"Title","desc":"Cite article name and trimming rationale.","condition":"Reduce: trim existing position · Instrument: ETF ticker"}}
  ],
  "calendar": [
    {{"day":"Mon {d2.strftime('%d %b')}","event":"<fill in>","impact":"<high|medium|low>"}},
    {{"day":"Tue {(d2+datetime.timedelta(1)).strftime('%d %b')}","event":"<fill in>","impact":"<high|medium|low>"}},
    {{"day":"Wed {(d2+datetime.timedelta(2)).strftime('%d %b')}","event":"<fill in>","impact":"<high|medium|low>"}},
    {{"day":"Thu {(d2+datetime.timedelta(3)).strftime('%d %b')}","event":"<fill in>","impact":"<high|medium|low>"}},
    {{"day":"Fri {(d2+datetime.timedelta(4)).strftime('%d %b')}","event":"<fill in>","impact":"<high|medium|low>"}}
  ],
  "risks": "Specific risk 1 · Specific risk 2 · Specific risk 3."
}}"""


def generate_content(prompt: str, api_key: str) -> dict:
    model    = _gemini_model(api_key)
    response = model.generate_content(
        prompt,
        generation_config={"temperature": 0.3},
    )
    
    cleaned = gemini_util.clean_json_text(response.text)
    
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.error("JSON Parse Error: %s", str(e))
        pass

    log.error("Gemini malformed JSON. Raw: " + cleaned)
    return {
        "macro_commentary": {
            "global_macro": "Markets navigated a volatile week as macro crosscurrents intensified. <strong>The portfolio's defensive tilt provided ballast</strong> against broad risk-off pressure.",
            "equity_strategy": "Equities oscillated between risk-on and risk-off, with US large caps outperforming European peers. Our base case remains cautiously constructive.",
            "portfolio_impact": "Quality and carry over beta into month-end. Positioning is reviewed in light of the macro backdrop above.",
        },
        "top_performers": [], "laggards": [],
        "tech_featured_note": "Technical signals are under active review. See the Technicals tab for full detail.",
        "trades": [{"tag": "Watch", "title": "Monitor positioning", "desc": "Current allocation appropriate pending macro clarity.", "condition": "View: Hold · Risk: Policy surprise"}],
        "calendar": [{"day": "Tue", "event": "US CPI", "impact": "high"}, {"day": "Fri", "event": "Nonfarm Payrolls", "impact": "high"}],
        "risks": "Central bank policy surprise · Geopolitical escalation · Earnings miss vs elevated multiples.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 7.  HTML BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _pct_class(v) -> str:
    if v is None:
        return ""
    return "pos" if v >= 0 else "neg"


def _bar_width(pnl_gbp: float, max_abs: float) -> int:
    return max(4, min(100, int(abs(pnl_gbp) / max_abs * 100))) if max_abs > 0 else 4


def _build_additional_reading_html(article_list: list) -> str:
    """Build Section 6 — Additional Reading from the distilled article_list.

    Each entry: {title, url, section}.  Shows a clickable link when url is
    non-empty, plain title otherwise.  Articles are grouped by section.
    Returns empty string if article_list is empty.
    """
    if not article_list:
        return ""

    # Group by section
    from collections import defaultdict
    groups: dict = defaultdict(list)
    for art in article_list:
        sec = art.get("section", "Other") or "Other"
        groups[sec].append(art)

    # Preferred section order — "Digest" first (the PM Digest itself), then research articles
    order = ["Digest", "Macro", "Equity", "EM/FX", "Rates/Credit", "Other"]
    _SECTION_COLOUR = {
        "Digest":       "var(--gold)",
        "Macro":        "var(--gold)",
        "Equity":       "#2e7d5e",
        "EM/FX":        "#1a6b8a",
        "Rates/Credit": "#7b3f8a",
        "Other":        "var(--slate)",
    }

    rows_html = ""
    for sec in order:
        arts = groups.get(sec, [])
        if not arts:
            continue
        col = _SECTION_COLOUR.get(sec, "var(--slate)")
        rows_html += (
            f'<div style="margin-bottom:18px;">'
            f'<div style="font-size:8px;font-weight:700;letter-spacing:1.5px;'
            f'text-transform:uppercase;color:{col};margin-bottom:8px;">{sec}</div>'
        )
        for art in arts:
            title = art.get("title", "").strip()
            url   = (art.get("url") or "").strip()
            is_digest_entry = (sec == "Digest")
            if not title:
                continue
            extra_style = (
                "font-weight:600;font-size:12px;" if is_digest_entry else ""
            )
            if url and url.startswith("http"):
                link = (
                    f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
                    f'style="color:var(--navy);text-decoration:none;font-size:11.5px;'
                    f'line-height:1.6;border-bottom:1px solid rgba(201,168,76,0.4);{extra_style}">'
                    f'{title}</a>'
                )
            else:
                link = (
                    f'<span style="color:var(--navy);font-size:11.5px;line-height:1.6;{extra_style}">'
                    f'{title}</span>'
                )
            row_style = "margin-bottom:10px;" if is_digest_entry else "margin-bottom:6px;"
            rows_html += f'<div style="{row_style}">→ {link}</div>'
        rows_html += '</div>'

    if not rows_html:
        return ""

    return f"""
    <!-- 06 Additional Reading -->
    <div class="section">
      <div class="section-label">06</div>
      <div class="section-title">Additional Reading</div>
      <div style="margin-top:4px;font-size:10px;color:var(--slate);margin-bottom:20px;">
        Source articles from this week's Barclays Global Portfolio Manager's Digest
      </div>
      {rows_html}
      <div style="margin-top:16px;padding:10px 14px;background:rgba(26,58,92,0.04);
        border-left:2px solid rgba(26,58,92,0.15);font-size:9.5px;color:var(--slate);line-height:1.7">
        Access to Barclays Live research requires a valid Barclays institutional subscription.
        Links open the original publication on live.barcap.com.
      </div>
    </div>"""


def build_html(
    accounts_or_product, stats_map, content, technicals,
    featured_ticker, featured_name, featured_signals,
    ranked_pnl_all, report_date, period_start,
    iusa_stats=None, benchmark_stats=None,
    weekly_trades=None,
    digest_brief: dict | None = None,
) -> str:
    if isinstance(accounts_or_product, dict):
        accounts_used = accounts_or_product.get("accounts", [])
        product = accounts_or_product
    else:
        accounts_used = accounts_or_product
        product = {"currency": "GBP", "language": "en", "ccy_symbol": "£", "template_filename": "faraglioni_FINAL.html"}

    ccy = product.get("currency", "GBP")
    ccy_sym = product.get("ccy_symbol", "£")
    lang = product.get("language", "en")
    fmt_money = _fmt_gbp if ccy == "GBP" else _fmt_eur

    template_name = product.get("template_filename", "faraglioni_FINAL.html")
    template_path = Path("Newsletter template") / template_name
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    html = template_path.read_text(encoding="utf-8")

    # ── Header dates ──────────────────────────────────────────────────────
    date_str   = report_date.strftime("%A, %d %B %Y")
    period_str = f"{period_start.strftime('%d %b')} – {report_date.strftime('%d %b %Y')}"
    html = re.sub(r"Wednesday, \d+ \w+ \d{4}", date_str, html)
    html = re.sub(r"\d+ \w+ – \d+ \w+ \d{4}", period_str, html)

    # ── S1: Performance table ──────────────────────────────────────────────
    rows = ""
    for acc in accounts_used:
        s = stats_map[acc]
        rows += f"""
          <tr>
            <td>{acc} Account</td>
            <td class="{_pct_class(s['weekly'])}">{_fmt_pct(s['weekly'])}</td>
            <td class="{_pct_class(s.get('last_month'))}">{_fmt_pct(s.get('last_month'))}</td>
            <td class="{_pct_class(s['ytd'])}">{_fmt_pct(s['ytd'])}</td>
            <td class="sharpe">{s['sharpe'] if s['sharpe'] is not None else '—'}</td>
          </tr>"""

    if len(accounts_used) > 1:
        def _wavg(key):
            pairs = [(stats_map[a][key], stats_map[a]["nav"]) for a in accounts_used if stats_map[a].get(key) is not None]
            if not pairs:
                return None
            tot_nav = sum(n for _, n in pairs)
            return sum(v * n for v, n in pairs) / tot_nav if tot_nav > 0 else None

        c_w = _wavg("weekly"); c_m = _wavg("last_month"); c_y = _wavg("ytd")
        sh_vals = [stats_map[a]["sharpe"] for a in accounts_used if stats_map[a].get("sharpe") is not None]
        c_sh = round(sum(sh_vals) / len(sh_vals), 2) if sh_vals else None
        rows += f"""
          <tr class="total-row">
            <td>Consolidated<span class="strategy-badge" style="color:rgba(201,168,76,0.55)">All Accounts</span></td>
            <td class="{_pct_class(c_w)}">{_fmt_pct(c_w)}</td>
            <td class="{_pct_class(c_m)}">{_fmt_pct(c_m)}</td>
            <td class="{_pct_class(c_y)}">{_fmt_pct(c_y)}</td>
            <td class="sharpe">{c_sh if c_sh is not None else '—'}</td>
          </tr>"""

    # ── Benchmark rows (lighter background, italic label, no Consolidated math)
    _BM_STYLE = (
        "background:rgba(237,242,247,0.6);"  # EDF2F7 tint
        "border-top:1px solid rgba(44,62,80,0.08);"
    )
    if iusa_stats:
        iw = iusa_stats.get("weekly"); im = iusa_stats.get("last_month"); iy = iusa_stats.get("ytd")
        rows += f"""
          <tr style="{_BM_STYLE}">
            <td><em style="font-size:12px">IUSA.L</em>
              <span class="strategy-badge" style="color:rgba(44,62,80,0.45);font-style:italic">iShares S&amp;P 500 ETF, GBP</span>
            </td>
            <td class="{_pct_class(iw)}">{_fmt_pct(iw)}</td>
            <td class="{_pct_class(im)}">{_fmt_pct(im)}</td>
            <td class="{_pct_class(iy)}">{_fmt_pct(iy)}</td>
            <td class="sharpe">{iusa_stats['sharpe'] if iusa_stats.get('sharpe') is not None else '—'}</td>
          </tr>"""

    if benchmark_stats:
        bm_label  = benchmark_stats.get("label", "Synthetic Benchmark")
        bw        = benchmark_stats.get("weekly")
        bm        = benchmark_stats.get("last_month")
        by        = benchmark_stats.get("ytd")
        bsh       = benchmark_stats.get("sharpe")
        na_tip    = benchmark_stats.get("na_tooltip", "")
        is_na_row = na_tip != ""   # sentinel: all values are None

        if is_na_row:
            # NA sentinel — show the row with N/A values and a tooltip
            rows += f"""
          <tr style="{_BM_STYLE}" title="{na_tip}">
            <td><em style="font-size:12px">{bm_label}</em>
              <span class="strategy-badge" style="color:rgba(44,62,80,0.45);font-style:italic">Benchmark Builder</span>
            </td>
            <td style="color:rgba(44,62,80,0.35);font-style:italic">N/A</td>
            <td style="color:rgba(44,62,80,0.35);font-style:italic">N/A</td>
            <td style="color:rgba(44,62,80,0.35);font-style:italic">N/A</td>
            <td class="sharpe" style="color:rgba(44,62,80,0.35);font-style:italic">N/A</td>
          </tr>"""
        else:
            rows += f"""
          <tr style="{_BM_STYLE}">
            <td><em style="font-size:12px">{bm_label}</em>
              <span class="strategy-badge" style="color:rgba(44,62,80,0.45);font-style:italic">Benchmark Builder</span>
            </td>
            <td class="{_pct_class(bw)}">{_fmt_pct(bw)}</td>
            <td class="{_pct_class(bm)}">{_fmt_pct(bm)}</td>
            <td class="{_pct_class(by)}">{_fmt_pct(by)}</td>
            <td class="sharpe">{bsh if bsh is not None else '—'}</td>
          </tr>"""
    elif iusa_stats is None:
        # Neither benchmark available — add a muted hint row
        rows += f"""
          <tr style="{_BM_STYLE}">
            <td colspan="5" style="font-size:11px;color:rgba(44,62,80,0.4);font-style:italic;text-align:center">
              Benchmark rows unavailable — run Benchmark Builder &amp; Recalculate to populate
            </td>
          </tr>"""

    html = re.sub(r'(<tbody>)(.*?)(</tbody>)', r'\1' + rows + r'\3', html, count=1, flags=re.DOTALL)

    # ── S2: Macro Commentary — three-part (PM Digest) or legacy single narrative ─
    mc     = content.get("macro_commentary")
    risks  = content.get("risks", "")
    risk_box = (
        "<div style='margin-top:16px;padding:12px 16px;"
        "background:rgba(139,38,53,0.06);border-left:3px solid var(--red);"
        "border-radius:2px;font-size:10.5px;color:var(--navy);line-height:1.7'>"
        "<strong style='color:var(--red);letter-spacing:1px;font-size:9px;text-transform:uppercase'>"
        f"Risks to Watch</strong><br>{risks}</div>"
    ) if risks else ""

    _GOLD  = ("display:inline-block;font-size:8px;font-weight:700;letter-spacing:1.5px;"
              "text-transform:uppercase;color:var(--gold);margin-bottom:6px;")
    _PARA  = "font-size:12.5px;line-height:1.75;color:var(--navy);margin-bottom:18px;"
    _HR    = "<hr style='border:none;border-top:1px solid rgba(201,168,76,0.18);margin:4px 0 16px'>"

    if mc and isinstance(mc, dict):
        gm = mc.get("global_macro", "").replace("\n\n", "<br><br>")
        eq = mc.get("equity_strategy", "").replace("\n\n", "<br><br>")
        pi = mc.get("portfolio_impact", "").replace("\n\n", "<br><br>")
        # Add class narrative-text so the template CSS handles strong colour,
        # font, and colour automatically — no inline overrides needed.
        narrative_body = (
            f'<div class="narrative-text" style="margin-bottom:22px;">'
            f'<span style="{_GOLD}">Global Macro Overview</span><br>{gm}'
            f'</div>'
            f'{_HR}'
            f'<div class="narrative-text" style="margin-bottom:22px;">'
            f'<span style="{_GOLD}">Equity Markets &amp; Strategy</span><br>{eq}'
            f'</div>'
            f'{_HR}'
            f'<div class="narrative-text" style="margin-bottom:22px;">'
            f'<span style="{_GOLD}">Portfolio Positioning &amp; Outlook</span><br>{pi}'
            f'</div>'
        )
    else:
        narrative = content.get("narrative", "").replace("\n\n", "<br><br>")
        narrative_body = f'<div class="narrative-text">{narrative}</div>'

    narrative_html = (
        f'<div class="narrative-box">\n'
        f'        {narrative_body}\n'
        f'        {risk_box}\n'
        f'        <div class="narrative-footer">\n'
        f'          <span>Faraglioni &amp; Aegis Research Desk</span>\n'
        f'          <span>Source: Barclays Research · Internal Analysis</span>\n'
        f'        </div>\n'
        f'      </div>')

    html = re.sub(
        r'<div class="narrative-box">.*?</div>\s*</div>\s*\n(\s*<!-- 03)',
        narrative_html + r'\n      </div>\n\n    \1',
        html, count=1, flags=re.DOTALL,
    )

    # ── S3: Contribution Analysis — ordered by £ PnL ─────────────────────
    tops    = [r for r in ranked_pnl_all if r["weekly_pnl_gbp"] >= 0][:3]
    lags    = list(reversed([r for r in ranked_pnl_all if r["weekly_pnl_gbp"] < 0]))[:3]
    max_abs = max((abs(r["weekly_pnl_gbp"]) for r in ranked_pnl_all), default=1)

    ai_tops = {i["ticker"]: i for i in content.get("top_performers", [])}
    ai_lags = {i["ticker"]: i for i in content.get("laggards", [])}

    def _contrib_items(items, ai_map, css):
        out = ""
        for r in items:
            t      = r["ticker"]
            name   = ai_map.get(t, {}).get("name") or r.get("name", t)
            driver = ai_map.get(t, {}).get("driver", "")
            pct_s  = _fmt_pct(r["weekly_pct"])
            pnl_val = r.get("weekly_pnl_gbp", 0)  # Key is legacy _gbp, value is native CCY
            pnl_s  = f"{ccy_sym}{pnl_val:+,.0f}"
            width  = _bar_width(pnl_val, max_abs)
            out += f"""
      <div class="contrib-item">
        <div class="contrib-header">
          <div class="contrib-ticker">{t}
            <span style="font-size:11px;color:var(--slate);font-weight:400;">&nbsp;{name}</span>
          </div>
          <div style="text-align:right;flex-shrink:0">
            <div class="contrib-pct {css}">{pct_s}</div>
            <div style="font-size:10px;color:var(--slate);margin-top:1px">{pnl_s}</div>
          </div>
        </div>
        <div class="contrib-desc">{driver}</div>
        <div class="bar-track"><div class="bar-fill {css}" style="width:{width}%"></div></div>
      </div>"""
        return out

    contrib_html = (
        '<div class="contrib-group-label">Top Performers</div>'
        + _contrib_items(tops, ai_tops, "pos")
        + '\n<hr class="contrib-divider">\n'
        + '<div class="contrib-group-label">Laggards</div>'
        + _contrib_items(lags, ai_lags, "neg")
    )

    html = re.sub(
        r'(<div class="section-title">Portfolio Contribution Analysis</div>)(.*?)(<div class="section">)',
        r'\1\n' + contrib_html + r'\n    </div>\n\n    <div class="section">',
        html, count=1, flags=re.DOTALL,
    )

    # ── S4: Technicals — each card labelled with ticker ────────────────────
    signals_label = " · ".join(featured_signals[:3]) if featured_signals else "No dominant signal"
    tech_note     = content.get("tech_featured_note", "")

    if technicals:
        rsi    = technicals.get("rsi_now", np.nan)
        pvs200 = technicals.get("price_vs_sma200", np.nan)
        rng_p  = technicals.get("range_pos_pct", 50.0)
        macd_n = technicals.get("macd_now", 0) or 0
        sig_n  = technicals.get("signal_now", 0) or 0
        cross  = technicals.get("macd_cross", "")
        h52 = technicals.get("high_52w", 0); l52 = technicals.get("low_52w", 0)

        rsi_v  = f"{rsi:.1f}" if not np.isnan(rsi) else "N/A"
        rsi_s  = "bearish" if rsi > 70 else ("caution" if rsi > 60 else ("bullish" if rsi >= 30 else "bullish"))
        rsi_l  = technicals.get("rsi_label", "NEUTRAL").title()
        rsi_n  = (f"Was {technicals.get('rsi_1w_ago',0):.1f} a week ago — "
                  f"now {technicals.get('rsi_trend','').lower()}.")

        dma_v  = f"{pvs200:+.1f}%" if not np.isnan(pvs200) else "N/A"
        dma_s  = "bullish" if pvs200 > 5 else ("bearish" if pvs200 < 0 else "caution")
        dma_l  = "Uptrend Confirmed" if pvs200 > 5 else ("Below 200-DMA" if pvs200 < 0 else "Marginally Above")
        dma_n  = technicals.get("golden_cross", "")

        if   "BULLISH" in cross.upper(): mv, ms, ml = "Bullish Crossover", "bullish", "MACD × Signal ↑"
        elif "BEARISH" in cross.upper(): mv, ms, ml = "Bearish Crossover", "bearish", "MACD × Signal ↓"
        else:
            above = macd_n > sig_n
            mv = "Above Signal" if above else "Below Signal"
            ms = "bullish" if above else "caution"
            ml = "Positive Momentum" if above else "Negative Momentum"
        mn = f"Histogram {technicals.get('hist_momentum','')} · MACD {macd_n:.4f} vs Signal {sig_n:.4f}."

        rv  = f"{rng_p:.0f}th %ile"
        rs  = "bullish" if rng_p >= 75 else ("bearish" if rng_p < 40 else "caution")
        rl  = "Near 52-Week High" if rng_p >= 75 else ("Lower Half" if rng_p < 40 else "Upper Half")
        rn  = f"Range: {l52:.2f} → {h52:.2f}."
    else:
        rsi_v=dma_v=mv=rv="N/A"; rsi_s=dma_s=ms=rs="caution"
        rsi_l=dma_l=ml=rl="No Data"; rsi_n=dma_n=mn=rn=""

    # Ticker label appended to each card heading
    tk = featured_ticker
    tech_html = f"""<div class="tech-featured">
        <div>
          <div class="tech-featured-label">Under the Lens · {signals_label}</div>
          <div class="tech-featured-ticker">{tk}
            <span style="font-family:'Montserrat',sans-serif;font-size:12px;font-weight:400;color:var(--slate);margin-left:10px">{featured_name}</span>
          </div>
        </div>
        <div style="font-size:10px;color:var(--slate);letter-spacing:1px;text-align:right">{date_str}</div>
      </div>
      {"<div style='margin:8px 0 18px;font-size:12.5px;color:var(--navy);line-height:1.7;font-style:italic'>" + tech_note + "</div>" if tech_note else ""}
      <div class="tech-grid">
        <div class="tech-card">
          <div class="tech-label">RSI 14-day · {tk}</div>
          <div class="tech-value">{rsi_v}</div>
          <div class="tech-signal {rsi_s}">{rsi_l}</div>
          <div class="tech-note">{rsi_n}</div>
        </div>
        <div class="tech-card">
          <div class="tech-label">vs 200-day MA · {tk}</div>
          <div class="tech-value">{dma_v}</div>
          <div class="tech-signal {dma_s}">{dma_l}</div>
          <div class="tech-note">{dma_n}</div>
        </div>
        <div class="tech-card">
          <div class="tech-label">MACD 12/26/9 · {tk}</div>
          <div class="tech-value" style="font-size:20px;line-height:1.3">{mv}</div>
          <div class="tech-signal {ms}">{ml}</div>
          <div class="tech-note">{mn}</div>
        </div>
        <div class="tech-card">
          <div class="tech-label">52-Week Range · {tk}</div>
          <div class="tech-value">{rv}</div>
          <div class="tech-signal {rs}">{rl}</div>
          <div class="tech-note">{rn}</div>
        </div>
      </div>"""

    html = re.sub(
        r'<div class="tech-featured">.*?(<div class="section">)',
        tech_html + r'\n    </div>\n\n    <div class="section">',
        html, count=1, flags=re.DOTALL,
    )

    # ── S5: Two-part Trades & Portfolio Activity ──────────────────────────
    if weekly_trades is None:
        weekly_trades = []
    tag_map = {"Breakout": "breakout", "Hedge": "hedge", "Watch": "watch", "Reduce": "reduce"}
    week_of = (report_date + datetime.timedelta(days=2)).strftime("%d %B")

    # ── Part A: Actual Trade Ledger (no AI) ───────────────────────────────
    if lang == "it":
        _DIR_CSS = {"BUY": "dir-buy", "SELL": "dir-sell", "DIV": "dir-div", "FEE": "dir-fee"}
        _DIR_LBL = {"BUY": "ACQUISTO", "SELL": "VENDITA", "DIV": "DIV", "FEE": "COMMISS"}
        act_lbl = "Movimenti di Portafoglio Questa Settimana"
        qty_lbl = "Quantità"
        pri_lbl = f"Prezzo&nbsp;({ccy_sym})"
        con_lbl = f"Controvalore&nbsp;({ccy_sym})"
        no_tr_msg = "Nessun movimento, dividendo o commissione nel periodo."
        id_lbl = "Idee di Investimento"
        dir_head = "Direzione"
    else:
        _DIR_CSS = {"BUY": "dir-buy", "SELL": "dir-sell", "DIV": "dir-div", "FEE": "dir-fee"}
        _DIR_LBL = {"BUY": "BUY", "SELL": "SELL", "DIV": "DIV", "FEE": "FEE"}
        act_lbl = "Portfolio Activity This Week"
        qty_lbl = "Shares"
        pri_lbl = f"Price&nbsp;({ccy_sym})"
        con_lbl = f"Consideration&nbsp;({ccy_sym})"
        no_tr_msg = "No trades, dividends or fees recorded in the reporting period."
        id_lbl = "Trade Ideas to Consider"
        dir_head = "Direction"

    period_label = f"{(report_date - datetime.timedelta(days=7)).strftime('%d %b')} – {report_date.strftime('%d %b %Y')}"

    s5 = (
        f'<div class="contrib-group-label" style="margin-bottom:6px">{act_lbl}'
        f'<span style="font-weight:400;text-transform:none;letter-spacing:0;'
        f'font-size:9px;color:var(--slate);margin-left:8px">{period_label}</span></div>\n'
    )

    if weekly_trades:
        s5 += (
            '      <div class="ledger-wrap">\n'
            '        <table class="ledger-table">\n'
            '          <thead><tr>\n'
            '            <th>Date</th><th>Account</th><th>Ticker</th>'
            f'<th>{dir_head}</th><th style="text-align:right">{qty_lbl}</th>'
            f'<th style="text-align:right">{pri_lbl}</th>'
            f'<th style="text-align:right">{con_lbl}</th>\n'
            '          </tr></thead>\n'
            '          <tbody>\n'
        )
        for row in weekly_trades:
            dir_css  = _DIR_CSS.get(row["direction"], "dir-fee")
            dir_lbl  = _DIR_LBL.get(row["direction"], row["direction"])
            shares_s = f"{row['shares']:,.0f}"  if row["shares"] > 0 else "—"
            price_s  = f"{row['price_gbp']:,.4f}" if row["price_gbp"] > 0 else "—"
            consid_val = row.get("consideration_gbp", 0)
            consid_s = f"{ccy_sym}{consid_val:,.2f}" if consid_val > 0 else "—"
            name_tip  = (f' title="{row["asset_name"]}"' if row["asset_name"] != row["ticker"] else "")
            s5 += (
                f'            <tr>\n'
                f'              <td>{row["date"]}</td>\n'
                f'              <td>{row["account"]}</td>\n'
                f'              <td{name_tip}>{row["ticker"]}</td>\n'
                f'              <td><span class="dir-pill {dir_css}">{dir_lbl}</span></td>\n'
                f'              <td style="text-align:right">{shares_s}</td>\n'
                f'              <td style="text-align:right">{price_s}</td>\n'
                f'              <td style="text-align:right">{consid_s}</td>\n'
                f'            </tr>\n'
            )
        s5 += '          </tbody>\n        </table>\n      </div>\n'
    else:
        s5 += (
            '      <div class="ledger-wrap">\n'
            '        <table class="ledger-table"><tbody>\n'
            f'          <tr><td colspan="7" class="no-trades">{no_tr_msg}</td></tr>\n'
            '        </tbody></table>\n      </div>\n'
        )

    # ── Part B: AI Trade Ideas (Gemini) ───────────────────────────────────
    s5 += (
        f'\n      <div class="contrib-group-label" style="margin-top:32px;margin-bottom:14px">'
        f'{id_lbl}</div>\n'
    )
    for tr in content.get("trades", []):
        css = tag_map.get(tr.get("tag", "Watch"), "watch")
        s5 += (
            f'      <div class="trade-item">\n'
            f'        <div class="trade-tag {css}">{tr.get("tag", "Watch")}</div>\n'
            f'        <div style="flex:1">\n'
            f'          <div class="trade-title">{tr.get("title", "")}</div>\n'
            f'          <div class="trade-desc">{tr.get("desc", "")}</div>\n'
            f'          <div class="trade-condition">{tr.get("condition", "")}</div>\n'
            f'        </div>\n      </div>\n'
        )

    # ── Section footnote ──────────────────────────────────────────────────
    s5 += (
        '\n      <div style="margin-top:20px;padding:10px 14px;'
        'background:rgba(26,58,92,0.04);border-left:2px solid rgba(26,58,92,0.15);'
        'font-size:9.5px;color:var(--slate);line-height:1.7">'
        '<em>Portfolio Activity</em> reflects transactions recorded in the ISA and SIPP ledgers during the reporting period — source data only, no model involvement. '
        '<em>Trade Ideas to Consider</em> are forward-looking proposals generated from Barclays macro research, constrained to ETFs and investment trusts '
        'eligible for UK ISA and SIPP accounts. They are informational only and do not constitute investment advice.'
        '</div>\n'
    )

    # ── Economic Calendar ─────────────────────────────────────────────────
    s5 += f'\n      <div class="contrib-group-label" style="margin-top:32px;margin-bottom:14px">Economic Calendar · Week of {week_of}</div>\n'
    for ev in content.get("calendar", []):
        imp = ev.get("impact", "medium").lower()
        s5 += (
            f'      <div class="calendar-item">\n'
            f'        <div class="cal-day">{ev.get("day", "")}</div>\n'
            f'        <div class="cal-event">{ev.get("event", "")}</div>\n'
            f'        <div class="cal-impact {imp}">{imp.capitalize()}</div>\n'
            f'      </div>\n'
        )

    html = re.sub(
        r'(<div class="section-title">Trades &amp; Portfolio Activity</div>).*?(?=\n\s*<div class="footer">|\Z)',
        r'\1\n\n' + s5 + '\n    </div>\n\n  ',
        html, count=1, flags=re.DOTALL,
    )

    html = html.replace("4 March 2026", report_date.strftime("%d %B %Y").lstrip("0"))

    # ── S6: Additional Reading (digest articles) ─────────────────────────
    article_list = (digest_brief or {}).get("article_list", [])
    s6 = _build_additional_reading_html(article_list)
    if s6:
        # Insert just before the footer — after the last section content,
        # before the footer disclaimer block.
        footer_marker = '<div class="footer">'
        if footer_marker in html:
            html = html.replace(footer_marker, s6 + "\n\n  " + footer_marker, 1)
        else:
            # Fallback: insert before </body>
            html = html.replace("</body>", s6 + "\n</body>", 1)

    return html


# ─────────────────────────────────────────────────────────────────────────────
# 8.  EMAIL
# ─────────────────────────────────────────────────────────────────────────────

_COMPRESSED_ASSETS_FILE = _BASE_DIR / "newsletter_assets_compressed.json"
_HERO_MAX_WIDTH   = 720   # px — matches email-wrapper width
_LOGO_MAX_HEIGHT  = 192   # px — 2× 96px display height for retina
_HERO_JPEG_Q      = 60    # JPEG quality for hero image
_LOGO_JPEG_Q      = 80    # JPEG quality for logo


def _compress_template_images(force: bool = False) -> dict:
    """Compress hero image and logo from the HTML template using Pillow.

    Reads the template, extracts base64-encoded images larger than 20KB,
    resizes and re-encodes them at reduced quality, then writes the compressed
    base64 strings to a companion JSON file so subsequent runs skip the
    (slow) compression step.  Target email size: ~80–100KB (well under Gmail's
    102KB clip threshold).

    Returns a dict {original_data_uri_prefix: compressed_data_uri}.
    Returns empty dict if Pillow is unavailable or no images needed compression.
    """
    if not force and _COMPRESSED_ASSETS_FILE.exists():
        try:
            return json.loads(_COMPRESSED_ASSETS_FILE.read_text())
        except Exception:
            pass

    if not _TEMPLATE_PATH.exists():
        return {}

    try:
        from PIL import Image
        import io as _io
        import base64 as _b64
    except ImportError:
        log.warning("Pillow not installed — image compression skipped. pip install pillow")
        return {}

    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    mapping: dict = {}

    # Find all data-URI image references larger than 20KB in src= and url()
    patterns = [
        re.compile(r'src="(data:image/([^;]+);base64,([^"]{20000,}))"', re.DOTALL),
        re.compile(r'url\((data:image/([^;]+);base64,([^)]{20000,}))\)', re.DOTALL),
    ]
    seen: set = set()

    for pat in patterns:
        for m in pat.finditer(html):
            full_uri = m.group(1)
            b64_data = m.group(3)
            key = full_uri[:200]
            if key in seen:
                continue
            seen.add(key)

            try:
                import io as _io2
                import base64 as _b642
                raw_bytes = _b642.b64decode(b64_data)
                img = Image.open(_io2.BytesIO(raw_bytes))
                w, h = img.size
                original_kb = len(b64_data) / 1024

                # Heuristic: logos are roughly square or portrait; hero images are wide
                is_logo = (h > 0 and w / h < 3)
                if is_logo:
                    if h > _LOGO_MAX_HEIGHT:
                        img = img.resize((int(w * _LOGO_MAX_HEIGHT / h), _LOGO_MAX_HEIGHT), Image.LANCZOS)
                    quality = _LOGO_JPEG_Q
                else:
                    if w > _HERO_MAX_WIDTH:
                        img = img.resize((_HERO_MAX_WIDTH, int(h * _HERO_MAX_WIDTH / w)), Image.LANCZOS)
                    quality = _HERO_JPEG_Q

                if img.mode in ("RGBA", "P", "LA"):
                    img = img.convert("RGB")

                buf = _io2.BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True)
                compressed_b64 = _b642.b64encode(buf.getvalue()).decode("ascii")
                compressed_uri = f"data:image/jpeg;base64,{compressed_b64}"
                mapping[full_uri] = compressed_uri

                log.info(
                    "_compress_template_images: %dx%d, %.1fKB → %.1fKB (%.0f%% reduction)",
                    img.width, img.height, original_kb, len(compressed_b64) / 1024,
                    (1 - len(compressed_b64) / len(b64_data)) * 100,
                )
            except Exception as exc:
                log.warning("_compress_template_images: skipping image: %s", exc)

    try:
        atomic_write_json(_COMPRESSED_ASSETS_FILE, mapping)
        log.info("_compress_template_images: cached %d image(s) to %s", len(mapping), _COMPRESSED_ASSETS_FILE)
    except Exception as exc:
        log.warning("_compress_template_images: could not write cache: %s", exc)

    return mapping


from backend.services.newsletter.mailer import (
    compress_html_images as _compress_html_images,
    prepare_for_email as _prepare_for_email,
    send_email,
)
