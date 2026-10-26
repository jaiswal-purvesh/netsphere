"""Phase 5 — Path Analyzer: "would this traffic be allowed today?" per
claude/firewall-policy-automation-design.md §3.8's `POST /v1/simulate`
(read-only, no intent created — "the single highest-ROI feature," per the
design doc, because it needs no write access to ship).

The path model NetSphere's topology graph already uses (app/api/v1/
endpoints/topology.py) is deliberately simple: `Network.firewall` is a
single free-text name, so a request can cross at most two enforcement
points — the source network's firewall and the destination network's,
if they differ. This is a real simplification (the design doc's §9 "What I
would revisit" calls out the same thing: "v1 uses a static topology map...
past ~100 EPs or with dynamic routing, this needs to become real path
computation over the routing/peering graph") but it's the honest one for
what this app's data model currently supports — extending it to multi-hop
route-table-aware path computation is Phase 5's own follow-up (roadmap
item 4, routes/route_tables), not a gap to paper over here.

Each hop's verdict is a REAL check against a REAL device's current
rulebase (app/services/fw_panorama_adapter.fetch_rulebase +
app/services/fw_redundancy.analyze — the same primitives Policy Optimizer
and the firewall-automation pipeline already use), never a guess. A hop
whose Network.firewall name doesn't match a credentialed, live
FirewallIntegration comes back "unknown" — not "allowed" and not
"blocked" — because this project's rule is that an unverifiable claim is
reported as unverifiable, not silently assumed either way.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.integration import FirewallIntegration
from app.models.network import Network
from app.services import fw_panorama_adapter as panorama
from app.services import secrets as secretsvc
from app.services.cidr import CidrError, ip_to_int, parse_cidr
from app.services.fw_panorama_adapter import PanoramaError
from app.services.fw_redundancy import analyze as redundancy_analyze
from app.services.secrets import SecretDecryptionError

ANALYZABLE_VENDORS = ("panorama", "pan_os")


@dataclass
class HopResult:
    firewall: str
    integration_id: str | None
    verdict: str  # allowed | blocked | not_currently_allowed | unknown
    covering_rule: str | None = None
    blocking_rule: str | None = None
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "firewall": self.firewall, "integration_id": self.integration_id, "verdict": self.verdict,
            "covering_rule": self.covering_rule, "blocking_rule": self.blocking_rule,
            "notes": self.notes, "error": self.error,
        }


@dataclass
class PathSimulationResult:
    source_network: Network | None
    destination_network: Network | None
    hops: list[HopResult]
    overall_verdict: str
    notes: list[str]


def _cidr_of(addr: str) -> str:
    """A simulate request may name a single host or a CIDR — normalize to
    a /32 CIDR for a bare address so it feeds fw_redundancy's containment
    checks the same way an existing rule's address objects do."""
    addr = addr.strip()
    if "/" in addr:
        return parse_cidr(addr).cidr
    ip_to_int(addr)  # raises CidrError on a bad address
    return f"{addr}/32"


def _resolve_network(db: Session, addr: str) -> Network | None:
    n = ip_to_int(addr.split("/")[0])
    return db.execute(
        select(Network)
        .where(Network.network_addr <= n, Network.broadcast_addr >= n, Network.deleted_at.is_(None))
        .order_by(Network.prefix_len.desc())
        .limit(1),
    ).scalar_one_or_none()


def _find_integration(db: Session, firewall_name: str) -> FirewallIntegration | None:
    """Matches Network.firewall's free-text name against a credentialed
    integration by name (case/whitespace-insensitive) — the same
    naming-is-the-link convention Policy Optimizer's integration picker
    relies on. Only panorama/pan_os are considered: those are the only
    vendors with a real fetch_rulebase() adapter (see fw_panorama_adapter,
    same restriction as Policy Optimizer's ANALYZABLE_VENDORS)."""
    candidates = db.execute(
        select(FirewallIntegration).where(
            FirewallIntegration.vendor.in_(ANALYZABLE_VENDORS), FirewallIntegration.is_active.is_(True),
        ),
    ).scalars().all()
    target = firewall_name.strip().lower()
    return next((i for i in candidates if i.name.strip().lower() == target), None)


