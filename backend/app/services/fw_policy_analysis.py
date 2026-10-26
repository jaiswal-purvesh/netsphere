"""Whole-rulebase hygiene analysis — the actual "Policy Optimizer" logic
behind the /firewalls page. Pulls a live rulebase via
fw_panorama_adapter.fetch_rulebase() and evaluates it top-down, rule by
rule, producing the same category of findings FireMon/Tufin/AlgoSec surface
on their rulebase-cleanup dashboards:

  any_any             critical  source=any AND destination=any AND service=any
  overly_permissive   warn      source=any or destination=any (but not all three)
  disabled            info      administratively disabled — flagged so a
                                 stale disabled rule doesn't quietly rot
                                 forever, not because disabled is itself risky
  shadowed            critical  an earlier ALLOW/DENY rule with an
                                 unconditional (App-ID-free) overlapping
                                 match makes this rule unreachable — the
                                 same "duplicate work" a shadow/redundancy
                                 audit exists to catch. When the shadowing
                                 rule is a DENY, this is a blocked_by_deny
                                 case: the later rule can never fire.
  duplicate           warn      this rule's source+destination+service is
                                 fully covered by an earlier rule with the
                                 SAME action, and neither is app-scoped —
                                 i.e. it does nothing an earlier rule
                                 doesn't already do.

Reuses fw_redundancy's containment primitives directly rather than
reimplementing CIDR/port-range subset logic — those functions were written
for "does one candidate request already match an existing rule" and apply
unchanged to "does an earlier rulebase rule already match this later one."

Severity counts (critical/warn/info) are the input to the /compliance
module's aggregate view — a framework-scoped "how many any-any rules touch
this subnet" question is answered by filtering these same findings by the
rule's CIDRs, not by a separate analysis.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.fw_redundancy import (
    NormalizedRule,
    _cidrs_covered,
    _rule_intersects_request,
    _services_covered,
)

SEVERITY_ORDER = {"critical": 0, "warn": 1, "info": 2}


@dataclass
class PolicyFinding:
    rule: str
    category: str
    severity: str  # critical | warn | info
    message: str
    related_rule: str | None = None

    def to_dict(self) -> dict:
        return {
            "rule": self.rule, "category": self.category, "severity": self.severity,
            "message": self.message, "related_rule": self.related_rule,
        }


def _is_any(cidrs: list[str]) -> bool:
    return any(c in ("any", "0.0.0.0/0") for c in cidrs)


def _service_is_any(services: list[dict]) -> bool:
    return any(s.get("proto") == "any" for s in services)


def _rule_covers_rule(earlier: NormalizedRule, later: NormalizedRule) -> bool:
    """True when `earlier` unconditionally matches everything `later`
    matches — reusing fw_redundancy's per-selector containment checks, with
    the same App-ID conservatism: an app-scoped earlier rule never counts
    as covering, since it only matches conditionally on App-ID."""
    if earlier.applications:
        return False
    return (
        _cidrs_covered(later.source_cidrs, earlier.source_cidrs)
        and _cidrs_covered(later.destination_cidrs, earlier.destination_cidrs)
        and _services_covered(later.services, earlier.services)
    )


def analyze_rulebase(rules: list[NormalizedRule]) -> list[PolicyFinding]:
    findings: list[PolicyFinding] = []

    for idx, rule in enumerate(rules):
        if rule.disabled:
            findings.append(PolicyFinding(
                rule=rule.name, category="disabled", severity="info",
                message="Rule is administratively disabled.",
            ))
            continue  # inactive: poses no live risk, and can't shadow/duplicate anything at runtime

        src_any, dst_any, svc_any = _is_any(rule.source_cidrs), _is_any(rule.destination_cidrs), _service_is_any(rule.services)
        if rule.action == "allow" and src_any and dst_any and svc_any:
            findings.append(PolicyFinding(
                rule=rule.name, category="any_any", severity="critical",
                message="Allows any source, any destination, any service — no effective scoping.",
            ))
        elif rule.action == "allow" and (src_any or dst_any):
            which = "source" if src_any else "destination"
            findings.append(PolicyFinding(
                rule=rule.name, category="overly_permissive", severity="warn",
                message=f"Rule has unrestricted {which} (\"any\") — narrow to the actual required CIDRs.",
            ))

        for earlier in rules[:idx]:
            if earlier.disabled:
                continue
            if not _rule_intersects_request(earlier, rule.source_cidrs, rule.destination_cidrs, rule.services):
                continue
            if not _rule_covers_rule(earlier, rule):
                continue
            if earlier.action != rule.action:
                findings.append(PolicyFinding(
                    rule=rule.name, category="shadowed", severity="critical",
                    message=f"Unreachable: earlier rule \"{earlier.name}\" ({earlier.action}) already matches "
                            f"everything this rule matches, so this rule never evaluates.",
                    related_rule=earlier.name,
                ))
            else:
                findings.append(PolicyFinding(
                    rule=rule.name, category="duplicate", severity="warn",
                    message=f"Redundant: earlier rule \"{earlier.name}\" (same action) already covers this rule's "
                            f"full match — safe to remove or merge.",
                    related_rule=earlier.name,
                ))
            break  # first (topmost) covering rule is the one that actually applies

    return findings


def severity_counts(findings: list[PolicyFinding]) -> dict:
    counts = {"critical": 0, "warn": 0, "info": 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return counts
