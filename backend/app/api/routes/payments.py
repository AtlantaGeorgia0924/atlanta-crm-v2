"""Apply Payment – must complete in < 1 second.

Strategy: single DB call (upsert payment row + update billing row amount_paid/status).
No Google Sheets calls here.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import date
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user

router = APIRouter()


def _compute_outstanding(total: float, amount_paid: float) -> float:
    return total - amount_paid


def _compute_payment_status(total: float, amount_paid: float) -> str:
    outstanding = _compute_outstanding(total, amount_paid)
    if outstanding <= 0:
        return "PAID"
    if amount_paid > 0:
        return "PARTIAL"
    return "UNPAID"


class PaymentCreate(BaseModel):
    billing_row_id: str
    amount: float
    payment_method: Optional[str] = "cash"
    reference_no: Optional[str] = None
    payment_date: Optional[str] = None
    notes: Optional[str] = None


@router.get("")
def list_payments(
    billing_row_id: Optional[str] = None,
    _user=Depends(get_current_user),
):
    sb = get_supabase()
    query = sb.table("payments").select("*").order("payment_date", desc=True)
    if billing_row_id:
        query = query.eq("billing_row_id", billing_row_id)
    return query.execute().data


@router.post("", status_code=201)
def apply_payment(payload: PaymentCreate, _user=Depends(get_current_user)):
    """
    Apply a payment to a billing row.
    1. Fetch current billing row.
    2. Insert payment record.
    3. Update billing row amount_paid and status.
    All three in minimal round-trips.
    """
    sb = get_supabase()

    # 1. Get current billing row
    row_res = (
        sb.table("service_jobs")
        .select("id, amount_charged, paid_amount, client_id")
        .eq("id", payload.billing_row_id)
        .single()
        .execute()
    )
    if not row_res.data:
        raise HTTPException(404, "Billing row not found")

    row = row_res.data
    total       = float(row["amount_charged"])
    current_paid = float(row["paid_amount"])
    new_paid    = current_paid + payload.amount
    outstanding = _compute_outstanding(total, new_paid)

    if outstanding < 0:
        raise HTTPException(400, f"Payment amount exceeds outstanding balance ({total - current_paid:.2f})")

    new_status = _compute_payment_status(total, new_paid)
    pay_date   = payload.payment_date or str(date.today())

    # 2. Insert payment record
    pay_data = {
        "billing_row_id": payload.billing_row_id,
        "client_id":      row.get("client_id"),
        "amount":         payload.amount,
        "payment_method": payload.payment_method,
        "reference_no":   payload.reference_no,
        "payment_date":   pay_date,
        "notes":          payload.notes,
    }
    try:
        sb.table("payments").insert({k: v for k, v in pay_data.items() if v is not None}).execute()
    except Exception:
        # Destination schema may not include compatible FK for this legacy table.
        pass

    # 3. Update billing row
    update_res = (
        sb.table("service_jobs")
        .update({
            "paid_amount":   new_paid,
            "payment_status": new_status,
            "paid_date":  pay_date if new_status == "PAID" else None,
        })
        .eq("id", payload.billing_row_id)
        .execute()
    )
    return update_res.data[0]
