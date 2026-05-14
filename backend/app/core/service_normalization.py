"""Normalize service_jobs data: payment status, amounts, dates, and return flags."""
from datetime import datetime
from typing import Dict
from app.core.financials import to_number


def normalize_service_jobs_data(sb) -> Dict[str, int]:
    """
    Normalize all service_jobs records in the database:
    - Trim and uppercase payment_status, convert PARTIAL → PART PAYMENT
    - For PAID: fill paid_amount if missing, fill paid_at if missing
    - For UNPAID: force paid_amount = 0
    - For PART PAYMENT: fill paid_amount = 0 if null
    - For RETURNED: mark is_return=true, paid_amount=0
    - Clamp overpayments: paid_amount cannot exceed amount_charged

    Returns dict with counts of fixed rows:
    - rows_fixed_payment_status
    - rows_fixed_paid_amount
    - rows_fixed_paid_at
    - rows_marked_returned
    - rows_clamped_overpayment
    """
    counts = {
        "rows_fixed_payment_status": 0,
        "rows_fixed_paid_amount": 0,
        "rows_fixed_paid_at": 0,
        "rows_marked_returned": 0,
        "rows_clamped_overpayment": 0,
    }

    # Fetch all service_jobs in batches
    rows: list[dict] = []
    start = 0
    batch_size = 1000
    while True:
        response = (
            sb.table("service_jobs")
            .select(
                "id,payment_status,amount_charged,paid_amount,paid_at,is_return,updated_at,created_at"
            )
            .range(start, start + batch_size - 1)
            .execute()
        )
        batch = response.data or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < batch_size:
            break
        start += batch_size

    # Process updates and collect only rows with actual changes
    updates_to_apply: list[dict] = []
    
    for row in rows:
        row_id = row.get("id")
        original_status = str(row.get("payment_status") or "").strip()
        payment_status = original_status.upper()
        if payment_status == "PARTIAL":
            payment_status = "PART PAYMENT"

        if payment_status != original_status:
            counts["rows_fixed_payment_status"] += 1

        amount_charged = to_number(row.get("amount_charged"))
        paid_amount = to_number(row.get("paid_amount"))
        paid_at = row.get("paid_at")
        is_return = row.get("is_return", False)
        updated_at = row.get("updated_at")
        created_at = row.get("created_at")

        # Track if this row needs any updates
        has_changes = payment_status != original_status
        
        # Normalize RETURNED status
        if payment_status == "RETURNED":
            if not is_return:
                is_return = True
                has_changes = True
                counts["rows_marked_returned"] += 1
            if paid_amount != 0.0:
                paid_amount = 0.0
                has_changes = True
                counts["rows_fixed_paid_amount"] += 1
        else:
            # Non-returned rows must always be marked as not returned
            if is_return:
                is_return = False
                has_changes = True

        # PAID row normalization
        if payment_status == "PAID":
            # Fill paid_amount if missing or zero
            if paid_amount <= 0:
                paid_amount = amount_charged
                has_changes = True
                counts["rows_fixed_paid_amount"] += 1

            # Fill paid_at if missing
            if not paid_at:
                paid_at = updated_at or created_at
                if paid_at:
                    has_changes = True
                    counts["rows_fixed_paid_at"] += 1

        # UNPAID row: force paid_amount = 0
        elif payment_status == "UNPAID":
            if paid_amount > 0:
                paid_amount = 0.0
                has_changes = True
                counts["rows_fixed_paid_amount"] += 1

        # PART PAYMENT: fill paid_amount with 0 if null
        elif payment_status == "PART PAYMENT":
            if paid_amount <= 0:
                paid_amount = 0.0
                has_changes = True
                counts["rows_fixed_paid_amount"] += 1

        # Clamp overpayments (skip RETURNED rows which are always 0)
        if payment_status != "RETURNED" and paid_amount > amount_charged:
            paid_amount = amount_charged
            has_changes = True
            counts["rows_clamped_overpayment"] += 1

        # Only add to updates if something changed
        if has_changes:
            updates_to_apply.append({
                "id": row_id,
                "payment_status": payment_status,
                "paid_amount": paid_amount,
                "paid_at": paid_at,
                "is_return": is_return,
            })

    # Apply updates using targeted update statements (not upsert to avoid required field constraints)
    if updates_to_apply:
        # Group updates by type for batch operations
        for update_obj in updates_to_apply:
            row_id = update_obj.get("id")
            # Build update payload with only the fields we're changing
            update_payload = {
                "payment_status": update_obj["payment_status"],
                "paid_amount": update_obj["paid_amount"],
            }
            # Only add optional fields if they're being set
            if update_obj.get("paid_at") is not None:
                update_payload["paid_at"] = update_obj["paid_at"]
            update_payload["is_return"] = update_obj["is_return"]
            
            # Execute targeted update for this row
            sb.table("service_jobs").update(update_payload).eq("id", row_id).execute()

    return counts

    return counts
