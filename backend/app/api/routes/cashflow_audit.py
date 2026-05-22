"""
Audit log API endpoints.

GET  /cashflow/audit              – paginated audit log with filters
POST /cashflow/audit/cleanup      – archive rows older than 12 months
GET  /cashflow/audit/export-csv   – export filtered rows as CSV
"""
import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.auth import get_current_user
from app.db.supabase_client import get_supabase
from app.core.logging_config import log_event
from app.core.rbac import user_is_admin

logger = logging.getLogger(__name__)

router = APIRouter()

_AUDIT_FIELDS = "id,action,amount,performed_by,related_record_id,detail,created_at"


# ── RBAC helper ───────────────────────────────────────────────────────────────

def _require_admin(user) -> None:
    """Raise 403 if the JWT user is not in the admins/managers app_settings list."""
    # Admin check: look for user id or email in app_settings key "admin_user_ids".
    # If the key doesn't exist yet, only super-admin (first user) can see this.
    # This is intentionally permissive at the DB layer – tighten with RLS policies.
    if not user_is_admin(user):
        raise HTTPException(status_code=403, detail="Forbidden")


# ── List / filter ─────────────────────────────────────────────────────────────

@router.get("/audit")
def list_audit_log(
    action: Optional[str] = Query(None),
    performed_by: Optional[str] = Query(None),
    related_record_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    _user=Depends(get_current_user),
):
    _require_admin(_user)
    sb = get_supabase()
    offset = (page - 1) * page_size

    q = sb.table("cashflow_audit_log").select(_AUDIT_FIELDS, count="exact")

    if action:
        q = q.eq("action", action)
    if performed_by:
        q = q.eq("performed_by", performed_by)
    if related_record_id:
        q = q.eq("related_record_id", related_record_id)
    if date_from:
        q = q.gte("created_at", date_from)
    if date_to:
        # Include the full day by going to midnight of the next day
        next_day = (datetime.fromisoformat(date_to) + timedelta(days=1)).date().isoformat()
        q = q.lt("created_at", next_day)

    result = q.order("created_at", desc=True).range(offset, offset + page_size - 1).execute()
    items = result.data or []
    total_count = int(result.count or 0)
    total_pages = max(1, (total_count + page_size - 1) // page_size)

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
        "total_pages": total_pages,
    }


# ── CSV export ────────────────────────────────────────────────────────────────

@router.get("/audit/export-csv")
def export_audit_csv(
    action: Optional[str] = Query(None),
    performed_by: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    _user=Depends(get_current_user),
):
    _require_admin(_user)
    sb = get_supabase()

    q = sb.table("cashflow_audit_log").select(_AUDIT_FIELDS)
    if action:
        q = q.eq("action", action)
    if performed_by:
        q = q.eq("performed_by", performed_by)
    if date_from:
        q = q.gte("created_at", date_from)
    if date_to:
        next_day = (datetime.fromisoformat(date_to) + timedelta(days=1)).date().isoformat()
        q = q.lt("created_at", next_day)

    rows = q.order("created_at", desc=True).limit(5000).execute().data or []

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["id", "action", "amount", "performed_by", "related_record_id", "detail", "created_at"],
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    log_event("audit_csv_exported", exported_rows=len(rows), performed_by=str(_user.id))

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cashflow_audit_export.csv"},
    )


# ── Archive / cleanup ─────────────────────────────────────────────────────────

@router.post("/audit/cleanup")
def cleanup_audit_log(_user=Depends(get_current_user)):
    """
    Move cashflow_audit_log rows older than 12 months into cashflow_audit_archive.
    Deletes originals only after successful archive insert.
    """
    _require_admin(_user)
    sb = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()

    old_rows = (
        sb.table("cashflow_audit_log")
        .select("*")
        .lt("created_at", cutoff)
        .execute()
        .data or []
    )
    if not old_rows:
        return {"archived": 0, "message": "No rows old enough to archive."}

    try:
        sb.table("cashflow_audit_archive").insert(old_rows).execute()
    except Exception as exc:
        raise HTTPException(500, f"Archive insert failed: {exc}")

    ids = [r["id"] for r in old_rows]
    sb.table("cashflow_audit_log").delete().in_("id", ids).execute()

    log_event("audit_cleanup", archived=len(ids), cutoff=cutoff, performed_by=str(_user.id))
    return {"archived": len(ids), "cutoff": cutoff}
