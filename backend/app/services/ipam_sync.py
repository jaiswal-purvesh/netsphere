"""Runs app/services/tcpwave_adapter.py's fetch_networks() and upserts the
result into networks/subnets/ip_addresses — the on-prem counterpart to
app/services/discovery.py's cloud-provider sync, extended one level
further: discovery.py only ever wrote networks+subnets because no cloud
provider adapter here returns individual IP objects, but TCPWave's
`object/list` does, and populating `ip_addresses` for the first time is
the actual point of this integration ("fetch all IPAM IP and details").

Idempotency:
  - Network: matched first by (external_source, external_ref) so a
    network whose CIDR changes upstream is still recognized as the same
    row on re-sync; falls back to (cloud_account_id, cidr) so a network a
    human already entered by hand with the same CIDR gets adopted (tagged
    with external_source/external_ref) rather than duplicated.
  - Subnet: same two-step match, scoped to the parent network.
  - IPAddress: matched by the (subnet_id, ip_address) unique constraint
    added alongside this feature (see the f3d8a6b12c47 migration) — the
    first real writer of this table.

A sync never deletes: an IP/subnet/network that disappears from TCPWave
between runs is left as-is (still real data NetSphere once observed) —
only `last_synced_at` staleness would flag that on the frontend, follow-up
work, not silently pruning rows a re-sync run might just not have reached.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ipam_integration import IpamIntegration, IpamSyncRun
from app.models.network import IPAddress, Network, Subnet
from app.models.org import CloudAccount
from app.services import secrets as secretsvc
from app.services import tcpwave_adapter as tcpwave
from app.services.cidr import CidrError, ip_to_int, parse_cidr

EXTERNAL_SOURCE = "tcpwave"


class IpamSyncError(Exception):
    pass


def _resolve_credentials(integration: IpamIntegration) -> tuple[str | None, tuple[str, str] | None]:
    token = secretsvc.decrypt(integration.token_ciphertext) if integration.token_ciphertext else None
    client_cert = None
    if integration.client_cert_ciphertext and integration.client_key_ciphertext:
        raise IpamSyncError(
            "client-certificate auth is stored but not yet wired up in this adapter "
            "(httpx needs the cert/key as files, not in-memory bytes) — use token auth for now",
        )
    if integration.auth_mode == "token" and not token:
        raise IpamSyncError("integration is set to token auth but has no saved token")
    if integration.auth_mode == "client_cert":
        raise IpamSyncError("client-certificate auth is not yet implemented — use token auth for now")
    return token, client_cert


def _upsert_network(db: Session, integration: IpamIntegration, net: tcpwave.TcpwaveNetwork, now: datetime) -> tuple[Network, bool]:
    try:
        parsed = parse_cidr(net.cidr)
    except CidrError as e:
        raise IpamSyncError(f"TCPWave network {net.external_ref!r} has an unparseable CIDR {net.cidr!r}: {e}") from e

    existing = db.execute(
        select(Network).where(Network.external_source == EXTERNAL_SOURCE, Network.external_ref == net.external_ref),
    ).scalar_one_or_none()
    if not existing:
        existing = db.execute(
            select(Network).where(Network.cloud_account_id == integration.cloud_account_id, Network.cidr == parsed.cidr),
        ).scalar_one_or_none()

    created = existing is None
    if not existing:
        existing = Network(
            cloud_account_id=integration.cloud_account_id,
            name=net.name or net.external_ref or parsed.cidr,
            cidr=parsed.cidr, network_addr=parsed.network, broadcast_addr=parsed.broadcast, prefix_len=parsed.prefix_len,
            provider="onprem", status="active",
        )
        db.add(existing)
    else:
        existing.name = net.name or existing.name
        existing.cidr = parsed.cidr
        existing.network_addr, existing.broadcast_addr, existing.prefix_len = parsed.network, parsed.broadcast, parsed.prefix_len

    existing.external_source = EXTERNAL_SOURCE
    existing.external_ref = net.external_ref
    existing.last_synced_at = now
    db.flush()
    return existing, created


def _upsert_subnet(db: Session, network: Network, sub: tcpwave.TcpwaveSubnet, now: datetime) -> tuple[Subnet, bool]:
    try:
        parsed = parse_cidr(sub.cidr)
    except CidrError as e:
        raise IpamSyncError(f"TCPWave subnet {sub.external_ref!r} has an unparseable CIDR {sub.cidr!r}: {e}") from e

    existing = db.execute(
        select(Subnet).where(
            Subnet.network_id == network.id, Subnet.external_source == EXTERNAL_SOURCE, Subnet.external_ref == sub.external_ref,
        ),
    ).scalar_one_or_none()
    if not existing:
        existing = db.execute(
            select(Subnet).where(Subnet.network_id == network.id, Subnet.cidr == parsed.cidr),
        ).scalar_one_or_none()

    created = existing is None
    if not existing:
        existing = Subnet(
            network_id=network.id, name=sub.name or sub.external_ref,
            cidr=parsed.cidr, network_addr=parsed.network, broadcast_addr=parsed.broadcast, prefix_len=parsed.prefix_len,
            status="active",
        )
        db.add(existing)
    else:
        existing.name = sub.name or existing.name
        existing.cidr = parsed.cidr
        existing.network_addr, existing.broadcast_addr, existing.prefix_len = parsed.network, parsed.broadcast, parsed.prefix_len

    existing.external_source = EXTERNAL_SOURCE
    existing.external_ref = sub.external_ref
    existing.last_synced_at = now
    db.flush()
    return existing, created


def _upsert_ip(db: Session, subnet: Subnet, obj: tcpwave.TcpwaveIpObject, now: datetime) -> bool:
    try:
        ip_int = ip_to_int(obj.ip_address)
    except CidrError:
        return False  # unparseable address from the source — skip rather than guess, don't fail the whole run over one bad record

    existing = db.execute(
        select(IPAddress).where(IPAddress.subnet_id == subnet.id, IPAddress.ip_address == obj.ip_address),
    ).scalar_one_or_none()
    created = existing is None
    if not existing:
        existing = IPAddress(subnet_id=subnet.id, ip_address=obj.ip_address, ip_int=ip_int)
        db.add(existing)

    existing.status = obj.status
    existing.hostname = obj.hostname or existing.hostname
    existing.mac_address = obj.mac_address or existing.mac_address
    existing.assigned_to = obj.organization_name or existing.assigned_to
    existing.external_source = EXTERNAL_SOURCE
    existing.external_ref = obj.external_ref
    existing.last_synced_at = now
    return created


def run_sync(db: Session, integration: IpamIntegration, triggered_by_id: uuid.UUID | None) -> IpamSyncRun:
    now = datetime.now(timezone.utc)
    # Column `default=0`s only apply at INSERT time, not on the plain Python
    # object before it's flushed — set them explicitly so the `+=` below
    # (which runs pre-flush, across a potentially long-running sync) works
    # against real ints from the start rather than None.
    run = IpamSyncRun(
        integration_id=integration.id, triggered_by_id=triggered_by_id,
        networks_seen=0, networks_created=0, networks_updated=0,
        subnets_seen=0, subnets_created=0, subnets_updated=0,
        ips_seen=0, ips_created=0, ips_updated=0,
    )

    if not integration.host:
        run.status, run.error_message = "error", "integration has no host configured"
        run.finished_at = datetime.now(timezone.utc)
        db.add(run)
        db.commit()
        return run

    if not integration.cloud_account_id:
        run.status, run.error_message = "error", (
            "integration has no cloud account selected — pick (or create) an on-prem "
            "cloud account to attach synced networks under"
        )
        run.finished_at = datetime.now(timezone.utc)
        db.add(run)
        db.commit()
        return run

    account = db.get(CloudAccount, integration.cloud_account_id)
    if not account:
        run.status, run.error_message = "error", f"cloud account {integration.cloud_account_id} no longer exists"
        run.finished_at = datetime.now(timezone.utc)
        db.add(run)
        db.commit()
        return run

    try:
        token, client_cert = _resolve_credentials(integration)
        networks = tcpwave.fetch_networks(
            integration.host, integration.port, integration.verify_tls, token,
            organization_name=integration.organization_name, client_cert=client_cert,
        )
    except (tcpwave.TcpwaveError, IpamSyncError, secretsvc.SecretDecryptionError) as exc:
        run.status = "error"
        run.error_message = str(exc)
        run.finished_at = datetime.now(timezone.utc)
        db.add(run)
        db.commit()
        return run

    for net in networks:
        network_row, net_created = _upsert_network(db, integration, net, now)
        run.networks_seen += 1
        run.networks_created += int(net_created)
        run.networks_updated += int(not net_created)

        for sub in net.subnets:
            subnet_row, sub_created = _upsert_subnet(db, network_row, sub, now)
            run.subnets_seen += 1
            run.subnets_created += int(sub_created)
            run.subnets_updated += int(not sub_created)

            for obj in sub.ip_objects:
                ip_created = _upsert_ip(db, subnet_row, obj, now)
                run.ips_seen += 1
                run.ips_created += int(ip_created)
                run.ips_updated += int(not ip_created)

    run.status = "ok"
    run.finished_at = datetime.now(timezone.utc)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run
