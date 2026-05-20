from typing import Any, Dict, List
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from app.db.supabase_client import get_supabase
from app.core.dashboard_metrics import compute_metrics_from_supabase, compute_profit_ledger, _norm_imei
from app.core.cashflow_sheet_sync import read_sheet_id
from app.core.google_sheets_auth import (
    build_google_service_account_credentials,
    validate_google_service_account_config,
)
from app.core.auth import get_current_user
from app.core.financials import to_number
from app.core.debtors import compute_debtors_from_supabase

router = APIRouter(tags=["Debug"])


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


def _sum_cashflow_transactions(records: List[Dict[str, str]]) -> tuple[float, float]:
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


def _extract_cashflow_totals(values: List[List[str]], records: List[Dict[str, str]]) -> tuple[float, float]:
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

    tx_expenses, tx_allowances = _sum_cashflow_transactions(records)
    if expenses_total == 0.0:
        expenses_total = tx_expenses
    if allowances_total == 0.0:
        allowances_total = tx_allowances

    return expenses_total, allowances_total


def _is_excluded_service_row(status_value: str) -> bool:
    normalized = _normalize_header(status_value)
    blocked_statuses = {"returned", "cancelled", "canceled", "refunded", "void", "reversed"}
    return normalized in blocked_statuses


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

    is_valid, config_error = validate_google_service_account_config()
    if not is_valid:
        parsing_errors.append(config_error)
        return result

    try:
        import gspread
        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds = build_google_service_account_credentials(scopes)
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

    services_values = workbook_cache["services"].get("Sheet1", [])
    clients_values = workbook_cache["services"].get("CLIENT DIRECTORY", [])
    cash_flow_values = workbook_cache["services"].get("CASH FLOW", [])
    debtors_values = workbook_cache["services"].get("Debtors Summary", [])
    inventory_values = workbook_cache["stocks"].get("Sheet1", [])

    if not services_values:
        parsing_errors.append("Sheet1 worksheet not found or empty in services spreadsheet")
    if not clients_values:
        parsing_errors.append("CLIENT DIRECTORY worksheet not found or empty")
    if not cash_flow_values:
        parsing_errors.append("CASH FLOW worksheet not found or empty")
    if not debtors_values:
        parsing_errors.append("Debtors Summary worksheet not found or empty")
    if not inventory_values:
        parsing_errors.append("Sheet1 worksheet not found or empty in stocks spreadsheet")

    service_records = _rows_as_records(services_values)
    client_records = _rows_as_records(clients_values)
    cash_flow_records = _rows_as_records(cash_flow_values)
    debtor_records = _rows_as_records(debtors_values)
    inventory_records = _rows_as_records(inventory_values)

    # Services Sheet1: use only PRICE and Amount paid
    billed_header = _get_exact_match(
        list(service_records[0].keys()) if service_records else [],
        ["PRICE"],
    )
    paid_header = _get_exact_match(
        list(service_records[0].keys()) if service_records else [],
        ["Amount paid"],
    )

    status_header = _get_exact_match(
        list(service_records[0].keys()) if service_records else [],
        ["STATUS"],
    )

    parsed_price_values: List[float] = []
    parsed_amount_paid_values: List[float] = []
    excluded_rows = 0
    total_billed = 0.0
    total_collected = 0.0
    total_outstanding = 0.0

    for row in service_records:
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
        parsed_price_values.append(price)
        parsed_amount_paid_values.append(paid)

        total_billed += price
        total_collected += paid
        total_outstanding += (price - paid)

    # Debtors Summary: sum balance column
    debtor_balance_header = _get_first_match(
        list(debtor_records[0].keys()) if debtor_records else [],
        ["balance", "outstanding", "amount outstanding", "total"],
    )
    total_debtors_balance = sum(to_number(r.get(debtor_balance_header)) for r in debtor_records) if debtor_balance_header else 0.0

    total_expenses, total_allowances = _extract_cashflow_totals(cash_flow_values, cash_flow_records)
    net_profit = total_collected - total_expenses - total_allowances

    # Inventory Sheet1: count PRODUCT STATUS = "SOLD"
    product_status_header = _get_first_match(
        list(inventory_records[0].keys()) if inventory_records else [],
        ["PRODUCT STATUS", "product status", "status"],
    )

    low_stock_count = 0
    if product_status_header:
        low_stock_count = sum(
            1
            for r in inventory_records
            if str(r.get(product_status_header, "")).strip().upper() == "SOLD"
        )

    result["calculated_dashboard_totals"] = {
        "total_billed": total_billed,
        "total_collected": total_collected,
        "total_outstanding": total_outstanding,
        "total_expenses": total_expenses,
        "total_allowances": total_allowances,
        "total_debtors_balance": total_debtors_balance,
        "net_profit": net_profit,
        "total_clients": len(client_records),
        "total_invoices": len(service_records),
        "low_stock_count": low_stock_count,
        "validation": {
            "first_10_parsed_price_values": parsed_price_values[:10],
            "first_10_parsed_amount_paid_values": parsed_amount_paid_values[:10],
            "final_totals": {
                "total_billed": total_billed,
                "total_collected": total_collected,
                "total_outstanding": total_outstanding,
                "total_expenses": total_expenses,
                "total_allowances": total_allowances,
                "net_profit": net_profit,
            },
            "excluded_rows_count": excluded_rows,
        },
        "detected_headers": {
            "services_sheet1_billed": billed_header,
            "services_sheet1_collected": paid_header,
            "services_sheet1_status": status_header,
            "debtors_balance": debtor_balance_header,
            "inventory_product_status": product_status_header,
        },
    }

    return result


