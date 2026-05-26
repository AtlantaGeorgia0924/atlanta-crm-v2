BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE OR REPLACE FUNCTION normalize_phone_digits(input TEXT)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT NULLIF(regexp_replace(COALESCE(input, ''), '\\D', '', 'g'), '');
$$;

CREATE OR REPLACE FUNCTION set_updated_at_generic()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF to_regclass('public.service_jobs') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE service_jobs ALTER COLUMN amount_charged TYPE NUMERIC(18,2) USING amount_charged::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE service_jobs ALTER COLUMN expense_amount TYPE NUMERIC(18,2) USING expense_amount::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE service_jobs ALTER COLUMN calculated_profit TYPE NUMERIC(18,2) USING calculated_profit::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE service_jobs ALTER COLUMN paid_amount TYPE NUMERIC(18,2) USING paid_amount::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ';
        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS deleted_by TEXT';
        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS restored_at TIMESTAMPTZ';
        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS restored_by TEXT';
        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS client_uuid UUID';
        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS invoice_reference TEXT';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'service_expense_amount'
    ) THEN
        EXECUTE 'ALTER TABLE service_jobs ALTER COLUMN service_expense_amount TYPE NUMERIC(18,2) USING service_expense_amount::NUMERIC(18,2)';
    END IF;

    IF to_regclass('public.inventory_items') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE inventory_items ALTER COLUMN cost_price TYPE NUMERIC(18,2) USING cost_price::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE inventory_items ALTER COLUMN selling_price TYPE NUMERIC(18,2) USING selling_price::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE inventory_items ALTER COLUMN expense_amount TYPE NUMERIC(18,2) USING expense_amount::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE inventory_items ALTER COLUMN product_profit TYPE NUMERIC(18,2) USING product_profit::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ';
        EXECUTE 'ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS deleted_by TEXT';
        EXECUTE 'ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS restored_at TIMESTAMPTZ';
        EXECUTE 'ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS restored_by TEXT';
    END IF;

    IF to_regclass('public.clients') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE clients ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ';
        EXECUTE 'ALTER TABLE clients ADD COLUMN IF NOT EXISTS deleted_by TEXT';
        EXECUTE 'ALTER TABLE clients ADD COLUMN IF NOT EXISTS restored_at TIMESTAMPTZ';
        EXECUTE 'ALTER TABLE clients ADD COLUMN IF NOT EXISTS restored_by TEXT';
    END IF;

    IF to_regclass('public.payments') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE payments ALTER COLUMN payment_amount TYPE NUMERIC(18,2) USING payment_amount::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE payments ALTER COLUMN amount TYPE NUMERIC(18,2) USING amount::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE payments ALTER COLUMN previous_balance TYPE NUMERIC(18,2) USING previous_balance::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE payments ALTER COLUMN new_balance TYPE NUMERIC(18,2) USING new_balance::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE payments ALTER COLUMN previous_paid_amount TYPE NUMERIC(18,2) USING previous_paid_amount::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE payments ALTER COLUMN new_paid_amount TYPE NUMERIC(18,2) USING new_paid_amount::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()';
    END IF;

    IF to_regclass('public.inventory_sales') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE inventory_sales ALTER COLUMN amount_charged TYPE NUMERIC(18,2) USING amount_charged::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE inventory_sales ALTER COLUMN paid_amount TYPE NUMERIC(18,2) USING paid_amount::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE inventory_sales ALTER COLUMN balance TYPE NUMERIC(18,2) USING balance::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE inventory_sales ALTER COLUMN total_profit TYPE NUMERIC(18,2) USING total_profit::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE inventory_sales ADD COLUMN IF NOT EXISTS client_uuid UUID';
        EXECUTE 'ALTER TABLE inventory_sales ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ';
        EXECUTE 'ALTER TABLE inventory_sales ADD COLUMN IF NOT EXISTS deleted_by TEXT';
        EXECUTE 'ALTER TABLE inventory_sales ADD COLUMN IF NOT EXISTS restored_at TIMESTAMPTZ';
        EXECUTE 'ALTER TABLE inventory_sales ADD COLUMN IF NOT EXISTS restored_by TEXT';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'inventory_sales' AND column_name = 'discount_amount'
    ) THEN
        EXECUTE 'ALTER TABLE inventory_sales ALTER COLUMN discount_amount TYPE NUMERIC(18,2) USING discount_amount::NUMERIC(18,2)';
    END IF;

    IF to_regclass('public.inventory_sale_items') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE inventory_sale_items ALTER COLUMN unit_price TYPE NUMERIC(18,2) USING unit_price::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE inventory_sale_items ALTER COLUMN unit_cost TYPE NUMERIC(18,2) USING unit_cost::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE inventory_sale_items ALTER COLUMN amount_charged TYPE NUMERIC(18,2) USING amount_charged::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE inventory_sale_items ALTER COLUMN profit TYPE NUMERIC(18,2) USING profit::NUMERIC(18,2)';
        EXECUTE 'ALTER TABLE inventory_sale_items ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()';
        EXECUTE 'ALTER TABLE inventory_sale_items ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ';
        EXECUTE 'ALTER TABLE inventory_sale_items ADD COLUMN IF NOT EXISTS deleted_by TEXT';
        EXECUTE 'ALTER TABLE inventory_sale_items ADD COLUMN IF NOT EXISTS restored_at TIMESTAMPTZ';
        EXECUTE 'ALTER TABLE inventory_sale_items ADD COLUMN IF NOT EXISTS restored_by TEXT';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('public.service_jobs') IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND constraint_name = 'fk_service_jobs_client_uuid'
    ) THEN
        EXECUTE 'ALTER TABLE service_jobs ADD CONSTRAINT fk_service_jobs_client_uuid FOREIGN KEY (client_uuid) REFERENCES clients(id) ON DELETE SET NULL';
    END IF;

    IF to_regclass('public.inventory_sales') IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public' AND table_name = 'inventory_sales' AND constraint_name = 'fk_inventory_sales_client_uuid'
    ) THEN
        EXECUTE 'ALTER TABLE inventory_sales ADD CONSTRAINT fk_inventory_sales_client_uuid FOREIGN KEY (client_uuid) REFERENCES clients(id) ON DELETE SET NULL';
    END IF;
