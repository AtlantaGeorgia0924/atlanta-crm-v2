"""Apply Payment – must complete in < 1 second.

Strategy: single DB call (upsert payment row + update billing row amount_paid/status).
No Google Sheets calls here.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.financials import compute_outstanding, compute_payment_status, to_number
from app.core.metrics_refresh import recompute_and_persist_metrics
from app.core.rbac import require_admin
from app.core.financial_events import emit_financial_event

router = APIRouter(dependencies=[Depends(require_admin)])


class PaymentCreate(BaseModel):
    billing_row_id: str
    amount: float
    payment_method: Optional[str] = "cash"
    reference_no: Optional[str] = None
    payment_date: Optional[str] = None
    notes: Optional[str] = None


class PaymentReverse(BaseModel):
    billing_row_id: str
    amount: float
    reversal_date: Optional[str] = None
    reason: Optional[str] = None


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
    total = max(0.0, to_number(row.get("amount_charged")))
    current_paid = max(0.0, to_number(row.get("paid_amount")))
    payment_amount = to_number(payload.amount)
    if payment_amount <= 0:
        raise HTTPException(422, "Payment amount must be greater than zero")

    new_paid = current_paid + payment_amount
    if new_paid > total:
        raise HTTPException(400, f"Payment amount exceeds outstanding balance ({max(total - current_paid, 0.0):.2f})")

    outstanding = compute_outstanding(total, new_paid)
    if new_paid <= 0:
        new_status = "UNPAID"
    elif new_paid < total:
        new_status = "PART PAYMENT"
    else:
        new_status = "PAID"
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
            "paid_at": datetime.utcnow().isoformat() if new_status == "PAID" else None,
        })
        .eq("id", payload.billing_row_id)
        .execute()
    )

    # Keep dashboard/cashflow cards in sync after payment updates.
    emit_financial_event(
        sb,
        "payment_updated",
        performed_by=str(_user.id),
        record_id=str(payload.billing_row_id),
        amount=payment_amount,
        detail={
            "previous_paid_amount": current_paid,
            "new_paid_amount": new_paid,
            "payment_status": new_status,
            "payment_method": payload.payment_method,
            "reference_no": payload.reference_no,
        },
    )
    recompute_and_persist_metrics(sb, source="supabase_after_payment")

    return update_res.data[0]


@router.post("/reverse", status_code=201)
def reverse_payment(payload: PaymentReverse, _user=Depends(get_current_user)):
    """
    Reverse an applied payment amount for a billing row.
    This never allows paid_amount to become negative.
    """
    sb = get_supabase()

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
    total = max(0.0, to_number(row.get("amount_charged")))
    current_paid = max(0.0, to_number(row.get("paid_amount")))
    reversal_amount = to_number(payload.amount)
    if reversal_amount <= 0:
        raise HTTPException(422, "Reversal amount must be greater than zero")
    if reversal_amount > current_paid:
        raise HTTPException(400, f"Reversal exceeds paid amount ({current_paid:.2f})")

    new_paid = max(0.0, current_paid - reversal_amount)
    outstanding = compute_outstanding(total, new_paid)
    if new_paid <= 0:
        new_status = "UNPAID"
    elif new_paid < total:
        new_status = "PART PAYMENT"
    else:
        new_status = "PAID"

    reversal_date = payload.reversal_date or str(date.today())

    update_res = (
        sb.table("service_jobs")
        .update(
            {
                "paid_amount": new_paid,
                "payment_status": new_status,
                "paid_date": reversal_date if new_status == "PAID" else None,
                "paid_at": datetime.utcnow().isoformat() if new_status == "PAID" else None,
            }
        )
        .eq("id", payload.billing_row_id)
        .execute()
    )

    # Persist reversal ledger line as negative amount when compatible.
    reversal_notes = (payload.reason or "").strip()
    try:
        sb.table("payments").insert(
            {
                "billing_row_id": payload.billing_row_id,
                "client_id": row.get("client_id"),
                "amount": -reversal_amount,
                "payment_method": "reversal",
                "reference_no": None,
                "payment_date": reversal_date,
                "notes": reversal_notes or "Payment reversal",
            }
        ).execute()
    except Exception:
        pass

    emit_financial_event(
        sb,
        "payment_reversed",
        performed_by=str(_user.id),
        record_id=str(payload.billing_row_id),
        amount=reversal_amount,
        detail={
            "previous_paid_amount": current_paid,
            "new_paid_amount": new_paid,
            "payment_status": new_status,
            "outstanding": outstanding,
            "reason": reversal_notes,
        },
    )
    recompute_and_persist_metrics(sb, source="supabase_after_payment_reversal")

    return update_res.data[0]
