# Finance Tool: Future Web App Migration Plan

This document outlines the strategies, architecture, and requirements discussed for upgrading the current Streamlit prototype (`app.py`) into a highly professional, bespoke web application. It is designed to be a reference for when you are ready to execute the upgrade.

---

## 1. The Core Architecture Shift
Currently, Streamlit handles both the backend logic and frontend display in a single file. To achieve a truly premium, custom UI, the industry standard is to decouple the system into two distinct parts:

*   **The Backend (API):** Built with **FastAPI** (Python). This will house all your existing Python logic (fetching Yahoo Finance data, Gemini AI report generation, metric calculations) and serve it as raw data endpoints.
*   **The Frontend (UI):** Built with **Next.js / React** (JavaScript/TypeScript). This will consume the data from the backend and render it with pixel-perfect control, custom animations, and a modern aesthetic.

---

## 2. The Incremental Migration Plan

To control token consumption and ensure you never break the working tool, we will migrate the application piece-by-piece over time. This approach breaks the project into 4 distinct phases that you can execute weeks or months apart. 

For each phase, you can copy and paste the provided **Key Prompt** to initiate the AI workflow.

### Phase 1: API Extraction (Estimated Time: 1-2 Hours)
We create a new `backend` folder and set up FastAPI. We move your pure Python logic (fetching Yahoo Finance data, Gemini prompts) into this backend. Your existing Streamlit app is then updated to fetch its data from this new local API instead of calculating it directly. You still use the Streamlit UI, but the "brain" of the app is now a professional API.

**Key Prompt to use:**
> "Create a `backend` folder and initialize a FastAPI application. Extract the data fetching and calculation logic from `app.py` into FastAPI endpoints. Keep `app.py` completely functional by replacing its internal calculation logic with requests to the new local FastAPI endpoints. Stop when complete so I can verify the Streamlit app still works."

### Phase 2: Frontend Foundation & Design System (Estimated Time: 1-2 Hours)
We create the `frontend` folder with Next.js. We analyze your newsletter and establish the global design system (Tailwind config, fonts, colors, dark mode setup). This results in a blank web app that perfectly matches your brand aesthetic, running on `localhost:3000`.

**Key Prompt to use:**
> "Initialize a Next.js project in a `frontend` folder. Review the **[INSERT NEWSLETTER FILENAME]** file to extract my brand's color palette, typography, and dark mode aesthetic. Apply this design system globally using Tailwind CSS. Set up the basic structural layout (e.g., sidebar and header). Do not build any specific tool features yet. Stop when the blank layout is rendering beautifully."

### Phase 3: Page-by-Page Migration (Estimated Time: 1-2 Hours per page)
Instead of building the whole UI at once, we migrate one feature at a time. We will translate each of the existing Streamlit pages into Next.js React components, connecting them to the FastAPI backend. 

Here are the specific prompts you can use to kick off each page migration session:

#### 1. Market Screener
> "Build the 'Market Screener' page in the Next.js frontend. Replicate the functionality from `pages/01_📈_Market_Screener.py`. Create React components for the data tables and the AI Report generation, ensuring they strictly adhere to our premium brand aesthetic (Cream/Navy/Gold). Connect this page to the FastAPI backend to fetch the real data. Stop when the Market Screener is fully functional."

#### 2. Portfolio Core: Dashboard & Trade Ingestion
> "Build the 'Portfolio Dashboard' and 'Trade Ingestion' pages in the Next.js frontend. Replicate the layout and core metrics from `pages/02_📊_Portfolio_Dashboard.py` and `pages/03_✍️_Trade_Ingestion.py`. Create modern, interactive charts for the portfolio history and a clean, responsive form for trade uploads. Connect them to the FastAPI backend. Stop when complete."

#### 3. Portfolio Core: Newsletter
> "Build the 'Newsletter' generator page in the Next.js frontend based on `pages/04_📰_Newsletter.py`. Ensure the web UI matches the premium, editorial aesthetic of the newsletter itself. Connect the generation and scheduling logic to the backend."

