from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

# The firewall/security-manager integrations this table stores credentials
# for, per claude/firewall-policy-automation-design.md §3.10
# (enforcement_point.credentials_ref) and the fwauto executor notes. This is
# the "Integrations" tab: one page to hold every access key the future
# execution automation (Panorama/FortiManager/direct-FortiGate adapters)
# will need, kept in one place and encrypted at rest rather than scattered
# across engineers' notes or .env files on laptops.
#
# vendor values:
#   "panorama"   - a Panorama manager. NGFWs it manages are represented as
#                  child rows (parent_id set, vendor="ngfw") rather than
#                  separate credentialed integrations, matching the design
#                  doc's "target the device group, never individual serials"
#                  guidance — the child row just records which device group
#                  a given managed firewall lives in for reference/PoA
#                  rendering, it does not hold its own secret.
#   "pan_os"     - a standalone PAN-OS firewall managed directly, e.g. the
#                  on-prem PA-5260 (not behind a Panorama in this estate).
#   "fortigate"  - a FortiGate managed directly via its own REST API.
#   "ngfw"       - a Palo Alto NGFW that sits behind a "panorama" row above
#                  it (parent_id required); device_group names where it
#                  lives on the manager. Holds no secret of its own.
INTEGRATION_VENDORS = ["panorama", "pan_os", "fortigate", "ngfw"]

# "api_key" - PAN-OS API key (Panorama/PA-5260), or a FortiGate API token.
# "username_password" - basic creds, used to mint a PAN-OS API key via
#   keygen, or as an admin login for a FortiGate that has no token issued.
INTEGRATION_AUTH_TYPES = ["api_key", "username_password"]


class FirewallIntegration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One credentialed connection to a firewall or firewall manager. The
    secret (API key or password) is stored only as a Fernet ciphertext
    (app/services/secrets.py) — the API never returns it, only a masked
    last-4 preview, and it is decrypted in-process only when a call to the
    device is actually made (test-connection today; the execution adapters
    from claude/panorama-executor-implementation.md's fwauto package would
    be the other reader once wired in).
    """

    __tablename__ = "firewall_integrations"

    vendor: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=443)
    verify_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    auth_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    secret_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    secret_last4: Mapped[str] = mapped_column(String(8), nullable=False, default="")

    # "ngfw" children only: which Panorama device group this firewall lives
    # in, and an optional serial for reference in generated PoAs.
    device_group: Mapped[str | None] = mapped_column(String(128), nullable=True)
    serial: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("firewall_integrations.id", ondelete="CASCADE"), nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # ok | error
    last_test_message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )
