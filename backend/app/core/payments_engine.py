from __future__ import annotations

import secrets
import string
from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException

from app.core.financials import compute_outstanding, compute_payment_status, to_number

_REF_CHARS = string.ascii_uppercase + string.digits


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


def _random_suffix(length: int = 4) -> str:
    return "".join(secrets.choice(_REF_CHARS) for _ in range(length))


def generate_payment_reference(sb=None, *, prefix: str = "ATL-PAY") -> str:
    """Generate a readable unique payment reference like ATL-PAY-YYYYMMDD-8F3K."""
    stamp = datetime.utcnow().strftime("%Y%m%d")
    for _ in range(8):
        candidate = f"{prefix}-{stamp}-{_random_suffix(4)}"
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
    return f"{prefix}-{stamp}-{_random_suffix(6)}"


def _load_service_job(sb, service_job_id: str) -> dict:
    result = (
        sb.table("service_jobs")
        .select("id,client_id,client_name,phone_number,amount_charged,paid_amount,payment_status")
        .eq("id", service_job_id)
        .single()
        .execute()
    )
    row = result.data
    if not row:
        raise HTTPException(404, "Invoice not found")
    return row


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
) -> dict:
    row = _load_service_job(sb, service_job_id)

    total = max(0.0, to_number(row.get("amount_charged")))
    previous_paid_amount = max(0.0, to_number(row.get("paid_amount")))
    previous_balance = compute_outstanding(total, previous_paid_amount)
    previous_status = _normalize_status(row.get("payment_status") or compute_payment_status(total, previous_paid_amount))

    amount = to_number(payment_amount)
    if amount <= 0:
        raise HTTPException(422, "Payment amount must be greater than zero")

    new_paid_amount = previous_paid_amount + amount
    if new_paid_amount > total + 1e-6:
        raise HTTPException(400, f"Payment amount exceeds outstanding balance ({max(total - previous_paid_amount, 0.0):.2f})")

    new_paid_amount = min(new_paid_amount, total)
    new_balance = compute_outstanding(total, new_paid_amount)
    new_status = _normalize_status(compute_payment_status(total, new_paid_amount))

    resolved_reference = str(reference_no or "").strip() or generate_payment_reference(sb)
    resolved_date = _normalize_date(payment_date)
    resolved_note = str(payment_note or "").strip() or None
    resolved_method = str(payment_method or "cash").strip() or "cash"

    payment_payload = {
        "reference_no": resolved_reference,
        "client_id": row.get("client_id"),
        "service_job_id": service_job_id,
        "billing_row_id": service_job_id,
        "client_name": row.get("client_name"),
        "client_phone": row.get("phone_number"),
        "payment_amount": amount,
        "amount": amount,
        "payment_method": resolved_method,
        "payment_note": resolved_note,
        "notes": resolved_note,
        "previous_balance": previous_balance,
        "new_balance": new_balance,
        "previous_paid_amount": previous_paid_amount,
        "new_paid_amount": new_paid_amount,
        "previous_status": previous_status,
        "new_status": new_status,
        "applied_by": applied_by,
        "applied_by_name": applied_by_name,
        "performed_by": applied_by,
        "payment_date": resolved_date,
    }
    inserted_payment = sb.table("payments").insert(payment_payload).execute().data[0]

    update_payload = {
        "paid_amount": new_paid_amount,
        "payment_status": new_status,
        "paid_date": resolved_date if new_status == "PAID" else None,
        "paid_at": datetime.utcnow().isoformat() if new_status == "PAID" else None,
    }
    updated_invoice = (
        sb.table("service_jobs")
        .update(update_payload)
        .eq("id", service_job_id)
        .execute()
        .data[0]
    )

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
) -> dict:
    row = _load_service_job(sb, service_job_id)

    total = max(0.0, to_number(row.get("amount_charged")))
    previous_paid_amount = max(0.0, to_number(row.get("paid_amount")))
    previous_balance = compute_outstanding(total, previous_paid_amount)
    previous_status = _normalize_status(row.get("payment_status") or compute_payment_status(total, previous_paid_amount))

    amount = to_number(reversal_amount)
    if amount <= 0:
        raise HTTPException(422, "Reversal amount must be greater than zero")
    if amount > previous_paid_amount + 1e-6:
        raise HTTPException(400, f"Reversal exceeds paid amount ({previous_paid_amount:.2f})")

    new_paid_amount = max(0.0, previous_paid_amount - amount)
    new_balance = compute_outstanding(total, new_paid_amount)
    new_status = _normalize_status(compute_payment_status(total, new_paid_amount))

    resolved_date = _normalize_date(reversal_date)
    reason = str(reversal_reason or "").strip() or "Payment reversal"

    payment_payload = {
        "reference_no": generate_payment_reference(sb, prefix="ATL-REV"),
        "client_id": row.get("client_id"),
        "service_job_id": service_job_id,
        "billing_row_id": service_job_id,
        "client_name": row.get("client_name"),
        "client_phone": row.get("phone_number"),
        "payment_amount": -amount,
        "amount": -amount,
        "payment_method": "reversal",
        "payment_note": reason,
        "notes": reason,
        "previous_balance": previous_balance,
        "new_balance": new_balance,
        "previous_paid_amount": previous_paid_amount,
        "new_paid_amount": new_paid_amount,
        "previous_status": previous_status,
        "new_status": new_status,
        "applied_by": reversed_by,
        "applied_by_name": reversed_by_name,
        "performed_by": reversed_by,
        "payment_date": resolved_date,
        "is_reversed": True,
        "reversed_at": datetime.utcnow().isoformat(),
        "reversed_by": reversed_by,
        "reversal_reason": reason,
    }
    inserted_payment = sb.table("payments").insert(payment_payload).execute().data[0]

    updated_invoice = (
        sb.table("service_jobs")
        .update(
            {
                "paid_amount": new_paid_amount,
                "payment_status": new_status,
                "paid_date": resolved_date if new_status == "PAID" else None,
                "paid_at": datetime.utcnow().isoformat() if new_status == "PAID" else None,
            }
        )
        .eq("id", service_job_id)
        .execute()
        .data[0]
    )

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
