import threading
import datetime
import json
import logging
import traceback
from pathlib import Path
from backend.services.engine import run_recalculation_pipeline
from backend.services.data_handler import get_account_registry
from backend.services.file_utils import atomic_write_json

_AUTO_REFRESH_SCHEDULE_FILE = Path(__file__).parent / "backend_schedule.json"

_AUTO_REFRESH_DEFAULTS = {
    "auto_refresh_enabled": False,
    "auto_refresh_hour": 1,
    "auto_refresh_minute": 0,
}

# Maximum number of nightly run log entries to keep
_MAX_NIGHTLY_LOG_ENTRIES = 30

class AutoRefreshManager:
    def __init__(self):
        self.thread = None
        self.stop_event = None

_manager = AutoRefreshManager()

def get_auto_refresh_cfg() -> dict:
    cfg = dict(_AUTO_REFRESH_DEFAULTS)
    try:
        if _AUTO_REFRESH_SCHEDULE_FILE.exists():
            stored = json.loads(_AUTO_REFRESH_SCHEDULE_FILE.read_text())
            for k in _AUTO_REFRESH_DEFAULTS:
                if k in stored:
                    cfg[k] = stored[k]
            # also return status fields
            for k in ["auto_refresh_last_run", "auto_refresh_last_status", "auto_refresh_last_error"]:
                if k in stored:
                    cfg[k] = stored[k]
    except Exception as e:
        logging.warning(f"Failed to load schedule config: {e}")
    
    cfg["is_running"] = _manager.thread is not None and _manager.thread.is_alive() and not _manager.stop_event.is_set()
    return cfg

def save_auto_refresh_cfg(enabled: bool, hour: int, minute: int) -> None:
    try:
        existing: dict = {}
        if _AUTO_REFRESH_SCHEDULE_FILE.exists():
            existing = json.loads(_AUTO_REFRESH_SCHEDULE_FILE.read_text())
        existing["auto_refresh_enabled"] = enabled
        existing["auto_refresh_hour"] = hour
        existing["auto_refresh_minute"] = minute
        atomic_write_json(_AUTO_REFRESH_SCHEDULE_FILE, existing)
    except Exception as e:
        logging.warning(f"Could not save auto-refresh config: {e}")


def _append_nightly_log_entry(entry: dict) -> None:
    """Append a structured run log entry to nightly_run_log in the schedule JSON (rolling, max 30)."""
    try:
        existing: dict = {}
        if _AUTO_REFRESH_SCHEDULE_FILE.exists():
            existing = json.loads(_AUTO_REFRESH_SCHEDULE_FILE.read_text())
        
        log_entries = existing.get("nightly_run_log", [])
        # Prepend newest first
        log_entries.insert(0, entry)
        # Keep only the last N entries
        existing["nightly_run_log"] = log_entries[:_MAX_NIGHTLY_LOG_ENTRIES]
        
        atomic_write_json(_AUTO_REFRESH_SCHEDULE_FILE, existing)
    except Exception as e:
        logging.getLogger("auto_refresh").warning(f"Failed to append nightly log entry: {e}")


def get_nightly_run_log() -> list:
    """Return the stored nightly_run_log entries (newest first)."""
    try:
        if _AUTO_REFRESH_SCHEDULE_FILE.exists():
            stored = json.loads(_AUTO_REFRESH_SCHEDULE_FILE.read_text())
            return stored.get("nightly_run_log", [])
    except Exception:
        pass
    return []


