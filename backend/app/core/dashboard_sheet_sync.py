import os
import re
from datetime import datetime
from typing import Dict, List, Tuple

from app.core.cashflow_sheet_sync import CASHFLOW_SUMMARY_ID, read_sheet_id
from app.core.config import settings as app_settings
from app.core.financials import to_number


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


def _worksheet_rows(worksheet) -> Tuple[List[Dict[str, str]], int]:
    raw = worksheet.get_all_values()
    if not raw:
        return [], 0
    headers = raw[0]
    data_rows = raw[1:]

    records: List[Dict[str, str]] = []
    for row in data_rows:
        cells = row + [""] * (len(headers) - len(row))
        record = {headers[i]: cells[i] for i in range(len(headers))}
        if any(str(v).strip() for v in record.values()):
            records.append(record)
    return records, len(records)


def _open_worksheet(spreadsheet, title: str):
    import gspread

    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        return None


def _sum_column(records: List[Dict[str, str]], aliases: List[str]) -> float:
    if not records:
        return 0.0
    header = _get_first_match(list(records[0].keys()), aliases)
    if not header:
        return 0.0
    return sum(to_number(r.get(header)) for r in records)


def sync_dashboard_metrics_from_sheets(sb) -> Dict:
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

    sheet_titles = {
        "services": "Services",
        "clients": "Clients",
        "expenses": "Expenses",
        "cash_flow": "Cash Flow",
        "allowances": "Allowance Withdrawals",
        "inventory": "Inventory",
    }

    services_ws = _open_worksheet(services_book, sheet_titles["services"])
    clients_ws = _open_worksheet(services_book, sheet_titles["clients"])
    expenses_ws = _open_worksheet(services_book, sheet_titles["expenses"])
    allowances_ws = _open_worksheet(services_book, sheet_titles["allowances"])
    inventory_ws = _open_worksheet(stocks_book, sheet_titles["inventory"])

    service_rows, service_count = _worksheet_rows(services_ws) if services_ws else ([], 0)
    client_rows, client_count = _worksheet_rows(clients_ws) if clients_ws else ([], 0)
    expense_rows, expense_count = _worksheet_rows(expenses_ws) if expenses_ws else ([], 0)
    allowance_rows, allowance_count = _worksheet_rows(allowances_ws) if allowances_ws else ([], 0)
    inventory_rows, inventory_count = _worksheet_rows(inventory_ws) if inventory_ws else ([], 0)

    billed_header = _get_first_match(
        list(service_rows[0].keys()) if service_rows else [],
        ["amount charged", "total", "billed", "amount"],
    )
    paid_header = _get_first_match(
        list(service_rows[0].keys()) if service_rows else [],
        ["paid amount", "amount paid", "collected", "paid"],
    )
    balance_header = _get_first_match(
        list(service_rows[0].keys()) if service_rows else [],
        ["balance", "outstanding", "amount outstanding"],
    )

    total_billed = sum(to_number(r.get(billed_header)) for r in service_rows) if billed_header else 0.0
    total_collected = sum(to_number(r.get(paid_header)) for r in service_rows) if paid_header else 0.0
    if balance_header:
        total_outstanding = sum(to_number(r.get(balance_header)) for r in service_rows)
    else:
        total_outstanding = max(0.0, total_billed - total_collected)

    total_expenses = _sum_column(expense_rows, ["amount", "expense", "expense amount", "cost", "total"])
    total_allowances = _sum_column(allowance_rows, ["amount", "withdrawal amount", "allowance"])
    net_profit = total_billed - total_expenses - total_allowances

    qty_header = _get_first_match(
        list(inventory_rows[0].keys()) if inventory_rows else [],
        ["quantity", "qty"],
    )
    reorder_header = _get_first_match(
        list(inventory_rows[0].keys()) if inventory_rows else [],
        ["reorder level", "reorder", "minimum", "min level"],
    )
    low_stock_count = 0
    if qty_header and reorder_header:
        low_stock_count = sum(
            1
            for r in inventory_rows
            if to_number(r.get(qty_header)) <= to_number(r.get(reorder_header))
        )

    values = {
        "total_billed": total_billed,
        "total_collected": total_collected,
        "total_outstanding": max(0.0, total_outstanding),
        "total_expenses": total_expenses,
        "total_allowances": total_allowances,
        "net_profit": net_profit,
        "total_clients": client_count,
        "total_invoices": service_count,
        "low_stock_count": low_stock_count,
    }

    sb.table("cashflow_summary").upsert(
        {
            "id": CASHFLOW_SUMMARY_ID,
            "period_key": "sheet_rows_summary",
            "weekly_paid_profits": values["total_collected"],
            "weekly_expenses": values["total_expenses"],
            "weekly_net_profit": values["net_profit"],
            "next_week_allowance": 0,
            "monthly_net_profit": values["total_billed"],
            "allowances_withdrawn": values["total_allowances"],
            "monthly_net_profit_left": values["total_outstanding"],
            "source_updated_at": datetime.utcnow().isoformat(),
        },
        on_conflict="id",
    ).execute()

    now_iso = datetime.utcnow().isoformat()
    sb.table("app_settings").upsert(
        [
            {"key": "dashboard_total_clients", "value": str(values["total_clients"])},
            {"key": "dashboard_total_invoices", "value": str(values["total_invoices"])},
            {"key": "dashboard_low_stock_count", "value": str(values["low_stock_count"])},
            {"key": "dashboard_last_recalculated_at", "value": now_iso},
        ],
        on_conflict="key",
    ).execute()

    rows_processed = {
        "Services": service_count,
        "Clients": client_count,
        "Expenses": expense_count,
        "Allowance Withdrawals": allowance_count,
        "Inventory": inventory_count,
        "Cash Flow": 0,
    }
    sheets_read = [name for name, count in rows_processed.items() if count >= 0]

    return {
        "sheets_read": sheets_read,
        "rows_processed": rows_processed,
        "values_calculated": values,
    }
