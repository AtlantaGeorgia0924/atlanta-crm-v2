import os
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from app.core.cashflow_sheet_sync import read_sheet_id
from app.core.config import settings as app_settings
from app.core.financials import to_number

NUMERIC12_MAX = 9_999_999_999.99


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


def _get_exact_match(headers: List[str], aliases: List[str]) -> str:
    normalized_aliases = {_normalize_header(a) for a in aliases}
    for header in headers:
        if _normalize_header(header) in normalized_aliases:
            return header
    return ""


# PRE-ACCOUNTING sentinel: any PAID row whose date cannot be determined from the
# sheet gets this value so the DB trigger (set_paid_at_once) does NOT stamp it
# with NOW() and inflate current-period metrics.
_PRE_ACCOUNTING_SENTINEL = "2025-12-31"


def _parse_date(value: str) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    # IMPORTANT: try MM/DD/YYYY (US format used by these Google Sheets) BEFORE
    # DD/MM/YYYY. Dates like '05/11/2026' must parse as May 11, not Nov 5.
    for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"]:
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
    # Find the actual header row: first row where the FIRST cell is non-empty
    # AND at least 5 cells total are non-empty.
    # This skips title/summary rows that have sparse or right-aligned content.
    header_idx = 0
    for i, row in enumerate(values):
        non_empty = sum(1 for cell in row if str(cell).strip())
        first_cell_filled = bool(str(row[0]).strip()) if row else False
        if first_cell_filled and non_empty >= 5:
            header_idx = i
            break
    headers = values[header_idx]
    rows = []
    for row_offset, row in enumerate(values[header_idx + 1:], start=1):
        padded = row + [""] * (len(headers) - len(row))
        record = {headers[i]: padded[i] for i in range(len(headers))}
        if any(str(v).strip() for v in record.values()):
            record["__sheet_row_number"] = header_idx + 1 + row_offset
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
    if normalized == "RETURNED":
        return "RETURNED"
    if normalized in {"PART PAYMENT", "PARTIAL"}:
        return "PART PAYMENT"
    if normalized in {"UNPAID", "PAID"}:
        return normalized
    return "UNPAID"


def _is_placeholder_text(value: Optional[str]) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    return text in {".", "..", "...", "....", ",,"}


def _fits_numeric12(value: float) -> bool:
    return abs(float(value)) <= NUMERIC12_MAX


def _batch_upsert(sb, table_name: str, rows: List[dict], on_conflict: str, chunk_size: int = 200):
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        last_exc = None
        for attempt in range(3):
            try:
                sb.table(table_name).upsert(chunk, on_conflict=on_conflict).execute()
                break
            except Exception as e:
                err_str = str(e)
                # Retry on transient network/connection errors
                if any(kw in err_str for kw in ["Broken pipe", "WriteError", "ConnectionError", "SSL", "SSLV3", "reset by peer", "timed out"]):
                    last_exc = e
                    time.sleep(1.5 ** attempt)
                    continue
                raise
        else:
            raise RuntimeError(f"Batch upsert to {table_name} failed after 3 attempts: {last_exc}")


def _fetch_all_rows(sb, table_name: str, select_clause: str, batch_size: int = 1000) -> List[dict]:
    rows: List[dict] = []
    start = 0
    while True:
        response = (
            sb.table(table_name)
            .select(select_clause)
            .range(start, start + batch_size - 1)
            .execute()
        )
        batch = response.data or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < batch_size:
            break
        start += batch_size
    return rows


def _same_value(a, b) -> bool:
    if a is None:
        a = ""
    if b is None:
        b = ""
    return str(a).strip() == str(b).strip()


def _has_unsynced_app_change(row: dict) -> bool:
    if str(row.get("sync_source") or "").lower() != "app":
        return False
    if not bool(row.get("sync_dirty")):
        return False
    updated_at = str(row.get("updated_at") or "")
    last_synced_at = str(row.get("last_synced_at") or "")
    if not updated_at:
        return False
    if not last_synced_at:
        return True
    return updated_at > last_synced_at


