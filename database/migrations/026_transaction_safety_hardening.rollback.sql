BEGIN;

DROP FUNCTION IF EXISTS checkout_inventory_cart_tx(JSONB, TEXT, TEXT, TEXT, NUMERIC, TEXT, NUMERIC, TEXT, TEXT, TEXT);
DROP FUNCTION IF EXISTS apply_service_payment_tx(UUID, NUMERIC, TEXT, TEXT, TEXT, DATE, TEXT, TEXT, TEXT);
DROP FUNCTION IF EXISTS reverse_service_payment_tx(UUID, NUMERIC, TEXT, TEXT, TEXT, DATE, TEXT);
DROP FUNCTION IF EXISTS cleanup_stale_idempotency_keys(INTERVAL);

DROP TABLE IF EXISTS stock_adjustment_audit;
DROP TABLE IF EXISTS inventory_movement_history;

DROP TRIGGER IF EXISTS trg_payments_append_only ON payments;

DROP INDEX IF EXISTS ux_inventory_sales_checkout_idempotency_key;
DROP INDEX IF EXISTS ux_inventory_sales_transaction_reference;
DROP INDEX IF EXISTS ux_payments_idempotency_key;

ALTER TABLE IF EXISTS inventory_sales
    DROP COLUMN IF EXISTS checkout_idempotency_key,
    DROP COLUMN IF EXISTS transaction_reference;

ALTER TABLE IF EXISTS payments
    DROP COLUMN IF EXISTS idempotency_key;

INSERT INTO migration_version_log (
    migration_version,
    description,
    status,
    applied_at,
    rolled_back_at,
    rollback_reference,
    applied_by,
    metadata
)
VALUES (
    '026_transaction_safety_hardening',
    'Transaction safety hardening for checkout and payments',
    'rolled_back',
    NOW(),
    NOW(),
    'database/migrations/026_transaction_safety_hardening.rollback.sql',
    CURRENT_USER,
    jsonb_build_object('rolled_back_by', CURRENT_USER)
)
ON CONFLICT (migration_version) DO UPDATE
SET status = 'rolled_back',
    rolled_back_at = NOW(),
    rollback_reference = EXCLUDED.rollback_reference,
    applied_by = EXCLUDED.applied_by,
    metadata = migration_version_log.metadata || jsonb_build_object('rolled_back_by', CURRENT_USER, 'rolled_back_at', NOW());

COMMIT;
