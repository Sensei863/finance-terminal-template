import pandas as pd
from dataclasses import dataclass
import logging
from backend.services.database import get_ledger_connection

logger = logging.getLogger("data_handler")

def _show_ui_warning(msg: str):
    logger.warning(msg)

def _show_ui_error(msg: str):
    logger.error(msg)

@dataclass
class EngineConfig:
    account_view: str = "Consolidated"
    run_all: bool = False
    repair_mode: bool = False
    time_horizon: str = "MAX"

# =============================================================================
# SNAPSHOT CONSTANTS
# =============================================================================

SNAPSHOT_DATE = pd.Timestamp("2020-01-01")

SNAPSHOT_BROKER_TO_YAHOO: dict[str, str] = {}

SNAPSHOT_YAHOO_TICKERS: list[str] = list(SNAPSHOT_BROKER_TO_YAHOO.values())

def load_start_snapshot() -> tuple[float, dict]:
    """
    Load optional opening portfolio state prior to ledger start.
    Defaults to an empty opening state (0.0 cash, no legacy holdings).
    """
    initial_cash = 0.0
    initial_quantities = {}
    return initial_cash, initial_quantities

# =============================================================================
# ACCOUNT REGISTRY & LEDGER LOADING (POSTGRES REFACTOR)
# =============================================================================

def get_account_registry() -> pd.DataFrame:
    with get_ledger_connection() as conn:
        query = "SELECT * FROM accounts WHERE deleted_at IS NULL ORDER BY id ASC"
        df = pd.read_sql_query(query, conn)
        
    df.rename(columns={
        "account_name": "Account Name",
        "classification": "Classification",
        "base_currency": "Base Currency",
        "legacy_cash_adjustment": "Legacy Cash Adjustment"
    }, inplace=True)
    
    # Mock worksheet column for legacy routers
    df["Worksheet"] = df["Account Name"] + "_Ledger"
    return df

def get_ticker_map() -> pd.DataFrame:
    with get_ledger_connection() as conn:
        query = """
            SELECT asset_name AS "Asset Name", ticker AS "Ticker"
            FROM ticker_map
            WHERE deleted_at IS NULL
            ORDER BY asset_name ASC
        """
        df = pd.read_sql_query(query, conn)
    return df

def get_account_base_currency(account_view: str, registry: pd.DataFrame) -> str:
    if registry.empty or 'Base Currency' not in registry.columns:
        return 'GBP'
    if account_view == 'Consolidated':
        return 'GBP'
    match = registry[registry['Account Name'].astype(str).str.strip().str.lower() == account_view.lower()]
    if match.empty:
        return 'GBP'
        
    raw = str(match.iloc[0].get('Base Currency', '')).strip().upper()
    if raw in ('GBP', 'EUR', 'USD'):
        return raw
        
    classification = str(match.iloc[0].get('Classification', '')).strip()
    if classification == 'Third Party EUR':
        return 'EUR'
        
    return 'GBP'

def is_third_party_eur(account_view: str, registry: pd.DataFrame) -> bool:
    if registry.empty or 'Classification' not in registry.columns:
        return False
    if account_view == 'Consolidated':
        return False
    match = registry[registry['Account Name'].astype(str).str.strip().str.lower() == account_view.lower()]
    if match.empty:
        return False
    return str(match.iloc[0].get('Classification', '')).strip() == 'Third Party EUR'

def get_legacy_cash_adjustment(account_name: str, registry: pd.DataFrame) -> float:
    if registry.empty or "Legacy Cash Adjustment" not in registry.columns:
        return 0.0
    
    if account_name.lower() == "consolidated":
        live_accts = registry[registry["Classification"].astype(str).str.strip().str.lower() == "live"]
        total_adj = 0.0
        for _, row in live_accts.iterrows():
            try:
                total_adj += float(row.get("Legacy Cash Adjustment", 0.0))
            except (ValueError, TypeError):
                pass
        return total_adj

    match = registry[registry["Account Name"].astype(str).str.strip().str.lower() == account_name.lower()]
    if match.empty:
        return 0.0
    try:
        return float(match.iloc[0].get("Legacy Cash Adjustment", 0.0))
    except (ValueError, TypeError):
        return 0.0

