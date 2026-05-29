"""Payment transaction APIs backed by the payments ledger table."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.metrics_refresh import refresh_financial_state
from app.core.rbac import require_admin
from app.core.financial_events import emit_financial_event
from app.core.payments_engine import (
    apply_invoice_payment,
    generate_payment_reference,
    reverse_invoice_payment,
)

router = APIRouter(dependencies=[Depends(require_admin)])


def _log_payment_audit(sb, *, action: str, service_job_id: str, performed_by: str, detail: dict | None = None) -> bool:
    try:
        sb.table("crm_audit_log").insert(
            {
                "action": action,
                "entity_type": "payment",
                "entity_id": service_job_id,
                "performed_by": performed_by,
                "detail": detail,
            }
        ).execute()
        return True
    except Exception:
        return False


def _normalize_status(value: Optional[str]) -> str:
    status = str(value or "").strip().upper()
    if status == "PARTIAL":
        return "PART PAYMENT"
    return status


def _validate_payment_outcome(engine_result: dict) -> None:
    invoice = engine_result.get("invoice") or {}
    paid = float(invoice.get("paid_amount") or 0)
    total = float(invoice.get("amount_charged") or 0)
    status = _normalize_status(invoice.get("payment_status"))
    balance = float(engine_result.get("new_balance") or 0)

    if paid < 0:
        raise HTTPException(500, "Invalid post-payment state: negative paid amount")
    if total < 0:
        raise HTTPException(500, "Invalid post-payment state: negative invoice total")
    if paid - total > 1e-6:
        raise HTTPException(500, "Invalid post-payment state: overpayment persisted")
    if balance < -1e-6:
        raise HTTPException(500, "Invalid post-payment state: negative balance persisted")

    if paid <= 0 and status != "UNPAID":
        raise HTTPException(500, "Invalid post-payment state: expected UNPAID")
    if paid > 0 and paid + 1e-6 < total and status not in {"PART PAYMENT", "PARTIAL"}:
        raise HTTPException(500, "Invalid post-payment state: expected PART PAYMENT")
    if paid + 1e-6 >= total and status != "PAID":
        raise HTTPException(500, "Invalid post-payment state: expected PAID")


class PaymentCreate(BaseModel):
    billing_row_id: Optional[str] = None
    service_job_id: Optional[str] = None
    amount: float
    payment_method: Optional[str] = "cash"
    reference_no: Optional[str] = None
    payment_date: Optional[str] = None
    notes: Optional[str] = None
    idempotency_key: Optional[str] = None


class PaymentReverse(BaseModel):
    billing_row_id: Optional[str] = None
    service_job_id: Optional[str] = None
    amount: float
    reversal_date: Optional[str] = None
    reason: Optional[str] = None
    idempotency_key: Optional[str] = None


def _resolve_service_job_id(billing_row_id: Optional[str], service_job_id: Optional[str]) -> str:
    resolved = str(service_job_id or billing_row_id or "").strip()
    if not resolved:
        raise HTTPException(422, "service_job_id (or billing_row_id) is required")
    return resolved


@router.get("")
def list_payments(
    billing_row_id: Optional[str] = None,
    service_job_id: Optional[str] = None,
    client_id: Optional[str] = None,
    client_name: Optional[str] = None,
    _user=Depends(get_current_user),
):
    sb = get_supabase()
    query = sb.table("payments").select("*").order("created_at", desc=True)
    resolved_service_job_id = service_job_id or billing_row_id
    if resolved_service_job_id:
        query = query.eq("service_job_id", resolved_service_job_id)
    if client_id:
        query = query.eq("client_id", client_id)
    if client_name:
        query = query.ilike("client_name", f"%{client_name}%")
    return query.execute().data


@router.get("/reference")
def preview_payment_reference(_user=Depends(get_current_user)):
    sb = get_supabase()
    return {"reference_no": generate_payment_reference(sb)}


@router.post("", status_code=201)
def apply_payment(payload: PaymentCreate, _user=Depends(get_current_user)):
    """Apply a payment transaction and update invoice state."""
    if not str(payload.idempotency_key or "").strip():
        raise HTTPException(422, "idempotency_key is required")

    sb = get_supabase()
    resolved_service_job_id = _resolve_service_job_id(payload.billing_row_id, payload.service_job_id)
    engine_result = apply_invoice_payment(
        sb,
        service_job_id=resolved_service_job_id,
        payment_amount=payload.amount,
        payment_method=payload.payment_method,
        payment_note=payload.notes,
        reference_no=payload.reference_no,
        payment_date=payload.payment_date,
        applied_by=str(_user.id),
        applied_by_name=_user.full_name or _user.email,
        idempotency_key=payload.idempotency_key,
    )
    _validate_payment_outcome(engine_result)

    # Keep dashboard/cashflow cards in sync after payment updates.
    emit_financial_event(
        sb,
        "payment_updated",
        performed_by=str(_user.id),
        record_id=resolved_service_job_id,
        amount=engine_result["applied_amount"],
        detail={
            "previous_paid_amount": engine_result["previous_paid_amount"],
            "new_paid_amount": engine_result["new_paid_amount"],
            "payment_status": engine_result["new_status"],
            "payment_method": payload.payment_method,
            "reference_no": engine_result["payment"].get("reference_no"),
            "payment_note": payload.notes,
            "previous_balance": engine_result["previous_balance"],
            "new_balance": engine_result["new_balance"],
        },
    )
    audit_saved = _log_payment_audit(
        sb,
        action="payment_applied",
        service_job_id=resolved_service_job_id,
        performed_by=str(_user.id),
        detail={
            "reference_no": engine_result["payment"].get("reference_no"),
            "amount": engine_result["applied_amount"],
            "payment_method": payload.payment_method,
            "payment_note": payload.notes,
            "applied_by_name": _user.full_name or _user.email,
        },
    )
    if not audit_saved:
        raise HTTPException(500, "Payment applied but audit log write failed")

    refresh_financial_state(sb, source="supabase_after_payment")

    return {
        "invoice": engine_result["invoice"],
        "payment": engine_result["payment"],
        "reference_no": engine_result["payment"].get("reference_no"),
    }


@router.post("/reverse", status_code=201)
def reverse_payment(payload: PaymentReverse, _user=Depends(get_current_user)):
    """Reverse an applied payment amount and persist reversal transaction."""
    if not str(payload.idempotency_key or "").strip():
        raise HTTPException(422, "idempotency_key is required")

    sb = get_supabase()
    resolved_service_job_id = _resolve_service_job_id(payload.billing_row_id, payload.service_job_id)
    reversal_notes = (payload.reason or "").strip()
    engine_result = reverse_invoice_payment(
        sb,
        service_job_id=resolved_service_job_id,
        reversal_amount=payload.amount,
        reversal_reason=reversal_notes,
        reversed_by=str(_user.id),
        reversed_by_name=_user.full_name or _user.email,
        reversal_date=payload.reversal_date,
        idempotency_key=payload.idempotency_key,
    )
    _validate_payment_outcome(engine_result)

    emit_financial_event(
        sb,
        "payment_reversed",
        performed_by=str(_user.id),
        record_id=resolved_service_job_id,
        amount=engine_result["reversal_amount"],
        detail={
            "previous_paid_amount": engine_result["previous_paid_amount"],
            "new_paid_amount": engine_result["new_paid_amount"],
            "payment_status": engine_result["new_status"],
            "outstanding": engine_result["new_balance"],
            "reason": reversal_notes,
            "reference_no": engine_result["payment"].get("reference_no"),
        },
    )
    audit_saved = _log_payment_audit(
        sb,
        action="payment_reversed",
        service_job_id=resolved_service_job_id,
        performed_by=str(_user.id),
        detail={
            "reference_no": engine_result["payment"].get("reference_no"),
            "amount": engine_result["reversal_amount"],
            "reason": reversal_notes,
            "applied_by_name": _user.full_name or _user.email,
        },
    )
    if not audit_saved:
        raise HTTPException(500, "Payment reversal applied but audit log write failed")

    refresh_financial_state(sb, source="supabase_after_payment_reversal")

    return {
        "invoice": engine_result["invoice"],
        "payment": engine_result["payment"],
    }
