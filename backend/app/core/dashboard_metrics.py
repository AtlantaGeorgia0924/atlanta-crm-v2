import logging
import re
from datetime import datetime, timedelta, timezone

from app.core.financials import compute_outstanding, to_number

logger = logging.getLogger(__name__)

ACCOUNTING_START_AT = datetime(2026, 5, 1, tzinfo=timezone.utc)


def _fetch_all_rows(sb, table_name: str, select_clause: str, batch_size: int = 1000) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        batch = (
            sb.table(table_name)
            .select(select_clause)
            .range(start, start + batch_size - 1)
            .execute()
            .data
            or []
        )
        rows.extend(batch)
        if len(batch) < batch_size:
            break
        start += batch_size
    return rows


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


def _parse_dt(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _week_bounds_utc(now_utc: datetime) -> tuple[datetime, datetime]:
    start = (now_utc - timedelta(days=now_utc.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    return start, end


def _month_bounds_utc(now_utc: datetime) -> tuple[datetime, datetime]:
    start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _norm_imei(value) -> str:
    raw = str(value or "").strip().upper()
    # Keep only identifier portion before slash, then remove non-alphanumerics.
    raw = raw.split("/", 1)[0]
    normalized = re.sub(r"[^A-Z0-9]", "", raw)
    if len(normalized) < 5:
        return ""
    return normalized


def compute_metrics_from_supabase(sb) -> dict:
    clients = _fetch_all_rows(sb, "clients", "id")

    services = _fetch_all_rows(
        sb,
        "service_jobs",
        "id,client_name,amount_charged,paid_amount,payment_status,service_date,paid_at,paid_date,is_return,service_expense_amount,expense_amount",
    )

    inventory = _fetch_all_rows(
        sb,
        "inventory_items",
        "id,item_name,product_status,payment_status,paid_at,paid_date,is_return,cost_price,selling_price,item_expense_amount,expense_amount",
    )

    try:
        expenses = _fetch_all_rows(sb, "cashflow_expenses", "amount,expense_date,is_reversed,reversed_at")
    except Exception:
        expenses = _fetch_all_rows(sb, "manual_expenses", "amount,expense_date")

    try:
        allowances = _fetch_all_rows(sb, "allowance_withdrawals", "amount,withdrawn_at,status,week_key")
    except Exception:
        allowances = _fetch_all_rows(sb, "allowance_withdrawals", "amount,withdrawal_date")

    now_utc = datetime.now(timezone.utc)
    week_start, week_end = _week_bounds_utc(now_utc)
    month_start, month_end = _month_bounds_utc(now_utc)

    # ── Service Jobs ──────────────────────────────────────────────────────────
    total_invoices = 0
    total_unpaid = 0
    amount_owed = 0.0
    monthly_sales = 0.0
    total_sales = 0.0
    total_collected = 0.0
    total_outstanding = 0.0
    service_profit_total = 0.0
    profit_seen_this_week = 0.0
    profit_seen_this_month = 0.0
    total_sales_collected_this_month = 0.0

    for row in services:
        total = to_number(row.get("amount_charged"))
        paid = to_number(row.get("paid_amount"))
        status = _norm(row.get("payment_status"))
        outstanding = compute_outstanding(total, paid)
        # prefer service_expense_amount; fall back to expense_amount
        service_expense = to_number(row.get("service_expense_amount")) or to_number(row.get("expense_amount"))
        paid_at = _parse_dt(row.get("paid_at") or row.get("paid_date"))
        is_reversed = bool(row.get("is_return"))

        total_invoices += 1
        total_sales += total
        total_collected += paid
        total_outstanding += outstanding

        include_profit = (
            status == "PAID"
            and paid_at is not None
            and paid_at >= ACCOUNTING_START_AT
            and not is_reversed
        )

        if include_profit:
            # Service profit rule: paid_amount - service_expense_amount
            row_profit = paid - service_expense
            service_profit_total += row_profit

            if week_start <= paid_at < week_end:
                profit_seen_this_week += row_profit
            if month_start <= paid_at < month_end:
                profit_seen_this_month += row_profit
                total_sales_collected_this_month += paid

        if _is_unpaid(status):
            total_unpaid += 1
        if _is_partial_or_unpaid(status):
            amount_owed += outstanding
        if _is_current_month(row.get("service_date")):
            monthly_sales += paid

    # ── Inventory Items ───────────────────────────────────────────────────────
    available_products = 0
    pending_products = 0
    low_quality_stock = 0
    inventory_profit_total = 0.0

    for row in inventory:
        prod_status = _norm(row.get("product_status") or row.get("payment_status"))
        if prod_status == "AVAILABLE":
            available_products += 1
        elif prod_status == "PENDING DEAL":
            pending_products += 1
        elif prod_status == "LOW QUALITY":
            low_quality_stock += 1

        paid_at = _parse_dt(row.get("paid_at") or row.get("paid_date"))
        is_reversed = bool(row.get("is_return"))
        # payment_status or product_status drives inclusion
        pay_status = _norm(row.get("payment_status") or row.get("product_status"))

        include_profit = (
            pay_status == "PAID"
            and paid_at is not None
            and paid_at >= ACCOUNTING_START_AT
            and not is_reversed
        )

        if include_profit:
            selling_price = to_number(row.get("selling_price"))
            cost_price = to_number(row.get("cost_price"))
            item_expense = to_number(row.get("item_expense_amount")) or to_number(row.get("expense_amount"))

            if cost_price > 0 or selling_price > 0:
                # Product profit rule: selling_price - cost_price - item_expense_amount
                row_profit = selling_price - cost_price - item_expense
                inventory_profit_total += row_profit

                if week_start <= paid_at < week_end:
                    profit_seen_this_week += row_profit
                if month_start <= paid_at < month_end:
                    profit_seen_this_month += row_profit
                    total_sales_collected_this_month += selling_price

    # ── Cashflow Expenses ─────────────────────────────────────────────────────
    total_expenses = 0.0
    expenses_of_the_week = 0.0
    expenses_of_the_month = 0.0
    for row in expenses:
        if bool(row.get("is_reversed")):
            continue
        amount = to_number(row.get("amount"))
        exp_dt = _parse_dt(row.get("expense_date"))
        total_expenses += amount
        if exp_dt and week_start <= exp_dt < week_end:
            expenses_of_the_week += amount
        if exp_dt and month_start <= exp_dt < month_end:
            expenses_of_the_month += amount

    # ── Allowances ────────────────────────────────────────────────────────────
    total_allowances = 0.0
    for row in allowances:
        if str(row.get("status") or "YES").upper() != "YES":
            continue
        total_allowances += to_number(row.get("amount"))

    gross_profit = inventory_profit_total + service_profit_total
    net_profit = gross_profit - total_expenses - total_allowances

    net_profit_of_the_week = profit_seen_this_week - expenses_of_the_week
    next_week_allowance = net_profit_of_the_week * 0.25
    net_profit_of_the_month = profit_seen_this_month - expenses_of_the_month
    net_profit_left_this_month = net_profit_of_the_month * 0.75

    week_key = now_utc.strftime("%G-W%V")
    month_key = now_utc.strftime("%Y-%m")

    try:
        sb.table("weekly_financial_snapshots").upsert(
            {
                "week_key": week_key,
                "profit_seen_this_week": profit_seen_this_week,
                "expenses_of_the_week": expenses_of_the_week,
                "net_profit_of_the_week": net_profit_of_the_week,
                "next_week_allowance": next_week_allowance,
            },
            on_conflict="week_key",
        ).execute()
        sb.table("monthly_financial_snapshots").upsert(
            {
                "month_key": month_key,
                "profit_seen_this_month": profit_seen_this_month,
                "expenses_of_the_month": expenses_of_the_month,
                "net_profit_of_the_month": net_profit_of_the_month,
                "net_profit_left_this_month": net_profit_left_this_month,
            },
            on_conflict="month_key",
        ).execute()
    except Exception as exc:
        logger.warning("Failed to persist financial snapshots: %s", exc)

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
            "total_service_expenses": 0,
            "total_allowances": total_allowances,
            "gross_profit": gross_profit,
            "net_profit": net_profit,
            "profit_seen_this_week": profit_seen_this_week,
            "expenses_of_the_week": expenses_of_the_week,
            "net_profit_of_the_week": net_profit_of_the_week,
            "next_week_allowance": next_week_allowance,
            "profit_seen_this_month": profit_seen_this_month,
            "expenses_of_the_month": expenses_of_the_month,
            "net_profit_of_the_month": net_profit_of_the_month,
            "net_profit_left_this_month": net_profit_left_this_month,
            "total_sales_collected_this_month": total_sales_collected_this_month,
        },
        "validation": {
            "total_inventory_profit": inventory_profit_total,
            "total_service_profit": service_profit_total,
            "final_net_profit": net_profit,
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
        {"key": "finance_profit_seen_this_week", "value": str(financial.get("profit_seen_this_week", 0))},
        {"key": "finance_expenses_of_the_week", "value": str(financial.get("expenses_of_the_week", 0))},
        {"key": "finance_net_profit_of_the_week", "value": str(financial.get("net_profit_of_the_week", 0))},
        {"key": "finance_next_week_allowance", "value": str(financial.get("next_week_allowance", 0))},
        {"key": "finance_profit_seen_this_month", "value": str(financial.get("profit_seen_this_month", 0))},
        {"key": "finance_expenses_of_the_month", "value": str(financial.get("expenses_of_the_month", 0))},
        {"key": "finance_net_profit_of_the_month", "value": str(financial.get("net_profit_of_the_month", 0))},
        {"key": "finance_net_profit_left_this_month", "value": str(financial.get("net_profit_left_this_month", 0))},
        {"key": "finance_total_sales_collected_this_month", "value": str(financial.get("total_sales_collected_this_month", 0))},
        {"key": "finance_total_inventory_profit", "value": str(validation.get("total_inventory_profit", 0))},
        {"key": "finance_total_service_profit", "value": str(validation.get("total_service_profit", 0))},
        {"key": "finance_final_net_profit", "value": str(validation.get("final_net_profit", financial["net_profit"]))},
        {"key": "dashboard_last_recalculated_at", "value": now_iso},
        {"key": "dashboard_last_source", "value": source},
    ]


def compute_profit_ledger(sb) -> dict:
    """
    Returns every qualifying transaction included in weekly and monthly profit,
    with full audit details per row.
    """
    now_utc = datetime.now(timezone.utc)
    week_start, week_end = _week_bounds_utc(now_utc)
    month_start, month_end = _month_bounds_utc(now_utc)

    services = _fetch_all_rows(
        sb,
        "service_jobs",
        "id,client_name,amount_charged,paid_amount,payment_status,paid_at,paid_date,is_return,service_expense_amount,expense_amount",
    )
    inventory = _fetch_all_rows(
        sb,
        "inventory_items",
        "id,item_name,product_status,payment_status,paid_at,paid_date,is_return,cost_price,selling_price,item_expense_amount,expense_amount",
    )

    weekly_rows: list[dict] = []
    monthly_rows: list[dict] = []
    excluded_rows: list[dict] = []

    # ── Service Jobs ──────────────────────────────────────────────────────────
    for row in services:
        paid = to_number(row.get("paid_amount"))
        status = _norm(row.get("payment_status"))
        service_expense = to_number(row.get("service_expense_amount")) or to_number(row.get("expense_amount"))
        paid_at = _parse_dt(row.get("paid_at") or row.get("paid_date"))
        is_reversed = bool(row.get("is_return"))

        include = (
            status == "PAID"
            and paid_at is not None
            and paid_at >= ACCOUNTING_START_AT
            and not is_reversed
        )

        if not include:
            reasons = []
            if status != "PAID":
                reasons.append(f"status={status}")
            if paid_at is None:
                reasons.append("no paid_at")
            elif paid_at < ACCOUNTING_START_AT:
                reasons.append(f"paid_at {paid_at.date()} < accounting_start")
            if is_reversed:
                reasons.append("reversed")
            excluded_rows.append({
                "source": "service_job",
                "id": row.get("id"),
                "client_name": row.get("client_name"),
                "paid_at": paid_at.isoformat() if paid_at else None,
                "exclusion_reason": "; ".join(reasons),
            })
            continue

        profit = paid - service_expense
        in_week = week_start <= paid_at < week_end
        in_month = month_start <= paid_at < month_end

        entry = {
            "source": "service_job",
            "id": row.get("id"),
            "client_name": row.get("client_name") or "—",
            "paid_at": paid_at.isoformat(),
            "paid_amount": paid,
            "selling_price": None,
            "cost_price": None,
            "expense_amount": service_expense,
            "computed_profit": round(profit, 2),
            "inclusion_reason": "service: paid_amount - service_expense_amount",
            "in_week": in_week,
            "in_month": in_month,
        }

        if in_week:
            weekly_rows.append(entry)
        if in_month:
            monthly_rows.append(entry)

    # ── Inventory Items ───────────────────────────────────────────────────────
    for row in inventory:
        pay_status = _norm(row.get("payment_status") or row.get("product_status"))
        paid_at = _parse_dt(row.get("paid_at") or row.get("paid_date"))
        is_reversed = bool(row.get("is_return"))
        selling_price = to_number(row.get("selling_price"))
        cost_price = to_number(row.get("cost_price"))
        item_expense = to_number(row.get("item_expense_amount")) or to_number(row.get("expense_amount"))

        include = (
            pay_status == "PAID"
            and paid_at is not None
            and paid_at >= ACCOUNTING_START_AT
            and not is_reversed
            and (cost_price > 0 or selling_price > 0)
        )

        if not include:
            reasons = []
            if pay_status != "PAID":
                reasons.append(f"status={pay_status}")
            if paid_at is None:
                reasons.append("no paid_at")
            elif paid_at < ACCOUNTING_START_AT:
                reasons.append(f"paid_at {paid_at.date()} < accounting_start")
            if is_reversed:
                reasons.append("reversed")
            if cost_price <= 0 and selling_price <= 0:
                reasons.append("no selling_price or cost_price")
            excluded_rows.append({
                "source": "inventory_item",
                "id": row.get("id"),
                "client_name": row.get("item_name"),
                "paid_at": paid_at.isoformat() if paid_at else None,
                "exclusion_reason": "; ".join(reasons),
            })
            continue

        profit = selling_price - cost_price - item_expense
        in_week = week_start <= paid_at < week_end
        in_month = month_start <= paid_at < month_end

        entry = {
            "source": "inventory_item",
            "id": row.get("id"),
            "client_name": row.get("item_name") or "—",
            "paid_at": paid_at.isoformat(),
            "paid_amount": selling_price,
            "selling_price": selling_price,
            "cost_price": cost_price,
            "expense_amount": item_expense,
            "computed_profit": round(profit, 2),
            "inclusion_reason": "product: selling_price - cost_price - item_expense_amount",
            "in_week": in_week,
            "in_month": in_month,
        }

        if in_week:
            weekly_rows.append(entry)
        if in_month:
            monthly_rows.append(entry)

    weekly_profit = sum(r["computed_profit"] for r in weekly_rows)
    monthly_profit = sum(r["computed_profit"] for r in monthly_rows)
    monthly_sales = sum(r["paid_amount"] for r in monthly_rows)

    return {
        "period": {
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "month_start": month_start.isoformat(),
            "month_end": month_end.isoformat(),
        },
        "summary": {
            "weekly_profit": round(weekly_profit, 2),
            "monthly_profit": round(monthly_profit, 2),
            "monthly_sales_collected": round(monthly_sales, 2),
            "weekly_transaction_count": len(weekly_rows),
            "monthly_transaction_count": len(monthly_rows),
            "excluded_transaction_count": len(excluded_rows),
        },
        "weekly_transactions": sorted(weekly_rows, key=lambda r: r["paid_at"]),
        "monthly_transactions": sorted(monthly_rows, key=lambda r: r["paid_at"]),
        "excluded_transactions": excluded_rows,
    }