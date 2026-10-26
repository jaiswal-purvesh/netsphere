"""Naming — build, check and audit names for every network component.

Read-only: nothing here writes to the inventory (see app/services/naming.py for
why there is no reservation step and no rules table). Gated on the union of
`ipam:view` and `inventory:view`, so anyone who can already see the inventory
can use the builder without a new permission being seeded into an existing
database.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_any_permission
from app.models.user import User
from app.schemas.naming import NameGenerateIn, NameGenerateOut, NameValidateIn, NameValidateOut
from app.services import naming

router = APIRouter(prefix="/naming", tags=["naming"])

_view = require_any_permission("ipam:view", "inventory:view")


@router.get("/spec")
def get_spec(db: Session = Depends(get_db), _: User = Depends(_view)) -> dict:
    return naming.spec(db)


@router.post("/generate", response_model=NameGenerateOut)
def generate_name(body: NameGenerateIn, db: Session = Depends(get_db), _: User = Depends(_view)) -> NameGenerateOut:
    r = naming.generate(db, naming.NameRequest(**body.model_dump()))
    return NameGenerateOut(
        name=r.name, pattern=r.pattern, parts=r.parts, issues=r.issues, unique=r.unique,
        collisions=r.collisions, seq=r.seq, alternatives=r.alternatives,
    )


@router.post("/validate", response_model=NameValidateOut)
def validate_name(body: NameValidateIn, db: Session = Depends(get_db), _: User = Depends(_view)) -> NameValidateOut:
    return NameValidateOut(**naming.validate(db, body.name, body.component, body.provider))


@router.get("/audit")
def audit_names(db: Session = Depends(get_db), _: User = Depends(_view)) -> dict:
    return naming.audit(db)
