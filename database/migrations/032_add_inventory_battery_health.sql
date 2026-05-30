-- Add battery health percentage for inventory device metadata.
ALTER TABLE IF EXISTS inventory_items
ADD COLUMN IF NOT EXISTS battery_health numeric(5,2);

-- Keep values within valid range when present.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'inventory_items_battery_health_range_check'
  ) THEN
    ALTER TABLE inventory_items
    ADD CONSTRAINT inventory_items_battery_health_range_check
    CHECK (battery_health IS NULL OR (battery_health >= 0 AND battery_health <= 100));
  END IF;
END $$;
