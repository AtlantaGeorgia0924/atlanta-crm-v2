import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from app.core.cashflow_sheet_sync import read_sheet_id
from app.core.config import settings as app_settings
from app.core.financials import to_number


def _normalize_header(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower())
    return re.sub(r"\s+", " ", text).strip()


def _get_first_match(headers: List[str], aliases: List[str]) -> str:
    normalized_aliases = [_normalize_header(a) for a in aliases]
    normalized_headers = {h: _normalize_header(h) for h in headers}
    for alias in normalized_aliases:
        for header, norm in normalized_headers.items():
            if norm == alias:
                return header
    for alias in normalized_aliases:
        for header, norm in normalized_headers.items():
            if alias in norm:
                return header
    return ""


def _parse_date(value: str) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"]:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except Exception:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return None


def _worksheet_rows(worksheet) -> Tuple[List[Dict[str, str]], int]:
    values = worksheet.get_all_values() if worksheet else []
    if not values:
        return [], 0
    headers = values[0]
    rows = []
    for row in values[1:]:
        padded = row + [""] * (len(headers) - len(row))
        record = {headers[i]: padded[i] for i in range(len(headers))}
        if any(str(v).strip() for v in record.values()):
            rows.append(record)
    return rows, len(rows)


def _open_worksheet(book, title: str):
    import gspread

    try:
        return book.worksheet(title)
    except gspread.WorksheetNotFound:
        return None


def _normalized_payment_status(status: str) -> str:
    normalized = _normalize_header(status).upper()
    if normalized in {"PART PAYMENT", "PARTIAL"}:
        return "PARTIAL"
    if normalized in {"UNPAID", "PAID"}:
        return normalized
    return "UNPAID"


def _batch_upsert(sb, table_name: str, rows: List[dict], on_conflict: str, chunk_size: int = 500):
    for i in range(0, len(rows), chunk_size):
        sb.table(table_name).upsert(rows[i : i + chunk_size], on_conflict=on_conflict).execute()


