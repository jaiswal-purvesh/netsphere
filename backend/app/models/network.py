from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Network(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A VPC / VNet / VCN / on-prem network. Mirrors the ip-pool-lookup
    tool's `ip_pools` table, extended with the org/account hierarchy and a
    self-referencing `parent_network_id` for VPC/subnet-of-subnet nesting
    (same idea as that tool's `parent_id`, renamed for clarity now that a
    separate `Subnet` table also exists below it).
    """

    __tablename__ = "networks"
    __table_args__ = (
        Index("ix_networks_range", "network_addr", "broadcast_addr"),
    )

    cloud_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cloud_accounts.id"))
    parent_network_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("networks.id", ondelete="SET NULL"), nullable=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cidr: Mapped[str] = mapped_column(String(64), nullable=False)
    network_addr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    broadcast_addr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    prefix_len: Mapped[int] = mapped_column(nullable=False)

    provider: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # denormalized
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_team: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_unit_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    environment_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vrf: Mapped[str | None] = mapped_column(String(128), nullable=True)
    vlan: Mapped[str | None] = mapped_column(String(32), nullable=True)
    firewall: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Provenance for a network pulled in by an external source (an IPAM
    # integration sync, e.g. app/services/ipam_sync.py against TCPWave) as
    # opposed to one entered by hand through this UI or the CSV importer —
    # both left null for those. `external_ref` is that source's own stable
    # identifier for the object (TCPWave's network address/name), used
    # together with `external_source` as the idempotency key on re-sync,
    # independent of (cloud_account_id, cidr) in case the CIDR itself
    # changes upstream.
    external_source: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    external_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    subnets: Mapped[list["Subnet"]] = relationship(back_populates="network", cascade="all, delete-orphan")


class Subnet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "subnets"
    __table_args__ = (
        Index("ix_subnets_range", "network_addr", "broadcast_addr"),
    )

    network_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("networks.id", ondelete="CASCADE"))
    # Best-effort cross-link to Phase 3's routing inventory: which route
    # table this subnet is associated with, when that's known. Nullable and
    # set by app/services/routing.py's discovery ingestion — same
    # not-enforced, cross-link-when-known convention as Interface.subnet_id
    # in app/models/device.py.
    route_table_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("route_tables.id", ondelete="SET NULL"), nullable=True,
    )

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cidr: Mapped[str] = mapped_column(String(64), nullable=False)
    network_addr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    broadcast_addr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    prefix_len: Mapped[int] = mapped_column(nullable=False)

    availability_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_team: Mapped[str | None] = mapped_column(String(255), nullable=True)
    application: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")

    external_source: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    external_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    network: Mapped["Network"] = relationship(back_populates="subnets")
    ip_addresses: Mapped[list["IPAddress"]] = relationship(back_populates="subnet", cascade="all, delete-orphan")


class IPAddress(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ip_addresses"
    __table_args__ = (
        Index("ix_ip_addresses_ip_int", "ip_int"),
        # Wasn't needed while nothing wrote to this table (see
        # app/services/ipam_sync.py's docstring); a sync upserting
        # thousands of IP objects needs a real idempotency key.
        UniqueConstraint("subnet_id", "ip_address", name="uq_ip_addresses_subnet_ip"),
    )

    subnet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subnets.id", ondelete="CASCADE"))

    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)  # IPv4 today; sized for IPv6 later
    ip_int: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="allocated")  # allocated|reserved|free
    assigned_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mac_address: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    external_source: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    external_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    subnet: Mapped["Subnet"] = relationship(back_populates="ip_addresses")
