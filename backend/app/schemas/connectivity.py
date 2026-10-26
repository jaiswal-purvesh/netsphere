from __future__ import annotations

from pydantic import BaseModel


class BgpSessionOut(BaseModel):
    id: str
    circuit_id: str
    local_asn: int
    peer_asn: int
    local_ip: str | None
    peer_ip: str | None
    state: str
    source: str
    external_id: str | None


class ConnectivityLinkOut(BaseModel):
    id: str
    network_id: str
    network_name: str
    status: str
    source: str


class CircuitOut(BaseModel):
    id: str
    owner_type: str  # cloud_account|device
    owner_id: str
    owner_label: str  # provider/account_identifier, or device hostname
    circuit_type: str
    name: str
    vrf: str | None
    bandwidth_mbps: int | None
    location: str | None
    status: str
    source: str
    external_id: str | None
    notes: str | None
    bgp_sessions: list[BgpSessionOut]
    links: list[ConnectivityLinkOut]


class CircuitCreate(BaseModel):
    owner_type: str  # cloud_account|device
    owner_id: str
    circuit_type: str
    name: str
    vrf: str | None = None
    bandwidth_mbps: int | None = None
    location: str | None = None
    status: str = "active"
    notes: str | None = None


class VpnConnectionOut(BaseModel):
    id: str
    network_id: str | None
    network_name: str | None
    device_id: str | None
    device_hostname: str | None
    peer_ip: str | None
    status: str
    source: str
    external_id: str | None
    notes: str | None


class VpnConnectionCreate(BaseModel):
    network_id: str | None = None
    device_id: str | None = None
    peer_ip: str | None = None
    status: str = "up"
    notes: str | None = None
