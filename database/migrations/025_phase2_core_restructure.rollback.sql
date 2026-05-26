BEGIN;

DROP TRIGGER IF EXISTS trg_audit_logs_append_only ON audit_logs;
DROP TRIGGER IF EXISTS trg_sale_payments_append_only ON sale_payments;
DROP TRIGGER IF EXISTS trg_service_payments_append_only ON service_payments;
DROP TRIGGER IF EXISTS trg_inventory_cart_items_updated ON inventory_cart_items;
DROP TRIGGER IF EXISTS trg_inventory_carts_updated ON inventory_carts;
DROP TRIGGER IF EXISTS trg_inventory_sale_items_updated_phase2 ON inventory_sale_items;
DROP TRIGGER IF EXISTS trg_inventory_sales_updated_phase2 ON inventory_sales;
DROP TRIGGER IF EXISTS trg_audit_logs_updated ON audit_logs;
DROP TRIGGER IF EXISTS trg_sale_payments_updated ON sale_payments;
DROP TRIGGER IF EXISTS trg_service_payments_updated ON service_payments;

DROP TABLE IF EXISTS inventory_cart_items;
DROP TABLE IF EXISTS inventory_carts;
DROP TABLE IF EXISTS audit_logs;
DROP TABLE IF EXISTS sale_payments;
DROP TABLE IF EXISTS service_payments;

ALTER TABLE IF EXISTS service_jobs DROP CONSTRAINT IF EXISTS fk_service_jobs_client_uuid;
ALTER TABLE IF EXISTS inventory_sales DROP CONSTRAINT IF EXISTS fk_inventory_sales_client_uuid;

ALTER TABLE IF EXISTS service_jobs
    DROP COLUMN IF EXISTS client_uuid,
    DROP COLUMN IF EXISTS invoice_reference,
    DROP COLUMN IF EXISTS deleted_at,
    DROP COLUMN IF EXISTS deleted_by,
    DROP COLUMN IF EXISTS restored_at,
    DROP COLUMN IF EXISTS restored_by;

ALTER TABLE IF EXISTS inventory_items
    DROP COLUMN IF EXISTS deleted_at,
    DROP COLUMN IF EXISTS deleted_by,
    DROP COLUMN IF EXISTS restored_at,
    DROP COLUMN IF EXISTS restored_by;

ALTER TABLE IF EXISTS clients
    DROP COLUMN IF EXISTS deleted_at,
    DROP COLUMN IF EXISTS deleted_by,
    DROP COLUMN IF EXISTS restored_at,
    DROP COLUMN IF EXISTS restored_by;

ALTER TABLE IF EXISTS payments
    DROP COLUMN IF EXISTS updated_at;

ALTER TABLE IF EXISTS inventory_sales
    DROP COLUMN IF EXISTS client_uuid,
    DROP COLUMN IF EXISTS deleted_at,
    DROP COLUMN IF EXISTS deleted_by,
    DROP COLUMN IF EXISTS restored_at,
    DROP COLUMN IF EXISTS restored_by;

ALTER TABLE IF EXISTS inventory_sale_items
    DROP COLUMN IF EXISTS updated_at,
    DROP COLUMN IF EXISTS deleted_at,
    DROP COLUMN IF EXISTS deleted_by,
    DROP COLUMN IF EXISTS restored_at,
    DROP COLUMN IF EXISTS restored_by;

DROP FUNCTION IF EXISTS normalize_phone_digits(TEXT);
DROP FUNCTION IF EXISTS prevent_append_only_mutation();

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
    '025_phase2_core_restructure',
    'Phase 2 core restructure',
    'rolled_back',
    NOW(),
    NOW(),
    'database/migrations/025_phase2_core_restructure.rollback.sql',
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