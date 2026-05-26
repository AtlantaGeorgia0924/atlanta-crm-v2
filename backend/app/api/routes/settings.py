from fastapi import APIRouter, Depends
from app.db.supabase_client import get_supabase
from app.core.auth import get_current_user
from app.core.rbac import require_admin

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("")
def get_settings(_user=Depends(get_current_user)):
    sb = get_supabase()
    result = sb.table("app_settings").select("*").execute()
    settings_map = {row["key"]: row["value"] for row in result.data}
    settings_map.setdefault("currency", "NGN")
    return settings_map


@router.put("/{key}")
def update_setting(key: str, value: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    sb.table("app_settings").upsert({"key": key, "value": value}).execute()
    return {"key": key, "value": value}


@router.get("/status")
def system_status(_user=Depends(get_current_user)):
    """Return database connectivity and last sync info."""
    sb = get_supabase()
    settings_res = sb.table("app_settings").select("*").execute()
    settings_map = {row["key"]: row["value"] for row in settings_res.data}
    return {
        "db_connected": True,
        "last_sync_at": settings_map.get("last_sync_at"),
        "last_workspace_refresh": settings_map.get("last_workspace_refresh"),
        "business_name": settings_map.get("business_name"),
        "currency": settings_map.get("currency") or "NGN",
    }
