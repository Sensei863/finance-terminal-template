"""
technicals_ui.py
────────────────
Standalone Technical Analysis page for the Portfolio Tracker.

Renders a per-ETF technical analysis panel driven directly from the
``positions`` dict already computed by the TWR engine.  No dependency
on the look-through holdings registry or any look-through cache.

Data flow
─────────
    positions : dict {yahoo_ticker: shares}   ← from calculate_twr_series
    df_prices : pd.DataFrame                  ← price grid from the engine
        │
        └─► yf.download(etf_tickers, period="2y", interval="1d")
                cached @st.cache_data(ttl=3600)
                completely independent of look-through engine

Integration (app.py)
────────────────────
1.  Import:
        import technicals_ui

2.  Add tab to the tab list (new order):
        tab_dash, tab_tech, tab_lookahead, tab_bm, tab_trades, tab_diag = st.tabs([
            "📊 Performance Dashboard",
            "📈 Technicals",
            "🔬 Look-Through",
            "📐 Benchmark Builder",
            "✍️ Trades",
            "🛠️ Diagnostics",
        ])

3.  Wire the tab:
        with tab_tech:
            technicals_ui.render_technicals_page(
                positions=positions,
                df_prices=df_prices,
            )
"""

import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from backend.services import gemini_util

def cache_data(ttl=None, show_spinner=True):
    def decorator(func):
        import functools
        cached_val = {}
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            if key not in cached_val:
                cached_val[key] = func(*args, **kwargs)
            return cached_val[key]
        return wrapper
    return decorator


# ──────────────────────────────────────────────────────────────────────────────
# Indicator calculations  (pure pandas/numpy — no extra dependencies)
# ──────────────────────────────────────────────────────────────────────────────

def _sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=1).mean()


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _bollinger(series: pd.Series, window: int = 20, num_std: float = 2.0):
    mid = _sma(series, window)
    std = series.rolling(window=window, min_periods=1).std()
    return mid, mid + num_std * std, mid - num_std * std


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line   = _ema(series, fast) - _ema(series, slow)
    signal_line = _ema(macd_line, signal)
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


# ──────────────────────────────────────────────────────────────────────────────
# Data fetching  (independent TTL cache — no look-through dependency)
# We always fetch 2y of data and let the slider window it client-side,
# so changing the slider never triggers a new network request.
# ──────────────────────────────────────────────────────────────────────────────

@cache_data(ttl=3600, show_spinner=False)
def _fetch_ohlcv(tickers: tuple) -> dict[str, pd.DataFrame]:
    """
    Download 2 years of OHLCV data from yfinance for a set of tickers.
    Always fetches 2y so the slider can zoom without re-fetching.

    Returns a dict  {ticker: DataFrame(Open, High, Low, Close, Volume)}
    Tickers for which no data is returned are silently excluded.
    """
    if not tickers:
        return {}

    ticker_list = list(tickers)
    try:
        raw = yf.download(
            ticker_list,
            period="2y",
            interval="1d",
            auto_adjust=True,
            threads=False,
            progress=False,
        )
    except Exception:
        return {}

    if raw.empty:
        return {}

    result: dict[str, pd.DataFrame] = {}

    from backend.services import currency_utils

    if isinstance(raw.columns, pd.MultiIndex):
        for t in ticker_list:
            try:
                df = raw.xs(t, level=1, axis=1)[["Open", "High", "Low", "Close", "Volume"]].dropna()
                if not df.empty:
                    result[t] = currency_utils.normalize_ohlcv(t, df)
            except (KeyError, Exception):
                pass
    else:
        if len(ticker_list) == 1:
            df = raw[["Open", "High", "Low", "Close", "Volume"]].dropna()
            if not df.empty:
                result[ticker_list[0]] = currency_utils.normalize_ohlcv(ticker_list[0], df)

    return result


# ──────────────────────────────────────────────────────────────────────────────
# AI commentary — Gemini-powered technical brief
# ──────────────────────────────────────────────────────────────────────────────

