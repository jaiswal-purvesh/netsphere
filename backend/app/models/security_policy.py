"""Phase 6 — Security Policies: normalized cloud NSG/SG/SL objects, plus the
RITM intake batch that feeds them into the existing fw-automation pipeline
(app/models/fw_automation.py).

Fills the reservation `app/models/cloud_networks.py`'s `CloudNetworkInterface.
security_groups` docstring made explicit: "`security_groups` is a free-text
JSONB list, not a normalized `security_groups`/`security_rules` object —
that's Phase 6's job per ERD.md's reservation." This module is that job.

Design choice — reuse the pipeline, generalize the target:
`FwIntent`/`FwPlan`/`FwApproval`/`FwExecution` (app/models/fw_automation.py)
already implement the whole intent -> plan (guardrails + redundancy) -> PoA
-> approve -> execute -> verify -> rollback machine, built for one
enforcement point (a Panorama device group). Rather than a parallel
cloud-only pipeline, `FwIntent` gains a `target_kind` discriminator
("firewall" | "azure_nsg" | "aws_sg" | "gcp_firewall" | "oci_security_list")
and a `security_group_id` FK alongside the existing `integration_id`, with a
real `CheckConstraint` requiring exactly one of the two — same
exactly-one-owner convention as `Route`/`Circuit`/`VpnConnection`. See
app/services/security_policy_adapter.py for the cloud-side adapter that
`fw_plan.py`/`fw_executor.py` dispatch to when `target_kind != "firewall"`.

Two new tables:
  SecurityGroup - one per (network, provider) — Azure NSG / AWS SG / GCP VPC
                  firewall rule set / OCI Security List, modeled uniformly.
                  Auto-created on first resolved intake row targeting a
                  network that doesn't have one yet (deterministic name
                  `<network.name>-sg`, tagged `source="auto"`), or
                  discovered from `CloudNetworkInterface.security_groups`
                  (Phase 3's free-text list) via a one-time backfill — see
                  app/services/security_policy_resolve.py.
  SecurityRule  - one normalized 5-tuple rule inside a SecurityGroup. This
                  is deliberately one row per (direction, protocol, port
                  range, single CIDR) rather than modeling each vendor's
                  native list-valued rule shape (an Azure NSG rule's
                  source/destination *list*, an AWS SG rule's multiple
                  IpRanges) — same "deliberately NOT a perfect universal
                  abstraction" bet claude/firewall-policy-automation-
                  design.md §0 makes for the firewall side; a multi-CIDR
                  rule from a vendor round-trips as N rows sharing
                  `rule_group_key`, an escape hatch this phase doesn't need
                  to exercise, not a schema limitation.

Vendor-shape notes deliberately NOT modeled as separate columns (kept as
`extra_json`, same "carried through, not invented" convention as FwIntent.
extra_fields_json): Azure NSG rule descriptions and NSG-level default
rules, AWS SG rule descriptions, GCP firewall rule target-tags/service-
accounts, OCI Security List's stateless flag. `priority` is the one field
promoted to a real column because both Azure and GCP need it to evaluate
correctly and the plan/diff renderer must reason about placement.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

SECURITY_GROUP_PROVIDERS = ["azure_nsg", "aws_sg", "gcp_firewall", "oci_security_list"]
SECURITY_RULE_DIRECTIONS = ["inbound", "outbound"]
SECURITY_RULE_ACTIONS = ["allow", "deny"]


class SecurityGroup(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "security_groups"

    network_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("networks.id", ondelete="CASCADE"))
    cloud_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cloud_accounts.id", ondelete="CASCADE"))

    provider: Mapped[str] = mapped_column(String(24), nullable=False)  # one of SECURITY_GROUP_PROVIDERS
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")  # manual|discovered|auto
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    network: Mapped["Network"] = relationship()  # noqa: F821
    rules: Mapped[list["SecurityRule"]] = relationship(back_populates="security_group", cascade="all, delete-orphan")


class SecurityRule(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """One normalized rule. `managed_by_fwauto=True` marks a rule this
    pipeline created (§3.4's `managed-by:fwauto` tag convention) — a rule
    discovered from existing `CloudNetworkInterface.security_groups` free
    text during backfill is `source="discovered"`, `managed_by_fwauto=False`,
    and is read-only from this pipeline's point of view (never mutated,
    only ever read for redundancy/shadow analysis — the same "never mutate
    an object the system did not create" rule §3.4 applies to Panorama
    objects)."""

    __tablename__ = "security_rules"

    security_group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("security_groups.id", ondelete="CASCADE"))

    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="inbound")
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)  # azure_nsg / gcp_firewall evaluate by priority
    action: Mapped[str] = mapped_column(String(8), nullable=False, default="allow")

    protocol: Mapped[str] = mapped_column(String(16), nullable=False, default="tcp")
    port_low: Mapped[int | None] = mapped_column(Integer, nullable=True)
    port_high: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cidr: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active|disabled
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")  # manual|discovered|automated
    managed_by_fwauto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rule_group_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    ticket_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    extra_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    security_group: Mapped["SecurityGroup"] = relationship(back_populates="rules")


class SecurityPolicyBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One RITM/connectivity-request sheet upload — Appendix A "PHASE 0 —
    INTAKE" of claude/firewall-policy-automation-design.md, generalized
    beyond the Panorama-only CSV batch flow that appendix describes to any
    of the target kinds `app/services/security_policy_adapter.py` supports.
    Kept even though every row's outcome is also visible on the `FwIntent`
    rows it created (via `FwIntent.batch_id`), because the *unresolvable*
    rows — no CIDR/network match found — are never turned into an intent at
    all and would otherwise vanish; `unresolved_rows_json` is where they're
    kept, one entry per skipped row with its reason, so intake is never
    silently lossy (this project's running rule)."""

    __tablename__ = "security_policy_batches"

    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_format: Mapped[str] = mapped_column(String(16), nullable=False, default="")  # xlsx|csv|ods
    ticket_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resolved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unresolved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unresolved_rows_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    parse_warnings_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
