"""Sync to Google Sheets – only triggered manually by the user.
No other endpoint calls Google Sheets.
"""
import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.config import settings as app_settings
from app.core.cashflow_sheet_sync import read_sheet_id, sync_cashflow_summary_from_sheet

router = APIRouter()
def _overwrite_worksheet(spreadsheet, tab_name: str, data: list[dict]) -> int:
    import gspread

    try:
        ws = spreadsheet.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=tab_name, rows=5000, cols=40)

    ws.clear()
    if not data:
        return 0

    headers = list(data[0].keys())
    values = [headers] + [[str(row.get(h, "")) for h in headers] for row in data]
    ws.update(values)
    return len(data)


def _sync_to_google_sheets(sb, services_sheet_id: str, stocks_sheet_id: str) -> dict:
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(
        app_settings.GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=scopes,
    )
    gc = gspread.authorize(creds)
    services_spreadsheet = gc.open_by_key(services_sheet_id)
    stocks_spreadsheet = gc.open_by_key(stocks_sheet_id)

    sheet_mapping = [
        (stocks_spreadsheet, "Inventory", "inventory_items"),
        (services_spreadsheet, "Services", "service_jobs"),
        (services_spreadsheet, "Clients", "clients"),
        (services_spreadsheet, "Expenses", "manual_expenses"),
        (services_spreadsheet, "Cash Flow", "cashflow_summary"),
        (services_spreadsheet, "Allowance Withdrawals", "allowance_withdrawals"),
    ]

    rows_written = {}
    for spreadsheet, tab_name, table_name in sheet_mapping:
        records = sb.table(table_name).select("*").execute().data or []
        rows_written[tab_name] = _overwrite_worksheet(spreadsheet, tab_name, records)

    sync_timestamp = datetime.utcnow().isoformat()
    sb.table("app_settings").upsert(
        {"key": "last_sync_at", "value": sync_timestamp}
    ).execute()

    cashflow_sync_details = None
    try:
        cashflow_sync_details = sync_cashflow_summary_from_sheet(sb)
    except Exception as e:
        print(f"[sync] cashflow sheet refresh skipped: {e}")

    return {
        "sheets_updated": [tab_name for tab_name, _ in sheet_mapping],
        "rows_written": rows_written,
        "sync_timestamp": sync_timestamp,
        "cashflow_summary_refresh": cashflow_sync_details,
    }


@router.post("/to-sheets")
def sync_to_sheets(_user=Depends(get_current_user)):
    """Manually trigger a full export from Supabase to Google Sheets."""
    sb = get_supabase()
    services_sheet_id = read_sheet_id(sb, purpose="services")
    stocks_sheet_id = read_sheet_id(sb, purpose="stocks")
    service_account_json = app_settings.GOOGLE_SERVICE_ACCOUNT_JSON

    if not services_sheet_id or not stocks_sheet_id:
        raise HTTPException(400, "Google Sheets not configured: set GOOGLE_SHEET_ID_SERVICES and GOOGLE_SHEET_ID_STOCKS (or matching app settings keys).")
    if not service_account_json or not os.path.exists(service_account_json):
        raise HTTPException(400, "Google Sheets not configured: service account JSON file not found. Set GOOGLE_SERVICE_ACCOUNT_JSON.")
    try:
        return _sync_to_google_sheets(sb, services_sheet_id, stocks_sheet_id)
    except Exception as e:
        raise HTTPException(500, f"Sync failed: {str(e)}")


@router.post("/refresh-workspace")
def refresh_workspace(_user=Depends(get_current_user)):
    """Update last_workspace_refresh timestamp – client re-fetches all data."""
    sb = get_supabase()
    cashflow_sync_details = None
    try:
        cashflow_sync_details = sync_cashflow_summary_from_sheet(sb)
    except Exception as e:
        print(f"[refresh-workspace] cashflow sheet refresh skipped: {e}")

    sb.table("app_settings").upsert(
        {"key": "last_workspace_refresh", "value": datetime.utcnow().isoformat()}
    ).execute()
    return {
        "message": "Workspace refreshed.",
        "refreshed_at": datetime.utcnow().isoformat(),
        "cashflow_summary_refresh": cashflow_sync_details,
    }
