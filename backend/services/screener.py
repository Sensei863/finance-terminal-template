import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
import os
import json
import logging
from pathlib import Path
from backend.services import storage
from backend.services import price_fetcher

log = logging.getLogger(__name__)

def cache_data(ttl=None, show_spinner=True):
    def decorator(func):
        import functools
        import time
        cached_val = {}
        
        def make_hashable(obj):
            if isinstance(obj, (tuple, list)):
                return tuple(make_hashable(x) for x in obj)
            elif isinstance(obj, dict):
                return tuple(sorted((k, make_hashable(v)) for k, v in obj.items()))
            return obj
            
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = (make_hashable(args), make_hashable(kwargs))
            now = time.time()
            if key in cached_val:
                result, timestamp = cached_val[key]
                if ttl is None or (now - timestamp) < ttl:
                    return result
            
            result = func(*args, **kwargs)
            cached_val[key] = (result, now)
            return result
        return wrapper
    return decorator
from datetime import datetime, timedelta

import re

from backend.services.data_handler import get_ticker_map
from backend.services import gemini_util
from backend.services import data_handler
from backend.services.engine import parse_transaction


# =====================================================================
# AI HELPERS (from appv0.py)
# =====================================================================
def fmtNum(n):
    if n is None or pd.isna(n): return "N/A"
    if n > 1e12: return f"{n/1e12:.2f}T"
    if n > 1e9: return f"{n/1e9:.2f}B"
    if n > 1e6: return f"{n/1e6:.2f}M"
    return f"{n:,.2f}"

# Removed get_available_models
DEFAULT_PROMPT_TEMPLATES = {
    "deep_dive_stock": """Role: Act as a Senior Equity Analyst writing a brief research note on {{longName}} ({{ticker}}).

**Provided Data Context:**
- Current Price: {{price}} {{currency}}
- 1-Year Return: {{one_year_return}}
- 52-Week High/Low: {{high_52}} / {{low_52}}
- Trend Signal (50-day vs 200-day SMA): {{trend}}
- P/E Ratio (Trailing): {{trailing_pe}}
- Forward P/E: {{forward_pe}}
- Dividend Yield: {{dividend_yield}}
- Market Cap: {{market_cap}}
- Industry: {{industry}}

**Analysis Requirements (in Markdown):**
1.  **Valuation:** Based on the P/E ratios, is the stock cheap, expensive, or fairly valued relative to its sector or historical average?
2.  **Growth Drivers:** What are the primary catalysts that could drive the stock's price up?
3.  **Key Risks:** What are the main headwinds or risks the company faces?
4.  **Analyst Consensus:** Briefly summarize the overall outlook.""",

    "deep_dive_etf": """Role: Act as a Senior Quantitative Investment Analyst.
Task: Provide a comprehensive but concise qualitative analysis of the following ETF: {{ticker}} ({{longName}}).

**Provided Data Context:**
- Current Price: {{price}} {{currency}}
- 1-Year Return: {{one_year_return}}
- 52-Week High/Low: {{high_52}} / {{low_52}}
- Trend Signal (50-day vs 200-day SMA): {{trend}}
- Max Drawdown (1Y): {{max_drawdown}}
- Expense Ratio: {{expense_ratio}}
- AUM: {{aum}}
- Average Volume: {{average_volume}}
- Dividend Yield: {{dividend_yield}}
- Beta (vs market): {{beta}}

**Analysis Requirements (in Markdown):**
1.  **Core Strategy & Exposure:** What is the ETF's primary investment objective and what market segment does it provide exposure to?
2.  **Performance Snapshot:** Briefly comment on its recent performance and trend relative to its 52-week range.
3.  **Risk Profile:** What are the key risks associated with this ETF (e.g., concentration, volatility, liquidity)?
4.  **Conclusion:** Summarize the key takeaways for a potential investor. Is this a core holding, tactical play, or niche satellite?""",

    "market_intel_default": """You are a senior portfolio manager at Faraglioni & Aegis Family Office writing a concise, institutional-grade Market Intelligence update. 
You must use your Google Search tool to find recent news (past 2-4 weeks) regarding the asset and its top constituents.

Asset: {{longName}} ({{ticker}})
Recent Performance: 1W: {{ret_1w}}, 1M: {{ret_1m}}, 1Y: {{ret_1y}}
Top 10 Constituents (for context): {{constituents}}

Format the report with the following sections using standard Markdown (no HTML).
## 🌍 Market Context & Price Action
Summarize the asset's recent performance. Use your search tool to explain the fundamental drivers or macro narratives that caused this movement. Keep it punchy and analytical.
## 📰 Key Developments & News
Bullet points covering the most material news items regarding the asset over the last month. 
## 🔬 Constituent Spotlight
(If the asset is an ETF, use your search tool to identify material news, earnings surprises, or events among its top 10 constituents listed above. Highlight the top 2-3 most impactful constituent stories. If this is a single stock, omit this section or discuss key competitors/suppliers.)
## 🔭 Lookahead
What are the upcoming catalysts over the next 2-4 weeks? (e.g. Earnings dates, central bank meetings, economic data).""",

    "market_intel_macro": """You are a senior portfolio manager at Faraglioni & Aegis Family Office writing a concise, institutional-grade Market Intelligence update. 
You must use your Google Search tool to find recent macro-economic news (past 2-4 weeks) that impacts this specific asset class.

Asset: {{longName}} ({{ticker}})
Asset Class Focus: Commodity / Fixed Income / Money Market
Recent Performance: 1W: {{ret_1w}}, 1M: {{ret_1m}}, 1Y: {{ret_1y}}

Format the report with the following sections using standard Markdown (no HTML).
## 🌍 Macro Context & Price Action
Summarize recent performance and the fundamental macro drivers (e.g. real yields, central bank policy, inflation prints, geopolitics) moving the asset class.
## 📰 Key Developments & News
Bullet points covering the most material macro news items impacting this asset over the last month. 
## 🏦 Yield & Rates Dynamics (or ⛏️ Commodity Dynamics)
What are the current expectations for interest rates/inflation (if bonds) or physical demand/supply (if commodity) that directly affect this asset?
## 🔭 Lookahead
What are the upcoming macro catalysts over the next 2-4 weeks? (e.g. CPI prints, central bank meetings, labor data)."""
}

