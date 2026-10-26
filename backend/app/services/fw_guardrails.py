"""Deterministic guardrails-as-code — §3.7. Kept as plain Python rather than
OPA/Rego for this phase (the rule set is small and changes with the code,
not independently of it); the contract — a list of {rule, severity,
message} findings, hard findings block the plan — is what would carry over
if these ever move to a real policy engine, so callers should not assume
anything about *how* a finding was produced.

Guardrails run once at plan time (fw_plan.build_plan) and are re-run at
execute time (fw_executor.execute) per §3.7's "run twice" requirement, since
a plan can sit `awaiting_approval` for a while and the guardrail set itself
may have changed underneath it.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.cidr import CidrError, parse_cidr

ANY_SOURCE_CIDRS = {"0.0.0.0/0"}
MAX_DESTINATION_HOSTS_WARN = 1024


@dataclass
class GuardrailFinding:
    rule: str
    severity: str  # "hard" | "warn"
    message: str

    def to_dict(self) -> dict:
        return {"rule": self.rule, "severity": self.severity, "message": self.message}


def evaluate(*, action: str, source: list[dict], destination: list[dict], service: list[dict], expires_at, exec_approval: bool = False, target_kind: str = "firewall") -> list[GuardrailFinding]:
    findings: list[GuardrailFinding] = []

    if target_kind == "aws_sg" and action == "deny":
        findings.append(GuardrailFinding(
            "aws-sg-no-deny", "hard",
            "AWS Security Groups do not support explicit deny rules (allow-only) — use a Network ACL for a deny requirement.",
        ))

    if action == "allow":
        for sel in source:
            cidr = sel.get("cidr", "")
            if cidr.strip() in ANY_SOURCE_CIDRS:
                findings.append(GuardrailFinding(
                    "no-any-source", "hard",
                    "Source 0.0.0.0/0 is not permitted on allow rules.",
                ))
        if not service:
            findings.append(GuardrailFinding(
                "service-required", "hard",
                "Service must be specified; any-service allow is not permitted.",
            ))

    if not source:
        findings.append(GuardrailFinding("source-required", "hard", "At least one source is required."))
    if not destination:
        findings.append(GuardrailFinding("destination-required", "hard", "At least one destination is required."))

    for sel, role in [(s, "source") for s in source] + [(d, "destination") for d in destination]:
        cidr = sel.get("cidr", "")
        try:
            parsed = parse_cidr(cidr)
        except CidrError as e:
            findings.append(GuardrailFinding(f"{role}-cidr-invalid", "hard", str(e)))
            continue
        host_count = parsed.broadcast - parsed.network + 1
        if role == "destination" and host_count > MAX_DESTINATION_HOSTS_WARN:
            findings.append(GuardrailFinding(
                "destination-too-broad", "warn",
                f"Destination {cidr} spans {host_count} hosts — consider narrowing.",
            ))

    for svc in service:
        proto = svc.get("proto")
        if proto not in ("tcp", "udp", "icmp", "any"):
            findings.append(GuardrailFinding("service-invalid", "hard", f"Unknown protocol {proto!r}."))
        if proto in ("tcp", "udp"):
            lo, hi = svc.get("port_low"), svc.get("port_high")
            if lo is None or hi is None or not (0 < lo <= hi <= 65535):
                findings.append(GuardrailFinding("service-invalid", "hard", f"Invalid port range {lo}-{hi}."))

    if expires_at is None and not exec_approval:
        findings.append(GuardrailFinding(
            "permanent-requires-exec-approval", "warn",
            "No expiry set — permanent rules should carry executive approval; flagged for reviewer attention.",
        ))

    return findings


def has_hard_failures(findings: list[GuardrailFinding]) -> bool:
    return any(f.severity == "hard" for f in findings)
