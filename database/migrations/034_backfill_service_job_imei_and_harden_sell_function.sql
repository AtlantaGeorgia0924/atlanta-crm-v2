-- Backfill IMEI on service jobs created from inventory sales and harden sell RPC mapping.

-- 1) Backfill existing service jobs where source inventory has IMEI but service job IMEI is empty.
UPDATE service_jobs sj
SET
    imei = ii.imei,
    device_model = COALESCE(NULLIF(BTRIM(COALESCE(sj.device_model, '')), ''), ii.item_name),
    source_updated_at = NOW()
FROM inventory_sale_items isi
JOIN inventory_items ii ON ii.id = isi.source_inventory_item_id
WHERE isi.service_job_id = sj.id
  AND NULLIF(BTRIM(COALESCE(ii.imei, '')), '') IS NOT NULL
  AND NULLIF(BTRIM(COALESCE(sj.imei, '')), '') IS NULL;

-- 2) Ensure future single-item sell flow propagates IMEI and device metadata into service_jobs.
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
        imei,
        device_model,
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
        NULLIF(BTRIM(COALESCE(v_item.imei, '')), ''),
        NULLIF(BTRIM(COALESCE(v_item.item_name, '')), ''),
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
