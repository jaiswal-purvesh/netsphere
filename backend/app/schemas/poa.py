from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator


class PoaReferenceFileOut(BaseModel):
    kind: str
    filename: str
    size_bytes: int
    updated_at: datetime

    model_config = {"from_attributes": True}


class PoaReferenceFileList(BaseModel):
    """One entry per POA_REFERENCE_KINDS slot, whether or not a file has been
    uploaded for it yet — so the frontend can render the full checklist of
    reference inventories (uploaded vs. still missing) in one call."""

    kind: str
    label: str
    uploaded: bool
    filename: str | None = None
    size_bytes: int | None = None
    updated_at: datetime | None = None


class PoaPerson(BaseModel):
    name: str = ""
    date: str = ""


class PoaRunTiming(BaseModel):
    pre_implementation: str = ""
    implementation_without_downtime: str = ""
    implementation_with_downtime: str = ""
    customer_confirmation_1: str = ""
    rollback_without_downtime: str = ""
    rollback_with_downtime: str = ""
    customer_confirmation_2: str = ""
    activity_window: str = ""


class PoaRunCreateMetadata(BaseModel):
    """Run-time metadata for one POA generation — the same field shape the
    standalone tool's config.json used. Every field is optional; anything
    left out renders as "None"/blank in the generated Word doc rather than
    failing the run, matching the original tool's tolerant behaviour."""

    ritm_number: str | None = None
    priority_level: str = ""
    description_of_change: str = ""
    purpose_of_change: str = ""
    systems_users_affected: str = ""
    change_owner: str = ""
    implementation_start: str = ""
    implementation_end: str = ""
    implementation_timing: PoaRunTiming = PoaRunTiming()
    on_prem_devices: str = ""
    azure_devices: str = ""
    panorama_devices: str = ""
    nsg_changes_required: str = ""
    nsg_details: str = ""
    routing_changes_required: str = ""
    routing_details: str = ""
    rollback_plan: str = ""
    pre_change_testing: str = ""
    post_change_testing: str = ""
    prepared_by: PoaPerson = PoaPerson()
    checked_by: PoaPerson = PoaPerson()
    change_manager: PoaPerson = PoaPerson()


class PoaRunSummary(BaseModel):
    id: str
    ritm_number: str
    input_filename: str
    row_count: int
    manual_count: int
    invalid_count: int
    warnings: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_id(cls, value):
        return str(value)


class PoaRunDetail(PoaRunSummary):
    rows: list[dict]
    metadata_json: dict

    model_config = {"from_attributes": True}
