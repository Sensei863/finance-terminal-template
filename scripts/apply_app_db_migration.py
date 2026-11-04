import os
import psycopg2
from dotenv import load_dotenv

def apply_migration(file_path, url_name):
    url = os.getenv(url_name)
    if not url:
        print(f"[{url_name}] Not found in .env!")
        return

    print(f"Applying {file_path} to {url_name}...")
    try:
        with open(file_path, 'r') as f:
            sql = f.read()

        conn = psycopg2.connect(url)
        conn.autocommit = True
        cur = conn.cursor()
        
        cur.execute(sql)
        print(f"SUCCESS! Migration applied successfully to {url_name}.")
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"FAILED! Error: {e}")

if __name__ == "__main__":
    load_dotenv()
    migration_file = os.path.join("migrations", "app_db", "001_cache_core.sql")
    apply_migration(migration_file, "APP_DATABASE_URL")
