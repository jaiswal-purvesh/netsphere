"""Policy Optimizer / Firewall Analyzer — the whole-rulebase hygiene
capability FireMon ("Policy Analyzer"), Tufin ("SecureTrack"), and AlgoSec
("Firewall Analyzer") all lead with: pull the live rulebase from each
enforcement point, evaluate it rule-by-rule for the industry-standard smells
(any-any, shadowed/duplicate, overly-broad, disabled, unlogged), and give
each rule a lightweight review record (owner, last-reviewed date, note) so
a security team can work a cleanup queue instead of re-reading the whole
rulebase from scratch every audit cycle.

This reuses, not reinvents:
  - app/services/fw_panorama_adapter.fetch_rulebase() for the real pull off
    a live Panorama device group (already implemented, genuinely calls the
    device — no mocked data).
  - app/services/fw_redundancy's CIDR/service-containment primitives for
    the shadowed/duplicate-rule pairwise check (adapted here to run against
    every prior rule in a rulebase, not just one candidate new request).

Two tables:
  FwPolicyAnalysisRun - one row per "Analyze" click: which integration,
                        when, how many rules pulled, and the finding
                        summary (counts by severity) so the frontend can
                        render history without re-running the analysis.
  FwRuleRecord        - one row per rule *identity* (name) within an
                        integration, carrying the review workflow fields
                        (owner/last_reviewed_at/review_note) across runs —
                        a rule keeps its review history even as the
                        rulebase is re-pulled and re-analyzed, and
                        first_seen_at/last_seen_at let the UI flag a rule
                        that has quietly disappeared from the device since
                        the last pull.

Findings themselves (any-any, shadowed, etc.) are NOT stored as their own
table — they are recomputed fresh on every analysis run from the pulled
rulebase (matching this project's "nothing here is mocked or faked" ethos:
a finding is only ever as current as the live device) and returned inline
on FwPolicyAnalysisRun.findings_json plus mirrored onto the matching
FwRuleRecord.last_findings_json for the rule-list view.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class FwPolicyAnalysisRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fw_policy_analysis_runs"

    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("firewall_integrations.id", ondelete="CASCADE"), nullable=False,
    )
    device_group: Mapped[str | None] = mapped_column(String(128), nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")  # ok | error
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    rule_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # {critical: n, warn: n, info: n}
    severity_counts_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # full per-rule finding list this run produced: [{rule, category, severity, message, related_rule}]
    findings_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    triggered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )


class FwRuleRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One rule's cross-run identity + review workflow state. Uniquely keyed
    on (integration_id, device_group, rule_name) — Panorama rule names are
    unique within a device group's pre-rulebase."""

    __tablename__ = "fw_rule_records"

    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("firewall_integrations.id", ondelete="CASCADE"), nullable=False,
    )
    device_group: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Snapshot of the rule as of the most recent analysis run, for display
    # without re-fetching the device.
    action: Mapped[str] = mapped_column(String(16), nullable=False, default="allow")
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_cidrs_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    destination_cidrs_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    services_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # set to None (rather than deleted) the run a previously-seen rule stops
    # appearing on the device, so review history is never silently lost.
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_findings_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    owner: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
