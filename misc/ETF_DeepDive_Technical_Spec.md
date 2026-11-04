# Technical Specification: Institutional ETF Analysis (Screener Integration)

**Faraglioni & Aegis — Finance Tool**
*Version 3.0 — April 2026*

---

## 1. Executive Summary

This document specifies the upgrade of the **Market Screener**'s AI analysis from a simple qualitative prompt to an **Institutional-Quality ETF Deep-Dive**.

When an ETF ticker is selected in the screener, the tool replaces the standard analysis with a structured investment memo leveraging five data pillars: live technicals/fundamentals, underlying constituent data, structural KIID metadata, Barclays macro research, and current portfolio context.

This is an "Active Ingestion" feature — if the tool lacks the necessary data to produce a high-conviction report, it provides inline ingestion tools to capture factsheets or holdings files immediately.

---

## 2. Objectives

1. **Materially Beyond Screener**: Deliver valuation-aware, macro-contextualised ETF analysis that goes materially beyond the legacy screener prompt.
2. **Data-Centric Intelligence**: Leverage data already resident in the tool (portfolio, prices, research library, ETF holdings DB) rather than relying on AI training knowledge alone.
3. **Investor-Centric Reporting**: Produce a report that directly answers the investor's practical questions: *What am I buying? Is it fairly priced? Does the macro support it? Does it fit my portfolio?*
4. **Clean Integration**: Integrate seamlessly into the existing multi-page navigation structure (`st.navigation`) without disrupting any current functionality.
5. **New Default for ETFs**: Replace the legacy screener prompt with this "Deep-Dive" memo whenever an ETF is detected.
6. **Code & Data Reuse**: Core engine must leverage existing modules (`holdings_db.py`, `holdings_parser.py`, `lookahead_engine.py`) to avoid duplication.
7. **Frictionless Ingestion**: Provide inline "Update Data" capabilities directly within the Screener interface to capture missing KIID/Holdings context.
8. **Data Hygiene**: Ensure the SQLite database remains lean by overwriting historical holdings for a specific ticker during re-uploads.

---

## 3. Architecture Overview

The feature is integrated into the **Market Analysis** module. It resides inside `screener.py` but delegates heavy lifting to a dedicated engine.

```
┌─────────────────────────────────────────────────────────────┐
│             pages/01_📈_Market_Screener.py                  │
│     (Enhanced with Inline Ingestion & Deep-Dive Trigger)     │
└──────────────────────┬──────────────────────────────────────┘
                       │ orchestrates
          ┌────────────▼────────────┐
          │   etf_deepdive_engine.py │
          │  (data assembly + prompt │
          │   construction)          │
          └────────────┬────────────┘
                       │ reads from / writes to
    ┌──────────────────┼──────────────────────────┬──────────────────┐
    │                  │                          │                  │
    ▼                  ▼                          ▼                  ▼
yfinance         holdings_db.py            holdings_parser.py    storage.py
(live price,     (ETF constituents,        (PDF/XLS extraction   (portfolio
 technicals,     KIID metadata,             of constituents)      positions)
 metrics)        staleness registry)              │                  │
    │                                             │                  │
    ▼                                             ▼                  ▼
newsletter_ui.py                             lookahead_engine.py
(Barclays research)                          (Overlap & Weight analysis)
```

---

## 4. User Flow (In-Screener)

1. **Selection**: User selects an ETF ticker via a dual-input mechanism:
   - **Dropdown**: Pre-populated with high-conviction tickers from the current portfolio holdings.
   - **Free-Text Input**: Allows for analysis of any valid Yahoo Finance ticker not in the portfolio.
2. **Readiness Check**: Tool immediately signals data coverage in the "Knowledge Base Support" panel:
   - ✅ **Live Data** (Always present)
   - ⚠️ **Holdings Stale** (e.g., >90 days old)
   - ❌ **KIID Missing** (e.g., no domicile/TER on file)
3. **Inline Ingestion (Optional)**: If data is missing/stale, user uploads a Factsheet (PDF) or Holdings (CSV) directly.
4. **Memo Generation**: User clicks "Institutional Analysis". Tool assembles all context.
5. **Output**: The standard AI response is replaced by an 8-section institutional investment memo.

---

## 5. Data Sources & Assembly

### 5.1 Live Price & Fundamentals (yfinance)

Reuse the existing `fetch_screener_data()` pattern from `screener.py`.

```python
LIVE_FIELDS = {
    "price":           float,   # current price (corrected for pence/GBP)
    "currency":        str,
    "long_name":       str,
    "ret_1w":          float,   # 1-week return
    "ret_1m":          float,
    "ret_3m":          float,
    "ret_6m":          float,
    "ret_1y":          float,
    "high_52w":        float,
    "low_52w":         float,
    "sma_50":          float,
    "sma_200":         float,
    "trend_signal":    str,     # "UPTREND" | "DOWNTREND"
    "curr_drawdown":   float,
    "forward_pe":      float,   # forwardPE
    "trailing_pe":     float,   # trailingPE
    "price_to_book":   float,   # priceToBook
    "dividend_yield":  float,
    "avg_volume":      int,
    "beta":            float,
    "expense_ratio":   float,   # annualReportExpenseRatio
    "aum":             float,   # totalAssets
    "category":        str,     # Morningstar category if available
    "inception_date":  str,
}
```

