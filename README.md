# Aegis Finance Terminal

A quantitative portfolio intelligence, automated reporting, and market analytics terminal.

> 📖 **Full Setup & Feature Guide:** See **[`FRIEND_SETUP_GUIDE.md`](./FRIEND_SETUP_GUIDE.md)** for step-by-step instructions (Cloud vs. 100% Local + Tailscale setup, Claude Code prompt, and complete feature walkthrough).

## Architecture

The platform uses a modern decoupled architecture:

- **Frontend (`frontend/`)**: [Next.js 16](https://nextjs.org/) (App Router), React 19, TypeScript, Tailwind CSS, Lucide icons, Lightweight Charts, and Recharts.
- **Backend (`backend/`)**: [FastAPI](https://fastapi.tiangolo.com/) (Python 3.11+), Uvicorn, PostgreSQL (Neon / Supabase / Local Postgres), AI market intelligence integration, and background task schedulers.
- **Ledger & DB (`migrations/`, `data/`)**: Multi-currency transaction ledgers, ETF look-through holdings database, Fama-French 3-factor & 5-factor models, and cached market prices.

---

## Directory Overview

```
Finance Tool/
├── backend/                  # FastAPI REST API, background schedulers & services
│   ├── main.py               # API entrypoint & route registration
│   ├── config.py             # App configuration & environment resolution
│   ├── scheduler.py          # Background auto-refresh & cron jobs
│   ├── routers/              # Modular API route controllers
│   └── services/             # Core quant calculation engines & integrations
├── frontend/                 # Next.js TypeScript web terminal
│   ├── app/                  # App Router pages (Portfolio, Performance, Technicals, etc.)
│   ├── components/           # UI components, tables, charts & navigation
│   └── hooks/                # Custom React hooks for data fetching & state
├── migrations/               # PostgreSQL DDL schemas for app_db and ledger
├── data/fama_french/         # Fama-French 3-factor and 5-factor datasets
├── Newsletter template/      # HTML templates, assets, and styling for email digests
├── scripts/                  # Admin utilities and database migration helpers
└── FRIEND_SETUP_GUIDE.md     # Complete architecture, feature tour & setup guide
```

---

## Quickstart & Local Development

### 1. Backend (FastAPI)
```bash
# From workspace root
uvicorn backend.main:app --reload --port 8000
```
API Documentation: `http://localhost:8000/docs`  
Health Check: `http://localhost:8000/health`

### 2. Frontend (Next.js)
```bash
cd frontend
npm install
npm run dev
```
Terminal UI: `http://localhost:3000`
