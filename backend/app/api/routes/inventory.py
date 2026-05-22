from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import json
import uuid
from datetime import datetime
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.metrics_refresh import recompute_and_persist_metrics

router = APIRouter()
INVENTORY_GROUPS_KEY = "inventory_groups"


def _extract_supplier(description: Optional[str]) -> Optional[str]:
    text = str(description or "")
    marker = "Supplier:"
    if marker not in text:
        return None
    part = text.split(marker, 1)[1].strip()
    return part.split("|", 1)[0].strip() if part else None


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
    return {
        **row,
        "unit_cost": row.get("cost_price", 0),
        "unit_price": row.get("selling_price"),
        "reorder_level": row.get("reorder_level", 0),
        "supplier": row.get("supplier") or _extract_supplier(row.get("description")),
        "supplier_phone": row.get("supplier_phone"),
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


def _normalize_payment_status(value: Optional[str]) -> str:
    normalized = str(value or "").strip().upper()
    if normalized == "PARTIAL":
        return "PART PAYMENT"
    if normalized in {"PAID", "PART PAYMENT", "UNPAID"}:
        return normalized
    return "UNPAID"


def _normalize_phone(value: Optional[str]) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


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
    result = sb.table("inventory_items").select("*", count="exact").order("item_name").execute()
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
    data = payload.model_dump(exclude_none=True)
    # Upsert supplier as a client if phone supplied
    raw_supplier_phone = data.get("supplier_phone")
    supplier_name = str(data.get("supplier") or "").strip()
    if supplier_name or raw_supplier_phone:
        _upsert_client(sb, supplier_name, raw_supplier_phone)
    mapped = {
        "item_name": data.get("item_name"),
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
        "location": data.get("location"),
        "payment_status": (data.get("payment_status") or "").upper() or None,
        "item_expense_amount": data.get("item_expense_amount", 0),
        "item_expense_description": data.get("item_expense_description"),
        "item_expense_date": data.get("item_expense_date"),
        "condition": data.get("condition"),
        "lock_status": data.get("lock_status"),
        "previously_locked": data.get("previously_locked", False),
        "unlock_method": data.get("unlock_method"),
    }
    mapped = {k: v for k, v in mapped.items() if v is not None or k in ("previously_locked",)}
    if mapped.get("payment_status") == "PAID":
        mapped["paid_at"] = datetime.utcnow().isoformat()
    result = sb.table("inventory_items").insert(mapped).execute()
    recompute_and_persist_metrics(sb, source="supabase_after_inventory_create")
    return result.data[0]


@router.post("/bulk", status_code=201)
def create_items_bulk(payload: StockBulkCreate, _user=Depends(get_current_user)):
    sb = get_supabase()
    if not payload.items:
        raise HTTPException(400, "At least one product is required")

    rows = []
    for item in payload.items:
        data = item.model_dump(exclude_none=True)
        name = str(data.get("item_name") or "").strip()
        if not name:
            continue
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "item_name": name,
                "sku": data.get("sku"),
                "category": _normalize_group_name(data.get("category")),
                "description": data.get("description"),
                "quantity": data.get("quantity", 0),
                "unit": data.get("unit", "pcs"),
                "cost_price": data.get("unit_cost", 0),
                "selling_price": data.get("unit_price", 0),
                "payment_status": (data.get("payment_status") or "").upper() or None,
                "item_expense_amount": data.get("item_expense_amount", 0),
                "item_expense_description": data.get("item_expense_description"),
                "item_expense_date": data.get("item_expense_date"),
                "paid_at": datetime.utcnow().isoformat() if (data.get("payment_status") or "").upper() == "PAID" else None,
            }
        )

    if not rows:
        raise HTTPException(422, "No valid product rows provided")

    result = sb.table("inventory_items").insert(rows).execute()
    recompute_and_persist_metrics(sb, source="supabase_after_inventory_bulk_create")
    return {
        "inserted": len(result.data or []),
        "items": result.data or [],
    }


