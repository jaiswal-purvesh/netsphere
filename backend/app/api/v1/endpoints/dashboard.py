from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.device import Device
from app.models.network import Network, Subnet
from app.models.user import User

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/summary")
def summary(db: Session = Depends(get_db), _: User = Depends(require_permission("ipam:view"))) -> dict:
    by_provider = dict(
        db.execute(
            select(Network.provider, func.count()).where(Network.deleted_at.is_(None)).group_by(Network.provider),
        ).all(),
    )
    total_networks = sum(by_provider.values())
    total_subnets = db.execute(select(func.count()).select_from(Subnet)).scalar_one()

    by_device_type = dict(
        db.execute(
            select(Device.device_type, func.count()).where(Device.deleted_at.is_(None)).group_by(Device.device_type),
        ).all(),
    )
    total_devices = sum(by_device_type.values())

    return {
        "total_networks": total_networks,
        "networks_by_provider": {
            "aws": by_provider.get("aws", 0),
            "azure": by_provider.get("azure", 0),
            "gcp": by_provider.get("gcp", 0),
            "oci": by_provider.get("oci", 0),
            "onprem": by_provider.get("onprem", 0),
        },
        "total_subnets": total_subnets,
        "total_devices": total_devices,
        "devices_by_type": {
            "router": by_device_type.get("router", 0),
            "switch": by_device_type.get("switch", 0),
            "firewall": by_device_type.get("firewall", 0),
            "load_balancer": by_device_type.get("load_balancer", 0),
            "other": by_device_type.get("other", 0),
        },
        # Everything below is not implemented yet (Phases 4-8) — reported as
        # null rather than a fabricated zero, so the UI can render "N/A"
        # instead of a misleading "0 incidents." Note "firewalls" here means
        # the Firewall Management module's managed-policy count (Phase 6),
        # not the device-inventory firewall count already in
        # devices_by_type.firewall above — those are two different things.
        "vpn_tunnels": None,
        "bgp_sessions": None,
        "firewalls": None,
        "network_incidents": None,
        "configuration_drift": None,
        "policy_violations": None,
    }
