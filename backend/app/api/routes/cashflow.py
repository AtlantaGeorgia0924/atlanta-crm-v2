"""Cash flow totals sourced from Supabase-derived metrics persisted in app_settings.

Architecture notes:
- /cashflow/page-data is the single aggregated endpoint for the CashFlow page.
- Statement metrics are cached via Redis (STATEMENT_CACHE_KEY) with 60 s TTL,
    shared across all Render instances.  Falls back to in-process cache when Redis
    is unavailable.
- Every financial mutation calls emit_financial_event() which in one call:
        invalidates all financial caches, writes audit log, structured-logs the event,
        and enqueues a background metrics rebuild job via RQ.
- Expenses and withdrawals are paginated (default 50, max 100).  Only the fields
    consumed by the frontend are projected to keep payloads lightweight.
- Slow-query logging warns when /page-data exceeds SLOW_QUERY_THRESHOLD_MS.
- page-data has partial-response protection: if expenses or withdrawals fail,
    the remaining sections still return with section-level error keys.
"""
import logging
import time
from datetime import datetime
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.financials import to_number
from app.core.dashboard_metrics import app_settings_payload, compute_metrics_from_supabase
from app.core.metrics_refresh import refresh_financial_state
from app.core.cache import get_statement_cache, set_statement_cache
from app.core.financial_events import emit_financial_event
from app.core.logging_config import record_latency
from app.core.rbac import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_admin)])

SLOW_QUERY_THRESHOLD_MS = 1000
PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MAX = 100

_EXPENSE_FIELDS = "id,amount,description,expense_date,is_reversed,reversed_at"
_WITHDRAWAL_FIELDS = "id,week_key,amount,withdrawn_at,status"


def _cache_invalidate(_sb) -> None:
    """Legacy shim: cache invalidation is handled by emit_financial_event."""
    return None


