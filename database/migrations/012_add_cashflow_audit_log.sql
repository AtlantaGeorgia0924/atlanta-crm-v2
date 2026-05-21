-- Audit log for cash flow mutations (expense creation/reversal, allowance withdrawal).
CREATE TABLE IF NOT EXISTS cashflow_audit_log (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    action        TEXT NOT NULL,          -- 'expense_created' | 'expense_reversed' | 'allowance_withdrawn'
    amount        NUMERIC(14,2),
    performed_by  TEXT,                   -- user id from JWT
    related_record_id TEXT,               -- expense or withdrawal id
    detail        JSONB,                  -- optional extra context
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cashflow_audit_action     ON cashflow_audit_log(action);
CREATE INDEX IF NOT EXISTS idx_cashflow_audit_created_at ON cashflow_audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cashflow_audit_performed_by ON cashflow_audit_log(performed_by);
