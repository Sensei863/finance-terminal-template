import os
import sys
import json
import hashlib
from datetime import datetime, timezone
import pandas as pd
import psycopg2
from dotenv import load_dotenv

# Add parent directory to path so we can import backend.services.data_handler
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.services import data_handler

def get_db_connection():
    url = os.getenv("LEDGER_DATABASE_URL")
    if not url:
        raise ValueError("LEDGER_DATABASE_URL not set in .env")
    return psycopg2.connect(url)

def run_migration(dry_run=True):
    print(f"Starting migration... (Dry Run: {dry_run})")
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    if not dry_run:
        cur.execute(
            """INSERT INTO import_batches (source_system, source_description, status) 
               VALUES ('google_sheets', 'Initial migration from Google Sheets', 'running') 
               RETURNING id"""
        )
        batch_id = cur.fetchone()[0]
    else:
        batch_id = -1

    # 1. Migrate Accounts
    print("Migrating accounts...")
    registry_df = data_handler.get_account_registry()
    account_count = 0
    accounts_map = {} # name -> id
    
    for _, row in registry_df.iterrows():
        acct_name = str(row.get("Account Name", "")).strip()
        if not acct_name or acct_name.lower() == "nan": continue
        
        classification = str(row.get("Classification", "Live")).strip()
        base_ccy = str(row.get("Base Currency", "GBP")).strip()
        if len(base_ccy) != 3: base_ccy = 'GBP'
        
        legacy_adj = float(row.get("Legacy Cash Adjustment", 0.0)) if pd.notna(row.get("Legacy Cash Adjustment")) else 0.0
        
        if not dry_run:
            cur.execute("""
                INSERT INTO accounts (account_name, classification, base_currency, legacy_cash_adjustment)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (owner_id, account_name) DO UPDATE SET
                    classification = EXCLUDED.classification,
                    base_currency = EXCLUDED.base_currency,
                    legacy_cash_adjustment = EXCLUDED.legacy_cash_adjustment,
                    updated_at = now()
                RETURNING id
            """, (acct_name, classification, base_ccy, legacy_adj))
            accounts_map[acct_name.lower()] = cur.fetchone()[0]
        else:
            accounts_map[acct_name.lower()] = -1
        account_count += 1

    # 2. Migrate Ticker Map
    print("Migrating ticker map...")
    ticker_df = data_handler.load_gsheet_data("Ticker_Map")
    ticker_count = 0
    if not ticker_df.empty:
        for _, row in ticker_df.iterrows():
            asset_name = str(row.get("Asset Name", "")).strip()
            ticker = str(row.get("Ticker", "")).strip()
            if not asset_name or not ticker or asset_name.lower() == "nan": continue
            
            if not dry_run:
                cur.execute("""
                    INSERT INTO ticker_map (asset_name, ticker, source)
                    VALUES (%s, %s, 'migration')
                    ON CONFLICT (owner_id, asset_name) DO UPDATE SET
                        ticker = EXCLUDED.ticker,
                        updated_at = now()
                """, (asset_name, ticker))
            ticker_count += 1

    # 3. Migrate Transactions
    print("Migrating transactions...")
    txn_count = 0
    for _, acct_row in registry_df.iterrows():
        acct_name = str(acct_row.get("Account Name", "")).strip()
        ws_name = str(acct_row.get("Worksheet", "")).strip()
        if not acct_name or not ws_name or acct_name.lower() == "nan": continue
        
        acct_id = accounts_map.get(acct_name.lower())
        if acct_id is None: continue
        
        df_ws = data_handler.load_gsheet_data(ws_name)
        if df_ws.empty: continue
        
        if "Date" in df_ws.columns:
            df_ws["Date"] = df_ws["Date"].apply(data_handler.parse_excel_date)
            
        for idx, row in df_ws.iterrows():
            if pd.isna(row.get("Date")): continue
            
            date_val = row["Date"].strftime("%Y-%m-%d")
            
            action = str(row.get("Action", "")).strip()
            if not action or action.lower() == "nan":
                if "Details" in row and pd.notna(row["Details"]):
                    action = "Legacy Record"
                else:
                    action = "Unknown"
                    
            asset_name = str(row.get("Asset Name", row.get("Details", ""))).strip()
            if asset_name.lower() == "nan": asset_name = ""
            
            try: qty = float(str(row.get("Qty", 0)).replace(',', ''))
            except: qty = 0.0
            
            try: price = float(str(row.get("Price", 0)).replace(',', ''))
            except: price = 0.0
            
            # Net Amount logic
            net_amt = 0.0
            if "Net Amount" in row and pd.notna(row["Net Amount"]) and str(row["Net Amount"]).strip():
                try: net_amt = float(str(row["Net Amount"]).replace('£', '').replace(',', ''))
                except: pass
            elif "Paid In" in row and pd.notna(row["Paid In"]) and str(row["Paid In"]).strip():
                try: net_amt = float(str(row["Paid In"]).replace('£', '').replace(',', ''))
                except: pass
            elif "Withdrawn" in row and pd.notna(row["Withdrawn"]) and str(row["Withdrawn"]).strip():
                try: net_amt = -float(str(row["Withdrawn"]).replace('£', '').replace(',', ''))
                except: pass
                
            currency = str(row.get("Currency", "GBP")).strip()
            if len(currency) != 3 or currency.lower() == "nan": currency = 'GBP'
            
            auto_ticker = str(row.get("Auto Ticker", "")).strip()
            if auto_ticker.lower() == "nan": auto_ticker = ""
            
            notes = str(row.get("Notes", "")).strip()
            if notes.lower() == "nan": notes = ""
            
            # Use json encoding of row dict for hash
            row_dict = {k: str(v) for k, v in row.items()}
            raw_details = json.dumps(row_dict)
            source_row_hash = hashlib.md5(raw_details.encode('utf-8')).hexdigest()
            row_number = idx + 2
            
            if not dry_run:
                cur.execute("""
                    INSERT INTO transactions (
                        account_id, transaction_date, action, asset_name, 
                        qty, price, net_amount, currency, auto_ticker, notes, 
                        raw_details, source_system, source_sheet, source_row_number, 
                        source_row_hash, import_batch_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'google_sheets', %s, %s, %s, %s
                    ) ON CONFLICT (source_system, source_sheet, source_row_number, source_row_hash) DO NOTHING
                """, (
                    acct_id, date_val, action, asset_name, qty, price, net_amt, 
                    currency, auto_ticker, notes, raw_details, ws_name, row_number, 
                    source_row_hash, batch_id
                ))
            txn_count += 1

    print(f"Finished parsing. Accounts: {account_count}, Tickers: {ticker_count}, Transactions: {txn_count}")
    
    if not dry_run:
        cur.execute("""
            UPDATE import_batches 
            SET completed_at = now(), status = 'completed', 
                account_count = %s, transaction_count = %s, ticker_map_count = %s
            WHERE id = %s
        """, (account_count, txn_count, ticker_count, batch_id))
        conn.commit()
        print("Migration committed.")
    else:
        conn.rollback()
        print("Dry run completed. Rolled back.")

    cur.close()
    conn.close()

if __name__ == "__main__":
    load_dotenv()
    import sys
    dry_run = "--real" not in sys.argv
    run_migration(dry_run=dry_run)
