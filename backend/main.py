import sys
import os
import logging
import shutil
from pathlib import Path
from typing import Optional

# Add parent directory to path so we can import the original modules
from dotenv import load_dotenv
load_dotenv()

import warnings
warnings.filterwarnings('ignore', category=UserWarning, message='.*pandas only supports SQLAlchemy connectable.*')

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from backend.services import engine
from backend.services import data_handler
from backend.services import storage

from fastapi.middleware.cors import CORSMiddleware
from backend.routers import screener, portfolio, ingestion, system, newsletter, lookthrough, diagnostics, optimization, factors, watchlist
from backend import scheduler

app = FastAPI(title="Finance Tool API")

# Setup CORS
allowed_origins_str = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
allowed_origins = [origin.strip() for origin in allowed_origins_str.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(screener.router)
app.include_router(portfolio.router)
app.include_router(ingestion.router)
app.include_router(system.router)
app.include_router(newsletter.router)
app.include_router(lookthrough.router)
app.include_router(diagnostics.router)
app.include_router(optimization.router)
app.include_router(factors.router)
app.include_router(watchlist.router)

@app.on_event("startup")
def startup_event():
    from backend.services import newsletter_service
    from backend.services import holdings_db
    # Initialize schemas dynamically on startup (safe for Postgres & SQLite)
    try:
        storage.init_db()
        holdings_db.init_db()
        print("Database schemas initialized successfully.")
    except Exception as db_err:
        print(f"Error initializing database schemas: {db_err}")
        
    # Startup DB sync is disabled — the app connects to Cloud DB natively.
    # get_db_connection_status() always returns is_sync_capable=False and
    # opening a raw connection here burns a PgBouncer slot at the worst moment.
    print("Startup: Using Cloud DB natively (sync check skipped).")

    scheduler.ensure_auto_refresh_running()
    newsletter_service._update_task_scheduler()
    print("Application startup complete.")

class RecalculateRequest(BaseModel):
    account_view: str
    force_full_prices: bool = False
    active_bm_name: Optional[str] = None

class AccountRequest(BaseModel):
    account_name: str
    classification: str
    base_currency: str

@app.post("/api/portfolio/simulate_benchmark")
def simulate_benchmark(req: RecalculateRequest):
    try:
        engine.run_recalculation_pipeline(
            req.account_view,
            force_full_prices=req.force_full_prices,
            active_bm_name=req.active_bm_name
        )
        return {"status": "success", "message": f"Simulated benchmark {req.active_bm_name}"}
    except Exception as e:
        logging.error(f"Error simulating benchmark: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/accounts/create")
def create_account(req: AccountRequest):
    worksheet_name = f"{req.account_name.strip().replace(' ', '_')}_Ledger"
    success, error_msg = data_handler.add_account_to_registry(
        req.account_name.strip(), 
        worksheet_name, 
        req.classification, 
        req.base_currency
    )
    if success:
        return {"status": "success"}
    else:
        raise HTTPException(status_code=400, detail=error_msg)

@app.delete("/api/accounts/{account_name}")
def delete_account(account_name: str):
    success, error_msg = data_handler.delete_account_from_registry(account_name)
    if success:
        return {"status": "success"}
    else:
        raise HTTPException(status_code=400, detail=error_msg)

@app.post("/api/cache/flush")
def flush_cache(req: RecalculateRequest):
    try:
        storage.clear_account_data(req.account_view)
        return {"status": "success", "message": "Database cache cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.get("/")
def root_check():
    return {"status": "ok", "message": "API is running"}

