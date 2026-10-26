"""Phase 3 — Cloud Networks ingestion. Upserts `DiscoveredCloudInterface`/
`DiscoveredPeering` results (see app/providers/base.py) into
`cloud_network_interfaces`/`network_peerings`, called from
app/services/discovery.py right after each network's subnets (interfaces)
and, separately, once per discovery run (peerings) — same idempotent-by-
natural-key upsert shape as app/services/routing.py, not a third pattern.

**Interfaces** are keyed by (subnet_id, external_id) — discovery.py builds
and passes the subnet_external_id -> subnet_id map it already has on hand
from upserting that network's own subnets, so this module never needs to
re-derive it.

**Peerings** are trickier: `DiscoveredPeering` names its two sides by
`Network.name` (see that dataclass's own docstring for why — no queryable
external_id column on Network today), and a provider's `discover_peerings()`
is intentionally NOT scoped to one account's networks (real peering
connections commonly cross accounts). That means a peering can arrive
before one or both of its Networks have been discovered yet — e.g.
discovery runs account-by-account and the peer on the far side hasn't been
pulled in yet. Rather than treating that as an error, an unresolvable
peering is skipped for this call and picked up idempotently the next time
discovery runs for the account that provides the missing side — the same
"additive, not required" contract app/services/routing.py already uses for
routing data on top of network/subnet discovery.

The (A,B)/(B,A) duplicate-pair problem (the same connection is
discoverable from either side's account, and a provider isn't guaranteed to
always name the two sides in the same order) is handled here, not with a
second unique index: both sides are resolved to real Network ids, then
ordered canonically (lower id first) before the upsert, so "A peers with B"
and "B peers with A" always land on the same row.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cloud_networks import CloudNetworkInterface, NetworkPeering
from app.models.network import Network
from app.providers.base import DiscoveredCloudInterface, DiscoveredPeering


def upsert_interfaces_for_network(
    db: Session,
    discovered: list[DiscoveredCloudInterface],
    subnet_id_by_external_id: dict[str, uuid.UUID],
) -> dict:
    """`subnet_id_by_external_id` maps each of this network's subnets'
    `DiscoveredSubnet.external_id` to the `Subnet.id` row discovery.py just
    upserted it to. An interface whose `subnet_external_id` isn't in that
    map (shouldn't happen for a well-formed provider, since interfaces are
    always drawn from the same network's own subnets) is skipped rather
    than raising — same additive-not-required contract as the rest of this
    module."""
    created = updated = skipped = 0
    for d in discovered:
        subnet_id = subnet_id_by_external_id.get(d.subnet_external_id)
        if subnet_id is None:
            skipped += 1
            continue
        existing = db.execute(
            select(CloudNetworkInterface).where(
                CloudNetworkInterface.subnet_id == subnet_id,
                CloudNetworkInterface.external_id == d.external_id,
            ),
        ).scalar_one_or_none()
        if existing:
            existing.name = d.name
            existing.private_ip = d.private_ip
            existing.public_ip = d.public_ip
            existing.attached_to = d.attached_to
            existing.status = d.status
            existing.security_groups = list(d.security_groups)
            existing.source = "discovered"
            updated += 1
        else:
            db.add(CloudNetworkInterface(
                subnet_id=subnet_id, name=d.name, private_ip=d.private_ip, public_ip=d.public_ip,
                attached_to=d.attached_to, status=d.status, security_groups=list(d.security_groups),
                source="discovered", external_id=d.external_id,
            ))
            created += 1
    return {"interfaces_created": created, "interfaces_updated": updated, "interfaces_skipped": skipped}


def upsert_peerings(db: Session, discovered: list[DiscoveredPeering]) -> dict:
    created = updated = skipped = 0
    for d in discovered:
        network_a = db.execute(select(Network).where(Network.name == d.network_a_name)).scalar_one_or_none()
        network_b = db.execute(select(Network).where(Network.name == d.network_b_name)).scalar_one_or_none()
        if network_a is None or network_b is None or network_a.id == network_b.id:
            # Either side not discovered yet, or (degenerate/bad data) both
            # sides resolve to the same network — skip, retried on the next
            # discovery pass rather than erroring the whole run.
            skipped += 1
            continue

        a_id, b_id = (network_a.id, network_b.id) if str(network_a.id) < str(network_b.id) else (network_b.id, network_a.id)
        existing = db.execute(
            select(NetworkPeering).where(NetworkPeering.network_a_id == a_id, NetworkPeering.network_b_id == b_id),
        ).scalar_one_or_none()
        if existing:
            existing.status = d.status
            existing.source = "discovered"
            existing.external_id = d.external_id
            updated += 1
        else:
            db.add(NetworkPeering(
                network_a_id=a_id, network_b_id=b_id, status=d.status,
                source="discovered", external_id=d.external_id,
            ))
            created += 1
    return {"peerings_created": created, "peerings_updated": updated, "peerings_skipped": skipped}