def import_google_sheets_to_supabase(sb) -> dict:
    import gspread
    from google.oauth2.service_account import Credentials

    services_sheet_id = read_sheet_id(sb, purpose="services")
    stocks_sheet_id = read_sheet_id(sb, purpose="stocks")
    service_account_json = app_settings.GOOGLE_SERVICE_ACCOUNT_JSON

    if not services_sheet_id or not stocks_sheet_id:
        raise ValueError("Google Sheets not configured: missing services/stocks sheet IDs")
    if not service_account_json or not os.path.exists(service_account_json):
        raise ValueError("Google Sheets not configured: service account JSON missing")

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(service_account_json, scopes=scopes)
    gc = gspread.authorize(creds)

    services_book = gc.open_by_key(services_sheet_id)
    stocks_book = gc.open_by_key(stocks_sheet_id)

    services_ws = _open_worksheet(services_book, "Sheet1")
    clients_ws = _open_worksheet(services_book, "CLIENT DIRECTORY")
    inventory_ws = _open_worksheet(stocks_book, "Sheet1")

    service_rows, service_count = _worksheet_rows(services_ws) if services_ws else ([], 0)
    client_rows, client_count = _worksheet_rows(clients_ws) if clients_ws else ([], 0)
    inventory_rows, inventory_count = _worksheet_rows(inventory_ws) if inventory_ws else ([], 0)

    service_headers = list(service_rows[0].keys()) if service_rows else []
    price_h = _get_first_match(service_headers, ["PRICE", "UNIT PRICE", "AMOUNT CHARGED"])
    paid_h = _get_first_match(service_headers, ["Amount paid", "PAID", "PAID AMOUNT"])
    status_h = _get_first_match(service_headers, ["STATUS", "PAYMENT STATUS"])
    date_h = _get_first_match(service_headers, ["DATE", "SERVICE DATE", "INVOICE DATE"])
    due_h = _get_first_match(service_headers, ["DUE DATE"])
    client_h = _get_first_match(service_headers, ["NAME", "CLIENT", "CLIENT NAME"])
    service_h = _get_first_match(service_headers, ["SERVICE NAME", "DESCRIPTION", "FAULT", "SERVICE"])
    qty_h = _get_first_match(service_headers, ["QUANTITY", "QTY"])
    expense_h = _get_first_match(service_headers, ["SERVICE EXPENSE", "EXPENSE"])
    notes_h = _get_first_match(service_headers, ["NOTES"])

    service_payload = []
    for idx, row in enumerate(service_rows):
        amount_charged = to_number(row.get(price_h)) if price_h else 0.0
        paid_amount = to_number(row.get(paid_h)) if paid_h else 0.0
        quantity = to_number(row.get(qty_h)) if qty_h else 1.0
        service_name = str(row.get(service_h) or "").strip() if service_h else ""
        if not service_name:
            service_name = "General Service"

        service_payload.append(
            {
                "legacy_source_id": f"sheet_import:service:{idx + 1}",
                "client_name": str(row.get(client_h) or "").strip() if client_h else None,
                "service_name": service_name,
                "description": str(row.get(service_h) or "").strip() if service_h else None,
                "quantity": quantity or 1.0,
                "amount_charged": amount_charged,
                "expense_amount": to_number(row.get(expense_h)) if expense_h else 0.0,
                "calculated_profit": paid_amount,
                "payment_status": _normalized_payment_status(row.get(status_h, "") if status_h else ""),
                "paid_amount": paid_amount,
                "paid_date": _parse_date(row.get(date_h)) if date_h else None,
                "service_date": _parse_date(row.get(date_h)) if date_h else None,
                "due_date": _parse_date(row.get(due_h)) if due_h else None,
                "notes": str(row.get(notes_h) or "").strip() if notes_h else None,
                "source_updated_at": datetime.utcnow().isoformat(),
            }
        )

    client_headers = list(client_rows[0].keys()) if client_rows else []
    client_name_h = _get_first_match(client_headers, ["NAME", "CLIENT NAME", "FULL NAME"])
    client_phone_h = _get_first_match(client_headers, ["PHONE", "PHONE NUMBER", "TEL"])
    client_email_h = _get_first_match(client_headers, ["EMAIL"])
    client_address_h = _get_first_match(client_headers, ["ADDRESS"])
    client_company_h = _get_first_match(client_headers, ["COMPANY", "BUSINESS"])
    client_notes_h = _get_first_match(client_headers, ["NOTES"])

    clients_payload = []
    for idx, row in enumerate(client_rows):
        name = str(row.get(client_name_h) or "").strip() if client_name_h else ""
        if not name:
            continue
        clients_payload.append(
            {
                "id": f"sheet_import:client:{idx + 1}",
                "name": name,
                "phone": str(row.get(client_phone_h) or "").strip() if client_phone_h else None,
                "email": str(row.get(client_email_h) or "").strip() if client_email_h else None,
                "address": str(row.get(client_address_h) or "").strip() if client_address_h else None,
                "company": str(row.get(client_company_h) or "").strip() if client_company_h else None,
                "notes": str(row.get(client_notes_h) or "").strip() if client_notes_h else None,
                "source_updated_at": datetime.utcnow().isoformat(),
            }
        )

    inventory_headers = list(inventory_rows[0].keys()) if inventory_rows else []
    item_h = _get_first_match(inventory_headers, ["DESCRIPTION", "DEVICE", "ITEM", "PRODUCT", "MODEL"])
    sku_h = _get_first_match(inventory_headers, ["IMEI", "SERIAL", "SKU"])
    category_h = _get_first_match(inventory_headers, ["CATEGORY", "TYPE"])
    status_h_inv = _get_first_match(inventory_headers, ["PRODUCT STATUS", "STATUS"])
    cost_h = _get_first_match(inventory_headers, ["COST PRICE", "COST"])
    sell_h = _get_first_match(inventory_headers, ["SELLING PRICE", "PRICE"])
    notes_h_inv = _get_first_match(inventory_headers, ["NOTES"])

    inventory_payload = []
    for idx, row in enumerate(inventory_rows):
        item_name = str(row.get(item_h) or "").strip() if item_h else ""
        if not item_name:
            continue

        status = str(row.get(status_h_inv) or "").strip() if status_h_inv else ""
        normalized_status = status.upper() if status else "AVAILABLE"
        quantity = 0.0 if normalized_status == "SOLD" else 1.0

        inventory_payload.append(
            {
                "legacy_source_id": f"sheet_import:inventory:{idx + 1}",
                "item_name": item_name,
                "sku": str(row.get(sku_h) or "").strip() if sku_h else None,
                "category": str(row.get(category_h) or "").strip() if category_h else None,
                "description": str(row.get(notes_h_inv) or "").strip() if notes_h_inv else None,
                "quantity": quantity,
                "unit": "pcs",
                "cost_price": to_number(row.get(cost_h)) if cost_h else 0.0,
                "selling_price": to_number(row.get(sell_h)) if sell_h else 0.0,
                "payment_status": normalized_status,
                "source_updated_at": datetime.utcnow().isoformat(),
            }
        )

    # Replace previously imported snapshots, keep non-imported manual data intact.
    sb.table("service_jobs").delete().ilike("legacy_source_id", "sheet_import:service:%").execute()
    sb.table("inventory_items").delete().ilike("legacy_source_id", "sheet_import:inventory:%").execute()
    sb.table("clients").delete().ilike("id", "sheet_import:client:%").execute()

    if service_payload:
        _batch_upsert(sb, "service_jobs", service_payload, on_conflict="legacy_source_id")
    if inventory_payload:
        _batch_upsert(sb, "inventory_items", inventory_payload, on_conflict="legacy_source_id")
    if clients_payload:
        _batch_upsert(sb, "clients", clients_payload, on_conflict="id")

    return {
        "sheets_read": ["Sheet1 (Services)", "CLIENT DIRECTORY", "Sheet1 (Inventory)"],
        "rows_processed": {
            "Sheet1 (Services)": service_count,
            "CLIENT DIRECTORY": client_count,
            "Sheet1 (Inventory)": inventory_count,
        },
        "rows_upserted": {
            "service_jobs": len(service_payload),
            "clients": len(clients_payload),
            "inventory_items": len(inventory_payload),
        },
        "headers_detected": {
            "services": {
                "price": price_h,
                "amount_paid": paid_h,
                "status": status_h,
                "date": date_h,
                "due_date": due_h,
                "client": client_h,
                "service_name": service_h,
            },
            "clients": {
                "name": client_name_h,
                "phone": client_phone_h,
                "email": client_email_h,
            },
            "inventory": {
                "item": item_h,
                "sku": sku_h,
                "status": status_h_inv,
                "cost_price": cost_h,
                "selling_price": sell_h,
            },
        },
    }