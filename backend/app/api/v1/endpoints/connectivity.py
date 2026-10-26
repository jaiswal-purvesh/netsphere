"""Phase 8 — Connectivity. Read/manual-entry side of the
circuits/bgp_sessions/connectivity_links/vpn_connections inventory
populated by discovery (app/services/connectivity.py, called from
discovery.py's cloud sweeps and devices.py's SNMP sweep). See
app/models/connectivity.py for why a circuit is owned by exactly one of a
CloudAccount or a Device.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.connectivity import BgpSession, Circuit, ConnectivityLink, VpnConnection
from app.models.device import Device
from app.models.network import Network
from app.models.org import CloudAccount
from app.models.user import User
from app.schemas.connectivity import (
    BgpSessionOut,
    CircuitCreate,
    CircuitOut,
    ConnectivityLinkOut,
    VpnConnectionCreate,
    VpnConnectionOut,
)

router = APIRouter(prefix="/connectivity", tags=["connectivity"])


def _bgp_out(s: BgpSession) -> BgpSessionOut:
    return BgpSessionOut(
        id=str(s.id), circuit_id=str(s.circuit_id), local_asn=s.local_asn, peer_asn=s.peer_asn,
        local_ip=s.local_ip, peer_ip=s.peer_ip, state=s.state, source=s.source, external_id=s.external_id,
    )


def _link_out(link: ConnectivityLink, network: Network) -> ConnectivityLinkOut:
    return ConnectivityLinkOut(id=str(link.id), network_id=str(network.id), network_name=network.name, status=link.status, source=link.source)


def _circuit_out(
    c: Circuit, cloud_accounts_by_id: dict[uuid.UUID, CloudAccount], devices_by_id: dict[uuid.UUID, Device],
    networks_by_id: dict[uuid.UUID, Network],
) -> CircuitOut | None:
    if c.cloud_account_id is not None:
        account = cloud_accounts_by_id.get(c.cloud_account_id)
        if not account:
            return None
        owner_type, owner_id, owner_label = "cloud_account", str(account.id), f"{account.provider}/{account.account_identifier}"
    else:
        device = devices_by_id.get(c.device_id)
        if not device:
            return None
        owner_type, owner_id, owner_label = "device", str(device.id), device.hostname

    links = [
        _link_out(link, networks_by_id[link.network_id])
        for link in c.links
        if link.deleted_at is None and link.network_id in networks_by_id
    ]
    return CircuitOut(
        id=str(c.id), owner_type=owner_type, owner_id=owner_id, owner_label=owner_label, circuit_type=c.circuit_type,
        name=c.name, vrf=c.vrf, bandwidth_mbps=c.bandwidth_mbps, location=c.location, status=c.status,
        source=c.source, external_id=c.external_id, notes=c.notes,
        bgp_sessions=[_bgp_out(s) for s in c.bgp_sessions], links=links,
    )


def _vpn_out(v: VpnConnection, networks_by_id: dict[uuid.UUID, Network], devices_by_id: dict[uuid.UUID, Device]) -> VpnConnectionOut:
    network = networks_by_id.get(v.network_id) if v.network_id else None
    device = devices_by_id.get(v.device_id) if v.device_id else None
    return VpnConnectionOut(
        id=str(v.id), network_id=str(v.network_id) if v.network_id else None,
        network_name=network.name if network else None,
        device_id=str(v.device_id) if v.device_id else None,
        device_hostname=device.hostname if device else None,
        peer_ip=v.peer_ip, status=v.status, source=v.source, external_id=v.external_id, notes=v.notes,
    )


@router.get("/circuits", response_model=list[CircuitOut])
def list_circuits(
    circuit_type: str | None = None, q: str | None = None,
    db: Session = Depends(get_db), _: User = Depends(require_permission("connectivity:view")),
) -> list[CircuitOut]:
    stmt = select(Circuit).where(Circuit.deleted_at.is_(None))
    if circuit_type:
        stmt = stmt.where(Circuit.circuit_type == circuit_type)
    if q:
        stmt = stmt.where(Circuit.name.ilike(f"%{q}%"))
    rows = db.execute(stmt.order_by(Circuit.name)).scalars().all()

    account_ids = {c.cloud_account_id for c in rows if c.cloud_account_id}
    device_ids = {c.device_id for c in rows if c.device_id}
    accounts_by_id = {a.id: a for a in db.execute(select(CloudAccount).where(CloudAccount.id.in_(account_ids))).scalars().all()} if account_ids else {}
    devices_by_id = {d.id: d for d in db.execute(select(Device).where(Device.id.in_(device_ids))).scalars().all()} if device_ids else {}

    link_network_ids = {link.network_id for c in rows for link in c.links if link.deleted_at is None}
    networks_by_id = {n.id: n for n in db.execute(select(Network).where(Network.id.in_(link_network_ids))).scalars().all()} if link_network_ids else {}

    out = [_circuit_out(c, accounts_by_id, devices_by_id, networks_by_id) for c in rows]
    return [c for c in out if c is not None]


@router.get("/circuits/{circuit_id}", response_model=CircuitOut)
def get_circuit(
    circuit_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("connectivity:view")),
) -> CircuitOut:
    c = db.get(Circuit, circuit_id)
    if not c or c.deleted_at is not None:
        raise HTTPException(status_code=404, detail="circuit not found")
    accounts_by_id = {}
    devices_by_id = {}
    if c.cloud_account_id:
        account = db.get(CloudAccount, c.cloud_account_id)
        if account:
            accounts_by_id[account.id] = account
    if c.device_id:
        device = db.get(Device, c.device_id)
        if device:
            devices_by_id[device.id] = device
    link_network_ids = {link.network_id for link in c.links if link.deleted_at is None}
    networks_by_id = {n.id: n for n in db.execute(select(Network).where(Network.id.in_(link_network_ids))).scalars().all()} if link_network_ids else {}
    out = _circuit_out(c, accounts_by_id, devices_by_id, networks_by_id)
    if out is None:
        raise HTTPException(status_code=404, detail="circuit's owner no longer exists")
    return out


@router.post("/circuits", response_model=CircuitOut, status_code=201)
def create_circuit(
    payload: CircuitCreate, db: Session = Depends(get_db), _: User = Depends(require_permission("connectivity:create")),
) -> CircuitOut:
    if payload.owner_type not in ("cloud_account", "device"):
        raise HTTPException(status_code=422, detail="owner_type must be 'cloud_account' or 'device'")
    owner_uuid = uuid.UUID(payload.owner_id)
    kwargs = {}
    accounts_by_id: dict[uuid.UUID, CloudAccount] = {}
    devices_by_id: dict[uuid.UUID, Device] = {}
    if payload.owner_type == "cloud_account":
        account = db.get(CloudAccount, owner_uuid)
        if not account:
            raise HTTPException(status_code=404, detail="cloud account not found")
        kwargs["cloud_account_id"] = owner_uuid
        accounts_by_id[account.id] = account
    else:
        device = db.get(Device, owner_uuid)
        if not device:
            raise HTTPException(status_code=404, detail="device not found")
        kwargs["device_id"] = owner_uuid
        devices_by_id[device.id] = device

    circuit = Circuit(
        circuit_type=payload.circuit_type, name=payload.name, vrf=payload.vrf, bandwidth_mbps=payload.bandwidth_mbps,
        location=payload.location, status=payload.status, source="manual", notes=payload.notes, **kwargs,
    )
    db.add(circuit)
    db.commit()
    db.refresh(circuit)
    return _circuit_out(circuit, accounts_by_id, devices_by_id, {})


@router.delete("/circuits/{circuit_id}", status_code=204)
def delete_circuit(
    circuit_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("connectivity:delete")),
) -> None:
    circuit = db.get(Circuit, circuit_id)
    if not circuit or circuit.deleted_at is not None:
        raise HTTPException(status_code=404, detail="circuit not found")
    circuit.deleted_at = datetime.now(timezone.utc)
    db.commit()


@router.get("/vpn-connections", response_model=list[VpnConnectionOut])
def list_vpn_connections(
    db: Session = Depends(get_db), _: User = Depends(require_permission("connectivity:view")),
) -> list[VpnConnectionOut]:
    rows = db.execute(select(VpnConnection).where(VpnConnection.deleted_at.is_(None))).scalars().all()
    network_ids = {v.network_id for v in rows if v.network_id}
    device_ids = {v.device_id for v in rows if v.device_id}
    networks_by_id = {n.id: n for n in db.execute(select(Network).where(Network.id.in_(network_ids))).scalars().all()} if network_ids else {}
    devices_by_id = {d.id: d for d in db.execute(select(Device).where(Device.id.in_(device_ids))).scalars().all()} if device_ids else {}
    return [_vpn_out(v, networks_by_id, devices_by_id) for v in rows]


@router.post("/vpn-connections", response_model=VpnConnectionOut, status_code=201)
def create_vpn_connection(
    payload: VpnConnectionCreate, db: Session = Depends(get_db), _: User = Depends(require_permission("connectivity:create")),
) -> VpnConnectionOut:
    has_network = bool(payload.network_id)
    has_device = bool(payload.device_id)
    if has_network == has_device:
        raise HTTPException(status_code=422, detail="exactly one of network_id or device_id is required")

    networks_by_id: dict[uuid.UUID, Network] = {}
    devices_by_id: dict[uuid.UUID, Device] = {}
    kwargs = {}
    if has_network:
        network = db.get(Network, uuid.UUID(payload.network_id))
        if not network:
            raise HTTPException(status_code=404, detail="network not found")
        kwargs["network_id"] = network.id
        networks_by_id[network.id] = network
    else:
        device = db.get(Device, uuid.UUID(payload.device_id))
        if not device:
            raise HTTPException(status_code=404, detail="device not found")
        kwargs["device_id"] = device.id
        devices_by_id[device.id] = device

    vpn = VpnConnection(peer_ip=payload.peer_ip, status=payload.status, source="manual", notes=payload.notes, **kwargs)
    db.add(vpn)
    db.commit()
    db.refresh(vpn)
    return _vpn_out(vpn, networks_by_id, devices_by_id)


@router.delete("/vpn-connections/{vpn_id}", status_code=204)
def delete_vpn_connection(
    vpn_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("connectivity:delete")),
) -> None:
    vpn = db.get(VpnConnection, vpn_id)
    if not vpn or vpn.deleted_at is not None:
        raise HTTPException(status_code=404, detail="vpn connection not found")
    vpn.deleted_at = datetime.now(timezone.utc)
    db.commit()
