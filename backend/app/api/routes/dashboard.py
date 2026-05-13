"""Dashboard – single DB function call for all metrics."""
from fastapi import APIRouter, Depends
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.financials import (
    compute_outstanding,
    is_valid_service_record,
    to_number,
)

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


def _compute_dashboard_totals(sb):
    clients_count = sb.table("clients").select("id", count="exact").limit(1).execute().count or 0
    billing_rows = _read_all(sb, "service_jobs", "id,service_name,description,amount_charged,paid_amount")
    expenses_rows = _read_all(sb, "manual_expenses", "amount")
    allowance_rows = _read_all(sb, "allowance_withdrawals", "amount")
    stock_rows = _read_all(sb, "inventory_items", "*")

    valid_service_rows = [row for row in billing_rows if is_valid_service_record(row)]
    total_billed = sum(to_number(r.get("amount_charged")) for r in valid_service_rows)
    total_collected = sum(to_number(r.get("paid_amount")) for r in valid_service_rows)
    total_outstanding = sum(
        compute_outstanding(r.get("amount_charged"), r.get("paid_amount"))
        for r in valid_service_rows
    )
    total_expenses = sum(to_number(r.get("amount")) for r in expenses_rows)
    total_allowances = sum(to_number(r.get("amount")) for r in allowance_rows)
    low_stock_count = sum(
        1
        for r in stock_rows
        if to_number(r.get("quantity")) <= to_number(r.get("reorder_level"))
    )

    return {
        "total_service_rows_included": len(valid_service_rows),
        "total_clients": clients_count,
        "total_invoices": len(valid_service_rows),
        "total_billed": total_billed,
        "total_collected": total_collected,
        "total_outstanding": total_outstanding,
        "total_expenses": total_expenses,
        "total_allowances": total_allowances,
        "low_stock_count": low_stock_count,
    }


@router.get("")
def get_dashboard(_user=Depends(get_current_user)):
    sb = get_supabase()
    totals = _compute_dashboard_totals(sb)
    return {
        "total_clients": totals["total_clients"],
        "total_invoices": totals["total_invoices"],
        "total_billed": totals["total_billed"],
        "total_collected": totals["total_collected"],
        "total_outstanding": totals["total_outstanding"],
        "total_expenses": totals["total_expenses"],
        "total_allowances": totals["total_allowances"],
        "low_stock_count": totals["low_stock_count"],
    }


@router.get("/validation")
def dashboard_validation(_user=Depends(get_current_user)):
    sb = get_supabase()
    totals = _compute_dashboard_totals(sb)
    return {
        "total_service_rows_included": totals["total_service_rows_included"],
        "total_billed": totals["total_billed"],
        "total_paid": totals["total_collected"],
        "total_outstanding": totals["total_outstanding"],
        "total_expenses": totals["total_expenses"],
        "total_allowances": totals["total_allowances"],
        "total_clients": totals["total_clients"],
        "low_stock_count": totals["low_stock_count"],
    }
