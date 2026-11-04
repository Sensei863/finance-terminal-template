# Aegis Terminal — Setup, Architecture & User Guide

Welcome! This repository is a private, institutional-grade quantitative portfolio terminal, market analytics engine, and automated reporting suite.

The live application you saw was implemented using a **Cloud Stack (Vercel + Render + Neon PostgreSQL)**, but you can choose between **two architectures**:
1. **☁️ Hosted Online (Vercel + Render + Neon)** — The exact setup I implemented for 24/7 web access.
2. **💻 100% Local Setup + Tailscale (No-Fuss)** — Zero cloud infrastructure, run on your PC with a local Postgres instance, and access it securely from your phone/laptop anywhere via Tailscale.

---

## 🏗️ Architecture Options (Choose Your Path)

```
Option A: Cloud Stack (How I implemented it)
┌──────────────────────┐         ┌───────────────────────┐         ┌────────────────────────┐
│  Next.js Frontend    │ ──HTTPS─▶  FastAPI Backend      │ ──SQL───▶  Neon PostgreSQL       │
│  (Vercel)            │         │  (Render Web Service) │         │  (Cloud Database)      │
└──────────────────────┘         └───────────────────────┘         └────────────────────────┘

Option B: 100% Local + Tailscale (Zero Cloud Setup)
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ Your Computer (Mac/PC/Linux)                                                              │
│  ┌───────────────────┐        ┌───────────────────┐        ┌────────────────────────────┐ │
│  │ Next.js Frontend  │ ──────▶│ FastAPI Backend   │ ──────▶│ Local PostgreSQL           │ │
│  │ (localhost:3000)  │        │ (localhost:8000)  │        │ (Docker or Native DB)      │ │
│  └───────────────────┘        └───────────────────┘        └────────────────────────────┘ │
└───────────────────────────────────────────▲───────────────────────────────────────────────┘
                                            │ Tailscale VPN (Free, Private Mesh)
                                  ┌─────────┴─────────┐
                                  │ iPhone / Laptop   │
                                  └───────────────────┘
```

---

## 🤖 Claude Code Quickstart (Copy & Paste to your AI Agent)

If you are using **Claude Code** (or any CLI coding agent), open this repo in your terminal and prompt:

> *"Please read `FRIEND_SETUP_GUIDE.md`. I want to set up my own instance of this finance terminal. I'm deciding between the author's cloud setup (Vercel + Render + Neon) and a 100% local setup + Tailscale. Help me provision the database, run the ledger migration, configure environment variables, and adapt the AI wrapper in `backend/services/gemini_util.py` to use my Anthropic Claude API key."*

---

## 🧭 Complete Tour: What the Terminal Does

The terminal is composed of multiple quant and portfolio modules accessible via the top navigation bar:

### 1. 📈 Portfolio Dashboard (`/portfolio`)
- **Multi-Account View**: Toggle between individual accounts (`ISA`, `SIPP`, `GIA`, `Crypto`, etc.) or view an aggregate **Consolidated** portfolio.
- **Real-Time Valuation**: Daily net asset value (NAV), daily profit & loss (P&L), total return, and time-weighted returns.
- **Asset Allocation**: Breakdown by asset class, geography, and equity style.
- **Top Holdings & Gainers/Losers**: Real-time pricing with currency conversion (supports GBP, USD, and EUR natively).

### 2. ⚡ Performance & Factor Analysis (`/performance`)
- **Fama-French 3-Factor & 5-Factor Regressions**: Analyzes your portfolio's sensitivity to Market Beta, Size (SMB), Value (HML), Profitability (RMW), and Investment (CMA).
- **Benchmark Comparison**: Compare your time-weighted portfolio returns against standard benchmarks (e.g. S&P 500, MSCI World, FTSE All-Share) or custom benchmark blends built in the Benchmark Builder.
- **Risk Metrics**: Sharpe ratio, Sortino ratio, Max Drawdown, rolling volatility, and historical Value-at-Risk (VaR).

### 3. 🔬 ETF Look-Through Analysis (inside `/portfolio` tab)
- **Deep-Dive Underlying Holdings**: Scrapes and parses ETF fact sheets to see your true underlying exposure (e.g., if you own VWRL, CSPX, and IITU, it calculates your real combined exposure to Apple, Microsoft, or Nvidia across all funds).
- **Overlap Detection**: Detects hidden correlation and duplicate risk across multiple ETFs.

