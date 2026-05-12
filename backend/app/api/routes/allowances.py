from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user

router = APIRouter()


class AllowanceCreate(BaseModel):
    staff_name: str
    allowance_type: str
    amount: float
    allowance_date: str
    approved_by: Optional[str] = None
    notes: Optional[str] = None


class AllowanceUpdate(BaseModel):
    staff_name: Optional[str] = None
    allowance_type: Optional[str] = None
    amount: Optional[float] = None
    allowance_date: Optional[str] = None
    approved_by: Optional[str] = None
    notes: Optional[str] = None


@router.get("")
def list_allowances(
    staff_name: Optional[str] = Query(None),
    month: Optional[str] = Query(None, description="YYYY-MM"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _user=Depends(get_current_user),
):
    sb = get_supabase()
    offset = (page - 1) * page_size
    query = (
        sb.table("allowance_withdrawals")
        .select("*", count="exact")
        .order("withdrawal_date", desc=True)
        .range(offset, offset + page_size - 1)
    )
    if staff_name:
        query = query.ilike("withdrawn_by", f"%{staff_name}%")
    if month:
        query = query.gte("withdrawal_date", f"{month}-01").lte("withdrawal_date", f"{month}-31")
    result = query.execute()
    data = []
    for row in (result.data or []):
        note = row.get("notes") or ""
        allowance_type = "other"
        if note.startswith("type:"):
            allowance_type = note.split("\n", 1)[0].replace("type:", "").strip() or "other"
        data.append(
            {
                **row,
                "staff_name": row.get("withdrawn_by"),
                "allowance_date": row.get("withdrawal_date"),
                "allowance_type": allowance_type,
                "approved_by": None,
            }
        )
    return {"data": data, "total": result.count, "page": page, "page_size": page_size}


@router.post("", status_code=201)
def create_allowance(payload: AllowanceCreate, _user=Depends(get_current_user)):
    sb = get_supabase()
    notes = payload.notes or ""
    notes = f"type:{payload.allowance_type}\n{notes}".strip()
    result = sb.table("allowance_withdrawals").insert(
        {
            "withdrawn_by": payload.staff_name,
            "amount": payload.amount,
            "withdrawal_date": payload.allowance_date,
            "notes": notes,
        }
    ).execute()
    return result.data[0]


@router.put("/{allowance_id}")
def update_allowance(allowance_id: str, payload: AllowanceUpdate, _user=Depends(get_current_user)):
    sb = get_supabase()
    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No fields to update")
    mapped = {}
    if "staff_name" in data:
        mapped["withdrawn_by"] = data["staff_name"]
    if "amount" in data:
        mapped["amount"] = data["amount"]
    if "allowance_date" in data:
        mapped["withdrawal_date"] = data["allowance_date"]
    if "notes" in data or "allowance_type" in data:
        allowance_type = data.get("allowance_type", "other")
        mapped["notes"] = f"type:{allowance_type}\n{data.get('notes') or ''}".strip()
    result = sb.table("allowance_withdrawals").update(mapped).eq("id", allowance_id).execute()
    return result.data[0]


@router.delete("/{allowance_id}", status_code=204)
def delete_allowance(allowance_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    sb.table("allowance_withdrawals").delete().eq("id", allowance_id).execute()
