import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.services import storage
from backend.services import screener

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])
logger = logging.getLogger(__name__)

class WatchlistAddRequest(BaseModel):
    ticker: str
    name: Optional[str] = None
    asset_class: Optional[str] = "Equity"
    notes: Optional[str] = None

@router.get("")
def list_watchlist():
    """Retrieve all active watchlist tickers."""
    try:
        items = storage.get_watchlist_tickers(active_only=True)
        return {"watchlist": items}
    except Exception as e:
        logger.error(f"Error fetching watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("")
def add_watchlist_ticker(req: WatchlistAddRequest):
    """Add a ticker to the watchlist."""
    ticker = req.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker is required.")
    
    name = req.name
    # If name not provided, attempt to look up via screener/yfinance metadata
    if not name:
        try:
            info = screener.load_or_fetch_metadata(ticker)
            name = info.get("shortName") or info.get("longName") or ticker
        except Exception:
            name = ticker

    success = storage.save_watchlist_ticker(
        ticker=ticker,
        name=name,
        asset_class=req.asset_class or "Equity",
        notes=req.notes
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save watchlist ticker.")
    
    return {"status": "success", "ticker": ticker, "name": name}

@router.delete("/{ticker}")
def delete_watchlist_ticker(ticker: str):
    """Remove a ticker from the watchlist."""
    ticker = ticker.strip().upper()
    success = storage.delete_watchlist_ticker(ticker)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete watchlist ticker.")
    return {"status": "success", "ticker": ticker}

@router.get("/universe")
def get_monitored_universe(account: str = "Consolidated"):
    """
    Returns the unified universe monitored for technical alerts:
    - holdings: current active portfolio positions
    - exited: positions exited within the last 12 months
    - watchlist: custom user-added candidate tickers
    """
    try:
        held = sorted(list(set(storage.get_currently_held_tickers(account))))
        exited_raw = screener.get_exited_tickers_last_12m(account)
        exited = sorted([t for t in exited_raw if t not in held])
        watchlist_items = storage.get_watchlist_tickers(active_only=True)
        watchlist_tickers = sorted([w["ticker"] for w in watchlist_items if w["ticker"] not in held and w["ticker"] not in exited])
        
        all_unique = sorted(list(set(held + exited + [w["ticker"] for w in watchlist_items])))
        
        return {
            "holdings": held,
            "exited": exited,
            "watchlist": watchlist_items,
            "all_monitored_tickers": all_unique
        }
    except Exception as e:
        logger.error(f"Error fetching monitored universe: {e}")
        raise HTTPException(status_code=500, detail=str(e))
