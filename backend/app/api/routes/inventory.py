from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import json
import re
import time
import uuid
from datetime import datetime
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.financial_events import emit_financial_event
from app.core.metrics_refresh import refresh_financial_state

router = APIRouter()
INVENTORY_GROUPS_KEY = "inventory_groups"
_INVENTORY_COLUMNS_CACHE: set[str] | None = None


def _inventory_item_columns(sb) -> set[str]:
    global _INVENTORY_COLUMNS_CACHE
    if _INVENTORY_COLUMNS_CACHE is not None:
        return _INVENTORY_COLUMNS_CACHE
    try:
        rows = (
            sb.table("information_schema.columns")
            .select("column_name")
            .eq("table_schema", "public")
            .eq("table_name", "inventory_items")
            .execute()
            .data
            or []
        )
        _INVENTORY_COLUMNS_CACHE = {str(r.get("column_name")) for r in rows if r.get("column_name")}
    except Exception:
        _INVENTORY_COLUMNS_CACHE = set()

    if not _INVENTORY_COLUMNS_CACHE:
        # Fallback for environments where information_schema is restricted.
        try:
            probe_rows = sb.table("inventory_items").select("*").limit(1).execute().data or []
            if probe_rows and isinstance(probe_rows[0], dict):
                _INVENTORY_COLUMNS_CACHE = {str(k) for k in probe_rows[0].keys()}
        except Exception:
            pass

    return _INVENTORY_COLUMNS_CACHE


def _apply_active_inventory_filter(sb, query):
    if "deleted_at" in _inventory_item_columns(sb):
        return query.is_("deleted_at", "null")
    if "payment_status" in _inventory_item_columns(sb):
        return query.or_("payment_status.is.null,payment_status.neq.DELETED")
    return query


def _extract_supplier(description: Optional[str]) -> Optional[str]:
    text = str(description or "")
    marker = "Supplier:"
    if marker not in text:
        return None
    part = text.split(marker, 1)[1].strip()
    return part.split("|", 1)[0].strip() if part else None


def _extract_supplier_details(description: Optional[str]) -> dict:
    text = str(description or "")

    def _extract_segment(labels: list[str]) -> Optional[str]:
        for label in labels:
            match = re.search(rf"(?i)(?:^|\|)\s*{label}\s*:\s*([^|]+)", text)
            if match:
                value = str(match.group(1) or "").strip()
                if value:
                    return value
        return None

    supplier_name = _extract_segment(["supplier", "vendor", "seller"])
    supplier_contact = _extract_segment([r"supplier\s*contact", r"contact\s*person"])
    supplier_phone_raw = _extract_segment([r"supplier\s*phone", r"contact\s*phone", "phone"])
    supplier_phone = _normalize_phone(supplier_phone_raw) if supplier_phone_raw else None
    if supplier_phone == "":
        supplier_phone = None

    if supplier_contact and supplier_phone and _normalize_phone(supplier_contact) == supplier_phone:
        supplier_contact = None

    return {
        "supplier": supplier_name,
        "supplier_phone": supplier_phone,
        "supplier_contact": supplier_contact,
    }


def _merge_supplier_details_into_description(
    description: Optional[str],
    supplier_name: Optional[str],
    supplier_phone: Optional[str],
    supplier_contact: Optional[str],
) -> str:
    base_parts = [part.strip() for part in str(description or "").split("|") if str(part).strip()]
    filtered_parts = []
    for part in base_parts:
        lower = part.lower()
        if lower.startswith("supplier:"):
            continue
        if lower.startswith("supplier phone:"):
            continue
        if lower.startswith("supplier contact:"):
            continue
        if lower.startswith("contact person:"):
            continue
        if lower.startswith("vendor:"):
            continue
        if lower.startswith("seller:"):
            continue
        filtered_parts.append(part)

    name = str(supplier_name or "").strip()
    phone = _normalize_phone(supplier_phone) if supplier_phone else ""
    contact = str(supplier_contact or "").strip()

    if name:
        filtered_parts.append(f"Supplier: {name}")
    if phone:
        filtered_parts.append(f"Supplier Phone: {phone}")
    if contact:
        filtered_parts.append(f"Supplier Contact: {contact}")

    return " | ".join(filtered_parts)


def _as_float(value: object) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _normalize_group_name(value: Optional[str]) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    upper = raw.upper()
    canonical_rules = [
        ("IPHONE", "IPHONE"),
        ("SAMSUNG", "SAMSUNG GALAXY"),
        ("GALAXY", "SAMSUNG GALAXY"),
        ("IPAD", "IPAD"),
        ("IWATCH", "IWATCH"),
        ("APPLE WATCH", "IWATCH"),
        ("MACBOOK", "MACBOOK"),
        ("AIRPODS", "AIRPODS"),
    ]
    for token, canonical in canonical_rules:
        if token in upper:
            return canonical
    return upper


def _product_status(row: dict) -> str:
    status = str(row.get("product_status") or row.get("payment_status") or "").strip().upper()
    if status:
        return status
    quantity = _as_float(row.get("quantity"))
    if quantity <= 0:
        return "SOLD"
    return "AVAILABLE"


def _is_sold_out(row: dict) -> bool:
    quantity = _as_float(row.get("quantity"))
    sold_flag = bool(row.get("sold_out"))
    status = _product_status(row)
    return quantity <= 0 or sold_flag or status == "SOLD"


