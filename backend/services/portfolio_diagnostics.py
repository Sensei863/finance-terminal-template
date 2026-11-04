"""
Ledger-only portfolio diagnostics (no price fetch).

Replay opening snapshot + Buys/Sells the same way as ``performance.calculate_twr_series``,
so you can inspect holdings on any historical date and see when a ticker first had shares.
"""

from __future__ import annotations

import pandas as pd

from backend.services.data_handler import (
    SNAPSHOT_DATE,
    apply_ticker_map,
    get_account_registry,
    get_sanitized_ledger,
    is_third_party_eur,
    get_ticker_map,
    load_start_snapshot,
)
from backend.services.engine import parse_transaction


def load_parsed_ledger_for_account(account_name: str) -> tuple[pd.DataFrame, bool, dict[str, float], pd.DataFrame]:
    """
    Load and parse the ledger for ``account_name`` using the same rules as the engine.

    Returns
    -------
    df_parsed, is_sipp, snapshot_quantities, df_raw
    """
    registry = get_account_registry()
    ticker_map = get_ticker_map()

    df_ledger, is_sipp, df_raw = get_sanitized_ledger(account_name)
    if df_ledger.empty:
        return pd.DataFrame(), is_sipp, {}, df_raw

    rich_cols = {"Net Amount", "Action", "Asset Name", "Qty", "Price", "Auto Ticker"}
    if rich_cols.issubset(set(df_ledger.columns)):
        df_parsed = df_ledger.copy()
        for col in ("Qty", "Price", "Net Amount"):
            if col in df_parsed.columns:
                df_parsed[col] = pd.to_numeric(df_parsed[col], errors="coerce").fillna(0.0)
        df_parsed["Auto Ticker"] = df_parsed["Auto Ticker"].fillna("").astype(str).str.strip()
    else:
        parsed_cols = df_ledger.apply(
            lambda r: parse_transaction(r, is_sipp=is_sipp), axis=1
        )
        parsed_cols.columns = [
            "Action",
            "Asset Name",
            "Qty",
            "Price",
            "Net Amount",
            "Auto Ticker",
        ]
        df_parsed = pd.concat(
            [df_ledger.reset_index(drop=True), parsed_cols.reset_index(drop=True)],
            axis=1,
        )

    df_parsed = apply_ticker_map(df_parsed, ticker_map)

    snap_qty: dict[str, float] = {}
    if not registry.empty:
        if is_third_party_eur(account_name, registry):
            snap_qty = {}
        elif account_name in ("ISA", "Consolidated"):
            try:
                _, snap_qty = load_start_snapshot()
            except Exception:
                snap_qty = {}
        else:
            snap_qty = {}

    return df_parsed, is_sipp, snap_qty, df_raw


