from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr

from app.core.auth import get_current_user
from app.core.rbac import require_admin
from app.db.supabase_client import get_supabase

router = APIRouter(dependencies=[Depends(require_admin)])


def _normalize_phone(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("234"):
        return digits
    if digits.startswith("0") and len(digits) == 11:
        return "234" + digits[1:]
    return digits


def _audit(sb, action: str, performed_by: str, entity_id: str, before_value=None, after_value=None, detail=None):
    try:
        sb.table("crm_audit_log").insert(
            {
                "action": action,
                "entity_type": "user",
                "entity_id": entity_id,
                "performed_by": performed_by,
                "before_value": before_value,
                "after_value": after_value,
                "detail": detail or {},
            }
        ).execute()
    except Exception:
        pass


class UserCreatePayload(BaseModel):
    full_name: str
    email: EmailStr
    phone: str | None = None
    password: str
    role: str = "staff"


class UserUpdatePayload(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    role: str | None = None
    is_active: bool | None = None


class PasswordResetPayload(BaseModel):
    password: str


@router.get("")
def list_users(
    search: str | None = Query(None),
    role: str | None = Query(None),
    is_active: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _user=Depends(get_current_user),
):
    sb = get_supabase()
    offset = (page - 1) * page_size
    q = sb.table("users").select("*", count="exact").order("created_at", desc=True).range(offset, offset + page_size - 1)
    if role:
        q = q.eq("role", role.lower())
    if is_active is not None:
        q = q.eq("is_active", is_active)
    if search:
        term = search.strip()
        if term:
            q = q.or_(
                f"full_name.ilike.%{term}%,"
                f"email.ilike.%{term}%,"
                f"phone.ilike.%{term}%"
            )
    result = q.execute()
    items = result.data or []
    total = int(result.count or 0)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


@router.post("", status_code=201)
def create_user(payload: UserCreatePayload, _user=Depends(get_current_user)):
    sb = get_supabase()
    role = str(payload.role or "staff").lower()
    if role not in {"admin", "staff"}:
        raise HTTPException(status_code=422, detail="role must be admin or staff")

    existing = sb.table("users").select("id").eq("email", payload.email).limit(1).execute().data or []
    if existing:
        raise HTTPException(status_code=409, detail="Email already exists")

    try:
        created_auth = sb.auth.admin.create_user(
            {
                "email": payload.email,
                "password": payload.password,
                "email_confirm": True,
                "user_metadata": {"full_name": payload.full_name, "role": role},
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    auth_user_id = str(getattr(created_auth.user, "id", "") or "") or str(uuid.uuid4())
    record = {
        "id": auth_user_id,
        "full_name": payload.full_name.strip(),
        "email": str(payload.email).lower().strip(),
        "phone": _normalize_phone(payload.phone),
        "role": role,
        "is_active": True,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "created_by": str(_user.id),
    }
    inserted = sb.table("users").upsert(record).execute().data or []
    created = inserted[0] if inserted else record
    _audit(
        sb,
        action="user_created",
        performed_by=str(_user.id),
        entity_id=auth_user_id,
        before_value=None,
        after_value={"role": role, "is_active": True, "email": created.get("email")},
    )
    return created


@router.put("/{user_id}")
def update_user(user_id: str, payload: UserUpdatePayload, _user=Depends(get_current_user)):
    sb = get_supabase()
    before = sb.table("users").select("*").eq("id", user_id).single().execute().data
    if not before:
        raise HTTPException(status_code=404, detail="User not found")

    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "role" in updates:
        next_role = str(updates["role"]).lower()
        if next_role not in {"admin", "staff"}:
            raise HTTPException(status_code=422, detail="role must be admin or staff")

        if str(before.get("role") or "").lower() == "admin" and next_role != "admin":
            admins_count = (
                sb.table("users")
                .select("id", count="exact")
                .eq("role", "admin")
                .eq("is_active", True)
                .execute()
                .count
                or 0
            )
            if int(admins_count) <= 1:
                raise HTTPException(status_code=400, detail="Cannot demote the last active admin")
        updates["role"] = next_role

    if "is_active" in updates and before.get("role") == "admin" and before.get("is_active") is True and updates["is_active"] is False:
        admins_count = (
            sb.table("users")
            .select("id", count="exact")
            .eq("role", "admin")
            .eq("is_active", True)
            .execute()
            .count
            or 0
        )
        if int(admins_count) <= 1:
            raise HTTPException(status_code=400, detail="Cannot deactivate the last active admin")

    if "phone" in updates:
        updates["phone"] = _normalize_phone(updates.get("phone"))
    if "email" in updates and updates.get("email"):
        updates["email"] = str(updates["email"]).lower().strip()

    updates["updated_at"] = datetime.utcnow().isoformat()
    updates["updated_by"] = str(_user.id)

    after_rows = sb.table("users").update(updates).eq("id", user_id).execute().data or []
    after = after_rows[0] if after_rows else {**before, **updates}

    auth_updates = {}
    if "email" in updates:
        auth_updates["email"] = updates["email"]
    if "is_active" in updates:
        auth_updates["ban_duration"] = "none" if updates["is_active"] else "876000h"
    if auth_updates:
        try:
            sb.auth.admin.update_user_by_id(user_id, auth_updates)
        except Exception:
            pass

    action = "user_updated"
    if before.get("role") != after.get("role"):
        action = "user_role_changed"
    if before.get("is_active") != after.get("is_active"):
        action = "user_activation_changed"
    _audit(
        sb,
        action=action,
        performed_by=str(_user.id),
        entity_id=user_id,
        before_value={"role": before.get("role"), "is_active": before.get("is_active")},
        after_value={"role": after.get("role"), "is_active": after.get("is_active")},
    )
    return after


@router.post("/{user_id}/reset-password")
def reset_password(user_id: str, payload: PasswordResetPayload, _user=Depends(get_current_user)):
    sb = get_supabase()
    target = sb.table("users").select("id,email").eq("id", user_id).single().execute().data
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        sb.auth.admin.update_user_by_id(user_id, {"password": payload.password})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    sb.table("users").update({"password_reset_at": datetime.utcnow().isoformat()}).eq("id", user_id).execute()
    _audit(
        sb,
        action="user_password_reset",
        performed_by=str(_user.id),
        entity_id=user_id,
        detail={"target_email": target.get("email")},
    )
    return {"message": "Password reset successfully"}