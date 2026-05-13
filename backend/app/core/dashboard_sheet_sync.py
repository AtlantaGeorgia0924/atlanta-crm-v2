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

    # Actual worksheet names in your spreadsheets
    sheet_titles = {
        "services_billing": "Sheet1",          # Services sheet - billing data
        "clients": "CLIENT DIRECTORY",         # Services sheet - client info
        "cash_flow": "CASH FLOW",              # Services sheet - cash flow data
        "debtors": "Debtors Summary",          # Services sheet - debtor balances
        "inventory": "Sheet1",                 # Stocks sheet - inventory data
    }

    # Open worksheets from Services book
    services_ws = _open_worksheet(services_book, sheet_titles["services_billing"])
    clients_ws = _open_worksheet(services_book, sheet_titles["clients"])
    cash_flow_ws = _open_worksheet(services_book, sheet_titles["cash_flow"])
    debtors_ws = _open_worksheet(services_book, sheet_titles["debtors"])
    
    # Open worksheets from Stocks book
    inventory_ws = _open_worksheet(stocks_book, sheet_titles["inventory"])

    service_rows, service_count = _worksheet_rows(services_ws) if services_ws else ([], 0)
    client_rows, client_count = _worksheet_rows(clients_ws) if clients_ws else ([], 0)
    cash_flow_rows, cash_flow_count = _worksheet_rows(cash_flow_ws) if cash_flow_ws else ([], 0)
    debtor_rows, debtor_count = _worksheet_rows(debtors_ws) if debtors_ws else ([], 0)
    inventory_rows, inventory_count = _worksheet_rows(inventory_ws) if inventory_ws else ([], 0)

    # Services Sheet1: PRICE (billed), Amount paid (collected), NAME, STATUS, DATE
    billed_header = _get_first_match(
        list(service_rows[0].keys()) if service_rows else [],
        ["PRICE", "price", "amount"],
    )
    paid_header = _get_first_match(
        list(service_rows[0].keys()) if service_rows else [],
        ["Amount paid", "amount paid", "collected"],
    )

    total_billed = sum(to_number(r.get(billed_header)) for r in service_rows) if billed_header else 0.0
    total_collected = sum(to_number(r.get(paid_header)) for r in service_rows) if paid_header else 0.0
    # Outstanding = PRICE - Amount paid
    total_outstanding = max(0.0, total_billed - total_collected)

    # Debtors Summary: count unique debtors or sum their balances
    debtor_balance_header = _get_first_match(
        list(debtor_rows[0].keys()) if debtor_rows else [],
        ["balance", "outstanding", "amount outstanding", "total"],
    )
    total_debtors = sum(to_number(r.get(debtor_balance_header)) for r in debtor_rows) if debtor_balance_header else 0.0

    # Cash Flow sheet: AMOUNT, SOURCE, CATEGORY, TYPE
    # Use AMOUNT for cash flow totals
    cash_flow_amount_header = _get_first_match(
        list(cash_flow_rows[0].keys()) if cash_flow_rows else [],
        ["AMOUNT", "amount", "total"],
    )
    total_cash_flow = sum(to_number(r.get(cash_flow_amount_header)) for r in cash_flow_rows) if cash_flow_amount_header else 0.0

    # For now, use cash flow as proxy for expenses/allowances
    # (You can split by CATEGORY if needed)
    total_expenses = total_cash_flow * 0.5  # Placeholder: split 50/50
    total_allowances = total_cash_flow * 0.5
    
    net_profit = total_billed - total_expenses - total_allowances

    # Inventory Sheet1: PRODUCT STATUS, DESCRIPTION, DEVICE, COST PRICE, NAME OF BUYER
    # Low stock = PRODUCT STATUS = "SOLD" or quantity fields
    product_status_header = _get_first_match(
        list(inventory_rows[0].keys()) if inventory_rows else [],
        ["PRODUCT STATUS", "product status", "status"],
    )
    
    # Count items with PRODUCT STATUS = "SOLD"
    low_stock_count = 0
    if product_status_header:
        low_stock_count = sum(
            1
            for r in inventory_rows
            if str(r.get(product_status_header, "")).strip().upper() == "SOLD"
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
        "total_debtors": debtor_count,
        "low_stock_count": low_stock_count,
    }

    sb.table("app_settings").upsert(
        [
            {"key": "dashboard_total_billed", "value": str(values["total_billed"])},
            {"key": "dashboard_total_collected", "value": str(values["total_collected"])},
            {"key": "dashboard_total_outstanding", "value": str(values["total_outstanding"])},
            {"key": "dashboard_total_expenses", "value": str(values["total_expenses"])},
            {"key": "dashboard_total_allowances", "value": str(values["total_allowances"])},
            {"key": "dashboard_net_profit", "value": str(values["net_profit"])},
        ],
        on_conflict="key",
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
        "Sheet1 (Services)": service_count,
        "CLIENT DIRECTORY": client_count,
        "CASH FLOW": cash_flow_count,
        "Debtors Summary": debtor_count,
        "Sheet1 (Inventory)": inventory_count,
    }
    sheets_read = [name for name, count in rows_processed.items() if count >= 0]

    return {
        "sheets_read": sheets_read,
        "rows_processed": rows_processed,
        "values_calculated": values,
    }