VALID_PROMPT_PLACEHOLDERS = {
    "deep_dive_stock": {"ticker", "longName", "price", "currency", "one_year_return", "high_52", "low_52", "trend", "trailing_pe", "forward_pe", "dividend_yield", "market_cap", "industry"},
    "deep_dive_etf": {"ticker", "longName", "price", "currency", "one_year_return", "high_52", "low_52", "trend", "max_drawdown", "expense_ratio", "aum", "average_volume", "dividend_yield", "beta"},
    "market_intel_default": {"longName", "ticker", "ret_1w", "ret_1m", "ret_1y", "constituents"},
    "market_intel_macro": {"longName", "ticker", "ret_1w", "ret_1m", "ret_1y"}
}

def get_prompts_config_path() -> Path:
    return Path(__file__).parent.parent / "prompts_config.json"

def init_prompts_config():
    path = get_prompts_config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_PROMPT_TEMPLATES, f, indent=4)
        except Exception as e:
            log.error(f"Failed to initialize prompts_config.json: {e}")

def load_prompt(prompt_key: str) -> str:
    init_prompts_config()
    path = get_prompts_config_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                if prompt_key in cfg:
                    return cfg[prompt_key]
        except Exception as e:
            log.error(f"Failed to read prompt {prompt_key} from config: {e}")
    return DEFAULT_PROMPT_TEMPLATES.get(prompt_key, "")

def render_prompt(template: str, context: dict) -> str:
    rendered = template
    for key, val in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(val))
    return rendered