def _build_technical_snapshot(df: pd.DataFrame, ticker: str, shares: float) -> dict:
    """
    Distils the full OHLCV history into a rich snapshot dict that gets fed
    verbatim into the Gemini prompt.  Heavy on recency — last 1 day and 5 days
    get the most granular treatment.
    """
    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]
    volume = df["Volume"]

    price_now  = close.iloc[-1]
    price_prev = close.iloc[-2] if len(close) > 1 else price_now

    # ── Returns ──────────────────────────────────────────────────────────
    def _ret(days):
        return close.pct_change(days).iloc[-1] if len(close) > days else float("nan")

    ret_1d  = _ret(1)
    ret_5d  = _ret(5)
    ret_1m  = _ret(21)
    ret_3m  = _ret(63)
    ret_6m  = _ret(126)
    ret_1y  = _ret(252)

    # ── Last 5 days detail ───────────────────────────────────────────────
    last5 = df.tail(5)[["Close", "High", "Low", "Volume"]].copy()
    last5.index = last5.index.strftime("%Y-%m-%d")
    last5_str = last5.to_string(float_format=lambda x: f"{x:.4f}")

    # ── Moving averages ──────────────────────────────────────────────────
    sma50_val  = _sma(close, 50).iloc[-1]
    sma200_val = _sma(close, 200).iloc[-1] if len(close) >= 200 else float("nan")
    price_vs_sma50  = (price_now / sma50_val  - 1) * 100
    price_vs_sma200 = (price_now / sma200_val - 1) * 100 if not np.isnan(sma200_val) else float("nan")

    golden_cross = (
        "GOLDEN CROSS (bullish)" if not np.isnan(sma200_val) and sma50_val > sma200_val
        else "DEATH CROSS (bearish)" if not np.isnan(sma200_val)
        else "SMA 200 not available"
    )

    # ── Bollinger Bands ──────────────────────────────────────────────────
    bb_mid, bb_upper, bb_lower = _bollinger(close, 20, 2.0)
    bb_pos = (price_now - bb_lower.iloc[-1]) / (bb_upper.iloc[-1] - bb_lower.iloc[-1]) * 100
    bb_bandwidth = (bb_upper.iloc[-1] - bb_lower.iloc[-1]) / bb_mid.iloc[-1] * 100

    # ── RSI ──────────────────────────────────────────────────────────────
    rsi_series  = _rsi(close, 14)
    rsi_now     = rsi_series.iloc[-1]
    rsi_1w_ago  = rsi_series.iloc[-6] if len(rsi_series) > 6 else float("nan")
    rsi_trend   = "rising" if rsi_now > rsi_1w_ago else "falling"
    rsi_label   = "OVERBOUGHT" if rsi_now > 70 else "OVERSOLD" if rsi_now < 30 else "NEUTRAL"

    # ── MACD ─────────────────────────────────────────────────────────────
    macd_line, sig_line, hist = _macd(close, 12, 26, 9)
    macd_now   = macd_line.iloc[-1]
    sig_now    = sig_line.iloc[-1]
    hist_now   = hist.iloc[-1]
    hist_prev  = hist.iloc[-2] if len(hist) > 1 else float("nan")
    macd_cross = (
        "BULLISH CROSSOVER (MACD crossed above signal in last 3 days)"
        if any(macd_line.iloc[-3:] > sig_line.iloc[-3:]) and macd_now > sig_now
        else "BEARISH CROSSOVER (MACD crossed below signal in last 3 days)"
        if any(macd_line.iloc[-3:] < sig_line.iloc[-3:]) and macd_now < sig_now
        else "No recent crossover"
    )
    hist_momentum = "expanding" if abs(hist_now) > abs(hist_prev) else "contracting"

    # ── Volume ───────────────────────────────────────────────────────────
    avg_vol_20d = volume.rolling(20).mean().iloc[-1]
    vol_today   = volume.iloc[-1]
    vol_ratio   = vol_today / avg_vol_20d if avg_vol_20d > 0 else float("nan")

    # ── Volatility & drawdown ─────────────────────────────────────────────
    daily_ret   = close.pct_change()
    rolling_vol = daily_ret.rolling(30).std().iloc[-1] * np.sqrt(252) * 100
    roll_max    = close.cummax()
    drawdown_now = (price_now / roll_max.iloc[-1] - 1) * 100
    max_dd_1y   = ((close / close.rolling(252).max()) - 1).min() * 100

    # ── 52-week range position ────────────────────────────────────────────
    high_52w = high.tail(252).max()
    low_52w  = low.tail(252).min()
    range_pos = (price_now - low_52w) / (high_52w - low_52w) * 100 if high_52w != low_52w else 50.0

    return {
        "ticker":          ticker,
        "price_now":       price_now,
        "position_value":  price_now * shares,
        "shares":          shares,
        # Returns
        "ret_1d":   ret_1d,
        "ret_5d":   ret_5d,
        "ret_1m":   ret_1m,
        "ret_3m":   ret_3m,
        "ret_6m":   ret_6m,
        "ret_1y":   ret_1y,
        # Recent price table
        "last5_days_table": last5_str,
        # Trend
        "sma50":           sma50_val,
        "sma200":          sma200_val,
        "price_vs_sma50":  price_vs_sma50,
        "price_vs_sma200": price_vs_sma200,
        "golden_cross":    golden_cross,
        # Bollinger
        "bb_position_pct": bb_pos,
        "bb_bandwidth_pct":bb_bandwidth,
        # RSI
        "rsi_now":    rsi_now,
        "rsi_label":  rsi_label,
        "rsi_trend":  rsi_trend,
        "rsi_1w_ago": rsi_1w_ago,
        # MACD
        "macd_now":       macd_now,
        "signal_now":     sig_now,
        "hist_now":       hist_now,
        "macd_cross":     macd_cross,
        "hist_momentum":  hist_momentum,
        # Volume
        "vol_today":    vol_today,
        "avg_vol_20d":  avg_vol_20d,
        "vol_ratio":    vol_ratio,
        # Risk
        "rolling_vol_30d": rolling_vol,
        "drawdown_now":    drawdown_now,
        "max_dd_1y":       max_dd_1y,
        "range_pos_pct":   range_pos,
        "high_52w":        high_52w,
        "low_52w":         low_52w,
    }


