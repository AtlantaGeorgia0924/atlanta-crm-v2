"""Shared auth dependency – validates the Supabase JWT sent from the browser."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.db.supabase_client import get_supabase

bearer = HTTPBearer()


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
):
    """Verify the JWT with Supabase and return the user payload."""
    sb = get_supabase()
    try:
        user = sb.auth.get_user(creds.credentials)
        if user is None or user.user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return user.user
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
