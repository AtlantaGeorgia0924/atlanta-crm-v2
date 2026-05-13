"""Dashboard sourced from manually refreshed snapshot persisted in Supabase."""
from fastapi import APIRouter, Depends
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.financials import to_number
from app.core.cashflow_sheet_sync import CASHFLOW_SUMMARY_ID

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


def _read_dashboard_cashflow_values(sb):
    settings_rows = (
        sb.table("app_settings")
        .select("key,value")
        .in_(
            "key",
            [
                "dashboard_total_billed",
                "dashboard_total_collected",
                "dashboard_total_outstanding",
                "dashboard_total_expenses",
                "dashboard_total_allowances",
                "dashboard_net_profit",
            ],
        )
        .execute()
        .data
        or []
    )
    settings_map = {row.get("key"): row.get("value") for row in settings_rows}
    if any(key in settings_map for key in [
        "dashboard_total_billed",
        "dashboard_total_collected",
        "dashboard_total_outstanding",
        "dashboard_total_expenses",
        "dashboard_total_allowances",
        "dashboard_net_profit",
    ]):
        return {
            "total_billed": to_number(settings_map.get("dashboard_total_billed")),
            "total_collected": to_number(settings_map.get("dashboard_total_collected")),
            "total_outstanding": max(0.0, to_number(settings_map.get("dashboard_total_outstanding"))),
            "total_expenses": to_number(settings_map.get("dashboard_total_expenses")),
            "total_allowances": to_number(settings_map.get("dashboard_total_allowances")),
            "net_profit": to_number(settings_map.get("dashboard_net_profit")),
        }

    row = (
        sb.table("cashflow_summary")
        .select("*")
        .eq("id", CASHFLOW_SUMMARY_ID)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not row:
        return {
            "total_billed": 0.0,
            "total_collected": 0.0,
            "total_outstanding": 0.0,
            "total_expenses": 0.0,
            "total_allowances": 0.0,
            "net_profit": 0.0,
        }

    item = row[0]
    return {
        "total_billed": to_number(item.get("monthly_net_profit")),
        "total_collected": to_number(item.get("weekly_paid_profits")),
        "total_outstanding": max(0.0, to_number(item.get("monthly_net_profit_left"))),
        "total_expenses": to_number(item.get("weekly_expenses")),
        "total_allowances": to_number(item.get("allowances_withdrawn")),
        "net_profit": to_number(item.get("weekly_net_profit")),
    }


def _compute_dashboard_totals(sb):
    stock_rows = _read_all(sb, "inventory_items", "*")
    cashflow_values = _read_dashboard_cashflow_values(sb)
    fallback_low_stock_count = sum(
        1
        for r in stock_rows
        if to_number(r.get("quantity")) <= to_number(r.get("reorder_level"))
    )

    settings_rows = (
        sb.table("app_settings")
        .select("key,value")
        .in_("key", ["dashboard_total_clients", "dashboard_total_invoices", "dashboard_low_stock_count"])
        .execute()
        .data
        or []
    )
    settings_map = {row.get("key"): row.get("value") for row in settings_rows}

    clients_count = int(to_number(settings_map.get("dashboard_total_clients")))
    invoice_count = int(to_number(settings_map.get("dashboard_total_invoices")))
    low_stock_count = int(to_number(settings_map.get("dashboard_low_stock_count")))

    if clients_count <= 0:
        clients_count = sb.table("clients").select("id", count="exact").limit(1).execute().count or 0
    if invoice_count <= 0:
        invoice_count = sb.table("service_jobs").select("id", count="exact").limit(1).execute().count or 0
    if low_stock_count <= 0:
        low_stock_count = fallback_low_stock_count

    return {
        "total_service_rows_included": invoice_count,
        "total_clients": clients_count,
        "total_invoices": invoice_count,
        "total_billed": cashflow_values["total_billed"],
        "total_collected": cashflow_values["total_collected"],
        "total_outstanding": cashflow_values["total_outstanding"],
        "total_expenses": cashflow_values["total_expenses"],
        "total_allowances": cashflow_values["total_allowances"],
        "net_profit": cashflow_values["net_profit"],
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
        "net_profit": totals["net_profit"],
        "low_stock_count": totals["low_stock_count"],
    }


@router.get("/validation")
def dashboard_validation(_user=Depends(get_current_user)):
    sb = get_supabase()
    cashflow_values = _read_dashboard_cashflow_values(sb)
    totals = _compute_dashboard_totals(sb)
    return {
        "values_displayed_on_dashboard": cashflow_values,
        "total_service_rows_included": totals["total_service_rows_included"],
        "total_billed": totals["total_billed"],
        "total_paid": totals["total_collected"],
        "total_outstanding": totals["total_outstanding"],
        "total_expenses": totals["total_expenses"],
        "total_allowances": totals["total_allowances"],
        "net_profit": totals["net_profit"],
        "total_clients": totals["total_clients"],
        "low_stock_count": totals["low_stock_count"],
    }
