"""DB-aware IPAM operations: search, overlap detection, and subnet
allocation. Thin orchestration layer over `app/services/cidr.py` (pure CIDR
math) and `app/services/allocate.py` (pure allocation math) plus the
SQLAlchemy models — mirrors the split between ip-pool-lookup's `lib/cidr.js`
/ `lib/allocate.js` (pure) and `lib/pools.js` (DB-aware) in the earlier
Node tool this is extending.
"""
from __future__ import annotations

import csv
import io
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.network import IPAddress, Network, Subnet
from app.models.org import CloudAccount
from app.services import allocate as alloc
from app.services.cidr import CidrError, ip_to_int, parse_cidr

# Column order for both export and import — keep these in sync. cloud_account_id
# round-trips an export back into an import exactly; provider+account_identifier
# are included too so a human can hand-write an import CSV without knowing any
# internal UUIDs (either identifies the account; cloud_account_id wins if both
# are given and valid).
CSV_COLUMNS = [
    "cloud_account_id", "account_identifier", "provider", "cidr", "name",
    "region", "owner_team", "business_unit_name", "environment_name",
    "vrf", "vlan", "firewall", "status", "notes",
]


class IpamError(ValueError):
    def __init__(self, message: str, free: list[dict] | None = None):
        super().__init__(message)
        self.message = message
        self.free = free or []


def search_ip(db: Session, ip: str) -> dict:
    """All networks and subnets containing `ip`, most specific first —
    the direct equivalent of the Node tool's longest-prefix-match lookup."""
    try:
        n = ip_to_int(ip)
    except CidrError as e:
        raise IpamError(str(e)) from e

    networks = db.execute(
        select(Network)
        .where(Network.network_addr <= n, Network.broadcast_addr >= n, Network.deleted_at.is_(None))
        .order_by(Network.prefix_len.desc()),
    ).scalars().all()
    subnets = db.execute(
        select(Subnet)
        .where(Subnet.network_addr <= n, Subnet.broadcast_addr >= n)
        .order_by(Subnet.prefix_len.desc()),
    ).scalars().all()

    matches = [
        {"kind": "network", "id": str(x.id), "cidr": x.cidr, "provider": x.provider, "prefix_len": x.prefix_len,
         "owner_team": x.owner_team, "environment": x.environment_name, "region": x.region}
        for x in networks
    ] + [
        {"kind": "subnet", "id": str(x.id), "network_id": str(x.network_id), "cidr": x.cidr,
         "prefix_len": x.prefix_len, "owner_team": x.owner_team, "application": x.application}
        for x in subnets
    ]
    matches.sort(key=lambda m: -m["prefix_len"])
    return {"ip": ip, "matches": matches, "best_match": matches[0] if matches else None}


def find_overlapping_networks(db: Session) -> list[dict]:
    """Every pair of networks whose ranges overlap and are NOT in a
    declared parent/child relationship — the Module-2 "detect overlapping
    CIDRs" requirement, same two-case (duplicate/nested) model as the
    ip-pool-lookup tool's lib/conflicts.js: valid CIDRs are always
    disjoint, identical, or strictly nested, never partially overlapping.
    """
    rows = db.execute(select(Network).where(Network.deleted_at.is_(None)).order_by(Network.network_addr)).scalars().all()
    conflicts: list[dict] = []
    for i in range(len(rows)):
        a = rows[i]
        for j in range(i + 1, len(rows)):
            b = rows[j]
            if not (a.network_addr <= b.broadcast_addr and b.network_addr <= a.broadcast_addr):
                continue
            if a.id == b.parent_network_id or b.id == a.parent_network_id:
                continue
            conflict_type = "duplicate" if (a.network_addr == b.network_addr and a.broadcast_addr == b.broadcast_addr) else "nested"
            conflicts.append({
                "type": conflict_type,
                "cross_provider": a.provider != b.provider,
                "a": {"id": str(a.id), "cidr": a.cidr, "provider": a.provider, "owner_team": a.owner_team},
                "b": {"id": str(b.id), "cidr": b.cidr, "provider": b.provider, "owner_team": b.owner_team},
            })
    rank = {"duplicate": 0, "nested": 1}
    conflicts.sort(key=lambda c: rank[c["type"]])
    return conflicts


