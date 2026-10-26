"""Firewall rule execution automation — Phase 3 of
claude/firewall-policy-automation-design.md's phasing table ("Execute, one
vendor"), scoped to Panorama/PAN-OS only for this phase (FortiManager joins
in Phase 4). Ports the intent → plan → PoA → approval → execute → verify
pipeline from that design doc (§2.2, §3.1, §3.9, §3.10) and the fwauto
Appendix A phase flow (claude/panorama-executor-implementation.md), using
the credentials already stored in the Integrations tab
(app/models/integration.py) as the enforcement-point connection.

Five tables, one per pipeline stage that needs its own audit trail:

  FwIntent    - the normalized request (§3.1 PolicyIntent), plus the latest
                guardrail/redundancy analysis and overall lifecycle status.
  FwPlan      - one immutable rendered artifact + plan_hash per analysis run
                (§3.1 "render is pure"; re-planning creates a new row rather
                than mutating one, so a stale approval is provably stale).
  FwPoa       - the generated Plan of Action document for that plan, with a
                poa_revision hash binding it to the plan (§3.9).
  FwApproval  - records who approved which (plan_hash, poa_revision) pair —
                the pair the executor re-checks before every apply (§3.9
                "Revisioning and the signoff chain").
  FwExecution - one row per execute attempt: snapshot ref, vendor job ids,
                terminal state, verify result. Kept 1:1 with FwPlan for this
                phase (single enforcement point per intent); becomes 1:N
                over ExecutionTask-per-target in Phase 4 (§3.10).

Per the team's working decisions (2026-09):
  - auto-created Panorama objects are scoped Shared (not per-device-group);
    tagged managed-by:fwauto per §3.4.
  - this system's approval is an additional internal control layered on top
    of ServiceNow change approval, which remains the system of record for
    change authorization (§3.9 "State coupling", assumption A6). We do not
    gate on a ServiceNow state here yet — `ticket_ref` is recorded for the
    PoA and audit trail, and reconciliation is manual until a ServiceNow
    connector exists.

2026-09-23 addition — POA as source of truth: `FwPoaDocument` holds the
request-level fields of an uploaded/pasted Plan of Action (one document can
describe several firewall rules — "multiple firewall implementations" per
the ask), and each extracted rule becomes its own `FwIntent` linked back to
it via `poa_document_id`, so the engineer types source/destination/port
exactly once, in the POA, never again in this tool (see
app/services/poa_firewall_parser.py). `FwIntent` gained the richer
rule-metadata fields (zones, NAT, security profiles, environment) the
parser can extract; fields Phase 3's Panorama adapter does not yet act on
(URL filtering/IPS/antivirus/SSL-inspection profile, QoS, schedule, rule
position) are kept in `extra_fields_json` rather than invented columns —
they round-trip through the plan/PoA/evidence text so nothing is silently
dropped, and promoting one to a first-class, adapter-applied field is a
follow-up, not a schema change.

2026-09-29 addition — Phase 6, the target generalized beyond Panorama:
`target_kind` discriminates which of the two mutually-exclusive target
columns is set — `integration_id` (a `firewall_integrations` row, the
original Phase 3 shape, `target_kind="firewall"`) or `security_group_id`
(a `security_groups` row — Azure NSG / AWS SG / GCP firewall / OCI Security
List — `app/models/security_policy.py`, `target_kind` one of "azure_nsg" |
"aws_sg" | "gcp_firewall" | "oci_security_list"). A real `CheckConstraint`
(`ck_fw_intents_exactly_one_target`) enforces exactly one is set, the same
convention as `Route`/`Circuit`/`VpnConnection`'s exactly-one-owner rule.
`app/services/fw_plan.py` and `app/services/fw_executor.py` branch on
`target_kind`: `"firewall"` keeps the existing Panorama-only path
byte-for-byte; every cloud kind dispatches to
`app/services/security_policy_adapter.py`, which implements the same
render/apply/verify shape against `SecurityGroup`/`SecurityRule` rows
instead of a live device — there is no live NSG/SG/SL API in this delivery
(cloud accounts here are mock-discovered, per `app/providers/mock/`), so
"deploying" a cloud rule means writing the normalized `SecurityRule` row
that represents it, exactly as Panorama's own mock/lab adapter represents
a device's rulebase as rows this system controls. `batch_id` links an
intent back to the `SecurityPolicyBatch` (RITM sheet upload) that created
it, when it was; an intent created by hand or via the POA-parser path
leaves it null.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

FW_INTENT_ACTIONS = ["allow", "deny"]
FW_INTENT_LOGGING = ["none", "session_start", "session_end", "both"]
FW_ENVIRONMENTS = ["dev", "uat", "prod"]

# Phase 6 — the enforcement points a `FwIntent` can target. "firewall" is
# the original Phase 3 shape (a firewall_integrations row, Panorama/PAN-OS
# only so far); the other four are normalized cloud security-group kinds,
# each backed by a `SecurityGroup` row (app/models/security_policy.py).
FW_TARGET_KINDS = ["firewall", "azure_nsg", "aws_sg", "gcp_firewall", "oci_security_list"]

# §11's per-environment approval policy: how many distinct human approvals
# an intent in this environment needs before it can execute. DEV needs
# none (an engineer can self-approve — enforced in the approve endpoint,
# not by skipping the step so the audit trail still records who signed
# off); UAT and PROD both require a human distinct from the requester
# (Separation of Duties), PROD's extra weight is policy/process (only
# users holding the approve permission at all — same as today) rather than
# a second required signature, which would need a quorum model this phase
# does not build.
FW_ENVIRONMENT_APPROVALS_REQUIRED = {"dev": 0, "uat": 1, "prod": 1}

# Mirrors §2.2's status machine, narrowed to what a single-EP, Panorama-only
# phase actually exercises. NEEDS_HUMAN and PARTIAL exist per §3.11's
# asymmetric rollback policy even though a single enforcement point makes
# PARTIAL unreachable today — kept so the state machine does not need to
# change shape when Phase 4 adds multi-EP execution.
FW_INTENT_STATUSES = [
    "received", "analyzed", "no_change_required", "rejected",
    "awaiting_approval", "approved", "executing",
    "applied_verified", "partial", "failed", "needs_human", "rolled_back",
]


class FwPoaDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The uploaded/pasted Plan of Action itself — the source of truth
    (§2, §23). Request-level header fields live here once; each firewall
    rule the parser found inside it becomes a child FwIntent (below) rather
    than repeating these fields per rule. `raw_content` is kept verbatim
    (as text — binary originals such as .docx/.xlsx/.pdf are decoded to
    text/structure at parse time and are not re-openable from this row) so
    a parse can be audited or re-run without asking the engineer to
    re-upload."""

    __tablename__ = "fw_poa_documents"

    poa_ref: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    change_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    snow_ticket: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    application_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    business_owner: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    technical_owner: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    environment: Mapped[str] = mapped_column(String(16), nullable=False, default="prod")
    source_application: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    destination_application: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    business_justification: Mapped[str] = mapped_column(Text, nullable=False, default="")
    implementation_window: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    rollback_requirement: Mapped[str] = mapped_column(Text, nullable=False, default="")

    source_format: Mapped[str] = mapped_column(String(16), nullable=False)  # json|yaml|csv|text|docx|xlsx|pdf
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    parse_warnings_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    rule_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class FwIntent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One connectivity request — §3.1 PolicyIntent, flattened: source/
    destination are CIDR lists (name/tag resolution per §1.1 F2 is out of
    scope for this phase; the requester supplies resolved CIDRs directly,
    same simplification the fwauto CSV batch flow made for its first cut).
    Normally created by the POA parser (one row per extracted rule) rather
    than typed by hand — see poa_document_id below."""

    __tablename__ = "fw_intents"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN integration_id IS NULL THEN 0 ELSE 1 END) "
            "+ (CASE WHEN security_group_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_fw_intents_exactly_one_target",
        ),
    )

    requester_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    ticket_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    action: Mapped[str] = mapped_column(String(8), nullable=False)
    logging: Mapped[str] = mapped_column(String(16), nullable=False, default="session_end")

    # [{ "cidr": "10.42.16.0/24" }, ...]
    source_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    destination_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # [{ "proto": "tcp", "port_low": 5432, "port_high": 5432 }, ...]
    service_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Phase 6: which of the two mutually-exclusive target columns below is
    # populated — see FW_TARGET_KINDS and this module's 2026-09-29 docstring
    # addition. Defaults to "firewall" so every pre-Phase-6 row (all of
    # which have integration_id set, none have security_group_id) needs no
    # backfill.
    target_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="firewall")

    # target_kind == "firewall": a "panorama" or "pan_os" row in
    # firewall_integrations. device_group is required for panorama, ignored
    # (vsys context implied) for a standalone pan_os target.
    integration_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("firewall_integrations.id"), nullable=True)
    device_group: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # target_kind in ("azure_nsg", "aws_sg", "gcp_firewall",
    # "oci_security_list"): the normalized cloud security group this intent
    # deploys a rule into.
    security_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_groups.id", ondelete="CASCADE"), nullable=True,
    )

    # Set when this intent was created by the RITM/connectivity-request
    # sheet intake (app/services/security_policy_intake.py) rather than by
    # hand or via the POA-parser path.
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_policy_batches.id", ondelete="SET NULL"), nullable=True,
    )

    # --- POA-as-source-of-truth additions (2026-09-23) ---
    poa_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fw_poa_documents.id", ondelete="CASCADE"), nullable=True,
    )
    rule_id: Mapped[str | None] = mapped_column(String(64), nullable=True)   # engineer-supplied external rule id, if any
    rule_name: Mapped[str | None] = mapped_column(String(63), nullable=True)  # explicit name from the POA; auto-generated if absent
    environment: Mapped[str] = mapped_column(String(16), nullable=False, default="prod")
    source_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destination_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nat_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    nat_details_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    security_profile: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Catch-all for the rest of §3's rule metadata this phase's Panorama
    # adapter does not act on yet (url_filtering_profile, ips_profile,
    # antivirus_profile, ssl_inspection_profile, qos_requirement, schedule,
    # rule_position, description, application) — extracted, validated,
    # carried through the plan/PoA/evidence text, never silently dropped.
    extra_fields_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="received")
    guardrail_findings_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    analysis_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class FwPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One rendered artifact for an intent. `render` is a pure function of
    (intent, fetched rulebase, fetched object catalog) per §3.2 — re-running
    it (because the intent, the device config, or the object catalog
    changed) produces a new row rather than mutating this one, so
    `plan_hash` always identifies exactly one immutable rendered plan."""

    __tablename__ = "fw_plans"

    intent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fw_intents.id", ondelete="CASCADE"))
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    guardrail_findings_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    analysis_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # { "objects_to_create": [...], "objects_reused": [...], "rule": {...} }
    artifact_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    human_diff_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    device_config_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    superseded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class FwPoa(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Generated Plan of Action document for one FwPlan — §3.9. Machine
    sections are locked (regenerating re-derives them from the plan);
    `engineer_freetext_json` holds the handful of sections §3.9's table
    marks editable (pre-check additions, contacts, duration)."""

    __tablename__ = "fw_poas"

    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fw_plans.id", ondelete="CASCADE"))
    poa_revision: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    template_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    engineer_freetext_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    rendered_markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    signed_off_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    signed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class FwApproval(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Binds a human decision to an exact (plan_hash, poa_revision) pair —
    §3.9/§5: the executor refuses to run unless the *current* plan_hash and
    poa_revision on the intent still match what was approved here."""

    __tablename__ = "fw_approvals"

    intent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fw_intents.id", ondelete="CASCADE"))
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fw_plans.id"))
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    poa_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fw_poas.id"))
    poa_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    approver_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(16), nullable=False)  # approved | rejected
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FwExecution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One execute attempt — Appendix A Phases 4-7 collapsed to a single
    enforcement point. `state` follows §A.4's row state machine, narrowed:
    PLANNED/APPROVED live on FwIntent.status; this row starts at
    OBJECTS_WRITTEN and ends at VERIFIED/FAILED/NEEDS_HUMAN/REVERTED."""

    __tablename__ = "fw_executions"

    intent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fw_intents.id", ondelete="CASCADE"))
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fw_plans.id"))
    executed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    state: Mapped[str] = mapped_column(String(24), nullable=False, default="started")
    snapshot_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    commit_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    push_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preview_matched: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    verify_result_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rolled_back: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FwEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The implementation evidence report — §16. Generated once execution
    reaches a terminal state (verified, partial, failed, or reverted) and
    kept verbatim rather than re-rendered on read, so what an auditor or
    ServiceNow saw at the time is exactly what is stored. `snow_writeback_*`
    records whether/what was sent back to ServiceNow — see
    app/services/fw_servicenow.py's module docstring for why that call is a
    stub in this phase rather than a live integration."""

    __tablename__ = "fw_evidences"

    intent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fw_intents.id", ondelete="CASCADE"))
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fw_executions.id", ondelete="CASCADE"))
    rendered_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    snow_writeback_attempted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    snow_writeback_status: Mapped[str] = mapped_column(String(16), nullable=False, default="")  # "" | stubbed | sent | failed
    snow_writeback_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
