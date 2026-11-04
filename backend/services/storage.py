import os
import json
import logging
from datetime import datetime, timezone
from functools import wraps

import pandas as pd
import numpy as np

from backend.services.database import get_app_connection
import psycopg2.extras

log = logging.getLogger(__name__)

def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return None if np.isnan(f) or np.isinf(f) else f
    except (TypeError, ValueError):
        return None

def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()

from pathlib import Path

def init_db() -> None:
    """Initialize app_db schemas by idempotently applying migration scripts."""
    migrations_dir = Path(__file__).resolve().parent.parent.parent / "migrations" / "app_db"
    if not migrations_dir.exists():
        return
    sql_files = sorted(migrations_dir.glob("*.sql"))
    if not sql_files:
        return
    try:
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                for sql_file in sql_files:
                    try:
                        sql_content = sql_file.read_text(encoding="utf-8")
                        cur.execute(sql_content)
                    except Exception as e:
                        log.warning(f"Error applying migration {sql_file.name}: {e}")
            conn.commit()
            log.info("App database schemas verified and up-to-date.")
    except Exception as e:
        log.warning(f"init_db could not connect to app database: {e}")

def save_engine_audit(account: str, audit_data: dict) -> None:
    serializable = {}
    for k, v in audit_data.items():
        if isinstance(v, pd.DataFrame):
            serializable[k] = {"_type": "df", "data": v.to_dict(orient="records")}
        elif isinstance(v, pd.Series):
             serializable[k] = {"_type": "series", "data": v.to_dict()}
        else:
            serializable[k] = v

    try:
        json_str = json.dumps(serializable, default=str)
    except Exception as e:
        log.error(f"Failed to serialize engine audit for {account}: {e}")
        return

    with get_app_connection() as conn:
        with conn.cursor() as cur:
            sql = """
                INSERT INTO engine_audit (account, audit_json) VALUES (%s, %s)
                ON CONFLICT (account) DO UPDATE SET audit_json=EXCLUDED.audit_json
            """
            cur.execute(sql, (account, json_str))
        conn.commit()

def load_engine_audit(account: str) -> dict | None:
    with get_app_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT audit_json FROM engine_audit WHERE account = %s", (account,))
            row = cur.fetchone()
            if not row:
                return None
            try:
                raw_dict = json.loads(row["audit_json"])
                audit_data = {}
                for k, v in raw_dict.items():
                    if isinstance(v, dict) and v.get("_type") == "df":
                        audit_data[k] = pd.DataFrame(v["data"])
                    elif isinstance(v, dict) and v.get("_type") == "series":
                        audit_data[k] = pd.Series(v["data"])
                    else:
                        audit_data[k] = v
                return audit_data
            except Exception as e:
                log.error(f"Failed to deserialize engine audit for {account}: {e}")
                return None