### 4. ⚖️ Portfolio Optimization (Mean-Variance & Risk Parity)
- **Markowitz Efficient Frontier**: Computes optimal portfolio weights based on historical return distributions and covariance matrices.
- **Objective Functions**: Maximize Sharpe Ratio, Minimize Volatility, or Target specific return constraints.

### 5. 🔍 Market Screener & Technicals (`/technicals`)
- **Multi-Asset Technical Screener**: Real-time indicators across your watchlist and market indices (RSI, Bollinger Bands, Moving Averages 50/200-day, MACD).
- **TradingView Lightweight Charts**: Interactive candlesticks and volume histograms.
- **Uptrend / Downtrend Alerts**: Automated state tracking for breakout signals.

### 6. 📰 Market Intelligence & AI Newsletters (`/newsletter`)
- **Automated Investor Letter**: Synthesizes weekly market movements, portfolio performance, and macro news into an institutional-grade PDF and HTML email digest.
- **Executive Summaries**: AI commentary explaining portfolio attribution and macro regime changes.

### 7. 📥 Trade Ingestion & Reconciliation (inside `/portfolio`)
- **Spreadsheet & PDF Import**: Upload raw broker transaction ledgers (`.csv`, `.xls`, `.pdf`).
- **Interactive Staging Table**: Review, edit, and sanitize trades with automatic ticker resolution (e.g. converting ISINs or broker descriptions to Yahoo Finance tickers) before committing to the database.

### 8. ⚙️ Settings, Benchmark Builder & Diagnostics (`/settings`)
- **Custom Benchmark Builder**: Create and persist synthetic multi-asset benchmark blends (e.g. `80% World Equities + 20% Global Bonds`) to benchmark your accounts against.
- **AI Prompt Editor**: Customize the system prompts used for Market Intelligence and Macro summaries directly from the UI (`backend/prompts_config.json`).
- **Technical Alert Configuration**: Configure RSI thresholds and weekly recap schedules for Uptrend and Downtrend scanners.
- **Engine Audit & Diagnostics**: Inspect raw ledger reconciliation, price source coverage, and nightly calculation run logs.

---

## 🚀 Setup Path 1: The Cloud Stack (Vercel + Render + Neon)
*This is the exact stack I implemented for the live website.*

