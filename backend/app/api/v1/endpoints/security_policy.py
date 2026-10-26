"""Phase 6 API — RITM/connectivity-request sheet intake, and browsing the
normalized `SecurityGroup`/`SecurityRule` objects those intents deploy into.
Lifecycle actions on the `FwIntent` rows this creates (plan/PoA/approve/
execute/rollback) are unchanged — see app/api/v1/endpoints/fw_intents.py,
which now branches on `target_kind` internally.

Reuses the "firewall" RBAC resource area rather than adding a new one: an
intake-created intent is, from an access-control point of view, exactly the
same kind of action as a hand-created or POA-parsed one (view/create map to
read/author, same as fw_intents.py's own router docstring already
establishes).
"""
from __future__ import annotations

import base64
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.fw_automation import FwIntent
from app.models.network import Network
from app.models.security_policy import SecurityGroup, SecurityPolicyBatch, SecurityRule
from app.models.user import User
from app.schemas.security_policy import (
    IntakeRowResultOut,
    SecurityGroupDetailOut,
    SecurityGroupOut,
    SecurityPolicyBatchOut,
    SecurityPolicyIntakeResponse,
    SecurityRuleOut,
)
from app.services import security_policy_intake as intake
from app.services import security_policy_resolve as resolve
from app.services.audit import record as audit_record

router = APIRouter(prefix="/security-policy", tags=["security-policy"])


def _batch_out(batch: SecurityPolicyBatch) -> SecurityPolicyBatchOut:
    return SecurityPolicyBatchOut(
        id=str(batch.id), source_filename=batch.source_filename, source_format=batch.source_format,
        row_count=batch.row_count, resolved_count=batch.resolved_count, unresolved_count=batch.unresolved_count,
        created_at=batch.created_at,
    )


@router.post("/intake", response_model=SecurityPolicyIntakeResponse, status_code=201)
def intake_ritm_sheet(
    payload: dict, db: Session = Depends(get_db), user: User = Depends(require_permission("firewall:create")),
) -> SecurityPolicyIntakeResponse:
    """Body: {"filename": str, "content_base64": str, "ticket_ref"?: str}.
    `content_base64` is the raw .xlsx/.csv/.ods bytes, base64-encoded —
    same convention as FwPoaUploadRequest.content_base64 in
    app/schemas/fw_automation.py, for the same reason (binary formats
    aren't valid JSON strings otherwise)."""
    filename = payload.get("filename")
    content_b64 = payload.get("content_base64")
    if not content_b64:
        raise HTTPException(status_code=400, detail="content_base64 is required")
    try:
        content = base64.b64decode(content_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="content_base64 is not valid base64")

    try:
        parsed = intake.parse_intake_file(content, filename)
    except intake.IntakeParseError as e:
        raise HTTPException(status_code=400, detail=str(e))

    batch = SecurityPolicyBatch(
        source_filename=filename, source_format=parsed.source_format,
        ticket_ref=payload.get("ticket_ref") or (filename.rsplit(".", 1)[0] if filename else ""),
        row_count=len(parsed.rows), parse_warnings_json=parsed.warnings, uploaded_by_id=user.id,
    )
    db.add(batch)
    db.flush()

    results: list[IntakeRowResultOut] = []
    unresolved_rows: list[dict] = []
    resolved_count = 0

    for row in parsed.rows:
        ports_label = ",".join(f"{p.port_low}-{p.port_high}" if p.port_low != p.port_high else str(p.port_low) for p in row.ports)
        destination_label = row.destination_ip or row.destination_fqdn or ""

        if not row.is_resolvable:
            reason = "; ".join(row.unresolved_reasons)
            unresolved_rows.append(row.to_dict())
            results.append(IntakeRowResultOut(
                row_number=row.row_number, status="skipped_unresolved", reason=reason,
                source=row.source_raw, destination=destination_label, ports=ports_label,
            ))
            continue

        try:
            target = resolve.resolve_destination(db, row.destination_ip)
        except resolve.UnresolvedTarget as e:
            unresolved_rows.append({**row.to_dict(), "unresolved_reasons": [str(e)]})
            results.append(IntakeRowResultOut(
                row_number=row.row_number, status="skipped_unresolved", reason=str(e),
                source=row.source_raw, destination=destination_label, ports=ports_label,
            ))
            continue

        # One FwIntent per port spec — a rule is a single (proto, port
        # range) tuple in this pipeline's model (matches FwIntent.
        # service_json's shape elsewhere); a RITM row with multiple ports
        # becomes multiple intents rather than one intent silently keeping
        # only the first port.
        for port in row.ports:
            fw_intent = FwIntent(
                requester_id=user.id, ticket_ref=batch.ticket_ref or (filename or "RITM-import"),
                justification=row.justification, action=row.action, logging="session_end",
                source_json=[{"cidr": row.source_raw if "/" in row.source_raw else f"{row.source_raw}/32"}],
                destination_json=[{"cidr": row.destination_ip if "/" in row.destination_ip else f"{row.destination_ip}/32"}],
                service_json=[{"proto": port.proto, "port_low": port.port_low, "port_high": port.port_high}],
                target_kind=target.target_kind, integration_id=target.integration_id, device_group=target.device_group,
                security_group_id=target.security_group_id, batch_id=batch.id, status="received",
            )
            db.add(fw_intent)
            db.flush()
            resolved_count += 1
            target_label = target.network_name or target.device_group or target.target_kind
            results.append(IntakeRowResultOut(
                row_number=row.row_number, status="created", intent_id=str(fw_intent.id),
                target_kind=target.target_kind, target_label=target_label,
                source=row.source_raw, destination=destination_label,
                ports=f"{port.proto}/{port.port_low}" if port.port_low == port.port_high else f"{port.proto}/{port.port_low}-{port.port_high}",
            ))

    batch.resolved_count = resolved_count
    batch.unresolved_count = len(unresolved_rows)
    batch.unresolved_rows_json = unresolved_rows
    db.commit()
    db.refresh(batch)

    audit_record(
        db, user_id=user.id, action="intake", resource_type="security_policy_batch", resource_id=str(batch.id),
        after={"row_count": batch.row_count, "resolved_count": resolved_count, "unresolved_count": len(unresolved_rows)},
    )

    return SecurityPolicyIntakeResponse(batch=_batch_out(batch), results=results)


