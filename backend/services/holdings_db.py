import os
from contextlib import contextmanager
import pandas as pd
from datetime import datetime, date
from typing import Dict, List, Optional
import warnings

warnings.filterwarnings('ignore', category=UserWarning, message='.*pandas only supports SQLAlchemy connectable.*')

from backend.services.database import get_app_connection

def db_path() -> str:
    return "PostgreSQL (APP_DATABASE_URL)"

def init_db() -> None:
    """
    Schema migrations are now handled by external Postgres migration scripts.
    This function is kept as a no-op for compatibility with app initialization.
    """
    pass

# ---------------------------------------------------------------------------
# etf_holdings — write
# ---------------------------------------------------------------------------

def save_holdings(
    etf_ticker: str,
    provider: str,
    df: pd.DataFrame,
    upload_date: str = None,
    is_synthetic: bool = False,
    index_proxy_note: str = None,
) -> int:
    if upload_date is None:
        upload_date = date.today().isoformat()

    required = {"name", "weight_pct"}
    missing  = required - set(df.columns)
    if missing:
        raise ValueError(f"Holdings DataFrame missing columns: {missing}")

    df = df.drop(columns=[c for c in df.columns if c.startswith("_")], errors="ignore")

    rows = []
    for _, row in df.iterrows():
        rows.append((
            etf_ticker,
            upload_date,
            provider,
            row.get("isin") or None,
            row.get("constituent_ticker") or None,
            str(row["name"]),
            float(row["weight_pct"]),
            row.get("asset_class") or "Equity",
        ))

    sql = """
        INSERT INTO etf_holdings
            (etf_ticker, upload_date, provider, isin, constituent_ticker,
             name, weight_pct, asset_class)
        VALUES %s
    """
    import psycopg2.extras
    with get_app_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM etf_holdings WHERE etf_ticker = %s", (etf_ticker,))
            if rows:
                psycopg2.extras.execute_values(cur, sql, rows, page_size=1000)
        conn.commit()

    _upsert_registry(etf_ticker, provider, upload_date, len(rows),
                     is_synthetic=is_synthetic, index_proxy_note=index_proxy_note)

    return len(rows)

def _upsert_registry(
    etf_ticker: str,
    provider: str,
    upload_date: str,
    row_count: int,
    is_synthetic: bool = False,
    index_proxy_note: str = None,
):
    sql = """
        INSERT INTO staleness_registry
            (etf_ticker, last_upload, upload_count, row_count, provider,
             is_synthetic, index_proxy_note)
        VALUES (%s, %s, 1, %s, %s, %s, %s)
        ON CONFLICT(etf_ticker) DO UPDATE SET
            last_upload       = excluded.last_upload,
            upload_count      = staleness_registry.upload_count + 1,
            row_count         = excluded.row_count,
            provider          = excluded.provider,
            is_synthetic      = excluded.is_synthetic,
            index_proxy_note  = COALESCE(excluded.index_proxy_note, staleness_registry.index_proxy_note)
    """
    with get_app_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (etf_ticker, upload_date, row_count, provider,
                               int(is_synthetic), index_proxy_note))
        conn.commit()

# ---------------------------------------------------------------------------
# etf_holdings — read
# ---------------------------------------------------------------------------

def get_latest_holdings(etf_ticker: str) -> pd.DataFrame:
    sql = """
        SELECT h.*
        FROM   etf_holdings h
        INNER JOIN (
            SELECT etf_ticker, MAX(upload_date) AS max_date
            FROM   etf_holdings
            WHERE  etf_ticker = %s
            GROUP  BY etf_ticker
        ) latest ON h.etf_ticker = latest.etf_ticker
                 AND h.upload_date = latest.max_date
        ORDER  BY h.weight_pct DESC
    """
    with get_app_connection() as conn:
        return pd.read_sql_query(sql, conn, params=(etf_ticker,))

def get_all_etf_tickers_in_db() -> list[str]:
    with get_app_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT etf_ticker FROM etf_holdings ORDER BY etf_ticker")
            return [row[0] for row in cur.fetchall()]

