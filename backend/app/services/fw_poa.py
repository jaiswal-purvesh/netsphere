"""Plan of Action document generation — §3.9. Renders a Markdown PoA from a
plan; machine-derived sections (everything except the free-text additions
table §3.9 marks editable) come straight from the plan/intent, never from
user input, so the document cannot describe something the plan will not
actually do. `poa_revision` is a hash of exactly the inputs that matter
(plan_hash, template version, the engineer's free-text) — regenerating with
identical free-text after nothing has changed produces the same revision;
changing any of the three produces a new one, invalidating any approval
recorded against the old revision (app/models/fw_automation.py's FwApproval
docstring).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.models.fw_automation import FwIntent, FwPlan
from app.models.integration import FirewallIntegration
from app.models.security_policy import SecurityGroup

TEMPLATE_VERSION = "v1"


def poa_revision(plan_hash: str, engineer_freetext: dict) -> str:
    import json
    blob = json.dumps({"plan_hash": plan_hash, "template_version": TEMPLATE_VERSION, "freetext": engineer_freetext}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def render_markdown(
    intent: FwIntent, plan: FwPlan, integration: FirewallIntegration | None, engineer_freetext: dict,
    security_group: SecurityGroup | None = None,
) -> str:
    """`integration` is set for `target_kind == "firewall"`; `security_group`
    is set for every cloud target_kind. Exactly one is non-None — mirrors
    the FwIntent `ck_fw_intents_exactly_one_target` invariant."""
    findings = plan.guardrail_findings_json or []
    hard = [f for f in findings if f["severity"] == "hard"]
    warn = [f for f in findings if f["severity"] == "warn"]
    analysis = plan.analysis_json or {}
    is_cloud = integration is None

    lines = [
        f"# Plan of Action — {intent.ticket_ref}",
        "",
        f"*Generated {datetime.now(timezone.utc).isoformat()} — plan_hash `{plan.plan_hash[:16]}…`*",
        "",
        "## Change summary",
        "",
        f"- **Ticket:** {intent.ticket_ref}",
        f"- **Requester:** {intent.requester_id or 'unknown'}",
        f"- **Justification:** {intent.justification or '(none provided)'}",
        f"- **Action:** {intent.action}",
        f"- **Expires:** {intent.expires_at.isoformat() if intent.expires_at else 'never (permanent)'}",
        "",
        "## Target enforcement point",
        "",
    ]
    if is_cloud and security_group is not None:
        lines += [
            f"- **Provider:** {security_group.provider}",
            f"- **Security group:** {security_group.name}",
            f"- **Network:** {security_group.network.name if security_group.network else security_group.network_id}",
        ]
    else:
        lines += [
            f"- **Vendor:** {integration.vendor}",
            f"- **Management host:** {integration.host}:{integration.port}",
            f"- **Device group:** {intent.device_group or integration.device_group or '(default)'}",
        ]

    lines += ["", "## Pre-checks", ""]
    if is_cloud:
        lines.append("- Confirm the security group's rule set has not changed since this plan was rendered (drift check).")
    else:
        lines.append("- Confirm no other administrator has uncommitted changes pending on this device group.")
        lines.append("- Confirm the plan's recorded device config version still matches the live device.")
    for extra in engineer_freetext.get("pre_checks", []):
        lines.append(f"- {extra}")

    lines += ["", "## Implementation steps", ""]
    if plan.artifact_json and is_cloud:
        a = plan.artifact_json
        lines.append(
            f"1. Create a {a.get('direction')} rule in {security_group.provider if security_group else 'the'} "
            f"security group `{security_group.name if security_group else a.get('security_group_id')}`: "
            f"action `{a.get('action')}`, protocol `{a.get('protocol')}`, port {a.get('port_low')}-{a.get('port_high')}, "
            f"CIDR `{a.get('cidr')}`" + (f", priority {a['priority']}" if a.get('priority') is not None else "") + ".",
        )
        lines.append("1. Tag the rule `managed-by:fwauto` and record the request's ticket reference on it.")
    elif plan.artifact_json:
        for o in plan.artifact_json.get("objects_to_create", []):
            lines.append(f"1. Create {o['type']} object `{o['name']}` = `{o['value']}` (Shared scope, tagged `managed-by:fwauto`).")
        lines.append(f"1. Create security rule `{plan.artifact_json.get('rule_name')}` in the pre-rulebase of device group "
                      f"`{intent.device_group or integration.device_group}`, action `{intent.action}`, tagged `managed-by:fwauto`.")
        lines.append("1. Validate the full candidate configuration.")
        lines.append("1. Commit (partial, scoped to the automation admin account).")
        lines.append(f"1. Push (`commit-all`) to device group `{intent.device_group or integration.device_group}`.")
    else:
        lines.append(f"No changes required — {analysis.get('verdict')}: "
                      f"{'; '.join(analysis.get('notes', [])) or 'already satisfied by existing policy.'}")

    lines += [
        "", "## Expected diff", "",
        "```", plan.human_diff_text or "(no diff — no change required)", "```",
    ]

    lines += ["", "## Validation steps", ""]
    if is_cloud:
        lines.append("- Read back the rule from the security group's rule list and confirm it is present with the intended action.")
    else:
        lines.append("- Read back the rule from Panorama and confirm it is present, enabled, and correctly tagged.")
        lines.append("- Confirm the push job to the device group completed successfully.")
    for extra in engineer_freetext.get("validation_steps", []):
        lines.append(f"- {extra}")

    lines += ["", "## Rollback steps", ""]
    if is_cloud:
        lines.append("- The rule this pipeline created is tagged `managed-by:fwauto`; rollback disables and soft-deletes it.")
    else:
        lines.append("- A named pre-change configuration snapshot is taken immediately before any write.")
        lines.append("- Rollback loads that snapshot, commits it (admin-scoped), and re-pushes to the device group.")
    for extra in engineer_freetext.get("rollback_steps", []):
        lines.append(f"- {extra}")

    lines += ["", "## Risk & impact assessment", "", f"- **Risk score:** {plan.risk_score}"]
    if hard:
        lines.append(f"- **{len(hard)} hard guardrail finding(s)** — this plan cannot execute until resolved:")
        for f in hard:
            lines.append(f"  - `{f['rule']}`: {f['message']}")
    if warn:
        lines.append(f"- **{len(warn)} warning(s):**")
        for f in warn:
            lines.append(f"  - `{f['rule']}`: {f['message']}")
    if analysis.get("notes"):
        lines.append("- **Analysis notes:**")
        for n in analysis["notes"]:
            lines.append(f"  - {n}")
    if engineer_freetext.get("risk_narrative"):
        lines.append(f"- {engineer_freetext['risk_narrative']}")

    default_duration = "Typically under a minute (a security-group rule write)." if is_cloud else "Typically 2–15 minutes (Panorama commit + push)."
    lines += [
        "", "## Estimated duration and change window",
        "", f"- {engineer_freetext.get('duration', default_duration)}",
        "", "## Contacts / escalation",
        "", f"- {engineer_freetext.get('contacts', '(not specified)')}",
    ]

    return "\n".join(lines)
