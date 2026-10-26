"""Runs a NetworkDeviceProvider's discover_devices() and upserts the result
into the devices/interfaces tables. Idempotent on (environment_id, hostname)
for devices and (device_id, name) for interfaces — same upsert-by-natural-
key idea as app/services/discovery.py, applied to device inventory instead
of cloud networks.

Also does a best-effort IPAM cross-link: if an interface's ip_address falls
inside a subnet NetSphere already has, its subnet_id is set. This is the
"network source of truth" convergence point between the device-inventory
half of Phase 2 and the IPAM half — not required for either to work alone.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.device import Device, Interface
from app.models.network import Subnet
from app.models.org import Environment
from app.providers.base import NetworkDeviceProvider
from app.services import connectivity as connectivitysvc
from app.services import routing as routingsvc
from app.services.cidr import CidrError, ip_to_int


def _find_subnet_for_ip(db: Session, ip_address: str | None) -> uuid.UUID | None:
    if not ip_address:
        return None
    try:
        n = ip_to_int(ip_address)
    except CidrError:
        return None
    subnet = db.execute(
        select(Subnet)
        .where(Subnet.network_addr <= n, Subnet.broadcast_addr >= n)
        .order_by(Subnet.prefix_len.desc())
        .limit(1),
    ).scalar_one_or_none()
    return subnet.id if subnet else None


def run_device_discovery(db: Session, provider: NetworkDeviceProvider, environment_id: uuid.UUID) -> dict:
    environment = db.get(Environment, environment_id)
    if not environment:
        raise ValueError(f"environment {environment_id} not found")

    discovered = provider.discover_devices()
    created_devices = 0
    updated_devices = 0
    created_interfaces = 0
    updated_interfaces = 0
    routes_created = 0
    routes_updated = 0
    device_id_by_hostname: dict[str, uuid.UUID] = {}

    for dev in discovered:
        existing = db.execute(
            select(Device).where(Device.environment_id == environment_id, Device.hostname == dev.hostname),
        ).scalar_one_or_none()

        if existing:
            device_row = existing
            device_row.vendor = dev.vendor
            device_row.device_type = dev.device_type
            device_row.mgmt_ip = dev.mgmt_ip
            device_row.site = dev.site
            device_row.source = "snmp"
            device_row.external_id = dev.external_id
            updated_devices += 1
        else:
            device_row = Device(
                environment_id=environment_id,
                hostname=dev.hostname,
                vendor=dev.vendor,
                device_type=dev.device_type,
                mgmt_ip=dev.mgmt_ip,
                site=dev.site,
                source="snmp",
                external_id=dev.external_id,
                status="active",
            )
            db.add(device_row)
            db.flush()  # get device_row.id before adding interfaces
            created_devices += 1

        for iface in dev.interfaces:
            existing_iface = db.execute(
                select(Interface).where(Interface.device_id == device_row.id, Interface.name == iface.name),
            ).scalar_one_or_none()
            subnet_id = _find_subnet_for_ip(db, iface.ip_address)

            if existing_iface:
                existing_iface.description = iface.description
                existing_iface.ip_address = iface.ip_address
                existing_iface.mac_address = iface.mac_address
                existing_iface.admin_status = iface.admin_status
                existing_iface.oper_status = iface.oper_status
                existing_iface.speed_mbps = iface.speed_mbps
                existing_iface.vlan_id = iface.vlan_id
                existing_iface.subnet_id = subnet_id
                updated_interfaces += 1
            else:
                db.add(Interface(
                    device_id=device_row.id,
                    subnet_id=subnet_id,
                    name=iface.name,
                    description=iface.description,
                    ip_address=iface.ip_address,
                    mac_address=iface.mac_address,
                    admin_status=iface.admin_status,
                    oper_status=iface.oper_status,
                    speed_mbps=iface.speed_mbps,
                    vlan_id=iface.vlan_id,
                ))
                created_interfaces += 1

        route_result = routingsvc.upsert_routes_for_device(db, device_row.id, dev.routes)
        routes_created += route_result["routes_created"]
        routes_updated += route_result["routes_updated"]

        device_id_by_hostname[dev.hostname] = device_row.id

    # On-prem side of any dedicated interconnect handoffs (MPLS/VRF) —
    # a whole-run call, not per-device, since discover_circuits() isn't
    # scoped to one device the way discover_devices() naturally is; see
    # app/providers/base.py::NetworkDeviceProvider.discover_circuits().
    circuit_result = connectivitysvc.upsert_circuits_for_devices(db, device_id_by_hostname, provider.discover_circuits())

    db.commit()
    return {
        "devices_discovered": len(discovered),
        "devices_created": created_devices,
        "devices_updated": updated_devices,
        "interfaces_created": created_interfaces,
        "interfaces_updated": updated_interfaces,
        "routes_created": routes_created,
        "routes_updated": routes_updated,
        "circuits_created": circuit_result["circuits_created"],
        "circuits_updated": circuit_result["circuits_updated"],
        "bgp_sessions_created": circuit_result["bgp_sessions_created"],
        "bgp_sessions_updated": circuit_result["bgp_sessions_updated"],
    }
