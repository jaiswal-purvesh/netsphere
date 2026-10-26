from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_permission
from app.models.network import Network, Subnet
from app.models.org import CloudAccount
from app.models.user import User
from app.schemas.ipam import (
    AllocateCreateRequest,
    AllocatePreviewRequest,
    ImportSummary,
    NetworkCreate,
    NetworkOut,
    NetworkUpdate,
    SubnetOut,
)
from app.services import ipam as ipam_service
from app.services.audit import record as audit_record
from app.services.cidr import CidrError, parse_cidr

router = APIRouter(prefix="/ipam", tags=["ipam"])


@router.get("/search")
def search(ip: str = Query(...), db: Session = Depends(get_db), _: User = Depends(require_permission("ipam:view"))) -> dict:
    try:
        return ipam_service.search_ip(db, ip)
    except ipam_service.IpamError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/overlaps")
def overlaps(db: Session = Depends(get_db), _: User = Depends(require_permission("ipam:view"))) -> dict:
    return {"conflicts": ipam_service.find_overlapping_networks(db)}


@router.get("/networks/export")
def export_networks(
    provider: str | None = None, q: str | None = None,
    db: Session = Depends(get_db), _: User = Depends(require_permission("ipam:view")),
) -> Response:
    csv_text = ipam_service.export_networks_csv(db, provider=provider, q=q)
    return Response(
        content=csv_text, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=netsphere_networks_export.csv"},
    )


@router.post("/networks/import", response_model=ImportSummary)
def import_networks(
    file: UploadFile = File(...),
    db: Session = Depends(get_db), user: User = Depends(require_permission("ipam:create")),
) -> ImportSummary:
    raw = file.file.read()
    try:
        text = raw.decode("utf-8-sig")  # tolerate a BOM from Excel-exported CSVs
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=400, detail=f"could not decode file as UTF-8: {e}") from e
    try:
        summary = ipam_service.import_networks_csv(db, text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    audit_record(
        db, user_id=user.id, action="ipam.network.import", resource_type="network",
        resource_id=None, after={"created": summary["created"], "updated": summary["updated"], "errors": summary["errors"]},
    )
    return ImportSummary(**summary)


@router.get("/networks", response_model=list[NetworkOut])
def list_networks(
    provider: str | None = None, q: str | None = None,
    db: Session = Depends(get_db), _: User = Depends(require_permission("ipam:view")),
) -> list[NetworkOut]:
    rows = ipam_service.query_networks(db, provider=provider, q=q)
    out = []
    for n in rows:
        count = db.execute(select(func.count()).select_from(Subnet).where(Subnet.network_id == n.id)).scalar_one()
        out.append(NetworkOut(
            id=str(n.id), name=n.name, cidr=n.cidr, provider=n.provider, region=n.region,
            owner_team=n.owner_team, environment_name=n.environment_name, firewall=n.firewall,
            status=n.status, subnet_count=count,
        ))
    return out


@router.post("/networks", response_model=NetworkOut, status_code=201)
def create_network(
    payload: NetworkCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("ipam:create")),
) -> NetworkOut:
    account = db.get(CloudAccount, uuid.UUID(payload.cloud_account_id))
    if not account:
        raise HTTPException(status_code=404, detail="cloud account not found")
    try:
        parsed = parse_cidr(payload.cidr)
    except CidrError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    existing = db.execute(
        select(Network).where(Network.cloud_account_id == account.id, Network.cidr == parsed.cidr),
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"{account.provider} already has a network for {parsed.cidr} under this account")

    network = Network(
        cloud_account_id=account.id,
        parent_network_id=uuid.UUID(payload.parent_network_id) if payload.parent_network_id else None,
        name=payload.name, cidr=parsed.cidr, network_addr=parsed.network, broadcast_addr=parsed.broadcast,
        prefix_len=parsed.prefix_len, provider=payload.provider, region=payload.region,
        owner_team=payload.owner_team, business_unit_name=payload.business_unit_name,
        environment_name=payload.environment_name, vrf=payload.vrf, vlan=payload.vlan,
        firewall=payload.firewall, notes=payload.notes,
    )
    db.add(network)
    db.commit()
    db.refresh(network)
    audit_record(
        db, user_id=user.id, action="ipam.network.create", resource_type="network",
        resource_id=str(network.id), after={"cidr": network.cidr, "provider": network.provider},
    )
    overlap_warnings = ipam_service.overlaps_for_cidr(db, network.cidr, exclude_network_id=network.id, provider=network.provider)
    return NetworkOut(
        id=str(network.id), name=network.name, cidr=network.cidr, provider=network.provider,
        region=network.region, owner_team=network.owner_team, environment_name=network.environment_name,
        firewall=network.firewall, status=network.status, subnet_count=0,
        overlap_warnings=overlap_warnings or None,
    )


