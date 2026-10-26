"""Runs a CloudProvider's discover_networks() and upserts the result into
the networks/subnets tables. Idempotent on (cloud_account_id, cidr) so
re-running discovery is safe — same idea as the ip-pool-lookup tool's CSV
upsert, applied to provider discovery instead of a spreadsheet.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.network import Network, Subnet
from app.models.org import CloudAccount
from app.providers.base import CloudProvider
from app.services import cloud_networks as cloudnetworkssvc
from app.services import connectivity as connectivitysvc
from app.services import routing as routingsvc
from app.services.cidr import parse_cidr


def run_discovery(db: Session, provider: CloudProvider, cloud_account_id: uuid.UUID) -> dict:
    account = db.get(CloudAccount, cloud_account_id)
    if not account:
        raise ValueError(f"cloud account {cloud_account_id} not found")

    discovered = provider.discover_networks()
    created_networks = 0
    created_subnets = 0
    route_tables_created = route_tables_updated = 0
    routes_created = routes_updated = 0
    interfaces_created = interfaces_updated = 0
    peerings_created = peerings_updated = 0

    for net in discovered:
        parsed = parse_cidr(net.cidr)
        existing = db.execute(
            select(Network).where(Network.cloud_account_id == cloud_account_id, Network.cidr == parsed.cidr),
        ).scalar_one_or_none()

        if existing:
            network_row = existing
        else:
            network_row = Network(
                cloud_account_id=cloud_account_id,
                name=net.name,
                cidr=parsed.cidr,
                network_addr=parsed.network,
                broadcast_addr=parsed.broadcast,
                prefix_len=parsed.prefix_len,
                provider=provider.provider_name,
                region=net.region,
                status="active",
                notes=f"Discovered via mock provider (external_id={net.external_id})",
            )
            db.add(network_row)
            db.flush()  # get network_row.id before adding subnets
            created_networks += 1

        subnet_id_by_external_id: dict[str, uuid.UUID] = {}
        for sub in net.subnets:
            sub_parsed = parse_cidr(sub.cidr)
            existing_subnet = db.execute(
                select(Subnet).where(Subnet.network_id == network_row.id, Subnet.cidr == sub_parsed.cidr),
            ).scalar_one_or_none()
            if existing_subnet:
                subnet_row = existing_subnet
            else:
                subnet_row = Subnet(
                    network_id=network_row.id,
                    name=sub.name,
                    cidr=sub_parsed.cidr,
                    network_addr=sub_parsed.network,
                    broadcast_addr=sub_parsed.broadcast,
                    prefix_len=sub_parsed.prefix_len,
                    availability_zone=sub.availability_zone,
                    status="active",
                )
                db.add(subnet_row)
                db.flush()  # get subnet_row.id before interfaces reference it
                created_subnets += 1
            subnet_id_by_external_id[sub.external_id] = subnet_row.id

        route_result = routingsvc.upsert_route_table_for_network(db, network_row.id, net.route_table)
        route_tables_created += route_result["route_tables_created"]
        route_tables_updated += route_result["route_tables_updated"]
        routes_created += route_result["routes_created"]
        routes_updated += route_result["routes_updated"]

        iface_result = cloudnetworkssvc.upsert_interfaces_for_network(db, net.interfaces, subnet_id_by_external_id)
        interfaces_created += iface_result["interfaces_created"]
        interfaces_updated += iface_result["interfaces_updated"]

    # Peerings are resolved by Network.name across the whole DB, not scoped
    # to this account's networks (see app/services/cloud_networks.py's
    # docstring) — a single pass after all of this call's networks/subnets
    # are committed-in-session, so a peer discovered earlier in *this same*
    # call already resolves.
    peering_result = cloudnetworkssvc.upsert_peerings(db, provider.discover_peerings())
    peerings_created += peering_result["peerings_created"]
    peerings_updated += peering_result["peerings_updated"]

    # Circuits are owned by this account directly (no cross-account
    # resolution needed the way peerings need); VPN connections resolve by
    # Network.name the same way peerings do, since a provider's VPN
    # backup path is reported alongside its own account's networks.
    circuit_result = connectivitysvc.upsert_circuits_for_account(db, cloud_account_id, provider.discover_circuits())
    vpn_result = connectivitysvc.upsert_vpn_connections(db, provider.discover_vpn_connections())

    db.commit()
    return {
        "networks_discovered": len(discovered),
        "networks_created": created_networks,
        "subnets_created": created_subnets,
        "route_tables_created": route_tables_created,
        "route_tables_updated": route_tables_updated,
        "routes_created": routes_created,
        "routes_updated": routes_updated,
        "interfaces_created": interfaces_created,
        "interfaces_updated": interfaces_updated,
        "peerings_created": peerings_created,
        "peerings_updated": peerings_updated,
        "circuits_created": circuit_result["circuits_created"],
        "circuits_updated": circuit_result["circuits_updated"],
        "bgp_sessions_created": circuit_result["bgp_sessions_created"],
        "bgp_sessions_updated": circuit_result["bgp_sessions_updated"],
        "connectivity_links_created": circuit_result["connectivity_links_created"],
        "vpn_connections_created": vpn_result["vpn_connections_created"],
        "vpn_connections_updated": vpn_result["vpn_connections_updated"],
    }
