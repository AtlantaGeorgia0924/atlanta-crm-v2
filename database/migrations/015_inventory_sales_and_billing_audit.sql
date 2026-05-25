CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Unified audit log for inventory and invoice/payment operations.
CREATE TABLE IF NOT EXISTS crm_audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    performed_by TEXT,
    before_value JSONB,
    after_value JSONB,
    detail JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crm_audit_action ON crm_audit_log(action);
CREATE INDEX IF NOT EXISTS idx_crm_audit_entity ON crm_audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_crm_audit_created_at ON crm_audit_log(created_at DESC);

-- Header-level sale record.
CREATE TABLE IF NOT EXISTS inventory_sales (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id TEXT,
    client_name TEXT NOT NULL,
    client_phone TEXT,
    payment_status TEXT NOT NULL,
    amount_charged NUMERIC(14,2) DEFAULT 0,
    paid_amount NUMERIC(14,2) DEFAULT 0,
    balance NUMERIC(14,2) DEFAULT 0,
    total_profit NUMERIC(14,2) DEFAULT 0,
    notes TEXT,
    sold_by TEXT,
    sold_at TIMESTAMPTZ DEFAULT NOW(),
    is_reversed BOOLEAN DEFAULT FALSE,
    reversed_at TIMESTAMPTZ,
    reversed_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inventory_sales_client_name ON inventory_sales(client_name);
CREATE INDEX IF NOT EXISTS idx_inventory_sales_payment_status ON inventory_sales(payment_status);
CREATE INDEX IF NOT EXISTS idx_inventory_sales_sold_at ON inventory_sales(sold_at DESC);

-- Item-level sale rows linking source inventory and service job.
CREATE TABLE IF NOT EXISTS inventory_sale_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sale_id UUID NOT NULL REFERENCES inventory_sales(id) ON DELETE CASCADE,
    source_inventory_item_id UUID NOT NULL REFERENCES inventory_items(id) ON DELETE RESTRICT,
    service_job_id UUID REFERENCES service_jobs(id) ON DELETE SET NULL,
    quantity NUMERIC(12,2) NOT NULL,
    unit_price NUMERIC(14,2) NOT NULL,
    unit_cost NUMERIC(14,2) DEFAULT 0,
    amount_charged NUMERIC(14,2) NOT NULL,
    profit NUMERIC(14,2) DEFAULT 0,
    notes TEXT,
    sold_by TEXT,
    sold_at TIMESTAMPTZ DEFAULT NOW(),
    is_reversed BOOLEAN DEFAULT FALSE,
    reversed_at TIMESTAMPTZ,
    reversed_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inventory_sale_items_sale_id ON inventory_sale_items(sale_id);
CREATE INDEX IF NOT EXISTS idx_inventory_sale_items_source_item_id ON inventory_sale_items(source_inventory_item_id);
CREATE INDEX IF NOT EXISTS idx_inventory_sale_items_service_job_id ON inventory_sale_items(service_job_id);

-- Inventory transaction history for stock movement traceability.
CREATE TABLE IF NOT EXISTS inventory_transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    inventory_item_id UUID NOT NULL REFERENCES inventory_items(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    quantity_change NUMERIC(12,2) NOT NULL,
    quantity_before NUMERIC(12,2) NOT NULL,
    quantity_after NUMERIC(12,2) NOT NULL,
    related_sale_id UUID REFERENCES inventory_sales(id) ON DELETE SET NULL,
    related_sale_item_id UUID REFERENCES inventory_sale_items(id) ON DELETE SET NULL,
    performed_by TEXT,
    note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inventory_transactions_item_created ON inventory_transactions(inventory_item_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_inventory_transactions_action ON inventory_transactions(action);

-- Transactional sale function to prevent overselling and keep inventory+billing in sync.
CREATE OR REPLACE FUNCTION sell_inventory_product(
    p_inventory_item_id UUID,
    p_quantity NUMERIC,
    p_unit_price NUMERIC,
    p_client_id TEXT,
    p_client_name TEXT,
    p_client_phone TEXT,
    p_paid_amount NUMERIC,
    p_payment_status TEXT,
    p_notes TEXT,
    p_sold_by TEXT
)
RETURNS TABLE (
    sale_id UUID,
    sale_item_id UUID,
    service_job_id UUID,
    remaining_quantity NUMERIC,
    amount_charged NUMERIC,
    balance NUMERIC,
    profit NUMERIC
) LANGUAGE plpgsql AS $$
DECLARE
    v_item inventory_items%ROWTYPE;
    v_qty_before NUMERIC(12,2);
    v_qty_after NUMERIC(12,2);
    v_qty NUMERIC(12,2);
    v_unit_price NUMERIC(14,2);
    v_paid NUMERIC(14,2);
    v_total NUMERIC(14,2);
    v_balance NUMERIC(14,2);
    v_cost NUMERIC(14,2);
    v_profit NUMERIC(14,2);
    v_status TEXT;
    v_sale_id UUID;
    v_sale_item_id UUID;
    v_service_job_id UUID;
BEGIN
    v_qty := COALESCE(p_quantity, 0);
    IF v_qty <= 0 THEN
        RAISE EXCEPTION 'Quantity must be greater than zero';
    END IF;

    SELECT * INTO v_item
    FROM inventory_items
    WHERE id = p_inventory_item_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Inventory item not found';
    END IF;

    v_qty_before := COALESCE(v_item.quantity, 0);
    IF v_qty_before < v_qty THEN
        RAISE EXCEPTION 'Insufficient stock. Remaining: %, requested: %', v_qty_before, v_qty;
    END IF;

    v_unit_price := COALESCE(NULLIF(p_unit_price, 0), COALESCE(v_item.selling_price, 0));
    IF v_unit_price <= 0 THEN
        RAISE EXCEPTION 'Selling price must be greater than zero';
    END IF;

    v_paid := GREATEST(COALESCE(p_paid_amount, 0), 0);
    v_total := ROUND(v_unit_price * v_qty, 2);
    IF v_paid > v_total THEN
        v_paid := v_total;
    END IF;
    v_balance := ROUND(v_total - v_paid, 2);

    v_status := UPPER(TRIM(COALESCE(p_payment_status, '')));
    IF v_status NOT IN ('PAID', 'PART PAYMENT', 'UNPAID', 'PARTIAL') THEN
        v_status := CASE
            WHEN v_balance <= 0 THEN 'PAID'
            WHEN v_paid > 0 THEN 'PART PAYMENT'
            ELSE 'UNPAID'
        END;
    ELSIF v_status = 'PARTIAL' THEN
        v_status := 'PART PAYMENT';
    END IF;

    IF v_status = 'PAID' THEN
        v_paid := v_total;
        v_balance := 0;
    ELSIF v_status = 'UNPAID' THEN
        v_paid := 0;
        v_balance := v_total;
    END IF;

    v_cost := COALESCE(v_item.cost_price, 0);
    v_profit := ROUND(v_total - (v_cost * v_qty), 2);

    v_qty_after := v_qty_before - v_qty;

    UPDATE inventory_items
    SET quantity = v_qty_after,
        payment_status = CASE WHEN v_qty_after <= 0 THEN 'SOLD' ELSE payment_status END,
        updated_at = NOW()
    WHERE id = p_inventory_item_id;

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
        sold_at
    ) VALUES (
        NULLIF(TRIM(COALESCE(p_client_id, '')), ''),
        p_client_name,
        NULLIF(TRIM(COALESCE(p_client_phone, '')), ''),
        v_status,
        v_total,
        v_paid,
        v_balance,
        v_profit,
        p_notes,
        p_sold_by,
        NOW()
    ) RETURNING id INTO v_sale_id;

    INSERT INTO service_jobs (
        id,
        client_id,
        client_name,
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
        source_created_at,
        source_updated_at
    ) VALUES (
        uuid_generate_v4(),
        NULLIF(TRIM(COALESCE(p_client_id, '')), ''),
        p_client_name,
        COALESCE(v_item.item_name, 'Inventory Sale'),
        CONCAT('Inventory sale: ', COALESCE(v_item.item_name, 'Item')),
        v_qty,
        v_total,
        ROUND(v_cost * v_qty, 2),
        ROUND(v_cost * v_qty, 2),
        v_status,
        v_paid,
        CASE WHEN v_status = 'PAID' THEN CURRENT_DATE ELSE NULL END,
        CASE WHEN v_status = 'PAID' THEN NOW() ELSE NULL END,
        CURRENT_DATE,
        CURRENT_DATE,
        p_notes,
        NOW(),
        NOW()
    ) RETURNING id INTO v_service_job_id;

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
        p_inventory_item_id,
        v_service_job_id,
        v_qty,
        v_unit_price,
        v_cost,
        v_total,
        v_profit,
        p_notes,
        p_sold_by,
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
        p_inventory_item_id,
        'SALE',
        -v_qty,
        v_qty_before,
        v_qty_after,
        v_sale_id,
        v_sale_item_id,
        p_sold_by,
        p_notes
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
        'inventory_sale_created',
        'inventory_sale_item',
        v_sale_item_id::TEXT,
        p_sold_by,
        jsonb_build_object('inventory_item_id', p_inventory_item_id::TEXT, 'quantity', v_qty_before),
        jsonb_build_object('inventory_item_id', p_inventory_item_id::TEXT, 'quantity', v_qty_after),
        jsonb_build_object('sale_id', v_sale_id::TEXT, 'service_job_id', v_service_job_id::TEXT, 'amount_charged', v_total)
    );

    RETURN QUERY SELECT v_sale_id, v_sale_item_id, v_service_job_id, v_qty_after, v_total, v_balance, v_profit;
END;
$$;

-- Transactional reversal function to restore stock and neutralize service impact.
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
        jsonb_build_object('sale_id', v_sale_item.sale_id::TEXT, 'service_job_id', COALESCE(v_sale_item.service_job_id::TEXT, ''), 'reason', p_reason)
    );

    RETURN QUERY SELECT v_sale_item.id, v_inventory.id, COALESCE(v_sale_item.quantity, 0), v_qty_after, v_sale_item.service_job_id;
END;
$$;
