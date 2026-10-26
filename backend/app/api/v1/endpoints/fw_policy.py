"""Policy Optimizer / Firewall Analyzer API — wires the /firewalls nav
placeholder to a real capability, patterned after FireMon Policy Analyzer /
Tufin SecureTrack / AlgoSec Firewall Analyzer's core "pull rulebase, flag
hygiene issues, track review state" loop (see app/services/
fw_policy_analysis.py for the finding logic).

Endpoints:
  GET  /firewalls/integrations         - which credentialed integrations
                                          can be analyzed (panorama/pan_os
                                          only — the only vendors with a
                                          real fetch_rulebase() adapter)
  POST /firewalls/analyze              - pull the live rulebase for one
                                          integration + device group, run
                                          the hygiene analysis, persist a
                                          run + upsert each rule's record
  GET  /firewalls/runs                 - analysis run history
  GET  /firewalls/rules                - the rule review queue (optionally
                                          filtered by integration), most
                                          recently analyzed first
  POST /firewalls/rules/{id}/review    - set owner / review note, stamps
                                          last_reviewed_at/_by

Reuses the "firewall" RBAC resource area — view for reads, execute for
triggering an analysis run (it makes a live call to the device, same class
of action as firewall:execute elsewhere in this app), update for the
review-workflow write.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.fw_policy import FwPolicyAnalysisRun, FwRuleRecord
from app.models.integration import FirewallIntegration
from app.models.user import User
from app.schemas.fw_policy import (
    AnalyzeRequest,
    FwPolicyAnalysisRunOut,
    FwRuleRecordOut,
    RuleReviewRequest,
)
from app.services import fw_panorama_adapter as panorama
from app.services import secrets as secretsvc
from app.services.audit import record as audit_record
from app.services.fw_policy_analysis import analyze_rulebase, severity_counts

router = APIRouter(prefix="/firewalls", tags=["policy-optimizer"])

ANALYZABLE_VENDORS = ("panorama", "pan_os")


def _integration_name(db: Session, integration_id: uuid.UUID) -> str:
    row = db.get(FirewallIntegration, integration_id)
    return row.name if row else "(deleted integration)"


def _run_out(row: FwPolicyAnalysisRun, integration_name: str) -> FwPolicyAnalysisRunOut:
    return FwPolicyAnalysisRunOut(
        id=str(row.id), integration_id=str(row.integration_id), integration_name=integration_name,
        device_group=row.device_group, status=row.status, error_message=row.error_message,
        rule_count=row.rule_count, severity_counts=row.severity_counts_json,
        findings=row.findings_json, created_at=row.created_at,
    )


def _rule_out(row: FwRuleRecord, integration_name: str) -> FwRuleRecordOut:
    return FwRuleRecordOut(
        id=str(row.id), integration_id=str(row.integration_id), integration_name=integration_name,
        device_group=row.device_group, rule_name=row.rule_name, action=row.action, disabled=row.disabled,
        source_cidrs=row.source_cidrs_json, destination_cidrs=row.destination_cidrs_json,
        services=row.services_json, first_seen_at=row.first_seen_at, last_seen_at=row.last_seen_at,
        removed_at=row.removed_at, findings=row.last_findings_json, owner=row.owner,
        last_reviewed_at=row.last_reviewed_at, review_note=row.review_note,
    )


@router.get("/integrations")
def list_analyzable_integrations(
    db: Session = Depends(get_db), _: User = Depends(require_permission("firewall:view")),
) -> list[dict]:
    rows = db.execute(
        select(FirewallIntegration)
        .where(FirewallIntegration.vendor.in_(ANALYZABLE_VENDORS), FirewallIntegration.is_active.is_(True))
        .order_by(FirewallIntegration.name),
    ).scalars().all()
    return [{"id": str(r.id), "name": r.name, "vendor": r.vendor} for r in rows]


@router.post("/analyze", response_model=FwPolicyAnalysisRunOut)
def analyze(
    payload: AnalyzeRequest, db: Session = Depends(get_db),
    user: User = Depends(require_permission("firewall:execute")),
) -> FwPolicyAnalysisRunOut:
    integration = db.get(FirewallIntegration, uuid.UUID(payload.integration_id))
    if not integration:
        raise HTTPException(status_code=404, detail="integration not found")
    if integration.vendor not in ANALYZABLE_VENDORS:
        raise HTTPException(
            status_code=400,
            detail=f"{integration.vendor} has no rulebase adapter yet — only {', '.join(ANALYZABLE_VENDORS)} are supported",
        )
    if not integration.host or not integration.secret_ciphertext:
        raise HTTPException(status_code=400, detail="integration is missing a host or saved credential")

    device_group = payload.device_group or integration.device_group
    if not device_group:
        raise HTTPException(status_code=400, detail="device_group is required (none saved on this integration)")

    now = datetime.now(timezone.utc)
    run = FwPolicyAnalysisRun(
        integration_id=integration.id, device_group=device_group, triggered_by_id=user.id,
    )

    try:
        secret = secretsvc.decrypt(integration.secret_ciphertext)
        rules = panorama.fetch_rulebase(integration.host, integration.port, integration.verify_tls, secret, device_group)
    except Exception as exc:  # noqa: BLE001 — a live-device call; surface whatever failed, never fabricate a result
        run.status = "error"
        run.error_message = str(exc)
        db.add(run)
        db.commit()
        audit_record(
            db, user_id=user.id, action="analyze", resource_type="fw_policy_analysis_run",
            resource_id=str(run.id), result="failure", after={"error": str(exc)},
        )
        raise HTTPException(status_code=502, detail=f"could not pull rulebase from device: {exc}") from exc

    findings = analyze_rulebase(rules)
    findings_by_rule: dict[str, list] = {}
    for f in findings:
        findings_by_rule.setdefault(f.rule, []).append(f.to_dict())

    run.rule_count = len(rules)
    run.severity_counts_json = severity_counts(findings)
    run.findings_json = [f.to_dict() for f in findings]
    db.add(run)

    seen_names = {r.name for r in rules}
    existing = {
        r.rule_name: r
        for r in db.execute(
            select(FwRuleRecord).where(
                FwRuleRecord.integration_id == integration.id, FwRuleRecord.device_group == device_group,
            ),
        ).scalars().all()
    }

    for rule in rules:
        rec = existing.get(rule.name)
        if rec is None:
            rec = FwRuleRecord(
                integration_id=integration.id, device_group=device_group, rule_name=rule.name,
                first_seen_at=now,
            )
            db.add(rec)
        rec.action = rule.action
        rec.disabled = rule.disabled
        rec.source_cidrs_json = rule.source_cidrs
        rec.destination_cidrs_json = rule.destination_cidrs
        rec.services_json = rule.services
        rec.last_seen_at = now
        rec.removed_at = None
        rec.last_findings_json = findings_by_rule.get(rule.name, [])

    for name, rec in existing.items():
        if name not in seen_names and rec.removed_at is None:
            rec.removed_at = now

    db.commit()
    db.refresh(run)

    audit_record(
        db, user_id=user.id, action="analyze", resource_type="fw_policy_analysis_run", resource_id=str(run.id),
        result="success", after={"rule_count": run.rule_count, "severity_counts": run.severity_counts_json},
    )
    return _run_out(run, integration.name)


@router.get("/runs", response_model=list[FwPolicyAnalysisRunOut])
def list_runs(
    integration_id: str | None = None, db: Session = Depends(get_db),
    _: User = Depends(require_permission("firewall:view")),
) -> list[FwPolicyAnalysisRunOut]:
    stmt = select(FwPolicyAnalysisRun).order_by(FwPolicyAnalysisRun.created_at.desc()).limit(100)
    if integration_id:
        stmt = stmt.where(FwPolicyAnalysisRun.integration_id == uuid.UUID(integration_id))
    rows = db.execute(stmt).scalars().all()
    names = {r.integration_id: _integration_name(db, r.integration_id) for r in rows}
    return [_run_out(r, names[r.integration_id]) for r in rows]


@router.get("/rules", response_model=list[FwRuleRecordOut])
def list_rules(
    integration_id: str | None = None, severity: str | None = None,
    db: Session = Depends(get_db), _: User = Depends(require_permission("firewall:view")),
) -> list[FwRuleRecordOut]:
    stmt = select(FwRuleRecord).order_by(FwRuleRecord.last_seen_at.desc())
    if integration_id:
        stmt = stmt.where(FwRuleRecord.integration_id == uuid.UUID(integration_id))
    rows = db.execute(stmt).scalars().all()
    if severity:
        rows = [r for r in rows if any(f.get("severity") == severity for f in r.last_findings_json)]
    names = {r.integration_id: _integration_name(db, r.integration_id) for r in rows}
    return [_rule_out(r, names[r.integration_id]) for r in rows]


@router.post("/rules/{record_id}/review", response_model=FwRuleRecordOut)
def review_rule(
    record_id: uuid.UUID, payload: RuleReviewRequest, db: Session = Depends(get_db),
    user: User = Depends(require_permission("firewall:update")),
) -> FwRuleRecordOut:
    rec = db.get(FwRuleRecord, record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="rule record not found")
    if payload.owner is not None:
        rec.owner = payload.owner
    if payload.review_note is not None:
        rec.review_note = payload.review_note
    rec.last_reviewed_at = datetime.now(timezone.utc)
    rec.last_reviewed_by_id = user.id
    db.commit()
    db.refresh(rec)

    audit_record(
        db, user_id=user.id, action="review", resource_type="fw_rule_record", resource_id=str(rec.id),
        after={"owner": rec.owner, "review_note": rec.review_note},
    )
    return _rule_out(rec, _integration_name(db, rec.integration_id))
