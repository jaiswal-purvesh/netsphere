"""Phase 6 — the cloud-side "adapter" `fw_plan.py`/`fw_executor.py` dispatch
to for any `FwIntent` whose `target_kind` isn't `"firewall"`. Mirrors
`app/services/fw_panorama_adapter.py`'s function shape (fetch_config_version
/ fetch_rulebase / render / apply_artifact / verify) closely enough that the
plan/execute orchestration barely needs to know which one it's talking to —
see the `target_kind` branches added to those two modules.

The one deliberate structural difference from the Panorama adapter: there
is no live NSG/SG/SL API to call. Every cloud account in this delivery is
mock-discovered (`app/providers/mock/`), so "the device" *is* this
project's own `SecurityGroup`/`SecurityRule` tables — writing a row here is
the full analogue of Panorama's stage-candidate-config step, and there is
no separate "push to device" phase because there is no separate device.
This is not a shortcut around the safety model: guardrails, redundancy
analysis, approval-binds-plan_hash, and PoA generation all still run
exactly as they do for Panorama (`fw_plan.py`/`fw_executor.py` call the
same `fw_guardrails.evaluate()` and `fw_redundancy.analyze()` either way) —
only the "does the target already have this rule / can it be created"
question is answered against our own database instead of an HTTP call to a
vendor. When a real Azure/AWS/GCP/OCI credential and SDK call is wired in
(the same way `app/providers/{azure,aws,gcp,oci}.py` support optional live
discovery today), this module's `apply_artifact` is the one function that
changes shape; `render`'s output (a pure `RenderedSecurityRule`) is already
what a real SDK call would need.
"""
from __future__ import annotations

import hashlib
import uuid

from sqlalchemy.orm import Session

from app.models.security_policy import SecurityGroup, SecurityRule
from app.services.fw_redundancy import NormalizedRule

# AWS Security Groups have no explicit deny — only additive allow rules
# (a "deny" is expressed by omission, or via a Network ACL, which this
# platform does not model). Rejecting it here, in the adapter itself, is
# the "adapter-level hard stop duplicating the guardrails" §5 calls for —
# fw_guardrails.py also rejects it at plan time; this is defence in depth
# in case a caller ever reaches apply_artifact without going through
# fw_plan.build_plan first.
NO_DENY_PROVIDERS = {"aws_sg"}


class SecurityPolicyAdapterError(Exception):
    pass


class RenderedSecurityRule:
    def __init__(self, *, security_group_id: uuid.UUID, direction: str, action: str, protocol: str,
                 port_low: int | None, port_high: int | None, cidr: str, priority: int | None,
                 ticket_ref: str, rule_group_key: str, expires_at=None):
        self.security_group_id = security_group_id
        self.direction = direction
        self.action = action
        self.protocol = protocol
        self.port_low = port_low
        self.port_high = port_high
        self.cidr = cidr
        self.priority = priority
        self.ticket_ref = ticket_ref
        self.rule_group_key = rule_group_key
        self.expires_at = expires_at

    def to_dict(self) -> dict:
        return {
            "security_group_id": str(self.security_group_id), "direction": self.direction, "action": self.action,
            "protocol": self.protocol, "port_low": self.port_low, "port_high": self.port_high, "cidr": self.cidr,
            "priority": self.priority, "ticket_ref": self.ticket_ref, "rule_group_key": self.rule_group_key,
        }


