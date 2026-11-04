import json
import re
from backend.services import gemini_util
import yfinance as yf

try:
    import streamlit as st
except ImportError:
    st = None

def _show_info(msg: str):
    import logging
    logging.getLogger("ticker_service").info(msg)
    if st is not None:
        try:
            from streamlit.runtime.scriptrunner import get_script_run_ctx
            if get_script_run_ctx() is not None:
                st.info(msg)
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Global Ticker Validation & Price Delta Sanity Checking Utilities
# ---------------------------------------------------------------------------

def is_valid_yahoo_ticker(ticker: str) -> bool:
    """Returns True if the ticker exists and is queryable on Yahoo Finance."""
    if not ticker or not isinstance(ticker, str):
        return False
    ticker = ticker.strip().upper()
    try:
        t = yf.Ticker(ticker)
        # fast_info is super lightweight and fast. If it raises or doesn't have exchange/price, it is likely invalid.
        info = t.fast_info
        if info and getattr(info, 'last_price', None) is not None:
            return True
        # If fast_info is blank, try history for 1 day
        hist = t.history(period="1d")
        if not hist.empty:
            return True
    except Exception:
        pass
    return False


def verify_price_tolerance(ticker: str, trade_date_str: str, trade_price: float, tolerance: float = 0.10) -> dict:
    """
    Fetches the close/adjusted price on trade_date_str (YYYY-MM-DD) from yfinance.
    Handles currency conversions if price is in pence (GBX) vs pounds (GBP).
    Returns:
      {
        "is_within_tolerance": bool,
        "expected_price": float,
        "actual_price": float,
        "warning_msg": str or None
      }
    """
    if not ticker or not isinstance(ticker, str) or not trade_price:
        return {"is_within_tolerance": True, "expected_price": 0.0, "actual_price": trade_price, "warning_msg": None}
    
    ticker = ticker.strip().upper()
    try:
        from datetime import datetime
        dt = datetime.strptime(trade_date_str, "%Y-%m-%d")
    except Exception:
        # Invalid date format or date is not fully resolved yet, skip warning
        return {"is_within_tolerance": True, "expected_price": 0.0, "actual_price": trade_price, "warning_msg": None}

    try:
        t = yf.Ticker(ticker)
        
        # Download historical data around the trade date to ensure we capture weekends/holidays (closest date)
        import pandas as pd
        start_dt = (dt - pd.Timedelta(days=4)).strftime("%Y-%m-%d")
        end_dt = (dt + pd.Timedelta(days=4)).strftime("%Y-%m-%d")
        
        hist = t.history(start=start_dt, end=end_dt)
        if hist.empty:
            return {"is_within_tolerance": True, "expected_price": 0.0, "actual_price": trade_price, "warning_msg": None}
            
        # Get the row closest to our target date
        hist.index = hist.index.tz_localize(None)
        closest_idx = (hist.index.to_series() - dt).abs().argmin()
        actual_row = hist.iloc[closest_idx]
        actual_price = float(actual_row["Close"])
        
        # Suffix and currency mapping adjustments
        ratio = trade_price / actual_price
        
        # Pence/Pound mismatch correction
        normalized_actual = actual_price
        if 80.0 < ratio < 120.0: # Trade in pence, Yahoo in pounds (e.g. Trade: 4500, Yahoo: 45)
            normalized_actual = actual_price * 100.0
        elif 0.008 < ratio < 0.012: # Trade in pounds, Yahoo in pence (e.g. Trade: 45, Yahoo: 4500)
            normalized_actual = actual_price / 100.0
            
        abs_diff = abs(trade_price - normalized_actual)
        pct_diff = abs_diff / normalized_actual if normalized_actual > 0 else 0
        
        is_ok = pct_diff <= tolerance
        
        warning_msg = None
        if not is_ok:
            warning_msg = (
                f"⚠️ **Price Discrepancy**: Your transaction price for **{ticker}** on {trade_date_str} was **{trade_price:,.4f}**, "
                f"but Yahoo Finance reported a price of **{normalized_actual:,.4f}** (variance {pct_diff * 100:.1f}%). "
                f"Please verify if this is off by a factor of 100 (GBP vs. GBX pence/pound scaling)."
            )
            
        return {
            "is_within_tolerance": is_ok,
            "expected_price": normalized_actual,
            "actual_price": actual_price,
            "warning_msg": warning_msg
        }
    except Exception as e:
        return {"is_within_tolerance": True, "expected_price": 0.0, "actual_price": trade_price, "warning_msg": f"Price verification failed: {e}"}

