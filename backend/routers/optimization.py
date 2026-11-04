from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np

from backend.services import storage
from backend.services import engine
from backend.services import optimization_engine

router = APIRouter(prefix="/api/optimization", tags=["optimization"])

class OptimizationRunRequest(BaseModel):
    account: str
    tickers: List[str]
    lookback_years: int
    opt_mode: str
    hypothetical_tickers: Optional[List[str]] = None
    return_overrides: Optional[Dict[str, float]] = None

@router.get("/held-tickers")
def get_held_tickers():
    tickers = storage.get_currently_held_tickers()
    return {"tickers": tickers}

def _fetch_prices_for_optimization(account: str, all_tickers: List[str], lookback_years: int):
    # Try to load cached full price grid
    try:
        cached_df = storage.load_full_price_grid(account)
    except Exception:
        cached_df = pd.DataFrame()

    missing_tickers = []
    found_tickers_data = {}

    if not cached_df.empty:
        for t in all_tickers:
            if t in cached_df.columns:
                found_tickers_data[t] = cached_df[t]
            else:
                missing_tickers.append(t)
    else:
        missing_tickers = all_tickers

    if missing_tickers:
        # Calculate start date based on lookback
        cutoff_date = pd.Timestamp.now(tz='UTC') - pd.DateOffset(years=lookback_years)
        start_date = cutoff_date.date()
        
        # Load expected prices from the database for unit cleansing anchors
        try:
            last_prices_df = storage.load_last_prices(account)
            expected_prices = last_prices_df.iloc[-1].to_dict() if not last_prices_df.empty else {}
        except Exception:
            expected_prices = {}

        # Fetch missing tickers via the engine's standardized history fetcher (which includes currency normalisation and spike filtering)
        fetched_df, _, _, _ = engine.fetch_portfolio_history_and_currency(
            tickers=missing_tickers,
            start_date=start_date,
            expected_prices=expected_prices,
            base_currency='GBP'
        )
        
        if not fetched_df.empty:
            for t in missing_tickers:
                if t in fetched_df.columns:
                    found_tickers_data[t] = fetched_df[t]

    if not found_tickers_data:
        raise HTTPException(status_code=400, detail="Could not fetch price data for any selected tickers.")

    prices_df = pd.DataFrame(found_tickers_data)
    prices_df = prices_df.dropna(how='all')
    prices_df = prices_df.ffill().bfill()
    
    # Filter lookback period
    cutoff_date = pd.Timestamp.now(tz='UTC') - pd.DateOffset(years=lookback_years)
    try:
        prices_df.index = pd.to_datetime(prices_df.index, utc=True)
    except Exception:
        pass
        
    # Ensure cutoff_date timezone matches index timezone
    if prices_df.index.tz is None:
        cutoff_date = cutoff_date.tz_localize(None)
        
    prices_df = prices_df[prices_df.index >= cutoff_date]
    
    # Drop weekends to align with 252 trading days annualization
    # (Cached prices from storage contain calendar days with flat-filled weekends)
    prices_df = prices_df[prices_df.index.dayofweek < 5]
    
    return prices_df