def _check_hop(
    db: Session, firewall_name: str, source_cidr: str, destination_cidr: str, service: dict,
) -> HopResult:
    integration = _find_integration(db, firewall_name)
    if not integration:
        return HopResult(
            firewall=firewall_name, integration_id=None, verdict="unknown",
            notes=[f"No credentialed, live integration named {firewall_name!r} — cannot verify against a real rulebase."],
        )
    if not integration.host or not integration.secret_ciphertext:
        return HopResult(
            firewall=firewall_name, integration_id=str(integration.id), verdict="unknown",
            notes=[f"Integration {integration.name!r} has no host/credential saved yet."],
        )
    device_group = integration.device_group
    if not device_group:
        return HopResult(
            firewall=firewall_name, integration_id=str(integration.id), verdict="unknown",
            notes=[f"Integration {integration.name!r} has no device group configured."],
        )

    try:
        secret = secretsvc.decrypt(integration.secret_ciphertext)
        rules = panorama.fetch_rulebase(integration.host, integration.port, integration.verify_tls, secret, device_group)
    except (PanoramaError, SecretDecryptionError) as exc:
        return HopResult(
            firewall=firewall_name, integration_id=str(integration.id), verdict="unknown",
            error=str(exc), notes=[f"Live check against {integration.name!r} failed: {exc}"],
        )

    result = redundancy_analyze(
        action="allow", source=[source_cidr], destination=[destination_cidr], service=[service],
        existing_rules=rules,
    )
    verdict_map = {
        "no_change_required": "allowed",
        "duplicate": "allowed",
        "blocked_by_deny": "blocked",
        "needs_new_rule": "not_currently_allowed",
        "shadowed": "not_currently_allowed",  # not reachable for action="allow" requests, kept for completeness
    }
    return HopResult(
        firewall=firewall_name, integration_id=str(integration.id), verdict=verdict_map.get(result.verdict, "unknown"),
        covering_rule=result.covering_rule, blocking_rule=result.blocking_rule, notes=result.notes,
    )


def simulate(db: Session, source: str, destination: str, protocol: str, port_low: int, port_high: int) -> PathSimulationResult:
    try:
        source_cidr = _cidr_of(source)
        destination_cidr = _cidr_of(destination)
    except CidrError as e:
        raise ValueError(str(e)) from e

    service = {"proto": protocol, "port_low": port_low, "port_high": port_high}
    source_network = _resolve_network(db, source)
    destination_network = _resolve_network(db, destination)

    notes: list[str] = []
    if not source_network:
        notes.append(f"{source!r} does not fall inside any known network — cannot identify a source-side enforcement point.")
    if not destination_network:
        notes.append(f"{destination!r} does not fall inside any known network — cannot identify a destination-side enforcement point.")

    firewall_names: list[str] = []
    for net in (source_network, destination_network):
        if net and net.firewall and net.firewall not in firewall_names:
            firewall_names.append(net.firewall)

    if not firewall_names:
        notes.append(
            "No firewall is recorded against the source or destination network — nothing in this app's inventory "
            "sits in the path, so this traffic would flow unfiltered as far as NetSphere can see.",
        )
        return PathSimulationResult(
            source_network=source_network, destination_network=destination_network,
            hops=[], overall_verdict="allowed", notes=notes,
        )

    hops = [_check_hop(db, name, source_cidr, destination_cidr, service) for name in firewall_names]

    if any(h.verdict == "blocked" for h in hops):
        overall = "blocked"
    elif any(h.verdict == "unknown" for h in hops):
        overall = "unknown"
    elif any(h.verdict == "not_currently_allowed" for h in hops):
        overall = "not_currently_allowed"
    else:
        overall = "allowed"

    return PathSimulationResult(
        source_network=source_network, destination_network=destination_network,
        hops=hops, overall_verdict=overall, notes=notes,
    )
