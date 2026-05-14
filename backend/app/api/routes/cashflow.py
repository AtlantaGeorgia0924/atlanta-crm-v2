"""Cash flow totals sourced from Supabase-derived metrics persisted in app_settings."""
from fastapi import APIRouter, Depends, Query
from typing import Optional
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.financials import to_number
from app.core.dashboard_metrics import app_settings_payload, compute_metrics_from_supabase

router = APIRouter()


def _read_statement_from_settings(sb):
    rows = (
        sb.table("app_settings")
        .select("key,value")
        .in_(
            "key",
            [
                "finance_total_sales",
                "finance_total_collected",
                "finance_total_outstanding",
                "finance_total_expenses",
                "finance_total_service_expenses",
                "finance_total_allowances",
                "finance_gross_profit",
                "finance_net_profit",
            ],
        )
        .execute()
        .data
        or []
    )
    kv = {row.get("key"): row.get("value") for row in rows}
    return {
        "total_sales": to_number(kv.get("finance_total_sales")),
        "total_collected": to_number(kv.get("finance_total_collected")),
        "total_outstanding": to_number(kv.get("finance_total_outstanding")),
        "total_expenses": to_number(kv.get("finance_total_expenses")),
        "total_service_expenses": to_number(kv.get("finance_total_service_expenses")),
        "total_allowances": to_number(kv.get("finance_total_allowances")),
        "gross_profit": to_number(kv.get("finance_gross_profit")),
        "net_profit": to_number(kv.get("finance_net_profit")),
    }


def _statement_or_fallback(sb):
    statement = _read_statement_from_settings(sb)
    if statement["total_sales"] == 0 and statement["total_collected"] == 0 and statement["net_profit"] == 0:
        metrics = compute_metrics_from_supabase(sb)
        sb.table("app_settings").upsert(
            app_settings_payload(metrics, source="supabase_auto_fallback"),
            on_conflict="key",
        ).execute()
        return metrics["financial"]
    return statement


@router.get("")
def get_cashflow(
    month: Optional[str] = Query(None, description="YYYY-MM filter"),
    year: Optional[str] = Query(None, description="YYYY filter"),
    _user=Depends(get_current_user),
):
    """Read cash flow figures from cashflow_summary row synced from Google Sheets."""
    sb = get_supabase()
    statement = _statement_or_fallback(sb)
    if any(statement.values()):
        period_label = month or year or "sheet_summary"
        if month and period_label != "sheet_summary" and month != period_label:
            return []
        if year and period_label != "sheet_summary" and not str(period_label).startswith(str(year)):
            return []
        return [
            {
                "period_month": period_label,
                "total_revenue": statement["total_sales"],
                "total_expenses": statement["total_expenses"],
                "total_allowances": statement["total_allowances"],
                "gross_profit": statement["net_profit"],
            }
        ]

    return []


@router.post("/refresh")
def trigger_refresh(_user=Depends(get_current_user)):
    """Recalculate financial statement from Supabase-only data."""
    sb = get_supabase()
    metrics = compute_metrics_from_supabase(sb)
    sb.table("app_settings").upsert(
        app_settings_payload(metrics, source="supabase"),
        on_conflict="key",
    ).execute()
    return {
        "message": "Cash flow statement refreshed from Supabase.",
        "values_calculated": metrics,
    }


@router.get("/statement")
def get_cashflow_statement(_user=Depends(get_current_user)):
    sb = get_supabase()
    return _statement_or_fallback(sb)