# ---------------------------------------------------------------------------
# OpenFIGI ticker resolution — free Bloomberg database, no API key needed
# ---------------------------------------------------------------------------

def _openfigi_lookup(queries: list[dict]) -> list[dict | None]:
    """
    POST identifier queries to the OpenFIGI v3 mapping endpoint.
    Returns a parallel list: first matching result per query, or None.
    Rate limit: 25 req/min without a key — plenty for our use.
    Includes an exponential backoff retry loop for 429 rate limits or network issues.
    """
    import urllib.request as _urlreq
    import urllib.error as _urlerr
    import time
    
    payload = json.dumps(queries).encode()
    req = _urlreq.Request(
        "https://api.openfigi.com/v3/mapping",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    
    max_retries = 1
    base_backoff = 1.0  # seconds
    
    for attempt in range(max_retries + 1):
        try:
            with _urlreq.urlopen(req, timeout=3) as resp:
                results = json.loads(resp.read())
            return [item.get("data", [None])[0] for item in results]
        except _urlerr.HTTPError as e:
            if e.code in (429, 502, 503, 504) and attempt < max_retries:
                time.sleep(base_backoff)
                continue
            break
        except Exception:
            if attempt < max_retries:
                time.sleep(base_backoff)
                continue
            break
            
    return [None] * len(queries)


def _figi_to_yahoo(result: dict | None) -> str:
    """Convert an OpenFIGI result dict to a Yahoo Finance ticker string."""
    if not result:
        return ""
    ticker = result.get("ticker", "")
    exch   = result.get("exchCode", "")
    if not ticker:
        return ""
    
    # Mapping Bloomberg/OpenFIGI exchCodes to Yahoo Finance suffixes
    EXCH_MAP = {
        "LN": ".L",   # London
        "IM": ".MI",  # Milan (Borsa Italiana)
        "GY": ".DE",  # Xetra (Germany)
        "GR": ".DE",  # Frankfurt (Germany)
        "FP": ".PA",  # Euronext Paris
        "NA": ".AS",  # Euronext Amsterdam
        "BB": ".BR",  # Euronext Brussels
        "PL": ".LS",  # Euronext Lisbon
        "SS": ".ST",  # Stockholm
        "NO": ".OL",  # Oslo
        "SW": ".SW",  # SIX Swiss
    }
    
    if exch in EXCH_MAP:
        return f"{ticker}{EXCH_MAP[exch]}"
    if exch in ("US", "UN", "UW", "UA"):
        return ticker
    return ""


def ai_fill_tickers(api_key, missing_assets: list[str], isin_map: dict = None, sedol_map: dict = None, base_currency: str = "GBP", ticker_map: dict = None, venue_map: dict = None, raw_ticker_map: dict = None) -> dict[str, str]:
    """
    Resolve Yahoo Finance tickers prioritizing consistency, SEDOL/ISIN OpenFIGI,
    direct Yahoo Finance validation with venue/currency hints, and Gemini Flash fallback.
    """
    if not missing_assets:
        return {}
    
    ticker_map = ticker_map or {}
    isin_map  = isin_map  or {}
    sedol_map = sedol_map or {}
    venue_map = venue_map or {}
    raw_ticker_map = raw_ticker_map or {}
    resolved: dict[str, str] = {}

    # ── Pass 0: Check existing Ticker_Map for consistency ───────────────────
    still_missing = []
    for name in missing_assets:
        if name in ticker_map and ticker_map[name]:
            resolved[name] = ticker_map[name]
        else:
            still_missing.append(name)
    
    if not still_missing:
        return resolved
    
    # Update missing_assets for remaining passes
    missing_assets = still_missing
    
    # ── Auto-detect ISIN/SEDOL format in asset names ────────────────────────
    for name in missing_assets:
        clean_name = str(name).strip().upper()
        # ISIN: 12 chars, alphanumeric
        if len(clean_name) == 12 and clean_name.isalnum() and name not in isin_map:
            isin_map[name] = clean_name
        # SEDOL: 7 chars, alphanumeric
        elif len(clean_name) == 7 and clean_name.isalnum() and name not in sedol_map:
            sedol_map[name] = clean_name

    # ── Pass 1: SEDOL lookup (LSE primary) ──────────────────────────────────
    sedol_assets = [n for n in missing_assets if sedol_map.get(n)]
    if sedol_assets:
        queries = [{"idType": "ID_SEDOL", "idValue": sedol_map[n]} for n in sedol_assets]
        for name, result in zip(sedol_assets, _openfigi_lookup(queries)):
            ticker = _figi_to_yahoo(result)
            if ticker:
                resolved[name] = ticker

    # ── Pass 2: ISIN lookup (Intelligent Exchange Prioritization) ───────────
    isin_assets = [n for n in missing_assets if isin_map.get(n) and n not in resolved]
    if isin_assets:
        candidates = ["IM", "GY", "FP", "NA", "LN"]
        queries = []
        for n in isin_assets:
            for ex in candidates:
                queries.append({"idType": "ID_ISIN", "idValue": isin_map[n], "exchCode": ex})
        
        lookup_results = _openfigi_lookup(queries)
        
        if base_currency == "EUR":
            priority = {"IM": 100, "GY": 90, "FP": 80, "NA": 70, "LN": 0}
        else:
            priority = {"LN": 100, "IM": 10, "GY": 10, "FP": 10, "NA": 10}
            
        res_idx = 0
        for name in isin_assets:
            best_ticker = None
            best_score  = -1
            
            for ex in candidates:
                result = lookup_results[res_idx]
                ticker = _figi_to_yahoo(result)
                score  = priority.get(ex, 0)
                
                if ticker and score > best_score:
                    best_ticker = ticker
                    best_score  = score
                res_idx += 1
                
            if best_ticker:
                resolved[name] = best_ticker

    # ── Pass 3 [NEW]: Direct Ticker Suffix Mapping & Validation ─────────────
    direct_assets = [n for n in missing_assets if n not in resolved and raw_ticker_map.get(n)]
    for name in direct_assets:
        raw_tick = str(raw_ticker_map[name]).strip().upper()
        venue = str(venue_map.get(name, "")).strip().upper()
        
        # Standardize Exchange/Venue Suffix guessing
        suffix = ""
        if "LONDON" in venue or "LSE" in venue or base_currency == "GBP":
            suffix = ".L"
        elif "BORSA" in venue or "MILAN" in venue or ("ITAL" in venue and base_currency == "EUR"):
            suffix = ".MI"
        elif "XETRA" in venue or "GY" in venue or "FRANKFURT" in venue or ("GERM" in venue and base_currency == "EUR"):
            suffix = ".DE"
            
        candidate = f"{raw_tick}{suffix}" if suffix else raw_tick
        
        if is_valid_yahoo_ticker(candidate):
            resolved[name] = candidate
            _show_info(f"⚡ Direct Validation: '{name}' resolved instantly to '{candidate}'")
            
    if resolved:
        _show_info("📡 Tickers resolved: " + ", ".join(f"{k} → {v}" for k, v in resolved.items()))

    # ── Pass 4: Gemini Flash fallback with enriched context hints ───────────
    unresolved = [n for n in missing_assets if not resolved.get(n)]
    if unresolved and api_key:
        try:
            model = gemini_util.get_best_gemini_model(api_key)
            lines = []
            for n in unresolved:
                parts = [f"Name: {n}"]
                if sedol_map.get(n): parts.append(f"SEDOL: {sedol_map[n]}")
                if isin_map.get(n):  parts.append(f"ISIN: {isin_map[n]}")
                if raw_ticker_map.get(n): parts.append(f"Broker Ticker Hint: {raw_ticker_map[n]}")
                if venue_map.get(n): parts.append(f"Exchange Venue: {venue_map[n]}")
                lines.append("- " + " | ".join(parts))
            
            if base_currency == "EUR":
                target_instr = "IMPORTANT: THE ACCOUNT IS EUR-DENOMINATED. NEVER return a London (.L) ticker. Prefer Milan (.MI) for Borsa Italiana, Xetra (.DE) for Germany, or Paris (.PA) for France."
            else:
                target_instr = "LSE tickers end in '.L'. Prefer .L (London) for UK/GBP accounts."

            prompt = (
                f"Find the Yahoo Finance ticker for each asset below. {target_instr}\n\n"
                f"ASSETS:\n" + "\n".join(lines) +
                f"\n\nReturn ONLY a JSON object: {{\"ASSET NAME\": \"TICK.SUFFIX\"}}"
            )
            ai_raw = json.loads(re.sub(r'```json\s*|\s*```', '', model.generate_content(prompt).text).strip())
                
            for k, v in ai_raw.items():
                if v:
                    if base_currency == "EUR" and str(v).upper().endswith(".L"):
                        continue
                    resolved[k] = v
        except Exception:
            pass
    
    if base_currency == "EUR":
        resolved = {k: v for k, v in resolved.items() if not str(v).upper().endswith(".L")}
        
    return resolved
