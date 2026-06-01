-- Add device metadata fields to service_jobs so billing invoices can persist inventory item details.
ALTER TABLE service_jobs
    ADD COLUMN IF NOT EXISTS storage TEXT,
    ADD COLUMN IF NOT EXISTS color TEXT,
    ADD COLUMN IF NOT EXISTS battery_health NUMERIC(5,2);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'service_jobs'::regclass
        AND conname = 'service_jobs_battery_health_range_check'
    ) THEN
        ALTER TABLE service_jobs ADD CONSTRAINT service_jobs_battery_health_range_check
            CHECK (battery_health IS NULL OR (battery_health >= 0 AND battery_health <= 100));
    END IF;
END$$;
