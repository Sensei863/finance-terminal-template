from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import pandas as pd
import io
import hashlib
import os

from backend.services import ingestion_service
from backend.services import ticker_service
from backend.services.database import get_ledger_connection
from backend.services.data_handler import get_account_registry, get_account_base_currency, get_ticker_map

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])

def get_gemini_api_key():
    env_key = os.environ.get("GEMINI_API_KEY")
    if env_key:
        return env_key
    try:
        from backend.config import get_secrets as load_config_secrets
        secrets = load_config_secrets()
        key = secrets.get("gemini_api_key")
        if key:
            return key
        if "connections" in secrets and "gsheets" in secrets["connections"]:
            return secrets["connections"]["gsheets"].get("gemini_api_key")
        return None
    except Exception:
        return None

@router.get("/accounts")
def get_accounts():
    registry = get_account_registry()
    if registry.empty:
        return {"accounts": []}
    
    # Check if Classification exists
    has_class = "Classification" in registry.columns
    
    accounts = []
    for _, row in registry.iterrows():
        name = str(row.get("Account Name", "")).strip()
        if not name: continue
        
        classification = str(row.get("Classification", "Live")).strip() if has_class else "Live"
        accounts.append({
            "name": name,
            "classification": classification
        })
        
    return {"accounts": accounts}

class ParsePdfRequest(BaseModel):
    account: str

@router.post("/parse-pdf")
async def parse_pdf(
    account: str = Form(...),
    file: UploadFile = File(...)
):
    pdf_bytes = await file.read()
    registry = get_account_registry()
    ingest_ccy = get_account_base_currency(account, registry)
    api_key = get_gemini_api_key()
    
    parsed_data = ingestion_service.parse_contract_note(
        pdf_bytes, 
        api_key,
        base_currency=ingest_ccy
    )
    
    if parsed_data and "_parse_error" in parsed_data[0]:
        raise HTTPException(status_code=400, detail=parsed_data[0]["_parse_error"])
        
    return {"parsed_trades": parsed_data}

class ResolveTickersRequest(BaseModel):
    account: str
    asset_names: List[str]
    isin_map: Optional[Dict[str, str]] = None
    sedol_map: Optional[Dict[str, str]] = None

@router.post("/resolve-tickers")
def resolve_tickers(req: ResolveTickersRequest):
    registry = get_account_registry()
    ingest_ccy = get_account_base_currency(req.account, registry)
    api_key = get_gemini_api_key()
    
    t_map = {}
    try:
        tm_df = get_ticker_map()
        if not tm_df.empty:
            t_map = dict(zip(tm_df["Asset Name"], tm_df["Ticker"]))
    except Exception:
        pass

    result = ticker_service.ai_fill_tickers(
        api_key,
        req.asset_names,
        isin_map=req.isin_map,
        sedol_map=req.sedol_map,
        base_currency=ingest_ccy,
        ticker_map=t_map,
    )
    
    return {"resolved": result}

class CommitRequest(BaseModel):
    account: str
    trades: List[Dict[str, Any]]

@router.post("/commit")
def commit_trades(req: CommitRequest):
    registry = get_account_registry()
    match = registry[registry["Account Name"].astype(str).str.strip().str.lower() == req.account.lower()]
    if match.empty:
        raise HTTPException(status_code=404, detail=f"Account {req.account} not found in registry")

    account_id = int(match.iloc[0]["id"])
    ingest_ccy = get_account_base_currency(req.account, registry)

    inserted = 0
    try:
        with get_ledger_connection() as conn:
            with conn.cursor() as cur:
                for row in req.trades:
                    raw_date = row.get("Date")
                    try:
                        try:
                            trade_date = pd.to_datetime(str(raw_date), format='%Y-%m-%d').strftime('%Y-%m-%d')
                        except Exception:
                            trade_date = pd.to_datetime(raw_date, dayfirst=True).strftime("%Y-%m-%d")
                    except Exception:
                        raise HTTPException(status_code=400, detail=f"Invalid trade date: {raw_date}")

                    action = str(row.get("Action", "") or "").strip() or "Buy"
                    asset = str(row.get("Asset Name", "") or "").strip()
                    ticker = str(row.get("Auto Ticker", "") or "").strip().upper() or None
                    if not asset:
                        raise HTTPException(status_code=400, detail="Asset Name is required for every trade.")

                    try:
                        qty = float(row.get("Qty", 0) or 0)
                        price = float(row.get("Price", 0) or 0)
                        net_amount = float(row.get("Net Amount", 0) or 0)
                    except (TypeError, ValueError):
                        raise HTTPException(status_code=400, detail=f"Invalid numeric value for {asset}.")

                    row_hash = hashlib.sha256(
                        f"{req.account}|{trade_date}|{action}|{asset}|{qty:.8f}|{price:.8f}|{net_amount:.8f}|{ticker or ''}".encode("utf-8")
                    ).hexdigest()

                    cur.execute(
                        """
                        INSERT INTO transactions (
                            account_id, transaction_date, action, asset_name, qty, price,
                            net_amount, currency, auto_ticker, notes, source_system,
                            source_sheet, source_row_hash
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'manual_ingestion', %s, %s)
                        """,
                        (
                            account_id,
                            trade_date,
                            action,
                            asset,
                            qty,
                            price,
                            net_amount,
                            ingest_ccy,
                            ticker,
                            "",
                            req.account,
                            row_hash,
                        ),
                    )
                    inserted += 1

                    if ticker and action in ("Buy", "Sell"):
                        cur.execute(
                            """
                            INSERT INTO ticker_map (asset_name, ticker, source)
                            VALUES (%s, %s, 'manual_ingestion')
                            ON CONFLICT (owner_id, asset_name)
                            DO UPDATE SET ticker = EXCLUDED.ticker, updated_at = now(), deleted_at = NULL
                            """,
                            (asset, ticker),
                        )
            conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success", "count": inserted}

