-- Archive table for cashflow_audit_log rows older than 12 months.
-- Identical schema to cashflow_audit_log so rows can be moved with a simple INSERT.
CREATE TABLE IF NOT EXISTS cashflow_audit_archive (
    id                UUID PRIMARY KEY,
    action            TEXT NOT NULL,
    amount            NUMERIC(14,2),
    performed_by      TEXT,
    related_record_id TEXT,
    detail            JSONB,
    created_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_audit_archive_action     ON cashflow_audit_archive(action);
CREATE INDEX IF NOT EXISTS idx_audit_archive_created_at ON cashflow_audit_archive(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_archive_record_id  ON cashflow_audit_archive(related_record_id);

-- Add index on cashflow_audit_log for related_record_id (lookup by linked record)
CREATE INDEX IF NOT EXISTS idx_cashflow_audit_record_id ON cashflow_audit_log(related_record_id);

-- Financial integrity issues log
CREATE TABLE IF NOT EXISTS financial_integrity_issues (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    check_name   TEXT NOT NULL,
    description  TEXT NOT NULL,
    severity     TEXT NOT NULL DEFAULT 'warning',   -- 'warning' | 'error'
    detail       JSONB,
    detected_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_integrity_check_name  ON financial_integrity_issues(check_name);
CREATE INDEX IF NOT EXISTS idx_integrity_detected_at ON financial_integrity_issues(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_integrity_severity    ON financial_integrity_issues(severity);
