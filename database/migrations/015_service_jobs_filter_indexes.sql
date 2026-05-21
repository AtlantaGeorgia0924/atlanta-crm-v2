CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Core filter/sort indexes (guarded for schema drift)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'service_date'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_service_date_desc ON service_jobs(service_date DESC)';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'payment_status'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_payment_status ON service_jobs(payment_status)';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'is_return'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_is_return ON service_jobs(is_return)';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'amount_charged'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_amount_charged ON service_jobs(amount_charged)';
    END IF;
END $$;

-- Trigram indexes for global ILIKE search fields (guarded for schema drift)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'client_name'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_client_name_trgm ON service_jobs USING gin (client_name gin_trgm_ops)';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'phone_number'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_phone_number_trgm ON service_jobs USING gin (phone_number gin_trgm_ops)';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'service_name'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_service_name_trgm ON service_jobs USING gin (service_name gin_trgm_ops)';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'notes'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_notes_trgm ON service_jobs USING gin (notes gin_trgm_ops)';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'legacy_source_id'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_legacy_source_id_trgm ON service_jobs USING gin (legacy_source_id gin_trgm_ops)';
    END IF;
END $$;
