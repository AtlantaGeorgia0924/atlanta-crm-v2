-- Add optional service expense tracking for service jobs.
-- notes may already exist in some environments, so guard with IF NOT EXISTS.

ALTER TABLE service_jobs
  ADD COLUMN IF NOT EXISTS notes text;

ALTER TABLE service_jobs
  ADD COLUMN IF NOT EXISTS service_expense numeric(18,2) DEFAULT 0;

UPDATE service_jobs
SET service_expense = 0
WHERE service_expense IS NULL;
