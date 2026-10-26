"""Mock AWS provider — deterministic demo data, no network calls. This is
the one fully-implemented provider in this delivery, meant to prove the
adapter pattern end-to-end (discover -> normalize -> ingest into IPAM ->
show in dashboard) without requiring real AWS credentials. Azure/GCP/OCI
mocks are thin stubs (see providers/mock/README.md) — extending them to
the same fullness as this one is a same-shaped, mechanical Phase 3 task,
not a design problem.

Demo shape follows docs/ARCHITECTURE.md's DEMO DATA numbers for AWS: 3
accounts, 5 VPCs total, 15 subnets total (3 per VPC).
"""
from __future__ import annotations

from app.providers.base import (
    CloudProvider,
    DiscoveredBgpSession,
    DiscoveredCircuit,
    DiscoveredCloudInterface,
    DiscoveredNetwork,
    DiscoveredPeering,
    DiscoveredRoute,
    DiscoveredRouteTable,
    DiscoveredSubnet,
    DiscoveredVpnConnection,
)

_DEMO_ACCOUNTS = ["111111111111", "222222222222", "333333333333"]

# (account_index, dx connection suffix, attached VPC suffix, VRF, bandwidth
# Mbps, colo location, local ASN, peer (on-prem) ASN, local/peer BGP IPs).
# One Direct Connect per account, landing on that account's own "prod" VPC —
# the real-world MPLS/VRF handoff this phase models (see
# app/providers/mock/snmp.py's matching on-prem-side circuits).
_DEMO_DIRECT_CONNECTS = [
    (0, "use1-01", "prod-use1", "vrf-prod", 1000, "Equinix DC2 - Ashburn", 65000, 64512, "169.254.1.1", "169.254.1.2"),
    (1, "euw1-01", "prod-euw1", "vrf-prod-eu", 1000, "Equinix LD5 - London", 65000, 64512, "169.254.2.1", "169.254.2.2"),
    (2, "apse1-01", "prod-apse1", "vrf-prod-apac", 500, "Equinix SG1 - Singapore", 65000, 64512, "169.254.3.1", "169.254.3.2"),
]

# (account_index, vpc_suffix, cidr, region)
_DEMO_VPCS = [
    (0, "prod-use1", "10.10.0.0/16", "us-east-1"),
    (0, "staging-use1", "10.11.0.0/16", "us-east-1"),
    (1, "prod-euw1", "10.20.0.0/16", "eu-west-1"),
    (1, "shared-services", "10.21.0.0/16", "eu-west-1"),
    (2, "prod-apse1", "10.30.0.0/16", "ap-southeast-1"),
]


def _subnets_for(cidr_base: str) -> list[DiscoveredSubnet]:
    # Three /24s per VPC, cheap and deterministic — first three /24s of the
    # VPC's /16, one per demo AZ.
    prefix = cidr_base.split(".")[0:2]
    azs = ["a", "b", "c"]
    return [
        DiscoveredSubnet(
            external_id=f"subnet-{prefix[0]}{prefix[1]}0{i}",
            cidr=f"{prefix[0]}.{prefix[1]}.{i}.0/24",
            availability_zone=f"{cidr_base.split('.')[0]}-{azs[i]}",
            name=f"subnet-{azs[i]}",
        )
        for i in range(3)
    ]


def _interfaces_for(suffix: str, subnets: list[DiscoveredSubnet]) -> list[DiscoveredCloudInterface]:
    # One ENI in the VPC's first subnet, deterministic and cheap — a
    # primary interface on a stand-in EC2 instance, same "one representative
    # object per network" depth as the route table above.
    sub = subnets[0]
    ip = sub.cidr.rsplit(".", 1)[0] + ".10"
    return [
        DiscoveredCloudInterface(
            external_id=f"eni-{suffix}-01", name=f"eni-{suffix}-01", subnet_external_id=sub.external_id,
            private_ip=ip, attached_to=f"i-{suffix}-app01", status="in_use",
            security_groups=[f"sg-{suffix}-app"],
        ),
    ]


