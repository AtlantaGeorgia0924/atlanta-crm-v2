SELECT 'service_jobs_total_rows' AS check_name, COUNT(*)::BIGINT AS actual
FROM service_jobs
UNION ALL
SELECT 'inventory_items_total_rows', COUNT(*)::BIGINT
FROM inventory_items
UNION ALL
SELECT 'inventory_sales_total_rows', COUNT(*)::BIGINT
FROM inventory_sales
UNION ALL
SELECT 'payments_total_rows', COUNT(*)::BIGINT
FROM payments
UNION ALL
SELECT 'payments_non_zero_rows', COUNT(*)::BIGINT
FROM payments
WHERE COALESCE(payment_amount, amount, 0) <> 0
UNION ALL
SELECT 'crm_audit_log_rows', COUNT(*)::BIGINT
FROM crm_audit_log
UNION ALL
SELECT 'cashflow_audit_log_rows', COUNT(*)::BIGINT
FROM cashflow_audit_log
UNION ALL
SELECT 'users_total_rows', COUNT(*)::BIGINT
FROM users;

SELECT 'users_by_role' AS section, lower(COALESCE(role, '')) AS role, COUNT(*)::BIGINT AS total
FROM users
GROUP BY lower(COALESCE(role, ''))
ORDER BY role;

SELECT 'service_jobs_payment_status' AS section, COALESCE(payment_status, '') AS payment_status, COUNT(*)::BIGINT AS total
FROM service_jobs
GROUP BY COALESCE(payment_status, '')
ORDER BY payment_status;

SELECT 'inventory_sales_payment_status' AS section, COALESCE(payment_status, '') AS payment_status, COUNT(*)::BIGINT AS total
FROM inventory_sales
GROUP BY COALESCE(payment_status, '')
ORDER BY payment_status;