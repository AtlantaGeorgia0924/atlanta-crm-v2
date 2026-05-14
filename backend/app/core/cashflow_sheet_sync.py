import os
import re
import time
from datetime import datetime
from typing import Dict, List

from app.core.config import settings as app_settings
from app.core.financials import to_number

CASHFLOW_SUMMARY_ID = "dashboard_totals"


def _read_settings_with_retry(sb, keys: List[str], attempts: int = 3, delay_seconds: float = 0.5):
    last_error = None
    for attempt in range(attempts):
        try:
            return (
                sb.table("app_settings")
                .select("key,value")
                .in_("key", keys)
                .execute()
                .data
                or []
            )
        except Exception as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(delay_seconds * (attempt + 1))
    raise last_error


def read_sheet_id(sb, purpose: str = "services") -> str:
    """
    Resolve Google Sheet ID by purpose with backward compatibility.

    Priority:
      1) purpose-specific env var
      2) purpose-specific app_settings key
      3) legacy single env var
      4) legacy single app_settings key
    """
    purpose = str(purpose or "services").strip().lower()

    if purpose == "stocks":
        if app_settings.GOOGLE_SHEET_ID_STOCKS:
            return app_settings.GOOGLE_SHEET_ID_STOCKS
        purpose_key = "google_sheet_id_stocks"
    else:
        if app_settings.GOOGLE_SHEET_ID_SERVICES:
            return app_settings.GOOGLE_SHEET_ID_SERVICES
        purpose_key = "google_sheet_id_services"

    local_settings = _read_settings_with_retry(sb, [purpose_key, "google_sheet_id"])
    settings_map = {row.get("key"): row.get("value") for row in local_settings}

    purpose_value = str(settings_map.get(purpose_key) or "").strip()
    if purpose_value:
        return purpose_value

    if app_settings.GOOGLE_SHEET_ID:
        return app_settings.GOOGLE_SHEET_ID
    return str(settings_map.get("google_sheet_id") or "").strip()


def _get_cashflow_worksheet(sheet_id: str):
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(
        app_settings.GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=scopes,
    )
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(sheet_id)
    return spreadsheet.worksheet("Cash Flow")


def _normalize_label(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _extract_first_numeric(cells: List[str]) -> float:
    for cell in cells:
        value = to_number(cell)
        if value != 0:
            return value
    return 0.0


def _parse_cashflow_summary(rows: List[List[str]]) -> Dict[str, float]:
    labels = {
        "total_billed": ["total billed", "billed", "total sales"],
        "total_collected": ["collected", "total collected", "cash in", "paid"],
        "total_outstanding": ["outstanding", "total outstanding", "debtors", "receivable"],
        "total_expenses": ["total expenses", "expenses"],
        "total_allowances": ["allowances", "total allowances", "allowance withdrawals"],
        "net_profit": ["net profit", "profit", "monthly net profit"],
    }

    found = {
        "total_billed": 0.0,
        "total_collected": 0.0,
        "total_outstanding": 0.0,
        "total_expenses": 0.0,
        "total_allowances": 0.0,
        "net_profit": 0.0,
    }

    for row in rows:
        normalized_row = [_normalize_label(c) for c in row]
        for i, cell in enumerate(normalized_row):
            if not cell:
                continue
            raw_tail = row[i + 1 :]
            for key, aliases in labels.items():
                if any(alias in cell for alias in aliases):
                    value = _extract_first_numeric(raw_tail)
                    if value == 0:
                        value = _extract_first_numeric(row)
                    if value != 0 or found[key] == 0:
                        found[key] = value

    # Enforce financial consistency as safety fallback.
    if found["total_outstanding"] < 0:
        found["total_outstanding"] = 0.0
    if found["net_profit"] == 0:
        found["net_profit"] = (
            found["total_collected"]
            - found["total_expenses"]
            - found["total_allowances"]
        )

    return found


def sync_cashflow_summary_from_sheet(sb) -> Dict[str, Dict]:
    sheet_id = read_sheet_id(sb, purpose="services")
    service_account_json = app_settings.GOOGLE_SERVICE_ACCOUNT_JSON

    if not sheet_id:
        raise ValueError("Google Sheets not configured: missing google_sheet_id")
    if not service_account_json or not os.path.exists(service_account_json):
        raise ValueError("Google Sheets not configured: service account JSON missing")

    ws = _get_cashflow_worksheet(sheet_id)
    rows = ws.get_all_values()
    parsed = _parse_cashflow_summary(rows)

    saved_row = {
        "id": CASHFLOW_SUMMARY_ID,
        "period_key": "sheet_summary",
        "weekly_paid_profits": parsed["total_collected"],
        "weekly_expenses": parsed["total_expenses"],
        "weekly_net_profit": parsed["net_profit"],
        "next_week_allowance": 0,
        "monthly_net_profit": parsed["total_billed"],
        "allowances_withdrawn": parsed["total_allowances"],
        "monthly_net_profit_left": parsed["total_outstanding"],
        "source_updated_at": datetime.utcnow().isoformat(),
    }

    settings_payload = [
        {"key": "dashboard_total_billed", "value": str(saved_row["monthly_net_profit"])},
        {"key": "dashboard_total_collected", "value": str(saved_row["weekly_paid_profits"])},
        {"key": "dashboard_total_outstanding", "value": str(saved_row["monthly_net_profit_left"])},
        {"key": "dashboard_total_expenses", "value": str(saved_row["weekly_expenses"])},
        {"key": "dashboard_total_allowances", "value": str(saved_row["allowances_withdrawn"])},
        {"key": "dashboard_net_profit", "value": str(saved_row["weekly_net_profit"])},
    ]
    sb.table("app_settings").upsert(settings_payload, on_conflict="key").execute()

    persisted = saved_row

    displayed_values = {
        "total_billed": to_number(persisted.get("monthly_net_profit")),
        "total_collected": to_number(persisted.get("weekly_paid_profits")),
        "total_outstanding": max(0.0, to_number(persisted.get("monthly_net_profit_left"))),
        "total_expenses": to_number(persisted.get("weekly_expenses")),
        "total_allowances": to_number(persisted.get("allowances_withdrawn")),
        "net_profit": to_number(persisted.get("weekly_net_profit")),
    }

    return {
        "values_read_from_google_sheets": parsed,
        "values_saved_to_cashflow_summary": {
            "id": persisted.get("id", CASHFLOW_SUMMARY_ID),
            "period_key": persisted.get("period_key", "sheet_summary"),
            "monthly_net_profit": displayed_values["total_billed"],
            "weekly_paid_profits": displayed_values["total_collected"],
            "monthly_net_profit_left": displayed_values["total_outstanding"],
            "weekly_expenses": displayed_values["total_expenses"],
            "allowances_withdrawn": displayed_values["total_allowances"],
            "weekly_net_profit": displayed_values["net_profit"],
        },
        "values_displayed_on_dashboard": displayed_values,
    }
