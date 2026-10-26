"""POA upload/intake API — §23's "write it once" entry point. Distinct from
the pre-existing app/api/v1/endpoints/poa.py (an unrelated RITM/change-
request POA generator). Two mutating verbs only:

  POST /fw-poa/dry-run  - parse + validate, persist nothing. Backs the ask's
                           mandatory "[Validate]" / dry-run-before-commit UX.
  POST /fw-poa          - parse, persist one FwPoaDocument + one FwIntent
                           per extracted rule, best-effort auto-plan each.

Plus read endpoints to list/fetch what intake produced. Uses the "firewall"
RBAC resource area exactly like fw_intents.py — uploading a POA is a form of
authoring intents, not a distinct role in this phase.
"""
from __future__ import annotations

import base64
import binascii
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.fw_automation import FwIntent, FwPoaDocument
from app.models.user import User
from app.schemas.fw_automation import (
    FwExtractedRuleOut,
    FwPoaDocumentOut,
    FwPoaDryRunResponse,
    FwPoaRuleResultOut,
    FwPoaUploadRequest,
    FwPoaUploadResponse,
)
from app.services import fw_poa_intake
from app.services.audit import record as audit_record
from app.services.poa_firewall_parser import PoaParseError, parse_poa

router = APIRouter(prefix="/fw-poa", tags=["fw-automation"])


def _decode(payload: FwPoaUploadRequest) -> bytes:
    if payload.content_base64:
        try:
            return base64.b64decode(payload.content_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail="content_base64 is not valid base64")
    if payload.content is not None:
        return payload.content.encode("utf-8")
    raise HTTPException(status_code=400, detail="exactly one of content or content_base64 is required")


def _doc_out(row: FwPoaDocument) -> FwPoaDocumentOut:
    return FwPoaDocumentOut(
        id=str(row.id), poa_ref=row.poa_ref, change_ref=row.change_ref, snow_ticket=row.snow_ticket,
        application_name=row.application_name, business_owner=row.business_owner, technical_owner=row.technical_owner,
        environment=row.environment, source_application=row.source_application, destination_application=row.destination_application,
        business_justification=row.business_justification, implementation_window=row.implementation_window,
        rollback_requirement=row.rollback_requirement, source_format=row.source_format,
        original_filename=row.original_filename, rule_count=row.rule_count,
        parse_warnings=row.parse_warnings_json, created_at=row.created_at,
    )


@router.post("/dry-run", response_model=FwPoaDryRunResponse)
def dry_run(payload: FwPoaUploadRequest, _: User = Depends(require_permission("firewall:create"))) -> FwPoaDryRunResponse:
    content = _decode(payload)
    try:
        parsed = parse_poa(content, filename=payload.filename, declared_format=payload.declared_format)
    except PoaParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return FwPoaDryRunResponse(
        source_format=parsed.source_format,
        header=parsed.header.model_dump(),
        warnings=parsed.warnings,
        rules=[
            FwExtractedRuleOut(
                rule_id=r.rule_id, rule_name=r.rule_name, firewall_vendor=r.firewall_vendor,
                management_platform=r.management_platform, device_group=r.device_group, vdom=r.vdom,
                source_zone=r.source_zone, destination_zone=r.destination_zone, source=r.source,
                destination=r.destination, protocol=r.protocol, destination_port=r.destination_port,
                action=r.action, missing_fields=r.missing_required_fields(),
            )
            for r in parsed.rules
        ],
    )


@router.post("", response_model=FwPoaUploadResponse, status_code=201)
def upload_poa(
    payload: FwPoaUploadRequest, db: Session = Depends(get_db), user: User = Depends(require_permission("firewall:create")),
) -> FwPoaUploadResponse:
    content = _decode(payload)
    try:
        parsed = parse_poa(content, filename=payload.filename, declared_format=payload.declared_format)
    except PoaParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    raw_text = payload.content if payload.content is not None else content.decode("utf-8", errors="replace")
    poa_doc, results = fw_poa_intake.intake(db, user, parsed, original_filename=payload.filename, raw_content=raw_text)

    audit_record(
        db, user_id=user.id, action="poa_upload", resource_type="fw_poa_document", resource_id=str(poa_doc.id),
        after={"rule_count": poa_doc.rule_count, "results": [r["status"] for r in results]},
    )
    return FwPoaUploadResponse(
        poa_document=_doc_out(poa_doc),
        results=[FwPoaRuleResultOut(**r) for r in results],
    )


@router.get("", response_model=list[FwPoaDocumentOut])
def list_poa_documents(db: Session = Depends(get_db), _: User = Depends(require_permission("firewall:view"))) -> list[FwPoaDocumentOut]:
    rows = db.execute(select(FwPoaDocument).order_by(FwPoaDocument.created_at.desc())).scalars().all()
    return [_doc_out(r) for r in rows]


@router.get("/{poa_document_id}", response_model=FwPoaDocumentOut)
def get_poa_document(poa_document_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("firewall:view"))) -> FwPoaDocumentOut:
    row = db.get(FwPoaDocument, poa_document_id)
    if not row:
        raise HTTPException(status_code=404, detail="POA document not found")
    return _doc_out(row)


@router.get("/{poa_document_id}/intents")
def list_poa_intents(poa_document_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("firewall:view"))) -> list[dict]:
    if not db.get(FwPoaDocument, poa_document_id):
        raise HTTPException(status_code=404, detail="POA document not found")
    rows = db.execute(select(FwIntent).where(FwIntent.poa_document_id == poa_document_id).order_by(FwIntent.created_at)).scalars().all()
    return [
        {"id": str(r.id), "rule_name": r.rule_name, "status": r.status, "action": r.action, "device_group": r.device_group}
        for r in rows
    ]
