from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class AuditLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only record of every mutating action. NOT hash-chained /
    tamper-evident in this phase — see ARCHITECTURE.md §5 for what that
    would take and why it's deferred (fwauto's `audit_event` design in
    firewall-policy-automation-design.md §3.10 is the reference for when
    this table needs that property).
    """

    __tablename__ = "audit_logs"

    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "ipam.subnet.create"
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[str] = mapped_column(String(16), default="success")  # success|failure
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
