import logging
from datetime import datetime

from app.core.financials import compute_outstanding, to_number

logger = logging.getLogger(__name__)


def _norm(value: str) -> str:
    return str(value or "").strip().upper()


def _is_partial_or_unpaid(status: str) -> bool:
    normalized = _norm(status)
    return normalized in {"UNPAID", "PARTIAL", "PART PAYMENT"}


def _is_unpaid(status: str) -> bool:
    return _norm(status) == "UNPAID"


def _is_current_month(value) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        text = str(value).strip()
        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"]:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except Exception:
                parsed = None
        if parsed is None:
            return False
    now = datetime.utcnow()
    return parsed.year == now.year and parsed.month == now.month


def _norm_imei(value) -> str:
    raw = str(value or "").strip().upper()
    # Reject placeholders that contain no alphanumeric characters or are too short
    import re as _re
    if not _re.search(r'[A-Z0-9]', raw) or len(raw) < 5:
        return ""
    return raw


def compute_metrics_from_supabase(sb) -> dict:
    clients = sb.table("clients").select("id").execute().data or []
    try:
        services = (
            sb.table("service_jobs")
            .select("id,amount_charged,paid_amount,payment_status,service_date,service_expense,expense_amount,imei")
            .execute()
            .data
            or []
        )
    except Exception:
        try:
            services = (
                sb.table("service_jobs")
                .select("id,amount_charged,paid_amount,payment_status,service_date,expense_amount,imei")
                .execute()
                .data
                or []
            )
        except Exception:
            services = (
                sb.table("service_jobs")
                .select("id,amount_charged,paid_amount,payment_status,service_date,expense_amount")
                .execute()
                .data
                or []
            )
    try:
        inventory = sb.table("inventory_items").select("id,product_status,payment_status,cost_price,imei,sku").execute().data or []
    except Exception:
        inventory = sb.table("inventory_items").select("id,payment_status,cost_price,sku").execute().data or []
    expenses = sb.table("manual_expenses").select("amount").execute().data or []
    allowances = sb.table("allowance_withdrawals").select("amount").execute().data or []

    total_invoices = 0
    total_unpaid = 0
    amount_owed = 0.0
    monthly_sales = 0.0
    total_sales = 0.0
    total_collected = 0.0
    total_outstanding = 0.0
    total_service_expenses = 0.0
    imei_inventory_map = {}
    for inv in inventory:
        inv_imei = _norm_imei(inv.get("imei") or inv.get("sku"))
        if inv_imei and inv_imei not in imei_inventory_map:
            imei_inventory_map[inv_imei] = to_number(inv.get("cost_price"))

    inventory_matched_count = 0
    inventory_profit_total = 0.0
    service_profit_total = 0.0
    unmatched_imei_count = 0
    skipped_missing_cost_price = 0

    for row in services:
        total = to_number(row.get("amount_charged"))
        paid = to_number(row.get("paid_amount"))
        status = _norm(row.get("payment_status"))
        outstanding = compute_outstanding(total, paid)
        service_expense = to_number(row.get("service_expense")) or to_number(row.get("expense_amount"))
        imei = _norm_imei(row.get("imei"))

        total_invoices += 1
        total_sales += total
        total_collected += paid
        total_outstanding += outstanding
        total_service_expenses += service_expense

        if imei:
            if imei in imei_inventory_map:
                inventory_matched_count += 1
                cost_price = imei_inventory_map[imei]
                if cost_price <= 0:
                    skipped_missing_cost_price += 1
                    logger.warning(
                        "Skipping IMEI sale due to missing/zero cost_price for service row id=%s imei=%s",
                        row.get("id"),
                        imei,
                    )
                    continue
            else:
                unmatched_imei_count += 1
                logger.warning("No inventory IMEI match for service row id=%s imei=%s; excluding from inventory profit", row.get("id"), imei)
                continue
            inventory_profit_total += paid - cost_price
        else:
            service_profit_total += paid - service_expense

        if _is_unpaid(status):
            total_unpaid += 1
        if _is_partial_or_unpaid(status):
            amount_owed += outstanding
        if _is_current_month(row.get("service_date")):
            monthly_sales += paid

    available_products = 0
    pending_products = 0
    low_quality_stock = 0
    for row in inventory:
        status = _norm(row.get("product_status") or row.get("payment_status"))
        if status == "AVAILABLE":
            available_products += 1
        elif status == "PENDING DEAL":
            pending_products += 1
        elif status == "LOW QUALITY":
            low_quality_stock += 1

    total_expenses = sum(to_number(row.get("amount")) for row in expenses)
    total_allowances = sum(to_number(row.get("amount")) for row in allowances)
    gross_profit = inventory_profit_total + service_profit_total
    net_profit = gross_profit - total_expenses - total_allowances

    return {
        "dashboard": {
            "clients": len(clients),
            "total_invoices": total_invoices,
            "total_unpaid": total_unpaid,
            "amount_owed": amount_owed,
            "monthly_sales": monthly_sales,
            "available_products": available_products,
            "pending_products": pending_products,
            "low_quality_stock": low_quality_stock,
            "net_profit": net_profit,
        },
        "financial": {
            "total_sales": total_sales,
            "total_collected": total_collected,
            "total_outstanding": total_outstanding,
            "total_expenses": total_expenses,
            "total_service_expenses": total_service_expenses,
            "total_allowances": total_allowances,
            "gross_profit": gross_profit,
            "net_profit": net_profit,
        },
        "validation": {
            "inventory_matched_by_imei": inventory_matched_count,
            "total_inventory_profit": inventory_profit_total,
            "total_service_profit": service_profit_total,
            "final_net_profit": net_profit,
            "imei_no_inventory_match": unmatched_imei_count,
            "skipped_missing_cost_price": skipped_missing_cost_price,
        },
    }


