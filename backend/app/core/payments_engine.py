from __future__ import annotations

import time
import uuid
from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException

from app.core.financials import to_number


def _normalize_date(value: Optional[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return date.today().isoformat()
    return text[:10]


def _normalize_status(value: Optional[str]) -> str:
    normalized = str(value or "").strip().upper()
    if normalized == "PARTIAL":
        return "PART PAYMENT"
    return normalized


def _reference_timestamp() -> str:
    return datetime.utcnow().strftime("%Y%m%d-%H%M%S")


def _reference_suffix(length: int = 8) -> str:
    return uuid.uuid4().hex[:length].upper()


def generate_payment_reference(sb=None, *, prefix: str = "ATL-PAY") -> str:
    """Generate a readable globally unique payment reference.

    Format: PREFIX-YYYYMMDD-HHMMSS-XXXXXXXX
    """
    for _ in range(12):
        candidate = f"{prefix}-{_reference_timestamp()}-{_reference_suffix()}"
        if sb is None:
            return candidate
        existing = (
            sb.table("payments")
            .select("id")
            .eq("reference_no", candidate)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not existing:
            return candidate
    return f"{prefix}-{_reference_timestamp()}-{uuid.uuid4().hex.upper()}"


def _is_reference_collision_error(message: str) -> bool:
    lowered = str(message or "").lower()
    return "payments_reference_no_key" in lowered or "duplicate key value violates unique constraint" in lowered


def _is_retryable_db_error(message: str) -> bool:
    lowered = str(message or "").lower()
    retry_tokens = (
        "deadlock detected",
        "could not serialize access",
        "sqlstate 40p01",
        "sqlstate 40001",
    )
    return any(token in lowered for token in retry_tokens)


def _rpc_with_retry(sb, fn_name: str, params: dict, *, max_attempts: int = 3):
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return sb.rpc(fn_name, params).execute().data or []
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts or not _is_retryable_db_error(str(exc)):
                raise
            time.sleep(0.08 * attempt)
    if last_error:
        raise last_error
    return []


def apply_invoice_payment(
    sb,
    *,
    service_job_id: str,
    payment_amount: float,
    payment_method: Optional[str],
    payment_note: Optional[str],
    reference_no: Optional[str],
    payment_date: Optional[str],
    applied_by: Optional[str],
    applied_by_name: Optional[str],
    idempotency_key: Optional[str] = None,
) -> dict:
    amount = to_number(payment_amount)
    if amount <= 0:
        raise HTTPException(422, "Payment amount must be greater than zero")

    resolved_reference = str(reference_no or "").strip() or generate_payment_reference(sb)
    resolved_date = _normalize_date(payment_date)
    resolved_note = str(payment_note or "").strip() or None
    resolved_method = str(payment_method or "cash").strip() or "cash"
    resolved_idempotency = str(idempotency_key or "").strip() or None

    rpc_rows = []
    for attempt in range(1, 4):
        try:
            rpc_rows = _rpc_with_retry(
                sb,
                "apply_service_payment_tx",
                {
                    "p_service_job_id": service_job_id,
                    "p_payment_amount": amount,
                    "p_payment_method": resolved_method,
                    "p_payment_note": resolved_note,
                    "p_reference_no": resolved_reference,
                    "p_payment_date": resolved_date,
                    "p_applied_by": applied_by,
                    "p_applied_by_name": applied_by_name,
                    "p_idempotency_key": resolved_idempotency,
                },
            )
            break
        except Exception as exc:
            message = str(exc)
            if "exceeds outstanding balance" in message.lower():
                raise HTTPException(400, message)
            if "must be greater than zero" in message.lower():
                raise HTTPException(422, message)
            if attempt < 3 and _is_reference_collision_error(message):
                resolved_reference = generate_payment_reference(sb)
                continue
            raise HTTPException(500, f"Payment apply failed: {message}")

    if not rpc_rows:
        raise HTTPException(500, "Payment apply failed")

    rpc_result = rpc_rows[0]
    payment_id = str(rpc_result.get("payment_id") or "").strip()
    inserted_payment = (
        sb.table("payments")
        .select("*")
        .eq("id", payment_id)
        .single()
        .execute()
        .data
    )
    if not inserted_payment:
        raise HTTPException(500, "Payment record could not be loaded")

    updated_invoice = (
        sb.table("service_jobs")
        .select("*")
        .eq("id", service_job_id)
        .single()
        .execute()
        .data
    )
    if not updated_invoice:
        raise HTTPException(500, "Invoice could not be loaded")

    previous_balance = to_number(rpc_result.get("previous_balance"))
    new_balance = to_number(rpc_result.get("new_balance"))
    previous_paid_amount = to_number(rpc_result.get("previous_paid_amount"))
    new_paid_amount = to_number(rpc_result.get("new_paid_amount"))
    previous_status = _normalize_status(rpc_result.get("previous_status"))
    new_status = _normalize_status(rpc_result.get("new_status"))

    return {
        "payment": inserted_payment,
        "invoice": updated_invoice,
        "previous_balance": previous_balance,
        "new_balance": new_balance,
        "previous_paid_amount": previous_paid_amount,
        "new_paid_amount": new_paid_amount,
        "previous_status": previous_status,
        "new_status": new_status,
        "applied_amount": amount,
    }


def reverse_invoice_payment(
    sb,
    *,
    service_job_id: str,
    reversal_amount: float,
    reversal_reason: Optional[str],
    reversed_by: Optional[str],
    reversed_by_name: Optional[str],
    reversal_date: Optional[str],
    idempotency_key: Optional[str] = None,
) -> dict:
    amount = to_number(reversal_amount)
    if amount <= 0:
        raise HTTPException(422, "Reversal amount must be greater than zero")

    resolved_date = _normalize_date(reversal_date)
    reason = str(reversal_reason or "").strip() or "Payment reversal"
    resolved_idempotency = str(idempotency_key or "").strip() or None

    try:
        rpc_rows = _rpc_with_retry(
            sb,
            "reverse_service_payment_tx",
            {
                "p_service_job_id": service_job_id,
                "p_reversal_amount": amount,
                "p_reversal_reason": reason,
                "p_reversed_by": reversed_by,
                "p_reversed_by_name": reversed_by_name,
                "p_reversal_date": resolved_date,
                "p_idempotency_key": resolved_idempotency,
            },
        )
    except Exception as exc:
        message = str(exc)
        if "exceeds paid amount" in message.lower():
            raise HTTPException(400, message)
        if "must be greater than zero" in message.lower():
            raise HTTPException(422, message)
        raise HTTPException(500, f"Payment reversal failed: {message}")

    if not rpc_rows:
        raise HTTPException(500, "Payment reversal failed")

    rpc_result = rpc_rows[0]
    payment_id = str(rpc_result.get("payment_id") or "").strip()
    inserted_payment = (
        sb.table("payments")
        .select("*")
        .eq("id", payment_id)
        .single()
        .execute()
        .data
    )
    if not inserted_payment:
        raise HTTPException(500, "Reversal payment record could not be loaded")

    updated_invoice = (
        sb.table("service_jobs")
        .select("*")
        .eq("id", service_job_id)
        .single()
        .execute()
        .data
    )
    if not updated_invoice:
        raise HTTPException(500, "Invoice could not be loaded")

    previous_balance = to_number(rpc_result.get("previous_balance"))
    new_balance = to_number(rpc_result.get("new_balance"))
    previous_paid_amount = to_number(rpc_result.get("previous_paid_amount"))
    new_paid_amount = to_number(rpc_result.get("new_paid_amount"))
    previous_status = _normalize_status(rpc_result.get("previous_status"))
    new_status = _normalize_status(rpc_result.get("new_status"))

    return {
        "payment": inserted_payment,
        "invoice": updated_invoice,
        "previous_balance": previous_balance,
        "new_balance": new_balance,
        "previous_paid_amount": previous_paid_amount,
        "new_paid_amount": new_paid_amount,
        "previous_status": previous_status,
        "new_status": new_status,
        "reversal_amount": amount,
    }
