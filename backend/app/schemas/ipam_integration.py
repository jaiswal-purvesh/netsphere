from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class IpamIntegrationCreate(BaseModel):
    vendor: str = "tcpwave"
    name: str
    host: str
    port: int = 7443
    verify_tls: bool = True
    auth_mode: str = "token"
    token: str | None = None  # required when auth_mode == "token"
    organization_name: str | None = None
    cloud_account_id: str | None = None
    notes: str = ""


class IpamIntegrationUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    verify_tls: bool | None = None
    auth_mode: str | None = None
    token: str | None = None  # omit to keep the existing token
    organization_name: str | None = None
    cloud_account_id: str | None = None
    is_active: bool | None = None
    notes: str | None = None


class IpamIntegrationOut(BaseModel):
    id: str
    vendor: str
    name: str
    host: str | None
    port: int
    verify_tls: bool
    auth_mode: str
    has_token: bool
    token_last4: str
    organization_name: str | None
    cloud_account_id: str | None
    is_active: bool
    notes: str
    last_tested_at: datetime | None
    last_test_status: str | None
    last_test_message: str
    created_at: datetime
    updated_at: datetime


class IpamIntegrationTestResult(BaseModel):
    ok: bool
    message: str
    tested_at: datetime


class IpamSyncRunOut(BaseModel):
    id: str
    integration_id: str
    status: str
    error_message: str
    networks_seen: int
    networks_created: int
    networks_updated: int
    subnets_seen: int
    subnets_created: int
    subnets_updated: int
    ips_seen: int
    ips_created: int
    ips_updated: int
    created_at: datetime
    finished_at: datetime | None


class IPAddressOut(BaseModel):
    id: str
    subnet_id: str
    ip_address: str
    status: str
    hostname: str | None
    mac_address: str | None
    assigned_to: str | None
    external_source: str | None
    last_synced_at: datetime | None
