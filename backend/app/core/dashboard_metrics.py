from datetime import datetime

from app.core.financials import compute_outstanding, to_number


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


def compute_metrics_from_supabase(sb) -> dict:
    clients = sb.table("clients").select("id").execute().data or []
    try:
        services = (
            sb.table("service_jobs")
            .select("id,amount_charged,paid_amount,payment_status,service_date,service_expense")
            .execute()
            .data
            or []
        )
    except Exception:
        services = (
            sb.table("service_jobs")
            .select("id,amount_charged,paid_amount,payment_status,service_date")
            .execute()
            .data
            or []
        )
    try:
        inventory = sb.table("inventory_items").select("id,product_status,payment_status").execute().data or []
    except Exception:
        inventory = sb.table("inventory_items").select("id,payment_status").execute().data or []
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

    for row in services:
        total = to_number(row.get("amount_charged"))
        paid = to_number(row.get("paid_amount"))
        status = _norm(row.get("payment_status"))
        outstanding = compute_outstanding(total, paid)

        total_invoices += 1
        total_sales += total
        total_collected += paid
        total_outstanding += outstanding
        total_service_expenses += to_number(row.get("service_expense"))

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
    gross_profit = total_collected - total_expenses - total_allowances
    net_profit = gross_profit - total_service_expenses

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
    }


def app_settings_payload(metrics: dict, source: str) -> list[dict]:
    now_iso = datetime.utcnow().isoformat()
    dashboard = metrics["dashboard"]
    financial = metrics["financial"]
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
        {"key": "dashboard_last_recalculated_at", "value": now_iso},
        {"key": "dashboard_last_source", "value": source},
    ]