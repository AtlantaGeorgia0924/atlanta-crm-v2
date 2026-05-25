-- Search performance and debtor allocation metadata support

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Global billing/service search accelerators.
DO $$
BEGIN
	IF EXISTS (
		SELECT 1 FROM information_schema.columns
		WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'client_name'
	) THEN
		EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_client_name_trgm ON service_jobs USING gin (client_name gin_trgm_ops)';
	END IF;

	IF EXISTS (
		SELECT 1 FROM information_schema.columns
		WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'phone_number'
	) THEN
		EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_phone_number_trgm ON service_jobs USING gin (phone_number gin_trgm_ops)';
	END IF;

	IF EXISTS (
		SELECT 1 FROM information_schema.columns
		WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'service_name'
	) THEN
		EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_service_name_trgm ON service_jobs USING gin (service_name gin_trgm_ops)';
	END IF;

	IF EXISTS (
		SELECT 1 FROM information_schema.columns
		WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'notes'
	) THEN
		EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_notes_trgm ON service_jobs USING gin (notes gin_trgm_ops)';
	END IF;

	IF EXISTS (
		SELECT 1 FROM information_schema.columns
		WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'description'
	) THEN
		EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_description_trgm ON service_jobs USING gin (description gin_trgm_ops)';
	END IF;

	IF EXISTS (
		SELECT 1 FROM information_schema.columns
		WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'payment_status'
	)
	AND EXISTS (
		SELECT 1 FROM information_schema.columns
		WHERE table_schema = 'public' AND table_name = 'service_jobs' AND column_name = 'service_date'
	) THEN
		EXECUTE 'CREATE INDEX IF NOT EXISTS idx_service_jobs_payment_status_service_date ON service_jobs (payment_status, service_date DESC)';
	END IF;
END $$;

-- Inventory-assisted service search accelerators.
DO $$
BEGIN
	IF EXISTS (
		SELECT 1 FROM information_schema.columns
		WHERE table_schema = 'public' AND table_name = 'inventory_items' AND column_name = 'item_name'
	) THEN
		EXECUTE 'CREATE INDEX IF NOT EXISTS idx_inventory_items_item_name_trgm ON inventory_items USING gin (item_name gin_trgm_ops)';
	END IF;

	IF EXISTS (
		SELECT 1 FROM information_schema.columns
		WHERE table_schema = 'public' AND table_name = 'inventory_items' AND column_name = 'imei'
	) THEN
		EXECUTE 'CREATE INDEX IF NOT EXISTS idx_inventory_items_imei_trgm ON inventory_items USING gin (imei gin_trgm_ops)';
	END IF;

	IF EXISTS (
		SELECT 1 FROM information_schema.columns
		WHERE table_schema = 'public' AND table_name = 'inventory_items' AND column_name = 'supplier'
	) THEN
		EXECUTE 'CREATE INDEX IF NOT EXISTS idx_inventory_items_supplier_trgm ON inventory_items USING gin (supplier gin_trgm_ops)';
	END IF;

	IF EXISTS (
		SELECT 1 FROM information_schema.columns
		WHERE table_schema = 'public' AND table_name = 'inventory_sale_items' AND column_name = 'source_inventory_item_id'
	) THEN
		EXECUTE 'CREATE INDEX IF NOT EXISTS idx_inventory_sale_items_source_inventory ON inventory_sale_items (source_inventory_item_id)';
	END IF;

	IF EXISTS (
		SELECT 1 FROM information_schema.columns
		WHERE table_schema = 'public' AND table_name = 'inventory_sale_items' AND column_name = 'service_job_id'
	) THEN
		EXECUTE 'CREATE INDEX IF NOT EXISTS idx_inventory_sale_items_service_job ON inventory_sale_items (service_job_id)';
	END IF;
END $$;

-- Debtor payment allocation metadata (backward compatible with legacy inserts).
DO $$
BEGIN
	IF to_regclass('public.payments') IS NOT NULL THEN
		EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS previous_balance NUMERIC(12,2)';
		EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS new_balance NUMERIC(12,2)';
		EXECUTE 'ALTER TABLE payments ADD COLUMN IF NOT EXISTS performed_by TEXT';

		IF EXISTS (
			SELECT 1 FROM information_schema.columns
			WHERE table_schema = 'public' AND table_name = 'payments' AND column_name = 'billing_row_id'
		) AND EXISTS (
			SELECT 1 FROM information_schema.columns
			WHERE table_schema = 'public' AND table_name = 'payments' AND column_name = 'created_at'
		) THEN
			EXECUTE 'CREATE INDEX IF NOT EXISTS idx_payments_billing_row_created ON payments (billing_row_id, created_at DESC)';
		END IF;

		IF EXISTS (
			SELECT 1 FROM information_schema.columns
			WHERE table_schema = 'public' AND table_name = 'payments' AND column_name = 'performed_by'
		) AND EXISTS (
			SELECT 1 FROM information_schema.columns
			WHERE table_schema = 'public' AND table_name = 'payments' AND column_name = 'created_at'
		) THEN
			EXECUTE 'CREATE INDEX IF NOT EXISTS idx_payments_performed_by_created ON payments (performed_by, created_at DESC)';
		END IF;
	END IF;
END $$;
