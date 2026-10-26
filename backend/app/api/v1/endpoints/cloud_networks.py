"""Phase 3 — Cloud Networks. Read/manual-entry side of the
cloud_network_interfaces/network_peerings inventory populated by discovery
(app/services/cloud_networks.py, called from discovery.py's cloud sweeps).
See app/models/cloud_networks.py for the peering canonical-ordering and
self-peering-rejection rules.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.cloud_networks import CloudNetworkInterface, NetworkPeering
from app.models.network import Network, Subnet
from app.models.user import User
from app.schemas.cloud_networks import (
    CloudNetworkInterfaceCreate,
    CloudNetworkInterfaceOut,
    NetworkPeeringCreate,
    NetworkPeeringOut,
)

router = APIRouter(prefix="/cloud-networks", tags=["cloud-networks"])


def _interface_out(iface: CloudNetworkInterface, subnet: Subnet, network: Network) -> CloudNetworkInterfaceOut:
    return CloudNetworkInterfaceOut(
        id=str(iface.id), subnet_id=str(iface.subnet_id), subnet_cidr=subnet.cidr,
        network_id=str(network.id), network_name=network.name,
        name=iface.name, private_ip=iface.private_ip, public_ip=iface.public_ip,
        attached_to=iface.attached_to, status=iface.status, security_groups=list(iface.security_groups or []),
        source=iface.source, external_id=iface.external_id, notes=iface.notes,
    )


def _peering_out(p: NetworkPeering, network_a: Network, network_b: Network) -> NetworkPeeringOut:
    return NetworkPeeringOut(
        id=str(p.id), network_a_id=str(p.network_a_id), network_a_name=network_a.name,
        network_b_id=str(p.network_b_id), network_b_name=network_b.name,
        status=p.status, source=p.source, external_id=p.external_id, notes=p.notes,
    )


@router.get("/interfaces", response_model=list[CloudNetworkInterfaceOut])
def list_interfaces(
    network_id: uuid.UUID | None = None, subnet_id: uuid.UUID | None = None, q: str | None = None,
    db: Session = Depends(get_db), _: User = Depends(require_permission("cloud_networks:view")),
) -> list[CloudNetworkInterfaceOut]:
    stmt = select(CloudNetworkInterface).where(CloudNetworkInterface.deleted_at.is_(None))
    if subnet_id:
        stmt = stmt.where(CloudNetworkInterface.subnet_id == subnet_id)
    if q:
        stmt = stmt.where(CloudNetworkInterface.name.ilike(f"%{q}%"))
    rows = db.execute(stmt.order_by(CloudNetworkInterface.name)).scalars().all()

    subnet_ids = {i.subnet_id for i in rows}
    subnets_by_id = {s.id: s for s in db.execute(select(Subnet).where(Subnet.id.in_(subnet_ids))).scalars().all()} if subnet_ids else {}
    net_ids = {s.network_id for s in subnets_by_id.values()}
    networks_by_id = {n.id: n for n in db.execute(select(Network).where(Network.id.in_(net_ids))).scalars().all()} if net_ids else {}

    out = []
    for iface in rows:
        subnet = subnets_by_id.get(iface.subnet_id)
        if not subnet:
            continue
        network = networks_by_id.get(subnet.network_id)
        if not network:
            continue
        if network_id and network.id != network_id:
            continue
        out.append(_interface_out(iface, subnet, network))
    return out


@router.post("/interfaces", response_model=CloudNetworkInterfaceOut, status_code=201)
def create_interface(
    payload: CloudNetworkInterfaceCreate, db: Session = Depends(get_db),
    _: User = Depends(require_permission("cloud_networks:create")),
) -> CloudNetworkInterfaceOut:
    subnet = db.get(Subnet, uuid.UUID(payload.subnet_id))
    if not subnet:
        raise HTTPException(status_code=404, detail="subnet not found")
    network = db.get(Network, subnet.network_id)
    if not network:
        raise HTTPException(status_code=404, detail="subnet's network no longer exists")
    iface = CloudNetworkInterface(
        subnet_id=subnet.id, name=payload.name, private_ip=payload.private_ip, public_ip=payload.public_ip,
        attached_to=payload.attached_to, status=payload.status, security_groups=list(payload.security_groups),
        source="manual", notes=payload.notes,
    )
    db.add(iface)
    db.commit()
    db.refresh(iface)
    return _interface_out(iface, subnet, network)


@router.delete("/interfaces/{interface_id}", status_code=204)
def delete_interface(
    interface_id: uuid.UUID, db: Session = Depends(get_db),
    _: User = Depends(require_permission("cloud_networks:delete")),
) -> None:
    iface = db.get(CloudNetworkInterface, interface_id)
    if not iface or iface.deleted_at is not None:
        raise HTTPException(status_code=404, detail="interface not found")
    from datetime import datetime, timezone
    iface.deleted_at = datetime.now(timezone.utc)
    db.commit()


@router.get("/peerings", response_model=list[NetworkPeeringOut])
def list_peerings(
    network_id: uuid.UUID | None = None,
    db: Session = Depends(get_db), _: User = Depends(require_permission("cloud_networks:view")),
) -> list[NetworkPeeringOut]:
    stmt = select(NetworkPeering).where(NetworkPeering.deleted_at.is_(None))
    if network_id:
        stmt = stmt.where(
            (NetworkPeering.network_a_id == network_id) | (NetworkPeering.network_b_id == network_id),
        )
    rows = db.execute(stmt).scalars().all()

    net_ids = {p.network_a_id for p in rows} | {p.network_b_id for p in rows}
    networks_by_id = {n.id: n for n in db.execute(select(Network).where(Network.id.in_(net_ids))).scalars().all()} if net_ids else {}
    return [
        _peering_out(p, networks_by_id[p.network_a_id], networks_by_id[p.network_b_id])
        for p in rows
        if p.network_a_id in networks_by_id and p.network_b_id in networks_by_id
    ]


@router.post("/peerings", response_model=NetworkPeeringOut, status_code=201)
def create_peering(
    payload: NetworkPeeringCreate, db: Session = Depends(get_db),
    _: User = Depends(require_permission("cloud_networks:create")),
) -> NetworkPeeringOut:
    a_uuid, b_uuid = uuid.UUID(payload.network_a_id), uuid.UUID(payload.network_b_id)
    if a_uuid == b_uuid:
        raise HTTPException(status_code=422, detail="a network cannot peer with itself")
    network_a = db.get(Network, a_uuid)
    network_b = db.get(Network, b_uuid)
    if not network_a or not network_b:
        raise HTTPException(status_code=404, detail="one or both networks not found")

    a_id, b_id = (a_uuid, b_uuid) if str(a_uuid) < str(b_uuid) else (b_uuid, a_uuid)
    existing = db.execute(
        select(NetworkPeering).where(NetworkPeering.network_a_id == a_id, NetworkPeering.network_b_id == b_id),
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="a peering between these networks already exists")

    peering = NetworkPeering(network_a_id=a_id, network_b_id=b_id, status=payload.status, source="manual", notes=payload.notes)
    db.add(peering)
    db.commit()
    db.refresh(peering)
    networks_by_id = {network_a.id: network_a, network_b.id: network_b}
    return _peering_out(peering, networks_by_id[peering.network_a_id], networks_by_id[peering.network_b_id])


@router.delete("/peerings/{peering_id}", status_code=204)
def delete_peering(
    peering_id: uuid.UUID, db: Session = Depends(get_db),
    _: User = Depends(require_permission("cloud_networks:delete")),
) -> None:
    peering = db.get(NetworkPeering, peering_id)
    if not peering or peering.deleted_at is not None:
        raise HTTPException(status_code=404, detail="peering not found")
    from datetime import datetime, timezone
    peering.deleted_at = datetime.now(timezone.utc)
    db.commit()
