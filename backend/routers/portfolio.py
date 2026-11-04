import concurrent.futures
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
import pandas as pd
import numpy as np
import math

from backend.services import storage
from backend.services.engine import run_recalculation_pipeline
from backend.services.data_handler import get_account_registry, get_account_base_currency, update_account_registry_field

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

def _clean_float(v):
    if v is None: return None
    if isinstance(v, (float, np.floating)):
        if math.isnan(v) or math.isinf(v): return None
    return float(v)

_DASHBOARD_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=8)

@router.get("/dashboard")
def get_portfolio_dashboard(account: str, benchmark: str = "IUSA.L", synthetic_bm: str = None):
    has_synth_req = bool(synthetic_bm and synthetic_bm != "None (use index line only)")

    fut_portfolio = _DASHBOARD_EXECUTOR.submit(storage.load_latest_portfolio, account)
    fut_bm = _DASHBOARD_EXECUTOR.submit(storage.load_latest_benchmark, account, synthetic_bm) if has_synth_req else None
    fut_ticker = _DASHBOARD_EXECUTOR.submit(storage.load_ticker_price_series, account, benchmark) if benchmark else None
    fut_registry = _DASHBOARD_EXECUTOR.submit(get_account_registry)
    fut_prices = _DASHBOARD_EXECUTOR.submit(storage.load_last_prices, account)

    try:
        cached_result = fut_portfolio.result()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Exception in portfolio: {str(e)}")

    try:
        cached_bm = fut_bm.result() if fut_bm else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Exception in benchmark: {str(e)}")

    try:
        b_series_raw = fut_ticker.result() if fut_ticker else pd.Series(dtype=float)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Exception in ticker: {str(e)}")

    if not cached_result:
        raise HTTPException(status_code=404, detail=f"No cached portfolio found for {account}")
    
    df_perf = cached_result["df_perf"]
    positions = cached_result["positions"]
    
    # Extract cash
    cash = 0.0
    if not df_perf.empty:
        if "Cash" in df_perf.columns:
            cash = df_perf["Cash"].iloc[-1]
        elif "Cash (£)" in df_perf.columns:
            cash = df_perf["Cash (£)"].iloc[-1]
        cash = _clean_float(cash) or 0.0
        
    # Get legacy cash adjustment
    registry = fut_registry.result()
    from backend.services.data_handler import get_legacy_cash_adjustment
    legacy_adj = get_legacy_cash_adjustment(account, registry)
    base_currency = get_account_base_currency(account, registry)
    currency_symbol = "€" if base_currency == "EUR" else ("$" if base_currency == "USD" else "£")
                
    df_perf = df_perf.copy()
    if cached_bm and "df_benchmark_perf" in cached_bm and not cached_bm["df_benchmark_perf"].empty:
        df_bm = cached_bm["df_benchmark_perf"]
        df_bm_reindexed = df_bm.reindex(df_perf.index, method='ffill').bfill()
        df_perf["Synth_NAV"] = df_bm_reindexed["TWR_Index"]
        df_perf["Synth_Daily"] = df_bm_reindexed.get("Daily_Return", 0.0)
        
    bench_first_valid_date = None
    if not b_series_raw.empty:
        b_valid_raw = b_series_raw.dropna()
        if not b_valid_raw.empty:
            bench_first_valid_date = pd.Timestamp(b_valid_raw.index[0])
        b_series = b_series_raw.reindex(df_perf.index).ffill().bfill()
        if not b_series.dropna().empty:
            df_perf["Bench_NAV"] = (b_series / b_series.iloc[0]) * 100.0
            df_perf["Bench_Daily"] = b_series.pct_change().fillna(0.0)

    if "Synth_NAV" in df_perf.columns:
        df_perf["Synth_NAV"] = df_perf["Synth_NAV"].ffill().bfill()
    if "Bench_NAV" in df_perf.columns:
        df_perf["Bench_NAV"] = df_perf["Bench_NAV"].ffill().bfill()
    
    # Format df_perf for JSON
    chart_data = []
    if not df_perf.empty:
        dates = [idx.strftime("%Y-%m-%d") if isinstance(idx, pd.Timestamp) else str(idx) for idx in df_perf.index]
        times = [int(idx.timestamp() * 1000) if isinstance(idx, pd.Timestamp) else int(pd.Timestamp(idx).timestamp() * 1000) for idx in df_perf.index]
        
        def get_col_list(col_name_primary, col_name_secondary=None):
            if col_name_primary in df_perf.columns:
                return df_perf[col_name_primary].tolist()
            if col_name_secondary and col_name_secondary in df_perf.columns:
                return df_perf[col_name_secondary].tolist()
            return [None] * len(df_perf)

        total_navs = get_col_list("Total NAV", "Total NAV (£)")
        equities = get_col_list("Equity", "Equity (£)")
        cashes = get_col_list("Cash", "Cash (£)")
        twr_indices = get_col_list("TWR_Index")
        net_investeds = get_col_list("Net_Invested")
        daily_returns = get_col_list("Daily_Return")
        bench_navs = get_col_list("Bench_NAV")
        synth_navs = get_col_list("Synth_NAV") if "Synth_NAV" in df_perf.columns else [None] * len(df_perf)
        
        chart_data = [
            {
                "date": date,
                "time": tm,
                "Total_NAV": _clean_float(tn),
                "Equity": _clean_float(eq),
                "Cash": _clean_float(ca),
                "TWR_Index": _clean_float(twr),
                "Net_Invested": _clean_float(net),
                "Daily_Return": _clean_float(dr),
                "Bench_NAV": _clean_float(bn),
                "Synth_NAV": _clean_float(sn)
            }
            for date, tm, tn, eq, ca, twr, net, dr, bn, sn in zip(
                dates, times, total_navs, equities, cashes, twr_indices, net_investeds, daily_returns, bench_navs, synth_navs
            )
        ]
            
    # Include latest prices and weights
    df_prices = fut_prices.result()
    total_nav = chart_data[-1]["Total_NAV"] if chart_data else 0.0
    total_invested = chart_data[-1]["Net_Invested"] if chart_data else 0.0
    
    pos_data = []
    for ticker, shares in positions.items():
        if shares < 0.001: continue
        price = 0.0
        if not df_prices.empty and ticker in df_prices.columns:
            price = _clean_float(df_prices[ticker].iloc[-1]) or 0.0
            
        val = shares * price
        weight = (val / total_nav * 100) if total_nav > 0 else 0.0
        pos_data.append({
            "ticker": ticker,
            "shares": shares,
            "price": price,
            "value": val,
            "weight": weight
        })

    # Calculate Analytics
    returns_summary = { "1M": None, "3M": None, "6M": None, "1Y": None, "YTD": None, "MAX": None, "CAGR": None }
    bench_returns = { "1M": None, "3M": None, "6M": None, "1Y": None, "YTD": None, "MAX": None, "CAGR": None }
    calendar_returns = {}
    bench_calendar_returns = {}
    risk = {"Ann_Vol": None, "Max_DD_All": None, "Max_DD_1Y": None, "Curr_DD": None, "VaR_95": None, "CVaR_95": None}
    bench_risk = {"Ann_Vol": None, "Max_DD_All": None, "Max_DD_1Y": None, "Curr_DD": None, "VaR_95": None, "CVaR_95": None}
    ratios = {"Sharpe": None, "Sortino": None, "Calmar": None}
    bench_ratios = {"Sharpe": None, "Sortino": None, "Calmar": None}

    if len(chart_data) > 0:
        df_chart = pd.DataFrame(chart_data)
        df_chart['date'] = pd.to_datetime(df_chart['date'])
        df_chart.set_index('date', inplace=True)
        
        # Ensure numeric types so math operations don't fail and return N/A
        if 'TWR_Index' in df_chart.columns:
            df_chart['TWR_Index'] = pd.to_numeric(df_chart['TWR_Index'], errors='coerce')
        if 'Bench_NAV' in df_chart.columns:
            df_chart['Bench_NAV'] = pd.to_numeric(df_chart['Bench_NAV'], errors='coerce')
        
        # We need daily return for risk metrics
        if 'Daily_Return' not in df_chart.columns and 'TWR_Index' in df_chart.columns:
            df_chart['Daily_Return'] = df_chart['TWR_Index'].pct_change().fillna(0)
            
        if 'Bench_Daily' not in df_chart.columns and 'Bench_NAV' in df_chart.columns:
            df_chart['Bench_Daily'] = df_chart['Bench_NAV'].pct_change().fillna(0)
            
        now = df_chart.index[-1]
        
        # Period Returns
        def calc_ret(col, months_back=None, is_ytd=False):
            if col not in df_chart.columns: return None
            last_val = df_chart[col].iloc[-1]
            if is_ytd:
                target_date = pd.Timestamp(year=now.year, month=1, day=1)
            elif months_back is not None:
                target_date = now - pd.DateOffset(months=months_back)
            else:
                first_val = df_chart[col].iloc[0]
                return (last_val / first_val) - 1 if first_val > 0 else 0
                
            past = df_chart[df_chart.index <= target_date]
            if not past.empty:
                val = past[col].iloc[-1]
                if val > 0: return (last_val / val) - 1
            return None

        returns_summary["MAX"] = calc_ret('TWR_Index')
        bench_returns["MAX"] = calc_ret('Bench_NAV')
        returns_summary["1M"] = calc_ret('TWR_Index', 1)
        bench_returns["1M"] = calc_ret('Bench_NAV', 1)
        returns_summary["3M"] = calc_ret('TWR_Index', 3)
        bench_returns["3M"] = calc_ret('Bench_NAV', 3)
        returns_summary["6M"] = calc_ret('TWR_Index', 6)
        bench_returns["6M"] = calc_ret('Bench_NAV', 6)
        returns_summary["1Y"] = calc_ret('TWR_Index', 12)
        bench_returns["1Y"] = calc_ret('Bench_NAV', 12)
        returns_summary["YTD"] = calc_ret('TWR_Index', is_ytd=True)
        bench_returns["YTD"] = calc_ret('Bench_NAV', is_ytd=True)
        
        # CAGR
        days = (now - df_chart.index[0]).days
        if days > 0:
            returns_summary["CAGR"] = ((df_chart['TWR_Index'].iloc[-1] / df_chart['TWR_Index'].iloc[0]) ** (365.25 / days)) - 1
            if 'Bench_NAV' in df_chart.columns and df_chart['Bench_NAV'].iloc[0] > 0:
                b_start_date = max(df_chart.index[0], bench_first_valid_date) if bench_first_valid_date is not None else df_chart.index[0]
                b_days = max((now - b_start_date).days, 1)
                bench_returns["CAGR"] = ((df_chart['Bench_NAV'].iloc[-1] / df_chart['Bench_NAV'].iloc[0]) ** (365.25 / b_days)) - 1
                
        # Calendar Year Returns (last 6 years)
        df_yr = df_chart.copy()
        df_yr['Year'] = df_yr.index.year
        ann_ret = df_yr.groupby('Year')['TWR_Index'].apply(lambda x: (x.iloc[-1] / x.iloc[0]) - 1 if x.iloc[0] > 0 else 0)
        ann_ret_b = df_yr.groupby('Year')['Bench_NAV'].apply(lambda x: (x.iloc[-1] / x.iloc[0]) - 1 if x.iloc[0] > 0 else 0) if 'Bench_NAV' in df_chart.columns else pd.Series(dtype=float)
        
        all_years = sorted(ann_ret.index.tolist())
        for yr in all_years[-6:]:
            calendar_returns[str(yr)] = _clean_float(ann_ret.get(yr))
            bench_calendar_returns[str(yr)] = _clean_float(ann_ret_b.get(yr))
            
        # Risk Metrics (using 5Y window)
        # Note: df_chart has a 365-calendar-day index (including weekend 0.0 returns).
        # Filter daily returns to weekdays (dayofweek < 5) so 252-day annualization
        # and 95% VaR percentiles are not diluted by 104 weekend zero-return days/year.
        risk_days = min(1825, len(df_chart))
        df_risk = df_chart.tail(risk_days)
        df_1y = df_chart.tail(365)
        
        def calc_risk(col_nav, col_daily):
            res = {"Ann_Vol": None, "Max_DD_All": None, "Max_DD_1Y": None, "Curr_DD": None, "VaR_95": None, "CVaR_95": None}
            if col_nav not in df_chart.columns or col_daily not in df_chart.columns: return res
            
            dr_all = df_risk[col_daily].dropna()
            dr = dr_all[dr_all.index.dayofweek < 5] if hasattr(dr_all.index, "dayofweek") else dr_all
            if len(dr) > 0:
                res["Ann_Vol"] = dr.std() * np.sqrt(252)
                res["VaR_95"] = float(np.percentile(dr, 5))
                tail_losses = dr[dr <= res["VaR_95"]]
                res["CVaR_95"] = float(tail_losses.mean()) if len(tail_losses) > 0 else res["VaR_95"]
            
            nav = df_risk[col_nav].dropna()
            if len(nav) > 0:
                res["Max_DD_All"] = ((nav / nav.cummax()) - 1).min()
                
            nav_all = df_chart[col_nav].dropna()
            if len(nav_all) > 0:
                res["Curr_DD"] = (nav_all.iloc[-1] / nav_all.cummax().iloc[-1]) - 1
                
            nav_1y = df_1y[col_nav].dropna()
            if len(nav_1y) > 0:
                res["Max_DD_1Y"] = ((nav_1y / nav_1y.cummax()) - 1).min()
                
            return {k: _clean_float(v) for k,v in res.items()}
            
        risk = calc_risk('TWR_Index', 'Daily_Return')
        bench_risk = calc_risk('Bench_NAV', 'Bench_Daily')
        
        # Advanced Ratios
        def calc_ratios(rsk, col_nav, col_daily):
            res = {"Sharpe": None, "Sortino": None, "Calmar": None}
            if col_nav not in df_chart.columns or col_daily not in df_chart.columns: return res
            
            dr_all = df_risk[col_daily].dropna()
            dr = dr_all[dr_all.index.dayofweek < 5] if hasattr(dr_all.index, "dayofweek") else dr_all
            nav = df_risk[col_nav].dropna()
            if len(dr) > 0 and len(nav) > 1 and nav.iloc[0] > 0:
                elapsed_cal_days = max((nav.index[-1] - nav.index[0]).days, 1)
                ann_ret_risk = (nav.iloc[-1] / nav.iloc[0]) ** (365.25 / elapsed_cal_days) - 1
                # Target semi-deviation across all trading days (MAR = 0)
                down_vol = float(np.sqrt(np.mean(np.minimum(0.0, dr) ** 2)) * np.sqrt(252))
                
                vol = rsk.get("Ann_Vol") or 0.0
                mdd = rsk.get("Max_DD_All") or 0.0
                
                res["Sharpe"] = (ann_ret_risk - 0.02) / vol if vol > 0 else 0.0
                res["Sortino"] = (ann_ret_risk - 0.02) / down_vol if down_vol > 0 else 0.0
                res["Calmar"] = ann_ret_risk / abs(mdd) if abs(mdd) > 0 else 0.0
            
            return {k: _clean_float(v) for k,v in res.items()}
            
        ratios = calc_ratios(risk, 'TWR_Index', 'Daily_Return')
        bench_ratios = calc_ratios(bench_risk, 'Bench_NAV', 'Bench_Daily')

    return {
        "account": account,
        "run_timestamp": cached_result.get("run_timestamp"),
        "base_currency": base_currency,
        "currency_symbol": currency_symbol,
        "metrics": {
            "cash": cash,
            "legacy_adjustment": legacy_adj,
            "total_nav": total_nav,
            "total_invested": total_invested,
            "returns": returns_summary,
            "bench_returns": bench_returns,
            "calendar_returns": calendar_returns,
            "bench_calendar_returns": bench_calendar_returns,
            "risk": risk,
            "bench_risk": bench_risk,
            "ratios": ratios,
            "bench_ratios": bench_ratios
        },
        "chart_data": chart_data,
        "positions": pos_data
    }

