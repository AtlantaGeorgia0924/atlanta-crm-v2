CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Future-proof role catalog.
CREATE TABLE IF NOT EXISTS role_catalog (
    key TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    is_system BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO role_catalog (key, label)
VALUES
    ('admin', 'Administrator'),
    ('staff', 'Staff'),
    ('manager', 'Manager'),
    ('accountant', 'Accountant'),
    ('inventory_officer', 'Inventory Officer')
ON CONFLICT (key) DO NOTHING;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'users'
    ) THEN
        EXECUTE 'ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER DEFAULT 0';
        EXECUTE 'ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ';
        EXECUTE 'ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_ip TEXT';
        EXECUTE 'ALTER TABLE users ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ';
        EXECUTE 'ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_at TIMESTAMPTZ';
        EXECUTE 'ALTER TABLE users ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ';
        EXECUTE 'ALTER TABLE users ADD COLUMN IF NOT EXISTS created_by TEXT';
        EXECUTE 'ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_by TEXT';
        EXECUTE 'ALTER TABLE users ALTER COLUMN role SET DEFAULT ''staff''';
        EXECUTE 'UPDATE users SET role = ''staff'' WHERE role IS NULL OR role = '''' OR role = ''user''';
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'users'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'users'
          AND constraint_name = 'chk_users_role_allowed'
    ) THEN
        EXECUTE 'ALTER TABLE users ADD CONSTRAINT chk_users_role_allowed CHECK (lower(role) IN (''admin'', ''staff'', ''manager'', ''accountant'', ''inventory_officer''))';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_users_role_active ON users(role, is_active);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users((lower(email)));
CREATE INDEX IF NOT EXISTS idx_users_last_login_at ON users(last_login_at DESC);

CREATE INDEX IF NOT EXISTS idx_crm_audit_entity_type_action ON crm_audit_log(entity_type, action);
CREATE INDEX IF NOT EXISTS idx_crm_audit_performed_by_created ON crm_audit_log(performed_by, created_at DESC);
