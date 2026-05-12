"""Auth routes – thin wrapper; Supabase handles the heavy lifting."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from app.db.supabase_client import get_supabase

router = APIRouter()


class LoginPayload(BaseModel):
    email: EmailStr
    password: str


class SignupPayload(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
def login(payload: LoginPayload):
    sb = get_supabase()
    try:
        result = sb.auth.sign_in_with_password(
            {"email": payload.email, "password": payload.password}
        )
        return {
            "access_token": result.session.access_token,
            "refresh_token": result.session.refresh_token,
            "user": {"id": str(result.user.id), "email": result.user.email},
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid credentials")


@router.post("/signup")
def signup(payload: SignupPayload):
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