@router.get("/ledger/{account}")
def get_ledger(account: str):
    registry = get_account_registry()
    match = registry[registry["Account Name"].astype(str).str.strip().str.lower() == account.lower()]
    if match.empty:
        raise HTTPException(status_code=404, detail="Account not found")

    query = """
        SELECT
            t.id,
            t.transaction_date AS "Date",
            t.action AS "Action",
            t.asset_name AS "Asset Name",
            t.qty AS "Qty",
            t.price AS "Price",
            t.net_amount AS "Net Amount",
            t.currency AS "Currency",
            t.auto_ticker AS "Auto Ticker",
            t.notes AS "Notes"
        FROM transactions t
        JOIN accounts a ON t.account_id = a.id
        WHERE a.account_name ILIKE %s
          AND t.deleted_at IS NULL
        ORDER BY t.transaction_date ASC, t.id ASC
    """
    with get_ledger_connection() as conn:
        df = pd.read_sql_query(query, conn, params=(account,))

    if df.empty:
        return {"ledger": []}

    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True).dt.strftime("%Y-%m-%d")
    df = df.fillna("")
    return {"ledger": df.to_dict(orient="records")}

@router.delete("/ledger/{account}/{row_index}")
def delete_ledger_row(account: str, row_index: int):
    registry = get_account_registry()
    match = registry[registry["Account Name"].astype(str).str.strip().str.lower() == account.lower()]
    if match.empty:
        raise HTTPException(status_code=404, detail="Account not found")

    if row_index < 0:
        raise HTTPException(status_code=400, detail="row_index must be non-negative")

    try:
        with get_ledger_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT t.id
                    FROM transactions t
                    JOIN accounts a ON t.account_id = a.id
                    WHERE a.account_name ILIKE %s
                      AND t.deleted_at IS NULL
                    ORDER BY t.transaction_date ASC, t.id ASC
                    OFFSET %s LIMIT 1
                    """,
                    (account, row_index),
                )
                row = cur.fetchone()
                if not row:
                    conn.rollback()
                    raise HTTPException(status_code=404, detail="Ledger row not found")

                cur.execute("UPDATE transactions SET deleted_at = now(), updated_at = now() WHERE id = %s", (row[0],))
            conn.commit()
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/parse-spreadsheet")
async def parse_spreadsheet(
    account: str = Form(...),
    file: UploadFile = File(...)
):
    contents = await file.read()
    filename = file.filename.lower()

    try:
        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(contents))
        elif filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format. Must be CSV or Excel (.xls/.xlsx).")

        if df.empty:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        def map_columns(dataframe):
            orig = dataframe.columns.tolist()
            clean = [str(h).lower().replace(" ", "").replace("_", "").replace("-", "") for h in orig]
            def fc(aliases):
                for alias in aliases:
                    for idx, h in enumerate(clean):
                        if h == alias:
                            return orig[idx]
                return None
            return fc(["date", "tradedate"]), fc(["assetname", "asset", "details", "description"]), fc

        date_col, asset_col, find_col = map_columns(df)

        # If header wasn't found in row 0, search top 10 rows for title/metadata offset
        if not date_col or not asset_col:
            for header_row_idx in range(min(10, len(df))):
                row_vals = df.iloc[header_row_idx].tolist()
                row_clean = [str(v).lower().replace(" ", "").replace("_", "").replace("-", "") for v in row_vals]
                has_date = any(alias in row_clean for alias in ["date", "tradedate"])
                has_asset = any(alias in row_clean for alias in ["assetname", "asset", "details", "description"])
                if has_date and has_asset:
                    new_cols = df.iloc[header_row_idx].tolist()
                    df = df.iloc[header_row_idx + 1:].copy()
                    df.columns = new_cols
                    df.reset_index(drop=True, inplace=True)
                    date_col, asset_col, find_col = map_columns(df)
                    break

        action_col = find_col(["action", "type", "transaction"])
        qty_col = find_col(["qty", "quantity", "shares"])
        price_col = find_col(["price", "rate"])
        net_col = find_col(["netamount", "amount", "net", "paidin", "withdrawn"])
        ticker_col = find_col(["ticker", "autoticker", "symbol"])

        if not date_col or not asset_col:
            raise HTTPException(status_code=400, detail="Could not find required columns (Date, Asset Name/Details) in the sheet.")

        trades = []
        for _, row in df.iterrows():
            raw_date = row[date_col]
            if pd.isna(raw_date): continue

            try:
                if isinstance(raw_date, pd.Timestamp):
                    parsed_date = raw_date.strftime('%Y-%m-%d')
                else:
                    try:
                        parsed_date = pd.to_datetime(str(raw_date), format='%Y-%m-%d').strftime('%Y-%m-%d')
                    except Exception:
                        parsed_date = pd.to_datetime(raw_date, dayfirst=True).strftime('%Y-%m-%d')
            except Exception:
                parsed_date = str(raw_date)

            raw_action = row[action_col] if action_col and not pd.isna(row[action_col]) else "Buy"
            action_val = str(raw_action).strip().capitalize()
            if action_val not in ("Buy", "Sell", "Transfer", "Fee", "Dividend", "Interest"):
                action_val = "Buy"

            asset_name = str(row[asset_col]).strip() if not pd.isna(row[asset_col]) else ""
            if not asset_name: continue

            qty = float(row[qty_col]) if qty_col and not pd.isna(row[qty_col]) else 0.0
            price = float(row[price_col]) if price_col and not pd.isna(row[price_col]) else 0.0

            net = 0.0
            if net_col and not pd.isna(row[net_col]):
                net = float(row[net_col])
            else:
                net = - (qty * price) if action_val == "Buy" else (qty * price)

            ticker = str(row[ticker_col]).strip().upper() if ticker_col and not pd.isna(row[ticker_col]) else ""

            trades.append({
                "Date": parsed_date,
                "Action": action_val,
                "Asset Name": asset_name,
                "Qty": qty,
                "Price": price,
                "Net Amount": net,
                "Auto Ticker": ticker
            })

        return {"parsed_trades": trades}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse file: {str(e)}")

"""
Legacy Google Sheets implementation removed from the live route path during the
Ledger DB migration. The block below is intentionally left unreachable only as
near-term reference while the migration settles.
"""
def _legacy_commit_trades_reference(req: CommitRequest):
    # Expected format: "2024-10-01", convert to "01/10/2024"
    rows_to_add = []
    headers = []
    uses_rich_schema = True
    ingest_ccy = "GBP"
    req_account = req.account
    for row in req.trades:
        try:
            trade_date = pd.to_datetime(row['Date'], dayfirst=True).strftime('%d/%m/%Y')
        except Exception:
            trade_date = row['Date']

        if uses_rich_schema:
            new_row_data = {
                "Date": trade_date,
                "Action": row.get("Action", ""),
                "Asset Name": row.get("Asset Name", ""),
                "Qty": row.get("Qty", 0),
                "Price": row.get("Price", 0),
                "Net Amount": float(row.get("Net Amount", 0)),
                "Auto Ticker": row.get("Auto Ticker", ""),
                "Notes": "",
                "Account": req_account,
            }
        else:
            action = row.get('Action', '')
            details = ""
            net = float(row.get('Net Amount', 0))
            if action in ('Buy', 'Sell'):
                if ingest_ccy == 'GBP':
                    price_val = float(row['Price']) * 100
                    ccy_lab   = "GBX"
                else:
                    price_val = float(row['Price'])
                    ccy_lab   = ingest_ccy
                act_label = "Bought" if action == "Buy" else "Sold"
                details = f"{act_label} {row['Qty']} {row['Asset Name']} @ {ccy_lab} {price_val:.2f}"
            elif action == 'Fee':
                details = "Online transaction fee"
            elif action == 'Transfer':
                details = "Direct Credit" if net > 0 else "Direct Debit"
            elif action == 'Dividend':
                details = f"Dividend: {row.get('Asset Name', '')} @ 0"
            elif action == 'Interest':
                details = "Interest on cash balance"
            else:
                details = row.get('Asset Name', '')
                
            new_row_data = {
                "Date": trade_date,
                "Details": details,
                "Paid In":   net if net > 0 else "",
                "Withdrawn": net if net < 0 else "",
            }
        
        # Ensure new row has the exact same columns as headers
        final_row = {col: new_row_data.get(col, "") for col in headers}
        rows_to_add.append([final_row[col] for col in headers])
        
    return rows_to_add
