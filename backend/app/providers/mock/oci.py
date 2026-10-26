"""Mock OCI provider — deterministic demo data, no network calls. Same
role as providers/mock/aws.py: proves the provider adapter pattern for a
fourth cloud without needing real OCI credentials.

Demo shape follows providers/mock/README.md's numbers for OCI: 2
compartments, 3 VCNs total, 8 subnets total (uneven per-VCN counts).
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

# (compartment_index, circuit suffix, attached VCN suffix, VRF, bandwidth
# Mbps, colo location, local ASN, peer (on-prem) ASN, local/peer BGP IPs).
# One FastConnect circuit per compartment — same MPLS/VRF-per-cloud shape
# as the AWS/Azure/GCP mocks (see app/providers/mock/snmp.py for the
# matching on-prem-side circuit).
_DEMO_FASTCONNECTS = [
    (0, "ashburn-01", "prod-vcn", "vrf-prod", 1000, "Equinix DC2 - Ashburn", 65030, 31898, "169.254.30.1", "169.254.30.2"),
    (1, "ashburn-02", "shared-vcn", "vrf-shared", 500, "Equinix DC2 - Ashburn", 65030, 31898, "169.254.31.1", "169.254.31.2"),
]

_DEMO_COMPARTMENTS = ["ocid1.compartment.oc1..demoprod", "ocid1.compartment.oc1..demoshared"]

# (compartment_index, vcn_suffix, cidr, region, subnet_count)
_DEMO_VCNS = [
    (0, "prod-vcn", "10.60.0.0/16", "us-ashburn-1", 3),
    (0, "prod-vcn-uk", "10.61.0.0/16", "uk-london-1", 3),
    (1, "shared-vcn", "10.62.0.0/16", "us-ashburn-1", 2),
]


def _subnets_for(cidr_base: str, count: int) -> list[DiscoveredSubnet]:
    prefix = cidr_base.split(".")[0:2]
    return [
        DiscoveredSubnet(
            external_id=f"subnet-{prefix[0]}{prefix[1]}0{i}",
            cidr=f"{prefix[0]}.{prefix[1]}.{i}.0/24",
            availability_zone=f"{cidr_base.split('.')[0]}-ad-{i + 1}",
            name=f"subnet-{i + 1}",
        )
        for i in range(count)
    ]


def _interfaces_for(suffix: str, subnets: list[DiscoveredSubnet]) -> list[DiscoveredCloudInterface]:
    # One VNIC in the VCN's first subnet — OCI's own term is "VNIC",
    # attached to a stand-in Compute instance. security_groups here name
    # OCI's Network Security Groups (NSGs), OCI's closest equivalent.
    sub = subnets[0]
    ip = sub.cidr.rsplit(".", 1)[0] + ".6"
    return [
        DiscoveredCloudInterface(
            external_id=f"vnic-{suffix}-01", name=f"{suffix}-vnic01", subnet_external_id=sub.external_id,
            private_ip=ip, attached_to=f"{suffix}-app-01", status="in_use",
            security_groups=[f"{suffix}-nsg"],
        ),
    ]


def _route_table_for(suffix: str) -> DiscoveredRouteTable:
    # OCI VCNs get one default route table per VCN (subnets each reference
    # exactly one); the local/"within-VCN" rule plus a default route to an
    # internet gateway for anything not the shared VCN, mirroring the same
    # "prod gets a public route, shared doesn't" convention as the other
    # three mocks.
    routes = [
        DiscoveredRoute(destination_cidr="10.60.0.0/14", target_type="local", target_ref="local"),
    ]
    if suffix != "shared-vcn":
        routes.append(DiscoveredRoute(
            destination_cidr="0.0.0.0/0", target_type="internet_gateway", target_ref=f"ig-{suffix}",
        ))
    return DiscoveredRouteTable(
        external_id=f"ocid1.routetable.oc1..{suffix}", name=f"{suffix}-default-rt", is_main=True, routes=routes,
    )


class MockOCIProvider(CloudProvider):
    provider_name = "oci"

    def discover_networks(self) -> list[DiscoveredNetwork]:
        networks = []
        for idx, suffix, cidr, region, subnet_count in _DEMO_VCNS:
            compartment = _DEMO_COMPARTMENTS[idx]
            if compartment != self.account_identifier and self.account_identifier != "*":
                continue
            subnets = _subnets_for(cidr, subnet_count)
            networks.append(DiscoveredNetwork(
                external_id=f"vcn-{suffix}",
                name=f"vcn-{suffix}",
                cidr=cidr,
                region=region,
                account_identifier=compartment,
                subnets=subnets,
                tags={"ManagedBy": "netsphere-mock", "Environment": suffix.split("-")[0]},
                route_table=_route_table_for(suffix),
                interfaces=_interfaces_for(suffix, subnets),
            ))
        return networks

    def discover_circuits(self) -> list[DiscoveredCircuit]:
        return [
            DiscoveredCircuit(
                external_id=f"fastconnect-{suffix}", name=f"FastConnect {suffix}", circuit_type="fastconnect",
                vrf=vrf, bandwidth_mbps=bw, location=loc, status="active", attached_network_name=f"vcn-{vcn_suffix}",
                bgp_sessions=[DiscoveredBgpSession(
                    local_asn=local_asn, peer_asn=peer_asn, local_ip=local_ip, peer_ip=peer_ip,
                    external_id=f"fastconnect-{suffix}-bgp",
                )],
            )
            for idx, suffix, vcn_suffix, vrf, bw, loc, local_asn, peer_asn, local_ip, peer_ip in _DEMO_FASTCONNECTS
            if _DEMO_COMPARTMENTS[idx] == self.account_identifier or self.account_identifier == "*"
        ]

    @staticmethod
    def demo_accounts() -> list[str]:
        return list(_DEMO_COMPARTMENTS)
