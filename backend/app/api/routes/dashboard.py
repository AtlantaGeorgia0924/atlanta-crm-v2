"""Dashboard – single DB function call for all metrics."""
from fastapi import APIRouter, Depends
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user

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
def get_dashboard(_user=Depends(get_current_user)):
    sb = get_supabase()
    clients_count = sb.table("clients").select("id", count="exact").limit(1).execute().count or 0
    billing_rows = _read_all(sb, "service_jobs", "amount_charged,paid_amount")
    expenses_rows = _read_all(sb, "manual_expenses", "amount")
    allowance_rows = _read_all(sb, "allowance_withdrawals", "amount")
    stock_rows = _read_all(sb, "inventory_items", "quantity")

    total_billed = sum(float(r.get("amount_charged") or 0) for r in billing_rows)
    total_collected = sum(float(r.get("paid_amount") or 0) for r in billing_rows)
    total_outstanding = total_billed - total_collected
    total_expenses = sum(float(r.get("amount") or 0) for r in expenses_rows)
    total_allowances = sum(float(r.get("amount") or 0) for r in allowance_rows)
    low_stock_count = sum(1 for r in stock_rows if float(r.get("quantity") or 0) <= 0)

    return {
        "total_clients": clients_count,
        "total_invoices": len(billing_rows),
        "total_billed": total_billed,
        "total_collected": total_collected,
        "total_outstanding": total_outstanding,
        "total_expenses": total_expenses,
        "total_allowances": total_allowances,
        "low_stock_count": low_stock_count,
    }
