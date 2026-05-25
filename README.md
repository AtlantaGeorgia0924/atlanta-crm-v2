# CRM App — Clean Architecture

A production-ready CRM built with **React + Vite**, **FastAPI**, and **Supabase PostgreSQL**.

---

## Architecture

```
crm-app/
├── frontend/          # React + Vite → deployed to Vercel
├── backend/           # FastAPI      → deployed to Render
├── database/
│   └── migrations/    # SQL run once in Supabase SQL editor
└── scripts/
    └── import_sheets.py   # One-time Google Sheets import
```

**Rule:** Supabase is the single source of truth.  
Google Sheets is only written to when you click "Sync to Sheets".

---

## Modules

| Module | Route |
|--------|-------|
| Authentication | `/login` |
| Dashboard | `/dashboard` |
| Clients / Contacts | `/clients` |
| Service / Billing | `/billing` |
| Inventory | `/inventory` |
| Debtors + Apply Payment | `/debtors` |
| Manual Expenses | `/expenses` |
| Allowance Tracking | `/allowances` |
| Cash Flow & Profit | `/cashflow` |
| Settings / System Status | `/settings` |
| Refresh Workspace | Sidebar button |
| Sync to Google Sheets | Sidebar button |

---

## Step 1 — Create a new Supabase project

1. Go to [supabase.com](https://supabase.com) → **New Project**.
2. Copy the **Project URL** and both API keys (anon + service_role).
3. Keep your **existing** Supabase project completely untouched.

---

## Step 2 — Run database migrations

Open your new project's **SQL Editor** and run every file in `database/migrations`
in numeric order. The current deterministic sequence is:

```
database/migrations/001_initial_schema.sql
database/migrations/002_rls_policies.sql
database/migrations/003_functions_and_views.sql
database/migrations/004_mvp_destination_tables.sql
database/migrations/005_add_imei_columns.sql
database/migrations/006_expand_cashflow_numeric_precision.sql
...
database/migrations/022_service_ownership_and_activity_tracking.sql
```

---

## Step 3 — Import from Google Sheets (one-time)

### Prerequisites

```bash
source backend/.venv/bin/activate
pip install gspread google-auth supabase python-dotenv
```

### Service Account Setup

1. Create a Google Cloud project.
2. Enable the **Google Sheets API**.
3. Create a **Service Account** → download the JSON key → save as `scripts/service_account.json`.
4. Share your Google Sheet with the service account email (Viewer permission).

### Configure

```bash
cp backend/.env.example scripts/.env
# Edit scripts/.env with your NEW Supabase URL, service role key, and sheet ID
```

### Run

```bash
backend/.venv/bin/python scripts/import_sheets.py
```

The script maps the following sheet tabs (rename to match your sheet):

| Sheet Tab | → Supabase Table |
|-----------|-----------------|
| `Contacts` | `clients` |
| `Billing` | `operational_billing_rows` |
| `Inventory` | `operational_stock_rows` |
| `Cash Flow` | `manual_expenses` |

**Column header mapping is flexible** — the script tries common header variants. Edit `map_*` functions in `import_sheets.py` if your headers differ.

---

## Step 4 — Run the backend locally

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Fill in SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_ANON_KEY,
# GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEET_ID_STOCKS,
# GOOGLE_SHEET_ID_SERVICES, and REDIS_URL.

uvicorn app.main:app --reload --port 8000
```

API docs available at: http://localhost:8000/docs

---

## Step 5 — Run the frontend locally

```bash
cd frontend
npm install

cp .env.example .env
# Fill in VITE_API_BASE_URL=/api
# Fill in VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY

npm run dev
```

Frontend: http://localhost:5173

---

## Step 6 — Deploy to Render (backend)

1. Push to GitHub.
2. Go to [render.com](https://render.com) → **New Web Service** → connect your repo.
3. Set **Root Directory** to `backend`.
4. Use the `render.yaml` for automatic config.
5. Add environment variables in Render dashboard.

---

## Step 7 — Deploy to Vercel (frontend)

1. Go to [vercel.com](https://vercel.com) → **New Project** → connect your repo.
2. Set **Root Directory** to `frontend`.
3. Add environment variables:
   - `VITE_API_BASE_URL` = `/api` when using the included Vercel rewrite, or your Render backend URL (e.g. `https://crm-api.onrender.com`)
   - `VITE_SUPABASE_URL`
   - `VITE_SUPABASE_ANON_KEY`

---

## Performance Notes

| Requirement | Implementation |
|-------------|----------------|
| Apply Payment < 1s | 3 direct Supabase calls, no Sheets |
| Refresh Workspace | Updates timestamp; client re-fetches |
| Cash Flow reads | Precomputed `cash_flow_summary` table |
| Heavy recalculations | Async background task via `BackgroundTasks` |
| No Sheets on read | Sheets only called from `/sync/to-sheets` |

---

## Production Readiness Verification

Run the full local gate before deployment:

```bash
npm run verify-system
```

This validates frontend build/lint, backend startup and health, migration
numbering, environment formats, Redis, Supabase, Google Sheets access, and
critical route presence. It never prints secret values.

---

## Environment Variables Summary

### Backend (`backend/.env`)
```
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_ANON_KEY=
GOOGLE_SERVICE_ACCOUNT_JSON=./service_account.json
GOOGLE_SHEET_ID=
GOOGLE_SHEET_ID_STOCKS=
GOOGLE_SHEET_ID_SERVICES=
REDIS_URL=
ALLOWED_ORIGINS=http://localhost:5173,https://your-app.vercel.app
ENV=development
```

### Frontend (`frontend/.env`)
```
VITE_API_BASE_URL=/api
VITE_API_URL=/api
VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
```
