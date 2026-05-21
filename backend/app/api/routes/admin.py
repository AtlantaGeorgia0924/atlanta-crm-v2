"""
Admin endpoints – financial integrity, metrics, and observability.

GET  /admin/financial-integrity-report  – run all consistency checks
GET  /admin/metrics                     – endpoint latency + cache hit stats
POST /admin/enqueue-integrity-check     – trigger background integrity job
POST /admin/enqueue-metrics-rebuild     – trigger background metrics rebuild
"""
import logging
from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.core.financial_integrity import run_all_checks
from app.core.logging_config import get_metrics_summary, log_event
from app.core.cache import cache_hit_rate
from app.db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/financial-integrity-report")
def financial_integrity_report(_user=Depends(get_current_user)):
    """Run all financial consistency validators synchronously and return results."""
    sb = get_supabase()
    issues = run_all_checks(sb)
    log_event("integrity_report_requested", issues_found=len(issues), performed_by=str(_user.id))
    return {
        "issues_found": len(issues),
        "issues": issues,
    }


@router.get("/metrics")
def get_metrics(_user=Depends(get_current_user)):
    """Return endpoint latency histograms and Redis cache hit rate."""
    return {
        "latency": get_metrics_summary(),
        "cache": cache_hit_rate(),
    }


@router.post("/enqueue-integrity-check")
def enqueue_integrity_check(_user=Depends(get_current_user)):
    """Enqueue a background financial integrity check via RQ."""
    try:
        import redis  # type: ignore
        from rq import Queue  # type: ignore
        import os
        from app.core.workers import run_integrity_check

        redis_url = os.getenv("REDIS_URL", "")
        if not redis_url:
            return {"status": "skipped", "reason": "REDIS_URL not configured"}
        r = redis.from_url(redis_url, socket_connect_timeout=2)
        q = Queue("financial", connection=r)
        job = q.enqueue(run_integrity_check, job_timeout=300)
        log_event("integrity_check_enqueued", job_id=job.id, performed_by=str(_user.id))
        return {"status": "enqueued", "job_id": job.id}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@router.post("/enqueue-metrics-rebuild")
def enqueue_metrics_rebuild(_user=Depends(get_current_user)):
    """Enqueue a background financial metrics rebuild via RQ."""
    try:
        import redis  # type: ignore
        from rq import Queue  # type: ignore
        import os
        from app.core.workers import rebuild_financial_metrics

        redis_url = os.getenv("REDIS_URL", "")
        if not redis_url:
            return {"status": "skipped", "reason": "REDIS_URL not configured"}
        r = redis.from_url(redis_url, socket_connect_timeout=2)
        q = Queue("financial", connection=r)
        job = q.enqueue(rebuild_financial_metrics, str(_user.id), job_timeout=120)
        log_event("metrics_rebuild_enqueued", job_id=job.id, performed_by=str(_user.id))
        return {"status": "enqueued", "job_id": job.id}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}
