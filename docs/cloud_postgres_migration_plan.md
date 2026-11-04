# Database Infrastructure Consolidation: Supabase Postgres Migration Plan

This document outlines the plan to move the current Aegis Terminal database stack to **Supabase PostgreSQL** while keeping the application effectively single-user for now. This is an intermediate infrastructure step: it removes the fragile SQLite/Postgres compatibility layer and moves the ledger away from Google Sheets, but it does **not** attempt to implement full multi-user product behavior yet.

The main goals are:
- Use native PostgreSQL everywhere instead of runtime SQLite query translation.
- Move the Google Sheets ledger into Supabase Postgres.
- Keep the ledger more protected than derived/cache data because it is the hardest data to reconstruct after an accidental wipe.
- Preserve a local, recoverable copy of the latest database state when the tool is opened locally.
- Create a clean foundation for eventual multi-user functionality without doing that work in this migration.

---

## 1. Current Problems

The application currently maintains a hybrid persistence model:

- **Ledger and account settings:** stored in Google Sheets and accessed through `gspread`.
- **Computed caches:** stored in SQLite locally, with production optionally routed to PostgreSQL through compatibility wrappers.
- **Runtime SQL translation:** `PostgreSQLConnectionWrapper`, `PostgreSQLCursorWrapper`, and `DictRowWrapper` translate SQLite-flavoured SQL into PostgreSQL-ish SQL at runtime.
- **Local/cloud drift:** local SQLite and cloud PostgreSQL can diverge in behavior and schema.
- **Recovery weakness:** a mistaken cache clear, sync issue, or manual DB wipe can be difficult to reason about because source-of-truth and derived data are not cleanly separated.

The target design should separate **irreplaceable source data** from **rebuildable derived data**.

---

## 2. Target Architecture

Use two Supabase projects:

```text
                    +------------------------+
                    |  Next.js UI (Vercel)   |
                    +-----------+------------+
                                |
                                | HTTPS
                    +-----------v------------+
                    |  FastAPI API (Render)  |
                    +-----------+------------+
                                |
              +-----------------+-----------------+
              |                                   |
     +--------v---------+               +---------v--------+
     | Supabase Ledger  |               | Supabase App DB  |
     | Source of truth  |               | Derived/cache DB |
     +------------------+               +------------------+
```

### Supabase Ledger Project

This project stores source-of-truth data:

- accounts
- transactions
- ticker map overrides
- migration import batches
- immutable/audit metadata

This project should be treated as protected infrastructure. The application should only perform narrow insert/update/delete operations through explicit ledger functions. Bulk destructive operations should not run against this project from normal app flows.

### Supabase App DB Project

This project stores rebuildable application data:

- portfolio snapshots
- per-ticker daily portfolio cache
- benchmark snapshots
- benchmark constituent cache
- last prices
- run logs
- engine audits
- look-through caches
- ETF holdings/reference caches where appropriate

If this database is corrupted or wiped, the app should be able to rebuild it from the Ledger project plus market/reference data.

### Local Recovery Copy

When the backend is opened locally, the tool should be able to save a latest-known-good copy of database state to the PC. This is not a dev Supabase project. It is a local recovery/export mechanism.

Recommended local backup output:

- `backups/YYYY-MM-DD_HHMMSS/ledger_export.sql` or `.dump`
- `backups/YYYY-MM-DD_HHMMSS/app_db_export.sql` or `.dump`
- `backups/YYYY-MM-DD_HHMMSS/manifest.json`
- `backups/YYYY-MM-DD_HHMMSS/reconciliation_report.json`

The manifest should include source project identifiers, table row counts, export timestamp, schema version, and checksums where practical.

---

## 3. Scope Boundaries

This migration should not implement full multi-user functionality yet.

In scope:

- Supabase Postgres as the canonical database engine.
- Separate source-of-truth ledger project and derived/cache app project.
- Native Postgres SQL and migrations.
- Removal of Google Sheets as the live ledger.
- Removal of SQLite/Postgres compatibility wrappers.
- Local backup/export capability for recovery.
- Schema choices that do not block future user isolation.

