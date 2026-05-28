"""Auth routes – thin wrapper; Supabase handles the heavy lifting."""
from datetime import datetime
import logging
import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from app.db.supabase_client import get_supabase, get_supabase_auth
from app.core.rbac import require_admin

router = APIRouter()
logger = logging.getLogger(__name__)


class LoginPayload(BaseModel):
    email: EmailStr
    password: str


class SignupPayload(BaseModel):
    email: EmailStr
    password: str


class RefreshPayload(BaseModel):
    refresh_token: str


_STATUS_BLOCK_MESSAGES = {
    "INACTIVE": "Account is inactive. Contact an admin to reactivate your account.",
    "SUSPENDED": "Account is suspended. Contact an admin to unlock access.",
    "DELETED": "Account has been deleted.",
}


def _audit(sb, *, action: str, entity_id: str, performed_by: str, detail: dict | None = None) -> None:
    try:
        sb.table("crm_audit_log").insert(
            {
                "action": action,
                "entity_type": "user",
                "entity_id": entity_id,
                "performed_by": performed_by,
                "detail": detail or {},
            }
        ).execute()
    except Exception:
        pass


def _ensure_profile_fields(profile: dict) -> dict:
    updated = dict(profile)
    updated["account_status"] = str(updated.get("account_status") or "ACTIVE").upper()
    if "is_active" not in updated:
        updated["is_active"] = updated["account_status"] == "ACTIVE"
    return updated


def _password_error_message(error_text: str) -> tuple[str, str]:
    lowered = str(error_text or "").lower()
    if "email not confirmed" in lowered or "not confirmed" in lowered:
        return "EMAIL_NOT_VERIFIED", "Email not verified. Please verify your email or ask an admin to resend activation."
    if "invalid login credentials" in lowered or "invalid credentials" in lowered:
        return "INVALID_PASSWORD", "Invalid password for this account."
    if "user not found" in lowered:
        return "AUTH_USER_MISSING", "Auth user missing for this account. Contact admin for recovery."
    if "token" in lowered and "expired" in lowered:
        return "TOKEN_ISSUE", "Authentication token issue detected. Please sign in again."
    return "AUTH_FAILED", "Unable to authenticate this account."


