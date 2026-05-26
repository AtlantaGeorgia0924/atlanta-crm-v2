"""Workspace refresh endpoints.

Google Sheets sync was removed. This module now exposes only the
Supabase-backed workspace refresh endpoints used by admin tools.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user
from app.core.metrics_refresh import recompute_and_persist_metrics
from app.core.rbac import require_admin
from app.db.supabase_client import get_supabase

router = APIRouter(dependencies=[Depends(require_admin)])


def _log_sync_audit(sb, action: str, performed_by: str, detail: dict | None = None) -> None:
    try:
        sb.table("crm_audit_log").insert(
            {
                "action": action,
                "entity_type": "sync",
                "entity_id": action,
                "performed_by": performed_by,
                "detail": detail or {},
            }
        ).execute()
    except Exception:
        pass


@router.post("/refresh-workspace")
def refresh_workspace(_user=Depends(get_current_user)):
    """Recalculate dashboard and financial metrics from Supabase only."""
    sb = get_supabase()
    try:
        metrics = recompute_and_persist_metrics(sb, source="supabase")
    except Exception as exc:
        raise HTTPException(500, f"Workspace refresh failed: {str(exc)}")

    refreshed_at = datetime.utcnow().isoformat()
    sb.table("app_settings").upsert(
        {"key": "last_workspace_refresh", "value": refreshed_at}
    ).execute()
    _log_sync_audit(sb, "refresh_workspace", str(_user.id), {"refreshed_at": refreshed_at})
    return {
        "message": "Workspace refreshed from Supabase.",
        "refreshed_at": refreshed_at,
        "source": "supabase",
        "values_calculated": metrics,
    }


@router.post("/refresh-supabase")
def refresh_from_supabase(_user=Depends(get_current_user)):
    """Backward-compatible alias for refresh-workspace (Supabase-only)."""
    return refresh_workspace(_user)