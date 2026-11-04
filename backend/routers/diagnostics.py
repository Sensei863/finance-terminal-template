import pandas as pd
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from backend.services.portfolio_diagnostics import (
    load_parsed_ledger_for_account,
    positions_as_of_table,
    first_nonzero_equity_date,
    ledger_rows_for_ticker
)
from backend.services.storage import load_engine_audit, get_run_log as storage_get_run_log

router = APIRouter(prefix="/api/diagnostics", tags=["Diagnostics"])

@router.get("/composition")
def get_portfolio_composition(account: str, as_of: str):
    """Get the portfolio composition for a specific date, and the first non-zero dates."""
    try:
        df_parsed, is_sipp, snap_qty, df_raw = load_parsed_ledger_for_account(account)
        
        # Calculate positions as of date
        as_of_ts = pd.Timestamp(as_of)
        df_pos = positions_as_of_table(df_parsed, as_of_ts, snap_qty)
        positions = df_pos.to_dict(orient="records") if not df_pos.empty else []
        
        # Calculate first non-zero date
        df_first = first_nonzero_equity_date(df_parsed, snap_qty)
        first_dates = df_first.to_dict(orient="records") if not df_first.empty else []
        
        # Snapshot formatting
        snapshot_list = [{"Ticker": k, "Opening Shares": v} for k, v in (snap_qty or {}).items()]
        
        return {
            "snapshot": snapshot_list,
            "positions": positions,
            "first_dates": first_dates
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/ledger_rows")
def get_ledger_rows(account: str, ticker: str):
    """Search for ledger rows related to a specific ticker."""
    try:
        df_parsed, _, _, _ = load_parsed_ledger_for_account(account)
        df_rows = ledger_rows_for_ticker(df_parsed, ticker)
        
        # Ensure 'Date' is string formatted nicely
        if not df_rows.empty and "Date" in df_rows.columns:
            df_rows["Date"] = pd.to_datetime(df_rows["Date"]).dt.strftime("%Y-%m-%d")
            
        rows = df_rows.to_dict(orient="records") if not df_rows.empty else []
        return {"rows": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/audit")
def get_engine_audit(account: str):
    """Retrieve the internal variables from the last engine recalculation run."""
    try:
        audit = load_engine_audit(account)
        if not audit:
            return {"status": "no_data", "message": "No audit data found. Run a recalculation first."}
            
        # Extract and format the data
        res = {
            "status": "success",
            "snapshot_cash": audit.get("snapshot_cash"),
            "snapshot_quantities": audit.get("snapshot_quantities", {}),
            "expected_prices": audit.get("expected_prices", []),
            "multipliers": audit.get("multipliers", {}),
            "sources": audit.get("sources", {}),
            "raw_latest": audit.get("raw_latest", {})
        }
        
        # Handle dataframes if they exist
        for df_key in ["df_raw_for_audit", "df_parsed"]:
            df = audit.get(df_key)
            if isinstance(df, pd.DataFrame) and not df.empty:
                # Need to handle Timestamp objects safely before returning
                for col in df.select_dtypes(include=['datetime', 'datetimetz']).columns:
                    df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S")
                df = df.fillna("")
                res[df_key] = df.to_dict(orient="records")
            else:
                res[df_key] = []
                
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/run_log")
def get_run_log(limit: int = 30):
    """Get the recent storage runs log."""
    try:
        df = storage_get_run_log(limit)
        if df.empty:
            return {"logs": []}
        return {"logs": df.to_dict(orient="records")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