def _serialize_item(row: dict) -> dict:
    product_status = _product_status(row)
    extracted = _extract_supplier_details(row.get("description"))
    return {
        **row,
        "imei": row.get("imei"),
        "unit_cost": row.get("cost_price", 0),
        "unit_price": row.get("selling_price"),
        "reorder_level": row.get("reorder_level", 0),
        "supplier": row.get("supplier") or extracted.get("supplier") or _extract_supplier(row.get("description")),
        "supplier_phone": row.get("supplier_phone") or extracted.get("supplier_phone"),
        "supplier_contact": row.get("supplier_contact") or extracted.get("supplier_contact"),
        "storage": row.get("storage"),
        "color": row.get("color"),
        "location": row.get("location"),
        "product_status": product_status,
        "is_active": True,
        "sold_out": _is_sold_out({**row, "product_status": product_status}),
        # Device fields
        "condition": row.get("condition"),
        "lock_status": row.get("lock_status"),
        "previously_locked": row.get("previously_locked", False),
        "unlock_method": row.get("unlock_method"),
    }


def _load_groups(sb) -> list[str]:
    row = sb.table("app_settings").select("key,value").eq("key", INVENTORY_GROUPS_KEY).execute().data or []
    if not row:
        return []
    raw = row[0].get("value")
    try:
        decoded = json.loads(raw) if raw else []
    except Exception:
        decoded = []
    groups = [_normalize_group_name(item) for item in (decoded or [])]
    return sorted({group for group in groups if group})


def _save_groups(sb, groups: list[str]) -> list[str]:
    clean_groups = sorted({_normalize_group_name(group) for group in groups if _normalize_group_name(group)})
    payload = {
        "key": INVENTORY_GROUPS_KEY,
        "value": json.dumps(clean_groups),
        "description": "Inventory product groups",
    }
    existing = sb.table("app_settings").select("key").eq("key", INVENTORY_GROUPS_KEY).execute().data or []
    if existing:
        sb.table("app_settings").update({"value": payload["value"], "description": payload["description"]}).eq("key", INVENTORY_GROUPS_KEY).execute()
    else:
        sb.table("app_settings").insert(payload).execute()
    return clean_groups


CONDITION_OPTIONS = [
    "Brand New",
    "Open Box",
    "Used - Clean",
    "Used - Average",
    "Used - Faulty",
    "For Parts",
]

LOCK_STATUS_OPTIONS = [
    "Factory Unlocked",
    "Carrier Locked",
    "iCloud Locked",
    "MDM Locked",
    "Unknown",
]

UNLOCK_METHOD_OPTIONS = [
    "RSIM",
    "Official Unlock",
    "Bypass",
    "MDM Removal",
    "Other",
]


class StockCreate(BaseModel):
    item_name: str
    imei: Optional[str] = None
    sku: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    quantity: float = 0
    unit: Optional[str] = "pcs"
    unit_cost: float = 0
    unit_price: Optional[float] = None  # Optional – set at sale time
    reorder_level: float = 0
    supplier: Optional[str] = None
    supplier_phone: Optional[str] = None
    supplier_contact: Optional[str] = None
    storage: Optional[str] = None
    color: Optional[str] = None
    location: Optional[str] = None
    source: Optional[str] = "manual"
    payment_status: Optional[str] = None
    item_expense_amount: Optional[float] = 0
    item_expense_description: Optional[str] = None
    item_expense_date: Optional[str] = None
    # Device fields
    condition: Optional[str] = None
    lock_status: Optional[str] = None
    previously_locked: Optional[bool] = False
    unlock_method: Optional[str] = None


class StockUpdate(BaseModel):
    item_name: Optional[str] = None
    imei: Optional[str] = None
    sku: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    unit_cost: Optional[float] = None
    unit_price: Optional[float] = None
    reorder_level: Optional[float] = None
    supplier: Optional[str] = None
    supplier_phone: Optional[str] = None
    supplier_contact: Optional[str] = None
    storage: Optional[str] = None
    color: Optional[str] = None
    location: Optional[str] = None
    is_active: Optional[bool] = None
    payment_status: Optional[str] = None
    item_expense_amount: Optional[float] = None
    item_expense_description: Optional[str] = None
    item_expense_date: Optional[str] = None
    # Device fields
    condition: Optional[str] = None
    lock_status: Optional[str] = None
    previously_locked: Optional[bool] = None
    unlock_method: Optional[str] = None


class StockBulkCreate(BaseModel):
    items: list[StockCreate]


class GroupCreate(BaseModel):
    name: str


class GroupUpdate(BaseModel):
    new_name: str


class GroupAssignment(BaseModel):
    item_ids: list[str]
    group_name: str


class SellProductPayload(BaseModel):
    quantity: float
    selling_price: Optional[float] = None
    client_name: str
    client_phone: Optional[str] = None
    payment_status: str
    paid_amount: float = 0
    notes: Optional[str] = None


class ReverseSalePayload(BaseModel):
    sale_item_id: str
    reason: Optional[str] = None


class CheckoutItemPayload(BaseModel):
    item_id: str
    quantity: float
    unit_price: Optional[float] = None


class InventoryCheckoutPayload(BaseModel):
    items: list[CheckoutItemPayload]
    buyer_name: str
    buyer_phone: Optional[str] = None
    notes: Optional[str] = None
    amount_paid: float = 0
    payment_method: Optional[str] = "cash"
    discount: float = 0
    idempotency_key: str


