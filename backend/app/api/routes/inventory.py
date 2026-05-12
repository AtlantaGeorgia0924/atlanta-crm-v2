from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user

router = APIRouter()


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


@router.get("")
def list_inventory(
    category: Optional[str] = Query(None),
    low_stock: bool = Query(False),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _user=Depends(get_current_user),
):
    sb = get_supabase()
    offset = (page - 1) * page_size
    query = (
        sb.table("inventory_items")
        .select("*", count="exact")
        .order("item_name")
        .range(offset, offset + page_size - 1)
    )
    if category:
        query = query.eq("category", category)
    if search:
        query = query.ilike("item_name", f"%{search}%")
    result = query.execute()
    data = [
        {
            **r,
            "unit_cost": r.get("cost_price", 0),
            "unit_price": r.get("selling_price", 0),
            "reorder_level": r.get("reorder_level", 0),
            "supplier": r.get("supplier"),
            "location": r.get("location"),
            "is_active": True,
        }
        for r in (result.data or [])
    ]
    if low_stock:
        data = [r for r in data if float(r["quantity"]) <= float(r["reorder_level"])]
    total = int(result.count or 0)
    total_pages = max(1, (total + page_size - 1) // page_size)
    print(f"[inventory] rows={len(data)} total={total} page={page} page_size={page_size}")
    return {
        "items": data,
        "data": data,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/{item_id}")
def get_item(item_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    result = sb.table("inventory_items").select("*").eq("id", item_id).single().execute()
    if not result.data:
        raise HTTPException(404, "Item not found")
    row = result.data
    row["unit_cost"] = row.get("cost_price", 0)
    row["unit_price"] = row.get("selling_price", 0)
    row["reorder_level"] = row.get("reorder_level", 0)
    row["supplier"] = row.get("supplier")
    row["location"] = row.get("location")
    row["is_active"] = True
    return row


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
    }
    result = sb.table("inventory_items").insert(mapped).execute()
    return result.data[0]


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
    result = sb.table("inventory_items").update(data).eq("id", item_id).execute()
    return result.data[0]


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    sb.table("inventory_items").delete().eq("id", item_id).execute()
