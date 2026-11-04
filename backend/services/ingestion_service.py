from backend.services import gemini_util
import json
from backend.services import currency_utils
from backend.services.data_handler import get_ticker_map
from backend.services.ticker_service import ai_fill_tickers


def _normalize_trades_from_llm(parsed) -> list[dict]:
    """Accept new schema with trades key, a bare array, or legacy single trade dict."""
    if isinstance(parsed, list):
        return [x for x in parsed if isinstance(x, dict)]
    if isinstance(parsed, dict):
        trades = parsed.get("trades")
        if isinstance(trades, list):
            return [x for x in trades if isinstance(x, dict)]
        if "trade_date" in parsed or "action" in parsed:
            return [parsed]
    return []


def _pence_to_pounds_multiplier(currency: str | None) -> float:
    """Scale a quoted number to major currency units when the tag is pence (GBX), matching currency_utils."""
    if not currency:
        return 1.0
    c = str(currency).strip()
    if c in ("GBX", "GBp") or c.upper() == "GBX":
        return 0.01
    return 1.0


def parse_contract_note(pdf_bytes: bytes, api_key: str, base_currency: str = "GBP") -> list[dict]:
    """
    Parses a PDF contract note using a multimodal LLM to extract trade details.

    This function follows the Gemini API pattern established in appv0.py:
    1. It configures the API key for each call.
    2. It dynamically selects the best 'flash' model available.
    3. It handles API errors and parsing failures gracefully.
    4. It attempts to resolve a Yahoo Finance ticker for each asset.

    Args:
        pdf_bytes: The raw byte content of the PDF file.
        api_key: The user's Gemini API key.

    Returns:
        A LIST of dictionaries containing the parsed trade details (and optional fee row) or an error message.
        On success: [{'Date', 'Action', ...}, ...] including optional fee rows per trade
        On failure: [{'_parse_error', '_raw_llm_response'}]
    """
    # Fail fast if no API key is provided, preventing an unnecessary API call.
    if not api_key:
        return [{"_parse_error": "No Gemini API key provided.", "_raw_llm_response": ""}]

    try:
        model = gemini_util.get_best_gemini_model(api_key)

        prompt = f"""You are parsing a broker contract note PDF for an account with a base currency of {base_currency}.

READ THE ENTIRE DOCUMENT, including every page. Some PDFs contain multiple separate dealings or contract sections — you must extract ALL of them. Do not merge two different instruments into one row; output one trade object per distinct deal.

Return ONLY valid JSON with no markdown formatting, no code fences, and no explanation. Use exactly this shape:
{{
  "trades": [
    {{
      "trade_date": "YYYY-MM-DD",
      "action": "Buy, Sell, Dividend, Interest, Fee, or Transfer",
      "asset_name": "full name as printed on the note",
      "isin": "12-character ISIN or null — look VERY carefully",
      "sedol": "7-character SEDOL or null — look VERY carefully near the name",
      "ticker": "broker symbol if printed, else null",
      "venue": "broker venue/exchange name if printed (e.g. 'LONDON STOCK EXCHANGE', 'XETRA', 'BORSA ITALIANA'), else null",
      "quantity": <number, no commas>,
      "price": <number as printed — e.g. 250.00p → 250.0>,
      "currency": "the currency of the unit PRICE (e.g. GBP, GBX, EUR, USD)",
      "net_amount": <number: NEGATIVE for buys, POSITIVE for sells — EXTREMELY IMPORTANT: If the document shows a foreign currency amount (e.g., $79.39) AND a converted {base_currency} amount, you MUST output the {base_currency} amount. Look for 'Total Settlement Amount' or 'Net Amount' in {base_currency}. NEVER output the foreign currency value if a base currency value exists>,
      "fees": <positive number: commission for this deal as printed, or 0 / null>,
      "fees_currency": "the currency of the FEE line only. Use GBP if commission shows £ or pounds. Use GBX only if the fee is clearly in pence."
    }}
  ]
}}

Rules:
- Include every trade from every page; the "trades" array length must match the number of distinct deals.
- If the document indicates a dividend payment or income, action should be "Dividend".
- For foreign trades or dividends, ALWAYS extract the final settled amount in the account's base currency ({base_currency}). Ignore the raw foreign currency amount if a converted {base_currency} amount is shown.
- If any field cannot be determined for a trade, use null for that field.
- "fees" must reflect charges for that deal; "fees_currency" must match how "fees" is denominated.
- Double-check whether prices are in pence (GBX) vs pounds (GBP)."""

        response = model.generate_content([
            {"inline_data": {"data": pdf_bytes, "mime_type": "application/pdf"}},
            prompt,
        ])

        raw_text = response.text
        cleaned_text = gemini_util.clean_json_text(raw_text)
        parsed_root = json.loads(cleaned_text)
        trades_raw = _normalize_trades_from_llm(parsed_root)

        if not trades_raw:
            return [{
                "_parse_error": "No trades found in model response (empty or unrecognized JSON shape).",
                "_raw_llm_response": raw_text,
            }]

        # Load existing ticker map for consistency across accounts
        t_map = {}
        try:
            tm_df = get_ticker_map()
            if not tm_df.empty:
                t_map = dict(zip(tm_df["Asset Name"], tm_df["Ticker"]))
        except Exception:
            pass

        # Unique asset names that need resolution (preserve order)
        asset_names_for_resolve = []
        seen = set()
        for t in trades_raw:
            an = t.get("asset_name")
            if an and an not in seen:
                seen.add(an)
                asset_names_for_resolve.append(an)

        isin_map = {}
        sedol_map = {}
        venue_map = {}
        raw_ticker_map = {}
        for t in trades_raw:
            an = t.get("asset_name")
            if not an:
                continue
            if t.get("isin"):
                isin_map[an] = t.get("isin")
            if t.get("sedol"):
                sedol_map[an] = t.get("sedol")
            if t.get("venue"):
                venue_map[an] = t.get("venue")
            if t.get("ticker"):
                raw_ticker_map[an] = t.get("ticker")

        res_map = {}
        if asset_names_for_resolve:
            res_map = ai_fill_tickers(
                api_key=api_key,
                missing_assets=asset_names_for_resolve,
                isin_map=isin_map or None,
                sedol_map=sedol_map or None,
                base_currency=base_currency,
                ticker_map=t_map,
                venue_map=venue_map or None,
                raw_ticker_map=raw_ticker_map or None,
            )

        results = []
        for parsed_json in trades_raw:
            auto_ticker = ""
            isin = parsed_json.get("isin")
            sedol = parsed_json.get("sedol")
            raw_ticker = parsed_json.get("ticker")
            asset_name = parsed_json.get("asset_name")

            if asset_name:
                auto_ticker = res_map.get(asset_name, "")
                if not auto_ticker and raw_ticker:
                    if "." not in raw_ticker and base_currency == "GBP":
                        auto_ticker = f"{raw_ticker.strip().upper()}.L"
                    else:
                        auto_ticker = raw_ticker.strip().upper()

            qty = parsed_json.get("quantity")
            price = parsed_json.get("price")
            currency = str(parsed_json.get("currency", "GBP")).upper()
            action = parsed_json.get("action", "")

            if price is not None:
                mult = currency_utils._determine_multiplier(
                    auto_ticker, float(price), currency=currency
                )
                if mult != 1.0 and base_currency == "GBP":
                    price = float(price) * mult
                    raw_net = parsed_json.get("net_amount")
                    if raw_net is not None:
                        parsed_json["net_amount"] = float(raw_net) * mult
                    # Do not scale fees with the share-line multiplier: commission is often in £ while price is in pence.

            raw_fees = parsed_json.get("fees")
            if raw_fees is not None:
                fee_ccy = parsed_json.get("fees_currency")
                # Default GBP: typical UK contract note fee is stated in pounds even when currency is GBX for the stock.
                if fee_ccy is None or (isinstance(fee_ccy, str) and not fee_ccy.strip()):
                    fee_ccy = "GBP"
                parsed_json["fees"] = float(raw_fees) * _pence_to_pounds_multiplier(str(fee_ccy))
            if qty is not None and price is not None:
                try:
                    consideration = float(qty) * float(price)
                    net_amount = (
                        -consideration
                        if str(action).lower() == "buy"
                        else consideration
                    )
                except (TypeError, ValueError):
                    net_amount = parsed_json.get("net_amount")
            else:
                net_amount = parsed_json.get("net_amount")

            main_trade = {
                "Date": parsed_json.get("trade_date"),
                "Action": action,
                "Asset Name": parsed_json.get("asset_name"),
                "Qty": qty,
                "Price": price,
                "Net Amount": net_amount,
                "Auto Ticker": auto_ticker,
                "_isin": parsed_json.get("isin") or "",
                "_sedol": parsed_json.get("sedol") or "",
                "_raw_ticker": parsed_json.get("ticker") or "",
                "_venue": parsed_json.get("venue") or "",
                "_raw_llm_response": raw_text,
            }
            results.append(main_trade)

            fees = parsed_json.get("fees", 0)
            if fees and float(fees) > 0:
                fee_row = {
                    "Date": parsed_json.get("trade_date"),
                    "Action": "Fee",
                    "Asset Name": f"Broker Fee – {parsed_json.get('asset_name', 'Unknown')}",
                    "Qty": 0,
                    "Price": 0,
                    "Net Amount": -abs(float(fees)),
                    "Auto Ticker": "",
                    "_isin": "",
                    "_sedol": "",
                    "_raw_llm_response": raw_text,
                }
                results.append(fee_row)

        return results

    except json.JSONDecodeError as e:
        return [{
            "_parse_error": f"Failed to parse JSON response: {e}",
            "_raw_llm_response": raw_text if "raw_text" in locals() else "No response text.",
        }]
    except Exception as e:
        return [{"_parse_error": str(e), "_raw_llm_response": ""}]