class RecalculateRequest(BaseModel):
    account: str
    force_full_prices: bool = False
    active_bm_name: str | None = None

@router.post("/recalculate")
def trigger_recalculation(req: RecalculateRequest, background_tasks: BackgroundTasks):
    # Clear the GSheet cache for this account before recalculating so that
    # repair mode always pulls fresh data from Google Sheets.
    try:
        from backend.services.data_handler import get_account_registry
        registry = get_account_registry()
        if not registry.empty and "Worksheet" in registry.columns:
            match = registry[registry["Account Name"].astype(str).str.strip().str.lower() == req.account.lower()]
            if not match.empty:
                ws = match.iloc[0].get("Worksheet", "")
    except Exception as cache_err:
        pass  # Don't block recalculation if cache clear fails

    err = run_recalculation_pipeline(
        req.account, 
        force_full_prices=req.force_full_prices,
        active_bm_name=req.active_bm_name
    )
    if err:
        raise HTTPException(status_code=500, detail=str(err))
    return {"status": "success", "message": f"Successfully recalculated {req.account}"}

@router.get("/legacy-adjustment")
def get_legacy_adjustment(account: str):
    from backend.services.data_handler import get_legacy_cash_adjustment, get_account_registry
    registry = get_account_registry()
    legacy_adj = get_legacy_cash_adjustment(account, registry)
    return {"account": account, "adjustment": legacy_adj}

