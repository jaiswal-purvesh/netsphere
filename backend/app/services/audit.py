from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def record(
    db: Session, *, user_id: uuid.UUID | None, action: str, resource_type: str,
    resource_id: str | None = None, before: dict | None = None, after: dict | None = None,
    request_id: str | None = None, result: str = "success",
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id, action=action, resource_type=resource_type, resource_id=resource_id,
        before=before, after=after, request_id=request_id, result=result,
    )
    db.add(entry)
    db.commit()
    return entry
