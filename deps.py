"""Authentication and authorisation dependencies."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .rbac import role_allows
from .security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

DbSession = Annotated[Session, Depends(get_db)]


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: DbSession,
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    payload = decode_access_token(credentials.credentials)
    if not payload or not payload.get("sub"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.scalar(select(User).where(User.email == payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is not active")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require(permission: str):
    def dependency(user: CurrentUser) -> User:
        permissions = list(user.role.permissions) if user.role else []
        if not role_allows(permissions, permission):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Role '{user.role.name}' lacks the '{permission}' permission",
            )
        return user

    return dependency


def has_permission(user: User, permission: str) -> bool:
    return role_allows(list(user.role.permissions) if user.role else [], permission)


def require_any(*permissions: str):
    def dependency(user: CurrentUser) -> User:
        if not any(has_permission(user, permission) for permission in permissions):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Requires one of: {', '.join(permissions)}",
            )
        return user

    return dependency
