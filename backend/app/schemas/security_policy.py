from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SecurityRuleOut(BaseModel):
    id: str
    direction: str
    priority: int | None
    action: str
    protocol: str
    port_low: int | None
    port_high: int | None
    cidr: str
    status: str
    source: str
    managed_by_fwauto: bool
    ticket_ref: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SecurityGroupOut(BaseModel):
    id: str
    network_id: str
    network_name: str
    cloud_account_id: str
    provider: str
    name: str
    description: str
    source: str
    rule_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SecurityGroupDetailOut(SecurityGroupOut):
    rules: list[SecurityRuleOut]


class IntakeRowResultOut(BaseModel):
    row_number: int
    status: str  # "created" | "skipped_unresolved" | "skipped_no_change_needed_check" | "error"
    reason: str = ""
    intent_id: str | None = None
    target_kind: str | None = None
    target_label: str | None = None
    source: str | None = None
    destination: str | None = None
    ports: str | None = None


class SecurityPolicyBatchOut(BaseModel):
    id: str
    source_filename: str | None
    source_format: str
    row_count: int
    resolved_count: int
    unresolved_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SecurityPolicyIntakeResponse(BaseModel):
    batch: SecurityPolicyBatchOut
    results: list[IntakeRowResultOut]