def extract_kiid(pdf_bytes: bytes, api_key: str, etf_ticker: str) -> dict:
    """
    Parses an ETF Factsheet (or KIID) PDF using a multimodal LLM to extract structural metadata.

    Args:
        pdf_bytes: The raw byte content of the PDF file.
        api_key: The user's Gemini API key.
        etf_ticker: The ticker symbol (to anchor the context).

    Returns:
        A dictionary matching the schema of the etf_kiid table.
    """
    if not api_key:
        raise ValueError("No Gemini API key provided.")

    try:
        model = gemini_util.get_best_gemini_model(api_key)

        prompt = f"""You are extracting structural ETF data from a factsheet for the ticker {etf_ticker}.
Extract the following fields and return ONLY a valid JSON object with no markdown formatting or text:
- "full_name": string (the full name of the ETF or Fund)
- "index_tracked": string (the benchmark or index it tracks)
- "replication_method": string (e.g., "Physical", "Synthetic", "Optimised Physical")
- "domicile": string (the country where the fund is domiciled, e.g. "Ireland", "Luxembourg")
- "ucits": integer (1 if it mentions UCITS compliant, 0 otherwise)
- "accumulating": integer (1 if the dividend treatment is accumulating/reinvesting, 0 if distributing/income/dist)
- "ter": float (Total Expense Ratio or Ongoing Charge, e.g. if 0.20%, return 0.20)
- "isin": string (the 12-character ISIN code)

If any field cannot be confidently determined from the document, set it to null.
"""
        response = model.generate_content([
            {"inline_data": {"data": pdf_bytes, "mime_type": "application/pdf"}},
            prompt,
        ])

        cleaned_text = gemini_util.clean_json_text(response.text)
        parsed_json = json.loads(cleaned_text)

        # Standardize ensuring keys exist
        return {
            "etf_ticker": etf_ticker.upper(),
            "full_name": parsed_json.get("full_name") or "",
            "index_tracked": parsed_json.get("index_tracked") or "",
            "replication_method": parsed_json.get("replication_method") or "",
            "domicile": parsed_json.get("domicile") or "",
            "ucits": int(parsed_json.get("ucits") or 0),
            "accumulating": int(parsed_json.get("accumulating") or 0),
            "ter": float(parsed_json.get("ter") or 0.0),
            "isin": parsed_json.get("isin") or "",
        }

    except Exception as e:
        raise RuntimeError(f"Failed to extract KIID metadata from PDF: {e}")
