from __future__ import annotations

from pydantic import BaseModel


class CloudNetworkInterfaceOut(BaseModel):
    id: str
    subnet_id: str
    subnet_cidr: str
    network_id: str
    network_name: str
    name: str
    private_ip: str | None
    public_ip: str | None
    attached_to: str | None
    status: str
    security_groups: list[str]
    source: str
    external_id: str | None
    notes: str | None


class CloudNetworkInterfaceCreate(BaseModel):
    subnet_id: str
    name: str
    private_ip: str | None = None
    public_ip: str | None = None
    attached_to: str | None = None
    status: str = "in_use"
    security_groups: list[str] = []
    notes: str | None = None


class NetworkPeeringOut(BaseModel):
    id: str
    network_a_id: str
    network_a_name: str
    network_b_id: str
    network_b_name: str
    status: str
    source: str
    external_id: str | None
    notes: str | None


class NetworkPeeringCreate(BaseModel):
    network_a_id: str
    network_b_id: str
    status: str = "active"
    notes: str | None = None
