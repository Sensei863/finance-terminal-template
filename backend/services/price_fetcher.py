import os
import io
import urllib.request
import urllib.error
import logging
import pandas as pd
import numpy as np

log = logging.getLogger(__name__)

try:
    import pandas_datareader as pdr
    _HAVE_PDR = True
except ImportError:
    _HAVE_PDR = False


def _to_stooq(yahoo_ticker: str) -> str:
    """
    Convert a Yahoo Finance ticker symbol to its Stooq equivalent.
    """
    t = yahoo_ticker.strip()
    SUFFIX_MAP = {
        ".XLON": ".UK",
        ".L":    ".UK",
        ".MI":   ".IT",
        ".PA":   ".FR",
        ".AS":   ".NL",
        ".DE":   ".DE",
        ".SW":   ".CH",
        ".MC":   ".ES",
    }
    upper = t.upper()
    for yahoo_sfx, stooq_sfx in SUFFIX_MAP.items():
        if upper.endswith(yahoo_sfx):
            return t[: -len(yahoo_sfx)] + stooq_sfx
    return t


def _fetch_stooq_pdr(stooq_symbol: str, start_date) -> pd.DataFrame:
    """
    Fetch daily OHLCV from Stooq using pandas_datareader (preferred path).
    """
    if not _HAVE_PDR:
        return pd.DataFrame()
        
    end_date = pd.Timestamp.today().normalize()
    df = pdr.get_data_stooq(stooq_symbol, start=start_date, end=end_date)
    if df.empty:
        return pd.DataFrame()
    df = df.sort_index()
    df.index = pd.to_datetime(df.index).normalize()
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df = df[~df.index.duplicated(keep="last")]
    
    # Ensure expected columns exist
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col not in df.columns:
            df[col] = np.nan
            
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])


def _fetch_stooq_csv(stooq_symbol: str, start_date) -> pd.DataFrame:
    """
    Fetch daily OHLCV directly from the Stooq CSV endpoint (fallback).
    """
    start_str = pd.Timestamp(start_date).strftime("%Y%m%d")
    end_str   = pd.Timestamp.today().strftime("%Y%m%d")
    url = (
        f"https://stooq.com/q/d/l/"
        f"?s={stooq_symbol.lower()}&d1={start_str}&d2={end_str}&i=d"
        f"&apikey=CPElSq8GHZjC9pJw2OD5hmczrLgRsoMa"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")

    df = pd.read_csv(io.StringIO(raw), index_col="Date", parse_dates=True)
    if df.empty or "Close" not in df.columns:
        return pd.DataFrame()
    df = df.sort_index()
    df.index = pd.to_datetime(df.index).normalize()
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df = df[~df.index.duplicated(keep="last")]
    
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col not in df.columns:
            df[col] = np.nan
            
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])


def _fetch_stooq(stooq_symbol: str, start_date) -> pd.DataFrame:
    """
    Unified Stooq fetcher. Tries pandas_datareader first, then direct CSV.
    """
    if _HAVE_PDR:
        try:
            df = _fetch_stooq_pdr(stooq_symbol, start_date)
            if not df.empty:
                return df
        except Exception:
            pass
    try:
        return _fetch_stooq_csv(stooq_symbol, start_date)
    except Exception:
        return pd.DataFrame()


def _fetch_yahoo(yahoo_symbol: str, start_date) -> pd.DataFrame:
    """
    Fetch daily OHLCV from Yahoo Finance via yfinance as fallback.
    """
    try:
        import yf_patch
    except ImportError:
        pass
        
    import yfinance as yf
    start = pd.Timestamp(start_date)
    
    try:
        raw = yf.download(
            yahoo_symbol,
            start=start.strftime("%Y-%m-%d"),
            auto_adjust=True,
            progress=False,
            threads=False
        )
        if raw.empty:
            return pd.DataFrame()
            
        df = pd.DataFrame(index=raw.index)
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if isinstance(raw.columns, pd.MultiIndex):
                # Try levels for ticker and column name
                if col in raw.columns.levels[0]:
                    if yahoo_symbol in raw.columns.levels[1]:
                        df[col] = raw[(col, yahoo_symbol)]
                    else:
                        if yahoo_symbol in raw.columns.levels[0]:
                            df[col] = raw[(yahoo_symbol, col)]
                        else:
                            df[col] = raw[col].iloc[:, 0]
                else:
                    df[col] = np.nan
            else:
                if col in raw.columns:
                    df[col] = raw[col]
                else:
                    df[col] = np.nan
                    
        df = df.sort_index()
        df.index = pd.to_datetime(df.index).normalize()
        if hasattr(df.index, "tz") and df.index.tz is not None:
            df.index = df.index.tz_localize(None)
            
        df = df[~df.index.duplicated(keep="last")]
        return df.dropna(subset=["Close"])
    except Exception as e:
        log.warning(f"_fetch_yahoo failed for {yahoo_symbol}: {e}")
        return pd.DataFrame()


def fetch_ohlcv_raw(ticker: str, start_date, normalize: bool = True) -> tuple[pd.DataFrame, str]:
    """
    Primary price fetcher with fallback.
    Returns (dataframe, source) where:
        dataframe: index=Date (normalize), columns=[Open, High, Low, Close, Volume]
        source: 'stooq' | 'yfinance' | 'Failed'
    """
    # Try Stooq first (preferred for UK/LSE)
    stooq_symbol = _to_stooq(ticker)
    df = _fetch_stooq(stooq_symbol, start_date)
    if not df.empty:
        source = "stooq"
    else:
        df = _fetch_yahoo(ticker, start_date)
        if not df.empty:
            source = "yfinance"
        else:
            return pd.DataFrame(), "Failed"
            
    # Apply Pence/Pound cleanse (native listing currency)
    if normalize:
        from backend.services.engine import _get_yahoo_quote_currency
        quote_ccy = _get_yahoo_quote_currency(ticker)
        
        from backend.services import currency_utils
        df = currency_utils.normalize_ohlcv(ticker, df, currency=quote_ccy, base_currency='GBP')
    
    return df, source
