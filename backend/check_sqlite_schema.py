import sqlite3

db_path = r'data\portfolio_history.db'
conn = sqlite3.connect(db_path)

print("=== Tables in local SQLite ===")
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
for (t,) in tables:
    print(f"  {t}")

print()
print("=== Column schemas ===")
for (t,) in tables:
    if t == 'sqlite_sequence':
        continue
    cols = conn.execute(f"PRAGMA table_info('{t}')").fetchall()
    print(f"\n[{t}]")
    for col in cols:
        print(f"  {col[1]} ({col[2]})")

conn.close()