def get_active_etf_tickers_in_db() -> list[str]:
    with get_app_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT h.etf_ticker
                FROM   etf_holdings h
                LEFT JOIN staleness_registry r ON h.etf_ticker = r.etf_ticker
                WHERE  COALESCE(r.ignore_look_through, 0) = 0
                ORDER  BY h.etf_ticker
            """)
            return [row[0] for row in cur.fetchall()]

def set_ignore_look_through(etf_ticker: str, ignore: bool) -> None:
    with get_app_connection() as conn:
        with conn.cursor() as cur:
            now_date_str = date.today().isoformat()
            cur.execute(
                """
                INSERT INTO staleness_registry (etf_ticker, last_upload, ignore_look_through)
                VALUES (%s, %s, %s)
                ON CONFLICT(etf_ticker) DO UPDATE SET ignore_look_through = excluded.ignore_look_through
                """,
                (etf_ticker, now_date_str, int(ignore)),
            )
        conn.commit()

def get_holdings_for_etfs(etf_tickers: list[str]) -> pd.DataFrame:
    if not etf_tickers:
        return pd.DataFrame()
    placeholders = ",".join(["%s"] * len(etf_tickers))
    sql = f"""
        SELECT h.*
        FROM   etf_holdings h
        INNER JOIN (
            SELECT etf_ticker, MAX(upload_date) AS max_date
            FROM   etf_holdings
            WHERE  etf_ticker IN ({placeholders})
            GROUP  BY etf_ticker
        ) latest ON h.etf_ticker = latest.etf_ticker
                 AND h.upload_date = latest.max_date
        ORDER  BY h.etf_ticker, h.weight_pct DESC
    """
    with get_app_connection() as conn:
        return pd.read_sql_query(sql, conn, params=tuple(etf_tickers))

# ---------------------------------------------------------------------------
# constituent_metadata — cache read/write
# ---------------------------------------------------------------------------

def get_cached_metadata(isins: list[str]) -> pd.DataFrame:
    if not isins:
        return pd.DataFrame()
    placeholders = ",".join(["%s"] * len(isins))
    sql = f"SELECT * FROM constituent_metadata WHERE isin IN ({placeholders})"
    with get_app_connection() as conn:
        return pd.read_sql_query(sql, conn, params=tuple(isins))

def save_metadata_batch(records: list[dict]) -> None:
    sql = """
        INSERT INTO constituent_metadata
            (isin, ticker, name, sector, industry, country, market_cap, fetched_at)
        VALUES %s
        ON CONFLICT(isin) DO UPDATE SET
            ticker     = excluded.ticker,
            name       = excluded.name,
            sector     = excluded.sector,
            industry   = excluded.industry,
            country    = excluded.country,
            market_cap = excluded.market_cap,
            fetched_at = excluded.fetched_at
    """
    now = datetime.utcnow().isoformat()
    rows = []
    for r in records:
        rows.append((
            r.get("isin", ""), r.get("ticker") or None, r.get("name") or None,
            r.get("sector") or None, r.get("industry") or None, r.get("country") or None,
            r.get("market_cap") or None, now,
        ))
    if rows:
        import psycopg2.extras
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, sql, rows, page_size=1000)
            conn.commit()

# ---------------------------------------------------------------------------
# ticker_isin_map — ticker → real ISIN bridge
# ---------------------------------------------------------------------------

def save_ticker_isin_map(mappings: dict[str, str]) -> None:
    sql = """
        INSERT INTO ticker_isin_map (ticker, isin, updated_at)
        VALUES %s
        ON CONFLICT(ticker) DO UPDATE SET
            isin       = excluded.isin,
            updated_at = excluded.updated_at
    """
    now = datetime.utcnow().isoformat()
    rows = [
        (ticker.upper(), isin.upper(), now)
        for ticker, isin in mappings.items()
        if isin and len(isin) == 12 and isin[:2].isalpha()
    ]
    if rows:
        import psycopg2.extras
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, sql, rows, page_size=1000)
            conn.commit()

def get_ticker_isin_map() -> dict[str, str]:
    with get_app_connection() as conn:
        explicit = pd.read_sql_query("SELECT ticker, isin FROM ticker_isin_map", conn)

        implicit = pd.read_sql_query("""
            SELECT
                UPPER(SUBSTR(ticker, 1,
                    CASE WHEN POSITION('.' IN ticker) > 0
                         THEN CAST(POSITION('.' IN ticker) AS INTEGER) - 1
                         ELSE LENGTH(ticker) END
                )) AS ticker,
                UPPER(isin) AS isin
            FROM constituent_metadata
            WHERE LENGTH(isin) = 12
              AND SUBSTR(isin, 1, 1) BETWEEN 'A' AND 'Z'
              AND SUBSTR(isin, 2, 1) BETWEEN 'A' AND 'Z'
              AND ticker IS NOT NULL
              AND ticker != ''
        """, conn)

    combined = pd.concat([implicit, explicit], ignore_index=True)
    combined = combined.dropna(subset=["ticker", "isin"])
    combined = combined.drop_duplicates(subset="ticker", keep="last")
    return dict(zip(combined["ticker"].str.upper(), combined["isin"].str.upper()))

_CACHE_EXCLUDE_COLS = {
    "sector_from_file", "country_from_file", "industry", "market_cap", "_join_key",
}

_CACHE_COLUMNS = [
    "account", "computed_at", "etf_ticker", "constituent_isin", "constituent_ticker",
    "constituent_name", "sector", "country", "etf_weight_pct",
    "portfolio_weight_pct", "effective_value_gbp", "asset_class", "has_holdings",
]

def save_lookahead_cache(df: pd.DataFrame, account: str, computed_at: str = None) -> int:
    if computed_at is None:
        computed_at = datetime.utcnow().isoformat()

    df = df.copy()
    df["account"] = account
    df["computed_at"] = computed_at

    extra_cols = [c for c in df.columns if c in _CACHE_EXCLUDE_COLS or c not in _CACHE_COLUMNS]
    if extra_cols:
        df = df.drop(columns=extra_cols, errors="ignore")

    for col in _CACHE_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df = df[[c for c in _CACHE_COLUMNS if c in df.columns]]

    # Provide engine explicitly mapped to sqlalchemy url if you still use pd.DataFrame.to_sql,
    # but to avoid dependency on sqlalchemy or specific connect string formatting, we do executemany instead:
    rows = [tuple(x) for x in df.to_numpy()]
    placeholders = ",".join(["%s"] * len(_CACHE_COLUMNS))
    cols = ",".join(_CACHE_COLUMNS)
    
    sql_insert = f"INSERT INTO lookahead_cache ({cols}) VALUES ({placeholders})"
    
    with get_app_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM lookahead_cache WHERE account = %s", (account,))
            cur.executemany(sql_insert, rows)
        conn.commit()

    return len(df)

def get_lookahead_cache(account: str) -> tuple[pd.DataFrame, str | None]:
    with get_app_connection() as conn:
        df = pd.read_sql_query(
            "SELECT * FROM lookahead_cache WHERE account = %s ORDER BY portfolio_weight_pct DESC",
            conn, params=(account,)
        )
    if df.empty:
        return df, None
    computed_at = df["computed_at"].iloc[0] if "computed_at" in df.columns else None
    return df, computed_at

def invalidate_lookahead_cache(account: str = None) -> None:
    with get_app_connection() as conn:
        with conn.cursor() as cur:
            if account:
                cur.execute("DELETE FROM lookahead_cache WHERE account = %s", (account,))
            else:
                cur.execute("DELETE FROM lookahead_cache")
        conn.commit()

# ---------------------------------------------------------------------------
# staleness_registry — reads
# ---------------------------------------------------------------------------

def get_registry() -> pd.DataFrame:
    with get_app_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT s.*, k.full_name 
            FROM staleness_registry s
            LEFT JOIN etf_kiid k ON s.etf_ticker = k.etf_ticker
            ORDER BY s.last_upload DESC
            """, conn
        )

