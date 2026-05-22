from __future__ import annotations

from datetime import datetime
import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr

from app.core.auth import get_current_user
from app.core.rbac import require_admin
from app.db.supabase_client import get_supabase

router = APIRouter(dependencies=[Depends(require_admin)])

_ALLOWED_ROLES = {"admin", "staff"}
_ALLOWED_STATUSES = {"ACTIVE", "INACTIVE", "SUSPENDED", "DELETED"}


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


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _normalize_status(value: str | None) -> str:
    text = str(value or "ACTIVE").strip().upper()
    return text if text in _ALLOWED_STATUSES else "ACTIVE"


def _password_strength_error(password: str) -> str | None:
    candidate = str(password or "")
    if len(candidate) < 8:
        return "Password must be at least 8 characters"
    if not any(ch.isupper() for ch in candidate):
        return "Password must contain an uppercase letter"
    if not any(ch.islower() for ch in candidate):
        return "Password must contain a lowercase letter"
    if not any(ch.isdigit() for ch in candidate):
        return "Password must contain a number"
    return None


def _generate_temp_password(length: int = 12) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(chars) for _ in range(length))


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


def _email_exists(sb, email: str, *, exclude_user_id: str | None = None) -> bool:
    query = sb.table("users").select("id").eq("email", email).limit(1)
    rows = query.execute().data or []
    if not rows:
        return False
    existing_id = str(rows[0].get("id") or "")
    return not exclude_user_id or existing_id != exclude_user_id


def _phone_exists(sb, phone: str | None, *, exclude_user_id: str | None = None) -> bool:
    if not phone:
        return False
    rows = sb.table("users").select("id").eq("phone", phone).limit(1).execute().data or []
    if not rows:
        return False
    existing_id = str(rows[0].get("id") or "")
    return not exclude_user_id or existing_id != exclude_user_id


def _active_admin_count(sb) -> int:
    count = (
        sb.table("users")
        .select("id", count="exact")
        .eq("role", "admin")
        .eq("account_status", "ACTIVE")
        .execute()
        .count
        or 0
    )
    return int(count)


def _status_to_active(status: str) -> bool:
    return status == "ACTIVE"


def _ensure_auth_unblocked(sb, user_id: str, *, is_active: bool) -> None:
    try:
        sb.auth.admin.update_user_by_id(
            user_id,
            {"ban_duration": "none" if is_active else "876000h"},
        )
    except Exception:
        pass


def _update_auth_email(sb, user_id: str, email: str) -> None:
    try:
        sb.auth.admin.update_user_by_id(user_id, {"email": email})
    except Exception:
        pass


def _dependency_counts(sb, user_id: str) -> dict[str, int]:
    checks: list[tuple[str, str, str]] = [
        ("crm_audit_log", "performed_by", "audit_events"),
        ("cashflow_audit_log", "performed_by", "cashflow_events"),
        ("payments", "performed_by", "payment_events"),
        ("users", "created_by", "created_users"),
        ("users", "updated_by", "updated_users"),
    ]
    output: dict[str, int] = {}
    for table, column, key in checks:
        try:
            count = (
                sb.table(table)
                .select("id", count="exact")
                .eq(column, user_id)
                .limit(1)
                .execute()
                .count
                or 0
            )
            output[key] = int(count)
        except Exception:
            output[key] = 0
    return output


def _reassign_dependencies(sb, user_id: str, new_user_id: str) -> None:
    updates: list[tuple[str, str]] = [
        ("crm_audit_log", "performed_by"),
        ("cashflow_audit_log", "performed_by"),
        ("payments", "performed_by"),
        ("users", "created_by"),
        ("users", "updated_by"),
    ]
    for table, column in updates:
        try:
            sb.table(table).update({column: new_user_id}).eq(column, user_id).execute()
        except Exception:
            pass


def _find_user(sb, user_id: str) -> dict:
    user = sb.table("users").select("*").eq("id", user_id).single().execute().data
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _find_auth_user_by_email(sb, email: str):
    normalized_email = str(email or "").lower().strip()
    if not normalized_email:
        return None
    try:
        page = 1
        while True:
            users = sb.auth.admin.list_users(page=page, per_page=1000) or []
            for user in users:
                if str(getattr(user, "email", "") or "").lower().strip() == normalized_email:
                    return user
            if len(users) < 1000:
                break
            page += 1
    except Exception:
        return None
    return None


class UserCreatePayload(BaseModel):
    full_name: str
    email: EmailStr
    phone: str | None = None
    password: str | None = None
    role: str = "staff"


