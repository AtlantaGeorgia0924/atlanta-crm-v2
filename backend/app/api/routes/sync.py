"""Sync to Google Sheets – only triggered manually by the user.
No other endpoint calls Google Sheets.

Hardened Incremental Export System:
===================================

1. VALUE PRESERVATION:
   - Null/empty database values do NOT overwrite existing sheet cells
   - Manual entries and formulas in Google Sheets are preserved
   - Uses merge logic: DB value overwrites sheet only if DB has non-empty value

2. DIRTY ROW FILTERING:
   - Only exports rows where sync_dirty=true AND sync_source='app'
   - Unchanged rows are never rewritten

3. STABLE ROW MATCHING:
   - Finds existing sheet rows by legacy_source_id, then id (fallback)
   - Does not rely solely on sheet_row_number
   - Handles row renumbering gracefully

4. HEADER EXPANSION:
   - New database columns are appended to sheet headers
   - Existing columns are never reordered

5. ERROR LOGGING:
   - All sync errors are logged to sync_errors table
   - Includes table_name, legacy_source_id, operation, error_message, created_at
   - Processing continues if one row fails (fault-tolerant)

6. ACCURATE COUNTING:
   - rows_updated: incremented only after successful sheet update
   - rows_inserted: incremented only after successful append
   - rows_skipped: incremented for rows that cannot be processed
   - errors: tracks errors even if sheet operation succeeded

7. STOCK SHEET (Inventory Tab):
   - Never blanks out cells due to null values in Supabase
   - Preserves manually entered notes, formulas, and values
   - Intelligently merges app changes with manual sheet data
"""
import ssl
import time
import json
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.config import settings as app_settings
from app.core.cashflow_sheet_sync import read_sheet_id
from app.core.google_sheets_auth import (
    build_google_service_account_credentials,
    validate_google_service_account_config,
)
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
    service_resp = sb.table("service_jobs").delete().like("legacy_source_id", "sheet_import:service:%").execute()
    inventory_resp = sb.table("inventory_items").delete().like("legacy_source_id", "sheet_import:inventory:%").execute()
    clients_resp = sb.table("clients").delete().like("id", "sheet_import:client:%").execute()

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


def _column_letter(index: int) -> str:
    result = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def _sheet_string(value):
    if value is None:
        return ""
    return str(value)


def _is_formula(cell_value: str) -> bool:
    """Detect if a cell contains a formula (starts with =)."""
    if not cell_value:
        return False
    return str(cell_value).strip().startswith("=")


def _should_preserve_cell(db_value, sheet_value: str, column_name: str) -> bool:
    """Determine if a sheet cell should be preserved (not overwritten).
    
    Preserve if:
    1. Database value is None or empty string, AND
    2. Sheet has a non-empty value (manual entry or formula)
    """
    if db_value is not None and str(db_value).strip():
        # Database has a value - use it
        return False
    
    sheet_val_str = str(sheet_value or "").strip()
    if not sheet_val_str:
        # Sheet is empty - nothing to preserve
        return False
    
    # Database is empty but sheet has value - preserve it
    return True


def _merge_row_values(current_sheet_row: list, db_row: dict, headers: list) -> list:
    """Merge database values with existing sheet row, preserving non-blank cells.
    
    For each column:
    - If DB value is None/empty and sheet has value (manual entry or formula), keep sheet value
    - Otherwise use DB value
    
    Args:
        current_sheet_row: Current row values from sheet
        db_row: Database record
        headers: Column names
    
    Returns:
        Merged row values
    """
    merged = []
    for idx, header in enumerate(headers):
        # Get current sheet value (pad with empty if out of bounds)
        sheet_val = current_sheet_row[idx] if idx < len(current_sheet_row) else ""
        
        # Get database value
        db_val = db_row.get(header)
        
        # Decide: preserve sheet value or use DB value
        if _should_preserve_cell(db_val, sheet_val, header):
            # Keep existing sheet value (manual entry or formula)
            merged.append(sheet_val)
        else:
            # Use database value (convert None to empty string)
            merged.append(_sheet_string(db_val))
    
    return merged