@router.get("/imei-matching")
def debug_imei_matching():
    """Live IMEI matching and profit diagnostics: returns metrics, row counts, and sample IMEIs."""
    sb = get_supabase()
    # Live metrics
    metrics = compute_metrics_from_supabase(sb)
    v = metrics.get("validation", {})
    # Raw IMEI lists
    service_rows = sb.table("service_jobs").select("id,imei").neq("imei", None).execute().data or []
    inventory_rows = sb.table("inventory_items").select("id,imei,sku,cost_price").execute().data or []
    service_imeis = [_norm_imei(r.get("imei")) for r in service_rows]
    service_imeis = [imei for imei in service_imeis if imei]

    inventory_identifiers = []
    inventory_cost_map = {}
    for row in inventory_rows:
        for candidate in (row.get("imei"), row.get("sku")):
            normalized_identifier = _norm_imei(candidate)
            if normalized_identifier:
                inventory_identifiers.append(normalized_identifier)
                if normalized_identifier not in inventory_cost_map:
                    inventory_cost_map[normalized_identifier] = row.get("cost_price")

    inventory_imei_set = set(inventory_identifiers)
    unmatched_imeis = [imei for imei in service_imeis if imei not in inventory_imei_set]
    matched_imeis = [imei for imei in service_imeis if imei in inventory_imei_set]
    # Count matched rows with missing/zero cost_price
    matched_missing_cost = [
        imei
        for imei in matched_imeis
        if not inventory_cost_map.get(imei) or float(inventory_cost_map.get(imei) or 0) <= 0
    ]
    return {
        "metrics": {
            "inventory_matched_by_imei": v.get("inventory_matched_by_imei"),
            "imei_no_inventory_match": v.get("imei_no_inventory_match"),
            "skipped_missing_cost_price": v.get("skipped_missing_cost_price"),
            "total_inventory_profit": v.get("total_inventory_profit"),
            "total_service_profit": v.get("total_service_profit"),
            "final_net_profit": v.get("final_net_profit"),
        },
        "diagnostics": {
            "service_jobs_with_imei": len(service_imeis),
            "inventory_items_with_imei": len(inventory_imei_set),
            "first_20_unmatched_service_imeis": unmatched_imeis[:20],
            "first_20_inventory_imeis": inventory_identifiers[:20],
            "matched_with_missing_cost_price": len(matched_missing_cost),
        },
    }


