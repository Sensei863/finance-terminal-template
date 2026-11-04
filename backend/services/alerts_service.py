import os
import json
import smtplib
import datetime
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
import numpy as np

from backend.services.technicals_service import _fetch_ohlcv, _build_technical_snapshot
from backend.services import currency_utils
from backend.services import gemini_util
from backend.config import get_secrets
from backend.services.file_utils import atomic_write_json

# Config
_ALERTS_STATE_FILE = Path(__file__).parent.parent.parent / "downtrend_alerts_state.json"
_ALERTS_CONFIG_FILE = Path(__file__).parent.parent.parent / "downtrend_alerts_config.json"
_UPTREND_STATE_FILE = Path(__file__).parent.parent.parent / "uptrend_alerts_state.json"
_UPTREND_CONFIG_FILE = Path(__file__).parent.parent.parent / "uptrend_alerts_config.json"

_sec = get_secrets()
SENDER_EMAIL = os.environ.get("SENDER_EMAIL") or os.environ.get("sender_email") or _sec.get("sender_email", "")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL") or os.environ.get("recipient_email") or _sec.get("recipient_email", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD") or os.environ.get("gmail_app_password") or _sec.get("gmail_app_password", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or _sec.get("gemini_api_key", "")

def _generate_gemini_summary(ticker: str, price: float, signals: list, snap: dict) -> str:
    """Uses Gemini to generate a brief 2-3 sentence technical explanation."""
    prompt = f"""You are a quantitative technical analyst for a family office.
A security in our portfolio has just triggered technical downtrend alerts.

Security: {ticker} (Current Price: {price:.2f})
Triggered Signals: {', '.join(signals)}

Technical Snapshot Context:
- SMA50: {snap.get('sma50', 'N/A')}
- SMA200: {snap.get('sma200', 'N/A')}
- RSI (14-day): {snap.get('rsi_now', 'N/A')} ({snap.get('rsi_trend', 'N/A')})
- MACD Signal: {snap.get('macd_cross', 'N/A')}

Write a concise, 2-to-3 sentence explanation of what these specific metrics mean for the asset's near-term price action. Do not give financial advice. Just explain the technical posture simply but professionally. No markdown formatting like bolding or headers."""
    
    try:
        model = gemini_util.get_best_gemini_model(GEMINI_API_KEY)
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logging.error(f"Gemini generation failed for {ticker}: {e}")
        return "Technical metrics suggest deteriorating near-term momentum and structural weakness."


def _generate_gemini_uptrend_summary(ticker: str, price: float, signals: list, snap: dict, origin: str = "HOLDING") -> str:
    """Uses Gemini to generate a brief 2-3 sentence technical explanation for uptrend breakouts."""
    context_desc = "in our portfolio" if origin == "HOLDING" else "on our monitoring watchlist (recently exited position)" if origin == "EXITED" else "on our candidate watchlist"
    prompt = f"""You are a quantitative technical analyst for a family office.
A security {context_desc} has just confirmed bullish uptrend / breakout signals.

Security: {ticker} (Current Price: {price:.2f})
Triggered Signals: {', '.join(signals)}

Technical Snapshot Context:
- SMA50: {snap.get('sma50', 'N/A')}
- SMA200: {snap.get('sma200', 'N/A')}
- RSI (14-day): {snap.get('rsi_now', 'N/A')} ({snap.get('rsi_trend', 'N/A')})
- MACD Signal: {snap.get('macd_cross', 'N/A')}
- Volume vs 20d Avg: {snap.get('vol_ratio', 'N/A')}

Write a concise, 2-to-3 sentence explanation of what these specific metrics mean for the asset's near-term strength and momentum continuation. Do not give financial advice. Just explain the technical posture simply but professionally. No markdown formatting like bolding or headers."""

    try:
        model = gemini_util.get_best_gemini_model(GEMINI_API_KEY)
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logging.error(f"Gemini uptrend generation failed for {ticker}: {e}")
        return "Technical metrics indicate strengthening momentum and structural upward trend continuation."



def check_downtrends(positions: dict):
    """
    Evaluates technical downtrends for all given positions.
    Fires an email alert for newly triggered signals.
    Sends a weekly recap based on the configured schedule.
    """
    if not positions:
        return

    tickers = list(positions.keys())
    ohlcv_data = _fetch_ohlcv(tuple(tickers))
    
    # Load state
    state = {}
    if _ALERTS_STATE_FILE.exists():
        try:
            state = json.loads(_ALERTS_STATE_FILE.read_text())
        except Exception:
            state = {}

    # Load config
    config = {
        "enable_weekly_recap": True,
        "recap_day": 4, # Friday
        "recap_hour": 18, # 6 PM
        "threshold_rsi": 45
    }
    if _ALERTS_CONFIG_FILE.exists():
        try:
            saved_config = json.loads(_ALERTS_CONFIG_FILE.read_text())
            config.update(saved_config)
        except Exception:
            pass
            
    triggered_alerts = []
    current_downtrends = []
    
    for ticker, shares in positions.items():
        if ticker not in ohlcv_data or shares <= 0:
            continue
            
        ohlcv_corrected = currency_utils.normalize_ohlcv(ticker, ohlcv_data[ticker])
        try:
            snap = _build_technical_snapshot(ohlcv_corrected, ticker, shares)
        except Exception as e:
            logging.warning(f"Error building snapshot for {ticker} in alerts_service: {e}")
            continue
            
        # Option B: Death Cross
        sma50 = snap.get('sma50', np.nan)
        sma200 = snap.get('sma200', np.nan)
        death_cross = not np.isnan(sma50) and not np.isnan(sma200) and sma50 < sma200
        
        # Option C: MACD Bearish Crossover
        macd_cross = snap.get('macd_cross', '')
        macd_bearish = "BEARISH CROSSOVER" in macd_cross.upper()
        
        # Option D: RSI dropping and price < SMA50
        rsi_now = snap.get('rsi_now', np.nan)
        rsi_trend = snap.get('rsi_trend', '')
        price_now = snap.get('price_now', np.nan)
        
        rsi_threshold = config.get("threshold_rsi", 45)
        composite_bearish = (rsi_now < rsi_threshold) and (rsi_trend == 'falling') and not np.isnan(price_now) and not np.isnan(sma50) and (price_now < sma50)
        
        signals = []
        if death_cross:
            signals.append("Death Cross (SMA50 < SMA200)")
        if macd_bearish:
            signals.append("MACD Bearish Crossover")
        if composite_bearish:
            signals.append(f"Composite (RSI < {rsi_threshold} & Price < SMA50)")
            
        if signals:
            current_downtrends.append({
                "ticker": ticker,
                "price": price_now,
                "signals": signals,
                "snap": snap,
                "commentary": "" # populated later if needed
            })
            
        # Check against state to see if it's new
        ticker_state = state.get(ticker, {})
        new_signals = []
        now_str = datetime.datetime.now().isoformat()
        
        for sig in signals:
            if sig not in ticker_state:
                new_signals.append(sig)
                ticker_state[sig] = now_str
                
        # If any signal *stopped* firing, we can remove it from state so it can trigger again in the future
        signals_to_remove = []
        for saved_sig in ticker_state:
            if saved_sig not in signals:
                signals_to_remove.append(saved_sig)
        for saved_sig in signals_to_remove:
            del ticker_state[saved_sig]
            
        if new_signals:
            summary = _generate_gemini_summary(ticker, price_now, new_signals, snap)
            triggered_alerts.append({
                "ticker": ticker,
                "price": price_now,
                "new_signals": new_signals,
                "snap": snap,
                "commentary": summary
            })
            
        if ticker_state:
            state[ticker] = ticker_state
        elif ticker in state:
            del state[ticker]

    # Save state
    try:
        atomic_write_json(_ALERTS_STATE_FILE, state)
    except Exception as e:
        logging.warning(f"Could not write alerts state: {e}")
    
    # Send daily alert if any new
    if triggered_alerts:
        _send_alert_email(triggered_alerts)
        
    # Weekly recap schedule check
    now = datetime.datetime.now()
    if config.get("enable_weekly_recap", True):
        if now.weekday() == config.get("recap_day", 4) and now.hour == config.get("recap_hour", 18):
            _RECAP_FLAG = Path(__file__).parent.parent.parent / "downtrend_recap_flag.txt"
            today_str = datetime.date.today().isoformat()
            already_sent = False
            if _RECAP_FLAG.exists():
                already_sent = _RECAP_FLAG.read_text().strip() == today_str
                
            if not already_sent and current_downtrends:
                # Generate commentary for all current downtrends
                for dt in current_downtrends:
                    dt["commentary"] = _generate_gemini_summary(dt["ticker"], dt["price"], dt["signals"], dt["snap"])
                _send_weekly_recap_email(current_downtrends)
                _RECAP_FLAG.write_text(today_str)



def check_uptrends(positions: dict = None, watchlist_tickers: list = None, exited_tickers: list = None):
    """
    Evaluates technical uptrends across:
    1. Current holdings (positions)
    2. Auto-included exited positions (exited in last 12m)
    3. User-defined watchlist candidates
    Fires an email alert for newly triggered signals.
    """
    from backend.services import storage
    from backend.services import screener
    
    if positions is None:
        positions = {}
        for acct in ["Consolidated", "ISA", "SIPP"]:
            cached = storage.load_latest_portfolio(acct)
            if cached and cached.get("positions"):
                for t, s in cached["positions"].items():
                    positions[t] = positions.get(t, 0.0) + s
                    
    if exited_tickers is None:
        try:
            exited_raw = screener.get_exited_tickers_last_12m()
            exited_tickers = [t for t in exited_raw if positions.get(t, 0.0) <= 0]
        except Exception:
            exited_tickers = []
            
    if watchlist_tickers is None:
        try:
            w_items = storage.get_watchlist_tickers(active_only=True)
            watchlist_tickers = [w["ticker"] for w in w_items]
        except Exception:
            watchlist_tickers = []
            
    held_tickers = [t for t, s in positions.items() if s > 0]
    all_tickers = sorted(list(set(held_tickers + list(exited_tickers) + list(watchlist_tickers))))
    
    if not all_tickers:
        return
        
    ohlcv_data = _fetch_ohlcv(tuple(all_tickers))
    
    # Load state
    state = {}
    if _UPTREND_STATE_FILE.exists():
        try:
            state = json.loads(_UPTREND_STATE_FILE.read_text())
        except Exception:
            state = {}

    # Load config
    config = {
        "enable_weekly_recap": False,
        "recap_day": 4, # Friday
        "recap_hour": 18, # 6 PM
        "threshold_rsi": 55,
        "volume_surge_multiplier": 1.5
    }
    if _UPTREND_CONFIG_FILE.exists():
        try:
            saved_config = json.loads(_UPTREND_CONFIG_FILE.read_text())
            config.update(saved_config)
        except Exception:
            pass
            
    triggered_alerts = []
    current_uptrends = []
    
    rsi_threshold = config.get("threshold_rsi", 55)
    volume_mult = config.get("volume_surge_multiplier", 1.5)
    
    for ticker in all_tickers:
        if ticker not in ohlcv_data:
            continue
            
        ohlcv_corrected = currency_utils.normalize_ohlcv(ticker, ohlcv_data[ticker])
        shares = positions.get(ticker, 0.0)
        try:
            snap = _build_technical_snapshot(ohlcv_corrected, ticker, shares)
        except Exception as e:
            logging.warning(f"Error building snapshot for {ticker} in check_uptrends: {e}")
            continue
            
        # Origin determination
        if ticker in positions and positions[ticker] > 0:
            origin = "HOLDING"
        elif ticker in exited_tickers:
            origin = "EXITED"
        else:
            origin = "WATCHLIST"
            
        # Signal A: Golden Cross (SMA50 > SMA200)
        sma50 = snap.get('sma50', np.nan)
        sma200 = snap.get('sma200', np.nan)
        golden_cross = not np.isnan(sma50) and not np.isnan(sma200) and sma50 > sma200
        
        # Signal B: MACD Bullish Crossover
        macd_cross = snap.get('macd_cross', '')
        macd_bullish = "BULLISH CROSSOVER" in macd_cross.upper()
        
        # Signal C: Composite Uptrend (RSI > threshold & rising & Price > SMA50)
        rsi_now = snap.get('rsi_now', np.nan)
        rsi_trend = snap.get('rsi_trend', '')
        price_now = snap.get('price_now', np.nan)
        composite_bullish = (rsi_now > rsi_threshold) and (rsi_trend == 'rising') and not np.isnan(price_now) and not np.isnan(sma50) and (price_now > sma50)
        
        # Signal D: Volume Surge (>= volume_mult x 20d average)
        vol_ratio = snap.get('vol_ratio', np.nan)
        volume_surge = not np.isnan(vol_ratio) and vol_ratio >= volume_mult
        
        signals = []
        if golden_cross:
            signals.append("Golden Cross (SMA50 > SMA200)")
        if macd_bullish:
            signals.append("MACD Bullish Crossover")
        if composite_bullish:
            signals.append(f"Composite (RSI > {rsi_threshold} & Price > SMA50)")
        if volume_surge:
            signals.append(f"Volume Surge ({vol_ratio:.1f}x 20d Avg)")
            
        if signals:
            current_uptrends.append({
                "ticker": ticker,
                "price": price_now,
                "signals": signals,
                "origin": origin,
                "snap": snap,
                "commentary": ""
            })
            
        ticker_state = state.get(ticker, {})
        new_signals = []
        now_str = datetime.datetime.now().isoformat()
        
        for sig in signals:
            if sig not in ticker_state:
                new_signals.append(sig)
                ticker_state[sig] = now_str
                
        signals_to_remove = []
        for saved_sig in ticker_state:
            if saved_sig not in signals:
                signals_to_remove.append(saved_sig)
        for saved_sig in signals_to_remove:
            del ticker_state[saved_sig]
            
        if new_signals:
            summary = _generate_gemini_uptrend_summary(ticker, price_now, new_signals, snap, origin)
            triggered_alerts.append({
                "ticker": ticker,
                "price": price_now,
                "new_signals": new_signals,
                "origin": origin,
                "snap": snap,
                "commentary": summary
            })
            
        if ticker_state:
            state[ticker] = ticker_state
        elif ticker in state:
            del state[ticker]
            
    # Save uptrend state
    try:
        atomic_write_json(_UPTREND_STATE_FILE, state)
    except Exception as e:
        logging.warning(f"Could not write uptrend alerts state: {e}")
        
    if triggered_alerts:
        _send_uptrend_alert_email(triggered_alerts)
        
    # Weekly recap schedule check
    now = datetime.datetime.now()
    if config.get("enable_weekly_recap", False):
        if now.weekday() == config.get("recap_day", 4) and now.hour == config.get("recap_hour", 18):
            _UPTREND_RECAP_FLAG = Path(__file__).parent.parent.parent / "uptrend_recap_flag.txt"
            today_str = datetime.date.today().isoformat()
            already_sent = False
            if _UPTREND_RECAP_FLAG.exists():
                already_sent = _UPTREND_RECAP_FLAG.read_text().strip() == today_str
                
            if not already_sent and current_uptrends:
                for ut in current_uptrends:
                    ut["commentary"] = _generate_gemini_uptrend_summary(ut["ticker"], ut["price"], ut["signals"], ut["snap"], ut.get("origin", "HOLDING"))
                _send_uptrend_weekly_recap_email(current_uptrends)
                _UPTREND_RECAP_FLAG.write_text(today_str)


def _send_alert_email(alerts: list):
    html = _build_email_html(alerts, title="Technical Downtrend Alert", is_recap=False, is_uptrend=False)
    _send_email("Downtrend Alert: Technical Signals Triggered", html)

def _send_weekly_recap_email(downtrends: list):
    html = _build_email_html(downtrends, title="Weekly Recap: Positions in Downtrend", is_recap=True, is_uptrend=False)
    _send_email("Weekly Recap: Portfolio Technical Posture", html)

def _send_uptrend_alert_email(alerts: list):
    html = _build_email_html(alerts, title="Technical Uptrend & Breakout Alert", is_recap=False, is_uptrend=True)
    _send_email("Uptrend Alert: Bullish Technical Signals Triggered", html)

def _send_uptrend_weekly_recap_email(uptrends: list):
    html = _build_email_html(uptrends, title="Weekly Recap: Positions in Bullish Posture", is_recap=True, is_uptrend=True)
    _send_email("Weekly Recap: Portfolio Bullish Posture", html)

def _send_email(subject: str, html_body: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Faraglioni & Aegis <{SENDER_EMAIL}>"
    msg["To"] = RECIPIENT_EMAIL

    msg.attach(MIMEText(html_body, "html"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SENDER_EMAIL, GMAIL_APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, [RECIPIENT_EMAIL], msg.as_string())
        server.quit()
        logging.info(f"Successfully sent email: {subject}")
    except Exception as e:
        logging.error(f"Failed to send email: {e}")

def _build_email_html(items, title, is_recap=False, is_uptrend=False):
    date_str = datetime.datetime.now().strftime("%A, %#d %B %Y")
    section_heading = ('Newly Triggered Uptrends & Breakouts' if not is_recap else 'Positions Currently in Bullish Posture') if is_uptrend else ('Newly Triggered Downtrends' if not is_recap else 'Positions Currently in Downtrend')
    
    cards_html = ""
    for item in items:
        ticker = item["ticker"]
        price = item["price"]
        signals_list = item.get("new_signals", []) if not is_recap else item.get("signals", [])
        commentary = item.get("commentary", "Technical metrics indicate structural trend development.")
        
        signal_badge_class = "bullish" if is_uptrend else "bearish"
        signals_html = ""
        for s in signals_list:
            signals_html += f'<div class="tech-signal {signal_badge_class}">{s}</div> '
            
        orig = item.get("origin", "")
        origin_badge = ""
        if orig == "HOLDING":
            origin_badge = '<span style="font-size:9px; background:rgba(201,168,76,0.15); color:#a07830; border:1px solid rgba(201,168,76,0.3); padding:2px 7px; border-radius:3px; margin-left:8px; text-transform:uppercase; font-weight:600; letter-spacing:0.5px;">Holding</span>'
        elif orig == "EXITED":
            origin_badge = '<span style="font-size:9px; background:rgba(138,155,176,0.15); color:#8a9bb0; border:1px solid rgba(138,155,176,0.3); padding:2px 7px; border-radius:3px; margin-left:8px; text-transform:uppercase; font-weight:600; letter-spacing:0.5px;">Exited</span>'
        elif orig == "WATCHLIST":
            origin_badge = '<span style="font-size:9px; background:rgba(45,122,79,0.15); color:#2d7a4f; border:1px solid rgba(45,122,79,0.3); padding:2px 7px; border-radius:3px; margin-left:8px; text-transform:uppercase; font-weight:600; letter-spacing:0.5px;">Watchlist</span>'

        border_accent = "rgba(45,122,79,0.4)" if is_uptrend else "rgba(201,168,76,0.3)"
        border_featured = "3px solid #2d7a4f" if is_uptrend else "3px solid var(--gold)"
            
        cards_html += f'''
        <div class="tech-featured" style="margin-top: 20px; border-left: {border_featured};">
          <div>
            <div class="tech-featured-label">Ticker</div>
            <div class="tech-featured-ticker">{ticker} &nbsp;&middot;&nbsp; £{price:.2f} {origin_badge}</div>
          </div>
          <div style="font-size:10px;color:var(--slate);letter-spacing:1px;">Active Signals</div>
        </div>
        <div style="margin-bottom: 12px;">
            {signals_html}
        </div>
        <div style="font-size: 13px; color: var(--navy); line-height: 1.6; padding-left: 20px; border-left: 2px solid {border_accent}; margin-bottom: 24px;">
            <em>{commentary}</em>
        </div>
        '''

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Faraglioni & Aegis Family Office — Weekly Investor Letter</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300;1,400&family=EB+Garamond:ital,wght@0,400;1,400&family=Montserrat:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --navy:       #0a1628;
    --navy-mid:   #112240;
    --navy-light: #1a3a5c;
    --gold:       #c9a84c;
    --gold-light: #e8c97a;
    --gold-dark:  #a07830;
    --cream:      #f8f5ef;
    --cream-dark: #ede8de;
    --slate:      #8a9bb0;
    --white:      #ffffff;
    --green:      #2d7a4f;
    --red:        #8b2635;
    --border:     rgba(201,168,76,0.25);
  }}

  * {{ margin:0; padding:0; box-sizing:border-box; }}

  body {{
    background: #e0dbd2;
    font-family: "Montserrat", sans-serif;
    color: var(--navy);
    -webkit-font-smoothing: antialiased;
  }}

  .email-wrapper {{
    max-width: 720px;
    margin: 40px auto;
    background: var(--cream);
    box-shadow: 0 20px 80px rgba(10,22,40,0.22), 0 4px 16px rgba(10,22,40,0.1);
  }}

  /* ══ HEADER ══ */
  .header {{
    background: var(--navy);
    padding: 48px 56px 40px;
    position: relative;
    overflow: hidden;
    text-align: center;
  }}

  .header::before {{
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: linear-gradient(90deg, transparent, var(--gold) 20%, var(--gold-light) 50%, var(--gold) 80%, transparent);
  }}

  .header-glow {{
    position: absolute;
    top: 0; left: 50%;
    transform: translateX(-50%);
    width: 300px; height: 300px;
    background: radial-gradient(ellipse at center, rgba(201,168,76,0.07) 0%, transparent 70%);
    pointer-events: none;
  }}

  .logo-container {{
    margin-bottom: 22px;
    position: relative;
    z-index: 2;
  }}

  .firm-name {{
    font-family: "Cormorant Garamond", serif;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 5px;
    text-transform: uppercase;
    color: var(--gold);
    margin-bottom: 18px;
    position: relative;
    z-index: 2;
  }}

  .report-title {{
    font-family: "Cormorant Garamond", serif;
    font-size: 36px;
    font-weight: 300;
    color: var(--white);
    line-height: 1.2;
    margin-bottom: 28px;
    position: relative;
    z-index: 2;
  }}

  .report-title em {{
    font-style: italic;
    color: var(--gold-light);
  }}

  .header-meta {{
    display: flex;
    justify-content: center;
    gap: 40px;
    border-top: 1px solid rgba(201,168,76,0.2);
    padding-top: 20px;
    position: relative;
    z-index: 2;
  }}

  .meta-item {{
    font-size: 9px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--slate);
    text-align: center;
  }}

  .meta-item span {{
    display: block;
    color: var(--cream);
    font-weight: 500;
    margin-top: 5px;
    letter-spacing: 0.5px;
    font-size: 11px;
    text-transform: none;
  }}

  /* ══ HERO IMAGE ══ */
  .hero-image-wrap {{
    width: 100%;
    display: block;
    border-bottom: 3px solid var(--gold);
    position: relative;
  }}
  .hero-image-wrap img {{
    width: 100%;
    max-height: 250px;
    object-fit: cover;
    object-position: center;
    display: block;
  }}
  .hero-image-wrap::after {{
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(to bottom,
      rgba(10,22,40,0.12) 0%,
      transparent 35%,
      transparent 70%,
      rgba(10,22,40,0.06) 100%
    );
    pointer-events: none;
  }}

  /* ══ BODY ══ */
  .body {{ padding: 0 56px 56px; }}

  /* ══ SECTIONS ══ */
  .section {{ padding: 40px 0; border-bottom: 1px solid var(--cream-dark); }}
  .section:last-child {{ border-bottom: none; }}

  .section-label {{
    font-size: 9px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: var(--gold);
    font-weight: 600;
    margin-bottom: 6px;
  }}

  .section-title {{
    font-family: "Cormorant Garamond", serif;
    font-size: 24px;
    font-weight: 400;
    color: var(--navy);
    margin-bottom: 28px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border);
  }}

  /* ══ TECHNICAL ══ */
  .tech-featured {{
    background: var(--cream-dark); padding: 16px 20px;
    margin-bottom: 16px; display: flex;
    justify-content: space-between; align-items: center;
    border-left: 3px solid var(--gold);
  }}
  .tech-featured-label {{ font-size: 9px; letter-spacing: 2px; text-transform: uppercase; color: var(--slate); margin-bottom: 4px; }}
  .tech-featured-ticker {{ font-family: "Cormorant Garamond", serif; font-size: 20px; color: var(--navy); }}
  
  .tech-signal {{
    font-size: 9.5px; font-weight: 600; letter-spacing: 1px;
    text-transform: uppercase; padding: 3px 9px;
    display: inline-block; margin-top: 4px; margin-bottom: 6px;
  }}
  .tech-signal.bullish {{ background: rgba(45,122,79,0.1); color: var(--green); }}
  .tech-signal.caution {{ background: rgba(201,168,76,0.15); color: #8a6800; }}
  .tech-signal.bearish {{ background: rgba(139,38,53,0.1); color: var(--red); }}
  
  /* ══ FOOTER ══ */
  .footer {{ background: var(--navy); padding: 32px 56px; border-top: 3px solid var(--gold); }}
  .footer-top {{
    display: flex; justify-content: space-between; align-items: flex-start;
    margin-bottom: 24px; padding-bottom: 24px;
    border-bottom: 1px solid rgba(201,168,76,0.15);
  }}
  .footer-firm {{ font-family: "Cormorant Garamond", serif; font-size: 20px; color: var(--white); font-weight: 300; }}
  .footer-firm span {{
    display: block; font-size: 9px; letter-spacing: 3px; text-transform: uppercase;
    color: var(--gold); font-family: "Montserrat", sans-serif; font-weight: 600; margin-bottom: 5px;
  }}
  .footer-tagline {{ font-family: "EB Garamond", serif; font-style: italic; font-size: 12px; color: rgba(255,255,255,0.28); margin-top: 4px; }}
  .footer-contact {{ text-align: right; font-size: 10px; color: var(--slate); line-height: 1.9; }}
  .footer-disclaimer {{ font-size: 9px; color: rgba(138,155,176,0.55); line-height: 1.75; }}
</style>
</head>
<body>
<div class="email-wrapper">

  <!-- ══ HEADER ══ -->
  <div class="header">
    <div class="header-glow"></div>

    <div class="logo-container">
      <img src="https://raw.githubusercontent.com/Sensei863/faraglioni-assets/main/Logo.png" alt="Faraglioni &amp; Aegis" style="height:96px;width:auto;border-radius:4px;">
    </div>

    <div class="firm-name">Faraglioni &amp; Aegis &nbsp;·&nbsp; Family Office</div>
    <div class="report-title">The Multi-Strategy<br><em>{title}</em></div>

    <div class="header-meta">
      <div class="meta-item">Date<span>{date_str}</span></div>
      <div class="meta-item">Classification<span>Strictly Private</span></div>
    </div>
  </div>

  <!-- ══ HERO IMAGE ══ -->
  <div class="hero-image-wrap">
    <img src="https://raw.githubusercontent.com/Sensei863/faraglioni-assets/main/image_c81b5f.jpg" alt="Hero">
  </div>

  <!-- ══ BODY ══ -->
  <div class="body">
    <div class="section">
      <div class="section-label">Technical Analysis</div>
      <div class="section-title">{section_heading}</div>
      {cards_html}
    </div>
  </div>

  <!-- ══ FOOTER ══ -->
  <div class="footer">
    <div class="footer-top">
      <div class="footer-firm">
        <span>Faraglioni &amp; Aegis</span>
        Family Office
        <div class="footer-tagline">Preserving Wealth. Securing Legacies.</div>
      </div>
      <div class="footer-contact">
        Technical Alerts<br>
        {date_str}<br>
        Strictly Private &amp; Confidential
      </div>
    </div>
    <div class="footer-disclaimer">
      This communication is prepared exclusively for the named recipient and is intended solely for personal reference. It does not constitute investment advice, an offer to buy or sell securities, or a solicitation of any kind. Past performance is not indicative of future results. All market data and third-party research referenced herein is sourced from publicly available materials and licensed research services. Faraglioni &amp; Aegis accepts no liability for investment decisions made on the basis of this communication. Please consult a regulated financial adviser before acting on any information contained herein.
    </div>
  </div>

</div>
</body>
</html>
"""
    return html
