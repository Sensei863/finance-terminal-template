"""
lookahead_engine.py
───────────────────
Core analytical engine for the ETF Look-Through module.

Responsibilities
────────────────
1.  Build the "exploded" portfolio view: positions → ETF weights → constituent weights
2.  Enrich constituents with sector / geography metadata (yfinance, cached in SQLite)
3.  Compute the three analyses:
      a) Overlap matrix
      b) Sector & geography breakdown
      c) Top-mover attribution (daily / weekly P&L contribution)
4.  Manage the computation cache — skip full re-run if nothing has changed

Design notes
────────────
• This module is STATELESS. It reads from holdings_db and returns DataFrames.
• All yfinance calls are batched and results are persisted to constituent_metadata
  to avoid redundant network traffic on every page load.
• The cache key is (sorted ETF tickers in portfolio + sorted upload_dates). If
  either changes the cache is stale and is recomputed on demand.
• Equity-only analysis: rows with asset_class != "Equity" are excluded from
  overlap and sector breakdowns (but kept in top-mover attribution if present).
"""

import pandas as pd
from backend.services import gemini_util
import numpy as np
import yfinance as yf
from datetime import date, timedelta
import time
import re

from backend.services import holdings_db as hdb


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EQUITY_CLASS          = "Equity"
MIN_WEIGHT_PCT        = 0.01   # constituents below this % of portfolio are ignored
METADATA_MAX_AGE_DAYS = 90     # re-fetch sector/geo metadata if older than this

# yfinance metadata fetch tuning
_BATCH_SIZE       = 50    # flush to SQLite every N records
_INTER_CALL_SLEEP = 0.25  # seconds between .info calls  (~240/min, safe)
_BATCH_PAUSE      = 3.0   # extra pause every _BATCH_SIZE calls
_MAX_RETRIES      = 2     # retries for transient HTTP errors
_RETRY_BACKOFF    = 5.0   # seconds per retry attempt (multiplied by attempt #)

# Top-movers price cache: reuse a single yf.download result within the same
# Python process rather than re-downloading on every cache-hit page load.
# Keyed by (frozenset(tickers), period, today_date).
_MOVERS_PRICE_CACHE: dict = {}
_MOVERS_CACHE_MAX_AGE_SECONDS = 3600   # 1 hour TTL

# ---------------------------------------------------------------------------
# Name normalisation helpers — used by both overlap and top-holdings engines
# ---------------------------------------------------------------------------

# Legal/corporate suffixes to strip when normalising constituent names.
# This lets "SAMSUNG ELECTRONICS CO" match "Samsung Electronics Co Ltd".
_LEGAL_SUFFIXES = re.compile(
    r"\b(ltd|limited|inc|corp|corporation|co|plc|ag|sa|nv|bv|se|"
    r"spa|srl|ab|asa|oyj|as|holdings|group|intl|international|"
    r"the|company|enterprises|ventures)\b[\s,\.]*$",
    re.IGNORECASE,
)

def _normalise_name(name: str) -> str:
    """
    Canonical name key for fuzzy constituent matching.
    Strips legal suffixes, collapses whitespace, lowercases.
    Examples:
        "SAMSUNG ELECTRONICS CO"   → "samsung electronics"
        "Samsung Electronics Co Ltd" → "samsung electronics"
        "NVIDIA CORP"              → "nvidia"
        "NVIDIA Corp"              → "nvidia"
    """
    s = str(name or "").strip()
    # Remove content in parentheses (e.g. share class qualifiers)
    s = re.sub(r"\([^)]*\)", "", s)
    # Iteratively strip trailing legal suffixes
    prev = None
    while prev != s:
        prev = s
        s = _LEGAL_SUFFIXES.sub("", s).strip().rstrip(",. ")
    return s.lower().strip()



# ---------------------------------------------------------------------------
# yfinance helpers
# ---------------------------------------------------------------------------

def _is_valid_yf_info(info: dict) -> bool:
    """
    Return True only if yfinance returned a genuinely populated info dict.

    yfinance returns a near-empty stub like {"trailingPegRatio": None} for
    unknown / delisted tickers instead of raising an exception.  We guard
    against caching that garbage by requiring a real quoteType and a name.
    """
    if not info or not isinstance(info, dict):
        return False
    qt = info.get("quoteType", "NONE")
    if not qt or str(qt).upper() in ("NONE", ""):
        return False
    if not info.get("shortName") and not info.get("longName"):
        return False
    return True


def _rate_limit_sleep(idx: int) -> None:
    """Inter-call pacing: longer pause every _BATCH_SIZE calls."""
    if (idx + 1) % _BATCH_SIZE == 0:
        time.sleep(_BATCH_PAUSE)
    else:
        time.sleep(_INTER_CALL_SLEEP)


# ---------------------------------------------------------------------------
# Ticker normalisation — convert provider formats to Yahoo Finance symbols
# ---------------------------------------------------------------------------

# Bloomberg exchange suffix → Yahoo Finance suffix
# Covers the most common exchanges seen in ETF holdings files.
_BLOOMBERG_EXCHANGE_MAP = {
    # Equities
    "US":  "",        # US-listed — no suffix needed
    "LN":  ".L",      # London Stock Exchange
    "FP":  ".PA",     # Euronext Paris
    "GY":  ".DE",     # XETRA (Germany)
    "GR":  ".DE",     # Frankfurt / XETRA
    "IM":  ".MI",     # Borsa Italiana (Milan)
    "SM":  ".MC",     # Bolsa Madrid
    "NA":  ".AS",     # Euronext Amsterdam
    "BB":  ".BR",     # Euronext Brussels
    "SW":  ".SW",     # SIX Swiss Exchange
    "SS":  ".ST",     # Nasdaq Stockholm
    "NO":  ".OL",     # Oslo Bors
    "DC":  ".CO",     # Nasdaq Copenhagen
    "HB":  ".HE",     # Nasdaq Helsinki
    "ID":  ".IR",     # Euronext Dublin
    "PL":  ".LS",     # Euronext Lisbon
    "AV":  ".VI",     # Vienna Stock Exchange
    "PW":  ".WA",     # Warsaw Stock Exchange
    "SP":  ".SI",     # Singapore Exchange
    "AU":  ".AX",     # ASX (Australia)
    "AT":  ".AT",     # Athens Stock Exchange
    "IT":  ".TA",     # Tel Aviv Stock Exchange
    "KS":  ".KS",     # Korea Stock Exchange
    "KQ":  ".KQ",     # KOSDAQ (Korea)
    "JP":  ".T",      # Tokyo Stock Exchange (fallback — numeric codes handled separately)
    "HK":  ".HK",     # Hong Kong Stock Exchange
    "TT":  ".TW",     # Taiwan Stock Exchange
    "IN":  ".NS",     # NSE India
    "SJ":  ".JO",     # Johannesburg Stock Exchange
    "BZ":  ".SA",     # B3 (Brazil)
    "MX":  ".MX",     # BMV (Mexico)
    "CN":  ".TO",     # Toronto Stock Exchange
    "CT":  ".TO",     # TSX (alternative suffix)
    "CI":  ".NE",     # CBOE Canada
}

# Exchanges where numeric tickers need zero-padding to a fixed width
_NUMERIC_TICKER_PADDING = {
    ".T":  4,   # Tokyo: 4-digit codes (7203 → 7203.T)
    ".KS": 6,   # Korea: 6-digit codes (005930 → 005930.KS)
    ".KQ": 6,
    ".HK": 4,   # Hong Kong: 4-digit codes
    ".TW": 4,
}