def save_portfolio_run(account: str, df_perf: pd.DataFrame, positions: dict, df_prices: pd.DataFrame) -> int:
    if df_perf is None or df_perf.empty:
        log.warning("save_portfolio_run: df_perf is empty — nothing saved.")
        return 0

    ts = _now_utc()

    snap_rows = []
    for date_idx, row in df_perf.iterrows():
        snap_rows.append((
            account,
            pd.Timestamp(date_idx).strftime("%Y-%m-%d"),
            _safe_float(row.get("Equity", row.get("Equity (£)"))),
            _safe_float(row.get("Cash", row.get("Cash (£)"))),
            _safe_float(row.get("Total NAV", row.get("Total NAV (£)"))),
            _safe_float(row.get("TWR_Index")),
            _safe_float(row.get("Net_Invested")),
            _safe_float(row.get("Daily_Return")),
            _safe_float(row.get("Bench_NAV")),
            ts,
        ))

    ticker_rows = []
    price_tickers = list(df_prices.columns) if df_prices is not None and not df_prices.empty else []
    price_dict = df_prices.to_dict(orient="index") if df_prices is not None and not df_prices.empty else {}
    for date_idx, perf_row in df_perf.iterrows():
        date_str  = pd.Timestamp(date_idx).strftime("%Y-%m-%d")
        total_nav = _safe_float(perf_row.get("Total NAV", perf_row.get("Total NAV (£)"))) or 0.0
        day_prices = price_dict.get(date_idx, {})

        for ticker in price_tickers:
            shares = positions.get(ticker, 0.0)
            price = None
            if ticker in day_prices:
                ts_price = day_prices[ticker]
                price = _safe_float(ts_price)

            active_shares = shares if shares is not None and shares > 0.001 else None
            value  = (active_shares * price) if (active_shares is not None and price is not None) else None
            weight = (value / total_nav) if (value is not None and total_nav > 0) else None

            ticker_rows.append((
                account, date_str, ticker,
                _safe_float(active_shares), price, _safe_float(value), _safe_float(weight),
                ts,
            ))

    try:
        from psycopg2.extras import execute_values
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                if snap_rows:
                    sql_snap = """
                        INSERT INTO portfolio_snapshots
                           (account, date, equity_gbp, cash_gbp, total_nav_gbp,
                            twr_index, net_invested, daily_return, bench_nav, run_timestamp)
                           VALUES %s
                        ON CONFLICT (account, date) DO UPDATE SET
                           equity_gbp=EXCLUDED.equity_gbp, cash_gbp=EXCLUDED.cash_gbp,
                           total_nav_gbp=EXCLUDED.total_nav_gbp, twr_index=EXCLUDED.twr_index,
                           net_invested=EXCLUDED.net_invested, daily_return=EXCLUDED.daily_return,
                           bench_nav=EXCLUDED.bench_nav, run_timestamp=EXCLUDED.run_timestamp
                    """
                    execute_values(cur, sql_snap, snap_rows, page_size=1000)
                
                if ticker_rows:
                    sql_ticker = """
                        INSERT INTO portfolio_ticker_daily
                           (account, date, ticker, shares, price_gbp, value_gbp, weight, run_timestamp)
                           VALUES %s
                        ON CONFLICT (account, date, ticker) DO UPDATE SET
                           shares=EXCLUDED.shares, price_gbp=EXCLUDED.price_gbp,
                           value_gbp=EXCLUDED.value_gbp, weight=EXCLUDED.weight,
                           run_timestamp=EXCLUDED.run_timestamp
                    """
                    execute_values(cur, sql_ticker, ticker_rows, page_size=10000)
                    
                cur.execute(
                    "INSERT INTO run_log (account, run_type, run_timestamp, rows_written, notes) VALUES (%s,%s,%s,%s,%s)",
                    (account, "portfolio", ts, len(snap_rows), f"tickers={len(positions)}")
                )
            conn.commit()
        log.info("save_portfolio_run: wrote %d snapshot rows for account=%s", len(snap_rows), account)
        save_last_prices(account, positions, df_prices)
        return len(snap_rows)
    except Exception as exc:
        log.error("save_portfolio_run failed: %s", exc)
        raise

