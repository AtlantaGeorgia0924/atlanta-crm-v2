from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.financials import (
    compute_outstanding,
    compute_payment_status,
    to_number,
)
from app.core.debtors import compute_debtors_from_supabase
from app.core.metrics_refresh import recompute_and_persist_metrics

router = APIRouter()


def _best_service_name(row: dict) -> str:
    candidates = [
        row.get("service_name"),
        row.get("service_description"),
        row.get("fault_description"),
        row.get("description"),
        row.get("notes"),
    ]
    for value in candidates:
        text = str(value or "").strip()
        if text and text.lower() != "unknown service":
            return text
    legacy_id = row.get("legacy_source_id")
    if legacy_id:
        return f"Service Job {legacy_id}"
    return "General Service"


class BillingCreate(BaseModel):
    client_id: Optional[str] = None
    client_name: str
    service_name: str
    description: Optional[str] = None
    quantity: float = 1
    unit_price: float
    amount_paid: float = 0
    service_expense: float = 0
    status: Optional[str] = "unpaid"
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    notes: Optional[str] = None
    source: Optional[str] = "manual"


class BillingUpdate(BaseModel):
    client_name: Optional[str] = None
    service_name: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount_paid: Optional[float] = None
    service_expense: Optional[float] = None
    status: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    payment_date: Optional[str] = None
    notes: Optional[str] = None


