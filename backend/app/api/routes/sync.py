"""Sync to Google Sheets – only triggered manually by the user.
No other endpoint calls Google Sheets.
"""
import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.config import settings as app_settings

router = APIRouter()


def _read_sheet_id(sb) -> str:
    if app_settings.GOOGLE_SHEET_ID:
        return app_settings.GOOGLE_SHEET_ID
    local_settings = (
        sb.table("app_settings")
        .select("key,value")
        .in_("key", ["google_sheet_id"])
        .execute()
        .data
        or []
    )
    settings_map = {row.get("key"): row.get("value") for row in local_settings}
    return settings_map.get("google_sheet_id") or ""


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


def _sync_to_google_sheets(sb, sheet_id: str) -> dict:
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(
        app_settings.GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=scopes,
    )
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(sheet_id)

    sheet_mapping = [
        ("Inventory", "inventory_items"),
        ("Services", "service_jobs"),
        ("Clients", "clients"),
        ("Expenses", "manual_expenses"),
        ("Cash Flow", "cashflow_summary"),
        ("Allowance Withdrawals", "allowance_withdrawals"),
    ]

    rows_written = {}
    for tab_name, table_name in sheet_mapping:
        records = sb.table(table_name).select("*").execute().data or []
        rows_written[tab_name] = _overwrite_worksheet(spreadsheet, tab_name, records)

    sync_timestamp = datetime.utcnow().isoformat()
    sb.table("app_settings").upsert(
        {"key": "last_sync_at", "value": sync_timestamp}
    ).execute()

    return {
        "sheets_updated": [tab_name for tab_name, _ in sheet_mapping],
        "rows_written": rows_written,
        "sync_timestamp": sync_timestamp,
    }


@router.post("/to-sheets")
def sync_to_sheets(_user=Depends(get_current_user)):
    """Manually trigger a full export from Supabase to Google Sheets."""
    sb = get_supabase()
    sheet_id = _read_sheet_id(sb)
    service_account_json = app_settings.GOOGLE_SERVICE_ACCOUNT_JSON

    if not sheet_id:
        raise HTTPException(400, "Google Sheets not configured: set google_sheet_id in Settings or GOOGLE_SHEET_ID env var.")
    if not service_account_json or not os.path.exists(service_account_json):
        raise HTTPException(400, "Google Sheets not configured: service account JSON file not found. Set GOOGLE_SERVICE_ACCOUNT_JSON.")
    try:
        return _sync_to_google_sheets(sb, sheet_id)
    except Exception as e:
        raise HTTPException(500, f"Sync failed: {str(e)}")


@router.post("/refresh-workspace")
def refresh_workspace(_user=Depends(get_current_user)):
    """Update last_workspace_refresh timestamp – client re-fetches all data."""
    sb = get_supabase()
    sb.table("app_settings").upsert(
        {"key": "last_workspace_refresh", "value": datetime.utcnow().isoformat()}
    ).execute()
    return {"message": "Workspace refreshed.", "refreshed_at": datetime.utcnow().isoformat()}
