from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator

from app.models.cloud_integration import CLOUD_VENDORS


class CloudIntegrationCreate(BaseModel):
    vendor: str
    name: str
    account_identifier: str
    region_default: str | None = None
    credentials: dict[str, Any]
    notes: str = ""
    is_active: bool = True

    @field_validator("vendor")
    @classmethod
    def _vendor_valid(cls, v: str) -> str:
        if v not in CLOUD_VENDORS:
            raise ValueError(f"vendor must be one of {CLOUD_VENDORS}")
        return v


class CloudIntegrationUpdate(BaseModel):
    """Same shape as create, everything optional. `credentials` (when
    given) fully replaces the stored credential set — omit it to keep the
    existing one, same convention as FirewallIntegrationUpdate's `secret`."""

    name: str | None = None
    region_default: str | None = None
    credentials: dict[str, Any] | None = None
    notes: str | None = None
    is_active: bool | None = None


class CloudIntegrationOut(BaseModel):
    id: str
    vendor: str
    name: str
    account_identifier: str
    region_default: str | None
    has_credentials: bool
    credential_summary: str
    is_active: bool
    notes: str
    last_tested_at: datetime | None
    last_test_status: str | None
    last_test_message: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def _stringify(cls, v):
        return str(v)


class CloudIntegrationTestResult(BaseModel):
    ok: bool
    message: str
    tested_at: datetime
