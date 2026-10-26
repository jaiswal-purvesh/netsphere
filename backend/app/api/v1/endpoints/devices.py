"""Device/interface inventory — the read side of Phase 2's device
discovery. Populated by POST /discovery/snmp (see discovery.py) or by
direct creation here; either way this is where the Network Inventory page
reads from.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.device import Device, Interface
from app.models.user import User
from app.schemas.devices import DeviceCreate, DeviceOut, InterfaceOut

router = APIRouter(prefix="/devices", tags=["devices"])


def _device_out(db: Session, d: Device) -> DeviceOut:
    count = db.execute(select(func.count()).select_from(Interface).where(Interface.device_id == d.id)).scalar_one()
    return DeviceOut(
        id=str(d.id), environment_id=str(d.environment_id), hostname=d.hostname, vendor=d.vendor,
        device_type=d.device_type, mgmt_ip=d.mgmt_ip, site=d.site, source=d.source, status=d.status,
        interface_count=count,
    )


@router.get("", response_model=list[DeviceOut])
def list_devices(
    site: str | None = None, q: str | None = None,
    db: Session = Depends(get_db), _: User = Depends(require_permission("inventory:view")),
) -> list[DeviceOut]:
    stmt = select(Device).where(Device.deleted_at.is_(None))
    if site:
        stmt = stmt.where(Device.site == site)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Device.hostname.ilike(like) | Device.mgmt_ip.ilike(like))
    rows = db.execute(stmt.order_by(Device.site, Device.hostname)).scalars().all()
    return [_device_out(db, d) for d in rows]


@router.post("", response_model=DeviceOut, status_code=201)
def create_device(
    payload: DeviceCreate, db: Session = Depends(get_db), _: User = Depends(require_permission("inventory:create")),
) -> DeviceOut:
    device = Device(
        environment_id=uuid.UUID(payload.environment_id), hostname=payload.hostname,
        device_type=payload.device_type, vendor=payload.vendor, mgmt_ip=payload.mgmt_ip,
        site=payload.site, notes=payload.notes, source="manual",
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return _device_out(db, device)


@router.get("/{device_id}/interfaces", response_model=list[InterfaceOut])
def list_interfaces(
    device_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("inventory:view")),
) -> list[InterfaceOut]:
    if not db.get(Device, device_id):
        raise HTTPException(status_code=404, detail="device not found")
    rows = db.execute(select(Interface).where(Interface.device_id == device_id).order_by(Interface.name)).scalars().all()
    return [
        InterfaceOut(
            id=str(i.id), device_id=str(i.device_id), name=i.name, description=i.description,
            ip_address=i.ip_address, mac_address=i.mac_address, admin_status=i.admin_status,
            oper_status=i.oper_status, speed_mbps=i.speed_mbps, vlan_id=i.vlan_id,
            subnet_id=str(i.subnet_id) if i.subnet_id else None,
        )
        for i in rows
    ]
