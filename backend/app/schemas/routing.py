from __future__ import annotations

from pydantic import BaseModel


class RouteOut(BaseModel):
    id: str
    route_table_id: str | None
    device_id: str | None
    destination_cidr: str
    target_type: str
    target_ref: str | None
    state: str
    external_id: str | None


class RouteCreate(BaseModel):
    destination_cidr: str
    target_type: str
    target_ref: str | None = None
    state: str = "active"


class RouteTableOut(BaseModel):
    id: str
    network_id: str
    network_name: str
    network_cidr: str
    name: str
    is_main: bool
    source: str
    external_id: str | None
    notes: str | None
    route_count: int
    routes: list[RouteOut]


class RouteTableCreate(BaseModel):
    network_id: str
    name: str
    is_main: bool = False
    notes: str | None = None


class DeviceRoutesOut(BaseModel):
    device_id: str
    hostname: str
    routes: list[RouteOut]
