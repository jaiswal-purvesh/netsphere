from __future__ import annotations

from pydantic import BaseModel


class OrganizationOut(BaseModel):
    id: str
    name: str
    model_config = {"from_attributes": True}


class OrganizationCreate(BaseModel):
    name: str


class BusinessUnitOut(BaseModel):
    id: str
    organization_id: str
    name: str
    model_config = {"from_attributes": True}


class BusinessUnitCreate(BaseModel):
    organization_id: str
    name: str


class EnvironmentOut(BaseModel):
    id: str
    business_unit_id: str
    name: str
    model_config = {"from_attributes": True}


class EnvironmentCreate(BaseModel):
    business_unit_id: str
    name: str


class CloudAccountOut(BaseModel):
    id: str
    environment_id: str
    provider: str
    account_identifier: str
    region_default: str | None
    status: str
    model_config = {"from_attributes": True}


class CloudAccountCreate(BaseModel):
    environment_id: str
    provider: str
    account_identifier: str
    region_default: str | None = None
    credential_ref: str | None = None
