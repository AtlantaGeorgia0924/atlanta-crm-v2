-- Add supplier phone, device condition, lock status, and unlock tracking to inventory_items.

ALTER TABLE inventory_items
    ADD COLUMN IF NOT EXISTS supplier_phone TEXT,
    ADD COLUMN IF NOT EXISTS condition TEXT,
    ADD COLUMN IF NOT EXISTS lock_status TEXT,
    ADD COLUMN IF NOT EXISTS previously_locked BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS unlock_method TEXT;

COMMENT ON COLUMN inventory_items.supplier_phone IS 'Normalized phone of the supplier/contact for this item';
COMMENT ON COLUMN inventory_items.condition IS 'Brand New | Open Box | Used - Clean | Used - Average | Used - Faulty | For Parts';
COMMENT ON COLUMN inventory_items.lock_status IS 'Factory Unlocked | Carrier Locked | iCloud Locked | MDM Locked | Unknown';
COMMENT ON COLUMN inventory_items.previously_locked IS 'Whether the device was locked at any point before purchase';
COMMENT ON COLUMN inventory_items.unlock_method IS 'RSIM | Official Unlock | Bypass | MDM Removal | Other';

CREATE INDEX IF NOT EXISTS idx_inventory_items_condition ON inventory_items(condition);
CREATE INDEX IF NOT EXISTS idx_inventory_items_lock_status ON inventory_items(lock_status);
