"""Phase 3 — Cloud Networks: the last piece of "network source of truth"
docs/ERD.md's "Tables designed, not yet migrated" section reserved for this
phase (`network_interfaces`, "ENIs/NICs discovered per cloud"), plus a
deliberate extension this phase adds alongside it: `NetworkPeering`
(VPC/VNet/VCN peering connections). Peering already appears as a route
`target_type` (`vpc_peering`) from Phase 3's Routing work — this table is
that connection made into a first-class object instead of only ever being
implied by a route.

`CloudNetworkInterface` mirrors `RouteTable`'s manual/discovered provenance
convention rather than IPAM's external_source/external_ref/last_synced_at
triple, since interfaces arrive from the same discovery sweep as their
network and subnet, not a separate sync job — same rationale as
`app/models/routing.py`'s docstring. `security_groups` is a free-text JSONB
list, not a normalized `security_groups`/`security_rules` object — that's
Phase 6's job per ERD.md's reservation, and this is the same "deliberate,
documented simplification" pattern as `Network.firewall`'s own free-text
field and Routing's one-table-per-network choice.

`NetworkPeering` resolves both sides by `Network.name` (see
`app/providers/base.py::DiscoveredPeering`'s docstring for why: `Network`
has no queryable external_id column today, only a free-text `notes` field).
Self-peering is rejected at the DB level (`ck_peerings_distinct_networks`)
the same way `Route`'s exactly-one-owner invariant is — a real constraint,
not just application-level convention. The (A,B)/(B,A) duplicate-pair
problem — the same peering discoverable from either side's account — is
handled in `app/services/cloud_networks.py` by always storing the pair in a
canonical order (network_a_id < network_b_id) before upserting, rather than
a second unique index that would have to special-case both orderings.
"""
from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class CloudNetworkInterface(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """An ENI/NIC/VNIC — one representative interface per network's first
    subnet in this delivery's mock providers, same "one representative
    object per network" depth as `RouteTable`. Real providers can discover
    as many as actually exist; nothing here caps the count."""

    __tablename__ = "cloud_network_interfaces"

    subnet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subnets.id", ondelete="CASCADE"))

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    private_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    public_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    attached_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="in_use")  # in_use|available
    security_groups: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # free-text names, see docstring

    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")  # manual|discovered
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    subnet: Mapped["Subnet"] = relationship()  # noqa: F821


class NetworkPeering(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A VPC/VNet/VCN peering connection between two networks. Stored with
    `network_a_id`/`network_b_id` in a canonical (lower-uuid-first) order by
    the ingestion service so the same real-world connection — discoverable
    from either side's cloud account — upserts to one row instead of two;
    see this module's docstring for why that's a service-layer concern
    rather than a second DB constraint."""

    __tablename__ = "network_peerings"
    __table_args__ = (
        CheckConstraint("network_a_id != network_b_id", name="ck_peerings_distinct_networks"),
        UniqueConstraint("network_a_id", "network_b_id", name="uq_peerings_pair"),
    )

    network_a_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("networks.id", ondelete="CASCADE"))
    network_b_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("networks.id", ondelete="CASCADE"))

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active|pending|rejected|expired
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")  # manual|discovered
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    network_a: Mapped["Network"] = relationship(foreign_keys=[network_a_id])  # noqa: F821
    network_b: Mapped["Network"] = relationship(foreign_keys=[network_b_id])  # noqa: F821
