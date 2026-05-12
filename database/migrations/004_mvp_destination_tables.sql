-- ============================================================
-- MVP Destination Tables (non-destructive)
-- Creates target tables for read-only migration from legacy project.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users copied from legacy auth_users
CREATE TABLE IF NOT EXISTS users (
    id                 TEXT PRIMARY KEY,
    email              TEXT,
    phone              TEXT,
    full_name          TEXT,
    role               TEXT DEFAULT 'user',
    is_active          BOOLEAN DEFAULT TRUE,
    source_created_at  TIMESTAMPTZ,
    source_updated_at  TIMESTAMPTZ,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Clients copied from legacy clients
CREATE TABLE IF NOT EXISTS clients (
    id                 TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    email              TEXT,
    phone              TEXT,
    address            TEXT,
    company            TEXT,
    notes              TEXT,
    source_created_at  TIMESTAMPTZ,
    source_updated_at  TIMESTAMPTZ,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mvp_clients_name ON clients(name);
CREATE INDEX IF NOT EXISTS idx_mvp_clients_email ON clients(email);

-- Manual expenses copied from legacy manual_expenses
CREATE TABLE IF NOT EXISTS manual_expenses (
    id                 TEXT PRIMARY KEY,
    category           TEXT,
    description        TEXT,
    amount             NUMERIC(12,2) DEFAULT 0,
    expense_date       DATE,
    paid_by            TEXT,
    receipt_ref        TEXT,
    notes              TEXT,
    source_created_at  TIMESTAMPTZ,
    source_updated_at  TIMESTAMPTZ,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mvp_manual_expenses_date ON manual_expenses(expense_date);

-- Inventory copied from legacy operational_stock_rows
CREATE TABLE IF NOT EXISTS inventory_items (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    legacy_source_id   TEXT UNIQUE,
    item_name          TEXT NOT NULL,
    sku                TEXT,
    category           TEXT,
    description        TEXT,
    quantity           NUMERIC(12,2) DEFAULT 0,
    unit               TEXT DEFAULT 'pcs',
    cost_price         NUMERIC(12,2) DEFAULT 0,
    selling_price      NUMERIC(12,2) DEFAULT 0,
    expense_amount     NUMERIC(12,2) DEFAULT 0,
    product_profit     NUMERIC(12,2) DEFAULT 0,
    payment_status     TEXT,
    paid_date          DATE,
    is_return          BOOLEAN DEFAULT FALSE,
    source_created_at  TIMESTAMPTZ,
    source_updated_at  TIMESTAMPTZ,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inventory_item_name ON inventory_items(item_name);
CREATE INDEX IF NOT EXISTS idx_inventory_sku ON inventory_items(sku);

-- Service jobs copied from legacy operational_billing_rows
CREATE TABLE IF NOT EXISTS service_jobs (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    legacy_source_id   TEXT UNIQUE,
    client_id          TEXT,
    client_name        TEXT,
    service_name       TEXT NOT NULL,
    description        TEXT,
    quantity           NUMERIC(12,2) DEFAULT 1,
    amount_charged     NUMERIC(12,2) DEFAULT 0,
    expense_amount     NUMERIC(12,2) DEFAULT 0,
    calculated_profit  NUMERIC(12,2) DEFAULT 0,
    payment_status     TEXT,
    paid_amount        NUMERIC(12,2) DEFAULT 0,
    paid_date          DATE,
    service_date       DATE,
    due_date           DATE,
    is_return          BOOLEAN DEFAULT FALSE,
    return_reference   TEXT,
    notes              TEXT,
    source_created_at  TIMESTAMPTZ,
    source_updated_at  TIMESTAMPTZ,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_service_jobs_client ON service_jobs(client_id);
CREATE INDEX IF NOT EXISTS idx_service_jobs_status ON service_jobs(payment_status);
CREATE INDEX IF NOT EXISTS idx_service_jobs_paid_date ON service_jobs(paid_date);

-- Allowance withdrawals copied from legacy allowance_withdrawals
CREATE TABLE IF NOT EXISTS allowance_withdrawals (
    id                 TEXT PRIMARY KEY,
    withdrawn_by       TEXT,
    amount             NUMERIC(12,2) NOT NULL,
    withdrawal_date    DATE NOT NULL,
    notes              TEXT,
    source_created_at  TIMESTAMPTZ,
    source_updated_at  TIMESTAMPTZ,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_allowance_withdrawals_date ON allowance_withdrawals(withdrawal_date);

-- Cashflow summary copied from legacy cashflow_summary
CREATE TABLE IF NOT EXISTS cashflow_summary (
    id                     TEXT PRIMARY KEY,
    period_key             TEXT,
    weekly_paid_profits    NUMERIC(12,2) DEFAULT 0,
    weekly_expenses        NUMERIC(12,2) DEFAULT 0,
    weekly_net_profit      NUMERIC(12,2) DEFAULT 0,
    next_week_allowance    NUMERIC(12,2) DEFAULT 0,
    monthly_net_profit     NUMERIC(12,2) DEFAULT 0,
    allowances_withdrawn   NUMERIC(12,2) DEFAULT 0,
    monthly_net_profit_left NUMERIC(12,2) DEFAULT 0,
    source_created_at      TIMESTAMPTZ,
    source_updated_at      TIMESTAMPTZ,
    created_at             TIMESTAMPTZ DEFAULT NOW(),
    updated_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cashflow_summary_period ON cashflow_summary(period_key);

-- App settings copied from legacy app_config
CREATE TABLE IF NOT EXISTS app_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    description TEXT,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Trigger for updated_at
CREATE OR REPLACE FUNCTION set_updated_at_generic()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_users_updated ON users;
CREATE TRIGGER trg_users_updated BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION set_updated_at_generic();

DROP TRIGGER IF EXISTS trg_inventory_items_updated ON inventory_items;
CREATE TRIGGER trg_inventory_items_updated BEFORE UPDATE ON inventory_items FOR EACH ROW EXECUTE FUNCTION set_updated_at_generic();

DROP TRIGGER IF EXISTS trg_service_jobs_updated ON service_jobs;
CREATE TRIGGER trg_service_jobs_updated BEFORE UPDATE ON service_jobs FOR EACH ROW EXECUTE FUNCTION set_updated_at_generic();

DROP TRIGGER IF EXISTS trg_allowance_withdrawals_updated ON allowance_withdrawals;
CREATE TRIGGER trg_allowance_withdrawals_updated BEFORE UPDATE ON allowance_withdrawals FOR EACH ROW EXECUTE FUNCTION set_updated_at_generic();

DROP TRIGGER IF EXISTS trg_cashflow_summary_updated ON cashflow_summary;
CREATE TRIGGER trg_cashflow_summary_updated BEFORE UPDATE ON cashflow_summary FOR EACH ROW EXECUTE FUNCTION set_updated_at_generic();

DROP TRIGGER IF EXISTS trg_app_settings_updated ON app_settings;
CREATE TRIGGER trg_app_settings_updated BEFORE UPDATE ON app_settings FOR EACH ROW EXECUTE FUNCTION set_updated_at_generic();
