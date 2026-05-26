SELECT 'service_payment_source_rows' AS check_name, COUNT(*)::BIGINT AS actual
FROM payments
WHERE COALESCE(payment_amount, amount, 0) <> 0
UNION ALL
SELECT 'service_jobs_total_rows', COUNT(*)::BIGINT
FROM service_jobs
UNION ALL
SELECT 'inventory_items_total_rows', COUNT(*)::BIGINT
FROM inventory_items
UNION ALL
SELECT 'inventory_sales_total_rows', COUNT(*)::BIGINT
FROM inventory_sales
UNION ALL
SELECT 'service_payment_history_rows', COUNT(*)::BIGINT
FROM service_payments
WHERE source_payment_id IS NOT NULL
UNION ALL
SELECT 'sale_payment_rows', COUNT(*)::BIGINT
FROM sale_payments
UNION ALL
SELECT 'migration_version_log_025_applied_rows', COUNT(*)::BIGINT
FROM migration_version_log
WHERE migration_version = '025_phase2_core_restructure'
  AND status = 'applied'
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
WHERE deleted_at IS NOT NULL AND deleted_by IS NULL
UNION ALL
SELECT 'service_payments_without_payment_time', COUNT(*)::BIGINT
FROM service_payments
WHERE payment_time IS NULL
UNION ALL
SELECT 'sale_payments_without_payment_time', COUNT(*)::BIGINT
FROM sale_payments
WHERE payment_time IS NULL
UNION ALL
SELECT 'service_payments_non_numeric_reversal_balance', COUNT(*)::BIGINT
FROM service_payments
WHERE entry_type = 'REVERSAL'
  AND amount >= 0
UNION ALL
SELECT 'invalid_user_roles', COUNT(*)::BIGINT
FROM users
WHERE lower(COALESCE(role, '')) NOT IN ('admin', 'staff', 'manager', 'accountant', 'inventory_officer');

SELECT 'append_only_trigger_count' AS check_name, COUNT(*)::BIGINT AS actual
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE NOT t.tgisinternal
  AND c.relname IN ('service_payments', 'sale_payments', 'audit_logs')
  AND t.tgname IN ('trg_service_payments_append_only', 'trg_sale_payments_append_only', 'trg_audit_logs_append_only')
UNION ALL
SELECT 'role_catalog_rows', COUNT(*)::BIGINT
FROM role_catalog
UNION ALL
SELECT 'audit_logs_with_before_or_after', COUNT(*)::BIGINT
FROM audit_logs
WHERE before_value IS NOT NULL OR after_value IS NOT NULL
UNION ALL
SELECT 'phase2_search_indexes_present', COUNT(*)::BIGINT
FROM pg_indexes
WHERE schemaname = 'public'
  AND indexname IN (
      'idx_service_jobs_client_name_phase2_trgm',
      'idx_service_jobs_service_name_phase2_trgm',
      'idx_service_jobs_description_phase2_trgm',
      'idx_inventory_sales_client_name_phase2_trgm',
      'idx_inventory_sales_client_phone_phase2_trgm'
  );

SELECT column_name, data_type, numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('service_jobs', 'inventory_items', 'payments', 'inventory_sales', 'inventory_sale_items', 'service_payments', 'sale_payments')
  AND column_name IN ('amount_charged', 'paid_amount', 'payment_amount', 'amount', 'cost_price', 'selling_price', 'expense_amount', 'product_profit', 'total_profit', 'balance', 'unit_price', 'unit_cost')
ORDER BY table_name, column_name;

SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('service_jobs', 'inventory_items', 'payments', 'inventory_sales', 'inventory_sale_items', 'service_payments', 'sale_payments')
  AND data_type IN ('real', 'double precision')
ORDER BY table_name, column_name;