def _recalculate_all_accounts(force_full_prices: bool = False, bypass_freshness: bool = False) -> tuple[list, dict]:
    """
    Run the recalculation pipeline for all accounts in the correct order.

    Returns
    -------
    (errors, run_entry)
        errors    : list of error strings (empty = all OK)
        run_entry : structured diagnostic log dict for this run
    """
    _log = logging.getLogger("auto_refresh")

    run_entry = {
        "run_start": datetime.datetime.now().isoformat(),
        "run_end": None,
        "triggered_by": "scheduler" if not force_full_prices else "dry_run",
        "force_full_prices": force_full_prices,
        "freshness_skipped": False,
        "cache_cleared": False,
        "owner": "backend",
        "pid": __import__('os').getpid(),
        "accounts_processed": [],
        "overall_status": "unknown",
        "db_sync_outcome": None,
    }

    registry = get_account_registry()
    if registry.empty:
        run_entry["overall_status"] = "error"
        run_entry["overall_error"] = "Registry is empty"
        run_entry["run_end"] = datetime.datetime.now().isoformat()
        return ["Registry is empty"], run_entry
        
    raw_accounts = registry["Account Name"].dropna().unique().tolist()
    
    # Ordered list: ISA → SIPP → others → Consolidated last
    accounts = []
    if "ISA" in raw_accounts:
        accounts.append("ISA")
    if "SIPP" in raw_accounts:
        accounts.append("SIPP")
    for a in raw_accounts:
        if a not in ("ISA", "SIPP", "Consolidated"):
            accounts.append(a)
    if not registry[registry["Classification"] == "Live"].empty:
        accounts.append("Consolidated")

    run_entry["account_order"] = accounts

    # --- Clear GSheet cache (matches what Streamlit Repair Mode does) ---
    # The Streamlit manual recalculate calls clear_gsheet_cache() before running.
    # Without this, the nightly run reads a 24h-old cached ledger from SQLite,
    # potentially missing dividends, cash deposits, or trades that arrived during the day.
    try:
        from backend.services.data_handler import clear_all_caches
        clear_all_caches()     # clears @cache_data decorators (registry, snapshot)
        run_entry["cache_cleared"] = True
        _log.info("Auto-refresh: GSheet cache cleared before recalculation")
    except Exception as cache_ex:
        _log.warning("Auto-refresh: cache clear failed: %s", cache_ex)
        run_entry["cache_clear_error"] = str(cache_ex)

    # --- Freshness check ---
    try:
        from backend.services import storage
        today_str = datetime.date.today().isoformat()
        run_log_df = storage.get_run_log(n=5)
        already_run_today = False
        if not run_log_df.empty:
            for _, row in run_log_df.iterrows():
                ts = row.get("run_timestamp")
                if ts and str(ts).startswith(today_str):
                    already_run_today = True
                    break
        if already_run_today and not force_full_prices and not bypass_freshness:
            _log.info("Auto-refresh: skipping recalculation since a run already occurred today.")
            run_entry["freshness_skipped"] = True
            run_entry["overall_status"] = "skipped"
            run_entry["run_end"] = datetime.datetime.now().isoformat()
            return [], run_entry
    except Exception as e:
        _log.warning(f"Auto-refresh: freshness check failed: {e}")
        run_entry["freshness_check_error"] = str(e)

    errs = []
    shared_price_cache = {}

    # Load newest benchmark definition to refresh during nightly auto-refresh run
    active_bm_name = None
    try:
        from backend.services import storage as _storage
        saved_defs = _storage.load_benchmark_definitions()
        if saved_defs:
            newest_def = sorted(saved_defs, key=lambda d: d.get("updated_at") or d.get("created_at") or "", reverse=True)[0]
            active_bm_name = newest_def.get("name")
    except Exception as bm_ex:
        _log.warning("Auto-refresh: could not load benchmark definitions: %s", bm_ex)

    for acct in accounts:
        acct_start = datetime.datetime.now().isoformat()
        acct_entry = {
            "account": acct,
            "start_time": acct_start,
            "end_time": None,
            "status": "unknown",
            "error": None,
            "force_full_prices": force_full_prices,
            # These will be populated via the engine audit after the run
            "snap_cash": None,
            "snap_qty_count": None,
            "legacy_adj": None,
            "ticker_count": None,
            "price_sources": {},
            "final_cash": None,
            "final_equity": None,
            "final_total_nav": None,
            "rows_written": None,
        }

        _log.info("Auto-refresh: starting recalculation for account=%s (force_full=%s)", acct, force_full_prices)

        try:
            # Pre-run: snapshot the run_log count so we can detect new rows
            try:
                from backend.services import storage as _storage
                pre_run_log = _storage.get_run_log(n=1)
                pre_run_last_id = int(pre_run_log.iloc[0].get("id", 0)) if not pre_run_log.empty else 0
            except Exception:
                pre_run_last_id = 0

            # Refresh all saved benchmarks for Consolidated (and use shared price cache)
            bm_name_to_pass = "__all__" if acct == "Consolidated" else None

            err = run_recalculation_pipeline(
                acct,
                force_full_prices=force_full_prices,
                active_bm_name=bm_name_to_pass,
                price_cache=shared_price_cache,
            )

            if err:
                acct_entry["status"] = "error"
                acct_entry["error"] = err
                errs.append(f"{acct}: {err}")
                _log.warning("Auto-refresh: account=%s failed: %s", acct, err)
            else:
                acct_entry["status"] = "success"
                _log.info("Auto-refresh: account=%s completed OK", acct)

                # --- Post-run diagnostics: read from engine audit ---
                try:
                    from backend.services import storage as _storage
                    audit = _storage.load_engine_audit(acct)
                    if audit:
                        acct_entry["snap_cash"] = audit.get("snapshot_cash")
                        snap_qty = audit.get("snapshot_quantities", {})
                        acct_entry["snap_qty_count"] = len(snap_qty) if isinstance(snap_qty, dict) else 0
                        acct_entry["legacy_adj"] = None  # not in audit currently
                        unique_tickers = audit.get("unique_tickers", [])
                        acct_entry["ticker_count"] = len(unique_tickers) if unique_tickers else 0
                        
                        # Price source breakdown
                        sources = audit.get("sources", {})
                        if sources:
                            from collections import Counter
                            counts = Counter(sources.values())
                            acct_entry["price_sources"] = dict(counts)
                        
                        # Multiplier anomalies (flag non-1.0 multipliers)
                        multipliers = audit.get("multipliers", {})
                        anomalous_mult = {t: m for t, m in multipliers.items() if m not in (1.0, None)}
                        if anomalous_mult:
                            acct_entry["multiplier_anomalies"] = anomalous_mult

                    # Read the most recent portfolio snapshot for this account
                    cached = _storage.load_latest_portfolio(acct)
                    if cached and cached.get("df_perf") is not None:
                        df_p = cached["df_perf"]
                        if not df_p.empty:
                            last_row = df_p.iloc[-1]
                            acct_entry["final_cash"] = float(last_row.get("Cash", last_row.get("Cash (£)", 0.0)) or 0.0)
                            acct_entry["final_equity"] = float(last_row.get("Equity", last_row.get("Equity (£)", 0.0)) or 0.0)
                            acct_entry["final_total_nav"] = float(last_row.get("Total NAV", last_row.get("Total NAV (£)", 0.0)) or 0.0)
                            acct_entry["snapshot_date"] = str(df_p.index[-1].date()) if hasattr(df_p.index[-1], "date") else str(df_p.index[-1])[:10]

                    # Count rows written
                    try:
                        post_run_log = _storage.get_run_log(n=5)
                        if not post_run_log.empty:
                            new_rows = post_run_log[post_run_log["id"] > pre_run_last_id]
                            acct_rows = new_rows[new_rows["account"] == acct]
                            if not acct_rows.empty:
                                acct_entry["rows_written"] = int(acct_rows["rows_written"].sum())
                    except Exception:
                        pass

                except Exception as audit_ex:
                    acct_entry["audit_read_error"] = str(audit_ex)
                    _log.warning("Auto-refresh: could not read audit for %s: %s", acct, audit_ex)

        except Exception as exc:
            acct_entry["status"] = "error"
            acct_entry["error"] = str(exc)
            acct_entry["traceback"] = traceback.format_exc()
            errs.append(f"{acct}: {exc}")
            _log.error("Auto-refresh: recalculation raised exception for %s: %s", acct, exc, exc_info=True)

        acct_entry["end_time"] = datetime.datetime.now().isoformat()
        run_entry["accounts_processed"].append(acct_entry)

    # DB sync
    try:
        from backend.services import storage as _storage
        status = _storage.get_run_log(n=1)  # just ping to check DB alive
        try:
            import backend.sync as sync
            sync_status = sync.get_db_connection_status()
            if sync_status.get("is_sync_capable"):
                local_write = sync_status.get("local_last_write")
                cloud_write = sync_status.get("cloud_last_write")

                def parse_ts(ts):
                    if not ts: return datetime.datetime.min
                    try: return datetime.datetime.fromisoformat(ts)
                    except Exception: return datetime.datetime.min

                l_dt = parse_ts(local_write)
                c_dt = parse_ts(cloud_write)

                if l_dt > c_dt:
                    _log.info("Auto-refresh: syncing local -> cloud (push)...")
                    result = sync.sync_local_to_cloud()
                    run_entry["db_sync_outcome"] = f"push: {result.get('status', 'done')}"
                elif c_dt > l_dt:
                    _log.info("Auto-refresh: syncing cloud -> local (pull)...")
                    result = sync.sync_cloud_to_local()
                    run_entry["db_sync_outcome"] = f"pull: {result.get('status', 'done')}"
                else:
                    run_entry["db_sync_outcome"] = "in_sync_no_action"
            else:
                run_entry["db_sync_outcome"] = "sync_not_capable"
        except Exception as sync_ex:
            run_entry["db_sync_outcome"] = f"error: {sync_ex}"
            _log.warning(f"Auto-refresh database sync failed: {sync_ex}")
    except Exception:
        pass

    # Downtrend alerts check
    try:
        from backend.services.alerts_service import check_downtrends
        from backend.services import storage as _storage
        
        all_positions = {}
        for acct in accounts:
            cached = _storage.load_latest_portfolio(acct)
            if cached and cached.get("positions"):
                for t, s in cached["positions"].items():
                    all_positions[t] = all_positions.get(t, 0.0) + s
                    
        check_downtrends(all_positions)
    except Exception as e:
        _log.warning(f"Auto-refresh: Downtrend alert check failed: {e}")

    # Specular Uptrend alerts check (Holdings + Exited + Watchlist)
    try:
        from backend.services.alerts_service import check_uptrends
        from backend.services import screener as _screener
        from backend.services import storage as _storage
        
        watchlist_items = _storage.get_watchlist_tickers(active_only=True)
        watchlist_tickers = [w["ticker"] for w in watchlist_items]
        exited_tickers = _screener.get_exited_tickers_last_12m()
        
        check_uptrends(
            positions=all_positions,
            watchlist_tickers=watchlist_tickers,
            exited_tickers=exited_tickers
        )
    except Exception as e:
        _log.warning(f"Auto-refresh: Uptrend alert check failed: {e}")

    # Proactive Screener Cache Warming
    try:
        warm_screener_cache()
    except Exception as e:
        _log.warning(f"Auto-refresh: Proactive cache warming failed: {e}")

    run_entry["overall_status"] = "error" if errs else "success"
    run_entry["run_end"] = datetime.datetime.now().isoformat()

    return errs, run_entry