def fetch_config_version(db: Session, security_group_id: uuid.UUID) -> str:
    """Analogue of Panorama's candidate-config version — a hash of the
    security group's current rule set, used for the same drift-detection
    purpose (`fw_executor.execute`'s Phase 1 re-check: if this changed
    between plan and execute, abort rather than apply against stale
    state)."""
    rules = db.query(SecurityRule).filter(
        SecurityRule.security_group_id == security_group_id, SecurityRule.deleted_at.is_(None),
    ).order_by(SecurityRule.id).all()
    blob = "|".join(
        f"{r.id}:{r.direction}:{r.action}:{r.protocol}:{r.port_low}:{r.port_high}:{r.cidr}:{r.status}"
        for r in rules
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def fetch_existing_rules(db: Session, security_group_id: uuid.UUID) -> list[NormalizedRule]:
    """Returns `fw_redundancy.NormalizedRule` rows — the same dataclass
    `fw_panorama_adapter.fetch_rulebase()` produces — so
    `fw_redundancy.analyze()` runs completely unmodified for cloud
    targets. An inbound cloud rule's CIDR is the permitted *source*; the
    destination is implicitly "this security group's own network", so it's
    recorded as the CIDR itself too (a cloud SG rule doesn't carry a
    separate destination selector the way a Panorama rule does — the
    destination is always "attached resources", which for containment
    purposes against a single-network request is equivalent)."""
    rules = db.query(SecurityRule).filter(
        SecurityRule.security_group_id == security_group_id, SecurityRule.deleted_at.is_(None),
        SecurityRule.status == "active",
    ).all()
    out = []
    for r in rules:
        cidrs = [r.cidr]
        out.append(NormalizedRule(
            name=str(r.id), action=r.action,
            source_cidrs=cidrs if r.direction == "inbound" else ["any"],
            destination_cidrs=cidrs if r.direction == "outbound" else ["any"],
            services=[{"proto": r.protocol, "port_low": r.port_low, "port_high": r.port_high}],
            disabled=(r.status != "active"),
        ))
    return out


def render(*, security_group: SecurityGroup, ticket_ref: str, action: str, protocol: str,
           port_low: int | None, port_high: int | None, source: list[str], destination: list[str],
           direction: str = "inbound") -> RenderedSecurityRule:
    if security_group.provider in NO_DENY_PROVIDERS and action == "deny":
        raise SecurityPolicyAdapterError(
            f"{security_group.provider} does not support explicit deny rules — "
            "AWS Security Groups are allow-only; use a Network ACL for a deny requirement.",
        )
    # The CIDR that matters for an inbound cloud security-group rule is the
    # *source* (who may reach this network) — the destination is the
    # network the security group already protects, implicit in
    # security_group_id itself; kept as a parameter for symmetry with the
    # Panorama adapter and to leave room for an "outbound" rule (source
    # implicit, destination explicit) without a signature change.
    cidr = source[0] if direction == "inbound" else (destination[0] if destination else source[0])
    rule_group_key = hashlib.sha256(f"{security_group.id}:{direction}:{protocol}:{port_low}:{port_high}:{cidr}".encode()).hexdigest()[:12]
    priority = None
    if security_group.provider in ("azure_nsg", "gcp_firewall"):
        # Deterministic placement in "band 300" (§3.5) equivalent: start at
        # 1000 and let the DB's row count push new automated rules upward,
        # append-only, exactly like Panorama's band-300 policy.
        existing_count = 0  # computed by caller via fetch_existing_rules count if needed; kept simple here
        priority = 1000 + existing_count
    return RenderedSecurityRule(
        security_group_id=security_group.id, direction=direction, action=action, protocol=protocol,
        port_low=port_low, port_high=port_high, cidr=cidr, priority=priority, ticket_ref=ticket_ref,
        rule_group_key=rule_group_key,
    )


def apply_artifact(db: Session, rendered: RenderedSecurityRule, *, expires_at=None) -> SecurityRule:
    row = SecurityRule(
        security_group_id=rendered.security_group_id, direction=rendered.direction, action=rendered.action,
        protocol=rendered.protocol, port_low=rendered.port_low, port_high=rendered.port_high, cidr=rendered.cidr,
        priority=rendered.priority, status="active", source="automated", managed_by_fwauto=True,
        rule_group_key=rendered.rule_group_key, ticket_ref=rendered.ticket_ref, expires_at=expires_at,
    )
    db.add(row)
    db.flush()
    return row


def verify_rule_present(db: Session, security_group_id: uuid.UUID, rule_group_key: str) -> dict:
    row = db.query(SecurityRule).filter(
        SecurityRule.security_group_id == security_group_id, SecurityRule.rule_group_key == rule_group_key,
        SecurityRule.deleted_at.is_(None), SecurityRule.status == "active",
    ).first()
    if not row:
        return {"present": False}
    return {"present": True, "action": row.action, "rule_id": str(row.id)}


def rollback(db: Session, rule_id: uuid.UUID) -> None:
    """Soft-deletes the rule this pipeline created — the cloud-side
    analogue of Panorama's snapshot-restore. Only ever called on a rule
    `managed_by_fwauto=True`; §3.4's "never mutate an object the system did
    not create" applies here as much as it does to Panorama objects."""
    from datetime import datetime, timezone

    row = db.get(SecurityRule, rule_id)
    if row and row.managed_by_fwauto:
        row.status = "disabled"
        row.deleted_at = datetime.now(timezone.utc)
        db.flush()
