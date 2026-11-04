from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np

from backend.services import storage
from backend.services import factor_analysis_engine as fae

router = APIRouter(prefix="/api/factors", tags=["factors"])

class FactorsRunRequest(BaseModel):
    account: str
    model_type: str
    frequency: str
    start_date: str
    end_date: str

class FactorsRollingRequest(BaseModel):
    account: str
    model_type: str
    frequency: str
    start_date: str
    end_date: str
    window: int

def _get_portfolio_returns(account: str, start_date: str, end_date: str, frequency: str) -> pd.Series:
    try:
        port_data = storage.load_latest_portfolio(account)
        df_perf = port_data["df_perf"] if port_data else pd.DataFrame()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load portfolio history: {str(e)}")

    if df_perf.empty:
        raise HTTPException(status_code=400, detail="No performance history found. Please run the calculation engine first.")

    if not isinstance(df_perf.index, pd.DatetimeIndex):
        df_perf.index = pd.to_datetime(df_perf.index)

    if "TWR_Index" in df_perf.columns:
        portfolio_returns = df_perf["TWR_Index"].pct_change().fillna(0.0)
    elif "Time-Weighted Return" in df_perf.columns:
        portfolio_returns = df_perf["Time-Weighted Return"].pct_change().fillna(0.0)
    elif "Daily_Return" in df_perf.columns:
        portfolio_returns = df_perf["Daily_Return"].fillna(0.0)
    else:
        raise HTTPException(status_code=400, detail="No return series found in the portfolio data.")

    # Filter dates
    try:
        sd = pd.to_datetime(start_date).tz_localize(None)
        ed = pd.to_datetime(end_date).tz_localize(None)
        portfolio_returns.index = portfolio_returns.index.tz_localize(None)
        portfolio_returns = portfolio_returns[(portfolio_returns.index >= sd) & (portfolio_returns.index <= ed)]
    except Exception:
        pass

    # Resample if needed
    if frequency.startswith("Weekly"):
        portfolio_returns = (1 + portfolio_returns).resample("W-FRI").prod() - 1
    elif frequency == "Monthly":
        portfolio_returns = (1 + portfolio_returns).resample("ME").prod() - 1

    return portfolio_returns

def _get_factor_df(model_type: str, frequency: str) -> pd.DataFrame:
    # Map to Fama-French internal types
    if model_type == "3-Factor":
        if frequency == "Monthly":
            ff_type = "3_factor_monthly"
        else:
            ff_type = "3_factor_daily"
    else:
        if frequency == "Monthly":
            ff_type = "5_factor_monthly"
        else:
            ff_type = "5_factor_daily"

    try:
        factor_df = fae.download_and_parse_factors(ff_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download Fama-French factors: {str(e)}")

    if factor_df.empty:
        raise HTTPException(status_code=500, detail="Downloaded Fama-French data is empty.")

    # `factor_df` is already returned as decimal values by `fae.download_and_parse_factors`
    # No need to divide by 100 again.

    if frequency.startswith("Weekly") and "daily" in ff_type:
        # Resample daily factors to weekly
        factor_df = (1 + factor_df).resample("W-FRI").prod() - 1

    return factor_df

@router.post("/run")
def run_factors(req: FactorsRunRequest):
    asset_returns = _get_portfolio_returns(req.account, req.start_date, req.end_date, req.frequency)
    factor_df = _get_factor_df(req.model_type, req.frequency)

    res = fae.run_regression_analysis(asset_returns, factor_df, req.model_type)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])

    # Annualize Alpha
    if req.frequency.startswith("Weekly"):
        ann_alpha = res["loadings"]["Alpha"]["beta"] * 52
    elif req.frequency == "Monthly":
        ann_alpha = res["loadings"]["Alpha"]["beta"] * 12
    else:
        ann_alpha = res["loadings"]["Alpha"]["beta"] * 252

    # Determine alpha significance based on p-value
    p_val = res["loadings"]["Alpha"]["p_value"]
    if p_val < 0.01:
        alpha_sig = "Highly Sig. (1%)"
    elif p_val < 0.05:
        alpha_sig = "Significant (5%)"
    elif p_val < 0.10:
        alpha_sig = "Marginally Sig. (10%)"
    else:
        alpha_sig = "Not Significant"

    # Cumulative Chart
    cum_actual = (1 + np.array(res["y_excess"])).cumprod() - 1
    cum_fitted = (1 + np.array(res["fitted"])).cumprod() - 1

    cumulative_chart = []
    for idx, d in enumerate(res["dates"]):
        cumulative_chart.append({
            "date": d,
            "actual": cum_actual[idx],
            "fitted": cum_fitted[idx]
        })

    # Regression Table Formatting
    def get_stars(p):
        if p < 0.01: return "***"
        if p < 0.05: return "**"
        if p < 0.10: return "*"
        return ""

    regression_table = []
    for f_name, stats in res["loadings"].items():
        regression_table.append({
            "factor": f_name,
            "beta": f"+{stats['beta']:.4f}" if stats['beta'] > 0 else f"{stats['beta']:.4f}",
            "stderr": f"{stats['stderr']:.4f}",
            "t_stat": f"+{stats['t_stat']:.2f}" if stats['t_stat'] > 0 else f"{stats['t_stat']:.2f}",
            "p_value": f"{stats['p_value']:.4f}",
            "significance": get_stars(stats['p_value'])
        })

    return {
        "n_obs": res["n_obs"],
        "r_squared": res["r_squared"],
        "adj_r_squared": res["adj_r_squared"],
        "annualized_alpha": ann_alpha,
        "alpha_significance": alpha_sig,
        "loadings": res["loadings"],
        "cumulative_chart": cumulative_chart,
        "regression_table": regression_table
    }

@router.post("/rolling")
def run_factors_rolling(req: FactorsRollingRequest):
    asset_returns = _get_portfolio_returns(req.account, req.start_date, req.end_date, req.frequency)
    factor_df = _get_factor_df(req.model_type, req.frequency)

    rolling_df = fae.run_rolling_regression(asset_returns, factor_df, req.model_type, req.window)
    if rolling_df.empty:
        return {"data": []}

    rolling_df = rolling_df.reset_index()
    # Ensure Date is string
    rolling_df["Date"] = rolling_df["Date"].dt.strftime("%Y-%m-%d")
    
    # We want format: [{"date": "...", "Mkt-RF": 1.2, "SMB": -0.1}, ...]
    return {"data": rolling_df.to_dict(orient="records")}
