from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import uuid
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user

router = APIRouter()


class ClientCreate(BaseModel):
    name: Optional[str] = None
    client_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    phone_number: Optional[str] = None
    address: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None
    source: Optional[str] = "manual"


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    client_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    phone_number: Optional[str] = None
    address: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None


@router.get("")
def list_clients(
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _user=Depends(get_current_user),
):
    sb = get_supabase()
    offset = (page - 1) * page_size
    query = (
        sb.table("clients")
        .select("*", count="exact")
        .order("name")
        .range(offset, offset + page_size - 1)
    )
    if search:
        query = query.ilike("name", f"%{search}%")
    result = query.execute()
    items = [
        {
            **row,
            "client_name": row.get("name"),
            "phone_number": row.get("phone"),
        }
        for row in (result.data or [])
    ]
    total = int(result.count or 0)
    total_pages = max(1, (total + page_size - 1) // page_size)
    print(f"[clients] rows={len(items)} total={total} page={page} page_size={page_size}")
    return {
        "items": items,
        "data": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/{client_id}")
def get_client(client_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    result = sb.table("clients").select("*").eq("id", client_id).single().execute()
    if not result.data:
        raise HTTPException(404, "Client not found")
    return result.data


@router.post("", status_code=201)
def create_client(payload: ClientCreate, _user=Depends(get_current_user)):
    sb = get_supabase()
    data = payload.model_dump(exclude_none=True)
    name = (data.get("name") or data.get("client_name") or "").strip()
    phone = (data.get("phone") or data.get("phone_number") or "").strip()
    if not name:
        raise HTTPException(422, "name is required")
    if not phone:
        raise HTTPException(422, "phone is required")

    email = (data.get("email") or "").strip() or None

    mapped = {
        "id": str(uuid.uuid4()),
        "name": name,
        "phone": phone,
        "email": email,
        "address": data.get("address"),
        "company": data.get("company"),
        "notes": data.get("notes"),
    }
    result = sb.table("clients").insert(mapped).execute()
    return result.data[0]


@router.put("/{client_id}")
def update_client(client_id: str, payload: ClientUpdate, _user=Depends(get_current_user)):
    sb = get_supabase()
    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No fields to update")
    if "client_name" in data:
        data["name"] = data.pop("client_name")
    if "phone_number" in data:
        data["phone"] = data.pop("phone_number")
    if "email" in data:
        data["email"] = (data.get("email") or "").strip() or None
    if "name" in data:
        data["name"] = str(data.get("name") or "").strip()
    if "phone" in data:
        data["phone"] = str(data.get("phone") or "").strip()
    result = sb.table("clients").update(data).eq("id", client_id).execute()
    return result.data[0]


@router.delete("/{client_id}", status_code=204)
def delete_client(client_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    sb.table("clients").delete().eq("id", client_id).execute()
