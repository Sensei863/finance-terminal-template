from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import datetime

from backend.services import newsletter_service
from backend.services.data_handler import get_account_registry

router = APIRouter(prefix="/api/newsletter", tags=["newsletter"])

@router.get("/products")
def get_products():
    """Load newsletter products and configurations."""
    products = newsletter_service._load_all_products()
    return {"products": products}

@router.get("/snapshots")
def get_snapshots():
    """Get available knowledge bank snapshots."""
    folders = newsletter_service._find_snapshot_folders()
    res = []
    for f, dt in folders:
        res.append({
            "path": str(f),
            "name": f.name,
            "date": dt.strftime("%Y-%m-%d %H:%M")
        })
    return {"snapshots": res}

class PreviewRequest(BaseModel):
    product: Dict[str, Any]
    accounts: List[str]
    chosen_folder: Optional[str] = None

@router.post("/preview-prompt")
def preview_prompt(req: PreviewRequest):
    """Assemble data and return the raw prompt preview."""
    import pandas as pd
    
    today = datetime.date.today()
    period_start = today - datetime.timedelta(days=7)
    
    # We set the accounts on the product object
    prod = req.product
    prod["accounts"] = req.accounts

    import pathlib
    folder = pathlib.Path(req.chosen_folder) if req.chosen_folder and req.chosen_folder != "auto" else None

    data = newsletter_service.assemble_newsletter_data(
        prod, 
        chosen_folder=folder,
        df_prices=None
    )
    if data is None:
        raise HTTPException(status_code=400, detail="Assemble data failed. Check if accounts have data.")
        
    ft, ts, fs = newsletter_service.pick_featured_ticker(data["all_pos"], pd.DataFrame(), data["ohlcv_data"])
    fn = data["names"].get(ft, ft)
    
    from backend.services.technicals_service import _build_prompt as _tech_prompt
    tech_str = _tech_prompt(ts) if ts else "No technical data."
    
    if prod.get("language") == "it":
        prompt = newsletter_service._build_prompt_it(
            data["accounts_used"], data["stats_map"], data["ticker_ctx"], data["ranked_pnl"],
            tech_str,
            ft, fn, fs, data["articles"], today, period_start,
            iusa_stats=data.get("iusa_stats"), benchmark_stats=data.get("benchmark_stats")
        )
    else:
        prompt = newsletter_service._build_prompt(
            data["accounts_used"], data["stats_map"], data["ticker_ctx"], data["ranked_pnl"],
            tech_str,
            ft, fn, fs, data["articles"], today, period_start,
            iusa_stats=data.get("iusa_stats"), benchmark_stats=data.get("benchmark_stats")
        )
        
    return {"prompt": prompt, "featured_ticker": ft, "featured_signals": fs, "articles_count": data["n_art"]}

class GenerateRequest(BaseModel):
    product: Dict[str, Any]
    accounts: List[str]
    chosen_folder: Optional[str] = None

@router.post("/generate")
def generate_newsletter(req: GenerateRequest):
    """Run the full newsletter generation pipeline and return HTML."""
    try:
        from backend.routers.ingestion import get_gemini_api_key
        api_key = get_gemini_api_key()
        
        # Override st.session_state so the underlying function works without Streamlit UI
        import streamlit as st
        if not hasattr(st, "session_state"):
            st.session_state = {}
        st.session_state["gemini_api_key_input"] = api_key
        
        prod = req.product
        prod["accounts"] = req.accounts
        
        # Instead of _run_newsletter_from_thread, we just assemble and build
        # _run_newsletter_from_thread also sends the email, which we may not want right away
        # But wait, user requested to generate it. Let's return the HTML.
        import datetime
        import pandas as pd
        today = datetime.date.today()
        period_start = today - datetime.timedelta(days=7)
        
        import pathlib
        folder = pathlib.Path(req.chosen_folder) if req.chosen_folder and req.chosen_folder != "auto" else None

        data = newsletter_service.assemble_newsletter_data(prod, chosen_folder=folder, df_prices=None)
        if data is None:
            raise HTTPException(status_code=400, detail="Data assembly failed.")
            
        ft, ts, fs = newsletter_service.pick_featured_ticker(data["all_pos"], pd.DataFrame(), data["ohlcv_data"])
        fn = data["names"].get(ft, ft)
        
        digest_brief = None
        if data.get("articles") and newsletter_service._is_pm_digest(data["articles"]):
            digest_brief = newsletter_service.distil_digest(data["articles"], api_key)
            
        from backend.services.technicals_service import _build_prompt as _tech_prompt
        tech_str = _tech_prompt(ts) if ts else "No technical data."
        
        if prod.get("language") == "it":
            prompt = newsletter_service._build_prompt_it(
                data["accounts_used"], data["stats_map"], data["ticker_ctx"], data["ranked_pnl"],
                tech_str, ft, fn, fs, data["articles"], today, period_start,
                iusa_stats=data.get("iusa_stats"), benchmark_stats=data.get("benchmark_stats"),
                digest_brief=digest_brief
            )
        else:
            prompt = newsletter_service._build_prompt(
                data["accounts_used"], data["stats_map"], data["ticker_ctx"], data["ranked_pnl"],
                tech_str, ft, fn, fs, data["articles"], today, period_start,
                iusa_stats=data.get("iusa_stats"), benchmark_stats=data.get("benchmark_stats"),
                digest_brief=digest_brief
            )
            
        content = newsletter_service.generate_content(prompt, api_key)
        
        weekly_trades = newsletter_service._load_weekly_trades(data["accounts_used"])
        final_html = newsletter_service.build_html(
            prod, stats_map=data["stats_map"],
            content=content, technicals=ts,
            featured_ticker=ft, featured_name=fn, featured_signals=fs,
            ranked_pnl_all=data["ranked_pnl"],
            report_date=today, period_start=period_start,
            iusa_stats=data.get("iusa_stats"), benchmark_stats=data.get("benchmark_stats"),
            weekly_trades=weekly_trades,
            digest_brief=digest_brief,
        )
        return {"html": final_html}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ScheduleConfig(BaseModel):
    product_id: str
    day: str
    hour: int
    minute: int
    enabled: bool
    refresh_hours: int
    additional_recipients: List[str]

