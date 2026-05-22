from fastapi import Depends, HTTPException, status

from app.core.auth import AuthContext, get_current_user


def user_is_admin(user: AuthContext) -> bool:
    return str(user.role or "").lower() == "admin"


def require_admin(user: AuthContext = Depends(get_current_user)) -> AuthContext:
    if not user_is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return user


def require_staff_or_admin(user: AuthContext = Depends(get_current_user)) -> AuthContext:
    role = str(user.role or "").lower()
    if role not in {"admin", "staff"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return user