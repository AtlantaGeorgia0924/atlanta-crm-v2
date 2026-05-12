from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from typing import Optional
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user

router = APIRouter()


class ClientCreate(BaseModel):
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None
    source: Optional[str] = "manual"


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
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
    return {"data": result.data, "total": result.count, "page": page, "page_size": page_size}


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
    result = sb.table("clients").insert(payload.model_dump(exclude_none=True)).execute()
    return result.data[0]


@router.put("/{client_id}")
def update_client(client_id: str, payload: ClientUpdate, _user=Depends(get_current_user)):
    sb = get_supabase()
    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No fields to update")
    result = sb.table("clients").update(data).eq("id", client_id).execute()
    return result.data[0]


@router.delete("/{client_id}", status_code=204)
def delete_client(client_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    sb.table("clients").delete().eq("id", client_id).execute()
