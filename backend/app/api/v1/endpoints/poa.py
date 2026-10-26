"""
Automation module: Plan of Action (POA) generation for network-change
engineers. Ported from a standalone RITM-POA tool (see app/poa/README.md)
into NetSphere as its own module, fulfilling the "automation" resource area
and the "/automation" nav slot the platform already reserved for it.

Endpoints:
  GET    /automation/poa/reference-files            - list the 7 reference
                                                        inventory slots and
                                                        whether each has an
                                                        uploaded file
  PUT    /automation/poa/reference-files/{kind}      - upload/replace one
  DELETE /automation/poa/reference-files/{kind}      - remove one
  POST   /automation/poa/runs                        - upload a RITM input
                                                        file + run metadata,
                                                        generate a POA
  GET    /automation/poa/runs                        - list past runs
  GET    /automation/poa/runs/{run_id}               - one run's full detail
                                                        (enriched rows)
  GET    /automation/poa/runs/{run_id}/excel         - download the .xlsx
  GET    /automation/poa/runs/{run_id}/docx          - download the .docx
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.poa import POA_REFERENCE_KINDS, PoaReferenceFile, PoaRun
from app.models.user import User
from app.poa.generator import PoaGenerationError, generate_poa
from app.poa.lookup import ReferenceData, ReferenceFile as PoaRefFile
from app.schemas.poa import (
    PoaReferenceFileList,
    PoaRunCreateMetadata,
    PoaRunDetail,
    PoaRunSummary,
)
from app.services.audit import record as audit_record

router = APIRouter(prefix="/automation/poa", tags=["automation"])

# Human-readable labels for the 7 reference slots, shown in the frontend's
# upload checklist next to POA_REFERENCE_KINDS' machine names.
REFERENCE_KIND_LABELS = {
    "oci_uat_inventory": "OCI UAT subnet inventory",
    "oci_prod_inventory": "OCI PROD subnet inventory",
    "cidr_firewall_inventory": "Merged CIDR -> Firewall inventory",
    "network_ipam": "On-prem Network IPAM",
    "oci_uat_nsg_sl_report": "OCI UAT NSG / Security List host report",
    "oci_prod_nsg_sl_report": "OCI PROD NSG / Security List host report",
    "security_list_audit": "Security list rule-count audit",
}

MAX_REFERENCE_FILE_BYTES = 25 * 1024 * 1024  # 25MB — these are spreadsheet exports, not raw dumps
MAX_INPUT_FILE_BYTES = 10 * 1024 * 1024


def _kind_or_404(kind: str) -> str:
    if kind not in POA_REFERENCE_KINDS:
        raise HTTPException(status_code=404, detail=f"unknown reference file kind: {kind}")
    return kind


@router.get("/reference-files", response_model=list[PoaReferenceFileList])
def list_reference_files(
    db: Session = Depends(get_db), _: User = Depends(require_permission("automation:view")),
) -> list[PoaReferenceFileList]:
    existing = {
        row.kind: row
        for row in db.execute(select(PoaReferenceFile)).scalars().all()
    }
    out = []
    for kind in POA_REFERENCE_KINDS:
        row = existing.get(kind)
        out.append(PoaReferenceFileList(
            kind=kind,
            label=REFERENCE_KIND_LABELS.get(kind, kind),
            uploaded=row is not None,
            filename=row.filename if row else None,
            size_bytes=row.size_bytes if row else None,
            updated_at=row.updated_at if row else None,
        ))
    return out


@router.put("/reference-files/{kind}", response_model=PoaReferenceFileList, status_code=200)
def upload_reference_file(
    kind: str, file: UploadFile = File(...),
    db: Session = Depends(get_db), user: User = Depends(require_permission("automation:create")),
) -> PoaReferenceFileList:
    _kind_or_404(kind)
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="uploaded file is empty")
    if len(content) > MAX_REFERENCE_FILE_BYTES:
        raise HTTPException(status_code=400, detail=f"file exceeds the {MAX_REFERENCE_FILE_BYTES // (1024*1024)}MB limit for a reference inventory")

    existing = db.execute(select(PoaReferenceFile).where(PoaReferenceFile.kind == kind)).scalar_one_or_none()
    if existing:
        existing.filename = file.filename or existing.filename
        existing.content = content
        existing.size_bytes = len(content)
        existing.uploaded_by_id = user.id
        row = existing
    else:
        row = PoaReferenceFile(
            kind=kind, filename=file.filename or kind, content=content,
            size_bytes=len(content), uploaded_by_id=user.id,
        )
        db.add(row)
    db.commit()
    db.refresh(row)

    audit_record(
        db, user_id=user.id, action="automation.poa.reference_file.upload", resource_type="poa_reference_file",
        resource_id=str(row.id), after={"kind": kind, "filename": row.filename, "size_bytes": row.size_bytes},
    )
    return PoaReferenceFileList(
        kind=kind, label=REFERENCE_KIND_LABELS.get(kind, kind), uploaded=True,
        filename=row.filename, size_bytes=row.size_bytes, updated_at=row.updated_at,
    )


@router.delete("/reference-files/{kind}", status_code=204)
def delete_reference_file(
    kind: str, db: Session = Depends(get_db), user: User = Depends(require_permission("automation:create")),
) -> Response:
    _kind_or_404(kind)
    row = db.execute(select(PoaReferenceFile).where(PoaReferenceFile.kind == kind)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="no file uploaded for this kind")
    db.delete(row)
    db.commit()
    audit_record(
        db, user_id=user.id, action="automation.poa.reference_file.delete", resource_type="poa_reference_file",
        resource_id=str(row.id), before={"kind": kind, "filename": row.filename},
    )
    return Response(status_code=204)


def _build_reference_data(db: Session) -> ReferenceData:
    rows = {row.kind: row for row in db.execute(select(PoaReferenceFile)).scalars().all()}

    def _ref(kind: str) -> PoaRefFile | None:
        row = rows.get(kind)
        return PoaRefFile(filename=row.filename, content=row.content) if row else None

    audit_row = rows.get("security_list_audit")
    audit_files = [PoaRefFile(filename=audit_row.filename, content=audit_row.content)] if audit_row else []

    return ReferenceData(
        uat_file=_ref("oci_uat_inventory"),
        prod_file=_ref("oci_prod_inventory"),
        cidr_firewall_file=_ref("cidr_firewall_inventory"),
        ipam_file=_ref("network_ipam"),
        uat_host_file=_ref("oci_uat_nsg_sl_report"),
        prod_host_file=_ref("oci_prod_nsg_sl_report"),
        security_list_audit_files=audit_files,
    )


@router.post("/runs", response_model=PoaRunDetail, status_code=201)
def create_run(
    input_file: UploadFile = File(...),
    ritm_number: str | None = Form(default=None),
    metadata: str | None = Form(default=None),
    db: Session = Depends(get_db), user: User = Depends(require_permission("automation:execute")),
) -> PoaRunDetail:
    content = input_file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="uploaded RITM input file is empty")
    if len(content) > MAX_INPUT_FILE_BYTES:
        raise HTTPException(status_code=400, detail=f"file exceeds the {MAX_INPUT_FILE_BYTES // (1024*1024)}MB limit for a RITM input")

    run_metadata = PoaRunCreateMetadata()
    if metadata:
        try:
            run_metadata = PoaRunCreateMetadata(**json.loads(metadata))
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"invalid metadata JSON: {e}") from e

    config = run_metadata.model_dump()
    if ritm_number:
        config["ritm_number"] = ritm_number

    ref = _build_reference_data(db)

    try:
        result = generate_poa(
            input_filename=input_file.filename or "ritm_input.csv",
            input_content=content,
            ref=ref,
            config=config,
            explicit_ritm=ritm_number,
        )
    except PoaGenerationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        # Unrecognised input format, unreadable spreadsheet, etc.
        raise HTTPException(status_code=400, detail=f"could not process the RITM input file: {e}") from e

    run = PoaRun(
        ritm_number=result.ritm_number,
        input_filename=input_file.filename or "ritm_input.csv",
        row_count=len(result.rows),
        manual_count=result.manual_count,
        invalid_count=result.invalid_count,
        warnings=result.warnings,
        rows=result.rows,
        metadata_json=config,
        excel_content=result.excel_content,
        docx_content=result.docx_content,
        created_by_id=user.id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    audit_record(
        db, user_id=user.id, action="automation.poa.run.create", resource_type="poa_run",
        resource_id=str(run.id),
        after={"ritm_number": run.ritm_number, "row_count": run.row_count, "manual_count": run.manual_count},
    )
    return PoaRunDetail.model_validate(run)


@router.get("/runs", response_model=list[PoaRunSummary])
def list_runs(
    db: Session = Depends(get_db), _: User = Depends(require_permission("automation:view")),
) -> list[PoaRunSummary]:
    rows = db.execute(select(PoaRun).order_by(PoaRun.created_at.desc())).scalars().all()
    return [PoaRunSummary.model_validate(r) for r in rows]


def _get_run_or_404(db: Session, run_id: uuid.UUID) -> PoaRun:
    run = db.get(PoaRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="POA run not found")
    return run


@router.get("/runs/{run_id}", response_model=PoaRunDetail)
def get_run(
    run_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("automation:view")),
) -> PoaRunDetail:
    return PoaRunDetail.model_validate(_get_run_or_404(db, run_id))


@router.get("/runs/{run_id}/excel")
def download_run_excel(
    run_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("automation:export")),
) -> Response:
    run = _get_run_or_404(db, run_id)
    return Response(
        content=run.excel_content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={run.ritm_number}-POA.xlsx"},
    )


@router.get("/runs/{run_id}/docx")
def download_run_docx(
    run_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("automation:export")),
) -> Response:
    run = _get_run_or_404(db, run_id)
    return Response(
        content=run.docx_content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={run.ritm_number}-POA.docx"},
    )
