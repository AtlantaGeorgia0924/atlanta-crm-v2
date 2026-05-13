"""Cash flow totals sourced from cached Google Sheet summary in cashflow_summary."""
from fastapi import APIRouter, Depends, Query
from typing import Optional
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.financials import to_number
from app.core.cashflow_sheet_sync import CASHFLOW_SUMMARY_ID, sync_cashflow_summary_from_sheet

router = APIRouter()


@router.get("")
def get_cashflow(
    month: Optional[str] = Query(None, description="YYYY-MM filter"),
    year: Optional[str] = Query(None, description="YYYY filter"),
    _user=Depends(get_current_user),
):
    """Read cash flow figures from cashflow_summary row synced from Google Sheets."""
    sb = get_supabase()
    settings_rows = (
        sb.table("app_settings")
        .select("key,value")
        .in_(
            "key",
            [
                "dashboard_total_billed",
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
        "dashboard_total_expenses",
        "dashboard_total_allowances",
        "dashboard_net_profit",
    ]):
        period_label = month or year or "sheet_summary"
        if month and period_label != "sheet_summary" and month != period_label:
            return []
        if year and period_label != "sheet_summary" and not str(period_label).startswith(str(year)):
            return []
        return [
            {
                "period_month": period_label,
                "total_revenue": to_number(settings_map.get("dashboard_total_billed")),
                "total_expenses": to_number(settings_map.get("dashboard_total_expenses")),
                "total_allowances": to_number(settings_map.get("dashboard_total_allowances")),
                "gross_profit": to_number(settings_map.get("dashboard_net_profit")),
            }
        ]

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
        return []

    item = row[0]
    period_label = item.get("period_key") or "sheet_summary"
    if month and period_label != "sheet_summary" and month != period_label:
        return []
    if year and period_label != "sheet_summary" and not str(period_label).startswith(str(year)):
        return []

    return [
        {
            "period_month": period_label,
            "total_revenue": to_number(item.get("weekly_paid_profits")),
            "total_expenses": to_number(item.get("weekly_expenses")),
            "total_allowances": to_number(item.get("allowances_withdrawn")),
            "gross_profit": to_number(item.get("weekly_net_profit")),
        }
    ]


@router.post("/refresh")
def trigger_refresh(_user=Depends(get_current_user)):
    """Refresh cashflow_summary from Google Sheets Cash Flow tab."""
    sb = get_supabase()
    details = sync_cashflow_summary_from_sheet(sb)
    return {
        "message": "Cash flow summary refreshed from Google Sheets.",
        **details,
    }
