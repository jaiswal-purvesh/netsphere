from __future__ import annotations

from pydantic import BaseModel


class InterfaceOut(BaseModel):
    id: str
    device_id: str
    name: str
    description: str | None
    ip_address: str | None
    mac_address: str | None
    admin_status: str
    oper_status: str
    speed_mbps: int | None
    vlan_id: int | None
    subnet_id: str | None


class DeviceOut(BaseModel):
    id: str
    environment_id: str
    hostname: str
    vendor: str | None
    device_type: str
    mgmt_ip: str | None
    site: str | None
    source: str
    status: str
    interface_count: int


class DeviceCreate(BaseModel):
    environment_id: str
    hostname: str
    device_type: str = "other"
    vendor: str | None = None
    mgmt_ip: str | None = None
    site: str | None = None
    notes: str | None = None