class InventorySaleHistoryRow(BaseModel):
    sale_item_id: str
    sale_id: Optional[str] = None
    service_job_id: Optional[str] = None
    quantity: float = 0
    unit_price: float = 0
    amount_charged: float = 0
    paid_amount: float = 0
    balance: float = 0
    payment_status: Optional[str] = None
    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    sold_at: Optional[str] = None
    sold_by: Optional[str] = None
    assigned_staff_name: Optional[str] = None
    created_by_name: Optional[str] = None
    is_reversed: bool = False


def _normalize_payment_status(value: Optional[str]) -> str:
    normalized = str(value or "").strip().upper()
    if normalized == "PARTIAL":
        return "PART PAYMENT"
    if normalized in {"PAID", "PART PAYMENT", "UNPAID"}:
        return normalized
    return "UNPAID"


def _normalize_phone(value: Optional[str]) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _service_job_columns(sb) -> set[str]:
    try:
        rows = (
            sb.table("information_schema.columns")
            .select("column_name")
            .eq("table_schema", "public")
            .eq("table_name", "service_jobs")
            .execute()
            .data
            or []
        )
        columns = {str(c.get("column_name")) for c in rows if c.get("column_name")}
    except Exception:
        columns = set()

    if not columns:
        try:
            sample = sb.table("service_jobs").select("*").limit(1).execute().data or []
            if sample and isinstance(sample[0], dict):
                columns = {str(k) for k in sample[0].keys()}
        except Exception:
            columns = set()

    return columns


