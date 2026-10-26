"""POA intake — turns a `ParsedPoa` (app/services/poa_firewall_parser.py)
into a persisted `FwPoaDocument` + one `FwIntent` per extracted rule
(§23's "write it once in the POA" requirement). Kept separate from the
parser itself: the parser is a pure, dependency-free text→object function;
this module is where DB writes, integration matching, and port/CIDR
shaping into the existing FwIntent columns happen, so the parser stays
trivially unit-testable without a database.

Matching a rule to a `FirewallIntegration` row is deliberately conservative
for this phase (Panorama/PAN-OS only, per fw_plan.py's `_load_integration`):
if the rule names a firewall hostname or management IP, that must match an
active integration's `host` or `name` exactly; otherwise, if exactly one
active integration exists for the rule's vendor family, use it. Anything
more ambiguous than that is surfaced as a skipped rule rather than guessed
at — a wrong enforcement point is a worse failure mode than a rule that
needs a human to disambiguate once.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.fw_automation import FwIntent, FwPoaDocument
from app.models.integration import FirewallIntegration
from app.models.user import User
from app.services import fw_plan, fw_reporting
from app.services import fw_panorama_adapter as panorama
from app.services.poa_firewall_parser import ExtractedHeader, ExtractedRule, ParsedPoa

# firewall_vendor (as ExtractedRule normalizes it) -> the FirewallIntegration
# vendor values that satisfy it. "paloalto" covers both a Panorama-managed
# estate and a standalone PA appliance; the rule's management_platform (if
# given) narrows further below.
_VENDOR_FAMILY = {"paloalto": ["panorama", "pan_os"], "fortigate": ["fortigate"]}


def _candidate_vendors(rule: ExtractedRule) -> list[str]:
    if rule.management_platform in ("panorama", "pan_os", "fortigate"):
        return [rule.management_platform]
    return _VENDOR_FAMILY.get(rule.firewall_vendor or "", ["panorama", "pan_os", "fortigate"])


def find_integration(db: Session, rule: ExtractedRule) -> FirewallIntegration | None:
    rows = (
        db.query(FirewallIntegration)
        .filter(FirewallIntegration.is_active.is_(True))
        .filter(FirewallIntegration.vendor.in_(_candidate_vendors(rule)))
        .all()
    )
    target = rule.firewall_hostname or rule.management_ip
    if target:
        for row in rows:
            if row.host == target or row.name == target:
                return row
        return None  # named a specific box that isn't a known integration — do not guess
    if len(rows) == 1:
        return rows[0]
    return None


_PORT_TOKEN_RE = re.compile(r"^\d+(-\d+)?$")


def _build_services(protocol: str | None, destination_port: str | None) -> list[dict]:
    protos = [p.strip().lower() for p in re.split(r"[,/]", protocol or "tcp") if p.strip()] or ["tcp"]
    ports: list[tuple[int | None, int | None]] = []
    for tok in re.split(r"[,;]", destination_port or ""):
        tok = tok.strip()
        if not tok or not _PORT_TOKEN_RE.match(tok):
            continue
        if "-" in tok:
            lo, hi = tok.split("-", 1)
            ports.append((int(lo), int(hi)))
        else:
            ports.append((int(tok), int(tok)))
    if not ports:
        ports = [(None, None)]
    return [{"proto": proto, "port_low": lo, "port_high": hi} for proto in protos for lo, hi in ports]


def _truthy_requirement(v: str | None) -> bool:
    if not v:
        return False
    return v.strip().lower() not in ("no", "none", "n/a", "not required", "false", "0")


def _normalize_logging(v) -> str:
    if isinstance(v, bool):
        return "session_end" if v else "none"
    s = str(v or "").strip().lower()
    if "both" in s:
        return "both"
    if "start" in s:
        return "session_start"
    if "none" in s or s in ("no", "false", "0"):
        return "none"
    return "session_end"


def _extra_fields(rule: ExtractedRule) -> dict:
    keys = (
        "url_filtering_profile", "ips_profile", "antivirus_profile", "ssl_inspection_profile",
        "qos_requirement", "schedule", "rule_position", "expiry_date", "rule_description",
        "application_ids", "source_address_object", "destination_address_object",
        "cloud_account", "firewall_location",
    )
    return {k: getattr(rule, k) for k in keys if getattr(rule, k)}


def build_poa_document(db: Session, user: User, parsed: ParsedPoa, *, original_filename: str | None, raw_content: str) -> FwPoaDocument:
    h = parsed.header
    doc = FwPoaDocument(
        poa_ref=h.poa_ref or f"POA-{datetime.now(timezone.utc):%Y%m%d%H%M%S}",
        change_ref=h.change_ref, snow_ticket=h.snow_ticket, application_name=h.application_name,
        business_owner=h.business_owner, technical_owner=h.technical_owner, environment=h.environment,
        source_application=h.source_application, destination_application=h.destination_application,
        business_justification=h.business_justification, implementation_window=h.implementation_window,
        rollback_requirement=h.rollback_requirement, source_format=parsed.source_format,
        original_filename=original_filename, raw_content=raw_content,
        parse_warnings_json=list(parsed.warnings), rule_count=len(parsed.rules),
        uploaded_by_id=user.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def build_intent_from_rule(db: Session, user: User, poa_doc: FwPoaDocument, header: ExtractedHeader, rule: ExtractedRule, integration: FirewallIntegration) -> FwIntent:
    nat_required = _truthy_requirement(rule.nat_requirement)
    row = FwIntent(
        requester_id=user.id,
        ticket_ref=header.change_ref or header.snow_ticket or header.poa_ref or poa_doc.poa_ref,
        justification=rule.business_justification or header.business_justification,
        action=rule.action or "allow",
        logging=_normalize_logging(rule.logging),
        source_json=[{"cidr": c} for c in rule.source],
        destination_json=[{"cidr": c} for c in rule.destination],
        service_json=_build_services(rule.protocol, rule.destination_port),
        integration_id=integration.id,
        device_group=rule.device_group or rule.vdom or integration.device_group,
        status="received",
        poa_document_id=poa_doc.id,
        rule_id=rule.rule_id,
        rule_name=rule.rule_name,
        environment=header.environment,
        source_zone=rule.source_zone,
        destination_zone=rule.destination_zone,
        nat_required=nat_required,
        nat_details_json={"requirement": rule.nat_requirement} if nat_required else {},
        security_profile=rule.security_profile,
        extra_fields_json=_extra_fields(rule),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def intake(db: Session, user: User, parsed: ParsedPoa, *, original_filename: str | None, raw_content: str) -> tuple[FwPoaDocument, list[dict]]:
    """Commits the parse: one FwPoaDocument, and one FwIntent per rule that
    has both complete required fields (§20) and a resolvable integration —
    every other rule comes back as a `results` entry explaining exactly why
    nothing was created for it, never a silent drop. Planning is then
    attempted best-effort per created intent so the dry-run/evidence text
    is available immediately; a planning failure downgrades that rule's
    status but does not undo the intent that was created."""
    poa_doc = build_poa_document(db, user, parsed, original_filename=original_filename, raw_content=raw_content)
    results: list[dict] = []

    for rule in parsed.rules:
        missing = rule.missing_required_fields()
        if missing:
            results.append({
                "rule_name": rule.rule_name, "intent_id": None,
                "status": "skipped_missing_information",
                "message": fw_reporting.format_missing_information(missing),
            })
            continue

        integration = find_integration(db, rule)
        if not integration:
            results.append({
                "rule_name": rule.rule_name, "intent_id": None,
                "status": "skipped_no_integration",
                "message": (
                    f"No active firewall integration matched vendor={rule.firewall_vendor!r} "
                    f"platform={rule.management_platform!r}"
                    + (f" host={rule.firewall_hostname or rule.management_ip!r}" if (rule.firewall_hostname or rule.management_ip) else "")
                    + " — add or activate the integration first, or name it explicitly in the POA."
                ),
            })
            continue

        intent = build_intent_from_rule(db, user, poa_doc, parsed.header, rule, integration)

        try:
            fw_plan.build_plan(db, intent)
            results.append({"rule_name": rule.rule_name, "intent_id": str(intent.id), "status": "planned", "message": f"Intent {intent.id} created and planned."})
        except fw_plan.PlanError as e:
            results.append({"rule_name": rule.rule_name, "intent_id": str(intent.id), "status": "skipped_plan_error", "message": f"Intent {intent.id} created, but planning failed: {e}"})
        except panorama.PanoramaError as e:
            results.append({"rule_name": rule.rule_name, "intent_id": str(intent.id), "status": "skipped_plan_error", "message": f"Intent {intent.id} created, but the firewall could not be reached to plan it: {e}"})

    return poa_doc, results