Out of scope for this phase:

- User signup/login product flow.
- Row Level Security policies for multiple end users.
- Per-user dashboards.
- Sharing portfolios between users.
- A public self-service import tool.

However, schemas should include a fixed internal `owner_id` column where cheap, so future multi-user migration does not require a painful rewrite. During this single-user phase, use one constant internal UUID such as `00000000-0000-0000-0000-000000000001`.

---

## 4. Database Schema Plan

Use proper SQL migration files rather than creating production schemas opportunistically during app startup.

Recommended structure:

```text
migrations/
  ledger/
    001_ledger_core.sql
    002_ledger_indexes.sql
    003_ledger_audit_guards.sql
  app_db/
    001_cache_core.sql
    002_cache_indexes.sql
    003_reference_tables.sql
```

### 4.1 Ledger Project Tables

```sql
CREATE TABLE accounts (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    owner_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    account_name TEXT NOT NULL,
    classification TEXT NOT NULL DEFAULT 'Live',
    base_currency VARCHAR(3) NOT NULL DEFAULT 'GBP' CHECK (length(base_currency) = 3),
    legacy_cash_adjustment NUMERIC(18, 4) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    UNIQUE (owner_id, account_name)
);

CREATE TABLE transactions (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    owner_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    account_id BIGINT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    transaction_date DATE NOT NULL,
    action TEXT NOT NULL,
    asset_name TEXT NOT NULL,
    qty NUMERIC(24, 8) NOT NULL DEFAULT 0,
    price NUMERIC(24, 8) NOT NULL DEFAULT 0,
    net_amount NUMERIC(24, 8) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'GBP' CHECK (length(currency) = 3),
    auto_ticker TEXT,
    notes TEXT,
    raw_details TEXT,
    source_system TEXT NOT NULL DEFAULT 'google_sheets',
    source_sheet TEXT,
    source_row_number INTEGER,
    source_row_hash TEXT,
    import_batch_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    UNIQUE (source_system, source_sheet, source_row_number, source_row_hash)
);

CREATE TABLE ticker_map (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    owner_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    asset_name TEXT NOT NULL,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'migration',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    UNIQUE (owner_id, asset_name)
);

CREATE TABLE import_batches (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    source_system TEXT NOT NULL,
    source_description TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',
    account_count INTEGER,
    transaction_count INTEGER,
    ticker_map_count INTEGER,
    reconciliation_json JSONB
);
```

Notes:

- `ON DELETE RESTRICT` is intentional for ledger transactions. Deleting an account should not casually delete historical source records.
- `source_row_hash` enables idempotent re-runs and more reliable duplicate detection than checking duplicate dates.
- `owner_id` should be fixed to a single internal UUID for now. Avoid nullable ownership columns in unique constraints because Postgres treats `NULL` values as distinct.
- `NUMERIC(18, 4)` is safer than `NUMERIC(15, 2)` for cash values because some imported data may require more than two decimal places before final presentation.

### 4.2 App DB Tables

The App DB must include all currently persisted cache tables, converted to native Postgres types and future-compatible ownership keys:

- `portfolio_snapshots`
- `portfolio_ticker_daily`
- `benchmark_snapshots`
- `benchmark_ticker_daily`
- `saved_benchmarks`
- `last_prices`
- `run_log`
- `engine_audit`
- `lookahead_cache`
- `etf_holdings`
- `constituent_metadata`
- `ticker_isin_map`
- `staleness_registry`
- `etf_kiid`
- `movers_price_cache`

Example cache table:

```sql
CREATE TABLE portfolio_snapshots (
    owner_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    account_name TEXT NOT NULL,
    date DATE NOT NULL,
    equity_gbp NUMERIC(18, 4),
    cash_gbp NUMERIC(18, 4),
    total_nav_gbp NUMERIC(18, 4),
    twr_index NUMERIC(18, 8),
    net_invested NUMERIC(18, 4),
    daily_return NUMERIC(18, 10),
    bench_nav NUMERIC(18, 8),
    run_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id, account_name, date)
);
```

