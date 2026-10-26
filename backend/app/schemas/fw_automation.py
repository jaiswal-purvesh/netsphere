from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator

from app.models.fw_automation import FW_INTENT_ACTIONS, FW_INTENT_LOGGING


class CidrSelector(BaseModel):
    cidr: str


class ServiceSelector(BaseModel):
    proto: str
    port_low: int | None = None
    port_high: int | None = None


class FwIntentCreate(BaseModel):
    ticket_ref: str
    justification: str = ""
    action: str
    logging: str = "session_end"
    expires_at: datetime | None = None
    source: list[CidrSelector]
    destination: list[CidrSelector]
    service: list[ServiceSelector]
    integration_id: str
    device_group: str | None = None

    @field_validator("action")
    @classmethod
    def _action_valid(cls, v: str) -> str:
        if v not in FW_INTENT_ACTIONS:
            raise ValueError(f"action must be one of {FW_INTENT_ACTIONS}")
        return v

    @field_validator("logging")
    @classmethod
    def _logging_valid(cls, v: str) -> str:
        if v not in FW_INTENT_LOGGING:
            raise ValueError(f"logging must be one of {FW_INTENT_LOGGING}")
        return v


class GuardrailFindingOut(BaseModel):
    rule: str
    severity: str
    message: str


class FwIntentOut(BaseModel):
    id: str
    ticket_ref: str
    justification: str
    action: str
    logging: str
    expires_at: datetime | None
    source: list[dict]
    destination: list[dict]
    service: list[dict]
    target_kind: str = "firewall"
    integration_id: str | None = None
    device_group: str | None
    security_group_id: str | None = None
    target_label: str | None = None
    batch_id: str | None = None
    status: str
    risk_score: int
    guardrail_findings: list[dict]
    analysis: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FwPlanOut(BaseModel):
    id: str
    intent_id: str
    plan_hash: str
    risk_score: int
    guardrail_findings: list[dict]
    analysis: dict
    artifact: dict
    human_diff_text: str
    device_config_version: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FwPoaSignoffRequest(BaseModel):
    pre_checks: list[str] = []
    validation_steps: list[str] = []
    rollback_steps: list[str] = []
    risk_narrative: str | None = None
    duration: str | None = None
    contacts: str | None = None


class FwPoaOut(BaseModel):
    id: str
    plan_id: str
    poa_revision: str
    rendered_markdown: str
    signed_off_by_id: str | None
    signed_off_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FwApprovalRequest(BaseModel):
    plan_hash: str
    poa_revision: str
    comment: str = ""


class FwRejectRequest(BaseModel):
    reason: str = ""


class FwApprovalOut(BaseModel):
    id: str
    decision: str
    plan_hash: str
    poa_revision: str
    approver_id: str
    comment: str
    decided_at: datetime

    model_config = {"from_attributes": True}


class FwPoaUploadRequest(BaseModel):
    """Body for both the dry-parse-only and the commit POA-intake endpoints
    (app/api/v1/endpoints/fw_poa_documents.py). `content` carries text
    formats (free text, JSON, YAML, CSV) verbatim; `content_base64` carries
    binary formats (.docx/.xlsx/.pdf) since those aren't valid JSON strings
    otherwise. Exactly one of the two must be set."""

    content: str | None = None
    content_base64: str | None = None
    filename: str | None = None
    declared_format: str | None = None  # "json"|"yaml"|"csv"|"text"|"docx"|"xlsx"|"pdf" — overrides filename-extension sniffing


class FwExtractedRuleOut(BaseModel):
    """A parsed-but-not-yet-persisted rule, as returned by the dry-run
    endpoint — the same shape `ExtractedRule` validated, so what the
    engineer previews is exactly what would be persisted on commit."""

    rule_id: str | None
    rule_name: str | None
    firewall_vendor: str | None
    management_platform: str | None
    device_group: str | None
    vdom: str | None
    source_zone: str | None
    destination_zone: str | None
    source: list[str]
    destination: list[str]
    protocol: str | None
    destination_port: str | None
    action: str | None
    missing_fields: list[str]


class FwPoaDryRunResponse(BaseModel):
    source_format: str
    header: dict
    rules: list[FwExtractedRuleOut]
    warnings: list[str]


class FwPoaDocumentOut(BaseModel):
    id: str
    poa_ref: str
    change_ref: str
    snow_ticket: str
    application_name: str
    business_owner: str
    technical_owner: str
    environment: str
    source_application: str
    destination_application: str
    business_justification: str
    implementation_window: str
    rollback_requirement: str
    source_format: str
    original_filename: str | None
    rule_count: int
    parse_warnings: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class FwPoaRuleResultOut(BaseModel):
    """Per-rule outcome of a commit — a rule either became an intent (and,
    best-effort, a plan) or was skipped with a reason. Never partially
    silent: every rule the parser found gets exactly one of these."""

    rule_name: str | None
    intent_id: str | None
    status: str  # "created" | "planned" | "skipped_missing_information" | "skipped_no_integration" | "skipped_plan_error"
    message: str


class FwPoaUploadResponse(BaseModel):
    poa_document: FwPoaDocumentOut
    results: list[FwPoaRuleResultOut]


class FwExecutionOut(BaseModel):
    id: str
    intent_id: str
    plan_id: str
    state: str
    snapshot_ref: str | None
    commit_job_id: str | None
    push_job_id: str | None
    verify_result: dict
    error_message: str
    rolled_back: bool
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}
