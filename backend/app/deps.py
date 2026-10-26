from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    if not token:
        raise unauthorized
    email = decode_access_token(token)
    if not email:
        raise unauthorized
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active:
        raise unauthorized
    return user


def require_permission(code: str):
    """FastAPI dependency factory: `Depends(require_permission("ipam:create"))`.
    SUPER_ADMIN always passes. Otherwise the user must hold a role whose
    permission set includes `code`.
    """

    def _check(user: User = Depends(get_current_user)) -> User:
        role_names = {r.name for r in user.roles}
        if "SUPER_ADMIN" in role_names:
            return user
        granted = {p.code for r in user.roles for p in r.permissions}
        if code not in granted:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"missing permission: {code}")
        return user

    return _check


def require_any_permission(*codes: str):
    """FastAPI dependency factory for a union check:
    `Depends(require_any_permission("automation:view", "firewall:view"))`
    passes if the user holds *any one* of the listed permissions (or is
    SUPER_ADMIN) — unlike `require_permission`, which requires the single
    code given.

    Added for Phase 7's unified Automation hub (`/automation/changes`),
    which surfaces both POA runs (`automation:*`) and fwauto firewall/cloud
    policy intents (`firewall:*`): a user holding either resource area's
    `:view` grant should see their own slice of the combined feed, rather
    than being locked out because they don't hold both. This is a real
    authorization relaxation (OR, not AND) — used only where a combined
    read view genuinely spans two resource areas, not as a way to loosen
    an existing single-resource-area check.
    """

    def _check(user: User = Depends(get_current_user)) -> User:
        role_names = {r.name for r in user.roles}
        if "SUPER_ADMIN" in role_names:
            return user
        granted = {p.code for r in user.roles for p in r.permissions}
        if not granted.intersection(codes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing permission: requires any of {', '.join(codes)}",
            )
        return user

    return _check