def overlaps_for_cidr(
    db: Session, cidr: str, exclude_network_id: uuid.UUID | None = None, provider: str | None = None,
) -> list[dict]:
    """Ad-hoc overlap/duplicate probe for a single CIDR against every other
    stored network — the same duplicate/nested classification as
    `find_overlapping_networks`, but usable before or right after a single
    network is created/edited/imported (real-time "duplicate or overlap IP"
    alert), without needing a second network row to already exist to pair
    it against. `exclude_network_id` leaves out the network being edited
    itself so it doesn't "conflict" with its own prior CIDR value.
    """
    parsed = parse_cidr(cidr)  # raises CidrError on invalid input — let callers translate to 400
    rows = db.execute(select(Network).where(Network.deleted_at.is_(None))).scalars().all()
    conflicts: list[dict] = []
    for n in rows:
        if exclude_network_id is not None and n.id == exclude_network_id:
            continue
        if not (parsed.network <= n.broadcast_addr and n.network_addr <= parsed.broadcast):
            continue
        conflict_type = "duplicate" if (parsed.network == n.network_addr and parsed.broadcast == n.broadcast_addr) else "nested"
        conflicts.append({
            "type": conflict_type,
            "cross_provider": (provider is not None and n.provider != provider),
            "network": {"id": str(n.id), "cidr": n.cidr, "provider": n.provider, "name": n.name, "owner_team": n.owner_team},
        })
    rank = {"duplicate": 0, "nested": 1}
    conflicts.sort(key=lambda c: rank[c["type"]])
    return conflicts


def query_networks(db: Session, provider: str | None = None, q: str | None = None) -> list[Network]:
    """Shared by GET /ipam/networks and the CSV export so the two never
    silently drift apart on what "the network list" means."""
    stmt = select(Network).where(Network.deleted_at.is_(None))
    if provider:
        stmt = stmt.where(Network.provider == provider)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Network.cidr.ilike(like) | Network.name.ilike(like) | Network.owner_team.ilike(like))
    return db.execute(stmt.order_by(Network.provider, Network.prefix_len.desc())).scalars().all()


def export_networks_csv(db: Session, provider: str | None = None, q: str | None = None) -> str:
    rows = query_networks(db, provider=provider, q=q)
    account_ids = {n.cloud_account_id for n in rows}
    accounts = {
        a.id: a for a in db.execute(select(CloudAccount).where(CloudAccount.id.in_(account_ids))).scalars().all()
    } if account_ids else {}

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for n in rows:
        account = accounts.get(n.cloud_account_id)
        writer.writerow({
            "cloud_account_id": str(n.cloud_account_id),
            "account_identifier": account.account_identifier if account else "",
            "provider": n.provider,
            "cidr": n.cidr,
            "name": n.name,
            "region": n.region or "",
            "owner_team": n.owner_team or "",
            "business_unit_name": n.business_unit_name or "",
            "environment_name": n.environment_name or "",
            "vrf": n.vrf or "",
            "vlan": n.vlan or "",
            "firewall": n.firewall or "",
            "status": n.status,
            "notes": n.notes or "",
        })
    return buf.getvalue()


def _resolve_cloud_account(db: Session, row: dict) -> CloudAccount:
    raw_id = (row.get("cloud_account_id") or "").strip()
    if raw_id:
        try:
            account = db.get(CloudAccount, uuid.UUID(raw_id))
        except ValueError as e:
            raise ValueError(f"cloud_account_id {raw_id!r} is not a valid UUID") from e
        if account:
            return account
        raise ValueError(f"no cloud account with id {raw_id}")

    provider = (row.get("provider") or "").strip()
    identifier = (row.get("account_identifier") or "").strip()
    if not provider or not identifier:
        raise ValueError("row needs either cloud_account_id, or both provider and account_identifier")
    account = db.execute(
        select(CloudAccount).where(CloudAccount.provider == provider, CloudAccount.account_identifier == identifier),
    ).scalars().first()
    if not account:
        raise ValueError(f"no cloud account for provider={provider!r} account_identifier={identifier!r}")
    return account


