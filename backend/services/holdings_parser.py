"""
holdings_parser.py
──────────────────
Provider-aware parser for ETF holdings files.

Supported providers
───────────────────
  • iShares  (BlackRock)   — CSV/XLSX, multi-row header
  • Xtrackers (DWS)        — XLSX, clean header
  • VanEck                 — XLSX / CSV
  • Amundi                 — XLSX, can have French-language headers
  • Vanguard               — CSV/XLSX

Public API
──────────
  detect_provider(df_raw) -> str | None
  parse_holdings(file_bytes, filename) -> tuple[str, pd.DataFrame]
      Returns (provider_name, normalised_df)

Normalised output schema (always the same regardless of source)
──────────────────────────────────────────────────────────────
  isin              : str   (empty string if not present)
  constituent_ticker: str   (empty string if not resolved in file)
  name              : str
  weight_pct        : float (0–100 scale)
  asset_class       : str   ("Equity" | "Bond" | "Cash" | "Other")
"""

import re
import io
import pandas as pd
import numpy as np


class SyntheticETFWarning(Exception):
    """
    Raised when a holdings file is for a synthetically replicated ETF.

    The collateral basket stored in the file is NOT the economic exposure —
    it is the swap collateral (typically large-cap stocks unrelated to the index).
    The caller should catch this, warn the user, and offer an index proxy upload.

    Attributes
    ----------
    provider        : str          — detected provider
    suggested_name  : str          — fund name from file header
    df_collateral   : pd.DataFrame — the collateral basket (for display only)
    replication_method : str       — raw value from the file (e.g. "Synthetic")
    """
    def __init__(self, provider: str, suggested_name: str,
                 df_collateral: pd.DataFrame, replication_method: str):
        self.provider           = provider
        self.suggested_name     = suggested_name
        self.df_collateral      = df_collateral
        self.replication_method = replication_method
        super().__init__(
            f"Synthetic ETF detected ({replication_method}): '{suggested_name}'. "
            f"The holdings file contains swap collateral, not index constituents. "
            f"Please attach an index proxy file instead."
        )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _patch_xlsx_stylesheet(file_bytes: bytes) -> io.BytesIO:
    """
    Amundi (and some other providers) export XLSX files with malformed colour
    values in the stylesheet — e.g. 6-char hex '001c4b' instead of the 8-char
    ARGB 'FF001c4b' that openpyxl requires, or '0xffffff' with a C-style prefix.

    This function patches xl/styles.xml inside the ZIP in-memory and returns
    a corrected BytesIO buffer, leaving the original bytes untouched.
    """
    import zipfile

    def _fix_rgb(m: re.Match) -> str:
        val = m.group(1)
        if val.lower().startswith("0x"):
            val = val[2:]          # strip C-style 0x prefix
        val = val.upper()
        if len(val) == 6:
            val = "FF" + val       # prepend full-opacity alpha channel
        return f'rgb="{val}"'

    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zin:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.namelist():
                data = zin.read(item)
                if item == "xl/styles.xml":
                    try:
                        text  = data.decode("utf-8")
                        text  = re.sub(r'rgb="([^"]+)"', _fix_rgb, text)
                        data  = text.encode("utf-8")
                    except Exception:
                        pass   # if patching fails, keep original bytes
                zout.writestr(item, data)
    buf.seek(0)
    return buf