@router.post("/run")
def run_optimization(req: OptimizationRunRequest):
    all_tickers = list(set(req.tickers + (req.hypothetical_tickers or [])))
    if not all_tickers:
        raise HTTPException(status_code=400, detail="No tickers provided.")

    prices_df = _fetch_prices_for_optimization(req.account, all_tickers, req.lookback_years)
    
    if len(prices_df) < 20:
        raise HTTPException(status_code=400, detail="Insufficient price history for the selected lookback.")

    daily_returns = prices_df.pct_change().dropna(how='all').fillna(0)
    cov_matrix = daily_returns.cov() * 252

    # Expected returns logic
    if req.return_overrides:
        returns_mean = pd.Series({
            t: req.return_overrides.get(t, daily_returns[t].mean() * 252)
            for t in daily_returns.columns
        })
    else:
        returns_mean = daily_returns.mean() * 252

    # Calculate optimal portfolios
    max_sharpe_res = optimization_engine.solve_max_sharpe(returns_mean, cov_matrix)
    min_vol_res = optimization_engine.solve_min_volatility(returns_mean, cov_matrix)

    # Calculate efficient frontier
    frontier_df = optimization_engine.calculate_efficient_frontier(returns_mean, cov_matrix)
    frontier_data = []
    if not frontier_df.empty:
        frontier_data = frontier_df.to_dict(orient="records")

    # Current portfolio weights
    current_portfolios = {}
    current_vol = None
    if req.account:
        try:
            port_data = storage.load_latest_portfolio(req.account)
            snapshot_df = port_data["df_perf"] if port_data else pd.DataFrame()
            if not snapshot_df.empty:
                latest = snapshot_df.iloc[-1]
                val = float(latest["Total NAV"])
                if val > 0:
                    # Let's query from daily ticker table for latest date.
                    from backend.services.database import get_app_connection
                    with get_app_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                SELECT ticker, weight FROM portfolio_ticker_daily
                                WHERE account = %s AND date = (SELECT MAX(date) FROM portfolio_ticker_daily WHERE account = %s)
                            """, (req.account, req.account))
                            rows = cur.fetchall()
                    
                    cw = {}
                    for r in rows:
                        cw[r[0]] = float(r[1]) if r[1] is not None else 0.0
                    
                    # Ensure sum is 1, and pad zeros for unheld assets in selection
                    port_ret, port_vol, port_sharpe = 0, 0, 0
                    if cw:
                        weights_arr = np.array([cw.get(t, 0.0) for t in returns_mean.index])
                        port_ret, port_vol, port_sharpe = optimization_engine.calculate_portfolio_stats(weights_arr, returns_mean, cov_matrix)
                        current_vol = port_vol
                        
                    current_portfolios[req.account] = {
                        "Weights": {t: cw.get(t, 0.0) for t in returns_mean.index},
                        "Return": port_ret,
                        "Volatility": port_vol,
                        "Sharpe": port_sharpe
                    }
        except Exception as e:
            print("Error computing current portfolio weights:", e)

    # Determine target portfolio based on mode
    target_portfolio = max_sharpe_res
    if req.opt_mode == "Min Volatility":
        target_portfolio = min_vol_res
    elif req.opt_mode == "Target Risk (Match Current)":
        if current_vol is not None and current_vol > 0:
            tr_res = optimization_engine.solve_target_risk(returns_mean, cov_matrix, current_vol)
            if tr_res.get("success"):
                target_portfolio = tr_res
            else:
                target_portfolio = max_sharpe_res # Fallback if solver fails
        else:
            raise HTTPException(status_code=400, detail="Cannot match current risk: no current portfolio found or current volatility is 0.")
    
    # Backtest and Forecast
    # To do this accurately we need daily target portfolio returns
    backtest_data = []
    forecast_data = {}
    
    if target_portfolio.get("success"):
        target_weights = target_portfolio["weights"]
        # Daily target return = sum of w_i * r_i(t)
        common_tickers = list(target_weights.index)
        t_daily_returns = daily_returns[common_tickers].dot(target_weights)
        
        # Cumulative backtest (normalized to 1)
        cum_target = (1 + t_daily_returns).cumprod()
        for dt, val in cum_target.items():
            backtest_data.append({"date": dt.strftime("%Y-%m-%d"), "target": val})
            
        # Add current portfolio backtest
        if current_portfolios.get(req.account):
            c_weights = current_portfolios[req.account]["Weights"]
            c_weights_s = pd.Series(c_weights)
            c_daily_returns = daily_returns[common_tickers].dot(c_weights_s)
            cum_current = (1 + c_daily_returns).cumprod()
            for idx, (dt, val) in enumerate(cum_current.items()):
                backtest_data[idx]["current"] = val
                
        # Forecast (GBM)
        try:
            # Re-fetch or reuse daily_returns for GBM (1 year forward, 252 days)
            # Use geometric Brownian motion or simpler approximation
            mu = target_portfolio["return"]
            sigma = target_portfolio["volatility"]
            
            days = 252
            last_val = cum_target.iloc[-1]
            dt_days = np.array(range(1, days + 1)) / 252
            
            median = last_val * np.exp((mu - 0.5 * sigma**2) * dt_days)
            upper_1s = median * np.exp(sigma * np.sqrt(dt_days))
            lower_1s = median * np.exp(-sigma * np.sqrt(dt_days))
            upper_2s = median * np.exp(2 * sigma * np.sqrt(dt_days))
            lower_2s = median * np.exp(-2 * sigma * np.sqrt(dt_days))
            
            base_date = pd.Timestamp.now(tz='UTC')
            forecast_dates = [(base_date + pd.Timedelta(days=int(d*365/252))).strftime("%Y-%m-%d") for d in dt_days]
            
            forecast_data = {
                "dates": forecast_dates,
                "median": median.tolist(),
                "upper_1s": upper_1s.tolist(),
                "lower_1s": lower_1s.tolist(),
                "upper_2s": upper_2s.tolist(),
                "lower_2s": lower_2s.tolist()
            }
        except Exception as e:
            print("Forecast error:", e)

    # Correlation Matrix
    corr_matrix = daily_returns.corr().round(2)
    
    # Individual assets
    individual_assets = []
    for t in returns_mean.index:
        individual_assets.append({
            "ticker": t,
            "return": returns_mean[t],
            "volatility": np.sqrt(cov_matrix.loc[t, t])
        })

    return {
        "frontier": frontier_data,
        "target_portfolio": {
            "weights": target_portfolio.get("weights", {}).to_dict() if isinstance(target_portfolio.get("weights"), pd.Series) else target_portfolio.get("weights", {}),
            "return": target_portfolio.get("return", 0),
            "volatility": target_portfolio.get("volatility", 0),
            "sharpe": target_portfolio.get("sharpe", 0)
        },
        "max_sharpe": {
            "weights": max_sharpe_res.get("weights", {}).to_dict() if isinstance(max_sharpe_res.get("weights"), pd.Series) else max_sharpe_res.get("weights", {}),
            "return": max_sharpe_res.get("return", 0),
            "volatility": max_sharpe_res.get("volatility", 0),
            "sharpe": max_sharpe_res.get("sharpe", 0)
        },
        "min_vol": {
            "weights": min_vol_res.get("weights", {}).to_dict() if isinstance(min_vol_res.get("weights"), pd.Series) else min_vol_res.get("weights", {}),
            "return": min_vol_res.get("return", 0),
            "volatility": min_vol_res.get("volatility", 0),
            "sharpe": min_vol_res.get("sharpe", 0)
        },
        "current_portfolios": current_portfolios,
        "individual_assets": individual_assets,
        "correlation_matrix": {
            "tickers": list(corr_matrix.columns),
            "values": corr_matrix.values.tolist()
        },
        "backtest": backtest_data,
        "forecast": forecast_data
    }

@router.post("/frontier")
def get_frontier_only(req: OptimizationRunRequest):
    # Lighter endpoint
    all_tickers = list(set(req.tickers + (req.hypothetical_tickers or [])))
    if not all_tickers:
        return {"frontier": [], "individual_assets": []}
    
    prices_df = _fetch_prices_for_optimization(req.account, all_tickers, req.lookback_years)
    if len(prices_df) < 20:
        return {"frontier": [], "individual_assets": []}

    daily_returns = prices_df.pct_change().dropna(how='all').fillna(0)
    cov_matrix = daily_returns.cov() * 252

    if req.return_overrides:
        returns_mean = pd.Series({
            t: req.return_overrides.get(t, daily_returns[t].mean() * 252)
            for t in daily_returns.columns
        })
    else:
        returns_mean = daily_returns.mean() * 252

    frontier_df = optimization_engine.calculate_efficient_frontier(returns_mean, cov_matrix)
    frontier_data = []
    if not frontier_df.empty:
        frontier_data = frontier_df.to_dict(orient="records")
        
    individual_assets = []
    for t in returns_mean.index:
        individual_assets.append({
            "ticker": t,
            "return": returns_mean[t],
            "volatility": np.sqrt(cov_matrix.loc[t, t])
        })

    return {
        "frontier": frontier_data,
        "individual_assets": individual_assets
    }

@router.post("/historical-returns")
def get_historical_returns(req: OptimizationRunRequest):
    all_tickers = list(set(req.tickers + (req.hypothetical_tickers or [])))
    if not all_tickers:
        return {}
    
    try:
        prices_df = _fetch_prices_for_optimization(req.account, all_tickers, req.lookback_years)
        if len(prices_df) < 20:
            return {}
        
        daily_returns = prices_df.pct_change().dropna(how='all').fillna(0)
        returns_mean = daily_returns.mean() * 252
        return returns_mean.to_dict()
    except Exception as e:
        print("Error fetching historical returns:", e)
        return {}
