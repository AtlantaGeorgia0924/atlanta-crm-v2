from __future__ import annotations

import re

from app.core.dashboard_metrics import _fetch_all_rows
from app.core.financials import to_number


def _normalize_status(value) -> str:
    normalized = str(value or "").strip().upper()
    if normalized in {"PARTIAL", "PART PAYMENT"}:
        return "PART PAYMENT"
    return normalized


def _normalize_client_name(value) -> str:
    return str(value or "").strip()


def _normalize_phone(value) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _is_valid_client_name(value) -> bool:
    normalized = _normalize_client_name(value)
    if not normalized:
        return False
    return normalized not in {".", "..", "...", "....", ",,"}


def _row_oldest_key(row: dict) -> str:
    return str(row.get("created_at") or row.get("service_date") or "")


def resolve_imei(row: dict) -> str:
    value = (
        row.get("imei")
        or row.get("device_imei")
        or row.get("imei_number")
        or row.get("source_imei")
        or row.get("imei1")
        or row.get("imei_2")
        or ""
    )
    return str(value or "").strip()


def compute_debtors_from_supabase(sb) -> dict:
    """Compute grouped debtors from live service rows with phone-first grouping."""
    rows = _fetch_all_rows(sb, "service_jobs", "*")

    included_rows: list[dict] = []
    excluded_rows: list[dict] = []
    grouped: dict[str, dict] = {}

    for row in rows:
        if row.get("deleted_at"):
            continue
        client_name = _normalize_client_name(row.get("client_name"))
        status = _normalize_status(row.get("payment_status"))
        total = to_number(row.get("amount_charged"))
        paid = to_number(row.get("paid_amount"))
        outstanding = max(total - paid, 0.0)
        is_return = bool(row.get("is_return"))
        has_valid_client_name = _is_valid_client_name(row.get("client_name"))

        include = (
            has_valid_client_name
            and status in {"UNPAID", "PART PAYMENT"}
            and status != "RETURNED"
            and outstanding > 0
            and not is_return
        )

        inclusion_reason = (
            f"status={status}; outstanding={outstanding:.2f}; is_return={str(is_return).lower()}; valid_client_name={str(has_valid_client_name).lower()}"
            if include
            else f"excluded: status={status}; outstanding={outstanding:.2f}; is_return={str(is_return).lower()}; valid_client_name={str(has_valid_client_name).lower()}"
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

        normalized_phone = _normalize_phone(row.get("phone_number") or row.get("phone"))
        key = f"phone:{normalized_phone}" if normalized_phone else f"name:{client_name.upper()}"

        if key not in grouped:
            grouped[key] = {
                "id": row.get("id"),
                "debtor_key": key,
                "billing_row_id": row.get("id"),
                "client_name": client_name,
                "phone_number": row.get("phone_number") or row.get("phone") or "",
                "phone_number_normalized": normalized_phone,
                "amount_charged": 0.0,
                "total_amount": 0.0,
                "amount_paid": 0.0,
                "balance": 0.0,
                "total_outstanding": 0.0,
                "row_count": 0,
                "unpaid_jobs": 0,
                "source_row_ids": [],
                "last_activity": row.get("service_date") or row.get("created_at"),
                "last_activity_date": row.get("service_date") or row.get("created_at"),
                "last_payment_date": row.get("paid_date"),
                "last_whatsapp_sent_at": None,
                "whatsapp_sent_count": 0,
                "representative_created_at": _row_oldest_key(row),
                "search_blob": "",
            }

        group = grouped[key]
        group["amount_charged"] += total
        group["total_amount"] += total
        group["amount_paid"] += paid
        group["balance"] += outstanding
        group["total_outstanding"] += outstanding
        group["row_count"] += 1
        group["unpaid_jobs"] += 1
        group["source_row_ids"].append(row.get("id"))

        if not group.get("phone_number") and (row.get("phone_number") or row.get("phone")):
            group["phone_number"] = row.get("phone_number") or row.get("phone")

        candidate_activity = row.get("service_date") or row.get("created_at")
        if str(candidate_activity or "") > str(group.get("last_activity") or ""):
            group["last_activity"] = candidate_activity
            group["last_activity_date"] = candidate_activity

        candidate_payment = row.get("paid_date")
        if str(candidate_payment or "") > str(group.get("last_payment_date") or ""):
            group["last_payment_date"] = candidate_payment

        if not group.get("billing_row_id"):
            group["billing_row_id"] = row.get("id")
            group["id"] = row.get("id")

        # Oldest row becomes representative for this debtor group.
        if _row_oldest_key(row) < str(group.get("representative_created_at") or ""):
            group["billing_row_id"] = row.get("id")
            group["id"] = row.get("id")
            group["client_name"] = client_name
            group["representative_created_at"] = _row_oldest_key(row)
            if row.get("phone_number") or row.get("phone"):
                group["phone_number"] = row.get("phone_number") or row.get("phone")

        group["search_blob"] = " ".join(
            [
                str(group.get("search_blob") or ""),
                str(client_name or ""),
                str(row.get("phone_number") or row.get("phone") or ""),
                str(row.get("service_name") or row.get("description") or ""),
                str(row.get("id") or ""),
                str(row.get("legacy_source_id") or ""),
                str(row.get("invoice_id") or ""),
                str(row.get("invoice_reference") or ""),
                str(resolve_imei(row) or ""),
                str(row.get("serial_number") or ""),
            ]
        ).strip()

    grouped_rows = [
        row
        for row in grouped.values()
        if _is_valid_client_name(row.get("client_name")) and to_number(row.get("balance")) > 0
    ]

    # Enrich with latest payment date by invoice id.
    try:
        payment_rows = _fetch_all_rows(sb, "payments", "service_job_id,billing_row_id,payment_date,created_at")
    except Exception:
        payment_rows = []

    latest_payment_by_invoice: dict[str, str] = {}
    for payment in payment_rows:
        invoice_id = str(payment.get("service_job_id") or payment.get("billing_row_id") or "")
        if not invoice_id:
            continue
        marker = str(payment.get("payment_date") or payment.get("created_at") or "")
        if marker > str(latest_payment_by_invoice.get(invoice_id) or ""):
            latest_payment_by_invoice[invoice_id] = marker

    for row in grouped_rows:
        latest_payment = str(row.get("last_payment_date") or "")
        for source_id in row.get("source_row_ids") or []:
            marker = str(latest_payment_by_invoice.get(str(source_id)) or "")
            if marker > latest_payment:
                latest_payment = marker
        row["last_payment_date"] = latest_payment or None

    # Enrich with WhatsApp activity and use oldest client record for matching phone.
    try:
        client_rows = _fetch_all_rows(
            sb,
            "clients",
            "id,name,phone,whatsapp_sent_count,last_whatsapp_sent_at,created_at",
        )
    except Exception:
        client_rows = []

    clients_by_phone: dict[str, list[dict]] = {}
    clients_by_name: dict[str, list[dict]] = {}
    for client in client_rows:
        norm_phone = _normalize_phone(client.get("phone"))
        norm_name = _normalize_client_name(client.get("name")).upper()
        if norm_phone:
            clients_by_phone.setdefault(norm_phone, []).append(client)
        if norm_name:
            clients_by_name.setdefault(norm_name, []).append(client)

    for row in grouped_rows:
        matches: list[dict] = []
        norm_phone = _normalize_phone(row.get("phone_number"))
        norm_name = _normalize_client_name(row.get("client_name")).upper()

        if norm_phone and norm_phone in clients_by_phone:
            matches = list(clients_by_phone.get(norm_phone) or [])
        elif norm_name and norm_name in clients_by_name:
            matches = list(clients_by_name.get(norm_name) or [])

        if not matches:
            continue

        oldest = sorted(matches, key=lambda c: str(c.get("created_at") or ""))[0]
        row["client_name"] = str(oldest.get("name") or row.get("client_name") or "")
        row["phone_number"] = str(oldest.get("phone") or row.get("phone_number") or "")
        row["last_whatsapp_sent_at"] = oldest.get("last_whatsapp_sent_at")
        row["whatsapp_sent_count"] = int(to_number(oldest.get("whatsapp_sent_count")))

    grouped_rows.sort(key=lambda r: (-to_number(r.get("balance")), str(r.get("client_name") or "").upper()))
    total_amount_owed = sum(to_number(row.get("balance")) for row in grouped_rows)

    return {
        "total_amount_owed": total_amount_owed,
        "included_rows": included_rows,
        "excluded_rows": excluded_rows,
        "grouped_clients": grouped_rows,
    }
