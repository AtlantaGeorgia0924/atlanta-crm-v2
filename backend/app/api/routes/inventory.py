from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import json
import uuid
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user

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
    return str(value or "").strip()


def _is_sold_out(row: dict) -> bool:
    quantity = _as_float(row.get("quantity"))
    sold_flag = bool(row.get("sold_out"))
    status = str(row.get("payment_status") or "").strip().upper()
    return quantity <= 0 or sold_flag or status == "SOLD"


def _serialize_item(row: dict) -> dict:
    return {
        **row,
        "unit_cost": row.get("cost_price", 0),
        "unit_price": row.get("selling_price", 0),
        "reorder_level": row.get("reorder_level", 0),
        "supplier": row.get("supplier") or _extract_supplier(row.get("description")),
        "location": row.get("location"),
        "is_active": True,
        "sold_out": _is_sold_out(row),
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


class StockCreate(BaseModel):
    item_name: str
    sku: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    quantity: float = 0
    unit: Optional[str] = "pcs"
    unit_cost: float = 0
    unit_price: float = 0
    reorder_level: float = 0
    supplier: Optional[str] = None
    location: Optional[str] = None
    source: Optional[str] = "manual"
    payment_status: Optional[str] = None


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
    location: Optional[str] = None
    is_active: Optional[bool] = None
    payment_status: Optional[str] = None


class StockBulkCreate(BaseModel):
    items: list[StockCreate]


class GroupCreate(BaseModel):
    name: str


class GroupUpdate(BaseModel):
    new_name: str


class GroupAssignment(BaseModel):
    item_ids: list[str]
    group_name: str


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
        data = [r for r in data if _is_sold_out(r)]
    else:
        data = [r for r in data if not _is_sold_out(r)]

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
    mapped = {
        "item_name": data.get("item_name"),
        "sku": data.get("sku"),
        "category": data.get("category"),
        "description": data.get("description"),
        "quantity": data.get("quantity", 0),
        "unit": data.get("unit", "pcs"),
        "cost_price": data.get("unit_cost", 0),
        "selling_price": data.get("unit_price", 0),
        "payment_status": (data.get("payment_status") or "").upper() or None,
    }
    result = sb.table("inventory_items").insert(mapped).execute()
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
                "category": data.get("category"),
                "description": data.get("description"),
                "quantity": data.get("quantity", 0),
                "unit": data.get("unit", "pcs"),
                "cost_price": data.get("unit_cost", 0),
                "selling_price": data.get("unit_price", 0),
                "payment_status": (data.get("payment_status") or "").upper() or None,
            }
        )

    if not rows:
        raise HTTPException(422, "No valid product rows provided")

    result = sb.table("inventory_items").insert(rows).execute()
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


@router.put("/{item_id}")
def update_item(item_id: str, payload: StockUpdate, _user=Depends(get_current_user)):
    sb = get_supabase()
    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No fields to update")
    if "unit_cost" in data:
        data["cost_price"] = data.pop("unit_cost")
    if "unit_price" in data:
        data["selling_price"] = data.pop("unit_price")
    data.pop("reorder_level", None)
    data.pop("supplier", None)
    data.pop("location", None)
    data.pop("is_active", None)
    if "payment_status" in data and data.get("payment_status") is not None:
        data["payment_status"] = str(data["payment_status"]).upper()
    result = sb.table("inventory_items").update(data).eq("id", item_id).execute()
    return result.data[0]


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    sb.table("inventory_items").delete().eq("id", item_id).execute()
