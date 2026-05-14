"""Cash flow totals sourced from Supabase-derived metrics persisted in app_settings."""
from datetime import datetime
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

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
                "finance_profit_seen_this_week",
                "finance_expenses_of_the_week",
                "finance_net_profit_of_the_week",
                "finance_next_week_allowance",
                "finance_profit_seen_this_month",
                "finance_expenses_of_the_month",
                "finance_net_profit_of_the_month",
                "finance_net_profit_left_this_month",
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
        "profit_seen_this_week": to_number(kv.get("finance_profit_seen_this_week")),
        "expenses_of_the_week": to_number(kv.get("finance_expenses_of_the_week")),
        "net_profit_of_the_week": to_number(kv.get("finance_net_profit_of_the_week")),
        "next_week_allowance": to_number(kv.get("finance_next_week_allowance")),
        "profit_seen_this_month": to_number(kv.get("finance_profit_seen_this_month")),
        "expenses_of_the_month": to_number(kv.get("finance_expenses_of_the_month")),
        "net_profit_of_the_month": to_number(kv.get("finance_net_profit_of_the_month")),
        "net_profit_left_this_month": to_number(kv.get("finance_net_profit_left_this_month")),
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


def _current_week_key(now: datetime) -> str:
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _can_withdraw_now(now: datetime) -> bool:
    # Saturday is weekday 5 in Python's Monday=0 indexing
    return now.weekday() == 5 and (now.hour > 17 or (now.hour == 17 and now.minute >= 0))


class CashflowExpenseCreate(BaseModel):
    amount: float
    description: Optional[str] = None
    expense_date: Optional[str] = None


class AllowanceWithdrawRequest(BaseModel):
    amount: Optional[float] = None


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


@router.get("/expenses")
def list_cashflow_expenses(_user=Depends(get_current_user)):
    sb = get_supabase()
    return (
        sb.table("cashflow_expenses")
        .select("*")
        .order("expense_date", desc=True)
        .execute()
        .data
        or []
    )


@router.post("/expenses", status_code=201)
def create_cashflow_expense(payload: CashflowExpenseCreate, _user=Depends(get_current_user)):
    sb = get_supabase()
    amount = to_number(payload.amount)
    if amount <= 0:
        raise HTTPException(422, "Expense amount must be greater than zero")

    row = {
        "amount": amount,
        "description": payload.description,
    }
    if payload.expense_date:
        row["expense_date"] = payload.expense_date

    inserted = sb.table("cashflow_expenses").insert(row).execute().data or []

    metrics = compute_metrics_from_supabase(sb)
    sb.table("app_settings").upsert(
        app_settings_payload(metrics, source="supabase_after_cashflow_expense"),
        on_conflict="key",
    ).execute()
    return inserted[0] if inserted else row


@router.post("/expenses/{expense_id}/reverse")
def reverse_cashflow_expense(expense_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    existing = (
        sb.table("cashflow_expenses")
        .select("id,is_reversed")
        .eq("id", expense_id)
        .single()
        .execute()
        .data
    )
    if not existing:
        raise HTTPException(404, "Expense not found")
    if existing.get("is_reversed"):
        raise HTTPException(400, "Expense already reversed")

    updated = (
        sb.table("cashflow_expenses")
        .update({"is_reversed": True, "reversed_at": datetime.utcnow().isoformat()})
        .eq("id", expense_id)
        .execute()
        .data
        or []
    )

    metrics = compute_metrics_from_supabase(sb)
    sb.table("app_settings").upsert(
        app_settings_payload(metrics, source="supabase_after_expense_reversal"),
        on_conflict="key",
    ).execute()
    return updated[0] if updated else {"id": expense_id, "is_reversed": True}


@router.get("/allowance-withdrawals")
def list_allowance_withdrawals(_user=Depends(get_current_user)):
    sb = get_supabase()
    return (
        sb.table("allowance_withdrawals")
        .select("*")
        .order("withdrawn_at", desc=True)
        .execute()
        .data
        or []
    )


@router.post("/allowance-withdrawals/withdraw", status_code=201)
def withdraw_allowance(payload: AllowanceWithdrawRequest, _user=Depends(get_current_user)):
    sb = get_supabase()
    now = datetime.now()
    week_key = _current_week_key(now)

    existing = (
        sb.table("allowance_withdrawals")
        .select("id,week_key")
        .eq("week_key", week_key)
        .execute()
        .data
        or []
    )
    if existing:
        raise HTTPException(400, f"Allowance already withdrawn for {week_key}")

    if not _can_withdraw_now(now):
        raise HTTPException(400, "Allowance withdrawal is allowed only on Saturday after 5:00 PM")

    statement = _statement_or_fallback(sb)
    allowed_default = max(0.0, to_number(statement.get("next_week_allowance")))
    requested_amount = to_number(payload.amount) if payload.amount is not None else allowed_default
    if requested_amount <= 0:
        raise HTTPException(400, "No allowance amount available to withdraw")

    row = {
        "id": str(uuid.uuid4()),
        "week_key": week_key,
        "amount": requested_amount,
        "withdrawn_at": now.isoformat(),
        "status": "YES",
        "withdrawn_by": "system",
        "withdrawal_date": now.date().isoformat(),
    }
    inserted = sb.table("allowance_withdrawals").insert(row).execute().data or []

    metrics = compute_metrics_from_supabase(sb)
    sb.table("app_settings").upsert(
        app_settings_payload(metrics, source="supabase_after_allowance_withdrawal"),
        on_conflict="key",
    ).execute()
    return inserted[0] if inserted else row