def save_benchmark_run(account: str, benchmark_label: str, df_benchmark_perf: pd.DataFrame, tickers_and_weights: dict, bm_prices: pd.DataFrame) -> int:
    if df_benchmark_perf is None or df_benchmark_perf.empty:
        log.warning("save_benchmark_run: df_benchmark_perf is empty — nothing saved.")
        return 0

    ts = _now_utc()

    snap_rows = []
    ticker_rows = []
    
    bm_prices_dict = bm_prices.to_dict() if bm_prices is not None and not bm_prices.empty else {}
    perf_dict = df_benchmark_perf.to_dict(orient="index")
    
    for date_idx, row in perf_dict.items():
        date_ts = pd.Timestamp(date_idx)
        date_str = date_ts.strftime("%Y-%m-%d")
        
        total_nav = _safe_float(row.get("Total NAV", row.get("Total NAV (£)")))
        twr_index = _safe_float(row.get("TWR_Index"))
        daily_ret = _safe_float(row.get("Daily_Return"))
        
        snap_rows.append((
            account, benchmark_label, date_str,
            total_nav, twr_index, daily_ret, ts,
        ))
        
        bm_nav = total_nav or 0.0
        for ticker, weight in tickers_and_weights.items():
            price = None
            if ticker in bm_prices_dict:
                raw_p = bm_prices_dict[ticker].get(date_idx, np.nan)
                price = _safe_float(raw_p)
            value = bm_nav * weight if bm_nav > 0 else None

            ticker_rows.append((
                account, benchmark_label, date_str, ticker, _safe_float(weight), price, _safe_float(value), ts,
            ))

    try:
        from psycopg2.extras import execute_values
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM benchmark_snapshots WHERE account = %s AND benchmark_label ILIKE %s", (account, benchmark_label))
                cur.execute("DELETE FROM benchmark_ticker_daily WHERE account = %s AND benchmark_label ILIKE %s", (account, benchmark_label))
                
                sql_snap = """
                    INSERT INTO benchmark_snapshots
                       (account, benchmark_label, date, total_nav_gbp, twr_index, daily_return, run_timestamp)
                       VALUES %s
                """
                execute_values(cur, sql_snap, snap_rows, page_size=10000)
                
                if ticker_rows:
                    sql_ticker = """
                        INSERT INTO benchmark_ticker_daily
                           (account, benchmark_label, date, ticker, target_weight, price_gbp, value_gbp, run_timestamp)
                           VALUES %s
                    """
                    execute_values(cur, sql_ticker, ticker_rows, page_size=10000)
                    
                cur.execute(
                    "INSERT INTO run_log (account, run_type, run_timestamp, rows_written, notes) VALUES (%s,%s,%s,%s,%s)",
                    (account, "benchmark", ts, len(snap_rows), f"label={benchmark_label}")
                )
            conn.commit()
        return len(snap_rows)
    except Exception as exc:
        log.error("save_benchmark_run failed: %s", exc)
        raise

def load_latest_portfolio(account: str) -> dict | None:
    try:
        with get_app_connection() as conn:
            df_snap = pd.read_sql_query(
                """
                SELECT date, equity_gbp, cash_gbp, total_nav_gbp,
                       twr_index, net_invested, daily_return, bench_nav, run_timestamp
                FROM portfolio_snapshots
                WHERE account = %(account)s
                ORDER BY date ASC
                """,
                conn, params={"account": account}
            )

            if df_snap.empty:
                return None

            df_snap["date"] = pd.to_datetime(df_snap["date"])
            df_snap.set_index("date", inplace=True)
            df_snap.index.name = "Date"

            df_perf = df_snap.rename(columns={
                "equity_gbp":    "Equity",
                "cash_gbp":      "Cash",
                "total_nav_gbp": "Total NAV",
                "twr_index":     "TWR_Index",
                "net_invested":  "Net_Invested",
                "daily_return":  "Daily_Return",
                "bench_nav":     "Bench_NAV",
            })

            run_ts = df_snap["run_timestamp"].iloc[-1] if "run_timestamp" in df_snap.columns else None
            df_perf.drop(columns=["run_timestamp"], errors="ignore", inplace=True)
            df_perf["Year"] = df_perf.index.year

            latest_date = df_snap.index.max().strftime("%Y-%m-%d")
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("""SELECT ticker, shares FROM portfolio_ticker_daily
                               WHERE account = %s AND date = %s""", (account, latest_date))
                ticker_rows = cur.fetchall()

            positions = {
                r["ticker"]: r["shares"]
                for r in ticker_rows
                if r["shares"] is not None and r["shares"] > 0
            }

        return {"df_perf": df_perf, "positions": positions, "run_timestamp": run_ts}
    except Exception as exc:
        log.error("load_latest_portfolio failed for account=%s: %s", account, exc)
        raise exc


