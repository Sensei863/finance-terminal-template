import logging
import base64
import numpy as np
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Body
from pydantic import BaseModel

from backend.services import holdings_db as hdb
from backend.services import holdings_parser as hparser
from backend.services import lookahead_engine as engine
from backend.services import storage
from .ingestion import get_gemini_api_key

router = APIRouter(prefix="/api/lookthrough", tags=["lookthrough"])

# --- Models ---

class SaveHoldingsRequest(BaseModel):
    etf_ticker: str
    provider: str
    df_records: List[Dict[str, Any]]
    is_synthetic: bool = False
    index_proxy_note: Optional[str] = None

class IgnoreRequest(BaseModel):
    etf_ticker: str
    ignore: bool

class AnalysisRequest(BaseModel):
    account: str
    force_refresh: bool = False

class OverlapPairRequest(BaseModel):
    account: str
    etf_a: str
    etf_b: str

# --- Endpoints ---

@router.get("/registry")
def get_registry():
    try:
        df = hdb.get_registry()
        # Add age calculation
        from datetime import date
        today = date.today()
        
        records = []
        if not df.empty:
            df["Age (days)"] = df["last_upload"].apply(
                lambda d: (today - date.fromisoformat(str(d))).days
            )
            df["Status"] = df.apply(
                lambda r: "🟡 Stale" if r["Age (days)"] > int(r.get("stale_days_threshold") or 60) else "🟢 Fresh",
                axis=1
            )
            records = df.replace({np.nan: None}).to_dict(orient="records")
        return {"registry": records}
    except Exception as e:
        logging.error(f"Error fetching registry: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/warnings")
def get_warnings(account: str = "Consolidated"):
    try:
        cached_result = storage.load_latest_portfolio(account)
        if not cached_result:
            return {"warnings": []}
            
        positions = cached_result.get("positions", {})
        active_positions = {t: s for t, s in positions.items() if s and s > 0.001}
        portfolio_tickers = list(active_positions.keys())
        
        warnings = hdb.get_staleness_warnings(portfolio_tickers)
        return {"warnings": warnings}
    except Exception as e:
        logging.error(f"Error fetching warnings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload")
