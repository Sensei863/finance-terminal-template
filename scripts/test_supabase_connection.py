import os
import psycopg2
from dotenv import load_dotenv

def test_connection(url_name):
    url = os.getenv(url_name)
    if not url:
        print(f"[{url_name}] Not found in .env!")
        return

    try:
        # Connect to the database
        conn = psycopg2.connect(url)
        cur = conn.cursor()
        
        # Execute a simple query
        cur.execute('SELECT version();')
        db_version = cur.fetchone()
        print(f"[{url_name}] SUCCESS! Connected to: {db_version[0][:40]}...")
        
        # Close the connection
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[{url_name}] FAILED! Error: {e}")

if __name__ == "__main__":
    print("Testing Supabase Connections...\n")
    # Load environment variables from .env file
    load_dotenv()
    
    test_connection("APP_DATABASE_URL")
    print("-" * 50)
    test_connection("LEDGER_DATABASE_URL")