def load_latest_benchmark(account: str, benchmark_label: str = None) -> dict | None:
    try:
        with get_app_connection() as conn:
            if not benchmark_label:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    cur.execute("SELECT benchmark_label FROM benchmark_snapshots WHERE account = %s ORDER BY run_timestamp DESC LIMIT 1", (account,))
                    row = cur.fetchone()
                    if not row: return None
                    benchmark_label = row["benchmark_label"]

            df_bm = pd.read_sql_query(
                """
                SELECT date, total_nav_gbp, twr_index, daily_return, benchmark_label, run_timestamp
                FROM benchmark_snapshots
                WHERE account = %s AND benchmark_label = %s
                ORDER BY date ASC
                """,
                conn, params=(account, benchmark_label),
            )

            if df_bm.empty: return None

            df_bm["date"] = pd.to_datetime(df_bm["date"])
            df_bm.set_index("date", inplace=True)
            df_bm.index.name = "Date"

            benchmark_label = df_bm["benchmark_label"].iloc[-1]
            run_ts          = df_bm["run_timestamp"].iloc[-1]

            df_benchmark_perf = df_bm.rename(columns={
                "total_nav_gbp": "Total NAV", "twr_index": "TWR_Index", "daily_return": "Daily_Return",
            }).drop(columns=["benchmark_label", "run_timestamp"], errors="ignore")
            df_benchmark_perf["Year"] = df_benchmark_perf.index.year

        return {"df_benchmark_perf": df_benchmark_perf, "benchmark_label": benchmark_label, "run_timestamp": run_ts}
    except Exception as exc:
        log.error("load_latest_benchmark failed for account=%s: %s", account, exc)
        return None


def save_last_prices(account: str, positions: dict, df_prices: pd.DataFrame) -> None:
    if df_prices is None or df_prices.empty: return
    ts = _now_utc()
    rows = []
    for ticker, shares in positions.items():
        if shares < 0.001 or ticker not in df_prices.columns: continue
        series = df_prices[ticker].dropna()
        if series.empty: continue
        price = _safe_float(series.iloc[-1])
        if price is not None: rows.append((account, ticker, price, ts))

    if not rows: return
    try:
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM last_prices WHERE account = %s", (account,))
                cur.executemany("INSERT INTO last_prices (account, ticker, price_gbp, run_timestamp) VALUES (%s,%s,%s,%s)", rows)
            conn.commit()
    except Exception as exc:
        log.error("save_last_prices failed: %s", exc)

def load_last_prices(account: str) -> pd.DataFrame:
    try:
        with get_app_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT ticker, price_gbp FROM last_prices WHERE account = %s", (account,))
                rows = cur.fetchall()
        if not rows: return pd.DataFrame()
        today = pd.Timestamp.today().normalize()
        data = {r["ticker"]: [r["price_gbp"]] for r in rows}
        df = pd.DataFrame(data, index=[today])
        df.index.name = "Date"
        return df
    except Exception as exc:
        log.error("load_last_prices failed for account=%s: %s", account, exc)
        return pd.DataFrame()