@router.get("/groups")
def list_groups(_user=Depends(get_current_user)):
    sb = get_supabase()
    rows = sb.table("inventory_items").select("category").execute().data or []
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

    rows = sb.table("inventory_items").select("id,category").eq("category", old_name).execute().data or []
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
    result = sb.table("inventory_items").select("*").eq("id", item_id).single().execute()
    if not result.data:
        raise HTTPException(404, "Item not found")
    return _serialize_item(result.data)


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
        rpc = (
            sb.rpc(
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
            .execute()
            .data
            or []
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
        columns = (
            sb.table("information_schema.columns")
            .select("column_name")
            .eq("table_schema", "public")
            .eq("table_name", "service_jobs")
            .execute()
            .data
            or []
        )
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

    recompute_and_persist_metrics(sb, source="supabase_after_inventory_sell")
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
        rpc = (
            sb.rpc(
                "reverse_inventory_sale",
                {
                    "p_sale_item_id": sale_item_id,
                    "p_reversed_by": str(_user.id),
                    "p_reason": payload.reason,
                },
            )
            .execute()
            .data
            or []
        )
    except Exception as exc:
        message = str(exc)
        if "already reversed" in message:
            raise HTTPException(409, message)
        raise HTTPException(500, f"Failed to reverse sale: {message}")

    if not rpc:
        raise HTTPException(500, "Reverse operation failed")

    restored = rpc[0]
    recompute_and_persist_metrics(sb, source="supabase_after_inventory_sale_reversal")
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
    existing = sb.table("inventory_items").select("*").eq("id", item_id).single().execute().data
    if not existing:
        raise HTTPException(404, "Item not found")

    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No fields to update")
    if "unit_cost" in data:
        data["cost_price"] = data.pop("unit_cost")
    if "unit_price" in data:
        data["selling_price"] = data.pop("unit_price")
    # Allowed passthrough fields (now including new device fields + supplier)
    ALLOWED_DIRECT = {"reorder_level", "supplier", "location", "is_active",
                      "condition", "lock_status", "previously_locked", "unlock_method"}
    # supplier_phone needs phone normalization
    if "supplier_phone" in data:
        normalized_phone = _normalize_phone(data.pop("supplier_phone"))
        data["supplier_phone"] = normalized_phone or None
        if data["supplier_phone"] is None:
            data.pop("supplier_phone")
    # Upsert supplier as client when contact info changes
    new_supplier = data.get("supplier") or existing.get("supplier")
    new_phone = data.get("supplier_phone") or existing.get("supplier_phone")
    if (data.get("supplier") or data.get("supplier_phone")) and new_supplier:
        _upsert_client(sb, str(new_supplier), new_phone)
    data.pop("is_active", None)  # do not pass is_active as-is; handle separately if needed
    if "payment_status" in data and data.get("payment_status") is not None:
        data["payment_status"] = str(data["payment_status"]).upper()
        if data["payment_status"] == "PAID":
            data.setdefault("paid_at", datetime.utcnow().isoformat())
    if "category" in data:
        data["category"] = _normalize_group_name(data.get("category"))
    result = sb.table("inventory_items").update(data).eq("id", item_id).execute()
    updated = result.data[0]

    before_qty = _as_float(existing.get("quantity"))
    after_qty = _as_float(updated.get("quantity"))
    if before_qty != after_qty:
        sb.table("inventory_transactions").insert(
            {
                "inventory_item_id": item_id,
                "action": "MANUAL_ADJUSTMENT",
                "quantity_change": after_qty - before_qty,
                "quantity_before": before_qty,
                "quantity_after": after_qty,
                "performed_by": str(_user.id),
                "note": "Manual inventory update",
            }
        ).execute()

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

    recompute_and_persist_metrics(sb, source="supabase_after_inventory_update")
    return updated


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    sb.table("inventory_items").delete().eq("id", item_id).execute()
    recompute_and_persist_metrics(sb, source="supabase_after_inventory_delete")
