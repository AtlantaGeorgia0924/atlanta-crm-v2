"""
Centralized financial event bus.

Every cash-flow mutation (expense create/reverse, allowance withdrawal,
service payment, sync import, manual adjustment) calls:

    emit_financial_event(
        event_type="expense_created",
        record_id=expense_id,
        performed_by=user_id,
        amount=500.0,
    )

This single call:
    1. Writes an audit log row to cashflow_audit_log.
    2. Emits a structured JSON log line for observability.
    3. Enqueues a background metrics-refresh job (if RQ is available).

Adding new listeners later only requires editing _LISTENERS below –
no mutation endpoint needs to change.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app.core.cache import invalidate_statement_cache, cache_delete
from app.core.logging_config import log_event

logger = logging.getLogger(__name__)

# Cache keys for dashboard and debtor summaries (extend as needed)
_DASHBOARD_CACHE_KEY = "dashboard:summary"
_DEBTORS_CACHE_KEY = "debtors:summary"


# ── Invalidation helper ───────────────────────────────────────────────────────

def invalidate_financial_caches(reason: str, triggered_by: str = "system") -> None:
    """
    Invalidate all financial caches in one call.

    Called by every financial mutation endpoint.  New cache keys can be added
    here without touching any endpoint.
    """
    invalidate_statement_cache()
    cache_delete(_DASHBOARD_CACHE_KEY)
    cache_delete(_DEBTORS_CACHE_KEY)

    log_event(
        "financial_cache_invalidated",
        reason=reason,
        triggered_by=triggered_by,
        ts=datetime.now(timezone.utc).isoformat(),
    )


# ── Audit log writer ──────────────────────────────────────────────────────────

def _write_audit_log(
    sb,
    action: str,
    amount: float,
    performed_by: str,
    related_record_id: Optional[str],
    detail: Optional[dict] = None,
) -> None:
    try:
        sb.table("cashflow_audit_log").insert(
            {
                "action": action,
                "amount": amount,
                "performed_by": performed_by,
                "related_record_id": related_record_id,
                "detail": detail or {},
                "created_at": datetime.utcnow().isoformat(),
            }
        ).execute()
    except Exception as exc:
        logger.warning("audit_log_write_failed action=%s error=%s", action, exc)


# ── Background job enqueue ────────────────────────────────────────────────────

def _enqueue_metrics_refresh(triggered_by: str = "system") -> None:
    """
    Enqueue a background financial metrics rebuild via RQ.
    Silently skips if Redis / RQ are unavailable.
    """
    try:
        import redis  # type: ignore
        from rq import Queue  # type: ignore
        import os
        from app.core.workers import rebuild_financial_metrics

        redis_url = os.getenv("REDIS_URL", "")
        if not redis_url:
            return
        r = redis.from_url(redis_url, socket_connect_timeout=2)
        q = Queue("financial", connection=r)
        q.enqueue(
            rebuild_financial_metrics,
            triggered_by,
            job_timeout=120,
            retry=3,
        )
    except Exception as exc:
        logger.warning("rq_enqueue_failed error=%s", exc)


# ── Listener registry ─────────────────────────────────────────────────────────

# Each listener is (priority, callable).  Lower priority runs first.
_LISTENERS: list[tuple[int, Callable]] = []


def register_listener(priority: int, fn: Callable) -> None:
    _LISTENERS.append((priority, fn))
    _LISTENERS.sort(key=lambda t: t[0])


# ── Main dispatcher ───────────────────────────────────────────────────────────

def emit_financial_event(
    sb,
    event_type: str,
    *,
    performed_by: str,
    record_id: Optional[str] = None,
    amount: float = 0.0,
    detail: Optional[dict] = None,
) -> None:
    """
    Emit a financial mutation event.

    Parameters
    ----------
    sb          : Supabase client (for audit log writes)
    event_type  : e.g. "expense_created", "expense_reversed", "allowance_withdrawn"
    performed_by: User id from JWT
    record_id   : Related DB row id (expense, withdrawal …)
    amount      : Financial amount involved
    detail      : Extra context dict stored in audit log
    """
    t0 = time.monotonic()

    # 1. Write audit log
    _write_audit_log(
        sb,
        action=event_type,
        amount=amount,
        performed_by=performed_by,
        related_record_id=record_id,
        detail=detail,
    )

    # 2. Structured event log
    log_event(
        "financial_event",
        event_type=event_type,
        performed_by=performed_by,
        record_id=record_id,
        amount=amount,
        elapsed_ms=round((time.monotonic() - t0) * 1000, 2),
    )

    # 3. Enqueue background metrics refresh
    _enqueue_metrics_refresh(triggered_by=performed_by)

    # 4. Custom listeners
    for _priority, fn in _LISTENERS:
        try:
            fn(event_type=event_type, record_id=record_id, performed_by=performed_by, amount=amount, detail=detail)
        except Exception as exc:
            logger.warning("listener_error fn=%s event=%s error=%s", fn.__name__, event_type, exc)