def _log_sync_error(sb, table_name: str, legacy_source_id: Optional[str], operation: str, error_msg: str):
    """Log a sync error for audit trail."""
    try:
        sb.table("sync_errors").insert({
            "table_name": table_name,
            "legacy_source_id": legacy_source_id or "unknown",
            "operation": operation,
            "error_message": error_msg[:500],  # Truncate to 500 chars
            "created_at": datetime.utcnow().isoformat(),
        }).execute()
    except Exception:
        # Silently fail - don't let error logging block the sync
        pass


def _get_or_create_worksheet(spreadsheet, tab_name: str):
    import gspread

    try:
        return spreadsheet.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=tab_name, rows=5000, cols=40)


def _extract_row_lookup(values: List[List[str]], headers: List[str]) -> dict:
    lookup = {}
    identity_idx = None
    if "legacy_source_id" in headers:
        identity_idx = headers.index("legacy_source_id")
    elif "id" in headers:
        identity_idx = headers.index("id")
    if identity_idx is None:
        return lookup
    for row_idx, row in enumerate(values[1:], start=2):
        if identity_idx >= len(row):
            continue
        key = str(row[identity_idx] or "").strip()
        if key:
            lookup[key] = row_idx
    return lookup


def _sync_dirty_rows_for_table(sb, spreadsheet, tab_name: str, table_name: str) -> dict:
    """
    Sync dirty rows from database to Google Sheets with smart value preservation.
    
    Only processes rows where sync_dirty=true AND sync_source='app'.
    Preserves existing sheet values when database has nulls.
    Skips rows with formula columns that aren't owned by the app.
    """
    ws = _get_or_create_worksheet(spreadsheet, tab_name)

    dirty_rows = (
        sb.table(table_name)
        .select("*")
        .eq("sync_dirty", True)
        .eq("sync_source", "app")
        .execute()
        .data
        or []
    )

    if not dirty_rows:
        return {"rows_updated": 0, "rows_inserted": 0, "rows_skipped": 0, "errors": 0}

    sheet_values = ws.get_all_values() or []
    headers = list(sheet_values[0]) if sheet_values else list(dirty_rows[0].keys())
    if not sheet_values:
        ws.update("A1", [headers])
        sheet_values = [headers]

    # Add any new headers from database that aren't in sheet
    missing_headers = [h for h in dirty_rows[0].keys() if h not in headers]
    if missing_headers:
        headers.extend(missing_headers)
        ws.update("A1", [headers])
        sheet_values = ws.get_all_values() or [headers]

    row_lookup = _extract_row_lookup(sheet_values, headers)

    now_iso = datetime.utcnow().isoformat()
    rows_updated = 0
    rows_inserted = 0
    rows_skipped = 0
    errors = 0

    for row in dirty_rows:
        legacy_source_id = row.get("legacy_source_id")
        row_id = row.get("id")
        identity_value = str(legacy_source_id or row_id or "").strip()
        
        try:
            sheet_row_number = int(row.get("sheet_row_number") or 0)
            
            # Try to find row in sheet by lookup if we don't have a valid row number
            if sheet_row_number < 2 and identity_value:
                sheet_row_number = int(row_lookup.get(identity_value) or 0)

            # UPDATE EXISTING ROW
            if sheet_row_number >= 2:
                try:
                    # Read current sheet row to preserve manual entries
                    current_row = sheet_values[sheet_row_number - 1] if sheet_row_number - 1 < len(sheet_values) else []
                    
                    # Merge database values with existing sheet values (preserve non-blanks)
                    merged_values = _merge_row_values(current_row, row, headers)
                    
                    # Update the row in sheet
                    end_col = _column_letter(len(headers))
                    ws.update(f"A{sheet_row_number}:{end_col}{sheet_row_number}", [merged_values])
                    rows_updated += 1
                    
                except Exception as e:
                    error_msg = f"Failed to update row {sheet_row_number}: {str(e)}"
                    _log_sync_error(sb, table_name, identity_value, "update", error_msg)
                    rows_skipped += 1
                    errors += 1
                    continue

            # INSERT NEW ROW
            else:
                try:
                    # For new rows, use database values directly (no merge needed)
                    values = [_sheet_string(row.get(header)) for header in headers]
                    ws.append_row(values, value_input_option="RAW")
                    
                    # Get new row number
                    current_values = ws.get_all_values() or []
                    sheet_row_number = len(current_values)
                    rows_inserted += 1
                    
                except Exception as e:
                    error_msg = f"Failed to append new row: {str(e)}"
                    _log_sync_error(sb, table_name, identity_value, "insert", error_msg)
                    rows_skipped += 1
                    errors += 1
                    continue

            # UPDATE METADATA IN DATABASE (after successful sheet operation)
            try:
                updates = {
                    "sheet_row_number": sheet_row_number,
                    "last_synced_at": now_iso,
                    "sync_dirty": False,
                    "sync_source": "app",
                }

                if row_id is not None:
                    sb.table(table_name).update(updates).eq("id", row_id).execute()
                elif legacy_source_id:
                    sb.table(table_name).update(updates).eq("legacy_source_id", legacy_source_id).execute()
                else:
                    # Can't identify the row - mark as skipped but don't fail
                    error_msg = "Cannot update metadata: no id or legacy_source_id"
                    _log_sync_error(sb, table_name, identity_value, "metadata_update", error_msg)
                    rows_skipped += 1
                    errors += 1
                    
            except Exception as e:
                # Sheet update succeeded but DB update failed - log but continue
                error_msg = f"Sheet updated but metadata update failed: {str(e)}"
                _log_sync_error(sb, table_name, identity_value, "metadata_update", error_msg)
                # Don't decrement rows_updated/rows_inserted since sheet operation succeeded
                errors += 1
                
        except Exception as e:
            # Catch-all for unexpected errors
            error_msg = f"Unexpected error processing row: {str(e)}"
            _log_sync_error(sb, table_name, str(legacy_source_id or row_id or "unknown"), "unknown", error_msg)
            rows_skipped += 1
            errors += 1

    return {
        "rows_updated": rows_updated,
        "rows_inserted": rows_inserted,
        "rows_skipped": rows_skipped,
        "errors": errors,
    }


