BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION prevent_append_only_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only; % is not allowed', TG_TABLE_NAME, TG_OP;
END;
$$;

ALTER TABLE IF EXISTS inventory_sales
    ADD COLUMN IF NOT EXISTS checkout_idempotency_key TEXT,
    ADD COLUMN IF NOT EXISTS transaction_reference TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_inventory_sales_checkout_idempotency_key
ON inventory_sales(checkout_idempotency_key)
WHERE checkout_idempotency_key IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_inventory_sales_transaction_reference
ON inventory_sales(transaction_reference)
WHERE transaction_reference IS NOT NULL;

ALTER TABLE IF EXISTS payments
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_payments_idempotency_key
ON payments(idempotency_key)
WHERE idempotency_key IS NOT NULL;

DROP TRIGGER IF EXISTS trg_payments_append_only ON payments;
CREATE TRIGGER trg_payments_append_only
BEFORE UPDATE OR DELETE ON payments
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

CREATE TABLE IF NOT EXISTS inventory_movement_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    inventory_item_id UUID NOT NULL REFERENCES inventory_items(id) ON DELETE CASCADE,
    movement_type TEXT NOT NULL,
    quantity_change NUMERIC(12,2) NOT NULL,
    quantity_before NUMERIC(12,2) NOT NULL,
    quantity_after NUMERIC(12,2) NOT NULL,
    reference_type TEXT,
    reference_id TEXT,
    transaction_reference TEXT,
    performed_by TEXT,
    note TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inventory_movement_history_item_created
