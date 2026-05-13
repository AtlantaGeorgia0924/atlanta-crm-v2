#!/usr/bin/env python3
"""Rebuild inventory_items from data/STOCK-3.xlsx as source of truth."""

import os
import sys
import uuid
import time
from datetime import datetime, timezone

import openpyxl
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
from app.db.supabase_client import get_supabase  # noqa: E402


BATCH_SIZE = 100


def rexec(fn, retries=5):
    for i in range(retries):
        try:
            return fn()
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(0.6 * (i + 1))


def parse_float(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return 0.0
    s = s.replace('NGN', '').replace('N', '').replace(',', '').replace('₦', '').strip()
    try:
        return float(s)
    except Exception:
        return 0.0


def normalize_status(product_status: str, sold_date_raw) -> str:
    s = (product_status or '').strip().upper()
    if 'PARTIAL' in s:
        return 'PARTIAL'
    if 'UNPAID' in s or 'PENDING' in s or 'AVAILABLE' in s:
        return 'UNPAID'
    if sold_date_raw:
        return 'PAID'
    if 'SOLD' in s or 'PAID' in s:
        return 'PAID'
    return 'UNPAID'


def to_iso_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    s = str(value).strip()
    if not s:
        return None
    # Try known sheet formats; if none match, return None to avoid DB cast errors.
    for fmt in ("%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%B, %d, %Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).isoformat()
        except Exception:
            pass
    return None


def main():
    root = os.path.join(os.path.dirname(__file__), '..')
    load_dotenv(os.path.join(root, 'backend', '.env'))

    file_path = os.path.join(root, 'data', 'STOCK-3.xlsx')
    if not os.path.exists(file_path):
        print(f"ERROR: Missing Excel file: {file_path}")
        return 1

    wb = openpyxl.load_workbook(file_path, data_only=False)
    ws = wb['Sheet1']

    # Real header row is row 3 in this workbook.
    headers = {str(c.value): i for i, c in enumerate(ws[3], start=1) if c.value}

    sb = get_supabase()

    # 1) Delete existing inventory rows.
    before = rexec(lambda: sb.table('inventory_items').select('id', count='exact').execute())
    existing_rows = before.data or []
    rows_deleted = int(before.count or 0)

    for row in existing_rows:
        rexec(lambda rid=row['id']: sb.table('inventory_items').delete().eq('id', rid).execute())

    # Safety pass: ensure table is empty before reimport.
    remaining = rexec(lambda: sb.table('inventory_items').select('id', count='exact').execute())
    remaining_rows = remaining.data or []
    for row in remaining_rows:
        rexec(lambda rid=row['id']: sb.table('inventory_items').delete().eq('id', rid).execute())

    # 2) Parse source rows.
    rows_to_insert = []
    rows_skipped = 0
    errors = 0

    now_iso = datetime.now(timezone.utc).isoformat()

    def get_cell(cells, key):
        idx = headers.get(key)
        if not idx or idx > len(cells):
            return None
        cell = cells[idx - 1]
        return cell.value if hasattr(cell, 'value') else cell

    for r in range(4, ws.max_row + 1):
        try:
            cells = list(ws[r])

            description = str(get_cell(cells, 'DESCRIPTION') or '').strip()
            device = str(get_cell(cells, 'DEVICE') or '').strip()
            color = str(get_cell(cells, 'COLOUR') or '').strip()
            storage = str(get_cell(cells, 'STORAGE') or '').strip()
            imei = str(get_cell(cells, 'IMEI') or '').strip()
            record_id = str(get_cell(cells, 'RECORD_ID') or '').strip()
            seller = str(get_cell(cells, 'NAME OF SELLER') or '').strip()
            product_status = str(get_cell(cells, 'PRODUCT STATUS') or '').strip()
            sold_date_raw = get_cell(cells, 'AVAILABILITY/DATE SOLD')
            expense_amount = parse_float(get_cell(cells, 'EXPENSE AMOUNT'))
            expense_desc = str(get_cell(cells, 'EXPENSE DESCRIPTION') or '').strip()
            cost_price = parse_float(get_cell(cells, 'COST PRICE'))

            # Valid stock rows in this workbook are rows with PRODUCT STATUS and DESCRIPTION/RECORD_ID.
            if not product_status or (not description and not record_id):
                rows_skipped += 1
                continue

            # Valid row criteria: has a product identifier/description.
            item_name = description or f"Stock Item {record_id or r}"
            sku = imei or record_id or None
            category = device or None
            quantity = 1.0

            # STOCK-3 has no explicit selling_price column; fallback to cost_price.
            selling_price = cost_price
            payment_status = normalize_status(product_status, sold_date_raw)
            paid_date = to_iso_date(sold_date_raw)

            product_profit = selling_price - cost_price - expense_amount

            # Preserve auxiliary fields in description text for supplier/expense display logic.
            extra_parts = []
            if color:
                extra_parts.append(f"Color: {color}")
            if storage:
                extra_parts.append(f"Storage: {storage}")
            if seller:
                extra_parts.append(f"Supplier: {seller}")
            if expense_desc:
                extra_parts.append(f"Expense Description: {expense_desc}")
            full_description = item_name
            if extra_parts:
                full_description = f"{item_name} | " + " | ".join(extra_parts)

            rows_to_insert.append({
                'id': str(uuid.uuid4()),
                'legacy_source_id': record_id or None,
                'item_name': item_name,
                'sku': sku,
                'category': category,
                'description': full_description,
                'quantity': quantity,
                'unit': 'pcs',
                'cost_price': cost_price,
                'selling_price': selling_price,
                'expense_amount': expense_amount,
                'product_profit': product_profit,
                'payment_status': payment_status,
                'paid_date': paid_date,
                'is_return': False,
                'source_created_at': now_iso,
                'source_updated_at': now_iso,
                'created_at': now_iso,
                'updated_at': now_iso,
            })
        except Exception:
            errors += 1

    # 3) Insert parsed rows.
    rows_imported = 0
    insert_errors = 0
    for i in range(0, len(rows_to_insert), BATCH_SIZE):
        chunk = rows_to_insert[i:i + BATCH_SIZE]
        try:
            rexec(lambda chunk=chunk: sb.table('inventory_items').insert(chunk).execute())
            rows_imported += len(chunk)
        except Exception:
            # fallback to per-row inserts to isolate bad records
            for row in chunk:
                try:
                    rexec(lambda row=row: sb.table('inventory_items').insert([row]).execute())
                    rows_imported += 1
                except Exception:
                    insert_errors += 1

    final_count = int(rexec(lambda: sb.table('inventory_items').select('id', count='exact').execute()).count or 0)
    total_errors = errors + insert_errors

    print('======================================================================')
    print('INVENTORY IMPORT SUMMARY')
    print('======================================================================')
    print(f'Rows deleted:        {rows_deleted}')
    print(f'Rows imported:       {rows_imported}')
    print(f'Rows skipped:        {rows_skipped}')
    print(f'Errors encountered:  {total_errors}')
    print(f'Final row count:     {final_count}')
    print('======================================================================')

    return 0 if total_errors == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
