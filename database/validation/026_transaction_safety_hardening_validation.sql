SELECT 'inventory_movement_history_exists' AS check_name, COUNT(*)::BIGINT AS actual
FROM pg_class
WHERE relnamespace = 'public'::regnamespace
  AND relname = 'inventory_movement_history'
UNION ALL
SELECT 'stock_adjustment_audit_exists', COUNT(*)::BIGINT
FROM pg_class
WHERE relnamespace = 'public'::regnamespace
  AND relname = 'stock_adjustment_audit'
UNION ALL
SELECT 'payments_idempotency_column_exists', COUNT(*)::BIGINT
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'payments'
  AND column_name = 'idempotency_key'
UNION ALL
SELECT 'inventory_sales_checkout_idempotency_column_exists', COUNT(*)::BIGINT
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'inventory_sales'
  AND column_name = 'checkout_idempotency_key'
UNION ALL
SELECT 'migration_version_log_026_applied_rows', COUNT(*)::BIGINT
FROM migration_version_log
WHERE migration_version = '026_transaction_safety_hardening'
  AND status = 'applied';

SELECT 'transaction_functions_present' AS check_name, COUNT(*)::BIGINT AS actual
FROM pg_proc
WHERE proname IN ('checkout_inventory_cart_tx', 'apply_service_payment_tx', 'reverse_service_payment_tx', 'cleanup_stale_idempotency_keys')
UNION ALL
SELECT 'payments_idempotency_unique_index', COUNT(*)::BIGINT
FROM pg_indexes
WHERE schemaname = 'public'
  AND indexname = 'ux_payments_idempotency_key'
UNION ALL
SELECT 'inventory_checkout_idempotency_unique_index', COUNT(*)::BIGINT
FROM pg_indexes
WHERE schemaname = 'public'
  AND indexname = 'ux_inventory_sales_checkout_idempotency_key'
UNION ALL
SELECT 'payments_append_only_trigger', COUNT(*)::BIGINT
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'payments'
  AND NOT t.tgisinternal
  AND t.tgname = 'trg_payments_append_only';

SELECT column_name, data_type, numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('inventory_movement_history', 'stock_adjustment_audit', 'payments', 'inventory_sales')
  AND column_name IN ('quantity_change', 'quantity_before', 'quantity_after', 'payment_amount', 'amount', 'amount_charged', 'paid_amount', 'balance')
ORDER BY table_name, column_name;
