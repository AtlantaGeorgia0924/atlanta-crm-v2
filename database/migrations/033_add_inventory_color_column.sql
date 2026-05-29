-- Add color specification column for inventory items.

ALTER TABLE inventory_items
    ADD COLUMN IF NOT EXISTS color TEXT;

COMMENT ON COLUMN inventory_items.color IS 'Color/finish for inventory item (e.g. Black, Silver, Midnight Green)';

CREATE INDEX IF NOT EXISTS idx_inventory_items_color ON inventory_items(color);
