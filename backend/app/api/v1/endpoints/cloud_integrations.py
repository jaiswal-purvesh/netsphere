"""Cloud integrations: the AWS/Azure/GCP/OCI half of the Integrations page
(app/api/v1/endpoints/integrations.py has the firewall half). Credentials
here are what app/providers/{aws,azure,gcp,oci}.py's real adapters use —
app/services/discovery.py's endpoints (discover_aws et al.) look up a
matching, active row by (vendor, account_identifier) and use it in place
of the mock provider when one exists, so saving a credential here is what
turns "demo data" into "live discovery" for that account, no other step
needed.

Secrets are Fernet-encrypted at rest (app/services/cloud_credentials.py,
built on app/services/secrets.py) and never returned — only a masked,
vendor-appropriate `credential_summary`. Only "test connection" ever
decrypts one, in-process, to make one cheap identity-only call.

Endpoints:
  GET    /cloud-integrations               - list
  POST   /cloud-integrations               - create (aws | azure | gcp | oci)
  PATCH  /cloud-integrations/{id}          - update; omit `credentials` to keep them
  DELETE /cloud-integrations/{id}          - remove
  POST   /cloud-integrations/{id}/test     - identity-only reachability check
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.cloud_integration import CloudIntegration
from app.models.user import User
from app.schemas.cloud_integration import (
    CloudIntegrationCreate,
    CloudIntegrationOut,
    CloudIntegrationTestResult,
    CloudIntegrationUpdate,
)
from app.services import cloud_credentials as credsvc
from app.services.audit import record as audit_record
from app.services.cloud_integration_test import TESTERS

router = APIRouter(prefix="/cloud-integrations", tags=["integrations"])


def _out(row: CloudIntegration) -> CloudIntegrationOut:
    return CloudIntegrationOut(
        id=str(row.id), vendor=row.vendor, name=row.name, account_identifier=row.account_identifier,
        region_default=row.region_default, has_credentials=row.credentials_ciphertext is not None,
        credential_summary=row.credential_summary, is_active=row.is_active, notes=row.notes,
        last_tested_at=row.last_tested_at, last_test_status=row.last_test_status,
        last_test_message=row.last_test_message, created_at=row.created_at, updated_at=row.updated_at,
    )


@router.get("", response_model=list[CloudIntegrationOut])
def list_cloud_integrations(
    db: Session = Depends(get_db), _: User = Depends(require_permission("integrations:view")),
) -> list[CloudIntegrationOut]:
    rows = db.execute(
        select(CloudIntegration).order_by(CloudIntegration.vendor, CloudIntegration.name),
    ).scalars().all()
    return [_out(r) for r in rows]


@router.post("", response_model=CloudIntegrationOut, status_code=201)
def create_cloud_integration(
    payload: CloudIntegrationCreate, db: Session = Depends(get_db),
    user: User = Depends(require_permission("integrations:create")),
) -> CloudIntegrationOut:
    try:
        credsvc.validate(payload.vendor, payload.credentials)
    except credsvc.CredentialValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    row = CloudIntegration(
        vendor=payload.vendor, name=payload.name, account_identifier=payload.account_identifier,
        region_default=payload.region_default, notes=payload.notes, is_active=payload.is_active,
        credentials_ciphertext=credsvc.encrypt_credentials(payload.credentials),
        credential_summary=credsvc.summarize(payload.vendor, payload.credentials),
        created_by_id=user.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"a {payload.vendor} integration for account {payload.account_identifier} already exists",
        ) from e
    db.refresh(row)
    audit_record(
        db, user_id=user.id, action="create", resource_type="cloud_integration",
        resource_id=str(row.id), after={"vendor": row.vendor, "name": row.name, "account_identifier": row.account_identifier},
    )
    return _out(row)


@router.patch("/{integration_id}", response_model=CloudIntegrationOut)
def update_cloud_integration(
    integration_id: uuid.UUID, payload: CloudIntegrationUpdate, db: Session = Depends(get_db),
    user: User = Depends(require_permission("integrations:update")),
) -> CloudIntegrationOut:
    row = db.get(CloudIntegration, integration_id)
    if not row:
        raise HTTPException(status_code=404, detail="cloud integration not found")

    data = payload.model_dump(exclude_unset=True, exclude={"credentials"})
    for field, value in data.items():
        setattr(row, field, value)

    if payload.credentials is not None:
        try:
            credsvc.validate(row.vendor, payload.credentials)
        except credsvc.CredentialValidationError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        row.credentials_ciphertext = credsvc.encrypt_credentials(payload.credentials)
        row.credential_summary = credsvc.summarize(row.vendor, payload.credentials)

    db.commit()
    db.refresh(row)
    audit_record(
        db, user_id=user.id, action="update", resource_type="cloud_integration", resource_id=str(row.id),
    )
    return _out(row)


@router.delete("/{integration_id}", status_code=204)
def delete_cloud_integration(
    integration_id: uuid.UUID, db: Session = Depends(get_db),
    user: User = Depends(require_permission("integrations:delete")),
) -> None:
    row = db.get(CloudIntegration, integration_id)
    if not row:
        raise HTTPException(status_code=404, detail="cloud integration not found")
    db.delete(row)
    db.commit()
    audit_record(
        db, user_id=user.id, action="delete", resource_type="cloud_integration", resource_id=str(integration_id),
    )


@router.post("/{integration_id}/test", response_model=CloudIntegrationTestResult)
def test_cloud_integration(
    integration_id: uuid.UUID, db: Session = Depends(get_db),
    user: User = Depends(require_permission("integrations:execute")),
) -> CloudIntegrationTestResult:
    row = db.get(CloudIntegration, integration_id)
    if not row:
        raise HTTPException(status_code=404, detail="cloud integration not found")
    if not row.credentials_ciphertext:
        raise HTTPException(status_code=400, detail="no credentials saved to test with")

    creds = credsvc.decrypt_credentials(row.credentials_ciphertext)
    if row.region_default and "region_default" not in creds:
        creds["region_default"] = row.region_default
    ok, message = TESTERS[row.vendor](creds)

    row.last_tested_at = datetime.now(timezone.utc)
    row.last_test_status = "ok" if ok else "error"
    row.last_test_message = message
    db.commit()

    audit_record(
        db, user_id=user.id, action="test_connection", resource_type="cloud_integration",
        resource_id=str(row.id), result="success" if ok else "failure", after={"message": message},
    )
    return CloudIntegrationTestResult(ok=ok, message=message, tested_at=row.last_tested_at)