def save_benchmark_definition(name: str, constituents: list[dict], rebalance_freq: str = "Q") -> None:
    ts = _now_utc()
    try:
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO saved_benchmarks (name, constituents, rebalance_freq, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (name) DO UPDATE SET constituents=EXCLUDED.constituents, rebalance_freq=EXCLUDED.rebalance_freq, updated_at=EXCLUDED.updated_at
                """, (name, json.dumps(constituents), rebalance_freq, ts, ts))
            conn.commit()
    except Exception as exc:
        log.error("save_benchmark_definition failed: %s", exc)
        raise

def load_benchmark_definitions() -> list[dict]:
    try:
        with get_app_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT name, constituents, rebalance_freq, created_at, updated_at FROM saved_benchmarks ORDER BY name ASC")
                rows = cur.fetchall()
        result = []
        for r in rows:
            c_val = r["constituents"]
            if isinstance(c_val, str):
                try:
                    constituents = json.loads(c_val)
                except Exception:
                    constituents = []
            elif isinstance(c_val, (list, dict)):
                constituents = c_val
            else:
                constituents = []
            result.append({
                "name": r["name"], "constituents": constituents, "rebalance_freq": r["rebalance_freq"],
                "created_at": r["created_at"], "updated_at": r["updated_at"],
            })
        return result
    except Exception as exc:
        log.error("load_benchmark_definitions failed: %s", exc)
        return []

def delete_benchmark_definition(name: str) -> None:
    try:
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM saved_benchmarks WHERE name = %s", (name,))
            conn.commit()
    except Exception as exc:
        log.error("delete_benchmark_definition failed: %s", exc)
        raise

def get_run_log(n: int = 20) -> pd.DataFrame:
    try:
        with get_app_connection() as conn:
            df = pd.read_sql_query("SELECT * FROM run_log ORDER BY id DESC LIMIT %s", conn, params=(n,))
        return df
    except Exception as exc:
        log.error("get_run_log failed: %s", exc)
        return pd.DataFrame()

def get_latest_account_run_timestamp(account: str) -> str | None:
    try:
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(run_timestamp) as ts FROM portfolio_snapshots WHERE account = %s", (account,))
                row = cur.fetchone()
                return row[0] if row else None
    except Exception as exc:
        log.error("get_latest_account_run_timestamp failed for %s: %s", account, exc)
        return None

def clear_account_data(account: str) -> None:
    try:
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                for table in ("portfolio_snapshots", "portfolio_ticker_daily", "last_prices"):
                    cur.execute(f"DELETE FROM {table} WHERE account = %s", (account,))
                cur.execute("INSERT INTO run_log (account, run_type, run_timestamp, rows_written, notes) VALUES (%s,%s,%s,%s,%s)", (account, "clear", _now_utc(), 0, "Manual cache clear"))
            conn.commit()
    except Exception as exc:
        log.error("clear_account_data failed: %s", exc)
        raise

def db_path() -> str:
    return "PostgreSQL (APP_DATABASE_URL)"

def load_full_price_grid(account: str) -> pd.DataFrame:
    try:
        with get_app_connection() as conn:
            df = pd.read_sql_query("""SELECT date, ticker, price_gbp FROM portfolio_ticker_daily WHERE account = %s AND price_gbp IS NOT NULL ORDER BY date ASC""", conn, params=(account,))
        if df.empty: return pd.DataFrame()
        df["date"] = pd.to_datetime(df["date"])
        wide = df.pivot_table(index="date", columns="ticker", values="price_gbp", aggfunc="last")
        wide.index.name = "Date"
        wide.columns.name = None
        return wide
    except Exception as exc:
        log.error("load_full_price_grid failed for account=%s: %s", account, exc)
        return pd.DataFrame()

def get_saved_tickers(account: str) -> set:
    try:
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT ticker FROM portfolio_ticker_daily WHERE account = %s", (account,))
                rows = cur.fetchall()
        return {r[0] for r in rows}
    except Exception as exc:
        log.error("get_saved_tickers failed for account=%s: %s", account, exc)
        return set()

def get_ticker_start_dates(account: str) -> dict[str, pd.Timestamp]:
    try:
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ticker, MIN(date) as min_date FROM portfolio_ticker_daily WHERE account = %s GROUP BY ticker", (account,))
                rows = cur.fetchall()
        return {r[0]: pd.Timestamp(r[1]) for r in rows}
    except Exception as exc:
        log.error("get_ticker_start_dates failed for account=%s: %s", account, exc)
        return {}

def get_latest_price_date(account: str) -> pd.Timestamp | None:
    try:
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(date) FROM portfolio_ticker_daily WHERE account = %s", (account,))
                row = cur.fetchone()
        if row and row[0]: return pd.Timestamp(row[0])
        return None
    except Exception as exc:
        log.error("get_latest_price_date failed for account=%s: %s", account, exc)
        return None

def get_all_held_tickers() -> list[str]:
    try:
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT ticker FROM portfolio_ticker_daily")
                rows = cur.fetchall()
            return [r[0] for r in rows]
    except Exception as exc:
        log.error("get_all_held_tickers failed: %s", exc)
        return []

def get_currently_held_tickers(account: str = None) -> list[str]:
    try:
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                if account:
                    cur.execute("""
                        SELECT DISTINCT ticker 
                        FROM portfolio_ticker_daily 
                        WHERE shares > 0.001 
                          AND account = %s
                          AND date = (SELECT MAX(date) FROM portfolio_ticker_daily WHERE account = %s)
                    """, (account, account))
                else:
                    cur.execute("""
                        SELECT DISTINCT ticker 
                        FROM portfolio_ticker_daily 
                        WHERE shares > 0.001 
                          AND (account, date) IN (
                              SELECT account, MAX(date) FROM portfolio_ticker_daily GROUP BY account
                          )
                    """)
                rows = cur.fetchall()
            return [r[0] for r in rows]
    except Exception as exc:
        log.error("get_currently_held_tickers failed: %s", exc)
        return []

def load_ticker_price_series(account: str, ticker: str) -> pd.Series:
    try:
        with get_app_connection() as conn:
            df = pd.read_sql_query(
                "SELECT date, price_gbp FROM portfolio_ticker_daily WHERE account = %s AND ticker = %s AND price_gbp IS NOT NULL ORDER BY date ASC",
                conn, params=(account, ticker)
            )
        if df.empty: return pd.Series(dtype=float)
        
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        df.index.name = "Date"
        
        return df["price_gbp"]
    except Exception as exc:
        log.error("load_ticker_price_series failed for account=%s, ticker=%s: %s", account, ticker, exc)
        return pd.Series(dtype=float)


# ---------------------------------------------------------------------------
# Screener Caching Helpers
# ---------------------------------------------------------------------------

def save_ticker_ohlcv(ticker: str, df: pd.DataFrame, source: str = 'yfinance') -> None:
    if df is None or df.empty:
        return
    rows = []
    ts = _now_utc()
    for date_idx, row in df.iterrows():
        date_str = pd.Timestamp(date_idx).strftime("%Y-%m-%d")
        rows.append((
            ticker,
            date_str,
            _safe_float(row.get("Open")),
            _safe_float(row.get("High")),
            _safe_float(row.get("Low")),
            _safe_float(row.get("Close")),
            _safe_float(row.get("Volume")),
            source,
            ts
        ))
    if not rows:
        return
    try:
        from psycopg2.extras import execute_values
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                sql = """
                    INSERT INTO ticker_ohlcv_daily (ticker, date, open, high, low, close, volume, source, fetched_at)
                    VALUES %s
                    ON CONFLICT (ticker, date) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        source = EXCLUDED.source,
                        fetched_at = EXCLUDED.fetched_at
                    WHERE ticker_ohlcv_daily.source = 'synthetic' OR EXCLUDED.source != 'synthetic'
                """
                execute_values(cur, sql, rows)
            conn.commit()
    except Exception as exc:
        log.error(f"save_ticker_ohlcv failed for ticker {ticker}: {exc}")
        raise

def load_ticker_ohlcv(ticker: str, start_date) -> pd.DataFrame:
    try:
        start_str = pd.Timestamp(start_date).strftime("%Y-%m-%d")
        with get_app_connection() as conn:
            df = pd.read_sql_query(
                """
                SELECT date, open, high, low, close, volume
                FROM ticker_ohlcv_daily
                WHERE ticker = %s AND date >= %s
                ORDER BY date ASC
                """,
                conn,
                params=(ticker, start_str)
            )
        if df.empty:
            return pd.DataFrame()
        
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        df.index.name = "Date"
        df.columns = ["Open", "High", "Low", "Close", "Volume"]
        return df
    except Exception as exc:
        log.error(f"load_ticker_ohlcv failed for ticker {ticker}: {exc}")
        return pd.DataFrame()

def get_latest_ohlcv_date(ticker: str):
    try:
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT MAX(date) FROM ticker_ohlcv_daily WHERE ticker = %s",
                    (ticker,)
                )
                row = cur.fetchone()
                if row and row[0]:
                    return row[0]
        return None
    except Exception as exc:
        log.error(f"get_latest_ohlcv_date failed for ticker {ticker}: {exc}")
        return None

def save_ticker_metadata(ticker: str, info: dict) -> None:
    if not info:
        return
    ts = _now_utc()
    try:
        info_json = json.dumps(info, default=str)
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ticker_metadata (ticker, info_json, fetched_at, quote_fetched_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (ticker) DO UPDATE SET
                        info_json = EXCLUDED.info_json,
                        fetched_at = EXCLUDED.fetched_at,
                        quote_fetched_at = EXCLUDED.quote_fetched_at
                    """,
                    (ticker, info_json, ts, ts)
                )
            conn.commit()
    except Exception as exc:
        log.error(f"save_ticker_metadata failed for ticker {ticker}: {exc}")
        raise

