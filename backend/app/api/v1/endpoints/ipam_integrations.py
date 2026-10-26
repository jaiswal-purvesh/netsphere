"""On-prem IPAM source integrations (TCPWave today) — credential storage,
a reachability test, and the "Sync now" trigger that pulls the ONPREM
team's networks/subnets/IP inventory into NetSphere's own IPAM tables. See
app/services/tcpwave_adapter.py and app/services/ipam_sync.py for the
actual pull/upsert logic; this module is CRUD + orchestration only.

Endpoints:
  GET    /ipam-integrations                    - list
  POST   /ipam-integrations                    - create
  PATCH  /ipam-integrations/{id}                - update (omit `token` to keep it)
  DELETE /ipam-integrations/{id}                - remove
  POST   /ipam-integrations/{id}/test           - reachability check (auth_token/get or a light list call)
  POST   /ipam-integrations/{id}/sync           - run a sync now, returns the run summary
  GET    /ipam-integrations/{id}/sync-runs      - sync history
  GET    /ipam-integrations/ip-addresses        - browse synced IPs (optionally filtered by subnet_id)

Reuses the "ipam" RBAC resource area (already seeded, already governs the
existing networks/subnets endpoints) — view for reads, create/update for
credential CRUD, execute for both test-connection and sync (both make a
live call out to the on-prem device).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.ipam_integration import IPAM_INTEGRATION_VENDORS, IpamIntegration, IpamSyncRun
from app.models.network import IPAddress
from app.models.user import User
from app.schemas.ipam_integration import (
    IPAddressOut,
    IpamIntegrationCreate,
    IpamIntegrationOut,
    IpamIntegrationTestResult,
    IpamIntegrationUpdate,
    IpamSyncRunOut,
)
from app.services import ipam_sync
from app.services import secrets as secretsvc
from app.services import tcpwave_adapter as tcpwave
from app.services.audit import record as audit_record

router = APIRouter(prefix="/ipam-integrations", tags=["ipam-integrations"])


def _out(row: IpamIntegration) -> IpamIntegrationOut:
    return IpamIntegrationOut(
        id=str(row.id), vendor=row.vendor, name=row.name, host=row.host, port=row.port,
        verify_tls=row.verify_tls, auth_mode=row.auth_mode,
        has_token=row.token_ciphertext is not None, token_last4=row.token_last4,
        organization_name=row.organization_name,
        cloud_account_id=str(row.cloud_account_id) if row.cloud_account_id else None,
        is_active=row.is_active, notes=row.notes,
        last_tested_at=row.last_tested_at, last_test_status=row.last_test_status,
        last_test_message=row.last_test_message, created_at=row.created_at, updated_at=row.updated_at,
    )


def _run_out(row: IpamSyncRun) -> IpamSyncRunOut:
    return IpamSyncRunOut(
        id=str(row.id), integration_id=str(row.integration_id), status=row.status, error_message=row.error_message,
        networks_seen=row.networks_seen, networks_created=row.networks_created, networks_updated=row.networks_updated,
        subnets_seen=row.subnets_seen, subnets_created=row.subnets_created, subnets_updated=row.subnets_updated,
        ips_seen=row.ips_seen, ips_created=row.ips_created, ips_updated=row.ips_updated,
        created_at=row.created_at, finished_at=row.finished_at,
    )


@router.get("", response_model=list[IpamIntegrationOut])
def list_integrations(
    db: Session = Depends(get_db), _: User = Depends(require_permission("ipam:view")),
) -> list[IpamIntegrationOut]:
    rows = db.execute(select(IpamIntegration).order_by(IpamIntegration.name)).scalars().all()
    return [_out(r) for r in rows]


@router.post("", response_model=IpamIntegrationOut, status_code=201)
def create_integration(
    payload: IpamIntegrationCreate, db: Session = Depends(get_db),
    user: User = Depends(require_permission("ipam:create")),
) -> IpamIntegrationOut:
    if payload.vendor not in IPAM_INTEGRATION_VENDORS:
        raise HTTPException(status_code=400, detail=f"vendor must be one of {IPAM_INTEGRATION_VENDORS}")
    if payload.auth_mode == "token" and not payload.token:
        raise HTTPException(status_code=400, detail="token auth requires a token")

    row = IpamIntegration(
        vendor=payload.vendor, name=payload.name, host=payload.host, port=payload.port,
        verify_tls=payload.verify_tls, auth_mode=payload.auth_mode,
        organization_name=payload.organization_name,
        cloud_account_id=uuid.UUID(payload.cloud_account_id) if payload.cloud_account_id else None,
        notes=payload.notes, created_by_id=user.id,
    )
    if payload.token:
        row.token_ciphertext = secretsvc.encrypt(payload.token)
        row.token_last4 = secretsvc.last4(payload.token)
    db.add(row)
    db.commit()
    db.refresh(row)

    audit_record(db, user_id=user.id, action="create", resource_type="ipam_integration", resource_id=str(row.id))
    return _out(row)


@router.patch("/{integration_id}", response_model=IpamIntegrationOut)
def update_integration(
    integration_id: uuid.UUID, payload: IpamIntegrationUpdate, db: Session = Depends(get_db),
    user: User = Depends(require_permission("ipam:update")),
) -> IpamIntegrationOut:
    row = db.get(IpamIntegration, integration_id)
    if not row:
        raise HTTPException(status_code=404, detail="integration not found")

    for field in ("name", "host", "port", "verify_tls", "auth_mode", "organization_name", "is_active", "notes"):
        val = getattr(payload, field)
        if val is not None:
            setattr(row, field, val)
    if payload.cloud_account_id is not None:
        row.cloud_account_id = uuid.UUID(payload.cloud_account_id) if payload.cloud_account_id else None
    if payload.token:
        row.token_ciphertext = secretsvc.encrypt(payload.token)
        row.token_last4 = secretsvc.last4(payload.token)

    db.commit()
    db.refresh(row)
    audit_record(db, user_id=user.id, action="update", resource_type="ipam_integration", resource_id=str(row.id))
    return _out(row)


@router.delete("/{integration_id}", status_code=204)
def delete_integration(
    integration_id: uuid.UUID, db: Session = Depends(get_db),
    user: User = Depends(require_permission("ipam:update")),
) -> None:
    row = db.get(IpamIntegration, integration_id)
    if not row:
        raise HTTPException(status_code=404, detail="integration not found")
    db.delete(row)
    db.commit()
    audit_record(db, user_id=user.id, action="delete", resource_type="ipam_integration", resource_id=str(integration_id))


@router.post("/{integration_id}/test", response_model=IpamIntegrationTestResult)
def test_integration(
    integration_id: uuid.UUID, db: Session = Depends(get_db),
    user: User = Depends(require_permission("ipam:execute")),
) -> IpamIntegrationTestResult:
    row = db.get(IpamIntegration, integration_id)
    if not row:
        raise HTTPException(status_code=404, detail="integration not found")
    if not row.host:
        raise HTTPException(status_code=400, detail="no host configured")

    ok, message = True, ""
    try:
        token = secretsvc.decrypt(row.token_ciphertext) if row.token_ciphertext else None
        if row.auth_mode == "client_cert":
            raise tcpwave.TcpwaveError("client-certificate auth is not yet implemented in this adapter")
        if not token:
            raise tcpwave.TcpwaveError("no saved token to test with")
        # A light real call rather than just opening a socket — one page of
        # network/list actually exercises auth, not just TCP reachability.
        tcpwave.fetch_networks(row.host, row.port, row.verify_tls, token, organization_name=row.organization_name)
        message = "Connected and listed networks successfully."
    except (tcpwave.TcpwaveError, secretsvc.SecretDecryptionError) as exc:
        ok, message = False, str(exc)

    row.last_tested_at = datetime.now(timezone.utc)
    row.last_test_status = "ok" if ok else "error"
    row.last_test_message = message
    db.commit()

    audit_record(
        db, user_id=user.id, action="test_connection", resource_type="ipam_integration", resource_id=str(row.id),
        result="success" if ok else "failure", after={"message": message},
    )
    return IpamIntegrationTestResult(ok=ok, message=message, tested_at=row.last_tested_at)


@router.post("/{integration_id}/sync", response_model=IpamSyncRunOut)
def sync_integration(
    integration_id: uuid.UUID, db: Session = Depends(get_db),
    user: User = Depends(require_permission("ipam:execute")),
) -> IpamSyncRunOut:
    row = db.get(IpamIntegration, integration_id)
    if not row:
        raise HTTPException(status_code=404, detail="integration not found")

    run = ipam_sync.run_sync(db, row, triggered_by_id=user.id)
    audit_record(
        db, user_id=user.id, action="sync", resource_type="ipam_sync_run", resource_id=str(run.id),
        result="success" if run.status == "ok" else "failure",
        after={"networks_seen": run.networks_seen, "subnets_seen": run.subnets_seen, "ips_seen": run.ips_seen},
    )
    if run.status == "error":
        # Still return 200 with the run body (mirrors Policy Optimizer's
        # analyze endpoint's honesty-over-silence choice) would hide the
        # failure from a caller checking only the status code, so this one
        # surfaces it as an error response instead — the run row itself
        # (GET .../sync-runs) is the durable record either way.
        raise HTTPException(status_code=502, detail=run.error_message)
    return _run_out(run)


@router.get("/{integration_id}/sync-runs", response_model=list[IpamSyncRunOut])
def list_sync_runs(
    integration_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require_permission("ipam:view")),
) -> list[IpamSyncRunOut]:
    rows = db.execute(
        select(IpamSyncRun).where(IpamSyncRun.integration_id == integration_id)
        .order_by(IpamSyncRun.created_at.desc()).limit(50),
    ).scalars().all()
    return [_run_out(r) for r in rows]


@router.get("/ip-addresses", response_model=list[IPAddressOut])
def list_ip_addresses(
    subnet_id: str | None = None, q: str | None = None,
    db: Session = Depends(get_db), _: User = Depends(require_permission("ipam:view")),
) -> list[IPAddressOut]:
    stmt = select(IPAddress).order_by(IPAddress.ip_int).limit(1000)
    if subnet_id:
        stmt = stmt.where(IPAddress.subnet_id == uuid.UUID(subnet_id))
    if q:
        like = f"%{q}%"
        stmt = stmt.where((IPAddress.hostname.ilike(like)) | (IPAddress.ip_address.ilike(like)))
    rows = db.execute(stmt).scalars().all()
    return [
        IPAddressOut(
            id=str(r.id), subnet_id=str(r.subnet_id), ip_address=r.ip_address, status=r.status,
            hostname=r.hostname, mac_address=r.mac_address, assigned_to=r.assigned_to,
            external_source=r.external_source, last_synced_at=r.last_synced_at,
        )
        for r in rows
    ]
