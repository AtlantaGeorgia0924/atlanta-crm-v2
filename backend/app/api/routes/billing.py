import re
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.financials import (
    compute_outstanding,
    compute_payment_status,
    to_number,
)
from app.core.debtors import compute_debtors_from_supabase
from app.core.metrics_refresh import recompute_and_persist_metrics
from app.core.rbac import user_is_admin

router = APIRouter()


def _iso_date_or_none(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:10]


def _log_billing_audit(
    sb,
    *,
    action: str,
    entity_id: str,
    performed_by: str,
    before_value: Optional[dict] = None,
    after_value: Optional[dict] = None,
    detail: Optional[dict] = None,
) -> None:
    try:
        sb.table("crm_audit_log").insert(
            {
                "action": action,
                "entity_type": "service_job",
                "entity_id": entity_id,
                "performed_by": performed_by,
                "before_value": before_value,
                "after_value": after_value,
                "detail": detail,
            }
        ).execute()
    except Exception:
        pass


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


def _normalize_client_name(value: Optional[str]) -> str:
    return str(value or "").strip().upper()


def _normalize_phone_number(value: Optional[str]) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _find_matching_client_by_phone(sb, phone_number: str) -> Optional[dict]:
    """Find a client by exact phone number match (normalized)."""
    if not phone_number:
        return None
    normalized_phone = _normalize_phone_number(phone_number)
    if not normalized_phone:
        return None
    client_rows = sb.table("clients").select("id,name,phone").execute().data or []
    for row in client_rows:
        if _normalize_phone_number(row.get("phone") or "") == normalized_phone:
            return row
    return None


def _find_matching_client_by_name(sb, client_name: str) -> Optional[dict]:
    """Find a client by normalized name match."""
    normalized_target = _normalize_client_name(client_name)
    if not normalized_target:
        return None
    client_rows = sb.table("clients").select("id,name,phone").execute().data or []
    for row in client_rows:
        if _normalize_client_name(row.get("name")) == normalized_target:
            return row
    return None


def _find_matching_client(sb, client_name: str, phone_number: Optional[str] = None) -> Optional[dict]:
    """Find a matching client with priority: phone first, then name.
    
    This ensures clients are deduplicated primarily by phone number.
    If phone matches an existing client, the existing client is returned unchanged.
    If phone doesn't match but name does, the name-matched client is returned.
    If neither matches, returns None.
    """
    # Priority 1: Match by phone number if provided
    if phone_number:
        by_phone = _find_matching_client_by_phone(sb, phone_number)
        if by_phone:
            return by_phone
    
    # Priority 2: Match by normalized name
    by_name = _find_matching_client_by_name(sb, client_name)
    if by_name:
        return by_name
    
    return None


def _find_latest_service_phone(sb, client_name: str) -> Optional[str]:
    normalized_target = _normalize_client_name(client_name)
    try:
        service_rows = (
            sb.table("service_jobs")
            .select("client_name,phone_number,service_date,source_updated_at,created_at")
            .execute()
            .data
            or []
        )
    except Exception:
        return None

    matching_rows = []
    for row in service_rows:
        if _normalize_client_name(row.get("client_name")) != normalized_target:
            continue
        raw_phone = str(row.get("phone_number") or "").strip()
        if not raw_phone:
            continue
        matching_rows.append(row)

    if not matching_rows:
        return None

    matching_rows.sort(
        key=lambda row: (
            str(row.get("service_date") or ""),
            str(row.get("source_updated_at") or ""),
            str(row.get("created_at") or ""),
        ),
        reverse=True,
    )
    return str(matching_rows[0].get("phone_number") or "").strip() or None


