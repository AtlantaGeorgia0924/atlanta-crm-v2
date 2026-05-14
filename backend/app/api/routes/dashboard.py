from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.core.dashboard_metrics import app_settings_payload, compute_metrics_from_supabase
from app.core.financials import to_number
from app.db.supabase_client import get_supabase

router = APIRouter()


def _read_dashboard_values_from_settings(sb):
    settings_rows = (
        sb.table("app_settings")
        .select("key,value")
        .in_(
            "key",
            [
                "dashboard_total_clients",
                "dashboard_total_invoices",
                "dashboard_total_unpaid",
                "dashboard_amount_owed",
                "dashboard_monthly_sales",
                "dashboard_available_products",
                "dashboard_pending_products",
                "dashboard_low_quality_stock",
                "dashboard_net_profit",
            ],
        )
        .execute()
        .data
        or []
    )
    settings_map = {row.get("key"): row.get("value") for row in settings_rows}
    return {
        "clients": int(to_number(settings_map.get("dashboard_total_clients"))),
        "total_invoices": int(to_number(settings_map.get("dashboard_total_invoices"))),
        "total_unpaid": int(to_number(settings_map.get("dashboard_total_unpaid"))),
        "amount_owed": to_number(settings_map.get("dashboard_amount_owed")),
        "monthly_sales": to_number(settings_map.get("dashboard_monthly_sales")),
        "available_products": int(to_number(settings_map.get("dashboard_available_products"))),
        "pending_products": int(to_number(settings_map.get("dashboard_pending_products"))),
        "low_quality_stock": int(to_number(settings_map.get("dashboard_low_quality_stock"))),
        "net_profit": to_number(settings_map.get("dashboard_net_profit")),
    }


def _get_dashboard_values(sb):
    values = _read_dashboard_values_from_settings(sb)
    if values["clients"] <= 0 and values["total_invoices"] <= 0:
        metrics = compute_metrics_from_supabase(sb)
        sb.table("app_settings").upsert(
            app_settings_payload(metrics, source="supabase_auto_fallback"),
            on_conflict="key",
        ).execute()
        return metrics["dashboard"]
    return values


@router.get("")
def get_dashboard(_user=Depends(get_current_user)):
    sb = get_supabase()
    return _get_dashboard_values(sb)


@router.get("/validation")
def dashboard_validation(_user=Depends(get_current_user)):
    sb = get_supabase()
    values = _get_dashboard_values(sb)
    return {
        "values_displayed_on_dashboard": values,
        "total_invoices": values["total_invoices"],
        "total_unpaid": values["total_unpaid"],
        "amount_owed": values["amount_owed"],
        "monthly_sales": values["monthly_sales"],
        "available_products": values["available_products"],
        "pending_products": values["pending_products"],
        "low_quality_stock": values["low_quality_stock"],
        "net_profit": values["net_profit"],
        "clients": values["clients"],
    }
