-- Add storage specification column for inventory device capacity (e.g., 64GB, 128GB).

ALTER TABLE inventory_items
    ADD COLUMN IF NOT EXISTS storage TEXT;

COMMENT ON COLUMN inventory_items.storage IS 'Storage capacity/specification for inventory item (e.g. 64GB, 128GB, 1TB)';

CREATE INDEX IF NOT EXISTS idx_inventory_items_storage ON inventory_items(storage);
