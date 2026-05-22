-- Payments transaction engine upgrade
-- Converts legacy payments usage into auditable payment transactions linked to service_jobs.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    reference_no TEXT UNIQUE NOT NULL,

    client_id UUID,
    service_job_id UUID,
    billing_row_id UUID,

    client_name TEXT,
    client_phone TEXT,

    payment_amount NUMERIC(12,2) NOT NULL,
    amount NUMERIC(12,2),

    payment_method TEXT,
    payment_note TEXT,
    notes TEXT,

    previous_balance NUMERIC(12,2),
    new_balance NUMERIC(12,2),

    previous_paid_amount NUMERIC(12,2),
    new_paid_amount NUMERIC(12,2),

    previous_status TEXT,
    new_status TEXT,

    applied_by UUID,
    applied_by_name TEXT,
    performed_by TEXT,

    payment_date DATE,

    is_reversed BOOLEAN NOT NULL DEFAULT FALSE,
    reversed_at TIMESTAMPTZ,
    reversed_by UUID,
    reversal_reason TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Backward-compatible upgrades for legacy environments.
DO $$
BEGIN
    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS service_job_id UUID';
    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS billing_row_id UUID';

    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS client_name TEXT';
    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS client_phone TEXT';

    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_amount NUMERIC(12,2)';
    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS amount NUMERIC(12,2)';

    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_note TEXT';
    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS notes TEXT';

    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS previous_balance NUMERIC(12,2)';
    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS new_balance NUMERIC(12,2)';
    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS previous_paid_amount NUMERIC(12,2)';
    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS new_paid_amount NUMERIC(12,2)';
    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS previous_status TEXT';
    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS new_status TEXT';

    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS applied_by UUID';
    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS applied_by_name TEXT';
    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS performed_by TEXT';

    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_date DATE';
    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS is_reversed BOOLEAN NOT NULL DEFAULT FALSE';
    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS reversed_at TIMESTAMPTZ';
    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS reversed_by UUID';
    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS reversal_reason TEXT';
    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()';

    EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS reference_no TEXT';
END $$;

-- Legacy compatibility backfills.
UPDATE payments
SET service_job_id = COALESCE(service_job_id, billing_row_id)
WHERE service_job_id IS NULL;

UPDATE payments
SET payment_amount = COALESCE(payment_amount, amount, 0)
WHERE payment_amount IS NULL;

UPDATE payments
SET amount = COALESCE(amount, payment_amount)
WHERE amount IS NULL;

UPDATE payments
SET payment_note = COALESCE(NULLIF(payment_note, ''), notes)
WHERE payment_note IS NULL OR payment_note = '';

UPDATE payments
SET notes = COALESCE(NULLIF(notes, ''), payment_note)
WHERE notes IS NULL OR notes = '';

UPDATE payments
SET payment_date = COALESCE(
    payment_date,
    CASE
        WHEN created_at IS NOT NULL THEN created_at::date
        ELSE CURRENT_DATE
    END
)
WHERE payment_date IS NULL;

-- Ensure each transaction has a unique, searchable reference.
UPDATE payments p
SET reference_no = CONCAT(
    'ATL-PAY-',
    TO_CHAR(COALESCE(p.payment_date, CURRENT_DATE), 'YYYYMMDD'),
    '-',
    UPPER(SUBSTRING(MD5(p.id::text), 1, 4))
)
WHERE p.reference_no IS NULL OR BTRIM(p.reference_no) = '';

WITH duplicates AS (
    SELECT id, reference_no,
           ROW_NUMBER() OVER (PARTITION BY reference_no ORDER BY created_at, id) AS rn
    FROM payments
)
UPDATE payments p
SET reference_no = CONCAT(p.reference_no, '-', duplicates.rn)
FROM duplicates
WHERE p.id = duplicates.id
  AND duplicates.rn > 1;

ALTER TABLE payments
    ALTER COLUMN reference_no SET NOT NULL,
    ALTER COLUMN payment_amount SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_reference_no ON payments(reference_no);
CREATE INDEX IF NOT EXISTS idx_payments_service_job_id ON payments(service_job_id);
CREATE INDEX IF NOT EXISTS idx_payments_client_id ON payments(client_id);
CREATE INDEX IF NOT EXISTS idx_payments_created_at_desc ON payments(created_at DESC);

-- Backward-compatibility helper indexes.
CREATE INDEX IF NOT EXISTS idx_payments_billing_row_id ON payments(billing_row_id);
CREATE INDEX IF NOT EXISTS idx_payments_client_name_created ON payments(client_name, created_at DESC);