def _resolve_whatsapp_contact(sb, client_name: str) -> dict:
    """Resolve WhatsApp contact information with phone-first priority.
    
    Priority:
    1. Check if client phone exists in clients table (from phone-first matching)
    2. Fall back to latest phone from service_jobs for that client
    3. Require manual entry if neither found
    """
    # Try phone-first matching: pass empty phone to get name+phone lookup
    client_row = _find_matching_client(sb, client_name)
    client_phone = str((client_row or {}).get("phone") or "").strip()
    service_phone = None if client_phone else _find_latest_service_phone(sb, client_name)

    raw_phone = client_phone or service_phone or ""
    return {
        "client_id": (client_row or {}).get("id"),
        "client_name": (client_row or {}).get("name") or client_name,
        "phone_number": raw_phone,
        "normalized_phone_number": _normalize_phone_number(raw_phone),
        "source": "clients.phone" if client_phone else "service_jobs.phone_number" if service_phone else None,
        "requires_manual_entry": not bool(raw_phone),
    }


def _upsert_client_phone(sb, client_name: str, phone_number: str) -> dict:
    """Upsert a client with phone-first matching priority.
    
    Matching Priority:
    1. If phone_number matches an existing client, keep the existing record as-is.
       Do not update the name even if it differs.
    2. If phone doesn't match but client_name matches, update only the phone if needed.
    3. If neither matches, create a new client.
    
    This ensures phone-based deduplication and preserves existing client names.
    """
    cleaned_phone = str(phone_number or "").strip()
    cleaned_name = str(client_name or "").strip()
    
    # Try to find existing client: phone first, then name
    existing_client = _find_matching_client(sb, cleaned_name, cleaned_phone)
    
    if existing_client:
        # If phone matches, preserve the existing client exactly as-is
        phone_match = _find_matching_client_by_phone(sb, cleaned_phone)
        if phone_match:
            # Phone matched - return existing client unchanged
            return phone_match
        
        # Name matched but phone didn't - update phone if it's different
        updates = {}
        if cleaned_phone and _normalize_phone_number(cleaned_phone) != _normalize_phone_number(existing_client.get("phone") or ""):
            updates["phone"] = cleaned_phone
        if updates:
            response = sb.table("clients").update(updates).eq("id", existing_client.get("id")).execute()
            return response.data[0] if response.data else {**existing_client, **updates}
        return existing_client
    
    # No match found - create new client
    new_client = {
        "id": str(uuid.uuid4()),
        "name": cleaned_name,
        "phone": cleaned_phone,
    }
    response = sb.table("clients").insert(new_client).execute()
    return response.data[0] if response.data else new_client


def _track_whatsapp_send(sb, client_name: str, phone_number: str) -> dict:
    client_row = _upsert_client_phone(sb, client_name, phone_number)
    sent_at = datetime.utcnow().isoformat()

    try:
        current_tracking = (
            sb.table("clients")
            .select("whatsapp_sent_count")
            .eq("id", client_row.get("id"))
            .single()
            .execute()
            .data
            or {}
        )
        sent_count = int(current_tracking.get("whatsapp_sent_count") or 0) + 1
        response = (
            sb.table("clients")
            .update({
                "whatsapp_sent_count": sent_count,
                "last_whatsapp_sent_at": sent_at,
            })
            .eq("id", client_row.get("id"))
            .execute()
        )
        updated_client = response.data[0] if response.data else {**client_row, "whatsapp_sent_count": sent_count, "last_whatsapp_sent_at": sent_at}
    except Exception:
        sent_count = 1
        updated_client = client_row

    return {
        "client_id": updated_client.get("id"),
        "client_name": updated_client.get("name") or client_name,
        "phone_number": updated_client.get("phone") or phone_number,
        "normalized_phone_number": _normalize_phone_number(updated_client.get("phone") or phone_number),
        "whatsapp_sent_count": sent_count,
        "last_whatsapp_sent_at": sent_at,
    }