def _incremental_sync_table(
    sb,
    table_name: str,
    key_field: str,
    payload_rows: List[dict],
    compare_fields: List[str],
) -> dict:
    now_iso = datetime.utcnow().isoformat()
    if not payload_rows:
        return {
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "skipped_app_newer": 0,
        }

    existing_rows = _fetch_all_rows(
        sb,
        table_name,
        f"{key_field},{','.join(compare_fields)},updated_at,last_synced_at,sync_dirty,sync_source,id,legacy_source_id",
    )
    existing_by_key = {str(r.get(key_field) or ""): r for r in existing_rows}

    inserted = 0
    updated = 0
    unchanged = 0
    skipped_app_newer = 0

    for row in payload_rows:
        key_value = str(row.get(key_field) or "")
        if not key_value:
            continue

        existing = existing_by_key.get(key_value)
        payload_with_tracking = {
            **row,
            "last_synced_at": now_iso,
            "sync_dirty": False,
            "sync_source": "sheet",
            "source_updated_at": now_iso,
        }

        if not existing:
            sb.table(table_name).insert(payload_with_tracking).execute()
            inserted += 1
            continue

        if _has_unsynced_app_change(existing):
            skipped_app_newer += 1
            continue

        row_changed = any(
            not _same_value(existing.get(field), row.get(field))
            for field in compare_fields
        )

        if not row_changed:
            unchanged += 1
            continue

        sb.table(table_name).update(payload_with_tracking).eq(key_field, key_value).execute()
        updated += 1

    return {
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "skipped_app_newer": skipped_app_newer,
    }


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
    # Use exact-name matching first for critical services columns to avoid
    # accidental partial matches (for example mapping PRICE to a wrong column).
    price_h = _get_exact_match(service_headers, ["PRICE"]) or _get_first_match(service_headers, ["PRICE", "UNIT PRICE", "AMOUNT CHARGED"])
    paid_h = _get_exact_match(service_headers, ["Amount paid"]) or _get_first_match(service_headers, ["Amount paid", "PAID", "PAID AMOUNT"])
    status_h = _get_exact_match(service_headers, ["STATUS"]) or _get_first_match(service_headers, ["STATUS", "PAYMENT STATUS"])
    date_h = _get_exact_match(service_headers, ["DATE"]) or _get_first_match(service_headers, ["DATE", "SERVICE DATE", "INVOICE DATE"])
    paid_date_h = _get_exact_match(service_headers, ["PAID DATE"]) or _get_first_match(service_headers, ["PAID DATE"])
    due_h = _get_first_match(service_headers, ["DUE DATE"])
    client_h = _get_exact_match(service_headers, ["NAME"]) or _get_first_match(service_headers, ["NAME", "CLIENT", "CLIENT NAME"])
    service_h = _get_exact_match(service_headers, ["DESCRIPTION"]) or _get_first_match(service_headers, ["SERVICE NAME", "DESCRIPTION", "FAULT", "SERVICE"])
    qty_h = _get_first_match(service_headers, ["QUANTITY", "QTY"])
    expense_h = _get_exact_match(service_headers, ["EXPENSE AMOUNT"]) or _get_first_match(service_headers, ["SERVICE EXPENSE", "EXPENSE", "EXPENSE AMOUNT"])
    expense_desc_h = _get_exact_match(service_headers, ["EXPENSE DESCRIPTION"]) or _get_first_match(service_headers, ["EXPENSE DESCRIPTION"])
    expense_date_h = _get_first_match(service_headers, ["EXPENSE DATE"])
    notes_h = _get_first_match(service_headers, ["NOTES"])
    imei_h = _get_exact_match(service_headers, ["IMEI"]) or _get_first_match(service_headers, ["IMEI", "SERIAL", "SERIAL NUMBER", "DEVICE IMEI", "IMEI NUMBER"])

    service_payload = []
    skipped_service_overflow = 0
    skipped_service_placeholder = 0
    for idx, row in enumerate(service_rows):
        amount_charged = to_number(row.get(price_h)) if price_h else 0.0
        paid_amount = to_number(row.get(paid_h)) if paid_h else 0.0
        quantity = to_number(row.get(qty_h)) if qty_h else 1.0
        service_expense = to_number(row.get(expense_h)) if expense_h else 0.0

        client_name_raw = str(row.get(client_h) or "").strip() if client_h else ""
        description_raw = str(row.get(service_h) or "").strip() if service_h else ""

        if (
            _is_placeholder_text(client_name_raw)
            or _is_placeholder_text(description_raw)
            or (amount_charged == 0 and paid_amount == 0)
        ):
            skipped_service_placeholder += 1
            continue

        service_name = description_raw

        if not all(
            _fits_numeric12(v)
            for v in [amount_charged, paid_amount, quantity, service_expense]
        ):
            skipped_service_overflow += 1
            continue

        # Preserve IMEI as a clean string; gspread may return numeric-looking values
        # as floats (e.g. 353956078843009.0) — strip the trailing ".0" so the IMEI
        # matches what is stored in inventory_items.
        raw_imei = row.get(imei_h, "") if imei_h else ""
        imei_str = str(raw_imei).strip()
        # If gspread returned a float representation, drop the decimal part
        if imei_str.endswith(".0") and imei_str[:-2].isdigit():
            imei_str = imei_str[:-2]
        # Reject placeholder values (dots only, dashes only, too short)
        import re as _re
        if not _re.search(r'[A-Za-z0-9]', imei_str) or len(imei_str) < 5:
            imei_str = None
        imei_str = imei_str or None

        # Determine payment status and set paid_at
        payment_status = _normalized_payment_status(row.get(status_h, "") if status_h else "")
        paid_date_value = _parse_date(row.get(paid_date_h)) if paid_date_h else None
        service_date_value = _parse_date(row.get(date_h)) if date_h else None

        # Normalize paid_amount by payment status:
        # PAID: paid_amount must equal amount_charged if it is 0/null
        # UNPAID: force paid_amount = 0
        # RETURNED: force paid_amount = 0 and mark as return
        # PARTIAL/PART PAYMENT: keep the actual value from the sheet
        paid_at_value = None
        is_return_value = False
        if payment_status == "PAID":
            if paid_amount <= 0:
                paid_amount = amount_charged
            # Prefer PAID DATE, fall back to service date, then sentinel so the DB
            # trigger (set_paid_at_once) does NOT stamp the row with NOW() and inflate metrics.
            paid_at_value = paid_date_value or service_date_value or _PRE_ACCOUNTING_SENTINEL
        elif payment_status == "RETURNED":
            paid_amount = 0.0
            paid_at_value = None
            is_return_value = True
        elif payment_status == "UNPAID":
            paid_amount = 0.0
            paid_at_value = None
        # PART PAYMENT: keep actual paid_amount from sheet; paid_at stays None

        service_payload.append(
            {
                "legacy_source_id": f"sheet_import:service:{idx + 1}",
                "sheet_row_number": int(row.get("__sheet_row_number") or 0),
                "client_name": client_name_raw,
                "service_name": service_name,
                "description": description_raw,
                "quantity": quantity or 1.0,
                "amount_charged": amount_charged,
                "paid_amount": paid_amount,
                "service_expense_amount": service_expense,
                "service_expense_description": str(row.get(expense_desc_h) or "").strip() if expense_desc_h else None,
                "service_expense_date": _parse_date(row.get(expense_date_h)) if expense_date_h else None,
                "calculated_profit": paid_amount,
                "payment_status": payment_status,
                "is_return": is_return_value,
                "paid_date": paid_date_value,
                "paid_at": paid_at_value,  # This is the key field for profit calculations
                "service_date": service_date_value,
                "due_date": _parse_date(row.get(due_h)) if due_h else None,
                "notes": str(row.get(notes_h) or "").strip() if notes_h else None,
                "imei": imei_str,
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
                "legacy_source_id": f"sheet_import:client:{idx + 1}",
                "sheet_row_number": int(row.get("__sheet_row_number") or 0),
                "name": name,
                "phone": str(row.get(client_phone_h) or "").strip() if client_phone_h else None,
                "email": str(row.get(client_email_h) or "").strip() if client_email_h else None,
                "address": str(row.get(client_address_h) or "").strip() if client_address_h else None,
                "company": str(row.get(client_company_h) or "").strip() if client_company_h else None,
                "notes": str(row.get(client_notes_h) or "").strip() if client_notes_h else None,
            }
        )

    inventory_headers = list(inventory_rows[0].keys()) if inventory_rows else []
    item_h = _get_first_match(inventory_headers, ["DESCRIPTION", "DEVICE", "ITEM", "PRODUCT", "MODEL", "PRODUCT NAME"])
    sku_h = _get_first_match(inventory_headers, ["IMEI", "SERIAL", "SKU", "SERIAL NUMBER"])
    category_h = _get_first_match(inventory_headers, ["DEVICE", "CATEGORY", "TYPE"])
    status_h_inv = _get_first_match(inventory_headers, ["PRODUCT STATUS", "STATUS"])
    cost_h = _get_first_match(inventory_headers, ["COST PRICE", "COST", "BUY PRICE", "PURCHASE PRICE"])
    sell_h = _get_first_match(inventory_headers, ["SELLING PRICE", "SELL PRICE", "SALE PRICE", "SOLD PRICE"])
    notes_h_inv = _get_first_match(inventory_headers, ["INTERNAL NOTE", "NOTES", "NOTE"])

    inventory_payload = []
    skipped_inventory_overflow = 0
    for idx, row in enumerate(inventory_rows):
        item_name = str(row.get(item_h) or "").strip() if item_h else ""
        if not item_name:
            continue

        status = str(row.get(status_h_inv) or "").strip() if status_h_inv else ""
        normalized_status = status.upper() if status else "AVAILABLE"
        quantity = 0.0 if normalized_status == "SOLD" else 1.0
        cost_price = to_number(row.get(cost_h)) if cost_h else 0.0
        selling_price = to_number(row.get(sell_h)) if sell_h else 0.0

        if not all(_fits_numeric12(v) for v in [quantity, cost_price, selling_price]):
            skipped_inventory_overflow += 1
            continue

        # Same IMEI normalisation for inventory — strip trailing ".0" from floats
        raw_inv_imei = row.get(sku_h, "") if sku_h else ""
        inv_imei_str = str(raw_inv_imei).strip()
        if inv_imei_str.endswith(".0") and inv_imei_str[:-2].isdigit():
            inv_imei_str = inv_imei_str[:-2]
        # Reject placeholder values
        import re as _re
        if not _re.search(r'[A-Za-z0-9]', inv_imei_str) or len(inv_imei_str) < 5:
            inv_imei_str = None
        inv_imei_str = inv_imei_str or None

        inventory_payload.append(
            {
                "legacy_source_id": f"sheet_import:inventory:{idx + 1}",
                "sheet_row_number": int(row.get("__sheet_row_number") or 0),
                "item_name": item_name,
                "sku": inv_imei_str,
                "imei": inv_imei_str,
                "category": str(row.get(category_h) or "").strip() if category_h else None,
                "description": str(row.get(notes_h_inv) or "").strip() if notes_h_inv else None,
                "quantity": quantity,
                "unit": "pcs",
                "cost_price": cost_price,
                "selling_price": selling_price,
                "payment_status": normalized_status,  # Also keep payment_status for backward compatibility
            }
        )

    imei_col_missing = False
    service_sync_result = {
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped_app_newer": 0,
    }
    inventory_sync_result = {
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped_app_newer": 0,
    }
    clients_sync_result = {
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped_app_newer": 0,
    }

    if service_payload:
        try:
            service_sync_result = _incremental_sync_table(
                sb,
                "service_jobs",
                "legacy_source_id",
                service_payload,
                [
                    "sheet_row_number",
                    "client_name",
                    "service_name",
                    "description",
                    "quantity",
                    "amount_charged",
                    "paid_amount",
                    "service_expense_amount",
                    "service_expense_description",
                    "service_expense_date",
                    "calculated_profit",
                    "payment_status",
                    "is_return",
                    "paid_date",
                    "paid_at",
                    "service_date",
                    "due_date",
                    "notes",
                    "imei",
                ],
            )
        except Exception as e:
            if "PGRST204" in str(e) and "imei" in str(e):
                imei_col_missing = True
                stripped = [{k: v for k, v in r.items() if k != "imei"} for r in service_payload]
                service_sync_result = _incremental_sync_table(
                    sb,
                    "service_jobs",
                    "legacy_source_id",
                    stripped,
                    [
                        "sheet_row_number",
                        "client_name",
                        "service_name",
                        "description",
                        "quantity",
                        "amount_charged",
                        "paid_amount",
                        "service_expense_amount",
                        "service_expense_description",
                        "service_expense_date",
                        "calculated_profit",
                        "payment_status",
                        "is_return",
                        "paid_date",
                        "paid_at",
                        "service_date",
                        "due_date",
                        "notes",
                    ],
                )
            else:
                raise

    if inventory_payload:
        try:
            inventory_sync_result = _incremental_sync_table(
                sb,
                "inventory_items",
                "legacy_source_id",
                inventory_payload,
                [
                    "sheet_row_number",
                    "item_name",
                    "sku",
                    "imei",
                    "category",
                    "description",
                    "quantity",
                    "unit",
                    "cost_price",
                    "selling_price",
                    "payment_status",
                ],
            )
        except Exception as e:
            if "PGRST204" in str(e) and "imei" in str(e):
                imei_col_missing = True
                stripped = [{k: v for k, v in r.items() if k != "imei"} for r in inventory_payload]
                inventory_sync_result = _incremental_sync_table(
                    sb,
                    "inventory_items",
                    "legacy_source_id",
                    stripped,
                    [
                        "sheet_row_number",
                        "item_name",
                        "sku",
                        "category",
                        "description",
                        "quantity",
                        "unit",
                        "cost_price",
                        "selling_price",
                        "payment_status",
                    ],
                )
            else:
                raise

    if clients_payload:
        clients_sync_result = _incremental_sync_table(
            sb,
            "clients",
            "id",
            clients_payload,
            [
                "legacy_source_id",
                "sheet_row_number",
                "name",
                "phone",
                "email",
                "address",
                "company",
                "notes",
            ],
        )

    # Post-import validation: compare imported rows to sheet rows by legacy_source_id.
    imported_service_rows = _fetch_all_rows(
        sb,
        "service_jobs",
        "legacy_source_id,amount_charged,paid_amount,payment_status",
    )
    imported_by_legacy = {
        r.get("legacy_source_id"): r
        for r in imported_service_rows
        if str(r.get("legacy_source_id") or "").startswith("sheet_import:service:")
    }

    validation_checked = 0
    validation_matches = 0
    validation_mismatches: List[dict] = []
    for idx, row in enumerate(service_rows):
        expected_amount_charged = to_number(row.get(price_h)) if price_h else 0.0
        expected_paid_amount = to_number(row.get(paid_h)) if paid_h else 0.0
        expected_client_name = str(row.get(client_h) or "").strip() if client_h else ""
        expected_description = str(row.get(service_h) or "").strip() if service_h else ""

        if (
            _is_placeholder_text(expected_client_name)
            or _is_placeholder_text(expected_description)
            or (expected_amount_charged == 0 and expected_paid_amount == 0)
        ):
            continue

        legacy_source_id = f"sheet_import:service:{idx + 1}"
        imported_row = imported_by_legacy.get(legacy_source_id)
        if not imported_row:
            validation_mismatches.append(
                {
                    "legacy_source_id": legacy_source_id,
                    "reason": "missing imported row",
                }
            )
            continue

        expected_payment_status = _normalized_payment_status(row.get(status_h, "") if status_h else "")

        if expected_payment_status == "PAID" and expected_paid_amount <= 0:
            expected_paid_amount = expected_amount_charged
        elif expected_payment_status == "RETURNED":
            expected_paid_amount = 0.0
        elif expected_payment_status == "UNPAID":
            expected_paid_amount = 0.0

        actual_amount_charged = to_number(imported_row.get("amount_charged"))
        actual_paid_amount = to_number(imported_row.get("paid_amount"))
        actual_payment_status = _normalized_payment_status(imported_row.get("payment_status", ""))

        validation_checked += 1
        if (
            actual_amount_charged == expected_amount_charged
            and actual_paid_amount == expected_paid_amount
            and actual_payment_status == expected_payment_status
        ):
            validation_matches += 1
        else:
            validation_mismatches.append(
                {
                    "legacy_source_id": legacy_source_id,
                    "expected": {
                        "amount_charged": expected_amount_charged,
                        "paid_amount": expected_paid_amount,
                        "payment_status": expected_payment_status,
                    },
                    "actual": {
                        "amount_charged": actual_amount_charged,
                        "paid_amount": actual_paid_amount,
                        "payment_status": actual_payment_status,
                    },
                }
            )

    return {
        "imei_col_missing": imei_col_missing,
        "sheets_read": ["Sheet1 (Services)", "CLIENT DIRECTORY", "Sheet1 (Inventory)"],
        "rows_processed": {
            "Sheet1 (Services)": service_count,
            "CLIENT DIRECTORY": client_count,
            "Sheet1 (Inventory)": inventory_count,
        },
        "rows_upserted": {
            "service_jobs": service_sync_result["inserted"] + service_sync_result["updated"],
            "clients": clients_sync_result["inserted"] + clients_sync_result["updated"],
            "inventory_items": inventory_sync_result["inserted"] + inventory_sync_result["updated"],
        },
        "rows_unchanged": {
            "service_jobs": service_sync_result["unchanged"],
            "clients": clients_sync_result["unchanged"],
            "inventory_items": inventory_sync_result["unchanged"],
        },
        "rows_skipped_app_newer": {
            "service_jobs": service_sync_result["skipped_app_newer"],
            "clients": clients_sync_result["skipped_app_newer"],
            "inventory_items": inventory_sync_result["skipped_app_newer"],
        },
        "rows_skipped_overflow": {
            "service_jobs": skipped_service_overflow,
            "inventory_items": skipped_inventory_overflow,
        },
        "rows_skipped_placeholder": {
            "service_jobs": skipped_service_placeholder,
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
                "imei": imei_h,
                "paid_date": paid_date_h,
                "expense_amount": expense_h,
                "expense_description": expense_desc_h,
            },
            "clients": {
                "name": client_name_h,
                "phone": client_phone_h,
                "email": client_email_h,
            },
            "inventory": {
                "item": item_h,
                "sku_imei": sku_h,
                "status": status_h_inv,
                "cost_price": cost_h,
                "selling_price": sell_h,
                "category": category_h,
            },
        },
        "services_import_validation": {
            "rows_checked": validation_checked,
            "rows_matched": validation_matches,
            "rows_mismatched": len(validation_mismatches),
            "mismatches": validation_mismatches[:100],
        },
    }