END $$;

UPDATE service_jobs sj
SET client_uuid = c.id
FROM clients c
WHERE sj.client_uuid IS NULL
  AND sj.client_id IS NOT NULL
  AND sj.client_id ~* '^[0-9a-f-]{36}$'
  AND c.id = sj.client_id::uuid;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'phone_number'
    ) THEN
        EXECUTE $sql$
            UPDATE service_jobs sj
            SET client_uuid = c.id
            FROM clients c
            WHERE sj.client_uuid IS NULL
              AND normalize_phone_digits(sj.phone_number) IS NOT NULL
              AND normalize_phone_digits(c.phone) = normalize_phone_digits(sj.phone_number)
        $sql$;
    END IF;
END $$;

UPDATE service_jobs sj
SET client_uuid = c.id
FROM clients c
WHERE sj.client_uuid IS NULL
  AND NULLIF(BTRIM(COALESCE(sj.client_name, '')), '') IS NOT NULL
  AND LOWER(BTRIM(c.name)) = LOWER(BTRIM(sj.client_name));

UPDATE inventory_sales s
SET client_uuid = c.id
FROM clients c
WHERE s.client_uuid IS NULL
  AND s.client_id IS NOT NULL
  AND s.client_id ~* '^[0-9a-f-]{36}$'
  AND c.id = s.client_id::uuid;

UPDATE inventory_sales s
SET client_uuid = c.id
FROM clients c
WHERE s.client_uuid IS NULL
  AND normalize_phone_digits(s.client_phone) IS NOT NULL
  AND normalize_phone_digits(c.phone) = normalize_phone_digits(s.client_phone);

UPDATE inventory_sales s
SET client_uuid = c.id
FROM clients c
WHERE s.client_uuid IS NULL
  AND NULLIF(BTRIM(COALESCE(s.client_name, '')), '') IS NOT NULL
  AND LOWER(BTRIM(c.name)) = LOWER(BTRIM(s.client_name));

