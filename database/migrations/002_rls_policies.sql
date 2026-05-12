-- ============================================================
-- Row Level Security Policies
-- Run after 001_initial_schema.sql
-- ============================================================

-- Enable RLS on all tables
ALTER TABLE clients                    ENABLE ROW LEVEL SECURITY;
ALTER TABLE operational_billing_rows   ENABLE ROW LEVEL SECURITY;
ALTER TABLE operational_stock_rows     ENABLE ROW LEVEL SECURITY;
ALTER TABLE manual_expenses            ENABLE ROW LEVEL SECURITY;
ALTER TABLE allowances                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments                   ENABLE ROW LEVEL SECURITY;
ALTER TABLE cash_flow_summary          ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings                   ENABLE ROW LEVEL SECURITY;

-- Authenticated users have full access to all tables
-- Adjust these policies to match your multi-user requirements

CREATE POLICY "auth_all_clients"
    ON clients FOR ALL
    TO authenticated
    USING (TRUE) WITH CHECK (TRUE);

CREATE POLICY "auth_all_billing"
    ON operational_billing_rows FOR ALL
    TO authenticated
    USING (TRUE) WITH CHECK (TRUE);

CREATE POLICY "auth_all_stock"
    ON operational_stock_rows FOR ALL
    TO authenticated
    USING (TRUE) WITH CHECK (TRUE);

CREATE POLICY "auth_all_expenses"
    ON manual_expenses FOR ALL
    TO authenticated
    USING (TRUE) WITH CHECK (TRUE);

CREATE POLICY "auth_all_allowances"
    ON allowances FOR ALL
    TO authenticated
    USING (TRUE) WITH CHECK (TRUE);

CREATE POLICY "auth_all_payments"
    ON payments FOR ALL
    TO authenticated
    USING (TRUE) WITH CHECK (TRUE);

CREATE POLICY "auth_all_cashflow"
    ON cash_flow_summary FOR ALL
    TO authenticated
    USING (TRUE) WITH CHECK (TRUE);

CREATE POLICY "auth_all_settings"
    ON settings FOR ALL
    TO authenticated
    USING (TRUE) WITH CHECK (TRUE);
