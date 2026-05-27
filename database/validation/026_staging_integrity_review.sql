-- Staging integrity review after applying 025 + 026.

-- Row count and total consistency snapshots.
SELECT 'service_jobs_rows' AS metric, COUNT(*)::BIGINT AS value FROM service_jobs
UNION ALL
SELECT 'inventory_items_rows', COUNT(*)::BIGINT FROM inventory_items
UNION ALL
SELECT 'inventory_sales_rows', COUNT(*)::BIGINT FROM inventory_sales
UNION ALL
SELECT 'inventory_sale_items_rows', COUNT(*)::BIGINT FROM inventory_sale_items
UNION ALL
SELECT 'payments_rows', COUNT(*)::BIGINT FROM payments
UNION ALL
SELECT 'crm_audit_log_rows', COUNT(*)::BIGINT FROM crm_audit_log
UNION ALL
SELECT 'audit_logs_rows', COUNT(*)::BIGINT FROM audit_logs;

SELECT 'payments_total_amount' AS metric, COALESCE(SUM(COALESCE(payment_amount, amount, 0)), 0)::NUMERIC(20,2) AS value
FROM payments
UNION ALL
SELECT 'inventory_sales_total_amount', COALESCE(SUM(COALESCE(amount_charged, 0)), 0)::NUMERIC(20,2)
FROM inventory_sales
UNION ALL
SELECT 'inventory_sales_total_paid', COALESCE(SUM(COALESCE(paid_amount, 0)), 0)::NUMERIC(20,2)
FROM inventory_sales
UNION ALL
SELECT 'service_jobs_total_amount', COALESCE(SUM(COALESCE(amount_charged, 0)), 0)::NUMERIC(20,2)
FROM service_jobs
UNION ALL
SELECT 'service_jobs_total_paid', COALESCE(SUM(COALESCE(paid_amount, 0)), 0)::NUMERIC(20,2)
FROM service_jobs;

-- Inventory consistency and non-negative stock guard.
SELECT 'negative_inventory_rows' AS check_name, COUNT(*)::BIGINT AS actual
FROM inventory_items
WHERE COALESCE(quantity, 0) < 0
UNION ALL
SELECT 'inventory_sales_without_items', COUNT(*)::BIGINT
FROM inventory_sales s
WHERE NOT EXISTS (SELECT 1 FROM inventory_sale_items si WHERE si.sale_id = s.id)
UNION ALL
SELECT 'movement_history_without_item', COUNT(*)::BIGINT
FROM inventory_movement_history m
LEFT JOIN inventory_items i ON i.id = m.inventory_item_id
WHERE i.id IS NULL
UNION ALL
SELECT 'stock_adjustment_without_item', COUNT(*)::BIGINT
FROM stock_adjustment_audit a
LEFT JOIN inventory_items i ON i.id = a.inventory_item_id
WHERE i.id IS NULL;

-- Soft delete behavior checks.
SELECT 'service_jobs_soft_deleted_rows' AS metric, COUNT(*)::BIGINT AS value
FROM service_jobs
WHERE deleted_at IS NOT NULL
UNION ALL
SELECT 'inventory_items_soft_deleted_rows', COUNT(*)::BIGINT
FROM inventory_items
WHERE deleted_at IS NOT NULL
UNION ALL
SELECT 'clients_soft_deleted_rows', COUNT(*)::BIGINT
FROM clients
WHERE deleted_at IS NOT NULL;

-- Append-only enforcement checks.
SELECT 'payments_append_only_trigger' AS check_name, COUNT(*)::BIGINT AS actual
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'payments'
  AND NOT t.tgisinternal
  AND t.tgname = 'trg_payments_append_only'
UNION ALL
SELECT 'service_payments_append_only_trigger', COUNT(*)::BIGINT
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'service_payments'
  AND NOT t.tgisinternal
  AND t.tgname = 'trg_service_payments_append_only'
UNION ALL
SELECT 'sale_payments_append_only_trigger', COUNT(*)::BIGINT
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'sale_payments'
  AND NOT t.tgisinternal
  AND t.tgname = 'trg_sale_payments_append_only'
UNION ALL
SELECT 'audit_logs_append_only_trigger', COUNT(*)::BIGINT
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'audit_logs'
  AND NOT t.tgisinternal
  AND t.tgname = 'trg_audit_logs_append_only';

-- Migration status and rollback history checkpoints.
SELECT migration_version, status, applied_at, rolled_back_at
FROM migration_version_log
WHERE migration_version IN ('025_phase2_core_restructure', '026_transaction_safety_hardening')
ORDER BY migration_version;

-- Index usage review for search-heavy access paths.
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, client_name, service_name
FROM service_jobs
WHERE deleted_at IS NULL
  AND (client_name ILIKE '%a%' OR service_name ILIKE '%a%' OR description ILIKE '%a%')
ORDER BY service_date DESC
LIMIT 200;

EXPLAIN (ANALYZE, BUFFERS)
SELECT id, item_name, quantity
FROM inventory_items
WHERE deleted_at IS NULL
  AND item_name ILIKE '%a%'
ORDER BY item_name
LIMIT 200;