class UserUpdatePayload(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    role: str | None = None
    is_active: bool | None = None
    account_status: str | None = None


class PasswordResetPayload(BaseModel):
    password: str


class SuspendPayload(BaseModel):
    reason: str | None = None


class DeleteUserPayload(BaseModel):
    hard_delete: bool = False
    reassign_to: str | None = None


@router.get("")
def list_users(
    search: str | None = Query(None),
    role: str | None = Query(None),
    is_active: bool | None = Query(None),
    account_status: str | None = Query(None),
    include_deleted: bool = Query(False),
    last_login_from: str | None = Query(None),
    last_login_to: str | None = Query(None),
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

    normalized_status = _normalize_status(account_status) if account_status else None
    if normalized_status:
        q = q.eq("account_status", normalized_status)
    elif not include_deleted:
        q = q.neq("account_status", "DELETED")

    if last_login_from:
        q = q.gte("last_login_at", str(last_login_from).strip()[:10])
    if last_login_to:
        q = q.lte("last_login_at", str(last_login_to).strip()[:10] + "T23:59:59")

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
    if role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=422, detail="Invalid role")

    email = str(payload.email).lower().strip()
    phone = _normalize_phone(payload.phone)
    if _email_exists(sb, email):
        raise HTTPException(status_code=409, detail="Email already exists")
    if _phone_exists(sb, phone):
        raise HTTPException(status_code=409, detail="Phone already exists")

    final_password = str(payload.password or "")
    generated_temp_password = None
    if not final_password:
        generated_temp_password = _generate_temp_password()
        final_password = generated_temp_password

    password_error = _password_strength_error(final_password)
    if password_error:
        raise HTTPException(status_code=422, detail=password_error)

    try:
        created_auth = sb.auth.admin.create_user(
            {
                "email": email,
                "password": final_password,
                "email_confirm": True,
                "user_metadata": {"full_name": payload.full_name, "role": role},
            }
        )
    except Exception as exc:
        existing_auth = _find_auth_user_by_email(sb, email)
        if not existing_auth:
            raise HTTPException(status_code=400, detail=f"Supabase Auth create failed: {exc}")
        try:
            sb.auth.admin.update_user_by_id(
                str(existing_auth.id),
                {
                    "password": final_password,
                    "email_confirm": True,
                    "user_metadata": {"full_name": payload.full_name, "role": role},
                },
            )
        except Exception:
            pass
        created_auth = existing_auth

    auth_user_id = str(getattr(created_auth.user, "id", "") or "")
    if not auth_user_id:
        auth_user_id = str(getattr(created_auth, "id", "") or "")
    if not auth_user_id:
        raise HTTPException(status_code=500, detail="Auth identity creation failed")

    record = {
        "id": auth_user_id,
        "full_name": payload.full_name.strip(),
        "email": email,
        "phone": phone,
        "role": role,
        "account_status": "ACTIVE",
        "is_active": True,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "created_by": str(_user.id),
        "failed_login_attempts": 0,
    }
    try:
        inserted = sb.table("users").upsert(record).execute().data or []
        created = inserted[0] if inserted else record
    except Exception as exc:
        try:
            sb.auth.admin.delete_user(auth_user_id)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Profile creation failed after auth user creation: {exc}")

    _audit(
        sb,
        action="user_created",
        performed_by=str(_user.id),
        entity_id=auth_user_id,
        before_value=None,
        after_value={"role": role, "account_status": "ACTIVE", "email": created.get("email")},
    )

    credentials = {
        "email": email,
        "temporary_password": generated_temp_password,
        "share_text": f"Login credentials\nEmail: {email}\nPassword: {generated_temp_password}" if generated_temp_password else None,
    }

    return {
        "user": created,
        "credentials": credentials,
    }


@router.put("/{user_id}")
def update_user(user_id: str, payload: UserUpdatePayload, _user=Depends(get_current_user)):
    sb = get_supabase()
    before = _find_user(sb, user_id)

    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "role" in updates:
        next_role = str(updates["role"]).lower()
        if next_role not in _ALLOWED_ROLES:
            raise HTTPException(status_code=422, detail="Invalid role")

        if str(before.get("role") or "").lower() == "admin" and next_role != "admin":
            if _active_admin_count(sb) <= 1:
                raise HTTPException(status_code=400, detail="Cannot demote the last active admin")
        updates["role"] = next_role

    if "phone" in updates:
        updates["phone"] = _normalize_phone(updates.get("phone"))
        if _phone_exists(sb, updates["phone"], exclude_user_id=user_id):
            raise HTTPException(status_code=409, detail="Phone already exists")

    if "email" in updates and updates.get("email"):
        updates["email"] = str(updates["email"]).lower().strip()
        if _email_exists(sb, updates["email"], exclude_user_id=user_id):
            raise HTTPException(status_code=409, detail="Email already exists")

    explicit_status = None
    if "account_status" in updates:
        explicit_status = _normalize_status(updates.pop("account_status"))

    if "is_active" in updates and explicit_status is None:
        explicit_status = "ACTIVE" if bool(updates.pop("is_active")) else "INACTIVE"

    if explicit_status is None:
        explicit_status = _normalize_status(before.get("account_status") or "ACTIVE")

    if before.get("id") == str(_user.id) and explicit_status in {"INACTIVE", "SUSPENDED", "DELETED"}:
        raise HTTPException(status_code=400, detail="You cannot disable your own account")

    if str(before.get("role") or "").lower() == "admin" and str(before.get("account_status") or "ACTIVE").upper() == "ACTIVE" and explicit_status != "ACTIVE":
        if _active_admin_count(sb) <= 1:
            raise HTTPException(status_code=400, detail="Cannot disable the last active admin")

    updates["account_status"] = explicit_status
    updates["is_active"] = _status_to_active(explicit_status)
    updates["updated_at"] = _now_iso()
    updates["updated_by"] = str(_user.id)

    if explicit_status == "SUSPENDED":
        updates["suspended_at"] = _now_iso()
    if explicit_status == "DELETED":
        updates["deleted_at"] = _now_iso()
        updates["deleted_by"] = str(_user.id)
    if explicit_status == "ACTIVE":
        updates["suspended_at"] = None
        updates["suspension_reason"] = None
        updates["deleted_at"] = None
        updates["deleted_by"] = None

    after_rows = sb.table("users").update(updates).eq("id", user_id).execute().data or []
    after = after_rows[0] if after_rows else {**before, **updates}

    if "email" in updates:
        _update_auth_email(sb, user_id, updates["email"])
    _ensure_auth_unblocked(sb, user_id, is_active=bool(updates.get("is_active")))

    action = "user_updated"
    if before.get("role") != after.get("role"):
        action = "user_role_changed"
    if before.get("account_status") != after.get("account_status"):
        action = "user_status_changed"
    _audit(
        sb,
        action=action,
        performed_by=str(_user.id),
        entity_id=user_id,
        before_value={"role": before.get("role"), "account_status": before.get("account_status"), "is_active": before.get("is_active")},
        after_value={"role": after.get("role"), "account_status": after.get("account_status"), "is_active": after.get("is_active")},
    )
    return after


@router.post("/{user_id}/reset-password")
def reset_password(user_id: str, payload: PasswordResetPayload, _user=Depends(get_current_user)):
    sb = get_supabase()
    target = _find_user(sb, user_id)

    password_error = _password_strength_error(payload.password)
    if password_error:
        raise HTTPException(status_code=422, detail=password_error)

    try:
        sb.auth.admin.update_user_by_id(user_id, {"password": payload.password})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Password reset failed: {exc}")

    sb.table("users").update({"password_reset_at": _now_iso(), "updated_by": str(_user.id)}).eq("id", user_id).execute()
    _audit(
        sb,
        action="user_password_reset",
        performed_by=str(_user.id),
        entity_id=user_id,
        detail={"target_email": target.get("email")},
    )
    return {"message": "Password reset successfully"}


@router.post("/{user_id}/activate")
def activate_user(user_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    before = _find_user(sb, user_id)

    updates = {
        "account_status": "ACTIVE",
        "is_active": True,
        "failed_login_attempts": 0,
        "suspended_at": None,
        "suspension_reason": None,
        "deleted_at": None,
        "deleted_by": None,
        "updated_at": _now_iso(),
        "updated_by": str(_user.id),
    }
    after = sb.table("users").update(updates).eq("id", user_id).execute().data[0]
    _ensure_auth_unblocked(sb, user_id, is_active=True)
    _audit(
        sb,
        action="user_reactivated",
        performed_by=str(_user.id),
        entity_id=user_id,
        before_value={"account_status": before.get("account_status")},
        after_value={"account_status": "ACTIVE"},
    )
    return after


@router.post("/{user_id}/suspend")
def suspend_user(user_id: str, payload: SuspendPayload, _user=Depends(get_current_user)):
    sb = get_supabase()
    before = _find_user(sb, user_id)

    if str(before.get("id") or "") == str(_user.id):
        raise HTTPException(status_code=400, detail="You cannot suspend yourself")

    if str(before.get("role") or "").lower() == "admin" and str(before.get("account_status") or "ACTIVE").upper() == "ACTIVE":
        if _active_admin_count(sb) <= 1:
            raise HTTPException(status_code=400, detail="Cannot suspend the last active admin")

    updates = {
        "account_status": "SUSPENDED",
        "is_active": False,
        "suspended_at": _now_iso(),
        "suspension_reason": str(payload.reason or "").strip() or None,
        "updated_at": _now_iso(),
        "updated_by": str(_user.id),
    }
    after = sb.table("users").update(updates).eq("id", user_id).execute().data[0]
    _ensure_auth_unblocked(sb, user_id, is_active=False)
    _audit(
        sb,
        action="user_suspended",
        performed_by=str(_user.id),
        entity_id=user_id,
        before_value={"account_status": before.get("account_status")},
        after_value={"account_status": "SUSPENDED"},
        detail={"reason": updates["suspension_reason"]},
    )
    return after


@router.post("/{user_id}/unlock")
def unlock_user(user_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    before = _find_user(sb, user_id)
    updates = {
        "failed_login_attempts": 0,
        "last_failed_login": None,
        "updated_at": _now_iso(),
        "updated_by": str(_user.id),
    }
    # Unlocking also restores suspended accounts unless explicitly deleted.
    if str(before.get("account_status") or "ACTIVE").upper() == "SUSPENDED":
        updates["account_status"] = "ACTIVE"
        updates["is_active"] = True
        updates["suspended_at"] = None
        updates["suspension_reason"] = None

    after = sb.table("users").update(updates).eq("id", user_id).execute().data[0]
    _ensure_auth_unblocked(sb, user_id, is_active=bool(after.get("is_active", True)))
    _audit(
        sb,
        action="user_unlocked",
        performed_by=str(_user.id),
        entity_id=user_id,
        before_value={"failed_login_attempts": before.get("failed_login_attempts"), "account_status": before.get("account_status")},
        after_value={"failed_login_attempts": after.get("failed_login_attempts"), "account_status": after.get("account_status")},
    )
    return after


@router.post("/{user_id}/resend-activation")
def resend_activation(user_id: str, _user=Depends(get_current_user)):
    sb = get_supabase()
    target = _find_user(sb, user_id)
    email = str(target.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="User does not have an email")

    # Prefer invite link generation; fallback to standard password reset email.
    sent = False
    last_error = None
    try:
        sb.auth.admin.generate_link({"type": "signup", "email": email})
        sent = True
    except Exception as exc:
        last_error = str(exc)

    if not sent:
        try:
            sb.auth.reset_password_email(email)
            sent = True
        except Exception as exc:
            last_error = str(exc)

    if not sent:
        raise HTTPException(status_code=400, detail=f"Activation resend failed: {last_error}")

    _audit(
        sb,
        action="user_activation_resent",
        performed_by=str(_user.id),
        entity_id=user_id,
        detail={"email": email},
    )
    return {"message": "Activation instructions sent"}


@router.delete("/{user_id}")
def delete_user(user_id: str, payload: DeleteUserPayload, _user=Depends(get_current_user)):
    sb = get_supabase()
    before = _find_user(sb, user_id)

    current_user_id = str(_user.id)
    if str(user_id) == current_user_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")

    role = str(before.get("role") or "").lower()
    status = str(before.get("account_status") or "ACTIVE").upper()
    if role == "admin" and status == "ACTIVE" and _active_admin_count(sb) <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last active admin")

    dependency_counts = _dependency_counts(sb, user_id)
    unresolved = {k: v for k, v in dependency_counts.items() if v > 0}

    reassign_to = str(payload.reassign_to or "").strip() or None
    if unresolved and not reassign_to:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "OWNERSHIP_REASSIGN_REQUIRED",
                "message": "User has ownership dependencies; provide reassign_to before deletion.",
                "dependencies": unresolved,
            },
        )

    if reassign_to:
        _find_user(sb, reassign_to)
        _reassign_dependencies(sb, user_id, reassign_to)

    if payload.hard_delete:
        sb.table("users").delete().eq("id", user_id).execute()
        try:
            sb.auth.admin.delete_user(user_id)
        except Exception:
            pass
        _audit(
            sb,
            action="user_hard_deleted",
            performed_by=current_user_id,
            entity_id=user_id,
            before_value={"account_status": before.get("account_status")},
            after_value=None,
            detail={"reassigned_to": reassign_to, "dependencies": unresolved},
        )
        return {"message": "User permanently deleted"}

    updates = {
        "account_status": "DELETED",
        "is_active": False,
        "deleted_at": _now_iso(),
        "deleted_by": current_user_id,
        "updated_at": _now_iso(),
        "updated_by": current_user_id,
    }
    sb.table("users").update(updates).eq("id", user_id).execute()
    _ensure_auth_unblocked(sb, user_id, is_active=False)

    _audit(
        sb,
        action="user_soft_deleted",
        performed_by=current_user_id,
        entity_id=user_id,
        before_value={"account_status": before.get("account_status"), "is_active": before.get("is_active")},
        after_value={"account_status": "DELETED", "is_active": False},
        detail={"reassigned_to": reassign_to, "dependencies": unresolved},
    )
    return {"message": "User deactivated and marked as deleted"}
