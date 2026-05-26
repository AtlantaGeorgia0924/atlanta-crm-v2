-- Fast service entry metadata used by the POS + CRM workflow.

ALTER TABLE service_jobs
    ADD COLUMN IF NOT EXISTS device_model TEXT;

CREATE INDEX IF NOT EXISTS idx_service_jobs_device_model_trgm
ON service_jobs USING gin (device_model gin_trgm_ops);
