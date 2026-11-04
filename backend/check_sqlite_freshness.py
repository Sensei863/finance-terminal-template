import sqlite3

db_path = r'data\portfolio_history.db'
conn = sqlite3.connect(db_path)

print("=== Data Freshness Check ===")
print()

# Most recent portfolio snapshot
row = conn.execute("SELECT MAX(date), MAX(run_timestamp) FROM portfolio_snapshots").fetchone()
print(f"portfolio_snapshots - latest date: {row[0]}, latest run_timestamp: {row[1]}")

# Most recent benchmark snapshot
row = conn.execute("SELECT MAX(date), MAX(run_timestamp) FROM benchmark_snapshots").fetchone()
print(f"benchmark_snapshots - latest date: {row[0]}, latest run_timestamp: {row[1]}")

# Most recent run log
row = conn.execute("SELECT MAX(run_timestamp), run_type FROM run_log ORDER BY id DESC LIMIT 1").fetchone()
print(f"run_log            - latest run: {row[0]} ({row[1]})")

# Accounts present
accounts = conn.execute("SELECT DISTINCT account, COUNT(*) as rows FROM portfolio_snapshots GROUP BY account").fetchall()
print()
print("=== Accounts in portfolio_snapshots ===")
for acct, count in accounts:
    print(f"  {acct}: {count} rows")

conn.close()
