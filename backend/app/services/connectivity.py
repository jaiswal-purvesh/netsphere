"""Phase 8 — Connectivity ingestion. Upserts `DiscoveredCircuit`/
`DiscoveredBgpSession`/`DiscoveredVpnConnection` results (see
app/providers/base.py) into `circuits`/`bgp_sessions`/`connectivity_links`/
`vpn_connections`, called from app/services/discovery.py (cloud circuits +
VPNs, once per account) and app/services/devices.py (on-prem circuits,
once per device-discovery run) — same idempotent-by-natural-key upsert
shape as app/services/routing.py and app/services/cloud_networks.py, not a
fourth pattern.

**Why a cloud-side circuit and its on-prem-side counterpart are two rows,
not one**: `CloudProvider.discover_circuits()` and
`NetworkDeviceProvider.discover_circuits()` are called independently (a
cloud account's own discovery sweep knows nothing about the on-prem
device inventory, and vice versa), and each side of a real Direct
Connect/ExpressRoute/Interconnect/FastConnect link is typically monitored
by a different team anyway (the cloud account owner vs. the network
team). Rather than invent a cross-provider matching step this phase
doesn't need, each side ingests its own `Circuit` row under its own owner
(`cloud_account_id` or `device_id`) — `app/providers/mock/aws.py`'s/
`azure.py`'s BGP peer IP/ASN values are deliberately mirrored from
`app/providers/mock/snmp.py`'s matching circuit so a human reading both
rows can see they describe the two ends of one physical link, even though
nothing in the schema enforces that relationship.

**Peerings-style resolution**: a `Circuit`'s `attached_network_name`
resolves to a `ConnectivityLink` the same way `DiscoveredPeering` resolves
its two networks — by `Network.name`, skipped (not errored) when
unresolved so a circuit discovered before its target network exists still
ingests cleanly and picks up the link on a later pass. `VpnConnection`
follows the identical skip-and-retry contract for its own `network_name`.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.connectivity import BgpSession, Circuit, ConnectivityLink, VpnConnection
from app.models.network import Network
from app.providers.base import DiscoveredBgpSession, DiscoveredCircuit, DiscoveredVpnConnection


def _upsert_bgp_sessions(db: Session, circuit_id: uuid.UUID, discovered: list[DiscoveredBgpSession]) -> tuple[int, int]:
    """Natural key: (circuit_id, peer_ip) — a circuit rarely has two BGP
    sessions to the same peer address, and when it does (redundant
    sessions) the later discovery pass updates the first match rather than
    duplicating, same acceptable-for-an-inventory-view trade-off as
    `app/services/routing.py`'s own route upsert."""
    existing = db.execute(select(BgpSession).where(BgpSession.circuit_id == circuit_id)).scalars().all()
    by_peer_ip = {s.peer_ip: s for s in existing}
    created = updated = 0
    for d in discovered:
        row = by_peer_ip.get(d.peer_ip)
        if row:
            row.local_asn = d.local_asn
            row.peer_asn = d.peer_asn
            row.local_ip = d.local_ip
            row.state = d.state
            row.external_id = d.external_id
            row.source = "discovered"
            updated += 1
        else:
            db.add(BgpSession(
                circuit_id=circuit_id, local_asn=d.local_asn, peer_asn=d.peer_asn, local_ip=d.local_ip,
                peer_ip=d.peer_ip, state=d.state, source="discovered", external_id=d.external_id,
            ))
            created += 1
    return created, updated


