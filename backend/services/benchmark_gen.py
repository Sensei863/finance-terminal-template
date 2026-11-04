import pandas as pd
import numpy as np
import yfinance as yf
from backend.services.data_handler import SNAPSHOT_DATE
from backend.services import currency_utils

class BenchmarkSimulator:
    """
    Generates a synthetic transaction ledger for a benchmark portfolio based on
    specified tickers, weights, and a rebalancing frequency.
    """
    def __init__(
        self,
        tickers_and_weights: dict,
        currency_map: dict,
        initial_capital: float,
        start_date: pd.Timestamp = None,
        rebalance_freq: str = 'Q',
        target_currency: str = 'GBP'
    ):
        self.tickers_and_weights = tickers_and_weights
        self.currency_map = currency_map
        self.initial_capital = initial_capital
        self.start_date = start_date if start_date is not None else SNAPSHOT_DATE
        self.rebalance_freq = rebalance_freq
        self.target_currency = target_currency
        self.tickers = list(self.tickers_and_weights.keys())
        self._fx_series = {}

    def _get_rebalance_dates(self, price_index: pd.DatetimeIndex) -> set:
        """Computes a set of rebalance dates based on the frequency."""
        start = price_index[0]
        end = price_index[-1]

        if self.rebalance_freq == 'None':
            return set()

        offset_map = {
            'Q': 'BQE-DEC',
            'A': 'BYE-DEC',
        }

        if self.rebalance_freq in offset_map:
            dates = pd.date_range(start=start, end=end, freq=offset_map[self.rebalance_freq])
            return set(dates.normalize())

        elif self.rebalance_freq == 'SA':
            all_month_ends = pd.date_range(start=start, end=end, freq='BME')
            return {d.normalize() for d in all_month_ends if d.month in [6, 12]}

        return set()

    def generate(self, prefetched_prices: pd.DataFrame = None) -> tuple[pd.DataFrame, dict]:
        """
        Generates a synthetic transaction ledger for the benchmark.

        Returns
        ───────
        df_ledger  : pd.DataFrame  — synthetic transaction ledger
        gbp_prices : dict          — {ticker: pd.Series} GBP-corrected price
                                     histories, ready to pass as bm_prices to
                                     calculate_twr_series (avoids a second raw
                                     yfinance fetch that would reintroduce the
                                     pence/GBP mismatch bug).
        """

        # A. Price Fetching
        currencies_needed = set(self.currency_map.values())
        fx_tickers = []
        
        # If any asset isn't in target_currency, we need FX
        for asset_ccy in currencies_needed:
            if asset_ccy != self.target_currency:
                # We need a cross to target_currency
                # Common pairs for yfinance: EURGBP=X, USDEUR=X, etc.
                # Simplest to always go through USD or direct if available.
                if asset_ccy == 'GBP' and self.target_currency == 'EUR':
                    fx_tickers.append("GBPEUR=X")
                elif asset_ccy == 'EUR' and self.target_currency == 'GBP':
                    fx_tickers.append("GBPEUR=X") # We'll invert later if needed
                elif asset_ccy == 'USD' and self.target_currency == 'EUR':
                    fx_tickers.append("EURUSD=X") # We'll invert
                elif asset_ccy == 'EUR' and self.target_currency == 'USD':
                    fx_tickers.append("EURUSD=X")
                elif asset_ccy == 'USD' and self.target_currency == 'GBP':
                    fx_tickers.append("GBPUSD=X")
                elif asset_ccy == 'GBP' and self.target_currency == 'USD':
                    fx_tickers.append("GBPUSD=X")

        all_tickers_to_fetch = self.tickers + list(set(fx_tickers))
        today = pd.Timestamp.today().normalize()

        prices = None
        if prefetched_prices is not None and not prefetched_prices.empty:
            # Check if all needed tickers are in the prefetched prices columns
            if all(t in prefetched_prices.columns for t in all_tickers_to_fetch):
                prices = prefetched_prices[all_tickers_to_fetch].ffill().bfill()
                prices.index = pd.to_datetime(prices.index)
                prices = prices.sort_index()

        if prices is None:
            raw_prices = yf.download(
                all_tickers_to_fetch,
                start=self.start_date,
                end=today,
                auto_adjust=True,
                threads=False
            )

            if raw_prices.empty:
                raise ValueError("yfinance returned no data for any requested tickers.")

            prices = raw_prices['Close'] if isinstance(raw_prices.columns, pd.MultiIndex) else raw_prices[['Close']]
            if len(all_tickers_to_fetch) == 1 and not isinstance(prices.columns, pd.MultiIndex):
                prices.columns = all_tickers_to_fetch

            prices = prices.ffill().bfill()

        for ticker in self.tickers:
            if ticker not in prices.columns or prices[ticker].isna().all():
                raise ValueError(f"No price data returned for {ticker} — check ticker symbol.")

        # B. Currency Conversion to Target Currency
        target_prices = {}
        union_index = prices.index

        # Cache FX rates (and handle inversions)
        def get_fx(pair_name):
            if pair_name in prices.columns:
                return prices[pair_name].reindex(union_index).ffill()
            return None

        # Simplified conversion: convert everything to target_currency
        for ticker in self.tickers:
            series = prices[ticker].dropna()
            asset_ccy = self.currency_map.get(ticker, 'GBP')

            if asset_ccy == self.target_currency:
                # Same currency — just check for pence/GBX quirk
                if asset_ccy == 'GBP': series = currency_utils.normalize_series(ticker, series)
                target_prices[ticker] = series
            else:
                # Need conversion
                fx_series = None
                pair = f"{asset_ccy}{self.target_currency}=X"
                inv_pair = f"{self.target_currency}{asset_ccy}=X"
                
                # Try direct
                if pair in prices.columns:
                    fx_series = prices[pair].reindex(union_index).ffill()
                elif inv_pair in prices.columns:
                    fx_series = 1.0 / prices[inv_pair].reindex(union_index).ffill()
                
                # Special cases for yfinance quirks (GBPEUR=X is standard, EURGBP=X is not always reliable)
                if fx_series is None:
                    if asset_ccy == 'GBP' and self.target_currency == 'EUR':
                        fx_series = get_fx('GBPEUR=X')
                    elif asset_ccy == 'EUR' and self.target_currency == 'GBP':
                        fx_series = 1.0 / get_fx('GBPEUR=X') if get_fx('GBPEUR=X') is not None else None
                
                if fx_series is None:
                    raise ValueError(f"Could not find FX rate to convert {asset_ccy} to {self.target_currency} for {ticker}")
                
                aligned_asset, aligned_fx = series.align(fx_series, join='inner')
                # If target is GBP, handle the pence quirk BEFORE conversion if asset is GBP
                if asset_ccy == 'GBP':
                    aligned_asset = currency_utils.normalize_series(ticker, aligned_asset)
                
                target_prices[ticker] = (aligned_asset * aligned_fx).dropna()

        # C. Day-0 Initialisation
        common_price_index = None
        for ticker in self.tickers:
            common_price_index = target_prices[ticker].index if common_price_index is None else common_price_index.intersection(target_prices[ticker].index)
        if common_price_index is None or common_price_index.empty: raise ValueError("No common trading days found for the selected assets after the start date.")

        t0 = common_price_index[0]
        ledger = []
        holdings = {ticker: 0.0 for ticker in self.tickers}

        for ticker, weight in self.tickers_and_weights.items():
            price_t0 = target_prices[ticker].loc[t0]
            if price_t0 <= 0: raise ValueError(f"Initial price for {ticker} on {t0.date()} is zero or negative.")
            qty = (self.initial_capital * weight) / price_t0
            holdings[ticker] = qty
            ledger.append({"Date": t0, "Action": "Buy", "Ticker": ticker, "Qty": qty, "Price": price_t0, "Net Amount": -1 * (qty * price_t0)})

        # D/E. Rebalancing
        rebalance_dates = self._get_rebalance_dates(common_price_index)
        for date in common_price_index[1:]:
            if date in rebalance_dates:
                try:
                    total_nav = sum(holdings[t] * target_prices[t].loc[date] for t in self.tickers)
                except KeyError: continue
                if total_nav <= 0: continue

                for ticker, weight in self.tickers_and_weights.items():
                    price_today = target_prices[ticker].loc[date]
                    if price_today <= 0: continue

                    target_value = total_nav * weight
                    current_value = holdings[ticker] * price_today
                    delta_value = target_value - current_value

                    if abs(delta_value) < 1.0: continue

                    qty_delta = abs(delta_value) / price_today
                    if delta_value > 0:
                        action, net_amount = "Buy", -abs(delta_value)
                        holdings[ticker] += qty_delta
                    else:
                        action, net_amount = "Sell", abs(delta_value)
                        holdings[ticker] -= qty_delta

                    ledger.append({"Date": date, "Action": action, "Ticker": ticker, "Qty": qty_delta, "Price": price_today, "Net Amount": net_amount})

        # F. Output Schema
        if not ledger:
            empty_df = pd.DataFrame(columns=["Date", "Action", "Ticker", "Qty", "Price", "Net Amount", "Asset Name", "Auto Ticker"])
            return empty_df, {}

        df_ledger = pd.DataFrame(ledger)
        df_ledger["Asset Name"] = df_ledger["Ticker"]
        df_ledger["Auto Ticker"] = df_ledger["Ticker"]

        df_ledger['Date'] = pd.to_datetime(df_ledger['Date'])
        for col in ['Qty', 'Price', 'Net Amount']:
            df_ledger[col] = df_ledger[col].astype(float)

        return df_ledger, target_prices
