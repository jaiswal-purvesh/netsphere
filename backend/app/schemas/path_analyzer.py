from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PathSimulateRequest(BaseModel):
    source: str
    destination: str
    protocol: str = "tcp"
    port: int | None = None
    port_low: int | None = None
    port_high: int | None = None


class HopOut(BaseModel):
    firewall: str
    integration_id: str | None
    verdict: str
    covering_rule: str | None
    blocking_rule: str | None
    notes: list[str]
    error: str | None


class NetworkRefOut(BaseModel):
    id: str
    name: str
    cidr: str


class PathSimulateResponse(BaseModel):
    id: str
    source: str
    destination: str
    protocol: str
    port_low: int
    port_high: int
    source_network: NetworkRefOut | None
    destination_network: NetworkRefOut | None
    hops: list[HopOut]
    overall_verdict: str
    notes: list[str]
    created_at: datetime
