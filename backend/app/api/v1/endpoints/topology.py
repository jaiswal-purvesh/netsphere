"""Topology — Phase 4's "network graph, relationships" (docs/ROADMAP.md),
read directly off the org hierarchy and IPAM/inventory data that Phases 1-2
already made the source of truth for, rather than a separately-maintained
topology store that could drift from it.

Tree: Organization -> BusinessUnit -> Environment -> CloudAccount ->
Network -> Subnet, with Device rows (Phase 2 inventory) hung off their
Environment directly (a device isn't modeled as belonging to one cloud
account/network). Cross-cutting relationships, not part of that tree, are
returned as extra edges:

  - device --attached_via(interface name)--> subnet, when an interface's
    resolved subnet_id (app/services/devices.py) points at a subnet in
    scope.
  - network --protected_by--> firewall, from the free-text `Network.firewall`
    field. Firewall nodes are deduplicated by name across networks. When a
    Device row of device_type "firewall" has a matching hostname, its id is
    attached as `device_id` in the firewall node's meta so a UI can link
    them — deliberately not merged into one node, since a name match isn't
    proof they're the same record.

Returns a flat {nodes, edges} shape rather than a nested tree so the
frontend can lay it out however it wants (indented tree, layered diagram,
force graph) without the API baking in a rendering choice.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.device import Device, Interface
from app.models.network import Network, Subnet
from app.models.org import BusinessUnit, CloudAccount, Environment, Organization
from app.models.user import User

router = APIRouter(prefix="/topology", tags=["topology"])


def _node(id_: str, type_: str, label: str, parent_id: str | None, **meta) -> dict:
    return {"id": id_, "type": type_, "label": label, "parent_id": parent_id, "meta": meta}


@router.get("")
def get_topology(
    environment_id: uuid.UUID | None = None,
    db: Session = Depends(get_db), _: User = Depends(require_permission("topology:view")),
) -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []

    env_stmt = select(Environment)
    if environment_id:
        env_stmt = env_stmt.where(Environment.id == environment_id)
    envs = db.execute(env_stmt).scalars().all()
    env_ids = {e.id for e in envs}
    bu_ids = {e.business_unit_id for e in envs}

    bus = db.execute(select(BusinessUnit).where(BusinessUnit.id.in_(bu_ids))).scalars().all() if bu_ids else []
    org_ids = {bu.organization_id for bu in bus}
    orgs = db.execute(select(Organization).where(Organization.id.in_(org_ids))).scalars().all() if org_ids else []

    for org in orgs:
        nodes.append(_node(f"org:{org.id}", "organization", org.name, None))
    for bu in bus:
        nodes.append(_node(f"bu:{bu.id}", "business_unit", bu.name, f"org:{bu.organization_id}"))
    for env in envs:
        nodes.append(_node(f"env:{env.id}", "environment", env.name, f"bu:{env.business_unit_id}"))

    accounts = (
        db.execute(select(CloudAccount).where(CloudAccount.environment_id.in_(env_ids))).scalars().all()
        if env_ids else []
    )
    account_ids = {a.id for a in accounts}
    for acct in accounts:
        nodes.append(_node(
            f"acct:{acct.id}", "cloud_account", f"{acct.provider}:{acct.account_identifier}",
            f"env:{acct.environment_id}", provider=acct.provider, status=acct.status,
        ))

    networks = (
        db.execute(select(Network).where(Network.deleted_at.is_(None), Network.cloud_account_id.in_(account_ids))).scalars().all()
        if account_ids else []
    )
    network_ids = {n.id for n in networks}

    firewall_name_to_id: dict[str, str] = {}
    for net in networks:
        nodes.append(_node(
            f"net:{net.id}", "network", net.name, f"acct:{net.cloud_account_id}",
            cidr=net.cidr, provider=net.provider, region=net.region, environment_name=net.environment_name,
            owner_team=net.owner_team, status=net.status,
        ))
        if net.firewall:
            fw_id = firewall_name_to_id.get(net.firewall)
            if not fw_id:
                fw_id = f"fw:{net.firewall}"
                firewall_name_to_id[net.firewall] = fw_id
                nodes.append(_node(fw_id, "firewall", net.firewall, None))
            edges.append({"from": f"net:{net.id}", "to": fw_id, "kind": "protected_by"})

    subnets = (
        db.execute(select(Subnet).where(Subnet.network_id.in_(network_ids))).scalars().all()
        if network_ids else []
    )
    subnet_ids = {s.id for s in subnets}
    for sn in subnets:
        nodes.append(_node(
            f"sub:{sn.id}", "subnet", sn.name or sn.cidr, f"net:{sn.network_id}",
            cidr=sn.cidr, availability_zone=sn.availability_zone, application=sn.application, status=sn.status,
        ))

    devices = (
        db.execute(select(Device).where(Device.deleted_at.is_(None), Device.environment_id.in_(env_ids))).scalars().all()
        if env_ids else []
    )
    device_node_id: dict[uuid.UUID, str] = {}
    for dev in devices:
        node_id = f"dev:{dev.id}"
        device_node_id[dev.id] = node_id
        nodes.append(_node(
            node_id, "device", dev.hostname, f"env:{dev.environment_id}",
            device_type=dev.device_type, vendor=dev.vendor, mgmt_ip=dev.mgmt_ip, site=dev.site, status=dev.status,
        ))
        if dev.device_type == "firewall" and dev.hostname in firewall_name_to_id:
            for n in nodes:
                if n["id"] == firewall_name_to_id[dev.hostname]:
                    n["meta"]["device_id"] = str(dev.id)
                    break

    if devices and subnet_ids:
        interfaces = db.execute(
            select(Interface).where(
                Interface.device_id.in_([d.id for d in devices]), Interface.subnet_id.in_(subnet_ids),
            ),
        ).scalars().all()
        for iface in interfaces:
            edges.append({
                "from": device_node_id[iface.device_id], "to": f"sub:{iface.subnet_id}",
                "kind": "attached_via", "label": iface.name,
            })

    for n in nodes:
        if n["parent_id"]:
            edges.append({"from": n["parent_id"], "to": n["id"], "kind": "contains"})

    return {"nodes": nodes, "edges": edges}