def _find_profile_by_email(sb, email: str) -> dict | None:
    try:
        rows = (
            sb.table("users")
            .select("*")
            .eq("email", email)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("login profile lookup failed email=%s error=%s", email, exc.__class__.__name__)
        return None


def _auth_user_exists(sb, user_id: str) -> bool:
    try:
        response = sb.auth.admin.get_user_by_id(user_id)
        return bool(getattr(response, "user", None))
    except Exception:
        return False


def _record_failed_login(sb, *, email: str, request: Request, reason_code: str, reason_message: str) -> None:
    profile = _find_profile_by_email(sb, email)
    if not profile:
        return
    user_id = str(profile.get("id") or "")
    attempts = int(profile.get("failed_login_attempts") or 0) + 1
    now = datetime.utcnow().isoformat()
    try:
        sb.table("users").update(
            {
                "failed_login_attempts": attempts,
                "last_failed_login": now,
            }
        ).eq("id", user_id).execute()
    except Exception:
        pass
    _audit(
        sb,
        action="user_login_failed",
        entity_id=user_id or email,
        performed_by=user_id or email,
        detail={
            "email": email,
            "reason_code": reason_code,
            "reason_message": reason_message,
            "ip": request.client.host if request and request.client else None,
            "user_agent": request.headers.get("user-agent") if request else None,
            "failed_login_attempts": attempts,
        },
    )


@router.post("/login")
def login(payload: LoginPayload, request: Request):
    sb_auth = get_supabase_auth()
    sb = get_supabase()
    normalized_email = str(payload.email).lower().strip()

    profile_by_email = _find_profile_by_email(sb, normalized_email)
    if profile_by_email:
        profile_by_email = _ensure_profile_fields(profile_by_email)
        status_value = str(profile_by_email.get("account_status") or "ACTIVE").upper()
        if status_value in _STATUS_BLOCK_MESSAGES:
            _record_failed_login(
                sb,
                email=normalized_email,
                request=request,
                reason_code=f"ACCOUNT_{status_value}",
                reason_message=_STATUS_BLOCK_MESSAGES[status_value],
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": f"ACCOUNT_{status_value}",
                    "message": _STATUS_BLOCK_MESSAGES[status_value],
                },
            )

    try:
        result = sb_auth.auth.sign_in_with_password(
            {"email": normalized_email, "password": payload.password}
        )
        user_id = str(result.user.id)
        profile = {
            "role": "staff",
            "is_active": True,
            "account_status": "ACTIVE",
            "full_name": (result.user.email or normalized_email).split("@")[0],
            "email": str(result.user.email or normalized_email).lower().strip(),
        }

        try:
            profile_rows = sb.table("users").select("*").eq("id", user_id).limit(1).execute().data or []
            if not profile_rows:
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
                inserted = sb.table("users").insert(
                    {
                        "id": user_id,
                        "email": str(result.user.email or normalized_email).lower().strip(),
                        "full_name": (result.user.email or "").split("@")[0],
                        "role": role,
                        "is_active": True,
                        "account_status": "ACTIVE",
                        "last_login_at": datetime.utcnow().isoformat(),
                        "last_login_ip": request.client.host if request and request.client else None,
                        "last_login_user_agent": request.headers.get("user-agent") if request else None,
                        "last_activity_at": datetime.utcnow().isoformat(),
                        "failed_login_attempts": 0,
                    }
                ).execute().data or []
                profile = inserted[0] if inserted else {"role": role, "is_active": True, "account_status": "ACTIVE"}
            else:
                profile = profile_rows[0]
        except Exception as exc:
            logger.warning("login profile sync failed user_id=%s error=%s", user_id, exc.__class__.__name__)

        profile = _ensure_profile_fields(profile)

        account_status = str(profile.get("account_status") or "ACTIVE").upper()
        if account_status in _STATUS_BLOCK_MESSAGES or not bool(profile.get("is_active", True)):
            _record_failed_login(
                sb,
                email=normalized_email,
                request=request,
                reason_code=f"ACCOUNT_{account_status}",
                reason_message=_STATUS_BLOCK_MESSAGES.get(account_status, "Account cannot sign in."),
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": f"ACCOUNT_{account_status}",
                    "message": _STATUS_BLOCK_MESSAGES.get(account_status, "Account cannot sign in."),
                },
            )

        try:
            sb.table("users").update(
                {
                    "last_login_at": datetime.utcnow().isoformat(),
                    "last_login_ip": request.client.host if request and request.client else None,
                    "last_login_user_agent": request.headers.get("user-agent") if request else None,
                    "last_activity_at": datetime.utcnow().isoformat(),
                    "failed_login_attempts": 0,
                }
            ).eq("id", user_id).execute()

            _audit(
                sb,
                action="user_login",
                entity_id=user_id,
                performed_by=user_id,
                detail={
                    "email": result.user.email,
                    "ip": request.client.host if request and request.client else None,
                    "user_agent": request.headers.get("user-agent") if request else None,
                },
            )
        except Exception as exc:
            logger.warning("login profile update skipped user_id=%s error=%s", user_id, exc.__class__.__name__)

        return {
            "access_token": result.session.access_token,
            "refresh_token": result.session.refresh_token,
            "expires_in": result.session.expires_in,
            "user": {
                "id": user_id,
                "email": result.user.email,
                "full_name": profile.get("full_name"),
                "phone": profile.get("phone"),
                "role": str(profile.get("role") or "staff").lower(),
                "is_active": bool(profile.get("is_active", True)),
                "account_status": account_status,
                "last_login_at": profile.get("last_login_at"),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        reason_code, reason_message = _password_error_message(str(e))

        if profile_by_email and reason_code == "INVALID_PASSWORD":
            user_id = str(profile_by_email.get("id") or "")
            if user_id and not _auth_user_exists(sb, user_id):
                reason_code = "AUTH_USER_MISSING"
                reason_message = "User exists in RBAC profile but Supabase auth identity is missing."

        _record_failed_login(
            sb,
            email=normalized_email,
            request=request,
            reason_code=reason_code,
            reason_message=reason_message,
        )
        raise HTTPException(
            status_code=401,
            detail={
                "code": reason_code,
                "message": reason_message,
            },
        )


@router.post("/signup")
def signup(payload: SignupPayload, _admin=Depends(require_admin)):
    sb = get_supabase()
    try:
        result = sb.auth.sign_up(
            {"email": payload.email, "password": payload.password}
        )
        return {"message": "Account created. Check your email to confirm.", "user_id": str(result.user.id)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/logout")
def logout():
    sb = get_supabase()
    sb.auth.sign_out()
    return {"message": "Logged out"}


@router.post("/refresh")
def refresh(payload: RefreshPayload):
    sb = get_supabase_auth()
    sb_admin = get_supabase()
    try:
        try:
            session = sb.auth.refresh_session(payload.refresh_token)
        except Exception:
            session = sb.auth.refresh_session({"refresh_token": payload.refresh_token})

        user_id = str(session.user.id)
        profile_rows = sb_admin.table("users").select("id,account_status,is_active,email").eq("id", user_id).limit(1).execute().data or []
        if profile_rows:
            profile = _ensure_profile_fields(profile_rows[0])
            account_status = str(profile.get("account_status") or "ACTIVE").upper()
            if account_status in _STATUS_BLOCK_MESSAGES or not bool(profile.get("is_active", True)):
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": f"ACCOUNT_{account_status}",
                        "message": _STATUS_BLOCK_MESSAGES.get(account_status, "Account cannot refresh tokens."),
                    },
                )

        return {
            "access_token": session.session.access_token,
            "refresh_token": session.session.refresh_token,
            "expires_in": session.session.expires_in,
        }
    except HTTPException:
        raise
    except Exception as e:
        code, message = _password_error_message(str(e))
        raise HTTPException(status_code=401, detail={"code": code, "message": message})
