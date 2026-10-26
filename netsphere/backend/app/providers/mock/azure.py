"""Mock Azure provider — deterministic demo data, no network calls. Same
role as providers/mock/aws.py: proves the provider adapter pattern for a
second cloud without needing real Azure credentials.

Demo shape follows providers/mock/README.md's numbers for Azure: 3
subscriptions, 4 VNets total, 12 subnets total (3 per VNet, same per-VNet
count as the AWS mock's per-VPC count).
"""
from __future__ import annotations

from app.providers.base import CloudProvider, DiscoveredNetwork, DiscoveredSubnet

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


class MockAzureProvider(CloudProvider):
    provider_name = "azure"

    def discover_networks(self) -> list[DiscoveredNetwork]:
        networks = []
        for idx, suffix, cidr, region in _DEMO_VNETS:
            subscription = _DEMO_SUBSCRIPTIONS[idx]
            if subscription != self.account_identifier and self.account_identifier != "*":
                continue
            networks.append(DiscoveredNetwork(
                external_id=f"vnet-{suffix}",
                name=f"vnet-{suffix}",
                cidr=cidr,
                region=region,
                account_identifier=subscription,
                subnets=_subnets_for(cidr),
                tags={"ManagedBy": "netsphere-mock", "Environment": suffix.split("-")[0]},
            ))
        return networks

    @staticmethod
    def demo_accounts() -> list[str]:
        return list(_DEMO_SUBSCRIPTIONS)
