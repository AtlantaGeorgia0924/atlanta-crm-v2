"""Cash flow totals sourced from Supabase-derived metrics persisted in app_settings.

Architecture notes:
- /cashflow/page-data is the single aggregated endpoint for the CashFlow page.
- Statement metrics are cached in-process for STATEMENT_CACHE_TTL_SECONDS to avoid
  re-hitting app_settings on every request.  The cache is invalidated whenever
  create_expense, reverse_expense or withdraw_allowance mutates financial state.
- Expenses and withdrawals are paginated (default 50, max 100).  Only the fields
  consumed by the frontend are projected to keep payloads lightweight.
- Slow-query logging warns when /page-data exceeds SLOW_QUERY_THRESHOLD_MS.
- Every mutation writes a row to cashflow_audit_log for full auditability.
- page-data is built with partial-response protection: if expenses or withdrawals
  query fails, the remaining sections are still returned with an error marker.
"""
import logging
import time
from datetime import datetime
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.financials import to_number
from app.core.dashboard_metrics import app_settings_payload, compute_metrics_from_supabase
from app.core.metrics_refresh import recompute_and_persist_metrics

logger = logging.getLogger(__name__)

router = APIRouter()

# ── In-process statement cache ────────────────────────────────────────────────
# Simple TTL cache keyed by supabase project URL to be multi-process safe on
# restarts. On Render, each dyno is a single process so this works well.
_STATEMENT_CACHE: dict[str, tuple[float, dict]] = {}
STATEMENT_CACHE_TTL_SECONDS = 60          # cache lifetime in seconds
SLOW_QUERY_THRESHOLD_MS = 1000            # warn if page-data exceeds 1 s
PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MAX = 100

# Fields returned to the frontend for each table (projection keeps payloads small).
_EXPENSE_FIELDS = "id,amount,description,expense_date,is_reversed,reversed_at"
_WITHDRAWAL_FIELDS = "id,week_key,amount,withdrawn_at,status"


# ── Statement cache helpers ───────────────────────────────────────────────────

def _cache_key(sb) -> str:
    """Return a stable per-project cache key."""
    try:
        return sb.supabase_url
    except Exception:
        return "default"


def _cache_get(sb) -> Optional[dict]:
    key = _cache_key(sb)
    entry = _STATEMENT_CACHE.get(key)
    if not entry:
        return None
    stored_at, data = entry
    if time.monotonic() - stored_at > STATEMENT_CACHE_TTL_SECONDS:
        _STATEMENT_CACHE.pop(key, None)
        return None
    return data


def _cache_set(sb, statement: dict) -> None:
    _STATEMENT_CACHE[_cache_key(sb)] = (time.monotonic(), statement)


def _cache_invalidate(sb) -> None:
    _STATEMENT_CACHE.pop(_cache_key(sb), None)


# ── Audit log writer ──────────────────────────────────────────────────────────

def _write_audit(
    sb,
    action: str,
    amount: float,
    performed_by: str,
    related_record_id: Optional[str],
    detail: Optional[dict] = None,
) -> None:
    try:
        sb.table("cashflow_audit_log").insert(
            {
                "action": action,
                "amount": amount,
                "performed_by": performed_by,
                "related_record_id": related_record_id,
                "detail": detail,
                "created_at": datetime.utcnow().isoformat(),
            }
        ).execute()
    except Exception as exc:
        logger.warning("audit_log_write_failed action=%s error=%s", action, exc)


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
    cached = _cache_get(sb)
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

    _cache_set(sb, result)
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
    metrics = recompute_and_persist_metrics(sb, source="supabase")
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

    _cache_invalidate(sb)
    recompute_and_persist_metrics(sb, source="supabase_after_cashflow_expense")

    record = inserted[0] if inserted else row
    _write_audit(
        sb,
        action="expense_created",
        amount=amount,
        performed_by=str(_user.id),
        related_record_id=str(record.get("id", "")),
        detail={"description": payload.description},
    )
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

    _cache_invalidate(sb)
    recompute_and_persist_metrics(sb, source="supabase_after_expense_reversal")

    record = updated[0] if updated else {"id": expense_id, "is_reversed": True}
    _write_audit(
        sb,
        action="expense_reversed",
        amount=to_number(existing.get("amount")),
        performed_by=str(_user.id),
        related_record_id=expense_id,
    )
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

    _cache_invalidate(sb)
    recompute_and_persist_metrics(sb, source="supabase_after_allowance_withdrawal")

    record = inserted[0] if inserted else row
    _write_audit(
        sb,
        action="allowance_withdrawn",
        amount=requested_amount,
        performed_by=str(_user.id),
        related_record_id=str(record.get("id", "")),
        detail={"week_key": week_key},
    )
    return record
