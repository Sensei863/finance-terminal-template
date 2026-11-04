import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from backend.services.performance import calculate_twr_series

def test_twr_snapshot_day_baseline():
    # Day 0: Snapshot date
    day0 = pd.Timestamp("2024-01-01")
    date_range = pd.date_range(day0, day0)
    
    # Prices: VUSA.L at 60.0
    df_prices = pd.DataFrame({"VUSA.L": [60.0]}, index=date_range)
    df_parsed = pd.DataFrame(columns=["Date", "Action", "Qty", "Net Amount", "Auto Ticker"])
    
    # Snapshot: £1,000 cash, 10 shares of VUSA.L (£600 equity)
    df_perf, positions, final_cash = calculate_twr_series(
        df_parsed=df_parsed,
        df_prices=df_prices,
        snapshot_cash=1000.0,
        snapshot_quantities={"VUSA.L": 10.0}
    )
    
    assert len(df_perf) >= 1
    first_row = df_perf.iloc[0]
    assert first_row["Equity"] == 600.0
    assert first_row["Cash"] == 1000.0
    assert first_row["Total NAV"] == 1600.0
    assert first_row["TWR_Index"] == 100.0
    assert first_row["Net_Invested"] == 1600.0
    assert positions.get("VUSA.L") == 10.0
    assert final_cash == 1000.0

def test_twr_cash_injection_neutrality():
    # Verify that external cash deposits do NOT artificially inflate TWR_Index
    day0 = pd.Timestamp("2024-01-01")
    day1 = pd.Timestamp("2024-01-02")
    date_range = pd.date_range(day0, day1)
    
    # Static price grid
    df_prices = pd.DataFrame({"VUSA.L": [60.0, 60.0]}, index=date_range)
    
    # External cash deposit of £500 on day 1
    ledger = pd.DataFrame([
        {
            "Date": day1,
            "Action": "Transfer",
            "Qty": 0.0,
            "Net Amount": 500.0,
            "Auto Ticker": ""
        }
    ])
    
    df_perf, positions, final_cash = calculate_twr_series(
        df_parsed=ledger,
        df_prices=df_prices,
        snapshot_cash=1000.0,
        snapshot_quantities={"VUSA.L": 10.0}
    )
    
    row_day1 = df_perf.loc[day1] if day1 in df_perf.index else df_perf.iloc[-1]
    assert row_day1["Cash"] == 1500.0
    assert row_day1["Total NAV"] == 2100.0
    # Net invested increased by £500
    assert row_day1["Net_Invested"] == 2100.0
    # Crucially, TWR must remain 100.0 because there was zero asset price performance
    assert pytest.approx(row_day1["TWR_Index"], abs=0.001) == 100.0

def test_twr_price_movement_compounding():
    # Day 0: 10 shares @ 60.0, Day 1: 10 shares @ 66.0 (+10% on £600 equity = +£60 on £1600 NAV = +3.75%)
    day0 = pd.Timestamp("2024-01-01")
    day1 = pd.Timestamp("2024-01-02")
    date_range = pd.date_range(day0, day1)
    
    df_prices = pd.DataFrame({"VUSA.L": [60.0, 66.0]}, index=date_range)
    df_parsed = pd.DataFrame(columns=["Date", "Action", "Qty", "Net Amount", "Auto Ticker"])
    
    df_perf, positions, final_cash = calculate_twr_series(
        df_parsed=df_parsed,
        df_prices=df_prices,
        snapshot_cash=1000.0,
        snapshot_quantities={"VUSA.L": 10.0}
    )
    
    row_day1 = df_perf.loc[day1] if day1 in df_perf.index else df_perf.iloc[-1]
    assert row_day1["Equity"] == 660.0
    assert row_day1["Total NAV"] == 1660.0
    # Expected return = (1660 / 1600) - 1 = 3.75%
    expected_twr = 100.0 * (1660.0 / 1600.0)
    assert pytest.approx(row_day1["TWR_Index"], abs=0.01) == expected_twr

