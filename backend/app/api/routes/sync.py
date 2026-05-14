"""Sync to Google Sheets – only triggered manually by the user.
No other endpoint calls Google Sheets.
"""
import os
import ssl
import time
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.config import settings as app_settings
from app.core.cashflow_sheet_sync import read_sheet_id
from app.core.metrics_refresh import recompute_and_persist_metrics
from app.core.sheets_import_sync import import_google_sheets_to_supabase
from app.core.service_normalization import normalize_service_jobs_data

router = APIRouter()


def _backup_imported_rows(sb, backup_stamp: str) -> dict:
    service_rows = (
        sb.table("service_jobs")
        .select("*", count="exact")
        .ilike("legacy_source_id", "sheet_import:service:%")
        .execute()
    )
    inventory_rows = (
        sb.table("inventory_items")
        .select("*", count="exact")
        .ilike("legacy_source_id", "sheet_import:inventory:%")
        .execute()
    )
    client_rows = (
        sb.table("clients")
        .select("*", count="exact")
        .ilike("id", "sheet_import:client:%")
        .execute()
    )

    service_data = service_rows.data or []
    inventory_data = inventory_rows.data or []
    client_data = client_rows.data or []

    backup_payload = [
        {
            "key": f"backup_import_service_jobs_{backup_stamp}",
            "value": json.dumps(service_data),
            "description": f"Backup before reset imported data ({backup_stamp})",
        },
        {
            "key": f"backup_import_inventory_items_{backup_stamp}",
            "value": json.dumps(inventory_data),
            "description": f"Backup before reset imported data ({backup_stamp})",
        },
        {
            "key": f"backup_import_clients_{backup_stamp}",
            "value": json.dumps(client_data),
            "description": f"Backup before reset imported data ({backup_stamp})",
        },
    ]
    sb.table("app_settings").upsert(backup_payload, on_conflict="key").execute()

    return {
        "service_jobs": len(service_data),
        "inventory_items": len(inventory_data),
        "clients": len(client_data),
    }


def _truncate_target_tables(sb) -> dict:
    service_resp = sb.table("service_jobs").delete().gte("created_at", "1900-01-01").execute()
    inventory_resp = sb.table("inventory_items").delete().gte("created_at", "1900-01-01").execute()
    clients_resp = sb.table("clients").delete().gte("created_at", "1900-01-01").execute()

    return {
        "service_jobs": len(service_resp.data or []),
        "inventory_items": len(inventory_resp.data or []),
        "clients": len(clients_resp.data or []),
    }


def _clear_cached_financial_metrics(sb) -> dict:
    settings_rows = sb.table("app_settings").select("key").execute().data or []
    cached_keys = []
    for row in settings_rows:
        key = str(row.get("key") or "")
        if key.startswith("finance_") or key.startswith("dashboard_"):
            cached_keys.append(key)

    if cached_keys:
        sb.table("app_settings").delete().in_("key", cached_keys).execute()

    return {"keys_cleared": len(cached_keys), "keys": cached_keys}


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
        metrics = recompute_and_persist_metrics(sb, source="supabase")
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

    # Normalize all service_jobs data (payment status, amounts, dates, returns)
    normalization_result = normalize_service_jobs_data(sb)

    try:
        metrics = recompute_and_persist_metrics(sb, source="supabase_after_sheet_import")
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
        "normalization": normalization_result,
        "values_calculated": metrics,
    }


@router.post("/refresh-supabase")
def refresh_from_supabase(_user=Depends(get_current_user)):
    """Backward-compatible alias for refresh-workspace (Supabase-only)."""
    return refresh_workspace(_user)


@router.post("/reset-imported-data-rebuild")
def reset_imported_data_and_rebuild(_user=Depends(get_current_user)):
    """
    Backup imported rows, truncate target tables, clear cached metrics,
    import fresh rows from Google Sheets, then recalculate all metrics.
    """
    sb = get_supabase()
    backup_stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    try:
        backup_counts = _backup_imported_rows(sb, backup_stamp)
        deleted_counts = _truncate_target_tables(sb)
        cache_clear = _clear_cached_financial_metrics(sb)

        import_result = import_google_sheets_to_supabase(sb)
        # Normalize all service_jobs data (payment status, amounts, dates, returns)
        normalization_result = normalize_service_jobs_data(sb)
        metrics = recompute_and_persist_metrics(sb, source="reset_imported_data_rebuild")
    except Exception as e:
        raise HTTPException(500, f"Reset imported data and rebuild failed: {str(e)}")

    refreshed_at = datetime.utcnow().isoformat()
    sb.table("app_settings").upsert(
        {"key": "last_reset_imported_data_rebuild", "value": refreshed_at}
    ).execute()

    return {
        "message": "Imported data reset and rebuild completed.",
        "refreshed_at": refreshed_at,
        "source": "reset_imported_data_rebuild",
        "backup": {
            "stamp": backup_stamp,
            "rows_backed_up": backup_counts,
        },
        "deleted_rows": deleted_counts,
        "cache_cleared": cache_clear,
        "imported_rows": import_result.get("rows_upserted", {}),
        "rows_processed": import_result.get("rows_processed", {}),
        "final_metrics": metrics,
    }
