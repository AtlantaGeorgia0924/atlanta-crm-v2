"""Sync to Google Sheets – only triggered manually by the user.
No other endpoint calls Google Sheets.
"""
import os
import ssl
import time
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.config import settings as app_settings
from app.core.cashflow_sheet_sync import read_sheet_id
from app.core.dashboard_metrics import app_settings_payload, compute_metrics_from_supabase
from app.core.sheets_import_sync import import_google_sheets_to_supabase

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

    return {
        "sheets_updated": [tab_name for _, tab_name, _ in sheet_mapping],
        "rows_written": rows_written,
        "sync_timestamp": sync_timestamp,
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
    except (ssl.SSLError, OSError, ConnectionError) as e:
        # Retry once on transient SSL errors
        try:
            time.sleep(2)
            return _sync_to_google_sheets(sb, services_sheet_id, stocks_sheet_id)
        except Exception as e2:
            raise HTTPException(500, f"Sync failed (SSL/network error): {str(e2)}")
    except Exception as e:
        raise HTTPException(500, f"Sync failed: {str(e)}")


@router.post("/refresh-workspace")
def refresh_workspace(_user=Depends(get_current_user)):
    """Recalculate dashboard and financial metrics from Supabase only."""
    sb = get_supabase()
    try:
        metrics = compute_metrics_from_supabase(sb)
        sb.table("app_settings").upsert(
            app_settings_payload(metrics, source="supabase"),
            on_conflict="key",
        ).execute()
    except Exception as e:
        raise HTTPException(500, f"Workspace refresh failed: {str(e)}")

    refreshed_at = datetime.utcnow().isoformat()
    sb.table("app_settings").upsert(
        {"key": "last_workspace_refresh", "value": refreshed_at}
    ).execute()
    return {
        "message": "Workspace refreshed from Supabase.",
        "refreshed_at": refreshed_at,
        "source": "supabase",
        "values_calculated": metrics,
    }


@router.post("/refresh-from-google-sheets")
def refresh_from_google_sheets(_user=Depends(get_current_user)):
    """Import latest services, inventory and clients from Google Sheets into Supabase."""
    sb = get_supabase()

    # Retry up to 3 times on transient SSL / network errors
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            import_result = import_google_sheets_to_supabase(sb)
            break
        except (ssl.SSLError, OSError, ConnectionError) as e:
            last_exc = e
            if attempt < 2:
                time.sleep(2 ** attempt)   # 1s, 2s back-off
            continue
        except Exception as e:
            raise HTTPException(500, f"Google Sheets refresh failed: {str(e)}")
    else:
        raise HTTPException(500, f"Google Sheets refresh failed after 3 attempts (SSL/network error): {str(last_exc)}")

    try:
        metrics = compute_metrics_from_supabase(sb)
        sb.table("app_settings").upsert(
            app_settings_payload(metrics, source="supabase_after_sheet_import"),
            on_conflict="key",
        ).execute()
    except Exception as e:
        raise HTTPException(500, f"Metric recalculation failed: {str(e)}")

    refreshed_at = datetime.utcnow().isoformat()
    sb.table("app_settings").upsert(
        {"key": "last_google_sheets_refresh", "value": refreshed_at}
    ).execute()
    return {
        "message": "Google Sheets imported into Supabase.",
        "refreshed_at": refreshed_at,
        "source": "google_sheets_import",
        **import_result,
        "values_calculated": metrics,
    }


@router.post("/refresh-supabase")
def refresh_from_supabase(_user=Depends(get_current_user)):
    """Backward-compatible alias for refresh-workspace (Supabase-only)."""
    return refresh_workspace(_user)