def warm_screener_cache() -> None:
    """
    Proactively warms the screener cache for held tickers, benchmark constituents,
    recently exited tickers, and custom watchlist tickers to ensure daytime users hit a warm cache.
    """
    _log = logging.getLogger("auto_refresh")
    _log.info("Auto-refresh: starting proactive screener cache warming...")
    try:
        from backend.services import storage as _storage
        from backend.services import screener as _screener
        
        held = set(_storage.get_currently_held_tickers())
        exited = set(_screener.get_exited_tickers_last_12m())
        watchlist = set(w["ticker"] for w in _storage.get_watchlist_tickers(active_only=True))
        
        benchmarks = set()
        saved_defs = _storage.load_benchmark_definitions()
        for d in saved_defs:
            const = d.get("constituents", [])
            for c in const:
                if c.get("ticker"):
                    benchmarks.add(c["ticker"])
                    
        defaults = {"IUSA.L"}
        warm_tickers = held.union(exited).union(benchmarks).union(defaults).union(watchlist)
        _log.info(f"Auto-refresh: warming cache for {len(warm_tickers)} tickers: {warm_tickers}")
        
        today = datetime.date.today()
        start_date = today - datetime.timedelta(days=730)
        
        warmed_count = 0
        failed_count = 0
        
        for t in sorted(warm_tickers):
            if not t:
                continue
            try:
                # Get/fetch OHLCV and metadata
                df = _screener.get_ohlcv_for_ticker(t, start_date)
                info = _screener.load_or_fetch_metadata(t)
                if not df.empty:
                    warmed_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                failed_count += 1
                _log.warning(f"Auto-refresh: failed to warm cache for ticker {t}: {e}")
                
        _log.info(f"Auto-refresh: screener cache warming complete. Warmed: {warmed_count}, Failed: {failed_count}")
    except Exception as e:
        _log.error(f"Auto-refresh: screener cache warming failed: {e}")