Important App DB rules:

- Cache tables should be clearable/rebuildable.
- Ledger tables should never live in the App DB.
- Any function that clears account data must target App DB only unless it is an explicitly named ledger maintenance function.
- `gsheet_cache` should be removed after migration because Google Sheets will no longer be the live source.

---

## 5. Security and Wipe Protection

The Ledger project should have stronger controls than the App DB.

Recommended safeguards:

1. **Separate Supabase project:** Ledger and App DB use different connection strings and credentials.
2. **Least privilege credentials:** normal runtime credentials should not own the schema and should not have blanket `DROP`, `TRUNCATE`, or unrestricted delete permissions.
3. **No app-level bulk wipe path:** cache-clearing endpoints must only point at the App DB.
4. **Soft-delete preference:** if ledger deletion is needed later, prefer `deleted_at` over physical deletion.
5. **Periodic export:** local backup/export should include the Ledger project every time the tool is opened locally, subject to throttling.
6. **Manual restore drill:** before removing Google Sheets, perform one restore from local export into a scratch database.
7. **Supabase backups:** enable whatever project-level backups are available/appropriate, but do not rely on provider backups as the only recovery path.

---

## 6. Code Refactor Plan

### Phase 1: Introduce Native Postgres Database Access

- Add explicit Ledger DB and App DB connection configuration:
  - `LEDGER_DATABASE_URL`
  - `APP_DATABASE_URL`
- Replace implicit `DATABASE_URL` routing with named connection helpers.
- Remove SQLite-specific runtime SQL translation.
- Use native Postgres placeholders and `ON CONFLICT` clauses.
- Keep connection logic small and boring: connect, execute parameterized SQL, commit/rollback.

### Phase 2: Move Account Registry and Ledger Reads to Ledger DB

Refactor data access functions so they read from Supabase Ledger:

- `get_account_registry()`
- `get_account_base_currency()`
- `get_legacy_cash_adjustment()`
- `get_consolidated_live_ledger()`
- `get_sanitized_ledger()`
- ticker map lookup helpers

The returned DataFrame shapes should remain compatible with the engine initially. This keeps the migration smaller: first change persistence, then simplify internal data shapes later.

### Phase 3: Application Refactor

**CRITICAL CONSTRAINT:** The original Streamlit app (files in the root directory like `app.py`, `app_v2.1.py`, `data_handler.py`, `storage.py`, `holdings_db.py`) must remain completely untouched. They will continue to use SQLite and Google Sheets. The refactoring in this phase applies **ONLY** to the new backend application located in the `backend/` directory.

1. Create native Postgres helpers for Ledger DB access using `psycopg2` or `asyncpg` in `backend/services/`.
2. Refactor read queries in `backend/services/data_handler.py` and `backend/services/storage.py` to hit Ledger DB instead of gspread.
3. Replace all SQLite writes in `backend/` App DB functions with Postgres native inserts (and `ON CONFLICT` patterns).
- insert rich transaction rows directly
- update `ticker_map` when a new asset/ticker mapping is confirmed
- invalidate relevant in-memory cache
- trigger App DB cache rebuild when appropriate
- keep audit/import metadata

### Phase 4: Convert App Cache Writes to Native Postgres

Convert storage and holdings cache functions to use App DB directly:

- `save_portfolio_run()`
- `load_latest_portfolio()`
- `save_benchmark_run()`
- `load_latest_benchmark()`
- `save_last_prices()`
- `save_engine_audit()`
- look-through cache functions
- run log functions

Every App DB write should be idempotent where practical.

### Phase 5: Remove Google Sheets Runtime Dependency

Only after reconciliation passes:

- remove `gspread` from backend requirements
- remove Google service account secrets from active runtime config
- delete/inactivate `gsheet_cache`
- remove Google Sheets paths from ingestion and data handler code
- keep a final exported copy of the Sheets data outside the app repo

---

## 7. One-Time Migration Plan

