from app.core.cache import cache_delete, set_statement_cache
from app.core.dashboard_metrics import app_settings_payload, compute_metrics_from_supabase
from app.core.financials import to_number


_DASHBOARD_CACHE_KEY = "dashboard:summary"
_DEBTORS_CACHE_KEY = "debtors:summary"


def recompute_and_persist_metrics(sb, source: str = "supabase_auto_update") -> dict:
    """Recompute dashboard/financial metrics and persist them into app_settings."""
    metrics = compute_metrics_from_supabase(sb)
    sb.table("app_settings").upsert(
        app_settings_payload(metrics, source=source),
        on_conflict="key",
    ).execute()
    return metrics


def _statement_from_metrics(metrics: dict) -> dict:
    financial = dict((metrics or {}).get("financial") or {})
    statement = {
        "total_sales": to_number(financial.get("total_sales")),
        "total_collected": to_number(financial.get("total_collected")),
        "total_outstanding": to_number(financial.get("total_outstanding")),
        "total_expenses": to_number(financial.get("total_expenses")),
        "total_service_expenses": to_number(financial.get("total_service_expenses")),
        "total_allowances": to_number(financial.get("total_allowances")),
        "gross_profit": to_number(financial.get("gross_profit")),
        "net_profit": to_number(financial.get("net_profit")),
        "profit_seen_this_week": to_number(financial.get("profit_seen_this_week")),
        "expenses_of_the_week": to_number(financial.get("expenses_of_the_week")),
        "net_profit_of_the_week": to_number(financial.get("net_profit_of_the_week")),
        "next_week_allowance": to_number(financial.get("next_week_allowance")),
        "profit_seen_this_month": to_number(financial.get("profit_seen_this_month")),
        "expenses_of_the_month": to_number(financial.get("expenses_of_the_month")),
        "net_profit_of_the_month": to_number(financial.get("net_profit_of_the_month")),
        "net_profit_left_this_month": to_number(financial.get("net_profit_left_this_month")),
    }
    statement["amount_owed"] = statement["total_outstanding"]
    statement["monthly_sales"] = statement["total_sales"]
    return statement


def refresh_financial_state(sb, *, source: str = "supabase_auto_update") -> dict:
    """Recompute, persist, and publish financial cache state without stale windows."""
    metrics = recompute_and_persist_metrics(sb, source=source)

    # Publish the latest statement first to avoid stale repopulation races.
    set_statement_cache(_statement_from_metrics(metrics))

    # Dependent summaries can be dropped after the latest statement is published.
    cache_delete(_DASHBOARD_CACHE_KEY)
    cache_delete(_DEBTORS_CACHE_KEY)
    return metrics