def get_consolidated_live_ledger() -> pd.DataFrame:
    """Fetches all live account transactions from Ledger DB."""
    query = """
        SELECT t.transaction_date AS "Date", t.action AS "Action", t.asset_name AS "Asset Name",
               t.qty AS "Qty", t.price AS "Price", t.net_amount AS "Net Amount",
               t.currency AS "Currency", t.auto_ticker AS "Auto Ticker", t.notes AS "Notes",
               t.raw_details AS "Raw Details", a.account_name AS "Account"
        FROM transactions t
        JOIN accounts a ON t.account_id = a.id
        WHERE a.classification ILIKE 'Live'
          AND t.deleted_at IS NULL
          AND a.deleted_at IS NULL
        ORDER BY t.transaction_date ASC
    """
    with get_ledger_connection() as conn:
        df = pd.read_sql_query(query, conn)
    
    if not df.empty:
        df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)
    return df

def get_sanitized_ledger(account_view: str) -> tuple[pd.DataFrame, bool, pd.DataFrame]:
    """
    Load, merge (for Consolidated), and sanitise the transaction ledger from Postgres.
    """
    df = pd.DataFrame()
    is_sipp = False

    if account_view == "Consolidated":
        df = get_consolidated_live_ledger()
    else:
        query = """
            SELECT t.transaction_date AS "Date", t.action AS "Action", t.asset_name AS "Asset Name",
                   t.qty AS "Qty", t.price AS "Price", t.net_amount AS "Net Amount",
                   t.currency AS "Currency", t.auto_ticker AS "Auto Ticker", t.notes AS "Notes",
                   t.raw_details AS "Raw Details", a.account_name AS "Account"
            FROM transactions t
            JOIN accounts a ON t.account_id = a.id
            WHERE a.account_name = %s
              AND t.deleted_at IS NULL
              AND a.deleted_at IS NULL
            ORDER BY t.transaction_date ASC
        """
        with get_ledger_connection() as conn:
            df = pd.read_sql_query(query, conn, params=(account_view,))
        
        if not df.empty:
            df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)

        if "SIPP" in account_view.upper():
            is_sipp = True

    raw_df = df.copy()

    if not df.empty:
        # Postgres migration seems to have stored all net_amounts as absolute values.
        # We must infer the correct cash-flow sign from the action.
        def apply_correct_sign(row):
            raw = row.get("Raw Details")
            if isinstance(raw, str):
                import json
                try:
                    rd = json.loads(raw)
                    paid_in = str(rd.get("Paid In", "")).replace("£", "").replace(",", "").strip()
                    withdrawn = str(rd.get("Withdrawn", "")).replace("£", "").replace(",", "").strip()
                    paid_val = float(paid_in) if paid_in else 0.0
                    withdrawn_val = float(withdrawn) if withdrawn else 0.0
                    return paid_val + withdrawn_val
                except Exception:
                    pass
            
            action = str(row.get("Action", "")).strip().lower()
            val = abs(float(row.get("Net Amount", 0.0)))
            
            if action in ("buy", "fee"):
                return -val
            elif action in ("sell", "unparsed sell (check diagnostics)", "dividend", "interest"):
                return val
            
            return val

        df["Net Amount"] = df.apply(apply_correct_sign, axis=1)
        
        def extract_paid_in(row):
            raw = row.get("Raw Details")
            if isinstance(raw, str):
                import json
                try:
                    return json.loads(raw).get("Paid In", "")
                except Exception:
                    pass
            net = row.get("Net Amount", 0.0)
            return net if net > 0 else 0.0
            
        def extract_withdrawn(row):
            raw = row.get("Raw Details")
            if isinstance(raw, str):
                import json
                try:
                    return json.loads(raw).get("Withdrawn", "")
                except Exception:
                    pass
            net = row.get("Net Amount", 0.0)
            return net if net < 0 else 0.0
            
        df["Paid In"] = df.apply(extract_paid_in, axis=1)
        df["Withdrawn"] = df.apply(extract_withdrawn, axis=1)
        
    return df, is_sipp, raw_df

