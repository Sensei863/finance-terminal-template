import pandas as pd
import numpy as np

def normalize_price(ticker: str, price: float, currency: str = None, anchor: float = None) -> float:
    """
    Normalizes a single price to GBP for London-listed instruments.
    """
    if pd.isna(price) or price <= 0:
        return price
        
    mult = _determine_multiplier(ticker, price, currency, anchor)
    return price * mult

def normalize_series(ticker: str, series: pd.Series, currency: str = None, anchor: float = None, base_currency: str = 'GBP') -> pd.Series:
    """
    Normalizes a Pandas Series of prices to GBP (if base_currency is GBP).
    Replicates the reliable v1.5 engine logic.
    """
    if series.empty or base_currency != 'GBP':
        return series
        
    # Use the median value as the representative price to prevent a single-day glitch
    # on the last day from corrupting the entire 15-day baseline.
    rep_price = float(series.dropna().median()) if not series.dropna().empty else 0.0
    if rep_price <= 0:
        return series

    # 1. Determine Global Multiplier
    mult = _determine_multiplier(ticker, rep_price, currency, anchor)
    s_adj = series * mult
    
    # 2. Point-in-time per-row unit correction (Ground Truth cleanup)
    # Replicates lines 405-412 of v1.5 engine.py
    check_anchor = anchor if (anchor and anchor > 0) else (rep_price * mult)
    if check_anchor > 0:
        # Use 20x threshold as proven in v1.5
        s_adj = s_adj.apply(
            lambda x: x * 0.01 if pd.notna(x) and x > (check_anchor * 20)
            else (x * 100.0 if pd.notna(x) and x < (check_anchor * 0.05) else x)
        )
            
    return s_adj

def normalize_ohlcv(ticker: str, df_ohlcv: pd.DataFrame, currency: str = None, base_currency: str = 'GBP') -> pd.DataFrame:
    """
    Normalizes an entire OHLCV DataFrame for the screener.
    Uses median-based heuristics since no anchor exists.
    """
    if df_ohlcv is None or df_ohlcv.empty or base_currency != 'GBP':
        return df_ohlcv
        
    price_cols = [c for c in df_ohlcv.columns if c != "Volume"]
    if not price_cols:
        return df_ohlcv
        
    df_out = df_ohlcv.copy()
    
    # Check median of Close for the global multiplier
    rep_price = float(df_out["Close"].median()) if "Close" in df_out.columns else float(df_out[price_cols[0]].median())
    if rep_price <= 0:
        return df_ohlcv
        
    mult = _determine_multiplier(ticker, rep_price, currency, None)
    
    if mult != 1.0:
        df_out[price_cols] = df_out[price_cols] * mult
        
    # Pass 2: Clip individual outlier rows based on a 20x deviation from the median
    # Simplified from the "dynamic scaling" to fixed 0.01/100.0 logic
    for col in price_cols:
        df_out[col] = df_out[col].apply(
            lambda x: x * 0.01 if pd.notna(x) and x > (rep_price * mult * 20)
            else (x * 100.0 if pd.notna(x) and x < (rep_price * mult * 0.05) else x)
        )
                        
    return df_out

def _determine_multiplier(ticker: str, raw_last: float, currency: str = None, anchor: float = None) -> float:
    """
    Core heuristic engine. Replicates v1.5 thresholds exactly.
    """
    # 1. Anchor Price Test (Highest conviction - Ground Truth)
    if anchor is not None and anchor > 0 and raw_last > 0:
        ratio = raw_last / anchor
        if ratio > 20:
            return 0.01
        elif ratio < 0.05:
            return 100.0
        return 1.0
        
    # 3. Currency Tag Test (yfinance metadata) — before UK raw>500 rule
    if currency:
        curr_upper = str(currency).strip()
        if curr_upper in ["GBX", "GBp"]:
            return 0.01

    # 2. Fallback Heuristic (for LSE tickers without anchor)
    # LSE lists many names in USD/EUR; those prices are NOT pence even when raw_last > 500.
    ticker_upper = str(ticker).upper().strip()
    is_uk_ticker = ticker_upper.endswith(".L") or ticker_upper.endswith(".UK") or ticker_upper.endswith(".XLON")
    curr_tag = str(currency).strip().upper() if currency else ""
    is_foreign_major = curr_tag in (
        "USD",
        "EUR",
        "CHF",
        "JPY",
        "CAD",
        "AUD",
        "CNY",
        "HKD",
        "SGD",
        "NOK",
        "SEK",
        "DKK",
        "PLN",
    )

    if is_uk_ticker and raw_last > 500 and not is_foreign_major:
        return 0.01

    return 1.0
