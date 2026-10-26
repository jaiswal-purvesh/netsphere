"""Phase 7 — the Automation module's unified change hub.

ARCHITECTURE.md §1 frames Phase 7 as wiring fwauto in as "the Automation
module's execution engine" once it's given "a shared UI/RBAC/audit layer,"
explicitly *not* rebuilding fwauto's plan/approval/execute pipeline a
second time. This service is that convergence layer: it reads the two
change-producing tables that already exist — `PoaRun` (the Automation
module's own POA document generator) and `FwIntent` (fwauto's intent →
plan → PoA → approval → execute pipeline, generalized in Phase 6 to also
cover cloud NSG/SG/SL targets) — and normalizes them into one feed, one
set of summary counts, and one audit trail view, without touching either
table's own schema or lifecycle logic.

Deliberately not a new data model: a `PoaRun` and an `FwIntent` are
different things with different lifecycles (a POA run is a finished
document the moment it's generated; an FwIntent moves through
received -> awaiting_approval -> approved -> executing -> applied_verified
with separation-of-duties approval in between). Merging their *rows* into
one table would blur that distinction and, per this project's own
"deliberate simplification" convention elsewhere (Network.firewall,
one-route-table-per-network, etc.), a read-only normalized view earns its
keep here far better than a shared table would.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.fw_automation import FwIntent
from app.models.integration import FirewallIntegration
from app.models.poa import PoaRun
from app.models.security_policy import SecurityGroup
from app.models.user import User

AUTOMATION_AUDIT_RESOURCE_TYPES = ("fw_intent", "poa_run")

# FwIntent.status values (see app/api/v1/endpoints/fw_intents.py and
# app/services/fw_plan.py/fw_executor.py for where each is set) mapped to
# one of five coarse buckets shared with PoaRun so the combined feed can
# show one consistent status vocabulary instead of two incompatible ones.
_FW_INTENT_STATUS_BUCKET = {
    "received": "in_progress",
    "awaiting_approval": "in_progress",
    "approved": "in_progress",
    "executing": "in_progress",
    "applied_verified": "completed",
    "no_change_required": "completed",
    "rejected": "rejected",
    "rolled_back": "rolled_back",
}


@dataclass
class AutomationChange:
    id: str
    kind: str  # "poa_run" | "fw_intent"
    title: str
    status: str
    status_bucket: str
    ticket_ref: str | None
    requested_by: str | None
    target_label: str | None
    created_at: datetime
    detail: dict = field(default_factory=dict)


def _user_label(db: Session, user_id: uuid.UUID | None, _cache: dict[uuid.UUID, str]) -> str | None:
    if user_id is None:
        return None
    if user_id in _cache:
        return _cache[user_id]
    user = db.get(User, user_id)
    label = user.full_name if user else None
    _cache[user_id] = label
    return label


def _fw_intent_target_label(db: Session, row: FwIntent) -> str | None:
    if row.target_kind == "firewall" and row.integration_id:
        integ = db.get(FirewallIntegration, row.integration_id)
        if integ:
            return f"{integ.name} ({integ.vendor})" + (f" / {row.device_group}" if row.device_group else "")
        return None
    if row.security_group_id:
        sg = db.get(SecurityGroup, row.security_group_id)
        if sg:
            return f"{sg.name} ({row.target_kind})"
    return None


def list_changes(db: Session, limit: int = 200) -> list[AutomationChange]:
    """Merged, most-recent-first feed of POA runs and fwauto intents."""
    user_cache: dict[uuid.UUID, str] = {}
    out: list[AutomationChange] = []

    poa_runs = db.execute(select(PoaRun).order_by(PoaRun.created_at.desc()).limit(limit)).scalars().all()
    for r in poa_runs:
        out.append(
            AutomationChange(
                id=str(r.id), kind="poa_run",
                title=f"POA — RITM {r.ritm_number}" if r.ritm_number else "POA run",
                status="generated", status_bucket="completed",
                ticket_ref=r.ritm_number,
                requested_by=_user_label(db, r.created_by_id, user_cache),
                target_label=f"{r.row_count} rows ({r.invalid_count} invalid)" if r.row_count else None,
                created_at=r.created_at,
                detail={"row_count": r.row_count, "invalid_count": r.invalid_count, "manual_count": r.manual_count},
            )
        )

    intents = db.execute(select(FwIntent).order_by(FwIntent.created_at.desc()).limit(limit)).scalars().all()
    for i in intents:
        out.append(
            AutomationChange(
                id=str(i.id), kind="fw_intent",
                title=f"{i.action.title()} — {i.ticket_ref}" if i.ticket_ref else f"{i.action.title()} request",
                status=i.status, status_bucket=_FW_INTENT_STATUS_BUCKET.get(i.status, "in_progress"),
                ticket_ref=i.ticket_ref,
                requested_by=_user_label(db, i.requester_id, user_cache),
                target_label=_fw_intent_target_label(db, i),
                created_at=i.created_at,
                detail={"action": i.action, "target_kind": i.target_kind, "risk_score": i.risk_score},
            )
        )

    out.sort(key=lambda c: c.created_at, reverse=True)
    return out[:limit]


def changes_summary(db: Session) -> dict:
    """Real counts (not estimates) for the Automation hub's stat cards."""
    poa_count = db.execute(select(PoaRun)).scalars().all()
    intents = db.execute(select(FwIntent)).scalars().all()

    intent_bucket_counts: dict[str, int] = {"in_progress": 0, "completed": 0, "rejected": 0, "rolled_back": 0}
    for i in intents:
        bucket = _FW_INTENT_STATUS_BUCKET.get(i.status, "in_progress")
        intent_bucket_counts[bucket] = intent_bucket_counts.get(bucket, 0) + 1

    cloud_target_count = sum(1 for i in intents if i.target_kind != "firewall")
    firewall_target_count = sum(1 for i in intents if i.target_kind == "firewall")

    return {
        "poa_run_count": len(poa_count),
        "fw_intent_count": len(intents),
        "fw_intent_in_progress": intent_bucket_counts["in_progress"],
        "fw_intent_completed": intent_bucket_counts["completed"],
        "fw_intent_rejected": intent_bucket_counts["rejected"],
        "fw_intent_rolled_back": intent_bucket_counts["rolled_back"],
        "fw_intent_firewall_targets": firewall_target_count,
        "fw_intent_cloud_targets": cloud_target_count,
    }


def list_audit_trail(db: Session, limit: int = 200) -> list[AuditLog]:
    """The shared audit layer, made visible for the first time: every
    mutating action already written to `audit_logs` by the fw_intents and
    poa endpoints (create/plan/poa_generate/poa_signoff/approve/reject/
    execute/rollback for fw_intent; create/generate for poa_run), filtered
    to just those two resource types and returned most-recent-first. No
    new writes happen here — `audit_record()` already runs on every
    mutating endpoint; this is the first reader."""
    rows = (
        db.execute(
            select(AuditLog)
            .where(AuditLog.resource_type.in_(AUTOMATION_AUDIT_RESOURCE_TYPES))
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return rows
