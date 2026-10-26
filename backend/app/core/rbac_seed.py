"""Default role → permission grants, seeded by `app/seed.py`. Kept as data
(not migrated in, since permissions are cheap to re-seed idempotently and
this is exactly the kind of thing that should be editable without a new
Alembic revision per tweak).
"""
from __future__ import annotations

from app.models.user import (
    AUDITOR,
    CLOUD_NETWORK_ENGINEER,
    NETWORK_ADMIN,
    NETWORK_ENGINEER,
    NOC_OPERATOR,
    READ_ONLY,
    RESOURCE_AREAS,
    SECURITY_ENGINEER,
    SUPER_ADMIN,
    VERBS,
)

ALL_PERMISSION_CODES = [f"{area}:{verb}" for area in RESOURCE_AREAS for verb in VERBS]

# SUPER_ADMIN is special-cased in app/deps.py::require_permission and gets
# everything without a row here; every other role's grant is explicit.
ROLE_GRANTS: dict[str, list[str]] = {
    NETWORK_ADMIN: [f"{a}:{v}" for a in RESOURCE_AREAS for v in VERBS if a != "admin"] + ["admin:view"],
    NETWORK_ENGINEER: [f"{a}:{v}" for a in ["ipam", "discovery", "inventory", "topology", "path", "routing", "cloud_networks", "connectivity"] for v in ["view", "create", "update"]]
    + [f"automation:{v}" for v in ["view", "create", "execute", "export"]],
    CLOUD_NETWORK_ENGINEER: [f"{a}:{v}" for a in ["ipam", "discovery", "topology", "routing", "cloud_networks", "connectivity"] for v in ["view", "create", "update", "execute"]]
    + [f"automation:{v}" for v in ["view", "create", "execute", "export"]],
    SECURITY_ENGINEER: [f"{a}:{v}" for a in ["firewall", "compliance", "path"] for v in ["view", "create", "update", "approve"]]
    + ["firewall:execute"]  # fw_intents execute/rollback — Phase 3 execution automation
    + ["ipam:view"]
    + [f"integrations:{v}" for v in ["view", "create", "update", "delete", "execute"]],
    NOC_OPERATOR: [f"{a}:view" for a in RESOURCE_AREAS if a != "admin"] + ["monitoring:update"],
    AUDITOR: [f"{a}:view" for a in RESOURCE_AREAS] + ["audit:export"],
    READ_ONLY: [f"{a}:view" for a in RESOURCE_AREAS if a != "admin"],
}
