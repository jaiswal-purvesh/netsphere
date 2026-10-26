"""Phase 6 — resolves one parsed intake row
(app/services/security_policy_intake.py) to a concrete enforcement point:
which `Network` the destination address falls inside, and therefore which
`SecurityGroup` (cloud) or `FirewallIntegration` (on-prem) the resulting
`FwIntent` should target.

This is a real CIDR-containment lookup against the network inventory
already built in earlier phases (`Network.network_addr`/`broadcast_addr`,
populated by discovery/IPAM sync) — not a guess and not a fixed mapping
table. Matches `claude/firewall-policy-automation-design.md` §1.1 F2
("enrich the request... resolve names/tags to concrete addresses") and F3
("determine which enforcement points sit in the traffic path"), scoped down
from that design's full topology/path service to the single-hop version
this phase needs: the destination's own network tells you which security
group protects it.

Resolution order for a row's destination IP:
  1. Look up every `Network` whose [network_addr, broadcast_addr] range
     contains the destination — Network.provider in (aws, azure, gcp, oci)
     means "this destination lives in a cloud VPC/VNet/VCN", so the target
     is that network's `SecurityGroup` (created on first use — see
     `get_or_create_security_group` below).
  2. If no cloud network contains it, but the destination falls inside some
     on-prem `Network`/`Subnet` (provider == "onprem") or no network at all
     (a raw private IP with no inventory record, common for a newly-
     provisioned host) — the target is a firewall: the single active
     `FirewallIntegration`, when there is exactly one, else left unresolved
     asking the operator to pick one (never silently guessing which of
     several firewalls is authoritative).
  3. A destination FQDN or an unparseable source is already unresolved from
     the intake parser itself and never reaches this function.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.integration import FirewallIntegration
from app.models.network import Network
from app.models.security_policy import SECURITY_GROUP_PROVIDERS, SecurityGroup
from app.services.cidr import CidrError, ip_to_int, parse_cidr

_PROVIDER_TO_TARGET_KIND = {
    "aws": "aws_sg",
    "azure": "azure_nsg",
    "gcp": "gcp_firewall",
    "oci": "oci_security_list",
}


class UnresolvedTarget(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass
class ResolvedTarget:
    target_kind: str  # "firewall" | "azure_nsg" | "aws_sg" | "gcp_firewall" | "oci_security_list"
    integration_id: uuid.UUID | None = None
    device_group: str | None = None
    security_group_id: uuid.UUID | None = None
    network_name: str | None = None


def _destination_value(destination_ip: str) -> int | tuple[int, int]:
    if "/" in destination_ip:
        parsed = parse_cidr(destination_ip)
        return (parsed.network, parsed.broadcast)
    n = ip_to_int(destination_ip)
    return (n, n)


def _find_containing_networks(db: Session, destination_ip: str) -> list[Network]:
    try:
        lo, hi = _destination_value(destination_ip)
    except CidrError:
        return []
    rows = db.execute(
        select(Network).where(
            Network.deleted_at.is_(None),
            Network.network_addr <= lo,
            Network.broadcast_addr >= hi,
        ),
    ).scalars().all()
    return list(rows)


def get_or_create_security_group(db: Session, network: Network) -> SecurityGroup:
    target_kind = _PROVIDER_TO_TARGET_KIND[network.provider]
    existing = db.execute(
        select(SecurityGroup).where(
            SecurityGroup.network_id == network.id,
            SecurityGroup.provider == target_kind,
            SecurityGroup.deleted_at.is_(None),
        ),
    ).scalars().first()
    if existing:
        return existing

    assert target_kind in SECURITY_GROUP_PROVIDERS
    sg = SecurityGroup(
        network_id=network.id, cloud_account_id=network.cloud_account_id, provider=target_kind,
        name=f"{network.name}-sg", description=f"Auto-created for {network.name} on first Phase 6 intake match.",
        source="auto",
    )
    db.add(sg)
    db.flush()
    return sg


def resolve_destination(db: Session, destination_ip: str) -> ResolvedTarget:
    """Raises UnresolvedTarget when the destination can't be placed with
    confidence — never guesses."""
    networks = _find_containing_networks(db, destination_ip)
    cloud_networks = [n for n in networks if n.provider in _PROVIDER_TO_TARGET_KIND]

    if cloud_networks:
        # Prefer the most specific (narrowest) match if more than one
        # network's range contains the address (parent/child VPC nesting).
        network = min(cloud_networks, key=lambda n: n.broadcast_addr - n.network_addr)
        sg = get_or_create_security_group(db, network)
        return ResolvedTarget(target_kind=sg.provider, security_group_id=sg.id, network_name=network.name)

    # Not in any known cloud network — treat as on-prem, targeting the
    # single active firewall integration if there is exactly one.
    integrations = db.execute(
        select(FirewallIntegration).where(FirewallIntegration.is_active.is_(True), FirewallIntegration.parent_id.is_(None)),
    ).scalars().all()
    if len(integrations) == 1:
        integ = integrations[0]
        return ResolvedTarget(target_kind="firewall", integration_id=integ.id, device_group=integ.device_group)
    if not integrations:
        raise UnresolvedTarget("destination is not inside any known cloud network, and no active firewall integration exists to target on-prem")
    raise UnresolvedTarget(
        f"destination is not inside any known cloud network, and {len(integrations)} active firewall "
        "integrations exist — pick one manually rather than guessing which is authoritative",
    )
