import pandas as pd
import numpy as np
import re
import io
import urllib.request
import urllib.error
import logging
from backend.services import storage
from backend.services import price_fetcher

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional fast path: pandas_datareader gives a clean DataFrame directly.
# If not installed, _HAVE_PDR stays False and we fall back to the direct
# Stooq CSV download (urllib), which needs no extra dependencies.
# ---------------------------------------------------------------------------
try:
    import pandas_datareader as pdr
    _HAVE_PDR = True
except ImportError:
    _HAVE_PDR = False


def fmtNum(n):
    if n is None or pd.isna(n):
        return "N/A"
    if n > 1e12:
        return f"{n/1e12:.2f}T"
    if n > 1e9:
        return f"{n/1e9:.2f}B"
    if n > 1e6:
        return f"{n/1e6:.2f}M"
    return f"{n:,.2f}"


def fetch_ticker_data(tickers, benchmark_symbol, period="2y"):
    """
    Screener-page data fetch (yfinance).

    ``period`` is now parameterised (was hardcoded "2y") so callers can
    request a longer lookback if needed.  Default stays "2y" for the
    screener page which only needs recent momentum data.
    """
    all_tickers    = tickers + [benchmark_symbol]
    unique_tickers = list(set(all_tickers))
    try:
        import yfinance as yf
        data = yf.download(
            unique_tickers,
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            threads=False,
        )
    except Exception:
        return pd.DataFrame(), {}

    info_dict = {}
    for t in unique_tickers:
        try:
            import yfinance as yf
            info_dict[t] = yf.Ticker(t).info
        except Exception:
            info_dict[t] = {}
    return data, info_dict


def calculate_metrics(df_close):
    df_clean = df_close.dropna()
    if df_clean.empty or len(df_clean) < 5:
        return None
    current = df_clean.iloc[-1]

    def get_ret(days):
        return df_clean.pct_change(days).iloc[-1] if len(df_clean) > days else 0.0

    ret_1w, ret_1m, ret_3m, ret_6m, ret_1y = (
        get_ret(5),
        get_ret(21),
        get_ret(63),
        get_ret(126),
        get_ret(252),
    )
    sma_50  = df_clean.rolling(window=50).mean().iloc[-1]
    sma_200 = df_clean.rolling(window=200).mean().iloc[-1]
    trend_signal = (
        "NEUTRAL"
        if pd.isna(sma_200)
        else ("UPTREND" if sma_50 > sma_200 else "DOWNTREND")
    )
    lookback       = min(len(df_clean), 252)
    daily_drawdown = df_clean.tail(lookback) / df_clean.tail(lookback).cummax() - 1.0
    high_52        = df_clean.tail(lookback).max()
    low_52         = df_clean.tail(lookback).min()
    denom          = high_52 - low_52
    return {
        "Price":    current,
        "1W":       ret_1w,
        "1M":       ret_1m,
        "3M":       ret_3m,
        "6M":       ret_6m,
        "1Y":       ret_1y,
        "SMA50":    sma_50,
        "SMA200":   sma_200,
        "Trend":    trend_signal,
        "MaxDD":    daily_drawdown.min(),
        "CurrDD":   daily_drawdown.iloc[-1],
        "High52":   high_52,
        "Low52":    low_52,
        "RangePos": (current - low_52) / denom if denom > 0 else 0.5,
    }


def parse_transaction(row, is_sipp=False):
    import json
    
    # 1. If it's a migrated row with Raw Details, re-parse from scratch to perfectly match old behavior
    raw = row.get("Raw Details")
    if pd.notna(raw) and isinstance(raw, str) and raw.strip():
        try:
            raw_str = raw.replace("'", '"') if "{'" in raw or ", '" in raw else raw
            raw_dict = json.loads(raw_str)
            details      = str(raw_dict.get("Details", "")).replace("<", " ")
            paid         = str(raw_dict.get("Paid In",    "0")).replace(",", "").strip()
            withdrawn    = str(raw_dict.get("Withdrawn",  "0")).replace(",", "").strip()
        except Exception:
            details      = str(row.get("Details", "")).replace("<", " ")
            paid         = str(row.get("Paid In",    "0")).replace(",", "").strip()
            withdrawn    = str(row.get("Withdrawn",  "0")).replace(",", "").strip()
    else:
        # 2. If it's a NEW row (no Raw Details) but ALREADY parsed (e.g. from UI)
        action_val = row.get("Action")
        if pd.notna(action_val) and str(action_val).strip() != "" and str(action_val).lower() != "nan" and str(action_val).lower() != "other":
            return pd.Series([
                str(action_val).strip(),
                str(row.get("Asset Name", "")),
                float(row.get("Qty", 0.0)) if pd.notna(row.get("Qty")) else 0.0,
                float(row.get("Price", 0.0)) if pd.notna(row.get("Price")) else 0.0,
                float(row.get("Net Amount", 0.0)) if pd.notna(row.get("Net Amount")) else 0.0,
                str(row.get("Auto Ticker", "")) if pd.notna(row.get("Auto Ticker")) else ""
            ])
            
        # 3. Otherwise (e.g. old GSheet fallback directly calling parse_transaction)
        details      = str(row.get("Details", "")).replace("<", " ")
        paid         = str(row.get("Paid In",    "0")).replace(",", "").strip()
        withdrawn    = str(row.get("Withdrawn",  "0")).replace(",", "").strip()

    paid_in       = float(paid)      if paid      and paid.lower()      != "nan" else 0.0
    withdrawn_amt = float(withdrawn) if withdrawn and withdrawn.lower() != "nan" else 0.0
    net_amount    = paid_in + withdrawn_amt

    action, asset_name, qty, price, auto_ticker = "Other", details, 0.0, 0.0, ""

    match_buy_full    = re.search(
        r"Bought\s+([\d,]+(?:\.\d+)?)\s+(.*?)\s+@\s+[a-zA-Z]{0,4}\s*([\d,]+(?:\.\d+)?)",
        details, re.IGNORECASE,
    )
    match_sell_full   = re.search(
        r"Sold\s+([\d,]+(?:\.\d+)?)\s+(.*?)\s+@\s+[a-zA-Z]{0,4}\s*([\d,]+(?:\.\d+)?)",
        details, re.IGNORECASE,
    )
    match_buy_partial = re.search(
        r"Bought\s+([\d,]+(?:\.\d+)?)\s+(.*)", details, re.IGNORECASE
    )
    match_sell_partial = re.search(
        r"Sold\s+([\d,]+(?:\.\d+)?)\s+(.*)", details, re.IGNORECASE
    )
    match_div = re.search(r"Dividend:\s+(.*?)\s+@",  details, re.IGNORECASE)
    match_fee = re.search(
        r"Online transaction fee (.*?) (Buy|Sell)", details, re.IGNORECASE
    )

    if match_buy_full:
        action, qty, asset_name, price = (
            "Buy",
            float(match_buy_full.group(1).replace(",", "")),
            match_buy_full.group(2).strip(),
            float(match_buy_full.group(3).replace(",", "")),
        )
    elif match_sell_full:
        action, qty, asset_name, price = (
            "Sell",
            float(match_sell_full.group(1).replace(",", "")),
            match_sell_full.group(2).strip(),
            float(match_sell_full.group(3).replace(",", "")),
        )
    elif match_buy_partial:
        action, qty, asset_name = (
            "Buy",
            float(match_buy_partial.group(1).replace(",", "")),
            match_buy_partial.group(2).strip(),
        )
        price = abs(net_amount / qty) if qty > 0 else 0.0
    elif match_sell_partial:
        action, qty, asset_name = (
            "Sell",
            float(match_sell_partial.group(1).replace(",", "")),
            match_sell_partial.group(2).strip(),
        )
        price = abs(net_amount / qty) if qty > 0 else 0.0
    elif match_div:
        action, asset_name = "Dividend", match_div.group(1).strip()
    elif "fee" in details.lower() and "transaction" in details.lower():
        action, asset_name = (
            "Fee",
            match_fee.group(1).strip() if match_fee else "Account Fee",
        )
    elif "fee" in details.lower():
        action, asset_name = "Fee", "Account Maintenance"
    elif "interest" in details.lower():
        action, asset_name = "Interest", "Cash Balance"
    elif "direct debit" in details.lower() or "direct credit" in details.lower():
        action, asset_name = "Transfer", "Cash Transfer"
    elif "sold" in details.lower() or "sale" in details.lower():
        action, asset_name = "Unparsed Sell (Check Diagnostics)", details

    ticker_match = re.search(r"\(([A-Z0-9]+)\.[A-Z]+\.[A-Z]+\)", asset_name)
    if ticker_match:
        auto_ticker = ticker_match.group(1) + ".L"
        asset_name  = re.sub(
            r"\s*\([A-Z0-9]+\.[A-Z]+\.[A-Z]+\)", "", asset_name
        ).strip()

    return pd.Series([action, asset_name, qty, price, net_amount, auto_ticker])


