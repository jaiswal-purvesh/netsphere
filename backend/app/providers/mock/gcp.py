"""Mock GCP provider — deterministic demo data, no network calls. Same
role as providers/mock/aws.py: proves the provider adapter pattern for a
third cloud without needing real GCP credentials.

Demo shape follows providers/mock/README.md's numbers for GCP: 3 projects,
4 VPCs total, 10 subnets total (uneven per-VPC counts, unlike AWS/Azure's
uniform 3-per-network — GCP VPCs commonly have a different subnet per
region rather than a fixed count, which this mirrors).
"""
from __future__ import annotations

from app.providers.base import (
    CloudProvider,
    DiscoveredBgpSession,
    DiscoveredCircuit,
    DiscoveredCloudInterface,
    DiscoveredNetwork,
    DiscoveredRoute,
    DiscoveredRouteTable,
    DiscoveredSubnet,
)

# (project_index, circuit suffix, attached VPC suffix, VRF, bandwidth Mbps,
# colo location, local ASN, peer (on-prem) ASN, local/peer BGP IPs). One
# Cloud Interconnect attachment per project — same MPLS/VRF-per-cloud shape
# as the AWS/Azure mocks (see app/providers/mock/snmp.py for the matching
# on-prem-side circuit).
_DEMO_INTERCONNECTS = [
    (0, "uscentral1-01", "prod-vpc", "vrf-prod", 1000, "Equinix SV1 - San Jose", 65020, 15169, "169.254.20.1", "169.254.20.2"),
    (1, "uscentral1-02", "staging-vpc", "vrf-staging", 500, "Equinix SV1 - San Jose", 65020, 15169, "169.254.21.1", "169.254.21.2"),
    (2, "uscentral1-03", "shared-vpc", "vrf-shared", 500, "Equinix SV1 - San Jose", 65020, 15169, "169.254.22.1", "169.254.22.2"),
]

_DEMO_PROJECTS = ["netsphere-demo-prod", "netsphere-demo-staging", "netsphere-demo-shared"]

# (project_index, vpc_suffix, cidr, region, subnet_count)
_DEMO_VPCS = [
    (0, "prod-vpc", "10.50.0.0/16", "us-central1", 3),
    (0, "prod-vpc-euw", "10.51.0.0/16", "europe-west1", 3),
    (1, "staging-vpc", "10.52.0.0/16", "us-central1", 2),
    (2, "shared-vpc", "10.53.0.0/16", "us-central1", 2),
]


def _subnets_for(cidr_base: str, count: int) -> list[DiscoveredSubnet]:
    prefix = cidr_base.split(".")[0:2]
    return [
        DiscoveredSubnet(
            external_id=f"subnet-{prefix[0]}{prefix[1]}0{i}",
            cidr=f"{prefix[0]}.{prefix[1]}.{i}.0/24",
            availability_zone=f"{cidr_base.split('.')[0]}-zone-{chr(97 + i)}",
            name=f"subnet-{i + 1}",
        )
        for i in range(count)
    ]


def _interfaces_for(suffix: str, subnets: list[DiscoveredSubnet]) -> list[DiscoveredCloudInterface]:
    # One vNIC in the VPC's first subnet, attached to a stand-in Compute
    # Engine instance — GCP's own term for this object.
    sub = subnets[0]
    ip = sub.cidr.rsplit(".", 1)[0] + ".5"
    return [
        DiscoveredCloudInterface(
            external_id=f"vnic-{suffix}-01", name="nic0", subnet_external_id=sub.external_id,
            private_ip=ip, attached_to=f"{suffix}-app-01", status="in_use",
            security_groups=[f"{suffix}-allow-app"],  # GCP calls these firewall tags, not security groups
        ),
    ]


def _route_table_for(suffix: str) -> DiscoveredRouteTable:
    # GCP has no route-table object at all — routes are network-scoped and
    # apply platform-wide (or by instance tag). Modeled here as one
    # implicit table per VPC so it fits the same normalized shape as the
    # other three providers; the default "in-subnet" route plus a
    # default-internet-gateway route for anything not the shared VPC (GCP's
    # own reserved "default-internet-gateway" target).
    routes = [
        DiscoveredRoute(destination_cidr="10.50.0.0/14", target_type="local", target_ref="in-subnet"),
    ]
    if suffix != "shared-vpc":
        routes.append(DiscoveredRoute(
            destination_cidr="0.0.0.0/0", target_type="internet_gateway", target_ref="default-internet-gateway",
        ))
    return DiscoveredRouteTable(external_id=f"routes-{suffix}", name=f"{suffix}-routes", is_main=False, routes=routes)


class MockGCPProvider(CloudProvider):
    provider_name = "gcp"

    def discover_networks(self) -> list[DiscoveredNetwork]:
        networks = []
        for idx, suffix, cidr, region, subnet_count in _DEMO_VPCS:
            project = _DEMO_PROJECTS[idx]
            if project != self.account_identifier and self.account_identifier != "*":
                continue
            subnets = _subnets_for(cidr, subnet_count)
            networks.append(DiscoveredNetwork(
                external_id=f"vpc-{suffix}",
                name=f"vpc-{suffix}",
                cidr=cidr,
                region=region,
                account_identifier=project,
                subnets=subnets,
                tags={"ManagedBy": "netsphere-mock", "Environment": suffix.split("-")[0]},
                route_table=_route_table_for(suffix),
                interfaces=_interfaces_for(suffix, subnets),
            ))
        return networks

    def discover_circuits(self) -> list[DiscoveredCircuit]:
        return [
            DiscoveredCircuit(
                external_id=f"interconnect-{suffix}", name=f"Cloud Interconnect {suffix}", circuit_type="interconnect",
                vrf=vrf, bandwidth_mbps=bw, location=loc, status="active", attached_network_name=f"vpc-{vpc_suffix}",
                bgp_sessions=[DiscoveredBgpSession(
                    local_asn=local_asn, peer_asn=peer_asn, local_ip=local_ip, peer_ip=peer_ip,
                    external_id=f"interconnect-{suffix}-bgp",
                )],
            )
            for idx, suffix, vpc_suffix, vrf, bw, loc, local_asn, peer_asn, local_ip, peer_ip in _DEMO_INTERCONNECTS
            if _DEMO_PROJECTS[idx] == self.account_identifier or self.account_identifier == "*"
        ]

    @staticmethod
    def demo_accounts() -> list[str]:
        return list(_DEMO_PROJECTS)
