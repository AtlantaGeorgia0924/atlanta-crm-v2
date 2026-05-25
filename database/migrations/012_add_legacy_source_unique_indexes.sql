-- Ensure incremental sync keys are indexed and unique where supported.
-- Uses partial unique indexes so null legacy_source_id values are allowed.

CREATE UNIQUE INDEX IF NOT EXISTS ux_clients_legacy_source_id
ON clients (legacy_source_id)
WHERE legacy_source_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_manual_expenses_legacy_source_id
ON manual_expenses (legacy_source_id)
WHERE legacy_source_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_cashflow_summary_legacy_source_id
ON cashflow_summary (legacy_source_id)
WHERE legacy_source_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_allowance_withdrawals_legacy_source_id
ON allowance_withdrawals (legacy_source_id)
WHERE legacy_source_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_inventory_items_legacy_source_id
ON inventory_items (legacy_source_id);

CREATE INDEX IF NOT EXISTS idx_service_jobs_legacy_source_id
ON service_jobs (legacy_source_id);