# =============================================================================
# TICKER MAP HELPERS
# =============================================================================

def apply_ticker_map(df_parsed: pd.DataFrame, df_ticker_map: pd.DataFrame = None) -> pd.DataFrame:
    """Applies ticker map to the ledger DataFrame. Fetches from DB if df_ticker_map is None."""
    if df_ticker_map is None or df_ticker_map.empty:
        query = 'SELECT asset_name AS "Asset Name", ticker AS "Ticker" FROM ticker_map'
        try:
            with get_ledger_connection() as conn:
                df_ticker_map = pd.read_sql_query(query, conn)
        except Exception as e:
            logger.error(f"Failed to fetch ticker map: {e}")
            return df_parsed

    if df_ticker_map.empty or "Asset Name" not in df_ticker_map.columns:
        return df_parsed

    mapping_dict = {
        str(k).strip().lower(): str(v).strip()
        for k, v in zip(df_ticker_map["Asset Name"], df_ticker_map["Ticker"])
        if pd.notna(k)
    }

    def map_ticker(row):
        asset_raw = str(row.get("Asset Name", "")).strip()
        asset_norm = asset_raw.lower()
        
        if asset_norm in mapping_dict:
            t = mapping_dict[asset_norm]
            if pd.notna(t) and t.lower() != "nan" and t != "":
                return t
        
        return row.get("Auto Ticker", "")

    df_parsed["Auto Ticker"] = df_parsed.apply(map_ticker, axis=1)
    return df_parsed

def add_account_to_registry(account_name: str, worksheet_name: str, classification: str, base_currency: str = 'GBP'):
    account_name = str(account_name or "").strip()
    classification = str(classification or "Live").strip() or "Live"
    base_currency = str(base_currency or "GBP").strip().upper() or "GBP"

    if not account_name:
        return False, "Account name is required."
    if base_currency not in ("GBP", "EUR", "USD"):
        return False, "Base currency must be GBP, EUR, or USD."

    try:
        with get_ledger_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO accounts (account_name, classification, base_currency)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (owner_id, account_name)
                    DO UPDATE SET
                        classification = EXCLUDED.classification,
                        base_currency = EXCLUDED.base_currency,
                        deleted_at = NULL,
                        updated_at = now()
                    """,
                    (account_name, classification, base_currency),
                )
            conn.commit()
        return True, None
    except Exception as exc:
        logger.exception("Failed to create account %s", account_name)
        return False, str(exc)

def delete_account_from_registry(account_name: str):
    account_name = str(account_name or "").strip()
    if not account_name:
        return False, "Account name is required."
    if account_name.lower() == "consolidated":
        return False, "Consolidated is a derived view and cannot be deleted."

    try:
        with get_ledger_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE accounts
                    SET deleted_at = now(), updated_at = now()
                    WHERE account_name = %s AND deleted_at IS NULL
                    """,
                    (account_name,),
                )
                if cur.rowcount == 0:
                    conn.rollback()
                    return False, f"Account {account_name} not found."
            conn.commit()
        return True, None
    except Exception as exc:
        logger.exception("Failed to delete account %s", account_name)
        return False, str(exc)

def update_account_registry_field(account_name: str, field_name: str, value):
    column_map = {
        "Classification": "classification",
        "Base Currency": "base_currency",
        "Legacy Cash Adjustment": "legacy_cash_adjustment",
    }
    column = column_map.get(field_name)
    if column is None:
        return False, f"Unsupported account field: {field_name}"

    try:
        with get_ledger_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE accounts SET {column} = %s, updated_at = now() WHERE account_name = %s AND deleted_at IS NULL",
                    (value, account_name),
                )
                if cur.rowcount == 0:
                    conn.rollback()
                    return False, f"Account {account_name} not found."
            conn.commit()
        return True, None
    except Exception as exc:
        logger.exception("Failed to update account %s field %s", account_name, field_name)
        return False, str(exc)

def clear_all_caches():
    """No-op cache clearer provided for scheduler and pipeline backward compatibility."""
    logger.debug("clear_all_caches called")

