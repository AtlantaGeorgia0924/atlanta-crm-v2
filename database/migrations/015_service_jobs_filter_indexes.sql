CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Core filter/sort indexes
CREATE INDEX IF NOT EXISTS idx_service_jobs_service_date_desc
    ON service_jobs(service_date DESC);

CREATE INDEX IF NOT EXISTS idx_service_jobs_payment_status
    ON service_jobs(payment_status);

CREATE INDEX IF NOT EXISTS idx_service_jobs_is_return
    ON service_jobs(is_return);

CREATE INDEX IF NOT EXISTS idx_service_jobs_amount_charged
    ON service_jobs(amount_charged);

-- Trigram indexes for global ILIKE search fields
CREATE INDEX IF NOT EXISTS idx_service_jobs_client_name_trgm
    ON service_jobs USING gin (client_name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_service_jobs_phone_number_trgm
    ON service_jobs USING gin (phone_number gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_service_jobs_service_name_trgm
    ON service_jobs USING gin (service_name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_service_jobs_notes_trgm
    ON service_jobs USING gin (notes gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_service_jobs_legacy_source_id_trgm
    ON service_jobs USING gin (legacy_source_id gin_trgm_ops);
