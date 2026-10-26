from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

VALID_PROVIDERS = ("aws", "azure", "gcp", "oci", "onprem")


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    business_units: Mapped[list["BusinessUnit"]] = relationship(back_populates="organization")


class BusinessUnit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "business_units"

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="business_units")
    environments: Mapped[list["Environment"]] = relationship(back_populates="business_unit")


class Environment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "environments"

    business_unit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("business_units.id"))
    name: Mapped[str] = mapped_column(String(64), nullable=False)  # prod | staging | dev | ...

    business_unit: Mapped["BusinessUnit"] = relationship(back_populates="environments")
    cloud_accounts: Mapped[list["CloudAccount"]] = relationship(back_populates="environment")


class CloudAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cloud_accounts"

    environment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("environments.id"))
    provider: Mapped[str] = mapped_column(String(16), nullable=False)  # aws|azure|gcp|oci|onprem
    account_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    # Pointer only — e.g. "vault:secret/netsphere/aws/123456789012" or an IAM
    # role ARN. Never a raw key/secret. See ARCHITECTURE.md §5.
    credential_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    region_default: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")

    environment: Mapped["Environment"] = relationship(back_populates="cloud_accounts")
