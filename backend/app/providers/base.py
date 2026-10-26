"""Cloud provider adapter contract. See ARCHITECTURE.md §3 for the rule
this enforces: no cloud-SDK import or vendor field name may appear outside
this package. Services and API endpoints only ever see these normalized
dataclasses.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DiscoveredSubnet:
    external_id: str
    cidr: str
    availability_zone: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class DiscoveredRoute:
    """One row of a route table (cloud) or a device's static routing table
    (on-prem) — same normalized shape either way, since a route is a route
    regardless of which side of the hybrid network it's on."""

    destination_cidr: str
    target_type: str  # local|internet_gateway|nat_gateway|vpc_peering|transit_gateway|vpn_gateway|virtual_appliance|next_hop|interface|instance|other
    target_ref: str | None = None  # the target's own id/name/next-hop-ip — free text, vendor-specific
    state: str = "active"  # active|blackhole
    external_id: str | None = None


@dataclass(frozen=True)
class DiscoveredRouteTable:
    external_id: str
    name: str
    is_main: bool = False
    routes: list[DiscoveredRoute] = field(default_factory=list)


@dataclass(frozen=True)
class DiscoveredCloudInterface:
    """An ENI/NIC — docs/ERD.md's `network_interfaces` (Phase 3, "ENIs/NICs
    discovered per cloud"). Attached to a subnet within the network it
    rides along with, same "discovery result carries its own children"
    shape as DiscoveredNetwork.subnets. Security groups are named here as
    free text (like Network.firewall's own free-text convention) — a
    normalized, cross-cloud security-group model is Phase 6's
    `security_groups`/`security_rules`, not this phase's job."""

    external_id: str
    name: str
    subnet_external_id: str
    private_ip: str | None = None
    public_ip: str | None = None
    attached_to: str | None = None  # the compute instance/resource it's attached to — free text
    status: str = "in_use"  # in_use|available
    security_groups: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DiscoveredPeering:
    """A VPC/VNet/VCN peering connection between two networks, named by
    each side's `DiscoveredNetwork.name` (the same natural key discovery
    already exposes — no separate external_id table needed to resolve
    it). Not every provider has this concept in the same shape GCP's
    routes-based model has no first-class peering object either, so
    `CloudProvider.discover_peerings()` defaults to returning none rather
    than forcing every provider to invent one."""

    external_id: str
    network_a_name: str
    network_b_name: str
    status: str = "active"  # active|pending|rejected|expired


@dataclass(frozen=True)
class DiscoveredBgpSession:
    """A BGP peering session running over a `DiscoveredCircuit` — the
    control plane that actually advertises routes across a dedicated
    interconnect (Direct Connect/ExpressRoute/Interconnect/FastConnect) or
    an on-prem MPLS handoff. Nested under the circuit it rides on, same
    "discovery result carries its own children" shape as
    `DiscoveredNetwork.subnets`/`DiscoveredRouteTable.routes`."""

    local_asn: int
    peer_asn: int
    local_ip: str | None = None
    peer_ip: str | None = None
    state: str = "established"  # established|idle|down
    external_id: str | None = None


@dataclass(frozen=True)
class DiscoveredCircuit:
    """A dedicated interconnect — AWS Direct Connect, Azure ExpressRoute,
    GCP Cloud Interconnect, OCI FastConnect — or the on-prem MPLS/VRF
    handoff on the other end of the same physical link. Provider-agnostic:
    a circuit is a circuit whether it's the cloud side (owned by a
    `CloudAccount`) or the on-prem side (owned by a `Device`); which owner
    applies is decided by which provider returned it, not by a field here.
    `attached_network_name`/`attached_device_hostname` name the local
    resource this circuit's other end lands on, resolved the same way
    `DiscoveredPeering` resolves networks — by the natural key discovery
    already exposes, not a separate external_id table. Exactly one of them
    is normally set (a cloud circuit names the VPC/VNet/VCN it attaches to;
    an on-prem circuit names the router/firewall that terminates it) but
    neither is required — an unresolvable or not-yet-discovered target is
    a skip-and-retry-later, same contract as peerings."""

    external_id: str
    name: str
    circuit_type: str  # direct_connect|expressroute|interconnect|fastconnect|mpls
    vrf: str | None = None
    bandwidth_mbps: int | None = None
    location: str | None = None  # the colo/POP name — free text, vendor-specific
    status: str = "active"  # active|provisioning|down|decommissioned
    attached_network_name: str | None = None
    attached_device_hostname: str | None = None
    bgp_sessions: list[DiscoveredBgpSession] = field(default_factory=list)


@dataclass(frozen=True)
class DiscoveredVpnConnection:
    """An IPsec site-to-site VPN — typically a backup path alongside a
    dedicated circuit (or the only path, for a network that doesn't
    warrant one), riding the public internet rather than a physical
    interconnect, so it has no `Circuit` owner of its own. Named by the
    same `Network.name` natural key `DiscoveredPeering` already uses."""

    external_id: str
    network_name: str
    peer_ip: str | None = None
    status: str = "up"  # up|down|degraded


