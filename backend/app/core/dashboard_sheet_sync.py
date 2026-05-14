import os
import re
import time
from datetime import datetime
from typing import Dict, List, Tuple

from app.core.cashflow_sheet_sync import read_sheet_id
from app.core.config import settings as app_settings
from app.core.dashboard_metrics import app_settings_payload
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


def _get_exact_match(headers: List[str], aliases: List[str]) -> str:
    normalized_aliases = {_normalize_header(a) for a in aliases}
    for header in headers:
        if _normalize_header(header) in normalized_aliases:
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


def _extract_label_total(values: List[List[str]], aliases: List[str]) -> float:
    normalized_aliases = [_normalize_header(a) for a in aliases]
    for row in values:
        for idx, cell in enumerate(row):
            normalized_cell = _normalize_header(cell)
            if any(alias in normalized_cell for alias in normalized_aliases):
                for candidate in row[idx + 1:]:
                    value = to_number(candidate)
                    if value != 0:
                        return value
                for candidate in row:
                    value = to_number(candidate)
                    if value != 0:
                        return value
    return 0.0


def _sum_cashflow_transactions(records: List[Dict[str, str]]) -> Tuple[float, float]:
    if not records:
        return 0.0, 0.0

    headers = list(records[0].keys())
    amount_header = _get_exact_match(headers, ["AMOUNT", "Amount"])
    source_header = _get_exact_match(headers, ["SOURCE", "Source"])
    type_header = _get_exact_match(headers, ["TYPE", "Type"])
    category_header = _get_exact_match(headers, ["CATEGORY", "Category"])
    description_header = _get_exact_match(headers, ["DESCRIPTION", "Description"])

    if not amount_header:
        return 0.0, 0.0

    expenses_total = 0.0
    allowances_total = 0.0

    for row in records:
        amount = to_number(row.get(amount_header))
        if amount == 0:
            continue

        source = _normalize_header(row.get(source_header, "") if source_header else "")
        typ = _normalize_header(row.get(type_header, "") if type_header else "")
        category = _normalize_header(row.get(category_header, "") if category_header else "")
        description = _normalize_header(row.get(description_header, "") if description_header else "")

        is_allowance = (
            "allowance" in source
            or "allowance" in typ
            or "allowance" in category
            or "allowance" in description
        )
        is_expense = (
            source in {"expense", "expenses", "cost"}
            or typ in {"expense", "expenses", "cost"}
            or "expense" in category
            or "expense" in description
            or "cost" in category
        )

        if is_allowance:
            allowances_total += abs(amount)
        elif is_expense:
            expenses_total += abs(amount)

    return expenses_total, allowances_total


def _extract_cashflow_totals(values: List[List[str]], records: List[Dict[str, str]]) -> Tuple[float, float]:
    headers = list(records[0].keys()) if records else []

    expense_aliases = ["Expenses total", "Total expenses", "Expenses"]
    allowance_aliases = ["Allowances total", "Total allowances", "Allowances"]

    expenses_header = _get_exact_match(headers, expense_aliases)
    allowances_header = _get_exact_match(headers, allowance_aliases)

    expenses_total = sum(to_number(r.get(expenses_header)) for r in records) if expenses_header else 0.0
    allowances_total = sum(to_number(r.get(allowances_header)) for r in records) if allowances_header else 0.0

    if expenses_total == 0.0:
        expenses_total = _extract_label_total(values, expense_aliases)
    if allowances_total == 0.0:
        allowances_total = _extract_label_total(values, allowance_aliases)

    # Fallback: derive totals from transactional CASH FLOW rows when summary labels are absent.
    tx_expenses, tx_allowances = _sum_cashflow_transactions(records)
    if expenses_total == 0.0:
        expenses_total = tx_expenses
    if allowances_total == 0.0:
        allowances_total = tx_allowances

    return expenses_total, allowances_total


def _upsert_with_retry(sb, payload, *, on_conflict: str, attempts: int = 3, delay_seconds: float = 0.6):
    last_error = None
    for attempt in range(attempts):
        try:
            return sb.table("app_settings").upsert(payload, on_conflict=on_conflict).execute()
        except Exception as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(delay_seconds * (attempt + 1))
    raise last_error


def _is_excluded_service_row(status_value: str) -> bool:
    normalized = _normalize_header(status_value)
    blocked_statuses = {"returned", "cancelled", "canceled", "refunded", "void", "reversed"}
    return normalized in blocked_statuses


def _normalized_payment_status(value: str) -> str:
    normalized = _normalize_header(value).upper().replace(" ", " ").strip()
    if normalized == "PART PAYMENT":
        return "PARTIAL"
    return normalized


