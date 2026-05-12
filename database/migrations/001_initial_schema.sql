-- ============================================================
-- CRM App - Initial Schema Migration
-- Supabase PostgreSQL
-- ============================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- CLIENTS (from Contacts sheet)
-- ============================================================
CREATE TABLE IF NOT EXISTS clients (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name          TEXT NOT NULL,
    email         TEXT,
    phone         TEXT,
    address       TEXT,
    company       TEXT,
    notes         TEXT,
    source        TEXT DEFAULT 'manual',   -- 'sheet_import' | 'manual'
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_clients_email ON clients(email);
CREATE INDEX idx_clients_name  ON clients(name);

-- ============================================================
-- OPERATIONAL BILLING ROWS (from Services/Billing sheet)
-- ============================================================
CREATE TABLE IF NOT EXISTS operational_billing_rows (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id       UUID REFERENCES clients(id) ON DELETE SET NULL,
    client_name     TEXT,                 -- denormalized for fast reads
    service_name    TEXT NOT NULL,
    description     TEXT,
    quantity        NUMERIC(12,2) DEFAULT 1,
    unit_price      NUMERIC(12,2) NOT NULL,
    total_amount    NUMERIC(12,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    amount_paid     NUMERIC(12,2) DEFAULT 0,
    balance         NUMERIC(12,2) GENERATED ALWAYS AS (quantity * unit_price - amount_paid) STORED,
    status          TEXT DEFAULT 'unpaid',  -- 'unpaid' | 'partial' | 'paid'
    invoice_date    DATE,
    due_date        DATE,
    payment_date    DATE,
    notes           TEXT,
    source          TEXT DEFAULT 'manual',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_billing_client_id  ON operational_billing_rows(client_id);
CREATE INDEX idx_billing_status     ON operational_billing_rows(status);
CREATE INDEX idx_billing_date       ON operational_billing_rows(invoice_date);

-- ============================================================
-- OPERATIONAL STOCK ROWS (from Stock/Inventory sheet)
-- ============================================================
CREATE TABLE IF NOT EXISTS operational_stock_rows (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    item_name       TEXT NOT NULL,
    sku             TEXT UNIQUE,
    category        TEXT,
    description     TEXT,
    quantity        NUMERIC(12,2) DEFAULT 0,
    unit            TEXT DEFAULT 'pcs',
    unit_cost       NUMERIC(12,2) DEFAULT 0,
    unit_price      NUMERIC(12,2) DEFAULT 0,
    reorder_level   NUMERIC(12,2) DEFAULT 0,
    supplier        TEXT,
    location        TEXT,
    is_active       BOOLEAN DEFAULT TRUE,
    source          TEXT DEFAULT 'manual',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_stock_item_name ON operational_stock_rows(item_name);
CREATE INDEX idx_stock_category  ON operational_stock_rows(category);

-- ============================================================
-- MANUAL EXPENSES (from Cash Flow sheet)
-- ============================================================
CREATE TABLE IF NOT EXISTS manual_expenses (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    category        TEXT NOT NULL,
    description     TEXT,
    amount          NUMERIC(12,2) NOT NULL,
    expense_date    DATE NOT NULL,
    paid_by         TEXT,
    receipt_ref     TEXT,
    notes           TEXT,
    source          TEXT DEFAULT 'manual',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_expenses_category ON manual_expenses(category);
CREATE INDEX idx_expenses_date     ON manual_expenses(expense_date);

-- ============================================================
-- ALLOWANCES (staff allowances tracking)
-- ============================================================
CREATE TABLE IF NOT EXISTS allowances (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    staff_name      TEXT NOT NULL,
    allowance_type  TEXT NOT NULL,   -- 'transport' | 'meal' | 'airtime' | 'other'
    amount          NUMERIC(12,2) NOT NULL,
    allowance_date  DATE NOT NULL,
    approved_by     TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_allowances_staff ON allowances(staff_name);
CREATE INDEX idx_allowances_date  ON allowances(allowance_date);

-- ============================================================
-- PAYMENTS (applied payments for debtors)
-- ============================================================
CREATE TABLE IF NOT EXISTS payments (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    billing_row_id  UUID REFERENCES operational_billing_rows(id) ON DELETE CASCADE,
    client_id       UUID REFERENCES clients(id) ON DELETE SET NULL,
    amount          NUMERIC(12,2) NOT NULL,
    payment_method  TEXT DEFAULT 'cash',   -- 'cash' | 'bank' | 'mobile_money' | 'other'
    reference_no    TEXT,
    payment_date    DATE NOT NULL DEFAULT CURRENT_DATE,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_payments_billing_row ON payments(billing_row_id);
CREATE INDEX idx_payments_client      ON payments(client_id);
CREATE INDEX idx_payments_date        ON payments(payment_date);

-- ============================================================
-- CASH FLOW SUMMARY (precomputed, refreshed async)
-- ============================================================
CREATE TABLE IF NOT EXISTS cash_flow_summary (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    period_month    TEXT NOT NULL,   -- 'YYYY-MM'
    total_revenue   NUMERIC(12,2) DEFAULT 0,
    total_expenses  NUMERIC(12,2) DEFAULT 0,
    total_allowances NUMERIC(12,2) DEFAULT 0,
    gross_profit    NUMERIC(12,2) GENERATED ALWAYS AS (total_revenue - total_expenses - total_allowances) STORED,
    computed_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(period_month)
);

-- ============================================================
-- SETTINGS
-- ============================================================
CREATE TABLE IF NOT EXISTS settings (
    key     TEXT PRIMARY KEY,
    value   TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO settings (key, value) VALUES
    ('business_name', 'My Business'),
    ('currency', 'GHS'),
    ('google_sheet_id', ''),
    ('last_sync_at', NULL),
    ('last_workspace_refresh', NULL)
ON CONFLICT (key) DO NOTHING;

-- ============================================================
-- updated_at trigger helper
-- ============================================================
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_clients_updated           BEFORE UPDATE ON clients           FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_billing_updated           BEFORE UPDATE ON operational_billing_rows FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_stock_updated             BEFORE UPDATE ON operational_stock_rows   FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_expenses_updated          BEFORE UPDATE ON manual_expenses          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_allowances_updated        BEFORE UPDATE ON allowances               FOR EACH ROW EXECUTE FUNCTION set_updated_at();
