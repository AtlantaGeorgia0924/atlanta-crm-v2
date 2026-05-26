SELECT 'migration_version_log_025_rolled_back_rows' AS check_name, COUNT(*)::BIGINT AS actual
FROM migration_version_log
WHERE migration_version = '025_phase2_core_restructure'
  AND status = 'rolled_back'
UNION ALL
SELECT 'service_payments_table_exists', COUNT(*)::BIGINT
FROM pg_class
WHERE relnamespace = 'public'::regnamespace
  AND relname = 'service_payments'
UNION ALL
SELECT 'sale_payments_table_exists', COUNT(*)::BIGINT
FROM pg_class
WHERE relnamespace = 'public'::regnamespace
  AND relname = 'sale_payments'
UNION ALL
SELECT 'audit_logs_table_exists', COUNT(*)::BIGINT
FROM pg_class
WHERE relnamespace = 'public'::regnamespace
  AND relname = 'audit_logs'
UNION ALL
SELECT 'inventory_carts_table_exists', COUNT(*)::BIGINT
FROM pg_class
WHERE relnamespace = 'public'::regnamespace
  AND relname = 'inventory_carts'
UNION ALL
SELECT 'inventory_cart_items_table_exists', COUNT(*)::BIGINT
FROM pg_class
WHERE relnamespace = 'public'::regnamespace
  AND relname = 'inventory_cart_items';

SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND (
      (table_name = 'service_jobs' AND column_name IN ('client_uuid', 'invoice_reference', 'deleted_at', 'deleted_by', 'restored_at', 'restored_by'))
      OR (table_name = 'inventory_items' AND column_name IN ('deleted_at', 'deleted_by', 'restored_at', 'restored_by'))
      OR (table_name = 'clients' AND column_name IN ('deleted_at', 'deleted_by', 'restored_at', 'restored_by'))
      OR (table_name = 'inventory_sales' AND column_name IN ('client_uuid', 'deleted_at', 'deleted_by', 'restored_at', 'restored_by'))
      OR (table_name = 'inventory_sale_items' AND column_name IN ('updated_at', 'deleted_at', 'deleted_by', 'restored_at', 'restored_by'))
  )
ORDER BY table_name, column_name;