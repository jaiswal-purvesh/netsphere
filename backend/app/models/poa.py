from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

# The reference inventories the standalone RITM-POA tool read from local
# files (config.json's "reference_files"). One row per kind, replaced
# in-place on re-upload — kept in Postgres (not a mounted volume) so the
# backend stays a stateless service per ARCHITECTURE.md, and so the file
# survives a container restart without a new volume to manage.
POA_REFERENCE_KINDS = [
    "oci_uat_inventory",
    "oci_prod_inventory",
    "cidr_firewall_inventory",
    "network_ipam",
    "oci_uat_nsg_sl_report",
    "oci_prod_nsg_sl_report",
    "security_list_audit",
]


class PoaReferenceFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One uploaded reference inventory (OCI subnet inventory, merged CIDR/
    firewall map, on-prem Network IPAM, NSG/Security-List host reports,
    security-list rule-count audit). `kind` is one of POA_REFERENCE_KINDS;
    unique so uploading a new file for a kind replaces the old one rather
    than accumulating versions — the generator always reads the current row
    per kind, same as the CLI tool always read the path in config.json.
    """

    __tablename__ = "poa_reference_files"

    kind: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )


class PoaRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One Plan-of-Action generation run: one RITM input in, one enriched
    row set + generated Excel + generated Word doc out. The generated files
    are stored as bytes (not a shared volume) for the same stateless-service
    reason as PoaReferenceFile — see ARCHITECTURE.md's provider-adapter/
    stateless-service note.
    """

    __tablename__ = "poa_runs"

    ritm_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    input_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    manual_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    rows: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    excel_content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    docx_content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )
