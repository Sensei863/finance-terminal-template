import pytest
import pandas as pd
from backend.services.currency_utils import normalize_price, normalize_series, normalize_ohlcv

def test_normalize_price_lse_pence():
    # LSE ticker quoted in GBp (pence) should be converted to GBP (pounds)
    p = normalize_price("VUSA.L", 6500.0, currency="GBp")
    assert p == 65.0

def test_normalize_price_lse_fake_gbp():
    # Handle yfinance quirk where pence is labeled as GBP
    p = normalize_price("VUSA.L", 6500.0, currency="GBP")
    assert p == 65.0

def test_normalize_price_lse_real_gbp():
    # Legitimate GBP price should not be scaled down
    p = normalize_price("IUSA.L", 60.0, currency="GBP")
    assert p == 60.0

def test_normalize_price_usd_ticker():
    # US tickers in USD should remain untouched
    p = normalize_price("AAPL", 150.0, currency="USD")
    assert p == 150.0

def test_normalize_price_heuristic_fallback():
    # If no currency tag is provided, heuristics detect GBp on .L ticker > 1000
    p = normalize_price("VUSA.L", 6500.0)
    assert p == 65.0

def test_normalize_series_gbp():
    s = pd.Series([6500.0, 6550.0, 6600.0])
    s_norm = normalize_series("VUSA.L", s)
    assert s_norm.iloc[-1] == 66.0
    assert s_norm.iloc[0] == 65.0

def test_normalize_series_with_anchor():
    s = pd.Series([6500.0, 6550.0, 6600.0])
    s_norm = normalize_series("VUSA.L", s, anchor=66.0)
    assert s_norm.iloc[-1] == 66.0

def test_normalize_series_non_gbp_base():
    # If account base currency is EUR, GBP normalization should not apply
    s_eur = pd.Series([6500.0, 6550.0, 6600.0])
    s_norm_eur = normalize_series("VUSA.L", s_eur, base_currency="EUR")
    assert s_norm_eur.iloc[-1] == 6600.0
