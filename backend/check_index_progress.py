import sys
import os
from dotenv import load_dotenv
import pandas as pd

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

load_dotenv(os.path.join(project_root, '.env'))

from backend.services.database import get_app_connection

def main():
    try:
        with get_app_connection() as conn:
            # Query the postgres progress view for index creation
            query = """
                SELECT 
                    a.datname as database,
                    a.pid,
                    a.query,
                    p.phase,
                    p.blocks_total,
                    p.blocks_done,
                    p.tuples_total,
                    p.tuples_done,
                    p.lockers_total,
                    p.lockers_done
                FROM pg_stat_progress_create_index p
                JOIN pg_stat_activity a ON p.pid = a.pid;
            """
            df = pd.read_sql_query(query, conn)
            
            if df.empty:
                print("No index creations currently in progress.")
            else:
                for idx, row in df.iterrows():
                    print(f"--- Process {row['pid']} ---")
                    print(f"Phase: {row['phase']}")
                    print(f"Query: {row['query']}")
                    if row['blocks_total'] > 0:
                        pct = (row['blocks_done'] / row['blocks_total']) * 100
                        print(f"Blocks: {row['blocks_done']} / {row['blocks_total']} ({pct:.1f}%)")
                    if row['tuples_total'] > 0:
                        pct = (row['tuples_done'] / row['tuples_total']) * 100
                        print(f"Tuples: {row['tuples_done']} / {row['tuples_total']} ({pct:.1f}%)")
                    if row['lockers_total'] > 0:
                        pct = (row['lockers_done'] / row['lockers_total']) * 100
                        print(f"Lockers: {row['lockers_done']} / {row['lockers_total']} ({pct:.1f}%)")
                    print()
                    
    except Exception as e:
        print(f"Error checking progress: {e}")

if __name__ == "__main__":
    main()