def _build_prompt(snap: dict) -> str:
    """Formats the snapshot into a structured prompt for Gemini."""

    def _pct(v, decimals=2):
        return f"{v:+.{decimals}f}%" if not np.isnan(v) else "N/A"

    def _f(v, decimals=4):
        return f"{v:.{decimals}f}" if not np.isnan(v) else "N/A"

    return f"""You are a senior quantitative portfolio analyst providing a concise daily/weekly technical briefing for a private investor.

The investor holds {snap['shares']:.2f} units of **{snap['ticker']}** (position value: £{snap['position_value']:,.0f}).

---
## RAW TECHNICAL DATA — {snap['ticker']}

**Recent Price Action (last 5 trading days):**
{snap['last5_days_table']}

**Returns:**
- Yesterday (1D): {_pct(snap['ret_1d'])}
- Last week (5D): {_pct(snap['ret_5d'])}
- Last month (1M): {_pct(snap['ret_1m'])}
- Last 3 months (3M): {_pct(snap['ret_3m'])}
- Last 6 months (6M): {_pct(snap['ret_6m'])}
- Last 12 months (1Y): {_pct(snap['ret_1y'])}

**Trend (Moving Averages):**
- SMA 50: {_f(snap['sma50'])} | Price vs SMA50: {_pct(snap['price_vs_sma50'])}
- SMA 200: {_f(snap['sma200'])} | Price vs SMA200: {_pct(snap['price_vs_sma200'])}
- Signal: {snap['golden_cross']}

**Bollinger Bands (20-day, ±2σ):**
- Price position within bands: {_f(snap['bb_position_pct'], 1)}% (0=lower band, 100=upper band)
- Band width (volatility proxy): {_f(snap['bb_bandwidth_pct'], 2)}%

**RSI (14-day):**
- Current: {_f(snap['rsi_now'], 1)} → {snap['rsi_label']}
- 1 week ago: {_f(snap['rsi_1w_ago'], 1)} → RSI is {snap['rsi_trend']}

**MACD (12/26/9):**
- MACD line: {_f(snap['macd_now'], 4)} | Signal line: {_f(snap['signal_now'], 4)}
- Histogram: {_f(snap['hist_now'], 4)} ({snap['hist_momentum']})
- Crossover status: {snap['macd_cross']}

**Volume:**
- Today's volume: {snap['vol_today']:,.0f}
- 20-day average volume: {snap['avg_vol_20d']:,.0f}
- Volume ratio (today vs 20d avg): {_f(snap['vol_ratio'], 2)}x

**Risk Metrics:**
- Rolling 30-day annualised volatility: {_f(snap['rolling_vol_30d'], 1)}%
- Current drawdown from peak: {_pct(snap['drawdown_now'])}
- Max drawdown (1Y): {_pct(snap['max_dd_1y'])}
- 52-week range: {_f(snap['low_52w'], 2)} – {_f(snap['high_52w'], 2)} | Position in range: {_f(snap['range_pos_pct'], 1)}%

---
## YOUR TASK

Write a **concise technical brief** (4–6 short paragraphs, plain English, no bullet lists) structured as follows:

1. **Yesterday & this week** — What happened in the last 1–5 trading days? Was the move meaningful given the volume context and recent range? Any notable candlestick patterns or intraday reversals visible in the 5-day table?

2. **Momentum & trend** — What do RSI, MACD, and the moving averages collectively say about the current momentum regime? Is momentum accelerating or fading? Is the trend intact or under pressure?

3. **Key levels to watch** — Where are the meaningful support/resistance levels implied by the Bollinger Bands, SMA lines, and 52-week range position?

4. **Risk context** — Comment on volatility and drawdown. Is the ETF in a normal volatility regime or elevated? Is the current drawdown shallow or concerning?

5. **Bottom line** — One crisp sentence summarising the overall technical posture for the next 1–2 weeks. Use plain language — this is for a private investor, not a trading desk.

Be direct and specific. Refer to actual numbers from the data above. Do not hedge every sentence with disclaimers. Do not recommend buying or selling — focus purely on technical posture."""


def _run_gemini_commentary(snap: dict, api_key: str) -> str:
    """Calls Gemini with the technical snapshot and returns markdown text."""
    try:
        model = gemini_util.get_best_gemini_model(api_key)
        prompt   = _build_prompt(snap)
        response = model.generate_content(prompt)
        return response.text

    except Exception as e:
        return f"⚠️ Gemini call failed: {e}"

