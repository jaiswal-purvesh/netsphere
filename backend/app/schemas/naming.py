from __future__ import annotations

from pydantic import BaseModel, Field


class NameGenerateIn(BaseModel):
    component: str
    provider: str | None = None
    env: str | None = None
    region: str | None = None
    site: str | None = None
    app: str | None = None
    role: str | None = None
    kind: str | None = None
    seq: int | None = Field(default=None, ge=1, le=99)


class NameCollision(BaseModel):
    name: str
    where: str


class NameGenerateOut(BaseModel):
    name: str | None
    pattern: str
    parts: dict[str, str]
    issues: list[str]
    unique: bool | None
    collisions: list[NameCollision]
    seq: int | None
    alternatives: list[str]


class NameValidateIn(BaseModel):
    name: str
    component: str
    provider: str | None = None


class NameValidateOut(BaseModel):
    compliant: bool
    issues: list[str]
    parts: dict[str, str]
    pattern: str
