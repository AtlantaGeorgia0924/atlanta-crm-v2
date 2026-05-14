-- Migration 005: Add IMEI columns to service_jobs and inventory_items
-- Run this in the Supabase SQL Editor: https://supabase.com/dashboard/project/_/sql

ALTER TABLE service_jobs
    ADD COLUMN IF NOT EXISTS imei TEXT;

ALTER TABLE inventory_items
    ADD COLUMN IF NOT EXISTS imei TEXT;

-- Optional: index for faster IMEI lookups during profit calculation
CREATE INDEX IF NOT EXISTS idx_service_jobs_imei ON service_jobs (imei)
    WHERE imei IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_inventory_items_imei ON inventory_items (imei)
    WHERE imei IS NOT NULL;
