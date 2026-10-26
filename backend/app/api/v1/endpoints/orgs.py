"""Minimal CRUD for the org hierarchy (Organization -> BusinessUnit ->
Environment -> CloudAccount). Just enough to bootstrap the tree that
networks hang off of — a full admin UI for this is out of scope for this
delivery (see ROADMAP), but the API needs to exist for IPAM to have
somewhere to attach a network.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.org import BusinessUnit, CloudAccount, Environment, Organization
from app.models.user import User
from app.schemas.org import (
    BusinessUnitCreate,
    BusinessUnitOut,
    CloudAccountCreate,
    CloudAccountOut,
    EnvironmentCreate,
    EnvironmentOut,
    OrganizationCreate,
    OrganizationOut,
)

router = APIRouter(prefix="/orgs", tags=["organizations"])


@router.get("/organizations", response_model=list[OrganizationOut])
def list_organizations(db: Session = Depends(get_db), _: User = Depends(require_permission("admin:view"))):
    rows = db.execute(select(Organization).where(Organization.deleted_at.is_(None))).scalars().all()
    return [OrganizationOut(id=str(o.id), name=o.name) for o in rows]


@router.post("/organizations", response_model=OrganizationOut, status_code=201)
def create_organization(payload: OrganizationCreate, db: Session = Depends(get_db), _: User = Depends(require_permission("admin:create"))):
    org = Organization(name=payload.name)
    db.add(org)
    db.commit()
    db.refresh(org)
    return OrganizationOut(id=str(org.id), name=org.name)


@router.get("/business-units", response_model=list[BusinessUnitOut])
def list_business_units(db: Session = Depends(get_db), _: User = Depends(require_permission("admin:view"))):
    rows = db.execute(select(BusinessUnit)).scalars().all()
    return [BusinessUnitOut(id=str(b.id), organization_id=str(b.organization_id), name=b.name) for b in rows]


@router.post("/business-units", response_model=BusinessUnitOut, status_code=201)
def create_business_unit(payload: BusinessUnitCreate, db: Session = Depends(get_db), _: User = Depends(require_permission("admin:create"))):
    bu = BusinessUnit(organization_id=uuid.UUID(payload.organization_id), name=payload.name)
    db.add(bu)
    db.commit()
    db.refresh(bu)
    return BusinessUnitOut(id=str(bu.id), organization_id=str(bu.organization_id), name=bu.name)


@router.get("/environments", response_model=list[EnvironmentOut])
def list_environments(db: Session = Depends(get_db), _: User = Depends(require_permission("admin:view"))):
    rows = db.execute(select(Environment)).scalars().all()
    return [EnvironmentOut(id=str(e.id), business_unit_id=str(e.business_unit_id), name=e.name) for e in rows]


@router.post("/environments", response_model=EnvironmentOut, status_code=201)
def create_environment(payload: EnvironmentCreate, db: Session = Depends(get_db), _: User = Depends(require_permission("admin:create"))):
    env = Environment(business_unit_id=uuid.UUID(payload.business_unit_id), name=payload.name)
    db.add(env)
    db.commit()
    db.refresh(env)
    return EnvironmentOut(id=str(env.id), business_unit_id=str(env.business_unit_id), name=env.name)


def _cloud_account_out(a: CloudAccount) -> CloudAccountOut:
    return CloudAccountOut(
        id=str(a.id), environment_id=str(a.environment_id), provider=a.provider,
        account_identifier=a.account_identifier, region_default=a.region_default, status=a.status,
    )


@router.get("/cloud-accounts", response_model=list[CloudAccountOut])
def list_cloud_accounts(db: Session = Depends(get_db), _: User = Depends(require_permission("ipam:view"))):
    rows = db.execute(select(CloudAccount)).scalars().all()
    return [_cloud_account_out(a) for a in rows]


@router.post("/cloud-accounts", response_model=CloudAccountOut, status_code=201)
def create_cloud_account(payload: CloudAccountCreate, db: Session = Depends(get_db), _: User = Depends(require_permission("admin:create"))):
    acct = CloudAccount(
        environment_id=uuid.UUID(payload.environment_id), provider=payload.provider,
        account_identifier=payload.account_identifier, region_default=payload.region_default,
        credential_ref=payload.credential_ref,
    )
    db.add(acct)
    db.commit()
    db.refresh(acct)
    return _cloud_account_out(acct)
