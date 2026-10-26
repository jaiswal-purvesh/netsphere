"""Firewall rule execution automation API — Phase 3 (Panorama/PAN-OS only)
of claude/firewall-policy-automation-design.md. Implements the subset of
§3.8's API surface this phase needs: intents, plan, PoA + signoff, approval
(with separation-of-duties), execute, and a manual rollback.

Reuses the existing "firewall" RBAC resource area (app/models/user.py) —
view/create map to read/author, approve is the SoD-checked approval gate,
execute covers both /execute and /rollback (both are "make Panorama do
something now" actions).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.fw_automation import FwApproval, FwExecution, FwIntent, FwPlan, FwPoa
from app.models.integration import FirewallIntegration
from app.models.security_policy import SecurityGroup
from app.models.user import User
from app.schemas.fw_automation import (
    FwApprovalOut,
    FwApprovalRequest,
    FwExecutionOut,
    FwIntentCreate,
    FwIntentOut,
    FwPlanOut,
    FwPoaOut,
    FwPoaSignoffRequest,
    FwRejectRequest,
)
from app.services import fw_executor, fw_plan, fw_poa
from app.services import fw_panorama_adapter as panorama
from app.services import secrets as secretsvc
from app.services.audit import record as audit_record

router = APIRouter(prefix="/fw-intents", tags=["fw-automation"])


def _intent_out(row: FwIntent, db: Session | None = None) -> FwIntentOut:
    target_label = None
    if row.target_kind == "firewall" and row.integration_id and db is not None:
        integ = db.get(FirewallIntegration, row.integration_id)
        if integ:
            target_label = f"{integ.name} ({integ.vendor})" + (f" / {row.device_group}" if row.device_group else "")
    elif row.security_group_id and db is not None:
        sg = db.get(SecurityGroup, row.security_group_id)
        if sg:
            target_label = f"{sg.name} ({row.target_kind})"

    return FwIntentOut(
        id=str(row.id), ticket_ref=row.ticket_ref, justification=row.justification,
        action=row.action, logging=row.logging, expires_at=row.expires_at,
        source=row.source_json, destination=row.destination_json, service=row.service_json,
        target_kind=row.target_kind,
        integration_id=str(row.integration_id) if row.integration_id else None, device_group=row.device_group,
        security_group_id=str(row.security_group_id) if row.security_group_id else None,
        target_label=target_label, batch_id=str(row.batch_id) if row.batch_id else None,
        status=row.status, risk_score=row.risk_score,
        guardrail_findings=row.guardrail_findings_json, analysis=row.analysis_json,
        created_at=row.created_at, updated_at=row.updated_at,
    )


def _plan_out(row: FwPlan) -> FwPlanOut:
    return FwPlanOut(
        id=str(row.id), intent_id=str(row.intent_id), plan_hash=row.plan_hash, risk_score=row.risk_score,
        guardrail_findings=row.guardrail_findings_json, analysis=row.analysis_json, artifact=row.artifact_json,
        human_diff_text=row.human_diff_text, device_config_version=row.device_config_version,
        created_at=row.created_at,
    )


def _poa_out(row: FwPoa) -> FwPoaOut:
    return FwPoaOut(
        id=str(row.id), plan_id=str(row.plan_id), poa_revision=row.poa_revision,
        rendered_markdown=row.rendered_markdown,
        signed_off_by_id=str(row.signed_off_by_id) if row.signed_off_by_id else None,
        signed_off_at=row.signed_off_at, created_at=row.created_at,
    )


def _execution_out(row: FwExecution) -> FwExecutionOut:
    return FwExecutionOut(
        id=str(row.id), intent_id=str(row.intent_id), plan_id=str(row.plan_id), state=row.state,
        snapshot_ref=row.snapshot_ref, commit_job_id=row.commit_job_id, push_job_id=row.push_job_id,
        verify_result=row.verify_result_json, error_message=row.error_message, rolled_back=row.rolled_back,
        started_at=row.started_at, finished_at=row.finished_at,
    )


def _get_intent(db: Session, intent_id: uuid.UUID) -> FwIntent:
    row = db.get(FwIntent, intent_id)
    if not row:
        raise HTTPException(status_code=404, detail="intent not found")
    return row


def _get_latest_plan(db: Session, intent: FwIntent) -> FwPlan:
    plan = fw_plan.latest_plan(db, intent.id)
    if not plan:
        raise HTTPException(status_code=400, detail="no plan yet — POST /plan first")
    return plan


@router.get("", response_model=list[FwIntentOut])
def list_intents(db: Session = Depends(get_db), _: User = Depends(require_permission("firewall:view"))) -> list[FwIntentOut]:
    rows = db.execute(select(FwIntent).order_by(FwIntent.created_at.desc())).scalars().all()
    return [_intent_out(r, db) for r in rows]


@router.post("", response_model=FwIntentOut, status_code=201)
def create_intent(
    payload: FwIntentCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("firewall:create")),
) -> FwIntentOut:
    try:
        integration_id = uuid.UUID(payload.integration_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid integration_id")
    integration = db.get(FirewallIntegration, integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="integration not found")

    row = FwIntent(
        requester_id=user.id, ticket_ref=payload.ticket_ref, justification=payload.justification,
        expires_at=payload.expires_at, action=payload.action, logging=payload.logging,
        source_json=[s.model_dump() for s in payload.source],
        destination_json=[d.model_dump() for d in payload.destination],
        service_json=[s.model_dump() for s in payload.service],
        integration_id=integration.id, device_group=payload.device_group,
        status="received",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit_record(db, user_id=user.id, action="create", resource_type="fw_intent", resource_id=str(row.id), after={"ticket_ref": row.ticket_ref, "action": row.action})
    return _intent_out(row, db)


@router.get("/{intent_id}", response_model=FwIntentOut)
def get_intent(intent_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("firewall:view"))) -> FwIntentOut:
    return _intent_out(_get_intent(db, intent_id), db)


@router.post("/{intent_id}/plan", response_model=FwPlanOut)
def plan_intent(intent_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_permission("firewall:create"))) -> FwPlanOut:
    intent = _get_intent(db, intent_id)
    if intent.status in ("executing", "applied_verified"):
        raise HTTPException(status_code=409, detail=f"cannot re-plan an intent in status {intent.status!r}")

    # Any previously-rendered plan for this intent is now potentially stale
    # the moment a new one is requested — mark it superseded so a UI or API
    # consumer never mistakes it for current.
    db.execute(
        FwPlan.__table__.update().where(FwPlan.intent_id == intent.id).values(superseded=True),
    )
    try:
        plan = fw_plan.build_plan(db, intent)
    except fw_plan.PlanError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except panorama.PanoramaError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach Panorama to plan: {e}")

    audit_record(db, user_id=user.id, action="plan", resource_type="fw_intent", resource_id=str(intent.id), after={"plan_hash": plan.plan_hash, "status": intent.status})
    return _plan_out(plan)


@router.get("/{intent_id}/plan", response_model=FwPlanOut)
def get_plan(intent_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("firewall:view"))) -> FwPlanOut:
    intent = _get_intent(db, intent_id)
    return _plan_out(_get_latest_plan(db, intent))


@router.get("/{intent_id}/poa", response_model=FwPoaOut)
def get_or_generate_poa(intent_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_permission("firewall:view"))) -> FwPoaOut:
    intent = _get_intent(db, intent_id)
    plan = _get_latest_plan(db, intent)
    existing = db.query(FwPoa).filter(FwPoa.plan_id == plan.id, FwPoa.superseded.is_(False)).order_by(FwPoa.created_at.desc()).first()
    if existing:
        return _poa_out(existing)
    return _generate_poa(db, intent, plan, {}, user)


@router.post("/{intent_id}/poa/regenerate", response_model=FwPoaOut)
def regenerate_poa(
    intent_id: uuid.UUID, payload: FwPoaSignoffRequest, db: Session = Depends(get_db),
    user: User = Depends(require_permission("firewall:update")),
) -> FwPoaOut:
    intent = _get_intent(db, intent_id)
    plan = _get_latest_plan(db, intent)
    db.query(FwPoa).filter(FwPoa.plan_id == plan.id).update({"superseded": True})
    return _generate_poa(db, intent, plan, {k: v for k, v in payload.model_dump().items() if v not in (None, [])}, user)


def _generate_poa(db: Session, intent: FwIntent, plan: FwPlan, freetext: dict, user: User) -> FwPoaOut:
    integration = db.get(FirewallIntegration, intent.integration_id) if intent.integration_id else None
    security_group = db.get(SecurityGroup, intent.security_group_id) if intent.security_group_id else None
    markdown = fw_poa.render_markdown(intent, plan, integration, freetext, security_group=security_group)
    revision = fw_poa.poa_revision(plan.plan_hash, freetext)
    row = FwPoa(plan_id=plan.id, poa_revision=revision, engineer_freetext_json=freetext, rendered_markdown=markdown)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit_record(db, user_id=user.id, action="poa_generate", resource_type="fw_intent", resource_id=str(intent.id), after={"poa_revision": revision})
    return _poa_out(row)


@router.post("/{intent_id}/poa/signoff", response_model=FwPoaOut)
def signoff_poa(intent_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_permission("firewall:update"))) -> FwPoaOut:
    intent = _get_intent(db, intent_id)
    plan = _get_latest_plan(db, intent)
    poa = db.query(FwPoa).filter(FwPoa.plan_id == plan.id, FwPoa.superseded.is_(False)).order_by(FwPoa.created_at.desc()).first()
    if not poa:
        raise HTTPException(status_code=400, detail="no PoA to sign off — GET /poa first")
    poa.signed_off_by_id = user.id
    poa.signed_off_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(poa)
    audit_record(db, user_id=user.id, action="poa_signoff", resource_type="fw_intent", resource_id=str(intent.id), after={"poa_revision": poa.poa_revision})
    return _poa_out(poa)


@router.post("/{intent_id}/approve", response_model=FwApprovalOut)
def approve_intent(
    intent_id: uuid.UUID, payload: FwApprovalRequest, db: Session = Depends(get_db),
    user: User = Depends(require_permission("firewall:approve")),
) -> FwApprovalOut:
    intent = _get_intent(db, intent_id)
    plan = _get_latest_plan(db, intent)
    if intent.requester_id and intent.requester_id == user.id:
        raise HTTPException(status_code=403, detail="separation of duties: the requester cannot approve their own intent")
    if payload.plan_hash != plan.plan_hash:
        raise HTTPException(status_code=409, detail="plan_hash does not match the current plan — refresh and re-review before approving")
    poa = db.query(FwPoa).filter(FwPoa.plan_id == plan.id, FwPoa.superseded.is_(False)).order_by(FwPoa.created_at.desc()).first()
    if not poa or payload.poa_revision != poa.poa_revision:
        raise HTTPException(status_code=409, detail="poa_revision does not match the current Plan of Action — refresh and re-review before approving")
    if intent.status != "awaiting_approval":
        raise HTTPException(status_code=409, detail=f"intent is in status {intent.status!r}, not awaiting_approval")

    approval = FwApproval(
        intent_id=intent.id, plan_id=plan.id, plan_hash=plan.plan_hash, poa_id=poa.id, poa_revision=poa.poa_revision,
        approver_id=user.id, decision="approved", comment=payload.comment, decided_at=datetime.now(timezone.utc),
    )
    db.add(approval)
    intent.status = "approved"
    db.commit()
    db.refresh(approval)
    audit_record(db, user_id=user.id, action="approve", resource_type="fw_intent", resource_id=str(intent.id), after={"plan_hash": plan.plan_hash, "poa_revision": poa.poa_revision})
    return FwApprovalOut(id=str(approval.id), decision=approval.decision, plan_hash=approval.plan_hash, poa_revision=approval.poa_revision, approver_id=str(approval.approver_id), comment=approval.comment, decided_at=approval.decided_at)


@router.post("/{intent_id}/reject", response_model=FwApprovalOut)
def reject_intent(
    intent_id: uuid.UUID, payload: FwRejectRequest, db: Session = Depends(get_db),
    user: User = Depends(require_permission("firewall:approve")),
) -> FwApprovalOut:
    intent = _get_intent(db, intent_id)
    plan = _get_latest_plan(db, intent)
    poa = db.query(FwPoa).filter(FwPoa.plan_id == plan.id, FwPoa.superseded.is_(False)).order_by(FwPoa.created_at.desc()).first()
    approval = FwApproval(
        intent_id=intent.id, plan_id=plan.id, plan_hash=plan.plan_hash,
        poa_id=poa.id if poa else uuid.uuid4(), poa_revision=poa.poa_revision if poa else "",
        approver_id=user.id, decision="rejected", comment=payload.reason, decided_at=datetime.now(timezone.utc),
    )
    db.add(approval)
    intent.status = "rejected"
    db.commit()
    db.refresh(approval)
    audit_record(db, user_id=user.id, action="reject", resource_type="fw_intent", resource_id=str(intent.id), after={"reason": payload.reason})
    return FwApprovalOut(id=str(approval.id), decision=approval.decision, plan_hash=approval.plan_hash, poa_revision=approval.poa_revision, approver_id=str(approval.approver_id), comment=approval.comment, decided_at=approval.decided_at)


@router.post("/{intent_id}/execute", response_model=FwExecutionOut)
def execute_intent(intent_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_permission("firewall:execute"))) -> FwExecutionOut:
    intent = _get_intent(db, intent_id)
    if intent.status != "approved":
        raise HTTPException(status_code=409, detail=f"intent is in status {intent.status!r}, not approved")
    plan = _get_latest_plan(db, intent)
    try:
        execution = fw_executor.execute(db, intent, plan, user.id)
    except fw_executor.ExecutionAborted as e:
        raise HTTPException(status_code=409, detail=e.reason)
    return _execution_out(execution)


@router.get("/{intent_id}/execution", response_model=FwExecutionOut)
def get_execution(intent_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("firewall:view"))) -> FwExecutionOut:
    row = db.query(FwExecution).filter(FwExecution.intent_id == intent_id).order_by(FwExecution.created_at.desc()).first()
    if not row:
        raise HTTPException(status_code=404, detail="no execution yet")
    return _execution_out(row)


@router.post("/{intent_id}/rollback", response_model=FwExecutionOut)
def rollback_intent(intent_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_permission("firewall:execute"))) -> FwExecutionOut:
    """Manual, explicitly-approved rollback of a previously verified change
    (§5: "Rollback is itself an approved action"). Automatic rollback on a
    failed apply/push/verify already happens inline in fw_executor.execute;
    this covers the "it worked but we need to back it out anyway" case."""
    intent = _get_intent(db, intent_id)
    last_execution = db.query(FwExecution).filter(FwExecution.intent_id == intent_id).order_by(FwExecution.created_at.desc()).first()
    if not last_execution or not last_execution.snapshot_ref:
        raise HTTPException(status_code=400, detail="no execution with a snapshot to roll back to")
    if intent.status != "applied_verified":
        raise HTTPException(status_code=409, detail=f"can only manually roll back an applied_verified intent, currently {intent.status!r}")

    integration = db.get(FirewallIntegration, intent.integration_id)
    secret = secretsvc.decrypt(integration.secret_ciphertext)
    device_group = intent.device_group or integration.device_group or ""
    try:
        job = panorama.rollback_to_snapshot(integration.host, integration.port, integration.verify_tls, secret, integration.username or "svc-fwauto", device_group, last_execution.snapshot_ref)
    except panorama.PanoramaError as e:
        raise HTTPException(status_code=502, detail=f"Rollback failed: {e}")

    last_execution.push_job_id = job
    last_execution.rolled_back = True
    last_execution.state = "reverted"
    intent.status = "rolled_back"
    db.commit()
    db.refresh(last_execution)
    audit_record(db, user_id=user.id, action="rollback", resource_type="fw_intent", resource_id=str(intent.id), after={"snapshot_ref": last_execution.snapshot_ref})
    return _execution_out(last_execution)
