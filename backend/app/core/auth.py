"""Shared auth dependency – validates JWT and hydrates CRM role context."""
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.db.supabase_client import get_supabase

bearer = HTTPBearer()

_DISABLED_ACCOUNT_STATUSES = {"INACTIVE", "SUSPENDED", "DELETED"}


@dataclass
class AuthContext:
    id: str
    email: str
    role: str
    is_active: bool
    account_status: str = "ACTIVE"
    full_name: str | None = None


def _log_auth_event(sb, action: str, user_id: str, detail: dict | None = None) -> None:
    try:
        sb.table("crm_audit_log").insert(
            {
                "action": action,
                "entity_type": "user",
                "entity_id": user_id,
                "performed_by": user_id,
                "detail": detail or {},
            }
        ).execute()
    except Exception:
        pass


def _get_or_create_profile(sb, user_id: str, email: str) -> dict:
    rows = sb.table("users").select("*").eq("id", user_id).limit(1).execute().data or []
    if rows:
        return rows[0]

    admins_count = (
        sb.table("users")
        .select("id", count="exact")
        .eq("role", "admin")
        .eq("is_active", True)
        .limit(1)
        .execute()
        .count
        or 0
    )
    role = "admin" if int(admins_count) == 0 else "staff"
    fallback_name = (email.split("@")[0] if email and "@" in email else email) or ""
    payload = {
        "id": user_id,
        "email": email,
        "full_name": fallback_name,
        "role": role,
        "is_active": True,
        "account_status": "ACTIVE",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    result = sb.table("users").insert(payload).execute().data or []
    created = result[0] if result else payload
    _log_auth_event(sb, "user_profile_bootstrapped", user_id, {"role": role})
    return created


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> AuthContext:
    """Verify JWT, then load CRM profile with role/is_active flags."""
    sb = get_supabase()
    try:
        auth_payload = sb.auth.get_user(creds.credentials)
        if auth_payload is None or auth_payload.user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

        auth_user = auth_payload.user
        user_id = str(auth_user.id)
        email = str(auth_user.email or "")
        profile = _get_or_create_profile(sb, user_id=user_id, email=email)

        account_status = str(profile.get("account_status") or "ACTIVE").upper()
        if account_status in _DISABLED_ACCOUNT_STATUSES or not bool(profile.get("is_active", True)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Account is {account_status.lower()}"
            )

        ip = request.client.host if request and request.client else None
        try:
            sb.table("users").update(
                {
                    "last_activity_at": datetime.utcnow().isoformat(),
                    "last_login_ip": ip,
                }
            ).eq("id", user_id).execute()
        except Exception:
            pass

        return AuthContext(
            id=user_id,
            email=email,
            role=str(profile.get("role") or "staff").lower(),
            is_active=bool(profile.get("is_active", True)),
            account_status=account_status,
            full_name=profile.get("full_name"),
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
