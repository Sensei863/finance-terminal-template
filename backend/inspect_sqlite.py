import sqlite3, os

dbs = [
    r'backend\services\data\portfolio_history.db',
    r'data\portfolio_history.db',
]

for db_path in dbs:
    if os.path.exists(db_path) and os.path.getsize(db_path) > 0:
        print(f'=== {db_path} ({os.path.getsize(db_path):,} bytes) ===')
        conn = sqlite3.connect(db_path)
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        for (t,) in tables:
            count = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            print(f'  {t}: {count:,} rows')
        conn.close()
        print()