def _read_xlsx_stdlib(file_bytes: bytes) -> pd.DataFrame:
    """
    Pure-stdlib XLSX reader using zipfile + xml.etree.ElementTree.
    No openpyxl or xlrd required — works even if those packages are missing.

    Reads the first worksheet only. All cell values are returned as strings.
    Shared strings are resolved; inline strings and numeric values are supported.
    """
    import zipfile
    import xml.etree.ElementTree as ET

    NS_SS  = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

    with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as z:
        names = z.namelist()

        # ── Shared strings table ──────────────────────────────────────────
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in names:
            ss_root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in ss_root.findall(f"{{{NS_SS}}}si"):
                # Each <si> may have a single <t> or multiple <r><t> runs
                texts = [t.text or "" for t in si.iter(f"{{{NS_SS}}}t")]
                shared_strings.append("".join(texts))

        # ── First worksheet ───────────────────────────────────────────────
        # Resolve workbook.xml → sheet1 path via relationships
        sheet_path = "xl/worksheets/sheet1.xml"   # safe default
        if "xl/workbook.xml" in names and "xl/_rels/workbook.xml.rels" in names:
            rels_root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            for rel in rels_root:
                target = rel.get("Target", "")
                if "sheet" in target.lower():
                    # Normalise path: targets can be any of:
                    #   "worksheets/sheet1.xml"      → prepend "xl/"
                    #   "xl/worksheets/sheet1.xml"   → use as-is
                    #   "/xl/worksheets/sheet1.xml"  → strip leading slash
                    target = target.lstrip("/")
                    if not target.startswith("xl/"):
                        target = "xl/" + target
                    if target in names:
                        sheet_path = target
                        break
                    # Some files use a relative path from the xl/ directory
                    alt = "xl/" + target.split("xl/", 1)[-1] if "xl/" in target else target
                    if alt in names:
                        sheet_path = alt
                        break

        ws_root = ET.fromstring(z.read(sheet_path))

    # ── Parse rows ────────────────────────────────────────────────────────
    rows: list[list[str]] = []
    max_col = 0

    for row_el in ws_root.iter(f"{{{NS_SS}}}row"):
        row_data: dict[int, str] = {}
        for cell in row_el.findall(f"{{{NS_SS}}}c"):
            # Column index from cell reference (e.g. "C14" → col 2, 0-based)
            ref  = cell.get("r", "A1")
            col_letters = re.match(r"[A-Z]+", ref)
            if col_letters:
                col_str = col_letters.group()
                col_idx = sum(
                    (ord(ch) - ord("A") + 1) * (26 ** i)
                    for i, ch in enumerate(reversed(col_str))
                ) - 1
            else:
                col_idx = 0

            cell_type = cell.get("t", "n")   # n=number, s=shared string, inlineStr, b=bool
            v_el = cell.find(f"{{{NS_SS}}}v")
            is_el = cell.find(f"{{{NS_SS}}}is")

            value = ""
            if cell_type == "s" and v_el is not None:
                # Shared string index
                try:
                    value = shared_strings[int(v_el.text)]
                except (IndexError, ValueError, TypeError):
                    value = v_el.text or ""
            elif cell_type == "inlineStr" and is_el is not None:
                texts = [t.text or "" for t in is_el.iter(f"{{{NS_SS}}}t")]
                value = "".join(texts)
            elif v_el is not None and v_el.text is not None:
                value = v_el.text

            row_data[col_idx] = value
            max_col = max(max_col, col_idx)

        if row_data:
            row_list = [row_data.get(c, "") for c in range(max_col + 1)]
            rows.append(row_list)

    if not rows:
        return pd.DataFrame()

    # Pad all rows to the same width
    width = max(len(r) for r in rows)
    rows  = [r + [""] * (width - len(r)) for r in rows]

    df = pd.DataFrame(rows, dtype=str)
    # Replace empty strings with NaN to match pandas read_excel behaviour
    df.replace("", pd.NA, inplace=True)
    return df


