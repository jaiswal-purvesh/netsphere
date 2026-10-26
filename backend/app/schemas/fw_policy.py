from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PolicyFindingOut(BaseModel):
    rule: str
    category: str
    severity: str
    message: str
    related_rule: str | None = None


class FwPolicyAnalysisRunOut(BaseModel):
    id: str
    integration_id: str
    integration_name: str
    device_group: str | None
    status: str
    error_message: str
    rule_count: int
    severity_counts: dict
    findings: list[PolicyFindingOut]
    created_at: datetime


class FwRuleRecordOut(BaseModel):
    id: str
    integration_id: str
    integration_name: str
    device_group: str | None
    rule_name: str
    action: str
    disabled: bool
    source_cidrs: list[str]
    destination_cidrs: list[str]
    services: list[dict]
    first_seen_at: datetime
    last_seen_at: datetime
    removed_at: datetime | None
    findings: list[PolicyFindingOut]
    owner: str
    last_reviewed_at: datetime | None
    review_note: str


class AnalyzeRequest(BaseModel):
    integration_id: str
    device_group: str | None = None


class RuleReviewRequest(BaseModel):
    owner: str | None = None
    review_note: str | None = None