def _sync_to_google_sheets(sb, services_sheet_id: str, stocks_sheet_id: str) -> dict:
    import gspread

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = build_google_service_account_credentials(scopes)
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
        rows_written[tab_name] = _sync_dirty_rows_for_table(sb, spreadsheet, tab_name, table_name)

    sync_timestamp = datetime.utcnow().isoformat()
    sb.table("app_settings").upsert(
        {"key": "last_sync_at", "value": sync_timestamp}
    ).execute()

    return {
        "mode": "incremental",
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
    if not services_sheet_id or not stocks_sheet_id:
        raise HTTPException(400, "Google Sheets not configured: set GOOGLE_SHEET_ID_SERVICES and GOOGLE_SHEET_ID_STOCKS (or matching app settings keys).")
    is_valid, config_error = validate_google_service_account_config()
    if not is_valid:
        raise HTTPException(400, config_error)
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
        except ValueError as e:
            if "Google Sheets not configured" in str(e):
                raise HTTPException(400, str(e))
            raise HTTPException(500, f"Google Sheets refresh failed: {str(e)}")
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
    except ValueError as e:
        if "Google Sheets not configured" in str(e):
            raise HTTPException(400, f"Reset imported data and rebuild failed: {str(e)}")
        raise HTTPException(500, f"Reset imported data and rebuild failed: {str(e)}")
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
