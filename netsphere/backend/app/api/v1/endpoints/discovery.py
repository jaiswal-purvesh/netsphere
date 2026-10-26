from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.user import User
from app.providers.mock.aws import MockAWSProvider
from app.providers.mock.azure import MockAzureProvider
from app.providers.mock.gcp import MockGCPProvider
from app.providers.mock.oci import MockOCIProvider
from app.providers.mock.snmp import MockSNMPProvider
from app.services.devices import run_device_discovery
from app.services.discovery import run_discovery

router = APIRouter(prefix="/discovery", tags=["discovery"])

# Every cloud named in the product spec now has a mock provider — see
# providers/mock/README.md. This set only exists so a provider name the
# spec never mentions still 501s cleanly instead of a bare 404 from the
# catch-all route below (currently empty — nothing left unimplemented).
_NOT_IMPLEMENTED: set[str] = set()


@router.post("/aws")
def discover_aws(
    cloud_account_id: uuid.UUID, account_identifier: str = "*",
    db: Session = Depends(get_db), _: User = Depends(require_permission("discovery:execute")),
) -> dict:
    provider = MockAWSProvider(account_identifier=account_identifier)
    return run_discovery(db, provider, cloud_account_id)


@router.post("/azure")
def discover_azure(
    cloud_account_id: uuid.UUID, account_identifier: str = "*",
    db: Session = Depends(get_db), _: User = Depends(require_permission("discovery:execute")),
) -> dict:
    provider = MockAzureProvider(account_identifier=account_identifier)
    return run_discovery(db, provider, cloud_account_id)


@router.post("/gcp")
def discover_gcp(
    cloud_account_id: uuid.UUID, account_identifier: str = "*",
    db: Session = Depends(get_db), _: User = Depends(require_permission("discovery:execute")),
) -> dict:
    provider = MockGCPProvider(account_identifier=account_identifier)
    return run_discovery(db, provider, cloud_account_id)


@router.post("/oci")
def discover_oci(
    cloud_account_id: uuid.UUID, account_identifier: str = "*",
    db: Session = Depends(get_db), _: User = Depends(require_permission("discovery:execute")),
) -> dict:
    provider = MockOCIProvider(account_identifier=account_identifier)
    return run_discovery(db, provider, cloud_account_id)


@router.post("/snmp")
def discover_snmp(
    environment_id: uuid.UUID, site: str | None = None,
    db: Session = Depends(get_db), _: User = Depends(require_permission("discovery:execute")),
) -> dict:
    provider = MockSNMPProvider(site=site)
    try:
        return run_device_discovery(db, provider, environment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{provider_name}")
def discover_not_implemented(provider_name: str) -> None:
    if provider_name in _NOT_IMPLEMENTED:
        raise HTTPException(
            status_code=501,
            detail=(
                f"{provider_name} discovery is not implemented in this delivery — "
                "no mock or real adapter exists yet. See providers/mock/README.md "
                "and ROADMAP.md."
            ),
        )
    raise HTTPException(status_code=404, detail=f"unknown provider: {provider_name}")
