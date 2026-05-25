-- ============================================================
-- Supabase-only Financial Accounting System
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1) Payment completion timestamps and per-record financial columns
ALTER TABLE IF EXISTS service_jobs
    ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS service_expense_amount NUMERIC(14,2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS service_expense_description TEXT,
    ADD COLUMN IF NOT EXISTS service_expense_date DATE,
    ADD COLUMN IF NOT EXISTS service_profit NUMERIC(14,2) DEFAULT 0;

ALTER TABLE IF EXISTS inventory_items
    ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS selling_price NUMERIC(14,2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS cost_price NUMERIC(14,2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS item_expense_amount NUMERIC(14,2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS item_expense_description TEXT,
    ADD COLUMN IF NOT EXISTS item_expense_date DATE,
    ADD COLUMN IF NOT EXISTS product_profit NUMERIC(14,2) DEFAULT 0;

-- Backfill paid_at for already-paid rows
UPDATE service_jobs
SET paid_at = COALESCE(paid_at, NOW())
WHERE UPPER(COALESCE(payment_status, '')) = 'PAID' AND paid_at IS NULL;

UPDATE inventory_items
SET paid_at = COALESCE(paid_at, NOW())
WHERE UPPER(COALESCE(payment_status, '')) = 'PAID' AND paid_at IS NULL;

-- Keep legacy columns aligned where possible
UPDATE service_jobs
SET service_expense_amount = COALESCE(service_expense_amount, expense_amount, 0)
WHERE service_expense_amount IS NULL OR service_expense_amount = 0;

UPDATE inventory_items
SET item_expense_amount = COALESCE(item_expense_amount, expense_amount, 0)
WHERE item_expense_amount IS NULL OR item_expense_amount = 0;

-- Trigger function: set paid_at once when payment_status becomes PAID
CREATE OR REPLACE FUNCTION set_paid_at_once()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF UPPER(COALESCE(NEW.payment_status, '')) = 'PAID' THEN
        NEW.paid_at := COALESCE(NEW.paid_at, NOW());
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_service_jobs_paid_at_once ON service_jobs;
CREATE TRIGGER trg_service_jobs_paid_at_once
BEFORE INSERT OR UPDATE ON service_jobs
FOR EACH ROW EXECUTE FUNCTION set_paid_at_once();

DROP TRIGGER IF EXISTS trg_inventory_items_paid_at_once ON inventory_items;
CREATE TRIGGER trg_inventory_items_paid_at_once
BEFORE INSERT OR UPDATE ON inventory_items
FOR EACH ROW EXECUTE FUNCTION set_paid_at_once();

-- Trigger function: maintain per-record profit columns
CREATE OR REPLACE FUNCTION calc_service_profit()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.service_profit := COALESCE(NEW.paid_amount, 0) - COALESCE(NEW.service_expense_amount, 0);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_service_jobs_profit_calc ON service_jobs;
CREATE TRIGGER trg_service_jobs_profit_calc
BEFORE INSERT OR UPDATE ON service_jobs
FOR EACH ROW EXECUTE FUNCTION calc_service_profit();

CREATE OR REPLACE FUNCTION calc_product_profit()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.product_profit := COALESCE(NEW.selling_price, 0)
        - COALESCE(NEW.cost_price, 0)
        - COALESCE(NEW.item_expense_amount, 0);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_inventory_items_profit_calc ON inventory_items;
CREATE TRIGGER trg_inventory_items_profit_calc
BEFORE INSERT OR UPDATE ON inventory_items
FOR EACH ROW EXECUTE FUNCTION calc_product_profit();

-- 6) Cash flow expenses table
CREATE TABLE IF NOT EXISTS cashflow_expenses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    amount NUMERIC(14,2) NOT NULL CHECK (amount >= 0),
    description TEXT,
    expense_date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_reversed BOOLEAN NOT NULL DEFAULT FALSE,
    reversed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cashflow_expenses_date ON cashflow_expenses(expense_date);
CREATE INDEX IF NOT EXISTS idx_cashflow_expenses_reversed ON cashflow_expenses(is_reversed);

DROP TRIGGER IF EXISTS trg_cashflow_expenses_updated ON cashflow_expenses;
CREATE TRIGGER trg_cashflow_expenses_updated
BEFORE UPDATE ON cashflow_expenses
FOR EACH ROW EXECUTE FUNCTION set_updated_at_generic();

-- 7) Weekly allowance withdrawals table (alter existing if present)
ALTER TABLE IF EXISTS allowance_withdrawals
    ADD COLUMN IF NOT EXISTS week_key TEXT,
    ADD COLUMN IF NOT EXISTS withdrawn_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'NO';

ALTER TABLE IF EXISTS allowance_withdrawals
    ALTER COLUMN id SET DEFAULT uuid_generate_v4()::text;

-- Backfill new columns for legacy rows
UPDATE allowance_withdrawals
SET withdrawn_at = COALESCE(withdrawn_at, NOW())
WHERE withdrawn_at IS NULL;

UPDATE allowance_withdrawals
SET week_key = COALESCE(week_key, TO_CHAR(COALESCE(withdrawn_at, NOW()), 'IYYY-"W"IW'))
WHERE week_key IS NULL;

UPDATE allowance_withdrawals
SET status = COALESCE(NULLIF(status, ''), 'YES')
WHERE status IS NULL OR status = '';

DO $$
BEGIN
    BEGIN
        ALTER TABLE allowance_withdrawals
            ADD CONSTRAINT allowance_withdrawals_status_check
            CHECK (status IN ('YES', 'NO'));
    EXCEPTION WHEN duplicate_object THEN
        NULL;
    END;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS ux_allowance_withdrawals_week_key ON allowance_withdrawals(week_key);
CREATE INDEX IF NOT EXISTS idx_allowance_withdrawals_withdrawn_at ON allowance_withdrawals(withdrawn_at);

-- 8) Historical snapshot tables
CREATE TABLE IF NOT EXISTS weekly_financial_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    week_key TEXT NOT NULL,
    profit_seen_this_week NUMERIC(14,2) NOT NULL DEFAULT 0,
    expenses_of_the_week NUMERIC(14,2) NOT NULL DEFAULT 0,
    net_profit_of_the_week NUMERIC(14,2) NOT NULL DEFAULT 0,
    next_week_allowance NUMERIC(14,2) NOT NULL DEFAULT 0,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (week_key)
);

CREATE TABLE IF NOT EXISTS monthly_financial_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    month_key TEXT NOT NULL,
    profit_seen_this_month NUMERIC(14,2) NOT NULL DEFAULT 0,
    expenses_of_the_month NUMERIC(14,2) NOT NULL DEFAULT 0,
    net_profit_of_the_month NUMERIC(14,2) NOT NULL DEFAULT 0,
    net_profit_left_this_month NUMERIC(14,2) NOT NULL DEFAULT 0,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (month_key)
);