def run_ai_analysis(api_key: str, ticker: str, info: dict, metrics: dict) -> str:
    """Runs a qualitative analysis on a stock or ETF using Gemini."""
    try:
        model = gemini_util.get_best_gemini_model(api_key)
        currency = info.get('currency', 'USD')
        prompt_type = info.get('quoteType', '').upper()

        if 'ETF' in prompt_type or 'FUND' in prompt_type:
            template = load_prompt("deep_dive_etf")
            context = {
                "ticker": ticker,
                "longName": info.get('longName', ticker),
                "price": f"{metrics['Price']:.2f}",
                "currency": currency,
                "one_year_return": f"{metrics['1Y']:.2%}",
                "high_52": f"{metrics['High52']:.2f}",
                "low_52": f"{metrics['Low52']:.2f}",
                "trend": metrics['Trend'],
                "max_drawdown": f"{metrics['MaxDD']:.2%}" if metrics.get('MaxDD') is not None else "N/A",
                "expense_ratio": info.get('annualReportExpenseRatio', 'N/A'),
                "aum": fmtNum(info.get('totalAssets', 0)),
                "average_volume": fmtNum(info.get('averageVolume', 0)),
                "dividend_yield": f"{info.get('dividendYield', 0)*100:.2f}%" if info.get('dividendYield') else 'N/A',
                "beta": info.get('beta', 'N/A')
            }
        else: # Default to stock analysis
            template = load_prompt("deep_dive_stock")
            context = {
                "ticker": ticker,
                "longName": info.get('longName', ticker),
                "price": f"{metrics['Price']:.2f}",
                "currency": currency,
                "one_year_return": f"{metrics['1Y']:.2%}",
                "high_52": f"{metrics['High52']:.2f}",
                "low_52": f"{metrics['Low52']:.2f}",
                "trend": metrics['Trend'],
                "trailing_pe": str(info.get('trailingPE', 'N/A')),
                "forward_pe": str(info.get('forwardPE', 'N/A')),
                "dividend_yield": f"{info.get('dividendYield', 0)*100:.2f}%" if info.get('dividendYield') else 'N/A',
                "market_cap": fmtNum(info.get('marketCap', 0)),
                "industry": info.get('industry', 'N/A')
            }

        prompt = render_prompt(template, context)
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"#### Analysis Failed\nAn error occurred while communicating with the Gemini API: {e}"

MACRO_ONLY_TICKERS = {
    "SGLN.L", "IGLH.L", "PPFB.L", "PHGP.L", "PHAU.L", # Gold
    "ERNS.L", "IBCI.L", # Bonds
}

def get_top10_constituents(ticker: str) -> list[dict]:
    from backend.services import holdings_db
    try:
        df = holdings_db.get_latest_holdings(ticker)
        if df.empty:
            return []
        top10 = df.head(10)
        return top10.to_dict('records')
    except Exception:
        return []

def run_market_intelligence_report(api_key: str, ticker: str, info: dict, metrics: dict) -> str:
    try:
        model = gemini_util.get_best_gemini_model(api_key, search_grounding=True)
        long_name = info.get('longName', ticker)
        
        def fmt_pct(v):
            if pd.isna(v) or v is None: return "N/A"
            return f"{v:+.2%}"
        
        ret_1w = fmt_pct(metrics.get('1W'))
        ret_1m = fmt_pct(metrics.get('1M'))
        ret_1y = fmt_pct(metrics.get('1Y'))
        
        # Check if macro only
        if ticker in MACRO_ONLY_TICKERS:
            template = load_prompt("market_intel_macro")
            context = {
                "longName": long_name,
                "ticker": ticker,
                "ret_1w": ret_1w,
                "ret_1m": ret_1m,
                "ret_1y": ret_1y
            }
        else:
            constituents = get_top10_constituents(ticker)
            if constituents:
                const_lines = [f"- {c['name']} (Weight: {c['weight_pct']:.2f}%)" for c in constituents]
                constituents_str = "\n" + "\n".join(const_lines)
            else:
                constituents_str = "N/A"
            
            template = load_prompt("market_intel_default")
            context = {
                "longName": long_name,
                "ticker": ticker,
                "ret_1w": ret_1w,
                "ret_1m": ret_1m,
                "ret_1y": ret_1y,
                "constituents": constituents_str
            }
            
        prompt = render_prompt(template, context)
        response = model.generate_content(prompt, generation_config={"tools": [{"google_search": {}}]})
        return response.text
    except Exception as e:
        return f"#### Analysis Failed\nAn error occurred while generating market intelligence: {e}"



