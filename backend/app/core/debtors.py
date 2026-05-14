from __future__ import annotations

from collections import defaultdict

from app.core.dashboard_metrics import _fetch_all_rows
from app.core.financials import compute_outstanding, to_number


def _normalize_status(value) -> str:
    normalized = str(value or "").strip().upper()
    if normalized in {"PARTIAL", "PART PAYMENT"}:
        return "PART PAYMENT"
    return normalized


def _normalize_client_name(value) -> str:
    text = str(value or "").strip()
    return text or "Unknown Client"


def compute_debtors_from_supabase(sb) -> dict:
    """
    Compute outstanding debtors from service_jobs.
    
    Inclusion rules (only rows matching ALL conditions are included):
    - payment_status IN ('UNPAID', 'PART PAYMENT')
    - outstanding > 0 (calculated as max(amount_charged - paid_amount, 0))
    - is_return = false
    
    Exclusion rules (any row matching these is excluded):
    - payment_status = 'PAID'
    - payment_status = 'RETURNED'
    - is_return = true
    - outstanding <= 0
    
    Outstanding formula: outstanding = max(amount_charged - paid_amount, 0)
    
    Returns dict with:
    - total_amount_owed: sum of all outstanding balances for included rows
    - included_rows: list of rows that met inclusion criteria
    - excluded_rows: list of rows that didn't meet criteria
    - grouped_clients: clients grouped by name with aggregated amounts
    """
    rows = _fetch_all_rows(
        sb,
        "service_jobs",
        "id,client_name,payment_status,amount_charged,paid_amount,is_return,due_date,service_date,created_at,legacy_source_id,service_name,description",
    )

    included_rows: list[dict] = []
    excluded_rows: list[dict] = []
    grouped: dict[str, dict] = {}

    for row in rows:
        client_name = _normalize_client_name(row.get("client_name"))
        status = _normalize_status(row.get("payment_status"))
        total = to_number(row.get("amount_charged"))
        paid = to_number(row.get("paid_amount"))
        outstanding = max(total - paid, 0.0)
        is_return = bool(row.get("is_return"))

        include = (
            status in {"UNPAID", "PART PAYMENT"}
            and outstanding > 0
            and not is_return
        )

        inclusion_reason = (
            f"status={status}; outstanding={outstanding:.2f}; is_return={str(is_return).lower()}"
            if include
            else f"excluded: status={status}; outstanding={outstanding:.2f}; is_return={str(is_return).lower()}"
        )

        row_payload = {
            "id": row.get("id"),
            "client_name": client_name,
            "payment_status": status,
            "amount_charged": total,
            "paid_amount": paid,
            "outstanding": outstanding,
            "inclusion_reason": inclusion_reason,
            "is_return": is_return,
            "due_date": row.get("due_date"),
            "service_date": row.get("service_date"),
            "service_name": row.get("service_name") or row.get("description") or "",
        }

        if not include:
            excluded_rows.append(row_payload)
            continue

        included_rows.append(row_payload)

        client_key = client_name.strip().upper()
        if client_key not in grouped:
            grouped[client_key] = {
                "id": row.get("id"),
                "billing_row_id": row.get("id"),
                "client_name": client_name,
                "payment_status": status,
                "amount_charged": 0.0,
                "total_amount": 0.0,
                "amount_paid": 0.0,
                "balance": 0.0,
                "status": "partial" if status == "PART PAYMENT" else "unpaid",
                "due_date": row.get("due_date"),
                "service_name": row.get("service_name") or row.get("description") or "Outstanding invoices",
                "row_type": "client",
                "row_count": 0,
                "source_row_ids": [],
            }

        group = grouped[client_key]
        group["amount_charged"] += total
        group["total_amount"] += total
        group["amount_paid"] += paid
        group["balance"] += outstanding
        group["row_count"] += 1
        group["source_row_ids"].append(row.get("id"))
        if not group.get("billing_row_id"):
            group["billing_row_id"] = row.get("id")
            group["id"] = row.get("id")

        # Preserve the oldest row as the representative payment target.
        if str(row.get("due_date") or row.get("service_date") or row.get("created_at") or "") < str(group.get("due_date") or group.get("service_date") or group.get("created_at") or ""):
            group["billing_row_id"] = row.get("id")
            group["id"] = row.get("id")
            group["due_date"] = row.get("due_date")
            group["service_name"] = row.get("service_name") or row.get("description") or "Outstanding invoices"

        if status == "PART PAYMENT":
            group["status"] = "partial"

    grouped_rows = sorted(grouped.values(), key=lambda r: (-to_number(r.get("balance")), str(r.get("client_name") or "").upper()))
    total_amount_owed = sum(to_number(row.get("balance")) for row in grouped_rows)

    return {
        "total_amount_owed": total_amount_owed,
        "included_rows": included_rows,
        "excluded_rows": excluded_rows,
        "grouped_clients": grouped_rows,
    }
