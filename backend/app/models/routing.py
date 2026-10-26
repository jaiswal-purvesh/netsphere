"""Phase 3 — Routing: the other half of "network source of truth" the
original spec called for (Module 4), alongside IPAM and device/interface
inventory. `route_tables` holds one row per network's routing (cloud side,
via discovery — see app/services/routing.py's docstring for the deliberate
one-table-per-network simplification); `routes` holds the individual
destination/target rows, owned by either a route table (cloud) or a device
(on-prem static routes) — never both, enforced at the DB level below.

This is exactly the `route_tables`/`routes` pair docs/ERD.md's "Tables
designed, not yet migrated" section reserved, described there as "consumed
by the path validator" — Path Analyzer's own multi-hop, route-aware path
computation (its currently-documented follow-up) is what a future session
wires this into; this phase is the inventory itself.
"""
from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

VALID_TARGET_TYPES = (
    "local", "internet_gateway", "nat_gateway", "vpc_peering", "transit_gateway",
    "vpn_gateway", "virtual_appliance", "next_hop", "interface", "instance", "other",
)


class RouteTable(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A network's routing table — cloud-side (VPC/VNet/VCN route table or
    GCP's network-scoped routes, normalized to the same shape) or an
    on-prem network entered by hand. Mirrors Device's manual/discovered
    provenance convention rather than IPAM's external_source/external_ref/
    last_synced_at triple, since route tables arrive from the same
    discovery sweep as their network, not a separate sync job."""

    __tablename__ = "route_tables"

    network_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("networks.id", ondelete="CASCADE"))

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_main: Mapped[bool] = mapped_column(nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")  # manual|discovered
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    network: Mapped["Network"] = relationship()  # noqa: F821
    routes: Mapped[list["Route"]] = relationship(back_populates="route_table", cascade="all, delete-orphan")


class Route(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One route, owned by exactly one of a RouteTable (cloud) or a Device
    (on-prem static route) — the CheckConstraint below is a real invariant,
    not just a convention, since a route with no owner or two owners is a
    data-integrity bug either way."""

    __tablename__ = "routes"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN route_table_id IS NULL THEN 0 ELSE 1 END) "
            "+ (CASE WHEN device_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_routes_exactly_one_owner",
        ),
    )

    route_table_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("route_tables.id", ondelete="CASCADE"), nullable=True,
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=True,
    )

    destination_cidr: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active|blackhole
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    route_table: Mapped["RouteTable | None"] = relationship(back_populates="routes")
    device: Mapped["Device | None"] = relationship()  # noqa: F821
