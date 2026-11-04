import os
import psycopg2
import logging

log = logging.getLogger(__name__)

def sync_local_to_cloud() -> dict:
    """Disabled: The application now natively connects to the Cloud PostgreSQL Database."""
    return {"status": "error", "message": "SQLite to Cloud sync is disabled. App uses Cloud DB natively."}

def sync_cloud_to_local() -> dict:
    """Disabled: The application now natively connects to the Cloud PostgreSQL Database."""
    return {"status": "error", "message": "Cloud to SQLite sync is disabled. App uses Cloud DB natively."}

def get_db_connection_status() -> dict:
    app_url = os.environ.get("APP_DATABASE_URL")
    ledger_url = os.environ.get("LEDGER_DATABASE_URL")
    
    is_sync_capable = False
    db_type = "PostgreSQL (Native)"
        
    cloud_rows = 0
    cloud_last_write = None
    
    # Check App DB connection via the shared pool (avoids a redundant raw connection)
    if app_url:
        try:
            from backend.services.database import get_app_connection
            with get_app_connection() as conn:
                with conn.cursor() as cur:
                    try:
                        cur.execute("SELECT COUNT(*) FROM run_log")
                        res = cur.fetchone()
                        if res: cloud_rows = res[0]
                        cur.execute("SELECT MAX(run_timestamp) FROM run_log")
                        res = cur.fetchone()
                        if res and res[0]:
                            val = res[0]
                            cloud_last_write = val.isoformat() if hasattr(val, "isoformat") else val
                    except Exception:
                        pass
        except Exception as e:
            log.warning(f"App DB check failed: {e}")
                
    return {
        "db_type": db_type,
        "is_prod": os.environ.get("RENDER") is not None,
        "is_sync_capable": is_sync_capable, # No longer needing sync
        "local_db_path": "Disabled (Cloud Native)",
        "local_modified": None,
        "local_rows": 0,
        "cloud_rows": cloud_rows,
        "local_last_write": None,
        "cloud_last_write": cloud_last_write,
        "last_push_sync": None,
        "last_pull_sync": None
    }
