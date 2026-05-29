BEGIN;

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
    v_client_phone TEXT;
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

    IF COALESCE(v_job.is_return, FALSE) THEN
        RAISE EXCEPTION 'Cannot apply payment to a returned invoice';
    END IF;

    v_total := GREATEST(COALESCE(v_job.amount_charged, 0), 0);
    v_prev_paid := GREATEST(COALESCE(v_job.paid_amount, 0), 0);
    v_prev_balance := GREATEST(v_total - v_prev_paid, 0);
    v_prev_status := UPPER(
        COALESCE(
            NULLIF(BTRIM(v_job.payment_status), ''),
            CASE
                WHEN v_prev_paid >= v_total AND v_total > 0 THEN 'PAID'
                WHEN v_prev_paid > 0 THEN 'PART PAYMENT'
                ELSE 'UNPAID'
            END
        )
    );

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
        v_reference := CONCAT(
            'ATL-PAY-',
            TO_CHAR(NOW(), 'YYYYMMDDHH24MISSMS'),
            '-',
            UPPER(SUBSTRING(MD5(gen_random_uuid()::TEXT), 1, 4))
        );
    END IF;

    v_date := COALESCE(p_payment_date, CURRENT_DATE);
    v_note := NULLIF(BTRIM(COALESCE(p_payment_note, '')), '');
    v_method := COALESCE(NULLIF(BTRIM(COALESCE(p_payment_method, '')), ''), 'cash');
    v_client_phone := COALESCE(to_jsonb(v_job)->>'phone_number', to_jsonb(v_job)->>'phone');

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
        CASE
            WHEN COALESCE(v_job.client_id, '') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            THEN v_job.client_id::UUID
            ELSE NULL
        END,
        v_job.id,
        v_job.id,
        v_job.client_name,
        v_client_phone,
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
    SELECT
        v_payment.id,
        v_payment.reference_no,
        v_prev_balance,
        v_next_balance,
        v_prev_paid,
        v_next_paid,
        v_prev_status,
        v_next_status,
        v_date;
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
    v_client_phone TEXT;
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
    v_prev_status := UPPER(
        COALESCE(
            NULLIF(BTRIM(v_job.payment_status), ''),
            CASE
                WHEN v_prev_paid >= v_total AND v_total > 0 THEN 'PAID'
                WHEN v_prev_paid > 0 THEN 'PART PAYMENT'
                ELSE 'UNPAID'
            END
        )
    );

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

    v_reference := CONCAT(
        'ATL-REV-',
        TO_CHAR(NOW(), 'YYYYMMDDHH24MISSMS'),
        '-',
        UPPER(SUBSTRING(MD5(gen_random_uuid()::TEXT), 1, 4))
    );
    v_date := COALESCE(p_reversal_date, CURRENT_DATE);
    v_reason := COALESCE(NULLIF(BTRIM(COALESCE(p_reversal_reason, '')), ''), 'Payment reversal');
    v_client_phone := COALESCE(to_jsonb(v_job)->>'phone_number', to_jsonb(v_job)->>'phone');

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
        CASE
            WHEN COALESCE(v_job.client_id, '') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            THEN v_job.client_id::UUID
            ELSE NULL
        END,
        v_job.id,
        v_job.id,
        v_job.client_name,
        v_client_phone,
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
    SELECT
        v_payment.id,
        v_payment.reference_no,
        v_prev_balance,
        v_next_balance,
        v_prev_paid,
        v_next_paid,
        v_prev_status,
        v_next_status,
        v_date;
END;
$$;

COMMIT;