async def upload_holdings_file(file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()
        filename = file.filename
        
        try:
            provider, suggested_name, df_norm = hparser.parse_holdings(file_bytes, filename)
            return {
                "status": "success",
                "is_synthetic": False,
                "provider": provider,
                "suggested_name": suggested_name,
                "data": df_norm.to_dict(orient="records")
            }
        except hparser.SyntheticETFWarning as syn:
            return {
                "status": "synthetic",
                "is_synthetic": True,
                "provider": syn.provider,
                "suggested_name": syn.suggested_name,
                "replication_method": syn.replication_method,
                "collateral_data": syn.df_collateral.to_dict(orient="records")
            }
    except Exception as e:
        logging.error(f"Error parsing file: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/save")
def save_holdings(req: SaveHoldingsRequest):
    try:
        import pandas as pd
        df = pd.DataFrame(req.df_records)
        
        hdb.invalidate_lookahead_cache()
        rows_saved = hdb.save_holdings(
            etf_ticker=req.etf_ticker,
            provider=req.provider,
            df=df,
            is_synthetic=req.is_synthetic,
            index_proxy_note=req.index_proxy_note
        )
        return {"status": "success", "rows_saved": rows_saved}
    except Exception as e:
        logging.error(f"Error saving holdings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/holdings/{ticker}")
def delete_holdings(ticker: str):
    try:
        hdb.delete_holdings(ticker)
        return {"status": "success"}
    except Exception as e:
        logging.error(f"Error deleting holdings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ignore")
def set_ignore(req: IgnoreRequest):
    try:
        hdb.set_ignore_look_through(req.etf_ticker, req.ignore)
        hdb.invalidate_lookahead_cache()
        return {"status": "success"}
    except Exception as e:
        logging.error(f"Error setting ignore flag: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status")
def get_status(account: str):
    try:
        df_cached, computed_at = hdb.get_lookahead_cache(account)
        return {"status": "success", "computed_at": computed_at}
    except Exception as e:
        logging.error(f"Error fetching status: {e}")
        return {"status": "success", "computed_at": None}

@router.post("/analysis")
def get_analysis(req: AnalysisRequest):
    try:
        cached_result = storage.load_latest_portfolio(req.account)
        if not cached_result:
            raise HTTPException(status_code=404, detail="No portfolio data found for account. Run calculation engine first.")
            
        positions = cached_result.get("positions", {})
        active_positions = {t: s for t, s in positions.items() if s and s > 0.001}
        df_prices = storage.load_last_prices(req.account)
        
        from backend.services.data_handler import get_account_base_currency, get_account_registry
        registry = get_account_registry()
        base_currency = get_account_base_currency(req.account, registry)
        currency_symbol = "€" if base_currency == "EUR" else ("$" if base_currency == "USD" else "£")
        
        if req.force_refresh:
            api_key = get_gemini_api_key()
            if api_key:
                engine.repair_unknown_metadata(api_key=api_key, _use_st=False)

        # Engine run
        results = engine.run_lookahead_analysis(
            positions=active_positions,
            df_prices=df_prices,
            account=req.account,
            force_refresh=req.force_refresh,
            api_key=get_gemini_api_key() or ""
        )
        
        # Convert DataFrames to dicts
        import numpy as np
        import pandas as pd
        
        def safe_df_to_dict(df):
            if isinstance(df, pd.DataFrame) and not df.empty:
                return df.replace({np.nan: None}).to_dict(orient="records")
            return []
            
        # Extract specific DataFrames from results
        df_overlap_matrix = results.get("df_overlap_matrix")
        overlap_matrix_data = {}
        if isinstance(df_overlap_matrix, pd.DataFrame) and not df_overlap_matrix.empty:
            overlap_matrix_data = {
                "labels": df_overlap_matrix.index.tolist(),
                "values": df_overlap_matrix.values.tolist()
            }
            
        def safe_head(df, n=100):
            if isinstance(df, pd.DataFrame) and not df.empty:
                return df.head(n)
            return df

        return {
            "status": "success",
            "base_currency": base_currency,
            "currency_symbol": currency_symbol,
            "computed_at": results.get("computed_at"),
            "from_cache": results.get("from_cache"),
            "df_sector": safe_df_to_dict(results.get("df_sector")),
            "df_geography": safe_df_to_dict(results.get("df_geography")),
            "df_top_holdings": safe_df_to_dict(results.get("df_top_holdings")),
            # Removed df_overlap_detail from main response since we fetch it via /overlap-pair
            "overlap_matrix": overlap_matrix_data,
            "df_movers_1d": safe_df_to_dict(safe_head(results.get("df_movers_1d"), 100)),
            "df_movers_1w": safe_df_to_dict(safe_head(results.get("df_movers_1w"), 100)),
        }
    except Exception as e:
        logging.error(f"Error running analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/overlap-pair")
def get_overlap_pair(req: OverlapPairRequest):
    try:
        df_cached, computed_at = hdb.get_lookahead_cache(req.account)
        if df_cached.empty:
            return {"status": "success", "data": []}
            
        df_filtered = df_cached[df_cached["etf_ticker"].isin([req.etf_a, req.etf_b])]
        detail_df = engine.compute_overlap_details(df_filtered)
        
        import numpy as np
        import pandas as pd
        def safe_df_to_dict(df):
            if isinstance(df, pd.DataFrame) and not df.empty:
                return df.replace({np.nan: None}).to_dict(orient="records")
            return []
            
        return {"status": "success", "data": safe_df_to_dict(detail_df)}
    except Exception as e:
        logging.error(f"Error computing overlap pair: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/fix-unknown")
def fix_unknown():
    try:
        res = engine.repair_unknown_metadata(api_key=get_gemini_api_key() or "", _use_st=False)
        return {"status": "success", "results": res}
    except Exception as e:
        logging.error(f"Error fixing unknown metadata: {e}")
        raise HTTPException(status_code=500, detail=str(e))