# =====================================================================
# TECHNICAL INDICATORS CALCULATIONS
# =====================================================================
def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def _bollinger(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> tuple:
    sma = _sma(series, period)
    rstd = series.rolling(window=period, min_periods=period).std()
    return sma, sma + std_dev * rstd, sma - std_dev * rstd

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
    macd_val = _ema(series, fast) - _ema(series, slow)
    sig_line = _ema(macd_val, signal)
    histogram = macd_val - sig_line
    return macd_val, sig_line, histogram


# =====================================================================
# DATA FETCHING & METRICS
# =====================================================================
def merge_metadata_with_etf_kiid(ticker: str, info: dict) -> dict:
    try:
        from backend.services import holdings_db
        kiid = holdings_db.get_kiid(ticker)
        if kiid:
            info = info.copy()
            if kiid.get("full_name"):
                info["longName"] = kiid["full_name"]
            if kiid.get("ter") is not None:
                info["annualReportExpenseRatio"] = kiid["ter"]
            if kiid.get("index_tracked"):
                info["indexTracked"] = kiid["index_tracked"]
    except Exception as e:
        log.warning(f"Error merging ETF KIID for {ticker}: {e}")
    return info

def load_or_fetch_metadata(t: str) -> dict:
    info = storage.load_ticker_metadata_quote(t)
    if info:
        return merge_metadata_with_etf_kiid(t, info)
    
    info = storage.load_ticker_metadata(t)
    
    try:
        fresh_info = yf.Ticker(t).info
        if fresh_info:
            storage.save_ticker_metadata(t, fresh_info)
            return merge_metadata_with_etf_kiid(t, fresh_info)
    except Exception as e:
        log.warning(f"Failed to fetch metadata from yfinance for {t}: {e}")
        
    if not info:
        try:
            with storage.get_app_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT info_json FROM ticker_metadata WHERE ticker = %s", (t,))
                    row = cur.fetchone()
                    if row:
                        val = row[0]
                        info = json.loads(val) if isinstance(val, str) else val
        except Exception:
            pass
            
    if info:
        return merge_metadata_with_etf_kiid(t, info)
    return {}

def get_last_trading_day() -> datetime.date:
    today = datetime.now().date()
    wd = today.weekday()
    if wd == 5:
        return today - timedelta(days=1)
    elif wd == 6:
        return today - timedelta(days=2)
    return today

def wait_for_lock_release(ticker: str, max_wait_sec: int = 15) -> bool:
    import time
    start_time = time.time()
    while time.time() - start_time < max_wait_sec:
        try:
            with storage.get_app_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM ticker_fetch_locks WHERE ticker = %s", (ticker,))
                    row = cur.fetchone()
                    if not row:
                        return True
        except Exception:
            pass
        time.sleep(0.5)
    return False

def get_ohlcv_for_ticker(t: str, start_date: datetime.date) -> pd.DataFrame:
    df_cached = storage.load_ticker_ohlcv(t, start_date)
    latest_cached = storage.get_latest_ohlcv_date(t)
    
    need_fetch = False
    fetch_start = start_date
    
    if df_cached.empty:
        need_fetch = True
    else:
        last_trading = get_last_trading_day()
        if latest_cached < last_trading:
            need_fetch = True
            fetch_start = latest_cached - timedelta(days=5)
            
        earliest_cached = df_cached.index.min().date()
        if earliest_cached > start_date + timedelta(days=10):
            need_fetch = True
            fetch_start = start_date
            
    if need_fetch:
        owner = f"screener_fetch_{os.getpid()}"
        if storage.try_acquire_fetch_lock(t, owner):
            try:
                df_fresh, source = price_fetcher.fetch_ohlcv_raw(t, fetch_start)
                if not df_fresh.empty:
                    storage.save_ticker_ohlcv(t, df_fresh, source=source)
                    df_cached = storage.load_ticker_ohlcv(t, start_date)
            except Exception as e:
                log.warning(f"Incremental fetch failed for {t}: {e}")
            finally:
                storage.release_fetch_lock(t)
        else:
            if wait_for_lock_release(t):
                df_cached = storage.load_ticker_ohlcv(t, start_date)
                
    return df_cached

@cache_data(ttl=3600)
def fetch_screener_data(tickers, benchmark_symbol, period="2y"):
    """Screener-page data fetch using yfinance & persistent cache."""
    all_tickers = list(tickers) + ([benchmark_symbol] if benchmark_symbol else [])
    unique_tickers = list(set(all_tickers))
    if not unique_tickers:
        return pd.DataFrame(), {}

    days_back = 730
    if period == "1mo": days_back = 30
    elif period == "3mo": days_back = 90
    elif period == "6mo": days_back = 180
    elif period == "1y": days_back = 365
    elif period == "2y": days_back = 730
    elif period == "5y": days_back = 1825
    elif period == "max": days_back = 3650
    start_date = datetime.now() - timedelta(days=days_back)

    ticker_dfs = {}
    info_dict = {}
    for t in unique_tickers:
        df_ticker = get_ohlcv_for_ticker(t, start_date.date())
        if not df_ticker.empty:
            ticker_dfs[t] = df_ticker
        info_dict[t] = load_or_fetch_metadata(t)

    if not ticker_dfs:
        return pd.DataFrame(), info_dict

    combined = pd.concat(ticker_dfs, axis=1)
    combined = combined.sort_index()
    return combined, info_dict


def calculate_screener_metrics(df_close):
    """Calculates performance and technical metrics for a given price series."""
    df_clean = df_close.dropna()
    if df_clean.empty or len(df_clean) < 5:
        return None
    current = df_clean.iloc[-1]

    def get_ret(days):
        return df_clean.pct_change(days).iloc[-1] if len(df_clean) > days else np.nan

    ret_1w, ret_1m, ret_3m, ret_6m, ret_1y = (get_ret(5), get_ret(21), get_ret(63), get_ret(126), get_ret(252))
    
    sma_50_series = _sma(df_clean, 50)
    sma_200_series = _sma(df_clean, 200)
    sma_50 = sma_50_series.iloc[-1] if not sma_50_series.empty else np.nan
    sma_200 = sma_200_series.iloc[-1] if not sma_200_series.empty else np.nan
    trend_signal = "NEUTRAL" if pd.isna(sma_200) or pd.isna(sma_50) else ("UPTREND" if sma_50 > sma_200 else "DOWNTREND")
    
    # Quantitative Technical Calculations
    rsi_series = _rsi(df_clean, 14)
    rsi_val = rsi_series.iloc[-1] if not rsi_series.empty else np.nan
    
    mid_bb, upper_bb, lower_bb = _bollinger(df_clean, 20, 2.0)
    bb_mid = mid_bb.iloc[-1] if not mid_bb.empty else np.nan
    bb_upper = upper_bb.iloc[-1] if not upper_bb.empty else np.nan
    bb_lower = lower_bb.iloc[-1] if not lower_bb.empty else np.nan
    bb_pos = (current - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5
    
    macd_line, sig_line, hist = _macd(df_clean, 12, 26, 9)
    macd_val = macd_line.iloc[-1] if not macd_line.empty else np.nan
    sig_val = sig_line.iloc[-1] if not sig_line.empty else np.nan
    hist_val = hist.iloc[-1] if not hist.empty else np.nan
    
    # Distance to SMAs
    dist_sma50 = (current - sma_50) / sma_50 if not pd.isna(sma_50) and sma_50 > 0 else np.nan
    dist_sma200 = (current - sma_200) / sma_200 if not pd.isna(sma_200) and sma_200 > 0 else np.nan

    lookback = min(len(df_clean), 252)
    daily_drawdown = df_clean.tail(lookback) / df_clean.tail(lookback).cummax() - 1.0
    high_52 = df_clean.tail(lookback).max()
    low_52 = df_clean.tail(lookback).min()
    denom = high_52 - low_52
    
    return {
        "Price": current, "1W": ret_1w, "1M": ret_1m, "3M": ret_3m, "6M": ret_6m, "1Y": ret_1y,
        "SMA50": sma_50, "SMA200": sma_200, "Trend": trend_signal,
        "RSI": rsi_val,
        "BB_Mid": bb_mid, "BB_Upper": bb_upper, "BB_Lower": bb_lower, "BB_Pos": bb_pos,
        "MACD": macd_val, "MACD_Signal": sig_val, "MACD_Hist": hist_val,
        "DistSMA50": dist_sma50, "DistSMA200": dist_sma200,
        "MaxDD": daily_drawdown.min(), "CurrDD": daily_drawdown.iloc[-1],
        "High52": high_52, "Low52": low_52,
        "RangePos": (current - low_52) / denom if denom > 0 else 0.5,
    }

# =====================================================================
# PORTFOLIO DATA & METRICS
# =====================================================================
@cache_data(ttl=600)
def get_ticker_portfolio_breakdown(ticker: str) -> dict:
    """Returns a dict of {account_name: shares_held} for the given ticker."""
    registry = data_handler.get_account_registry()
    breakdown = {}
    if not registry.empty and "Account Name" in registry.columns:
        from backend.services import storage
        for _, row in registry.iterrows():
            acct = str(row["Account Name"]).strip()
            port_data = storage.load_latest_portfolio(acct)
            if port_data and "positions" in port_data:
                shares = port_data["positions"].get(ticker, 0.0)
                if shares > 0.001:
                    breakdown[acct] = shares
    return breakdown

@cache_data(ttl=600)
def get_ticker_activity(ticker: str, account: str = "Consolidated", cached_info: dict = None) -> tuple:
    """Fetches transaction history and dividends for a given ticker."""
    df_ledger, is_sipp, _ = data_handler.get_sanitized_ledger(account)
    df_trades = pd.DataFrame()
    if not df_ledger.empty:
        df_parsed = df_ledger.copy()
        
        # Apply Ticker_Map to catch manually mapped tickers
        df_ticker_map = data_handler.get_ticker_map()
        df_parsed = data_handler.apply_ticker_map(df_parsed, df_ticker_map)
        
        df_trades = df_parsed[df_parsed["Auto Ticker"].astype(str).str.strip().str.upper() == ticker.strip().upper()].copy()
        if not df_trades.empty:
            df_trades["Action"] = df_trades["Action"].astype(str).str.strip().str.title()
            df_trades = df_trades[df_trades["Action"].isin(["Buy", "Sell", "Unparsed Sell (Check Diagnostics)", "Dividend"])]
            if not df_trades.empty and "Date" in df_trades.columns:
                df_trades["Date"] = pd.to_datetime(df_trades["Date"]).dt.normalize()
                df_trades = df_trades.sort_values("Date")
            
    df_dividends = pd.DataFrame()
    try:
        info = cached_info
        if not info:
            info = load_or_fetch_metadata(ticker)
        info_currency = str(info.get('currency', '')).strip() if info else ''
        
        t_obj = yf.Ticker(ticker)
        actions = t_obj.actions
        if not actions.empty and "Dividends" in actions.columns:
            divs = actions[actions["Dividends"] > 0].copy()
            divs.index = divs.index.tz_localize(None).normalize()
            df_dividends = divs[["Dividends"]].rename(columns={"Dividends": "Amount"})
            from backend.services import currency_utils
            if not df_dividends.empty:
                mult = currency_utils._determine_multiplier(ticker, float(df_dividends["Amount"].max()), currency=info_currency)
                if mult != 1.0:
                    df_dividends["Amount"] = df_dividends["Amount"] * mult
    except Exception as e:
        log.warning(f"Failed to fetch dividends / actions for {ticker}: {e}")
        
    return df_trades, df_dividends

def calculate_position_metrics(df_trades: pd.DataFrame, df_dividends: pd.DataFrame, current_price: float) -> dict:
    """Calculates Avg Book Cost, Total Return, and Yield metrics."""
    metrics = {
        "total_shares": 0.0, "avg_book_cost": 0.0, "total_invested": 0.0,
        "total_purchases": 0.0, "total_sales": 0.0, "net_cash_invested": 0.0,
        "total_dividends": 0.0, "abs_return": 0.0, "ann_return": 0.0,
        "lifetime_profit": 0.0,
        "ttm_yield": 0.0, "yield_on_cost": 0.0, "first_buy_date": None,
        "last_trade_date": None
    }
    
    total_cost = 0.0
    shares = 0.0
    if not df_trades.empty:
        for _, row in df_trades.iterrows():
            action = row["Action"]
            qty = row["Qty"]
            net_amt = row["Net Amount"]
            if action == "Buy":
                shares += qty
                total_cost += abs(net_amt)
                metrics["total_purchases"] += abs(net_amt)
            elif action in ("Sell", "Unparsed Sell (Check Diagnostics)"):
                metrics["total_sales"] += abs(net_amt)
                if shares > 0:
                    avg_cost_before = total_cost / shares
                    shares = max(0.0, shares - qty)
                    total_cost = shares * avg_cost_before
                    
        metrics["total_shares"] = shares
        metrics["net_cash_invested"] = metrics["total_purchases"] - metrics["total_sales"]
        metrics["first_buy_date"] = df_trades["Date"].min()
        metrics["last_trade_date"] = df_trades["Date"].max()
        
        if shares > 0.001:
            metrics["avg_book_cost"] = total_cost / shares
            metrics["total_invested"] = total_cost
            
    cumulative_divs = 0.0
    ttm_divs_per_share = 0.0
    now = pd.Timestamp.today().normalize()
    one_year_ago = now - pd.Timedelta(days=365)
    
    if not df_dividends.empty:
        trade_dates = df_trades["Date"].tolist() if not df_trades.empty else []
        trade_actions = df_trades["Action"].tolist() if not df_trades.empty else []
        trade_qtys = df_trades["Qty"].tolist() if not df_trades.empty else []
        
        for div_date, row in df_dividends.iterrows():
            div_amt = row["Amount"]
            if div_date >= one_year_ago:
                ttm_divs_per_share += div_amt
                
            if metrics["first_buy_date"] is not None and div_date >= metrics["first_buy_date"]:
                shares_held = 0.0
                for d, a, q in zip(trade_dates, trade_actions, trade_qtys):
                    if d <= div_date:
                        if a == "Buy": shares_held += q
                        else: shares_held = max(0.0, shares_held - q)
                if shares_held > 0.001:
                    cumulative_divs += shares_held * div_amt

        metrics["total_dividends"] = cumulative_divs
        
    # Check if we have manually recorded dividends in the ledger
    if not df_trades.empty:
        df_divs = df_trades[df_trades["Action"] == "Dividend"]
        if not df_divs.empty:
            metrics["total_dividends"] = float(df_divs["Net Amount"].abs().sum())
        
    has_trades = (not df_trades.empty and metrics["total_purchases"] > 0)
    
    if has_trades:
        current_value = metrics["total_shares"] * current_price
        metrics["lifetime_profit"] = current_value - metrics["total_purchases"] + metrics["total_sales"] + metrics["total_dividends"]
        metrics["unrealised_profit"] = current_value - metrics["total_invested"]
        metrics["realised_profit"] = metrics["lifetime_profit"] - metrics["unrealised_profit"] - metrics["total_dividends"]
        
        if metrics["total_purchases"] > 0:
             metrics["abs_return"] = metrics["lifetime_profit"] / metrics["total_purchases"]
        
        # Lock exited return CAGR to holding period
        if metrics["total_shares"] <= 0.001 and metrics["last_trade_date"] is not None:
            holding_days = (metrics["last_trade_date"] - metrics["first_buy_date"]).days
        else:
            holding_days = (now - metrics["first_buy_date"]).days
            
        if holding_days > 0:
            metrics["ann_return"] = (1 + metrics["abs_return"]) ** (365.25 / holding_days) - 1.0
            
        if current_price > 0:
            metrics["ttm_yield"] = ttm_divs_per_share / current_price
            
        if metrics["total_shares"] > 0.001 and metrics["avg_book_cost"] > 0:
            metrics["yield_on_cost"] = ttm_divs_per_share / metrics["avg_book_cost"]
        else:
            metrics["yield_on_cost"] = 0.0
            
    return metrics

# =====================================================================
# RENDER FUNCTION
# =====================================================================
@cache_data(ttl=600)
def get_exited_tickers_last_12m(account: str = "Consolidated") -> list[str]:
    """
    Scans the requested ledger to find tickers that are currently exited 
    (shares <= 0.001) but had transactions in the last 12 months.
    """
    df_ledger, _, _ = data_handler.get_sanitized_ledger(account)
    if df_ledger.empty:
        return []
        
    df_parsed = df_ledger.copy()
    
    df_ticker_map = data_handler.get_ticker_map()
    df_parsed = data_handler.apply_ticker_map(df_parsed, df_ticker_map)
    
    df_parsed = df_parsed.dropna(subset=["Auto Ticker"])
    df_parsed = df_parsed[df_parsed["Auto Ticker"] != ""]
    
    shares_map = {}
    last_trade_date = {}
    
    for _, row in df_parsed.iterrows():
        t = str(row["Auto Ticker"]).strip().upper()
        action = str(row["Action"]).strip().title()
        qty = row["Qty"]
        date_val = row["Date"]
        
        if pd.isna(qty) or qty is None:
            qty = 0.0
            
        if action == "Buy":
            shares_map[t] = shares_map.get(t, 0.0) + qty
            last_trade_date[t] = max(last_trade_date.get(t, date_val), date_val)
        elif action in ("Sell", "Unparsed Sell (Check Diagnostics)"):
            shares_map[t] = max(0.0, shares_map.get(t, 0.0) - qty)
            last_trade_date[t] = max(last_trade_date.get(t, date_val), date_val)
            
    exited_tickers = []
    now = pd.Timestamp.today().normalize()
    one_year_ago = now - pd.Timedelta(days=365)
    
    for t, shares in shares_map.items():
        if shares <= 0.001:
            t_last_date = last_trade_date.get(t)
            if t_last_date and t_last_date >= one_year_ago:
                exited_tickers.append(t)
                
    return exited_tickers

def get_cached_fx_close(yahoo_fx: str, start_date) -> pd.Series:
    """
    Fetch FX close series using DB cache layer.
    """
    df_cached = storage.load_ticker_ohlcv(yahoo_fx, start_date)
    latest_cached = storage.get_latest_ohlcv_date(yahoo_fx)
    
    need_fetch = False
    if df_cached.empty:
        need_fetch = True
    else:
        last_trading = get_last_trading_day()
        if latest_cached < last_trading:
            need_fetch = True
            
    if need_fetch:
        owner = f"screener_fx_{os.getpid()}"
        if storage.try_acquire_fetch_lock(yahoo_fx, owner):
            try:
                fetch_start = start_date
                if latest_cached:
                    fetch_start = latest_cached - timedelta(days=5)
                df_fresh, source = price_fetcher.fetch_ohlcv_raw(yahoo_fx, fetch_start)
                if not df_fresh.empty:
                    storage.save_ticker_ohlcv(yahoo_fx, df_fresh, source=source)
                    df_cached = storage.load_ticker_ohlcv(yahoo_fx, start_date)
            except Exception as e:
                log.warning(f"FX fetch failed for {yahoo_fx}: {e}")
            finally:
                storage.release_fetch_lock(yahoo_fx)
                
    if not df_cached.empty and "Close" in df_cached.columns:
        return df_cached["Close"]
    return pd.Series(dtype=float)


