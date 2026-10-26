from __future__ import annotations

from pydantic import BaseModel, EmailStr


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    is_active: bool
    roles: list[str]

    model_config = {"from_attributes": True}
