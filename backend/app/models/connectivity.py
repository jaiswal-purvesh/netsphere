"""Phase 8 — Connectivity: the `vpn_connections`/`bgp_sessions`/`circuits`/
`connectivity_links` quartet docs/ERD.md reserved for "VPN/DX/ER/
Interconnect/FastConnect monitoring." Built in response to the user
describing their actual hybrid network: each cloud reaches on-prem over
its own dedicated interconnect (AWS Direct Connect, Azure ExpressRoute,
GCP Cloud Interconnect, OCI FastConnect) riding an MPLS backbone with
VRF-based segmentation, not a flat shared network.

`Circuit` is the interconnect itself — the cloud-side end (owned by a
`CloudAccount`) or the on-prem-side end (owned by a `Device`), each
discovered and ingested independently even though a matched pair describes
one real physical link (see `app/services/connectivity.py`'s docstring for
why that's a service-layer concern, not a schema one). Ownership mirrors
`Route`'s exactly-one-owner convention (`app/models/routing.py`) with a
real `CheckConstraint`, not just application-level convention.

`ConnectivityLink` cross-links a `Circuit` to the `Network` it attaches to
on the cloud side (an on-prem circuit has no `Network` to link — its
"other end" is the cloud-side `Circuit` row a future session could match
by VRF/location, not modeled as a direct FK here to avoid coupling two
independently-discovered rows together).

`BgpSession` is the control-plane session running over a `Circuit` — kept
circuit-scoped only (not also device/network-scoped) as this phase's own
deliberate simplification, the same kind of honest trade-off as Routing's
one-table-per-network model: a circuit's own BGP peering is what's being
monitored here, not a general routing-protocol model.

`VpnConnection` is a separate, lighter path — an IPsec site-to-site VPN,
typically a backup alongside a dedicated circuit, riding the public
internet rather than a physical interconnect. It attaches directly to a
`Network` (nullable) or a `Device` (nullable), same exactly-one-owner
convention as `Circuit`/`Route`.
"""
from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

VALID_CIRCUIT_TYPES = ("direct_connect", "expressroute", "interconnect", "fastconnect", "mpls")


class Circuit(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "circuits"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN cloud_account_id IS NULL THEN 0 ELSE 1 END) "
            "+ (CASE WHEN device_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_circuits_exactly_one_owner",
        ),
    )

    cloud_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cloud_accounts.id", ondelete="CASCADE"), nullable=True,
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=True,
    )

    circuit_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    vrf: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bandwidth_mbps: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active|provisioning|down|decommissioned

    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")  # manual|discovered
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    cloud_account: Mapped["CloudAccount | None"] = relationship()  # noqa: F821
    device: Mapped["Device | None"] = relationship()  # noqa: F821
    bgp_sessions: Mapped[list["BgpSession"]] = relationship(back_populates="circuit", cascade="all, delete-orphan")
    links: Mapped[list["ConnectivityLink"]] = relationship(back_populates="circuit", cascade="all, delete-orphan")


class ConnectivityLink(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Which cloud `Network` a `Circuit` attaches to. Only cloud-side
    circuits get one of these — an on-prem circuit's "other end" is a
    separately-discovered cloud-side `Circuit` row, not this network
    directly (see this module's own docstring)."""

    __tablename__ = "connectivity_links"

    network_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("networks.id", ondelete="CASCADE"))
    circuit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("circuits.id", ondelete="CASCADE"))

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active|pending|down
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")  # manual|discovered
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    network: Mapped["Network"] = relationship()  # noqa: F821
    circuit: Mapped["Circuit"] = relationship(back_populates="links")


class BgpSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bgp_sessions"

    circuit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("circuits.id", ondelete="CASCADE"))

    local_asn: Mapped[int] = mapped_column(BigInteger, nullable=False)
    peer_asn: Mapped[int] = mapped_column(BigInteger, nullable=False)
    local_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    peer_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="established")  # established|idle|down

    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")  # manual|discovered
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    circuit: Mapped["Circuit"] = relationship(back_populates="bgp_sessions")


class VpnConnection(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "vpn_connections"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN network_id IS NULL THEN 0 ELSE 1 END) "
            "+ (CASE WHEN device_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_vpn_connections_exactly_one_owner",
        ),
    )

    network_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("networks.id", ondelete="CASCADE"), nullable=True,
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=True,
    )

    peer_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="up")  # up|down|degraded

    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")  # manual|discovered
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    network: Mapped["Network | None"] = relationship()  # noqa: F821
    device: Mapped["Device | None"] = relationship()  # noqa: F821
