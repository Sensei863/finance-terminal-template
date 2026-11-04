import pandas as pd
import numpy as np

from backend.services.engine import build_trade_anchored_prices, PRICE_DEVIATION_TOLERANCE
from backend.services.data_handler import SNAPSHOT_DATE


def calculate_twr_series(
    df_parsed: pd.DataFrame,
    df_prices: pd.DataFrame,
    df_ticker_map: pd.DataFrame = None,
    initial_cash: float = 0.0,
    snapshot_cash: float = 0.0,
    snapshot_quantities: dict = None,
    return_prices: bool = False,
):
    """
    Core Performance Engine — Deterministic Snapshot Model.

    Architecture overview
    ─────────────────────
    The engine no longer back-solves for historical holdings.  Instead:

      1.  ``snapshot_cash`` and ``snapshot_quantities`` (from
          ``data_handler.load_start_snapshot()``) are injected directly into
          the opening state on ``SNAPSHOT_DATE`` (2017-08-26).

      2.  Only ledger rows AFTER the snapshot date are processed (the caller,
          ``data_handler.get_sanitized_ledger()``, already strips earlier rows).

      3.  ``TWR_Index`` is pinned to 100.0 on the snapshot date.  The snapshot
          NAV becomes ``prev_nav`` without any compounding, so no artificial
          gain or loss is recorded on the opening day.

    Removed from the legacy version
    ─────────────────────────────────
    •   "Legacy Shares (Pre-2017)" ghost-ticker injection — the entire block
        that read ``df_ticker_map["Legacy Shares (Pre-2017)"]`` and priced
        those shares at ``df_prices[t].iloc[0]`` has been deleted.  It was
        the primary cause of the £17k NAV discrepancy because ``iloc[0]``
        was whatever stale price happened to be at the start of the grid.

    Parameters
    ──────────
    df_parsed : pd.DataFrame
        Ledger rows after the snapshot date only.
    df_prices : pd.DataFrame
        Price grid from ``fetch_portfolio_history_and_currency``.  Must cover
        from SNAPSHOT_DATE to today.
    df_ticker_map : pd.DataFrame, optional
        Manual ticker overrides — consumed by the price-anchoring engine only.
    initial_cash : float
        Extra sidebar cash (pre-2017 cash NOT already in the snapshot).
        Normally 0.0 for ISA accounts.
    snapshot_cash : float
        Cash balance from ``Start_Portfolio_ISA`` (e.g. £669.06).
    snapshot_quantities : dict, optional
        {yahoo_ticker: quantity} from ``Start_Portfolio_ISA``.

    Returns
    ───────
    df_perf : pd.DataFrame
        Daily index (Date) with columns:
        Equity, Cash, Total NAV, TWR_Index, Net_Invested,
        Daily_Return, Year.
    positions : dict
        Final {ticker: shares} state at end of date_range.
    cash : float
        Final cash balance.
    df_prices : pd.DataFrame, optional
        Returned only when return_prices=True. This is the post-repair price
        grid after trade anchoring, interpolation, spike filtering and smoothing.
    """

    NAV_NEUTRALITY_TOLERANCE = 0.02   # 2 % of NAV

    if snapshot_quantities is None:
        snapshot_quantities = {}

    # ------------------------------------------------------------------
    # 1. Universe of tickers
    # ------------------------------------------------------------------
    ledger_tickers = (
        df_parsed["Auto Ticker"].dropna().astype(str).str.strip().tolist()
        if not df_parsed.empty else []
    )
    map_tickers: list = []
    if (
        df_ticker_map is not None
        and not df_ticker_map.empty
        and "Ticker" in df_ticker_map.columns
    ):
        map_tickers = (
            df_ticker_map["Ticker"].dropna().astype(str).str.strip().tolist()
        )
    snapshot_tickers = list(snapshot_quantities.keys())

    unique_tickers = list(set(ledger_tickers + map_tickers + snapshot_tickers))
    unique_tickers = [t for t in unique_tickers if t and t.lower() != "nan"]

    # ------------------------------------------------------------------
    # 2. Date range — anchored to SNAPSHOT_DATE
    # ------------------------------------------------------------------
    # If there's a snapshot (cash or shares), the history MUST start from the
    # snapshot date to value the opening state.
    start_date_for_loop = SNAPSHOT_DATE
    if not snapshot_quantities and (snapshot_cash is None or snapshot_cash < 0.01):
        if not df_parsed.empty and "Date" in df_parsed.columns and not df_parsed['Date'].empty:
            min_date = df_parsed['Date'].min()
            if pd.notna(min_date):
                start_date_for_loop = min_date

    date_range = pd.date_range(
        start=start_date_for_loop, end=pd.Timestamp.today().normalize()
    )

    if not df_prices.empty:
        df_prices = df_prices.reindex(date_range).ffill().bfill()

    # ------------------------------------------------------------------
    # 3. Price safety net: trade-ledger anchoring & FX-ghost correction
    # ------------------------------------------------------------------
    if not df_prices.empty:
        df_prices = build_trade_anchored_prices(
            df_prices=df_prices,
            df_parsed=df_parsed,
            df_ticker_map=df_ticker_map,
            date_range=date_range,
        )

    # ------------------------------------------------------------------
    # 4. Initialise state from the snapshot ("Big Bang")
    #
    #    positions            — loaded from Start_Portfolio_ISA directly
    #    cash                 — snapshot_cash + optional sidebar override
    #    net_invested_capital — set on Day-0 to the full opening NAV so
    #                           TWR starts at exactly 100.0
    #    twr_index            — 100.0 always
    #    prev_nav             — None flags "snapshot day not yet seen"
    # ------------------------------------------------------------------
    positions: dict = {t: 0.0 for t in unique_tickers}

    for ticker, qty in snapshot_quantities.items():
        if qty > 0.0:
            positions[ticker] = positions.get(ticker, 0.0) + qty

    cash: float = snapshot_cash + initial_cash
    net_invested_capital: float = 0.0   # set properly on Day-0 (see loop)
    twr_index: float = 100.0
    prev_nav = None    # None → "snapshot day not yet processed"

    # ------------------------------------------------------------------
    # 5. Pre-compute per-(ticker, date) ledger-implied prices for the
    #    NAV-neutrality guard inside the loop.
    # ------------------------------------------------------------------
    df_parsed_copy = df_parsed.copy() if not df_parsed.empty else pd.DataFrame()

    if not df_parsed_copy.empty:
        df_parsed_copy["NormalizedDate"] = pd.to_datetime(
            df_parsed_copy["Date"]
        ).dt.normalize()
        try:
            tx_by_date = df_parsed_copy.groupby("NormalizedDate")
        except Exception:
            tx_by_date = None
    else:
        tx_by_date = None

    ledger_implied: dict = {}
    if not df_parsed_copy.empty:
        for _, row in df_parsed_copy.iterrows():
            action = row.get("Action", "")
            if action not in ("Buy", "Sell", "Unparsed Sell (Check Diagnostics)"):
                continue
            t = str(row.get("Auto Ticker", "")).strip()
            if not t or t.lower() == "nan":
                continue
            qty = row.get("Qty", 0.0)
            net = row.get("Net Amount", 0.0)
            if qty > 0 and net != 0:
                ledger_implied[(t, row["NormalizedDate"])] = abs(net / qty)

    # ------------------------------------------------------------------
    # 6. Main TWR Loop
    # ------------------------------------------------------------------
    portfolio_history: list = []

    # OPTIMIZATION: Pre-convert df_prices to a nested dictionary for fast O(1) lookups
    prices_dict = {}
    if not df_prices.empty:
        prices_dict = {col: df_prices[col].to_dict() for col in df_prices.columns}

    for current_date in date_range:
        daily_cash_flow = 0.0
        todays_trades: list = []   # [(ticker, action, qty, net_amt, imp_price)]

        # ── Process daily ledger events ──────────────────────────────
        if (
            tx_by_date is not None
            and hasattr(tx_by_date, "groups")
            and current_date in tx_by_date.groups
        ):
            day_txs = tx_by_date.get_group(current_date)
            for _, row in day_txs.iterrows():
                action  = row["Action"]
                t = (
                    str(row["Auto Ticker"]).strip()
                    if pd.notna(row["Auto Ticker"])
                    else ""
                )
                if t.lower() == "nan":
                    t = ""
                qty     = row["Qty"]
                net_amt = row["Net Amount"]

                cash += net_amt

                # Only external transfers move the TWR denominator base.
                # Buys, Sells, Dividends, Fees, Interest are all internal.
                if action == "Transfer" or (
                    action not in (
                        "Buy",
                        "Sell",
                        "Unparsed Sell (Check Diagnostics)",
                        "Dividend",
                        "Fee",
                        "Interest",
                    )
                    and net_amt != 0
                ):
                    daily_cash_flow      += net_amt
                    net_invested_capital += net_amt

                if action == "Buy":
                    if t != "":
                        positions[t] = positions.get(t, 0.0) + qty
                        todays_trades.append(
                            (t, "Buy", qty, net_amt, ledger_implied.get((t, current_date)))
                        )
                elif action in ("Sell", "Unparsed Sell (Check Diagnostics)"):
                    if t != "":
                        positions[t] = max(0.0, positions.get(t, 0.0) - qty)
                        todays_trades.append(
                            (t, "Sell", qty, net_amt, ledger_implied.get((t, current_date)))
                        )

        # ── Mark-to-market (first pass with Stooq / anchored prices) ─
        equity_value  = 0.0
        ticker_equity: dict = {}   # {ticker: (shares, price, value)}

        for t, shares in positions.items():
            if shares > 0.01 and not df_prices.empty and t in df_prices.columns:
                # OPTIMIZED DICTIONARY LOOKUP (FAST)
                p = prices_dict[t].get(current_date, np.nan)

                # LEGACY PANDAS LOOKUP (SLOW) - Commented out for easy revertibility:
                # p = (
                #     df_prices.loc[current_date, t]
                #     if current_date in df_prices.index
                #     else np.nan
                # )

                if pd.notna(p):
                    val = shares * p
                    equity_value         += val
                    ticker_equity[t]      = (shares, p, val)

        total_nav = equity_value + cash

        # ── NAV-neutrality guard (last-resort safety net) ─────────────
        #
        # A Buy or Sell is a pure cash-for-equity swap: NAV must be unchanged.
        # If it deviates by more than NAV_NEUTRALITY_TOLERANCE, a price ghost
        # survived the anchoring pass — substitute the ledger-implied price.
        #
        # Mode 1: ticker has a known ledger-implied price → direct check.
        # Mode 2: no Auto Ticker → infer price from cash delta, scan all tickers.
        if prev_nav is not None and prev_nav > 0.01 and todays_trades:
            expected_nav  = prev_nav + daily_cash_flow
            nav_deviation = abs(total_nav - expected_nav) / prev_nav

            if nav_deviation > NAV_NEUTRALITY_TOLERANCE:
                corrected_equity   = equity_value
                correction_applied = False

                for (t, action, qty, net_amt, imp_price) in todays_trades:
                    if imp_price is None or imp_price <= 0:
                        continue
                    if t not in ticker_equity:
                        continue
                    shares, yahoo_price, yahoo_val = ticker_equity[t]
                    if abs(yahoo_price / imp_price - 1.0) > PRICE_DEVIATION_TOLERANCE:
                        corrected_equity -= yahoo_val
                        corrected_equity += shares * imp_price
                        correction_applied = True

                if not correction_applied:
                    for (t, action, qty, net_amt, imp_price) in todays_trades:
                        if imp_price is not None or qty <= 0 or net_amt == 0:
                            continue
                        inferred = abs(net_amt) / qty
                        if inferred <= 0:
                            continue
                        for cand, (shares, yp, yv) in ticker_equity.items():
                            if abs(yp / inferred - 1.0) > PRICE_DEVIATION_TOLERANCE:
                                corrected_equity   -= yv
                                corrected_equity   += shares * inferred
                                correction_applied  = True
                                break
                        if correction_applied:
                            break

                if correction_applied:
                    equity_value = corrected_equity
                    total_nav    = equity_value + cash
                    

        # ── TWR Compounding ───────────────────────────────────────────
        #
        # SNAPSHOT DAY (prev_nav is None):
        #   Set net_invested_capital = total_nav so the TWR denominator
        #   opens at the correct base.  Record TWR_Index = 100.0.
        #   Do NOT compound (continue to next date).
        #
        # All subsequent days:
        #   daily_twr = (NAV_end − external_flows) / NAV_start − 1
        #   Circuit-breaker: clamp to (−0.99, +1.5).
        #
        if prev_nav is None:
            net_invested_capital = total_nav   # anchor denominator to opening NAV
            prev_nav             = total_nav
            portfolio_history.append({
                "Date":         current_date,
                "Equity":       round(equity_value, 2),
                "Cash":         round(cash, 2),
                "Total NAV":    round(total_nav, 2),
                "TWR_Index":    round(twr_index, 4),
                "Net_Invested": round(net_invested_capital, 2),
                "Year":         current_date.year,
            })
            continue   # no compounding on snapshot day

        if prev_nav > 0.01:
            daily_twr  = max(
                min((total_nav - daily_cash_flow) / prev_nav - 1.0, 1.5), -0.99
            )
            twr_index *= 1.0 + daily_twr

        prev_nav = total_nav

        portfolio_history.append({
            "Date":         current_date,
            "Equity":       round(equity_value, 2),
            "Cash":         round(cash, 2),
            "Total NAV":    round(total_nav, 2),
            "TWR_Index":    round(twr_index, 4),
            "Net_Invested": round(net_invested_capital, 2),
            "Year":         current_date.year,
        })

    # ------------------------------------------------------------------
    # 7. Build output DataFrame
    # ------------------------------------------------------------------
    df_perf = pd.DataFrame(portfolio_history)
    if not df_perf.empty:
        df_perf.set_index("Date", inplace=True)
        df_perf["Daily_Return"] = df_perf["TWR_Index"].pct_change().fillna(0)

    if return_prices:
        return df_perf, positions, cash, df_prices
    return df_perf, positions, cash