ON inventory_movement_history(inventory_item_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_inventory_movement_history_transaction_reference
ON inventory_movement_history(transaction_reference);

CREATE TABLE IF NOT EXISTS stock_adjustment_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    inventory_item_id UUID NOT NULL REFERENCES inventory_items(id) ON DELETE CASCADE,
    adjustment_type TEXT NOT NULL,
    quantity_before NUMERIC(12,2) NOT NULL,
    quantity_after NUMERIC(12,2) NOT NULL,
    quantity_change NUMERIC(12,2) NOT NULL,
    reason TEXT,
    reference_type TEXT,
    reference_id TEXT,
    transaction_reference TEXT,
    performed_by TEXT,
    detail JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stock_adjustment_audit_item_created
ON stock_adjustment_audit(inventory_item_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_stock_adjustment_audit_transaction_reference
ON stock_adjustment_audit(transaction_reference);

CREATE OR REPLACE FUNCTION apply_service_payment_tx(
    p_service_job_id UUID,
    p_payment_amount NUMERIC,
    p_payment_method TEXT,
    p_payment_note TEXT,
    p_reference_no TEXT,
    p_payment_date DATE,
    p_applied_by TEXT,
    p_applied_by_name TEXT,
    p_idempotency_key TEXT DEFAULT NULL
)
RETURNS TABLE (
    payment_id UUID,
    reference_no TEXT,
    previous_balance NUMERIC,
    new_balance NUMERIC,
    previous_paid_amount NUMERIC,
    new_paid_amount NUMERIC,
    previous_status TEXT,
    new_status TEXT,
    payment_date DATE
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_job service_jobs%ROWTYPE;
    v_payment payments%ROWTYPE;
    v_total NUMERIC(18,2);
    v_amount NUMERIC(18,2);
    v_prev_paid NUMERIC(18,2);
    v_next_paid NUMERIC(18,2);
    v_prev_balance NUMERIC(18,2);
    v_next_balance NUMERIC(18,2);
    v_prev_status TEXT;
    v_next_status TEXT;
    v_reference TEXT;
    v_date DATE;
    v_note TEXT;
    v_method TEXT;
    v_applied_uuid UUID;
BEGIN
    IF p_idempotency_key IS NOT NULL AND BTRIM(p_idempotency_key) <> '' THEN
        SELECT * INTO v_payment
        FROM payments
        WHERE idempotency_key = BTRIM(p_idempotency_key)
        LIMIT 1;

        IF FOUND THEN
            RETURN QUERY
            SELECT
                v_payment.id,
                v_payment.reference_no,
                COALESCE(v_payment.previous_balance, 0),
                COALESCE(v_payment.new_balance, 0),
                COALESCE(v_payment.previous_paid_amount, 0),
                COALESCE(v_payment.new_paid_amount, 0),
                COALESCE(v_payment.previous_status, 'UNPAID'),
                COALESCE(v_payment.new_status, 'UNPAID'),
                COALESCE(v_payment.payment_date, CURRENT_DATE);
            RETURN;
        END IF;
    END IF;

    SELECT * INTO v_job
    FROM service_jobs
    WHERE id = p_service_job_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Invoice not found';
    END IF;

    v_total := GREATEST(COALESCE(v_job.amount_charged, 0), 0);
    v_prev_paid := GREATEST(COALESCE(v_job.paid_amount, 0), 0);
    v_prev_balance := GREATEST(v_total - v_prev_paid, 0);
    v_prev_status := UPPER(COALESCE(NULLIF(BTRIM(v_job.payment_status), ''), CASE WHEN v_prev_paid >= v_total AND v_total > 0 THEN 'PAID' WHEN v_prev_paid > 0 THEN 'PART PAYMENT' ELSE 'UNPAID' END));

    v_amount := ROUND(COALESCE(p_payment_amount, 0), 2);
    IF v_amount <= 0 THEN
        RAISE EXCEPTION 'Payment amount must be greater than zero';
    END IF;

    IF v_amount > v_prev_balance + 0.000001 THEN
        RAISE EXCEPTION 'Payment amount exceeds outstanding balance';
    END IF;

    v_next_paid := ROUND(LEAST(v_prev_paid + v_amount, v_total), 2);
    v_next_balance := ROUND(GREATEST(v_total - v_next_paid, 0), 2);
    v_next_status := CASE
        WHEN v_next_paid >= v_total AND v_total > 0 THEN 'PAID'
        WHEN v_next_paid > 0 THEN 'PART PAYMENT'
        ELSE 'UNPAID'
    END;

    v_reference := NULLIF(BTRIM(COALESCE(p_reference_no, '')), '');
    IF v_reference IS NULL THEN
        v_reference := CONCAT('ATL-PAY-', TO_CHAR(NOW(), 'YYYYMMDDHH24MISSMS'), '-', UPPER(SUBSTRING(MD5(gen_random_uuid()::TEXT), 1, 4)));
    END IF;

    v_date := COALESCE(p_payment_date, CURRENT_DATE);
    v_note := NULLIF(BTRIM(COALESCE(p_payment_note, '')), '');
    v_method := COALESCE(NULLIF(BTRIM(COALESCE(p_payment_method, '')), ''), 'cash');

    IF COALESCE(p_applied_by, '') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN
        v_applied_uuid := p_applied_by::UUID;
    ELSE
        v_applied_uuid := NULL;
    END IF;

    INSERT INTO payments (
        reference_no,
        idempotency_key,
        client_id,
        service_job_id,
        billing_row_id,
        client_name,
        client_phone,
        payment_amount,
        amount,
        payment_method,
        payment_note,
        notes,
        previous_balance,
        new_balance,
        previous_paid_amount,
        new_paid_amount,
        previous_status,
        new_status,
        applied_by,
        applied_by_name,
        performed_by,
        payment_date,
        is_reversed
    ) VALUES (
        v_reference,
        NULLIF(BTRIM(COALESCE(p_idempotency_key, '')), ''),
        CASE WHEN COALESCE(v_job.client_id, '') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN v_job.client_id::UUID ELSE NULL END,
        v_job.id,
        v_job.id,
        v_job.client_name,
        v_job.phone_number,
        v_amount,
        v_amount,
        v_method,
        v_note,
        v_note,
        v_prev_balance,
        v_next_balance,
        v_prev_paid,
        v_next_paid,
        v_prev_status,
        v_next_status,
        v_applied_uuid,
        NULLIF(BTRIM(COALESCE(p_applied_by_name, '')), ''),
        NULLIF(BTRIM(COALESCE(p_applied_by, '')), ''),
        v_date,
        FALSE
    ) RETURNING * INTO v_payment;

    UPDATE service_jobs
    SET paid_amount = v_next_paid,
        payment_status = v_next_status,
        paid_date = CASE WHEN v_next_status = 'PAID' THEN v_date ELSE NULL END,
        paid_at = CASE WHEN v_next_status = 'PAID' THEN NOW() ELSE NULL END,
        last_payment_by = NULLIF(BTRIM(COALESCE(p_applied_by, '')), ''),
        last_payment_by_name = NULLIF(BTRIM(COALESCE(p_applied_by_name, '')), ''),
        last_payment_at = NOW()
    WHERE id = v_job.id;

    RETURN QUERY
    SELECT v_payment.id, v_payment.reference_no, v_prev_balance, v_next_balance, v_prev_paid, v_next_paid, v_prev_status, v_next_status, v_date;
END;
$$;

CREATE OR REPLACE FUNCTION reverse_service_payment_tx(
    p_service_job_id UUID,
    p_reversal_amount NUMERIC,
    p_reversal_reason TEXT,
    p_reversed_by TEXT,
    p_reversed_by_name TEXT,
    p_reversal_date DATE,
    p_idempotency_key TEXT DEFAULT NULL
)
RETURNS TABLE (
    payment_id UUID,
    reference_no TEXT,
    previous_balance NUMERIC,
    new_balance NUMERIC,
    previous_paid_amount NUMERIC,
    new_paid_amount NUMERIC,
    previous_status TEXT,
    new_status TEXT,
    reversal_date DATE
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_job service_jobs%ROWTYPE;
    v_payment payments%ROWTYPE;
    v_total NUMERIC(18,2);
    v_amount NUMERIC(18,2);
    v_prev_paid NUMERIC(18,2);
    v_next_paid NUMERIC(18,2);
    v_prev_balance NUMERIC(18,2);
    v_next_balance NUMERIC(18,2);
    v_prev_status TEXT;
    v_next_status TEXT;
    v_reference TEXT;
    v_date DATE;
    v_reason TEXT;
    v_reversed_uuid UUID;
BEGIN
    IF p_idempotency_key IS NOT NULL AND BTRIM(p_idempotency_key) <> '' THEN
        SELECT * INTO v_payment
        FROM payments
        WHERE idempotency_key = BTRIM(p_idempotency_key)
        LIMIT 1;

        IF FOUND THEN
            RETURN QUERY
            SELECT
                v_payment.id,
                v_payment.reference_no,
                COALESCE(v_payment.previous_balance, 0),
                COALESCE(v_payment.new_balance, 0),
                COALESCE(v_payment.previous_paid_amount, 0),
                COALESCE(v_payment.new_paid_amount, 0),
                COALESCE(v_payment.previous_status, 'UNPAID'),
                COALESCE(v_payment.new_status, 'UNPAID'),
                COALESCE(v_payment.payment_date, CURRENT_DATE);
            RETURN;
        END IF;
    END IF;

    SELECT * INTO v_job
    FROM service_jobs
    WHERE id = p_service_job_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Invoice not found';
    END IF;

    v_total := GREATEST(COALESCE(v_job.amount_charged, 0), 0);
    v_prev_paid := GREATEST(COALESCE(v_job.paid_amount, 0), 0);
    v_prev_balance := GREATEST(v_total - v_prev_paid, 0);
    v_prev_status := UPPER(COALESCE(NULLIF(BTRIM(v_job.payment_status), ''), CASE WHEN v_prev_paid >= v_total AND v_total > 0 THEN 'PAID' WHEN v_prev_paid > 0 THEN 'PART PAYMENT' ELSE 'UNPAID' END));

    v_amount := ROUND(COALESCE(p_reversal_amount, 0), 2);
    IF v_amount <= 0 THEN
        RAISE EXCEPTION 'Reversal amount must be greater than zero';
    END IF;

    IF v_amount > v_prev_paid + 0.000001 THEN
        RAISE EXCEPTION 'Reversal exceeds paid amount';
    END IF;

    v_next_paid := ROUND(GREATEST(v_prev_paid - v_amount, 0), 2);
    v_next_balance := ROUND(GREATEST(v_total - v_next_paid, 0), 2);
    v_next_status := CASE
        WHEN v_next_paid >= v_total AND v_total > 0 THEN 'PAID'
        WHEN v_next_paid > 0 THEN 'PART PAYMENT'
        ELSE 'UNPAID'
    END;

    v_reference := CONCAT('ATL-REV-', TO_CHAR(NOW(), 'YYYYMMDDHH24MISSMS'), '-', UPPER(SUBSTRING(MD5(gen_random_uuid()::TEXT), 1, 4)));
    v_date := COALESCE(p_reversal_date, CURRENT_DATE);
    v_reason := COALESCE(NULLIF(BTRIM(COALESCE(p_reversal_reason, '')), ''), 'Payment reversal');

    IF COALESCE(p_reversed_by, '') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN
        v_reversed_uuid := p_reversed_by::UUID;
    ELSE
        v_reversed_uuid := NULL;
    END IF;

    INSERT INTO payments (
        reference_no,
        idempotency_key,
        client_id,
        service_job_id,
        billing_row_id,
        client_name,
        client_phone,
        payment_amount,
        amount,
        payment_method,
        payment_note,
        notes,
        previous_balance,
        new_balance,
        previous_paid_amount,
        new_paid_amount,
        previous_status,
        new_status,
        applied_by,
        applied_by_name,
        performed_by,
        payment_date,
        is_reversed,
        reversed_at,
        reversed_by,
        reversal_reason
    ) VALUES (
        v_reference,
        NULLIF(BTRIM(COALESCE(p_idempotency_key, '')), ''),
        CASE WHEN COALESCE(v_job.client_id, '') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN v_job.client_id::UUID ELSE NULL END,
        v_job.id,
        v_job.id,
        v_job.client_name,
        v_job.phone_number,
        -v_amount,
        -v_amount,
        'reversal',
        v_reason,
        v_reason,
        v_prev_balance,
        v_next_balance,
        v_prev_paid,
        v_next_paid,
        v_prev_status,
        v_next_status,
        v_reversed_uuid,
        NULLIF(BTRIM(COALESCE(p_reversed_by_name, '')), ''),
        NULLIF(BTRIM(COALESCE(p_reversed_by, '')), ''),
        v_date,
        TRUE,
        NOW(),
        v_reversed_uuid,
        v_reason
    ) RETURNING * INTO v_payment;

    UPDATE service_jobs
    SET paid_amount = v_next_paid,
        payment_status = v_next_status,
        paid_date = CASE WHEN v_next_status = 'PAID' THEN v_date ELSE NULL END,
        paid_at = CASE WHEN v_next_status = 'PAID' THEN NOW() ELSE NULL END,
        last_payment_by = NULLIF(BTRIM(COALESCE(p_reversed_by, '')), ''),
        last_payment_by_name = NULLIF(BTRIM(COALESCE(p_reversed_by_name, '')), ''),
        last_payment_at = NOW()
    WHERE id = v_job.id;

    RETURN QUERY
    SELECT v_payment.id, v_payment.reference_no, v_prev_balance, v_next_balance, v_prev_paid, v_next_paid, v_prev_status, v_next_status, v_date;
END;
$$;

CREATE OR REPLACE FUNCTION checkout_inventory_cart_tx(
    p_items JSONB,
    p_client_id TEXT,
    p_client_name TEXT,
    p_client_phone TEXT,
    p_amount_paid NUMERIC,
    p_payment_method TEXT,
    p_discount NUMERIC,
    p_notes TEXT,
    p_sold_by TEXT,
    p_idempotency_key TEXT
)
RETURNS TABLE (
    sale_id UUID,
    transaction_reference TEXT,
    payment_status TEXT,
    total_amount NUMERIC,
    paid_amount NUMERIC,
    balance NUMERIC,
    item_count INTEGER,
    service_job_ids TEXT
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_existing inventory_sales%ROWTYPE;
    v_existing_jobs TEXT;
    v_item JSONB;
    v_item_row inventory_items%ROWTYPE;
    v_item_id UUID;
    v_qty NUMERIC(12,2);
    v_unit_price NUMERIC(14,2);
    v_unit_cost NUMERIC(14,2);
    v_qty_before NUMERIC(12,2);
    v_qty_after NUMERIC(12,2);
    v_line_total NUMERIC(14,2);
    v_line_cost NUMERIC(14,2);
    v_line_profit NUMERIC(14,2);
    v_line_discount NUMERIC(14,2);
    v_line_paid NUMERIC(14,2);
    v_line_status TEXT;
    v_subtotal NUMERIC(14,2) := 0;
    v_total_cost NUMERIC(14,2) := 0;
    v_discount NUMERIC(14,2);
    v_total NUMERIC(14,2);
    v_paid NUMERIC(14,2);
    v_balance NUMERIC(14,2);
    v_status TEXT;
    v_sale_id UUID;
    v_sale_item_id UUID;
    v_service_job_id UUID;
    v_reference TEXT;
    v_remaining_paid NUMERIC(14,2);
    v_service_ids UUID[] := ARRAY[]::UUID[];
    v_items JSONB[] := ARRAY[]::JSONB[];
    v_idx INTEGER := 0;
BEGIN
    IF p_items IS NULL OR jsonb_typeof(p_items) <> 'array' OR jsonb_array_length(p_items) = 0 THEN
        RAISE EXCEPTION 'Cart is empty';
    END IF;

    IF NULLIF(BTRIM(COALESCE(p_client_name, '')), '') IS NULL THEN
        RAISE EXCEPTION 'Buyer/client name is required';
    END IF;

    IF NULLIF(BTRIM(COALESCE(p_idempotency_key, '')), '') IS NULL THEN
        RAISE EXCEPTION 'idempotency_key is required';
    END IF;

    SELECT * INTO v_existing
    FROM inventory_sales
    WHERE checkout_idempotency_key = BTRIM(p_idempotency_key)
    LIMIT 1;

    IF FOUND THEN
        SELECT COALESCE(string_agg(service_job_id::TEXT, ','), '') INTO v_existing_jobs
        FROM inventory_sale_items
        WHERE sale_id = v_existing.id;

        RETURN QUERY
        SELECT
            v_existing.id,
            COALESCE(v_existing.transaction_reference, v_existing.invoice_reference),
            COALESCE(v_existing.payment_status, 'UNPAID'),
            COALESCE(v_existing.amount_charged, 0),
            COALESCE(v_existing.paid_amount, 0),
            COALESCE(v_existing.balance, 0),
            COALESCE((SELECT COUNT(*)::INT FROM inventory_sale_items WHERE sale_id = v_existing.id), 0),
            v_existing_jobs;
        RETURN;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (
            SELECT (elem->>'item_id') AS item_id, COUNT(*) AS c
            FROM jsonb_array_elements(p_items) AS elem
            GROUP BY (elem->>'item_id')
            HAVING COUNT(*) > 1
        ) dup
    ) THEN
        RAISE EXCEPTION 'Duplicate cart items are not allowed';
    END IF;

    -- Lock inventory rows in deterministic order to reduce deadlock risk.
    FOR v_item IN
        SELECT jsonb_build_object(
            'item_id', req.item_id,
            'quantity', req.quantity,
            'unit_price', req.unit_price
        )
        FROM jsonb_to_recordset(p_items) AS req(item_id TEXT, quantity NUMERIC, unit_price NUMERIC)
        ORDER BY req.item_id::UUID
    LOOP
        v_item_id := NULLIF(BTRIM(COALESCE(v_item->>'item_id', '')), '')::UUID;
        v_qty := ROUND(COALESCE((v_item->>'quantity')::NUMERIC, 0), 2);
        v_unit_price := ROUND(COALESCE((v_item->>'unit_price')::NUMERIC, 0), 2);

        IF v_qty <= 0 THEN
            RAISE EXCEPTION 'Quantity must be greater than zero';
        END IF;

        SELECT * INTO v_item_row
        FROM inventory_items
        WHERE id = v_item_id
        FOR UPDATE;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'Inventory item not found';
        END IF;

        v_qty_before := COALESCE(v_item_row.quantity, 0);
        IF v_qty_before < v_qty THEN
            RAISE EXCEPTION 'Insufficient stock for % (remaining %, requested %)', COALESCE(v_item_row.item_name, 'Unknown Item'), v_qty_before, v_qty;
        END IF;

        IF v_unit_price <= 0 THEN
            v_unit_price := ROUND(COALESCE(v_item_row.selling_price, 0), 2);
        END IF;
        IF v_unit_price <= 0 THEN
            RAISE EXCEPTION 'Selling price must be greater than zero for %', COALESCE(v_item_row.item_name, 'Unknown Item');
        END IF;

        v_unit_cost := ROUND(COALESCE(v_item_row.cost_price, 0), 2);
        v_line_total := ROUND(v_qty * v_unit_price, 2);
        v_line_cost := ROUND(v_qty * v_unit_cost, 2);

        v_subtotal := ROUND(v_subtotal + v_line_total, 2);
        v_total_cost := ROUND(v_total_cost + v_line_cost, 2);

        v_items := array_append(v_items, jsonb_build_object(
            'inventory_item_id', v_item_row.id,
            'item_name', v_item_row.item_name,
            'qty', v_qty,
            'qty_before', v_qty_before,
            'unit_price', v_unit_price,
            'unit_cost', v_unit_cost,
            'line_total', v_line_total,
            'line_cost', v_line_cost,
            'imei', v_item_row.imei,
            'sku', v_item_row.sku,
            'serial_number', v_item_row.serial_number,
            'condition', v_item_row.condition,
            'lock_status', v_item_row.lock_status,
            'unlock_method', v_item_row.unlock_method
        ));
    END LOOP;

    v_discount := ROUND(LEAST(GREATEST(COALESCE(p_discount, 0), 0), v_subtotal), 2);
    v_total := ROUND(v_subtotal - v_discount, 2);
    v_paid := ROUND(LEAST(GREATEST(COALESCE(p_amount_paid, 0), 0), v_total), 2);
    v_balance := ROUND(v_total - v_paid, 2);
    v_status := CASE
        WHEN v_paid <= 0 THEN 'UNPAID'
        WHEN v_paid < v_total THEN 'PART PAYMENT'
        ELSE 'PAID'
    END;

    v_reference := CONCAT('ATL-CART-', TO_CHAR(NOW(), 'YYYYMMDDHH24MISSMS'), '-', UPPER(SUBSTRING(MD5(gen_random_uuid()::TEXT), 1, 5)));

    INSERT INTO inventory_sales (
        client_id,
        client_name,
        client_phone,
        payment_status,
        amount_charged,
        paid_amount,
        balance,
        total_profit,
        notes,
        sold_by,
        sold_at,
        payment_method,
        discount_amount,
        invoice_reference,
        transaction_reference,
        checkout_idempotency_key
    ) VALUES (
        NULLIF(BTRIM(COALESCE(p_client_id, '')), ''),
        BTRIM(p_client_name),
        NULLIF(BTRIM(COALESCE(p_client_phone, '')), ''),
        v_status,
        v_total,
        v_paid,
        v_balance,
        ROUND(v_total - v_total_cost, 2),
        NULLIF(BTRIM(COALESCE(p_notes, '')), ''),
        NULLIF(BTRIM(COALESCE(p_sold_by, '')), ''),
        NOW(),
        COALESCE(NULLIF(BTRIM(COALESCE(p_payment_method, '')), ''), 'cash'),
        v_discount,
        v_reference,
        v_reference,
        BTRIM(p_idempotency_key)
    ) RETURNING id INTO v_sale_id;

    v_remaining_paid := v_paid;

    FOREACH v_item IN ARRAY v_items
    LOOP
        v_idx := v_idx + 1;
        v_item_id := (v_item->>'inventory_item_id')::UUID;
        v_qty := ROUND((v_item->>'qty')::NUMERIC, 2);
        v_qty_before := ROUND((v_item->>'qty_before')::NUMERIC, 2);
        v_unit_price := ROUND((v_item->>'unit_price')::NUMERIC, 2);
        v_unit_cost := ROUND((v_item->>'unit_cost')::NUMERIC, 2);
        v_line_total := ROUND((v_item->>'line_total')::NUMERIC, 2);
        v_line_cost := ROUND((v_item->>'line_cost')::NUMERIC, 2);

        IF v_subtotal > 0 THEN
            v_line_discount := ROUND(v_discount * (v_line_total / v_subtotal), 2);
        ELSE
            v_line_discount := 0;
        END IF;

        v_line_total := ROUND(v_line_total - v_line_discount, 2);
        v_line_paid := ROUND(LEAST(v_remaining_paid, v_line_total), 2);
        v_remaining_paid := ROUND(v_remaining_paid - v_line_paid, 2);
        v_line_status := CASE
            WHEN v_line_paid <= 0 THEN 'UNPAID'
            WHEN v_line_paid < v_line_total THEN 'PART PAYMENT'
            ELSE 'PAID'
        END;

        v_qty_after := ROUND(v_qty_before - v_qty, 2);
        IF v_qty_after < 0 THEN
            RAISE EXCEPTION 'Negative stock prevented for item %', v_item_id;
        END IF;

        UPDATE inventory_items
        SET quantity = v_qty_after,
            payment_status = CASE WHEN v_qty_after <= 0 THEN 'SOLD' ELSE payment_status END,
            updated_at = NOW(),
            sync_dirty = TRUE,
            sync_source = 'app'
        WHERE id = v_item_id;

        INSERT INTO service_jobs (
            id,
            client_id,
            client_name,
            phone_number,
            service_name,
            description,
            quantity,
            amount_charged,
            expense_amount,
            service_expense_amount,
            payment_status,
            paid_amount,
            paid_date,
            paid_at,
            service_date,
            due_date,
            notes,
            imei,
            serial_number,
            device_model,
            condition,
            lock_status,
            unlock_method,
            created_by,
            created_by_name,
            created_by_role,
            last_edited_by,
            last_edited_by_name,
            last_edited_at,
            assigned_staff_id,
            assigned_staff_name,
            source_created_at,
            source_updated_at,
            sync_dirty,
            sync_source
        ) VALUES (
            gen_random_uuid(),
            NULLIF(BTRIM(COALESCE(p_client_id, '')), ''),
            BTRIM(p_client_name),
            NULLIF(BTRIM(COALESCE(p_client_phone, '')), ''),
            CONCAT('Sale: ', COALESCE(v_item->>'item_name', 'Inventory Item')),
            CONCAT('Inventory cart checkout: ', COALESCE(v_item->>'item_name', 'Inventory Item'), ' x ', v_qty),
            v_qty,
            v_line_total,
            v_line_cost,
            v_line_cost,
            v_line_status,
            v_line_paid,
            CASE WHEN v_line_status = 'PAID' THEN CURRENT_DATE ELSE NULL END,
            CASE WHEN v_line_status = 'PAID' THEN NOW() ELSE NULL END,
            CURRENT_DATE,
            CURRENT_DATE,
            NULLIF(BTRIM(COALESCE(p_notes, '')), ''),
            COALESCE(NULLIF(BTRIM(COALESCE(v_item->>'imei', '')), ''), NULLIF(BTRIM(COALESCE(v_item->>'sku', '')), '')),
            NULLIF(BTRIM(COALESCE(v_item->>'serial_number', '')), ''),
            NULLIF(BTRIM(COALESCE(v_item->>'item_name', '')), ''),
            NULLIF(BTRIM(COALESCE(v_item->>'condition', '')), ''),
            NULLIF(BTRIM(COALESCE(v_item->>'lock_status', '')), ''),
            NULLIF(BTRIM(COALESCE(v_item->>'unlock_method', '')), ''),
            NULLIF(BTRIM(COALESCE(p_sold_by, '')), ''),
            NULL,
            'staff',
            NULLIF(BTRIM(COALESCE(p_sold_by, '')), ''),
            NULL,
            NOW(),
            NULLIF(BTRIM(COALESCE(p_sold_by, '')), ''),
            NULL,
            NOW(),
            NOW(),
            TRUE,
            'app'
        ) RETURNING id INTO v_service_job_id;

        v_service_ids := array_append(v_service_ids, v_service_job_id);
        v_line_profit := ROUND(v_line_total - v_line_cost, 2);

        INSERT INTO inventory_sale_items (
            sale_id,
            source_inventory_item_id,
            service_job_id,
            quantity,
            unit_price,
            unit_cost,
            amount_charged,
            profit,
            notes,
            sold_by,
            sold_at
        ) VALUES (
            v_sale_id,
            v_item_id,
            v_service_job_id,
            v_qty,
            v_unit_price,
            v_unit_cost,
            v_line_total,
            v_line_profit,
            NULLIF(BTRIM(COALESCE(p_notes, '')), ''),
            NULLIF(BTRIM(COALESCE(p_sold_by, '')), ''),
            NOW()
        ) RETURNING id INTO v_sale_item_id;

        INSERT INTO inventory_transactions (
            inventory_item_id,
            action,
            quantity_change,
            quantity_before,
            quantity_after,
            related_sale_id,
            related_sale_item_id,
            performed_by,
            note
        ) VALUES (
            v_item_id,
            'SALE',
            -v_qty,
            v_qty_before,
            v_qty_after,
            v_sale_id,
            v_sale_item_id,
            NULLIF(BTRIM(COALESCE(p_sold_by, '')), ''),
            'Cart checkout sale'
        );

        INSERT INTO inventory_movement_history (
            inventory_item_id,
            movement_type,
            quantity_change,
            quantity_before,
            quantity_after,
            reference_type,
            reference_id,
            transaction_reference,
            performed_by,
            note,
            metadata
        ) VALUES (
            v_item_id,
            'SALE',
            -v_qty,
            v_qty_before,
            v_qty_after,
            'inventory_sale_item',
            v_sale_item_id::TEXT,
            v_reference,
            NULLIF(BTRIM(COALESCE(p_sold_by, '')), ''),
            'Inventory deducted during cart checkout',
            jsonb_build_object('sale_id', v_sale_id::TEXT, 'service_job_id', v_service_job_id::TEXT)
        );

        INSERT INTO stock_adjustment_audit (
            inventory_item_id,
            adjustment_type,
            quantity_before,
            quantity_after,
            quantity_change,
            reason,
            reference_type,
            reference_id,
            transaction_reference,
            performed_by,
            detail
        ) VALUES (
            v_item_id,
            'CART_CHECKOUT_DEDUCTION',
            v_qty_before,
            v_qty_after,
            -v_qty,
            'Cart checkout stock deduction',
            'inventory_sale_item',
            v_sale_item_id::TEXT,
            v_reference,
            NULLIF(BTRIM(COALESCE(p_sold_by, '')), ''),
            jsonb_build_object(
                'sale_id', v_sale_id::TEXT,
                'service_job_id', v_service_job_id::TEXT,
                'line_paid', v_line_paid,
                'line_status', v_line_status,
                'line_discount', v_line_discount
            )
        );

        IF v_line_paid > 0 THEN
            INSERT INTO payments (
                reference_no,
                service_job_id,
                billing_row_id,
                client_name,
                client_phone,
                payment_amount,
                amount,
                payment_method,
                payment_note,
                notes,
                previous_balance,
                new_balance,
                previous_paid_amount,
                new_paid_amount,
                previous_status,
                new_status,
                performed_by,
                payment_date,
                is_reversed
            ) VALUES (
                CONCAT(v_reference, '-P', LPAD(v_idx::TEXT, 2, '0')),
                v_service_job_id,
                v_service_job_id,
                BTRIM(p_client_name),
                NULLIF(BTRIM(COALESCE(p_client_phone, '')), ''),
                v_line_paid,
                v_line_paid,
                COALESCE(NULLIF(BTRIM(COALESCE(p_payment_method, '')), ''), 'cash'),
                'Checkout payment',
                NULLIF(BTRIM(COALESCE(p_notes, '')), ''),
                ROUND(v_line_total - v_line_paid, 2) + v_line_paid,
                ROUND(v_line_total - v_line_paid, 2),
                0,
                v_line_paid,
                'UNPAID',
                v_line_status,
                NULLIF(BTRIM(COALESCE(p_sold_by, '')), ''),
                CURRENT_DATE,
                FALSE
            );
        END IF;
    END LOOP;

    INSERT INTO crm_audit_log (
        action,
        entity_type,
        entity_id,
        performed_by,
        detail
    ) VALUES (
        'inventory_cart_checkout',
        'inventory_sale',
        v_sale_id::TEXT,
        NULLIF(BTRIM(COALESCE(p_sold_by, '')), ''),
        jsonb_build_object(
            'transaction_reference', v_reference,
            'item_count', cardinality(v_service_ids),
            'amount_charged', v_total,
            'paid_amount', v_paid,
            'payment_status', v_status,
            'service_job_ids', v_service_ids
        )
    );

    RETURN QUERY
    SELECT
        v_sale_id,
        v_reference,
        v_status,
        v_total,
        v_paid,
        v_balance,
        cardinality(v_service_ids),
        COALESCE(array_to_string(v_service_ids, ','), '');
END;
$$;

CREATE OR REPLACE FUNCTION cleanup_stale_idempotency_keys(
    p_older_than INTERVAL DEFAULT INTERVAL '180 days'
)
RETURNS TABLE (
    payments_cleared BIGINT,
    checkouts_cleared BIGINT
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_payments BIGINT := 0;
    v_checkouts BIGINT := 0;
BEGIN
    UPDATE payments
    SET idempotency_key = NULL
    WHERE idempotency_key IS NOT NULL
      AND created_at < NOW() - p_older_than;
    GET DIAGNOSTICS v_payments = ROW_COUNT;

    UPDATE inventory_sales
    SET checkout_idempotency_key = NULL
    WHERE checkout_idempotency_key IS NOT NULL
      AND COALESCE(sold_at, created_at, NOW()) < NOW() - p_older_than;
    GET DIAGNOSTICS v_checkouts = ROW_COUNT;

    RETURN QUERY SELECT v_payments, v_checkouts;
END;
$$;

CREATE OR REPLACE FUNCTION reverse_inventory_sale(
    p_sale_item_id UUID,
    p_reversed_by TEXT,
    p_reason TEXT
)
RETURNS TABLE (
    sale_item_id UUID,
    inventory_item_id UUID,
    restored_quantity NUMERIC,
    new_inventory_quantity NUMERIC,
    service_job_id UUID
) LANGUAGE plpgsql AS $$
DECLARE
    v_sale_item inventory_sale_items%ROWTYPE;
    v_inventory inventory_items%ROWTYPE;
    v_qty_before NUMERIC(12,2);
    v_qty_after NUMERIC(12,2);
    v_reference TEXT;
BEGIN
    SELECT * INTO v_sale_item
    FROM inventory_sale_items
    WHERE id = p_sale_item_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Sale item not found';
    END IF;

    IF COALESCE(v_sale_item.is_reversed, FALSE) THEN
        RAISE EXCEPTION 'Sale item already reversed';
    END IF;

    SELECT * INTO v_inventory
    FROM inventory_items
    WHERE id = v_sale_item.source_inventory_item_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Source inventory item not found';
    END IF;

    SELECT COALESCE(transaction_reference, invoice_reference) INTO v_reference
    FROM inventory_sales
    WHERE id = v_sale_item.sale_id;

    v_qty_before := COALESCE(v_inventory.quantity, 0);
    v_qty_after := v_qty_before + COALESCE(v_sale_item.quantity, 0);

    UPDATE inventory_items
    SET quantity = v_qty_after,
        payment_status = CASE WHEN v_qty_after > 0 AND UPPER(COALESCE(payment_status, '')) = 'SOLD' THEN 'AVAILABLE' ELSE payment_status END,
        updated_at = NOW()
    WHERE id = v_inventory.id;

    UPDATE inventory_sale_items
    SET is_reversed = TRUE,
        reversed_at = NOW(),
        reversed_by = p_reversed_by,
        notes = TRIM(CONCAT(COALESCE(notes, ''), CASE WHEN p_reason IS NOT NULL AND TRIM(p_reason) <> '' THEN ' | Reversal reason: ' || TRIM(p_reason) ELSE '' END))
    WHERE id = p_sale_item_id;

    UPDATE inventory_sales
    SET is_reversed = TRUE,
        reversed_at = NOW(),
        reversed_by = p_reversed_by,
        updated_at = NOW()
    WHERE id = v_sale_item.sale_id;

    IF v_sale_item.service_job_id IS NOT NULL THEN
        UPDATE service_jobs
        SET is_return = TRUE,
            payment_status = 'RETURNED',
            source_updated_at = NOW(),
            notes = TRIM(CONCAT(COALESCE(notes, ''), CASE WHEN p_reason IS NOT NULL AND TRIM(p_reason) <> '' THEN ' | Returned: ' || TRIM(p_reason) ELSE ' | Returned' END))
        WHERE id = v_sale_item.service_job_id;
    END IF;

    INSERT INTO inventory_transactions (
        inventory_item_id,
        action,
        quantity_change,
        quantity_before,
        quantity_after,
        related_sale_id,
        related_sale_item_id,
        performed_by,
        note
    ) VALUES (
        v_inventory.id,
        'SALE_REVERSAL',
        COALESCE(v_sale_item.quantity, 0),
        v_qty_before,
        v_qty_after,
        v_sale_item.sale_id,
        v_sale_item.id,
        p_reversed_by,
        p_reason
    );

    INSERT INTO inventory_movement_history (
        inventory_item_id,
        movement_type,
        quantity_change,
        quantity_before,
        quantity_after,
        reference_type,
        reference_id,
        transaction_reference,
        performed_by,
        note,
        metadata
    ) VALUES (
        v_inventory.id,
        'SALE_REVERSAL',
        COALESCE(v_sale_item.quantity, 0),
        v_qty_before,
        v_qty_after,
        'inventory_sale_item',
        v_sale_item.id::TEXT,
        v_reference,
        p_reversed_by,
        COALESCE(NULLIF(BTRIM(p_reason), ''), 'Sale reversal'),
        jsonb_build_object('sale_id', v_sale_item.sale_id::TEXT, 'service_job_id', v_sale_item.service_job_id::TEXT)
    );

    INSERT INTO stock_adjustment_audit (
        inventory_item_id,
        adjustment_type,
        quantity_before,
        quantity_after,
        quantity_change,
        reason,
        reference_type,
        reference_id,
        transaction_reference,
        performed_by,
        detail
    ) VALUES (
        v_inventory.id,
        'SALE_REVERSAL_RESTORE',
        v_qty_before,
        v_qty_after,
        COALESCE(v_sale_item.quantity, 0),
        COALESCE(NULLIF(BTRIM(p_reason), ''), 'Sale reversal inventory restoration'),
        'inventory_sale_item',
        v_sale_item.id::TEXT,
        v_reference,
        p_reversed_by,
        jsonb_build_object('sale_id', v_sale_item.sale_id::TEXT, 'service_job_id', v_sale_item.service_job_id::TEXT)
    );

    INSERT INTO crm_audit_log (
        action,
        entity_type,
        entity_id,
        performed_by,
        before_value,
        after_value,
        detail
    ) VALUES (
        'inventory_sale_reversed',
        'inventory_sale_item',
        v_sale_item.id::TEXT,
        p_reversed_by,
        jsonb_build_object('inventory_item_id', v_inventory.id::TEXT, 'quantity', v_qty_before, 'is_reversed', FALSE),
        jsonb_build_object('inventory_item_id', v_inventory.id::TEXT, 'quantity', v_qty_after, 'is_reversed', TRUE),
        jsonb_build_object(
            'sale_id', v_sale_item.sale_id::TEXT,
            'service_job_id', v_sale_item.service_job_id::TEXT,
            'reason', p_reason,
            'transaction_reference', v_reference
        )
    );

    RETURN QUERY SELECT v_sale_item.id, v_inventory.id, COALESCE(v_sale_item.quantity, 0), v_qty_after, v_sale_item.service_job_id;
END;
$$;

INSERT INTO migration_version_log (
    migration_version,
    description,
    status,
    applied_at,
    rollback_reference,
    applied_by,
    metadata
)
VALUES (
    '026_transaction_safety_hardening',
    'Transaction safety hardening for checkout and payments',
    'applied',
    NOW(),
    'database/migrations/026_transaction_safety_hardening.rollback.sql',
    CURRENT_USER,
    jsonb_build_object(
        'validation_sql', 'database/validation/026_transaction_safety_hardening_validation.sql',
        'tables', jsonb_build_array('inventory_movement_history', 'stock_adjustment_audit'),
        'functions', jsonb_build_array('checkout_inventory_cart_tx', 'apply_service_payment_tx', 'reverse_service_payment_tx')
    )
)
ON CONFLICT (migration_version) DO UPDATE
SET description = EXCLUDED.description,
    status = 'applied',
    applied_at = EXCLUDED.applied_at,
    rolled_back_at = NULL,
    rollback_reference = EXCLUDED.rollback_reference,
    applied_by = EXCLUDED.applied_by,
    metadata = migration_version_log.metadata || EXCLUDED.metadata;

COMMIT;