def start_auto_refresh_thread(hour: int, minute: int) -> str:
    if _manager.stop_event:
        _manager.stop_event.set()

    stop_event = threading.Event()
    _manager.stop_event = stop_event
    fired_date_box = [None]

    def _loop():
        _log = logging.getLogger("auto_refresh")
        while not stop_event.is_set():
            now = datetime.datetime.now()
            today = now.date()
            target = datetime.time(hour, minute)
            now_time = now.time().replace(second=0, microsecond=0)
            
            delta = abs((datetime.datetime.combine(today, now_time) - datetime.datetime.combine(today, target)).total_seconds())
            
            if delta <= 30 and fired_date_box[0] != today:
                _log.info("Auto-refresh: firing recalculation at %s", now.strftime("%H:%M"))
                try:
                    errs, run_entry = _recalculate_all_accounts(force_full_prices=False)
                    fired_date_box[0] = today
                    
                    # Persist structured run entry
                    _append_nightly_log_entry(run_entry)

                    try:
                        cfg = {}
                        if _AUTO_REFRESH_SCHEDULE_FILE.exists():
                            cfg = json.loads(_AUTO_REFRESH_SCHEDULE_FILE.read_text())
                        cfg["auto_refresh_last_run"] = now.isoformat()
                        if errs:
                            _log.warning("Auto-refresh: errors — %s", "; ".join(errs))
                            cfg["auto_refresh_last_status"] = "error"
                            cfg["auto_refresh_last_error"] = "; ".join(errs)
                        else:
                            _log.info("Auto-refresh: all accounts recalculated OK")
                            cfg["auto_refresh_last_status"] = "success"
                            cfg["auto_refresh_last_error"] = None
                        atomic_write_json(_AUTO_REFRESH_SCHEDULE_FILE, cfg)
                    except Exception:
                        pass
                except Exception as exc:
                    _log.error("Auto-refresh: recalculation failed: %s", exc, exc_info=True)
                    try:
                        cfg = {}
                        if _AUTO_REFRESH_SCHEDULE_FILE.exists():
                            cfg = json.loads(_AUTO_REFRESH_SCHEDULE_FILE.read_text())
                        cfg["auto_refresh_last_run"] = now.isoformat()
                        cfg["auto_refresh_last_status"] = "error"
                        cfg["auto_refresh_last_error"] = str(exc)
                        atomic_write_json(_AUTO_REFRESH_SCHEDULE_FILE, cfg)
                    except Exception:
                        pass
            stop_event.wait(timeout=60)

    t = threading.Thread(target=_loop, daemon=True, name="auto_refresh")
    t.start()
    _manager.thread = t
    return f"Auto-refresh active — runs daily at {hour:02d}:{minute:02d}"

def stop_auto_refresh_thread():
    if _manager.stop_event:
        _manager.stop_event.set()
    _manager.thread = None
    _manager.stop_event = None

def ensure_auto_refresh_running() -> None:
    cfg = get_auto_refresh_cfg()
    if not cfg.get("auto_refresh_enabled"):
        return
    
    if _manager.thread is None or not _manager.thread.is_alive():
        start_auto_refresh_thread(
            cfg.get("auto_refresh_hour", 1),
            cfg.get("auto_refresh_minute", 0),
        )