def _mask_financial_fields_for_staff(row: dict) -> dict:
    row["total_amount"] = None
    row["amount_paid"] = None
    row["balance"] = None
    row["gross_profit"] = None
    row["net_profit"] = None
    return row


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
    payment_status: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None),
    returned: Optional[bool] = Query(None),
    is_return: Optional[bool] = Query(None),
    paid_state: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _user=Depends(get_current_user),
):
    is_admin = user_is_admin(_user)
    sb = get_supabase()
    offset = (page - 1) * page_size
    query = (
        sb.table("service_jobs")
        .select("*", count="exact")
        .order("service_date", desc=True)
        .range(offset, offset + page_size - 1)
    )
    normalized_status_input = (payment_status or status or "").strip()
    if normalized_status_input:
        normalized = normalized_status_input.upper()
        if normalized in {"PARTIAL", "PART PAYMENT"}:
            query = query.in_("payment_status", ["PARTIAL", "PART PAYMENT"])
        else:
            query = query.eq("payment_status", normalized)
    if client_id:
        query = query.eq("client_id", client_id)
    effective_from = from_date or date_from
    effective_to = to_date or date_to
    if effective_from:
        query = query.gte("service_date", _iso_date_or_none(effective_from))
    if effective_to:
        query = query.lte("service_date", _iso_date_or_none(effective_to))
    if min_amount is not None:
        query = query.gte("amount_charged", min_amount)
    if max_amount is not None:
        query = query.lte("amount_charged", max_amount)
    effective_is_return = is_return if is_return is not None else returned
    if effective_is_return is not None:
        query = query.eq("is_return", effective_is_return)

    if paid_state:
        normalized_paid = paid_state.strip().lower()
        if normalized_paid == "paid":
            query = query.eq("payment_status", "PAID")
        elif normalized_paid in {"unpaid", "not_paid"}:
            query = query.neq("payment_status", "PAID")

    if search:
        term = search.strip()
        if term:
            try:
                uuid.UUID(term)
                query = query.eq("id", term)
            except Exception:
                pass
            # Cross-column search for scalability (client, phone, service, notes, id)
            query = query.or_(
                f"client_name.ilike.%{term}%,"
                f"phone_number.ilike.%{term}%,"
                f"service_name.ilike.%{term}%,"
                f"description.ilike.%{term}%,"
                f"notes.ilike.%{term}%,"
                f"legacy_source_id.ilike.%{term}%"
            )

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
        rows.append(row if is_admin else _mask_financial_fields_for_staff(row))
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


@router.get("/grouped")
def list_billing_grouped(
    status: Optional[str] = Query(None),
    payment_status: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None),
    returned: Optional[bool] = Query(None),
    is_return: Optional[bool] = Query(None),
    paid_state: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
    _user=Depends(get_current_user),
):
    is_admin = user_is_admin(_user)
    sb = get_supabase()
    offset = (page - 1) * page_size
    query = (
        sb.table("service_jobs")
        .select("*", count="exact")
        .order("service_date", desc=True)
        .order("created_at", desc=True)
        .range(offset, offset + page_size - 1)
    )

    normalized_status_input = (payment_status or status or "").strip()
    if normalized_status_input:
        normalized = normalized_status_input.upper()
        if normalized in {"PARTIAL", "PART PAYMENT"}:
            query = query.in_("payment_status", ["PARTIAL", "PART PAYMENT"])
        else:
            query = query.eq("payment_status", normalized)
    if client_id:
        query = query.eq("client_id", client_id)
    effective_from = from_date or date_from
    effective_to = to_date or date_to
    if effective_from:
        query = query.gte("service_date", _iso_date_or_none(effective_from))
    if effective_to:
        query = query.lte("service_date", _iso_date_or_none(effective_to))
    if min_amount is not None:
        query = query.gte("amount_charged", min_amount)
    if max_amount is not None:
        query = query.lte("amount_charged", max_amount)
    effective_is_return = is_return if is_return is not None else returned
    if effective_is_return is not None:
        query = query.eq("is_return", effective_is_return)
    if paid_state:
        normalized_paid = paid_state.strip().lower()
        if normalized_paid == "paid":
            query = query.eq("payment_status", "PAID")
        elif normalized_paid in {"unpaid", "not_paid"}:
            query = query.neq("payment_status", "PAID")
    if search:
        term = search.strip()
        if term:
            try:
                uuid.UUID(term)
                query = query.eq("id", term)
            except Exception:
                pass
            query = query.or_(
                f"client_name.ilike.%{term}%,"
                f"phone_number.ilike.%{term}%,"
                f"service_name.ilike.%{term}%,"
                f"description.ilike.%{term}%,"
                f"notes.ilike.%{term}%,"
                f"legacy_source_id.ilike.%{term}%"
            )

    result = query.execute()
    rows = result.data or []

    groups: dict[str, dict] = {}
    for row in rows:
        service_date = str(row.get("service_date") or "")[:10] or "Unknown"
        total = to_number(row.get("amount_charged"))
        paid = to_number(row.get("paid_amount"))
        balance = compute_outstanding(total, paid)

        group = groups.setdefault(
            service_date,
            {
                "service_date": service_date,
                "items": [],
                "summary": {
                    "job_count": 0,
                    "total_amount": 0.0,
                    "total_paid": 0.0,
                    "total_outstanding": 0.0,
                },
            },
        )
        row["total_amount"] = total
        row["amount_paid"] = paid
        row["balance"] = balance
        row["status"] = compute_payment_status(total, paid).lower()
        row["service_name"] = _best_service_name(row)
        group["items"].append(row if is_admin else _mask_financial_fields_for_staff(row))
        group["summary"]["job_count"] += 1
        if is_admin:
            group["summary"]["total_amount"] += total
            group["summary"]["total_paid"] += paid
            group["summary"]["total_outstanding"] += balance

    grouped = sorted(groups.values(), key=lambda g: g["service_date"], reverse=True)
    total = int(result.count or 0)
    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "groups": grouped,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/debtors")
