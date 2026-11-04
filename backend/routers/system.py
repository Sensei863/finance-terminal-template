import re
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/system", tags=["System"])

class SecretsUpdate(BaseModel):
    gemini_api_key: str

def get_secrets_path() -> Path:
    """Resolve the .streamlit/secrets.toml path from the project root."""
    return Path(__file__).parent.parent.parent / ".streamlit" / "secrets.toml"

@router.get("/secrets")
def get_secrets():
    """Retrieve a masked preview of the Gemini API Key (never expose raw secret)."""
    try:
        from backend.config import get_secrets as load_config_secrets
        secrets = load_config_secrets()
        api_key = str(
            secrets.get("gemini_api_key")
            or secrets.get("connections", {}).get("gsheets", {}).get("gemini_api_key", "")
            or ""
        ).strip()
        if len(api_key) > 8:
            masked = f"{api_key[:4]}...{api_key[-4:]}"
        elif api_key:
            masked = "****"
        else:
            masked = ""
        return {"gemini_api_key": masked, "configured": bool(api_key)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read secrets: {e}")

@router.post("/secrets")
def update_secrets(payload: SecretsUpdate):
    """Safely rewrite the gemini_api_key in secrets.toml."""
    if "..." in payload.gemini_api_key or payload.gemini_api_key == "****":
        return {"status": "success", "message": "API Key unchanged"}
    path = get_secrets_path()
    
    lines = []
    found = False
    
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read secrets: {e}")
            
    # Iterate and replace the key if found
    for i, line in enumerate(lines):
        if line.strip().startswith("gemini_api_key"):
            lines[i] = f'gemini_api_key = "{payload.gemini_api_key}"\n'
            found = True
            break
            
    if not found:
        # If not found, append to the file
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.append(f'gemini_api_key = "{payload.gemini_api_key}"\n')
        
    # Ensure directory exists
    path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write secrets: {e}")
        
    return {"status": "success", "message": "API Key updated successfully"}

from backend.services import storage
import backend.scheduler as scheduler

@router.get("/benchmarks")
def get_benchmarks():
    """Get all saved synthetic benchmarks."""
    try:
        bms = storage.load_benchmark_definitions()
        return {"benchmarks": bms}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/schedule")
def get_schedule():
    """Get auto-refresh configuration."""
    try:
        cfg = scheduler.get_auto_refresh_cfg()
        return cfg
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ScheduleUpdate(BaseModel):
    enabled: bool
    hour: int
    minute: int

@router.post("/schedule")
def update_schedule(payload: ScheduleUpdate):
    """Update auto-refresh configuration."""
    try:
        scheduler.save_auto_refresh_cfg(payload.enabled, payload.hour, payload.minute)
        if payload.enabled:
            scheduler.start_auto_refresh_thread(payload.hour, payload.minute)
        else:
            scheduler.stop_auto_refresh_thread()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/logs")
def get_logs():
    """Get latest storage run logs."""
    try:
        df = storage.get_run_log(20)
        logs = df.to_dict(orient="records") if not df.empty else []
        return {"logs": logs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from pydantic import BaseModel
class SyncRequest(BaseModel):
    direction: str # "push" or "pull"

@router.get("/db-status")
def get_db_status():
    """Retrieve current DB connection and sync metadata."""
    try:
        import backend.sync as sync
        return sync.get_db_connection_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/db-sync")
def trigger_db_sync(req: SyncRequest):
    """Trigger a database sync in the specified direction."""
    try:
        import backend.sync as sync
        if req.direction == "push":
            res = sync.sync_local_to_cloud()
        elif req.direction == "pull":
            res = sync.sync_cloud_to_local()
        else:
            raise HTTPException(status_code=400, detail="Invalid sync direction. Use 'push' or 'pull'.")
            
        if res.get("status") == "error":
            raise HTTPException(status_code=500, detail=res.get("message"))
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nightly-log")
def get_nightly_log():
    """Return the structured nightly auto-refresh run log (newest first, max 30 entries)."""
    try:
        from backend.scheduler import get_nightly_run_log
        entries = get_nightly_run_log()
        return {"entries": entries, "count": len(entries)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class DryRunRequest(BaseModel):
    force_full_prices: bool = False
    bypass_freshness: bool = False


@router.post("/trigger-nightly-dry-run")
def trigger_nightly_dry_run(payload: DryRunRequest):
    """
    Trigger _recalculate_all_accounts() on demand and return a structured diagnostic log.

    Set force_full_prices=True to simulate Repair Mode (full price re-download).
    Set force_full_prices=False to simulate the normal nightly run (incremental delta).

    The resulting run_entry is also appended to the nightly_run_log so it persists.
    The freshness check is NOT bypassed automatically — pass force_full_prices=True
    to override it (mimicking repair mode behaviour which always runs).
    """
    try:
        from backend.scheduler import _recalculate_all_accounts, _append_nightly_log_entry

        errs, run_entry = _recalculate_all_accounts(
            force_full_prices=payload.force_full_prices,
            bypass_freshness=payload.bypass_freshness,
        )
        run_entry["triggered_by"] = f"manual_dry_run (force_full={payload.force_full_prices}, bypass_freshness={payload.bypass_freshness})"

        # Persist to rolling log
        _append_nightly_log_entry(run_entry)

        return {
            "status": "success" if not errs else "partial_error",
            "errors": errs,
            "run_entry": run_entry,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/alerts-state")
def get_alerts_state():
    """Retrieve the downtrend alerts state."""
    try:
        state_path = Path(__file__).parent.parent.parent / "downtrend_alerts_state.json"
        if state_path.exists():
            import json
            return json.loads(state_path.read_text())
        return {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/test-alert")
def send_test_alert():
    """Trigger a test downtrend alert email."""
    try:
        from backend.services.alerts_service import _send_email, _build_email_html
        test_alert = [{"ticker": "TEST.L", "price": 100.0, "new_signals": ["Test Signal"]}]
        html = _build_email_html(test_alert, title="Test Alert", is_recap=False)
        _send_email("Test Alert: System Check", html)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/preview-alert")
def preview_alert():
    """Returns the HTML for a test downtrend alert."""
    try:
        from backend.services.alerts_service import _build_email_html
        test_alert = [{"ticker": "TEST.L", "price": 100.0, "new_signals": ["Test Signal"]}]
        html = _build_email_html(test_alert, title="Test Alert", is_recap=False)
        return {"html": html}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/alerts-config")
def get_alerts_config():
    """Retrieve the downtrend alerts configuration."""
    try:
        config_path = Path(__file__).parent.parent.parent / "downtrend_alerts_config.json"
        if config_path.exists():
            import json
            return json.loads(config_path.read_text())
        return {
            "enable_weekly_recap": True,
            "recap_day": 4, # Friday
            "recap_hour": 18, # 6 PM
            "threshold_rsi": 45
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/alerts-config")
def set_alerts_config(payload: dict):
    """Set the downtrend alerts configuration."""
    try:
        config_path = Path(__file__).parent.parent.parent / "downtrend_alerts_config.json"
        import json
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(payload, indent=2))
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/uptrend-alerts-state")
def get_uptrend_alerts_state():
    """Retrieve the uptrend alerts state."""
    try:
        state_path = Path(__file__).parent.parent.parent / "uptrend_alerts_state.json"
        if state_path.exists():
            import json
            return json.loads(state_path.read_text())
        return {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/test-uptrend-alert")
def send_test_uptrend_alert():
    """Trigger a test uptrend alert email."""
    try:
        from backend.services.alerts_service import _send_email, _build_email_html
        test_alert = [
            {"ticker": "TEST.L", "price": 125.50, "new_signals": ["Golden Cross (SMA50 > SMA200)", "MACD Bullish Crossover", "Volume Surge (1.8x 20d Avg)"], "origin": "WATCHLIST", "commentary": "Strong upward momentum confirmed by institutional volume surge and moving average breakout."}
        ]
        html = _build_email_html(test_alert, title="Test Uptrend Alert", is_recap=False, is_uptrend=True)
        _send_email("Test Alert: Uptrend System Check", html)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/preview-uptrend-alert")
def preview_uptrend_alert():
    """Returns the HTML for a test uptrend alert."""
    try:
        from backend.services.alerts_service import _build_email_html
        test_alert = [
            {"ticker": "VUAG.L", "price": 89.20, "new_signals": ["Golden Cross (SMA50 > SMA200)", "MACD Bullish Crossover", "Volume Surge (1.7x 20d Avg)"], "origin": "HOLDING", "commentary": "Consolidation phase has completed with a decisive expansion above the 50-day moving average. Structural trend posture remains firmly bullish."},
            {"ticker": "IQQH.DE", "price": 14.35, "new_signals": ["Composite (RSI > 55 & Price > SMA50)", "MACD Bullish Crossover"], "origin": "WATCHLIST", "commentary": "Momentum oscillators indicate accelerating buying interest following an extended base breakout."}
        ]
        html = _build_email_html(test_alert, title="Technical Uptrend & Breakout Alert", is_recap=False, is_uptrend=True)
        return {"html": html}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/uptrend-alerts-config")
def get_uptrend_alerts_config():
    """Retrieve the uptrend alerts configuration."""
    try:
        config_path = Path(__file__).parent.parent.parent / "uptrend_alerts_config.json"
        if config_path.exists():
            import json
            return json.loads(config_path.read_text())
        return {
            "enable_weekly_recap": False,
            "recap_day": 4, # Friday
            "recap_hour": 18, # 6 PM
            "threshold_rsi": 55,
            "volume_surge_multiplier": 1.5
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/uptrend-alerts-config")
def set_uptrend_alerts_config(payload: dict):
    """Set the uptrend alerts configuration."""
    try:
        config_path = Path(__file__).parent.parent.parent / "uptrend_alerts_config.json"
        import json
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(payload, indent=2))
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



class PromptsUpdate(BaseModel):
    prompts: dict

def validate_prompt_template(prompt_key: str, template: str):
    # Count braces matching
    if template.count("{{") != template.count("}}"):
        raise ValueError("Mismatched double braces '{{' and '}}'. Ensure every opening '{{' has a closing '}}'.")
        
    # Find all placeholder contents
    placeholders = re.findall(r"\{\{([^}]+)\}\}", template)
    
    from backend.services.screener import VALID_PROMPT_PLACEHOLDERS
    valid_keys = VALID_PROMPT_PLACEHOLDERS.get(prompt_key)
    if valid_keys is None:
        raise ValueError(f"Unknown prompt type: {prompt_key}")
        
    for p in placeholders:
        p_clean = p.strip()
        if not re.match(r"^[a-zA-Z0-9_]+$", p_clean):
            raise ValueError(f"Invalid placeholder name: '{{{{{p}}}}}'. Only alphanumeric characters and underscores are allowed.")
        if p_clean not in valid_keys:
            raise ValueError(f"Unrecognized placeholder: '{{{{{p_clean}}}}}'. Valid placeholders for this prompt are: {', '.join(sorted(valid_keys))}")

@router.get("/prompts")
def get_prompts():
    """Retrieve current, default, and valid placeholders for all prompts."""
    try:
        from backend.services.screener import (
            DEFAULT_PROMPT_TEMPLATES, 
            VALID_PROMPT_PLACEHOLDERS,
            load_prompt
        )
        active = {key: load_prompt(key) for key in DEFAULT_PROMPT_TEMPLATES}
        placeholders = {key: list(val) for key, val in VALID_PROMPT_PLACEHOLDERS.items()}
        return {
            "active": active,
            "defaults": DEFAULT_PROMPT_TEMPLATES,
            "placeholders": placeholders
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/prompts")
def update_prompts(payload: PromptsUpdate):
    """Validate and save custom prompt templates."""
    try:
        from backend.services.screener import (
            DEFAULT_PROMPT_TEMPLATES,
            get_prompts_config_path,
            init_prompts_config
        )
        init_prompts_config()
        config_path = get_prompts_config_path()
        import json
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            
        for key, template in payload.prompts.items():
            if key not in DEFAULT_PROMPT_TEMPLATES:
                raise HTTPException(status_code=400, detail=f"Invalid prompt key: {key}")
            try:
                validate_prompt_template(key, template)
            except ValueError as ve:
                raise HTTPException(status_code=400, detail=str(ve))
            cfg[key] = template
            
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
            
        return {"status": "success", "message": "Prompts updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/prompts/reset")
def reset_prompts(payload: dict):
    """Reset one or all prompts to defaults."""
    try:
        from backend.services.screener import (
            DEFAULT_PROMPT_TEMPLATES,
            get_prompts_config_path,
            init_prompts_config
        )
        init_prompts_config()
        config_path = get_prompts_config_path()
        import json
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            
        prompt_key = payload.get("prompt_key")
        if prompt_key:
            if prompt_key not in DEFAULT_PROMPT_TEMPLATES:
                raise HTTPException(status_code=400, detail=f"Invalid prompt key: {prompt_key}")
            cfg[prompt_key] = DEFAULT_PROMPT_TEMPLATES[prompt_key]
        else:
            cfg = DEFAULT_PROMPT_TEMPLATES.copy()
            
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
            
        return {"status": "success", "message": "Prompts reset successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


