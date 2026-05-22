"""Auth routes – thin wrapper; Supabase handles the heavy lifting."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from app.db.supabase_client import get_supabase, get_supabase_auth
from app.core.rbac import require_admin

router = APIRouter()


class LoginPayload(BaseModel):
    email: EmailStr
    password: str


class SignupPayload(BaseModel):
    email: EmailStr
    password: str


class RefreshPayload(BaseModel):
    refresh_token: str


@router.post("/login")
def login(payload: LoginPayload, request: Request):
    sb_auth = get_supabase_auth()
    sb = get_supabase()
    try:
        result = sb_auth.auth.sign_in_with_password(
            {"email": payload.email, "password": payload.password}
        )
        user_id = str(result.user.id)
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
                    "email": result.user.email,
                    "full_name": (result.user.email or "").split("@")[0],
                    "role": role,
                    "is_active": True,
                    "last_login_at": datetime.utcnow().isoformat(),
                    "last_login_ip": request.client.host if request and request.client else None,
                    "last_activity_at": datetime.utcnow().isoformat(),
                    "failed_login_attempts": 0,
                }
            ).execute().data or []
            profile = inserted[0] if inserted else {"role": role, "is_active": True}
        else:
            profile = profile_rows[0]

        if not bool(profile.get("is_active", True)):
            raise HTTPException(status_code=403, detail="Forbidden")

        sb.table("users").update(
            {
                "last_login_at": datetime.utcnow().isoformat(),
                "last_login_ip": request.client.host if request and request.client else None,
                "last_activity_at": datetime.utcnow().isoformat(),
                "failed_login_attempts": 0,
            }
        ).eq("id", user_id).execute()

        try:
            sb.table("crm_audit_log").insert(
                {
                    "action": "user_login",
                    "entity_type": "user",
                    "entity_id": user_id,
                    "performed_by": user_id,
                    "detail": {"email": result.user.email},
                }
            ).execute()
        except Exception:
            pass

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
                "last_login_at": profile.get("last_login_at"),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        try:
            current_rows = sb.table("users").select("id,failed_login_attempts").eq("email", payload.email).limit(1).execute().data or []
            if current_rows:
                current = current_rows[0]
                sb.table("users").update(
                    {"failed_login_attempts": int(current.get("failed_login_attempts") or 0) + 1}
                ).eq("id", current.get("id")).execute()
        except Exception:
            pass
        raise HTTPException(status_code=401, detail=str(e))


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
    try:
        try:
            session = sb.auth.refresh_session(payload.refresh_token)
        except Exception:
            session = sb.auth.refresh_session({"refresh_token": payload.refresh_token})
        return {
            "access_token": session.session.access_token,
            "refresh_token": session.session.refresh_token,
            "expires_in": session.session.expires_in,
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))
