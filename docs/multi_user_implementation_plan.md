# Multi-User Authentication & Implementation Plan

## Context
A review of the current codebase shows that the **Cloud Postgres Migration** phase has been successfully completed, and the database has been migrated to **Neon**. The legacy Google Sheets dependency has been fully retired, and all data (Ledger & Cache) now resides natively in Neon PostgreSQL (`LEDGER_DATABASE_URL` and `APP_DATABASE_URL`). 

Crucially, the database tables (`accounts`, `transactions`, `portfolio_snapshots`, etc.) **already include an `owner_id` column**. However, the backend is currently running in a single-user mode, using a hardcoded internal UUID (`00000000-0000-0000-0000-000000000001`) for all database operations, and the frontend still uses a single passcode (`NEXT_PUBLIC_APP_PASSCODE`).

The goal of this phase is to activate real multi-tenant functionality by introducing proper user authentication and passing the authenticated `user_id` throughout the stack.

## User Review Required

> [!IMPORTANT]
> **Authentication Provider Selection:** 
> Since we are using Neon instead of Supabase, we don't have "Supabase Auth" built-in. We need to choose an authentication provider. 
> **Recommendation:** We can use **Auth.js (NextAuth)** on the frontend with a simple credentials provider, and issue a JWT token to the FastAPI backend, OR we can use a managed service like **Clerk** which provides pre-built beautiful login components and handles all the JWT issuance automatically. 

> [!WARNING]
> **Existing Dummy UUID Data:** 
> Your existing data in Neon is currently tied to the dummy UUID `00000000-0000-0000-0000-000000000001`. Once you create a real user account for yourself, we will need to run a one-time SQL script to `UPDATE` all your tables and replace the dummy UUID with your real `user_id`.

## Open Questions

> [!NOTE]
> 1. **Auth Provider:** Do you prefer a simple custom email/password system (NextAuth + custom FastAPI JWT), or a managed provider like Clerk/Auth0?
> 2. **Sign-up Policy:** Do you want to allow self-service sign-ups (where anyone with the URL can register), or should we disable public sign-ups so you have to manually invite/create accounts for family members?

---

## Proposed Changes

### Database Layer (Neon Postgres)
The physical tables and `owner_id` columns already exist. We need to:
- **Data Transfer Migration Script**: Provide you with a short SQL script to map your current `00000000-0000-0000-0000-000000000001` records to your actual registered UUID once you sign up.
- **(Optional) Users Table**: If we go with a custom Auth solution, we will need to create a `users` table in Neon to store email and hashed passwords.

### Backend Layer (FastAPI)

#### [NEW] `backend/auth.py`
A new utility module to validate the authorization header token (either verifying our own JWT or verifying the Clerk/NextAuth JWT via JWKS):
- Decodes the JWT token sent from Next.js (`Authorization: Bearer <token>`).
- Returns the authenticated user's UUID (`user_id`).

#### [MODIFY] `backend/main.py` & `backend/routers/*.py`
- Create a FastAPI dependency `Depends(get_current_user_id)`.
- Inject this dependency into all protected routes in `portfolio.py`, `ingestion.py`, `screener.py`, etc.
- Pass the dynamic `user_id` down into the engine and service calls instead of relying on default parameters.

#### [MODIFY] `backend/services/database.py` & Data Access Functions
- The data access functions (e.g., `get_sanitized_ledger`, `get_account_registry` in `backend/services/data_handler.py` and `backend/services/storage.py`) currently do not filter by `owner_id` in their SQL queries.
- We must update these SQL strings to include `WHERE owner_id = %s` (or `AND owner_id = %s`) and pass the verified `user_id` from the router layer.

### Frontend Layer (Next.js)

#### [MODIFY] `frontend/app/login/page.tsx`
- Replace the current client-side passcode logic (`NEXT_PUBLIC_APP_PASSCODE`).
- Integrate the chosen authentication provider's Sign In / Sign Up interface.

#### [MODIFY] `frontend/components/layout/AuthGuard.tsx`
- Refactor the check from the `auth_passcode` cookie to listening to the active session state of our auth provider.
- Attach the `access_token` to all backend API requests via the `Authorization: Bearer <token>` header.

#### [MODIFY] Frontend Ingestion UI (CSV Bootstrapping)
- The backend already has a robust CSV parsing route (`/api/ingestion/parse-spreadsheet` in `backend/routers/ingestion.py`).
- We just need to ensure the frontend exposes this functionality clearly for new users (like your GF) so they can upload their historical transaction CSVs and seamlessly bootstrap their isolated account ledgers.

---

## Verification Plan

### Automated Tests
- Write a unit test script (`scratch/test_multi_user.py`) to verify:
  1. Token validation behavior (valid vs invalid JWTs).
  2. Data scoping: Write transactions for `User A` and verify that `User B` cannot retrieve or compute on them using the backend services.

### Manual Verification
- Deploy changes to Render (sandbox) and Vercel (preview deployment).
- Register two accounts (Yours and GF's).
- Run the dummy UUID migration script for your account in Neon.
- Log into your GF's account, upload a test CSV through the ingestion UI, and verify her portfolio renders correctly while remaining entirely invisible to your account.