def replay_equity_positions(
    df_parsed: pd.DataFrame,
    as_of: pd.Timestamp | str,
    snapshot_quantities: dict[str, float] | None = None,
) -> dict[str, float]:
    """
    Equity lots only: snapshot opening quantities plus all Buys/Sells on or before ``as_of``.

    Matches ``performance.calculate_twr_series`` position rules (no dividends/fees).
    """
    snapshot_quantities = snapshot_quantities or {}
    as_of = pd.Timestamp(as_of).normalize()

    positions: dict[str, float] = {}
    for t, q in snapshot_quantities.items():
        t = str(t).strip()
        if not t or t.lower() == "nan":
            continue
        try:
            fq = float(q)
        except (TypeError, ValueError):
            continue
        if fq > 0.0:
            positions[t] = fq

    if df_parsed.empty or "Date" not in df_parsed.columns:
        return positions

    df = df_parsed.copy()
    df["_d"] = pd.to_datetime(df["Date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["_d"])
    df = df[df["_d"] <= as_of].sort_values(["_d"]).reset_index(drop=True)

    for _, row in df.iterrows():
        action = str(row.get("Action", "") or "")
        raw_t = row.get("Auto Ticker", "")
        t = str(raw_t).strip() if pd.notna(raw_t) else ""
        if not t or t.lower() == "nan":
            continue
        try:
            qty = float(row.get("Qty", 0) or 0.0)
        except (TypeError, ValueError):
            qty = 0.0

        if action == "Buy" and qty > 0.0:
            positions[t] = positions.get(t, 0.0) + qty
        elif action in ("Sell", "Unparsed Sell (Check Diagnostics)") and qty > 0.0:
            positions[t] = max(0.0, positions.get(t, 0.0) - qty)

    return positions


def positions_as_of_table(
    df_parsed: pd.DataFrame,
    as_of: pd.Timestamp | str,
    snapshot_quantities: dict[str, float] | None = None,
    min_shares: float = 0.01,
) -> pd.DataFrame:
    """Return a sorted DataFrame: Ticker, Shares (for positions > min_shares)."""
    pos = replay_equity_positions(df_parsed, as_of, snapshot_quantities)
    rows = [(t, q) for t, q in sorted(pos.items()) if q > min_shares]
    if not rows:
        return pd.DataFrame(columns=["Ticker", "Shares"])
    return pd.DataFrame(rows, columns=["Ticker", "Shares"])


def first_nonzero_equity_date(
    df_parsed: pd.DataFrame,
    snapshot_quantities: dict[str, float] | None = None,
) -> pd.DataFrame:
    """
    For every ticker that ever has shares > 0.01, record the first calendar date that happens.

    Snapshot opening lines are attributed to ``SNAPSHOT_DATE`` (same convention as the engine).
    """
    snapshot_quantities = snapshot_quantities or {}
    first: dict[str, pd.Timestamp] = {}
    positions: dict[str, float] = {}

    for t, q in snapshot_quantities.items():
        t = str(t).strip()
        if not t or t.lower() == "nan":
            continue
        try:
            fq = float(q)
        except (TypeError, ValueError):
            continue
        if fq > 0.01:
            positions[t] = fq
            first[t] = pd.Timestamp(SNAPSHOT_DATE).normalize()

    if df_parsed.empty or "Date" not in df_parsed.columns:
        return _first_dates_to_df(first)

    df = df_parsed.copy()
    df["_d"] = pd.to_datetime(df["Date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["_d"]).sort_values(["_d"]).reset_index(drop=True)

    for _, row in df.iterrows():
        d = row["_d"]
        action = str(row.get("Action", "") or "")
        raw_t = row.get("Auto Ticker", "")
        t = str(raw_t).strip() if pd.notna(raw_t) else ""
        if not t or t.lower() == "nan":
            continue
        try:
            qty = float(row.get("Qty", 0) or 0.0)
        except (TypeError, ValueError):
            qty = 0.0

        prev = positions.get(t, 0.0)

        if action == "Buy" and qty > 0.0:
            positions[t] = prev + qty
        elif action in ("Sell", "Unparsed Sell (Check Diagnostics)") and qty > 0.0:
            positions[t] = max(0.0, prev - qty)
        else:
            continue

        new = positions.get(t, 0.0)
        if new > 0.01 and t not in first:
            first[t] = d

    return _first_dates_to_df(first)


def _first_dates_to_df(first: dict[str, pd.Timestamp]) -> pd.DataFrame:
    if not first:
        return pd.DataFrame(columns=["Ticker", "First date with position"])
    df = pd.DataFrame(
        [(t, first[t]) for t in sorted(first.keys())],
        columns=["Ticker", "First date with position"],
    )
    df["First date with position"] = pd.to_datetime(
        df["First date with position"]
    ).dt.strftime("%Y-%m-%d")
    return df


def ledger_rows_for_ticker(
    df_parsed: pd.DataFrame,
    ticker: str,
    max_rows: int = 500,
) -> pd.DataFrame:
    """All Buy/Sell rows mentioning ``ticker`` (after ticker map), newest last."""
    if df_parsed.empty or not ticker:
        return pd.DataFrame()
    t = str(ticker).strip().upper()
    mask = df_parsed["Auto Ticker"].astype(str).str.strip().str.upper() == t
    sub = df_parsed.loc[mask].copy()
    if sub.empty:
        return pd.DataFrame()
    cols = [c for c in ["Date", "Action", "Asset Name", "Qty", "Net Amount", "Auto Ticker"] if c in sub.columns]
    sub = sub[cols].tail(max_rows)
    return sub
