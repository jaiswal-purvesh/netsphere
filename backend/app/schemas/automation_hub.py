from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AutomationChangeOut(BaseModel):
    id: str
    kind: str  # "poa_run" | "fw_intent"
    title: str
    status: str
    status_bucket: str
    ticket_ref: str | None = None
    requested_by: str | None = None
    target_label: str | None = None
    created_at: datetime
    detail: dict = {}


class AutomationChangesSummaryOut(BaseModel):
    poa_run_count: int
    fw_intent_count: int
    fw_intent_in_progress: int
    fw_intent_completed: int
    fw_intent_rejected: int
    fw_intent_rolled_back: int
    fw_intent_firewall_targets: int
    fw_intent_cloud_targets: int


class AutomationAuditEntryOut(BaseModel):
    id: str
    user_label: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    result: str
    after: dict | None = None
    created_at: datetime
