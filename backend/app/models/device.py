"""Network device / interface inventory — the rest of Phase 2's "network
source of truth" beyond IPAM: on-prem and cloud-adjacent devices (routers,
switches, firewalls, load balancers) discovered via SNMP (mocked here, same
pattern as the AWS mock discovery flow) or entered by hand. Mirrors the
Network/Subnet shape deliberately: a device "contains" interfaces the same
way a network "contains" subnets.
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

VALID_DEVICE_TYPES = ("router", "switch", "firewall", "load_balancer", "other")


class Device(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "devices"

    environment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("environments.id"))

    hostname: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    vendor: Mapped[str | None] = mapped_column(String(64), nullable=True)  # cisco|juniper|paloalto|fortinet|generic|...
    device_type: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    mgmt_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    site: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # "manual" (created via the API/UI) or "snmp" (discovered) — mirrors how
    # cloud_accounts distinguishes real vs. mock provider data, but here on
    # the device row itself since there's no separate account concept.
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # provider-native id, when source=snmp
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    interfaces: Mapped[list["Interface"]] = relationship(back_populates="device", cascade="all, delete-orphan")


class Interface(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "interfaces"

    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"))
    # Best-effort cross-link into IPAM: set when the interface's ip_address
    # falls inside a subnet NetSphere already knows about. Nullable and set
    # by app/services/devices.py, not enforced — an interface with no
    # matching subnet (the common case for a fresh on-prem mgmt range) is
    # not an error.
    subnet_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subnets.id", ondelete="SET NULL"), nullable=True,
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. GigabitEthernet0/1
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    mac_address: Mapped[str | None] = mapped_column(String(32), nullable=True)
    admin_status: Mapped[str] = mapped_column(String(16), nullable=False, default="up")
    oper_status: Mapped[str] = mapped_column(String(16), nullable=False, default="up")
    speed_mbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vlan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    device: Mapped["Device"] = relationship(back_populates="interfaces")
