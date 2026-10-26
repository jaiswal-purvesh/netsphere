from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.cloud_integration import CloudIntegration
from app.models.org import CloudAccount
from app.models.user import User
from app.providers.aws import AWSProvider
from app.providers.azure import AzureProvider
from app.providers.base import CloudProvider
from app.providers.gcp import GCPProvider
from app.providers.mock.aws import MockAWSProvider
from app.providers.mock.azure import MockAzureProvider
from app.providers.mock.gcp import MockGCPProvider
from app.providers.mock.oci import MockOCIProvider
from app.providers.mock.snmp import MockSNMPProvider
from app.providers.oci import OCIProvider
from app.services import cloud_credentials as credsvc
from app.services.devices import run_device_discovery
from app.services.discovery import run_discovery

router = APIRouter(prefix="/discovery", tags=["discovery"])

# Every cloud named in the product spec now has a mock provider — see
# providers/mock/README.md. This set only exists so a provider name the
# spec never mentions still 501s cleanly instead of a bare 404 from the
# catch-all route below (currently empty — nothing left unimplemented).
_NOT_IMPLEMENTED: set[str] = set()

_REAL_PROVIDERS: dict[str, type[CloudProvider]] = {
    "aws": AWSProvider, "azure": AzureProvider, "gcp": GCPProvider, "oci": OCIProvider,
}


def _resolve_provider(
    db: Session, vendor: str, mock_cls: type[CloudProvider], cloud_account_id: uuid.UUID, account_identifier: str,
) -> CloudProvider:
    """Live-credential-first: if an active CloudIntegration exists for this
    vendor + the cloud account's real account_identifier (set on the
    Integrations page), use the real SDK-backed adapter against it.
    Otherwise fall back to the deterministic mock, same as before this
    existed — so a fresh `docker compose up` with no cloud credentials
    configured still demos exactly as it always has.
    """
    account = db.get(CloudAccount, cloud_account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"cloud account {cloud_account_id} not found")

    integration = db.execute(
        select(CloudIntegration).where(
            CloudIntegration.vendor == vendor,
            CloudIntegration.account_identifier == account.account_identifier,
            CloudIntegration.is_active.is_(True),
        ),
    ).scalar_one_or_none()

    if integration and integration.credentials_ciphertext:
        creds = credsvc.decrypt_credentials(integration.credentials_ciphertext)
        return _REAL_PROVIDERS[vendor](
            account_identifier=account.account_identifier, region=account.region_default, credentials=creds,
        )
    return mock_cls(account_identifier=account_identifier)


def _run(db: Session, provider: CloudProvider, cloud_account_id: uuid.UUID) -> dict:
    try:
        return run_discovery(db, provider, cloud_account_id)
    except NotImplementedError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/aws")
def discover_aws(
    cloud_account_id: uuid.UUID, account_identifier: str = "*",
    db: Session = Depends(get_db), _: User = Depends(require_permission("discovery:execute")),
) -> dict:
    provider = _resolve_provider(db, "aws", MockAWSProvider, cloud_account_id, account_identifier)
    return _run(db, provider, cloud_account_id)


@router.post("/azure")
def discover_azure(
    cloud_account_id: uuid.UUID, account_identifier: str = "*",
    db: Session = Depends(get_db), _: User = Depends(require_permission("discovery:execute")),
) -> dict:
    provider = _resolve_provider(db, "azure", MockAzureProvider, cloud_account_id, account_identifier)
    return _run(db, provider, cloud_account_id)


@router.post("/gcp")
def discover_gcp(
    cloud_account_id: uuid.UUID, account_identifier: str = "*",
    db: Session = Depends(get_db), _: User = Depends(require_permission("discovery:execute")),
) -> dict:
    provider = _resolve_provider(db, "gcp", MockGCPProvider, cloud_account_id, account_identifier)
    return _run(db, provider, cloud_account_id)


@router.post("/oci")
def discover_oci(
    cloud_account_id: uuid.UUID, account_identifier: str = "*",
    db: Session = Depends(get_db), _: User = Depends(require_permission("discovery:execute")),
) -> dict:
    provider = _resolve_provider(db, "oci", MockOCIProvider, cloud_account_id, account_identifier)
    return _run(db, provider, cloud_account_id)


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
