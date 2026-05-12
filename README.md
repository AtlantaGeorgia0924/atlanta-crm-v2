# atlanta-crm-v2

Clean-architecture foundation for a new CRM rebuild that keeps the legacy system untouched.

## Stack

- Frontend: React + Vite
- Backend: FastAPI
- Database: Supabase PostgreSQL
- Backup: Google Sheets (manual sync only)
- Hosting targets:
  - Frontend: Vercel
  - Backend: Render

## Architecture Rules

- Supabase is the single source of truth.
- Normal application reads and writes go directly to Supabase.
- Google Sheets is only used for:
  - the initial import
  - a user-initiated **Sync to Google Sheets**
- Cash flow reads from precomputed summary tables.
- Heavy recalculations run asynchronously.

## Initial Import Mapping

- `Services/Billing` → `operational_billing_rows`
- `Stock/Inventory` → `operational_stock_rows`
- `Cash Flow` → `manual_expenses` and related tables
- `Contacts` → `clients`

## Included Foundation Modules

1. Authentication
2. Inventory Management
3. Service Management
4. Debtors and Apply Payment
5. Clients / Contacts
6. Import Contacts from Sheet
7. Cash Flow and Profit Calculation
8. Manual Expenses
9. Allowance Tracking
10. Dashboard
11. Refresh Workspace
12. Sync to Google Sheets
13. Settings / System Status

## Local Development

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Backend

```bash
cd backend
python -m pip install -e .[dev]
uvicorn app.main:app --reload
```

### Backend tests

```bash
cd backend
pytest
```
