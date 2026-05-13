"""Cash flow totals derived from source tables using shared financial logic."""
from fastapi import APIRouter, Depends, Query
from typing import Optional
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.financials import is_valid_service_record, month_key, to_number

router = APIRouter()


def _read_all(sb, table: str, columns: str, batch_size: int = 1000):
    rows = []
    start = 0
    while True:
        end = start + batch_size - 1
        chunk = sb.table(table).select(columns).range(start, end).execute().data or []
        rows.extend(chunk)
        if len(chunk) < batch_size:
            break
        start += batch_size
    return rows


@router.get("")
def get_cashflow(
    month: Optional[str] = Query(None, description="YYYY-MM filter"),
    year: Optional[str] = Query(None, description="YYYY filter"),
    _user=Depends(get_current_user),
):
    """Compute monthly cash flow directly from source tables."""
    sb = get_supabase()
    billing_rows = _read_all(sb, "service_jobs", "service_name,description,paid_amount,paid_date,service_date")
    expense_rows = _read_all(sb, "manual_expenses", "amount,expense_date")
    allowance_rows = _read_all(sb, "allowance_withdrawals", "amount,withdrawal_date")

    month_totals = {}

    def _accept_period(key: Optional[str]) -> bool:
        if not key:
            return False
        if month:
            return key == month
        if year:
            return key.startswith(f"{year}-")
        return True

    def _bucket(key: str):
        if key not in month_totals:
            month_totals[key] = {
                "period_month": key,
                "total_revenue": 0.0,
                "total_expenses": 0.0,
                "total_allowances": 0.0,
                "gross_profit": 0.0,
            }
        return month_totals[key]

    for row in billing_rows:
        if not is_valid_service_record(row):
            continue
        key = month_key(row.get("paid_date")) or month_key(row.get("service_date"))
        if not _accept_period(key):
            continue
        bucket = _bucket(key)
        bucket["total_revenue"] += to_number(row.get("paid_amount"))

    for row in expense_rows:
        key = month_key(row.get("expense_date"))
        if not _accept_period(key):
            continue
        bucket = _bucket(key)
        bucket["total_expenses"] += to_number(row.get("amount"))

    for row in allowance_rows:
        key = month_key(row.get("withdrawal_date"))
        if not _accept_period(key):
            continue
        bucket = _bucket(key)
        bucket["total_allowances"] += to_number(row.get("amount"))

    rows = list(month_totals.values())
    for row in rows:
        row["gross_profit"] = row["total_revenue"] - row["total_expenses"] - row["total_allowances"]
    rows.sort(key=lambda x: x.get("period_month") or "", reverse=True)
    return rows


@router.post("/refresh")
def trigger_refresh(_user=Depends(get_current_user)):
    """Refresh endpoint kept for compatibility with existing UI."""
    return {"message": "Cash flow uses live source-table totals; no background refresh required."}
