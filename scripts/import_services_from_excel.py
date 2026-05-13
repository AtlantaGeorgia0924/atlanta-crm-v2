#!/usr/bin/env python3
"""
Import service/billing data from INVENTORY-3.xlsx into service_jobs table.
Clears existing service_jobs data and repopulates from Excel.
Also creates/updates clients from the imported records.
Uses batch inserts for efficiency.
"""

import sys
import os
from datetime import datetime
import uuid

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'backend', '.env'))

from app.db.supabase_client import get_supabase

try:
    import openpyxl
except ImportError:
    print("ERROR: openpyxl not installed. Run: pip install openpyxl")
    sys.exit(1)

BATCH_SIZE = 100


def to_iso_string(dt):
    """Convert datetime to ISO string or return as-is if already string."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    if isinstance(dt, str):
        s = dt.strip() if dt else ""
        return s if s else None
    return None




def import_services():
    """Import services from Excel with batch operations."""
    sb = get_supabase()
    
    file_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'INVENTORY-3.xlsx')
    if not os.path.exists(file_path):
        print(f"ERROR: Excel file not found at {file_path}")
        sys.exit(1)
    
    print("[*] Loading Excel file...")
    wb = openpyxl.load_workbook(file_path, data_only=False)
    ws = wb['Sheet1']
    
    # Read headers
    headers = {}
    for col_idx, cell in enumerate(ws[1], start=1):
        if cell.value:
            headers[cell.value] = col_idx
    
    print(f"[*] Found {len(headers)} columns in Excel")
    
    # Step 1: Delete all existing service_jobs
    print("\n[1/4] Deleting existing service_jobs...")
    deleted_count = 0
    try:
        all_records = sb.table("service_jobs").select("id", count="exact").execute()
        if hasattr(all_records, 'count') and all_records.count and all_records.count > 0:
            # Batch delete in chunks
            for record in (all_records.data or []):
                try:
                    sb.table("service_jobs").delete().eq("id", record["id"]).execute()
                    deleted_count += 1
                except Exception as e:
                    pass  # Continue on individual failures
    except Exception as e:
        print(f"  (Delete operation note: {str(e)[:50]})")
    
    print(f"  ✓ Deleted {deleted_count} existing rows")
    
    # Step 2: Parse Excel and collect data
    print("\n[2/4] Parsing Excel file...")
    service_records = []
    clients_map = {}
    parse_errors = 0
    skipped_rows = 0
    
    for row_idx in range(2, min(ws.max_row + 1, 2000)):  # Limit to 2000 rows for safety
        try:
            row = list(ws[row_idx])
            
            def get_cell(col_name):
                col_idx = headers.get(col_name)
                if not col_idx or col_idx > len(row):
                    return None
                val = row[col_idx - 1].value if hasattr(row[col_idx - 1], 'value') else row[col_idx - 1]
                return val
            
            name = str(get_cell('NAME') or "").strip()
            phone = str(get_cell('PHONE NUMBER') or "").strip()
            description = str(get_cell('DESCRIPTION') or "").strip()
            price = float(get_cell('PRICE') or 0)
            amount_paid = float(get_cell('Amount paid') or 0)
            paid_date = get_cell('PAID DATE')
            expense_amount = float(get_cell('EXPENSE AMOUNT') or 0)
            service_date = get_cell('DATE')
            record_id = str(get_cell('RECORD_ID') or "")
            
            # Skip empty rows
            if not name or price == 0:
                skipped_rows += 1
                continue
            
            # Track client
            if name and phone and not phone.startswith('='):
                clients_map[name] = phone
            
            # Determine status
            balance = price - amount_paid
            if balance <= 0:
                final_status = "PAID"
            elif amount_paid > 0:
                final_status = "PARTIAL"
            else:
                final_status = "UNPAID"
            
            service_records.append({
                "name": name,
                "description": description,
                "price": price,
                "amount_paid": amount_paid,
                "balance": balance,
                "status": final_status,
                "paid_date": to_iso_string(paid_date),
                "service_date": to_iso_string(service_date),
                "expense_amount": expense_amount,
                "record_id": record_id,
            })
        
        except Exception as e:
            parse_errors += 1
            if parse_errors <= 3:
                print(f"  (Row {row_idx} parse note: {str(e)[:40]})")
    
    print(f"  ✓ Parsed {len(service_records)} service records ({parse_errors} parse notes)")
    print(f"  ✓ Skipped {skipped_rows} rows (empty or zero amount)")
    print(f"  ✓ Found {len(clients_map)} unique clients")
    
    # Step 3: Batch create clients
    print("\n[3/4] Creating clients...")
    clients_created = 0
    clients_updated = 0
    
    try:
        clients_list = list(clients_map.items())
        for i in range(0, len(clients_list), BATCH_SIZE):
            batch = clients_list[i:i+BATCH_SIZE]
            batch_inserts = []
            
            for client_name, phone_number in batch:
                batch_inserts.append({
                    "id": str(uuid.uuid4()),
                    "name": client_name,
                    "phone": phone_number,
                })
            
            try:
                sb.table("clients").insert(batch_inserts).execute()
                clients_created += len(batch_inserts)
            except Exception as e:
                # May fail due to duplicates, try individual inserts
                for item in batch_inserts:
                    try:
                        sb.table("clients").insert([item]).execute()
                        clients_created += 1
                    except:
                        try:
                            sb.table("clients").update({"phone": item["phone"]}).eq("name", item["name"]).execute()
                            clients_updated += 1
                        except:
                            pass
            
            if (i // BATCH_SIZE + 1) % 5 == 0:
                print(f"  ... {clients_created} clients created")
    
    except Exception as e:
        print(f"  ✗ Client creation error: {str(e)[:60]}")
    
    print(f"  ✓ Created {clients_created} clients")
    print(f"  ✓ Updated {clients_updated} existing clients")
    
    # Step 4: Batch import services
    print("\n[4/4] Importing service records...")
    services_imported = 0
    import_errors = 0
    
    try:
        # Build all service inserts first.
        batch_inserts = []

        # Build client name -> id map once to avoid per-row lookups.
        client_name_to_id = {}
        try:
            client_rows = sb.table("clients").select("id,name").execute().data or []
            client_name_to_id = {
                str(r.get("name") or "").strip(): r.get("id")
                for r in client_rows
                if str(r.get("name") or "").strip()
            }
        except Exception:
            client_name_to_id = {}
        
        for rec in service_records:
            # Find client_id from prebuilt map.
            client_id = client_name_to_id.get(rec["name"])
            
            batch_inserts.append({
                "id": str(uuid.uuid4()),
                "client_id": client_id,
                "client_name": rec["name"],
                "service_name": (rec["description"][:100] if rec["description"] else "Service"),
                "description": rec["description"],
                "quantity": 1.0,
                "amount_charged": rec["price"],
                "paid_amount": rec["amount_paid"],
                "payment_status": rec["status"],
                "paid_date": rec["paid_date"],
                "service_date": rec["service_date"],
                "due_date": rec["service_date"],
                "expense_amount": rec["expense_amount"],
                "calculated_profit": rec["price"] - rec["expense_amount"],
                "notes": None,
                "legacy_source_id": rec["record_id"],
            })
        
        # Insert in batches
        for i in range(0, len(batch_inserts), BATCH_SIZE):
            batch = batch_inserts[i:i+BATCH_SIZE]
            
            try:
                sb.table("service_jobs").insert(batch).execute()
                services_imported += len(batch)
            except Exception as e:
                # Try individual inserts as fallback
                for item in batch:
                    try:
                        sb.table("service_jobs").insert([item]).execute()
                        services_imported += 1
                    except Exception as e2:
                        import_errors += 1
            
            if (i // BATCH_SIZE + 1) % 10 == 0:
                print(f"  ... imported {services_imported} records")
    
    except Exception as e:
        print(f"  ✗ Service import error: {str(e)[:60]}")
    
    print(f"  ✓ Imported {services_imported} service records")
    
    # Print summary
    print("\n" + "="*70)
    print("IMPORT SUMMARY")
    print("="*70)
    print(f"Deleted service_jobs rows:  {deleted_count}")
    print(f"Clients created:            {clients_created}")
    print(f"Clients updated:            {clients_updated}")
    print(f"Service jobs imported:      {services_imported}")
    print(f"Rows skipped:               {skipped_rows}")
    print(f"Parse notes:                {parse_errors}")
    print(f"Total errors:               {import_errors}")
    print("="*70)
    
    return {
        "deleted": deleted_count,
        "clients_created": clients_created,
        "clients_updated": clients_updated,
        "services_imported": services_imported,
        "rows_skipped": skipped_rows,
        "parse_notes": parse_errors,
        "errors": import_errors,
    }



if __name__ == "__main__":
    result = import_services()
    sys.exit(0 if result["errors"] == 0 else 1)