@router.post("/schedule")
def update_schedule(cfg: ScheduleConfig):
    """Save the schedule and restart the background thread."""
    newsletter_service._save_schedule(cfg.model_dump(), cfg.product_id)
    msg = newsletter_service._update_task_scheduler()
    return {"status": "success", "message": msg}

@router.post("/send")
def send_newsletter(req: dict):
    html = req.get("html")
    subject = req.get("subject", "Weekly Investor Letter")
    recipients = req.get("recipients", [])
    if not html:
        raise HTTPException(status_code=400, detail="Missing html payload.")
    
    ok = newsletter_service.send_email(html, subject, recipients=recipients, _from_thread=True)
    if not ok:
        raise HTTPException(status_code=500, detail="Email sending failed.")
    return {"status": "success"}

class UpdateAccountsRequest(BaseModel):
    product_id: str
    accounts: List[str]

@router.post("/update-accounts")
def update_accounts(req: UpdateAccountsRequest):
    """Update the accounts list for a product configuration and persist it."""
    products = newsletter_service._load_all_products()
    for p in products:
        if p.get("product_id") == req.product_id:
            p["accounts"] = req.accounts
            break
    newsletter_service._save_all_products(products)
    return {"status": "success"}

class UpdateProductConfigRequest(BaseModel):
    product_id: str
    accounts: Optional[List[str]] = None
    synthetic_benchmark: Optional[str] = None
    benchmark_label: Optional[str] = None

@router.post("/update-product-config")
def update_product_config(req: UpdateProductConfigRequest):
    """Update general product configuration fields and persist them."""
    products = newsletter_service._load_all_products()
    for p in products:
        if p.get("product_id") == req.product_id:
            if req.accounts is not None:
                p["accounts"] = req.accounts
            if req.synthetic_benchmark is not None:
                p["synthetic_benchmark"] = req.synthetic_benchmark
            if req.benchmark_label is not None:
                p["benchmark_label"] = req.benchmark_label
            break
    newsletter_service._save_all_products(products)
    return {"status": "success", "products": products}

class GenerateAndSendRequest(BaseModel):
    product: Dict[str, Any]
    accounts: List[str]
    chosen_folder: Optional[str] = None

@router.post("/generate-and-send")
def generate_and_send_newsletter(req: GenerateAndSendRequest):
    """Run the full newsletter generation and sending pipeline in one call."""
    try:
        from backend.routers.ingestion import get_gemini_api_key
        api_key = get_gemini_api_key()
        
        # Override st.session_state for headless operation
        import streamlit as st
        if not hasattr(st, "session_state"):
            st.session_state = {}
        st.session_state["gemini_api_key_input"] = api_key
        
        prod = req.product
        prod["accounts"] = req.accounts
        import pathlib
        folder = pathlib.Path(req.chosen_folder) if req.chosen_folder and req.chosen_folder != "auto" else None
        
        newsletter_service._run_newsletter_from_thread(prod, chosen_folder=folder)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