@router.get("/batches", response_model=list[SecurityPolicyBatchOut])
def list_batches(db: Session = Depends(get_db), _: User = Depends(require_permission("firewall:view"))) -> list[SecurityPolicyBatchOut]:
    rows = db.execute(select(SecurityPolicyBatch).order_by(SecurityPolicyBatch.created_at.desc())).scalars().all()
    return [_batch_out(r) for r in rows]


@router.get("/batches/{batch_id}", response_model=SecurityPolicyIntakeResponse)
def get_batch(batch_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("firewall:view"))) -> SecurityPolicyIntakeResponse:
    batch = db.get(SecurityPolicyBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="batch not found")
    intents = db.execute(select(FwIntent).where(FwIntent.batch_id == batch.id)).scalars().all()
    results = [
        IntakeRowResultOut(
            row_number=0, status="created", intent_id=str(i.id), target_kind=i.target_kind,
            source=(i.source_json[0]["cidr"] if i.source_json else None),
            destination=(i.destination_json[0]["cidr"] if i.destination_json else None),
        )
        for i in intents
    ]
    for unresolved in batch.unresolved_rows_json:
        results.append(IntakeRowResultOut(
            row_number=unresolved.get("row_number", 0), status="skipped_unresolved",
            reason="; ".join(unresolved.get("unresolved_reasons", [])),
            source=unresolved.get("source_raw"), destination=unresolved.get("destination_ip") or unresolved.get("destination_fqdn"),
        ))
    return SecurityPolicyIntakeResponse(batch=_batch_out(batch), results=results)


def _sg_out(db: Session, sg: SecurityGroup) -> SecurityGroupOut:
    rule_count = db.execute(
        select(func.count(SecurityRule.id)).where(SecurityRule.security_group_id == sg.id, SecurityRule.deleted_at.is_(None)),
    ).scalar_one()
    network = db.get(Network, sg.network_id)
    return SecurityGroupOut(
        id=str(sg.id), network_id=str(sg.network_id), network_name=network.name if network else "",
        cloud_account_id=str(sg.cloud_account_id), provider=sg.provider, name=sg.name, description=sg.description,
        source=sg.source, rule_count=rule_count, created_at=sg.created_at,
    )


@router.get("/security-groups", response_model=list[SecurityGroupOut])
def list_security_groups(db: Session = Depends(get_db), _: User = Depends(require_permission("firewall:view"))) -> list[SecurityGroupOut]:
    rows = db.execute(select(SecurityGroup).where(SecurityGroup.deleted_at.is_(None)).order_by(SecurityGroup.created_at.desc())).scalars().all()
    return [_sg_out(db, r) for r in rows]


@router.get("/security-groups/{security_group_id}", response_model=SecurityGroupDetailOut)
def get_security_group(security_group_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("firewall:view"))) -> SecurityGroupDetailOut:
    sg = db.get(SecurityGroup, security_group_id)
    if not sg or sg.deleted_at is not None:
        raise HTTPException(status_code=404, detail="security group not found")
    rules = db.execute(
        select(SecurityRule).where(SecurityRule.security_group_id == sg.id, SecurityRule.deleted_at.is_(None))
        .order_by(SecurityRule.priority.asc().nulls_last(), SecurityRule.created_at.asc()),
    ).scalars().all()
    base = _sg_out(db, sg)
    def _rule_out(r: SecurityRule) -> SecurityRuleOut:
        return SecurityRuleOut(
            id=str(r.id), direction=r.direction, priority=r.priority, action=r.action, protocol=r.protocol,
            port_low=r.port_low, port_high=r.port_high, cidr=r.cidr, status=r.status, source=r.source,
            managed_by_fwauto=r.managed_by_fwauto, ticket_ref=r.ticket_ref, created_at=r.created_at,
        )

    return SecurityGroupDetailOut(**base.model_dump(), rules=[_rule_out(r) for r in rules])