Create `scripts/migrate_sheets_to_supabase_ledger.py`.

The script should:

1. Connect to the current Google Sheet.
2. Create an `import_batches` row.
3. Import `Account_Settings` into `accounts`.
4. Import all ledger worksheets into `transactions`.
5. Import `Ticker_Map` into `ticker_map`.
6. Preserve raw row metadata:
   - source sheet
   - source row number
   - raw details
   - row hash
7. Support dry-run mode.
8. Support idempotent re-run mode.
9. Emit a reconciliation report.

Reconciliation checks:

- account counts match source
- transaction counts match by worksheet/account
- total `Paid In`, `Withdrawn`, and `Net Amount` match source within tolerance
- first and last transaction date match by account
- ticker map count matches source
- duplicate source rows are reported, not silently collapsed
- rich-schema and legacy-schema worksheets are both handled explicitly

Do not sever Google Sheets until these checks pass and a local backup has been created.

---

## 8. Local Backup and Recovery Plan

When the backend runs locally, provide a tool action or startup task that can export the latest Ledger and App DB state to the local PC.

Recommended behavior:

- Do not export on every hot reload. Throttle to once per day by default.
- Allow manual "Backup now" from diagnostics/settings.
- Store backups under a local `backups/` directory excluded from git.
- Keep at least the latest N backups, for example 14 daily backups.
- Include a manifest and reconciliation report.
- Test restore into a scratch/local database before declaring the migration complete.

This replaces the need for a separate Supabase Dev project as the primary safety mechanism. A Dev project may still be useful later for staging releases, but it is not required for this migration.

---

## 9. Rollout Sequence

1. Create Ledger Supabase project.
2. Create App DB Supabase project.
3. Apply Ledger migrations.
4. Apply App DB migrations.
5. Run Google Sheets to Ledger migration in dry-run mode.
6. Run migration for real into Ledger.
7. Run reconciliation report.
8. Create local backup/export of both projects.
9. Restore backup into scratch DB to prove recoverability.
10. Point local app to Ledger/App DB in read-only comparison mode.
11. Compare engine outputs against current Google Sheets + SQLite path.
12. Switch ledger reads to Ledger DB.
13. Switch trade commits to Ledger DB.
14. Switch cache writes to App DB.
15. Run full recalculation and verify dashboards.
16. Remove Google Sheets runtime dependency.
17. Keep Google Sheets frozen as an archive for a defined cooling-off period.

---

## 10. Acceptance Criteria

The migration is complete when:

- The app can run without Google Sheets credentials.
- Ledger reads come from the Ledger Supabase project.
- Derived caches write to the App DB Supabase project.
- Clearing/rebuilding caches cannot wipe ledger source data.
- Local backup/export exists and has been restore-tested.
- Current portfolio outputs match pre-migration outputs within defined tolerances.
- Trade ingestion writes new rows to Supabase Ledger and updates ticker mappings.
- The SQLite/Postgres compatibility wrappers are removed.
- `gspread` is no longer required by the backend runtime.

---

## 11. Key Risks

- **Ledger migration loss:** mitigated by dry-run, row hashes, reconciliation reports, and local exports.
- **Accidental ledger wipe:** mitigated by separate project, limited credentials, no bulk wipe endpoint, and restore-tested backups.
- **Behavior drift:** mitigated by preserving DataFrame shapes initially and comparing engine outputs before cutover.
- **Precision drift:** mitigated by `NUMERIC` types for financial values and explicit tolerances in reconciliation.
- **Operational confusion:** mitigated by named `LEDGER_DATABASE_URL` and `APP_DATABASE_URL` instead of one ambiguous `DATABASE_URL`.

---

## 12. Future Multi-User Readiness

This plan deliberately stops short of multi-user functionality, but it should not block it.

Future work can add:

- Supabase Auth
- JWT verification in FastAPI
- non-null `owner_id`
- Row Level Security
- per-user account isolation
- frontend sign-in/sign-up flows

The intermediate migration should therefore avoid assumptions that make all data globally scoped forever.