def _fetch_price_series(yahoo_symbol: str, start_date) -> tuple[pd.Series, str]:
    """
    Primary price fetcher with automatic provider fallback.
    Delegates to the unified price_fetcher module.
    """
    df, source = price_fetcher.fetch_ohlcv_raw(yahoo_symbol, start_date, normalize=False)
    if not df.empty and "Close" in df.columns:
        source_label = "Stooq" if source == "stooq" else ("Yahoo" if source == "yfinance" else source)
        return df["Close"], source_label
    return pd.Series(dtype=float), "Failed"


# Process-local cache: (symbol -> currency or None)
_YAHOO_QUOTE_CCY_CACHE: dict[str, str | None] = {}


def _get_yahoo_quote_currency(yahoo_symbol: str) -> str | None:
    """
    Yahoo-reported quote currency for this symbol (e.g. USD for many LSE USD ETFs).

    Cached per process to avoid repeated slow .info calls across incremental fetches.
    """
    key = yahoo_symbol.strip().upper()
    if key in _YAHOO_QUOTE_CCY_CACHE:
        return _YAHOO_QUOTE_CCY_CACHE[key]
    try:
        import yfinance as yf

        tk = yf.Ticker(yahoo_symbol)
        c = None
        try:
            fi = tk.fast_info
            c = fi.get("currency") if hasattr(fi, "get") else getattr(fi, "currency", None)
        except Exception:
            pass
        if not c:
            # Suffix-based heuristic guess to avoid calling yfinance's extremely slow tk.info
            # which does multiple HTTP requests and hangs/fails for delisted assets.
            upper = key.upper()
            if upper.endswith(".L") or upper.endswith(".XLON"):
                c = "GBX"
            elif any(upper.endswith(sfx) for sfx in (".DE", ".PA", ".AS", ".MI", ".SW", ".MC")):
                c = "EUR"
            elif "." not in upper:
                c = "USD"
            else:
                c = None
        out = str(c).strip() if c else None
        if out is not None:
            if out == "GBp" or out.upper() == "GBX":
                out = "GBX"
            else:
                out = out.upper()
        _YAHOO_QUOTE_CCY_CACHE[key] = out
        return out
    except Exception:
        _YAHOO_QUOTE_CCY_CACHE[key] = None
        return None


