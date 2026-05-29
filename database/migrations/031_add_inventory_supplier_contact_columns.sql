-- Add supplier profile fields to inventory items so existing and future records can
-- store supplier details without relying on description parsing.

ALTER TABLE inventory_items
    ADD COLUMN IF NOT EXISTS supplier TEXT,
    ADD COLUMN IF NOT EXISTS supplier_phone TEXT,
    ADD COLUMN IF NOT EXISTS supplier_contact TEXT;

COMMENT ON COLUMN inventory_items.supplier IS 'Supplier name for this inventory item';
COMMENT ON COLUMN inventory_items.supplier_phone IS 'Normalized supplier phone number';
COMMENT ON COLUMN inventory_items.supplier_contact IS 'Supplier contact person (if different from supplier name)';

-- Backfill supplier details from legacy description markers when present.
UPDATE inventory_items
SET supplier = NULLIF(TRIM((REGEXP_MATCHES(description, '(?i)(?:^|\|)\s*(?:supplier|vendor|seller)\s*:\s*([^|]+)'))[1]), '')
WHERE (supplier IS NULL OR TRIM(supplier) = '')
  AND description IS NOT NULL
  AND description ~* '(?:supplier|vendor|seller)\s*:';

UPDATE inventory_items
SET supplier_phone = NULLIF(REGEXP_REPLACE(COALESCE((REGEXP_MATCHES(description, '(?i)(?:supplier\s*phone|contact\s*phone|phone)\s*:\s*([^|]+)'))[1], ''), '\\D', '', 'g'), '')
WHERE (supplier_phone IS NULL OR TRIM(supplier_phone) = '')
  AND description IS NOT NULL
  AND description ~* '(?:supplier\s*phone|contact\s*phone|phone)\s*:';

UPDATE inventory_items
SET supplier_contact = NULLIF(TRIM((REGEXP_MATCHES(description, '(?i)(?:supplier\s*contact|contact\s*person)\s*:\s*([^|]+)'))[1]), '')
WHERE (supplier_contact IS NULL OR TRIM(supplier_contact) = '')
  AND description IS NOT NULL
  AND description ~* '(?:supplier\s*contact|contact\s*person)\s*:';

CREATE INDEX IF NOT EXISTS idx_inventory_items_supplier ON inventory_items (supplier);
CREATE INDEX IF NOT EXISTS idx_inventory_items_supplier_phone ON inventory_items (supplier_phone);
