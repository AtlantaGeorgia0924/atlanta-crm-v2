-- Service ownership and activity tracking metadata.

DO $$
BEGIN
    IF to_regclass('public.service_jobs') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS created_by TEXT';
        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS created_by_name TEXT';
        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS created_by_role TEXT';

        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS last_edited_by TEXT';
        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS last_edited_by_name TEXT';
        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS last_edited_at TIMESTAMPTZ';

        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS returned_by TEXT';
        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS returned_by_name TEXT';
        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS returned_at TIMESTAMPTZ';

        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS last_payment_by TEXT';
        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS last_payment_by_name TEXT';
        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS last_payment_at TIMESTAMPTZ';

        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS assigned_staff_id TEXT';
        EXECUTE 'ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS assigned_staff_name TEXT';

        EXECUTE 'UPDATE service_jobs
            SET created_by_name = COALESCE(created_by_name, ''System Import'')
            WHERE (created_by_name IS NULL OR BTRIM(created_by_name) = '''')
              AND (legacy_source_id IS NOT NULL OR source_created_at IS NOT NULL)';

        EXECUTE 'UPDATE service_jobs
            SET created_by_role = COALESCE(created_by_role, ''system'')
            WHERE (created_by_role IS NULL OR BTRIM(created_by_role) = '''')
              AND (legacy_source_id IS NOT NULL OR source_created_at IS NOT NULL)';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_service_jobs_created_by ON service_jobs(created_by);
CREATE INDEX IF NOT EXISTS idx_service_jobs_last_edited_by ON service_jobs(last_edited_by);
CREATE INDEX IF NOT EXISTS idx_service_jobs_assigned_staff_id ON service_jobs(assigned_staff_id);
CREATE INDEX IF NOT EXISTS idx_service_jobs_created_at_desc ON service_jobs(created_at DESC);
