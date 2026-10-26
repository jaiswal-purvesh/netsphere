"""Plan orchestration — ties together the guardrails, redundancy analysis,
and the Panorama adapter's `render` into one FwPlan row. This is the
"ANALYZE" step of both the main design (§2.2 step 5) and fwauto's Appendix A
Phase 2: read-only, no writes to the device, safe to re-run as often as
needed (each run supersedes the previous plan for the same intent rather
than mutating it — see app/models/fw_automation.py's FwPlan docstring).
"""
from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.fw_automation import FwIntent, FwPlan
from app.models.integration import FirewallIntegration
from app.models.security_policy import SecurityGroup
from app.services import fw_guardrails, fw_panorama_adapter as panorama
from app.services import fw_redundancy
from app.services import secrets as secretsvc
from app.services import security_policy_adapter as cloud_adapter


class PlanError(Exception):
    """Raised for conditions that must stop planning outright (missing/
    inactive integration, wrong vendor) — distinct from guardrail hard
    failures, which still produce a plan (so the requester/approver can see
    *why* it was rejected) rather than aborting before one exists."""


def _load_integration(db: Session, intent: FwIntent) -> FirewallIntegration:
    integration = db.get(FirewallIntegration, intent.integration_id)
    if not integration or not integration.is_active:
        raise PlanError("The configured firewall integration is missing or inactive.")
    if integration.vendor not in ("panorama", "pan_os"):
        raise PlanError(
            f"Vendor {integration.vendor!r} is not yet supported for execution — "
            "Phase 3 covers Panorama/PAN-OS only. FortiManager lands in Phase 4.",
        )
    if not integration.host or not integration.secret_ciphertext:
        raise PlanError("The integration has no host or saved API key to plan against.")
    return integration


