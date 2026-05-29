-- Billing search hardening indexes for larger datasets (1k/5k/10k+ rows)

CREATE EXTENSION IF NOT EXISTS pg_trgm;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'invoice_id'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_invoice_id_trgm ON service_jobs USING gin (invoice_id gin_trgm_ops)';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'invoice_reference'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_invoice_reference_trgm ON service_jobs USING gin (invoice_reference gin_trgm_ops)';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'serial_number'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_serial_number_trgm ON service_jobs USING gin (serial_number gin_trgm_ops)';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'imei'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_imei_trgm ON service_jobs USING gin (imei gin_trgm_ops)';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'condition'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_condition_trgm ON service_jobs USING gin (condition gin_trgm_ops)';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'lock_status'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_lock_status_trgm ON service_jobs USING gin (lock_status gin_trgm_ops)';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'created_by_name'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_created_by_name_trgm ON service_jobs USING gin (created_by_name gin_trgm_ops)';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'assigned_staff_name'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_assigned_staff_name_trgm ON service_jobs USING gin (assigned_staff_name gin_trgm_ops)';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('public.payments') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'payments' AND column_name = 'reference_no'
        ) THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_payments_reference_no_trgm ON payments USING gin (reference_no gin_trgm_ops)';
        END IF;

        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'payments' AND column_name = 'payment_note'
        ) THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_payments_payment_note_trgm ON payments USING gin (payment_note gin_trgm_ops)';
        END IF;

        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'payments' AND column_name = 'notes'
        ) THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_payments_notes_trgm ON payments USING gin (notes gin_trgm_ops)';
        END IF;

        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'payments' AND column_name = 'applied_by_name'
        ) THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_payments_applied_by_name_trgm ON payments USING gin (applied_by_name gin_trgm_ops)';
        END IF;

        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'payments' AND column_name = 'service_job_id'
        ) AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'payments' AND column_name = 'created_at'
        ) THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_payments_service_job_created_at ON payments (service_job_id, created_at DESC)';
        END IF;
    END IF;
END $$;
