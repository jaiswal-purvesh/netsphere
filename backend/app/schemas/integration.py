from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator

from app.models.integration import INTEGRATION_AUTH_TYPES, INTEGRATION_VENDORS


class IntegrationCreate(BaseModel):
    vendor: str
    name: str
    host: str | None = None
    port: int = 443
    verify_tls: bool = True
    auth_type: str | None = None
    username: str | None = None
    secret: str | None = None  # plaintext in the request body only; never stored or echoed back
    device_group: str | None = None
    serial: str | None = None
    parent_id: str | None = None
    notes: str = ""
    is_active: bool = True

    @field_validator("vendor")
    @classmethod
    def _vendor_valid(cls, v: str) -> str:
        if v not in INTEGRATION_VENDORS:
            raise ValueError(f"vendor must be one of {INTEGRATION_VENDORS}")
        return v

    @field_validator("auth_type")
    @classmethod
    def _auth_type_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in INTEGRATION_AUTH_TYPES:
            raise ValueError(f"auth_type must be one of {INTEGRATION_AUTH_TYPES}")
        return v

    @model_validator(mode="after")
    def _shape_by_vendor(self) -> "IntegrationCreate":
        if self.vendor == "ngfw":
            if not self.parent_id:
                raise ValueError("ngfw entries must set parent_id to the Panorama managing them")
        else:
            if not self.host:
                raise ValueError(f"{self.vendor} requires a host")
            if not self.auth_type:
                raise ValueError(f"{self.vendor} requires auth_type")
        return self


class IntegrationUpdate(BaseModel):
    """Same shape as create, everything optional — only fields supplied are
    changed. `secret` is write-only: omit it to keep the existing one."""

    name: str | None = None
    host: str | None = None
    port: int | None = None
    verify_tls: bool | None = None
    auth_type: str | None = None
    username: str | None = None
    secret: str | None = None
    device_group: str | None = None
    serial: str | None = None
    notes: str | None = None
    is_active: bool | None = None

    @field_validator("auth_type")
    @classmethod
    def _auth_type_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in INTEGRATION_AUTH_TYPES:
            raise ValueError(f"auth_type must be one of {INTEGRATION_AUTH_TYPES}")
        return v


class IntegrationOut(BaseModel):
    id: str
    vendor: str
    name: str
    host: str | None
    port: int
    verify_tls: bool
    auth_type: str | None
    username: str | None
    has_secret: bool
    secret_last4: str
    device_group: str | None
    serial: str | None
    parent_id: str | None
    is_active: bool
    notes: str
    last_tested_at: datetime | None
    last_test_status: str | None
    last_test_message: str
    created_at: datetime
    updated_at: datetime
    children: list["IntegrationOut"] = []

    model_config = {"from_attributes": True}

    @field_validator("id", "parent_id", mode="before")
    @classmethod
    def _stringify(cls, v):
        return str(v) if v is not None else None


class IntegrationTestResult(BaseModel):
    ok: bool
    message: str
    tested_at: datetime
