from __future__ import annotations

from pydantic import BaseModel, Field


class NetworkCreate(BaseModel):
    cloud_account_id: str
    name: str
    cidr: str = Field(examples=["10.4.0.0/16"])
    provider: str
    region: str | None = None
    owner_team: str | None = None
    business_unit_name: str | None = None
    environment_name: str | None = None
    vrf: str | None = None
    vlan: str | None = None
    firewall: str | None = None
    notes: str | None = None
    parent_network_id: str | None = None


class NetworkUpdate(BaseModel):
    """Partial update — every field optional, only supplied fields change.
    Deliberately narrower than NetworkCreate: cloud_account_id/provider/
    parent_network_id aren't editable here (moving a network between
    accounts or providers is a re-create, not an edit)."""

    name: str | None = None
    cidr: str | None = Field(default=None, examples=["10.4.0.0/16"])
    firewall: str | None = None
    environment_name: str | None = None
    region: str | None = None
    owner_team: str | None = None
    business_unit_name: str | None = None
    vrf: str | None = None
    vlan: str | None = None
    notes: str | None = None
    status: str | None = None


class NetworkOut(BaseModel):
    id: str
    name: str
    cidr: str
    provider: str
    region: str | None
    owner_team: str | None
    environment_name: str | None
    firewall: str | None = None
    status: str
    subnet_count: int = 0
    # Populated (non-blocking) by create/update when the new/changed CIDR
    # duplicates or nests inside another network — the "alert", not a 409.
    overlap_warnings: list[dict] | None = None

    model_config = {"from_attributes": True}


class ImportRowResult(BaseModel):
    row: int
    status: str  # created|updated|error
    message: str | None = None
    cidr: str | None = None
    name: str | None = None
    network_id: str | None = None
    overlap_warnings: list[dict] | None = None


class ImportSummary(BaseModel):
    created: int
    updated: int
    errors: int
    rows: list[ImportRowResult]


class SubnetOut(BaseModel):
    id: str
    network_id: str
    name: str | None
    cidr: str
    availability_zone: str | None
    owner_team: str | None
    application: str | None
    status: str

    model_config = {"from_attributes": True}


class AllocatePreviewRequest(BaseModel):
    hosts: int = Field(gt=0)


class AllocateCreateRequest(BaseModel):
    hosts: int = Field(gt=0)
    name: str | None = None
    availability_zone: str | None = None
    owner_team: str | None = None
    application: str | None = None
