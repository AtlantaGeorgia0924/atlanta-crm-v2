from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user

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
        query = query.eq("payment_status", status.upper())
    if client_id:
        query = query.eq("client_id", client_id)
    result = query.execute()
    rows = []
    for row in (result.data or []):
        total = float(row.get("amount_charged") or 0)
        paid = float(row.get("paid_amount") or 0)
        qty = float(row.get("quantity") or 1)
        row["unit_price"] = total
        row["total_amount"] = total
        row["amount_paid"] = paid
        row["balance"] = total - paid
        row["status"] = str(row.get("payment_status") or "UNPAID").lower()
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
    """All billing rows with outstanding balances."""
    sb = get_supabase()
    result = (
        sb.table("service_jobs")
        .select("*")
        .neq("payment_status", "PAID")
        .order("due_date")
        .execute()
    )
    rows = []
    for row in (result.data or []):
        total = float(row.get("amount_charged") or 0)
        paid = float(row.get("paid_amount") or 0)
        balance = total - paid
        if balance <= 0:
            continue
        row["total_amount"] = total
        row["amount_paid"] = paid
        row["balance"] = balance
        row["status"] = str(row.get("payment_status") or "UNPAID").lower()
        row["service_name"] = _best_service_name(row)
        row["row_type"] = "service"
        rows.append(row)

    # Include unpaid inventory sales as debtors.
    inv_rows = (
        sb.table("inventory_items")
        .select("id,item_name,quantity,selling_price,cost_price,expense_amount,payment_status,paid_date")
        .neq("payment_status", "PAID")
        .execute()
        .data
        or []
    )
    for item in inv_rows:
        quantity = float(item.get("quantity") or 0)
        selling_price = float(item.get("selling_price") or 0)
        cost_price = float(item.get("cost_price") or 0)
        expense_amount = float(item.get("expense_amount") or 0)
        computed_total = quantity * selling_price
        # Fallbacks handle sparse migrated rows where selling/quantity may be zero.
        total = computed_total if computed_total > 0 else max(selling_price, cost_price, expense_amount, 0.0)
        rows.append(
            {
                "id": f"inventory::{item.get('id')}",
                "client_name": "Inventory Sale",
                "service_name": item.get("item_name") or "Inventory Item",
                "total_amount": total,
                "amount_paid": 0,
                "balance": total,
                "status": "unpaid",
                "due_date": item.get("paid_date"),
                "row_type": "inventory",
            }
        )

    rows.sort(key=lambda x: x.get("due_date") or "")
    return rows


@router.get("/{billing_id}")
def get_billing(billing_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    result = sb.table("service_jobs").select("*").eq("id", billing_id).single().execute()
    if not result.data:
        raise HTTPException(404, "Billing row not found")
    row = result.data
    total = float(row.get("amount_charged") or 0)
    paid = float(row.get("paid_amount") or 0)
    row["total_amount"] = total
    row["amount_paid"] = paid
    row["balance"] = total - paid
    row["status"] = str(row.get("payment_status") or "UNPAID").lower()
    row["invoice_date"] = row.get("service_date")
    row["service_name"] = _best_service_name(row)
    return row


@router.post("", status_code=201)
def create_billing(payload: BillingCreate, _user=Depends(get_current_user)):
    sb = get_supabase()
    data = payload.model_dump(exclude_none=True)
    # Determine status
    amount_paid = data.get("amount_paid", 0)
    unit_price  = data.get("unit_price", 0)
    quantity    = data.get("quantity", 1)
    total       = unit_price * quantity
    if amount_paid >= total:
        payment_status = "PAID"
    elif amount_paid > 0:
        payment_status = "PARTIAL"
    else:
        payment_status = "UNPAID"

    mapped = {
        "client_id": data.get("client_id"),
        "client_name": data.get("client_name"),
        "service_name": data.get("service_name"),
        "description": data.get("description"),
        "quantity": quantity,
        "amount_charged": total,
        "payment_status": payment_status,
        "paid_amount": amount_paid,
        "paid_date": data.get("invoice_date") if payment_status == "PAID" else None,
        "service_date": data.get("invoice_date"),
        "due_date": data.get("due_date"),
        "notes": data.get("notes"),
    }
    result = sb.table("service_jobs").insert(mapped).execute()
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
        qty = float(data.get("quantity", existing.get("quantity") or 1))
        current_total = float(existing.get("amount_charged") or 0)
        inferred_unit = current_total / float(existing.get("quantity") or 1)
        unit = float(data.pop("unit_price", inferred_unit))
        data["amount_charged"] = qty * unit

    result = sb.table("service_jobs").update(data).eq("id", billing_id).execute()
    return result.data[0]


@router.delete("/{billing_id}", status_code=204)
def delete_billing(billing_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    sb.table("service_jobs").delete().eq("id", billing_id).execute()