def normalise_ticker(raw: str) -> str:
    """
    Convert a raw constituent ticker from any provider format to a
    Yahoo Finance-compatible symbol.

    Handles:
      Bloomberg format  : "RTX US" → "RTX", "HO FP" → "HO.PA", "SAAB B SS" → "SAABB.ST"
      US Share Classes  : "BRK/A" → "BRK-A"
      Trailing Junk     : "BA/" → "BA", "QQ/.L" → "QQ.L", "RR." → "RR"
      Numeric TSE/KRX   : "8035" → "8035.T",  "005930" → "005930.KS"
      Already-valid YF  : "AAPL", "BAYN.DE" — returned unchanged

    Returns the original string cleaned/normalised.
    """
    if not raw or not isinstance(raw, str):
        return raw

    # 1. Skip obvious junk / placeholders
    ticker = raw.strip()
    if ticker.upper() in ("", "NAN", "NONE", "N/A", "<NA>", "NULL"):
        return ""

    ticker = re.sub(r'^ticker:\s*', '', ticker, flags=re.I)
    
    # 2. Already has a Yahoo suffix? (e.g. "BAYN.DE")
    # But clean internal junk (e.g. "QQ/.L" → "QQ.L")
    if re.search(r'\.[A-Z]{1,3}$', ticker):
        if "/" in ticker or " " in ticker:
            base, suffix = ticker.rsplit(".", 1)
            # Join base parts: "SAAB B" → "SAABB"
            base = "".join(base.split())
            base = base.replace("/", "-").replace("--", "-").rstrip("./-")
            return f"{base}.{suffix}"
        return ticker

    # 3. Handle Bloomberg-style spaced tickers (e.g. "RTX US", "SAAB B SS")
    parts = ticker.split()
    if len(parts) >= 2:
        last_part = parts[-1].upper()
        if last_part in _BLOOMBERG_EXCHANGE_MAP:
            # Join all preceding parts: "SAAB B" "SS" → "SAABB"
            base = "".join(parts[:-1]).upper()
            suffix = _BLOOMBERG_EXCHANGE_MAP[last_part]
            # Clean base: "BRK/A" → "BRK-A"
            base = base.replace("/", "-").replace("--", "-").rstrip("./-")
            return base + suffix

    # 4. Fallback: general punctuation cleaning for known issues
    # "BRK/A" → "BRK-A", "BA/" → "BA", "SAAB B" → "SAAB-B"
    ticker = ticker.replace("/", "-").replace(" ", "-").replace("--", "-").rstrip("./-")
    
    # 5. Pure numeric tickers (TSE/KRX)
    if re.match(r'^\d+$', ticker):
        n = len(ticker)
        if n <= 4:
            # 4-digit or shorter → Tokyo Stock Exchange
            return ticker.zfill(4) + ".T"
        elif n == 5:
            # 5-digit → likely Tokyo
            return ticker + ".T"
        elif n == 6:
            # 6-digit → Korean exchange (KRX)
            return ticker + ".KS"

    return ticker


def normalise_tickers(tickers: list[str]) -> dict[str, str]:
    """
    Normalise a list of raw tickers.
    Returns {raw_ticker: normalised_ticker} mapping.
    Tickers that are unchanged map to themselves.
    """
    return {t: normalise_ticker(t) for t in tickers}


def _fetch_and_cache_metadata(symbols: list[str]) -> None:
    """
    Fetch sector/country/market-cap metadata from yfinance for a list of
    symbols and persist to the SQLite constituent_metadata cache.

    Guarantees
    ----------
    Rate-safe  : 0.25 s/call + 3 s pause every 50 calls (~180 calls/min).
    Validated  : empty yfinance stubs are discarded so bad data is never
                 cached (a future refresh will retry those symbols).
    Retry      : transient HTTP/connection errors get up to _MAX_RETRIES
                 attempts with linear back-off before being skipped.
    Crash-safe : records are flushed to SQLite every _BATCH_SIZE symbols,
                 so a crash mid-run preserves all completed work.
    Progress   : Streamlit progress bar when running inside the app;
                 plain print() fallback for CLI / test contexts.
    """
    if not symbols:
        return

    try:
        import streamlit as st
        _use_st = True
    except ImportError:
        _use_st = False

    total = len(symbols)
    new_records: list[dict] = []

    progress_bar = None
    status_text  = None

    def _flush(records: list[dict]) -> None:
        if records:
            hdb.save_metadata_batch(records)
            records.clear()

    for idx, symbol in enumerate(symbols):
        pct = idx / total
        yf_symbol = normalise_ticker(symbol)   # convert to Yahoo Finance format
        msg = f"Fetching metadata {idx + 1}/{total} - {yf_symbol}"
        if _use_st:
            progress_bar.progress(pct, text=msg)
        elif idx % 25 == 0:
            print(f"  {msg}")

        info: dict = {}
        for attempt in range(_MAX_RETRIES + 1):
            try:
                info = yf.Ticker(yf_symbol).info
                break
            except Exception as exc:
                err = str(exc).lower()
                is_transient = any(k in err for k in
                                   ("connection", "timeout", "503", "502", "rate"))
                if is_transient and attempt < _MAX_RETRIES:
                    wait = _RETRY_BACKOFF * (attempt + 1)
                    if _use_st:
                        status_text.warning(
                            f"Transient error for {yf_symbol} "
                            f"(attempt {attempt + 1}/{_MAX_RETRIES + 1}) - "
                            f"waiting {wait:.0f}s..."
                        )
                    time.sleep(wait)
                else:
                    info = {}
                    break

        if not _is_valid_yf_info(info):
            _rate_limit_sleep(idx)
            continue

        # Extract the real ISIN if yfinance returned one
        # (present in info for most stocks as a 12-char alphanumeric string)
        real_isin = None
        for field in ("isin", "ISIN"):
            val = info.get(field)
            if val and isinstance(val, str) and len(val) == 12 and val[:2].isalpha():
                real_isin = val.upper()
                break

        new_records.append({
            "isin":       symbol,      # original key for cache lookup (ISIN or raw ticker)
            "ticker":     yf_symbol,   # normalised Yahoo Finance symbol
            "name":       info.get("longName") or info.get("shortName", ""),
            "sector":     info.get("sector") or "",
            "industry":   info.get("industry") or "",
            "country":    info.get("country") or "",
            "market_cap": info.get("marketCap"),
        })

        # If yfinance gave us a real ISIN for this ticker, save the mapping
        # so the overlap engine can resolve ticker-keyed ETFs to ISINs
        if real_isin:
            base_ticker = yf_symbol.split(".")[0].upper()
            hdb.save_ticker_isin_map({base_ticker: real_isin})

        _rate_limit_sleep(idx)

        if len(new_records) >= _BATCH_SIZE:
            _flush(new_records)

    _flush(new_records)

    if _use_st:
        progress_bar.progress(1.0, text=f"Metadata ready ({total} symbols processed).")
        status_text.empty()


# ---------------------------------------------------------------------------
# 1. Portfolio explosion — positions → constituent rows
# ---------------------------------------------------------------------------