def get_staleness_warnings(
    current_portfolio_tickers: list[str],
    stale_threshold_days: int = 60,
) -> list[dict]:
    warnings = []
    registry_df = get_registry()
    registered  = set(registry_df["etf_ticker"].tolist()) if not registry_df.empty else set()
    today        = date.today()

    for ticker in current_portfolio_tickers:
        if ticker not in registered:
            warnings.append({
                "type":    "MISSING",
                "ticker":  ticker,
                "message": f"No holdings file uploaded for **{ticker}**. "
                           f"Look-through analysis is incomplete for this position.",
            })
        else:
            row = registry_df[registry_df["etf_ticker"] == ticker].iloc[0]
            last_upload = date.fromisoformat(str(row["last_upload"]).split("T")[0])
            age_days    = (today - last_upload).days
            threshold   = int(row.get("stale_days_threshold") or stale_threshold_days)
            if age_days > threshold:
                warnings.append({
                    "type":    "STALE",
                    "ticker":  ticker,
                    "message": f"Holdings file for **{ticker}** is **{age_days} days old** "
                               f"(uploaded {last_upload}). Consider re-uploading.",
                    "age_days": age_days,
                })

    return warnings

def set_stale_threshold(etf_ticker: str, days: int) -> None:
    with get_app_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE staleness_registry SET stale_days_threshold = %s WHERE etf_ticker = %s",
                (days, etf_ticker),
            )
        conn.commit()

def delete_holdings(etf_ticker: str) -> None:
    with get_app_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM etf_holdings WHERE etf_ticker = %s", (etf_ticker,))
            cur.execute("DELETE FROM staleness_registry WHERE etf_ticker = %s", (etf_ticker,))
        conn.commit()
    invalidate_lookahead_cache()

# ---------------------------------------------------------------------------
# etf_kiid — metadata
# ---------------------------------------------------------------------------

def save_kiid(data: dict) -> None:
    sql = """
        INSERT INTO etf_kiid (
            etf_ticker, full_name, index_tracked, replication_method,
            domicile, ucits, accumulating, ter, isin, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(etf_ticker) DO UPDATE SET
            full_name = excluded.full_name,
            index_tracked = excluded.index_tracked,
            replication_method = excluded.replication_method,
            domicile = excluded.domicile,
            ucits = excluded.ucits,
            accumulating = excluded.accumulating,
            ter = excluded.ter,
            isin = excluded.isin,
            updated_at = excluded.updated_at
    """
    now = datetime.utcnow().isoformat()
    with get_app_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (
                data.get("etf_ticker"), data.get("full_name"), data.get("index_tracked"),
                data.get("replication_method"), data.get("domicile"), data.get("ucits"),
                data.get("accumulating"), data.get("ter"), data.get("isin"), now
            ))
        conn.commit()

def get_kiid(etf_ticker: str) -> dict:
    sql = "SELECT * FROM etf_kiid WHERE etf_ticker = %s"
    with get_app_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, (etf_ticker,))
            row = cur.fetchone()
            return dict(row) if row else {}
