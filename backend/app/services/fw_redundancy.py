"""Redundancy / shadow analysis — §3.6, scoped down from fwauto's full
interval-tree/atom-decomposition algorithm (claude/panorama-executor-
implementation.md) to direct CIDR-subset and port-range-subset containment
checks against the device's *existing* rulebase, evaluated top-down in
rule order (first match wins, matching real firewall evaluation order).

This is a deliberately conservative simplification, not a shortcut taken
carelessly: a coverage claim only fires when a requested CIDR is a subset
of a *single* existing rule's source/destination CIDR (rather than a union
of several, which fwauto's atom-splitting handles). That means this
analysis can under-report "already allowed" in cases spanning multiple
existing rules — an acceptable direction to be wrong in, since it only
costs a redundant-but-harmless rule creation, never a false "already
covered" that skips a rule the requester actually needs (same asymmetry
fwauto's docs call out as the one to protect against).

App-ID conservatism (fwauto's note, carried over): a rule constrained to
specific applications never counts as covering an L4-only request — the
request wants the port unconditionally, the existing rule only permits it
conditionally on App-ID matching.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.cidr import parse_cidr


@dataclass
class NormalizedRule:
    """One existing rule, already flattened from Panorama's XML into this
    shape by fw_panorama_adapter.fetch_rulebase — sources/destinations are
    resolved CIDRs (address-group members expanded), not object names."""

    name: str
    action: str  # allow | deny
    source_cidrs: list[str]
    destination_cidrs: list[str]
    services: list[dict]  # [{proto, port_low, port_high}]
    applications: list[str] = field(default_factory=list)
    disabled: bool = False


@dataclass
class RedundancyResult:
    verdict: str  # no_change_required | duplicate | shadowed | blocked_by_deny | needs_new_rule
    covering_rule: str | None = None
    blocking_rule: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict, "covering_rule": self.covering_rule,
            "blocking_rule": self.blocking_rule, "notes": self.notes,
        }


def _cidr_subset(inner: str, outer: str) -> bool:
    try:
        a, b = parse_cidr(inner), parse_cidr(outer)
    except Exception:
        return False
    return a.network >= b.network and a.broadcast <= b.broadcast


def _cidrs_covered(requested: list[str], existing: list[str]) -> bool:
    if not existing:
        return False
    if any(c in ("0.0.0.0/0", "any") for c in existing):
        return True
    return all(any(_cidr_subset(r, e) for e in existing) for r in requested)


def _services_covered(requested: list[dict], existing: list[dict]) -> bool:
    if not existing:
        return False
    if any(s.get("proto") == "any" for s in existing):
        return True
    for req in requested:
        covered = False
        for ex in existing:
            if ex.get("proto") != req.get("proto"):
                continue
            if ex.get("port_low", 0) <= req.get("port_low", 0) and req.get("port_high", 0) <= ex.get("port_high", 0):
                covered = True
                break
        if not covered:
            return False
    return True


def _intersects_cidrs(a: list[str], b: list[str]) -> bool:
    if not a or not b:
        return False
    if any(c in ("0.0.0.0/0", "any") for c in a + b):
        return True
    for x in a:
        for y in b:
            if _cidr_subset(x, y) or _cidr_subset(y, x):
                return True
    return False


def _intersects_services(a: list[dict], b: list[dict]) -> bool:
    if not a or not b:
        return False
    if any(s.get("proto") == "any" for s in a + b):
        return True
    for x in a:
        for y in b:
            if x.get("proto") != y.get("proto"):
                continue
            if x.get("port_low", 0) <= y.get("port_high", 0) and y.get("port_low", 0) <= x.get("port_high", 0):
                return True
    return False


def _rule_intersects_request(rule: NormalizedRule, source: list[str], destination: list[str], service: list[dict]) -> bool:
    return (
        _intersects_cidrs(source, rule.source_cidrs)
        and _intersects_cidrs(destination, rule.destination_cidrs)
        and _intersects_services(service, rule.services)
    )


def _rule_covers_request(rule: NormalizedRule, source: list[str], destination: list[str], service: list[dict], has_app_constraint: bool) -> bool:
    if rule.applications and not has_app_constraint:
        # App-ID conservatism: a rule scoped to specific apps never covers
        # an L4-only request that wants the port unconditionally.
        return False
    return (
        _cidrs_covered(source, rule.source_cidrs)
        and _cidrs_covered(destination, rule.destination_cidrs)
        and _services_covered(service, rule.services)
    )


def analyze(
    *, action: str, source: list[str], destination: list[str], service: list[dict],
    existing_rules: list[NormalizedRule], has_app_constraint: bool = False,
) -> RedundancyResult:
    notes: list[str] = []

    for rule in existing_rules:
        if rule.disabled:
            continue
        if not _rule_intersects_request(rule, source, destination, service):
            continue

        covers = _rule_covers_request(rule, source, destination, service, has_app_constraint)

        if rule.action == action and covers:
            if action == "allow":
                return RedundancyResult("no_change_required", covering_rule=rule.name, notes=[
                    f"Already permitted end-to-end by existing rule {rule.name!r}.",
                ])
            return RedundancyResult("duplicate", covering_rule=rule.name, notes=[
                f"An equivalent deny rule {rule.name!r} already exists.",
            ])

        if rule.action != action and covers:
            if action == "allow":
                # An earlier deny fully covers the requested traffic.
                return RedundancyResult("blocked_by_deny", blocking_rule=rule.name, notes=[
                    f"Existing deny rule {rule.name!r} intersects the request — "
                    "the new allow would be partially or fully ineffective unless placed above it.",
                ])
            notes.append(f"Existing allow rule {rule.name!r} covers this traffic — the new deny would be shadowed unless placed above it.")
            return RedundancyResult("shadowed", blocking_rule=rule.name, notes=notes)

        if rule.action != action and not covers:
            # Partial intersection with an opposite-action rule: not fully
            # blocking/shadowing, but worth surfacing to the approver.
            notes.append(f"Rule {rule.name!r} ({rule.action}) partially overlaps this request — review placement.")

    return RedundancyResult("needs_new_rule", notes=notes)
