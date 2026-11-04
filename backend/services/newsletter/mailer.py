import os
import re
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from backend.config import get_secrets

log = logging.getLogger(__name__)

_HERO_MAX_WIDTH   = 720   # px — matches email-wrapper width
_LOGO_MAX_HEIGHT  = 192   # px — 2× 96px display height for retina
_HERO_JPEG_Q      = 60    # JPEG quality for hero image
_LOGO_JPEG_Q      = 80    # JPEG quality for logo


def _get_email_credentials():
    sec = get_secrets()
    sender = os.environ.get("SENDER_EMAIL") or os.environ.get("sender_email") or sec.get("sender_email", "")
    recipient = os.environ.get("RECIPIENT_EMAIL") or os.environ.get("recipient_email") or sec.get("recipient_email", "")
    password = os.environ.get("GMAIL_APP_PASSWORD") or os.environ.get("gmail_app_password") or sec.get("gmail_app_password", "")
    return sender, recipient, password


def compress_html_images(html: str) -> str:
    """Compress all large base64 images embedded in an HTML string using Pillow.

    Images >20 KB are resized and re-encoded as JPEG at reduced quality.
    Images that are already small enough are left untouched.
    """
    try:
        from PIL import Image
        import io as _io
        import base64 as _b64
    except ImportError:
        log.warning("Pillow not installed — image compression skipped. pip install pillow")
        return html

    patterns = [
        re.compile(r'(src=")(data:image/([^;]+);base64,)([^"]{20000,})(")', re.DOTALL),
        re.compile(r'(url\()(data:image/([^;]+);base64,)([^)]{20000,})(\))', re.DOTALL),
    ]

    for pat in patterns:
        def _replace(m):
            prefix    = m.group(1)   # src=" or url(
            b64_data  = m.group(4)   # raw base64 payload
            suffix    = m.group(5)   # " or )
            try:
                raw_bytes = _b64.b64decode(b64_data)
                img = Image.open(_io.BytesIO(raw_bytes))
                w, h = img.size

                is_logo = (h > 0 and w / h < 3)
                if is_logo:
                    if h > _LOGO_MAX_HEIGHT:
                        img = img.resize((int(w * _LOGO_MAX_HEIGHT / h), _LOGO_MAX_HEIGHT), Image.LANCZOS)
                    quality = _LOGO_JPEG_Q
                else:
                    if w > _HERO_MAX_WIDTH:
                        img = img.resize((_HERO_MAX_WIDTH, int(h * _HERO_MAX_WIDTH / w)), Image.LANCZOS)
                    quality = _HERO_JPEG_Q

                if img.mode in ("RGBA", "P", "LA"):
                    img = img.convert("RGB")

                buf = _io.BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True)
                compressed_b64 = _b64.b64encode(buf.getvalue()).decode("ascii")
                return f'{prefix}data:image/jpeg;base64,{compressed_b64}{suffix}'
            except Exception as exc:
                log.warning("compress_html_images: skipping image: %s", exc)
                return m.group(0)

        html = pat.sub(_replace, html)

    return html


def prepare_for_email(html: str) -> str:
    """Prepare newsletter HTML for email delivery.
    1. Compress large base64 images embedded in live HTML.
    2. Resolve all CSS var(--x) references to literal values for Gmail compat.
    """
    try:
        html = compress_html_images(html)
    except Exception as exc:
        log.warning("compress_html_images failed, falling back to strip: %s", exc)
        def _strip_img(m):
            src = m.group(1)
            return "" if src.startswith("data:") and len(src) > 20_000 else m.group(0)
        html = re.sub(r'<img\s[^>]*src="([^"]*)"[^>]*/?>', _strip_img, html, flags=re.DOTALL)

        def _strip_bg(m):
            return "background:none;" if len(m.group(1)) > 20_000 else m.group(0)
        html = re.sub(r'background(?:-image)?\s*:\s*url\(([^)]+)\)\s*;?', _strip_bg, html, flags=re.DOTALL)
        html = re.sub(r'<div class="hero-image-wrap">\s*</div>', "", html)

    # Resolve CSS variables
    css_var_map = {}
    for match in re.finditer(r'--([\w-]+)\s*:\s*([^;}{]+);', html):
        css_var_map[f"var(--{match.group(1)})"] = match.group(2).strip()
    for _ in range(3):
        for var, value in css_var_map.items():
            html = html.replace(var, value)

    return html


def send_email(
    html_content: str,
    subject: str,
    recipients: list | None = None,
    _from_thread: bool = False,
) -> bool:
    """Send the newsletter HTML via Gmail SMTP.

    Args:
        html_content : Raw newsletter HTML (processed before send).
        subject      : Email subject line.
        recipients   : List of recipient email addresses.
        _from_thread : Thread context flag.
    """
    sender_email, default_recipient, password = _get_email_credentials()

    if recipients is None:
        recipients = [default_recipient]
    if default_recipient and default_recipient not in recipients:
        recipients = [default_recipient] + list(recipients)

    if not sender_email or not password:
        log.error("send_email failed: SENDER_EMAIL or GMAIL_APP_PASSWORD is not configured.")
        return False

    email_html = prepare_for_email(html_content)
    size_kb = len(email_html.encode("utf-8")) / 1024
    log.info("Email HTML size after prep: %.1fKB → %d recipient(s)", size_kb, len(recipients))
    if size_kb > 95:
        log.warning(f"⚠️ Email is {size_kb:.0f}KB — Gmail may clip at 102KB.")

    to_header = ", ".join(recipients)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender_email
    msg["To"]      = to_header
    msg.attach(MIMEText(email_html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(sender_email, password)
            s.sendmail(sender_email, recipients, msg.as_string())
        return True
    except Exception as e:
        log.error(f"Email failed: {e}")
        return False