def _propagate_inventory_device_metadata_to_service_job(sb, service_job_id: str, inventory_item_id: str):
    service_job_id = str(service_job_id or "").strip()
    inventory_item_id = str(inventory_item_id or "").strip()
    if not service_job_id or not inventory_item_id:
        return

    service_rows = (
        sb.table("service_jobs")
        .select("*")
        .eq("id", service_job_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not service_rows:
        return
    service_row = service_rows[0]

    item_rows = (
        sb.table("inventory_items")
        .select("*")
        .eq("id", inventory_item_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not item_rows:
        return
    item = item_rows[0]

    updates = {
        "imei": item.get("imei") or None,
        "device_model": item.get("item_name") or None,
        "condition": item.get("condition") or None,
        "lock_status": item.get("lock_status") or None,
        "unlock_method": item.get("unlock_method") or None,
    }

    # Only fill missing values to avoid clobbering edited service rows.
    missing_only = {}
    for key, value in updates.items():
        current = str(service_row.get(key) or "").strip()
        next_value = str(value or "").strip()
        if not current and next_value:
            missing_only[key] = value

    if not missing_only:
        return

    allowed = _service_job_columns(sb)
    payload = {k: v for k, v in missing_only.items() if k in allowed and v is not None}
    if payload:
        sb.table("service_jobs").update(payload).eq("id", service_job_id).execute()


def _upsert_client(sb, client_name: str, client_phone: Optional[str]) -> Optional[str]:
    name = str(client_name or "").strip()
    phone = _normalize_phone(client_phone)
    if not name:
        return None

    rows = sb.table("clients").select("id,name,phone").execute().data or []
    if phone:
        for row in rows:
            if _normalize_phone(row.get("phone")) == phone:
                return str(row.get("id"))

    normalized_name = name.upper()
    for row in rows:
        if str(row.get("name") or "").strip().upper() == normalized_name:
            if phone and _normalize_phone(row.get("phone")) != phone:
                sb.table("clients").update({"phone": client_phone}).eq("id", row.get("id")).execute()
            return str(row.get("id"))

    created = (
        sb.table("clients")
        .insert({
            "id": str(uuid.uuid4()),
            "name": name,
            "phone": client_phone,
        })
        .execute()
        .data
        or []
    )
    return str(created[0].get("id")) if created else None


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


def _log_inventory_audit(
    sb,
    *,
    action: str,
    entity_type: str,
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
                "entity_type": entity_type,
                "entity_id": entity_id,
                "performed_by": performed_by,
                "before_value": before_value,
                "after_value": after_value,
                "detail": detail,
            }
        ).execute()
    except Exception:
        # Audit failures should never block the primary operation.
        pass


@router.get("")
def list_inventory(
    category: Optional[str] = Query(None),
    low_stock: bool = Query(False),
    search: Optional[str] = Query(None),
    view: str = Query("products"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _user=Depends(get_current_user),
):
    sb = get_supabase()
    query = sb.table("inventory_items").select("*", count="exact").order("item_name")
    result = _apply_active_inventory_filter(sb, query).execute()
    data = [_serialize_item(r) for r in (result.data or [])]

    if search:
        term = str(search).strip().lower()
        data = [r for r in data if term in str(r.get("item_name") or "").lower() or term in str(r.get("sku") or "").lower()]

    if category:
        data = [r for r in data if str(r.get("category") or "").strip() == category]

    mode = str(view or "products").strip().lower()
    if mode == "out_of_stock":
        data = [r for r in data if _product_status(r) == "SOLD" or _as_float(r.get("quantity")) <= 0]
    elif mode == "pending_deals":
        data = [r for r in data if _product_status(r) == "PENDING DEAL"]
    else:
        data = [r for r in data if _product_status(r) == "AVAILABLE" and _as_float(r.get("quantity")) > 0]

    if low_stock:
        data = [r for r in data if _as_float(r.get("quantity")) <= _as_float(r.get("reorder_level"))]

    total = len(data)
    offset = (page - 1) * page_size
    data = data[offset : offset + page_size]
    total_pages = max(1, (total + page_size - 1) // page_size)
    print(f"[inventory] rows={len(data)} total={total} page={page} page_size={page_size} view={mode}")
    return {
        "items": data,
        "data": data,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.post("", status_code=201)
def create_item(payload: StockCreate, _user=Depends(get_current_user)):
    sb = get_supabase()
    data = payload.model_dump(exclude_none=True, exclude_unset=True)
    # Upsert supplier as a client if phone supplied
    raw_supplier_phone = data.get("supplier_phone")
    supplier_name = str(data.get("supplier") or "").strip()
    supplier_contact = str(data.get("supplier_contact") or "").strip()
    if supplier_name or raw_supplier_phone:
        _upsert_client(sb, supplier_name, raw_supplier_phone)
    mapped = {
        "item_name": data.get("item_name"),
        "imei": str(data.get("imei") or "").strip() or None,
        "sku": data.get("sku"),
        "category": _normalize_group_name(data.get("category")),
        "description": data.get("description"),
        "quantity": data.get("quantity", 0),
        "unit": data.get("unit", "pcs"),
        "cost_price": data.get("unit_cost", 0),
        "selling_price": data.get("unit_price"),
        "reorder_level": data.get("reorder_level", 0),
        "supplier": supplier_name or None,
        "supplier_phone": _normalize_phone(raw_supplier_phone) or None,
        "supplier_contact": supplier_contact or None,
        "storage": data.get("storage"),
        "color": data.get("color"),
        "location": data.get("location"),
        "payment_status": (data.get("payment_status") or "").upper() or None,
        "item_expense_amount": data.get("item_expense_amount", 0),
        "item_expense_description": data.get("item_expense_description"),
        "item_expense_date": data.get("item_expense_date"),
        "condition": data.get("condition"),
        "lock_status": data.get("lock_status"),
        "previously_locked": data.get("previously_locked"),
        "unlock_method": data.get("unlock_method"),
    }
    mapped = {k: v for k, v in mapped.items() if v is not None}
    item_columns = _inventory_item_columns(sb)

    if item_columns and (
        "supplier" not in item_columns
        or "supplier_phone" not in item_columns
        or "supplier_contact" not in item_columns
    ):
        if supplier_name or raw_supplier_phone or supplier_contact:
            mapped["description"] = _merge_supplier_details_into_description(
                mapped.get("description") or data.get("description") or data.get("item_name"),
                supplier_name,
                _normalize_phone(raw_supplier_phone),
                supplier_contact,
            )

    if item_columns:
        mapped = {k: v for k, v in mapped.items() if k in item_columns}
    if mapped.get("payment_status") == "PAID":
        mapped["paid_at"] = datetime.utcnow().isoformat()
    insert_payload = dict(mapped)
    while True:
        try:
            result = sb.table("inventory_items").insert(insert_payload).execute()
            break
        except Exception as exc:
            msg = str(exc)
            missing = re.search(r"Could not find the '([^']+)' column", msg)
            if not missing:
                raise
            missing_col = missing.group(1)
            if missing_col not in insert_payload:
                raise
            insert_payload.pop(missing_col, None)

    refresh_financial_state(sb, source="supabase_after_inventory_create")
    return result.data[0]


@router.post("/bulk", status_code=201)
def create_items_bulk(payload: StockBulkCreate, _user=Depends(get_current_user)):
    sb = get_supabase()
    if not payload.items:
        raise HTTPException(400, "At least one product is required")

    rows = []
    item_columns = _inventory_item_columns(sb)
    for item in payload.items:
        data = item.model_dump(exclude_none=True, exclude_unset=True)
        name = str(data.get("item_name") or "").strip()
        if not name:
            continue
        row = {
                "id": str(uuid.uuid4()),
                "item_name": name,
            "imei": str(data.get("imei") or "").strip() or None,
                "sku": data.get("sku"),
                "category": _normalize_group_name(data.get("category")),
                "description": data.get("description"),
                "quantity": data.get("quantity", 0),
                "unit": data.get("unit", "pcs"),
                "cost_price": data.get("unit_cost", 0),
                "selling_price": data.get("unit_price", 0),
                "storage": data.get("storage"),
                "color": data.get("color"),
                "payment_status": (data.get("payment_status") or "").upper() or None,
                "item_expense_amount": data.get("item_expense_amount", 0),
                "item_expense_description": data.get("item_expense_description"),
                "item_expense_date": data.get("item_expense_date"),
                "paid_at": datetime.utcnow().isoformat() if (data.get("payment_status") or "").upper() == "PAID" else None,
        }
        row = {k: v for k, v in row.items() if v is not None}
        if item_columns:
            row = {k: v for k, v in row.items() if k in item_columns}
        rows.append(row)

    if not rows:
        raise HTTPException(422, "No valid product rows provided")

    result = sb.table("inventory_items").insert(rows).execute()
    refresh_financial_state(sb, source="supabase_after_inventory_bulk_create")
    return {
        "inserted": len(result.data or []),
        "items": result.data or [],
    }


@router.get("/groups")
def list_groups(_user=Depends(get_current_user)):
    sb = get_supabase()
    query = sb.table("inventory_items").select("category")
    rows = _apply_active_inventory_filter(sb, query).execute().data or []
    data_groups = {
        _normalize_group_name(row.get("category"))
        for row in rows
        if _normalize_group_name(row.get("category"))
    }
    configured_groups = set(_load_groups(sb))
    groups = sorted(configured_groups.union(data_groups))

    counts = {group: 0 for group in groups}
    for row in rows:
        group = _normalize_group_name(row.get("category"))
        if group in counts:
            counts[group] += 1

    return {
        "groups": [{"name": name, "product_count": counts.get(name, 0)} for name in groups],
        "total": len(groups),
    }


@router.post("/groups", status_code=201)
def create_group(payload: GroupCreate, _user=Depends(get_current_user)):
    sb = get_supabase()
    group_name = _normalize_group_name(payload.name)
    if not group_name:
        raise HTTPException(422, "Group name is required")
    groups = set(_load_groups(sb))
    groups.add(group_name)
    stored = _save_groups(sb, list(groups))
    return {"name": group_name, "groups": stored}


@router.put("/groups/{group_name}")
def rename_group(group_name: str, payload: GroupUpdate, _user=Depends(get_current_user)):
    sb = get_supabase()
    old_name = _normalize_group_name(group_name)
    new_name = _normalize_group_name(payload.new_name)
    if not old_name or not new_name:
        raise HTTPException(422, "Both current and new group names are required")

    rows_query = sb.table("inventory_items").select("id,category").eq("category", old_name)
    rows = _apply_active_inventory_filter(sb, rows_query).execute().data or []
    for row in rows:
        sb.table("inventory_items").update({"category": new_name}).eq("id", row.get("id")).execute()

    groups = set(_load_groups(sb))
    if old_name in groups:
        groups.remove(old_name)
    groups.add(new_name)
    stored = _save_groups(sb, list(groups))
    return {"name": new_name, "updated_items": len(rows), "groups": stored}


@router.post("/assign-group")
def assign_items_to_group(payload: GroupAssignment, _user=Depends(get_current_user)):
    sb = get_supabase()
    group_name = _normalize_group_name(payload.group_name)
    item_ids = [str(item_id).strip() for item_id in payload.item_ids if str(item_id).strip()]
    if not group_name:
        raise HTTPException(422, "Group name is required")
    if not item_ids:
        raise HTTPException(422, "At least one item id is required")

    for item_id in item_ids:
        sb.table("inventory_items").update({"category": group_name}).eq("id", item_id).execute()

    groups = set(_load_groups(sb))
    groups.add(group_name)
    _save_groups(sb, list(groups))
    return {"updated": len(item_ids), "group_name": group_name}


@router.get("/{item_id}")
def get_item(item_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    query = sb.table("inventory_items").select("*").eq("id", item_id).limit(1)
    rows = _apply_active_inventory_filter(sb, query).execute().data or []
    if not rows:
        raise HTTPException(404, "Item not found")
    return _serialize_item(rows[0])


@router.get("/{item_id}/transactions")
def get_item_transactions(
    item_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _user=Depends(get_current_user),
):
    sb = get_supabase()
    offset = (page - 1) * page_size
    result = (
        sb.table("inventory_transactions")
        .select("*", count="exact")
        .eq("inventory_item_id", item_id)
        .order("created_at", desc=True)
        .range(offset, offset + page_size - 1)
        .execute()
    )
    items = result.data or []
    total = int(result.count or 0)
    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }


@router.get("/{item_id}/sales-history")
def get_item_sales_history(
    item_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _user=Depends(get_current_user),
):
    sb = get_supabase()
    offset = (page - 1) * page_size

    result = (
        sb.table("inventory_sale_items")
        .select(
            "id,sale_id,service_job_id,quantity,unit_price,amount_charged,sold_at,sold_by,is_reversed",
            count="exact",
        )
        .eq("source_inventory_item_id", item_id)
        .order("sold_at", desc=True)
        .range(offset, offset + page_size - 1)
        .execute()
    )

    sale_items = result.data or []
    total = int(result.count or 0)
    total_pages = max(1, (total + page_size - 1) // page_size)

    sale_ids = [str(row.get("sale_id")) for row in sale_items if row.get("sale_id")]
    service_job_ids = [str(row.get("service_job_id")) for row in sale_items if row.get("service_job_id")]

    sales_map: dict[str, dict] = {}
    if sale_ids:
        sale_rows = (
            sb.table("inventory_sales")
            .select("id,client_name,client_phone,paid_amount,balance,payment_status,sold_by,sold_at")
            .in_("id", sale_ids)
            .execute()
            .data
            or []
        )
        sales_map = {str(row.get("id")): row for row in sale_rows if row.get("id")}

    service_map: dict[str, dict] = {}
    if service_job_ids:
        service_rows = (
            sb.table("service_jobs")
            .select("id,assigned_staff_name,created_by_name")
            .in_("id", service_job_ids)
            .execute()
            .data
            or []
        )
        service_map = {str(row.get("id")): row for row in service_rows if row.get("id")}

    items: list[dict] = []
    for row in sale_items:
        sale_id = str(row.get("sale_id") or "")
        service_job_id = str(row.get("service_job_id") or "")
        sale_header = sales_map.get(sale_id, {})
        service_meta = service_map.get(service_job_id, {})

        items.append(
            {
                "sale_item_id": str(row.get("id") or ""),
                "sale_id": sale_id or None,
                "service_job_id": service_job_id or None,
                "quantity": _as_float(row.get("quantity")),
                "unit_price": _as_float(row.get("unit_price")),
                "amount_charged": _as_float(row.get("amount_charged")),
                "paid_amount": _as_float(sale_header.get("paid_amount")),
                "balance": _as_float(sale_header.get("balance")),
                "payment_status": sale_header.get("payment_status"),
                "client_name": sale_header.get("client_name"),
                "client_phone": sale_header.get("client_phone"),
                "sold_at": row.get("sold_at") or sale_header.get("sold_at"),
                "sold_by": row.get("sold_by") or sale_header.get("sold_by"),
                "assigned_staff_name": service_meta.get("assigned_staff_name"),
                "created_by_name": service_meta.get("created_by_name"),
                "is_reversed": bool(row.get("is_reversed")),
            }
        )

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }


@router.post("/checkout", status_code=201)
def checkout_inventory_cart(payload: InventoryCheckoutPayload, _user=Depends(get_current_user)):
    sb = get_supabase()

    if not payload.items:
        raise HTTPException(422, "Cart is empty")

    buyer_name = str(payload.buyer_name or "").strip()
    if not buyer_name:
        raise HTTPException(422, "Buyer/client name is required")

    idempotency_key = str(payload.idempotency_key or "").strip()
    if not idempotency_key:
        raise HTTPException(422, "idempotency_key is required")

    client_id = _upsert_client(sb, buyer_name, payload.buyer_phone)
    items_payload = []
    for item in payload.items:
        item_id = str(item.item_id or "").strip()
        quantity = _as_float(item.quantity)
        if not item_id:
            raise HTTPException(422, "Every cart item requires item_id")
        if quantity <= 0:
            raise HTTPException(422, "Every cart item quantity must be greater than zero")
        line_unit_price = _as_float(item.unit_price)
        items_payload.append(
            {
                "item_id": item_id,
                "quantity": quantity,
                "unit_price": line_unit_price if line_unit_price > 0 else None,
            }
        )

    try:
        rpc = _rpc_with_retry(
            sb,
            "checkout_inventory_cart_tx",
            {
                "p_items": items_payload,
                "p_client_id": client_id,
                "p_client_name": buyer_name,
                "p_client_phone": payload.buyer_phone,
                "p_amount_paid": max(_as_float(payload.amount_paid), 0),
                "p_payment_method": payload.payment_method,
                "p_discount": max(_as_float(payload.discount), 0),
                "p_notes": payload.notes,
                "p_sold_by": str(_user.id),
                "p_idempotency_key": idempotency_key,
            },
        )
    except Exception as exc:
        message = str(exc)
        if "Insufficient stock" in message or "Negative stock prevented" in message:
            raise HTTPException(409, message)
        if "idempotency_key is required" in message:
            raise HTTPException(422, message)
        raise HTTPException(500, f"Checkout failed: {message}")

    if not rpc:
        raise HTTPException(500, "Checkout failed")

    row = rpc[0]
    sale_id = row.get("sale_id")
    sale_items = (
        sb.table("inventory_sale_items")
        .select("id,service_job_id,source_inventory_item_id,quantity,amount_charged")
        .eq("sale_id", sale_id)
        .order("created_at")
        .execute()
        .data
        or []
    )

    for sale_item in sale_items:
        _propagate_inventory_device_metadata_to_service_job(
            sb,
            str(sale_item.get("service_job_id") or ""),
            str(sale_item.get("source_inventory_item_id") or ""),
        )

    emit_financial_event(
        sb,
        "inventory_sale",
        performed_by=str(_user.id),
        record_id=str(sale_id or ""),
        amount=_as_float(row.get("paid_amount")),
        detail={
            "transaction_reference": row.get("transaction_reference"),
            "total_amount": _as_float(row.get("total_amount")),
            "balance": _as_float(row.get("balance")),
            "item_count": int(row.get("item_count") or 0),
        },
    )
    refresh_financial_state(sb, source="supabase_after_inventory_cart_checkout")
    return {
        "sale_id": sale_id,
        "transaction_reference": row.get("transaction_reference"),
        "payment_status": row.get("payment_status"),
        "total_amount": _as_float(row.get("total_amount")),
        "amount_paid": _as_float(row.get("paid_amount")),
        "balance": _as_float(row.get("balance")),
        "item_count": int(row.get("item_count") or 0),
        "service_job_ids": [str(sale_item.get("service_job_id")) for sale_item in sale_items if sale_item.get("service_job_id")],
        "items": sale_items,
    }


@router.post("/{item_id}/sell", status_code=201)
def sell_product(item_id: str, payload: SellProductPayload, _user=Depends(get_current_user)):
    sb = get_supabase()
    quantity = _as_float(payload.quantity)
    if quantity <= 0:
        raise HTTPException(422, "Quantity must be greater than zero")

    client_name = str(payload.client_name or "").strip()
    if not client_name:
        raise HTTPException(422, "Client name is required")

    status = _normalize_payment_status(payload.payment_status)
    paid_amount = max(_as_float(payload.paid_amount), 0)
    selling_price = _as_float(payload.selling_price)
    if payload.selling_price is not None and selling_price <= 0:
        raise HTTPException(422, "Selling price must be greater than zero")

    client_id = _upsert_client(sb, client_name, payload.client_phone)

    try:
        rpc = _rpc_with_retry(
            sb,
            "sell_inventory_product",
            {
                "p_inventory_item_id": item_id,
                "p_quantity": quantity,
                "p_unit_price": selling_price,
                "p_client_id": client_id,
                "p_client_name": client_name,
                "p_client_phone": payload.client_phone,
                "p_paid_amount": paid_amount,
                "p_payment_status": status,
                "p_notes": payload.notes,
                "p_sold_by": str(_user.id),
            },
        )
    except Exception as exc:
        message = str(exc)
        if "Insufficient stock" in message:
            raise HTTPException(409, message)
        raise HTTPException(500, f"Failed to sell product: {message}")

    if not rpc:
        raise HTTPException(500, "Sell operation failed")

    sold = rpc[0]
    service_job_id = str(sold.get("service_job_id") or "").strip()
    if service_job_id:
        actor_role = str(getattr(_user, "role", "staff") or "staff").strip().lower()
        actor_label = "Admin" if actor_role == "admin" else "Staff"
        actor_name = (str(getattr(_user, "full_name", "") or "").strip() or str(getattr(_user, "email", "") or "").strip())
        display_name = f"{actor_name} ({actor_label})" if actor_name else actor_label
        try:
            columns = (
                sb.table("information_schema.columns")
                .select("column_name")
                .eq("table_schema", "public")
                .eq("table_name", "service_jobs")
                .execute()
                .data
                or []
            )
        except Exception:
            columns = []
        column_names = {str(c.get("column_name")) for c in columns if c.get("column_name")}
        ownership_payload = {
            "created_by": str(_user.id),
            "created_by_name": display_name,
            "created_by_role": actor_role,
            "last_edited_by": str(_user.id),
            "last_edited_by_name": display_name,
            "last_edited_at": datetime.utcnow().isoformat(),
            "assigned_staff_id": str(_user.id),
            "assigned_staff_name": display_name,
        }
        ownership_payload = {k: v for k, v in ownership_payload.items() if k in column_names}
        if ownership_payload:
            sb.table("service_jobs").update(ownership_payload).eq("id", service_job_id).execute()

        _propagate_inventory_device_metadata_to_service_job(sb, service_job_id, item_id)

    emit_financial_event(
        sb,
        "inventory_sale",
        performed_by=str(_user.id),
        record_id=str(sold.get("sale_item_id") or sold.get("sale_id") or ""),
        amount=_as_float(sold.get("amount_charged")),
        detail={
            "service_job_id": sold.get("service_job_id"),
            "remaining_quantity": _as_float(sold.get("remaining_quantity")),
            "balance": _as_float(sold.get("balance")),
        },
    )
    refresh_financial_state(sb, source="supabase_after_inventory_sell")
    return {
        "sale_id": sold.get("sale_id"),
        "sale_item_id": sold.get("sale_item_id"),
        "service_job_id": sold.get("service_job_id"),
        "remaining_quantity": _as_float(sold.get("remaining_quantity")),
        "amount_charged": _as_float(sold.get("amount_charged")),
        "balance": _as_float(sold.get("balance")),
        "profit": _as_float(sold.get("profit")),
        "payment_status": status,
    }


@router.post("/sales/reverse")
def reverse_sold_product(payload: ReverseSalePayload, _user=Depends(get_current_user)):
    sb = get_supabase()
    sale_item_id = str(payload.sale_item_id or "").strip()
    if not sale_item_id:
        raise HTTPException(422, "sale_item_id is required")

    try:
        rpc = _rpc_with_retry(
            sb,
            "reverse_inventory_sale",
            {
                "p_sale_item_id": sale_item_id,
                "p_reversed_by": str(_user.id),
                "p_reason": payload.reason,
            },
        )
    except Exception as exc:
        message = str(exc)
        if "already reversed" in message:
            raise HTTPException(409, message)
        raise HTTPException(500, f"Failed to reverse sale: {message}")

    if not rpc:
        raise HTTPException(500, "Reverse operation failed")

    restored = rpc[0]
    emit_financial_event(
        sb,
        "inventory_sale_reversed",
        performed_by=str(_user.id),
        record_id=str(restored.get("sale_item_id") or ""),
        amount=0.0,
        detail={
            "inventory_item_id": restored.get("inventory_item_id"),
            "service_job_id": restored.get("service_job_id"),
            "restored_quantity": _as_float(restored.get("restored_quantity")),
        },
    )
    refresh_financial_state(sb, source="supabase_after_inventory_sale_reversal")
    return {
        "sale_item_id": restored.get("sale_item_id"),
        "inventory_item_id": restored.get("inventory_item_id"),
        "restored_quantity": _as_float(restored.get("restored_quantity")),
        "new_inventory_quantity": _as_float(restored.get("new_inventory_quantity")),
        "service_job_id": restored.get("service_job_id"),
    }


@router.put("/{item_id}")
def update_item(item_id: str, payload: StockUpdate, _user=Depends(get_current_user)):
    sb = get_supabase()
    existing_query = sb.table("inventory_items").select("*").eq("id", item_id).limit(1)
    existing_rows = _apply_active_inventory_filter(sb, existing_query).execute().data or []
    existing = existing_rows[0] if existing_rows else None
    if not existing:
        raise HTTPException(404, "Item not found")

    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No fields to update")
    if "unit_cost" in data:
        data["cost_price"] = data.pop("unit_cost")
    if "unit_price" in data:
        data["selling_price"] = data.pop("unit_price")
    if "imei" in data:
        data["imei"] = str(data.get("imei") or "").strip() or None
        if data["imei"] is None:
            data.pop("imei")
    # supplier_phone needs phone normalization
    if "supplier_phone" in data:
        normalized_phone = _normalize_phone(data.pop("supplier_phone"))
        data["supplier_phone"] = normalized_phone or None
        if data["supplier_phone"] is None:
            data.pop("supplier_phone")
    if "supplier_contact" in data:
        data["supplier_contact"] = str(data.get("supplier_contact") or "").strip() or None
        if data["supplier_contact"] is None:
            data.pop("supplier_contact")

    item_columns = _inventory_item_columns(sb)
    existing_supplier_details = _extract_supplier_details(existing.get("description"))
    existing_supplier_name = existing.get("supplier") or existing_supplier_details.get("supplier")
    existing_supplier_phone = existing.get("supplier_phone") or existing_supplier_details.get("supplier_phone")
    existing_supplier_contact = existing.get("supplier_contact") or existing_supplier_details.get("supplier_contact")

    supplier_in_payload = any(k in data for k in ("supplier", "supplier_phone", "supplier_contact"))
    if supplier_in_payload and item_columns and (
        "supplier" not in item_columns
        or "supplier_phone" not in item_columns
        or "supplier_contact" not in item_columns
    ):
        data["description"] = _merge_supplier_details_into_description(
            data.get("description", existing.get("description")),
            data.get("supplier", existing_supplier_name),
            data.get("supplier_phone", existing_supplier_phone),
            data.get("supplier_contact", existing_supplier_contact),
        )

    if item_columns:
        data = {k: v for k, v in data.items() if k in item_columns}

    # Upsert supplier as client when contact info changes
    new_supplier = data.get("supplier") or existing_supplier_name
    new_phone = data.get("supplier_phone") or existing_supplier_phone
    if (data.get("supplier") or data.get("supplier_phone")) and new_supplier:
        _upsert_client(sb, str(new_supplier), new_phone)

    data.pop("is_active", None)  # do not pass is_active as-is; handle separately if needed
    if "payment_status" in data and data.get("payment_status") is not None:
        data["payment_status"] = str(data["payment_status"]).upper()
        if data["payment_status"] == "PAID":
            data.setdefault("paid_at", datetime.utcnow().isoformat())
    if "category" in data:
        data["category"] = _normalize_group_name(data.get("category"))

    if not data:
        raise HTTPException(400, "No valid fields to update")

    result = sb.table("inventory_items").update(data).eq("id", item_id).execute()
    updated = result.data[0]

    before_qty = _as_float(existing.get("quantity"))
    after_qty = _as_float(updated.get("quantity"))
    if before_qty != after_qty:
        qty_delta = after_qty - before_qty
        sb.table("inventory_transactions").insert(
            {
                "inventory_item_id": item_id,
                "action": "MANUAL_ADJUSTMENT",
                "quantity_change": qty_delta,
                "quantity_before": before_qty,
                "quantity_after": after_qty,
                "performed_by": str(_user.id),
                "note": "Manual inventory update",
            }
        ).execute()
        try:
            sb.table("inventory_movement_history").insert(
                {
                    "inventory_item_id": item_id,
                    "movement_type": "MANUAL_ADJUSTMENT",
                    "quantity_change": qty_delta,
                    "quantity_before": before_qty,
                    "quantity_after": after_qty,
                    "reference_type": "inventory_item",
                    "reference_id": item_id,
                    "performed_by": str(_user.id),
                    "note": "Manual inventory update",
                    "metadata": {"fields_updated": sorted(list(data.keys()))},
                }
            ).execute()
            sb.table("stock_adjustment_audit").insert(
                {
                    "inventory_item_id": item_id,
                    "adjustment_type": "MANUAL_ADJUSTMENT",
                    "quantity_before": before_qty,
                    "quantity_after": after_qty,
                    "quantity_change": qty_delta,
                    "reason": "Manual inventory update",
                    "reference_type": "inventory_item",
                    "reference_id": item_id,
                    "performed_by": str(_user.id),
                    "detail": {"fields_updated": sorted(list(data.keys()))},
                }
            ).execute()
        except Exception:
            pass

    _log_inventory_audit(
        sb,
        action="inventory_item_updated",
        entity_type="inventory_item",
        entity_id=item_id,
        performed_by=str(_user.id),
        before_value={
            "quantity": before_qty,
            "selling_price": _as_float(existing.get("selling_price")),
            "cost_price": _as_float(existing.get("cost_price")),
        },
        after_value={
            "quantity": after_qty,
            "selling_price": _as_float(updated.get("selling_price")),
            "cost_price": _as_float(updated.get("cost_price")),
        },
        detail={"fields_updated": sorted(list(data.keys()))},
    )

    if before_qty != after_qty:
        emit_financial_event(
            sb,
            "inventory_quantity_corrected",
            performed_by=str(_user.id),
            record_id=item_id,
            amount=0.0,
            detail={
                "quantity_before": before_qty,
                "quantity_after": after_qty,
            },
        )
    refresh_financial_state(sb, source="supabase_after_inventory_update")
    return updated


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    existing_query = sb.table("inventory_items").select("id").eq("id", item_id).limit(1)
    existing = _apply_active_inventory_filter(sb, existing_query).execute().data or []
    if not existing:
        raise HTTPException(404, "Item not found")

    item_columns = _inventory_item_columns(sb)
    if "deleted_at" in item_columns:
        sb.table("inventory_items").update(
            {
                "deleted_at": datetime.utcnow().isoformat(),
                "deleted_by": str(_user.id),
            }
        ).eq("id", item_id).execute()
    elif "payment_status" in item_columns:
        # Legacy-schema fallback: mark as deleted without hard-deleting referenced rows.
        sb.table("inventory_items").update(
            {
                "payment_status": "DELETED",
            }
        ).eq("id", item_id).execute()
    else:
        raise HTTPException(500, "Inventory delete is unavailable: soft-delete columns are missing")
    emit_financial_event(
        sb,
        "inventory_item_deleted",
        performed_by=str(_user.id),
        record_id=item_id,
        amount=0.0,
    )
    refresh_financial_state(sb, source="supabase_after_inventory_delete")