def list_debtors(search: Optional[str] = Query(None), _user=Depends(get_current_user)):
    """Grouped debtor balances calculated dynamically from live service rows."""
    if not user_is_admin(_user):
        raise HTTPException(status_code=403, detail="Forbidden")
    sb = get_supabase()
    debtors = compute_debtors_from_supabase(sb)
    grouped_rows = debtors["grouped_clients"]
    for row in grouped_rows:
        row["service_name"] = row.get("service_name") or "Outstanding invoices"
    
    # Filter by search term if provided
    if search:
        search_lower = search.lower().strip()
        grouped_rows = [
            row for row in grouped_rows
            if search_lower in (row.get("client_name") or "").lower()
            or search_lower in (row.get("service_name") or "").lower()
        ]
    
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
    created = result.data[0]
    _log_billing_audit(
        sb,
        action="invoice_created",
        entity_id=str(created.get("id")),
        performed_by=str(_user.id),
        before_value=None,
        after_value={
            "amount_charged": to_number(created.get("amount_charged")),
            "paid_amount": to_number(created.get("paid_amount")),
            "payment_status": str(created.get("payment_status") or ""),
        },
        detail={
            "client_name": created.get("client_name"),
            "service_name": created.get("service_name"),
        },
    )
    recompute_and_persist_metrics(sb, source="supabase_after_billing_create")
    return created


