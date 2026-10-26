"""On-prem IPAM source integrations — the ONPREM network team's system of
record (TCPWave IPAM/DDI today) as a *pull* source for NetSphere's own
networks/subnets/ip_addresses tables, the same "one credential, one page"
pattern as FirewallIntegration (app/models/integration.py) and
CloudIntegration (app/models/cloud_integration.py).

TCPWave's REST API (see app/services/tcpwave_adapter.py's docstring for the
full research writeup and — importantly — what's confirmed vs. inferred
about it) authenticates with either a long-lived session token
(`TIMS-Session-Token` header, minted via /tims/rest/auth_token/get) or a
client TLS certificate. Both are supported here: the token is Fernet-
encrypted the same way a firewall integration's API key is
(app/services/secrets.py); the client cert+key are stored the same way,
separately, since a deployment may use either or both together.

`cloud_account_id` is required to actually run a sync (validated in
app/services/ipam_sync.py, not at the DB layer, so a partially-configured
integration can still be saved and edited) — it's the existing "onprem"
CloudAccount (app/models/org.py's provider="onprem", already a first-class
value everywhere else in this app: VALID_PROVIDERS, the dashboard's
by-provider breakdown) that discovered networks/subnets attach under,
exactly like a CloudIntegration's discovered VPCs attach under an "aws"/
"azure"/etc. CloudAccount. Reusing the existing org hierarchy rather than
inventing a parallel one for on-prem data.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

IPAM_INTEGRATION_VENDORS = ["tcpwave"]
IPAM_AUTH_MODES = ["token", "client_cert"]


class IpamIntegration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ipam_integrations"

    vendor: Mapped[str] = mapped_column(String(16), nullable=False, default="tcpwave")
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # TCPWave's own examples all use 7443, never the plain HTTPS 443 — see
    # the adapter module's docstring for why this isn't hardcoded.
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=7443)
    verify_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    auth_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="token")
    token_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    token_last4: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    client_cert_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    client_key_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # TCPWave scopes objects by organization_name; leave blank to pull every
    # organization the token/cert can see.
    organization_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    cloud_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cloud_accounts.id"), nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # ok | error
    last_test_message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )


class IpamSyncRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per "Sync now" click — mirrors FwPolicyAnalysisRun's role for
    Policy Optimizer. Kept even on failure (status="error") so a flaky
    on-prem link shows up as a visible history, not a silent no-op."""

    __tablename__ = "ipam_sync_runs"

    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ipam_integrations.id", ondelete="CASCADE"), nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")  # ok | error
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    networks_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    networks_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    networks_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subnets_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subnets_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subnets_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ips_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ips_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ips_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    triggered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )
