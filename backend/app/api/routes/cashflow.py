"""Cash flow reads from precomputed cash_flow_summary table.
Refresh is triggered async – never blocks the request."""
from fastapi import APIRouter, Depends, BackgroundTasks, Query
from typing import Optional
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user

router = APIRouter()


def _refresh_summary():
    """Run the DB function that recomputes cashflow_summary."""
    sb = get_supabase()
    sb.rpc("refresh_cashflow_summary").execute()


@router.get("")
def get_cashflow(
    month: Optional[str] = Query(None, description="YYYY-MM filter"),
    year: Optional[str] = Query(None, description="YYYY filter"),
    _user=Depends(get_current_user),
):
    """Read from precomputed summary – fast."""
    sb = get_supabase()
    query = sb.table("cashflow_summary").select("*").order("period_key", desc=True)
    if month:
        query = query.eq("period_key", month)
    elif year:
        query = query.like("period_key", f"{year}-%")
    result = query.execute()
    rows = []
    for row in (result.data or []):
        rows.append(
            {
                "period_month": row.get("period_key"),
                "total_revenue": row.get("weekly_paid_profits", 0),
                "total_expenses": row.get("weekly_expenses", 0),
                "total_allowances": row.get("allowances_withdrawn", 0),
                "gross_profit": row.get("weekly_net_profit", 0),
            }
        )
    return rows


@router.post("/refresh")
def trigger_refresh(background_tasks: BackgroundTasks, _user=Depends(get_current_user)):
    """Kick off async recalculation. Returns immediately."""
    background_tasks.add_task(_refresh_summary)
    return {"message": "Cash flow refresh started in the background."}