def build_exploded_portfolio(
    positions: dict,                  # {yahoo_ticker: shares}
    df_prices: pd.DataFrame,          # price grid from calculate_twr_series
    etf_tickers_with_holdings: list[str],
) -> pd.DataFrame:
    """
    Multiply portfolio positions through ETF holdings files to produce
    a constituent-level view.

    For each ETF in `positions`:
      - If a holdings file exists: expand into constituent rows
      - Otherwise: keep as a single "opaque" row (MISSING_HOLDINGS flag)

    For non-ETF positions (e.g. individual stocks):
      - Pass through as-is with weight = their portfolio share

    Returns a DataFrame with columns:
        etf_ticker, constituent_isin, constituent_ticker, constituent_name,
        etf_weight_pct, portfolio_weight_pct, effective_value_gbp,
        asset_class, has_holdings
    """
    if not positions:
        return pd.DataFrame()

    # ── 1a. Compute current portfolio NAV per position ────────────────────
    today = pd.Timestamp.today().normalize()
    pos_values: dict[str, float] = {}
    total_nav = 0.0

    for ticker, shares in positions.items():
        if shares <= 0:
            continue
        price = np.nan
        if not df_prices.empty and ticker in df_prices.columns:
            # Walk back up to 5 trading days for the last valid price
            for lag in range(6):
                d = today - pd.Timedelta(days=lag)
                if d in df_prices.index and pd.notna(df_prices.loc[d, ticker]):
                    price = float(df_prices.loc[d, ticker])
                    break
        if pd.notna(price) and price > 0:
            val = shares * price
            pos_values[ticker] = val
            total_nav += val

    if total_nav <= 0:
        return pd.DataFrame()

    # ── 1b. Explode each position ──────────────────────────────────────────
    rows = []
    holdings_db_cache = {}  # {etf_ticker: df_holdings}

    for ticker, portfolio_value in pos_values.items():
        port_weight = (portfolio_value / total_nav) * 100.0

        if ticker in etf_tickers_with_holdings:
            # Fetch latest holdings
            if ticker not in holdings_db_cache:
                holdings_db_cache[ticker] = hdb.get_latest_holdings(ticker)
            df_h = holdings_db_cache[ticker]

            # Filter to equity only for the look-through
            df_eq = df_h[df_h["asset_class"] == EQUITY_CLASS].copy()
            if df_eq.empty:
                df_eq = df_h.copy()   # fallback: use all rows

            # Normalise weights within the file (they may not sum to 100)
            total_file_weight = df_eq["weight_pct"].sum()
            if total_file_weight > 0:
                df_eq["weight_pct_norm"] = df_eq["weight_pct"] / total_file_weight * 100.0
            else:
                df_eq["weight_pct_norm"] = df_eq["weight_pct"]

            for _, constituent in df_eq.iterrows():
                etf_w  = float(constituent["weight_pct"])
                # Effective portfolio weight = portfolio_weight × constituent_weight / 100
                eff_w  = port_weight * (etf_w / 100.0)
                eff_val = portfolio_value * (etf_w / 100.0)

                rows.append({
                    "etf_ticker":           ticker,
                    "constituent_isin":     constituent.get("isin") or "",
                    "constituent_ticker":   constituent.get("constituent_ticker") or "",
                    "constituent_name":     constituent.get("name", ""),
                    "etf_weight_pct":       etf_w,
                    "portfolio_weight_pct": eff_w,
                    "effective_value_gbp":  eff_val,
                    "asset_class":          constituent.get("asset_class", EQUITY_CLASS),
                    "has_holdings":         True,
                })
        else:
            # Single position — treat as its own constituent
            rows.append({
                "etf_ticker":           ticker,
                "constituent_isin":     "",
                "constituent_ticker":   ticker,
                "constituent_name":     ticker,
                "etf_weight_pct":       100.0,
                "portfolio_weight_pct": port_weight,
                "effective_value_gbp":  portfolio_value,
                "asset_class":          EQUITY_CLASS,
                "has_holdings":         ticker in etf_tickers_with_holdings,
            })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Drop negligible positions
    df = df[df["portfolio_weight_pct"] >= MIN_WEIGHT_PCT].copy()

    return df.sort_values("portfolio_weight_pct", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 2. Metadata enrichment — sector / geography from yfinance
# ---------------------------------------------------------------------------

def enrich_with_metadata(df_exploded: pd.DataFrame, allow_network: bool = True) -> pd.DataFrame:
    """
    Join sector/geography metadata onto the exploded portfolio.

    Priority order for sector/country:
      1. Values already present in the holdings file (e.g. Amundi exports include
         Sector and Country columns) — stored as 'sector_from_file' / 'country_from_file'
      2. SQLite constituent_metadata cache (populated from prior yfinance fetches)
      3. Fresh yfinance fetch for anything still missing
    """
    if df_exploded.empty:
        return df_exploded

    df_out = df_exploded.copy()

    # Initialise metadata columns if not present
    if "sector" not in df_out.columns:
        df_out["sector"] = ""
    if "country" not in df_out.columns:
        df_out["country"] = ""

    # ── Pass 1: use values already in the file (Amundi provides these) ────
    if "sector_from_file" in df_out.columns:
        mask = df_out["sector_from_file"].fillna("").str.strip() != ""
        df_out.loc[mask, "sector"] = df_out.loc[mask, "sector_from_file"]

    if "country_from_file" in df_out.columns:
        mask = df_out["country_from_file"].fillna("").str.strip() != ""
        df_out.loc[mask, "country"] = df_out.loc[mask, "country_from_file"]

    # ── Pass 2 & 3: yfinance for rows still missing metadata ──────────────
    still_missing_sector  = df_out["sector"].fillna("").str.strip() == ""
    still_missing_country = df_out["country"].fillna("").str.strip() == ""
    needs_meta = still_missing_sector | still_missing_country

    if not needs_meta.any():
        # All metadata already sourced from file — skip yfinance entirely
        df_out["sector"]  = df_out["sector"].replace({"": "Unknown", "nan": "Unknown"}).fillna("Unknown")
        df_out["country"] = df_out["country"].replace({"": "Unknown", "nan": "Unknown"}).fillna("Unknown")
        return df_out

    # Collect ISINs / tickers that need enrichment
    isins = (
        df_out.loc[needs_meta, "constituent_isin"]
        .dropna()
        .unique()
        .tolist()
    )
    isins = [i for i in isins if i and i != ""]

    # Check cache
    cached_df = hdb.get_cached_metadata(isins) if isins else pd.DataFrame()
    stale_cutoff = (date.today() - timedelta(days=METADATA_MAX_AGE_DAYS)).isoformat()
    if not cached_df.empty:
        fresh = cached_df[cached_df["fetched_at"] >= stale_cutoff]["isin"].tolist()
        need_fetch = [i for i in isins if i not in fresh]
    else:
        need_fetch = isins

    # Tickers for rows with no ISIN and no metadata
    tickers_no_isin = (
        df_out.loc[needs_meta & (df_out["constituent_isin"] == ""), "constituent_ticker"]
        .dropna()
        .unique()
        .tolist()
    )
    tickers_no_isin = [t for t in tickers_no_isin if t and t != ""]

    new_records = []
    symbols_to_fetch = list(set(need_fetch + tickers_no_isin))

    if symbols_to_fetch and allow_network:
        for symbol in symbols_to_fetch:
            try:
                # Always normalise to Yahoo Finance format before fetching
                # (e.g. "BRKB" → "BRK-B", "BA." → "BA.L", "005930" → "005930.KS")
                yf_symbol = normalise_ticker(symbol)
                info = yf.Ticker(yf_symbol).info
                new_records.append({
                    "isin":       symbol,      # keep original as lookup key
                    "ticker":     yf_symbol,   # store the normalised YF ticker
                    "name":       info.get("longName") or info.get("shortName", ""),
                    "sector":     info.get("sector", ""),
                    "industry":   info.get("industry", ""),
                    "country":    info.get("country", ""),
                    "market_cap": info.get("marketCap"),
                })
                time.sleep(0.1)
            except Exception:
                continue

        if new_records:
            hdb.save_metadata_batch(new_records)
            cached_df = hdb.get_cached_metadata(isins) if isins else pd.DataFrame()
            if tickers_no_isin:
                extra = hdb.get_cached_metadata(tickers_no_isin)
                if not extra.empty:
                    cached_df = pd.concat([cached_df, extra], ignore_index=True)

    # Merge cached metadata for rows that still need it
    if not cached_df.empty:
        meta = cached_df[["isin", "sector", "industry", "country"]].copy()
        meta.columns = ["_join_key", "sector_yf", "industry_yf", "country_yf"]

        df_out["_join_key"] = df_out["constituent_isin"].where(
            df_out["constituent_isin"] != "", df_out["constituent_ticker"]
        )
        df_out = df_out.merge(meta, on="_join_key", how="left").drop(columns=["_join_key"])

        # Fill only the rows that were still missing after file-sourced pass
        for col, yf_col in [("sector", "sector_yf"), ("country", "country_yf")]:
            if yf_col in df_out.columns:
                missing_mask = df_out[col].fillna("").str.strip() == ""
                df_out.loc[missing_mask, col] = df_out.loc[missing_mask, yf_col].fillna("")
                df_out.drop(columns=[yf_col], inplace=True, errors="ignore")
        df_out.drop(columns=["industry_yf"], inplace=True, errors="ignore")

    # Final cleanup
    df_out["sector"]  = df_out["sector"].replace({"": "Unknown", "nan": "Unknown"}).fillna("Unknown")
    df_out["country"] = df_out["country"].replace({"": "Unknown", "nan": "Unknown"}).fillna("Unknown")

    # Drop file-sourced helper columns — they've been merged into sector/country
    df_out.drop(columns=["sector_from_file", "country_from_file"], inplace=True, errors="ignore")

    return df_out


# ---------------------------------------------------------------------------
# 3a. Overlap analysis
# ---------------------------------------------------------------------------

def _make_overlap_key(row: pd.Series) -> str:
    """
    Build a single stable join key for one constituent row.
    Priority: ISIN > ticker > name (lower-cased).
    Only used for single-row contexts; use _make_overlap_keys_vectorised
    for whole DataFrames.
    """
    isin = str(row.get("constituent_isin", "") or "").strip()
    if isin and isin.upper() not in ("", "NAN", "NONE", "N/A"):
        return isin.upper()
    ticker = str(row.get("constituent_ticker", "") or "").strip()
    if ticker and ticker.upper() not in ("", "NAN", "NONE", "N/A"):
        return ticker.upper()
    return str(row.get("constituent_name", "") or "").strip().lower()


def _make_overlap_keys_vectorised(df: pd.DataFrame) -> pd.Series:
    """
    Vectorised key builder for the overlap engine.

    Priority chain per constituent row:
      1. Real ISIN from etf_holdings.isin  (best — globally unique)
      2. Ticker resolved to real ISIN via ticker_isin_map
         (fixes VHVG.L ticker-keyed vs MEUD.L ISIN-keyed overlap)
      3. Raw ticker  (upper-cased, for same-ticker ETF pairs like VHVG vs IUSA)
      4. Name        (lower-cased, last resort)

    The ticker_isin_map is loaded once per call from the DB — it's a small
    table (~1,000 rows max) so the overhead is negligible compared to the
    overlap computation itself.
    """
    _BAD = {"", "NAN", "NONE", "N/A"}

    def _clean_upper(col: str) -> pd.Series:
        s = df[col].fillna("").astype(str).str.strip().str.upper()
        return s.where(~s.isin(_BAD), "")

    isin   = _clean_upper("constituent_isin")
    ticker = _clean_upper("constituent_ticker")
    # Use normalised name (strips "Co/Ltd/Corp" suffixes) so that
    # "SAMSUNG ELECTRONICS CO" (KRWL, no ticker) matches
    # "Samsung Electronics Co Ltd" (VHVG, ticker=005930) at the name-fallback
    # level when no ISIN or ticker bridge is available.
    name   = df.get("constituent_name", pd.Series("", index=df.index)) \
               .fillna("").astype(str).apply(_normalise_name)

    # Load the ticker → real ISIN bridge from DB
    try:
        ticker_to_isin = hdb.get_ticker_isin_map()   # {BASE_TICKER: REAL_ISIN}
    except Exception:
        ticker_to_isin = {}

    # Resolve tickers to real ISINs where possible.
    # The map is keyed by BASE ticker (e.g. "005930") but constituent_ticker
    # may include an exchange suffix (e.g. "005930.KS").  Strip the suffix
    # before the map lookup so Korean / European stocks resolve correctly.
    # Example: KRWL has "005930.KS" and VHVG has ISIN "KR7005930003" —
    # without the strip, the lookup fails and overlap is missed.
    ticker_base = ticker.str.split(".").str[0]   # "005930.KS" → "005930"
    resolved_isin = ticker_base.map(ticker_to_isin).fillna("")
    # Also try the full ticker (handles cases where map key already has suffix)
    resolved_isin_full = ticker.map(ticker_to_isin).fillna("")
    resolved_isin = resolved_isin.where(resolved_isin != "", resolved_isin_full)

    # Layer priority: normalised-name → ticker → resolved_isin → explicit_isin
    # (higher priority layers overwrite lower ones)
    key = name.copy()
    key = key.where(ticker        == "", ticker)
    key = key.where(resolved_isin == "", resolved_isin)
    key = key.where(isin          == "", isin)

    # ── Name→canonical bridge ────────────────────────────────────────────
    # Problem: KRWL Samsung has no ticker → key = "samsung electronics" (norm name)
    #          VHVG Samsung has ticker "005930" → key = "005930"
    # These never match even though the stocks are identical.
    # Fix: build a map {normalised_name → canonical_key} from rows that already
    # have a ticker/ISIN key, then remap name-only rows to the canonical key.
    # This is a single vectorised pass — O(N) not O(N²).
    name_series   = name.copy()          # normalised name for every row
    is_name_key   = (key == name_series) # True where key fell back to name

    if is_name_key.any():
        # Build bridge from rows where key != name (i.e. has a real ticker/ISIN key)
        has_real_key = ~is_name_key
        if has_real_key.any():
            bridge = (
                pd.Series(key.values,  index=name_series.values, name="canonical")
                .loc[name_series[has_real_key].values]
            )
            # bridge index = normalised_name, values = canonical key
            # Convert to a plain dict for O(1) lookup
            bridge_dict: dict = {}
            for nm, ck in zip(name_series[has_real_key], key[has_real_key]):
                bridge_dict.setdefault(nm, ck)   # first ticker wins

            # Remap name-only rows
            remapped = name_series[is_name_key].map(bridge_dict).fillna("")
            key = key.copy()
            update_mask = is_name_key & (remapped != "")
            key[update_mask] = remapped[update_mask]

    return key


def compute_overlap_matrix(df_exploded: pd.DataFrame) -> pd.DataFrame:
    """
    Compute pairwise ETF overlap as a symmetric matrix.

    Overlap(A, B) = sum of min(weight_in_A, weight_in_B) for all shared
    constituents, where weights are normalised within each ETF to sum to 1.

    The join key priority is: ISIN > ticker > name (case-insensitive).
    Keys are built once for the entire DataFrame, then reused across all
    pair computations — O(N) key-building instead of O(N * pairs).

    Returns a square DataFrame (ETF tickers as both index and columns).
    Diagonal = 1.0 (self-overlap). Off-diagonal in [0, 1].
    """
    # Exclude opaque rows (ETFs with no holdings file — e.g. SGLN gold ETF).
    # These rows have has_holdings=False and carry no constituent data, so they
    # add nothing to overlap analysis and should not appear in the heatmap.
    df_for_overlap = df_exploded.copy()
    if "has_holdings" in df_for_overlap.columns:
        df_for_overlap = df_for_overlap[df_for_overlap["has_holdings"] == True].copy()

    etf_tickers = df_for_overlap["etf_ticker"].unique().tolist()
    if len(etf_tickers) < 2:
        return pd.DataFrame()

    # Build keys once for the whole DataFrame (vectorised)
    df_keyed = df_for_overlap.copy()
    df_keyed["_key"] = _make_overlap_keys_vectorised(df_keyed)

    etf_weights: dict[str, dict[str, float]] = {}
    for etf in etf_tickers:
        sub     = df_keyed[df_keyed["etf_ticker"] == etf]
        total_w = sub["etf_weight_pct"].sum()
        etf_weights[etf] = (
            sub.groupby("_key")["etf_weight_pct"]
            .sum()
            .div(total_w if total_w > 0 else 1.0)
            .to_dict()
        )

    matrix = pd.DataFrame(index=etf_tickers, columns=etf_tickers, dtype=float)
    for a in etf_tickers:
        for b in etf_tickers:
            if a == b:
                matrix.loc[a, b] = 1.0
            else:
                shared = set(etf_weights[a].keys()) & set(etf_weights[b].keys())
                matrix.loc[a, b] = round(
                    sum(min(etf_weights[a][k], etf_weights[b][k]) for k in shared), 4
                )
    return matrix


def compute_overlap_details(df_exploded: pd.DataFrame) -> pd.DataFrame:
    """
    For each pair of ETFs, return the shared constituents with their
    contribution to the overlap score. Used for the drill-down table.

    Keys are built once upfront (not per-pair) for O(N) instead of
    O(N * num_pairs) key construction.
    """
    # Exclude opaque rows (no holdings file) before computing overlap details
    df_exploded = df_exploded.copy()
    if "has_holdings" in df_exploded.columns:
        df_exploded = df_exploded[df_exploded["has_holdings"] == True].copy()

    etf_tickers = df_exploded["etf_ticker"].unique().tolist()
    if len(etf_tickers) < 2:
        return pd.DataFrame()

    # Build keys once for the entire DataFrame
    df_keyed = df_exploded.copy()
    df_keyed["_key"] = _make_overlap_keys_vectorised(df_keyed)

    # Pre-aggregate per ETF (sum duplicate keys, keep first name)
    etf_agg: dict[str, pd.DataFrame] = {}
    for etf in etf_tickers:
        sub = df_keyed[df_keyed["etf_ticker"] == etf]
        etf_agg[etf] = (
            sub.groupby("_key", as_index=False)
            .agg(constituent_name=("constituent_name", "first"),
                 etf_weight_pct  =("etf_weight_pct",   "sum"))
        )

    rows = []
    seen_pairs: set = set()

    for i, a in enumerate(etf_tickers):
        for b in etf_tickers[i + 1:]:
            pair_key = tuple(sorted([a, b]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            merged = etf_agg[a].merge(etf_agg[b], on="_key",
                                      suffixes=(f"_{a}", f"_{b}"))
            for _, row in merged.iterrows():
                w_a  = row[f"etf_weight_pct_{a}"]
                w_b  = row[f"etf_weight_pct_{b}"]
                name = row.get(f"constituent_name_{a}") or row.get(f"constituent_name_{b}", "")
                rows.append({
                    "ETF A":               a,
                    "ETF B":               b,
                    "Constituent":         name,
                    f"Weight in {a} (%)":  round(w_a, 4),
                    f"Weight in {b} (%)":  round(w_b, 4),
                    "Min Weight (overlap)":round(min(w_a, w_b), 4),
                })

    if not rows:
        return pd.DataFrame()

    return (
        pd.DataFrame(rows)
        .sort_values(["ETF A", "ETF B", "Min Weight (overlap)"],
                     ascending=[True, True, False])
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# 3b. Sector & geography analysis
# ---------------------------------------------------------------------------

def compute_sector_breakdown(df_enriched: pd.DataFrame) -> pd.DataFrame:
    """
    Returns a DataFrame of (sector, portfolio_weight_pct, effective_value_gbp)
    aggregated across all constituents, equity only.

    Opaque rows (has_holdings=False) — e.g. gold ETFs (SGLN), commodity ETFs, or
    any ticker where no holdings file has been uploaded — are excluded.  These rows
    carry no sector attribution and would otherwise inflate the "Unknown" bucket.
    """
    eq = df_enriched[df_enriched["asset_class"] == EQUITY_CLASS].copy()
    # Exclude opaque pass-through rows (the ETF itself when no holdings file exists)
    if "has_holdings" in eq.columns:
        eq = eq[eq["has_holdings"] == True].copy()
    if eq.empty:
        return pd.DataFrame()

    result = (
        eq.groupby("sector", as_index=False)
        .agg(
            portfolio_weight_pct=("portfolio_weight_pct", "sum"),
            effective_value_gbp =("effective_value_gbp",  "sum"),
        )
        .sort_values("portfolio_weight_pct", ascending=False)
        .reset_index(drop=True)
    )
    return result


def compute_geography_breakdown(df_enriched: pd.DataFrame) -> pd.DataFrame:
    """
    Returns (country, portfolio_weight_pct, effective_value_gbp) for equity only.

    Opaque rows (has_holdings=False) are excluded — same rationale as
    compute_sector_breakdown.
    """
    eq = df_enriched[df_enriched["asset_class"] == EQUITY_CLASS].copy()
    # Exclude opaque pass-through rows
    if "has_holdings" in eq.columns:
        eq = eq[eq["has_holdings"] == True].copy()
    if eq.empty:
        return pd.DataFrame()

    result = (
        eq.groupby("country", as_index=False)
        .agg(
            portfolio_weight_pct=("portfolio_weight_pct", "sum"),
            effective_value_gbp =("effective_value_gbp",  "sum"),
        )
        .sort_values("portfolio_weight_pct", ascending=False)
        .reset_index(drop=True)
    )
    return result


def compute_top_holdings(df_enriched: pd.DataFrame, top_n: int = 30) -> pd.DataFrame:
    """
    Aggregate effective portfolio weight per unique constituent (across all ETFs).
    Returns the top N constituents by portfolio weight.

    Key priority (same as overlap engine for consistency):
      1. Real ISIN              — globally unique, best
      2. Ticker resolved to ISIN via ticker_isin_map (base ticker, suffix-stripped)
      3. Raw ticker (upper)     — e.g. NVDA consolidates VHVG and IUSA rows
      4. Normalised name        — strips "Corp/Ltd/Co" so "NVIDIA Corp" == "NVIDIA CORP"

    Without step 3, NVIDIA appears twice (VHVG + IUSA both have ticker NVDA but
    different name capitalisation, and neither has an ISIN in the file).
    Without step 4, Samsung appears twice when KRWL has no ticker at all.
    """
    if df_enriched.empty:
        return pd.DataFrame()

    df = df_enriched.copy()

    _BAD = {"", "NAN", "NONE", "N/A"}

    isin   = df["constituent_isin"].fillna("").astype(str).str.strip().str.upper()
    isin   = isin.where(~isin.isin(_BAD), "")

    ticker = df["constituent_ticker"].fillna("").astype(str).str.strip().str.upper()
    ticker = ticker.where(~ticker.isin(_BAD), "")

    name   = df["constituent_name"].fillna("").astype(str).apply(_normalise_name)

    # Load ticker → ISIN bridge (same as overlap engine)
    try:
        ticker_to_isin = hdb.get_ticker_isin_map()
    except Exception:
        ticker_to_isin = {}

    # Resolve ticker to ISIN (strip exchange suffix first)
    ticker_base   = ticker.str.split(".").str[0]
    resolved_isin = ticker_base.map(ticker_to_isin).fillna("")
    resolved_isin_full = ticker.map(ticker_to_isin).fillna("")
    resolved_isin = resolved_isin.where(resolved_isin != "", resolved_isin_full)

    # Build canonical key: name → ticker → resolved_isin → explicit_isin
    key = name.copy()
    key = key.where(ticker        == "", ticker)
    key = key.where(resolved_isin == "", resolved_isin)
    key = key.where(isin          == "", isin)

    # Name→canonical bridge (same logic as overlap engine):
    # Rows with no ticker/ISIN fall back to normalised name, but another row
    # for the SAME company may have a ticker key.  Bridge them so they group.
    is_name_key = (key == name)
    if is_name_key.any():
        has_real_key = ~is_name_key
        if has_real_key.any():
            bridge_dict: dict = {}
            for nm, ck in zip(name[has_real_key], key[has_real_key]):
                bridge_dict.setdefault(nm, ck)
            remapped    = name[is_name_key].map(bridge_dict).fillna("")
            key         = key.copy()
            update_mask = is_name_key & (remapped != "")
            key[update_mask] = remapped[update_mask]

    df["_key"] = key

    has_sector  = "sector"  in df.columns
    has_country = "country" in df.columns

    agg_dict = {
        "constituent_name":     ("constituent_name",     "first"),
        "constituent_ticker":   ("constituent_ticker",   "first"),
        "portfolio_weight_pct": ("portfolio_weight_pct", "sum"),
        "effective_value_gbp":  ("effective_value_gbp",  "sum"),
        "held_via":             ("etf_ticker",           lambda x: ", ".join(sorted(set(x)))),
    }
    if has_sector:
        agg_dict["sector"]  = ("sector",  "first")
    if has_country:
        agg_dict["country"] = ("country", "first")

    agg = (
        df.groupby("_key", as_index=False)
        .agg(**agg_dict)
        .sort_values("portfolio_weight_pct", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
        .drop(columns=["_key"])
    )
    return agg


# ---------------------------------------------------------------------------
# 3c. Top-mover attribution
# ---------------------------------------------------------------------------

# SQLite table for persisting movers price-return data across restarts.
# Schema: (cache_date TEXT, period TEXT, ticker TEXT, price_return REAL,
#           PRIMARY KEY (cache_date, period, ticker))
# Written by _save_movers_price_cache / read by _load_movers_price_cache.
_MOVERS_DB_TTL_HOURS = 24   # persist to SQLite for up to 24h


def _movers_db_ensure_table() -> None:
    """Create the movers_price_cache table if it doesn't exist."""
    try:
        from backend.services.database import get_app_connection
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS movers_price_cache (
                        cache_date VARCHAR(255) NOT NULL,
                        period     VARCHAR(50) NOT NULL,
                        ticker     VARCHAR(255) NOT NULL,
                        price_return REAL,
                        fetched_at VARCHAR(255) NOT NULL,
                        PRIMARY KEY (cache_date, period, ticker)
                    )
                """)
            conn.commit()
    except Exception as e:
        import logging
        logging.error(f"Error ensuring movers_price_cache table: {e}")


def _save_movers_price_cache(returns: dict[str, float], period: str, cache_date: str) -> None:
    """Persist a {ticker: return} dict to movers_price_cache."""
    try:
        _movers_db_ensure_table()
        now = pd.Timestamp.utcnow().isoformat()
        rows = [(cache_date, period, t, r, now) for t, r in returns.items()]
        
        if not rows:
            return
            
        from backend.services.database import get_app_connection
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO movers_price_cache
                       (cache_date, period, ticker, price_return, fetched_at)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT(cache_date, period, ticker) DO UPDATE SET
                       price_return = EXCLUDED.price_return,
                       fetched_at = EXCLUDED.fetched_at""",
                    rows
                )
            conn.commit()
    except Exception as e:
        import logging
        logging.error(f"Error saving movers_price_cache: {e}")


def _load_movers_price_cache(period: str, cache_date: str) -> dict[str, float] | None:
    """
    Load persisted price returns for (period, cache_date).
    Returns None if no data is found or if the data is older than TTL.
    """
    try:
        from backend.services.database import get_app_connection
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT ticker, price_return, fetched_at FROM movers_price_cache
                       WHERE cache_date = %s AND period = %s""",
                    (cache_date, period)
                )
                rows = cur.fetchall()
            
            if not rows:
                return None
            
            df = pd.DataFrame(rows, columns=["ticker", "price_return", "fetched_at"])
            
            # Check TTL
            oldest_fetch = df["fetched_at"].min()
            oldest_dt = pd.to_datetime(oldest_fetch)
            if (pd.Timestamp.utcnow() - oldest_dt).total_seconds() > (_MOVERS_DB_TTL_HOURS * 3600):
                # Expired — delete and return None
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM movers_price_cache WHERE cache_date = %s AND period = %s",
                        (cache_date, period)
                    )
                conn.commit()
                return None
                
            return dict(zip(df["ticker"], df["price_return"]))
    except Exception as e:
        import logging
        logging.error(f"Error loading movers_price_cache: {e}")
        return None


def _resolve_movers_tickers(df_exploded: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich df_exploded with a resolved '_yf_ticker' column suitable for
    yf.download().  Re-uses the same 3-step logic as compute_top_movers:
      1. ISIN → yfinance ticker via constituent_metadata
      2. Name bridge for ticker-less rows
      3. normalise_ticker() for Yahoo Finance format
    Returns df_agg: one row per resolved ticker with aggregated value.
    """
    df_work = df_exploded.copy()

    # Step 1: ISIN → yfinance ticker from metadata
    isin_to_yf: dict[str, str] = {}
    try:
        all_isins = (df_work["constituent_isin"]
                     .dropna().astype(str).str.strip().unique().tolist())
        all_isins = [i for i in all_isins if i and i not in ("", "nan")]
        if all_isins:
            meta_df = hdb.get_cached_metadata(all_isins)
            if not meta_df.empty and "ticker" in meta_df.columns:
                for _, mr in meta_df.iterrows():
                    iv = str(mr.get("isin",   "") or "").strip()
                    tv = str(mr.get("ticker", "") or "").strip()
                    if iv and tv:
                        isin_to_yf[iv] = tv
    except Exception:
        pass

    # Fill from ISIN where ticker is missing
    has_no_ticker = df_work["constituent_ticker"].fillna("").str.strip() == ""
    has_isin      = df_work["constituent_isin"].fillna("").str.strip() != ""
    fill_mask = has_no_ticker & has_isin
    if fill_mask.any():
        df_work.loc[fill_mask, "constituent_ticker"] = (
            df_work.loc[fill_mask, "constituent_isin"]
            .map(isin_to_yf).fillna("")
        )

    # Step 2: name bridge
    has_no_ticker2 = df_work["constituent_ticker"].fillna("").str.strip() == ""
    if has_no_ticker2.any():
        _BAD = {"", "NAN", "NONE", "N/A"}
        norm_names  = df_work["constituent_name"].fillna("").astype(str).apply(_normalise_name)
        raw_tickers = df_work["constituent_ticker"].fillna("").astype(str).str.strip().str.upper()
        raw_tickers = raw_tickers.where(~raw_tickers.isin(_BAD), "")
        bridge: dict[str, str] = {}
        for nm, tk in zip(norm_names[raw_tickers != ""], raw_tickers[raw_tickers != ""]):
            bridge.setdefault(nm, tk)
        bridged     = norm_names[has_no_ticker2].map(bridge).fillna("")
        update_mask = has_no_ticker2 & (bridged != "")
        if update_mask.any():
            df_work.loc[update_mask, "constituent_ticker"] = bridged[update_mask]

    # Step 3: normalise to Yahoo Finance format
    df_work["constituent_ticker"] = (
        df_work["constituent_ticker"]
        .fillna("").astype(str).str.strip()
        .apply(lambda t: normalise_ticker(t) if t else "")
    )

    # Aggregate: one row per resolved ticker
    df_agg = (
        df_work
        .groupby("constituent_ticker", as_index=False)
        .agg(
            constituent_name   =("constituent_name",    "first"),
            etf_ticker         =("etf_ticker",          lambda x: ", ".join(sorted(set(x)))),
            effective_value_gbp=("effective_value_gbp", "sum"),
        )
    )
    df_agg = df_agg[df_agg["constituent_ticker"].str.strip() != ""].copy()
    return df_agg


def _clear_movers_db_cache(cache_date: str) -> None:
    """Delete today's movers price cache from SQLite so it is recomputed fresh."""
    try:
        _movers_db_ensure_table()
        from backend.services.database import get_app_connection
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM movers_price_cache WHERE cache_date = %s",
                    (cache_date,),
                )
        _MOVERS_PRICE_CACHE.clear()
    except Exception:
        pass


def fetch_movers_price_returns(
    df_exploded: pd.DataFrame,
    df_prices:   pd.DataFrame,
    allow_network: bool = True,
) -> dict[str, dict[str, float]]:
    """
    Download price history ONCE for all constituent tickers and return a dict
    of {period: {ticker: return}} for periods "1D", "1W".

    Strategy
    --------
    1. Check SQLite movers_price_cache — if today's data exists, return it
       immediately (survives Streamlit restarts, unlike the old in-process dict).
    2. Download a single 35-day window with yf.download() covering all tickers.
       Slice that window to derive both 1D and 1W returns — one network round-trip
       instead of two separate downloads per period.
    3. Persist results to SQLite so the next page-load is instant.

    The old in-process _MOVERS_PRICE_CACHE dict is kept as a sub-second
    guard against repeated Streamlit rerenders within the same second.
    """
    today      = pd.Timestamp.today().normalize()
    cache_date = str(today.date())

    # ── Fast path: in-process cache (sub-second, same Python process) ─────
    _process_key = (cache_date, "BOTH")
    cached_process = _MOVERS_PRICE_CACHE.get(_process_key)
    if cached_process is not None:
        cached_time, cached_data = cached_process
        age = (pd.Timestamp.now() - cached_time).total_seconds()
        if age < _MOVERS_CACHE_MAX_AGE_SECONDS:
            return cached_data

    # ── SQLite cache: survives restarts, valid all day ─────────────────────
    db_1d = _load_movers_price_cache("1D", cache_date)
    db_1w = _load_movers_price_cache("1W", cache_date)
    if db_1d and db_1w:
        result = {"1D": db_1d, "1W": db_1w}
        _MOVERS_PRICE_CACHE[_process_key] = (pd.Timestamp.now(), result)
        return result

    # ── Need to download — resolve tickers first ───────────────────────────
    df_agg = _resolve_movers_tickers(df_exploded)
    tickers_needed = df_agg["constituent_ticker"].tolist()

    price_returns_1d: dict[str, float] = {}
    price_returns_1w: dict[str, float] = {}

    # Use prices already in df_prices (free — no network call)
    start_1w = today - pd.Timedelta(days=12)   # 7d + 5d weekend buffer
    start_1d = today - pd.Timedelta(days=6)    # 1d + 5d weekend buffer

    tickers_missing = []
    if not df_prices.empty:
        for t in tickers_needed:
            if t in df_prices.columns:
                s = df_prices.loc[df_prices.index >= start_1w, t].dropna()
                if len(s) >= 2:
                    ret_1w = float(s.iloc[-1] / s.iloc[0]) - 1.0
                    # Sanity clamp: flag implausible returns for re-fetch
                    if abs(ret_1w) <= 5.0:
                        price_returns_1w[t] = ret_1w
                        s1d = s[s.index >= start_1d]
                        if len(s1d) >= 2:
                            ret_1d = float(s1d.iloc[-1] / s1d.iloc[0]) - 1.0
                            if abs(ret_1d) <= 5.0:
                                price_returns_1d[t] = ret_1d
                    else:
                        # Return looks like a unit-mismatch artefact — re-fetch
                        tickers_missing.append(t)
                else:
                    tickers_missing.append(t)
            else:
                tickers_missing.append(t)
    else:
        tickers_missing = tickers_needed

    # ── Single yf.download for everything still missing ────────────────────
    if tickers_missing and allow_network:
        # Download ONE 35-day window — enough for both 1W and 1D slicing
        start_dl = today - pd.Timedelta(days=35)
        norm_map = normalise_tickers(tickers_missing)
        yf_tickers = list(set(norm_map.values()))
        reverse_map: dict[str, list[str]] = {}
        for raw, yf_t in norm_map.items():
            reverse_map.setdefault(yf_t, []).append(raw)

        try:
            hist = yf.download(
                yf_tickers,
                start=start_dl,
                end=today + pd.Timedelta(days=1),
                auto_adjust=True,
                threads=True,     # parallel download — much faster for large lists
                progress=False,
            )
            if not hist.empty:
                close = (hist["Close"]
                         if isinstance(hist.columns, pd.MultiIndex)
                         else hist[["Close"]])
                if len(yf_tickers) == 1 and not isinstance(close.columns, pd.MultiIndex):
                    close.columns = yf_tickers

                for yf_t in yf_tickers:
                    if yf_t not in close.columns:
                        continue
                    s = close[yf_t].dropna()
                    if len(s) < 2:
                        continue

                    # ── Pence / GBP correction ────────────────────────────
                    # LSE tickers (ending in .L) are quoted in GBX (pence)
                    # by yfinance.  A median price > 500 almost certainly means
                    # pence — divide by 100 to convert to GBP.  This does NOT
                    # affect the return ratio (pence/pence = GBP/GBP), but it
                    # guards against a mixed-unit scenario where the first data
                    # point in the slice is from a day where yfinance returned
                    # a split-adjusted or ex-div price in a different unit.
                    # Dividing the whole series normalises it before slicing.
                    if yf_t.endswith(".L") and s.median() > 500:
                        s = s / 100.0

                    # 1W return
                    s1w = s[s.index >= start_1w]
                    if len(s1w) >= 2:
                        ret_1w = float(s1w.iloc[-1] / s1w.iloc[0]) - 1.0
                        # Sanity clamp: >500% weekly return is almost certainly
                        # a data artefact (unit mismatch, bad first data point)
                        if abs(ret_1w) <= 5.0:
                            for raw in reverse_map.get(yf_t, [yf_t]):
                                price_returns_1w[raw] = ret_1w
                    # 1D return — slice same history, no extra call
                    s1d = s[s.index >= start_1d]
                    if len(s1d) >= 2:
                        ret_1d = float(s1d.iloc[-1] / s1d.iloc[0]) - 1.0
                        if abs(ret_1d) <= 5.0:
                            for raw in reverse_map.get(yf_t, [yf_t]):
                                price_returns_1d[raw] = ret_1d
        except Exception:
            pass

    result = {"1D": price_returns_1d, "1W": price_returns_1w}

    # Persist to SQLite and in-process cache
    _save_movers_price_cache(price_returns_1d, "1D", cache_date)
    _save_movers_price_cache(price_returns_1w, "1W", cache_date)
    _MOVERS_PRICE_CACHE[_process_key] = (pd.Timestamp.now(), result)

    return result


def compute_top_movers(
    df_exploded: pd.DataFrame,
    df_prices:   pd.DataFrame,
    period: str = "1W",
    _price_returns: dict[str, float] | None = None,
) -> pd.DataFrame:
    """
    Compute P&L contribution per constituent for the selected period.

    contribution_gbp(i) = effective_value_gbp(i) × price_return(i, period)

    Pass _price_returns to avoid re-downloading when computing both 1D and 1W
    in the same orchestrator call (see run_lookahead_analysis).
    """
    if df_exploded.empty:
        return pd.DataFrame()

    df_agg       = _resolve_movers_tickers(df_exploded)
    price_returns = _price_returns or {}

    # ── Build result ───────────────────────────────────────────────────────
    rows = []
    for _, row in df_agg.iterrows():
        t   = row["constituent_ticker"]
        ret = price_returns.get(t, np.nan)
        val = row["effective_value_gbp"]
        contribution = val * ret if pd.notna(ret) else np.nan
        rows.append({
            "Constituent":          row["constituent_name"],
            "Ticker":               t,
            "Held via":             row["etf_ticker"],
            "Effective Value (Local)":  round(val, 2),
            "Price Return (%)":     round(ret * 100, 2) if pd.notna(ret) else None,
            "P&L Contribution (Local)": round(contribution, 2) if pd.notna(contribution) else None,
        })

    df_result = pd.DataFrame(rows)
    if df_result.empty:
        return df_result

    df_result["_abs"] = pd.to_numeric(df_result["P&L Contribution (Local)"], errors="coerce").abs()
    return (
        df_result
        .sort_values("_abs", ascending=False, na_position="last")
        .drop(columns=["_abs"])
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# 3d. Unknown metadata repair — yfinance retry + Gemini fallback
# ---------------------------------------------------------------------------

# Gemini prompt template for sector/country resolution
_GEMINI_METADATA_PROMPT = """You are a financial data assistant. For each company below, provide the GICS sector and country of incorporation/headquarters. Return ONLY a JSON array, no explanation, no markdown fences.

Companies:
{companies}

Return format (array, one object per company):
[
  {{"name": "company name as given", "sector": "GICS sector name", "country": "country name"}},
  ...
]

Valid GICS sectors: Technology, Financial Services, Healthcare, Consumer Cyclical, Consumer Defensive, Industrials, Communication Services, Energy, Basic Materials, Real Estate, Utilities.
If you cannot determine a field with confidence, use null."""


def repair_unknown_metadata(api_key: str = "", _use_st: bool = True) -> dict:
    """
    Find all constituent_metadata rows with null sector/country and attempt
    to repair them using two strategies in sequence:

    Pass 1 — yfinance retry with normalised ticker
        Many nulls exist because the original fetch used a raw provider ticker
        (e.g. "BRKB", "BA.", "RHM") instead of the Yahoo Finance equivalent
        ("BRK-B", "BA.L", "RHM.DE").  normalise_ticker() fixes these.

    Pass 2 — Gemini AI fallback (requires api_key)
        For anything yfinance still cannot resolve (no-sector stub, Korean
        stocks without exchange-listed data, etc.), batch the names to Gemini
        and ask it to fill in GICS sector + country.

    Returns a dict with repair statistics:
        {"yf_fixed": int, "gemini_fixed": int, "still_unknown": int}
    """
    try:
        import streamlit as st
        if not _use_st:
            raise ImportError
    except ImportError:
        _use_st = False

    def _info(msg):
        print(msg.encode('ascii', 'ignore').decode('ascii'))

    # ── Gather all null-sector/country entries ──────────────────────────
    from backend.services.database import get_app_connection
    with get_app_connection() as conn:
        null_rows = pd.read_sql_query(
            """SELECT isin, ticker, name
               FROM constituent_metadata
               WHERE (sector IS NULL OR sector = '' OR country IS NULL OR country = '')
               AND isin NOT IN (
                   SELECT DISTINCT etf_ticker FROM staleness_registry
                   WHERE COALESCE(ignore_look_through, 0) = 1
               )""",
            conn
        )

    if null_rows.empty:
        _info("✅ No Unknown metadata to repair.")
        return {"yf_fixed": 0, "gemini_fixed": 0, "still_unknown": 0}

    total = len(null_rows)
    _info(f"🔍 Found {total} constituents with missing sector/country. Attempting repair...")

    yf_fixed    = 0
    still_nulls: list[dict] = []   # feed to Gemini

    # ── Pass 1: yfinance with normalised tickers ─────────────────────────
    progress = None

    for idx, row in null_rows.iterrows():
        raw_symbol  = str(row["isin"]    or row["ticker"] or "").strip()
        if not raw_symbol:
            still_nulls.append({"name": str(row["name"] or ""), "isin": raw_symbol})
            continue

        yf_symbol = normalise_ticker(raw_symbol)

        if progress:
            progress.progress((idx + 1) / total,
                              text=f"yfinance: {yf_symbol} ({idx+1}/{total})")

        try:
            info = yf.Ticker(yf_symbol).info
            sector  = info.get("sector",  "") or ""
            country = info.get("country", "") or ""

            if sector or country:
                # Update the existing record in-place
                from backend.services.database import get_app_connection
                with get_app_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """UPDATE constituent_metadata
                               SET sector=%s, country=%s, ticker=%s, fetched_at=%s
                               WHERE isin=%s""",
                            (sector or None, country or None, yf_symbol,
                             pd.Timestamp.utcnow().isoformat(), raw_symbol)
                        )
                yf_fixed += 1
            else:
                still_nulls.append({
                    "name":  str(row["name"] or raw_symbol),
                    "isin":  raw_symbol,
                    "ticker": yf_symbol,
                })
        except Exception:
            still_nulls.append({
                "name":  str(row["name"] or raw_symbol),
                "isin":  raw_symbol,
                "ticker": yf_symbol,
            })

        time.sleep(_INTER_CALL_SLEEP)

    if progress:
        progress.progress(1.0, text=f"yfinance pass done. Fixed {yf_fixed}/{total}.")

    _info(f"  yfinance fixed {yf_fixed} of {total}. {len(still_nulls)} still unknown.")

    gemini_fixed = 0

    # ── Pass 2: Gemini fallback ───────────────────────────────────────────
    if still_nulls and api_key:
        try:
            import json, re as _re
            model = gemini_util.get_best_gemini_model(api_key)
            if model:
                BATCH = 40   # keep prompts short

                batches = [still_nulls[i:i+BATCH]
                           for i in range(0, len(still_nulls), BATCH)]

                gem_progress = None

                for b_idx, batch in enumerate(batches):
                    if gem_progress:
                        gem_progress.progress(b_idx / len(batches),
                                              text=f"Gemini batch {b_idx+1}/{len(batches)}")

                    companies_str = "\n".join(
                        f"{i+1}. {item['name']} (ticker: {item.get('ticker','?')})"
                        for i, item in enumerate(batch)
                    )
                    prompt = _GEMINI_METADATA_PROMPT.format(companies=companies_str)

                    try:
                        resp = model.generate_content(prompt)
                        raw  = resp.text.strip()
                        raw  = _re.sub(r"```json|```", "", raw).strip()
                        results_list = json.loads(raw)

                        if isinstance(results_list, list):
                            for i, item in enumerate(batch):
                                if i >= len(results_list):
                                    break
                                gem_row = results_list[i]
                                sector  = (gem_row.get("sector")  or "").strip()
                                country = (gem_row.get("country") or "").strip()

                                # Only use Gemini values that look real
                                if sector and sector.lower() not in ("null", "none", "unknown", ""):
                                    from backend.services.database import get_app_connection
                                    with get_app_connection() as conn:
                                        with conn.cursor() as cur:
                                            cur.execute(
                                                """UPDATE constituent_metadata
                                                   SET sector=%s, country=%s, fetched_at=%s
                                                   WHERE isin=%s""",
                                                (sector,
                                                 country if country.lower() not in ("null","none","") else None,
                                                 pd.Timestamp.utcnow().isoformat(),
                                                 item["isin"])
                                            )
                                    gemini_fixed += 1

                    except Exception:
                        pass  # batch failed — continue with next batch

                    time.sleep(1.0)   # be polite to Gemini API

                if gem_progress:
                    gem_progress.progress(1.0, text=f"Gemini fixed {gemini_fixed}.")

        except ImportError:
            _info("  Gemini not available (google-generativeai not installed).")

    # ── Pass 3: Mark remaining as Unknown to prevent infinite retries ───────
    still_unknown_count = len(still_nulls) - gemini_fixed
    if still_unknown_count > 0:
        from backend.services.database import get_app_connection
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                for item in still_nulls:
                    cur.execute(
                        """UPDATE constituent_metadata
                           SET sector='Unknown', country='Unknown', fetched_at=%s
                           WHERE isin=%s AND (sector IS NULL OR sector = '')""",
                        (pd.Timestamp.utcnow().isoformat(), item["isin"])
                    )
        _info(f"  Marked {still_unknown_count} items as 'Unknown' to prevent endless retries.")

    # Invalidate the lookahead cache so enriched data is re-computed
    if yf_fixed + gemini_fixed > 0:
        hdb.invalidate_lookahead_cache()
        _info(f"✅ Repaired {yf_fixed + gemini_fixed} entries. Cache invalidated — run Refresh Analysis to apply.")

    return {"yf_fixed": yf_fixed, "gemini_fixed": gemini_fixed, "still_unknown": still_unknown_count}


# ---------------------------------------------------------------------------
# 4. Orchestrator — full refresh with caching
# ---------------------------------------------------------------------------

def run_lookahead_analysis(
    positions: dict,
    df_prices: pd.DataFrame,
    account: str,
    force_refresh: bool = False,
    api_key: str = "",
) -> dict:
    """
    Main entry point called by the Streamlit UI.

    If a valid cache exists and force_refresh=False, returns the cached result
    immediately. Otherwise runs the full pipeline and saves to cache.

    Returns a dict with keys:
        df_exploded       — raw look-through rows
        df_enriched       — look-through + sector/geo metadata
        df_overlap_matrix — pairwise overlap heatmap
        df_overlap_detail — constituent-level overlap drill-down
        df_sector         — sector breakdown
        df_geography      — geography breakdown
        df_top_holdings   — top 30 consolidated positions
        df_movers_1d      — P&L attribution (1-day)
        df_movers_1w      — P&L attribution (1-week)
        computed_at       — ISO timestamp string
        coverage_warnings — list of warning dicts from staleness_registry
    """
    # ── Check cache ────────────────────────────────────────────────────────
    if force_refresh:
        # Wipe the movers price cache so stale/bad returns (e.g. pence/GBP
        # unit mismatch from a prior run) are recomputed cleanly.
        _clear_movers_db_cache(str(pd.Timestamp.today().normalize().date()))

    if not force_refresh:
        df_cached, computed_at = hdb.get_lookahead_cache(account)
        if not df_cached.empty and computed_at:
            # Movers need fresh prices but are expensive — only recompute once
            # per hour using the in-process _MOVERS_PRICE_CACHE mechanism.
            # The first call after an hour triggers one batched yf.download;
            # subsequent Streamlit rerenders within that hour are free.

            # Strip any ETFs that have been flagged as ignored SINCE the cache
            # was built (e.g. ERNS / IBCI / SGLN toggled off).  This means
            # ignore-flag changes take effect immediately without a full refresh.
            _active_in_db = set(hdb.get_active_etf_tickers_in_db())
            _ignored_now  = set(hdb.get_all_etf_tickers_in_db()) - _active_in_db
            if _ignored_now and "etf_ticker" in df_cached.columns:
                df_cached = df_cached[~df_cached["etf_ticker"].isin(_ignored_now)].copy()

            df_enriched = df_cached
            out = {
                "df_exploded":       df_cached,
                "df_enriched":       df_enriched,
                "df_overlap_matrix": compute_overlap_matrix(df_cached),
                "df_overlap_detail": compute_overlap_details(df_cached),
                "df_sector":         compute_sector_breakdown(df_enriched),
                "df_geography":      compute_geography_breakdown(df_enriched),
                "df_top_holdings":   compute_top_holdings(df_enriched),
                "computed_at":       computed_at,
                "coverage_warnings": _get_warnings(list(positions.keys())),
                "from_cache":        True,
            }
            # Download prices once for both periods — single yf.download call,
            # results persisted to SQLite so next load is instant
            _pr = fetch_movers_price_returns(df_cached, df_prices, allow_network=force_refresh)
            out["df_movers_1d"] = compute_top_movers(df_cached, df_prices, "1D", _price_returns=_pr.get("1D", {}))
            out["df_movers_1w"] = compute_top_movers(df_cached, df_prices, "1W", _price_returns=_pr.get("1W", {}))
            return out

    # ── Full pipeline ──────────────────────────────────────────────────────
    # Use get_active (respects ignore_look_through flag) so that Fixed Income /
    # Gold / Commodity ETFs are excluded from exploding, overlap and sector/geo.
    etf_tickers_in_db = hdb.get_active_etf_tickers_in_db()
    # Build the set of ignored tickers so we can strip them from positions too
    ignored_tickers = set(hdb.get_all_etf_tickers_in_db()) - set(etf_tickers_in_db)

    # Remove ignored tickers from positions so they never appear as opaque rows
    positions_filtered = {t: s for t, s in positions.items() if t not in ignored_tickers}

    df_exploded = build_exploded_portfolio(
        positions=positions_filtered,
        df_prices=df_prices,
        etf_tickers_with_holdings=etf_tickers_in_db,
    )

    if df_exploded.empty:
        return _empty_result(positions)

    df_enriched = enrich_with_metadata(df_exploded, allow_network=force_refresh)

    # Persist enriched result as the new cache
    # NOTE: repair_unknown_metadata is NOT called here — it runs via the
    # dedicated sidebar button only, to avoid adding ~90s to every refresh.
    hdb.save_lookahead_cache(df_enriched, account)
    computed_at = pd.Timestamp.utcnow().isoformat()

    out = {
        "df_exploded":       df_exploded,
        "df_enriched":       df_enriched,
        "df_overlap_matrix": compute_overlap_matrix(df_exploded),
        "df_overlap_detail": compute_overlap_details(df_exploded),
        "df_sector":         compute_sector_breakdown(df_enriched),
        "df_geography":      compute_geography_breakdown(df_enriched),
        "df_top_holdings":   compute_top_holdings(df_enriched),
        "computed_at":       computed_at,
        "coverage_warnings": _get_warnings(list(positions.keys())),
        "from_cache":        False,
    }
    # Download prices once, slice for both periods — persisted to SQLite
    _pr = fetch_movers_price_returns(df_exploded, df_prices, allow_network=force_refresh)
    out["df_movers_1d"] = compute_top_movers(df_exploded, df_prices, "1D", _price_returns=_pr.get("1D", {}))
    out["df_movers_1w"] = compute_top_movers(df_exploded, df_prices, "1W", _price_returns=_pr.get("1W", {}))
    return out


def _get_warnings(portfolio_tickers: list[str]) -> list[dict]:
    # Only warn about tickers that could plausibly be ETFs
    # (heuristic: exclude tickers that appear in the holdings as constituents)
    etf_tickers_in_db = set(hdb.get_all_etf_tickers_in_db())
    # For now, warn about any portfolio ticker that isn't in the DB
    # The UI will let the user suppress warnings for known non-ETF tickers
    return hdb.get_staleness_warnings(portfolio_tickers)


def _empty_result(positions: dict) -> dict:
    return {
        "df_exploded":       pd.DataFrame(),
        "df_enriched":       pd.DataFrame(),
        "df_overlap_matrix": pd.DataFrame(),
        "df_overlap_detail": pd.DataFrame(),
        "df_sector":         pd.DataFrame(),
        "df_geography":      pd.DataFrame(),
        "df_top_holdings":   pd.DataFrame(),
        "df_movers_1d":      pd.DataFrame(),
        "df_movers_1w":      pd.DataFrame(),
        "computed_at":       None,
        "coverage_warnings": _get_warnings(list(positions.keys())),
        "from_cache":        False,
    }
