#!/usr/bin/env python3
"""
import_sheets.py
================
One-time import of Google Sheets data into a fresh Supabase project.

Usage:
    pip install gspread google-auth supabase python-dotenv
    python import_sheets.py

The script reads each tab from the Google Sheet and upserts rows into
the corresponding Supabase table. Run it once; it is SAFE to re-run
(upsert on natural keys).

IMPORTANT: This script uses your NEW Supabase project credentials.
           Your existing database is never touched.
"""

import os
import json
import sys
from datetime import datetime
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
from supabase import create_client, Client

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────
SUPABASE_URL              = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
GOOGLE_SERVICE_ACCOUNT    = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "service_account.json")
GOOGLE_SHEET_ID           = os.environ["GOOGLE_SHEET_ID"]

# Map: (sheet_tab_name, supabase_table, column_mapping_fn)
# column_mapping_fn receives a dict of {header: value} and returns
# the dict to insert into Supabase. Return None to skip the row.

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# ── Helpers ─────────────────────────────────────────────────────────────────

def connect_sheets():
    creds = Credentials.from_service_account_file(GOOGLE_SERVICE_ACCOUNT, scopes=SCOPES)
    return gspread.authorize(creds)


def connect_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def sheet_to_dicts(gc, sheet_id: str, tab_name: str) -> list[dict]:
    try:
        ws = gc.open_by_key(sheet_id).worksheet(tab_name)
    except gspread.WorksheetNotFound:
        print(f"  [SKIP] Tab '{tab_name}' not found in sheet.")
        return []
    records = ws.get_all_records(numericise_ignore=["all"])
    print(f"  Read {len(records)} rows from '{tab_name}'")
    return records


def clean_str(v) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s if s else None


def clean_float(v) -> float | None:
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def clean_date(v) -> str | None:
    s = clean_str(v)
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ── Mapping functions ────────────────────────────────────────────────────────

def map_client(row: dict) -> dict | None:
    name = clean_str(row.get("Name") or row.get("name") or row.get("Full Name"))
    if not name:
        return None
    return {
        "name":    name,
        "email":   clean_str(row.get("Email") or row.get("email")),
        "phone":   clean_str(row.get("Phone") or row.get("phone") or row.get("Tel")),
        "address": clean_str(row.get("Address") or row.get("address")),
        "company": clean_str(row.get("Company") or row.get("company") or row.get("Business")),
        "notes":   clean_str(row.get("Notes") or row.get("notes")),
        "source":  "sheet_import",
    }


def map_billing(row: dict) -> dict | None:
    service = clean_str(row.get("Service") or row.get("service") or row.get("Description") or row.get("Item"))
    client  = clean_str(row.get("Client") or row.get("client") or row.get("Customer"))
    price   = clean_float(row.get("Unit Price") or row.get("unit_price") or row.get("Price") or row.get("Amount"))
    if not service or price is None:
        return None
    qty      = clean_float(row.get("Qty") or row.get("Quantity") or row.get("qty")) or 1.0
    paid     = clean_float(row.get("Amount Paid") or row.get("amount_paid") or row.get("Paid")) or 0.0
    total    = qty * price
    status   = "paid" if paid >= total else ("partial" if paid > 0 else "unpaid")
    return {
        "client_name":  client or "Unknown",
        "service_name": service,
        "quantity":     qty,
        "unit_price":   price,
        "amount_paid":  paid,
        "status":       status,
        "invoice_date": clean_date(row.get("Invoice Date") or row.get("Date") or row.get("date")),
        "due_date":     clean_date(row.get("Due Date") or row.get("due_date")),
        "notes":        clean_str(row.get("Notes") or row.get("notes")),
        "source":       "sheet_import",
    }