def import_networks_csv(db: Session, content: str) -> dict:
    """Bulk create-or-update networks from a CSV (same column set
    `export_networks_csv` writes). Each row is processed in its own
    savepoint so one bad row doesn't abort the rest of the batch; a row
    that upserts a CIDR already used elsewhere still gets an
    `overlap_warnings` list in its result — importing is not blocked by an
    overlap, only informed by it, same policy as the single-network
    create/update endpoints.
    """
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise ValueError("empty CSV — expected a header row")
    missing_required = {"cidr", "name"} - set(reader.fieldnames)
    if missing_required:
        raise ValueError(f"CSV is missing required column(s): {', '.join(sorted(missing_required))}")

    results: list[dict] = []
    for row_num, row in enumerate(reader, start=2):
        try:
            with db.begin_nested():
                cidr_raw = (row.get("cidr") or "").strip()
                name = (row.get("name") or "").strip()
                if not cidr_raw:
                    raise ValueError("cidr is required")
                if not name:
                    raise ValueError("name is required")

                account = _resolve_cloud_account(db, row)
                parsed = parse_cidr(cidr_raw)
                provider = (row.get("provider") or "").strip() or account.provider

                existing = db.execute(
                    select(Network).where(Network.cloud_account_id == account.id, Network.cidr == parsed.cidr),
                ).scalar_one_or_none()

                def field(key: str, current: str | None) -> str | None:
                    val = row.get(key)
                    if val is None:
                        return current
                    val = val.strip()
                    return val or None

                if existing:
                    existing.name = name
                    existing.region = field("region", existing.region)
                    existing.owner_team = field("owner_team", existing.owner_team)
                    existing.business_unit_name = field("business_unit_name", existing.business_unit_name)
                    existing.environment_name = field("environment_name", existing.environment_name)
                    existing.vrf = field("vrf", existing.vrf)
                    existing.vlan = field("vlan", existing.vlan)
                    existing.firewall = field("firewall", existing.firewall)
                    existing.notes = field("notes", existing.notes)
                    status_val = (row.get("status") or "").strip()
                    if status_val:
                        existing.status = status_val
                    network = existing
                    row_status = "updated"
                else:
                    network = Network(
                        cloud_account_id=account.id, name=name, cidr=parsed.cidr, network_addr=parsed.network,
                        broadcast_addr=parsed.broadcast, prefix_len=parsed.prefix_len, provider=provider,
                        region=field("region", None), owner_team=field("owner_team", None),
                        business_unit_name=field("business_unit_name", None),
                        environment_name=field("environment_name", None), vrf=field("vrf", None),
                        vlan=field("vlan", None), firewall=field("firewall", None), notes=field("notes", None),
                    )
                    db.add(network)
                    row_status = "created"

                db.flush()
                overlap_warnings = overlaps_for_cidr(db, parsed.cidr, exclude_network_id=network.id, provider=provider)
        except (CidrError, ValueError) as e:
            results.append({"row": row_num, "status": "error", "message": str(e)})
            continue

        results.append({
            "row": row_num, "status": row_status, "cidr": parsed.cidr, "name": name,
            "network_id": str(network.id), "overlap_warnings": overlap_warnings,
        })

    db.commit()
    return {
        "created": sum(1 for r in results if r["status"] == "created"),
        "updated": sum(1 for r in results if r["status"] == "updated"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "rows": results,
    }


def _occupied_within_network(db: Session, network: Network) -> list[alloc.Range]:
    subnets = db.execute(select(Subnet).where(Subnet.network_id == network.id)).scalars().all()
    return [alloc.Range(s.network_addr, s.broadcast_addr) for s in subnets]


def free_space_summary(db: Session, network_id: uuid.UUID) -> dict:
    network = db.get(Network, network_id)
    if not network:
        raise IpamError("network not found")
    occupied = _occupied_within_network(db, network)
    free = alloc.free_ranges(network.network_addr, network.broadcast_addr, occupied)
    total_addresses = network.broadcast_addr - network.network_addr + 1
    total_free = sum(r.end - r.start + 1 for r in free)
    return {
        "network": {"id": str(network.id), "cidr": network.cidr, "provider": network.provider},
        "total_addresses": total_addresses,
        "total_free": total_free,
        "free": [{"range": alloc.range_to_cidr_or_span(r.start, r.end), "addresses": r.end - r.start + 1} for r in free],
    }


def preview_allocation(db: Session, network_id: uuid.UUID, hosts: int) -> dict:
    network = db.get(Network, network_id)
    if not network:
        raise IpamError("network not found")
    occupied = _occupied_within_network(db, network)
    try:
        result = alloc.suggest_allocation(
            network.network_addr, network.broadcast_addr, network.prefix_len, hosts, occupied,
        )
    except alloc.AllocationError as e:
        raise IpamError(e.message, e.free) from e
    return {
        "network": {"id": str(network.id), "cidr": network.cidr, "provider": network.provider},
        "hosts": hosts,
        "prefix_len": result.prefix_len,
        "usable_hosts": result.usable_hosts,
        "block_size": result.block_size,
        "suggested_cidr": result.suggested_cidr,
        "free": result.free,
    }


def allocate_subnet(
    db: Session, network_id: uuid.UUID, hosts: int, *,
    name: str | None, availability_zone: str | None, owner_team: str | None, application: str | None,
) -> Subnet:
    preview = preview_allocation(db, network_id, hosts)  # recompute server-side; never trust a client-supplied CIDR
    parsed = parse_cidr(preview["suggested_cidr"])
    subnet = Subnet(
        network_id=network_id, name=name, cidr=parsed.cidr, network_addr=parsed.network,
        broadcast_addr=parsed.broadcast, prefix_len=parsed.prefix_len,
        availability_zone=availability_zone, owner_team=owner_team, application=application,
    )
    db.add(subnet)
    db.commit()
    db.refresh(subnet)
    return subnet