@router.put("/{billing_id}")
def update_billing(billing_id: str, payload: BillingUpdate, _user=Depends(get_current_user)):
    sb = get_supabase()
    existing_before = sb.table("service_jobs").select("*").eq("id", billing_id).single().execute().data
    if not existing_before:
        raise HTTPException(404, "Billing row not found")

    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No fields to update")

    if not user_is_admin(_user):
        restricted_fields = {"amount_paid", "status", "payment_date", "unit_price", "service_expense"}
        if restricted_fields.intersection(set(data.keys())):
            raise HTTPException(status_code=403, detail="Forbidden")

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
    updated = result.data[0]

    _log_billing_audit(
        sb,
        action="invoice_updated",
        entity_id=billing_id,
        performed_by=str(_user.id),
        before_value={
            "amount_charged": to_number(existing_before.get("amount_charged")),
            "paid_amount": to_number(existing_before.get("paid_amount")),
            "payment_status": str(existing_before.get("payment_status") or ""),
        },
        after_value={
            "amount_charged": to_number(updated.get("amount_charged")),
            "paid_amount": to_number(updated.get("paid_amount")),
            "payment_status": str(updated.get("payment_status") or ""),
        },
        detail={"fields_updated": sorted(list(data.keys()))},
    )

    before_paid = to_number(existing_before.get("paid_amount"))
    after_paid = to_number(updated.get("paid_amount"))
    before_status = str(existing_before.get("payment_status") or "")
    after_status = str(updated.get("payment_status") or "")
    if before_paid != after_paid or before_status != after_status:
        _log_billing_audit(
            sb,
            action="payment_updated",
            entity_id=billing_id,
            performed_by=str(_user.id),
            before_value={"paid_amount": before_paid, "payment_status": before_status},
            after_value={"paid_amount": after_paid, "payment_status": after_status},
            detail={"reason": "billing_update"},
        )

    recompute_and_persist_metrics(sb, source="supabase_after_billing_update")
    return updated


@router.delete("/{billing_id}", status_code=204)
def delete_billing(billing_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    sb.table("service_jobs").delete().eq("id", billing_id).execute()
    recompute_and_persist_metrics(sb, source="supabase_after_billing_delete")


@router.get("/debtors/{client_name}/items")
def get_debtor_items(client_name: str, _user=Depends(get_current_user)):
    """Get all outstanding items for a specific client (used in Debtor Details page)."""
    if not user_is_admin(_user):
        raise HTTPException(status_code=403, detail="Forbidden")
    sb = get_supabase()
    debtors = compute_debtors_from_supabase(sb)
    included_rows = debtors["included_rows"]
    
    # Filter rows for this client and format them
    client_items = [
        {
            "id": row.get("id"),
            "service_name": row.get("service_name"),
            "service_date": row.get("service_date"),
            "amount_charged": row.get("amount_charged"),
            "paid_amount": row.get("paid_amount"),
            "outstanding": row.get("outstanding"),
            "payment_status": row.get("payment_status"),
            "description": row.get("service_name") or "Service",
        }
        for row in included_rows
        if row.get("client_name").strip().upper() == client_name.strip().upper()
    ]
    
    # Sort by service_date descending
    client_items.sort(key=lambda x: str(x.get("service_date") or ""), reverse=True)
    
    total_outstanding = sum(item.get("outstanding", 0) for item in client_items)
    
    return {
        "client_name": client_name,
        "items": client_items,
        "item_count": len(client_items),
        "total_outstanding": total_outstanding,
    }


class WhatsAppTracker(BaseModel):
    phone_number: Optional[str] = None


@router.get("/debtors/{client_name}/whatsapp-contact")
def get_debtor_whatsapp_contact(client_name: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    return _resolve_whatsapp_contact(sb, client_name)


@router.post("/debtors/{client_name}/whatsapp")
def track_whatsapp_send(client_name: str, payload: WhatsAppTracker, _user=Depends(get_current_user)):
    """Persist WhatsApp phone if provided and track a successful send."""
    sb = get_supabase()
    resolved = _resolve_whatsapp_contact(sb, client_name)
    raw_phone = str(payload.phone_number or resolved.get("phone_number") or "").strip()
    normalized_phone = _normalize_phone_number(raw_phone)

    if not normalized_phone:
        raise HTTPException(422, "Phone number is required")

    tracked = _track_whatsapp_send(sb, client_name, raw_phone)
    _log_billing_audit(
        sb,
        action="whatsapp_sent",
        entity_id=str(tracked.get("client_id") or client_name),
        performed_by=str(_user.id),
        detail={
            "client_name": client_name,
            "phone_number": tracked.get("phone_number"),
            "whatsapp_sent_count": tracked.get("whatsapp_sent_count"),
            "last_whatsapp_sent_at": tracked.get("last_whatsapp_sent_at"),
        },
    )
    return {
        "message": "WhatsApp send tracked",
        **tracked,
    }