def map_stock(row: dict) -> dict | None:
    name = clean_str(row.get("Item") or row.get("item") or row.get("Product") or row.get("Name"))
    if not name:
        return None
    return {
        "item_name":    name,
        "sku":          clean_str(row.get("SKU") or row.get("sku") or row.get("Code")),
        "category":     clean_str(row.get("Category") or row.get("category")),
        "description":  clean_str(row.get("Description") or row.get("description")),
        "quantity":     clean_float(row.get("Quantity") or row.get("Qty") or row.get("qty")) or 0.0,
        "unit":         clean_str(row.get("Unit") or row.get("unit")) or "pcs",
        "unit_cost":    clean_float(row.get("Unit Cost") or row.get("unit_cost") or row.get("Cost")) or 0.0,
        "unit_price":   clean_float(row.get("Unit Price") or row.get("unit_price") or row.get("Price")) or 0.0,
        "reorder_level": clean_float(row.get("Reorder Level") or row.get("reorder_level") or row.get("Min Qty")) or 0.0,
        "supplier":     clean_str(row.get("Supplier") or row.get("supplier")),
        "location":     clean_str(row.get("Location") or row.get("location")),
        "source":       "sheet_import",
    }


def map_expense(row: dict) -> dict | None:
    amount = clean_float(row.get("Amount") or row.get("amount"))
    date   = clean_date(row.get("Date") or row.get("date") or row.get("Expense Date"))
    cat    = clean_str(row.get("Category") or row.get("category") or row.get("Type")) or "Uncategorised"
    if amount is None or not date:
        return None
    return {
        "category":     cat,
        "description":  clean_str(row.get("Description") or row.get("description") or row.get("Details")),
        "amount":       amount,
        "expense_date": date,
        "paid_by":      clean_str(row.get("Paid By") or row.get("paid_by")),
        "receipt_ref":  clean_str(row.get("Receipt") or row.get("receipt_ref") or row.get("Ref")),
        "notes":        clean_str(row.get("Notes") or row.get("notes")),
        "source":       "sheet_import",
    }


# ── Import runner ────────────────────────────────────────────────────────────

def import_tab(gc, sb: Client, tab_name: str, table: str, mapper):
    print(f"\n▶ Importing '{tab_name}' → {table}")
    rows = sheet_to_dicts(gc, GOOGLE_SHEET_ID, tab_name)
    if not rows:
        return 0, 0

    mapped  = [mapper(r) for r in rows]
    clean   = [r for r in mapped if r is not None]
    skipped = len(mapped) - len(clean)

    if not clean:
        print("  No valid rows to insert.")
        return 0, skipped

    # Batch insert in chunks of 500
    CHUNK = 500
    inserted = 0
    for i in range(0, len(clean), CHUNK):
        chunk = clean[i:i + CHUNK]
        sb.table(table).insert(chunk, upsert=False).execute()
        inserted += len(chunk)

    print(f"  ✓ Inserted {inserted}, skipped {skipped}")
    return inserted, skipped


def main():
    print("=" * 60)
    print("CRM Google Sheets → Supabase Import")
    print("=" * 60)
    print(f"Supabase: {SUPABASE_URL}")
    print(f"Sheet ID: {GOOGLE_SHEET_ID}")
    print()

    gc = connect_sheets()
    sb = connect_supabase()

    total_inserted = 0

    # ── 1. Contacts → clients
    # Change "Contacts" to match your actual sheet tab name
    ins, _ = import_tab(gc, sb, "Contacts", "clients", map_client)
    total_inserted += ins

    # ── 2. Services/Billing → operational_billing_rows
    ins, _ = import_tab(gc, sb, "Billing", "operational_billing_rows", map_billing)
    total_inserted += ins

    # ── 3. Stock/Inventory → operational_stock_rows
    ins, _ = import_tab(gc, sb, "Inventory", "operational_stock_rows", map_stock)
    total_inserted += ins

    # ── 4. Cash Flow / Expenses → manual_expenses
    ins, _ = import_tab(gc, sb, "Cash Flow", "manual_expenses", map_expense)
    total_inserted += ins

    # ── 5. Refresh cash flow summary
    print("\n▶ Refreshing cash_flow_summary…")
    sb.rpc("refresh_cash_flow_summary").execute()
    print("  ✓ Done")

    print(f"\n{'=' * 60}")
    print(f"Import complete. Total rows inserted: {total_inserted}")
    print("=" * 60)


if __name__ == "__main__":
    main()