# ── Statement helpers ─────────────────────────────────────────────────────────

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
    statement = {
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
    statement["amount_owed"] = statement["total_outstanding"]
    statement["monthly_sales"] = statement["total_sales"]
    return statement


def _statement_or_fallback(sb):
    cached = get_statement_cache()
    if cached is not None:
        return cached

    statement = _read_statement_from_settings(sb)
    if statement["total_sales"] == 0 and statement["total_collected"] == 0 and statement["net_profit"] == 0:
        metrics = compute_metrics_from_supabase(sb)
        sb.table("app_settings").upsert(
            app_settings_payload(metrics, source="supabase_auto_fallback"),
            on_conflict="key",
        ).execute()
        financial = dict(metrics["financial"])
        financial["amount_owed"] = to_number(financial.get("total_outstanding"))
        financial["monthly_sales"] = to_number(financial.get("total_sales"))
        result = financial
    else:
        result = statement

    set_statement_cache(result)
    return result


def _read_currency(sb) -> str:
    row = (
        sb.table("app_settings")
        .select("value")
        .eq("key", "currency")
        .limit(1)
        .execute()
        .data
        or []
    )
    if not row:
        return "NGN"
    return str(row[0].get("value") or "NGN")


def _paginate_table(sb, table_name: str, order_by: str, page: int, page_size: int, fields: str = "*"):
    safe_size = min(page_size, PAGE_SIZE_MAX)
    offset = (page - 1) * safe_size
    response = (
        sb.table(table_name)
        .select(fields, count="exact")
        .order(order_by, desc=True)
        .range(offset, offset + safe_size - 1)
        .execute()
    )
    items = response.data or []
    total_count = int(response.count or 0)
    total_pages = max(1, (total_count + safe_size - 1) // safe_size)
    return {
        "items": items,
        "page": page,
        "page_size": safe_size,
        "total_count": total_count,
        "total_pages": total_pages,
    }


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
    metrics = refresh_financial_state(sb, source="supabase")
    return {
        "message": "Cash flow statement refreshed from Supabase.",
        "values_calculated": metrics,
    }


@router.get("/statement")
def get_cashflow_statement(_user=Depends(get_current_user)):
    sb = get_supabase()
    return _statement_or_fallback(sb)


@router.get("/page-data")
def get_cashflow_page_data(
    expense_page: int = Query(1, ge=1),
    withdrawals_page: int = Query(1, ge=1),
    page_size: int = Query(PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    _user=Depends(get_current_user),
):
    t_start = time.monotonic()
    sb = get_supabase()

    # ── Statement (cached) ────────────────────────────────────────────────────
    statement_error: Optional[str] = None
    statement: Optional[dict] = None
    try:
        statement = _statement_or_fallback(sb)
    except Exception as exc:
        statement_error = str(exc)
        logger.warning("cashflow_page_data statement_error=%s", exc)

    # ── Currency ──────────────────────────────────────────────────────────────
    currency = "NGN"
    try:
        currency = _read_currency(sb)
    except Exception as exc:
        logger.warning("cashflow_page_data currency_error=%s", exc)

    # ── Expenses (partial-response protected) ─────────────────────────────────
    expenses_error: Optional[str] = None
    expenses: dict = {"items": [], "page": expense_page, "page_size": page_size, "total_count": 0, "total_pages": 1}
    try:
        expenses = _paginate_table(
            sb, "cashflow_expenses", "expense_date", expense_page, page_size, _EXPENSE_FIELDS
        )
    except Exception as exc:
        expenses_error = str(exc)
        logger.warning("cashflow_page_data expenses_error=%s", exc)

    # ── Withdrawals (partial-response protected) ──────────────────────────────
    withdrawals_error: Optional[str] = None
    withdrawals: dict = {"items": [], "page": withdrawals_page, "page_size": page_size, "total_count": 0, "total_pages": 1}
    try:
        withdrawals = _paginate_table(
            sb, "allowance_withdrawals", "withdrawn_at", withdrawals_page, page_size, _WITHDRAWAL_FIELDS
        )
    except Exception as exc:
        withdrawals_error = str(exc)
        logger.warning("cashflow_page_data withdrawals_error=%s", exc)

    # ── Slow-query monitoring ─────────────────────────────────────────────────
    elapsed_ms = (time.monotonic() - t_start) * 1000
    if elapsed_ms > SLOW_QUERY_THRESHOLD_MS:
        logger.warning(
            "SLOW_QUERY /cashflow/page-data elapsed_ms=%.1f expense_page=%d withdrawals_page=%d page_size=%d",
            elapsed_ms, expense_page, withdrawals_page, page_size,
        )

    record_latency("cashflow.page_data", elapsed_ms)

    response: dict[str, Any] = {
        "statement": statement,
        "expenses": expenses,
        "withdrawals": withdrawals,
        "currency": currency,
        "elapsed_ms": round(elapsed_ms, 1),
    }
    # Surface section-level errors so the frontend can show targeted messages
    if statement_error:
        response["statement_error"] = statement_error
    if expenses_error:
        response["expenses_error"] = expenses_error
    if withdrawals_error:
        response["withdrawals_error"] = withdrawals_error

    return response


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

    record = inserted[0] if inserted else row
    emit_financial_event(
        sb,
        "expense_created",
        performed_by=str(_user.id),
        record_id=str(record.get("id", "")),
        amount=amount,
        detail={"description": payload.description},
    )
    refresh_financial_state(sb, source="supabase_after_cashflow_expense_create")
    return record


@router.post("/expenses/{expense_id}/reverse")
def reverse_cashflow_expense(expense_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    existing = (
        sb.table("cashflow_expenses")
        .select("id,is_reversed,amount")
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

    record = updated[0] if updated else {"id": expense_id, "is_reversed": True}
    emit_financial_event(
        sb,
        "expense_reversed",
        performed_by=str(_user.id),
        record_id=expense_id,
        amount=to_number(existing.get("amount")),
    )
    refresh_financial_state(sb, source="supabase_after_cashflow_expense_reverse")
    return record


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
        "withdrawn_by": str(_user.id),
        "withdrawal_date": now.date().isoformat(),
    }
    inserted = sb.table("allowance_withdrawals").insert(row).execute().data or []

    record = inserted[0] if inserted else row
    emit_financial_event(
        sb,
        "allowance_withdrawn",
        performed_by=str(_user.id),
        record_id=str(record.get("id", "")),
        amount=requested_amount,
        detail={"week_key": week_key},
    )
    refresh_financial_state(sb, source="supabase_after_allowance_withdrawal")
    return record
