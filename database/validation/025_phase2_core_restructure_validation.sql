SELECT 'service_payment_source_rows' AS check_name, COUNT(*)::BIGINT AS actual
FROM payments
WHERE COALESCE(payment_amount, amount, 0) <> 0
UNION ALL
SELECT 'service_payment_history_rows', COUNT(*)::BIGINT
FROM service_payments
WHERE source_payment_id IS NOT NULL
UNION ALL
SELECT 'sale_payment_rows', COUNT(*)::BIGINT
FROM sale_payments
UNION ALL
SELECT 'crm_audit_log_rows', COUNT(*)::BIGINT
FROM crm_audit_log
UNION ALL
SELECT 'audit_logs_from_crm', COUNT(*)::BIGINT
FROM audit_logs
WHERE source_table = 'crm_audit_log'
UNION ALL
SELECT 'cashflow_audit_log_rows', COUNT(*)::BIGINT
FROM cashflow_audit_log
UNION ALL
SELECT 'audit_logs_from_cashflow', COUNT(*)::BIGINT
FROM audit_logs
WHERE source_table = 'cashflow_audit_log';

SELECT 'service_payments_without_service_job' AS check_name, COUNT(*)::BIGINT AS actual
FROM service_payments
WHERE service_job_id IS NULL
UNION ALL
SELECT 'sale_payments_without_sale', COUNT(*)::BIGINT
FROM sale_payments
WHERE sale_id IS NULL
UNION ALL
SELECT 'service_jobs_without_deleted_at_column_data', COUNT(*)::BIGINT
FROM service_jobs
WHERE deleted_at IS NOT NULL AND deleted_by IS NULL;

SELECT column_name, data_type, numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('service_jobs', 'inventory_items', 'payments', 'inventory_sales', 'inventory_sale_items', 'service_payments', 'sale_payments')
  AND column_name IN ('amount_charged', 'paid_amount', 'payment_amount', 'amount', 'cost_price', 'selling_price', 'expense_amount', 'product_profit', 'total_profit', 'balance', 'unit_price', 'unit_cost')
ORDER BY table_name, column_name;