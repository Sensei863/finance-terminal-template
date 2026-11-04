import sys
import os
from dotenv import load_dotenv

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

load_dotenv(os.path.join(project_root, '.env'))

from backend.services.database import get_app_connection

def main():
    try:
        with get_app_connection() as conn:
            with conn.cursor() as cur:
                print("Disabling statement timeout for index creation...")
                cur.execute("SET statement_timeout = 0;")
                
                print("Creating index on portfolio_snapshots (account, date)...")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_account_date ON portfolio_snapshots (account, date);")
                
                print("Creating index on portfolio_ticker_daily (account, date)...")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_portfolio_ticker_daily_account_date ON portfolio_ticker_daily (account, date);")
                
                print("Creating index on ticker_ohlcv_daily (ticker, date)...")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ticker_ohlcv_daily_ticker_date ON ticker_ohlcv_daily (ticker, date);")
                
            conn.commit()
            print("Successfully created indices!")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