### 5.2 ETF Structure & Holdings (holdings_db.py)

Read constituents using `get_latest_holdings(ticker)`.

```python
def _build_holdings_context(etf_ticker: str) -> str:
    """
    Returns a formatted string summarising:
    - Top 15 holdings by weight (name, weight_pct)
    - Sector & Country breakdown (aggregated by lookahead_engine)
    - Data freshness (last_upload from staleness_registry)
    - Replication method (Physical vs Synthetic)
    """
```

### 5.3 KIID Metadata (NEW Table)

Store static structural data that yfinance lacks.

```sql
CREATE TABLE IF NOT EXISTS etf_kiid (
    etf_ticker          TEXT    PRIMARY KEY,
    full_name           TEXT,
    index_tracked       TEXT,
    replication_method  TEXT,   -- "Physical" | "Synthetic"
    domicile            TEXT,   -- e.g. "Ireland"
    ucits               INTEGER,
    accumulating        INTEGER, -- 1=Acc, 0=Dist
    ter                 REAL,
    isin                TEXT,
    updated_at          TEXT
);
```

**Ingestion**: `ingestion_service.py` extracts these from the Factsheet PDF. **Overwrite Policy**: Always replace existing entry on re-ingestion to prevent bloat.

### 5.4 Barclays Macro Context (Rolling 4-Week Horizon)

The engine does not rely on a single report. It reuses `distil_digest()` from `newsletter_ui.py` to fetch and distill the **last 4 weeks** of research folders.

- **Logic**: Construct a chronological "Macro Narrative" from the 4 most recent PM Digests/Reports.
- **Requirement**: This prevents the AI from being "trapped" in a single week's noise and ensures it understands the structural path of inflation, rates, and earnings established over the previous month.

### 5.5 Portfolio Overlap (lookahead_engine.py)

Reuses `compute_overlap_details()` and `storage.load_latest_portfolio()`.

```python
def _build_portfolio_context(etf_ticker: str) -> str:
    """
    Calculates overlap (%) with existing holdings.
    Identifies redundant exposure (e.g., analysing SWDA when already owning IUSA).
    """
```

---

## 6. Prompt Architecture

The prompt is structured to enforce institutional discipline. Reuses `get_best_gemini_model()`.

**Main Analysis Template:**