### 1. Database (Neon PostgreSQL)
1. Create a free account at [Neon.tech](https://neon.tech/) and create a project.
2. Under Connection Details, select **Connection string (pooled)**:
   ```text
   postgresql://[user]:[password]@[ep-name]-pooler.neon.tech/neondb?sslmode=require
   ```
3. Open the **SQL Editor** in Neon and run the ledger DDL:
   - Run [`migrations/ledger/001_ledger_core.sql`](./migrations/ledger/001_ledger_core.sql)
   *(Note: `migrations/app_db/` schemas are applied automatically on backend startup).*

### 2. Backend (Render / Railway)
1. Fork or push this repository to your GitHub.
2. Create a new **Web Service** on [Render.com](https://render.com/).
3. Connect your repository:
   - **Environment**: Python 3
   - **Build Command**: `pip install -r backend/requirements.txt`
   - **Start Command**: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
4. Set Environment Variables in Render:
   - `DATABASE_URL`: Your pooled Neon connection string.
   - `ALLOWED_ORIGINS`: `https://your-frontend.vercel.app`
   - `ANTHROPIC_API_KEY` (or `GEMINI_API_KEY`): Your AI API key.
5. Copy your Render web service URL (e.g. `https://my-terminal-api.onrender.com`).

### 3. Frontend (Vercel)
1. Create a new project on [Vercel](https://vercel.com/) and import your repo.
2. In Project Settings, set **Root Directory** to `frontend`.
3. Add Environment Variables:
   - `NEXT_PUBLIC_API_URL`: Your Render backend URL (`https://my-terminal-api.onrender.com`).
   - `APP_PASSCODE`: Your desired web passcode (e.g. `1234`).
4. Click **Deploy**. Your terminal is now live online!

---

## 💻 Setup Path 2: 100% Local Setup + Tailscale (No-Fuss, Zero Cloud)
*If you don't want to manage third-party cloud accounts and prefer running on your PC.*

### 1. Local Database (Docker or Native Postgres)
Run a local PostgreSQL container in 5 seconds:
```bash
docker run --name finance-db -e POSTGRES_PASSWORD=postgres -p 5432:5432 -d postgres:16
```
Or use a native PostgreSQL server (`brew install postgresql@16` on Mac or the Windows installer).

Initialize the ledger table:
```bash
psql -h localhost -U postgres -d postgres -f migrations/ledger/001_ledger_core.sql
```

### 2. Environment Variables
- In root `.env`:
  ```bash
  DATABASE_URL="postgresql://postgres:postgres@localhost:5432/postgres"
  ALLOWED_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"
  ANTHROPIC_API_KEY="your-anthropic-key"  # or GEMINI_API_KEY
  ```
- In `frontend/.env.local`:
  ```bash
  NEXT_PUBLIC_API_URL="http://localhost:8000"
  APP_PASSCODE="1234"
  NEXT_PUBLIC_APP_PASSCODE="1234"
  ```

### 3. Start Both Services
Terminal 1 (Backend):
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000
```

Terminal 2 (Frontend):
```bash
cd frontend
npm install
npm run dev
```
Open **`http://localhost:3000`** in your browser!

### 4. Remote Access with Tailscale (View on Phone/Laptop)
To view your local setup on your phone or laptop away from home without any cloud hosting:
1. Install [Tailscale](https://tailscale.com/) on your host computer and your phone/laptop.
2. Find your computer's Tailscale IP (e.g. `100.64.0.15`).
3. Add that IP to `ALLOWED_ORIGINS` in `.env`:
   ```bash
   ALLOWED_ORIGINS="http://localhost:3000,http://100.64.0.15:3000"
   ```
4. In `frontend/.env.local`, set:
   ```bash
   NEXT_PUBLIC_API_URL="http://100.64.0.15:8000"
   ```
5. Run the servers listening on all interfaces (`--host 0.0.0.0` for uvicorn, `npm run dev -- -H 0.0.0.0` for Next.js).
6. Connect to `http://100.64.0.15:3000` securely from your phone anywhere!

---

## 🧠 Using Anthropic Claude API instead of Gemini

All 7 AI-powered features in the backend (**Market Screener**, **Investor Newsletter**, **PDF Trade Ingestion**, **AI Ticker Resolution**, **ETF Look-Through Metadata Repair**, **Technicals AI Summary**, and **Email Alerts**) route through a single central factory function: `get_best_gemini_model(api_key)` in [`backend/services/gemini_util.py`](./backend/services/gemini_util.py), which returns a model wrapper with a `.generate_content(contents)` method returning an object with `.text`.

To switch the entire application to **Anthropic Claude**, have **Claude Code** make this single centralized change:

1. **Install Anthropic SDK**: `pip install anthropic` (and add `anthropic` to `requirements.txt` / `backend/requirements.txt`).
2. **Add Key to `.env`**: `ANTHROPIC_API_KEY="sk-ant-..."` (or pass it via `GEMINI_API_KEY` if you want zero config-file changes).
3. **Update `backend/services/gemini_util.py`**:
   Add a drop-in `ClaudeModelWrapper` inside `get_best_gemini_model()` so every service works with Claude automatically:
   ```python
   class _ClaudeResponse:
       def __init__(self, text: str):
           self.text = text

   class ClaudeModelWrapper:
       def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
           import anthropic
           self.client = anthropic.Anthropic(api_key=api_key)
           self.model_name = model

       def generate_content(self, contents, config=None, **kwargs):
           prompt = contents if isinstance(contents, str) else str(contents)
           resp = self.client.messages.create(
               model=self.model_name,
               max_tokens=4096,
               messages=[{"role": "user", "content": prompt}],
           )
           return _ClaudeResponse(resp.content[0].text)
   ```
   Then in `get_best_gemini_model(api_key, ...)`, check for `os.environ.get("ANTHROPIC_API_KEY")` (or `api_key.startswith("sk-ant-")`) and return `ClaudeModelWrapper(anthropic_key)`.

*(Note: Even without any AI API key configured, all core portfolio math, Sharpe/Sortino ratios, Fama-French factor regressions, efficient frontier optimization, and charts run 100% offline using NumPy/Pandas and yfinance!)*
