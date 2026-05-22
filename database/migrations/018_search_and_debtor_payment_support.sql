-- Search performance and debtor allocation metadata support

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Global billing/service search accelerators.
CREATE INDEX IF NOT EXISTS idx_service_jobs_client_name_trgm
ON service_jobs USING gin (client_name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_service_jobs_phone_number_trgm
ON service_jobs USING gin (phone_number gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_service_jobs_service_name_trgm
ON service_jobs USING gin (service_name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_service_jobs_notes_trgm
ON service_jobs USING gin (notes gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_service_jobs_description_trgm
ON service_jobs USING gin (description gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_service_jobs_payment_status_service_date
ON service_jobs (payment_status, service_date DESC);

-- Inventory-assisted service search accelerators.
CREATE INDEX IF NOT EXISTS idx_inventory_items_item_name_trgm
ON inventory_items USING gin (item_name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_inventory_items_imei_trgm
ON inventory_items USING gin (imei gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_inventory_items_supplier_trgm
ON inventory_items USING gin (supplier gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_inventory_sale_items_source_inventory
ON inventory_sale_items (source_inventory_item_id);

CREATE INDEX IF NOT EXISTS idx_inventory_sale_items_service_job
ON inventory_sale_items (service_job_id);

-- Debtor payment allocation metadata (backward compatible with legacy inserts).
ALTER TABLE payments ADD COLUMN IF NOT EXISTS previous_balance NUMERIC(12,2);
ALTER TABLE payments ADD COLUMN IF NOT EXISTS new_balance NUMERIC(12,2);
ALTER TABLE payments ADD COLUMN IF NOT EXISTS performed_by TEXT;

CREATE INDEX IF NOT EXISTS idx_payments_billing_row_created
ON payments (billing_row_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_payments_performed_by_created
ON payments (performed_by, created_at DESC);
