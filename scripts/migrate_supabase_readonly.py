#!/usr/bin/env python3
"""
Read-only migration from existing Supabase (source) to new Supabase (destination).

Safety guarantees:
- Source project is read-only: script only performs SELECT operations on source.
- No deletes, no truncates, no drops, no updates on source.
- Destination receives inserts/upserts only.

Report output includes:
- rows_read
- rows_inserted
- rows_updated
- rows_skipped
- errors
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client


load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("migrate_supabase_readonly")


def log_event(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, default=str))


def env_required(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


SOURCE_SUPABASE_URL = env_required("SOURCE_SUPABASE_URL")
SOURCE_SUPABASE_SERVICE_ROLE_KEY = env_required("SOURCE_SUPABASE_SERVICE_ROLE_KEY")
DEST_SUPABASE_URL = env_required("DEST_SUPABASE_URL")
DEST_SUPABASE_SERVICE_ROLE_KEY = env_required("DEST_SUPABASE_SERVICE_ROLE_KEY")
MIGRATION_MODE = os.getenv("MIGRATION_MODE", "upsert").strip().lower()
BATCH_SIZE = int(os.getenv("MIGRATION_BATCH_SIZE", "500"))
RETRIES = int(os.getenv("MIGRATION_RETRIES", "4"))

if MIGRATION_MODE not in {"upsert", "skip_existing"}:
    raise RuntimeError("MIGRATION_MODE must be one of: upsert, skip_existing")


def source_client() -> Client:
    return create_client(SOURCE_SUPABASE_URL, SOURCE_SUPABASE_SERVICE_ROLE_KEY)


def dest_client() -> Client:
    return create_client(DEST_SUPABASE_URL, DEST_SUPABASE_SERVICE_ROLE_KEY)


def parse_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def parse_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    log_event("malformed_date", raw_value=text)
    return None


def normalize_payment_status(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"PAID", "PARTIAL", "PART PAYMENT", "UNPAID", "RETURNED"}:
        if text == "PARTIAL":
            return "PART PAYMENT"
        return text
    if text in {"PAYED"}:
        return "PAID"
    return "UNPAID"


def as_uuid(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return str(uuid.UUID(text))
    except ValueError:
        return None


def as_key(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass
class TablePlan:
    source_table: str
    dest_table: str
    key_field: str
    map_row: Any


class MigrationRunner:
    def __init__(self, source: Client, dest: Client):
        self.source = source
        self.dest = dest

    def _execute_with_retry(self, fn, operation: str, table_name: str):
        last_exc = None
        for attempt in range(RETRIES):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                if attempt == RETRIES - 1:
                    break
                time.sleep(0.5 * (attempt + 1))
                log_event(
                    "retry",
                    operation=operation,
                    table=table_name,
                    attempt=attempt + 1,
                    error=str(exc),
                )
        raise RuntimeError(
            f"Operation failed after retries: {operation} on {table_name}: {last_exc}"
        )

    def _log_sync_error(self, table_name: str, legacy_source_id: Any, operation: str, error_message: str) -> None:
        payload = {
            "table_name": table_name,
            "legacy_source_id": None if legacy_source_id is None else str(legacy_source_id),
            "operation": operation,
            "error_message": str(error_message)[:500],
            "created_at": datetime.utcnow().isoformat(),
        }
        try:
            self.dest.table("sync_errors").insert(payload).execute()
        except Exception as exc:
            log_event(
                "sync_error_log_failed",
                table=table_name,
                operation=operation,
                original_error=error_message,
                logger_error=str(exc),
            )

    def read_all_rows(self, table: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        start = 0
        while True:
            end = start + BATCH_SIZE - 1
            response = self._execute_with_retry(
                lambda: self.source.table(table).select("*").range(start, end).execute(),
                operation="read_source_batch",
                table_name=table,
            )
            chunk = response.data or []
            rows.extend(chunk)
            if len(chunk) < BATCH_SIZE:
                break
            start += BATCH_SIZE
        return rows

    def existing_keys(self, table: str, key_field: str, keys: list[Any]) -> set[Any]:
        if not keys:
            return set()
        found: set[Any] = set()
        for i in range(0, len(keys), BATCH_SIZE):
            sub = keys[i:i + BATCH_SIZE]
            result = self._execute_with_retry(
                lambda sub=sub: self.dest.table(table).select(key_field).in_(key_field, sub).execute(),
                operation="read_destination_keys",
                table_name=table,
            )
            for row in (result.data or []):
                found.add(row.get(key_field))
        return found

    def run_plan(self, plan: TablePlan) -> dict[str, Any]:
        report = {
            "source_table": plan.source_table,
            "destination_table": plan.dest_table,
            "rows_read": 0,
            "rows_inserted": 0,
            "rows_updated": 0,
            "rows_skipped": 0,
            "conflicts": 0,
            "errors": [],
        }

        try:
            source_rows = self.read_all_rows(plan.source_table)
            report["rows_read"] = len(source_rows)

            transformed: list[dict[str, Any]] = []
            seen_source_keys: set[Any] = set()
            for raw in source_rows:
                mapped = plan.map_row(raw)
                if mapped is None:
                    report["rows_skipped"] += 1
                    continue
                if plan.key_field not in mapped or mapped.get(plan.key_field) is None:
                    report["rows_skipped"] += 1
                    continue
                source_key = mapped.get(plan.key_field)
                if source_key in seen_source_keys:
                    report["conflicts"] += 1
                    self._log_sync_error(
                        plan.dest_table,
                        source_key,
                        "source_duplicate_key",
                        f"Duplicate key in source payload for {plan.key_field}",
                    )
                    continue
                seen_source_keys.add(source_key)
                transformed.append(mapped)

            keys = [row[plan.key_field] for row in transformed]
            existing = self.existing_keys(plan.dest_table, plan.key_field, keys)

            if MIGRATION_MODE == "skip_existing":
                to_insert = [row for row in transformed if row[plan.key_field] not in existing]
                report["rows_skipped"] += len(transformed) - len(to_insert)

                for i in range(0, len(to_insert), BATCH_SIZE):
                    batch = to_insert[i:i + BATCH_SIZE]
                    if not batch:
                        continue
                    self._execute_with_retry(
                        lambda batch=batch: self.dest.table(plan.dest_table).insert(batch).execute(),
                        operation="insert_skip_existing",
                        table_name=plan.dest_table,
                    )
                report["rows_inserted"] = len(to_insert)
                return report

            # MIGRATION_MODE=upsert
            rows_insert = [row for row in transformed if row[plan.key_field] not in existing]
            rows_update = [row for row in transformed if row[plan.key_field] in existing]

            for i in range(0, len(transformed), BATCH_SIZE):
                batch = transformed[i:i + BATCH_SIZE]
                if not batch:
                    continue
                self._execute_with_retry(
                    lambda batch=batch: self.dest.table(plan.dest_table).upsert(batch, on_conflict=plan.key_field).execute(),
                    operation="upsert_batch",
                    table_name=plan.dest_table,
                )

            report["rows_inserted"] = len(rows_insert)
            report["rows_updated"] = len(rows_update)
            return report

        except Exception as exc:
            report["errors"].append(str(exc))
            self._log_sync_error(plan.dest_table, None, "run_plan", str(exc))
            return report


def map_auth_user(row: dict[str, Any]) -> dict[str, Any] | None:
    user_id = as_key(row.get("id"))
    if not user_id:
        return None
    return {
        "id": user_id,
        "email": row.get("email"),
        "phone": row.get("phone"),
        "full_name": row.get("full_name") or row.get("name"),
        "role": row.get("role") or "user",
        "is_active": row.get("is_active", True),
        "source_created_at": row.get("created_at"),
        "source_updated_at": row.get("updated_at"),
    }


def map_inventory(row: dict[str, Any]) -> dict[str, Any] | None:
    legacy_id = as_key(row.get("id"))
    item_name = row.get("item_name") or row.get("name") or row.get("product_name") or row.get("title")
    if not legacy_id:
        return None
    if not item_name:
        item_name = f"Legacy Item {legacy_id}"

    selling_price = parse_float(row.get("unit_price") or row.get("selling_price"), 0.0)
    cost_price = parse_float(row.get("unit_cost") or row.get("cost_price"), 0.0)
    expense_amount = parse_float(row.get("expense_amount"), 0.0)
    product_profit = selling_price - cost_price - expense_amount

    return {
        "legacy_source_id": legacy_id,
        "item_name": item_name,
        "sku": row.get("sku"),
        "category": row.get("category"),
        "description": row.get("description"),
        "quantity": parse_float(row.get("quantity"), 0.0),
        "unit": row.get("unit") or "pcs",
        "cost_price": cost_price,
        "selling_price": selling_price,
        "expense_amount": expense_amount,
        "product_profit": row.get("calculated_profit") if row.get("calculated_profit") is not None else product_profit,
        "payment_status": normalize_payment_status(row.get("payment_status")),
        "paid_date": parse_date(row.get("paid_date")),
        "is_return": bool(row.get("is_return", False)),
        "source_created_at": row.get("created_at"),
        "source_updated_at": row.get("updated_at"),
    }


def map_service_job(row: dict[str, Any]) -> dict[str, Any] | None:
    legacy_id = as_key(row.get("id"))
    if not legacy_id:
        return None

    quantity = parse_float(row.get("quantity"), 1.0)
    unit_price = parse_float(row.get("unit_price"), 0.0)
    amount_charged = parse_float(row.get("amount_charged"), quantity * unit_price)
    expense_amount = parse_float(row.get("expense_amount"), 0.0)
    calculated_profit = amount_charged - expense_amount

    raw_status = row.get("payment_status")
    if raw_status is None:
        raw_status = row.get("status")
    payment_status = normalize_payment_status(raw_status)

    paid_amount = parse_float(row.get("amount_paid"), 0.0)
    paid_date = parse_date(row.get("paid_date") or row.get("payment_date"))

    is_return = bool(row.get("is_return", False))
    if is_return or payment_status == "RETURNED":
        is_return = True
        payment_status = "RETURNED"
        paid_amount = 0.0

    if payment_status == "PAID" and paid_amount <= 0:
        paid_amount = amount_charged
    if payment_status in {"UNPAID", "RETURNED"}:
        paid_amount = 0.0

    realized_revenue = paid_amount if payment_status in {"PAID", "PART PAYMENT"} else 0.0
    calculated_profit = realized_revenue - expense_amount

    return {
        "legacy_source_id": legacy_id,
        "client_id": as_key(row.get("client_id")),
        "client_name": row.get("client_name"),
        "service_name": row.get("service_name") or row.get("title") or "Unknown Service",
        "description": row.get("description"),
        "quantity": quantity,
        "amount_charged": amount_charged,
        "expense_amount": expense_amount,
        "calculated_profit": row.get("calculated_profit") if row.get("calculated_profit") is not None else calculated_profit,
        "payment_status": payment_status,
        "paid_amount": paid_amount,
        "paid_date": paid_date,
        "service_date": parse_date(row.get("service_date") or row.get("invoice_date")),
        "due_date": parse_date(row.get("due_date")),
        "is_return": is_return,
        "return_reference": row.get("return_reference"),
        "notes": row.get("notes"),
        "source_created_at": row.get("created_at"),
        "source_updated_at": row.get("updated_at"),
    }


def map_client(row: dict[str, Any]) -> dict[str, Any] | None:
    client_id = as_key(row.get("id"))
    if not client_id:
        return None
    phone = row.get("phone")
    if phone is not None:
        phone = re.sub(r"\D+", "", str(phone)) or None

    return {
        "id": client_id,
        "name": row.get("name") or "Unknown",
        "email": row.get("email"),
        "phone": phone,
        "address": row.get("address"),
        "company": row.get("company"),
        "notes": row.get("notes"),
        "source": row.get("source") or "legacy_migration",
        "is_active": row.get("is_active", True),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def map_manual_expense(row: dict[str, Any]) -> dict[str, Any] | None:
    expense_id = as_key(row.get("id"))
    if not expense_id:
        return None
    return {
        payment_status = normalize_payment_status(row.get("payment_status"))
        paid_amount = parse_float(row.get("paid_amount"), 0.0)
        if payment_status in {"UNPAID", "RETURNED"}:
            realized_revenue = 0.0
        elif payment_status == "PART PAYMENT":
            realized_revenue = paid_amount
        else:
            realized_revenue = selling_price
        product_profit = realized_revenue - cost_price - expense_amount
        "category": row.get("category") or "Uncategorised",
        "description": row.get("description"),
        "amount": parse_float(row.get("amount"), 0.0),
        "expense_date": parse_date(row.get("expense_date") or row.get("date")),
        "paid_by": row.get("paid_by"),
        "receipt_ref": row.get("receipt_ref"),
        "notes": row.get("notes"),
        "source": row.get("source") or "legacy_migration",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def map_allowance_withdrawal(row: dict[str, Any]) -> dict[str, Any] | None:
    allowance_id = as_key(row.get("id"))
    if not allowance_id:
        return None
    return {
        "id": allowance_id,
        "withdrawn_by": row.get("withdrawn_by") or row.get("staff_name"),
        "amount": parse_float(row.get("amount"), 0.0),
        "withdrawal_date": parse_date(row.get("withdrawal_date") or row.get("allowance_date")),
        "notes": row.get("notes"),
        "source_created_at": row.get("created_at"),
        "source_updated_at": row.get("updated_at"),
    }


def map_cashflow_summary(row: dict[str, Any]) -> dict[str, Any] | None:
    source_id = as_key(row.get("id"))
    if not source_id:
        return None

    weekly_paid_profits = parse_float(row.get("weekly_paid_profits"), 0.0)
    weekly_expenses = parse_float(row.get("weekly_expenses"), 0.0)
    weekly_net_profit = weekly_paid_profits - weekly_expenses
    next_week_allowance = weekly_net_profit * 0.25
    monthly_net_profit = parse_float(row.get("monthly_net_profit"), 0.0)
    allowances_withdrawn = parse_float(row.get("allowances_withdrawn"), 0.0)
    monthly_net_profit_left = monthly_net_profit - allowances_withdrawn

    return {
        "id": source_id,
        "period_key": row.get("period_key") or row.get("period_month") or row.get("week_label"),
        "weekly_paid_profits": row.get("weekly_paid_profits") if row.get("weekly_paid_profits") is not None else weekly_paid_profits,
        "weekly_expenses": row.get("weekly_expenses") if row.get("weekly_expenses") is not None else weekly_expenses,
        "weekly_net_profit": row.get("weekly_net_profit") if row.get("weekly_net_profit") is not None else weekly_net_profit,
        "next_week_allowance": row.get("next_week_allowance") if row.get("next_week_allowance") is not None else next_week_allowance,
        "monthly_net_profit": row.get("monthly_net_profit") if row.get("monthly_net_profit") is not None else monthly_net_profit,
        "allowances_withdrawn": row.get("allowances_withdrawn") if row.get("allowances_withdrawn") is not None else allowances_withdrawn,
        "monthly_net_profit_left": row.get("monthly_net_profit_left") if row.get("monthly_net_profit_left") is not None else monthly_net_profit_left,
        "source_created_at": row.get("created_at"),
        "source_updated_at": row.get("updated_at"),
    }


def map_app_setting(row: dict[str, Any]) -> dict[str, Any] | None:
    key = row.get("key")
    if not key:
        return None
    value = row.get("value")
    if isinstance(value, (dict, list)):
        value = json.dumps(value)
    return {
        "key": str(key),
        "value": None if value is None else str(value),
        "description": row.get("description"),
        "updated_at": row.get("updated_at") or row.get("created_at"),
    }


def print_report(report: list[dict[str, Any]]) -> None:
    total_read = sum(item["rows_read"] for item in report)
    total_inserted = sum(item["rows_inserted"] for item in report)
    total_updated = sum(item["rows_updated"] for item in report)
    total_skipped = sum(item["rows_skipped"] for item in report)
    total_errors = sum(len(item["errors"]) for item in report)

    print("\n=== Migration Report ===")
    for item in report:
        print(
            f"- {item['source_table']} -> {item['destination_table']}: "
            f"read={item['rows_read']} inserted={item['rows_inserted']} "
            f"updated={item['rows_updated']} skipped={item['rows_skipped']} "
            f"errors={len(item['errors'])}"
        )
        for error in item["errors"]:
            print(f"    error: {error}")

    summary = {
        "rows_read": total_read,
        "rows_inserted": total_inserted,
        "rows_updated": total_updated,
        "rows_skipped": total_skipped,
        "errors": total_errors,
    }

                destination_clients_by_phone: dict[str, str] = {}
                if plan.dest_table == "clients":
                    try:
                        dest_clients = self._execute_with_retry(
                            lambda: self.dest.table("clients").select("id,phone").execute(),
                            operation="read_destination_clients",
                            table_name="clients",
                        ).data or []
                        for client in dest_clients:
                            normalized_phone = re.sub(r"\D+", "", str(client.get("phone") or ""))
                            if normalized_phone:
                                destination_clients_by_phone[normalized_phone] = str(client.get("id"))
                    except Exception as exc:
                        log_event("destination_client_lookup_failed", error=str(exc))

    print("\n=== Totals ===")
    print(json.dumps(summary, indent=2))


def main() -> None:

                    if plan.dest_table == "clients":
                        normalized_phone = re.sub(r"\D+", "", str(mapped.get("phone") or ""))
                        if normalized_phone and normalized_phone in destination_clients_by_phone:
                            mapped["id"] = destination_clients_by_phone[normalized_phone]
                        elif normalized_phone:
                            destination_clients_by_phone[normalized_phone] = str(mapped.get("id"))

    log_event("migration_start", mode=MIGRATION_MODE, batch_size=BATCH_SIZE)

    src = source_client()
    dst = dest_client()
    runner = MigrationRunner(src, dst)

    plans: list[TablePlan] = [
        TablePlan("auth_users", "users", "id", map_auth_user),
        TablePlan("operational_stock_rows", "inventory_items", "legacy_source_id", map_inventory),
        TablePlan("operational_billing_rows", "service_jobs", "legacy_source_id", map_service_job),
        TablePlan("clients", "clients", "id", map_client),
        TablePlan("manual_expenses", "manual_expenses", "id", map_manual_expense),
        TablePlan("allowance_withdrawals", "allowance_withdrawals", "id", map_allowance_withdrawal),
        TablePlan("cashflow_summary", "cashflow_summary", "id", map_cashflow_summary),
        TablePlan("app_config", "app_settings", "key", map_app_setting),
    ]

    report: list[dict[str, Any]] = []
    for plan in plans:
        log_event("table_start", source=plan.source_table, destination=plan.dest_table)
        table_report = runner.run_plan(plan)
        report.append(table_report)
        log_event("table_end", **table_report)

    print_report(report)


if __name__ == "__main__":
    main()