@router.get("")
def list_billing(
    status: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _user=Depends(get_current_user),
):
    sb = get_supabase()
    offset = (page - 1) * page_size
    query = (
        sb.table("service_jobs")
        .select("*", count="exact")
        .order("service_date", desc=True)
        .range(offset, offset + page_size - 1)
    )
    if status:
        normalized = status.strip().upper()
        if normalized in {"PARTIAL", "PART PAYMENT"}:
            query = query.in_("payment_status", ["PARTIAL", "PART PAYMENT"])
        else:
            query = query.eq("payment_status", normalized)
    if client_id:
        query = query.eq("client_id", client_id)
    result = query.execute()
    rows = []
    for row in (result.data or []):
        total = to_number(row.get("amount_charged"))
        paid = to_number(row.get("paid_amount"))
        qty = to_number(row.get("quantity")) or 1
        service_expense = to_number(row.get("service_expense"))
        if service_expense == 0:
            service_expense = to_number(row.get("service_expense_amount")) or to_number(row.get("expense_amount"))
        outstanding = compute_outstanding(total, paid)
        status_value = compute_payment_status(total, paid)
        row["unit_price"] = total
        row["total_amount"] = total
        row["amount_paid"] = paid
        row["balance"] = outstanding
        row["status"] = status_value.lower()
        row["service_expense"] = service_expense
        row["gross_profit"] = paid
        row["net_profit"] = to_number(row.get("service_profit")) or (paid - service_expense)
        row["invoice_date"] = row.get("service_date")
        row["service_name"] = _best_service_name(row)
        row["description"] = row.get("description") or row.get("service_name")
        row["quantity"] = qty
        rows.append(row)
    total = int(result.count or 0)
    total_pages = max(1, (total + page_size - 1) // page_size)
    print(f"[billing] rows={len(rows)} total={total} page={page} page_size={page_size}")
    return {
        "items": rows,
        "data": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/debtors")
def list_debtors(_user=Depends(get_current_user)):
    """Grouped debtor balances calculated dynamically from live service rows."""
    sb = get_supabase()
    debtors = compute_debtors_from_supabase(sb)
    grouped_rows = debtors["grouped_clients"]
    for row in grouped_rows:
        row["service_name"] = row.get("service_name") or "Outstanding invoices"
    return grouped_rows


@router.get("/{billing_id}")
def get_billing(billing_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    result = sb.table("service_jobs").select("*").eq("id", billing_id).single().execute()
    if not result.data:
        raise HTTPException(404, "Billing row not found")
    row = result.data
    total = to_number(row.get("amount_charged"))
    paid = to_number(row.get("paid_amount"))
    outstanding = compute_outstanding(total, paid)
    service_expense = to_number(row.get("service_expense"))
    if service_expense == 0:
        service_expense = to_number(row.get("service_expense_amount")) or to_number(row.get("expense_amount"))
    status_value = compute_payment_status(total, paid)
    row["total_amount"] = total
    row["amount_paid"] = paid
    row["balance"] = outstanding
    row["status"] = status_value.lower()
    row["service_expense"] = service_expense
    row["gross_profit"] = paid
    row["net_profit"] = to_number(row.get("service_profit")) or (paid - service_expense)
    row["invoice_date"] = row.get("service_date")
    row["service_name"] = _best_service_name(row)
    return row


@router.post("", status_code=201)
def create_billing(payload: BillingCreate, _user=Depends(get_current_user)):
    sb = get_supabase()
    data = payload.model_dump(exclude_none=True)
    # Determine status
    amount_paid = to_number(data.get("amount_paid", 0))
    unit_price = to_number(data.get("unit_price", 0))
    quantity = to_number(data.get("quantity", 1)) or 1
    total       = unit_price * quantity
    payment_status = compute_payment_status(total, amount_paid)

    mapped = {
        "client_id": data.get("client_id"),
        "client_name": data.get("client_name"),
        "service_name": data.get("service_name"),
        "description": data.get("description"),
        "quantity": quantity,
        "amount_charged": total,
        "payment_status": payment_status,
        "paid_amount": amount_paid,
        "service_expense_amount": to_number(data.get("service_expense", 0)),
        "service_expense_date": data.get("invoice_date"),
        "service_expense_description": data.get("description"),
        "paid_date": data.get("invoice_date") if payment_status == "PAID" else None,
        "paid_at": datetime.utcnow().isoformat() if payment_status == "PAID" else None,
        "service_date": data.get("invoice_date"),
        "due_date": data.get("due_date"),
        "notes": data.get("notes"),
    }
    result = sb.table("service_jobs").insert(mapped).execute()
    recompute_and_persist_metrics(sb, source="supabase_after_billing_create")
    return result.data[0]


@router.put("/{billing_id}")
def update_billing(billing_id: str, payload: BillingUpdate, _user=Depends(get_current_user)):
    sb = get_supabase()
    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No fields to update")

    if "status" in data:
        data["payment_status"] = str(data.pop("status")).upper()
    if "amount_paid" in data:
        data["paid_amount"] = data.pop("amount_paid")
    if "invoice_date" in data:
        data["service_date"] = data.pop("invoice_date")
    if "payment_date" in data:
        data["paid_date"] = data.pop("payment_date")

    if "unit_price" in data or "quantity" in data:
        existing = sb.table("service_jobs").select("amount_charged,quantity").eq("id", billing_id).single().execute().data
        qty = to_number(data.get("quantity", existing.get("quantity") or 1)) or 1
        current_total = to_number(existing.get("amount_charged") or 0)
        existing_qty = to_number(existing.get("quantity") or 1) or 1
        inferred_unit = current_total / existing_qty
        unit = to_number(data.pop("unit_price", inferred_unit))
        data["amount_charged"] = qty * unit

    if any(field in data for field in ["amount_charged", "paid_amount", "payment_status"]):
        existing = sb.table("service_jobs").select("amount_charged,paid_amount").eq("id", billing_id).single().execute().data
        total = to_number(data.get("amount_charged", existing.get("amount_charged") or 0))
        paid = to_number(data.get("paid_amount", existing.get("paid_amount") or 0))
        data["payment_status"] = compute_payment_status(total, paid)
        if data["payment_status"] == "PAID":
            data["paid_date"] = data.get("paid_date")
            data.setdefault("paid_at", datetime.utcnow().isoformat())
        else:
            data["paid_date"] = None

    result = sb.table("service_jobs").update(data).eq("id", billing_id).execute()
    recompute_and_persist_metrics(sb, source="supabase_after_billing_update")
    return result.data[0]


@router.delete("/{billing_id}", status_code=204)
def delete_billing(billing_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    sb.table("service_jobs").delete().eq("id", billing_id).execute()
    recompute_and_persist_metrics(sb, source="supabase_after_billing_delete")