```
You are a senior portfolio manager and CFA charterholder at Faraglioni & Aegis Family Office.
Your mandate combines fundamental valuation discipline with macro-aware asset allocation.
You write with precision and intellectual honesty. Avoid marketing language.
You are producing a pre-allocation investment memo on a single ETF.
Today: {report_date}.
═══ DATA CONTEXT ═══
A. LIVE MARKET: {long_name} ({ticker}) | Price {price}, Forward P/E {forward_pe}, Yield {dividend_yield}, Trend {trend_signal}.
B. STRUCTURE: Replication {replication}, Domicile {domicile}, TER {ter}.
C. HOLDINGS: {holdings_ctx} (Top 15, Sector/Geo weights).
D. MACRO: {macro_ctx} (Rolling 4-week chronological research distillation).
E. PORTFOLIO: {portfolio_ctx} (Current overlap and concentration).

═══ GENERATION INSTRUCTIONS ═══

Write a structured investment memo with EXACTLY the following sections.
Use Markdown. Each section must be a ## header. Be specific — cite actual numbers
from Sections A–D. Do not fabricate data not present in the context above.
Flag explicitly where data is unavailable rather than guessing.

## 1. ETF Profile & Structure
One paragraph. Index tracked, replication method, domicile, accumulating/distributing,
TER. Note any structural risks (counterparty, currency, synthetic collateral).
Flag if replication method or domicile creates tax inefficiency for a UK investor.

## 2. Underlying Exposure
One paragraph + one table. Describe the geographic and sector composition based on
the constituent data in Section B. Identify the top 3 concentration risks by name.
Table format: | Region/Sector | Weight% | Key Holding |

## 3. Performance & Technical Posture
Two short paragraphs.
Para 1: Return attribution — contextualise 1M/3M/6M/1Y returns. Are recent returns
driven by multiple expansion or earnings growth? Is the trend (SMA signal) intact?
Para 2: Drawdown and volatility context. Is the current drawdown shallow or meaningful?
How does beta compare to a broad equity benchmark?

## 4. Valuation Assessment
This section is MANDATORY even if forward P/E data is unavailable — in that case,
use the constituent geographic/sector weights to infer likely valuation regime
(e.g. "heavy US tech weighting implies elevated multiples").
- State current Forward P/E and P/B vs. historical norms where known.
- Is the valuation a tailwind, headwind, or neutral for a 5-year horizon?
- If EM or non-US exposure: compare valuation discount/premium to US equities.
- One-sentence verdict: CHEAP | FAIR | STRETCHED | UNCERTAIN

## 5. Macro Context & Timing
Source EXCLUSIVELY from Section C (Barclays research). Do not use generic macro views.
- What does the current macro regime imply for this ETF's specific exposure?
 Synthesize the provided 4-week macro narrative. 
- Give significant weight (approx 70%) to the most recent report for tactical timing.
- Use the earlier 3 weeks (approx 30%) to identify structural trends and ensure the current move isn't an anomaly.
- Are earnings revisions for the underlying index positive or negative?
- Does the interest rate environment support or challenge this asset class?
- Direct answer to: "Does the macro context support initiating or adding to a position NOW?"
  Answer must be one of: SUPPORTIVE | NEUTRAL | CAUTIOUS | CONTRA-INDICATOR
  followed by 2–3 sentences of specific justification from the research.

## 6. Portfolio Fit & Overlap
Source from Section D.
- Does the portfolio already hold this ETF? If yes, what is the current weight?
- Which existing holdings have material constituent overlap? Name them.
- What incremental exposure does this ETF add that the portfolio currently lacks?
- What is a reasonable position size as % of total NAV given current concentration?
  Suggest a specific range (e.g. "3–5% of NAV") with brief rationale.
- Role classification: CORE | SATELLITE | TACTICAL OVERLAY | AVOID (REDUNDANT)

## 7. Bull / Base / Bear Cases (3–5 Year Horizon)
| Scenario | Key Assumptions | Est. Annualised Return | Probability |
|---|---|---|---|
| Bull | ... | ...% | ...% |
| Base | ... | ...% | ...% |
| Bear | ... | ...% | ...% |
Note: Probability column must sum to 100%.

## 8. Investment Verdict
- **Rating:** STRONG BUY | BUY | HOLD | REDUCE | AVOID
- **Conviction:** HIGH | MEDIUM | LOW
- **Primary rationale:** One sentence.
- **Top 3 reasons to invest:** bullet list
- **Top 3 risks to monitor:** bullet list
- **Suggested entry:** Lump sum vs. phased DCA. Specific price level or condition
  that would make you more or less aggressive (e.g. "add on >5% pullback").


```

---

## 7. UI Specification (`screener.py` modification)

The Screener UI is enhanced to include the **Knowledge Base & Deep-Dive** section.

```
┌─────────────────────────────────────────────────────┐
│  📈 Market Screener / Selected: SWDA.L              │
├─────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────┐ │
│  │ 📋 Knowledge Base Support                       │ │
│  │  ✅ Live Data (yfinance)                         │ │
│  │  ⚠️ Holdings (Vanguard — Stale: 112 days)        │ │
│  │  ❌ KIID Structure (Missing)                     │ │
│  │  [📥 Update Holdings]  [📄 Update Factsheet]     │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  [⚡ Generate Institutional Memo]                    │
│                                                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │ Generated Investment Memo (Rendered Markdown)    │ │
│  │ ## 1. ETF Profile...                            │ │
│  │ ## 2. Underlying Exposure...                    │ │
│  │ ...                                             │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

---

## 8. New Functions Summary

### `etf_deepdive_engine.py`

| Function | Inputs | Returns | Notes |
|---|---|---|---|
| `get_data_readiness(ticker)` | str | dict | Returns ✅/⚠️/❌ status for 5 pillars |
| `ingest_etf_metadata(pdf_bytes)`| bytes | dict | Extracts KIID data via ingestion_service |
| `build_deepdive_prompt(...)` | multiple | str | Assembles the Version 6 template |
| `generate_memo(prompt)` | str | str | Gemini 2.5 Flash call |

### `holdings_db.py` additions

| Function | Inputs | Returns | Notes |
|---|---|---|---|
| `save_kiid(data)` | dict | None | Upserts etf_kiid table |
| `get_kiid(ticker)` | str | dict | Returns structural metadata |

---

## 9. Implementation Notes

### Code Reuse (Mandatory)

- Use `holdings_parser.parse_holdings()` for CSV/XLS uploads.
- Use `lookahead_engine` logic for sector/geo aggregation.
- Use `newsletter_ui.distil_digest()` for the macro pillar.

### Data Hygiene

- The tool follows a **"Latest is Best"** policy. Saving new holdings triggers a `delete_holdings(ticker)` call first to ensure the SQLite file doesn't grow with historical noise.

### Graceful Degradation

- If a data source (e.g., Macro) is missing, the engine substitutes: *"Macro context unavailable for this region — proceed with fundamental caution."*

---

*Faraglioni & Aegis — Finance Tool Internal Specification*
*Version 3.0 — April 2026*
