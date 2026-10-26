from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

# Seeded roles, per the product spec. Kept as plain string constants (not a
# DB enum) so an org can add a custom role later without a migration.
SUPER_ADMIN = "SUPER_ADMIN"
NETWORK_ADMIN = "NETWORK_ADMIN"
NETWORK_ENGINEER = "NETWORK_ENGINEER"
CLOUD_NETWORK_ENGINEER = "CLOUD_NETWORK_ENGINEER"
SECURITY_ENGINEER = "SECURITY_ENGINEER"
NOC_OPERATOR = "NOC_OPERATOR"
AUDITOR = "AUDITOR"
READ_ONLY = "READ_ONLY"

ALL_ROLES = [
    SUPER_ADMIN, NETWORK_ADMIN, NETWORK_ENGINEER, CLOUD_NETWORK_ENGINEER,
    SECURITY_ENGINEER, NOC_OPERATOR, AUDITOR, READ_ONLY,
]

# Permission verbs, per the product spec: VIEW/CREATE/UPDATE/DELETE/APPROVE/
# EXECUTE/EXPORT, each scoped to a resource area. Only "ipam" and "discovery"
# have real endpoints behind them in Phase 1; the rest are seeded so RBAC
# checks for later phases don't need a migration to add the permission row,
# only to add the endpoint that checks it.
RESOURCE_AREAS = [
    "ipam", "discovery", "inventory", "topology", "path", "routing", "cloud_networks", "connectivity", "firewall",
    "automation", "integrations", "change", "compliance", "monitoring", "audit", "admin",
]
VERBS = ["view", "create", "update", "delete", "approve", "execute", "export"]


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    roles: Mapped[list["Role"]] = relationship(
        "Role", secondary="user_roles", back_populates="users", lazy="selectin",
    )


class Role(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="")

    users: Mapped[list["User"]] = relationship("User", secondary="user_roles", back_populates="roles")
    permissions: Mapped[list["Permission"]] = relationship(
        "Permission", secondary="role_permissions", back_populates="roles", lazy="selectin",
    )


class Permission(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # e.g. "ipam:create"
    description: Mapped[str] = mapped_column(String(255), default="")

    roles: Mapped[list["Role"]] = relationship("Role", secondary="role_permissions", back_populates="permissions")


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id"), primary_key=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permissions.id"), primary_key=True,
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id"), primary_key=True)
    # Resource-scoped RBAC (e.g. "only business unit X") is a Phase 10
    # feature — this column is reserved for it now so the join table
    # doesn't need restructuring later, but nothing reads it yet.
    scope_business_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_units.id"), nullable=True,
    )
