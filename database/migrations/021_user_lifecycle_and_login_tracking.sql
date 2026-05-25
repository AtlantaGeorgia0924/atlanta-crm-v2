-- User lifecycle, login diagnostics, and safe deletion support.

DO $$
BEGIN
    IF to_regclass('public.users') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE users ADD COLUMN IF NOT EXISTS account_status TEXT DEFAULT ''ACTIVE''';
        EXECUTE 'ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ';
        EXECUTE 'ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_by TEXT';
        EXECUTE 'ALTER TABLE users ADD COLUMN IF NOT EXISTS suspension_reason TEXT';
        EXECUTE 'ALTER TABLE users ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMPTZ';
        EXECUTE 'ALTER TABLE users ADD COLUMN IF NOT EXISTS last_failed_login TIMESTAMPTZ';
        EXECUTE 'ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_user_agent TEXT';

        EXECUTE 'UPDATE users SET account_status = CASE
            WHEN COALESCE(is_active, TRUE) = FALSE THEN ''INACTIVE''
            ELSE ''ACTIVE''
        END
        WHERE account_status IS NULL OR BTRIM(account_status) = ''''';

        EXECUTE 'UPDATE users SET account_status = UPPER(account_status)';

        EXECUTE 'UPDATE users SET is_active = CASE
            WHEN account_status = ''ACTIVE'' THEN TRUE
            ELSE FALSE
        END
        WHERE is_active IS DISTINCT FROM (account_status = ''ACTIVE'')';

        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.table_constraints
            WHERE table_schema = 'public'
              AND table_name = 'users'
              AND constraint_name = 'chk_users_account_status'
        ) THEN
            EXECUTE 'ALTER TABLE users ADD CONSTRAINT chk_users_account_status
                CHECK (account_status IN (''ACTIVE'', ''INACTIVE'', ''SUSPENDED'', ''DELETED''))';
        END IF;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_users_account_status ON users(account_status);
CREATE INDEX IF NOT EXISTS idx_users_deleted_at ON users(deleted_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_last_failed_login ON users(last_failed_login DESC);

-- Ensure phone uniqueness when present.
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone_unique
ON users(phone)
WHERE phone IS NOT NULL AND BTRIM(phone) <> '';