def _is_current_month_date(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    parsed = None
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"]:
        try:
            parsed = datetime.strptime(text, fmt)
            break
        except Exception:
            parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return False
    now = datetime.utcnow()
    return parsed.year == now.year and parsed.month == now.month


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

    # Services Sheet1: PRICE, Amount paid, STATUS, DATE (+ optional service expense)
    billed_header = _get_exact_match(
        list(service_rows[0].keys()) if service_rows else [],
        ["PRICE"],
    )
    paid_header = _get_exact_match(
        list(service_rows[0].keys()) if service_rows else [],
        ["Amount paid"],
    )

    status_header = _get_exact_match(
        list(service_rows[0].keys()) if service_rows else [],
        ["STATUS"],
    )
    date_header = _get_first_match(
        list(service_rows[0].keys()) if service_rows else [],
        ["DATE", "INVOICE DATE", "SERVICE DATE"],
    )
    service_expense_header = _get_first_match(
        list(service_rows[0].keys()) if service_rows else [],
        ["SERVICE EXPENSE", "SERVICE_EXPENSE"],
    )

    parsed_price_values: List[float] = []
    parsed_amount_paid_values: List[float] = []
    excluded_rows = 0
    total_sales = 0.0
    total_collected = 0.0
    total_outstanding = 0.0
    total_service_expenses = 0.0
    total_unpaid = 0
    amount_owed = 0.0
    monthly_sales = 0.0
    total_invoices = 0

    for row in service_rows:
        raw_price = row.get(billed_header) if billed_header else None
        raw_paid = row.get(paid_header) if paid_header else None

        status_value = row.get(status_header, "") if status_header else ""
        if _is_excluded_service_row(status_value):
            excluded_rows += 1
            continue

        has_price = str(raw_price or "").strip() != ""
        has_paid = str(raw_paid or "").strip() != ""
        if not has_price and not has_paid:
            continue

        price = to_number(raw_price)
        paid = to_number(raw_paid)
        outstanding = max(0.0, price - paid)
        normalized_status = _normalized_payment_status(row.get(status_header, "") if status_header else "")
        service_expense = to_number(row.get(service_expense_header)) if service_expense_header else 0.0

        parsed_price_values.append(price)
        parsed_amount_paid_values.append(paid)

        total_sales += price
        total_collected += paid
        total_outstanding += outstanding
        total_service_expenses += service_expense
        total_invoices += 1

        if normalized_status == "UNPAID":
            total_unpaid += 1
        if normalized_status in {"UNPAID", "PART PAYMENT", "PARTIAL"}:
            amount_owed += outstanding
        if _is_current_month_date(row.get(date_header, "") if date_header else ""):
            monthly_sales += paid

    # Debtors Summary: count unique debtors or sum their balances
    debtor_balance_header = _get_first_match(
        list(debtor_rows[0].keys()) if debtor_rows else [],
        ["balance", "outstanding", "amount outstanding", "total"],
    )
    total_debtors = sum(to_number(r.get(debtor_balance_header)) for r in debtor_rows) if debtor_balance_header else 0.0

    total_expenses, total_allowances = _extract_cashflow_totals(
        cash_flow_ws.get_all_values() if cash_flow_ws else [],
        cash_flow_rows,
    )

    gross_profit = total_collected - total_expenses - total_allowances
    net_profit = gross_profit - total_service_expenses

    # Inventory Sheet1: PRODUCT STATUS values: Available, Pending Deal, Sold, Low Quality
    product_status_header = _get_first_match(
        list(inventory_rows[0].keys()) if inventory_rows else [],
        ["PRODUCT STATUS", "product status", "status"],
    )

    available_products = 0
    pending_products = 0
    low_quality_stock = 0
    if product_status_header:
        for r in inventory_rows:
            status = str(r.get(product_status_header, "")).strip().upper()
            if status == "AVAILABLE":
                available_products += 1
            elif status == "PENDING DEAL":
                pending_products += 1
            elif status == "LOW QUALITY":
                low_quality_stock += 1

    values = {
        "dashboard": {
            "clients": client_count,
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
            "total_service_expenses": total_service_expenses,
            "total_allowances": total_allowances,
            "gross_profit": gross_profit,
            "net_profit": net_profit,
        },
        "validation": {
            "first_10_parsed_price_values": parsed_price_values[:10],
            "first_10_parsed_amount_paid_values": parsed_amount_paid_values[:10],
            "final_totals": {
                "total_sales": total_sales,
                "total_collected": total_collected,
                "total_outstanding": total_outstanding,
                "total_expenses": total_expenses,
                "total_service_expenses": total_service_expenses,
                "total_allowances": total_allowances,
                "gross_profit": gross_profit,
                "net_profit": net_profit,
            },
            "detected_headers": {
                "services_price": billed_header,
                "services_amount_paid": paid_header,
                "services_status": status_header,
                "services_date": date_header,
                "services_service_expense": service_expense_header,
            },
            "excluded_rows_count": excluded_rows,
        },
    }

    _upsert_with_retry(
        sb,
        app_settings_payload(
            {
                "dashboard": values["dashboard"],
                "financial": values["financial"],
            },
            source="google_sheets",
        ),
        on_conflict="key",
    )

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