def _canonical_hash(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def _load_security_group(db: Session, intent: FwIntent) -> SecurityGroup:
    sg = db.get(SecurityGroup, intent.security_group_id)
    if not sg or sg.deleted_at is not None:
        raise PlanError("The target security group is missing or has been deleted.")
    return sg


def build_plan(db: Session, intent: FwIntent) -> FwPlan:
    if intent.target_kind == "firewall":
        return _build_plan_firewall(db, intent)
    return _build_plan_cloud(db, intent)


def _build_plan_firewall(db: Session, intent: FwIntent) -> FwPlan:
    integration = _load_integration(db, intent)
    device_group = intent.device_group or integration.device_group or ""
    secret = secretsvc.decrypt(integration.secret_ciphertext)

    source = [s["cidr"] for s in intent.source_json]
    destination = [d["cidr"] for d in intent.destination_json]
    service = intent.service_json

    guardrail_findings = fw_guardrails.evaluate(
        action=intent.action, source=intent.source_json, destination=intent.destination_json,
        service=service, expires_at=intent.expires_at, target_kind=intent.target_kind,
    )
    risk_score = sum(10 for f in guardrail_findings if f.severity == "hard") + sum(2 for f in guardrail_findings if f.severity == "warn")

    device_config_version = panorama.fetch_config_version(integration.host, integration.port, integration.verify_tls, secret)

    artifact = None
    human_diff = ""
    analysis_dict = {}
    plan_hash_payload: dict = {}

    if not fw_guardrails.has_hard_failures(guardrail_findings):
        existing_rules = panorama.fetch_rulebase(integration.host, integration.port, integration.verify_tls, secret, device_group)
        analysis = fw_redundancy.analyze(
            action=intent.action, source=source, destination=destination, service=service,
            existing_rules=existing_rules,
        )
        analysis_dict = analysis.to_dict()

        if analysis.verdict in ("needs_new_rule", "shadowed"):
            # shadowed still renders a plan — the approver needs to see the
            # rule that *would* be created, plus the warning about placement.
            addresses, services = panorama.fetch_objects(integration.host, integration.port, integration.verify_tls, secret, device_group)
            plan_seq = str(uuid.uuid4())[:8]
            rendered = panorama.render(
                ticket_ref=intent.ticket_ref, action=intent.action, logging=intent.logging,
                source=source, destination=destination, service=service,
                addresses=addresses, services=services, plan_seq=plan_seq,
                rule_name_override=intent.rule_name, source_zone=intent.source_zone,
                destination_zone=intent.destination_zone, security_profile=intent.security_profile,
            )
            artifact = rendered.to_dict()
            human_diff = _render_human_diff(intent, rendered)
            plan_hash_payload = {
                "intent": {
                    "action": intent.action, "logging": intent.logging, "source": source,
                    "destination": destination, "service": service, "device_group": device_group,
                },
                "artifact": artifact,
                "device_config_version": device_config_version,
            }

    return _finalize_plan(db, intent, guardrail_findings, risk_score, analysis_dict, artifact, human_diff, device_config_version, plan_hash_payload_override=(plan_hash_payload or None))


def _build_plan_cloud(db: Session, intent: FwIntent) -> FwPlan:
    security_group = _load_security_group(db, intent)

    source = [s["cidr"] for s in intent.source_json]
    destination = [d["cidr"] for d in intent.destination_json]
    service = intent.service_json

    guardrail_findings = fw_guardrails.evaluate(
        action=intent.action, source=intent.source_json, destination=intent.destination_json,
        service=service, expires_at=intent.expires_at, target_kind=intent.target_kind,
    )
    risk_score = sum(10 for f in guardrail_findings if f.severity == "hard") + sum(2 for f in guardrail_findings if f.severity == "warn")

    device_config_version = cloud_adapter.fetch_config_version(db, security_group.id)

    artifact = None
    human_diff = ""
    analysis_dict = {}
    plan_hash_payload: dict = {}

    if not fw_guardrails.has_hard_failures(guardrail_findings):
        existing_rules = cloud_adapter.fetch_existing_rules(db, security_group.id)
        analysis = fw_redundancy.analyze(
            action=intent.action, source=source, destination=destination, service=service,
            existing_rules=existing_rules,
        )
        analysis_dict = analysis.to_dict()

        if analysis.verdict in ("needs_new_rule", "shadowed"):
            svc = service[0] if service else {"proto": "tcp", "port_low": None, "port_high": None}
            try:
                rendered = cloud_adapter.render(
                    security_group=security_group, ticket_ref=intent.ticket_ref, action=intent.action,
                    protocol=svc.get("proto", "tcp"), port_low=svc.get("port_low"), port_high=svc.get("port_high"),
                    source=source, destination=destination,
                )
            except cloud_adapter.SecurityPolicyAdapterError as e:
                guardrail_findings.append(fw_guardrails.GuardrailFinding("cloud-adapter-rejected", "hard", str(e)))
                risk_score += 10
                return _finalize_plan(db, intent, guardrail_findings, risk_score, analysis_dict, None, "", device_config_version)

            artifact = rendered.to_dict()
            human_diff = (
                f"Rule to create in {security_group.provider} {security_group.name!r} "
                f"(network {security_group.network.name}): {intent.action} {source} -> "
                f"{svc.get('proto')}/{svc.get('port_low')}-{svc.get('port_high')}"
            )
            plan_hash_payload = {
                "intent": {
                    "action": intent.action, "source": source, "destination": destination, "service": service,
                    "security_group_id": str(security_group.id),
                },
                "artifact": artifact,
                "device_config_version": device_config_version,
            }

    return _finalize_plan(db, intent, guardrail_findings, risk_score, analysis_dict, artifact, human_diff, device_config_version, plan_hash_payload_override=plan_hash_payload)


def _finalize_plan(db, intent, guardrail_findings, risk_score, analysis_dict, artifact, human_diff, device_config_version, plan_hash_payload_override: dict | None = None) -> FwPlan:
    plan_hash_payload = plan_hash_payload_override if plan_hash_payload_override is not None else ({
        "intent": {"id": str(intent.id)}, "artifact": artifact, "device_config_version": device_config_version,
    } if artifact else {})
    plan = FwPlan(
        intent_id=intent.id,
        plan_hash=_canonical_hash(plan_hash_payload) if artifact else _canonical_hash({"no_op": analysis_dict}),
        risk_score=risk_score,
        guardrail_findings_json=[f.to_dict() for f in guardrail_findings],
        analysis_json=analysis_dict,
        artifact_json=artifact or {},
        human_diff_text=human_diff,
        device_config_version=device_config_version,
    )
    db.add(plan)

    intent.guardrail_findings_json = plan.guardrail_findings_json
    intent.analysis_json = analysis_dict
    intent.risk_score = risk_score
    if fw_guardrails.has_hard_failures(guardrail_findings):
        intent.status = "rejected"
    elif analysis_dict.get("verdict") == "no_change_required":
        intent.status = "no_change_required"
    elif analysis_dict.get("verdict") == "duplicate":
        intent.status = "no_change_required"
    else:
        intent.status = "awaiting_approval"

    db.commit()
    db.refresh(plan)
    return plan


def _render_human_diff(intent: FwIntent, rendered) -> str:
    lines = [f"Rule to create: {rendered.rule_name} ({intent.action})"]
    if rendered.objects_to_create:
        lines.append("New objects:")
        for o in rendered.objects_to_create:
            lines.append(f"  + {o['type']} {o['name']} = {o['value']}")
    if rendered.objects_reused:
        lines.append("Reused existing objects:")
        for o in rendered.objects_reused:
            lines.append(f"  = {o['type']} {o['name']}")
    rb = rendered.rule_body
    lines.append(f"  source={rb['source']} destination={rb['destination']} service={rb['service']} action={rb['action']}")
    return "\n".join(lines)


def latest_plan(db: Session, intent_id) -> FwPlan | None:
    return db.execute(
        select(FwPlan).where(FwPlan.intent_id == intent_id, FwPlan.superseded.is_(False))
        .order_by(FwPlan.created_at.desc()),
    ).scalars().first()
