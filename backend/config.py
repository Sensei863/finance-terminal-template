import os
import re
from pathlib import Path

# Try to use standard library tomllib (Python 3.11+)
try:
    import tomllib
except ImportError:
    # Try third-party toml package
    try:
        import toml as tomllib
    except ImportError:
        tomllib = None

def parse_toml_fallback(toml_str: str) -> dict:
    """
    Extremely robust simple fallback parser for standard key-value pairs 
    and simple table headings in TOML.
    """
    res = {}
    current_section = None
    for line in toml_str.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Check for section: e.g., [connections.gsheets]
        m_section = re.match(r"^\[(.*)\]$", line)
        if m_section:
            current_section = m_section.group(1).strip()
            continue
        
        # Check for key-value: e.g., project_id = "..."
        if "=" in line:
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            
            # Handle escaped characters (like newlines in private_key)
            val = val.replace("\\n", "\n")
            
            if current_section:
                # build nested structure: section.key
                parts = current_section.split(".")
                curr = res
                for part in parts[:-1]:
                    if part not in curr:
                        curr[part] = {}
                    curr = curr[part]
                last_part = parts[-1]
                if last_part not in curr:
                    curr[last_part] = {}
                curr[last_part][key] = val
            else:
                res[key] = val
    return res

def parse_toml(toml_str: str) -> dict:
    """Parses TOML string using the best available parser."""
    if tomllib and hasattr(tomllib, "loads"):
        try:
            return tomllib.loads(toml_str)
        except Exception:
            pass
    elif tomllib and hasattr(tomllib, "parse"):  # standard toml library interface
        try:
            return tomllib.parse(toml_str)
        except Exception:
            pass
    return parse_toml_fallback(toml_str)

def get_secrets() -> dict:
    """
    Retrieves and parses secrets.
    Prioritizes explicit environment variables (.env / Render / Vercel).
    Maintains backward compatibility with legacy secrets TOML if needed.
    """
    secrets = {}

    # 1. Primary: Direct environment variables
    for key in [
        "GEMINI_API_KEY",
        "GMAIL_APP_PASSWORD",
        "RECIPIENT_EMAIL",
        "SENDER_EMAIL",
        "DATABASE_URL",
        "APP_DATABASE_URL",
        "LEDGER_DATABASE_URL",
    ]:
        val = os.environ.get(key) or os.environ.get(key.lower()) or os.environ.get(key.upper())
        if val:
            secrets[key.lower()] = val

    if os.environ.get("GOOGLE_CREDENTIALS_JSON"):
        try:
            import json
            secrets["connections"] = {
                "gsheets": json.loads(os.environ.get("GOOGLE_CREDENTIALS_JSON"))
            }
        except Exception:
            pass

    # 2. Secondary fallback: TOML if credentials weren't in direct environment
    if "gemini_api_key" not in secrets or "gmail_app_password" not in secrets:
        env_str = os.environ.get("STREAMLIT_SECRETS_TOML")
        if env_str:
            try:
                parsed = parse_toml(env_str)
                for k, v in parsed.items():
                    if k not in secrets:
                        secrets[k] = v
            except Exception:
                pass

    return secrets
