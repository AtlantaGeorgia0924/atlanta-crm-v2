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
from app.core.financial_events import emit_financial_event
from app.core.payments_engine import apply_invoice_payment

router = APIRouter()

_SERVICE_JOB_COLUMNS_CACHE: set[str] | None = None
_STAFF_VIEW_OWN_FLAG_KEY = "staff_can_only_view_own_services"


def _iso_date_or_none(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:10]


def _normalize_search_term(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return re.sub(r"\s+", " ", text)


def _service_job_columns(sb) -> set[str]:
    global _SERVICE_JOB_COLUMNS_CACHE
    if _SERVICE_JOB_COLUMNS_CACHE is not None:
        return _SERVICE_JOB_COLUMNS_CACHE
    rows = (
        sb.table("information_schema.columns")
        .select("column_name")
        .eq("table_schema", "public")
        .eq("table_name", "service_jobs")
        .execute()
        .data
        or []
    )
    _SERVICE_JOB_COLUMNS_CACHE = {str(r.get("column_name")) for r in rows if r.get("column_name")}
    return _SERVICE_JOB_COLUMNS_CACHE


def _staff_scope_enabled(sb) -> bool:
    """Future permission flag scaffold: staff_can_only_view_own_services."""
    rows = (
        sb.table("app_settings")
        .select("value")
        .eq("key", _STAFF_VIEW_OWN_FLAG_KEY)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return False
    value = str(rows[0].get("value") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _actor_display_name(user) -> str:
    role = str(getattr(user, "role", "staff") or "staff").strip().lower()
    label = "Admin" if role == "admin" else "Staff"
    name = str(getattr(user, "full_name", "") or "").strip() or str(getattr(user, "email", "") or "").strip()
    return f"{name} ({label})" if name else label


def _inventory_search_service_ids(sb, term: str) -> list[str]:
    if not term:
        return []
    wildcard = "%" + "%".join(term.split()) + "%"

    # Search inventory item metadata first, then map matching items to related service rows.
    inventory_matches = (
        sb.table("inventory_items")
        .select("id")
        .or_(
            f"item_name.ilike.{wildcard},"
            f"imei.ilike.{wildcard},"
            f"sku.ilike.{wildcard},"
            f"supplier.ilike.{wildcard},"
            f"unlock_method.ilike.{wildcard}"
        )
        .limit(500)
        .execute()
        .data
        or []
    )
    inventory_ids = [str(r.get("id")) for r in inventory_matches if r.get("id")]
    if not inventory_ids:
        return []

    links = (
        sb.table("inventory_sale_items")
        .select("service_job_id")
        .in_("source_inventory_item_id", inventory_ids)
        .limit(1000)
        .execute()
        .data
        or []
    )
    result = []
    for row in links:
        service_job_id = row.get("service_job_id")
        if service_job_id:
            result.append(str(service_job_id))
    return list(dict.fromkeys(result))


def _apply_service_search_filters(sb, query, raw_search: Optional[str]):
    term = _normalize_search_term(raw_search)
    if not term:
        return query, False

    wildcard = "%" + "%".join(term.split()) + "%"
    columns = _service_job_columns(sb)

    search_fields = [
        "client_name",
        "phone_number",
        "service_name",
        "description",
        "notes",
        "legacy_source_id",
        "imei",
        "serial_number",
        "device_model",
        "supplier",
        "unlock_method",
    ]
    clauses = [f"{field}.ilike.{wildcard}" for field in search_fields if field in columns]

    try:
        uuid.UUID(term)
        clauses.append(f"id.eq.{term}")
    except Exception:
        pass

    related_ids = _inventory_search_service_ids(sb, term)
    if related_ids:
        clauses.append(f"id.in.({','.join(related_ids)})")

    if clauses:
        query = query.or_(",".join(clauses))
    return query, True


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


def _normalize_payment_status(value: Optional[str]) -> str:
    status = str(value or "").strip().upper()
    if status == "PARTIAL":
        return "PART PAYMENT"
    return status


def _compute_financial_state(total_amount, paid_amount) -> tuple[float, float, str]:
    total = max(0.0, to_number(total_amount))
    paid = max(0.0, to_number(paid_amount))
    if paid > total:
        raise HTTPException(status_code=422, detail="Paid amount cannot exceed total amount")

    outstanding = compute_outstanding(total, paid)
    if paid <= 0:
        status = "UNPAID"
    elif paid < total:
        status = "PART PAYMENT"
    else:
        status = "PAID"
    return total, paid, status


def _serialize_billing_row(row: dict, *, is_admin: bool = True) -> dict:
    total = to_number(row.get("amount_charged"))
    paid = to_number(row.get("paid_amount"))
    outstanding = compute_outstanding(total, paid)
    service_expense = to_number(row.get("service_expense"))
    if service_expense == 0:
        service_expense = to_number(row.get("service_expense_amount")) or to_number(row.get("expense_amount"))
    status_value = _normalize_payment_status(row.get("payment_status") or compute_payment_status(total, paid))

    serialized = dict(row)
    serialized["unit_price"] = total
    serialized["total_amount"] = total
    serialized["amount_paid"] = paid
    serialized["balance"] = outstanding
    serialized["status"] = status_value.lower()
    serialized["service_expense"] = service_expense
    serialized["gross_profit"] = paid
    serialized["net_profit"] = to_number(row.get("service_profit")) or (paid - service_expense)
    serialized["invoice_date"] = row.get("service_date")
    serialized["service_name"] = _best_service_name(row)
    serialized["description"] = row.get("description") or row.get("service_name")
    serialized["quantity"] = to_number(row.get("quantity")) or 1
    serialized["created_by"] = row.get("created_by")
    serialized["created_by_name"] = row.get("created_by_name")
    serialized["created_by_role"] = row.get("created_by_role")
    serialized["last_edited_by"] = row.get("last_edited_by")
    serialized["last_edited_by_name"] = row.get("last_edited_by_name")
    serialized["last_edited_at"] = row.get("last_edited_at")
    serialized["returned_by"] = row.get("returned_by")
    serialized["returned_by_name"] = row.get("returned_by_name")
    serialized["returned_at"] = row.get("returned_at")
    serialized["last_payment_by"] = row.get("last_payment_by")
    serialized["last_payment_by_name"] = row.get("last_payment_by_name")
    serialized["last_payment_at"] = row.get("last_payment_at")
    serialized["assigned_staff_id"] = row.get("assigned_staff_id")
    serialized["assigned_staff_name"] = row.get("assigned_staff_name")
    return serialized if is_admin else _mask_financial_fields_for_staff(serialized)


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
    phone_number: Optional[str] = None
    client_phone: Optional[str] = None
    imei: Optional[str] = None
    serial_number: Optional[str] = None
    condition: Optional[str] = None
    lock_status: Optional[str] = None
    unlock_method: Optional[str] = None


class BillingUpdate(BaseModel):
    client_name: Optional[str] = None
    service_name: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount_paid: Optional[float] = None
    service_expense: Optional[float] = None
    status: Optional[str] = None
    payment_status: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    payment_date: Optional[str] = None
    notes: Optional[str] = None
    phone_number: Optional[str] = None
    client_phone: Optional[str] = None
    imei: Optional[str] = None
    serial_number: Optional[str] = None
    condition: Optional[str] = None
    lock_status: Optional[str] = None
    unlock_method: Optional[str] = None


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
    created_by: Optional[str] = Query(None),
    edited_by: Optional[str] = Query(None),
    assigned_staff: Optional[str] = Query(None),
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
    if created_by:
        query = query.eq("created_by", created_by)
    if edited_by:
        query = query.eq("last_edited_by", edited_by)
    if assigned_staff:
        query = query.eq("assigned_staff_id", assigned_staff)

    if not is_admin and _staff_scope_enabled(sb):
        query = query.eq("created_by", str(_user.id))

    query, has_search = _apply_service_search_filters(sb, query, search)

    # Search defaults to global (all dates). Date filters remain optional refinements.
    effective_from = from_date or date_from
    effective_to = to_date or date_to
    if (effective_from and (not has_search or from_date or date_from)):
        query = query.gte("service_date", _iso_date_or_none(effective_from))
    if (effective_to and (not has_search or to_date or date_to)):
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

    result = query.execute()
    rows = [_serialize_billing_row(row, is_admin=is_admin) for row in (result.data or [])]
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
    created_by: Optional[str] = Query(None),
    edited_by: Optional[str] = Query(None),
    assigned_staff: Optional[str] = Query(None),
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
    if created_by:
        query = query.eq("created_by", created_by)
    if edited_by:
        query = query.eq("last_edited_by", edited_by)
    if assigned_staff:
        query = query.eq("assigned_staff_id", assigned_staff)

    if not is_admin and _staff_scope_enabled(sb):
        query = query.eq("created_by", str(_user.id))

    query, has_search = _apply_service_search_filters(sb, query, search)

    effective_from = from_date or date_from
    effective_to = to_date or date_to
    if (effective_from and (not has_search or from_date or date_from)):
        query = query.gte("service_date", _iso_date_or_none(effective_from))
    if (effective_to and (not has_search or to_date or date_to)):
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
        serialized = _serialize_billing_row(row, is_admin=is_admin)
        group["items"].append(serialized)
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

    if search:
        term = _normalize_search_term(search)
        tokens = term.split()

        def matches(row: dict) -> bool:
            haystack = " ".join(
                [
                    str(row.get("client_name") or ""),
                    str(row.get("phone_number") or ""),
                    str(row.get("service_name") or ""),
                    str(row.get("last_activity") or ""),
                ]
            ).lower()
            normalized_haystack = re.sub(r"\s+", " ", haystack)
            return all(token in normalized_haystack for token in tokens)

        grouped_rows = [row for row in grouped_rows if matches(row)]

    return grouped_rows


def _normalize_client_key(value: str) -> str:
    return str(value or "").strip().upper()


def _open_client_invoices(sb, client_name: str) -> list[dict]:
    target = _normalize_client_key(client_name)
    try:
        rows = (
            sb.table("service_jobs")
            .select("id,client_name,service_name,description,service_date,due_date,amount_charged,paid_amount,payment_status,is_return,notes,phone_number,created_at")
            .in_("payment_status", ["UNPAID", "PART PAYMENT", "PARTIAL"])
            .eq("is_return", False)
            .order("service_date")
            .order("created_at")
            .limit(1000)
            .execute()
            .data
            or []
        )
    except Exception:
        rows = (
            sb.table("service_jobs")
            .select("id,client_name,service_name,description,service_date,due_date,amount_charged,paid_amount,payment_status,is_return,notes,created_at")
            .in_("payment_status", ["UNPAID", "PART PAYMENT", "PARTIAL"])
            .eq("is_return", False)
            .order("service_date")
            .order("created_at")
            .limit(1000)
            .execute()
            .data
            or []
        )

    result: list[dict] = []
    for row in rows:
        if _normalize_client_key(row.get("client_name") or "") != target:
            continue
        total = to_number(row.get("amount_charged"))
        paid = to_number(row.get("paid_amount"))
        balance = compute_outstanding(total, paid)
        if balance <= 0:
            continue
        result.append(
            {
                "id": row.get("id"),
                "service_name": _best_service_name(row),
                "service_date": row.get("service_date"),
                "due_date": row.get("due_date"),
                "amount_charged": total,
                "paid_amount": paid,
                "balance": balance,
                "outstanding": balance,
                "payment_status": compute_payment_status(total, paid),
                "notes": row.get("notes"),
                "phone_number": row.get("phone_number"),
            }
        )
    return result


@router.get("/debtors/{client_name}/ledger")
def debtor_ledger(client_name: str, _user=Depends(get_current_user)):
    if not user_is_admin(_user):
        raise HTTPException(status_code=403, detail="Forbidden")
    sb = get_supabase()
    invoices = _open_client_invoices(sb, client_name)
    invoice_ids = [str(i.get("id")) for i in invoices if i.get("id")]

    payment_history = []
    if invoice_ids:
        try:
            history_rows = (
                sb.table("payments")
                .select(
                    "id,service_job_id,billing_row_id,payment_amount,amount,payment_method,reference_no,"
                    "payment_date,payment_note,notes,created_at,applied_by_name,new_balance,new_status,"
                    "is_reversed,reversal_reason"
                )
                .in_("service_job_id", invoice_ids)
                .order("created_at", desc=True)
                .limit(500)
                .execute()
                .data
                or []
            )
        except Exception:
            history_rows = (
                sb.table("payments")
                .select("id,billing_row_id,amount,payment_method,reference_no,payment_date,notes,created_at")
                .in_("billing_row_id", invoice_ids)
                .order("created_at", desc=True)
                .limit(500)
                .execute()
                .data
                or []
            )
        payment_history = [
            {
                **row,
                "service_job_id": row.get("service_job_id") or row.get("billing_row_id"),
                "payment_amount": to_number(row.get("payment_amount") or row.get("amount")),
                "payment_note": row.get("payment_note") or row.get("notes"),
            }
            for row in history_rows
        ]

    total_outstanding = sum(to_number(i.get("balance")) for i in invoices)
    unpaid_jobs = len(invoices)

    return {
        "client_name": client_name,
        "items": invoices,
        "item_count": unpaid_jobs,
        "total_outstanding": total_outstanding,
        "payment_history": payment_history,
    }


class DebtorPaymentAllocation(BaseModel):
    billing_row_id: str
    amount: float


class DebtorPaymentApplyPayload(BaseModel):
    amount: float
    payment_method: Optional[str] = "cash"
    reference_no: Optional[str] = None
    payment_date: Optional[str] = None
    notes: Optional[str] = None
    mode: Optional[str] = "auto"  # auto | manual
    allocations: Optional[list[DebtorPaymentAllocation]] = None


@router.post("/debtors/{client_name}/apply-payment")
def apply_debtor_payment(client_name: str, payload: DebtorPaymentApplyPayload, _user=Depends(get_current_user)):
    if not user_is_admin(_user):
        raise HTTPException(status_code=403, detail="Forbidden")

    sb = get_supabase()
    total_payment = to_number(payload.amount)
    if total_payment <= 0:
        raise HTTPException(status_code=422, detail="Payment amount must be greater than zero")

    open_rows = _open_client_invoices(sb, client_name)
    if not open_rows:
        raise HTTPException(status_code=400, detail="No unpaid invoices found for this debtor")

    open_map = {str(r.get("id")): r for r in open_rows if r.get("id")}
    allocations: list[dict] = []

    mode = str(payload.mode or "auto").strip().lower()
    if mode not in {"auto", "manual"}:
        raise HTTPException(status_code=422, detail="mode must be auto or manual")

    if mode == "manual":
        provided = payload.allocations or []
        if not provided:
            raise HTTPException(status_code=422, detail="Manual allocation requires allocations")

        manual_total = 0.0
        for item in provided:
            row_id = str(item.billing_row_id)
            if row_id not in open_map:
                raise HTTPException(status_code=400, detail=f"Invoice {row_id} is not eligible for payment")
            amt = to_number(item.amount)
            if amt <= 0:
                raise HTTPException(status_code=400, detail="Allocation amounts must be greater than zero")
            if amt > to_number(open_map[row_id].get("balance")):
                raise HTTPException(status_code=400, detail=f"Allocation exceeds balance for invoice {row_id}")
            manual_total += amt
            allocations.append({"billing_row_id": row_id, "amount": amt})

        if manual_total - total_payment > 1e-6:
            raise HTTPException(status_code=400, detail="Total allocated exceeds payment amount")
    else:
        remaining = total_payment
        for row in open_rows:
            if remaining <= 0:
                break
            row_id = str(row.get("id"))
            balance = to_number(row.get("balance"))
            applied = min(balance, remaining)
            if applied <= 0:
                continue
            allocations.append({"billing_row_id": row_id, "amount": applied})
            remaining -= applied

    if not allocations:
        raise HTTPException(status_code=400, detail="No allocatable invoice found for payment")

    payment_date = payload.payment_date or datetime.utcnow().date().isoformat()
    applied_total = 0.0
    unapplied = total_payment
    allocation_results = []
    multiple_allocations = len(allocations) > 1
    base_reference = str(payload.reference_no or "").strip() or None

    for idx, alloc in enumerate(allocations, start=1):
        billing_row_id = str(alloc["billing_row_id"])
        applied_amount = to_number(alloc["amount"])
        before = open_map[billing_row_id]

        invoice_reference = None
        if base_reference and not multiple_allocations:
            invoice_reference = base_reference
        elif base_reference and multiple_allocations:
            invoice_reference = f"{base_reference}-{idx:02d}"

        payment_result = apply_invoice_payment(
            sb,
            service_job_id=billing_row_id,
            payment_amount=applied_amount,
            payment_method=payload.payment_method,
            payment_note=payload.notes,
            reference_no=invoice_reference,
            payment_date=payment_date,
            applied_by=str(_user.id),
            applied_by_name=_user.full_name or _user.email,
        )

        prev_paid = payment_result["previous_paid_amount"]
        prev_balance = payment_result["previous_balance"]
        new_paid = payment_result["new_paid_amount"]
        new_balance = payment_result["new_balance"]
        new_status = payment_result["new_status"]

        _log_billing_audit(
            sb,
            action="payment_updated",
            entity_id=billing_row_id,
            performed_by=str(_user.id),
            before_value={"paid_amount": prev_paid, "payment_status": before.get("payment_status")},
            after_value={"paid_amount": new_paid, "payment_status": new_status},
            detail={
                "client_name": client_name,
                "allocated_amount": applied_amount,
                "previous_balance": prev_balance,
                "new_balance": new_balance,
                "payment_method": payload.payment_method,
                "payment_reference": payment_result["payment"].get("reference_no"),
                "payment_note": payload.notes,
                "mode": mode,
            },
        )

        allocation_results.append(
            {
                "billing_row_id": billing_row_id,
                "service_name": before.get("service_name"),
                "previous_balance": prev_balance,
                "new_balance": new_balance,
                "applied_amount": applied_amount,
                "new_status": new_status,
                "reference_no": payment_result["payment"].get("reference_no"),
            }
        )
        applied_total += applied_amount
        unapplied -= applied_amount

    emit_financial_event(
        sb,
        "debtor_payment_applied",
        performed_by=str(_user.id),
        amount=applied_total,
        detail={
            "client_name": client_name,
            "mode": mode,
            "allocations": allocation_results,
            "payment_method": payload.payment_method,
            "reference_no": base_reference,
            "payment_note": payload.notes,
        },
    )
    recompute_and_persist_metrics(sb, source="supabase_after_debtor_payment")

    return {
        "message": "Payment applied",
        "client_name": client_name,
        "mode": mode,
        "applied_total": applied_total,
        "unapplied_amount": max(unapplied, 0.0),
        "allocations": allocation_results,
    }


@router.get("/{billing_id}")
def get_billing(billing_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    result = sb.table("service_jobs").select("*").eq("id", billing_id).single().execute()
    if not result.data:
        raise HTTPException(404, "Billing row not found")
    return _serialize_billing_row(result.data, is_admin=user_is_admin(_user))


@router.get("/{billing_id}/activity")
def get_billing_activity(
    billing_id: str,
    limit: int = Query(100, ge=1, le=500),
    _user=Depends(get_current_user),
):
    sb = get_supabase()
    exists = sb.table("service_jobs").select("id").eq("id", billing_id).limit(1).execute().data or []
    if not exists:
        raise HTTPException(404, "Billing row not found")

    rows = (
        sb.table("crm_audit_log")
        .select("id,action,entity_type,entity_id,performed_by,before_value,after_value,detail,created_at")
        .eq("entity_id", billing_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    return {"items": rows, "count": len(rows)}


@router.post("", status_code=201)
def create_billing(payload: BillingCreate, _user=Depends(get_current_user)):
    sb = get_supabase()
    data = payload.model_dump(exclude_none=True)
    amount_paid = to_number(data.get("amount_paid", 0))
    unit_price = to_number(data.get("unit_price", 0))
    quantity = to_number(data.get("quantity", 1)) or 1
    if quantity <= 0:
        raise HTTPException(status_code=422, detail="Quantity must be greater than zero")
    total = unit_price * quantity
    total, amount_paid, payment_status = _compute_financial_state(total, amount_paid)

    service_columns = _service_job_columns(sb)
    actor_role = str(getattr(_user, "role", "staff") or "staff").strip().lower()
    actor_name = _actor_display_name(_user)
    now_iso = datetime.utcnow().isoformat()

    mapped = {
        "client_id": data.get("client_id"),
        "client_name": data.get("client_name"),
        "phone_number": data.get("phone_number") or data.get("client_phone"),
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
        "imei": data.get("imei"),
        "serial_number": data.get("serial_number"),
        "condition": data.get("condition"),
        "lock_status": data.get("lock_status"),
        "unlock_method": data.get("unlock_method"),
        "created_by": str(_user.id),
        "created_by_name": actor_name,
        "created_by_role": actor_role,
        "last_edited_by": str(_user.id),
        "last_edited_by_name": actor_name,
        "last_edited_at": now_iso,
        "assigned_staff_id": str(_user.id),
        "assigned_staff_name": actor_name,
    }
    mapped = {k: v for k, v in mapped.items() if k in service_columns and v is not None}
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
            "created_by_name": actor_name,
        },
    )
    emit_financial_event(
        sb,
        "invoice_updated",
        performed_by=str(_user.id),
        record_id=str(created.get("id")),
        amount=to_number(created.get("amount_charged")),
        detail={
            "reason": "invoice_create",
            "client_name": created.get("client_name"),
            "payment_status": created.get("payment_status"),
        },
    )
    recompute_and_persist_metrics(sb, source="supabase_after_billing_create")
    return _serialize_billing_row(created, is_admin=user_is_admin(_user))


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

    requested_status = None
    if "payment_status" in data:
        requested_status = _normalize_payment_status(data.get("payment_status"))
        data["payment_status"] = requested_status
    if "status" in data:
        requested_status = _normalize_payment_status(data.pop("status"))
        data["payment_status"] = requested_status
    if "amount_paid" in data:
        data["paid_amount"] = data.pop("amount_paid")
    if "client_phone" in data:
        data["phone_number"] = data.pop("client_phone")
    if "invoice_date" in data:
        data["service_date"] = data.pop("invoice_date")
    if "payment_date" in data:
        data["paid_date"] = data.pop("payment_date")

    existing_amount = to_number(existing_before.get("amount_charged"))
    existing_paid = to_number(existing_before.get("paid_amount"))
    existing_qty = to_number(existing_before.get("quantity") or 1) or 1
    actor_name = _actor_display_name(_user)
    now_iso = datetime.utcnow().isoformat()

    if "unit_price" in data or "quantity" in data:
        qty = to_number(data.get("quantity", existing_qty)) or 1
        if qty <= 0:
            raise HTTPException(status_code=422, detail="Quantity must be greater than zero")
        current_total = existing_amount
        inferred_unit = current_total / existing_qty
        unit = to_number(data.pop("unit_price", inferred_unit))
        if unit < 0:
            raise HTTPException(status_code=422, detail="Unit price cannot be negative")
        data["amount_charged"] = qty * unit

    # RETURNED must never be overwritten by automatic recomputation.
    if requested_status == "RETURNED":
        data["is_return"] = True
        data["paid_amount"] = 0
        data["payment_status"] = "RETURNED"
        data["paid_date"] = None
        data["paid_at"] = None
        data["returned_by"] = str(_user.id)
        data["returned_by_name"] = actor_name
        data["returned_at"] = now_iso
    else:
        total_input = data.get("amount_charged", existing_amount)
        paid_input = data.get("paid_amount", existing_paid)
        total, paid, payment_status = _compute_financial_state(total_input, paid_input)
        data["amount_charged"] = total
        data["paid_amount"] = paid
        data["payment_status"] = payment_status
        data["is_return"] = False
        if payment_status == "PAID":
            if not data.get("paid_date"):
                data["paid_date"] = data.get("service_date") or existing_before.get("paid_date") or datetime.utcnow().date().isoformat()
            data.setdefault("paid_at", datetime.utcnow().isoformat())
        else:
            data["paid_date"] = None
            data["paid_at"] = None

    data["last_edited_by"] = str(_user.id)
    data["last_edited_by_name"] = actor_name
    data["last_edited_at"] = now_iso

    service_columns = _service_job_columns(sb)
    data = {k: v for k, v in data.items() if k in service_columns}
    if not data:
        raise HTTPException(status_code=400, detail="No valid fields to update")

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
        detail={
            "fields_updated": sorted(list(data.keys())),
            "edited_by": str(_user.id),
            "edited_by_name": actor_name,
            "previous_amount": to_number(existing_before.get("amount_charged")),
            "new_amount": to_number(updated.get("amount_charged")),
            "previous_paid_amount": to_number(existing_before.get("paid_amount")),
            "new_paid_amount": to_number(updated.get("paid_amount")),
            "previous_status": str(existing_before.get("payment_status") or ""),
            "new_status": str(updated.get("payment_status") or ""),
            "timestamp": datetime.utcnow().isoformat(),
        },
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

    emit_financial_event(
        sb,
        "invoice_updated",
        performed_by=str(_user.id),
        record_id=billing_id,
        amount=to_number(updated.get("amount_charged")),
        detail={
            "previous_amount": to_number(existing_before.get("amount_charged")),
            "new_amount": to_number(updated.get("amount_charged")),
            "previous_paid_amount": before_paid,
            "new_paid_amount": after_paid,
            "previous_status": before_status,
            "new_status": after_status,
        },
    )
    recompute_and_persist_metrics(sb, source="supabase_after_billing_update")
    return _serialize_billing_row(updated, is_admin=user_is_admin(_user))


@router.delete("/{billing_id}", status_code=204)
def delete_billing(billing_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    existing = sb.table("service_jobs").select("*").eq("id", billing_id).limit(1).execute().data or []
    before_value = existing[0] if existing else None
    emit_financial_event(
        sb,
        "invoice_deleted",
        performed_by=str(_user.id),
        record_id=billing_id,
        amount=0.0,
        detail={"reason": "billing_delete"},
    )
    _log_billing_audit(
        sb,
        action="invoice_deleted",
        entity_id=billing_id,
        performed_by=str(_user.id),
        before_value=before_value,
        after_value={"deleted": True},
        detail={"reason": "billing_delete"},
    )
    sb.table("service_jobs").delete().eq("id", billing_id).execute()
    recompute_and_persist_metrics(sb, source="supabase_after_billing_delete")


@router.get("/debtors/{client_name}/items")
def get_debtor_items(client_name: str, _user=Depends(get_current_user)):
    """Get all outstanding items for a specific client (used in Debtor Details page)."""
    if not user_is_admin(_user):
        raise HTTPException(status_code=403, detail="Forbidden")
    sb = get_supabase()
    client_items = _open_client_invoices(sb, client_name)
    total_outstanding = sum(to_number(item.get("balance")) for item in client_items)
    invoice_ids = [str(i.get("id")) for i in client_items if i.get("id")]

    payment_history = []
    if invoice_ids:
        try:
            history_rows = (
                sb.table("payments")
                .select(
                    "id,service_job_id,billing_row_id,payment_amount,amount,payment_method,reference_no,"
                    "payment_date,payment_note,notes,created_at,applied_by_name,new_balance,new_status,"
                    "is_reversed,reversal_reason"
                )
                .in_("service_job_id", invoice_ids)
                .order("created_at", desc=True)
                .limit(1000)
                .execute()
                .data
                or []
            )
        except Exception:
            history_rows = (
                sb.table("payments")
                .select("id,billing_row_id,amount,payment_method,reference_no,payment_date,notes,created_at")
                .in_("billing_row_id", invoice_ids)
                .order("created_at", desc=True)
                .limit(1000)
                .execute()
                .data
                or []
            )
        payment_history = [
            {
                **row,
                "service_job_id": row.get("service_job_id") or row.get("billing_row_id"),
                "payment_amount": to_number(row.get("payment_amount") or row.get("amount")),
                "payment_note": row.get("payment_note") or row.get("notes"),
            }
            for row in history_rows
        ]

    return {
        "client_name": client_name,
        "items": client_items,
        "item_count": len(client_items),
        "total_outstanding": total_outstanding,
        "payment_history": payment_history,
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
