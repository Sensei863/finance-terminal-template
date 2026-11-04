import sys
import os
import math
import pandas as pd
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from backend.services import screener
from backend.services import storage
from backend.services import currency_utils

router = APIRouter(prefix="/api/screener", tags=["screener"])

class AIAnalysisRequest(BaseModel):
    ticker: str
    info: dict
    metrics: dict

def clean_nan(val):
    if pd.isna(val) or val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    return val

@router.get("/tickers")
def get_tickers(account: str = "Consolidated"):
    try:
        held_tickers = sorted(list(set(storage.get_currently_held_tickers(account))))
        exited_tickers_raw = screener.get_exited_tickers_last_12m(account)
        exited_tickers = sorted([t for t in exited_tickers_raw if t not in held_tickers])
        watchlist_items = storage.get_watchlist_tickers(active_only=True)
        watchlist_tickers = sorted([w["ticker"] for w in watchlist_items if w["ticker"] not in held_tickers and w["ticker"] not in exited_tickers])
        return {
            "current": held_tickers,
            "recent_exits": exited_tickers,
            "watchlist": watchlist_tickers,
            "watchlist_details": watchlist_items
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/data")
def get_screener_data(ticker: str, benchmark: str = "IUSA.L", account: str = "Consolidated"):
    try:
        raw_data, info_data = screener.fetch_screener_data(tuple([ticker]), benchmark)
        if raw_data.empty:
            raise HTTPException(status_code=404, detail="No data found from yfinance")

        def get_close(symbol):
            if isinstance(raw_data.columns, pd.MultiIndex):
                if symbol in raw_data.columns.levels[0]:
                    return raw_data[symbol]['Close']
            return pd.Series(dtype=float)

        t_close = get_close(ticker)
        if t_close.empty:
            raise HTTPException(status_code=404, detail="No close price data for ticker")

        info = dict(info_data.get(ticker, {}))

        # Normalize index to date-only timezone-naive to avoid alignment issues during merge/reindex
        t_close.index = pd.to_datetime(t_close.index).normalize()
        if hasattr(t_close.index, "tz") and t_close.index.tz is not None:
            t_close.index = t_close.index.tz_localize(None)

        # Get account base currency
        from backend.services import data_handler
        registry = data_handler.get_account_registry()
        acct_ccy = data_handler.get_account_base_currency(account, registry)

        quote_ccy = info.get('currency', 'USD')
        if quote_ccy in ('GBp', 'GBX'):
            quote_ccy = 'GBX'
        else:
            quote_ccy = str(quote_ccy).upper().strip()

        # Get portfolio trades and dividends
        df_trades, df_dividends = screener.get_ticker_activity(ticker, account=account, cached_info=info)

        # Apply FX translation to GBP if base currency is GBP and asset is listed in USD/EUR
        if acct_ccy == 'GBP' and quote_ccy == 'USD':
            start_date = t_close.index.min()
            gbpusd = screener.get_cached_fx_close("GBPUSD=X", start_date)
            if not gbpusd.empty:
                fx = gbpusd.reindex(t_close.index).ffill().bfill()
                t_close = t_close / fx
                info['currency'] = 'GBP'
                
                # Also convert dividends to GBP
                if not df_dividends.empty:
                    df_dividends = df_dividends.copy()
                    df_dividends.index = pd.to_datetime(df_dividends.index).normalize()
                    if hasattr(df_dividends.index, "tz") and df_dividends.index.tz is not None:
                        df_dividends.index = df_dividends.index.tz_localize(None)
                    div_start = df_dividends.index.min()
                    gbpusd_div = screener.get_cached_fx_close("GBPUSD=X", div_start)
                    if not gbpusd_div.empty:
                        fx_div = gbpusd_div.reindex(df_dividends.index).ffill().bfill()
                        df_dividends["Amount"] = df_dividends["Amount"] / fx_div
                        
        elif acct_ccy == 'GBP' and quote_ccy == 'EUR':
            start_date = t_close.index.min()
            eurgbp = screener.get_cached_fx_close("EURGBP=X", start_date)
            if not eurgbp.empty:
                fx = eurgbp.reindex(t_close.index).ffill().bfill()
                t_close = t_close * fx
                info['currency'] = 'GBP'
                
                # Also convert dividends to GBP
                if not df_dividends.empty:
                    df_dividends = df_dividends.copy()
                    df_dividends.index = pd.to_datetime(df_dividends.index).normalize()
                    if hasattr(df_dividends.index, "tz") and df_dividends.index.tz is not None:
                        df_dividends.index = df_dividends.index.tz_localize(None)
                    div_start = df_dividends.index.min()
                    eurgbp_div = screener.get_cached_fx_close("EURGBP=X", div_start)
                    if not eurgbp_div.empty:
                        fx_div = eurgbp_div.reindex(df_dividends.index).ffill().bfill()
                        df_dividends["Amount"] = df_dividends["Amount"] * fx_div

        metrics = screener.calculate_screener_metrics(t_close)
        if not metrics:
            raise HTTPException(status_code=500, detail="Failed to calculate metrics")

        anchor = None
        if not df_trades.empty:
            buys = df_trades[df_trades['Action'] == 'Buy']
            if not buys.empty:
                total_cost = buys['Net Amount'].abs().sum()
                total_shares = buys['Qty'].sum()
                if total_shares > 0:
                    anchor = total_cost / total_shares

        # Apply UK normalization
        currency_val = info.get('currency', 'USD')
        mult = currency_utils._determine_multiplier(ticker, metrics['Price'], currency=currency_val, anchor=anchor)
        if mult != 1.0:
            metrics['Price'] *= mult
            metrics['High52'] *= mult
            metrics['Low52'] *= mult
            
        ticker_upper = str(ticker).upper().strip()
        is_uk_ticker = ticker_upper.endswith(".L") or ticker_upper.endswith(".UK") or ticker_upper.endswith(".XLON")
        if is_uk_ticker or info.get('currency') == 'GBp':
            info['currency'] = 'GBP'
            
        pos_metrics = screener.calculate_position_metrics(df_trades, df_dividends, metrics['Price'])
        brkdown = screener.get_ticker_portfolio_breakdown(ticker)
        
        # Format for JSON
        for k, v in metrics.items():
            metrics[k] = clean_nan(v)
            
        for k, v in pos_metrics.items():
            if isinstance(v, pd.Timestamp):
                pos_metrics[k] = v.isoformat()
            else:
                pos_metrics[k] = clean_nan(v)

        # Get chart data
        t_close_norm = currency_utils.normalize_series(ticker, t_close.dropna(), currency=info.get('currency', 'USD'), anchor=anchor)
        
        chart_data = []
        if not t_close_norm.empty:
            # Rebase
            rebase_val = t_close_norm.iloc[0]
            
            # Benchmark
            bench_close = get_close(benchmark)
            b_slice = bench_close.reindex(t_close_norm.index).ffill()
            b_rebase = b_slice.iloc[0] if not b_slice.empty and pd.notna(b_slice.iloc[0]) else None
            
            # Portfolio
            port_data = storage.load_latest_portfolio(account)
            p_twr = pd.Series(dtype=float)
            if port_data and not port_data['df_perf'].empty:
                p_twr = port_data['df_perf']["TWR_Index"].reindex(t_close_norm.index).ffill()
            p_rebase = p_twr.dropna().iloc[0] if not p_twr.dropna().empty else None

            for date, price in t_close_norm.items():
                pt = {
                    "date": date.strftime("%Y-%m-%d"),
                    "asset_pct": clean_nan((price / rebase_val - 1) * 100 if rebase_val else None),
                }
                
                if b_rebase and date in b_slice:
                    b_val = b_slice[date]
                    if pd.notna(b_val):
                        pt["bench_pct"] = clean_nan((b_val / b_rebase - 1) * 100)
                        
                if p_rebase and date in p_twr:
                    p_val = p_twr[date]
                    if pd.notna(p_val):
                        pt["port_pct"] = clean_nan((p_val / p_rebase - 1) * 100)
                        
                chart_data.append(pt)

        # Calculate shares held over time for dividends (both ledger and YF fallback)
        shares_timeline = []
        current_shares = 0.0
        if not df_trades.empty:
            df_trades_sorted = df_trades.sort_values(by="Date")
            for _, r in df_trades_sorted.iterrows():
                act = str(r["Action"]).strip().lower()
                q = float(r["Qty"]) if pd.notna(r["Qty"]) else 0.0
                if act == 'buy':
                    current_shares += q
                elif act in ('sell', 'unparsed sell (check diagnostics)'):
                    current_shares -= q
                shares_timeline.append({"date": r["Date"], "shares": current_shares})

        # Activity markers
        trades_list = []
        if not df_trades.empty:
            for _, r in df_trades.iterrows():
                qty = float(r["Qty"]) if pd.notna(r["Qty"]) else 0.0
                net_amount = float(r["Net Amount"]) if pd.notna(r["Net Amount"]) else 0.0
                action = str(r["Action"]).strip().title()
                
                # If ledger dividend, populate qty with held shares at that date
                if action == "Dividend":
                    date_pd = pd.to_datetime(r["Date"]).tz_localize(None)
                    held_shares = 0.0
                    for st in shares_timeline:
                        if st["date"] <= date_pd:
                            held_shares = st["shares"]
                    qty = held_shares
                
                # The mathematically robust sanitized price in base currency
                if qty > 0 and net_amount != 0 and action != "Dividend":
                    trade_price = abs(net_amount) / qty
                else:
                    # Fallback to raw price parsed with currency engine if missing
                    trade_price = r["Price"]
                    if pd.notna(trade_price) and trade_price > 0:
                        trade_price = currency_utils.normalize_price(
                            ticker, 
                            float(trade_price), 
                            currency=currency_val, 
                            anchor=metrics.get('Price')
                        )
                
                trades_list.append({
                    "date": r["Date"].strftime("%Y-%m-%d"),
                    "action": r["Action"],
                    "qty": clean_nan(qty),
                    "price": clean_nan(trade_price),
                    "amount": clean_nan(r["Net Amount"]),
                    "account": str(r.get("Account", ""))
                })

        # Dividends from Yahoo Finance metadata (df_dividends from screener.get_ticker_activity)
        divs_list = []
        if not df_dividends.empty:
            for d, r in df_dividends.iterrows():
                div_date_pd = pd.to_datetime(d).tz_localize(None)
                
                # Find shares held on or before div_date
                held_shares = 0.0
                for st in shares_timeline:
                    if st["date"] <= div_date_pd:
                        held_shares = st["shares"]
                
                # Only include YF dividends if shares were actually held at the time
                if held_shares > 0.001:
                    total_div = float(r["Amount"]) * held_shares
                    divs_list.append({
                        "date": d.strftime("%Y-%m-%d"),
                        "amount": clean_nan(total_div),
                        "shares": clean_nan(held_shares)
                    })

        return {
            "metrics": metrics,
            "info": info,
            "portfolio": {
                "metrics": pos_metrics,
                "breakdown": brkdown,
            },
            "chart_data": chart_data,
            "trades": trades_list,
            "dividends": divs_list
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ai-analysis")
def generate_ai_analysis(req: AIAnalysisRequest):
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured on server")
        report = screener.run_ai_analysis(api_key, req.ticker, req.info, req.metrics)
        return {"report": report}
    except Exception as e:
        err_str = str(e).lower()
        if "503" in err_str or "unavailable" in err_str or "high demand" in err_str:
            raise HTTPException(status_code=503, detail="The AI model is currently experiencing high demand. Please try again in a few moments.")
        if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str:
            raise HTTPException(status_code=429, detail="You have exceeded your Gemini API quota. Please wait a minute or check your billing plan.")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/market-intel")
def generate_market_intel(req: AIAnalysisRequest):
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured on server")
        report = screener.run_market_intelligence_report(api_key, req.ticker, req.info, req.metrics)
        return {"report": report}
    except Exception as e:
        err_str = str(e).lower()
        if "503" in err_str or "unavailable" in err_str or "high demand" in err_str:
            raise HTTPException(status_code=503, detail="The AI model is currently experiencing high demand. Please try again in a few moments.")
        if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str:
            raise HTTPException(status_code=429, detail="You have exceeded your Gemini API quota. Please wait a minute or check your billing plan.")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/technicals")
def get_technicals_data(ticker: str):
    try:
        raw_data, info_data = screener.fetch_screener_data(tuple([ticker]), None)
        if raw_data.empty:
            raise HTTPException(status_code=404, detail="No data found from yfinance")

        def get_series(symbol, col):
            if isinstance(raw_data.columns, pd.MultiIndex):
                if symbol in raw_data.columns.levels[0]:
                    return raw_data[symbol][col]
            elif len(raw_data.columns) > 0 and not isinstance(raw_data.columns, pd.MultiIndex):
                return raw_data[col]
            return pd.Series(dtype=float)

        t_close = get_series(ticker, "Close")
        t_high = get_series(ticker, "High")
        t_low = get_series(ticker, "Low")
        t_open = get_series(ticker, "Open")
        t_vol = get_series(ticker, "Volume")
        
        if t_close.empty:
            raise HTTPException(status_code=404, detail="No price data for ticker")

        df_clean = t_close.dropna()
        if len(df_clean) < 5:
            raise HTTPException(status_code=400, detail="Not enough data points")

        # Technical Indicators
        sma50 = screener._sma(df_clean, 50)
        sma200 = screener._sma(df_clean, 200)
        bb_mid, bb_upper, bb_lower = screener._bollinger(df_clean, 20, 2.0)
        rsi = screener._rsi(df_clean, 14)
        macd, sig, hist = screener._macd(df_clean, 12, 26, 9)
        
        # Risk Metrics
        daily_ret = df_clean.pct_change()
        rolling_vol = daily_ret.rolling(30).std() * np.sqrt(252) * 100
        roll_max = df_clean.cummax()
        drawdown = (df_clean / roll_max - 1) * 100

        def clean_nan(val):
            if pd.isna(val) or np.isinf(val): return None
            return float(val)

        timeseries = []
        for date, close_val in df_clean.items():
            if pd.isna(close_val): continue
            d_str = date.strftime("%Y-%m-%d")
            
            o_val = t_open.get(date, close_val)
            h_val = t_high.get(date, close_val)
            l_val = t_low.get(date, close_val)
            v_val = t_vol.get(date, 0)
            
            timeseries.append({
                "time": d_str,
                "open": clean_nan(o_val),
                "high": clean_nan(h_val),
                "low": clean_nan(l_val),
                "close": clean_nan(close_val),
                "value": clean_nan(v_val),
                "sma50": clean_nan(sma50.get(date)),
                "sma200": clean_nan(sma200.get(date)),
                "bb_upper": clean_nan(bb_upper.get(date)),
                "bb_lower": clean_nan(bb_lower.get(date)),
                "rsi": clean_nan(rsi.get(date)),
                "macd": clean_nan(macd.get(date)),
                "macd_signal": clean_nan(sig.get(date)),
                "macd_hist": clean_nan(hist.get(date)),
                "volatility": clean_nan(rolling_vol.get(date)),
                "drawdown": clean_nan(drawdown.get(date)),
            })

        return {
            "timeseries": timeseries,
            "info": info_data.get(ticker, {})
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

class AITechnicalsRequest(BaseModel):
    ticker: str
    snapshot: str

@router.post("/technicals-ai")
def generate_technicals_ai(req: AITechnicalsRequest):
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured on server")
            
        from backend.services import gemini_util
        model = gemini_util.get_best_gemini_model(api_key)
        prompt = f"""Role: You are a Quantitative Technical Analyst at a premier hedge fund.
Task: Write a punchy, actionable 'Technical Brief' for the asset based ONLY on the snapshot below.

SNAPSHOT DATA:
{req.snapshot}

Structure your response using standard markdown:
## 📊 Trend & Momentum
Summarize the prevailing trend (SMA positioning) and momentum (RSI/MACD). Is it overbought/oversold?
## 📉 Volatility & Risk
Analyze the Bollinger Bands, Drawdown, and 30D Volatility. Are we in a squeeze? Is risk elevated?
## 🎯 Verdict
A crisp one-sentence conclusion (e.g. "Bullish continuation likely", "Caution: Bearish divergence", "Range-bound chop").
"""
        response = model.generate_content(prompt)
        return {"report": response.text}
    except Exception as e:
        import traceback
        traceback.print_exc()
        err_str = str(e).lower()
        if "503" in err_str or "unavailable" in err_str or "high demand" in err_str:
            raise HTTPException(status_code=503, detail="The AI model is currently experiencing high demand. Please try again in a few moments.")
        if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str:
            raise HTTPException(status_code=429, detail="You have exceeded your Gemini API quota. Please wait a minute or check your billing plan.")
        raise HTTPException(status_code=500, detail=str(e))