def load_ticker_metadata(ticker: str, max_age_days: int = 30) -> dict | None:
    try:
        with get_app_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT info_json, fetched_at
                    FROM ticker_metadata
                    WHERE ticker = %s AND fetched_at >= now() - %s * INTERVAL '1 day'
                    """,
                    (ticker, max_age_days)
                )
                row = cur.fetchone()
                if row:
                    val = row["info_json"]
                    return json.loads(val) if isinstance(val, str) else val
        return None
    except Exception as exc:
        log.error(f"load_ticker_metadata failed for ticker {ticker}: {exc}")
        return None

def load_ticker_metadata_quote(ticker: str, max_age_hours: int = 24) -> dict | None:
    try:
        with get_app_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT info_json, quote_fetched_at
                    FROM ticker_metadata
                    WHERE ticker = %s AND quote_fetched_at >= now() - %s * INTERVAL '1 hour'
                    """,
                    (ticker, max_age_hours)
                )
                row = cur.fetchone()
                if row:
                    val = row["info_json"]
                    return json.loads(val) if isinstance(val, str) else val
        return None
    except Exception as exc:
        log.error(f"load_ticker_metadata_quote failed for ticker {ticker}: {exc}")
        return None

def try_acquire_fetch_lock(ticker: str, owner: str, expire_seconds: int = 60) -> bool:
    try:
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM ticker_fetch_locks WHERE ticker = %s AND locked_at < now() - %s * INTERVAL '1 second'",
                    (ticker, expire_seconds)
                )
                cur.execute(
                    "INSERT INTO ticker_fetch_locks (ticker, locked_at, locked_by) VALUES (%s, now(), %s) ON CONFLICT (ticker) DO NOTHING",
                    (ticker, owner)
                )
                if cur.rowcount > 0:
                    conn.commit()
                    return True
            conn.commit()
    except Exception as e:
        log.warning(f"Error acquiring lock for {ticker}: {e}")
    return False