def _route_table_for(suffix: str) -> DiscoveredRouteTable:
    # The VPC's main route table: the mandatory local route plus an
    # internet gateway default route for anything named "shared-services"
    # or "prod" (demo stand-in for "has a public-facing tier"), and a VPC
    # peering route toward the shared-services CIDR for everything else —
    # deterministic and disjoint from the overlap-detector's demo ranges.
    routes = [
        DiscoveredRoute(destination_cidr="10.0.0.0/8", target_type="local", target_ref="local", state="active"),
    ]
    if "shared" in suffix or "prod" in suffix:
        routes.append(DiscoveredRoute(
            destination_cidr="0.0.0.0/0", target_type="internet_gateway", target_ref=f"igw-{suffix}",
        ))
    else:
        routes.append(DiscoveredRoute(
            destination_cidr="10.21.0.0/16", target_type="vpc_peering", target_ref=f"pcx-{suffix}-shared",
        ))
    return DiscoveredRouteTable(external_id=f"rtb-{suffix}", name=f"rtb-{suffix}-main", is_main=True, routes=routes)


class MockAWSProvider(CloudProvider):
    provider_name = "aws"

    def discover_networks(self) -> list[DiscoveredNetwork]:
        networks = []
        for idx, suffix, cidr, region in _DEMO_VPCS:
            account = _DEMO_ACCOUNTS[idx]
            if account != self.account_identifier and self.account_identifier != "*":
                continue
            subnets = _subnets_for(cidr)
            networks.append(DiscoveredNetwork(
                external_id=f"vpc-{suffix}",
                name=f"vpc-{suffix}",
                cidr=cidr,
                region=region,
                account_identifier=account,
                subnets=subnets,
                tags={"ManagedBy": "netsphere-mock", "Environment": suffix.split("-")[0]},
                route_table=_route_table_for(suffix),
                interfaces=_interfaces_for(suffix, subnets),
            ))
        return networks

    def discover_peerings(self) -> list[DiscoveredPeering]:
        # Matches the vpc_peering routes _route_table_for() already creates
        # toward shared-services for every non-prod/non-shared VPC — the
        # peering *connection* object those routes imply, made real. Real
        # AWS peering commonly crosses accounts (as this demo data does:
        # staging-use1/prod-apse1 live in different accounts than
        # shared-services), which is exactly why this is a whole-provider
        # method rather than scoped to one account's own networks.
        return [
            DiscoveredPeering(
                external_id=f"pcx-{suffix}-shared", network_a_name=f"vpc-{suffix}", network_b_name="vpc-shared-services",
            )
            for _, suffix, _, _ in _DEMO_VPCS
            if "shared" not in suffix and "prod" not in suffix
        ]

    def discover_circuits(self) -> list[DiscoveredCircuit]:
        # One Direct Connect per account (see _DEMO_DIRECT_CONNECTS above),
        # each with a single eBGP session to the on-prem PE router — the
        # matching other-side circuit lives in providers/mock/snmp.py.
        return [
            DiscoveredCircuit(
                external_id=f"dxcon-{suffix}", name=f"Direct Connect {suffix}", circuit_type="direct_connect",
                vrf=vrf, bandwidth_mbps=bw, location=loc, status="active", attached_network_name=f"vpc-{vpc_suffix}",
                bgp_sessions=[DiscoveredBgpSession(
                    local_asn=local_asn, peer_asn=peer_asn, local_ip=local_ip, peer_ip=peer_ip,
                    external_id=f"dxcon-{suffix}-bgp",
                )],
            )
            for idx, suffix, vpc_suffix, vrf, bw, loc, local_asn, peer_asn, local_ip, peer_ip in _DEMO_DIRECT_CONNECTS
            if _DEMO_ACCOUNTS[idx] == self.account_identifier or self.account_identifier == "*"
        ]

    def discover_vpn_connections(self) -> list[DiscoveredVpnConnection]:
        # A Site-to-Site VPN backup path for shared-services, alongside
        # whichever account's Direct Connect actually lands there — real
        # AWS environments commonly keep a VPN as a cheaper/faster-to-
        # provision fallback for exactly this kind of shared hub network.
        if self.account_identifier not in (_DEMO_ACCOUNTS[1], "*"):
            return []
        return [DiscoveredVpnConnection(external_id="vpn-shared-services-01", network_name="vpc-shared-services", peer_ip="203.0.113.10")]

    @staticmethod
    def demo_accounts() -> list[str]:
        return list(_DEMO_ACCOUNTS)