def test_twr_internal_trade_neutrality():
    # Buying shares with cash is a cash-for-equity swap. NAV and TWR must be unchanged.
    day0 = pd.Timestamp("2024-01-01")
    day1 = pd.Timestamp("2024-01-02")
    date_range = pd.date_range(day0, day1)
    
    df_prices = pd.DataFrame({"VUSA.L": [60.0, 60.0]}, index=date_range)
    
    # Buy 5 shares @ 60.0 on Day 1 (-£300 cash, +5 shares)
    ledger = pd.DataFrame([
        {
            "Date": day1,
            "Action": "Buy",
            "Qty": 5.0,
            "Net Amount": -300.0,
            "Auto Ticker": "VUSA.L"
        }
    ])
    
    df_perf, positions, final_cash = calculate_twr_series(
        df_parsed=ledger,
        df_prices=df_prices,
        snapshot_cash=1000.0,
        snapshot_quantities={"VUSA.L": 10.0}
    )
    
    row_day1 = df_perf.loc[day1] if day1 in df_perf.index else df_perf.iloc[-1]
    assert row_day1["Cash"] == 700.0
    assert row_day1["Equity"] == 900.0 # 15 shares * 60.0
    assert row_day1["Total NAV"] == 1600.0
    assert pytest.approx(row_day1["TWR_Index"], abs=0.001) == 100.0
    assert positions.get("VUSA.L") == 15.0

def test_twr_dividend_recognition():
    # Dividends are internal returns (retained in portfolio as cash), so they boost TWR.
    day0 = pd.Timestamp("2024-01-01")
    day1 = pd.Timestamp("2024-01-02")
    date_range = pd.date_range(day0, day1)
    
    df_prices = pd.DataFrame({"VUSA.L": [60.0, 60.0]}, index=date_range)
    
    # Receive £32 cash dividend on Day 1 (+£32 cash)
    ledger = pd.DataFrame([
        {
            "Date": day1,
            "Action": "Dividend",
            "Qty": 0.0,
            "Net Amount": 32.0,
            "Auto Ticker": "VUSA.L"
        }
    ])
    
    df_perf, positions, final_cash = calculate_twr_series(
        df_parsed=ledger,
        df_prices=df_prices,
        snapshot_cash=1000.0,
        snapshot_quantities={"VUSA.L": 10.0}
    )
    
    row_day1 = df_perf.loc[day1] if day1 in df_perf.index else df_perf.iloc[-1]
    assert row_day1["Cash"] == 1032.0
    assert row_day1["Total NAV"] == 1632.0
    # Expected return = (1632 / 1600) - 1 = +2.0%
    expected_twr = 100.0 * (1632.0 / 1600.0)
    assert pytest.approx(row_day1["TWR_Index"], abs=0.01) == expected_twr


def test_weekday_volatility_not_diluted_by_weekends():
    # Verify that filtering a calendar-day series (freq='D' with 0.0 weekend returns)
    # to weekdays (dayofweek < 5) preserves true 252-day annualized volatility.
    cal_dates = pd.date_range("2024-01-01", "2024-12-31", freq="D")
    rng = np.random.default_rng(42)
    daily_rets = pd.Series(0.0, index=cal_dates)
    is_weekday = cal_dates.dayofweek < 5
    true_weekday_rets = rng.normal(0.0005, 0.01, size=int(is_weekday.sum()))
    daily_rets.loc[is_weekday] = true_weekday_rets

    expected_ann_vol = float(pd.Series(true_weekday_rets).std() * np.sqrt(252))
    diluted_ann_vol = float(daily_rets.std() * np.sqrt(252))
    filtered_ann_vol = float(daily_rets[daily_rets.index.dayofweek < 5].std() * np.sqrt(252))

    assert pytest.approx(filtered_ann_vol, rel=1e-9) == expected_ann_vol
    assert diluted_ann_vol < expected_ann_vol * 0.90