def _read_file(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """
    Read an uploaded file into a raw DataFrame without any cleaning.

    For XLSX files, three attempts are made in order:
      1. pd.read_excel with openpyxl (fast path — works for most providers).
      2. Patch the stylesheet ZIP in-memory and retry with openpyxl
         (handles Amundi's malformed 6-char hex colour values).
      3. Pure-stdlib XML parser (_read_xlsx_stdlib) — works even if openpyxl
         is not installed or both openpyxl attempts fail.

    For CSV files, multiple encodings are tried.
    """
    name_lower = filename.lower()
    if name_lower.endswith((".xlsx", ".xls")):
        # Initialise error holders so they are always bound, even if an
        # earlier attempt succeeds and the variable is never assigned in
        # its except-block (avoids UnboundLocalError in the final raise).
        e1: Exception | None = None
        e2: Exception | None = None

        # ── Attempt 1: standard openpyxl read ────────────────────────────
        try:
            return pd.read_excel(io.BytesIO(file_bytes), header=None, dtype=str)
        except Exception as _e1:
            e1 = _e1

        # ── Attempt 2: patch stylesheet then retry openpyxl ───────────────
        # Catches both the colour-hex error AND works if openpyxl is present
        # but the file is malformed.
        try:
            patched_buf = _patch_xlsx_stylesheet(file_bytes)
            return pd.read_excel(patched_buf, header=None, dtype=str)
        except Exception as _e2:
            e2 = _e2

        # ── Attempt 3: pure-stdlib XML fallback (no openpyxl needed) ─────
        # This always runs if the two openpyxl attempts above failed,
        # including when openpyxl is simply not installed.
        try:
            return _read_xlsx_stdlib(file_bytes)
        except Exception as e3:
            # All three attempts failed — raise with full context
            raise ValueError(
                f"Could not read Excel file '{filename}'. "
                f"Attempt 1 (openpyxl): {e1}. "
                f"Attempt 2 (patched openpyxl): {e2}. "
                f"Attempt 3 (stdlib XML): {e3}."
            )

    # CSV fallback — try multiple encodings.
    #
    # Challenge: some iShares files begin with a narrow 2-column metadata row
    # ("Fund Holdings as of","26/Feb/2026") then a pseudo-blank line (\xc2\xa0),
    # then the real 12-column table.  Pandas infers the column count from row 0
    # and produces a broken 2-column result.
    #
    # Strategy:
    #   1. Decode to text and scan all lines to find the true (widest) column count.
    #   2. Read the file normally (header=None) — this always produces the wide table
    #      IF we pass the correct number of columns via `names=`.
    #   3. Keep ALL lines (including the narrow metadata) so that detect_provider()
    #      can still find provider signatures in the header rows.
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            text = file_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
        # Count columns per line (commas + 1) to find the maximum
        max_cols = 1
        for line in text.splitlines():
            # Simple comma count — good enough for well-formed CSV
            n = line.count(",") + 1
            if n > max_cols:
                max_cols = n
        try:
            df_csv = pd.read_csv(
                io.BytesIO(file_bytes),
                header=None,
                dtype=str,
                encoding=enc,
                sep=",",
                names=list(range(max_cols)),   # force correct column count
                on_bad_lines="skip",
            )
            if df_csv.shape[1] > 1:
                return df_csv
        except Exception:
            continue
    raise ValueError(f"Could not parse file '{filename}' as CSV with any known encoding.")


def _find_header_row(df: pd.DataFrame, keywords: list[str]) -> int | None:
    """
    Scan rows top-down looking for the first row that contains ALL keywords
    (case-insensitive). Returns the 0-based row index or None.
    """
    kw_lower = [k.lower() for k in keywords]
    for i, row in df.iterrows():
        row_str = " ".join(str(v).lower() for v in row.values if pd.notna(v))
        if all(k in row_str for k in kw_lower):
            return i
    return None


def _promote_header(df: pd.DataFrame, header_row: int) -> pd.DataFrame:
    """
    Use `header_row` as the column names and discard all rows above it.
    """
    df.columns = df.iloc[header_row].astype(str).str.strip()
    df = df.iloc[header_row + 1:].reset_index(drop=True)
    return df


def _clean_weight(series: pd.Series) -> pd.Series:
    """
    Convert a weight column to float 0-100 scale.
    Handles: '4.23%', '4,23', '0.0423', '4.23'
    """
    s = (
        series.astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", ".", regex=False)
        .str.strip()
    )
    numeric = pd.to_numeric(s, errors="coerce")
    # If all values < 1.0 (proportion form), multiply by 100
    valid = numeric.dropna()
    if len(valid) > 0 and valid.abs().max() <= 1.0:
        numeric = numeric * 100.0
    return numeric


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """
    Return the first column name (case-insensitive, stripped) that matches
    any candidate string (also case-insensitive, stripped).
    """
    col_map = {str(c).strip().lower(): c for c in df.columns}
    for cand in candidates:
        key = cand.strip().lower()
        if key in col_map:
            return col_map[key]
    return None


def _classify_asset(row_text: str) -> str:
    t = str(row_text).lower()
    if any(w in t for w in ("bond", "treasury", "gilt", "note", "bill", "fixed income", "debt")):
        return "Bond"
    if any(w in t for w in ("cash", "deposit", "money market", "liquidity")):
        return "Cash"
    if any(w in t for w in ("future", "option", "swap", "derivative", "forward")):
        return "Other"
    return "Equity"


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

_PROVIDER_SIGNATURES: dict[str, list[str]] = {
    # iShares files always contain "BlackRock" or "iShares" in the first few rows
    # and a column called "Weight (%)"
    "ishares": ["blackrock", "ishares", "fund holdings as of"],
    # Xtrackers / DWS
    "xtrackers": ["xtrackers", "dws"],
    # VanEck — branded files contain "vaneck"/"van eck"; unbranded exports are
    # detected structurally by their "% of net assets" + "holding name" + "isin" header.
    "vaneck": ["vaneck", "van eck"],
    # Amundi (also shows "amundi etf" or "lyxor" which was rebranded)
    "amundi": ["amundi", "lyxor"],
    # Vanguard
    "vanguard": ["vanguard"],
    # Legal & General
    "lg": ["legal & general", "l&g"],
}


def detect_provider(df_raw: pd.DataFrame) -> str | None:
    """
    Scan the first 15 rows of a raw DataFrame for provider signatures.
    Returns a provider key or None if unrecognised.

    Structural fallbacks (for files that lack provider branding):
      • VanEck unbranded exports: header row contains "% of net assets",
        "holding name", and "isin" but no other provider fingerprint.
    """
    sample = df_raw.head(15).astype(str).values.flatten()
    combined = " ".join(str(v) for v in sample).lower()

    for provider, signatures in _PROVIDER_SIGNATURES.items():
        if any(sig in combined for sig in signatures):
            return provider

    # ── Structural fallback: VanEck unbranded export ─────────────────────
    # These files start with "All Holdings  MM/DD/YYYY" and have a clean
    # table with a leading Number column, Holding Name, Ticker (Bloomberg),
    # ISIN, and "% of Net Assets" — no "VanEck" text anywhere in the file.
    vaneck_structural_signals = ["% of net assets", "holding name", "isin"]
    if all(sig in combined for sig in vaneck_structural_signals):
        return "vaneck"

    return None


def suggest_fund_name(df_raw: pd.DataFrame, provider: str) -> str:
    """
    Attempt to extract the fund name from the file header.
    Used to pre-fill the ETF selector in the UI.
    """
    # ── Provider-specific extraction ─────────────────────────────────────
    # Vanguard XLSX: row 3 is always the fund name (after download-date, blank,
    # "Holdings details" section label, then the actual fund name).
    if provider == "vanguard":
        for i in range(min(8, len(df_raw))):
            row_vals = df_raw.iloc[i].dropna().astype(str).tolist()
            for v in row_vals:
                v_clean = v.strip()
                # Fund name contains "ETF", "Fund", or "UCITS" and is long enough
                if (len(v_clean) > 15
                        and re.search(r"[a-zA-Z]{3,}", v_clean)
                        and any(kw in v_clean.lower() for kw in
                                ("etf", "fund", "ucits", "index", "trust"))):
                    return v_clean

    # VanEck unbranded exports: no fund name in the file body — return ""
    # so the UI falls back to letting the user name it manually.
    if provider == "vaneck":
        return ""

    skip_phrases = (
        "date", "currency", "nav", "fund size", "as of", "per share",
        "isin", "sedol", "bloomberg", "benchmark",
        "downloaded", "all holdings", "as at",
        "holdings details", "holding name", "security name",
    )
    for i in range(min(10, len(df_raw))):
        row_vals = df_raw.iloc[i].dropna().astype(str).tolist()
        for v in row_vals:
            v_clean = v.strip()
            # Heuristic: a fund name is usually > 10 chars and contains letters
            if len(v_clean) > 10 and re.search(r"[a-zA-Z]{3,}", v_clean):
                # Skip generic metadata labels
                if not any(skip in v_clean.lower() for skip in skip_phrases):
                    return v_clean
    return ""


# ---------------------------------------------------------------------------
# Provider-specific parsers
# ---------------------------------------------------------------------------

def _parse_ishares(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    iShares (BlackRock) format.

    Two observed layouts:
      Classic: 2-3 metadata rows, then header with Name/ISIN/Ticker/Asset Class/Weight (%)
      DFEU-style: row 0 = "Fund Holdings as of, <date>", row 1 = blank,
                  row 2 = Ticker/Name/Sector/Asset Class/Market Value/Weight (%)/...

    Both layouts are handled by _find_header_row searching for "weight".
    DFEU-style has no ISIN column — Ticker is the primary identifier.
    Sector and Location (country) columns are used when present.
    """
    header_row = _find_header_row(df_raw, ["weight"])
    if header_row is None:
        header_row = _find_header_row(df_raw, ["name", "ticker"])
    if header_row is None:
        header_row = _find_header_row(df_raw, ["name", "isin"])
    if header_row is None:
        raise ValueError("iShares: could not locate header row.")

    df = _promote_header(df_raw, header_row)

    name_col    = _find_col(df, ["name", "issuer name", "security name"])
    weight_col  = _find_col(df, ["weight (%)", "weight(%)", "weight", "% of portfolio"])
    isin_col    = _find_col(df, ["isin"])
    ticker_col  = _find_col(df, ["ticker", "issuer ticker"])
    class_col   = _find_col(df, ["asset class", "asset type", "type"])
    sector_col  = _find_col(df, ["sector", "gics sector", "industry"])
    country_col = _find_col(df, ["location", "country", "country of domicile"])

    if not name_col or not weight_col:
        raise ValueError(f"iShares: missing required columns. Found: {list(df.columns)}")

    df = df[df[name_col].notna() & (df[name_col].astype(str).str.strip() != "")].copy()
    # Drop summary/footer rows; also drop pure cash rows (name == ticker == "XXX CASH")
    df = df[~df[name_col].astype(str).str.lower().str.strip().str.match(
        r"^(total|-|\s*)$"
    )].copy()

    result = pd.DataFrame()
    result["name"]               = df[name_col].astype(str).str.strip()
    result["weight_pct"]         = _clean_weight(df[weight_col])
    result["isin"]               = df[isin_col].astype(str).str.strip() if isin_col else ""
    result["constituent_ticker"] = df[ticker_col].astype(str).str.strip() if ticker_col else ""
    result["asset_class"]        = (
        df[class_col].astype(str).str.strip() if class_col
        else result["name"].apply(_classify_asset)
    )

    # Normalise asset class labels
    result["asset_class"] = result["asset_class"].replace({
        "Equity": "Equity", "Fixed Income": "Bond", "Cash and/or Derivatives": "Cash",
        "Bond": "Bond", "Money Market": "Cash", "Alternatives": "Other",
    })

    # Preserve sector and country from file — saves yfinance round-trips
    if sector_col:
        result["sector_from_file"]  = (df[sector_col].astype(str).str.strip()
                                       .replace({"nan": "", "None": ""}))
    if country_col:
        result["country_from_file"] = (df[country_col].astype(str).str.strip()
                                       .replace({"nan": "", "None": ""}))

    return result.dropna(subset=["weight_pct"]).reset_index(drop=True)


def _parse_xtrackers(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Xtrackers (DWS) format.

    Confirmed live structure (Constituent_LU*.xlsx):
      Row 0:  long disclaimer text in col 0
      Row 1:  column headers starting with an unnamed row-number column, then:
              Name, ISIN, Country, Currency, Exchange, Type of Security,
              Rating, Primary Listing, Industry Classification, Weighting
      Row 2+: data rows where col 0 = row number (1, 2, 3…), col 1 = name

    Weight column is "Weighting" (proportion: 0.044 = 4.4%).
    Sector = "Industry Classification". Country = "Country".
    """
    # Header row search: look for "weighting" or "name" (row 1 in live file)
    header_row = _find_header_row(df_raw, ["weighting"])
    if header_row is None:
        header_row = _find_header_row(df_raw, ["weight"])
    if header_row is None:
        header_row = _find_header_row(df_raw, ["name", "isin"])
    if header_row is None:
        raise ValueError("Xtrackers: could not locate header row.")

    df = _promote_header(df_raw, header_row)

    # The first column is an unnamed row-number column — drop it if its values
    # are all numeric or missing (i.e. it's just "1", "2", "3"...)
    first_col = df.columns[0]
    first_col_vals = df[first_col].dropna().astype(str).str.strip()
    if first_col_vals.str.match(r"^\d+$").all():
        df = df.drop(columns=[first_col])

    name_col    = _find_col(df, ["name", "component", "security", "description"])
    weight_col  = _find_col(df, [
        "weighting", "index weight (%)", "weight (%)", "weight(%)",
        "weight", "index weight", "net asset %",
    ])
    isin_col    = _find_col(df, ["isin"])
    ticker_col  = _find_col(df, ["ticker", "bloomberg ticker", "ric"])
    sector_col  = _find_col(df, [
        "industry classification", "industry", "sector", "gics sector",
    ])
    country_col = _find_col(df, ["country", "country of domicile"])
    class_col   = _find_col(df, ["type of security", "asset class", "asset type", "type"])

    if not name_col or not weight_col:
        raise ValueError(f"Xtrackers: missing required columns. Found: {list(df.columns)}")

    df = df[df[name_col].notna() & (df[name_col].astype(str).str.strip() != "")].copy()
    df = df[~df[name_col].astype(str).str.lower().str.strip()
            .isin(["total", "sum", "-", ""])].copy()

    result = pd.DataFrame()
    result["name"]               = df[name_col].astype(str).str.strip()
    result["weight_pct"]         = _clean_weight(df[weight_col])
    result["isin"]               = df[isin_col].astype(str).str.strip() if isin_col else ""
    result["constituent_ticker"] = df[ticker_col].astype(str).str.strip() if ticker_col else ""

    if class_col:
        result["asset_class"] = df[class_col].astype(str).str.strip().replace({
            "Equity": "Equity", "Bond": "Bond", "Fixed Income": "Bond", "Cash": "Cash",
        })
    else:
        result["asset_class"] = result["name"].apply(_classify_asset)

    if sector_col:
        result["sector_from_file"]  = (df[sector_col].astype(str).str.strip()
                                       .replace({"nan": "", "None": "", "-": ""}))
    if country_col:
        result["country_from_file"] = (df[country_col].astype(str).str.strip()
                                       .replace({"nan": "", "None": ""}))

    return result.dropna(subset=["weight_pct"]).reset_index(drop=True)


def _parse_vaneck(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    VanEck format.

    Two observed layouts:
      Branded: XLSX/CSV with a metadata header containing "VanEck" and a table
               with Name / Weight columns.
      Unbranded: "All Holdings  MM/DD/YYYY" header, then a clean table with:
                 Number | Holding Name | Ticker (Bloomberg) | ISIN | Shares |
                 Market Value | % of Net Assets

    The leading "Number" column (sequential integers 1, 2, 3…) is stripped.
    Bloomberg tickers (e.g. "RTX US", "HO FP") are stored as-is in
    constituent_ticker — the look-through engine resolves Yahoo tickers
    via ISIN, which is always present in this format.
    """
    header_row = _find_header_row(df_raw, ["% of net assets", "weight"])
    if header_row is None:
        header_row = _find_header_row(df_raw, ["% of net assets"])
    if header_row is None:
        header_row = _find_header_row(df_raw, ["isin"])
    if header_row is None:
        # Try just finding any row with "name"
        header_row = _find_header_row(df_raw, ["name"])
    if header_row is None:
        raise ValueError("VanEck: could not locate header row.")

    df = _promote_header(df_raw, header_row)

    # Strip leading sequential-number index column (common in VanEck exports)
    first_col = df.columns[0]
    first_col_vals = df[first_col].dropna().astype(str).str.strip()
    if first_col_vals.str.match(r"^\d+$").all():
        df = df.drop(columns=[first_col])

    name_col   = _find_col(df, ["holding name", "name", "security name", "description"])
    weight_col = _find_col(df, ["% of net assets", "weight (%)", "weight(%)", "weight", "% net assets", "portfolio weight"])
    isin_col   = _find_col(df, ["isin"])
    ticker_col = _find_col(df, ["ticker", "bloomberg"])
    sector_col = _find_col(df, ["sector", "industry", "gics sector"])
    country_col= _find_col(df, ["country", "country of domicile", "region"])

    if not name_col or not weight_col:
        raise ValueError(f"VanEck: missing required columns. Found: {list(df.columns)}")

    df = df[df[name_col].notna() & (df[name_col].astype(str).str.strip() != "")].copy()
    df = df[~df[name_col].astype(str).str.lower().str.startswith(("total", "other/cash", "-", "cash"))].copy()

    result = pd.DataFrame()
    result["name"]              = df[name_col].astype(str).str.strip()
    result["weight_pct"]        = _clean_weight(df[weight_col])
    result["isin"]              = df[isin_col].astype(str).str.strip() if isin_col else ""
    # Bloomberg tickers (e.g. "RTX US", "HO FP") are stored verbatim.
    # The look-through engine resolves Yahoo Finance tickers via ISIN instead.
    result["constituent_ticker"]= df[ticker_col].astype(str).str.strip() if ticker_col else ""
    result["asset_class"]       = result["name"].apply(_classify_asset)

    if sector_col:
        result["sector_from_file"]  = df[sector_col].astype(str).str.strip().replace({"nan": "", "None": "", "-": ""})
    if country_col:
        result["country_from_file"] = df[country_col].astype(str).str.strip().replace({"nan": "", "None": ""})

    return result.dropna(subset=["weight_pct"]).reset_index(drop=True)


def _parse_amundi(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Amundi (and legacy Lyxor) format.

    Actual file structure (confirmed from live export):
      - Rows 0-18: metadata header (fund name, ISIN, AUM, disclaimer)
      - Row 19:    column headers — 'ISIN code', 'Name', 'Asset class',
                   'Currency', 'Weight', 'Sector', 'Country'
      - Row 20+:   constituent data

    Weights are in proportion form (0.0379 = 3.79%) — _clean_weight handles this.
    Sector and Country are pre-populated — pass them through directly rather than
    re-fetching from yfinance, which saves significant enrichment time.

    Also handles French-language column headers from older Lyxor exports.

    Attaches _replication_method to the result so parse_holdings can detect
    synthetic funds and raise SyntheticETFWarning before saving.
    """
    # ── Read replication method from file header BEFORE promoting header ──
    replication_method = ""
    for i in range(min(20, len(df_raw))):
        row_vals = df_raw.iloc[i].dropna().astype(str).tolist()
        row_str  = " ".join(row_vals).lower()
        if "replication" in row_str:
            # The value is in the next non-empty cell after the label
            for v in row_vals:
                if v.lower() not in ("replication method", "replication type",
                                     "replication", "méthode de réplication"):
                    replication_method = v.strip()
                    break
            break

    header_row = _find_header_row(df_raw, ["isin code", "weight"])
    if header_row is None:
        header_row = _find_header_row(df_raw, ["isin", "weight"])
    if header_row is None:
        header_row = _find_header_row(df_raw, ["poids", "weight", "pond"])
    if header_row is None:
        header_row = _find_header_row(df_raw, ["nom", "name"])
    if header_row is None:
        raise ValueError(
            "Amundi: could not locate the header row. "
            "Expected a row containing 'ISIN code' and 'Weight'."
        )

    df = _promote_header(df_raw, header_row)

    name_col   = _find_col(df, ["name", "nom", "libellé", "libelle", "security", "description", "titre"])
    weight_col = _find_col(df, [
        "weight", "weight (%)", "poids (%)", "poids(%)", "pond. (%)", "pond.(%)",
        "% net assets", "poids", "pondération", "pond.",
    ])
    isin_col   = _find_col(df, ["isin code", "isin"])
    class_col  = _find_col(df, ["asset class", "asset type", "type", "classe"])
    sector_col = _find_col(df, ["sector", "secteur", "gics sector"])
    country_col= _find_col(df, ["country", "pays", "country of domicile"])

    if not name_col or not weight_col:
        raise ValueError(
            f"Amundi: missing required columns 'Name' and/or 'Weight'. "
            f"Found columns: {list(df.columns)}"
        )

    # Drop empty rows and footer totals
    df = df[df[name_col].notna() & (df[name_col].astype(str).str.strip() != "")].copy()
    df = df[~df[name_col].astype(str).str.lower().str.startswith(("total", "sous-total", "-"))].copy()

    result = pd.DataFrame()
    result["name"]              = df[name_col].astype(str).str.strip()
    result["weight_pct"]        = _clean_weight(df[weight_col])
    result["isin"]              = df[isin_col].astype(str).str.strip() if isin_col else ""
    result["constituent_ticker"]= ""   # Amundi files don't include tickers
    result["asset_class"]       = (
        df[class_col].astype(str).str.strip().str.title() if class_col
        else result["name"].apply(_classify_asset)
    )
    # Preserve sector and country from file — avoids a yfinance round-trip for these
    if sector_col:
        result["sector_from_file"]  = df[sector_col].astype(str).str.strip().replace({"nan": "", "None": ""})
    if country_col:
        result["country_from_file"] = df[country_col].astype(str).str.strip().replace({"nan": "", "None": ""})

    # Normalise asset class: Amundi uses 'Equity', 'Bond', 'Cash' etc.
    result["asset_class"] = result["asset_class"].replace({
        "Equity":        "Equity",
        "Fixed Income":  "Bond",
        "Bond":          "Bond",
        "Cash":          "Cash",
        "Money Market":  "Cash",
        "Derivative":    "Other",
        "Other":         "Other",
    })

    result = result.dropna(subset=["weight_pct"]).reset_index(drop=True)
    # Attach replication method so parse_holdings can detect synthetic funds
    result["_replication_method"] = replication_method
    return result


def _parse_vanguard(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Vanguard format.

    Two observed layouts:
      Classic CSV: clean table, weight column labelled '% of fund' or
                   'Portfolio weight (%)'.
      XLSX export: multi-row header (download date, fund name, as-at date),
                   then a table starting with:
                   Ticker | Holding name | % of market value | Sector |
                   Region | Market value | Shares
                   No ISIN column — Ticker is the primary identifier
                   (US tickers are plain Yahoo Finance symbols: NVDA, AAPL…).

    The parser tries multiple header-row strategies in order of specificity.
    """
    # Strategy 1: prefer the most distinctive weight label
    header_row = _find_header_row(df_raw, ["% of market value"])
    if header_row is None:
        header_row = _find_header_row(df_raw, ["% of fund"])
    if header_row is None:
        header_row = _find_header_row(df_raw, ["portfolio weight"])
    # Strategy 2: look for "holding name" (XLSX export)
    if header_row is None:
        header_row = _find_header_row(df_raw, ["holding name"])
    # Strategy 3: generic fallbacks
    if header_row is None:
        header_row = _find_header_row(df_raw, ["isin"])
    if header_row is None:
        header_row = _find_header_row(df_raw, ["holding"])
    if header_row is None:
        header_row = _find_header_row(df_raw, ["stock"])
    if header_row is None:
        raise ValueError("Vanguard: could not locate header row.")

    df = _promote_header(df_raw, header_row)

    name_col   = _find_col(df, ["holding name", "holding", "stock name", "security", "name", "description"])
    weight_col = _find_col(df, [
        "% of market value",          # XLSX export
        "% of fund",                  # classic CSV
        "portfolio weight (%)",
        "portfolio weight",
        "weight (%)",
        "weight",
    ])
    isin_col   = _find_col(df, ["isin"])
    ticker_col = _find_col(df, ["ticker", "sedol"])
    sector_col = _find_col(df, ["sector", "gics sector", "industry"])
    country_col= _find_col(df, ["region", "country", "country of domicile"])

    if not name_col or not weight_col:
        raise ValueError(f"Vanguard: missing required columns. Found: {list(df.columns)}")

    df = df[df[name_col].notna() & (df[name_col].astype(str).str.strip() != "")].copy()
    df = df[~df[name_col].astype(str).str.lower().str.startswith(("total", "other holdings", "-"))].copy()

    result = pd.DataFrame()
    result["name"]              = df[name_col].astype(str).str.strip()
    result["weight_pct"]        = _clean_weight(df[weight_col])
    result["isin"]              = df[isin_col].astype(str).str.strip() if isin_col else ""
    result["constituent_ticker"]= df[ticker_col].astype(str).str.strip() if ticker_col else ""
    result["asset_class"]       = result["name"].apply(_classify_asset)

    # Pass sector and region through directly — saves yfinance round-trips
    if sector_col:
        result["sector_from_file"]  = df[sector_col].astype(str).str.strip().replace({"nan": "", "None": "", "-": ""})
    if country_col:
        result["country_from_file"] = df[country_col].astype(str).str.strip().replace({"nan": "", "None": ""})

    return result.dropna(subset=["weight_pct"]).reset_index(drop=True)


def _parse_lg(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Legal & General (L&G) format.
    
    Observed structure:
      - Rows 0-3: Metadata (Basket Name, ETF ID, Date)
      - Row 4: Column headers: Security Description, ISIN, Trading Currency, Constituent Weight (Base)
      - Row 5+: Constituent data
      - Footers: Cash Component, Basket Client Disclaimer
      
    Weights are in proportion form (0.0132 = 1.32%). _clean_weight(Line 340) 
    automatically handles the 100x scaling for proportions.
    """
    header_row = _find_header_row(df_raw, ["constituent weight"])
    if header_row is None:
        header_row = _find_header_row(df_raw, ["security description", "isin"])
    if header_row is None:
        raise ValueError("L&G: could not locate header row. Expected 'Security Description' and 'Constituent Weight'.")

    df = _promote_header(df_raw, header_row)

    name_col   = _find_col(df, ["security description", "name", "description"])
    weight_col = _find_col(df, ["constituent weight (base)", "constituent weight", "weight", "weight (%)"])
    isin_col   = _find_col(df, ["isin", "isin code"])
    ticker_col = _find_col(df, ["ticker", "sedol"])

    if not name_col or not weight_col:
        raise ValueError(f"L&G: missing required columns. Found: {list(df.columns)}")

    # Clean data: drop rows with no name or no isin (filters footer disclaimers)
    df = df[df[name_col].notna() & (df[name_col].astype(str).str.strip() != "")].copy()
    
    # L&G CSVs have multi-line disclaimers at the bottom. 
    # We filter by ensuring the ISIN col has a standard ISIN (length > 10) or Weight > 0
    if isin_col:
        df = df[df[isin_col].astype(str).str.len() >= 10].copy()

    result = pd.DataFrame()
    result["name"]              = df[name_col].astype(str).str.strip()
    result["weight_pct"]        = _clean_weight(df[weight_col])
    result["isin"]              = df[isin_col].astype(str).str.strip() if isin_col else ""
    result["constituent_ticker"]= df[ticker_col].astype(str).str.strip() if ticker_col else ""
    result["asset_class"]       = result["name"].apply(_classify_asset)

    return result.dropna(subset=["weight_pct"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Parser dispatch table
# ---------------------------------------------------------------------------

_PARSERS = {
    "ishares":   _parse_ishares,
    "xtrackers": _parse_xtrackers,
    "vaneck":    _parse_vaneck,
    "amundi":    _parse_amundi,
    "vanguard":  _parse_vanguard,
    "lg":        _parse_lg,
}


def parse_holdings(file_bytes: bytes, filename: str) -> tuple[str, str, pd.DataFrame]:
    """
    Main entry point for the UI.

    Returns
    ───────
    provider       : str   — detected provider key (or "unknown")
    suggested_name : str   — fund name extracted from file header (may be "")
    df_normalised  : pd.DataFrame — normalised holdings (see module docstring)

    Raises ValueError with a human-readable message if parsing fails.
    """
    df_raw       = _read_file(file_bytes, filename)
    provider     = detect_provider(df_raw)
    suggested_nm = suggest_fund_name(df_raw, provider or "")

    if provider is None:
        raise ValueError(
            "Could not identify the fund provider from this file. "
            "Expected one of: iShares, Xtrackers, VanEck, Amundi, Vanguard, L&G. "
            "Please check the file is a standard holdings export."
        )

    parser_fn = _PARSERS[provider]
    df_norm   = parser_fn(df_raw)

    # Post-parse sanity checks
    if df_norm.empty:
        raise ValueError(f"{provider.title()}: parser produced an empty DataFrame — check file format.")

    valid_weights = df_norm["weight_pct"].dropna()
    if valid_weights.empty or valid_weights.sum() == 0:
        raise ValueError(f"{provider.title()}: all weights are zero or missing after parsing.")

    # ── Synthetic replication check ──────────────────────────────────────
    # _replication_method is attached by _parse_amundi (and can be added to other
    # provider parsers as needed).  Raise SyntheticETFWarning before any data is
    # saved — the caller (lookahead_ui) catches it and prompts for a proxy file.
    replication_col = df_norm.get("_replication_method")
    if replication_col is not None:
        replication_val = str(replication_col.iloc[0]).strip() if len(replication_col) else ""
        if "synthetic" in replication_val.lower():
            # Clean internal column before handing df back in the exception
            df_collateral = df_norm.drop(
                columns=[c for c in df_norm.columns if c.startswith("_")],
                errors="ignore"
            ).copy()
            raise SyntheticETFWarning(
                provider=provider,
                suggested_name=suggested_nm,
                df_collateral=df_collateral,
                replication_method=replication_val,
            )
        df_norm = df_norm.drop(columns=["_replication_method"], errors="ignore")

    # Normalise ISIN: strip whitespace, upper-case, blank out "nan"
    df_norm["isin"] = (
        df_norm["isin"]
        .astype(str)
        .str.strip()
        .str.upper()
        .replace({"NAN": "", "NONE": "", "N/A": ""})
    )

    # Normalise ticker: blank out "nan"
    df_norm["constituent_ticker"] = (
        df_norm["constituent_ticker"]
        .astype(str)
        .str.strip()
        .replace({"NAN": "", "NONE": "", "N/A": ""})
    )

    # Filter out rows with weight <= 0 or clearly non-equity/non-relevant
    df_norm = df_norm[df_norm["weight_pct"] > 0].copy()

    # Ensure asset_class has no nulls
    df_norm["asset_class"] = df_norm["asset_class"].fillna("Equity")

    return provider, suggested_nm, df_norm