def app_settings_payload(metrics: dict, source: str) -> list[dict]:
    now_iso = datetime.utcnow().isoformat()
    dashboard = metrics["dashboard"]
    financial = metrics["financial"]
    validation = metrics.get("validation", {})
    return [
        {"key": "dashboard_total_clients", "value": str(dashboard["clients"])},
        {"key": "dashboard_total_invoices", "value": str(dashboard["total_invoices"])},
        {"key": "dashboard_total_unpaid", "value": str(dashboard["total_unpaid"])},
        {"key": "dashboard_amount_owed", "value": str(dashboard["amount_owed"])},
        {"key": "dashboard_monthly_sales", "value": str(dashboard["monthly_sales"])},
        {"key": "dashboard_available_products", "value": str(dashboard["available_products"])},
        {"key": "dashboard_pending_products", "value": str(dashboard["pending_products"])},
        {"key": "dashboard_low_quality_stock", "value": str(dashboard["low_quality_stock"])},
        {"key": "dashboard_net_profit", "value": str(dashboard["net_profit"])},
        {"key": "finance_total_sales", "value": str(financial["total_sales"])},
        {"key": "finance_total_collected", "value": str(financial["total_collected"])},
        {"key": "finance_total_outstanding", "value": str(financial["total_outstanding"])},
        {"key": "finance_total_expenses", "value": str(financial["total_expenses"])},
        {"key": "finance_total_service_expenses", "value": str(financial["total_service_expenses"])},
        {"key": "finance_total_allowances", "value": str(financial["total_allowances"])},
        {"key": "finance_gross_profit", "value": str(financial["gross_profit"])},
        {"key": "finance_net_profit", "value": str(financial["net_profit"])},
        {"key": "finance_inventory_matched_by_imei", "value": str(validation.get("inventory_matched_by_imei", 0))},
        {"key": "finance_total_inventory_profit", "value": str(validation.get("total_inventory_profit", 0))},
        {"key": "finance_total_service_profit", "value": str(validation.get("total_service_profit", 0))},
        {"key": "finance_final_net_profit", "value": str(validation.get("final_net_profit", financial["net_profit"]))},
        {"key": "finance_imei_no_inventory_match", "value": str(validation.get("imei_no_inventory_match", 0))},
        {"key": "finance_skipped_missing_cost_price", "value": str(validation.get("skipped_missing_cost_price", 0))},
        {"key": "dashboard_last_recalculated_at", "value": now_iso},
        {"key": "dashboard_last_source", "value": source},
    ]