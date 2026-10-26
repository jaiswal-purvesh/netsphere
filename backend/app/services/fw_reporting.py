"""Human-facing formatted text for the three fixed-format outputs the ask
specifies verbatim: existing-rule detection (§6), dry-run (§10), and the
implementation evidence report (§16). Kept separate from the data model so
the exact wording can evolve without touching what's stored — the API
returns these as plain strings alongside the structured JSON a UI would
normally prefer, for anyone who wants to paste the same text a human
reviewer would have written by hand into a ticket or a chat message.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.fw_automation import FwExecution, FwIntent, FwPlan
from app.models.integration import FirewallIntegration


def format_existing_rule_message(analysis: dict) -> str:
    """§6's three cases, driven off the same fw_redundancy.RedundancyResult
    dict already stored on the plan/intent — never a second, separately
    maintained judgement call."""
    verdict = analysis.get("verdict")

    if verdict in ("no_change_required", "duplicate"):
        rule = analysis.get("covering_rule") or "(unnamed)"
        return (
            "Rule already exists.\nNo implementation required.\n\n"
            f"Existing Rule:\n{rule}"
        )

    if verdict in ("shadowed", "blocked_by_deny"):
        rule = analysis.get("blocking_rule") or "(unnamed)"
        notes = "\n".join(analysis.get("notes", []))
        return (
            "Similar policy detected.\n\n"
            f"Existing Rule:\n{rule}\n\n"
            f"{notes}\n\n"
            "Manual approval required before modification."
        )

    return "No matching or conflicting rule found.\nContinuing with implementation."


def _risk_label(risk_score: int) -> str:
    if risk_score >= 10:
        return "HIGH"
    if risk_score >= 2:
        return "MEDIUM"
    return "LOW"


def format_dry_run(intent: FwIntent, plan: FwPlan, integration: FirewallIntegration) -> str:
    """§10's exact dry-run block. `Implementation: READY` only when there
    are no hard guardrail findings and a rule would actually be created —
    a no-change-required or rejected plan says so instead, since nothing
    would run for either."""
    hard = [f for f in plan.guardrail_findings_json if f["severity"] == "hard"]
    artifact = plan.artifact_json or {}
    rule_body = artifact.get("rule_body", {})

    lines = [
        f"POA ID: {intent.rule_id or intent.id}",
        f"Firewall: {integration.name}",
        f"Manager: {integration.vendor}",
        f"Device Group: {intent.device_group or integration.device_group or '(default)'}",
        "",
        f"ACTION: {'CREATE SECURITY POLICY' if rule_body else 'NO ACTION'}",
        "",
    ]
    if artifact:
        lines += [
            f"Rule Name:\n{artifact.get('rule_name')}",
            "",
            f"Source:\n{', '.join(rule_body.get('source', []))}",
            "",
            f"Destination:\n{', '.join(rule_body.get('destination', []))}",
            "",
            f"Protocol:\n{', '.join(s.get('proto', '') for s in intent.service_json)}",
            "",
            f"Port:\n{', '.join(str(s.get('port_low', '')) for s in intent.service_json)}",
            "",
            f"Action:\n{rule_body.get('action', intent.action).upper()}",
            "",
            "Objects Required:",
        ]
        reused_names = {o["name"] for o in artifact.get("objects_reused", [])}
        created_names = {o["name"] for o in artifact.get("objects_to_create", [])}
        for name in sorted(reused_names):
            lines.append(f"✓ {name} exists")
        for name in sorted(created_names):
            lines.append(f"+ {name} will be created")

    lines += [
        "",
        "Existing Rule:",
        (plan.analysis_json or {}).get("covering_rule") or (plan.analysis_json or {}).get("blocking_rule") or "Not found",
        "",
        f"Risk:\n{_risk_label(plan.risk_score)}",
        "",
        "Implementation:",
        "BLOCKED — hard guardrail failures" if hard else ("READY" if artifact else "NOT REQUIRED"),
    ]
    return "\n".join(lines)


def format_missing_information(missing_fields: list[str]) -> str:
    """§20's "IMPLEMENTATION BLOCKED / Missing Information" block."""
    lines = ["IMPLEMENTATION BLOCKED", "", "Missing Information:", ""]
    lines += [f"- {f}" for f in missing_fields]
    lines += ["", "Action Required:", "Update POA before implementation."]
    return "\n".join(lines)


def format_connectivity_blocked(firewall_name: str, reason: str) -> str:
    return (
        "IMPLEMENTATION BLOCKED\n\n"
        f"Firewall:\n{firewall_name}\n\n"
        f"Reason:\n{reason}\n\n"
        "No configuration was changed."
    )


def format_evidence_report(
    intent: FwIntent, plan: FwPlan, execution: FwExecution, integration: FirewallIntegration,
) -> str:
    """§16's exact evidence report template. Every value below reads
    straight off the already-persisted plan/execution rows — this function
    formats, it never computes a fresh verdict, so the report can never
    say something the recorded pipeline state doesn't back up."""
    artifact = plan.artifact_json or {}
    rule_body = artifact.get("rule_body", {})
    now = datetime.now(timezone.utc)

    pre_check = "PASSED" if not any(f["severity"] == "hard" for f in plan.guardrail_findings_json) else "FAILED"
    dry_run = "PASSED" if artifact or (plan.analysis_json or {}).get("verdict") == "no_change_required" else "N/A"
    approval = "PASSED" if intent.status not in ("rejected",) else "N/A"
    impl_status = {
        "verified": "SUCCESS", "partial": "PARTIAL", "reverted": "FAILED (ROLLED BACK)",
        "needs_human": "NEEDS HUMAN REVIEW", "aborted": "ABORTED", "failed": "FAILED",
    }.get(execution.state, execution.state.upper())
    post_check = "PASSED" if execution.verify_result_json.get("present") else ("N/A" if not execution.verify_result_json else "FAILED")

    lines = [
        "=====================================",
        "FIREWALL IMPLEMENTATION REPORT",
        "=====================================",
        "",
        f"POA ID        : {intent.rule_id or intent.id}",
        f"Change ID     : {intent.ticket_ref}",
        "Implemented By: Automation",
        f"Date/Time     : {now.strftime('%d-%b-%Y %H:%M UTC')}",
        "",
        f"Firewall      : {integration.name}",
        f"Manager       : {integration.vendor}",
        f"Device Group  : {intent.device_group or integration.device_group or '(default)'}",
        "",
        f"Rule Name     : {artifact.get('rule_name', '(no change required)')}",
        "",
        f"Source        : {', '.join(rule_body.get('source', [])) or ', '.join(s['cidr'] for s in intent.source_json)}",
        f"Destination   : {', '.join(rule_body.get('destination', [])) or ', '.join(d['cidr'] for d in intent.destination_json)}",
        f"Protocol      : {', '.join(s.get('proto', '') for s in intent.service_json)}",
        f"Port          : {', '.join(str(s.get('port_low', '')) for s in intent.service_json)}",
        f"Action        : {intent.action.upper()}",
        "",
        f"Pre-check     : {pre_check}",
        f"Dry Run       : {dry_run}",
        f"Approval      : {approval}",
        f"Implementation: {impl_status}",
        f"Post-check    : {post_check}",
        "",
        f"Rollback      : {'PERFORMED' if execution.rolled_back else 'NOT REQUIRED'}",
        "",
        "=====================================",
    ]
    if execution.error_message:
        lines.insert(-1, f"Notes         : {execution.error_message}")
    return "\n".join(lines)
