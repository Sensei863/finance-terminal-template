import os
import zipfile
import urllib.request
import io
import pandas as pd
import numpy as np
import scipy.stats as stats
from pathlib import Path

# Paths
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "fama_french"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# URL Dictionary
FAMA_FRENCH_URLS = {
    "3_factor_daily": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip",
    "3_factor_monthly": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip",
    "5_factor_daily": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    "5_factor_monthly": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_CSV.zip",
}

def download_and_parse_factors(factor_type: str) -> pd.DataFrame:
    """
    Downloads, parses, and caches Fama-French factors.
    Returns a dataframe with DateTimeIndex and float values.
    """
    cache_path = CACHE_DIR / f"{factor_type}.csv"
    
    # Fast path: load from cache if it exists and is not empty
    if cache_path.exists() and cache_path.stat().st_size > 1024:
        try:
            df = pd.read_csv(cache_path, parse_dates=["Date"])
            df.set_index("Date", inplace=True)
            return df
        except Exception:
            pass # fallback to downloading if parsing cache fails

    url = FAMA_FRENCH_URLS.get(factor_type)
    if not url:
        raise ValueError(f"Unknown Fama-French factor type: {factor_type}")

    # Download ZIP with User-Agent header (Dartmouth blocks default python agent)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    
    with urllib.request.urlopen(req) as response:
        zip_data = response.read()

    # Extract CSV from ZIP
    with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
        csv_filename = z.namelist()[0]
        csv_bytes = z.read(csv_filename)
    
    # Read text lines to clean metadata
    csv_text = csv_bytes.decode("utf-8", errors="ignore")
    lines = csv_text.splitlines()
    
    # Find start of main table
    # Standard Kenneth French files have a blank line or title line, then the header.
    # We hunt for a line that starts with Date/blank/Mkt-RF or has date format like YYYYMMDD
    header_idx = 0
    for idx, line in enumerate(lines[:10]):
        # The daily file has 'Mkt-RF' or starts with empty comma
        if "Mkt-RF" in line or "SMB" in line:
            header_idx = idx
            break
            
    # Clean the header
    header_line = lines[header_idx]
    cols = [c.strip() for c in header_line.split(",")]
    if cols[0] == "" or not cols[0]:
        cols[0] = "Date"
        
    # Reassemble table lines up to the blank line or annual factors section
    table_lines = [header_line]
    is_monthly = "monthly" in factor_type
    
    for line in lines[header_idx + 1:]:
        parts = [p.strip() for p in line.split(",")]
        if not parts or parts[0] == "":
            break
        # Monthly file usually has an "Annual Factors: January-December" section at the bottom
        if is_monthly and "Annual Factors" in line:
            break
        # Ignore lines that do not start with digits (the date)
        if not parts[0].isdigit():
            continue
        table_lines.append(line)
        
    # Read with pandas
    cleaned_csv = "\n".join(table_lines)
    df = pd.read_csv(io.StringIO(cleaned_csv))
    
    # Parse dates
    df.rename(columns={df.columns[0]: "Date"}, inplace=True)
    df["Date"] = df["Date"].astype(str)
    
    if is_monthly:
        # Format is YYYYMM
        df["Date"] = pd.to_datetime(df["Date"], format="%Y%m") + pd.offsets.MonthEnd(0)
    else:
        # Format is YYYYMMDD
        df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d")
        
    df.set_index("Date", inplace=True)
    
    # Fama-French factors are in percentage format (e.g. 1.23 means 1.23%).
    # We divide by 100 to convert to decimal returns.
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce") / 100.0
        
    df.dropna(inplace=True)
    
    # Save to local cache
    df.to_csv(cache_path)
    return df

def resample_daily_to_weekly(df_daily: pd.DataFrame) -> pd.DataFrame:
    """
    Helper function to compound daily Fama-French factors into weekly returns.
    Aligned to Friday (W-FRI).
    """
    # For returns we compound: R_week = prod(1 + R_day) - 1
    # For Risk-free rate RF, we also compound.
    # Mkt-RF, SMB, HML, RMW, CMA are excess or return spreads. They are compounded as well.
    weekly_df = (1.0 + df_daily).resample("W-FRI").prod() - 1.0
    return weekly_df