def _upsert_circuit(db: Session, discovered: DiscoveredCircuit, **owner_kwargs) -> tuple[Circuit, dict]:
    """`owner_kwargs` is `{"cloud_account_id": id}` or `{"device_id": id}` —
    whichever FK owns this circuit. Natural key is `external_id`, scoped to
    that owner (two different owners legitimately reusing the same
    provider-native id would be a real anomaly, not something to collapse)."""
    existing = db.execute(
        select(Circuit).where(Circuit.external_id == discovered.external_id, *(
            getattr(Circuit, k) == v for k, v in owner_kwargs.items()
        )),
    ).scalar_one_or_none()

    if existing:
        existing.name = discovered.name
        existing.circuit_type = discovered.circuit_type
        existing.vrf = discovered.vrf
        existing.bandwidth_mbps = discovered.bandwidth_mbps
        existing.location = discovered.location
        existing.status = discovered.status
        existing.source = "discovered"
        circuit_row = existing
        created = 0
    else:
        circuit_row = Circuit(
            name=discovered.name, circuit_type=discovered.circuit_type, vrf=discovered.vrf,
            bandwidth_mbps=discovered.bandwidth_mbps, location=discovered.location, status=discovered.status,
            source="discovered", external_id=discovered.external_id, **owner_kwargs,
        )
        db.add(circuit_row)
        db.flush()  # get circuit_row.id before adding BGP sessions/links
        created = 1

    bgp_created, bgp_updated = _upsert_bgp_sessions(db, circuit_row.id, discovered.bgp_sessions)

    link_created = 0
    if discovered.attached_network_name:
        network = db.execute(select(Network).where(Network.name == discovered.attached_network_name)).scalar_one_or_none()
        if network is not None:
            existing_link = db.execute(
                select(ConnectivityLink).where(
                    ConnectivityLink.circuit_id == circuit_row.id, ConnectivityLink.network_id == network.id,
                ),
            ).scalar_one_or_none()
            if existing_link:
                existing_link.status = "active"
                existing_link.source = "discovered"
            else:
                db.add(ConnectivityLink(network_id=network.id, circuit_id=circuit_row.id, status="active", source="discovered"))
                link_created = 1

    return circuit_row, {
        "circuits_created": created, "circuits_updated": 0 if created else 1,
        "bgp_sessions_created": bgp_created, "bgp_sessions_updated": bgp_updated,
        "connectivity_links_created": link_created,
    }


def _merge(*results: dict) -> dict:
    keys = ["circuits_created", "circuits_updated", "bgp_sessions_created", "bgp_sessions_updated", "connectivity_links_created"]
    return {k: sum(r.get(k, 0) for r in results) for k in keys}


def upsert_circuits_for_account(db: Session, cloud_account_id: uuid.UUID, discovered: list[DiscoveredCircuit]) -> dict:
    """Called from app/services/discovery.py right after a cloud account's
    peerings are ingested. An empty `discovered` list (most accounts don't
    have a dedicated interconnect provisioned) is a no-op, same
    additive-not-required contract as Routing/Cloud Networks."""
    if not discovered:
        return _merge()
    return _merge(*(_upsert_circuit(db, d, cloud_account_id=cloud_account_id)[1] for d in discovered))


def upsert_circuits_for_devices(db: Session, device_id_by_hostname: dict[str, uuid.UUID], discovered: list[DiscoveredCircuit]) -> dict:
    """Called once per app/services/devices.py discovery run, after all of
    that run's devices are upserted — `device_id_by_hostname` is the
    hostname->id map that loop already built. A circuit whose
    `attached_device_hostname` isn't in the map (shouldn't happen for a
    well-formed provider) is skipped rather than raising."""
    if not discovered:
        return _merge()
    results = []
    for d in discovered:
        device_id = device_id_by_hostname.get(d.attached_device_hostname)
        if device_id is None:
            continue
        results.append(_upsert_circuit(db, d, device_id=device_id)[1])
    return _merge(*results)


def upsert_vpn_connections(db: Session, discovered: list[DiscoveredVpnConnection]) -> dict:
    created = updated = skipped = 0
    for d in discovered:
        network = db.execute(select(Network).where(Network.name == d.network_name)).scalar_one_or_none()
        if network is None:
            skipped += 1
            continue
        existing = db.execute(
            select(VpnConnection).where(VpnConnection.network_id == network.id, VpnConnection.external_id == d.external_id),
        ).scalar_one_or_none()
        if existing:
            existing.peer_ip = d.peer_ip
            existing.status = d.status
            existing.source = "discovered"
            updated += 1
        else:
            db.add(VpnConnection(
                network_id=network.id, peer_ip=d.peer_ip, status=d.status, source="discovered", external_id=d.external_id,
            ))
            created += 1
    return {"vpn_connections_created": created, "vpn_connections_updated": updated, "vpn_connections_skipped": skipped}
