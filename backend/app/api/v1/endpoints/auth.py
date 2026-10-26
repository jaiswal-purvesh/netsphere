from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.auth import TokenResponse, UserOut
from app.security import create_access_token, verify_password

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == form.username).first()
    if not user or not user.is_active or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="incorrect email or password")
    return TokenResponse(access_token=create_access_token(user.email))


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(
        id=str(user.id), email=user.email, full_name=user.full_name,
        is_active=user.is_active, roles=[r.name for r in user.roles],
    )
