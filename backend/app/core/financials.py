import re
from datetime import date, datetime
from math import isfinite
from typing import Optional


_CURRENCY_CLEAN_RE = re.compile(r"[^0-9.\-]")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})")


def to_number(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        num = float(value)
        return num if isfinite(num) else 0.0

    text = str(value).strip()
    if not text:
        return 0.0

    cleaned = _CURRENCY_CLEAN_RE.sub("", text.replace(",", ""))
    if cleaned in {"", "-", ".", "-."}:
        return 0.0
    try:
        num = float(cleaned)
        return num if isfinite(num) else 0.0
    except Exception:
        return 0.0


def compute_outstanding(total_amount, amount_paid) -> float:
    total = to_number(total_amount)
    paid = to_number(amount_paid)
    return max(0.0, total - paid)


def compute_payment_status(total_amount, amount_paid) -> str:
    total = to_number(total_amount)
    paid = to_number(amount_paid)
    raw_outstanding = total - paid
    if raw_outstanding <= 0:
        return "PAID"
    if paid > 0:
        return "PART PAYMENT"
    return "UNPAID"


def normalize_text(value) -> str:
    return str(value or "").strip()


def is_valid_service_record(row: dict) -> bool:
    service_name = normalize_text(row.get("service_name"))
    description = normalize_text(row.get("description"))
    amount_charged = to_number(row.get("amount_charged"))
    paid_amount = to_number(row.get("paid_amount"))
    return bool(service_name or description or amount_charged != 0 or paid_amount != 0)


def month_key(value) -> Optional[str]:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m")
    if isinstance(value, date):
        return value.strftime("%Y-%m")
    text = normalize_text(value)
    if not text:
        return None
    m = _MONTH_RE.search(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None