def release_fetch_lock(ticker: str) -> None:
    try:
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ticker_fetch_locks WHERE ticker = %s", (ticker,))
            conn.commit()
    except Exception as exc:
        log.error(f"release_fetch_lock failed for ticker {ticker}: {exc}")


# ---------------------------------------------------------------------------
# Watchlist Tickers
# ---------------------------------------------------------------------------

def get_watchlist_tickers(active_only: bool = True) -> list[dict]:
    try:
        with get_app_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                if active_only:
                    cur.execute("SELECT ticker, name, asset_class, notes, added_at, is_active FROM watchlist_tickers WHERE is_active = true ORDER BY added_at DESC")
                else:
                    cur.execute("SELECT ticker, name, asset_class, notes, added_at, is_active FROM watchlist_tickers ORDER BY added_at DESC")
                rows = cur.fetchall()
            return [
                {
                    "ticker": r["ticker"],
                    "name": r["name"],
                    "asset_class": r["asset_class"],
                    "notes": r["notes"],
                    "added_at": r["added_at"].isoformat() if r["added_at"] else None,
                    "is_active": r["is_active"],
                }
                for r in rows
            ]
    except Exception as exc:
        log.error(f"get_watchlist_tickers failed: {exc}")
        return []

def save_watchlist_ticker(ticker: str, name: str = None, asset_class: str = "Equity", notes: str = None) -> bool:
    ticker = ticker.strip().upper()
    try:
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                sql = """
                    INSERT INTO watchlist_tickers (ticker, name, asset_class, notes, added_at, is_active)
                    VALUES (%s, %s, %s, %s, now(), true)
                    ON CONFLICT (ticker) DO UPDATE SET
                        name = COALESCE(EXCLUDED.name, watchlist_tickers.name),
                        asset_class = COALESCE(EXCLUDED.asset_class, watchlist_tickers.asset_class),
                        notes = COALESCE(EXCLUDED.notes, watchlist_tickers.notes),
                        is_active = true
                """
                cur.execute(sql, (ticker, name, asset_class, notes))
            conn.commit()
        return True
    except Exception as exc:
        log.error(f"save_watchlist_ticker failed for {ticker}: {exc}")
        return False

def delete_watchlist_ticker(ticker: str) -> bool:
    ticker = ticker.strip().upper()
    try:
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM watchlist_tickers WHERE ticker = %s", (ticker,))
            conn.commit()
        return True
    except Exception as exc:
        log.error(f"delete_watchlist_ticker failed for {ticker}: {exc}")
        return False