#### 4. Analytics: Technicals & Look-Through
> "Build the 'Technicals' and 'Look-Through' analytics pages in the Next.js frontend based on `pages/05_📈_Technicals.py` and `pages/06_🔬_Look_Through.py`. Create the Technicals page as a distinct top-level page, alongside a renamed 'Performance & PnL' page (formerly Market Screener). Both pages must share a unified sidebar ticker dropdown that only lists current holdings and positions exited within the last 12 months, plus an 'Add New' button to analyze arbitrary tickers. Restore all missing dividend/yield/return metrics to the Performance page. For the Technicals page, integrate 'lightweight-charts' by TradingView to render sophisticated, synced candlestick and momentum charts matching the old Streamlit functionality. Connect the backend to serve the pre-calculated indicators."

#### 5. Analytics: Benchmarks, Diagnostics, Optimization & Factors
> "Build the remaining analytics pages ('Benchmark Builder', 'Diagnostics', 'Portfolio Optimization', and 'Factor Analysis') in Next.js. Replicate the complex data tables and calculation forms. Ensure the UI feels like a professional, high-end quant terminal. Stop when complete."

### Phase 4: Polish & Deployment (Estimated Time: 1-2 Hours)
We add micro-animations, loading states, and deploy both the Next.js frontend to Vercel and the FastAPI backend to Render. The Streamlit app is finally retired.

**Key Prompt to use:**
> "Review the entire Next.js frontend. Add professional micro-animations (e.g., hover effects, smooth table loading states, skeleton loaders for the AI report). Ensure mobile responsiveness. Then, guide me through deploying the backend to Render and the frontend to Vercel."

---

## 3. Design & Branding Requirements

To ensure the new application feels like a natural extension of your brand, the design must be anchored to your existing weekly newsletter.

*   **Reference Material:** Before initiating the frontend build (Phase 2), ensure you provide the AI with a copy of your weekly newsletter (e.g., an HTML file, PDF, or screenshot saved in the project directory).
*   **Extraction:** The AI must extract the exact color palette, typography choices, and general spacing/vibe from the newsletter and apply them to the Tailwind CSS configuration in the Next.js app.

---

## 4. Hosting & Cost Breakdown ($0/month)

Assuming you remain the primary/sole user, you can host the decoupled application for free using modern cloud developer tiers:

*   **Frontend Hosting (Next.js):** Vercel or Netlify. Cost: **$0/mo**. (Provides high-speed global delivery).
*   **Backend Hosting (FastAPI):** Render or PythonAnywhere. Cost: **$0/mo**. (Note: Render's free tier spins down after 15 minutes of inactivity, resulting in a ~45-second "cold start" delay for your first visit of the day).
*   **APIs (Yahoo Finance / Gemini):** Remains on existing free tiers/API keys.
*   **Total Monthly Cost:** **$0.00** *(Excluding any custom domain name registration, which is optional).*

---

## Appendix: The Autonomous "Big Bang" Rewrite

If you decide you do *not* want to control token costs and simply want the AI to execute the entire migration autonomously in one massive run, you can use the following "Perfect Prompt". 

**Warning:** This has the highest upfront token consumption.

> **`/goal`** Rebuild my current Streamlit app (`app.py`) into a professional web application. 
> 
> 1. **Architecture:** Use Next.js for the frontend and FastAPI for the backend.
> 2. **Design & Branding:** The design must be completely consistent with my weekly newsletter. Please review the file **[INSERT NEWSLETTER FILENAME HERE]** located in this directory. Extract the color palette, typography, and overall aesthetic (light/dark mode, spacing, button styles) from that file and apply it strictly to the new web app so my brand identity is seamless.
> 3. **Location:** Create a `frontend` and `backend` folder inside my current `Finance Tool` directory and build the projects there.
> 4. **Scope:** Do a 1:1 copy of all current features found in `app.py`. 
> 
> You have full autonomy to analyze the newsletter, make design decisions based on it, create files, and run commands to set this up. Go.