@dataclass(frozen=True)
class DiscoveredNetwork:
    external_id: str
    name: str
    cidr: str
    region: str
    account_identifier: str
    subnets: list[DiscoveredSubnet] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    # One route table per network — the real simplification this phase
    # ships with. AWS/Azure/OCI can have several route tables per VPC with
    # per-subnet associations; GCP routes are network-scoped with no
    # separate route-table object at all. Modeling "the network's routing,
    # as one table" covers all four honestly without inventing per-provider
    # association semantics this phase doesn't need yet — see
    # app/services/routing.py's docstring for the same trade-off spelled
    # out where it's consumed.
    route_table: DiscoveredRouteTable | None = None
    # ENIs/NICs attached to subnets within this network — see
    # DiscoveredCloudInterface's own docstring for the Phase 3/6 boundary.
    interfaces: list[DiscoveredCloudInterface] = field(default_factory=list)


class CloudProvider(ABC):
    """One instance per (provider, account/subscription/project). Real,
    credential-backed subclasses (AWSProvider, AzureProvider, GCPProvider,
    OCIProvider) live in this same package and now call the real SDKs —
    see each module's docstring — using `credentials`, the decrypted dict
    from a CloudIntegration row (app/models/cloud_integration.py,
    app/services/cloud_credentials.py). A real provider instantiated
    without credentials (no matching CloudIntegration configured) still
    raises NotImplementedError, same as before Phase 3.
    Mock subclasses (providers/mock/) implement the same interface against
    generated demo data so the rest of the platform can be built and
    tested against something real-shaped without cloud credentials.
    """

    provider_name: str = "unknown"

    def __init__(self, account_identifier: str, region: str | None = None, credentials: dict | None = None) -> None:
        self.account_identifier = account_identifier
        self.region = region
        self.credentials = credentials or {}

    @abstractmethod
    def discover_networks(self) -> list[DiscoveredNetwork]:
        """VPCs/VNets/VCNs (with their subnets and ENIs/NICs) for this account."""
        raise NotImplementedError

    def discover_peerings(self) -> list[DiscoveredPeering]:
        """Peering connections involving this account's networks. Not
        `@abstractmethod` — GCP's routes-based model has no first-class
        peering object, so the base default is "none" rather than forcing
        every provider to fake one. Only providers/mock/aws.py overrides
        this meaningfully in this delivery."""
        return []

    def discover_circuits(self) -> list[DiscoveredCircuit]:
        """This account's dedicated interconnects (Direct Connect/
        ExpressRoute/Interconnect/FastConnect) — Phase 8's `circuits`/
        `bgp_sessions` (docs/ERD.md). Default "none", same rationale as
        `discover_peerings()`: not every account has a dedicated
        interconnect provisioned."""
        return []

    def discover_vpn_connections(self) -> list[DiscoveredVpnConnection]:
        """IPsec site-to-site VPNs involving this account's networks —
        Phase 8's `vpn_connections`. Default "none"."""
        return []


@dataclass(frozen=True)
class DiscoveredInterface:
    external_id: str
    name: str
    description: str | None = None
    ip_address: str | None = None
    mac_address: str | None = None
    admin_status: str = "up"
    oper_status: str = "up"
    speed_mbps: int | None = None
    vlan_id: int | None = None


@dataclass(frozen=True)
class DiscoveredDevice:
    external_id: str
    hostname: str
    device_type: str
    vendor: str | None = None
    mgmt_ip: str | None = None
    site: str | None = None
    interfaces: list[DiscoveredInterface] = field(default_factory=list)
    # A device's own static routing table — on-prem routes belong to the
    # device that holds them, not to a network the way a cloud route table
    # does, so these ride along with the device's own discovery result
    # rather than a separate discover_routes() round trip.
    routes: list[DiscoveredRoute] = field(default_factory=list)


class NetworkDeviceProvider(ABC):
    """One instance per discovery run (a whole SNMP sweep, a site, etc. —
    unlike CloudProvider there's no per-account credential to scope this
    to). Real, credential-backed subclasses (`providers/snmp.py`) raise
    NotImplementedError from every method until real polling is wired in
    (pysnmp/netmiko); `providers/mock/snmp.py` implements the same
    interface against generated demo data, same rationale as MockAWSProvider.
    """

    provider_name: str = "unknown"

    @abstractmethod
    def discover_devices(self) -> list[DiscoveredDevice]:
        """Devices (with their interfaces and static routes) reachable by
        this provider."""
        raise NotImplementedError

    def discover_circuits(self) -> list[DiscoveredCircuit]:
        """The on-prem side of a dedicated interconnect handoff — an MPLS
        circuit terminating on one of this provider's own devices, the
        other end of the exact same physical link a `CloudProvider`'s own
        `discover_circuits()` reports from the cloud side. A whole-run
        method (like `discover_devices()`), not per-device, since unlike
        `CloudProvider` there's no per-account scope to hang this off of —
        `DiscoveredCircuit.attached_device_hostname` says which of this
        run's devices terminates each one. Default "none", same rationale
        as `CloudProvider.discover_peerings()`."""
        return []


class FirewallProvider(ABC):
    """Interface only in this delivery — no mock implementation yet (Module
    7 is Phase 6). Deliberately shaped to match the adapter contract already
    specified in `firewall-policy-automation-design.md` §3.2 rather than
    inventing a second one: fetch_rulebase/fetch_objects/snapshot/render/
    preview/apply/poll/verify/rollback. Not reproduced here to avoid two
    copies drifting — see that document when this phase starts.
    """
