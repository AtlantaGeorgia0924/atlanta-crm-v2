"""
RQ background workers for heavy financial operations.

Workers run in a separate process:
    rq worker financial --url $REDIS_URL

Jobs
----
- rebuild_financial_metrics   : recompute and persist all dashboard/financial metrics
- archive_old_audit_logs      : move >12-month audit rows to cashflow_audit_archive
- run_integrity_check         : run financial consistency validator and log issues
"""
import logging
import os

logger = logging.getLogger(__name__)


def rebuild_financial_metrics(triggered_by: str = "background") -> dict:
    """
    Recompute and persist financial metrics from Supabase.

    This is the heavy computation moved off the request thread.
    Called by emit_financial_event after every mutation.
    """
    from app.db.supabase_client import get_supabase
    from app.core.metrics_refresh import recompute_and_persist_metrics
    from app.core.cache import set_statement_cache
    from app.core.logging_config import log_event

    logger.info("worker_start job=rebuild_financial_metrics triggered_by=%s", triggered_by)
    sb = get_supabase()
    metrics = recompute_and_persist_metrics(sb, source=f"worker_{triggered_by}")

    # Warm the shared cache immediately after rebuild
    financial = metrics.get("financial", {})
    from app.core.financials import to_number
    statement = {k: to_number(v) for k, v in financial.items()}
    statement["amount_owed"] = to_number(financial.get("total_outstanding"))
    statement["monthly_sales"] = to_number(financial.get("total_sales"))
    set_statement_cache(statement)

    log_event("worker_complete", job="rebuild_financial_metrics", triggered_by=triggered_by)
    return {"status": "ok", "triggered_by": triggered_by}


def archive_old_audit_logs() -> dict:
    """
    Move cashflow_audit_log rows older than 12 months into cashflow_audit_archive.
    Deletes source rows only after successful archive insert.
    """
    from app.db.supabase_client import get_supabase
    from app.core.logging_config import log_event
    from datetime import datetime, timedelta

    sb = get_supabase()
    cutoff = (datetime.utcnow() - timedelta(days=365)).isoformat()

    old_rows = (
        sb.table("cashflow_audit_log")
        .select("*")
        .lt("created_at", cutoff)
        .execute()
        .data or []
    )
    if not old_rows:
        log_event("audit_archive_skip", reason="no_rows_to_archive")
        return {"archived": 0}

    # Insert into archive table first
    sb.table("cashflow_audit_archive").insert(old_rows).execute()

    # Delete originals
    ids = [r["id"] for r in old_rows]
    sb.table("cashflow_audit_log").delete().in_("id", ids).execute()

    log_event("audit_archive_complete", archived=len(ids), cutoff=cutoff)
    return {"archived": len(ids), "cutoff": cutoff}


def run_integrity_check() -> dict:
    """Run the financial consistency validator and log any issues found."""
    from app.db.supabase_client import get_supabase
    from app.core.financial_integrity import run_all_checks

    sb = get_supabase()
    issues = run_all_checks(sb)
    return {"issues_found": len(issues), "issues": issues}
