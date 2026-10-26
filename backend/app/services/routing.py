"""Phase 3 — Routing ingestion. Upserts a `DiscoveredRouteTable`/
`DiscoveredRoute` result (see app/providers/base.py) into `route_tables`/
`routes`, called from app/services/discovery.py (cloud route tables, one
per network) and app/services/devices.py (on-prem static routes, one set
per device) right after each one upserts its own network/device row —
same idempotent-by-natural-key upsert shape as both of those already use,
not a third pattern.

**Deliberate simplification** (documented here once, referenced from
providers/base.py and docs/ROADMAP.md rather than re-explained in three
places): this phase models "one route table per network." A real AWS VPC
can have several route tables with per-subnet associations; GCP has no
route-table object at all, only network-scoped routes. Collapsing each
provider's routing down to a single normalized table per network is the
same kind of real, acknowledged trade-off Path Analyzer's
`Network.firewall` single-field model already makes — accurate for what
this phase needs (an inventory of what's routing where), not yet accurate
enough for per-subnet route selection, which is exactly what a future
multi-hop path-computation pass over `routes` would need to add.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.routing import Route, RouteTable
from app.providers.base import DiscoveredRoute, DiscoveredRouteTable


def _upsert_routes(db: Session, existing_routes: list[Route], discovered: list[DiscoveredRoute], **owner_kwargs) -> tuple[int, int]:
    """`owner_kwargs` is `{"route_table_id": id}` or `{"device_id": id}` —
    whichever FK owns these rows. Natural key is (owner, destination_cidr,
    target_type): a device or route table rarely has two routes to the
    same destination via the same kind of target, and when it does (e.g.
    ECMP) the later discovery pass simply updates target_ref/state on the
    first match rather than duplicating rows — acceptable for an inventory
    view, revisited if ECMP-aware routing ever needs its own model."""
    by_key = {(r.destination_cidr, r.target_type): r for r in existing_routes}
    created = updated = 0
    for d in discovered:
        key = (d.destination_cidr, d.target_type)
        existing = by_key.get(key)
        if existing:
            existing.target_ref = d.target_ref
            existing.state = d.state
            existing.external_id = d.external_id
            updated += 1
        else:
            db.add(Route(
                destination_cidr=d.destination_cidr, target_type=d.target_type, target_ref=d.target_ref,
                state=d.state, external_id=d.external_id, **owner_kwargs,
            ))
            created += 1
    return created, updated


def upsert_route_table_for_network(
    db: Session, network_id: uuid.UUID, discovered: DiscoveredRouteTable | None,
) -> dict:
    """Called right after app/services/discovery.py upserts a Network row.
    A `None` discovered table (a provider that returned no routing info for
    this network) is a no-op, not an error — routing data is additive on
    top of the network/subnet discovery that already worked before this
    phase existed."""
    if discovered is None:
        return {"route_tables_created": 0, "route_tables_updated": 0, "routes_created": 0, "routes_updated": 0}

    existing = db.execute(
        select(RouteTable).where(RouteTable.network_id == network_id, RouteTable.external_id == discovered.external_id),
    ).scalar_one_or_none()

    if existing:
        existing.name = discovered.name
        existing.is_main = discovered.is_main
        existing.source = "discovered"
        route_table_row = existing
        rt_created, rt_updated = 0, 1
    else:
        route_table_row = RouteTable(
            network_id=network_id, name=discovered.name, is_main=discovered.is_main,
            source="discovered", external_id=discovered.external_id,
        )
        db.add(route_table_row)
        db.flush()  # get route_table_row.id before adding routes
        rt_created, rt_updated = 1, 0

    existing_routes = db.execute(select(Route).where(Route.route_table_id == route_table_row.id)).scalars().all()
    routes_created, routes_updated = _upsert_routes(
        db, list(existing_routes), discovered.routes, route_table_id=route_table_row.id,
    )
    return {
        "route_tables_created": rt_created, "route_tables_updated": rt_updated,
        "routes_created": routes_created, "routes_updated": routes_updated,
    }


def upsert_routes_for_device(db: Session, device_id: uuid.UUID, discovered: list[DiscoveredRoute]) -> dict:
    """Called right after app/services/devices.py upserts a Device row. An
    empty `discovered` list (most switches — L2 devices don't route) is a
    no-op, matching the same "additive, not required" contract as the
    network side above."""
    if not discovered:
        return {"routes_created": 0, "routes_updated": 0}
    existing_routes = db.execute(select(Route).where(Route.device_id == device_id)).scalars().all()
    created, updated = _upsert_routes(db, list(existing_routes), discovered, device_id=device_id)
    return {"routes_created": created, "routes_updated": updated}
