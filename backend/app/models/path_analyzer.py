"""Phase 5 (Path Analyzer) — per docs/ROADMAP.md's "Immediate next
session's likely candidates" #1 and claude/firewall-policy-automation-
design.md §3.8's `POST /v1/simulate`: "a read-only 'is this already
allowed?' endpoint... **Ship it first.**" This is that endpoint, reusing
the design doc's shape rather than inventing a second one.

One row per simulate call, for the same reason Policy Optimizer and IPAM
Sync keep a run history (FwPolicyAnalysisRun, IpamSyncRun): a live check
against a real device is worth a durable record, and an honest "unknown"
result (no credentialed integration for a hop) is itself useful history,
not just a transient error to discard.
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class PathSimulationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "path_simulation_runs"

    source: Mapped[str] = mapped_column(String(64), nullable=False)
    destination: Mapped[str] = mapped_column(String(64), nullable=False)
    protocol: Mapped[str] = mapped_column(String(16), nullable=False)
    port_low: Mapped[int] = mapped_column(Integer, nullable=False)
    port_high: Mapped[int] = mapped_column(Integer, nullable=False)

    # allowed | blocked | not_currently_allowed | unknown
    overall_verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    # [{firewall, integration_id, verdict, covering_rule, blocking_rule, notes, error}]
    hops_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    notes_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    source_network_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("networks.id", ondelete="SET NULL"), nullable=True,
    )
    destination_network_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("networks.id", ondelete="SET NULL"), nullable=True,
    )
    triggered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )
