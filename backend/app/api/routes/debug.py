from typing import Any, Dict, List
import os
import re

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.core.cashflow_sheet_sync import read_sheet_id
from app.core.config import settings as app_settings
from app.core.financials import to_number
from app.db.supabase_client import get_supabase

router = APIRouter()


def _normalize_header(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower())
    return re.sub(r"\s+", " ", text).strip()


def _get_first_match(headers: List[str], aliases: List[str]) -> str:
    normalized_aliases = [_normalize_header(a) for a in aliases]
    exact = {h: _normalize_header(h) for h in headers}

    for alias in normalized_aliases:
        for header, normalized in exact.items():
            if normalized == alias:
                return header
    for alias in normalized_aliases:
        for header, normalized in exact.items():
            if alias in normalized:
                return header
    return ""


def _rows_as_records(values: List[List[str]]) -> List[Dict[str, str]]:
    if not values:
        return []
    headers = values[0]
    rows = []
    for row in values[1:]:
        cells = row + [""] * (len(headers) - len(row))
        rows.append({headers[i]: cells[i] for i in range(len(headers))})
    return rows


def _sum_column(records: List[Dict[str, str]], aliases: List[str]) -> float:
    if not records:
        return 0.0
    header = _get_first_match(list(records[0].keys()), aliases)
    if not header:
        return 0.0
    return sum(to_number(r.get(header)) for r in records)