def _fetch_fx_close_series(yahoo_fx: str, start_date) -> pd.Series:
    """Single-column daily Close for a Yahoo FX pair, ascending dates."""
    try:
        import yfinance as yf

        start = pd.Timestamp(start_date)
        raw = yf.download(
            yahoo_fx,
            start=start.strftime("%Y-%m-%d"),
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        if raw.empty:
            return pd.Series(dtype=float)
        if isinstance(raw.columns, pd.MultiIndex):
            s = raw["Close"].iloc[:, 0]
        else:
            s = raw["Close"] if "Close" in raw.columns else raw.iloc[:, 0]
        s = s.sort_index()
        s.index = pd.to_datetime(s.index).normalize()
        if hasattr(s.index, "tz") and s.index.tz is not None:
            s.index = s.index.tz_localize(None)
        s = s[~s.index.duplicated(keep="last")]
        return s.dropna().astype(float)
    except Exception:
        return pd.Series(dtype=float)


# =============================================================================
# PRIMARY FETCH FUNCTION
# =============================================================================

def fetch_portfolio_history_and_currency(
    tickers, start_date, expected_prices, is_sipp=False, base_currency='GBP', price_cache: dict = None
):
    """
    Fetch daily Close price history for every ticker using Stooq as the
    primary data source, then apply the Pence/Pound cleanse and rolling spike
    filter that were established in appv0.py.

    Parameters
    ----------
    tickers         : list[str]
        Yahoo-format ticker symbols (e.g. 'IUSA.L').  Conversion to the Stooq
        format (.L → .UK) is handled internally.
    start_date      : date-like
        Earliest history date.  Must be set to ``SNAPSHOT_DATE`` (2017-08-26)
        by the caller so the price grid always covers the opening snapshot day.
        ``app.py`` imports ``SNAPSHOT_DATE`` from ``data_handler`` for this.
    expected_prices : dict[str, float]
        {yahoo_ticker: current_price_in_GBP}.  Anchor for the Pence/Pound
        ratio test.  If absent or zero, the heuristic (raw_last > 500 → pence)
        is used instead.
    is_sipp         : bool
        Compatibility parameter; not used in pricing logic.

    Returns  (identical contract to the former Yahoo-based version)
    -------
    df_prices         : pd.DataFrame
        Columns = original Yahoo-format ticker symbols, index = DatetimeIndex.
        Columns where Stooq returned nothing are all-NaN; build_trade_anchored_
        prices() will bridge those from the ledger.
    multipliers       : dict[str, float]
        {yahoo_ticker: multiplier applied}  — 0.01 (pence→£), 100.0, or 1.0.
    sources           : dict[str, str]
        {yahoo_ticker: 'Stooq' | 'Yahoo' | 'Failed'}
    raw_latest_prices : dict[str, float]
        {yahoo_ticker: last raw close before multiplier} — used by diagnostics.

    Pence/Pound Cleanse  (verbatim logic from appv0.py, thresholds unchanged)
    --------------------
    Stooq returns GBX (pence) for most .UK tickers, so the cleanse applies.
    Some LSE listings quote in USD/EUR; Yahoo's ``currency`` metadata is used
    to skip the wrong pence heuristic and to convert nominal prices to GBP for
    ``base_currency=='GBP'`` using GBPUSD=X / EURGBP=X.

    Anchor and ratio rules (unchanged):

        ratio = raw_last / anchor_gbp
        ratio > 20   → mult = 0.01    (data in pence, divide to get pounds)
        ratio < 0.05 → mult = 100.0   (data already fractional, scale up)
        no anchor, raw_last > 500 → mult = 0.01   (heuristic fallback;
            skipped when Yahoo reports a major foreign quote currency)

    The per-row point-in-time correction and the rolling 5-day median spike
    filter (20% threshold, min_periods=3) are also preserved verbatim.
    """
    valid_tickers = [t for t in tickers if t and pd.notna(t) and t.strip() != ""]
    if not valid_tickers:
        return pd.DataFrame(), {}, {}, {}

    df_prices         = pd.DataFrame()
    multipliers       = {}
    sources           = {}
    raw_latest_prices = {}

    # OPTIMIZATION: Pre-fetch GBPEUR=X exchange rate series once outside the loop if base_currency is EUR and there are LSE (.L) assets
    gbpeur_series = None
    if base_currency == 'EUR' and any(str(t).upper().endswith('.L') for t in valid_tickers):
        fx_cache_key = ("GBPEUR=X", start_date)
        if price_cache is not None and fx_cache_key in price_cache:
            gbpeur_series = price_cache[fx_cache_key]
        else:
            try:
                import yfinance as yf
                fx_data = yf.download('GBPEUR=X', start=start_date, 
                                     auto_adjust=True, threads=False, progress=False)
                if not fx_data.empty:
                    if isinstance(fx_data.columns, pd.MultiIndex):
                        gbpeur_series = fx_data['Close']['GBPEUR=X']
                    else:
                        gbpeur_series = fx_data['Close']
                    if price_cache is not None:
                        price_cache[fx_cache_key] = gbpeur_series
            except Exception:
                pass

    gbpusd_series = None
    eurgbp_series = None

    for yahoo_t in valid_tickers:
        series   = pd.Series(dtype=float)
        source   = "Failed"
        mult     = 1.0
        raw_last = np.nan

        anchor = float(expected_prices.get(yahoo_t, 0.0))

        # ------------------------------------------------------------------
        # 1. Fetch from Stooq (primary) with Yahoo Finance fallback
        # ------------------------------------------------------------------
        cache_key = (yahoo_t, start_date)
        if price_cache is not None and cache_key in price_cache:
            s, source = price_cache[cache_key]
        else:
            s, source = _fetch_price_series(yahoo_t, start_date)
            if price_cache is not None:
                price_cache[cache_key] = (s, source)
        quote_ccy = _get_yahoo_quote_currency(yahoo_t)

        if not s.empty:
            raw_last = float(s.iloc[-1])

            # --------------------------------------------------------------
            # 2. Pence / Pound Cleanse (Centralized Utility)
            # --------------------------------------------------------------
            from backend.services import currency_utils
            s_adj = currency_utils.normalize_series(
                yahoo_t,
                s,
                currency=quote_ccy,
                anchor=anchor,
                base_currency=base_currency,
            )

            # --------------------------------------------------------------
            # 3a. LSE (and similar) names quoted in USD/EUR → convert to GBP
            #      for GBP-based accounts. Yahoo/Stooq return nominal quote
            #      currency; without this step USD prices were mis-read as £.
            # --------------------------------------------------------------
            if base_currency == "GBP" and not s_adj.empty and quote_ccy == "USD":
                if gbpusd_series is None or gbpusd_series.empty:
                    fx_cache_key = ("GBPUSD=X", start_date)
                    if price_cache is not None and fx_cache_key in price_cache:
                        gbpusd_series = price_cache[fx_cache_key]
                    else:
                        gbpusd_series = _fetch_fx_close_series("GBPUSD=X", start_date)
                        if price_cache is not None:
                            price_cache[fx_cache_key] = gbpusd_series
                if not gbpusd_series.empty:
                    fx = gbpusd_series.reindex(s_adj.index).ffill().bfill()
                    s_adj = s_adj / fx
            elif base_currency == "GBP" and not s_adj.empty and quote_ccy == "EUR":
                if eurgbp_series is None or eurgbp_series.empty:
                    fx_cache_key = ("EURGBP=X", start_date)
                    if price_cache is not None and fx_cache_key in price_cache:
                        eurgbp_series = price_cache[fx_cache_key]
                    else:
                        eurgbp_series = _fetch_fx_close_series("EURGBP=X", start_date)
                        if price_cache is not None:
                            price_cache[fx_cache_key] = eurgbp_series
                if not eurgbp_series.empty:
                    fx = eurgbp_series.reindex(s_adj.index).ffill().bfill()
                    s_adj = s_adj * fx
            
            # To preserve the `mult` return value (for legacy diagnostics)
            mult = 1.0
            if base_currency == 'GBP' and not s.empty and not s_adj.empty:
                if float(s.iloc[-1]) > 0:
                     # Round to nearest expected multiplier (0.01, 1.0, 100.0)
                    raw_mult = float(s_adj.iloc[-1]) / float(s.iloc[-1])
                    if 0.005 < raw_mult < 0.05: mult = 0.01
                    elif 50 < raw_mult < 200: mult = 100.0

            # --------------------------------------------------------------
            # 3b. FX conversion for non-base-currency assets (EUR accounts)
            #     LSE (.L) assets held in EUR account -> convert GBP to EUR.
            # --------------------------------------------------------------
            if base_currency == 'EUR' and yahoo_t.upper().endswith('.L'):
                if gbpeur_series is not None and not gbpeur_series.empty:
                    try:
                        fx = gbpeur_series.reindex(s_adj.index).ffill().bfill()
                        s_adj = s_adj * fx
                    except Exception:
                        pass  # leave unconverted if FX reindexing fails

            # --------------------------------------------------------------
            # 4. Rolling spike filter
            #    Window=5, centre=True, min_periods=3 — verbatim from appv0.py.
            # --------------------------------------------------------------
            if len(s_adj) >= 5:
                rolling_med = s_adj.rolling(
                    window=5, center=True, min_periods=3
                ).median()
                mask              = np.abs(s_adj - rolling_med) > (0.2 * rolling_med)
                s_adj_clean       = s_adj.copy()
                s_adj_clean[mask] = np.nan
                s_adj = s_adj_clean.interpolate(method="time").bfill().ffill()

            series = s_adj
            # source is already set correctly by _fetch_price_series

        # Store under the ORIGINAL Yahoo-format ticker.  All downstream code
        # in performance.py and the TWR loop references df_prices[yahoo_t].
        df_prices[yahoo_t]         = series
        sources[yahoo_t]           = source
        multipliers[yahoo_t]       = mult
        raw_latest_prices[yahoo_t] = raw_last

    return df_prices, multipliers, sources, raw_latest_prices


# =============================================================================
# PRICE SMOOTHING ENGINE
# =============================================================================

# ---------------------------------------------------------------------------
# Constants for build_trade_anchored_prices
# ---------------------------------------------------------------------------
MAX_GAP_DAYS = 5          # flat-line runs longer than this trigger the bridge

# FX-ghost detection: if Stooq's price on a trade date differs from the
# broker's ledger-implied GBP price by more than this fraction, Stooq is
# wrong (USD/GBP currency mismatch or unadjusted corporate action) and the
# ledger price takes over.
# Example: SDVY ETF returned ~$42.79 USD on 2019-05-16 while the broker
# charged £14.05 GBP (ratio 3.04×). The old pence/pound filter only fired
# at >20× so 3× slipped through uncaught, inflating NAV by £2,672.
PRICE_DEVIATION_TOLERANCE = 0.30   # 30%




# Spike filter threshold: a single day that moves more than this fraction
# vs. BOTH its neighbours is treated as a bad data point.
SPIKE_THRESHOLD = 0.10   # 10%


def filter_price_spikes(
    df: pd.DataFrame,
    threshold: float = SPIKE_THRESHOLD,
) -> pd.DataFrame:
    """
    Remove isolated single-day price spikes caused by bad data from Stooq / yfinance.

    A day t is flagged as a spike when:
        |price(t) / price(t-1) - 1| > threshold
        AND
        |price(t) / price(t+1) - 1| > threshold

    i.e. the price shoots up (or down) vs the prior close AND immediately
    reverses the next day -- the signature of a data error, not a real move.
    The bad value is replaced by the simple average of its two neighbours.

    Only isolated single-day spikes are corrected; two consecutive bad days
    are left alone (could be a genuine halt / corporate action).
    """
    if df is None or df.empty:
        return df
    df = df.copy()
    for col in df.columns:
        values = df[col].to_numpy(dtype=float, na_value=np.nan, copy=True)
        n = len(values)
        for i in range(1, n - 1):
            p_prev, p_curr, p_next = values[i - 1], values[i], values[i + 1]
            if np.isnan(p_prev) or np.isnan(p_curr) or np.isnan(p_next):
                continue
            if p_prev == 0 or p_next == 0:
                continue
            if (abs(p_curr / p_prev - 1.0) > threshold and
                    abs(p_curr / p_next - 1.0) > threshold):
                values[i] = (p_prev + p_next) / 2.0
        df[col] = values
    return df

def build_trade_anchored_prices(
    df_prices: pd.DataFrame,
    df_parsed: pd.DataFrame,
    df_ticker_map: pd.DataFrame,
    date_range: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    Validate and repair every price series in df_prices against the broker
    ledger (ground truth in GBP).

    Three failure modes are handled:

    A. NaN gaps  — Stooq returned nothing for some / all dates.
    B. Flat-line runs > MAX_GAP_DAYS — bfill artifact from a dead feed.
       Classic example: SDVY had a 21-month price gap (Aug 2017 – May 2019)
       that bfill froze at the last known value.
    C. FX-ghost prices — Stooq returned the correct *ticker* but in the
       WRONG currency (USD instead of GBP).  Detected by comparing Stooq's
       price on every trade date to |NetAmount / Qty| from the broker ledger.
       If the ratio exceeds PRICE_DEVIATION_TOLERANCE the ledger anchor
       overrides the contaminated window and interpolate() re-bridges edges.

    All boolean masking is done on consistently-indexed .loc[] slices to
    avoid pandas broadcast shape-mismatch errors.
    """
    if df_prices.empty:
        return df_prices


    # ------------------------------------------------------------------
    # 1. Current-price lookup from Ticker Map
    # ------------------------------------------------------------------
    current_price_map: dict = {}
    if df_ticker_map is not None and not df_ticker_map.empty:
        for _, row in df_ticker_map.iterrows():
            t = str(row.get("Ticker", "")).strip()
            if not t or t.lower() == "nan":
                continue
            try:
                cp = float(row.get("Current Price", 0.0))
            except (ValueError, TypeError):
                cp = 0.0
            if cp > 0:
                current_price_map[t] = cp

    # ------------------------------------------------------------------
    # 2. Trade-anchor lookup: ticker -> {date: ledger_implied_price_gbp}
    #    implied_price = |NetAmount / Qty|  (broker ledger, always GBP)
    # ------------------------------------------------------------------
    trade_anchors: dict = {}
    if df_parsed is not None and not df_parsed.empty:
        for _, row in df_parsed.iterrows():
            t = str(row.get("Auto Ticker", "")).strip()
            if not t or t.lower() == "nan":
                continue
            action = row.get("Action", "")
            if action not in ("Buy", "Sell", "Unparsed Sell (Check Diagnostics)"):
                continue
            qty = row.get("Qty", 0.0)
            net = row.get("Net Amount", 0.0)
            if qty > 0 and net != 0:
                implied_price = abs(net / qty)
                trade_date    = pd.Timestamp(row["Date"]).normalize()
                if t not in trade_anchors:
                    trade_anchors[t] = {}
                trade_anchors[t][trade_date] = implied_price   # last trade wins

    today = pd.Timestamp.today().normalize()

    for t in list(df_prices.columns):
        series = df_prices[t].copy()
        
        # Treat 0.0 as NaN immediately — no financial instrument can be zero.
        series[series <= 0] = np.nan

        anchors: dict = dict(trade_anchors.get(t, {}))
        if t in current_price_map:
            anchors[today] = current_price_map[t]

        if not anchors:
            continue   # no ledger data — cannot validate

        # ------------------------------------------------------------------
        # 3. Build the full synthetic (ledger-anchored, linearly interpolated)
        #    series. Constructed unconditionally — used by all patch modes.
        # ------------------------------------------------------------------
        anchor_series = pd.Series(anchors, dtype=float)
        anchor_series = anchor_series[~anchor_series.index.duplicated(keep="last")]
        anchor_series = anchor_series.reindex(date_range)
        anchor_series.interpolate(method="time", inplace=True)
        anchor_series.bfill(inplace=True)
        anchor_series.ffill(inplace=True)

        # ------------------------------------------------------------------
        # 5. Apply 'Ledger-First' Repair logic
        # ------------------------------------------------------------------
        combined = series.copy()

        # Step 1: Treat 0.0 as NaN
        combined[combined <= 0] = np.nan

        # Step 2: HARD ANCHOR — Ledger prices are absolute truth on trade dates
        for d, p in anchors.items():
            if d in combined.index:
                combined.loc[d] = p

        # Step 3: INTERPOLATE — Bridges gaps (linear trend for long gaps)
        combined.interpolate(method="time", inplace=True)

        # Step 4: BACKFILL/FFILL — Covers tails (before first trade / after last data)
        combined.bfill(inplace=True)
        combined.ffill(inplace=True)

        # Step 5: SAFETY BRAKE — 20% Daily Move Guard
        # If a ticker moves > 20% in one day WITHOUT a ledger trade, it is likely
        # a data blackout or pricing error. We ffill the previous price.
        # Threshold 20% as requested.
        for i in range(1, len(combined)):
            current_date = combined.index[i]
            prev_price = combined.iloc[i-1]
            curr_price = combined.iloc[i]
            
            # Skip if either price is invalid
            if pd.isna(prev_price) or pd.isna(curr_price) or prev_price <= 0:
                continue
                
            # Check for >20% move
            if abs(curr_price / prev_price - 1.0) > 0.20:
                # If there is a ledger anchor for this date, trust it.
                # Otherwise, it's a suspicious ghost move.
                if current_date not in anchors:
                    combined.iloc[i] = prev_price

        df_prices[t] = combined

    # Final pass: remove isolated single-day bad data spikes from all series
    # and apply a 5-day median smoothing to eliminate 'jumpiness' around anchors.
    df_prices = filter_price_spikes(df_prices)
    df_prices = df_prices.rolling(window=5, center=True, min_periods=1).median()

    return df_prices


# ---------------------------------------------------------------------------
# Incremental price fetch — avoids re-downloading 8 years of Stooq history
# on every recalculate when only the last few days have changed.
# ---------------------------------------------------------------------------

def _incremental_fetch(
    tickers: list,
    full_start,
    expected_prices: dict,
    account: str,
    base_currency: str = "GBP",
    delta_days: int = 15,
    price_cache: dict = None,
    active_tickers: set = None,
    always_update_tickers: set = None,
) -> tuple:
    """
    Smart price fetcher that reuses the stored price grid where possible.

    Strategy
    ────────
    1. Load the existing price grid from portfolio_ticker_daily (SQLite, instant).
    2. Identify which tickers are NEW (not yet in the DB) vs KNOWN (already stored).
    3. For NEW tickers  → fetch full history from Stooq (unavoidable).
    4. For KNOWN tickers → fetch only the last `delta_days` days from Stooq
       (tiny request, avoids rate-limiting) and merge onto the stored history.
    5. Return the merged grid, plus dummy multipliers/sources/raw_latest so the
       calling code doesn't need to change its unpacking.

    This means:
    • Adding an interest/dividend/fee row → 0 new tickers → only delta fetch.
    • Adding a new Buy → 1 new ticker gets full history, rest get delta only.
    • First-ever run (DB empty) → identical to the old full fetch.
    """
    import pandas as pd
    import numpy as np

    # ── 1. Load existing price grid and start dates from DB ──────────────
    df_stored = storage.load_full_price_grid(account)
    saved_tickers = storage.get_saved_tickers(account)
    start_dates = storage.get_ticker_start_dates(account)
    latest_date = storage.get_latest_price_date(account)

    all_tickers = [t for t in tickers if t and pd.notna(t) and str(t).strip() != ""]

    # ── 2. Classify tickers ───────────────────────────────────────────────
    # A ticker is 'new' if it's not in the DB, OR if its stored history
    # starts after full_start (needs backfill).
    new_tickers = []
    known_tickers = []
    
    active_tickers = active_tickers or set()
    default_always = {"IUSA.L", "IUSA.DE", "SWDA.L", "MEUD.L", "AGGG.L", "DBMG.L"}
    always_update_set = default_always.union(always_update_tickers) if always_update_tickers else default_always
    
    from backend.services.data_handler import SNAPSHOT_DATE
    target_start = pd.Timestamp(full_start if full_start else SNAPSHOT_DATE).normalize()
    
    for t in all_tickers:
        if t not in saved_tickers:
            new_tickers.append(t)
        else:
            # Only fetch delta for active positions or benchmark tickers to avoid slow timeouts on exited assets
            is_active = (t in active_tickers)
            is_always_update = (t in always_update_set)
            if is_active or is_always_update:
                ticker_start = start_dates.get(t)
                # If the ticker in DB starts more than 10 days after our target start,
                # consider it incomplete and re-fetch full history.
                if ticker_start and ticker_start > (target_start + pd.Timedelta(days=10)):
                    new_tickers.append(t)
                else:
                    known_tickers.append(t)
            else:
                # Exited ticker — skip delta fetch and preserve historical DB prices
                pass

    # ── 3. Determine fetch windows ────────────────────────────────────────
    if latest_date is not None:
        delta_start = latest_date - pd.Timedelta(days=delta_days)
    else:
        delta_start = target_start

    # ── 4. Fetch from Stooq ───────────────────────────────────────────────
    df_new = pd.DataFrame()
    df_delta = pd.DataFrame()
    multipliers = {}
    sources = {}
    raw_latest = {}

    # New tickers — full history needed
    if new_tickers:
        df_new, m1, s1, r1 = fetch_portfolio_history_and_currency(
            new_tickers, full_start, expected_prices,
            is_sipp=False, base_currency=base_currency, price_cache=price_cache,
        )
        multipliers.update(m1)
        sources.update(s1)
        raw_latest.update(r1)

    # Known tickers — delta only (last N days)
    if known_tickers:
        df_delta, m2, s2, r2 = fetch_portfolio_history_and_currency(
            known_tickers, delta_start, expected_prices,
            is_sipp=False, base_currency=base_currency, price_cache=price_cache,
        )
        multipliers.update(m2)
        sources.update(s2)
        raw_latest.update(r2)

        # ── Self-Healing Unit Mismatch Circuit Breaker ──
        corrupted_tickers = []
        for t in known_tickers:
            if t in df_delta.columns and not df_stored.empty and t in df_stored.columns:
                fresh_series = df_delta[t].dropna()
                stored_series = df_stored[t].dropna()
                if not fresh_series.empty and not stored_series.empty:
                    fresh_val = float(fresh_series.iloc[-1])
                    stored_val = float(stored_series.iloc[-1])
                    if fresh_val > 0.0 and stored_val > 0.0:
                        ratio = fresh_val / stored_val
                        # Trigger if there's a >5x or <0.2x jump (impossible for normal assets)
                        if ratio > 5.0 or ratio < 0.2:
                            log.warning(
                                "[Self-Heal] Unit mismatch circuit breaker tripped for '%s'! "
                                "Cache shows %s, newly fetched price shows %s (Ratio: %s). "
                                "Forcing full history refetch to heal database.",
                                t, stored_val, fresh_val, ratio
                            )
                            corrupted_tickers.append(t)

        if corrupted_tickers:
            log.info("[Self-Heal] Re-fetching full history for corrupted tickers: %s", corrupted_tickers)
            # Remove them from known_tickers so they are not merged from df_stored
            known_tickers = [t for t in known_tickers if t not in corrupted_tickers]
            # Remove them from df_delta so they are not merged
            df_delta = df_delta.drop(columns=[t for t in corrupted_tickers if t in df_delta.columns], errors="ignore")
            # Fetch their full history
            df_healed, m_heal, s_heal, r_heal = fetch_portfolio_history_and_currency(
                corrupted_tickers, full_start, expected_prices,
                is_sipp=False, base_currency=base_currency, price_cache=price_cache,
            )
            # Combine healed into df_new so it overwrites df_prices with clean history
            if df_new.empty:
                df_new = df_healed
            else:
                df_new = pd.concat([df_new, df_healed], axis=1)
                
            multipliers.update(m_heal)
            sources.update(s_heal)
            raw_latest.update(r_heal)

    # ── 5. Merge: stored history + delta slice ────────────────────────────
    # Start from the stored grid (covers full history for known tickers).
    # Then overwrite/append with the fresh delta rows — this updates the tail
    # and fixes any gaps from prior rate-limit failures.
    if not df_stored.empty:
        # Combine stored + delta for known tickers
        if not df_delta.empty:
            # concat then keep the latest value for any duplicate (date, ticker)
            combined_known = pd.concat([df_stored, df_delta], axis=0)
            combined_known = combined_known[~combined_known.index.duplicated(keep="last")]
            combined_known.sort_index(inplace=True)
        else:
            combined_known = df_stored

        # Add columns for new tickers (full history)
        if not df_new.empty:
            df_new = df_new[~df_new.index.duplicated(keep="last")]
            # We must be careful not to overwrite valid data in combined_known 
            # if df_new is incomplete for some reason.
            df_prices = combined_known.reindex(
                combined_known.index.union(df_new.index)
            )
            
            for col in df_new.columns:
                s_new = df_new[col].dropna()
                if not s_new.empty:
                    # Overwrite the column with the new full history
                    df_prices[col] = s_new.reindex(df_prices.index)
                else:
                    # If df_new[col] is empty, keep what we had in combined_known
                    pass
            
            df_prices = df_prices.ffill()
        else:
            df_prices = combined_known

    else:
        # No stored data — combine new + delta as the full grid
        parts = [p for p in [df_new, df_delta] if not p.empty]
        if parts:
            df_prices = pd.concat(parts, axis=1)
            df_prices = df_prices.loc[:, ~df_prices.columns.duplicated(keep="last")]
            df_prices.sort_index(inplace=True)
        else:
            df_prices = pd.DataFrame()

    # Forward-fill any remaining gaps (weekends / holidays)
    if not df_prices.empty:
        df_prices = df_prices.ffill().bfill()

    return df_prices, multipliers, sources, raw_latest


# =============================================================================
# UNIFIED RECALCULATION PIPELINE
# =============================================================================

def run_recalculation_pipeline(account_name: str, force_full_prices: bool = False, active_bm_name: str = None, price_cache: dict = None) -> str | None:
    """
    Unified entry point for calculating an account's performance.
    Used by the UI, background scheduler, and the 'Refresh All' button.
    
    1. Fetches ledger data (Google Sheets)
    2. Fetches/Updates price history (Smart Incremental Fetch)
    3. Runs TWR performance math
    4. Saves results to local SQLite database
    5. Runs synthetic benchmark simulation if defined
    
    Returns None on success, or an error string on failure.
    """
    log = logging.getLogger("engine_pipeline")
    try:
        from backend.services.data_handler import (
            get_account_registry,
            get_ticker_map,
            get_sanitized_ledger,
            apply_ticker_map,
            get_account_base_currency,
            get_legacy_cash_adjustment,
            SNAPSHOT_DATE
        )
        from backend.services.performance import calculate_twr_series
        from backend.services.benchmark_gen import BenchmarkSimulator

        # ── 1. Preparation ───────────────────────────────────────────────────
        registry = get_account_registry()
        if registry.empty:
            return "Account Registry is empty."

        ticker_map = get_ticker_map()
        acct_ccy = get_account_base_currency(account_name, registry)
        legacy_adj = get_legacy_cash_adjustment(account_name, registry)

        # ── 2. Ledger ────────────────────────────────────────────────────────
        df_ledger, is_sipp, df_raw_for_audit = get_sanitized_ledger(account_name)
        if df_ledger.empty:
            return f"Ledger for '{account_name}' is empty."

        # Parse and Map
        rich_cols = {"Net Amount", "Action", "Asset Name", "Qty", "Price", "Auto Ticker"}
        if rich_cols.issubset(set(df_ledger.columns)):
            df_parsed = df_ledger.copy()
            for col in ("Qty", "Price", "Net Amount"):
                if col in df_parsed.columns:
                    df_parsed[col] = pd.to_numeric(df_parsed[col], errors="coerce").fillna(0.0)
            df_parsed["Auto Ticker"] = df_parsed["Auto Ticker"].fillna("").astype(str).str.strip()
        else:
            parsed_cols = df_ledger.apply(lambda r: parse_transaction(r, is_sipp=is_sipp), axis=1)
            parsed_cols.columns = ["Action", "Asset Name", "Qty", "Price", "Net Amount", "Auto Ticker"]
            df_parsed = pd.concat([df_ledger.reset_index(drop=True), parsed_cols.reset_index(drop=True)], axis=1)
        
        df_parsed = apply_ticker_map(df_parsed, ticker_map)

        # ── 3. Snapshot ──────────────────────────────────────────────────────
        from backend.services.data_handler import load_start_snapshot, is_third_party_eur
        is_tp_eur = is_third_party_eur(account_name, registry)
        
        if is_tp_eur:
            snap_cash, snap_qty = 0.0, {}
        elif account_name in ("ISA", "Consolidated"):
            try:
                snap_cash, snap_qty = load_start_snapshot()
            except Exception:
                snap_cash, snap_qty = 669.06, {}
        else:
            snap_cash, snap_qty = 0.0, {}

        # ── 4. Prices (SMART FETCH) ──────────────────────────────────────────
        # Determine the full universe of tickers needed
        ledger_tickers = df_parsed["Auto Ticker"].dropna().astype(str).str.strip().tolist()
        # Get active benchmark constituents to include in unique_tickers so they are fetched
        bm_tickers = []
        bm_fx_tickers = []
        if active_bm_name and active_bm_name != "None (use index line only)" and active_bm_name != "":
            try:
                saved_defs = storage.load_benchmark_definitions()
                if saved_defs:
                    bm_def = next((d for d in saved_defs if d["name"] == active_bm_name), None)
                    if bm_def:
                        bm_tickers = [c["ticker"] for c in bm_def["constituents"]]
                        currencies_needed = {c["currency"] for c in bm_def["constituents"]}
                        for asset_ccy in currencies_needed:
                            if asset_ccy != acct_ccy:
                                if asset_ccy == 'GBP' and acct_ccy == 'EUR':
                                    bm_fx_tickers.append("GBPEUR=X")
                                elif asset_ccy == 'EUR' and acct_ccy == 'GBP':
                                    bm_fx_tickers.append("GBPEUR=X")
                                elif asset_ccy == 'USD' and acct_ccy == 'EUR':
                                    bm_fx_tickers.append("EURUSD=X")
                                elif asset_ccy == 'EUR' and acct_ccy == 'USD':
                                    bm_fx_tickers.append("EURUSD=X")
                                elif asset_ccy == 'USD' and acct_ccy == 'GBP':
                                    bm_fx_tickers.append("GBPUSD=X")
                                elif asset_ccy == 'GBP' and acct_ccy == 'USD':
                                    bm_fx_tickers.append("GBPUSD=X")
            except Exception as bm_tickers_err:
                log.error(f"Failed to load benchmark constituents/FX for unique_tickers: {bm_tickers_err}")

        snap_tickers = list(snap_qty.keys())
        index_benchmark = "IUSA.L" if acct_ccy == "GBP" else "IUSA.DE"
        
        unique_tickers = list({str(t).strip() for t in ledger_tickers + snap_tickers + bm_tickers + bm_fx_tickers + [index_benchmark, "SWDA.L", "MEUD.L"]
                                if t and str(t).lower() != "nan" and str(t).strip() != ""})

        # Expected prices for pence/pound correction
        expected_prices = {}
        if not ticker_map.empty and "Ticker" in ticker_map.columns:
            for _, row in ticker_map.iterrows():
                t = str(row["Ticker"]).strip()
                if t and t.lower() != "nan":
                    try:
                        expected_prices[t] = float(row.get("Current Price", 0.0))
                    except: pass

        # Price fetch start date
        price_start = SNAPSHOT_DATE
        if account_name not in ("ISA", "Consolidated"):
            if not df_parsed.empty and "Date" in df_parsed.columns:
                m = df_parsed["Date"].min()
                if pd.notna(m): price_start = m

        # Calculate active tickers (currently held positions with > 0.01 shares)
        active_tickers = set()
        if snap_qty:
            for t, q in snap_qty.items():
                if q > 0:
                    active_tickers.add(t)
        if not df_parsed.empty:
            # Replicate sequential share tracking to determine final holdings
            pos_tracker = {}
            if snap_qty:
                pos_tracker = {t: q for t, q in snap_qty.items() if q > 0}
            df_sorted = df_parsed.sort_values("Date")
            for _, row in df_sorted.iterrows():
                act = row.get("Action")
                t_symbol = str(row.get("Auto Ticker", "")).strip()
                if t_symbol and t_symbol.lower() != "nan":
                    qty = row.get("Qty", 0.0)
                    if pd.isna(qty):
                        qty = 0.0
                    if act == "Buy":
                        pos_tracker[t_symbol] = pos_tracker.get(t_symbol, 0.0) + qty
                    elif act in ("Sell", "Unparsed Sell (Check Diagnostics)"):
                        pos_tracker[t_symbol] = max(0.0, pos_tracker.get(t_symbol, 0.0) - qty)
            active_tickers = {t for t, q in pos_tracker.items() if q > 0.01}

        if force_full_prices:
            df_prices, multipliers, sources, raw_latest = fetch_portfolio_history_and_currency(
                unique_tickers, price_start, expected_prices, base_currency=acct_ccy, price_cache=price_cache
            )
        else:
            df_prices, multipliers, sources, raw_latest = _incremental_fetch(
                unique_tickers, price_start, expected_prices, account_name, base_currency=acct_ccy, price_cache=price_cache,
                active_tickers=active_tickers, always_update_tickers=set(bm_tickers + bm_fx_tickers)
            )
        
        df_prices = filter_price_spikes(df_prices)

        # ── 5. Math (TWR) ────────────────────────────────────────────────────
        df_perf, positions, _, df_prices_repaired = calculate_twr_series(
            df_parsed=df_parsed,
            df_prices=df_prices,
            df_ticker_map=ticker_map,
            initial_cash=legacy_adj,
            snapshot_cash=snap_cash,
            snapshot_quantities=snap_qty,
            return_prices=True,
        )
        df_prices = df_prices_repaired

        if df_perf.empty:
            return f"TWR calculation returned empty result for {account_name}."

        # Attach Index Benchmark rebased to 100
        if index_benchmark in df_prices.columns:
            b = df_prices[index_benchmark].reindex(df_perf.index).ffill().bfill()
            if not b.dropna().empty:
                df_perf = df_perf.copy()
                df_perf["Bench_NAV"] = (b / b.iloc[0]) * 100.0

        # ── 6. Persistence ───────────────────────────────────────────────────
        storage.clear_account_data(account_name)
        storage.save_portfolio_run(
            account=account_name,
            df_perf=df_perf,
            positions=positions,
            df_prices=df_prices,
        )

        saved_bm_defs = []
        if active_bm_name and active_bm_name != "None (use index line only)" and active_bm_name != "":
            try:
                saved_defs = storage.load_benchmark_definitions()
                if saved_defs:
                    if active_bm_name == "__all__":
                        saved_bm_defs = saved_defs
                    else:
                        matched = next((d for d in saved_defs if d["name"] == active_bm_name), None)
                        if matched:
                            saved_bm_defs = [matched]
            except Exception as bm_load_err:
                log.error(f"Failed to load benchmark definitions: {bm_load_err}")

        for bm_def in saved_bm_defs:
            try:
                bm_name = bm_def["name"]
                bm_tickers_weights = {c["ticker"]: c["weight"] for c in bm_def["constituents"]}
                bm_currency_map = {c["ticker"]: c["currency"] for c in bm_def["constituents"]}
                
                nav_col = "Total NAV" if "Total NAV" in df_perf.columns else df_perf.columns[-1]
                bm_initial_capital = max(1000.0, float(df_perf[nav_col].iloc[0]))

                sim = BenchmarkSimulator(
                    tickers_and_weights=bm_tickers_weights,
                    currency_map=bm_currency_map,
                    initial_capital=bm_initial_capital,
                    start_date=SNAPSHOT_DATE,
                    rebalance_freq=bm_def.get("rebalance_freq", "Q"),
                    target_currency=acct_ccy,
                )
                bm_ledger, bm_prices_dict = sim.generate(prefetched_prices=df_prices)
                bm_prices = pd.DataFrame(bm_prices_dict).ffill().bfill()
                bm_prices = filter_price_spikes(bm_prices)

                df_bm_perf, _, _, bm_prices_repaired = calculate_twr_series(
                    df_parsed=bm_ledger,
                    df_prices=bm_prices,
                    df_ticker_map=None,
                    initial_cash=0.0,
                    snapshot_cash=bm_initial_capital,
                    snapshot_quantities={},
                    return_prices=True,
                )
                bm_prices = bm_prices_repaired

                if not df_bm_perf.empty:
                    storage.save_benchmark_run(
                        account=account_name,
                        benchmark_label=bm_name,
                        df_benchmark_perf=df_bm_perf,
                        tickers_and_weights=bm_tickers_weights,
                        bm_prices=bm_prices,
                    )
            except Exception as bm_err:
                log.error(f"Pipeline benchmark failed for {account_name} ({bm_def.get('name')}): {bm_err}")

        # ── 8. Diagnostics Sync (Storage) ─────────────────────────────────────────
        try:
            audit_data = {
                "_ran_full_engine": True,
                "_force_full_prices": force_full_prices,
                "_run_timestamp": __import__('datetime').datetime.now().isoformat(),
                "df_raw_for_audit": df_raw_for_audit,
                "df_parsed": df_parsed,
                "snapshot_cash": snap_cash,
                "snapshot_quantities": snap_qty,
                "legacy_adj": float(legacy_adj) if legacy_adj is not None else None,
                "account_currency": acct_ccy,
                "expected_prices": expected_prices,
                "multipliers": multipliers,
                "sources": sources,
                "raw_latest": raw_latest,
                "unique_tickers": unique_tickers
            }
            storage.save_engine_audit(account_name, audit_data)
        except Exception as audit_err:
            log.error(f"Failed to save engine audit: {audit_err}")

        return None # Success

    except Exception as e:
        log.error(f"Pipeline failed for {account_name}: {e}", exc_info=True)
        return str(e)
