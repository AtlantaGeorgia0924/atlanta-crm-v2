from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.core.dashboard_metrics import app_settings_payload, compute_metrics_from_supabase
from app.core.financials import to_number
from app.core.rbac import user_is_admin
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
    values = _get_dashboard_values(sb)
    if user_is_admin(_user):
        return values
    values["total_unpaid"] = 0
    values["amount_owed"] = 0
    values["monthly_sales"] = 0
    values["net_profit"] = 0
    return values


@router.get("/validation")
def dashboard_validation(_user=Depends(get_current_user)):
    sb = get_supabase()
    values = _get_dashboard_values(sb)
    settings_rows = (
        sb.table("app_settings")
        .select("key,value")
        .in_(
            "key",
            [
                "finance_inventory_matched_by_imei",
                "finance_total_inventory_profit",
                "finance_total_service_profit",
                "finance_final_net_profit",
                "finance_imei_no_inventory_match",
                "finance_skipped_missing_cost_price",
            ],
        )
        .execute()
        .data
        or []
    )
    settings_map = {row.get("key"): row.get("value") for row in settings_rows}
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
        "inventory_matched_by_imei": int(to_number(settings_map.get("finance_inventory_matched_by_imei"))),
        "imei_no_inventory_match": int(to_number(settings_map.get("finance_imei_no_inventory_match"))),
        "skipped_missing_cost_price": int(to_number(settings_map.get("finance_skipped_missing_cost_price"))),
        "total_inventory_profit": to_number(settings_map.get("finance_total_inventory_profit")),
        "total_service_profit": to_number(settings_map.get("finance_total_service_profit")),
        "final_net_profit": to_number(settings_map.get("finance_final_net_profit")),
        "imei_validation": {
            "inventory_matched_by_imei": int(to_number(settings_map.get("finance_inventory_matched_by_imei"))),
            "total_inventory_profit": to_number(settings_map.get("finance_total_inventory_profit")),
            "total_service_profit": to_number(settings_map.get("finance_total_service_profit")),
            "final_net_profit": to_number(settings_map.get("finance_final_net_profit")),
            "imei_no_inventory_match": int(to_number(settings_map.get("finance_imei_no_inventory_match"))),
            "skipped_missing_cost_price": int(to_number(settings_map.get("finance_skipped_missing_cost_price"))),
        },
    }