def run_regression_analysis(
    asset_returns: pd.Series,
    factor_df: pd.DataFrame,
    model_type: str = "5-Factor"
) -> dict:
    """
    Runs multi-variable linear regression using NumPy / SciPy.
    - asset_returns: pd.Series of asset returns (with DatetimeIndex)
    - factor_df: pd.DataFrame of factors (with DatetimeIndex)
    - model_type: '3-Factor' or '5-Factor'
    
    Returns a dictionary of metrics, betas, p-values, t-stats, and R-squared.
    """
    # Define factors based on model
    if model_type == "3-Factor":
        factor_cols = ["Mkt-RF", "SMB", "HML"]
    else:
        factor_cols = ["Mkt-RF", "SMB", "HML", "RMW", "CMA"]
        
    # Intersect indexes
    common_idx = asset_returns.index.intersection(factor_df.index)
    if len(common_idx) < 60:
        return {"error": f"Insufficient aligned data points. Need at least 60, but only found {len(common_idx)}."}
        
    y = asset_returns.loc[common_idx].values
    X_df = factor_df.loc[common_idx, factor_cols]
    
    # Subtract Risk-Free Rate from Asset Returns to get Excess Returns
    rf = factor_df.loc[common_idx, "RF"].values
    y_excess = y - rf
    
    # Prepare X with an intercept
    X = X_df.values
    N, K = X.shape
    X_design = np.column_stack((np.ones(N), X)) # intercept is first col
    
    # Solve OLS: beta = (X^T * X)^-1 * X^T * y
    try:
        beta, residuals, rank, s = np.linalg.lstsq(X_design, y_excess, rcond=None)
    except Exception as e:
        return {"error": f"Regression computation failed: {str(e)}"}
        
    # Calculate statistics
    y_mean = np.mean(y_excess)
    ss_total = np.sum((y_excess - y_mean) ** 2)
    ss_residual = np.sum((y_excess - X_design @ beta) ** 2)
    
    r_squared = 1.0 - (ss_residual / ss_total) if ss_total > 0 else 0.0
    adj_r_squared = 1.0 - (1.0 - r_squared) * (N - 1) / (N - K - 1) if N - K - 1 > 0 else 0.0
    
    # Variance-Covariance matrix of coefficients
    # s2 = ss_residual / (N - df_model - 1)
    dof = N - K - 1
    s2 = ss_residual / dof if dof > 0 else 0.0
    
    try:
        vcov = s2 * np.linalg.inv(X_design.T @ X_design)
        stderr = np.sqrt(np.diag(vcov))
    except Exception:
        stderr = np.zeros(K + 1)
        
    # t-statistics and p-values
    t_stats = np.zeros(K + 1)
    p_values = np.zeros(K + 1)
    
    for i in range(K + 1):
        if stderr[i] > 0:
            t_stats[i] = beta[i] / stderr[i]
            p_values[i] = 2.0 * (1.0 - stats.t.cdf(np.abs(t_stats[i]), df=dof)) if dof > 0 else 1.0
        else:
            t_stats[i] = 0.0
            p_values[i] = 1.0
            
    # Compile output
    factor_names = ["Alpha"] + factor_cols
    loadings = {}
    for i, name in enumerate(factor_names):
        loadings[name] = {
            "beta": float(beta[i]),
            "stderr": float(stderr[i]),
            "t_stat": float(t_stats[i]),
            "p_value": float(p_values[i])
        }
        
    return {
        "n_obs": int(N),
        "dof": int(dof),
        "r_squared": float(r_squared),
        "adj_r_squared": float(adj_r_squared),
        "loadings": loadings,
        "y_excess": y_excess.tolist(),
        "fitted": (X_design @ beta).tolist(),
        "dates": common_idx.strftime("%Y-%m-%d").tolist()
    }

def run_rolling_regression(
    asset_returns: pd.Series,
    factor_df: pd.DataFrame,
    model_type: str = "5-Factor",
    window: int = 60
) -> pd.DataFrame:
    """
    Computes rolling betas over a moving window of days/weeks/months.
    """
    if model_type == "3-Factor":
        factor_cols = ["Mkt-RF", "SMB", "HML"]
    else:
        factor_cols = ["Mkt-RF", "SMB", "HML", "RMW", "CMA"]
        
    common_idx = asset_returns.index.intersection(factor_df.index)
    if len(common_idx) < window:
        return pd.DataFrame()
        
    y = asset_returns.loc[common_idx]
    rf = factor_df.loc[common_idx, "RF"]
    y_excess = y - rf
    X = factor_df.loc[common_idx, factor_cols]
    
    # Store outputs
    rolling_results = []
    
    for end_idx in range(window, len(common_idx) + 1):
        start_idx = end_idx - window
        sub_dates = common_idx[start_idx:end_idx]
        
        y_sub = y_excess.iloc[start_idx:end_idx].values
        X_sub = X.iloc[start_idx:end_idx].values
        X_design = np.column_stack((np.ones(window), X_sub))
        
        try:
            beta, _, _, _ = np.linalg.lstsq(X_design, y_sub, rcond=None)
            res = {"Date": sub_dates[-1], "Alpha": beta[0]}
            for i, col in enumerate(factor_cols):
                res[col] = beta[i + 1]
            rolling_results.append(res)
        except Exception:
            pass
            
    if not rolling_results:
        return pd.DataFrame()
        
    df_roll = pd.DataFrame(rolling_results)
    df_roll.set_index("Date", inplace=True)
    return df_roll