CREATE TABLE IF NOT EXISTS service_payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_job_id UUID NOT NULL REFERENCES service_jobs(id) ON DELETE RESTRICT,
    client_id UUID REFERENCES clients(id) ON DELETE SET NULL,
    source_payment_id UUID UNIQUE,
    entry_type TEXT NOT NULL CHECK (entry_type IN ('PAYMENT', 'REVERSAL', 'MIGRATION')),
    reference_no TEXT NOT NULL,
    amount NUMERIC(18,2) NOT NULL CHECK (amount <> 0),
    payment_method TEXT,
    note TEXT,
    previous_paid_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    new_paid_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    previous_balance NUMERIC(18,2) NOT NULL DEFAULT 0,
    new_balance NUMERIC(18,2) NOT NULL DEFAULT 0,
    previous_status TEXT,
    new_status TEXT,
    recorded_by TEXT,
    recorded_by_name TEXT,
    payment_date DATE,
    payment_time TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sale_payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sale_id UUID NOT NULL REFERENCES inventory_sales(id) ON DELETE RESTRICT,
    client_id UUID REFERENCES clients(id) ON DELETE SET NULL,
    entry_type TEXT NOT NULL CHECK (entry_type IN ('PAYMENT', 'REVERSAL', 'MIGRATION')),
    reference_no TEXT NOT NULL,
    amount NUMERIC(18,2) NOT NULL CHECK (amount <> 0),
    payment_method TEXT,
    note TEXT,
    previous_paid_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    new_paid_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    previous_balance NUMERIC(18,2) NOT NULL DEFAULT 0,
    new_balance NUMERIC(18,2) NOT NULL DEFAULT 0,
    previous_status TEXT,
    new_status TEXT,
    recorded_by TEXT,
    recorded_by_name TEXT,
    payment_date DATE,
    payment_time TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_table TEXT,
    source_row_id TEXT,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    actor_id TEXT,
    actor_name TEXT,
    actor_role TEXT,
    before_value JSONB,
    after_value JSONB,
    detail JSONB NOT NULL DEFAULT '{}'::JSONB,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inventory_carts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID REFERENCES clients(id) ON DELETE SET NULL,
    client_name TEXT,
    client_phone TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CHECKED_OUT', 'ABANDONED', 'CANCELLED')),
    subtotal NUMERIC(18,2) NOT NULL DEFAULT 0,
    discount_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    total_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    total_paid NUMERIC(18,2) NOT NULL DEFAULT 0,
    total_balance NUMERIC(18,2) NOT NULL DEFAULT 0,
    linked_sale_id UUID REFERENCES inventory_sales(id) ON DELETE SET NULL,
    created_by TEXT,
    checked_out_by TEXT,
    checked_out_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS inventory_cart_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cart_id UUID NOT NULL REFERENCES inventory_carts(id) ON DELETE CASCADE,
    inventory_item_id UUID NOT NULL REFERENCES inventory_items(id) ON DELETE RESTRICT,
    quantity NUMERIC(12,2) NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(18,2) NOT NULL DEFAULT 0,
    line_total NUMERIC(18,2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

DROP TRIGGER IF EXISTS trg_service_payments_updated ON service_payments;
CREATE TRIGGER trg_service_payments_updated BEFORE UPDATE ON service_payments FOR EACH ROW EXECUTE FUNCTION set_updated_at_generic();

DROP TRIGGER IF EXISTS trg_sale_payments_updated ON sale_payments;
CREATE TRIGGER trg_sale_payments_updated BEFORE UPDATE ON sale_payments FOR EACH ROW EXECUTE FUNCTION set_updated_at_generic();

DROP TRIGGER IF EXISTS trg_audit_logs_updated ON audit_logs;
CREATE TRIGGER trg_audit_logs_updated BEFORE UPDATE ON audit_logs FOR EACH ROW EXECUTE FUNCTION set_updated_at_generic();

DROP TRIGGER IF EXISTS trg_inventory_sales_updated_phase2 ON inventory_sales;
CREATE TRIGGER trg_inventory_sales_updated_phase2 BEFORE UPDATE ON inventory_sales FOR EACH ROW EXECUTE FUNCTION set_updated_at_generic();

DROP TRIGGER IF EXISTS trg_inventory_sale_items_updated_phase2 ON inventory_sale_items;
CREATE TRIGGER trg_inventory_sale_items_updated_phase2 BEFORE UPDATE ON inventory_sale_items FOR EACH ROW EXECUTE FUNCTION set_updated_at_generic();

DROP TRIGGER IF EXISTS trg_inventory_carts_updated ON inventory_carts;
CREATE TRIGGER trg_inventory_carts_updated BEFORE UPDATE ON inventory_carts FOR EACH ROW EXECUTE FUNCTION set_updated_at_generic();

DROP TRIGGER IF EXISTS trg_inventory_cart_items_updated ON inventory_cart_items;
CREATE TRIGGER trg_inventory_cart_items_updated BEFORE UPDATE ON inventory_cart_items FOR EACH ROW EXECUTE FUNCTION set_updated_at_generic();

INSERT INTO service_payments (
    service_job_id,
    client_id,
    source_payment_id,
    entry_type,
    reference_no,
    amount,
    payment_method,
    note,
    previous_paid_amount,
    new_paid_amount,
    previous_balance,
    new_balance,
    previous_status,
    new_status,
    recorded_by,
    recorded_by_name,
    payment_date,
    payment_time,
    created_at,
    updated_at,
    metadata
)
SELECT
    COALESCE(p.service_job_id, p.billing_row_id),
    COALESCE(sj.client_uuid, NULL),
    p.id,
    CASE
        WHEN COALESCE(p.payment_amount, p.amount, 0) < 0 OR COALESCE(p.is_reversed, FALSE) THEN 'REVERSAL'
        ELSE 'PAYMENT'
    END,
    COALESCE(NULLIF(BTRIM(p.reference_no), ''), CONCAT('MIG-PAY-', SUBSTRING(MD5(p.id::TEXT), 1, 12))),
    COALESCE(p.payment_amount, p.amount),
    NULLIF(BTRIM(p.payment_method), ''),
    COALESCE(NULLIF(BTRIM(p.payment_note), ''), NULLIF(BTRIM(p.notes), ''), NULLIF(BTRIM(p.reversal_reason), '')),
    COALESCE(p.previous_paid_amount, 0),
    COALESCE(p.new_paid_amount, COALESCE(p.payment_amount, p.amount, 0)),
    COALESCE(p.previous_balance, GREATEST(COALESCE(sj.amount_charged, 0) - COALESCE(p.previous_paid_amount, 0), 0)),
    COALESCE(p.new_balance, GREATEST(COALESCE(sj.amount_charged, 0) - COALESCE(p.new_paid_amount, COALESCE(p.payment_amount, p.amount, 0)), 0)),
    p.previous_status,
    p.new_status,
    COALESCE(p.performed_by, p.applied_by::TEXT),
    p.applied_by_name,
    p.payment_date,
    COALESCE(p.created_at, NOW()),
    COALESCE(p.created_at, NOW()),
    COALESCE(p.updated_at, p.created_at, NOW()),
    jsonb_build_object(
        'legacy_table', 'payments',
        'legacy_billing_row_id', p.billing_row_id,
        'legacy_client_name', p.client_name,
        'legacy_client_phone', p.client_phone,
        'legacy_is_reversed', COALESCE(p.is_reversed, FALSE)
    )
FROM payments p
JOIN service_jobs sj ON sj.id = COALESCE(p.service_job_id, p.billing_row_id)
WHERE COALESCE(p.payment_amount, p.amount, 0) <> 0
ON CONFLICT (source_payment_id) DO NOTHING;

INSERT INTO sale_payments (
    sale_id,
    client_id,
    entry_type,
    reference_no,
    amount,
    payment_method,
    note,
    previous_paid_amount,
    new_paid_amount,
    previous_balance,
    new_balance,
    previous_status,
    new_status,
    recorded_by,
    payment_date,
    payment_time,
    created_at,
    updated_at,
    metadata
)
SELECT
    s.id,
    s.client_uuid,
    'MIGRATION',
    COALESCE(NULLIF(BTRIM(s.invoice_reference), ''), CONCAT('MIG-SALE-', SUBSTRING(MD5(s.id::TEXT), 1, 12))),
    s.paid_amount,
    NULLIF(BTRIM(s.payment_method), ''),
    NULLIF(BTRIM(s.notes), ''),
    0,
    s.paid_amount,
    COALESCE(s.amount_charged, 0),
    COALESCE(s.balance, GREATEST(COALESCE(s.amount_charged, 0) - COALESCE(s.paid_amount, 0), 0)),
    'UNPAID',
    COALESCE(NULLIF(BTRIM(s.payment_status), ''), CASE WHEN COALESCE(s.paid_amount, 0) > 0 THEN 'PART PAYMENT' ELSE 'UNPAID' END),
    s.sold_by,
    COALESCE(s.sold_at::DATE, CURRENT_DATE),
    COALESCE(s.sold_at, s.created_at, NOW()),
    COALESCE(s.created_at, NOW()),
    COALESCE(s.updated_at, s.created_at, NOW()),
    jsonb_build_object('legacy_table', 'inventory_sales', 'migration_source', 'aggregate_paid_amount')
FROM inventory_sales s
WHERE COALESCE(s.paid_amount, 0) <> 0
  AND NOT EXISTS (
      SELECT 1
      FROM sale_payments sp
      WHERE sp.sale_id = s.id
        AND sp.entry_type = 'MIGRATION'
  );

INSERT INTO audit_logs (
    source_table,
    source_row_id,
    action,
    entity_type,
    entity_id,
    actor_id,
    before_value,
    after_value,
    detail,
    occurred_at,
    created_at,
    updated_at
)
SELECT
    'crm_audit_log',
    a.id::TEXT,
    a.action,
    a.entity_type,
    a.entity_id,
    a.performed_by,
    a.before_value,
    a.after_value,
    COALESCE(a.detail, '{}'::JSONB),
    COALESCE(a.created_at, NOW()),
    COALESCE(a.created_at, NOW()),
    COALESCE(a.created_at, NOW())
FROM crm_audit_log a
WHERE NOT EXISTS (
    SELECT 1
    FROM audit_logs al
    WHERE al.source_table = 'crm_audit_log'
      AND al.source_row_id = a.id::TEXT
);

INSERT INTO audit_logs (
    source_table,
    source_row_id,
    action,
    entity_type,
    entity_id,
    actor_id,
    detail,
    occurred_at,
    created_at,
    updated_at
)
SELECT
    'cashflow_audit_log',
    a.id::TEXT,
    a.action,
    'cashflow',
    a.entity_id,
    a.performed_by,
    COALESCE(a.detail, '{}'::JSONB),
    COALESCE(a.created_at, NOW()),
    COALESCE(a.created_at, NOW()),
    COALESCE(a.created_at, NOW())
FROM cashflow_audit_log a
WHERE NOT EXISTS (
    SELECT 1
    FROM audit_logs al
    WHERE al.source_table = 'cashflow_audit_log'
      AND al.source_row_id = a.id::TEXT
);

CREATE INDEX IF NOT EXISTS idx_service_payments_job_time ON service_payments(service_job_id, payment_time DESC);
CREATE INDEX IF NOT EXISTS idx_service_payments_client_time ON service_payments(client_id, payment_time DESC);
CREATE INDEX IF NOT EXISTS idx_service_payments_reference ON service_payments(reference_no);

CREATE INDEX IF NOT EXISTS idx_sale_payments_sale_time ON sale_payments(sale_id, payment_time DESC);
CREATE INDEX IF NOT EXISTS idx_sale_payments_client_time ON sale_payments(client_id, payment_time DESC);
CREATE INDEX IF NOT EXISTS idx_sale_payments_reference ON sale_payments(reference_no);

CREATE INDEX IF NOT EXISTS idx_audit_logs_entity_time ON audit_logs(entity_type, entity_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor_time ON audit_logs(actor_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action_time ON audit_logs(action, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_clients_active_name ON clients(LOWER(name)) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_clients_active_phone_digits ON clients(normalize_phone_digits(phone)) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_service_jobs_active_service_date ON service_jobs(service_date DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_service_jobs_active_created_by ON service_jobs(created_by) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_service_jobs_active_assigned_staff ON service_jobs(assigned_staff_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_service_jobs_invoice_reference ON service_jobs(invoice_reference);
CREATE INDEX IF NOT EXISTS idx_service_jobs_client_uuid ON service_jobs(client_uuid) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_service_jobs_client_name_phase2_trgm ON service_jobs USING gin (client_name gin_trgm_ops) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_service_jobs_service_name_phase2_trgm ON service_jobs USING gin (service_name gin_trgm_ops) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_service_jobs_description_phase2_trgm ON service_jobs USING gin (description gin_trgm_ops) WHERE deleted_at IS NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'phone_number'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_phone_number_phase2_trgm ON service_jobs USING gin (phone_number gin_trgm_ops) WHERE deleted_at IS NULL';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_inventory_items_active_name ON inventory_items(LOWER(item_name)) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_inventory_items_active_category ON inventory_items(category) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_inventory_sales_client_uuid_time ON inventory_sales(client_uuid, sold_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_inventory_sales_client_name_phase2_trgm ON inventory_sales USING gin (client_name gin_trgm_ops) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_inventory_sales_client_phone_phase2_trgm ON inventory_sales USING gin (client_phone gin_trgm_ops) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_inventory_carts_status_created ON inventory_carts(status, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_inventory_cart_items_cart_active ON inventory_cart_items(cart_id) WHERE deleted_at IS NULL;

COMMIT;