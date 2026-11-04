import sys
import os
import json

sys.path.append(os.path.abspath(os.path.dirname(__file__) + '/..'))
from dotenv import load_dotenv
load_dotenv()

from backend.services import database, engine

database._init_pools()
conn = database._ledger_pool.getconn()
try:
    cur = conn.cursor()
    cur.execute("SELECT id, raw_details, asset_name FROM transactions WHERE auto_ticker IS NULL OR auto_ticker = ''")
    rows = cur.fetchall()
    count = 0
    
    for r in rows:
        row_id = r[0]
        raw_json = r[1]
        
        try:
            raw_dict = json.loads(raw_json)
            parsed = engine.parse_transaction(raw_dict)
            auto_t = parsed[5] # The 6th element is auto_ticker
            
            if auto_t and auto_t.strip():
                cur.execute("UPDATE transactions SET auto_ticker = %s WHERE id = %s", (auto_t.strip(), row_id))
                count += 1
        except Exception as e:
            print(f"Error parsing row {row_id}: {e}")
            
    conn.commit()
    cur.close()
    print(f"Updated {count} rows with auto_ticker")
finally:
    database._ledger_pool.putconn(conn)
