"""
Export year-end portfolio value attribution to Excel.

The report uses the cached daily engine output in data/portfolio_history.db:

* total_nav_gbp / equity_gbp / cash_gbp give the portfolio value at each
  period end.
* net_invested is the engine's cumulative external-capital series. Its
  period change is therefore payments/transfers.
* performance_delta is the residual NAV movement after external flows:
      end_nav - start_nav - net_payments_transfers

Dividends, interest, fees, buys and sells are intentionally included in
performance_delta because the existing performance engine treats them as
internal account events rather than external cashflows.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Iterable

import pandas as pd
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter


DEFAULT_DB = Path("data") / "portfolio_history.db"
DEFAULT_OUTPUT_DIR = Path("outputs")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export year-end NAV attribution for one or more accounts."
    )
    parser.add_argument(
        "--account",
        default="ISA",
        help="Account to export, or 'all'. Default: ISA.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help=f"SQLite database path. Default: {DEFAULT_DB}",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output .xlsx path. Defaults to outputs/year_end_attribution_<account>.xlsx.",
    )
    parser.add_argument(
        "--no-current",
        action="store_true",
        help="Only include 31 Dec period ends; omit the current incomplete year.",
    )
    return parser.parse_args()


def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    return sqlite3.connect(db_path)


def available_accounts(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "select distinct account from portfolio_snapshots order by account"
    ).fetchall()
    return [row[0] for row in rows]


def load_snapshots(conn: sqlite3.Connection, account: str) -> pd.DataFrame:
    df = pd.read_sql_query(
        """
        select
            account,
            date,
            equity_gbp,
            cash_gbp,
            total_nav_gbp,
            twr_index,
            net_invested,
            daily_return,
            bench_nav,
            run_timestamp
        from portfolio_snapshots
        where account = ?
        order by date
        """,
        conn,
        params=[account],
        parse_dates=["date"],
    )
    if df.empty:
        raise ValueError(f"No portfolio snapshots found for account '{account}'.")

    numeric_cols = [
        "equity_gbp",
        "cash_gbp",
        "total_nav_gbp",
        "twr_index",
        "net_invested",
        "daily_return",
        "bench_nav",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.sort_values("date").reset_index(drop=True)


def endpoint_rows(df: pd.DataFrame, include_current: bool) -> pd.DataFrame:
    year_ends = df[(df["date"].dt.month == 12) & (df["date"].dt.day == 31)].copy()
    latest = df.tail(1).copy()

    if include_current and not latest.empty:
        latest_date = latest.iloc[0]["date"]
        if not (latest_date.month == 12 and latest_date.day == 31):
            year_ends = pd.concat([year_ends, latest], ignore_index=True)

    first_date = df.iloc[0]["date"]
    year_ends = year_ends[year_ends["date"] > first_date]
    return year_ends.sort_values("date").reset_index(drop=True)


def build_attribution(df: pd.DataFrame, include_current: bool) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    endpoints = endpoint_rows(df, include_current=include_current)
    opening = df.iloc[0]

    period_rows = []
    value_rows = []
    prior = opening

    opening_value = {
        "account": opening["account"],
        "year": opening["date"].year,
        "period_end": opening["date"].date(),
        "is_opening_row": True,
        "equity_gbp": opening["equity_gbp"],
        "cash_gbp": opening["cash_gbp"],
        "total_nav_gbp": opening["total_nav_gbp"],
        "net_invested": opening["net_invested"],
        "twr_index": opening["twr_index"],
    }
    value_rows.append(opening_value)

    for _, end in endpoints.iterrows():
        start_nav = float(prior["total_nav_gbp"])
        end_nav = float(end["total_nav_gbp"])
        net_payments = float(end["net_invested"] - prior["net_invested"])
        total_delta = end_nav - start_nav
        performance_delta = total_delta - net_payments

        start_twr = float(prior["twr_index"])
        end_twr = float(end["twr_index"])
        twr_return = (end_twr / start_twr - 1.0) if start_twr else None

        is_calendar_year_end = end["date"].month == 12 and end["date"].day == 31
        period_label = str(end["date"].year) if is_calendar_year_end else f"{end['date'].year} YTD"

        period_rows.append(
            {
                "account": end["account"],
                "period": period_label,
                "period_start": prior["date"].date(),
                "period_end": end["date"].date(),
                "start_nav_gbp": start_nav,
                "end_equity_gbp": float(end["equity_gbp"]),
                "end_cash_gbp": float(end["cash_gbp"]),
                "end_nav_gbp": end_nav,
                "total_nav_delta_gbp": total_delta,
                "net_payments_transfers_gbp": net_payments,
                "performance_delta_gbp": performance_delta,
                "twr_return": twr_return,
                "start_twr_index": start_twr,
                "end_twr_index": end_twr,
                "ending_net_invested_gbp": float(end["net_invested"]),
            }
        )

        value_rows.append(
            {
                "account": end["account"],
                "year": end["date"].year,
                "period_end": end["date"].date(),
                "is_opening_row": False,
                "equity_gbp": float(end["equity_gbp"]),
                "cash_gbp": float(end["cash_gbp"]),
                "total_nav_gbp": end_nav,
                "net_invested": float(end["net_invested"]),
                "twr_index": end_twr,
            }
        )
        prior = end

    daily = df[["account", "date", "net_invested", "total_nav_gbp"]].copy()
    daily["external_cashflow_gbp"] = daily["net_invested"].diff().fillna(0.0)
    daily_flows = daily[daily["external_cashflow_gbp"].abs() > 0.005].copy()
    daily_flows["date"] = daily_flows["date"].dt.date
    daily_flows = daily_flows[
        ["account", "date", "external_cashflow_gbp", "net_invested", "total_nav_gbp"]
    ]

    return (
        pd.DataFrame(period_rows),
        pd.DataFrame(value_rows),
        daily_flows.reset_index(drop=True),
    )


def methodology_rows(accounts: Iterable[str], include_current: bool, db_path: Path) -> pd.DataFrame:
    current_note = (
        "Includes latest available snapshot as a YTD period when it is not 31 Dec."
        if include_current
        else "Only includes completed 31 Dec calendar-year periods."
    )
    return pd.DataFrame(
        [
            ["Source", str(db_path)],
            ["Accounts", ", ".join(accounts)],
            ["Period ends", current_note],
            ["Year-end value", "portfolio_snapshots.total_nav_gbp at 31 Dec."],
            ["Payments/transfers", "Change in portfolio_snapshots.net_invested over the period."],
            ["Performance delta", "End NAV - start NAV - payments/transfers."],
            [
                "Internal events",
                "Dividends, interest, fees, buys and sells remain in performance_delta_gbp.",
            ],
            ["TWR return", "end_twr_index / start_twr_index - 1."],
        ],
        columns=["item", "definition"],
    )


def default_output_path(account_arg: str) -> Path:
    suffix = "all" if account_arg.lower() == "all" else account_arg
    safe_suffix = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in suffix)
    return DEFAULT_OUTPUT_DIR / f"year_end_attribution_{safe_suffix}.xlsx"


def write_workbook(
    output_path: Path,
    summary: pd.DataFrame,
    values: pd.DataFrame,
    cashflows: pd.DataFrame,
    methodology: pd.DataFrame,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary.to_excel(writer, index=False, sheet_name="Attribution")
        values.to_excel(writer, index=False, sheet_name="Year End Values")
        cashflows.to_excel(writer, index=False, sheet_name="Cashflows")
        methodology.to_excel(writer, index=False, sheet_name="Methodology")

        workbook = writer.book
        for sheet in workbook.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            style_sheet(sheet)

        apply_number_formats(workbook["Attribution"])
        apply_number_formats(workbook["Year End Values"])
        apply_number_formats(workbook["Cashflows"])


def style_sheet(sheet) -> None:
    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font

    for col_idx, column_cells in enumerate(sheet.columns, start=1):
        max_len = 0
        for cell in column_cells:
            if cell.value is not None:
                max_len = max(max_len, len(str(cell.value)))
        sheet.column_dimensions[get_column_letter(col_idx)].width = min(max(max_len + 2, 12), 34)


def apply_number_formats(sheet) -> None:
    percent_headers = {"twr_return", "daily_return"}
    money_markers = ("gbp", "nav", "cash", "equity", "invested")

    for cell in sheet[1]:
        header = str(cell.value).lower() if cell.value is not None else ""
        if header in percent_headers:
            number_format = "0.00%"
        elif any(marker in header for marker in money_markers):
            number_format = '#,##0.00;[Red]-#,##0.00'
        else:
            number_format = None

        if number_format:
            for row_cell in sheet.iter_cols(
                min_col=cell.column,
                max_col=cell.column,
                min_row=2,
                max_row=sheet.max_row,
            ):
                for value_cell in row_cell:
                    value_cell.number_format = number_format


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    include_current = not args.no_current

    with connect(db_path) as conn:
        accounts = available_accounts(conn)
        if args.account.lower() == "all":
            selected_accounts = accounts
        else:
            selected_accounts = [args.account]

        missing = [account for account in selected_accounts if account not in accounts]
        if missing:
            raise ValueError(
                f"Account(s) not found: {', '.join(missing)}. "
                f"Available accounts: {', '.join(accounts)}"
            )

        summary_parts = []
        value_parts = []
        cashflow_parts = []
        for account in selected_accounts:
            snapshots = load_snapshots(conn, account)
            summary, values, cashflows = build_attribution(
                snapshots, include_current=include_current
            )
            summary_parts.append(summary)
            value_parts.append(values)
            cashflow_parts.append(cashflows)

    summary_df = pd.concat(summary_parts, ignore_index=True) if summary_parts else pd.DataFrame()
    values_df = pd.concat(value_parts, ignore_index=True) if value_parts else pd.DataFrame()
    cashflows_df = pd.concat(cashflow_parts, ignore_index=True) if cashflow_parts else pd.DataFrame()
    methodology_df = methodology_rows(selected_accounts, include_current, db_path)

    output_path = Path(args.output) if args.output else default_output_path(args.account)
    write_workbook(output_path, summary_df, values_df, cashflows_df, methodology_df)
    print(f"Wrote {output_path.resolve()}")


if __name__ == "__main__":
    main()
