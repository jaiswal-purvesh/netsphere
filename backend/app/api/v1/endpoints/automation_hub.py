"""Phase 7 — the Automation module's unified change hub.

Wires fwauto's intent/plan/approval/execute pipeline into the Automation
module as a *shared UI/RBAC/audit layer* (ARCHITECTURE.md §1), rather than
building a second Terraform/Ansible runner. Concretely this router adds
three read endpoints that sit above the existing `PoaRun`/`FwIntent`
tables — see app/services/automation_hub.py for why this is a normalized
read view, not a new shared data model.

Endpoints:
  GET /automation/changes          - merged, most-recent-first feed of POA
                                      runs and fwauto intents
  GET /automation/changes/summary  - real counts for the hub's stat cards
  GET /automation/audit            - the audit trail for both change kinds
                                      (first-ever reader of `audit_logs`)

Gated on `require_any_permission("automation:view", "firewall:view")`: a
user holding either resource area's view grant can see the combined feed,
matching the "shared UI" framing — someone who only works fwauto intents
shouldn't be locked out of the hub just because they don't also hold the
`automation` resource area, and vice versa.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_any_permission
from app.models.user import User
from app.schemas.automation_hub import (
    AutomationAuditEntryOut,
    AutomationChangeOut,
    AutomationChangesSummaryOut,
)
from app.services import automation_hub

router = APIRouter(prefix="/automation", tags=["automation"])

_view_either = require_any_permission("automation:view", "firewall:view")


@router.get("/changes", response_model=list[AutomationChangeOut])
def list_changes(
    limit: int = 200, db: Session = Depends(get_db), _: User = Depends(_view_either),
) -> list[AutomationChangeOut]:
    changes = automation_hub.list_changes(db, limit=limit)
    return [
        AutomationChangeOut(
            id=c.id, kind=c.kind, title=c.title, status=c.status, status_bucket=c.status_bucket,
            ticket_ref=c.ticket_ref, requested_by=c.requested_by, target_label=c.target_label,
            created_at=c.created_at, detail=c.detail,
        )
        for c in changes
    ]


@router.get("/changes/summary", response_model=AutomationChangesSummaryOut)
def changes_summary(db: Session = Depends(get_db), _: User = Depends(_view_either)) -> AutomationChangesSummaryOut:
    return AutomationChangesSummaryOut(**automation_hub.changes_summary(db))


@router.get("/audit", response_model=list[AutomationAuditEntryOut])
def audit_trail(
    limit: int = 200, db: Session = Depends(get_db), _: User = Depends(_view_either),
) -> list[AutomationAuditEntryOut]:
    rows = automation_hub.list_audit_trail(db, limit=limit)
    user_cache: dict = {}
    out = []
    for r in rows:
        label = None
        if r.user_id is not None:
            if r.user_id not in user_cache:
                u = db.get(User, r.user_id)
                user_cache[r.user_id] = u.full_name if u else None
            label = user_cache[r.user_id]
        out.append(
            AutomationAuditEntryOut(
                id=str(r.id), user_label=label, action=r.action, resource_type=r.resource_type,
                resource_id=r.resource_id, result=r.result, after=r.after, created_at=r.created_at,
            )
        )
    return out
