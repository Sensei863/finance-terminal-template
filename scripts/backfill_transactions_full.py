import sys
import os
import json
import traceback

sys.path.append(os.path.abspath(os.path.dirname(__file__) + '/..'))
from dotenv import load_dotenv
load_dotenv()

from backend.services import database, engine

database._init_pools()
conn = database._ledger_pool.getconn()
try:
    cur = conn.cursor()
    cur.execute("SELECT id, raw_details FROM transactions")
    rows = cur.fetchall()
    count = 0
    
    for r in rows:
        row_id = r[0]
        raw_json = r[1]
        
        try:
            raw_dict = json.loads(raw_json)
            # engine.parse_transaction returns: pd.Series([action, asset_name, qty, price, net_amount, auto_ticker])
            parsed = engine.parse_transaction(raw_dict)
            action = parsed[0]
            asset_name = parsed[1]
            qty = parsed[2]
            price = parsed[3]
            # net_amount = parsed[4] (not updating net_amount because migration probably got it right from Paid In/Withdrawn, but could update if needed)
            auto_t = parsed[5]
            
            # For nulls, substitute empty strings
            action = action if action is not None else "Other"
            asset_name = asset_name if asset_name is not None else ""
            auto_t = auto_t if auto_t is not None else ""
            qty = float(qty) if qty is not None else 0.0
            price = float(price) if price is not None else 0.0
            
            cur.execute("""
                UPDATE transactions 
                SET action = %s, asset_name = %s, qty = %s, price = %s, auto_ticker = %s 
                WHERE id = %s
            """, (action, asset_name, qty, price, auto_t, row_id))
            count += 1
            
        except Exception as e:
            print(f"Error parsing row {row_id}: {e}")
            traceback.print_exc()
            
    conn.commit()
    cur.close()
    print(f"Updated {count} rows with full parsed data")
finally:
    database._ledger_pool.putconn(conn)
