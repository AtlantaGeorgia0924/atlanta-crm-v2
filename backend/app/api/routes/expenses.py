from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.rbac import require_admin

router = APIRouter(dependencies=[Depends(require_admin)])


class ExpenseCreate(BaseModel):
    category: str
    description: Optional[str] = None
    amount: float
    expense_date: str
    paid_by: Optional[str] = None
    receipt_ref: Optional[str] = None
    notes: Optional[str] = None
    source: Optional[str] = "manual"


class ExpenseUpdate(BaseModel):
    category: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    expense_date: Optional[str] = None
    paid_by: Optional[str] = None
    receipt_ref: Optional[str] = None
    notes: Optional[str] = None


@router.get("")
def list_expenses(
    category: Optional[str] = Query(None),
    month: Optional[str] = Query(None, description="YYYY-MM"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _user=Depends(get_current_user),
):
    sb = get_supabase()
    offset = (page - 1) * page_size
    query = (
        sb.table("manual_expenses")
        .select("*", count="exact")
        .order("expense_date", desc=True)
        .range(offset, offset + page_size - 1)
    )
    if category:
        query = query.eq("category", category)
    if month:
        query = query.gte("expense_date", f"{month}-01").lte("expense_date", f"{month}-31")
    result = query.execute()
    return {"data": result.data, "total": result.count, "page": page, "page_size": page_size}


@router.post("", status_code=201)
def create_expense(payload: ExpenseCreate, _user=Depends(get_current_user)):
    sb = get_supabase()
    result = sb.table("manual_expenses").insert(payload.model_dump(exclude_none=True)).execute()
    return result.data[0]


@router.put("/{expense_id}")
def update_expense(expense_id: str, payload: ExpenseUpdate, _user=Depends(get_current_user)):
    sb = get_supabase()
    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No fields to update")
    result = sb.table("manual_expenses").update(data).eq("id", expense_id).execute()
    return result.data[0]


@router.delete("/{expense_id}", status_code=204)
def delete_expense(expense_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    sb.table("manual_expenses").delete().eq("id", expense_id).execute()
