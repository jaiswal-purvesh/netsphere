"""Integrations: one page to hold every credential the firewall-automation
pipeline needs (Panorama, standalone PAN-OS such as the on-prem PA-5260,
FortiGate, and the individual NGFWs a Panorama manages) — see
claude/firewall-policy-automation-design.md §3.10 (enforcement_point.
credentials_ref) and claude/panorama-executor-implementation.md (the
fwauto executor this will eventually feed). Nothing here executes firewall
changes yet; this module is the secure credential store + reachability
check the executor work depends on.

Secrets are Fernet-encrypted at rest (app/services/secrets.py) and never
returned by the API — GET responses carry only `has_secret` and a masked
`secret_last4`. Only "test connection" ever decrypts one, in-process, to
make one read-only API call to the device.

Endpoints:
  GET    /integrations                 - list, top-level entries with their
                                          managed NGFWs nested under each
                                          Panorama
  POST   /integrations                 - create (panorama | pan_os |
                                          fortigate | ngfw)
  PATCH  /integrations/{id}            - update; omit `secret` to keep it
  DELETE /integrations/{id}            - remove (cascades to ngfw children)
  POST   /integrations/{id}/test       - reachability + auth check
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.integration import FirewallIntegration
from app.models.user import User
from app.schemas.integration import (
    IntegrationCreate,
    IntegrationOut,
    IntegrationTestResult,
    IntegrationUpdate,
)
from app.services import secrets as secretsvc
from app.services.audit import record as audit_record
from app.services.integration_test import test_fortigate, test_panos

router = APIRouter(prefix="/integrations", tags=["integrations"])


def _out(row: FirewallIntegration, children: list[FirewallIntegration] | None = None) -> IntegrationOut:
    return IntegrationOut(
        id=str(row.id), vendor=row.vendor, name=row.name, host=row.host, port=row.port,
        verify_tls=row.verify_tls, auth_type=row.auth_type, username=row.username,
        has_secret=row.secret_ciphertext is not None, secret_last4=row.secret_last4,
        device_group=row.device_group, serial=row.serial,
        parent_id=str(row.parent_id) if row.parent_id else None,
        is_active=row.is_active, notes=row.notes,
        last_tested_at=row.last_tested_at, last_test_status=row.last_test_status,
        last_test_message=row.last_test_message,
        created_at=row.created_at, updated_at=row.updated_at,
        children=[_out(c) for c in children] if children else [],
    )


@router.get("", response_model=list[IntegrationOut])
def list_integrations(
    db: Session = Depends(get_db), _: User = Depends(require_permission("integrations:view")),
) -> list[IntegrationOut]:
    rows = db.execute(select(FirewallIntegration).order_by(FirewallIntegration.vendor, FirewallIntegration.name)).scalars().all()
    by_parent: dict[uuid.UUID | None, list[FirewallIntegration]] = {}
    for r in rows:
        by_parent.setdefault(r.parent_id, []).append(r)
    top_level = by_parent.get(None, [])
    return [_out(r, by_parent.get(r.id, [])) for r in top_level]


@router.post("", response_model=IntegrationOut, status_code=201)
def create_integration(
    payload: IntegrationCreate, db: Session = Depends(get_db),
    user: User = Depends(require_permission("integrations:create")),
) -> IntegrationOut:
    parent = None
    if payload.parent_id:
        parent = db.get(FirewallIntegration, uuid.UUID(payload.parent_id))
        if not parent:
            raise HTTPException(status_code=404, detail="parent integration not found")
        if parent.vendor != "panorama":
            raise HTTPException(status_code=400, detail="parent_id must reference a panorama integration")

    row = FirewallIntegration(
        vendor=payload.vendor, name=payload.name, host=payload.host, port=payload.port,
        verify_tls=payload.verify_tls, auth_type=payload.auth_type, username=payload.username,
        device_group=payload.device_group, serial=payload.serial,
        parent_id=parent.id if parent else None,
        notes=payload.notes, is_active=payload.is_active,
        created_by_id=user.id,
    )
    if payload.secret:
        row.secret_ciphertext = secretsvc.encrypt(payload.secret)
        row.secret_last4 = secretsvc.last4(payload.secret)

    db.add(row)
    db.commit()
    db.refresh(row)
    audit_record(
        db, user_id=user.id, action="create", resource_type="firewall_integration",
        resource_id=str(row.id), after={"vendor": row.vendor, "name": row.name, "host": row.host},
    )
    return _out(row)


@router.patch("/{integration_id}", response_model=IntegrationOut)
def update_integration(
    integration_id: uuid.UUID, payload: IntegrationUpdate, db: Session = Depends(get_db),
    user: User = Depends(require_permission("integrations:update")),
) -> IntegrationOut:
    row = db.get(FirewallIntegration, integration_id)
    if not row:
        raise HTTPException(status_code=404, detail="integration not found")

    data = payload.model_dump(exclude_unset=True, exclude={"secret"})
    for field, value in data.items():
        setattr(row, field, value)
    if payload.secret:
        row.secret_ciphertext = secretsvc.encrypt(payload.secret)
        row.secret_last4 = secretsvc.last4(payload.secret)

    db.commit()
    db.refresh(row)
    audit_record(
        db, user_id=user.id, action="update", resource_type="firewall_integration", resource_id=str(row.id),
    )
    children = db.execute(
        select(FirewallIntegration).where(FirewallIntegration.parent_id == row.id),
    ).scalars().all()
    return _out(row, children)


@router.delete("/{integration_id}", status_code=204)
def delete_integration(
    integration_id: uuid.UUID, db: Session = Depends(get_db),
    user: User = Depends(require_permission("integrations:delete")),
) -> None:
    row = db.get(FirewallIntegration, integration_id)
    if not row:
        raise HTTPException(status_code=404, detail="integration not found")
    db.delete(row)
    db.commit()
    audit_record(
        db, user_id=user.id, action="delete", resource_type="firewall_integration", resource_id=str(integration_id),
    )


@router.post("/{integration_id}/test", response_model=IntegrationTestResult)
def test_integration(
    integration_id: uuid.UUID, db: Session = Depends(get_db),
    user: User = Depends(require_permission("integrations:execute")),
) -> IntegrationTestResult:
    row = db.get(FirewallIntegration, integration_id)
    if not row:
        raise HTTPException(status_code=404, detail="integration not found")
    if row.vendor == "ngfw":
        raise HTTPException(
            status_code=400,
            detail="an NGFW entry has no credentials of its own — test its Panorama instead",
        )
    if not row.host:
        raise HTTPException(status_code=400, detail="no host configured")
    if not row.secret_ciphertext:
        raise HTTPException(status_code=400, detail="no API key/secret saved to test with")

    secret = secretsvc.decrypt(row.secret_ciphertext)
    if row.vendor in ("panorama", "pan_os"):
        ok, message = test_panos(row.host, row.port, row.verify_tls, secret)
    else:
        ok, message = test_fortigate(row.host, row.port, row.verify_tls, secret)

    row.last_tested_at = datetime.now(timezone.utc)
    row.last_test_status = "ok" if ok else "error"
    row.last_test_message = message
    db.commit()

    audit_record(
        db, user_id=user.id, action="test_connection", resource_type="firewall_integration",
        resource_id=str(row.id), result="success" if ok else "failure", after={"message": message},
    )
    return IntegrationTestResult(ok=ok, message=message, tested_at=row.last_tested_at)
