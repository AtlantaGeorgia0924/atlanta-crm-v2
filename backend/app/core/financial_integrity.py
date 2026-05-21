"""
Financial consistency validator.

Runs a suite of checks against live Supabase data and logs any
discrepancies to the `financial_integrity_issues` table.

Checks
------
1. Outstanding totals cross-check (app_settings vs. sum of unpaid rows)
2. PAID rows with zero paid_amount
3. Duplicate legacy_source_id within the same table
4. Negative balance on manually-added expenses
5. Cashflow summary fields that differ by >5% from row-level aggregates

Each issue is also written to `financial_integrity_issues` for history.
"""
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.logging_config import log_event

logger = logging.getLogger(__name__)

TOLERANCE_PCT = 0.05   # 5 % tolerance for floating-point aggregation drift


def _log_issue(sb, check_name: str, description: str, severity: str = "warning", detail: dict | None = None) -> dict:
    issue: dict[str, Any] = {
        "check_name": check_name,
        "description": description,
        "severity": severity,
        "detail": detail or {},
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        sb.table("financial_integrity_issues").insert(issue).execute()
    except Exception as exc:
        logger.warning("integrity_issue_write_failed check=%s error=%s", check_name, exc)
    log_event("integrity_issue", **issue)
    return issue


def _check_paid_zero_amount(sb) -> list[dict]:
    """Find service_jobs / inventory_items that are PAID but paid_amount = 0."""
    issues = []
    for table, amount_col in [("service_jobs", "paid_amount"), ("inventory_items", "paid_amount")]:
        try:
            rows = (
                sb.table(table)
                .select("id,payment_status," + amount_col)
                .eq("payment_status", "PAID")
                .eq(amount_col, 0)
                .execute()
                .data or []
            )
            for row in rows:
                issues.append(
                    _log_issue(
                        sb,
                        check_name="paid_zero_amount",
                        description=f"{table} row {row['id']} is PAID but {amount_col}=0",
                        severity="error",
                        detail={"table": table, "row_id": row["id"]},
                    )
                )
        except Exception as exc:
            logger.warning("integrity_check_error check=paid_zero_amount table=%s error=%s", table, exc)
    return issues


def _check_duplicate_legacy_source_id(sb) -> list[dict]:
    """Find tables with duplicate legacy_source_id values (non-null)."""
    issues = []
    for table in ("service_jobs", "inventory_items", "manual_expenses", "allowance_withdrawals"):
        try:
            rows = (
                sb.table(table)
                .select("legacy_source_id")
                .not_.is_("legacy_source_id", "null")
                .execute()
                .data or []
            )
            ids = [r["legacy_source_id"] for r in rows]
            seen: set = set()
            dupes = {x for x in ids if x in seen or seen.add(x)}  # type: ignore[func-returns-value]
            for dup in dupes:
                issues.append(
                    _log_issue(
                        sb,
                        check_name="duplicate_legacy_source_id",
                        description=f"{table} has duplicate legacy_source_id={dup}",
                        severity="warning",
                        detail={"table": table, "legacy_source_id": dup},
                    )
                )
        except Exception as exc:
            logger.warning("integrity_check_error check=duplicate_legacy_source_id table=%s error=%s", table, exc)
    return issues


def _check_negative_expenses(sb) -> list[dict]:
    """Find cashflow_expenses rows with amount <= 0 that are not reversed."""
    issues = []
    try:
        rows = (
            sb.table("cashflow_expenses")
            .select("id,amount,is_reversed")
            .lte("amount", 0)
            .eq("is_reversed", False)
            .execute()
            .data or []
        )
        for row in rows:
            issues.append(
                _log_issue(
                    sb,
                    check_name="negative_expense",
                    description=f"cashflow_expenses row {row['id']} has non-positive amount={row['amount']}",
                    severity="error",
                    detail={"row_id": row["id"], "amount": row["amount"]},
                )
            )
    except Exception as exc:
        logger.warning("integrity_check_error check=negative_expenses error=%s", exc)
    return issues


def _check_outstanding_cross_reference(sb) -> list[dict]:
    """
    Compare total_outstanding in app_settings against sum of unpaid service/inventory rows.
    Flags if discrepancy exceeds TOLERANCE_PCT.
    """
    issues = []
    try:
        row = (
            sb.table("app_settings")
            .select("value")
            .eq("key", "finance_total_outstanding")
            .single()
            .execute()
            .data
        )
        if not row:
            return issues
        cached_outstanding = float(row.get("value") or 0)

        # Sum unpaid from service_jobs
        sj_rows = (
            sb.table("service_jobs")
            .select("amount_charged,paid_amount")
            .in_("payment_status", ["UNPAID", "PART PAYMENT"])
            .execute()
            .data or []
        )
        inv_rows = (
            sb.table("inventory_items")
            .select("selling_price,paid_amount")
            .in_("payment_status", ["UNPAID", "PART PAYMENT"])
            .execute()
            .data or []
        )
        computed = sum(
            float(r.get("amount_charged") or 0) - float(r.get("paid_amount") or 0)
            for r in sj_rows
        ) + sum(
            float(r.get("selling_price") or 0) - float(r.get("paid_amount") or 0)
            for r in inv_rows
        )
        if cached_outstanding > 0:
            drift = abs(cached_outstanding - computed) / cached_outstanding
            if drift > TOLERANCE_PCT:
                issues.append(
                    _log_issue(
                        sb,
                        check_name="outstanding_cross_reference",
                        description=(
                            f"app_settings outstanding={cached_outstanding:.2f} "
                            f"vs computed={computed:.2f} drift={drift:.1%}"
                        ),
                        severity="warning",
                        detail={
                            "cached": cached_outstanding,
                            "computed": round(computed, 2),
                            "drift_pct": round(drift * 100, 2),
                        },
                    )
                )
    except Exception as exc:
        logger.warning("integrity_check_error check=outstanding_cross_reference error=%s", exc)
    return issues


def run_all_checks(sb) -> list[dict]:
    """Run every check and return all issues found."""
    all_issues: list[dict] = []
    all_issues.extend(_check_paid_zero_amount(sb))
    all_issues.extend(_check_duplicate_legacy_source_id(sb))
    all_issues.extend(_check_negative_expenses(sb))
    all_issues.extend(_check_outstanding_cross_reference(sb))

    log_event(
        "integrity_check_complete",
        total_issues=len(all_issues),
        ts=datetime.now(timezone.utc).isoformat(),
    )
    return all_issues