@router.get("/google-sheets")
def debug_google_sheets(_user=Depends(get_current_user)):
    sb = get_supabase()
    parsing_errors: List[str] = []

    services_sheet_id = read_sheet_id(sb, purpose="services")
    stocks_sheet_id = read_sheet_id(sb, purpose="stocks")

    result: Dict[str, Any] = {
        "spreadsheet_id_used": {
            "services": services_sheet_id,
            "stocks": stocks_sheet_id,
        },
        "worksheet_names_found": {"services": [], "stocks": []},
        "headers_detected": {"services": {}, "stocks": {}},
        "first_5_rows": {"services": {}, "stocks": {}},
        "calculated_dashboard_totals": {
            "total_billed": 0.0,
            "total_collected": 0.0,
            "total_outstanding": 0.0,
            "total_expenses": 0.0,
            "total_allowances": 0.0,
            "net_profit": 0.0,
            "total_clients": 0,
            "total_invoices": 0,
            "low_stock_count": 0,
        },
        "parsing_errors": parsing_errors,
    }

    service_account_json = app_settings.GOOGLE_SERVICE_ACCOUNT_JSON
    if not service_account_json or not os.path.exists(service_account_json):
        parsing_errors.append("Service account JSON missing or invalid path")
        return result

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds = Credentials.from_service_account_file(service_account_json, scopes=scopes)
        gc = gspread.authorize(creds)
    except Exception as exc:
        parsing_errors.append(f"Failed to initialize Google Sheets client: {exc}")
        return result

    services_book = None
    stocks_book = None

    if services_sheet_id:
        try:
            services_book = gc.open_by_key(services_sheet_id)
        except Exception as exc:
            parsing_errors.append(f"Failed to open services spreadsheet: {exc}")
    else:
        parsing_errors.append("Missing services spreadsheet ID")

    if stocks_sheet_id:
        try:
            stocks_book = gc.open_by_key(stocks_sheet_id)
        except Exception as exc:
            parsing_errors.append(f"Failed to open stocks spreadsheet: {exc}")
    else:
        parsing_errors.append("Missing stocks spreadsheet ID")

    workbook_cache: Dict[str, Dict[str, List[List[str]]]] = {"services": {}, "stocks": {}}

    for purpose, book in [("services", services_book), ("stocks", stocks_book)]:
        if not book:
            continue
        try:
            worksheets = book.worksheets()
            names = [ws.title for ws in worksheets]
            result["worksheet_names_found"][purpose] = names

            for ws in worksheets:
                try:
                    values = ws.get_all_values()
                    workbook_cache[purpose][ws.title] = values
                    headers = values[0] if values else []
                    first_five = values[1:6] if len(values) > 1 else []
                    result["headers_detected"][purpose][ws.title] = headers
                    result["first_5_rows"][purpose][ws.title] = first_five
                except Exception as exc:
                    parsing_errors.append(f"Failed reading worksheet '{ws.title}' in {purpose}: {exc}")
        except Exception as exc:
            parsing_errors.append(f"Failed listing worksheets in {purpose}: {exc}")

    services_values = workbook_cache["services"].get("Services", [])
    clients_values = workbook_cache["services"].get("Clients", [])
    expenses_values = workbook_cache["services"].get("Expenses", [])
    allowances_values = workbook_cache["services"].get("Allowance Withdrawals", [])
    inventory_values = workbook_cache["stocks"].get("Inventory", [])

    if not services_values:
        parsing_errors.append("Services worksheet not found or empty")
    if not clients_values:
        parsing_errors.append("Clients worksheet not found or empty")
    if not expenses_values:
        parsing_errors.append("Expenses worksheet not found or empty")
    if not allowances_values:
        parsing_errors.append("Allowance Withdrawals worksheet not found or empty")
    if not inventory_values:
        parsing_errors.append("Inventory worksheet not found or empty")

    service_records = _rows_as_records(services_values)
    client_records = _rows_as_records(clients_values)
    expense_records = _rows_as_records(expenses_values)
    allowance_records = _rows_as_records(allowances_values)
    inventory_records = _rows_as_records(inventory_values)

    billed_header = _get_first_match(
        list(service_records[0].keys()) if service_records else [],
        ["amount charged", "total", "billed", "amount"],
    )
    paid_header = _get_first_match(
        list(service_records[0].keys()) if service_records else [],
        ["paid amount", "amount paid", "collected", "paid"],
    )
    balance_header = _get_first_match(
        list(service_records[0].keys()) if service_records else [],
        ["balance", "outstanding", "amount outstanding"],
    )

    total_billed = sum(to_number(r.get(billed_header)) for r in service_records) if billed_header else 0.0
    total_collected = sum(to_number(r.get(paid_header)) for r in service_records) if paid_header else 0.0
    if balance_header:
        total_outstanding = sum(to_number(r.get(balance_header)) for r in service_records)
    else:
        total_outstanding = max(0.0, total_billed - total_collected)

    total_expenses = _sum_column(expense_records, ["amount", "expense", "expense amount", "cost", "total"])
    total_allowances = _sum_column(allowance_records, ["amount", "withdrawal amount", "allowance"])
    net_profit = total_billed - total_expenses - total_allowances

    qty_header = _get_first_match(
        list(inventory_records[0].keys()) if inventory_records else [],
        ["quantity", "qty"],
    )
    reorder_header = _get_first_match(
        list(inventory_records[0].keys()) if inventory_records else [],
        ["reorder level", "reorder", "minimum", "min level"],
    )

    low_stock_count = 0
    if qty_header and reorder_header:
        low_stock_count = sum(
            1
            for r in inventory_records
            if to_number(r.get(qty_header)) <= to_number(r.get(reorder_header))
        )

    result["calculated_dashboard_totals"] = {
        "total_billed": total_billed,
        "total_collected": total_collected,
        "total_outstanding": max(0.0, total_outstanding),
        "total_expenses": total_expenses,
        "total_allowances": total_allowances,
        "net_profit": net_profit,
        "total_clients": len(client_records),
        "total_invoices": len(service_records),
        "low_stock_count": low_stock_count,
        "detected_headers": {
            "services_billed": billed_header,
            "services_collected": paid_header,
            "services_outstanding": balance_header,
            "inventory_quantity": qty_header,
            "inventory_reorder_level": reorder_header,
        },
    }

    return result
