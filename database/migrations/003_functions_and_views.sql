-- ============================================================
-- Cash Flow Summary Refresh Function
-- Called by the async refresh worker
-- ============================================================

CREATE OR REPLACE FUNCTION refresh_cash_flow_summary()
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
    r RECORD;
BEGIN
    -- Collect distinct months from billing, expenses, allowances
    FOR r IN
        SELECT DISTINCT TO_CHAR(d, 'YYYY-MM') AS period_month
        FROM (
            SELECT invoice_date AS d FROM operational_billing_rows WHERE invoice_date IS NOT NULL
            UNION
            SELECT expense_date FROM manual_expenses
            UNION
            SELECT allowance_date FROM allowances
        ) all_dates
    LOOP
        INSERT INTO cash_flow_summary (period_month, total_revenue, total_expenses, total_allowances, computed_at)
        VALUES (
            r.period_month,
            COALESCE((
                SELECT SUM(amount_paid) FROM operational_billing_rows
                WHERE TO_CHAR(invoice_date, 'YYYY-MM') = r.period_month
            ), 0),
            COALESCE((
                SELECT SUM(amount) FROM manual_expenses
                WHERE TO_CHAR(expense_date, 'YYYY-MM') = r.period_month
            ), 0),
            COALESCE((
                SELECT SUM(amount) FROM allowances
                WHERE TO_CHAR(allowance_date, 'YYYY-MM') = r.period_month
            ), 0),
            NOW()
        )
        ON CONFLICT (period_month) DO UPDATE SET
            total_revenue    = EXCLUDED.total_revenue,
            total_expenses   = EXCLUDED.total_expenses,
            total_allowances = EXCLUDED.total_allowances,
            computed_at      = EXCLUDED.computed_at;
    END LOOP;
END;
$$;

-- ============================================================
-- Debtors view (fast read)
-- ============================================================
CREATE OR REPLACE VIEW debtors AS
SELECT
    b.id,
    b.client_id,
    b.client_name,
    b.service_name,
    b.total_amount,
    b.amount_paid,
    b.balance,
    b.status,
    b.invoice_date,
    b.due_date
FROM operational_billing_rows b
WHERE b.balance > 0
ORDER BY b.due_date ASC NULLS LAST;

-- ============================================================
-- Dashboard summary function (single fast query)
-- ============================================================
CREATE OR REPLACE FUNCTION get_dashboard_summary()
RETURNS JSON LANGUAGE plpgsql AS $$
DECLARE
    result JSON;
BEGIN
    SELECT json_build_object(
        'total_clients',        (SELECT COUNT(*) FROM clients WHERE is_active = TRUE),
        'total_invoices',       (SELECT COUNT(*) FROM operational_billing_rows),
        'total_billed',         (SELECT COALESCE(SUM(total_amount), 0) FROM operational_billing_rows),
        'total_collected',      (SELECT COALESCE(SUM(amount_paid), 0) FROM operational_billing_rows),
        'total_outstanding',    (SELECT COALESCE(SUM(balance), 0) FROM operational_billing_rows WHERE balance > 0),
        'total_expenses',       (SELECT COALESCE(SUM(amount), 0) FROM manual_expenses),
        'total_allowances',     (SELECT COALESCE(SUM(amount), 0) FROM allowances),
        'low_stock_count',      (SELECT COUNT(*) FROM operational_stock_rows WHERE quantity <= reorder_level AND is_active = TRUE),
        'computed_at',          NOW()
    ) INTO result;
    RETURN result;
END;
$$;