class LegacyAdjRequest(BaseModel):
    account: str
    adjustment: float

@router.post("/legacy-adjustment")
def update_legacy_adjustment(req: LegacyAdjRequest):
    success, err = update_account_registry_field(req.account, "Legacy Cash Adjustment", req.adjustment)
    if not success:
        raise HTTPException(status_code=500, detail=str(err))
    return {"status": "success"}

@router.get("/performance-report")
def get_performance_report(account: str, horizon: str = "MAX", start_date: str = None, end_date: str = None):
    from backend.services.data_handler import get_sanitized_ledger, get_account_registry, get_account_base_currency, get_ticker_map, apply_ticker_map
    
    # 1. Load latest portfolio snapshots
    cached = storage.load_latest_portfolio(account)
    if not cached:
        raise HTTPException(status_code=404, detail=f"No cached portfolio found for {account}")
        
    df_perf = cached["df_perf"]
    if df_perf.empty:
        raise HTTPException(status_code=404, detail=f"Cached portfolio index is empty for {account}")
        
    # Determine date boundaries based on df_perf index
    latest_date = df_perf.index[-1]
    
    if end_date:
        try:
            end_pd = pd.to_datetime(end_date)
        except Exception:
            end_pd = latest_date
    else:
        end_pd = latest_date
        
    if start_date:
        try:
            start_pd = pd.to_datetime(start_date)
        except Exception:
            start_pd = df_perf.index[0]
    else:
        if horizon == "1M":
            start_pd = end_pd - pd.DateOffset(months=1)
        elif horizon == "3M":
            start_pd = end_pd - pd.DateOffset(months=3)
        elif horizon == "6M":
            start_pd = end_pd - pd.DateOffset(months=6)
        elif horizon == "YTD":
            start_pd = pd.Timestamp(year=end_pd.year, month=1, day=1)
        elif horizon == "1Y":
            start_pd = end_pd - pd.DateOffset(years=1)
        elif horizon == "3Y":
            start_pd = end_pd - pd.DateOffset(years=3)
        elif horizon == "5Y":
            start_pd = end_pd - pd.DateOffset(years=5)
        else: # MAX or ALL
            start_pd = df_perf.index[0]
            
    # Bound check
    if start_pd < df_perf.index[0]:
        start_pd = df_perf.index[0]
    if end_pd > latest_date:
        end_pd = latest_date
        
    # Get actual index dates
    idx_start = df_perf.index[df_perf.index <= start_pd]
    if idx_start.empty:
        idx_start = df_perf.index[df_perf.index >= start_pd]
    date_start_actual = idx_start[-1] if not idx_start.empty else df_perf.index[0]
    
    idx_end = df_perf.index[df_perf.index <= end_pd]
    date_end_actual = idx_end[-1] if not idx_end.empty else latest_date
    
    val_start = float(df_perf.loc[date_start_actual, "Total NAV"])
    val_end = float(df_perf.loc[date_end_actual, "Total NAV"])
    increase = val_end - val_start
    
    # 2. Get base currency and symbol
    registry = get_account_registry()
    base_currency = get_account_base_currency(account, registry)
    currency_symbol = "€" if base_currency == "EUR" else "£"
    
    # 3. Get transactions and filter in period (date_start_actual, date_end_actual]
    df_ledger, is_sipp, _ = get_sanitized_ledger(account)
    
    # Sort ledger chronologically to compute running cost since inception
    realized_gains_period = 0.0
    paid_in = 0.0
    withdrawn = 0.0
    transferred = 0.0
    fees = 0.0
    tax = 0.0
    rebates = 0.0
    dividends = 0.0
    interest = 0.0
    
    if not df_ledger.empty:
        df_sorted_tx = df_ledger.copy()
        df_sorted_tx["NormalizedDate"] = pd.to_datetime(df_sorted_tx["Date"]).dt.normalize()
        df_sorted_tx = df_sorted_tx.sort_values("NormalizedDate").reset_index(drop=True)
        
        # Apply ticker map
        ticker_map = get_ticker_map()
        df_sorted_tx = apply_ticker_map(df_sorted_tx, ticker_map)
        
        # FIFO / average cost tracking since inception
        shares_held = {}
        avg_cost = {}
        
        for _, row in df_sorted_tx.iterrows():
            tx_date = row["NormalizedDate"]
            action = str(row.get("Action", "")).strip()
            ticker = str(row.get("Auto Ticker", "")).strip()
            qty = float(row.get("Qty", 0.0))
            net_amt = float(row.get("Net Amount", 0.0))
            
            # Identify period-specific aggregates
            is_in_period = (tx_date > date_start_actual) and (tx_date <= date_end_actual)
            
            if action == "Dividend" and is_in_period:
                dividends += net_amt
            elif action == "Interest" and is_in_period:
                interest += net_amt
            elif action == "Fee" and is_in_period:
                fees += net_amt
            elif action in ("Buy", "Sell", "Unparsed Sell (Check Diagnostics)"):
                pass
            elif is_in_period:
                # Other actions (Transfer, Other) are external cash flows
                if net_amt > 0:
                    paid_in += net_amt
                else:
                    withdrawn += net_amt
                    
            # Ticker-level shares / cost tracking
            if not ticker or ticker.lower() == "nan":
                continue
                
            if action == "Buy":
                curr_shares = shares_held.get(ticker, 0.0)
                curr_cost = avg_cost.get(ticker, 0.0) * curr_shares
                new_shares = curr_shares + qty
                new_cost = curr_cost + abs(net_amt)
                shares_held[ticker] = new_shares
                avg_cost[ticker] = new_cost / new_shares if new_shares > 0 else 0.0
            elif action in ("Sell", "Unparsed Sell (Check Diagnostics)"):
                curr_shares = shares_held.get(ticker, 0.0)
                curr_avg_cost = avg_cost.get(ticker, 0.0)
                
                # realized gain/loss
                proceeds = abs(net_amt)
                cost_of_shares_sold = qty * curr_avg_cost
                trade_realized_gain = proceeds - cost_of_shares_sold
                
                if is_in_period:
                    realized_gains_period += trade_realized_gain
                    
                new_shares = max(0.0, curr_shares - qty)
                shares_held[ticker] = new_shares
                if new_shares <= 0.001:
                    avg_cost[ticker] = 0.0
                    
    payments_transfers_total = paid_in + withdrawn + transferred + fees + tax + rebates
    performance_total = increase - payments_transfers_total
    
    # Investment value change is the residual performance
    investment_value_change = performance_total - realized_gains_period - interest - dividends
    
    # TWR return percentage
    twr_start = float(df_perf.loc[date_start_actual, "TWR_Index"])
    twr_end = float(df_perf.loc[date_end_actual, "TWR_Index"])
    twr_return_pct = ((twr_end / twr_start - 1.0) * 100.0) if twr_start > 0 else 0.0
    
    # Chart series
    df_chart = df_perf.loc[date_start_actual:date_end_actual]
    chart_series = []
    for d, row in df_chart.iterrows():
        chart_series.append({
            "date": d.strftime("%Y-%m-%d"),
            "time": int(d.timestamp() * 1000),
            "Total_NAV": float(row["Total NAV"]),
            "TWR_Index": float(row["TWR_Index"])
        })
        
    return {
        "account": account,
        "base_currency": base_currency,
        "currency_symbol": currency_symbol,
        "date_start": date_start_actual.strftime("%Y-%m-%d"),
        "date_end": date_end_actual.strftime("%Y-%m-%d"),
        "value_start": round(val_start, 2),
        "value_end": round(val_end, 2),
        "increase": round(increase, 2),
        "twr_return_pct": round(twr_return_pct, 2),
        "payments_transfers": {
            "paid_in": round(paid_in, 2),
            "withdrawn": round(withdrawn, 2),
            "transferred": round(transferred, 2),
            "fees_charges": round(fees, 2),
            "tax": round(tax, 2),
            "rebates": round(rebates, 2),
            "total": round(payments_transfers_total, 2)
        },
        "performance": {
            "value_change": round(investment_value_change, 2),
            "investments_sold": round(realized_gains_period, 2),
            "gross_interest": round(interest, 2),
            "accrued_interest": 0.0,
            "dividends": round(dividends, 2),
            "total": round(performance_total, 2)
        },
        "chart_data": chart_series
    }

