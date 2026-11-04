import pytest
import pandas as pd
import numpy as np
from backend.services.factor_analysis_engine import resample_daily_to_weekly, run_regression_analysis

def test_resample_daily_to_weekly():
    # 5 business days with 1% daily return
    dates = pd.date_range("2024-01-01", periods=5, freq="B")
    df_daily = pd.DataFrame({"Mkt-RF": [0.01] * 5}, index=dates)
    
    df_weekly = resample_daily_to_weekly(df_daily)
    assert len(df_weekly) == 1
    # Compounded return: (1.01)^5 - 1 ≈ 0.0510100501
    expected = (1.01 ** 5) - 1.0
    assert pytest.approx(df_weekly["Mkt-RF"].iloc[0], rel=1e-4) == expected

def test_run_regression_analysis_known_loadings():
    np.random.seed(42)
    n = 200
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    
    mkt = np.random.normal(0.0005, 0.01, n)
    smb = np.random.normal(0.0002, 0.005, n)
    hml = np.random.normal(-0.0001, 0.006, n)
    rf = np.ones(n) * 0.0001
    
    # Ground truth: Alpha = 0.0002, Beta_Mkt = 1.2, Beta_SMB = 0.5, Beta_HML = -0.3
    true_alpha = 0.0002
    excess_asset = true_alpha + 1.2 * mkt + 0.5 * smb - 0.3 * hml + np.random.normal(0, 0.0005, n)
    asset_ret = excess_asset + rf
    
    asset_series = pd.Series(asset_ret, index=dates)
    factor_df = pd.DataFrame({
        "Mkt-RF": mkt,
        "SMB": smb,
        "HML": hml,
        "RF": rf
    }, index=dates)
    
    results = run_regression_analysis(asset_series, factor_df, model_type="3-Factor")
    
    # Verify R-squared is strong
    assert results["r_squared"] > 0.95
    # Verify Betas are within close range of ground truth
    loadings = results["loadings"]
    assert pytest.approx(loadings["Mkt-RF"]["beta"], abs=0.05) == 1.2
    assert pytest.approx(loadings["SMB"]["beta"], abs=0.05) == 0.5
    assert pytest.approx(loadings["HML"]["beta"], abs=0.05) == -0.3