@router.patch("/networks/{network_id}", response_model=NetworkOut)
def update_network(
    network_id: uuid.UUID, payload: NetworkUpdate,
    db: Session = Depends(get_db), user: User = Depends(require_permission("ipam:update")),
) -> NetworkOut:
    network = db.get(Network, network_id)
    if not network or network.deleted_at is not None:
        raise HTTPException(status_code=404, detail="network not found")

    before = {
        "name": network.name, "cidr": network.cidr, "firewall": network.firewall,
        "environment_name": network.environment_name,
    }

    data = payload.model_dump(exclude_unset=True)

    if "cidr" in data and data["cidr"] is not None:
        try:
            parsed = parse_cidr(data["cidr"])
        except CidrError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if parsed.cidr != network.cidr:
            dup = db.execute(
                select(Network).where(
                    Network.cloud_account_id == network.cloud_account_id,
                    Network.cidr == parsed.cidr,
                    Network.id != network.id,
                ),
            ).scalar_one_or_none()
            if dup:
                raise HTTPException(status_code=409, detail=f"a network for {parsed.cidr} already exists under this account")
        network.cidr = parsed.cidr
        network.network_addr = parsed.network
        network.broadcast_addr = parsed.broadcast
        network.prefix_len = parsed.prefix_len
        data.pop("cidr")

    for field, value in data.items():
        setattr(network, field, value)

    db.commit()
    db.refresh(network)

    audit_record(
        db, user_id=user.id, action="ipam.network.update", resource_type="network",
        resource_id=str(network.id), before=before,
        after={"name": network.name, "cidr": network.cidr, "firewall": network.firewall,
               "environment_name": network.environment_name},
    )

    count = db.execute(select(func.count()).select_from(Subnet).where(Subnet.network_id == network.id)).scalar_one()
    overlap_warnings = ipam_service.overlaps_for_cidr(db, network.cidr, exclude_network_id=network.id, provider=network.provider)
    return NetworkOut(
        id=str(network.id), name=network.name, cidr=network.cidr, provider=network.provider,
        region=network.region, owner_team=network.owner_team, environment_name=network.environment_name,
        firewall=network.firewall, status=network.status, subnet_count=count,
        overlap_warnings=overlap_warnings or None,
    )


@router.get("/networks/{network_id}/overlaps")
def network_overlaps(
    network_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("ipam:view")),
) -> dict:
    """On-demand duplicate/overlap check for one existing network — same
    classification `GET /ipam/overlaps` uses for the whole table, scoped to
    just this network's current CIDR. Lets the UI show a live alert (e.g.
    while editing a network's CIDR) without re-fetching the global conflict
    list."""
    network = db.get(Network, network_id)
    if not network or network.deleted_at is not None:
        raise HTTPException(status_code=404, detail="network not found")
    conflicts = ipam_service.overlaps_for_cidr(db, network.cidr, exclude_network_id=network.id, provider=network.provider)
    return {"network": {"id": str(network.id), "cidr": network.cidr}, "conflicts": conflicts}


@router.get("/networks/{network_id}/subnets", response_model=list[SubnetOut])
def list_subnets(
    network_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("ipam:view")),
) -> list[SubnetOut]:
    rows = db.execute(select(Subnet).where(Subnet.network_id == network_id).order_by(Subnet.network_addr)).scalars().all()
    return [
        SubnetOut(id=str(s.id), network_id=str(s.network_id), name=s.name, cidr=s.cidr,
                  availability_zone=s.availability_zone, owner_team=s.owner_team,
                  application=s.application, status=s.status)
        for s in rows
    ]


@router.get("/networks/{network_id}/free-space")
def free_space(
    network_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("ipam:view")),
) -> dict:
    try:
        return ipam_service.free_space_summary(db, network_id)
    except ipam_service.IpamError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/networks/{network_id}/allocate/preview")
def preview_allocate(
    network_id: uuid.UUID, hosts: int = Query(..., gt=0),
    db: Session = Depends(get_db), _: User = Depends(require_permission("ipam:view")),
) -> dict:
    try:
        return ipam_service.preview_allocation(db, network_id, hosts)
    except ipam_service.IpamError as e:
        raise HTTPException(status_code=409, detail={"message": str(e), "free": e.free}) from e


@router.post("/networks/{network_id}/allocate", response_model=SubnetOut, status_code=201)
def allocate(
    network_id: uuid.UUID, payload: AllocateCreateRequest,
    db: Session = Depends(get_db), user: User = Depends(require_permission("ipam:create")),
) -> SubnetOut:
    try:
        subnet = ipam_service.allocate_subnet(
            db, network_id, payload.hosts, name=payload.name, availability_zone=payload.availability_zone,
            owner_team=payload.owner_team, application=payload.application,
        )
    except ipam_service.IpamError as e:
        raise HTTPException(status_code=409, detail={"message": str(e), "free": e.free}) from e
    audit_record(
        db, user_id=user.id, action="ipam.subnet.allocate", resource_type="subnet",
        resource_id=str(subnet.id), after={"cidr": subnet.cidr, "network_id": str(network_id)},
    )
    return SubnetOut(
        id=str(subnet.id), network_id=str(subnet.network_id), name=subnet.name, cidr=subnet.cidr,
        availability_zone=subnet.availability_zone, owner_team=subnet.owner_team,
        application=subnet.application, status=subnet.status,
    )
