from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

# Cloud credentials for the same Integrations page as
# app/models/integration.py's FirewallIntegration — the other half of "one
# page to hold every access key" the user asked for, this time so
# discovery (app/services/discovery.py) can pull LIVE VPCs/VNets/VCNs/
# subnets into the network inventory instead of only the demo mock data.
# See app/providers/{aws,azure,gcp,oci}.py for the adapters that read
# these credentials, and app/providers/base.py's rule that no cloud SDK
# may be imported outside that package.
#
# One row per (vendor, account_identifier) — account_identifier matches
# cloud_accounts.account_identifier (an AWS account id, Azure subscription
# id, GCP project id, or OCI tenancy/compartment OCID), which is how
# discovery looks up which credential to use for a given cloud account
# without needing a hard foreign key (a cloud account can be seeded from
# the mock providers before any real credential exists for it).
CLOUD_VENDORS = ["aws", "azure", "gcp", "oci"]


class CloudIntegration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Credentials are vendor-shaped (an AWS access key pair looks nothing
    like a GCP service-account JSON key), so rather than a rigid column per
    possible field, the whole credentials dict is JSON-encoded and
    Fernet-encrypted into `credentials_ciphertext` (app/services/secrets.py).
    `credential_summary` is the only piece ever shown in the clear — a
    short, non-secret preview (e.g. an access key's last 4 chars, or a
    service account's client_email) computed at save time by
    app/services/cloud_credentials.py.
    """

    __tablename__ = "cloud_integrations"
    __table_args__ = (UniqueConstraint("vendor", "account_identifier", name="uq_cloud_integration_vendor_account"),)

    vendor: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    account_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    region_default: Mapped[str | None] = mapped_column(String(64), nullable=True)

    credentials_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    credential_summary: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # ok | error
    last_test_message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )
