"""Sync to Google Sheets – only triggered manually by the user.
No other endpoint calls Google Sheets.
"""
import json
import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.config import settings as app_settings

router = APIRouter()


def _do_sync():
    """Background task: export all tables to Google Sheets."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(
            app_settings.GOOGLE_SERVICE_ACCOUNT_JSON, scopes=SCOPES
        )
        gc = gspread.authorize(creds)
        sb = get_supabase()
        sheet_id = app_settings.GOOGLE_SHEET_ID
        if not sheet_id:
            local_settings = sb.table("app_settings").select("key,value").in_("key", ["google_sheet_id"]).execute().data or []
            settings_map = {row.get("key"): row.get("value") for row in local_settings}
            sheet_id = settings_map.get("google_sheet_id") or ""
        if not sheet_id:
            return

        def write_tab(tab_name: str, data: list[dict]):
            try:
                ws = gc.open_by_key(sheet_id).worksheet(tab_name)
            except gspread.WorksheetNotFound:
                ws = gc.open_by_key(sheet_id).add_worksheet(title=tab_name, rows=5000, cols=30)
            if not data:
                return
            headers = list(data[0].keys())
            rows = [headers] + [[str(row.get(h, "")) for h in headers] for row in data]
            ws.clear()
            ws.update(rows)

        write_tab("clients",         sb.table("clients").select("*").execute().data)
        write_tab("billing",         sb.table("service_jobs").select("*").execute().data)
        write_tab("inventory",       sb.table("inventory_items").select("*").execute().data)
        write_tab("expenses",        sb.table("manual_expenses").select("*").execute().data)
        write_tab("allowances",      sb.table("allowance_withdrawals").select("*").execute().data)
        write_tab("cashflow",        sb.table("cashflow_summary").select("*").execute().data)

        # Update last sync timestamp
        sb.table("app_settings").upsert(
            {"key": "last_sync_at", "value": datetime.utcnow().isoformat()}
        ).execute()

    except Exception as e:
        # Log but don't crash the server
        print(f"[SYNC ERROR] {e}")


@router.post("/to-sheets")
def sync_to_sheets(background_tasks: BackgroundTasks, _user=Depends(get_current_user)):
    """Manually trigger a full export to Google Sheets. Returns immediately."""
    sb = get_supabase()
    settings_rows = sb.table("app_settings").select("key,value").in_("key", ["google_sheet_id"]).execute().data or []
    settings_map = {row.get("key"): row.get("value") for row in settings_rows}

    sheet_id = app_settings.GOOGLE_SHEET_ID or settings_map.get("google_sheet_id") or ""
    service_account_json = app_settings.GOOGLE_SERVICE_ACCOUNT_JSON

    if not sheet_id:
        raise HTTPException(400, "Google Sheets not configured: set google_sheet_id in Settings or GOOGLE_SHEET_ID env var.")
    if not service_account_json or not os.path.exists(service_account_json):
        raise HTTPException(400, "Google Sheets not configured: service account JSON file not found. Set GOOGLE_SERVICE_ACCOUNT_JSON.")

    background_tasks.add_task(_do_sync)
    return {"message": "Sync to Google Sheets started. This may take a minute."}


@router.post("/refresh-workspace")
def refresh_workspace(_user=Depends(get_current_user)):
    """Update last_workspace_refresh timestamp – client re-fetches all data."""
    sb = get_supabase()
    sb.table("app_settings").upsert(
        {"key": "last_workspace_refresh", "value": datetime.utcnow().isoformat()}
    ).execute()
    return {"message": "Workspace refreshed.", "refreshed_at": datetime.utcnow().isoformat()}
