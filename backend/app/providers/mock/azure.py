"""Mock Azure provider — deterministic demo data, no network calls. Same
role as providers/mock/aws.py: proves the provider adapter pattern for a
second cloud without needing real Azure credentials.

Demo shape follows providers/mock/README.md's numbers for Azure: 3
subscriptions, 4 VNets total, 12 subnets total (3 per VNet, same per-VNet
count as the AWS mock's per-VPC count).
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

# (subscription_index, circuit suffix, attached VNet suffix, VRF, bandwidth
# Mbps, colo location, local ASN, peer (on-prem) ASN, local/peer BGP IPs).
# One ExpressRoute circuit per subscription — same MPLS/VRF-per-cloud
# shape as the AWS mock's Direct Connects (see app/providers/mock/snmp.py
# for the matching on-prem-side circuit).
_DEMO_EXPRESSROUTES = [
    (0, "eastus-01", "prod-eastus", "vrf-prod", 1000, "Equinix DC2 - Ashburn", 65010, 12076, "169.254.10.1", "169.254.10.2"),
    (1, "westeu-01", "prod-westeu", "vrf-prod-eu", 1000, "Equinix LD5 - London", 65010, 12076, "169.254.11.1", "169.254.11.2"),
    (2, "shared-01", "shared-services", "vrf-shared", 500, "Equinix DC2 - Ashburn", 65010, 12076, "169.254.12.1", "169.254.12.2"),
]

# Fake-but-shaped-like-real subscription GUIDs.
_DEMO_SUBSCRIPTIONS = [
    "a1b2c3d4-0001-4000-8000-000000000001",
    "a1b2c3d4-0002-4000-8000-000000000002",
    "a1b2c3d4-0003-4000-8000-000000000003",
]

# (subscription_index, vnet_suffix, cidr, region)
_DEMO_VNETS = [
    (0, "prod-eastus", "172.16.0.0/16", "eastus"),
    (0, "staging-eastus", "172.17.0.0/16", "eastus"),
    (1, "prod-westeu", "172.18.0.0/16", "westeurope"),
    (2, "shared-services", "172.19.0.0/16", "eastus"),
]


def _subnets_for(cidr_base: str) -> list[DiscoveredSubnet]:
    # Three /24s per VNet, same pattern as the AWS mock — Azure doesn't
    # have AZs the same way, so these are named for Azure's own convention
    # (a numbered subnet within the VNet) rather than availability zones.
    prefix = cidr_base.split(".")[0:2]
    return [
        DiscoveredSubnet(
            external_id=f"subnet-{prefix[0]}{prefix[1]}0{i}",
            cidr=f"{prefix[0]}.{prefix[1]}.{i}.0/24",
            availability_zone=f"az{i + 1}",
            name=f"subnet-{i + 1}",
        )
        for i in range(3)
    ]


def _interfaces_for(suffix: str, subnets: list[DiscoveredSubnet]) -> list[DiscoveredCloudInterface]:
    # One NIC in the VNet's first subnet — Azure's own term is "network
    # interface" (NIC), attached to a stand-in VM.
    sub = subnets[0]
    ip = sub.cidr.rsplit(".", 1)[0] + ".4"
    return [
        DiscoveredCloudInterface(
            external_id=f"nic-{suffix}-01", name=f"{suffix}-nic01", subnet_external_id=sub.external_id,
            private_ip=ip, attached_to=f"vm-{suffix}-app01", status="in_use",
            security_groups=[f"{suffix}-nsg"],
        ),
    ]


def _route_table_for(suffix: str) -> DiscoveredRouteTable:
    # Azure route tables have no "main"/implicit-default concept the way
    # AWS does — every VNet gets an explicit user-defined route table here,
    # with Azure's own "VnetLocal" system route plus a default route toward
    # a virtual network gateway for anything that isn't the shared-services
    # hub itself.
    routes = [
        DiscoveredRoute(destination_cidr="172.16.0.0/12", target_type="local", target_ref="VnetLocal"),
    ]
    if suffix != "shared-services":
        routes.append(DiscoveredRoute(
            destination_cidr="0.0.0.0/0", target_type="vpn_gateway", target_ref=f"vgw-{suffix}",
        ))
    return DiscoveredRouteTable(external_id=f"rt-{suffix}", name=f"{suffix}-rt", is_main=False, routes=routes)


class MockAzureProvider(CloudProvider):
    provider_name = "azure"

    def discover_networks(self) -> list[DiscoveredNetwork]:
        networks = []
        for idx, suffix, cidr, region in _DEMO_VNETS:
            subscription = _DEMO_SUBSCRIPTIONS[idx]
            if subscription != self.account_identifier and self.account_identifier != "*":
                continue
            subnets = _subnets_for(cidr)
            networks.append(DiscoveredNetwork(
                external_id=f"vnet-{suffix}",
                name=f"vnet-{suffix}",
                cidr=cidr,
                region=region,
                account_identifier=subscription,
                subnets=subnets,
                tags={"ManagedBy": "netsphere-mock", "Environment": suffix.split("-")[0]},
                route_table=_route_table_for(suffix),
                interfaces=_interfaces_for(suffix, subnets),
            ))
        return networks

    def discover_circuits(self) -> list[DiscoveredCircuit]:
        return [
            DiscoveredCircuit(
                external_id=f"er-{suffix}", name=f"ExpressRoute {suffix}", circuit_type="expressroute",
                vrf=vrf, bandwidth_mbps=bw, location=loc, status="active", attached_network_name=f"vnet-{vnet_suffix}",
                bgp_sessions=[DiscoveredBgpSession(
                    local_asn=local_asn, peer_asn=peer_asn, local_ip=local_ip, peer_ip=peer_ip,
                    external_id=f"er-{suffix}-bgp",
                )],
            )
            for idx, suffix, vnet_suffix, vrf, bw, loc, local_asn, peer_asn, local_ip, peer_ip in _DEMO_EXPRESSROUTES
            if _DEMO_SUBSCRIPTIONS[idx] == self.account_identifier or self.account_identifier == "*"
        ]

    @staticmethod
    def demo_accounts() -> list[str]:
        return list(_DEMO_SUBSCRIPTIONS)
