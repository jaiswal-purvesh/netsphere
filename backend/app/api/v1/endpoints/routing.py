"""Phase 3 — Routing. Read/manual-entry side of the route_tables/routes
inventory populated by discovery (app/services/routing.py, called from
discovery.py's cloud sweeps and devices.py's SNMP sweep). See
app/models/routing.py for why a route belongs to exactly one of a
RouteTable (cloud) or a Device (on-prem static route).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.device import Device
from app.models.network import Network
from app.models.routing import Route, RouteTable
from app.models.user import User
from app.schemas.routing import (
    DeviceRoutesOut,
    RouteCreate,
    RouteOut,
    RouteTableCreate,
    RouteTableOut,
)

router = APIRouter(prefix="/routing", tags=["routing"])


def _route_out(r: Route) -> RouteOut:
    return RouteOut(
        id=str(r.id), route_table_id=str(r.route_table_id) if r.route_table_id else None,
        device_id=str(r.device_id) if r.device_id else None, destination_cidr=r.destination_cidr,
        target_type=r.target_type, target_ref=r.target_ref, state=r.state, external_id=r.external_id,
    )


def _route_table_out(rt: RouteTable, network: Network) -> RouteTableOut:
    routes = sorted(rt.routes, key=lambda r: r.destination_cidr)
    return RouteTableOut(
        id=str(rt.id), network_id=str(rt.network_id), network_name=network.name, network_cidr=network.cidr,
        name=rt.name, is_main=rt.is_main, source=rt.source, external_id=rt.external_id, notes=rt.notes,
        route_count=len(routes), routes=[_route_out(r) for r in routes],
    )


@router.get("/route-tables", response_model=list[RouteTableOut])
def list_route_tables(
    network_id: uuid.UUID | None = None, q: str | None = None,
    db: Session = Depends(get_db), _: User = Depends(require_permission("routing:view")),
) -> list[RouteTableOut]:
    stmt = select(RouteTable).where(RouteTable.deleted_at.is_(None))
    if network_id:
        stmt = stmt.where(RouteTable.network_id == network_id)
    if q:
        stmt = stmt.where(RouteTable.name.ilike(f"%{q}%"))
    rows = db.execute(stmt.order_by(RouteTable.name)).scalars().all()

    net_ids = {rt.network_id for rt in rows}
    networks_by_id = {n.id: n for n in db.execute(select(Network).where(Network.id.in_(net_ids))).scalars().all()} if net_ids else {}
    return [_route_table_out(rt, networks_by_id[rt.network_id]) for rt in rows if rt.network_id in networks_by_id]


@router.get("/route-tables/{route_table_id}", response_model=RouteTableOut)
def get_route_table(
    route_table_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("routing:view")),
) -> RouteTableOut:
    rt = db.get(RouteTable, route_table_id)
    if not rt or rt.deleted_at is not None:
        raise HTTPException(status_code=404, detail="route table not found")
    network = db.get(Network, rt.network_id)
    if not network:
        raise HTTPException(status_code=404, detail="route table's network no longer exists")
    return _route_table_out(rt, network)


@router.post("/route-tables", response_model=RouteTableOut, status_code=201)
def create_route_table(
    payload: RouteTableCreate, db: Session = Depends(get_db), _: User = Depends(require_permission("routing:create")),
) -> RouteTableOut:
    network = db.get(Network, uuid.UUID(payload.network_id))
    if not network:
        raise HTTPException(status_code=404, detail="network not found")
    rt = RouteTable(
        network_id=network.id, name=payload.name, is_main=payload.is_main, source="manual", notes=payload.notes,
    )
    db.add(rt)
    db.commit()
    db.refresh(rt)
    return _route_table_out(rt, network)


@router.post("/route-tables/{route_table_id}/routes", response_model=RouteOut, status_code=201)
def add_route(
    route_table_id: uuid.UUID, payload: RouteCreate,
    db: Session = Depends(get_db), _: User = Depends(require_permission("routing:create")),
) -> RouteOut:
    rt = db.get(RouteTable, route_table_id)
    if not rt or rt.deleted_at is not None:
        raise HTTPException(status_code=404, detail="route table not found")
    route = Route(
        route_table_id=rt.id, destination_cidr=payload.destination_cidr, target_type=payload.target_type,
        target_ref=payload.target_ref, state=payload.state,
    )
    db.add(route)
    db.commit()
    db.refresh(route)
    return _route_out(route)


@router.delete("/routes/{route_id}", status_code=204)
def delete_route(
    route_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("routing:delete")),
) -> None:
    route = db.get(Route, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="route not found")
    db.delete(route)
    db.commit()


@router.get("/device-routes", response_model=list[DeviceRoutesOut])
def list_device_routes(
    device_id: uuid.UUID | None = None,
    db: Session = Depends(get_db), _: User = Depends(require_permission("routing:view")),
) -> list[DeviceRoutesOut]:
    """On-prem static routes, grouped by the device that holds them —
    the other half of this phase's routing inventory, alongside cloud
    route tables above. Only devices with at least one route are
    returned (most switches have none — L2 devices don't route)."""
    stmt = select(Device).where(Device.deleted_at.is_(None))
    if device_id:
        stmt = stmt.where(Device.id == device_id)
    devices = db.execute(stmt.order_by(Device.hostname)).scalars().all()

    dev_ids = [d.id for d in devices]
    routes_by_device: dict[uuid.UUID, list[Route]] = {}
    if dev_ids:
        for r in db.execute(select(Route).where(Route.device_id.in_(dev_ids))).scalars().all():
            routes_by_device.setdefault(r.device_id, []).append(r)

    return [
        DeviceRoutesOut(
            device_id=str(d.id), hostname=d.hostname,
            routes=[_route_out(r) for r in sorted(routes_by_device[d.id], key=lambda r: r.destination_cidr)],
        )
        for d in devices
        if d.id in routes_by_device
    ]