@router.get("/metrics-validation")
def get_metrics_validation(_user=Depends(get_current_user)):
    """
    Returns top-level financial metrics for quick validation.
    """
    from datetime import datetime, timezone

    sb = get_supabase()

    try:
        metrics = compute_metrics_from_supabase(sb)
    except Exception as e:
        return {"error": str(e), "status": "failed"}

    financial = metrics.get("financial", {})
    validation = metrics.get("validation", {})

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "key_metrics": {
            "profit_seen_this_week": financial.get("profit_seen_this_week"),
            "profit_seen_this_month": financial.get("profit_seen_this_month"),
            "total_sales_collected_this_month": financial.get("total_sales_collected_this_month"),
            "total_outstanding": financial.get("total_outstanding"),
            "net_profit_of_the_week": financial.get("net_profit_of_the_week"),
            "net_profit_of_the_month": financial.get("net_profit_of_the_month"),
        },
        "breakdown": {
            "total_inventory_profit": validation.get("total_inventory_profit"),
            "total_service_profit": validation.get("total_service_profit"),
            "total_expenses": financial.get("total_expenses"),
            "total_allowances": financial.get("total_allowances"),
            "gross_profit": financial.get("gross_profit"),
            "net_profit": financial.get("net_profit"),
        },
    }


@router.get("/profit-ledger")
def get_profit_ledger(_user=Depends(get_current_user)):
    """
    Returns every transaction included in weekly and monthly profit calculations.

    Each row shows: client_name, paid_at, paid_amount, cost_price,
    expense_amount, computed_profit, inclusion_reason.

    Use this to audit and validate totals against real-world sales data.
    """
    sb = get_supabase()
    try:
        return compute_profit_ledger(sb)
    except Exception as e:
        return {"error": str(e), "status": "failed"}


@router.get("/debtors-validation")
def get_debtors_validation(_user=Depends(get_current_user)):
    """
    Return detailed debtors calculation results from the live database.
    """
    sb = get_supabase()
    try:
        debtors = compute_debtors_from_supabase(sb)
    except Exception as e:
        return {"error": str(e), "status": "failed"}

    return {
        "total_amount_owed": debtors["total_amount_owed"],
        "included_rows": debtors["included_rows"],
        "excluded_rows": debtors["excluded_rows"],
        "grouped_clients": debtors["grouped_clients"],
        "included_count": len(debtors["included_rows"]),
        "excluded_count": len(debtors["excluded_rows"]),
    }


@router.post("/recalculate-metrics")
def recalculate_metrics(_user=Depends(get_current_user)):
    """
    Force immediate recalculation of all metrics and return results.
    
    Useful for testing metric calculations without UI refresh.
    """
    from datetime import datetime, timezone
    
    sb = get_supabase()
    
    try:
        from app.core.metrics_refresh import recompute_and_persist_metrics
        metrics = recompute_and_persist_metrics(sb, source="debug_recalculate")
    except Exception as e:
        return {"error": str(e), "status": "failed"}
    
    financial = metrics.get("financial", {})
    
    return {
        "status": "recalculated",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "key_metrics": {
            "profit_seen_this_week": financial.get("profit_seen_this_week"),
            "profit_seen_this_month": financial.get("profit_seen_this_month"),
            "total_sales_collected_this_month": financial.get("total_sales_collected_this_month"),
            "total_outstanding": financial.get("total_outstanding"),
        }
    }


@router.get("/cache-status")
def get_cache_status(_user=Depends(get_current_user)):
    """
    Return the current cached metric values from app_settings.
    
    Shows what the UI is displaying vs. what's computed.
    """
    sb = get_supabase()
    
    try:
        settings = sb.table("app_settings").select("key,value").execute().data or []
    except Exception as e:
        return {"error": str(e), "status": "failed"}
    
    # Build cache dict
    cache = {}
    for setting in settings:
        key = setting.get("key", "")
        if any(x in key for x in ["profit", "expense", "collected", "outstanding", "last_"]):
            cache[key] = setting.get("value")
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cache": cache
    }
